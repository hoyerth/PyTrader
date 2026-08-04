# serviceui/set_run_worker.py
"""
Service-UI: Hintergrund-Worker für die Set-Ausführung.

Phase 15, Kapitel 15.1 (U15-D1): Aus service_win.py ausgelagert –
Verhalten unverändert.
"""

from typing import Any, Dict

from PySide6.QtCore import QThread, Signal

from analytics.engine.set_evaluator import ServiceSetEvaluator


class ServiceSetRunWorker(QThread):
    """Phase 13 Schritt 4: Führt ein Service-Set im Hintergrund aus.

    Lädt OHLCV (Symbol/Timeframe) und ruft ServiceSetEvaluator.execute_set()
    in einem separaten Thread auf, damit die GUI nicht blockiert.
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
            for iid in results:
                self.log_message.emit(f"  {iid}: fertig")
            self.run_finished.emit(self.set_definition.get("set_id", ""), len(results))
        except Exception as e:
            self.run_failed.emit(self.set_definition.get("set_id", ""), str(e))
