"""
chart/indicator_dialog_support.py - Support-Klassen fuer den IndicatorSettingsDialog

23.03 God-File-Split (15.08.2026): Aus chart/indicator_dialog.py extrahiert,
KEINE Logik-Aenderung. Enthaelt DialogServiceSetRunWorker, _ServiceStack,
_jsonify_style_objects, _PresetItemAdapter und _ServiceSetItemAdapter.
"""

from typing import Any, Dict, List, Optional
from PySide6.QtCore import QSize, QThread, Signal
from PySide6.QtWidgets import QMessageBox, QStackedWidget

from chart.overlays.style_models import LineStyle, MarkerStyle
from chart.widgets.named_item_actions import NamedItemAdapter


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


class _ServiceStack(QStackedWidget):
	"""QStackedWidget mit dynamischer H�he anhand der AKTUELLEN Seite (Punkt 4).

	Der Standard-QStackedWidget liefert als sizeHint das MAXIMUM aller Seiten.
	Damit bliebe die Box 'Service-Parameter' so hoch wie die h�chste Service-
	Seite, auch wenn eine k�rzere Seite sichtbar ist (leerer Raum). Diese
	Variante richtet die H�he exakt nach der aktuell sichtbaren Seite aus -
	die Box endet immer unter dem letzten Parameter der aktiven Seite.
	"""

	def sizeHint(self) -> QSize:
		w = self.currentWidget()
		if w is not None:
			return w.sizeHint()
		return super().sizeHint()

	def minimumSizeHint(self) -> QSize:
		w = self.currentWidget()
		if w is not None:
			return w.minimumSizeHint()
		return super().minimumSizeHint()

	def setCurrentIndex(self, index: int) -> None:
		super().setCurrentIndex(index)
		# Eltern-Layouts informieren, dass sich die Höhe (sizeHint) geändert hat –
		# auch bei nicht angezeigtem Dialog. Sonst bleibt die Höhe der Box
		# 'Service-Parameter' auf der höchsten/alten Seite stehen.
		self.updateGeometry()


def _jsonify_style_objects(obj: Any) -> Any:
	"""P16.03 Schritt 4: Konvertiert LineStyle/MarkerStyle-Objekte rekursiv
	via .to_dict() in JSON-kompatible Dicts (vor save_indicator_preset).

	Der aktuelle Preset-Payload (_build_preset_payload) enthält nur primitive
	Werte (Farb-Strings, shape/size/style/width-Geschwister-Keys) – dieser
	Helfer ist eine DEFENSIVE Absicherung: Sollte jemals ein Style-Vertrag
	(Dataclass) direkt im Payload landen (z. B. durch ein zukünftiges
	Control), schlägt json.dumps in state_manager.save_indicator_preset
	nicht fehl, sondern speichert den JSON-Standard
	(show/color/width/style bzw. show/color/shape/size).
	"""
	if isinstance(obj, (LineStyle, MarkerStyle)):
		return obj.to_dict()
	if isinstance(obj, dict):
		return {k: _jsonify_style_objects(v) for k, v in obj.items()}
	if isinstance(obj, (list, tuple)):
		return [_jsonify_style_objects(v) for v in obj]
	return obj


class _PresetItemAdapter(NamedItemAdapter):
	"""Adapter für die PRESET-Sammlung (Referenz-Mechanik) im Prop-Fenster.

	Phase 13 Schritt 8: Die _item_*-Protokoll-Methoden liegen NICHT auf der
	Dialog-Klasse (zwei Callback-Sätze – Presets + Service-Sets – würden sich
	dort sonst gegenseitig überschreiben), sondern in je einem Adapter. Dieser
	Adapter kapselt die Preset-Verwaltung des Indikator-Prop-Fensters.
	"""

	def __init__(self, dlg: "IndicatorSettingsDialog") -> None:
		self.dlg = dlg

	def _item_scope_label(self) -> str:
		return "Preset"

	def _item_current_name(self) -> str:
		return self.dlg.current_preset_name

	def _item_current_id(self) -> Optional[str]:
		return None  # Presets werden über ihren Namen identifiziert

	def _item_auto_name(self) -> str:
		return ""  # Presets: leerer Name → Abbruch mit Hinweis

	def _item_list_names(self) -> List[str]:
		return self.dlg.state_manager.list_indicator_presets(
			self.dlg.indicator.indicator_id)

	def _item_exists(self, name: str) -> bool:
		return name in self._item_list_names()

	def _item_save_as(self, name: str) -> str:
		"""Speichert das Preset unter 'name' (getrenntes Dict {set_id, display_params})."""
		payload = self.dlg._build_preset_payload()
		# P16.03 Schritt 4: Style-Objekte vor dem JSON-Speichern via .to_dict()
		# in JSON-kompatible Dicts konvertieren (defensive Absicherung gegen
		# TypeError in state_manager.save_indicator_preset -> json.dumps).
		payload = _jsonify_style_objects(payload)
		self.dlg.state_manager.save_indicator_preset(
			self.dlg.indicator.indicator_id, name, payload)
		return name

	def _item_delete_current(self) -> bool:
		try:
			self.dlg.state_manager.delete_indicator_preset(
				self.dlg.indicator.indicator_id, self.dlg.current_preset_name)
			return True
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Preset löschen fehlgeschlagen: {e}")
			return False

	def _item_select(self, name_or_id: Optional[str] = None) -> None:
		"""Setzt die Preset-Auswahl nach Speichern (name) bzw. Löschen (None).

		Nach dem Löschen wird das nächstverfügbare Preset GELADEN (on_preset_
		selected), damit die UI-Parameter auf den nächsten Stand wechseln –
		identisches Verhalten zur bisherigen delete_current_preset()-Logik.
		"""
		if name_or_id is not None:
			self.dlg.current_preset_name = name_or_id
			self.dlg.refresh_preset_list()
			self.dlg.on_params_changed_callback(
				self.dlg._build_preset_payload(), self.dlg.current_preset_name)
			return
		remaining = [p for p in self._item_list_names()
		             if p != self._item_reserved_name()]
		nxt = remaining[0] if remaining else (self._item_reserved_name() or "")
		self.dlg.current_preset_name = nxt
		self.dlg.refresh_preset_list()
		self.dlg.on_preset_selected(nxt)

	def _item_reserved_name(self) -> Optional[str]:
		# Anwender-Anweisung 06.08.2026: 'Default' ist wie jedes andere Preset
		# überschreibbar (und löschbar) – KEIN geschützter Name mehr.
		return None


