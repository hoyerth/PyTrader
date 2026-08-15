"""
service_selector_dialog_run.py - Run-Worker & Service-Ausfuehrung (Selection-Details, TF-Combo, Run-Log, Progress)

23.08 God-File-Split (15.08.2026): Aus serviceui/service_selector_dialog.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der ServiceSelectorDialog-
Klasse als Mixin (Klasse ServiceSelectorDialogRunMixin).
"""

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from PySide6.QtCore import (
    Slot,
)

from PySide6.QtWidgets import (
    QMessageBox,
)

from serviceui.master_tree import (
    TYPE_CATEGORY,
    TYPE_CLONE,
    TYPE_PLUGIN,
    TYPE_SERVICE,
    TYPE_SET,
)

from serviceui.run_worker import (
    ALL_TIMEFRAMES,
    ServiceRunWorker,
)

from serviceui.service_set_utils import (
    variant_run_entries,
)

class ServiceSelectorDialogRunMixin:

    # ------------------------------------------------------------------
    # Read-Only-Parameter-Panel (Punkte 1-3: horizontal, 2-Spalten-Default,
    # Fensterbreite == rechte Kante der Parameter-Box)
    # ------------------------------------------------------------------
    @Slot()
    def _on_checked_changed(self) -> None:
        """Live-Filter bei Checkbox-Aenderungen im Picker (10.08.2026).

        Ein An-/Abhaken aktualisiert sofort die Datenquellen des
        AnalyticsWindow (selection_ids_requested -> set_feature_ids) -
        dadurch erneuern sich auch die Resultatparameter-Dropdowns
        (heatmap field/agg etc.). Das Read-Only-Panel folgt weiterhin der
        GEKLICKTEN Zeile (Punkte 1-7), nicht den Haken.
        """
        tree = self.selector.master_tree
        if tree is None:
            return
        try:
            ids = list(tree.checked_feature_ids() or [])
            hashes = list(tree.checked_instance_hashes() or [])
        except (RuntimeError, AttributeError):
            return
        self.selection_ids_requested.emit(ids)
        self.selection_hashes_requested.emit(hashes)

    def _on_tree_selection_details(self, node_type: str, set_id: str,
                                   service_id: str, plugin_id: str) -> None:
        """Slot fuer `MasterTree.selection_details` (Mausklick in einer Zeile).

        Bugfix-Runde 3 (06.08.2026, Punkte 1-7): Das Panel folgt der
        GEKLICKTEN Zeile, NICHT den Checkboxen (analog service_win
        `_on_master_selection`):

          * Set-Zeile ODER Service-Zeile IN einem Set -> ALLE Services des
            Sets nebeneinander (`_entries_for_scope`, Punkt 4+5).
          * Plugin-Zeile (⚡ Standalone / 📦 Plugins) -> NUR dieser eine
            Service (Punkt 6).
          * Kategorie-Ordner (18.01.01, E-4) -> ALLE Elemente des Pfads
            (rekursiv). 18.01.03 (L3): Sets-Ordner (set_id == 'sets')
            liefern die Service-Spalten aller Sets unter dem Pfad,
            Plugins-Ordner die Plugin-Spalten (category_plugin_ids).
          * Gruppen-/sonstige Zeilen -> KEIN Service (Punkt 7).

        10.08.2026 (Bugfix, Punkt 1+2): Der LIVE-FILTER folgt
        AUSSCHLIESSLICH den Checkboxen (`checked_changed` ->
        `_on_checked_changed` -> `selection_ids_requested` mit
        `checked_feature_ids()`) - der Zeilen-Klick steuert NUR das Panel.
        Vorher emittierte dieser Handler beim Klick zusaetzlich
        `selection_ids_requested` mit dem Zeilen-Scope und ueberschrieb
        damit den angehakten Filter (feature_ids der Historie/des Profils
        entsprach dem letzten Klick statt den Haken; die
        Ergebnisparameter-Dropdowns folgten dem Klick statt den Haken).
        Standalone-Services (belongs_to_indicator == False) sind editierbar
        (plugin_params_<id>), alle anderen Zeilen bleiben read-only.
        """
        self._last_scope = (node_type, set_id, service_id, plugin_id)
        # 10.08.2026 (Bugfix, Punkt 1+2): KEIN selection_ids_requested mehr -
        # der Filter folgt den Checkboxen (checked_changed), nicht dem Klick.
        # Ein Klick darf den angehakten Filter nicht ueberschreiben (sonst
        # speichern Historie/Profil den letzten Klick statt der Haken).
        editable = None
        if node_type in (TYPE_PLUGIN, TYPE_CLONE) and plugin_id:
            if not self.model.belongs_to_indicator(str(plugin_id)):
                editable = str(plugin_id)
        self._rebuild_param_panel(
            self._entries_for_scope(node_type, set_id, service_id, plugin_id),
            editable_plugin=editable)
        # 21.01b: Pill-Strip dem geklickten Service nachziehen.
        pid_badge, hash_badge = self._resolve_badge_scope(
            node_type, set_id, service_id, plugin_id)
        self._refresh_badge_bar(pid_badge, hash_badge)

    def _resolve_selection_ids(self, node_type: str, set_id: str,
                               service_id: str, plugin_id: str) -> List[str]:
        """Loest eine geklickte Baum-Zeile in feature_ids (plugin_ids) auf.

        18.01.01 (E-4): Klick auf Set -> alle Services des Sets; Klick auf
        Kategorie-Ordner -> rekursive Aufloesung; Klick auf Plugin-Zeile ->
        [plugin_id]; Service-Zeile -> [plugin_id des Service]. 18.01.03
        (L3): Fuer Kategorie-Ordner traegt set_id die Eltern-GRUPPE
        ('sets'/'plugins', aus MasterTree._emit_selection_details) – die
        Aufloesung unterscheidet damit Sets-Ordner (Sets unter dem Pfad ->
        deren Service-plugin_ids) von Plugins-Ordnern (category_plugin_ids).
        """
        if node_type == TYPE_CATEGORY:
            return self.model.category_service_plugin_ids(
                set_id or "", plugin_id or "")
        if node_type in (TYPE_PLUGIN, TYPE_CLONE) and plugin_id:
            # 20.04 (Q7): Clone-Zeilen loesen auf die plugin_id des
            # Plugin-Parents auf (Filter bleibt feature_id IN (plugin_ids)).
            return [str(plugin_id)]
        if node_type == TYPE_SERVICE and set_id and service_id:
            cfg = self.model.find_service(set_id, service_id) or {}
            pid = str(cfg.get("plugin_id") or service_id)
            return [pid] if pid else []
        if node_type == TYPE_SET and set_id:
            definition = self.model.find_set(set_id) or {}
            services = definition.get("services") or {}
            order = definition.get("execution_order") or list(services.keys())
            ids: List[str] = []
            for iid in order:
                cfg = services.get(iid) or {}
                pid = str(cfg.get("plugin_id") or iid)
                if pid and pid not in ids:
                    ids.append(pid)
            return ids
        return []

    # ------------------------------------------------------------------
    # 21.01b (11.08.2026): Run im Picker (TF-Zeile + Pill-Strip)
    # ------------------------------------------------------------------
    def _run_symbol(self) -> str:
        """Aktives Symbol aus dem Parent (AnalyticsWindow.combo_symbol)."""
        parent = self.parent()
        cb = getattr(parent, "combo_symbol", None)
        if cb is not None:
            try:
                txt = cb.currentText()
            except Exception:
                txt = ""
            if txt:
                return str(txt)
        return "SILVER"

    def _run_timeframe(self) -> str:
        """Gewaehlter Run-Timeframe (Sentinel = Multi-TF im Worker)."""
        combo = getattr(self, "combo_run_tf", None)
        if combo is None:
            return ALL_TIMEFRAMES
        return str(combo.currentText() or ALL_TIMEFRAMES)

    def _fill_run_tf_combo(self) -> None:
        """Befuellt combo_run_tf: Sentinel 'ALLE Timeframes' + alle TFs
        aufsteigend nach Dauer (M1..MN1, wie combo_tf im ServiceWindow)."""
        combo = getattr(self, "combo_run_tf", None)
        if combo is None:
            return
        try:
            from db_service import TF_SECONDS_MAP, get_timeframes
            try:
                tfs = list(get_timeframes().keys())
            except Exception:
                tfs = list(TF_SECONDS_MAP.keys())
            sort_map = TF_SECONDS_MAP
        except Exception:
            tfs = ["M1", "M2", "M5", "M10", "M15", "M30",
                   "H1", "H4", "D1", "W1", "MN1"]
            sort_map = {}
        tfs = sorted(tfs, key=lambda tf: sort_map.get(tf, 10 ** 12))
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(ALL_TIMEFRAMES)
        for tf in tfs:
            if tf != ALL_TIMEFRAMES:
                combo.addItem(tf)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _plugin_config(self, plugin_id: str) -> Dict[str, Any]:
        """Standalone-Plugin-Config wie im ServiceWindow (17.01.04-Muster).
        Basis sind die Registry-Defaults; gespeicherte Werte aus
        global_settings (Key 'plugin_params_<pid>') ueberschreiben."""
        try:
            from analytics.features.feature_builder import PluginRegistry
            plugin = PluginRegistry().get(plugin_id)
        except KeyError:
            plugin = None
        params = dict(getattr(plugin, "default_params", None) or {}) \
            if plugin else {}
        lookback: int = 1000
        if "lookback" in params:
            try:
                lookback = int(params.pop("lookback") or 1000)
            except (TypeError, ValueError):
                lookback = 1000
        cfg: Dict[str, Any] = {
            "plugin_id": plugin_id,
            "lookback": lookback,
            "params": params,
            "version": getattr(plugin, "version", "0.0.0") or "0.0.0",
        }
        try:
            saved = self._state_manager.get_global_value(
                f"plugin_params_{plugin_id}", None)
        except Exception:
            saved = None
        if isinstance(saved, dict):
            lb = saved.get("lookback")
            if lb is not None:
                try:
                    cfg["lookback"] = int(lb)
                except (TypeError, ValueError):
                    pass
            saved_params = saved.get("params")
            if isinstance(saved_params, dict):
                merged = dict(cfg["params"])
                merged.update(saved_params)
                cfg["params"] = merged
        return cfg

    def _start_run_worker(self, scope_id: str, set_definition: Dict[str, Any],
                          instance_id: Optional[str]) -> None:
        """Startet den gezielten ServiceRunWorker (Single/Set) mit dem
        Timeframe aus combo_run_tf – Muster service_win._start_run_worker."""
        if self._run_worker is not None and self._run_worker.isRunning():
            QMessageBox.information(
                self, "Service-Ausführung",
                "Eine Service-Ausführung läuft bereits.")
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        self._run_worker = ServiceRunWorker(
            self.set_evaluator, symbol, timeframe, set_definition,
            instance_id=instance_id, parent=self,
        )
        self._run_worker.log_message.connect(self._on_run_log)
        self._run_worker.run_finished.connect(self._on_run_worker_finished)
        self._run_worker.run_failed.connect(self._on_run_worker_failed)
        # 21.01b: Per-TF-Signale -> Pill-Strip (Laufzeit-/Fehler-Zustand).
        self._run_worker.tf_started.connect(self._on_tf_started)
        self._run_worker.tf_finished.connect(self._on_tf_finished)
        # 12.08.2026 (User-Meldung 2): Per-Service-Fortschritt -> Progress-Bar.
        self._run_worker.service_progress.connect(self._on_service_progress)
        self._reset_run_progress("Starte Ausfuehrung ...")
        self._run_worker.start()

    def _on_run_log(self, message: str) -> None:
        try:
            print(f"[ServicePicker] {message}")
        except Exception:
            pass

    def _merge_live_param_values(self, definition: Dict[str, Any]) -> None:
        """13.08.2026 (Punkt 7, F7): Implizites Uebernehmen der Parameterbox.

        Der Picker-Run nutzt sonst die GESPEICHERTE Set-/Plugin-Definition
        (set_repo.get_set / variant_run_entries + _plugin_config). Wurden
        in der Parameterbox Werte geaendert, ohne zu speichern (inkl.
        Modus), gingen sie bei der Ausfuehrung verloren - Wurzel von Bug 4
        (MA_Slope_Change landete nie im Store, weil der Run mit
        default_params -> erstem Mode-Eintrag lief). Hier werden die LIVE-
        Control-Werte der aktuellen Parameterbox in die Run-Definition
        uebernommen (nur fuer DIESEN Run, keine Persistenz).

        Match: exakte instance_id (Set-Service/Standalone ohne Presets);
        bei Clone-Runs (instance_id = '<pid>#<hash>') zusaetzlich per
        plugin_id, sofern in der Definition genau EIN Service matcht
        (mehrere Varianten = mehrdeutig, dann keine Uebernahme).
        """
        host = getattr(self, "_param_host", None)
        if host is None:
            return
        controls = getattr(host, "_service_param_controls", None) or {}
        if not controls:
            return
        services = definition.get("services") or {}
        for (iid, key), ctrl in controls.items():
            cfg = services.get(iid)
            if not isinstance(cfg, dict):
                matches = [c for c in services.values()
                           if isinstance(c, dict)
                           and str(c.get("plugin_id") or "") == str(iid)]
                if len(matches) == 1:
                    cfg = matches[0]
                else:
                    continue
            try:
                value = host._ctrl_value(ctrl)
            except (RuntimeError, AttributeError):
                continue
            if key == "lookback":
                try:
                    cfg["lookback"] = int(value)
                except (TypeError, ValueError):
                    pass
            else:
                cfg.setdefault("params", {})[key] = value

    def _on_run_service(self, set_id: str, service_id: str) -> None:
        """'▶️ Diesen Service ausführen' (Picker-MasterTree)."""
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            QMessageBox.warning(
                self, "Service ausführen",
                f"Set '{set_id}' nicht gefunden.")
            return
        if service_id not in (definition.get("services") or {}):
            QMessageBox.warning(
                self, "Service ausführen",
                f"Service '{service_id}' nicht im Set '{set_id}'.")
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        set_name = str(definition.get("display_name") or set_id)
        reply = QMessageBox.question(
            self, "Service ausführen",
            f"Service '{service_id}' aus dem Set '{set_name}' ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Der erzeugte Feature-Store-Payload wird in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        # 13.08.2026 (Punkt 7, F7): Implizites Uebernehmen der Parameterbox-
        # Werte (inkl. Modus) vor der Ausfuehrung - sonst liefe der Run mit
        # der GESPEICHERTEN Definition (Aenderungen ohne Speichern gehen
        # verloren).
        self._merge_live_param_values(definition)
        self._start_run_worker(service_id, definition, instance_id=service_id)

    def _on_run_set(self, set_id: str) -> None:
        """'▶️ Alle Services ausführen' (Picker-MasterTree)."""
        if not set_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", str(e))
            return
        if not definition:
            QMessageBox.warning(
                self, "Set ausführen", f"Set '{set_id}' nicht gefunden.")
            return
        if not definition.get("execution_order"):
            QMessageBox.information(
                self, "Set ausführen", f"Set '{set_id}' hat keine Services.")
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        set_name = str(definition.get("display_name") or set_id)
        count = len(definition.get("execution_order") or [])
        reply = QMessageBox.question(
            self, "Set ausführen",
            f"Alle Services ({count}) des Sets '{set_name}' ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Die erzeugten Feature-Store-Payloads werden in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        # 13.08.2026 (Punkt 7, F7): Parameterbox-Werte implizit uebernehmen
        # (sichtbare Set-Service-Spalten), bevor das ganze Set laeuft.
        self._merge_live_param_values(definition)
        self._start_run_worker(set_id, definition, instance_id=None)

    def _on_run_plugin(self, plugin_id: str, instance_hash: str = "") -> None:
        """'▶️ Diesen Service ausführen' (Plugin-/Clone-Zeile).

        11.08.2026 (Bugfixing, Varianten-Run): `instance_hash` wird vom
        MasterTree-Kontextmenue mitgeliefert – Clone-Zeilen laufen NUR mit
        den Parametern + Hash der Variante; Plugin-Zeilen mit Presets
        laufen ALLE aktiven Varianten (Bug 1/2/3).
        """
        if not plugin_id:
            return
        sm = getattr(self, "_state_manager", None)
        entries = variant_run_entries(plugin_id, sm, self._plugin_config)
        if not entries:
            return
        if instance_hash:
            entries = [e for e in entries
                       if e[1].get("instance_hash") == instance_hash]
            if not entries:
                entries = [(plugin_id, self._plugin_config(plugin_id))]
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        single = len(entries) == 1
        if single:
            _iid, _cfg = entries[0]
            _name = str(_cfg.get("preset_name") or plugin_id)
            title = "Service ausführen"
            text = (f"Service '{plugin_id}' (Variante '{_name}') ausführen?\n\n"
                    f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                    f"Der erzeugte Feature-Store-Payload wird in analytics.duckdb "
                    f"geschrieben.")
        else:
            title = "Alle Varianten ausführen"
            text = (f"Alle Varianten ({len(entries)}) von '{plugin_id}' "
                    f"ausführen?\n\n"
                    f"Symbol: {symbol}   Timeframe: {timeframe}\n"
                    f"Die erzeugten Feature-Store-Payloads werden in "
                    f"analytics.duckdb geschrieben.")
        reply = QMessageBox.question(
            self, title, text, QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        definition = {
            "set_id": f"plugin_{plugin_id}",
            "display_name": plugin_id,
            "execution_order": [e[0] for e in entries],
            "services": {e[0]: e[1] for e in entries},
        }
        # 13.08.2026 (Punkt 7, F7): Parameterbox-Werte implizit uebernehmen
        # (inkl. Modus - Bug 4: der Run nutzte sonst default_params und
        # lief immer mit dem ersten Mode-Eintrag).
        self._merge_live_param_values(definition)
        self._start_run_worker(
            plugin_id, definition,
            instance_id=entries[0][0] if single else None)

    def _on_run_category(self, group: str, category_path: str) -> None:
        """'▶️ Alle Services ausführen' (Kategorie-Ordner, rekursiv)."""
        if not category_path:
            return
        model = getattr(self, "model", None)
        if model is None:
            return
        plugin_ids = model.category_service_plugin_ids(group, category_path)
        if not plugin_ids:
            QMessageBox.information(
                self, "Alle Services ausführen",
                f"Kategorie '{category_path}' hat keine Services.")
            return
        # 11.08.2026 (Bugfixing, Bug 3): Plugins MIT Presets -> ALLE aktiven
        # Varianten werden ausgefuehrt (jede mit eigenen Parametern + Hash).
        sm = getattr(self, "_state_manager", None)
        entries_all: List[tuple] = []
        for pid in plugin_ids:
            entries_all.extend(variant_run_entries(pid, sm, self._plugin_config))
        if not entries_all:
            return
        symbol = self._run_symbol()
        timeframe = self._run_timeframe()
        count = len(entries_all)
        reply = QMessageBox.question(
            self, "Alle Services ausführen",
            f"Alle Services ({count}) der Kategorie '{category_path}' "
            f"ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Die erzeugten Feature-Store-Payloads werden in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        definition = {
            "set_id": f"category_{category_path}",
            "display_name": category_path,
            "execution_order": [e[0] for e in entries_all],
            "services": {e[0]: e[1] for e in entries_all},
        }
        self._start_run_worker(category_path, definition, instance_id=None)

    def _on_run_worker_finished(self, scope_id: str, stored: int) -> None:
        """Run abgeschlossen: Pill-Strip zuruecksetzen + Status neu laden."""
        self._on_run_log(f"Ausführung abgeschlossen: {stored} Feature-Row(s) "
                         f"im feature_store gespeichert ({scope_id}).")
        self._reset_run_progress()
        self.badge_bar.set_running(None)
        self._refresh_badge_bar()

    def _on_run_worker_failed(self, scope_id: str, error: str) -> None:
        """Run fehlgeschlagen: Pill-Strip zuruecksetzen + Status neu laden."""
        self._on_run_log(f"FEHLER bei Ausführung ({scope_id}): {error}")
        self._reset_run_progress()
        self.badge_bar.set_running(None)
        self._refresh_badge_bar()

    @Slot(str, str, int, int)
    def _on_service_progress(self, tf: str, iid: str, done: int,
                             total: int) -> None:
        """12.08.2026 (User-Meldung 2): Per-Service-Fortschritt anzeigen."""
        bar = getattr(self, "progress_bar", None)
        if bar is not None:
            bar.setMaximum(max(total, 1))
            bar.setValue(done)
        lbl = getattr(self, "progress_label", None)
        if lbl is not None:
            lbl.setText(f"{tf}: {iid} ({done}/{total})")

    def _reset_run_progress(self, label: str = "") -> None:
        """Setzt den Fortschrittsbalken zurueck (Default: leeres Label)."""
        bar = getattr(self, "progress_bar", None)
        if bar is not None:
            # 12.08.2026: setMaximum(0) waere eine endlose Busy-Animation
            # (indeterminate) - determinate leere Range (0..1) verwenden.
            bar.setRange(0, 1)
            bar.setValue(0)
        lbl = getattr(self, "progress_label", None)
        if lbl is not None:
            lbl.setText(label)
