"""
indicator_dialog_ui.py - UI-Aufbau: init_ui (Legacy/Plugin/Params-only), Collapsible, Reflow, Control-Widget

23.10 God-File-Split (15.08.2026): Aus chart/indicator_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der
IndicatorSettingsDialog-Klasse als Mixin (Klasse IndicatorSettingsDialogUiMixin).
"""

from typing import (
    Any,
    List,
)

from PySide6.QtCore import (
    Qt,
)

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QWidget,
    QVBoxLayout,
)

from chart.indicator_dialog_support import (
    _ServiceStack,
)

class IndicatorSettingsDialogUiMixin:

	# -------------------------------------------------------------------------
	# UI-Aufbau
	# -------------------------------------------------------------------------

	def init_ui(self) -> None:
		# 5.4 User-Anforderung (Scrollbar für das gesamte Fenster,
		# ContentScrollMixin): Das Fenster ist scrollbar, wenn der Inhalt
		# höher/breiter als der Bildschirm ist; sonst exakt auf Inhaltgröße.
		# Alles wird in ein Inhalt-Widget gepackt, das von einer
		# ContentScrollArea umschlossen wird; die Fenstergröße wird auf den
		# Bildschirm geklemmt (setMaximumSize). KEIN SetFixedSize auf dem
		# Inhalt-Layout: QLayout.SetFixedSize würde das Inhalt-Widget auf die
		# ERSTE Größe fixieren (setFixedSize) und späteres Wachstum (Service-
		# Seiten, aufgeklappte Experten-Optionen) blockieren; die Klemme würde
		# zudem das Screen-Cap überschreiben. resize_to_clamped_content() setzt
		# das Inhalt-Widget in jedem Reflow explizit auf die Layout-Größe.
		outer = QVBoxLayout(self)
		outer.setContentsMargins(0, 0, 0, 0)

		self._content_widget = QWidget()
		content_layout = QVBoxLayout(self._content_widget)
		content_layout.setSpacing(6)
		content_layout.setAlignment(Qt.AlignTop)

		plugin = self._get_plugin()
		if plugin is not None:
			self._init_plugin_ui(content_layout, plugin)
		else:
			self._init_legacy_ui(content_layout)
			# Preset-Verwaltung (Legacy: unten, im eigenen Rahmen)
			content_layout.addWidget(self._build_preset_group())

		# Bugfix (06.08.2026): _init_plugin_ui_params_only platziert den
		# Schließen-Button bereits im Plugin-Grid (Zeile 0, Spalte 2, rechts
		# mittig neben der Preset-Box) - hier NUR anfügen, wenn er nicht
		# schon im Plugin-Grid sitzt (sonst
		# Doppel-Button).
		if not getattr(self, "_close_placed_in_plugin_ui", False):
			btn_close = QPushButton("Schließen")
			btn_close.clicked.connect(self.accept)
			content_layout.addWidget(btn_close)

		# ScrollArea umschließt den Inhalt (natürliche Größe); das Fenster wird
		# auf den Bildschirm geklemmt (Scrollbars bei Überlänge, sonst exakt
		# Inhaltgröße – ohne fixe Pixelwerte).
		self.install_content_scroll(self._content_widget, parent_layout=outer)

		self._ui_ready = True
		self._reflow()

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

		# Bugfix (06.08.2026): Plugin-Indikator OHNE deklarierte Services
		# (service_plugin_ids leer, z.B. Multi-MA 'ind_moving_averages').
		# Anwenderanforderung: "in diesem indikator gibt es keine services -
		# dazu alles ausblenden". Alle Service-Boxen ('Service-Parameter',
		# 'Service-Set Aktionen', 'Experten-Optionen') entfallen KOMPLETT;
		# der selbst-contained Indikator rendert stattdessen ALLE Parameter
		# direkt (param_layout-gruppiert, inkl. der vorher fehlenden
		# maX_type/maX_period/maX_smooth_type/maX_alpha).
		has_services = bool(self._indicator_service_ids())
		if not has_services:
			self._init_plugin_ui_params_only(main_layout)
			return

		# --- 1) Grid: Indi-Props + Service-Parameter links; rechts daneben auf
		# gleicher Höhe 'Service-Set Aktionen' (darunter 'Experten-Optionen') ---
		# Zeile 0: 'Anzeige & Farben' (links) + Preset-Rahmen (rechts oben).
		# Zeile 1: 'Service-Parameter' (links) + 'Service-Set Aktionen' mit der
		# 'Experten-Optionen'-Box direkt darunter (rechts) – die drei
		# Service-Boxen gehören thematisch zusammen und stehen daher auf
		# gleicher Höhe (gleiche Grid-Zeile, AlignTop).
		content_grid = QGridLayout()
		content_grid.setSpacing(6)
		left_col = QVBoxLayout()
		left_col.setAlignment(Qt.AlignTop)

		# --- 1a) Reine Indi-Props (Sichtbarkeit, Farben) oberhalb der Trennlinie ---
		indi_keys = [k for k in self.plugin_order if self._is_visual_key(k)]
		if indi_keys:
			indi_group = QGroupBox("Anzeige & Farben")
			# Horizontal Expanding -> füllt die Spaltenbreite (identisch mit der
			# Breite der Box 'Service-Parameter'); vertikal Maximum (Inhalt-Höhe).
			indi_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
			indi_form = QFormLayout(indi_group)
			for key in indi_keys:
				spec = self.plugin_schema.get(key, {})
				cval = self.params.get(key, spec.get("default"))
				ctrl = self.create_schema_control(key, cval, spec)
				self.param_controls[key] = ctrl
				indi_form.addRow(self.plugin_labels.get(key, self._human(key)), ctrl)
			left_col.addWidget(indi_group)

			# --- 1b) Trennlinie ---
			line = QFrame()
			line.setFrameShape(QFrame.HLine)
			line.setFrameShadow(QFrame.Sunken)
			left_col.addWidget(line)

		content_grid.addLayout(left_col, 0, 0, Qt.AlignTop)

		# --- 1c) Service-Parameter-Box (links, Zeile 1) ---
		svc_group = QGroupBox("Service-Parameter")
		# 4.2.4: Vertikale Size-Policy = Maximum -> Die Box endet dynamisch
		# unter dem letzten Parameter (z.B. Level 6) und waechst beim
		# Vergroessern des Fensters NICHT mit (bleibt auf Inhalt-Hoehe).
		svc_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
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
		# USER-REQ: Info-Button kompakt (nur Icon 'i'), Tooltip kurz.
		self.btn_info_service = QPushButton("ℹ")
		self.btn_info_service.setToolTip("Beschreibung des Services")
		self.btn_info_service.setFixedSize(28, 28)
		self.btn_info_service.clicked.connect(self._show_service_info)
		svc_row.addWidget(self.btn_info_service)
		svc_layout.addLayout(svc_row)

		self.stack_service_forms = _ServiceStack()
		# 4.4: Das QStackedWidget nutzt Maximum (vertikal), damit die Box
		# 'Service-Parameter' exakt unter dem letzten Parameter der AKTUELL
		# sichtbaren Service-Seite endet (kein leerer Raum durch hoechste Seite).
		self.stack_service_forms.setSizePolicy(
			QSizePolicy.Expanding, QSizePolicy.Maximum)
		svc_layout.addWidget(self.stack_service_forms)

		content_grid.addWidget(svc_group, 1, 0, Qt.AlignTop)

		# --- 1d) Rechte Spalte Zeile 0: Preset-Rahmen (rechts oben) ---
		right_top = QVBoxLayout()
		right_top.setAlignment(Qt.AlignTop)
		right_top.addWidget(self._build_preset_group(), 0, Qt.AlignTop)
		content_grid.addLayout(right_top, 0, 1, Qt.AlignTop)

		# --- 1e) Rechte Spalte Zeile 1: Service-Set Aktionen + Experten-Optionen ---
		# Direkt auf Höhe der 'Service-Parameter'-Box (gleiche Grid-Zeile 1),
		# die Expert-Box unmittelbar darunter – thematisch zusammengehörig.
		right_bottom = QVBoxLayout()
		right_bottom.setAlignment(Qt.AlignTop)

		# Set-Aktionen: Name / Speichern / Ausführen / Löschen
		act_group = QGroupBox("Service-Set Aktionen")
		# Horizontal Expanding -> füllt die rechte Spaltenbreite (wie Preset);
		# vertikal Maximum -> bleibt auf Inhalt-Höhe (Punkt 4).
		act_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
		act_layout = QVBoxLayout(act_group)

		name_row = QHBoxLayout()
		name_row.addWidget(QLabel("Name:"))
		self.edit_set_name = QLineEdit()
		name_row.addWidget(self.edit_set_name)
		act_layout.addLayout(name_row)

		# Phase 14 P14-01: Set-Beschreibung unter dem Set-Namen
		desc_row = QHBoxLayout()
		desc_row.addWidget(QLabel("Beschreibung:"))
		self.edit_set_description = QLineEdit()
		self.edit_set_description.setPlaceholderText(
			"Ausführliche Set-/Strategie-Beschreibung (optional)")
		self.edit_set_description.setToolTip(
			"Individuelle Anmerkung für dieses Service-Set (Phase 14 P14-01).")
		desc_row.addWidget(self.edit_set_description)
		act_layout.addLayout(desc_row)

		btn_row = QHBoxLayout()
		self.btn_new_service_set = QPushButton("✨ Neu")
		self.btn_new_service_set.clicked.connect(self.create_new_service_set)
		btn_row.addWidget(self.btn_new_service_set)
		self.btn_save_set = QPushButton("💾 Set speichern")
		self.btn_save_set.clicked.connect(self.save_service_set)
		btn_row.addWidget(self.btn_save_set)
		# USER-REQ: Set-ausführen-Button kompakt (nur Icon ▶, Tooltip statt Text)
		self.btn_execute_set = QPushButton("▶")
		self.btn_execute_set.setToolTip("Set ausführen")
		self.btn_execute_set.setFixedSize(28, 28)
		self.btn_execute_set.clicked.connect(self.execute_service_set)
		btn_row.addWidget(self.btn_execute_set)
		self.btn_delete_set = QPushButton("❌ Set löschen")
		self.btn_delete_set.clicked.connect(self.delete_service_set)
		btn_row.addWidget(self.btn_delete_set)
		act_layout.addLayout(btn_row)

		right_bottom.addWidget(act_group, 0, Qt.AlignTop)

		# Expert-Bereich (ausklappbar) mit Plugin-Metadaten
		self.group_expert = QGroupBox("Experten-Optionen")
		self.group_expert.setCheckable(True)
		self.group_expert.setChecked(False)
		# Horizontal Expanding -> füllt die rechte Spaltenbreite; vertikal
		# Maximum -> kollabiert beim Zuklappen auf die Titelzeile (Punkt 4).
		self.group_expert.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
		expert_layout = QVBoxLayout(self.group_expert)

		# Bugfix 05.08.2026: `metadata` ist eine PluginFeature-Property – der
		# Plugin-Pfad (Branch 1 in _get_plugin) kann aber auch einen Indikator
		# liefern, der parameter_schema+plugin_id implementiert (z.B.
		# Ind_FixedGridProximity), ohne PluginFeature zu sein (kein metadata).
		# getattr-Guard: PluginFeature unveraendert, Indikator ohne metadata
		# erhaelt leere Metadaten statt AttributeError.
		meta = dict(getattr(plugin, "metadata", None) or {})
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

		# 4.4: Ausklappbarer Sub-Bereich – beim Abwählen werden die Kinder
		# ausgeblendet und das Fenster nahtlos auf die neue Höhe verkleinert.
		self._setup_collapsible(self.group_expert)

		right_bottom.addWidget(self.group_expert, 0, Qt.AlignTop)

		content_grid.addLayout(right_bottom, 1, 1, Qt.AlignTop)

		# Linke Spalte bekommt beim manuellen Aufziehen den zusätzlichen Raum
		# (beide linken Boxen wachsen horizontal mit, gleiche Breite).
		content_grid.setColumnStretch(0, 1)
		main_layout.addLayout(content_grid)

		# Initiale Set-Liste befüllen (list_sets() als Quelle, Roadmap §5.2)
		self.refresh_service_set_list()

	def _init_plugin_ui_params_only(self, main_layout: QVBoxLayout) -> None:
		"""Bugfix (06.08.2026): Plugin-Indikator OHNE deklarierte Services.

		Rendert ALLE Parameter direkt - gruppiert nach `param_layout` (z.B.
		Multi-MA: 'MA 1 (Führung)' .. 'MA 8'), sonst flach. Die Service-Boxen
		('Service-Parameter', 'Service-Set Aktionen', 'Experten-Optionen')
		entfallen komplett (Anwenderanforderung, siehe _init_plugin_ui). Die
		Preset-Verwaltung bleibt erhalten (Speichern/Laden der Parameter).
		Damit erscheinen auch die vorher fehlenden Nicht-Darstellungs-Parameter
		(maX_type/maX_period/maX_smoothing/maX_alpha) im Prop-Fenster.

		Layout (Vertrag C, 07.08.2026, Anwenderanforderungen):
		  * Zeile 0: Preset-Box ganz oben links, so breit wie MA1+MA2
		    (Spalten 0-1, span 2); rechts daneben (Spalte 2) vertikal
		    zentriert der Schließen-Button.
		  * Zeile 1: die ersten zwei Parameter-Boxen nebeneinander (MA1/MA2).
		  * Danach: je 3 Parameter-Boxen pro Zeile (Multi-MA: Zeile 2 =
		    MA3/MA4/MA5, Zeile 3 = MA6/MA7/MA8).
		  * Nichts unterhalb der letzten Boxen-Zeile -> das Fenster endet
		    exakt am unteren Rand der letzten Boxen.
		  * Das kompakte 3-Spalten-Grid ergibt ~900px Breite (ContentScroll-
		    Mixin klemmt die Groesse auf den Inhalt bzw. den Bildschirm).
		"""
		content_grid = QGridLayout()
		content_grid.setSpacing(6)

		# --- Zeile 0: Preset-Box oben links (Spalten 0-1, span 2 = bis zum
		# Ende von MA2); rechts daneben in Spalte 2 vertikal zentriert der
		# Schließen-Button (rechts mittig neben der Preset-Box). ---
		self._close_placed_in_plugin_ui = True
		content_grid.addWidget(
			self._build_preset_group(), 0, 0, 1, 2, Qt.AlignTop)

		layout_schema = getattr(self.plugin, "param_layout", None)
		groups: List[Any] = []
		if isinstance(layout_schema, list) and layout_schema \
				and isinstance(layout_schema[0], (tuple, list)):
			groups = list(layout_schema)
		else:
			groups = [("Parameter", list(self.plugin_order))]

		# Parameter-Boxen bauen (gefiltert: noch nicht gerendert, nicht expert).
		rendered_groups: List[QGroupBox] = []
		for title, keys in groups:
			# Nur noch nicht gerenderte, nicht-expert Keys dieser Gruppe.
			grp_keys = [
				k for k in keys
				if k not in self.param_controls
				and not self.plugin_schema.get(k, {}).get("expert")
			]
			if not grp_keys:
				continue
			group = QGroupBox(str(title))
			# Horizontal Expanding -> füllt die Spaltenbreite (wie die
			# 'Anzeige & Farben'-Box im Service-Pfad); vertikal Maximum.
			group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
			form = QFormLayout(group)
			for key in grp_keys:
				spec = self.plugin_schema.get(key, {})
				cval = self.params.get(key, spec.get("default"))
				ctrl = self.create_schema_control(key, cval, spec)
				self.param_controls[key] = ctrl
				form.addRow(self.plugin_labels.get(key, self._human(key)), ctrl)
			rendered_groups.append(group)

		# Nicht in param_layout enthaltene Keys flach nachtragen (Schutz).
		remaining = [
			k for k in self.plugin_order
			if k not in self.param_controls
			and not self.plugin_schema.get(k, {}).get("expert")
		]
		if remaining:
			group = QGroupBox("Weitere Parameter")
			group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
			form = QFormLayout(group)
			for key in remaining:
				spec = self.plugin_schema.get(key, {})
				cval = self.params.get(key, spec.get("default"))
				ctrl = self.create_schema_control(key, cval, spec)
				self.param_controls[key] = ctrl
				form.addRow(self.plugin_labels.get(key, self._human(key)), ctrl)
			rendered_groups.append(group)

		# --- 3-Spalten-Grid (Vertrag C, Bugfix 07.08.2026) ---
		# Zeile 1: Gruppe 1 (Spalte 0) + Gruppe 2 (Spalte 1) nebeneinander
		# (MA1/MA2). Ab Gruppe 3 folgen je 3 Boxen pro Zeile (Zeile 2:
		# G3/G4/G5, Zeile 3: G6/G7/G8). Der Schliessen-Button sitzt in
		# Zeile 0 Spalte 2 (rechts mittig neben der Preset-Box).
		btn_close = QPushButton("Schließen")
		btn_close.clicked.connect(self.accept)
		if rendered_groups:
			content_grid.addWidget(rendered_groups[0], 1, 0, Qt.AlignTop)
			if len(rendered_groups) > 1:
				content_grid.addWidget(rendered_groups[1], 1, 1, Qt.AlignTop)
			content_grid.addWidget(btn_close, 0, 2, Qt.AlignCenter)
			for i in range(2, len(rendered_groups)):
				g = i - 2
				content_grid.addWidget(
					rendered_groups[i], g // 3 + 2, g % 3, Qt.AlignTop)

		# Alle 3 Spalten wachsen beim Aufziehen gleichmaessig; die Breite
		# ergibt sich aus den drei Boxen nebeneinander ("~900px", Vertrag C).
		content_grid.setColumnStretch(0, 1)
		content_grid.setColumnStretch(1, 1)
		content_grid.setColumnStretch(2, 1)
		main_layout.addLayout(content_grid)

	# -------------------------------------------------------------------------
	# Service-Set-UI (Phase 13 Schritt 5)
	# -------------------------------------------------------------------------

	def _setup_collapsible(self, group: QGroupBox) -> None:
		"""Macht eine ausklappbare QGroupBox wirklich kollabierbar (Punkt 4).

		Beim Abwählen werden die Kinder ausgeblendet und self.adjustSize()
		verkleinert das Prop-Fenster nahtlos auf die neue Inhalt-Höhe; beim
		Aufklappen wird es entsprechend vergrößert (4.4 Implementierungsanweisung).
		"""
		def _toggle(checked: bool) -> None:
			for child in group.findChildren(QWidget):
				child.setVisible(checked)
			if self._ui_ready:
				self._reflow()
		group.toggled.connect(_toggle)
		# Initialzustand anwenden (ausgeklappt/versteckt)
		_toggle(group.isChecked())

	def _reflow(self) -> None:
		"""Erzwingt die Neuberechnung des Layouts (dynamische Größe, Punkt 4).

		Bei einem nicht angezeigten Dialog werden Show-Events nicht zugestellt,
		wodurch das Haupt-Layout sonst seinen alten sizeHint behält. Durch
		explizites invalidate() wird die Gesamthöhe immer frisch berechnet.

		5.4 User-Anforderung: Die Fenstergröße wird DEFERRED auf
		min(Inhalt, Bildschirm) gesetzt (ContentScrollMixin._schedule_reflow):
		Beim Stack-Neuaufbau sind die alten Seiten per deleteLater() noch im
		Widget-Baum; bis sie zerstört sind, liefern die Layout-Caches einen
		veralteten sizeHint. _apply_reflow_size zerstört sie erst und misst
		dann den konsistenten Inhalt.
		"""
		self._schedule_reflow()

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
