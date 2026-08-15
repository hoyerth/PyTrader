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

# 20.04 (Q2/Q4): Deterministischer Parameter-Hash. Runde 13b
# (Bugfix Dropdown-NoData): on-the-fly-Fallback in _build_set_item fuer
# Set-Instanzen, deren Set-Definition beim regularen Hinzufuegen keinen
# instance_hash persistiert hat (Alt-Bestand).
from analytics.engine.service_models import generate_instance_hash
from serviceui.master_tree_build import MasterTreeBuildMixin
from serviceui.master_tree_dragdrop import MasterTreeDragDropMixin
from serviceui.master_tree_ui import MasterTreeUiMixin
from serviceui.master_tree_checks import MasterTreeChecksMixin
from serviceui.master_tree_events import MasterTreeEventsMixin
from serviceui.master_tree_selection import MasterTreeSelectionMixin

from serviceui.master_tree_constants import (
    BADGE_COLUMN_WIDTH,
    BADGE_TRUNCATE_ICON,
    BRANCH_ZONE_WIDTH,
    CHECKBOX_ZONE_WIDTH,
    INFO_BUTTON_COLOR_INDICATOR,
    INFO_BUTTON_COLOR_NEUTRAL,
    INFO_BUTTON_SIZE,
    INFO_BUTTON_TEXT,
    INFO_BUTTON_WIDTH,
    LEVEL_INDENT,
    MAX_BADGE_CELL_CHARS,
    MIME_CATEGORY_MOVE,
    ROLE_ARCHIVED,
    ROLE_INSTANCE_HASH,
    ROLE_INSTANCE_ID,
    ROLE_NODE_TYPE,
    ROLE_PLUGIN_ID,
    ROLE_PRESET_NAME,
    ROLE_SET_ID,
    TYPE_CATEGORY,
    TYPE_CLONE,
    TYPE_GROUP,
    TYPE_PLUGIN,
    TYPE_SERVICE,
    TYPE_SET,
    TreeItemIterator,
    _expandable_label,
    isValid,
)


class MasterTree(
    QTreeWidget,
    MasterTreeBuildMixin, MasterTreeDragDropMixin, MasterTreeUiMixin,
    MasterTreeChecksMixin, MasterTreeEventsMixin, MasterTreeSelectionMixin,
):
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
    #   run_plugin_requested(plugin_id, instance_hash) – '▶️ Diesen Service
    #      ausführen' (Einzel-Plugin-Zeile, ohne Set). 11.08.2026 (Bugfixing):
    #      Clone-Zeilen liefern den instance_hash der Variante mit (NUR diese
    #      Variante laeuft mit ihren Parametern); Plugin-Zeilen senden '' (mit
    #      Presets laufen alle aktiven Varianten, sonst Basis-Parameter).
    #   run_category_requested(group, path) – '▶️ Alle Services ausführen'
    #                                      (Kategorie-Ordner, rekursiv; path
    #                                      z.B. 'Swing Points/Geometrie';
    #                                      group = 'sets' | 'plugins',
    #                                      18.01.03: Sets-Ordner moeglich)
    #   category_info_requested(group, path) – Info-Button auf Kategorie-Ordnern
    run_plugin_requested = Signal(str, str)
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
    # 10.08.2026 (Bugfix): 'Variante umbenennen' (Clone/Preset-Kontextmenue).
    # Der MasterTree fragt den neuen Namen ab (vorbelegt) und emittiert
    # rename_variant_requested(plugin_id, instance_hash, new_name) – der
    # Orchestrator (ServiceWindow / ServiceSelectorDialog) persistiert den
    # Preset-Rename in indicator_presets (indicator_id, preset_name).
    rename_variant_requested = Signal(str, str, str)

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

