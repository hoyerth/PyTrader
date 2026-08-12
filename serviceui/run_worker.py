# serviceui/run_worker.py
"""
Service-UI: Gezielter Hintergrund-Worker fuer die MasterTree-Kontextmenue-
Aktionen '▶️ Diesen Service ausfuehren' / '▶️ Alle Services ausfuehren'
(Phase 15, 05.08.2026).

Im Gegensatz zum historischen `ServiceSetRunWorker` (btn_execute_set, KEIN
Feature-Store-Schreibpfad) persistiert dieser Worker den erzeugten
`feature_store_payload` ZWINGEND in analytics.duckdb (`feature_store`, via
FeatureBuilder.store_plugin_payload) und emittiert danach den EventBus
(`service_set_changed`) – dadurch liest das `ServiceSelectorModel` beim
automatischen refresh() das neue `MAX(created_at)` je feature_id und der
MasterTree aktualisiert das Datum '(DD.MM.JJ)' am betroffenen Service-Knoten
ohne App-Neustart (alle offenen Analytics-/Chart-Fenster folgen synchron).

KEIN globaler Massen-Scan (HistoricalScanner wird bewusst NICHT verwendet):
Der Run ist strikt zielgerichtet –
  * laedt OHLCV nur fuer das aktive Symbol + den gewaehlten Timeframe
    (FeatureBuilder.load_ohlcv),
  * fuehrt nur die selektierte Instanz (Single) bzw. das selektierte Set
    (Set) in execution_order aus (ServiceSetEvaluator.execute_set).

Einzel-Service-Run (single): Es wird eine Mini-Definition gebildet, die den
selektierten Service UND alle Upstream-Services (fruehere Positionen in der
execution_order des Sets) enthaelt – damit liefern Abhaengigkeiten
(depends_on, z.B. grid_1 -> prox_1) ihre shared_state-Eintraege und ein
nachgelagerter Service (srv_proximity) kann tatsaechlich Hits erzeugen und in
den feature_store schreiben.

Der Worker emittiert NUR Signale (log_message / run_finished / run_failed /
tf_started / tf_finished); den Bestaetigungsdialog zeigt der Orchestrator
(ServiceWindow) VOR dem Start.
"""

from typing import Any, Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

# U15-E (05.08.2026): Sentinel-Wert der Timeframe-Filterleiste im
# ServiceWindow. Wird der Kontextmenue-Run mit diesem Timeframe gestartet,
# fuehrt der Worker ALLE verfuegbaren Timeframes nacheinander aus (Multi-TF).
ALL_TIMEFRAMES = "ALLE Timeframes"


