"""
service_selector_dialog_selection.py - Filter/Selection/Apply, Info-Dialoge (Plugin/Set/Description)

23.08 God-File-Split (15.08.2026): Aus serviceui/service_selector_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der ServiceSelectorDialog-
Klasse als Mixin (Klasse ServiceSelectorDialogSelectionMixin).
"""

from typing import (
    Any,
    Dict,
    List,
)

from PySide6.QtCore import (
    Slot,
)

from PySide6.QtWidgets import (
    QMessageBox,
)

from analytics.engine.description_dialog import (
    ServiceDescriptionDialog,
)

class ServiceSelectorDialogSelectionMixin:

    # ------------------------------------------------------------------
    # Oeffentliche API
    # ------------------------------------------------------------------
    def apply_feature_ids(self, feature_ids: List[str],
                          instance_hashes=None) -> None:
        """Spiegelt die aktuelle ViewModel-Auswahl im Baum (Reverse-Mapping).

        Wird beim Oeffnen des Dialogs gerufen, damit ein restauriertes
        Profil bzw. der aktive Filter im Checkbox-Baum sichtbar ist.
        Runde 10 (Bug 1): instance_hashes (Varianten) werden ebenfalls
        auf den Baum gemappt - nur die passenden Clone-Varianten werden
        angehakt (Hash-Granularitaet).
        """
        tree = self.selector.master_tree
        if tree is not None:
            tree.set_checked_feature_ids(
                list(feature_ids or []), list(instance_hashes or []))

    def current_display_names(self) -> List[str]:
        tree = self.selector.master_tree
        return tree.checked_display_names() if tree is not None else []

    def current_feature_ids(self) -> List[str]:
        tree = self.selector.master_tree
        return tree.checked_feature_ids() if tree is not None else []

    # ------------------------------------------------------------------
    # Aktions-Zeile
    # ------------------------------------------------------------------
    def _on_clear_filters(self) -> None:
        """Leert alle Checkboxen (mit Sicherheitsabfrage) und emittiert leer.

        Entspricht dem Task-Vertrag: `services_selected([], [])` – der
        AnalyticsWindow setzt daraufhin den Filter zurueck (alle Features).
        """
        reply = QMessageBox.question(
            self, "Aktive Filter entfernen",
            "Möchtest du alle aktiven Datenquellen-Filter wirklich entfernen? "
            "Die Anzeige im Analytics-Fenster zeigt danach wieder alle "
            "Features.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        tree = self.selector.master_tree
        if tree is not None:
            tree.clear_checks()
        # Bugfix-Runde 3 (06.08.2026): Filter entfernen leert auch das
        # Klick-Panel (kein Scope mehr, Hinweis-Text).
        self._last_scope = None
        self._rebuild_param_panel([])
        self.services_selected.emit([], [])

    def _on_apply(self) -> None:
        """Emittiert `services_selected(display_names, feature_ids)` und zu."""
        self.services_selected.emit(
            self.current_display_names(),
            self.current_feature_ids(),
        )
        self.accept()

    # ------------------------------------------------------------------
    # 20.03.02 (F4): i-Button im MasterTree -> Read-Only-Beschreibung
    # ------------------------------------------------------------------
    @Slot(str, str, str)
    def _on_info_requested(self, set_id: str, service_id: str,
                           plugin_id: str) -> None:
        """Info-Button im MasterTree (ServicePicker, 20.03.02 F4).

        Read-Only `ServiceDescriptionDialog.from_plugin()` bzw.
        `from_set()` (kein Editieren – der editierbare
        `ServiceDescriptionEditDialog` bleibt dem ServiceWindow
        vorbehalten). `header_line` im vereinheitlichten F5-Format
        ('📌 im <Indikator> | 🟢 aktiv in <Indikator>' / '⚪ inaktiv').
        """
        try:
            if service_id and set_id:
                cfg = self.model.find_service(set_id, service_id) or {}
                pid = str(cfg.get("plugin_id") or service_id)
                plugin = self._resolve_info_plugin(pid)
                if plugin is None:
                    return
                dlg = ServiceDescriptionDialog.from_plugin(
                    plugin, instance_id=service_id, config=cfg, parent=self,
                    header_line=self._info_header_line(pid))
                dlg.exec()
            elif plugin_id and not service_id:
                plugin = self._resolve_info_plugin(plugin_id)
                if plugin is None:
                    return
                dlg = ServiceDescriptionDialog.from_plugin(
                    plugin, parent=self,
                    header_line=self._info_header_line(plugin_id))
                dlg.exec()
            elif set_id and not service_id:
                definition = self.model.find_set(set_id)
                if not definition:
                    return
                dlg = ServiceDescriptionDialog.from_set(
                    definition, parent=self,
                    header_line=self._info_set_header_line(definition))
                dlg.exec()
        except (RuntimeError, AttributeError):
            pass

    @Slot(str, str)
    def _on_category_info_requested(self, group: str,
                                    category_path: str) -> None:
        """Info-Dialog fuer einen Kategorie-Ordner (20.03.02, F4).

        Analog zur Set-Info (ServiceDescriptionDialog.from_set, keine
        persistierbare Beschreibung): Read-Only-Liste aller Services unter
        dem Ordner (rekursiv) mit dem Kategorie-Pfad als Titel
        (ServiceWindow-Muster _on_category_info_requested).
        """
        if not category_path:
            return
        try:
            plugin_ids = self.model.category_service_plugin_ids(
                group, category_path)
            definition = {
                "set_id": f"category_{category_path}",
                "display_name": category_path,
                "description": f"Kategorie-Ordner: {category_path}",
                "execution_order": list(plugin_ids),
                "services": {pid: {"plugin_id": pid} for pid in plugin_ids},
            }
            dlg = ServiceDescriptionDialog.from_set(definition, parent=self)
            dlg.exec()
        except (RuntimeError, AttributeError):
            pass

    def _resolve_info_plugin(self, plugin_id: str):
        """Registry-Lookup fuer den Info-Dialog (defensiv, ohne KeyError)."""
        try:
            from analytics.features.feature_builder import PluginRegistry
            return PluginRegistry().get(plugin_id)
        except KeyError:
            return None

    def _info_header_line(self, plugin_id: str) -> str:
        """Erste Dialog-Zeile fuer Plugin-/Service-Zeilen (20.03.02, F5).

        Vereinheitlichtes Badge-Format ('📌 im <Indikator> | 🟢 aktiv in
        <Indikator>' / '⚪ inaktiv'); leer ohne Indikator-Zugehoerigkeit.
        """
        model = self.model
        if model is None or not model.belongs_to_indicator(plugin_id):
            return ""
        name = model.get_indicator_display_name(plugin_id)
        if model.is_active_in_chart(plugin_id):
            return f"📌 im {name} | 🟢 aktiv in {name}"
        return f"📌 im {name} | ⚪ inaktiv"

    def _info_set_header_line(self, set_def: Dict[str, Any]) -> str:
        """Erste Dialog-Zeile fuer Set-Zeilen (20.03.02, F5).

        Vereinheitlichtes Badge-Format; mehrere Indikatoren mit ' + '
        verknuepft.
        """
        model = self.model
        if model is None:
            return ""
        names = model.get_set_indicator_names(set_def or {})
        if not names:
            return ""
        label = " + ".join(names)
        if model.is_set_active(set_def or {}):
            return f"📌 im {label} | 🟢 aktiv in {label}"
        return f"📌 im {label} | ⚪ inaktiv"
