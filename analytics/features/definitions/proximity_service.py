# analytics/features/definitions/proximity_service.py
"""
Service: Proximity (Phase 13 Schritt 6)

Liest die Linienliste aus context.shared_state[depends_on[0]] (z. B. grid_1)
und wendet die PROZENTUALE visit%-Semantik des Alt-Grid-Indikators an
(Paritätsfunktionen in `grid_math.py`, Phase 15 U15-B3):

    visit_min = lvl * (1.0 - visit_pct / 100.0)
    visit_max = lvl * (1.0 + visit_pct / 100.0)
    touch_high = visit_min <= high <= visit_max
    touch_low  = visit_min <= low  <= visit_max
    pierce     = low <= lvl and high >= lvl

– NICHT die absolute threshold-Distanz des Alt-Plugins grid_liquidity.

Das native UTC-Zeitfenster (Minute 0/30 ± time_window_mins) wird pro Hit als
`in_window`-Flag in den hit_circles gemeldet. Die FARBE der Kreise (gelb im
Fenster / fuchsia außerhalb) und die Sichtbarkeit (show_lines / show_circles)
sind KEINE Service-Parameter – sie werden vom INDIKATOR gesteuert
(chart/indicators/grid_liquidity.py), der die Circle-Farben auf Basis seines
eigenen Schemas (circle_color_std / circle_color_active) und des
`in_window`-Flags setzt.

lookback (Scan-Fenster von rechts nach links) = min(statistics_signal_limit,
len(df)) aus context.settings. Der Service schreibt die Hit-Records nach
feature_data (feature_store=True) für Schritt 7 (Marker/Statistik).

Capabilities: render=True, feature_store=True.
"""

from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np

from analytics.features.definitions.grid_math import (
    f_in_window_around,
    f_strip_trailing_zeros,
)
from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)


