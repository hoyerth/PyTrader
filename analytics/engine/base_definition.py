# analytics/engine/base_definition.py
"""
Abstrakte Basisklasse für alle Signal-Definitionen.
Jedes Signal (Regel, Pattern, ML) erbt von SignalDefinition und
implementiert evaluate(), das einen Confidence-Score [0.0, 1.0] pro Bar liefert.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import pandas as pd


class SignalDefinition(ABC):
    """Abstrakte Basisklasse für Signal-Definitionen."""

    @property
    @abstractmethod
    def signal_id(self) -> str:
        """Eindeutige ID (z. B. 'ema_trend_v1')."""
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Anzeigename für UI/Logs."""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Versionsstring (z. B. '1.0.0')."""
        pass

    @property
    @abstractmethod
    def default_params(self) -> Dict[str, Any]:
        """Standard-Parameter für dieses Signal."""
        pass

    @property
    def param_descriptions(self) -> Dict[str, str]:
        """Optionale Beschreibungen der Parameter."""
        return {}

    @property
    def live_op(self) -> bool:
        """
        Live-Betriebsmodus.
        True (Default) → Dynamisch: wird bei Chart-Aufruf aktualisiert, Live-Tracking.
        False → Statisch: dient als unveränderliche Benchmark-Historie für Statistiken.
        """
        return True

    @property
    def required_features(self) -> List[str]:
        """
        Liste der Feature-Namen, die für evaluate() benötigt werden.
        Wird vom FeatureBuilder verwendet, um fehlende Features zu erkennen.
        """
        return []

    @abstractmethod
    def evaluate(self, df_features: pd.DataFrame, params: Optional[Dict[str, Any]] = None) -> pd.Series:
        """
        Berechnet den Confidence-Score [0.0, 1.0] für jede Bar.

        Args:
            df_features: DataFrame mit Feature-Spalten (bar_time + feature-Spalten).
            params: Überschreibt default_params für diesen Aufruf.

        Returns:
            pd.Series mit Confidence-Werten [0.0, 1.0], gleicher Index wie df_features.
        """
        pass
