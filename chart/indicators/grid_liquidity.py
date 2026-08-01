# chart/indicators/grid_liquidity.py
"""
NEUER Grid-Indikator mit Plugin-Architektur (Phase 12 Schritt 5).

Konsumiert das GridLiquidityFeature-Plugin über den PluginExecutor und gibt
dessen chart_render_payload zurück (lines + hit_circles). Die Service-Logik
liegt im Plugin (analytics/features/definitions/grid_liquidity.py); dieser
Indikator ist nur der visuelle Adapter (Basis-Parameter über den generischen
indicator_dialog.py, Interim bis zum neuen Property-Fenster nach Phase 12).

Der bestehende chart/indicators/grid.py bleibt UNVERÄNDERT und läuft als
Alt-Implementierung parallel (indicator_id 'grid').
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from .base_indicator import BaseIndicator
from analytics.features.feature_builder import PluginExecutor, PluginRegistry


class GridLiquidityIndicator(BaseIndicator):

    def __init__(self) -> None:
        super().__init__()
        self._executor: PluginExecutor = PluginExecutor()
        self._plugin_id: str = "grid_liquidity"

    @property
    def indicator_id(self) -> str:
        return "grid_liquidity"

    @property
    def display_name(self) -> str:
        return "Grid Liquidity (Plugin)"

    @property
    def default_params(self) -> Dict[str, Any]:
        """Standard-Parameter direkt aus dem Plugin-Schema (Single Source of Truth)."""
        return dict(PluginRegistry().get(self._plugin_id).default_params)

    @property
    def param_options(self) -> Dict[str, List[Any]]:
        return {}

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "grid_step": "Rasterabstand",
            "proximity_threshold": "Toleranz",
            "line_color": "Linien-Farbe",
            "circle_color_std": "Std-Hit-Farbe",
            "circle_color_active": "Aktiv-Hit-Farbe",
            "show_lines": "Linien anzeigen",
            "show_circles": "Circles anzeigen",
            "prox_level1": "Level 1",
            "prox_level2": "Level 2",
            "prox_level3": "Level 3",
            "prox_level4": "Level 4",
            "prox_level5": "Level 5",
            "prox_level6": "Level 6",
        }

    @property
    def param_layout(self) -> Optional[List[Any]]:
        return [
            ("Raster & Toleranz", ["grid_step", "proximity_threshold"]),
            ("Farben", ["line_color", "circle_color_std", "circle_color_active"]),
            ("Anzeige", ["show_lines", "show_circles"]),
            ("Custom Levels 1-3", ["prox_level1", "prox_level2", "prox_level3"]),
            ("Custom Levels 4-6", ["prox_level4", "prox_level5", "prox_level6"]),
        ]

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
        """Führt das GridLiquidityFeature-Plugin über den PluginExecutor aus und
        reicht dessen chart_render_payload als Zeichnungsdaten durch."""
        empty_result: Dict[str, Any] = {
            "lines": [],
            "hit_circles": [],
            "status_info": {"in_time_window": False, "active_hits": []},
        }
        if df is None or df.empty:
            return empty_result

        try:
            result = self._executor.execute(self._plugin_id, df, params)
        except Exception as e:
            print(f"⚠️ [GridLiquidityIndicator] Plugin-Ausführung fehlgeschlagen: {e}")
            return empty_result

        crp = result.get("chart_render_payload", {}) if isinstance(result, dict) else {}

        lines = crp.get("lines", [])
        hit_circles = crp.get("hit_circles", [])
        return {
            "lines": lines,
            "hit_circles": hit_circles,
            "status_info": {"in_time_window": False, "active_hits": []},
        }
