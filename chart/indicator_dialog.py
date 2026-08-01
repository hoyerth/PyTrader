"""
chart/indicator_dialog.py - Dynamic Universal Settings Dialog with Inline Layout Support & Strict Type Validation

Phase 13 Schritt 5 (additiv): Plugin-Prop-Fenster mit Expert-Modus & Service-Sets.
- Plugin-basierte Indikatoren (erkennbar an parameter_schema / plugin_id) erhalten
  ein NEUES Layout: reine Indi-Props (Sichtbarkeit, Farben) oberhalb einer
  Trennlinie (QFrame.HLine), darunter die Service-Props mit Set-Auswahl
  (ServiceSetRepository.list_sets()), QStackedWidget (eine Formular-Seite pro
  Service) und einem ausklappbaren Expert-Bereich (QGroupBox checkable) mit
  Plugin-Metadaten (description, author, version).
- min/max/step werden exakt aus dem ParameterSchema auf QDoubleSpinBox/QSpinBox
  übertragen; Reihenfolge + Labels kommen aus parameter_order/param_labels der
  Plugin-/Service-Definition (NICHT mehr aus dem Chart-Adapter).
- Set-Aktionen: Name vergeben / Speichern / Ausführen (ServiceSetEvaluator im
  Hintergrund-Thread) / Löschen (zwingend mit QMessageBox-Gegenfrage).
- Alt-Indikatoren ohne Plugin (z.B. 'grid') behalten das bisherige Layout.
"""

from typing import Any, Dict, Callable, List, Optional
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
	QApplication,
	QCheckBox,
	QComboBox,
	QDialog,
	QDoubleSpinBox,
	QFormLayout,
	QFrame,
	QGroupBox,
	QHBoxLayout,
	QInputDialog,
	QLabel,
	QLineEdit,
	QMessageBox,
	QPushButton,
	QSpinBox,
	QStackedWidget,
	QWidget,
	QVBoxLayout,
)

from chart.indicators.base_indicator import BaseIndicator
from state_manager import StateManager


class DialogServiceSetRunWorker(QThread):
	"""Phase 13 Schritt 5: Führt ein Service-Set im Hintergrund aus (Prop-Fenster).

	Lädt OHLCV (Symbol/Timeframe) und ruft ServiceSetEvaluator.execute_set()
	in einem separaten Thread auf, damit der Dialog nicht blockiert.
	"""

	run_finished = Signal(str, int)  # set_id, Anzahl erfolgreicher Services
	run_failed = Signal(str, str)    # set_id, Fehlermeldung

	def __init__(self, evaluator, symbol: str, timeframe: str,
	             set_definition: Dict[str, Any], parent=None) -> None:
		super().__init__(parent)
		self.evaluator = evaluator
		self.symbol = symbol
		self.timeframe = timeframe
		self.set_definition = set_definition

	def run(self) -> None:
		try:
			from analytics.features.feature_builder import FeatureBuilder, prepare_plugin_df
			from analytics.features.plugins.base_plugin import PluginContext
			from state_manager import StateManager

			settings = StateManager().get_app_settings()
			fb = FeatureBuilder()
			df = fb.load_ohlcv(self.symbol, self.timeframe, limit=settings.feature_builder_limit)
			if df is None or df.empty:
				self.run_failed.emit(
					self.set_definition.get("set_id", ""),
					f"Keine OHLCV-Daten fuer {self.symbol} {self.timeframe}.",
				)
				return

			df_plugin = prepare_plugin_df(df)
			context = PluginContext(
				symbol=self.symbol,
				timeframe=self.timeframe,
				mode="batch",
				timestamp=int(df_plugin["time"].iloc[-1]) if len(df_plugin) else None,
				settings=settings,
			)
			results = self.evaluator.execute_set(self.set_definition, df_plugin, context=context)
			self.run_finished.emit(self.set_definition.get("set_id", ""), len(results))
		except Exception as e:
			self.run_failed.emit(self.set_definition.get("set_id", ""), str(e))


