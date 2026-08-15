"""
feature_store_reader_heatmap.py - Heatmap-Fetch (Klassik + generische 2D-Engine)

23.05 God-File-Split (15.08.2026): Aus analytics/engine/feature_store_reader.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der FeatureStoreReader
als Mixin (Klasse FeatureStoreHeatmapMixin).
"""

from datetime import (
    datetime as _dt_datetime,
)

from datetime import (
    timezone as _dt_timezone,
)

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import numpy as np

from analytics.engine.feature_store_reader_constants import (
    DAYS_PER_WEEK,
    DIM_MAPPINGS,
    DOW_LABELS,
    HEATMAP_AGGREGATIONS,
    HOURS_PER_DAY,
    MAX_HEATMAP_CELLS,
    TF_SECONDS,
)

class FeatureStoreHeatmapMixin:

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
        # 21.03.12 (MTF-FC auf Analytics): Optionaler Zeitfilter (Wanduhr-
        # Epochs relativ zum letzten Datenpunkt; None = kein Filter).
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        # 21.03.20 (Analytics Modus-Filter): source_mode-Filter fuer
        # Multi-Modus-Services (None/"all"/leer = kein Filter).
        service_mode: Optional[str] = None,
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
        self._apply_time_range(from_ts, to_ts, conditions, params)
        self._apply_mode_filter(service_mode, conditions, params)

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
        # 21.03.12 (MTF-FC auf Analytics, Entscheidung 6a): Aggregations-TF
        # fuer das date-Raster (z. B. 'M15'/'H1'; 'auto'/None = kein
        # Bucketing). Optionaler Zeitfilter (Wanduhr-Epochs relativ zum
        # letzten Datenpunkt; None = kein Filter).
        bucket_tf: Optional[str] = None,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        # 12.08.2026 (Option A, Bug 1/2): (Service|Parameter)-Paar-Filter
        # ('{service_id}|{key}') des 'Feld'-Dropdowns - der Reader filtert
        # auf PARAMETER-Ebene (feature_data->>key IS NOT NULL je Service).
        # Leer/None = kein Paar-Filter (reines feature_ids-Verhalten).
        field_pairs: Optional[List[str]] = None,
        # 21.03.20 (Analytics Modus-Filter): source_mode-Filter fuer
        # Multi-Modus-Services (None/"all"/leer = kein Filter).
        service_mode: Optional[str] = None,
        # 21.03.20-Bugfix 3: optionale '{feature_id}::{mode}'-Kombinationen
        # der aktiven Services (Registry) - die service_id-Achse zeigt
        # damit auch noch nicht berechnete Modi als leere Achsenpunkte
        # (nur bei deaktivem Modus-Filter; leere Liste = kein Effekt).
        extra_service_modes: Optional[List[str]] = None,
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
        # 21.03.12 (Entscheidung 6a): `bucket_tf` bucketed das date-Raster
        # auf das Aggregations-TF-Raster (agg_tf). to_timestamp liefert
        # naive TIMESTAMP-Werte (Wanduhr) - _axis_coords interpretiert sie
        # als Wanduhr (UTC-Darstellung, Invariante 7).
        if bucket_tf:
            _secs = TF_SECONDS.get(str(bucket_tf).strip().upper())
            if _secs:
                _bucket_expr = (
                    f"(to_timestamp((FLOOR(EXTRACT('epoch' FROM bar_time AT "
                    f"TIME ZONE 'UTC') / {_secs})::BIGINT) * {_secs}) "
                    f"AT TIME ZONE 'UTC')"
                )
                if x_key == "date":
                    x_expr = _bucket_expr
                if y_key == "date":
                    y_expr = _bucket_expr
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
        # 12.08.2026 (Option A, Bug 1/2): (Service|Parameter)-Paar-Filter
        # des 'Feld'-Dropdowns - OR-Bedingung je Paar
        # (`feature_id = ? AND json_extract_string(feature_data, '$.key')
        # IS NOT NULL`). Leere Liste = kein Paar-Filter (nur
        # feature_ids-Filter).
        self._apply_field_pair_filter(field_pairs, conditions, params)
        self._apply_time_range(from_ts, to_ts, conditions, params)
        self._apply_mode_filter(service_mode, conditions, params)
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
        # 21.03.20-Bugfix 3: fehlende (Service, Modus)-Kombinationen
        # aus der Registry ergaenzen (nur service_id-Dimension, leere
        # Zellen = fill). Der Modus-Filter schraenkt Rows VOR der
        # Aggregation ein - bei konkretem Modus bleibt die Achse auf
        # diesen Modus begrenzt (keine Registry-Ergaenzung noetig).
        if extra_service_modes and (x_key == "service_id"
                                    or y_key == "service_id"):
            extra = {str(e) for e in extra_service_modes if str(e).strip()}
            if extra:
                if x_key == "service_id":
                    x_values = sorted(set(x_values) | extra)
                if y_key == "service_id":
                    y_values = sorted(set(y_values) | extra)
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
            # Rohwerte als ISO-Strings (Candle-Overlay-E9: Datum -> Datumsobjekt).
            # 21.03.12 (bucket_tf): tz-aware Datetimes (falls DuckDB den
            # Session-TZ anhaengt) defensiv auf naive Wanduhr-UTC normalisieren.
            "x_values": [
                (str(v.astimezone(_dt_timezone.utc).replace(tzinfo=None))
                 if isinstance(v, _dt_datetime) and v.tzinfo is not None
                 else str(v))
                for v in x_values
            ],
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
