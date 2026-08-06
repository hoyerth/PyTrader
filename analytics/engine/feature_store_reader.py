# analytics/engine/feature_store_reader.py
"""
feature_store_reader.py - FeatureStoreReader (Phase 15.03).

Reiner Lese-Zugriff auf die `feature_store`-Tabelle in `analytics.duckdb`
(Invariante 4 / MVVM: DuckDB -> FeatureStoreReader -> AnalyticsRepository
-> ViewModel -> UI). Der Reader fuehrt KEINE Berechnungen aus und schreibt
NIE in die DB – er kapselt ausschliesslich lesende DuckDB-Abfragen.

Datenmodell feature_store (Hybrid-Schema, Phasen 12+):
    symbol, timeframe, bar_time TIMESTAMPTZ, ema_diff, rsi_14,
    atr_normalized, created_at, feature_id, plugin_version,
    feature_data JSON (FeatureStorePayload des Plugins)

Wanduhr-Garantie (Invariante 7, 15.03-Spez: Heatmap X/Y):
    Die gespeicherten bar_time-Werte sind Berlin-Wanduhr-encoded (MT5
    liefert Wanduhr-Epochs, die 1:1 als UTC-Darstellung in die DB
    geschrieben werden; EXTRACT('epoch' FROM bar_time) liefert exakt diese
    Wanduhr-Epochs). Fuer Wochentag/Stunde (Heatmap) wird DAHER die
    UTC-Forcierung `bar_time AT TIME ZONE 'UTC'` verwendet – OHNE sie
    rechnet DuckDB in die System-Lokalzeit um (Berlin +2h/+1h) und die
    Heatmap waere um den Offset verschoben (DST-bruchig, Invariante 7).

E-3 (schema_version-Pflichtfeld): Alte feature_store-Rows ohne
`schema_version` in feature_data erhalten beim Lesen den Default `"1.0.0"` –
die DB-Zeile bleibt unveraendert (Lesen ist rein).
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from db_service import DbPool, _parse_json_field

# Projekt-Root = 2 Ebenen ueber dieser Datei (engine/ -> analytics/ -> Root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_ANALYTICS = str(BASE_DIR / "data" / "analytics.duckdb")

# E-3 (Phase 15.04, harmonisiert): schema_version-Default fuer Alt-Rows ohne
# Pflichtfeld. 15.04 vereinheitlicht den Default auf "1.0.0" (dreistellig,
# Semantic Versioning major.minor.patch) – identisch zum Plugin-Vertrag
# (grid_lines/proximity/metadata) und zur base_plugin-Spezifikation.
# Zuvor stand hier "1.0" (zweistellig) – Reader-Default und Plugin-Vertrag
# sind seit 15.04 deckungsgleich.
SCHEMA_VERSION_DEFAULT = "1.0.0"

# Native Feature-Spalten der feature_store-Tabelle (fuer Heatmap-Metriken,
# Scatter-/Verteilungs-Achsen). Keine JSON-Feld-Pfade – nur echte Spalten.
NATIVE_COLUMNS = ("ema_diff", "rsi_14", "atr_normalized")

# Heatmap-Achsen (15.03-Spezifikation): X = Wochentage, Y = Tagesstunden
# Berlin Wanduhr. Matrix: rows = Stunde (0-23), cols = DOW (0=Sonntag..6).
DOW_LABELS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"]
HOURS_PER_DAY = 24
DAYS_PER_WEEK = 7


class FeatureStoreReader:
    """Kapselt rein lesend DuckDB-Abfragen auf den feature_store."""

    def __init__(self, db_path: str = DB_ANALYTICS) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Interna
    # ------------------------------------------------------------------
    def _get_connection(self):
        return DbPool.get(self.db_path)

    @staticmethod
    def _normalize_feature_data(raw: Any) -> Dict[str, Any]:
        """Parst feature_data (str->dict) und stellt schema_version sicher.

        E-3: Fehlt das Pflichtfeld `schema_version` (Alt-Rows), wird es beim
        Lesen additiv mit dem Default `"1.0.0"` ergaenzt – die DB-Zeile bleibt
        unveraendert (rein lesender Reader).
        """
        data = _parse_json_field(raw) or {}
        data = dict(data)
        data.setdefault("schema_version", SCHEMA_VERSION_DEFAULT)
        return data

    @staticmethod
    def _epoch_of(bar_time: Any) -> int:
        """Wandelt bar_time (datetime/epoch) in die Wanduhr-Epoch (int) um.

        Verwendet .timestamp() auf der UTC-Darstellung – das liefert exakt
        die gespeicherte Wanduhr-encoded Epoch (konsistent zum Chart und zu
        statistics_repository.fetch_signals).
        """
        if hasattr(bar_time, "timestamp"):
            return int(bar_time.timestamp())
        return int(bar_time)

    @staticmethod
    def _apply_feature_filter(
        feature_ids: Optional[List[str]],
        feature_id: Optional[str],
        conditions: List[str],
        params: List[Any],
    ) -> None:
        """Erweitert WHERE um einen feature_id-Filter (IN-Clause bzw. Einzel-ID).

        15.03-E (Multi-Select): Bevorzugt wird `feature_ids` – die
        Analytics-Engine filtert per `WHERE feature_id IN (...)` ueber alle
        gewaehlten Datenquellen. Der Legacy-Parameter `feature_id` bleibt
        fuer Alt-Aufrufer (z. B. test/check_p15_s4_infra.py) erhalten.
        Leere Liste/None = KEIN Filter (alle Rows).
        """
        ids = [str(i) for i in (feature_ids or []) if str(i).strip()]
        if ids:
            placeholders = ", ".join("?" for _ in ids)
            conditions.append(f"feature_id IN ({placeholders})")
            params.extend(ids)
        elif feature_id:
            conditions.append("feature_id = ?")
            params.append(feature_id)

    # ------------------------------------------------------------------
    # Lesen: Roh-Zeilen
    # ------------------------------------------------------------------
    def fetch_rows(
        self,
        symbol: str,
        timeframe: str,
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Liefert Feature-Store-Zeilen als Dicts (zeilen-aufwaerts sortiert).

        Jede Zeile enthaelt:
            time          – Wanduhr-Epoch (int, bar_time)
            symbol/timeframe – Filterwerte
            feature_id    – Plugin-ID (oder None)
            plugin_version– Plugin-Version (oder None)
            ema_diff/rsi_14/atr_normalized – native Spalten (oder None)
            feature_data  – geparstes JSON inkl. schema_version-Default (E-3)

        Args:
            symbol: Symbol-Name (case-insensitive)
            timeframe: Timeframe (case-insensitive)
            feature_id: Optionaler Einzel-Filter auf die Plugin-ID (Legacy)
            feature_ids: Optionaler Multi-Filter (15.03-E) – filtert per
                `feature_id IN (...)`. Leere Liste/None = kein Filter.
            limit: Maximale Anzahl Zeilen (Default 1000)
        """
        if not symbol or not timeframe:
            return []
        if limit is None:
            limit = 1000
        conditions = ["LOWER(symbol) = LOWER(?)", "LOWER(timeframe) = LOWER(?)"]
        params: List[Any] = [symbol, timeframe]
        self._apply_feature_filter(feature_ids, feature_id, conditions, params)

        con = self._get_connection()
        try:
            rows = con.execute(f"""
                SELECT
                    bar_time,
                    symbol,
                    timeframe,
                    feature_id,
                    plugin_version,
                    ema_diff,
                    rsi_14,
                    atr_normalized,
                    feature_data
                FROM feature_store
                WHERE {' AND '.join(conditions)}
                ORDER BY bar_time ASC
                LIMIT ?
            """, params + [limit]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_rows fehlgeschlagen: {e}")
            return []

        out: List[Dict[str, Any]] = []
        for r in rows:
            out.append({
                "time": self._epoch_of(r[0]),
                "symbol": str(r[1]),
                "timeframe": str(r[2]),
                "feature_id": str(r[3]) if r[3] is not None else None,
                "plugin_version": str(r[4]) if r[4] is not None else None,
                "ema_diff": self._float_or_none(r[5]),
                "rsi_14": self._float_or_none(r[6]),
                "atr_normalized": self._float_or_none(r[7]),
                "feature_data": self._normalize_feature_data(r[8]),
            })
        return out

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        """Konvertiert einen DB-Wert in float (None/ungueltig -> None)."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Lesen: Gezielte Spalten (Scatter / Verteilung)
    # ------------------------------------------------------------------
    def fetch_columns(
        self,
        symbol: str,
        timeframe: str,
        columns: List[str],
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, float]]:
        """Liefert nur die angeforderten nativen Spalten (non-null).

        Args:
            symbol/timeframe: Filter (case-insensitive)
            columns: Nur native Spalten (ema_diff, rsi_14, atr_normalized)
            feature_id: Optionaler Einzel-Filter auf die Plugin-ID (Legacy)
            feature_ids: Optionaler Multi-Filter (15.03-E) per
                `feature_id IN (...)`. Leere Liste/None = kein Filter.
            limit: Maximale Zeilen (Default 1000)

        Returns:
            Liste von Dicts {spaltenname: float, ...} – Zeilen mit NULL in
            einer angeforderten Spalte werden ausgelassen (Scatter/Histogramm).
        """
        if not symbol or not timeframe or not columns:
            return []
        valid = [c for c in columns if c in NATIVE_COLUMNS]
        if not valid:
            return []
        if limit is None:
            limit = 1000
        col_sql = ", ".join(f'"{c}"' for c in valid)
        conditions = ["LOWER(symbol) = LOWER(?)", "LOWER(timeframe) = LOWER(?)"]
        params: List[Any] = [symbol, timeframe]
        self._apply_feature_filter(feature_ids, feature_id, conditions, params)

        con = self._get_connection()
        try:
            rows = con.execute(f"""
                SELECT {col_sql}
                FROM feature_store
                WHERE {' AND '.join(conditions)}
                  AND {" AND ".join(f'"{c}" IS NOT NULL' for c in valid)}
                ORDER BY bar_time ASC
                LIMIT ?
            """, params + [limit]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_columns fehlgeschlagen: {e}")
            return []

        out: List[Dict[str, float]] = []
        for r in rows:
            item: Dict[str, float] = {}
            ok = True
            for i, c in enumerate(valid):
                fv = self._float_or_none(r[i])
                if fv is None:
                    ok = False
                    break
                item[c] = fv
            if ok:
                out.append(item)
        return out

    # ------------------------------------------------------------------
    # Lesen: Heatmap (2D-Matrix X=Wochentag, Y=Stunde, Berlin Wanduhr)
    # ------------------------------------------------------------------
    def fetch_heatmap(
        self,
        symbol: str,
        timeframe: str,
        metric: str = "count",
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Aggregiert eine 2D-Matrix (X: Wochentage, Y: Tagesstunden).

        Wanduhr-Garantie (Invariante 7): DOW/HOUR werden mit
        `bar_time AT TIME ZONE 'UTC'` extrahiert – die gespeicherten Werte
        sind Wanduhr-encoded, die UTC-Darstellung ist die Wanduhr-Zeit.
        Ohne die Forcierung rechnet DuckDB in die System-Lokalzeit (Berlin
        +2h/+1h) um und die Heatmap waere DST-bruchig verschoben.

        Args:
            symbol/timeframe: Filter (case-insensitive)
            metric: "count" (Anzahl Zeilen je Zelle) ODER eine native Spalte
                (ema_diff, rsi_14, atr_normalized) -> AVG je Zelle.
            feature_id: Optionaler Einzel-Filter auf die Plugin-ID (Legacy)
            feature_ids: Optionaler Multi-Filter (15.03-E) per
                `feature_id IN (...)`. Leere Liste/None = kein Filter.
            limit: Optionaler Deckel (nur fuer konsistente Semantik; die
                Aggregation erfolgt in SQL ueber den Filter).

        Returns:
            {
              "matrix":   7x24 Liste (rows=Stunde 0-23, cols=DOW 0=So..6=Sa),
                          count -> 0 fuer leere Zellen,
                          avg   -> nan fuer leere Zellen (numpy),
              "x_labels": DOW_LABELS (Wochentage, Spalten),
              "y_labels": ["00:00", ..., "23:00"] (Stunden, Zeilen),
              "metric":   metric,
              "symbol":   symbol, "timeframe": timeframe,
            }

        Raises:
            ValueError: bei unbekannter Metrik (nur count / native Spalten).
        """
        if not symbol or not timeframe:
            return self._empty_heatmap(symbol, timeframe, metric)
        metric_key = str(metric).lower()
        if metric_key == "count":
            agg_sql = "COUNT(*) AS val"
        elif metric_key in NATIVE_COLUMNS:
            agg_sql = f'AVG("{metric_key}") AS val'
        else:
            raise ValueError(
                f"[FeatureStoreReader] Unbekannte Heatmap-Metrik '{metric}' – "
                f"erlaubt: 'count' oder eine native Spalte {NATIVE_COLUMNS}."
            )

        conditions = ["LOWER(symbol) = LOWER(?)", "LOWER(timeframe) = LOWER(?)"]
        params: List[Any] = [symbol, timeframe]
        self._apply_feature_filter(feature_ids, feature_id, conditions, params)

        con = self._get_connection()
        try:
            rows = con.execute(f"""
                SELECT
                    EXTRACT(DOW FROM bar_time AT TIME ZONE 'UTC')::INTEGER AS dow,
                    EXTRACT(HOUR FROM bar_time AT TIME ZONE 'UTC')::INTEGER AS hour,
                    {agg_sql}
                FROM feature_store
                WHERE {' AND '.join(conditions)}
                GROUP BY 1, 2
                ORDER BY 1, 2
            """, params).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_heatmap fehlgeschlagen: {e}")
            return self._empty_heatmap(symbol, timeframe, metric)

        # Matrix: rows=Stunde (0-23), cols=DOW (0-6). count -> 0, avg -> nan.
        fill = 0.0 if metric_key == "count" else float("nan")
        matrix = np.full((HOURS_PER_DAY, DAYS_PER_WEEK), fill, dtype=float)
        for r in rows:
            dow = int(r[0])
            hour = int(r[1])
            val = r[2]
            if 0 <= dow < DAYS_PER_WEEK and 0 <= hour < HOURS_PER_DAY and val is not None:
                matrix[hour][dow] = float(val)

        return {
            "matrix": matrix.tolist(),
            "x_labels": list(DOW_LABELS),
            "y_labels": [f"{h:02d}:00" for h in range(HOURS_PER_DAY)],
            "metric": metric,
            "symbol": symbol,
            "timeframe": timeframe,
        }

    def _empty_heatmap(
        self, symbol: str, timeframe: str, metric: str
    ) -> Dict[str, Any]:
        """Leere Heatmap (keine Daten / Fehler / fehlende Filter)."""
        fill = 0.0 if str(metric).lower() == "count" else float("nan")
        return {
            "matrix": np.full(
                (HOURS_PER_DAY, DAYS_PER_WEEK), fill, dtype=float
            ).tolist(),
            "x_labels": list(DOW_LABELS),
            "y_labels": [f"{h:02d}:00" for h in range(HOURS_PER_DAY)],
            "metric": metric,
            "symbol": symbol,
            "timeframe": timeframe,
        }

    # ------------------------------------------------------------------
    # Lesen: Datum der letzten Ausfuehrung (MasterTree, 05.08.2026)
    # ------------------------------------------------------------------
    def fetch_last_execution_dates(self) -> Dict[str, str]:
        """Neuester Schreib-Zeitpunkt je feature_id – formatiert als 'DD.MM.JJ'.

        Wird vom ServiceSelectorModel fuer die MasterTree-Anzeige
        'Service_Name (DD.MM.JJ)' gelesen (Datum der letzten Ausfuehrung).
        Quelle: MAX(created_at) je feature_id ueber ALLE Symbole/Timeframes.
        store_plugin_payload() aktualisiert created_at bei jedem Upsert
        (ON CONFLICT DO UPDATE), damit der Zeitstempel die LETZTE Ausfuehrung
        widerspiegelt (nicht den Erst-Schreibzeitpunkt der Bar).

        Robustheit (Bugfix 05.08.2026, Punkt 1):
          * Case-insensitiv: feature_id wird per LOWER(TRIM(...)) normalisiert –
            Registry-/Plugin-IDs (z.B. 'proximity') werden unabhaengig von der
            in der DB gespeicherten Gross-/Kleinschreibung gefunden.
          * Whitespace-tolerant: fuehrende/trailing Leerzeichen (z.B. durch
            Alt-Schreibpfade) werden ignoriert.
          * Defensiv: Zeilen mit NULL/leerer feature_id ODER NULL created_at
            werden uebersprungen (Alt-Rows ohne Zeitstempel koennen kein
            gueltiges Datum liefern).

        Returns:
            Dict feature_id (lower) -> 'DD.MM.JJ' (z.B. {'proximity': '05.08.26'});
            leer bei fehlender DB/Tabelle oder Fehler (defensiv).
        """
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT LOWER(TRIM(feature_id)) AS fid, MAX(created_at)
                FROM feature_store
                WHERE feature_id IS NOT NULL AND TRIM(feature_id) != ''
                GROUP BY LOWER(TRIM(feature_id))
            """).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_last_execution_dates "
                  f"fehlgeschlagen: {e}")
            return {}
        out: Dict[str, str] = {}
        for r in rows:
            if r[0] is None or r[1] is None:
                continue
            try:
                out[str(r[0])] = r[1].strftime("%d.%m.%y")
            except (AttributeError, ValueError):
                continue
        return out

    # ------------------------------------------------------------------
    # Lesen: Metadaten
    # ------------------------------------------------------------------
    def get_available_timeframes(self, symbol: str) -> List[str]:
        """Liefert die Timeframes mit Feature-Store-Daten fuer ein Symbol.

        Dient der TF-Combo-Ausgrauung (15.03-Fix): Timeframes ohne Daten im
        feature_store werden in der UI ausgegraut und sind nicht auswaehlbar.

        Returns:
            Liste der Timeframe-Strings (z. B. ["M1", "H1", ...]) – leer,
            wenn das Symbol keine Feature-Daten hat.
        """
        if not symbol:
            return []
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT DISTINCT timeframe FROM feature_store
                WHERE LOWER(symbol) = LOWER(?)
                ORDER BY timeframe
            """, [symbol]).fetchall()
            return [str(r[0]) for r in rows if r[0] is not None]
        except Exception as e:
            print(f"WARN [FeatureStoreReader] get_available_timeframes "
                  f"fehlgeschlagen: {e}")
            return []

    def get_available_features(
        self, symbol: str, timeframe: str
    ) -> Dict[str, Any]:
        """Liefert verfuegbare Plugin-IDs, native Spalten und Zeilenzahl.

        Returns:
            {"feature_ids": [...], "columns": [...], "total_rows": int}
        """
        con = self._get_connection()
        try:
            ids = [r[0] for r in con.execute("""
                SELECT DISTINCT feature_id FROM feature_store
                WHERE feature_id IS NOT NULL AND feature_id != ''
                ORDER BY feature_id
            """).fetchall()]
            total = con.execute("""
                SELECT COUNT(*) FROM feature_store
                WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
            """, [symbol, timeframe]).fetchone()
            total = int(total[0]) if total and total[0] is not None else 0
        except Exception as e:
            print(f"WARN [FeatureStoreReader] get_available_features "
                  f"fehlgeschlagen: {e}")
            return {"feature_ids": [], "columns": list(NATIVE_COLUMNS),
                    "total_rows": 0}
        return {
            "feature_ids": [str(i) for i in ids],
            "columns": list(NATIVE_COLUMNS),
            "total_rows": total,
        }

    # ------------------------------------------------------------------
    # Lesen: Jump-to-Chart-Helfer (15.03 Schritt 5, open_chart_at_bar)
    # ------------------------------------------------------------------
    def fetch_latest_bar_time(
        self,
        symbol: str,
        timeframe: str,
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch (int) der Feature-Rows (oder None).

        Wird fuer 'Jump-to-Chart' (Variante 2) aus Scatter/Heatmap genutzt:
        Ein Klick auf einen Punkt/eine Zelle oeffnet das Chart-Fenster an der
        zugehoerigen Bar-Position. Wanduhr-Garantie: EXTRACT('epoch') liefert
        exakt die gespeicherte Wanduhr-Epoch (Invariante 7).

        15.03-E (Multi-Select): Ueber `feature_ids` wird der neueste
        bar_time ueber ALLE gewaehlten Datenquellen gesucht (OR-Semantik).
        """
        if not symbol or not timeframe:
            return None
        conditions = ["LOWER(symbol) = LOWER(?)", "LOWER(timeframe) = LOWER(?)"]
        params: List[Any] = [symbol, timeframe]
        self._apply_feature_filter(feature_ids, feature_id, conditions, params)
        con = self._get_connection()
        try:
            row = con.execute(f"""
                SELECT EXTRACT('epoch' FROM MAX(bar_time))::BIGINT
                FROM feature_store
                WHERE {' AND '.join(conditions)}
            """, params).fetchone()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_latest_bar_time "
                  f"fehlgeschlagen: {e}")
            return None
        if row and row[0] is not None:
            return int(row[0])
        return None

    def fetch_recent_bar_time_for_cell(
        self,
        symbol: str,
        timeframe: str,
        dow: int,
        hour: int,
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch einer (dow, hour)-Heatmap-Zelle (oder None).

        Jump-to-Chart aus der Heatmap: Ein Doppelklick auf eine Zelle
        (Wochentag x Tagesstunde) oeffnet das Chart an der neuesten
        Feature-Bar dieser Zelle. DOW/HOUR werden mit
        `bar_time AT TIME ZONE 'UTC'` extrahiert (Wanduhr-Garantie,
        Invariante 7 – identisch zu fetch_heatmap).

        15.03-E (Multi-Select): Ueber `feature_ids` wird die Zelle ueber
        ALLE gewaehlten Datenquellen abgefragt (OR-Semantik).
        """
        if not symbol or not timeframe:
            return None
        try:
            dow = int(dow)
            hour = int(hour)
        except (TypeError, ValueError):
            return None
        if not (0 <= dow < DAYS_PER_WEEK and 0 <= hour < HOURS_PER_DAY):
            return None
        conditions = [
            "LOWER(symbol) = LOWER(?)",
            "LOWER(timeframe) = LOWER(?)",
            "EXTRACT(DOW FROM bar_time AT TIME ZONE 'UTC')::INTEGER = ?",
            "EXTRACT(HOUR FROM bar_time AT TIME ZONE 'UTC')::INTEGER = ?",
        ]
        params: List[Any] = [symbol, timeframe, dow, hour]
        self._apply_feature_filter(feature_ids, feature_id, conditions, params)
        con = self._get_connection()
        try:
            row = con.execute(f"""
                SELECT EXTRACT('epoch' FROM MAX(bar_time))::BIGINT
                FROM feature_store
                WHERE {' AND '.join(conditions)}
            """, params).fetchone()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_recent_bar_time_for_cell "
                  f"fehlgeschlagen: {e}")
            return None
        if row and row[0] is not None:
            return int(row[0])
        return None

    def exists(self) -> bool:
        """True, wenn die analytics.duckdb-Datei existiert."""
        return os.path.exists(self.db_path)
