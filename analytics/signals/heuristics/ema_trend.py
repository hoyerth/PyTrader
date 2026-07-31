# analytics/signals/heuristics/ema_trend.py
"""
Signal: EMA-Trend
Bewertet die Trendstärke anhand der EMA-Differenz (ema_diff).
- Stark positiv (> Schwellwert) → hoher Confidence für Aufwärtstrend
- Stark negativ (< -Schwellwert) → hoher Confidence für Abwärtstrend
- Nah an 0 → niedriger Confidence (kein klarer Trend)
"""

from typing import Any, Dict, Optional
import pandas as pd
import numpy as np
from analytics.engine.base_definition import SignalDefinition


class EMATrendSignal(SignalDefinition):
    @property
    def signal_id(self) -> str:
        return "ema_trend_v1"

    @property
    def display_name(self) -> str:
        return "EMA Trend Signal"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "threshold_pct": 0.3,       # Schwellwert in Prozent (absolut)
            "max_confidence": 1.0,       # Maximaler Confidence bei starkem Trend
            "direction": "both",         # 'long', 'short', 'both'
        }

    @property
    def param_descriptions(self) -> Dict[str, str]:
        return {
            "threshold_pct": "Schwellwert: |ema_diff| > threshold ergibt Confidence > 0",
            "max_confidence": "Maximaler Confidence-Wert bei sehr starkem Trend",
            "direction": "Richtung: 'long', 'short' oder 'both'",
        }

    @property
    def required_features(self) -> list:
        return ["ema_diff"]

    @property
    def live_op(self) -> bool:
        return False

    def evaluate(self, df_features: pd.DataFrame, params: Optional[Dict[str, Any]] = None) -> pd.Series:
        p = {**self.default_params, **(params or {})}
        threshold = float(p["threshold_pct"])
        max_conf = float(p["max_confidence"])
        direction = str(p["direction"])

        if "ema_diff" not in df_features.columns:
            raise ValueError("EMA-Trend Signal benötigt 'ema_diff' im Feature-Store")

        ema = df_features["ema_diff"].values
        abs_ema = np.abs(ema)

        # Confidence linear von 0 bei threshold bis max_conf bei 3*threshold
        confidence = np.clip((abs_ema - threshold) / (3 * threshold - threshold), 0.0, 1.0)
        confidence = confidence * max_conf

        # Richtungsfilter
        if direction == "long":
            confidence[ema < 0] = 0.0
        elif direction == "short":
            confidence[ema > 0] = 0.0

        return pd.Series(confidence, index=df_features.index)
