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

# P15-Bugfix: shiboken6.isValid() schuetzt vor dem Zugriff auf bereits
# C++-seitig zerstoerte Items (QTreeWidget.clear() nach data_changed bei
# wildem Klicken) – verhindert Access Violation (0xC0000005).
try:
    from shiboken6 import isValid
except ImportError:  # pragma: no cover
    def isValid(obj) -> bool:  # type: ignore
        return obj is not None

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

# Bugfix 2.1 (04.08.2026): Lange Relationstexte in der Badge-Spalte (z. B.
# "📌 Indikator: Grid Liquidity | 🟢 Aktiv in Chart") werden auf ein '!'-Icon
# gekuerzt – der volle Text steht im Tooltip der Spalte 1 (keine extrem breiten
# Spalten im MasterTree).
MAX_BADGE_CELL_CHARS = 24
BADGE_TRUNCATE_ICON = "!"


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
        # Breite fuer die Badge-Spalte vorbelegen (ResizeToContents passt sie
        # an den Inhalt an; nach Bugfix 2.1 sind lange Badges nur noch '!')
        self.setColumnWidth(1, 80)
        self.setRootIsDecorated(True)

        self._populate()
        self.itemSelectionChanged.connect(self._emit_selection)
        self.model.data_changed.connect(self._populate)

    # -------------------------------------------------------------------------
    # Befuellung aus dem Modell
    # -------------------------------------------------------------------------

    def _populate(self) -> None:
        """Baut den Baum aus model.build_tree() neu auf (deterministisch)."""
        current = self._safe_current_selection()
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
        try:
            self._restore_selection(current)
        except Exception as e:
            print(f"WARN [MasterTree] Auswahl-Restore fehlgeschlagen: {e}")

    def _safe_current_selection(self) -> Dict[str, str]:
        """Liess die aktuelle Auswahl defensiv (isValid-Guard gegen zerstoerte
        Items, z.B. nach einem zwischenzeitlichen clear())."""
        try:
            item = self.currentItem()
            if item is None or not isValid(item):
                return {"set_id": "", "service_id": ""}
            node_type = item.data(0, ROLE_NODE_TYPE)
            set_id = str(item.data(0, ROLE_SET_ID) or "")
            if node_type == TYPE_SERVICE:
                return {"set_id": set_id,
                        "service_id": str(item.data(0, ROLE_INSTANCE_ID) or "")}
            if node_type == TYPE_SET:
                return {"set_id": set_id, "service_id": ""}
            return {"set_id": "", "service_id": ""}
        except (RuntimeError, AttributeError):
            return {"set_id": "", "service_id": ""}

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
            # Bugfix 2.0: KEINE fuehrenden Leerzeichen – QTreeWidget indentiert
            # Kinder nativ, die zusaetzlichen 2 Spaces raubten nur Platz.
            badge = str(svc.get("badge") or "")
            svc_item = QTreeWidgetItem([
                f"{svc.get('instance_id')}  [{svc.get('plugin_id')}]",
                self._badge_cell_text(badge),
            ])
            svc_item.setData(0, ROLE_NODE_TYPE, TYPE_SERVICE)
            svc_item.setData(0, ROLE_SET_ID, child.get("set_id") or "")
            svc_item.setData(0, ROLE_INSTANCE_ID, svc.get("instance_id") or "")
            svc_item.setData(0, ROLE_PLUGIN_ID, svc.get("plugin_id") or "")
            if badge:
                # Bugfix 2.1: voller Relationstext im Tooltip der Badge-Spalte
                svc_item.setToolTip(1, badge)
            set_item.addChild(svc_item)
        return set_item

    def _build_plugin_item(self, child: Dict[str, Any],
                           group: str) -> QTreeWidgetItem:
        pid = child.get("plugin_id") or ""
        # Bugfix 2.0: keine fuehrenden Leerzeichen (native Tree-Indentation)
        badge = str(child.get("badge") or "")
        plugin_item = QTreeWidgetItem([pid, self._badge_cell_text(badge)])
        plugin_item.setData(0, ROLE_NODE_TYPE, TYPE_PLUGIN)
        plugin_item.setData(0, ROLE_SET_ID, group)
        plugin_item.setData(0, ROLE_PLUGIN_ID, pid)
        if badge:
            # Bugfix 2.1: voller Relationstext im Tooltip der Badge-Spalte
            plugin_item.setToolTip(1, badge)
        return plugin_item

    @staticmethod
    def _badge_cell_text(badge: str) -> str:
        """Kurzform fuer die Badge-Spalte (Relationen zu Indikatoren).

        Texte laenger als MAX_BADGE_CELL_CHARS werden auf das '!'-Icon
        gekuerzt (der volle Text steht im Tooltip der Spalte 1) – verhindert
        extrem breite Spalten bei langen Indikator-Relationen (Bugfix 2.1).
        """
        badge = str(badge or "")
        if len(badge) > MAX_BADGE_CELL_CHARS:
            return BADGE_TRUNCATE_ICON
        return badge

    # -------------------------------------------------------------------------
    # Selektion / Auswertung
    # -------------------------------------------------------------------------

    def current_selection(self) -> Dict[str, str]:
        """Liefert die aktuelle Auswahl als {"set_id": ..., "service_id": ...}.

        P15-Bugfix: isValid-Guard – bei wildem Klicken kann currentItem() auf
        ein durch clear() zerstoertes C++-Item zeigen; der Zugriff auf
        .data() wuerde sonst einen Access Violation (0xC0000005) ausloesen.
        """
        try:
            item = self.currentItem()
            if item is None or not isValid(item):
                return {"set_id": "", "service_id": ""}
            node_type = item.data(0, ROLE_NODE_TYPE)
            set_id = str(item.data(0, ROLE_SET_ID) or "")
            if node_type == TYPE_SERVICE:
                return {"set_id": set_id,
                        "service_id": str(item.data(0, ROLE_INSTANCE_ID) or "")}
            if node_type == TYPE_SET:
                return {"set_id": set_id, "service_id": ""}
            return {"set_id": "", "service_id": ""}
        except (RuntimeError, AttributeError):
            return {"set_id": "", "service_id": ""}

    def current_set_id(self) -> str:
        return self.current_selection().get("set_id", "")

    def current_service_id(self) -> str:
        return self.current_selection().get("service_id", "")

    def _emit_selection(self) -> None:
        sel = self.current_selection()
        try:
            self.selection_changed.emit(sel["set_id"], sel["service_id"])
        except (RuntimeError, AttributeError):
            pass

    def _restore_selection(self, previous: Dict[str, str]) -> None:
        """Stellt die Auswahl nach einem Refresh wieder her (sofern vorhanden).

        P15-Bugfix: setCurrentItem unter blockSignals (kein Signal-Sturm /
        keine Rekursion in _on_master_selection) + isValid-Guards gegen
        zerstoerte Items (Access-Violation-Schutz).
        """
        if not previous or not previous.get("set_id"):
            return
        target_id = previous.get("service_id") or previous.get("set_id")
        try:
            self.blockSignals(True)
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                svc_id = item.data(0, ROLE_INSTANCE_ID)
                set_id = item.data(0, ROLE_SET_ID)
                node_type = item.data(0, ROLE_NODE_TYPE)
                if (node_type == TYPE_SERVICE and svc_id == target_id
                        and set_id == previous.get("set_id")):
                    self.setCurrentItem(item)
                    break
                if (node_type == TYPE_SET and set_id == target_id
                        and not previous.get("service_id")):
                    self.setCurrentItem(item)
                    break
        finally:
            self.blockSignals(False)


class TreeItemIterator:
    """Leichter Iterator ueber alle QTreeWidgetItems (rekursiv, depth-first).

    P15-Bugfix: isValid-Guard im __next__ – Items koennen zwischen Sammlung
    und Iteration C++-seitig zerstoert werden (clear() bei data_changed).
    """

    def __init__(self, tree: QTreeWidget) -> None:
        self._items: list = []
        try:
            for i in range(tree.topLevelItemCount()):
                self._collect(tree.topLevelItem(i))
        except (RuntimeError, AttributeError):
            self._items = []
        self._index = 0

    def _collect(self, item: Optional[QTreeWidgetItem]) -> None:
        if item is None or not isValid(item):
            return
        self._items.append(item)
        try:
            for i in range(item.childCount()):
                self._collect(item.child(i))
        except (RuntimeError, AttributeError):
            pass

    def __iter__(self):
        self._index = 0
        return self

    def __next__(self) -> Optional[QTreeWidgetItem]:
        if self._index >= len(self._items):
            raise StopIteration
        item = self._items[self._index]
        self._index += 1
        if item is None or not isValid(item):
            return None
        return item
