"""
service_selector_dialog_sets.py - Set-/Ordner-Verwaltung (Anlegen, Umbenennen, Loeschen, Verschieben)

23.08 God-File-Split (15.08.2026): Aus serviceui/service_selector_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der ServiceSelectorDialog-
Klasse als Mixin (Klasse ServiceSelectorDialogSetMixin).
"""

from typing import (
    Any,
    Dict,
)

from PySide6.QtCore import (
    Slot,
)

from PySide6.QtWidgets import (
    QInputDialog,
    QMessageBox,
)

from analytics.engine.service_models import (
    generate_instance_hash,
)

from config.event_bus import (
    event_bus,
)

class ServiceSelectorDialogSetMixin:

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
