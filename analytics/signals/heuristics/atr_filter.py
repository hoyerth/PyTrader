# analytics/signals/heuristics/atr_filter.py
"""
Signal: ATR-Filter
Bewertet die Volatilitätssituation anhand des normalisierten ATR.
- Hoher ATR (> Schwellwert) → hoher Confidence (Ausbruch/Volatilität)
- Niedriger ATR → niedriger Confidence (Seitwärts/Konsolidierung)
"""

from typing import Any, Dict, Optional
import pandas as pd
import numpy as np
from analytics.engine.base_definition import SignalDefinition


class ATRFilterSignal(SignalDefinition):
    @property
    def signal_id(self) -> str:
        return "atr_filter_v1"

    @property
    def display_name(self) -> str:
        return "ATR Volatility Filter"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "threshold_pct": 0.8,       # ATR-Schwellwert in Prozent
            "max_confidence": 1.0,       # Maximaler Confidence
            "mode": "high_volatility",   # 'high_volatility' oder 'low_volatility'
        }

    @property
    def param_descriptions(self) -> Dict[str, str]:
        return {
            "threshold_pct": "ATR-Schwellwert: ATR > threshold ergibt Confidence > 0",
            "max_confidence": "Maximaler Confidence-Wert",
            "mode": "Modus: 'high_volatility' oder 'low_volatility'",
        }

    @property
    def required_features(self) -> list:
        return ["atr_normalized"]

    @property
    def live_op(self) -> bool:
        return False

    def evaluate(self, df_features: pd.DataFrame, params: Optional[Dict[str, Any]] = None) -> pd.Series:
        p = {**self.default_params, **(params or {})}
        threshold = float(p["threshold_pct"])
        max_conf = float(p["max_confidence"])
        mode = str(p["mode"])

        if "atr_normalized" not in df_features.columns:
            raise ValueError("ATR-Filter Signal benötigt 'atr_normalized' im Feature-Store")

        atr = df_features["atr_normalized"].values

        if mode == "high_volatility":
            # Hoher ATR → hoher Confidence
            confidence = np.clip((atr - threshold) / (3 * threshold - threshold), 0.0, 1.0)
        else:
            # Niedriger ATR → hoher Confidence
            confidence = np.clip((threshold - atr) / (threshold - 0.1), 0.0, 1.0)

        confidence = confidence * max_conf
        return pd.Series(confidence, index=df_features.index)
