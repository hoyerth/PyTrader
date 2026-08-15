"""
serviceui/service_win_run.py - Service-Ausfuehrung (Run-Worker, Sync-Guard, Fortschritt, TF-Status, Badges, Full-Sync)

23.04 God-File-Split (15.08.2026): Aus serviceui/service_win.py extrahiert,
KEINE Logik-Aenderung. Enthaelt die Methoden der ServiceWindow
als Mixin (Klasse ServiceRunMixin).
"""

from typing import (
    Any,
    Dict,
    Optional,
    Tuple,
)

from PySide6.QtCore import (
    Slot,
)

from PySide6.QtWidgets import (
    QMessageBox,
)

from analytics.engine.service_models import (
    generate_instance_hash,
)

from serviceui.service_set_utils import (
    variant_run_entries,
)

from serviceui.run_worker import (
    ServiceRunWorker,
)

from analytics.engine.feature_store_reader import (
    FeatureStoreReader,
)

from config.event_bus import (
    event_bus,
)

# P15-Bugfix: shiboken6.isValid() schuetzt vor dem Zugriff auf bereits
# C++-seitig zerstoerte Qt-Objekte (Access Violation 0xC0000005 bei wildem
# Klicken, wenn z.B. Controls per deleteLater entfernt werden).
try:
    from shiboken6 import isValid as _qt_valid
except ImportError:  # pragma: no cover
    def _qt_valid(obj) -> bool:  # type: ignore
        return obj is not None

