# serviceui/param_columns.py
"""
Service-UI: Parameter-Column-Builder (dynamische Service-Spalten).

Phase 15, Kapitel 15.1 (U15-D1): Aus service_win.py ausgelagert –
Verhalten unverändert. Als Mixin, damit die Host-Klasse (ServiceWindow)
weiterhin direkt `self._build_service_columns(...)` etc. aufrufen kann.

Die Methoden greifen auf Host-Attribute zurück, die zur Laufzeit vorhanden
sind: service_columns_layout, _service_param_controls, _service_desc_controls,
top_row, widget_service_columns, combo_symbol, combo_tf_set, _symbol_precision,
list_execution_order, collect_set_definition(), _schedule_reflow (ContentScrollMixin),
_service_lock/_build_tooltip (ServiceWindow).
"""

from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout,
    QWidget,
)


class ServiceParamColumnsMixin:
    """Baut die dynamischen Service-Spalten (Roadmap 5.4.2.2).

    Für jede instance_id in execution_order wird eine QGroupBox-Spalte im
    service_columns_layout erzeugt. Jede Spalte skaliert in der Höhe exakt
    mit der Anzahl ihrer Parameter (QSizePolicy.Maximum); die Fensterbreite
    wächst mit der Anzahl der Spalten nach rechts – ohne leeren Raum und
    ohne fixe Pixelwerte.
    """

    @staticmethod
    def _is_visual_key(key: str) -> bool:
        """Konvention für reine Darstellungs-Props: Sichtbarkeit (show_*) + Farben (color).

        Darstellungs-Parameter gehören NICHT ins Service-Set (nur Berechnungs-
        Logik, Roadmap 5.4.1.2) und werden daher in den Service-Spalten
        ausgeblendet (konsistent zum Indikator-Dialog).
        """
        if key.startswith("show_"):
            return True
        if "color" in key.lower():
            return True
        return False

    @staticmethod
    def _human(key: str) -> str:
        return key.replace("_", " ").title()

    @staticmethod
    def _decimal_places(value: Any) -> int:
        """Nachkommastellen eines float (für QDoubleSpinBox.setDecimals)."""
        if not isinstance(value, float) or value != value:  # NaN-Schutz
            return 4
        s = f"{value:.10f}".rstrip("0")
        if "." in s:
            return len(s.split(".")[1])
        return 0

    def _get_symbol_precision(self) -> int:
        """USER-REQ: Preisskala-Praezision (fix je Symbol) fuer die 6
        Custom-Level-Eingabefelder. Lazy ermittelt (db_service.get_symbol_
        precision) und fuer die Fenster-Instanz gecacht – kein DB-Zugriff
        bei jedem Spalten-Neuaufbau."""
        if self._symbol_precision is None:
            try:
                from db_service import get_symbol_precision
                symbol = (self.combo_symbol.currentText()
                          if self.combo_symbol else "SILVER")
                timeframe = (self.combo_tf_set.currentText()
                             if self.combo_tf_set else "H1")
                self._symbol_precision = get_symbol_precision(symbol, timeframe)
            except Exception:
                self._symbol_precision = 2
        return self._symbol_precision

    def _create_param_control(self, key: str, val: Any, spec: Dict[str, Any]) -> QWidget:
        """Erzeugt ein Eingabe-Widget exakt aus dem ParameterSchema.

        float -> QDoubleSpinBox, int -> QSpinBox, bool -> QCheckBox,
        choice -> QComboBox, color/str -> QLineEdit. min/max/step werden 1:1
        übertragen (Roadmap 5.4.2.2).
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
            return spin
        if p_type == "int":
            spin = QSpinBox()
            spin.setRange(int(spec.get("min", -100000)), int(spec.get("max", 100000)))
            spin.setSingleStep(int(spec.get("step", 1)))
            try:
                spin.setValue(int(val))
            except (TypeError, ValueError):
                spin.setValue(int(spec.get("default", 0)))
            return spin
        if p_type == "bool":
            chk = QCheckBox()
            chk.setChecked(bool(val))
            return chk
        if p_type == "choice":
            combo = QComboBox()
            combo.addItems([str(o) for o in (spec.get("options") or [])])
            combo.setCurrentText(str(val))
            return combo
        txt = QLineEdit()
        txt.setText(str(val))
        return txt

    @staticmethod
    def _ctrl_value(ctrl: QWidget) -> Any:
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

    def _setup_collapsible(self, group: QGroupBox) -> None:
        """Macht eine ausklappbare QGroupBox wirklich kollabierbar.

        Beim Abwählen werden die Kinder ausgeblendet und die Fensterhöhe per
        _reflow() nahtlos verkleinert (Roadmap 5.4.2.2: Ein-/Ausklappen
        verändert die Höhe dynamisch). Zusätzlich wird group.updateGeometry()
        gerufen, damit der gecachte QWidgetItemV2-sizeHint der Box invalidiert
        wird (Qt 6.11: Layouts refreshen diesen Cache sonst NICHT).
        """
        def _toggle(checked: bool) -> None:
            for child in group.findChildren(QWidget):
                child.setVisible(checked)
            group.updateGeometry()  # QWidgetItemV2-Cache invalidieren (s. oben)
            self._reflow()
        group.toggled.connect(_toggle)
        _toggle(group.isChecked())

    def _reflow(self) -> None:
        """Erzwingt die Neuberechnung der Layouts (dynamische Höhe/Breite).

        Qt 6.11: QWidgetItemV2 cached den sizeHint eines Widgets beim ersten
        Zugriff und aktualisiert ihn NICHT, wenn der Inhalt später wächst –
        selbst layout.invalidate() hilft nicht. Daher werden die Caches der
        betroffenen Widgets explizit per updateGeometry() invalidiert
        (invalidateSizeCache) und die Layout-Caches geleert.

        WICHTIG: Die Fenstergröße wird DEFERRED (nächste Event-Loop-Runde)
        angepasst. Beim Set-Wechsel sind die alten Service-Spalten per
        deleteLater() noch im Widget-Baum; bis sie zerstört sind, melden die
        Layout-Caches einen veralteten (zu kleinen) sizeHint (z.B. 18x18 für
        eine volle Spalten-Zeile). Ein synchrones resize würde das Fenster
        daher fälschlich schrumpfen. _schedule_reflow() zerstört die
        deleteLater-Widgets und berechnet die Größe erst aus dem konsistenten
        Zustand (ContentScrollMixin).
        """
        self._schedule_reflow()

    def _clear_service_columns(self) -> None:
        """Entfernt alle Service-Spalten aus dem service_columns_layout."""
        if self.service_columns_layout is None:
            return
        while self.service_columns_layout.count():
            item = self.service_columns_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._service_param_controls = {}
        self._service_desc_controls = {}

    def _build_service_columns(self, set_definition: Dict[str, Any]) -> None:
        """Baut die dynamischen Service-Spalten (Roadmap 5.4.2.2).

        Für jede instance_id in execution_order wird eine QGroupBox-Spalte im
        service_columns_layout erzeugt. Jede Spalte skaliert in der Höhe exakt
        mit der Anzahl ihrer Parameter (QSizePolicy.Maximum); die Fensterbreite
        wächst mit der Anzahl der Spalten nach rechts – ohne leeren Raum und
        ohne fixe Pixelwerte.
        """
        if self.service_columns_layout is None:
            return
        self._clear_service_columns()
        services = set_definition.get("services") or {}
        for iid in (set_definition.get("execution_order") or []):
            cfg = services.get(iid) or {}
            pid = cfg.get("plugin_id") or iid
            col = self._build_service_column(iid, pid, cfg)
            self.service_columns_layout.addWidget(col)
        # Container erneut in die obere Zeile einfügen: Das QWidgetItem
        # eines Widgets meldet dessen Größe zum Zeitpunkt des Einfügens und
        # aktualisiert sich bei späterem Inhalts-Wachstum nicht (Qt-Quirk).
        # Entfernen + erneutes Einfügen erzeugt ein frisches QWidgetItem mit
        # der aktuellen Größe.
        if self.top_row is not None and self.widget_service_columns is not None:
            self.top_row.removeWidget(self.widget_service_columns)
            self.top_row.addWidget(self.widget_service_columns)
        self._reflow()

    def _build_service_column(self, iid: str, pid: str, cfg: Dict[str, Any]) -> QGroupBox:
        """Erzeugt EINE Service-Spalte (QGroupBox) mit Parameter-Formular.

        - Normale Parameter im QFormLayout (float/int/bool nach Schema).
        - expert: True (inkl. lookback) in einer einklappbaren
          QGroupBox 'Experten-Optionen' am Spaltenfuß.

        P14-04-E: Spaltentitel trägt die 🔒-Kennzeichnung, wenn der Service in
        einem gespeicherten Service-Set vorkommt (Sperre sichtbar).
        """
        prefix, _ = self._service_lock(pid)
        col = QGroupBox(f"{prefix}{iid}  [{pid}]")
        # 5.4.2.2 Punkt 3: Spalte skaliert in der Höhe exakt mit ihrem Inhalt
        # (endet unter dem letzten Parameter), wächst beim Vergrößern des
        # Fensters NICHT mit.
        col.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        vl = QVBoxLayout(col)
        vl.setAlignment(Qt.AlignTop)

        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(pid)
        except KeyError:
            vl.addWidget(QLabel(f"Plugin '{pid}' nicht gefunden."))
            return col

        full_schema: Dict[str, Any] = dict(getattr(plugin, "base_parameter_schema", None) or {})
        full_schema.update(dict(plugin.parameter_schema or {}))
        order = list(getattr(plugin, "parameter_order", None) or (plugin.parameter_schema or {}).keys())
        for key in (getattr(plugin, "base_parameter_schema", None) or {}):
            if key not in order:
                order.append(key)
        labels = dict(getattr(plugin, "param_labels", None) or {})
        for key, spec in (getattr(plugin, "base_parameter_schema", None) or {}).items():
            labels.setdefault(key, spec.get("description") or self._human(key))

        params = dict(cfg.get("params") or {})
        lookback = cfg.get("lookback")

        # Phase 14 P14-01: Individuelle Instanz-Beschreibung (bearbeitbar) –
        # wird in ServiceInstanceConfig.description gespeichert und in
        # Tooltip + Info-Dialog angezeigt.
        # Phase 16 (05.08.2026): Stift-Button (✏️) neben dem Beschreibungsfeld
        # oeffnet den modalen ServiceDescriptionEditDialog (mehrzeiliger
        # QTextEdit); [Speichern] persistiert via Repo + EventBus. Die
        # QLineEdit bleibt als schnelles Einzeilen-Feld erhalten.
        desc_row = QHBoxLayout()
        desc_label = QLabel("Beschreibung:")
        desc_edit = QLineEdit()
        desc_edit.setPlaceholderText("Individuelle Anmerkung für diese Instanz (optional)")
        desc_edit.setText(str(cfg.get("description") or ""))
        self._service_desc_controls[iid] = desc_edit
        desc_edit.textChanged.connect(lambda _t, iid=iid: self._update_service_tooltip(iid))
        desc_row.addWidget(desc_label)
        desc_row.addWidget(desc_edit)
        desc_edit_btn = QPushButton("✏️")
        desc_edit_btn.setObjectName("btn_desc_edit")
        desc_edit_btn.setToolTip(
            "Beschreibung bearbeiten – öffnet den mehrzeiligen Editor")
        desc_edit_btn.setFixedWidth(32)
        desc_edit_btn.setCursor(Qt.PointingHandCursor)
        desc_edit_btn.clicked.connect(
            lambda _=False, iid=iid: self._open_service_desc_editor(iid))
        desc_row.addWidget(desc_edit_btn)
        vl.addLayout(desc_row)

        # Normale (Nicht-Expert-, Nicht-Darstellungs-)Parameter
        form = QFormLayout()
        for key in order:
            spec = full_schema.get(key, {})
            if spec.get("expert") or self._is_visual_key(key):
                continue
            cval = params.get(key, spec.get("default"))
            # USER-REQ: P14-01 Nachtrag - Alt-Sets speichern die 6 Custom-Levels
            # als Aggregat custom_levels (Liste/String) statt als Einzelparameter
            # prox_level1..6 - leere Level-Felder werden daraus vorbefüllt.
            if key.startswith("prox_level") and not cval:
                try:
                    from analytics.features.definitions.grid_lines_service import map_custom_levels_to_prox_levels
                    cval = map_custom_levels_to_prox_levels(params).get(key, cval)
                except Exception:
                    pass
            ctrl = self._create_param_control(key, cval, spec)
            self._service_param_controls[(iid, key)] = ctrl
            form.addRow(labels.get(key, self._human(key)), ctrl)
        vl.addLayout(form)

        # Expert-Parameter (inkl. lookback als Service-Instanz-Einstellung)
        expert_keys = [k for k in order if full_schema.get(k, {}).get("expert")]
        if expert_keys:
            exp_grp = QGroupBox("Experten-Optionen")
            exp_grp.setCheckable(True)
            exp_grp.setChecked(False)
            exp_grp.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            ef = QFormLayout(exp_grp)
            for key in expert_keys:
                spec = full_schema.get(key, {})
                if key == "lookback":
                    cval = lookback if lookback is not None else spec.get("default")
                else:
                    cval = params.get(key, spec.get("default"))
                ctrl = self._create_param_control(key, cval, spec)
                self._service_param_controls[(iid, key)] = ctrl
                ef.addRow(labels.get(key, self._human(key)), ctrl)
            vl.addWidget(exp_grp)
            self._setup_collapsible(exp_grp)

        return col

    def _rebuild_columns(self) -> None:
        """Baut die Service-Spalten aus dem aktuellen Editor-Zustand neu."""
        if self.service_columns_layout is None:
            return
        definition = self.collect_set_definition()
        self._build_service_columns(definition)

    def _update_service_tooltip(self, iid: str) -> None:
        """Aktualisiert den Tooltip des Listen-Items live beim Tippen."""
        if not self.list_execution_order:
            return
        for i in range(self.list_execution_order.count()):
            item = self.list_execution_order.item(i)
            if item.data(Qt.UserRole) == iid:
                cfg: Dict[str, Any] = {"plugin_id": item.data(Qt.UserRole + 1) or iid}
                desc_ctrl = self._service_desc_controls.get(iid)
                if desc_ctrl is not None:
                    cfg["description"] = desc_ctrl.text().strip()
                # P14-04-E: Sperr-Nachtrag (🔒) beibehalten – der Live-Tooltip
                # darf die Sperr-Kennzeichnung nicht überschreiben.
                _prefix, lock_tip = self._service_lock(str(cfg.get("plugin_id") or ""))
                item.setToolTip(self._build_tooltip(iid, cfg) + lock_tip)
                break
