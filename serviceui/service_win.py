# serviceui/service_win.py
"""
Service-Kontrollfenster für PyTrader.
Service-Set-Verwaltung, Parameter-Editor und gezielte Service-Ausführung
(MasterTree-Kontextmenü -> ServiceRunWorker). Der globale Historical Scanner
wurde am 05.08.2026 ersatzlos entfernt – Ausführung nur noch zielgerichtet.
Mit automatischem State Persistence via PersistentWindow.

Phase 13 Schritt 4: Zusätzlich Service-Set-Verwaltung (ServiceSetRepository +
ServiceSetEvaluator): Set-Auswahl (list_sets()), execution_order-Anzeige mit
Up/Down-Umsortierung, Name (leer → Auto-Name), Speichern/Löschen (mit
QMessageBox-Rückfrage) und Ausführen (ServiceSetEvaluator im Hintergrund).

Phase 15 Kapitel 15.1 (U15-D1): Modularisierung – die gewachsene Datei wurde
in den Unterordner serviceui/ verschoben und in Module zerlegt (Verhalten
unverändert):
  * service_set_utils.py   – _available_plugin_ids, _sets_using_plugin
  * param_columns.py       – ServiceParamColumnsMixin (Parameter-Column-Builder)
  * trash_dialog.py        – ServiceSetTrashDialog (Papierkorb-Dialog)
Diese Datei re-exportiert die öffentliche API, damit bestehende Aufrufe
(main.py, Tests) weiter funktionieren.
"""

from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QFile, QIODevice, QSize, QTimer, Qt, Slot
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QGroupBox, QHBoxLayout,
    QInputDialog, QLabel, QMenu,
    QMessageBox, QProgressBar, QPushButton, QSplitter, QTextEdit,
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

from analytics.engine.description_dialog import (
    ServiceDescriptionDialog,
    ServiceDescriptionEditDialog,
)
from analytics.engine.service_models import generate_instance_hash
from analytics.engine.service_set_repository import ServiceSetRepository
from analytics.engine.set_evaluator import ServiceSetEvaluator
from persistent_win import PersistentWindow, register_persistent_window
from scrollable_content import ContentScrollArea, ContentScrollMixin
from chart.widgets.named_item_actions import NamedItemActionsMixin

# Phase 15 U15-D1: Submodule der Service-UI
from serviceui.service_set_utils import (
    _available_plugin_ids,
    _sets_using_plugin,
    variant_run_entries,
)
from serviceui.param_columns import ServiceParamColumnsMixin
from serviceui.trash_dialog import ServiceSetTrashDialog
from serviceui.new_set_dialog import NewServiceSetDialog
# 05.08.2026: Gezielter Run-Worker fuer die MasterTree-Kontextmenue-Aktionen
# ('▶️ Diesen Service ausführen' / '▶️ Alle Services ausführen') – persistiert
# den feature_store_payload und emittiert den EventBus (Datum live im Baum).
# U15-E (05.08.2026): ALL_TIMEFRAMES = Sentinel fuer Multi-TF-Ausfuehrung.
from serviceui.run_worker import ALL_TIMEFRAMES, ServiceRunWorker
# 21.01b (11.08.2026): TF-Status-Pills (Pill-Strip) – zeigt je Timeframe die
# feature_store-Belegung des gewaehlten Services (fetch_service_tf_status).
from analytics.engine.feature_store_reader import FeatureStoreReader
from serviceui.common_widgets import TfStatusBadgeBar

# Phase 15 15.01: Symbol- & Favoriten-Verwaltung (SymbolsWindow + EventBus)
from serviceui.symbols_win import SymbolsWindow
from symbol_repository import SymbolRepository, get_symbol_repository
from config.event_bus import event_bus

# Phase 15 15.02: Service-UI Refactoring – MasterTree & generischer
# ServiceSelector (ServiceSelectorWidget im Modus FULL_EDIT).
from serviceui.service_selector_widget import ServiceSelectorWidget

# Projekt-Root (eine Ebene über serviceui/) – für die UI-Datei unter ui/.
BASE_DIR = Path(__file__).resolve().parent.parent


