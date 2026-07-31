# analytics/features/definitions/ema_diff.py
"""
Feature: EMA-Differenz (ema_diff)
Berechnet die normalisierte Differenz zwischen zwei EMAs (schnell - langsam).
"""

from typing import Any, Dict
import pandas as pd
from analytics.features.base_feature import BaseFeature


class EMADiffFeature(BaseFeature):
    @property
    def name(self) -> str:
        return "ema_diff"

    @property
    def description(self) -> str:
        return "Normalisierte Differenz zwischen schnellem und langsamem EMA"

    def _calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
        fast_period = params.get("fast_period", 12)
        slow_period = params.get("slow_period", 26)

        ema_fast = df["close"].ewm(span=fast_period, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow_period, adjust=False).mean()

        diff = ema_fast - ema_slow
        # Normalisierung auf close-Preis (Prozentuale Abweichung)
        normalized = (diff / df["close"]) * 100.0

        return normalized
