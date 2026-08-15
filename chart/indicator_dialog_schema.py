"""
indicator_dialog_schema.py - Schema-/Precision-Helper: Dezimalstellen, Symbol-Praezision, Key-Pruefungen

23.10 God-File-Split (15.08.2026): Aus chart/indicator_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der
IndicatorSettingsDialog-Klasse als Mixin (Klasse IndicatorSettingsDialogSchemaMixin).
"""

from typing import (
    Any,
    Dict,
)

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from chart.overlays.style_models import (
    LINE_STYLES,
    LineStyle,
    MarkerStyle,
    MARKER_SHAPES,
)

from chart.widgets.style_picker_widget import (
    StylePickerWidget,
)

class IndicatorSettingsDialogSchemaMixin:

	# -------------------------------------------------------------------------
	# Schema-basierte Control-Erzeugung (Phase 13 Schritt 5)
	# -------------------------------------------------------------------------

	@staticmethod
	def _decimal_places(value: Any) -> int:
		"""Nachkommastellen eines float (fuer QDoubleSpinBox.setDecimals).

		5.5 Fix (Bugfix #2): Floats erhalten MINDESTENS 2 Nachkommastellen.
		Damit lassen auch Felder ohne explizites step (z.B. Custom-Level
		prox_level1-6 mit Default 0.0) Nachkommastellen zu - vorher ergab
		_decimal_places(0.0) == 0 und die SpinBox hatte keine Dezimalstellen.
		"""
		if not isinstance(value, float) or value != value:  # NaN-Schutz
			return 4
		s = f"{value:.10f}".rstrip("0")
		if "." in s:
			return max(2, len(s.split(".")[1]))
		return 2

	def _get_symbol_precision(self) -> int:
		"""USER-REQ: Preisskala-Praezision (fix je Symbol) fuer die 6
		Custom-Level-Eingabefelder. Lazy ermittelt (db_service.get_symbol_
		precision) und fuer die Dialog-Instanz gecacht – kein DB-Zugriff bei
		jedem Control-Neuaufbau."""
		if self._symbol_precision is None:
			try:
				from db_service import get_symbol_precision
				self._symbol_precision = get_symbol_precision(
					self.symbol, self.timeframe)
			except Exception:
				self._symbol_precision = 2
		return self._symbol_precision

	@staticmethod
	def _is_visual_key(key: str) -> bool:
		"""Konvention fuer reine Indi-Props: Sichtbarkeit (show_*) + Farben (color)."""
		if key.startswith("show_"):
			return True
		if "color" in key.lower():
			return True
		return False

	@staticmethod
	def _style_sibling_keys(key: str, style_type: str) -> tuple:
		"""P16.03-Bugfix: Leitet die Geschwister-Keys eines StylePickerWidget-
		Params her (Konvention: 'color' im Key -> 'shape'/'size' bei marker,
		'style'/'width' bei line). Liefert (None, None), wenn keine Konvention
		passt. Die Marker-Form/-Groesse wird NICHT als separates Control
		gerendert (der StylePickerWidget zeigt sie bereits), sondern ueber
		diese Geschwister-Params persistiert (nicht in parameter_order)."""
		if "color" not in key:
			return None, None
		if style_type == "marker":
			return key.replace("color", "shape"), key.replace("color", "size")
		return key.replace("color", "style"), key.replace("color", "width")

	@staticmethod
	def _human(key: str) -> str:
		return key.replace("_", " ").title()

	def create_schema_control(self, key: str, val: Any, spec: Dict[str, Any]) -> QWidget:
		"""Erzeugt ein Eingabe-Widget exakt aus dem ParameterSchema.

		min/max/step werden 1:1 auf QDoubleSpinBox/QSpinBox uebertragen.
		"""
		p_type = spec.get("type")

		if p_type == "float":
			spin = QDoubleSpinBox()
			spin.setRange(float(spec.get("min", -1e9)), float(spec.get("max", 1e9)))
			step = spec.get("step")
			decimals = self._decimal_places(step) if step is not None else self._decimal_places(spec.get("default"))
			# USER-REQ: Custom-Levels (prox_level1..6) nutzen die Preisskala-
			# Praezision (fix je Symbol). MUSS vor setValue geschehen, sonst
			# rundet QDoubleSpinBox den Wert auf die Schema-Default-Digits.
			if key.startswith("prox_level"):
				decimals = self._get_symbol_precision()
			spin.setDecimals(min(6, max(0, decimals)))
			spin.setSingleStep(float(step) if step is not None else 0.01)
			try:
				spin.setValue(float(val))
			except (TypeError, ValueError):
				spin.setValue(float(spec.get("default", 0.0)))
			spin.editingFinished.connect(self.on_param_control_changed)
			return spin

		if p_type == "int":
			spin = QSpinBox()
			spin.setRange(int(spec.get("min", -100000)), int(spec.get("max", 100000)))
			spin.setSingleStep(int(spec.get("step", 1)))
			try:
				spin.setValue(int(val))
			except (TypeError, ValueError):
				spin.setValue(int(spec.get("default", 0)))
			spin.editingFinished.connect(self.on_param_control_changed)
			return spin

		if p_type == "bool":
			chk = QCheckBox()
			chk.setChecked(bool(val))
			chk.toggled.connect(self.on_param_control_changed)
			return chk

		if p_type == "choice":
			combo = QComboBox()
			options = [str(o) for o in (spec.get("options") or [])]
			combo.addItems(options)
			combo.setCurrentText(str(val))
			combo.currentTextChanged.connect(self.on_param_control_changed)
			return combo

		if p_type == "color":
			# 5.5 Feintuning + Phase 16 (06.08.2026): Farbparameter werden als
			# StylePickerWidget gerendert – das komplette Composite (Sichtbarkeit,
			# Farbe, Stärke, Linienart). Der Dialog liest/schreibt NUR den
			# Farbanteil via get_style()/set_color() (Refactoring-Anweisung
			# ColorButton -> StylePickerWidget, Entscheidung: vollwertiges
			# Composite, Dialog nutzt nur den Farbanteil).
			# allow_alpha aus dem Schema (Default True) schaltet den
			# Transparenz-Slider im QColorDialog (ShowAlphaChannel) frei.
			# Der Farb-Button liefert '#RRGGBB' (Alpha=255) bzw. 'rgba(r,g,b,a)'
			# (Teil-Transparenz) – 1:1 kompatibel mit TradingView v5 / CSS.
			allow_alpha = bool(spec.get("allow_alpha", True))
			# P16.03-Bugfix (06.08.2026): style_type aus der Schema-Spec
			# (Default 'line'). Circle-Farbparameter (circle_color_std/_active)
			# deklarieren "style_type": "marker" -> das Prop-Fenster zeigt
			# den MARKER-Modus (Markergröße + Form) statt Linienmodus. Der
			# passende Style-Typ wird übergeben, damit die Initialfarbe beim
			# marker-Modus nicht verloren geht (Typ-Mismatch im Widget würde
			# sonst auf die Default-Farbe zurueckfallen).
			style_type = str(spec.get("style_type", "line"))
			# Phase 16.06 (07.08.2026): Die interne 'sichtbar'-Checkbox des
			# StylePickerWidget kann per Schema-Flag 'show_visibility' (Default
			# True) ausgeblendet werden - fuer Parameter, deren Sichtbarkeit ein
			# separater 'show_*'-Param steuert (Multi-MA: show_maX,
			# FixedGridProximity: show_lines/show_circles). Damit entfaellt die
			# doppelte Sichtbarkeits-Steuerung im Dialog (get_style() liefert
			# dann show=True; die Persistenz bleibt unveraendert: color +
			# Sibling-Keys style/width bzw. shape/size).
			show_visibility = bool(spec.get("show_visibility", True))
			# Bugfix (06.08.2026): Reiner Farbwaehler (color_only im Schema,
			# z.B. Multi-MA ma1_bear_color) - KEIN StylePickerWidget-Composite.
			# Diese Farb-Parameter besitzen keine Geschwister-Keys
			# (style/width bzw. shape/size) und keine eigene
			# Sichtbarkeits-Checkbox (die steuert show_maX).
			if bool(spec.get("color_only", False)):
				if style_type == "marker":
					style_obj = MarkerStyle(color=str(val))
				else:
					style_obj = LineStyle(color=str(val))
				ctrl = StylePickerWidget(
					style=style_obj, enable_alpha=allow_alpha,
					style_type=style_type, color_only=True,
					show_visibility=show_visibility)
				ctrl.style_changed.connect(self.on_param_control_changed)
				return ctrl
			if style_type == "marker":
				# P16.03-Bugfix: Marker-Form/-Groesse aus den Geschwister-Params
				# vorbelegen (Konvention 'color' -> 'shape'/'size'), damit das
				# Widget beim Oeffnen die gespeicherte Form/Groesse zeigt.
				shape_key, size_key = self._style_sibling_keys(key, "marker")
				shape_val = "circle"
				if shape_key and shape_key in self.params:
					shape_val = str(self.params.get(shape_key) or "circle")
					if shape_val not in MARKER_SHAPES:
						shape_val = "circle"
				size_val = 6
				if size_key and size_key in self.params:
					try:
						size_val = int(self.params.get(size_key))
					except (TypeError, ValueError):
						size_val = 6
				style_obj = MarkerStyle(color=str(val), shape=shape_val, size=size_val)
			else:
				# P16.03-Bugfix: Linienart/-staerke aus den Geschwister-Params
				# vorbelegen (Konvention 'color' -> 'style'/'width'), damit das
				# Widget beim Oeffnen die gespeicherte Linienart/-staerke zeigt.
				style_key, width_key = self._style_sibling_keys(key, "line")
				style_val = "solid"
				if style_key and style_key in self.params:
					style_val = str(self.params.get(style_key) or "solid")
					if style_val not in LINE_STYLES:
						style_val = "solid"
				width_val = 1
				if width_key and width_key in self.params:
					try:
						width_val = int(self.params.get(width_key))
					except (TypeError, ValueError):
						width_val = 1
				style_obj = LineStyle(color=str(val), style=style_val, width=width_val)
			ctrl = StylePickerWidget(style=style_obj, enable_alpha=allow_alpha, style_type=style_type, show_visibility=show_visibility)
			ctrl.style_changed.connect(self.on_param_control_changed)
			return ctrl

		# str / sonstiges
		txt = QLineEdit()
		txt.setText(str(val))
		txt.editingFinished.connect(self.on_param_control_changed)
		return txt

	def _ctrl_value(self, ctrl: QWidget) -> Any:
		"""Liest den aktuellen Wert eines Controls typsicher aus."""
		if isinstance(ctrl, QCheckBox):
			return ctrl.isChecked()
		if isinstance(ctrl, QSpinBox):
			return ctrl.value()
		if isinstance(ctrl, QDoubleSpinBox):
			return ctrl.value()
		if isinstance(ctrl, QComboBox):
			return ctrl.currentText()
		if isinstance(ctrl, StylePickerWidget):
			return ctrl.get_style().color
		return ctrl.text()
