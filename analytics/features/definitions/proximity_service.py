# analytics/features/definitions/proximity_service.py
"""
Service: Proximity (Phase 13 Schritt 6)

Liest die Linienliste aus context.shared_state[depends_on[0]] (z. B. grid_1)
und wendet die PROZENTUALE visit%-Semantik von grid.py an:

    visit_min = lvl * (1.0 - visit_pct / 100.0)
    visit_max = lvl * (1.0 + visit_pct / 100.0)
    touch_high = visit_min <= high <= visit_max
    touch_low  = visit_min <= low  <= visit_max
    pierce     = low <= lvl and high >= lvl

– NICHT die absolute threshold-Distanz des Alt-Plugins grid_liquidity.

Das native UTC-Zeitfenster (Minute 0/30 ± time_window_mins) bestimmt wie in
grid.py nur die Farbe der Kreise:
  - Zeitfilter INAKTIV  → alle Treffer circle_color_std (gelb #FFEB3B)
  - Zeitfilter AKTIV    → im Fenster circle_color_std, ausserhalb
                          circle_color_active (fuchsia #E91E63)

lookback (Scan-Fenster von rechts nach links) = min(statistics_signal_limit,
len(df)) aus context.settings. Der Service schreibt die Hit-Records nach
feature_data (feature_store=True) für Schritt 7 (Marker/Statistik).

Capabilities: render=True, feature_store=True.
"""

from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# Paritäts-Defaults (identisch zu grid.py)
YELLOW = "#FFEB3B"
FUCHSIA = "#E91E63"


def f_in_window_around(minute_val: int, center: int, span: int) -> bool:
    """Native UTC-Zeitfenster-Logik – identisch zu grid.py."""
    lower = center - span
    upper = center + span
    if lower < 0:
        return minute_val >= (60 + lower) or minute_val <= upper
    elif upper > 59:
        return minute_val >= lower or minute_val <= (upper - 60)
    else:
        return lower <= minute_val <= upper


def f_strip_trailing_zeros(val: float) -> str:
    """Identisch zu grid.py – '%.6f' ohne nachgestellte Nullen."""
    s = f"{val:.6f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _bar_utc_minutes(df: pd.DataFrame) -> List[int]:
    """UTC-Minute (0-59) jeder Bar – konsistent zu grid_liquidity.py."""
    out: List[int] = []
    if "time" in df.columns:
        for t in df["time"]:
            try:
                out.append(datetime.fromtimestamp(int(t), tz=dt_timezone.utc).minute)
            except (TypeError, ValueError, OSError):
                out.append(0)
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
            "description": "Prozentuale visit%-Treffer auf den Grid-Linien (Parität zu grid.py) inkl. Feature-Store-Records",
            "author": "PyTrader AI",
            "tags": ["grid", "proximity", "liquidity", "feature-store"],
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

    # --- Single Source of Truth fürs Prop-Fenster (Phase 13 Schritt 5) -------
    @property
    def parameter_order(self) -> List[str]:
        return [
            "show_circles", "circle_color_std", "circle_color_active",
            "visit_pct",
            "use_time_filter", "time_window_mins",
            "show_lines",
        ]

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "show_circles": "Hits anzeigen",
            "circle_color_std": "Std-Hit-Farbe (im Fenster)",
            "circle_color_active": "Aktiv-Hit-Farbe (ausserhalb)",
            "visit_pct": "Besuchs-Toleranz (%)",
            "use_time_filter": "Time Filter aktiv",
            "time_window_mins": "Time Filter Minuten (0/30)",
            "show_lines": "Level-Tracking (Linien-Sichtbarkeit)",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        return {
            "visit_pct": {
                "type": "float", "default": 0.05, "min": 0.0, "max": 100.0,
                "step": 0.005, "description": "Prozentuale Toleranz um jede Linie (prox_visitPct ↔ visit_pct)",
            },
            "time_window_mins": {
                "type": "int", "default": 5, "min": 0, "max": 30,
                "step": 1, "description": "Time Filter Minuten um 0/30 (prox_timeWindowMins ↔ time_window_mins)",
            },
            "use_time_filter": {
                "type": "bool", "default": True,
                "description": "Time Filter aktiv – außerhalb gelb/fuchsia (prox_useTimeFilter ↔ use_time_filter)",
            },
            "show_lines": {
                "type": "bool", "default": True,
                "description": "Level-Tracking aktiv (grid.py: tracked_levels = levels if show_lines else [])",
            },
            "show_circles": {
                "type": "bool", "default": True, "description": "Hits anzeigen",
            },
            "circle_color_std": {
                "type": "color", "default": YELLOW, "description": "Farbe Hit im Zeitfenster",
            },
            "circle_color_active": {
                "type": "color", "default": FUCHSIA, "description": "Farbe Hit außerhalb des Fensters",
            },
        }

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Wendet die prozentuale visit%-Semantik von grid.py auf die Linien aus
        context.shared_state[depends_on[0]] an und schreibt Hit-Records nach
        feature_data (feature_store=True)."""
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
        show_lines = bool(p["show_lines"])
        show_circles = bool(p["show_circles"])
        circle_std = str(p.get("circle_color_std") or YELLOW)
        circle_active = str(p.get("circle_color_active") or FUCHSIA)

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

        tracked_levels = [float(l["price"]) for l in lines_payload] if show_lines else []

        # --- Proximity & Hit-Logik (exakte Parität zu grid.py) ---------------
        hit_circles: List[Dict[str, Any]] = []
        active_hits: List[str] = []
        feature_rows: List[Dict[str, Any]] = []

        minutes = _bar_utc_minutes(scan_df)
        last_idx = scan_df.index[-1] if len(scan_df) else None

        for pos, (idx, row) in enumerate(scan_df.iterrows()):
            time_val = int(row["time"])
            c_high = float(row["high"])
            c_low = float(row["low"])

            row_m = minutes[pos]
            row_in_time = (
                f_in_window_around(row_m, 0, time_window_mins)
                or f_in_window_around(row_m, 30, time_window_mins)
            )
            if use_time_filter and not row_in_time:
                circle_color = circle_active
            else:
                circle_color = circle_std

            levels_hit: List[float] = []
            for lvl in tracked_levels:
                visit_min = lvl * (1.0 - visit_pct / 100.0)
                visit_max = lvl * (1.0 + visit_pct / 100.0)

                touch_high = visit_min <= c_high <= visit_max
                touch_low = visit_min <= c_low <= visit_max
                pierce = c_low <= lvl and c_high >= lvl
                near = touch_high or touch_low or pierce

                if near:
                    levels_hit.append(lvl)
                    if show_circles:
                        hit_circles.append({
                            "time": time_val,
                            "price": lvl,
                            "color": circle_color,
                        })
                    if last_idx is not None and idx == last_idx:
                        active_hits.append(f_strip_trailing_zeros(lvl))

            feature_rows.append({
                "bar_time": time_val,
                "levels_hit": levels_hit,
                "is_hit": bool(levels_hit),
                "in_time_window": bool(row_in_time),
                "time_window_mins": time_window_mins,
                "use_time_filter": use_time_filter,
                "visit_pct": visit_pct,
            })

        # --- Status-Info (letzte Bar des Scan-Fensters, Parität zu grid.py) --
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
