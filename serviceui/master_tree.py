# serviceui/master_tree.py
"""
Service-UI: 2-Spalten-MasterTree (Phase 15 15.02).

Hierarchische Darstellung der Service-Landschaft:

  * Spalte 0: Knoten – 📁 Service-Sets (mit ihren Service-Instanzen),
              📦 Alle verfuegbaren Services (kategorisierte Ordner).
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
              Gilt seit 05.08.2026 (Punkt 4) auch fuer Standalone-Services
              und Plugin-Zeilen ('srv_proximity (02.08.26)').
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
      open_trash_requested()                           – '🗑️ Papierkorb öffnen...'
    (Service-Info nutzt das bestehende `info_requested`-Signal.)
"""

from typing import Any, Dict, List, Optional

import json

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QHeaderView, QInputDialog, QMenu, QPushButton, QTreeWidget,
    QTreeWidgetItem,
)

# 18.01.03 (Dynamic Tree Management): MIME-Typ fuer den internen
# Kategorie-Drag & Drop. Die MIME-Daten kodieren den gezogenen Knoten als
# JSON: {"node_type": "set|plugin|category", "group": "sets|plugins",
#         "id": <set_id|plugin_id|category-path>, "path": <Quell-Pfad>}.
MIME_CATEGORY_MOVE = "application/x-pytrader-category-move"

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
# 20.04 (Q6/Q7): Zusaetzliche Rollen fuer Clone-Knoten (TYPE_CLONE) und
# die Archiv-Kennzeichnung. ROLE_INSTANCE_HASH traegt den 8-stelligen
# Parameter-Hash eines Clones (generate_instance_hash); ROLE_ARCHIVED=True
# markiert archivierte Knoten (non-checkable, Archiv-Safety).
ROLE_INSTANCE_HASH = Qt.UserRole + 4
ROLE_ARCHIVED = Qt.UserRole + 5

# 15.03-E (Multi-Select): Klickzone der Checkbox-Indikatoren in Spalte 0.
# Klicks links dieser Zone (innerhalb der Item-Zeile) werden dem Qt-Default
# ueberlassen, damit die Checkbox togglet (itemChanged feuert); Klicks
# rechts davon togglen weiterhin das Auf-/Zuklappen (mousePressEvent).
CHECKBOX_ZONE_WIDTH = 24

#: Knotentypen
TYPE_GROUP = "group"
TYPE_SET = "set"
TYPE_SERVICE = "service"
TYPE_PLUGIN = "plugin"
# 20.04 (Q7): Clone-/Preset-Knoten (Kind eines Plugin-Parents in der
# Services-Gruppe). Traegt ROLE_PLUGIN_ID (plugin_id des Parents) und
# ROLE_INSTANCE_HASH; aktive Clones sind anhakbar, archivierte nicht.
TYPE_CLONE = "clone"
# 16.08 (K3): Kategorie-Ordner-Knoten (Dynamic Category Trees). Nicht
# auswaehlbar, expandierbar; traegt KEINEN Info-Button (K5), keine Badges
# und ist im Checkbox-Modus nicht anhakbar (K4).
TYPE_CATEGORY = "category"

# Bugfix 2.1 (04.08.2026, aktualisiert): Lange Relationstexte in der Badge-
# Spalte (z. B. "📌 im Ind_FixedGridProximity | ⚪ inaktiv in ...") werden auf
# das Info-Zeichen 'i' gekuerzt – der Indikator-Name steht im Tooltip der
# Spalte 1 (keine extrem breiten Spalten im MasterTree).
MAX_BADGE_CELL_CHARS = 24
# Bugfix 04.08.2026 (Punkt 5): ASCII 'i' statt Unicode '🛈' (U+1F5D8) – das
# Emoji rendert in den Qt-Fonts unter Windows nicht zuverlaessig (tofu-Box).
# WICHTIG (05.08.2026): Der Text-'i' ist durch den echten Info-Button ersetzt;
# die Konstante bleibt nur als Test-Referenz erhalten (Historik).
BADGE_TRUNCATE_ICON = "i"

