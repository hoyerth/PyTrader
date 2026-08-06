# chart/overlays/__init__.py
# Phase 16 P16.03 (06.08.2026): Generische Zeichnungsobjekte & Style-Vertraege.
#
# LineStyle / MarkerStyle kapseln Styling-Attribute (Farbe, Dicke, Stil, Form,
# Sichtbarkeit) und konvertieren sich via .to_js_dict() direkt fuer das
# Canvas-Frontend sowie via .to_dict()/.from_dict() fuer die JSON-Persistenz
# (indicator_presets im StateManager).
from .style_models import (
    LINE_STYLES,
    MARKER_SHAPES,
    LineStyle,
    MarkerStyle,
)

__all__ = [
    "LINE_STYLES",
    "MARKER_SHAPES",
    "LineStyle",
    "MarkerStyle",
]
