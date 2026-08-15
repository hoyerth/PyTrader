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
from PySide6.QtCore import Qt
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
	QWidget,
	QVBoxLayout,
)

from chart.indicators.base_indicator import BaseIndicator
from chart.overlays.style_models import LINE_STYLES, LineStyle, MarkerStyle, MARKER_SHAPES
from chart.widgets.style_picker_widget import StylePickerWidget
from chart.widgets.named_item_actions import NamedItemActionsMixin
from analytics.engine.description_dialog import ServiceDescriptionDialog
from state_manager import StateManager
from scrollable_content import ContentScrollMixin
from chart.indicator_dialog_support import (
    DialogServiceSetRunWorker, _ServiceStack, _jsonify_style_objects,
    _PresetItemAdapter, _ServiceSetItemAdapter,
)

from chart.indicator_dialog_plugin import IndicatorSettingsDialogPluginMixin
from chart.indicator_dialog_schema import IndicatorSettingsDialogSchemaMixin
from chart.indicator_dialog_ui import IndicatorSettingsDialogUiMixin
from chart.indicator_dialog_sets import IndicatorSettingsDialogSetsMixin
from chart.indicator_dialog_run import IndicatorSettingsDialogRunMixin
from chart.indicator_dialog_presets import IndicatorSettingsDialogPresetsMixin
from chart.indicator_dialog_geometry import IndicatorSettingsDialogGeometryMixin
class IndicatorSettingsDialog(
    ContentScrollMixin, NamedItemActionsMixin, QDialog,
    IndicatorSettingsDialogPluginMixin, IndicatorSettingsDialogSchemaMixin,
    IndicatorSettingsDialogUiMixin, IndicatorSettingsDialogSetsMixin,
    IndicatorSettingsDialogRunMixin, IndicatorSettingsDialogPresetsMixin,
    IndicatorSettingsDialogGeometryMixin,
):

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
		# Phase 16.06 (07.08.2026): Fenster-Flags - der '?'-Button (ContextHelp)
		# entfaellt; das Window-X (Schliessen) wird GARANTIERT gesetzt.
		# Empirisch (PySide6/Windows): Ein QDialog mit Parent liefert
		# windowFlags()=Dialog|TitleHint|SystemMenuHint (OHNE CloseButtonHint)
		# und ein OR mit Qt.WindowCloseButtonHint wird von Qt wieder verworfen
		# (bleibt 12291 -> kein X). Einzig das EXPLIZITE Setzen aller Hints
		# setzt das X zuverlaessig (flags=134230019, Close=True). Diese eine
		# zentrale Stelle gilt generisch fuer ALLE Indikator-Prop-Fenster.
		self.setWindowFlags(
			Qt.Dialog
			| Qt.WindowTitleHint
			| Qt.WindowSystemMenuHint
			| Qt.WindowCloseButtonHint
		)

		self.param_controls: Dict[str, QWidget] = {}
		# Phase 13 Schritt 5 Punkt 4: Fenster & Boxen sind vollständig dynamisch –
		# KEINE fixen Pixelwerte für Höhe/Breite. Die Größe ergibt sich allein aus
		# dem Inhalt (setSizeConstraint(SetFixedSize) am Ende von init_ui).
		# Während des UI-Aufbaus wird self.adjustSize() übersprungen.
		self._ui_ready = False
		self.init_ui()

		# Nicht-modaler Dialog: letzte Position/Groesse wiederherstellen
		self._restore_geometry()
