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
from typing import Any, Dict, Optional, Tuple

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
from serviceui.service_win_run import ServiceRunMixin
from serviceui.service_win_tree import ServiceTreeMixin
from serviceui.service_win_editor import ServiceEditorMixin
from serviceui.service_win_sets import ServiceSetsMixin
from serviceui.service_win_presets import ServicePresetMixin
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
from repositories.symbol_repository import SymbolRepository, get_symbol_repository
from config.event_bus import event_bus

# Phase 15 15.02: Service-UI Refactoring – MasterTree & generischer
# ServiceSelector (ServiceSelectorWidget im Modus FULL_EDIT).
from serviceui.service_selector_widget import ServiceSelectorWidget

# Projekt-Root (eine Ebene über serviceui/) – für die UI-Datei unter ui/.
BASE_DIR = Path(__file__).resolve().parent.parent


@register_persistent_window()  # auto_restore=True (Bugfix 05.08.2026)
class ServiceWindow(ServiceParamColumnsMixin, ContentScrollMixin, NamedItemActionsMixin,
                   ServiceRunMixin, ServiceTreeMixin, ServiceEditorMixin,
                   ServiceSetsMixin, ServicePresetMixin, PersistentWindow):
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
        # 12.08.2026 (User-Meldung 'Data only loeschen'): Optionaler
        # instance_hash der angezeigten Variante - der Pill-Strip wird
        # damit VARIANTEN-GENAU geladen (nach Purge verschwinden ihre TFs).
        self._badge_instance_hash: Optional[str] = None
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
            # 12.08.2026 (User-Meldung 'Fortschrittsbalken laeuft dauerhaft'):
            # setMaximum(0) startet eine INDETERMINATE Busy-Animation, die nie
            # endet. Determinate leere Range (0..1, Wert 0) statt Busy-Loop;
            # _on_service_progress setzt beim Run die echte Range (max(total,1)).
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)
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
            # 21.03.22 (Full Market-Data Sync Button): Der Button wird hier
            # nur ERZEUGT (Parent self.ui) - platziert wird er weiter unten
            # in der Filter-/Symbol-Zeile (layout_symbol) LINKS neben dem
            # Papierkorb (btn_trash_sets). Waehrend des Syncs pausiert der
            # 45s-Auto-Sync (Concurrency-Guard).
            self.btn_sync_all_market = QPushButton(
                "🔄 Sync Alle Daten", self.ui)
            self.btn_sync_all_market.setToolTip(
                "Aktualisiert ALLE in market_data.duckdb gespeicherten "
                "Symbol:Timeframe-Paare aus MT5."
            )
            self._sync_worker = None
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
        # 21.03.22 (Full Market-Data Sync Button): Manueller Full-Sync aller
        # gespeicherten Symbol:TF-Paare (Concurrency-Guard pausiert den
        # 45s-sync_timer waehrend des Laufs).
        if self.btn_sync_all_market:
            self.btn_sync_all_market.clicked.connect(
                self._on_sync_all_market_clicked)
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
        # 21.03.22 (Full Market-Data Sync Button): Links neben dem Papierkorb
        # (btn_trash_sets). Damit Papierkorb + Sync-Button rechtsbuendig mit
        # dem rechten Ende der Parameter-Box abschliessen, wird der bestehende
        # horizontalSpacer der .ui zum Stretch-Spacer (setStretch) - die
        # Gruppe rutscht damit an den rechten Fensterrand (= Param-Box-Rand).
        if layout_symbol is not None and self.btn_trash_sets is not None:
            btn_sync = getattr(self, "btn_sync_all_market", None)
            if btn_sync is not None:
                for _i in range(layout_symbol.count()):
                    _item = layout_symbol.itemAt(_i)
                    if _item is not None and _item.spacerItem() is not None:
                        layout_symbol.setStretch(_i, 1)
                        break
                idx = layout_symbol.indexOf(self.btn_trash_sets)
                layout_symbol.insertWidget(idx, btn_sync)
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
        # 13.08.2026 (Runde 3d): Grafikteiler Tree|Parameter in der
        # Fenster-Historie sichern (Restore in restore_state).
        try:
            sp = getattr(self, "main_splitter", None)
            if sp is not None:
                self._state_manager.save_splitter_state(
                    self.DIALOG_GEOMETRY_KEY, sp.sizes())
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
            # 13.08.2026 (Runde 3d): Grafikteiler Tree|Parameter aus
            # der Historie wiederherstellen.
            try:
                sizes = self._state_manager.get_splitter_state(
                    self.DIALOG_GEOMETRY_KEY)
                sp = getattr(self, "main_splitter", None)
                if sizes and sp is not None:
                    clean = [int(s) for s in sizes
                             if str(s).strip().lstrip("-").isdigit()
                             and int(s) > 0]
                    if len(clean) == 2:
                        sp.setSizes(clean)
            except Exception:
                pass
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
    # Phase 14 P14-02: Hot-Reload der Plugins (Dynamic Discovery)
    # =========================================================================

    def closeEvent(self, event):
        # PersistentWindow.save_state() wird in super().closeEvent gerufen
        # 05.08.2026: Gezielter Kontextmenue-Run-Worker sauber beenden.
        if self._run_worker and self._run_worker.isRunning():
            # 12.08.2026 (WAL-Korruption beim App-Exit): Worker VOR dem
            # Fenster-Close sauber stoppen - sonst stirbt der Thread mitten
            # im DB-Write, wenn die App den Prozess beendet (korrupte WAL
            # beim naechsten Start). stop() setzt nur das Abbruch-Flag; der
            # Worker beendet sich an der naechsten Service-Grenze.
            self._run_worker.stop()
            self._run_worker.wait(5000)
        super().closeEvent(event)
