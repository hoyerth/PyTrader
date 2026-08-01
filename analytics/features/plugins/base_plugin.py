# analytics/features/plugins/base_plugin.py
"""
Basisklasse & typisierte Verträge für das Plugin-System (Phase 12 + 13).

Kernprinzip: STRICTE ZUSTANDSLOSIGKEIT. Plugins speichern niemals eigene
Zustände oder Parameter. Jede Berechnung ist eine reine Funktion
calculate(df, params, context). Das ermöglicht fehlerfreie Parallelisierung,
Thread-Sicherheit und eine klare Trennung zwischen Feature-Engine
(FeatureStorePayload) und visuellem Indikator (ChartRenderPayload).

Feature-Store-Lese-Regel (präzisiert für Phase 13): Die INDIKATOR-Berechnung
(GUI) liest NIE direkt aus dem Feature-Store; der Scanner schreibt NIE aus dem
Render-Payload. Overlay-Konsumenten (SignalOverlay, Statistik) lesen den
Feature-Store erst in Phase 13 Schritt 7.
"""

from abc import ABC, abstractmethod
from copy import copy as _shallow_copy
from dataclasses import dataclass, field
from typing import Dict, Any, List, TypedDict, Literal, Optional
import pandas as pd

from config.app_settings import AppSettings


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
    expert: bool  # True → Prop im ausklappbaren Expert-Bereich (Default: False)


# ==============================================================================
# PluginContext & PluginCapabilities (Phase 13)
# ==============================================================================
class PluginCapabilities(TypedDict):
    """Ersetzt das deprecated live_op (Cleanup in Phase 13 Schritt 7)."""
    chart: bool          # als Chart-Indikator verfügbar
    batch: bool          # in der Batch-Pipeline ausführbar
    live: bool           # unterstützt Live-Ticks
    feature_store: bool  # schreibt feature_data in feature_store
    render: bool         # liefert chart_render_payload


@dataclass
class PluginContext:
    """Immutabler Plugin-Kontext für die Service-/Plugin-Ausführung.

    Grundprinzip: Services greifen NIE direkt auf Datenbanken oder globale
    Settings zu – alles läuft über diesen Kontext.
    """
    symbol: str = ""
    timeframe: str = ""
    mode: Literal["chart", "batch", "live"] = "chart"
    timestamp: Optional[int] = None  # epoch-Sekunden des Live-Ticks / der letzten Bar
    shared_state: Dict[str, Any] = field(default_factory=dict)
    settings: Optional[AppSettings] = None  # Kopie (kein globaler Zugriff)

    def __post_init__(self) -> None:
        # Settings werden als Kopie übergeben – mutieren der Ursprungs-Instanz
        # darf den Context nicht beeinflussen (kein globaler Zugriff).
        if self.settings is not None:
            self.settings = _shallow_copy(self.settings)


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
        """DEPRECATED: wird durch capabilities['live'] ersetzt
        (Cleanup in Phase 13 Schritt 7)."""
        return True

    @property
    def capabilities(self) -> PluginCapabilities:
        """PluginCapabilities (Phase 13) – ersetzt live_op."""
        return {
            "chart": True,
            "batch": True,
            "live": self.live_op,
            "feature_store": True,
            "render": True,
        }

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
    def parameter_order(self) -> List[str]:
        """Darstellungs-Reihenfolge der Props im Prop-Fenster.

        Single Source of Truth: Kann an den ANFANG jeder Plugin-/Service-
        Definition überschrieben werden. Default = Reihenfolge aus dem Schema.
        """
        return list(self.parameter_schema.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        """Label-Namen der Props im Prop-Fenster.

        Single Source of Truth: Kann an den ANFANG jeder Plugin-/Service-
        Definition überschrieben werden. Default = description bzw.
        humanisierter Parameter-Key.
        """
        labels: Dict[str, str] = {}
        for key, spec in self.parameter_schema.items():
            desc = spec.get("description", "")
            labels[key] = desc if desc else key.replace("_", " ").title()
        return labels

    def is_expert_param(self, key: str) -> bool:
        """True, wenn der Parameter mit expert=True markiert ist (Default: False)."""
        return bool(self.parameter_schema.get(key, {}).get("expert", False))

    @property
    def default_params(self) -> Dict[str, Any]:
        return {k: v["default"] for k, v in self.parameter_schema.items() if "default" in v}

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validiert Eingabeparameter gegen das Schema und setzt Defaults ein.

        min/max werden hart geclippt; step dient als Widget-Schrittweite im
        Prop-Fenster (keine Rundung auf step im Validator).
        """
        validated = {}
        schema = self.parameter_schema
        for key, spec in schema.items():
            val = params.get(key, spec.get("default"))
            p_type = spec.get("type")

            if val is None:
                # Kein Default angegeben → typspezifischen Null-Wert verwenden
                val = 0.0 if p_type == "float" else 0 if p_type == "int" else False if p_type == "bool" else ""
            elif p_type == "float":
                val = float(val)
            elif p_type == "int":
                val = int(val)
            elif p_type == "bool":
                val = bool(val)

            try:
                if "min" in spec and val < spec["min"]:
                    val = spec["min"]
                if "max" in spec and val > spec["max"]:
                    val = spec["max"]
            except TypeError:
                # Nicht-vergleichbare Werte (z.B. bool/color) unverändert lassen
                pass

            validated[key] = val
        return validated

    @abstractmethod
    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Stateless Berechnungslogik: Leseinput = df + validated_params.

        Rückwärtskompatibilität Phase 12: calculate(df, params) ohne context
        bleibt gültig (context ist Optional).
        """
        pass
