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

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
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


@register_persistent_window()
class AnalyticsWindow(PersistentWindow):
    """Analytics-Hauptfenster (win_analytics, 1280 x 800, nicht-modal)."""

    INSTANCE_ID = "win_analytics"
    # Bugfix 04.08.2026 (Fenster-Historie): auto_restore=True – das Fenster
    # wird beim App-Start wiederhergestellt, wenn es beim Beenden der App
    # OFFEN war. _keep_history_on_close bleibt Default (False): ein MANUELL
    # geschlossenes Fenster wird aus der aktiven History entfernt
    # (delete_instance) und poppt beim naechsten Start NICHT wieder auf
    # (Semantik identisch zu chart_win).

    def __init__(
        self,
        parent=None,
        view_model: Optional[AnalyticsViewModel] = None,
        analytics_repo: Any = None,
        profile_repo: Any = None,
        selector_model: Optional[ServiceSelectorModel] = None,
    ) -> None:
        super().__init__(parent)
        self._vm = view_model or AnalyticsViewModel(
            analytics_repo=analytics_repo,
            profile_repo=profile_repo,
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
        self._selector_model: ServiceSelectorModel = (
            selector_model or ServiceSelectorModel(parent=self))
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
        top = QHBoxLayout()
        self.combo_profile = QComboBox()
        self.combo_profile.setMinimumWidth(160)
        self.edit_profile_name = QLineEdit()
        self.edit_profile_name.setPlaceholderText("Profil-Name")
        self.edit_profile_name.setMaximumWidth(180)
        self.edit_profile_desc = QLineEdit()
        self.edit_profile_desc.setPlaceholderText("Beschreibung (optional)")
        self.edit_profile_desc.setMaximumWidth(200)
        self.btn_profile_new = QPushButton("Neu")
        self.btn_profile_save = QPushButton("💾 Save")
        self.btn_profile_delete = QPushButton("Löschen")
        self.label_dirty = QLabel("")
        self.label_dirty.setStyleSheet("color: #e65100; font-weight: bold;")
        self.progress_busy = QProgressBar()
        self.progress_busy.setRange(0, 0)  # indeterminierter Spinner
        self.progress_busy.setFixedWidth(120)
        self.progress_busy.setVisible(False)

        top.addWidget(QLabel("Profil:"))
        top.addWidget(self.combo_profile)
        top.addWidget(self.edit_profile_name)
        top.addWidget(self.edit_profile_desc)
        top.addWidget(self.btn_profile_new)
        top.addWidget(self.btn_profile_save)
        top.addWidget(self.btn_profile_delete)
        top.addWidget(self.label_dirty)
        top.addStretch(1)
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
        filt.addStretch(1)
        root.addLayout(filt)

        # --- Body: Sidebar + Seiten (QStackedWidget) ---
        body = QHBoxLayout()
        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(150)
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

        body.addWidget(self.sidebar)
        body.addWidget(self.pages_stack, 1)
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
            self._service_dialog.destroyed.connect(
                self._on_service_dialog_destroyed)
        self._service_dialog.apply_feature_ids(
            self._vm.params.get("feature_ids") or [])
        self._service_dialog.show()
        self._service_dialog.raise_()
        self._service_dialog.activateWindow()

    @Slot()
    def _on_service_dialog_destroyed(self) -> None:
        """Setzt die Dialog-Referenz zurueck (zerstoert mit dem Parent)."""
        self._service_dialog = None

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
        vm.busy_changed.connect(self._on_busy_changed)
        vm.query_failed.connect(self._on_query_failed)
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
    # Datenfluss (MVVM): Feature-Dropdown, Seiten, Status
    # ------------------------------------------------------------------
    def _on_page_changed(self, row: int) -> None:
        if 0 <= row < self.pages_stack.count():
            page = self.pages_stack.widget(row)
            if hasattr(page, "request_data"):
                page.request_data()

    @Slot(str, str)
    def _on_query_failed(self, kind: str, error: str) -> None:
        print(f"WARN [AnalyticsWindow] Abfrage '{kind}' fehlgeschlagen: {error}")

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
        if profile is None:
            self.edit_profile_name.clear()
            self.edit_profile_desc.clear()
            self._active_display_names = []
            self._sync_service_filter_button()
            return
        self.edit_profile_name.setText(profile.get("name") or "")
        self.edit_profile_desc.setText(profile.get("description") or "")
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
        """Synchronisiert Name-/Beschreibungs-/Limit-Felder mit dem VM (Bugfix).

        Wird beim App-Start nach `load_profiles()` gerufen: Dort emittiert der
        ViewModel KEIN `active_profile_changed` (nur set_active_profile/
        create_profile) – die edit-Felder blieben sonst leer. Ein leerer
        `edit_profile_name` wuerde beim ersten Save als `name=''` persistiert
        werden (die Combo zeigt dann '?'). Ohne aktives Profil werden die
        Felder geleert; das Limit-Feld wird mit dem VM-Wert synchronisiert.
        """
        active = self._vm.active_profile
        if active:
            self.edit_profile_name.setText(active.get("name") or "")
            self.edit_profile_desc.setText(active.get("description") or "")
        else:
            self.edit_profile_name.clear()
            self.edit_profile_desc.clear()
        if hasattr(self, "edit_limit"):
            self.edit_limit.setText(
                str(int(self._vm.params.get("limit")
                        or self._default_limit)))

    @Slot(bool)
    def _on_dirty_changed(self, dirty: bool) -> None:
        self.label_dirty.setText(
            "● ungespeicherte Änderungen" if dirty else "")
        self.setWindowTitle(
            WINDOW_TITLE_BASE + (" *" if dirty else ""))

    @Slot()
    def _on_profile_new(self) -> None:
        name, ok = QInputDialog.getText(self, "Neues Profil", "Profil-Name:")
        name = (name or "").strip()
        if not ok or not name:
            return
        desc, ok2 = QInputDialog.getText(
            self, "Neues Profil", "Beschreibung (optional):")
        if not ok2:
            desc = ""
        try:
            self._vm.create_profile(name, desc or "")
        except ValueError as e:
            QMessageBox.warning(self, "Profil anlegen", str(e))

    @Slot()
    def _on_profile_save(self) -> None:
        """Explicit Save: Name/Beschreibung + aktuelle Parameter persistieren."""
        if self._vm.active_profile is None:
            return
        pid = self._vm.active_profile["profile_id"]
        self._vm.update_profile(
            pid,
            name=self.edit_profile_name.text(),
            description=self.edit_profile_desc.text(),
        )
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
    def _initial_load(self) -> None:
        # VM mit dem aktuellen Combo-Zustand starten (Fix 15.03, idempotent):
        # restore_state (t=0) bzw. _apply_profile koennen bereits Werte gesetzt
        # haben; ohne Historie/Profil sorgt das hier dafuer, dass die Ansicht
        # sofort Daten fuer das sichtbare Symbol/Timeframe laedt.
        self._vm.set_symbol(self.combo_symbol.currentText())
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
        self._on_page_changed(self.sidebar.currentRow())
        # 15.03-E: QUERY_FEATURES speiste das entfernte combo_feature-Dropdown –
        # ohne Feature-Dropdown ist keine Features-Metadaten-Abfrage noetig.

    def closeEvent(self, event) -> None:
        """Stoppt Debounce + laufenden Worker (PersistentWindow speichert).

        Der Fenster-Historie-Eintrag bleibt dank _keep_history_on_close
        erhalten, damit Symbol/Timeframe beim naechsten Oeffnen
        wiederhergestellt werden (Fix 15.03).
        """
        try:
            self._vm.shutdown()
        except Exception:
            pass
        super().closeEvent(event)
