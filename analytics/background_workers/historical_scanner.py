# analytics/background_workers/historical_scanner.py
"""
Historical Scanner – QThread-Worker für Batch-Scans über historische Daten.
Unterstützt Full-Scan (Delete + Re-Scan) und Delta-Update (fehlende Bars).

Phase 15 U15-C2 (Alt-Pfad-Rückbau, additiv): ZIELZUSTAND des
HistoricalScanner ist der PLUGIN-BATCH (`_run_plugin_batch` über den
PluginExecutor, aktive Batch-Presets aus `indicator_presets`). Der Alt-Scan
(grid_scan / Standard-Scan über SetEvaluator) bleibt parallel betreibbar,
schreibt aber wie der Plugin-Batch AUSSCHLIESSLICH in den feature_store
(Phase 13 Schritt 7.B) – es finden KEINE signal_results-Writes mehr statt.
`signal_results` bleibt bis zur finalen Entscheidung (U15-C3) unverändert
als Referenz erhalten.
"""

import time
from typing import Any, Dict, List, Optional, Set
from PySide6.QtCore import QThread, Signal

from analytics.features.feature_builder import FeatureBuilder, PluginExecutor, prepare_plugin_df
from analytics.engine.set_evaluator import SetEvaluator
from analytics.signals.heuristics.ema_trend import EMATrendSignal
from analytics.signals.heuristics.atr_filter import ATRFilterSignal
from analytics.signals.composite.grid_proximity_signal import GridProximitySignal
from db_service import get_timeframes
from state_manager import StateManager