# Bugfix 20.03.01 (09.08.2026): Das Unicode-Zeichen "ℹ" (U+2139) rendert
# unter Windows in Qt bei fehlendem Font als Tofu-Box – der Info-Button
# war nicht mehr erkennbar (User-Meldung 'i-Button im Tree geht nicht
# mehr'; vgl. Bugfix 04.08.2026, Punkt 5: Unicode-Badge '🛈' ebenfalls
# durch ASCII 'i' ersetzt). Daher wieder ASCII 'i' als Button-Beschriftung.
# Der QPushButton (Spalte 1) ersetzt seit 05.08.2026 das Badge-Text-'i';
# die Status-Spalte wird auf die Button-Breite verkleinert (Spalte 0 ist
# Stretch und bekommt den freien Platz). Der Button erscheint auf ALLEN
# Service-/Plugin-/Set-Zeilen; gehoert die Zeile einem Indikator, ist er
# gelb (#FFD700) und traegt den Tooltip 'aktiv/im <Indikator>'
# (Namenslogik unveraendert aus _apply_badge).
INFO_BUTTON_TEXT = "i"
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
    # Bugfix 06.08.2026 (Bugfix-Runde 3, Punkte 1-7): Klick-Scope der
    # geklickten Zeile (node_type, set_id, service_id, plugin_id). Wird aus
    # `mousePressEvent` bei JEDEM Mausklick auf eine gueltige Zeile emittiert
    # (auch Checkbox-Zone / Expand-Toggle, unabhaengig von einer Selektion).
    # Der ServiceSelectorDialog zeigt daraus die Parameter im Read-Only-Panel
    # (analog service_win: Set/Service-in-Set -> alle Set-Services; Plugin-
    # Zeile -> nur dieser Service; sonst leer).
    selection_details = Signal(str, str, str, str)
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
    # Phase 15: Kontextmenue '🗑️ Papierkorb öffnen...' (Haupt-Gruppe
    # 📁 Service-Sets) – oeffnet den Papierkorb-Dialog. Der Orchestrator
    # (ServiceWindow) ruft dieselbe Methode auf wie der Papierkorb-Button
    # in der Aktionsleiste (show_trash_dialog()).
    open_trash_requested = Signal()
    # 15.03-E (Multi-Select): Checkbox-Zustand wurde geaendert (SELECT_MULTI).
    # Der ServiceSelectorDialog lauscht darauf und baut sein rechter
    # Read-Only-Parameter-Panel neu auf.
    checked_changed = Signal()
    # 05.08.2026 (Ausfuehrungsdatum & Kontextmenue-Ausfuehrung):
    #   run_service_requested(set_id, instance_id) – '▶️ Diesen Service ausfuehren'
    #   run_set_requested(set_id)                   – '▶️ Alle Services ausfuehren'
    # Der Orchestrator (ServiceWindow) startet dafuer den gezielten
    # ServiceRunWorker (kein globaler Massen-Scan) und zeigt zuvor den
    # Bestaetigungsdialog (Set/Service + Symbol/Timeframe).
    run_service_requested = Signal(str, str)
    run_set_requested = Signal(str)
    # 17.01.02 (Bugfix-Runde): Run-/Info-Aktionen fuer die Services-Gruppe.
    #   run_plugin_requested(plugin_id)  – '▶️ Diesen Service ausführen'
    #                                      (Einzel-Plugin-Zeile, ohne Set)
    #   run_category_requested(group, path) – '▶️ Alle Services ausführen'
    #                                      (Kategorie-Ordner, rekursiv; path
    #                                      z.B. 'Swing Points/Geometrie';
    #                                      group = 'sets' | 'plugins',
    #                                      18.01.03: Sets-Ordner moeglich)
    #   category_info_requested(group, path) – Info-Button auf Kategorie-Ordnern
    run_plugin_requested = Signal(str)
    run_category_requested = Signal(str, str)
    category_info_requested = Signal(str, str)
    # 18.01.03 (Dynamic Tree Management): Ordner-CRUD & Kategorie-Drag&Drop.
    #   create_folder_requested(group, full_path) – 'Neuer Ordner' (der
    #       MasterTree zeigt den Namensdialog; der Orchestrator PERSISTIERT
    #       den Ordner ueber global_settings (tree_folders_<group>,
    #       service_set_utils.create_empty_folder) – E3-revidiert
    #       08.08.2026: Leere Ordner verschwinden NICHT beim Refresh).
    #   delete_folder_requested(group, path) – 'Ordner löschen' (manuelle
    #       Loeschung; der Orchestrator entfernt den Eintrag ueber
    #       service_set_utils.delete_empty_folder).
    #   rename_folder_requested(group, old_path, new_path) – 'Umbenennen'
    #       (String-Replace aller Kinder + persistierter Leere-Ordner im
    #       Orchestrator).
    #   folder_item_moved(node_type, item_id, new_path) – Drop eines Sets
    #       (TYPE_SET) bzw. Plugins (TYPE_PLUGIN) in einen Ziel-Ordner.
    #   folder_moved(group, old_path, new_path) – Drop eines Ordners auf
    #       einen anderen Ordner (verschiebt alle Kinder rekursiv).
    create_folder_requested = Signal(str, str)
    delete_folder_requested = Signal(str, str)
    rename_folder_requested = Signal(str, str, str)
    folder_item_moved = Signal(str, str, str)
    folder_moved = Signal(str, str, str)
    # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im Kontextmenue (Service-/Clone-
    # Zeilen). Der Orchestrator (ServiceWindow) verknuepft die Aktionen mit
    # seinen Handlern:
    #   data_only_purge_requested(set_id, service_id, plugin_id,
    #                             instance_hash)
    #       – 'Data Only Löschen': NUR die berechneten Feature-Daten der
    #         Instanz purgen (FeatureBuilder.purge_instance_data, Q5). Bei
    #         Clone-Zeilen sind set_id/service_id leer (plugin_id + Hash).
    #   delete_complete_requested(set_id, service_id, plugin_id,
    #                             instance_hash)
    #       – 'Vollständig Löschen': Instanz/Preset + Feature-Daten entfernen
    #         (2-stufige Sicherheitsabfrage im Orchestrator).
    #   doc_log_requested(set_id, service_id, plugin_id, instance_hash)
    #       – 'Doc Log bearbeiten': Negativ-Wissen editieren
    #         (ServiceInstanceConfig.doc_log bzw. indicator_presets.doc_log
    #         bei Clones).
    #   duplicate_variant_requested(set_id, service_id, plugin_id,
    #                               instance_hash)
    #       – 'Als Variante duplizieren' (Q8): neue Instanz/Preset-Variante
    #         mit kopierten Parametern (neue instance_id / Preset-Name).
    data_only_purge_requested = Signal(str, str, str, str)
    delete_complete_requested = Signal(str, str, str, str)
    doc_log_requested = Signal(str, str, str, str)
    duplicate_variant_requested = Signal(str, str, str, str)

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

        # Phase 15 (Dirty-State): instance_ids mit ungespeicherten Parameter-
        # Aenderungen. Die Sternchen-Markierung ('*' am Service-Knoten) wird
        # bei jedem Baum-Neuaufbau aus diesem Set re-appliziert (set_instance_
        # dirty / clear_dirty_markers halten es aktuell).
        self._dirty_instance_ids: set = set()

        # 15.03-E (Multi-Select): Checkbox-Modus (SELECT_MULTI, nur im
        # ServiceSelectorDialog). _checked_items haelt die angehakten Knoten
        # als (node_type, set_id, key_id)-Tupel – key_id = instance_id bei
        # Services bzw. plugin_id bei Standalone-/Plugin-Zeilen. Der Zustand
        # bleibt ueber data_changed-Baum-Neuaufbauten erhalten (analog zum
        # Dirty-Set); Set-Knoten sind Tri-State und werden IMMER aus ihren
        # Service-Kindern abgeleitet (kein eigener Key).
        self._checkable: bool = False
        self._checked_items: set = set()
        self._updating_checks: bool = False

        # 18.01.03 (Dynamic Tree Management): Interner Kategorie-Drag&Drop.
        # Nur Sets/Plugins/Ordner sind ziehbar (E4 – kein Service-Reorder);
        # der Drop aktualisiert den Kategorie-Pfad ueber die Signale
        # folder_item_moved/folder_moved (Modell/Repositories persistieren).
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QTreeWidget.DragDrop)  # type: ignore[attr-defined]
        #: Beim Mausklick gemerktes Item – Quelle eines beginnenden Drags
        #: (mousePressEvent -> startDrag).
        self._drag_source: Optional[QTreeWidgetItem] = None
        # 18.01.03 (Bugfix 08.08.2026): Aufklapp-Zustand ueber Baum-
        # Neuaufbauten hinweg erhalten. Ein Ordner-/Item-Move oder eine
        # Ordner-Erstellung triggert data_changed -> _populate(); der Baum
        # soll dabei NICHT zusammenklappen. Schluessel im RAM:
        #   ("cat", group, kategorie-pfad) fuer Ordner,
        #   ("set", set_id)                 fuer Set-Knoten.
        self._expand_after_rebuild: set = set()

        self._populate()
        self.itemSelectionChanged.connect(self._emit_selection)
        # 15.03-E: Checkbox-Aenderungen (Klick) -> Tri-State + Signal.
        self.itemChanged.connect(self._on_item_changed)
        self.model.data_changed.connect(self._populate)

    # -------------------------------------------------------------------------
    # Befuellung aus dem Modell
    # -------------------------------------------------------------------------

    def _populate(self) -> None:
        """Baut den Baum aus model.build_tree() neu auf (deterministisch)."""
        current = self._safe_current_selection()
        # 18.01.03 (Bugfix 08.08.2026): Expansion-Zustand VOR dem Neuaufbau
        # sichern – der Baum soll nach Ordner-Erstellung/-Verschiebung NICHT
        # zusammenklappen (_collect_expanded_state liest den IST-Baum).
        expanded = self._collect_expanded_state()
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
        # 18.01.03 (Bugfix 08.08.2026): Expansion unter blockSignals
        # wiederherstellen (keine Signal-Seiteneffekte; die '>'/'⌄'-Labels
        # refresht der anschliessende Label-Block explizit).
        self._apply_expanded_state(expanded)
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
        # 15.03-E (Multi-Select): _checked_items mit dem IST-Baum abgleichen
        # (stale Keys geloeschter Services/Plugins entfernen).
        self._sync_checked_from_tree()
        # Phase 15 (Dirty-State): Sternchen-Markierungen ungespeicherter
        # Parameter-Aenderungen nach einem Neuaufbau wieder anwenden
        # (data_changed -> _populate wuerde sie sonst verlieren). Waehrend
        # dessen ist die Checkbox-Verarbeitung gesperrt (die Text-Aenderung
        # wuerde sonst ein spurious checked_changed emittieren).
        self._updating_checks = True
        try:
            for iid in list(getattr(self, "_dirty_instance_ids", set())):
                self._apply_dirty_label(iid, True)
        finally:
            self._updating_checks = False
        # 18.01.03 (E3-revidiert): Leere Ordner kommen jetzt aus dem Modell
        # (build_tree mischt die persistierten tree_folders_<group>-Pfade
        # ein) – ein separater UI-Zustand ist nicht mehr noetig.
        pass

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
        """Erzeugt das Kind-Item fuer einen Knoten der Gruppe `group`.

        16.08 (K2/K3): Ordner-Knoten (group == GROUP_CATEGORY) werden
        rekursiv aufgebaut; Plugin-Blaetter in Ordnern nutzen weiterhin
        _build_plugin_item (Badge/Ausfuehrungsdatum unveraendert). Die
        Original-Gruppe (standalone/plugins) wird durch die Rekursion
        durchgereicht, damit ROLE_SET_ID der Blaetter stabil bleibt.
        """
        if isinstance(child, dict) and child.get("group") == self.model.GROUP_CATEGORY:
            return self._build_category_item(child, group)
        if group == self.model.GROUP_SETS:
            return self._build_set_item(child)
        # 17.01.01: GROUP_STANDALONE entfaellt ersatzlos – Plugin-Zeilen
        # existieren nur noch in GROUP_PLUGINS (Kategorien-Ordner inklusive).
        if group == self.model.GROUP_PLUGINS:
            return self._build_plugin_item(child, group)
        return None

    def _build_category_item(self, child: Dict[str, Any],
                             group: str) -> QTreeWidgetItem:
        """Erzeugt einen Ordner-Knoten (K3, 16.08).

        Nicht auswaehlbar, expandierbar, '📁 <Name>' im Label (aus dem
        Modell, K2-Format); Kinder rekursiv ueber _build_child_item.
        Ordner tragen KEINEN Info-Button (K5 – _attach_item_buttons
        ueberspringt TYPE_CATEGORY automatisch), keine Badges/Datum (K2)
        und sind im Checkbox-Modus nicht anhakbar (K4 – kein
        ItemIsUserCheckable). Die Selektion liefert fuer Ordner den
        Default-Pfad zurueck (K7).
        """
        label = _expandable_label(str(child.get("label") or "?"),
                                  bool(child.get("children")), False)
        cat_item = QTreeWidgetItem([label, ""])
        cat_item.setData(0, ROLE_NODE_TYPE, TYPE_CATEGORY)
        cat_item.setData(0, ROLE_SET_ID, str(child.get("label") or ""))
        # K3/K4: nicht auswaehlbar UND nicht anhakbar – Qt setzt
        # ItemIsUserCheckable standardmaessig, daher beide Flags entfernen.
        cat_item.setFlags(cat_item.flags()
                          & ~(Qt.ItemIsSelectable | Qt.ItemIsUserCheckable))
        for sub in child.get("children") or []:
            item = self._build_child_item(group, sub)
            if item is not None:
                cat_item.addChild(item)
        return cat_item

    def _build_set_item(self, child: Dict[str, Any]) -> QTreeWidgetItem:
        services = child.get("services", [])
        name = _expandable_label(str(child.get("display_name") or "Unbenannt"),
                                 bool(services), False)
        set_item = QTreeWidgetItem([name, ""])
        set_item.setData(0, ROLE_NODE_TYPE, TYPE_SET)
        set_item.setData(0, ROLE_SET_ID, child.get("set_id") or "")
        set_item.setToolTip(0, f"Service-Set: {child.get('set_id') or '?'}")
        # 20.04 (Q6): Archivierte Sets (is_archived=True) sind non-checkable
        # (Archive Safety) – sie liegen im '📁 Archiv'-Ordner der Sets-Gruppe.
        archived_set = bool(child.get("archived"))
        if archived_set:
            set_item.setData(0, ROLE_ARCHIVED, True)
        # 15.03-E (Multi-Select): Set-Knoten anhakbar – der Tri-State wird
        # NACH dem Anhaengen der Service-Kinder aus deren Zustaenden
        # abgeleitet (_apply_set_state).
        if self._checkable and not archived_set:
            set_item.setFlags(set_item.flags() | Qt.ItemIsUserCheckable)
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
            last_exec = str(svc.get("last_execution") or "--.--.--")
            svc_label = f"{svc.get('instance_id')} ({last_exec})"
            # 20.04 (Q6): Einzeln archivierte Instanzen tragen im Archiv
            # eine Kennzeichnung (is_archived=True -> non-checkable).
            svc_archived = bool(svc.get("is_archived"))
            if svc_archived:
                svc_label = f"🔹 {svc_label}"
            svc_item = QTreeWidgetItem([svc_label, ""])
            svc_item.setData(0, ROLE_NODE_TYPE, TYPE_SERVICE)
            svc_item.setData(0, ROLE_SET_ID, child.get("set_id") or "")
            svc_item.setData(0, ROLE_INSTANCE_ID, svc.get("instance_id") or "")
            svc_item.setData(0, ROLE_PLUGIN_ID, plugin_id)
            svc_item.setData(0, ROLE_INSTANCE_HASH,
                             str(svc.get("instance_hash") or ""))
            if svc_archived or archived_set:
                svc_item.setData(0, ROLE_ARCHIVED, True)
            # 15.03-E (Multi-Select): Service-Knoten anhakbar – Zustand aus
            # _checked_items re-applizieren (bleibt ueber Neuaufbauten erhalten).
            if self._checkable and not svc_archived and not archived_set:
                svc_item.setFlags(svc_item.flags() | Qt.ItemIsUserCheckable)
                key = (TYPE_SERVICE,
                       str(child.get("set_id") or ""),
                       str(svc.get("instance_id") or ""))
                state = (Qt.Checked if key in self._checked_items
                         else Qt.Unchecked)
                svc_item.setData(0, Qt.CheckStateRole, state)
            self._apply_badge(svc_item, plugin_id, svc.get("badge") or "")
            set_item.addChild(svc_item)
        if self._checkable:
            self._apply_set_state(set_item)
        return set_item

    def _build_plugin_item(self, child: Dict[str, Any],
                           group: str) -> QTreeWidgetItem:
        pid = child.get("plugin_id") or ""
        # Keine fuehrenden Leerzeichen: Einrueckung via setIndentation().
        # 05.08.2026 (Punkt 4): Das Datum der letzten Ausfuehrung (DD.MM.JJ,
        # aus dem feature_store) haengt auch an Standalone-/Plugin-Zeilen:
        # 'srv_proximity (02.08.26)' – ohne Eintrag '(--.--.--)'.
        last_exec = str(child.get("last_execution") or "--.--.--")
        clones = child.get("clones") or []
        archived_parent = bool(child.get("archived"))
        plugin_item = QTreeWidgetItem([f"{pid} ({last_exec})", ""])
        plugin_item.setData(0, ROLE_NODE_TYPE, TYPE_PLUGIN)
        plugin_item.setData(0, ROLE_SET_ID, group)
        plugin_item.setData(0, ROLE_PLUGIN_ID, pid)
        if archived_parent:
            plugin_item.setData(0, ROLE_ARCHIVED, True)
        # 20.04 (Q7): Plugins MIT Clones sind Template-Parents (nicht direkt
        # ausfuehrbar) – KEINE Checkbox am Plugin-Knoten; die Clones tragen
        # die Haken. Plugins OHNE Clones bleiben anhakbare flache Blaetter
        # (Bestandsverhalten, feature_id des Feature-Store = plugin_id).
        if clones:
            plugin_item.setFlags(
                plugin_item.flags() & ~Qt.ItemIsUserCheckable)
        elif self._checkable:
            plugin_item.setFlags(
                plugin_item.flags() | Qt.ItemIsUserCheckable)
            key = (TYPE_PLUGIN, "", pid)
            state = (Qt.Checked if key in self._checked_items
                     else Qt.Unchecked)
            plugin_item.setData(0, Qt.CheckStateRole, state)
        self._apply_badge(plugin_item, pid, child.get("badge") or "")
        for clone in clones:
            plugin_item.addChild(self._build_clone_item(clone, pid))
        return plugin_item

    def _build_clone_item(self, clone: Dict[str, Any],
                          plugin_id: str) -> QTreeWidgetItem:
        """Erzeugt ein Clone-/Preset-Kind unter einem Plugin-Parent (20.04).

        Label-Format (Doku §3): aktive Clones `🟢 <Preset> (#<hash>)`,
        archivierte Clones `🔹 <Preset> (#<hash>)`. Aktive Clones sind im
        Checkbox-Modus anhakbar; ARCHIVIERTE Clones sind non-checkable
        (Archive Safety, Q6) und emittieren keine IDs an Scans/Analytics.
        """
        preset_name = str(clone.get("preset_name") or "Default")
        instance_hash = str(clone.get("instance_hash") or "")
        archived = bool(clone.get("is_archived"))
        hash_suffix = f" (#{instance_hash})" if instance_hash else ""
        prefix = "🔹" if archived else "🟢"
        clone_item = QTreeWidgetItem([f"{prefix} {preset_name}{hash_suffix}", ""])
        clone_item.setData(0, ROLE_NODE_TYPE, TYPE_CLONE)
        clone_item.setData(0, ROLE_PLUGIN_ID, plugin_id)
        clone_item.setData(0, ROLE_INSTANCE_HASH, instance_hash)
        if archived:
            clone_item.setData(0, ROLE_ARCHIVED, True)
        # Tooltip: Plugin/Preset + Parameter + Doc-Log (Negativ-Wissen).
        tooltip = f"Plugin: {plugin_id}\nPreset: {preset_name}"
        params = clone.get("params") or {}
        if isinstance(params, dict) and params:
            try:
                tooltip += "\n" + ", ".join(
                    f"{k}={v}" for k, v in list(params.items())[:8])
            except Exception:
                pass
        doc_log = str(clone.get("doc_log") or "").strip()
        if doc_log:
            tooltip += f"\n📝 {doc_log}"
        clone_item.setToolTip(0, tooltip)
        # Checkbox nur fuer AKTIVE Clones im Checkbox-Modus (Q6).
        if self._checkable and not archived:
            clone_item.setFlags(
                clone_item.flags() | Qt.ItemIsUserCheckable)
            key = (TYPE_CLONE, plugin_id, instance_hash)
            state = (Qt.Checked if key in self._checked_items
                     else Qt.Unchecked)
            clone_item.setData(0, Qt.CheckStateRole, state)
        elif archived:
            # QTreeWidgetItem traegt ItemIsUserCheckable per Default – bei
            # ARCHIVIERTEN Clones explizit entfernen (Archive Safety, Q6).
            clone_item.setFlags(
                clone_item.flags() & ~Qt.ItemIsUserCheckable)
        return clone_item

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
          dadurch greift Variante a) auch fuer Services (srv_grid_lines/
          srv_proximity), die IN einem aktiven Indikator (Ind_FixedGridProximity)
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

    def _category_path_of(self, item) -> str:
        """Voller Kategorie-Pfad eines Ordner-Items (17.01.02).

        Sammelt die Ordner-Labels von der Wurzel bis zum Item und verkettet
        sie slash-separiert OHNE '📁 '-Praefix (z.B. 'Swing Points/Geometrie').
        Liefert '' fuer Nicht-Ordner-Items oder leere Ketten. Das Format
        entspricht exakt `ServiceSelectorModel.category_plugin_ids()`.
        """
        parts: List[str] = []
        node = item
        hops = 0
        while node is not None and isValid(node) and hops < 64:
            if node.data(0, ROLE_NODE_TYPE) == TYPE_CATEGORY:
                label = str(node.data(0, ROLE_SET_ID) or "").strip()
                if label.startswith("📁"):
                    label = label[len("📁"):].lstrip()
                if label:
                    parts.append(label)
            node = node.parent()
            hops += 1
        return "/".join(reversed(parts))

    # -------------------------------------------------------------------------
    # 18.01.03 (Dynamic Tree Management): Kategorie-Drag&Drop + Ordner-CRUD
    # -------------------------------------------------------------------------

    def _group_of(self, item) -> str:
        """Eltern-GRUPPE eines Items ('sets' / 'plugins', 18.01.03, L3).

        Wandert vom Item zur Top-Level-Gruppe (TYPE_GROUP) und liefert deren
        ROLE_SET_ID (GROUP_SETS/GROUP_PLUGINS). Leer, wenn keine Gruppe
        gefunden wird (defensiv).
        """
        node = item
        hops = 0
        while node is not None and isValid(node) and hops < 64:
            if node.data(0, ROLE_NODE_TYPE) == TYPE_GROUP:
                return str(node.data(0, ROLE_SET_ID) or "")
            node = node.parent()
            hops += 1
        return ""

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

    def _on_item_changed(self, item, column: int) -> None:
        """Aktualisiert die Checkbox-Zustaende (15.03-E, SELECT_MULTI).

        itemChanged feuert bei JEDER Daten-Aenderung eines Items; die Guards
        (`_checkable`, `_updating_checks`, Knotentyp) halten den Handler
        schlank. Set-Knoten propagieren ihren Zustand auf alle Service-
        Kinder; der Tri-State der Sets wird IMMER aus den Kindern abgeleitet
        (Qt bietet in QTreeWidget keine automatische Synchronisation).

        Bugfix 06.08.2026 (Punkte 1/2/6): `itemChanged` feuert auch bei
        TEXT-Aenderungen – z. B. `_refresh_expand_label` nach einem
        Zeilen-Klick auf einen Set-Knoten (Auf-/Zuklappen). Solche spurious
        Events duerfen die Haken NICHT veraendern: Es wird nur verarbeitet,
        wenn sich der CheckState tatsaechlich vom erwarteten Zustand
        unterscheidet (erwartet = aus `_checked_items` bzw. den Service-
        Kindern des Sets abgeleitet).
        """
        if column != 0 or not self._checkable or self._updating_checks:
            return
        if item is None or not isValid(item):
            return
        node_type = item.data(0, ROLE_NODE_TYPE)
        if node_type not in (TYPE_SET, TYPE_SERVICE, TYPE_PLUGIN, TYPE_CLONE):
            return
        self._updating_checks = True
        try:
            state = item.checkState(0)
            if node_type == TYPE_SERVICE:
                key = (TYPE_SERVICE,
                       str(item.data(0, ROLE_SET_ID) or ""),
                       str(item.data(0, ROLE_INSTANCE_ID) or ""))
                # Kein echter Checkbox-Wechsel (z. B. Text-Refresh)? -> return.
                expected = (Qt.Checked if key in self._checked_items
                            else Qt.Unchecked)
                if state == expected:
                    return
                if state == Qt.Checked:
                    self._checked_items.add(key)
                    # Bugfix 08.08.2026: Eltern-Kette aufklappen, damit der
                    # angehakte Service im Set sofort sichtbar ist.
                    self._expand_ancestors(item)
                else:
                    self._checked_items.discard(key)
                parent = item.parent()
                if parent is not None and isValid(parent):
                    self._apply_set_state(parent)
            elif node_type == TYPE_PLUGIN:
                key = (TYPE_PLUGIN, "",
                       str(item.data(0, ROLE_PLUGIN_ID) or ""))
                expected = (Qt.Checked if key in self._checked_items
                            else Qt.Unchecked)
                if state == expected:
                    return
                if state == Qt.Checked:
                    self._checked_items.add(key)
                    # Bugfix 08.08.2026: Eltern-Kette aufklappen (Ordner/
                    # Gruppe), damit die angehakte Plugin-Zeile sichtbar ist.
                    self._expand_ancestors(item)
                else:
                    self._checked_items.discard(key)
            elif node_type == TYPE_CLONE:
                # 20.04 (Q7): Clone-Haken -> feature_id ist die plugin_id
                # des Plugin-Parents (WHERE feature_id IN (plugin_ids)).
                key = (TYPE_CLONE,
                       str(item.data(0, ROLE_PLUGIN_ID) or ""),
                       str(item.data(0, ROLE_INSTANCE_HASH) or ""))
                expected = (Qt.Checked if key in self._checked_items
                            else Qt.Unchecked)
                if state == expected:
                    return
                if state == Qt.Checked:
                    self._checked_items.add(key)
                    self._expand_ancestors(item)
                else:
                    self._checked_items.discard(key)
            elif node_type == TYPE_SET:
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                # Nur bei ECHTEM Wechsel verarbeiten (Tri-State-Ableitung).
                if state == self._derive_set_state(item):
                    return
                for i in range(item.childCount()):
                    child = item.child(i)
                    if child is None or not isValid(child):
                        continue
                    if child.data(0, ROLE_NODE_TYPE) != TYPE_SERVICE:
                        continue
                    key = (TYPE_SERVICE, set_id,
                           str(child.data(0, ROLE_INSTANCE_ID) or ""))
                    if state == Qt.Checked:
                        self._checked_items.add(key)
                        child.setData(0, Qt.CheckStateRole, Qt.Checked)
                    else:
                        self._checked_items.discard(key)
                        child.setData(0, Qt.CheckStateRole, Qt.Unchecked)
                self._apply_set_state(item)
                # Bugfix 08.08.2026: Auch beim Set-Anhaken die Eltern-Kette
                # des Sets aufklappen (Set in Kategorie-Ordner sichtbar).
                self._expand_ancestors(item)
            self.checked_changed.emit()
        finally:
            self._updating_checks = False

    def _derive_set_state(self, set_item) -> int:
        """Erwarteter Tri-State eines Set-Knotens aus seinen Service-Kindern.

        Checked = alle Kinder gecheckt, PartiallyChecked = gemischt,
        Unchecked = keines (Sets ohne Service-Kinder = Unchecked). Dient als
        Vergleichswert in `_on_item_changed`, um spurious itemChanged-Events
        (Text-/Tooltip-Refresh) von echten Checkbox-Klicks zu unterscheiden.
        """
        checked = 0
        total = 0
        for i in range(set_item.childCount()):
            child = set_item.child(i)
            if child is None or not isValid(child):
                continue
            if child.data(0, ROLE_NODE_TYPE) != TYPE_SERVICE:
                continue
            total += 1
            if child.checkState(0) == Qt.Checked:
                checked += 1
        if total > 0 and checked == total:
            return Qt.Checked
        if checked > 0:
            return Qt.PartiallyChecked
        return Qt.Unchecked

    def _apply_set_state(self, set_item) -> None:
        """Setzt den Tri-State eines Set-Knotens aus seinen Service-Kindern.

        Checked = alle Kinder gecheckt, PartiallyChecked = gemischt,
        Unchecked = keines. Sets ohne Service-Kinder sind Unchecked.
        """
        if set_item is None or not isValid(set_item):
            return
        if not self._checkable:
            return
        checked = 0
        total = 0
        for i in range(set_item.childCount()):
            child = set_item.child(i)
            if child is None or not isValid(child):
                continue
            if child.data(0, ROLE_NODE_TYPE) != TYPE_SERVICE:
                continue
            total += 1
            if child.checkState(0) == Qt.Checked:
                checked += 1
        if total > 0 and checked == total:
            state = Qt.Checked
        elif checked > 0:
            state = Qt.PartiallyChecked
        else:
            state = Qt.Unchecked
        set_item.setData(0, Qt.CheckStateRole, state)

    def _sync_checked_from_tree(self) -> None:
        """Gleicht `_checked_items` mit dem IST-Baum ab (stale Keys raus).

        Wird am Ende von `_populate()` gerufen: Nach einem Neuaufbau haelt
        das Set nur noch Keys tatsaechlich vorhandener, angehakter Knoten
        (geloeschte Sets/Services/Plugins verschwinden automatisch).
        """
        if not self._checkable:
            return
        synced: set = set()
        for item in TreeItemIterator(self):
            if item is None or not isValid(item):
                continue
            if item.checkState(0) != Qt.Checked:
                continue
            node_type = item.data(0, ROLE_NODE_TYPE)
            if node_type == TYPE_SERVICE:
                synced.add((TYPE_SERVICE,
                            str(item.data(0, ROLE_SET_ID) or ""),
                            str(item.data(0, ROLE_INSTANCE_ID) or "")))
            elif node_type == TYPE_PLUGIN:
                synced.add((TYPE_PLUGIN, "",
                            str(item.data(0, ROLE_PLUGIN_ID) or "")))
            elif node_type == TYPE_CLONE:
                # 20.04 (Q7): Clone-Keys (plugin_id, instance_hash).
                synced.add((TYPE_CLONE,
                            str(item.data(0, ROLE_PLUGIN_ID) or ""),
                            str(item.data(0, ROLE_INSTANCE_HASH) or "")))
        self._checked_items = synced

    def checked_services(self) -> List[Dict[str, str]]:
        """Alle angehakten Service-/Plugin-Knoten (deterministisch sortiert).

        Returns:
            Pro Eintrag: {"node_type", "set_id", "instance_id", "plugin_id"}.
            Bei Service-Knoten ist instance_id die Set-Instanz; bei
            Standalone-/Plugin-Zeilen ist plugin_id gesetzt (set_id/instance_id
            leer).
        """
        result: List[Dict[str, str]] = []
        for node_type, set_id, key_id in sorted(self._checked_items):
            if node_type == TYPE_SERVICE:
                cfg = self.model.find_service(set_id, key_id) or {}
                result.append({
                    "node_type": TYPE_SERVICE,
                    "set_id": set_id,
                    "instance_id": key_id,
                    "plugin_id": str(cfg.get("plugin_id") or key_id),
                })
            elif node_type == TYPE_PLUGIN:
                result.append({
                    "node_type": TYPE_PLUGIN,
                    "set_id": "",
                    "instance_id": "",
                    "plugin_id": key_id,
                })
            elif node_type == TYPE_CLONE:
                # 20.04 (Q7): Clone-Haken -> feature_id ist die plugin_id
                # (im set_id-Slot gespeichert); instance_hash im
                # instance_id-Slot fuer die Varianten-Aufloesung.
                result.append({
                    "node_type": TYPE_CLONE,
                    "set_id": "",
                    "instance_id": key_id,
                    "plugin_id": set_id,
                })
        return result

    def checked_feature_ids(self) -> List[str]:
        """Deduplizierte plugin_ids aller Haken (SQL-Vertrag `IN (...)`).

        Mehrere Services mit derselben plugin_id (z. B. grid_1 + grid_2)
        ergeben EINEN feature_id-Eintrag ('srv_grid_lines').
        """
        ids: List[str] = []
        for entry in self.checked_services():
            pid = entry["plugin_id"]
            if pid and pid not in ids:
                ids.append(pid)
        return ids

    def checked_display_names(self) -> List[str]:
        """Lesbare Namen fuer die Button-Anzeige (Top-Bar).

        Set-Services: '<Set-Anzeigename>/<instance_id>'
        (z. B. 'Mein Scalper/prox_1'); Standalone-/Plugin-Zeilen: plugin_id
        (z. B. 'srv_proximity').
        """
        names: List[str] = []
        for entry in self.checked_services():
            if entry["node_type"] == TYPE_SERVICE:
                s = self.model.find_set(entry["set_id"]) or {}
                set_name = s.get("display_name") or entry["set_id"] or "?"
                names.append(f"{set_name}/{entry['instance_id']}")
            elif entry["node_type"] == TYPE_CLONE:
                # 20.04 (Q7): Clone-Anzeige '<plugin_id> (#<hash>)'.
                pid = entry["plugin_id"]
                h = entry.get("instance_id") or ""
                names.append(f"{pid} (#{h})" if h else pid)
            else:
                names.append(entry["plugin_id"])
        return names

    def clear_checks(self) -> None:
        """Entfernt ALLE Checkbox-Haken (Dialog-'Filter entfernen').

        Set-Knoten werden mit ihren Service-Kindern zurueckgesetzt; das
        Signal `checked_changed` wird anschliessend emittiert.
        """
        if not self._checkable:
            return
        self._updating_checks = True
        try:
            self._checked_items.clear()
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                if item.data(0, ROLE_NODE_TYPE) in (TYPE_SET, TYPE_SERVICE,
                                                    TYPE_PLUGIN, TYPE_CLONE):
                    item.setData(0, Qt.CheckStateRole, Qt.Unchecked)
        finally:
            self._updating_checks = False
        self.checked_changed.emit()

    def set_checked_feature_ids(self, feature_ids) -> None:
        """Setzt die Haken anhand von plugin_ids (Reverse-Mapping).

        Wird beim Oeffnen des Dialogs aufgerufen, damit die aktuelle
        ViewModel-Auswahl (Profil/Filter) im Baum widergespiegelt wird.
        Matcht Services ueber ihre plugin_id UND Standalone-/Plugin-Zeilen;
        nicht gematchte Haken werden entfernt.
        """
        if not self._checkable:
            return
        wanted = {str(f).strip().lower() for f in (feature_ids or []) if str(f).strip()}
        self._updating_checks = True
        # Bugfix 08.08.2026 (Bug 2): Angehakte Items merken, um danach ihre
        # Eltern-Kette aufzuklappen (der Baum startet eingeklappt – ohne
        # Expansion bleiben die aktivierten Services/Plugins unsichtbar).
        checked_items: List[QTreeWidgetItem] = []
        try:
            self._checked_items.clear()
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                node_type = item.data(0, ROLE_NODE_TYPE)
                if node_type == TYPE_SERVICE:
                    set_id = str(item.data(0, ROLE_SET_ID) or "")
                    instance_id = str(item.data(0, ROLE_INSTANCE_ID) or "")
                    cfg = self.model.find_service(set_id, instance_id) or {}
                    pid = str(cfg.get("plugin_id") or instance_id)
                    checked = pid.lower() in wanted
                    if checked:
                        self._checked_items.add((TYPE_SERVICE, set_id,
                                                 instance_id))
                        checked_items.append(item)
                    item.setData(0, Qt.CheckStateRole,
                                 Qt.Checked if checked else Qt.Unchecked)
                elif node_type == TYPE_PLUGIN:
                    pid = str(item.data(0, ROLE_PLUGIN_ID) or "")
                    checked = pid.lower() in wanted
                    if checked:
                        self._checked_items.add((TYPE_PLUGIN, "", pid))
                        checked_items.append(item)
                    item.setData(0, Qt.CheckStateRole,
                                 Qt.Checked if checked else Qt.Unchecked)
                elif node_type == TYPE_CLONE:
                    # 20.04 (Q7): Clone-Haken folgen der plugin_id (feature-
                    # id des Filters); instance_hash unterscheidet Varianten.
                    pid = str(item.data(0, ROLE_PLUGIN_ID) or "")
                    instance_hash = str(item.data(0, ROLE_INSTANCE_HASH) or "")
                    checked = pid.lower() in wanted
                    if checked:
                        self._checked_items.add(
                            (TYPE_CLONE, pid, instance_hash))
                        checked_items.append(item)
                    item.setData(0, Qt.CheckStateRole,
                                 Qt.Checked if checked else Qt.Unchecked)
            # Tri-States der Sets aus den Kindern ableiten
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                if item.data(0, ROLE_NODE_TYPE) == TYPE_SET:
                    self._apply_set_state(item)
            # Bugfix 08.08.2026 (Bug 2): Eltern-Kette aller angehakten Items
            # aufklappen, damit die aktivierten Services sichtbar sind.
            for item in checked_items:
                self._expand_ancestors(item)
        finally:
            self._updating_checks = False
        self.checked_changed.emit()

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
          * Plugin-Zeile (Services) -> '▶️ Diesen Service ausführen'
                                     (run_plugin_requested, einzeln) +
                                     'Service-Info anzeigen' (17.01.02)
          * Kategorie-Ordner      -> '▶️ Alle Services ausführen'
                                     (run_category_requested, rekursiv) +
                                     'Ordner-Info anzeigen' (17.01.02) +
                                     'Neuer Ordner' / 'Umbenennen' /
                                     'Ordner löschen' (18.01.03; Loeschen
                                     nur fuer leere Ordner aktiv)
          * Sonstige Gruppen      -> Order/Entfernen ausgegraut (17.01.02).

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
            # 17.01.02 (Bugfix-Runde): Kategorie-Ordner erhalten jetzt ein
            # Kontextmenue mit '▶️ Alle Services ausführen' (rekursiv, alle
            # Services unter dem Ordner) + 'Ordner-Info anzeigen' (analog zu
            # den Set-Aktionen in der 📁-Gruppe). 18.01.03: Run/Info tragen
            # zusaetzlich die Eltern-GRUPPE ('sets'/'plugins', L3) und das
            # Menue bietet 'Neuer Ordner' + 'Umbenennen' + 'Ordner löschen'
            # (Ordner-CRUD, 18.01.03; Loeschen nur fuer leere Ordner aktiv).
            if node_type == TYPE_CATEGORY:
                cat_path = self._category_path_of(item)
                cat_group = self._group_of(item)
                if not cat_path:
                    return
                menu = QMenu(self)
                act_run = menu.addAction("▶️ Alle Services ausführen")
                act_run.triggered.connect(
                    lambda _=False, g=cat_group, cp=cat_path:
                    self.run_category_requested.emit(g, cp))
                menu.addSeparator()
                act_info = menu.addAction("Ordner-Info anzeigen")
                act_info.triggered.connect(
                    lambda _=False, g=cat_group, cp=cat_path:
                    self.category_info_requested.emit(g, cp))
                menu.addSeparator()
                act_new = menu.addAction("Neuer Ordner")
                act_new.triggered.connect(
                    lambda _=False, g=cat_group, cp=cat_path:
                    self._on_new_folder(g, cp))
                act_ren = menu.addAction("Umbenennen")
                act_ren.triggered.connect(
                    lambda _=False, g=cat_group, cp=cat_path:
                    self._on_rename_folder(g, cp))
                menu.addSeparator()
                # 18.01.03 (E3-revidiert, 08.08.2026): 'Ordner löschen' –
                # die EINZIGE Moeglichkeit, einen leeren Ordner zu entfernen
                # (leere Ordner verschwinden NICHT automatisch beim Refresh).
                # Nur fuer Ordner OHNE Kinder aktiv – bei gefuellten Ordnern
                # muss der Benutzer zuerst die Kinder herausziehen (Guard).
                act_del = menu.addAction("Ordner löschen")
                act_del.setToolTip(
                    "Nur für leere Ordner verfügbar – entfernt den Ordner "
                    "dauerhaft.")
                act_del.setEnabled(item.childCount() == 0)
                act_del.triggered.connect(
                    lambda _=False, g=cat_group, cp=cat_path:
                    self.delete_folder_requested.emit(g, cp))
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            menu = QMenu(self)
            if node_type == TYPE_GROUP:
                group = str(item.data(0, ROLE_SET_ID) or "")
                if group == self.model.GROUP_SETS:
                    act = menu.addAction("Neues Set anlegen")
                    act.triggered.connect(
                        lambda _=False: self.create_set_requested.emit())
                    # 18.01.03: 'Neuer Ordner' in der Sets-Gruppe (Root).
                    act_folder = menu.addAction("Neuer Ordner")
                    act_folder.triggered.connect(
                        lambda _=False, g=group:
                        self._on_new_folder(g, ""))
                    menu.addSeparator()
                    act_trash = menu.addAction("🗑️ Papierkorb öffnen...")
                    act_trash.triggered.connect(
                        lambda _=False: self.open_trash_requested.emit())
                else:
                    # 18.01.03: 'Neuer Ordner' auch in der Services-Gruppe
                    # (Root) – die uebrigen Struktur-Aktionen bleiben
                    # ausgegraut (_add_outside_set_actions).
                    act_folder = menu.addAction("Neuer Ordner")
                    act_folder.triggered.connect(
                        lambda _=False, g=group:
                        self._on_new_folder(g, ""))
                    menu.addSeparator()
                    self._add_outside_set_actions(menu, item)
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            if node_type == TYPE_SET:
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                archived_set = bool(item.data(0, ROLE_ARCHIVED))
                # 05.08.2026: 'Alle Services ausführen' – gezielter Run des
                # Sets (kein globaler Massen-Scan); der Orchestrator zeigt
                # den Bestaetigungsdialog (Set + Symbol/Timeframe).
                # 20.04 (Q6): Archivierte Sets sind von Run/Struktur-Aktionen
                # ausgenommen (Archive Safety) – nur Loeschen bleibt aktiv.
                act_run = menu.addAction("▶️ Alle Services ausführen")
                act_run.setEnabled(not archived_set)
                act_run.triggered.connect(
                    lambda _=False, s=set_id:
                    self.run_set_requested.emit(s))
                menu.addSeparator()
                act_rename = menu.addAction("Set umbenennen")
                act_rename.setEnabled(not archived_set)
                act_rename.triggered.connect(
                    lambda _=False, s=set_id:
                    self.rename_set_requested.emit(s))
                act_add = menu.addAction("Service hinzufügen")
                act_add.setEnabled(not archived_set)
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
                # 20.04 (Q1/Q9): instance_hash der Instanz (aus der Set-
                # Definition, ROLE_INSTANCE_HASH) – Grundlage von Data-Only-
                # Purge, Voll-Loeschung und Doc-Log.
                instance_hash = str(item.data(0, ROLE_INSTANCE_HASH) or "")
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
                # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung (Service-in-Set).
                # 'Als Variante duplizieren' erzeugt eine neue Instanz mit
                # kopierten Parametern (Q8); 'Doc Log bearbeiten' editiert
                # das Negativ-Wissen; 'Data Only Löschen' purgt NUR die
                # Feature-Daten (Q5); 'Vollständig Löschen' entfernt die
                # Instanz + Daten (2-stufige Sicherheitsabfrage).
                menu.addSeparator()
                act_variant = menu.addAction("Als Variante duplizieren")
                act_variant.triggered.connect(
                    lambda _=False, s=set_id, i=service_id, p=plugin_id,
                           h=instance_hash:
                    self.duplicate_variant_requested.emit(s, i, p, h))
                act_doclog = menu.addAction("Doc Log bearbeiten")
                act_doclog.triggered.connect(
                    lambda _=False, s=set_id, i=service_id, p=plugin_id,
                           h=instance_hash:
                    self.doc_log_requested.emit(s, i, p, h))
                menu.addSeparator()
                act_purge = menu.addAction("Data Only Löschen")
                act_purge.triggered.connect(
                    lambda _=False, s=set_id, i=service_id, p=plugin_id,
                           h=instance_hash:
                    self.data_only_purge_requested.emit(s, i, p, h))
                act_del = menu.addAction("Vollständig Löschen")
                act_del.triggered.connect(
                    lambda _=False, s=set_id, i=service_id, p=plugin_id,
                           h=instance_hash:
                    self.delete_complete_requested.emit(s, i, p, h))
                menu.addSeparator()
                act_purge = menu.addAction("Papierkorb löschen…")
                act_purge.triggered.connect(
                    lambda _=False: self.purge_trash_requested.emit())
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            # 20.04 (Q7): Clone-Zeile (Preset/Variante eines Plugin-Parents).
            # Der Run adressiert den Service ueber die plugin_id; archivierte
            # Clones sind von allen Aktionen ausgenommen (Archive Safety, Q6).
            if node_type == TYPE_CLONE:
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
                instance_hash = str(item.data(0, ROLE_INSTANCE_HASH) or "")
                archived = bool(item.data(0, ROLE_ARCHIVED))
                menu = QMenu(self)
                act_run = menu.addAction("▶️ Diesen Service ausführen")
                act_run.setEnabled(not archived)
                act_run.triggered.connect(
                    lambda _=False, p=plugin_id:
                    self.run_plugin_requested.emit(p))
                menu.addSeparator()
                act_info = menu.addAction("Service-Info anzeigen")
                act_info.setEnabled(not archived)
                act_info.triggered.connect(
                    lambda _=False, p=plugin_id:
                    self.info_requested.emit("", "", p))
                # 20.04 (Q5/Q6/Q8): Preset-/Varianten-Verwaltung. Archivierte
                # Clones sind von den Bearbeitungs-/Lauf-Aktionen ausgenommen
                # (Archive Safety, Q6) – nur 'Vollständig Löschen' bleibt als
                # einzige Loesch-Option aktiv (Archiv-Einheit: einzelner Clone).
                menu.addSeparator()
                act_variant = menu.addAction("Als Variante duplizieren")
                act_variant.setEnabled(not archived)
                act_variant.triggered.connect(
                    lambda _=False, p=plugin_id, h=instance_hash:
                    self.duplicate_variant_requested.emit("", "", p, h))
                act_doclog = menu.addAction("Doc Log bearbeiten")
                act_doclog.setEnabled(not archived)
                act_doclog.triggered.connect(
                    lambda _=False, p=plugin_id, h=instance_hash:
                    self.doc_log_requested.emit("", "", p, h))
                menu.addSeparator()
                act_purge = menu.addAction("Data Only Löschen")
                act_purge.setEnabled(not archived)
                act_purge.triggered.connect(
                    lambda _=False, p=plugin_id, h=instance_hash:
                    self.data_only_purge_requested.emit("", "", p, h))
                act_del = menu.addAction("Vollständig Löschen")
                act_del.triggered.connect(
                    lambda _=False, p=plugin_id, h=instance_hash:
                    self.delete_complete_requested.emit("", "", p, h))
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            # Plugin-Zeile (Services-Gruppe / Kategorie-Ordner):
            # 17.01.02 (Bugfix-Runde) – '▶️ Diesen Service ausführen' wie bei
            # den Set-Service-Zeilen (einzelner Run, Sicherheitsabfrage durch
            # den Orchestrator); 'Service-Info anzeigen' bleibt aktiv.
            if node_type == TYPE_PLUGIN:
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
                menu = QMenu(self)
                act_run = menu.addAction("▶️ Diesen Service ausführen")
                act_run.triggered.connect(
                    lambda _=False, p=plugin_id:
                    self.run_plugin_requested.emit(p))
                menu.addSeparator()
                act_info = menu.addAction("Service-Info anzeigen")
                act_info.triggered.connect(
                    lambda _=False, p=plugin_id:
                    self.info_requested.emit("", "", p))
                # 20.04 (Q8): 'Als Variante duplizieren' – erzeugt eine
                # Preset-Variante (indicator_presets) aus den aktuellen
                # Plugin-Parametern; der Plugin-Knoten wird zum Parent mit
                # Clone-Kindern (erste Variante eines flachen Blatts).
                menu.addSeparator()
                act_variant = menu.addAction("Als Variante duplizieren")
                act_variant.triggered.connect(
                    lambda _=False, p=plugin_id:
                    self.duplicate_variant_requested.emit("", "", p, ""))
                menu.exec(self.viewport().mapToGlobal(pos))
                return
            # Sonstige Nicht-Set-Knoten (Gruppen der Services-Seite)
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

        Erweiterung 15.03-E (Multi-Select): Klicks in die Checkbox-Zone
        (CHECKBOX_ZONE_WIDTH, linke Kante der Item-Zeile in Spalte 0) werden
        dem Qt-Default ueberlassen, damit die Checkbox togglet
        (itemChanged feuert); nur Klicks rechts der Zone togglen das
        Auf-/Zuklappen.

        Bugfix 06.08.2026 (Bugfix-Runde 3, Punkte 1-7): JEDER Mausklick auf
        eine gueltige Zeile emittiert `selection_details` (vor der
        Verzweigung, damit auch Checkbox-Zonen- und Expand-Klicks den
        Klick-Scope liefern) – das Read-Only-Panel des Dialogs folgt damit
        dem Klick, NICHT den Checkboxen.
        """
        try:
            pos = (event.position().toPoint() if hasattr(event, "position")
                   else event.pos())
            item = self.itemAt(pos)
            if item is None or not isValid(item):
                super().mousePressEvent(event)
                return
            # 18.01.03 (Drag & Drop): Quelle fuer einen beginnenden Drag
            # merken (nur linke Maustaste; startDrag wertet sie aus).
            self._drag_source = (
                item if event.button() == Qt.LeftButton else None)
            # Klick-Scope fuer das Read-Only-Panel (Bugfix 06.08.2026).
            self._emit_selection_details(item)
            # Checkbox-Klick hat Vorrang vor dem Expand-Toggle
            if self._checkable and (item.flags() & Qt.ItemIsUserCheckable):
                rect = self.visualItemRect(item)
                if pos.x() < rect.left() + CHECKBOX_ZONE_WIDTH:
                    super().mousePressEvent(event)
                    return
            if item.childCount() > 0:
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

    def _emit_selection_details(self, item) -> None:
        """Emittiert `selection_details` fuer die geklickte Zeile.

        Liefert die Zeilen-Daten (node_type, set_id, service_id, plugin_id)
        je Knotentyp – Service-Zeilen tragen alle vier Rollen, Set-Zeilen nur
        node_type+set_id, Plugin-Zeilen nur node_type+plugin_id (set_id ist
        hier bewusst leer, die ROLE_SET_ID haelt nur die Gruppenkennung),
        Gruppen-/sonstige Zeilen nur node_type. Der Dialog entscheidet aus
        diesem Scope, welche Parameter angezeigt werden.
        """
        if item is None or not isValid(item):
            return
        try:
            node_type = str(item.data(0, ROLE_NODE_TYPE) or "")
            set_id = ""
            service_id = ""
            plugin_id = ""
            if node_type == TYPE_SERVICE:
                set_id = str(item.data(0, ROLE_SET_ID) or "")
                service_id = str(item.data(0, ROLE_INSTANCE_ID) or "")
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
            elif node_type == TYPE_SET:
                set_id = str(item.data(0, ROLE_SET_ID) or "")
            elif node_type == TYPE_PLUGIN:
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
            elif node_type == TYPE_CLONE:
                # 20.04 (Q7): Clone-Zeilen liefern plugin_id (feature_id)
                # im plugin_id-Slot; der instance_hash (Varianten-Key) wird
                # im service_id-Slot mitgeliefert (Info/Param-Panel).
                plugin_id = str(item.data(0, ROLE_PLUGIN_ID) or "")
                service_id = str(item.data(0, ROLE_INSTANCE_HASH) or "")
            elif node_type == TYPE_CATEGORY:
                # 18.01.01 (E-4): Kategorie-Ordner liefern den VOLLEN
                # Kategorie-Pfad (z.B. 'Swing Points/Geometrie') im
                # plugin_id-Slot – Grundlage fuer die ID-Aufloesung im
                # AnalyticsWindow (Baum-Selektion -> set_feature_ids).
                # 18.01.03 (L3): Zusaetzlich wird die Eltern-GRUPPE
                # ('sets'/'plugins') im set_id-Slot geliefert, damit die
                # Aufloesung Sets-Ordner von Plugins-Ordnern unterscheiden
                # kann (Sets-Ordner -> category_set_ids -> Services).
                set_id = self._group_of(item)
                plugin_id = self._category_path_of(item)
            self.selection_details.emit(node_type, set_id, service_id,
                                        plugin_id)
        except (RuntimeError, AttributeError):
            pass

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

    # -------------------------------------------------------------------------
    # 20.04 (Q8-Bugfix): Programmgesteuerte Selektion nach dem Duplizieren –
    # 'Als Variante duplizieren' muss ein SICHTBARES Ergebnis liefern. Die
    # neuen Instanzen/Clones werden expandiert (Eltern-Kette), selektiert und
    # in den sichtbaren Bereich gescrollt (unter blockSignals, kein Signal-
    # Sturm auf _on_master_selection).
    # -------------------------------------------------------------------------

    def select_instance(self, set_id: str, service_id: str) -> bool:
        """Selektiert eine Service-Instanz (TYPE_SERVICE) im Baum."""
        return self._select_by(lambda it: (
            it.data(0, ROLE_NODE_TYPE) == TYPE_SERVICE
            and str(it.data(0, ROLE_SET_ID) or "") == str(set_id)
            and str(it.data(0, ROLE_INSTANCE_ID) or "") == str(service_id)))

    def select_clone(self, plugin_id: str, instance_hash: str) -> bool:
        """Selektiert einen Clone-Knoten (TYPE_CLONE, Preset/Variante)."""
        return self._select_by(lambda it: (
            it.data(0, ROLE_NODE_TYPE) == TYPE_CLONE
            and str(it.data(0, ROLE_PLUGIN_ID) or "") == str(plugin_id)
            and str(it.data(0, ROLE_INSTANCE_HASH) or "") == str(instance_hash)))

    def _select_by(self, predicate) -> bool:
        """Iterator + Prädikat: expandieren, selektieren, scrollen."""
        try:
            for item in TreeItemIterator(self):
                if item is None or not isValid(item):
                    continue
                try:
                    if not predicate(item):
                        continue
                    self._expand_ancestors(item)
                    self.blockSignals(True)
                    try:
                        self.setCurrentItem(item)
                        self.scrollToItem(item)
                    finally:
                        self.blockSignals(False)
                    return True
                except (RuntimeError, AttributeError):
                    continue
        except (RuntimeError, AttributeError):
            pass
        return False


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
