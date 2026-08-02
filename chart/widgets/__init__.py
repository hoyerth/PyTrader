# chart/widgets/__init__.py
# Wiederverwendbare kompakte UI-Widgets (Phase 13 Kapitel 5.5).
#
# HINWEIS: Bewusst MINIMAL gehalten – hier werden KEINE schweren Module
# importiert (kein chart_win, keine Indikatoren). ColorButton ist ein
# eigenständiges PySide6-Widget und kann von indicator_dialog.py,
# service_win.py und Tests ohne Circular-Import-Risiko eingebunden werden.
from .color_button import ColorButton

__all__ = ["ColorButton"]
