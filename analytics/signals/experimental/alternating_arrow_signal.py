# analytics/signals/experimental/alternating_arrow_signal.py
"""
Experimental Signal: Alternating Arrow Signal
Erzeugt deterministisch alternierende Buy/Sell-Signale basierend auf dem
bar_time-Index. Dient als Test-Signal für die Live-Pipeline (Tick -> Bar-Close
-> Feature Store -> Signal-Engine -> Persistence -> UI-Overlay).

Signal-Logik:
- Gerader bar_time-Index (bar_time % 2 == 0) -> Buy (confidence=1.0)
- Ungerader bar_time-Index (bar_time % 2 == 1) -> Sell (confidence=1.0)
- Erste Bar immer neutral (confidence=0.0)
"""

from typing import Any, Dict, Optional
import pandas as pd
import numpy as np
from analytics.engine.base_definition import SignalDefinition


class AlternatingArrowSignal(SignalDefinition):
    """Erzeugt alternierende Buy/Sell-Pfeile für Testzwecke."""

    @property
    def signal_id(self) -> str:
        return "alternating_arrow_v1"

    @property
    def display_name(self) -> str:
        return "Alternating Arrow (Test)"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def default_params(self) -> Dict[str, Any]:
        return {
            "confidence_buy": 1.0,
            "confidence_sell": 1.0,
            "skip_first_bars": 1,
        }

    @property
    def param_descriptions(self) -> Dict[str, str]:
        return {
            "confidence_buy": "Confidence-Wert für Buy-Signale",
            "confidence_sell": "Confidence-Wert für Sell-Signale",
            "skip_first_bars": "Anzahl der ersten Bars ohne Signal",
        }

    @property
    def required_features(self) -> list:
        return []

    @property
    def live_op(self) -> bool:
        """Testsignal ist deaktiviert (keine automatischen Test-Signale in der Live-Pipeline)."""
        return False

    def evaluate(self, df_features: pd.DataFrame, params: Optional[Dict[str, Any]] = None) -> pd.Series:
        p = {**self.default_params, **(params or {})}
        conf_buy = float(p["confidence_buy"])
        conf_sell = float(p["confidence_sell"])
        skip = int(p["skip_first_bars"])

        n = len(df_features)
        confidence = np.zeros(n, dtype=float)

        if n <= skip:
            return pd.Series(confidence, index=df_features.index)

        # Alternierend: gerader Index = Buy, ungerader Index = Sell
        for i in range(skip, n):
            bar_time = df_features.iloc[i].get("bar_time", i)
            # Nutze bar_time als Seed für deterministische Alternierung
            if isinstance(bar_time, (int, float)):
                idx_val = int(bar_time)
            else:
                idx_val = i

            if idx_val % 2 == 0:
                confidence[i] = conf_buy
            else:
                confidence[i] = conf_sell

        return pd.Series(confidence, index=df_features.index)
