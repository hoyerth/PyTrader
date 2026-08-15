# analytics/engine/analytics_view_model.py
"""
analytics_view_model.py - AnalyticsViewModel (Phase 15.03 Schritt 4).

Vermittelt zwischen `AnalyticsRepository` (+ `FeatureStoreReader`), dem
asynchronen `AnalyticsAsyncWorker` und den UI-Pages (analytics/ui/*,
Invariante 4 / MVVM). KEIN SQL, KEIN UI-Code – nur Qt-Core (QObject/QTimer)
und Repositories. Datenfluss:

    UI-Page -> set_*()/request_*() -> ViewModel (Debounce-QTimer 250 ms)
    -> AnalyticsAsyncWorker (QThread) -> data_ready(query_kind, data)

Aufgaben (15.03-Spezifikation):
1. Datenfluss: UI-Pages fordern Daten ueber `request_*()` an; der ViewModel
   puffert die aktuellen Parameter, debounced (QTimer, 200-300 ms) und
   startet bei Bedarf einen Async-Worker. Parameternaenderungen (Slider
   usw.) feuern die betroffenen Abfragen automatisch nach.
2. Profil-Verwaltung (Option B – Explicit Save): Aktives Profil via
   `AnalyticsProfileRepository`; Parametertrends setzen das Dirty-Flag
   (`*` im Titel/Combo); gespeichert wird erst auf `save_profile()`.
3. Max-Lookback-Cap: `MAX_LOOKBACK_LIMIT = 50_000` (hart, 15.03-Spez).
4. EventBus: Profilwechsel wird auf `event_bus.profile_changed(str)`
   emittiert (Invariante 5 / zentraler EventBus, Payload = Profil-Name).
"""

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, QTimer, Signal

from analytics.engine.analytics_repository import AnalyticsRepository
from analytics.engine.analytics_worker import (
    QUERY_TABLE,
    QUERY_HEATMAP,
    QUERY_HEATMAP_GENERIC,
    QUERY_OHLCV,
    QUERY_DAILY_OHLC,
    QUERY_SCATTER,
    QUERY_DISTRIBUTION,
    QUERY_FEATURES,
    MAX_LOOKBACK_LIMIT,
    AnalyticsAsyncWorker,
)
from repositories.analytics_profile_repository import (
    AnalyticsProfileRepository,
    get_analytics_profile_repository,
    SCHEMA_VERSION_DEFAULT,
)
from config.event_bus import event_bus
from analytics.engine.analytics_view_model_query import AnalyticsViewModelQueryMixin
from analytics.engine.analytics_view_model_setters import AnalyticsViewModelSetterMixin
from analytics.engine.analytics_view_model_fields import AnalyticsViewModelFieldMixin
from analytics.engine.analytics_view_model_heatmap import AnalyticsViewModelHeatmapMixin
from analytics.engine.analytics_view_model_profile import AnalyticsViewModelProfileMixin
from analytics.engine.analytics_view_model_resolve import AnalyticsViewModelResolveMixin

from analytics.engine.analytics_view_model_constants import (
    DEBOUNCE_MS,
    DEFAULT_BINS,
    DEFAULT_LIMIT,
    _ALL_QUERIES,
)


