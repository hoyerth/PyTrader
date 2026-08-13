# analytics/engine/analytics_repository.py
"""
analytics_repository.py - AnalyticsRepository (Phase 15.03).

High-Level-Datenmethoden fuer die Analytics-UI (AnalyticsWindow).
Delegiert lesend an den `FeatureStoreReader` (reiner Lese-Pfad auf den
feature_store, Invariante 4 / MVVM) und bereitet die Rohdaten in die von
den UI-Pages benoetigten Strukturen auf:

    get_table()         – rohe Feature-Zeilen fuer die Tabellen-Seite
    get_heatmap()       – 2D-Matrix (X: Wochentage, Y: Tagesstunden
                          Berlin Wanduhr, Invariante 7)
    get_scatter()       – X/Y-Paare zweier feature_data-JSON-Keys (19.02)
    get_distribution()  – Histogramm (bins/counts) eines JSON-Keys (19.02)

19.02 (Cleanup): Die Legacy-Native-Spalten ema_diff/rsi_14/atr_normalized
sind entfernt. Scatter-/Verteilungs-/Heatmap-Achsen werden rein dynamisch
aus den numerischen JSON-Keys des `feature_data` abgeleitet
(`available_feature_keys(numeric_only=True)`).

Das Repository ist rein lesend (kein SQL in UI, keine Schreiboperationen) –
die Profil-Persistenz (Option B / Explicit Save) liegt separat im
`AnalyticsProfileRepository` (Schritt 2).

E-1: Das Alt-Repository `analytics/statistics_repository.py` bleibt bis auf
Weiteres unveraendert bestehen (genutzt vom Legacy-StatisticWindow); dieses
Repository ist der Ersatz fuer die neue Analytics-UI (15.03).
"""

from typing import Any, Dict, List, Optional

import numpy as np

from analytics.engine.feature_store_reader import (
    FeatureStoreReader,
)

# 19.02 (Cleanup): HEATMAP_METRICS ENTFERNT – Heatmap-Metriken sind "count"
# oder dynamische feature_data-JSON-Keys (available_feature_keys(numeric_only)).
# Die Achsen-Verfuegbarkeit wird pro Symbol/Timeframe aus dem feature_data
# abgeleitet (keine nativen Spalten mehr).


