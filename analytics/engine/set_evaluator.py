# analytics/engine/set_evaluator.py
"""
Set-Evaluator – Kombiniert mehrere Signale zu einem gewichteten Gesamt-Score.
Unterstützt gewichtete Summen mit Schwellenwert (Threshold).
"""

from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
import json

from analytics.engine.base_definition import SignalDefinition


class SetEvaluator:
    """
    Wertet Signal-Sets aus: Kombiniert Einzelsignale mit Gewichtung
    zu einem Gesamt-Confidence-Score pro Bar.
    """

    def __init__(self, signals: Dict[str, SignalDefinition]) -> None:
        """
        Args:
            signals: Dict aller verfügbarer Signale {signal_id: SignalDefinition}
        """
        self.signals = signals

    def evaluate_set(
        self,
        set_config: Dict[str, Any],
        df_features: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Wertet ein komplettes Signal-Set aus.

        Args:
            set_config: JSON-konforme Konfiguration {
                "signals": [{"id": "ema_trend_v1", "weight": 0.6, "params": {...}}, ...],
                "threshold": 0.5
            }
            df_features: DataFrame mit Feature-Spalten

        Returns:
            DataFrame mit Spalten: bar_time, confidence_total, sowie Einzel-Confidences
        """
        signal_configs = set_config.get("signals", [])
        threshold = float(set_config.get("threshold", 0.5))

        if not signal_configs:
            raise ValueError("Set-Konfiguration enthält keine Signale")

        result = df_features[["bar_time"]].copy()
        total_weight = 0.0
        weighted_sum = pd.Series(0.0, index=df_features.index)

        for cfg in signal_configs:
            signal_id = cfg["id"]
            weight = float(cfg.get("weight", 1.0))
            params = cfg.get("params", {})

            if signal_id not in self.signals:
                print(f"⚠️ [SetEvaluator] Unbekanntes Signal: {signal_id}")
                continue

            signal = self.signals[signal_id]

            # Prüfen ob benötigte Features vorhanden sind
            missing = [f for f in signal.required_features if f not in df_features.columns]
            if missing:
                print(f"⚠️ [SetEvaluator] Fehlende Features für {signal_id}: {missing}")
                continue

            confidence = signal.evaluate(df_features, params)
            result[f"conf_{signal_id}"] = confidence.values

            weighted_sum += confidence * weight
            total_weight += weight

        # Gewichteter Gesamt-Score
        if total_weight > 0:
            result["confidence_total"] = (weighted_sum / total_weight).values
        else:
            result["confidence_total"] = 0.0

        # Binäres Signal (Threshold-Überschreitung)
        result["signal_binary"] = (result["confidence_total"] >= threshold).astype(int)

        return result

    def evaluate_set_from_db(
        self,
        set_id: str,
        set_configs: Dict[str, Dict[str, Any]],
        df_features: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Lädt eine Set-Konfiguration anhand der set_id und wertet sie aus.

        Args:
            set_id: ID des Signal-Sets
            set_configs: Dict aller verfügbarer Set-Konfigurationen
            df_features: DataFrame mit Feature-Spalten

        Returns:
            DataFrame mit Ergebnissen
        """
        if set_id not in set_configs:
            raise ValueError(f"Set-ID '{set_id}' nicht gefunden")

        config = set_configs[set_id]
        if isinstance(config.get("configuration"), str):
            config["configuration"] = json.loads(config["configuration"])

        return self.evaluate_set(config["configuration"], df_features)
