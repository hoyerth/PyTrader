# serviceui/set_item_adapter.py
"""
Service-UI: Adapter für die generische Service-Set-Verwaltung.

Phase 15, Kapitel 15.1 (U15-D1): Aus service_win.py ausgelagert –
Verhalten unverändert. Die _item_*-Protokoll-Methoden greifen auf das
ServiceWindow (self.dlg) zu (NamedItemActionsMixin-Mechanik, exakt analog
zur Preset-Verwaltung im Indikator-Prop-Fenster).
"""

from typing import Any, Dict, List, Optional

from chart.widgets.named_item_actions import NamedItemAdapter
from analytics.engine.service_set_repository import ServiceSetRepository
from config.event_bus import event_bus


class _ServiceSetItemAdapter(NamedItemAdapter):
    """Adapter für die SERVICE-SET-Sammlung im Service-Fenster.

    Phase 13 Schritt 8: Die Service-Set-Verwaltung (Speichern/Löschen) nutzt
    exakt dieselbe generische Preset-Mechanik wie das Indikator-Prop-Fenster
    (NamedItemActionsMixin). Die _item_*-Protokoll-Methoden liegen in diesem
    Adapter und greifen auf das ServiceWindow (self.dlg) zu.
    """

    def __init__(self, dlg: "ServiceWindow") -> None:
        self.dlg = dlg

    def _item_scope_label(self) -> str:
        return "Service-Set"

    def _item_current_name(self) -> str:
        return self.dlg.edit_set_name.text().strip() if self.dlg.edit_set_name else ""

    def _item_current_id(self) -> Optional[str]:
        if self.dlg._current_set_id:
            return self.dlg._current_set_id
        if self.dlg.combo_set:
            return self.dlg.combo_set.currentData()
        return None

    def _item_auto_name(self) -> str:
        """Auto-Name aus den instance_ids (Roadmap: leerer Name → Auto-Name)."""
        try:
            definition = self.dlg.collect_set_definition()
            definition["display_name"] = ""
            return ServiceSetRepository._default_display_name(definition)
        except Exception as e:
            print(f"⚠️ [ServiceWindow] Auto-Name fehlgeschlagen: {e}")
            return ""

    def _item_list_names(self) -> List[str]:
        return [s.get("display_name") or "" for s in self.dlg.set_repo.list_sets()]

    def _item_exists(self, name: str) -> bool:
        """True, wenn ein ANDERES Set bereits diesen Namen trägt."""
        current = self._item_current_id()
        return any(
            (s.get("display_name") or "") == name and s.get("set_id") != current
            for s in self.dlg.set_repo.list_sets()
        )

    def _item_save_as(self, name: str) -> Optional[str]:
        """Speichert das Set unter 'name'; liefert die set_id zurück."""
        definition = self.dlg.collect_set_definition()
        if not definition.get("execution_order"):
            self.dlg.log("Keine Services in der Ausführungs-Reihenfolge – "
                         "Speichern abgebrochen.")
            return None
        if not definition.get("services"):
            self.dlg.log("WARNUNG: Set hat keine services-Konfiguration "
                         "(nur Reihenfolge wird gespeichert).")
        definition["display_name"] = name
        set_id = self.dlg.set_repo.save_set(definition)
        self.dlg.log(f"Set gespeichert: {set_id}")
        # Phase 15.02: Struktur-Aenderung -> EventBus, damit alle lauschenden
        # ServiceSelectorModel-Instanzen (MasterTree, Analytics, ...) live
        # aktualisieren (Invariante 5: schwellenfreie Entkopplung).
        event_bus.service_set_changed.emit()
        return set_id

    def _item_delete_current(self) -> bool:
        set_id = self._item_current_id()
        if not set_id:
            self.dlg.log("Kein Set zum Löschen ausgewählt.")
            return False
        if self.dlg.set_repo.delete_set(set_id):
            # P14-05: Soft-Delete – das Set liegt im Papierkorb und kann über
            # den Papierkorb-Dialog wiederhergestellt werden.
            self.dlg.log(f"Set in den Papierkorb verschoben (P14-05): {set_id}")
            # Phase 15.02: Struktur-Aenderung -> EventBus (Live-Sync aller
            # ServiceSelectorModel-Instanzen, Invariante 5).
            event_bus.service_set_changed.emit()
            return True
        self.dlg.log(f"Set '{set_id}' nicht gefunden.")
        return False

    def _item_select(self, set_id: Optional[str] = None) -> None:
        """Setzt die Set-Auswahl nach Speichern (set_id) bzw. Löschen (None)."""
        self.dlg._current_set_id = None  # Neuauswahl erzwingen (sonst bleibt Alt-Selektion)
        self.dlg.refresh_set_list()
        if set_id and self.dlg.combo_set:
            idx = self.dlg.combo_set.findData(set_id)
            if idx >= 0:
                self.dlg.combo_set.setCurrentIndex(idx)

    def _item_reserved_name(self) -> Optional[str]:
        return None  # Service-Sets haben kein geschütztes 'Default'-Set


# Öffentlicher Alias (Phase 15 U15-D1): der Adapter ist Teil des Set-Editors
# und wird von außen nicht als "privat" importiert.
ServiceSetItemAdapter = _ServiceSetItemAdapter
