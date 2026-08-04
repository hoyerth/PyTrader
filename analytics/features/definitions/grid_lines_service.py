# analytics/features/definitions/grid_lines_service.py
"""
Service: GridLines (Phase 13 Schritt 6)

Paritäts-Service zur Alt-Implementierung (ehemals chart/indicators/grid.py,
am 04.08.2026 entfernt) – baut das Level-Raster EXAKT wie der Alt-Indikator.
Die Paritätsfunktionen liegen in `grid_math.py` (Phase 15 U15-B3, eingefrorene
Referenz-Kopien):

    center = f_round_to_custom_step(last_close, step_size)
    levels = {round(center + i * step_size, 6) | i in [-steps_around, steps_around]}
             + Custom-Levels (prox_level1..6, nur > 0)

Der Service liefert den chart_render_payload (lines) in identischer Struktur
wie der Alt-Indikator (is_custom-Färbung, width 1/3, style Solid) und schreibt
die Linienliste zusätzlich nach context.shared_state[self.instance_id] – der
nachgelagerte ProximityService liest sie von dort (depends_on).

KEINE eigenen Zeitkonzepte: Das native UTC-Zeitfenster (Minute 0/30 ±
time_window_mins) ist ausschließlich Sache des ProximityService (Farbgebung),
nicht dieses Services.

Capabilities: render=True, feature_store=False (schreibt NICHT in den Store).
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from analytics.features.definitions.grid_math import (
    build_grid_levels,
    f_round_to_custom_step,
)
from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)


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


def _extract_prox_levels(params: Dict[str, Any]) -> List[float]:
    """Custom-Levels aus den EINZELPARAMETERN prox_level1..6 (nur > 0).

    Parität zu grid_liquidity._extract_custom_levels(): Einzelwerte werden
    bevorzugt, wenn mindestens einer > 0 ist.
    """
    levels: List[float] = []
    for i in range(1, 7):
        v = params.get(f"prox_level{i}")
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0.0:
            levels.append(round(fv, 6))
    return levels


def custom_levels_from_params(params: Dict[str, Any]) -> List[float]:
    """Custom-Levels aus params: bevorzugt prox_level1..6 (Einzelparameter,
    Alt-/Neu-Speicherung im Service-Modell), sonst custom_levels (Liste/String).

    USER-REQ: P14-01 Nachtrag - Sets koennen die 6 Level EINZELN
    (prox_level1..6) ODER als Aggregat (custom_levels) gespeichert haben -
    beide Formen werden gelesen.
    """
    levels = _extract_prox_levels(params)
    if levels:
        return levels
    return _parse_custom_levels(params.get("custom_levels"))


def map_custom_levels_to_prox_levels(params: Dict[str, Any]) -> Dict[str, float]:
    """Mappt gespeicherte custom_levels (Liste/String) auf prox_level1..6.

    USER-REQ: P14-01 Nachtrag - damit Alt-Sets mit Aggregat-Speicherung im
    Editor (6 Level-Felder) ihre Werte weiterhin anzeigen. Nur Werte > 0
    werden gemappt; max. 6 Level.
    """
    out: Dict[str, float] = {}
    for i, v in enumerate(_parse_custom_levels(params.get("custom_levels"))[:6], start=1):
        if v > 0.0:
            out[f"prox_level{i}"] = float(v)
    return out


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
            "description": "Baut das Grid-Raster in Parität zum Alt-Grid (Center ± steps_around × step_size + Custom-Levels)",
            "author": "PyTrader AI",
            "tags": ["grid", "lines", "raster"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Baut das Level-Raster exakt wie der Alt-Grid-Indikator "
                                "(Paritätsfunktionen in grid_math.py) und "
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
        # USER-REQ: P14-01 Nachtrag - die 6 Custom-Levels werden im Editor als
        # EINZELPARAMETER prox_level1..6 (Level 1..6, wie grid_liquidity)
        # gerendert. custom_levels bleibt im parameter_schema (interne Pipeline
        # & Aggregat-Speicherung), ist aber NICHT in der Darstellungs-Reihenfolge
        # -> wird im Editor nicht als Komma-Feld gerendert.
        return [
            "show_lines", "line_color",
            "step_size", "steps_around",
            "prox_level1", "prox_level2", "prox_level3",
            "prox_level4", "prox_level5", "prox_level6",
        ]

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "show_lines": "Linien anzeigen",
            "line_color": "Linien-Farbe",
            "step_size": "Rasterabstand",
            "steps_around": "Level-Anzahl (je Seite)",
            "prox_level1": "Level 1",
            "prox_level2": "Level 2",
            "prox_level3": "Level 3",
            "prox_level4": "Level 4",
            "prox_level5": "Level 5",
            "prox_level6": "Level 6",
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
            # USER-REQ: P14-01 Nachtrag - die 6 Custom-Levels werden im Editor
            # als EINZELPARAMETER prox_level1..6 gerendert (Level 1..6). Das
            # Aggregat custom_levels bleibt im Schema erhalten - die interne
            # Pipeline (GridLiquidityIndicator._build_set_definition) und
            # Alt-Sets speichern die Level als Liste/String. calculate() liest
            # beide Formen (custom_levels_from_params).
            "custom_levels": {
                "type": "str", "default": "",
                "description": "Custom-Levels, nur > 0 (prox_level1..6 ↔ custom_levels)",
            },
            "prox_level1": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 1"},
            "prox_level2": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 2"},
            "prox_level3": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 3"},
            "prox_level4": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 4"},
            "prox_level5": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 5"},
            "prox_level6": {"type": "float", "default": 0.0, "min": 0.0, "max": 100000.0, "step": 0.01, "description": "Custom Level 6"},
            "show_lines": {
                "type": "bool", "default": True, "description": "Grid-Linien anzeigen",
            },
            "line_color": {
                "type": "color", "default": "",
                "description": "Linien-Farbe (leer = Paritäts-Styling aus grid_math.py)",
            },
        }

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Baut das Raster in Parität zum Alt-Grid (grid_math.py) und schreibt
        die Linienliste nach context.shared_state[self.instance_id] (Namespace-isoliert)."""
        if df is None or df.empty:
            return {"feature_store_payload": {}, "chart_render_payload": {"lines": [], "hit_circles": []}}

        p = self.validate_params(params)
        step_size = float(p["step_size"])
        steps_around = int(p["steps_around"])
        show_lines = bool(p["show_lines"])
        line_color = str(p.get("line_color") or "").strip()

        custom_levels = custom_levels_from_params(p)
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