@register_persistent_window()  # auto_restore=True (Bugfix 05.08.2026)
class ServiceWindow(ServiceParamColumnsMixin, ContentScrollMixin, NamedItemActionsMixin, PersistentWindow):
    INSTANCE_ID = "win_service"
    # Bugfix 06.08.2026 (User-Anweisung, History-Bug): auto_restore=True
    # bleibt – war das Fenster beim Beenden der App OFFEN, wird es beim
    # naechsten Start wiederhergestellt (Save & Restore wie AnalyticsWindow).
    # _keep_history_on_close=False (NEU): Ein MANUELL geschlossenes
    # ServiceWindow (X) wird aus der Fenster-Historie entfernt
    # (delete_instance) und beim naechsten App-Start NICHT wiederhergestellt.
    # Die FENSTERPOSITION ueberlebt das manuelle Schliessen ueber
    # global_settings (save_dialog_geometry in save_state) und wird beim
    # naechsten manuellen Oeffnen ueber den Service-Button wiederhergestellt
    # (Fallback in restore_state, DIALOG_GEOMETRY_KEY).
    _keep_history_on_close = False
    #: Geometrie-Key fuer die POSITION, die ein manuelles Schliessen
    #: ueberlebt (global_settings, vgl. IndicatorSettingsDialog-Muster).
    DIALOG_GEOMETRY_KEY = "win_service"
    # 05.08.2026: Die FensterGROESSE folgte exakt dem Inhalt (auch schrumpfen).
    # 11.08.2026 (Bugfix Runde 17c, User-Meldung 4/5): Umgestellt – der INHALT
    # folgt jetzt dem FENSTER (normales resizable Fenster): _exact_fit_to_content
    # = False bedeutet 'nur wachsen, nie schrumpfen' (Mixin-Pfad). Das Fenster
    # kann manuell grossgezogen und maximiert werden; widgetResizable=True
    # streckt den Inhalt auf den Viewport (Splitter, MasterTree, Param-Box).
    _exact_fit_to_content = False
    # 11.08.2026 (Bugfix, Slider): Mindest-Breite des FENSTERS ueber der
    # Splitter-Minima-Summe (Tree 400 + Panel 520 = 920). Dadurch hat der
    # QSplitter IMMER Spielraum - der Slider zwischen den beiden Hauptrahmen
    # bleibt beweglich, auch wenn der Inhalt schmal ist (vorher klebte das
    # Fenster exakt am Inhalt und der Slider war fixiert). ContentScrollMixin
    # resizet das Inhalt-Widget dabei auf die Fensterbreite (Splitter fuellt
    # den Spielraum). Screen-Klemme schuetzt kleine Bildschirme.
    _min_window_width = 1100

    def __init__(self, parent=None, service_set_repo: Optional[ServiceSetRepository] = None):
        super().__init__(parent)

        # Phase 13 Schritt 4: Service-Set-Verwaltung
        self.set_repo: ServiceSetRepository = service_set_repo or ServiceSetRepository()
        self.set_evaluator = ServiceSetEvaluator()
        # 05.08.2026: Worker fuer die gezielte Kontextmenue-Ausfuehrung
        # (MasterTree '▶️ Service(s) ausführen') – FeatureStore-Persistenz.
        self._run_worker: Optional[ServiceRunWorker] = None
        # 21.01b: Plugin-ID des aktuell im Pill-Strip angezeigten Services.
        self._badge_plugin_id: Optional[str] = None
        self._current_set_id: Optional[str] = None
        self._current_set_definition: Optional[Dict[str, Any]] = None
        # 17.01.04 (Bugfix): Standalone-Plugin-Editierung – ist eine
        # Plugin-Zeile unter 'Services' (Kategorie-Ordner) im Parameter-
        # Editor geladen, haelt dieses Feld die plugin_id. Die gespeicherten
        # Parameter liegen in global_settings (Key 'plugin_params_<pid>').
        self._current_plugin_editing: Optional[str] = None
        # 10.08.2026 (Bugfix, Varianten-Params): Wird ein Clone-Knoten
        # (Preset/Variante) editiert, haelt dieses Feld das Preset-Dict aus
        # indicator_presets (indicator_id, preset_name, is_active_batch,
        # doc_log) - der Save-Pfad schreibt dann in das Preset statt in
        # global_settings (plugin_params_<pid>).
        self._current_preset_editing: Optional[Dict[str, Any]] = None
        # USER-REQ (P14-03): Preisskala-Praezision je Symbol fuer die 6
        # Custom-Level-Eingabefelder (prox_level1..6). Lazy + gecacht.
        self._symbol_precision: Optional[int] = None
        # Phase 16 (05.08.2026): Concurrency-Guard – Referenzzähler für die
        # pausierten 45s-Hintergrund-Syncs (sync_timer in main.py). Bei
        # jedem beginnenden Service-Run wird das EventBus-Signal
        # service_run_started emittiert (nur beim Übergang 0→1), nach dem
        # letzten Abschluss service_run_finished (1→0). Dadurch wird der
        # Sync-Timer für die Dauer intensiver Berechnungen geblockt.
        self._sync_guard_count: int = 0


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
        self.text_log: QTextEdit = self.ui.findChild(QTextEdit, "text_log")

        # 05.08.2026 (U15-E): Timeframe-Control in der Filterleiste (neben dem
        # Symbol-Dropdown) – steuert die gezielte Kontextmenue-Ausfuehrung
        # (MasterTree '▶️ Service(s) ausführen'). 'ALLE Timeframes' (Index 0,
        # Sentinel ALL_TIMEFRAMES) fuehrt alle verfuegbaren Timeframes aus.
        self.combo_tf: QComboBox = self.ui.findChild(QComboBox, "combo_tf")
        # Phase 14 P14-05: Papierkorb-Button (Soft-Delete/Wiederherstellung)
        self.btn_trash_sets: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_trash_sets")
        # 05.08.2026 (Kleinere Einstellungen): Das Log wird in die LINKE
        # Splitter-Spalte UNTER den MasterTree verschoben (Breite = Tree-Breite)
        # und auf 4 Zeilen Hoehe begrenzt. Das Fenster endet dadurch exakt
        # unter dem Log (siehe right_panel-Aufbau weiter unten).
        if self.text_log:
            fm = self.text_log.fontMetrics()
            # 11.08.2026 (User-Nachtrag): Log-Hoehe 6 Zeilen = 2 Zeilen
            # HOEHER als die 4-Zeilen-Stufe (die 10.08.-Reduktion auf 2 ist
            # damit zweifach ueberholt).
            self.text_log.setMaximumHeight(fm.lineSpacing() * 6 + 12)
            self.text_log.setMinimumHeight(fm.lineSpacing() * 6 + 12)

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
        self.widget_service_columns = QGroupBox("Service-Parameter")
        self.widget_service_columns.setObjectName("widget_service_columns")
        self.service_columns_layout = QHBoxLayout(self.widget_service_columns)
        self.service_columns_layout.setSpacing(6)
        # Inhalt-Widget + Layout VOR dem Scroll-Wrapper referenzieren.
        # 11.08.2026 (Bugfix Runde 17c, User-Meldung 4): self.ui ist seit der
        # .ui-Umstellung (QMainWindow -> QWidget) das WIDGET mit dem Layout
        # selbst (kein centralwidget-Zwischenschritt mehr). Das frueher hier
        # eingebettete QMainWindow wuchs NICHT mit dem Fenster (Qt verlangt
        # QMainWindow nur als Top-Level) - Ursache fuer 'Grossziehen ohne
        # Anpassung'. install_content_scroll setzt die ScrollArea jetzt direkt
        # als CentralWidget von self (siehe unten).
        self.content_widget = self.ui
        self.central_layout = self.content_widget.layout() if self.content_widget else None
        if self.central_layout is not None:
            # Bugfix 05.08.2026 (Layout-Bereinigung Phase 13): ZWEI-SPALTEN-
            # Splitter statt Drei-Spalten - die Service-Sets-Box (Phase 13)
            # ist ersatzlos entfernt (alle Funktionen im MasterTree/Kontext-
            # menue bzw. im Parameterfenster der rechten Spalte).
            #  * Spalte 1 (links):  MasterTree (Service tree) - volle Hoehe.
            #  * Spalte 2 (rechts): Service-Parameter-Box (widget_service_
            #                       columns) in einer ContentScrollArea mit
            #                       max. Hoehe/Breite + Scrollbalken,
            #                       darunter fest die Aktions-Leiste
            #                       [Speichern] / [Speichern & Ausfuehren].
            # Die Status-Zeile (Laufzeit/Fortschritt) bleibt im central_layout
            # direkt UNTER dem Splitter (= unter der hoechsten Box).
            self.top_row = QHBoxLayout()
            self.top_row.setSpacing(6)
            # Splitter direkt NACH der Filter-/Symbol-Zeile (layout_symbol,
            # Index 0) einfuegen. Die frueheren Scan-Widgets (btn_start_scan,
            # layout_status) sind am 05.08.2026 ersatzlos entfernt – Status
            # + Log liegen darunter im central_layout.
            idx = 1

            # Spalte 1: MasterTree (Service tree)
            self.right_panel = QWidget()
            right_layout = QVBoxLayout(self.right_panel)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(6)
            # MasterTree im Modus B / FULL_EDIT (seit 05.08.2026 ohne Toolbar)
            self.service_selector = ServiceSelectorWidget(
                mode=ServiceSelectorWidget.MODE_FULL_EDIT, parent=self)
            right_layout.addWidget(self.service_selector, 1)
            # 12.08.2026 (User-Meldung 2): Fortschrittsbalken fuer
            # Service-Runs unter dem MasterTree (ueber dem Log) - zeigt
            # je Service den Fortschritt ueber alle Services des
            # aktuellen Timeframes (ServiceRunWorker.service_progress).
            self.progress_label = QLabel("")
            self.progress_bar = QProgressBar()
            self.progress_bar.setMaximum(0)   # Busy bis zum 1. Wert
            self.progress_bar.setFixedHeight(16)
            self.progress_bar.setTextVisible(False)
            progress_row = QHBoxLayout()
            progress_row.setSpacing(6)
            progress_row.addWidget(self.progress_label, 3)
            progress_row.addWidget(self.progress_bar, 2)
            progress_widget = QWidget()
            progress_widget.setLayout(progress_row)
            right_layout.addWidget(progress_widget, 0)
            # 05.08.2026 (Kleinere Einstellungen, Punkt 5): Das Log wandert
            # UNTER den MasterTree in dieselbe Spalte – seine Breite entspricht
            # damit exakt der Tree-Breite, und das Fenster endet unten exakt
            # unter dem Log (Punkt 3). Das QTextEdit wird dabei automatisch aus
            # dem central_layout (verticalLayout) umgehaengt.
            if self.text_log:
                right_layout.addWidget(self.text_log, 0)
            # Mindest-Breite, damit eingerueckte Texte (LEVEL_INDENT) lesbar
            # sind; die Maximalbreite entfaellt im 2-Spalten-Layout (der Tree
            # bekommt den groesseren Anteil, die Parameter-Spalte bleibt
            # min. 320px breit).
            try:
                self.service_selector.master_tree.setMinimumWidth(400)
            except (RuntimeError, AttributeError):
                pass

            # Spalte 2: Service-Parameter-Box + Aktions-Leiste
            self._param_panel = QWidget()
            # 10.08.2026 (Bugfix, Slider): Das 960px-Minimum addierte sich mit
            # dem Tree-Minimum (400px) auf ~1360px - der QSplitter hatte
            # praktisch keinen Spielraum, der Slider war unbeweglich. Das
            # Panel-Minimum ist jetzt schlank (520px); bei schmalerem Panel
            # zeigt die ContentScrollArea horizontale Scrollbalken.
            self._param_panel.setMinimumWidth(520)
            param_layout = QVBoxLayout(self._param_panel)
            param_layout.setContentsMargins(0, 0, 0, 0)
            param_layout.setSpacing(6)
            # 21.01b (11.08.2026): TF-Status-Pills (Pill-Strip) am Kopf der
            # Parameter-/Status-Spalte – pro Timeframe die feature_store-
            # Belegung des aktuell gewaehlten Services. Wird bei der
            # Service-Auswahl (_on_master_selection_details) und nach jedem
            # Run neu geladen (fetch_service_tf_status).
            self.badge_bar = TfStatusBadgeBar()
            param_layout.insertWidget(0, self.badge_bar)
            # 05.08.2026 (Kleinere Einstellungen, Punkt 2): max. Hoehe der
            # Parameter-Box VERDOPPELT (620 -> 1240), damit Tree UND Box
            # standardmaessig doppelt so hoch sind; die max. BREITE bleibt so
            # bemessen, dass ZWEI Service-Spalten nebeneinander OHNE
            # horizontalen Scrollbalken passen - bei mehr Services/Spalten
            # scrollt die ContentScrollArea.
            self._param_scroll = ContentScrollArea()
            # 11.08.2026 (Bugfix Runde 17c, User-Meldung 5): widgetResizable
            # = True + KEINE max. Breite/Hoehe mehr – die Service-Parameter-
            # Box passt sich der Fenstergroesse an (vorher auf 1000x1240
            # gedeckelt; beim Grossziehen blieb sie stehen).
            self._param_scroll.setWidgetResizable(True)
            self._param_scroll.setWidget(self.widget_service_columns)
            param_layout.addWidget(self._param_scroll, 1)
            # Aktions-Leiste direkt UNTER der Parameter-Box - [Speichern]
            # persistiert die Parameter-Aenderungen ohne Neuberechnung;
            # [Speichern & Ausfuehren] speichert und stoesst sofort den
            # Service-Run an (ServiceRunWorker, kein Schwerlast-Scan).
            # Feste Position ausserhalb der ScrollArea -> immer sichtbar.
            self._param_action_row = QHBoxLayout()
            self._param_action_row.setSpacing(6)
            self.btn_save_params = QPushButton("✔ Speichern")
            self.btn_save_run_params = QPushButton(
                "▶ Speichern & Ausführen")
            self.btn_save_params.setToolTip(
                "Speichert die aktuellen Parameter-Aenderungen im Set "
                "(app_data.duckdb) und entfernt das '*' im Baum.")
            self.btn_save_run_params.setToolTip(
                "Speichert die Aenderungen UND stoesst sofort die "
                "Neuberechnung an (Bestaetigungsabfrage mit Symbol/Timeframe).")
            # Nur bei manueller Parameter-Aenderung (Dirty) sichtbar.
            self.btn_save_params.setVisible(False)
            self.btn_save_run_params.setVisible(False)
            self._param_action_row.addWidget(self.btn_save_params)
            self._param_action_row.addWidget(self.btn_save_run_params)
            self._param_action_row.addStretch(1)
            param_layout.addLayout(self._param_action_row)

            self.main_splitter = QSplitter(Qt.Horizontal)
            self.main_splitter.addWidget(self.right_panel)
            self.main_splitter.addWidget(self._param_panel)
            # 11.08.2026 (Bugfix, Slider): KEINE setStretchFactor-Aufrufe mehr -
            # die 3:2-Faktoren erzwangen bei jedem Fenster-Reflow die Verteilung
            # und machten den Slider zaeh (die Anwenderposition sprang zurueck).
            # Der QSplitter behaelt jetzt die vom Anwender gezogene Position.
            # Keine Spalte unter ihre Mindestgroesse kollabieren lassen.
            self.main_splitter.setCollapsible(0, False)
            self.main_splitter.setCollapsible(1, False)
            # 11.08.2026 (Bugfix, Slider): Der Handle wird dicker (8px statt
            # 4px Default) - besser greifbar/ziehbar.
            self.main_splitter.setHandleWidth(8)
            # 10.08.2026 (Bugfix, Slider): Startgroessen einmalig setzen -
            # danach behaelt der QSplitter die Position des Anwenders
            # (_resize_param_box_deferred waechst nur noch, siehe
            # param_columns.py).
            self.main_splitter.setSizes([460, 820])

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
        self.install_content_scroll(self.content_widget, install_to=self)
        # 11.08.2026 (Bugfix Runde 17c, User-Meldung 4): widgetResizable=True
        # – die ContentScrollArea streckt das Inhalt-Widget auf den Viewport.
        # Beim manuellen Grossziehen (Rahmen/Ecke) wachsen Splitter, MasterTree
        # und Param-Box mit (vorher widgetResizable=False: Inhalt blieb stehen,
        # das Fenster wurde nur leer groesser). Nur ServiceWindow; der
        # IndicatorSettingsDialog (anderer Mixin-Nutzer) bleibt unveraendert.
        if self.content_scroll is not None:
            self.content_scroll.setWidgetResizable(True)
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
            # 11.08.2026 (Bugfix Runde 17d, User-Meldungen 4+5): KEIN
            # setAlignment(AlignTop|AlignLeft) mehr - es HIELT die Layout-
            # Verteilung an: Der QSplitter (MasterTree | Parameter-Box) blieb
            # auf seiner Mindest-Hoehe stehen, obwohl das Fenster groesser
            # gezogen/maximiert wurde (extra Raum blieb als Leerflaeche
            # unterhalb des Splitters). Mit widgetResizable=True +
            # _exact_fit_to_content=False folgt der INHALT dem FENSTER: Der
            # Splitter faengt das Wachstum ab und verteilt es an MasterTree
            # (Hoehe!) und Parameter-Box (Breite + Hoehe).
        self._service_param_controls: Dict[Any, QWidget] = {}
        # Phase 14 P14-01: Beschreibungs-Eingabefelder der Service-Instanzen
        self._service_desc_controls: Dict[str, QWidget] = {}

        # Phase 14 P14-05: Papierkorb-Dialog (Soft-Delete)
        if self.btn_trash_sets:
            self.btn_trash_sets.clicked.connect(self.show_trash_dialog)
        # Phase 15 (Dirty-State): Parameter-Panel-Aktionsleiste (Speichern /
        # Speichern & Ausführen) – siehe _save_params_from_panel /
        # _save_and_run_from_panel.
        if self.btn_save_params:
            self.btn_save_params.clicked.connect(self._save_params_from_panel)
        if self.btn_save_run_params:
            self.btn_save_run_params.clicked.connect(self._save_and_run_from_panel)

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

        # Phase 15 15.02: MasterTree/ServiceSelector (FULL_EDIT) verdrahten –
        # Kontextmenue-Aktionen auf die bestehenden Set-Methoden + EventBus-
        # Sync. Die fruehere Aktions-Toolbar oberhalb des Baums ist entfernt
        # (05.08.2026) – der MasterTree hat die volle vertikale Hoehe.
        self._wire_selector_toolbar()

        self.log(f"Verfügbare Plugins: {_available_plugin_ids()}")

        # State asynchron wiederherstellen (nach show(), damit move vom
        # Window-Manager akzeptiert werden). Die POSITION wird restauriert
        # (Punkt 1); direkt danach setzt der Reflow das Fenster exakt auf den
        # Inhalt (Breite = Tree+Box, Hoehe = bis Log-Unterkante, Punkte 3+4).
        QTimer.singleShot(0, self.restore_state)
        QTimer.singleShot(0, self._apply_reflow_size)

    # --- PersistentWindow-Interface ---

    def save_state(self) -> None:
        """Persistiert Fenster-POSITION und -GROESSE (05.08.2026, Punkt 1).

        11.08.2026 (Bugfix Runde 17c): Seit _exact_fit_to_content=False folgt
        der Inhalt dem Fenster – die GROESSE wird jetzt wiederhergestellt
        (restore_state), damit die manuell gezogene/Maximize-Groesse des Users
        erhalten bleibt. Position + Symbol/Timeframe bleiben weiterhin erhalten.

        06.08.2026 (History-Bug): Die POSITION wird zusaetzlich in
        global_settings gesichert (save_dialog_geometry). Beim manuellen
        Schliessen loescht delete_instance den window_instances-Eintrag
        (_keep_history_on_close=False) – die Position ueberlebt das und wird
        beim naechsten manuellen Oeffnen ueber den Fallback in
        restore_state() wiederhergestellt (User-Anweisung 06.08.2026).
        """
        inst_id = self.get_instance_id()
        if not inst_id:
            return
        p = self.pos()
        self._state_manager.save_window_geometry(
            inst_id, p.x(), p.y(), self.width(), self.height(), self.isMaximized())
        try:
            self._state_manager.save_dialog_geometry(
                self.DIALOG_GEOMETRY_KEY, p.x(), p.y(),
                self.width(), self.height())
        except Exception:
            pass
        symbol = self.get_persistent_symbol()
        tf = self.get_persistent_timeframe()
        if symbol and tf:
            self._state_manager.save_instance_state(
                instance_id=inst_id, symbol=symbol, timeframe=tf)

    def restore_state(self) -> None:
        """Stellt NUR die Fenster-POSITION wieder her (05.08.2026, Punkt 1).

        Die Groesse wird hier bewusst NICHT angewendet – der Inhalt-Reflow
        (resize_to_clamped_content) setzt das Fenster exakt auf min(Inhalt,
        Bildschirm). Die gespeicherte Breite/Hoehe waere sonst stale
        (z.B. schmaler als die Parameter-Box).

        06.08.2026 (History-Bug): Nach einem MANUELLEN Schliessen wurde der
        window_instances-Eintrag geloescht (delete_instance). Die Position
        liegt dann in global_settings (save_dialog_geometry in save_state)
        und wird hier als Fallback wiederhergestellt – so bleibt die
        Fensterposition beim erneuten manuellen Oeffnen erhalten, ohne dass
        das Fenster beim App-Start automatisch restauriert wird.
        """
        inst_id = self.get_instance_id()
        if not inst_id:
            return
        # Window-Flags korrigieren (QUiLoader setzt oft Qt.Tool | Qt.Dialog).
        # 11.08.2026 (Bugfix Runde 17c): Nur wenn das Fenster noch NICHT
        # sichtbar ist - setWindowFlags() auf einem sichtbaren Fenster bricht
        # die Layout-Geometrie-Verwaltung (Inhalt folgt dem Resize nicht
        # mehr). Die Flags werden seit Runde 17c bereits im Konstruktor
        # (PersistentWindow.__init__) gesetzt, wo das Fenster unsichtbar ist.
        if not self.isVisible():
            self._fix_window_flags()
        geom = self._state_manager.get_window_geometry(inst_id)
        if not geom:
            try:
                geom = self._state_manager.get_dialog_geometry(
                    self.DIALOG_GEOMETRY_KEY)
            except Exception:
                geom = None
        if geom:
            pos_x = geom.get("pos_x")
            pos_y = geom.get("pos_y")
            width = geom.get("width")
            height = geom.get("height")
            screen_geo = QApplication.primaryScreen().availableGeometry()
            # 11.08.2026 (Bugfix Runde 17c, User-Meldung 4): Fenster-GROESSE
            # wiederherstellen – vorher bewusst ignoriert (exakt-fit-to-content).
            # Mit _exact_fit_to_content=False bleibt die User-Groesse erhalten.
            if width and height:
                self.resize(max(int(width), 640), max(int(height), 480))
            if pos_x is not None and pos_y is not None:
                if pos_x < screen_geo.x() - 100 or pos_x > screen_geo.right() or \
                   pos_y < screen_geo.y() - 100 or pos_y > screen_geo.bottom():
                    pos_x, pos_y = 100, 100
                self.move(pos_x, pos_y)
            self._restored_is_maximized = bool(geom.get("is_maximized", False))
        # Symbol/Timeframe aus instance_states
        all_inst = self._state_manager.load_all_instances()
        matched = next((i for i in all_inst if i.get("instance_id") == inst_id), None)
        if matched:
            raw_symbol = matched.get("symbol")
            raw_tf = matched.get("timeframe")
            symbol = str(raw_symbol) if raw_symbol is not None else self.get_persistent_symbol()
            tf = str(raw_tf) if raw_tf is not None else self.get_persistent_timeframe()
            self._apply_persistent_filters(symbol, tf)

    def _apply_reflow_size(self) -> None:
        """Erweitert den Mixin-Reflow um Punkt 2 (05.08.2026).

        Der Splitter (Tree | Parameter-Box) bekommt eine Mindest-Hoehe von
        2x seiner natuerlichen Hoehe – dadurch oeffnet das Fenster
        standardmaessig doppelt so hoch und Tree UND Box sind doppelt so
        hoch. WICHTIG: Nach dem setMinimumHeight muessen die Layout-Caches
        erneut invalidiert werden – der vertikale Layout-sizeHint ist sonst
        veraltet (Qt 6.11-Caching) und uebernimmt das neue Minimum nicht
        (Fenster bliebe auf der alten Hoehe).
        """
        sp = getattr(self, "main_splitter", None)
        if sp is not None:
            natural = sp.sizeHint().height()
            sp.setMinimumHeight(natural * 2)
            sp.updateGeometry()
            self._invalidate_content_caches()
        super()._apply_reflow_size()

    def resize_to_clamped_content(self) -> None:
        """11.08.2026 (Bugfix Runde 17c, User-Meldung 4): Override.

        Das Basis-Mixin resizet das Inhalt-Widget MANUELL (auf sizeHint bzw.
        auf die Fensterbreite). Mit widgetResizable=True (Runde 17c) verwaltet
        die ContentScrollArea das Inhalt-Widget aber selbst - das manuelle
        resize() brach die Layout-Verwaltung und 'fror' die ScrollArea auf der
        alten Groesse ein (Inhalt folgte dem Fenster-Resize nicht mehr).

        Daher wird hier NUR die FENSTER-Groesse nachgefuehrt:
          * nur wachsen, nie schrumpfen (User darf frei ziehen/verkleinern),
          * Screen-Klemme (max. verfuegbare Flaeche),
          * _min_window_width (Splitter-Spielraum, ServiceWindow=1100).
        Das Inhalt-Widget (Splitter, MasterTree, Param-Box) folgt der
        ScrollArea automatisch (widgetResizable=True).
        """
        if self._content_widget is None:
            return
        content = self.clamped_content_size()
        frame = self.frameGeometry().size() - self.size()
        desired = QSize(content.width() + frame.width(),
                        content.height() + frame.height())
        screen = QApplication.primaryScreen().availableGeometry()
        current = self.size()
        new_w = min(max(desired.width(), current.width()), screen.width())
        new_h = min(max(desired.height(), current.height()), screen.height())
        min_w = getattr(self, '_min_window_width', 0) or 0
        if min_w:
            new_w = max(new_w, min(min_w, screen.width()))
        if not self.isMaximized():
            self.resize(new_w, new_h)

    def apply_screen_cap(self) -> None:
        """11.08.2026 (Bugfix Runde 17d2, User-Meldung 1): KEIN setMaximumSize.

        Qt's Windows-QPA zeigt/aktiviert den Maximize-Button NUR, wenn
        maximumSize() == QWINDOWSIZE_MAX (16777215) ist (oder
        Qt::CustomizeWindowHint gesetzt ist) - siehe qwindowswindow.cpp,
        shouldShowMaximizeButton(): 'return (flags & Qt::CustomizeWindowHint)
        || w->maximumSize() == QSize(QWINDOWSIZE_MAX, QWINDOWSIZE_MAX);'.

        Das bisherige setMaximumSize(screen.size()) (Runde 17b) bzw.
        setMaximumSize(screen.size()*2) (Runde 17c) war NIE gleich
        QWINDOWSIZE_MAX -> Windows graute den Maximize-Button weiterhin aus.

        Mit widgetResizable=True + _exact_fit_to_content=False ist die
        Screen-Klemme der DEFAULT-Groesse Aufgabe des Reflows
        (resize_to_clamped_content klemmt auf availableGeometry). Ein
        OS-seitiges Maximum ist nicht noetig: Das Fenster behaelt die
        Qt-Defaults (max = QWINDOWSIZE_MAX) und kann frei maximiert werden
        (der Inhalt folgt via ContentScrollArea).
        """
        pass  # bewusst KEIN setMaximumSize - Maximize-Button bleibt aktiv

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
        danach folgen alle Timeframes AUFSTEIGEND nach Dauer sortiert –
        kuerzeste zuerst (M1, M2, M5, M10, M15, M30, H1, H4, D1, W1, MN1),
        identische Reihenfolge wie im chart_win (Bugfix 05.08.2026).
        get_timeframes() liefert intern die MT5-Reihenfolge (MN1..M1),
        daher wird explizit ueber TF_SECONDS_MAP sortiert. Fallback bei
        nicht verfuegbarem MT5: TF_SECONDS_MAP bzw. eine Basisliste. Die
        aktuelle Auswahl bleibt erhalten, sofern sie noch existiert;
        Default ist 'M1'.
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
            tfs = ["M1", "M2", "M5", "M10", "M15", "M30",
                   "H1", "H4", "D1", "W1", "MN1"]
        # Bugfix 05.08.2026: Kuerzeste zuerst (M1..MN1) wie im chart_win.
        tfs = sorted(tfs, key=lambda tf: TF_SECONDS_MAP.get(tf, 10**12))
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
        if (self._current_set_definition is not None
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
        # 17.01.04 (Bugfix): Klick-Scope (node_type, set_id, service_id,
        # plugin_id) – traegt auch die plugin_id von Plugin-Zeilen unter
        # 'Services'. Daraus wird der Standalone-Plugin-Editor geladen
        # (Parameter anzeigen/editieren/speichern wie bei Sets).
        tree.selection_details.connect(self._on_master_selection_details)
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
        # Phase 15: Kontextmenue '🗑️ Papierkorb öffnen...' (Haupt-Gruppe
        # 📁 Service-Sets) – gleiche Methode wie der Papierkorb-Button in
        # der oberen Aktionsleiste (btn_trash_sets).
        tree.open_trash_requested.connect(self.show_trash_dialog)
        # 05.08.2026: Gezielte Ausfuehrung ('▶️ Diesen Service ausführen' /
        # '▶️ Alle Services ausführen') -> ServiceRunWorker mit Sicherheits-
        # abfrage (Set/Service + aktives Symbol/Timeframe) + FeatureStore-
        # Persistenz + EventBus-Sync.
        tree.run_service_requested.connect(self._on_run_service)
        tree.run_set_requested.connect(self._on_run_set)
        # 17.01.02 (Bugfix-Runde): Run-/Info-Aktionen der Services-Gruppe
        # (Plugin-Zeilen einzeln, Kategorie-Ordner rekursiv, Ordner-Info).
        tree.run_plugin_requested.connect(self._on_run_plugin)
        tree.run_category_requested.connect(self._on_run_category)
        tree.category_info_requested.connect(self._on_category_info_requested)
        # 18.01.03 (Dynamic Tree Management): Ordner-CRUD & Kategorie-
        # Drag&Drop – Sets/Plugins/Ordner ziehen, 'Neuer Ordner' (wird
        # PERSISTIERT, E3-revidiert 08.08.2026), 'Umbenennen' (String-Replace
        # aller Kinder) und 'Ordner löschen' (manuelle Loeschung) werden hier
        # persistiert.
        tree.folder_item_moved.connect(self._on_folder_item_moved)
        tree.folder_moved.connect(self._on_folder_moved)
        tree.rename_folder_requested.connect(self._on_rename_folder)
        tree.create_folder_requested.connect(self._on_create_folder)
        tree.delete_folder_requested.connect(self._on_delete_folder)
        # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im MasterTree-Kontextmenue
        # (Service-/Clone-Zeilen) -> Handler (unten). 'Data Only Löschen'
        # purgt die Feature-Daten (Q5), 'Vollständig Löschen' entfernt
        # Instanz/Preset + Daten, 'Doc Log bearbeiten' editiert das
        # Negativ-Wissen und 'Als Variante duplizieren' erzeugt Kopien (Q8).
        tree.data_only_purge_requested.connect(self._on_data_only_purge)
        tree.delete_complete_requested.connect(self._on_delete_complete)
        tree.doc_log_requested.connect(self._on_doc_log_requested)
        tree.duplicate_variant_requested.connect(self._on_duplicate_variant)
        # 10.08.2026 (Bugfix): 'Variante umbenennen' (Clone/Preset) – der
        # MasterTree fragt den neuen Namen ab; dieser Handler persistiert
        # den Rename in indicator_presets (indicator_id, preset_name).
        tree.rename_variant_requested.connect(self._on_rename_variant)

    @Slot(str)
    def _toolbar_add_service(self, plugin_id: str,
                             set_id: Optional[str] = None) -> None:
        """Fuegt einen Service (Plugin) in das Set ein (Kontextmenue
        'Service hinzufuegen' -> eigene Auswahlbox).

        Phase 13-Bereinigung (05.08.2026): Der fruehere Weg ueber das
        Instanz-Eingabefeld der entfernten Service-Sets-Box entfaellt - der
        Service wird direkt ueber die Plugin-Auswahl mit
        Registry-Defaults angelegt (_add_service_to_set)."""
        if not plugin_id:
            return
        target = set_id or self._current_set_id
        if not target:
            self.log("Kein Set geladen - Service kann nicht hinzugefuegt werden.")
            return
        self._add_service_to_set(target, str(plugin_id))

    @Slot(str, str)
    def _on_master_selection(self, set_id: str, service_id: str) -> None:
        """Laedt das im MasterTree gewaehlte Set direkt in den Parameter-
        Editor (rechte Splitter-Spalte).

        Phase 13-Bereinigung (05.08.2026): Der bisherige Umweg ueber das
        Set-Dropdown der entfernten Service-Sets-Box entfaellt - die
        Auswahl im MasterTree ist die alleinige Quelle. Bei Set-Auswahl
        werden die Parameter-Spalten aufgebaut; ohne Auswahl (Plugin-/
        Standalone-Zeilen) wird der Editor geleert.

        17.01.04 (Bugfix): Bei einer Plugin-Zeile unter 'Services' feuert
        selection_changed mit leeren IDs NACH selection_details. Der
        Plugin-Editor wurde dort bereits geladen (_current_plugin_editing) –
        der Editor darf in diesem Fall NICHT geleert werden."""
        self._set_param_actions_visible(False)
        if not set_id:
            if self._current_plugin_editing:
                return  # Plugin-Editor bleibt (via selection_details geladen)
            self._clear_set_editor()
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        self.load_set_into_editor(definition)

    # -------------------------------------------------------------------------
    # 17.01.04 (Bugfix): Standalone-Plugin-Editor (Parameter-Spalte fuer
    # Plugin-Zeilen unter 'Services' – anzeigen/editieren/speichern wie bei
    # Sets; Persistenz in global_settings, Key 'plugin_params_<pid>').
    # -------------------------------------------------------------------------

    @Slot(str, str, str, str)
    def _on_master_selection_details(self, node_type: str, set_id: str,
                                     service_id: str, plugin_id: str) -> None:
        """Slot fuer `MasterTree.selection_details` (Mausklick in einer Zeile).

        17.01.04 (Bugfix): Klick auf eine Plugin-Zeile (TYPE_PLUGIN) unter
        'Services' (auch in Kategorie-Ordnern) laedt den Standalone-Plugin-
        Editor in die rechte Parameter-Spalte – editierbar, mit Speichern.
        Set-/Service-Zeilen verhalten sich unveraendert (der eigentliche
        Set-Load laeuft ueber selection_changed); hier wird nur der
        Plugin-Modus zurueckgesetzt.
        """
        if node_type in ("plugin", "clone") and plugin_id:
            # 21.01b: Pill-Strip fuer den geklickten Service laden.
            self._refresh_badge_bar(str(plugin_id))
            if node_type == "clone":
                # 10.08.2026 (Bugfix, Varianten-Params): Eine Variante/Clone
                # hat EIGENE Parameter in indicator_presets (20.04, Q7) -
                # der Editor laedt die presetspezifischen Werte statt der
                # globalen Standalone-Parameter (plugin_params_<pid>). Der
                # instance_hash liegt im service_id-Slot (MasterTree.
                # _emit_selection_details).
                self._load_clone_editor(str(plugin_id), str(service_id))
            else:
                self._load_plugin_editor(str(plugin_id))
            return
        # Jede andere Zeile beendet den Plugin-Editor-Modus; der Set-Editor
        # wird weiterhin ueber selection_changed gesteuert (Bestandslogik).
        if self._current_plugin_editing:
            self._current_plugin_editing = None
        if self._current_preset_editing:
            self._current_preset_editing = None
        # 21.01b: Pill-Strip fuer Set-/Service-Zeilen nachziehen (erster
        # Service des Sets bzw. der Service selbst).
        self._refresh_badge_bar(
            self._resolve_badge_plugin(node_type, set_id,
                                       service_id, plugin_id))

    def _plugin_config(self, plugin_id: str) -> Dict[str, Any]:
        """ServiceInstanceConfig eines Standalone-Plugins.

        Liefert {"plugin_id", "lookback", "params", "version"} – Basis sind
        die Registry-Defaults; gespeicherte Werte aus global_settings
        (Key 'plugin_params_<pid>') ueberschreiben lookback/params und
        ergaenzen eine optionale Beschreibung.
        """
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            plugin = None
        params = dict(getattr(plugin, "default_params", None) or {}) if plugin else {}
        lookback: int = 1000
        if "lookback" in params:
            try:
                lookback = int(params.pop("lookback") or 1000)
            except (TypeError, ValueError):
                lookback = 1000
        cfg: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": lookback,
            "params": params,
            "version": getattr(plugin, "version", "0.0.0") or "0.0.0",
        }
        try:
            saved = self._state_manager.get_global_value(
                f"plugin_params_{plugin_id}", None)
        except Exception:
            saved = None
        if isinstance(saved, dict):
            lb = saved.get("lookback")
            if lb is not None:
                try:
                    cfg["lookback"] = int(lb)
                except (TypeError, ValueError):
                    pass
            saved_params = saved.get("params")
            if isinstance(saved_params, dict):
                merged = dict(params)
                merged.update(saved_params)
                cfg["params"] = merged
            desc = saved.get("description")
            if desc:
                cfg["description"] = str(desc)
        return cfg

    def _load_plugin_editor(self, plugin_id: str) -> None:
        """Laedt die Parameter eines Standalone-Plugins in den Editor.

        Baut eine Ad-hoc-Definition (nur dieser eine Service) aus
        `_plugin_config` und zeigt sie editierbar in der rechten Spalte.
        Der Speicherpfad laeuft bei Aenderungen ueber `_save_plugin_params`
        (global_settings) statt ueber ServiceSetRepository.
        """
        if not plugin_id:
            return
        try:
            from analytics.features.feature_builder import PluginRegistry
            PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden.")
            self._current_plugin_editing = None
            self._current_preset_editing = None
            self._clear_set_editor()
            return
        cfg = self._plugin_config(plugin_id)
        definition: Dict[str, Any] = {
            "set_id": "",
            "display_name": plugin_id,
            "description": str(cfg.get("description") or ""),
            "execution_order": [plugin_id],
            "services": {plugin_id: cfg},
        }
        self._current_plugin_editing = plugin_id
        self._current_preset_editing = None
        self.load_set_into_editor(definition)

    def _load_clone_editor(self, plugin_id: str, instance_hash: str) -> None:
        """Laedt die Parameter einer Variante (Clone) in den Editor.

        10.08.2026 (Bugfix, Varianten-Params): Jede Variante hat EIGENE
        Parameter-Einstellungen in indicator_presets (Kapitel 20.04, Model C).
        Ein Klick auf einen Clone-Knoten darf NICHT die globalen Standalone-
        Parameter (plugin_params_<pid>) laden - der Editor zeigt die
        presetspezifischen Werte. Der Save-Pfad (_save_plugin_params)
        schreibt Aenderungen via save_indicator_preset in das Preset
        (indicator_id, preset_name) zurueck.
        """
        if not plugin_id or not instance_hash:
            return
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            self.log(f"Preset zu #{instance_hash} nicht gefunden.")
            self._current_plugin_editing = None
            self._current_preset_editing = None
            self._clear_set_editor()
            return
        indicator_id = str(preset.get("indicator_id") or "")
        preset_name = str(preset.get("preset_name") or "Default")
        if not indicator_id:
            self.log(f"Preset '{preset_name}' hat keine indicator_id.")
            return
        # Basis = Registry-Defaults + gespeicherte Standalone-Werte; die
        # presetspezifischen Parameter ueberschreiben (Varianten-Params).
        cfg = self._plugin_config(plugin_id)
        preset_params = preset.get("params") or {}
        if isinstance(preset_params, dict) and preset_params:
            merged = dict(cfg.get("params") or {})
            merged.update(preset_params)
            cfg["params"] = merged
        definition: Dict[str, Any] = {
            "set_id": "",
            "display_name": f"{plugin_id} ({preset_name})",
            "description": str(preset.get("doc_log") or ""),
            "execution_order": [plugin_id],
            "services": {plugin_id: cfg},
        }
        self._current_plugin_editing = plugin_id
        # Merke das Preset fuer den Save-Pfad (is_active_batch/doc_log
        # bleiben beim Speichern erhalten).
        self._current_preset_editing = preset
        self.load_set_into_editor(definition)

    def _save_plugin_params(self) -> bool:
        """Persistiert die Parameter des aktuell editierten Standalone-
        Plugins in global_settings (Key 'plugin_params_<pid>').

        Returns: True bei Erfolg (Dirty-Marker entfernt).
        """
        plugin_id = self._current_plugin_editing
        if not plugin_id:
            return False
        definition = self.collect_set_definition()
        services = definition.get("services") or {}
        cfg = next(iter(services.values()), None)
        if not isinstance(cfg, dict):
            self.log(f"FEHLER beim Speichern der Plugin-Parameter: "
                     f"keine Service-Config.")
            return False
        # 10.08.2026 (Bugfix, Varianten-Params): Im Clone-/Preset-Modus wird
        # in indicator_presets gespeichert (eigene Parameter je Variante)
        # statt in global_settings (plugin_params_<pid>).
        preset = self._current_preset_editing
        if isinstance(preset, dict):
            indicator_id = str(preset.get("indicator_id") or "")
            preset_name = str(preset.get("preset_name") or "Default")
            if not indicator_id:
                self.log("Preset hat keine indicator_id - nicht gespeichert.")
                return False
            try:
                self._state_manager.save_indicator_preset(
                    indicator_id, preset_name,
                    dict(cfg.get("params") or {}),
                    plugin_id=plugin_id,
                    version=str(cfg.get("version")
                                or preset.get("version") or "0.0.0"),
                    is_active_batch=bool(preset.get("is_active_batch")),
                    doc_log=str(preset.get("doc_log") or ""),
                )
            except Exception as e:
                self.log(f"FEHLER beim Speichern der Varianten-Parameter: {e}")
                return False
            self._clear_dirty_markers()
            event_bus.service_set_changed.emit()
            self.log(f"Parameter gespeichert (Variante '{preset_name}'): "
                     f"{plugin_id}")
            return True
        data: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": int(cfg.get("lookback") or 1000),
            "params": dict(cfg.get("params") or {}),
            "description": str(cfg.get("description") or ""),
        }
        try:
            self._state_manager.save_global_value(
                f"plugin_params_{plugin_id}", data)
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Plugin-Parameter: {e}")
            return False
        self._clear_dirty_markers()
        # 18.01.01 (E-3): EventBus-Live-Sync - analog zum Set-Speichern
        # (save_set-Pfad) und zum Dialog-Picker, damit alle MasterTree-
        # Instanzen (auch der Analytics-Picker) die Standalone-Parameter
        # bzw. den geaenderten Zustand live uebernehmen.
        event_bus.service_set_changed.emit()
        self.log(f"Parameter gespeichert (Plugin): {plugin_id}")
        return True

    def _begin_sync_guard(self) -> None:
        """Blockt den 45s-Hintergrund-Sync (sync_timer in main.py).

        Erhoeht den Referenzzaehler und emittiert `service_run_started`
        ausschliesslich beim Uebergang 0→1 – mehrere parallele Runs
        (ServiceRunWorker) pausieren den Sync nur EINMAL.
        """
        self._sync_guard_count += 1
        if self._sync_guard_count == 1:
            try:
                event_bus.service_run_started.emit()
            except (RuntimeError, AttributeError):
                pass

    def _end_sync_guard(self) -> None:
        """Gibt den 45s-Hintergrund-Sync wieder frei.

        Senkt den Referenzzaehler; erst beim Uebergang 1→0 (alle
        Service-Berechnungen abgeschlossen) wird `service_run_finished`
        emittiert und der Sync-Timer im MainWindow wieder gestartet.
        """
        if self._sync_guard_count <= 0:
            return
        self._sync_guard_count -= 1
        if self._sync_guard_count == 0:
            try:
                event_bus.service_run_finished.emit()
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
        # 12.08.2026 (User-Meldung 2): Per-Service-Fortschrittsbalken.
        self._run_worker.service_progress.connect(self._on_service_progress)
        # 21.01b: Per-TF-Signale -> Pill-Strip (Laufzeit-/Fehler-Zustand).
        self._run_worker.tf_started.connect(self._on_tf_started)
        self._run_worker.tf_finished.connect(self._on_tf_finished)
        # 12.08.2026: Progress-Reset beim Start (Busy-Modus).
        self._reset_run_progress("Starte Ausführung ...")
        # Phase 16: 45s-Hintergrund-Sync pausieren, solange der Run laeuft.
        self._begin_sync_guard()
        self._run_worker.start()

    @Slot(str, str)
    def _on_run_service(self, set_id: str, service_id: str) -> None:
        """'▶️ Diesen Service ausführen' (MasterTree-Kontextmenue).

        Sicherheitsabfrage mit Set-/Service-Name und dem aktuell gewaehlten
        Symbol/Timeframe, danach gezielter Single-Run (inkl. Upstream-
        Abhaengigkeiten im Set, damit z.B. srv_proximity seine Linien hat).
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

    @Slot(str, str)
    def _on_run_plugin(self, plugin_id: str, instance_hash: str = "") -> None:
        """'▶️ Diesen Service ausführen' (Plugin-/Clone-Zeile unter 📦 Services).

        17.01.02 (Bugfix-Runde): Einzel-Services ausserhalb von Sets (z.B.
        unter Kategorie-Ordnern) erhalten dieselbe Run-Aktion wie die
        Service-Zeilen der Sets. Sicherheitsabfrage mit Plugin-Name und dem
        aktuell gewaehlten Symbol/Timeframe, danach gezielter Single-Run via
        ServiceRunWorker mit einer Ad-hoc-Mini-Definition (nur dieser
        Service; prepare_worker_definition loest ggf. dependencies auf).

        11.08.2026 (Bugfixing, Varianten-Run): `instance_hash` wird vom
        MasterTree-Kontextmenue mitgeliefert:
          * Clone-Zeile  -> hash der Variante: NUR diese Variante laeuft mit
                            ihren EIGENEN Parametern + Hash (Datum im Baum
                            aktualisiert sich an der Variante, Bug 1).
          * Plugin-Zeile -> leer: mit Presets laufen ALLE aktiven Varianten,
                            sonst Basis-Parameter (Bestandsverhalten).
        """
        if not plugin_id:
            return
        sm = getattr(self, "_state_manager", None)
        entries = variant_run_entries(plugin_id, sm, self._plugin_config)
        if not entries:
            return
        if instance_hash:
            entries = [e for e in entries
                       if e[1].get("instance_hash") == instance_hash]
            if not entries:
                # Variante nicht (mehr) vorhanden -> Basis-Fallback.
                entries = [(plugin_id, self._plugin_config(plugin_id))]
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Timeframe-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        single = len(entries) == 1
        if single:
            _iid, _cfg = entries[0]
            _name = str(_cfg.get("preset_name") or plugin_id)
            title = "Service ausführen"
            text = (f"Service '{plugin_id}' (Variante '{_name}') ausführen?\n\n"
                    f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                    f"Der erzeugte Feature-Store-Payload wird in analytics.duckdb "
                    f"geschrieben.")
        else:
            title = "Alle Varianten ausführen"
            text = (f"Alle Varianten ({len(entries)}) von '{plugin_id}' "
                    f"ausführen?\n\n"
                    f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                    f"Die erzeugten Feature-Store-Payloads werden in "
                    f"analytics.duckdb geschrieben.")
        reply = QMessageBox.question(
            self, title, text, QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen.")
            return
        definition = {
            "set_id": f"plugin_{plugin_id}",
            "display_name": plugin_id,
            "execution_order": [e[0] for e in entries],
            "services": {e[0]: e[1] for e in entries},
        }
        self._start_run_worker(
            plugin_id, definition,
            instance_id=entries[0][0] if single else None)

    @Slot(str, str)
    def _on_run_category(self, group: str, category_path: str) -> None:
        """▶️ Alle Services ausführen (Kategorie-Ordner).

        17.01.02 (Bugfix-Runde): Ordner-Knoten erhalten dieselbe Run-Aktion
        wie die Sets. Es werden ALLE Services unter dem Ordner ausgefuehrt
        (rekursiv, inkl. Unter-Ordner). 18.01.03 (L3): `group` unterscheidet
        Sets-Ordner ('sets' – alle Service-plugin_ids der Sets unter dem
        Pfad, rekursiv) von Plugins-Ordnern ('plugins' – via
        ServiceSelectorModel.category_plugin_ids). Sicherheitsabfrage mit
        Kategorie-Name und dem aktuell gewaehlten Symbol/Timeframe, danach
        gezielter Set-Run mit einer Ad-hoc-Definition.
        """
        if not category_path:
            return
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return
        plugin_ids = model.category_service_plugin_ids(group, category_path)

        if not plugin_ids:
            self.log(f"Kategorie '{category_path}' hat keine Services – "
                     f"Ausführung abgebrochen.")
            return
        # 11.08.2026 (Bugfixing, Bug 3): Plugins MIT Presets werden zu ALLEN
        # aktiven Varianten expandiert (jede mit eigenen Parametern + Hash),
        # damit 'Alle Services ausführen' auch die Varianten ausfuehrt.
        sm = getattr(self, "_state_manager", None)
        entries_all: List[tuple] = []
        for pid in plugin_ids:
            entries_all.extend(variant_run_entries(pid, sm, self._plugin_config))
        if not entries_all:
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Timeframe-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        count = len(entries_all)
        reply = QMessageBox.question(
            self, "Alle Services ausführen",
            f"Alle Services ({count}) der Kategorie '{category_path}' "
            f"ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Die erzeugten Feature-Store-Payloads werden in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen.")
            return
        definition = {
            "set_id": f"category_{category_path}",
            "display_name": category_path,
            "execution_order": [e[0] for e in entries_all],
            # 17.01.04: Gespeicherte Plugin-Parameter je Service verwenden
            # (falls vorhanden), sonst Registry-Defaults. Varianten tragen
            # Preset-Parameter + instance_hash.
            "services": {e[0]: e[1] for e in entries_all},
        }
        self._start_run_worker(category_path, definition, instance_id=None)

    @Slot(str, str)
    def _on_category_info_requested(self, group: str,
                                    category_path: str) -> None:
        """Info-Dialog fuer einen Kategorie-Ordner (17.01.02, wie Set-Info).

        Read-Only-Liste aller Services unter dem Ordner (rekursiv) mit dem
        Kategorie-Pfad als Titel – analog zur Set-Info (ServiceDescription
        Dialog.from_set, keine persistierbare Beschreibung). 18.01.03 (L3):
        `group` unterscheidet Sets- von Plugins-Ordnern (Aufloesung via
        ServiceSelectorModel.category_service_plugin_ids).
        """
        if not category_path:
            return
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return
        plugin_ids = model.category_service_plugin_ids(group, category_path)

        definition = {
            "set_id": f"category_{category_path}",
            "display_name": category_path,
            "description": f"Kategorie-Ordner: {category_path}",
            "execution_order": list(plugin_ids),
            "services": {pid: {"plugin_id": pid} for pid in plugin_ids},
        }
        try:
            dlg = ServiceDescriptionDialog.from_set(definition, parent=self)
            dlg.exec()
        except (RuntimeError, AttributeError) as e:
            self.log(f"Info-Dialog nicht möglich: {e}")

    # -------------------------------------------------------------------------
    # 18.01.03 (Dynamic Tree Management): Kategorie-Drag&Drop & Ordner-CRUD
    # -------------------------------------------------------------------------

    @Slot(str, str, str)
    def _on_folder_item_moved(self, node_type: str, item_id: str,
                              new_path: str) -> None:
        """Drop eines Sets/Plugins in einen Ziel-Ordner (MasterTree).

        Persistiert den neuen Kategorie-Pfad:
          * TYPE_SET    -> Set-Definition (category-Feld) via save_set (E2).
          * TYPE_PLUGIN -> Kategorie-Override (plugin_category_<id>,
                           global_settings – E1).
        18.01.03 (E3-revidiert, Bugfix 08.08.2026): Der QUELL-Ordner
        (und seine Elternkette) wird VOR dem Update ermittelt und nach
        dem Verschieben als Leere-Ordner persistiert
        (ensure_folder_path) – damit bleibt der Ordner sichtbar und
        verschiebbar, wenn sein letztes Kind entzogen wurde.
        Danach EventBus-Sync, damit ALLE MasterTree-Instanzen live
        refreshen (Invariante 5).
        """
        from serviceui.master_tree import TYPE_PLUGIN, TYPE_SET
        from serviceui.service_set_utils import (
            ensure_folder_path, set_plugin_category, set_set_category)
        source_path = ""
        group = ""
        ok = False
        if node_type == TYPE_SET:
            group = "sets"
            try:
                definition = self.set_repo.get_set(item_id) or {}
                source_path = str(definition.get("category") or "").strip().strip("/")
            except Exception:
                source_path = ""
            ok = set_set_category(self.set_repo, item_id, new_path)
        elif node_type == TYPE_PLUGIN:
            group = "plugins"
            model = getattr(self.service_selector, "model", None)
            if model is not None:
                try:
                    source_path = model.plugin_category_path(item_id)
                except Exception:
                    source_path = ""
            ok = set_plugin_category(self.state_manager, item_id, new_path)
        if not ok:
            self.log(f"Kategorie-Verschiebung fehlgeschlagen "
                     f"({node_type} '{item_id}').")
            return
        if source_path:
            ensure_folder_path(self.state_manager, group, source_path)
        event_bus.service_set_changed.emit()

    @Slot(str, str)
    def _on_create_folder(self, group: str, full_path: str) -> None:
        """Kontextmenue 'Neuer Ordner' (create_folder_requested).

        18.01.03 (E3-revidiert, 08.08.2026): Persistiert den
        benutzererzeugten (ggf. leeren) Ordner ueber global_settings
        (service_set_utils.create_empty_folder, Key
        'tree_folders_<group>') und emittiert den EventBus, damit alle
        MasterTree-Instanzen live refreshen (Invariante 5). Leere
        Ordner verschwinden damit NICHT beim Refresh, sondern nur bei
        manueller Loeschung ('Ordner löschen').
        """
        from serviceui.service_set_utils import create_empty_folder
        if not create_empty_folder(self.state_manager,
                                   str(group or ""), full_path):
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str)
    def _on_delete_folder(self, group: str, path: str) -> None:
        """Kontextmenue 'Ordner löschen' (delete_folder_requested).

        18.01.03 (E3-revidiert): Entfernt den persistierten Ordner-
        Eintrag (service_set_utils.delete_empty_folder, Key
        'tree_folders_<group>') und emittiert den EventBus. Der
        MasterTree erlaubt die Aktion nur fuer Ordner ohne Kinder;
        Kinder (falls vorhanden) bleiben unangetastet.
        """
        from serviceui.service_set_utils import delete_empty_folder
        if not delete_empty_folder(self.state_manager,
                                   str(group or ""), path):
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str, str)
    def _on_folder_moved(self, group: str, old_path: str,
                         new_path: str) -> None:
        """Drop eines Ordners auf einen anderen Ordner (MasterTree).

        Verschiebt alle Kinder rekursiv (String-Replace des Pfad-Praefixes
        via service_set_utils.rename_category) und emittiert den EventBus.
        """
        self._rename_folder(group, old_path, new_path)

    @Slot(str, str, str)
    def _on_rename_folder(self, group: str, old_path: str,
                          new_path: str) -> None:
        """Kontextmenue 'Umbenennen' (rename_folder_requested).

        Fuehrt dasselbe String-Replace aus wie der Ordner-Drop
        (_on_folder_moved) – DRY ueber `_rename_folder`.
        """
        self._rename_folder(group, old_path, new_path)

    def _rename_folder(self, group: str, old_path: str,
                       new_path: str) -> None:
        """Zentraler Ordner-Rename (String-Replace aller Kinder).

        18.01.03 (E1/E2): Sets-Ordner aktualisieren das category-Feld der
        Set-Definitionen; Plugins-Ordner setzen Kategorie-Overrides
        (plugin_category_<id>). Nach Aenderung EventBus-Sync.
        """
        from serviceui.service_set_utils import rename_category
        try:
            count = rename_category(
                getattr(self.service_selector, "model", None),
                self.set_repo, self.state_manager,
                str(group or ""), old_path, new_path)
        except Exception as e:
            self.log(f"Ordner-Umbenennung fehlgeschlagen: {e}")
            return
        if count > 0:
            event_bus.service_set_changed.emit()
        self.log(f"Ordner '{old_path}' -> '{new_path}': {count} "
                 f"Element(e) verschoben.")

    @Slot(str, int)
    def _on_run_worker_finished(self, scope_id: str, stored: int) -> None:
        """Loggt den Abschluss des gezielten Runs (FeatureStore-Persistenz).

        Der EventBus-Sync erfolgt bereits im Worker (service_set_changed) –
        das ServiceSelectorModel hat dadurch das neue MAX(created_at) gelesen
        und der MasterTree zeigt das Datum '(DD.MM.JJ)' live an.
        """
        # Phase 16: 45s-Hintergrund-Sync wieder freigeben.
        self._end_sync_guard()
        self._reset_run_progress()
        self.log(f"Ausführung abgeschlossen: {stored} Feature-Row(s) im "
                 f"feature_store gespeichert ({scope_id}).")
        # 21.01b: Pill-Strip nach dem Run neu laden (neue Counts/last_run).
        bar = getattr(self, "badge_bar", None)
        if bar is not None:
            bar.set_running(None)
        self._refresh_badge_bar()

    @Slot(str, str)
    def _on_run_worker_failed(self, scope_id: str, error: str) -> None:
        # Phase 16: 45s-Hintergrund-Sync auch bei Fehler freigeben.
        self._end_sync_guard()
        self._reset_run_progress()
        self.log(f"FEHLER bei Ausführung ({scope_id}): {error}")
        # 21.01b: Pill-Strip nach Fehler zuruecksetzen + Status neu laden.
        bar = getattr(self, "badge_bar", None)
        if bar is not None:
            bar.set_running(None)
        self._refresh_badge_bar()

    @Slot(str, str, int, int)
    def _on_service_progress(self, tf: str, iid: str, done: int,
                             total: int) -> None:
        """12.08.2026 (User-Meldung 2): Per-Service-Fortschritt anzeigen."""
        bar = getattr(self, "progress_bar", None)
        if bar is not None:
            bar.setMaximum(max(total, 1))
            bar.setValue(done)
        lbl = getattr(self, "progress_label", None)
        if lbl is not None:
            lbl.setText(f"{tf}: {iid} ({done}/{total})")

    def _reset_run_progress(self, label: str = "") -> None:
        """Setzt den Fortschrittsbalken zurueck (Default: leeres Label)."""
        bar = getattr(self, "progress_bar", None)
        if bar is not None:
            bar.setMaximum(0)
            bar.setValue(0)
        lbl = getattr(self, "progress_label", None)
        if lbl is not None:
            lbl.setText(label)

    # -------------------------------------------------------------------------
    # 21.01b (11.08.2026): TF-Status-Pills (Pill-Strip)
    # -------------------------------------------------------------------------
    def _on_tf_started(self, tf: str) -> None:
        """Hebt den gerade laufenden Timeframe im Pill-Strip blau hervor."""
        bar = getattr(self, "badge_bar", None)
        if bar is None:
            return
        bar.set_running(tf)
        bar.clear_error(tf)

    def _on_tf_finished(self, tf: str, stored: int, had_data: bool) -> None:
        """TF fertig: ohne OHLCV-Daten/Fehler rot markieren, sonst neutral."""
        bar = getattr(self, "badge_bar", None)
        if bar is None:
            return
        if had_data:
            bar.clear_error(tf)
        else:
            bar.set_error(tf)
        bar.set_running(None)

    def _resolve_badge_plugin(self, node_type: str, set_id: str,
                              service_id: str,
                              plugin_id: str) -> Optional[str]:
        """Ermittelt die plugin_id fuer den Pill-Strip einer Baum-Zeile."""
        if plugin_id:
            return str(plugin_id)
        if set_id:
            try:
                definition = self.set_repo.get_set(set_id)
            except Exception:
                definition = None
            if definition:
                order = list(definition.get("execution_order") or [])
                services = dict(definition.get("services") or {})
                for iid in order:
                    cfg = services.get(iid) or {}
                    pid = str(cfg.get("plugin_id") or iid)
                    if pid:
                        return pid
        return str(service_id) if service_id else None

    def _refresh_badge_bar(self, plugin_id: Optional[str] = None) -> None:
        """Laedt die TF-Status-Pills fuer den angegebenen Service neu.

        Quelle: FeatureStoreReader.fetch_service_tf_status() – je Timeframe
        die Anzahl der feature_store-Eintraege und der letzte Lauf.
        """
        bar = getattr(self, "badge_bar", None)
        if bar is None:
            return
        if plugin_id:
            self._badge_plugin_id = plugin_id
        pid = self._badge_plugin_id
        if not pid:
            bar.clear()
            return
        try:
            status = FeatureStoreReader().fetch_service_tf_status(pid)
        except Exception:
            status = {}
        bar.update_status(status)

    # -------------------------------------------------------------------------
    # Phase 15 (Dirty-State): Parameter-Panel-Aktionsleiste
    # -------------------------------------------------------------------------

    @Slot()
    def _save_params_from_panel(self) -> None:
        """'[💾 Speichern]' – persistiert die aktuellen Parameter-Aenderungen
        des aktiven Sets (ServiceSetRepository.save_set, ohne Neuberechnung),
        entfernt den '*' -Dirty-Marker im Baum und emittiert den EventBus
        (Live-Sync aller ServiceSelectorModel-Instanzen).

        17.01.04: Im Standalone-Plugin-Modus (_current_plugin_editing)
        laeuft die Persistenz ueber global_settings (_save_plugin_params)
        statt ueber ServiceSetRepository.
        """
        if self._current_plugin_editing:
            self._save_plugin_params()
            return
        if not self._current_set_id:
            self.log("Kein Set geladen – Speichern nicht möglich.")
            return
        definition = self.collect_set_definition()
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Parameter: {e}")
            return
        self._clear_dirty_markers()
        event_bus.service_set_changed.emit()
        self.log(f"Parameter gespeichert (P15): {self._current_set_id}")

    @Slot()
    def _save_and_run_from_panel(self) -> None:
        """'[▶️ Speichern & Ausführen]' – speichert die Aenderungen und
        stoesst nach Bestaetigungsabfrage (Symbol/Timeframe) sofort die
        Neuberechnung an.

        Die Neuberechnung laeuft ueber den gezielten ServiceRunWorker
        (FeatureStore-Persistenz + EventBus-Sync): Dadurch wird der
        '*' -Marker entfernt und nach Abschluss das Ausfuehrungsdatum
        '(DD.MM.JJ)' im MasterTree live aktualisiert.

        17.01.04: Im Standalone-Plugin-Modus wird nur der eine Service
        gespeichert (global_settings) und ausgefuehrt.
        """
        if self._current_plugin_editing:
            plugin_id = self._current_plugin_editing
            if not self._save_plugin_params():
                return
            definition = self.collect_set_definition()
            symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
            # U15-E: Zeitachsen-Control der Filterleiste (combo_tf) – kann
            # auch 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
            timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
            reply = QMessageBox.question(
                self, "Speichern & Ausführen",
                f"Plugin '{plugin_id}' wurde gespeichert.\n\n"
                f"Jetzt ausführen?\n"
                f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                f"Der Service wird neu berechnet und der Feature-Store-Payload "
                f"in analytics.duckdb geschrieben.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                self.log("Ausführung abgebrochen (Parameter gespeichert).")
                return
            self._start_run_worker(plugin_id, definition, instance_id=plugin_id)
            return
        if not self._current_set_id:
            self.log("Kein Set geladen – Speichern & Ausführen nicht möglich.")
            return
        definition = self.collect_set_definition()
        if not definition.get("execution_order"):
            self.log("Keine Services in der Ausführungs-Reihenfolge – "
                     "Speichern & Ausführen abgebrochen.")
            return
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Parameter: {e}")
            return
        self._clear_dirty_markers()
        event_bus.service_set_changed.emit()
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Timeframe-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        set_name = str(definition.get("display_name") or self._current_set_id)
        count = len(definition.get("execution_order") or [])
        reply = QMessageBox.question(
            self, "Speichern & Ausführen",
            f"Set '{set_name}' wurde gespeichert.\n\n"
            f"Jetzt ausführen?\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Alle Services ({count}) werden neu berechnet und die "
            f"Feature-Store-Payloads in analytics.duckdb geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen (Parameter gespeichert).")
            return
        self._start_run_worker(self._current_set_id, definition, instance_id=None)

    def _clear_dirty_markers(self) -> None:
        """Entfernt alle '*' -Dirty-Marker im MasterTree (nach Speichern).

        Bugfix 05.08.2026 (Punkt 2): Blendet zusaetzlich die Speicher-
        Buttons aus - ohne manuelle Parameter-Aenderung sind sie nicht
        sichtbar.
        """
        self._set_param_actions_visible(False)
        selector = getattr(self, "service_selector", None)
        tree = getattr(selector, "master_tree", None)
        if tree is None:
            return
        try:
            tree.clear_dirty_markers()
        except (RuntimeError, AttributeError):
            pass

    def _set_param_actions_visible(self, visible: bool) -> None:
        """Blendet die Speicher-Buttons der Parameter-Spalte ein/aus.

        Bugfix 05.08.2026 (Punkt 2/3): Sichtbar NUR bei manueller
        Parameter-Aenderung (Dirty), sonst unsichtbar. Wird von
        _mark_service_dirty (param_columns) eingeblendet und von
        _clear_dirty_markers / _on_master_selection ausgeblendet.
        """
        for name in ("btn_save_params", "btn_save_run_params"):
            btn = getattr(self, name, None)
            if btn is not None:
                try:
                    btn.setVisible(bool(visible))
                except (RuntimeError, AttributeError):
                    pass

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
        (service_plugin_ids, z.B. srv_grid_lines + srv_proximity) werden mit
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
        # Geladenes Set im Editor nachziehen (Baum-Label kommt aus dem Modell).
        if self._current_set_id == set_id:
            try:
                self.load_set_into_editor(self.set_repo.get_set(set_id))
            except Exception as e:
                self.log(f"FEHLER beim Nachladen des Sets: {e}")

    @Slot(str)
    def _on_add_set_service(self, set_id: str) -> None:
        """'Service hinzufuegen' (Kontextmenue): EIGENE Auswahlbox.

        Bugfix 05.08.2026: Eine eigene QInputDialog-Auswahlbox statt der
        frueheren Toolbar-Auswahl. Nach der Auswahl wird der Service direkt
        ins Set uebernommen und sofort persistiert (_add_service_to_set)."""
        if not set_id:
            return
        selector = getattr(self, "service_selector", None)
        ids = sorted(selector.get_plugin_ids()) if selector is not None else []
        if not ids:
            self.log("Keine Services verfuegbar.")
            return
        pid, ok = QInputDialog.getItem(
            self, "Service hinzufuegen",
            "Service waehlen:", ids, 0, False)
        if not ok or not pid:
            return
        self._toolbar_add_service(str(pid), set_id)

    @Slot(str)
    def _on_delete_set(self, set_id: str) -> None:
        """'Set loeschen' (Kontextmenue): Set laden (falls noetig) und
        delete_set() aufrufen - die P14-04-E-Sperre ('letztes Set') und die
        Rueckfrage (Papierkorb, P14-05) greifen dort zentral."""
        if not set_id:
            return
        if self._current_set_id != set_id:
            try:
                definition = self.set_repo.get_set(set_id)
                if definition:
                    self.load_set_into_editor(definition)
            except Exception as e:
                self.log(f"FEHLER beim Laden des Sets: {e}")
                return
        self.delete_set()

    @Slot(str, str, int)
    def _on_move_service(self, set_id: str, service_id: str, delta: int) -> None:
        """Order / (Kontextmenue): Service in der execution_order des Sets
        verschieben - arbeitet direkt auf der DB-Definition und persistiert
        sofort (P14-05-Snapshot via set_repo.save_set)."""
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        order = list(definition.get("execution_order") or [])
        if service_id not in order:
            return
        i = order.index(service_id)
        j = i + delta
        if j < 0 or j >= len(order):
            return
        order[i], order[j] = order[j], order[i]
        definition["execution_order"] = order
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Reihenfolge geaendert: {service_id} "
                 f"({'rauf' if delta < 0 else 'runter'})")
        event_bus.service_set_changed.emit()
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)

    @Slot(str, str)
    def _on_remove_service(self, set_id: str, service_id: str) -> None:
        """'Service entfernen' (Kontextmenue): P14-04-E-Sperrpruefung +
        doppelte Nachfrage (P14-05-Snapshot), dann direkter Entzug aus der
        DB-Definition (kein Umweg ueber die entfernte Service-Sets-Box)."""
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id) or {}
        plugin_id = str(cfg.get("plugin_id") or service_id)
        # P14-04-E: Nur der LETZTE Vorkommen eines Indikator-Services ueber
        # ALLE gespeicherten Sets ist gesperrt.
        if self._plugin_belongs_to_indicator(plugin_id):
            others = self._remaining_sets_with_plugin(
                plugin_id, exclude_set_id=set_id)
            if not others:
                QMessageBox.warning(
                    self, "Service gesperrt",
                    f"Der Service '{plugin_id}' ist der letzte in einem "
                    f"gespeicherten Service-Set.\n"
                    f"Fuer den Indikator muss mindestens ein gueltiges Set "
                    f"mit diesem Service erhalten bleiben (P14-04).")
                return
        reply = QMessageBox.question(
            self, "Service entfernen",
            f"Service '{service_id} [{plugin_id}]' aus dem Set entfernen?",
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
        order = [i for i in (definition.get("execution_order") or [])
                 if i != service_id]
        services.pop(service_id, None)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Service entfernt: {service_id}")
        event_bus.service_set_changed.emit()
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)

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
        damit die Service-Ausführung nie ohne Symbol-Auswahl steht. Die aktuelle
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

    # =========================================================================
    # Phase 13 Schritt 4: Service-Set-Verwaltung
    # =========================================================================

    def _clear_set_editor(self) -> None:
        """Leert den Set-Zustand (ohne Phase-13-Box: nur interne Felder +
        Parameter-Spalten)."""
        self._current_set_id = None
        self._current_set_definition = None
        # 17.01.04: Auch den Standalone-Plugin-Editor-Modus beenden.
        self._current_plugin_editing = None
        # 10.08.2026 (Bugfix, Varianten-Params): Preset-Modus ebenfalls
        # beenden (sonst wuerde der naechste Save in ein fremdes Preset
        # schreiben).
        self._current_preset_editing = None
        # Phase 15 (Dirty-State): Marker des vorherigen Sets entfernen.
        self._clear_dirty_markers()
        self._clear_service_columns()

    def load_set_into_editor(self, definition: Dict[str, Any]) -> None:
        """Uebernimmt eine ServiceSetDefinition in den internen Zustand und
        baut die dynamischen Service-Spalten (Parameterfenster, rechte
        Splitter-Spalte) neu auf."""
        # Phase 15 (Dirty-State): Marker des vorherigen Sets entfernen - ein
        # frisch geladenes Set ist per Definition unveraendert (kein '*').
        self._clear_dirty_markers()
        self._current_set_id = definition.get("set_id")
        self._current_set_definition = definition
        self._build_service_columns(definition)

    def _next_instance_id(self, services: Dict[str, Any],
                          plugin_id: str) -> str:
        """Liefert die naechste freie instance_id fuer ein Plugin im Set.

        Basis ist der plugin_id selbst (z.B. 'srv_proximity'); bei bereits
        vorhandener Instanz werden '_2', '_3', ... angehaengt."""
        base = plugin_id
        if base not in services:
            return base
        i = 2
        while f"{base}_{i}" in services:
            i += 1
        return f"{base}_{i}"

    def _add_service_to_set(self, set_id: str, plugin_id: str) -> None:
        """Fuegt einen Service (Plugin) mit Registry-Defaults zum Set hinzu.

        Phase 13-Bereinigung (05.08.2026): ersetzt den frueheren
        Eingabe-/Hinzufuegen-Pfad der entfernten Service-Sets-Box.
        Die instance_id wird automatisch vergeben (plugin_id bzw.
        plugin_id_2/_3/...), Duplikate werden dadurch ausgeschlossen.
        Persistiert sofort (set_repo.save_set) + EventBus-Live-Sync."""
        if not set_id or not plugin_id:
            return
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden. "
                     f"Verfuegbare Plugins: {_available_plugin_ids()}")
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        services = dict(definition.get("services") or {})
        order = list(definition.get("execution_order") or [])
        iid = self._next_instance_id(services, plugin_id)
        params = dict(getattr(plugin, "default_params", None) or {})
        lookback = 1000
        if "lookback" in params:
            try:
                lookback = int(params.pop("lookback") or 1000)
            except (TypeError, ValueError):
                lookback = 1000
        services[iid] = {
            "plugin_id": plugin_id,
            "lookback": lookback,
            "params": params,
            "version": getattr(plugin, "version", "0.0.0") or "0.0.0",
            # Runde 13b (Bugfix Dropdown-NoData): instance_hash mit
            # persistieren, damit NEUE Set-Instanzen von Anfang an die
            # Varianten-Einschraenkung erfuellen (vorher fehlte der Hash
            # beim regularen Hinzufuegen - der MasterTree berechnet ihn fuer
            # Alt-Bestand on-the-fly, neue Instanzen tragen ihn direkt).
            "instance_hash": generate_instance_hash(plugin_id, params),
        }
        order.append(iid)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Service hinzugefuegt: {iid} [{plugin_id}]")
        event_bus.service_set_changed.emit()
        # Aktuelle Editor-Spalten aktualisieren, wenn das Set geladen ist.
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)
    def collect_set_definition(self) -> Dict[str, Any]:
        """Baut aus dem internen Set-Zustand + Parameter-Spalten eine
        ServiceSetDefinition.

        Phase 13-Bereinigung (05.08.2026): Ohne die entfernte Service-Sets-
        Box kommen Name/Beschreibung/Reihenfolge direkt aus der geladenen
        DB-Definition (_current_set_definition); die Werte der dynamischen
        Service-Spalten werden in die services-Konfiguration uebernommen."""
        current = dict(self._current_set_definition or {})
        order = list(current.get("execution_order") or [])
        services = dict(current.get("services") or {})

        # Werte aus den dynamischen Service-Spalten uebernehmen (lookback =
        # Service-Instanz-Einstellung, wird NICHT in params geschrieben).
        for (iid, key), ctrl in self._service_param_controls.items():
            cfg = services.setdefault(
                iid, {"plugin_id": "", "lookback": 1000, "params": {}})
            if key == "lookback":
                cfg["lookback"] = int(self._ctrl_value(ctrl))
            else:
                cfg.setdefault("params", {})[key] = self._ctrl_value(ctrl)

        # Instanz-Beschreibung aus den Spalten uebernehmen
        # (ServiceInstanceConfig.description - gehoert NICHT in params).
        for iid, ctrl in self._service_desc_controls.items():
            cfg = services.setdefault(
                iid, {"plugin_id": "", "lookback": 1000, "params": {}})
            cfg["description"] = ctrl.text().strip()

        # Semantische Versionierung: aktuelle plugin.version einstempeln.
        from analytics.features.feature_builder import PluginRegistry
        registry = PluginRegistry()
        for iid, cfg in services.items():
            pid = cfg.get("plugin_id") or iid
            try:
                plugin = registry.get(pid)
                cfg["version"] = getattr(plugin, "version", "0.0.0") or "0.0.0"
            except KeyError:
                pass

        return {
            "set_id": self._current_set_id or "",
            "display_name": str(current.get("display_name") or ""),
            "description": str(current.get("description") or ""),
            "indicator_id": current.get("indicator_id"),
            "execution_order": order,
            "services": services,
        }
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

    def _open_service_desc_editor(self, instance_id: str) -> None:
        """Oeffnet den modalen ServiceDescriptionEditDialog fuer die Instanz-
        Beschreibung (Stift-Button im Parameter-Panel).

        Phase 16: Bearbeitet AUSSCHLIESSLICH die Instanz-Beschreibung
        (ServiceInstanceConfig.description) – kein Plugin-Metadaten-Fallback,
        keine Verarbeitung von Plugin-Beschreibungen im Service Window.
        """
        if not instance_id:
            return
        cfg: Dict[str, Any] = {}
        if self._current_set_definition:
            cfg = dict((self._current_set_definition.get("services") or {})
                       .get(instance_id, {}))
        desc_ctrl = self._service_desc_controls.get(instance_id)
        if desc_ctrl is not None and _qt_valid(desc_ctrl):
            cfg["description"] = desc_ctrl.text()
        plugin_id = cfg.get("plugin_id") or instance_id
        dlg = ServiceDescriptionEditDialog(
            parent=self,
            instance_id=instance_id,
            plugin_id=plugin_id,
            header_line=self._info_header_tooltip(str(plugin_id)),
            description=str(cfg.get("description") or ""),
            title="Service-Beschreibung bearbeiten",
        )
        dlg.save_requested.connect(
            lambda desc, iid=instance_id:
            self._save_instance_description(self._current_set_id or "", iid, desc))
        dlg.exec()

    def _save_instance_description(self, set_id: str, instance_id: str,
                                   new_desc: str) -> None:
        """Persistiert eine geaenderte Instanz-Beschreibung.

        Phase 16 (05.08.2026): Single Source of Truth – die Instanz-
        Beschreibung gehoert ausschliesslich in
        `ServiceInstanceConfig.description` (JSON-Payload des Service-Sets in
        app_data.duckdb, Feld definition['services'][instance_id]
        ['description']). Kein Plugin-Fallback.

        * Editor-Spalte (QLineEdit) + Tooltip werden live aktualisiert.
        * Persistenz via ServiceSetRepository.save_set() + EventBus.
        """
        clean = (new_desc or "").strip()
        # Live-Update im Editor (setText feuert textChanged → Tooltip-Sync)
        desc_ctrl = self._service_desc_controls.get(instance_id)
        if desc_ctrl is not None and _qt_valid(desc_ctrl):
            desc_ctrl.setText(clean)
        # In der geladenen Definition nachziehen (sofortige Folge-Speicherung)
        if self._current_set_definition is not None:
            cfg = (self._current_set_definition.get("services") or {}).get(instance_id)
            if isinstance(cfg, dict):
                cfg["description"] = clean
        # 17.01.04: Standalone-Plugin-Editor – Beschreibung in die Plugin-
        # Konfiguration (global_settings) uebernehmen statt in ein Set.
        if self._current_plugin_editing:
            if self._save_plugin_params():
                self.log(f"Instanz-Beschreibung '{instance_id}' gespeichert "
                         f"(Plugin).")
            return
        if not set_id:
            self.log(f"Instanz-Beschreibung '{instance_id}' aktualisiert "
                     f"(Set noch nicht gespeichert).")
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Beschreibung nicht "
                     f"gespeichert.")
            return
        services = definition.get("services") or {}
        if instance_id in services:
            services[instance_id]["description"] = clean
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
            event_bus.service_set_changed.emit()
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Instanz-Beschreibung: {e}")
            return
        # Phase 15 (Dirty-State): explizites Set-Speichern -> '*' entfernen.
        self._clear_dirty_markers()
        self.log(f"Instanz-Beschreibung '{instance_id}' gespeichert.")

    def _save_set_description(self, set_id: str, new_desc: str) -> None:
        """Persistiert die Set-Beschreibung (ServiceSetDefinition.description).

        Phase 16 (05.08.2026): analog zur Instanz-Beschreibung – Single
        Source of Truth ist das JSON-Payload des Sets in app_data.duckdb.
        """
        clean = (new_desc or "").strip()
        if self._current_set_definition is not None and \
                self._current_set_definition.get("set_id") == set_id:
            self._current_set_definition["description"] = clean
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Beschreibung nicht "
                     f"gespeichert.")
            return
        definition["description"] = clean
        try:
            self.set_repo.save_set(definition)
            event_bus.service_set_changed.emit()
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Set-Beschreibung: {e}")
            return
        # Phase 15 (Dirty-State): explizites Set-Speichern -> '*' entfernen.
        self._clear_dirty_markers()
        self.log(f"Set-Beschreibung '{set_id}' gespeichert.")

    @Slot(str, str, str)
    def _on_tree_info_requested(self, set_id: str, service_id: str,
                                plugin_id: str) -> None:
        """Oeffnet den Beschreibungs-Editor / -Dialog fuer die Info-Button-Zeile.

        Bugfix 05.08.2026: Der Info-Button sitzt jetzt direkt im MasterTree
        (Spalte 1) statt in der Box 'Service-Sets (Phase 13)'. Je nach
        Zeilentyp:

          * Service-Zeile:  ServiceDescriptionEditDialog (Instanz-Beschreibung
                            editierbar, header_line = 'aktiv/im <Indikator>').
          * Set-Zeile:      ServiceDescriptionEditDialog (Set-Beschreibung
                            editierbar, header_line aus _info_set_tooltip).
          * Plugin-Zeile:   ServiceDescriptionEditDialog (Plugin-Info, ohne
                            Instanz) – Bugfix 05.08.2026: derselbe Editor wie
                            bei den Einzel-Services der Sets (vorbefuellt mit
                            der Plugin-Beschreibung; kein Persistenz-Ziel).

        Bugfix 05.08.2026: Auch Plugin-/Standalone-Zeilen oeffnen den
        Beschreibungs-Editor (konsistent zu den Einzel-Services). Eine
        persistierbare Beschreibung existiert nur fuer Instanzen (in Sets)
        und fuer die Sets selbst.
        """
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return
        try:
            # 1) Service-Zeile (set_id + service_id) – editierbar
            if service_id and set_id:
                cfg = model.find_service(set_id, service_id) or {}
                pid = str(cfg.get("plugin_id") or service_id)
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id=service_id,
                    plugin_id=pid,
                    header_line=self._info_header_tooltip(pid),
                    description=str(cfg.get("description") or ""),
                    title="Service-Beschreibung bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda desc, s=set_id, i=service_id:
                    self._save_instance_description(s, i, desc))
                dlg.exec()
                return
            # 2) Plugin-Zeile (nur plugin_id; set_id = Gruppenkennung) –
            #    EDITIERBAR wie die Einzel-Services der Sets (Bugfix
            #    05.08.2026): derselbe ServiceDescriptionEditDialog. Ein
            #    Plugin ohne Instanz/Set hat keine persistierbare Instanz-
            #    Beschreibung – der Editor wird mit der Plugin-Metadaten-
            #    Beschreibung vorbefuellt (kein save_requested: Speichern/
            #    Abbrechen schliessen den Dialog, es gibt kein Ziel).
            if plugin_id and not service_id:
                plugin = self._resolve_info_plugin(plugin_id)
                if plugin is None:
                    return
                meta = dict(getattr(plugin, "metadata", None) or {})
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id="",
                    plugin_id=plugin_id,
                    header_line=self._info_header_tooltip(plugin_id),
                    description=str(meta.get("description") or ""),
                    title="Service-Beschreibung bearbeiten",
                )
                dlg.exec()
                return
            # 3) Set-Zeile (nur set_id) – editierbar (Set-Beschreibung)
            if set_id and not service_id and not plugin_id:
                set_def = model.find_set(set_id)
                if not set_def:
                    self.log(f"Set '{set_id}' nicht gefunden.")
                    return
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id="",
                    plugin_id=str(set_def.get("display_name") or set_id),
                    header_line=self._info_set_tooltip(set_def),
                    description=str(set_def.get("description") or ""),
                    title="Set-Beschreibung bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda desc, s=set_id: self._save_set_description(s, desc))
                dlg.exec()
                return
        except (RuntimeError, AttributeError) as e:
            self.log(f"Info-Dialog nicht moeglich: {e}")

    # =========================================================================
    # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im MasterTree-Kontextmenue
    # -------------------------------------------------------------------------
    # 'Data Only Löschen', 'Vollständig Löschen', 'Doc Log bearbeiten' und
    # 'Als Variante duplizieren' fuer Service-Instanzen (in Sets) und
    # Plugin-Clones (indicator_presets). Alle Aktionen laufen entkoppelt
    # ueber die MasterTree-Signale (keine UI-Kopplung, Invariante 2).
    # =========================================================================

    def _find_preset_for_hash(self, plugin_id: str,
                              instance_hash: str) -> Optional[Dict[str, Any]]:
        """Findet das Preset (indicator_presets) eines Clones ueber seinen
        deterministischen instance_hash (20.04, Q2/Q4)."""
        if not plugin_id or not instance_hash:
            return None
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            return None
        try:
            for p in sm.list_plugin_presets(plugin_id) or []:
                if not isinstance(p, dict):
                    continue
                params = p.get("params") or {}
                # 11.08.2026 (Bugfix Varianten-Kollision): Der Hash eines
                # Presets fliesst inkl. preset_name ein (identisch zum
                # ServiceSelectorModel / variant_run_entries). Fallback auf
                # den Legacy-Params-only-Hash fuer Alt-Bestand.
                preset_name = str(p.get("preset_name") or "Default")
                if (generate_instance_hash(plugin_id, params,
                                           preset_name=preset_name)
                        == instance_hash
                        or generate_instance_hash(plugin_id, params)
                        == instance_hash):
                    return p
        except Exception as e:
            self.log(f"Preset-Suche fehlgeschlagen: {e}")
        return None

    def _purge_legacy_allowed(self, plugin_id: str,
                              params: Optional[Dict[str, Any]]) -> bool:
        """True, wenn der Params-only-Legacy-Pool der Variante EINDEUTIG
        dieser Variante gehoert (12.08.2026, Bugfix Runde 6).

        Alt-Rows aus Runs VOR der Preset-Hash-Umstellung (11.08.2026) liegen
        unter dem reinen Params-only-Hash `generate_instance_hash(plugin_id,
        params)` (ohne preset_name). Dieser Pool ist mehreren Varianten mit
        IDENTISCHEN Params gemeinsam - er darf beim 'Data Only Loeschen'
        einer einzelnen Variante nur entfernt werden, wenn KEINE andere
        aktive Variante (Preset/Clone ODER Set-Instanz) denselben
        Params-only-Hash besitzt.

        Returns:
            True = Pool eindeutig dieser Variante zugeordnet (Legacy-Purge
            erlaubt); False = Pool wird geteilt oder nicht bestimmbar.
        """
        if not plugin_id or params is None:
            return False
        try:
            from analytics.engine.service_models import generate_instance_hash
        except Exception:
            return False
        target = generate_instance_hash(plugin_id, params)
        owners = 0
        sm = getattr(self, "_state_manager", None)
        if sm is not None:
            try:
                for p in sm.list_plugin_presets(plugin_id) or []:
                    if not isinstance(p, dict):
                        continue
                    if generate_instance_hash(
                            plugin_id, p.get("params") or {}) == target:
                        owners += 1
            except Exception:
                pass
        try:
            for set_id in self.set_repo.list_sets():
                defn = self.set_repo.get_set(set_id)
                if not isinstance(defn, dict):
                    continue
                for cfg in (defn.get("services") or {}).values():
                    if not isinstance(cfg, dict):
                        continue
                    cpid = str(cfg.get("plugin_id") or "")
                    if cpid.lower() == plugin_id.lower() and \
                            generate_instance_hash(
                                cpid, cfg.get("params") or {}) == target:
                        owners += 1
        except Exception:
            pass
        # owners == 1: nur diese eine Variante belegt den Pool. owners == 0
        # (z. B. Standalone-Service): kein Legacy-Pool-Szenario - False.
        return owners == 1

    def _next_preset_copy_name(self, sm, plugin_id: str,
                               base: str) -> str:
        """Naechster freier Preset-Name fuer eine Varianten-Kopie (Q8).

        Quelle ist `list_plugin_presets(plugin_id)` (nur ECHTE Preset-Rows) –
        NICHT `list_indicator_presets`, das den UI-Default 'Default' immer
        fabriziert. Ist der Basis-Name (z. B. 'Default') noch GAR NICHT
        vergeben – der Fall eines flachen Plugin-Blattes, das seine erste
        Variante erhaelt – wird der Basis-Name direkt verwendet. Sonst
        '<base> (Kopie)', '(Kopie 2)', ...
        """
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if base not in existing:
            return base
        candidate = f"{base} (Kopie)"
        i = 2
        while candidate in existing:
            candidate = f"{base} (Kopie {i})"
            i += 1
        return candidate

    @Slot(str, str, str, str)
    def _on_data_only_purge(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Data Only Löschen' (20.04, Q5): purge_instance_data.

        Entfernt NUR die berechneten Feature-Daten der Instanz aus dem
        feature_store – die Instanz-Konfiguration (Set/Preset) bleibt
        unangetastet; die Daten werden beim naechsten Scan neu berechnet.

        * Service-in-Set: Hash aus der Set-Definition (cfg.instance_hash)
          oder bei Alt-Daten aus den aktuellen Params neu berechnet.
        * Clone/Preset: Hash direkt aus ROLE_INSTANCE_HASH.
        """
        params = None
        if not instance_hash:
            if set_id and service_id:
                model = getattr(self.service_selector, "model", None)
                cfg = model.find_service(set_id, service_id) if model else None
                if cfg:
                    params = cfg.get("params") or {}
                    instance_hash = generate_instance_hash(
                        cfg.get("plugin_id") or service_id, params)
            if not instance_hash:
                self.log("Kein instance_hash fuer 'Data Only Löschen' "
                         "verfuegbar.")
                return
        # 11.08.2026 (Bugfix Runde 5): Parameter der Variante ermitteln
        # – Grundlage fuer den Legacy-Pool-Purge (Params-only-Hash) im
        # FeatureBuilder – sonst bleiben die Alt-Rows und das Datum
        # setzt nach dem Purge nicht auf 'nie' zurueck.
        if params is None:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset:
                params = preset.get("params") or {}
        label = service_id or f"{plugin_id} (#{instance_hash})"
        reply = QMessageBox.question(
            self, "Data Only Löschen",
            f"Berechnete Feature-Daten der Instanz '{label}' "
            f"(#{instance_hash}) dauerhaft löschen?\n\n"
            "Gelöscht werden ALLE Timeframes (M1-MN1) dieser "
            "Variante. Die Instanz-Konfiguration bleibt erhalten – die Daten werden "
            "beim nächsten Scan neu berechnet.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            from analytics.features.feature_builder import FeatureBuilder
            n = FeatureBuilder().purge_instance_data(
                instance_hash, plugin_id, params,
                purge_legacy=self._purge_legacy_allowed(
                    plugin_id, params))
        except Exception as e:
            self.log(f"FEHLER beim Purgen der Feature-Daten: {e}")
            return
        self.log(f"Feature-Daten gelöscht: {n} Zeilen "
                 f"(Instanz #{instance_hash}, alle Timeframes).")
        self._reset_run_progress()
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_delete_complete(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Vollständig Löschen' (20.04): Instanz/Preset + Daten entfernen.

        Zwei Sicherheitsabfragen (P14-05-Muster). Betrifft:
        * Service-in-Set: Instanz aus service_sets entfernen + Feature-Daten
          der Variante purgen (Hash aus cfg bzw. Params).
        * Clone/Preset: indicator_presets-Eintrag löschen + Feature-Daten
          purgen (Archiv-Einheit: einzelner Clone – auch archivierte Clones
          sind hierueber endgueltig entfernt).
        """
        if set_id and service_id:
            self._delete_complete_set_instance(set_id, service_id, plugin_id)
        elif plugin_id:
            self._delete_complete_preset(plugin_id, instance_hash)
        else:
            self.log("Vollständig Löschen: keine Ziel-Instanz.")

    def _delete_complete_set_instance(self, set_id: str, service_id: str,
                                      plugin_id: str) -> None:
        """Voll-Loeschung einer Service-Instanz in einem Set."""
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id) or {}
        pid = str(cfg.get("plugin_id") or plugin_id or service_id)
        # P14-04-E: nur der LETZTE Vorkommen eines Indikator-Services gesperrt.
        if self._plugin_belongs_to_indicator(pid):
            others = self._remaining_sets_with_plugin(
                pid, exclude_set_id=set_id)
            if not others:
                QMessageBox.warning(
                    self, "Service gesperrt",
                    f"Der Service '{pid}' ist der letzte in einem "
                    f"gespeicherten Service-Set.\n"
                    f"Für den Indikator muss mindestens ein gültiges Set "
                    f"mit diesem Service erhalten bleiben (P14-04).")
                return
        label = f"{service_id} [{pid}]"
        reply = QMessageBox.question(
            self, "Vollständig Löschen",
            f"Instanz '{label}' vollständig löschen?\n\n"
            "Die Instanz wird aus dem Set entfernt UND die berechneten "
            "Feature-Daten dieser Parameter-Variante werden gelöscht "
            "(ALLE Timeframes M1-MN1).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            f"'{label}' wird dauerhaft entfernt – inkl. aller gespeicherten "
            "Feature-Daten der Variante. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        # 1) Instanz aus dem Set entfernen
        order = [i for i in (definition.get("execution_order") or [])
                 if i != service_id]
        services.pop(service_id, None)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        # 2) Feature-Daten der Variante purgen
        hash_ = str(cfg.get("instance_hash") or "")
        if not hash_:
            hash_ = generate_instance_hash(pid, cfg.get("params") or {})
        if hash_:
            try:
                from analytics.features.feature_builder import FeatureBuilder
                n = FeatureBuilder().purge_instance_data(
                    hash_, pid, cfg.get("params") or {})
            except Exception as e:
                n = 0
                self.log(f"WARN: Feature-Daten-Purge fehlgeschlagen: {e}")
            self.log(f"Variante #{hash_} purged ({n} Zeilen).")
            self._reset_run_progress()
        self.log(f"Instanz vollständig gelöscht: {label}")
        event_bus.service_set_changed.emit()
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)

    def _delete_complete_preset(self, plugin_id: str,
                                instance_hash: str) -> None:
        """Voll-Loeschung eines Plugin-Presets/Clones."""
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            self.log(f"Preset zu #{instance_hash} nicht gefunden.")
            return
        preset_name = str(preset.get("preset_name") or "Default")
        indicator_id = str(preset.get("indicator_id") or "")
        reply = QMessageBox.question(
            self, "Vollständig Löschen",
            f"Preset '{preset_name}' von '{plugin_id}' vollständig löschen?"
            f"\n\nDas Preset wird aus indicator_presets entfernt UND die "
            "berechneten Feature-Daten dieser Parameter-Variante werden "
            "gelöscht (ALLE Timeframes M1-MN1).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            f"'{preset_name}' wird dauerhaft gelöscht – inkl. aller "
            "gespeicherten Feature-Daten der Variante. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        sm = getattr(self, "_state_manager", None)
        if sm is not None and indicator_id:
            try:
                sm.delete_indicator_preset(indicator_id, preset_name)
            except Exception as e:
                self.log(f"FEHLER beim Löschen des Presets: {e}")
                return
        if instance_hash:
            try:
                from analytics.features.feature_builder import FeatureBuilder
                n = FeatureBuilder().purge_instance_data(
                    instance_hash, plugin_id, preset.get("params") or {},
                    purge_legacy=self._purge_legacy_allowed(
                        plugin_id, preset.get("params") or {}))
            except Exception as e:
                n = 0
                self.log(f"WARN: Feature-Daten-Purge fehlgeschlagen: {e}")
            self.log(f"Variante #{instance_hash} purged ({n} Zeilen).")
            self._reset_run_progress()
        self.log(f"Preset vollständig gelöscht: '{preset_name}'.")
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_doc_log_requested(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Doc Log bearbeiten' (20.04, Q1/Q7).

        Oeffnet den ServiceDescriptionEditDialog fuer das Freitextfeld
        (Negativ-Wissen). Persistenz:
        * Service-in-Set: ServiceInstanceConfig.doc_log (Set-JSON).
        * Clone/Preset: indicator_presets.doc_log.
        """
        try:
            if set_id and service_id:
                model = getattr(self.service_selector, "model", None)
                cfg = model.find_service(set_id, service_id) if model else None
                cfg = cfg or {}
                pid = str(cfg.get("plugin_id") or service_id)
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id=service_id,
                    plugin_id=pid,
                    header_line=self._info_header_tooltip(pid),
                    description=str(cfg.get("doc_log") or ""),
                    title="Doc Log bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda text, s=set_id, i=service_id:
                    self._save_instance_doc_log(s, i, text))
                dlg.exec()
                return
            if plugin_id and instance_hash:
                preset = self._find_preset_for_hash(plugin_id, instance_hash)
                preset_name = str((preset or {}).get("preset_name")
                                  or instance_hash)
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id=preset_name,
                    plugin_id=plugin_id,
                    header_line=self._info_header_tooltip(plugin_id),
                    description=str((preset or {}).get("doc_log") or ""),
                    title="Doc Log bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda text, p=plugin_id, h=instance_hash:
                    self._save_plugin_doc_log(p, h, text))
                dlg.exec()
                return
        except (RuntimeError, AttributeError) as e:
            self.log(f"Doc-Log-Dialog nicht möglich: {e}")

    def _save_instance_doc_log(self, set_id: str, instance_id: str,
                               new_log: str) -> None:
        """Persistiert das Doc-Log einer Service-Instanz (20.04, Q7).

        Ziel: ServiceInstanceConfig.doc_log im Set-JSON (single source of
        truth wie description). Analog _save_instance_description.
        """
        clean = (new_log or "").strip()
        # In der geladenen Definition nachziehen (sofortige Folge-Speicherung)
        if self._current_set_definition is not None:
            cfg = (self._current_set_definition.get("services") or {}).get(
                instance_id)
            if isinstance(cfg, dict):
                cfg["doc_log"] = clean
        if not set_id:
            self.log(f"Doc Log '{instance_id}' aktualisiert "
                     f"(Set noch nicht gespeichert).")
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Doc Log nicht "
                     f"gespeichert.")
            return
        services = definition.get("services") or {}
        if instance_id in services:
            services[instance_id]["doc_log"] = clean
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
            event_bus.service_set_changed.emit()
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Doc Logs: {e}")
            return
        self._clear_dirty_markers()
        self.log(f"Doc Log '{instance_id}' gespeichert.")

    def _save_plugin_doc_log(self, plugin_id: str, instance_hash: str,
                             new_log: str) -> None:
        """Persistiert das Doc-Log eines Plugin-Presets (20.04, Q7)."""
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            self.log("Doc Log nicht gespeichert (kein StateManager).")
            return
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if not preset or not preset.get("indicator_id"):
            self.log(f"Preset zu #{instance_hash} nicht gefunden.")
            return
        try:
            sm.set_plugin_preset_doc_log(
                preset.get("indicator_id"), preset.get("preset_name"),
                new_log)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Preset-Doc-Logs: {e}")
            return
        self.log(f"Doc Log '{preset.get('preset_name')}' gespeichert.")
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_duplicate_variant(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Als Variante duplizieren' (20.04, Q8).

        * Service-in-Set: neue Instanz mit kopierten Parametern + neu
          berechnetem instance_hash (neue instance_id via _next_instance_id).
        * Clone/Preset: neues Preset mit kopierten Parametern (Name
          '<Preset> (Kopie)'); aus einem flachen Plugin-Blatt entsteht so
          die erste Variante.
        """
        if set_id and service_id:
            self._duplicate_set_instance(set_id, service_id)
            return
        if plugin_id:
            self._duplicate_preset(plugin_id, instance_hash)
            return
        self.log("Als Variante duplizieren: keine Ziel-Instanz.")

    @Slot(str, str, str)
    def _on_rename_variant(self, plugin_id: str, instance_hash: str,
                           new_name: str) -> None:
        """'Variante umbenennen' (10.08.2026, Bugfix).

        Benennt ein Plugin-Preset (Clone/Variante) in indicator_presets um.
        Kollisionspruefung gegen die UEBRIGEN Presets des Plugins; die
        Feature-Store-Daten (Spalte instance_hash) bleiben unberuehrt
        (der Hash haengt an den Parametern, nicht am Namen).
        """
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            self.log(f"Preset zu #{instance_hash} nicht gefunden – "
                     f"Umbenennen abgebrochen.")
            return
        old_name = str(preset.get("preset_name") or "Default")
        indicator_id = str(preset.get("indicator_id") or "")
        if not indicator_id:
            self.log("Preset hat keine indicator_id – Umbenennen abgebrochen.")
            return
        clean = (new_name or "").strip()
        if not clean or clean == old_name:
            return
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            self.log("Umbenennen nicht moeglich (kein StateManager).")
            return
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception as e:
            self.log(f"FEHLER beim Laden der Preset-Namen: {e}")
            return
        if clean in existing:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Eine andere Variante von '{plugin_id}' heisst bereits "
                f"'{clean}'.")
            return
        try:
            sm.rename_indicator_preset(indicator_id, old_name, clean)
        except Exception as e:
            self.log(f"FEHLER beim Umbenennen der Variante: {e}")
            return
        self.log(f"Variante '{old_name}' umbenannt zu '{clean}'.")
        event_bus.service_set_changed.emit()

    def _duplicate_set_instance(self, set_id: str, service_id: str) -> None:
        """Dupliziert eine Service-Instanz in ihrem Set (Q8)."""
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id)
        if not isinstance(cfg, dict):
            self.log(f"Instanz '{service_id}' nicht gefunden.")
            return
        pid = str(cfg.get("plugin_id") or service_id)
        iid = self._next_instance_id(services, pid)
        copy = dict(cfg)
        copy["params"] = dict(cfg.get("params") or {})
        copy["instance_hash"] = generate_instance_hash(pid, copy["params"])
        copy.pop("description", None)
        copy.pop("doc_log", None)
        services[iid] = copy
        order = list(definition.get("execution_order") or [])
        order.append(iid)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Variante '{iid}' dupliziert aus '{service_id}' "
                 f"(#{copy['instance_hash']}).")
        event_bus.service_set_changed.emit()
        # Q8-Bugfix: Ergebnis SICHTBAR machen – das Ziel-Set wird in den
        # Parameter-Editor geladen (neue Service-Spalte der Variante) und
        # die neue Instanz im Baum expandiert/selektiert.
        self.load_set_into_editor(definition)
        tree = getattr(getattr(self, "service_selector", None),
                       "master_tree", None)
        if tree is not None:
            tree.select_instance(set_id, iid)

    def _duplicate_preset(self, plugin_id: str, instance_hash: str) -> None:
        """Dupliziert einen Plugin-Clone als neues Preset (Q8)."""
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            self.log("Variante nicht dupliziert (kein StateManager).")
            return
        if instance_hash:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset is None:
                self.log(f"Preset zu #{instance_hash} nicht gefunden.")
                return
            base = str(preset.get("preset_name") or "Default")
            params = dict(preset.get("params") or {})
            indicator_id = str(preset.get("indicator_id") or "")
            version = preset.get("version")
            # Diff 2 (User-Bugreport 09.08.2026): Eine duplizierte Variante
            # ist IMMER batch-aktiv (is_active_batch=True) – NICHT der Status
            # des Quell-Presets. Sonst bliebe eine archivierte/inaktive Kopie
            # unsichtbar: Scans/LiveAnalyzer ignorieren is_active_batch=False
            # und das Analytics-Dropdown zeigt sie erst nach einem Run.
            is_active = True
        else:
            # Flaches Plugin-Blatt: aktuelle Standalone-Parameter
            # (global_settings, Key 'plugin_params_<plugin_id>').
            try:
                raw = sm.get_global_value(f"plugin_params_{plugin_id}", {})
            except Exception:
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            base = "Default"
            params = dict(raw.get("params") or {})
            indicator_id = plugin_id
            version = raw.get("version") or "1.0.0"
            is_active = True
        if not indicator_id:
            indicator_id = plugin_id
        # 10.08.2026 (Bugfix): Beim Anlegen einer neuen Variante MUSS ein
        # neuer Name vergeben werden – kein stummes Auto-Schema
        # ('<base> (Kopie)'). Der Dialog ist mit dem freien Kopiernamen
        # vorbelegt; Kollisionen werden abgefangen.
        suggested = self._next_preset_copy_name(sm, plugin_id, base)
        new_name, ok = QInputDialog.getText(
            self, "Variante anlegen",
            f"Name für die neue Variante (aus '{base}'):", text=suggested)
        new_name = (new_name or "").strip()
        if not ok or not new_name:
            self.log("Variante nicht dupliziert (Name fehlt/abgebrochen).")
            return
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if new_name in existing:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Eine andere Variante von '{plugin_id}' heisst bereits "
                f"'{new_name}'.")
            return
        try:
            sm.save_indicator_preset(
                indicator_id, new_name, params,
                plugin_id=plugin_id,
                version=version,
                is_active_batch=is_active,
                doc_log="",
            )
        except Exception as e:
            self.log(f"FEHLER beim Duplizieren der Variante: {e}")
            return
        # 11.08.2026 (Bugfix Varianten-Kollision): Der Hash der neuen
        # Variante fliesst inkl. des NEUEN Preset-Namens ein (identisch zum
        # ServiceSelectorModel) - sonst kollidieren Params-only-Hashes.
        new_hash = generate_instance_hash(plugin_id, params,
                                          preset_name=new_name)
        self.log(f"Variante '{new_name}' dupliziert aus '{base}' "
                 f"(#{new_hash}).")
        event_bus.service_set_changed.emit()
        # Q8-Bugfix: Ergebnis SICHTBAR machen – den neuen Clone-Knoten im
        # Baum expandieren/selektieren (ohne Editor-Overwrite; der Clone-
        # Tooltip zeigt die kopierten Parameter).
        tree = getattr(getattr(self, "service_selector", None),
                       "master_tree", None)
        if tree is not None:
            tree.select_clone(plugin_id, new_hash)

    def _resolve_info_plugin(self, plugin_id: str):
        """Liefert das Plugin aus der Registry (oder None + Log-Eintrag)."""
        try:
            from analytics.features.feature_builder import PluginRegistry
            return PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden.")
            return None

    def _info_header_tooltip(self, plugin_id: str) -> str:
        """Erste Dialog-Zeile = Badge-Header des Info-Buttons (20.03.02, F5).

        Vereinheitlichtes Format: '📌 im <Indikator> | 🟢 aktiv in
        <Indikator>' bzw. '📌 im <Indikator> | ⚪ inaktiv'. Leer ohne
        Indikator-Zugehoerigkeit.
        """
        model = getattr(self.service_selector, "model", None)
        if model is None or not model.belongs_to_indicator(plugin_id):
            return ""
        name = model.get_indicator_display_name(plugin_id)
        if model.is_active_in_chart(plugin_id):
            return f"📌 im {name} | 🟢 aktiv in {name}"
        return f"📌 im {name} | ⚪ inaktiv"

    def _info_set_tooltip(self, set_def: Dict[str, Any]) -> str:
        """Erste Dialog-Zeile fuer Set-Zeilen (20.03.02, F5).

        Vereinheitlichtes Badge-Format analog _info_header_tooltip; mehrere
        Indikatoren mit ' + ' verknuepft ('📌 im <I1> + <I2> | 🟢 aktiv in
        <I1> + <I2>' bzw. '⚪ inaktiv').
        """
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return ""
        names = model.get_set_indicator_names(set_def or {})
        if not names:
            return ""
        label = " + ".join(names)
        if model.is_set_active(set_def or {}):
            return f"📌 im {label} | 🟢 aktiv in {label}"
        return f"📌 im {label} | ⚪ inaktiv"

    @Slot()
    def delete_set(self) -> None:
        """Loescht das aktive Set in den Papierkorb (P14-05).

        Phase 13-Bereinigung (05.08.2026): Ohne die entfernte Service-Sets-
        Box wird direkt auf die DB-Definition des geladenen Sets zugegriffen
        (kein NamedItemAdapter mehr). P14-04-E-Sperre ('letztes Set') und
        Papierkorb-Rueckfrage bleiben unveraendert."""
        current_id = self._current_set_id
        if not current_id:
            self.log("Kein Set geladen - Loeschen nicht moeglich.")
            return
        current = None
        try:
            current = self.set_repo.get_set(current_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not current:
            self.log(f"Set '{current_id}' nicht gefunden.")
            return
        # P14-04-E-Sperre: Letzter Vorkommen eines Indikator-Services.
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
                    self, "Loeschen gesperrt",
                    f"Dieses Service-Set enthaelt den letzten "
                    f"gespeicherten Service '{pid}' fuer den Indikator.\n"
                    f"Es muss mindestens ein gueltiges Set mit diesem "
                    f"Service erhalten bleiben (P14-04).")
                return
        name = str(current.get("display_name") or current_id)
        reply = QMessageBox.question(
            self, "Set in den Papierkorb verschieben",
            f"Set '{name}' wirklich in den Papierkorb verschieben?\n"
            f"(Wiederherstellung ueber den Papierkorb-Dialog moeglich.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            ok = self.set_repo.delete_set(current_id)
        except Exception as e:
            self.log(f"FEHLER beim Loeschen des Sets: {e}")
            return
        if not ok:
            self.log(f"Set '{current_id}' nicht gefunden.")
            return
        self.log(f"Set in den Papierkorb verschoben (P14-05): {current_id}")
        event_bus.service_set_changed.emit()
        self._current_set_id = None
        self._current_set_definition = None
        self._clear_dirty_markers()
        self._clear_service_columns()
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
            refresh_fn=lambda: None,
            parent=self,
        )
        dialog.exec()

    # =========================================================================
    # Phase 14 P14-02: Hot-Reload der Plugins (Dynamic Discovery)
    # =========================================================================

    def closeEvent(self, event):
        # PersistentWindow.save_state() wird in super().closeEvent gerufen
        # 05.08.2026: Gezielter Kontextmenue-Run-Worker sauber beenden.
        if self._run_worker and self._run_worker.isRunning():
            self._run_worker.wait(2000)
        super().closeEvent(event)
