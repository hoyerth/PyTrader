"""
serviceui/service_win_tree.py - MasterTree-Handler (Selection, Folder-Operationen, Kategorie-Info)

23.04 God-File-Split (15.08.2026): Aus serviceui/service_win.py extrahiert,
KEINE Logik-Aenderung. Enthaelt die Methoden der ServiceWindow
als Mixin (Klasse ServiceTreeMixin).
"""

from PySide6.QtCore import (
    Slot,
)

from analytics.engine.description_dialog import (
    ServiceDescriptionDialog,
)

from config.event_bus import (
    event_bus,
)

class ServiceTreeMixin:

    @Slot(str, str)
    def _on_master_selection(self, set_id: str, service_id: str) -> None:
        """Laedt das im MasterTree gewaehlte Set direkt in den Parameter-
        Editor (rechte Splitter-Spalte).

        Phase 13-Bereinigung (05.08.2026): Der bisherige Umweg ueber das
        Set-Dropdown der entfernten Service-Sets-Box entfaellt - die
        Auswahl im MasterTree ist die alleinige Quelle. Bei Set-Auswahl
        werden die Parameter-Spalten aufgebaut; ohne Auswahl (Plugin-/
        Standalone-Zeilen) wird der Editor geleert.

        17.01.04 (Bugfix): Bei einer Plugin-Zeile unter 'Services' feuert
        selection_changed mit leeren IDs NACH selection_details. Der
        Plugin-Editor wurde dort bereits geladen (_current_plugin_editing) –
        der Editor darf in diesem Fall NICHT geleert werden."""
        self._set_param_actions_visible(False)
        if not set_id:
            if self._current_plugin_editing:
                return  # Plugin-Editor bleibt (via selection_details geladen)
            self._clear_set_editor()
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        self.load_set_into_editor(definition)

    # -------------------------------------------------------------------------
    # 17.01.04 (Bugfix): Standalone-Plugin-Editor (Parameter-Spalte fuer
    # Plugin-Zeilen unter 'Services' – anzeigen/editieren/speichern wie bei
    # Sets; Persistenz in global_settings, Key 'plugin_params_<pid>').
    # -------------------------------------------------------------------------

    @Slot(str, str, str, str)
    def _on_master_selection_details(self, node_type: str, set_id: str,
                                     service_id: str, plugin_id: str) -> None:
        """Slot fuer `MasterTree.selection_details` (Mausklick in einer Zeile).

        17.01.04 (Bugfix): Klick auf eine Plugin-Zeile (TYPE_PLUGIN) unter
        'Services' (auch in Kategorie-Ordnern) laedt den Standalone-Plugin-
        Editor in die rechte Parameter-Spalte – editierbar, mit Speichern.
        Set-/Service-Zeilen verhalten sich unveraendert (der eigentliche
        Set-Load laeuft ueber selection_changed); hier wird nur der
        Plugin-Modus zurueckgesetzt.
        """
        if node_type in ("plugin", "clone") and plugin_id:
            # 21.01b: Pill-Strip fuer den geklickten Service laden.
            # 12.08.2026: Clone-Knoten tragen den instance_hash im
            # service_id-Slot -> Pills VARIANTEN-GENAU anzeigen.
            self._refresh_badge_bar(
                str(plugin_id),
                str(service_id) if node_type == "clone" else None)
            if node_type == "clone":
                # 10.08.2026 (Bugfix, Varianten-Params): Eine Variante/Clone
                # hat EIGENE Parameter in indicator_presets (20.04, Q7) -
                # der Editor laedt die presetspezifischen Werte statt der
                # globalen Standalone-Parameter (plugin_params_<pid>). Der
                # instance_hash liegt im service_id-Slot (MasterTree.
                # _emit_selection_details).
                self._load_clone_editor(str(plugin_id), str(service_id))
            else:
                self._load_plugin_editor(str(plugin_id))
            return
        # Jede andere Zeile beendet den Plugin-Editor-Modus; der Set-Editor
        # wird weiterhin ueber selection_changed gesteuert (Bestandslogik).
        if self._current_plugin_editing:
            self._current_plugin_editing = None
        if self._current_preset_editing:
            self._current_preset_editing = None
        # 21.01b: Pill-Strip fuer Set-/Service-Zeilen nachziehen (erster
        # Service des Sets bzw. der Service selbst).
        pid_badge, hash_badge = self._resolve_badge_scope(
            node_type, set_id, service_id, plugin_id)
        self._refresh_badge_bar(pid_badge, hash_badge)

    @Slot(str, str)
    def _on_category_info_requested(self, group: str,
                                    category_path: str) -> None:
        """Info-Dialog fuer einen Kategorie-Ordner (17.01.02, wie Set-Info).

        Read-Only-Liste aller Services unter dem Ordner (rekursiv) mit dem
        Kategorie-Pfad als Titel – analog zur Set-Info (ServiceDescription
        Dialog.from_set, keine persistierbare Beschreibung). 18.01.03 (L3):
        `group` unterscheidet Sets- von Plugins-Ordnern (Aufloesung via
        ServiceSelectorModel.category_service_plugin_ids).
        """
        if not category_path:
            return
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return
        plugin_ids = model.category_service_plugin_ids(group, category_path)

        definition = {
            "set_id": f"category_{category_path}",
            "display_name": category_path,
            "description": f"Kategorie-Ordner: {category_path}",
            "execution_order": list(plugin_ids),
            "services": {pid: {"plugin_id": pid} for pid in plugin_ids},
        }
        try:
            dlg = ServiceDescriptionDialog.from_set(definition, parent=self)
            dlg.exec()
        except (RuntimeError, AttributeError) as e:
            self.log(f"Info-Dialog nicht möglich: {e}")

    # -------------------------------------------------------------------------
    # 18.01.03 (Dynamic Tree Management): Kategorie-Drag&Drop & Ordner-CRUD
    # -------------------------------------------------------------------------

    @Slot(str, str, str)
    def _on_folder_item_moved(self, node_type: str, item_id: str,
                              new_path: str) -> None:
        """Drop eines Sets/Plugins in einen Ziel-Ordner (MasterTree).

        Persistiert den neuen Kategorie-Pfad:
          * TYPE_SET    -> Set-Definition (category-Feld) via save_set (E2).
          * TYPE_PLUGIN -> Kategorie-Override (plugin_category_<id>,
                           global_settings – E1).
        18.01.03 (E3-revidiert, Bugfix 08.08.2026): Der QUELL-Ordner
        (und seine Elternkette) wird VOR dem Update ermittelt und nach
        dem Verschieben als Leere-Ordner persistiert
        (ensure_folder_path) – damit bleibt der Ordner sichtbar und
        verschiebbar, wenn sein letztes Kind entzogen wurde.
        Danach EventBus-Sync, damit ALLE MasterTree-Instanzen live
        refreshen (Invariante 5).
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
            model = getattr(self.service_selector, "model", None)
            if model is not None:
                try:
                    source_path = model.plugin_category_path(item_id)
                except Exception:
                    source_path = ""
            ok = set_plugin_category(self.state_manager, item_id, new_path)
        if not ok:
            self.log(f"Kategorie-Verschiebung fehlgeschlagen "
                     f"({node_type} '{item_id}').")
            return
        if source_path:
            ensure_folder_path(self.state_manager, group, source_path)
        event_bus.service_set_changed.emit()

    @Slot(str, str)
    def _on_create_folder(self, group: str, full_path: str) -> None:
        """Kontextmenue 'Neuer Ordner' (create_folder_requested).

        18.01.03 (E3-revidiert, 08.08.2026): Persistiert den
        benutzererzeugten (ggf. leeren) Ordner ueber global_settings
        (service_set_utils.create_empty_folder, Key
        'tree_folders_<group>') und emittiert den EventBus, damit alle
        MasterTree-Instanzen live refreshen (Invariante 5). Leere
        Ordner verschwinden damit NICHT beim Refresh, sondern nur bei
        manueller Loeschung ('Ordner löschen').
        """
        from serviceui.service_set_utils import create_empty_folder
        if not create_empty_folder(self.state_manager,
                                   str(group or ""), full_path):
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str)
    def _on_delete_folder(self, group: str, path: str) -> None:
        """Kontextmenue 'Ordner löschen' (delete_folder_requested).

        18.01.03 (E3-revidiert): Entfernt den persistierten Ordner-
        Eintrag (service_set_utils.delete_empty_folder, Key
        'tree_folders_<group>') und emittiert den EventBus. Der
        MasterTree erlaubt die Aktion nur fuer Ordner ohne Kinder;
        Kinder (falls vorhanden) bleiben unangetastet.
        """
        from serviceui.service_set_utils import delete_empty_folder
        if not delete_empty_folder(self.state_manager,
                                   str(group or ""), path):
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str, str)
    def _on_folder_moved(self, group: str, old_path: str,
                         new_path: str) -> None:
        """Drop eines Ordners auf einen anderen Ordner (MasterTree).

        Verschiebt alle Kinder rekursiv (String-Replace des Pfad-Praefixes
        via service_set_utils.rename_category) und emittiert den EventBus.
        """
        self._rename_folder(group, old_path, new_path)

    @Slot(str, str, str)
    def _on_rename_folder(self, group: str, old_path: str,
                          new_path: str) -> None:
        """Kontextmenue 'Umbenennen' (rename_folder_requested).

        Fuehrt dasselbe String-Replace aus wie der Ordner-Drop
        (_on_folder_moved) – DRY ueber `_rename_folder`.
        """
        self._rename_folder(group, old_path, new_path)

    def _rename_folder(self, group: str, old_path: str,
                       new_path: str) -> None:
        """Zentraler Ordner-Rename (String-Replace aller Kinder).

        18.01.03 (E1/E2): Sets-Ordner aktualisieren das category-Feld der
        Set-Definitionen; Plugins-Ordner setzen Kategorie-Overrides
        (plugin_category_<id>). Nach Aenderung EventBus-Sync.
        """
        from serviceui.service_set_utils import rename_category
        try:
            count = rename_category(
                getattr(self.service_selector, "model", None),
                self.set_repo, self.state_manager,
                str(group or ""), old_path, new_path)
        except Exception as e:
            self.log(f"Ordner-Umbenennung fehlgeschlagen: {e}")
            return
        if count > 0:
            event_bus.service_set_changed.emit()
        self.log(f"Ordner '{old_path}' -> '{new_path}': {count} "
                 f"Element(e) verschoben.")
