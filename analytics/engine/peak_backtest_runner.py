# analytics/engine/peak_backtest_runner.py
"""
peak_backtest_runner.py - Serientests / Backtest-Orchestrierung (22.01).

Headless Runner: ohlcv -> grid/prox + peak-Services -> DB (PENDING/NULL).
Laeuft in einem Worker nach dem `ServiceRunWorker`-Muster (Pr�ambel 9),
ohne UI-Importe (SRP - Rule 2.3).

Pipeline (Frage 3): grid_1 -> prox_1 (Zone-Hits in shared_state) ->
peak_1 -> grab_1. Der Service `srv_peak_grabber` leitet `is_yellow_window`
selbst her (Fallback True ohne Proximity-Signal, Frage 3).

Frage 4: Outcome bleibt PENDING-Platzhalter (Exit-/Forward-Evaluation folgt
in einem spaeteren Kapitel als separates Auswertungs-Modul).
"""
import uuid
from datetime import datetime
from typing import List, Optional

import pandas as pd

from analytics.engine.peak_models import (
    GrabberResultRecord,
    PeakConfig,
    PeakGrabberConfig,
    SignalDirection,
)
from analytics.engine.set_evaluator import ServiceSetEvaluator
from analytics.features.feature_builder import (
    PluginExecutor,
    prepare_plugin_df,
)
from analytics.features.plugins.base_plugin import PluginContext
from repositories.grabber_repository import GrabberRepository


class PeakBacktestRunner:
    """Serientest: ohlcv -> grid/prox + peak-Services -> DB (PENDING/NULL)."""

    def __init__(self) -> None:
        self.executor = PluginExecutor()
        self.evaluator = ServiceSetEvaluator(self.executor)
        self.repo = GrabberRepository()

    def _load_ohlcv(self, symbol: str, timeframe: str,
                    limit: Optional[int]) -> Optional[pd.DataFrame]:
        from analytics.features.feature_builder import FeatureBuilder
        df = FeatureBuilder().load_ohlcv(symbol, timeframe, limit)
        return prepare_plugin_df(df)

    def run_series(
        self,
        symbol: str,
        timeframe: str,
        cfg: PeakGrabberConfig,
        peak_cfg: PeakConfig = PeakConfig(),
        limit: Optional[int] = None,
    ) -> List[GrabberResultRecord]:
        df = self._load_ohlcv(symbol, timeframe, limit)
        if df is None or df.empty:
            return []

        # Frage 3: grid_1 -> prox_1 (Zone-Hits in shared_state) -> peak_1 ->
        # grab_1. Der Service srv_peak_grabber leitet is_yellow_window selbst
        # her.
        definition = {
            "set_id": "peak_backtest_internal",
            "display_name": "Peak Backtest (intern)",
            "execution_order": ["grid_1", "prox_1", "peak_1", "grab_1"],
            "services": {
                "grid_1": {
                    "plugin_id": "srv_grid_lines",
                    "lookback": int(limit or len(df)),
                    "params": {"step_size": 0.5, "steps_around": 4},
                },
                "prox_1": {
                    "plugin_id": "srv_proximity",
                    "lookback": int(limit or len(df)),
                    "depends_on": ["grid_1"],
                    "params": {
                        "visit_pct": 0.05,
                        "time_window_mins": 5,   # Frage 3: +/-5 min um :00/:30
                        "use_time_filter": True,
                    },
                },
                "peak_1": {
                    "plugin_id": "srv_peak_finder",
                    "lookback": int(limit or len(df)),
                    "params": {"sl_offset_pct": peak_cfg.sl_offset_pct},
                },
                "grab_1": {
                    "plugin_id": "srv_peak_grabber",
                    "lookback": int(limit or len(df)),
                    "depends_on": ["peak_1", "prox_1"],
                    "params": {
                        "reversal_pct": cfg.reversal_pct,
                        "min_hold_bars": cfg.min_hold_bars,
                        "invalidation_bars": cfg.invalidation_bars,
                        "invalidation_threshold_pct": cfg.invalidation_threshold_pct,
                        "require_proximity_window": cfg.require_proximity_window,
                        "sl_offset_pct": peak_cfg.sl_offset_pct,
                    },
                },
            },
        }
        context = PluginContext(symbol=symbol, timeframe=timeframe,
                                mode="batch")
        results = self.evaluator.execute_set(definition, df, context)
        grab_recs = ((results.get("grab_1") or {}).get(
            "feature_store_payload") or {}).get("records") or []

        # Schnellzugriff: bar_time (epoch) -> Zeilen-Index (kein index()-Scan)
        times = df["time"].to_numpy()
        idx_by_time = {int(t): i for i, t in enumerate(times)}

        run_id = f"BT-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        records: List[GrabberResultRecord] = []
        for r in grab_recs:
            sig = int(r["signal"])
            is_upd = abs(sig) == 2
            i = idx_by_time.get(int(r["bar_time"]))
            if i is None:
                continue
            rec = GrabberResultRecord(
                signal_id=str(uuid.uuid4()),  # stabil (kein hash(), B: Pythons
                # hash() ist pro Prozess randomisiert)
                run_id=run_id,
                timestamp=pd.Timestamp(int(r["bar_time"]),
                                       unit="s").to_pydatetime(),  # B7
                symbol=symbol,
                timeframe=timeframe,
                direction=SignalDirection.BUY if sig > 0 else SignalDirection.SELL,
                entry_price=float(df.iloc[i]["close"]),
                sl_price=float(r["sl_price"]),
                peak_price=float(r["peak_price"]),
                peak_bar_index=i,
                is_update=is_upd,
                reversal_pct=(0.0 if is_upd else abs(
                    float(df.iloc[i]["close"]) - float(r["peak_price"]))
                    / float(r["peak_price"]) * 100.0),
                is_yellow_window=bool(r["is_yellow_window"]),
                gate_source="SERIES_UPDATE" if is_upd else "SERIES_TRIGGER",
                # Frage 4: Outcome bleibt PENDING-Platzhalter (spaeteres Modul)
                outcome_status="PENDING",
                pnl_r_multiple=None,
                max_favorable_exc=None,
                max_adverse_exc=None,
            )
            records.append(rec)
        self.repo.save_records(records)
        return records
