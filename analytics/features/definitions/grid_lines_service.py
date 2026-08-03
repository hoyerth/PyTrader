# analytics/features/definitions/grid_lines_service.py
"""
Service: GridLines (Phase 13 Schritt 6)

Paritäts-Service zur Alt-Implementierung chart/indicators/grid.py – baut das
Level-Raster EXAKT wie grid.py (Zentrierung auf dem letzten Close):

    center = f_round_to_custom_step(last_close, step_size)
    levels = {round(center + i * step_size, 6) | i in [-steps_around, steps_around]}
             + Custom-Levels (prox_level1..6, nur > 0)

Der Service liefert den chart_render_payload (lines) in identischer Struktur
wie grid.py (is_custom-Färbung, width 1/3, style Solid) und schreibt die
Linienliste zusätzlich nach context.shared_state[self.instance_id] – der
nachgelagerte ProximityService liest sie von dort (depends_on).

KEINE eigenen Zeitkonzepte: Das native UTC-Zeitfenster (Minute 0/30 ±
time_window_mins) ist ausschließlich Sache des ProximityService (Farbgebung),
nicht dieses Services.

Capabilities: render=True, feature_store=False (schreibt NICHT in den Store).
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)


def f_round_to_custom_step(price: float, step: float) -> float:
    """Identisch zu chart/indicators/grid.py – Rundung auf das nächste
    Vielfache von step (Paritäts-Anforderung)."""
    if step <= 0:
        return price
    inv_step = 1.0 / step
    return round(price * inv_step) / inv_step


def build_grid_levels(
    last_close: float,
    step_size: float,
    steps_around: int,
    custom_levels: Optional[List[float]] = None,
) -> List[float]:
    """Sortierte Level-Liste (absteigend) – exakte Parität zu grid.py.

    grid.py:
      center_price = f_round_to_custom_step(last_close, step_size)
      grid_levels  = {round(center_price + i*step_size, 6)
                      | i in range(-steps_around, steps_around+1)}
      + {round(c_lvl, 6) | c_lvl in custom_levels, c_lvl > 0.0}
    """
    center_price = f_round_to_custom_step(last_close, step_size)
    grid_levels: set = set()
    for i in range(-steps_around, steps_around + 1):
        grid_levels.add(round(center_price + (i * step_size), 6))
    for c_lvl in (custom_levels or []):
        v = float(c_lvl)
        if v > 0.0:
            grid_levels.add(round(v, 6))
    return sorted(list(grid_levels), reverse=True)


def _parse_custom_levels(raw: Any) -> List[float]:
    """Akzeptiert Liste/Tupel ODER Komma-/Semikolon-String; nur Werte > 0."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [round(float(x), 6) for x in raw if _to_float(x, 0.0) > 0.0]
    if isinstance(raw, str) and raw.strip():
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        return [round(float(x), 6) for x in parts if _to_float(x, 0.0) > 0.0]
    return []


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class GridLinesService(PluginFeature):

    @property
    def plugin_id(self) -> str:
        return "grid_lines"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, str]:
        return {
            "category": "Grid",
            "display_name": "Grid Lines",
            "description": "Baut das Grid-Raster in Parität zu grid.py (Center ± steps_around × step_size + Custom-Levels)",
            "author": "PyTrader AI",
            "tags": ["grid", "lines", "raster"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Baut das Level-Raster exakt wie chart/indicators/"
                                "grid.py (Zentrierung auf dem letzten Close) und "
                                "schreibt die Linienliste in den shared_state "
                                "für nachgelagerte Services (depends_on).",
            "condition_rules": [
                "Zentrierung: runden(close / step_size) × step_size",
                "Levels: center + i × step_size für i in [-steps_around, steps_around]",
                "Custom-Levels nur > 0",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": True,
            "batch": True,
            "live": False,
            "feature_store": False,  # GridLines rendert nur, schreibt NICHT in den Store
            "render": True,
        }

    # --- Single Source of Truth fürs Prop-Fenster (Phase 13 Schritt 5) -------
    @property
    def parameter_order(self) -> List[str]:
        return [
            "show_lines", "line_color",
            "step_size", "steps_around", "custom_levels",
        ]

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "show_lines": "Linien anzeigen",
            "line_color": "Linien-Farbe",
            "step_size": "Rasterabstand",
            "steps_around": "Level-Anzahl (je Seite)",
            "custom_levels": "Custom-Levels (kommagetrennt)",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        return {
            "step_size": {
                "type": "float", "default": 0.5, "min": 0.01, "max": 1000.0,
                "step": 0.05, "description": "Rasterabstand (prox_stepSize ↔ step_size)",
            },
            "steps_around": {
                "type": "int", "default": 4, "min": 0, "max": 100,
                "step": 1, "description": "Level ober-/unterhalb des Zentrums (prox_stepsAround ↔ steps_around)",
            },
            # Listeneingabe wird bewusst als 'str' deklariert, damit der
            # Schema-Validator sie unverändert durchreicht (Liste ODER String).
            "custom_levels": {
                "type": "str", "default": "",
                "description": "Custom-Levels, nur > 0 (prox_level1..6 ↔ custom_levels)",
            },
            "show_lines": {
                "type": "bool", "default": True, "description": "Grid-Linien anzeigen",
            },
            "line_color": {
                "type": "color", "default": "",
                "description": "Linien-Farbe (leer = Paritäts-Styling aus grid.py)",
            },
        }

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Baut das Raster in Parität zu grid.py und schreibt die Linienliste
        nach context.shared_state[self.instance_id] (Namespace-isoliert)."""
        if df is None or df.empty:
            return {"feature_store_payload": {}, "chart_render_payload": {"lines": [], "hit_circles": []}}

        p = self.validate_params(params)
        step_size = float(p["step_size"])
        steps_around = int(p["steps_around"])
        show_lines = bool(p["show_lines"])
        line_color = str(p.get("line_color") or "").strip()

        custom_levels = _parse_custom_levels(p.get("custom_levels"))
        sorted_levels = build_grid_levels(
            last_close=float(df.iloc[-1]["close"]),
            step_size=step_size,
            steps_around=steps_around,
            custom_levels=custom_levels,
        )

        # --- Lines-Payload (exakte Parität zu grid.py) -----------------------
        lines_payload: List[Dict[str, Any]] = []
        if show_lines:
            for lvl in sorted_levels:
                is_custom = any(abs(lvl - c_lvl) < 0.0001 for c_lvl in custom_levels)
                if line_color:
                    color = line_color
                else:
                    # Paritäts-Styling: Custom-Levels kräftiger + dünner (mit ★)
                    color = "rgba(33, 150, 243, 0.9)" if is_custom else "rgba(33, 150, 243, 0.5)"
                lines_payload.append({
                    "price": lvl,
                    "color": color,
                    "width": 1 if is_custom else 3,
                    "style": "Solid",
                    "is_custom": is_custom,
                })

        # Linienliste in den Namespace schreiben – der ProximityService liest
        # sie von dort (depends_on). Atomare Zuweisung (neue Liste).
        if context is not None and context.instance_id:
            context.shared_state[context.instance_id] = list(lines_payload)

        return {
            "feature_store_payload": {},
            "chart_render_payload": {
                "lines": lines_payload,
                "hit_circles": [],
            },
        }
