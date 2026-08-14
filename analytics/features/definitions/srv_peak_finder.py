# analytics/features/definitions/srv_peak_finder.py
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

_PEAK_FINDER_SCHEMA: Dict[str, ParameterSchema] = {
    "sl_offset_pct": {
        "type": "float", "default": 0.15, "min": 0.0, "max": 10.0,
        "step": 0.01, "description": "SL-Puffer über/unter Peak (%)",
    },
}


class PeakFinderService(PluginFeature):
    """Vektorisierte Peak-Tracking & SL-Berechnung (Hist-Batch, stateless)."""

    @property
    def plugin_id(self) -> str:
        return "srv_peak_finder"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, str]:
        return {
            "category": "Swing Points/Peak Grabber",
            "display_name": "Peak Finder",
            "indicator_name": "Ind_Peak",
            "indicator_id": "ind_peak",
            "description": "Running Highs/Lows samt SL-Offset (Batch, stateless)",
            "author": "PyTrader AI",
            "tags": ["peak", "swing", "stop-loss"],
            "condition_rules": [
                "peak_high = maximum.accumulate(high)",
                "peak_low  = minimum.accumulate(low)",
                "sl_high = peak_high * (1 + sl_offset_pct/100)",
                "sl_low  = peak_low  * (1 - sl_offset_pct/100)",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": True,
            "batch": True,
            "live": False,            # Live läuft im Indikator (PeakGrabberLiveState)
            "feature_store": True,
            "render": False,          # P16.01: Styling baut der Indikator
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        return {k: dict(v) for k, v in _PEAK_FINDER_SCHEMA.items()}

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        if df is None or df.empty:
            return {"feature_store_payload": {}}
        p = self.validate_params(params)
        highs = df["high"].to_numpy(dtype=np.float64)
        lows = df["low"].to_numpy(dtype=np.float64)

        peak_highs = np.maximum.accumulate(highs)
        peak_lows = np.minimum.accumulate(lows)
        f_h = 1.0 + (float(p["sl_offset_pct"]) / 100.0)
        f_l = 1.0 - (float(p["sl_offset_pct"]) / 100.0)

        records: List[Dict[str, Any]] = []
        times = df["time"].to_numpy()
        for i in range(len(df)):
            records.append({
                "bar_time": int(times[i]),
                "peak_high": float(peak_highs[i]),
                "peak_low": float(peak_lows[i]),
                "sl_high": float(peak_highs[i] * f_h),
                "sl_low": float(peak_lows[i] * f_l),
            })
        # Shared-State für nachgelagerte srv_peak_grabber (depends_on):
        if context is not None and context.instance_id:
            context.shared_state[context.instance_id] = {
                "peak_highs": peak_highs,
                "peak_lows": peak_lows,
                "sl_highs": peak_highs * f_h,
                "sl_lows": peak_lows * f_l,
                "records": records,
            }
        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {"schema_version": "1.0.0"},
            },
        }
