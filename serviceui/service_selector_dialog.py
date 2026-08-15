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
    (z. B. ["Mein Scalper/prox_1", "srv_proximity"]).
  * `feature_ids`:   technische IDs fuer die SQL-Abfrage – die plugin_ids
    des Feature-Store (z. B. ["srv_grid_lines", "srv_proximity"]), dedupliziert
    (`feature_store.feature_id` IST die plugin_id).

Live-Sync (Invariante 5): Das `ServiceSelectorModel` hoert auf
`event_bus.service_set_changed` und refresht den Baum automatisch; der
Checkbox-Zustand bleibt dank MasterTree-internem `_checked_items` ueber
Neuaufbauten erhalten. Das rechte Panel wird nach einem Modell-Refresh mit
dem zuletzt GEKLICKTEN Scope neu gebaut.

Bugfix-Runde 3 (06.08.2026, User-Anweisung Punkte 1-7): Das Read-Only-Panel
folgt dem MAUSKLICK auf eine Tree-Zeile (analog service_win), NICHT den
Checkboxen:
  1. Angezeigt werden NICHT mehr alle angehakten Services, sondern die
     Parameter der GEKLICKTEN Zeile.
  2. Die Anzeige haengt NICHT von den Checkboxen ab (die Checkboxen
     bestimmen weiterhin nur den Analytics-Filter feature_ids).
  3. Jeder einfache Mausklick in einer Tree-Zeile waehlt die Anzeige
     (`MasterTree.selection_details`, wird aus mousePressEvent emittiert).
  4. Klick auf eine SET-Zeile -> Parameter aller Services des Sets.
  5. Klick auf eine SERVICE-Zeile IN einem Set -> ebenfalls alle Services
     des Sets (service_win-Muster `_on_master_selection`).
  6. Klick auf eine PLUGIN-Zeile (⚡ Standalone / 📦 Plugins) -> NUR dieser
     eine Service wird angezeigt.
  7. Alle anderen Zeilen (Gruppen, leere Auswahl) -> KEIN Service im Panel.
  8. (Nachtrag) Die einzelnen Service-Rahmen (QGroupBox) behalten beim
     Vergroessern ihre DEFAULT-Breite (sizeHint) – der abschliessende
     Stretch im QHBoxLayout absorbiert den freien Platz (kein Strecken).

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

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.description_dialog import ServiceDescriptionDialog
from analytics.engine.feature_store_reader import FeatureStoreReader
from analytics.engine.service_models import generate_instance_hash
from analytics.engine.service_selector_model import ServiceSelectorModel
from analytics.engine.set_evaluator import ServiceSetEvaluator
from config.event_bus import event_bus
from serviceui.master_tree import (
    TYPE_CATEGORY, TYPE_CLONE, TYPE_PLUGIN, TYPE_SERVICE, TYPE_SET,
)
from serviceui.param_columns import ServiceParamColumnsMixin
from serviceui.service_selector_widget import ServiceSelectorWidget
# 21.01b (11.08.2026): Run im Picker (TF-Zeile + Pill-Strip, User-Entscheid).
from serviceui.common_widgets import TfStatusBadgeBar
from serviceui.run_worker import ALL_TIMEFRAMES, ServiceRunWorker
from serviceui.service_set_utils import variant_run_entries
from serviceui.service_selector_dialog_selection import ServiceSelectorDialogSelectionMixin
from serviceui.service_selector_dialog_presets import ServiceSelectorDialogPresetMixin
from serviceui.service_selector_dialog_sets import ServiceSelectorDialogSetMixin
from serviceui.service_selector_dialog_run import ServiceSelectorDialogRunMixin
from serviceui.service_selector_dialog_badge import ServiceSelectorDialogBadgeMixin
from serviceui.service_selector_dialog_panel import ServiceSelectorDialogPanelMixin

from serviceui.service_selector_dialog_constants import (
    BODY_SPACING,
    DIALOG_GEOMETRY_KEY,
    PANEL_BUFFER,
    TREE_DEFAULT_WIDTH,
)
from serviceui.service_selector_dialog_host import _DialogParamHost


