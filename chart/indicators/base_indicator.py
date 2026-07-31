"""
chart/indicators/base_indicator.py - Base Class for all PyTrader Indicators
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import pandas as pd


class BaseIndicator(ABC):

	def __init__(self) -> None:
		pass

	@property
	@abstractmethod
	def indicator_id(self) -> str:
		"""Eindeutige ID des Indikators (z. B. 'grid')."""
		pass

	@property
	@abstractmethod
	def display_name(self) -> str:
		"""Anzeigename für UI & Button-Tooltips."""
		pass

	@property
	@abstractmethod
	def default_params(self) -> Dict[str, Any]:
		"""Standard-Parameter mit Werten."""
		pass

	@property
	def param_options(self) -> Dict[str, List[Any]]:
		"""Optional: Dropdown-Optionen für bestimmte Schlüssel."""
		return {}

	@property
	def param_labels(self) -> Dict[str, str]:
		"""Optional: Benutzerdefinierte Label für Parameter (key → Anzeigename)."""
		return {}

	@property
	def param_layout(self) -> Optional[List[Any]]:
		"""Optional: Layout-Struktur für mehrspaltige Parameter-Zeilen."""
		return None

	@abstractmethod
	def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> Dict[str, Any]:
		"""Führt die mathematische Berechnung auf dem DataFrame aus und liefert Zeichnungsdaten zurück."""
		pass