class HistoricalScanner(QThread):
    """Scannt historische Daten für ein Symbol über alle Timeframes."""

    progress_updated = Signal(str, int, int)  # message, current, total
    scan_finished = Signal(str, int)          # symbol, total_signals_written
    log_message = Signal(str)                 # log text

    def __init__(
        self,
        symbol: str,
        new_scan: bool = False,
        grid_scan: bool = False,
        parent=None,
        db_path_app: Optional[str] = None,
        db_path_analytics: Optional[str] = None,
        db_path_market: Optional[str] = None,
        timeframes: Optional[List[str]] = None,
    ):
        super().__init__(parent)
        self.symbol = symbol
        self.new_scan = new_scan
        self.grid_scan = grid_scan
        self._running = True
        # Override-Pfade (Test/Isolation) – None = Produktions-DBs
        self._db_path_app = db_path_app
        self._db_path_analytics = db_path_analytics
        self._db_path_market = db_path_market
        self._timeframes = timeframes

        self._state_mgr = StateManager(db_path=db_path_app) if db_path_app else StateManager()
        self._settings = self._state_mgr.get_app_settings()

        self.feature_builder = FeatureBuilder()
        # Phase 12: PluginExecutor fuer den Plugin-Modus (aktive Batch-Presets).
        # Der Alt-Pfad (grid_scan / Standard-Scan) bleibt davon unberuehrt.
        self.plugin_executor = PluginExecutor()

        if self.grid_scan:
            # Grid-Proximity Scan (Phase 11): Grid-Levels + ATR als Feature-
            # Basis fuer grid_proximity_v1. Die Grid-Spalten werden zusaetzlich
            # in den feature_store geschrieben (siehe run()).
            self._feature_names: List[str] = ["atr_normalized", "grid_levels"]
            self._feature_params: Dict[str, Dict[str, Any]] = {
                "atr_normalized": {"period": 14},
                "grid_levels": {
                    "step_size": 0.5,
                    "steps_around": 4,
                    "custom_levels": [],
                    "time_window_mins": 5,
                    "use_time_filter": True,
                },
            }
            self._source_id = "grid_proximity_v1"
            self.signals = {
                "grid_proximity_v1": GridProximitySignal(),
            }
            self.evaluator = SetEvaluator(self.signals)
            self.set_config = {
                "signals": [
                    {"id": "grid_proximity_v1", "weight": 1.0, "params": {}},
                ],
                "threshold": 0.5,
            }
        else:
            # Standard-Scan (EMA + ATR)
            self._feature_names = ["ema_diff", "atr_normalized"]
            self._feature_params = {
                "ema_diff": {"fast_period": 12, "slow_period": 26},
                "atr_normalized": {"period": 14},
            }
            self._source_id = "ema_atr_set_v1"
            self.signals = {
                "ema_trend_v1": EMATrendSignal(),
                "atr_filter_v1": ATRFilterSignal(),
            }
            self.evaluator = SetEvaluator(self.signals)
            self.set_config = {
                "signals": [
                    {"id": "ema_trend_v1", "weight": 0.7, "params": {"threshold_pct": 0.3, "max_confidence": 1.0, "direction": "both"}},
                    {"id": "atr_filter_v1", "weight": 0.3, "params": {"threshold_pct": 0.8, "max_confidence": 1.0, "mode": "high_volatility"}},
                ],
                "threshold": 0.5,
            }

    def stop(self):
        self._running = False

    def _get_active_batch_plugins(self) -> List[Dict[str, Any]]:
        """Liefert die aktiven Batch-Presets (is_active_batch = True) aus den
        indicator_presets. Steuert den Plugin-Modus (Phase 12)."""
        try:
            return self._state_mgr.list_active_batch_presets()
        except Exception as e:
            self.log_message.emit(f"Plugin-Presets konnten nicht geladen werden: {e}")
            return []

    def _run_plugin_batch(
        self,
        df_ohlcv,
        tf: str,
        active_plugins: List[Dict[str, Any]],
    ) -> None:
        """Phase 12 Plugin-Modus: Fuehrt alle aktiven Batch-Presets ueber den
        PluginExecutor aus und schreibt den feature_store_payload in den
        feature_store (Hybrid-Spalten feature_id/plugin_version/feature_data).
        Der Alt-Pfad schreibt weiterhin seine nativen Spalten."""
        if df_ohlcv is None or df_ohlcv.empty:
            return
        # Plugin-Vertrag: DataFrame mit 'time'-Spalte (epoch-Sekunden).
        # load_ohlcv() liefert 'bar_time' (datetime) -> hier anpassen.
        df_plugin = prepare_plugin_df(df_ohlcv)
        for preset in active_plugins:
            plugin_id = preset.get("plugin_id")
            if not plugin_id:
                continue
            try:
                result = self.plugin_executor.execute(
                    plugin_id, df_plugin, preset.get("params", {})
                )
            except Exception as e:
                import traceback
                self.log_message.emit(f"  {tf}: Plugin {plugin_id} FEHLER: {e}")
                self.log_message.emit(f"    {traceback.format_exc()}")
                continue
            payload = result.get("feature_store_payload", {}) if isinstance(result, dict) else {}
            if payload:
                try:
                    n = self.feature_builder.store_plugin_payload(self.symbol, tf, payload)
                    self.log_message.emit(
                        f"  {tf}: Plugin {plugin_id}: {n} Feature-Rows im feature_store"
                    )
                except Exception as e:
                    self.log_message.emit(f"  {tf}: Plugin {plugin_id} Store-Fehler: {e}")

    def run(self):
        from pathlib import Path

        from db_service import DbPool

        BASE_DIR = Path(__file__).resolve().parent.parent.parent
        DB_ANALYTICS = self._db_path_analytics or str(BASE_DIR / "data" / "analytics.duckdb")
        DB_MARKET = self._db_path_market or str(BASE_DIR / "data" / "market_data.duckdb")

        # U15-C2 (Zielzustand): Der Plugin-Batch (PluginExecutor) ist der
        # primäre Schreibpfad in den feature_store. Der Alt-Scan (SetEvaluator)
        # bleibt kompatibel – ebenfalls feature_store-only (keine
        # signal_results-Writes, Phase 13 Schritt 7.B).

        feature_names = self._feature_names
        feature_params = self._feature_params
        source_id = self._source_id

        # Phase 12: aktive Batch-Presets (Plugin-Modus) einmal bestimmen
        active_plugins = self._get_active_batch_plugins()

        total_signals = 0
        timeframes = self._timeframes if self._timeframes is not None else list(get_timeframes().keys())
        num_tfs = len(timeframes)

        self.log_message.emit(f"Starte Scan fuer {self.symbol} ueber {num_tfs} Timeframes...")
        if self.new_scan:
            self.log_message.emit("Modus: FULL SCAN (bestehende Signale werden geloescht)")
        else:
            self.log_message.emit("Modus: DELTA UPDATE (nur fehlende Bars)")

        start_time = time.time()

        for idx, tf in enumerate(timeframes):
            if not self._running:
                self.log_message.emit("Scan abgebrochen.")
                return

            self.progress_updated.emit(f"Verarbeite {tf}...", idx, num_tfs)

            try:
                # 1. OHLCV laden
                df_ohlcv = self.feature_builder.load_ohlcv(self.symbol, tf, limit=self._settings.scanner_candle_limit)
                if df_ohlcv.empty:
                    self.log_message.emit(f"  {tf}: Keine OHLCV-Daten, ueberspringe")
                    continue

                # 1b. Plugin-Modus (Phase 12): Aktive Batch-Presets über den
                # PluginExecutor. Nutzt den vollständigen Lookback (Grid-Levels
                # brauchen die volle Preisspanne); das Delta-Update (Schritt 2)
                # betrifft ausschließlich den Alt-Pfad.
                if active_plugins:
                    self._run_plugin_batch(df_ohlcv, tf, active_plugins)

                # 2. Delta-Update: Nur neue Bars scannen
                # (Phase 13 Schritt 7.B: Anker ist der feature_store statt
                # signal_results – es finden keine signal_results-Writes mehr statt.)
                if not self.new_scan:
                    con = DbPool.get(DB_ANALYTICS)
                    last_signal = con.execute("""
                        SELECT MAX(bar_time) FROM feature_store
                        WHERE symbol = ? AND timeframe = ? AND feature_id = ?
                    """, [self.symbol, tf, source_id]).fetchone()[0]

                    if last_signal is not None:
                        df_ohlcv = df_ohlcv[df_ohlcv["bar_time"] > last_signal]
                        if df_ohlcv.empty:
                            self.log_message.emit(f"  {tf}: Keine neuen Bars seit letztem Scan")
                            continue
                        self.log_message.emit(f"  {tf}: {len(df_ohlcv)} neue Bars seit {last_signal}")

                # 3. Features berechnen
                df_features = self.feature_builder.calculate_features(
                    df_ohlcv,
                    feature_names=feature_names,
                    params=feature_params,
                )

                # 3b. Features in den feature_store schreiben (Grid-Scan:
                # Grid-Levels & Zeitfenster-Flags fuer Signal & Chart-Overlay)
                if self.grid_scan:
                    try:
                        self.feature_builder.store_features(self.symbol, tf, df_features)
                    except Exception as e:
                        self.log_message.emit(f"  {tf}: FEHLER beim Feature-Store: {e}")

                # 4. Signal-Set auswerten
                result = self.evaluator.evaluate_set(self.set_config, df_features)

                # 5. Nur Bars mit binaerem Signal uebernehmen
                signals = result[result["signal_binary"] == 1]
                if signals.empty:
                    self.log_message.emit(f"  {tf}: Keine Signale gefunden")
                    continue

                # 6. Hits als feature_store-Records schreiben (feature_id =
                #    source_id). Phase 13 Schritt 7.B: KEINE signal_results
                #    mehr – die Marker/Statistik lesen feature_data.
                records: List[Dict[str, Any]] = []
                for _, row in signals.iterrows():
                    bt = row["bar_time"]
                    records.append({
                        "bar_time": bt,
                        "is_hit": True,
                        "confidence_total": float(row["confidence_total"]),
                        "signal_binary": 1,
                        "source_id": source_id,
                    })

                try:
                    n = self.feature_builder.store_plugin_payload(
                        self.symbol, tf,
                        {"feature_id": source_id, "plugin_version": "1.0.0",
                         "records": records},
                    )
                except Exception as e:
                    n = 0
                    self.log_message.emit(f"  {tf}: FEHLER beim feature_store-Write: {e}")
                self.log_message.emit(f"  {tf}: {n} Hit-Rows in feature_store geschrieben")
                total_signals += n

            except Exception as e:
                self.log_message.emit(f"  {tf}: FEHLER: {e}")
                import traceback
                self.log_message.emit(f"    {traceback.format_exc()}")

        elapsed = time.time() - start_time
        elapsed_str = f"{int(elapsed // 3600):02d}:{int((elapsed % 3600) // 60):02d}:{int(elapsed % 60):02d}"
        self.log_message.emit(f"Scan abgeschlossen in {elapsed_str}")
        self.log_message.emit(f"Gesamt: {total_signals} Signale geschrieben")
        self.progress_updated.emit("Fertig", num_tfs, num_tfs)
        self.scan_finished.emit(self.symbol, total_signals)
