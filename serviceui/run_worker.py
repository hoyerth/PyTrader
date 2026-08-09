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

Der Worker emittiert NUR Signale (log_message / run_finished / run_failed);
den Bestaetigungsdialog zeigt der Orchestrator (ServiceWindow) VOR dem Start.
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
    aller Timeframes emittiert.

    Signals:
        log_message(str)      – Fortschritts-/Ergebnis-Meldungen.
        run_finished(str, int)– scope_id (set_id ODER instance_id), Anzahl
                                geschriebener Feature-Rows (0 moeglich, wenn
                                der Service keinen feature_store-Payload hat).
        run_failed(str, str)  – scope_id, Fehlermeldung.
    """

    log_message = Signal(str)
    run_finished = Signal(str, int)
    run_failed = Signal(str, str)

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
                return list(get_timeframes().keys())
            except Exception:
                return list(TF_SECONDS_MAP.keys())
        except Exception:
            return ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]

    def _execute_timeframe(self, fb, settings, definition: Dict[str, Any],
                           scope_label: str, tf: str) -> Tuple[int, bool]:
        """Fuehrt die Pipeline fuer EINEN Timeframe aus und persistiert die
        Feature-Payloads im feature_store.

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
            payload = (result or {}).get("feature_store_payload") or {}
            records = payload.get("records") or []
            if not records:
                self.log_message.emit(
                    f"  {iid}: fertig (kein Feature-Store-Payload)")
                continue
            cfg = svc_cfgs.get(iid) or {}
            pid = str(cfg.get("plugin_id") or iid)
            params = cfg.get("params") or {}
            instance_hash = str(cfg.get("instance_hash") or "") or \
                generate_instance_hash(pid, params)
            fb.store_plugin_payload(self.symbol, tf, payload,
                                    instance_hash=instance_hash)
            stored += len(records)
            self.log_message.emit(
                f"  {iid}: {len(records)} Feature-Row(s) gespeichert "
                f"({self.symbol} {tf})")
        return stored, True

    # ------------------------------------------------------------------
    # Worker-Loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Laedt OHLCV (ein oder alle Timeframes), fuehrt die Pipeline aus,
        persistiert die Payloads im feature_store und stoesst den EventBus-
        Sync an (einmalig nach Abschluss)."""
        scope_id = self.instance_id or str(
            self.set_definition.get("set_id") or "")
        try:
            from analytics.features.feature_builder import FeatureBuilder
            from config.event_bus import event_bus
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
                try:
                    stored, had_data = self._execute_timeframe(
                        fb, settings, definition, scope_label, tf)
                except Exception as e:
                    # U15-E (Multi-TF): Ein fehlgeschlagener Timeframe bricht
                    # die Gesamt-Ausfuehrung NICHT ab – Fehler wird geloggt,
                    # die restlichen Timeframes laufen weiter.
                    if self.timeframe == ALL_TIMEFRAMES:
                        self.log_message.emit(
                            f"  {self.symbol} {tf}: FEHLER – {e}")
                        continue
                    raise
                total_stored += stored
                if not had_data:
                    no_data_tfs.append(tf)
                elif stored == 0:
                    no_payload_tfs.append(tf)

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

            # UI-Sync: Nach Abschluss des Workers werden alle lauschenden
            # ServiceSelectorModel-Instanzen (MasterTree, Analytics, ...)
            # automatisch aktualisiert – sie lesen das neue MAX(created_at)
            # und der Baum zeigt das Datum (DD.MM.JJ) live an.
            try:
                event_bus.service_set_changed.emit()
            except Exception as e:  # pragma: no cover
                print(f"WARN [ServiceRunWorker] EventBus-Emitt fehlgeschlagen: {e}")

            self.run_finished.emit(scope_id, total_stored)
        except Exception as e:
            self.run_failed.emit(scope_id, str(e))
