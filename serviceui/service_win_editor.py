"""
serviceui/service_win_editor.py - Parameter-/Set-Editor (Plugin-Config, Editor laden, Save, Dirty-State, Set-Editor, Beschreibungen)

23.04 God-File-Split (15.08.2026): Aus serviceui/service_win.py extrahiert,
KEINE Logik-Aenderung. Enthaelt die Methoden der ServiceWindow
als Mixin (Klasse ServiceEditorMixin).
"""

from typing import (
    Any,
    Dict,
    Optional,
)

from PySide6.QtCore import (
    Slot,
)

from PySide6.QtWidgets import (
    QMessageBox,
)

from analytics.engine.description_dialog import (
    ServiceDescriptionEditDialog,
)

from analytics.engine.service_models import (
    generate_instance_hash,
)

from serviceui.service_set_utils import (
    _available_plugin_ids,
    _sets_using_plugin,
)

from config.event_bus import (
    event_bus,
)

# P15-Bugfix: shiboken6.isValid() schuetzt vor dem Zugriff auf bereits
# C++-seitig zerstoerte Qt-Objekte (Access Violation 0xC0000005 bei wildem
# Klicken, wenn z.B. Controls per deleteLater entfernt werden).
try:
    from shiboken6 import isValid as _qt_valid
except ImportError:  # pragma: no cover
    def _qt_valid(obj) -> bool:  # type: ignore
        return obj is not None

