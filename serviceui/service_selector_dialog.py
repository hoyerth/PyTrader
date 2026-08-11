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

from typing import Any, Dict, List, Optional

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
    """Mixin-Host fuer das Parameter-Panel des Dialogs.

    `ServiceParamColumnsMixin._build_service_column()` erwartet Host-
    Attribute des ServiceWindow (Parameter-Controls, Sperr-Lookup usw.).
    Dieser Host stellt die benoetigten Attribute/Methoden bereit:

      * Read-Only-Anzeige (Sets/Indikator-Services): deaktivierte QGroupBox,
        kein Dirty-Tracking (kein Speichern).
      * 18.01.01 (E-3/E-4): Standalone-Services (`belongs_to_indicator ==
        False`) werden EDITIERBAR gerendert – Parameter laufen in
        global_settings (Key 'plugin_params_<pid>'), der Speichern-Button
        des Dialogs wird bei Aenderungen eingeblendet (_set_param_actions_
        visible) und `_save_plugin_params()` persistiert + emittiert
        `event_bus.service_set_changed` (Live-Sync aller MasterTree).
    """

    def __init__(self, state_manager=None) -> None:
        self._service_param_controls: Dict[str, Any] = {}
        self._service_desc_controls: Dict[str, Any] = {}
        # 08.08.2026 (Bugfix): `ServiceParamColumnsMixin._build_service_column`
        # schreibt auch in diese Registrys (Conditional-Visibility-Schema je
        # Instanz, Form-Label-Referenzen, Info-Labels) – ohne Init schlaegt die
        # Parameteranzeige mit 'AttributeError: _mode_schemas' fehl.
        self._mode_schemas: Dict[str, Any] = {}
        self._service_param_labels: Dict[str, Any] = {}
        self._service_info_labels: Dict[str, Any] = {}
        self._service_info_pids: Dict[str, Any] = {}
        # 20.03.01 (Bugfix): `ServiceParamColumnsMixin._build_service_column`
        # schreibt seit dem Output-Schema-Umbau auch in diese Registry –
        # ohne Init schlaegt die Parameteranzeige mit 'AttributeError:
        # _service_output_schemas' fehl (analog _mode_schemas, 08.08.2026).
        self._service_output_schemas: Dict[str, Any] = {}
        self._symbol_precision: Optional[int] = None
        self.combo_symbol = None
        self.combo_tf = None
        # 18.01.01: Standalone-Editierung im Dialog-Kontext.
        self._state_manager = state_manager
        self._current_plugin_editing: Optional[str] = None
        self._current_set_definition: Optional[Dict[str, Any]] = None
        # 10.08.2026 (Bugfix, Varianten-Params): Wird ein Clone-Knoten
        # (Preset/Variante) editiert, haelt dieses Feld das Preset-Dict aus
        # indicator_presets - _save_plugin_params schreibt dann in das
        # Preset statt in global_settings (plugin_params_<pid>).
        self._current_preset_editing: Optional[Dict[str, Any]] = None
        #: Speichern-Button des Dialogs (wird nach dem UI-Aufbau gesetzt).
        self.btn_save_params: Optional[QPushButton] = None

    def _service_lock(self, plugin_id: str):
        """Keine Set-Sperre im Dialog (kein Set-Editing hier)."""
        return "", ""

    def _open_service_desc_editor(self, instance_id: str) -> None:
        """Read-Only: kein Beschreibungs-Editor im Dialog."""
        pass

    def _schedule_reflow(self) -> None:
        """Kein Fenster-Reflow (Param-Panel skaliert nicht)."""
        pass

    def _resize_param_box_deferred(self) -> None:
        """08.08.2026 (Bugfix): Dialog-Variante statt ServiceWindow-No-op.

        `_setup_collapsible` (Experten-Optionen) und
        `_apply_conditional_visibility` (Mode-Wechsel) rufen diese Methode
        nach Aenderungen der Spaltenhoehe. Hier wird der Param-Container des
        Dialogs auf seine Layout-Groesse nachgezogen – die ScrollArea zeigt
        bei Ueberhoehe Scrollbalken, die Dialog-Fensterhoehe bleibt FIX
        (ServiceWindow-Muster 07.08.2026).
        """
        dlg = getattr(self, "_dialog", None)
        if dlg is not None:
            try:
                dlg._resize_param_container_deferred()
            except (RuntimeError, AttributeError):
                pass

    def _set_param_actions_visible(self, visible: bool) -> None:
        """Blendet den Speichern-Button des Dialogs ein/aus (Dirty-State)."""
        btn = self.btn_save_params
        if btn is not None:
            try:
                btn.setVisible(bool(visible))
            except (RuntimeError, AttributeError):
                pass

    def _plugin_config(self, plugin_id: str) -> Dict[str, Any]:
        """ServiceInstanceConfig eines Standalone-Plugins (service_win-Muster).

        Basis sind die Registry-Defaults; gespeicherte Werte aus
        global_settings (Key 'plugin_params_<pid>') ueberschreiben
        lookback/params und ergaenzen eine optionale Beschreibung.
        """
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            plugin = None
        params = dict(getattr(plugin, "default_params", None) or {}) if plugin else {}
        lookback: int = 1000
        if "lookback" in params:
            try:
                lookback = int(params.pop("lookback") or 1000)
            except (TypeError, ValueError):
                lookback = 1000
        cfg: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": lookback,
            "params": params,
            "version": getattr(plugin, "version", "0.0.0") or "0.0.0",
        }
        if self._state_manager is not None:
            try:
                saved = self._state_manager.get_global_value(
                    f"plugin_params_{plugin_id}", None)
            except Exception:
                saved = None
            if isinstance(saved, dict):
                lb = saved.get("lookback")
                if lb is not None:
                    try:
                        cfg["lookback"] = int(lb)
                    except (TypeError, ValueError):
                        pass
                saved_params = saved.get("params")
                if isinstance(saved_params, dict):
                    merged = dict(params)
                    merged.update(saved_params)
                    cfg["params"] = merged
                desc = saved.get("description")
                if desc:
                    cfg["description"] = str(desc)
        return cfg

    def _save_plugin_params(self) -> bool:
        """Persistiert die Parameter des editierbaren Standalone-Plugins.

        global_settings (Key 'plugin_params_<pid>') + EventBus-Sync
        (`service_set_changed`, 18.01.01 E-3) – so synchronisieren alle
        ServiceSelectorModel-Instanzen den MasterTree live.

        Wie `collect_set_definition` in service_win wird die individuelle
        Instanz-Beschreibung aus dem Beschreibungs-Control uebernommen
        (`_service_desc_controls`), damit auch Beschreibungs-Aenderungen
        persistiert werden (nicht nur lookback/params).
        """
        plugin_id = self._current_plugin_editing
        if not plugin_id or self._state_manager is None:
            return False
        definition = self._current_set_definition or {}
        services = definition.get("services") or {}
        cfg = next(iter(services.values()), None)
        if not isinstance(cfg, dict):
            return False
        # 10.08.2026 (Bugfix, Varianten-Params): Im Clone-/Preset-Modus wird
        # in indicator_presets gespeichert (eigene Parameter je Variante)
        # statt in global_settings (plugin_params_<pid>).
        preset = self._current_preset_editing
        if isinstance(preset, dict):
            indicator_id = str(preset.get("indicator_id") or "")
            preset_name = str(preset.get("preset_name") or "Default")
            if not indicator_id:
                return False
            try:
                self._state_manager.save_indicator_preset(
                    indicator_id, preset_name,
                    dict(cfg.get("params") or {}),
                    plugin_id=plugin_id,
                    version=str(cfg.get("version")
                                or preset.get("version") or "0.0.0"),
                    is_active_batch=bool(preset.get("is_active_batch")),
                    doc_log=str(preset.get("doc_log") or ""),
                )
            except Exception as e:
                print(f"WARN [ServiceSelectorDialog] Varianten-Parameter "
                      f"nicht gespeichert: {e}")
                return False
            self._set_param_actions_visible(False)
            event_bus.service_set_changed.emit()
            return True
        description = str(cfg.get("description") or "")
        desc_ctrl = self._service_desc_controls.get(plugin_id)
        if desc_ctrl is not None:
            try:
                description = str(desc_ctrl.text()).strip()
            except (RuntimeError, AttributeError):
                pass
        data: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": int(cfg.get("lookback") or 1000),
            "params": dict(cfg.get("params") or {}),
            "description": description,
        }
        try:
            self._state_manager.save_global_value(
                f"plugin_params_{plugin_id}", data)
        except Exception as e:
            print(f"WARN [ServiceSelectorDialog] Plugin-Parameter nicht "
                  f"gespeichert: {e}")
            return False
        self._set_param_actions_visible(False)
        event_bus.service_set_changed.emit()
        return True


