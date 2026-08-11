# analytics/ui/analytics_win.py
"""
analytics_win.py - AnalyticsWindow (Phase 15.03).

Hauptfenster der Analytics-Engine: `PersistentWindow` mit INSTANCE_ID
"win_analytics", 1280 x 800, nicht-modal. Ersetzt das Legacy-
Statistik-Fenster (`statistic_win.py`; E-1: das Alt-Repository
`analytics/statistics_repository.py` bleibt bestehen).

MVVM-Orchestrator (Invariante 4, kein SQL in der UI):
    UI (Top-Bar CRUD, Sidebar, Pages) <-> AnalyticsViewModel <-> Worker
    <-> AnalyticsRepository/FeatureStoreReader <-> DuckDB

Aufgaben (15.03-Spezifikation):
- Top-Bar: Profil-CRUD (Option B – Explicit Save, Dirty-Flag '*').
- Sidebar-Navigation: Tabelle, Heatmap, Scatter, Verteilung, Equity.
- 15.03-E: Datenquellen-Dialog (`ServiceSelectorDialog`, Multi-Select) ersetzt
  das alte combo_feature-Dropdown UND das Service-Filter-Popover – Checkbox-
  MasterTree (Sets/Services/Standalone/Plugins), Button `[ 🛠️ Datenquellen:
  ... ▾ ]`, ViewModel `set_feature_ids(...)`, SQL `WHERE feature_id IN (...)`.
- Jump-to-Chart (Variante 2): open_chart_at_bar(symbol, tf, bar_time)
  und Chart-Fenster in den Vordergrund holen.
- E-2: Migration der win_statistics-Persistenz nach win_analytics
  (Fenstergeometrie & Instanz-Zustand).
- EventBus (Invariante 5): Profilwechsel + Favoriten-Aenderungen.
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_view_model import AnalyticsViewModel
from analytics.engine.analytics_worker import QUERY_TABLE
from analytics.engine.service_selector_model import ServiceSelectorModel
from analytics.ui.table_page import TablePage
from analytics.ui.heatmap_page import HeatmapPage
from analytics.ui.scatter_page import ScatterPage
from analytics.ui.distribution_page import DistributionPage
from analytics.ui.equity_page import EquityPage
from persistent_win import PersistentWindow, register_persistent_window
from state_manager import StateManager
from symbol_repository import SymbolRepository, get_symbol_repository
from config.event_bus import event_bus
from serviceui.service_selector_dialog import ServiceSelectorDialog
from serviceui.symbols_win import SymbolsWindow

# Im AnalyticsWindow angebotene Timeframes (Feature-Store-Auswahl).
# 15.03-Fix: ALLE MT5-Timeframes werden angeboten (der Feature-Store haelt
# z. B. fuer SILVER Daten in M1, M2, M5, M10, M15, M30, H1, H4, D1, W1, MN1).
# Timeframes ohne Feature-Store-Daten werden in der Combo ausgegraut
# (_refresh_timeframe_combo) und sind nicht auswaehlbar.
TIMEFRAMES = ["M1", "M2", "M5", "M10", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]

# Fenstertitel (Option B: '*' = ungespeicherte Parametertrends).
WINDOW_TITLE_BASE = "PyTrader - Analytics"


def migrate_statistics_persistence(
    state_manager: Optional[StateManager] = None,
) -> bool:
    """E-2: Migriert Fenstergeometrie & Instanz-Zustand von win_statistics.

    Wird beim Oeffnen des AnalyticsWindow EINMALIG ausgefuehrt (idempotent):
    - Geometrie (window_instances) wird nach win_analytics kopiert (nur wenn
      dort noch kein Eintrag existiert).
    - Instanz-Zustand (instance_states: symbol/timeframe) wird kopiert.
    - Die Alt-Eintraege win_statistics werden entfernt (statistic_win ist
      durch AnalyticsWindow ersetzt).

    Hinweis (15.03): Die Fensterzustands-Persistenz wird laut Entscheidung
    E-2 in 15.04 in `window_state_repository.py` gekapselt; bis dahin nutzt
    die Migration direkt das StateManager-Persistence-Interface.

    Returns:
        True, wenn Daten von win_statistics uebernommen wurden.
    """
    sm = state_manager or StateManager()
    geom = sm.get_window_geometry("win_statistics")
    if geom is None:
        return False
    migrated = False

    # 1. Geometrie kopieren (nur wenn win_analytics noch keinen Eintrag hat)
    if sm.get_window_geometry("win_analytics") is None:
        sm.save_window_geometry(
            "win_analytics",
            geom.get("pos_x"),
            geom.get("pos_y"),
            geom.get("width"),
            geom.get("height"),
            bool(geom.get("is_maximized")),
        )
        migrated = True

    # 2. Instanz-Zustand kopieren (symbol/timeframe)
    all_inst = sm.load_all_instances()
    stats_inst = next(
        (i for i in all_inst if i.get("instance_id") == "win_statistics"), None
    )
    if stats_inst and stats_inst.get("symbol"):
        ana_inst = next(
            (i for i in all_inst if i.get("instance_id") == "win_analytics"),
            None,
        )
        if not (ana_inst and ana_inst.get("symbol")):
            sm.save_instance_state(
                "win_analytics",
                stats_inst["symbol"],
                stats_inst.get("timeframe") or "H1",
            )
            migrated = True

    # 3. Alt-Eintraege entfernen (statistic_win ist ersetzt)
    try:
        sm.delete_instance("win_statistics")
    except Exception:
        pass
    return migrated


def _params_signature(params: Dict[str, Any]) -> tuple:
    """Deterministische, hashbare Signatur der VM-Params (Runde 11, A6).

    Wird fuer die Query-Key-Pruefung in _on_page_changed genutzt: identische
    Seite + gleiche Restore-Generation + gleiche Params -> kein redundanter
    Re-Query (die Daten sind bereits frisch). Dicts/Listen werden rekursiv
    in sortierte Tupel normalisiert (deterministisch, hashbar).
    """

    def _norm(v: Any) -> Any:
        if isinstance(v, dict):
            return tuple(sorted((str(k), _norm(val))
                                for k, val in v.items()))
        if isinstance(v, (list, tuple)):
            return tuple(_norm(x) for x in v)
        return v

    return tuple(sorted((str(k), _norm(v))
                        for k, v in params.items()))


@register_persistent_window()
class AnalyticsWindow(PersistentWindow):
    """Analytics-Hauptfenster (win_analytics, 1280 x 800, nicht-modal)."""

    INSTANCE_ID = "win_analytics"
    # Bugfix 04.08.2026 (Fenster-Historie): auto_restore=True – das Fenster
    # wird beim App-Start wiederhergestellt, wenn es beim Beenden der App
    # OFFEN war.
    # 11.08.2026 (Bugfix Runde 17e, User-Meldung 2): _keep_history_on_close
    # jetzt False – ein MANUELL geschlossenes Analytics-Fenster wird aus
    # der Fenster-Historie entfernt (delete_instance) und beim naechsten
    # App-Start NICHT wiederhergestellt (Historie intakt, konsistent mit
    # ServiceWindow). Der Analytics-Workspace (vm.params + Layout)
    # ueberlebt das manuelle Schliessen ueber ein global_settings-Backup
    # ("analytics_workspace") und wird beim naechsten manuellen Oeffnen
    # wiederhergestellt (siehe _save_workspace/_restore_workspace); die
    # Fenster-Position ueberlebt ueber DIALOG_GEOMETRY_KEY (Muster
    # ServiceWindow).
    _keep_history_on_close = False
    #: Geometrie-Key fuer die POSITION, die ein manuelles Schliessen
    #: ueberlebt (global_settings, vgl. ServiceWindow-Muster).
    DIALOG_GEOMETRY_KEY = "win_analytics"

    def __init__(
        self,
        parent=None,
        view_model: Optional[AnalyticsViewModel] = None,
        analytics_repo: Any = None,
        profile_repo: Any = None,
        selector_model: Optional[ServiceSelectorModel] = None,
    ) -> None:
        super().__init__(parent)
        # 20.01 (E5): Das ServiceSelectorModel wird VOR dem ViewModel erzeugt
        # und injiziert – der VM nutzt es fuer den Fault-Tolerant-Resolver
        # (resolve_valid_feature_ids) beim Profil-/Workspace-Restore.
        self._selector_model: ServiceSelectorModel = (
            selector_model or ServiceSelectorModel(parent=self))
        self._vm = view_model or AnalyticsViewModel(
            analytics_repo=analytics_repo,
            profile_repo=profile_repo,
            selector_model=self._selector_model,
            parent=self,
        )
        self._symbol_repo: SymbolRepository = get_symbol_repository()
        self._profile_combo_syncing: bool = False
        # 06.08.2026 (Punkt 5): Default-Limit = 'Statistik-Signale' aus den
        # App-Optionen (AppSettings.statistics_signal_limit). Das Limit-Feld
        # ist seitdem ein reines Textfeld (keine Up/Down-Pfeile).
        try:
            _app_settings = self.state_manager.get_app_settings()
            self._default_limit: int = int(
                getattr(_app_settings, "statistics_signal_limit", 10_000))
            # 19.04 (Paging): Zeilen pro Seite aus den App-Optionen
            # (statistics_page_size, Default 100) – wird an die TablePage
            # injiziert (set_page_size), die die geladenen Rows seitenweise
            # rendert (Muster statistic_win.py).
            self._table_page_size: int = int(
                getattr(_app_settings, "statistics_page_size", 100))
        except Exception:
            self._default_limit = 10_000
            self._table_page_size = 100

        # 15.03-E: Datenquellen-Dialog (ServiceSelectorDialog, Multi-Select)
        # ersetzt das fruehere Service-Filter-Popover. Das
        # ServiceSelectorModel ist injizierbar (Headless-Tests); der Dialog
        # wird lazy erzeugt (nicht-modal) und beim Schliessen zerstört.
        self._service_dialog: Optional[ServiceSelectorDialog] = None
        #: Anzeigenamen des aktiven Datenquellen-Filters (fuer den Button).
        #: Beim Profilwechsel zurueckgesetzt – Namen werden dann aus den
        #: persistierten feature_ids ueber das Model re-resolved.
        self._active_display_names: List[str] = []

        self.setWindowTitle(WINDOW_TITLE_BASE)
        self.resize(1280, 800)

        # E-2: win_statistics-Persistenz migrieren – VOR restore_state(),
        # damit die wiederhergestellte Geometrie die migrierten Werte nutzt.
        try:
            migrate_statistics_persistence(self.state_manager)
        except Exception as e:
            print(f"WARN [AnalyticsWindow] E-2-Migration fehlgeschlagen: {e}")

        self._build_ui()
        self._wire_view_model()
        self._wire_controls()

        # State asynchron wiederherstellen (nach show(), damit move/resize
        # vom Window-Manager akzeptiert werden – Muster StatisticWindow).
        QTimer.singleShot(0, self.restore_state)
        # Initiale Daten + Profile laden.
        QTimer.singleShot(100, self._initial_load)

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- Top-Bar: Profil-CRUD (Option B – Explicit Save) ---
        # 21.01 (E5, 11.08.2026): combo_profile dehnbar (Expanding,
        # min. 560 px - User-Meldung 1, editierbar); Namens-/Beschreibungs-
        # Felder wandern in den separaten Speicher-Dialog (_on_profile_save)
        # bzw. breiten Neu-Dialog (_on_profile_new). label_dirty + Buttons
        # streng rechtsbuendig (addStretch davor).
        top = QHBoxLayout()
        self.combo_profile = QComboBox()
        self.combo_profile.setMinimumWidth(560)
        self.combo_profile.setEditable(True)
        self.combo_profile.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_profile_new = QPushButton("➕ Neu")
        self.btn_profile_save = QPushButton("💾 Speichern")
        self.btn_profile_delete = QPushButton("🗑️ Löschen")
        self.label_dirty = QLabel("")
        self.label_dirty.setStyleSheet("color: #e65100; font-weight: bold;")
        self.progress_busy = QProgressBar()
        self.progress_busy.setRange(0, 0)  # indeterminierter Spinner
        self.progress_busy.setFixedWidth(120)
        self.progress_busy.setVisible(False)

        top.addWidget(QLabel("Profil:"))
        top.addWidget(self.combo_profile, 1)
        top.addStretch(1)
        top.addWidget(self.label_dirty)
        top.addWidget(self.btn_profile_new)
        top.addWidget(self.btn_profile_save)
        top.addWidget(self.btn_profile_delete)
        top.addWidget(self.progress_busy)
        root.addLayout(top)

        # --- Filter-Zeile: Symbol / TF / Datenquellen (Multi-Select) / Limit ---
        # 15.03-E: Der Datenquellen-Button oeffnet den ServiceSelectorDialog
        # (Multi-Select, Checkbox-MasterTree) – ersetzt das alte
        # combo_feature-Dropdown UND das Service-Filter-Popover
        # (Entscheidung 06.08.2026).
        filt = QHBoxLayout()
        self.combo_symbol = QComboBox()
        self.btn_symbol_fav = QPushButton("★")
        self.btn_symbol_fav.setFixedWidth(32)
        self.btn_symbol_fav.setToolTip(
            "Favoriten verwalten – öffnet das Symbol-Fenster.")
        self.combo_tf = QComboBox()
        for tf in TIMEFRAMES:
            self.combo_tf.addItem(tf, tf)
        self.btn_data_sources = QPushButton(
            "[ 🛠️ Datenquellen: Keiner ausgewählt ▾ ]")
        self.btn_data_sources.setToolTip(
            "Datenquellen wählen – öffnet den Multi-Select-Dialog "
            "(Sets/Services/Plugins).")
        # 06.08.2026 (Punkt 5): Limit als reines TEXTFELD (keine Up/Down-
        # Pfeile). Default = 'Statistik-Signale' aus den App-Optionen
        # (statistics_signal_limit, siehe __init__).
        self.edit_limit = QLineEdit()
        self.edit_limit.setText(str(self._default_limit))
        self.edit_limit.setPlaceholderText("Signale")
        self.edit_limit.setMaximumWidth(120)
        self.edit_limit.setToolTip(
            "Maximale Signale für die Detail-Tabelle – Default aus den "
            "App-Optionen ('Statistik-Signale'). Nur Zahleneingabe.")

        filt.addWidget(QLabel("Symbol:"))
        filt.addWidget(self.combo_symbol)
        filt.addWidget(self.btn_symbol_fav)
        filt.addWidget(QLabel("Timeframe:"))
        filt.addWidget(self.combo_tf)
        filt.addWidget(QLabel("Datenquellen:"))
        filt.addWidget(self.btn_data_sources)
        filt.addWidget(QLabel("Limit:"))
        filt.addWidget(self.edit_limit)
        # 19.01 (Step 1): Status-Message direkt hinter dem Limit-Feld –
        # zeigt den Ergebnistext der Tabellen-Abfrage (total == 0 ->
        # "⚠️ Keine Daten vorhanden", sonst "✅ n Einträge"; E1). Dezent
        # orange, damit der Hinweis auffaellt, aber nicht stoert.
        self.label_status_msg = QLabel("")
        self.label_status_msg.setStyleSheet(
            "color: #b7950b; font-weight: bold;")
        filt.addWidget(self.label_status_msg)
        # 20.01 (Graceful Degradation): Warn-Hinweis bei nicht mehr
        # verfügbaren Services (fehlende plugin_ids im Profil/Workspace).
        self.label_missing_warning = QLabel("")
        self.label_missing_warning.setStyleSheet(
            "color: #c62828; font-weight: bold;")
        self.label_missing_warning.setVisible(False)
        filt.addWidget(self.label_missing_warning)
        filt.addStretch(1)
        root.addLayout(filt)

        # --- Body: Sidebar + Seiten (QStackedWidget) ---
        body = QHBoxLayout()
        # 10.08.2026 (Bugfix, UI-Splitter): Sidebar (links) und Seiten-Stack
        # (rechts) liegen in einem QSplitter - der Slider ist mit der Maus
        # frei verschiebbar (statt starrer 150px-Fixbreite + Stretch).
        self.sidebar = QListWidget()
        self.sidebar.setMinimumWidth(120)
        self.pages_stack = QStackedWidget()
        self.table_page = TablePage()
        self.heatmap_page = HeatmapPage()
        self.scatter_page = ScatterPage()
        self.distribution_page = DistributionPage()
        self.equity_page = EquityPage()
        for page in (self.table_page, self.heatmap_page, self.scatter_page,
                     self.distribution_page, self.equity_page):
            self.pages_stack.addWidget(page)
        for label in ("Tabelle", "Heatmap", "Scatter", "Verteilung", "Equity"):
            self.sidebar.addItem(QListWidgetItem(label))
        self.sidebar.setCurrentRow(0)

        self._body_splitter = QSplitter(Qt.Horizontal)
        self._body_splitter.addWidget(self.sidebar)
        self._body_splitter.addWidget(self.pages_stack)
        self._body_splitter.setStretchFactor(0, 0)
        self._body_splitter.setStretchFactor(1, 1)
        self._body_splitter.setCollapsible(0, False)
        self._body_splitter.setCollapsible(1, False)
        self._body_splitter.setSizes([150, 1200])
        body.addWidget(self._body_splitter, 1)
        root.addLayout(body, 1)

        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    # Datenquellen-Dialog (15.03-E / 18.01.01 E-4: ServiceSelectorDialog,
    # frei beweglicher Service-Picker waehrend der Analytics-Session)
    # ------------------------------------------------------------------
    @Slot()
    def _open_service_dialog(self) -> None:
        """Oeffnet den Service-Picker (nicht-modal, Singleton-Lazy).

        18.01.01 (E-4): Der Dialog ist KEIN Wegwerf-Popover mehr – er bleibt
        als Singleton erhalten (kein WA_DeleteOnClose) und kann waehrend der
        Analytics-Session frei beweglich platziert werden (Position wird
        ueber global_settings persistiert). Klick auf eine Baum-Zeile im
        Picker filtert LIVE (`selection_ids_requested` -> set_feature_ids),
        Services/Sets lassen sich dort direkt verwalten.
        """
        if self._service_dialog is None:
            self._service_dialog = ServiceSelectorDialog(
                model=self._selector_model, parent=self)
            self._service_dialog.services_selected.connect(
                self._on_services_selected)
            # 18.01.01 (E-4): Live-Filter bei Klick auf eine Baum-Zeile.
            self._service_dialog.selection_ids_requested.connect(
                self._on_picker_ids_selected)
            # Runde 10 (Bug 1): Varianten-Hashes -> VM (zusaetzlich zu
            # feature_ids; der Slot liest die aktuellen ids aus dem VM).
            self._service_dialog.selection_hashes_requested.connect(
                self._on_picker_hashes_selected)
            self._service_dialog.destroyed.connect(
                self._on_service_dialog_destroyed)
        # Runde 9 (Bug 1): Modell explizit refreshen, damit der Baum
        # sicher aufgebaut ist - das initiale data_changed des Modells
        # lief VOR der Dialog-Erstellung (Dialog ist lazy), ein leerer
        # Baum wuerde die restaurierten Haken sonst verlieren. Der
        # MasterTree faengt ein zwischenzeitlich leeres Set ueber
        # _pending_feature_ids ab (set_checked_feature_ids merkt sie).
        try:
            self._selector_model.refresh()
        except Exception as e:
            print(f"WARN [AnalyticsWindow] Picker-Modell-Refresh: {e}")
        self._service_dialog.apply_feature_ids(
            self._vm.params.get("feature_ids") or [],
            self._vm.params.get("instance_hashes") or [])
        self._service_dialog.show()
        self._service_dialog.raise_()
        self._service_dialog.activateWindow()

    @Slot()
    def _on_service_dialog_destroyed(self) -> None:
        """Setzt die Dialog-Referenz zurueck (zerstoert mit dem Parent)."""
        self._service_dialog = None

    @Slot(list)
    def _on_picker_hashes_selected(self, instance_hashes: List[str]) -> None:
        """Runde 10 (Bug 1): Varianten-Hashes aus dem Picker uebernehmen.

        feature_ids (plugin_ids) bleiben unveraendert - nur die
        Varianten-Einschraenkung wird aktualisiert. Dadurch ist ein
        Check/Uncheck EINER Variante im Datenfilter sichtbar.
        """
        self._vm.set_feature_ids(
            self._vm.params.get("feature_ids") or [],
            list(instance_hashes or []))
        self._sync_service_filter_button()
        self.label_missing_warning.setVisible(False)

    @Slot(list)
    def _on_picker_ids_selected(self, feature_ids: List[str]) -> None:
        """Live-Filter aus dem Picker (Klick auf Set/Ordner/Plugin).

        18.01.01 (E-4): Die aufgeloesten feature_ids (plugin_ids) werden
        sofort an `AnalyticsViewModel.set_feature_ids()` gereicht – die
        Charts filtern ohne 'Anwenden'. Der Button-Text wird synchronisiert
        (Anzeigenamen ueber das Modell re-resolved).
        """
        self._active_display_names = []
        self._vm.set_feature_ids(list(feature_ids or []))
        self._sync_service_filter_button()
        # 20.01: Manuelle Datenquellen-Aenderung -> Warn-Label zuruecksetzen.
        self.label_missing_warning.setVisible(False)

    @Slot(list, list)
    def _on_services_selected(
        self, display_names: List[str], feature_ids: List[str]
    ) -> None:
        """Uebernimmt die Multi-Auswahl aus dem Dialog (Signal-Vertrag).

        `display_names` werden fuer den Button-Text gemerkt; `feature_ids`
        (plugin_ids) gehen an `AnalyticsViewModel.set_feature_ids()` – das
        ViewModel filtert die Charts per `WHERE feature_id IN (...)`.
        """
        self._active_display_names = list(display_names or [])
        self._vm.set_feature_ids(list(feature_ids or []))
        self._sync_service_filter_button()
        # 20.01: Manuelle Datenquellen-Aenderung -> Warn-Label zuruecksetzen.
        self.label_missing_warning.setVisible(False)

    def _sync_service_filter_button(self) -> None:
        """Synchronisiert den Datenquellen-Button mit dem VM-Parameter.

        Wird beim Setzen/Entfernen des Filters, bei Profilwechseln
        (active_profile_changed) und ueber `event_bus.profile_changed`
        aufgerufen. Nach einem Profilwechsel liegen nur die persistierten
        feature_ids (plugin_ids) vor – die Anzeigenamen werden dann ueber
        `ServiceSelectorModel.resolve_display_names()` re-resolved.
        """
        ids = self._vm.params.get("feature_ids") or []
        if not ids:
            self.btn_data_sources.setText(
                "[ 🛠️ Datenquellen: Keiner ausgewählt ▾ ]")
            return
        names = (self._active_display_names
                 or self._selector_model.resolve_display_names(ids))
        self.btn_data_sources.setText(
            f"[ 🛠️ Datenquellen: {', '.join(names)} ▾ ]")

    @Slot()
    def _sync_ui_from_restored_params(self) -> None:
        """Synchronisiert die Fenster-UI nach `params_restored`.

        10.08.2026 (Bugfix, Punkt 3): `params_restored` feuert nach einem
        Workspace-Restore UND nach einem Profilwechsel (_apply_profile).
        Hier wird die Fenster-Ebene nachgezogen: Sidebar-Seite (sofern der
        Workspace eine page_index hat), die aktuelle Page (falls sie eine
        _sync_from_params-Methode anbietet) und die Filterleiste
        (Symbol/Timeframe/Datenquellen-Button). Die Unterseiten syncen ihre
        Combos ueber eigene params_restored-Verbindungen.
        """
        try:
            page_index = int((self._vm.workspace_layout or {}).get(
                "page_index", -1))
            if 0 <= page_index < self.pages_stack.count():
                if self.sidebar.currentRow() != page_index:
                    self.sidebar.blockSignals(True)
                    self.sidebar.setCurrentRow(page_index)
                    self.sidebar.blockSignals(False)
                # 10.08.2026 (Punkt 4): Seiten-Stack EXPLIZIT umschalten
                # (blockSignals unterdrueckt currentRowChanged -> _on_page_
                # changed feuert nicht; ohne setCurrentIndex bleibt die
                # alte Seite sichtbar).
                self.pages_stack.setCurrentIndex(page_index)
        except (RuntimeError, AttributeError):
            pass
        # Runde 11 (Architektur, A3/A6): Zentraler Seiten-Sync NACH dem
        # VM-Param-Setzen (genau EIN Durchgang; die Einzel-Verbindungen der
        # Widgets auf params_restored entfallen). Danach die Daten der
        # aktiven Seite anfordern (A6: Query-Key-Pruefung -> request_data).
        self._sync_all_pages_from_params()
        self._request_current_page_data()
        # 10.08.2026 (Punkt 3): Ansichts-Modus der Heatmap-Seite auch aus
        # dem Profil-Restore uebernehmen (workspace_layout wird von
        # _apply_profile befuellt). Muster _restore_workspace.
        try:
            heatmap_mode = (self._vm.workspace_layout or {}).get(
                "heatmap_mode")
            if heatmap_mode:
                self.heatmap_page.set_mode(str(heatmap_mode))
        except Exception as e:
            print(f"WARN [AnalyticsWindow] Heatmap-Modus-Restore: {e}")
        # 10.08.2026 (Bugfix Runde 7, Bug 2): ServicePicker nach einem
        # Profilwechsel wieder oeffnen, falls das Layout es verlangt.
        try:
            if (self._vm.workspace_layout or {}).get("service_picker_open"):
                self._open_service_dialog()
        except Exception as e:
            print(f"WARN [AnalyticsWindow] ServicePicker-Restore: {e}")
        self._sync_profile_filters()
        self._sync_service_filter_button()

    # ------------------------------------------------------------------
    # MVVM + Steuerung verdrahten
    # ------------------------------------------------------------------
    def _wire_view_model(self) -> None:
        vm = self._vm
        for page in (self.table_page, self.heatmap_page, self.scatter_page,
                     self.distribution_page, self.equity_page):
            page.attach_view_model(vm)
        vm.profiles_available.connect(self._on_profiles_available)
        vm.active_profile_changed.connect(self._on_active_profile_changed)
        vm.dirty_changed.connect(self._on_dirty_changed)
        # 10.08.2026 (Bugfix, Punkt 3): Der ViewModel emittiert
        # params_restored nach restore_workspace() UND _apply_profile()
        # (20.04-Timing-Fix) - die Fenster-Ebene wird synchronisiert
        # (Sidebar-Seite + aktuelle Page + Filterleiste). Die Unterseiten
        # (Heatmap-Widget) syncen ihre Combos ueber eigene Verbindungen.
        if hasattr(vm, "params_restored"):
            vm.params_restored.connect(self._sync_ui_from_restored_params)
        vm.busy_changed.connect(self._on_busy_changed)
        vm.query_failed.connect(self._on_query_failed)
        # 20.01 (Graceful Degradation): fehlende Services -> Warn-Label.
        vm.missing_services_detected.connect(self._on_missing_services)
        # 19.01 (Step 1): Status-Text bei Tabellen-Abfragen (total == 0 ->
        # "Keine Daten vorhanden", E1). Nur QUERY_TABLE wird ausgewertet.
        vm.data_ready.connect(self._on_data_ready)
        # 19.01 (E3): Service-Namensaufloesung fuer die TablePage (IoC) –
        # kein SQL / keine direkte Modell-Kopplung in der Page.
        self.table_page.set_name_resolver(
            self._selector_model.resolve_display_names)
        # 19.03 (Step 1): Tabellen-Settings (Spaltenbreiten, Zeilenhoehe,
        # Sortierung) der TablePage in den ViewModel leiten (Persistenz,
        # Option B – Explicit Save; E6: kein Query-Refresh).
        self.table_page.table_settings_changed.connect(
            self._on_table_settings_changed)

        # 19.04 (Paging): Zeilen pro Seite aus den AppSettings injizieren
        # (statistics_page_size). Die TablePage rendert nur Seiten der
        # Groesse page_size; die geladenen _current_rows (bis zum Limit)
        # bleiben vollstaendig erhalten (Jump-to-Chart/Seitenwechsel).
        self.table_page.set_page_size(self._table_page_size)

        # Jump-to-Chart (Variante 2): open_chart_at_bar + Aufloesung
        self.table_page.set_navigation_handler(self._open_chart_at_bar)
        self.heatmap_page.set_navigation_handler(self._open_chart_at_bar)
        self.heatmap_page.set_cell_resolver(
            self._vm.resolve_recent_bar_time_for_cell)
        self.scatter_page.set_navigation_handler(self._open_chart_at_bar)
        self.scatter_page.set_bar_resolver(self._vm.resolve_latest_bar_time)

    def _wire_controls(self) -> None:
        self.combo_symbol.currentTextChanged.connect(self._vm.set_symbol)
        # TF-Ausgrauung (15.03-Fix): Bei Symbolwechsel die verfuegbaren
        # Timeframes aus dem Feature-Store ermitteln und TFs ohne Daten
        # ausgrauen (nicht auswaehlbar).
        self.combo_symbol.currentTextChanged.connect(self._refresh_timeframe_combo)
        self.combo_tf.currentTextChanged.connect(self._vm.set_timeframe)
        # 15.03-E: Datenquellen-Dialog (Multi-Select, ersetzt Popover)
        self.btn_data_sources.clicked.connect(self._open_service_dialog)
        event_bus.profile_changed.connect(self._sync_service_filter_button)
        # 06.08.2026 (Punkt 5): Limit-Textfeld -> ViewModel. Der Default
        # (App-Optionen 'Statistik-Signale') wird beim Start gesetzt, damit
        # Feld und VM-Parameter konsistent sind.
        self.edit_limit.textChanged.connect(self._on_limit_text_changed)
        self._vm.set_limit(self._default_limit)
        self.btn_symbol_fav.clicked.connect(self.open_symbols_window)
        self.btn_profile_new.clicked.connect(self._on_profile_new)
        self.btn_profile_save.clicked.connect(self._on_profile_save)
        self.btn_profile_delete.clicked.connect(self._on_profile_delete)
        self.combo_profile.currentIndexChanged.connect(self._on_profile_selected)
        self.sidebar.currentRowChanged.connect(self._on_page_changed)
        event_bus.favorites_changed.connect(self._refresh_symbol_combo)
        self._refresh_symbol_combo()
        self._refresh_timeframe_combo()

    @Slot(str)
    def _on_limit_text_changed(self, text: str) -> None:
        """Uebernimmt die Limit-Texteingabe (Punkt 5, reines Textfeld).

        Nur ganzzahlige Werte werden an das ViewModel gereicht (das clamt
        auf 1..MAX_LOOKBACK_LIMIT); leere oder ungueltige Eingaben lassen den
        letzten gueltigen Wert unveraendert.
        """
        text = (text or "").strip()
        if not text:
            return
        try:
            val = int(text)
        except ValueError:
            return
        self._vm.set_limit(val)

    def _refresh_timeframe_combo(self, symbol: Optional[str] = None) -> None:
        """Graut Timeframes ohne Feature-Store-Daten aus (nicht auswaehlbar).

        Fix 15.03 (TF-Verfuegbarkeit): TFs mit Daten bleiben aktiv; TFs ohne
        Daten werden per QComboBox-Model disabled (Qt stellt sie grau dar und
        verhindert die Auswahl). Die aktuelle Auswahl wird nur beibehalten,
        wenn ihr TF Daten hat; sonst faellt sie auf den ersten verfuegbaren TF
        zurueck. Schlaegt die Abfrage fehl, bleiben alle TFs aktiv (Fallback).
        """
        if not hasattr(self, "combo_tf") or not hasattr(self, "combo_symbol"):
            return
        symbol = (symbol or self.combo_symbol.currentText()).strip()
        available: Optional[set] = None  # None = Abfrage fehlgeschlagen
        if symbol:
            try:
                tfs = self._vm.available_timeframes(symbol)
                available = {str(t) for t in tfs}
            except Exception:
                available = None
        self.combo_tf.blockSignals(True)
        first_enabled = -1
        for i in range(self.combo_tf.count()):
            tf = self.combo_tf.itemText(i)
            enabled = (available is None) or (tf in available)
            self.combo_tf.model().item(i).setEnabled(enabled)
            if enabled and first_enabled < 0:
                first_enabled = i
        current = self.combo_tf.currentText()
        cur_idx = self.combo_tf.findText(current)
        if cur_idx >= 0 and self.combo_tf.model().item(cur_idx).isEnabled():
            pass  # aktuelle Auswahl hat Daten -> behalten
        elif first_enabled >= 0:
            self.combo_tf.setCurrentIndex(first_enabled)
        self.combo_tf.blockSignals(False)

    # ------------------------------------------------------------------
    # PersistentWindow-Interface
    # ------------------------------------------------------------------
    def get_persistent_symbol(self) -> str:
        return (self.combo_symbol.currentText()
                if hasattr(self, "combo_symbol") else "SILVER")

    def get_persistent_timeframe(self) -> str:
        return (self.combo_tf.currentText()
                if hasattr(self, "combo_tf") else "M1")

    def _apply_persistent_filters(self, symbol: str, timeframe: str) -> None:
        """Wird von PersistentWindow.restore_state() gerufen."""
        if symbol and hasattr(self, "combo_symbol"):
            idx = self.combo_symbol.findText(symbol)
            if idx < 0:
                # Nicht-Favorit aus der Historie: in die Combo aufnehmen,
                # damit der gespeicherte Filter wiederhergestellt wird
                # (Fix 15.03 – zuletzt gewaehltes Symbol bleibt gemerkt).
                self.combo_symbol.blockSignals(True)
                self.combo_symbol.addItem(symbol, symbol)
                idx = self.combo_symbol.count() - 1
                self.combo_symbol.blockSignals(False)
            self.combo_symbol.setCurrentIndex(idx)
        if timeframe and hasattr(self, "combo_tf"):
            idx = self.combo_tf.findText(timeframe)
            if idx >= 0:
                self.combo_tf.setCurrentIndex(idx)
        # VM-Parameter idempotent uebernehmen (setCurrentIndex hat die
        # Signale bereits gefeuert; der ViewModel dedupliziert gleiche Werte).
        self._vm.set_symbol(self.get_persistent_symbol())
        self._vm.set_timeframe(self.get_persistent_timeframe())
        # TF-Ausgrauung nach Restore: Fall der aktuelle TF keine Daten hat,
        # faellt die Auswahl auf den ersten verfuegbaren TF zurueck.
        self._refresh_timeframe_combo(symbol)

    # ------------------------------------------------------------------
    # Symbol- & Favoriten-Verwaltung (15.01-Muster)
    # ------------------------------------------------------------------
    @Slot()
    def open_symbols_window(self) -> None:
        """Oeffnet das nicht-modale SymbolsWindow (Singleton-Verhalten)."""
        existing = SymbolsWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = SymbolsWindow(self)  # parent=self nur fuer state_manager-Zugriff
        win.show()

    def _refresh_symbol_combo(self) -> None:
        """Befuellt die Symbol-ComboBox aus den Favoriten (Fallback Defaults).

        Die aktuell gewaehlte Auswahl bleibt erhalten – auch wenn sie kein
        Favorit (mehr) ist (analog StatisticWindow) – damit der Filter nicht
        ungewollt umspringt und ein aus der Historie restauriertes Symbol
        sichtbar bleibt (Fix 15.03).
        """
        if not hasattr(self, "combo_symbol"):
            return
        favorites = self._symbol_repo.get_favorite_symbols()
        if not favorites:
            favorites = list(SymbolRepository.DEFAULT_SYMBOLS)
        current = self.combo_symbol.currentText()
        self.combo_symbol.blockSignals(True)
        self.combo_symbol.clear()
        for sym in favorites:
            self.combo_symbol.addItem(sym, sym)
        if current and current not in favorites:
            self.combo_symbol.addItem(current, current)
        idx = self.combo_symbol.findText(current)
        self.combo_symbol.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_symbol.blockSignals(False)

    # ------------------------------------------------------------------
    # Runde 11 (Architektur, A3/A6): Zentraler Seiten-Sync + Query-
    # Orchestrierung
    # ------------------------------------------------------------------
    def _sync_all_pages_from_params(self) -> None:
        """Synchronisiert ALLE Seiten-Controls aus den VM-Params (A3).

        Runde 11 (Architektur, A3): Zentraler Sync nach restore_workspace()/
        _apply_profile() - genau EIN Durchgang mit blockSignals (page-intern
        via _syncing/_set_combo_data). Die direkte params_restored-
        Verbindung des HeatmapWidgets (attach_view_model) entfaellt - das
        Window orchestriert hier.
        """
        for page in (self.table_page, self.heatmap_page, self.scatter_page,
                     self.distribution_page, self.equity_page):
            if hasattr(page, "_sync_from_params"):
                try:
                    page._sync_from_params()
                except (RuntimeError, AttributeError):
                    pass
        # 20.02: Das generische HeatmapWidget syncen seine Combos separat
        # (es ist ein Unter-Widget der HeatmapPage, keine eigene Page).
        try:
            generic = getattr(self.heatmap_page, "_generic", None)
            if generic is not None and hasattr(generic, "_sync_from_params"):
                generic._sync_from_params()
        except (RuntimeError, AttributeError):
            pass

    def _request_current_page_data(self) -> None:
        """Fordert die Daten der aktiven Seite an (A6: sync -> key -> query)."""
        row = self.sidebar.currentRow()
        if not (0 <= row < self.pages_stack.count()):
            return
        self._on_page_changed(row)

    # ------------------------------------------------------------------
    # Datenfluss (MVVM): Feature-Dropdown, Seiten, Status
    # ------------------------------------------------------------------
    def _on_page_changed(self, row: int) -> None:
        if 0 <= row < self.pages_stack.count():
            # Bugfix 08.08.2026: Seiten-Stack NIE umgeschaltet (Alt-Bug
            # seit Phase 15.03) - es fehlte setCurrentIndex. Dadurch blieb
            # unabhaengig vom Sidebar-Klick immer die Tabelle (Index 0)
            # sichtbar. Jetzt: Stack auf die geklickte Seite + lazy request.
            self.pages_stack.setCurrentIndex(row)
            page = self.pages_stack.widget(row)
            # Runde 11 (A6): Query-Key-Pruefung - identische Seite + gleiche
            # Restore-Generation + gleiche Params -> KEIN redundanter
            # Re-Query (die Daten sind bereits frisch; z. B. doppelter
            # Aufruf aus _initial_load/_request_current_page_data).
            key = (row, self._vm.restore_generation,
                   _params_signature(self._vm.params))
            if key != getattr(self, "_last_request_key", None):
                self._last_request_key = key
                if hasattr(page, "request_data"):
                    page.request_data()

    @Slot(str, str)
    def _on_query_failed(self, kind: str, error: str) -> None:
        print(f"WARN [AnalyticsWindow] Abfrage '{kind}' fehlgeschlagen: {error}")

    @Slot(list)
    def _on_missing_services(self, missing: List[str]) -> None:
        """Zeigt an, welche gespeicherten Services nicht mehr verfügbar sind.

        20.01 (Graceful Degradation): Fehlende feature_ids (entfernte/
        umbenannte Plugins) wurden beim Profil-/Workspace-Restore isoliert
        gefiltert – die verbliebenen Quellen bleiben aktiv. Das Label wird
        bei manueller Datenquellen-Aenderung oder save_profile() versteckt.
        """
        missing = [str(m) for m in missing or [] if str(m or "").strip()]
        if not missing:
            self.label_missing_warning.setVisible(False)
            return
        self.label_missing_warning.setText(
            f"⚠️ {len(missing)} Services nicht mehr verfügbar")
        self.label_missing_warning.setVisible(True)

    @Slot(str, dict)
    def _on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        """Status-Text der Tabellen-Abfrage (19.01 Step 1).

        Zeigt den Ergebnisstatus NUR fuer QUERY_TABLE (total aus dem
        Repository = LIMIT-gekappte Zeilenzahl, E1). total == 0 ->
        "Keine Daten vorhanden" (dezent orange), sonst "n Eintraege".
        Leere Zustaende der Unterseiten (Overlay-Stacks) schalten die
        Pages bereits selbst um (E5) – dieser Text ist ergaenzend.
        """
        if kind != QUERY_TABLE:
            return
        try:
            total = int(data.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        if total == 0:
            self.label_status_msg.setText("⚠️ Keine Daten vorhanden")
        else:
            self.label_status_msg.setText(f"✅ {total} Einträge")

    @Slot(dict)
    def _on_table_settings_changed(self, settings: Dict[str, Any]) -> None:
        """Uebernimmt TablePage-Settings in den ViewModel (19.03 Step 1/2).

        Spaltenbreiten {Spaltenname: Breite} (E5), **globale Zeilenhoehe**
        (E9/19.06: ein Wert fuer die GESAMTE Tabelle – das Ziehen einer
        Zeile setzt alle Zeilen live auf diese Hoehe), Sortier-Spalte/
        -Richtung (E8). Reine UI-Zustaende der TablePage: set_table_settings
        markiert nur das Profil-Dirty-Flag (E6, Option B) und loest KEINEN
        Query-Refresh aus (kein Debounce/Worker).
        """
        so = settings.get("sort_order")
        self._vm.set_table_settings(
            widths=settings.get("column_widths") or {},
            row_height=int(settings.get("row_height") or 0),
            sort_column=int(settings.get("sort_column") or 0),
            sort_order=int(so) if so is not None else 1,
        )

    @Slot(bool)
    def _on_busy_changed(self, busy: bool) -> None:
        self.progress_busy.setVisible(busy)

    # ------------------------------------------------------------------
    # Profil-CRUD (Option B – Explicit Save)
    # ------------------------------------------------------------------
    @Slot(list)
    def _on_profiles_available(self, profiles: List[Dict[str, Any]]) -> None:
        active_pid = next(
            (p.get("profile_id") for p in profiles if p.get("is_active")),
            None,
        )
        self._profile_combo_syncing = True
        self.combo_profile.blockSignals(True)
        self.combo_profile.clear()
        if not profiles:
            self.combo_profile.addItem("– kein Profil –", None)
        for p in profiles:
            self.combo_profile.addItem(
                p.get("name") or "?", p.get("profile_id"))
        target = active_pid or (self._vm.active_profile or {}).get("profile_id")
        idx = self.combo_profile.findData(target)
        self.combo_profile.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_profile.blockSignals(False)
        self._profile_combo_syncing = False

    @Slot(int)
    def _on_profile_selected(self, _index: int) -> None:
        if self._profile_combo_syncing:
            return
        profile_id = self.combo_profile.currentData()
        if profile_id:
            self._vm.set_active_profile(profile_id)

    @Slot(object)
    def _on_active_profile_changed(
        self, profile: Optional[Dict[str, Any]]
    ) -> None:
        # 21.01 (E5): Name-/Beschreibungs-Felder leben im Speicher-Dialog
        # (kein Header-Edit mehr) – hier nur noch die Combo + Filter-Sync.
        if profile is None:
            self._active_display_names = []
            self._sync_service_filter_button()
            return
        pid = profile.get("profile_id")
        idx = self.combo_profile.findData(pid)
        if idx >= 0 and self.combo_profile.currentIndex() != idx:
            self.combo_profile.blockSignals(True)
            self.combo_profile.setCurrentIndex(idx)
            self.combo_profile.blockSignals(False)
        # 15.03-E: Profilwechsel uebernimmt feature_ids in den VM – die
        # Anzeigenamen werden neu aus den persistierten IDs aufgeloest
        # (resolve_display_names) und der Button-Text synchronisiert.
        self._active_display_names = []
        self._sync_service_filter_button()
        # 06.08.2026 (Punkt 5): Limit-Feld mit dem (ggf. aus dem Profil
        # geladenen) VM-Wert synchronisieren.
        if hasattr(self, "edit_limit"):
            self.edit_limit.setText(
                str(int(self._vm.params.get("limit") or self._default_limit)))
        # Bugfix 08.08.2026 (symbol/tf-Profil-Restore): Der Profilwechsel
        # hat die VM-Parameter symbol/timeframe via _apply_profile() gesetzt –
        # die Combos muessen diesen Werten folgen (sonst zeigen sie weiter
        # die Historie-Werte und beim Schliessen wird der falsche Zustand
        # persistiert).
        self._sync_profile_filters()

    def _sync_profile_filters(self) -> None:
        """Synchronisiert Symbol-/TF-Combos mit den VM-Parametern (Bugfix).

        Beim Profilwechsel (active_profile_changed) bzw. nach load_profiles()
        wurden die VM-Parameter `symbol`/`timeframe` aus dem Profil-Payload
        uebernommen (ViewModel._apply_profile). Die Combos wuerden aber auf
        den alten (Historie-)Werten bleiben – das ergibt inkonsistente
        Abfragen und eine falsche Persistenz beim Schliessen
        (get_persistent_symbol liefert den Combo-Wert). Der Sync laeuft mit
        blockSignals(True), damit keine set_symbol/set_timeframe-Signalkette
        (und kein zusaetzlicher Query) ausgeloest wird – der Profilwechsel
        hat die Abfragen bereits via refresh_all() angestossen. Ein Symbol
        ausserhalb der Favoriten wird in die Combo aufgenommen (Muster
        _apply_persistent_filters), damit der gespeicherte Filter sichtbar
        bleibt.
        """
        if not hasattr(self, "combo_symbol") or not hasattr(self, "combo_tf"):
            return
        symbol = (self._vm.params.get("symbol") or "").strip()
        if not symbol:
            return
        self.combo_symbol.blockSignals(True)
        if self.combo_symbol.findText(symbol) < 0:
            self.combo_symbol.addItem(symbol, symbol)
        self.combo_symbol.setCurrentIndex(self.combo_symbol.findText(symbol))
        self.combo_symbol.blockSignals(False)
        timeframe = (self._vm.params.get("timeframe") or "M1").strip()
        self.combo_tf.blockSignals(True)
        idx = self.combo_tf.findText(timeframe)
        if idx >= 0:
            self.combo_tf.setCurrentIndex(idx)
        self.combo_tf.blockSignals(False)
        # TF-Ausgrauung fuer das (ggf. neue) Symbol aktualisieren.
        self._refresh_timeframe_combo(symbol)

    def _sync_profile_editor(self) -> None:
        """Synchronisiert das Limit-Feld mit dem VM (Bugfix).

        Wird beim App-Start nach `load_profiles()` gerufen: Dort emittiert der
        ViewModel KEIN `active_profile_changed` (nur set_active_profile/
        create_profile) – das Limit-Feld bliebe sonst auf dem Default, obwohl
        das aktive Profil einen abweichenden Wert haben kann.
        21.01 (E5): Die Namens-/Beschreibungs-Felder existieren nicht mehr im
        Header – Name/Beschreibung werden ausschliesslich im Speicher-Dialog
        editiert (dort mit den aktuellen Profilwerten vorbelegt).
        """
        if hasattr(self, "edit_limit"):
            self.edit_limit.setText(
                str(int(self._vm.params.get("limit")
                        or self._default_limit)))

    @staticmethod
    def _resolve_save_name(name: str, current_name: str) -> str:
        """Leerer Name beim Speichern -> aktueller Profilname (E5).

        21.01 (E5): Die Header-Namensfelder sind entfernt; der Speicher-
        Dialog wird mit dem aktuellen Profilnamen vorbelegt. Laesst der
        Anwender das Feld leer (bzw. nur Whitespace), bleibt der
        bestehende Profilname erhalten – kein '?'-Verlust in der Combo
        (Bugfix 19.05/19.06-Semantik, jetzt im Dialog statt Header-Feld).
        """
        return (str(name or "").strip()
                or str(current_name or "").strip() or "")

    @Slot(bool)
    def _on_dirty_changed(self, dirty: bool) -> None:
        self.label_dirty.setText(
            "● ungespeicherte Änderungen" if dirty else "")
        self.setWindowTitle(
            WINDOW_TITLE_BASE + (" *" if dirty else ""))

    def _current_ui_layout(self) -> Dict[str, Any]:
        """Aktuelles UI-Layout (Seite + Heatmap-Modus) fuer die
        Profil-Persistenz (10.08.2026, Punkte 3/4)."""
        return {
            "page_index": self.sidebar.currentRow()
            if hasattr(self, "sidebar") else 0,
            "heatmap_mode": self.heatmap_page.mode_id
            if hasattr(self, "heatmap_page") else "standard",
            # 10.08.2026 (Bugfix Runde 7, Bug 2): Picker-Offen-Zustand auch
            # im Profil-Payload persistieren (Muster _save_workspace).
            "service_picker_open": bool(
                self._service_dialog is not None
                and self._service_dialog.isVisible()),
        }

    @Slot()
    def _on_profile_new(self) -> None:
        # 21.01 (E3 + User-Meldung 1, 11.08.2026): Der Neu-Dialog ist ein
        # BREITER QDialog (Fenster min. 560 px, Namensfeld min. 420 px) mit
        # Name + Beschreibung in EINEM Formular (vorher zwei schmale
        # QInputDialog-Instanzen hintereinander). Der Auto-Namensgenerator
        # fuellt das Namensfeld vor (deutsch, Fallbacks; kein leeres Feld).
        suggested = ""
        try:
            suggested = self._vm.generate_profile_name_suggestion() or ""
        except Exception:
            suggested = ""
        dialog = QDialog(self)
        dialog.setWindowTitle("Neues Profil")
        dialog.setMinimumWidth(560)
        form = QFormLayout(dialog)
        edit_name = QLineEdit(suggested)
        edit_name.setMinimumWidth(420)
        edit_name.setPlaceholderText("Profil-Name")
        edit_desc = QLineEdit()
        edit_desc.setPlaceholderText("Beschreibung (optional)")
        form.addRow("Name:", edit_name)
        form.addRow("Beschreibung:", edit_desc)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Anlegen")
        form.addRow(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.Accepted:
            return
        name = (edit_name.text() or "").strip()
        if not name:
            return
        desc = (edit_desc.text() or "").strip()
        # 10.08.2026 (Punkte 3/4): UI-Layout (Seite + Heatmap-Modus) im
        # neuen Profil persistieren (create_profile ruft _current_payload).
        self._vm.set_ui_layout(self._current_ui_layout())
        try:
            self._vm.create_profile(name, desc)
        except ValueError as e:
            QMessageBox.warning(self, "Profil anlegen", str(e))

    @Slot()
    def _on_profile_save(self) -> None:
        """Explicit Save: Name/Beschreibung + aktuelle Parameter persistieren.

        21.01 (E5): Name und Beschreibung werden im SEPARATEN Speicher-Dialog
        mit den aktuellen Profilwerten vorbelegt (die Header-Edit-Felder sind
        entfernt). Ohne Namensaenderung bleibt der bestehende Name erhalten
        (kein '?'-Verlust).
        """
        if self._vm.active_profile is None:
            return
        # 20.01: save_profile() bestaetigt die aktuelle Datenquellen-Wahl ->
        # Warn-Label (fehlende Services) zuruecksetzen.
        self.label_missing_warning.setVisible(False)
        pid = self._vm.active_profile["profile_id"]
        current_name = (self._vm.active_profile.get("name") or "").strip()
        current_desc = (self._vm.active_profile.get("description")
                        or "").strip()
        dialog = QDialog(self)
        dialog.setWindowTitle("Profil speichern")
        form = QFormLayout(dialog)
        edit_name = QLineEdit(current_name)
        edit_desc = QLineEdit(current_desc)
        edit_desc.setPlaceholderText("Beschreibung (optional)")
        form.addRow("Name:", edit_name)
        form.addRow("Beschreibung:", edit_desc)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Speichern")
        form.addRow(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.Accepted:
            return
        name = self._resolve_save_name(edit_name.text(), current_name)
        desc = (edit_desc.text() or "").strip()
        self._vm.update_profile(pid, name=name, description=desc)
        # 10.08.2026 (Punkte 3/4): UI-Layout (Seite + Heatmap-Modus) in das
        # Profil persistieren (save_profile ruft _current_payload).
        self._vm.set_ui_layout(self._current_ui_layout())
        self._vm.save_profile()

    @Slot()
    def _on_profile_delete(self) -> None:
        if self._vm.active_profile is None:
            return
        name = self._vm.active_profile.get("name") or "?"
        reply = QMessageBox.question(
            self, "Profil löschen",
            f"Profil '{name}' wirklich löschen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._vm.delete_profile(self._vm.active_profile["profile_id"])

    # ------------------------------------------------------------------
    # Jump-to-Chart (Variante 2): open_chart_at_bar
    # ------------------------------------------------------------------
    def _open_chart_at_bar(
        self, symbol: str, timeframe: str, bar_time: int
    ) -> None:
        """Oeffnet/fokussiert ein Chart-Fenster an der Bar-Position."""
        main_window = self._find_main_window()
        if main_window is not None and hasattr(main_window, "open_chart_at_bar"):
            main_window.open_chart_at_bar(symbol, timeframe, bar_time)
        elif main_window is not None and hasattr(main_window, "open_chart_window"):
            main_window.open_chart_window()

    def _find_main_window(self):
        app = QApplication.instance()
        if not app:
            return None
        for widget in app.topLevelWidgets():
            if widget.metaObject().className() == "MainWindow":
                return widget
        return None

    # ------------------------------------------------------------------
    # Initiale Ladung + Lebenszyklus
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Workspace-Persistenz (20.01, E1/E7): vm.params + UI-Layout
    # ------------------------------------------------------------------
    @staticmethod
    def _snapshot_params(params: Dict[str, Any]) -> Dict[str, Any]:
        """Flache, entkoppelte Kopie der VM-Params (kein Aliasing, B3-3).

        Runde 11 (Bug 3, B3-3): Die Workspace-Persistenz darf die
        ViewModel-Referenz nicht weiterreichen - Listen/Dicts
        (feature_ids, instance_hashes, Zoom-Bereiche, table_column_widths)
        werden als Kopien uebernommen (mutierende Aufrufer aendern sonst
        die Live-Params des ViewModel).
        """
        out: Dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, list):
                out[k] = list(v)
            elif isinstance(v, dict):
                out[k] = dict(v)
            else:
                out[k] = v
        return out

    def _save_workspace(self) -> None:
        """Persistiert den Analytics-Workspace (VM-Parameter + Layout).

        20.01: Payload = {"params": vm.params, "layout": {"page_index": ...}}.
        Wird im closeEvent VOR super().closeEvent() ausgefuehrt. Seit Runde
        17e (_keep_history_on_close=False) wird die instance_states-Zeile
        beim manuellen Schliessen zwar geloescht - das Workspace-Backup in
        global_settings ("analytics_workspace") ueberlebt und wird beim
        naechsten manuellen Oeffnen wiederhergestellt.
        """
        try:
            # Runde 11 (Bug 3, B3-3): Entkoppelte Kopie statt Referenz -
            # der ViewModel._params wuerde sonst mit dem Workspace-Payload
            # aliasen (mutierende Aufrufer aendern die Live-Params).
            params_snapshot = self._snapshot_params(self._vm.params)
            payload = {
                "params": params_snapshot,
                "layout": {
                    "page_index": self.sidebar.currentRow()
                    if hasattr(self, "sidebar") else 0,
                    # 20.02 (E2): Ansichts-Modus der Heatmap-Seite
                    # (standard | generic) im Workspace mitpersistieren.
                    "heatmap_mode": self.heatmap_page.mode_id
                    if hasattr(self, "heatmap_page") else "standard",
                    # 10.08.2026 (Bugfix Runde 7, Bug 2): War der
                    # ServicePicker beim Schliessen offen? _save_workspace
                    # laeuft VOR dem close() des Dialogs im closeEvent,
                    # damit der Zustand hier noch sichtbar ist.
                    "service_picker_open": bool(
                        self._service_dialog is not None
                        and self._service_dialog.isVisible()),
                },
            }
            self.state_manager.save_workspace_state(
                self.INSTANCE_ID, payload)
            # 11.08.2026 (Bugfix Runde 17e, User-Meldung 2): Zusaetzliches
            # Backup in global_settings - es ueberlebt das MANUELLE
            # Schliessen (delete_instance loescht die instance_states-Zeile)
            # und wird beim naechsten manuellen Oeffnen wiederhergestellt
            # (Fallback in _restore_workspace).
            try:
                self.state_manager.save_global_value(
                    "analytics_workspace", payload)
            except Exception:
                pass
        except Exception as e:
            print(f"WARN [AnalyticsWindow] Workspace-Save fehlgeschlagen: {e}")

    def _restore_workspace(self) -> None:
        """Stellt den letzten Workspace wieder her (20.01, E7).

        Laeuft NACH load_profiles() (aktives Profil wird zuerst angewendet);
        der Workspace (letzter Sitzungszustand) gewinnt. Fehlende Services
        meldet der ViewModel via missing_services_detected -> Warn-Label.
        """
        try:
            payload = self.state_manager.get_workspace_state(
                self.INSTANCE_ID)
        except Exception as e:
            print(f"WARN [AnalyticsWindow] Workspace-Restore fehlgeschlagen: {e}")
            return
        # 11.08.2026 (Bugfix Runde 17e, User-Meldung 2): Nach einem MANUELLEN
        # Schliessen ist die instance_states-Zeile geloescht - Fallback auf
        # das global_settings-Backup aus _save_workspace.
        if not payload:
            try:
                payload = self.state_manager.get_global_value(
                    "analytics_workspace")
            except Exception:
                payload = None
        if not payload:
            return
        self._vm.restore_workspace(payload)
        # Combos/Button mit den restaurierten VM-Parametern synchronisieren.
        self._sync_profile_filters()
        self._sync_service_filter_button()
        page_index = int(
            (self._vm.workspace_layout or {}).get("page_index", -1))
        if 0 <= page_index < self.pages_stack.count():
            self.sidebar.setCurrentRow(page_index)
        # 20.02 (E2): Ansichts-Modus der Heatmap-Seite wiederherstellen.
        try:
            heatmap_mode = (self._vm.workspace_layout or {}).get(
                "heatmap_mode")
            if heatmap_mode:
                self.heatmap_page.set_mode(str(heatmap_mode))
        except Exception as e:
            print(f"WARN [AnalyticsWindow] Heatmap-Modus-Restore: {e}")
        # Limit-Feld mit dem VM-Wert synchronisieren (Workspace kann abweichen).
        if hasattr(self, "edit_limit"):
            self.edit_limit.setText(
                str(int(self._vm.params.get("limit")
                        or self._default_limit)))
        # 10.08.2026 (Bugfix Runde 7, Bug 2): War der ServicePicker beim
        # Schliessen offen, wird er nach dem Restore wieder geoeffnet (die
        # Position stellt der Dialog selbst aus global_settings wieder her).
        try:
            if (self._vm.workspace_layout or {}).get("service_picker_open"):
                self._open_service_dialog()
        except Exception as e:
            print(f"WARN [AnalyticsWindow] ServicePicker-Restore: {e}")

    def _initial_load(self) -> None:
        # Runde 10 (Bug 3): Deterministischer Initial-Load - die Symbol-Combo
        # wird hier nochmals gefuellt (idempotent, erhaelt die aktuelle
        # Auswahl), damit sie NICHT leer sein kann, wenn restore_state (t=0)
        # noch kein Symbol gesetzt hat. Leere Combos wurden sonst per
        # set_symbol("")/set_timeframe("") in die VM-Params uebernommen ->
        # _current_params() lieferte None -> Initial-Queries uebersprungen.
        self._refresh_symbol_combo()
        if self.combo_symbol.currentText():
            self._vm.set_symbol(self.combo_symbol.currentText())
        if self.combo_tf.currentText():
            self._vm.set_timeframe(self.combo_tf.currentText())
        self._vm.load_profiles()
        # Bugfix 08.08.2026 (symbol/tf-Profil-Restore): load_profiles()
        # emittiert active_profile_changed NICHT (nur set_active_profile/
        # create_profile) – die VM-Parameter wurden aber bereits aus dem
        # Profil-Payload gesetzt. Die Combos muessen deshalb hier explizit
        # synchronisiert werden, sonst bleiben sie auf den Historie-Werten
        # (inkonsistente Anzeige + falsche Persistenz beim Schliessen).
        self._sync_profile_filters()
        # Bugfix 08.08.2026 (Profilname '?' nach Save): Auch die Name-/
        # Beschreibungs-Felder bleiben nach load_profiles() leer (kein
        # active_profile_changed). Beim ersten Save wuerde update_profile
        # name='' persistieren und die Combo zeigt '?'. Deshalb die Felder
        # hier aus dem (ggf. geladenen) aktiven Profil synchronisieren.
        self._sync_profile_editor()
        # 20.01 (E7): Workspace NACH dem aktiven Profil anwenden – der letzte
        # Sitzungszustand gewinnt. Fehlende Services -> Warn-Label.
        self._restore_workspace()
        self._on_page_changed(self.sidebar.currentRow())
        # Runde 9 (Bug 4): Finalen Refresh sicherstellen - falls weder ein
        # aktives Profil (load_profiles) noch ein Workspace (restore_workspace)
        # existierte, wurde ggf. keine Query gestartet (set_symbol/
        # set_timeframe waren idempotent). refresh_all() stoesst die
        # Initial-Queries mit den finalen Parametern an (der Debounce
        # buegelt doppelte Refreshes ab). Der Datenquellen-Button wird
        # ebenfalls nachgezogen (fehlte nach reinem Profil-/Workspace-Start).
        self._vm.refresh_all()
        self._sync_service_filter_button()
        # 15.03-E: QUERY_FEATURES speiste das entfernte combo_feature-Dropdown –
        # ohne Feature-Dropdown ist keine Features-Metadaten-Abfrage noetig.

    def save_state(self) -> None:
        """Persistiert Fenster-POSITION und -GROESSE (inkl. Dialog-Fallback).

        11.08.2026 (Bugfix Runde 17e, User-Meldung 2): Neben window_instances
        wird die Geometrie zusaetzlich in global_settings gesichert
        (DIALOG_GEOMETRY_KEY) – sie ueberlebt damit das manuelle Schliessen
        (delete_instance loescht window_instances/instance_states) und wird
        beim naechsten manuellen Oeffnen ueber den Fallback in
        restore_state() wiederhergestellt (Muster ServiceWindow).
        """
        inst_id = self.get_instance_id()
        if not inst_id:
            return
        try:
            p = self.pos()
            self._state_manager.save_dialog_geometry(
                self.DIALOG_GEOMETRY_KEY, p.x(), p.y(),
                self.width(), self.height())
        except Exception:
            pass
        # Basis-Teil: window_instances-Geometrie + instance_states
        # (Symbol/Timeframe via get_persistent_symbol/timeframe).
        super().save_state()

    def restore_state(self) -> None:
        """Stellt Geometrie + Filter wieder her (inkl. Dialog-Fallback).

        11.08.2026 (Bugfix Runde 17e, User-Meldung 2): Nach einem MANUELLEN
        Schliessen existiert kein window_instances-Eintrag mehr – die
        Position wird dann aus global_settings (DIALOG_GEOMETRY_KEY)
        wiederhergestellt (Muster ServiceWindow). Der Rest (Symbol/
        Timeframe/Workspace) laeuft ueber super().restore_state() bzw.
        _initial_load -> _restore_workspace().
        """
        inst_id = self.get_instance_id()
        if not inst_id:
            return
        # Window-Flags korrigieren (NUR bei unsichtbarem Fenster –
        # setWindowFlags() auf sichtbarem Fenster bricht die Layout-
        # Geometrie-Verwaltung, Bugfix Runde 17c).
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
            if width and height:
                self.resize(max(int(width), 640), max(int(height), 480))
            if pos_x is not None and pos_y is not None:
                if pos_x < screen_geo.x() - 100 or pos_x > screen_geo.right() or \
                   pos_y < screen_geo.y() - 100 or pos_y > screen_geo.bottom():
                    pos_x, pos_y = 100, 100
                self.move(pos_x, pos_y)
            self._restored_is_maximized = bool(geom.get("is_maximized", False))
        # Symbol/Timeframe (instance_states) ueber die Basis wiederherstellen.
        super().restore_state()

    def closeEvent(self, event) -> None:
        """Stoppt Debounce + Worker und persistiert den Workspace.

        11.08.2026 (Bugfix Runde 17e, User-Meldung 2): _keep_history_on_close
        = False – der Fenster-Historie-Eintrag wird beim MANUELLEN
        Schliessen entfernt (kein Wiedererscheinen beim Neustart). Der
        Workspace (instance_states.workspace_state + global_settings-Backup)
        wird hier VOR super().closeEvent() gespeichert und beim naechsten
        manuellen Oeffnen wiederhergestellt.
        """
        try:
            self._vm.shutdown()
        except Exception:
            pass
        # 10.08.2026 (Bugfix Runde 7, Bug 2): Der Workspace wird VOR dem
        # Schliessen des ServicePickers gespeichert, damit `service_picker_
        # open` den Zustand des noch sichtbaren Dialogs erfasst.
        self._save_workspace()
        # 10.08.2026 (Bugfix, Punkt 3): Den ServicePicker-Singleton mit
        # schliessen, wenn das AnalyticsWindow geschlossen wird - sonst
        # bleibt der frei bewegliche Dialog als Waisenfenster haengen.
        # Das `destroyed`-Signal setzt self._service_dialog zurueck.
        try:
            if self._service_dialog is not None:
                self._service_dialog.close()
        except (RuntimeError, AttributeError):
            pass
        super().closeEvent(event)
