# serviceui/master_tree.py
"""
Service-UI: 2-Spalten-MasterTree (Phase 15 15.02).

Hierarchische Darstellung der Service-Landschaft:

  * Spalte 0: Knoten – 📁 Service-Sets (mit ihren Service-Instanzen),
              ⚡ Standalone Services, 📦 Alle verfuegbaren Plugins.
              Die Spalte ist Stretch und fuellt die gesamte Breite bis zur
              Status-Spalte. Untereintraege sind per setIndentation()
              eingerueckt (Bugfix 04.08.2026); die Top-Level-Knoten starten
              ganz links (rootIsDecorated=False, keine Branch-Einrueckung
              auf Ebene 0). Jeder Knoten mit Kindern (potentiell aufklappbar)
              traegt ein Auf-/Zuklapp-Symbol vor dem Namen ('>' wenn
              eingeklappt, '⌄' wenn ausgeklappt); ein einfacher Mausklick auf
              einen aufklappbaren Knoten togglet auf/zu (Doppelklick ist
              deaktiviert). Die Top-Level-Knoten beginnen ganz links an der
              Linie der umschliessenden Box (kein Icon/Spacer auf Ebene 0).
  * Spalte 1: Schmale Status-Spalte ganz RECHTS (Fixed-Spalte, fest am
              rechten Rand verankert) – kompakte Badges
              (`📌 im <Indikator> | 🟢 aktiv in <Indikator>` /
              `⚪ inaktiv in <Indikator>`); sehr lange Badges werden auf das
              ASCII-Info-Zeichen 'i' gekuerzt (Bugfix 04.08.2026 – Unicode
              '🛈' U+1F5D8 rendert in den Qt-Fonts nicht zuverlaessig).
              Der Tooltip der Spalte zeigt den Indikator-Namen.

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
from PySide6.QtWidgets import (
    QHeaderView, QTreeWidget, QTreeWidgetItem,
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

# Bugfix 2.1 (04.08.2026, aktualisiert): Lange Relationstexte in der Badge-
# Spalte (z. B. "📌 im GridLiquidityIndicator | ⚪ inaktiv in ...") werden auf
# das Info-Zeichen 'i' gekuerzt – der Indikator-Name steht im Tooltip der
# Spalte 1 (keine extrem breiten Spalten im MasterTree).
MAX_BADGE_CELL_CHARS = 24
# Bugfix 04.08.2026 (Punkt 5): ASCII 'i' statt Unicode '🛈' (U+1F5D8) – das
# Emoji rendert in den Qt-Fonts unter Windows nicht zuverlaessig (tofu-Box).
BADGE_TRUNCATE_ICON = "i"

# Bugfix 3.0 (04.08.2026): Status-Spalte (Spalte 1) ist eine schmale
# Festbreiten-Spalte ganz rechts – nur Platz fuer das kompakte Badge bzw.
# das 'i'-Zeichen, nicht fuer lange Relationstexte.
BADGE_COLUMN_WIDTH = 36

# Bugfix 3.1 (04.08.2026, aktualisiert): Einrueckung + '>'/'⌄'-Marker.
# Untereintraege sind per setIndentation(LEVEL_INDENT) eingerueckt; die
# Auf-/Zuklapp-Markierung uebernimmt das Symbol vor dem Namen ('>' bei
# eingeklappt, '⌄' bei ausgeklappt, siehe _expandable_label). drawBranches
# bleibt als bewusst leerer Override erhalten, damit Qt KEINE nativen
# Branch-Dreiecke zeichnet. Ein einfacher Mausklick auf die GESAMTE Zeile
# eines aufklappbaren Knotens togglet (Punkt 4) – der fruehere schmale
# Klickstreifen entfaellt. BRANCH_ZONE_WIDTH bleibt nur als Test-Referenz
# erhalten (historische Symbol-Klickzone).
BRANCH_ZONE_WIDTH = 16

# Bugfix (04.08.2026): Hierarchie-Einrueckung in Pixeln je Ebene (Qt-Default
# 20px) – Untereintraege (Service-Instanzen unter Sets, Sets unter Gruppen)
# werden dadurch sichtbar eingerueckt statt buendig angeordnet.
LEVEL_INDENT = 20


def _expandable_label(name: str, has_children: bool,
                      is_expanded: bool) -> str:
    """Auf-/Zuklapp-Praefix fuer Knoten mit Untereintraegen (04.08.2026).

    An jedem Knoten, der Kinder enthaelt (potentiell aufklappbar), steht ein
    Symbol vor dem Namen: '>' wenn eingeklappt, '⌄' wenn ausgeklappt.
    Blatt-Knoten (ohne Kinder) erhalten keinen Praefix.
    """
    if not has_children:
        return name
    return ("⌄ " if is_expanded else "> ") + name


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
            # Bugfix (04.08.2026): Spalte 0 (Services) ist Stretch – sie fuellt
            # die gesamte verfuegbare Breite bis zur Status-Spalte. Spalte 1
            # (Status): schmale Fixed-Spalte, dadurch fest am RECHTEN Rand
            # verankert. WICHTIG: setStretchLastSection(False) – QTreeView
            # setzt den Default auf True, wodurch die letzte Spalte trotz
            # Fixed-Mode auf die Restbreite gedehnt wuerde.
            header.setStretchLastSection(False)
            header.setSectionResizeMode(0, QHeaderView.Stretch)
            header.setSectionResizeMode(1, QHeaderView.Fixed)
            header.resizeSection(1, BADGE_COLUMN_WIDTH)
        # Bugfix (04.08.2026): Untereintraege werden per setIndentation()
        # eingerueckt (LEVEL_INDENT px je Ebene). rootIsDecorated=False –
        # die Top-Level-Knoten starten ganz links (keine zusaetzliche
        # Branch-Einrueckung auf Ebene 0); die nativen Branch-Dreiecke
        # unterdrueckt zusaetzlich der bewusst leere drawBranches()-Override.
        # Die Auf-/Zuklapp-Markierung uebernimmt das '>'-Symbol (siehe
        # _expandable_label).
        self.setIndentation(LEVEL_INDENT)
        self.setRootIsDecorated(False)
        # Bugfix 04.08.2026 (Punkt 4): Einfacher Klick togglet auf/zu – der
        # Qt-Default-Doppelklick (expandsOnDoubleClick) ist deaktiviert.
        self.setExpandsOnDoubleClick(False)
        # Bugfix 04.08.2026 (Punkt 2/3): Das Auf-/Zuklapp-Symbol ('>'/'⌄')
        # folgt dem Zustand jedes aufklappbaren Knotens. Die Signale muessen
        # VOR _populate() verbunden sein – _populate() laeuft zwar unter
        # blockSignals, refresht die Top-Level-Labels aber explizit am Ende.
        self.itemExpanded.connect(self._refresh_expand_label)
        self.itemCollapsed.connect(self._refresh_expand_label)

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
                children = group.get("children", [])
                label = _expandable_label(str(group.get("label", "")),
                                          bool(children), False)
                group_item = QTreeWidgetItem([label])
                group_item.setData(0, ROLE_NODE_TYPE, TYPE_GROUP)
                group_item.setData(0, ROLE_SET_ID, group.get("group", ""))
                group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)
                for child in children:
                    item = self._build_child_item(group.get("group"), child)
                    if item is not None:
                        group_item.addChild(item)
                self.addTopLevelItem(group_item)
                group_item.setExpanded(True)
        except Exception as e:
            print(f"WARN [MasterTree] Baum-Aufbau fehlgeschlagen: {e}")
        self.blockSignals(False)
        # Bugfix 04.08.2026 (Punkt 2/3): unter blockSignals feuern die
        # itemExpanded/itemCollapsed-Signale nicht – die Labels der
        # Top-Level-Knoten werden hier explizit auf den IST-Zustand gebracht
        # ('⌄' wenn expandiert, '>' wenn zugeklappt).
        try:
            for i in range(self.topLevelItemCount()):
                item = self.topLevelItem(i)
                if item is not None and isValid(item):
                    self._refresh_expand_label(item)
        except (RuntimeError, AttributeError):
            pass
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
        services = child.get("services", [])
        name = _expandable_label(str(child.get("display_name") or "Unbenannt"),
                                 bool(services), False)
        set_item = QTreeWidgetItem([name, ""])
        set_item.setData(0, ROLE_NODE_TYPE, TYPE_SET)
        set_item.setData(0, ROLE_SET_ID, child.get("set_id") or "")
        set_item.setToolTip(0, f"Service-Set: {child.get('set_id') or '?'}")
        for svc in services:
            # Keine fuehrenden Leerzeichen im Text: die Einrueckung der
            # Untereintraege kommt aus setIndentation(LEVEL_INDENT).
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
        # Keine fuehrenden Leerzeichen: Einrueckung via setIndentation()
        plugin_item = QTreeWidgetItem([pid, ""])
        plugin_item.setData(0, ROLE_NODE_TYPE, TYPE_PLUGIN)
        plugin_item.setData(0, ROLE_SET_ID, group)
        plugin_item.setData(0, ROLE_PLUGIN_ID, pid)
        self._apply_badge(plugin_item, pid, child.get("badge") or "")
        return plugin_item

    def _apply_badge(self, item: QTreeWidgetItem, plugin_id: str,
                     badge: str) -> None:
        """Setzt die Darstellung eines Service-/Plugin-Items (Spalte 0/1).

        * Spalte 1: kompaktes Badge; laenger als MAX_BADGE_CELL_CHARS wird es
          auf das ASCII-Info-Zeichen 'i' gekuerzt – die Status-Spalte zeigt
          dann kein Warn-'!'-, sondern ein Info-Symbol.
        * Tooltip der Spalte 1 (Bugfix 04.08.2026): unterscheidet, ob der
          Indikator der Abhaengigkeit aktuell AKTIV im Chart ist
          ('aktiv <Indikator>') oder nur eine reine Abhaengigkeit darstellt
          ('im <Indikator>').
        """
        badge = str(badge or "")
        if len(badge) > MAX_BADGE_CELL_CHARS:
            item.setText(1, BADGE_TRUNCATE_ICON)
        else:
            item.setText(1, badge)
        name = self.model.get_indicator_display_name(plugin_id)
        if self.model.is_active_in_chart(plugin_id):
            item.setToolTip(1, f"aktiv {name}")
        else:
            item.setToolTip(1, f"im {name}")

    # -------------------------------------------------------------------------
    # Bugfix 04.08.2026: '>'/'⌄'-Marker statt Branch-Dreiecke + Einfach-Klick
    # -------------------------------------------------------------------------

    def drawBranches(self, painter, rect, index) -> None:
        """Bewusst leerer Override: KEINE nativen Branch-Dreiecke.

        Die Auf-/Zuklapp-Markierung uebernimmt das Symbol vor dem Namen
        ('>' eingeklappt / '⌄' ausgeklappt, siehe _expandable_label und
        _refresh_expand_label). Dieser Override bleibt erhalten, damit Qt
        (auch bei rootIsDecorated=False) keine nativen Branch-Dreiecke
        zeichnet; die Einrueckung der Untereintraege (setIndentation) bleibt
        davon unberuehrt.
        """
        pass

    def _refresh_expand_label(self, item) -> None:
        """Setzt das Auf-/Zuklapp-Symbol ('>'/'⌄') auf den IST-Zustand.

        Bugfix 04.08.2026 (Punkt 2/3): Slot fuer itemExpanded/itemCollapsed.
        Blatt-Knoten (ohne Kinder) tragen kein Symbol.
        """
        if item is None or not isValid(item):
            return
        if item.childCount() <= 0:
            return
        text = item.text(0)
        prefix = "⌄ " if item.isExpanded() else "> "
        if text.startswith("> ") or text.startswith("⌄ "):
            item.setText(0, prefix + text[2:])
        else:
            item.setText(0, prefix + text)

    def mousePressEvent(self, event) -> None:
        """Bugfix 04.08.2026 (Punkt 4): Einfacher Klick togglet auf/zu.

        Ein einfacher Mausklick auf einen Knoten MIT Untereintraegen klappt
        den Knoten auf bzw. zu (gesamte Zeile = Klickzone, kein Zielen auf
        ein schmales Symbol noetig). Der Doppelklick togglet NICHT mehr
        (setExpandsOnDoubleClick(False)). Klicks auf Blatt-Knoten verhalten
        sich normal (Selektion). Das Symbol aktualisiert sich automatisch
        ueber itemExpanded/itemCollapsed (_refresh_expand_label).
        """
        try:
            pos = (event.position().toPoint() if hasattr(event, "position")
                   else event.pos())
            item = self.itemAt(pos)
            if item is not None and isValid(item) and item.childCount() > 0:
                item.setExpanded(not item.isExpanded())
                # Selektierbare Knoten (Sets) trotzdem auswaehlen, damit die
                # Auswahl-API (current_set_id/current_service_id) funktioniert.
                if item.flags() & Qt.ItemIsSelectable:
                    self.setCurrentItem(item)
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
