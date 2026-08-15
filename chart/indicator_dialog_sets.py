"""
indicator_dialog_sets.py - Service-Set-Liste/-Auswahl: Service-IDs/-Items/-Cfg, Set-Combo, Tooltip, Stack-Rebuild

23.10 God-File-Split (15.08.2026): Aus chart/indicator_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der
IndicatorSettingsDialog-Klasse als Mixin (Klasse IndicatorSettingsDialogSetsMixin).
"""

from typing import (
    Any,
    Dict,
    List,
)

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QWidget,
    QVBoxLayout,
)

from analytics.engine.description_dialog import (
    ServiceDescriptionDialog,
)

class IndicatorSettingsDialogSetsMixin:

	# -------------------------------------------------------------------------
	# Indikator-Services (Phase 13 Schritt 6-Korrektur): die Services, die der
	# aktive Plugin-Indikator intern ausführt (z.B. srv_grid_lines + srv_proximity beim
	# Ind_FixedGridProximity-Indikator). grid_liquidity (Altbestand) ist nur Schema-
	# Quelle und KEIN Service des Indikators.
	# -------------------------------------------------------------------------

	def _indicator_service_ids(self) -> List[str]:
		"""Service-Plugin-IDs, die der aktive Indikator intern ausführt.

		Leer, wenn der Indikator keine deklariert → Fallback auf die Services
		des gewählten Sets (Alt-Verhalten).
		"""
		if self.indicator is None:
			return []
		ids = getattr(self.indicator, "service_plugin_ids", None)
		if isinstance(ids, (list, tuple)):
			return [str(x) for x in ids]
		return []

	def _service_items(self) -> List[Dict[str, Any]]:
		"""Anzuzeigende Services im Prop-Fenster: [{instance_id, plugin_id}].

		Bevorzugt die vom Indikator deklarierten Service-IDs (z.B. srv_grid_lines +
		srv_proximity). Existiert ein Service mit dieser plugin_id im gewählten Set,
		wird dessen instance_id (z.B. grid_1) übernommen; sonst plugin_id.
		Ohne Indikator-Deklaration: die Services des gewählten Sets.
		Phase 14 P14-01: Fallback auf das aktive Plugin als Service, wenn weder
		Set-Services noch deklarierte Services existieren (konsistent zur
		Service-Erzeugung in collect_set_definition).
		"""
		svc_ids = self._indicator_service_ids()
		definition = self._current_set_definition
		services = ((definition or {}).get("services") or {}) if definition else {}
		if not svc_ids:
			items = [
				{"instance_id": iid,
				 "plugin_id": (services.get(iid) or {}).get("plugin_id") or "?"}
				for iid in ((definition or {}).get("execution_order") or [])
			]
		else:
			items = []
			for pid in svc_ids:
				iid = next(
					(i for i in ((definition or {}).get("execution_order") or [])
					 if (services.get(i) or {}).get("plugin_id") == pid),
					None,
				)
				items.append({"instance_id": iid or pid, "plugin_id": pid})
		if not items and self.plugin is not None:
			items = [{"instance_id": self.plugin.plugin_id,
			          "plugin_id": self.plugin.plugin_id}]
		return items

	def _service_cfg(self, plugin_id: str) -> Dict[str, Any]:
		"""Konfiguration eines Service (lookback+params): aus dem gewählten Set,
		falls ein Service mit plugin_id existiert, sonst Defaults aus der
		Registry."""
		definition = self._current_set_definition
		services = ((definition or {}).get("services") or {}) if definition else {}
		for i in ((definition or {}).get("execution_order") or []):
			cfg = services.get(i) or {}
			if cfg.get("plugin_id") == plugin_id:
				return dict(cfg)
		try:
			from analytics.features.feature_builder import PluginRegistry
			sp = PluginRegistry().get(plugin_id)
			return {"plugin_id": plugin_id, "lookback": 1000,
			        "params": dict(getattr(sp, "default_params", None) or {})}
		except Exception:
			return {"plugin_id": plugin_id, "lookback": 1000, "params": {}}

	def refresh_service_set_list(self) -> None:
		"""Befüllt das Set-Dropdown aus ServiceSetRepository.list_sets()."""
		if not self.combo_service_set:
			return
		current = self.combo_service_set.currentData()
		# 5.5 Fix (Bugfix #3): Beim Oeffnen/Restore das uebergebene Set
		# vorbelegen, wenn noch keine Auswahl besteht (current leer).
		prefer = current or self._current_set_id

		self.combo_service_set.blockSignals(True)
		self.combo_service_set.clear()
		self.combo_service_set.addItem("- kein Set -", "")
		for s in self._indicator_sets():
			label = s.get("display_name") or s.get("set_id") or "Unbenannt"
			self.combo_service_set.addItem(label, s.get("set_id"))
		if prefer:
			idx = self.combo_service_set.findData(prefer)
			if idx >= 0:
				self.combo_service_set.setCurrentIndex(idx)
		self.combo_service_set.blockSignals(False)
		self._on_service_set_changed()

	def _indicator_sets(self) -> List[Dict[str, Any]]:
		"""22.01b (14.08.2026, User-Anweisung 2): Indikator-gebundene Set-Auswahl.

		Strenger Filter fuer das Prop-Fenster: nur Sets, deren
		`indicator_id == self.indicator.indicator_id` ODER die ausschliesslich
		Plugins dieses Indikators enthalten (alle service plugin_ids ⊆
		indicator.service_plugin_ids). Freie Sets und Sets anderer Indikatoren
		bleiben im globalen service_win sichtbar, NICHT hier (Konsequenz fuer
		analytics_win: bleibt ungefiltert - die Analytics-Engine liest Daten
		direkt aus dem feature_store, indikator-unabhaengig).
		"""
		try:
			all_sets = self.set_repo.list_sets()
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Set-Liste nicht ladbar: {e}")
			return []
		ind_id = str(getattr(self.indicator, "indicator_id", "") or "")
		own_plugins = {
			str(p) for p in (getattr(self.indicator, "service_plugin_ids", None) or [])
		}
		if not ind_id and not own_plugins:
			return []  # Indikator ohne Service-Zuordnung -> keine Sets anbieten
		out: List[Dict[str, Any]] = []
		for s in all_sets:
			if str(s.get("indicator_id") or "") == ind_id:
				out.append(s)
				continue
			svcs = s.get("services") or {}
			pids = [str((cfg or {}).get("plugin_id") or "")
			        for cfg in svcs.values() if isinstance(cfg, dict)]
			pids = [p for p in pids if p]
			if pids and all(p in own_plugins for p in pids):
				out.append(s)
		return out

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
				if self.edit_set_description:
					self.edit_set_description.setText(definition.get("description") or "")
		else:
			if self.edit_set_name:
				self.edit_set_name.clear()
			if self.edit_set_description:
				self.edit_set_description.clear()

		if self.combo_service_sel:
			self.combo_service_sel.blockSignals(True)
			self.combo_service_sel.clear()
			for item in self._service_items():
				self.combo_service_sel.addItem(
					f"{item['instance_id']} [{item['plugin_id']}]",
					item['instance_id'])
			self.combo_service_sel.blockSignals(False)

		# 5.4 Schritt 2: Die Berechnungslogik des gewählten Sets in self.params
		# mergen, damit Seite 0 (Service-Props des aktiven Plugins) die aktuellen
		# Logik-Werte zeigt. Die Darstellung (Farben, Sichtbarkeiten) bleibt
		# unberührt – sie lebt getrennt in display_params.
		self.params.update(self._resolve_set_logic_params())
		# 5.5 Fix (Bugfix #1+#3): Die zuletzt im Dialog gemeldeten Service-
		# Parameter (Live-Overlay / logic_params aus geladenem Preset) wieder
		# ueber die Set-Logik legen - so bleiben Aenderungen an grid_step,
		# prox_levels, ... beim Set-Wechsel UND beim Restore erhalten.
		self.params.update(self._preset_logic_params)
		self._rebuild_service_stack()

	def _on_service_selected(self, index: int) -> None:
		"""Wechselt die QStackedWidget-Seite (Seite i = Service i).

		Phase 14 P14-01: Es gibt keine separate Plugin-Live-Seite mehr –
		Seite 0 ist der erste Service (Parität zum service_win).
		"""
		if not self.stack_service_forms:
			return
		self.stack_service_forms.setCurrentIndex(max(0, index))
		# 4.4: Fenster/Box auf die neue Service-Seite nachziehen (dynamische Höhe)
		if self._ui_ready:
			self._reflow()

	# -------------------------------------------------------------------------
	# Phase 14 P14-01: Tooltips & Info-Dialog für Service-Instanzen
	# -------------------------------------------------------------------------

	def _build_tooltip(self, instance_id: str, config: Dict[str, Any]) -> str:
		"""Baut einen Rich-Text-Tooltip (HTML) für eine Service-Instanz.

		Angezeigt werden instance_id, Plugin-ID und – falls vorhanden – die
		individuelle Instanz-Beschreibung (ServiceInstanceConfig.description).
		"""
		lines = [f"<b>{instance_id}</b>", f"Plugin: {config.get('plugin_id', '?')}"]
		desc = config.get("description")
		if desc:
			lines.append(f"<i>{desc}</i>")
		return "<br>".join(lines)

	def _show_service_info(self) -> None:
		"""Öffnet den ServiceDescriptionDialog für die markierte Service-Instanz.

		Die Selektion kommt aus combo_service_sel (instance_id als UserData);
		Plugin-Objekt und Instanz-Config werden aus der Registry bzw. dem
		gewählten Set aufgelöst.
		"""
		if not self.combo_service_sel or self.plugin is None:
			return
		iid = self.combo_service_sel.currentData()
		if not iid:
			return
		cfg: Dict[str, Any] = {}
		if self._current_set_definition:
			cfg = dict((self._current_set_definition.get("services") or {}).get(iid, {}))
		# Live-Beschreibung aus dem Eingabefeld übernehmen (falls vorhanden)
		desc_ctrl = self._set_desc_controls.get(str(iid))
		if desc_ctrl is not None:
			cfg["description"] = desc_ctrl.text().strip()
		pid = cfg.get("plugin_id") or iid
		plugin = None
		try:
			from analytics.features.feature_builder import PluginRegistry
			plugin = PluginRegistry().get(pid)
		except KeyError:
			QMessageBox.warning(self, "Plugin nicht gefunden",
			                    f"Plugin '{pid}' ist nicht registriert.")
			return
		dlg = ServiceDescriptionDialog.from_plugin(
			plugin, instance_id=str(iid), config=cfg, parent=self)
		dlg.exec()

	def _rebuild_service_stack(self) -> None:
		"""Baut das QStackedWidget neu: EINE Seite pro Service aus dem
		Service-Modell – Parität zu den Service-Spalten im service_win.

		Phase 14 P14-01: Es werden NUR die im Service-Modell gespeicherten
		Parameter des jeweiligen Service angezeigt (cfg['params'] + lookback +
		description). Die frühere 'Seite 0' mit den Plugin-Live-Parametern aus
		self.params entfällt – sie zeigte Werte, die NICHT im Modell stehen.
		Rein visuelle Keys (show_*/color) werden ausgeblendet (wie service_win).
		"""
		if not self.stack_service_forms:
			return
		stack = self.stack_service_forms
		while stack.count():
			w = stack.widget(0)
			stack.removeWidget(w)
			w.deleteLater()
		self._set_param_controls = {}
		self._set_desc_controls = {}

		# Seiten fuer die anzuzeigenden Services (Indikator-Services, sonst
		# Services des gewählten Sets) – pro Service eine Seite
		for item in self._service_items():
			iid = item["instance_id"]
			pid = item["plugin_id"]
			cfg = self._service_cfg(pid)
			page = QWidget()
			vl = QVBoxLayout(page)
			# Phase 14 P14-01: Individuelle Instanz-Beschreibung (bearbeitbar) –
			# wird in ServiceInstanceConfig.description gespeichert und im
			# Info-Dialog (ServiceDescriptionDialog) angezeigt.
			desc_row = QHBoxLayout()
			desc_row.addWidget(QLabel("Beschreibung:"))
			desc_edit = QLineEdit()
			desc_edit.setPlaceholderText("Individuelle Anmerkung für diese Instanz (optional)")
			desc_edit.setText(str(cfg.get("description") or ""))
			self._set_desc_controls[iid] = desc_edit
			desc_row.addWidget(desc_edit)
			vl.addLayout(desc_row)
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
				# Normale (Nicht-Expert-, Nicht-Darstellungs-)Parameter –
				# NUR die im Service-Modell gespeicherten (wie service_win).
				for key in sp_order:
					spec = sp_schema.get(key, {})
					if spec.get("expert") or self._is_visual_key(key):
						continue
					cval = sp_params.get(key, spec.get("default"))
					# USER-REQ: P14-01 Nachtrag - Alt-Sets speichern die 6
					# Custom-Levels als Aggregat custom_levels (Liste/String)
					# statt als Einzelparameter prox_level1..6. Damit die 6
					# Level-Felder diese Werte trotzdem anzeigen, werden leere
					# Felder aus dem Aggregat vorbefüllt.
					if key.startswith("prox_level") and not cval:
						try:
							from analytics.features.definitions.srv_grid_lines import map_custom_levels_to_prox_levels
							cval = map_custom_levels_to_prox_levels(sp_params).get(key, cval)
						except Exception:
							pass
					ctrl = self.create_schema_control(key, cval, spec)
					self._set_param_controls[f"{iid}:{key}"] = ctrl
					# USER-REQ: Set bei Aenderung automatisch ausfuehren
					self._connect_service_param_commit(ctrl)
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
						# USER-REQ: Set bei Aenderung automatisch ausfuehren
						self._connect_service_param_commit(ctrl)
						ef.addRow(sp_labels.get(key, self._human(key)), ctrl)
					vl.addWidget(exp_grp)
					# 4.4: Auch der Service-Expert-Bereich ist ausklappbar
					# (Kinder ein-/ausblenden + adjustSize auf dem Dialog).
					self._setup_collapsible(exp_grp)
			except Exception:
				pf.addRow(QLabel(f"Plugin '{pid}' nicht gefunden."))
			stack.addWidget(page)

		# Phase 14 P14-01: Stack-Seite mit der Combo-Auswahl synchronisieren
		# (Seite 0 = erster Service; keine separate Plugin-Seite mehr).
		if self.combo_service_sel is not None:
			combo_idx = self.combo_service_sel.currentIndex()
		else:
			combo_idx = 0
		if stack.count():
			stack.setCurrentIndex(max(0, min(combo_idx, stack.count() - 1)))
		# 4.4: Fenster/Box auf die neue Stack-Seite nachziehen (dynamische Höhe)
		if self._ui_ready:
			self._reflow()
