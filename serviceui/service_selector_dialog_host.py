"""
serviceui/service_selector_dialog_host.py - _DialogParamHost (Mixin-Host fuer das Param-Panel)

23.08 God-File-Split (15.08.2026): Aus serviceui/service_selector_dialog.py
extrahiert, KEINE Logik-Aenderung. Wird von __init__ UND den Mixin-Methoden
_on_save_plugin_params/_rebuild_param_panel/_clear_panel genutzt - eigene
Datei, damit die Hauptdatei sie re-exportieren kann (kein Zirkularimport).
"""

from PySide6.QtWidgets import QPushButton
from analytics.engine.service_selector_model import ServiceSelectorModel
from config.event_bus import event_bus
from serviceui.param_columns import ServiceParamColumnsMixin

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
