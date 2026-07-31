# analytics/features/base_feature.py
"""
Basisklasse für alle Feature-Definitionen im Feature Store.
Jedes Feature erbt von BaseFeature und implementiert calculate().
Unterstützt Single-Spalten (pd.Series) und Multi-Spalten (pd.DataFrame) Rückgaben.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Union
import pandas as pd


class BaseFeature(ABC):
    """Abstrakte Basisklasse für Feature-Berechnungen."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Eindeutiger Spaltenname im feature_store (z. B. 'ema_diff')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Menschleserliche Beschreibung."""
        pass

    @property
    def column_names(self) -> List[str]:
        """
        Gibt die Liste der Spaltennamen zurück, die dieses Feature erzeugt.
        Default: [self.name] für Single-Spalten-Features.
        Überschreiben für Multi-Spalten-Features.
        """
        return [self.name]

    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Union[pd.Series, pd.DataFrame]:
        """
        Berechnet das Feature auf einem OHLCV-DataFrame.
        
        Kann entweder eine pd.Series (Single-Spalte) oder ein pd.DataFrame 
        (Multi-Spalten) zurückgeben.
        
        Args:
            df: OHLCV-DataFrame mit bar_time, open, high, low, close, tick_volume
            params: Feature-spezifische Parameter
        
        Returns:
            pd.Series oder pd.DataFrame mit demselben Index wie df
        """
        return self._calculate(df, params)

    @abstractmethod
    def _calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Union[pd.Series, pd.DataFrame]:
        """Interne Berechnungslogik. Subklassen implementieren diese Methode."""
        pass
