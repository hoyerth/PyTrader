# chart/overlays/signal_overlay.py
"""
Signal-Overlay – Liest Marker-Daten aus analytics.duckdb und bereitet sie
als Lightweight Charts Marker-Daten für das Chart-Fenster auf.

Phase 13 Schritt 7: Die Marker kommen aus den Feature-Store-Daten
(feature_store.feature_data, feature_id = Plugin-Identität).
Phase 13 Schritt 7.B: Rückbau der Alt-Signal-Mechanik abgeschlossen –
der Legacy-Fallback auf signal_results wurde ENTFERNT; es gibt nur noch
den feature_store-Pfad.
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
    Liest Marker aus feature_data (feature_id = Plugin-Identität) für die
    Darstellung im Chart. Kein signal_results-Fallback mehr (Phase 13 7.B).
    """

    def __init__(self):
        self._current_set_id: Optional[str] = None
        self._state_mgr = StateManager()
        self._settings = self._state_mgr.get_app_settings()

    @property
    def current_set_id(self) -> Optional[str]:
        return self._current_set_id

    def get_available_sets(self) -> List[str]:
        """Liefert alle verfügbaren Sets aus den Feature-Store-Daten.

        Phase 13 Schritt 7: Quelle sind die feature_data-Einträge
        (feature_id IS NOT NULL + feature_data gefüllt) – NICHT mehr
        `SELECT DISTINCT source_id FROM signal_results`.
        Das 'Set' = feature_id (die feature_store-Tabelle hat keine set_id).
        """
        if not Path(DB_ANALYTICS).exists():
            return []
        con = DbPool.get(DB_ANALYTICS)
        rows = con.execute("""
            SELECT DISTINCT feature_id
            FROM feature_store
            WHERE feature_id IS NOT NULL AND feature_data IS NOT NULL
            ORDER BY feature_id
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
        Holt Marker aus den Feature-Store-Daten (feature_id).

        Phase 13 Schritt 7.B: Nur noch feature_store – der Legacy-Fallback
        auf signal_results wurde entfernt. set_id = feature_id.

        Args:
            symbol: Symbol-Name
            timeframe: Timeframe
            set_id: feature_id (optional, sonst current_set_id)
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
        return self._fetch_markers_from_feature_data(
            con, symbol, timeframe, set_id, limit)

    def _fetch_markers_from_feature_data(
        self,
        con: duckdb.DuckDBPyConnection,
        symbol: str,
        timeframe: str,
        feature_id: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Baut Marker aus feature_data (is_hit=true).

        WICHTIG: Subquery mit DESC + äußeres ASC für Lightweight Charts;
        EXTRACT(epoch) direkt in SQL, damit DuckDB TIMESTAMPTZ korrekt
        verarbeitet.

        Zwei Record-Typen (Phase 13 7.B, nach Rückbau der Alt-Mechanik):
          - Proximity-Records (feature_id='proximity' bzw. grid-Proximity):
            besitzen levels_hit + in_time_window → Text = Anzahl getroffener
            Levels, Farbe grün (im nativen UTC-Zeitfenster) / fuchsia.
          - EMA/ATR-Records (z. B. feature_id='ema_atr_set_v1'): besitzen
            KEIN levels_hit/in_time_window → confidence-basierte Farbe und
            Text = Confidence-Prozent.
        """
        rows = con.execute("""
            SELECT EXTRACT('epoch' FROM bar_time)::BIGINT AS time_epoch,
                   feature_data
            FROM (
                SELECT bar_time, feature_data
                FROM feature_store
                WHERE symbol = ? AND timeframe = ? AND feature_id = ?
                  AND feature_data IS NOT NULL
                ORDER BY bar_time DESC
                LIMIT ?
            )
            ORDER BY bar_time ASC
        """, [symbol, timeframe, feature_id, limit]).fetchall()

        markers = []
        for row in rows:
            time_sec = row[0]
            if time_sec is None or time_sec <= 0:
                continue

            data = row[1] or {}
            # DuckDB liefert JSON-Spalten als String – ggf. parsen.
            if isinstance(data, str):
                try:
                    import json
                    data = json.loads(data) or {}
                except (ValueError, TypeError):
                    data = {}
            if not data.get("is_hit"):
                continue

            levels = data.get("levels_hit")
            in_window = bool(data.get("in_time_window"))
            confidence = float(data.get("confidence_total") or 0.0)

            if levels is not None:
                # Proximity-Record: Anzahl getroffener Levels + Zeitfenster
                text = str(len(levels))
                color = "#26a69a" if in_window else "#E91E63"  # grün / fuchsia
            else:
                # EMA/ATR-Record (Phase 13 7.B): Confidence-basierte Farbe
                if confidence >= 0.8:
                    color = "#26a69a"   # Grün (stark)
                elif confidence >= 0.5:
                    color = "#FFEB3B"   # Gelb (mittel)
                else:
                    color = "#ef5350"   # Rot (schwach)
                text = f"{confidence:.0%}"

            markers.append({
                "time": time_sec,
                "position": "aboveBar",
                "color": color,
                "shape": "circle",
                "size": 1,
                "text": text,
            })

        return markers
