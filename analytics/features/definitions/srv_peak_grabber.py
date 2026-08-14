# analytics/features/definitions/srv_peak_grabber.py
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from analytics.features.definitions.grabber_kernel import run_grabber_kernel
from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

_PEAK_GRABBER_SCHEMA: Dict[str, ParameterSchema] = {
    "reversal_pct": {"type": "float", "default": 0.30, "min": 0.01, "max": 10.0, "step": 0.01, "description": "Reversal % für Trigger (z)"},
    "min_hold_bars": {"type": "int", "default": 3, "min": 1, "max": 1000, "step": 1, "description": "Min. Bars Haltedauer des Peaks"},
    "invalidation_bars": {"type": "int", "default": 5, "min": 1, "max": 10000, "step": 1, "description": "Beobachtungsfenster x (Bars)"},
    "invalidation_threshold_pct": {"type": "float", "default": 0.10, "min": 0.0, "max": 10.0, "step": 0.01, "description": "Toleranz y% vor Hard-Invalidation"},
    "require_proximity_window": {"type": "bool", "default": True, "description": "Nur im Yellow Window triggern"},
    # Gemeinsamer SL-Parameter (Parität zu srv_peak_finder): Das Set muss
    # BEIDEN Instanzen denselben Wert geben (Single Source: Indikator-Schema).
    "sl_offset_pct": {"type": "float", "default": 0.15, "min": 0.0, "max": 10.0, "step": 0.01, "description": "SL-Puffer über/unter Peak (%) – muss srv_peak_finder entsprechen"},
    # Optionaler Test-Override (NICHT in parameter_order): JSON-bool-Liste je
    # Bar. Fehlt er, leitet der Service selbst ab (_derive_yellow_window, Frage 3).
    "is_yellow_window": {"type": "str", "default": "", "description": "Intern/Test: JSON-bool-Liste je Bar (Override)"},
}


