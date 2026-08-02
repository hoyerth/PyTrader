# chart/widgets/__init__.py
# Wiederverwendbare kompakte UI-Widgets (Phase 13 Kapitel 5.5 + Schritt 9).
#
# HINWEIS: Bewusst MINIMAL gehalten – hier werden KEINE schweren Module
# importiert (kein chart_win, keine Indikatoren). ColorButton ist ein
# eigenständiges PySide6-Widget und kann von indicator_dialog.py,
# service_win.py und Tests ohne Circular-Import-Risiko eingebunden werden.
# NamedItemActionsMixin ist ein reines Qt-Mixin (nur QInputDialog/QMessageBox)
# und ebenfalls import-schwerelos.
from .color_button import ColorButton
from .named_item_actions import NamedItemActionsMixin

__all__ = ["ColorButton", "NamedItemActionsMixin"]
