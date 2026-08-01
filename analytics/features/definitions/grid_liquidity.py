# analytics/features/definitions/grid_liquidity.py
"""
Plugin: Grid Liquidity & Proximity (Phase 12 Schritt 4).

Paritäts-Plugin zur bestehenden Alt-Implementierung chart/indicators/grid.py.

VERBINDLICHE ENTSCHEIDUNGEN (Roadmap Phase 12):
1. Die Farb-/Aktivitätslogik unten (`8 <= dt.hour <= 16`) ist ausschließlich
   ein PLATZHALTER aus der Roadmap. Sie ersetzt NICHT das native UTC-Zeitfenster
   (Minute 0/30 ± time_window_mins) in analytics/features/definitions/grid_levels.py
   bzw. chart/indicators/grid.py. Andere Zeitkonzepte werden in einem separaten
   Layer darübergelegt – nie in die native Logik hinein.
2. Die persistente Speicherung des vollständigen Liq-Rasters folgt später im
   Plugin-System (Service schreibt Raster in DB → Indikator holt es).
3. Der Alt-Indikator chart/indicators/grid.py bleibt UNVERÄNDERT (Referenz-Alt-
   Implementierung, Parallelbetrieb). Dieses Plugin ist die Neu-Implementierung.
"""

from typing import Dict, Any

import numpy as np
import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginFeature,
    PluginMetadata,
)


def _f_in_window_around(minute_val: int, center: int, span: int) -> bool:
    """Native UTC-Zeitfenster-Logik (identisch zu f_in_window_around() in
    chart/indicators/grid.py und in_window_around() in grid_levels.py).
    True, wenn minute_val im Fenster center +/- span liegt (mit Wrap-Around
    ueber 0/59). Wird hier im Service dupliziert, damit getimte Treffer als
    Feature-Store-Daten in Analysen nutzbar sind – die native Logik selbst
    bleibt unveraendert."""
    lower = center - span
    upper = center + span
    if lower < 0:
        return minute_val >= (60 + lower) or minute_val <= upper
    elif upper > 59:
        return minute_val >= lower or minute_val <= (upper - 60)
    else:
        return lower <= minute_val <= upper


def _bar_utc_minutes(df: pd.DataFrame) -> np.ndarray:
    """Liefert die UTC-Minute (0-59) jeder Bar – konsistent zu
    GridLevelsFeature._bar_utc_minutes(). Unterstuetzt 'bar_time'
    (datetime/pandas) und 'time' (epoch-Sekunden)."""
    n = len(df)
    if "bar_time" in df.columns:
        t = pd.to_datetime(df["bar_time"])
        if t.dt.tz is not None:
            return t.dt.tz_convert("UTC").dt.minute.to_numpy(dtype=int)
        return t.dt.minute.to_numpy(dtype=int)
    elif "time" in df.columns:
        t = pd.to_datetime(df["time"], unit="s", utc=True)
        return t.dt.minute.to_numpy(dtype=int)
    return np.zeros(n, dtype=int)


