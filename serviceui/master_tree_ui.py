"""
master_tree_ui.py - Expand-State, Info-Buttons, Dirty-Marker, Checkable-Modus

23.06 God-File-Split (15.08.2026): Aus serviceui/master_tree.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der MasterTree-
Klasse als Mixin (Klasse MasterTreeUiMixin).
"""

from PySide6.QtCore import (
    Qt,
)

from PySide6.QtWidgets import (
    QPushButton,
)

from serviceui.master_tree_constants import (
    INFO_BUTTON_COLOR_INDICATOR,
    INFO_BUTTON_COLOR_NEUTRAL,
    INFO_BUTTON_SIZE,
    INFO_BUTTON_TEXT,
    ROLE_INSTANCE_ID,
    ROLE_NODE_TYPE,
    ROLE_PLUGIN_ID,
    ROLE_SET_ID,
    TYPE_CATEGORY,
    TYPE_CLONE,
    TYPE_PLUGIN,
    TYPE_SERVICE,
    TYPE_SET,
    TreeItemIterator,
    isValid,
)

class MasterTreeUiMixin:

    # -------------------------------------------------------------------------
    # 18.01.03 (Bugfix 08.08.2026): Expansion-Erhaltung ueber _populate()
    # -------------------------------------------------------------------------

    def _collect_expanded_state(self) -> set:
        """Sammelt die aufgeklappten Knoten des IST-Baums (RAM-Schluessel).

        Schluessel: ("cat", group, kategorie-pfad) fuer Ordner bzw.
        ("set", set_id) fuer Set-Knoten. Top-Level-Gruppen (TYPE_GROUP)
        werden in _populate() ohnehin immer expandiert; Blatt-/Service-
        Knoten sind nicht aufklappbar. isValid-Guards gegen zerstoerte
        Items (Access-Violation-Schutz).
        """
        result: set = set()
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                if not item.isExpanded():
                    continue
                node_type = item.data(0, ROLE_NODE_TYPE)
                if node_type == TYPE_CATEGORY:
                    result.add(("cat", self._group_of(item),
                                self._category_path_of(item)))
                elif node_type == TYPE_SET:
                    result.add(("set",
                                str(item.data(0, ROLE_SET_ID) or "")))
                elif node_type == TYPE_PLUGIN and item.childCount() > 0:
                    # 10.08.2026 (Bugfix): Plugin-Parents mit Varianten/
                    # Clones sind aufklappbare Knoten - ihre Expansion muss
                    # ueber Rebuilds (data_changed -> _populate nach
                    # Speichern/Umbenennen/Duplizieren) erhalten bleiben,
                    # sonst klappt der Knoten zusammen. Nur ein Mausklick
                    # auf den Knoten soll togglen.
                    result.add(("plugin",
                                str(item.data(0, ROLE_PLUGIN_ID) or "")))
        except (RuntimeError, AttributeError):
            pass
        return result

    def _apply_expanded_state(self, expanded: set) -> None:
        """Expandiert die gesammelten Knoten nach dem Neuaufbau wieder.

        Zusaetzlich werden Einmal-Expansionen aus `_expand_after_rebuild`
        angewandt (Ziel-Ordner nach Drop, neu erzeugter Ordner) und danach
        geleert. Die '>'/'⌄'-Labels werden explizit aktualisiert (setExpanded
        unter blockSignals feuert kein itemExpanded).
        """
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                node_type = item.data(0, ROLE_NODE_TYPE)
                expand = False
                if node_type == TYPE_CATEGORY:
                    key = ("cat", self._group_of(item),
                           self._category_path_of(item))
                    expand = (key in expanded
                              or key in self._expand_after_rebuild)
                elif node_type == TYPE_SET:
                    key = ("set", str(item.data(0, ROLE_SET_ID) or ""))
                    expand = key in expanded
                elif node_type == TYPE_PLUGIN and item.childCount() > 0:
                    key = ("plugin",
                           str(item.data(0, ROLE_PLUGIN_ID) or ""))
                    expand = key in expanded
                if expand:
                    item.setExpanded(True)
        except (RuntimeError, AttributeError):
            pass
        self._expand_after_rebuild.clear()
        # Labels aller aufklappbaren Knoten auf den IST-Zustand bringen.
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                self._refresh_expand_label(item)
        except (RuntimeError, AttributeError):
            pass

    def _mark_expand(self, group: str, path: str) -> None:
        """Merkt die Ordnerkette von `path` fuer die naechste Expansion.

        Wird VOR dem emit() der Struktur-Signale gerufen (der EventBus-
        Refresh laeuft synchron waehrend des emit): Beim unmittelbar
        folgenden _populate() werden diese Pfade (und alle Eltern-Glieder)
        aufgeklappt, damit z. B. ein neu erzeugter Ordner oder ein
        Drop-Ziel-Ordner sofort sichtbar bleibt.
        """
        parts = [p.strip() for p in str(path or "").split("/") if p.strip()]
        for i in range(len(parts)):
            self._expand_after_rebuild.add(
                ("cat", str(group or ""), "/".join(parts[: i + 1])))

    def _attach_item_buttons(self) -> None:
        """Haengt die Info-Buttons (Spalte 1) an alle Service-/Set-/Plugin-
        Zeilen UND Kategorie-Ordner (Bugfix 05.08.2026 / 17.01.02).

        Der Button ist ein kompakter QPushButton ("ℹ", Icon-Breite) und ersetzt
        die frueheren Text-Badges. Gehoert die Zeile einem Indikator (Tooltip
        aus _apply_badge/_apply_set_badge vorhanden), ist er gelb (#FFD700)
        eingefaerbt und traegt den Tooltip; sonst neutral. Der Klick emittiert
        `info_requested` mit den zeilenspezifischen Daten:
          Service-Zeile -> (set_id, instance_id, plugin_id)
          Set-Zeile      -> (set_id, "", "")
          Plugin-Zeile   -> ("", "", plugin_id)
          Kategorie-Ordner -> `category_info_requested(Kategorie-Pfad)`
            (17.01.02: wie bei Sets – der Ordner-Button zeigt die Kategorie-
            Info mit allen Services unter dem Ordner).
        Gruppen-Knoten (📁 Sets / 📦 Services, TYPE_GROUP) erhalten bewusst
        KEINEN Button.
        """
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                node_type = item.data(0, ROLE_NODE_TYPE)
                if node_type not in (TYPE_SERVICE, TYPE_SET, TYPE_PLUGIN,
                                     TYPE_CATEGORY, TYPE_CLONE):
                    continue
                tooltip = item.toolTip(1) or ""
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                service_id = ""
                plugin_id = ""
                if node_type == TYPE_SERVICE:
                    service_id = str(item.data(0, ROLE_INSTANCE_ID) or "")
                    plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
                elif node_type in (TYPE_PLUGIN, TYPE_CLONE):
                    # Plugin-/Clone-Zeilen: set_id bewusst leer (die
                    # ROLE_SET_ID traegt nur die Gruppenkennung); bei
                    # Clones liefert ROLE_PLUGIN_ID die feature_id.
                    set_id = ""
                    plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")

                btn = QPushButton(INFO_BUTTON_TEXT, self)
                btn.setFixedSize(INFO_BUTTON_SIZE, INFO_BUTTON_SIZE)
                btn.setCursor(Qt.PointingHandCursor)
                color = (INFO_BUTTON_COLOR_INDICATOR if tooltip
                         else INFO_BUTTON_COLOR_NEUTRAL)
                btn.setStyleSheet(
                    f"QPushButton {{ color:{color}; border:none;"
                    f" font-weight:bold; background:transparent; }}")
                if tooltip:
                    btn.setToolTip(tooltip)
                # 17.01.02: Kategorie-Ordner emittieren category_info_requested
                # mit dem vollen Kategorie-Pfad (analog Set-Info). 18.01.03
                # (L3): Zusaetzlich wird die Eltern-GRUPPE uebergeben, damit
                # der Orchestrator Sets-Ordner ('sets') von Plugins-Ordnern
                # ('plugins') unterscheiden kann.
                if node_type == TYPE_CATEGORY:
                    cat_path = self._category_path_of(item)
                    cat_group = self._group_of(item)
                    btn.setToolTip(
                        f"Kategorie: {cat_path or '?'}")
                    btn.clicked.connect(
                        lambda _=False, g=cat_group, cp=cat_path:
                        self.category_info_requested.emit(g, cp))
                else:
                    btn.clicked.connect(
                        lambda _=False, s=set_id, svc=service_id, pid=plugin_id:
                        self.info_requested.emit(s, svc, pid))
                self.setItemWidget(item, 1, btn)
        except (RuntimeError, AttributeError):
            pass

    # -------------------------------------------------------------------------
    # Phase 15 (Dirty-State): '*' am Service-Knoten bei ungespeicherten
    # Parameter-Aenderungen (Format 'Service_Name* (DD.MM.JJ)')
    # -------------------------------------------------------------------------

    def set_instance_dirty(self, instance_id: str, dirty: bool) -> None:
        """Markiert eine Service-Instanz als ungespeichert ('*' am Knoten).

        Der Dirty-Zustand wird im RAM gehalten (self._dirty_instance_ids) und
        bei jedem Baum-Neuaufbau (_populate) re-appliziert. Nach erfolgreichem
        Speichern ruft der Orchestrator clear_dirty_markers() auf.
        """
        if not instance_id:
            return
        if dirty:
            self._dirty_instance_ids.add(instance_id)
        else:
            self._dirty_instance_ids.discard(instance_id)
        self._apply_dirty_label(instance_id, dirty)

    def clear_dirty_markers(self) -> None:
        """Entfernt ALLE Sternchen-Markierungen (nach Speichern).

        Das Set wird geleert und die Knoten-Labels zurueckgesetzt; der
        naechste Baum-Neuaufbau erzeugt damit saubere Labels.
        """
        for iid in list(self._dirty_instance_ids):
            self._apply_dirty_label(iid, False)
        self._dirty_instance_ids.clear()

    def _apply_dirty_label(self, instance_id: str, dirty: bool) -> None:
        """Setzt/entfernt das '*' im Label des Service-Knotens mit
        instance_id. Das Ausfuehrungsdatum '(DD.MM.JJ)' bleibt erhalten."""
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                if item.data(0, ROLE_NODE_TYPE) != TYPE_SERVICE:
                    continue
                if str(item.data(0, ROLE_INSTANCE_ID) or "") != instance_id:
                    continue
                text = item.text(0) or ""
                name, sep, rest = text.partition(" (")
                if not sep:
                    continue
                name = name.rstrip("*")
                item.setText(0, f"{name}{'*' if dirty else ''} ({rest}")
                break
        except (RuntimeError, AttributeError):
            pass

    # -------------------------------------------------------------------------
    # 15.03-E (Multi-Select): Checkbox-Modus (ServiceSelectorDialog)
    # -------------------------------------------------------------------------

    def set_checkable(self, checkable: bool) -> None:
        """Schaltet den Checkbox-Modus ein/aus (SELECT_MULTI).

        Im Normalbetrieb (FULL_EDIT, ServiceWindow) ist der Baum NICHT
        anhakbar – `set_checkable(True)` aktiviert die Checkboxen fuer den
        ServiceSelectorDialog und baut den Baum neu auf (Zustand beginnt
        leer). `set_checkable(False)` deaktiviert und leert den Zustand.
        """
        checkable = bool(checkable)
        if checkable == self._checkable:
            return
        self._checkable = checkable
        if not checkable:
            self._checked_items.clear()
        self._populate()

    def _expand_ancestors(self, item) -> None:
        """Klappt die Eltern-Kette eines Items auf (Bugfix 08.08.2026).

        Bug 2 (User-Meldung: 'Tree-Knoten sollen aufgeklappt sein und die
        Services sichtbar sein, die aktiviert wurden'): Nach dem Setzen der
        Checkboxen (`set_checked_feature_ids`) bzw. beim Live-Anhaken
        (`_on_item_changed`) muessen die Eltern-Knoten (Sets / Kategorie-
        Ordner) expandiert sein – der Baum startet eingeklappt, nur die
        Top-Level-Gruppen sind in _populate() expandiert. Ohne Expansion
        bleiben angehakte Services/Plugins in eingeklappten Eltern unsichtbar.
        setExpanded feuert itemExpanded -> _refresh_expand_label ('>'/'⌄'-
        Label-Sync); waehrend `_updating_checks == True` ignoriert
        _on_item_changed die dadurch ausgeloesten spurious itemChanged-Events.
        """
        node = item
        hops = 0
        while node is not None and isValid(node) and hops < 64:
            node = node.parent()
            if node is None or not isValid(node):
                break
            try:
                if node.childCount() > 0 and not node.isExpanded():
                    node.setExpanded(True)
            except (RuntimeError, AttributeError):
                break
            hops += 1