def _bar_utc_minutes(df: pd.DataFrame) -> List[int]:
    """UTC-Minute (0-59) jeder Bar – konsistent zu grid_liquidity.py.

    Phase 16 (05.08.2026): Vektorisierter Fast-Path fuer 'time'-Spalten
    (epoch-Sekunden, int) – (t // 60) % 60 ist mathematisch identisch zu
    datetime.fromtimestamp(t, tz=utc).minute (auch fuer negative Zeiten,
    Python/numpy-Floor-Division). Bereichs-Guard: Zeiten ausserhalb des
    datetime-basierten Alt-Bereichs fallen auf den OSError-Fallback zurueck
    (dort wird 0 gesetzt – exakte Alt-Paritaet).
    """
    if "time" in df.columns:
        try:
            import numpy as np
            t = df["time"].to_numpy(dtype=np.int64)
            if len(t) == 0 or (int(np.min(t)) >= -62135596800
                               and int(np.max(t)) < 253402300799):
                return [int(m) for m in ((t // 60) % 60).tolist()]
        except (TypeError, ValueError, OSError):
            pass
        out: List[int] = []
        for t in df["time"]:
            try:
                out.append(datetime.fromtimestamp(int(t), tz=dt_timezone.utc).minute)
            except (TypeError, ValueError, OSError):
                out.append(0)
        return out
    elif "bar_time" in df.columns:
        t = pd.to_datetime(df["bar_time"])
        if t.dt.tz is not None:
            out = t.dt.tz_convert("UTC").dt.minute.tolist()
        else:
            out = t.dt.minute.tolist()
    return [int(m) for m in out]


class ProximityService(PluginFeature):

    @property
    def plugin_id(self) -> str:
        return "proximity"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, str]:
        return {
            "category": "Grid",
            "display_name": "Proximity",
            # Bugfix (04.08.2026): Zugehoeriger Indikator-Name fuer die Status-
            # Badges im MasterTree (der Service laeuft IN GridLiquidityIndicator).
            "indicator_name": "GridLiquidityIndicator",
            # Bugfix (05.08.2026): indicator_id = indicators_state-Key des
            # zugehoerigen Indikators. ServiceSelectorModel.is_active_in_chart()
            # prueft damit die Aktiv-Frage auf Indikator-Ebene (Tooltip
            # 'aktiv <Indikator>' statt nur 'im <Indikator>').
            "indicator_id": "grid_liquidity",
            "description": "Prozentuale visit%-Treffer auf den Grid-Linien (Parität zu grid_math.py) inkl. Feature-Store-Records",
            "author": "PyTrader AI",
            "tags": ["grid", "proximity", "liquidity", "feature-store"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Liest die Linienliste aus shared_state[depends_on] "
                                "und wendet die prozentuale visit%-Semantik der "
                                "Paritätsfunktionen (grid_math.py) an "
                                "(visit_min/max je Linie). Schreibt "
                                "Hit-Records in den Feature-Store.",
            "condition_rules": [
                "Treffer: visit_min <= high/low <= visit_max ODER Piercing (low <= lvl <= high)",
                "in_window-Flag: Minute 0/30 ± time_window_mins (UTC)",
                "Scan-Fenster: min(statistics_signal_limit, len(df)) von rechts",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": True,
            "batch": True,
            "live": False,
            "feature_store": True,  # schreibt Hit-Records nach feature_data
            "render": True,
        }

    @property
    def dependencies(self) -> List[str]:
        """Vorab berechnete Service-Plugins (PluginFeature.dependencies).

        05.08.2026 (Bugfix Service-Run): proximity liest seine Linienliste aus
        context.shared_state[depends_on[0]] – dafuer muss eine vorgelagerte
        grid_lines-Instanz in execution_order stehen. Gespeicherte Sets aus
        der UI-Pfade haben oft KEIN explizites depends_on; die Worker-
        Aufbereitung (serviceui/service_set_utils.prepare_worker_definition)
        loest daraus die implizite Abhaengigkeit auf (naechste VORHERIGE
        Instanz mit plugin_id in dependencies). Explizit gesetzte
        depends_on-Werte (z.B. Indikator-intern grid_1 -> prox_1) bleiben
        unveraendert gueltig.
        """
        return ["grid_lines"]

    # --- Single Source of Truth fürs Prop-Fenster (Phase 13 Schritt 5) -------
    # Hinweis (Schritt 6-Korrektur 3): Die visuellen Parameter (show_circles,
    # circle_color_std, circle_color_active, show_lines) sind KEINE
    # Service-Parameter – sie gehören zum Indikator-Schema und werden dort
    # gesteuert (chart/indicators/grid_liquidity.py). Der Service meldet nur
    # das in_window-Flag; der Indikator färbt die Kreise.
    @property
    def parameter_order(self) -> List[str]:
        return [
            "visit_pct",
            "use_time_filter", "time_window_mins",
        ]

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "visit_pct": "Besuchs-Toleranz (%)",
            "use_time_filter": "Time Filter aktiv",
            "time_window_mins": "Time Filter Minuten (0/30)",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        return {
            "visit_pct": {
                "type": "float", "default": 0.05, "min": 0.0, "max": 100.0,
                "step": 0.005, "description": "Prozentuale Toleranz um jede Linie (Parität zu grid_math.py visit_pct)",
            },
            "time_window_mins": {
                "type": "int", "default": 5, "min": 0, "max": 30,
                "step": 1, "description": "Time Filter Minuten um 0/30 UTC",
            },
            "use_time_filter": {
                "type": "bool", "default": True,
                "description": "Time Filter aktiv – steuert das in_window-Flag der Hits",
            },
        }

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Wendet die prozentuale visit%-Semantik der Paritätsfunktionen
        (grid_math.py) auf die Linien aus context.shared_state[depends_on[0]]
        an und schreibt Hit-Records nach feature_data (feature_store=True)."""
        empty: FeatureCalculateResult = {
            "feature_store_payload": {},
            "chart_render_payload": {"lines": [], "hit_circles": []},
        }
        if df is None or df.empty:
            return empty

        # --- Linien aus dem shared_state des abhängigen Services lesen -------
        dep_id: Optional[str] = None
        if context is not None:
            deps = context.depends_on or []
            dep_id = deps[0] if deps else None
        lines_payload: List[Dict[str, Any]] = []
        if context is not None and dep_id is not None:
            shared = context.shared_state.get(dep_id)
            if isinstance(shared, list):
                lines_payload = shared
            elif isinstance(shared, dict):
                lines_payload = shared.get("lines") or []

        if not lines_payload:
            # Keine Linien verfügbar (z. B. Direkt-Aufruf ohne Pipeline) →
            # kein Proximity möglich. Fail-Fast würde der Evaluator ohnehin
            # werfen; hier defensiv leer zurückgeben.
            return empty

        p = self.validate_params(params)
        visit_pct = float(p["visit_pct"])
        time_window_mins = int(p["time_window_mins"])
        use_time_filter = bool(p["use_time_filter"])

        # --- Scan-Fenster von rechts nach links: min(statistics_signal_limit, len(df))
        limit = len(df)
        if context is not None and context.settings is not None:
            try:
                sig_limit = int(getattr(context.settings, "statistics_signal_limit", 0))
                if sig_limit > 0:
                    limit = min(sig_limit, limit)
            except (TypeError, ValueError):
                pass
        scan_df = df.tail(limit)

        # tracked_levels: IMMER aus der Linienliste – Sichtbarkeit (show_lines)
        # steuert der GridLinesService (liefert bei show_lines=false gar keine
        # Linien) bzw. der Indikator. show_lines ist KEIN Service-Parameter.
        tracked_levels = [float(l["price"]) for l in lines_payload]

        # --- Proximity & Hit-Logik (exakte Parität zu grid_math.py) ----------
        # Phase 16 (05.08.2026): Numpy-Vektorisierung statt der O(n*m)-Double-
        # Loop (df.iterrows() x tracked_levels). Bei 10k+ Lookback-Bars sinkt
        # die Rechenzeit von mehreren Sekunden auf wenige Millisekunden.
        # Parität:
        #   * near = (visit_min <= high <= visit_max) | (visit_min <= low <=
        #     visit_max) | (low <= lvl <= high) – identische Vergleichs-
        #     Semantik zu grid_math.py.
        #   * NaN high/low propagieren in den Vergleichen zu False (kein Hit)
        #     – wie im Alt-Pfad (Float-Vergleich mit NaN ist False).
        #   * Reihung hit_circles/levels_hit: zeilen-major, innerhalb einer
        #     Zeile in tracked_levels-Reihenfolge (lexsort über Zeile+Level).
        hit_circles: List[Dict[str, Any]] = []
        active_hits: List[str] = []
        feature_rows: List[Dict[str, Any]] = []

        n = len(scan_df)
        minutes = _bar_utc_minutes(scan_df)
        if n:
            times = scan_df["time"].to_numpy(dtype=np.int64)
            high = scan_df["high"].to_numpy(dtype=np.float64)
            low = scan_df["low"].to_numpy(dtype=np.float64)
            levels_arr = np.array(tracked_levels, dtype=np.float64)
            in_win = np.array([
                (f_in_window_around(m, 0, time_window_mins)
                 or f_in_window_around(m, 30, time_window_mins))
                for m in minutes
            ], dtype=bool)

            levels_hit: List[List[float]] = [[] for _ in range(n)]
            if len(levels_arr):
                factor = visit_pct / 100.0
                vmin = levels_arr * (1.0 - factor)
                vmax = levels_arr * (1.0 + factor)
                # Broadcasting: (len(levels), n)-Bool-Matrix – jede Zeile ist
                # ein Level, jede Spalte eine Bar.
                near = (
                    ((vmin[:, None] <= high[None, :]) & (high[None, :] <= vmax[:, None]))
                    | ((vmin[:, None] <= low[None, :]) & (low[None, :] <= vmax[:, None]))
                    | ((low[None, :] <= levels_arr[:, None]) & (high[None, :] >= levels_arr[:, None]))
                )
                # np.nonzero liefert (Achse-0 = Level, Achse-1 = Bar).
                lvl_idxs, bar_idxs = np.nonzero(near)
                if len(lvl_idxs):
                    # Zeilen-major (Bar aussen) + Level-Reihenfolge innen
                    # (stabil) – identische Abfolge wie die Alt-Double-Loop.
                    order = np.lexsort((lvl_idxs, bar_idxs))
                    bar_sorted = bar_idxs[order]
                    lvl_sorted = lvl_idxs[order]
                    starts = np.concatenate(
                        ([0], np.flatnonzero(np.diff(bar_sorted) != 0) + 1))
                    ends = np.concatenate((starts[1:], [len(bar_sorted)]))
                    last_pos = n - 1
                    for s, e in zip(starts, ends):
                        r = int(bar_sorted[s])
                        lvls = [float(x) for x in levels_arr[lvl_sorted[s:e]]]
                        levels_hit[r] = lvls
                        t_val = int(times[r])
                        win_flag = bool(in_win[r])
                        for lvl in lvls:
                            # hit_circles ohne Farbe – der INDIKATOR färbt auf
                            # Basis seines eigenen Schemas (circle_color_std /
                            # _active) und des in_window-Flags. in_window=True
                            # wenn die Bar im UTC-Zeitfenster (0/30 ±
                            # time_window_mins) liegt.
                            hit_circles.append({
                                "time": t_val,
                                "price": lvl,
                                "in_window": win_flag,
                            })
                        if r == last_pos:
                            active_hits.extend(
                                f_strip_trailing_zeros(v) for v in lvls)

            feature_rows = []
            for pos in range(n):
                feature_rows.append({
                    "bar_time": int(times[pos]),
                    "levels_hit": levels_hit[pos],
                    "is_hit": bool(levels_hit[pos]),
                    "in_time_window": bool(in_win[pos]),
                    "time_window_mins": time_window_mins,
                    "use_time_filter": use_time_filter,
                    "visit_pct": visit_pct,
                })

        # --- Status-Info (letzte Bar des Scan-Fensters, Parität zu grid_math.py)
        if len(scan_df):
            last_ts = int(scan_df.iloc[-1]["time"])
            last_m = datetime.fromtimestamp(last_ts, tz=dt_timezone.utc).minute
            full_win = f_in_window_around(last_m, 0, time_window_mins)
            half_win = f_in_window_around(last_m, 30, time_window_mins)
            in_time_window_raw = full_win or half_win
            in_time_window = in_time_window_raw if use_time_filter else True
        else:
            in_time_window = False

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": feature_rows,
                "metadata": {
                    "total_hits": len(hit_circles),
                    "depends_on": dep_id,
                    "scan_limit": limit,
                    "visit_pct": visit_pct,
                    # P14-03 (Invariante 5): explizite schema_version in jedem
                    # Feature-Payload – der Indikator-Lesepfad (feature_data)
                    # prüft sie beim Chart-Re-Render.
                    "schema_version": "1.0.0",
                },
            },
            "chart_render_payload": {
                "lines": [],
                "hit_circles": hit_circles,
                "status_info": {
                    "in_time_window": in_time_window,
                    "active_hits": active_hits,
                },
            },
        }
