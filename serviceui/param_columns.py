# serviceui/param_columns.py
"""
Service-UI: Parameter-Column-Builder (dynamische Service-Spalten).

Phase 15, Kapitel 15.1 (U15-D1): Aus service_win.py ausgelagert –
Verhalten unverändert. Als Mixin, damit die Host-Klasse (ServiceWindow)
weiterhin direkt `self._build_service_columns(...)` etc. aufrufen kann.

Die Methoden greifen auf Host-Attribute zurück, die zur Laufzeit vorhanden
sind: service_columns_layout, _service_param_controls, _service_desc_controls,
widget_service_columns, combo_symbol, combo_tf, _symbol_precision,
collect_set_definition(), _schedule_reflow (ContentScrollMixin),
_service_lock/_build_tooltip (ServiceWindow).
"""

from typing import Any, Dict

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtGui import QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSizePolicy, QSpinBox, QTextEdit,
    QVBoxLayout, QWidget,
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
                timeframe = (self.combo_tf.currentText()
                             if self.combo_tf else "H1")
                self._symbol_precision = get_symbol_precision(symbol, timeframe)
            except Exception:
                self._symbol_precision = 2
        return self._symbol_precision

    def _create_param_control(self, key: str, val: Any, spec: Dict[str, Any]) -> QWidget:
        """Erzeugt ein Eingabe-Widget exakt aus dem ParameterSchema.

        float -> QDoubleSpinBox, int -> QSpinBox, bool -> QCheckBox,
        choice -> QComboBox, color/str -> QLineEdit. min/max/step werden 1:1
        übertragen (Roadmap 5.4.2.2).

        17.01.05 (Bugfix, UI-Dropdown-Extension): Deklariert der Schema-
        Eintrag `options` (Liste/Tupel), wird VOR der Datentyp-Prüfung eine
        QComboBox gerendert – unabhängig vom type-Wert ("str"/"choice").
        Dadurch werden z. B. die mode-/ma_type-/period_extrema_type-Felder
        der Swing-Services (type="str" + options) als Dropdown statt als
        QLineEdit angezeigt.
        """
        options = spec.get("options")
        if options and isinstance(options, (list, tuple)):
            combo = QComboBox()
            combo.addItems([str(o) for o in options])
            val_str = str(val if val is not None else spec.get("default", ""))
            idx = combo.findText(val_str)
            if idx >= 0:
                combo.setCurrentIndex(idx)
            return combo
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

    @staticmethod
    def _scroll_textedit_top(editor: QTextEdit) -> None:
        """Scrollt eine Read-Only-QTextEdit HART nach oben (Cursor + Scroll).

        Qt setzt nach `setHtml` den Text-Cursor intern ans Dokument-ENDE und
        scrollt beim finalen Layout dorthin – dadurch ist die erste Zeile
        verdeckt. Fix (17.01.06):
          1. Cursor ans Dokument-Anfang (`QTextCursor.MoveOperation.Start`).
          2. Vertikalen Scrollbalken erst auf Maximum setzen (erzwingt die
             Neuberechnung des Viewports) und dann auf 0 (ganz oben).
        Wirkt nur dauerhaft, wenn es NACH dem endgueltigen Layout/Resize
        ausgefuehrt wird (Qt wrappt das Dokument nach setHtml erst in einer
        spaeteren Event-Loop-Runde um und scrollt dann ggf. erneut).
        """
        if editor is None:
            return
        try:
            cur = editor.textCursor()
            cur.setPosition(0)
            editor.setTextCursor(cur)
            editor.moveCursor(QTextCursor.MoveOperation.Start)
            sb = editor.verticalScrollBar()
            if sb is not None:
                sb.setValue(sb.maximum())  # unten -> Viewport neu berechnen
                sb.setValue(0)             # ganz nach oben (erste Zeile)
            editor.ensureCursorVisible()
        except (RuntimeError, AttributeError):
            pass  # Widget bereits zerstoert (deleteLater) – ignorieren

    # ------------------------------------------------------------------
    # 17.01.05 (Bugfix): Conditional Visibility (Modus-abhaengige Parameter)
    # ------------------------------------------------------------------
    def _apply_conditional_visibility(self, iid: str) -> None:
        """Blendet Parameter mit `visible_when`-Schema-Deklaration ein/aus.

        Konvention (additiv, 17.01.05): Ein Parameter-Schema-Eintrag kann
        zusaetzlich tragen:
            "visible_when": {"mode": ["Algo_A", "Algo_B"]}
        (auch einzelner String erlaubt). Liegt der aktuelle Wert des
        `mode`-Controls (Dropdown) NICHT in der Liste, werden Control + Label
        ausgeblendet; sonst eingeblendet. Parameter ohne `visible_when`
        bleiben immer sichtbar. Wird beim Spaltenaufbau und bei jedem
        Mode-Wechsel aufgerufen.
        """
        schema = getattr(self, "_mode_schemas", {}).get(iid)
        if not schema:
            return
        mode_ctrl = self._service_param_controls.get((iid, "mode"))
        mode_val = (str(self._ctrl_value(mode_ctrl))
                    if mode_ctrl is not None else "")
        for key, spec in schema.items():
            vw = spec.get("visible_when")
            if not isinstance(vw, dict) or "mode" not in vw:
                continue
            allowed = vw["mode"]
            if isinstance(allowed, str):
                allowed = [allowed]
            visible = mode_val in {str(a) for a in allowed}
            ctrl = self._service_param_controls.get((iid, key))
            if ctrl is None:
                continue
            try:
                ctrl.setVisible(visible)
            except (RuntimeError, AttributeError):
                pass
            lbl = getattr(self, "_service_param_labels", {}).get((iid, key))
            if lbl is not None:
                try:
                    lbl.setVisible(visible)
                except (RuntimeError, AttributeError):
                    pass
        # 17.01.05 (Bugfix): Auch das Info-Label (Service-/Algo-Beschreibung)
        # auf den aktuellen Modus aktualisieren.
        self._update_service_info_label(iid)

    # ------------------------------------------------------------------
    # 17.01.05 (Bugfix): Read-only Info-Label unter dem individuellen
    # Beschreibungsfeld – zeigt die in der Definition vorgefuellte
    # Service-Beschreibung + die Beschreibung des aktuell gewaehlten
    # Algorithmus (mode) an. Wird beim Spaltenaufbau und bei jedem
    # Mode-Wechsel aktualisiert.
    # ------------------------------------------------------------------
    def _update_service_info_label(self, iid: str) -> None:
        """Setzt den Rich-Text des Info-Labels fuer eine Service-Instanz.

        Angezeigt werden (read-only, unter dem editierbaren Beschreibungs-
        Feld): display_name/plugin_id, die Service-Beschreibung aus den
        Plugin-Metadaten (description_long, sonst description) sowie der
        aktuell gewaehlte Algorithmus (mode) inkl. Schema-Beschreibung.
        """
        label = getattr(self, "_service_info_labels", {}).get(iid)
        if label is None:
            return
        pid = getattr(self, "_service_info_pids", {}).get(iid, iid)
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(pid)
        except (KeyError, AttributeError):
            plugin = None
        meta = dict(getattr(plugin, "metadata", None) or {})
        display = str(meta.get("display_name") or pid)
        desc = str(meta.get("description_long")
                   or meta.get("description") or "").strip()
        schema = getattr(self, "_mode_schemas", {}).get(iid, {})
        mode_spec = schema.get("mode", {}) if isinstance(schema, dict) else {}
        mode_ctrl = self._service_param_controls.get((iid, "mode"))
        mode_val = (str(self._ctrl_value(mode_ctrl)) if mode_ctrl is not None
                    else str(mode_spec.get("default") or ""))
        labels = dict(getattr(plugin, "param_labels", None) or {})
        mode_label = str(labels.get("mode")
                         or mode_spec.get("description") or "Algorithmus")
        mode_desc = str(mode_spec.get("description") or "")

        import html as _html
        parts = [f"<b>{_html.escape(display)}</b>"]
        if desc:
            parts.append(_html.escape(desc))
        if mode_val:
            parts.append(f"<b>{_html.escape(mode_label)}:</b> "
                         f"{_html.escape(mode_val)}")
        if mode_desc and mode_desc != mode_label:
            parts.append(f"<i>{_html.escape(mode_desc)}</i>")
        try:
            # QTextEdit (read-only): HTML setzen – bei langem Text scrollt
            # die Anzeige vertikal (max. Hoehe gedeckelt).
            label.setHtml("<br>".join(parts))
            # 17.01.06 (Bugfix): Nach dem Text-Update die Anzeige IMMER ganz
            # nach oben scrollen (Cursor->Start + Scrollbar->0). Synchrone
            # Ausfuehrung + DEFERRED (QTimer singleShot 0): Qt setzt nach
            # setHtml den Cursor ans Dokument-Ende und wrappt das Dokument
            # erst in einer spaeteren Event-Loop-Runde um (dann scrollt es
            # ggf. erneut zum Cursor). Der deferred Reset wirkt daher erst
            # nach dem finalen Layout; zusaetzlich wird der Reset nach dem
            # finalen Box-Resize in _resize_param_box_deferred ausgefuehrt.
            self._scroll_textedit_top(label)
            QTimer.singleShot(
                0, lambda l=label: self._scroll_textedit_top(l))
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # Phase 15 (Dirty-State): Aenderungs-Tracking der Parameter-Controls
    # ------------------------------------------------------------------
    def _connect_param_change(self, ctrl: QWidget, iid: str, key: str) -> None:
        """Verbindet das Aenderungs-Signal eines Parameter-Controls mit dem
        Dirty-State-Tracking (valueChanged/textChanged/toggled).

        Jede Aenderung aktualisiert die ServiceSetDefinition im RAM
        (_current_set_definition) und markiert die instance_id im MasterTree
        als ungespeichert ('*' am Service-Knoten).
        """
        if isinstance(ctrl, QCheckBox):
            ctrl.toggled.connect(
                lambda _v, i=iid, k=key: self._on_param_changed(i, k))
        elif isinstance(ctrl, (QSpinBox, QDoubleSpinBox)):
            ctrl.valueChanged.connect(
                lambda _v, i=iid, k=key: self._on_param_changed(i, k))
        elif isinstance(ctrl, QComboBox):
            ctrl.currentTextChanged.connect(
                lambda _v, i=iid, k=key: self._on_param_changed(i, k))
        else:  # QLineEdit (color/str)
            ctrl.textChanged.connect(
                lambda _t, i=iid, k=key: self._on_param_changed(i, k))

    def _on_param_changed(self, iid: str, key: str) -> None:
        """Aktualisiert die RAM-ServiceSetDefinition und markiert die
        Instanz als dirty ('*' im MasterTree)."""
        ctrl = self._service_param_controls.get((iid, key))
        if ctrl is None:
            return
        value = self._ctrl_value(ctrl)
        # RAM-Definition der geladenen ServiceSetDefinition aktualisieren
        # (lookback ist eine Instanz-Einstellung, alle anderen gehoeren in
        # params; Phase 15 Dirty-State).
        definition = getattr(self, "_current_set_definition", None)
        if definition is not None:
            cfg = (definition.get("services") or {}).get(iid)
            if isinstance(cfg, dict):
                if key == "lookback":
                    cfg["lookback"] = value
                else:
                    cfg.setdefault("params", {})[key] = value
        self._mark_service_dirty(iid)

    def _mark_service_dirty(self, iid: str) -> None:
        """Versieht den Service-Knoten im MasterTree mit einem '*' (und
        merkt den Dirty-Zustand fuer Baum-Neuaufbauten).

        Bugfix 05.08.2026 (Punkt 2): Blendet zusaetzlich die Speicher-
        Buttons der Parameter-Spalte ein (_set_param_actions_visible im
        Orchestrator) - eine manuelle Parameter-Aenderung macht das
        Speichern erst noetig/sichtbar.
        """
        try:
            self._set_param_actions_visible(True)
        except (RuntimeError, AttributeError):
            pass
        selector = getattr(self, "service_selector", None)
        tree = getattr(selector, "master_tree", None)
        if tree is None or not iid:
            return
        try:
            tree.set_instance_dirty(iid, True)
        except (RuntimeError, AttributeError):
            pass

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

        Zusatz (Layout-Runde 2, 05.08.2026): Die Service-Parameter-Box liegt
        in einer ContentScrollArea mit widgetResizable=False – die ScrollArea
        resizet das Widget NICHT automatisch. Die Box wird daher DEFERRED
        (nach dem Zerstören der deleteLater-Altspalten) auf ihre aktuelle
        Layout-Größe gesetzt, damit die ScrollArea Scrollbalken anzeigen
        kann, sobald die Box das max. Format übersteigt (Punkt 5).
        """
        self._schedule_reflow()
        QTimer.singleShot(0, self._resize_param_box_deferred)

    def _resize_param_box_deferred(self) -> None:
        """Setzt die Service-Parameter-Box (in der ContentScrollArea) DEFERRED
        auf ihre aktuelle Layout-Größe.

        Muss NACH dem Zerstören der per deleteLater() markierten Alt-Spalten
        laufen – ein synchrones resize in _reflow() würde den veralteten
        QWidgetItemV2-sizeHint (18x18 für ein gerade geleertes Layout) lesen
        und die Box auf 18x18 schrumpfen (Bugfix 05.08.2026, Punkt 5).
        """
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        except (RuntimeError, AttributeError):
            pass
        box = getattr(self, "widget_service_columns", None)
        if box is None or box.layout() is None:
            return
        try:
            box.updateGeometry()
            box.resize(box.layout().sizeHint())
            scroll = getattr(self, "_param_scroll", None)
            if scroll is not None:
                scroll.updateGeometry()
            # Bugfix 05.08.2026 (Punkt 1): Der QSplitter fixiert die
            # Spaltengroessen beim addWidget (VOR dem Spaltenaufbau) und
            # aktualisiert sie nicht, wenn die sizeHints danach wachsen
            # (Qt-Quirk, analog QWidgetItemV2). Nach dem Spaltenaufbau wird
            # die Param-Spalte auf ihre aktuelle Layout-Breite gesetzt, damit
            # 2 Services nebeneinander ohne horizontalen Scroll passen.
            splitter = getattr(self, "main_splitter", None)
            # 05.08.2026 (Layout-Runde 3): ZWEI-SPALTEN-Splitter seit der
            # Phase-13-Bereinigung – der deferred setSizes greift erst mit
            # count() == 2 (vorher 3 -> stale Spaltengroessen nach dem
            # Spaltenaufbau, Bugfix Punkt 1).
            if splitter is not None and splitter.count() == 2:
                hints = []
                for i in range(splitter.count()):
                    w = splitter.widget(i)
                    if w is not None:
                        hints.append(w.sizeHint().width())
                if hints:
                    splitter.setSizes(hints)
        except (RuntimeError, AttributeError):
            pass
        # 17.01.06 (Bugfix): Nach dem FINALEN Box-Resize (DeferredDelete +
        # box.resize) alle Read-only-Info-Anzeigen wieder ganz nach oben
        # scrollen. Durch das Resize wrappt das Dokument der QTextEdit um;
        # Qt scrollt dabei (weil der Cursor von setHtml intern am Dokument-
        # Ende stand) um einige Zeilen nach unten – die erste Zeile waere
        # sonst verdeckt. Dieser Aufruf laeuft NACH dem Layout, sodass die
        # Scroll-Position oben haelt.
        for _info in list(
                getattr(self, "_service_info_labels", {}).values()):
            self._scroll_textedit_top(_info)

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
        # 17.01.05 (Bugfix): Conditional-Visibility-Zustand je Instanz
        # (Modus-abhaengige Parameter-Ein-/Ausblendung) zuruecksetzen.
        self._mode_schemas = {}
        self._service_param_labels = {}
        # 17.01.05 (Bugfix): Read-only Info-Label (vorgefuellte Service-/Algo-
        # Beschreibung) je Instanz zuruecksetzen.
        self._service_info_labels = {}
        self._service_info_pids = {}

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
        # Bugfix 05.08.2026 (Layout-Runde 2): Die Service-Parameter-Box
        # (widget_service_columns) liegt seit dem ZWEI-SPALTEN-Splitter FEST in
        # einer ContentScrollArea (_param_scroll, rechte Splitter-Spalte, max.
        # Hoehe/Breite mit Scrollbalken - Punkt 5). KEIN Reinsert mehr noetig
        # (der fruehere Reinsert stammte aus dem Alt-Layout und verschob die
        # Box aus dem Editor-Panel). Der Qt-6.11-QWidgetItemV2-Cache wird ueber
        # updateGeometry() invalidiert, damit die ScrollArea/der Splitter die
        # aktuelle Spaltenbreite/-hoehe live uebernehmen (vgl. _reflow).
        if self.widget_service_columns is not None:
            self.widget_service_columns.updateGeometry()
        scroll = getattr(self, "_param_scroll", None)
        if scroll is not None:
            scroll.updateGeometry()
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
        # 17.01.05 (Bugfix): Conditional Visibility – Schema je Instanz merken,
        # um Parameter mit "visible_when"-Deklaration modus-abhaengig
        # ein-/auszublenden (_apply_conditional_visibility).
        self._mode_schemas[iid] = full_schema
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
        # Phase 15 (Dirty-State): auch die Instanz-Beschreibung ist Teil des
        # Sets und wird erst beim Set-Speichern persistiert -> dirty markieren.
        desc_edit.textChanged.connect(lambda _t, iid=iid: self._mark_service_dirty(iid))
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

        # 17.01.05 (Bugfix): Read-only Info-Anzeige unter dem individuellen
        # Beschreibungsfeld – zeigt die in der Definition vorgefuellte
        # Service-Beschreibung + die Beschreibung des aktuell gewaehlten
        # Algorithmus (mode). Rein informativ (kein Input), wird beim
        # Mode-Wechsel live aktualisiert (_update_service_info_label).
        # Ergaenzung: Als QTextEdit (read-only) mit gedeckelter Hoehe – wird
        # der Text zu lang, erscheint eine vertikale Scrollbar (kein
        # Aufblahen der Spalte).
        info_label = QTextEdit()
        info_label.setReadOnly(True)
        info_label.setAcceptRichText(True)
        info_label.setFrameShape(QTextEdit.NoFrame)
        info_label.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        info_label.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        info_label.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        info_label.setTabChangesFocus(True)
        info_label.setStyleSheet(
            "QTextEdit { background: transparent; border: none; "
            "color: #666; font-size: 11px; }")
        info_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        # Deckelhoehe: ~3 Textzeilen – darueber scrollt der Text vertikal.
        fm = info_label.fontMetrics()
        info_label.setMaximumHeight(fm.lineSpacing() * 3 + 12)
        self._service_info_labels[iid] = info_label
        self._service_info_pids[iid] = pid
        vl.addWidget(info_label)

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
                    from analytics.features.definitions.srv_grid_lines import map_custom_levels_to_prox_levels
                    cval = map_custom_levels_to_prox_levels(params).get(key, cval)
                except Exception:
                    pass
            ctrl = self._create_param_control(key, cval, spec)
            self._service_param_controls[(iid, key)] = ctrl
            # Phase 15 (Dirty-State): Aenderungen markieren die Instanz.
            self._connect_param_change(ctrl, iid, key)
            form.addRow(labels.get(key, self._human(key)), ctrl)
            # 17.01.05 (Bugfix): Label-Referenz fuer die modus-abhaengige
            # Ein-/Ausblendung merken.
            lbl = form.labelForField(ctrl)
            if lbl is not None:
                self._service_param_labels[(iid, key)] = lbl
            # 17.01.05 (Bugfix): Mode-Wechsel (Dropdown) blendet die
            # modus-spezifischen Parameter passend ein/aus.
            if key == "mode" and isinstance(ctrl, QComboBox):
                ctrl.currentTextChanged.connect(
                    lambda _v, i=iid: self._apply_conditional_visibility(i))
        vl.addLayout(form)
        # 17.01.05 (Bugfix): Initialzustand der Modus-Sichtbarkeit anwenden
        # (ein geladenes Set kann einen nicht-Default-Mode besitzen).
        self._apply_conditional_visibility(iid)

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
                # Phase 15 (Dirty-State): Aenderungen markieren die Instanz.
                self._connect_param_change(ctrl, iid, key)
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

