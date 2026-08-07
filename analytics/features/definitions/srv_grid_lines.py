# analytics/features/definitions/srv_grid_lines.py
"""
Service: GridLines (Phase 13 Schritt 6) – Naming Convention 16.08.01: srv_

Paritäts-Service zur Alt-Implementierung (ehemals chart/indicators/grid.py,
am 04.08.2026 entfernt) – baut das Level-Raster EXAKT wie der Alt-Indikator.
Die Paritätsfunktionen liegen in `grid_math.py` (Phase 15 U15-B3, eingefrorene
Referenz-Kopien):

    center = f_round_to_custom_step(last_close, step_size)
    levels = {round(center + i * step_size, 6) | i in [-steps_around, steps_around]}
             + Custom-Levels (prox_level1..6, nur > 0)

Der Service liefert KEINEN chart_render_payload mehr (Phase 16 P16.01, E2/E5:
render=False) – er schreibt ausschliesslich eine REINE Level-Liste
(`[{price}, ...]`, ohne Farben/Styling) nach context.shared_state[self.instance_id];
der nachgelagerte ProximityService liest sie von dort (depends_on), der
Indikator (chart/indicators/ind_fixed_grid_proximity.py) baut daraus in
`build_chart_render_payload()` das Styling (is_custom-Färbung, width 1/3,
style Solid – Parität zum Alt-Grid).

KEINE eigenen Zeitkonzepte: Das native UTC-Zeitfenster (Minute 0/30 ±
time_window_mins) ist ausschließlich Sache des ProximityService (Farbgebung),
nicht dieses Services.

Capabilities: render=False (P16.01), feature_store=True (schreibt Grid-Level je Bar in den Store).

05.08.2026 (U15-E, echte Feature-Store-Payloads): `calculate()` erzeugt jetzt
ZWINGEND ein gefuelltes `feature_store_payload` mit `feature_id="srv_grid_lines"`,
`plugin_version` und `records` je Bar:
    {"bar_time", "grid_nearest_level", "grid_step", "upper_level", "lower_level"}
  * grid_nearest_level = center = round(close / step_size) * step_size
  * upper_level        = center + step_size
  * lower_level        = center - step_size
Dadurch schreibt grid_lines (srv_grid_lines) bei der Ausfuehrung echte
mathematische Zeilen in analytics.duckdb (`feature_store`) – unabhaengig von
`show_lines` (das nur die RENDER-Darstellung steuert, nicht die
Daten-Mathematik).
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

    Parität zu ind_fixed_grid_proximity._extract_custom_levels(): Einzelwerte werden
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
        return "srv_grid_lines"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, str]:
        return {
            "category": "Grid",
            "display_name": "Grid Lines",
            # Phase 16 (06.08.2026): Zugehoeriger Indikator-Name fuer die Status-
            # Badges im MasterTree (der Service laeuft IN Ind_FixedGridProximity).
            "indicator_name": "Ind_FixedGridProximity",
            # Phase 16 (06.08.2026): indicator_id = indicators_state-Key des
            # zugehoerigen Indikators. ServiceSelectorModel.is_active_in_chart()
            # prueft damit die Aktiv-Frage auf Indikator-Ebene (Tooltip
            # 'aktiv <Indikator>' statt nur 'im <Indikator>').
            "indicator_id": "ind_fixed_grid_proximity",

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
            # 05.08.2026 (U15-E): grid_lines schreibt jetzt echte Grid-Level
            # je Bar in den Store (feature_store_payload in calculate()).
            "feature_store": True,
            # Phase 16 (P16.01, E5): render=False - der Service liefert KEINEN
            # chart_render_payload mehr; der Indikator baut das Styling.
            "render": False,
        }

    # --- Single Source of Truth fürs Prop-Fenster (Phase 13 Schritt 5) -------
    @property
    def parameter_order(self) -> List[str]:
        # USER-REQ: P14-01 Nachtrag - die 6 Custom-Levels werden im Editor als
        # EINZELPARAMETER prox_level1..6 (Level 1..6, wie ind_fixed_grid_proximity)
        # gerendert. custom_levels bleibt im parameter_schema (interne Pipeline
        # & Aggregat-Speicherung), ist aber NICHT in der Darstellungs-Reihenfolge
        # -> wird im Editor nicht als Komma-Feld gerendert.
        # Phase 16 (P16.01): show_lines/line_color sind KEINE Service-Parameter
        # mehr (E1/E5) - sie steuern ausschliesslich die Render-Darstellung im
        # Indikator (chart/indicators/ind_fixed_grid_proximity.py).
        return [
            "step_size", "steps_around",
            "prox_level1", "prox_level2", "prox_level3",
            "prox_level4", "prox_level5", "prox_level6",
        ]

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
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
            # Pipeline (FixedGridProximityIndicator._build_set_definition) und
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
        }

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Baut das Raster in Parität zum Alt-Grid (grid_math.py) und schreibt
        die reine LEVEL-Liste nach context.shared_state[self.instance_id]
        (Namespace-isoliert).

        05.08.2026 (U15-E): Zusaetzlich wird ein gefuelltes feature_store_payload
        erzeugt (feature_id='srv_grid_lines', plugin_version, records je Bar mit
        bar_time / grid_nearest_level / grid_step / upper_level / lower_level) -
        grid_lines schreibt damit echte mathematische Grid-Level in den
        feature_store.

        Phase 16 (P16.01, E2): Der Service liefert KEINEN chart_render_payload
        mehr (render=False, E5). Die Level-Liste im shared_state enthaelt nur
        noch {price} - OHNE Farben/width/style. Das Render-Styling (Farben,
        Sichtbarkeit) baut ausschliesslich der Indikator
        (build_chart_render_payload in ind_fixed_grid_proximity.py)."""
        if df is None or df.empty:
            return {"feature_store_payload": {}}

        p = self.validate_params(params)
        step_size = float(p["step_size"])
        steps_around = int(p["steps_around"])

        custom_levels = custom_levels_from_params(p)
        sorted_levels = build_grid_levels(
            last_close=float(df.iloc[-1]["close"]),
            step_size=step_size,
            steps_around=steps_around,
            custom_levels=custom_levels,
        )

        # --- Reine Level-Liste (P16.01/E2, exakte Parität zu grid.py) --------
        # OHNE Farben/Styling - der nachgelagerte ProximityService liest nur
        # {price} (tracked_levels), der Indikator baut das Styling daraus.
        level_entries: List[Dict[str, Any]] = [
            {"price": lvl} for lvl in sorted_levels
        ]

        # Level-Liste in den Namespace schreiben – der ProximityService liest
        # sie von dort (depends_on). Atomare Zuweisung (neue Liste).
        if context is not None and context.instance_id:
            context.shared_state[context.instance_id] = list(level_entries)

        # --- Feature-Store-Payload (05.08.2026, U15-E) -----------------------
        # Pro Bar: grid_nearest_level = center (naechstes Grid-Level zum close),
        # upper/lower = center +/- step_size (deterministische Klammer um den
        # close). Unabhaengig von show_lines – die Mathematik gilt immer.
        #
        # Phase 16 (05.08.2026): Numpy-Vektorisierung statt df.iterrows() –
        # 10k+ Lookback-Bars laufen in wenigen Millisekunden. Exakte Paritaet:
        #   * NaN/Inf-close wird uebersprungen (Alt-Pfad: round(NaN) wirft
        #     ValueError -> continue; np.isfinite liefert dieselbe Maske).
        #   * np.round (half-to-even) ist identisch zu Pythons round() fuer
        #     dieselben float64-Werte; step<=0 liefert close unveraendert
        #     (f_round_to_custom_step-Parität).
        #   * Nicht int-konvertierbare 'time'-Spalten (z.B. datetime64) fallen
        #     auf den identischen Zeilenpfad zurueck.
        feature_rows: List[Dict[str, Any]] = []
        if "time" in df.columns and "close" in df.columns and len(df):
            try:
                import numpy as np
                closes = df["close"].to_numpy(dtype=np.float64)
                t_raw = df["time"].to_numpy()
                if np.issubdtype(t_raw.dtype, np.datetime64):
                    # Datetime-Spalte: Zeilenpfad (Paritaet zur Alt-Logik).
                    raise TypeError("datetime-Spalte -> Zeilen-Fallback")
                times = t_raw.astype(np.int64)
                valid = np.isfinite(closes)
                if step_size > 0:
                    inv_step = 1.0 / step_size
                    centers = np.round(closes[valid] * inv_step) / inv_step
                else:
                    centers = closes[valid]
                ts_list = times[valid].tolist()
                c_list = [float(c) for c in centers.tolist()]
                for bar_ts_int, center in zip(ts_list, c_list):
                    feature_rows.append({
                        "bar_time": int(bar_ts_int),
                        "grid_nearest_level": center,
                        "grid_step": step_size,
                        "upper_level": round(center + step_size, 6),
                        "lower_level": round(center - step_size, 6),
                    })
            except (TypeError, ValueError):
                # Fallback: Spalten nicht numpy-konvertierbar – identischer
                # Zeilenpfad wie vor der Vektorisierung.
                for _i, row in df.iterrows():
                    try:
                        close_val = float(row["close"])
                        center = f_round_to_custom_step(close_val, step_size)
                    except (TypeError, ValueError, KeyError):
                        continue
                    bar_ts = row.get("time")
                    if bar_ts is None:
                        continue
                    try:
                        bar_ts_int = int(bar_ts)
                    except (TypeError, ValueError):
                        continue
                    feature_rows.append({
                        "bar_time": bar_ts_int,
                        "grid_nearest_level": center,
                        "grid_step": step_size,
                        "upper_level": round(center + step_size, 6),
                        "lower_level": round(center - step_size, 6),
                    })

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": feature_rows,
                "metadata": {
                    "schema_version": "1.0.0",
                    "step_size": step_size,
                },
            },
        }
