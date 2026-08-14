# repositories/grabber_repository.py
from typing import List

import pandas as pd

from analytics.engine.peak_models import GrabberResultRecord
from db_service import DB_ANALYTICS, DbPool


class GrabberRepository:
    """Kapselt den DB-Zugriff auf grabber_test_results (MVVM, Präambel 4/6)."""

    def __init__(self, db_path: str = DB_ANALYTICS) -> None:
        self.db_path = db_path

    _COLS = [
        "signal_id", "run_id", "timestamp", "symbol", "timeframe",
        "direction", "entry_price", "sl_price", "peak_price",
        "peak_bar_index", "is_update", "reversal_pct",
        "is_yellow_window", "gate_source", "outcome_status",
        "pnl_r_multiple", "max_favorable_exc", "max_adverse_exc",
    ]

    def save_records(self, records: List[GrabberResultRecord]) -> int:
        """Batch-Upsert (18 Spalten, B1). ON CONFLICT aktualisiert nur
        die Outcome-Felder (nachlaufende Serientest-Bewertung)."""
        if not records:
            return 0
        rows = [
            (
                r.signal_id, r.run_id, r.timestamp, r.symbol, r.timeframe,
                r.direction.value, r.entry_price, r.sl_price, r.peak_price,
                r.peak_bar_index, r.is_update, r.reversal_pct,
                r.is_yellow_window, r.gate_source, r.outcome_status,
                r.pnl_r_multiple, r.max_favorable_exc, r.max_adverse_exc,
            )
            for r in records
        ]
        con = DbPool.get(self.db_path)
        df = pd.DataFrame(rows, columns=self._COLS)
        con.register("df_grabber", df)
        cols = ", ".join(self._COLS)
        try:
            con.execute(f"""
                INSERT INTO grabber_test_results ({cols})
                SELECT {cols} FROM df_grabber
                ON CONFLICT (signal_id) DO UPDATE SET
                    outcome_status = EXCLUDED.outcome_status,
                    pnl_r_multiple = EXCLUDED.pnl_r_multiple,
                    max_favorable_exc = EXCLUDED.max_favorable_exc,
                    max_adverse_exc = EXCLUDED.max_adverse_exc
            """)
        finally:
            con.unregister("df_grabber")
        return len(rows)

    def fetch_records(self, run_id: str) -> List[dict]:
        con = DbPool.get(self.db_path)
        rows = con.execute(
            "SELECT * FROM grabber_test_results WHERE run_id = ? "
            "ORDER BY timestamp", [run_id]).fetchall()
        cols = [d[0] for d in con.description]
        return [dict(zip(cols, r)) for r in rows]

    def delete_run(self, run_id: str) -> int:
        con = DbPool.get(self.db_path)
        res = con.execute(
            "DELETE FROM grabber_test_results WHERE run_id = ?",
            [run_id])
        return len(res.fetchall() or [])
