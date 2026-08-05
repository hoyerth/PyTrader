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
nachgelagerter Service (proximity) kann tatsaechlich Hits erzeugen und in
den feature_store schreiben.

Der Worker emittiert NUR Signale (log_message / run_finished / run_failed);
den Bestaetigungsdialog zeigt der Orchestrator (ServiceWindow) VOR dem Start.
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import QThread, Signal


class ServiceRunWorker(QThread):
    """Fuehrt einen Einzel-Service oder ein ganzes Service-Set zielgerichtet
    im Hintergrund aus und persistiert die Feature-Payloads im feature_store.

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
    # Worker-Loop
    # ------------------------------------------------------------------
    def run(self) -> None:
        """Laedt OHLCV, fuehrt die Pipeline aus, persistiert die Payloads
        im feature_store und stoesst den EventBus-Sync an."""
        scope_id = self.instance_id or str(
            self.set_definition.get("set_id") or "")
        try:
            from analytics.features.feature_builder import (
                FeatureBuilder, prepare_plugin_df)
            from analytics.features.plugins.base_plugin import PluginContext
            from config.event_bus import event_bus
            from state_manager import StateManager

            settings = StateManager().get_app_settings()
            fb = FeatureBuilder()
            df = fb.load_ohlcv(self.symbol, self.timeframe,
                               limit=settings.feature_builder_limit)
            if df is None or df.empty:
                self.run_failed.emit(
                    scope_id,
                    f"Keine OHLCV-Daten fuer {self.symbol} {self.timeframe}.")
                return

            df_plugin = prepare_plugin_df(df)
            context = PluginContext(
                symbol=self.symbol,
                timeframe=self.timeframe,
                mode="batch",
                timestamp=int(df_plugin["time"].iloc[-1]) if len(df_plugin) else None,
                settings=settings,
            )

            definition = self._build_scope_definition()
            display = str(definition.get("display_name")
                          or self.set_definition.get("display_name")
                          or scope_id or "Unbenannt")
            scope_label = (f"Service '{self.instance_id}' im Set '{display}'"
                           if self.instance_id else f"Set '{display}'")
            self.log_message.emit(
                f"Ausfuehren: {scope_label} ({self.symbol} {self.timeframe})")

            results = self.evaluator.execute_set(definition, df_plugin,
                                                 context=context)

            # Feature-Store-Persistenz: Jeder Service mit non-leerem
            # feature_store_payload wird in analytics.duckdb geschrieben.
            stored = 0
            for iid, result in results.items():
                payload = (result or {}).get("feature_store_payload") or {}
                records = payload.get("records") or []
                if not records:
                    self.log_message.emit(
                        f"  {iid}: fertig (kein Feature-Store-Payload)")
                    continue
                fb.store_plugin_payload(self.symbol, self.timeframe, payload)
                stored += len(records)
                self.log_message.emit(
                    f"  {iid}: {len(records)} Feature-Row(s) gespeichert")

            self.log_message.emit(
                f"Fertig: {stored} Feature-Row(s) im feature_store "
                f"({self.symbol} {self.timeframe}).")

            # UI-Sync: Nach Abschluss des Workers werden alle lauschenden
            # ServiceSelectorModel-Instanzen (MasterTree, Analytics, ...)
            # automatisch aktualisiert – sie lesen das neue MAX(created_at)
            # und der Baum zeigt das Datum (DD.MM.JJ) live an.
            try:
                event_bus.service_set_changed.emit()
            except Exception as e:  # pragma: no cover
                print(f"WARN [ServiceRunWorker] EventBus-Emitt fehlgeschlagen: {e}")

            self.run_finished.emit(scope_id, stored)
        except Exception as e:
            self.run_failed.emit(scope_id, str(e))