class AnalyticsViewModel(
    QObject,
    AnalyticsViewModelQueryMixin, AnalyticsViewModelSetterMixin,
    AnalyticsViewModelFieldMixin, AnalyticsViewModelHeatmapMixin,
    AnalyticsViewModelProfileMixin, AnalyticsViewModelResolveMixin,
):
    """MVVM-ViewModel der Analytics-Engine (kein SQL, kein UI)."""

    # Datenfluss-Signale (query_kind -> Ergebnis/Fehler)
    data_ready = Signal(str, dict)
    query_failed = Signal(str, str)
    busy_changed = Signal(bool)  # Progress-Spinner an/aus

    # Profil-Signale (Option B – Explicit Save)
    active_profile_changed = Signal(object)  # Profil-Dict oder None
    dirty_changed = Signal(bool)             # '*' im Titel/Combo
    profile_saved = Signal(str)              # profile_id
    profile_deleted = Signal(str)            # profile_id
    profiles_available = Signal(list)        # Liste der Profile

    # 20.01 (Graceful Degradation, E5): fehlende (entfernte/umbenannte)
    # Services – Payload: Liste der nicht mehr registrierten plugin_ids.
    missing_services_detected = Signal(list)

    # 20.04-Timing-Fix (D): Nach restore_workspace()/_apply_profile() – die
    # UI-Pages synchronisieren ihre Combos explizit aus den restaurierten
    # VM-Params (kein UI-Import im ViewModel, MVVM-Invariante 4).
    params_restored = Signal()

    # Runde 8 (Bugfix 4, 10.08.2026): feature_ids-Aenderungen (ServicePicker
    # Check/Uncheck) SYNCHRON an die UI – das HeatmapWidget leitet sein
    # 'Feld'-Dropdown sofort aus den gecachten Feld-Metadaten + den neuen
    # feature_ids neu ab (kein Debounce/Query-Round-Trip noetig). Wird in
    # set_feature_ids() NACH der Uebernahme emittiert (idempotent: nur bei
    # echter Aenderung). Restore-Pfade setzen _params["feature_ids"] DIREKT
    # und emittieren stattdessen params_restored (kein Dirty/Doppel-Refresh).
    feature_ids_changed = Signal()

    def __init__(
        self,
        analytics_repo: Optional[AnalyticsRepository] = None,
        profile_repo: Optional[AnalyticsProfileRepository] = None,
        selector_model=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._repo = analytics_repo or AnalyticsRepository()
        self._profile_repo = profile_repo or get_analytics_profile_repository()
        # 20.01 (E5): ServiceSelectorModel fuer den Fault-Tolerant-Resolver
        # (resolve_valid_feature_ids). Lazy Default – wird nur bei Bedarf
        # instanziiert (Tests/Alt-Aufrufer ohne Injektion bleiben schlank).
        self._selector_model = selector_model

        # Aktuelle Ansichtsparameter (werden im Profil-Payload persistiert).
        self._params: Dict[str, Any] = {
            "symbol": "",
            "timeframe": "M1",
            # 15.03-E (Multi-Select): feature_ids = Liste der plugin_ids
            # (Datenquellen-Filter, `WHERE feature_id IN (...)`); leer = alle.
            "feature_ids": [],
            # Runde 10 (Bug 1): Varianten-Einschraenkung (instance_hashes
            # der gecheckten Clone-Varianten; leer = alle Varianten der
            # gewaehlten plugin_ids).
            "instance_hashes": [],
            # 19.02 (Cleanup): Keine festen Legacy-Spalten-Defaults mehr –
            # scatter_x/scatter_y/distribution_column werden beim ersten
            # Daten-Payload auf die verfuegbaren feature_data-JSON-Keys
            # aufgeloest (Repo-Defaults). Leer = Repo waehlt die ersten
            # numerischen Keys.
            "heatmap_metric": "count",
            "scatter_x": "",
            "scatter_y": "",
            "distribution_column": "",
            "bins": DEFAULT_BINS,
            "limit": DEFAULT_LIMIT,
            # 20.02 (E1/E3/E8/E10, generische 2D-Heatmap): Konfiguration der
            # generischen Heatmap – x/y-Dimensionen (DIM_MAPPINGS), Aggregation
            # und numerischer feature_data-JSON-Key (`field`, E6). Defaults
            # laut Kapitel: Confluence-Modus (CONFLUENCE_COUNT) auf
            # Datum×Stunde. `selected_feature_ids` entfaellt (E10: Redundanz
            # zu feature_ids). Zoom = normalisierte Viewport-Anteile [0,1]
            # (E8), rein client-seitig (kein DB-Requery).
            "heatmap_x_dim": "date",
            "heatmap_y_dim": "hour",
            "heatmap_field": "",
            "heatmap_agg": "confluence_count",
            # 21.01 (E1, 11.08.2026): TF-Freigabe – True entfaellt die
            # TF-WHERE-Bedingung der generischen Heatmap (Preset
            # `[📊 Service-Timeframe]`: alle Zeitebenen M1..D1 in EINER
            # Query). Persistiert im Profil-Payload (charts.heatmap).
            "heatmap_all_timeframes": False,
            "candle_projection_enabled": False,
            "zoom_x_range": [0.0, 1.0],
            "zoom_y_range": [0.0, 1.0],
            # 19.03 (Step 2): TablePage-Settings – reine UI-Zustaende ohne
            # DB-Abfrage. Persistiert im Profil-Payload (Option B – Explicit
            # Save); set_table_settings() markiert nur dirty (E6, kein
            # Query-Refresh). Spaltenbreiten {Spaltenname: Breite} (E5),
            # Zeilenhoehe als Default-Section-Size (E9), Sortier-Spalte und
            # -Richtung als Qt-Werte (E8; 1 = DescendingOrder = Zeit absteigend).
            "table_column_widths": {},
            "table_row_height": 0,
            "table_sort_column": 0,
            "table_sort_order": 1,
            # 21.03.12 (MTF-FC auf Analytics): Filterleisten-Parameter des
            # MtfFilterBarWidget. `data_tf` = Analysequelle ('multi' = alle
            # TFs in einer Query via all_timeframes; sonst fixierter TF, der
            # den `timeframe`-Filter uebernimmt). `agg_tf` = Aggregations-TF
            # (Entscheidung 6a: 'auto' oder konkreter TF fuer das Zeitraster
            # der generischen Heatmap). `range_from`/`range_to` = optionaler
            # Zeitfilter (bar_time BETWEEN), Basis = letzter Datenpunkt.
            "data_tf": "multi",
            "agg_tf": "auto",
            "range_preset": None,
            "range_from": None,
            "range_to": None,
            # 21.03.12: Von set_data_tf() verwaltetes Flag - True = alle
            # Timeframes in EINER Query (data_tf='multi'), False = fixierter
            # TF. Separates Flag von heatmap_all_timeframes (21.01-Preset).
            "all_timeframes": False,
            # 21.03.14 (Wunsch 2): Tabellen-Sortierung des MtfFilterBarWidget
            # ('date' | 'signal' | 'tf'). Reiner UI-Zustand (kein SQL-Filter);
            # wird im Profil-Payload (Sektion sources) persistiert und beim
            # Profil-/Workspace-Restore ueber die Filterleiste restauriert
            # (nach dem Rueckbau der View-Template-Buttons).
            "sort_mode": "date",
            # 21.03.20 (Analytics Modus-Filter): source_mode-Filter fuer
            # Multi-Modus-Services. Default "all" = kein Filter (alle Modi).
            # Wirkt GLOBAL auf alle Analytics-Datenquellen (Entscheidung 1);
            # wird in der sources-Sektion des Profil-Payloads persistiert.
            "service_mode": "all",
        }
        self._pending_kinds: List[str] = []
        self._worker: Optional[AnalyticsAsyncWorker] = None
        self._dirty = False
        self._active_profile: Optional[Dict[str, Any]] = None
        self._profiles: List[Dict[str, Any]] = []
        # 20.01 (E7): UI-Layout-Anteil des zuletzt restaurierten Workspace
        # (z. B. {"page_index": 2}) – von der UI abfragbar, kein _params-Key.
        self._workspace_layout: Dict[str, Any] = {}
        # 10.08.2026 (Punkte 3/4): UI-Layout-Anteil fuer die PROFIL-
        # Persistenz (page_index, heatmap_mode) - die UI uebergibt ihn vor
        # jedem save_profile()/create_profile() via set_ui_layout(); die
        # Werte wandern ueber _current_payload() (Sektion "layout") in den
        # Profil-Payload und werden in _apply_profile() in _workspace_layout
        # abgelegt (die UI liest sie dort - identischer Pfad wie der
        # Workspace-Restore).
        self._ui_layout: Dict[str, Any] = {}
        # Runde 8 (Bugfix 3, 10.08.2026): Generations-Token gegen
        # Stale-Payloads - wird bei JEDEM restore_workspace()/
        # _apply_profile() erhoeht und wandert ueber _current_params() in
        # die Worker-Params. Der Worker spiegelt es ins Ergebnis-Dict
        # (data["restore_generation"]); die UI verwirft Payloads aelterer
        # Generation (Queries, die VOR dem Restore gestartet wurden,
        # duerfen den synchron restaurierten Zustand nicht ueberschreiben).
        self._restore_generation: int = 0

        # Debounce-QTimer (200-300 ms, 15.03-Spezifikation)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._start_next_query)
