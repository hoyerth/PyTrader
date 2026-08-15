"""
serviceui/service_win_presets.py - Presets/Varianten/Doc-Log (Tree-Info, Preset-Hash, Purge, Duplicate, Varianten, Doc-Log)

23.04 God-File-Split (15.08.2026): Aus serviceui/service_win.py extrahiert,
KEINE Logik-Aenderung. Enthaelt die Methoden der ServiceWindow
als Mixin (Klasse ServicePresetMixin).
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

from analytics.engine.description_dialog import (
    ServiceDescriptionEditDialog,
)

from analytics.engine.service_models import (
    generate_instance_hash,
)

from config.event_bus import (
    event_bus,
)

class ServicePresetMixin:

    @Slot(str, str, str)
    def _on_tree_info_requested(self, set_id: str, service_id: str,
                                plugin_id: str) -> None:
        """Oeffnet den Beschreibungs-Editor / -Dialog fuer die Info-Button-Zeile.

        Bugfix 05.08.2026: Der Info-Button sitzt jetzt direkt im MasterTree
        (Spalte 1) statt in der Box 'Service-Sets (Phase 13)'. Je nach
        Zeilentyp:

          * Service-Zeile:  ServiceDescriptionEditDialog (Instanz-Beschreibung
                            editierbar, header_line = 'aktiv/im <Indikator>').
          * Set-Zeile:      ServiceDescriptionEditDialog (Set-Beschreibung
                            editierbar, header_line aus _info_set_tooltip).
          * Plugin-Zeile:   ServiceDescriptionEditDialog (Plugin-Info, ohne
                            Instanz) – Bugfix 05.08.2026: derselbe Editor wie
                            bei den Einzel-Services der Sets (vorbefuellt mit
                            der Plugin-Beschreibung; kein Persistenz-Ziel).

        Bugfix 05.08.2026: Auch Plugin-/Standalone-Zeilen oeffnen den
        Beschreibungs-Editor (konsistent zu den Einzel-Services). Eine
        persistierbare Beschreibung existiert nur fuer Instanzen (in Sets)
        und fuer die Sets selbst.
        """
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return
        try:
            # 1) Service-Zeile (set_id + service_id) – editierbar
            if service_id and set_id:
                cfg = model.find_service(set_id, service_id) or {}
                pid = str(cfg.get("plugin_id") or service_id)
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id=service_id,
                    plugin_id=pid,
                    header_line=self._info_header_tooltip(pid),
                    description=str(cfg.get("description") or ""),
                    title="Service-Beschreibung bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda desc, s=set_id, i=service_id:
                    self._save_instance_description(s, i, desc))
                dlg.exec()
                return
            # 2) Plugin-Zeile (nur plugin_id; set_id = Gruppenkennung) –
            #    EDITIERBAR wie die Einzel-Services der Sets (Bugfix
            #    05.08.2026): derselbe ServiceDescriptionEditDialog. Ein
            #    Plugin ohne Instanz/Set hat keine persistierbare Instanz-
            #    Beschreibung – der Editor wird mit der Plugin-Metadaten-
            #    Beschreibung vorbefuellt (kein save_requested: Speichern/
            #    Abbrechen schliessen den Dialog, es gibt kein Ziel).
            if plugin_id and not service_id:
                plugin = self._resolve_info_plugin(plugin_id)
                if plugin is None:
                    return
                meta = dict(getattr(plugin, "metadata", None) or {})
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id="",
                    plugin_id=plugin_id,
                    header_line=self._info_header_tooltip(plugin_id),
                    description=str(meta.get("description") or ""),
                    title="Service-Beschreibung bearbeiten",
                )
                dlg.exec()
                return
            # 3) Set-Zeile (nur set_id) – editierbar (Set-Beschreibung)
            if set_id and not service_id and not plugin_id:
                set_def = model.find_set(set_id)
                if not set_def:
                    self.log(f"Set '{set_id}' nicht gefunden.")
                    return
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id="",
                    plugin_id=str(set_def.get("display_name") or set_id),
                    header_line=self._info_set_tooltip(set_def),
                    description=str(set_def.get("description") or ""),
                    title="Set-Beschreibung bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda desc, s=set_id: self._save_set_description(s, desc))
                dlg.exec()
                return
        except (RuntimeError, AttributeError) as e:
            self.log(f"Info-Dialog nicht moeglich: {e}")

    # =========================================================================
    # 20.04 (Q5/Q6/Q8): Instanz-Verwaltung im MasterTree-Kontextmenue
    # -------------------------------------------------------------------------
    # 'Data Only Löschen', 'Vollständig Löschen', 'Doc Log bearbeiten' und
    # 'Als Variante duplizieren' fuer Service-Instanzen (in Sets) und
    # Plugin-Clones (indicator_presets). Alle Aktionen laufen entkoppelt
    # ueber die MasterTree-Signale (keine UI-Kopplung, Invariante 2).
    # =========================================================================

    def _find_preset_for_hash(self, plugin_id: str,
                              instance_hash: str) -> Optional[Dict[str, Any]]:
        """Findet das Preset (indicator_presets) eines Clones ueber seinen
        deterministischen instance_hash (20.04, Q2/Q4)."""
        if not plugin_id or not instance_hash:
            return None
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            return None
        try:
            for p in sm.list_plugin_presets(plugin_id) or []:
                if not isinstance(p, dict):
                    continue
                params = p.get("params") or {}
                # 11.08.2026 (Bugfix Varianten-Kollision): Der Hash eines
                # Presets fliesst inkl. preset_name ein (identisch zum
                # ServiceSelectorModel / variant_run_entries). Fallback auf
                # den Legacy-Params-only-Hash fuer Alt-Bestand.
                preset_name = str(p.get("preset_name") or "Default")
                if (generate_instance_hash(plugin_id, params,
                                           preset_name=preset_name)
                        == instance_hash
                        or generate_instance_hash(plugin_id, params)
                        == instance_hash):
                    return p
        except Exception as e:
            self.log(f"Preset-Suche fehlgeschlagen: {e}")
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
            for set_id in self.set_repo.list_sets():
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

    def _next_preset_copy_name(self, sm, plugin_id: str,
                               base: str) -> str:
        """Naechster freier Preset-Name fuer eine Varianten-Kopie (Q8).

        Quelle ist `list_plugin_presets(plugin_id)` (nur ECHTE Preset-Rows) –
        NICHT `list_indicator_presets`, das den UI-Default 'Default' immer
        fabriziert. Ist der Basis-Name (z. B. 'Default') noch GAR NICHT
        vergeben – der Fall eines flachen Plugin-Blattes, das seine erste
        Variante erhaelt – wird der Basis-Name direkt verwendet. Sonst
        '<base> (Kopie)', '(Kopie 2)', ...
        """
        try:
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
            candidate = f"{base} (Kopie {i})"
            i += 1
        return candidate

    @Slot(str, str, str, str)
    def _on_data_only_purge(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Data Only Löschen' (20.04, Q5): purge_instance_data.

        Entfernt NUR die berechneten Feature-Daten der Instanz aus dem
        feature_store – die Instanz-Konfiguration (Set/Preset) bleibt
        unangetastet; die Daten werden beim naechsten Scan neu berechnet.

        * Service-in-Set: Hash aus der Set-Definition (cfg.instance_hash)
          oder bei Alt-Daten aus den aktuellen Params neu berechnet.
        * Clone/Preset: Hash direkt aus ROLE_INSTANCE_HASH.
        """
        params = None
        if not instance_hash:
            if set_id and service_id:
                model = getattr(self.service_selector, "model", None)
                cfg = model.find_service(set_id, service_id) if model else None
                if cfg:
                    params = cfg.get("params") or {}
                    instance_hash = generate_instance_hash(
                        cfg.get("plugin_id") or service_id, params)
            if not instance_hash:
                self.log("Kein instance_hash fuer 'Data Only Löschen' "
                         "verfuegbar.")
                return
        # 11.08.2026 (Bugfix Runde 5): Parameter der Variante ermitteln
        # – Grundlage fuer den Legacy-Pool-Purge (Params-only-Hash) im
        # FeatureBuilder – sonst bleiben die Alt-Rows und das Datum
        # setzt nach dem Purge nicht auf 'nie' zurueck.
        if params is None:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset:
                params = preset.get("params") or {}
        label = service_id or f"{plugin_id} (#{instance_hash})"
        reply = QMessageBox.question(
            self, "Data Only Löschen",
            f"Berechnete Feature-Daten der Instanz '{label}' "
            f"(#{instance_hash}) dauerhaft löschen?\n\n"
            "Gelöscht werden ALLE Timeframes (M1-MN1) dieser "
            "Variante. Die Instanz-Konfiguration bleibt erhalten – die Daten werden "
            "beim nächsten Scan neu berechnet.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            from analytics.features.feature_builder import FeatureBuilder
            n = FeatureBuilder().purge_instance_data(
                instance_hash, plugin_id, params,
                purge_legacy=self._purge_legacy_allowed(
                    plugin_id, params))
        except Exception as e:
            self.log(f"FEHLER beim Purgen der Feature-Daten: {e}")
            return
        self.log(f"Feature-Daten gelöscht: {n} Zeilen "
                 f"(Instanz #{instance_hash}, alle Timeframes).")
        self._reset_run_progress()
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_delete_complete(self, set_id: str, service_id: str,
                            plugin_id: str, instance_hash: str) -> None:
        """'Vollständig Löschen' (20.04): Instanz/Preset + Daten entfernen.

        Zwei Sicherheitsabfragen (P14-05-Muster). Betrifft:
        * Service-in-Set: Instanz aus service_sets entfernen + Feature-Daten
          der Variante purgen (Hash aus cfg bzw. Params).
        * Clone/Preset: indicator_presets-Eintrag löschen + Feature-Daten
          purgen (Archiv-Einheit: einzelner Clone – auch archivierte Clones
          sind hierueber endgueltig entfernt).
        """
        if set_id and service_id:
            self._delete_complete_set_instance(set_id, service_id, plugin_id)
        elif plugin_id:
            self._delete_complete_preset(plugin_id, instance_hash)
        else:
            self.log("Vollständig Löschen: keine Ziel-Instanz.")

    def _delete_complete_set_instance(self, set_id: str, service_id: str,
                                      plugin_id: str) -> None:
        """Voll-Loeschung einer Service-Instanz in einem Set."""
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id) or {}
        pid = str(cfg.get("plugin_id") or plugin_id or service_id)
        # P14-04-E: nur der LETZTE Vorkommen eines Indikator-Services gesperrt.
        if self._plugin_belongs_to_indicator(pid):
            others = self._remaining_sets_with_plugin(
                pid, exclude_set_id=set_id)
            if not others:
                QMessageBox.warning(
                    self, "Service gesperrt",
                    f"Der Service '{pid}' ist der letzte in einem "
                    f"gespeicherten Service-Set.\n"
                    f"Für den Indikator muss mindestens ein gültiges Set "
                    f"mit diesem Service erhalten bleiben (P14-04).")
                return
        label = f"{service_id} [{pid}]"
        reply = QMessageBox.question(
            self, "Vollständig Löschen",
            f"Instanz '{label}' vollständig löschen?\n\n"
            "Die Instanz wird aus dem Set entfernt UND die berechneten "
            "Feature-Daten dieser Parameter-Variante werden gelöscht "
            "(ALLE Timeframes M1-MN1).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            f"'{label}' wird dauerhaft entfernt – inkl. aller gespeicherten "
            "Feature-Daten der Variante. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        # 1) Instanz aus dem Set entfernen
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
        # 2) Feature-Daten der Variante purgen
        hash_ = str(cfg.get("instance_hash") or "")
        if not hash_:
            hash_ = generate_instance_hash(pid, cfg.get("params") or {})
        if hash_:
            try:
                from analytics.features.feature_builder import FeatureBuilder
                n = FeatureBuilder().purge_instance_data(
                    hash_, pid, cfg.get("params") or {})
            except Exception as e:
                n = 0
                self.log(f"WARN: Feature-Daten-Purge fehlgeschlagen: {e}")
            self.log(f"Variante #{hash_} purged ({n} Zeilen).")
            self._reset_run_progress()
        self.log(f"Instanz vollständig gelöscht: {label}")
        event_bus.service_set_changed.emit()
        if self._current_set_id == set_id:
            self.load_set_into_editor(definition)

    def _delete_complete_preset(self, plugin_id: str,
                                instance_hash: str) -> None:
        """Voll-Loeschung eines Plugin-Presets/Clones."""
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            self.log(f"Preset zu #{instance_hash} nicht gefunden.")
            return
        preset_name = str(preset.get("preset_name") or "Default")
        indicator_id = str(preset.get("indicator_id") or "")
        reply = QMessageBox.question(
            self, "Vollständig Löschen",
            f"Preset '{preset_name}' von '{plugin_id}' vollständig löschen?"
            f"\n\nDas Preset wird aus indicator_presets entfernt UND die "
            "berechneten Feature-Daten dieser Parameter-Variante werden "
            "gelöscht (ALLE Timeframes M1-MN1).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        reply2 = QMessageBox.question(
            self, "Wirklich?",
            f"'{preset_name}' wird dauerhaft gelöscht – inkl. aller "
            "gespeicherten Feature-Daten der Variante. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply2 != QMessageBox.Yes:
            return
        sm = getattr(self, "_state_manager", None)
        if sm is not None and indicator_id:
            try:
                sm.delete_indicator_preset(indicator_id, preset_name)
            except Exception as e:
                self.log(f"FEHLER beim Löschen des Presets: {e}")
                return
        if instance_hash:
            try:
                from analytics.features.feature_builder import FeatureBuilder
                n = FeatureBuilder().purge_instance_data(
                    instance_hash, plugin_id, preset.get("params") or {},
                    purge_legacy=self._purge_legacy_allowed(
                        plugin_id, preset.get("params") or {}))
            except Exception as e:
                n = 0
                self.log(f"WARN: Feature-Daten-Purge fehlgeschlagen: {e}")
            self.log(f"Variante #{instance_hash} purged ({n} Zeilen).")
            self._reset_run_progress()
        self.log(f"Preset vollständig gelöscht: '{preset_name}'.")
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_doc_log_requested(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Doc Log bearbeiten' (20.04, Q1/Q7).

        Oeffnet den ServiceDescriptionEditDialog fuer das Freitextfeld
        (Negativ-Wissen). Persistenz:
        * Service-in-Set: ServiceInstanceConfig.doc_log (Set-JSON).
        * Clone/Preset: indicator_presets.doc_log.
        """
        try:
            if set_id and service_id:
                model = getattr(self.service_selector, "model", None)
                cfg = model.find_service(set_id, service_id) if model else None
                cfg = cfg or {}
                pid = str(cfg.get("plugin_id") or service_id)
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id=service_id,
                    plugin_id=pid,
                    header_line=self._info_header_tooltip(pid),
                    description=str(cfg.get("doc_log") or ""),
                    title="Doc Log bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda text, s=set_id, i=service_id:
                    self._save_instance_doc_log(s, i, text))
                dlg.exec()
                return
            if plugin_id and instance_hash:
                preset = self._find_preset_for_hash(plugin_id, instance_hash)
                preset_name = str((preset or {}).get("preset_name")
                                  or instance_hash)
                dlg = ServiceDescriptionEditDialog(
                    parent=self,
                    instance_id=preset_name,
                    plugin_id=plugin_id,
                    header_line=self._info_header_tooltip(plugin_id),
                    description=str((preset or {}).get("doc_log") or ""),
                    title="Doc Log bearbeiten",
                )
                dlg.save_requested.connect(
                    lambda text, p=plugin_id, h=instance_hash:
                    self._save_plugin_doc_log(p, h, text))
                dlg.exec()
                return
        except (RuntimeError, AttributeError) as e:
            self.log(f"Doc-Log-Dialog nicht möglich: {e}")

    def _save_instance_doc_log(self, set_id: str, instance_id: str,
                               new_log: str) -> None:
        """Persistiert das Doc-Log einer Service-Instanz (20.04, Q7).

        Ziel: ServiceInstanceConfig.doc_log im Set-JSON (single source of
        truth wie description). Analog _save_instance_description.
        """
        clean = (new_log or "").strip()
        # In der geladenen Definition nachziehen (sofortige Folge-Speicherung)
        if self._current_set_definition is not None:
            cfg = (self._current_set_definition.get("services") or {}).get(
                instance_id)
            if isinstance(cfg, dict):
                cfg["doc_log"] = clean
        if not set_id:
            self.log(f"Doc Log '{instance_id}' aktualisiert "
                     f"(Set noch nicht gespeichert).")
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Doc Log nicht "
                     f"gespeichert.")
            return
        services = definition.get("services") or {}
        if instance_id in services:
            services[instance_id]["doc_log"] = clean
        definition["services"] = services
        try:
            self.set_repo.save_set(definition)
            event_bus.service_set_changed.emit()
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Doc Logs: {e}")
            return
        self._clear_dirty_markers()
        self.log(f"Doc Log '{instance_id}' gespeichert.")

    def _save_plugin_doc_log(self, plugin_id: str, instance_hash: str,
                             new_log: str) -> None:
        """Persistiert das Doc-Log eines Plugin-Presets (20.04, Q7)."""
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            self.log("Doc Log nicht gespeichert (kein StateManager).")
            return
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if not preset or not preset.get("indicator_id"):
            self.log(f"Preset zu #{instance_hash} nicht gefunden.")
            return
        try:
            sm.set_plugin_preset_doc_log(
                preset.get("indicator_id"), preset.get("preset_name"),
                new_log)
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Preset-Doc-Logs: {e}")
            return
        self.log(f"Doc Log '{preset.get('preset_name')}' gespeichert.")
        event_bus.service_set_changed.emit()

    @Slot(str, str, str, str)
    def _on_duplicate_variant(self, set_id: str, service_id: str,
                              plugin_id: str, instance_hash: str) -> None:
        """'Als Variante duplizieren' (20.04, Q8).

        * Service-in-Set: neue Instanz mit kopierten Parametern + neu
          berechnetem instance_hash (neue instance_id via _next_instance_id).
        * Clone/Preset: neues Preset mit kopierten Parametern (Name
          '<Preset> (Kopie)'); aus einem flachen Plugin-Blatt entsteht so
          die erste Variante.
        """
        if set_id and service_id:
            self._duplicate_set_instance(set_id, service_id)
            return
        if plugin_id:
            self._duplicate_preset(plugin_id, instance_hash)
            return
        self.log("Als Variante duplizieren: keine Ziel-Instanz.")

    @Slot(str, str, str)
    def _on_rename_variant(self, plugin_id: str, instance_hash: str,
                           new_name: str) -> None:
        """'Variante umbenennen' (10.08.2026, Bugfix).

        Benennt ein Plugin-Preset (Clone/Variante) in indicator_presets um.
        Kollisionspruefung gegen die UEBRIGEN Presets des Plugins; die
        Feature-Store-Daten (Spalte instance_hash) bleiben unberuehrt
        (der Hash haengt an den Parametern, nicht am Namen).
        """
        preset = self._find_preset_for_hash(plugin_id, instance_hash)
        if preset is None:
            self.log(f"Preset zu #{instance_hash} nicht gefunden – "
                     f"Umbenennen abgebrochen.")
            return
        old_name = str(preset.get("preset_name") or "Default")
        indicator_id = str(preset.get("indicator_id") or "")
        if not indicator_id:
            self.log("Preset hat keine indicator_id – Umbenennen abgebrochen.")
            return
        clean = (new_name or "").strip()
        if not clean or clean == old_name:
            return
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            self.log("Umbenennen nicht moeglich (kein StateManager).")
            return
        try:
            existing = {str(p.get("preset_name") or "")
                        for p in (sm.list_plugin_presets(plugin_id) or [])
                        if isinstance(p, dict)}
        except Exception as e:
            self.log(f"FEHLER beim Laden der Preset-Namen: {e}")
            return
        if clean in existing:
            QMessageBox.warning(
                self, "Name vergeben",
                f"Eine andere Variante von '{plugin_id}' heisst bereits "
                f"'{clean}'.")
            return
        try:
            sm.rename_indicator_preset(indicator_id, old_name, clean)
        except Exception as e:
            self.log(f"FEHLER beim Umbenennen der Variante: {e}")
            return
        self.log(f"Variante '{old_name}' umbenannt zu '{clean}'.")
        event_bus.service_set_changed.emit()

    def _duplicate_set_instance(self, set_id: str, service_id: str) -> None:
        """Dupliziert eine Service-Instanz in ihrem Set (Q8)."""
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets ({set_id}): {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden.")
            return
        services = dict(definition.get("services") or {})
        cfg = services.get(service_id)
        if not isinstance(cfg, dict):
            self.log(f"Instanz '{service_id}' nicht gefunden.")
            return
        pid = str(cfg.get("plugin_id") or service_id)
        iid = self._next_instance_id(services, pid)
        copy = dict(cfg)
        copy["params"] = dict(cfg.get("params") or {})
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
        except Exception as e:
            self.log(f"FEHLER beim Speichern des Sets: {e}")
            return
        self.log(f"Variante '{iid}' dupliziert aus '{service_id}' "
                 f"(#{copy['instance_hash']}).")
        event_bus.service_set_changed.emit()
        # Q8-Bugfix: Ergebnis SICHTBAR machen – das Ziel-Set wird in den
        # Parameter-Editor geladen (neue Service-Spalte der Variante) und
        # die neue Instanz im Baum expandiert/selektiert.
        self.load_set_into_editor(definition)
        tree = getattr(getattr(self, "service_selector", None),
                       "master_tree", None)
        if tree is not None:
            tree.select_instance(set_id, iid)

    def _duplicate_preset(self, plugin_id: str, instance_hash: str) -> None:
        """Dupliziert einen Plugin-Clone als neues Preset (Q8)."""
        sm = getattr(self, "_state_manager", None)
        if sm is None:
            self.log("Variante nicht dupliziert (kein StateManager).")
            return
        if instance_hash:
            preset = self._find_preset_for_hash(plugin_id, instance_hash)
            if preset is None:
                self.log(f"Preset zu #{instance_hash} nicht gefunden.")
                return
            base = str(preset.get("preset_name") or "Default")
            params = dict(preset.get("params") or {})
            indicator_id = str(preset.get("indicator_id") or "")
            version = preset.get("version")
            # Diff 2 (User-Bugreport 09.08.2026): Eine duplizierte Variante
            # ist IMMER batch-aktiv (is_active_batch=True) – NICHT der Status
            # des Quell-Presets. Sonst bliebe eine archivierte/inaktive Kopie
            # unsichtbar: Scans/LiveAnalyzer ignorieren is_active_batch=False
            # und das Analytics-Dropdown zeigt sie erst nach einem Run.
            is_active = True
        else:
            # Flaches Plugin-Blatt: aktuelle Standalone-Parameter
            # (global_settings, Key 'plugin_params_<plugin_id>').
            try:
                raw = sm.get_global_value(f"plugin_params_{plugin_id}", {})
            except Exception:
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            base = "Default"
            params = dict(raw.get("params") or {})
            indicator_id = plugin_id
            version = raw.get("version") or "1.0.0"
            is_active = True
        if not indicator_id:
            indicator_id = plugin_id
        # 10.08.2026 (Bugfix): Beim Anlegen einer neuen Variante MUSS ein
        # neuer Name vergeben werden – kein stummes Auto-Schema
        # ('<base> (Kopie)'). Der Dialog ist mit dem freien Kopiernamen
        # vorbelegt; Kollisionen werden abgefangen.
        suggested = self._next_preset_copy_name(sm, plugin_id, base)
        new_name, ok = QInputDialog.getText(
            self, "Variante anlegen",
            f"Name für die neue Variante (aus '{base}'):", text=suggested)
        new_name = (new_name or "").strip()
        if not ok or not new_name:
            self.log("Variante nicht dupliziert (Name fehlt/abgebrochen).")
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
                is_active_batch=is_active,
                doc_log="",
            )
        except Exception as e:
            self.log(f"FEHLER beim Duplizieren der Variante: {e}")
            return
        # 11.08.2026 (Bugfix Varianten-Kollision): Der Hash der neuen
        # Variante fliesst inkl. des NEUEN Preset-Namens ein (identisch zum
        # ServiceSelectorModel) - sonst kollidieren Params-only-Hashes.
        new_hash = generate_instance_hash(plugin_id, params,
                                          preset_name=new_name)
        self.log(f"Variante '{new_name}' dupliziert aus '{base}' "
                 f"(#{new_hash}).")
        event_bus.service_set_changed.emit()
        # Q8-Bugfix: Ergebnis SICHTBAR machen – den neuen Clone-Knoten im
        # Baum expandieren/selektieren (ohne Editor-Overwrite; der Clone-
        # Tooltip zeigt die kopierten Parameter).
        tree = getattr(getattr(self, "service_selector", None),
                       "master_tree", None)
        if tree is not None:
            tree.select_clone(plugin_id, new_hash)

    def _resolve_info_plugin(self, plugin_id: str):
        """Liefert das Plugin aus der Registry (oder None + Log-Eintrag)."""
        try:
            from analytics.features.feature_builder import PluginRegistry
            return PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden.")
            return None

    def _info_header_tooltip(self, plugin_id: str) -> str:
        """Erste Dialog-Zeile = Badge-Header des Info-Buttons (20.03.02, F5).

        Vereinheitlichtes Format: '📌 im <Indikator> | 🟢 aktiv in
        <Indikator>' bzw. '📌 im <Indikator> | ⚪ inaktiv'. Leer ohne
        Indikator-Zugehoerigkeit.
        """
        model = getattr(self.service_selector, "model", None)
        if model is None or not model.belongs_to_indicator(plugin_id):
            return ""
        name = model.get_indicator_display_name(plugin_id)
        if model.is_active_in_chart(plugin_id):
            return f"📌 im {name} | 🟢 aktiv in {name}"
        return f"📌 im {name} | ⚪ inaktiv"

    def _info_set_tooltip(self, set_def: Dict[str, Any]) -> str:
        """Erste Dialog-Zeile fuer Set-Zeilen (20.03.02, F5).

        Vereinheitlichtes Badge-Format analog _info_header_tooltip; mehrere
        Indikatoren mit ' + ' verknuepft ('📌 im <I1> + <I2> | 🟢 aktiv in
        <I1> + <I2>' bzw. '⚪ inaktiv').
        """
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return ""
        names = model.get_set_indicator_names(set_def or {})
        if not names:
            return ""
        label = " + ".join(names)
        if model.is_set_active(set_def or {}):
            return f"📌 im {label} | 🟢 aktiv in {label}"
        return f"📌 im {label} | ⚪ inaktiv"
