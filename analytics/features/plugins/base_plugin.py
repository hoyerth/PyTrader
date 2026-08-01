# analytics/features/plugins/base_plugin.py
"""
Basisklasse & typisierte Verträge für das Plugin-System (Phase 12).

Kernprinzip: STRICTE ZUSTANDSLOSIGKEIT. Plugins speichern niemals eigene
Zustände oder Parameter. Jede Berechnung ist eine reine Funktion
calculate(df, params). Das ermöglicht fehlerfreie Parallelisierung,
Thread-Sicherheit und eine klare Trennung zwischen Feature-Engine
(FeatureStorePayload) und visuellem Indikator (ChartRenderPayload).

Der Chart liest NIE direkt aus dem Feature-Store; der Scanner schreibt
NIE aus dem Render-Payload.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, TypedDict, Literal, Optional
import pandas as pd


# ==============================================================================
# Parametervalidierung & Schema
# ==============================================================================
class ParameterSchema(TypedDict, total=False):
    type: Literal["float", "int", "bool", "str", "color", "choice"]
    default: Any
    min: Optional[float]
    max: Optional[float]
    step: Optional[float]
    options: Optional[List[str]]
    description: str


# ==============================================================================
# Zukunftssicherer ChartRenderPayload (LightweightCharts v5 / JS-Bridge)
# ==============================================================================
class ChartLine(TypedDict):
    price: float
    color: str
    width: int
    style: Literal["solid", "dashed", "dotted"]


class ChartCircle(TypedDict):
    time: int
    price: float
    color: str
    priority: int


class ChartMarker(TypedDict):
    time: int
    position: Literal["aboveBar", "belowBar", "inBar"]
    color: str
    shape: Literal["circle", "square", "arrowUp", "arrowDown"]
    size: int
    text: str
    priority: int


class ChartArea(TypedDict):
    time_from: int
    time_to: int
    price_top: float
    price_bottom: float
    color: str


class ChartLabel(TypedDict):
    time: int
    price: float
    text: str
    color: str


class ChartRenderPayload(TypedDict, total=False):
    lines: List[ChartLine]
    hit_circles: List[ChartCircle]  # JS-Bridge kompatibel
    markers: List[ChartMarker]
    areas: List[ChartArea]          # Erweiterung für Zonen/Kanäle
    labels: List[ChartLabel]        # Erweiterung für Text-Labels
    custom: Dict[str, Any]


# ==============================================================================
# Strikter FeatureStorePayload (DuckDB)
# ==============================================================================
class FeatureStorePayload(TypedDict, total=False):
    feature_id: str
    plugin_version: str
    records: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    statistics: Dict[str, Any]


class FeatureCalculateResult(TypedDict):
    feature_store_payload: FeatureStorePayload
    chart_render_payload: ChartRenderPayload


# ==============================================================================
# Plugin-Metadaten & Schnittstelle
# ==============================================================================
class PluginMetadata(TypedDict):
    category: str
    display_name: str
    description: str
    author: str
    tags: List[str]


class PluginFeature(ABC):
    """Stateless Plugin-Basisklasse mit Schemavalidierung und Metadaten."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Dauerhaft stabile ID (z.B. 'grid_liquidity')."""
        pass

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> PluginMetadata:
        return {
            "category": "General",
            "display_name": self.plugin_id.replace("_", " ").title(),
            "description": "",
            "author": "System",
            "tags": []
        }

    @property
    def live_op(self) -> bool:
        return True

    @property
    def dependencies(self) -> List[str]:
        """IDs anderer Plugins, die vorab berechnet werden müssen."""
        return []

    @property
    @abstractmethod
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Schema zur automatischen Validierung & UI-Generierung."""
        pass

    @property
    def default_params(self) -> Dict[str, Any]:
        return {k: v["default"] for k, v in self.parameter_schema.items() if "default" in v}

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validiert Eingabeparameter gegen das Schema und setzt Defaults ein."""
        validated = {}
        schema = self.parameter_schema
        for key, spec in schema.items():
            val = params.get(key, spec.get("default"))
            p_type = spec.get("type")
            if p_type == "float":
                val = float(val)
            elif p_type == "int":
                val = int(val)
            elif p_type == "bool":
                val = bool(val)

            if "min" in spec and val < spec["min"]:
                val = spec["min"]
            if "max" in spec and val > spec["max"]:
                val = spec["max"]
            validated[key] = val
        return validated

    @abstractmethod
    def calculate(self, df: pd.DataFrame, params: Dict[str, Any]) -> FeatureCalculateResult:
        """Stateless Berechnungslogik: Leseinput = df + validated_params."""
        pass