class PeakGrabberService(PluginFeature):
    """Batch-Pfad der Peak-Grabber-State-Machine (stateless, Kernel)."""

    @property
    def plugin_id(self) -> str:
        return "srv_peak_grabber"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, str]:
        return {
            "category": "Swing Points/Peak Grabber",
            "display_name": "Peak Grabber",
            "indicator_name": "Ind_Peak",
            "indicator_id": "ind_peak",
            "description": "Gated State-Machine: BUY/SELL-Trigger & -Updates aus Peaks",
            "author": "PyTrader AI",
            "tags": ["peak", "grabber", "signal"],
            "condition_rules": [
                "Startzustand IDLE; Bar 0 = Bootstrap (First-Peak-Skip)",
                "Neuer Peak im Fenster: kleine Überschreitung -> ARMED/UPDATE, grosse -> INVALIDATED",
                "Reversal >= z% nach min_hold_bars -> TRIGGERED",
                "is_yellow_window = Zone-Hit ∧ Zeitfenster (±5 min um :00/:30); Fallback True ohne Proximity-Signal (Frage 3)",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": True,
            "batch": True,
            "live": False,            # Live läuft im Indikator
            "feature_store": True,
            "render": False,          # P16.01: Styling baut der Indikator
        }

    @property
    def dependencies(self) -> List[str]:
        return ["srv_peak_finder"]

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        return {k: dict(v) for k, v in _PEAK_GRABBER_SCHEMA.items()}

    # -------------------------------------------------- Frage 3: Yellow-Fenster
    @staticmethod
    def _bar_in_time_window(epoch_sec: int) -> bool:
        """Wanduhr-Minute in [0±5] oder [30±5] (Präambel 8: MT5-Epochs sind
        Berlin-Wanduhr-encoded; Muster `_f_in_window_around`, srv_proximity)."""
        minute = (epoch_sec // 60) % 60

        def _in(center: int, span: int = 5) -> bool:
            lower = center - span
            upper = center + span
            if lower < 0:
                return minute >= (60 + lower) or minute <= upper
            if upper > 59:
                return minute >= lower or minute <= (upper - 60)
            return lower <= minute <= upper

        return _in(0) or _in(30)

    @staticmethod
    def _extract_prox_zone_map(context: Optional[PluginContext]):
        """Zone-Hit (`levels_hit` ≠ leer) je bar_time aus der srv_proximity-
        Instanz im `context.shared_state`. None = kein Proximity-Signal."""
        if context is None:
            return None
        for _key, value in (context.shared_state or {}).items():
            if not isinstance(value, dict):
                continue
            if isinstance(value.get("records"), list):
                rows = value["records"]
                if any("levels_hit" in r for r in rows):
                    return {
                        int(r.get("bar_time", 0)): bool(r.get("levels_hit"))
                        for r in rows
                    }
            if "levels_hit" in value:  # Einzel-Record (Live)
                return {
                    int(value.get("bar_time", 0)): bool(
                        value.get("levels_hit"))
                }
        return None

    def _derive_yellow_window(
        self, df: pd.DataFrame, context: Optional[PluginContext]
    ) -> List[bool]:
        """Frage 3: `is_yellow_window := is_in_proximity_zone ∧
        is_in_time_window(±5 min um :00/:30)`.

        `is_in_proximity_zone` aus der srv_proximity-Instanz im Context
        (Zone-Hit-Records); **fehlt das Proximity-Signal → Fallback `True`**
        (Gate offen). `is_in_time_window` wird immer aus der Wanduhr-Minute
        der Bar hergeleitet (Präambel 8)."""
        zone_map = self._extract_prox_zone_map(context)
        out: List[bool] = []
        for t in df["time"]:
            epoch = int(t)
            in_win = self._bar_in_time_window(epoch)
            zone = True if zone_map is None else bool(
                zone_map.get(epoch, False))
            out.append(bool(zone and in_win))
        return out

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        if df is None or df.empty:
            return {"feature_store_payload": {}}
        p = self.validate_params(params)

        # Frage 3: is_yellow_window wird IM SERVICE hergeleitet
        # (_derive_yellow_window, Zone-Hit ∧ Zeitfenster, Fallback True).
        # Optionaler Test-Override: params["is_yellow_window"] als JSON-bool-
        # Liste (nicht in parameter_order, siehe Schema-Kommentar).
        yw_raw = p.get("is_yellow_window")
        if isinstance(yw_raw, str) and yw_raw.strip():
            import json as _json
            yw_list = _json.loads(yw_raw)
        elif isinstance(yw_raw, (list, tuple)):
            yw_list = list(yw_raw)
        else:
            yw_list = self._derive_yellow_window(df, context)
        yw = np.asarray([bool(x) for x in yw_list], dtype=bool)

        highs = df["high"].to_numpy(dtype=np.float64)
        lows = df["low"].to_numpy(dtype=np.float64)
        closes = df["close"].to_numpy(dtype=np.float64)

        # Peak/SL-Arrays aus dem depends_on-shared_state (srv_peak_finder).
        if context is not None and context.depends_on:
            src = context.shared_state.get(context.depends_on[0]) or {}
        else:
            src = {}
        sl_offset_pct = float((p.get("sl_offset_pct") or 0.15))
        if src and "sl_highs" in src:
            sl_highs = src["sl_highs"]
            sl_lows = src["sl_lows"]
            peak_highs = src["peak_highs"]
            peak_lows = src["peak_lows"]
        else:
            # Fallback: eigene Peak-Berechnung (Parität srv_peak_finder).
            peak_highs = np.maximum.accumulate(highs)
            peak_lows = np.minimum.accumulate(lows)
            f_h = 1.0 + (sl_offset_pct / 100.0)
            f_l = 1.0 - (sl_offset_pct / 100.0)
            sl_highs = peak_highs * f_h
            sl_lows = peak_lows * f_l

        signals, sl_prices, peak_prices = run_grabber_kernel(
            highs, lows, closes, yw,
            float(p["reversal_pct"]),
            int(p["min_hold_bars"]),
            int(p["invalidation_bars"]),
            float(p["invalidation_threshold_pct"]),
            sl_offset_pct,
            bool(p["require_proximity_window"]),
            True,  # gate_active: Button-Steuerung ist Aufgabe des Aufrufers
        )

        records: List[Dict[str, Any]] = []
        times = df["time"].to_numpy()
        for i in range(len(df)):
            if signals[i] == 0:
                continue
            records.append({
                "bar_time": int(times[i]),
                "signal": int(signals[i]),
                "signal_label": _SIGNAL_LABELS.get(int(signals[i]), "?"),
                "sl_price": float(sl_prices[i]),
                "peak_price": float(peak_prices[i]),
                "peak_high": float(peak_highs[i]),
                "peak_low": float(peak_lows[i]),
                "is_yellow_window": bool(yw[i]),
            })
        n_triggers = int(np.count_nonzero((signals == 1) | (signals == -1)))
        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {
                    "schema_version": "1.0.0",
                    "statistics": {
                        "signal_count": len(records),
                        "trigger_count": n_triggers,
                    },
                },
            },
        }


_SIGNAL_LABELS: Dict[int, str] = {
    1: "BUY_TRIGGER",
    2: "BUY_UPDATE",
    -1: "SELL_TRIGGER",
    -2: "SELL_UPDATE",
}
