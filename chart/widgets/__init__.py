# chart/widgets/__init__.py
# Wiederverwendbare kompakte UI-Widgets (Phase 13 Kapitel 5.5 + Schritt 9).
#
# HINWEIS: Bewusst MINIMAL gehalten – hier werden KEINE schweren Module
# importiert (kein chart_win, keine Indikatoren). StylePickerWidget ist ein
# eigenständiges PySide6-Widget und kann von indicator_dialog.py,
# serviceui/service_win.py und Tests ohne Circular-Import-Risiko eingebunden werden.
# NamedItemActionsMixin ist ein reines Qt-Mixin (nur QInputDialog/QMessageBox)
# und ebenfalls import-schwerelos.
#
# Phase 16 (06.08.2026): ColorButton wurde durch das generische
# StylePickerWidget ersetzt (Farbe + Stärke + Stil + Sichtbarkeit).
#
# Phase 16 P16.03 (06.08.2026): Die Style-Vertraege LineStyle/MarkerStyle
# leben seitdem zentral in `chart/overlays/style_models.py` und werden hier
# re-exportiert (rueckwaertskompatibler Importweg). StylePickerWidget selbst
# importiert sie bereits direkt aus den overlays.
from chart.overlays.style_models import LineStyle, MarkerStyle
from .style_picker_widget import StylePickerWidget
from .named_item_actions import NamedItemActionsMixin, NamedItemAdapter

__all__ = ["LineStyle", "MarkerStyle", "StylePickerWidget", "NamedItemActionsMixin", "NamedItemAdapter"]