class ServiceRunMixin:

    def _begin_sync_guard(self) -> None:
        """Blockt den 45s-Hintergrund-Sync (sync_timer in main.py).

        Erhoeht den Referenzzaehler und emittiert `service_run_started`
        ausschliesslich beim Uebergang 0→1 – mehrere parallele Runs
        (ServiceRunWorker) pausieren den Sync nur EINMAL.
        """
        self._sync_guard_count += 1
        if self._sync_guard_count == 1:
            try:
                event_bus.service_run_started.emit()
            except (RuntimeError, AttributeError):
                pass

    def _end_sync_guard(self) -> None:
        """Gibt den 45s-Hintergrund-Sync wieder frei.

        Senkt den Referenzzaehler; erst beim Uebergang 1→0 (alle
        Service-Berechnungen abgeschlossen) wird `service_run_finished`
        emittiert und der Sync-Timer im MainWindow wieder gestartet.
        """
        if self._sync_guard_count <= 0:
            return
        self._sync_guard_count -= 1
        if self._sync_guard_count == 0:
            try:
                event_bus.service_run_finished.emit()
            except (RuntimeError, AttributeError):
                pass

    # -------------------------------------------------------------------------
    # 05.08.2026: Gezielte Kontextmenue-Ausfuehrung (Service(s) ausfuehren)
    # -------------------------------------------------------------------------

    def _start_run_worker(self, scope_id: str, set_definition: Dict[str, Any],
                          instance_id: Optional[str]) -> None:
        """Startet den gezielten ServiceRunWorker (Single/Set) im Hintergrund.

        * Laedt OHLCV nur fuer das aktive Symbol + den gewaehlten Timeframe
          (FeatureBuilder.load_ohlcv) – KEIN globaler Massen-Scan.
        * Fuehrt die Pipeline via ServiceSetEvaluator.execute_set() aus und
          persistiert die erzeugten feature_store_payloads ZWINGEND in
          analytics.duckdb (feature_store, FeatureBuilder.store_plugin_payload).
        * Der Worker emittiert nach Abschluss `event_bus.service_set_changed`
          – alle ServiceSelectorModel-Instanzen (MasterTree, Analytics, ...)
          aktualisieren dadurch live das Ausfuehrungsdatum '(DD.MM.JJ)'.
        """
        if self._run_worker and self._run_worker.isRunning():
            self.log("Service-Ausführung läuft bereits.")
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E (05.08.2026): Timeframe-Control der Filterleiste (combo_tf) –
        # 'ALLE Timeframes' startet die Multi-TF-Ausfuehrung im Worker.
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        self._run_worker = ServiceRunWorker(
            self.set_evaluator, symbol, timeframe, set_definition,
            instance_id=instance_id, parent=self,
        )
        self._run_worker.log_message.connect(self.log)
        self._run_worker.run_finished.connect(self._on_run_worker_finished)
        self._run_worker.run_failed.connect(self._on_run_worker_failed)
        # 12.08.2026 (User-Meldung 2): Per-Service-Fortschrittsbalken.
        self._run_worker.service_progress.connect(self._on_service_progress)
        # 21.01b: Per-TF-Signale -> Pill-Strip (Laufzeit-/Fehler-Zustand).
        self._run_worker.tf_started.connect(self._on_tf_started)
        self._run_worker.tf_finished.connect(self._on_tf_finished)
        # 12.08.2026: Progress-Reset beim Start (Busy-Modus).
        self._reset_run_progress("Starte Ausführung ...")
        # Phase 16: 45s-Hintergrund-Sync pausieren, solange der Run laeuft.
        self._begin_sync_guard()
        self._run_worker.start()

    @Slot(str, str)
    def _on_run_service(self, set_id: str, service_id: str) -> None:
        """'▶️ Diesen Service ausführen' (MasterTree-Kontextmenue).

        Sicherheitsabfrage mit Set-/Service-Name und dem aktuell gewaehlten
        Symbol/Timeframe, danach gezielter Single-Run (inkl. Upstream-
        Abhaengigkeiten im Set, damit z.B. srv_proximity seine Linien hat).
        """
        if not set_id or not service_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Ausführung abgebrochen.")
            return
        if service_id not in (definition.get("services") or {}):
            self.log(f"Service '{service_id}' nicht im Set '{set_id}'.")
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Zeitachsen-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
        set_name = str(definition.get("display_name") or set_id)
        reply = QMessageBox.question(
            self, "Service ausführen",
            f"Service '{service_id}' aus dem Set '{set_name}' ausführen?\n\n"
            f"Symbol: {symbol}   Timeframe: {timeframe}\n"
            f"Der erzeugte Feature-Store-Payload wird in analytics.duckdb "
            f"geschrieben.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            self.log("Ausführung abgebrochen.")
            return
        self._start_run_worker(service_id, definition, instance_id=service_id)

    @Slot(str)
    def _on_run_set(self, set_id: str) -> None:
        """'▶️ Alle Services ausführen' (MasterTree-Kontextmenue).

        Sicherheitsabfrage mit Set-Name und dem aktuell gewaehlten
        Symbol/Timeframe, danach gezielter Set-Run (nur dieses Set).
        """
        if not set_id:
            return
        try:
            definition = self.set_repo.get_set(set_id)
        except Exception as e:
            self.log(f"FEHLER beim Laden des Sets: {e}")
            return
        if not definition:
            self.log(f"Set '{set_id}' nicht gefunden – Ausführung abgebrochen.")
            return
        if not definition.get("execution_order"):
            self.log(f"Set '{set_id}' hat keine Services – Ausführung abgebrochen.")
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Zeitachsen-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
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
            self.log("Ausführung abgebrochen.")
            return
        self._start_run_worker(set_id, definition, instance_id=None)

    @Slot(str, str)
    def _on_run_plugin(self, plugin_id: str, instance_hash: str = "") -> None:
        """'▶️ Diesen Service ausführen' (Plugin-/Clone-Zeile unter 📦 Services).

        17.01.02 (Bugfix-Runde): Einzel-Services ausserhalb von Sets (z.B.
        unter Kategorie-Ordnern) erhalten dieselbe Run-Aktion wie die
        Service-Zeilen der Sets. Sicherheitsabfrage mit Plugin-Name und dem
        aktuell gewaehlten Symbol/Timeframe, danach gezielter Single-Run via
        ServiceRunWorker mit einer Ad-hoc-Mini-Definition (nur dieser
        Service; prepare_worker_definition loest ggf. dependencies auf).

        11.08.2026 (Bugfixing, Varianten-Run): `instance_hash` wird vom
        MasterTree-Kontextmenue mitgeliefert:
          * Clone-Zeile  -> hash der Variante: NUR diese Variante laeuft mit
                            ihren EIGENEN Parametern + Hash (Datum im Baum
                            aktualisiert sich an der Variante, Bug 1).
          * Plugin-Zeile -> leer: mit Presets laufen ALLE aktiven Varianten,
                            sonst Basis-Parameter (Bestandsverhalten).
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
                # Variante nicht (mehr) vorhanden -> Basis-Fallback.
                entries = [(plugin_id, self._plugin_config(plugin_id))]
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Timeframe-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
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
            self.log("Ausführung abgebrochen.")
            return
        definition = {
            "set_id": f"plugin_{plugin_id}",
            "display_name": plugin_id,
            "execution_order": [e[0] for e in entries],
            "services": {e[0]: e[1] for e in entries},
        }
        self._start_run_worker(
            plugin_id, definition,
            instance_id=entries[0][0] if single else None)

    @Slot(str, str)
    def _on_run_category(self, group: str, category_path: str) -> None:
        """▶️ Alle Services ausführen (Kategorie-Ordner).

        17.01.02 (Bugfix-Runde): Ordner-Knoten erhalten dieselbe Run-Aktion
        wie die Sets. Es werden ALLE Services unter dem Ordner ausgefuehrt
        (rekursiv, inkl. Unter-Ordner). 18.01.03 (L3): `group` unterscheidet
        Sets-Ordner ('sets' – alle Service-plugin_ids der Sets unter dem
        Pfad, rekursiv) von Plugins-Ordnern ('plugins' – via
        ServiceSelectorModel.category_plugin_ids). Sicherheitsabfrage mit
        Kategorie-Name und dem aktuell gewaehlten Symbol/Timeframe, danach
        gezielter Set-Run mit einer Ad-hoc-Definition.
        """
        if not category_path:
            return
        model = getattr(self.service_selector, "model", None)
        if model is None:
            return
        plugin_ids = model.category_service_plugin_ids(group, category_path)

        if not plugin_ids:
            self.log(f"Kategorie '{category_path}' hat keine Services – "
                     f"Ausführung abgebrochen.")
            return
        # 11.08.2026 (Bugfixing, Bug 3): Plugins MIT Presets werden zu ALLEN
        # aktiven Varianten expandiert (jede mit eigenen Parametern + Hash),
        # damit 'Alle Services ausführen' auch die Varianten ausfuehrt.
        sm = getattr(self, "_state_manager", None)
        entries_all: List[tuple] = []
        for pid in plugin_ids:
            entries_all.extend(variant_run_entries(pid, sm, self._plugin_config))
        if not entries_all:
            return
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        # U15-E: Timeframe-Control der Filterleiste (combo_tf) – kann auch
        # 'ALLE Timeframes' sein (Multi-TF-Ausfuehrung im Worker).
        timeframe = self.combo_tf.currentText() if self.combo_tf else "H1"
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
            self.log("Ausführung abgebrochen.")
            return
        definition = {
            "set_id": f"category_{category_path}",
            "display_name": category_path,
            "execution_order": [e[0] for e in entries_all],
            # 17.01.04: Gespeicherte Plugin-Parameter je Service verwenden
            # (falls vorhanden), sonst Registry-Defaults. Varianten tragen
            # Preset-Parameter + instance_hash.
            "services": {e[0]: e[1] for e in entries_all},
        }
        self._start_run_worker(category_path, definition, instance_id=None)

    @Slot(str, int)
    def _on_run_worker_finished(self, scope_id: str, stored: int) -> None:
        """Loggt den Abschluss des gezielten Runs (FeatureStore-Persistenz).

        Der EventBus-Sync erfolgt bereits im Worker (service_set_changed) –
        das ServiceSelectorModel hat dadurch das neue MAX(created_at) gelesen
        und der MasterTree zeigt das Datum '(DD.MM.JJ)' live an.
        """
        # Phase 16: 45s-Hintergrund-Sync wieder freigeben.
        self._end_sync_guard()
        self._reset_run_progress()
        self.log(f"Ausführung abgeschlossen: {stored} Feature-Row(s) im "
                 f"feature_store gespeichert ({scope_id}).")
        # 21.01b: Pill-Strip nach dem Run neu laden (neue Counts/last_run).
        bar = getattr(self, "badge_bar", None)
        if bar is not None:
            bar.set_running(None)
        self._refresh_badge_bar()

    @Slot(str, str)
    def _on_run_worker_failed(self, scope_id: str, error: str) -> None:
        # Phase 16: 45s-Hintergrund-Sync auch bei Fehler freigeben.
        self._end_sync_guard()
        self._reset_run_progress()
        self.log(f"FEHLER bei Ausführung ({scope_id}): {error}")
        # 21.01b: Pill-Strip nach Fehler zuruecksetzen + Status neu laden.
        bar = getattr(self, "badge_bar", None)
        if bar is not None:
            bar.set_running(None)
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

    # -------------------------------------------------------------------------
    # 21.01b (11.08.2026): TF-Status-Pills (Pill-Strip)
    # -------------------------------------------------------------------------
    def _on_tf_started(self, tf: str) -> None:
        """Hebt den gerade laufenden Timeframe im Pill-Strip blau hervor."""
        bar = getattr(self, "badge_bar", None)
        if bar is None:
            return
        bar.set_running(tf)
        bar.clear_error(tf)

    def _on_tf_finished(self, tf: str, stored: int, had_data: bool) -> None:
        """TF fertig: ohne OHLCV-Daten/Fehler rot markieren, sonst neutral."""
        bar = getattr(self, "badge_bar", None)
        if bar is None:
            return
        if had_data:
            bar.clear_error(tf)
        else:
            bar.set_error(tf)
        bar.set_running(None)

    def _resolve_badge_scope(self, node_type: str, set_id: str,
                             service_id: str,
                             plugin_id: str) -> Tuple[Optional[str],
                                                      Optional[str]]:
        """Ermittelt (plugin_id, instance_hash) fuer den Pill-Strip.

        12.08.2026 (User-Meldung 'Data only loeschen'): Der Pill-Strip wird
        VARIANTEN-GENAU geladen. Clone-Knoten tragen den instance_hash im
        service_id-Slot (MasterTree._emit_selection_details, 20.04 Q7);
        Set-/Service-Zeilen liefern den Hash der ersten Instanz aus der
        Set-Definition (cfg['instance_hash'], sonst Params-only-Hash).
        """
        if plugin_id:
            h = str(service_id) if node_type == "clone" else None
            return str(plugin_id), (h or None)
        if set_id:
            try:
                definition = self.set_repo.get_set(set_id)
            except Exception:
                definition = None
            if definition:
                order = list(definition.get("execution_order") or [])
                services = dict(definition.get("services") or {})
                for iid in order:
                    cfg = services.get(iid) or {}
                    pid = str(cfg.get("plugin_id") or iid)
                    if pid:
                        h = str(cfg.get("instance_hash") or "") or None
                        if not h:
                            try:
                                h = generate_instance_hash(
                                    pid, cfg.get("params") or {})
                            except Exception:
                                h = None
                        return pid, h
        return (str(service_id) if service_id else None), None

    # -------------------------------------------------------------------------
    # Phase 21.03.22: Full Market-Data Sync Button (alle Paare aktualisieren)
    # -------------------------------------------------------------------------

    @Slot()
    def _on_sync_all_market_clicked(self) -> None:
        """Startet den Full-Sync aller in market_data.duckdb vorhandenen Symbol:TF-Paare."""
        _worker = getattr(self, "_sync_worker", None)
        if _worker is not None and _qt_valid(_worker) and _worker.isRunning():
            return

        from repositories.market_data_repository import MarketDataRepository
        all_pairs = MarketDataRepository().get_all_stored_symbol_tf_pairs()

        if not all_pairs:
            return

        # 45s-Auto-Sync pausieren via Concurrency-Guard (EventBus, IoC)
        from config.event_bus import event_bus
        event_bus.service_run_started.emit()

        self.btn_sync_all_market.setEnabled(False)
        self.btn_sync_all_market.setText("⏳ Sync läuft...")

        from workers.data_sync_worker import DataSyncWorker
        self._sync_worker = DataSyncWorker(pairs=all_pairs, parent=self)
        self._sync_worker.sync_completed.connect(self._on_sync_all_completed)
        self._sync_worker.finished.connect(self._sync_worker.deleteLater)
        self._sync_worker.start()

    @Slot(set)
    def _on_sync_all_completed(self, updated_pairs: set) -> None:
        """Nach Abschluss des Full-Syncs: Auto-Sync fortsetzen & UI refreshen."""
        from config.event_bus import event_bus
        event_bus.service_run_finished.emit()

        self.btn_sync_all_market.setEnabled(True)
        self.btn_sync_all_market.setText("🔄 Sync Alle Daten")

        self._refresh_badge_bar()
        if hasattr(self, "service_selector"):
            self.service_selector.refresh()
        # Nach deleteLater (finished-Signal) keine stale C++-Referenz halten.
        self._sync_worker = None

    def _refresh_badge_bar(self, plugin_id: Optional[str] = None,
                           instance_hash: Optional[str] = None) -> None:
        """Laedt die TF-Status-Pills fuer den angegebenen Service neu.

        Quelle: FeatureStoreReader.fetch_service_tf_status() – je Timeframe
        die Anzahl der feature_store-Eintraege und der letzte Lauf.

        12.08.2026 (User-Meldung 'Data only loeschen'): Mit `instance_hash`
        wird der Pill-Strip VARIANTEN-GENAU geladen (nur die TFs dieser
        Variante); ohne Hash bleibt das service-weite Verhalten erhalten.
        """
        bar = getattr(self, "badge_bar", None)
        if bar is None:
            return
        if plugin_id:
            self._badge_plugin_id = plugin_id
        if instance_hash:
            self._badge_instance_hash = instance_hash
        pid = self._badge_plugin_id
        if not pid:
            bar.clear()
            return
        h = self._badge_instance_hash or None
        try:
            status = FeatureStoreReader().fetch_service_tf_status(pid, h)
        except Exception:
            status = {}
        bar.update_status(status)
