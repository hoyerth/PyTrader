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
              05.08.2026 (Ausfuehrungsdatum): An den Namen jedes Service-
              Knotens haengt das Datum der letzten Ausfuehrung in Klammern:
              'prox_1 (05.08.26)' (DD.MM.JJ aus MAX(created_at) des
              feature_store je feature_id) – ohne Eintrag '(--.--.--)'.
  * Spalte 1: Schmale Status-Spalte ganz RECHTS (Fixed-Spalte, fest am
              rechten Rand verankert) – pro Zeile ein echter Info-Button
              (QPushButton "ℹ", Icon-Breite ~20 px). Badge-TEXTE werden
              NICHT mehr angezeigt (Bugfix 05.08.2026: der Button ersetzt
              die frueheren Text-Badges bzw. das gekuerzte ASCII-'i').
              Der Button-Tooltip zeigt den Indikator-Namen ('aktiv
              <Indikator>' wenn der Indikator im Chart aktiv ist, sonst
              'im <Indikator>' – Bugfix 05.08.2026: Aktiv-Pruefung ueber
              die indicator_id des zugehoerigen Indikators). Gehoert eine
              Zeile (Service/Plugin/Set) einem Indikator, ist der Button
              gelb (#FFD700) eingefaerbt, sonst neutral. Klick oeffnet den
              Beschreibungs-Dialog (Signal `info_requested`).

Der Baum wird ausschliesslich aus dem `ServiceSelectorModel` befuellt
(lesendes Datenmodell, Invariante 4: kein SQL in UI) und aktualisiert sich
automatisch ueber `data_changed`/EventBus. Der `ServiceSelectorWidget` nutzt
den MasterTree im Modus `FULL_EDIT` (seit 05.08.2026 ohne Aktions-Toolbar –
volle vertikale Hoehe, alle Aktionen via Kontextmenue).

Signale:
  * selection_changed(set_id, service_id) – bei jeder Baum-Selektion
    (set_id/service_id koennen leer sein, wenn nichts Konkretes gewaehlt ist).
  * info_requested(set_id, service_id, plugin_id) – Klick auf den Info-Button
    (Spalte 1). Je nach Zeilentyp sind nur die passenden Felder gefuellt:
      Service-Zeile: set_id + service_id + plugin_id
      Set-Zeile:      set_id (service_id/plugin_id leer)
      Plugin-Zeile:   plugin_id (set_id/service_id leer)
  * Kontextmenue (Bugfix 05.08.2026, strikt entkoppelt – der Orchestrator
    verknuepft die Aktionen mit seinen Handlern):
      create_set_requested()                          – 'Neues Set anlegen'
      rename_set_requested(set_id)                    – 'Set umbenennen'
      add_set_service_requested(set_id)               – 'Service hinzufuegen'
      delete_set_requested(set_id)                    – 'Set loeschen (Papierkorb)'
      move_service_requested(set_id, service_id, delta) – Order ▲ (-1) / ▼ (+1)
      remove_service_requested(set_id, service_id)    – 'Service entfernen'
      run_service_requested(set_id, instance_id)      – '▶️ Diesen Service ausführen'
      run_set_requested(set_id)                        – '▶️ Alle Services ausführen'
    (Service-Info nutzt das bestehende `info_requested`-Signal.)
  * group_activated(group) – Klick auf einen (nicht selektierbaren) Gruppen-
    Knoten (z.B. 'sets' / 'standalone' / 'plugins'). Das Signal bleibt fuer
    potenzielle Aufrufer erhalten (die fruehere Toolbar-State-Nutzung ist
    seit 05.08.2026 entfernt).
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHeaderView, QMenu, QPushButton, QTreeWidget, QTreeWidgetItem,
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
# WICHTIG (05.08.2026): Der Text-'i' ist durch den echten Info-Button ersetzt;
# die Konstante bleibt nur als Test-Referenz erhalten (Historik).
BADGE_TRUNCATE_ICON = "i"

# Bugfix 05.08.2026: Echter Info-Button (QPushButton "ℹ", Icon-Breite) in
# Spalte 1 statt Badge-Text/'i'-Zeichen. Die Status-Spalte wird auf die
# Button-Breite verkleinert (Spalte 0 ist Stretch und bekommt den freien
# Platz). Der Button erscheint auf ALLEN Service-/Plugin-/Set-Zeilen; gehoert
# die Zeile einem Indikator, ist er gelb (#FFD700) und traegt den Tooltip
# 'aktiv/im <Indikator>' (Namenslogik unveraendert aus _apply_badge).
INFO_BUTTON_TEXT = "ℹ"
INFO_BUTTON_SIZE = 20          # ~Icon-Breite
INFO_BUTTON_WIDTH = 24         # Spaltenbreite (Status-Spalte)
INFO_BUTTON_COLOR_INDICATOR = "#FFD700"   # gelb bei Indikator-Zugehoerigkeit
INFO_BUTTON_COLOR_NEUTRAL = "#666666"     # neutral sonst

# Bugfix 3.0 (04.08.2026): Status-Spalte (Spalte 1) ist eine schmale
# Festbreiten-Spalte ganz rechts. Die Breite richtet sich seit 05.08.2026
# nach dem Info-Button (INFO_BUTTON_WIDTH); BADGE_COLUMN_WIDTH bleibt als
# Test-Referenz fuer die historische Text-Badge-Breite erhalten.
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
    # Bugfix 05.08.2026: Klick auf den Info-Button (Spalte 1).
    # Argumente (set_id, service_id, plugin_id) – je nach Zeilentyp gefuellt.
    info_requested = Signal(str, str, str)
    # Bugfix 05.08.2026: Kontextmenue (Rechtsklick) – entkoppelt; der
    # Orchestrator (ServiceWindow) verknuepft die Aktionen mit seinen Handlern.
    create_set_requested = Signal()
    rename_set_requested = Signal(str)          # set_id
    add_set_service_requested = Signal(str)     # set_id
    delete_set_requested = Signal(str)          # set_id
    move_service_requested = Signal(str, str, int)  # set_id, service_id, delta
    remove_service_requested = Signal(str, str)     # set_id, service_id
    # Bugfix 05.08.2026: Kontextmenue 'Papierkorb löschen' – endgueltig
    # leeren (Orchestrator fuehrt die doppelte Sicherheitsabfrage aus).
    purge_trash_requested = Signal()
    # Bugfix 05.08.2026: Klick auf einen (nicht selektierbaren) Gruppen-Knoten
    # (group id: 'sets' / 'standalone' / 'plugins'). Das Signal bleibt fuer
    # potenzielle Aufrufer erhalten (keine Toolbar-Verwendung mehr).
    group_activated = Signal(str)
    # 05.08.2026 (Ausfuehrungsdatum & Kontextmenue-Ausfuehrung):
    #   run_service_requested(set_id, instance_id) – '▶️ Diesen Service ausfuehren'
    #   run_set_requested(set_id)                   – '▶️ Alle Services ausfuehren'
    # Der Orchestrator (ServiceWindow) startet dafuer den gezielten
    # ServiceRunWorker (kein globaler Massen-Scan) und zeigt zuvor den
    # Bestaetigungsdialog (Set/Service + Symbol/Timeframe).
    run_service_requested = Signal(str, str)
    run_set_requested = Signal(str)

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
            header.resizeSection(1, INFO_BUTTON_WIDTH)
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

        # Bugfix 05.08.2026: Kontextmenue per Rechtsklick (dynamisch je
        # Knotentyp, siehe _show_context_menu). Die Aktionen sind entkoppelt
        # (Signale) – der Orchestrator verknuepft sie mit seinen Handlern.
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

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
        # Bugfix 05.08.2026: Info-Buttons (Spalte 1) NACH dem vollstaendigen
        # Baum-Aufbau anhaengen – setItemWidget() verlangt, dass das Item
        # bereits Teil des TreeWidgets ist (sonst kein sichtbarer Button).
        self._attach_item_buttons()

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
        # Bugfix 05.08.2026: Gehoert das Set einem Indikator, traegt der
        # Info-Button (Spalte 1) den Tooltip 'aktiv/im <Indikator>' (siehe
        # _apply_set_badge und _attach_item_buttons).
        self._apply_set_badge(set_item, child.get("definition") or child)
        for svc in services:
            # Keine fuehrenden Leerzeichen im Text: die Einrueckung der
            # Untereintraege kommt aus setIndentation(LEVEL_INDENT).
            # 05.08.2026 (Ausfuehrungsdatum): Das Datum der letzten
            # Ausfuehrung (DD.MM.JJ, aus dem feature_store) haengt direkt am
            # Service-Namen: 'prox_1 (05.08.26)' – ohne Eintrag '(--.--.--)'.
            plugin_id = svc.get("plugin_id") or ""
            last_exec = str(svc.get("last_execution") or "(--.--.--)")
            svc_item = QTreeWidgetItem([
                f"{svc.get('instance_id')} ({last_exec})",
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

        * Spalte 1: KEIN Badge-Text mehr (Bugfix 05.08.2026) – den Platz
          nimmt der echte Info-Button ein (siehe _attach_item_buttons).
        * Tooltip (Bugfix 05.08.2026): ODER-Logik auf Indikator-Basis –
          a) Service wird aktiv von einem Indikator verwendet
             -> 'aktiv <Indikator>'
          b) sonst, wenn der Service zu einem Indikator gehoert
             -> 'im <Indikator>'
          Die Aktiv-Pruefung beruecksichtigt den ZUGEHOERIGEN Indikator
          (metadata['indicator_id']), nicht nur die Plugin-ID selbst –
          dadurch greift Variante a) auch fuer Services (grid_lines/
          proximity), die IN einem aktiven Indikator (GridLiquidityIndicator)
          laufen. Der Tooltip wird auf Spalte 0 UND Spalte 1 gesetzt
          (Spalte 1 uebernimmt ihn der Info-Button).
        """
        # Badge-Text entfaellt in Spalte 1 (Info-Button statt Text-Badge).
        item.setText(1, "")
        if self.model.belongs_to_indicator(plugin_id):
            name = self.model.get_indicator_display_name(plugin_id)
            tooltip = (f"aktiv {name}" if self.model.is_active_in_chart(plugin_id)
                       else f"im {name}")
        else:
            tooltip = ""
        item.setToolTip(0, tooltip)
        item.setToolTip(1, tooltip)

    def _apply_set_badge(self, item: QTreeWidgetItem,
                         definition: Dict[str, Any]) -> None:
        """Set-Badge (Bugfix 05.08.2026): gehoert ein Service-Set einem
        Indikator, traegt der Info-Button (Spalte 1) die Tooltip-Namenslogik
        aus _apply_badge ('aktiv <Indikator>' / 'im <Indikator>'). Mehrere
        Indikatoren im Set werden mit ' + ' verknuepft. Ohne Indikator-
        Zugehoerigkeit bleibt Spalte 1 leer (neutraler Button, kein Tooltip).
        Spalte 0 behaelt den 'Service-Set: <set_id>'-Tooltip (siehe
        _build_set_item) – der Set-Bezug bleibt erhalten.
        """
        names = self.model.get_set_indicator_names(definition or {})
        if not names:
            item.setToolTip(1, "")
            return
        label = " + ".join(names)
        tooltip = (f"aktiv {label}" if self.model.is_set_active(definition or {})
                   else f"im {label}")
        item.setToolTip(1, tooltip)

    def _attach_item_buttons(self) -> None:
        """Haengt die Info-Buttons (Spalte 1) an alle Service-/Set-/Plugin-
        Zeilen (Bugfix 05.08.2026).

        Der Button ist ein kompakter QPushButton ("ℹ", Icon-Breite) und ersetzt
        die frueheren Text-Badges. Gehoert die Zeile einem Indikator (Tooltip
        aus _apply_badge/_apply_set_badge vorhanden), ist er gelb (#FFD700)
        eingefaerbt und traegt den Tooltip; sonst neutral. Der Klick emittiert
        `info_requested` mit den zeilenspezifischen Daten:
          Service-Zeile -> (set_id, instance_id, plugin_id)
          Set-Zeile      -> (set_id, "", "")
          Plugin-Zeile   -> ("", "", plugin_id)
        Gruppen-Knoten (📁/⚡/📦) erhalten bewusst KEINEN Button.
        """
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                node_type = item.data(0, ROLE_NODE_TYPE)
                if node_type not in (TYPE_SERVICE, TYPE_SET, TYPE_PLUGIN):
                    continue
                tooltip = item.toolTip(1) or ""
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                service_id = ""
                plugin_id = ""
                if node_type == TYPE_SERVICE:
                    service_id = str(item.data(0, ROLE_INSTANCE_ID) or "")
                    plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
                elif node_type == TYPE_PLUGIN:
                    # Plugin-Zeilen: set_id bewusst leer (die ROLE_SET_ID
                    # traegt nur die Gruppenkennung 'standalone'/'plugins').
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
                btn.clicked.connect(
                    lambda _=False, s=set_id, svc=service_id, pid=plugin_id:
                    self.info_requested.emit(s, svc, pid))
                self.setItemWidget(item, 1, btn)
        except (RuntimeError, AttributeError):
            pass

    # -------------------------------------------------------------------------
    # Kontextmenue (Bugfix 05.08.2026, entkoppelt)
    # -------------------------------------------------------------------------

    def _show_context_menu(self, pos) -> None:
        """Baut das Kontextmenue fuer den Rechtsklick dynamisch je Knotentyp.

        Die Aktionen emittieren AUSSCHLIESSLICH Signale – der Orchestrator
        (ServiceWindow) verknuepft sie mit seinen Handlern:

          * Gruppe 📁 (sets)      -> 'Neues Set anlegen' (create_set_requested)
          * Set-Knoten            -> '▶️ Alle Services ausführen' (run_set),
                                     'Set umbenennen', 'Service hinzufuegen',
                                     'Set loeschen' (rename/add/delete-requested)
          * Service-Knoten        -> '▶️ Diesen Service ausführen' (run_service),
                                     'Order ▲/▼', 'Service entfernen',
                                     'Service-Info anzeigen' (move/remove/
                                     info_requested)
          * Ausserhalb eines Sets (Plugin-Zeilen, ⚡-/📦-Gruppen):
                                     Order/Entfernen/Umbenennen ausgegraut;
                                     'Service-Info anzeigen' bleibt fuer
                                     Plugin-Zeilen aktiv.

        isValid-Guards: Bei wildem Klicken koennen Items zwischen itemAt() und
        Datenzugriff C++-seitig zerstoert sein (Access-Violation-Schutz).
        """
        try:
            item = self.itemAt(pos)
            if item is None or not isValid(item):
                return
            # Bugfix 05.08.2026: Rechtsklick togglet aufklappbare Knoten
            # (Konsistenz mit Linksklick), damit das Kontextmenue immer auf
            # dem sichtbaren Knoten steht.
            try:
                if item.childCount() > 0:
                    item.setExpanded(not item.isExpanded())
            except (RuntimeError, AttributeError):
                pass
            node_type = item.data(0, ROLE_NODE_TYPE)
            menu = QMenu(self)
            if node_type == TYPE_GROUP:
                group = str(item.data(0, ROLE_SET_ID) or "")
                if group == self.model.GROUP_SETS:
                    act = menu.addAction("Neues Set anlegen")
                    act.triggered.connect(
                        lambda _=False: self.create_set_requested.emit())
                else:
                    self._add_outside_set_actions(menu, item)
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            if node_type == TYPE_SET:
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                # 05.08.2026: 'Alle Services ausführen' – gezielter Run des
                # Sets (kein globaler Massen-Scan); der Orchestrator zeigt
                # den Bestaetigungsdialog (Set + Symbol/Timeframe).
                act_run = menu.addAction("▶️ Alle Services ausführen")
                act_run.triggered.connect(
                    lambda _=False, s=set_id:
                    self.run_set_requested.emit(s))
                menu.addSeparator()
                act_rename = menu.addAction("Set umbenennen")
                act_rename.triggered.connect(
                    lambda _=False, s=set_id:
                    self.rename_set_requested.emit(s))
                act_add = menu.addAction("Service hinzufügen")
                act_add.triggered.connect(
                    lambda _=False, s=set_id:
                    self.add_set_service_requested.emit(s))
                menu.addSeparator()
                act_del = menu.addAction("Set löschen")
                act_del.triggered.connect(
                    lambda _=False, s=set_id:
                    self.delete_set_requested.emit(s))
                menu.addSeparator()
                act_purge = menu.addAction("Papierkorb löschen…")
                act_purge.triggered.connect(
                    lambda _=False: self.purge_trash_requested.emit())
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            if node_type == TYPE_SERVICE:
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                service_id = str(item.data(0, ROLE_INSTANCE_ID) or "")
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
                # 05.08.2026: 'Diesen Service ausführen' – gezielter Run des
                # Einzel-Services (inkl. Upstream-Abhaengigkeiten im Set);
                # der Orchestrator zeigt den Bestaetigungsdialog (Service +
                # Symbol/Timeframe).
                act_run = menu.addAction("▶️ Diesen Service ausführen")
                act_run.triggered.connect(
                    lambda _=False, s=set_id, i=service_id:
                    self.run_service_requested.emit(s, i))
                menu.addSeparator()
                act_up = menu.addAction("Order ▲")
                act_up.triggered.connect(
                    lambda _=False, s=set_id, i=service_id:
                    self.move_service_requested.emit(s, i, -1))
                act_down = menu.addAction("Order ▼")
                act_down.triggered.connect(
                    lambda _=False, s=set_id, i=service_id:
                    self.move_service_requested.emit(s, i, 1))
                menu.addSeparator()
                act_rem = menu.addAction("Service entfernen")
                act_rem.triggered.connect(
                    lambda _=False, s=set_id, i=service_id:
                    self.remove_service_requested.emit(s, i))
                act_info = menu.addAction("Service-Info anzeigen")
                act_info.triggered.connect(
                    lambda _=False, s=set_id, i=service_id, p=plugin_id:
                    self.info_requested.emit(s, i, p))
                menu.addSeparator()
                act_purge = menu.addAction("Papierkorb löschen…")
                act_purge.triggered.connect(
                    lambda _=False: self.purge_trash_requested.emit())
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            # Plugin-Zeile (standalone/plugins) – nur Info aktiv
            self._add_outside_set_actions(menu, item)
            menu.exec(self.viewport().mapToGlobal(pos))
        except (RuntimeError, AttributeError):
            pass

    def _add_outside_set_actions(self, menu: QMenu, item) -> None:
        """Fuegt die ausgegrauten Struktur-Aktionen fuer Knoten ausserhalb
        eines Sets hinzu (Plugin-Zeilen sowie ⚡- und 📦-Gruppen). Bei
        Plugin-Zeilen bleibt 'Service-Info anzeigen' aktiv."""
        menu.addAction("Order ▲").setEnabled(False)
        menu.addAction("Order ▼").setEnabled(False)
        menu.addSeparator()
        menu.addAction("Service entfernen").setEnabled(False)
        if item is not None and isValid(item) and \
                item.data(0, ROLE_NODE_TYPE) == TYPE_PLUGIN:
            menu.addSeparator()
            plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
            act_info = menu.addAction("Service-Info anzeigen")
            act_info.triggered.connect(
                lambda _=False, p=plugin_id:
                self.info_requested.emit("", "", p))

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

        Bugfix 05.08.2026: Klick auf einen (nicht selektierbaren) Gruppen-
        Knoten emittiert zusaetzlich `group_activated(group)` – das Signal
        bleibt fuer potenzielle Aufrufer erhalten (die fruehere Toolbar-State-
        Nutzung ist seit 05.08.2026 entfernt).
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
                if item.data(0, ROLE_NODE_TYPE) == TYPE_GROUP:
                    self.group_activated.emit(
                        str(item.data(0, ROLE_SET_ID) or ""))
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
