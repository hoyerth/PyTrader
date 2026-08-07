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

Phase 13 Schritt 5 Punkt 4 (VERBINDLICH): Vollständig dynamische Fenster- &
Box-Größen – KEINE fixen Pixelwerte. Höhe/Breite des Fensters und aller Boxen
ergeben sich ausschließlich aus dem Inhalt: Haupt-Layout mit
setSizeConstraint(QLayout.SetFixedSize), SizePolicies Maximum/Preferred,
QStackedWidget-Höhe folgt der AKTUELLEN Service-Seite (_ServiceStack),
kollabierbarer Expert-Bereich mit adjustSize() (4.2–4.7 Implementierungsanweisung).

"""

from typing import Any, Dict, Callable, List, Optional
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtWidgets import (
	QApplication,
	QCheckBox,
	QComboBox,
	QDialog,
	QDoubleSpinBox,
	QFormLayout,
	QFrame,
	QGridLayout,
	QGroupBox,
	QHBoxLayout,
	QInputDialog,
	QLabel,
	QLineEdit,
	QMessageBox,
	QPushButton,
	QSizePolicy,
	QSpinBox,
	QStackedWidget,
	QWidget,
	QVBoxLayout,
)

from chart.indicators.base_indicator import BaseIndicator
from chart.overlays.style_models import LINE_STYLES, LineStyle, MarkerStyle, MARKER_SHAPES
from chart.widgets.style_picker_widget import StylePickerWidget
from chart.widgets.named_item_actions import NamedItemAdapter, NamedItemActionsMixin
from analytics.engine.description_dialog import ServiceDescriptionDialog
from state_manager import StateManager
from scrollable_content import ContentScrollMixin


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
		return [s.get("display_name") or "" for s in self.dlg.set_repo.list_sets()]

	def _item_exists(self, name: str) -> bool:
		"""True, wenn ein ANDERES Set bereits diesen Namen trägt."""
		current = self._item_current_id()
		return any(
			(s.get("display_name") or "") == name and s.get("set_id") != current
			for s in self.dlg.set_repo.list_sets()
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
			(s for s in self.dlg.set_repo.list_sets()
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


class IndicatorSettingsDialog(ContentScrollMixin, NamedItemActionsMixin, QDialog):

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
		current_set_id: Optional[str] = None,
		logic_params: Optional[Dict[str, Any]] = None,
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
		# USER-REQ (P14-03): Preisskala-Praezision je Symbol fuer die 6
		# Custom-Level-Eingabefelder (prox_level1..6). Lazy + gecacht.
		self._symbol_precision: Optional[int] = None
		self._set_repo = service_set_repo
		self._set_evaluator = None
		self._set_run_worker: Optional[DialogServiceSetRunWorker] = None
		# 5.5 Fix (Bugfix #3): Beim Restore/Neuaufbau das zuletzt gewaehlte
		# Service-Set vorbelegen, damit die Set-Combo und die Service-Logik
		# beim Oeffnen des Fensters wiederhergestellt werden.
		self._current_set_id: Optional[str] = current_set_id or None
		self._current_set_definition: Optional[Dict[str, Any]] = None
		self._set_param_controls: Dict[str, QWidget] = {}
		# Phase 14 P14-01: Beschreibungs-Eingabefelder der Service-Instanzen
		self._set_desc_controls: Dict[str, QWidget] = {}
		# 5.5 Fix: Live-Overlay der Service-Parameter (logic_params). Wird beim
		# Oeffnen vom Chart-Window getrennt uebergeben (st['logic_params']),
		# beim Preset-Laden ersetzt und nach dem Set-Logik-Merge in
		# _on_service_set_changed wieder angewendet, damit die zuletzt vom
		# Dialog gemeldeten Werte (grid_step, prox_levels, ...) beim Restore
		# und beim Set-Wechsel NICHT von den gespeicherten Set-Werten
		# ueberschrieben werden.
		self._preset_logic_params: Dict[str, Any] = dict(logic_params or {})

		# Bugfix (06.08.2026): Indikatoren OHNE deklarierte Services (z.B.
		# Multi-MA) erzeugen die Service-UI-Attribute NICHT mehr (siehe
		# _init_plugin_ui -> _init_plugin_ui_params_only). Die None-
		# Vorbelegung macht die bestehenden 'if self.<attr>:'-Guards (z.B.
		# in _build_preset_payload, on_preset_selected, refresh_service_set_
		# list) None-sicher - ohne jede Aenderung an der Service-Pfad-Logik.
		self.combo_service_set: Optional[QComboBox] = None
		self.combo_service_sel: Optional[QComboBox] = None
		self.stack_service_forms: Optional[QWidget] = None
		self.edit_set_name: Optional[QLineEdit] = None
		self.edit_set_description: Optional[QLineEdit] = None
		self.group_expert: Optional[QGroupBox] = None

		# Phase 13 Schritt 8: EIN NamedItemAdapter pro Sammlung (Presets +
		# Service-Sets). Die _item_*-Protokoll-Methoden liegen NICHT auf der
		# Dialog-Klasse, sondern in den Adaptern – zwei Callback-Sätze auf
		# derselben Klasse würden sich sonst gegenseitig überschreiben.
		self._preset_adapter = _PresetItemAdapter(self)
		self._set_adapter = _ServiceSetItemAdapter(self)

		# Plugin-Kontext (nur im Plugin-Modus gesetzt)
		self.plugin = None
		self.plugin_schema: Dict[str, Any] = {}
		self.plugin_order: List[str] = []
		self.plugin_labels: Dict[str, str] = {}

		self.setWindowTitle(f"Einstellungen - {self.indicator.display_name}")
		self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

		self.param_controls: Dict[str, QWidget] = {}
		# Phase 13 Schritt 5 Punkt 4: Fenster & Boxen sind vollständig dynamisch –
		# KEINE fixen Pixelwerte für Höhe/Breite. Die Größe ergibt sich allein aus
		# dem Inhalt (setSizeConstraint(SetFixedSize) am Ende von init_ui).
		# Während des UI-Aufbaus wird self.adjustSize() übersprungen.
		self._ui_ready = False
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
			# Bugfix (06.08.2026): Reiner Farbwaehler (color_only im Schema,
			# z.B. Multi-MA maX_color) - KEIN StylePickerWidget-Composite.
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
					style_type=style_type, color_only=True)
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
			ctrl = StylePickerWidget(style=style_obj, enable_alpha=allow_alpha, style_type=style_type)
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
	# Indikator-Services (Phase 13 Schritt 6-Korrektur): die Services, die der
	# aktive Plugin-Indikator intern ausführt (z.B. grid_lines + proximity beim
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

		Bevorzugt die vom Indikator deklarierten Service-IDs (z.B. grid_lines +
		proximity). Existiert ein Service mit dieser plugin_id im gewählten Set,
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
		for s in self.set_repo.list_sets():
			label = s.get("display_name") or s.get("set_id") or "Unbenannt"
			self.combo_service_set.addItem(label, s.get("set_id"))
		if prefer:
			idx = self.combo_service_set.findData(prefer)
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
							from analytics.features.definitions.grid_lines_service import map_custom_levels_to_prox_levels
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
			# grid_lines + proximity). Fremde Services werden nicht eingemischt.
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

		# Kein Set geladen → die Indikator-Services (z.B. grid_lines + proximity)
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
		"""Stellt die letzte POSITION des nicht-modalen Dialogs wieder her.

		Phase 13 Schritt 5 Punkt 4: Die Größe wird NICHT wiederhergestellt –
		das Prop-Fenster ist vollständig dynamisch (Inhalt bestimmt Höhe/Breite,
		keine fixen Pixelwerte, kein leerer Raum unter dem Preset-Block).
		"""
		try:
			geom = self.state_manager.get_dialog_geometry(self.DIALOG_GEOMETRY_KEY)
			if not geom:
				return

			pos_x = geom.get("pos_x")
			pos_y = geom.get("pos_y")

			# Position validieren (Bildschirm-Bounds; sonst zuruecksetzen)
			if pos_x is not None and pos_y is not None:
				screen = QApplication.primaryScreen().availableGeometry()
				if pos_x < screen.x() - 100 or pos_x > screen.right() or \
				   pos_y < screen.y() - 100 or pos_y > screen.bottom():
					pos_x = pos_y = None
				else:
					self.move(pos_x, pos_y)
		except Exception as e:
			print(f"⚠️ [IndicatorDialog] Geometrie-Restore fehlgeschlagen: {e}")

	def _save_geometry(self) -> None:
		"""Speichert die aktuelle Position/Groesse des Dialogs.

		Punkt 4: Wiederhergestellt wird nur die Position (siehe
		_restore_geometry) – die Größe ist dynamisch (Inhalt bestimmt Höhe/Breite).
		"""
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
