# serviceui/service_win.py
"""
Service-Kontrollfenster für PyTrader.
Steuert den Historical Scanner (Full-Scan / Delta-Update) über ein separates Fenster.
Mit automatischem State Persistence via PersistentWindow.

Phase 13 Schritt 4: Zusätzlich Service-Set-Verwaltung (ServiceSetRepository +
ServiceSetEvaluator): Set-Auswahl (list_sets()), execution_order-Anzeige mit
Up/Down-Umsortierung, Name (leer → Auto-Name), Speichern/Löschen (mit
QMessageBox-Rückfrage) und Ausführen (ServiceSetEvaluator im Hintergrund).

Phase 15 Kapitel 15.1 (U15-D1): Modularisierung – die gewachsene Datei wurde
in den Unterordner serviceui/ verschoben und in Module zerlegt (Verhalten
unverändert):
  * service_set_utils.py   – _available_plugin_ids, _sets_using_plugin
  * set_run_worker.py      – ServiceSetRunWorker (QThread)
  * set_item_adapter.py    – ServiceSetItemAdapter (NamedItemAdapter)
  * param_columns.py       – ServiceParamColumnsMixin (Parameter-Column-Builder)
  * trash_dialog.py        – ServiceSetTrashDialog (Papierkorb-Dialog)
Diese Datei re-exportiert die öffentliche API, damit bestehende Aufrufe
(main.py, Tests) weiter funktionieren.
"""

from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QFile, QIODevice, QTimer, Qt, Slot
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QSplitter, QTextEdit,
    QVBoxLayout, QWidget,
)

# P15-Bugfix: shiboken6.isValid() schuetzt vor dem Zugriff auf bereits
# C++-seitig zerstoerte Qt-Objekte (Access Violation 0xC0000005 bei wildem
# Klicken, wenn z.B. Controls per deleteLater entfernt werden).
try:
    from shiboken6 import isValid as _qt_valid
except ImportError:  # pragma: no cover
    def _qt_valid(obj) -> bool:  # type: ignore
        return obj is not None

from analytics.background_workers.historical_scanner import HistoricalScanner
from analytics.engine.description_dialog import ServiceDescriptionDialog
from analytics.engine.service_set_repository import ServiceSetRepository
from analytics.engine.set_evaluator import ServiceSetEvaluator
from persistent_win import PersistentWindow, register_persistent_window
from scrollable_content import ContentScrollMixin
from chart.widgets.named_item_actions import NamedItemActionsMixin

# Phase 15 U15-D1: Submodule der Service-UI
from serviceui.service_set_utils import _available_plugin_ids, _sets_using_plugin
from serviceui.set_run_worker import ServiceSetRunWorker
from serviceui.set_item_adapter import ServiceSetItemAdapter, _ServiceSetItemAdapter
from serviceui.param_columns import ServiceParamColumnsMixin
from serviceui.trash_dialog import ServiceSetTrashDialog
from serviceui.new_set_dialog import NewServiceSetDialog
# 05.08.2026: Gezielter Run-Worker fuer die MasterTree-Kontextmenue-Aktionen
# ('▶️ Diesen Service ausführen' / '▶️ Alle Services ausführen') – persistiert
# den feature_store_payload und emittiert den EventBus (Datum live im Baum).
# U15-E (05.08.2026): ALL_TIMEFRAMES = Sentinel fuer Multi-TF-Ausfuehrung.
from serviceui.run_worker import ALL_TIMEFRAMES, ServiceRunWorker

# Phase 15 15.01: Symbol- & Favoriten-Verwaltung (SymbolsWindow + EventBus)
from serviceui.symbols_win import SymbolsWindow
from symbol_repository import SymbolRepository, get_symbol_repository
from config.event_bus import event_bus

# Phase 15 15.02: Service-UI Refactoring – MasterTree & generischer
# ServiceSelector (ServiceSelectorWidget im Modus FULL_EDIT).
from serviceui.service_selector_widget import ServiceSelectorWidget

# Projekt-Root (eine Ebene über serviceui/) – für die UI-Datei unter ui/.
BASE_DIR = Path(__file__).resolve().parent.parent