class ServiceSelectorDialog(
    QDialog,
    ServiceSelectorDialogSelectionMixin, ServiceSelectorDialogPresetMixin,
    ServiceSelectorDialogSetMixin, ServiceSelectorDialogRunMixin,
    ServiceSelectorDialogBadgeMixin, ServiceSelectorDialogPanelMixin,
):
    """Multi-Select-Dialog fuer die Analytics-Datenquellen (15.03-E).

    18.01.01 (E-4): Der Picker ist das frei bewegliche "Manager-Window"
    waehrend einer Analytics-Session. Zusaetzlich zum Multi-Select-Filter:
      * Live-Filter: Klick auf eine Baum-Zeile (Set/Ordner/Plugin) loest die
        feature_ids auf und emittiert `selection_ids_requested` – das
        AnalyticsWindow filtert sofort (ohne 'Anwenden').
      * Standalone-Editierung: Standalone-Services (belongs_to_indicator ==
        False) sind im Param-Panel editierbar (plugin_params_<id>, E-3).
      * Verwaltung: MasterTree-Kontextmenue (Set anlegen/umbenennen/loeschen,
        Service hinzufuegen/entfernen/verschieben) via ServiceSetRepository –
        Services lassen sich waehrend der Session live verwalten.
    """

    #: (display_names, feature_ids) – beim 'Anwenden & Schliessen' bzw.
    #: leere Listen beim 'Aktive Filter entfernen'.
    services_selected = Signal(list, list)
    #: 18.01.01 (E-4): Live-Filter - aufgeloeste feature_ids (plugin_ids),
    #: sofort an das AnalyticsWindow. 10.08.2026 (Bugfix, Punkt 1+2): Der
    #: Filter folgt AUSSCHLIESSLICH den Checkboxen (checked_changed ->
    #: _on_checked_changed -> checked_feature_ids()); der Zeilen-Klick
    #: emittiert dieses Signal NICHT mehr (nur das Read-Only-Panel folgt
    #: dem Klick, Punkte 1-7).
    selection_ids_requested = Signal(list)
    # Runde 10 (Bug 1): Varianten-granularer Filter - instance_hashes der
    # gecheckten Clone-Varianten (parallel zu selection_ids_requested).
    selection_hashes_requested = Signal(list)
    # 13.08.2026 (Runde 3d): Grafikteiler Tree|Parameter verschoben
    # (tree_width, panel_width) - das AnalyticsWindow merkt sich die
    # Position fuer Workspace- und Profil-Persistenz.
    splitter_changed = Signal(int, int)

    def __init__(
        self,
        model: Optional[ServiceSelectorModel] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.model = model or ServiceSelectorModel(parent=self)
        # 18.01.01: Zugriff auf die ServiceSetRepository (CRUD-Verwaltung).
        self.set_repo = getattr(self.model, "set_repo", None)
        # 06.08.2026 (Punkt 4): StateManager fuer die Dialog-Geometrie.
        # Der Parent (AnalyticsWindow) ist ein PersistentWindow mit
        # `state_manager`-Property; ohne Parent bleiben Save/Restore no-ops.
        self._state_manager = getattr(parent, "state_manager", None)
        self._param_host = _DialogParamHost(state_manager=self._state_manager)
        # 21.01b (11.08.2026): Run-Infrastruktur fuer die MasterTree-
        # Kontextmenue-Aktionen (User-Entscheid: Run im Picker voll
        # funktional, TF-Zeile + Pill-Strip).
        self.set_evaluator = ServiceSetEvaluator()
        self._run_worker: Optional[ServiceRunWorker] = None
        #: Plugin-ID des Services, dessen TF-Pills aktuell angezeigt werden.
        self._badge_plugin_id: Optional[str] = None
        # 12.08.2026 (User-Meldung 'Data only loeschen'): Optionaler
        # instance_hash der angezeigten Variante - der Pill-Strip wird
        # damit VARIANTEN-GENAU geladen (nach Purge verschwinden ihre TFs).
        self._badge_instance_hash: Optional[str] = None
        # 06.08.2026 (Bugfix-Runde 3, Punkte 1-7): Zuletzt GEKLICKTE
        # Tree-Zeile (node_type, set_id, service_id, plugin_id) – Grundlage
        # des Panels (analog service_win). Bleibt nach Modell-Refreshes
        # erhalten, damit das Panel nicht ungewollt zurueckspringt.
        self._last_scope: Optional[tuple] = None
        # 06.08.2026 (Punkte 3+4): Minimum-Breite der Parameter-Box
        # (Default: Platz fuer 2 Service-Spalten nebeneinander).
        self._panel_min_width: int = 0

        self.setWindowTitle("Datenquellen auswählen")
        self.resize(980, 600)
        self.setMinimumWidth(760)
        root = QVBoxLayout(self)
        # 08.08.2026 (Bugfix): `setSizeConstraint` ist eine QLayout-Methode,
        # KEIN QWidget-Attribut – der fruehere self.setSizeConstraint(...)-
        # Aufruf crashte beim Oeffnen des Pickers (AttributeError). Der
        # QDialog-Default (SetDefaultConstraint) wuerde die Fenstergroesse
        # beim show() auf den Layout-sizeHint setzen (Hoehe an die Parameter-
        # Spalten geklemmt); SetNoConstraint haelt die Fenstergroesse FIX,
        # bei Ueberhoehe zeigt die ScrollArea Scrollbalken.
        root.setSizeConstraint(QLayout.SetNoConstraint)
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
        # 10.08.2026 (Bugfix, UI-Splitter): Der Tree ist NICHT mehr starr
        # fixiert - er liegt zusammen mit dem Parameter-Panel in einem
        # QSplitter, dessen Handle der Anwender mit der Maus frei verschieben
        # kann (Klick-Ergonomie, Punkt 3). Nur die Mindestbreite verhindert
        # das Kollabieren; TREE_DEFAULT_WIDTH ist die Startgroesse.
        self.selector.setMinimumWidth(180)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self.selector)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setCollapsible(0, False)

        panel = QWidget(self)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(4)
        panel_layout.addWidget(
            QLabel("Service-Parameter (Read-Only):"))
        # 21.01b (11.08.2026): Run-Timeframe-Zeile (combo_run_tf, Sentinel
        # ALL_TIMEFRAMES wie im ServiceWindow) + TF-Status-Pills des zuletzt
        # geklickten Services (fetch_service_tf_status).
        tf_row = QHBoxLayout()
        tf_row.setSpacing(4)
        tf_row.addWidget(QLabel("Run Timeframe:"))
        self.combo_run_tf = QComboBox()
        self.combo_run_tf.setMinimumWidth(130)
        self.combo_run_tf.setToolTip(
            "Zeitrahmen fuer '▶️ Service(s) ausführen' – 'ALLE Timeframes' "
            "fuehrt alle verfuegbaren Timeframes nacheinander aus.")
        tf_row.addWidget(self.combo_run_tf)
        tf_row.addStretch(1)
        panel_layout.addLayout(tf_row)
        self.badge_bar = TfStatusBadgeBar()
        panel_layout.addWidget(self.badge_bar)
        # 12.08.2026 (User-Meldung 2): Fortschrittsbalken fuer Service-Runs
        # (Muster service_win) - zeigt je Service den Fortschritt ueber alle
        # Services des aktuellen Timeframes (ServiceRunWorker.service_progress).
        self.progress_label = QLabel("")
        self.progress_bar = QProgressBar()
        # 12.08.2026 (User-Meldung 'Fortschrittsbalken laeuft dauerhaft'):
        # setMaximum(0) startet eine INDETERMINATE Busy-Animation, die nie
        # endet. Determinate leere Range (0..1, Wert 0) statt Busy-Loop;
        # _on_service_progress setzt beim Run die echte Range (max(total,1)).
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(16)
        self.progress_bar.setTextVisible(False)
        progress_row = QHBoxLayout()
        progress_row.setSpacing(6)
        progress_row.addWidget(self.progress_label, 3)
        progress_row.addWidget(self.progress_bar, 2)
        panel_layout.addLayout(progress_row)
        self._fill_run_tf_combo()
        self.param_panel = panel  # 06.08.2026: feste Breite auf dem PANEL-WIDGET
        self.param_scroll = QScrollArea(panel)
        # 08.08.2026 (Bugfix, ServiceWindow-Muster 07.08.2026): widgetResizable
        # False – der Param-Container behaelt seine NATUERLICHE Groesse
        # (wird nach jedem Panel-Aufbau explizit auf layout().sizeHint()
        # gesetzt, _resize_param_container_deferred). Wird er groesser als
        # der Viewport (viele/hohe Parameter), zeigt die ScrollArea vertikale
        # Scrollbalken – die Dialog-Fensterhoehe bleibt FIX (keine
        # Hoehen-Anpassung an den Parameter-Inhalt).
        self.param_scroll.setWidgetResizable(False)
        # Punkt 2: bei mehr als 2 Spalten horizontale Scrollbar (AsNeeded).
        self.param_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # 08.08.2026 (Bugfix): auch vertikal Scrollbalken bei Ueberhoehe.
        self.param_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.param_container = QWidget()
        # Punkt 1: Service-Spalten horizontal nebeneinander (QHBoxLayout).
        self.param_box_layout = QHBoxLayout(self.param_container)
        self.param_box_layout.setContentsMargins(0, 0, 0, 0)
        self.param_box_layout.setSpacing(6)
        self.param_scroll.setWidget(self.param_container)
        panel_layout.addWidget(self.param_scroll, 1)
        # 18.01.01 (E-3): Speichern-Button fuer editierbare Standalone-
        # Services (wird nur bei Parameter-Aenderungen eingeblendet).
        self.btn_save_params = QPushButton("💾 Parameter speichern")
        self.btn_save_params.setVisible(False)
        self.btn_save_params.setToolTip(
            "Speichert die Parameter des editierbaren Standalone-Services "
            "(plugin_params_<id>) inkl. EventBus-Sync (E-3).")
        panel_layout.addWidget(self.btn_save_params)
        self._splitter.addWidget(panel)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setCollapsible(1, False)
        self._splitter.setSizes([TREE_DEFAULT_WIDTH, 620])
        # 13.08.2026 (Runde 3d): Splitter-Bewegung live melden
        # (Workspace-/Profil-Persistenz im AnalyticsWindow);
        # zusaetzlich sichert _save_geometry die Position in
        # global_settings (Historie).
        self._splitter.splitterMoved.connect(self._on_splitter_moved)
        body.addWidget(self._splitter, 1)
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
        self.btn_save_params.clicked.connect(self._on_save_plugin_params)
        tree = self.selector.master_tree
        if tree is not None:
            # Bugfix-Runde 3 (06.08.2026): Das Panel folgt dem MAUSKLICK auf
            # eine Tree-Zeile (selection_details), NICHT den Checkboxen
            # (checked_changed-Verbindung entfernt – Punkte 1-7).
            tree.selection_details.connect(self._on_tree_selection_details)
            # 10.08.2026 (Bugfix, Punkt 2): Check/Uncheck im ServicePicker
            # muss die Resultatparameter-Dropdowns live aktualisieren - der
            # Analytics-Filter (feature_ids) folgt den HAKEN (checked_changed),
            # zusaetzlich zum Klick-Scope (selection_details). Das Panel
            # selbst bleibt klickgesteuert (Punkte 1-7 unveraendert).
            tree.checked_changed.connect(self._on_checked_changed)
            # 18.01.01 (E-4): Live-Verwaltung waehrend der Analytics-Session –
            # der MasterTree emittiert die CRUD-Signale; der Dialog fuehrt
            # sie ueber die ServiceSetRepository aus (Set anlegen/umbenennen/
            # loeschen, Service hinzufuegen/entfernen/verschieben).
            tree.create_set_requested.connect(self._on_create_set)
            tree.rename_set_requested.connect(self._on_rename_set)
            tree.add_set_service_requested.connect(self._on_add_set_service)
            tree.delete_set_requested.connect(self._on_delete_set)
            tree.move_service_requested.connect(self._on_move_service)
            tree.remove_service_requested.connect(self._on_remove_service)
            # 18.01.03 (Dynamic Tree Management): Kategorie-Drag&Drop &
            # Ordner-CRUD im Picker (Manager-Window) – Sets/Plugins/Ordner
            # ziehen (folder_item_moved/folder_moved), 'Neuer Ordner' (wird
            # PERSISTIERT, E3-revidiert 08.08.2026), 'Umbenennen'
            # (rename_folder_requested) und 'Ordner löschen' (manuelle
            # Loeschung) werden hier persistiert.
            tree.folder_item_moved.connect(self._on_folder_item_moved)
            tree.folder_moved.connect(self._on_folder_moved)
            tree.rename_folder_requested.connect(self._on_rename_folder)
            tree.create_folder_requested.connect(self._on_create_folder)
            tree.delete_folder_requested.connect(self._on_delete_folder)
            # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im MasterTree-Kontextmenue
            # (Service-/Clone-Zeilen) -> Handler (Muster service_win). Ohne
            # diese Verbindungen emittiert der MasterTree die Signale zwar,
            # aber niemand fuehrt sie aus – 'Als Variante duplizieren' im
            # Analytics-Datenquellen-Picker blieb wirkungslos (Q8-Bugfix).
            tree.data_only_purge_requested.connect(
                self._on_data_only_purge)
            tree.delete_complete_requested.connect(
                self._on_delete_complete)
            tree.doc_log_requested.connect(self._on_doc_log_requested)
            tree.duplicate_variant_requested.connect(
                self._on_duplicate_variant)
            # 10.08.2026 (Bugfix): 'Variante umbenennen' (Clone/Preset) –
            # der MasterTree fragt den neuen Namen ab; dieser Handler
            # persistiert den Rename in indicator_presets.
            tree.rename_variant_requested.connect(
                self._on_rename_variant)
            # 21.01b (11.08.2026): Run-Aktionen im Picker verdrahten (TF-Zeile
            # + Pill-Strip voll funktional, User-Entscheid). Die Handler
            # zeigen die Sicherheitsabfrage und starten den ServiceRunWorker
            # mit dem Timeframe aus combo_run_tf (Muster service_win).
            tree.run_service_requested.connect(self._on_run_service)
            tree.run_set_requested.connect(self._on_run_set)
            tree.run_plugin_requested.connect(self._on_run_plugin)
            tree.run_category_requested.connect(self._on_run_category)
        # Live-Sync: Modell-Refresh (EventBus -> data_changed) baut den Baum
        # neu; das Panel wird mit dem zuletzt geklickten Scope nachgezogen.
        self.model.data_changed.connect(self._on_model_data_changed)
        # 18.01.01: Der Host blendet den Speichern-Button des Dialogs ein.
        self._param_host.btn_save_params = self.btn_save_params
        # 08.08.2026 (Bugfix): Host kann den Param-Container nachziehen
        # (Mode-Wechsel/Experten-Kollaps rufen _resize_param_box_deferred)
        # – kein Fenster-Reflow, nur Container-Resize (Scrollbalken).
        self._param_host._dialog = self

        # 20.03.02 (F4): i-Button im MasterTree (ServicePicker) oeffnet den
        # Read-Only ServiceDescriptionDialog.from_plugin()/from_set() –
        # im Gegensatz zum editierbaren ServiceDescriptionEditDialog im
        # ServiceWindow. Kategorie-Ordner zeigen die Ordner-Info analog zur
        # Set-Info (ServiceWindow-Muster _on_category_info_requested).
        self.selector.info_requested.connect(self._on_info_requested)
        self.selector.category_info_requested.connect(
            self._on_category_info_requested)

        # Punkt 4: Letzte Position/Groesse wiederherstellen.
        self._restore_geometry()
        # Panel initial bauen (leer -> Hinweis), damit die Breiten-Logik
        # (Punkte 2+3) vor dem Anzeigen greift.
        self._rebuild_param_panel()
