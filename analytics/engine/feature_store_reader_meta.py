"""
feature_store_reader_meta.py - Meta-Cache, Connection, Epoch (Reader-Infrastruktur)

23.05 God-File-Split (15.08.2026): Aus analytics/engine/feature_store_reader.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der FeatureStoreReader
als Mixin (Klasse FeatureStoreMetaMixin).
"""

import time

from typing import (
    Any,
    Dict,
    Optional,
    Set,
    Tuple,
)

from db_service import (
    DbPool,
)

class FeatureStoreMetaMixin:

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
        # 21.03.20 (Analytics Modus-Filter): source_mode-Werte je
        # Service (Multi-Modus-Services srv_swing_*/srv_trend_*) -
        # Grundlage des Modus-Dropdowns OHNE zusaetzlichen
        # DB-Roundtrip (gleicher Cache wie die Keys, Runde 15).
        source_modes_by_service: Dict[str, Set[str]] = {}
        # 21.03.20-Bugfix 3: JSON-Keys je (Service, source_mode) - Grundlage
        # modus-spezifischer Ergebnis-Parameter im Feld-Dropdown (modus-
        # gefilterte Keys statt aller Keys ueber alle Modi hinweg).
        keys_by_service_mode: Dict[str, Dict[str, Set[str]]] = {}
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
            # source_mode (nur nicht-leere String-Werte) - das
            # Modus-Dropdown zeigt ausschliesslich tatsaechlich
            # geschriebene Modi (dynamisch, keine Registry-Logik).
            sm = data.get("source_mode")
            if sm is not None and str(sm).strip():
                source_modes_by_service.setdefault(
                    service, set()).add(str(sm).strip())
                # 21.03.20-Bugfix 3: Keys DIESER Row sammeln (modus-
                # spezifische Ergebnis-Parameter fuer das Feld-Dropdown) -
                # NICHT bucket.keys() (bucket aggregiert ueber ALLE Modi).
                row_keys = {str(k) for k in data
                            if k != "schema_version" and str(k).strip()}
                keys_by_service_mode.setdefault(service, {}).setdefault(
                    str(sm).strip(), set()).update(row_keys)
        entry = {
            "types_by_service": types_by_service,
            "hashes_by_service": hashes_by_service,
            "null_hash_pids": null_hash_pids,
            "source_modes_by_service": source_modes_by_service,
            "keys_by_service_mode": keys_by_service_mode,
        }
        self._meta_put(key, entry)
        return entry

    # ------------------------------------------------------------------
    # Interna
    # ------------------------------------------------------------------
    def _get_connection(self):
        return DbPool.get(self.db_path)

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
