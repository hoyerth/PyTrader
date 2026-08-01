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
            "line_color": {"type": "color", "default": "#2196F3", "description": "Farbe Grid-Linien"},
            "circle_color_std": {"type": "color", "default": "#FFEB3B", "description": "Farbe Standard-Hit"},
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

        for idx, row in df.iterrows():
            close_price = row["close"]
            bar_time = int(row["time"])

            nearest_lvl = round(close_price / step) * step
            dist = abs(close_price - nearest_lvl)
            is_hit = dist <= threshold

            if is_hit and p["show_circles"]:
                dt = pd.to_datetime(bar_time, unit='s')
                # ROADMAP-PLATZHALTER: 8-16h ist NUR ein Beispiel für die
                # Aktiv-Farb-Logik. Das native UTC-Zeitfenster (Minute 0/30 ±
                # time_window_mins) in grid_levels.py bleibt davon UNBERÜHRT.
                is_active_window = 8 <= dt.hour <= 16
                color = p["circle_color_active"] if is_active_window else p["circle_color_std"]

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
