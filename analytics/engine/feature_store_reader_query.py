"""
feature_store_reader_query.py - Row-/Column-/Key-Fetch, Verfuegbarkeitslisten

23.05 God-File-Split (15.08.2026): Aus analytics/engine/feature_store_reader.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der FeatureStoreReader
als Mixin (Klasse FeatureStoreQueryMixin).
"""

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
)

from analytics.engine.feature_store_reader_constants import (
    SENTINEL_NATIVE,
)

class FeatureStoreQueryMixin:

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
        # 21.03.12 (MTF-FC auf Analytics): Optionaler Zeitfilter (Wanduhr-
        # Epochs relativ zum letzten Datenpunkt; None = kein Filter).
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        # 21.03.20 (Analytics Modus-Filter): source_mode-Filter fuer
        # Multi-Modus-Services (None/"all"/leer = kein Filter).
        service_mode: Optional[str] = None,
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
        self._apply_time_range(from_ts, to_ts, conditions, params)
        self._apply_mode_filter(service_mode, conditions, params)

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
        # 21.03.20-Bugfix 3: Modus-Filter (modus-spezifische Keys).
        service_mode: Optional[str] = None,
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
            # 21.03.20-Bugfix 3: Optionaler Modus-Filter - nur Keys, die in
            # Rows mit diesem source_mode vorkommen (modus-spezifische
            # Ergebnis-Parameter). Noch nicht berechnete Modi liefern leer
            # (der output_schema-Fallback im Repository greift dort).
            use_mode = (str(service_mode or "").strip()
                        if str(service_mode or "").strip().lower()
                        not in ("all", "alle") else "")
            if use_mode:
                mode_keys = base.get("keys_by_service_mode", {}).get(
                    service, {}).get(use_mode) or set()
                keys = sorted(k for k in bucket.keys() if k in mode_keys)
            else:
                keys = sorted(bucket.keys())
            if numeric_only:
                keys = [k for k in keys if bucket[k] == {"num"}]
            if keys:
                out[service] = keys
        return out

    def fetch_available_source_modes(
        self,
        symbol: str,
        timeframe: str,
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
    ) -> Tuple[List[str], bool]:
        """Distinct source_mode-Werte je Symbol/TF (21.03.20, Modus-Dropdown).

        Analysiert den gecachten Metadaten-Basis-Scan `_feature_meta_base`
        (Runde 15, Performance-Fix 3: EIN DB-Scan fuer alle Metadaten-
        Methoden) - der leichte QUERY_FEATURES-Pfad bekommt die Modus-Liste
        OHNE zusaetzlichen Roundtrip. Der feature_ids-Filter folgt dem
        Muster `feature_keys_by_service` (case-insensitiv + whitespace-
        tolerant): abgewaehlte Services liefern ihre Modi NICHT mehr.

        Returns:
            (source_modes, has_source_mode_services)
              source_modes:             sortierte, case-originale Modus-Werte
                                        (z. B. ['momentum', 'structure'])
              has_source_mode_services: True, wenn mindestens ein AKTIVER
                                        Service einen nicht-leeren
                                        source_mode-Wert schreibt (Combo-
                                        Deaktivierung im HeatmapWidget).
        """
        if not symbol or not timeframe:
            return [], False
        base = self._feature_meta_base(symbol, timeframe)
        if base is None:
            return [], False
        modes_by_service = base.get("source_modes_by_service", {})
        wanted = {str(i).strip().lower() for i in (feature_ids or [])
                  if str(i).strip()}
        if not wanted and feature_id:
            wanted = {str(feature_id).strip().lower()}
        hashes = set()
        if instance_hashes:
            hashes = {str(h).strip().lower() for h in instance_hashes
                      if str(h).strip()}
        hashes_by_service = base["hashes_by_service"]
        null_hash_pids = base["null_hash_pids"]

        values: Set[str] = set()
        has = False
        for service, modes in modes_by_service.items():
            svc_l = str(service).strip().lower()
            if wanted and svc_l not in wanted:
                continue
            if hashes:
                svc_hashes = hashes_by_service.get(svc_l, set())
                if not (svc_l in null_hash_pids or (svc_hashes & hashes)):
                    continue
            if modes:
                values.update(modes)
                has = True
        return sorted(values), has

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
        # 21.03.12 (MTF-FC auf Analytics): Optionaler Zeitfilter (Wanduhr-
        # Epochs relativ zum letzten Datenpunkt; None = kein Filter).
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        # 21.03.20 (Analytics Modus-Filter): source_mode-Filter fuer
        # Multi-Modus-Services (None/"all"/leer = kein Filter).
        service_mode: Optional[str] = None,
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
        self._apply_time_range(from_ts, to_ts, conditions, params)
        self._apply_mode_filter(service_mode, conditions, params)

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
