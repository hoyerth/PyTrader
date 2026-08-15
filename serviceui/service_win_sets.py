"""
serviceui/service_win_sets.py - Set-Verwaltung (Anlegen, Umbenennen, Loeschen, Verschieben, Papierkorb)

23.04 God-File-Split (15.08.2026): Aus serviceui/service_win.py extrahiert,
KEINE Logik-Aenderung. Enthaelt die Methoden der ServiceWindow
als Mixin (Klasse ServiceSetsMixin).
"""

from PySide6.QtCore import (
    Slot,
)

from PySide6.QtWidgets import (
    QDialog,
    QInputDialog,
    QMessageBox,
)

from serviceui.trash_dialog import (
    ServiceSetTrashDialog,
)

from serviceui.new_set_dialog import (
    NewServiceSetDialog,
)

from config.event_bus import (
    event_bus,
)

class ServiceSetsMixin:

    @Slot()
    def _on_add_set(self) -> None:
        """Erzeugt ein NEUES Service-Set ([➕ Set] / Kontextmenue
        'Neues Set anlegen').

        Bugfix 05.08.2026 (einfache Bedienung): Dialog mit Namens- und
        Indikator-Auswahl (NewServiceSetDialog). Der Name ist Pflicht; wird
        ein Indikator gewaehlt, wird er explizit zugewiesen (indicator_id)
        und die Basis-Services automatisch angelegt (_build_new_set_definition).
        Das neue Set wird direkt im MasterTree selektiert.
        """
        try:
            from analytics.engine.service_selector_model import list_indicators
            indicators = list_indicators()
        except Exception:
            indicators = []
        dlg = NewServiceSetDialog(indicators, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        name = dlg.result_name()
        ind_id = dlg.result_indicator_id()
        if any((s.get("display_name") or "") == name
               for s in self.set_repo.list_sets()):
            QMessageBox.warning(
                self, "Name vergeben",
                f"Ein Service-Set heißt bereits '{name}'.")
            return
        definition = self._build_new_set_definition(name, ind_id)
        try:
            set_id = self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Anlegen des Sets: {e}")
            return
        if not set_id:
            self.log("Set-Anlage fehlgeschlagen.")
            return
        self.log(f"Neues Service-Set angelegt: {set_id}"
                 + (f" (Indikator: {ind_id})" if ind_id else ""))
        event_bus.service_set_changed.emit()
        # Neues Set im MasterTree selektieren (Editor-Sync via selection_changed)
        self._select_set_in_tree(set_id)

    @Slot(str)
    def _on_rename_set(self, set_id: str) -> None:
        """Benennt ein Service-Set um (Kontextmenue 'Set umbenennen').

        Direkt ueber set_repo: Namensdialog (vorbelegt), Kollisionspruefung
        gegen die UEBRIGEN Sets, dann save_set() mit gleicher set_id und
        neuem display_name. Bewusst NICHT ueber den NamedItemAdapter –
        dessen _item_save_as() verweigert leere execution_order (leere Sets
        waeren sonst nicht umbenennbar).
        """
        if not set_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Umbenennen abgebrochen.")
            return
        current_name = str(definition.get("display_name") or "")
        name, ok = QInputDialog.getText(
            self, "Set umbenennen",
            f"Neuer Name für das Service-Set '{current_name}':",
            text=current_name,
        )
        if not ok:
            return
        clean = name.strip()
        if not clean:
            QMessageBox.warning(self, "Fehler", "Der Name darf nicht leer sein.")
            return
        collision = any(
            (s.get("display_name") or "") == clean and s.get("set_id") != set_id
            for s in self.set_repo.list_sets())
        if collision:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Ein anderes Service-Set heißt bereits '{clean}'.")
            return
        definition["display_name"] = clean
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Set umbenannt: '{current_name}' -> '{clean}'")
        event_bus.service_set_changed.emit()
        # Geladenes Set im Editor nachziehen (Baum-Label kommt aus dem Modell).
        if self._current_set_id == set_id:
            try:
                self.load_set_into_editor(self.set_repo.get_set(set_id))
            except Exception as e:
                self.log(f"FEHLER beim Nachladen des Sets: {e}")

    @Slot(str)
    def _on_add_set_service(self, set_id: str) -> None:
        """'Service hinzufuegen' (Kontextmenue): EIGENE Auswahlbox.

        Bugfix 05.08.2026: Eine eigene QInputDialog-Auswahlbox statt der
        frueheren Toolbar-Auswahl. Nach der Auswahl wird der Service direkt
        ins Set uebernommen und sofort persistiert (_add_service_to_set)."""
        if not set_id:
            return
        selector = getattr(self, "service_selector", None)
        ids = sorted(selector.get_plugin_ids()) if selector is not None else []
        if not ids:
            self.log("Keine Services verfuegbar.")
            return
        pid, ok = QInputDialog.getItem(
            self, "Service hinzufuegen",
            "Service waehlen:", ids, 0, False)
        if not ok or not pid:
            return
        self._toolbar_add_service(str(pid), set_id)

    @Slot(str)
    def _on_delete_set(self, set_id: str) -> None:
        """'Set loeschen' (Kontextmenue): Set laden (falls noetig) und
        delete_set() aufrufen - die P14-04-E-Sperre ('letztes Set') und die
        Rueckfrage (Papierkorb, P14-05) greifen dort zentral."""
        if not set_id:
            return
        if self._current_set_id != set_id:
            try:
                definition = self.set_repo.get_set(set_id)
                if definition:
                    self.load_set_into_editor(definition)
            except Exception as e:
                self.log(f"FEHLER beim Laden des Sets: {e}")
                return
        self.delete_set()

    @Slot(str, str, int)
    def _on_move_service(self, set_id: str, service_id: str, delta: int) -> None:
        """Order / (Kontextmenue): Service in der execution_order des Sets
        verschieben - arbeitet direkt auf der DB-Definition und persistiert
        sofort (P14-05-Snapshot via set_repo.save_set)."""
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        order = list(definition.get("execution_order") or [])
        if service_id not in order:
            return
        i = order.index(service_id)
        j = i + delta
        if j < 0 or j >= len(order):
            return
        order[i], order[j] = order[j], order[i]
        definition["execution_order"] = order
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Reihenfolge geaendert: {service_id} "
                 f"({'rauf' if delta < 0 else 'runter'})")
        event_bus.service_set_changed.emit()
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)

    @Slot(str, str)
    def _on_remove_service(self, set_id: str, service_id: str) -> None:
        """'Service entfernen' (Kontextmenue): P14-04-E-Sperrpruefung +
        doppelte Nachfrage (P14-05-Snapshot), dann direkter Entzug aus der
        DB-Definition (kein Umweg ueber die entfernte Service-Sets-Box)."""
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id) or {}
        plugin_id = str(cfg.get("plugin_id") or service_id)
        # P14-04-E: Nur der LETZTE Vorkommen eines Indikator-Services ueber
        # ALLE gespeicherten Sets ist gesperrt.
        if self._plugin_belongs_to_indicator(plugin_id):
            others = self._remaining_sets_with_plugin(
                plugin_id, exclude_set_id=set_id)
            if not others:
                QMessageBox.warning(
                    self, "Service gesperrt",
                    f"Der Service '{plugin_id}' ist der letzte in einem "
                    f"gespeicherten Service-Set.\n"
                    f"Fuer den Indikator muss mindestens ein gueltiges Set "
                    f"mit diesem Service erhalten bleiben (P14-04).")
                return
        reply = QMessageBox.question(
            self, "Service entfernen",
            f"Service '{service_id} [{plugin_id}]' aus dem Set entfernen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            "Der bisherige Set-Stand wird als Snapshot gesichert "
            "(service_set_history). Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        order = [i for i in (definition.get("execution_order") or [])
                 if i != service_id]
        services.pop(service_id, None)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Service entfernt: {service_id}")
        event_bus.service_set_changed.emit()
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)

    @Slot()
    def _on_purge_trash(self) -> None:
        """Leert den Papierkorb ENDGUELTIG (Kontextmenue 'Papierkorb löschen').

        Bugfix 05.08.2026: Doppelte Sicherheitsabfrage (P14-05) – der Vorgang
        ist nicht umkehrbar. Einzelne Sets koennen weiterhin ueber den
        Papierkorb-Dialog (btn_trash_sets) wiederhergestellt werden.
        """
        trash = self.set_repo.list_trash()
        if not trash:
            QMessageBox.information(
                self, "Papierkorb",
                "Der Papierkorb ist leer – es gibt nichts zu löschen.")
            return
        count = len(trash)
        reply = QMessageBox.question(
            self, "Papierkorb löschen",
            f"{count} Set(s) liegen im Papierkorb.\n"
            f"Wirklich ENDGÜLTIG löschen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            "Diese Aktion kann nicht rückgängig gemacht werden.\nFortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        try:
            n = self.set_repo.purge_trash()
        except Exception as e:
            self.log(f"FEHLER beim Leeren des Papierkorbs: {e}")
            return
        self.log(f"Papierkorb geleert: {n} Set(s) endgültig entfernt (P14-05).")
        event_bus.service_set_changed.emit()

    @Slot()
    def delete_set(self) -> None:
        """Loescht das aktive Set in den Papierkorb (P14-05).

        Phase 13-Bereinigung (05.08.2026): Ohne die entfernte Service-Sets-
        Box wird direkt auf die DB-Definition des geladenen Sets zugegriffen
        (kein NamedItemAdapter mehr). P14-04-E-Sperre ('letztes Set') und
        Papierkorb-Rueckfrage bleiben unveraendert."""
        current_id = self._current_set_id
        if not current_id:
            self.log("Kein Set geladen - Loeschen nicht moeglich.")
            return
        current = None
        try:
            current = self.set_repo.get_set(current_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not current:
            self.log(f"Set '{current_id}' nicht gefunden.")
            return
        # P14-04-E-Sperre: Letzter Vorkommen eines Indikator-Services.
        services = current.get("services") or {}
        for cfg in services.values():
            if not isinstance(cfg, dict):
                continue
            pid = str(cfg.get("plugin_id") or "")
            if not pid or not self._plugin_belongs_to_indicator(pid):
                continue
            others = self._remaining_sets_with_plugin(
                pid, exclude_set_id=current_id)
            if not others:
                QMessageBox.warning(
                    self, "Loeschen gesperrt",
                    f"Dieses Service-Set enthaelt den letzten "
                    f"gespeicherten Service '{pid}' fuer den Indikator.\n"
                    f"Es muss mindestens ein gueltiges Set mit diesem "
                    f"Service erhalten bleiben (P14-04).")
                return
        name = str(current.get("display_name") or current_id)
        reply = QMessageBox.question(
            self, "Set in den Papierkorb verschieben",
            f"Set '{name}' wirklich in den Papierkorb verschieben?\n"
            f"(Wiederherstellung ueber den Papierkorb-Dialog moeglich.)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            ok = self.set_repo.delete_set(current_id)
        except Exception as e:
            self.log(f"FEHLER beim Loeschen des Sets: {e}")
            return
        if not ok:
            self.log(f"Set '{current_id}' nicht gefunden.")
            return
        self.log(f"Set in den Papierkorb verschoben (P14-05): {current_id}")
        event_bus.service_set_changed.emit()
        self._current_set_id = None
        self._current_set_definition = None
        self._clear_dirty_markers()
        self._clear_service_columns()
    @Slot()
    def show_trash_dialog(self) -> None:
        """Öffnet den Papierkorb-Dialog für Service-Sets (P14-05).

        Phase 15 U15-D1: Der Dialog ist in serviceui/trash_dialog.py als
        eigenständige Widget-Klasse (ServiceSetTrashDialog) ausgelagert –
        Verhalten unverändert (inkl. doppelter Sicherheitsnachfrage).
        """
        dialog = ServiceSetTrashDialog(
            repo=self.set_repo,
            log_fn=self.log,
            refresh_fn=lambda: None,
            parent=self,
        )
        dialog.exec()
