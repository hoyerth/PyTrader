# analytics/engine/feature_store_reader.py
"""
feature_store_reader.py - FeatureStoreReader (Phase 15.03).

Reiner Lese-Zugriff auf die `feature_store`-Tabelle in `analytics.duckdb`
(Invariante 4 / MVVM: DuckDB -> FeatureStoreReader -> AnalyticsRepository
-> ViewModel -> UI). Der Reader fuehrt KEINE Berechnungen aus und schreibt
NIE in die DB – er kapselt ausschliesslich lesende DuckDB-Abfragen.

Datenmodell feature_store (Hybrid-Schema, Phasen 12+; 19.02-Cleanup):
    symbol, timeframe, bar_time TIMESTAMPTZ, created_at, feature_id,
    plugin_version, feature_data JSON (FeatureStorePayload des Plugins)

19.02 (Cleanup): Die Legacy-Native-Spalten ema_diff/rsi_14/atr_normalized
sind entfernt. Scatter-/Verteilungs-/Heatmap-Achsen und Tabellen-Spalten
werden rein dynamisch aus den JSON-Keys von `feature_data` abgeleitet
(`available_feature_keys()`); es gibt KEINE nativen Spalten mehr.

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
import threading
import time
from datetime import datetime as _dt_datetime
from datetime import timezone as _dt_timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from db_service import DbPool, _parse_json_field

# Projekt-Root = 2 Ebenen ueber dieser Datei (engine/ -> analytics/ -> Root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_ANALYTICS = str(BASE_DIR / "data" / "analytics.duckdb")
# 20.02 (E9, Candle-Overlay): OHLCV-Quelle fuer den Preis-Strip – read-only
# via DbPool, analog FeatureBuilder.load_ohlcv() (Spalten time/open/high/
# low/close/tick_volume).
DB_MARKET = str(BASE_DIR / "data" / "market_data.duckdb")

# E-3 (Phase 15.04, harmonisiert): schema_version-Default fuer Alt-Rows ohne
# Pflichtfeld. 15.04 vereinheitlicht den Default auf "1.0.0" (dreistellig,
# Semantic Versioning major.minor.patch) – identisch zum Plugin-Vertrag
# (srv_grid_lines/srv_proximity/metadata) und zur base_plugin-Spezifikation.
# Zuvor stand hier "1.0" (zweistellig) – Reader-Default und Plugin-Vertrag
# sind seit 15.04 deckungsgleich.
SCHEMA_VERSION_DEFAULT = "1.0.0"

# 17.01 (E-1, 07.08.2026): Sentinel feature_id fuer native Feature-Builder-Rows
# (ohne Plugin). Seit der PK-Migration (symbol, timeframe, bar_time,
# feature_id) tragen sie feature_id='native' und werden in allen UI-Listen
# (feature_ids / letzte Ausfuehrung) ausgeblendet.
SENTINEL_NATIVE = "native"

# 19.02 (Cleanup): NATIVE_COLUMNS ENTFERNT – die Legacy-Spalten ema_diff/
# rsi_14/atr_normalized existieren nicht mehr im Neuschema. Achsen und
# Metriken (Scatter/Verteilung/Heatmap) werden rein dynamisch aus den
# feature_data-JSON-Keys abgeleitet (available_feature_keys()).

# Heatmap-Achsen (15.03-Spezifikation): X = Wochentage, Y = Tagesstunden
# Berlin Wanduhr. Matrix: rows = Stunde (0-23), cols = DOW (0=Sonntag..6).
DOW_LABELS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"]
# 20.02.01 (E5): Wochentag-Skala strikt Montag-Freitag (DuckDB Mo=1..Fr=5).
DOW_WEEK_LABELS = ("Mo", "Di", "Mi", "Do", "Fr")
HOURS_PER_DAY = 24
DAYS_PER_WEEK = 7

# 20.02 (Generische 2D-Heatmap-Engine, Kapitel 20.02 §2 / Review E4-E6):
# DIM_MAPPINGS – Whitelist fuer die SQL-Dimensionen von fetch_generic_heatmap().
# Wanduhr-Garantie (Invariante 7): dow/hour/date nutzen die
# UTC-Forcierung `bar_time AT TIME ZONE 'UTC'` (die gespeicherten Werte sind
# Wanduhr-encoded; die UTC-Darstellung IST die Wanduhr-Zeit). E4: `date` wird
# WIE dow/hour mit der UTC-Forcierung extrahiert – das Kapitel-Literal
# `CAST(bar_time AS DATE)` waere DST-fragil (Session-TZ Berlin +1/+2h).
# 20.02.01 (E6): `dow_hour` ist ersatzlos entfernt (Kapitel-Vorgabe) – die
# Kombination ist ueber die Dimensionen `dow` (Mo-Fr) und `hour` (Tageszeit)
# abbildbar; Alt-Profil-/Workspace-Werte werden im ViewModel per Sanitizer
# auf "hour" abgebildet.
DIM_MAPPINGS = {
    "date": "CAST(bar_time AT TIME ZONE 'UTC' AS DATE)",
    "dow": "EXTRACT(DOW FROM bar_time AT TIME ZONE 'UTC')::INTEGER",
    "hour": "EXTRACT(HOUR FROM bar_time AT TIME ZONE 'UTC')::INTEGER",
    "timeframe": "LOWER(timeframe)",
    "service_id": "LOWER(feature_id)",
    "symbol": "LOWER(symbol)",
}

# 20.02: Verfuegbare Dimensionen / Aggregationen (UI-Combos, E1/E5).
# 20.02.01 (E6): `dow_hour` entfernt.
HEATMAP_DIMENSIONS = (
    "date", "dow", "hour", "timeframe", "service_id", "symbol",
)
HEATMAP_AGGREGATIONS = (
    "count", "confluence_count", "avg", "sum", "min", "max",
)

# 20.02 (Luecke 5.3-5): Defensiver Pivot-Deckel – die dichte Matrix wird
# begrenzt (date×dow_hour waere 366×168 = 61.488 Zellen).
MAX_HEATMAP_CELLS = 50_000

# 20.02 (E9): Default-Lookback des OHLCV-Snapshots fuer das Candle-Overlay
# (analog DEFAULT_LIMIT 5000 der Analytics-Tabelle; M1 ≈ 3,5 Tage).
OHLCV_SNAPSHOT_LIMIT = 5000

# 20.02-Bugfix (09.08.2026, Punkt 2/User-Meldung): Der kuenstliche
# Limit-Lookback (5000) schnitt die Heatmap-Daten ab (sichtbar waren nur die
# letzten ~4 Tage bei M1). Die generische Heatmap laedt seither ALLE
# verfuegbaren Daten (limit=None, Pivot-Deckel MAX_HEATMAP_CELLS begrenzt die
# Matrix). Das Candle-Overlay aggregiert Tages-Ohlc SQL-seitig ueber bis zu
# DAILY_OHLC_MAX_DAYS Tage (deckt den gesamten Heatmap-Zeitraum ab).
DAILY_OHLC_MAX_DAYS = 4000


class FeatureStoreReader:
    """Kapselt rein lesend DuckDB-Abfragen auf den feature_store."""

    def __init__(self, db_path: str = DB_ANALYTICS) -> None:
        self.db_path = db_path
        # Runde 15 (Ultra-Low-Latency, Performance-Fix 3): In-Memory-Cache
        # der STABILEN Metadaten (feature_data-JSON-Keys je Service,
        # instance_hash-Fakten). Schlüssel = (symbol.lower(), timeframe.lower()).
        # Die Metadaten aendern sich nur bei store_plugin_payload()-Writes –
        # die bestehende `feature_cache_last_invalidated`-Mechanik
        # (feature_builder.py, Invariante 13) markiert solche Writes. Ohne
        # den Cache scannen `available_feature_keys`/`feature_keys_by_service`/
        # `available_instance_hashes`/`plugin_ids_with_hashes` den Store
        # mehrmals pro Update (bis zu 6 Voll-Scans -> Dropdown-Verzoegerung).
        # Thread-Lock, weil der Reader von Worker-Threads gemeinsam genutzt
        # wird (MVVM: ein Repository/Reader pro ViewModel).
        self._meta_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._meta_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Interna: Metadaten-Cache (Runde 15, Performance-Fix 3)
    # ------------------------------------------------------------------
    @staticmethod
    def _meta_key(symbol: str, timeframe: str) -> Tuple[str, str]:
        """Cache-Schluessel (symbol/timeframe normalisiert, case-insensitiv)."""
        return (str(symbol or "").strip().lower(),
                str(timeframe or "").strip().lower())

    def _meta_cache_valid(self, key: Tuple[str, str]) -> bool:
        """True, wenn der Cache-Eintrag fuer (symbol, timeframe) gueltig ist.

        Invalidation (Invariante 13 / P14-03): `feature_cache_last_invalidated`
        wird bei JEDEM `store_plugin_payload()` fuer (symbol, timeframe)
        aktualisiert. Ein Eintrag ist genau dann gueltig, wenn nach seiner
        Erstellung (ts) KEINE Invalidation registriert wurde. Lazy Import
        (kein pandas-Load beim Reader-Modul-Import; feature_builder laedt
        schwergewichtigere Abhaengigkeiten). Fehlt der Mechanismus (Tests/
        Standalone), bleibt der Eintrag bis zur expliziten Invalidation
        gueltig (der Writer-Pfad liegt im selben Prozess und aktualisiert
        die Invalidation IMMER mit).
        """
        entry = self._meta_cache.get(key)
        if entry is None:
            return False
        try:
            from analytics.features.feature_builder import (
                feature_cache_last_invalidated,
            )
            last_inv = feature_cache_last_invalidated(*key)
        except Exception:
            last_inv = None
        return last_inv is None or last_inv < float(entry.get("ts") or 0.0)

    def _meta_get(self, key: Tuple[str, str]) -> Optional[Dict[str, Any]]:
        """Liefert den gueltigen Cache-Eintrag (oder None bei Miss/Stale)."""
        with self._meta_lock:
            if not self._meta_cache_valid(key):
                return None
            return self._meta_cache.get(key)

    def _meta_put(self, key: Tuple[str, str], entry: Dict[str, Any]) -> None:
        """Legt den Cache-Eintrag mit aktuellem Zeitstempel ab."""
        entry["ts"] = time.time()
        with self._meta_lock:
            self._meta_cache[key] = dict(entry)

    def invalidate_meta_cache(
        self, symbol: Optional[str] = None, timeframe: Optional[str] = None
    ) -> None:
        """Loescht den Metadaten-Cache (ganz oder je symbol/timeframe).

        Defensiver Notausgang (z. B. Tests, die ohne
        feature_cache_last_invalidated schreiben). Im Produktivpfad
        invalidiert `store_plugin_payload()` automatisch via Invariante 13.
        """
        with self._meta_lock:
            if symbol is None or timeframe is None:
                self._meta_cache.clear()
                return
            self._meta_cache.pop(self._meta_key(symbol, timeframe), None)

    def _feature_meta_base(
        self, symbol: str, timeframe: str
    ) -> Optional[Dict[str, Any]]:
        """Einmaliger Basis-Scan der feature_store-Metadaten (gedacht).

        Liefert – aus dem Cache ODER frisch per GENAU EINER DuckDB-Abfrage
        (alle 4 Metadaten-Methoden teilen sich diesen Scan; vorher liefen
        bis zu 6 Voll-Scans pro Update):
            {
              "types_by_service": {fid: {key: set(Typ-Str)}},   # ungefiltert
              "hashes_by_service": {fid_lower: set(nicht-leere Hashes)},
              "null_hash_pids":    {fid_lower},  # fids mit NULL-Hash-Zeilen
            }
        None bei fehlender DB/Tabelle oder Fehler (defensiv, wird NICHT
        gecacht – ein spaeter erfolgreicher Versuch bleibt moeglich).

        Semantik identisch zu den bisherigen Einzelabfragen:
          * `schema_version`-Key und leere Keys werden ignoriert (E-3).
          * Rows ohne feature_id landen unter "" (Legacy/native).
          * NULL-Hash-Zeilen = undifferenzierter Alt-Bestand
            (gehoert der plugin_id als Ganzes, Runde 13c).
        """
        if not symbol or not timeframe:
            return None
        key = self._meta_key(symbol, timeframe)
        entry = self._meta_get(key)
        if entry is not None and "types_by_service" in entry:
            return entry
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT DISTINCT feature_id, instance_hash, feature_data
                FROM feature_store
                WHERE LOWER(symbol) = LOWER(?)
                  AND LOWER(timeframe) = LOWER(?)
                  AND feature_data IS NOT NULL
            """, [symbol, timeframe]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] _feature_meta_base "
                  f"fehlgeschlagen: {e}")
            return None

        types_by_service: Dict[str, Dict[str, set]] = {}
        hashes_by_service: Dict[str, set] = {}
        null_hash_pids: Set[str] = set()
        for fid, hash_raw, raw in rows:
            data = self._normalize_feature_data(raw)
            if not isinstance(data, dict):
                continue
            service = str(fid) if fid is not None else ""
            bucket = types_by_service.setdefault(service, {})
            for k, v in data.items():
                if k == "schema_version" or not str(k).strip():
                    continue
                key_str = str(k)
                if isinstance(v, bool):
                    t = "bool"
                elif isinstance(v, (int, float)):
                    t = "num"
                elif v is None:
                    t = "null"
                else:
                    t = "str"
                bucket.setdefault(key_str, set()).add(t)
            # Hash-Zuordnung (nicht-leere Hashes getrennt vom NULL-Bestand).
            svc_l = str(service).strip().lower()
            h_s = str(hash_raw or "").strip()
            if h_s:
                hashes_by_service.setdefault(svc_l, set()).add(h_s)
            else:
                null_hash_pids.add(svc_l)
        entry = {
            "types_by_service": types_by_service,
            "hashes_by_service": hashes_by_service,
            "null_hash_pids": null_hash_pids,
        }
        self._meta_put(key, entry)
        return entry

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
        instance_hashes: Optional[List[str]] = None,
    ) -> None:
        """Erweitert WHERE um einen feature_id-Filter (IN-Clause bzw. Einzel-ID).

        15.03-E (Multi-Select): Bevorzugt wird `feature_ids` – die
        Analytics-Engine filtert per `WHERE feature_id IN (...)` ueber alle
        gewaehlten Datenquellen. Der Legacy-Parameter `feature_id` bleibt
        fuer Alt-Aufrufer (z. B. test/check_p15_s4_infra.py) erhalten.
        Leere Liste/None = KEIN Filter (alle Rows).

        Bugfix 08.08.2026 (Bug 1: 'keine Anzeige ausgewaehlter Services'):
        Der Filter ist case-insensitiv UND whitespace-tolerant –
        `LOWER(TRIM(feature_id))` auf der DB-Spalte sowie `LOWER(TRIM(..))`
        auf den Parameterwerten. Muster: `fetch_last_execution_dates`
        normalisiert bereits so (historisch reale Gross-/Kleinschreibungs-
        und Leerzeichen-Abweichungen zwischen Registry-plugin_ids und
        gespeicherten feature_store-Werten). Vorher matchte die nackte
        `feature_id IN (...)`-Clause bei solchen Abweichungen nichts und
        Tabelle/Heatmap blieben leer.
        """
        ids = [str(i).strip().lower() for i in (feature_ids or [])
               if str(i).strip()]
        if ids:
            placeholders = ", ".join("?" for _ in ids)
            conditions.append(f"LOWER(TRIM(feature_id)) IN ({placeholders})")
            params.extend(ids)
        elif feature_id:
            conditions.append("LOWER(TRIM(feature_id)) = LOWER(TRIM(?))")
            params.append(feature_id)
        # Runde 10 (Bug 1): Varianten-Einschraenkung - werden
        # instance_hashes uebergeben, bleiben NUR die Rows der gewaehlten
        # Varianten (exakter Hash-Match, case-insensitiv) plus Alt-Bestand
        # OHNE Hash (NULL) - letztere gehoeren der plugin_id als Ganzes
        # und werden nie durch die Varianten-Auswahl ausgeblendet.
        if instance_hashes:
            hashes = [str(h).strip().lower() for h in instance_hashes
                      if str(h).strip()]
            if hashes:
                placeholders = ", ".join("?" for _ in hashes)
                conditions.append(
                    f"(instance_hash IS NULL OR "
                    f"LOWER(TRIM(instance_hash)) IN ({placeholders}))")
                params.extend(hashes)

    # ------------------------------------------------------------------
    # Lesen: Roh-Zeilen
    # ------------------------------------------------------------------
    def fetch_rows(
        self,
        symbol: str,
        timeframe: str,
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Liefert Feature-Store-Zeilen als Dicts (vom NEUESTEN Stand abwaerts).

        19.02 (Cleanup): Die Legacy-Native-Spalten ema_diff/rsi_14/
        atr_normalized sind entfernt – jede Zeile enthaelt:
            time          – Wanduhr-Epoch (int, bar_time)
            symbol/timeframe – Filterwerte
            feature_id    – Plugin-ID (oder None)
            plugin_version– Plugin-Version (oder None)
            feature_data  – geparstes JSON inkl. schema_version-Default (E-3)

        Bugfix 08.08.2026 (Vorgabe): Die Zeilen werden mit `ORDER BY bar_time
        DESC` vom NEUESTEN Stand rueckwaerts bis zum `limit` gelesen (neuestes
        Datum zuerst). Vorher stand `ASC` – mit Limit wurden dadurch die
        AELTESTEN Zeilen geliefert (genau das Gegenteil der Vorgabe). Die
        TablePage sortiert die Anzeige zusaetzlich deterministisch absteigend.

        Args:
            symbol: Symbol-Name (case-insensitive)
            timeframe: Timeframe (case-insensitive)
            feature_id: Optionaler Einzel-Filter auf die Plugin-ID (Legacy)
            feature_ids: Optionaler Multi-Filter (15.03-E) – filtert per
                `feature_id IN (...)`. Leere Liste/None = kein Filter.
            limit: Maximale Anzahl Zeilen (Default 1000) – die NEUESTEN
                `limit` Zeilen (rueckwaerts vom neuesten Stand).
        """
        if not symbol or not timeframe:
            return []
        if limit is None:
            limit = 1000
        conditions = ["LOWER(symbol) = LOWER(?)", "LOWER(timeframe) = LOWER(?)"]
        params: List[Any] = [symbol, timeframe]
        self._apply_feature_filter(
            feature_ids, feature_id, conditions, params,
            instance_hashes=instance_hashes)

        con = self._get_connection()
        try:
            rows = con.execute(f"""
                SELECT
                    bar_time,
                    symbol,
                    timeframe,
                    feature_id,
                    plugin_version,
                    feature_data
                FROM feature_store
                WHERE {' AND '.join(conditions)}
                ORDER BY bar_time DESC
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
                "feature_data": self._normalize_feature_data(r[5]),
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
    # Lesen: Dynamische JSON-Keys (Scatter / Verteilung / Heatmap, 19.02)
    # ------------------------------------------------------------------
    @staticmethod
    def _is_json_key_identifier(key: Any) -> bool:
        """True, wenn der JSON-Key ein sicheres DuckDB-Identifier-Format hat.

        Wird fuer SQL-Einbettungen (feature_data->>'key') verwendet – nur
        [A-Za-z_][A-Za-z0-9_]* wird akzeptiert (kein SQL-Injection-/Quoting-
        Risiko). JSON-Keys aus den Service-Payloads sind alle identifier-sicher.
        """
        import re
        return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key or "")))

    @staticmethod
    def _format_dim_value(dim: str, value: Any) -> str:
        """Formatiert einen Dimensions-Rohwert fuer Achsen-Beschriftungen.

        20.02 (generische Heatmap): `date` -> 'TT.MM.', `hour` -> 'HH:00',
        `dow` -> Mo-Fr-Kurzname (20.02.01 E5, DOW_WEEK_LABELS; Sonntag/
        Samstag werden per SQL-Filter ausgeschlossen). Alle anderen
        Dimensionen (timeframe/service_id/symbol) -> Rohwert-String.
        """
        try:
            if dim == "date":
                if hasattr(value, "strftime"):
                    return value.strftime("%d.%m.")
                return str(value)
            if dim == "hour":
                return f"{int(value):02d}:00"
            if dim == "dow":
                v = int(value)
                if 1 <= v <= len(DOW_WEEK_LABELS):
                    return DOW_WEEK_LABELS[v - 1]
                return str(value)
        except (TypeError, ValueError):
            pass
        return str(value)

    @staticmethod
    def _axis_coords(dim: str, values: List[Any]) -> List[float]:
        """Achsen-Koordinaten (natuerliche Werte) je Matrix-Zeile/-Spalte.

        20.02-Bugfix (09.08.2026, Punkte 3-6/User-Meldung): Fuer die
        TradingView-aehnliche Achsen-Darstellung tragen die Achsen die
        NATUERLICHEN Werte statt Zell-Indizes:
          - `date`      -> Wanduhr-Mitternachts-Epoch (Sekunden)
          - hour        -> die ganzzahligen Stunden (0-23)
          - dow         -> 1..5 (Montag-Freitag, 20.02.01 E5)
          - kategorial  -> Indizes 0..n-1 (timeframe/service_id/symbol)
        Das Widget mappt das ImageItem per setRect auf diesen Bereich und
        erzeugt dynamische Ticks je Zoom-Level (bis zur Minute bei Datum).
        """
        if dim == "date":
            out: List[float] = []
            for v in values:
                if isinstance(v, _dt_datetime):
                    out.append(float(int(v.timestamp())))
                elif hasattr(v, "year") and hasattr(v, "month") \
                        and hasattr(v, "day"):
                    # date-Objekt (CAST AS DATE): Mitternacht Wanduhr-UTC
                    out.append(float(int(_dt_datetime(
                        v.year, v.month, v.day,
                        tzinfo=_dt_timezone.utc).timestamp())))
                else:
                    try:
                        out.append(float(int(_dt_datetime.fromisoformat(
                            str(v)).replace(tzinfo=_dt_timezone.utc)
                            .timestamp())))
                    except (TypeError, ValueError):
                        out.append(0.0)
            return out
        if dim in ("hour", "dow"):
            try:
                return [float(int(v)) for v in values]
            except (TypeError, ValueError):
                return [float(i) for i in range(len(values))]
        # Kategorial (timeframe/service_id/symbol): Indizes 0..n-1.
        return [float(i) for i in range(len(values))]

    def available_feature_keys(
        self,
        symbol: str,
        timeframe: str,
        numeric_only: bool = False,
    ) -> List[str]:
        """Union aller feature_data-JSON-Keys (19.02, dynamische Achsen).

        Wertet die DISTINCT-JSON-Strukturen der Rows (symbol/timeframe)
        aus; pro Struktur werden die Keys gesammelt. `schema_version`
        (Pflichtfeld, E-3) wird ignoriert.

        Runde 15 (Performance-Fix 3): Die Auswertung laeuft ueber den
        gemeinsamen Metadaten-Basis-Scan `_feature_meta_base` (EIN Scan fuer
        available_feature_keys/feature_keys_by_service/available_instance_
        hashes/plugin_ids_with_hashes; Invalidation via
        `feature_cache_last_invalidated`, Invariante 13). Ergebnis
        identisch zur bisherigen Einzelabfrage.

        Args:
            symbol/timeframe: Filter (case-insensitive)
            numeric_only: True => nur Keys, deren Wert in ALLEN Vorkommen
                numerisch (int/float, kein bool/str/None) ist – Grundlage
                fuer Scatter-/Verteilungs-Achsen und Heatmap-Metriken.

        Returns:
            Deterministisch sortierte Key-Liste (alphabetisch); leer bei
            fehlender DB/Tabelle oder Fehler (defensiv).
        """
        if not symbol or not timeframe:
            return []
        base = self._feature_meta_base(symbol, timeframe)
        if base is None:
            return []
        key_types: Dict[str, set] = {}
        for bucket in base["types_by_service"].values():
            for k, types in bucket.items():
                key_types.setdefault(k, set()).update(types)
        keys = sorted(key_types.keys())
        if not numeric_only:
            return keys
        # numeric_only: jeder Key muss durchgaengig numerisch (nicht bool/null/str)
        return [k for k in keys if key_types[k] == {"num"}]

    def feature_keys_by_service(
        self,
        symbol: str,
        timeframe: str,
        numeric_only: bool = False,
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
    ) -> Dict[str, List[str]]:
        """feature_data-JSON-Keys je feature_id (20.02.01, Feld-Dropdown).

        Ordnet jedem Service (feature_id) die JSON-Keys zu, die er im
        feature_data liefert – Grundlage fuer das 'Feld'-Dropdown der
        generischen Heatmap ('{Service} / {Key}', User-Meldung 3b). Die
        Typ-Logik ist identisch zu `available_feature_keys`: bei
        `numeric_only=True` muss ein Key in ALLEN Vorkommen des jeweiligen
        Services numerisch sein (int/float, kein bool/null/str).

        09.08.2026 (User-Meldung Feld-Dropdown): Die Zuordnung wird ueber
        `feature_id`/`feature_ids` gefiltert (Muster `fetch_rows`, inkl.
        case-insensitivem + whitespace-tolerantem Filter) – abgewaehlte
        Services liefern ihre Keys NICHT mehr, damit das Feld-Dropdown nur
        noch die tatsaechlich selektierten Datenquellen zeigt.

        Zeilen ohne feature_id (Legacy/native) werden unter "" gruppiert;
        das Repository ignoriert sie (Dropdown-Fallback: Roh-Key ohne
        Service-Prefix).

        Returns:
            {feature_id: [sortierte JSON-Keys...]} – leer bei fehlender
            DB/Tabelle oder Fehler (defensiv, rein lesend).
        """
        if not symbol or not timeframe:
            return {}
        base = self._feature_meta_base(symbol, timeframe)
        if base is None:
            return {}
        types_by_service = base["types_by_service"]
        hashes_by_service = base["hashes_by_service"]
        null_hash_pids = base["null_hash_pids"]
        # 09.08.2026 (User-Meldung Feld-Dropdown): feature_id/feature_ids-
        # Filter anwenden, damit abgewaehlte Services nicht im Dropdown
        # erscheinen (Root Cause 2). Runde 15: Die Filterung erfolgt in
        # Python auf dem gecachten Basis-Scan (identische Semantik zur
        # bisherigen SQL-IN-Clause: case-insensitiv + whitespace-tolerant).
        wanted = {str(i).strip().lower() for i in (feature_ids or [])
                  if str(i).strip()}
        if not wanted and feature_id:
            wanted = {str(feature_id).strip().lower()}
        # Runde 10 (Bug 1): Varianten-Einschraenkung – NULL-Hash-Zeilen
        # (Alt-Bestand) passieren IMMER, sonst muss ein nicht-leerer Hash
        # der gewaehlten Variante treffen (exakter Hash-Match, case-insensitiv).
        hashes = set()
        if instance_hashes:
            hashes = {str(h).strip().lower() for h in instance_hashes
                      if str(h).strip()}

        out: Dict[str, List[str]] = {}
        for service, bucket in types_by_service.items():
            svc_l = str(service).strip().lower()
            if wanted and svc_l not in wanted:
                continue
            if hashes:
                svc_hashes = hashes_by_service.get(svc_l, set())
                if not (svc_l in null_hash_pids or (svc_hashes & hashes)):
                    continue
            keys = sorted(bucket.keys())
            if numeric_only:
                keys = [k for k in keys if bucket[k] == {"num"}]
            if keys:
                out[service] = keys
        return out

    def fetch_columns(
        self,
        symbol: str,
        timeframe: str,
        columns: List[str],
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, float]]:
        """Liefert numerische Werte angeforderter feature_data-JSON-Keys.

        19.02 (Cleanup): Die alten nativen DB-Spalten sind entfernt – die
        Spalten werden stattdessen als JSON-Keys aus `feature_data`
        extrahiert (identische Semantik: Zeilen mit fehlendem/nicht-
        numerischem Wert in einer Spalte werden ausgelassen).

        Bugfix 08.08.2026 (Vorgabe): Wie fetch_rows werden die Zeilen vom
        NEUESTEN Stand rueckwaerts bis zum `limit` gelesen (`ORDER BY
        bar_time DESC`) – vorher ASC (aelteste N Zeilen bei Limit).

        Args:
            symbol/timeframe: Filter (case-insensitive)
            columns: JSON-Keys aus feature_data (nur identifier-sichere)
            feature_id: Optionaler Einzel-Filter auf die Plugin-ID (Legacy)
            feature_ids: Optionaler Multi-Filter (15.03-E) per
                `feature_id IN (...)`. Leere Liste/None = kein Filter.
            limit: Maximale Zeilen (Default 1000) – die NEUESTEN `limit`
                Zeilen (rueckwaerts vom neuesten Stand).

        Returns:
            Liste von Dicts {key: float, ...} – Zeilen mit NULL/nicht-
            numerischem Wert in einer angeforderten Spalte werden
            ausgelassen (Scatter/Histogramm).
        """
        if not symbol or not timeframe or not columns:
            return []
        valid = [str(c) for c in columns if self._is_json_key_identifier(c)]
        if not valid:
            return []
        if limit is None:
            limit = 1000
        conditions = ["LOWER(symbol) = LOWER(?)", "LOWER(timeframe) = LOWER(?)"]
        params: List[Any] = [symbol, timeframe]
        self._apply_feature_filter(
            feature_ids, feature_id, conditions, params,
            instance_hashes=instance_hashes)

        con = self._get_connection()
        try:
            rows = con.execute(f"""
                SELECT feature_data
                FROM feature_store
                WHERE {' AND '.join(conditions)}
                  AND feature_data IS NOT NULL
                ORDER BY bar_time DESC
                LIMIT ?
            """, params + [limit]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_columns fehlgeschlagen: {e}")
            return []

        out: List[Dict[str, float]] = []
        for (raw,) in rows:
            data = self._normalize_feature_data(raw)
            if not isinstance(data, dict):
                continue
            item: Dict[str, float] = {}
            ok = True
            for c in valid:
                v = data.get(c)
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    ok = False
                    break
                item[c] = float(v)
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
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
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
            metric: "count" (Anzahl Zeilen je Zelle) ODER ein numerischer
                feature_data-JSON-Key (19.02) -> AVG je Zelle (z. B.
                'grid_nearest_level', 'visit_pct').
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
            ValueError: bei unbekannter Metrik (nur 'count' / identifier-
                sichere JSON-Keys).
        """
        if not symbol or not timeframe:
            return self._empty_heatmap(symbol, timeframe, metric)
        metric_key = str(metric).lower()
        if metric_key == "count":
            agg_sql = "COUNT(*) AS val"
        elif self._is_json_key_identifier(metric_key):
            # 19.02 (Cleanup): Metrik = JSON-Key aus feature_data – AVG ueber
            # die numerischen Werte. TRY_CAST liefert NULL fuer fehlende/nicht-
            # numerische Werte; AVG ignoriert NULLs (wie bisher bei nativen
            # Spalten mit NULL-Zellen).
            agg_sql = (
                f"AVG(TRY_CAST(feature_data->>'{metric_key}' AS DOUBLE)) AS val"
            )
        else:
            raise ValueError(
                f"[FeatureStoreReader] Unbekannte Heatmap-Metrik '{metric}' – "
                f"erlaubt: 'count' oder ein numerischer JSON-Key des "
                f"feature_data."
            )

        conditions = ["LOWER(symbol) = LOWER(?)", "LOWER(timeframe) = LOWER(?)"]
        params: List[Any] = [symbol, timeframe]
        self._apply_feature_filter(
            feature_ids, feature_id, conditions, params,
            instance_hashes=instance_hashes)

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
    # Lesen: Generische 2D-Heatmap (20.02, Kapitel §2 / Review E1-E6)
    # ------------------------------------------------------------------
    def fetch_generic_heatmap(
        self,
        symbol: str,
        timeframe: str,
        x_dim: str,
        y_dim: str,
        field: Optional[str] = None,
        agg: str = "count",
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
        limit: Optional[int] = None,
        # 21.01 (E1, 11.08.2026): TF-Freigabe fuer Timeframe-Matrizen.
        # Bei `all_timeframes=True` entfaellt die WHERE-Bedingung
        # `LOWER(timeframe) = LOWER(?)` – DuckDB liest ALLE Zeitebenen
        # (M1..D1) des Symbols in EINER Query. Der `timeframe`-Parameter
        # bleibt fuer den Normalpfad erhalten (Kapitel-Vorgabe `timeframe=""`
        # ist VERWORFEN: der alte Guard `if not symbol or not timeframe:`
        # brach damit mit einer leeren Matrix ab).
        all_timeframes: bool = False,
    ) -> Dict[str, Any]:
        """Aggregiert eine generische 2D-Matrix ueber zwei Dimensionen.

        20.02 (additiv, E1/E5/E6): Freie Dimensionen via `DIM_MAPPINGS`
        (date/dow/hour/timeframe/service_id/symbol – 20.02.01 E6: `dow_hour`
        entfernt), Aggregationen COUNT / CONFLUENCE_COUNT
        (COUNT(DISTINCT feature_id)) sowie AVG/SUM/MIN/MAX ueber einen
        numerischen feature_data-JSON-Key (`field`, via TRY_CAST – Muster
        fetch_heatmap). HIT_RATE entfaellt in V1 (E5: kein Schwellwert
        spezifiziert). 20.02.01 (E5): `dow`-Achsen sind strikt Montag-Freitag
        (zusätzliche WHERE-Bedingung `BETWEEN 1 AND 5`, DuckDB Mo=1..Fr=5).

        21.01 (E1, 11.08.2026): `all_timeframes=True` entfaellt die
        TF-WHERE-Bedingung – Grundlage des Presets `[📊 Service-Timeframe]`
        (X = `timeframe`, Y = `service_id`, agg = `count`). Der
        `timeframe`-Guard wird dabei uebersprungen (leerer/aktueller
        Timeframe erlaubt), `symbol` bleibt Pflicht.

        Wanduhr-Garantie (Invariante 7 / E4): date/dow/hour werden
        mit `bar_time AT TIME ZONE 'UTC'` extrahiert (die gespeicherten Werte
        sind Wanduhr-encoded; die UTC-Darstellung IST die Wanduhr-Zeit).

        Lookback (Nachtrag Umsetzung): `limit` wird im CTE auf die NEUESTEN
        `limit` Bars angewendet (ORDER BY bar_time DESC) – analog zum
        Limit-Verhalten der Analytics-Tabelle; die Aggregation laeuft ueber
        diesen Ausschnitt.

        Pivot-Deckel (Luecke 5.3-5): uebersteigt die dichte Matrix
        MAX_HEATMAP_CELLS, wird die x-Dimension (bzw. danach die y-Dimension)
        deterministisch auf die letzten Sortierwerte begrenzt.

        Args:
            symbol/timeframe: Filter (case-insensitive). Bei
                `all_timeframes=True` ist `timeframe` optional (alle TFs).
            x_dim/y_dim: Dimensions-Keys aus DIM_MAPPINGS (case-insensitiv)
            field: Numerischer feature_data-JSON-Key (Pflicht nur fuer
                AVG/SUM/MIN/MAX; bei COUNT/CONFLUENCE_COUNT ignoriert, E6)
            agg: "count" | "confluence_count" | "avg" | "sum" | "min" | "max"
            feature_id: Optionaler Einzel-Filter (Legacy)
            feature_ids: Optionaler Multi-Filter (`WHERE feature_id IN (...)`).
                Leere Liste/None = kein Filter.
            limit: Max. Bars des Aggregations-Ausschnitts (neueste zuerst).
            all_timeframes: True = TF-WHERE-Bedingung entfaellt (E1).

        Returns:
            {
              "matrix":  dense M x N (rows = y_values, cols = x_values);
                         COUNT/CONFLUENCE_COUNT -> 0 fuer leere Zellen,
                         Wert-Aggregationen -> NaN (numpy),
              "x_labels"/"y_labels": formatierte Achsen-Beschriftungen,
              "x_values": Rohwerte (ISO-Strings; z. B. Datum -> 'YYYY-MM-DD'
                          fuer das Candle-Overlay, E9),
              "min_val"/"max_val": Spannweite der endlichen Matrix-Werte,
              "x_dim"/"y_dim"/"agg"/"field"/"symbol"/"timeframe",
            }

        Raises:
            ValueError: bei unbekannter Dimension/Aggregation oder fehlendem
                `field` fuer AVG/SUM/MIN/MAX (defensiv im Repository gefangen).
        """
        if not symbol or (not timeframe and not all_timeframes):
            return self._empty_generic_heatmap(
                x_dim, y_dim, agg, field, symbol, timeframe)
        x_key = str(x_dim or "").lower()
        y_key = str(y_dim or "").lower()
        x_expr = DIM_MAPPINGS.get(x_key)
        y_expr = DIM_MAPPINGS.get(y_key)
        if x_expr is None or y_expr is None:
            raise ValueError(
                f"[FeatureStoreReader] Unbekannte Dimension '{x_dim}/{y_dim}' – "
                f"erlaubt: {', '.join(DIM_MAPPINGS)}."
            )
        agg_key = str(agg).lower()
        if agg_key == "count":
            agg_sql = "COUNT(*) AS val"
        elif agg_key == "confluence_count":
            agg_sql = "COUNT(DISTINCT feature_id) AS val"
        elif agg_key in ("avg", "sum", "min", "max"):
            field_key = str(field or "").strip()
            if not self._is_json_key_identifier(field_key):
                raise ValueError(
                    f"[FeatureStoreReader] Aggregation '{agg_key}' benoetigt "
                    f"einen identifier-sicheren numerischen feature_data-"
                    f"JSON-Key als 'field' (erhalten: '{field}')."
                )
            agg_sql = (
                f"{agg_key.upper()}(TRY_CAST(feature_data->>'{field_key}' "
                f"AS DOUBLE)) AS val"
            )
        else:
            raise ValueError(
                f"[FeatureStoreReader] Unbekannte Aggregation '{agg}' – "
                f"erlaubt: {', '.join(HEATMAP_AGGREGATIONS)}."
            )

        conditions = ["LOWER(symbol) = LOWER(?)"]
        params: List[Any] = [symbol]
        # 21.01 (E1): TF-Freigabe – bei `all_timeframes=True` entfaellt die
        # TF-WHERE-Bedingung, sodass alle Zeitebenen (M1..D1) in EINER Query
        # aggregiert werden (Preset `[📊 Service-Timeframe]`).
        if not all_timeframes:
            conditions.append("LOWER(timeframe) = LOWER(?)")
            params.append(timeframe)
        self._apply_feature_filter(
            feature_ids, feature_id, conditions, params,
            instance_hashes=instance_hashes)
        # 20.02.01 (E5): `dow`-Achse strikt Montag-Freitag (DuckDB Mo=1..Fr=5).
        if x_key == "dow" or y_key == "dow":
            conditions.append(
                "EXTRACT(DOW FROM bar_time AT TIME ZONE 'UTC')::INTEGER "
                "BETWEEN 1 AND 5")

        if limit:
            sql = f"""
                WITH sel AS (
                    SELECT bar_time, timeframe, feature_id, symbol, feature_data
                    FROM feature_store
                    WHERE {' AND '.join(conditions)}
                    ORDER BY bar_time DESC
                    LIMIT ?
                )
                SELECT {x_expr} AS x_val, {y_expr} AS y_val, {agg_sql}
                FROM sel
                GROUP BY 1, 2
                ORDER BY 1, 2
            """
            params = params + [int(limit)]
        else:
            sql = f"""
                WITH sel AS (
                    SELECT bar_time, timeframe, feature_id, symbol, feature_data
                    FROM feature_store
                    WHERE {' AND '.join(conditions)}
                )
                SELECT {x_expr} AS x_val, {y_expr} AS y_val, {agg_sql}
                FROM sel
                GROUP BY 1, 2
                ORDER BY 1, 2
            """

        con = self._get_connection()
        try:
            rows = con.execute(sql, params).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_generic_heatmap "
                  f"fehlgeschlagen: {e}")
            return self._empty_generic_heatmap(
                x_key, y_key, agg_key, field, symbol, timeframe)

        # Pivot-Deckel (Luecke 5.3-5): deterministisch auf die letzten
        # Sortierwerte begrenzen (bei date = die neuesten Datumswerte).
        x_values = sorted({r[0] for r in rows})
        y_values = sorted({r[1] for r in rows})
        if (len(x_values) * len(y_values)) > MAX_HEATMAP_CELLS:
            max_x = max(1, MAX_HEATMAP_CELLS // max(1, len(y_values)))
            x_keep = set(x_values[-max_x:])
            x_values = sorted(x_keep)
            if (len(x_values) * len(y_values)) > MAX_HEATMAP_CELLS:
                max_y = max(1, MAX_HEATMAP_CELLS // max(1, len(x_values)))
                y_keep = set(y_values[-max_y:])
                y_values = sorted(y_keep)
            keep_x = set(x_values)
            keep_y = set(y_values)
            rows = [r for r in rows
                    if r[0] in keep_x and r[1] in keep_y]

        fill = 0.0 if agg_key in ("count", "confluence_count") else float("nan")
        matrix = np.full((len(y_values), len(x_values)), fill, dtype=float)
        x_index = {v: i for i, v in enumerate(x_values)}
        y_index = {v: j for j, v in enumerate(y_values)}
        for r in rows:
            val = r[2]
            if val is None:
                continue
            xi = x_index.get(r[0])
            yi = y_index.get(r[1])
            if xi is not None and yi is not None:
                matrix[yi][xi] = float(val)

        finite = matrix[np.isfinite(matrix)]
        if finite.size:
            min_val = float(finite.min())
            max_val = float(finite.max())
        else:
            min_val, max_val = 0.0, 0.0

        return {
            "matrix": matrix.tolist(),
            "x_labels": [self._format_dim_value(x_key, v) for v in x_values],
            "y_labels": [self._format_dim_value(y_key, v) for v in y_values],
            # Rohwerte als ISO-Strings (Candle-Overlay-E9: Datum -> Datumsobjekt)
            "x_values": [str(v) for v in x_values],
            # 20.02-Bugfix (09.08.2026): Natuerliche Achsen-Koordinaten
            # (date -> Mitternachts-Epochs, hour/dow -> Ganzzahlen, dow 1..5
            # Mo-Fr, kategorial -> Indizes) fuer die dynamischen Achsen-Ticks.
            "x_axis": self._axis_coords(x_key, x_values),
            "y_axis": self._axis_coords(y_key, y_values),
            "min_val": min_val,
            "max_val": max_val,
            "x_dim": x_key,
            "y_dim": y_key,
            "agg": agg_key,
            "field": str(field or "") or None,
            "symbol": symbol,
            "timeframe": timeframe,
        }

    def _empty_generic_heatmap(
        self,
        x_dim: str,
        y_dim: str,
        agg: str,
        field: Optional[str],
        symbol: str,
        timeframe: str,
    ) -> Dict[str, Any]:
        """Leere generische Heatmap (keine Daten / Fehler / fehlende Filter)."""
        return {
            "matrix": np.zeros((0, 0), dtype=float).tolist(),
            "x_labels": [],
            "y_labels": [],
            "x_values": [],
            "x_axis": [],
            "y_axis": [],
            "min_val": 0.0,
            "max_val": 0.0,
            "x_dim": str(x_dim or "").lower(),
            "y_dim": str(y_dim or "").lower(),
            "agg": str(agg or "").lower(),
            "field": str(field or "") or None,
            "symbol": symbol,
            "timeframe": timeframe,
        }

    # ------------------------------------------------------------------
    # Lesen: OHLCV-Snapshot fuer das Candle-Overlay (20.02, E9)
    # ------------------------------------------------------------------
    def fetch_ohlcv_snapshot(
        self,
        symbol: str,
        timeframe: str,
        limit: Optional[int] = None,
        market_db_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Liest OHLCV-Bars aus market_data.duckdb (read-only, Wanduhr).

        20.02 (E9, Candle-Overlay): Quelle sind die OHLCV-Rohdaten
        (`ohlcv_bars` in `data/market_data.duckdb`, Spalten
        time/open/high/low/close/tick_volume – Muster
        FeatureBuilder.load_ohlcv()). Der Preis-Strip im HeatmapWidget
        gruppiert die Bars pro Spalte (Datum) zu Tages-Ohlc.

        Wanduhr-Garantie (Invariante 7): Die Epochs sind Wanduhr-encoded –
        `_epoch_of()` (UTC-Darstellung) liefert exakt die gespeicherte
        Wanduhr-Epoch; das Widget dekodiert sie als UTC-Datum.

        Args:
            symbol/timeframe: Filter (case-insensitive)
            limit: Max. Bars (Default OHLCV_SNAPSHOT_LIMIT = 5000), die
                NEUESTEN zuerst (ORDER BY time DESC).
            market_db_path: Testbarkeit (Seam) – Default DB_MARKET.

        Returns:
            {"bars": [{"time": int(Wanduhr-Epoch), "open": float, "high": float,
                       "low": float, "close": float, "volume": float}, ...]
             (aufsteigend chronologisch), "symbol", "timeframe"}
        """
        if not symbol or not timeframe:
            return {"bars": [], "symbol": symbol, "timeframe": timeframe}
        if limit is None:
            limit = OHLCV_SNAPSHOT_LIMIT
        con = DbPool.get(market_db_path or DB_MARKET)
        try:
            rows = con.execute("""
                SELECT "time", open, high, low, close, tick_volume
                FROM ohlcv_bars
                WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
                  AND "time" IS NOT NULL
                  AND open IS NOT NULL AND high IS NOT NULL
                  AND low IS NOT NULL AND close IS NOT NULL
                ORDER BY "time" DESC
                LIMIT ?
            """, [symbol, timeframe, int(limit)]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_ohlcv_snapshot "
                  f"fehlgeschlagen: {e}")
            return {"bars": [], "symbol": symbol, "timeframe": timeframe}

        bars: List[Dict[str, Any]] = []
        for r in rows:
            try:
                bars.append({
                    "time": self._epoch_of(r[0]),
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": float(r[5]) if r[5] is not None else 0.0,
                })
            except (TypeError, ValueError):
                continue
        # Aufsteigend (chronologisch) – das Widget rendert von links nach rechts.
        bars.reverse()
        return {"bars": bars, "symbol": symbol, "timeframe": timeframe}

    # ------------------------------------------------------------------
    # Lesen: Tages-OHLC fuer das Candle-Overlay (20.02-Bugfix, 09.08.2026)
    # ------------------------------------------------------------------
    def fetch_daily_ohlc(
        self,
        symbol: str,
        timeframe: str,
        max_days: Optional[int] = None,
        market_db_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Tages-Ohlc je Wanduhr-Datum (SQL-seitig aggregiert, read-only).

        20.02-Bugfix (09.08.2026, Punkt 1+2/User-Meldung): Das Candle-Overlay
        muss im GLEICHEN Canvas ueber der Heatmap liegen und den GESAMTEN
        Heatmap-Zeitraum abdecken. Dafuer werden die ohlcv_bars SQL-seitig pro
        Wanduhr-Datum zu einem Tages-Candle aggregiert (GROUP BY Datum in
        UTC-Darstellung – die Epochs sind Wanduhr-encoded, Invariante 7) –
        um Groessenordnungen schneller als das Laden aller Bars + Python-
        Gruppierung (bei M1 wären das sonst > 1 Mio. Bars).

        Wanduhr-Garantie (Invariante 7): `CAST("time" AT TIME ZONE 'UTC' AS
        DATE)` liefert das Wanduhr-Datum; die Mitternachts-Epoch wird als
        UTC-Darstellung berechnet (exakt die Wanduhr-Epoch des Tages).

        Args:
            symbol/timeframe: Filter (case-insensitive)
            max_days: Max. Anzahl Tage (Default DAILY_OHLC_MAX_DAYS = 4000;
                deckt ~11 Jahre M1 bzw. den gesamten Heatmap-Zeitraum).
            market_db_path: Testbarkeit (Seam) – Default DB_MARKET.

        Returns:
            {"bars": [{"time": int(Wanduhr-Mitternachts-Epoch), "open": float,
                       "high": float, "low": float, "close": float}, ...]
             (aufsteigend chronologisch), "symbol", "timeframe"}
        """
        if not symbol or not timeframe:
            return {"bars": [], "symbol": symbol, "timeframe": timeframe}
        if max_days is None:
            max_days = DAILY_OHLC_MAX_DAYS
        con = DbPool.get(market_db_path or DB_MARKET)
        try:
            rows = con.execute("""
                SELECT
                    CAST("time" AT TIME ZONE 'UTC' AS DATE) AS d,
                    FIRST(open ORDER BY "time") AS open,
                    MAX(high) AS high,
                    MIN(low) AS low,
                    LAST(close ORDER BY "time") AS close
                FROM ohlcv_bars
                WHERE LOWER(symbol) = LOWER(?)
                  AND LOWER(timeframe) = LOWER(?)
                  AND "time" IS NOT NULL
                  AND open IS NOT NULL AND high IS NOT NULL
                  AND low IS NOT NULL AND close IS NOT NULL
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT ?
            """, [symbol, timeframe, int(max_days)]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_daily_ohlc "
                  f"fehlgeschlagen: {e}")
            return {"bars": [], "symbol": symbol, "timeframe": timeframe}

        bars: List[Dict[str, Any]] = []
        for r in rows:
            d = r[0]
            if d is None:
                continue
            try:
                if hasattr(d, "year") and hasattr(d, "month") and hasattr(d, "day"):
                    epoch = int(_dt_datetime(
                        d.year, d.month, d.day,
                        tzinfo=_dt_timezone.utc).timestamp())
                else:
                    epoch = int(_dt_datetime.fromisoformat(
                        str(d)).replace(tzinfo=_dt_timezone.utc).timestamp())
                bars.append({
                    "time": epoch,
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                })
            except (TypeError, ValueError):
                continue
        # Aufsteigend (chronologisch) – das Widget rendert von links nach rechts.
        bars.reverse()
        return {"bars": bars, "symbol": symbol, "timeframe": timeframe}

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
            Registry-/Plugin-IDs (z.B. 'srv_proximity') werden unabhaengig von der
            in der DB gespeicherten Gross-/Kleinschreibung gefunden.
          * Whitespace-tolerant: fuehrende/trailing Leerzeichen (z.B. durch
            Alt-Schreibpfade) werden ignoriert.
          * Defensiv: Zeilen mit NULL/leerer feature_id ODER NULL created_at
            werden uebersprungen (Alt-Rows ohne Zeitstempel koennen kein
            gueltiges Datum liefern).

        Returns:
            Dict feature_id (lower) -> 'DD.MM.JJ' (z.B. {'srv_proximity': '05.08.26'});
            leer bei fehlender DB/Tabelle oder Fehler (defensiv).
        """
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT LOWER(TRIM(feature_id)) AS fid, MAX(created_at)
                FROM feature_store
                WHERE feature_id IS NOT NULL AND TRIM(feature_id) != ''
                  AND feature_id != ?
                GROUP BY LOWER(TRIM(feature_id))
            """, [SENTINEL_NATIVE]).fetchall()
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

    def fetch_last_execution_dates_by_hash(
        self,
    ) -> Dict[str, Dict[str, str]]:
        """Neuester Schreib-Zeitpunkt je (feature_id, instance_hash).

        Bugfix 10.08.2026 (Varianten-Ausfuehrungsdatum): Varianten/Clones
        (indicator_presets) haben EIGENE Feature-Store-Rows (Spalte
        `instance_hash`, 20.04 Q9). Fuer die MasterTree-Anzeige
        '<Preset> (DD.MM.JJ)' wird das Datum der letzten Ausfuehrung je
        Parameter-Variante benoetigt – nicht das der plugin_id insgesamt.

        Quelle: MAX(created_at) GROUP BY feature_id + instance_hash ueber
        ALLE Symbole/Timeframes. Case-insensitiv/whitespace-tolerant wie
        `fetch_last_execution_dates`; Rows ohne instance_hash (nicht
        Varianten-gesteuerte Services) und ohne created_at werden
        uebersprungen.

        Returns:
            Dict feature_id (lower) -> {instance_hash: 'DD.MM.JJ'} – leer
            bei fehlender DB/Tabelle oder Fehler (defensiv).
        """
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT LOWER(TRIM(feature_id)) AS fid, instance_hash,
                       MAX(created_at)
                FROM feature_store
                WHERE feature_id IS NOT NULL AND TRIM(feature_id) != ''
                  AND feature_id != ?
                  AND instance_hash IS NOT NULL AND instance_hash != ''
                GROUP BY LOWER(TRIM(feature_id)), instance_hash
            """, [SENTINEL_NATIVE]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] "
                  f"fetch_last_execution_dates_by_hash fehlgeschlagen: {e}")
            return {}
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            if r[0] is None or r[1] is None or r[2] is None:
                continue
            try:
                out.setdefault(str(r[0]), {})[str(r[1])] = r[2].strftime(
                    "%d.%m.%y")
            except (AttributeError, ValueError):
                continue
        return out

    def fetch_last_execution_datetimes_by_hash(
        self,
    ) -> Dict[str, Dict[str, str]]:
        """Neuester Schreib-Zeitpunkt je (feature_id, instance_hash) mit Uhrzeit.

        Bugfix 11.08.2026 (Dropdown-Anzeige, User-Meldung 1): Das
        Feld-Dropdown haengt an gecheckte Varianten das Datum+Uhrzeit der
        letzten Ausfuehrung an ('{Name} / {Preset} / DD.MM.JJ HH:MM').
        `fetch_last_execution_dates_by_hash` liefert nur das Datum - diese
        Methode ergaenzt die Uhrzeit (Format 'DD.MM.JJ HH:MM', z. B.
        '23.04.26 22:14'). Quelle/Filter/Semantik identisch zur
        Datums-Variante (MAX(created_at) GROUP BY feature_id +
        instance_hash ueber ALLE Symbole/Timeframes; case-insensitiv/
        whitespace-tolerant; Rows ohne instance_hash/created_at werden
        uebersprungen).

        Returns:
            Dict feature_id (lower) -> {instance_hash: 'DD.MM.JJ HH:MM'} -
            leer bei fehlender DB/Tabelle oder Fehler (defensiv).
        """
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT LOWER(TRIM(feature_id)) AS fid, instance_hash,
                       MAX(created_at)
                FROM feature_store
                WHERE feature_id IS NOT NULL AND TRIM(feature_id) != ''
                  AND feature_id != ?
                  AND instance_hash IS NOT NULL AND instance_hash != ''
                GROUP BY LOWER(TRIM(feature_id)), instance_hash
            """, [SENTINEL_NATIVE]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] "
                  f"fetch_last_execution_datetimes_by_hash fehlgeschlagen: "
                  f"{e}")
            return {}
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            if r[0] is None or r[1] is None or r[2] is None:
                continue
            try:
                out.setdefault(str(r[0]), {})[str(r[1])] = r[2].strftime(
                    "%d.%m.%y %H:%M")
            except (AttributeError, ValueError):
                continue
        return out

    def fetch_last_execution_datetimes(self) -> Dict[str, str]:
        """Neuester Schreib-Zeitpunkt je feature_id MIT Uhrzeit.

        Bugfix 11.08.2026 (Runde 16c, Dropdown-Anzeige, User-Meldung):
        Das Feld-Dropdown haengt an Services OHNE Varianten (Standalone,
        z. B. srv_trend_breakout) das Datum+Uhrzeit der letzten Ausfuehrung
        an ('{Name} / {Key} / DD.MM.JJ HH:MM', z. B. '23.04.26 22:14').
        `fetch_last_execution_dates` liefert nur das Datum - diese Methode
        ergaenzt die Uhrzeit. Quelle/Filter/Semantik identisch zur
        Datums-Variante (MAX(created_at) GROUP BY feature_id ueber ALLE
        Symbole/Timeframes; case-insensitiv/whitespace-tolerant; Rows ohne
        created_at werden uebersprungen).

        Returns:
            Dict feature_id (lower) -> 'DD.MM.JJ HH:MM' - leer bei
            fehlender DB/Tabelle oder Fehler (defensiv).
        """
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT LOWER(TRIM(feature_id)) AS fid, MAX(created_at)
                FROM feature_store
                WHERE feature_id IS NOT NULL AND TRIM(feature_id) != ''
                  AND feature_id != ?
                GROUP BY LOWER(TRIM(feature_id))
            """, [SENTINEL_NATIVE]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_last_execution_datetimes "
                  f"fehlgeschlagen: {e}")
            return {}
        out: Dict[str, str] = {}
        for r in rows:
            if r[0] is None or r[1] is None:
                continue
            try:
                out[str(r[0])] = r[1].strftime("%d.%m.%y %H:%M")
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

    def available_instance_hashes(
        self, symbol: str, timeframe: str,
    ) -> set:
        """Liefert die instance_hash-Werte mit feature_data (20.04-Q8-Fix).

        (No Data)-Unterstuetzung: Das Analytics-Feld-Dropdown zeigt neue
        Plugin-Varianten (Clones/Presets) sofort an – markiert als
        '(No Data)' – bis der erste Scan/LiveRun Daten in den feature_store
        geschrieben hat. Diese Methode liefert die Menge der Hashes, die
        bereits Zeilen BESITZEN (rein lesend, kein SQL in der UI).

        Returns:
            set[str] – leer bei fehlender DB/Tabelle oder Fehlern
            (defensiv, Invariante FeatureStoreReader: rein lesend).
        """
        if not symbol or not timeframe:
            return set()
        base = self._feature_meta_base(symbol, timeframe)
        if base is None:
            return set()
        out: Set[str] = set()
        for hashes in base["hashes_by_service"].values():
            out.update(hashes)
        return out

    def plugin_ids_with_hashes(
        self, symbol: str, timeframe: str,
    ) -> set:
        """Plugin-IDs mit mindestens einer instance_hash-Zeile (Runde 13c).

        Runde 13c (Bugfix Dropdown-NoData, Alt-Bestand): Der Reader muss
        unterscheiden koennen, ob die Daten einer plugin_id VARIANTEN-
        AUFGETEILT vorliegen (eigene instance_hash-Rows je Variante) oder
        UNDIFFERENZIERT (Alt-Rows ohne Hash, gehoeren der plugin_id als
        Ganzes). Diese Methode liefert die Mengen der plugin_ids, die
        mindestens EINE Zeile mit gesetztem instance_hash besitzen
        (rein lesend, kein SQL in der UI).

        Runde 15 (Performance-Fix 3): Abgeleitet aus dem gemeinsamen
        Metadaten-Basis-Scan `_feature_meta_base` (keine separate Abfrage;
        Identitaet = unter "" gruppierte Legacy/native-Rows ohne feature_id
        werden ausgeschlossen, wie bisher).

        Returns:
            set[str] – leer bei fehlender DB/Tabelle oder Fehlern
            (defensiv, Invariante FeatureStoreReader: rein lesend).
        """
        if not symbol or not timeframe:
            return set()
        base = self._feature_meta_base(symbol, timeframe)
        if base is None:
            return set()
        return {k for k in base["hashes_by_service"]
                if k and str(k).strip() != ""}

    def resolve_no_data_variants(
        self,
        symbol: str,
        timeframe: str,
        presets_data: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Plugin-Varianten ohne feature_store-Daten (Runde 11, B4-1).

        Runde 11 (Bug 4): Die '(No Data)'-Auswertung wurde aus dem
        UI-Hauptthread in den QUERY_FEATURES-Worker verlagert. Der
        ViewModel liefert die Preset-Modell-Daten als Snapshot
        (`presets_data`: {"presets": {pid: [...]}, "sets": [...],
        "standalone": [pid...], "display_names": {"{pid}|{pname}": str},
        "active_hashes": [gecheckte Varianten-Hashes]}); diese Methode
        kombiniert sie mit den DB-Fakten (`available_instance_hashes` /
        `feature_keys_by_service`) im Worker-Thread.

        Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026): Die neue
        Snapshot-Sektion `standalone` listet registrierte Plugins ohne
        Presets und ohne Set-Instanz (z. B. srv_trend_breakout) als
        hash-lose Variante (preset_name 'Default'). Eine Standalone-Variante
        gilt als 'ohne Daten', wenn ihre plugin_id keine feature_store-Zeilen
        besitzt (`_has_data` prueft `pids_with_data` direkt - kein
        Hash-/Alt-Bestand-Fallback noetig). Dadurch erscheint ein
        registrierter, aber noch nie ausgeführter Service korrekt als
        '(No Data)' im Feld-Dropdown.

        Runde 13 (Bugfix Dropdown-NoData): `active_hashes` (nicht leer =
        Varianten-Einschraenkung) macht die Auswertung VARIANTEN-GENAU -
        es werden NUR die im ServicePicker gecheckten Varianten geliefert
        (nicht-gecheckte Instanzen derselben plugin_id erscheinen nicht
        mehr im '(No Data)'-Abschnitt; das Dropdown zeigt damit nicht mehr
        die erste Variante eines Services, wenn eine andere gecheckt ist).

        Runde 13c (Alt-Bestand): Eine Variante ohne Hash-Treffer zaehlt
        trotzdem als 'hat Daten', wenn die plugin_id ausschliesslich
        undifferenzierte Alt-Rows OHNE instance_hash besitzt
        (`plugin_ids_with_hashes`) � dieser Alt-Bestand gehoert der
        ORIGINAL-Variante (der ERSTEN aktiven Variante der plugin_id im
        Snapshot). Runde 14: Weitere Varianten derselben plugin_id werden
        NICHT vom Alt-Bestand abgedeckt - eine neu erzeugte zweite Variante
        ohne Daten muss als '(No Data)' erscheinen.

        Eine Variante gilt als 'ohne Daten', wenn ihr instance_hash KEINE
        Zeilen besitzt (oder - bei Varianten ohne Hash - ihr plugin_id keine
        feature_store-Zeilen liefert). Archivierte Presets sind bewusst
        unsichtbar (Q6/Q7).

        Returns:
            Liste von {"plugin_id", "preset_name", "instance_hash",
            "display_name"} - leer, wenn alle Varianten Daten besitzen
            (defensiv, rein lesend).
        """
        if not symbol or not timeframe:
            return []
        presets = (presets_data or {}).get("presets") or {}
        sets = (presets_data or {}).get("sets") or []
        display_names = (presets_data or {}).get("display_names") or {}
        # Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026):
        # Registrierte Plugins ohne Presets und ohne Set-Instanz
        # (z. B. srv_trend_breakout) - der ViewModel markiert sie ueber
        # die Snapshot-Sektion "standalone" als hash-lose Variante. Sie
        # gelten als '(No Data)', solange der feature_store keine Rows
        # ihrer plugin_id besitzt (Reader prueft `pids_with_data`).
        standalone = (presets_data or {}).get("standalone") or []
        # Runde 13 (Bugfix Dropdown-NoData): Varianten-Einschraenkung aus dem
        # Snapshot - leer = KEINE Einschraenkung (alle Varianten der aktiven
        # Services), nicht leer = nur die gecheckten Varianten.
        active_hashes = {str(h).strip().lower()
                         for h in ((presets_data or {}).get("active_hashes")
                                   or [])}
        try:
            available = self.available_instance_hashes(symbol, timeframe)
        except Exception:
            available = set()
        # Runde 13c (Bugfix Dropdown-NoData, Alt-Bestand): Plugin-IDs mit
        # eigenem instance_hash-Bestand (Varianten-Aufteilung). Liegt die
        # plugin_id NICHT in dieser Menge, stammt ihr gesamter Bestand aus
        # undifferenzierten Alt-Rows OHNE Hash (z. B. srv_proximity: alle
        # Rows instance_hash IS NULL) – dann deckt der Alt-Bestand jede
        # Variante des Services ab (kein '(No Data)'-Fehlalarm fuer
        # Varianten, deren berechneter Hash in keiner DB-Zeile steht).
        # WICHTIG: pids_with_hashes=None bei Fehler (z. B. Fake/Temp-DB
        # ohne Tabelle) - dann bleibt die Runde-10-Semantik konservativ
        # erhalten (kein Alt-Bestand-Fallback auf unbekannter Basis).
        try:
            pids_with_hashes = self.plugin_ids_with_hashes(symbol, timeframe)
        except Exception:
            pids_with_hashes = None
        # Runde 12 (Option A, Performance): Die teure feature_keys_by_service-
        # Abfrage (laedt feature_data-JSONs) wird auf die AKTIVEN plugin_ids
        # des Snapshots eingeschraenkt (Preset-Keys + Set-Instanz-Services) -
        # bei leerem Snapshot (keine aktiven Presets) genuegt eine leere
        # pids_with_data-Menge. Vorher scannte die Abfrage ALLE Zeilen des
        # Symbols (Hauptgrund fuer das langsame Dropdown-Update).
        active_pids: List[str] = []
        for _pid in (presets or {}).keys():
            active_pids.append(str(_pid))
        for _s in sets or []:
            _services = _s.get("services") if isinstance(_s, dict) else None
            if not isinstance(_services, dict):
                continue
            for _svc in _services.values():
                if isinstance(_svc, dict) and str(
                        _svc.get("plugin_id") or "").strip():
                    active_pids.append(str(_svc["plugin_id"]))
        # Runde 15c: Standalone-Services ebenfalls in die Abfrage-Scope
        # aufnehmen - `pids_with_data` muss deren Datenlage kennen, sonst
        # wuerde ein Standalone-Service MIT Rows faelschlich als '(No Data)'
        # geliefert (feature_keys_by_service scannt nur die aktiven pids).
        for _pid in standalone or []:
            _s = str(_pid or "").strip()
            if _s:
                active_pids.append(_s)
        active_pids = list(dict.fromkeys(active_pids))
        try:
            if active_pids:
                keys_by_service = self.feature_keys_by_service(
                    symbol, timeframe, feature_ids=active_pids)
            else:
                keys_by_service = {}
            pids_with_data = {str(k).strip().lower()
                              for k in (keys_by_service or {})}
        except Exception:
            pids_with_data = set()
        try:
            from analytics.engine.service_models import generate_instance_hash
        except Exception:
            generate_instance_hash = None
        # Runde 10 (Bug 2): available case-insensitiv indexieren (einmalig).
        available_low = {str(x).strip().lower()
                         for x in (available or set())}

        def _has_data(pid: str, h: str) -> bool:
            """True, wenn die Variante feature_store-Daten besitzt.

            Runde 10 (Bug 2): Differenzierung statt grobem
            pids_with_data-Fallback - eine benannte Variante mit eigenem
            instance_hash zaehlt NUR, wenn GENAU dieser Hash Zeilen
            besitzt. Der pids_with_data-Fallback gilt nur noch fuer
            Varianten OHNE Hash (NULL/Alt-Bestand).

            Runde 13c (Bugfix Dropdown-NoData, Alt-Bestand): Besitzt die
            plugin_id KEINERLEI hash-differenzierte Zeilen (`pids_with_hashes`
            leer), stammt ihr Bestand aus undifferenzierten Alt-Rows
            (instance_hash IS NULL, z. B. srv_proximity vor der
            feature_data-Migration). Dieser Alt-Bestand gehoert der
            plugin_id als Ganzes und deckt JEDE Variante ab - sonst wuerde
            z. B. die Set-Instanz 'srv_proximity' trotz 99K M1-Zeilen als
            '(No Data)' gemeldet, weil ihr berechneter Hash
            (generate_instance_hash) in keiner DB-Zeile steht. Der
            Fallback greift NUR, wenn die Hash-Bestands-Abfrage ERFOLGREICH
            war (pids_with_hashes ist None = Abfragefehler -> konservativ
            Runde-10-Semantik, kein Fallback).
            """
            if not pid:
                return True
            h_s = str(h or "").strip()
            if h_s:
                if h_s.lower() in available_low:
                    return True
                # Undifferenzierter Alt-Bestand (keine Hash-Zeilen der
                # plugin_id bekannt): die plugin-weiten Daten decken die
                # ORIGINAL-Variante ab (die ERSTE aktive Variante im
                # Snapshot - ihr gehoert der Alt-Bestand, der vor der
                # Hash-Aera von genau dieser Instanz geschrieben wurde).
                # Nur bei erfolgreicher Bestands-Abfrage. Runde 14: Der
                # Fallback gilt NICHT fuer weitere Varianten derselben
                # plugin_id - eine neu erzeugte zweite Variante (anderer
                # Hash, noch nie berechnet) hat KEINE Daten und muss als
                # '(No Data)' erscheinen.
                if (pids_with_hashes is not None
                        and str(pid).strip().lower() not in pids_with_hashes
                        and h_s == first_hash_by_pid.get(
                            str(pid).strip().lower(), "")):
                    return str(pid).strip().lower() in pids_with_data
                return False
            return str(pid).strip().lower() in pids_with_data

        # Runde 14 (Bugfix Dropdown-NoData, 2. Variante ohne Daten):
        # Bestimme die ERSTE aktive Variante je plugin_id im Snapshot
        # (Reihenfolge wie im ServicePicker: Presets/Clones zuerst, dann
        # Set-Instanzen). Nur dieser Original-Variante darf der
        # Alt-Bestand-Fallback (undifferenzierte NULL-Hash-Rows) zugeordnet
        # werden - der Bestand wurde vor der Hash-Aera von genau der
        # ersten/originalen Instanz geschrieben.
        first_hash_by_pid: Dict[str, str] = {}

        def _collect_first(pid: str, h: str) -> None:
            k = str(pid or "").strip().lower()
            if not k:
                return
            if k not in first_hash_by_pid:
                first_hash_by_pid[k] = str(h or "").strip()

        for _pid, _clones in presets.items():
            if not isinstance(_clones, list):
                continue
            for _clone in _clones:
                if not isinstance(_clone, dict) or _clone.get("is_archived"):
                    continue
                _collect_first(str(_pid),
                               str(_clone.get("instance_hash") or ""))
        for _s in sets or []:
            _services = _s.get("services") if isinstance(_s, dict) else None
            if not isinstance(_services, dict):
                continue
            for _svc in _services.values():
                if not isinstance(_svc, dict) or _svc.get("is_archived"):
                    continue
                _pid = str(_svc.get("plugin_id") or "").strip()
                if not _pid:
                    continue
                _h = ""
                if generate_instance_hash is not None:
                    _h = generate_instance_hash(_pid, _svc.get("params") or {})
                _collect_first(_pid, _h)

        out: List[Dict[str, Any]] = []
        seen: Set[Tuple[str, str]] = set()

        def _add(pid: str, pname: str, h: str) -> None:
            pid_s = str(pid or "").strip()
            if not pid_s:
                return
            h_s = str(h or "").strip()
            # Runde 13 (Bugfix Dropdown-NoData): Varianten-Einschraenkung -
            # ist eine Hash-Auswahl aktiv (active_hashes nicht leer), werden
            # NUR die gecheckten Varianten geliefert. Nicht-gecheckte
            # Instanzen derselben plugin_id erscheinen nicht mehr als
            # '(No Data)' (vorher wurde hier die ERSTE Variante des Services
            # angezeigt bzw. ungecheckte Instanzen mit aufgefuehrt).
            # Runde 16 (Bugfix Mischbetrieb, User-Meldung 5/6, 11.08.2026):
            # Der Guard greift nur noch bei Varianten MIT Hash (`h_s and`) -
            # hash-lose Varianten (Standalone-Services wie srv_trend_breakout
            # und NULL-Hash-Alt-Bestand) werden UEBER `feature_ids` gecheckt
            # und duerfen von einer aktiven Hash-Auswahl nicht verworfen
            # werden (sonst verschwinden Services im Mischbetrieb).
            if active_hashes and h_s and h_s.lower() not in active_hashes:
                return
            key = (pid_s.lower(), h_s)
            if key in seen:
                return
            seen.add(key)
            if _has_data(pid_s, h_s):
                return
            pname_s = str(pname or "Default")
            out.append({
                "plugin_id": pid_s,
                "preset_name": pname_s,
                "instance_hash": h_s,
                "display_name": str(
                    display_names.get(f"{pid_s}|{pname_s}")
                    or self._no_data_fallback_name(pid_s, pname_s)),
            })

        for pid, clones in presets.items():
            if not isinstance(clones, list):
                continue
            for clone in clones:
                if not isinstance(clone, dict):
                    continue
                if clone.get("is_archived"):
                    continue
                _add(str(pid),
                     str(clone.get("preset_name") or "Default"),
                     str(clone.get("instance_hash") or ""))
        # Runde 9 (Bug 2): Set-Instanz-Varianten ebenfalls erfassen.
        for s in sets or []:
            services = s.get("services") if isinstance(s, dict) else None
            if not isinstance(services, dict):
                continue
            for instance_id, svc in services.items():
                if not isinstance(svc, dict):
                    continue
                if svc.get("is_archived"):
                    continue
                pid = str(svc.get("plugin_id") or "").strip()
                if not pid:
                    continue
                if generate_instance_hash is not None:
                    h = generate_instance_hash(pid, svc.get("params") or {})
                else:
                    h = ""
                _add(pid, f"{pid} [{instance_id}]", h)
        # Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026): Reine
        # Standalone-Services als hash-lose Variante (preset_name 'Default')
        # erfassen - `_has_data(pid, "")` prueft direkt `pids_with_data`
        # (kein Hash-/Alt-Bestand-Fallback noetig). Ein Standalone-Service
        # ohne feature_store-Rows erscheint damit als '(No Data)' im
        # Feld-Dropdown; sobald Daten existieren, bleibt der Hinweis aus.
        for pid in standalone or []:
            _add(str(pid), "Default", "")
        return out

    @staticmethod
    def _no_data_fallback_name(pid: str, pname: str) -> str:
        """Lesbarer Fallback-Anzeigename (ohne Modell-Zugriff im Reader).

        Runde 11 (Bug 4, B4-1): Der Reader kennt das ServiceSelectorModel
        nicht - der ViewModel liefert die Anzeigenamen ueber den Snapshot
        (`display_names`); dieser Fallback greift nur bei fehlendem
        Snapshot-Eintrag (defensiv, identisch zur VM-Logik).
        """
        pretty = (pid.replace("srv_", "").replace("ind_", "")
                  .replace("_", " ").title())
        if not pretty:
            pretty = pid
        # Runde 16 (Bugfix 1, 11.08.2026): Anzeige-Format auf
        # '{Name} / {Preset}' umgestellt (identisch zum ViewModel-Format;
        # vorher '{Name} ({Preset})'). 'Default' wird als Platzhalter-
        # Preset uebersprungen (Standalone-Services ohne echten Preset).
        if pname and str(pname).strip().lower() != "default":
            return f"{pretty} / {str(pname).strip()}"
        return pretty

    def get_available_features(
        self, symbol: str, timeframe: str
    ) -> Dict[str, Any]:
        """Liefert verfuegbare Plugin-IDs, JSON-Keys und Zeilenzahl.

        19.02 (Cleanup): `columns` = dynamische feature_data-JSON-Keys
        (statt der entfernten nativen Spalten).

        Returns:
            {"feature_ids": [...], "columns": [...], "total_rows": int}
        """
        con = self._get_connection()
        try:
            ids = [r[0] for r in con.execute("""
                SELECT DISTINCT feature_id FROM feature_store
                WHERE feature_id IS NOT NULL AND feature_id != ''
                  AND feature_id != ?
                ORDER BY feature_id
            """, [SENTINEL_NATIVE]).fetchall()]
            total = con.execute("""
                SELECT COUNT(*) FROM feature_store
                WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
            """, [symbol, timeframe]).fetchone()
            total = int(total[0]) if total and total[0] is not None else 0
        except Exception as e:
            print(f"WARN [FeatureStoreReader] get_available_features "
                  f"fehlgeschlagen: {e}")
            return {"feature_ids": [], "columns": [], "total_rows": 0}
        return {
            "feature_ids": [str(i) for i in ids],
            "columns": self.available_feature_keys(symbol, timeframe),
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
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
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
        self._apply_feature_filter(
            feature_ids, feature_id, conditions, params,
            instance_hashes=instance_hashes)
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
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
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
        self._apply_feature_filter(
            feature_ids, feature_id, conditions, params,
            instance_hashes=instance_hashes)
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
