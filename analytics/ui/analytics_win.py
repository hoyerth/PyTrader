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
- 15.03-E + 18.01.01 (E-4): Datenquellen-Filter DIREKT im Fenster (ersetzt
  den `ServiceSelectorDialog`): Checkbox-MasterTree (Sets/Ordner/Services/
  Plugins) mit Baum-Selektion -> `set_feature_ids(...)` und editierbarem
  Standalone-Param-Panel (`plugin_params_<id>` + EventBus-Sync E-3),
  SQL `WHERE feature_id IN (...)`.
- Jump-to-Chart (Variante 2): open_chart_at_bar(symbol, tf, bar_time)
  und Chart-Fenster in den Vordergrund holen.
- E-2: Migration der win_statistics-Persistenz nach win_analytics
  (Fenstergeometrie & Instanz-Zustand).
- EventBus (Invariante 5): Profilwechsel + Favoriten-Aenderungen.
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, Slot
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
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_view_model import AnalyticsViewModel
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
from serviceui.master_tree import MasterTree
from serviceui.param_columns import ServiceParamColumnsMixin
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
class AnalyticsWindow(ServiceParamColumnsMixin, PersistentWindow):
    """Analytics-Hauptfenster (win_analytics, 1280 x 800, nicht-modal).

    18.01.01 (E-4): Erbt zusaetzlich `ServiceParamColumnsMixin` – der
    eingebettete Datenquellen-Filter rendert damit die editierbaren
    Standalone-Parameter-Spalten direkt im Fenster (E-2: die reale
    Param-Column-Klasse, kein 'ParamColumnsWidget')."""

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
        except Exception:
            self._default_limit = 10_000

        # 15.03-E + 18.01.01 (E-4): Das ServiceSelectorModel ist injizierbar
        # (Headless-Tests). Seit 18.01.01 ist der Datenquellen-Filter KEIN
        # Dialog mehr, sondern der eingebettete MasterTree (Checkbox-Multi-
        # Select, Baum-Selektion -> set_feature_ids) mit editierbarem
        # Standalone-Param-Panel (Option B).
        self._selector_model: ServiceSelectorModel = (
            selector_model or ServiceSelectorModel(parent=self))
        # 18.01.01: Standalone-Plugin-Editierung im Analytics-Kontext –
        # Persistenz in global_settings (Key 'plugin_params_<pid>').
        self._current_plugin_editing: Optional[str] = None
        self._current_set_definition: Optional[Dict[str, Any]] = None
        #: Preisskala-Praezision je Symbol (lazy, _get_symbol_precision).
        self._symbol_precision: Optional[int] = None

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

        # --- Filter-Zeile: Symbol / TF / Limit ---
        # 18.01.01 (E-4): Der Datenquellen-Button ist ersatzlos entfernt –
        # der Multi-Select-Filter liegt seitdem als eingebetteter MasterTree
        # im Body-Bereich (Baum-Selektion -> set_feature_ids, Option B).
        filt = QHBoxLayout()
        self.combo_symbol = QComboBox()
        self.btn_symbol_fav = QPushButton("★")
        self.btn_symbol_fav.setFixedWidth(32)
        self.btn_symbol_fav.setToolTip(
            "Favoriten verwalten – öffnet das Symbol-Fenster.")
        self.combo_tf = QComboBox()
        for tf in TIMEFRAMES:
            self.combo_tf.addItem(tf, tf)
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
        filt.addWidget(QLabel("Limit:"))
        filt.addWidget(self.edit_limit)
        filt.addStretch(1)
        root.addLayout(filt)

        # --- Body: Sidebar + Datenquellen (MasterTree + Param-Panel) + Seiten ---
        # 18.01.01 (E-4): Der ServiceSelectorDialog ist ersatzlos in das
        # Fenster eingebettet: Checkbox-MasterTree (Multi-Select-Filter,
        # Klick-Selektion -> set_feature_ids) mit editierbarem Param-Panel
        # (Standalone-Services, plugin_params_<id> + E-3 EventBus-Sync).
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

        service_zone = QWidget()
        sz = QHBoxLayout(service_zone)
        sz.setContentsMargins(0, 0, 0, 0)
        sz.setSpacing(6)

        tree_panel = QWidget()
        tp = QVBoxLayout(tree_panel)
        tp.setContentsMargins(0, 0, 0, 0)
        tp.setSpacing(4)
        tp.addWidget(QLabel(
            "Datenquellen (Klick = Filtern, Haken = Multi-Select):"))
        self.service_tree = MasterTree(self._selector_model, parent=self)
        self.service_tree.set_checkable(True)
        # 18.01.01: Kein Struktur-/Run-Kontextmenue im Analytics-Filter –
        # die Run-/CRUD-Aktionen gehören in das ServiceWindow.
        self.service_tree.setContextMenuPolicy(Qt.NoContextMenu)
        self.service_tree.setMinimumWidth(300)
        self.service_tree.setMaximumWidth(430)
        tp.addWidget(self.service_tree, 1)
        sz.addWidget(tree_panel, 0)

        param_panel = QWidget()
        pp = QVBoxLayout(param_panel)
        pp.setContentsMargins(0, 0, 0, 0)
        pp.setSpacing(4)
        pp.addWidget(QLabel("Service-Parameter:"))
        self.param_scroll = QScrollArea(param_panel)
        self.param_scroll.setWidgetResizable(True)
        self.param_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.param_container = QWidget()
        # 18.01.01: service_columns_layout erwartet der Param-Column-Mixin
        # (_clear_service_columns/_build_service_column).
        self.service_columns_layout = QHBoxLayout(self.param_container)
        self.service_columns_layout.setContentsMargins(0, 0, 0, 0)
        self.service_columns_layout.setSpacing(6)
        self.param_scroll.setWidget(self.param_container)
        pp.addWidget(self.param_scroll, 1)
        self.btn_save_params = QPushButton("💾 Parameter speichern")
        self.btn_save_params.setVisible(False)
        self.btn_save_params.setToolTip(
            "Speichert die Parameter des editierbaren Standalone-Services "
            "(plugin_params_<id>) inkl. EventBus-Sync (E-3).")
        pp.addWidget(self.btn_save_params)
        sz.addWidget(param_panel, 1)

        body.addWidget(self.sidebar)
        body.addWidget(service_zone, 2)
        body.addWidget(self.pages_stack, 3)
        root.addLayout(body, 1)

        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    # 18.01.01 (E-4): Eingebetteter Datenquellen-Filter
    # (MasterTree + editierbares Param-Panel, ersetzt ServiceSelectorDialog)
    # ------------------------------------------------------------------

    def _sync_tree_from_vm(self) -> None:
        """Synchronisiert die Checkboxen des MasterTree mit dem VM-Filter.

        Ersetzt die fruehere Button-Sync-Logik (18.01.01, E-4): Nach einem
        Profilwechsel bzw. `event_bus.profile_changed` werden die
        persistierten feature_ids (plugin_ids) als Haken im Baum abgebildet.
        Der dadurch emittierte `checked_changed` ruft `set_feature_ids`
        idempotent auf (gleiche IDs -> kein Refresh, keine Schleife).
        """
        if not hasattr(self, "service_tree"):
            return
        ids = self._vm.params.get("feature_ids") or []
        self.service_tree.set_checked_feature_ids(ids)

    def _on_service_tree_checked(self) -> None:
        """Multi-Select-Filter (Checkboxen): Haken -> ViewModel.

        feature_ids (plugin_ids) der angehakten Service-/Plugin-Knoten gehen
        an `AnalyticsViewModel.set_feature_ids()` (SQL WHERE feature_id IN).
        """
        ids = self.service_tree.checked_feature_ids()
        self._vm.set_feature_ids(ids)

    def _resolve_selection_ids(self, node_type: str, set_id: str,
                               service_id: str, plugin_id: str) -> List[str]:
        """Loest eine geklickte Baum-Zeile in feature_ids (plugin_ids) auf.

        18.01.01 (E-4): Klick auf Set -> alle Services des Sets; Klick auf
        Kategorie-Ordner -> `category_plugin_ids(Pfad, rekursiv)`; Klick auf
        Plugin-Zeile -> [plugin_id]; Service-Zeile -> [plugin_id des Service].
        """
        if node_type == "category":
            return self._selector_model.category_plugin_ids(plugin_id or "")
        if node_type == "plugin" and plugin_id:
            return [str(plugin_id)]
        if node_type == "service" and set_id and service_id:
            cfg = self._selector_model.find_service(set_id, service_id) or {}
            pid = str(cfg.get("plugin_id") or service_id)
            return [pid] if pid else []
        if node_type == "set" and set_id:
            definition = self._selector_model.find_set(set_id) or {}
            services = definition.get("services") or {}
            order = definition.get("execution_order") or list(services.keys())
            ids: List[str] = []
            for iid in order:
                cfg = services.get(iid) or {}
                pid = str(cfg.get("plugin_id") or iid)
                if pid and pid not in ids:
                    ids.append(pid)
            return ids
        return []

    def _entries_for_scope(self, node_type: str, set_id: str,
                           service_id: str, plugin_id: str) -> List[Dict[str, str]]:
        """Param-Panel-Entries der geklickten Tree-Zeile (service_win-Muster).

        Returns:
            Liste von {"node_type", "set_id", "instance_id", "plugin_id"} –
            leer fuer Gruppen/leere Auswahl. Kategorie-Ordner liefern die
            Plugins des Pfads (rekursiv), Set-/Service-Zeilen alle Services
            des Sets, Plugin-Zeilen nur diesen einen Service.
        """
        if node_type == "category":
            entries: List[Dict[str, str]] = []
            for pid in self._selector_model.category_plugin_ids(plugin_id or ""):
                entries.append({
                    "node_type": "plugin",
                    "set_id": "",
                    "instance_id": "",
                    "plugin_id": pid,
                })
            return entries
        if node_type == "plugin" and plugin_id:
            return [{
                "node_type": "plugin",
                "set_id": "",
                "instance_id": "",
                "plugin_id": str(plugin_id),
            }]
        if node_type in ("set", "service") and set_id:
            definition = self._selector_model.find_set(set_id) or {}
            services = definition.get("services") or {}
            order = definition.get("execution_order") or list(services.keys())
            entries = []
            for iid in order:
                cfg = services.get(iid) or {}
                if not isinstance(cfg, dict):
                    continue
                entries.append({
                    "node_type": "service",
                    "set_id": str(set_id),
                    "instance_id": str(iid),
                    "plugin_id": str(cfg.get("plugin_id") or iid),
                })
            return entries
        return []

    def _plugin_config(self, plugin_id: str) -> Dict[str, Any]:
        """ServiceInstanceConfig eines Standalone-Plugins (Analytics-Kontext).

        Basis sind die Registry-Defaults; gespeicherte Werte aus
        global_settings (Key 'plugin_params_<pid>') ueberschreiben lookback/
        params und ergaenzen eine optionale Beschreibung (service_win-Muster).
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
            saved = self.state_manager.get_global_value(
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

    def _rebuild_param_panel(self, entries: Optional[List[Dict[str, str]]],
                             editable_plugin: Optional[str] = None) -> None:
        """Baut das Param-Panel aus den uebergebenen Entries neu.

        Standalone-Plugin-Zeilen (editable_plugin gesetzt) rendern die
        Spalte AKTIV (editierbar, Dirty-Tracking + Speichern); alle anderen
        Zeilen (Sets, Indikator-Services, Ordner) werden read-only angezeigt
        (deaktivierte QGroupBox, wie im ServiceSelectorDialog).
        """
        self._clear_service_columns()
        self._set_param_actions_visible(False)
        self._current_plugin_editing = None
        self._current_set_definition = None
        entries = list(entries or [])
        if not entries:
            self.service_columns_layout.addWidget(
                QLabel("Keine Auswahl – klicke eine Zeile im Baum."))
            self.service_columns_layout.addStretch(1)
            return
        for entry in entries:
            pid = str(entry.get("plugin_id") or "")
            if entry["node_type"] == "service":
                iid = str(entry.get("instance_id") or "")
                cfg = self._selector_model.find_service(
                    str(entry.get("set_id") or ""), iid) or {}
            else:
                iid = pid
                cfg = self._plugin_config(pid)
            editable = bool(editable_plugin) and pid == editable_plugin
            try:
                box = self._build_service_column(iid, pid, cfg)
            except Exception as e:
                box = None
                self.service_columns_layout.addWidget(
                    QLabel(f"Parameteranzeige nicht verfügbar: {e}"))
            if box is not None:
                if not editable:
                    box.setEnabled(False)
                    box.setToolTip("Read-Only – Parameter der gewählten "
                                   "Datenquelle (editierbar im ServiceWindow)")
                else:
                    # 18.01.01 (E-4): Editierbarer Standalone-Service –
                    # RAM-Definition fuer das Dirty-Tracking (_on_param_changed)
                    # bereitstellen; Persistenz via _save_plugin_params.
                    definition: Dict[str, Any] = {
                        "set_id": "",
                        "display_name": pid,
                        "description": str(cfg.get("description") or ""),
                        "execution_order": [pid],
                        "services": {pid: cfg},
                    }
                    self._current_plugin_editing = pid
                    self._current_set_definition = definition
                self.service_columns_layout.addWidget(box)
        self.service_columns_layout.addStretch(1)

    @Slot(str, str, str, str)
    def _on_service_selection_details(self, node_type: str, set_id: str,
                                      service_id: str, plugin_id: str) -> None:
        """Slot fuer MasterTree.selection_details (Mausklick in einer Zeile).

        18.01.01 (E-4): Jeder Klick auf eine Datenquellen-Zeile
        (a) loest die IDs der Zeile auf und setzt den VM-Filter
            (`set_feature_ids`, Baum-Selektion -> Filter) und
        (b) baut das Param-Panel neu (Set/Ordner/Plugin -> Entries).
        Standalone-Services (belongs_to_indicator == False) sind editierbar;
        Indikator-/Set-Services bleiben read-only.
        """
        # Filter setzen (Set/Ordner/Plugin -> IDs aufloesen).
        ids = self._resolve_selection_ids(node_type, set_id, service_id,
                                          plugin_id)
        if ids:
            self._vm.set_feature_ids(ids)
            self.service_tree.set_checked_feature_ids(ids)
        # Param-Panel: editierbar nur fuer einzelne Standalone-Plugin-Zeilen.
        editable = None
        if node_type == "plugin" and plugin_id:
            if not self._selector_model.belongs_to_indicator(str(plugin_id)):
                editable = str(plugin_id)
        self._rebuild_param_panel(
            self._entries_for_scope(node_type, set_id, service_id, plugin_id),
            editable_plugin=editable)

    @Slot()
    def _save_plugin_params(self) -> bool:
        """Persistiert die Parameter des editierbaren Standalone-Plugins.

        global_settings (Key 'plugin_params_<pid>') + EventBus-Sync
        (`service_set_changed`, E-3) – so synchronisieren alle
        ServiceSelectorModel-Instanzen den MasterTree live.
        """
        plugin_id = self._current_plugin_editing
        if not plugin_id:
            return False
        definition = self._current_set_definition or {}
        services = definition.get("services") or {}
        cfg = next(iter(services.values()), None)
        if not isinstance(cfg, dict):
            return False
        data: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": int(cfg.get("lookback") or 1000),
            "params": dict(cfg.get("params") or {}),
            "description": str(cfg.get("description") or ""),
        }
        try:
            self.state_manager.save_global_value(
                f"plugin_params_{plugin_id}", data)
        except Exception as e:
            print(f"WARN [AnalyticsWindow] Plugin-Parameter nicht "
                  f"gespeichert: {e}")
            return False
        self._set_param_actions_visible(False)
        event_bus.service_set_changed.emit()
        return True

    def _set_param_actions_visible(self, visible: bool) -> None:
        """Blendet den Speichern-Button des Param-Panels ein/aus (Dirty)."""
        btn = getattr(self, "btn_save_params", None)
        if btn is not None:
            try:
                btn.setVisible(bool(visible))
            except (RuntimeError, AttributeError):
                pass

    # --- ServiceParamColumnsMixin-Host (18.01.01, E-2) -------------------
    def _service_lock(self, plugin_id: str) -> tuple:
        """Keine Set-Sperre im Analytics-Kontext (kein Set-Editing hier)."""
        return "", ""

    def _open_service_desc_editor(self, instance_id: str) -> None:
        """Analytics: kein Beschreibungs-Editor (Parameter-Ansicht pur)."""
        pass

    def _schedule_reflow(self) -> None:
        """Analytics: kein Fenster-Reflow (Param-Panel skaliert nicht)."""
        pass

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
        # 18.01.01 (E-4): Eingebetteter Datenquellen-Filter (MasterTree).
        # checked_changed (Checkboxen) = Multi-Select-Filter; selection_details
        # (Klick auf Set/Ordner/Plugin) = ID-Aufloesung + Param-Panel.
        self.service_tree.checked_changed.connect(self._on_service_tree_checked)
        self.service_tree.selection_details.connect(
            self._on_service_selection_details)
        self.btn_save_params.clicked.connect(self._save_plugin_params)
        event_bus.profile_changed.connect(self._sync_tree_from_vm)
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
            self._sync_tree_from_vm()
            return
        self.edit_profile_name.setText(profile.get("name") or "")
        self.edit_profile_desc.setText(profile.get("description") or "")
        pid = profile.get("profile_id")
        idx = self.combo_profile.findData(pid)
        if idx >= 0 and self.combo_profile.currentIndex() != idx:
            self.combo_profile.blockSignals(True)
            self.combo_profile.setCurrentIndex(idx)
            self.combo_profile.blockSignals(False)
        # 18.01.01 (E-4): Profilwechsel uebernimmt feature_ids in den VM –
        # die Checkboxen des eingebetteten MasterTree werden aus den
        # persistierten IDs synchronisiert (_sync_tree_from_vm).
        self._sync_tree_from_vm()
        # 06.08.2026 (Punkt 5): Limit-Feld mit dem (ggf. aus dem Profil
        # geladenen) VM-Wert synchronisieren.
        if hasattr(self, "edit_limit"):
            self.edit_limit.setText(
                str(int(self._vm.params.get("limit") or self._default_limit)))

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
