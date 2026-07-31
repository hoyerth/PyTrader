# analytics/features/definitions/atr_normalized.py
"""
Feature: Normalisierter ATR (atr_normalized)
Berechnet den Average True Range, normalisiert auf den Schlusskurs in Prozent.
"""

from typing import Any, Dict
import pandas as pd
import numpy as np
from analytics.features.base_feature import BaseFeature


class ATRNormalizedFeature(BaseFeature):
    @property
    def name(self) -> str:
        return "atr_normalized"

    @property
    def description(self) -> str:
        return "Average True Range, normalisiert auf close in Prozent"

    def _calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> pd.Series:
        period = params.get("period", 14)

        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        # True Range
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]

        tr1 = high - low
        tr2 = np.abs(high - prev_close)
        tr3 = np.abs(low - prev_close)
        tr = np.maximum(np.maximum(tr1, tr2), tr3)

        # ATR als EMA der True Range
        atr = pd.Series(tr).ewm(span=period, adjust=False).mean()

        # Normalisierung auf close in Prozent
        normalized = (atr / df["close"]) * 100.0

        return normalized
