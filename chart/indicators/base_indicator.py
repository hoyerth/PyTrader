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

	def get_live_overlays(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""P14-03-E: Liefert die Live-Overlays des Plugins als Liste von Overlay-Items
		{kind, layer, time, price, color, priority, ...}. Basis-Default: [].
		Plugin-Klassen überschreiben diesen Hook (Open/Closed), damit die Engine
		(chart_win) die Overlays ALLER aktiven Indikatoren generisch einsammelt –
		kein Indikator-spezifischer Sonderfall pro Plugin."""
		return []

	def remember_live_time(self, ts: int) -> None:
		"""P14-03-E (Flacker-Fix): Merkt eine offene Live-Bar-Zeit (gerundete
		Epoch), damit der New-Candle-Erkennung des Plugins nach einem
		calculate()-Rebuild die Live-Bar nicht als "neue Kerze" erscheint und der
		debounced Refresh nicht erneut feuert. Basis-Default: no-op.
		Plugin-Klassen mit New-Candle-Callback überschreiben diesen Hook
		(Open/Closed), damit die Engine (chart_win) die Re-Injektion generisch
		über ALLE Indikatoren ausführen kann – kein Indikator-Sonderfall."""
		pass