class ServiceSelectorDialog(QDialog):
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

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------
    def apply_feature_ids(self, feature_ids: List[str],
                          instance_hashes=None) -> None:
        """Spiegelt die aktuelle ViewModel-Auswahl im Baum (Reverse-Mapping).

        Wird beim Oeffnen des Dialogs gerufen, damit ein restauriertes
        Profil bzw. der aktive Filter im Checkbox-Baum sichtbar ist.
        Runde 10 (Bug 1): instance_hashes (Varianten) werden ebenfalls
        auf den Baum gemappt - nur die passenden Clone-Varianten werden
        angehakt (Hash-Granularitaet).
        """
        tree = self.selector.master_tree
        if tree is not None:
            tree.set_checked_feature_ids(
                list(feature_ids or []), list(instance_hashes or []))

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
        # Bugfix-Runde 3 (06.08.2026): Filter entfernen leert auch das
        # Klick-Panel (kein Scope mehr, Hinweis-Text).
        self._last_scope = None
        self._rebuild_param_panel([])
        self.services_selected.emit([], [])

    def _on_apply(self) -> None:
        """Emittiert `services_selected(display_names, feature_ids)` und zu."""
        self.services_selected.emit(
            self.current_display_names(),
            self.current_feature_ids(),
        )
        self.accept()

    # ------------------------------------------------------------------
    # 20.03.02 (F4): i-Button im MasterTree -> Read-Only-Beschreibung
    # ------------------------------------------------------------------
    @Slot(str, str, str)
    def _on_info_requested(self, set_id: str, service_id: str,
                           plugin_id: str) -> None:
        """Info-Button im MasterTree (ServicePicker, 20.03.02 F4).

        Read-Only `ServiceDescriptionDialog.from_plugin()` bzw.
        `from_set()` (kein Editieren – der editierbare
        `ServiceDescriptionEditDialog` bleibt dem ServiceWindow
        vorbehalten). `header_line` im vereinheitlichten F5-Format
        ('📌 im <Indikator> | 🟢 aktiv in <Indikator>' / '⚪ inaktiv').
        """
        try:
            if service_id and set_id:
                cfg = self.model.find_service(set_id, service_id) or {}
                pid = str(cfg.get("plugin_id") or service_id)
                plugin = self._resolve_info_plugin(pid)
                if plugin is None:
                    return
                dlg = ServiceDescriptionDialog.from_plugin(
                    plugin, instance_id=service_id, config=cfg, parent=self,
                    header_line=self._info_header_line(pid))
                dlg.exec()
            elif plugin_id and not service_id:
                plugin = self._resolve_info_plugin(plugin_id)
                if plugin is None:
                    return
                dlg = ServiceDescriptionDialog.from_plugin(
                    plugin, parent=self,
                    header_line=self._info_header_line(plugin_id))
                dlg.exec()
            elif set_id and not service_id:
                definition = self.model.find_set(set_id)
                if not definition:
                    return
                dlg = ServiceDescriptionDialog.from_set(
                    definition, parent=self,
                    header_line=self._info_set_header_line(definition))
                dlg.exec()
        except (RuntimeError, AttributeError):
            pass

    @Slot(str, str)
    def _on_category_info_requested(self, group: str,
                                    category_path: str) -> None:
        """Info-Dialog fuer einen Kategorie-Ordner (20.03.02, F4).

        Analog zur Set-Info (ServiceDescriptionDialog.from_set, keine
        persistierbare Beschreibung): Read-Only-Liste aller Services unter
        dem Ordner (rekursiv) mit dem Kategorie-Pfad als Titel
        (ServiceWindow-Muster _on_category_info_requested).
        """
        if not category_path:
            return
        try:
            plugin_ids = self.model.category_service_plugin_ids(
                group, category_path)
            definition = {
                "set_id": f"category_{category_path}",
                "display_name": category_path,
                "description": f"Kategorie-Ordner: {category_path}",
                "execution_order": list(plugin_ids),
                "services": {pid: {"plugin_id": pid} for pid in plugin_ids},
            }
            dlg = ServiceDescriptionDialog.from_set(definition, parent=self)
            dlg.exec()
        except (RuntimeError, AttributeError):
            pass

    def _resolve_info_plugin(self, plugin_id: str):
        """Registry-Lookup fuer den Info-Dialog (defensiv, ohne KeyError)."""
        try:
            from analytics.features.feature_builder import PluginRegistry
            return PluginRegistry().get(plugin_id)
        except KeyError:
            return None

    def _info_header_line(self, plugin_id: str) -> str:
        """Erste Dialog-Zeile fuer Plugin-/Service-Zeilen (20.03.02, F5).

        Vereinheitlichtes Badge-Format ('📌 im <Indikator> | 🟢 aktiv in
        <Indikator>' / '⚪ inaktiv'); leer ohne Indikator-Zugehoerigkeit.
        """
        model = self.model
        if model is None or not model.belongs_to_indicator(plugin_id):
            return ""
        name = model.get_indicator_display_name(plugin_id)
        if model.is_active_in_chart(plugin_id):
            return f"📌 im {name} | 🟢 aktiv in {name}"
        return f"📌 im {name} | ⚪ inaktiv"

    def _info_set_header_line(self, set_def: Dict[str, Any]) -> str:
        """Erste Dialog-Zeile fuer Set-Zeilen (20.03.02, F5).

        Vereinheitlichtes Badge-Format; mehrere Indikatoren mit ' + '
        verknuepft.
        """
        model = self.model
        if model is None:
            return ""
        names = model.get_set_indicator_names(set_def or {})
        if not names:
            return ""
        label = " + ".join(names)
        if model.is_set_active(set_def or {}):
            return f"📌 im {label} | 🟢 aktiv in {label}"
        return f"📌 im {label} | ⚪ inaktiv"

    # ------------------------------------------------------------------
    # 18.01.01 (E-4): Live-Verwaltung (Set/Service-CRUD im Picker)
    # ------------------------------------------------------------------
    @Slot()
    def _on_save_plugin_params(self) -> None:
        """Speichern-Button: persistiert die editierbaren Standalone-Params."""
        if not self._param_host._save_plugin_params():
            QMessageBox.warning(
                self, "Fehler",
                "Parameter konnten nicht gespeichert werden "
                "(kein editierbarer Standalone-Service ausgewählt).")

    # ------------------------------------------------------------------
    # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im Kontextmenue – Handler
    # (Muster service_win, ohne Editor-Load/Logging; der Dialog ist ein
    # Read-Only-Picker, aber die Duplizierung/Loeschung muss funktionieren).
    # ------------------------------------------------------------------

    def _find_preset_for_hash(self, plugin_id: str,
                              instance_hash: str):
        """Preset-Dict zu plugin_id + instance_hash (indicator_presets)."""
        try:
            sm = self.model.state_manager
            for preset in sm.list_plugin_presets(plugin_id) or []:
                if not isinstance(preset, dict):
                    continue
                from analytics.engine.service_models import (
                    generate_instance_hash)
                # 11.08.2026 (Bugfix Varianten-Kollision): Hash eines
                # Presets inkl. preset_name (identisch zu Modell/Run);
                # Legacy-Fallback fuer Alt-Bestand.
                preset_name = str(preset.get("preset_name") or "Default")
                if (generate_instance_hash(plugin_id,
                                           preset.get("params") or {},
                                           preset_name=preset_name)
                        == instance_hash
                        or generate_instance_hash(
                            plugin_id, preset.get("params") or {})
                        == instance_hash):
                    return preset
        except Exception:
            pass
        return None

    @Slot(str, str, str, str)
    def _on_duplicate_variant(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Als Variante duplizieren' (20.04, Q8) – Muster service_win."""
        try:
            if set_id and service_id:
                self._duplicate_set_instance(set_id, service_id)
                return
            if plugin_id:
                self._duplicate_preset(plugin_id, instance_hash)
                return
        except (RuntimeError, AttributeError):
            pass

    @Slot(str, str, str)
    def _on_rename_variant(self, plugin_id: str, instance_hash: str,
                           new_name: str) -> None:
        """'Variante umbenennen' (10.08.2026, Bugfix) – Picker-Variante.

        Persistiert den Rename in indicator_presets (indicator_id,
        preset_name) mit Kollisionspruefung. Die Feature-Store-Daten
        (Spalte instance_hash) bleiben unberuehrt. Der Picker nutzt
        QMessageBox-Warnungen statt des ServiceWindow-Loggings.
        """
        try:
            sm = self.model.state_manager
        except Exception:
            return
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            QMessageBox.warning(
                self, "Umbenennen",
                f"Preset zu #{instance_hash} nicht gefunden.")
            return
        old_name = str(preset.get("preset_name") or "Default")
        indicator_id = str(preset.get("indicator_id") or "")
        if not indicator_id:
            QMessageBox.warning(
                self, "Umbenennen",
                "Preset hat keine indicator_id – Umbenennen abgebrochen.")
            return
        clean = (new_name or "").strip()
        if not clean or clean == old_name:
            return
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if clean in existing:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Eine andere Variante von '{plugin_id}' heisst bereits "
                f"'{clean}'.")
            return
        try:
            sm.rename_indicator_preset(indicator_id, old_name, clean)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _next_preset_copy_name(self, plugin_id: str, base: str) -> str:
        """Naechster freier Preset-Name '<base> (Kopie)', '(Kopie 2)', ..."""
        try:
            sm = self.model.state_manager
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if base not in existing:
            return base
        candidate = f"{base} (Kopie)"
        i = 2
        while candidate in existing:
            i += 1
            candidate = f"{base} (Kopie {i})"
        return candidate

    def _duplicate_set_instance(self, set_id: str, service_id: str) -> None:
        """Dupliziert eine Service-Instanz in ihrem Set (Q8)."""
        if self.set_repo is None:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception:
            return
        if not definition:
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id)
        if not isinstance(cfg, dict):
            return
        pid = str(cfg.get("plugin_id") or service_id)
        iid = self._next_instance_id(services, pid)
        copy = dict(cfg)
        copy["params"] = dict(cfg.get("params") or {})
        from analytics.engine.service_models import generate_instance_hash
        copy["instance_hash"] = generate_instance_hash(pid, copy["params"])
        copy.pop("description", None)
        copy.pop("doc_log", None)
        services[iid] = copy
        order = list(definition.get("execution_order") or [])
        order.append(iid)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception:
            return
        event_bus.service_set_changed.emit()

    def _duplicate_preset(self, plugin_id: str, instance_hash: str) -> None:
        """Dupliziert einen Plugin-Clone als neues Preset (Q8)."""
        try:
            sm = self.model.state_manager
        except Exception:
            return
        base = "Default"
        params = {}
        indicator_id = plugin_id
        version = "1.0.0"
        if instance_hash:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset is None:
                return
            base = str(preset.get("preset_name") or "Default")
            params = dict(preset.get("params") or {})
            indicator_id = str(preset.get("indicator_id") or plugin_id)
            version = preset.get("version") or "1.0.0"
        else:
            # Flaches Plugin-Blatt: aktuelle Standalone-Parameter.
            try:
                raw = sm.get_global_value(f"plugin_params_{plugin_id}", {})
            except Exception:
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            params = dict(raw.get("params") or {})
            version = raw.get("version") or "1.0.0"
        # 10.08.2026 (Bugfix): Beim Anlegen einer neuen Variante MUSS ein
        # neuer Name vergeben werden – der Dialog ist mit dem freien
        # Kopiernamen vorbelegt; Kollisionen werden abgefangen.
        suggested = self._next_preset_copy_name(plugin_id, base)
        new_name, ok = QInputDialog.getText(
            self, "Variante anlegen",
            f"Name für die neue Variante (aus '{base}'):", text=suggested)
        new_name = (new_name or "").strip()
        if not ok or not new_name:
            return
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if new_name in existing:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Eine andere Variante von '{plugin_id}' heisst bereits "
                f"'{new_name}'.")
            return
        try:
            sm.save_indicator_preset(
                indicator_id, new_name, params,
                plugin_id=plugin_id,
                version=version,
                # Q8-Bugfix: Kopie IMMER batch-aktiv (nicht Erbe vom
                # Quell-Preset), damit Scans/LiveAnalyzer sie berechnen.
                is_active_batch=True,
                doc_log="",
            )
        except Exception:
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_data_only_purge(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Data Only Löschen' (Q5): Feature-Daten purgen, Struktur bleibt."""
        if not instance_hash:
            return
        reply = QMessageBox.question(
            self, "Data Only Löschen",
            f"Feature-Daten der Variante #{instance_hash} löschen?\n"
            "Struktur, Parameter und Doc-Log bleiben erhalten.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            from analytics.features.feature_builder import FeatureBuilder
            FeatureBuilder().purge_instance_data(instance_hash)
        except Exception:
            pass
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_delete_complete(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Vollständig Löschen': Preset/Instanz + Daten entfernen."""
        try:
            sm = self.model.state_manager
        except Exception:
            return
        if set_id and service_id and self.set_repo is not None:
            try:
                definition = self.set_repo.get_set(set_id)
            except Exception:
                return
            if not definition:
                return
            services = dict(definition.get("services") or {})
            cfg = services.get(service_id)
            if not isinstance(cfg, dict):
                return
            label = str(cfg.get("plugin_id") or service_id)
            reply = QMessageBox.question(
                self, "Vollständig Löschen",
                f"Instanz '{service_id}' aus Set '{set_id}' vollständig "
                "löschen?\n\nDas Preset wird entfernt UND die "
                "berechneten Feature-Daten gelöscht.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            services.pop(service_id, None)
            order = [i for i in (definition.get("execution_order") or [])
                     if i != service_id]
            definition["execution_order"] = order
            definition["services"] = services
            try:
                self.set_repo.save_set(definition)
            except Exception:
                return
            if instance_hash:
                try:
                    from analytics.features.feature_builder import (
                        FeatureBuilder)
                    FeatureBuilder().purge_instance_data(instance_hash)
                except Exception:
                    pass
            event_bus.service_set_changed.emit()
            return
        if plugin_id and instance_hash:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset is None:
                return
            preset_name = str(preset.get("preset_name") or "Default")
            indicator_id = str(preset.get("indicator_id") or "")
            reply = QMessageBox.question(
                self, "Vollständig Löschen",
                f"Preset '{preset_name}' von '{plugin_id}' vollständig "
                "löschen?\n\nDas Preset wird entfernt UND die "
                "berechneten Feature-Daten gelöscht.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            if sm is not None and indicator_id:
                try:
                    sm.delete_indicator_preset(indicator_id, preset_name)
                except Exception:
                    return
            if instance_hash:
                try:
                    from analytics.features.feature_builder import (
                        FeatureBuilder)
                    FeatureBuilder().purge_instance_data(instance_hash)
                except Exception:
                    pass
            event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_doc_log_requested(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Doc Log bearbeiten' (Q7) – Read-Only-Hinweis im Picker.

        Der Dialog ist ein Read-Only-Datenquellen-Picker ohne Editor – die
        vollstaendige Doc-Log-Bearbeitung uebernimmt das ServiceWindow. Hier
        wird eine kurze Info angezeigt, damit der Menuepunkt nicht wirkungslos
        bleibt.
        """
        try:
            if set_id and service_id:
                QMessageBox.information(
                    self, "Doc Log",
                    "Die Doc-Log-Bearbeitung erfolgt im ServiceWindow "
                    "(Kontextmenü der Instanz).")
                return
            if plugin_id and instance_hash:
                preset = self._find_preset_for_hash(plugin_id, instance_hash)
                doc = str((preset or {}).get("doc_log") or "")
                QMessageBox.information(
                    self, "Doc Log",
                    f"Doc Log von '{plugin_id}':\n\n{doc or '(leer)'}\n\n"
                    "Bearbeitung im ServiceWindow (Kontextmenü des Clones).")
                return
        except (RuntimeError, AttributeError):
            pass

    def _next_instance_id(self, services: Dict[str, Any],
                          plugin_id: str) -> str:
        """Naechste freie instance_id fuer ein Plugin im Set (service_win-
        Muster): Basis ist die plugin_id, bei Belegung '_2', '_3', ..."""
        base = plugin_id
        if base not in services:
            return base
        i = 2
        while f"{base}_{i}" in services:
            i += 1
        return f"{base}_{i}"

    def _add_service_to_set(self, set_id: str, plugin_id: str) -> None:
        """Fuegt einen Service (Plugin) mit Registry-Defaults zum Set hinzu
        und persistiert sofort (set_repo + EventBus-Live-Sync)."""
        if not set_id or not plugin_id or self.set_repo is None:
            return
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            QMessageBox.warning(
                self, "Fehler", f"Plugin '{plugin_id}' nicht gefunden.")
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            return
        services = dict(definition.get("services") or {})
        order = list(definition.get("execution_order") or [])
        iid = self._next_instance_id(services, plugin_id)
        params = dict(getattr(plugin, "default_params", None) or {})
        lookback = 1000
        if "lookback" in params:
            try:
                lookback = int(params.pop("lookback") or 1000)
            except (TypeError, ValueError):
                lookback = 1000
        services[iid] = {
            "plugin_id": plugin_id,
            "lookback": lookback,
            "params": params,
            "version": getattr(plugin, "version", "0.0.0") or "0.0.0",
            # Runde 13b (Bugfix Dropdown-NoData): instance_hash mit
            # persistieren (analog service_win._add_service_to_set).
            "instance_hash": generate_instance_hash(plugin_id, params),
        }
        order.append(iid)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _on_create_set(self) -> None:
        """Kontextmenue 'Neues Set anlegen' (Pickername-Dialog)."""
        name, ok = QInputDialog.getText(self, "Neues Service-Set", "Set-Name:")
        name = (name or "").strip()
        if not ok or not name:
            return
        definition: Dict[str, Any] = {
            "set_id": "",
            "display_name": name,
            "description": "",
            "execution_order": [],
            "services": {},
        }
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _on_rename_set(self, set_id: str) -> None:
        """Kontextmenue 'Set umbenennen' (Namensdialog, Kollisionspruefung)."""
        if not set_id or self.set_repo is None:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            return
        current_name = str(definition.get("display_name") or "")
        name, ok = QInputDialog.getText(
            self, "Set umbenennen",
            f"Neuer Name für das Service-Set '{current_name}':",
            text=current_name,
        )
        if not ok:
            return
        clean = (name or "").strip()
        if not clean:
            QMessageBox.warning(self, "Fehler", "Der Name darf nicht leer sein.")
            return
        collision = any(
            (s.get("display_name") or "") == clean and s.get("set_id") != set_id
            for s in self.set_repo.list_sets())
        if collision:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Ein anderes Service-Set heißt bereits '{clean}'.")
            return
        definition["display_name"] = clean
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _on_add_set_service(self, set_id: str) -> None:
        """Kontextmenue 'Service hinzufügen' (Plugin-Auswahlbox)."""
        if not set_id:
            return
        ids = sorted(self.model.get_plugins().keys())
        if not ids:
            QMessageBox.information(
                self, "Service hinzufügen", "Keine Services verfügbar.")
            return
        pid, ok = QInputDialog.getItem(
            self, "Service hinzufügen", "Service wählen:", ids, 0, False)
        if not ok or not pid:
            return
        self._add_service_to_set(set_id, str(pid))

    def _on_delete_set(self, set_id: str) -> None:
        """Kontextmenue 'Set löschen' (Rueckfrage, Soft-Delete/Papierkorb)."""
        if not set_id or self.set_repo is None:
            return
        reply = QMessageBox.question(
            self, "Set löschen",
            f"Service-Set '{set_id}' wirklich löschen (in den Papierkorb)?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            self.set_repo.delete_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _on_move_service(self, set_id: str, service_id: str, delta: int) -> None:
        """Kontextmenue 'Order ▲/▼' (execution_order verschieben)."""
        if not set_id or not service_id or self.set_repo is None:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            return
        order = list(definition.get("execution_order") or [])
        if service_id not in order:
            return
        i = order.index(service_id)
        j = i + delta
        if j < 0 or j >= len(order):
            return
        order[i], order[j] = order[j], order[i]
        definition["execution_order"] = order
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _on_remove_service(self, set_id: str, service_id: str) -> None:
        """Kontextmenue 'Service entfernen' (Rueckfrage, direkter Entzug)."""
        if not set_id or not service_id or self.set_repo is None:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            return
        reply = QMessageBox.question(
            self, "Service entfernen",
            f"Service '{service_id}' aus dem Set entfernen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        services = dict(definition.get("services") or {})
        order = [i for i in (definition.get("execution_order") or [])
                 if i != service_id]
        services.pop(service_id, None)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    # ------------------------------------------------------------------
    # 18.01.03 (Dynamic Tree Management): Kategorie-Drag&Drop & Ordner-CRUD
    # im Picker (Manager-Window). Persistenz analog service_win ueber die
    # gemeinsamen Helfer service_set_utils (DRY, E1/E2).
    # ------------------------------------------------------------------
    @Slot(str, str, str)
    def _on_folder_item_moved(self, node_type: str, item_id: str,
                              new_path: str) -> None:
        """Drop eines Sets/Plugins in einen Ziel-Ordner (MasterTree).

        TYPE_SET    -> category-Feld der Set-Definition (E2).
        TYPE_PLUGIN -> Kategorie-Override plugin_category_<id> (E1).
        18.01.03 (E3-revidiert, Bugfix 08.08.2026): Der QUELL-Ordner
        (und seine Elternkette) wird VOR dem Update ermittelt und nach dem
        Verschieben als Leere-Ordner persistiert (ensure_folder_path) –
        damit bleibt der Ordner sichtbar, wenn sein letztes Kind entzogen
        wurde. Danach EventBus-Sync (Live-Refresh aller MasterTrees).
        """
        from serviceui.master_tree import TYPE_PLUGIN, TYPE_SET
        from serviceui.service_set_utils import (
            ensure_folder_path, set_plugin_category, set_set_category)
        source_path = ""
        group = ""
        ok = False
        if node_type == TYPE_SET:
            group = "sets"
            try:
                definition = self.set_repo.get_set(item_id) or {}
                source_path = str(definition.get("category") or "").strip().strip("/")
            except Exception:
                source_path = ""
            ok = set_set_category(self.set_repo, item_id, new_path)
        elif node_type == TYPE_PLUGIN:
            group = "plugins"
            try:
                source_path = self.model.plugin_category_path(item_id)
            except Exception:
                source_path = ""
            ok = set_plugin_category(self._state_manager, item_id, new_path)
        if not ok:
            print(f"WARN [ServiceSelectorDialog] Kategorie-Verschiebung "
                  f"fehlgeschlagen ({node_type} '{item_id}').")
            return
        if source_path:
            ensure_folder_path(self._state_manager, group, source_path)
        event_bus.service_set_changed.emit()

    @Slot(str, str)
    def _on_create_folder(self, group: str, full_path: str) -> None:
        """Kontextmenue 'Neuer Ordner' (create_folder_requested).

        18.01.03 (E3-revidiert, 08.08.2026): Persistiert den
        benutzererzeugten (ggf. leeren) Ordner ueber global_settings
        (service_set_utils.create_empty_folder, Key 'tree_folders_<group>')
        und emittiert den EventBus. Leere Ordner verschwinden damit NICHT
        beim Refresh, sondern nur bei manueller Loeschung.
        """
        from serviceui.service_set_utils import create_empty_folder
        if not create_empty_folder(self._state_manager,
                                   str(group or ""), full_path):
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str)
    def _on_delete_folder(self, group: str, path: str) -> None:
        """Kontextmenue 'Ordner löschen' (delete_folder_requested).

        18.01.03 (E3-revidiert): Entfernt den persistierten Ordner-Eintrag
        (service_set_utils.delete_empty_folder, Key 'tree_folders_<group>')
        und emittiert den EventBus. Der MasterTree erlaubt die Aktion nur
        fuer Ordner ohne Kinder; Kinder bleiben unangetastet.
        """
        from serviceui.service_set_utils import delete_empty_folder
        if not delete_empty_folder(self._state_manager,
                                   str(group or ""), path):
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str, str)
    def _on_folder_moved(self, group: str, old_path: str,
                         new_path: str) -> None:
        """Drop eines Ordners auf einen anderen Ordner (MasterTree)."""
        self._rename_folder(group, old_path, new_path)

    @Slot(str, str, str)
    def _on_rename_folder(self, group: str, old_path: str,
                          new_path: str) -> None:
        """Kontextmenue 'Umbenennen' (rename_folder_requested)."""
        self._rename_folder(group, old_path, new_path)

    def _rename_folder(self, group: str, old_path: str,
                       new_path: str) -> None:
        """Zentraler Ordner-Rename (String-Replace aller Kinder).

        18.01.03 (E1/E2): Sets-Ordner aktualisieren das category-Feld der
        Set-Definitionen; Plugins-Ordner setzen Kategorie-Overrides.
        """
        from serviceui.service_set_utils import rename_category
        try:
            count = rename_category(
                self.model, self.set_repo, self._state_manager,
                str(group or ""), old_path, new_path)
        except Exception as e:
            print(f"WARN [ServiceSelectorDialog] Ordner-Umbenennung "
                  f"fehlgeschlagen: {e}")
            return
        if count > 0:
            event_bus.service_set_changed.emit()

    # ------------------------------------------------------------------
    # Read-Only-Parameter-Panel (Punkte 1-3: horizontal, 2-Spalten-Default,
    # Fensterbreite == rechte Kante der Parameter-Box)
    # ------------------------------------------------------------------
    @Slot()
    def _on_checked_changed(self) -> None:
        """Live-Filter bei Checkbox-Aenderungen im Picker (10.08.2026).

        Ein An-/Abhaken aktualisiert sofort die Datenquellen des
        AnalyticsWindow (selection_ids_requested -> set_feature_ids) -
        dadurch erneuern sich auch die Resultatparameter-Dropdowns
        (heatmap field/agg etc.). Das Read-Only-Panel folgt weiterhin der
        GEKLICKTEN Zeile (Punkte 1-7), nicht den Haken.
        """
        tree = self.selector.master_tree
        if tree is None:
            return
        try:
            ids = list(tree.checked_feature_ids() or [])
            hashes = list(tree.checked_instance_hashes() or [])
        except (RuntimeError, AttributeError):
            return
        self.selection_ids_requested.emit(ids)
        self.selection_hashes_requested.emit(hashes)

    def _on_tree_selection_details(self, node_type: str, set_id: str,
                                   service_id: str, plugin_id: str) -> None:
        """Slot fuer `MasterTree.selection_details` (Mausklick in einer Zeile).

        Bugfix-Runde 3 (06.08.2026, Punkte 1-7): Das Panel folgt der
        GEKLICKTEN Zeile, NICHT den Checkboxen (analog service_win
        `_on_master_selection`):

          * Set-Zeile ODER Service-Zeile IN einem Set -> ALLE Services des
            Sets nebeneinander (`_entries_for_scope`, Punkt 4+5).
          * Plugin-Zeile (⚡ Standalone / 📦 Plugins) -> NUR dieser eine
            Service (Punkt 6).
          * Kategorie-Ordner (18.01.01, E-4) -> ALLE Elemente des Pfads
            (rekursiv). 18.01.03 (L3): Sets-Ordner (set_id == 'sets')
            liefern die Service-Spalten aller Sets unter dem Pfad,
            Plugins-Ordner die Plugin-Spalten (category_plugin_ids).
          * Gruppen-/sonstige Zeilen -> KEIN Service (Punkt 7).

        10.08.2026 (Bugfix, Punkt 1+2): Der LIVE-FILTER folgt
        AUSSCHLIESSLICH den Checkboxen (`checked_changed` ->
        `_on_checked_changed` -> `selection_ids_requested` mit
        `checked_feature_ids()`) - der Zeilen-Klick steuert NUR das Panel.
        Vorher emittierte dieser Handler beim Klick zusaetzlich
        `selection_ids_requested` mit dem Zeilen-Scope und ueberschrieb
        damit den angehakten Filter (feature_ids der Historie/des Profils
        entsprach dem letzten Klick statt den Haken; die
        Ergebnisparameter-Dropdowns folgten dem Klick statt den Haken).
        Standalone-Services (belongs_to_indicator == False) sind editierbar
        (plugin_params_<id>), alle anderen Zeilen bleiben read-only.
        """
        self._last_scope = (node_type, set_id, service_id, plugin_id)
        # 10.08.2026 (Bugfix, Punkt 1+2): KEIN selection_ids_requested mehr -
        # der Filter folgt den Checkboxen (checked_changed), nicht dem Klick.
        # Ein Klick darf den angehakten Filter nicht ueberschreiben (sonst
        # speichern Historie/Profil den letzten Klick statt der Haken).
        editable = None
        if node_type in (TYPE_PLUGIN, TYPE_CLONE) and plugin_id:
            if not self.model.belongs_to_indicator(str(plugin_id)):
                editable = str(plugin_id)
        self._rebuild_param_panel(
            self._entries_for_scope(node_type, set_id, service_id, plugin_id),
            editable_plugin=editable)
        # 21.01b: Pill-Strip dem geklickten Service nachziehen.
        self._refresh_badge_bar(
            self._resolve_badge_plugin(node_type, set_id,
                                       service_id, plugin_id))

    def _resolve_selection_ids(self, node_type: str, set_id: str,
                               service_id: str, plugin_id: str) -> List[str]:
        """Loest eine geklickte Baum-Zeile in feature_ids (plugin_ids) auf.

        18.01.01 (E-4): Klick auf Set -> alle Services des Sets; Klick auf
        Kategorie-Ordner -> rekursive Aufloesung; Klick auf Plugin-Zeile ->
        [plugin_id]; Service-Zeile -> [plugin_id des Service]. 18.01.03
        (L3): Fuer Kategorie-Ordner traegt set_id die Eltern-GRUPPE
        ('sets'/'plugins', aus MasterTree._emit_selection_details) – die
        Aufloesung unterscheidet damit Sets-Ordner (Sets unter dem Pfad ->
        deren Service-plugin_ids) von Plugins-Ordnern (category_plugin_ids).
        """
        if node_type == TYPE_CATEGORY:
            return self.model.category_service_plugin_ids(
                set_id or "", plugin_id or "")
        if node_type in (TYPE_PLUGIN, TYPE_CLONE) and plugin_id:
            # 20.04 (Q7): Clone-Zeilen loesen auf die plugin_id des
            # Plugin-Parents auf (Filter bleibt feature_id IN (plugin_ids)).
            return [str(plugin_id)]
        if node_type == TYPE_SERVICE and set_id and service_id:
            cfg = self.model.find_service(set_id, service_id) or {}
            pid = str(cfg.get("plugin_id") or service_id)
            return [pid] if pid else []
        if node_type == TYPE_SET and set_id:
            definition = self.model.find_set(set_id) or {}
            services = definition.get("services") or {}
            order = definition.get("execution_order") or list(services.keys())
            ids: List[str] = []
            for iid in order:
                cfg = services.get(iid) or {}
                pid = str(cfg.get("plugin_id") or iid)
                if pid and pid not in ids:
                    ids.append(pid)
            return ids
        return []

    # ------------------------------------------------------------------
    # 21.01b (11.08.2026): Run im Picker (TF-Zeile + Pill-Strip)
    # ------------------------------------------------------------------
    def _run_symbol(self) -> str:
        """Aktives Symbol aus dem Parent (AnalyticsWindow.combo_symbol)."""
        parent = self.parent()
        cb = getattr(parent, "combo_symbol", None)
        if cb is not None:
            try:
                txt = cb.currentText()
            except Exception:
                txt = ""
            if txt:
                return str(txt)
        return "SILVER"

    def _run_timeframe(self) -> str:
        """Gewaehlter Run-Timeframe (Sentinel = Multi-TF im Worker)."""
        combo = getattr(self, "combo_run_tf", None)
        if combo is None:
            return ALL_TIMEFRAMES
        return str(combo.currentText() or ALL_TIMEFRAMES)

    def _fill_run_tf_combo(self) -> None:
        """Befuellt combo_run_tf: Sentinel 'ALLE Timeframes' + alle TFs
        aufsteigend nach Dauer (M1..MN1, wie combo_tf im ServiceWindow)."""
        combo = getattr(self, "combo_run_tf", None)
        if combo is None:
            return
        try:
            from db_service import TF_SECONDS_MAP, get_timeframes
            try:
                tfs = list(get_timeframes().keys())
            except Exception:
                tfs = list(TF_SECONDS_MAP.keys())
            sort_map = TF_SECONDS_MAP
        except Exception:
            tfs = ["M1", "M2", "M5", "M10", "M15", "M30",
                   "H1", "H4", "D1", "W1", "MN1"]
            sort_map = {}
        tfs = sorted(tfs, key=lambda tf: sort_map.get(tf, 10 ** 12))
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(ALL_TIMEFRAMES)
        for tf in tfs:
            if tf != ALL_TIMEFRAMES:
                combo.addItem(tf)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _plugin_config(self, plugin_id: str) -> Dict[str, Any]:
        """Standalone-Plugin-Config wie im ServiceWindow (17.01.04-Muster).
        Basis sind die Registry-Defaults; gespeicherte Werte aus
        global_settings (Key 'plugin_params_<pid>') ueberschreiben."""
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            plugin = None
        params = dict(getattr(plugin, "default_params", None) or {}) \
            if plugin else {}
        lookback: int = 1000
        if "lookback" in params:
            try:
                lookback = int(params.pop("lookback") or 1000)
            except (TypeError, ValueError):
                lookback = 1000
        cfg: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": lookback,
            "params": params,
            "version": getattr(plugin, "version", "0.0.0") or "0.0.0",
        }
        try:
            saved = self._state_manager.get_global_value(
                f"plugin_params_{plugin_id}", None)
        except Exception:
            saved = None
        if isinstance(saved, dict):
            lb = saved.get("lookback")
            if lb is not None:
                try:
                    cfg["lookback"] = int(lb)
                except (TypeError, ValueError):
                    pass
            saved_params = saved.get("params")
            if isinstance(saved_params, dict):
                merged = dict(cfg["params"])
                merged.update(saved_params)
                cfg["params"] = merged
        return cfg

    def _start_run_worker(self, scope_id: str, set_definition: Dict[str, Any],
                          instance_id: Optional[str]) -> None:
        """Startet den gezielten ServiceRunWorker (Single/Set) mit dem
        Timeframe aus combo_run_tf – Muster service_win._start_run_worker."""
        if self._run_worker is not None and self._run_worker.isRunning():
            QMessageBox.information(
                self, "Service-Ausführung",
                "Eine Service-Ausführung läuft bereits.")
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        self._run_worker = ServiceRunWorker(
            self.set_evaluator, symbol, timeframe, set_definition,
            instance_id=instance_id, parent=self,
        )
        self._run_worker.log_message.connect(self._on_run_log)
        self._run_worker.run_finished.connect(self._on_run_worker_finished)
        self._run_worker.run_failed.connect(self._on_run_worker_failed)
        # 21.01b: Per-TF-Signale -> Pill-Strip (Laufzeit-/Fehler-Zustand).
        self._run_worker.tf_started.connect(self._on_tf_started)
        self._run_worker.tf_finished.connect(self._on_tf_finished)
        self._run_worker.start()

    def _on_run_log(self, message: str) -> None:
        try:
            print(f"[ServicePicker] {message}")
        except Exception:
            pass

    def _on_run_service(self, set_id: str, service_id: str) -> None:
        """'▶️ Diesen Service ausführen' (Picker-MasterTree)."""
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            QMessageBox.warning(
                self, "Service ausführen",
                f"Set '{set_id}' nicht gefunden.")
            return
        if service_id not in (definition.get("services") or {}):
            QMessageBox.warning(
                self, "Service ausführen",
                f"Service '{service_id}' nicht im Set '{set_id}'.")
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        set_name = str(definition.get("display_name") or set_id)
        reply = QMessageBox.question(
            self, "Service ausführen",
            f"Service '{service_id}' aus dem Set '{set_name}' ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Der erzeugte Feature-Store-Payload wird in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._start_run_worker(service_id, definition, instance_id=service_id)

    def _on_run_set(self, set_id: str) -> None:
        """'▶️ Alle Services ausführen' (Picker-MasterTree)."""
        if not set_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            QMessageBox.warning(
                self, "Set ausführen", f"Set '{set_id}' nicht gefunden.")
            return
        if not definition.get("execution_order"):
            QMessageBox.information(
                self, "Set ausführen", f"Set '{set_id}' hat keine Services.")
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        set_name = str(definition.get("display_name") or set_id)
        count = len(definition.get("execution_order") or [])
        reply = QMessageBox.question(
            self, "Set ausführen",
            f"Alle Services ({count}) des Sets '{set_name}' ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Die erzeugten Feature-Store-Payloads werden in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        self._start_run_worker(set_id, definition, instance_id=None)

    def _on_run_plugin(self, plugin_id: str, instance_hash: str = "") -> None:
        """'▶️ Diesen Service ausführen' (Plugin-/Clone-Zeile).

        11.08.2026 (Bugfixing, Varianten-Run): `instance_hash` wird vom
        MasterTree-Kontextmenue mitgeliefert – Clone-Zeilen laufen NUR mit
        den Parametern + Hash der Variante; Plugin-Zeilen mit Presets
        laufen ALLE aktiven Varianten (Bug 1/2/3).
        """
        if not plugin_id:
            return
        sm = getattr(self, "_state_manager", None)
        entries = variant_run_entries(plugin_id, sm, self._plugin_config)
        if not entries:
            return
        if instance_hash:
            entries = [e for e in entries
                       if e[1].get("instance_hash") == instance_hash]
            if not entries:
                entries = [(plugin_id, self._plugin_config(plugin_id))]
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        single = len(entries) == 1
        if single:
            _iid, _cfg = entries[0]
            _name = str(_cfg.get("preset_name") or plugin_id)
            title = "Service ausführen"
            text = (f"Service '{plugin_id}' (Variante '{_name}') ausführen?\n\n"
                    f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                    f"Der erzeugte Feature-Store-Payload wird in analytics.duckdb "
                    f"geschrieben.")
        else:
            title = "Alle Varianten ausführen"
            text = (f"Alle Varianten ({len(entries)}) von '{plugin_id}' "
                    f"ausführen?\n\n"
                    f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                    f"Die erzeugten Feature-Store-Payloads werden in "
                    f"analytics.duckdb geschrieben.")
        reply = QMessageBox.question(
            self, title, text, QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        definition = {
            "set_id": f"plugin_{plugin_id}",
            "display_name": plugin_id,
            "execution_order": [e[0] for e in entries],
            "services": {e[0]: e[1] for e in entries},
        }
        self._start_run_worker(
            plugin_id, definition,
            instance_id=entries[0][0] if single else None)

    def _on_run_category(self, group: str, category_path: str) -> None:
        """'▶️ Alle Services ausführen' (Kategorie-Ordner, rekursiv)."""
        if not category_path:
            return
        model = getattr(self, "model", None)
        if model is None:
            return
        plugin_ids = model.category_service_plugin_ids(group, category_path)
        if not plugin_ids:
            QMessageBox.information(
                self, "Alle Services ausführen",
                f"Kategorie '{category_path}' hat keine Services.")
            return
        # 11.08.2026 (Bugfixing, Bug 3): Plugins MIT Presets -> ALLE aktiven
        # Varianten werden ausgefuehrt (jede mit eigenen Parametern + Hash).
        sm = getattr(self, "_state_manager", None)
        entries_all: List[tuple] = []
        for pid in plugin_ids:
            entries_all.extend(variant_run_entries(pid, sm, self._plugin_config))
        if not entries_all:
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        count = len(entries_all)
        reply = QMessageBox.question(
            self, "Alle Services ausführen",
            f"Alle Services ({count}) der Kategorie '{category_path}' "
            f"ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Die erzeugten Feature-Store-Payloads werden in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        definition = {
            "set_id": f"category_{category_path}",
            "display_name": category_path,
            "execution_order": [e[0] for e in entries_all],
            "services": {e[0]: e[1] for e in entries_all},
        }
        self._start_run_worker(category_path, definition, instance_id=None)

    def _on_run_worker_finished(self, scope_id: str, stored: int) -> None:
        """Run abgeschlossen: Pill-Strip zuruecksetzen + Status neu laden."""
        self._on_run_log(f"Ausführung abgeschlossen: {stored} Feature-Row(s) "
                         f"im feature_store gespeichert ({scope_id}).")
        self.badge_bar.set_running(None)
        self._refresh_badge_bar()

    def _on_run_worker_failed(self, scope_id: str, error: str) -> None:
        """Run fehlgeschlagen: Pill-Strip zuruecksetzen + Status neu laden."""
        self._on_run_log(f"FEHLER bei Ausführung ({scope_id}): {error}")
        self.badge_bar.set_running(None)
        self._refresh_badge_bar()

    def _on_tf_started(self, tf: str) -> None:
        """Hebt den gerade laufenden Timeframe im Pill-Strip blau hervor."""
        self.badge_bar.set_running(tf)
        self.badge_bar.clear_error(tf)

    def _on_tf_finished(self, tf: str, stored: int, had_data: bool) -> None:
        """TF fertig: ohne OHLCV-Daten/Fehler rot markieren, sonst neutral."""
        if had_data:
            self.badge_bar.clear_error(tf)
        else:
            self.badge_bar.set_error(tf)
        self.badge_bar.set_running(None)

    def _resolve_badge_plugin(self, node_type: str, set_id: str,
                              service_id: str,
                              plugin_id: str) -> Optional[str]:
        """Ermittelt die plugin_id fuer den Pill-Strip einer Baum-Zeile."""
        if plugin_id:
            return str(plugin_id)
        if node_type == TYPE_SERVICE:
            if set_id and service_id:
                cfg = self.model.find_service(set_id, service_id) or {}
                return str(cfg.get("plugin_id") or service_id)
            return str(service_id) if service_id else None
        if node_type == TYPE_SET and set_id:
            definition = self.model.find_set(set_id) or {}
            order = list(definition.get("execution_order") or [])
            services = dict(definition.get("services") or {})
            for iid in order:
                cfg = services.get(iid) or {}
                pid = str(cfg.get("plugin_id") or iid)
                if pid:
                    return pid
        return None

    def _refresh_badge_bar(self, plugin_id: Optional[str] = None) -> None:
        """Laedt die TF-Status-Pills fuer den angegebenen Service neu
        (FeatureStoreReader.fetch_service_tf_status)."""
        if plugin_id:
            self._badge_plugin_id = plugin_id
        pid = self._badge_plugin_id
        if not pid:
            self.badge_bar.clear()
            return
        try:
            status = FeatureStoreReader().fetch_service_tf_status(pid)
        except Exception:
            status = {}
        self.badge_bar.update_status(status)

    def _on_model_data_changed(self) -> None:
        """Modell-Refresh (EventBus -> data_changed): Panel neu aufbauen.

        Nach einem Baum-Neuaufbau (neues Set, Ausfuehrungsdatum, ...) wird
        das Panel mit dem zuletzt GEKLICKTEN Scope nachgezogen; ohne Scope
        (noch nichts angeklickt) bleibt das Panel leer.
        """
        scope = getattr(self, "_last_scope", None)
        if scope:
            self._on_tree_selection_details(*scope)
        else:
            self._rebuild_param_panel([])

    def _entries_for_scope(self, node_type: str, set_id: str, service_id: str,
                           plugin_id: str) -> List[Dict[str, str]]:
        """Panel-Entries fuer die geklickte Tree-Zeile (service_win-Muster).

        Returns:
            Liste von {"node_type", "set_id", "instance_id", "plugin_id"} –
            leer fuer Zeilen ohne Parameter-Anzeige (Gruppen, leere Auswahl).
            Kategorie-Ordner (18.01.01, E-4) liefern die Elemente des Pfads
            rekursiv; 18.01.03 (L3) unterscheidet dabei ueber die im set_id-
            Slot mitgelieferte Gruppe: Sets-Ordner -> Set-Service-Entries
            aller Sets unter dem Pfad, Plugins-Ordner -> Plugin-Entries
            (category_plugin_ids).
        """
        if node_type == TYPE_CATEGORY:
            if str(set_id or "") == str(self.model.GROUP_SETS):
                entries: List[Dict[str, str]] = []
                for set_id_under in self.model.category_set_ids(
                        plugin_id or ""):
                    definition = self.model.find_set(set_id_under) or {}
                    services = definition.get("services") or {}
                    order = definition.get("execution_order") \
                        or list(services.keys())
                    for iid in order:
                        cfg = services.get(iid) or {}
                        if not isinstance(cfg, dict):
                            continue
                        entries.append({
                            "node_type": TYPE_SERVICE,
                            "set_id": str(set_id_under),
                            "instance_id": str(iid),
                            "plugin_id": str(cfg.get("plugin_id") or iid),
                        })
                return entries
            entries: List[Dict[str, str]] = []
            for pid in self.model.category_plugin_ids(plugin_id or ""):
                entries.append({
                    "node_type": TYPE_PLUGIN,
                    "set_id": "",
                    "instance_id": "",
                    "plugin_id": pid,
                })
            return entries
        if node_type in (TYPE_PLUGIN, TYPE_CLONE) and plugin_id:
            # 20.04 (Q7): Clone-Zeilen zeigen wie Plugin-Zeilen den
            # Standalone-Service (feature_id = plugin_id des Parents).
            # 10.08.2026 (Bugfix, Varianten-Params): Zusaetzlich werden die
            # presetspezifischen Parameter (indicator_presets) mitgegeben -
            # das Panel zeigt die EIGENEN Parameter der Variante (service_id
            # traegt hier den instance_hash, MasterTree._emit_selection_-
            # details), nicht die globalen Standalone-Params.
            if node_type == TYPE_CLONE:
                preset = self._find_preset_for_hash(
                    plugin_id, service_id)
                if preset is not None:
                    return [{
                        "node_type": TYPE_PLUGIN,
                        "set_id": "",
                        "instance_id": "",
                        "plugin_id": str(plugin_id),
                        "preset_params": dict(preset.get("params") or {}),
                        "preset": preset,
                    }]
            return [{
                "node_type": TYPE_PLUGIN,
                "set_id": "",
                "instance_id": "",
                "plugin_id": str(plugin_id),
            }]
        if node_type in (TYPE_SET, TYPE_SERVICE) and set_id:
            definition = self.model.find_set(set_id) or {}
            services = definition.get("services") or {}
            order = definition.get("execution_order") or list(services.keys())
            entries: List[Dict[str, str]] = []
            for iid in order:
                cfg = services.get(iid) or {}
                if not isinstance(cfg, dict):
                    continue
                entries.append({
                    "node_type": TYPE_SERVICE,
                    "set_id": str(set_id),
                    "instance_id": str(iid),
                    "plugin_id": str(cfg.get("plugin_id") or iid),
                })
            return entries
        return []

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
