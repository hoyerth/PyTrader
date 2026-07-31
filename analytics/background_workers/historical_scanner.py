# analytics/background_workers/historical_scanner.py
"""
Historical Scanner – QThread-Worker für Batch-Scans über historische Daten.
Unterstützt Full-Scan (Delete + Re-Scan) und Delta-Update (fehlende Bars).
"""

import time
from typing import Any, Dict, List, Optional, Set
from PySide6.QtCore import QThread, Signal

from analytics.features.feature_builder import FeatureBuilder
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

    def __init__(self, symbol: str, new_scan: bool = False, grid_scan: bool = False, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self.new_scan = new_scan
        self.grid_scan = grid_scan
        self._running = True
        self._state_mgr = StateManager()
        self._settings = self._state_mgr.get_app_settings()

        self.feature_builder = FeatureBuilder()

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

    def run(self):
        import duckdb
        import pandas as pd
        import uuid
        from pathlib import Path

        from db_service import DbPool

        BASE_DIR = Path(__file__).resolve().parent.parent.parent
        DB_ANALYTICS = str(BASE_DIR / "data" / "analytics.duckdb")
        DB_MARKET = str(BASE_DIR / "data" / "market_data.duckdb")

        feature_names = self._feature_names
        feature_params = self._feature_params
        source_id = self._source_id

        total_signals = 0
        timeframes = list(get_timeframes().keys())
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

                # 2. Delta-Update: Nur neue Bars scannen
                if not self.new_scan:
                    con = DbPool.get(DB_ANALYTICS)
                    last_signal = con.execute("""
                        SELECT MAX(bar_time) FROM signal_results
                        WHERE symbol = ? AND timeframe = ? AND source_id = ?
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

                # 6. In signal_results schreiben
                con = DbPool.get(DB_ANALYTICS)
                # Bei Full-Scan: Alte Signale loeschen (nur fuer diese source_id)
                if self.new_scan:
                    con.execute("""
                        DELETE FROM signal_results
                        WHERE symbol = ? AND timeframe = ? AND source_id = ?
                    """, [self.symbol, tf, source_id])

                # Neue Signale vorbereiten
                from datetime import timezone, datetime as _dt
                rows_to_insert = []
                for _, row in signals.iterrows():
                    bt = row["bar_time"]
                    # pandas Timestamp -> timezone-aware datetime UTC
                    if hasattr(bt, "to_pydatetime"):
                        bt_dt = bt.to_pydatetime().replace(tzinfo=timezone.utc)
                    elif isinstance(bt, (int, float)):
                        bt_dt = _dt.fromtimestamp(int(bt), tz=timezone.utc)
                    else:
                        bt_dt = bt
                    rows_to_insert.append((
                        str(uuid.uuid4()),
                        self.symbol,
                        tf,
                        bt_dt,
                        source_id,
                        float(row["confidence_total"]),
                        "historical_batch",
                        '{}',
                    ))

                if rows_to_insert:
                    con.executemany("""
                        INSERT INTO signal_results (event_id, symbol, timeframe, bar_time, source_id, confidence, context_type, metadata_payload)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, rows_to_insert)

                self.log_message.emit(f"  {tf}: {len(rows_to_insert)} Signale geschrieben")
                total_signals += len(rows_to_insert)

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
