# service_win.py
"""
Service-Kontrollfenster für PyTrader.
Steuert den Historical Scanner (Full-Scan / Delta-Update) über ein separates Fenster.
Mit automatischem State Persistence via PersistentWindow.

Phase 13 Schritt 4: Zusätzlich Service-Set-Verwaltung (ServiceSetRepository +
ServiceSetEvaluator): Set-Auswahl (list_sets()), execution_order-Anzeige mit
Up/Down-Umsortierung, Name (leer → Auto-Name), Speichern/Löschen (mit
QMessageBox-Rückfrage) und Ausführen (ServiceSetEvaluator im Hintergrund).
"""

from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QFile, QIODevice, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QProgressBar, QPushButton, QSizePolicy, QSpinBox, QTextEdit, QVBoxLayout,
    QWidget,
)

from analytics.background_workers.historical_scanner import HistoricalScanner
from analytics.engine.service_set_repository import ServiceSetRepository
from analytics.engine.set_evaluator import ServiceSetEvaluator
from persistent_win import PersistentWindow, register_persistent_window
from scrollable_content import ContentScrollMixin
from chart.widgets.named_item_actions import NamedItemAdapter, NamedItemActionsMixin

BASE_DIR = Path(__file__).resolve().parent


class ServiceSetRunWorker(QThread):
    """Phase 13 Schritt 4: Führt ein Service-Set im Hintergrund aus.

    Lädt OHLCV (Symbol/Timeframe) und ruft ServiceSetEvaluator.execute_set()
    in einem separaten Thread auf, damit die GUI nicht blockiert.
    """

    log_message = Signal(str)
    run_finished = Signal(str, int)  # set_id, Anzahl erfolgreicher Services
    run_failed = Signal(str, str)    # set_id, Fehlermeldung

    def __init__(self, evaluator: ServiceSetEvaluator, symbol: str, timeframe: str,
                 set_definition: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.evaluator = evaluator
        self.symbol = symbol
        self.timeframe = timeframe
        self.set_definition = set_definition

    def run(self):
        try:
            from analytics.features.feature_builder import FeatureBuilder, prepare_plugin_df
            from analytics.features.plugins.base_plugin import PluginContext
            from state_manager import StateManager

            settings = StateManager().get_app_settings()
            fb = FeatureBuilder()
            df = fb.load_ohlcv(self.symbol, self.timeframe, limit=settings.feature_builder_limit)
            if df is None or df.empty:
                self.run_failed.emit(
                    self.set_definition.get("set_id", ""),
                    f"Keine OHLCV-Daten fuer {self.symbol} {self.timeframe}.",
                )
                return

            df_plugin = prepare_plugin_df(df)
            context = PluginContext(
                symbol=self.symbol,
                timeframe=self.timeframe,
                mode="batch",
                timestamp=int(df_plugin["time"].iloc[-1]) if len(df_plugin) else None,
                settings=settings,
            )
            display = self.set_definition.get("display_name") or self.set_definition.get("set_id") or "Unbenannt"
            self.log_message.emit(f"Ausfuehren: {display} ({self.symbol} {self.timeframe})")

            results = self.evaluator.execute_set(self.set_definition, df_plugin, context=context)
            for iid in results:
                self.log_message.emit(f"  {iid}: fertig")
            self.run_finished.emit(self.set_definition.get("set_id", ""), len(results))
        except Exception as e:
            self.run_failed.emit(self.set_definition.get("set_id", ""), str(e))


class _ServiceSetItemAdapter(NamedItemAdapter):
    """Adapter für die SERVICE-SET-Sammlung im Service-Fenster.

    Phase 13 Schritt 8: Die Service-Set-Verwaltung (Speichern/Löschen) nutzt
    exakt dieselbe generische Preset-Mechanik wie das Indikator-Prop-Fenster
    (NamedItemActionsMixin). Die _item_*-Protokoll-Methoden liegen in diesem
    Adapter und greifen auf das ServiceWindow (self.dlg) zu.
    """

    def __init__(self, dlg: "ServiceWindow") -> None:
        self.dlg = dlg

    def _item_scope_label(self) -> str:
        return "Service-Set"

    def _item_current_name(self) -> str:
        return self.dlg.edit_set_name.text().strip() if self.dlg.edit_set_name else ""

    def _item_current_id(self) -> Optional[str]:
        if self.dlg._current_set_id:
            return self.dlg._current_set_id
        if self.dlg.combo_set:
            return self.dlg.combo_set.currentData()
        return None

    def _item_auto_name(self) -> str:
        """Auto-Name aus den instance_ids (Roadmap: leerer Name → Auto-Name)."""
        try:
            definition = self.dlg.collect_set_definition()
            definition["display_name"] = ""
            return ServiceSetRepository._default_display_name(definition)
        except Exception as e:
            print(f"⚠️ [ServiceWindow] Auto-Name fehlgeschlagen: {e}")
            return ""

    def _item_list_names(self) -> List[str]:
        return [s.get("display_name") or "" for s in self.dlg.set_repo.list_sets()]

    def _item_exists(self, name: str) -> bool:
        """True, wenn ein ANDERES Set bereits diesen Namen trägt."""
        current = self._item_current_id()
        return any(
            (s.get("display_name") or "") == name and s.get("set_id") != current
            for s in self.dlg.set_repo.list_sets()
        )

    def _item_save_as(self, name: str) -> Optional[str]:
        """Speichert das Set unter 'name'; liefert die set_id zurück."""
        definition = self.dlg.collect_set_definition()
        if not definition.get("execution_order"):
            self.dlg.log("Keine Services in der Ausführungs-Reihenfolge – "
                         "Speichern abgebrochen.")
            return None
        if not definition.get("services"):
            self.dlg.log("WARNUNG: Set hat keine services-Konfiguration "
                         "(nur Reihenfolge wird gespeichert).")
        definition["display_name"] = name
        set_id = self.dlg.set_repo.save_set(definition)
        self.dlg.log(f"Set gespeichert: {set_id}")
        return set_id

    def _item_delete_current(self) -> bool:
        set_id = self._item_current_id()
        if not set_id:
            self.dlg.log("Kein Set zum Löschen ausgewählt.")
            return False
        if self.dlg.set_repo.delete_set(set_id):
            self.dlg.log(f"Set gelöscht: {set_id}")
            return True
        self.dlg.log(f"Set '{set_id}' nicht gefunden.")
        return False

    def _item_select(self, set_id: Optional[str] = None) -> None:
        """Setzt die Set-Auswahl nach Speichern (set_id) bzw. Löschen (None)."""
        self.dlg._current_set_id = None  # Neuauswahl erzwingen (sonst bleibt Alt-Selektion)
        self.dlg.refresh_set_list()
        if set_id and self.dlg.combo_set:
            idx = self.dlg.combo_set.findData(set_id)
            if idx >= 0:
                self.dlg.combo_set.setCurrentIndex(idx)

    def _item_reserved_name(self) -> Optional[str]:
        return None  # Service-Sets haben kein geschütztes 'Default'-Set


@register_persistent_window(auto_restore=False)
class ServiceWindow(ContentScrollMixin, NamedItemActionsMixin, PersistentWindow):
    INSTANCE_ID = "win_service"

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
        self._current_set_id: Optional[str] = None
        self._current_set_definition: Optional[Dict[str, Any]] = None

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
        self.check_grid_scan: QCheckBox = self.ui.findChild(QCheckBox, "check_grid_scan")
        self.btn_start: QPushButton = self.ui.findChild(QPushButton, "btn_start_scan")
        self.label_elapsed: QLabel = self.ui.findChild(QLabel, "label_elapsed_value")
        self.progress_bar: QProgressBar = self.ui.findChild(QProgressBar, "progress_bar")
        self.text_log: QTextEdit = self.ui.findChild(QTextEdit, "text_log")

        # Phase 13 Schritt 4: Service-Set-Controls
        self.combo_set: QComboBox = self.ui.findChild(QComboBox, "combo_set")
        self.combo_tf_set: QComboBox = self.ui.findChild(QComboBox, "combo_tf_set")
        self.btn_refresh_sets: QPushButton = self.ui.findChild(QPushButton, "btn_refresh_sets")
        self.edit_set_name: QLineEdit = self.ui.findChild(QLineEdit, "edit_set_name")
        self.list_execution_order: QListWidget = self.ui.findChild(QListWidget, "list_execution_order")
        self.btn_move_up: QPushButton = self.ui.findChild(QPushButton, "btn_move_up")
        self.btn_move_down: QPushButton = self.ui.findChild(QPushButton, "btn_move_down")
        self.btn_remove_instance: QPushButton = self.ui.findChild(QPushButton, "btn_remove_instance")
        self.edit_new_instance: QLineEdit = self.ui.findChild(QLineEdit, "edit_new_instance")
        self.btn_add_instance: QPushButton = self.ui.findChild(QPushButton, "btn_add_instance")
        self.btn_save_set: QPushButton = self.ui.findChild(QPushButton, "btn_save_set")
        self.btn_delete_set: QPushButton = self.ui.findChild(QPushButton, "btn_delete_set")
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
            # 5.4 User-Anpassung: 'Service-Parameter' oben RECHTS direkt neben
            # dem Rahmen 'Service-Sets' (gleiche Zeile, Service-Sets links).
            self.top_row = QHBoxLayout()
            self.top_row.setSpacing(6)
            idx = self.central_layout.indexOf(self.group_service_sets)
            if idx < 0:
                idx = 0
            self.central_layout.removeWidget(self.group_service_sets)
            self.top_row.addWidget(self.group_service_sets)
            self.top_row.addWidget(self.widget_service_columns)
            self.central_layout.insertLayout(idx, self.top_row)
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
        if self.btn_add_instance:
            self.btn_add_instance.clicked.connect(self.add_instance)
            if self.edit_new_instance:
                self.edit_new_instance.returnPressed.connect(self.add_instance)
        if self.btn_save_set:
            self.btn_save_set.clicked.connect(self.save_set)
        if self.btn_delete_set:
            self.btn_delete_set.clicked.connect(self.delete_set)
        if self.btn_execute_set:
            self.btn_execute_set.clicked.connect(self.execute_set)

        # Sofort speichern bei Symbol-Änderung
        if self.combo_symbol:
            self.combo_symbol.currentTextChanged.connect(self.save_state)

        # Set-Dropdown initial befüllen (list_sets() als Quelle)
        self.refresh_set_list()

        # State asynchron wiederherstellen (nach show(), damit move/resize vom Window-Manager akzeptiert werden)
        QTimer.singleShot(0, self.restore_state)

    # --- PersistentWindow-Interface ---

    def get_persistent_symbol(self) -> str:
        return self.combo_symbol.currentText() if self.combo_symbol else "SILVER"

    def get_persistent_timeframe(self) -> str:
        return "H1"

    def _apply_persistent_filters(self, symbol: str, timeframe: str) -> None:
        if self.combo_symbol:
            idx = self.combo_symbol.findText(symbol)
            if idx >= 0:
                self.combo_symbol.setCurrentIndex(idx)

    # --- Scanner ---

    @Slot()
    def start_scan(self):
        if self.scanner and self.scanner.isRunning():
            self.log("Scan laeuft bereits.")
            return

        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        new_scan = self.check_new_scan.isChecked() if self.check_new_scan else False
        grid_scan = self.check_grid_scan.isChecked() if self.check_grid_scan else False

        mode = "GRID PROXIMITY" if grid_scan else "EMA+ATR STANDARD"
        self.log(f"Starte {mode}-Scan: {symbol}, New Scan = {new_scan}")
        self.btn_start.setEnabled(False)
        self._elapsed_seconds = 0
        self.label_elapsed.setText("00:00:00")
        self.progress_bar.setValue(0)
        self._elapsed_timer.start(1000)

        self.scanner = HistoricalScanner(symbol, new_scan, grid_scan)
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
        self.log(f"Scan für {symbol} beendet: {count} Signale geschrieben.")

    @Slot(str)
    def log(self, message: str):
        if self.text_log:
            self.text_log.append(message)

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
        """Leert Name-Feld und execution_order-Liste des Set-Editors."""
        self._current_set_id = None
        self._current_set_definition = None
        if self.edit_set_name:
            self.edit_set_name.clear()
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
        if self.edit_set_name:
            self.edit_set_name.setText(definition.get("display_name") or "")
        if self.list_execution_order:
            self.list_execution_order.clear()
            services = definition.get("services") or {}
            for iid in (definition.get("execution_order") or []):
                cfg = services.get(iid, {})
                plugin_id = cfg.get("plugin_id", "?")
                item = QListWidgetItem(f"{iid}  [{plugin_id}]")
                item.setData(Qt.UserRole, iid)
                item.setData(Qt.UserRole + 1, plugin_id)
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

    @Slot()
    def remove_instance(self) -> None:
        """Entfernt den markierten Service aus der Ausführungs-Reihenfolge."""
        lw = self.list_execution_order
        if not lw or lw.currentRow() < 0:
            return
        lw.takeItem(lw.currentRow())
        self._rebuild_columns()

    @Slot()
    def add_instance(self) -> None:
        """Fügt eine Service-Instanz 'instance_id [plugin_id]' zur Liste hinzu.

        Plugin muss in der PluginRegistry existieren (Default-Params werden
        beim Speichern eines neuen Sets verwendet). Duplikate werden abgelehnt.
        """
        if not self.edit_new_instance or not self.list_execution_order:
            return
        text = self.edit_new_instance.text().strip()
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
            self.log(f"Plugin '{plugin_id}' nicht gefunden (verfügbar: grid_liquidity).")
            return

        for i in range(self.list_execution_order.count()):
            if self.list_execution_order.item(i).data(Qt.UserRole) == iid:
                self.log(f"instance_id '{iid}' existiert bereits.")
                return

        item = QListWidgetItem(f"{iid}  [{plugin_id}]")
        item.setData(Qt.UserRole, iid)
        item.setData(Qt.UserRole + 1, plugin_id)
        self.list_execution_order.addItem(item)
        self.edit_new_instance.clear()
        self.log(f"Service hinzugefügt: {iid} [{plugin_id}]")
        self._rebuild_columns()

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

        return {
            "set_id": self._current_set_id or "",
            "display_name": self.edit_set_name.text().strip() if self.edit_set_name else "",
            "execution_order": order,
            "services": services,
        }

    # =========================================================================
    # Phase 13 5.4 Schritt 1: Breiten- & Höhendynamisches Layout (Service-Spalten)
    # =========================================================================

    @staticmethod
    def _is_visual_key(key: str) -> bool:
        """Konvention für reine Darstellungs-Props: Sichtbarkeit (show_*) + Farben (color).

        Darstellungs-Parameter gehören NICHT ins Service-Set (nur Berechnungs-
        Logik, Roadmap 5.4.1.2) und werden daher in den Service-Spalten
        ausgeblendet (konsistent zum Indikator-Dialog).
        """
        if key.startswith("show_"):
            return True
        if "color" in key.lower():
            return True
        return False

    @staticmethod
    def _human(key: str) -> str:
        return key.replace("_", " ").title()

    @staticmethod
    def _decimal_places(value: Any) -> int:
        """Nachkommastellen eines float (für QDoubleSpinBox.setDecimals)."""
        if not isinstance(value, float) or value != value:  # NaN-Schutz
            return 4
        s = f"{value:.10f}".rstrip("0")
        if "." in s:
            return len(s.split(".")[1])
        return 0

    def _create_param_control(self, key: str, val: Any, spec: Dict[str, Any]) -> QWidget:
        """Erzeugt ein Eingabe-Widget exakt aus dem ParameterSchema.

        float -> QDoubleSpinBox, int -> QSpinBox, bool -> QCheckBox,
        choice -> QComboBox, color/str -> QLineEdit. min/max/step werden 1:1
        übertragen (Roadmap 5.4.2.2).
        """
        p_type = spec.get("type")
        if p_type == "float":
            spin = QDoubleSpinBox()
            spin.setRange(float(spec.get("min", -1e9)), float(spec.get("max", 1e9)))
            step = spec.get("step")
            decimals = self._decimal_places(step) if step is not None else self._decimal_places(spec.get("default"))
            spin.setDecimals(min(6, max(0, decimals)))
            spin.setSingleStep(float(step) if step is not None else 0.01)
            try:
                spin.setValue(float(val))
            except (TypeError, ValueError):
                spin.setValue(float(spec.get("default", 0.0)))
            return spin
        if p_type == "int":
            spin = QSpinBox()
            spin.setRange(int(spec.get("min", -100000)), int(spec.get("max", 100000)))
            spin.setSingleStep(int(spec.get("step", 1)))
            try:
                spin.setValue(int(val))
            except (TypeError, ValueError):
                spin.setValue(int(spec.get("default", 0)))
            return spin
        if p_type == "bool":
            chk = QCheckBox()
            chk.setChecked(bool(val))
            return chk
        if p_type == "choice":
            combo = QComboBox()
            combo.addItems([str(o) for o in (spec.get("options") or [])])
            combo.setCurrentText(str(val))
            return combo
        txt = QLineEdit()
        txt.setText(str(val))
        return txt

    @staticmethod
    def _ctrl_value(ctrl: QWidget) -> Any:
        """Liest den aktuellen Wert eines Controls typsicher aus."""
        if isinstance(ctrl, QCheckBox):
            return ctrl.isChecked()
        if isinstance(ctrl, QSpinBox):
            return ctrl.value()
        if isinstance(ctrl, QDoubleSpinBox):
            return ctrl.value()
        if isinstance(ctrl, QComboBox):
            return ctrl.currentText()
        return ctrl.text()

    def _setup_collapsible(self, group: QGroupBox) -> None:
        """Macht eine ausklappbare QGroupBox wirklich kollabierbar.

        Beim Abwählen werden die Kinder ausgeblendet und die Fensterhöhe per
        _reflow() nahtlos verkleinert (Roadmap 5.4.2.2: Ein-/Ausklappen
        verändert die Höhe dynamisch). Zusätzlich wird group.updateGeometry()
        gerufen, damit der gecachte QWidgetItemV2-sizeHint der Box invalidiert
        wird (Qt 6.11: Layouts refreshen diesen Cache sonst NICHT).
        """
        def _toggle(checked: bool) -> None:
            for child in group.findChildren(QWidget):
                child.setVisible(checked)
            group.updateGeometry()  # QWidgetItemV2-Cache invalidieren (s. oben)
            self._reflow()
        group.toggled.connect(_toggle)
        _toggle(group.isChecked())

    def _reflow(self) -> None:
        """Erzwingt die Neuberechnung der Layouts (dynamische Höhe/Breite).

        Qt 6.11: QWidgetItemV2 cached den sizeHint eines Widgets beim ersten
        Zugriff und aktualisiert ihn NICHT, wenn der Inhalt später wächst –
        selbst layout.invalidate() hilft nicht. Daher werden die Caches der
        betroffenen Widgets explizit per updateGeometry() invalidiert
        (invalidateSizeCache) und die Layout-Caches geleert.

        WICHTIG: Die Fenstergröße wird DEFERRED (nächste Event-Loop-Runde)
        angepasst. Beim Set-Wechsel sind die alten Service-Spalten per
        deleteLater() noch im Widget-Baum; bis sie zerstört sind, melden die
        Layout-Caches einen veralteten (zu kleinen) sizeHint (z.B. 18x18 für
        eine volle Spalten-Zeile). Ein synchrones resize würde das Fenster
        daher fälschlich schrumpfen. _schedule_reflow() zerstört die
        deleteLater-Widgets und berechnet die Größe erst aus dem konsistenten
        Zustand (ContentScrollMixin).
        """
        self._schedule_reflow()

    def _clear_service_columns(self) -> None:
        """Entfernt alle Service-Spalten aus dem service_columns_layout."""
        if self.service_columns_layout is None:
            return
        while self.service_columns_layout.count():
            item = self.service_columns_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._service_param_controls = {}

    def _build_service_columns(self, set_definition: Dict[str, Any]) -> None:
        """Baut die dynamischen Service-Spalten (Roadmap 5.4.2.2).

        Für jede instance_id in execution_order wird eine QGroupBox-Spalte im
        service_columns_layout erzeugt. Jede Spalte skaliert in der Höhe exakt
        mit der Anzahl ihrer Parameter (QSizePolicy.Maximum); die Fensterbreite
        wächst mit der Anzahl der Spalten nach rechts – ohne leeren Raum und
        ohne fixe Pixelwerte.
        """
        if self.service_columns_layout is None:
            return
        self._clear_service_columns()
        services = set_definition.get("services") or {}
        for iid in (set_definition.get("execution_order") or []):
            cfg = services.get(iid) or {}
            pid = cfg.get("plugin_id") or iid
            col = self._build_service_column(iid, pid, cfg)
            self.service_columns_layout.addWidget(col)
        # Container erneut in die obere Zeile einfügen: Das QWidgetItem
        # eines Widgets meldet dessen Größe zum Zeitpunkt des Einfügens und
        # aktualisiert sich bei späterem Inhalts-Wachstum nicht (Qt-Quirk).
        # Entfernen + erneutes Einfügen erzeugt ein frisches QWidgetItem mit
        # der aktuellen Größe.
        if self.top_row is not None and self.widget_service_columns is not None:
            self.top_row.removeWidget(self.widget_service_columns)
            self.top_row.addWidget(self.widget_service_columns)
        self._reflow()

    def _build_service_column(self, iid: str, pid: str, cfg: Dict[str, Any]) -> QGroupBox:
        """Erzeugt EINE Service-Spalte (QGroupBox) mit Parameter-Formular.

        - Normale Parameter im QFormLayout (float/int/bool nach Schema).
        - expert: True (inkl. lookback) in einer einklappbaren
          QGroupBox 'Experten-Optionen' am Spaltenfuß.
        """
        col = QGroupBox(f"{iid}  [{pid}]")
        # 5.4.2.2 Punkt 3: Spalte skaliert in der Höhe exakt mit ihrem Inhalt
        # (endet unter dem letzten Parameter), wächst beim Vergrößern des
        # Fensters NICHT mit.
        col.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        vl = QVBoxLayout(col)
        vl.setAlignment(Qt.AlignTop)

        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(pid)
        except KeyError:
            vl.addWidget(QLabel(f"Plugin '{pid}' nicht gefunden."))
            return col

        full_schema: Dict[str, Any] = dict(getattr(plugin, "base_parameter_schema", None) or {})
        full_schema.update(dict(plugin.parameter_schema or {}))
        order = list(getattr(plugin, "parameter_order", None) or (plugin.parameter_schema or {}).keys())
        for key in (getattr(plugin, "base_parameter_schema", None) or {}):
            if key not in order:
                order.append(key)
        labels = dict(getattr(plugin, "param_labels", None) or {})
        for key, spec in (getattr(plugin, "base_parameter_schema", None) or {}).items():
            labels.setdefault(key, spec.get("description") or self._human(key))

        params = dict(cfg.get("params") or {})
        lookback = cfg.get("lookback")

        # Normale (Nicht-Expert-, Nicht-Darstellungs-)Parameter
        form = QFormLayout()
        for key in order:
            spec = full_schema.get(key, {})
            if spec.get("expert") or self._is_visual_key(key):
                continue
            cval = params.get(key, spec.get("default"))
            ctrl = self._create_param_control(key, cval, spec)
            self._service_param_controls[(iid, key)] = ctrl
            form.addRow(labels.get(key, self._human(key)), ctrl)
        vl.addLayout(form)

        # Expert-Parameter (inkl. lookback als Service-Instanz-Einstellung)
        expert_keys = [k for k in order if full_schema.get(k, {}).get("expert")]
        if expert_keys:
            exp_grp = QGroupBox("Experten-Optionen")
            exp_grp.setCheckable(True)
            exp_grp.setChecked(False)
            exp_grp.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            ef = QFormLayout(exp_grp)
            for key in expert_keys:
                spec = full_schema.get(key, {})
                if key == "lookback":
                    cval = lookback if lookback is not None else spec.get("default")
                else:
                    cval = params.get(key, spec.get("default"))
                ctrl = self._create_param_control(key, cval, spec)
                self._service_param_controls[(iid, key)] = ctrl
                ef.addRow(labels.get(key, self._human(key)), ctrl)
            vl.addWidget(exp_grp)
            self._setup_collapsible(exp_grp)

        return col

    def _rebuild_columns(self) -> None:
        """Baut die Service-Spalten aus dem aktuellen Editor-Zustand neu."""
        if self.service_columns_layout is None:
            return
        definition = self.collect_set_definition()
        self._build_service_columns(definition)

    @Slot()
    def save_set(self) -> None:
        """Speichert das aktive Set – analog zur Preset-Verwaltung (generisch).

        Namensdialog (vorbelegt), leerer Name → Auto-Name aus den instance_ids
        (z.B. 'grid_1 + prox_1'), Überschreiben-Rückfrage bei doppeltem Namen.
        Implementierung: NamedItemActionsMixin.save_named_item() mit dem
        Service-Set-Adapter (_ServiceSetItemAdapter).
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
        """
        self.delete_named_item(self._set_adapter)

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
            self.btn_execute_set.setEnabled(False)
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
        self.log(f"Set-Ausführung abgeschlossen: {count} Services.")

    @Slot(str, str)
    def _on_set_run_failed(self, set_id: str, error: str) -> None:
        if self.btn_execute_set:
            self.btn_execute_set.setEnabled(True)
        self.log(f"FEHLER bei Set-Ausführung: {error}")

    def closeEvent(self, event):
        # PersistentWindow.save_state() wird in super().closeEvent gerufen
        if self.scanner and self.scanner.isRunning():
            self.scanner.stop()
            self.scanner.wait(2000)
        if self._set_run_worker and self._set_run_worker.isRunning():
            self._set_run_worker.wait(2000)
        self._elapsed_timer.stop()
        super().closeEvent(event)