class AnalyticsRepository:
    """High-Level-Datenzugriff fuer die Analytics-UI (lesend)."""

    def __init__(self, reader: Optional[FeatureStoreReader] = None) -> None:
        self.reader = reader or FeatureStoreReader()

    # ------------------------------------------------------------------
    # Tabelle
    # ------------------------------------------------------------------
    def get_table(
        self,
        symbol: str,
        timeframe: str,
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
        limit: Optional[int] = 1000,
        # 21.03.12 (MTF-FC auf Analytics): Optionaler Zeitfilter (Wanduhr-
        # Epochs relativ zum letzten Datenpunkt; None = kein Filter).
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        # 21.03.20 (Analytics Modus-Filter): source_mode-Filter fuer
        # Multi-Modus-Services (None/"all"/leer = kein Filter).
        service_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rohe Feature-Zeilen fuer die Tabellen-Seite.

        Returns:
            {"rows": [FeatureStoreReader-Zeilen...], "total": n}
        """
        rows = self.reader.fetch_rows(
            symbol, timeframe, feature_id=feature_id, feature_ids=feature_ids,
            instance_hashes=instance_hashes, limit=limit,
            from_ts=from_ts, to_ts=to_ts,
            service_mode=service_mode)
        return {"rows": rows, "total": len(rows)}

    # ------------------------------------------------------------------
    # Heatmap (X: Wochentage, Y: Tagesstunden Berlin Wanduhr)
    # ------------------------------------------------------------------
    def get_heatmap(
        self,
        symbol: str,
        timeframe: str,
        metric: str = "count",
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
        # 21.03.12 (MTF-FC auf Analytics): Optionaler Zeitfilter (Wanduhr-
        # Epochs relativ zum letzten Datenpunkt; None = kein Filter).
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        # 21.03.20 (Analytics Modus-Filter): source_mode-Filter fuer
        # Multi-Modus-Services (None/"all"/leer = kein Filter).
        service_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """2D-Matrix (Wochentag x Tagesstunde) fuer die Heatmap-Seite.

        19.02 (Cleanup): Metrik ist "count" oder ein numerischer
        feature_data-JSON-Key (Default "count"). Unbekannte/fehlende
        JSON-Metriken fallen auf "count" zurueck (defensiv, keine ValueError-
        Haenger im UI). `metrics` liefert die verfuegbaren Metriken.

        Wanduhr-Garantie (Invariante 7): Die Extraktion von Wochentag/Stunde
        erfolgt im Reader mit `bar_time AT TIME ZONE 'UTC'` (die gespeicherten
        Werte sind Berlin-Wanduhr-encoded – die UTC-Darstellung IST die
        Wanduhr-Zeit, kein Offset).

        Returns:
            {
              "matrix":   7x24 (rows=Stunde 0-23, cols=DOW 0=So..6=Sa),
              "x_labels": Wochentage, "y_labels": Stunden,
              "metric", "metrics": ["count", ...JSON-Keys],
              "symbol", "timeframe",
            }
        """
        avail = self.reader.available_feature_keys(
            symbol, timeframe, numeric_only=True)
        metrics = ["count"] + avail
        use_metric = metric if metric in metrics else "count"
        result = self.reader.fetch_heatmap(
            symbol, timeframe, metric=use_metric, feature_id=feature_id,
            feature_ids=feature_ids, instance_hashes=instance_hashes,
            from_ts=from_ts, to_ts=to_ts,
            service_mode=service_mode
        )
        result["metrics"] = metrics
        return result

    # ------------------------------------------------------------------
    # Feld-Metadaten (Runde 15, Fix 1/3): metrics + field_sources fuer das
    # 'Feld'-Dropdown – gemeinsamer Pfad fuer QUERY_HEATMAP_GENERIC und den
    # leichten QUERY_FEATURES-Payload. `feature_keys_by_service` wird im
    # Reader gecacht (EIN DB-Scan, Invalidation via Invariante 13), damit
    # beide Aufrufer identische Metadaten OHNE Doppel-Abfrage erhalten.
    # ------------------------------------------------------------------
    def _field_metadata(
        self,
        symbol: str,
        timeframe: str,
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        instance_hashes: Optional[List[str]] = None,
    ) -> tuple:
        """Verfuegbare Feld-Metriken + Quellen-Zuordnung (Feld-Dropdown).

        09.08.2026 (User-Meldung Feld-Dropdown, Root Cause 2): Die
        Feldquellen werden STRENG ueber den feature_ids-Filter bestimmt –
        abgewaehlte Services (z. B. Grid-Lines) duerfen ihre Keys nicht
        mehr ins 'Feld'-Dropdown liefern.

        Runde 15b (Bugfix Dropdown, User-Meldung 10.08.2026): Die
        Feld-Struktur gehoert zu den SERVICES (feature_ids), NICHT zu den
        Varianten (instance_hashes) – eine gecheckte NoData-Variante
        (Hash ohne DB-Rows) darf den aktiven Service NICHT aus der
        Feld-Metadaten ausblenden (sonst greift der ungefilterte Fallback
        und das Dropdown zeigt alle Keys aller Services ohne Prefix).
        `instance_hashes` bleibt fuer die DATEN-Queries (Table/Heatmap)
        bestehen; die NoData-Variante wird separat im Payload markiert.
        Zusaetzlich greift der defensive Fallback `avail` (alle Keys)
        NUR ohne aktiven feature_ids/feature_id-Filter – bei aktivem
        Filter ist eine leere by_service-Menge ein LEGITIMES Ergebnis
        (z. B. nur String-Services selektiert) und darf nicht zu einem
        ungefilterten Dropdown fuehren.

        Returns:
            (metrics, field_sources)
              metrics:      ["count", "confluence_count"] + numerische Keys
                            der SELEKTIERTEN Services
              field_sources:{Key: [service_id...]} (nur selektierte Services)
        """
        try:
            avail = self.reader.available_feature_keys(
                symbol, timeframe, numeric_only=True)
        except Exception:
            avail = []
        try:
            # Runde 15b: KEIN instance_hashes-Filter hier (siehe oben) –
            # die Feld-Struktur folgt den aktiven Services, nicht den
            # Varianten-Hashes.
            by_service = self.reader.feature_keys_by_service(
                symbol, timeframe, numeric_only=True,
                feature_id=feature_id, feature_ids=feature_ids)
        except Exception:
            by_service = {}
        field_sources: Dict[str, List[str]] = {}
        for fid, keys in by_service.items():
            if not fid:
                continue  # Legacy-Rows ohne feature_id -> kein Service-Prefix
            for k in keys:
                field_sources.setdefault(k, []).append(fid)
        # Nur die Keys der SELEKTIERTEN Services in der Metrik-/Feldliste –
        # das HeatmapWidget baut das 'Feld'-Dropdown aus `metrics` auf
        # (_sync_combos_from_payload); ohne diese Begrenzung erschienen
        # abgewaehlte Keys weiterhin (nur ohne Service-Prefix).
        avail_filtered = sorted({k for keys in by_service.values()
                                 for k in keys})
        # Runde 15b: Fallback nur ohne aktiven Filter (echte Leer-Datenlage
        # bei 'alle Features'). Bei aktivem Filter gilt: kein Service matcht
        # -> konsistent leere Feld-Liste (kein ungefiltertes Dropdown).
        if not avail_filtered and not feature_ids and not feature_id:
            avail_filtered = avail  # defensiv: ohne Filter -> ungefiltert
        return (["count", "confluence_count"] + avail_filtered, field_sources)

    # ------------------------------------------------------------------
    # Generische 2D-Heatmap (20.02, additiv – Kapitel §2 / Review E1/E5/E6)
    # ------------------------------------------------------------------
    def get_generic_heatmap(
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
        # Runde 12 (Option A): Preset-Modell-Snapshot fuer die No-Data-
        # Auswertung im selben Worker (kein separater QUERY_FEATURES-
        # Roundtrip mehr; Payload-Attribut no_data_variants).
        presets_data: Optional[Dict[str, Any]] = None,
        # 21.01 (E1, 11.08.2026): TF-Freigabe fuer Timeframe-Matrizen
        # (Preset `[📊 Service-Timeframe]`) – wird an den Reader gereicht.
        all_timeframes: bool = False,
        # 21.03.12 (MTF-FC auf Analytics, Entscheidung 6a): Aggregations-TF
        # fuer das date-Raster (z. B. 'M15'/'H1'; 'auto'/None = kein
        # Bucketing) + optionaler Zeitfilter (Wanduhr-Epochs).
        bucket_tf: Optional[str] = None,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        # 12.08.2026 (Option A, Bug 1/2): (Service|Parameter)-Paar-Filter
        # ('{service_id}|{key}') des 'Feld'-Dropdowns - der Reader filtert
        # auf PARAMETER-Ebene (feature_data-JSON-Keys je Service). Leer/
        # None = kein Paar-Filter (reines feature_ids-Verhalten).
        field_pairs: Optional[List[str]] = None,
        # 21.03.20 (Analytics Modus-Filter): source_mode-Filter fuer
        # Multi-Modus-Services (None/"all"/leer = kein Filter).
        service_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generische 2D-Matrix (freie Dimensionen + Aggregationen, 20.02).

        Additiv zur bestehenden get_heatmap() (Dow×Stunde bleibt Standard).
        Wanduhr-Garantie (Invariante 7 / E4) wie fetch_heatmap – die
        Extraktion erfolgt im Reader mit `bar_time AT TIME ZONE 'UTC'`.

        21.01 (E1): `all_timeframes=True` entfaellt die TF-WHERE-Bedingung –
        Grundlage des Presets `[📊 Service-Timeframe]` (X = `timeframe`,
        Y = `service_id`, agg = `count`). `timeframe` bleibt fuer den
        Normalpfad erhalten.

        Returns:
            {
              "matrix": dense M x N, "x_labels"/"y_labels", "x_values",
              "min_val"/"max_val", "x_dim"/"y_dim"/"agg"/"field",
              "metrics": ["count", "confluence_count", ...numerische JSON-Keys],
              "field_sources": {Key: [service_id...]} (20.02.01, Meldung 3b),
              "symbol", "timeframe",
            }
        """
        # Runde 15 (Fix 1/3): Gemeinsamer Feld-Metadaten-Pfad
        # (_field_metadata) – metrics + field_sources kommen aus dem
        # gecachten Reader-Basis-Scan (EIN DB-Scan; der QUERY_FEATURES-
        # Leichtpfad liefert identische Metadaten OHNE die teure
        # Heatmap-Pivot-Aggregation).
        metrics, field_sources = self._field_metadata(
            symbol, timeframe, feature_id=feature_id, feature_ids=feature_ids,
            instance_hashes=instance_hashes)
        # Numerische Keys aus den Metadaten (ohne count/confluence_count) –
        # Grundlage des E6-Fallbacks fuer Wert-Aggregationen.
        avail_filtered = [m for m in metrics
                          if m not in ("count", "confluence_count")]
        use_agg = str(agg or "count").lower()
        use_field = str(field or "")
        # E6: Bei Wert-Aggregationen (AVG/SUM/MIN/MAX) ist `field` ein
        # numerischer JSON-Key – defensiv auf den ersten verfuegbaren Key
        # zurueckfallen (keine ValueError-Haenger im UI).
        if use_agg in ("avg", "sum", "min", "max"):
            if use_field not in avail_filtered:
                use_field = avail_filtered[0] if avail_filtered else ""
        try:
            result = self.reader.fetch_generic_heatmap(
                symbol, timeframe, x_dim, y_dim, field=use_field or None,
                agg=use_agg, feature_id=feature_id, feature_ids=feature_ids,
                instance_hashes=instance_hashes, limit=limit,
                all_timeframes=all_timeframes,
                bucket_tf=bucket_tf, from_ts=from_ts, to_ts=to_ts,
                field_pairs=field_pairs,
                service_mode=service_mode,
            )
        except ValueError as e:
            print(f"WARN [AnalyticsRepository] get_generic_heatmap: {e}")
            result = self.reader._empty_generic_heatmap(
                x_dim, y_dim, use_agg, use_field or None, symbol, timeframe)
        result["metrics"] = metrics
        result["field_sources"] = field_sources
        # Runde 12 (Option A): No-Data-Varianten im SELBEN Payload wie die
        # Grafik (kein zweiter Worker-Roundtrip). Payload-Vertrag (Runde 11,
        # B4-2): no_data_variants IMMER vorhanden; no_data_variants_error
        # markiert einen fehlgeschlagenen Check.
        no_data_error = False
        try:
            variants = self.reader.resolve_no_data_variants(
                symbol, timeframe, presets_data or {})
        except Exception as e:
            print(f"WARN [AnalyticsRepository] get_generic_heatmap "
                  f"no_data_variants: {e}")
            variants = []
            no_data_error = True
        if isinstance(variants, list):
            result["no_data_variants"] = [dict(v) for v in variants]
        else:
            result["no_data_variants"] = []
        result["no_data_variants_error"] = no_data_error
        return result

    # ------------------------------------------------------------------
    # OHLCV-Snapshot fuer das Candle-Overlay (20.02, E9)
    # ------------------------------------------------------------------
    def get_ohlcv_snapshot(
        self,
        symbol: str,
        timeframe: str,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """OHLCV-Bars aus market_data.duckdb (read-only, Wanduhr-Epochs).

        20.02 (E9): Read-only-Delegation an den FeatureStoreReader – kein SQL
        in der UI. Der Preis-Strip im HeatmapWidget gruppiert die Bars pro
        Datums-Spalte zu Tages-Ohlc.

        Returns:
            {"bars": [{"time": int, "open": float, "high": float,
                       "low": float, "close": float, "volume": float}, ...],
             "symbol", "timeframe"}
        """
        return self.reader.fetch_ohlcv_snapshot(symbol, timeframe, limit=limit)

    # 20.02-Bugfix (09.08.2026, Punkt 1+2): Tages-Ohlc fuer das Candle-Overlay
    # im selben Canvas – SQL-seitig aggregiert (deckt den gesamten
    # Heatmap-Zeitraum ab, statt nur der letzten OHLCV_SNAPSHOT_LIMIT Bars).
    def get_daily_ohlc(
        self,
        symbol: str,
        timeframe: str,
        max_days: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Tages-Ohlc je Wanduhr-Datum (read-only, Wanduhr-Mitternachts-Epochs).

        20.02-Bugfix: Additive Alternative zum OHLCV-Snapshot – das
        HeatmapWidget zeichnet die Tages-Candles ueber die Heatmap-Zellen
        (gleicher Canvas, rechte Preis-Achse). Kein SQL in der UI.

        Returns:
            {"bars": [{"time": int(Wanduhr-Mitternachts-Epoch), "open": float,
                       "high": float, "low": float, "close": float}, ...],
             "symbol", "timeframe"}
        """
        return self.reader.fetch_daily_ohlc(symbol, timeframe, max_days=max_days)

    # ------------------------------------------------------------------
    # Scatter
    # ------------------------------------------------------------------
    def get_scatter(
        self,
        symbol: str,
        timeframe: str,
        x_column: Optional[str] = None,
        y_column: Optional[str] = None,
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
        """X/Y-Paare zweier feature_data-JSON-Keys fuer die Scatter-Seite.

        19.02 (Cleanup): Achsen sind dynamische JSON-Keys aus `feature_data`
        (nicht mehr native DB-Spalten). Defaults: die ersten beiden
        numerischen Keys der aktuellen Datenlage (x != y). Rows mit NULL/
        nicht-numerischem Wert in einer Achse werden ausgelassen.

        Returns:
            {"points": [{"x": float, "y": float}, ...],
             "x_label": x_column, "y_label": y_column,
             "columns": [verfuegbare numerische JSON-Keys...],
             "symbol", "timeframe", "total": n}
        """
        avail = self.reader.available_feature_keys(
            symbol, timeframe, numeric_only=True)
        if not avail:
            return {
                "points": [], "x_label": "", "y_label": "", "columns": [],
                "symbol": symbol, "timeframe": timeframe, "total": 0,
            }
        x_col = x_column if x_column in avail else avail[0]
        y_candidates = [c for c in avail if c != x_col]
        y_col = y_column if y_column in avail and y_column != x_col \
            else (y_candidates[0] if y_candidates else x_col)

        rows = self.reader.fetch_columns(
            symbol, timeframe, [x_col, y_col],
            feature_id=feature_id, feature_ids=feature_ids,
            instance_hashes=instance_hashes, limit=limit,
            from_ts=from_ts, to_ts=to_ts,
            service_mode=service_mode,
        )
        points: List[Dict[str, float]] = []
        for r in rows:
            xv = r.get(x_col)
            yv = r.get(y_col)
            if xv is None or yv is None:
                continue
            if not (np.isfinite(xv) and np.isfinite(yv)):
                continue
            points.append({"x": xv, "y": yv})
        return {
            "points": points,
            "x_label": x_col,
            "y_label": y_col,
            "columns": avail,
            "symbol": symbol,
            "timeframe": timeframe,
            "total": len(points),
        }

    # ------------------------------------------------------------------
    # Verteilung
    # ------------------------------------------------------------------
    def get_distribution(
        self,
        symbol: str,
        timeframe: str,
        column: Optional[str] = None,
        bins: int = 20,
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
        """Histogramm eines feature_data-JSON-Keys fuer die Verteilungs-Seite.

        19.02 (Cleanup): Die Spalte ist ein dynamischer JSON-Key aus
        `feature_data` (Default: erster numerischer Key der Datenlage).
        Berechnet bin-Edges + counts mit numpy.histogram (NaN-/Inf-Werte
        werden ausgelassen).

        Returns:
            {"bins": [edges...], "counts": [n...], "column": column,
             "columns": [verfuegbare numerische JSON-Keys...],
             "symbol", "timeframe", "total": n}
        """
        avail = self.reader.available_feature_keys(
            symbol, timeframe, numeric_only=True)
        col = column if column in avail else (avail[0] if avail else "")
        try:
            n_bins = max(2, int(bins))
        except (TypeError, ValueError):
            n_bins = 20

        if not col:
            return {
                "bins": [], "counts": [], "column": "", "columns": avail,
                "symbol": symbol, "timeframe": timeframe, "total": 0,
            }

        rows = self.reader.fetch_columns(
            symbol, timeframe, [col], feature_id=feature_id,
            feature_ids=feature_ids, instance_hashes=instance_hashes,
            limit=limit, from_ts=from_ts, to_ts=to_ts,
            service_mode=service_mode,
        )
        values = [r[col] for r in rows if r.get(col) is not None]
        values = [v for v in values if np.isfinite(v)]
        if not values:
            return {
                "bins": [], "counts": [], "column": col, "columns": avail,
                "symbol": symbol, "timeframe": timeframe, "total": 0,
            }

        counts, bin_edges = np.histogram(values, bins=n_bins)
        return {
            "bins": [float(e) for e in bin_edges],
            "counts": [int(c) for c in counts],
            "column": col,
            "columns": avail,
            "symbol": symbol,
            "timeframe": timeframe,
            "total": len(values),
        }

    # ------------------------------------------------------------------
    # Jump-to-Chart (15.03 Schritt 5, Variante 2: open_chart_at_bar)
    # ------------------------------------------------------------------
    def get_latest_bar_time(
        self,
        symbol: str,
        timeframe: str,
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch (int) der Feature-Rows (oder None).

        Fuer 'Jump-to-Chart' aus Scatter (ein Klick auf einen Punkt oeffnet
        das Chart an der neuesten Feature-Bar des Symbol/Timeframe).
        """
        return self.reader.fetch_latest_bar_time(
            symbol, timeframe, feature_id=feature_id, feature_ids=feature_ids,
            instance_hashes=instance_hashes
        )

    def get_recent_bar_time_for_cell(
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

        Fuer 'Jump-to-Chart' aus der Heatmap: Doppelklick auf eine Zelle
        (Wochentag x Tagesstunde) oeffnet das Chart an der neuesten
        Feature-Bar dieser Zelle (Wanduhr-Garantie, Invariante 7).
        """
        return self.reader.fetch_recent_bar_time_for_cell(
            symbol, timeframe, dow, hour,
            feature_id=feature_id, feature_ids=feature_ids,
            instance_hashes=instance_hashes
        )

    # ------------------------------------------------------------------
    # Metadaten
    # ------------------------------------------------------------------
    def available_timeframes(self, symbol: str) -> List[str]:
        """Timeframes mit Feature-Store-Daten fuer ein Symbol (TF-Ausgrauung)."""
        return self.reader.get_available_timeframes(symbol)

    def get_available_features(
        self,
        symbol: str,
        timeframe: str,
        presets_data: Optional[Dict[str, Any]] = None,
        # Runde 15 (Fix 1): feature_ids/instance_hashes fuer die Feld-
        # Metadaten (metrics/field_sources) im QUERY_FEATURES-Leichtpfad.
        feature_ids: Optional[List[str]] = None,
        instance_hashes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Verfuegbare Plugin-IDs, JSON-Keys, Zeilenzahl + No-Data-Varianten.

        Runde 11 (Bug 4, B4-1/B4-2): `no_data_variants` ist IMMER Teil des
        Payload-Vertrags (leere Liste, wenn keine Varianten ohne Daten
        existieren oder die Auswertung fehlschlaegt; `no_data_variants_error`
        markiert einen Fehlschlag). Die Auswertung laeuft hier (Worker-
        Thread), nicht im UI-Hauptthread.

        Runde 15 (Fix 1, Ultra-Low-Latency): Zusaetzlich traegt der Payload
        `metrics` + `field_sources` (Feld-Metadaten, identisch zu
        get_generic_heatmap) – das 'Feld'-Dropdown + die '(No Data)'-Hinweise
        kommen damit ueber den LEICHTEN Metadaten-Query (Reader-Cache, kein
        Heatmap-Pivot), getrennt von der Grafik.
        """
        result = self.reader.get_available_features(symbol, timeframe)
        if not isinstance(result, dict):
            result = {}
        # Runde 15 (Fix 1): Feld-Metadaten (metrics/field_sources) ueber
        # denselben Reader-Basis-Scan wie die Heatmap (cache-served).
        metrics, field_sources = self._field_metadata(
            symbol, timeframe, feature_ids=feature_ids,
            instance_hashes=instance_hashes)
        result["metrics"] = metrics
        result["field_sources"] = field_sources
        # 21.03.20 (Analytics Modus-Filter): source_modes +
        # Deaktivierungs-Flag im LEICHTEN QUERY_FEATURES-Payload
        # (Modus-Dropdown im HeatmapWidget; gecachter Reader-Basis-
        # Scan, kein zusaetzlicher Roundtrip).
        try:
            source_modes, has_sm = (
                self.reader.fetch_available_source_modes(
                    symbol, timeframe, feature_ids=feature_ids,
                    instance_hashes=instance_hashes))
        except Exception:
            source_modes, has_sm = [], False
        result["source_modes"] = source_modes
        result["has_source_mode_services"] = has_sm
        no_data_error = False
        try:
            variants = self.reader.resolve_no_data_variants(
                symbol, timeframe, presets_data or {})
        except Exception as e:
            print(f"WARN [AnalyticsRepository] no_data_variants "
                  f"fehlgeschlagen: {e}")
            variants = []
            no_data_error = True
        if isinstance(variants, list):
            result["no_data_variants"] = [dict(v) for v in variants]
        else:
            result["no_data_variants"] = []
        result["no_data_variants_error"] = no_data_error
        return result

    def available_heatmap_metrics(
        self, symbol: str, timeframe: str
    ) -> List[str]:
        """Verfuegbare Heatmap-Metriken fuer ein Symbol/Timeframe (19.02).

        "count" + numerische feature_data-JSON-Keys (dynamisch). Ohne Daten
        liefert die Methode ["count"] (defensiver Fallback fuer die UI).
        """
        try:
            keys = self.reader.available_feature_keys(
                symbol, timeframe, numeric_only=True)
        except Exception:
            keys = []
        return ["count"] + list(keys)

    def available_feature_columns(
        self, symbol: str, timeframe: str
    ) -> List[str]:
        """Numerische feature_data-JSON-Keys (Scatter-/Verteilungs-Dropdowns).

        19.02 (Cleanup): Ersetzt die entfernten nativen Spalten. Defensiv:
        Fehler/leere Daten -> [] (UI kann dann leer starten und fuellt die
        Combos aus dem ersten Daten-Payload).
        """
        try:
            return self.reader.available_feature_keys(
                symbol, timeframe, numeric_only=True)
        except Exception:
            return []
