# chart/widgets/named_item_actions.py
"""
Generische Neu-/Speichern-/Löschen-Logik für benannte Sammlungen
(Presets, Service-Sets) – analog zur Preset-Verwaltung im Prop-Fenster.

Warum: Die Service-Set-Verwaltung (Indikator-Prop-Fenster + Service-Fenster)
soll identisch zur bewährten Preset-Mechanik im Indikator-Prop-Fenster
funktionieren. Statt die Dialog-Logik an zwei Stellen zu duplizieren, liegt
sie hier ZENTRAL in einem Mixin; die Unterklassen implementieren nur noch
die _item_*-Callbacks (Namen, Listen, Persistenz, Auswahl).

Mechanik (identisch zur Preset-Verwaltung):
  * SPEICHERN (save_named_item):
      - Namensdialog (QInputDialog.getText), vorbelegt mit dem aktuellen Namen.
      - Leerer Name  → Auto-Name, falls die Unterklasse einen liefert
        (_item_auto_name, z.B. 'grid_1 + prox_1'), sonst Abbruch mit Hinweis.
      - Geschützter Name (z.B. 'Default') → Ablehnung.
      - Name bereits vergeben → Überschreiben-Rückfrage (QMessageBox.question).
      - Danach speichern (_item_save_as, liefert die neue ID) und die Auswahl
        auf das gespeicherte Element setzen (_item_select(id)).
  * LÖSCHEN (delete_named_item):
      - Geschützter Name → Ablehnung.
      - Rückfrage (QMessageBox.question, Default = Nein).
      - Danach löschen (_item_delete_current) und das nächstverfügbare Element
        auswählen (_item_select(None)).

Die UI-Interaktion (Dialoge, Rückfragen, Ablauf) ist damit exakt einmal
implementiert und für Presets UND Service-Sets identisch.
"""

from typing import Any, List, Optional

from PySide6.QtWidgets import QInputDialog, QMessageBox


class NamedItemActionsMixin:
    """Mixin für benannte Sammlungen (Presets / Service-Sets).

    Die Unterklasse implementiert die _item_*-Callbacks; diese Klasse liefert
    save_named_item()/delete_named_item() mit der Preset-Mechanik.
    """

    # ------------------------------------------------------------------
    # Callbacks (von der Unterklasse zu implementieren)
    # ------------------------------------------------------------------
    def _item_scope_label(self) -> str:
        """Anzeigename der Sammlung, z.B. 'Service-Set' / 'Preset'."""
        raise NotImplementedError

    def _item_current_name(self) -> str:
        """Aktueller Name des bearbeiteten Elements (Editor/Combo)."""
        raise NotImplementedError

    def _item_current_id(self) -> Optional[str]:
        """Aktuelle ID des bearbeiteten Elements (oder None bei neu)."""
        raise NotImplementedError

    def _item_auto_name(self) -> str:
        """Auto-Name bei leerem Namensfeld (z.B. 'grid_1 + prox_1').

        Leerer String → der Mixin bricht mit einem Hinweis ab (Preset-
        Verhalten). Service-Sets liefern hier den Default-Name aus den
        instance_ids (Roadmap: 'leerer Name → Auto-Name').
        """
        return ""

    def _item_list_names(self) -> List[str]:
        """Alle vorhandenen Namen der Sammlung."""
        raise NotImplementedError

    def _item_exists(self, name: str) -> bool:
        """True, wenn 'name' bereits von einem ANDEREN Element vergeben ist."""
        raise NotImplementedError

    def _item_save_as(self, name: str) -> Optional[Any]:
        """Speichert das Element unter 'name' und liefert die neue ID zurück.

        None → Speichern wurde abgebrochen (z.B. ungültige Sammlung); der
        Mixin überspringt dann die Auswahl-Aktualisierung.
        """
        raise NotImplementedError

    def _item_delete_current(self) -> bool:
        """Löscht das aktuelle Element; liefert True bei Erfolg."""
        raise NotImplementedError

    def _item_select(self, name_or_id: Optional[Any] = None) -> None:
        """Setzt die Auswahl: nach dem Speichern auf das neue Element,
        nach dem Löschen (name_or_id=None) auf das nächstverfügbare."""
        raise NotImplementedError

    def _item_reserved_name(self) -> Optional[str]:
        """Geschützter Name (z.B. 'Default' für Presets) oder None."""
        return None

    # ------------------------------------------------------------------
    # Preset-analoge Mechanik (ZENTRAL – für Presets und Service-Sets)
    # ------------------------------------------------------------------
    def save_named_item(self, dialog_title: Optional[str] = None,
                        prompt: Optional[str] = None) -> None:
        """Speichert ein Element analog zur Preset-Verwaltung.

        Ablauf: Namensdialog → Auto-Name bei leerem Feld → Schutz des
        reservierten Namens → Überschreiben-Rückfrage bei doppeltem Namen →
        speichern (_item_save_as) → Auswahl aktualisieren (_item_select).
        """
        scope = self._item_scope_label()
        title = dialog_title or f"{scope} speichern"
        label = prompt or f"Name für das {scope}:"
        current = self._item_current_name()

        name, ok = QInputDialog.getText(self, title, label, text=current)
        if not ok:
            return  # Benutzer abgebrochen

        clean = name.strip()
        if not clean:
            auto = self._item_auto_name()
            if not auto:
                QMessageBox.warning(self, "Fehler",
                                    "Der Name darf nicht leer sein.")
                return
            clean = auto

        reserved = self._item_reserved_name()
        if reserved and clean.lower() == reserved.lower():
            QMessageBox.warning(
                self, "Fehler",
                f"Der Name '{reserved}' ist geschützt und kann nicht "
                f"überschrieben werden.",
            )
            return

        if self._item_exists(clean):
            reply = QMessageBox.question(
                self, "Überschreiben bestätigen",
                f"{scope} '{clean}' existiert bereits.\n"
                f"Möchtest du es überschreiben?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        new_id = self._item_save_as(clean)
        if new_id is not None:
            self._item_select(new_id)

    def delete_named_item(self) -> None:
        """Löscht das aktuelle Element analog zur Preset-Verwaltung.

        Ablauf: Schutz des reservierten Namens → Rückfrage → löschen
        (_item_delete_current) → nächstes Element auswählen (_item_select(None)).
        """
        scope = self._item_scope_label()
        current = self._item_current_name()
        if not current:
            return

        reserved = self._item_reserved_name()
        if reserved and current == reserved:
            QMessageBox.warning(self, "Fehler",
                                f"'{reserved}' kann nicht gelöscht werden.")
            return

        reply = QMessageBox.question(
            self, "Löschen bestätigen",
            f"Möchtest du {scope} '{current}' wirklich löschen?\n"
            f"Dies kann nicht rückgängig gemacht werden.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._item_delete_current()
        self._item_select(None)
