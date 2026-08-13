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
from analytics_profile_repository import (
    AnalyticsProfileRepository,
    get_analytics_profile_repository,
    SCHEMA_VERSION_DEFAULT,
)
from config.event_bus import event_bus

# QTimer-Debounce (15.03-Spezifikation: 200-300 ms) gegen SQL-Feuer.
DEBOUNCE_MS = 250

# Default-Parameter (Anfangs-Parametrisierung der Analytics-Ansichten).
DEFAULT_BINS = 20
DEFAULT_LIMIT = 5000

# 21.03.12 (MTF-FC auf Analytics): Alle Haupt-Queries, die beim data_tf-
# Wechsel neu angestossen werden (OHLCV/DAILY_OHLC sind on-demand und
# folgen keinem Filterwechsel - identisch zur refresh_all()-Liste).
_ALL_QUERIES = (QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                QUERY_SCATTER, QUERY_DISTRIBUTION, QUERY_FEATURES)


class AnalyticsViewModel(QObject):
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

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Stoppt Debounce + laufenden Worker und wartet dessen Ende ab.

        Fix 15.03 (Haenger bei TF-Wechsel): Der Worker wird gecancelt (Flag)
        und mit wait() abgewartet (Queries sind schnell, < 1 s). Ohne wait()
        wuerde der noch laufende QThread beim Zerstoeren des Fensters/
        ViewModel abgebrochen ('QThread: Destroyed while thread is still
        running') – die App haengt. self._worker wird vorher auf None gesetzt,
        damit verspaetete Signale des alten Workers vom Guard in
        _on_finished/_on_failed verworfen werden.
        """
        self._debounce.stop()
        self._pending_kinds.clear()
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.cancel()
            if worker.isRunning():
                worker.wait(5000)

    # ------------------------------------------------------------------
    # Datenfluss: UI-Pages fordern Abfragen an (MVVM)
    # ------------------------------------------------------------------
    def request_table(self) -> None:
        self._refresh((QUERY_TABLE,))

    def request_heatmap(self) -> None:
        self._refresh((QUERY_HEATMAP,))

    # 20.02 (additiv): Generische 2D-Heatmap (freie Dimensionen) + OHLCV-
    # Snapshot fuer das Candle-Overlay (E9) – werden on-demand von der
    # HeatmapPage im Generisch-Modus angefordert (kein refresh_all-Pflicht).
    def request_heatmap_generic(self) -> None:
        self._refresh((QUERY_HEATMAP_GENERIC,))

    def request_ohlcv_snapshot(self) -> None:
        self._refresh((QUERY_OHLCV,))

    # 20.02-Bugfix (09.08.2026, Punkt 1+2): Tages-Ohlc fuer das Candle-Overlay
    # im selben Canvas – SQL-seitig aggregiert (deckt den gesamten
    # Heatmap-Zeitraum ab; das HeatmapWidget nutzt diesen Query statt
    # QUERY_OHLCV).
    def request_daily_ohlc(self) -> None:
        self._refresh((QUERY_DAILY_OHLC,))

    def request_scatter(self) -> None:
        self._refresh((QUERY_SCATTER,))

    def request_distribution(self) -> None:
        self._refresh((QUERY_DISTRIBUTION,))

    def request_features(self) -> None:
        self._refresh((QUERY_FEATURES,))

    def refresh_all(self) -> None:
        """Stoesst alle Abfragen neu an (Seiten-/Profilwechsel)."""
        self._refresh((QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                       QUERY_SCATTER, QUERY_DISTRIBUTION, QUERY_FEATURES))

    # ------------------------------------------------------------------
    # Parameter setzen (UI-Pages) – markieren Dirty + feuern betroffen ab
    # ------------------------------------------------------------------
    def set_symbol(self, symbol: str) -> None:
        self._set_param("symbol", str(symbol or ""),
                        (QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                         QUERY_OHLCV, QUERY_SCATTER, QUERY_DISTRIBUTION,
                         QUERY_FEATURES))

    def set_timeframe(self, timeframe: str) -> None:
        self._set_param("timeframe", str(timeframe or "M1"),
                        (QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                         QUERY_OHLCV, QUERY_SCATTER, QUERY_DISTRIBUTION,
                         QUERY_FEATURES))

    # ------------------------------------------------------------------
    # 21.03.12 (MTF-FC auf Analytics): Filterleisten-Parameter
    # ------------------------------------------------------------------
    def set_data_tf(self, data_tf: str) -> None:
        """Setzt die Analysequelle des MtfFilterBarWidget ('multi' | TF).

        'multi'  -> alle Timeframes in EINER Query (`all_timeframes=True`,
                    der `timeframe`-Filter entfaellt im Reader).
        'M15' o.ae. -> Fixiert auf diesen TF: `all_timeframes=False` und der
                    `timeframe`-Filter uebernimmt den fixierten TF (die UI
                    synchronisiert combo_tf daraus).
        """
        data_tf = str(data_tf or "").strip() or "multi"
        if data_tf == "multi":
            if (self._params.get("data_tf") == "multi"
                    and not self._params.get("all_timeframes")):
                self._params["all_timeframes"] = True
                self._mark_dirty()
                self._refresh(_ALL_QUERIES)
            elif self._params.get("data_tf") != "multi":
                self._params["data_tf"] = "multi"
                self._params["all_timeframes"] = True
                self._mark_dirty()
                self._refresh(_ALL_QUERIES)
            return
        # Fixiert auf einen konkreten TF.
        tf = data_tf.upper()
        changed = (self._params.get("data_tf") != tf
                   or self._params.get("timeframe") != tf
                   or self._params.get("all_timeframes"))
        if not changed:
            return
        self._params["data_tf"] = tf
        self._params["all_timeframes"] = False
        self._params["timeframe"] = tf
        self._mark_dirty()
        self._refresh(_ALL_QUERIES)

    def set_agg_tf(self, agg_tf: str) -> None:
        """Setzt den Aggregations-TF (Entscheidung 6a: 'auto' | TF).

        'auto' -> Granularitaet wird dynamisch aus dem Zeitraum abgeleitet
                  (kein Zeit-Bucketing; Verhalten wie bisher).
        'H1' o.ae. -> Die generische Heatmap fasst die date-Achse starr auf
                  diesem TF-Raster zusammen (bucket_tf im Reader).
        """
        agg_tf = str(agg_tf or "").strip().lower() or "auto"
        self._set_param("agg_tf", agg_tf, (QUERY_HEATMAP_GENERIC,))

    def set_sort_mode(self, mode: str) -> None:
        """21.03.14 (Wunsch 2): Speichert die Tabellen-Sortierung.

        `sort_mode` ist 'date' | 'signal' | 'tf' und wird fuer die
        Profil-Persistenz gemerkt (Sektion sources). Reiner UI-Zustand
        (die TablePage wendet die Sortierung ueber den EventBus an) -
        KEIN Query-Refresh, nur Dirty-Markierung (Option B - Explicit
        Save). Idempotent ohne Aenderung.
        """
        mode = str(mode or "").strip().lower()
        if mode not in ("date", "signal", "tf"):
            mode = "date"
        if mode == self._params.get("sort_mode"):
            return
        self._params["sort_mode"] = mode
        self._mark_dirty()

    def set_service_mode(self, mode: str) -> None:
        """21.03.20: Setzt den Modus-Filter (z. B. 'MA_Peak_Hysteresis').

        `"all"` (Default) = kein Filter (alle Modi). Wirkt GLOBAL auf
        alle Analytics-Datenquellen (Entscheidung 1): Tabelle, beide
        Heatmaps, Scatter, Verteilung. `QUERY_FEATURES` wird mitrefreshed,
        damit die dynamische Modus-Liste / das Deaktivierungs-Flag
        (`has_source_mode_services`) synchron zur Auswahl bleibt. Idempotent
        ohne Aenderung (kein Refresh/Dirty).
        """
        mode = str(mode or "all").strip()
        if mode == self._params.get("service_mode"):
            return
        self._params["service_mode"] = mode
        self._mark_dirty()
        self._refresh((QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP,
                       QUERY_HEATMAP_GENERIC, QUERY_SCATTER,
                       QUERY_DISTRIBUTION))

    def set_range(self, from_ts, to_ts, preset: Optional[str] = None) -> None:
        """Setzt den Zeitraum-Filter (optional, bar_time BETWEEN).

        `from_ts`/`to_ts` sind Wanduhr-Epochs (int) oder None (kein Filter).
        `preset` ist der Range-Preset-Name des MtfFilterBarWidget (z. B.
        '7d'/'90d'/'Year', 21.03.15) und wird fuer die Profil-Persistenz
        gemerkt. Alt-Werte 'YTD' (bis 21.03.15) bzw. 'Benutzerdefiniert'
        (entfallenes Custom-Panel) werden auf den neuen Preset-Satz
        abgebildet. Wird vom Range-Picker des MtfFilterBarWidget gesetzt
        (Basis = letzter Datenpunkt statt time.time()).
        """
        f = int(from_ts) if from_ts is not None else None
        t = int(to_ts) if to_ts is not None else None
        preset = str(preset or "").strip() or None
        # 21.03.15 (Bug 3): Alt-Profile mit 'YTD'/'Benutzerdefiniert' auf den
        # neuen Preset-Satz (24h/7d/30d/90d/Year) abbilden.
        if preset == "YTD":
            preset = "Year"
        elif preset == "Benutzerdefiniert":
            preset = "7d"
        if (f == self._params.get("range_from")
                and t == self._params.get("range_to")
                and preset == self._params.get("range_preset")):
            return
        self._params["range_from"] = f
        self._params["range_to"] = t
        self._params["range_preset"] = preset
        self._mark_dirty()
        self._refresh((QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                       QUERY_SCATTER, QUERY_DISTRIBUTION))

    def clear_range(self) -> None:
        """Entfernt den Zeitraum-Filter (kein Zeitfilter mehr)."""
        self.set_range(None, None)

    def latest_data_epoch(self) -> Optional[int]:
        """Neuester Wanduhr-Epoch der Feature-Daten (Range-Referenzpunkt).

        Delegiert lesend an das Repository (`fetch_latest_bar_time` fuer das
        aktuelle Symbol/Timeframe) – der `now_provider` des MtfFilterBarWidget
        rechnet die Presets relativ zum letzten Datenpunkt statt zu
        time.time(). Defensiv: ohne Symbol/Timeframe oder bei Fehler -> None
        (das Widget faellt dann auf time.time() zurueck).
        """
        symbol = str(self._params.get("symbol") or "")
        timeframe = str(self._params.get("timeframe") or "")
        if not symbol or not timeframe:
            return None
        try:
            return self._repo.get_latest_bar_time(symbol, timeframe)
        except Exception:
            return None

    def set_feature_id(self, feature_id: Optional[str]) -> None:
        """Kompatibilitaets-Alias (Legacy): Einzel-ID -> Multi-Liste."""
        self.set_feature_ids([feature_id] if feature_id else [])

    def set_feature_ids(self, feature_ids, instance_hashes=None) -> None:
        """Setzt die Multi-Auswahl der Datenquellen (15.03-E).

        `feature_ids` sind die plugin_ids des Feature-Store (z. B.
        ["srv_grid_lines", "srv_proximity"]); leer = kein Filter (alle Features).
        Typen-/Duplikat-normalisiert; ohne Aenderung wird kein Refresh
        ausgeloest (idempotent, wie set_symbol/set_timeframe).

        Runde 10 (Bug 1): `instance_hashes` schraenkt die gewaehlten
        plugin_ids auf bestimmte Varianten (Clones) ein - None/leer =
        KEINE Varianten-Einschraenkung (alle Varianten der plugin_ids).
        None bedeutet ausserdem: bestehende Hash-Einschraenkung bleibt
        erhalten (z. B. bei reinen feature_ids-Aenderungen durch das
        Feld-Dropdown). Die Hashes fliessen als zusaetzliche
        WHERE-Bedingung in die Reader-Queries
        (`(instance_hash IS NULL OR instance_hash IN (...))`).
        """
        ids = self._normalize_feature_ids(feature_ids)
        hashes_changed = instance_hashes is not None
        if hashes_changed:
            hashes = self._normalize_instance_hashes(instance_hashes)
        else:
            # None = bestehende Einschraenkung beibehalten (kein
            # versehentliches Leeren durch Alt-Aufrufer).
            hashes = self._params.get("instance_hashes") or []
        if (ids == self._params.get("feature_ids")
                and (not hashes_changed
                     or hashes == self._params.get("instance_hashes"))):
            return
        ids_changed = ids != self._params.get("feature_ids")
        self._params["feature_ids"] = ids
        if hashes_changed:
            self._params["instance_hashes"] = hashes
        self._mark_dirty()
        if ids_changed:
            # Runde 8 (Bugfix 4): Die UI leitet ihr 'Feld'-Dropdown
            # SYNCHRON neu ab (kein Query-Round-Trip) - das
            # HeatmapWidget verbindet feature_ids_changed und baut
            # Items/Haken/Current sofort neu. (Nur bei feature_ids-
            # Aenderung; reine Hash-Aenderung laesst das Feld-Dropdown
            # unveraendert.)
            self.feature_ids_changed.emit()
        # Runde 15b (Bugfix Dropdown, User-Meldung 10.08.2026): QUERY_FEATURES
        # gehoert in den Refresh - der leichte Metadaten-Pfad liefert die
        # field_sources/no_data_variants fuer die AKTUELLEN feature_ids +
        # instance_hashes (Feld-Dropdown + NoData-Hinweise). Ohne den
        # Refresh bliebe das Dropdown auf dem Cache-Stand des letzten
        # Payloads (z. B. ein zuvor gefilterter Satz ohne die neu gecheckten
        # Services) - Check/Uncheck waere erst nach einem Seitenwechsel
        # sichtbar. Die Queue-Reihenfolge (QUERY_FEATURES zuerst) spiegelt
        # die Runde-15-Prioritaet: leichtes Dropdown-Update VOR der Grafik.
        self._refresh((QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP,
                       QUERY_HEATMAP_GENERIC, QUERY_SCATTER,
                       QUERY_DISTRIBUTION))

    def set_field_selection(self, field_pairs, update_ids: bool = True) -> None:
        """Setzt die (Service|Parameter)-Auswahl des 'Feld'-Dropdowns.

        12.08.2026 (Option A, Bug 1/2): Die Feld-Auswahl ist eine explizite
        Liste von '{service_id}|{key}'-Paaren (effective pairs) - der
        Reader filtert damit auf PARAMETER-Ebene (field_pairs-WHERE:
        `feature_data->>key IS NOT NULL` je Service). Leere Liste = kein
        Paar-Filter (reines feature_ids-Verhalten wie bisher).

        `update_ids=True` (USER-Interaktion, ServicePicker-Sync): Die
        Services werden aus den Paaren abgeleitet und in `feature_ids`
        uebernommen (Dropdown und Picker bleiben konsistent; Abwaehlen des
        letzten Parameters eines Services entfernt ihn aus dem Picker).

        `update_ids=False` (PROGRAMMATISCHER Sync am Ende des
        Dropdown-Rebuilds): `feature_ids` bleibt UNANGETASTET - der
        ServicePicker ist die Service-Quelle; Services OHNE numerische
        Feld-Keys duerfen dadurch nicht stillschweigend aus der Auswahl
        fallen (nur ihre Paare koennen fehlen).

        Im Gegensatz zu set_feature_ids() wird der Refresh auch bei
        UNVERAENDERTER Service-Menge ausgeloest, wenn sich die Parameter-
        Auswahl geaendert hat. Idempotent ohne Aenderung (kein
        Refresh/Dirty).
        """
        pairs = self._normalize_field_pairs(field_pairs)
        ids = self._pairs_to_feature_ids(pairs)
        current_pairs = self._params.get("field_selection") or []
        current_ids = self._params.get("feature_ids") or []
        pairs_changed = pairs != current_pairs
        ids_changed = update_ids and ids != current_ids
        if not pairs_changed and not ids_changed:
            return
        self._params["field_selection"] = pairs
        if ids_changed:
            self._params["feature_ids"] = ids
        self._mark_dirty()
        if ids_changed:
            # Service-Satz geaendert -> ServicePicker + Feld-Metadaten
            # (QUERY_FEATURES) synchron nachziehen (identisch zu
            # set_feature_ids).
            self.feature_ids_changed.emit()
            self._refresh((QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP,
                       QUERY_HEATMAP_GENERIC, QUERY_SCATTER,
                       QUERY_DISTRIBUTION))
        else:
            # NUR die Parameter-Auswahl hat sich geaendert -> nur die
            # generische Heatmap neu aggregieren (Bug 1: An/Abwaehlen
            # eines Parameters muss die Grafik aendern).
            self._refresh((QUERY_HEATMAP_GENERIC,))

    @staticmethod
    def _normalize_field_pairs(value) -> List[str]:
        """Normalisiert '{service_id}|{key}'-Paare (dedupliziert, getrimmt).

        12.08.2026 (Option A): Eintraege ohne `|` oder mit leerer Service-/
        Key-Seite werden verworfen. Die Keys bleiben case-sensitiv (JSON-
        Keys aus den Service-Payloads), die Service-ID wird getrimmt.
        """
        if not value:
            return []
        out: List[str] = []
        for v in value:
            s = str(v).strip()
            if not s or "|" not in s:
                continue
            sid, key = s.split("|", 1)
            sid = sid.strip()
            key = key.strip()
            if sid and key and f"{sid}|{key}" not in out:
                out.append(f"{sid}|{key}")
        return out

    @staticmethod
    def _pairs_to_feature_ids(pairs) -> List[str]:
        """Leitet die aktiven Service-IDs aus '{service_id}|{key}'-Paaren ab.

        12.08.2026 (Option A): Dedupliziert in Paar-Reihenfolge (die
        Feld-Dropdown-Item-Reihenfolge bestimmt die ServicePicker-Reihenfolge
        - konsistent zu _checked_field_service_ids()).
        """
        out: List[str] = []
        for p in pairs or []:
            s = str(p or "")
            if "|" not in s:
                continue
            sid = s.split("|", 1)[0].strip()
            if sid and sid not in out:
                out.append(sid)
        return out

    @staticmethod
    def _normalize_feature_ids(value) -> List[str]:
        """Normalisiert feature_ids (Liste[str], dedupliziert, getrimmt)."""
        if not value:
            return []
        out: List[str] = []
        for v in value:
            s = str(v).strip()
            if s and s not in out:
                out.append(s)
        return out

    @staticmethod
    def _normalize_instance_hashes(value) -> List[str]:
        """Normalisiert instance_hashes (Liste[str], dedupliziert,
        getrimmt) - Runde 10 (Bug 1, Varianten-Einschraenkung)."""
        if not value:
            return []
        out: List[str] = []
        for v in value:
            s = str(v).strip()
            if s and s not in out:
                out.append(s)
        return out

    def _resolve_feature_ids(
        self, feature_ids: List[str]
    ) -> Tuple[List[str], List[str]]:
        """Isoliert fehlende Services ueber den Resolver (20.01, E5).

        Ohne ein injiziertes Modell (Tests/Alt-Aufrufer) wird ein lazies
        Default-Modell erzeugt (nur wenn ueberhaupt IDs zu pruefen sind).
        Fehler -> (normalisierte ids, []) defensiv (kein Absturz).
        """
        ids = self._normalize_feature_ids(feature_ids)
        if not ids:
            return [], []
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            return model.resolve_valid_feature_ids(ids)
        except Exception:
            return ids, []

    @staticmethod
    def _flatten_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Flacht v2-Sections (sources/charts/table/styling) auf Top-Level ab.

        20.01 (E2/E3): Der ViewModel arbeitet weiterhin mit flachen `_params` –
        die v2-Sektions-Keys haben Vorrang vor gleichnamigen Top-Level-Resten
        (die bei der v1→v2-Migration verlustfrei erhalten bleiben).
        """
        flat: Dict[str, Any] = {}
        for section in ("sources", "charts", "table", "styling"):
            values = payload.get(section)
            if isinstance(values, dict):
                flat.update(values)
        for key, value in payload.items():
            if key in ("schema_version", "sources", "charts", "table",
                       "styling"):
                continue
            if key not in flat:
                flat[key] = value
        return flat

    def set_heatmap_metric(self, metric: str) -> None:
        self._set_param("heatmap_metric", str(metric or "count"),
                        (QUERY_HEATMAP,))

    # ------------------------------------------------------------------
    # 20.02: Generische 2D-Heatmap – Konfiguration/Zoom/Overlay (additiv)
    # ------------------------------------------------------------------
    def set_heatmap_config(
        self, x_dim: str, y_dim: str, field: str, agg: str
    ) -> None:
        """Setzt die Konfiguration der generischen Heatmap (20.02, E1).

        x_dim/y_dim aus DIM_MAPPINGS (case-insensitiv), `agg` eine der
        HEATMAP_AGGREGATIONS, `field` der numerische feature_data-JSON-Key
        (E6: nur bei AVG/SUM/MIN/MAX relevant; COUNT/CONFLUENCE_COUNT
        ignorieren ihn). 20.02.01 (E6): `dow_hour` wird per Sanitizer auf
        "hour" abgebildet. Ohne Aenderung idempotent (kein Refresh).
        """
        x_dim = self._sanitize_dim(x_dim or "date")
        y_dim = self._sanitize_dim(y_dim or "hour")
        agg = str(agg or "confluence_count").lower()
        field = str(field or "")
        changed = (x_dim != self._params.get("heatmap_x_dim")
                   or y_dim != self._params.get("heatmap_y_dim")
                   or agg != self._params.get("heatmap_agg")
                   or field != self._params.get("heatmap_field"))
        if not changed:
            return
        self._params["heatmap_x_dim"] = x_dim
        self._params["heatmap_y_dim"] = y_dim
        self._params["heatmap_agg"] = agg
        self._params["heatmap_field"] = field
        self._mark_dirty()
        self._refresh((QUERY_HEATMAP_GENERIC,))

    # ------------------------------------------------------------------
    # 21.01: Smart-Presets (E4, 11.08.2026)
    # ------------------------------------------------------------------
    def _set_heatmap_all_timeframes(self, enabled: bool) -> None:
        """Setzt die TF-Freigabe der generischen Heatmap (21.01, E1).

        Idempotent ohne Aenderung; Dirty-Flag + Refresh nur bei echtem
        Wechsel (Muster set_heatmap_config).
        """
        enabled = bool(enabled)
        if enabled == self._params.get("heatmap_all_timeframes"):
            return
        self._params["heatmap_all_timeframes"] = enabled
        self._mark_dirty()
        self._refresh((QUERY_HEATMAP_GENERIC,))

    def apply_smart_preset_confluence(self) -> None:
        """`[⚡ Signal-Confluence]`: X=date, Y=service_id, count(DISTINCT fid).

        Chronologische Lichtsaeulen zeitgleicher Signale (Hauptansicht).
        Konfiguration + Dirty-Flag (Option B), KEIN Auto-Save (E4).
        """
        self._set_heatmap_all_timeframes(False)
        self.set_heatmap_config("date", "service_id", "", "confluence_count")

    def apply_smart_preset_session(self) -> None:
        """`[🕒 Session-Hotspots]`: X=dow (Mo-Fr), Y=hour, count(DISTINCT fid).

        Tageszeit-/Wochentag-Muster im Handelsverlauf (Wanduhr, E5-Phase 20).
        Konfiguration + Dirty-Flag (Option B), KEIN Auto-Save (E4).
        """
        self._set_heatmap_all_timeframes(False)
        self.set_heatmap_config("dow", "hour", "", "confluence_count")

    def apply_smart_preset_intensity(self, x_dim: str = "date") -> None:
        """`[📏 Wert-Intensität]`: X=date (Standard) oder dow (E2), Y=hour.

        Auspraegung von Messwerten (z. B. distance_pip, atr) – AVG/Max ueber
        den ersten verfuegbaren numerischen feature_data-JSON-Key (Repo-
        Fallback, wenn keiner existiert). `x_dim` akzeptiert "date" (Default)
        oder "dow" (E2). Konfiguration + Dirty-Flag (Option B), KEIN
        Auto-Save (E4).
        """
        x_key = "dow" if str(x_dim or "").strip().lower() == "dow" else "date"
        # Erster verfuegbarer numerischer Key (Muster Repo-E6-Fallback) –
        # bei leeren Daten bleibt field="" (Repo faellt defensiv zurueck).
        try:
            avail = self._repo.available_feature_columns(
                str(self._params.get("symbol") or ""),
                str(self._params.get("timeframe") or "M1"))
            field = avail[0] if avail else ""
        except Exception:
            field = ""
        self._set_heatmap_all_timeframes(False)
        self.set_heatmap_config(x_key, "hour", field, "avg")

    def apply_smart_preset_timeframe(self) -> None:
        """`[📊 Service-Timeframe]`: X=timeframe (ALLE TFs), Y=service_id.

        Verteilung der Services ueber Zeitebenen (E1: `all_timeframes=True`
        entfaellt die TF-WHERE-Bedingung – alle M1..D1 in EINER Query).
        Konfiguration + Dirty-Flag (Option B), KEIN Auto-Save (E4).
        """
        self._set_heatmap_all_timeframes(True)
        self.set_heatmap_config("timeframe", "service_id", "", "count")

    # ------------------------------------------------------------------
    # 21.01 (E3): Auto-Namensgenerator fuer neue Profile (DEUTSCH)
    # ------------------------------------------------------------------
    def generate_profile_name_suggestion(self) -> str:
        """Sprechender Profilname – Formel `[Symbol] [TF] - [Modus] ([Kontext])`.

        E3 (11.08.2026): Sprache DEUTSCH, z. B.
        `SILVER M1 - Confluence Zeitachse (3 Services)`.
        * Kontext-Klammer = Anzahl der selektierten Services (feature_ids);
          bei 0 Auswahlen `(Alle Services)` statt `(0 Services)`.
        * Fehlendes Symbol/Timeframe -> Platzhalter `ALLE`
          (z. B. `ALLE M1 - Confluence Zeitachse (3 Services)`).
        * Modus-Ableitung aus der AKTUELLEN Heatmap-Konfiguration
          (Confluence/Session/Intensitaet/TF-Matrix) – der Vorschlag passt
          zum eingestellten Ansichts-Szenario.
        """
        symbol = str(self._params.get("symbol") or "").strip() or "ALLE"
        timeframe = str(self._params.get("timeframe") or "").strip() or "ALLE"
        x_dim = str(self._params.get("heatmap_x_dim") or "").lower()
        y_dim = str(self._params.get("heatmap_y_dim") or "").lower()
        agg = str(self._params.get("heatmap_agg") or "").lower()
        if x_dim == "timeframe":
            mode = "Service-Zeitebenen"
        elif x_dim == "dow" and y_dim == "hour":
            mode = "Session-Hotspots"
        elif agg in ("avg", "sum", "min", "max"):
            mode = "Wert-Intensität"
        else:
            mode = "Confluence Zeitachse"
        n = len(self._params.get("feature_ids") or [])
        context = f"{n} Services" if n > 0 else "Alle Services"
        return f"{symbol} {timeframe} - {mode} ({context})"

    def set_heatmap_zoom(self, x_range, y_range) -> None:
        """Setzt die normalisierten Viewport-Anteile [0,1] (20.02, E8).

        Rein client-seitig (die UI wendet die Bereiche direkt per
        setXRange/setYRange an) – KEIN DB-Requery. Die Werte werden geclampt
        (0 ≤ lo < hi ≤ 1) und fuer die Persistenz (Profil/Workspace)
        markiert (Option B – Explicit Save).
        """
        x_clamped = self._clamp_zoom(x_range)
        y_clamped = self._clamp_zoom(y_range)
        if (x_clamped == self._params.get("zoom_x_range")
                and y_clamped == self._params.get("zoom_y_range")):
            return
        self._params["zoom_x_range"] = x_clamped
        self._params["zoom_y_range"] = y_clamped
        self._mark_dirty()

    def set_candle_projection(self, enabled: bool) -> None:
        """Schaltet das Candle-Overlay (Preis-Strip) an/aus (20.02, E9).

        Reiner UI-Zustand ohne DB-Abfrage (der OHLCV-Snapshot wird von der
        HeatmapPage on-demand angefordert); nur Dirty-Markierung fuer die
        Profil-Persistenz.
        """
        enabled = bool(enabled)
        if enabled == self._params.get("candle_projection_enabled"):
            return
        self._params["candle_projection_enabled"] = enabled
        self._mark_dirty()

    @staticmethod
    def _clamp_zoom(value) -> List[float]:
        """Clampt einen Zoom-Bereich auf [0.0, 1.0] mit lo < hi (E8)."""
        try:
            lo, hi = float(value[0]), float(value[1])
        except (TypeError, ValueError, IndexError):
            return [0.0, 1.0]
        lo = max(0.0, min(1.0, lo))
        hi = max(0.0, min(1.0, hi))
        return [lo, hi] if hi > lo else [0.0, 1.0]

    @staticmethod
    def _sanitize_dim(value) -> str:
        """Bereinigt eine Heatmap-Dimension (20.02.01, E6).

        `dow_hour` ist ersatzlos aus DIM_MAPPINGS/HEATMAP_DIMENSIONS entfernt.
        Alt-Profil-/Workspace-/Config-Werte mit `dow_hour` werden auf die
        gueltige Dimension "hour" (Tageszeit) abgebildet – sonst wuerde
        `_set_combo_data` (additives Hinzufuegen unbekannter Werte) die
        entfernte Dimension wieder in die UI-Combos aufnehmen.
        """
        dim = str(value or "").lower()
        return "hour" if dim == "dow_hour" else dim

    def set_scatter_columns(self, x_column: str, y_column: str) -> None:
        # 19.02 (Cleanup): Leere Werte = Repo-Default (erste numerische
        # feature_data-JSON-Keys). Keine Legacy-Spalten-Fallbacks mehr.
        self._set_param("scatter_x", str(x_column or ""),
                        (QUERY_SCATTER,))
        self._set_param("scatter_y", str(y_column or ""),
                        (QUERY_SCATTER,))

    def set_distribution_column(self, column: str) -> None:
        self._set_param("distribution_column",
                        str(column or ""),
                        (QUERY_DISTRIBUTION,))

    def set_bins(self, bins: int) -> None:
        new_bins = self._clamp_bins(bins)
        if new_bins != self._params["bins"]:
            self._params["bins"] = new_bins
            self._mark_dirty()
            self._refresh((QUERY_DISTRIBUTION,))

    def set_limit(self, limit: int) -> None:
        new_limit = self._clamp_limit(limit)
        if new_limit != self._params["limit"]:
            self._params["limit"] = new_limit
            self._mark_dirty()
            self._refresh((QUERY_TABLE, QUERY_SCATTER, QUERY_DISTRIBUTION))

    def set_table_settings(
        self,
        widths: Optional[Dict[str, Any]] = None,
        row_height: int = 0,
        sort_column: int = 0,
        sort_order: int = 1,
    ) -> None:
        """Uebernimmt TablePage-Settings (19.03 E6, ohne Query-Refresh).

        Spaltenbreiten {Spaltenname: Breite} (E5), **globale Zeilenhoehe**
        (E9/19.06: ein Wert fuer die GESAMTE Tabelle – das Ziehen einer
        Zeile setzt alle Zeilen live auf diese Hoehe), Sortier-Spalte und
        -Richtung (E8). Reine UI-Zustaende der TablePage: KEIN `_refresh`/
        Debounce/Worker und keine DB-Abfrage – nur die Dirty-Markierung fuer
        die Profil-Persistenz (Option B – Explicit Save). Typ-/Werte-
        normalisiert; ohne tatsaechliche Aenderung idempotent (kein
        unnötiges Dirty-Flag bei Drag-Ereignissen).
        """
        norm_widths: Dict[str, int] = {}
        for k, v in (widths or {}).items():
            try:
                w = int(v)
            except (TypeError, ValueError):
                continue
            if w > 0:
                norm_widths[str(k)] = w
        try:
            rh = max(0, int(row_height))
        except (TypeError, ValueError):
            rh = 0
        try:
            sc = max(0, int(sort_column))
        except (TypeError, ValueError):
            sc = 0
        try:
            so_raw = int(sort_order)
        except (TypeError, ValueError):
            so_raw = 1
        so = so_raw if so_raw in (0, 1) else 1

        if (norm_widths == self._params.get("table_column_widths")
                and rh == self._params.get("table_row_height")
                and sc == self._params.get("table_sort_column")
                and so == self._params.get("table_sort_order")):
            return
        self._params["table_column_widths"] = norm_widths
        self._params["table_row_height"] = rh
        self._params["table_sort_column"] = sc
        self._params["table_sort_order"] = so
        self._mark_dirty()

    def _set_param(self, key: str, value: Any, kinds: Iterable[str]) -> None:
        if self._params.get(key) == value:
            return
        self._params[key] = value
        self._mark_dirty()
        self._refresh(kinds)

    # ------------------------------------------------------------------
    # Interna: Debounce + Worker-Verwaltung
    # ------------------------------------------------------------------
    def _refresh(self, kinds: Iterable[str]) -> None:
        for kind in kinds:
            if kind not in self._pending_kinds:
                self._pending_kinds.append(kind)
        self._debounce.start()

    def _start_next_query(self) -> None:
        """Startet die naechste gepufferte Abfrage (Debounce-Timeout)."""
        if self._worker is not None and self._worker.isRunning():
            return  # laufender Worker uebernimmt; Puffer bleibt gefuellt
        while self._pending_kinds:
            kind = self._pending_kinds.pop(0)
            params = self._current_params(kind)
            if params is None:
                continue  # kein Symbol/Timeframe -> Abfrage ueberspringen
            self._launch(kind, params)
            return
        self.busy_changed.emit(False)

    def _launch(self, kind: str, params: Dict[str, Any]) -> None:
        worker = AnalyticsAsyncWorker(self._repo, kind, params, parent=self)
        self._worker = worker
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        self.busy_changed.emit(True)
        worker.start()

    def _on_finished(self, worker, kind: str, result: Dict[str, Any]) -> None:
        """Verarbeitet das Ergebnis eines Workers – NUR des aktuellen.

        Fix 15.03 (Haenger bei TF-Wechsel): Race-Condition, bei der ein
        veralteter Worker (Thread bereits beendet, finished_ok noch nicht
        zugestellt, waehrend der Debounce bereits einen neuen Worker startet)
        den self._worker-Verweis ueberschrieb und mehrere Worker parallel
        liefen. Der Guard `self._worker is worker` verwirft verspaetete
        Ergebnisse veralteter Worker; nur der zuletzt gestartete Worker darf
        weiterverarbeiten.
        """
        if self._worker is not worker:
            return
        self._worker = None
        self.data_ready.emit(kind, result)
        self._start_next_query()

    def _on_failed(self, worker, kind: str, error: str) -> None:
        """Verarbeitet einen Worker-Fehler – NUR des aktuellen (Race-Guard).

        Siehe _on_finished: Verspaetete Fehler veralteter Worker werden
        verworfen, damit der laufende/naechste Worker nicht gestoert wird.
        """
        if self._worker is not worker:
            return
        self._worker = None
        self.query_failed.emit(kind, error)
        self._start_next_query()

    def _current_params(self, kind: str) -> Optional[Dict[str, Any]]:
        """Baut die Abfrageparameter fuer einen query_kind (oder None)."""
        p = self._params
        if not p.get("symbol") or not p.get("timeframe"):
            return None
        base: Dict[str, Any] = {
            "symbol": p["symbol"],
            "timeframe": p["timeframe"],
            "feature_ids": p["feature_ids"],
            # Runde 10 (Bug 1): Varianten-Einschraenkung in die
            # Query-Params (leer = alle Varianten der feature_ids).
            "instance_hashes": p.get("instance_hashes") or [],
            # Runde 8 (Bugfix 3): Generation in die Worker-Params - der
            # Worker spiegelt sie ins Ergebnis-Dict, die UI erkennt damit
            # Stale-Payloads (Queries vor dem letzten Restore).
            "restore_generation": self._restore_generation,
            # 21.03.12 (MTF-FC auf Analytics): Optionaler Zeitfilter
            # (Wanduhr-Epochs relativ zum letzten Datenpunkt; None = alle).
            "from_ts": p.get("range_from"),
            "to_ts": p.get("range_to"),
            # 21.03.20 (Analytics Modus-Filter): source_mode-Filter
            # (GLOBAL - alle Query-Kinds, Entscheidung 1).
            "service_mode": p.get("service_mode", "all"),
        }
        if kind == QUERY_TABLE:
            base["limit"] = p["limit"]
        elif kind == QUERY_HEATMAP:
            base["metric"] = p["heatmap_metric"]
        elif kind == QUERY_HEATMAP_GENERIC:
            # 20.02: Generische 2D-Heatmap – Konfiguration aus den heatmap_*-
            # _params. 20.02-Bugfix (09.08.2026, Punkt 2): KEIN limit-Lookback
            # mehr (limit=None => ALLE verfuegbaren Daten; der Pivot-Deckel
            # MAX_HEATMAP_CELLS im Reader begrenzt die Matrix). Vorher schnitt
            # der 5000er-Lookback die Heatmap auf die letzten ~4 Tage (M1) ab.
            base["x_dim"] = p["heatmap_x_dim"]
            base["y_dim"] = p["heatmap_y_dim"]
            base["field"] = p.get("heatmap_field") or None
            base["agg"] = p["heatmap_agg"]
            # 12.08.2026 (Option A, Bug 1/2): Explizite (Service|Parameter)-
            # Auswahl des 'Feld'-Dropdowns -> der Reader filtert auf
            # PARAMETER-Ebene (feature_data-JSON-Keys je Service). Leer =
            # kein Paar-Filter (verhalten wie bisher, reiner feature_ids-
            # Filter). Wird in set_field_selection() gepflegt.
            base["field_selection"] = p.get("field_selection") or []
            # 21.01 (E1): TF-Freigabe in die Worker-Params – True entfaellt
            # im Reader die TF-WHERE-Bedingung (Preset `[📊 Service-Timeframe]`).
            # 21.03.12: OR-verknuepft mit `all_timeframes` (data_tf='multi' -
            # Analysequelle des MtfFilterBarWidget uebernimmt die Freigabe).
            base["all_timeframes"] = bool(
                p.get("heatmap_all_timeframes", False)
                or p.get("all_timeframes", False))
            # 21.03.12 (Entscheidung 6a): agg_tf -> bucket_tf fuer das
            # date-Raster der generischen Heatmap ('auto'/leer = kein
            # Bucketing, dynamische Granularitaet wie bisher).
            _agg_tf = str(p.get("agg_tf") or "auto").strip().lower()
            base["bucket_tf"] = None if _agg_tf in ("", "auto") else _agg_tf
            # Runde 12 (Option A): Preset-Modell-Snapshot fuer die
            # No-Data-Auswertung IM SELBEN Datenfluss wie die Grafik
            # (kein zweiter serieller QUERY_FEATURES-Worker-Roundtrip -
            # das Dropdown aktualisiert sich mit/knapp nach der Grafik
            # statt erst danach). Der Snapshot ist in-memory (kein DB).
            base["presets_data"] = self._no_data_presets_snapshot()
        elif kind == QUERY_OHLCV:
            # 20.02 (E9): OHLCV-Snapshot – limit=None => Reader-Default
            # (OHLCV_SNAPSHOT_LIMIT); kein feature_ids-Filter noetig.
            pass
        elif kind == QUERY_DAILY_OHLC:
            # 20.02-Bugfix (09.08.2026): Tages-Ohlc fuer das Candle-Overlay –
            # max_days=None => Reader-Default DAILY_OHLC_MAX_DAYS (4000 Tage,
            # deckt den gesamten Heatmap-Zeitraum).
            pass
        elif kind == QUERY_SCATTER:
            base["x_column"] = p["scatter_x"]
            base["y_column"] = p["scatter_y"]
            base["limit"] = p["limit"]
        elif kind == QUERY_DISTRIBUTION:
            base["column"] = p["distribution_column"]
            base["bins"] = p["bins"]
            base["limit"] = p["limit"]
        elif kind == QUERY_FEATURES:
            # Runde 11 (Bug 4, B4-1): Preset-Modell-Snapshot fuer die
            # No-Data-Auswertung im QUERY_FEATURES-Worker (kein synchroner
            # DB-Zugriff im UI-Hauptthread). Der Worker/Repo berechnet
            # `no_data_variants` als Payload-Attribut (B4-2).
            base["presets_data"] = self._no_data_presets_snapshot()
        return base

    # ------------------------------------------------------------------
    # Dirty-Flag (Option B – Explicit Save)
    # ------------------------------------------------------------------
    def _mark_dirty(self) -> None:
        """Nur bei vorhandenem aktivem Profil (sonst nichts zu speichern)."""
        if not self._dirty and self._active_profile is not None:
            self._dirty = True
            self.dirty_changed.emit(True)

    # ------------------------------------------------------------------
    # Profil-Verwaltung (CRUD + aktives Profil)
    # ------------------------------------------------------------------
    def load_profiles(self) -> None:
        """Laedt die Profil-Liste und wendet das aktive Profil an."""
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        active = self._profile_repo.get_active_profile()
        if active is not None:
            self._apply_profile(active, mark_dirty=False)
        elif self._active_profile is not None:
            self._active_profile = None
            self._dirty = False
            self.dirty_changed.emit(False)
            self.active_profile_changed.emit(None)

    def create_profile(
        self, name: str, description: str = ""
    ) -> Optional[str]:
        """Legt ein neues Profil mit den aktuellen Parametern an.

        Das neue Profil wird sofort aktiv (genau EIN aktives Profil).
        Raises ValueError bei doppeltem Namen.
        """
        name = (name or "").strip()
        if not name:
            return None
        if self._profile_repo.get_profile_by_name(name) is not None:
            raise ValueError(f"Profil '{name}' existiert bereits.")
        profile_id = self._profile_repo.create_profile(
            name, self._current_payload(), description
        )
        self._profile_repo.set_active(profile_id)
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        self._active_profile = self._profile_repo.get_profile(profile_id)
        self._dirty = False
        self.dirty_changed.emit(False)
        self.active_profile_changed.emit(dict(self._active_profile))
        self._emit_profile_changed(self._active_profile["name"])
        return profile_id

    def save_profile(self) -> bool:
        """Persistiert die aktuellen Parameter im aktiven Profil (Save).

        Returns:
            True, wenn ein aktives Profil existierte und gespeichert wurde.
        """
        if self._active_profile is None:
            return False
        profile_id = self._active_profile["profile_id"]
        ok = self._profile_repo.update_profile(
            profile_id, payload=self._current_payload()
        )
        if ok:
            self._active_profile = self._profile_repo.get_profile(profile_id)
            self._dirty = False
            self.dirty_changed.emit(False)
            self.profile_saved.emit(profile_id)
            self._emit_profile_changed(self._active_profile["name"])
        return ok

    def update_profile(
        self,
        profile_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Aktualisiert Name/Beschreibung eines Profils (additiv)."""
        ok = self._profile_repo.update_profile(
            profile_id, name=name, description=description
        )
        if ok:
            self._profiles = self._profile_repo.list_profiles()
            self.profiles_available.emit([dict(p) for p in self._profiles])
            if (self._active_profile is not None
                    and self._active_profile["profile_id"] == profile_id):
                self._active_profile = self._profile_repo.get_profile(profile_id)
                self.active_profile_changed.emit(dict(self._active_profile))
                self._emit_profile_changed(self._active_profile["name"])
        return ok

    def delete_profile(self, profile_id: str) -> bool:
        """Loescht ein Profil (hart). Aktives Profil wird zurueckgesetzt."""
        ok = self._profile_repo.delete_profile(profile_id)
        if not ok:
            return False
        was_active = (self._active_profile is not None
                      and self._active_profile["profile_id"] == profile_id)
        if was_active:
            self._active_profile = None
            self._dirty = False
            self.dirty_changed.emit(False)
            self.active_profile_changed.emit(None)
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        self.profile_deleted.emit(profile_id)
        return True

    def set_active_profile(self, profile_id: str) -> bool:
        """Setzt ein Profil als aktiv und wendet dessen Parameter an."""
        profile = self._profile_repo.get_profile(profile_id)
        if profile is None:
            return False
        self._profile_repo.set_active(profile_id)
        self._apply_profile(profile, mark_dirty=False)
        self.active_profile_changed.emit(dict(profile))
        self._emit_profile_changed(profile["name"])
        return True

    def _apply_profile(
        self, profile: Dict[str, Any], mark_dirty: bool = True
    ) -> None:
        """Uebernimmt die Profil-Parameter in die Ansicht (Explicit Save).

        20.01 (E2/E3/E5): Das Repository liefert beim Lesen bereits migrierte
        v2-Sectioned-Payloads – die flachen Sektionen werden hier auf die
        flachen `_params` abgebildet (keine VM-eigene Migration, Single
        Source of Truth im Repository). Fehlende Services (entfernte/
        umbenannte Plugins) werden per ServiceSelectorModel isoliert und via
        `missing_services_detected` gemeldet; die validen IDs werden DIREKT
        in `_params` geschrieben (kein `set_feature_ids`: kein Dirty-Flag,
        kein Doppel-Refresh, B4).
        """
        self._active_profile = dict(profile)
        payload = profile.get("payload") or {}
        flat = self._flatten_payload(payload)
        # 10.08.2026 (Punkte 3/4): UI-Layout (page_index/heatmap_mode) aus
        # dem Profil-Payload uebernehmen - die UI liest es ueber
        # workspace_layout (identischer Pfad wie restore_workspace).
        layout = payload.get("layout")
        if isinstance(layout, dict):
            self._workspace_layout.update(dict(layout))
        # Runde 11 (Bug 3, B3-2): Gemeinsamer Restore-Helper (Replace-
        # Semantik inkl. instance_hashes -> garantiert leer bei fehlendem
        # Payload-Key statt des alten Werts).
        self._restore_params_from_payload(flat)
        # 15.03-E (Profil-Migration): Alt-Payloads speicherten den Filter als
        # Einzelwert `feature_id` (String) – in `feature_ids` (Liste) wandeln.
        if "feature_ids" not in flat and flat.get("feature_id"):
            self._params["feature_ids"] = self._normalize_feature_ids(
                [flat["feature_id"]])
        # 20.02 (Luecke 5.3-6): `charts.heatmap` ist ein VERSCHACHTELTES Dict –
        # _flatten_payload() bildet es NICHT auf flache _params ab. Explizit
        # aufloesen (E3: additiv, kein Schema-Bump auf v2.1).
        self._apply_heatmap_section(flat.get("heatmap"))
        # 20.02.01 (E6): Alt-Payloads mit `dow_hour` (flach ODER via
        # charts.heatmap) auf die gueltige Dimension "hour" abbilden.
        for _hk in ("heatmap_x_dim", "heatmap_y_dim"):
            if self._params.get(_hk) == "dow_hour":
                self._params[_hk] = "hour"
        self._params["feature_ids"] = self._normalize_feature_ids(
            self._params.get("feature_ids"))
        # Runde 10 (Bug 1): instance_hashes genauso normalisieren.
        self._params["instance_hashes"] = self._normalize_instance_hashes(
            self._params.get("instance_hashes"))
        # 12.08.2026 (Option A): (Service|Parameter)-Auswahl des
        # 'Feld'-Dropdowns genauso normalisieren (Alt-Payloads ohne den
        # Key -> leer = kein Paar-Filter, Verhalten wie bisher).
        self._params["field_selection"] = self._normalize_field_pairs(
            self._params.get("field_selection"))
        # 20.01 (E5) + Runde 9 (Bug 1): Fehlende Services NUR melden -
        # die IDs bleiben im Filter (kein stilles Kuerzen des restaurierten
        # Filters; die DB liefert fuer unbekannte IDs keine Zeilen).
        if self._params["feature_ids"]:
            _, missing = self._resolve_feature_ids(self._params["feature_ids"])
            if missing:
                self.missing_services_detected.emit(list(missing))
        self._params["bins"] = self._clamp_bins(self._params.get("bins"))
        self._params["limit"] = self._clamp_limit(self._params.get("limit"))
        if not mark_dirty:
            self._dirty = False
            self.dirty_changed.emit(False)
        # Runde 8 (Bugfix 3): Generation erhoehen - die UI verwirft
        # Stale-Payloads aelterer Generation (Queries, die VOR diesem
        # Profilwechsel gestartet wurden).
        self._restore_generation += 1
        # Runde 10 (Bug 4): REIHENFOLGE - erst die UI-Combos synchronisieren
        # (params_restored), DANN die Daten anfordern. Runde 11 (A1): KEIN
        # refresh_all() mehr im Restore-Pfad - das AnalyticsWindow
        # orchestriert die Queries zentral (A6: Sync -> Query-Key-Pruefung
        # -> request_data). Ein expliziter User-Refresh (Button) darf
        # weiterhin refresh_all() nutzen.
        self.params_restored.emit()

    def _apply_heatmap_section(self, heat: Any) -> None:
        """Loest die verschachtelte `charts.heatmap`-Sektion auf (20.02).

        Luecke 5.3-6: `_flatten_payload()` bildet das verschachtelte Dict
        nicht auf die flachen `_params`-Keys ab – dieser Helfer uebernimmt
        die 20.02-Keys additiv (nur vorhandene/gueltige Werte; None bleibt
        unveraendert). Zoom-Bereiche werden geclampt (E8).
        """
        if not isinstance(heat, dict):
            return
        if heat.get("x_dim") is not None:
            self._params["heatmap_x_dim"] = self._sanitize_dim(heat["x_dim"])
        if heat.get("y_dim") is not None:
            self._params["heatmap_y_dim"] = self._sanitize_dim(heat["y_dim"])
        if heat.get("agg") is not None:
            self._params["heatmap_agg"] = str(heat["agg"]).lower()
        if heat.get("field") is not None:
            self._params["heatmap_field"] = str(heat["field"])
        # 21.01 (E1): TF-Freigabe aus dem Payload restaurieren.
        if heat.get("all_timeframes") is not None:
            self._params["heatmap_all_timeframes"] = bool(
                heat["all_timeframes"])
        if heat.get("candle_projection_enabled") is not None:
            self._params["candle_projection_enabled"] = bool(
                heat["candle_projection_enabled"])
        if isinstance(heat.get("zoom_x_range"), (list, tuple)):
            self._params["zoom_x_range"] = self._clamp_zoom(
                heat["zoom_x_range"])
        if isinstance(heat.get("zoom_y_range"), (list, tuple)):
            self._params["zoom_y_range"] = self._clamp_zoom(
                heat["zoom_y_range"])

    def _restore_params_from_payload(self, flat: Dict[str, Any]) -> None:
        """Uebernimmt flache Payload-Params per Replace-Semantik (B3-2).

        Runde 11 (Bug 3, B3-2): Gemeinsamer Restore-Pfad fuer
        `_apply_profile()` und `restore_workspace()`. Bekannte `_params`-Keys
        werden UEBERSCHRIEBEN, sofern der Payload einen nicht-None-Wert
        liefert (additiv, wie bisher). Der Varianten-Filter `instance_hashes`
        folgt echter Replace-Semantik: Fehlt der Key im Payload (Alt-Payloads
        ohne Varianten-Angabe), ist er garantiert leer ([]) statt des
        vorherigen Werts - ein gespeicherter Zustand OHNE Varianten-Ein-
        schraenkung darf nicht stillschweigend den alten Filter uebernehmen.
        Andere Keys (z. B. heatmap-Konfiguration, table-Settings) werden
        NICHT generell geleert - nur vorhandene Payload-Werte zaehlen
        (additiv, kein Datenverlust).
        """
        for key in list(self._params.keys()):
            if key in flat and flat[key] is not None:
                self._params[key] = flat[key]
        if "instance_hashes" not in flat or not flat.get("instance_hashes"):
            self._params["instance_hashes"] = []
        # 21.03.15 (Bug 3): Alt-Profile mit 'YTD'/'Benutzerdefiniert' auf den
        # neuen Range-Preset-Satz abbilden (das Custom-Panel ist entfallen).
        _preset = str(self._params.get("range_preset") or "").strip() or None
        if _preset == "YTD":
            self._params["range_preset"] = "Year"
        elif _preset == "Benutzerdefiniert":
            self._params["range_preset"] = "7d"

    def set_ui_layout(self, layout: Optional[Dict[str, Any]] = None) -> None:
        """Uebernimmt das aktuelle UI-Layout fuer die Profil-Persistenz.

        10.08.2026 (Punkte 3/4): Der ViewModel kennt keine UI-Widgets
        (MVVM-Invariante 4) - das AnalyticsWindow uebergibt page_index und
        heatmap_mode vor jedem save_profile()/create_profile(); die Werte
        wandern ueber _current_payload() (Sektion "layout") in den
        Profil-Payload und werden beim _apply_profile() in
        _workspace_layout restauriert (die UI liest sie dort ueber
        workspace_layout).
        """
        self._ui_layout = dict(layout or {})

    def _current_payload(self) -> Dict[str, Any]:
        """Profil-Payload aus den aktuellen Ansichtsparametern (v2, sectioned).

        20.01 (E3): Die v2-Sektionen sources/charts/table/styling gruppieren
        die bekannten Parameter; neue UI-Settings lassen sich spaeter additiv
        unter neuen Sektionen ergaenzen (kein Schema-Bump noetig).
        """
        p = self._params
        return {
            "schema_version": SCHEMA_VERSION_DEFAULT,
            "sources": {
                "symbol": p.get("symbol"),
                "timeframe": p.get("timeframe"),
                "feature_ids": list(p.get("feature_ids") or []),
                # Runde 11 (Bug 3, B3-1): Varianten-Einschraenkung im
                # Profil-Payload persistieren (Replace-Semantik beim
                # Restore: fehlt der Key -> garantiert leer, B3-2).
                "instance_hashes": list(p.get("instance_hashes") or []),
                # 21.03.12 (MTF-FC auf Analytics): Filterleisten-Zustand
                # (data_tf/agg_tf/range) im Profil persistieren - die
                # Analysequelle, die Aggregations-TF und der Zeitraum des
                # MtfFilterBarWidget werden beim Profilwechsel restauriert.
                # 21.03.14 (Wunsch 2): `sort_mode` kommt additiv hinzu
                # (nach dem Rueckbau der View-Template-Buttons).
                "data_tf": p.get("data_tf"),
                "agg_tf": p.get("agg_tf"),
                "range_preset": p.get("range_preset"),
                "range_from": p.get("range_from"),
                "range_to": p.get("range_to"),
                "all_timeframes": p.get("all_timeframes"),
                "sort_mode": p.get("sort_mode"),
                # 21.03.20 (Analytics Modus-Filter): source_mode-Filter
                # wird additiv in der sources-Sektion persistiert
                # (Restore ueber _restore_params_from_payload).
                "service_mode": p.get("service_mode"),
            },
            "charts": {
                "heatmap_metric": p.get("heatmap_metric"),
                "scatter_x": p.get("scatter_x"),
                "scatter_y": p.get("scatter_y"),
                "distribution_column": p.get("distribution_column"),
                "bins": p.get("bins"),
                # 20.02 (E2/E3): Generische Heatmap-Config additiv unter
                # charts.heatmap (kein Schema-Bump noetig; v2-Sektionen sind
                # fuer additive UI-Settings ausgelegt, 20.01 E3).
                "heatmap": {
                    "x_dim": p.get("heatmap_x_dim"),
                    "y_dim": p.get("heatmap_y_dim"),
                    "field": p.get("heatmap_field"),
                    "agg": p.get("heatmap_agg"),
                    # 21.01 (E1): TF-Freigabe additiv persistieren.
                    "all_timeframes": p.get("heatmap_all_timeframes"),
                    "candle_projection_enabled": p.get(
                        "candle_projection_enabled"),
                    "zoom_x_range": list(p.get("zoom_x_range")
                                         or [0.0, 1.0]),
                    "zoom_y_range": list(p.get("zoom_y_range")
                                         or [0.0, 1.0]),
                },
            },
            "table": {
                "limit": p.get("limit"),
                "table_column_widths": dict(
                    p.get("table_column_widths") or {}),
                "table_row_height": p.get("table_row_height"),
                "table_sort_column": p.get("table_sort_column"),
                "table_sort_order": p.get("table_sort_order"),
            },
            "styling": {},
            # 10.08.2026 (Punkte 3/4): UI-Layout-Anteil (page_index,
            # heatmap_mode) additiv - von der UI via set_ui_layout() gesetzt.
            "layout": dict(self._ui_layout or {}),
        }

    def restore_workspace(self, workspace: Dict[str, Any]) -> None:
        """Wendet den gespeicherten Fenster-Workspace an (20.01, E7).

        Uebernimmt die Workspace-Parameter (letzter Sitzungszustand gewinnt
        ueber das aktive Profil) verlustfrei in `_params` – OHNE Dirty-Flag
        und mit demselben Resolver-Pfad wie `_apply_profile` (fehlende
        Services werden isoliert und via `missing_services_detected`
        gemeldet). Der UI-Layout-Anteil (z. B. page_index) wird separat unter
        `workspace_layout` bereitgestellt (kein `_params`-Key). Danach
        `refresh_all()` (Daten fuer alle Seiten).

        Args:
            workspace: Payload aus `state_manager.get_workspace_state(...)`
                im Format {"params": {...}, "layout": {...}}.
        """
        if not isinstance(workspace, dict):
            return
        self._workspace_layout = dict(workspace.get("layout") or {})
        params = workspace.get("params")
        if not isinstance(params, dict):
            return
        # Runde 11 (Bug 3, B3-2): Gemeinsamer Restore-Helper (Replace-
        # Semantik inkl. instance_hashes -> garantiert leer bei fehlendem
        # Payload-Key statt des alten Werts).
        self._restore_params_from_payload(params)
        # 20.02.01 (E6): Alt-Workspaces mit `dow_hour` -> "hour" (Tageszeit).
        for _hk in ("heatmap_x_dim", "heatmap_y_dim"):
            if self._params.get(_hk) == "dow_hour":
                self._params[_hk] = "hour"
        # 20.04-Q8-Fix (User-Bugreport Punkt 1a): Auch die verschachtelte
        # `charts.heatmap`-Sektion des Workspace-Params restaurieren
        # (heatmap_agg/heatmap_field) – der flache Key-Loop uebernimmt die
        # flachen Keys, aber das verschachtelte Dict (wie im Profil-Payload)
        # muss explizit via _apply_heatmap_section aufgeloest werden.
        if isinstance(params.get("heatmap"), dict):
            self._apply_heatmap_section(params.get("heatmap"))
        self._params["feature_ids"] = self._normalize_feature_ids(
            self._params.get("feature_ids"))
        # Runde 10 (Bug 1): instance_hashes genauso normalisieren.
        self._params["instance_hashes"] = self._normalize_instance_hashes(
            self._params.get("instance_hashes"))
        # 12.08.2026 (Option A): (Service|Parameter)-Auswahl des
        # 'Feld'-Dropdowns genauso normalisieren (identisch zu
        # _apply_profile).
        self._params["field_selection"] = self._normalize_field_pairs(
            self._params.get("field_selection"))
        # Runde 9 (Bug 1): Fehlende Services NUR melden, NICHT aus dem
        # Filter entfernen - der Resolver wuerde sonst den restaurierten
        # Filter stillschweigend kuerzen (die DB liefert fuer unbekannte
        # IDs einfach keine Zeilen; Graceful Degradation ohne Datenverlust).
        if self._params["feature_ids"]:
            _, missing = self._resolve_feature_ids(self._params["feature_ids"])
            if missing:
                self.missing_services_detected.emit(list(missing))
        self._params["bins"] = self._clamp_bins(self._params.get("bins"))
        self._params["limit"] = self._clamp_limit(self._params.get("limit"))
        # Runde 8 (Bugfix 3): Generation erhoehen - die UI verwirft
        # Stale-Payloads aelterer Generation (Queries, die VOR diesem
        # Workspace-Restore gestartet wurden).
        self._restore_generation += 1
        # Runde 10 (Bug 4): REIHENFOLGE - erst die UI-Combos synchronisieren
        # (params_restored), DANN die Daten anfordern. Runde 11 (A1): KEIN
        # refresh_all() mehr im Restore-Pfad - das AnalyticsWindow
        # orchestriert die Queries zentral (A6: Sync -> Query-Key-Pruefung
        # -> request_data).
        self.params_restored.emit()

    @staticmethod
    def _emit_profile_changed(name: str) -> None:
        """Emittiert profile_changed auf dem zentralen EventBus."""
        event_bus.profile_changed.emit(name or "")

    # ------------------------------------------------------------------
    # Jump-to-Chart-Resolution (15.03 Schritt 5, Variante 2)
    # ------------------------------------------------------------------
    def resolve_latest_bar_time(
        self, symbol: str, timeframe: str
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch fuer 'Jump-to-Chart' (oder None).

        Schnelle Punktabfrage (PK-Index) fuer Klick-auf-Punkt aus dem
        Scatter – delegiert lesend an das AnalyticsRepository (kein SQL
        im ViewModel).
        """
        return self._repo.get_latest_bar_time(
            symbol, timeframe,
            feature_ids=self._params.get("feature_ids"),
        )

    def resolve_recent_bar_time_for_cell(
        self, symbol: str, timeframe: str, dow: int, hour: int
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch einer (dow, hour)-Zelle (oder None).

        Jump-to-Chart aus der Heatmap (Doppelklick auf eine Zelle) –
        delegiert lesend an das AnalyticsRepository.
        """
        return self._repo.get_recent_bar_time_for_cell(
            symbol, timeframe, dow, hour,
            feature_ids=self._params.get("feature_ids"),
        )

    # ------------------------------------------------------------------
    # Clamping (Typ- & Werte-Sicherheit)
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp_bins(value: Any) -> int:
        try:
            return max(2, int(value))
        except (TypeError, ValueError):
            return DEFAULT_BINS

    @staticmethod
    def _clamp_limit(value: Any) -> int:
        if value is None:
            return DEFAULT_LIMIT
        try:
            return max(1, min(int(value), MAX_LOOKBACK_LIMIT))
        except (TypeError, ValueError):
            return DEFAULT_LIMIT

    # ------------------------------------------------------------------
    # Lesende Zugriffe fuer UI-Pages
    # ------------------------------------------------------------------
    @property
    def params(self) -> Dict[str, Any]:
        """Kopie der aktuellen Ansichtsparameter (fuer UI-Kontrolle)."""
        return dict(self._params)

    @property
    def active_profile(self) -> Optional[Dict[str, Any]]:
        """Kopie des aktiven Profils (oder None)."""
        return dict(self._active_profile) if self._active_profile else None

    @property
    def profiles(self) -> List[Dict[str, Any]]:
        """Kopie der Profil-Liste (deterministisch nach Name sortiert)."""
        return [dict(p) for p in self._profiles]

    @property
    def is_dirty(self) -> bool:
        """True, wenn ungespeicherte Parametertrends vorliegen ('*')."""
        return self._dirty

    @property
    def workspace_layout(self) -> Dict[str, Any]:
        """UI-Layout-Anteil des zuletzt restaurierten Workspace (20.01, E7).

        Z. B. {"page_index": n} – wird von der UI nach `restore_workspace()`
        abgefragt (kein `_params`-Key).
        """
        return dict(self._workspace_layout)

    @property
    def restore_generation(self) -> int:
        """Generations-Token des letzten Restores (Runde 8, Stale-Guard).

        Wird bei jedem restore_workspace()/_apply_profile() erhoeht und vom
        Worker in jedes Ergebnis-Dict gespiegelt (`data["restore_"]`
        generation). Die UI vergleicht den Payload-Wert mit diesem Token und
        verwirft Payloads aelterer Generation (Queries, die VOR dem Restore
        gestartet wurden, ueberschreiben den synchron restaurierten Zustand
        nicht mehr).
        """
        return self._restore_generation

    def heatmap_metrics(self, symbol: str, timeframe: str) -> List[str]:
        """Verfuegbare Heatmap-Metriken fuer ein Symbol/Timeframe (19.02).

        "count" + numerische feature_data-JSON-Keys (dynamisch). Defensiv:
        ohne Daten/bei Fehler -> ["count"].
        """
        try:
            return self._repo.available_heatmap_metrics(
                str(symbol or ""), str(timeframe or ""))
        except Exception:
            return ["count"]

    def available_feature_columns(
        self, symbol: str, timeframe: str
    ) -> List[str]:
        """Numerische feature_data-JSON-Keys (Scatter-/Verteilungs-Dropdown).

        19.02 (Cleanup): Ersetzt die entfernten nativen Spalten. Defensiv:
        Fehler/leere Daten -> [].
        """
        try:
            return self._repo.available_feature_columns(
                str(symbol or ""), str(timeframe or ""))
        except Exception:
            return []

    # ------------------------------------------------------------------
    # 20.02.01 (E8): Lesbares Service-Label fuer die service_id-Dimension
    # ------------------------------------------------------------------
    def resolve_service_label(self, plugin_id: str) -> str:
        """Lesbares Service-Label '{Kategorie} / {Name}' (20.02.01, E8).

        Formatiert eine `service_id`-Dimension der generischen Heatmap:
        das `srv_`-Prefix entfaellt (metadata['display_name'], z. B.
        'Trend Breakout'), der Kategorie-Pfad (plugin_category_path,
        Slash -> ' / ') wird vorangestellt (z. B.
        'Swing Points / Trend Breakout'). Unbekannte/entfernte IDs ->
        Rohwert (defensiv). Lazy `_selector_model` (Muster
        `_resolve_feature_ids`), rein lesend, kein SQL.
        """
        key = str(plugin_id or "").strip()
        if not key:
            return ""
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            plugin = model.get_plugin(key)
            if plugin is None:
                return key
            meta = getattr(plugin, "metadata", {}) or {}
            name = str(meta.get("display_name") or key)
            if name.lower().startswith("srv_"):
                name = name[4:]
            category = str(model.plugin_category_path(key) or "")
            if category:
                return f"{category} / {name}"
            return name
        except Exception:
            return key

    def resolve_service_display_name(self, plugin_id: str,
                                     preset_name: Optional[str] = None,
                                     exec_date: Optional[str] = None) -> str:
        """Service-Name OHNE Kategorie-Pfad, direkt aus dem Service-Objekt.

        09.08.2026 (User-Meldung 'Feld'-Dropdown): Der Name wird DIREKT aus
        dem Service-Objekt abgeleitet – aus dessen `plugin_id` (der
        Identitaet des Objekts): `srv_`-Prefix entfaellt, Unterstriche
        werden zu Leerzeichen, Worte title-case ('srv_swing_momentum' ->
        'Swing Momentum'). Damit steht der KORREKTE Service-Name im
        'Feld'-Dropdown der generischen Heatmap; `metadata['display_name']`
        ist nicht zuverlaessig (z. B. 'Swing Momentum Service' mit
        'Service'-Suffix, das wie ein MasterTree-Pfad-Bestandteil wirkt).
        Kein Kategorie-Pfad. Unbekannte/entfernte IDs -> lesbarer Pretty-
        Fallback (defensiv). Rein lesend, kein SQL.

        20.04 (Q2, §4): Optionaler `preset_name` ergaenzt das Label um
        ' ({Preset_Name})' – Anzeige-Format '{Service} ({Preset}) /
        {Parameter}' fuer Parameter-Varianten (Clones). Ohne preset_name
        bleibt das Label unveraendert (Zero-Regression).

        Runde 16 (Bugfix 1, 11.08.2026): Format-Vereinheitlichung auf
        '{Name} / {Preset} / {Datum}' (Schraegstrich statt Klammern;
        'Default' als Platzhalter-Preset wird uebersprungen). Optionaler
        `exec_date` haengt Datum+Uhrzeit der letzten Ausfuehrung an
        ('DD.MM.JJ HH:MM') - Grundlage der Feld-Dropdown-Anzeige.
        """
        key = str(plugin_id or "").strip()
        if not key or key.lower() in ("none", "native") \
                or key.lower().startswith("native_"):
            # 09.08.2026 (User-Meldung Feld-Dropdown, Root Cause 3) +
            # 20.03.02 (F3): Leere/fehlende/Native-Keys liefern einen
            # lesbaren Sammel-Namen statt eines Leerstrings (kein leerer
            # Prefix vor Feld-Eintraegen). `native`/`native_*` werden wie
            # `none` auf 'Allgemein' gemappt (benutzerfreundlich).
            return "Allgemein"
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            plugin = model.get_plugin(key)
            if plugin is None:
                # 09.08.2026 (Root Cause 3): Unbekannte/abgewaehlte Keys
                # (z. B. Native-Rows) -> lesbarer Pretty-Fallback statt
                # Rohwert/Leerstring ('native' -> 'Native').
                pretty = (key.replace("src_", "").replace("srv_", "")
                          .replace("ind_", "").replace("_", " ").title())
                return pretty or key
            pid = str(getattr(plugin, "plugin_id", None) or key)
            name = pid
            for prefix in ("src_", "srv_", "ind_"):
                if name.lower().startswith(prefix):
                    name = name[len(prefix):]
                    break
            pretty = name.replace("_", " ").title()
            if not pretty:
                pretty = key
            # Runde 16 (Bugfix 1): Preset-Name + Ausfuehrungsdatum per
            # Schraegstrich anhaengen ('{Name} / {Preset} / DD.MM.JJ HH:MM').
            # 'Default' ist ein Platzhalter-Preset (Standalone-Services) und
            # wird uebersprungen.
            preset = str(preset_name or "").strip()
            if preset and preset.lower() != "default":
                pretty = f"{pretty} / {preset}"
            exec_d = str(exec_date or "").strip()
            if exec_d:
                pretty = f"{pretty} / {exec_d}"
            return pretty
        except Exception:
            return key

    def checked_variant(
        self, plugin_id: str
    ) -> Optional[Dict[str, str]]:
        """Aktuell gecheckte Variante eines Services inkl. Ausfuehrungsdatum.

        Runde 16 (Bugfix 1, 11.08.2026): Grundlage der Feld-Dropdown-
        Anzeige '{Name} / {Preset} / DD.MM.JJ HH:MM' - das Dropdown haengt
        an Feld-Eintraege die im ServicePicker gecheckte Variante (Preset)
        und das Datum+Uhrzeit ihrer letzten Ausfuehrung an.

        Auswahl-Semantik (identisch zum Reader/Snapshot):
          * Ist `instance_hashes` aktiv (Varianten-Einschraenkung), gewinnt
            die gecheckte Variante (exakter Hash-Match).
          * Ohne Hash-Auswahl zaehlt die ERSTE aktive (nicht archivierte)
            Variante des Services - ist der Service ein reiner Standalone
            (keine Presets), bleibt das Ergebnis None (kein Preset-Anhang).
          * Datum+Uhrzeit: Varianten mit Hash ueber
            `last_execution_datetime_for_hash` ('DD.MM.JJ HH:MM'), hash-lose
            Services ueber `last_execution_date` (nur Datum). Ohne Eintraege
            liefern beide den '--...'-Fallback (die Anzeige laesst ihn aus).

        Returns:
            {"preset_name", "instance_hash", "exec_datetime"} oder None
            (unbekannter Service / keine Presets / Fehler - defensiv).
        """
        key = str(plugin_id or "").strip()
        if not key:
            return None
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            active_hashes = {str(h).strip().lower()
                             for h in (self._params.get("instance_hashes")
                                       or [])}
            clones = (model.plugin_presets() or {}).get(key.lower()) or []
            chosen = None
            if active_hashes:
                for c in clones:
                    if not isinstance(c, dict):
                        continue
                    h = str(c.get("instance_hash") or "").strip()
                    if h and h.lower() in active_hashes:
                        chosen = c
                        break
            else:
                for c in clones:
                    if isinstance(c, dict) and not c.get("is_archived"):
                        chosen = c
                        break
                if chosen is None and clones:
                    chosen = clones[0]
            if chosen is None or not isinstance(chosen, dict):
                return None
            h = str(chosen.get("instance_hash") or "").strip()
            if h:
                exec_date = model.last_execution_datetime_for_hash(key, h)
            else:
                exec_date = model.last_execution_date(key)
            return {
                "preset_name": str(chosen.get("preset_name") or "Default"),
                "instance_hash": h,
                "exec_datetime": exec_date,
            }
        except Exception:
            return None

    def service_execution_datetime(self, plugin_id: str) -> str:
        """Datum+Uhrzeit der letzten Ausfuehrung eines Services.

        Runde 16c (Bugfix 1, 11.08.2026, User-Meldung): Das Feld-Dropdown
        haengt an Services OHNE Varianten (Standalone, z. B.
        srv_trend_breakout - kein Preset/keine Set-Instanz) das
        Ausfuehrungsdatum an ('{Name} / {Key} / DD.MM.JJ HH:MM', z. B.
        '23.04.26 22:14'). Rein lesend ueber das ServiceSelectorModel
        (`last_execution_datetime`); Fallback '--.--.-- --:--' ohne
        Eintraege oder bei Fehlern (defensiv).
        """
        key = str(plugin_id or "").strip()
        if not key:
            return "--.--.-- --:--"
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            return model.last_execution_datetime(key)
        except Exception:
            return "--.--.-- --:--"

    def resolve_instance_hashes(self,
                                hashes: Iterable[str]) -> List[str]:
        """Loest instance_hash-Werte transparent auf plugin_ids auf (20.04, Q2).

        Quelle: Plugin-Presets/Clones des `ServiceSelectorModel`
        (`plugin_presets()`, in refresh() aus indicator_presets geladen) –
        die Zuordnung Hash -> plugin_id ist dort deterministisch ueber
        `generate_instance_hash` abgelegt. Rueckgabe: deduplizierte
        plugin_ids (Reihenfolge erhalten, case-insensitiv). Hashes ohne
        Treffer werden verworfen (defensiv). Der Filter bleibt dadurch auf
        `WHERE feature_id IN (plugin_ids)` – die Varianten-Aufloesung
        passiert transparent im ViewModel (kein SQL, rein lesend).

        Beispiel: `resolve_instance_hashes(["a91f3b"])` -> ["srv_swing_pivot"].
        """
        wanted = {str(h or "").strip()
                  for h in (hashes or []) if str(h or "").strip()}
        if not wanted:
            return []
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        result: List[str] = []
        seen: Set[str] = set()
        try:
            presets = model.plugin_presets() or {}
            for pid, clones in presets.items():
                if not clones or not isinstance(clones, list):
                    continue
                for clone in clones:
                    if not isinstance(clone, dict):
                        continue
                    h = str(clone.get("instance_hash") or "").strip()
                    if not h or h not in wanted:
                        continue
                    if str(pid).lower() not in seen:
                        seen.add(str(pid).lower())
                        result.append(str(pid))
                    # Ein plugin_id pro Hash genuegt (dedupliziert).
                    wanted.discard(h)
        except Exception:
            pass
        return result

    def _no_data_presets_snapshot(self) -> Dict[str, Any]:
        """Serialisiert die Preset-Modell-Daten fuer die No-Data-Auswertung.

        Runde 11 (Bug 4, B4-1): Die '(No Data)'-Auswertung laeuft im
        QUERY_FEATURES-Worker (Repo, Worker-Thread) - dort ist das
        ServiceSelectorModel nicht verfuegbar. Der ViewModel reicht eine
        reine Daten-Snapshot (in-memory, KEIN SQL) ueber die Query-Params:
            {"presets": {pid: [{"preset_name", "instance_hash",
                                "is_archived"}]},
             "sets": [{"services": {instance_id: {"plugin_id", "params",
                                                   "is_archived"}}}],
             "standalone": [plugin_id der registrierten Plugins ohne
                            Presets und ohne Set-Instanz (hash-lose
                            Variante, 15c)],
             "display_names": {"{pid}|{pname}": "Anzeigename"},
             "active_hashes": [instance_hash der im Picker gecheckten
                               Varianten (leer = keine Einschraenkung)]}
        Der Reader kombiniert den Snapshot mit den DB-Fakten
        (available_instance_hashes / feature_keys_by_service) im Worker-
        Thread und liefert `no_data_variants` als Payload-Attribut (B4-2).

        Runde 13 (Bugfix Dropdown-NoData): `active_hashes` macht den Payload
        VARIANTEN-GENAU - der Reader `resolve_no_data_variants()` liefert
        damit nur noch die im ServicePicker gecheckten Varianten als
        '(No Data)' (nicht-gecheckte Instanzen derselben plugin_id erscheinen
        nicht mehr; das Dropdown zeigt nicht mehr die erste Variante).

        Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026): Reine
        Standalone-Services (registrierte Plugins OHNE Presets/Clones UND
        OHNE Set-Instanz, z. B. srv_trend_breakout) wurden nie in den
        Snapshot aufgenommen - der Reader konnte sie daher nie als
        '(No Data)' markieren, obwohl der feature_store noch keine Rows
        ihrer plugin_id besitzt. Die neue Snapshot-Sektion `standalone`
        listet genau diese Plugins als hash-lose Variante (preset_name
        'Default'); der Reader prueft sie gegen `pids_with_data`.
        """
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        presets: Dict[str, Any] = {}
        sets: List[Any] = []
        display_names: Dict[str, str] = {}
        # Runde 15c (Bugfix Standalone): Registrierte Plugins ohne Presets
        # und ohne Set-Instanz als hash-lose '(No Data)'-Kandidaten.
        standalone: List[str] = []
        # Runde 12 (Punkt 4): Nur GE CHECKTE Services in den Snapshot
        # aufnehmen (feature_ids-Filter; leer = kein Filter = alle). Nicht
        # angehakte Services duerfen keine '(No Data)'-Hinweise liefern.
        active_ids = {str(f).strip().lower()
                      for f in (self._params.get("feature_ids") or [])}
        # Runde 13c (Bugfix Dropdown-NoData, Kernwunsch): Leerer Filter
        # (feature_ids=[]) = KEINE '(No Data)'-Eintraege. Ohne aktive
        # Datenquellen-Auswahl wuerde der Snapshot ALLE Services enthalten
        # und der Reader jede NoData-Variante im Feld-Dropdown anzeigen
        # (der Button 'Aktive Filter entfernen' verspricht 'zeigt danach
        # wieder alle Features' – ohne NoData-Rauschen).
        if not active_ids:
            return {"presets": {}, "sets": [], "display_names": {},
                    "active_hashes": []}
        # Runde 13 (Bugfix Dropdown-NoData): Varianten-Einschraenkung mit
        # an den Reader geben - die '(No Data)'-Auswertung wird damit
        # variantengenau (nur im Picker gecheckte Varianten im Payload).
        active_hashes = {str(h).strip().lower()
                         for h in (self._params.get("instance_hashes") or [])}
        try:
            for pid, clones in (model.plugin_presets() or {}).items():
                pid_s = str(pid)
                if active_ids and pid_s.strip().lower() not in active_ids:
                    continue
                clone_list: List[Dict[str, Any]] = []
                for c in clones or []:
                    if not isinstance(c, dict):
                        continue
                    h_s = str(c.get("instance_hash") or "").strip().lower()
                    # Runde 13b (Bugfix Dropdown-NoData): Harte Varianten-
                    # Einschraenkung - sind Hashes gecheckt (active_hashes
                    # nicht leer), duerfen NUR diese Varianten in den
                    # Snapshot (bewusst OHNE `h_s and`-Guard: eine hash-lose
                    # Variante ist bei aktiver Einschraenkung nie Teil der
                    # Auswahl und darf kein '(No Data)' liefern - sonst
                    # erscheinen ungecheckte Instanzen weiterhin).
                    if active_hashes and h_s not in active_hashes:
                        continue
                    pname = str(c.get("preset_name") or "Default")
                    clone_list.append({
                        "preset_name": pname,
                        "instance_hash": str(c.get("instance_hash") or ""),
                        "is_archived": bool(c.get("is_archived")),
                    })
                    display_names[f"{pid_s}|{pname}"] = \
                        self.resolve_service_display_name(pid_s, pname)
                if clone_list:
                    presets[pid_s] = clone_list
            for s in model.get_sets() or []:
                if not isinstance(s, dict):
                    continue
                services = s.get("services")
                if not isinstance(services, dict):
                    continue
                if active_ids:
                    services = {
                        k: svc for k, svc in services.items()
                        if isinstance(svc, dict)
                        and str(svc.get("plugin_id") or "").strip().lower()
                        in active_ids}
                if services:
                    sets.append({"services": services})
            # Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026):
            # Registrierte Plugins, die weder Presets/Clones noch eine
            # Set-Instanz besitzen (z. B. srv_trend_breakout), sind reine
            # Standalone-Services. Als hash-lose Variante (preset_name
            # 'Default') geprueft, erscheinen sie im Feld-Dropdown, sobald
            # der feature_store noch keine Rows ihrer plugin_id besitzt.
            # Beim Vorhandensein von Daten (pids_with_data) bleibt der
            # NoData-Hinweis aus (Reader-Semantik). Ausgeschlossen sind
            # Plugins mit Presets oder Set-Instanzen (dort laeuft die
            # bestehende Preset-/Set-Auswertung).
            # Runde 16 (Bugfix Mischbetrieb, User-Meldung 5/6, 11.08.2026):
            # Der Runde-15c-Guard `if not active_hashes:` ist ENTFERNT - er
            # schloss die Standalone-Sektion aus, sobald eine Hash-Auswahl
            # aktiv war (Mischbetrieb Service + Version). Standalone-
            # Services werden UEBER `feature_ids` gecheckt, NICHT ueber
            # Hashes - eine aktive Varianten-Einschraenkung darf sie daher
            # nicht aus der NoData-Auswertung verwerfen.
            try:
                all_presets = model.plugin_presets() or {}
                preset_keys = {str(k).strip().lower()
                               for k in all_presets}
                set_pids: Set[str] = set()
                for _s in model.get_sets() or []:
                    _services = (_s.get("services")
                                 if isinstance(_s, dict) else None)
                    if not isinstance(_services, dict):
                        continue
                    for _svc in _services.values():
                        if isinstance(_svc, dict) and str(
                                _svc.get("plugin_id") or "").strip():
                            set_pids.add(
                                str(_svc["plugin_id"]).strip().lower())
                for _pid in (model.get_plugins() or {}).keys():
                    _pid_l = str(_pid).strip().lower()
                    if not _pid_l:
                        continue
                    if active_ids and _pid_l not in active_ids:
                        continue
                    if _pid_l in preset_keys or _pid_l in set_pids:
                        continue
                    standalone.append(_pid)
                    display_names[f"{_pid}|Default"] = \
                        self.resolve_service_display_name(_pid)
            except Exception:
                pass
        except Exception:
            pass
        return {
            "presets": presets,
            "sets": sets,
            "standalone": standalone,
            "display_names": display_names,
            "active_hashes": sorted(active_hashes),
        }

    @property
    def max_lookback_limit(self) -> int:
        """Max-Lookback-Cap (UI-Slider-Maximum)."""
        return MAX_LOOKBACK_LIMIT

    def available_timeframes(self, symbol: str) -> List[str]:
        """Timeframes mit Feature-Store-Daten fuer ein Symbol (TF-Ausgrauung).

        Delegiert lesend an das AnalyticsRepository (kein SQL im ViewModel).
        Bei Fehlern wird eine leere Liste geliefert; die UI kann dann alle
        Timeframes aktiv lassen (Fallback).
        """
        try:
            return self._repo.available_timeframes(str(symbol or ""))
        except Exception:
            return []