class IndicatorSettingsDialog(QDialog):

	# Gemeinsamer Geometrie-Key fuer ALLE Indikator-Einstellungsdialoge
	# (gilt damit automatisch fuer alle Indikatoren, aktuelle & zukuenftige).
	DIALOG_GEOMETRY_KEY = "indicator_settings"

	def __init__(
		self,
		indicator: BaseIndicator,
		current_params: Dict[str, Any],
		current_preset_name: str,
		state_manager: StateManager,
		on_params_changed_callback: Callable[[Dict[str, Any], str], None],
		parent=None,
		symbol: str = "SILVER",
		timeframe: str = "H1",
		service_set_repo: Optional[Any] = None,
	) -> None:
		super().__init__(parent)

		self.indicator = indicator
		self.params = dict(current_params)
		self.current_preset_name = current_preset_name
		self.state_manager = state_manager
		self.on_params_changed_callback = on_params_changed_callback

		# Phase 13 Schritt 5: Service-Set-Verwaltung (lazy)
		self.symbol = symbol
		self.timeframe = timeframe
		self._set_repo = service_set_repo
		self._set_evaluator = None
		self._set_run_worker: Optional[DialogServiceSetRunWorker] = None
		self._current_set_id: Optional[str] = None
		self._current_set_definition: Optional[Dict[str, Any]] = None
		self._set_param_controls: Dict[str, QWidget] = {}

		# Plugin-Kontext (nur im Plugin-Modus gesetzt)
		self.plugin = None
		self.plugin_schema: Dict[str, Any] = {}
		self.plugin_order: List[str] = []
		self.plugin_labels: Dict[str, str] = {}

		self.setWindowTitle(f"Einstellungen - {self.indicator.display_name}")
		self.setMinimumWidth(520)
		self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

		self.param_controls: Dict[str, QWidget] = {}
		self.init_ui()

		# Nicht-modaler Dialog: letzte Position/Groesse wiederherstellen
		self._restore_geometry()

	# -------------------------------------------------------------------------
	# Phase 13 Schritt 5: Plugin-Erkennung & Schema-Zugriff
	# -------------------------------------------------------------------------

	def _get_plugin(self) -> Optional[Any]:
		"""Liefert das PluginFeature-Objekt (Schema/Metadaten) oder None (Legacy).

		Erkennung: (1) der Indikator IST ein PluginFeature (parameter_schema +
		plugin_id), oder (2) der Indikator hat eine plugin_id/_plugin_id, ueber
		die das Plugin aus der PluginRegistry geladen wird.
		"""
		if hasattr(self.indicator, "parameter_schema") and hasattr(self.indicator, "plugin_id"):
			return self.indicator
		pid = getattr(self.indicator, "_plugin_id", None) or getattr(self.indicator, "plugin_id", None)
		if pid:
			try:
				from analytics.features.feature_builder import PluginRegistry
				return PluginRegistry().get(pid)
			except Exception:
				return None
		return None

	# -------------------------------------------------------------------------
	# Service-Set-Repository (lazy – echte DB nur bei Nutzung)
	# -------------------------------------------------------------------------

	@property
	def set_repo(self) -> Any:
		if self._set_repo is None:
			from analytics.engine.service_set_repository import ServiceSetRepository
			self._set_repo = ServiceSetRepository()
		return self._set_repo

	@property
	def set_evaluator(self) -> Any:
		if self._set_evaluator is None:
			from analytics.engine.set_evaluator import ServiceSetEvaluator
			self._set_evaluator = ServiceSetEvaluator()
		return self._set_evaluator

	# -------------------------------------------------------------------------
	# Schema-basierte Control-Erzeugung (Phase 13 Schritt 5)
	# -------------------------------------------------------------------------

	@staticmethod
	def _decimal_places(value: Any) -> int:
		"""Nachkommastellen eines float (fuer QDoubleSpinBox.setDecimals)."""
		if not isinstance(value, float) or value != value:  # NaN-Schutz
			return 4
		s = f"{value:.10f}".rstrip("0")
		if "." in s:
			return len(s.split(".")[1])
		return 0

	@staticmethod
	def _is_visual_key(key: str) -> bool:
		"""Konvention fuer reine Indi-Props: Sichtbarkeit (show_*) + Farben (color)."""
		if key.startswith("show_"):
			return True
		if "color" in key.lower():
			return True
		return False

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

		# color / str / sonstiges
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
		return ctrl.text()

	# -------------------------------------------------------------------------
	# UI-Aufbau
	# -------------------------------------------------------------------------

	def init_ui(self) -> None:
		main_layout = QVBoxLayout(self)

		plugin = self._get_plugin()
		if plugin is not None:
			self._init_plugin_ui(main_layout, plugin)
		else:
			self._init_legacy_ui(main_layout)

		# Preset-Verwaltungszeile (beide Modi)
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

	def _init_legacy_ui(self, main_layout: QVBoxLayout) -> None:
		"""Bisheriges Layout fuer Alt-Indikatoren ohne Plugin-Schema (z.B. 'grid')."""
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

	def _init_plugin_ui(self, main_layout: QVBoxLayout, plugin: Any) -> None:
		"""Phase 13 Schritt 5: Plugin-Prop-Fenster mit Expert-Modus & Service-Sets.

		Was in den Expert-Bereich kommt, wird an den Parametern der
		Service-Definition angegeben (expert: True im parameter_schema der
		Definition, die ganz oben in der Datei steht). Der lookback ist ein
		Basis-Parameter (base_parameter_schema der Basisklasse) und erscheint
		dadurch automatisch für JEDES Plugin im Expert-Bereich.
		"""
		self.plugin = plugin
		base_schema = dict(getattr(plugin, "base_parameter_schema", None) or {})
		full_schema = dict(base_schema)
		full_schema.update(dict(plugin.parameter_schema or {}))
		self.plugin_schema = full_schema
		self.plugin_order = list(getattr(plugin, "parameter_order", None) or plugin.parameter_schema.keys())
		for key in base_schema:
			if key not in self.plugin_order:
				self.plugin_order.append(key)
		self.plugin_labels = dict(getattr(plugin, "param_labels", None) or {})
		for key, spec in base_schema.items():
			self.plugin_labels.setdefault(key, spec.get("description") or self._human(key))

		# --- 1) Reine Indi-Props (Sichtbarkeit, Farben) oberhalb der Trennlinie ---
		indi_keys = [k for k in self.plugin_order if self._is_visual_key(k)]
		if indi_keys:
			indi_group = QGroupBox("Anzeige & Farben")
			indi_form = QFormLayout(indi_group)
			for key in indi_keys:
				spec = self.plugin_schema.get(key, {})
				cval = self.params.get(key, spec.get("default"))
				ctrl = self.create_schema_control(key, cval, spec)
				self.param_controls[key] = ctrl
				indi_form.addRow(self.plugin_labels.get(key, self._human(key)), ctrl)
			main_layout.addWidget(indi_group)

		# --- 2) Trennlinie ---
		line = QFrame()
		line.setFrameShape(QFrame.HLine)
		line.setFrameShadow(QFrame.Sunken)
		main_layout.addWidget(line)

		# --- 3) Service-Bereich (Set-Auswahl + QStackedWidget pro Service) ---
		svc_group = QGroupBox("Service-Parameter")
		svc_layout = QVBoxLayout(svc_group)

		set_row = QHBoxLayout()
		set_row.addWidget(QLabel("Service-Set:"))
		self.combo_service_set = QComboBox()
		self.combo_service_set.currentIndexChanged.connect(self._on_service_set_changed)
		set_row.addWidget(self.combo_service_set)
		svc_layout.addLayout(set_row)

		svc_row = QHBoxLayout()
		svc_row.addWidget(QLabel("Service:"))
		self.combo_service_sel = QComboBox()
		self.combo_service_sel.currentIndexChanged.connect(self._on_service_selected)
		svc_row.addWidget(self.combo_service_sel)
		svc_layout.addLayout(svc_row)

		self.stack_service_forms = QStackedWidget()
		svc_layout.addWidget(self.stack_service_forms)

		main_layout.addWidget(svc_group)

		# --- 4) Expert-Bereich (ausklappbar) mit Plugin-Metadaten ---
		self.group_expert = QGroupBox("Experten-Optionen")
		self.group_expert.setCheckable(True)
		self.group_expert.setChecked(False)
		expert_layout = QVBoxLayout(self.group_expert)

		meta = dict(plugin.metadata or {})
		meta_text = (
			f"<b>{meta.get('display_name', plugin.plugin_id)}</b> "
			f"v{getattr(plugin, 'version', '1.0.0')}<br>"
			f"{meta.get('description', '')}<br>"
			f"Autor: {meta.get('author', '')}"
		)
		meta_label = QLabel(meta_text)
		meta_label.setWordWrap(True)
		expert_layout.addWidget(meta_label)

		expert_form = QFormLayout()
		expert_keys = [
			k for k in self.plugin_order
			if self.plugin_schema.get(k, {}).get("expert")
		]
		for key in expert_keys:
			spec = self.plugin_schema.get(key, {})
			cval = self.params.get(key, spec.get("default"))
			ctrl = self.create_schema_control(key, cval, spec)
			self.param_controls[key] = ctrl
			expert_form.addRow(self.plugin_labels.get(key, self._human(key)), ctrl)
		expert_layout.addLayout(expert_form)

		main_layout.addWidget(self.group_expert)

		# --- 5) Set-Aktionen: Name / Speichern / Ausführen / Löschen ---
		act_group = QGroupBox("Service-Set Aktionen")
		act_layout = QVBoxLayout(act_group)

		name_row = QHBoxLayout()
		name_row.addWidget(QLabel("Name:"))
		self.edit_set_name = QLineEdit()
		name_row.addWidget(self.edit_set_name)
		act_layout.addLayout(name_row)

		btn_row = QHBoxLayout()
		self.btn_save_set = QPushButton("💾 Set speichern")
		self.btn_save_set.clicked.connect(self.save_service_set)
		btn_row.addWidget(self.btn_save_set)
		self.btn_execute_set = QPushButton("▶ Set ausführen")
		self.btn_execute_set.clicked.connect(self.execute_service_set)
		btn_row.addWidget(self.btn_execute_set)
		self.btn_delete_set = QPushButton("❌ Set löschen")
		self.btn_delete_set.clicked.connect(self.delete_service_set)
		btn_row.addWidget(self.btn_delete_set)
		act_layout.addLayout(btn_row)

		main_layout.addWidget(act_group)

		# Initiale Set-Liste befüllen (list_sets() als Quelle, Roadmap §5.2)
		self.refresh_service_set_list()

	# -------------------------------------------------------------------------
	# Service-Set-UI (Phase 13 Schritt 5)
	# -------------------------------------------------------------------------

	def refresh_service_set_list(self) -> None:
		"""Befüllt das Set-Dropdown aus ServiceSetRepository.list_sets()."""
		if not self.combo_service_set:
			return
		current = self.combo_service_set.currentData()

		self.combo_service_set.blockSignals(True)
		self.combo_service_set.clear()
		self.combo_service_set.addItem("- kein Set -", "")
		for s in self.set_repo.list_sets():
			label = s.get("display_name") or s.get("set_id") or "Unbenannt"
			self.combo_service_set.addItem(label, s.get("set_id"))
		if current:
			idx = self.combo_service_set.findData(current)
			if idx >= 0:
				self.combo_service_set.setCurrentIndex(idx)
		self.combo_service_set.blockSignals(False)
		self._on_service_set_changed()

	def _on_service_set_changed(self) -> None:
		"""Lädt das gewählte Set in den Editor + baut die Service-Seiten neu."""
		set_id = self.combo_service_set.currentData() if self.combo_service_set else ""
		self._current_set_id = set_id or None
		self._current_set_definition = None

		if set_id:
			definition = self.set_repo.get_set(set_id)
			if definition:
				self._current_set_definition = definition
				if self.edit_set_name:
					self.edit_set_name.setText(definition.get("display_name") or "")
		else:
			if self.edit_set_name:
				self.edit_set_name.clear()

		if self.combo_service_sel:
			self.combo_service_sel.blockSignals(True)
			self.combo_service_sel.clear()
			if self._current_set_definition:
				services = self._current_set_definition.get("services") or {}
				for iid in (self._current_set_definition.get("execution_order") or []):
					pid = services.get(iid, {}).get("plugin_id", "?")
					self.combo_service_sel.addItem(f"{iid} [{pid}]", iid)
			self.combo_service_sel.blockSignals(False)

		self._rebuild_service_stack()

	def _on_service_selected(self, index: int) -> None:
		"""Wechselt die QStackedWidget-Seite (Seite 0 = aktives Plugin)."""
		if not self.stack_service_forms:
			return
		self.stack_service_forms.setCurrentIndex(index + 1 if index >= 0 else 0)

	def _rebuild_service_stack(self) -> None:
		"""Baut das QStackedWidget neu: Seite 0 = aktive Service-Parameter des
		Plugins, weitere Seiten = Services des gewählten Sets."""
		if not self.stack_service_forms:
			return
		stack = self.stack_service_forms
		while stack.count():
			w = stack.widget(0)
			stack.removeWidget(w)
			w.deleteLater()
		self._set_param_controls = {}

		# Seite 0: Service-Props des aktiven Plugin-Indikators (self.params)
		page0 = QWidget()
		form0 = QFormLayout(page0)
		for key in self.plugin_order:
			spec = self.plugin_schema.get(key, {})
			if self._is_visual_key(key) or spec.get("expert"):
				continue
			cval = self.params.get(key, spec.get("default"))
			ctrl = self.create_schema_control(key, cval, spec)
			self.param_controls[key] = ctrl
			form0.addRow(self.plugin_labels.get(key, self._human(key)), ctrl)
		stack.addWidget(page0)

		# Seiten fuer die Services des gewählten Sets (pro Service eine Seite)
		definition = self._current_set_definition
		if definition:
			services = definition.get("services") or {}
			for iid in (definition.get("execution_order") or []):
				cfg = services.get(iid, {})
				pid = cfg.get("plugin_id", "")
				page = QWidget()
				vl = QVBoxLayout(page)
				pf = QFormLayout()
				vl.addLayout(pf)
				try:
					from analytics.features.feature_builder import PluginRegistry
					sp = PluginRegistry().get(pid)
					sp_base = dict(getattr(sp, "base_parameter_schema", None) or {})
					sp_schema = dict(sp_base)
					sp_schema.update(dict(sp.parameter_schema or {}))
					sp_labels = dict(getattr(sp, "param_labels", None) or {})
					for key, spec in sp_base.items():
						sp_labels.setdefault(key, spec.get("description") or self._human(key))
					sp_order = list(getattr(sp, "parameter_order", None) or sp.parameter_schema.keys())
					for key in sp_base:
						if key not in sp_order:
							sp_order.append(key)
					sp_params = dict(cfg.get("params") or {})
					# Normale (Nicht-Expert-)Parameter
					for key in sp_order:
						spec = sp_schema.get(key, {})
						if spec.get("expert"):
							continue
						cval = sp_params.get(key, spec.get("default"))
						ctrl = self.create_schema_control(key, cval, spec)
						self._set_param_controls[f"{iid}:{key}"] = ctrl
						pf.addRow(sp_labels.get(key, self._human(key)), ctrl)
					# Expert-Unterbereich je Service (lookback + expert-Parameter)
					expert_keys = [k for k in sp_order if sp_schema.get(k, {}).get("expert")]
					if expert_keys:
						exp_grp = QGroupBox("Experten-Optionen")
						exp_grp.setCheckable(True)
						exp_grp.setChecked(False)
						ef = QFormLayout(exp_grp)
						for key in expert_keys:
							spec = sp_schema.get(key, {})
							if key == "lookback":
								# lookback ist die Service-Instanz-Einstellung
								# (ServiceInstanceConfig.lookback), nicht ein
								# Plugin-param.
								cval = cfg.get("lookback", spec.get("default"))
							else:
								cval = sp_params.get(key, spec.get("default"))
							ctrl = self.create_schema_control(key, cval, spec)
							self._set_param_controls[f"{iid}:{key}"] = ctrl
							ef.addRow(sp_labels.get(key, self._human(key)), ctrl)
						vl.addWidget(exp_grp)
				except Exception:
					pf.addRow(QLabel(f"Plugin '{pid}' nicht gefunden."))
				stack.addWidget(page)

		stack.setCurrentIndex(0)

	# -------------------------------------------------------------------------
	# Set-Aktionen (Phase 13 Schritt 5)
	# -------------------------------------------------------------------------

	def collect_set_definition(self) -> Dict[str, Any]:
		"""Baut die ServiceSetDefinition aus Set + Editor zusammen."""
		if self._current_set_definition:
			definition = dict(self._current_set_definition)
			services = dict(definition.get("services") or {})
		else:
			definition = {"set_id": "", "display_name": "", "execution_order": [], "services": {}}
			services = {}

		if self.edit_set_name:
			definition["display_name"] = self.edit_set_name.text().strip()

		# Kein Set geladen → aktives Plugin als neuer Service (instance_id = plugin_id)
		if not definition.get("execution_order") and self.plugin is not None:
			pid = self.plugin.plugin_id
			params: Dict[str, Any] = {}
			lookback: int = 1000
			for key in self.plugin_order:
				spec = self.plugin_schema.get(key, {})
				if self._is_visual_key(key) or key == "lookback":
					continue  # Indi-Props gehören nicht ins Service-Set; lookback ist Instanz-Einstellung
				if key in self.param_controls:
					params[key] = self._ctrl_value(self.param_controls[key])
				else:
					params[key] = self.params.get(key, spec.get("default"))
			if "lookback" in self.param_controls:
				lookback = int(self._ctrl_value(self.param_controls["lookback"]))
			else:
				lookback = int(self.params.get("lookback", 1000) or 1000)
			services[pid] = {"plugin_id": pid, "lookback": lookback, "params": params}
			definition["execution_order"] = [pid]

		# Service-Params aus den Set-Formular-Seiten übernehmen.
		# lookback ist die Service-Instanz-Einstellung (ServiceInstanceConfig.
		# lookback) und wird NICHT in params geschrieben.
		for fkey, ctrl in self._set_param_controls.items():
			iid, pkey = fkey.split(":", 1)
			cfg = services.setdefault(iid, {"plugin_id": self.plugin.plugin_id, "params": {}})
			if pkey == "lookback":
				cfg["lookback"] = int(self._ctrl_value(ctrl))
			else:
				cfg.setdefault("params", {})[pkey] = self._ctrl_value(ctrl)

		definition["services"] = services
		return definition

	def save_service_set(self) -> None:
		"""Speichert das aktive Set über ServiceSetRepository.save_set().
		Leerer Name → Auto-Name aus instance_ids (z.B. 'grid_1 + prox_1')."""
		definition = self.collect_set_definition()
		if not definition.get("execution_order") or not definition.get("services"):
			QMessageBox.information(self, "Speichern", "Keine Service-Parameter vorhanden.")
			return
		set_id = self.set_repo.save_set(definition)
		self._current_set_id = set_id
		print(f"💾 [IndicatorDialog] Service-Set gespeichert: {set_id}")
		self.refresh_service_set_list()
		idx = self.combo_service_set.findData(set_id)
		if idx >= 0:
			self.combo_service_set.setCurrentIndex(idx)

	def delete_service_set(self) -> None:
		"""Löscht das gewählte Set – zwingend mit QMessageBox-Gegenfrage."""
		set_id = self.combo_service_set.currentData() if self.combo_service_set else ""
		if not set_id:
			return
		name = self.combo_service_set.currentText()
		ret = QMessageBox.warning(
			self, "Set löschen",
			f"Service-Set '{name}' wirklich löschen?\nDies kann nicht rückgängig gemacht werden.",
			QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
		)
		if ret != QMessageBox.Yes:
			return
		self.set_repo.delete_set(set_id)
		self._current_set_id = None
		self._current_set_definition = None
		self.refresh_service_set_list()

	def execute_service_set(self) -> None:
		"""Startet den ServiceSetEvaluator für das aktive Set (Hintergrund-Thread)."""
		definition = self.collect_set_definition()
		if not definition.get("execution_order") or not definition.get("services"):
			return
		if self._set_run_worker and self._set_run_worker.isRunning():
			print("⚠️ [IndicatorDialog] Set-Ausführung läuft bereits.")
			return
		self._set_run_worker = DialogServiceSetRunWorker(
			self.set_evaluator, self.symbol, self.timeframe, definition, parent=self,
		)
		self._set_run_worker.run_finished.connect(self._on_set_run_finished)
		self._set_run_worker.run_failed.connect(self._on_set_run_failed)
		self._set_run_worker.start()

	def _on_set_run_finished(self, set_id: str, count: int) -> None:
		print(f"✅ [IndicatorDialog] Set-Ausführung abgeschlossen: {count} Services.")

	def _on_set_run_failed(self, set_id: str, error: str) -> None:
		QMessageBox.warning(self, "Set-Ausführung fehlgeschlagen", str(error))

	# -------------------------------------------------------------------------
	# Legacy-Helfer (für Alt-Indikatoren)
	# -------------------------------------------------------------------------

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

	# -------------------------------------------------------------------------
	# Geometrie-Persistenz & Presets (unverändert für beide Modi)
	# -------------------------------------------------------------------------

	def _restore_geometry(self) -> None:
		"""Stellt die letzte Position/Groesse des nicht-modalen Dialogs wieder her."""
		try:
			geom = self.state_manager.get_dialog_geometry(self.DIALOG_GEOMETRY_KEY)
			if not geom:
				return

			pos_x = geom.get("pos_x")
			pos_y = geom.get("pos_y")
			width = geom.get("width")
			height = geom.get("height")

			# Position validieren (Bildschirm-Bounds; sonst zuruecksetzen)
			if pos_x is not None and pos_y is not None:
				screen = QApplication.primaryScreen().availableGeometry()
				if pos_x < screen.x() - 100 or pos_x > screen.right() or \
				   pos_y < screen.y() - 100 or pos_y > screen.bottom():
					pos_x = pos_y = None
				else:
					self.move(pos_x, pos_y)

			# Groesse nur uebernehmen, wenn plausibel (min. Breite des Dialogs)
			if width is not None and height is not None:
				try:
					self.resize(max(440, int(width)), max(100, int(height)))
				except (ValueError, TypeError):
					pass
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Geometrie-Restore fehlgeschlagen: {e}")

	def _save_geometry(self) -> None:
		"""Speichert die aktuelle Position/Groesse des Dialogs."""
		try:
			p = self.pos()
			s = self.size()
			self.state_manager.save_dialog_geometry(
				self.DIALOG_GEOMETRY_KEY, p.x(), p.y(), s.width(), s.height()
			)
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Geometrie-Save fehlgeschlagen: {e}")

	def done(self, r: int) -> None:
		"""Wird bei jedem Schliessen aufgerufen (accept/reject/Esc/X) ->
		Geometrie vor dem Schliessen speichern."""
		self._save_geometry()
		if self._set_run_worker and self._set_run_worker.isRunning():
			self._set_run_worker.wait(2000)
		super().done(r)

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
