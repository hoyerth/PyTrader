# serviceui/master_tree.py
"""
Service-UI: 2-Spalten-MasterTree (Phase 15 15.02).

Hierarchische Darstellung der Service-Landschaft:

  * Spalte 0: Knoten – 📁 Service-Sets (mit ihren Service-Instanzen),
              ⚡ Standalone Services, 📦 Alle verfuegbaren Plugins.
  * Spalte 1: Kompakte Status-Badges (`📌 Indikator: <Name> |
              🟢 Aktiv in Chart` / `⚪ Inaktiv in Chart`).

Der Baum wird ausschliesslich aus dem `ServiceSelectorModel` befuellt
(lesendes Datenmodell, Invariante 4: kein SQL in UI) und aktualisiert sich
automatisch ueber `data_changed`/EventBus. Der `ServiceSelectorWidget` nutzt
den MasterTree im Modus `FULL_EDIT` (MasterTree + ServiceToolbar).

Signale:
  * selection_changed(set_id, service_id) – bei jeder Baum-Selektion
    (set_id/service_id koennen leer sein, wenn nichts Konkretes gewaehlt ist).
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHeaderView, QTreeWidget, QTreeWidgetItem

# UserRole-Kennungen fuer die Knotentypen (Deterministische Auswertung)
ROLE_NODE_TYPE = Qt.UserRole
ROLE_SET_ID = Qt.UserRole + 1
ROLE_INSTANCE_ID = Qt.UserRole + 2
ROLE_PLUGIN_ID = Qt.UserRole + 3

#: Knotentypen
TYPE_GROUP = "group"
TYPE_SET = "set"
TYPE_SERVICE = "service"
TYPE_PLUGIN = "plugin"


class MasterTree(QTreeWidget):
    """2-Spalten-TreeWidget fuer die hierarchische Service-Darstellung."""

    selection_changed = Signal(str, str)  # set_id, service_id

    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self.model = model
        self.setColumnCount(2)
        self.setHeaderLabels(["Services", "Status"])
        header = self.header()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        # Breite genug fuer die Badges vorbelegen
        self.setColumnWidth(1, 260)
        self.setRootIsDecorated(True)

        self._populate()
        self.itemSelectionChanged.connect(self._emit_selection)
        self.model.data_changed.connect(self._populate)

    # -------------------------------------------------------------------------
    # Befuellung aus dem Modell
    # -------------------------------------------------------------------------

    def _populate(self) -> None:
        """Baut den Baum aus model.build_tree() neu auf (deterministisch)."""
        current = self.current_selection()
        self.blockSignals(True)
        self.clear()
        try:
            for group in self.model.build_tree():
                group_item = QTreeWidgetItem([str(group.get("label", ""))])
                group_item.setData(0, ROLE_NODE_TYPE, TYPE_GROUP)
                group_item.setData(0, ROLE_SET_ID, group.get("group", ""))
                group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)
                for child in group.get("children", []):
                    item = self._build_child_item(group.get("group"), child)
                    if item is not None:
                        group_item.addChild(item)
                self.addTopLevelItem(group_item)
                group_item.setExpanded(True)
        except Exception as e:
            print(f"WARN [MasterTree] Baum-Aufbau fehlgeschlagen: {e}")
        self.blockSignals(False)
        # Aktuelle Auswahl nach Refresh wiederherstellen (falls noch vorhanden)
        self._restore_selection(current)

    def _build_child_item(self, group: str,
                          child: Dict[str, Any]) -> Optional[QTreeWidgetItem]:
        """Erzeugt das Kind-Item fuer einen Knoten der Gruppe `group`."""
        if group == self.model.GROUP_SETS:
            return self._build_set_item(child)
        if group == self.model.GROUP_STANDALONE:
            return self._build_plugin_item(child, group)
        if group == self.model.GROUP_PLUGINS:
            return self._build_plugin_item(child, group)
        return None

    def _build_set_item(self, child: Dict[str, Any]) -> QTreeWidgetItem:
        set_item = QTreeWidgetItem([str(child.get("display_name") or "Unbenannt"), ""])
        set_item.setData(0, ROLE_NODE_TYPE, TYPE_SET)
        set_item.setData(0, ROLE_SET_ID, child.get("set_id") or "")
        set_item.setToolTip(0, f"Service-Set: {child.get('set_id') or '?'}")
        for svc in child.get("services", []):
            svc_item = QTreeWidgetItem([
                f"  {svc.get('instance_id')}  [{svc.get('plugin_id')}]",
                str(svc.get("badge") or ""),
            ])
            svc_item.setData(0, ROLE_NODE_TYPE, TYPE_SERVICE)
            svc_item.setData(0, ROLE_SET_ID, child.get("set_id") or "")
            svc_item.setData(0, ROLE_INSTANCE_ID, svc.get("instance_id") or "")
            svc_item.setData(0, ROLE_PLUGIN_ID, svc.get("plugin_id") or "")
            set_item.addChild(svc_item)
        return set_item

    def _build_plugin_item(self, child: Dict[str, Any],
                           group: str) -> QTreeWidgetItem:
        pid = child.get("plugin_id") or ""
        label = f"  {pid}"
        plugin_item = QTreeWidgetItem([label, str(child.get("badge") or "")])
        plugin_item.setData(0, ROLE_NODE_TYPE, TYPE_PLUGIN)
        plugin_item.setData(0, ROLE_SET_ID, group)
        plugin_item.setData(0, ROLE_PLUGIN_ID, pid)
        return plugin_item

    # -------------------------------------------------------------------------
    # Selektion / Auswertung
    # -------------------------------------------------------------------------

    def current_selection(self) -> Dict[str, str]:
        """Liefert die aktuelle Auswahl als {"set_id": ..., "service_id": ...}."""
        item = self.currentItem()
        if item is None:
            return {"set_id": "", "service_id": ""}
        node_type = item.data(0, ROLE_NODE_TYPE)
        set_id = str(item.data(0, ROLE_SET_ID) or "")
        if node_type == TYPE_SERVICE:
            return {"set_id": set_id,
                    "service_id": str(item.data(0, ROLE_INSTANCE_ID) or "")}
        if node_type == TYPE_SET:
            return {"set_id": set_id, "service_id": ""}
        return {"set_id": "", "service_id": ""}

    def current_set_id(self) -> str:
        return self.current_selection().get("set_id", "")

    def current_service_id(self) -> str:
        return self.current_selection().get("service_id", "")

    def _emit_selection(self) -> None:
        sel = self.current_selection()
        self.selection_changed.emit(sel["set_id"], sel["service_id"])

    def _restore_selection(self, previous: Dict[str, str]) -> None:
        """Stellt die Auswahl nach einem Refresh wieder her (sofern vorhanden)."""
        if not previous or not previous.get("set_id"):
            return
        target_id = previous.get("service_id") or previous.get("set_id")
        for item in TreeItemIterator(self):
            svc_id = item.data(0, ROLE_INSTANCE_ID)
            set_id = item.data(0, ROLE_SET_ID)
            node_type = item.data(0, ROLE_NODE_TYPE)
            if (node_type == TYPE_SERVICE and svc_id == target_id
                    and set_id == previous.get("set_id")):
                self.setCurrentItem(item)
                return
            if (node_type == TYPE_SET and set_id == target_id
                    and not previous.get("service_id")):
                self.setCurrentItem(item)
                return


class TreeItemIterator:
    """Leichter Iterator ueber alle QTreeWidgetItems (rekursiv, depth-first)."""

    def __init__(self, tree: QTreeWidget) -> None:
        self._items: list = []
        for i in range(tree.topLevelItemCount()):
            self._collect(tree.topLevelItem(i))
        self._index = 0

    def _collect(self, item: QTreeWidgetItem) -> None:
        self._items.append(item)
        for i in range(item.childCount()):
            self._collect(item.child(i))

    def __iter__(self):
        self._index = 0
        return self

    def __next__(self) -> Optional[QTreeWidgetItem]:
        if self._index >= len(self._items):
            raise StopIteration
        item = self._items[self._index]
        self._index += 1
        return item