class ServiceEditorMixin:

    @Slot(str)
    def _toolbar_add_service(self, plugin_id: str,
                             set_id: Optional[str] = None) -> None:
        """Fuegt einen Service (Plugin) in das Set ein (Kontextmenue
        'Service hinzufuegen' -> eigene Auswahlbox).

        Phase 13-Bereinigung (05.08.2026): Der fruehere Weg ueber das
        Instanz-Eingabefeld der entfernten Service-Sets-Box entfaellt - der
        Service wird direkt ueber die Plugin-Auswahl mit
        Registry-Defaults angelegt (_add_service_to_set)."""
        if not plugin_id:
            return
        target = set_id or self._current_set_id
        if not target:
            self.log("Kein Set geladen - Service kann nicht hinzugefuegt werden.")
            return
        self._add_service_to_set(target, str(plugin_id))

    def _plugin_config(self, plugin_id: str) -> Dict[str, Any]:
        """ServiceInstanceConfig eines Standalone-Plugins.

        Liefert {"plugin_id", "lookback", "params", "version"} – Basis sind
        die Registry-Defaults; gespeicherte Werte aus global_settings
        (Key 'plugin_params_<pid>') ueberschreiben lookback/params und
        ergaenzen eine optionale Beschreibung.
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

    def _load_plugin_editor(self, plugin_id: str) -> None:
        """Laedt die Parameter eines Standalone-Plugins in den Editor.

        Baut eine Ad-hoc-Definition (nur dieser eine Service) aus
        `_plugin_config` und zeigt sie editierbar in der rechten Spalte.
        Der Speicherpfad laeuft bei Aenderungen ueber `_save_plugin_params`
        (global_settings) statt ueber ServiceSetRepository.
        """
        if not plugin_id:
            return
        try:
            from analytics.features.feature_builder import PluginRegistry
            PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden.")
            self._current_plugin_editing = None
            self._current_preset_editing = None
            self._clear_set_editor()
            return
        cfg = self._plugin_config(plugin_id)
        definition: Dict[str, Any] = {
            "set_id": "",
            "display_name": plugin_id,
            "description": str(cfg.get("description") or ""),
            "execution_order": [plugin_id],
            "services": {plugin_id: cfg},
        }
        self._current_plugin_editing = plugin_id
        self._current_preset_editing = None
        self.load_set_into_editor(definition)

    def _load_clone_editor(self, plugin_id: str, instance_hash: str) -> None:
        """Laedt die Parameter einer Variante (Clone) in den Editor.

        10.08.2026 (Bugfix, Varianten-Params): Jede Variante hat EIGENE
        Parameter-Einstellungen in indicator_presets (Kapitel 20.04, Model C).
        Ein Klick auf einen Clone-Knoten darf NICHT die globalen Standalone-
        Parameter (plugin_params_<pid>) laden - der Editor zeigt die
        presetspezifischen Werte. Der Save-Pfad (_save_plugin_params)
        schreibt Aenderungen via save_indicator_preset in das Preset
        (indicator_id, preset_name) zurueck.
        """
        if not plugin_id or not instance_hash:
            return
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            self.log(f"Preset zu #{instance_hash} nicht gefunden.")
            self._current_plugin_editing = None
            self._current_preset_editing = None
            self._clear_set_editor()
            return
        indicator_id = str(preset.get("indicator_id") or "")
        preset_name = str(preset.get("preset_name") or "Default")
        if not indicator_id:
            self.log(f"Preset '{preset_name}' hat keine indicator_id.")
            return
        # Basis = Registry-Defaults + gespeicherte Standalone-Werte; die
        # presetspezifischen Parameter ueberschreiben (Varianten-Params).
        cfg = self._plugin_config(plugin_id)
        preset_params = preset.get("params") or {}
        if isinstance(preset_params, dict) and preset_params:
            merged = dict(cfg.get("params") or {})
            merged.update(preset_params)
            cfg["params"] = merged
        definition: Dict[str, Any] = {
            "set_id": "",
            "display_name": f"{plugin_id} ({preset_name})",
            "description": str(preset.get("doc_log") or ""),
            "execution_order": [plugin_id],
            "services": {plugin_id: cfg},
        }
        self._current_plugin_editing = plugin_id
        # Merke das Preset fuer den Save-Pfad (is_active_batch/doc_log
        # bleiben beim Speichern erhalten).
        self._current_preset_editing = preset
        self.load_set_into_editor(definition)

    def _save_plugin_params(self) -> bool:
        """Persistiert die Parameter des aktuell editierten Standalone-
        Plugins in global_settings (Key 'plugin_params_<pid>').

        Returns: True bei Erfolg (Dirty-Marker entfernt).
        """
        plugin_id = self._current_plugin_editing
        if not plugin_id:
            return False
        definition = self.collect_set_definition()
        services = definition.get("services") or {}
        cfg = next(iter(services.values()), None)
        if not isinstance(cfg, dict):
            self.log(f"FEHLER beim Speichern der Plugin-Parameter: "
                     f"keine Service-Config.")
            return False
        # 10.08.2026 (Bugfix, Varianten-Params): Im Clone-/Preset-Modus wird
        # in indicator_presets gespeichert (eigene Parameter je Variante)
        # statt in global_settings (plugin_params_<pid>).
        preset = self._current_preset_editing
        if isinstance(preset, dict):
            indicator_id = str(preset.get("indicator_id") or "")
            preset_name = str(preset.get("preset_name") or "Default")
            if not indicator_id:
                self.log("Preset hat keine indicator_id - nicht gespeichert.")
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
                self.log(f"FEHLER beim Speichern der Varianten-Parameter: {e}")
                return False
            self._clear_dirty_markers()
            event_bus.service_set_changed.emit()
            self.log(f"Parameter gespeichert (Variante '{preset_name}'): "
                     f"{plugin_id}")
            return True
        data: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": int(cfg.get("lookback") or 1000),
            "params": dict(cfg.get("params") or {}),
            "description": str(cfg.get("description") or ""),
        }
        try:
            self._state_manager.save_global_value(
                f"plugin_params_{plugin_id}", data)
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Plugin-Parameter: {e}")
            return False
        self._clear_dirty_markers()
        # 18.01.01 (E-3): EventBus-Live-Sync - analog zum Set-Speichern
        # (save_set-Pfad) und zum Dialog-Picker, damit alle MasterTree-
        # Instanzen (auch der Analytics-Picker) die Standalone-Parameter
        # bzw. den geaenderten Zustand live uebernehmen.
        event_bus.service_set_changed.emit()
        self.log(f"Parameter gespeichert (Plugin): {plugin_id}")
        return True

    # -------------------------------------------------------------------------
    # Phase 15 (Dirty-State): Parameter-Panel-Aktionsleiste
    # -------------------------------------------------------------------------

    @Slot()
    def _save_params_from_panel(self) -> None:
        """'[💾 Speichern]' – persistiert die aktuellen Parameter-Aenderungen
        des aktiven Sets (ServiceSetRepository.save_set, ohne Neuberechnung),
        entfernt den '*' -Dirty-Marker im Baum und emittiert den EventBus
        (Live-Sync aller ServiceSelectorModel-Instanzen).

        17.01.04: Im Standalone-Plugin-Modus (_current_plugin_editing)
        laeuft die Persistenz ueber global_settings (_save_plugin_params)
        statt ueber ServiceSetRepository.
        """
        if self._current_plugin_editing:
            self._save_plugin_params()
            return
        if not self._current_set_id:
            self.log("Kein Set geladen – Speichern nicht möglich.")
            return
        definition = self.collect_set_definition()
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Parameter: {e}")
            return
        self._clear_dirty_markers()
        event_bus.service_set_changed.emit()
        self.log(f"Parameter gespeichert (P15): {self._current_set_id}")

    @Slot()
    def _save_and_run_from_panel(self) -> None:
        """'[▶️ Speichern & Ausführen]' – speichert die Aenderungen und
        stoesst nach Bestaetigungsabfrage (Symbol/Timeframe) sofort die
        Neuberechnung an.

        Die Neuberechnung laeuft ueber den gezielten ServiceRunWorker
        (FeatureStore-Persistenz + EventBus-Sync): Dadurch wird der
        '*' -Marker entfernt und nach Abschluss das Ausfuehrungsdatum
        '(DD.MM.JJ)' im MasterTree live aktualisiert.

        17.01.04: Im Standalone-Plugin-Modus wird nur der eine Service
        gespeichert (global_settings) und ausgefuehrt.
        """
        if self._current_plugin_editing:
            plugin_id = self._current_plugin_editing
            if not self._save_plugin_params():
                return
            definition = self.collect_set_definition()
            symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
            # U15-E: Zeitachsen-Control der Filterleiste (combo_tf) – kann
            # auch 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
            timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
            reply = QMessageBox.question(
                self, "Speichern & Ausführen",
                f"Plugin '{plugin_id}' wurde gespeichert.\n\n"
                f"Jetzt ausführen?\n"
                f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                f"Der Service wird neu berechnet und der Feature-Store-Payload "
                f"in analytics.duckdb geschrieben.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                self.log("Ausführung abgebrochen (Parameter gespeichert).")
                return
            self._start_run_worker(plugin_id, definition, instance_id=plugin_id)
            return
        if not self._current_set_id:
            self.log("Kein Set geladen – Speichern & Ausführen nicht möglich.")
            return
        definition = self.collect_set_definition()
        if not definition.get("execution_order"):
            self.log("Keine Services in der Ausführungs-Reihenfolge – "
                     "Speichern & Ausführen abgebrochen.")
            return
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Parameter: {e}")
            return
        self._clear_dirty_markers()
        event_bus.service_set_changed.emit()
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Timeframe-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        set_name = str(definition.get("display_name") or self._current_set_id)
        count = len(definition.get("execution_order") or [])
        reply = QMessageBox.question(
            self, "Speichern & Ausführen",
            f"Set '{set_name}' wurde gespeichert.\n\n"
            f"Jetzt ausführen?\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Alle Services ({count}) werden neu berechnet und die "
            f"Feature-Store-Payloads in analytics.duckdb geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen (Parameter gespeichert).")
            return
        self._start_run_worker(self._current_set_id, definition, instance_id=None)

    def _clear_dirty_markers(self) -> None:
        """Entfernt alle '*' -Dirty-Marker im MasterTree (nach Speichern).

        Bugfix 05.08.2026 (Punkt 2): Blendet zusaetzlich die Speicher-
        Buttons aus - ohne manuelle Parameter-Aenderung sind sie nicht
        sichtbar.
        """
        self._set_param_actions_visible(False)
        selector = getattr(self, "service_selector", None)
        tree = getattr(selector, "master_tree", None)
        if tree is None:
            return
        try:
            tree.clear_dirty_markers()
        except (RuntimeError, AttributeError):
            pass

    def _set_param_actions_visible(self, visible: bool) -> None:
        """Blendet die Speicher-Buttons der Parameter-Spalte ein/aus.

        Bugfix 05.08.2026 (Punkt 2/3): Sichtbar NUR bei manueller
        Parameter-Aenderung (Dirty), sonst unsichtbar. Wird von
        _mark_service_dirty (param_columns) eingeblendet und von
        _clear_dirty_markers / _on_master_selection ausgeblendet.
        """
        for name in ("btn_save_params", "btn_save_run_params"):
            btn = getattr(self, name, None)
            if btn is not None:
                try:
                    btn.setVisible(bool(visible))
                except (RuntimeError, AttributeError):
                    pass

    def _plugin_belongs_to_indicator(self, plugin_id: str) -> bool:
        """True, wenn der Service einem Indikator zugeordnet ist
        (metadata['indicator_id']/['indicator_name']).

        Bugfix 05.08.2026: Grundlage der entschaerften P14-04-Sperre –
        nur Indikator-Services sind ueber die 'letztes Vorkommen'-Regel
        geschuetzt, freie Services sind immer loeschbar.
        """
        try:
            model = getattr(getattr(self, "service_selector", None),
                            "model", None)
            if model is not None:
                return bool(model.belongs_to_indicator(plugin_id))
        except (RuntimeError, AttributeError):
            pass
        return False

    def _remaining_sets_with_plugin(self, plugin_id: str,
                                    exclude_set_id: Optional[str]) -> list:
        """GESPEICHERTE Sets (ohne exclude_set_id), die einen Service mit
        plugin_id enthalten – Basis der P14-04-Sperre (Bugfix 05.08.2026:
        Entfernen/Loeschen erlaubt, solange ein gueltiges Set fuer den
        Indikator erhalten bleibt)."""
        return [
            s for s in self.set_repo.list_sets()
            if s.get("set_id") != exclude_set_id
            and any((cfg or {}).get("plugin_id") == plugin_id
                    for cfg in (s.get("services") or {}).values())
        ]

    def _select_set_in_tree(self, set_id: str) -> None:
        """Selektiert ein Set im MasterTree (Bugfix 05.08.2026).

        Loest ueber selection_changed -> _on_master_selection den Editor-Sync
        aus – direkt nach dem Anlegen eines neuen Sets.
        """
        selector = getattr(self, "service_selector", None)
        tree = getattr(selector, "master_tree", None)
        if tree is None or not set_id:
            return
        try:
            from serviceui.master_tree import (
                ROLE_NODE_TYPE, ROLE_SET_ID, TYPE_SET, TreeItemIterator)
            for item in TreeItemIterator(tree):
                if item is None:
                    continue
                if (item.data(0, ROLE_NODE_TYPE) == TYPE_SET and
                        str(item.data(0, ROLE_SET_ID) or "") == set_id):
                    tree.setCurrentItem(item)
                    return
        except (RuntimeError, AttributeError):
            pass

    def _build_new_set_definition(self, name: str,
                                  indicator_id: str) -> Dict[str, Any]:
        """Baut die Definition fuer ein neues Service-Set.

        Bugfix 05.08.2026: Bei Indikator-Auswahl wird die `indicator_id`
        explizit gespeichert und die Basis-Services des Indikators
        (service_plugin_ids, z.B. srv_grid_lines + srv_proximity) werden mit
        Registry-Defaults automatisch angelegt (instance_id = plugin_id) –
        einfache Bedienung und das Set ist sofort gueltig fuer den Indikator.
        """
        definition: Dict[str, Any] = {
            "set_id": "",
            "display_name": name,
            "description": "",
            "execution_order": [],
            "services": {},
        }
        if not indicator_id:
            return definition
        definition["indicator_id"] = indicator_id
        try:
            from analytics.engine.service_selector_model import list_indicators
            info = next(
                (i for i in list_indicators()
                 if str(i.get("indicator_id") or "") == indicator_id),
                None,
            )
        except Exception:
            info = None
        if info is None:
            return definition
        try:
            from analytics.features.feature_builder import PluginRegistry
            registry = PluginRegistry()
        except Exception:
            registry = None
        for pid in (info.get("service_plugin_ids") or []):
            pid = str(pid)
            if not pid or pid in definition["services"]:
                continue
            params: Dict[str, Any] = {}
            if registry is not None:
                try:
                    params = dict(getattr(
                        registry.get(pid), "default_params", {}) or {})
                except (KeyError, AttributeError):
                    params = {}
            lookback: int = 1000
            if "lookback" in params:
                try:
                    lookback = int(params.pop("lookback") or 1000)
                except (TypeError, ValueError):
                    lookback = 1000
            definition["services"][pid] = {
                "plugin_id": pid,
                "lookback": lookback,
                "params": params,
            }
            definition["execution_order"].append(pid)
        return definition

    # =========================================================================
    # Phase 13 Schritt 4: Service-Set-Verwaltung
    # =========================================================================

    def _clear_set_editor(self) -> None:
        """Leert den Set-Zustand (ohne Phase-13-Box: nur interne Felder +
        Parameter-Spalten)."""
        self._current_set_id = None
        self._current_set_definition = None
        # 17.01.04: Auch den Standalone-Plugin-Editor-Modus beenden.
        self._current_plugin_editing = None
        # 10.08.2026 (Bugfix, Varianten-Params): Preset-Modus ebenfalls
        # beenden (sonst wuerde der naechste Save in ein fremdes Preset
        # schreiben).
        self._current_preset_editing = None
        # Phase 15 (Dirty-State): Marker des vorherigen Sets entfernen.
        self._clear_dirty_markers()
        self._clear_service_columns()

    def load_set_into_editor(self, definition: Dict[str, Any]) -> None:
        """Uebernimmt eine ServiceSetDefinition in den internen Zustand und
        baut die dynamischen Service-Spalten (Parameterfenster, rechte
        Splitter-Spalte) neu auf."""
        # Phase 15 (Dirty-State): Marker des vorherigen Sets entfernen - ein
        # frisch geladenes Set ist per Definition unveraendert (kein '*').
        self._clear_dirty_markers()
        self._current_set_id = definition.get("set_id")
        self._current_set_definition = definition
        self._build_service_columns(definition)

    def _next_instance_id(self, services: Dict[str, Any],
                          plugin_id: str) -> str:
        """Liefert die naechste freie instance_id fuer ein Plugin im Set.

        Basis ist der plugin_id selbst (z.B. 'srv_proximity'); bei bereits
        vorhandener Instanz werden '_2', '_3', ... angehaengt."""
        base = plugin_id
        if base not in services:
            return base
        i = 2
        while f"{base}_{i}" in services:
            i += 1
        return f"{base}_{i}"

    def _add_service_to_set(self, set_id: str, plugin_id: str) -> None:
        """Fuegt einen Service (Plugin) mit Registry-Defaults zum Set hinzu.

        Phase 13-Bereinigung (05.08.2026): ersetzt den frueheren
        Eingabe-/Hinzufuegen-Pfad der entfernten Service-Sets-Box.
        Die instance_id wird automatisch vergeben (plugin_id bzw.
        plugin_id_2/_3/...), Duplikate werden dadurch ausgeschlossen.
        Persistiert sofort (set_repo.save_set) + EventBus-Live-Sync."""
        if not set_id or not plugin_id:
            return
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden. "
                     f"Verfuegbare Plugins: {_available_plugin_ids()}")
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
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
            # persistieren, damit NEUE Set-Instanzen von Anfang an die
            # Varianten-Einschraenkung erfuellen (vorher fehlte der Hash
            # beim regularen Hinzufuegen - der MasterTree berechnet ihn fuer
            # Alt-Bestand on-the-fly, neue Instanzen tragen ihn direkt).
            "instance_hash": generate_instance_hash(plugin_id, params),
        }
        order.append(iid)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Service hinzugefuegt: {iid} [{plugin_id}]")
        event_bus.service_set_changed.emit()
        # Aktuelle Editor-Spalten aktualisieren, wenn das Set geladen ist.
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)
    def collect_set_definition(self) -> Dict[str, Any]:
        """Baut aus dem internen Set-Zustand + Parameter-Spalten eine
        ServiceSetDefinition.

        Phase 13-Bereinigung (05.08.2026): Ohne die entfernte Service-Sets-
        Box kommen Name/Beschreibung/Reihenfolge direkt aus der geladenen
        DB-Definition (_current_set_definition); die Werte der dynamischen
        Service-Spalten werden in die services-Konfiguration uebernommen."""
        current = dict(self._current_set_definition or {})
        order = list(current.get("execution_order") or [])
        services = dict(current.get("services") or {})

        # Werte aus den dynamischen Service-Spalten uebernehmen (lookback =
        # Service-Instanz-Einstellung, wird NICHT in params geschrieben).
        for (iid, key), ctrl in self._service_param_controls.items():
            cfg = services.setdefault(
                iid, {"plugin_id": "", "lookback": 1000, "params": {}})
            if key == "lookback":
                cfg["lookback"] = int(self._ctrl_value(ctrl))
            else:
                cfg.setdefault("params", {})[key] = self._ctrl_value(ctrl)

        # Instanz-Beschreibung aus den Spalten uebernehmen
        # (ServiceInstanceConfig.description - gehoert NICHT in params).
        for iid, ctrl in self._service_desc_controls.items():
            cfg = services.setdefault(
                iid, {"plugin_id": "", "lookback": 1000, "params": {}})
            cfg["description"] = ctrl.text().strip()

        # Semantische Versionierung: aktuelle plugin.version einstempeln.
        from analytics.features.feature_builder import PluginRegistry
        registry = PluginRegistry()
        for iid, cfg in services.items():
            pid = cfg.get("plugin_id") or iid
            try:
                plugin = registry.get(pid)
                cfg["version"] = getattr(plugin, "version", "0.0.0") or "0.0.0"
            except KeyError:
                pass

        return {
            "set_id": self._current_set_id or "",
            "display_name": str(current.get("display_name") or ""),
            "description": str(current.get("description") or ""),
            "indicator_id": current.get("indicator_id"),
            "execution_order": order,
            "services": services,
        }
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

    def _service_lock(self, plugin_id: str) -> tuple:
        """P14-04-E: (🔒-Präfix, Tooltip-Nachtrag) für die sichtbare Sperr-
        Kennzeichnung im Service-Fenster.

        Ein Service ist gesperrt, wenn er in einem gespeicherten Service-Set
        vorkommt (Indikator-Basisservice). Liefert ("", "") wenn der Service
        frei ist; andernfalls ein 🔒-Präfix für Listeneintrag/Spaltentitel und
        einen HTML-Tooltip-Nachtrag mit dem Namen des verwendeten Sets.
        """
        names = _sets_using_plugin(str(plugin_id), self.set_repo.list_sets())
        if not names:
            return "", ""
        return "🔒 ", (f"<br><b>Gesperrt (P14-04)</b>: wird vom Service-Set "
                       f"'{names[0]}' verwendet – Entfernen nicht möglich")

    def _open_service_desc_editor(self, instance_id: str) -> None:
        """Oeffnet den modalen ServiceDescriptionEditDialog fuer die Instanz-
        Beschreibung (Stift-Button im Parameter-Panel).

        Phase 16: Bearbeitet AUSSCHLIESSLICH die Instanz-Beschreibung
        (ServiceInstanceConfig.description) – kein Plugin-Metadaten-Fallback,
        keine Verarbeitung von Plugin-Beschreibungen im Service Window.
        """
        if not instance_id:
            return
        cfg: Dict[str, Any] = {}
        if self._current_set_definition:
            cfg = dict((self._current_set_definition.get("services") or {})
                       .get(instance_id, {}))
        desc_ctrl = self._service_desc_controls.get(instance_id)
        if desc_ctrl is not None and _qt_valid(desc_ctrl):
            cfg["description"] = desc_ctrl.text()
        plugin_id = cfg.get("plugin_id") or instance_id
        dlg = ServiceDescriptionEditDialog(
            parent=self,
            instance_id=instance_id,
            plugin_id=plugin_id,
            header_line=self._info_header_tooltip(str(plugin_id)),
            description=str(cfg.get("description") or ""),
            title="Service-Beschreibung bearbeiten",
        )
        dlg.save_requested.connect(
            lambda desc, iid=instance_id:
            self._save_instance_description(self._current_set_id or "", iid, desc))
        dlg.exec()

    def _save_instance_description(self, set_id: str, instance_id: str,
                                   new_desc: str) -> None:
        """Persistiert eine geaenderte Instanz-Beschreibung.

        Phase 16 (05.08.2026): Single Source of Truth – die Instanz-
        Beschreibung gehoert ausschliesslich in
        `ServiceInstanceConfig.description` (JSON-Payload des Service-Sets in
        app_data.duckdb, Feld definition['services'][instance_id]
        ['description']). Kein Plugin-Fallback.

        * Editor-Spalte (QLineEdit) + Tooltip werden live aktualisiert.
        * Persistenz via ServiceSetRepository.save_set() + EventBus.
        """
        clean = (new_desc or "").strip()
        # Live-Update im Editor (setText feuert textChanged → Tooltip-Sync)
        desc_ctrl = self._service_desc_controls.get(instance_id)
        if desc_ctrl is not None and _qt_valid(desc_ctrl):
            desc_ctrl.setText(clean)
        # In der geladenen Definition nachziehen (sofortige Folge-Speicherung)
        if self._current_set_definition is not None:
            cfg = (self._current_set_definition.get("services") or {}).get(instance_id)
            if isinstance(cfg, dict):
                cfg["description"] = clean
        # 17.01.04: Standalone-Plugin-Editor – Beschreibung in die Plugin-
        # Konfiguration (global_settings) uebernehmen statt in ein Set.
        if self._current_plugin_editing:
            if self._save_plugin_params():
                self.log(f"Instanz-Beschreibung '{instance_id}' gespeichert "
                         f"(Plugin).")
            return
        if not set_id:
            self.log(f"Instanz-Beschreibung '{instance_id}' aktualisiert "
                     f"(Set noch nicht gespeichert).")
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Beschreibung nicht "
                     f"gespeichert.")
            return
        services = definition.get("services") or {}
        if instance_id in services:
            services[instance_id]["description"] = clean
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
            event_bus.service_set_changed.emit()
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Instanz-Beschreibung: {e}")
            return
        # Phase 15 (Dirty-State): explizites Set-Speichern -> '*' entfernen.
        self._clear_dirty_markers()
        self.log(f"Instanz-Beschreibung '{instance_id}' gespeichert.")

    def _save_set_description(self, set_id: str, new_desc: str) -> None:
        """Persistiert die Set-Beschreibung (ServiceSetDefinition.description).

        Phase 16 (05.08.2026): analog zur Instanz-Beschreibung – Single
        Source of Truth ist das JSON-Payload des Sets in app_data.duckdb.
        """
        clean = (new_desc or "").strip()
        if self._current_set_definition is not None and \
                self._current_set_definition.get("set_id") == set_id:
            self._current_set_definition["description"] = clean
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Beschreibung nicht "
                     f"gespeichert.")
            return
        definition["description"] = clean
        try:
            self.set_repo.save_set(definition)
            event_bus.service_set_changed.emit()
        except Exception as e:
            self.log(f"FEHLER beim Speichern der Set-Beschreibung: {e}")
            return
        # Phase 15 (Dirty-State): explizites Set-Speichern -> '*' entfernen.
        self._clear_dirty_markers()
        self.log(f"Set-Beschreibung '{set_id}' gespeichert.")