class _ServiceSetItemAdapter(NamedItemAdapter):
	"""Adapter für die SERVICE-SET-Sammlung im Indikator-Prop-Fenster.

	Phase 13 Schritt 8: identische Mechanik wie die Preset-Verwaltung, aber
	auf Service-Sets gemünzt (ServiceSetRepository statt StateManager). Die
	_item_*-Methoden greifen auf den Dialog (self.dlg) zu.
	"""

	def __init__(self, dlg: "IndicatorSettingsDialog") -> None:
		self.dlg = dlg

	def _item_scope_label(self) -> str:
		return "Service-Set"

	def _item_current_name(self) -> str:
		return self.dlg.edit_set_name.text().strip() if self.dlg.edit_set_name else ""

	def _item_current_id(self) -> Optional[str]:
		return self.dlg._current_set_id

	def _item_auto_name(self) -> str:
		"""Auto-Name aus den instance_ids (Roadmap: leerer Name → Auto-Name)."""
		try:
			from analytics.engine.service_set_repository import ServiceSetRepository
			definition = self.dlg.collect_set_definition()
			definition["display_name"] = ""
			return ServiceSetRepository._default_display_name(definition)
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Auto-Name fehlgeschlagen: {e}")
			return ""

	def _item_list_names(self) -> List[str]:
		return [s.get("display_name") or "" for s in self.dlg._indicator_sets()]

	def _item_exists(self, name: str) -> bool:
		"""True, wenn ein ANDERES Set bereits diesen Namen trägt."""
		current = self._item_current_id()
		return any(
			(s.get("display_name") or "") == name and s.get("set_id") != current
			for s in self.dlg._indicator_sets()
		)

	def _item_save_as(self, name: str) -> Optional[str]:
		"""Speichert das Set unter 'name'; liefert die set_id zurück.

		Analog Preset: Existiert bereits ein ANDERES Set mit diesem Namen und
		hat der Nutzer das Überschreiben bestätigt, wird DESSEN set_id
		übernommen (Name identifiziert das Set, kein Duplikat).
		"""
		definition = self.dlg.collect_set_definition()
		if not definition.get("execution_order") or not definition.get("services"):
			QMessageBox.information(self.dlg, "Speichern",
			                        "Keine Service-Parameter vorhanden.")
			return None
		definition["display_name"] = name
		existing = next(
			(s for s in self.dlg._indicator_sets()
			 if (s.get("display_name") or "") == name
			 and s.get("set_id") != self._item_current_id()),
			None,
		)
		if existing:
			definition["set_id"] = existing["set_id"]
		set_id = self.dlg.set_repo.save_set(definition)
		print(f"💾 [IndicatorDialog] Service-Set gespeichert: {set_id}")
		return set_id

	def _item_delete_current(self) -> bool:
		set_id = self._item_current_id()
		if not set_id:
			return False
		return self.dlg.set_repo.delete_set(set_id)

	def _item_select(self, set_id: Optional[str] = None) -> None:
		"""Setzt die Set-Auswahl nach Speichern (set_id) bzw. Löschen (None)."""
		self.dlg._current_set_id = None  # Neuauswahl erzwingen (sonst bleibt Alt-Selektion)
		self.dlg.refresh_service_set_list()
		if set_id:
			idx = self.dlg.combo_service_set.findData(set_id)
			if idx >= 0:
				self.dlg.combo_service_set.setCurrentIndex(idx)

	def _item_reserved_name(self) -> Optional[str]:
		return None  # Service-Sets haben kein geschütztes 'Default'-Set
