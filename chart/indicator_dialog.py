"""
chart/indicator_dialog.py - Dynamic Universal Settings Dialog with Inline Layout Support & Strict Type Validation
"""

from typing import Any, Dict, Callable, List
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
	QCheckBox,
	QComboBox,
	QDialog,
	QDoubleSpinBox,
	QFormLayout,
	QHBoxLayout,
	QInputDialog,
	QLabel,
	QLineEdit,
	QMessageBox,
	QPushButton,
	QSpinBox,
	QWidget,
	QVBoxLayout,
)

from chart.indicators.base_indicator import BaseIndicator
from state_manager import StateManager


class IndicatorSettingsDialog(QDialog):

	def __init__(
		self,
		indicator: BaseIndicator,
		current_params: Dict[str, Any],
		current_preset_name: str,
		state_manager: StateManager,
		on_params_changed_callback: Callable[[Dict[str, Any], str], None],
		parent=None
	) -> None:
		super().__init__(parent)

		self.indicator = indicator
		self.params = dict(current_params)
		self.current_preset_name = current_preset_name
		self.state_manager = state_manager
		self.on_params_changed_callback = on_params_changed_callback

		self.setWindowTitle(f"Einstellungen - {self.indicator.display_name}")
		self.setMinimumWidth(440)
		self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

		self.param_controls: Dict[str, QWidget] = {}
		self.init_ui()

	def create_control_widget(self, key: str, val: Any) -> QWidget:
		if key in self.indicator.param_options:
			combo = QComboBox()
			options = [str(opt) for opt in self.indicator.param_options[key]]
			combo.addItems(options)
			combo.setCurrentText(str(val))
			combo.currentTextChanged.connect(self.on_param_control_changed)
			return combo

		elif isinstance(val, bool):
			chk = QCheckBox()
			chk.setChecked(val)
			chk.toggled.connect(self.on_param_control_changed)
			return chk

		elif isinstance(val, int):
			spin = QSpinBox()
			spin.setRange(-100000, 100000)
			spin.setValue(val)
			spin.editingFinished.connect(self.on_param_control_changed)
			return spin

		elif isinstance(val, float):
			spin_f = QDoubleSpinBox()
			spin_f.setRange(-100000.0, 100000.0)
			spin_f.setDecimals(4)
			spin_f.setSingleStep(0.01)
			spin_f.setValue(val)
			spin_f.editingFinished.connect(self.on_param_control_changed)
			return spin_f

		else:
			txt = QLineEdit()
			txt.setText(str(val))
			txt.editingFinished.connect(self.on_param_control_changed)
			return txt

	def init_ui(self) -> None:
		main_layout = QVBoxLayout(self)
		form_layout = QFormLayout()

		layout_schema = self.indicator.param_layout

		if not layout_schema:
			layout_schema = list(self.params.keys())

		for item in layout_schema:
			if isinstance(item, str):
				key = item
				if key in self.params:
					label_text = self.indicator.param_labels.get(key, key.replace("_", " ").title())
					ctrl = self.create_control_widget(key, self.params[key])
					self.param_controls[key] = ctrl
					form_layout.addRow(label_text, ctrl)

			elif isinstance(item, tuple) and len(item) == 2:
				row_label, keys = item
				row_layout = QHBoxLayout()
				row_layout.setSpacing(6)

				for i, key in enumerate(keys):
					if key in self.params:
						# Sub-Label nur ab 2. Key, da row_label den ersten abdeckt
						if i > 0:
							sub_label = self.indicator.param_labels.get(key, "")
							if sub_label:
								row_layout.addWidget(QLabel(sub_label))
						ctrl = self.create_control_widget(key, self.params[key])
						self.param_controls[key] = ctrl
						row_layout.addWidget(ctrl)

				form_layout.addRow(row_label, row_layout)

		main_layout.addLayout(form_layout)

		# Preset-Verwaltungszeile
		preset_layout = QHBoxLayout()
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

		main_layout.addLayout(preset_layout)

		btn_close = QPushButton("Schließen")
		btn_close.clicked.connect(self.accept)
		main_layout.addWidget(btn_close)

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
				elif isinstance(ctrl, QLineEdit) and isinstance(val, str):
					ctrl.setText(val)

				ctrl.blockSignals(False)

	def on_param_control_changed(self) -> None:
		self.params = self.collect_params_from_ui()
		self.on_params_changed_callback(self.params, self.current_preset_name)

	def on_preset_selected(self, preset_name: str) -> None:
		if not preset_name:
			return

		self.current_preset_name = preset_name

		if preset_name == "Default":
			self.params = dict(self.indicator.default_params)
		else:
			loaded = self.state_manager.get_indicator_preset(self.indicator.indicator_id, preset_name)
			if loaded:
				self.params = loaded

		self.update_ui_from_params(self.params)
		self.on_params_changed_callback(self.params, self.current_preset_name)

	def save_current_preset(self) -> None:
		self.params = self.collect_params_from_ui()

		name, ok = QInputDialog.getText(
			self, "Preset speichern",
			"Name für das Parameter-Set:",
			text=self.current_preset_name if self.current_preset_name != "Default" else ""
		)
		if not ok or not name.strip():
			return

		clean_name = name.strip()
		if clean_name.lower() == "default":
			QMessageBox.warning(self, "Fehler", "Das 'Default'-Preset kann nicht überschrieben werden.")
			return

		# Prüfen ob bereits ein Preset mit diesem Namen existiert
		existing_presets = self.state_manager.list_indicator_presets(self.indicator.indicator_id)
		if clean_name in existing_presets:
			reply = QMessageBox.question(
				self, "Überschreiben bestätigen",
				f"Das Preset '{clean_name}' existiert bereits.\nMöchtest du es überschreiben?",
				QMessageBox.Yes | QMessageBox.No
			)
			if reply != QMessageBox.Yes:
				return

		self.state_manager.save_indicator_preset(self.indicator.indicator_id, clean_name, self.params)
		self.current_preset_name = clean_name
		self.refresh_preset_list()
		self.on_params_changed_callback(self.params, self.current_preset_name)

	def delete_current_preset(self) -> None:
		if self.current_preset_name == "Default":
			QMessageBox.warning(self, "Fehler", "Das 'Default'-Preset kann nicht gelöscht werden.")
			return

		reply = QMessageBox.question(
			self, "Löschen bestätigen",
			f"Möchtest du das Preset '{self.current_preset_name}' wirklich löschen?",
			QMessageBox.Yes | QMessageBox.No
		)

		if reply == QMessageBox.Yes:
			self.state_manager.delete_indicator_preset(self.indicator.indicator_id, self.current_preset_name)

			# Nächstes verfügbares Preset auswählen, sonst Default
			remaining = self.state_manager.list_indicator_presets(self.indicator.indicator_id)
			remaining = [p for p in remaining if p != "Default"]

			if remaining:
				next_preset = remaining[0]
			else:
				next_preset = "Default"

			self.current_preset_name = next_preset
			self.refresh_preset_list()
			self.on_preset_selected(next_preset)