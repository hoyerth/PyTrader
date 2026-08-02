# analytics/statistics_repository.py
"""
Statistics Repository – SQL-Aggregations-Queries auf feature_data
(Proximity-Services, feature_id='proximity') + Forward-Performance.

Phase 13 Schritt 7: Die Statistik liest die Treffer-Records künftig aus
dem feature_store (feature_data der Proximity-Services) statt aus
signal_results. statistic_win.py bleibt API-stabil – es ändert sich nur
die Datenquelle, nicht das Fenster.

Da die feature_store-Tabelle KEINE set_id-Spalte hat, ist das 'Set' im
neuen Datenmodell die feature_id (Plugin-Identität, z. B. 'proximity').
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
        """Liefert alle verfügbaren Sets aus den Feature-Store-Daten.

        Phase 13 Schritt 7: Quelle sind die feature_data-Einträge der
        Proximity-Services (feature_id IS NOT NULL + feature_data gefüllt).
        """
        if not Path(DB_ANALYTICS).exists():
            return []
        con = DbPool.get(DB_ANALYTICS)
        rows = con.execute("""
                SELECT DISTINCT feature_id FROM feature_store
                WHERE feature_id IS NOT NULL AND feature_data IS NOT NULL
                ORDER BY feature_id
            """).fetchall()
        return [r[0] for r in rows]

    def get_summary(
        self,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Aggregierte Kennzahlen über feature_data (Proximity-Hits).

        Returns:
            Dict mit total_signals (Hit-Bars), avg_confidence (Hit-Fraktion
            0..1), win_rate (% der Hits im nativen Zeitfenster), best_tf.
        """
        if not Path(DB_ANALYTICS).exists():
            return {"total_signals": 0, "avg_confidence": 0.0, "win_rate": 0.0, "best_tf": "-"}

        conditions = ["feature_data IS NOT NULL"]
        params = []
        if symbol and symbol != "ALLE":
            conditions.append("LOWER(symbol) = LOWER(?)")
            params.append(symbol)
        if timeframe and timeframe != "ALLE":
            conditions.append("LOWER(timeframe) = LOWER(?)")
            params.append(timeframe)
        if source_id:
            conditions.append("feature_id = ?")
            params.append(source_id)

        where_clause = " AND ".join(conditions)

        con = DbPool.get(DB_ANALYTICS)
        # Gesamtzahl Bars + Hit-Bars (is_hit=true in feature_data)
        row = con.execute(f"""
            SELECT
                COUNT(*) AS total_bars,
                COUNT(*) FILTER (WHERE CAST(feature_data['is_hit'] AS BOOLEAN)) AS hit_bars
            FROM feature_store
            WHERE {where_clause}
        """, params).fetchone()
        total_bars = int(row[0]) if row[0] else 0
        hit_bars = int(row[1]) if row[1] else 0

        # avg_confidence = Hit-Fraktion über alle gescannten Bars (0..1)
        avg_conf = (hit_bars / total_bars) if total_bars else 0.0

        # Win-Rate: % der Hits im nativen UTC-Zeitfenster (in_time_window)
        win_rate = self._calc_win_rate(con, where_clause, params)

        # Bester Timeframe (meiste Hits)
        row_tf = con.execute(f"""
            SELECT timeframe, COUNT(*) AS cnt
            FROM feature_store
            WHERE {where_clause}
              AND CAST(feature_data['is_hit'] AS BOOLEAN)
            GROUP BY timeframe
            ORDER BY cnt DESC
            LIMIT 1
        """, params).fetchone()
        best_tf = str(row_tf[0]) if row_tf else "-"

        return {
            "total_signals": hit_bars,
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
        Berechnet die Win-Rate als Qualitäts-Proxy: Anteil der Hit-Bars,
        die im nativen UTC-Zeitfenster (in_time_window=true) liegen.
        """
        try:
            row = con.execute(f"""
                SELECT
                    COUNT(*) FILTER (WHERE CAST(feature_data['is_hit'] AS BOOLEAN)) AS total,
                    COUNT(*) FILTER (WHERE CAST(feature_data['is_hit'] AS BOOLEAN)
                                     AND CAST(feature_data['in_time_window'] AS BOOLEAN)) AS wins
                FROM feature_store
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
        Detailierte Signalliste für die Tabelle – aus feature_data.

        Returns:
            Liste von Dicts mit time, symbol, timeframe, source_id (feature_id),
            confidence (Hit-Intensität 0..1), outcome (Win/Neutral).
        """
        if not Path(DB_ANALYTICS).exists():
            return []

        conditions = ["feature_data IS NOT NULL"]
        params = []
        if symbol and symbol != "ALLE":
            conditions.append("LOWER(symbol) = LOWER(?)")
            params.append(symbol)
        if timeframe and timeframe != "ALLE":
            conditions.append("LOWER(timeframe) = LOWER(?)")
            params.append(timeframe)
        if source_id:
            conditions.append("feature_id = ?")
            params.append(source_id)

        where_clause = " AND ".join(conditions)

        con = DbPool.get(DB_ANALYTICS)
        try:
            rows = con.execute(f"""
                SELECT
                    bar_time,
                    symbol,
                    timeframe,
                    feature_id,
                    CAST(feature_data['is_hit'] AS BOOLEAN) AS is_hit,
                    CAST(feature_data['in_time_window'] AS BOOLEAN) AS in_window,
                    COALESCE(json_array_length(feature_data['levels_hit']), 0) AS n_levels
                FROM feature_store
                WHERE {where_clause}
                  AND CAST(feature_data['is_hit'] AS BOOLEAN)
                ORDER BY bar_time DESC
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
            source = str(row[3]) if row[3] else ""
            n_levels = int(row[6]) if row[6] else 0
            in_window = bool(row[5])

            # Hit-Intensität: je getroffenes Level +0.25 (max. 1.0)
            confidence = min(1.0, n_levels * 0.25)

            # Outcome als Qualitäts-Proxy: Hit im nativen Zeitfenster = Win
            outcome = "Win" if in_window else "Neutral"

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
