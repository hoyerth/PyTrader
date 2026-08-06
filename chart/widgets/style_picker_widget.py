# chart/widgets/style_picker_widget.py
# Phase 16 (06.08.2026): Generischer Stil-Waehler - ersetzt ColorButton
# (chart/widgets/color_button.py).
#
# Der bisherige ColorButton war ein reiner Farbwaehler (Phase 13 Kapitel 5.5).
# Das StylePickerWidget buendelt zentral:
#   1. QCheckBox      -> Sichtbarkeit (show)
#   2. Farb-Button    -> Farbe (color) via QColorDialog (optional mit Alpha)
#   3. QSpinBox       -> Linienstaerke (width, 1-10) bzw. Markergroesse (size)
#   4. QComboBox      -> Linienart (style: solid/dashed/dotted/dashdotted)
#                        bzw. Marker-Form (shape: circle/square/arrowUp/arrowDown)
#
# Phase 16 P16.03 (06.08.2026): Die Style-Vertraege LineStyle/MarkerStyle
# leben jetzt zentral in `chart/overlays/style_models.py` (to_js_dict /
# to_dict / from_dict). Das Widget unterstuetzt beide Typen ueber den
# Konstruktor-Parameter `style_type`:
#   * style_type="line"   -> get_style()/set_style() arbeiten mit LineStyle
#   * style_type="marker" -> get_style()/set_style() arbeiten mit MarkerStyle
#
# API: get_style() -> LineStyle|MarkerStyle, set_style(...),
#      set_color(str) fuer reine Farb-Updates (Dialog-Restore-Pfad).
# Signal: style_changed = Signal(object) - emittiert das aktuelle Style-Objekt.
#
# Farb-Logik (Paritaet zum Alt-ColorButton):
#   - Alpha == 255 -> '#RRGGBB' (Hex, Grossbuchstaben, volle Deckkraft).
#   - Alpha < 255  -> 'rgba(r, g, b, a)' mit a als Float (0..1) -
#                     1:1 kompatibel mit TradingView Lightweight Charts v5
#                     (WebEngine) und HTML/CSS.
#   - QColorDialog.ShowAlphaChannel schaltet den Deckkraft-Slider frei.
#
# HINWEIS (06.08.2026): Der Indikator-Pfad (fixed_grid_proximity.py) liefert
# style-Werte in Schreibweise "Solid" (capitalized). Die Style-Vertraege
# verwenden gemaeSS P16.03 lowercase-Werte (solid/dashed/dotted/dashdotted).
# Eine Vereinheitlichung erfolgt bei der Indikator-Anbindung (Schritt 3).

from typing import Optional, Union

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QWidget,
)

from chart.overlays.style_models import (
    LINE_STYLES,
    MARKER_SHAPES,
    LineStyle,
    MarkerStyle,
)


