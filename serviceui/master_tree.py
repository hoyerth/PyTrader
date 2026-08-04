# serviceui/master_tree.py
"""
Service-UI: 2-Spalten-MasterTree (Phase 15 15.02).

Hierarchische Darstellung der Service-Landschaft:

  * Spalte 0: Knoten – 📁 Service-Sets (mit ihren Service-Instanzen),
              ⚡ Standalone Services, 📦 Alle verfuegbaren Plugins.
              Alle Zeilen sind buendig (keine Hierarchie-Einrueckung,
              Bugfix 3.1); Knoten mit Kindern tragen links ein Aufklapp-
              Dreieck (selbst gezeichnet, per Klick toggelbar).
  * Spalte 1: Schmale Status-Spalte rechts – kompakte Badges
              (`📌 Indikator: <Name> | 🟢 Aktiv in Chart` /
              `⚪ Inaktiv in Chart`); sehr lange Badges werden auf ein
              farbiges '!'-Icon gekuerzt (Bugfix 2.1). Der Tooltip der
              Spalte zeigt den Namen des Indikators (Bugfix 3.0).

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
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QHeaderView, QStyle, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem,
)

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
# "📌 Indikator: Grid Liquidity | 🟢 Aktiv in Chart") werden auf ein farbiges
# '!'-Icon gekuerzt – der Name des Indikators steht im Tooltip der Spalte 1
# (keine extrem breiten Spalten im MasterTree).
MAX_BADGE_CELL_CHARS = 24
BADGE_TRUNCATE_ICON = "!"

# Bugfix 3.0 (04.08.2026): Status-Spalte (Spalte 1) ist eine schmale
# Festbreiten-Spalte ganz rechts – nur Platz fuer das kompakte Badge bzw.
# das '!'-Icon, nicht fuer lange Relationstexte.
BADGE_COLUMN_WIDTH = 36

# Bugfix 3.1 (04.08.2026): Bündige Zeilen + Aufklapp-Dreiecke.
# Die native Qt-Indentation (20px/Ebene) entfaellt (setIndentation(0)),
# damit alle Zeilen buendig sind. Die Aufklapp-Dreiecke werden deshalb
# selbst gezeichnet (drawBranches) – in einer festen Zone am linken Rand,
# deren Breite ein transparentes Spacer-Icon auf allen Zeilen reserviert
# (keine Text-Ueberlappung mit dem Dreieck).
BRANCH_ZONE_WIDTH = 16


class MasterTree(QTreeWidget):
    """2-Spalten-TreeWidget fuer die hierarchische Service-Darstellung."""

    selection_changed = Signal(str, str)  # set_id, service_id

    def __init__(self, model, parent=None) -> None:
        super().__init__(parent)
        self.model = model
        self.setColumnCount(2)
        self.setHeaderLabels(["Services", ""])
        header = self.header()
        if header is not None:
            # Spalte 0 (Services): ResizeToContents (bewaehrter Modus, kein
            # Stretch-Layout-Risiko). Spalte 1 (Status): schmale Fixed-Spalte
            # ganz rechts (Bugfix 3.0). WICHTIG: setStretchLastSection(False)
            # – QTreeView setzt den Default auf True, wodurch die letzte
            # Spalte trotz Fixed-Mode auf die Restbreite gedehnt wuerde.
            header.setStretchLastSection(False)
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.Fixed)
            header.resizeSection(1, BADGE_COLUMN_WIDTH)
        # Bugfix 3.1: Native Qt-Indentation (20px/Ebene) entfaellt – alle
        # Zeilen buendig. Die Aufklapp-Dreiecke zeichnet drawBranches()
        # selbst (setRootIsDecorated bleibt aus Kompatibilitaet aktiv).
        self.setIndentation(0)
        self.setRootIsDecorated(True)
        # Transparentes Spacer-Icon: reserviert links die BRANCH_ZONE_WIDTH
        # fuer das Aufklapp-Dreieck, damit der Text jeder Zeile buendig
        # NACH der Dreieck-Zone beginnt (keine Ueberlappung).
        _spacer = QPixmap(BRANCH_ZONE_WIDTH, BRANCH_ZONE_WIDTH)
        _spacer.fill(Qt.transparent)
        self._branch_spacer_icon = QIcon(_spacer)
        # Farbiges '!'-Icon (Spalte 1) fuer gekuerzte Badges (Bugfix 2.1)
        self._warn_icon = self.style().standardIcon(
            QStyle.StandardPixmap.SP_MessageBoxWarning)

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
                group_item.setIcon(0, self._branch_spacer_icon)
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
        set_item.setIcon(0, self._branch_spacer_icon)
        set_item.setToolTip(0, f"Service-Set: {child.get('set_id') or '?'}")
        for svc in child.get("services", []):
            # Bugfix 2.0: KEINE fuehrenden Leerzeichen – die bündige Zeile
            # kommt aus setIndentation(0) (Bugfix 3.0), nicht aus Spaces.
            plugin_id = svc.get("plugin_id") or ""
            svc_item = QTreeWidgetItem([
                f"{svc.get('instance_id')}  [{plugin_id}]",
                "",
            ])
            svc_item.setData(0, ROLE_NODE_TYPE, TYPE_SERVICE)
            svc_item.setData(0, ROLE_SET_ID, child.get("set_id") or "")
            svc_item.setData(0, ROLE_INSTANCE_ID, svc.get("instance_id") or "")
            svc_item.setData(0, ROLE_PLUGIN_ID, plugin_id)
            self._apply_badge(svc_item, plugin_id, svc.get("badge") or "")
            set_item.addChild(svc_item)
        return set_item

    def _build_plugin_item(self, child: Dict[str, Any],
                           group: str) -> QTreeWidgetItem:
        pid = child.get("plugin_id") or ""
        # Bugfix 2.0: keine fuehrenden Leerzeichen (bündig via setIndentation(0))
        plugin_item = QTreeWidgetItem([pid, ""])
        plugin_item.setData(0, ROLE_NODE_TYPE, TYPE_PLUGIN)
        plugin_item.setData(0, ROLE_SET_ID, group)
        plugin_item.setData(0, ROLE_PLUGIN_ID, pid)
        self._apply_badge(plugin_item, pid, child.get("badge") or "")
        return plugin_item

    def _apply_badge(self, item: QTreeWidgetItem, plugin_id: str,
                     badge: str) -> None:
        """Setzt die Darstellung eines Service-/Plugin-Items (Spalte 0/1).

        * Spacer-Icon in Spalte 0 (Bugfix 3.1): reserviert die Dreieck-Zone,
          damit alle Zeilen buendig nach der Zone beginnen.
        * Spalte 1: kompaktes Badge; laenger als MAX_BADGE_CELL_CHARS wird es
          auf ein farbiges '!'-Icon gekuerzt (Bugfix 2.1).
        * Tooltip der Spalte 1 (Bugfix 3.0): Name des Indikators
          (metadata['display_name']) statt der Badge-Zeile.
        """
        item.setIcon(0, self._branch_spacer_icon)
        badge = str(badge or "")
        if len(badge) > MAX_BADGE_CELL_CHARS:
            if not self._warn_icon.isNull():
                item.setIcon(1, self._warn_icon)
            else:  # pragma: no cover - Plattform ohne Standard-Icon
                item.setText(1, BADGE_TRUNCATE_ICON)
        else:
            item.setText(1, badge)
        item.setToolTip(
            1,
            f"Indikator: {self.model.get_indicator_display_name(plugin_id)}",
        )

    # -------------------------------------------------------------------------
    # Bugfix 3.1: Aufklapp-Dreiecke bei buendigen Zeilen
    # -------------------------------------------------------------------------

    def drawBranches(self, painter, rect, index) -> None:
        """Zeichnet die Aufklapp-Dreiecke am linken Rand (Bugfix 3.1).

        Da setIndentation(0) die native Qt-Branch-Zeichnung (indentation
        pro Ebene) entfaellt, werden die Dreiecke fuer alle Knoten mit
        Kindern hier selbst gezeichnet – im Stil des aktiven Qt-Styles,
        in der BRANCH_ZONE_WIDTH-breiten Zone am linken Rand (die alle
        Zeilen durch ihr Spacer-Icon freihalten). Der uebergebene `rect`
        begrenzt den sichtbaren Ausschnitt; unsichtbare (collapsed) Zeilen
        liefern eine leere visualItemRect und werden uebersprungen.
        """
        try:
            if rect is None or rect.isEmpty():
                return
            opt = QStyleOptionViewItem()
            opt.initFrom(self)
            opt.state |= QStyle.State_Item
            top, bottom = rect.top(), rect.bottom()
            for item in TreeItemIterator(self):
                if item is None or not isValid(item) or item.childCount() <= 0:
                    continue
                r = self.visualItemRect(item)
                if r.isEmpty() or r.bottom() < top or r.top() > bottom:
                    continue
                bo = QStyleOptionViewItem(opt)
                bo.rect = r
                bo.rect.setRight(r.left() + BRANCH_ZONE_WIDTH - 1)
                state = QStyle.State_Children
                if item.isExpanded():
                    state |= QStyle.State_Open
                bo.state = state
                self.style().drawPrimitive(
                    QStyle.PE_IndicatorBranch, bo, painter, self)
        except (RuntimeError, AttributeError):
            pass

    def mousePressEvent(self, event) -> None:
        """Bugfix 3.1: Klick in die Dreieck-Zone togglet auf/zu.

        Die native Branch-Klickzone existiert bei setIndentation(0) nicht;
        der Klick in die BRANCH_ZONE_WIDTH-breite Zone am linken Rand einer
        Zeile mit Kindern wird hier selbst ausgewertet.
        """
        try:
            pos = (event.position().toPoint() if hasattr(event, "position")
                   else event.pos())
            item = self.itemAt(pos)
            if item is not None and isValid(item) and item.childCount() > 0:
                r = self.visualItemRect(item)
                if r.left() <= pos.x() < r.left() + BRANCH_ZONE_WIDTH:
                    item.setExpanded(not item.isExpanded())
                    event.accept()
                    return
        except (RuntimeError, AttributeError):
            pass
        super().mousePressEvent(event)

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
