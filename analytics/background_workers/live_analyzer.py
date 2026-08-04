# analytics/background_workers/live_analyzer.py
"""
Live Analyzer – QThread-Worker für die Live-Analyse bei Bar-Close.

Phase 15 (Alt-Signal-Rückbau): Die Alt-Signal-Mechanik (ema_atr_set_v1 /
alternating_arrow_v1 / grid_proximity_v1) wurde komplett entfernt – es gibt
keine Signal-Engine, keine signal_results-Writes und keine new_live_signal-
Emission mehr. Der LiveAnalyzer evaluiert ausschließlich die aktiven
Batch-Plugins (live_op=True) über den PluginExecutor:

    Tick -> Bar-Close -> PluginExecutor -> feature_store (feature_data)

Der resiliente Pfad `_process_plugin_bars_resilient()` (P14-03-E) ist der
primäre Bar-Close-Pfad: stark verkürzter Lookback (1-2 Bars) gegen das im
`PluginContext.shared_state` gepufferte Raster – keine volle Pipeline und
KEINE DB-Abfragen im Live-Tick.
"""

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

from analytics.features.feature_builder import (
    FeatureBuilder,
    PluginExecutor,
    PluginExecutionError,
    prepare_plugin_df,
)
from analytics.features.plugins.base_plugin import PluginContext
from db_service import DbPool
from state_manager import StateManager

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_ANALYTICS = str(BASE_DIR / "data" / "analytics.duckdb")
DB_MARKET = str(BASE_DIR / "data" / "market_data.duckdb")


