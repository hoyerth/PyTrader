"""
indicator_dialog_run.py - Set-Logik/Run: Logic-Params, Preset-Payload, Set-CRUD, Run-Worker, Commit

23.10 God-File-Split (15.08.2026): Aus chart/indicator_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der
IndicatorSettingsDialog-Klasse als Mixin (Klasse IndicatorSettingsDialogRunMixin).
"""

from typing import (
    Any,
    Dict,
    Optional,
)

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from chart.overlays.style_models import (
    LineStyle,
    MarkerStyle,
)

from chart.widgets.style_picker_widget import (
    StylePickerWidget,
)

from chart.indicator_dialog_support import (
    DialogServiceSetRunWorker,
)

class IndicatorSettingsDialogRunMixin:

	def _resolve_set_logic_params(self) -> Dict[str, Any]:
		"""5.4 Schritt 2: Berechnungslogik des gewählten Service-Sets.

		Liefert lookback + params des Service im Set, dessen plugin_id zum
		aktiven Plugin passt (sonst erster Service). Leer, wenn kein Set
		gewählt ist oder das Set keine Services hat. Die Darstellung (Farben,
		Sichtbarkeiten) bleibt davon unberührt – sie lebt in display_params.
		"""
		if self.plugin is None:
			return {}
		set_id = self.combo_service_set.currentData() if self.combo_service_set else ""
		if not set_id:
			return {}
		try:
			definition = self.set_repo.get_set(set_id)
			services = (definition or {}).get("services") or {}
			order = (definition or {}).get("execution_order") or []
			# Alle Services des Sets mergen, die zum Indikator gehören (das
			# aktive Plugin selbst ODER deklarierte Indikator-Services wie
			# srv_grid_lines + srv_proximity). Fremde Services werden nicht eingemischt.
			svc_ids = self._indicator_service_ids()
			merged: Dict[str, Any] = {}
			merged_lookback: Optional[int] = None
			for iid in order:
				s = services.get(iid) or {}
				sid = s.get("plugin_id")
				if not (sid == self.plugin.plugin_id or sid in svc_ids):
					continue
				if s.get("lookback") is not None:
					merged_lookback = int(s["lookback"])
				merged.update(dict(s.get("params") or {}))
			if not merged and order:
				# Fallback (Alt): erster Service des Sets
				s = services.get(order[0]) or {}
				if s.get("lookback") is not None:
					merged_lookback = int(s["lookback"])
				merged.update(dict(s.get("params") or {}))
			if merged_lookback is not None:
				merged["lookback"] = merged_lookback
			return merged
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Service-Set '{set_id}' nicht ladbar: {e}")
			return {}

	def _collect_logic_params(self) -> Dict[str, Any]:
		"""5.5 Fix: Live-Service-Parameter (logic_params) aus den Controls.

		Alle Nicht-Darstellungs-Keys aus self.param_controls (Box
		'Service-Parameter' + Expert-Optionen des aktiven Plugins) - also
		grid_step, proximity_threshold, prox_levels, lookback usw. Diese
		ueberlagern im Chart die Basis-Logik des Service-Sets (Live-Overlay).
		USER-REQ: Zusaetzlich werden die aktuellen Werte der Service-Seiten
		(_set_param_controls) als Live-Overlay gemeldet, damit Aenderungen an
		Service-Parametern SOFORT im Chart sichtbar werden (on_param_control_
		changed feuert bei editingFinished ueber create_schema_control).
		"""
		logic: Dict[str, Any] = {}
		for key, ctrl in self.param_controls.items():
			if not self._is_visual_key(key):
				logic[key] = self._ctrl_value(ctrl)
		for fkey, ctrl in self._set_param_controls.items():
			iid, key = fkey.split(":", 1)
			if self._is_visual_key(key) or key == "lookback":
				continue  # Darstellung + Instanz-Setting (lookback) nicht in die Logik
			logic[key] = self._ctrl_value(ctrl)
		return logic

	def _build_preset_payload(self) -> Dict[str, Any]:
		"""5.4 Schritt 2 + 5.5 Fix: Getrenntes Rückgabe-Dictionary (Logik vs. Darstellung).

		Plugin-Modus: set_id (gewähltes Service-Set) + logic_params (Live-
		Service-Parameter aus der Box 'Service-Parameter' + Expert-Optionen)
		+ display_params (nur reine Darstellung: Sichtbarkeit, Farben). Die
		Basis-Berechnungslogik lebt im Service-Set (service_sets-Tabelle);
		logic_params ueberlagert sie als Live-Overlay, damit Aenderungen an
		grid_step / prox_levels / lookback SOFORT auf dem Chart erscheinen.
		Legacy (Alt-Indikator ohne Plugin): volle params (kein Set).
		"""
		if self.plugin is None:
			return dict(self.collect_params_from_ui())
		set_id = self.combo_service_set.currentData() if self.combo_service_set else ""
		display: Dict[str, Any] = {}
		for key, ctrl in self.param_controls.items():
			if self._is_visual_key(key):
				display[key] = self._ctrl_value(ctrl)
				# P16.03-Bugfix: Form/Groesse bzw. Linienart/-staerke in
				# display_params aufnehmen (Konvention 'color' -> 'shape'/'size'
				# bzw. 'style'/'width'), damit Presets die Auswahl im
				# StylePickerWidget round-trippen. Bugfix (06.08.2026):
				# color_only-Waehler (Multi-MA) haben KEINE Geschwister-Keys
				# und werden uebersprungen.
				if isinstance(ctrl, StylePickerWidget):
					if getattr(ctrl, "color_only", False):
						continue
					style_obj = ctrl.get_style()
					if isinstance(style_obj, MarkerStyle):
						shape_key, size_key = self._style_sibling_keys(key, "marker")
						if shape_key:
							display[shape_key] = style_obj.shape
						if size_key:
							display[size_key] = style_obj.size
					elif isinstance(style_obj, LineStyle):
						style_key, width_key = self._style_sibling_keys(key, "line")
						if style_key:
							display[style_key] = style_obj.style
						if width_key:
							display[width_key] = style_obj.width
		return {"set_id": set_id or "", "logic_params": self._collect_logic_params(),
		        "display_params": display}

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
		if self.edit_set_description:
			definition["description"] = self.edit_set_description.text().strip()

		# Kein Set geladen → die Indikator-Services (z.B. srv_grid_lines + srv_proximity)
		# als neue Services, sonst das aktive Plugin (instance_id = plugin_id).
		if not definition.get("execution_order") and self.plugin is not None:
			svc_ids = self._indicator_service_ids()
			if svc_ids:
				for sid in svc_ids:
					try:
						from analytics.features.feature_builder import PluginRegistry
						base = dict(getattr(PluginRegistry().get(sid), "default_params", None) or {})
					except Exception:
						base = {}
					params = dict(base)
					lookback = int(params.pop("lookback", 1000) or 1000) if "lookback" in params else 1000
					for fkey, ctrl in self._set_param_controls.items():
						iid, key = fkey.split(":", 1)
						if iid != sid:
							continue
						if key == "lookback":
							lookback = int(self._ctrl_value(ctrl))
						else:
							params[key] = self._ctrl_value(ctrl)
					services[sid] = {"plugin_id": sid, "lookback": lookback, "params": params}
				definition["execution_order"] = list(svc_ids)
			else:
				pid = self.plugin.plugin_id
				params: Dict[str, Any] = {}
				lookback: int = 1000
				# Phase 14 P14-01: Der Plugin-als-Service-Editor liegt jetzt in
				# den Service-Seiten (_set_param_controls), nicht mehr auf einer
				# separaten Plugin-Live-Seite (param_controls / self.params).
				for fkey, ctrl in self._set_param_controls.items():
					c_iid, key = fkey.split(":", 1)
					if c_iid != pid:
						continue
					if key == "lookback":
						lookback = int(self._ctrl_value(ctrl))
					else:
						params[key] = self._ctrl_value(ctrl)
				services[pid] = {"plugin_id": pid, "lookback": lookback, "params": params}
				definition["execution_order"] = [pid]

		# Service-Params aus den Set-Formular-Seiten übernehmen.
		# lookback ist die Service-Instanz-Einstellung (ServiceInstanceConfig.
		# lookback) und wird NICHT in params geschrieben.
		for fkey, ctrl in self._set_param_controls.items():
			iid, pkey = fkey.split(":", 1)
			existing_cfg = services.get(iid) or {}
			pid = (existing_cfg.get("plugin_id")
			       or (iid if iid in self._indicator_service_ids()
			           else (self.plugin.plugin_id if self.plugin else iid)))
			cfg = services.setdefault(iid, {"plugin_id": pid, "params": {}})
			if pkey == "lookback":
				cfg["lookback"] = int(self._ctrl_value(ctrl))
			else:
				cfg.setdefault("params", {})[pkey] = self._ctrl_value(ctrl)

		# Phase 14 P14-01: Instanz-Beschreibung aus den Service-Seiten
		# übernehmen (ServiceInstanceConfig.description – gehört NICHT in params).
		for iid, ctrl in self._set_desc_controls.items():
			existing_cfg = services.get(iid) or {}
			pid = (existing_cfg.get("plugin_id")
			       or (iid if iid in self._indicator_service_ids()
			           else (self.plugin.plugin_id if self.plugin else iid)))
			cfg = services.setdefault(iid, {"plugin_id": pid, "params": {}})
			cfg["description"] = ctrl.text().strip()

		definition["services"] = services
		return definition

	def _generate_default_service_set_name(self) -> str:
		"""Generiert einen vorgegebenen Namen aus Indikator-Name und Symbol.

		Bugfix: Vorschlag im Format '<Indikator-Name>-<Symbol>-', getrennt
		durch Bindestriche OHNE Leerzeichen (z. B. 'Ind_FixedGridProximity-BTCUSD-').
		Als Vorgabe wird NUR der Indikator-Name genommen (display_name, ohne
		'(Plugin)'-Suffix) – NICHT die Service-Namen (plugin.metadata
		enthaelt z. B. 'Ind_FixedGridProximity' und faellt als Quelle
		weg). Fallback auf plugin_id bzw. 'Set'; Symbol aus dem Dialog-
		Kontext, Fallback 'DEFAULT'.
		"""
		indicator_name: str = ""
		dn = getattr(self.indicator, "display_name", None)
		if dn and str(dn).strip():
			indicator_name = str(dn).strip()
		# Nachgestelltes '(Plugin)'-Suffix entfernen (reiner Indikator-Name).
		if indicator_name.endswith(")"):
			import re
			indicator_name = re.sub(r"\s*\([^)]*\)\s*$", "", indicator_name).strip()
		if not indicator_name and self.plugin is not None:
			indicator_name = str(getattr(self.plugin, "plugin_id", "") or "").strip()
		if not indicator_name:
			indicator_name = "Set"
		symbol = str(getattr(self, "symbol", None) or "DEFAULT").strip() or "DEFAULT"
		return f"{indicator_name}-{symbol}-"

	def create_new_service_set(self) -> None:
		"""Setzt den Editor zurück, um ein völlig neues Service-Set anzulegen,
		und belegt das Namensfeld mit einem dynamischen Vorschlag vor.

		5.6 + 5.6.5: Parität zur Preset-Verwaltung – „Neu / Leeren“ leert die
		Set-Auswahl („- kein Set -“), setzt _current_set_id/_current_set_definition
		auf None und baut den Service-Stack auf den Default-Zustand (Indikator-
		Services mit Default-Params) zurück. Das Namensfeld wird danach mit
		'<Indikator-Name> - <Symbol>' vorbelegt und der Text für die direkte
		Bearbeitung markiert (selectAll + Fokus). Die Service-Parameter des
		aktiven Plugins (Live-Overlay) bleiben als Ausgangsbasis erhalten.
		"""
		self._current_set_id = None
		self._current_set_definition = None
		if self.edit_set_name:
			self.edit_set_name.clear()
		if self.edit_set_description:
			self.edit_set_description.clear()
		if self.combo_service_set:
			self.combo_service_set.blockSignals(True)
			self.combo_service_set.setCurrentIndex(0)  # "- kein Set -"
			self.combo_service_set.blockSignals(False)
		# _on_service_set_changed leert Namensfeld, baut combo_service_sel +
		# Service-Stack neu und setzt self.params auf die Indikator-Default-Logik.
		self._on_service_set_changed()
		# 5.6.5: Namensfeld mit dynamischem Vorschlag vorbelegen + markieren.
		default_name = self._generate_default_service_set_name()
		if self.edit_set_name:
			self.edit_set_name.setText(default_name)
			self.edit_set_name.selectAll()
			self.edit_set_name.setFocus()
		if self._ui_ready:
			self._reflow()

	def save_service_set(self) -> None:
		"""Speichert das aktive Set – analog zur Preset-Verwaltung (generisch).

		Namensdialog (vorbelegt), leerer Name → Auto-Name aus instance_ids
		(z.B. 'grid_1 + prox_1'), Überschreiben-Rückfrage bei doppeltem Namen.
		Implementierung: NamedItemActionsMixin.save_named_item() mit dem
		Service-Set-Adapter (_ServiceSetItemAdapter).
		"""
		self.save_named_item(
			self._set_adapter,
			dialog_title="Service-Set speichern",
			prompt="Name für das Service-Set:",
		)

	def delete_service_set(self) -> None:
		"""Löscht das gewählte Set – analog zur Preset-Verwaltung (generisch).

		Rückfrage (QMessageBox.question), danach wird das nächstverfügbare Set
		ausgewählt. Implementierung: NamedItemActionsMixin.delete_named_item()
		mit dem Service-Set-Adapter.
		"""
		self.delete_named_item(self._set_adapter)

	# -------------------------------------------------------------------------
	# USER-REQ: Automatische Set-Ausfuehrung bei Service-Parameter-Aenderung
	# -------------------------------------------------------------------------

	def _connect_service_param_commit(self, ctrl: QWidget) -> None:
		"""Verbindet ein Service-Parameter-Control mit der Auto-Ausfuehrung.

		USER-REQ: Bei Verlassen des Eingabefeldes (editingFinished bei
		SpinBox/LineEdit) bzw. sofortiger Aenderung (Checkbox/Combo) wird das
		Set automatisch ausgefuehrt, damit die Aenderung sofort im Chart
		sichtbar wird. on_param_control_changed (in create_schema_control
		verbunden) meldet die Werte bereits als Live-Overlay an den Chart;
		diese Methode ergaenzt nur den Auto-Run.
		"""
		if isinstance(ctrl, (QSpinBox, QDoubleSpinBox, QLineEdit)):
			ctrl.editingFinished.connect(self._on_service_param_commit)
		elif isinstance(ctrl, QCheckBox):
			ctrl.toggled.connect(self._on_service_param_commit)
		elif isinstance(ctrl, QComboBox):
			ctrl.currentTextChanged.connect(self._on_service_param_commit)

	def _on_service_param_commit(self, *args: Any) -> None:
		"""Fuehrt das Set nach einer Service-Parameter-Aenderung aus."""
		self.execute_service_set()

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
