"""
master_tree_selection.py - Selektion & Public-API (current_*, select_*, Restore, _select_by)

23.06 God-File-Split (15.08.2026): Aus serviceui/master_tree.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der MasterTree-
Klasse als Mixin (Klasse MasterTreeSelectionMixin).
"""

from typing import (
    Dict,
)

from serviceui.master_tree_constants import (
    ROLE_INSTANCE_HASH,
    ROLE_INSTANCE_ID,
    ROLE_NODE_TYPE,
    ROLE_PLUGIN_ID,
    ROLE_SET_ID,
    TYPE_CLONE,
    TYPE_SERVICE,
    TYPE_SET,
    TreeItemIterator,
    isValid,
)

class MasterTreeSelectionMixin:

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
