"""
master_tree_checks.py - Checkbox-Modus (Tri-State, checked_*-Abfragen, Pending-Hooks)

23.06 God-File-Split (15.08.2026): Aus serviceui/master_tree.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der MasterTree-
Klasse als Mixin (Klasse MasterTreeChecksMixin).
"""

from typing import (
    Dict,
    List,
)

from PySide6.QtCore import (
    Qt,
)

from PySide6.QtWidgets import (
    QTreeWidgetItem,
)

from serviceui.master_tree_constants import (
    ROLE_INSTANCE_HASH,
    ROLE_INSTANCE_ID,
    ROLE_NODE_TYPE,
    ROLE_PLUGIN_ID,
    ROLE_SET_ID,
    TYPE_CLONE,
    TYPE_PLUGIN,
    TYPE_SERVICE,
    TYPE_SET,
    TreeItemIterator,
    isValid,
)

class MasterTreeChecksMixin:

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
                       str(item.data(0, ROLE_INSTANCE_ID) or ""),
                       str(item.data(0, ROLE_INSTANCE_HASH) or ""))
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
                    # Runde 9 (Bug 3): KEIN _uncheck_plugin_rows mehr - das
                    # Abhaengen ALLER Zeilen einer plugin_id hat beim Uncheck
                    # einer Variante auch die anderen Clones abgehaengt
                    # (falsch). checked_feature_ids() dedupliziert ohnehin
                    # auf plugin_id: Der Filter bleibt aktiv, solange
                    # mindestens eine Zeile gecheckt ist.
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
                    # Runde 9 (Bug 3): _uncheck_plugin_rows entfernt (siehe
                    # TYPE_SERVICE) - nur diesen einen Key abhaengen.
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
                    # Runde 9 (Bug 3): _uncheck_plugin_rows entfernt (siehe
                    # TYPE_SERVICE) - nur diesen einen Key abhaengen.
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
                           str(child.data(0, ROLE_INSTANCE_ID) or ""),
                           str(child.data(0, ROLE_INSTANCE_HASH) or ""))
                    if state == Qt.Checked:
                        self._checked_items.add(key)
                        child.setData(0, Qt.CheckStateRole, Qt.Checked)
                    else:
                        self._checked_items.discard(key)
                        child.setData(0, Qt.CheckStateRole, Qt.Unchecked)
                        # Runde 9 (Bug 3): _uncheck_plugin_rows entfernt
                        # (siehe TYPE_SERVICE) - nur diesen einen Key
                        # abhaengen, nicht alle Zeilen der plugin_id.
                self._apply_set_state(item)
                # Bugfix 08.08.2026: Auch beim Set-Anhaken die Eltern-Kette
                # des Sets aufklappen (Set in Kategorie-Ordner sichtbar).
                self._expand_ancestors(item)
            self.checked_changed.emit()
        finally:
            self._updating_checks = False

    # Runde 9 (Bug 3): _uncheck_plugin_rows ist ENTFERNT/AUSKOMMENTIERT -
    # das Abhaengen ALLER Zeilen einer plugin_id beim Uncheck einer
    # Variante hat auch die anderen Clones abgehaengt (falsch). Siehe
    # _on_item_changed (nur den einen Key abhaengen).
    #     def _uncheck_plugin_rows(self, plugin_id: str) -> None:
    #         """Haengt ALLE Zeilen einer plugin_id ab (Bugfix 10.08.2026).

    #         `checked_feature_ids()` dedupliziert die Haken auf
    #         plugin_id-Ebene (eine plugin_id == eine feature_id fuer
    #         `WHERE feature_id IN (...)`). Beim Restore
    #         (`set_checked_feature_ids`) koennen deshalb mehrere Zeilen-
    #         Typen derselben plugin_id angehakt sein: die Service-Zeile im
    #         Set, das Standalone-Plugin-Blatt (TYPE_PLUGIN) und ggf.
    #         Clones. Ein Uncheck NUR einer Zeile wuerde die plugin_id
    #         ueber die anderen Zeilen im Filter belassen (Dropdown/
    #         Historie reagieren nicht) - deshalb werden hier alle Zeilen
    #         mit derselben plugin_id abgehaengt und ihre Keys aus
    #         `_checked_items` entfernt. Wird aus den Uncheck-Zweigen von
    #         `_on_item_changed` gerufen (laeuft unter `_updating_checks
    #         == True`, d. h. die setData-Aufrufe feuern keine spurious
    #         Events).
    #         """
    #         pid = str(plugin_id or "").lower()
    #         if not pid:
    #             return
    #         for item in TreeItemIterator(self):
    #             if item is None or not isValid(item):
    #                 continue
    #             node_type = item.data(0, ROLE_NODE_TYPE)
    #             if node_type not in (TYPE_SERVICE, TYPE_PLUGIN, TYPE_CLONE):
    #                 continue
    #             if str(item.data(0, ROLE_PLUGIN_ID) or "").lower() != pid:
    #                 continue
    #             if item.checkState(0) != Qt.Checked:
    #                 continue
    #             if node_type == TYPE_SERVICE:
    #                 key = (TYPE_SERVICE,
    #                        str(item.data(0, ROLE_SET_ID) or ""),
    #                        str(item.data(0, ROLE_INSTANCE_ID) or ""))
    #             elif node_type == TYPE_PLUGIN:
    #                 key = (TYPE_PLUGIN, "",
    #                        str(item.data(0, ROLE_PLUGIN_ID) or ""))
    #             else:
    #                 key = (TYPE_CLONE,
    #                        str(item.data(0, ROLE_PLUGIN_ID) or ""),
    #                        str(item.data(0, ROLE_INSTANCE_HASH) or ""))
    #             self._checked_items.discard(key)
    #             item.setData(0, Qt.CheckStateRole, Qt.Unchecked)
    #             parent = item.parent()
    #             if (parent is not None and isValid(parent)
    #                     and parent.data(0, ROLE_NODE_TYPE) == TYPE_SET):
    #                 self._apply_set_state(parent)
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
                            str(item.data(0, ROLE_INSTANCE_ID) or ""),
                            str(item.data(0, ROLE_INSTANCE_HASH) or "")))
            elif node_type == TYPE_PLUGIN and item.childCount() == 0:
                # 10.08.2026 (Punkt 6): Plugin-Parents mit Varianten sind
                # non-checkable - kein Haken-Sync (Konsistenz zum Reverse-
                # Mapping in set_checked_feature_ids).
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
        for entry in sorted(self._checked_items):
            node_type = str(entry[0])
            if node_type == TYPE_SERVICE:
                set_id = str(entry[1] or "")
                instance_id = str(entry[2] or "")
                # Runde 13 (Bugfix Dropdown-NoData): 4. Element = instance_hash
                # der Set-Instanz-Variante (variantengenaue Einschraenkung).
                instance_hash = str(entry[3] or "") if len(entry) > 3 else ""
                cfg = self.model.find_service(set_id, instance_id) or {}
                result.append({
                    "node_type": TYPE_SERVICE,
                    "set_id": set_id,
                    "instance_id": instance_id,
                    "plugin_id": str(cfg.get("plugin_id") or instance_id),
                    "instance_hash": instance_hash,
                })
            elif node_type == TYPE_PLUGIN:
                result.append({
                    "node_type": TYPE_PLUGIN,
                    "set_id": "",
                    "instance_id": "",
                    "plugin_id": str(entry[2] or ""),
                    "instance_hash": "",
                })
            elif node_type == TYPE_CLONE:
                # 20.04 (Q7): Clone-Haken -> feature_id ist die plugin_id
                # (im set_id-Slot gespeichert); instance_hash im
                # instance_id-Slot fuer die Varianten-Aufloesung.
                result.append({
                    "node_type": TYPE_CLONE,
                    "set_id": "",
                    "instance_id": str(entry[2] or ""),
                    "plugin_id": str(entry[1] or ""),
                    "instance_hash": str(entry[2] or ""),
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

    def checked_instance_hashes(self) -> List[str]:
        """Deduplizierte instance_hashes aller gecheckten Clone-Varianten.

        Runde 10 (Bug 1): Der Filter ist damit varianten-granular - ein
        Check/Uncheck EINER Variante (Clone) aendert den Datenfilter
        sichtbar (feature_ids bleibt plugin_id-granular fuer die
        IN-Klausel, instance_hashes schraenkt auf die gewaehlten
        Varianten ein). Leere Liste = keine Varianten-Einschraenkung.
        """
        hashes: List[str] = []
        for entry in self.checked_services():
            # Runde 13 (Bugfix Dropdown-NoData): Hashes ALLER gecheckten
            # Varianten sammeln - Clone-Knoten UND Set-Instanz-Varianten
            # (vorher nur TYPE_CLONE; Set-Instanzen verloren ihren Hash in
            # der Check-Sync-Kette und die Varianten-Einschraenkung blieb
            # leer -> No-Data-Dropdown zeigte die falsche/erste Variante).
            h = entry.get("instance_hash") or ""
            if h and h not in hashes:
                hashes.append(h)
        return hashes

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

    def set_checked_feature_ids(self, feature_ids,
                               instance_hashes=None) -> None:
        """Setzt die Haken anhand von plugin_ids (Reverse-Mapping).

        Wird beim Oeffnen des Dialogs aufgerufen, damit die aktuelle
        ViewModel-Auswahl (Profil/Filter) im Baum widergespiegelt wird.
        Matcht Services ueber ihre plugin_id UND Standalone-/Plugin-Zeilen;
        nicht gematchte Haken werden entfernt.
        """
        if not self._checkable:
            return
        wanted = {str(f).strip().lower() for f in (feature_ids or []) if str(f).strip()}
        # Runde 9 (Bug 1): Ist der Baum noch NICHT aufgebaut (das initiale
        # data_changed des Modells lief VOR der Dialog-Erstellung, der Baum
        # bleibt sonst leer), werden die gewuenschten IDs gemerkt und beim
        # naechsten _populate() automatisch angewendet - sonst gingen die
        # restaurierten Haken verloren ('restore fails wenn offen').
        if self.topLevelItemCount() == 0:
            self._pending_feature_ids = [str(f) for f in (feature_ids or [])]
            self._pending_instance_hashes = [
                str(h) for h in (instance_hashes or []) if str(h).strip()]
            return
        self._updating_checks = True
        # Runde 10 (Bug 1): instance_hashes is None = KEINE
        # Varianten-Einschraenkung (alle Clones der wanted plugin_ids);
        # leere Liste = explizit KEINE Variante angehakt.
        hash_restriction = instance_hashes is not None
        wanted_hashes = {str(h).strip().lower()
                         for h in (instance_hashes or []) if str(h).strip()}
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
                    instance_hash = str(item.data(0, ROLE_INSTANCE_HASH) or "")
                    cfg = self.model.find_service(set_id, instance_id) or {}
                    pid = str(cfg.get("plugin_id") or instance_id)
                    # Runde 13 (Bugfix Dropdown-NoData): Reverse-Mapping mit
                    # Hash-Granularitaet auch fuer Set-Instanz-Varianten
                    # (analog TYPE_CLONE) - sind instance_hashes gesetzt,
                    # wird NUR die passende Instanz angehakt.
                    if hash_restriction:
                        checked = (pid.lower() in wanted
                                   and instance_hash.strip().lower()
                                   in wanted_hashes)
                    else:
                        checked = pid.lower() in wanted
                    if checked:
                        self._checked_items.add((TYPE_SERVICE, set_id,
                                                 instance_id,
                                                 instance_hash))
                        checked_items.append(item)
                    item.setData(0, Qt.CheckStateRole,
                                 Qt.Checked if checked else Qt.Unchecked)
                elif node_type == TYPE_PLUGIN and item.childCount() == 0:
                    # 10.08.2026 (Punkt 6): Plugin-Parents MIT Varianten/
                    # Clones sind Template-Knoten OHNE Checkbox (sie tragen
                    # nur die Clone-Haken) - beim Reverse-Mapping werden sie
                    # uebersprungen; nur flache Blaetter bleiben anhakbar.
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
                    # Runde 10 (Bug 1): Reverse-Mapping mit Hash-Granularitaet
                    # - sind instance_hashes gesetzt, wird NUR die passende
                    # Variante angehakt (sonst alle der plugin_id).
                    pid = str(item.data(0, ROLE_PLUGIN_ID) or "")
                    instance_hash = str(item.data(0, ROLE_INSTANCE_HASH) or "")
                    if hash_restriction:
                        checked = (pid.lower() in wanted
                                   and instance_hash.strip().lower()
                                   in wanted_hashes)
                    else:
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