@register_persistent_window()
class ServiceWindow(ServiceParamColumnsMixin, ContentScrollMixin, NamedItemActionsMixin, PersistentWindow):
    INSTANCE_ID = "win_service"
    # Bugfix 04.08.2026 (Fenster-Historie): auto_restore=True – wie chart_win
    # wird das ServiceWindow beim App-Start wiederhergestellt, wenn es beim
    # Beenden der App OFFEN war (Geometrie/Position werden dann restauriert).
    # _keep_history_on_close bleibt Default (False): ein MANUELL geschlossenes
    # Fenster wird aus der aktiven History entfernt (delete_instance) und
    # poppt beim naechsten Start NICHT wieder auf.

    def __init__(self, parent=None, service_set_repo: Optional[ServiceSetRepository] = None):
        super().__init__(parent)
        self.scanner: Optional[HistoricalScanner] = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_seconds = 0
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        # Phase 13 Schritt 4: Service-Set-Verwaltung
        self.set_repo: ServiceSetRepository = service_set_repo or ServiceSetRepository()
        self.set_evaluator = ServiceSetEvaluator()
        self._set_run_worker: Optional[ServiceSetRunWorker] = None
        # 05.08.2026: Worker fuer die gezielte Kontextmenue-Ausfuehrung
        # (MasterTree '▶️ Service(s) ausführen') – FeatureStore-Persistenz.
        self._run_worker: Optional[ServiceRunWorker] = None
        self._current_set_id: Optional[str] = None
        self._current_set_definition: Optional[Dict[str, Any]] = None
        # USER-REQ (P14-03): Preisskala-Praezision je Symbol fuer die 6
        # Custom-Level-Eingabefelder (prox_level1..6). Lazy + gecacht.
        self._symbol_precision: Optional[int] = None

        # Phase 13 Schritt 8: Service-Set-Adapler für die generische
        # Neu-/Speichern-/Löschen-Mechanik (NamedItemActionsMixin) – exakt
        # analog zur Preset-Verwaltung im Indikator-Prop-Fenster.
        self._set_adapter = _ServiceSetItemAdapter(self)

        # UI laden
        ui_file = QFile(str(BASE_DIR / "ui" / "service_win.ui"))
        if ui_file.open(QIODevice.ReadOnly):
            loader = QUiLoader()
            self.ui = loader.load(ui_file)
            ui_file.close()
            self.setCentralWidget(self.ui)
        else:
            self.ui = QWidget(self)
            self.setCentralWidget(self.ui)

        self.setWindowTitle("PyTrader - Service Kontrolle")

        # Controls
        self.combo_symbol: QComboBox = self.ui.findChild(QComboBox, "combo_symbol")
        self.check_new_scan: QCheckBox = self.ui.findChild(QCheckBox, "check_new_scan")
        self.btn_start: QPushButton = self.ui.findChild(QPushButton, "btn_start_scan")
        self.label_elapsed: QLabel = self.ui.findChild(QLabel, "label_elapsed_value")
        self.progress_bar: QProgressBar = self.ui.findChild(QProgressBar, "progress_bar")
        self.text_log: QTextEdit = self.ui.findChild(QTextEdit, "text_log")

        # Phase 13 Schritt 4: Service-Set-Controls
        self.combo_set: QComboBox = self.ui.findChild(QComboBox, "combo_set")
        self.combo_tf_set: QComboBox = self.ui.findChild(QComboBox, "combo_tf_set")
        # 05.08.2026 (U15-E): Timeframe-Control in der Filterleiste (neben dem
        # Symbol-Dropdown) – steuert die gezielte Kontextmenue-Ausfuehrung
        # (MasterTree '▶️ Service(s) ausführen'). 'ALLE Timeframes' (Index 0,
        # Sentinel ALL_TIMEFRAMES) fuehrt alle verfuegbaren Timeframes aus.
        self.combo_tf: QComboBox = self.ui.findChild(QComboBox, "combo_tf")
        self.btn_refresh_sets: QPushButton = self.ui.findChild(QPushButton, "btn_refresh_sets")
        self.edit_set_name: QLineEdit = self.ui.findChild(QLineEdit, "edit_set_name")
        # Phase 14 P14-01: Set-Beschreibung + Info-Button (ServiceDescriptionDialog)
        self.edit_set_description: Optional[QLineEdit] = self.ui.findChild(QLineEdit, "edit_set_description")
        self.btn_info_service: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_info_service")
        self.list_execution_order: QListWidget = self.ui.findChild(QListWidget, "list_execution_order")
        self.btn_move_up: QPushButton = self.ui.findChild(QPushButton, "btn_move_up")
        self.btn_move_down: QPushButton = self.ui.findChild(QPushButton, "btn_move_down")
        self.btn_remove_instance: QPushButton = self.ui.findChild(QPushButton, "btn_remove_instance")
        self.edit_new_instance: QLineEdit = self.ui.findChild(QLineEdit, "edit_new_instance")
        self.btn_add_instance: QPushButton = self.ui.findChild(QPushButton, "btn_add_instance")
        # Phase 14 P14-02: Hot-Reload-Button für Custom-Plugins
        self.btn_reload_plugins: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_reload_plugins")
        # Phase 13 Schritt 6-Korrektur: Dropdown mit ALLEN verfügbaren Services
        self.combo_plugin_select: Optional[QComboBox] = self.ui.findChild(QComboBox, "combo_plugin_select")
        self.btn_save_set: QPushButton = self.ui.findChild(QPushButton, "btn_save_set")
        self.btn_delete_set: QPushButton = self.ui.findChild(QPushButton, "btn_delete_set")
        # Phase 14 P14-05: Papierkorb-Button (Soft-Delete/Wiederherstellung)
        self.btn_trash_sets: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_trash_sets")
        self.btn_execute_set: QPushButton = self.ui.findChild(QPushButton, "btn_execute_set")

        # Phase 13 5.4 Schritt 1: Dynamische Service-Spalten (Breite/Höhe aus
        # dem Inhalt – KEINE fixen Pixelwerte). Das Inhalt-Layout erhält
        # SetFixedSize + AlignTop|AlignLeft: Das Fenster wächst mit der Anzahl
        # der Spalten nach rechts und beim Ausklappen der Experten-Optionen
        # nach unten – ohne leeren Raum (Roadmap 5.4.2.2 Punkt 3).
        #
        # WICHTIG: Der Spalten-Container wird IM CODE erzeugt (nicht per
        # QUiLoader). Das QWidgetItem QUiLoader-erzeugter Widgets meldet nach
        # einer späteren Layout-Änderung einen veralteten sizeHint (Qt-Quirk:
        # 18x18 bzw. alter Gruppenstand), wodurch die Fensterbreite nicht mit
        # der Spaltenanzahl wachsen würde. Im Code erzeugte Widgets (wie die
        # Spalten selbst) werden korrekt weitergereicht.
        self.group_service_sets: Optional[QGroupBox] = self.ui.findChild(QGroupBox, "group_service_sets")
        self.widget_service_columns = QGroupBox("Service-Parameter")
        self.widget_service_columns.setObjectName("widget_service_columns")
        self.service_columns_layout = QHBoxLayout(self.widget_service_columns)
        self.service_columns_layout.setSpacing(6)
        # Inhalt-Widget + Layout VOR dem Scroll-Wrapper referenzieren
        # (install_content_scroll ersetzt das CentralWidget von self.ui).
        self.content_widget = self.ui.centralWidget()
        self.central_layout = self.content_widget.layout() if self.content_widget else None
        if self.central_layout is not None:
            # Phase 15 15.02 (Orchestrator): QSplitter-Zusammensetzung.
            #  * Links:  bestehender Set-Editor + dynamische Service-Spalten.
            #  * Rechts: MasterTree (2-Spalten-Hierarchie, Live-Status-Badges,
            #            ServiceSelectorWidget im Modus FULL_EDIT).
            self.top_row = QHBoxLayout()
            self.top_row.setSpacing(6)
            idx = self.central_layout.indexOf(self.group_service_sets)
            if idx < 0:
                idx = 0
            self.central_layout.removeWidget(self.group_service_sets)

            self._editor_panel = QWidget()
            editor_layout = QVBoxLayout(self._editor_panel)
            editor_layout.setContentsMargins(0, 0, 0, 0)
            editor_layout.setSpacing(6)
            editor_layout.addWidget(self.group_service_sets)
            editor_layout.addWidget(self.widget_service_columns)

            self.right_panel = QWidget()
            right_layout = QVBoxLayout(self.right_panel)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(6)
            # MasterTree im Modus B / FULL_EDIT (seit 05.08.2026 ohne Toolbar)
            self.service_selector = ServiceSelectorWidget(
                mode=ServiceSelectorWidget.MODE_FULL_EDIT, parent=self)
            right_layout.addWidget(self.service_selector, 1)

            self.main_splitter = QSplitter(Qt.Horizontal)
            self.main_splitter.addWidget(self._editor_panel)
            self.main_splitter.addWidget(self.right_panel)
            self.main_splitter.setStretchFactor(0, 3)
            self.main_splitter.setStretchFactor(1, 2)

            self.top_row.addWidget(self.main_splitter)
            self.central_layout.insertLayout(idx, self.top_row)
        # Fenstergroesse (15.02): 1280 x 800 als Default – Single Source of
        # Truth ist die ui/service_win.ui-Geometrie (der QUiLoader wendet sie
        # beim Laden an). KEIN resize()-Aufruf im Code: der 5.4-Content-Reflow
        # (resize_to_clamped_content) darf die Groesse weiterhin inhalt- und
        # bildschirmbasiert anpassen (keine fixen Pixel im Quellcode).
        # Scroll-Wrapper: gesamtes Fenster scrollbar, wenn Inhalt > Bildschirm
        # (ContentScrollMixin). Der Inhalt behält seine natürliche Größe; das
        # Fenster wird auf den Bildschirm geklemmt (Scrollbars erscheinen erst,
        # wenn der Inhalt den Viewport übersteigt).
        self.install_content_scroll(self.content_widget, install_to=self.ui)
        self.main_layout = self.ui.layout()
        # KEIN SetFixedSize auf dem QMainWindowLayout: das würde die
        # Fenstergröße auf den Inhalt fixieren und das Bildschirm-Cap
        # (setMaximumSize) überschreiben. Auch das INHALT-Layout bekommt KEIN
        # SetFixedSize: QLayout.SetFixedSize ruft setFixedSize() auf dem
        # Inhalt-Widget auf und fixiert es auf die ERSTE Layout-Größe – späteres
        # Wachstum (Service-Spalten, Experten-Optionen) wäre dadurch blockiert.
        # Stattdessen setzt resize_to_clamped_content() das Inhalt-Widget in
        # jedem Reflow explizit auf die aktuelle Layout-Größe (ContentScrollMixin).
        if self.central_layout is not None:
            self.central_layout.setSpacing(6)
            self.central_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._service_param_controls: Dict[Any, QWidget] = {}
        # Phase 14 P14-01: Beschreibungs-Eingabefelder der Service-Instanzen
        self._service_desc_controls: Dict[str, QWidget] = {}

        if self.btn_start:
            self.btn_start.clicked.connect(self.start_scan)

        # Phase 13 Schritt 4: Service-Set-Signale
        if self.combo_set:
            self.combo_set.currentIndexChanged.connect(self._on_set_selected)
        if self.btn_refresh_sets:
            self.btn_refresh_sets.clicked.connect(self.refresh_set_list)
        if self.btn_move_up:
            self.btn_move_up.clicked.connect(lambda: self.move_order_item(-1))
        if self.btn_move_down:
            self.btn_move_down.clicked.connect(lambda: self.move_order_item(1))
        if self.btn_remove_instance:
            self.btn_remove_instance.clicked.connect(self.remove_instance)
        # Phase 14 P14-01: Info-Button + itemClicked-Selektion der Instanzliste
        self._current_list_iid: Optional[str] = None
        if self.list_execution_order:
            self.list_execution_order.itemClicked.connect(self._on_order_item_clicked)
            self.list_execution_order.itemSelectionChanged.connect(self._sync_list_selection)
        if self.btn_info_service:
            self.btn_info_service.clicked.connect(self._show_service_info)
        if self.btn_add_instance:
            self.btn_add_instance.clicked.connect(self.add_instance)
            if self.edit_new_instance:
                self.edit_new_instance.returnPressed.connect(self.add_instance)
        if self.btn_save_set:
            self.btn_save_set.clicked.connect(self.save_set)
        if self.btn_delete_set:
            self.btn_delete_set.clicked.connect(self.delete_set)
        # Phase 14 P14-05: Papierkorb-Dialog (Soft-Delete)
        if self.btn_trash_sets:
            self.btn_trash_sets.clicked.connect(self.show_trash_dialog)
        if self.btn_execute_set:
            self.btn_execute_set.clicked.connect(self.execute_set)

        # U15-D2 (Bedien-Feinschliff): Log-Kontextmenü (Kopieren / Log leeren)
        # + Auto-Scroll ans Ende in log() – siehe _on_log_context_menu().
        if self.text_log:
            self.text_log.setContextMenuPolicy(Qt.CustomContextMenu)
            self.text_log.customContextMenuRequested.connect(self._on_log_context_menu)

        # Sofort speichern bei Symbol-Änderung
        if self.combo_symbol:
            self.combo_symbol.currentTextChanged.connect(self.save_state)
            # USER-REQ: Preisskala-Praezision ist je Symbol fix – beim
            # Symbol-Wechsel Cache invalidieren + Spalten neu bauen.
            self.combo_symbol.currentTextChanged.connect(self._on_symbol_changed)
        # U15-E (05.08.2026): Timeframe-Control (Filterleiste) ebenfalls sofort
        # speichern – get_persistent_timeframe() liest combo_tf.
        if self.combo_tf:
            self.combo_tf.currentTextChanged.connect(self.save_state)

        # Phase 15 15.01: Favoriten-Symbol-Verwaltung.
        # ★-Button rechts neben der Symbol-ComboBox oeffnet das nicht-modale
        # SymbolsWindow (Favoriten verwalten). Das Symbol-Dropdown zeigt nur
        # Favoriten (is_favorite == True) und wird ueber den EventBus bei
        # jeder Favoriten-Aenderung neu befuellt (Entkopplung, kein direktes
        # Fenster-Wissen).
        self._symbol_repo: SymbolRepository = get_symbol_repository()
        self.btn_symbol_fav: QPushButton = QPushButton("★", self.ui)
        self.btn_symbol_fav.setObjectName("btn_symbol_fav")
        self.btn_symbol_fav.setToolTip(
            "Favoriten verwalten – oeffnet das Symbol-Fenster. "
            "Das Symbol-Dropdown zeigt nur Favoriten.")
        self.btn_symbol_fav.setFixedWidth(32)
        layout_symbol = self.ui.findChild(QHBoxLayout, "layout_symbol")
        if layout_symbol is not None and self.combo_symbol is not None:
            idx = layout_symbol.indexOf(self.combo_symbol)
            layout_symbol.insertWidget(idx + 1, self.btn_symbol_fav)
        self.btn_symbol_fav.clicked.connect(self.open_symbols_window)
        # EventBus: Favoriten-Aenderungen -> ComboBox neu befuellen
        event_bus.favorites_changed.connect(self._refresh_symbol_combo)
        self._refresh_symbol_combo()

        # U15-E (05.08.2026): Timeframe-Dropdown der Filterleiste befuellen –
        # 'ALLE Timeframes' (Index 0) + alle Timeframes aus get_timeframes().
        self._refresh_timeframe_combo()

        # Set-Dropdown initial befüllen (list_sets() als Quelle)
        self.refresh_set_list()

        # Phase 13 Schritt 6-Korrektur: Verfügbare Services sichtbar machen –
        # der Platzhalter im Eingabefeld zeigt jetzt grid_lines + proximity
        # (die neuen Services aus Schritt 6) statt nur grid_liquidity.
        if self.edit_new_instance:
            self.edit_new_instance.setPlaceholderText(
                "instance_id [plugin_id]  z.B. grid_1 [grid_lines] oder prox_1 [proximity]"
            )
        # Dropdown listet ALLE registrierten Services (grid_lines, grid_liquidity,
        # proximity). Auswahl füllt das Instanz-Feld vor ("plugin_id [plugin_id]").
        if self.combo_plugin_select:
            from analytics.features.feature_builder import PluginRegistry
            for pid in sorted(PluginRegistry().plugins.keys()):
                self.combo_plugin_select.addItem(pid, pid)
            self.combo_plugin_select.currentTextChanged.connect(self._on_plugin_select_changed)
        # Phase 14 P14-02: Hot-Reload der Custom-Plugins (data/custom_plugins/)
        if self.btn_reload_plugins:
            self.btn_reload_plugins.clicked.connect(self.reload_plugins)

        # Phase 15 15.02: MasterTree/ServiceSelector (FULL_EDIT) verdrahten –
        # Kontextmenue-Aktionen auf die bestehenden Set-Methoden + EventBus-
        # Sync. Die fruehere Aktions-Toolbar oberhalb des Baums ist entfernt
        # (05.08.2026) – der MasterTree hat die volle vertikale Hoehe.
        self._wire_selector_toolbar()

        self.log(f"Verfügbare Plugins: {_available_plugin_ids()}")

        # State asynchron wiederherstellen (nach show(), damit move/resize vom Window-Manager akzeptiert werden)
        QTimer.singleShot(0, self.restore_state)

    # --- PersistentWindow-Interface ---

    def get_persistent_symbol(self) -> str:
        return self.combo_symbol.currentText() if self.combo_symbol else "SILVER"

    def get_persistent_timeframe(self) -> str:
        """Liefert den aktuell gewaehlten Timeframe der Filterleiste (combo_tf).

        05.08.2026 (U15-E): 'ALLE Timeframes' ist eine reguläre, persistierbare
        Auswahl (Sentinel ALL_TIMEFRAMES) – save_state() speichert sie 1:1,
        damit beim naechsten Oeffnen exakt derselbe Modus wiederhergestellt
        wird. Fallback: "H1", wenn kein Control existiert.
        """
        if self.combo_tf:
            tf = self.combo_tf.currentText()
            if tf:
                return tf
        return "H1"

    def _apply_persistent_filters(self, symbol: str, timeframe: str) -> None:
        if self.combo_symbol:
            idx = self.combo_symbol.findText(symbol)
            if idx >= 0:
                self.combo_symbol.setCurrentIndex(idx)
        # U15-E: Timeframe der Filterleiste wiederherstellen (inkl. Sentinel
        # 'ALLE Timeframes' – findText trifft den exakten Eintrag).
        if self.combo_tf and timeframe:
            idx = self.combo_tf.findText(timeframe)
            if idx >= 0:
                self.combo_tf.setCurrentIndex(idx)

    def _refresh_timeframe_combo(self) -> None:
        """Befuellt das Timeframe-Control der Filterleiste (U15-E).

        Index 0 ist der Sentinel 'ALLE Timeframes' (Multi-TF-Ausfuehrung),
        danach folgen alle Timeframes aus db_service.get_timeframes()
        (MN1..M1). Fallback bei nicht verfuegbarem MT5: TF_SECONDS_MAP bzw.
        eine Basisliste. Die aktuelle Auswahl bleibt erhalten, sofern sie
        noch existiert; Default ist 'M1'.
        """
        if not self.combo_tf:
            return
        try:
            from db_service import TF_SECONDS_MAP, get_timeframes
            try:
                tfs = list(get_timeframes().keys())
            except Exception:
                tfs = list(TF_SECONDS_MAP.keys())
        except Exception:
            tfs = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
        current = self.combo_tf.currentText()
        self.combo_tf.blockSignals(True)
        self.combo_tf.clear()
        self.combo_tf.addItem(ALL_TIMEFRAMES)
        for tf in tfs:
            if tf != ALL_TIMEFRAMES:
                self.combo_tf.addItem(tf)
        idx = self.combo_tf.findText(current)
        if idx < 0:
            idx = self.combo_tf.findText("M1")
        self.combo_tf.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_tf.blockSignals(False)

    def _on_symbol_changed(self, symbol: str) -> None:
        """USER-REQ: Preisskala-Praezision ist je Symbol fix. Beim Symbol-
        Wechsel wird der Precision-Cache invalidiert und – falls ein Set
        aktiv ist – die Service-Spalten neu aufgebaut, damit die 6
        Custom-Level-Felder (prox_level1..6) die neue Preisskala-Praezision
        des Symbols anzeigen."""
        self._symbol_precision = None
        if (self.combo_set is not None and self.combo_set.currentIndex() >= 0
                and self.service_columns_layout is not None):
            self._rebuild_columns()

    # --- Phase 15 15.02: MasterTree / ServiceSelector (FULL_EDIT) ---

    def _wire_selector_toolbar(self) -> None:
        """Verdrahtet den ServiceSelectorWidget (Modus FULL_EDIT) mit den
        bestehenden Set-Methoden (add/move/remove/rename).

        05.08.2026 (CRUD-Buttons entfernt): Die Aktions-Toolbar oberhalb des
        MasterTrees (btn_add/btn_remove/Order-Pfeile) ist ersatzlos aus der
        UI und aus allen Event-Verbindungen entfernt – alle Struktur-Aktionen
        und die neuen Run-Aktionen laufen ueber das MasterTree-Kontextmenue
        (entkoppelte Signale, DRY: dieselben Handler wie zuvor)."""
        selector = getattr(self, "service_selector", None)
        if selector is None or selector.master_tree is None:
            return
        tree = selector.master_tree
        # MasterTree-Auswahl + Kontextmenue (entkoppelt) -> Editor/Handler
        tree.selection_changed.connect(self._on_master_selection)
        # Bugfix 05.08.2026: Info-Button-Klicks (Spalte 1) -> Beschreibungs-
        # Dialog (Service / Plugin / Set).
        tree.info_requested.connect(self._on_tree_info_requested)
        # Kontextmenue-Aktionen (Rechtsklick im Baum).
        tree.create_set_requested.connect(self._on_add_set)
        tree.rename_set_requested.connect(self._on_rename_set)
        tree.add_set_service_requested.connect(self._on_add_set_service)
        tree.delete_set_requested.connect(self._on_delete_set)
        tree.move_service_requested.connect(self._on_move_service)
        tree.remove_service_requested.connect(self._on_remove_service)
        tree.purge_trash_requested.connect(self._on_purge_trash)
        # 05.08.2026: Gezielte Ausfuehrung ('▶️ Diesen Service ausführen' /
        # '▶️ Alle Services ausführen') -> ServiceRunWorker mit Sicherheits-
        # abfrage (Set/Service + aktives Symbol/Timeframe) + FeatureStore-
        # Persistenz + EventBus-Sync.
        tree.run_service_requested.connect(self._on_run_service)
        tree.run_set_requested.connect(self._on_run_set)

    @Slot(str)
    def _toolbar_add_service(self, plugin_id: str) -> None:
        """Uebernimmt die Popup-Auswahl ins Instanz-Feld und fuegt den
        Service zum aktiven Set hinzu (add_instance)."""
        if not plugin_id:
            return
        if self.edit_new_instance:
            self.edit_new_instance.setText(f"{plugin_id} [{plugin_id}]")
        self.add_instance()

    @Slot(str, str)
    def _on_master_selection(self, set_id: str, service_id: str) -> None:
        """Synchronisiert Editor (Set-Combo/Liste) mit der
        MasterTree-Auswahl.

        P15-Bugfix: isValid-Guards – bei wildem Klicken koennen combo_set /
        list_execution_order waehrend des Handlers neu aufgebaut werden
        (setCurrentIndex -> _on_set_selected -> load_set_into_editor); der
        Zugriff auf geloeschte Items wuerde sonst crashen (0xC0000005).
        """
        try:
            if set_id and self.combo_set is not None and _qt_valid(self.combo_set):
                idx = self.combo_set.findData(set_id)
                if idx >= 0 and self.combo_set.currentData() != set_id:
                    self.combo_set.setCurrentIndex(idx)
        except (RuntimeError, AttributeError):
            pass
        if service_id and self.list_execution_order is not None:
            try:
                if not _qt_valid(self.list_execution_order):
                    return
                for i in range(self.list_execution_order.count()):
                    item = self.list_execution_order.item(i)
                    if item is None or not _qt_valid(item):
                        continue
                    if item.data(Qt.UserRole) == service_id:
                        self.list_execution_order.setCurrentRow(i)
                        self._current_list_iid = service_id
                        break
            except (RuntimeError, AttributeError):
                pass

    # -------------------------------------------------------------------------
    # 05.08.2026: Gezielte Kontextmenue-Ausfuehrung (Service(s) ausfuehren)
    # -------------------------------------------------------------------------

    def _start_run_worker(self, scope_id: str, set_definition: Dict[str, Any],
                          instance_id: Optional[str]) -> None:
        """Startet den gezielten ServiceRunWorker (Single/Set) im Hintergrund.

        * Laedt OHLCV nur fuer das aktive Symbol + den gewaehlten Timeframe
          (FeatureBuilder.load_ohlcv) – KEIN globaler Massen-Scan.
        * Fuehrt die Pipeline via ServiceSetEvaluator.execute_set() aus und
          persistiert die erzeugten feature_store_payloads ZWINGEND in
          analytics.duckdb (feature_store, FeatureBuilder.store_plugin_payload).
        * Der Worker emittiert nach Abschluss `event_bus.service_set_changed`
          – alle ServiceSelectorModel-Instanzen (MasterTree, Analytics, ...)
          aktualisieren dadurch live das Ausfuehrungsdatum '(DD.MM.JJ)'.
        """
        if self._run_worker and self._run_worker.isRunning():
            self.log("Service-Ausführung läuft bereits.")
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E (05.08.2026): Timeframe-Control der Filterleiste (combo_tf) –
        # 'ALLE Timeframes' startet die Multi-TF-Ausfuehrung im Worker.
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        self._run_worker = ServiceRunWorker(
            self.set_evaluator, symbol, timeframe, set_definition,
            instance_id=instance_id, parent=self,
        )
        self._run_worker.log_message.connect(self.log)
        self._run_worker.run_finished.connect(self._on_run_worker_finished)
        self._run_worker.run_failed.connect(self._on_run_worker_failed)
        self._run_worker.start()

    @Slot(str, str)
    def _on_run_service(self, set_id: str, service_id: str) -> None:
        """'▶️ Diesen Service ausführen' (MasterTree-Kontextmenue).

        Sicherheitsabfrage mit Set-/Service-Name und dem aktuell gewaehlten
        Symbol/Timeframe, danach gezielter Single-Run (inkl. Upstream-
        Abhaengigkeiten im Set, damit z.B. proximity seine Linien hat).
        """
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Ausführung abgebrochen.")
            return
        if service_id not in (definition.get("services") or {}):
            self.log(f"Service '{service_id}' nicht im Set '{set_id}'.")
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Zeitachsen-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        set_name = str(definition.get("display_name") or set_id)
        reply = QMessageBox.question(
            self, "Service ausführen",
            f"Service '{service_id}' aus dem Set '{set_name}' ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Der erzeugte Feature-Store-Payload wird in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen.")
            return
        self._start_run_worker(service_id, definition, instance_id=service_id)

    @Slot(str)
    def _on_run_set(self, set_id: str) -> None:
        """'▶️ Alle Services ausführen' (MasterTree-Kontextmenue).

        Sicherheitsabfrage mit Set-Name und dem aktuell gewaehlten
        Symbol/Timeframe, danach gezielter Set-Run (nur dieses Set).
        """
        if not set_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Ausführung abgebrochen.")
            return
        if not definition.get("execution_order"):
            self.log(f"Set '{set_id}' hat keine Services – Ausführung abgebrochen.")
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Zeitachsen-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        set_name = str(definition.get("display_name") or set_id)
        count = len(definition.get("execution_order") or [])
        reply = QMessageBox.question(
            self, "Set ausführen",
            f"Alle Services ({count}) des Sets '{set_name}' ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Die erzeugten Feature-Store-Payloads werden in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen.")
            return
        self._start_run_worker(set_id, definition, instance_id=None)

    @Slot(str, int)
    def _on_run_worker_finished(self, scope_id: str, stored: int) -> None:
        """Loggt den Abschluss des gezielten Runs (FeatureStore-Persistenz).

        Der EventBus-Sync erfolgt bereits im Worker (service_set_changed) –
        das ServiceSelectorModel hat dadurch das neue MAX(created_at) gelesen
        und der MasterTree zeigt das Datum '(DD.MM.JJ)' live an.
        """
        self.log(f"Ausführung abgeschlossen: {stored} Feature-Row(s) im "
                 f"feature_store gespeichert ({scope_id}).")

    @Slot(str, str)
    def _on_run_worker_failed(self, scope_id: str, error: str) -> None:
        self.log(f"FEHLER bei Ausführung ({scope_id}): {error}")

    def _persist_current_set(self, action: str) -> None:
        """Persistiert das aktuell geladene Service-Set zurueck in die DB.

        Bugfix 05.08.2026: Struktur-Aenderungen (add/move/remove) werden
        SOFORT gespeichert (P14-05: Snapshot beim Ueberschreiben) und der
        EventBus emittiert `service_set_changed` – alle ServiceSelectorModel-
        Instanzen (MasterTree, Analytics, ...) aktualisieren live. Verwaiste
        services-Konfigurationen (nicht mehr in execution_order) werden dabei
        bereinigt. Nur Sets MIT set_id werden persistiert (ein neues, noch
        ungespeichertes Set lebt bis zum expliziten 'Speichern' im Editor).
        """
        if not self._current_set_id:
            return
        try:
            definition = self.collect_set_definition()
            order = definition.get("execution_order") or []
            services = definition.get("services") or {}
            definition["services"] = {
                iid: cfg for iid, cfg in services.items() if iid in order
            }
            self.set_repo.save_set(definition)
            event_bus.service_set_changed.emit()
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets ({action}): {e}")

    def _plugin_belongs_to_indicator(self, plugin_id: str) -> bool:
        """True, wenn der Service einem Indikator zugeordnet ist
        (metadata['indicator_id']/['indicator_name']).

        Bugfix 05.08.2026: Grundlage der entschaerften P14-04-Sperre –
        nur Indikator-Services sind ueber die 'letztes Vorkommen'-Regel
        geschuetzt, freie Services sind immer loeschbar.
        """
        try:
            model = getattr(getattr(self, "service_selector", None),
                            "model", None)
            if model is not None:
                return bool(model.belongs_to_indicator(plugin_id))
        except (RuntimeError, AttributeError):
            pass
        return False

    def _remaining_sets_with_plugin(self, plugin_id: str,
                                    exclude_set_id: Optional[str]) -> list:
        """GESPEICHERTE Sets (ohne exclude_set_id), die einen Service mit
        plugin_id enthalten – Basis der P14-04-Sperre (Bugfix 05.08.2026:
        Entfernen/Loeschen erlaubt, solange ein gueltiges Set fuer den
        Indikator erhalten bleibt)."""
        return [
            s for s in self.set_repo.list_sets()
            if s.get("set_id") != exclude_set_id
            and any((cfg or {}).get("plugin_id") == plugin_id
                    for cfg in (s.get("services") or {}).values())
        ]

    def _select_set_in_tree(self, set_id: str) -> None:
        """Selektiert ein Set im MasterTree (Bugfix 05.08.2026).

        Loest ueber selection_changed -> _on_master_selection den Editor-Sync
        aus – direkt nach dem Anlegen eines neuen Sets.
        """
        selector = getattr(self, "service_selector", None)
        tree = getattr(selector, "master_tree", None)
        if tree is None or not set_id:
            return
        try:
            from serviceui.master_tree import (
                ROLE_NODE_TYPE, ROLE_SET_ID, TYPE_SET, TreeItemIterator)
            for item in TreeItemIterator(tree):
                if item is None:
                    continue
                if (item.data(0, ROLE_NODE_TYPE) == TYPE_SET and
                        str(item.data(0, ROLE_SET_ID) or "") == set_id):
                    tree.setCurrentItem(item)
                    return
        except (RuntimeError, AttributeError):
            pass

    def _build_new_set_definition(self, name: str,
                                  indicator_id: str) -> Dict[str, Any]:
        """Baut die Definition fuer ein neues Service-Set.

        Bugfix 05.08.2026: Bei Indikator-Auswahl wird die `indicator_id`
        explizit gespeichert und die Basis-Services des Indikators
        (service_plugin_ids, z.B. grid_lines + proximity) werden mit
        Registry-Defaults automatisch angelegt (instance_id = plugin_id) –
        einfache Bedienung und das Set ist sofort gueltig fuer den Indikator.
        """
        definition: Dict[str, Any] = {
            "set_id": "",
            "display_name": name,
            "description": "",
            "execution_order": [],
            "services": {},
        }
        if not indicator_id:
            return definition
        definition["indicator_id"] = indicator_id
        try:
            from analytics.engine.service_selector_model import list_indicators
            info = next(
                (i for i in list_indicators()
                 if str(i.get("indicator_id") or "") == indicator_id),
                None,
            )
        except Exception:
            info = None
        if info is None:
            return definition
        try:
            from analytics.features.feature_builder import PluginRegistry
            registry = PluginRegistry()
        except Exception:
            registry = None
        for pid in (info.get("service_plugin_ids") or []):
            pid = str(pid)
            if not pid or pid in definition["services"]:
                continue
            params: Dict[str, Any] = {}
            if registry is not None:
                try:
                    params = dict(getattr(
                        registry.get(pid), "default_params", {}) or {})
                except (KeyError, AttributeError):
                    params = {}
            lookback: int = 1000
            if "lookback" in params:
                try:
                    lookback = int(params.pop("lookback") or 1000)
                except (TypeError, ValueError):
                    lookback = 1000
            definition["services"][pid] = {
                "plugin_id": pid,
                "lookback": lookback,
                "params": params,
            }
            definition["execution_order"].append(pid)
        return definition

    @Slot()
    def _on_add_set(self) -> None:
        """Erzeugt ein NEUES Service-Set ([➕ Set] / Kontextmenue
        'Neues Set anlegen').

        Bugfix 05.08.2026 (einfache Bedienung): Dialog mit Namens- und
        Indikator-Auswahl (NewServiceSetDialog). Der Name ist Pflicht; wird
        ein Indikator gewaehlt, wird er explizit zugewiesen (indicator_id)
        und die Basis-Services automatisch angelegt (_build_new_set_definition).
        Das neue Set wird direkt im MasterTree selektiert.
        """
        try:
            from analytics.engine.service_selector_model import list_indicators
            indicators = list_indicators()
        except Exception:
            indicators = []
        dlg = NewServiceSetDialog(indicators, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        name = dlg.result_name()
        ind_id = dlg.result_indicator_id()
        if any((s.get("display_name") or "") == name
               for s in self.set_repo.list_sets()):
            QMessageBox.warning(
                self, "Name vergeben",
                f"Ein Service-Set heißt bereits '{name}'.")
            return
        definition = self._build_new_set_definition(name, ind_id)
        try:
            set_id = self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Anlegen des Sets: {e}")
            return
        if not set_id:
            self.log("Set-Anlage fehlgeschlagen.")
            return
        self.log(f"Neues Service-Set angelegt: {set_id}"
                 + (f" (Indikator: {ind_id})" if ind_id else ""))
        event_bus.service_set_changed.emit()
        self.refresh_set_list()
        if self.combo_set is not None:
            idx = self.combo_set.findData(set_id)
            if idx >= 0:
                self.combo_set.setCurrentIndex(idx)
        # Neues Set im MasterTree selektieren (Editor-Sync via selection_changed)
        self._select_set_in_tree(set_id)

    @Slot(str)
    def _on_rename_set(self, set_id: str) -> None:
        """Benennt ein Service-Set um (Kontextmenue 'Set umbenennen').

        Direkt ueber set_repo: Namensdialog (vorbelegt), Kollisionspruefung
        gegen die UEBRIGEN Sets, dann save_set() mit gleicher set_id und
        neuem display_name. Bewusst NICHT ueber den NamedItemAdapter –
        dessen _item_save_as() verweigert leere execution_order (leere Sets
        waeren sonst nicht umbenennbar).
        """
        if not set_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Umbenennen abgebrochen.")
            return
        current_name = str(definition.get("display_name") or "")
        name, ok = QInputDialog.getText(
            self, "Set umbenennen",
            f"Neuer Name für das Service-Set '{current_name}':",
            text=current_name,
        )
        if not ok:
            return
        clean = name.strip()
        if not clean:
            QMessageBox.warning(self, "Fehler", "Der Name darf nicht leer sein.")
            return
        collision = any(
            (s.get("display_name") or "") == clean and s.get("set_id") != set_id
            for s in self.set_repo.list_sets())
        if collision:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Ein anderes Service-Set heißt bereits '{clean}'.")
            return
        definition["display_name"] = clean
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Set umbenannt: '{current_name}' -> '{clean}'")
        event_bus.service_set_changed.emit()
        self.refresh_set_list()
        if self.combo_set is not None:
            idx = self.combo_set.findData(set_id)
            if idx >= 0:
                self.combo_set.setCurrentIndex(idx)

    @Slot(str)
    def _on_add_set_service(self, set_id: str) -> None:
        """'Service hinzufuegen' (Kontextmenue): EIGENE Auswahlbox.

        Bugfix 05.08.2026: Eine eigene QInputDialog-Auswahlbox statt der
        frueheren Toolbar-Auswahl (show_add_menu, Toolbar seit 05.08.2026
        entfernt). Nach der Auswahl wird der Service ueber den bestehenden
        Pfad (edit_new_instance + add_instance) ins Set uebernommen und
        sofort persistiert.
        """
        if not set_id:
            return
        if self.combo_set is not None:
            idx = self.combo_set.findData(set_id)
            if idx >= 0:
                self.combo_set.setCurrentIndex(idx)
        selector = getattr(self, "service_selector", None)
        ids = sorted(selector.get_plugin_ids()) if selector is not None else []
        if not ids:
            self.log("Keine Services verfuegbar.")
            return
        pid, ok = QInputDialog.getItem(
            self, "Service hinzufügen",
            "Service wählen:", ids, 0, False)
        if not ok or not pid:
            return
        self._toolbar_add_service(str(pid))

    @Slot(str)
    def _on_delete_set(self, set_id: str) -> None:
        """'Set loeschen' (Kontextmenue / [🗑️ Set löschen]): Set in den
        Editor laden und delete_set() aufrufen – die P14-04-E-Sperre
        ('letztes Set') und die Rueckfrage (Papierkorb, P14-05) greifen
        dort zentral."""
        if not set_id:
            return
        if self.combo_set is not None:
            idx = self.combo_set.findData(set_id)
            if idx >= 0:
                self.combo_set.setCurrentIndex(idx)
        self.delete_set()

    def _select_service_in_editor(self, set_id: str, service_id: str) -> None:
        """Laedt das Set in den Editor und markiert die Service-Instanz in
        der execution_order-Liste (gemeinsame Vorbereitung fuer Order-/
        Entfernen-Aktionen aus dem Kontextmenue)."""
        if self.combo_set is not None:
            idx = self.combo_set.findData(set_id)
            if idx >= 0:
                self.combo_set.setCurrentIndex(idx)
        if service_id and self.list_execution_order is not None:
            try:
                if not _qt_valid(self.list_execution_order):
                    return
                for i in range(self.list_execution_order.count()):
                    item = self.list_execution_order.item(i)
                    if item is None or not _qt_valid(item):
                        continue
                    if item.data(Qt.UserRole) == service_id:
                        self.list_execution_order.setCurrentRow(i)
                        self._current_list_iid = service_id
                        break
            except (RuntimeError, AttributeError):
                pass

    @Slot(str, str, int)
    def _on_move_service(self, set_id: str, service_id: str, delta: int) -> None:
        """Order ▲/▼ (Kontextmenue): Service in der execution_order des Sets
        verschieben – Reuse von move_order_item(delta)."""
        if not set_id or not service_id:
            return
        self._select_service_in_editor(set_id, service_id)
        self.move_order_item(delta)

    @Slot(str, str)
    def _on_remove_service(self, set_id: str, service_id: str) -> None:
        """'Service entfernen' (Kontextmenue / [➖ Service entfernen]): Reuse
        von remove_instance() – inkl. P14-04-Sperrpruefung (gesperrte
        Services werden mit Hinweis abgelehnt)."""
        if not set_id or not service_id:
            return
        self._select_service_in_editor(set_id, service_id)
        self.remove_instance()

    @Slot()
    def _on_purge_trash(self) -> None:
        """Leert den Papierkorb ENDGUELTIG (Kontextmenue 'Papierkorb löschen').

        Bugfix 05.08.2026: Doppelte Sicherheitsabfrage (P14-05) – der Vorgang
        ist nicht umkehrbar. Einzelne Sets koennen weiterhin ueber den
        Papierkorb-Dialog (btn_trash_sets) wiederhergestellt werden.
        """
        trash = self.set_repo.list_trash()
        if not trash:
            QMessageBox.information(
                self, "Papierkorb",
                "Der Papierkorb ist leer – es gibt nichts zu löschen.")
            return
        count = len(trash)
        reply = QMessageBox.question(
            self, "Papierkorb löschen",
            f"{count} Set(s) liegen im Papierkorb.\n"
            f"Wirklich ENDGÜLTIG löschen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            "Diese Aktion kann nicht rückgängig gemacht werden.\nFortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        try:
            n = self.set_repo.purge_trash()
        except Exception as e:
            self.log(f"FEHLER beim Leeren des Papierkorbs: {e}")
            return
        self.log(f"Papierkorb geleert: {n} Set(s) endgültig entfernt (P14-05).")
        event_bus.service_set_changed.emit()

    # --- Phase 15 15.01: Symbol- & Favoriten-Verwaltung ---

    @Slot()
    def open_symbols_window(self) -> None:
        """Oeffnet das nicht-modale SymbolsWindow (Singleton-Verhalten).

        Analog zu open_service_window in main.py: Existiert bereits eine
        sichtbare Instanz, wird sie in den Vordergrund geholt statt neu
        geoeffnet (PersistentWindow.get_existing_instance()).
        """
        existing = SymbolsWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = SymbolsWindow(self)  # parent=self nur fuer state_manager-Zugriff
        win.show()

    def _refresh_symbol_combo(self) -> None:
        """Befuellt die Symbol-ComboBox aus den Favoriten (is_favorite == True).

        Wird beim Start und bei jedem `EventBus.favorites_changed`-Event
        aufgerufen (Verbindung im __init__). Fallback auf die Standard-
        Defaults (SILVER/GOLD/BTCUSD), falls keine Favoriten gesetzt sind –
        damit der Scanner nie ohne Symbol-Auswahl steht. Die aktuelle
        Auswahl bleibt erhalten, sofern sie noch Favorit ist.
        """
        if not self.combo_symbol:
            return
        favorites = self._symbol_repo.get_favorite_symbols()
        if not favorites:
            favorites = list(SymbolRepository.DEFAULT_SYMBOLS)
        current = self.combo_symbol.currentText()
        self.combo_symbol.blockSignals(True)
        self.combo_symbol.clear()
        for sym in favorites:
            self.combo_symbol.addItem(sym)
        idx = self.combo_symbol.findText(current)
        if idx >= 0:
            self.combo_symbol.setCurrentIndex(idx)
        self.combo_symbol.blockSignals(False)

    # --- Scanner ---

    @Slot()
    def start_scan(self):
        if self.scanner and self.scanner.isRunning():
            self.log("Scan laeuft bereits.")
            return

        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        new_scan = self.check_new_scan.isChecked() if self.check_new_scan else False

        # U15-D2 (Bedien-Feinschliff): Bestätigungsdialog vor FULL SCAN.
        # new_scan=True löscht bestehende Feature-Rows und berechnet neu
        # (HistoricalScanner: "Modus: FULL SCAN ...") –
        # dieser Overwrite ist unwiderruflich, daher Rückfrage.
        if new_scan:
            reply = QMessageBox.question(
                self, "Voll-Scan bestätigen",
                f"Voll-Scan für {symbol}?\n\n"
                "Bestehende Feature-Rows werden überschrieben und neu "
                "berechnet (unwiderruflich). Fortfahren?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.log("Voll-Scan abgebrochen.")
                return

        self.log(f"Starte Plugin-Batch: {symbol}, New Scan = {new_scan}")
        self.btn_start.setEnabled(False)
        self._elapsed_seconds = 0
        self.label_elapsed.setText("00:00:00")
        self.progress_bar.setValue(0)
        self._elapsed_timer.start(1000)

        self.scanner = HistoricalScanner(symbol, new_scan)
        self.scanner.progress_updated.connect(self.on_progress)
        self.scanner.scan_finished.connect(self.on_finished)
        self.scanner.log_message.connect(self.log)
        self.scanner.start()

    @Slot(str, int, int)
    def on_progress(self, message: str, current: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.log(message)

    @Slot(str, int)
    def on_finished(self, symbol: str, count: int):
        self._elapsed_timer.stop()
        self.btn_start.setEnabled(True)
        self.log(f"Scan für {symbol} beendet: {count} Feature-Rows geschrieben.")

    @Slot(str)
    def log(self, message: str):
        if self.text_log:
            self.text_log.append(message)
            # U15-D2 (Bedien-Feinschliff): Auto-Scroll ans Log-Ende, damit
            # bei langen Scans immer die neueste Meldung sichtbar ist.
            bar = self.text_log.verticalScrollBar()
            if bar is not None:
                bar.setValue(bar.maximum())

    def _on_log_context_menu(self, pos) -> None:
        """U15-D2 (Bedien-Feinschliff): Kontext-Rechtsklick im Log-Bereich.

        Aktionen: 'Kopieren' (nur bei vorhandener Textauswahl) und
        'Log leeren'. Reine QTextEdit-Operationen (copy/clear), keine
        Logik-Duplikate.
        """
        if not self.text_log:
            return
        menu = QMenu(self)
        copy_action = menu.addAction("Kopieren")
        copy_action.setEnabled(bool(self.text_log.textCursor().hasSelection()))
        clear_action = menu.addAction("Log leeren")
        chosen = menu.exec(self.text_log.mapToGlobal(pos))
        if chosen == copy_action:
            self.text_log.copy()
        elif chosen == clear_action:
            self.text_log.clear()

    def _update_elapsed(self):
        self._elapsed_seconds += 1
        h = self._elapsed_seconds // 3600
        m = (self._elapsed_seconds % 3600) // 60
        s = self._elapsed_seconds % 60
        self.label_elapsed.setText(f"{h:02d}:{m:02d}:{s:02d}")

    # =========================================================================
    # Phase 13 Schritt 4: Service-Set-Verwaltung
    # =========================================================================

    def refresh_set_list(self) -> None:
        """Befüllt das Set-Dropdown aus ServiceSetRepository.list_sets().

        Quelle für die Set-Auswahl (Roadmap §4.2). Behält die aktuelle
        Auswahl bei, sofern sie noch existiert; andernfalls wird das erste
        Set geladen und in den Editor übertragen.
        """
        if not self.combo_set:
            return
        sets = self.set_repo.list_sets()
        current = self.combo_set.currentData()

        self.combo_set.blockSignals(True)
        self.combo_set.clear()
        for s in sets:
            label = s.get("display_name") or s.get("set_id") or "Unbenannt"
            self.combo_set.addItem(label, s.get("set_id"))
        self.combo_set.blockSignals(False)

        # Aktuelle Auswahl beibehalten, falls noch vorhanden.
        selected_id: Optional[str] = None
        if current is not None:
            idx = self.combo_set.findData(current)
            if idx >= 0:
                self.combo_set.setCurrentIndex(idx)
                selected_id = current

        if selected_id is None and sets:
            # Achtung: addItem() setzt das erste Item automatisch auf Index 0,
            # während die Signale blockiert sind -> setCurrentIndex(0) löst KEIN
            # currentIndexChanged aus. Daher explizit in den Editor laden.
            self.combo_set.setCurrentIndex(0)
            selected_id = self.combo_set.itemData(0)

        if selected_id:
            definition = self.set_repo.get_set(selected_id)
            if definition:
                self.load_set_into_editor(definition)
        else:
            # Kein Set (mehr) vorhanden -> Editor leeren
            self._clear_set_editor()

    def _clear_set_editor(self) -> None:
        """Leert Name-Feld, Beschreibung und execution_order-Liste des Set-Editors."""
        self._current_set_id = None
        self._current_set_definition = None
        self._current_list_iid = None
        if self.edit_set_name:
            self.edit_set_name.clear()
        if self.edit_set_description:
            self.edit_set_description.clear()
        if self.list_execution_order:
            self.list_execution_order.clear()
        self._clear_service_columns()

    @Slot(int)
    def _on_set_selected(self, index: int) -> None:
        """Lädt das im Dropdown gewählte Set in den Editor."""
        if index < 0 or not self.combo_set:
            return
        set_id = self.combo_set.itemData(index)
        if not set_id:
            return
        definition = self.set_repo.get_set(set_id)
        if definition:
            self.load_set_into_editor(definition)
            self.log(f"Set geladen: {set_id}")

    def load_set_into_editor(self, definition: Dict[str, Any]) -> None:
        """Überträgt eine ServiceSetDefinition in Name-Feld + execution_order-Liste.

        Phase 13 5.4 Schritt 1: Baut zusätzlich die dynamischen Service-Spalten
        (eine QGroupBox pro Service mit Parameter-Formular) auf.
        """
        self._current_set_id = definition.get("set_id")
        self._current_set_definition = definition
        self._current_list_iid = None
        if self.edit_set_name:
            self.edit_set_name.setText(definition.get("display_name") or "")
        if self.edit_set_description:
            self.edit_set_description.setText(definition.get("description") or "")
        if self.list_execution_order:
            self.list_execution_order.clear()
            services = definition.get("services") or {}
            for iid in (definition.get("execution_order") or []):
                cfg = services.get(iid, {})
                plugin_id = cfg.get("plugin_id", "?")
                prefix, lock_tip = self._service_lock(plugin_id)
                item = QListWidgetItem(f"{prefix}{iid}  [{plugin_id}]")
                item.setData(Qt.UserRole, iid)
                item.setData(Qt.UserRole + 1, plugin_id)
                item.setToolTip(self._build_tooltip(iid, cfg) + lock_tip)
                self.list_execution_order.addItem(item)
        self._build_service_columns(definition)

    def collect_current_order(self) -> list:
        """Liefert die instance_ids aus der Liste (aktuelle execution_order)."""
        if not self.list_execution_order:
            return []
        return [
            self.list_execution_order.item(i).data(Qt.UserRole)
            for i in range(self.list_execution_order.count())
        ]

    @Slot()
    def move_order_item(self, delta: int) -> None:
        """Verschiebt das markierte Listenelement um delta (-1 = hoch, +1 = runter)."""
        lw = self.list_execution_order
        if not lw:
            return
        row = lw.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= lw.count():
            return
        item = lw.takeItem(row)
        lw.insertItem(new_row, item)
        lw.setCurrentRow(new_row)
        self._rebuild_columns()
        # Bugfix 05.08.2026: Reihenfolge SOFORT persistieren (P14-05-Snapshot)
        # + EventBus-Live-Sync (MasterTree/Set-Anzeige zeigen die neue Order).
        self._persist_current_set("Reihenfolge geaendert")

    @Slot()
    def remove_instance(self) -> None:
        """Entfernt den markierten Service aus der Ausführungs-Reihenfolge.

        P14-04-E (Service-Sperre): Einzel-Services, die in einem gespeicherten
        Service-Set vorkommen, dürfen NICHT entfernt werden – sonst würde das
        Set invalide und der Indikator verlöre seine Basisservices. Beim
        Löschversuch erscheint ein Hinweis mit dem Namen des verwendeten Sets.
        """
        lw = self.list_execution_order
        if not lw or lw.currentRow() < 0:
            return
        item = lw.item(lw.currentRow())
        plugin_id = str(item.data(Qt.UserRole + 1) or item.data(Qt.UserRole) or "")
        # P14-04-E (Bugfix 05.08.2026): Nur der LETZTE Vorkommen eines
        # Indikator-Services ueber ALLE gespeicherten Sets ist gesperrt –
        # solange ein anderes gültiges Set den Service enthaelt, darf er
        # entfernt werden.
        if self._plugin_belongs_to_indicator(plugin_id):
            others = self._remaining_sets_with_plugin(
                plugin_id, exclude_set_id=self._current_set_id)
            if not others:
                QMessageBox.warning(
                    self, "Service gesperrt",
                    f"Der Service '{plugin_id}' ist der letzte in einem "
                    f"gespeicherten Service-Set.\n"
                    f"Für den Indikator muss mindestens ein gültiges Set "
                    f"mit diesem Service erhalten bleiben (P14-04).")
                return
        # Bugfix 05.08.2026: Doppelte Sicherheitsabfrage (P14-05) – der
        # bisherige Set-Stand wird als Snapshot in service_set_history
        # gesichert, bevor der Service entfernt wird.
        iid = str(item.data(Qt.UserRole) or "")
        reply = QMessageBox.question(
            self, "Service entfernen",
            f"Service '{iid} [{plugin_id}]' aus dem Set entfernen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            "Der bisherige Set-Stand wird als Snapshot gesichert "
            "(service_set_history). Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        lw.takeItem(lw.currentRow())
        self._rebuild_columns()
        # Bugfix 05.08.2026: Entfernen SOFORT persistieren + EventBus-Sync.
        self._persist_current_set("Service entfernt")

    @Slot()
    def _on_plugin_select_changed(self, plugin_id: str) -> None:
        """Füllt das Instanz-Feld mit 'plugin_id [plugin_id]' vor, wenn der
        User einen Service aus dem verfügbaren-Dropdown wählt (Schritt 6-
        Korrektur: alle Services sichtbar + auswählbar)."""
        if not plugin_id or not self.edit_new_instance:
            return
        self.edit_new_instance.setText(f"{plugin_id} [{plugin_id}]")

    @Slot()
    def add_instance(self) -> None:
        """Fügt eine Service-Instanz 'instance_id [plugin_id]' zur Liste hinzu.

        Plugin muss in der PluginRegistry existieren (Default-Params werden
        beim Speichern eines neuen Sets verwendet). Duplikate werden abgelehnt.
        """
        if not self.edit_new_instance or not self.list_execution_order:
            return
        text = self.edit_new_instance.text().strip()
        # Fallback: leeres Feld + Service im verfügbaren-Dropdown gewählt
        if not text and self.combo_plugin_select:
            plugin_id = self.combo_plugin_select.currentText()
            if plugin_id:
                text = f"{plugin_id} [{plugin_id}]"
        if not text:
            return
        # Formate: "instance_id [plugin_id]", "instance_id:plugin_id" oder "instance_id"
        import re
        m = re.match(r"^([\w\-]+)\s*[\[:]\s*([\w\-]+)\s*\]?$", text)
        if m:
            iid, plugin_id = m.group(1), m.group(2)
        else:
            iid = text
            plugin_id = text

        try:
            from analytics.features.feature_builder import PluginRegistry
            PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden. "
                     f"Verfügbare Plugins: {_available_plugin_ids()}")
            return

        for i in range(self.list_execution_order.count()):
            if self.list_execution_order.item(i).data(Qt.UserRole) == iid:
                self.log(f"instance_id '{iid}' existiert bereits.")
                return

        prefix, lock_tip = self._service_lock(plugin_id)
        item = QListWidgetItem(f"{prefix}{iid}  [{plugin_id}]")
        item.setData(Qt.UserRole, iid)
        item.setData(Qt.UserRole + 1, plugin_id)
        item.setToolTip(self._build_tooltip(iid, {"plugin_id": plugin_id}) + lock_tip)
        self.list_execution_order.addItem(item)
        self.edit_new_instance.clear()
        self.log(f"Service hinzugefügt: {iid} [{plugin_id}]")
        self._rebuild_columns()
        # Bugfix 05.08.2026: Hinzufuegen SOFORT persistieren (nur bei
        # geladenem Set) + EventBus-Live-Sync (Tree zeigt den neuen Service).
        self._persist_current_set("Service hinzugefuegt")

    def collect_set_definition(self) -> Dict[str, Any]:
        """Baut aus dem Editor eine ServiceSetDefinition.

        Für ein geladenes Set werden die services aus der DB übernommen;
        für neue Instanzen (bzw. neue Sets) werden die services aus den
        Listeneinträgen aufgebaut (plugin_id + Default-Params aus der
        Registry). Die Werte der dynamischen Service-Spalten (5.4 Schritt 1)
        werden anschließend in die services-Konfiguration übernommen.
        """
        order = self.collect_current_order()
        services: Dict[str, Any] = {}
        if self._current_set_id:
            existing = self.set_repo.get_set(self._current_set_id) or {}
            services = dict(existing.get("services") or {})

        # Jede Instanz in der Reihenfolge braucht eine services-Konfiguration –
        # neue Instanzen erhalten Default-Params aus der Registry.
        from analytics.features.feature_builder import PluginRegistry
        registry = PluginRegistry()
        if self.list_execution_order:
            for i in range(self.list_execution_order.count()):
                item = self.list_execution_order.item(i)
                iid = item.data(Qt.UserRole)
                plugin_id = item.data(Qt.UserRole + 1) or iid
                if not iid:
                    continue
                if iid not in services:
                    try:
                        plugin = registry.get(plugin_id)
                        cfg: Dict[str, Any] = {
                            "plugin_id": plugin_id,
                            "lookback": 1000,
                            "params": dict(plugin.default_params),
                        }
                    except KeyError:
                        cfg = {"plugin_id": plugin_id, "lookback": 1000, "params": {}}
                    services[iid] = cfg

        # Werte aus den dynamischen Service-Spalten übernehmen.
        # lookback ist die Service-Instanz-Einstellung (ServiceInstanceConfig.
        # lookback) und wird NICHT in params geschrieben.
        for (iid, key), ctrl in self._service_param_controls.items():
            cfg = services.setdefault(iid, {"plugin_id": "", "lookback": 1000, "params": {}})
            if key == "lookback":
                cfg["lookback"] = int(self._ctrl_value(ctrl))
            else:
                cfg.setdefault("params", {})[key] = self._ctrl_value(ctrl)

        # Phase 14 P14-01: Instanz-Beschreibung aus den Spalten übernehmen
        # (ServiceInstanceConfig.description – gehört NICHT in params).
        for iid, ctrl in self._service_desc_controls.items():
            cfg = services.setdefault(iid, {"plugin_id": "", "lookback": 1000, "params": {}})
            cfg["description"] = ctrl.text().strip()

        # Phase 14 P14-04: Semantische Versionierung – bei JEDER instance_id
        # wird die aktuelle plugin.version aus der PluginRegistry eingestempelt
        # (ServiceInstanceConfig.version). So trägt jede gespeicherte Instanz
        # die Version des erzeugenden Plugins für den späteren Schema-Migrator.
        # Kann ein Plugin nicht aufgelöst werden (z. B. deinstalliert), bleibt
        # ein vorhandenes version-Feld bzw. dessen Fehlen unverändert erhalten.
        for iid, cfg in services.items():
            pid = cfg.get("plugin_id") or iid
            try:
                plugin = registry.get(pid)
                cfg["version"] = getattr(plugin, "version", "0.0.0") or "0.0.0"
            except KeyError:
                pass

        return {
            "set_id": self._current_set_id or "",
            "display_name": self.edit_set_name.text().strip() if self.edit_set_name else "",
            # Phase 14 P14-01: Set-Beschreibung wird mitgespeichert
            "description": self.edit_set_description.text().strip() if self.edit_set_description else "",
            # Bugfix 05.08.2026: explizite Indikator-Zuordnung erhalten
            "indicator_id": (self._current_set_definition or {}).get("indicator_id"),
            "execution_order": order,
            "services": services,
        }

    # =========================================================================
    # Phase 14 P14-01: Tooltips & Info-Dialog für Service-Instanzen
    # =========================================================================

    def _build_tooltip(self, instance_id: str, config: Dict[str, Any]) -> str:
        """Baut einen Rich-Text-Tooltip (HTML) für eine Service-Instanz.

        Angezeigt werden instance_id, Plugin-ID und – falls vorhanden – die
        individuelle Instanz-Beschreibung (ServiceInstanceConfig.description).
        """
        lines = [f"<b>{instance_id}</b>", f"Plugin: {config.get('plugin_id', '?')}"]
        desc = config.get("description")
        if desc:
            lines.append(f"<i>{desc}</i>")
        return "<br>".join(lines)

    def _service_lock(self, plugin_id: str) -> tuple:
        """P14-04-E: (🔒-Präfix, Tooltip-Nachtrag) für die sichtbare Sperr-
        Kennzeichnung im Service-Fenster.

        Ein Service ist gesperrt, wenn er in einem gespeicherten Service-Set
        vorkommt (Indikator-Basisservice). Liefert ("", "") wenn der Service
        frei ist; andernfalls ein 🔒-Präfix für Listeneintrag/Spaltentitel und
        einen HTML-Tooltip-Nachtrag mit dem Namen des verwendeten Sets.
        """
        names = _sets_using_plugin(str(plugin_id), self.set_repo.list_sets())
        if not names:
            return "", ""
        return "🔒 ", (f"<br><b>Gesperrt (P14-04)</b>: wird vom Service-Set "
                       f"'{names[0]}' verwendet – Entfernen nicht möglich")

    def _on_order_item_clicked(self, item: QListWidgetItem) -> None:
        """Merkt sich die aktuell markierte instance_id (itemClicked)."""
        if item is not None:
            self._current_list_iid = item.data(Qt.UserRole)

    def _sync_list_selection(self) -> None:
        """Synchronisiert _current_list_iid mit der aktuellen Selektion."""
        if self.list_execution_order is not None:
            row = self.list_execution_order.currentRow()
            if row >= 0:
                self._current_list_iid = self.list_execution_order.item(row).data(Qt.UserRole)


    @Slot()
    def _show_service_info(self) -> None:
        """Öffnet den ServiceDescriptionDialog für die markierte Instanz.

        Phase 15 U15-D1: Der Info-/Beschreibungs-Dialog selbst ist bereits
        extern ausgelagert (analytics/engine/description_dialog.py,
        ServiceDescriptionDialog); diese Slot-Methode öffnet ihn nur noch.
        """
        iid = self._current_list_iid
        if not iid or self.list_execution_order is None:
            self.log("Keine Service-Instanz markiert.")
            return
        cfg: Dict[str, Any] = {}
        plugin = None
        if self._current_set_definition:
            cfg = dict((self._current_set_definition.get("services") or {}).get(iid, {}))
        # Live-Beschreibung aus dem Eingabefeld übernehmen (falls vorhanden)
        desc_ctrl = self._service_desc_controls.get(iid)
        if desc_ctrl is not None:
            cfg["description"] = desc_ctrl.text().strip()
        plugin_id = cfg.get("plugin_id") or iid
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden.")
            return
        dlg = ServiceDescriptionDialog.from_plugin(plugin, instance_id=iid, config=cfg, parent=self)
        dlg.exec()

    @Slot(str, str, str)
    def _on_tree_info_requested(self, set_id: str, service_id: str,
                                plugin_id: str) -> None:
        """Oeffnet den ServiceDescriptionDialog fuer die Info-Button-Zeile.

        Bugfix 05.08.2026: Der Info-Button sitzt jetzt direkt im MasterTree
        (Spalte 1) statt in der Box 'Service-Sets (Phase 13)'. Je nach
        Zeilentyp wird der passende Dialog geoeffnet:

          * Service-Zeile:  from_plugin (Instanz + Config + header_line)
          * Plugin-Zeile:   from_plugin (ohne Instanz, header_line)
          * Set-Zeile:      from_set (Set-Name/-Beschreibung/-Services,
                            header_line)

        Die ERSTE Dialog-Zeile ist der bisherige Tooltip-Text
        ('aktiv/im <Indikator>'), danach folgt eine Leerzeile und dann der
        Beschreibungstext (header_line-Rendering im Dialog).
        """
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return
        try:
            # 1) Service-Zeile (set_id + service_id)
            if service_id and set_id:
                cfg = model.find_service(set_id, service_id) or {}
                pid = str(cfg.get("plugin_id") or service_id)
                plugin = self._resolve_info_plugin(pid)
                if plugin is None:
                    return
                dlg = ServiceDescriptionDialog.from_plugin(
                    plugin, instance_id=service_id, config=cfg, parent=self,
                    header_line=self._info_header_tooltip(pid))
                dlg.exec()
                return
            # 2) Plugin-Zeile (nur plugin_id; set_id = Gruppenkennung)
            if plugin_id and not service_id:
                plugin = self._resolve_info_plugin(plugin_id)
                if plugin is None:
                    return
                dlg = ServiceDescriptionDialog.from_plugin(
                    plugin, instance_id="", config=None, parent=self,
                    header_line=self._info_header_tooltip(plugin_id))
                dlg.exec()
                return
            # 3) Set-Zeile (nur set_id)
            if set_id and not service_id and not plugin_id:
                set_def = model.find_set(set_id)
                if not set_def:
                    self.log(f"Set '{set_id}' nicht gefunden.")
                    return
                dlg = ServiceDescriptionDialog.from_set(
                    set_def, parent=self,
                    header_line=self._info_set_tooltip(set_def))
                dlg.exec()
                return
        except (RuntimeError, AttributeError) as e:
            self.log(f"Info-Dialog nicht moeglich: {e}")

    def _resolve_info_plugin(self, plugin_id: str):
        """Liefert das Plugin aus der Registry (oder None + Log-Eintrag)."""
        try:
            from analytics.features.feature_builder import PluginRegistry
            return PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden.")
            return None

    def _info_header_tooltip(self, plugin_id: str) -> str:
        """Erste Dialog-Zeile = bisheriger Tooltip-Text des Info-Buttons
        ('aktiv <Indikator>' / 'im <Indikator>'); leer ohne Indikator-
        Zugehoerigkeit."""
        model = getattr(self.service_selector, "model", None)
        if model is None or not model.belongs_to_indicator(plugin_id):
            return ""
        name = model.get_indicator_display_name(plugin_id)
        return (f"aktiv {name}" if model.is_active_in_chart(plugin_id)
                else f"im {name}")

    def _info_set_tooltip(self, set_def: Dict[str, Any]) -> str:
        """Erste Dialog-Zeile fuer Set-Zeilen (Tooltip-Namenslogik analog
        _apply_set_badge: 'aktiv/im <Indikator>', mehrere mit ' + ')."""
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return ""
        names = model.get_set_indicator_names(set_def or {})
        if not names:
            return ""
        label = " + ".join(names)
        return (f"aktiv {label}" if model.is_set_active(set_def or {})
                else f"im {label}")

    @Slot()
    def save_set(self) -> None:
        """Speichert das aktive Set – analog zur Preset-Verwaltung (generisch).

        Namensdialog (vorbelegt), leerer Name → Auto-Name aus den instance_ids
        (z.B. 'grid_1 + prox_1'), Überschreiben-Rückfrage bei doppeltem Namen.
        Implementierung: NamedItemActionsMixin.save_named_item() mit dem
        Service-Set-Adapter (ServiceSetItemAdapter).
        """
        self.save_named_item(
            self._set_adapter,
            dialog_title="Service-Set speichern",
            prompt="Name für das Service-Set:",
        )

    @Slot()
    def delete_set(self) -> None:
        """Löscht das gewählte Set – analog zur Preset-Verwaltung (generisch).

        Rückfrage (QMessageBox.question), danach wird das nächstverfügbare Set
        ausgewählt. Implementierung: NamedItemActionsMixin.delete_named_item()
        mit dem Service-Set-Adapter.

        P14-04-E (Set-Sperre): Es muss immer mindestens ein gültiges Service-
        Set erhalten bleiben, damit der Indikator funktionsfähig bleibt. Das
        Löschen des letzten verbliebenen Sets ist gesperrt.
        """
        # P14-04-E (Bugfix 05.08.2026): Ein Set darf gelöscht werden,
        # solange für jeden Indikator-Service des Sets in einem ANDEREN
        # gespeicherten Set noch ein Vorkommen existiert (gültiges Set für
        # den Indikator bleibt erhalten). Enthält das Set den LETZTEN
        # Vorkommen eines Indikator-Services, ist das Löschen gesperrt.
        current_id = self._set_adapter._item_current_id()
        current = next(
            (s for s in self.set_repo.list_sets()
             if s.get("set_id") == current_id),
            None,
        )
        if current:
            services = current.get("services") or {}
            for cfg in services.values():
                if not isinstance(cfg, dict):
                    continue
                pid = str(cfg.get("plugin_id") or "")
                if not pid or not self._plugin_belongs_to_indicator(pid):
                    continue
                others = self._remaining_sets_with_plugin(
                    pid, exclude_set_id=current_id)
                if not others:
                    QMessageBox.warning(
                        self, "Löschen gesperrt",
                        f"Dieses Service-Set enthält den letzten "
                        f"gespeicherten Service '{pid}' für den Indikator.\n"
                        f"Es muss mindestens ein gültiges Set mit diesem "
                        f"Service erhalten bleiben (P14-04).")
                    return
        # Bugfix 05.08.2026: Erste Bestaetigung – das Set wird in den
        # Papierkorb (service_sets_trash) verschoben (zweite Abfrage folgt
        # in delete_named_item; Wiederherstellung ueber den Papierkorb-
        # Dialog).
        name = self._set_adapter._item_current_name()
        if not name:
            return
        reply = QMessageBox.question(
            self, "Set in den Papierkorb verschieben",
            f"Set '{name}' wirklich in den Papierkorb verschieben?\n"
            f"(Wiederherstellung über den Papierkorb-Dialog möglich.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self.delete_named_item(self._set_adapter)

    # =========================================================================
    # Phase 14 P14-05: Papierkorb (Soft-Delete / Wiederherstellung)
    # =========================================================================

    @Slot()
    def show_trash_dialog(self) -> None:
        """Öffnet den Papierkorb-Dialog für Service-Sets (P14-05).

        Phase 15 U15-D1: Der Dialog ist in serviceui/trash_dialog.py als
        eigenständige Widget-Klasse (ServiceSetTrashDialog) ausgelagert –
        Verhalten unverändert (inkl. doppelter Sicherheitsnachfrage).
        """
        dialog = ServiceSetTrashDialog(
            repo=self.set_repo,
            log_fn=self.log,
            refresh_fn=self.refresh_set_list,
            parent=self,
        )
        dialog.exec()

    # =========================================================================
    # Phase 14 P14-02: Hot-Reload der Plugins (Dynamic Discovery)
    # =========================================================================

    @Slot()
    def reload_plugins(self) -> None:
        """Lädt Custom-Plugins aus data/custom_plugins/ neu (Hot-Reload).

        P14-02: Ruft PluginRegistry().reload() auf (unter RLock) und
        aktualisiert das verfügbare-Services-Dropdown. Bereits laufende
        Service-Ausführungen laufen auf ihren bisherigen Objektinstanzen
        weiter; neue Instanziierungen nutzen die neuen Klassen.
        """
        try:
            from analytics.features.feature_builder import PluginRegistry
            registry = PluginRegistry()
            registry.reload()
            self.log("Plugins neu geladen.")
        except Exception as e:
            self.log(f"FEHLER beim Plugin-Reload: {e}")
        # Dropdown aktualisieren (neue Custom-Plugins sichtbar machen)
        if self.combo_plugin_select:
            current = self.combo_plugin_select.currentText()
            self.combo_plugin_select.blockSignals(True)
            self.combo_plugin_select.clear()
            for pid in sorted(PluginRegistry().plugins.keys()):
                self.combo_plugin_select.addItem(pid, pid)
            idx = self.combo_plugin_select.findText(current)
            self.combo_plugin_select.setCurrentIndex(idx if idx >= 0 else 0)
            self.combo_plugin_select.blockSignals(False)
        self.log(f"Verfügbare Plugins: {_available_plugin_ids()}")

    @Slot()
    def execute_set(self) -> None:
        """Startet den ServiceSetEvaluator für das aktive Set (Hintergrund-Thread)."""
        definition = self.collect_set_definition()
        if not definition.get("execution_order"):
            self.log("Keine Services in der Ausführungs-Reihenfolge.")
            return
        if not definition.get("services"):
            self.log("Set hat keine services-Konfiguration – Ausführung nicht möglich.")
            return
        if self._set_run_worker and self._set_run_worker.isRunning():
            self.log("Set-Ausführung läuft bereits.")
            return

        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        timeframe = self.combo_tf_set.currentText() if self.combo_tf_set else "H1"

        if self.btn_execute_set:
            # U15-D2 (Bedien-Feinschliff): sichtbarer Button-Lock – der
            # Button wird deaktiviert und zeigt 'Läuft...', solange der
            # Worker aktiv ist (verhindert doppeltes Ausführen).
            self.btn_execute_set.setEnabled(False)
            self.btn_execute_set.setText("Läuft...")
        self._set_run_worker = ServiceSetRunWorker(
            self.set_evaluator, symbol, timeframe, definition, parent=self,
        )
        self._set_run_worker.log_message.connect(self.log)
        self._set_run_worker.run_finished.connect(self._on_set_run_finished)
        self._set_run_worker.run_failed.connect(self._on_set_run_failed)
        self._set_run_worker.start()

    @Slot(str, int)
    def _on_set_run_finished(self, set_id: str, count: int) -> None:
        if self.btn_execute_set:
            self.btn_execute_set.setEnabled(True)
            self.btn_execute_set.setText("Ausführen")
        self.log(f"Set-Ausführung abgeschlossen: {count} Services.")

    @Slot(str, str)
    def _on_set_run_failed(self, set_id: str, error: str) -> None:
        if self.btn_execute_set:
            self.btn_execute_set.setEnabled(True)
            self.btn_execute_set.setText("Ausführen")
        self.log(f"FEHLER bei Set-Ausführung: {error}")

    def closeEvent(self, event):
        # PersistentWindow.save_state() wird in super().closeEvent gerufen
        if self.scanner and self.scanner.isRunning():
            self.scanner.stop()
            self.scanner.wait(2000)
        if self._set_run_worker and self._set_run_worker.isRunning():
            self._set_run_worker.wait(2000)
        # 05.08.2026: Gezielter Kontextmenue-Run-Worker sauber beenden.
        if self._run_worker and self._run_worker.isRunning():
            self._run_worker.wait(2000)
        self._elapsed_timer.stop()
        super().closeEvent(event)
