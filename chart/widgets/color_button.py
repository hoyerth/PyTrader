# chart/widgets/color_button.py
# Phase 13 Kapitel 5.5 Schritt 1: Kompakter Farbwähler mit Alpha-Kanal.
#
# Roadmap 5.5.1.2:
#   - Baut zu 100 % auf PySide6 (QColorDialog + QPushButton) auf – keine
#     externen UI-Bibliotheken.
#   - Platzeffizient: kleines Farbquadrat (festgelegte Kompaktgröße 60x24 px),
#     das die gewählte Farbe inklusive Deckkraft als Hintergrund anzeigt.
#   - Transparenz: über QColorDialog.ShowAlphaChannel wird ein Schieberegler
#     für die Deckkraft (0-255) freigeschaltet.
#   - CSS/Chart-Kompatibilität: bei 100 % Deckkraft (Alpha=255) liefert color()
#     ein Hex-Format '#RRGGBB'; bei Teil-Transparenz einen rgba(r,g,b,a)-String
#     (a als Float 0..1). Beides ist 1:1 kompatibel mit TradingView Lightweight
#     Charts v5 (WebEngine) und HTML/CSS.
#
# Roadmap 5.5.2.1 Prämisse 3 (Kompaktes Layout): Die feste Kompaktgröße ist
# bewusst klein; Size-Policy = Fixed verhindert, dass das Widget in Layouts
# gedehnt wird und die dynamische Höhe/Breite des Prop-Fensters blockiert.

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QPushButton, QSizePolicy


class ColorButton(QPushButton):
    """Kompakter Farbwähler (farbiges Quadrat) mit optionalem Alpha-Kanal.

    Attributes:
        _color: QColor        – aktuelle Farbe inkl. Alpha (0-255).
        _enable_alpha: bool   – ob der QColorDialog den Alpha-Slider zeigt.

    Signal:
        colorChanged = Signal(str) – emittiert den Farb-String (hex oder
        rgba(...)) bei jeder Änderung über den Farbdialog.
    """

    colorChanged = Signal(str)

    def __init__(self, default_color: str = "#2196F3", enable_alpha: bool = True,
                 parent=None) -> None:
        super().__init__(parent)
        self._enable_alpha: bool = bool(enable_alpha)
        self._color: QColor = QColor()
        self.setColor(default_color)

        # Kompakte Festgröße (Roadmap 5.5.1.2: "festgelegte Kompaktgröße z. B.
        # 60x24 px"). Fixed-Size-Policy: das Widget wird in Layouts weder
        # gedehnt noch gestaucht -> blockiert die Layout-Dynamik nicht.
        self.setFixedSize(60, 24)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Farbe auswählen (inkl. Transparenz)")
        self.clicked.connect(self._open_color_dialog)

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def color(self) -> str:
        """Gibt die aktuelle Farbe als String zurück.

        Alpha == 255 -> '#RRGGBB' (Hex, Großbuchstaben, volle Deckkraft).
        Alpha < 255  -> 'rgba(r, g, b, a)' mit a als Float (0..1) –
                        direkt kompatibel mit TradingView v5 / CSS.
        """
        c = self._color
        if not c.isValid():
            return "#000000"
        if c.alpha() < 255:
            a = round(c.alpha() / 255.0, 2)
            return f"rgba({c.red()}, {c.green()}, {c.blue()}, {a})"
        return c.name().upper()

    def setColor(self, color_str: str) -> None:
        """Setzt die Farbe aus einem Hex- oder rgba(...)-String.

        Ungültige Eingaben werden ignoriert (bisherige Farbe bleibt erhalten).
        Aktualisiert anschließend das Button-Styling.
        """
        parsed = self._parse_color(color_str)
        if parsed is not None:
            self._color = parsed
            self.update_style()

    def update_style(self) -> None:
        """Setzt das Button-Stylesheet auf die aktuelle Farbe inkl. Deckkraft.

        Hintergrund wird immer als rgba(...) gesetzt, damit die Transparenz
        direkt im Button sichtbar ist (Deckkraft-Visualisierung).
        """
        c = self._color
        if not c.isValid():
            bg = "rgba(0, 0, 0, 1.0)"
        else:
            bg = f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha() / 255.0})"
        self.setStyleSheet(
            "QPushButton { background-color: " + bg +
            "; border: 1px solid #555555; border-radius: 3px; }"
        )

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _open_color_dialog(self) -> None:
        """Öffnet QColorDialog.getColor() (mit Alpha-Slider, wenn aktiviert).

        Bei gültiger Auswahl wird colorChanged mit dem neuen Farb-String
        emittiert (hex oder rgba(...), je nach Alpha).
        """
        options = QColorDialog.ColorDialogOption(0)
        if self._enable_alpha:
            options |= QColorDialog.ColorDialogOption.ShowAlphaChannel
        chosen = QColorDialog.getColor(self._color, self, "Farbe auswählen", options)
        if chosen.isValid():
            self._color = chosen
            self.update_style()
            self.colorChanged.emit(self.color())

    @staticmethod
    def _parse_color(color_str: str) -> Optional[QColor]:
        """Parst Hex- oder rgba(...)-Strings in ein QColor (oder None)."""
        s = (color_str or "").strip()
        if not s:
            return None
        low = s.lower()
        if low.startswith("rgba("):
            try:
                inner = s[s.index("(") + 1:s.rindex(")")]
                parts = [p.strip() for p in inner.split(",")]
                if len(parts) != 4:
                    return None
                r = int(round(float(parts[0])))
                g = int(round(float(parts[1])))
                b = int(round(float(parts[2])))
                a_frac = float(parts[3])
            except (ValueError, TypeError):
                return None
            r = max(0, min(255, r))
            g = max(0, min(255, g))
            b = max(0, min(255, b))
            alpha = max(0, min(255, int(round(a_frac * 255))))
            return QColor(r, g, b, alpha)
        c = QColor(s)
        return c if c.isValid() else None
