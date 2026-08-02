# chart/overlays/signal_overlay.py
"""
Signal-Overlay – Liest Marker-Daten aus analytics.duckdb und bereitet sie
als Lightweight Charts Marker-Daten für das Chart-Fenster auf.

Phase 13 Schritt 7: Die Grid-Proximity-Marker kommen aus den NEUEN
Feature-Store-Daten (feature_store.feature_data der Proximity-Services,
feature_id='proximity'). Da die feature_store-Tabelle KEINE set_id-Spalte
hat, ist das 'Set' im neuen Datenmodell die feature_id (Plugin-Identität).

Hybrid-Pfad (Rückwärtskompatibilität):
  - set_id entspricht einer feature_id im feature_store (z. B. 'proximity')
    → Marker werden aus feature_data gebaut (Proximity-Hits).
  - set_id ist eine Legacy-Set-ID aus signal_results (z. B. 'ema_atr_set_v1')
    → Fallback auf signal_results (Alt-Pfad, bleibt bis zum Rückbau aktiv).
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
    Liest Marker aus feature_data (Proximity-Services) – mit Fallback auf
    signal_results für Legacy-Set-IDs – für die Darstellung im Chart.
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

        Phase 13 Schritt 7: Quelle sind die feature_data-Einträge der
        Proximity-Services (feature_id IS NOT NULL + feature_data gefüllt) –
        NICHT mehr `SELECT DISTINCT source_id FROM signal_results`.
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
        Holt Marker aus den Feature-Store-Daten (Hybrid-Pfad).

        Phase 13 Schritt 7:
          - set_id = feature_id (z. B. 'proximity') → Marker aus feature_data
            (nur Bars mit is_hit=true; Farbe nach in_time_window).
          - set_id = Legacy-Set-ID (nur in signal_results) → Fallback auf
            signal_results (Alt-Pfad, bleibt bis zum Rückbau erhalten).

        Args:
            symbol: Symbol-Name
            timeframe: Timeframe
            set_id: feature_id bzw. source_id (optional, sonst current_set_id)
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

        # Neuer Pfad: set_id als feature_id im feature_store vorhanden?
        feature_row = con.execute("""
            SELECT COUNT(*) FROM feature_store
            WHERE feature_id = ? AND symbol = ? AND timeframe = ?
              AND feature_data IS NOT NULL
        """, [set_id, symbol, timeframe]).fetchone()
        if feature_row and feature_row[0] and feature_row[0] > 0:
            return self._fetch_markers_from_feature_data(
                con, symbol, timeframe, set_id, limit)

        # Legacy-Fallback: signal_results (source_id) – Alt-Pfad
        return self._fetch_markers_from_signal_results(
            con, symbol, timeframe, set_id, limit)

    def _fetch_markers_from_feature_data(
        self,
        con: duckdb.DuckDBPyConnection,
        symbol: str,
        timeframe: str,
        feature_id: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Baut Marker aus feature_data (Proximity-Hits, is_hit=true).

        WICHTIG: Subquery mit DESC + äußeres ASC für Lightweight Charts;
        EXTRACT(epoch) direkt in SQL, damit DuckDB TIMESTAMPTZ korrekt
        verarbeitet. Farbe: Hit im nativen UTC-Zeitfenster → grün,
        außerhalb → fuchsia (konsistent zur Proximity-Hit-Semantik).
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

            levels = data.get("levels_hit") or []
            in_window = bool(data.get("in_time_window"))
            color = "#26a69a" if in_window else "#E91E63"  # grün / fuchsia

            markers.append({
                "time": time_sec,
                "position": "aboveBar",
                "color": color,
                "shape": "circle",
                "size": 1,
                "text": str(len(levels)),
            })

        return markers

    def _fetch_markers_from_signal_results(
        self,
        con: duckdb.DuckDBPyConnection,
        symbol: str,
        timeframe: str,
        source_id: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Legacy-Pfad: Marker aus signal_results (Alt-Signal-Mechanik).

        Bleibt bis zum Rückbau der Signal-Mechanik erhalten (Phase 13
        Schritt 7.2.3: erst nach manuellem User-Test deaktivieren).
        """
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
        """, [symbol, timeframe, source_id, limit]).fetchall()

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
