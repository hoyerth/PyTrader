# analytics/background_workers/historical_scanner.py
"""
Historical Scanner – QThread-Worker für Batch-Scans über historische Daten.

Phase 15 (Alt-Signal-Rückbau): Der Alt-Scan (grid_scan / Standard-Scan über
SetEvaluator mit ema_atr_set_v1 / grid_proximity_v1) wurde komplett entfernt –
es gibt keine Signal-Engine und keine signal_results-Writes mehr. Der Scanner
führt ausschließlich den PLUGIN-BATCH aus: aktive Batch-Presets aus
`indicator_presets` werden über den PluginExecutor ausgeführt und schreiben
ihre Ergebnisse in den feature_store (feature_data, feature_id = Plugin).
"""

import time
from typing import Any, Dict, List, Optional
from PySide6.QtCore import QThread, Signal

from analytics.features.feature_builder import FeatureBuilder, PluginExecutor, prepare_plugin_df
from db_service import get_timeframes
from state_manager import StateManager


class HistoricalScanner(QThread):
    """Scannt historische Daten für ein Symbol über alle Timeframes (Plugin-Batch)."""

    progress_updated = Signal(str, int, int)  # message, current, total
    scan_finished = Signal(str, int)          # symbol, total_feature_rows
    log_message = Signal(str)                 # log text

    def __init__(
        self,
        symbol: str,
        new_scan: bool = False,
        parent=None,
        db_path_app: Optional[str] = None,
        db_path_analytics: Optional[str] = None,
        db_path_market: Optional[str] = None,
        timeframes: Optional[List[str]] = None,
    ):
        super().__init__(parent)
        self.symbol = symbol
        self.new_scan = new_scan
        self._running = True
        # Override-Pfade (Test/Isolation) – None = Produktions-DBs
        self._db_path_app = db_path_app
        self._db_path_analytics = db_path_analytics
        self._db_path_market = db_path_market
        self._timeframes = timeframes

        self._state_mgr = StateManager(db_path=db_path_app) if db_path_app else StateManager()
        self._settings = self._state_mgr.get_app_settings()

        self.feature_builder = FeatureBuilder()
        # PluginExecutor fuer den Plugin-Batch (aktive Batch-Presets).
        self.plugin_executor = PluginExecutor()

    def stop(self):
        self._running = False

    def _get_active_batch_plugins(self) -> List[Dict[str, Any]]:
        """Liefert die aktiven Batch-Presets (is_active_batch = True) aus den
        indicator_presets. Steuert den Plugin-Batch."""
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
    ) -> int:
        """Fuehrt alle aktiven Batch-Presets ueber den PluginExecutor aus und
        schreibt den feature_store_payload in den feature_store (Hybrid-Spalten
        feature_id/plugin_version/feature_data).

        Returns:
            Anzahl der geschriebenen Feature-Rows (summiert ueber alle Plugins).
        """
        if df_ohlcv is None or df_ohlcv.empty:
            return 0
        # Plugin-Vertrag: DataFrame mit 'time'-Spalte (epoch-Sekunden).
        # load_ohlcv() liefert 'bar_time' (datetime) -> hier anpassen.
        df_plugin = prepare_plugin_df(df_ohlcv)
        total_rows = 0
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
                    total_rows += n
                    self.log_message.emit(
                        f"  {tf}: Plugin {plugin_id}: {n} Feature-Rows im feature_store"
                    )
                except Exception as e:
                    self.log_message.emit(f"  {tf}: Plugin {plugin_id} Store-Fehler: {e}")
        return total_rows

    def run(self):
        # Phase 12: aktive Batch-Presets (Plugin-Batch) einmal bestimmen
        active_plugins = self._get_active_batch_plugins()

        total_rows = 0
        timeframes = self._timeframes if self._timeframes is not None else list(get_timeframes().keys())
        num_tfs = len(timeframes)

        self.log_message.emit(f"Starte Plugin-Batch fuer {self.symbol} ueber {num_tfs} Timeframes...")
        if not active_plugins:
            self.log_message.emit(
                "Keine aktiven Batch-Presets (is_active_batch) gefunden – "
                "nichts zu tun. Aktiviere zuerst einen Batch-Service in den "
                "Indikator-Einstellungen."
            )
            self.progress_updated.emit("Fertig", num_tfs, num_tfs)
            self.scan_finished.emit(self.symbol, 0)
            return
        if self.new_scan:
            self.log_message.emit("Modus: FULL SCAN (kompletter Neuaufbau der Feature-Rows)")
        else:
            self.log_message.emit("Modus: DELTA UPDATE (Upsert, fehlende Bars werden ergaenzt)")

        start_time = time.time()

        for idx, tf in enumerate(timeframes):
            if not self._running:
                self.log_message.emit("Scan abgebrochen.")
                return

            self.progress_updated.emit(f"Verarbeite {tf}...", idx, num_tfs)

            try:
                df_ohlcv = self.feature_builder.load_ohlcv(self.symbol, tf, limit=self._settings.scanner_candle_limit)
                if df_ohlcv.empty:
                    self.log_message.emit(f"  {tf}: Keine OHLCV-Daten, ueberspringe")
                    continue

                total_rows += self._run_plugin_batch(df_ohlcv, tf, active_plugins)

            except Exception as e:
                self.log_message.emit(f"  {tf}: FEHLER: {e}")
                import traceback
                self.log_message.emit(f"    {traceback.format_exc()}")

        elapsed = time.time() - start_time
        elapsed_str = f"{int(elapsed // 3600):02d}:{int((elapsed % 3600) // 60):02d}:{int(elapsed % 60):02d}"
        self.log_message.emit(f"Scan abgeschlossen in {elapsed_str}")
        self.log_message.emit(f"Gesamt: {total_rows} Feature-Rows geschrieben")
        self.progress_updated.emit("Fertig", num_tfs, num_tfs)
        self.scan_finished.emit(self.symbol, total_rows)
