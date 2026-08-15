"""
master_tree_events.py - Kontextmenue, Maus-Event, Rendering-Overrides, Selection-Details

23.06 God-File-Split (15.08.2026): Aus serviceui/master_tree.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der MasterTree-
Klasse als Mixin (Klasse MasterTreeEventsMixin).
"""

from PySide6.QtCore import (
    Qt,
)

from PySide6.QtWidgets import (
    QMenu,
)

from serviceui.master_tree_constants import (
    CHECKBOX_ZONE_WIDTH,
    ROLE_ARCHIVED,
    ROLE_INSTANCE_HASH,
    ROLE_INSTANCE_ID,
    ROLE_NODE_TYPE,
    ROLE_PLUGIN_ID,
    ROLE_SET_ID,
    TYPE_CATEGORY,
    TYPE_CLONE,
    TYPE_GROUP,
    TYPE_PLUGIN,
    TYPE_SERVICE,
    TYPE_SET,
    isValid,
)

class MasterTreeEventsMixin:
        # Bugfix 10.08.2026 (Bug 5): KEIN checked_changed hier - dieses
        # programmatische Set (beim Oeffnen des Picker-Dialogs) darf keine
        # Feedback-Schleife in Gang setzen (checked_changed -> selection_ids
        # -> set_feature_ids wuerde den restaurierten Filter ueberschreiben).
        # Nur Nutzer-Aktionen (_on_item_changed) und clear_checks() emittieren.

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
                    lambda _=False, p=plugin_id, h=instance_hash:
                    self.run_plugin_requested.emit(p, h))
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
                # 10.08.2026 (Bugfix): 'Variante umbenennen' – Fragt den
                # neuen Preset-Namen ab (Namensdialog im MasterTree) und
                # emittiert rename_variant_requested (Orchestrator persistiert).
                act_rename = menu.addAction("Variante umbenennen")
                act_rename.setEnabled(not archived)
                act_rename.triggered.connect(
                    lambda _=False, it=item:
                    self._on_rename_clone(it))
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
                    self.run_plugin_requested.emit(p, ""))
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