class ServiceRunWorker(QThread):
    """Fuehrt einen Einzel-Service oder ein ganzes Service-Set zielgerichtet
    im Hintergrund aus und persistiert die Feature-Payloads im feature_store.

    05.08.2026 (U15-E): Multi-Timeframe-Ausfuehrung – wenn `timeframe` den
    Sentinel-Wert ALL_TIMEFRAMES ('ALLE Timeframes') traegt, laeuft der Worker
    ALLE verfuegbaren Timeframes (get_timeframes, Fallback TF_SECONDS_MAP)
    nacheinander durch: pro Timeframe OHLCV laden, Pipeline ausfuehren und
    die Payloads mit dem jeweiligen Timeframe in den feature_store schreiben.
    Der EventBus-Sync (`service_set_changed`) wird NUR EINMAL nach Abschluss
    aller Timeframes emittiert (E17, 11.08.2026: auch bei Teilerfolg bzw.
    auf Fehlerpfaden, damit bereits geschriebene Payloads im Baum ankommen).

    Signals:
        log_message(str)      – Fortschritts-/Ergebnis-Meldungen.
        run_finished(str, int)– scope_id (set_id ODER instance_id), Anzahl
                                geschriebener Feature-Rows (0 moeglich, wenn
                                der Service keinen feature_store-Payload hat).
        run_failed(str, str)  – scope_id, Fehlermeldung.
        tf_started(str)       – Timeframe-Start (21.01b, Pill-Strip-Laufzeit).
        tf_finished(str, int, bool) – Timeframe fertig: tf, geschriebene
                                Rows, ob OHLCV-Daten vorhanden waren.
        service_progress(str, str, int, int) - Per-Service-Fortschritt:
                                tf, instance_id, erledigte Services, Gesamt.
    """

    log_message = Signal(str)
    run_finished = Signal(str, int)
    run_failed = Signal(str, str)
    tf_started = Signal(str)
    tf_finished = Signal(str, int, bool)
    # 12.08.2026 (User-Meldung 2): Per-Service-Fortschritt.
    service_progress = Signal(str, str, int, int)

    def __init__(self, evaluator, symbol: str, timeframe: str,
                 set_definition: Dict[str, Any],
                 instance_id: Optional[str] = None,
                 parent=None) -> None:
        """Erstellt den Worker.

        Args:
            evaluator:      ServiceSetEvaluator (execute_set-Pipeline).
            symbol:         Aktives Symbol (z.B. 'SILVER').
            timeframe:      Gewaehlter Timeframe (z.B. 'M1').
            set_definition: Vollstaendige ServiceSetDefinition des Sets.
            instance_id:    Optional – bei Single-Run die selektierte
                            instance_id; None = ganzes Set ausfuehren.
            parent:         Qt-Parent (optional).
        """
        super().__init__(parent)
        self.evaluator = evaluator
        self.symbol = symbol
        self.timeframe = timeframe
        self.set_definition = set_definition
        self.instance_id = instance_id
        # 12.08.2026 (WAL-Korruption beim App-Exit): Abbruch-Flag fuer einen
        # sauberen Worker-Stopp. Wird nur zwischen zwei DB-Writes geprueft
        # (Service-Grenzen / Timeframe-Grenzen) - NIE mitten in einem
        # store_plugin_payload-INSERT, sonst bleibt die WAL inkonsistent.
        self._abort_requested = False

    def stop(self) -> None:
        """Fordert einen sauberen Abbruch an (12.08.2026).

        Setzt das Abbruch-Flag. Der Worker beendet sich an der naechsten
        Service-/Timeframe-Grenze - d. h. nach dem naechsten abgeschlossenen
        store_plugin_payload-Write. Bereits gespeicherte Payloads bleiben
        erhalten, die WAL bleibt konsistent (kein Abbruch mitten im INSERT).
        """
        self._abort_requested = True

    # ------------------------------------------------------------------
    # Ausfuehrungs-Scope (Single vs. Set)
    # ------------------------------------------------------------------
    def _build_scope_definition(self) -> Dict[str, Any]:
        """Liefert die auszufuehrende (Mini-)Definition.

        * Set-Run: die vollstaendige Set-Definition.
        * Single-Run: der selektierte Service + alle Upstream-Services
          (vorherige Positionen in execution_order) – Abhaengigkeiten
          (depends_on) bleiben gueltig, die Pipeline ist aber strikt auf
          die selektierte Instanz ausgerichtet (kein globaler Massen-Scan).
        """
        if not self.instance_id:
            return self.set_definition
        order = list(self.set_definition.get("execution_order") or [])
        services = dict(self.set_definition.get("services") or {})
        if self.instance_id not in services:
            raise ValueError(
                f"Service '{self.instance_id}' nicht im Set vorhanden.")
        if self.instance_id in order:
            idx = order.index(self.instance_id)
        else:
            # Instanz nicht in der Reihenfolge -> nur die Instanz selbst
            idx = 0
            order = []
        scope_order = order[:idx + 1]
        scope_services = {
            iid: services[iid] for iid in scope_order if iid in services
        }
        return {
            "set_id": self.set_definition.get("set_id"),
            "display_name": self.set_definition.get("display_name"),
            "execution_order": scope_order,
            "services": scope_services,
        }

    # ------------------------------------------------------------------
    # U15-E (05.08.2026): Timeframe-Aufloesung (Single vs. Multi-TF)
    # ------------------------------------------------------------------
    def _resolve_timeframes(self) -> List[str]:
        """Liefert die auszufuehrenden Timeframes in stabiler Reihenfolge.

        * Spezifischer Timeframe: [self.timeframe] (Single-Run, unveraendert).
        * ALL_TIMEFRAMES: alle verfuegbaren Timeframes aus get_timeframes()
          (Fallback: TF_SECONDS_MAP; letzter Fallback: Basisliste).
        """
        if self.timeframe != ALL_TIMEFRAMES:
            return [self.timeframe]
        try:
            from db_service import TF_SECONDS_MAP, get_timeframes
            try:
                tfs = list(get_timeframes().keys())
            except Exception:
                tfs = list(TF_SECONDS_MAP.keys())
            # 21.01b (E18c, 11.08.2026): stabil AUFSTEIGEND nach Dauer
            # (M1..MN1) – gleiche Reihenfolge wie combo_tf/Pill-Strip;
            # schnelle TFs laufen damit zuerst.
            return sorted(tfs, key=lambda tf: TF_SECONDS_MAP.get(tf, 10 ** 12))
        except Exception:
            return ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

    def _execute_timeframe(self, fb, settings, definition: Dict[str, Any],
                           scope_label: str, tf: str) -> Tuple[int, bool]:
        """Fuehrt die Pipeline fuer EINEN Timeframe aus und persistiert die
        Feature-Payloads im feature_store.

        E17 (11.08.2026): Die Pipeline laeuft resilient – schlaegt ein
        EINZELNER Service fehl, wird er geloggt (execute_set_resilient:
        last_errors/last_skipped) und die restlichen Services laufen weiter
        statt die Gesamt-Ausfuehrung abzubrechen. execute_set (Fail-Fast)
        bleibt als Fallback fuer fremde Evaluator-Instanzen ohne die
        Resilient-Methode.

        Returns:
            (stored, had_data) – Anzahl geschriebener Feature-Rows (0, wenn
            kein Payload vorhanden ist) und ob OHLCV-Daten geladen wurden
            (False, wenn die Quelle leer war – NUR dann ist die Meldung
            'Keine OHLCV-Daten' korrekt, 17.01.02 Bugfix).
        """
        from analytics.features.feature_builder import prepare_plugin_df
        from analytics.features.plugins.base_plugin import PluginContext

        df = fb.load_ohlcv(self.symbol, tf,
                           limit=settings.scanner_candle_limit)
        if df is None or df.empty:
            self.log_message.emit(
                f"  {self.symbol} {tf}: keine OHLCV-Daten – uebersprungen")
            return 0, False

        df_plugin = prepare_plugin_df(df)
        context = PluginContext(
            symbol=self.symbol,
            timeframe=tf,
            mode="batch",
            timestamp=int(df_plugin["time"].iloc[-1]) if len(df_plugin) else None,
            settings=settings,
        )

        self.log_message.emit(
            f"Ausfuehren: {scope_label} ({self.symbol} {tf})")
        if hasattr(self.evaluator, "execute_set_resilient"):
            results = self.evaluator.execute_set_resilient(
                definition, df_plugin, context=context,
                progress_callback=lambda iid, pos, total: (
                    self.service_progress.emit(tf, iid, pos, total)))
        else:
            results = self.evaluator.execute_set(definition, df_plugin,
                                                 context=context)

        stored = 0
        # 20.04 (Q9): Instanz-Hashes je iid – Grundlage der feature_store-
        # Spalte instance_hash (Varianten-Statistik + gezieltes Purge, Q5).
        # Bevorzugt cfg.instance_hash (Set-Definition), sonst deterministisch
        # aus generate_instance_hash(plugin_id, params) neu berechnet.
        from analytics.engine.service_models import generate_instance_hash
        svc_cfgs = dict(definition.get("services") or {})
        for iid, result in results.items():
            # 12.08.2026 (WAL-Korruption beim App-Exit): Sauberer Abbruch an
            # der Service-Grenze - VOR dem naechsten store_plugin_payload.
            # Bereits geschriebene Payloads dieses Timeframes bleiben intakt.
            if self._abort_requested:
                break
            payload = (result or {}).get("feature_store_payload") or {}
            records = payload.get("records") or []
            if not records:
                self.log_message.emit(
                    f"  {iid}: fertig (kein Feature-Store-Payload)")
                continue
            cfg = svc_cfgs.get(iid) or {}
            pid = str(cfg.get("plugin_id") or iid)
            params = cfg.get("params") or {}
            # 11.08.2026 (Bugfix Varianten-Kollision): Fallback-Hash inkl.
            # preset_name berechnen (identisch zum ServiceSelectorModel) –
            # die cfg.instance_hash (aus variant_run_entries) hat Vorrang.
            preset_name = str(cfg.get("preset_name") or "") or None
            instance_hash = str(cfg.get("instance_hash") or "") or \
                generate_instance_hash(pid, params,
                                       preset_name=preset_name)
            fb.store_plugin_payload(self.symbol, tf, payload,
                                    instance_hash=instance_hash)
            stored += len(records)
            self.log_message.emit(
                f"  {iid}: {len(records)} Feature-Row(s) gespeichert "
                f"({self.symbol} {tf})")
        return stored, True

    # ------------------------------------------------------------------
    # E17 (11.08.2026): EventBus-Sync (auch auf Fehlerpfaden)
    # ------------------------------------------------------------------
    def _emit_service_changed(self) -> None:
        """Stoesst den UI-Sync einmalig an.

        Nach (Teil-)Abschluss des Workers werden alle lauschenden
        ServiceSelectorModel-Instanzen (MasterTree, Analytics, ...)
        automatisch aktualisiert – sie lesen das neue MAX(created_at) und
        der Baum zeigt das Datum (DD.MM.JJ) live an. E17: Der Sync wird
        auch bei run_failed/Teilerfolg emittiert, damit bereits geschriebene
        Payloads (z.B. fruehere Timeframes eines Multi-TF-Runs) sichtbar
        werden.
        """
        try:
            from config.event_bus import event_bus
            event_bus.service_set_changed.emit()
        except Exception as e:  # pragma: no cover
            print(f"WARN [ServiceRunWorker] EventBus-Emitt fehlgeschlagen: {e}")

    # ------------------------------------------------------------------
    # Worker-Loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Laedt OHLCV (ein oder alle Timeframes), fuehrt die Pipeline aus,
        persistiert die Payloads im feature_store und stoesst den EventBus-
        Sync an (einmalig nach Abschluss – auch bei Teilerfolg/Fehler)."""
        scope_id = self.instance_id or str(
            self.set_definition.get("set_id") or "")
        try:
            from analytics.features.feature_builder import FeatureBuilder
            from state_manager import StateManager

            settings = StateManager().get_app_settings()
            fb = FeatureBuilder()
            definition = self._build_scope_definition()
            # 20.04 (Q6): Archiv-Ignoranz (Archive Safety) – archivierte Sets
            # bzw. einzeln archivierte Instanzen werden NICHT ausgefuehrt.
            # Der MasterTree deaktiviert die Run-Aktionen zusaetzlich
            # (Doppel-Absicherung; Scans/Executors bleiben rein lesend).
            if not self.instance_id and self.set_definition.get("is_archived"):
                self.log_message.emit(
                    f"Archiviertes Set '{scope_id}' wird nicht ausgefuehrt "
                    f"(Q6).")
                self.run_finished.emit(scope_id, 0)
                return
            if self.instance_id:
                _svc = (self.set_definition.get("services") or {}).get(
                    self.instance_id) or {}
                if _svc.get("is_archived"):
                    self.log_message.emit(
                        f"Archivierte Instanz '{self.instance_id}' wird nicht "
                        f"ausgefuehrt (Q6).")
                    self.run_finished.emit(scope_id, 0)
                    return
            # 05.08.2026 (Bugfix Service-Run):
            #  * Fehlende depends_on-Einträge (z.B. srv_proximity -> srv_grid_lines)
            #    werden automatisch aufgelöst (sonst 'kein Feature-Store-
            #    Payload' beim Single-Run eines nachgelagerten Services).
            #  * Scanner-Candles (max) aus den App-Optionen als max Lookback
            #    für ALLE Services (Datenbasis wie beim Historical Scanner).
            from serviceui.service_set_utils import prepare_worker_definition
            definition = prepare_worker_definition(
                definition,
                getattr(settings, "scanner_candle_limit", 100000),
            )
            display = str(definition.get("display_name")
                          or self.set_definition.get("display_name")
                          or scope_id or "Unbenannt")
            scope_label = (f"Service '{self.instance_id}' im Set '{display}'"
                           if self.instance_id else f"Set '{display}'")
            self.log_message.emit(f"Ausfuehren: {scope_label}")

            timeframes = self._resolve_timeframes()
            if not timeframes:
                self.run_failed.emit(
                    scope_id, "Keine Timeframes verfuegbar.")
                return

            total_stored = 0
            no_data_tfs: List[str] = []
            no_payload_tfs: List[str] = []
            for tf in timeframes:
                # 12.08.2026 (WAL-Korruption beim App-Exit): Sauberer Abbruch
                # an der Timeframe-Grenze (nach abgeschlossener Persistenz des
                # vorherigen Timeframes) - nie mitten in einem DB-Write.
                if self._abort_requested:
                    self.log_message.emit("Abbruch angefordert - Ausfuehrung "
                                          "wird sauber beendet.")
                    break
                self.tf_started.emit(tf)
                try:
                    stored, had_data = self._execute_timeframe(
                        fb, settings, definition, scope_label, tf)
                except Exception as e:
                    # U15-E (Multi-TF): Ein fehlgeschlagener Timeframe bricht
                    # die Gesamt-Ausfuehrung NICHT ab – Fehler wird geloggt,
                    # die restlichen Timeframes laufen weiter.
                    self.tf_finished.emit(tf, 0, False)
                    if self.timeframe == ALL_TIMEFRAMES:
                        self.log_message.emit(
                            f"  {self.symbol} {tf}: FEHLER – {e}")
                        continue
                    raise
                self.tf_finished.emit(tf, stored, had_data)
                total_stored += stored
                if not had_data:
                    no_data_tfs.append(tf)
                elif stored == 0:
                    no_payload_tfs.append(tf)

            # E17: Sync NACH der (Teil-)Ausfuehrung – auch wenn anschliessend
            # run_failed folgt, kommen bereits geschriebene Payloads im Baum an.
            self._emit_service_changed()

            # Single-TF-Fehler differenzieren (17.01.02 Bugfix): Die
            # Meldung 'Keine OHLCV-Daten' ist NUR korrekt, wenn die Quelle
            # leer war. Waren Daten vorhanden, aber der Service hat keinen
            # Feature-Store-Payload erzeugt, wird das praezise gemeldet
            # (z. B. Scaffold mit records=[], unbekannter Modus).
            if len(timeframes) == 1:
                if no_data_tfs:
                    self.run_failed.emit(
                        scope_id,
                        f"Keine OHLCV-Daten fuer {self.symbol} {timeframes[0]}.")
                    return
                if no_payload_tfs:
                    self.run_failed.emit(
                        scope_id,
                        f"Kein Feature-Store-Payload erzeugt fuer "
                        f"{self.symbol} {timeframes[0]} (Service lieferte "
                        f"0 Records – Daten waren vorhanden).")
                    return

            self.log_message.emit(
                f"Fertig: {total_stored} Feature-Row(s) im feature_store "
                f"({self.symbol}).")

            self.run_finished.emit(scope_id, total_stored)
        except Exception as e:
            # E17: Auch bei Abbruch durch Exception wird der Sync angestossen
            # (falls bereits Payloads geschrieben wurden).
            self._emit_service_changed()
            self.run_failed.emit(scope_id, str(e))