class LiveAnalyzer(QThread):
    """
    Analysiert eine geschlossene Live-Kerze (Bar-Close Event) über die
    aktiven Batch-Plugins (live_op=True) und schreibt die Ergebnisse in den
    feature_store (feature_data).
    """

    log_message = Signal(str)

    def __init__(
        self,
        symbol: str = "SILVER",
        timeframe: str = "M1",
        lookback_bars: int = 500,
        parent=None,
    ):
        super().__init__(parent)
        self.symbol = symbol
        self.timeframe = timeframe
        self.lookback_bars = lookback_bars
        self._running = True

        # Feature Builder
        self.feature_builder = FeatureBuilder()

        # Zentraler PluginExecutor für den Plugin-Modus (aktive Batch-Presets
        # mit live_op = True). Dieselbe Instanz, die auch der HistoricalScanner
        # nutzt.
        self.plugin_executor = PluginExecutor()
        self._state_mgr = StateManager()

        # P14-03 (Live-Entkopplung A.1.2): Persistenter EvaluationContext-
        # Buffer über alle Polls hinweg. Der LiveAnalyzer evaluiert geschlossene
        # Kerzen mit stark verkürztem Lookback (1-2 Bars) GEGEN dieses im RAM
        # gepufferte Raster – kein voller Pipeline-Neuaufbau pro Poll.
        self._live_shared_state: Dict[str, Any] = {}
        self._live_context = PluginContext(
            symbol=self.symbol,
            timeframe=self.timeframe,
            mode="live",
            shared_state=self._live_shared_state,
        )

        # Letzte verarbeitete Bar-Time (für Duplikatserkennung)
        self._last_processed_bar_time: Optional[int] = None

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        """
        Hauptschleife: Wartet auf Bar-Close-Events (Polling) und evaluiert
        die aktiven Batch-Plugins über den resilienten Pfad
        `_process_plugin_bars_resilient()` (Plugin-Modus, gepuffertes
        shared_state-Raster).
        """
        self.log_message.emit(
            f"LiveAnalyzer gestartet: {self.symbol} {self.timeframe}, "
            f"lookback={self.lookback_bars}"
        )

        while self._running:
            try:
                self._process_plugin_bars_resilient()
            except Exception as e:
                self.log_message.emit(f"❌ LiveAnalyzer Fehler: {e}")

            # Polling-Intervall: 1 Sekunde (fuer M1 ausreichend)
            self.msleep(1000)

        self.log_message.emit("LiveAnalyzer gestoppt.")

    def _get_active_live_plugins(self) -> List[Dict[str, Any]]:
        """Liefert aktive Batch-Presets, deren Plugin live_op = True ist
        (Phase 12 Plugin-Modus)."""
        try:
            presets = self._state_mgr.list_active_batch_presets()
        except Exception:
            return []
        active: List[Dict[str, Any]] = []
        for preset in presets:
            plugin_id = preset.get("plugin_id")
            if not plugin_id:
                continue
            try:
                plugin = self.plugin_executor.registry.get(plugin_id)
            except KeyError:
                continue
            if getattr(plugin, "live_op", True):
                active.append(preset)
        return active

    def _process_plugin_bars(self) -> None:
        """Phase 12 Plugin-Modus (Live): Fuehrt aktive Batch-Plugins mit
        live_op = True über dieselbe PluginExecutor-Instanz aus und schreibt
        den feature_store_payload in den feature_store.

        P14-03 (Schritt 3.1, additiv): Fuer laufende Bar-Close-Evaluierungen
        existiert der Seam _process_plugin_bars_resilient() – er nutzt einen
        stark verkuerzten Lookback (limit=2: 1 unvollstaendige + 1 frisch
        geschlossene Kerze) gegen das gepufferte EvaluationContext.shared_state
        -Raster. Dieser Alt-Pfad bleibt unveraendert."""
        plugins = self._get_active_live_plugins()
        if not plugins:
            return

        con = DbPool.get(DB_MARKET)
        latest_bar_time = con.execute("""
            SELECT EXTRACT('epoch' FROM MAX("time"))::BIGINT FROM ohlcv_bars
            WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
              AND "time" IS NOT NULL
        """, [self.symbol, self.timeframe]).fetchone()[0]
        if latest_bar_time is None:
            return
        latest_bar_time = int(latest_bar_time)

        if self._last_processed_bar_time is not None and latest_bar_time <= self._last_processed_bar_time:
            return

        df_ohlcv = self.feature_builder.load_ohlcv(
            self.symbol, self.timeframe, limit=self.lookback_bars
        )
        if df_ohlcv.empty:
            return

        df_plugin = prepare_plugin_df(df_ohlcv)
        for preset in plugins:
            plugin_id = preset.get("plugin_id")
            try:
                result = self.plugin_executor.execute(plugin_id, df_plugin, preset.get("params", {}))
            except Exception as e:
                self.log_message.emit(f"❌ Plugin-Fehler ({plugin_id}): {e}")
                continue
            payload = result.get("feature_store_payload", {}) if isinstance(result, dict) else {}
            if payload:
                try:
                    n = self.feature_builder.store_plugin_payload(self.symbol, self.timeframe, payload)
                    self.log_message.emit(
                        f"🔌 Plugin {plugin_id}: {n} Feature-Rows im feature_store"
                    )
                except Exception as e:
                    self.log_message.emit(f"❌ Plugin-Store-Fehler ({plugin_id}): {e}")

        self._last_processed_bar_time = latest_bar_time

    def _process_plugin_bars_resilient(self) -> None:
        """P14-03 (Live-Entkopplung A.1.2): Bar-Close-Evaluierung im
        Hintergrund mit STARK VERKÜRZTEM Lookback (1-2 Bars) gegen das im
        EvaluationContext.shared_state gepufferte Raster.

        Additiver Seam zum bestehenden Phase-12-Pfad (run() ruft weiterhin
        _process_plugin_bars auf): Der persistente self._live_context
        (shared_state = self._live_shared_state) puffert das Grid-Raster über
        alle Polls hinweg; bei Bar-Close werden nur die letzten 1-2 Bars neu
        bewertet. Schlägt ein Service fehl, wird der Fehler strukturiert
        (PluginExecutionErrorInfo) geloggt und der alte shared_state-Eintrag
        (State-Fallback) bleibt für abhängige Auswertungen erhalten – KEINE
        DB-Abfragen im Live-Tick, nur bei Bar-Close.
        """
        plugins = self._get_active_live_plugins()
        if not plugins:
            return

        con = DbPool.get(DB_MARKET)
        latest_bar_time = con.execute("""
            SELECT EXTRACT('epoch' FROM MAX("time"))::BIGINT FROM ohlcv_bars
            WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
              AND "time" IS NOT NULL
        """, [self.symbol, self.timeframe]).fetchone()[0]
        if latest_bar_time is None:
            return
        latest_bar_time = int(latest_bar_time)

        if self._last_processed_bar_time is not None and latest_bar_time <= self._last_processed_bar_time:
            return

        df_ohlcv = self.feature_builder.load_ohlcv(
            self.symbol, self.timeframe, limit=self.lookback_bars
        )
        if df_ohlcv.empty:
            return

        df_plugin = prepare_plugin_df(df_ohlcv)
        # P14-03: stark verkürzter Lookback (1-2 Bars) gegen das gepufferte
        # Raster – minimiert Rechnerlast und DB-I/O.
        df_short = df_plugin.tail(2)

        for preset in plugins:
            plugin_id = preset.get("plugin_id")
            # instance_id = plugin_id → GridLinesService schreibt sein Raster
            # in den persistenten shared_state (Namespace-isoliert).
            svc_ctx = replace(self._live_context, instance_id=plugin_id)
            if plugin_id == "proximity":
                # Proximity liest das Grid-Raster aus shared_state[depends_on[0]].
                svc_ctx = replace(svc_ctx, depends_on=["grid_lines"])
            try:
                result = self.plugin_executor.execute(
                    plugin_id, df_short, preset.get("params", {}), context=svc_ctx
                )
            except PluginExecutionError as e:
                info = e.info
                self.log_message.emit(
                    f"WARN [LiveAnalyzer] LiveService '{plugin_id}' fehlgeschlagen "
                    f"({info.stage}: {info.exception_type}: "
                    f"{info.exception_message}) – State-Fallback aktiv"
                )
                continue
            except Exception as e:
                self.log_message.emit(
                    f"WARN [LiveAnalyzer] LiveService '{plugin_id}' fehlgeschlagen: {e}"
                )
                continue
            payload = result.get("feature_store_payload", {}) if isinstance(result, dict) else {}
            if payload:
                try:
                    n = self.feature_builder.store_plugin_payload(
                        self.symbol, self.timeframe, payload
                    )
                    self.log_message.emit(
                        f"Plugin {plugin_id}: {n} Feature-Rows im feature_store"
                    )
                except Exception as e:
                    self.log_message.emit(f"Plugin-Store-Fehler ({plugin_id}): {e}")

        self._last_processed_bar_time = latest_bar_time
