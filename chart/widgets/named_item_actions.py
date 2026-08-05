# chart/widgets/named_item_actions.py
"""
Generische Neu-/Speichern-/Löschen-Logik für benannte Sammlungen
(Presets, Service-Sets) – analog zur Preset-Verwaltung im Prop-Fenster.

Warum: Die Service-Set-Verwaltung (Indikator-Prop-Fenster + Service-Fenster)
soll identisch zur bewährten Preset-Mechanik im Indikator-Prop-Fenster
funktionieren. Statt die Dialog-Logik an mehreren Stellen zu duplizieren,
liegt sie hier ZENTRAL im NamedItemActionsMixin; die Aufrufer liefern nur
noch einen NamedItemAdapter mit den _item_*-Protokoll-Methoden.

Mechanik (identisch zur Preset-Verwaltung):
  * SPEICHERN (save_named_item(adapter, ...)):
      - Namensdialog (QInputDialog.getText), vorbelegt mit dem aktuellen Namen.
      - Leerer Name  → Auto-Name, falls der Adapter einen liefert
        (_item_auto_name, z.B. 'grid_1 + prox_1'), sonst Abbruch mit Hinweis.
      - Geschützter Name (z.B. 'Default') → Ablehnung.
      - Name bereits vergeben → Überschreiben-Rückfrage (QMessageBox.question).
      - Danach speichern (_item_save_as, liefert die neue ID) und die Auswahl
        auf das gespeicherte Element setzen (_item_select(id)).
  * LÖSCHEN (delete_named_item(adapter)):
      - Geschützter Name → Ablehnung.
      - Rückfrage (QMessageBox.question, Default = Nein).
      - Danach löschen (_item_delete_current) und das nächstverfügbare Element
        auswählen (_item_select(None)).

Die UI-Interaktion (Dialoge, Rückfragen, Ablauf) ist damit exakt einmal
implementiert und für Presets UND Service-Sets identisch.

Hinweis (Adapter-Design): Ein Dialog/Window kann MEHRERE benannte Sammlungen
verwalten (z.B. Presets + Service-Sets im Indikator-Prop-Fenster). Die
_item_*-Callbacks dürfen daher NICHT auf der Dialog-Klasse selbst liegen –
zwei Callback-Sätze würden sich sonst gegenseitig überschreiben (gleiche
Methodennamen). Stattdessen implementiert pro Sammlung EIN NamedItemAdapter
die _item_*-Methoden und wird beim Aufruf an das Mixin übergeben.
"""

from typing import Any, List, Optional

from PySide6.QtWidgets import QInputDialog, QMessageBox


class NamedItemAdapter:
    """Protokoll/Basisklasse für EINE benannte Sammlung (Presets / Service-Sets).

    Ein Adapter kapselt die Sammlungsspezifik (Namen, Listen, Persistenz,
    Auswahl) und greift dazu auf das Host-Widget (Dialog/Fenster) zu – der
    Host hält dafür eine Referenz auf den Adapter (z.B. self._set_adapter).
    """

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


class NamedItemActionsMixin:
    """Mixin für benannte Sammlungen (Presets / Service-Sets).

    Liefert save_named_item(adapter)/delete_named_item(adapter) mit der
    Preset-Mechanik; der Adapter (NamedItemAdapter) kapselt die
    Sammlungsspezifik. Die UI-Interaktion ist damit exakt einmal implementiert.
    """

    # ------------------------------------------------------------------
    # Preset-analoge Mechanik (ZENTRAL – für Presets und Service-Sets)
    # ------------------------------------------------------------------
    def save_named_item(self, adapter: NamedItemAdapter,
                        dialog_title: Optional[str] = None,
                        prompt: Optional[str] = None) -> None:
        """Speichert ein Element analog zur Preset-Verwaltung.

        Ablauf: Namensdialog → Auto-Name bei leerem Feld → Schutz des
        reservierten Namens → Überschreiben-Rückfrage bei doppeltem Namen →
        speichern (adapter._item_save_as) → Auswahl aktualisieren
        (adapter._item_select).
        """
        scope = adapter._item_scope_label()
        title = dialog_title or f"{scope} speichern"
        label = prompt or f"Name für das {scope}:"
        current = adapter._item_current_name()

        name, ok = QInputDialog.getText(self, title, label, text=current)
        if not ok:
            return  # Benutzer abgebrochen

        clean = name.strip()
        if not clean:
            auto = adapter._item_auto_name()
            if not auto:
                QMessageBox.warning(self, "Fehler",
                                    "Der Name darf nicht leer sein.")
                return
            clean = auto

        reserved = adapter._item_reserved_name()
        if reserved and clean.lower() == reserved.lower():
            QMessageBox.warning(
                self, "Fehler",
                f"Der Name '{reserved}' ist geschützt und kann nicht "
                f"überschrieben werden.",
            )
            return

        if adapter._item_exists(clean):
            reply = QMessageBox.question(
                self, "Überschreiben bestätigen",
                f"{scope} '{clean}' existiert bereits.\n"
                f"Möchtest du es überschreiben?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        new_id = adapter._item_save_as(clean)
        if new_id is not None:
            adapter._item_select(new_id)

    def delete_named_item(self, adapter: NamedItemAdapter,
                          confirm: bool = True) -> None:
        """Löscht das aktuelle Element analog zur Preset-Verwaltung.

        Ablauf: Schutz des reservierten Namens → (optional) Rückfrage →
        löschen (adapter._item_delete_current) → nächstes Element auswählen
        (adapter._item_select(None)).

        Bugfix 05.08.2026 (Papierkorb): Service-Sets werden soft-deleted –
        der Aufrufer (ServiceWindow.delete_set) fragt bereits einmal nach
        ('Set in den Papierkorb verschieben') und ruft diese Methode mit
        confirm=False auf, damit KEINE zweite Rückfrage erscheint. Die
        Preset-Verwaltung (ohne Papierkorb) behält confirm=True (Default).
        """
        scope = adapter._item_scope_label()
        current = adapter._item_current_name()
        if not current:
            return

        reserved = adapter._item_reserved_name()
        if reserved and current == reserved:
            QMessageBox.warning(self, "Fehler",
                                f"'{reserved}' kann nicht gelöscht werden.")
            return

        if confirm:
            reply = QMessageBox.question(
                self, "Löschen bestätigen",
                f"Möchtest du {scope} '{current}' wirklich löschen?\n"
                f"Dies kann nicht rückgängig gemacht werden.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        adapter._item_delete_current()
        adapter._item_select(None)
