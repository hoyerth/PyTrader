# chart/overlays/signal_overlay.py
"""
Signal-Overlay – Liest Signal-Ergebnisse aus analytics.duckdb und bereitet
sie als Lightweight Charts Marker-Daten für das Chart-Fenster auf.
"""

from typing import Any, Dict, List, Optional
import duckdb
from pathlib import Path

from db_service import DbPool
from state_manager import StateManager

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_ANALYTICS = str(BASE_DIR / "data" / "analytics.duckdb")


class SignalOverlay:
    """
    Liest gefilterte Signale aus signal_results und erstellt Marker-Daten
    für die Darstellung im Lightweight Charts Chart.
    """

    def __init__(self):
        self._current_set_id: Optional[str] = None
        self._state_mgr = StateManager()
        self._settings = self._state_mgr.get_app_settings()

    @property
    def current_set_id(self) -> Optional[str]:
        return self._current_set_id

    def get_available_sets(self) -> List[str]:
        """Liefert alle verfügbaren source_id Werte aus signal_results."""
        if not Path(DB_ANALYTICS).exists():
            return []
        con = DbPool.get(DB_ANALYTICS)
        rows = con.execute("""
            SELECT DISTINCT source_id FROM signal_results
            ORDER BY source_id
        """).fetchall()
        return [r[0] for r in rows]

    def set_active_set(self, set_id: str):
        self._current_set_id = set_id

    def fetch_markers(
        self,
        symbol: str,
        timeframe: str,
        set_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Holt Signale aus signal_results und formatiert sie als Marker.

        Args:
            symbol: Symbol-Name
            timeframe: Timeframe
            set_id: source_id (optional, sonst current_set_id)
            limit: Maximale Anzahl Marker

        Returns:
            Liste von Marker-Dicts für Lightweight Charts:
            [{time, position, color, shape, size, text}, ...]
        """
        if set_id is None:
            set_id = self._current_set_id
        if set_id is None:
            return []

        if limit is None:
            limit = self._settings.signal_marker_limit

        if not Path(DB_ANALYTICS).exists():
            return []

        con = DbPool.get(DB_ANALYTICS)
        # WICHTIG: Subquery mit DESC + äußeres ASC für Lightweight Charts
        # EXTRACT(epoch) direkt in SQL, damit DuckDB TIMESTAMPTZ korrekt verarbeitet
        rows = con.execute("""
            SELECT EXTRACT('epoch' FROM bar_time)::BIGINT AS time_epoch,
                   confidence, metadata_payload
            FROM (
                SELECT bar_time, confidence, metadata_payload
                FROM signal_results
                WHERE symbol = ? AND timeframe = ? AND source_id = ?
                ORDER BY bar_time DESC
                LIMIT ?
            )
            ORDER BY bar_time ASC
        """, [symbol, timeframe, set_id, limit]).fetchall()

        markers = []
        for row in rows:
            time_sec = row[0]
            if time_sec is None or time_sec <= 0:
                continue

            confidence = float(row[1]) if row[1] is not None else 0.5

            # Farbe basierend auf Confidence
            if confidence >= 0.8:
                color = "#26a69a"  # Grün (stark)
            elif confidence >= 0.5:
                color = "#FFEB3B"  # Gelb (mittel)
            else:
                color = "#ef5350"  # Rot (schwach)

            markers.append({
                "time": time_sec,
                "position": "aboveBar",
                "color": color,
                "shape": "arrowDown",
                "size": 1,
                "text": f"{confidence:.0%}",
            })

        return markers
