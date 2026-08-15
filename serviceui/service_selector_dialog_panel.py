"""
service_selector_dialog_panel.py - Param-Panel-Aufbau, Panel-Groesse, Splitter, Geometrie-Restore, done

23.08 God-File-Split (15.08.2026): Aus serviceui/service_selector_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der ServiceSelectorDialog-
Klasse als Mixin (Klasse ServiceSelectorDialogPanelMixin).
"""

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QTimer,
)

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
)

from serviceui.master_tree import (
    TYPE_SERVICE,
)

from serviceui.service_selector_dialog_constants import (
    DIALOG_GEOMETRY_KEY,
    PANEL_BUFFER,
)

class ServiceSelectorDialogPanelMixin:

    def _rebuild_param_panel(
        self,
        entries: Optional[List[Dict[str, str]]] = None,
        editable_plugin: Optional[str] = None,
    ) -> None:
        """Baut das rechte Parameter-Panel aus den uebergebenen Entries neu.

        Bugfix-Runde 3 (06.08.2026): Die Entries kommen aus `_entries_for_scope`
        (GEKLICKTE Zeile, service_win-Muster) – NICHT mehr aus
        `tree.checked_services()` (Checkboxen). Fuer jeden Eintrag wird eine
        QGroupBox-Spalte ueber `ServiceParamColumnsMixin._build_service_column()`
        erzeugt (seit 06.08.2026 HORIZONTAL nebeneinander, Punkt 1):
          * Set-Service:  cfg aus der Set-Definition (instance_id + params)
          * Plugin-Zeile: cfg aus `_plugin_config(pid)` (Schema-Defaults +
            gespeicherte plugin_params_<id>)
        18.01.01 (E-4): Standalone-Services (editable_plugin gesetzt) sind
        EDITIERBAR (Dirty-Tracking + Speichern); alle anderen bleiben
        read-only (deaktivierte QGroupBox).
        Danach werden Panel-Breite (Default: 2 Spalten, Punkt 2) und
        Fensterbreite (Punkt 3) angepasst.
        """
        self._clear_panel()
        host = self._param_host
        host._current_plugin_editing = None
        host._current_set_definition = None
        host._current_preset_editing = None
        host._set_param_actions_visible(False)
        entries = list(entries or [])
        if not entries:
            self.param_box_layout.addWidget(
                QLabel("Keine Auswahl – klicke eine Zeile im Baum."))
            # Bugfix 06.08.2026 (Runde 3): Der abschliessende Stretch nimmt
            # den freien Platz auf – der Hinweis behaelt seine Default-Breite.
            self.param_box_layout.addStretch(1)
            self._apply_panel_size(0)
            # 08.08.2026 (Bugfix): Container auf Layout-Groesse nachziehen
            # (Scrollbalken statt Fensterhoehen-Anpassung).
            QTimer.singleShot(0, self._resize_param_container_deferred)
            return
        for entry in entries:
            pid = str(entry.get("plugin_id") or "")
            if entry["node_type"] == TYPE_SERVICE:
                iid = str(entry.get("instance_id") or "")
                cfg = self.model.find_service(
                    str(entry.get("set_id") or ""), iid) or {}
            else:
                iid = pid
                cfg = host._plugin_config(pid)
                # 10.08.2026 (Bugfix, Varianten-Params): presetspezifische
                # Parameter ueberschreiben die Registry-/Standalone-Defaults.
                preset_params = entry.get("preset_params")
                if isinstance(preset_params, dict) and preset_params:
                    merged = dict(cfg.get("params") or {})
                    merged.update(preset_params)
                    cfg["params"] = merged
                # Preset fuer den Save-Pfad merken (indicator_presets statt
                # global_settings).
                host._current_preset_editing = entry.get("preset")
            editable = bool(editable_plugin) and pid == editable_plugin
            try:
                box = host._build_service_column(iid, pid, cfg)
            except Exception as e:  # defensiv: Plugin/Schema-Fehler
                box = None
                self.param_box_layout.addWidget(
                    QLabel(f"Parameteranzeige nicht verfügbar: {e}"))
            if box is not None:
                if not editable:
                    box.setEnabled(False)
                    box.setToolTip("Read-Only – Parameter der gewählten "
                                   "Datenquelle (editierbar im ServiceWindow)")
                else:
                    # 18.01.01 (E-4): Editierbarer Standalone-Service –
                    # RAM-Definition fuer das Dirty-Tracking (_on_param_changed)
                    # bereitstellen; Persistenz via _save_plugin_params.
                    definition: Dict[str, Any] = {
                        "set_id": "",
                        "display_name": pid,
                        "description": str(cfg.get("description") or ""),
                        "execution_order": [pid],
                        "services": {pid: cfg},
                    }
                    host._current_plugin_editing = pid
                    host._current_set_definition = definition
                self.param_box_layout.addWidget(box)
        # Bugfix 06.08.2026 (Runde 3): Die einzelnen Service-Rahmen
        # (QGroupBox) werden beim Vergroessern NICHT gestreckt – sie behalten
        # ihre Default-Breite (sizeHint). Ohne abschliessenden Stretch
        # verteilt QHBoxLayout den freien Platz gleichmaessig auf alle
        # Spalten (Stretch-Faktor 0 = Aufteilung des Ueberschusses). Der
        # Stretch (Faktor 1) absorbiert den gesamten freien Platz.
        self.param_box_layout.addStretch(1)
        self._apply_panel_size(len(entries))
        # 08.08.2026 (Bugfix): Container auf Layout-Groesse nachziehen –
        # ScrollArea zeigt Scrollbalken statt Fensterhoehen-Anpassung.
        QTimer.singleShot(0, self._resize_param_container_deferred)

    def _apply_panel_size(self, col_count: int) -> None:
        """Punkt 2+3: Panel-MINIMUM-Breite (Default: ZWEI Spalten).

        Bei 1 Spalte wird das Minimum auf die Spaltenbreite gesetzt; ab 2
        Spalten gilt der Default (Platz fuer 2 nebeneinander). Mehr Spalten
        erzeugen eine horizontale Scrollbar (QScrollArea, AsNeeded). Die Box
        ist seit 06.08.2026 NICHT mehr fix: Der Benutzer kann das Fenster
        verzoegern/vergroessern – der Tree behaelt seine feste Breite
        (Punkt 4), die Parameter-Box waechst mit bzw. schrumpft bis zu
        diesem Minimum (Punkt 3).
        """
        widths = []
        for i in range(self.param_box_layout.count()):
            item = self.param_box_layout.itemAt(i)
            w = item.widget()
            if w is not None and w.sizeHint().isValid():
                widths.append(w.sizeHint().width())
        if not widths:
            panel_w = 280
        elif col_count >= 2:
            # Default: ZWEI Spalten nebeneinander (+ Puffer fuer Rahmen/
            # vertikale Scrollbar, damit keine horizontale Scrollbar erscheint).
            panel_w = widths[0] + widths[1] \
                + self.param_box_layout.spacing() + PANEL_BUFFER
        else:
            panel_w = widths[0] + PANEL_BUFFER
        panel_w = max(panel_w, 280)
        self._panel_min_width = panel_w
        # Minimum auf dem PANEL-WIDGET (Direkt-Kind im Body-Layout) UND der
        # ScrollArea: das Panel kann beim Fenster-Vergroessern mitwachsen,
        # aber nicht unter die 2-Spalten-Default-Groesse schrumpfen.
        self.param_panel.setMinimumWidth(panel_w)
        self.param_scroll.setMinimumWidth(panel_w)
        # Container-Minimum: volle Breite aller Spalten -> horizontale
        # Scrollbar, sobald der Inhalt breiter als das Panel ist (Punkt 2).
        total_w = sum(widths) + self.param_box_layout.spacing() * max(
            0, len(widths) - 1)
        self.param_container.setMinimumWidth(max(total_w, panel_w))
        # Punkt 3: Fensterbreite exakt bis zur rechten Kante der Parameter-Box.
        self._fit_dialog_width()

    def _resize_param_container_deferred(self) -> None:
        """Setzt den Param-Container auf seine Layout-Groesse (Scrollbar).

        08.08.2026 (Bugfix, ServiceWindow-Muster 07.08.2026): Bei
        widgetResizable=False behaelt der Container seine natuerliche
        Groesse (hier: layout().sizeHint()). Wird er groesser als der
        Viewport (viele/hohe Parameter), zeigt die ScrollArea vertikale
        Scrollbalken – die Dialog-Fensterhoehe bleibt FIX. Deferred (nach
        deleteLater der Alt-Spalten), damit der sizeHint nicht veraltet
        gelesen wird (QWidgetItemV2-Cache, Muster
        `_resize_param_box_deferred` in param_columns.py).
        """
        try:
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        except (RuntimeError, AttributeError):
            pass
        try:
            lay = self.param_container.layout()
            if lay is None:
                return
            self.param_container.updateGeometry()
            self.param_container.resize(lay.sizeHint())
            self.param_scroll.updateGeometry()
        except (RuntimeError, AttributeError):
            pass

    def _fit_dialog_width(self) -> None:
        """Punkt 3: Fensterbreite == rechte Kante der Parameter-Box.

        Misst die tatsaechliche rechte Kante des Panel-Widgets (Direkt-Kind
        des Dialogs, Minimum-Breite) und zieht das Fenster nach, falls die
        Kante ueber die Dialogkante hinauslaeuft. Beim Oeffnen gilt:
        Breite = Margins + fester Tree + Spacing + Panel-Minimum (2 Spalten).
        Eine vom Benutzer bewusst groessere Breite (gespeicherte Geometrie,
        Punkt 4) bleibt erhalten. Nach dem Anzeigen wird der Fit ueber
        `showEvent` + QTimer erneut angestossen (stabile Layout-Geometrie).
        """
        self.layout().activate()
        # 10.08.2026 (Bugfix, UI-Splitter): Das Panel liegt jetzt in einem
        # QSplitter - die rechte Kante muss dialog-relativ bestimmt werden
        # (mapTo statt geometry(), dessen Eltern-System der Splitter ist).
        # Das Panel ist das rechte Splitter-Widget; target = Tree-Breite +
        # Handle + Panel-Minimum + Margins waechst mit dem Inhalt mit.
        splitter = getattr(self, "_splitter", None)
        if splitter is not None:
            margins = self.layout().contentsMargins()
            tree_w = self.selector.size().width()
            handle = splitter.handleWidth()
            panel_min = max(self.param_panel.minimumWidth(),
                            self.param_panel.sizeHint().width())
            target = (margins.left() + tree_w + handle + panel_min
                      + margins.right() + 1)
        else:
            panel_right = self.param_panel.geometry().right()  # dialog-relativ
            margins_right = self.layout().contentsMargins().right()
            target = panel_right + margins_right + 1
        target = max(target, self.minimumWidth())
        if self.width() < target:
            self.resize(target, self.height())

    def showEvent(self, event) -> None:
        """Punkt 3: Fensterbreite nach dem Anzeigen nachziehen (deferred).

        Vor `show()` sind die Layout-Geometrien (Positionen) noch nicht
        berechnet – der deferred Fit stellt sicher, dass die Fensterbreite
        exakt an der rechten Kante der Parameter-Box endet.
        """
        super().showEvent(event)
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._fit_dialog_width)
        except Exception:
            pass

    def _clear_panel(self) -> None:
        """Leert das Parameter-Panel (alle Spalten + Control-Registry)."""
        while self.param_box_layout.count():
            item = self.param_box_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        host = self._param_host
        host._service_param_controls.clear()
        host._service_desc_controls.clear()
        # 08.08.2026 (Bugfix): Schema-/Label-Registrys ebenfalls zuruecksetzen
        # (Muster `_clear_service_columns` in param_columns.py) – sonst bleiben
        # Conditional-Visibility-Schemas und Info-Labels fremder Instanzen
        # haengen, wenn der naechste Spaltenaufbau weniger Spalten baut.
        host._mode_schemas.clear()
        host._service_param_labels.clear()
        host._service_info_labels.clear()
        host._service_info_pids.clear()

    # ------------------------------------------------------------------
    # 13.08.2026 (Runde 3d): Grafikteiler Tree|Parameter
    # ------------------------------------------------------------------
    def _on_splitter_moved(self, _pos: int, _index: int) -> None:
        """Meldet die Splitter-Position an das AnalyticsWindow (Workspace/
        Profil-Persistenz, Runde 3d)."""
        try:
            sizes = list(self._splitter.sizes())
            if len(sizes) >= 2:
                self.splitter_changed.emit(sizes[0], sizes[1])
        except (RuntimeError, AttributeError):
            pass

    def current_splitter_sizes(self) -> List[int]:
        """Aktuelle Splitter-Breiten (Tree, Panel) fuer Workspace/Profil."""
        try:
            sizes = list(self._splitter.sizes())
            return [int(s) for s in sizes if str(s).strip().lstrip("-").isdigit()]
        except (RuntimeError, AttributeError):
            return []

    def set_splitter_sizes(self, sizes) -> None:
        """Wendet gespeicherte Splitter-Breiten an (Workspace/Profil).

        Defensiv: nur 2 positive Werte; der Tree respektiert seine
        Mindestbreite (selector.minimumWidth)."""
        try:
            if not sizes or not isinstance(sizes, (list, tuple)):
                return
            clean = [int(s) for s in sizes
                     if str(s).strip().lstrip("-").isdigit() and int(s) > 0]
            if len(clean) != 2:
                return
            try:
                min_tree = self.selector.minimumWidth()
            except (RuntimeError, AttributeError):
                min_tree = 0
            if clean[0] < min_tree:
                clean[0] = min_tree
            self._splitter.setSizes(clean)
        except (RuntimeError, AttributeError):
            pass

    # ------------------------------------------------------------------
    # Punkt 4: Geometrie-Persistenz (global_settings, IndicatorDialog-Muster)
    # ------------------------------------------------------------------
    def _restore_geometry(self) -> None:
        """Stellt die letzte Position/Groesse des Dialogs wieder her.

        Gespeichert wird in global_settings (save_dialog_geometry) – der
        Dialog ist kein PersistentWindow. Beim naechsten Panel-Aufbau wird
        die Breite ggf. auf den Inhalts-Bedarf angehoben (Punkt 3).
        """
        sm = self._state_manager
        if sm is None:
            return
        try:
            geom = sm.get_dialog_geometry(DIALOG_GEOMETRY_KEY)
        except Exception:
            return
        if not geom:
            return
        try:
            pos_x = geom.get("pos_x")
            pos_y = geom.get("pos_y")
            w = geom.get("width")
            h = geom.get("height")
            # Runde 10 (Bug 5): Gegen ALLE Screens pruefen - eine Position
            # auf dem 2. Monitor ist NICHT off-screen (Fallback nur, wenn
            # sie auf KEINEM Screen liegt). Vorher wurde nur der Primary-
            # Screen geprueft -> Position auf Monitor 2 wurde verworfen.
            screens = [s.availableGeometry()
                       for s in QApplication.screens()]
            if pos_x is not None and pos_y is not None:
                on_screen = any(
                    (scr.x() - 100 <= pos_x <= scr.right())
                    and (scr.y() - 100 <= pos_y <= scr.bottom())
                    for scr in screens)
                if not on_screen:
                    pos_x = pos_y = None
                else:
                    self.move(pos_x, pos_y)
            if w and h:
                self.resize(max(int(w), self.minimumWidth()), int(h))
            # 13.08.2026 (Runde 3d): Grafikteiler Tree|Parameter aus
            # der Historie wiederherstellen (global_settings).
            try:
                sizes = sm.get_splitter_state(DIALOG_GEOMETRY_KEY)
                if sizes:
                    self.set_splitter_sizes(sizes)
            except Exception:
                pass
        except Exception:
            pass

    def _save_geometry(self) -> None:
        """Speichert die aktuelle Position/Groesse des Dialogs (Punkt 4)."""
        sm = self._state_manager
        if sm is None:
            return
        try:
            p = self.pos()
            s = self.size()
            sm.save_dialog_geometry(
                DIALOG_GEOMETRY_KEY, p.x(), p.y(), s.width(), s.height())
            # 13.08.2026 (Runde 3d): Grafikteiler mitpersistieren
            # (Gesamt-Historie in global_settings).
            try:
                sm.save_splitter_state(
                    DIALOG_GEOMETRY_KEY, self.current_splitter_sizes())
            except Exception:
                pass
        except Exception:
            pass

    def done(self, r: int) -> None:
        """Wird bei jedem Schliessen gerufen (accept/reject/Esc/X) ->
        Geometrie vor dem Schliessen speichern (Punkt 4)."""
        self._save_geometry()
        super().done(r)
