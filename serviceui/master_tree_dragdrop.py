"""
master_tree_dragdrop.py - Drag & Drop (MIME, Drop-Target, Ordner-CRUD-Dialoge)

23.06 God-File-Split (15.08.2026): Aus serviceui/master_tree.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der MasterTree-
Klasse als Mixin (Klasse MasterTreeDragDropMixin).
"""

import json

from PySide6.QtCore import (
    QMimeData,
    Qt,
)

from PySide6.QtGui import (
    QDrag,
)

from PySide6.QtWidgets import (
    QInputDialog,
)

from serviceui.master_tree_constants import (
    MIME_CATEGORY_MOVE,
    ROLE_ARCHIVED,
    ROLE_INSTANCE_HASH,
    ROLE_NODE_TYPE,
    ROLE_PLUGIN_ID,
    ROLE_PRESET_NAME,
    ROLE_SET_ID,
    TYPE_CATEGORY,
    TYPE_GROUP,
    TYPE_PLUGIN,
    TYPE_SET,
    isValid,
)

class MasterTreeDragDropMixin:

    def _drag_id(self, item) -> str:
        """Eindeutige ID eines ziehbaren Knotens fuer die MIME-Daten.

        Sets -> set_id (ROLE_SET_ID), Plugins -> plugin_id (ROLE_PLUGIN_ID),
        Kategorie-Ordner -> voller Kategorie-Pfad (_category_path_of).
        """
        node_type = item.data(0, ROLE_NODE_TYPE)
        if node_type == TYPE_CATEGORY:
            return self._category_path_of(item)
        if node_type == TYPE_SET:
            return str(item.data(0, ROLE_SET_ID) or "")
        if node_type == TYPE_PLUGIN:
            return str(item.data(0, ROLE_PLUGIN_ID) or "")
        return ""

    def startDrag(self, supported_actions) -> None:
        """Startet den internen Kategorie-Drag (18.01.03, E4).

        Ueberschrieben, damit NUR Sets/Plugins/Ordner gezogen werden
        (kein Service-Reorder – E4) und die Ziel-Informationen als JSON-MIME
        transportiert werden (Ordner sind nicht selektierbar, daher liefert
        der Qt-Default-Mime aus selectedItems() nicht die Quelle).
        """
        item = getattr(self, "_drag_source", None)
        if item is None or not isValid(item):
            super().startDrag(supported_actions)
            return
        node_type = item.data(0, ROLE_NODE_TYPE)
        if node_type not in (TYPE_SET, TYPE_PLUGIN, TYPE_CATEGORY):
            super().startDrag(supported_actions)
            return
        # 20.04 (Q6): Archivierte Knoten sind nicht ziehbar (Archive
        # Safety) – sie duerfen nicht in normale Kategorie-Ordner wandern.
        if item.data(0, ROLE_ARCHIVED):
            super().startDrag(supported_actions)
            return
        try:
            payload = {
                "node_type": node_type,
                "group": self._group_of(item),
                "id": self._drag_id(item),
                "path": (self._category_path_of(item)
                         if node_type == TYPE_CATEGORY else ""),
            }
            mime = QMimeData()
            mime.setData(MIME_CATEGORY_MOVE,
                         json.dumps(payload).encode("utf-8"))
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.MoveAction, Qt.MoveAction)
        except (RuntimeError, AttributeError):
            pass
        finally:
            self._drag_source = None

    def dragEnterEvent(self, event) -> None:
        """Akzeptiert nur den eigenen Kategorie-Move-MIME (18.01.03)."""
        try:
            if event.mimeData().hasFormat(MIME_CATEGORY_MOVE):
                event.acceptProposedAction()
                return
        except (RuntimeError, AttributeError):
            pass
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        """Akzeptiert den eigenen Kategorie-Move-MIME waehrend des Drags."""
        try:
            if event.mimeData().hasFormat(MIME_CATEGORY_MOVE):
                event.acceptProposedAction()
                return
        except (RuntimeError, AttributeError):
            pass
        super().dragMoveEvent(event)

    def _drop_target(self, item) -> tuple:
        """Bestimmt (Gruppe, Ziel-Kategorie-Pfad) fuer ein Drop-Ziel-Item.

        * Gruppe (TYPE_GROUP)  -> ("sets"/"plugins", "" = Root-Ebene)
        * Ordner (TYPE_CATEGORY) -> (Eltern-Gruppe, Ordner-Pfad)
        * Blatt (Set/Service/Plugin) -> (Eltern-Gruppe, Pfad des naechsten
          Kategorie-Vorfahren; "" wenn direkt unter der Gruppe)
        Liefert ("", "") wenn kein gueltiges Ziel gefunden wird (18.01.03).
        """
        if item is None or not isValid(item):
            return "", ""
        node_type = item.data(0, ROLE_NODE_TYPE)
        if node_type == TYPE_GROUP:
            return str(item.data(0, ROLE_SET_ID) or ""), ""
        if node_type == TYPE_CATEGORY:
            return self._group_of(item), self._category_path_of(item)
        # Blatt: zum naechsten Kategorie-Vorfahren (oder zur Gruppe) wandern.
        node = item.parent()
        hops = 0
        while node is not None and isValid(node) and hops < 64:
            nt = node.data(0, ROLE_NODE_TYPE)
            if nt == TYPE_CATEGORY:
                return self._group_of(node), self._category_path_of(node)
            if nt == TYPE_GROUP:
                return str(node.data(0, ROLE_SET_ID) or ""), ""
            node = node.parent()
            hops += 1
        return "", ""

    def dropEvent(self, event) -> None:
        """Verarbeitet den Kategorie-Drop (18.01.03).

        Der Baum fuehrt KEINEN echten Item-Move aus – es werden nur die
        Signale folder_item_moved (Set/Plugin) bzw. folder_moved (Ordner)
        emittiert; der Orchestrator persistiert den Kategorie-Pfad ueber
        Modell/Repositories und der naechste Refresh baut den Baum neu.
        Guards:
          * Nur der eigene MIME wird verarbeitet (sonst Qt-Default).
          * Gruppen-Mismatch (Set in Plugins-Ordner ziehen) -> abgelehnt.
          * Ordner-Zyklus (Ordner in seinen eigenen Unterordner) -> abgelehnt.
        """
        if not event.mimeData().hasFormat(MIME_CATEGORY_MOVE):
            super().dropEvent(event)
            return
        try:
            payload = json.loads(
                bytes(event.mimeData().data(MIME_CATEGORY_MOVE)).decode("utf-8"))
        except (ValueError, TypeError):
            event.ignore()
            return
        source_type = str(payload.get("node_type") or "")
        source_group = str(payload.get("group") or "")
        source_id = str(payload.get("id") or "")
        source_path = str(payload.get("path") or "")
        try:
            pos = (event.position().toPoint() if hasattr(event, "position")
                   else event.pos())
        except AttributeError:
            pos = event.pos()
        target = self.itemAt(pos)
        target_group, target_path = self._drop_target(target)
        if not target_group:
            event.ignore()
            return
        # 20.04 (Q6): Der Archiv-Ordner ist kein Drag-Ziel (Archive Safety).
        # Kategorie-Pfad 'Archiv' (ohne '📁 '-Praefix) wird abgelehnt.
        if str(target_path or "").strip().lower().startswith("archiv"):
            event.ignore()
            return
        if source_group and source_group != target_group:
            event.ignore()
            return
        if source_type == TYPE_CATEGORY:
            # Ordner-Verschiebung: Zyklus-Schutz (eigener Unterordner).
            if (not source_path or target_path == source_path
                    or target_path.startswith(source_path + "/")):
                event.ignore()
                return
            # 18.01.03 (Bugfix 08.08.2026): Ziel-Ordnerkette fuer den
            # folgenden Refresh zum Aufklappen merken (VOR dem emit).
            self._mark_expand(source_group, target_path)
            self.folder_moved.emit(source_group, source_path, target_path)
            event.accept()
            return
        if source_type in (TYPE_SET, TYPE_PLUGIN) and source_id:
            # 18.01.03 (Bugfix 08.08.2026): Ziel-Ordnerkette fuer den
            # folgenden Refresh zum Aufklappen merken (VOR dem emit).
            self._mark_expand(target_group, target_path)
            self.folder_item_moved.emit(source_type, source_id, target_path)
        event.accept()

    def _on_new_folder(self, group: str, parent_path: str) -> None:
        """Kontextmenue 'Neuer Ordner' (18.01.03, E3-revidiert).

        Fragt den Namen ab und emittiert `create_folder_requested(group,
        full_path)` – der Orchestrator PERSISTIERT den (ggf. leeren) Ordner
        ueber global_settings (service_set_utils.create_empty_folder,
        Key 'tree_folders_<group>'). Damit bleibt der Ordner ueber Refreshs
        erhalten und verschwindet nur bei manueller Loeschung im
        Kontextmenue ('Ordner löschen').
        """
        name, ok = QInputDialog.getText(
            self, "Neuer Ordner", "Ordner-Name:")
        name = (name or "").strip().strip("/")
        if not ok or not name:
            return
        parent_path = str(parent_path or "").strip().strip("/")
        full_path = f"{parent_path}/{name}" if parent_path else name
        # 18.01.03 (Bugfix 08.08.2026): Neuen Ordner (und Elternkette) fuer
        # den folgenden Refresh zum Aufklappen merken – VOR dem emit, weil
        # der Orchestrator den EventBus synchron feuert (data_changed ->
        # _populate).
        self._mark_expand(str(group), full_path)
        self.create_folder_requested.emit(str(group), full_path)

    def _on_rename_folder(self, group: str, old_path: str) -> None:
        """Kontextmenue 'Umbenennen' (18.01.03).

        Fragt den neuen Namen ab (vorbelegt mit dem letzten Pfad-Teil) und
        emittiert `rename_folder_requested(group, old_path, new_path)` – der
        Orchestrator fuehrt den String-Replace ueber alle Kinder aus
        (service_set_utils.rename_category) und emittiert den EventBus.
        """
        old_path = str(old_path or "").strip().strip("/")
        if not old_path:
            return
        old_name = old_path.split("/")[-1]
        new_name, ok = QInputDialog.getText(
            self, "Ordner umbenennen", "Neuer Name:", text=old_name)
        new_name = (new_name or "").strip().strip("/")
        if not ok or not new_name or new_name == old_name:
            return
        parts = old_path.split("/")
        new_path = "/".join(parts[:-1] + [new_name])
        self.rename_folder_requested.emit(str(group), old_path, new_path)

    def _on_rename_clone(self, item) -> None:
        """Kontextmenue 'Variante umbenennen' (10.08.2026, Bugfix).

        Fragt den neuen Preset-Namen ab (vorbelegt mit dem aktuellen Namen)
        und emittiert `rename_variant_requested(plugin_id, instance_hash,
        new_name)` – der Orchestrator (ServiceWindow/ServiceSelectorDialog)
        persistiert den Rename in indicator_presets und emittiert den
        EventBus (Live-Sync aller MasterTrees).
        """
        if item is None or not isValid(item):
            return
        plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
        instance_hash = str(item.data(0, ROLE_INSTANCE_HASH) or "")
        old_name = str(item.data(0, ROLE_PRESET_NAME) or "")
        if not plugin_id or not instance_hash:
            return
        new_name, ok = QInputDialog.getText(
            self, "Variante umbenennen",
            "Neuer Name der Variante:", text=old_name)
        new_name = (new_name or "").strip()
        if not ok or not new_name or new_name == old_name:
            return
        self.rename_variant_requested.emit(
            plugin_id, instance_hash, new_name)
