# analytics/statistics_repository.py
"""
Statistics Repository – SQL-Aggregations-Queries auf signal_results + Forward-Performance.
"""

from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import duckdb
import pandas as pd

from db_service import DbPool

BASE_DIR = Path(__file__).resolve().parent.parent
DB_ANALYTICS = str(BASE_DIR / "data" / "analytics.duckdb")
DB_MARKET = str(BASE_DIR / "data" / "market_data.duckdb")


class StatisticsRepository:
    """Kapselt alle SQL-Zugriffe für das Statistik-Fenster."""

    def get_available_sets(self) -> List[str]:
        """Liefert alle verfuegbaren source_id Werte."""
        if not Path(DB_ANALYTICS).exists():
            return []
        con = DbPool.get(DB_ANALYTICS)
        rows = con.execute("""
                SELECT DISTINCT source_id FROM signal_results
                ORDER BY source_id
            """).fetchall()
        return [r[0] for r in rows]

    def get_summary(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Aggregierte Kennzahlen ueber signal_results.

        Returns:
            Dict mit total_signals, avg_confidence, win_rate, best_tf
        """
        if not Path(DB_ANALYTICS).exists():
            return {"total_signals": 0, "avg_confidence": 0.0, "win_rate": 0.0, "best_tf": "-"}

        conditions = []
        params = []
        if symbol and symbol != "ALLE":
            conditions.append("sr.symbol = ?")
            params.append(symbol)
        if timeframe and timeframe != "ALLE":
            conditions.append("sr.timeframe = ?")
            params.append(timeframe)
        if source_id:
            conditions.append("sr.source_id = ?")
            params.append(source_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        con = DbPool.get(DB_ANALYTICS)
        # Gesamtzahl und avg confidence
        row = con.execute(f"""
            SELECT
                COUNT(*) AS total,
                COALESCE(AVG(sr.confidence), 0.0) AS avg_conf
            FROM signal_results sr
            WHERE {where_clause}
        """, params).fetchone()
        total = int(row[0]) if row[0] else 0
        avg_conf = float(row[1]) if row[1] else 0.0

        # Bester Timeframe (meiste Signale)
        row_tf = con.execute(f"""
            SELECT sr.timeframe, COUNT(*) AS cnt
            FROM signal_results sr
            WHERE {where_clause}
            GROUP BY sr.timeframe
            ORDER BY cnt DESC
            LIMIT 1
        """, params).fetchone()
        best_tf = str(row_tf[0]) if row_tf else "-"

        # Win-Rate via Forward-Performance (naechste 10 Bars)
        win_rate = self._calc_win_rate(con, where_clause, params)

        return {
            "total_signals": total,
            "avg_confidence": round(avg_conf, 4),
            "win_rate": round(win_rate, 1),
            "best_tf": best_tf,
        }

    def _calc_win_rate(
        self,
        con: duckdb.DuckDBPyConnection,
        where_clause: str,
        params: List[Any],
    ) -> float:
        """
        Berechnet exemplarische Win-Rate (vereinfacht, performant).
        Nutzt den durchschnittlichen Confidence-Score als Proxy.
        Ein Signal gilt als "Win", wenn confidence > 0.7.
        """
        try:
            row = con.execute(f"""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE sr.confidence >= 0.7) AS wins
                FROM signal_results sr
                WHERE {where_clause}
            """, params).fetchone()

            total = int(row[0]) if row[0] else 0
            wins = int(row[1]) if row[1] else 0

            if total == 0:
                return 0.0
            return (wins / total) * 100.0
        except Exception as e:
            print(f"⚠️ [StatisticsRepository] Win-Rate Fehler: {e}")
            return 0.0

    def fetch_signals(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        Detailierte Signalliste fuer die Tabelle.

        Returns:
            Liste von Dicts mit time, symbol, timeframe, source_id, confidence, outcome
        """
        if not Path(DB_ANALYTICS).exists():
            return []

        conditions = []
        params = []
        if symbol and symbol != "ALLE":
            conditions.append("sr.symbol = ?")
            params.append(symbol)
        if timeframe and timeframe != "ALLE":
            conditions.append("sr.timeframe = ?")
            params.append(timeframe)
        if source_id:
            conditions.append("sr.source_id = ?")
            params.append(source_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        con = DbPool.get(DB_ANALYTICS)
        try:
            rows = con.execute(f"""
                SELECT
                    sr.bar_time,
                    sr.symbol,
                    sr.timeframe,
                    sr.source_id,
                    sr.confidence
                FROM signal_results sr
                WHERE {where_clause}
                ORDER BY sr.bar_time DESC
                LIMIT ?
            """, params + [limit]).fetchall()
        except Exception as e:
            print(f"⚠️ [StatisticsRepository] fetch_signals Fehler: {e}")
            return []

        results = []
        for row in rows:
            bar_time = row[0]
            symbol_val = str(row[1])
            tf_val = str(row[2])
            source = str(row[3])
            confidence = float(row[4]) if row[4] is not None else 0.0

            # Outcome basierend auf Confidence
            if confidence >= 0.7:
                outcome = "Win"
            elif confidence >= 0.5:
                outcome = "Neutral"
            else:
                outcome = "Loss"

            # Zeitstempel
            if hasattr(bar_time, 'timestamp'):
                time_sec = int(bar_time.timestamp())
            else:
                time_sec = int(bar_time)

            results.append({
                "time": time_sec,
                "symbol": symbol_val,
                "timeframe": tf_val,
                "source_id": source,
                "confidence": confidence,
                "outcome": outcome,
            })

        return results