class GridLiquidityFeature(PluginFeature):

    @property
    def plugin_id(self) -> str:
        return "grid_liquidity"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> PluginMetadata:
        return {
            "category": "Grid",
            "display_name": "Grid Liquidity & Proximity",
            "description": "Erkennt Preisnähe zu Grid-Leveln inkl. Custom Levels & Zeitfenstern",
            "author": "PyTrader AI",
            "tags": ["grid", "liquidity", "proximity"],
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        return {
            "grid_step": {"type": "float", "default": 0.50, "min": 0.01, "max": 100.0, "step": 0.05, "description": "Rasterabstand"},
            "proximity_threshold": {"type": "float", "default": 0.05, "min": 0.001, "max": 10.0, "step": 0.005, "description": "Toleranzschwelle"},
            "use_time_filter": {"type": "bool", "default": True, "description": "Time Filter aktiv (Zeitfenster um ganze/halbe Stunde)"},
            "time_window_mins": {"type": "int", "default": 5, "min": 0, "max": 30, "step": 1, "description": "Time Filter Minuten (0 oder 30 um ganze/halbe Stunde)"},
            "line_color": {"type": "color", "default": "#2196F3", "description": "Farbe Grid-Linien"},
            "circle_color_std": {"type": "color", "default": "#FFEB3B", "description": "Farbe Standard-Hit (im Zeitfenster)"},
            "circle_color_active": {"type": "color", "default": "#E91E63", "description": "Farbe Hit in Aktivitätsfenster"},
            "show_lines": {"type": "bool", "default": True, "description": "Grid-Linien anzeigen"},
            "show_circles": {"type": "bool", "default": True, "description": "Hits anzeigen"},
            "prox_level1": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 1"},
            "prox_level2": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 2"},
            "prox_level3": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 3"},
            "prox_level4": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 4"},
            "prox_level5": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 5"},
            "prox_level6": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "description": "Custom Level 6"},
        }

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> FeatureCalculateResult:
        if df.empty:
            return {"feature_store_payload": {}, "chart_render_payload": {}}

        p = self.validate_params(params)
        step = p["grid_step"]
        threshold = p["proximity_threshold"]
        use_time_filter = bool(p["use_time_filter"])
        time_window_mins = int(p["time_window_mins"])

        min_price = df["low"].min()
        max_price = df["high"].max()

        start_lvl = np.floor(min_price / step) * step
        end_lvl = np.ceil(max_price / step) * step
        levels = list(np.arange(start_lvl, end_lvl + step, step))

        custom_lvls = [p[f"prox_level{i}"] for i in range(1, 7) if p[f"prox_level{i}"] > 0]
        all_levels = sorted(list(set(levels + custom_lvls)))

        lines_payload = []
        if p["show_lines"]:
            lines_payload = [
                {"price": float(lvl), "color": p["line_color"], "width": 1, "style": "solid"}
                for lvl in all_levels
            ]

        hit_circles = []
        feature_rows = []

        # Native UTC-Minute jeder Bar (konsistent zu GridLevelsFeature)
        bar_minutes = _bar_utc_minutes(df)
        minutes = list(bar_minutes)

        for idx, row in df.iterrows():
            close_price = row["close"]
            bar_time = int(row["time"])

            nearest_lvl = round(close_price / step) * step
            dist = abs(close_price - nearest_lvl)
            is_hit = dist <= threshold

            # Zeitfenster um ganze Stunde (Minute 0) UND halbe Stunde (Minute 30)
            # – identische native UTC-Logik wie der Alt-Indikator (grid.py).
            row_m = minutes[idx]
            row_in_time = (
                _f_in_window_around(row_m, 0, time_window_mins)
                or _f_in_window_around(row_m, 30, time_window_mins)
            )
            is_time_window_active = row_in_time if use_time_filter else True

            if is_hit and p["show_circles"]:
                # Farblogik identisch zum Alt-Indikator:
                # - Zeitfilter INAKTIV: alle Proximity-Punkte gelb
                # - Zeitfilter AKTIV: Punkte im Fenster gelb, ausserhalb fuchsia
                if use_time_filter and not row_in_time:
                    color = p["circle_color_active"]
                else:
                    color = p["circle_color_std"]

                hit_circles.append({
                    "time": bar_time,
                    "price": float(nearest_lvl),
                    "color": color,
                    "priority": 10,
                })

            feature_rows.append({
                "bar_time": bar_time,
                "nearest_level": float(nearest_lvl),
                "distance": float(dist),
                "is_hit": bool(is_hit),
                # Getimter Treffer für spätere Analysen (Phase 13 Services):
                # 1 wenn die Bar im Zeitfenster liegt (Minute 0/30 ± mins), sonst 0
                "is_time_window_active": int(is_time_window_active),
                "time_window_mins": time_window_mins,
                "use_time_filter": use_time_filter,
            })

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": feature_rows,
                "metadata": {"total_hits": len(hit_circles)},
            },
            "chart_render_payload": {
                "lines": lines_payload,
                "hit_circles": hit_circles,
            },
        }
