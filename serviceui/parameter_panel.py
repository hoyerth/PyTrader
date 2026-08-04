# serviceui/parameter_panel.py
"""
Service-UI: Parameter-Formular (Phase 15 15.02).

Zeigt die Parameter der aktuell markierten Service-Instanz (lookback +
Plugin-Schema) in einem scrollbaren Formular an (ContentScrollMixin).

Entkoppelt: Das Panel kennt weder Repository noch Datenbank – es bekommt
instance_id, plugin_id und die Konfiguration ueber `set_service()` und
meldet Aenderungen ueber `params_changed(instance_id, params)` zurueck
(Invariante 4: kein SQL in UI; SRP).

Wiederverwendung der Control-Builder aus `ServiceParamColumnsMixin`
(identisches Widget-Verhalten wie die Service-Spalten im Alt-Fenster).
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget,
)

from scrollable_content import ContentScrollMixin
from serviceui.param_columns import ServiceParamColumnsMixin


class ParameterPanel(ContentScrollMixin, ServiceParamColumnsMixin, QWidget):
    """Scrollbares Parameter-Formular fuer eine Service-Instanz."""

    params_changed = Signal(str, dict)  # instance_id, params (partial)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._instance_id: Optional[str] = None
        self._plugin = None
        self._controls: Dict[Any, QWidget] = {}
        # Preisskala-Praezision (fix je Symbol) fuer prox_level1..6
        self._symbol_precision: Optional[int] = None

        self._content = QWidget(self)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(4, 4, 4, 4)
        self._content_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.title_label = QLabel("Kein Service ausgewählt")
        self.title_label.setStyleSheet("font-weight: bold;")
        self._content_layout.addWidget(self.title_label)

        self.form_group = QGroupBox("Parameter")
        self.form_layout = QFormLayout(self.form_group)
        self.form_layout.setAlignment(Qt.AlignTop)
        self._content_layout.addWidget(self.form_group)

        # In den Scroll-Wrapper (behaelt natuerliche Groesse, Scrollbars bei Bedarf)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.install_content_scroll(self._content, parent_layout=outer)

    # -------------------------------------------------------------------------
    # Preisskala-Praezision (ueberschreibt ServiceParamColumnsMixin)
    # -------------------------------------------------------------------------

    def set_symbol_precision(self, precision: int) -> None:
        """Setzt die Preisskala-Praezision des aktiven Symbols (fuer prox_levels)."""
        self._symbol_precision = max(0, int(precision))

    def _get_symbol_precision(self) -> int:
        return self._symbol_precision if self._symbol_precision is not None else 2

    # -------------------------------------------------------------------------
    # Befuellung
    # -------------------------------------------------------------------------

    def set_service(self, instance_id: str, plugin_id: str,
                    config: Optional[Dict[str, Any]]) -> None:
        """Laedt die Parameter einer Service-Instanz ins Formular.

        Args:
            instance_id: instance_id der markierten Instanz ("" -> leeren).
            plugin_id:   Plugin-ID (aus dem Modell/Set).
            config:      Service-Konfiguration {"lookback": int,
                         "params": {...}} oder None (Defaults aus dem Plugin).
        """
        self.clear()
        if not instance_id or not plugin_id:
            self.title_label.setText("Kein Service ausgewählt")
            return

        from analytics.features.feature_builder import PluginRegistry
        try:
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            self.title_label.setText(f"Plugin '{plugin_id}' nicht gefunden")
            return

        self._instance_id = instance_id
        self._plugin = plugin
        self.title_label.setText(f"{instance_id}  [{plugin_id}]")

        config = config or {}
        params = dict(config.get("params") or {})
        lookback = config.get("lookback")

        full_schema: Dict[str, Any] = dict(getattr(plugin, "base_parameter_schema", None) or {})
        full_schema.update(dict(plugin.parameter_schema or {}))
        order = list(getattr(plugin, "parameter_order", None) or (plugin.parameter_schema or {}).keys())
        for key in (getattr(plugin, "base_parameter_schema", None) or {}):
            if key not in order:
                order.append(key)
        labels = dict(getattr(plugin, "param_labels", None) or {})
        for key, spec in (getattr(plugin, "base_parameter_schema", None) or {}).items():
            labels.setdefault(key, spec.get("description") or self._human(key))

        normal_keys = [k for k in order if not full_schema.get(k, {}).get("expert")
                       and not self._is_visual_key(k)]
        expert_keys = [k for k in order if full_schema.get(k, {}).get("expert")]

        for key in normal_keys:
            spec = full_schema.get(key, {})
            cval = params.get(key, spec.get("default"))
            ctrl = self._create_param_control(key, cval, spec)
            self._controls[key] = ctrl
            self._connect_changed(key, ctrl)
            self.form_layout.addRow(labels.get(key, self._human(key)), ctrl)

        if expert_keys:
            exp_grp = QGroupBox("Experten-Optionen")
            exp_grp.setCheckable(True)
            exp_grp.setChecked(False)
            exp_grp.setStyleSheet("")
            ef = QFormLayout(exp_grp)
            for key in expert_keys:
                spec = full_schema.get(key, {})
                if key == "lookback":
                    cval = lookback if lookback is not None else spec.get("default")
                else:
                    cval = params.get(key, spec.get("default"))
                ctrl = self._create_param_control(key, cval, spec)
                self._controls[key] = ctrl
                self._connect_changed(key, ctrl)
                ef.addRow(labels.get(key, self._human(key)), ctrl)
            self._content_layout.addWidget(exp_grp)
            self._setup_collapsible(exp_grp)

        self._reflow()

    def clear(self) -> None:
        """Leert das Formular (naechster set_service() baut es neu auf).

        P15-Bugfix: Die Controls der Form-Zeilen werden EXPLIZIT entfernt
        (setParent(None) + deleteLater) statt nur die Layout-Zeilen zu loesen –
        sonst stapeln sich die unsichtbaren C++-Widgets als Kinder des
        form_group und koennen bei schnellen Klicks Signale auf geloeschte
        Zustände feuern (Memory-Leak + Access-Violation-Kandidat).
        """
        self._instance_id = None
        self._plugin = None
        self._controls = {}
        # Widgets der Form-Zeilen entfernen (FormLayout leeren)
        try:
            while self.form_layout.rowCount():
                item = self.form_layout.takeRow(0)
                # PySide6: TakeRowResult liefert labelItem/fieldItem als
                # Attribute (QWidgetItem), NICHT als Methoden.
                field = item.fieldItem
                if field is not None:
                    w = field.widget()
                    if w is not None:
                        w.setParent(None)
                        w.deleteLater()
                label_item = item.labelItem
                if label_item is not None:
                    w = label_item.widget()
                    if w is not None:
                        w.setParent(None)
                        w.deleteLater()
        except (RuntimeError, AttributeError):
            pass
        # Experten-Gruppe (falls vorhanden) entfernen
        try:
            for child in list(self._content.findChildren(QGroupBox)):
                if child is not self.form_group:
                    child.setParent(None)
                    child.deleteLater()
        except (RuntimeError, AttributeError):
            pass
        self._reflow()

    # -------------------------------------------------------------------------
    # Auslesen & Aenderungs-Signal
    # -------------------------------------------------------------------------

    def current_instance_id(self) -> Optional[str]:
        return self._instance_id

    def collect_params(self) -> Dict[str, Any]:
        """Liefert die aktuellen Parameterwerte des Formulars."""
        return {key: self._ctrl_value(ctrl) for key, ctrl in self._controls.items()}

    def _connect_changed(self, key: str, ctrl: QWidget) -> None:
        """Verdrahtet das Aenderungs-Signal des Controls auf params_changed."""
        if isinstance(ctrl, (QGroupBox,)):
            return
        signal = getattr(ctrl, "valueChanged", None)
        if signal is None:
            signal = getattr(ctrl, "textChanged", None)
        if signal is None:
            signal = getattr(ctrl, "toggled", None)
        if signal is None:
            signal = getattr(ctrl, "currentTextChanged", None)
        if signal is None:
            return
        signal.connect(lambda _v, k=key: self._emit_params_changed(k))

    def _emit_params_changed(self, _key: str) -> None:
        """P15-Bugfix: try/except – das Panel kann zwischen Signal und Aufruf
        zerstoert/gecleart worden sein (Access-Violation-Schutz)."""
        try:
            if self._instance_id is not None:
                self.params_changed.emit(self._instance_id, self.collect_params())
        except (RuntimeError, AttributeError):
            pass

    def _reflow(self) -> None:
        """Passt die Groesse an den Inhalt an (deferred, ContentScrollMixin)."""
        try:
            if hasattr(self, "_schedule_reflow"):
                self._schedule_reflow()
        except (RuntimeError, AttributeError):
            pass
