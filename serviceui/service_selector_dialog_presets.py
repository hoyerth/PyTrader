"""
service_selector_dialog_presets.py - Preset-/Varianten-Verwaltung (Save, Duplicate, Rename, Purge, Doc-Log)

23.08 God-File-Split (15.08.2026): Aus serviceui/service_selector_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der ServiceSelectorDialog-
Klasse als Mixin (Klasse ServiceSelectorDialogPresetMixin).
"""

from typing import (
    Any,
    Dict,
    Optional,
)

from PySide6.QtCore import (
    Slot,
)

from PySide6.QtWidgets import (
    QInputDialog,
    QMessageBox,
)

from config.event_bus import (
    event_bus,
)

class ServiceSelectorDialogPresetMixin:

    # ------------------------------------------------------------------
    # 18.01.01 (E-4): Live-Verwaltung (Set/Service-CRUD im Picker)
    # ------------------------------------------------------------------
    @Slot()
    def _on_save_plugin_params(self) -> None:
        """Speichern-Button: persistiert die editierbaren Standalone-Params."""
        if not self._param_host._save_plugin_params():
            QMessageBox.warning(
                self, "Fehler",
                "Parameter konnten nicht gespeichert werden "
                "(kein editierbarer Standalone-Service ausgewählt).")

    # ------------------------------------------------------------------
    # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im Kontextmenue – Handler
    # (Muster service_win, ohne Editor-Load/Logging; der Dialog ist ein
    # Read-Only-Picker, aber die Duplizierung/Loeschung muss funktionieren).
    # ------------------------------------------------------------------

    def _find_preset_for_hash(self, plugin_id: str,
                              instance_hash: str):
        """Preset-Dict zu plugin_id + instance_hash (indicator_presets)."""
        try:
            sm = self.model.state_manager
            for preset in sm.list_plugin_presets(plugin_id) or []:
                if not isinstance(preset, dict):
                    continue
                from analytics.engine.service_models import (
                    generate_instance_hash)
                # 11.08.2026 (Bugfix Varianten-Kollision): Hash eines
                # Presets inkl. preset_name (identisch zu Modell/Run);
                # Legacy-Fallback fuer Alt-Bestand.
                preset_name = str(preset.get("preset_name") or "Default")
                if (generate_instance_hash(plugin_id,
                                           preset.get("params") or {},
                                           preset_name=preset_name)
                        == instance_hash
                        or generate_instance_hash(
                            plugin_id, preset.get("params") or {})
                        == instance_hash):
                    return preset
        except Exception:
            pass
        return None

    def _purge_legacy_allowed(self, plugin_id: str,
                              params: Optional[Dict[str, Any]]) -> bool:
        """True, wenn der Params-only-Legacy-Pool der Variante EINDEUTIG
        dieser Variante gehoert (12.08.2026, Bugfix Runde 6).

        Alt-Rows aus Runs VOR der Preset-Hash-Umstellung (11.08.2026) liegen
        unter dem reinen Params-only-Hash `generate_instance_hash(plugin_id,
        params)` (ohne preset_name). Dieser Pool ist mehreren Varianten mit
        IDENTISCHEN Params gemeinsam - er darf beim 'Data Only Loeschen'
        einer einzelnen Variante nur entfernt werden, wenn KEINE andere
        aktive Variante (Preset/Clone ODER Set-Instanz) denselben
        Params-only-Hash besitzt.

        Returns:
            True = Pool eindeutig dieser Variante zugeordnet (Legacy-Purge
            erlaubt); False = Pool wird geteilt oder nicht bestimmbar.
        """
        if not plugin_id or params is None:
            return False
        try:
            from analytics.engine.service_models import generate_instance_hash
        except Exception:
            return False
        target = generate_instance_hash(plugin_id, params)
        owners = 0
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            try:
                sm = self.model.state_manager
            except Exception:
                sm = None
        if sm is not None:
            try:
                for p in sm.list_plugin_presets(plugin_id) or []:
                    if not isinstance(p, dict):
                        continue
                    if generate_instance_hash(
                            plugin_id, p.get("params") or {}) == target:
                        owners += 1
            except Exception:
                pass
        try:
            for set_id in (self.set_repo.list_sets()
                           if self.set_repo is not None else []):
                defn = self.set_repo.get_set(set_id)
                if not isinstance(defn, dict):
                    continue
                for cfg in (defn.get("services") or {}).values():
                    if not isinstance(cfg, dict):
                        continue
                    cpid = str(cfg.get("plugin_id") or "")
                    if cpid.lower() == plugin_id.lower() and \
                            generate_instance_hash(
                                cpid, cfg.get("params") or {}) == target:
                        owners += 1
        except Exception:
            pass
        # owners == 1: nur diese eine Variante belegt den Pool. owners == 0
        # (z. B. Standalone-Service): kein Legacy-Pool-Szenario - False.
        return owners == 1

    @Slot(str, str, str, str)
    def _on_duplicate_variant(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Als Variante duplizieren' (20.04, Q8) – Muster service_win."""
        try:
            if set_id and service_id:
                self._duplicate_set_instance(set_id, service_id)
                return
            if plugin_id:
                self._duplicate_preset(plugin_id, instance_hash)
                return
        except (RuntimeError, AttributeError):
            pass

    @Slot(str, str, str)
    def _on_rename_variant(self, plugin_id: str, instance_hash: str,
                           new_name: str) -> None:
        """'Variante umbenennen' (10.08.2026, Bugfix) – Picker-Variante.

        Persistiert den Rename in indicator_presets (indicator_id,
        preset_name) mit Kollisionspruefung. Die Feature-Store-Daten
        (Spalte instance_hash) bleiben unberuehrt. Der Picker nutzt
        QMessageBox-Warnungen statt des ServiceWindow-Loggings.
        """
        try:
            sm = self.model.state_manager
        except Exception:
            return
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            QMessageBox.warning(
                self, "Umbenennen",
                f"Preset zu #{instance_hash} nicht gefunden.")
            return
        old_name = str(preset.get("preset_name") or "Default")
        indicator_id = str(preset.get("indicator_id") or "")
        if not indicator_id:
            QMessageBox.warning(
                self, "Umbenennen",
                "Preset hat keine indicator_id – Umbenennen abgebrochen.")
            return
        clean = (new_name or "").strip()
        if not clean or clean == old_name:
            return
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if clean in existing:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Eine andere Variante von '{plugin_id}' heisst bereits "
                f"'{clean}'.")
            return
        try:
            sm.rename_indicator_preset(indicator_id, old_name, clean)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        event_bus.service_set_changed.emit()

    def _next_preset_copy_name(self, plugin_id: str, base: str) -> str:
        """Naechster freier Preset-Name '<base> (Kopie)', '(Kopie 2)', ..."""
        try:
            sm = self.model.state_manager
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if base not in existing:
            return base
        candidate = f"{base} (Kopie)"
        i = 2
        while candidate in existing:
            i += 1
            candidate = f"{base} (Kopie {i})"
        return candidate

    def _duplicate_set_instance(self, set_id: str, service_id: str) -> None:
        """Dupliziert eine Service-Instanz in ihrem Set (Q8)."""
        if self.set_repo is None:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception:
            return
        if not definition:
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id)
        if not isinstance(cfg, dict):
            return
        pid = str(cfg.get("plugin_id") or service_id)
        iid = self._next_instance_id(services, pid)
        copy = dict(cfg)
        copy["params"] = dict(cfg.get("params") or {})
        from analytics.engine.service_models import generate_instance_hash
        copy["instance_hash"] = generate_instance_hash(pid, copy["params"])
        copy.pop("description", None)
        copy.pop("doc_log", None)
        services[iid] = copy
        order = list(definition.get("execution_order") or [])
        order.append(iid)
        definition["execution_order"] = order
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
        except Exception:
            return
        event_bus.service_set_changed.emit()

    def _duplicate_preset(self, plugin_id: str, instance_hash: str) -> None:
        """Dupliziert einen Plugin-Clone als neues Preset (Q8)."""
        try:
            sm = self.model.state_manager
        except Exception:
            return
        base = "Default"
        params = {}
        indicator_id = plugin_id
        version = "1.0.0"
        if instance_hash:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset is None:
                return
            base = str(preset.get("preset_name") or "Default")
            params = dict(preset.get("params") or {})
            indicator_id = str(preset.get("indicator_id") or plugin_id)
            version = preset.get("version") or "1.0.0"
        else:
            # Flaches Plugin-Blatt: aktuelle Standalone-Parameter.
            try:
                raw = sm.get_global_value(f"plugin_params_{plugin_id}", {})
            except Exception:
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            params = dict(raw.get("params") or {})
            version = raw.get("version") or "1.0.0"
        # 10.08.2026 (Bugfix): Beim Anlegen einer neuen Variante MUSS ein
        # neuer Name vergeben werden – der Dialog ist mit dem freien
        # Kopiernamen vorbelegt; Kollisionen werden abgefangen.
        suggested = self._next_preset_copy_name(plugin_id, base)
        new_name, ok = QInputDialog.getText(
            self, "Variante anlegen",
            f"Name für die neue Variante (aus '{base}'):", text=suggested)
        new_name = (new_name or "").strip()
        if not ok or not new_name:
            return
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception:
            existing = set()
        if new_name in existing:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Eine andere Variante von '{plugin_id}' heisst bereits "
                f"'{new_name}'.")
            return
        try:
            sm.save_indicator_preset(
                indicator_id, new_name, params,
                plugin_id=plugin_id,
                version=version,
                # Q8-Bugfix: Kopie IMMER batch-aktiv (nicht Erbe vom
                # Quell-Preset), damit Scans/LiveAnalyzer sie berechnen.
                is_active_batch=True,
                doc_log="",
            )
        except Exception:
            return
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_data_only_purge(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Data Only Löschen' (Q5): Feature-Daten purgen, Struktur bleibt."""
        if not instance_hash:
            return
        # 11.08.2026 (Bugfix Runde 5): Parameter der Variante ermitteln
        # – Grundlage fuer den Legacy-Pool-Purge (Params-only-Hash).
        params = None
        if set_id and service_id:
            try:
                _cfg = self.model.find_service(set_id, service_id)
                if isinstance(_cfg, dict):
                    params = _cfg.get("params") or {}
            except Exception:
                pass
        if params is None:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset:
                params = preset.get("params") or {}
        reply = QMessageBox.question(
            self, "Data Only Löschen",
            f"Feature-Daten der Variante #{instance_hash} löschen?\n"
            "Struktur, Parameter und Doc-Log bleiben erhalten.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            from analytics.features.feature_builder import FeatureBuilder
            FeatureBuilder().purge_instance_data(
                instance_hash, plugin_id, params,
                purge_legacy=self._purge_legacy_allowed(
                    plugin_id, params))
        except Exception:
            pass
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_delete_complete(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Vollständig Löschen': Preset/Instanz + Daten entfernen."""
        try:
            sm = self.model.state_manager
        except Exception:
            return
        if set_id and service_id and self.set_repo is not None:
            try:
                definition = self.set_repo.get_set(set_id)
            except Exception:
                return
            if not definition:
                return
            services = dict(definition.get("services") or {})
            cfg = services.get(service_id)
            if not isinstance(cfg, dict):
                return
            label = str(cfg.get("plugin_id") or service_id)
            reply = QMessageBox.question(
                self, "Vollständig Löschen",
                f"Instanz '{service_id}' aus Set '{set_id}' vollständig "
                "löschen?\n\nDas Preset wird entfernt UND die "
                "berechneten Feature-Daten gelöscht.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            services.pop(service_id, None)
            order = [i for i in (definition.get("execution_order") or [])
                     if i != service_id]
            definition["execution_order"] = order
            definition["services"] = services
            try:
                self.set_repo.save_set(definition)
            except Exception:
                return
            if instance_hash:
                try:
                    from analytics.features.feature_builder import (
                        FeatureBuilder)
                    FeatureBuilder().purge_instance_data(
                        instance_hash,
                        plugin_id or (cfg.get("plugin_id") or ""),
                        cfg.get("params") or {})
                except Exception:
                    pass
            event_bus.service_set_changed.emit()
            return
        if plugin_id and instance_hash:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset is None:
                return
            preset_name = str(preset.get("preset_name") or "Default")
            indicator_id = str(preset.get("indicator_id") or "")
            reply = QMessageBox.question(
                self, "Vollständig Löschen",
                f"Preset '{preset_name}' von '{plugin_id}' vollständig "
                "löschen?\n\nDas Preset wird entfernt UND die "
                "berechneten Feature-Daten gelöscht.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            if sm is not None and indicator_id:
                try:
                    sm.delete_indicator_preset(indicator_id, preset_name)
                except Exception:
                    return
            if instance_hash:
                try:
                    from analytics.features.feature_builder import (
                        FeatureBuilder)
                    FeatureBuilder().purge_instance_data(
                        instance_hash, plugin_id, preset.get("params") or {},
                        purge_legacy=self._purge_legacy_allowed(
                            plugin_id, preset.get("params") or {}))
                except Exception:
                    pass
            event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_doc_log_requested(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Doc Log bearbeiten' (Q7) – Read-Only-Hinweis im Picker.

        Der Dialog ist ein Read-Only-Datenquellen-Picker ohne Editor – die
        vollstaendige Doc-Log-Bearbeitung uebernimmt das ServiceWindow. Hier
        wird eine kurze Info angezeigt, damit der Menuepunkt nicht wirkungslos
        bleibt.
        """
        try:
            if set_id and service_id:
                QMessageBox.information(
                    self, "Doc Log",
                    "Die Doc-Log-Bearbeitung erfolgt im ServiceWindow "
                    "(Kontextmenü der Instanz).")
                return
            if plugin_id and instance_hash:
                preset = self._find_preset_for_hash(plugin_id, instance_hash)
                doc = str((preset or {}).get("doc_log") or "")
                QMessageBox.information(
                    self, "Doc Log",
                    f"Doc Log von '{plugin_id}':\n\n{doc or '(leer)'}\n\n"
                    "Bearbeitung im ServiceWindow (Kontextmenü des Clones).")
                return
        except (RuntimeError, AttributeError):
            pass

    def _next_instance_id(self, services: Dict[str, Any],
                          plugin_id: str) -> str:
        """Naechste freie instance_id fuer ein Plugin im Set (service_win-
        Muster): Basis ist die plugin_id, bei Belegung '_2', '_3', ..."""
        base = plugin_id
        if base not in services:
            return base
        i = 2
        while f"{base}_{i}" in services:
            i += 1
        return f"{base}_{i}"
