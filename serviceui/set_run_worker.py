# serviceui/set_run_worker.py
"""
Service-UI: Hintergrund-Worker für die Set-Ausführung.

Phase 15, Kapitel 15.1 (U15-D1): Aus service_win.py ausgelagert.
05.08.2026 (Punkt 2, Ausführungsdatum): Der Worker persistiert die
erzeugten `feature_store_payloads` ZWINGEND in analytics.duckdb
(`feature_store`, FeatureBuilder.store_plugin_payload) und emittiert danach
`event_bus.service_set_changed` – dadurch liest das `ServiceSelectorModel`
beim automatischen refresh() das neue MAX(created_at) je feature_id und der
MasterTree aktualisiert das Datum '(DD.MM.JJ)' am betroffenen Service-Knoten
ohne App-Neustart. Vorher schrieb nur der RAM-basierte Render-Pfad (kein
Datum im Baum nach btn_execute_set).

Hinweis: `grid_lines` liefert bewusst KEINEN feature_store_payload (reines
Chart-Overlay) – nur Services mit non-leeren `records` (z.B. `proximity`)
schreiben Zeilen.
"""

from typing import Any, Dict

from PySide6.QtCore import QThread, Signal

from analytics.engine.set_evaluator import ServiceSetEvaluator


class ServiceSetRunWorker(QThread):
    """Phase 13 Schritt 4: Führt ein Service-Set im Hintergrund aus.

    Lädt OHLCV (Symbol/Timeframe), ruft ServiceSetEvaluator.execute_set()
    in einem separaten Thread auf (GUI blockiert nicht), persistiert die
    Feature-Payloads im feature_store und stösst den EventBus-Sync an.
    """

    log_message = Signal(str)
    run_finished = Signal(str, int)  # set_id, Anzahl erfolgreicher Services
    run_failed = Signal(str, str)    # set_id, Fehlermeldung

    def __init__(self, evaluator: ServiceSetEvaluator, symbol: str, timeframe: str,
                 set_definition: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.evaluator = evaluator
        self.symbol = symbol
        self.timeframe = timeframe
        self.set_definition = set_definition

    def run(self):
        try:
            from analytics.features.feature_builder import FeatureBuilder, prepare_plugin_df
            from analytics.features.plugins.base_plugin import PluginContext
            from config.event_bus import event_bus
            from state_manager import StateManager

            settings = StateManager().get_app_settings()
            fb = FeatureBuilder()
            df = fb.load_ohlcv(self.symbol, self.timeframe, limit=settings.feature_builder_limit)
            if df is None or df.empty:
                self.run_failed.emit(
                    self.set_definition.get("set_id", ""),
                    f"Keine OHLCV-Daten fuer {self.symbol} {self.timeframe}.",
                )
                return

            df_plugin = prepare_plugin_df(df)
            context = PluginContext(
                symbol=self.symbol,
                timeframe=self.timeframe,
                mode="batch",
                timestamp=int(df_plugin["time"].iloc[-1]) if len(df_plugin) else None,
                settings=settings,
            )
            display = self.set_definition.get("display_name") or self.set_definition.get("set_id") or "Unbenannt"
            self.log_message.emit(f"Ausfuehren: {display} ({self.symbol} {self.timeframe})")

            results = self.evaluator.execute_set(self.set_definition, df_plugin, context=context)

            # Feature-Store-Persistenz (05.08.2026, Punkt 2): Jeder Service
            # mit non-leerem feature_store_payload wird in analytics.duckdb
            # geschrieben. created_at wird bei jedem Upsert aktualisiert
            # (ON CONFLICT DO UPDATE) -> MAX(created_at) je feature_id
            # liefert die LETZTE Ausfuehrung.
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

            # UI-Sync: Nach Abschluss aktualisieren sich alle lauschenden
            # ServiceSelectorModel-Instanzen (MasterTree, Analytics, ...)
            # automatisch – sie lesen das neue MAX(created_at) und der Baum
            # zeigt das Datum (DD.MM.JJ) live an.
            try:
                event_bus.service_set_changed.emit()
            except Exception as e:  # pragma: no cover
                print(f"WARN [ServiceSetRunWorker] EventBus-Emitt fehlgeschlagen: {e}")

            for iid in results:
                self.log_message.emit(f"  {iid}: fertig")
            self.run_finished.emit(self.set_definition.get("set_id", ""), len(results))
        except Exception as e:
            self.run_failed.emit(self.set_definition.get("set_id", ""), str(e))
