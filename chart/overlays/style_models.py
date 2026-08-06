# chart/overlays/style_models.py
# Phase 16 P16.03 (06.08.2026): Generische Style-Vertraege (Dataclasses).
#
# Visuelle Attribute (Farbe, Dicke, Stil, Form) werden nicht mehr als flache
# Einzelparameter (line_color, line_width, ...) durch das System gereicht,
# sondern in typisierten Styling-Klassen gebuendelt:
#
#   * LineStyle   - Linien: show / color / width / style
#   * MarkerStyle - Punkte (Hit-Circles u. a.): show / color / shape / size
#
# Konvertierungen:
#   * to_js_dict()  - direkt fuer die JS-Bridge (TradingView Lightweight
#                     Charts v5): style-Werte lowercase (solid/dashed/dotted/
#                     dashdotted), shape-Werte LWC-kompatibel
#                     (circle/square/arrowUp/arrowDown).
#   * to_dict()     - JSON-kompatibles Dict (Preset-Persistenz im
#                     StateManager / indicator_presets).
#   * from_dict()   - Rueck-Konvertierung (tolerant gegen fehlende Felder:
#                     Defaults werden ergaenzt).
#
# Farb-Logik (Paritaet zum ColorButton / StylePickerWidget):
#   - Alpha == 255 -> '#RRGGBB' (Hex, Grossbuchstaben, volle Deckkraft).
#   - Alpha < 255  -> 'rgba(r, g, b, a)' mit a als Float (0..1) -
#                     1:1 kompatibel mit TradingView Lightweight Charts v5
#                     (WebEngine) und HTML/CSS.

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Konvertierungs-Helfer
# ---------------------------------------------------------------------------

def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if value is None:
        return default
    return bool(value)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: str) -> str:
    if value is None:
        return default
    return str(value)


# ---------------------------------------------------------------------------
# LineStyle
# ---------------------------------------------------------------------------

#: Gueltige Linienarten (lowercase, JS-Bridge-Konvention).
LINE_STYLES: List[str] = ["solid", "dashed", "dotted", "dashdotted"]


@dataclass
class LineStyle:
    """Stil-Definition fuer Linien: Sichtbarkeit, Farbe, Staerke, Linienart.

    Attributes:
        show:  bool  – Linie sichtbar (QCheckBox).
        color: str   – '#RRGGBB' (Alpha=255) oder 'rgba(r,g,b,a)' (Teil-Transparenz).
        width: int   – Linienstaerke in px (1–10, QSpinBox).
        style: str   – 'solid' | 'dashed' | 'dotted' | 'dashdotted' (QComboBox).
    """

    show: bool = True
    color: str = "#2196F3"
    width: int = 1
    style: str = "solid"

    # -- JS-Bridge -----------------------------------------------------------
    def to_js_dict(self) -> Dict[str, Any]:
        """JS-Bridge-Darstellung (LWC v5): lowercase style-Werte."""
        return {
            "show": bool(self.show),
            "color": str(self.color),
            "width": int(self.width),
            "style": str(self.style) if str(self.style) in LINE_STYLES else "solid",
        }

    # -- JSON-Persistenz -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """JSON-kompatibles Dict (Presets im StateManager)."""
        return self.to_js_dict()

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LineStyle":
        """Erzeugt eine LineStyle aus einem (JSON-)Dict – tolerant: fehlende
        Felder erhalten ihre Defaults, ungueltige style-Werte fallen auf
        'solid' zurueck. None -> Default-Instanz.
        """
        if not isinstance(data, dict):
            return cls()
        style = _as_str(data.get("style"), "solid")
        if style not in LINE_STYLES:
            style = "solid"
        return cls(
            show=_as_bool(data.get("show"), True),
            color=_as_str(data.get("color"), "#2196F3"),
            width=_as_int(data.get("width"), 1),
            style=style,
        )


# ---------------------------------------------------------------------------
# MarkerStyle
# ---------------------------------------------------------------------------

#: Gueltige Marker-Formen (LWC v5-kompatibel fuer die JS-Bridge).
MARKER_SHAPES: List[str] = ["circle", "square", "arrowUp", "arrowDown"]


@dataclass
class MarkerStyle:
    """Stil-Definition fuer Marker/Punkte: Sichtbarkeit, Farbe, Form, Groesse.

    Attributes:
        show:  bool  – Marker sichtbar (QCheckBox).
        color: str   – '#RRGGBB' (Alpha=255) oder 'rgba(r,g,b,a)' (Teil-Transparenz).
        shape: str   – 'circle' | 'square' | 'arrowUp' | 'arrowDown' (QComboBox).
        size:  int   – Markergroesse in px (QSpinBox).
    """

    show: bool = True
    color: str = "#FFEB3B"
    shape: str = "circle"
    size: int = 6

    # -- JS-Bridge -----------------------------------------------------------
    def to_js_dict(self) -> Dict[str, Any]:
        """JS-Bridge-Darstellung (LWC v5): shape-Werte LWC-kompatibel."""
        return {
            "show": bool(self.show),
            "color": str(self.color),
            "shape": str(self.shape) if str(self.shape) in MARKER_SHAPES else "circle",
            "size": int(self.size),
        }

    # -- JSON-Persistenz -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        """JSON-kompatibles Dict (Presets im StateManager)."""
        return self.to_js_dict()

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "MarkerStyle":
        """Erzeugt eine MarkerStyle aus einem (JSON-)Dict – tolerant: fehlende
        Felder erhalten ihre Defaults, ungueltige shape-Werte fallen auf
        'circle' zurueck. None -> Default-Instanz.
        """
        if not isinstance(data, dict):
            return cls()
        shape = _as_str(data.get("shape"), "circle")
        if shape not in MARKER_SHAPES:
            shape = "circle"
        return cls(
            show=_as_bool(data.get("show"), True),
            color=_as_str(data.get("color"), "#FFEB3B"),
            shape=shape,
            size=_as_int(data.get("size"), 6),
        )