class StylePickerWidget(QWidget):
    """Kombinierter Stil-Waehler: Sichtbarkeit + Farbe + Staerke/Groesse + Art.

    Kapselt intern:
      1. QCheckBox  (Sichtbarkeit `show`)
      2. kleiner Farb-Button (Farbe `color` via QColorDialog, optional Alpha)
      3. QSpinBox   (Linienstaerke `width` bzw. Markergroesse `size`)
      4. QComboBox  (Linienart `style` bzw. Marker-Form `shape`)

    Signal:
        style_changed = Signal(object) – emittiert das aktualisierte
        `LineStyle`- bzw. `MarkerStyle`-Objekt bei jeder Aenderung.
    """

    style_changed = Signal(object)

    # Kompakte Festgroesse des Farb-Buttons (Paritaet zum Alt-ColorButton,
    # Roadmap 5.5.1.2: "festgelegte Kompaktgroesse z. B. 60x24 px" – hier
    # bewusst kleiner, da das Composite drei weitere Elemente enthaelt).
    _SWATCH_W = 40
    _SWATCH_H = 24

    def __init__(
        self,
        style: Optional[Union[LineStyle, MarkerStyle]] = None,
        enable_alpha: bool = True,
        parent=None,
        style_type: str = "line",
        color_only: bool = False,
    ) -> None:
        super().__init__(parent)
        self._enable_alpha: bool = bool(enable_alpha)
        # color_only (Bugfix 06.08.2026): Reiner Farbwaehler - das Composite
        # (Sichtbarkeits-Checkbox, Linienstaerke/Groesse, Linienart/Markerform)
        # wird NICHT angezeigt. Verwendet fuer reine Farb-Parameter (z.B.
        # Multi-MA maX_color), deren Sichtbarkeit ein separater 'show_*'-
        # Parameter steuert. get_style() liefert weiterhin ein Style-Objekt
        # (Defaults fuer show/width/style) - der Dialog liest nur .color.
        self._color_only: bool = bool(color_only)
        # style_type: "line" (LineStyle) | "marker" (MarkerStyle)
        self._style_type: str = "marker" if style_type == "marker" else "line"
        if self._style_type == "marker":
            self._style: MarkerStyle = (
                style if isinstance(style, MarkerStyle) else MarkerStyle()
            )
        else:
            self._style: LineStyle = (
                style if isinstance(style, LineStyle) else LineStyle()
            )
        self._color: QColor = QColor()

        # --- Farb-Button ----------------------------------------------------
        # Eindeutiger ObjectName: Das Stylesheet in _update_swatch() wird ueber
        # 'QPushButton#StylePickerSwatch' auf DIESEN Button gescoped. Ohne
        # Scoping wuerde der breite Selektor 'QPushButton' auf alle
        # Nachkommen-Buttons abfaerben – insbesondere auf die kleinen Buttons
        # im QColorDialog (wird mit self als Parent geoeffnet).
        self._color_btn = QPushButton()
        self._color_btn.setObjectName("StylePickerSwatch")
        self._color_btn.setFixedSize(self._SWATCH_W, self._SWATCH_H)
        self._color_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._color_btn.setToolTip("Farbe auswählen (inkl. Transparenz)")

        # --- Sichtbarkeit ---------------------------------------------------
        self._show_check = QCheckBox("sichtbar")
        self._show_check.setToolTip("Linie anzeigen" if self._style_type == "line"
                                    else "Marker anzeigen")

        # --- Staerke / Groesse ---------------------------------------------
        self._width_spin = QSpinBox()
        if self._style_type == "marker":
            self._width_spin.setRange(1, 20)
            self._width_spin.setToolTip("Markergröße (px)")
            self._width_spin.setSuffix(" px")
        else:
            self._width_spin.setRange(1, 10)
            self._width_spin.setToolTip("Linienstärke (px)")
            self._width_spin.setSuffix(" px")

        # --- Linienart / Marker-Form ---------------------------------------
        self._style_combo = QComboBox()
        if self._style_type == "marker":
            self._style_combo.addItems(list(MARKER_SHAPES))
            self._style_combo.setToolTip("Marker-Form")
        else:
            self._style_combo.addItems(list(LINE_STYLES))
            self._style_combo.setToolTip("Linienart")

        # --- Initialwerte (Signale blockiert, damit keine fruehen Emissionen
        #     waehrend der Konstruktion ausgeloest werden) --------------------
        for w in (self._show_check, self._width_spin, self._style_combo):
            w.blockSignals(True)
        try:
            self._apply_style_to_ui(self._style)
            self._set_color_internal(self._style.color)
        finally:
            for w in (self._show_check, self._width_spin, self._style_combo):
                w.blockSignals(False)

        # --- Signalverbindungen ---------------------------------------------
        self._color_btn.clicked.connect(self._open_color_dialog)
        self._show_check.toggled.connect(self._on_part_changed)
        self._width_spin.valueChanged.connect(self._on_part_changed)
        self._style_combo.currentTextChanged.connect(self._on_part_changed)

        # --- Layout ---------------------------------------------------------
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        # color_only: NUR den Farb-Button anzeigen (kein Composite).
        if not self._color_only:
            layout.addWidget(self._show_check)
            layout.addWidget(self._color_btn)
            layout.addWidget(self._width_spin)
            layout.addWidget(self._style_combo)
        else:
            layout.addWidget(self._color_btn)
        layout.addStretch(1)

        self._update_swatch()

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------

    @property
    def style_type(self) -> str:
        """Aktueller Widget-Modus: 'line' (LineStyle) oder 'marker' (MarkerStyle)."""
        return self._style_type

    @property
    def color_only(self) -> bool:
        """True = reiner Farbwaehler (ohne Sichtbarkeits-/Stil-Composite).

        Der Dialog nutzt dieses Flag, um die Geschwister-Keys (style/width
        bzw. shape/size) beim Persistieren zu UEBERSPRINGEN - ein reiner
        Farb-Parameter besitzt keine solchen Geschwister.
        """
        return self._color_only

    def get_style(self) -> Union[LineStyle, MarkerStyle]:
        """Liefert den aktuellen Stil als NEUES Style-Objekt (LineStyle bei
        style_type='line', MarkerStyle bei style_type='marker').

        Es wird eine frische Instanz zurueckgegeben, damit externe Aenderungen
        den internen Zustand nicht unbeabsichtigt mutieren.
        """
        if self._style_type == "marker":
            return MarkerStyle(
                show=self._show_check.isChecked(),
                color=self._color_button_value(),
                shape=str(self._style_combo.currentText()),
                size=int(self._width_spin.value()),
            )
        return LineStyle(
            show=self._show_check.isChecked(),
            color=self._color_button_value(),
            width=int(self._width_spin.value()),
            style=str(self._style_combo.currentText()),
        )

    def set_style(self, style: Union[LineStyle, MarkerStyle]) -> None:
        """Setzt den Stil aus einem Style-Objekt und aktualisiert die UI.

        Akzeptiert LineStyle und MarkerStyle. Passt der Typ nicht zum Modus,
        werden show/color uebernommen und die restlichen Felder auf den
        Modus-Default zurueckgesetzt (defensive Toleranz).

        Emittiert bewusst KEIN style_changed (programmatisches Setzen).
        """
        if style is None:
            return
        self._style = style
        self._show_check.blockSignals(True)
        self._width_spin.blockSignals(True)
        self._style_combo.blockSignals(True)
        try:
            self._apply_style_to_ui(style)
            self._set_color_internal(style.color)
        finally:
            self._show_check.blockSignals(False)
            self._width_spin.blockSignals(False)
            self._style_combo.blockSignals(False)

    def set_color(self, color_str: str) -> None:
        """Setzt ausschliesslich die Farbe (behaelt show/width|size/style|shape).

        Wird vom indicator_dialog-Restore-Pfad genutzt, der aus einem
        Farb-Parameter ('type: color') nur den Farbanteil zurueckliest und
        wiederherstellt. Emittiert KEIN style_changed.
        """
        self._set_color_internal(color_str)

    def color(self) -> str:
        """Kompatibilitaets-Shim: aktuelle Farbe als String (hex/rgba)."""
        return self._color_button_value()

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _apply_style_to_ui(
        self, style: Union[LineStyle, MarkerStyle]
    ) -> None:
        """Uebernimmt ein Style-Objekt in die Teil-Widgets (Signale blockiert).

        Bei Typ-Mismatch zum Modus werden show/color uebernommen, die
        modusspezifischen Felder (width|size, style|shape) auf Defaults
        gesetzt (defensive Toleranz).
        """
        if self._style_type == "marker" and isinstance(style, MarkerStyle):
            self._show_check.setChecked(bool(style.show))
            self._width_spin.setValue(int(style.size))
            if style.shape in MARKER_SHAPES:
                self._style_combo.setCurrentText(style.shape)
            else:
                self._style_combo.setCurrentText("circle")
        elif self._style_type == "line" and isinstance(style, LineStyle):
            self._show_check.setChecked(bool(style.show))
            self._width_spin.setValue(int(style.width))
            if style.style in LINE_STYLES:
                self._style_combo.setCurrentText(style.style)
            else:
                self._style_combo.setCurrentText("solid")
        else:
            # Typ-Mismatch: show uebernehmen, modusspezifische Felder = Defaults
            self._show_check.setChecked(bool(style.show))
            if self._style_type == "marker":
                self._width_spin.setValue(6)
                self._style_combo.setCurrentText("circle")
            else:
                self._width_spin.setValue(1)
                self._style_combo.setCurrentText("solid")

    def _color_button_value(self) -> str:
        """Farb-String aus dem internen QColor (Paritaet zum Alt-ColorButton)."""
        c = getattr(self, "_color", QColor())
        if not c.isValid():
            return "#000000"
        if c.alpha() < 255:
            a = round(c.alpha() / 255.0, 2)
            return f"rgba({c.red()}, {c.green()}, {c.blue()}, {a})"
        return c.name().upper()

    def _set_color_internal(self, color_str: str) -> None:
        """Parst einen Hex-/rgba()-String und aktualisiert Swatch + Zustand.

        Ungueltige Eingaben werden ignoriert (bisherige Farbe bleibt erhalten).
        """
        parsed = self._parse_color(color_str)
        if parsed is not None:
            self._color = parsed
            self._update_swatch()

    def _update_swatch(self) -> None:
        """Setzt das Swatch-Stylesheet auf die aktuelle Farbe inkl. Deckkraft."""
        c = getattr(self, "_color", QColor())
        if not c.isValid():
            bg = "rgba(0, 0, 0, 1.0)"
        else:
            bg = f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha() / 255.0})"
        self._color_btn.setStyleSheet(
            "QPushButton#StylePickerSwatch { background-color: " + bg +
            "; border: 1px solid #555555; border-radius: 3px; }"
        )

    def _open_color_dialog(self) -> None:
        """Oeffnet QColorDialog.getColor() (mit Alpha-Slider, wenn aktiviert).

        Bei gueltiger Auswahl werden Swatch + interner Zustand aktualisiert
        und style_changed mit dem neuen Style-Objekt emittiert.
        """
        options = QColorDialog.ColorDialogOption(0)
        if self._enable_alpha:
            options |= QColorDialog.ColorDialogOption.ShowAlphaChannel
        chosen = QColorDialog.getColor(self._color, self, "Farbe auswählen", options)
        if chosen.isValid():
            self._color = chosen
            self._update_swatch()
            self._on_part_changed()

    def _on_part_changed(self, *args) -> None:
        """Zentraler Handler aller Teil-Widget-Aenderungen.

        Aktualisiert den internen Zustand und emittiert style_changed mit dem
        aktuellen Style-Objekt.
        """
        self._style = self.get_style()
        self.style_changed.emit(self._style)

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
