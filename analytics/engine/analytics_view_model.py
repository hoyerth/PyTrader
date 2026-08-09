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
        }
        self._pending_kinds: List[str] = []
        self._worker: Optional[AnalyticsAsyncWorker] = None
        self._dirty = False
        self._active_profile: Optional[Dict[str, Any]] = None
        self._profiles: List[Dict[str, Any]] = []
        # 20.01 (E7): UI-Layout-Anteil des zuletzt restaurierten Workspace
        # (z. B. {"page_index": 2}) – von der UI abfragbar, kein _params-Key.
        self._workspace_layout: Dict[str, Any] = {}

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

    def set_feature_id(self, feature_id: Optional[str]) -> None:
        """Kompatibilitaets-Alias (Legacy): Einzel-ID -> Multi-Liste."""
        self.set_feature_ids([feature_id] if feature_id else [])

    def set_feature_ids(self, feature_ids) -> None:
        """Setzt die Multi-Auswahl der Datenquellen (15.03-E).

        `feature_ids` sind die plugin_ids des Feature-Store (z. B.
        ["srv_grid_lines", "srv_proximity"]); leer = kein Filter (alle Features).
        Typen-/Duplikat-normalisiert; ohne Aenderung wird kein Refresh
        ausgeloest (idempotent, wie set_symbol/set_timeframe).
        """
        ids = self._normalize_feature_ids(feature_ids)
        if ids == self._params.get("feature_ids"):
            return
        self._params["feature_ids"] = ids
        self._mark_dirty()
        self._refresh((QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                       QUERY_SCATTER, QUERY_DISTRIBUTION))

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
        for key in list(self._params.keys()):
            if key in flat and flat[key] is not None:
                self._params[key] = flat[key]
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
        # 20.01 (E5): Fehlende Services isolieren – valide IDs direkt setzen.
        valid, missing = self._resolve_feature_ids(self._params["feature_ids"])
        self._params["feature_ids"] = valid
        if missing:
            self.missing_services_detected.emit(list(missing))
        self._params["bins"] = self._clamp_bins(self._params.get("bins"))
        self._params["limit"] = self._clamp_limit(self._params.get("limit"))
        if not mark_dirty:
            self._dirty = False
            self.dirty_changed.emit(False)
        self.refresh_all()

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
        if heat.get("candle_projection_enabled") is not None:
            self._params["candle_projection_enabled"] = bool(
                heat["candle_projection_enabled"])
        if isinstance(heat.get("zoom_x_range"), (list, tuple)):
            self._params["zoom_x_range"] = self._clamp_zoom(
                heat["zoom_x_range"])
        if isinstance(heat.get("zoom_y_range"), (list, tuple)):
            self._params["zoom_y_range"] = self._clamp_zoom(
                heat["zoom_y_range"])

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
        for key in list(self._params.keys()):
            if key in params and params[key] is not None:
                self._params[key] = params[key]
        # 20.02.01 (E6): Alt-Workspaces mit `dow_hour` -> "hour" (Tageszeit).
        for _hk in ("heatmap_x_dim", "heatmap_y_dim"):
            if self._params.get(_hk) == "dow_hour":
                self._params[_hk] = "hour"
        self._params["feature_ids"] = self._normalize_feature_ids(
            self._params.get("feature_ids"))
        valid, missing = self._resolve_feature_ids(self._params["feature_ids"])
        self._params["feature_ids"] = valid
        if missing:
            self.missing_services_detected.emit(list(missing))
        self._params["bins"] = self._clamp_bins(self._params.get("bins"))
        self._params["limit"] = self._clamp_limit(self._params.get("limit"))
        self.refresh_all()

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
                                     preset_name: Optional[str] = None) -> str:
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
                pretty = (key.replace("srv_", "").replace("ind_", "")
                          .replace("_", " ").title())
                return pretty or key
            pid = str(getattr(plugin, "plugin_id", None) or key)
            name = pid
            for prefix in ("srv_", "ind_"):
                if name.lower().startswith(prefix):
                    name = name[len(prefix):]
                    break
            pretty = name.replace("_", " ").title()
            if not pretty:
                pretty = key
            # 20.04 (Q2): Preset-Name (Variante) in Klammern ergaenzen.
            preset = str(preset_name or "").strip()
            if preset:
                pretty = f"{pretty} ({preset})"
            return pretty
        except Exception:
            return key

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
