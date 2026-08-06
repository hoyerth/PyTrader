# serviceui/service_selector_dialog.py
"""
Service-UI: ServiceSelectorDialog (Phase 15.03-E, Multi-Select).

Dialog/Popover fuer die wiederverwendbare Service-Auswahl im
AnalyticsWindow ("Datenquellen"). Bettet das bestehende
`ServiceSelectorWidget` im Modus `MODE_SELECT_MULTI` ein (DRY-Prinzip):

  * Links:  `MasterTree` mit Checkboxen (`[x]`) an allen Set-, Service-,
            Standalone- und Plugin-Knoten (Tri-State fuer Sets).
  * Rechts: Read-Only-"Service-Parameter"-Panel – die Parameter-Spalten aus
            service_win.py (`ServiceParamColumnsMixin._build_service_column`),
            deaktiviert (setEnabled(False), kein Bearbeiten/Speichern):
              - angehakte Set-Services -> Spalte je Service des Sets
              - angehakte Standalone-/Plugin-Zeilen -> Spalte je Plugin

Aktions-Zeile unten:
  * [ 🗑️ Aktive Filter entfernen ] – modale Sicherheitsabfrage
    (`QMessageBox.question`), setzt alle Checkboxen zurueck und emittiert
    `services_selected([], [])`.
  * [ 💾 Anwenden & Schließen ]     – emittiert
    `services_selected(display_names, feature_ids)` und schliesst.

Datenvertrag (Entscheidung 06.08.2026):
  * `display_names`: lesbare Namen fuer die Button-Anzeige
    (z. B. ["Mein Scalper/prox_1", "proximity"]).
  * `feature_ids`:   technische IDs fuer die SQL-Abfrage – die plugin_ids
    des Feature-Store (z. B. ["grid_lines", "proximity"]), dedupliziert
    (`feature_store.feature_id` IST die plugin_id).

Live-Sync (Invariante 5): Das `ServiceSelectorModel` hoert auf
`event_bus.service_set_changed` und refresht den Baum automatisch; der
Checkbox-Zustand bleibt dank MasterTree-internem `_checked_items` ueber
Neuaufbauten erhalten. Das rechte Panel wird bei jeder Checkbox-Aenderung
und jedem Modell-Refresh neu gebaut.

Bugfix-Runde 06.08.2026 (User-Anweisung, Punkte 1-4):
  1. Services im Parameter-Panel liegen HORIZONTAL nebeneinander
     (`QHBoxLayout` statt `QVBoxLayout`).
  2. Default-Breite der Parameter-Box = Platz fuer ZWEI Spalten
     nebeneinander; bei mehr angehakten Services wird horizontal gescrollt
     (QScrollArea, `ScrollBarAsNeeded`).
  3. Die Fensterbreite endet exakt an der rechten Kante der Parameter-Box
     (rechte Kante Dialog == rechte Kante Panel, `_fit_dialog_width`).
  4. Letzte Fensterposition/-groesse werden persistiert
     (`state_manager.save_dialog_geometry`, Key 'service_selector') und beim
     naechsten Oeffnen wiederhergestellt (Muster IndicatorSettingsDialog).
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.service_selector_model import ServiceSelectorModel
from serviceui.param_columns import ServiceParamColumnsMixin
from serviceui.service_selector_widget import ServiceSelectorWidget

#: Geometrie-Key fuer Position/Groesse des Datenquellen-Dialogs
#: (global_settings, Muster IndicatorSettingsDialog).
DIALOG_GEOMETRY_KEY = "service_selector"
#: Puffer fuer ScrollArea-Rahmen/-Scrollbar, damit 2 Spalten OHNE horizontale
#: Scrollbar nebeneinander passen (Punkt 2).
PANEL_BUFFER = 24
#: Body-Spacing (body.setSpacing(8) unten) – fuer die Breiten-Rechnung (Punkt 3).
BODY_SPACING = 8
#: 06.08.2026 (Punkte 3+4): FESTE Default-Breite des MasterTree (links).
#: Beim manuellen Vergroessern des Fensters behaelt der Tree diese Breite;
#: nur die Parameter-Box waechst mit (bzw. schrumpft bis zu ihrer
#: Minimum-Breite = Platz fuer zwei Service-Spalten nebeneinander).
TREE_DEFAULT_WIDTH = 300


class _DialogParamHost(ServiceParamColumnsMixin):
    """Minimaler Mixin-Host fuer das Read-Only-Parameter-Panel des Dialogs.

    `ServiceParamColumnsMixin._build_service_column()` erwartet Host-
    Attribute des ServiceWindow (Parameter-Controls, Sperr-Lookup usw.).
    Dieser Mini-Host stellt nur die benoetigten Attribute/Methoden bereit;
    alle Bearbeitungs-/Persistenz-Pfade sind no-op – der Dialog zeigt die
    Parameter-Spalten ausschliesslich Read-Only an (deaktivierte QGroupBox,
    kein Dirty-Tracking, kein Speichern).
    """

    def __init__(self) -> None:
        self._service_param_controls: Dict[str, Any] = {}
        self._service_desc_controls: Dict[str, Any] = {}
        self._symbol_precision: Optional[int] = None
        self.combo_symbol = None
        self.combo_tf = None

    def _service_lock(self, plugin_id: str):
        """Keine Set-Sperre im Dialog (Read-Only-Anzeige)."""
        return "", ""

    def _open_service_desc_editor(self, instance_id: str) -> None:
        """Read-Only: kein Beschreibungs-Editor im Dialog."""
        pass

    def _schedule_reflow(self) -> None:
        """Read-Only: kein Editor-Reflow noetig."""
        pass


class ServiceSelectorDialog(QDialog):
    """Multi-Select-Dialog fuer die Analytics-Datenquellen (15.03-E)."""

    #: (display_names, feature_ids) – beim 'Anwenden & Schliessen' bzw.
    #: leere Listen beim 'Aktive Filter entfernen'.
    services_selected = Signal(list, list)

    def __init__(
        self,
        model: Optional[ServiceSelectorModel] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.model = model or ServiceSelectorModel(parent=self)
        self._param_host = _DialogParamHost()
        # 06.08.2026 (Punkt 4): StateManager fuer die Dialog-Geometrie.
        # Der Parent (AnalyticsWindow) ist ein PersistentWindow mit
        # `state_manager`-Property; ohne Parent bleiben Save/Restore no-ops.
        self._state_manager = getattr(parent, "state_manager", None)
        # 06.08.2026 (Punkte 3+4): Minimum-Breite der Parameter-Box
        # (Default: Platz fuer 2 Service-Spalten nebeneinander).
        self._panel_min_width: int = 0

        self.setWindowTitle("Datenquellen auswählen")
        self.resize(980, 600)
        self.setMinimumWidth(760)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- Body: links MasterTree (Checkboxen), rechts Parameter-Panel ---
        body = QHBoxLayout()
        body.setSpacing(BODY_SPACING)
        self.selector = ServiceSelectorWidget(
            ServiceSelectorWidget.MODE_SELECT_MULTI,
            model=self.model,
            parent=self,
        )
        # Punkt 4: Die BREITE DES TREES IST FIX (TREE_DEFAULT_WIDTH) – beim
        # manuellen Vergroessern des Fensters bleibt der Tree stehen und nur
        # die Parameter-Box waechst mit (Punkt 3).
        self.selector.setFixedWidth(TREE_DEFAULT_WIDTH)
        body.addWidget(self.selector, 0)

        panel = QWidget(self)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(4)
        panel_layout.addWidget(
            QLabel("Service-Parameter (Read-Only):"))
        self.param_panel = panel  # 06.08.2026: feste Breite auf dem PANEL-WIDGET
        self.param_scroll = QScrollArea(panel)
        self.param_scroll.setWidgetResizable(True)
        # Punkt 2: bei mehr als 2 Spalten horizontale Scrollbar (AsNeeded).
        self.param_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.param_container = QWidget()
        # Punkt 1: Service-Spalten horizontal nebeneinander (QHBoxLayout).
        self.param_box_layout = QHBoxLayout(self.param_container)
        self.param_box_layout.setContentsMargins(0, 0, 0, 0)
        self.param_box_layout.setSpacing(6)
        self.param_scroll.setWidget(self.param_container)
        panel_layout.addWidget(self.param_scroll, 1)
        body.addWidget(panel, 2)
        root.addLayout(body, 1)

        # --- Aktions-Zeile unten ---
        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.btn_clear = QPushButton("🗑️ Aktive Filter entfernen")
        self.btn_clear.setToolTip(
            "Entfernt alle angehakten Datenquellen (mit Sicherheitsabfrage).")
        self.btn_apply = QPushButton("💾 Anwenden & Schließen")
        self.btn_apply.setDefault(True)
        actions.addWidget(self.btn_clear)
        actions.addStretch(1)
        actions.addWidget(self.btn_apply)
        root.addLayout(actions)

        # --- Verdrahtung ---
        self.btn_clear.clicked.connect(self._on_clear_filters)
        self.btn_apply.clicked.connect(self._on_apply)
        tree = self.selector.master_tree
        if tree is not None:
            tree.checked_changed.connect(self._rebuild_param_panel)
        # Live-Sync: Modell-Refresh (EventBus -> data_changed) baut den Baum
        # neu; das Panel wird hier explizit nachgezogen (checked_changed
        # feuert waehrend des blockierten Neuaufbaus nicht).
        self.model.data_changed.connect(self._rebuild_param_panel)

        # Punkt 4: Letzte Position/Groesse wiederherstellen.
        self._restore_geometry()
        # Panel initial bauen (leer -> Hinweis), damit die Breiten-Logik
        # (Punkte 2+3) vor dem Anzeigen greift.
        self._rebuild_param_panel()

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------
    def apply_feature_ids(self, feature_ids: List[str]) -> None:
        """Spiegelt die aktuelle ViewModel-Auswahl im Baum (Reverse-Mapping).

        Wird beim Oeffnen des Dialogs gerufen, damit ein restauriertes
        Profil bzw. der aktive Filter im Checkbox-Baum sichtbar ist.
        """
        tree = self.selector.master_tree
        if tree is not None:
            tree.set_checked_feature_ids(list(feature_ids or []))

    def current_display_names(self) -> List[str]:
        tree = self.selector.master_tree
        return tree.checked_display_names() if tree is not None else []

    def current_feature_ids(self) -> List[str]:
        tree = self.selector.master_tree
        return tree.checked_feature_ids() if tree is not None else []

    # ------------------------------------------------------------------
    # Aktions-Zeile
    # ------------------------------------------------------------------
    def _on_clear_filters(self) -> None:
        """Leert alle Checkboxen (mit Sicherheitsabfrage) und emittiert leer.

        Entspricht dem Task-Vertrag: `services_selected([], [])` – der
        AnalyticsWindow setzt daraufhin den Filter zurueck (alle Features).
        """
        reply = QMessageBox.question(
            self, "Aktive Filter entfernen",
            "Möchtest du alle aktiven Datenquellen-Filter wirklich entfernen? "
            "Die Anzeige im Analytics-Fenster zeigt danach wieder alle "
            "Features.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        tree = self.selector.master_tree
        if tree is not None:
            tree.clear_checks()
        self.services_selected.emit([], [])

    def _on_apply(self) -> None:
        """Emittiert `services_selected(display_names, feature_ids)` und zu."""
        self.services_selected.emit(
            self.current_display_names(),
            self.current_feature_ids(),
        )
        self.accept()

    # ------------------------------------------------------------------
    # Read-Only-Parameter-Panel (Punkte 1-3: horizontal, 2-Spalten-Default,
    # Fensterbreite == rechte Kante der Parameter-Box)
    # ------------------------------------------------------------------
    def _rebuild_param_panel(self) -> None:
        """Baut das rechte Parameter-Panel aus den angehakten Services neu.

        Fuer jeden angehakten Service wird eine deaktivierte QGroupBox-
        Spalte ueber `ServiceParamColumnsMixin._build_service_column()`
        erzeugt – seit 06.08.2026 HORIZONTAL nebeneinander (Punkt 1):
          * Set-Service:  cfg aus der Set-Definition (instance_id + params)
          * Standalone-/Plugin-Zeile: cfg {"plugin_id": pid} (Schema-Defaults)
        Danach werden Panel-Breite (Default: 2 Spalten, Punkt 2) und
        Fensterbreite (Punkt 3) angepasst.
        """
        self._clear_panel()
        tree = self.selector.master_tree
        if tree is None:
            return
        entries = tree.checked_services()
        if not entries:
            self.param_box_layout.addWidget(
                QLabel("Keine Datenquellen ausgewählt."))
            self._apply_panel_size(0)
            return
        host = self._param_host
        for entry in entries:
            pid = str(entry.get("plugin_id") or "")
            if entry["node_type"] == "service":
                iid = str(entry.get("instance_id") or "")
                cfg = self.model.find_service(
                    str(entry.get("set_id") or ""), iid) or {}
            else:
                iid = pid
                cfg = {"plugin_id": pid}
            try:
                box = host._build_service_column(iid, pid, cfg)
            except Exception as e:  # defensiv: Plugin/Schema-Fehler
                box = None
                self.param_box_layout.addWidget(
                    QLabel(f"Parameteranzeige nicht verfügbar: {e}"))
            if box is not None:
                box.setEnabled(False)
                box.setToolTip("Read-Only – Parameter der gewählten Datenquelle")
                self.param_box_layout.addWidget(box)
        self._apply_panel_size(len(entries))

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
        self._param_host._service_param_controls.clear()
        self._param_host._service_desc_controls.clear()

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
            screen = QApplication.primaryScreen().availableGeometry()
            if pos_x is not None and pos_y is not None:
                if (pos_x < screen.x() - 100 or pos_x > screen.right() or
                        pos_y < screen.y() - 100 or pos_y > screen.bottom()):
                    pos_x = pos_y = None
                else:
                    self.move(pos_x, pos_y)
            if w and h:
                self.resize(max(int(w), self.minimumWidth()), int(h))
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
        except Exception:
            pass

    def done(self, r: int) -> None:
        """Wird bei jedem Schliessen gerufen (accept/reject/Esc/X) ->
        Geometrie vor dem Schliessen speichern (Punkt 4)."""
        self._save_geometry()
        super().done(r)
