"""
indicator_dialog_presets.py - Preset-Verwaltung: Preset-Gruppe/-Liste, Params aus/in UI, Preset-Aktionen

23.10 God-File-Split (15.08.2026): Aus chart/indicator_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der
IndicatorSettingsDialog-Klasse als Mixin (Klasse IndicatorSettingsDialogPresetsMixin).
"""

from typing import (
    Any,
    Dict,
)

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
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

class IndicatorSettingsDialogPresetsMixin:

	# -------------------------------------------------------------------------
	# Preset-Verwaltung (Phase 13 Schritt 5 Punkt 4: im eigenen Rahmen)
	# -------------------------------------------------------------------------

	def _build_preset_group(self) -> QGroupBox:
		"""Baut die Preset-Verwaltungsbox (Rahmen um die Preset-Auswahl).

		Im Plugin-Modus wird sie direkt rechts oben neben 'Anzeige & Farben'
		platziert; im Legacy-Modus unten (bisherige Position). Die Box wächst
		nicht mit dem Fenster mit (Punkt 4: dynamische Größen).
		"""
		preset_group = QGroupBox("Preset")
		preset_layout = QHBoxLayout(preset_group)
		preset_layout.addWidget(QLabel("Preset:"))

		self.combo_presets = QComboBox()
		self.refresh_preset_list()
		self.combo_presets.currentTextChanged.connect(self.on_preset_selected)
		preset_layout.addWidget(self.combo_presets)

		btn_save_preset = QPushButton("💾 Speichern")
		btn_save_preset.clicked.connect(self.save_current_preset)
		preset_layout.addWidget(btn_save_preset)

		btn_delete_preset = QPushButton("❌ Löschen")
		btn_delete_preset.clicked.connect(self.delete_current_preset)
		preset_layout.addWidget(btn_delete_preset)

		preset_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
		return preset_group

	def refresh_preset_list(self) -> None:
		self.combo_presets.blockSignals(True)
		self.combo_presets.clear()
		presets = self.state_manager.list_indicator_presets(self.indicator.indicator_id)
		self.combo_presets.addItems(presets)

		if self.current_preset_name in presets:
			self.combo_presets.setCurrentText(self.current_preset_name)
		else:
			self.combo_presets.setCurrentText("Default")

		self.combo_presets.blockSignals(False)

	def collect_params_from_ui(self) -> Dict[str, Any]:
		# Mit default_params starten, damit Keys ohne UI-Control erhalten bleiben
		new_params = dict(self.indicator.default_params)

		for key, ctrl in self.param_controls.items():
			if isinstance(ctrl, QCheckBox):
				new_params[key] = ctrl.isChecked()
			elif isinstance(ctrl, QSpinBox):
				new_params[key] = ctrl.value()
			elif isinstance(ctrl, QDoubleSpinBox):
				new_params[key] = ctrl.value()
			elif isinstance(ctrl, QComboBox):
				raw_val = ctrl.currentText()
				default_val = self.indicator.default_params.get(key)

				# Typsicheres Casten anhand des Ursprungstyps im Indikator
				if isinstance(default_val, bool):
					new_params[key] = raw_val.lower() in ("true", "1", "yes")
				elif isinstance(default_val, int):
					try:
						new_params[key] = int(raw_val)
					except ValueError:
						new_params[key] = default_val
				elif isinstance(default_val, float):
					try:
						new_params[key] = float(raw_val)
					except ValueError:
						new_params[key] = default_val
				else:
					new_params[key] = raw_val
			elif isinstance(ctrl, StylePickerWidget):
				style_obj = ctrl.get_style()
				new_params[key] = style_obj.color
				# Bugfix (06.08.2026): color_only-Waehler (Multi-MA) haben
				# keine Geschwister-Keys -> Sibling-Schreiben ueberspringen.
				if getattr(ctrl, "color_only", False):
					continue
				# P16.03-Bugfix: Form/Groesse bzw. Linienart/-staerke in die
				# Geschwister-Keys schreiben (Konvention 'color' ->
				# 'shape'/'size' bzw. 'style'/'width'), damit die Auswahl im
				# Widget persistiert und der Indikator sie in den Payload gibt.
				if isinstance(style_obj, MarkerStyle):
					shape_key, size_key = self._style_sibling_keys(key, "marker")
					if shape_key:
						new_params[shape_key] = style_obj.shape
					if size_key:
						new_params[size_key] = style_obj.size
				elif isinstance(style_obj, LineStyle):
					style_key, width_key = self._style_sibling_keys(key, "line")
					if style_key:
						new_params[style_key] = style_obj.style
					if width_key:
						new_params[width_key] = style_obj.width
			elif isinstance(ctrl, QLineEdit):
				new_params[key] = ctrl.text()
		return new_params

	def update_ui_from_params(self, params_dict: Dict[str, Any]) -> None:
		for key, val in params_dict.items():
			if key in self.param_controls:
				ctrl = self.param_controls[key]
				ctrl.blockSignals(True)

				if isinstance(ctrl, QCheckBox) and isinstance(val, bool):
					ctrl.setChecked(val)
				elif isinstance(ctrl, (QSpinBox, QDoubleSpinBox)) and isinstance(val, (int, float)):
					ctrl.setValue(val)
				elif isinstance(ctrl, QComboBox):
					ctrl.setCurrentText(str(val))
				elif isinstance(ctrl, StylePickerWidget) and isinstance(val, str):
					ctrl.set_color(val)
					# Bugfix (06.08.2026): color_only-Waehler (Multi-MA) haben
					# keine Geschwister-Keys -> Restore-Schritt ueberspringen.
					if getattr(ctrl, "color_only", False):
						continue
					# P16.03-Bugfix: Form/Groesse bzw. Linienart/-staerke aus
					# den Geschwister-Params zurueckspielen (sonst zeigt das
					# Widget beim Restore die Defaults, obwohl der Chart die
					# gespeicherte Form nutzt).
					style_obj = ctrl.get_style()
					if isinstance(style_obj, MarkerStyle):
						shape_key, size_key = self._style_sibling_keys(key, "marker")
						if shape_key and shape_key in params_dict:
							shp = str(params_dict.get(shape_key) or "circle")
							if shp in MARKER_SHAPES:
								style_obj.shape = shp
						if size_key and size_key in params_dict:
							try:
								style_obj.size = int(params_dict.get(size_key))
							except (TypeError, ValueError):
								pass
						ctrl.set_style(style_obj)
					elif isinstance(style_obj, LineStyle):
						style_key, width_key = self._style_sibling_keys(key, "line")
						if style_key and style_key in params_dict:
							stl = str(params_dict.get(style_key) or "solid")
							if stl in LINE_STYLES:
								style_obj.style = stl
						if width_key and width_key in params_dict:
							try:
								style_obj.width = int(params_dict.get(width_key))
							except (TypeError, ValueError):
								pass
						ctrl.set_style(style_obj)
				elif isinstance(ctrl, QLineEdit) and isinstance(val, str):
					ctrl.setText(val)

				ctrl.blockSignals(False)

	def on_param_control_changed(self) -> None:
		self.params = self.collect_params_from_ui()
		# 5.5 Fix: Das Live-Overlay (logic_params) bei jeder Aenderung
		# mitfuehren, damit Set-Wechsel/Restore im Dialog den aktuellen
		# Stand der Service-Parameter beibehalten (Bugfix #1+#3).
		if self.plugin is not None:
			self._preset_logic_params = self._collect_logic_params()
		# 5.4 Schritt 2: Getrenntes Dict {set_id, display_params} an das
		# Chart-Window – die Berechnungslogik lebt im Service-Set.
		self.on_params_changed_callback(self._build_preset_payload(), self.current_preset_name)

	def on_preset_selected(self, preset_name: str) -> None:
		if not preset_name:
			return

		self.current_preset_name = preset_name

		if preset_name == "Default":
			self.params = dict(self.indicator.default_params)
		else:
			loaded = self.state_manager.get_indicator_preset(self.indicator.indicator_id, preset_name)
			if loaded:
				if (self.plugin is not None and isinstance(loaded, dict)
						and "display_params" in loaded):
					# 5.4 Schritt 2: Decoupled Preset (set_id + display_params).
					# Darstellung übernehmen, Set-Auswahl setzen (löst
					# _on_service_set_changed → mergt die Logik in self.params).
					# 5.5 Fix (Bugfix #3): Auch logic_params aus dem Preset
					# laden - das sind die zuletzt gemeldeten Service-Werte
					# (Live-Overlay), die beim Restore erhalten bleiben muessen.
					display = dict(loaded.get("display_params") or {})
					self._preset_logic_params = dict(loaded.get("logic_params") or {})
					set_id = loaded.get("set_id") or ""
					merged = dict(self.indicator.default_params)
					merged.update(self._preset_logic_params)
					merged.update(display)
					self.params = merged
					if self.combo_service_set:
						idx = self.combo_service_set.findData(set_id)
						self.combo_service_set.setCurrentIndex(idx if idx >= 0 else 0)
				else:
					# Legacy-Preset: volle params
					self.params = loaded

		self.update_ui_from_params(self.params)
		self.on_params_changed_callback(self._build_preset_payload(), self.current_preset_name)

	def save_current_preset(self) -> None:
		"""Speichert das aktive Preset (generische Preset-Mechanik).

		Implementierung: NamedItemActionsMixin.save_named_item() mit dem
		Preset-Adapter (_PresetItemAdapter) – Namensdialog, Überschreiben-
		Rückfrage bei doppeltem Namen. 'Default' ist überschreibbar
		(Anwender-Anweisung 06.08.2026).
		"""
		self.params = self.collect_params_from_ui()
		self.save_named_item(
			self._preset_adapter,
			dialog_title="Preset speichern",
			prompt="Name für das Parameter-Set:",
		)

	def delete_current_preset(self) -> None:
		"""Löscht das aktive Preset (generische Preset-Mechanik).

		Implementierung: NamedItemActionsMixin.delete_named_item() mit dem
		Preset-Adapter – Rückfrage, danach nächstverfügbares Preset laden.
		'Default' ist löschbar (Anwender-Anweisung 06.08.2026).
		"""
		self.delete_named_item(self._preset_adapter)
