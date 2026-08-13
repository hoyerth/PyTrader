# PROJEKT-ÜBERSICHT: PyTrader — Analytics-UI & Feature Store

> Teil-Export (sachbezogen). Vollständiger Export: export_Full.md
> Dateien in dieser Datei: 13

## 1. ORDNERSTRUKTUR
```
PyTrader/
    analytics/
        engine/
            analytics_repository.py
            analytics_view_model.py
            analytics_worker.py
            feature_store_reader.py
        ui/
            __init__.py
            analytics_win.py
            common.py
            distribution_page.py
            equity_page.py
            heatmap_page.py
            heatmap_widget.py
            scatter_page.py
            table_page.py
```

## 2. QUELLCODE

### DATEI: analytics/engine/analytics_repository.py
```py
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

from typing import Any, Dict, List, Optional, Set

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
        # 21.03.20-Bugfix 3: Modus-Filter (modus-spezifische Keys).
        service_mode: Optional[str] = None,
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
                feature_id=feature_id, feature_ids=feature_ids,
                service_mode=service_mode)
        except Exception:
            by_service = {}
        # 21.03.20-Bugfix 3: Modus-Fallback - ist ein Modus gewaehlt, aber
        # noch nicht in der DB berechnet (leere modus-gefilterte Keys),
        # werden die nicht-technischen output_schema-Keys der selektierten
        # Services als Ergebnis-Parameter vorgeschlagen (Param-Box bleibt
        # nutzbar; der konkrete Modus kann danach berechnet/ausgefuehrt
        # werden). Muster _registry_service_mode_pairs (Registry, rein
        # lesend, Fehler defensiv).
        use_mode = (str(service_mode or "").strip()
                    if str(service_mode or "").strip().lower()
                    not in ("all", "alle") else "")
        if use_mode and not by_service:
            try:
                fallback_keys = self._registry_output_keys(
                    feature_ids, feature_id)
            except Exception:
                fallback_keys = {}
            if fallback_keys:
                by_service = fallback_keys
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
        # 13.08.2026 (Punkte 1b+8, F1/F8): `service_mode` wird jetzt DURCH-
        # gereicht - vorher ueberschrieb das QUERY_HEATMAP_GENERIC-Payload
        # die modus-gefilterte Feld-Liste aus QUERY_FEATURES (die
        # Parameter-Box zeigte die falschen/ungefilterten Keys).
        metrics, field_sources = self._field_metadata(
            symbol, timeframe, feature_id=feature_id, feature_ids=feature_ids,
            instance_hashes=instance_hashes, service_mode=service_mode)
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
        # 21.03.20-Bugfix 3: Fehlende Registry-Modi als Achsenpunkte.
        # 13.08.2026 (Punkt 1a, F1): Die Ergaenzung greift JETZT AUCH bei
        # konkretem Modus-Filter - die Registry-Paare werden dann auf den
        # gewaehlten Modus gefiltert. Vorher blieb die service_id-Achse bei
        # konkretem Modus auf die DB-geschriebenen Kombinationen begrenzt
        # (ein noch nicht berechneter Modus erzeugte KEINEN Achsenpunkt,
        # obwohl der Modus im Dropdown waehlbar war).
        extra_service_modes = None
        mode_raw = str(service_mode or "").strip()
        mode_key = mode_raw.lower()
        try:
            if mode_key in ("", "all", "alle"):
                extra_service_modes = sorted(
                    self._registry_service_mode_pairs(
                        feature_ids, feature_id))
            elif mode_raw:
                extra_service_modes = sorted(
                    p for p in self._registry_service_mode_pairs(
                        feature_ids, feature_id)
                    if "::" in p
                    and p.rsplit("::", 1)[1].strip().lower() == mode_key)
        except Exception:
            extra_service_modes = None
        try:
            result = self.reader.fetch_generic_heatmap(
                symbol, timeframe, x_dim, y_dim, field=use_field or None,
                agg=use_agg, feature_id=feature_id, feature_ids=feature_ids,
                instance_hashes=instance_hashes, limit=limit,
                all_timeframes=all_timeframes,
                bucket_tf=bucket_tf, from_ts=from_ts, to_ts=to_ts,
                field_pairs=field_pairs,
                service_mode=service_mode,
                extra_service_modes=extra_service_modes,
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

    @staticmethod
    def _registry_service_mode_pairs(
        feature_ids: Optional[List[str]],
        feature_id: Optional[str] = None,
    ) -> Set[str]:
        """'{feature_id}::{mode}'-Kombinationen der aktiven Services.

        21.03.20-Bugfix 2/3: Liest parameter_schema["mode"]["options"]
        der gewaehlten Services (PluginRegistry-Singleton, in-Memory).
        Leere feature_ids = alle Services (Multi-Modus-faehige Plugins
        tragen einen "mode"-Key mit nicht-leeren options). Format
        `{plugin_id.lower()}::{mode}` (case-originaler Modus) - deckungs-
        gleich mit der service_id-Achsen-Expression des Readers. Rein
        lesend, kein DB-Zugriff; Fehler defensiv abgefangen.
        """
        try:
            from analytics.features.feature_builder import PluginRegistry
            reg = PluginRegistry()
        except Exception:
            return set()
        wanted = {str(i).strip().lower() for i in (feature_ids or [])
                  if str(i).strip()}
        if not wanted and feature_id:
            wanted = {str(feature_id).strip().lower()}
        out: Set[str] = set()
        try:
            plugins = reg.plugins or {}
            for pid, plugin in plugins.items():
                if wanted and str(pid).strip().lower() not in wanted:
                    continue
                schema = getattr(plugin, "parameter_schema", None) or {}
                mode_cfg = schema.get("mode") or {}
                options = [str(o).strip() for o in (mode_cfg.get("options")
                                                    or []) if str(o).strip()]
                if options:
                    pid_l = str(pid).strip().lower()
                    for m in options:
                        out.add(f"{pid_l}::{m}")
        except Exception:
            pass
        return out

    @classmethod
    def _registry_output_keys(
        cls,
        feature_ids: Optional[List[str]],
        feature_id: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        """Nicht-technische output_schema-Keys je Service (Registry).

        21.03.20-Bugfix 3: Fallback fuer die Parameter-Box (Feld-Dropdown),
        wenn der gewaehlte Modus noch nicht in der DB berechnet wurde
        (leere modus-gefilterte field_sources). `output_schema`-Felder mit
        `technical: True` (System-Metrik) werden ausgeschlossen. Rein
        lesend, kein DB-Zugriff; Fehler defensiv leer.
        """
        try:
            from analytics.features.feature_builder import PluginRegistry
            reg = PluginRegistry()
        except Exception:
            return {}
        wanted = {str(i).strip().lower() for i in (feature_ids or [])
                  if str(i).strip()}
        if not wanted and feature_id:
            wanted = {str(feature_id).strip().lower()}
        out: Dict[str, List[str]] = {}
        try:
            plugins = reg.plugins or {}
            for pid, plugin in plugins.items():
                if wanted and str(pid).strip().lower() not in wanted:
                    continue
                schema = getattr(plugin, "output_schema", None) or {}
                keys = [k for k, v in schema.items()
                        if k and not (v or {}).get("technical")]
                if keys:
                    out[str(pid)] = sorted(keys)
        except Exception:
            pass
        return out

    @classmethod
    def _registry_source_modes(
        cls,
        feature_ids: Optional[List[str]],
        feature_id: Optional[str] = None,
    ) -> Set[str]:
        """Mogliche source_mode-Werte der aktiven Services (Registry).

        21.03.20-Bugfix 2: UNION-Quelle fuer das Modus-Dropdown (alle
        waehlbaren Modi statt nur der DB-geschriebenen). Abgeleitet aus
        `_registry_service_mode_pairs` (eine Registry-Sammlung).
        """
        pairs = cls._registry_service_mode_pairs(feature_ids, feature_id)
        modes: Set[str] = set()
        for p in pairs:
            if "::" in p:
                modes.add(p.split("::", 1)[1])
        return modes

    def get_available_features(

        self,
        symbol: str,
        timeframe: str,
        presets_data: Optional[Dict[str, Any]] = None,
        # Runde 15 (Fix 1): feature_ids/instance_hashes fuer die Feld-
        # Metadaten (metrics/field_sources) im QUERY_FEATURES-Leichtpfad.
        feature_ids: Optional[List[str]] = None,
        instance_hashes: Optional[List[str]] = None,
        # 21.03.20-Bugfix 3: Modus-Filter (modus-spezifische Keys).
        service_mode: Optional[str] = None,
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
            instance_hashes=instance_hashes,
            service_mode=service_mode)
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
        # 21.03.20-Bugfix 2: UNION der Registry-Modi. Die DB-geschriebenen
        # source_mode-Werte decken nur die tatsaechlich ausgefuehrten Modi
        # ab (meist der Default); parameter_schema["mode"]["options"] der
        # aktiven Services enthaelt ALLE moeglichen Modi (z. B. Swing
        # Momentum: MA_Peak_Hysteresis/MA_Slope_Change/Chande_Kroll_Ratchet).
        # Das Modus-Dropdown zeigt damit alle waehlbaren Modi; ein noch
        # nicht berechneter Modus liefert bei Auswahl konsistent leere
        # Zellen (Entscheidung 3, kein Crash). In-Memory-Registry-Singleton
        # (Worker-Thread, kein DB-Roundtrip).
        registry_modes = self._registry_source_modes(feature_ids)
        if registry_modes:
            merged = list(dict.fromkeys(
                [str(m) for m in (source_modes or [])]
                + sorted(registry_modes)))
            result["source_modes"] = merged
        else:
            result["source_modes"] = source_modes
        result["has_source_mode_services"] = bool(
            has_sm or registry_modes)
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

```

--------------------------------------------------

### DATEI: analytics/engine/analytics_view_model.py
```py
# analytics/engine/analytics_view_model.py
"""
analytics_view_model.py - AnalyticsViewModel (Phase 15.03 Schritt 4).

Vermittelt zwischen `AnalyticsRepository` (+ `FeatureStoreReader`), dem
asynchronen `AnalyticsAsyncWorker` und den UI-Pages (analytics/ui/*,
Invariante 4 / MVVM). KEIN SQL, KEIN UI-Code – nur Qt-Core (QObject/QTimer)
und Repositories. Datenfluss:

    UI-Page -> set_*()/request_*() -> ViewModel (Debounce-QTimer 250 ms)
    -> AnalyticsAsyncWorker (QThread) -> data_ready(query_kind, data)

Aufgaben (15.03-Spezifikation):
1. Datenfluss: UI-Pages fordern Daten ueber `request_*()` an; der ViewModel
   puffert die aktuellen Parameter, debounced (QTimer, 200-300 ms) und
   startet bei Bedarf einen Async-Worker. Parameternaenderungen (Slider
   usw.) feuern die betroffenen Abfragen automatisch nach.
2. Profil-Verwaltung (Option B – Explicit Save): Aktives Profil via
   `AnalyticsProfileRepository`; Parametertrends setzen das Dirty-Flag
   (`*` im Titel/Combo); gespeichert wird erst auf `save_profile()`.
3. Max-Lookback-Cap: `MAX_LOOKBACK_LIMIT = 50_000` (hart, 15.03-Spez).
4. EventBus: Profilwechsel wird auf `event_bus.profile_changed(str)`
   emittiert (Invariante 5 / zentraler EventBus, Payload = Profil-Name).
"""

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from PySide6.QtCore import QObject, QTimer, Signal

from analytics.engine.analytics_repository import AnalyticsRepository
from analytics.engine.analytics_worker import (
    QUERY_TABLE,
    QUERY_HEATMAP,
    QUERY_HEATMAP_GENERIC,
    QUERY_OHLCV,
    QUERY_DAILY_OHLC,
    QUERY_SCATTER,
    QUERY_DISTRIBUTION,
    QUERY_FEATURES,
    MAX_LOOKBACK_LIMIT,
    AnalyticsAsyncWorker,
)
from analytics_profile_repository import (
    AnalyticsProfileRepository,
    get_analytics_profile_repository,
    SCHEMA_VERSION_DEFAULT,
)
from config.event_bus import event_bus

# QTimer-Debounce (15.03-Spezifikation: 200-300 ms) gegen SQL-Feuer.
DEBOUNCE_MS = 250

# Default-Parameter (Anfangs-Parametrisierung der Analytics-Ansichten).
DEFAULT_BINS = 20
DEFAULT_LIMIT = 5000

# 21.03.12 (MTF-FC auf Analytics): Alle Haupt-Queries, die beim data_tf-
# Wechsel neu angestossen werden (OHLCV/DAILY_OHLC sind on-demand und
# folgen keinem Filterwechsel - identisch zur refresh_all()-Liste).
_ALL_QUERIES = (QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                QUERY_SCATTER, QUERY_DISTRIBUTION, QUERY_FEATURES)


class AnalyticsViewModel(QObject):
    """MVVM-ViewModel der Analytics-Engine (kein SQL, kein UI)."""

    # Datenfluss-Signale (query_kind -> Ergebnis/Fehler)
    data_ready = Signal(str, dict)
    query_failed = Signal(str, str)
    busy_changed = Signal(bool)  # Progress-Spinner an/aus

    # Profil-Signale (Option B – Explicit Save)
    active_profile_changed = Signal(object)  # Profil-Dict oder None
    dirty_changed = Signal(bool)             # '*' im Titel/Combo
    profile_saved = Signal(str)              # profile_id
    profile_deleted = Signal(str)            # profile_id
    profiles_available = Signal(list)        # Liste der Profile

    # 20.01 (Graceful Degradation, E5): fehlende (entfernte/umbenannte)
    # Services – Payload: Liste der nicht mehr registrierten plugin_ids.
    missing_services_detected = Signal(list)

    # 20.04-Timing-Fix (D): Nach restore_workspace()/_apply_profile() – die
    # UI-Pages synchronisieren ihre Combos explizit aus den restaurierten
    # VM-Params (kein UI-Import im ViewModel, MVVM-Invariante 4).
    params_restored = Signal()

    # Runde 8 (Bugfix 4, 10.08.2026): feature_ids-Aenderungen (ServicePicker
    # Check/Uncheck) SYNCHRON an die UI – das HeatmapWidget leitet sein
    # 'Feld'-Dropdown sofort aus den gecachten Feld-Metadaten + den neuen
    # feature_ids neu ab (kein Debounce/Query-Round-Trip noetig). Wird in
    # set_feature_ids() NACH der Uebernahme emittiert (idempotent: nur bei
    # echter Aenderung). Restore-Pfade setzen _params["feature_ids"] DIREKT
    # und emittieren stattdessen params_restored (kein Dirty/Doppel-Refresh).
    feature_ids_changed = Signal()

    def __init__(
        self,
        analytics_repo: Optional[AnalyticsRepository] = None,
        profile_repo: Optional[AnalyticsProfileRepository] = None,
        selector_model=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._repo = analytics_repo or AnalyticsRepository()
        self._profile_repo = profile_repo or get_analytics_profile_repository()
        # 20.01 (E5): ServiceSelectorModel fuer den Fault-Tolerant-Resolver
        # (resolve_valid_feature_ids). Lazy Default – wird nur bei Bedarf
        # instanziiert (Tests/Alt-Aufrufer ohne Injektion bleiben schlank).
        self._selector_model = selector_model

        # Aktuelle Ansichtsparameter (werden im Profil-Payload persistiert).
        self._params: Dict[str, Any] = {
            "symbol": "",
            "timeframe": "M1",
            # 15.03-E (Multi-Select): feature_ids = Liste der plugin_ids
            # (Datenquellen-Filter, `WHERE feature_id IN (...)`); leer = alle.
            "feature_ids": [],
            # Runde 10 (Bug 1): Varianten-Einschraenkung (instance_hashes
            # der gecheckten Clone-Varianten; leer = alle Varianten der
            # gewaehlten plugin_ids).
            "instance_hashes": [],
            # 19.02 (Cleanup): Keine festen Legacy-Spalten-Defaults mehr –
            # scatter_x/scatter_y/distribution_column werden beim ersten
            # Daten-Payload auf die verfuegbaren feature_data-JSON-Keys
            # aufgeloest (Repo-Defaults). Leer = Repo waehlt die ersten
            # numerischen Keys.
            "heatmap_metric": "count",
            "scatter_x": "",
            "scatter_y": "",
            "distribution_column": "",
            "bins": DEFAULT_BINS,
            "limit": DEFAULT_LIMIT,
            # 20.02 (E1/E3/E8/E10, generische 2D-Heatmap): Konfiguration der
            # generischen Heatmap – x/y-Dimensionen (DIM_MAPPINGS), Aggregation
            # und numerischer feature_data-JSON-Key (`field`, E6). Defaults
            # laut Kapitel: Confluence-Modus (CONFLUENCE_COUNT) auf
            # Datum×Stunde. `selected_feature_ids` entfaellt (E10: Redundanz
            # zu feature_ids). Zoom = normalisierte Viewport-Anteile [0,1]
            # (E8), rein client-seitig (kein DB-Requery).
            "heatmap_x_dim": "date",
            "heatmap_y_dim": "hour",
            "heatmap_field": "",
            "heatmap_agg": "confluence_count",
            # 21.01 (E1, 11.08.2026): TF-Freigabe – True entfaellt die
            # TF-WHERE-Bedingung der generischen Heatmap (Preset
            # `[📊 Service-Timeframe]`: alle Zeitebenen M1..D1 in EINER
            # Query). Persistiert im Profil-Payload (charts.heatmap).
            "heatmap_all_timeframes": False,
            "candle_projection_enabled": False,
            "zoom_x_range": [0.0, 1.0],
            "zoom_y_range": [0.0, 1.0],
            # 19.03 (Step 2): TablePage-Settings – reine UI-Zustaende ohne
            # DB-Abfrage. Persistiert im Profil-Payload (Option B – Explicit
            # Save); set_table_settings() markiert nur dirty (E6, kein
            # Query-Refresh). Spaltenbreiten {Spaltenname: Breite} (E5),
            # Zeilenhoehe als Default-Section-Size (E9), Sortier-Spalte und
            # -Richtung als Qt-Werte (E8; 1 = DescendingOrder = Zeit absteigend).
            "table_column_widths": {},
            "table_row_height": 0,
            "table_sort_column": 0,
            "table_sort_order": 1,
            # 21.03.12 (MTF-FC auf Analytics): Filterleisten-Parameter des
            # MtfFilterBarWidget. `data_tf` = Analysequelle ('multi' = alle
            # TFs in einer Query via all_timeframes; sonst fixierter TF, der
            # den `timeframe`-Filter uebernimmt). `agg_tf` = Aggregations-TF
            # (Entscheidung 6a: 'auto' oder konkreter TF fuer das Zeitraster
            # der generischen Heatmap). `range_from`/`range_to` = optionaler
            # Zeitfilter (bar_time BETWEEN), Basis = letzter Datenpunkt.
            "data_tf": "multi",
            "agg_tf": "auto",
            "range_preset": None,
            "range_from": None,
            "range_to": None,
            # 21.03.12: Von set_data_tf() verwaltetes Flag - True = alle
            # Timeframes in EINER Query (data_tf='multi'), False = fixierter
            # TF. Separates Flag von heatmap_all_timeframes (21.01-Preset).
            "all_timeframes": False,
            # 21.03.14 (Wunsch 2): Tabellen-Sortierung des MtfFilterBarWidget
            # ('date' | 'signal' | 'tf'). Reiner UI-Zustand (kein SQL-Filter);
            # wird im Profil-Payload (Sektion sources) persistiert und beim
            # Profil-/Workspace-Restore ueber die Filterleiste restauriert
            # (nach dem Rueckbau der View-Template-Buttons).
            "sort_mode": "date",
            # 21.03.20 (Analytics Modus-Filter): source_mode-Filter fuer
            # Multi-Modus-Services. Default "all" = kein Filter (alle Modi).
            # Wirkt GLOBAL auf alle Analytics-Datenquellen (Entscheidung 1);
            # wird in der sources-Sektion des Profil-Payloads persistiert.
            "service_mode": "all",
        }
        self._pending_kinds: List[str] = []
        self._worker: Optional[AnalyticsAsyncWorker] = None
        self._dirty = False
        self._active_profile: Optional[Dict[str, Any]] = None
        self._profiles: List[Dict[str, Any]] = []
        # 20.01 (E7): UI-Layout-Anteil des zuletzt restaurierten Workspace
        # (z. B. {"page_index": 2}) – von der UI abfragbar, kein _params-Key.
        self._workspace_layout: Dict[str, Any] = {}
        # 10.08.2026 (Punkte 3/4): UI-Layout-Anteil fuer die PROFIL-
        # Persistenz (page_index, heatmap_mode) - die UI uebergibt ihn vor
        # jedem save_profile()/create_profile() via set_ui_layout(); die
        # Werte wandern ueber _current_payload() (Sektion "layout") in den
        # Profil-Payload und werden in _apply_profile() in _workspace_layout
        # abgelegt (die UI liest sie dort - identischer Pfad wie der
        # Workspace-Restore).
        self._ui_layout: Dict[str, Any] = {}
        # Runde 8 (Bugfix 3, 10.08.2026): Generations-Token gegen
        # Stale-Payloads - wird bei JEDEM restore_workspace()/
        # _apply_profile() erhoeht und wandert ueber _current_params() in
        # die Worker-Params. Der Worker spiegelt es ins Ergebnis-Dict
        # (data["restore_generation"]); die UI verwirft Payloads aelterer
        # Generation (Queries, die VOR dem Restore gestartet wurden,
        # duerfen den synchron restaurierten Zustand nicht ueberschreiben).
        self._restore_generation: int = 0

        # Debounce-QTimer (200-300 ms, 15.03-Spezifikation)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._debounce.timeout.connect(self._start_next_query)

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------
    def shutdown(self) -> None:
        """Stoppt Debounce + laufenden Worker und wartet dessen Ende ab.

        Fix 15.03 (Haenger bei TF-Wechsel): Der Worker wird gecancelt (Flag)
        und mit wait() abgewartet (Queries sind schnell, < 1 s). Ohne wait()
        wuerde der noch laufende QThread beim Zerstoeren des Fensters/
        ViewModel abgebrochen ('QThread: Destroyed while thread is still
        running') – die App haengt. self._worker wird vorher auf None gesetzt,
        damit verspaetete Signale des alten Workers vom Guard in
        _on_finished/_on_failed verworfen werden.
        """
        self._debounce.stop()
        self._pending_kinds.clear()
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.cancel()
            if worker.isRunning():
                worker.wait(5000)

    # ------------------------------------------------------------------
    # Datenfluss: UI-Pages fordern Abfragen an (MVVM)
    # ------------------------------------------------------------------
    def request_table(self) -> None:
        self._refresh((QUERY_TABLE,))

    def request_heatmap(self) -> None:
        self._refresh((QUERY_HEATMAP,))

    # 20.02 (additiv): Generische 2D-Heatmap (freie Dimensionen) + OHLCV-
    # Snapshot fuer das Candle-Overlay (E9) – werden on-demand von der
    # HeatmapPage im Generisch-Modus angefordert (kein refresh_all-Pflicht).
    def request_heatmap_generic(self) -> None:
        self._refresh((QUERY_HEATMAP_GENERIC,))

    def request_ohlcv_snapshot(self) -> None:
        self._refresh((QUERY_OHLCV,))

    # 20.02-Bugfix (09.08.2026, Punkt 1+2): Tages-Ohlc fuer das Candle-Overlay
    # im selben Canvas – SQL-seitig aggregiert (deckt den gesamten
    # Heatmap-Zeitraum ab; das HeatmapWidget nutzt diesen Query statt
    # QUERY_OHLCV).
    def request_daily_ohlc(self) -> None:
        self._refresh((QUERY_DAILY_OHLC,))

    def request_scatter(self) -> None:
        self._refresh((QUERY_SCATTER,))

    def request_distribution(self) -> None:
        self._refresh((QUERY_DISTRIBUTION,))

    def request_features(self) -> None:
        self._refresh((QUERY_FEATURES,))

    def refresh_all(self) -> None:
        """Stoesst alle Abfragen neu an (Seiten-/Profilwechsel)."""
        self._refresh((QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                       QUERY_SCATTER, QUERY_DISTRIBUTION, QUERY_FEATURES))

    # ------------------------------------------------------------------
    # Parameter setzen (UI-Pages) – markieren Dirty + feuern betroffen ab
    # ------------------------------------------------------------------
    def set_symbol(self, symbol: str) -> None:
        self._set_param("symbol", str(symbol or ""),
                        (QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                         QUERY_OHLCV, QUERY_SCATTER, QUERY_DISTRIBUTION,
                         QUERY_FEATURES))

    def set_timeframe(self, timeframe: str) -> None:
        self._set_param("timeframe", str(timeframe or "M1"),
                        (QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                         QUERY_OHLCV, QUERY_SCATTER, QUERY_DISTRIBUTION,
                         QUERY_FEATURES))

    # ------------------------------------------------------------------
    # 21.03.12 (MTF-FC auf Analytics): Filterleisten-Parameter
    # ------------------------------------------------------------------
    def set_data_tf(self, data_tf: str) -> None:
        """Setzt die Analysequelle des MtfFilterBarWidget ('multi' | TF).

        'multi'  -> alle Timeframes in EINER Query (`all_timeframes=True`,
                    der `timeframe`-Filter entfaellt im Reader).
        'M15' o.ae. -> Fixiert auf diesen TF: `all_timeframes=False` und der
                    `timeframe`-Filter uebernimmt den fixierten TF (die UI
                    synchronisiert combo_tf daraus).
        """
        data_tf = str(data_tf or "").strip() or "multi"
        if data_tf == "multi":
            if (self._params.get("data_tf") == "multi"
                    and not self._params.get("all_timeframes")):
                self._params["all_timeframes"] = True
                self._mark_dirty()
                self._refresh(_ALL_QUERIES)
            elif self._params.get("data_tf") != "multi":
                self._params["data_tf"] = "multi"
                self._params["all_timeframes"] = True
                self._mark_dirty()
                self._refresh(_ALL_QUERIES)
            return
        # Fixiert auf einen konkreten TF.
        tf = data_tf.upper()
        changed = (self._params.get("data_tf") != tf
                   or self._params.get("timeframe") != tf
                   or self._params.get("all_timeframes"))
        if not changed:
            return
        self._params["data_tf"] = tf
        self._params["all_timeframes"] = False
        self._params["timeframe"] = tf
        self._mark_dirty()
        self._refresh(_ALL_QUERIES)

    def set_agg_tf(self, agg_tf: str) -> None:
        """Setzt den Aggregations-TF (Entscheidung 6a: 'auto' | TF).

        'auto' -> Granularitaet wird dynamisch aus dem Zeitraum abgeleitet
                  (kein Zeit-Bucketing; Verhalten wie bisher).
        'H1' o.ae. -> Die generische Heatmap fasst die date-Achse starr auf
                  diesem TF-Raster zusammen (bucket_tf im Reader).
        """
        agg_tf = str(agg_tf or "").strip().lower() or "auto"
        self._set_param("agg_tf", agg_tf, (QUERY_HEATMAP_GENERIC,))

    def set_sort_mode(self, mode: str) -> None:
        """21.03.14 (Wunsch 2): Speichert die Tabellen-Sortierung.

        `sort_mode` ist 'date' | 'signal' | 'tf' und wird fuer die
        Profil-Persistenz gemerkt (Sektion sources). Reiner UI-Zustand
        (die TablePage wendet die Sortierung ueber den EventBus an) -
        KEIN Query-Refresh, nur Dirty-Markierung (Option B - Explicit
        Save). Idempotent ohne Aenderung.
        """
        mode = str(mode or "").strip().lower()
        if mode not in ("date", "signal", "tf"):
            mode = "date"
        if mode == self._params.get("sort_mode"):
            return
        self._params["sort_mode"] = mode
        self._mark_dirty()

    def set_service_mode(self, mode: str) -> None:
        """21.03.20: Setzt den Modus-Filter (z. B. 'MA_Peak_Hysteresis').

        `"all"` (Default) = kein Filter (alle Modi). Wirkt GLOBAL auf
        alle Analytics-Datenquellen (Entscheidung 1): Tabelle, beide
        Heatmaps, Scatter, Verteilung. `QUERY_FEATURES` wird mitrefreshed,
        damit die dynamische Modus-Liste / das Deaktivierungs-Flag
        (`has_source_mode_services`) synchron zur Auswahl bleibt. Idempotent
        ohne Aenderung (kein Refresh/Dirty).
        """
        mode = str(mode or "all").strip()
        if mode == self._params.get("service_mode"):
            return
        self._params["service_mode"] = mode
        self._mark_dirty()
        self._refresh((QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP,
                       QUERY_HEATMAP_GENERIC, QUERY_SCATTER,
                       QUERY_DISTRIBUTION))

    def set_range(self, from_ts, to_ts, preset: Optional[str] = None) -> None:
        """Setzt den Zeitraum-Filter (optional, bar_time BETWEEN).

        `from_ts`/`to_ts` sind Wanduhr-Epochs (int) oder None (kein Filter).
        `preset` ist der Range-Preset-Name des MtfFilterBarWidget (z. B.
        '7d'/'90d'/'Year', 21.03.15) und wird fuer die Profil-Persistenz
        gemerkt. Alt-Werte 'YTD' (bis 21.03.15) bzw. 'Benutzerdefiniert'
        (entfallenes Custom-Panel) werden auf den neuen Preset-Satz
        abgebildet. Wird vom Range-Picker des MtfFilterBarWidget gesetzt
        (Basis = letzter Datenpunkt statt time.time()).
        """
        f = int(from_ts) if from_ts is not None else None
        t = int(to_ts) if to_ts is not None else None
        preset = str(preset or "").strip() or None
        # 21.03.15 (Bug 3): Alt-Profile mit 'YTD'/'Benutzerdefiniert' auf den
        # neuen Preset-Satz (24h/7d/30d/90d/Year) abbilden.
        if preset == "YTD":
            preset = "Year"
        elif preset == "Benutzerdefiniert":
            preset = "7d"
        if (f == self._params.get("range_from")
                and t == self._params.get("range_to")
                and preset == self._params.get("range_preset")):
            return
        self._params["range_from"] = f
        self._params["range_to"] = t
        self._params["range_preset"] = preset
        self._mark_dirty()
        self._refresh((QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                       QUERY_SCATTER, QUERY_DISTRIBUTION))

    def clear_range(self) -> None:
        """Entfernt den Zeitraum-Filter (kein Zeitfilter mehr)."""
        self.set_range(None, None)

    def latest_data_epoch(self) -> Optional[int]:
        """Neuester Wanduhr-Epoch der Feature-Daten (Range-Referenzpunkt).

        Delegiert lesend an das Repository (`fetch_latest_bar_time` fuer das
        aktuelle Symbol/Timeframe) – der `now_provider` des MtfFilterBarWidget
        rechnet die Presets relativ zum letzten Datenpunkt statt zu
        time.time(). Defensiv: ohne Symbol/Timeframe oder bei Fehler -> None
        (das Widget faellt dann auf time.time() zurueck).
        """
        symbol = str(self._params.get("symbol") or "")
        timeframe = str(self._params.get("timeframe") or "")
        if not symbol or not timeframe:
            return None
        try:
            return self._repo.get_latest_bar_time(symbol, timeframe)
        except Exception:
            return None

    def set_feature_id(self, feature_id: Optional[str]) -> None:
        """Kompatibilitaets-Alias (Legacy): Einzel-ID -> Multi-Liste."""
        self.set_feature_ids([feature_id] if feature_id else [])

    def set_feature_ids(self, feature_ids, instance_hashes=None) -> None:
        """Setzt die Multi-Auswahl der Datenquellen (15.03-E).

        `feature_ids` sind die plugin_ids des Feature-Store (z. B.
        ["srv_grid_lines", "srv_proximity"]); leer = kein Filter (alle Features).
        Typen-/Duplikat-normalisiert; ohne Aenderung wird kein Refresh
        ausgeloest (idempotent, wie set_symbol/set_timeframe).

        Runde 10 (Bug 1): `instance_hashes` schraenkt die gewaehlten
        plugin_ids auf bestimmte Varianten (Clones) ein - None/leer =
        KEINE Varianten-Einschraenkung (alle Varianten der plugin_ids).
        None bedeutet ausserdem: bestehende Hash-Einschraenkung bleibt
        erhalten (z. B. bei reinen feature_ids-Aenderungen durch das
        Feld-Dropdown). Die Hashes fliessen als zusaetzliche
        WHERE-Bedingung in die Reader-Queries
        (`(instance_hash IS NULL OR instance_hash IN (...))`).
        """
        ids = self._normalize_feature_ids(feature_ids)
        hashes_changed = instance_hashes is not None
        if hashes_changed:
            hashes = self._normalize_instance_hashes(instance_hashes)
        else:
            # None = bestehende Einschraenkung beibehalten (kein
            # versehentliches Leeren durch Alt-Aufrufer).
            hashes = self._params.get("instance_hashes") or []
        if (ids == self._params.get("feature_ids")
                and (not hashes_changed
                     or hashes == self._params.get("instance_hashes"))):
            return
        ids_changed = ids != self._params.get("feature_ids")
        self._params["feature_ids"] = ids
        if hashes_changed:
            self._params["instance_hashes"] = hashes
        self._mark_dirty()
        if ids_changed:
            # Runde 8 (Bugfix 4): Die UI leitet ihr 'Feld'-Dropdown
            # SYNCHRON neu ab (kein Query-Round-Trip) - das
            # HeatmapWidget verbindet feature_ids_changed und baut
            # Items/Haken/Current sofort neu. (Nur bei feature_ids-
            # Aenderung; reine Hash-Aenderung laesst das Feld-Dropdown
            # unveraendert.)
            self.feature_ids_changed.emit()
        # Runde 15b (Bugfix Dropdown, User-Meldung 10.08.2026): QUERY_FEATURES
        # gehoert in den Refresh - der leichte Metadaten-Pfad liefert die
        # field_sources/no_data_variants fuer die AKTUELLEN feature_ids +
        # instance_hashes (Feld-Dropdown + NoData-Hinweise). Ohne den
        # Refresh bliebe das Dropdown auf dem Cache-Stand des letzten
        # Payloads (z. B. ein zuvor gefilterter Satz ohne die neu gecheckten
        # Services) - Check/Uncheck waere erst nach einem Seitenwechsel
        # sichtbar. Die Queue-Reihenfolge (QUERY_FEATURES zuerst) spiegelt
        # die Runde-15-Prioritaet: leichtes Dropdown-Update VOR der Grafik.
        self._refresh((QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP,
                       QUERY_HEATMAP_GENERIC, QUERY_SCATTER,
                       QUERY_DISTRIBUTION))

    def set_field_selection(self, field_pairs, update_ids: bool = True) -> None:
        """Setzt die (Service|Parameter)-Auswahl des 'Feld'-Dropdowns.

        12.08.2026 (Option A, Bug 1/2): Die Feld-Auswahl ist eine explizite
        Liste von '{service_id}|{key}'-Paaren (effective pairs) - der
        Reader filtert damit auf PARAMETER-Ebene (field_pairs-WHERE:
        `feature_data->>key IS NOT NULL` je Service). Leere Liste = kein
        Paar-Filter (reines feature_ids-Verhalten wie bisher).

        `update_ids=True` (USER-Interaktion, ServicePicker-Sync): Die
        Services werden aus den Paaren abgeleitet und in `feature_ids`
        uebernommen (Dropdown und Picker bleiben konsistent; Abwaehlen des
        letzten Parameters eines Services entfernt ihn aus dem Picker).

        `update_ids=False` (PROGRAMMATISCHER Sync am Ende des
        Dropdown-Rebuilds): `feature_ids` bleibt UNANGETASTET - der
        ServicePicker ist die Service-Quelle; Services OHNE numerische
        Feld-Keys duerfen dadurch nicht stillschweigend aus der Auswahl
        fallen (nur ihre Paare koennen fehlen).

        Im Gegensatz zu set_feature_ids() wird der Refresh auch bei
        UNVERAENDERTER Service-Menge ausgeloest, wenn sich die Parameter-
        Auswahl geaendert hat. Idempotent ohne Aenderung (kein
        Refresh/Dirty).
        """
        pairs = self._normalize_field_pairs(field_pairs)
        ids = self._pairs_to_feature_ids(pairs)
        current_pairs = self._params.get("field_selection") or []
        current_ids = self._params.get("feature_ids") or []
        pairs_changed = pairs != current_pairs
        ids_changed = update_ids and ids != current_ids
        if not pairs_changed and not ids_changed:
            return
        self._params["field_selection"] = pairs
        if ids_changed:
            self._params["feature_ids"] = ids
        self._mark_dirty()
        if ids_changed:
            # Service-Satz geaendert -> ServicePicker + Feld-Metadaten
            # (QUERY_FEATURES) synchron nachziehen (identisch zu
            # set_feature_ids).
            self.feature_ids_changed.emit()
            self._refresh((QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP,
                       QUERY_HEATMAP_GENERIC, QUERY_SCATTER,
                       QUERY_DISTRIBUTION))
        else:
            # NUR die Parameter-Auswahl hat sich geaendert -> nur die
            # generische Heatmap neu aggregieren (Bug 1: An/Abwaehlen
            # eines Parameters muss die Grafik aendern).
            self._refresh((QUERY_HEATMAP_GENERIC,))

    @staticmethod
    def _normalize_field_pairs(value) -> List[str]:
        """Normalisiert '{service_id}|{key}'-Paare (dedupliziert, getrimmt).

        12.08.2026 (Option A): Eintraege ohne `|` oder mit leerer Service-/
        Key-Seite werden verworfen. Die Keys bleiben case-sensitiv (JSON-
        Keys aus den Service-Payloads), die Service-ID wird getrimmt.
        """
        if not value:
            return []
        out: List[str] = []
        for v in value:
            s = str(v).strip()
            if not s or "|" not in s:
                continue
            sid, key = s.split("|", 1)
            sid = sid.strip()
            key = key.strip()
            if sid and key and f"{sid}|{key}" not in out:
                out.append(f"{sid}|{key}")
        return out

    @staticmethod
    def _pairs_to_feature_ids(pairs) -> List[str]:
        """Leitet die aktiven Service-IDs aus '{service_id}|{key}'-Paaren ab.

        12.08.2026 (Option A): Dedupliziert in Paar-Reihenfolge (die
        Feld-Dropdown-Item-Reihenfolge bestimmt die ServicePicker-Reihenfolge
        - konsistent zu _checked_field_service_ids()).
        """
        out: List[str] = []
        for p in pairs or []:
            s = str(p or "")
            if "|" not in s:
                continue
            sid = s.split("|", 1)[0].strip()
            if sid and sid not in out:
                out.append(sid)
        return out

    @staticmethod
    def _normalize_feature_ids(value) -> List[str]:
        """Normalisiert feature_ids (Liste[str], dedupliziert, getrimmt)."""
        if not value:
            return []
        out: List[str] = []
        for v in value:
            s = str(v).strip()
            if s and s not in out:
                out.append(s)
        return out

    @staticmethod
    def _normalize_instance_hashes(value) -> List[str]:
        """Normalisiert instance_hashes (Liste[str], dedupliziert,
        getrimmt) - Runde 10 (Bug 1, Varianten-Einschraenkung)."""
        if not value:
            return []
        out: List[str] = []
        for v in value:
            s = str(v).strip()
            if s and s not in out:
                out.append(s)
        return out

    def _resolve_feature_ids(
        self, feature_ids: List[str]
    ) -> Tuple[List[str], List[str]]:
        """Isoliert fehlende Services ueber den Resolver (20.01, E5).

        Ohne ein injiziertes Modell (Tests/Alt-Aufrufer) wird ein lazies
        Default-Modell erzeugt (nur wenn ueberhaupt IDs zu pruefen sind).
        Fehler -> (normalisierte ids, []) defensiv (kein Absturz).
        """
        ids = self._normalize_feature_ids(feature_ids)
        if not ids:
            return [], []
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            return model.resolve_valid_feature_ids(ids)
        except Exception:
            return ids, []

    @staticmethod
    def _flatten_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Flacht v2-Sections (sources/charts/table/styling) auf Top-Level ab.

        20.01 (E2/E3): Der ViewModel arbeitet weiterhin mit flachen `_params` –
        die v2-Sektions-Keys haben Vorrang vor gleichnamigen Top-Level-Resten
        (die bei der v1→v2-Migration verlustfrei erhalten bleiben).
        """
        flat: Dict[str, Any] = {}
        for section in ("sources", "charts", "table", "styling"):
            values = payload.get(section)
            if isinstance(values, dict):
                flat.update(values)
        for key, value in payload.items():
            if key in ("schema_version", "sources", "charts", "table",
                       "styling"):
                continue
            if key not in flat:
                flat[key] = value
        return flat

    def set_heatmap_metric(self, metric: str) -> None:
        self._set_param("heatmap_metric", str(metric or "count"),
                        (QUERY_HEATMAP,))

    # ------------------------------------------------------------------
    # 20.02: Generische 2D-Heatmap – Konfiguration/Zoom/Overlay (additiv)
    # ------------------------------------------------------------------
    def set_heatmap_config(
        self, x_dim: str, y_dim: str, field: str, agg: str
    ) -> None:
        """Setzt die Konfiguration der generischen Heatmap (20.02, E1).

        x_dim/y_dim aus DIM_MAPPINGS (case-insensitiv), `agg` eine der
        HEATMAP_AGGREGATIONS, `field` der numerische feature_data-JSON-Key
        (E6: nur bei AVG/SUM/MIN/MAX relevant; COUNT/CONFLUENCE_COUNT
        ignorieren ihn). 20.02.01 (E6): `dow_hour` wird per Sanitizer auf
        "hour" abgebildet. Ohne Aenderung idempotent (kein Refresh).
        """
        x_dim = self._sanitize_dim(x_dim or "date")
        y_dim = self._sanitize_dim(y_dim or "hour")
        agg = str(agg or "confluence_count").lower()
        field = str(field or "")
        changed = (x_dim != self._params.get("heatmap_x_dim")
                   or y_dim != self._params.get("heatmap_y_dim")
                   or agg != self._params.get("heatmap_agg")
                   or field != self._params.get("heatmap_field"))
        if not changed:
            return
        self._params["heatmap_x_dim"] = x_dim
        self._params["heatmap_y_dim"] = y_dim
        self._params["heatmap_agg"] = agg
        self._params["heatmap_field"] = field
        self._mark_dirty()
        self._refresh((QUERY_HEATMAP_GENERIC,))

    # ------------------------------------------------------------------
    # 21.01: Smart-Presets (E4, 11.08.2026)
    # ------------------------------------------------------------------
    def _set_heatmap_all_timeframes(self, enabled: bool) -> None:
        """Setzt die TF-Freigabe der generischen Heatmap (21.01, E1).

        Idempotent ohne Aenderung; Dirty-Flag + Refresh nur bei echtem
        Wechsel (Muster set_heatmap_config).
        """
        enabled = bool(enabled)
        if enabled == self._params.get("heatmap_all_timeframes"):
            return
        self._params["heatmap_all_timeframes"] = enabled
        self._mark_dirty()
        self._refresh((QUERY_HEATMAP_GENERIC,))

    def apply_smart_preset_confluence(self) -> None:
        """`[⚡ Signal-Confluence]`: X=date, Y=service_id, count(DISTINCT fid).

        Chronologische Lichtsaeulen zeitgleicher Signale (Hauptansicht).
        Konfiguration + Dirty-Flag (Option B), KEIN Auto-Save (E4).
        """
        self._set_heatmap_all_timeframes(False)
        self.set_heatmap_config("date", "service_id", "", "confluence_count")

    def apply_smart_preset_session(self) -> None:
        """`[🕒 Session-Hotspots]`: X=dow (Mo-Fr), Y=hour, count(DISTINCT fid).

        Tageszeit-/Wochentag-Muster im Handelsverlauf (Wanduhr, E5-Phase 20).
        Konfiguration + Dirty-Flag (Option B), KEIN Auto-Save (E4).
        """
        self._set_heatmap_all_timeframes(False)
        self.set_heatmap_config("dow", "hour", "", "confluence_count")

    def apply_smart_preset_intensity(self, x_dim: str = "date") -> None:
        """`[📏 Wert-Intensität]`: X=date (Standard) oder dow (E2), Y=hour.

        Auspraegung von Messwerten (z. B. distance_pip, atr) – AVG/Max ueber
        den ersten verfuegbaren numerischen feature_data-JSON-Key (Repo-
        Fallback, wenn keiner existiert). `x_dim` akzeptiert "date" (Default)
        oder "dow" (E2). Konfiguration + Dirty-Flag (Option B), KEIN
        Auto-Save (E4).
        """
        x_key = "dow" if str(x_dim or "").strip().lower() == "dow" else "date"
        # Erster verfuegbarer numerischer Key (Muster Repo-E6-Fallback) –
        # bei leeren Daten bleibt field="" (Repo faellt defensiv zurueck).
        try:
            avail = self._repo.available_feature_columns(
                str(self._params.get("symbol") or ""),
                str(self._params.get("timeframe") or "M1"))
            field = avail[0] if avail else ""
        except Exception:
            field = ""
        self._set_heatmap_all_timeframes(False)
        self.set_heatmap_config(x_key, "hour", field, "avg")

    def apply_smart_preset_timeframe(self) -> None:
        """`[📊 Service-Timeframe]`: X=timeframe (ALLE TFs), Y=service_id.

        Verteilung der Services ueber Zeitebenen (E1: `all_timeframes=True`
        entfaellt die TF-WHERE-Bedingung – alle M1..D1 in EINER Query).
        Konfiguration + Dirty-Flag (Option B), KEIN Auto-Save (E4).
        """
        self._set_heatmap_all_timeframes(True)
        self.set_heatmap_config("timeframe", "service_id", "", "count")

    # ------------------------------------------------------------------
    # 21.01 (E3): Auto-Namensgenerator fuer neue Profile (DEUTSCH)
    # ------------------------------------------------------------------
    def generate_profile_name_suggestion(self) -> str:
        """Sprechender Profilname – Formel `[Symbol] [TF] - [Modus] ([Kontext])`.

        E3 (11.08.2026): Sprache DEUTSCH, z. B.
        `SILVER M1 - Confluence Zeitachse (3 Services)`.
        * Kontext-Klammer = Anzahl der selektierten Services (feature_ids);
          bei 0 Auswahlen `(Alle Services)` statt `(0 Services)`.
        * Fehlendes Symbol/Timeframe -> Platzhalter `ALLE`
          (z. B. `ALLE M1 - Confluence Zeitachse (3 Services)`).
        * Modus-Ableitung aus der AKTUELLEN Heatmap-Konfiguration
          (Confluence/Session/Intensitaet/TF-Matrix) – der Vorschlag passt
          zum eingestellten Ansichts-Szenario.
        """
        symbol = str(self._params.get("symbol") or "").strip() or "ALLE"
        timeframe = str(self._params.get("timeframe") or "").strip() or "ALLE"
        x_dim = str(self._params.get("heatmap_x_dim") or "").lower()
        y_dim = str(self._params.get("heatmap_y_dim") or "").lower()
        agg = str(self._params.get("heatmap_agg") or "").lower()
        if x_dim == "timeframe":
            mode = "Service-Zeitebenen"
        elif x_dim == "dow" and y_dim == "hour":
            mode = "Session-Hotspots"
        elif agg in ("avg", "sum", "min", "max"):
            mode = "Wert-Intensität"
        else:
            mode = "Confluence Zeitachse"
        n = len(self._params.get("feature_ids") or [])
        context = f"{n} Services" if n > 0 else "Alle Services"
        return f"{symbol} {timeframe} - {mode} ({context})"

    def set_heatmap_zoom(self, x_range, y_range) -> None:
        """Setzt die normalisierten Viewport-Anteile [0,1] (20.02, E8).

        Rein client-seitig (die UI wendet die Bereiche direkt per
        setXRange/setYRange an) – KEIN DB-Requery. Die Werte werden geclampt
        (0 ≤ lo < hi ≤ 1) und fuer die Persistenz (Profil/Workspace)
        markiert (Option B – Explicit Save).
        """
        x_clamped = self._clamp_zoom(x_range)
        y_clamped = self._clamp_zoom(y_range)
        if (x_clamped == self._params.get("zoom_x_range")
                and y_clamped == self._params.get("zoom_y_range")):
            return
        self._params["zoom_x_range"] = x_clamped
        self._params["zoom_y_range"] = y_clamped
        self._mark_dirty()

    def set_candle_projection(self, enabled: bool) -> None:
        """Schaltet das Candle-Overlay (Preis-Strip) an/aus (20.02, E9).

        Reiner UI-Zustand ohne DB-Abfrage (der OHLCV-Snapshot wird von der
        HeatmapPage on-demand angefordert); nur Dirty-Markierung fuer die
        Profil-Persistenz.
        """
        enabled = bool(enabled)
        if enabled == self._params.get("candle_projection_enabled"):
            return
        self._params["candle_projection_enabled"] = enabled
        self._mark_dirty()

    @staticmethod
    def _clamp_zoom(value) -> List[float]:
        """Clampt einen Zoom-Bereich auf [0.0, 1.0] mit lo < hi (E8)."""
        try:
            lo, hi = float(value[0]), float(value[1])
        except (TypeError, ValueError, IndexError):
            return [0.0, 1.0]
        lo = max(0.0, min(1.0, lo))
        hi = max(0.0, min(1.0, hi))
        return [lo, hi] if hi > lo else [0.0, 1.0]

    @staticmethod
    def _sanitize_dim(value) -> str:
        """Bereinigt eine Heatmap-Dimension (20.02.01, E6).

        `dow_hour` ist ersatzlos aus DIM_MAPPINGS/HEATMAP_DIMENSIONS entfernt.
        Alt-Profil-/Workspace-/Config-Werte mit `dow_hour` werden auf die
        gueltige Dimension "hour" (Tageszeit) abgebildet – sonst wuerde
        `_set_combo_data` (additives Hinzufuegen unbekannter Werte) die
        entfernte Dimension wieder in die UI-Combos aufnehmen.
        """
        dim = str(value or "").lower()
        return "hour" if dim == "dow_hour" else dim

    def set_scatter_columns(self, x_column: str, y_column: str) -> None:
        # 19.02 (Cleanup): Leere Werte = Repo-Default (erste numerische
        # feature_data-JSON-Keys). Keine Legacy-Spalten-Fallbacks mehr.
        self._set_param("scatter_x", str(x_column or ""),
                        (QUERY_SCATTER,))
        self._set_param("scatter_y", str(y_column or ""),
                        (QUERY_SCATTER,))

    def set_distribution_column(self, column: str) -> None:
        self._set_param("distribution_column",
                        str(column or ""),
                        (QUERY_DISTRIBUTION,))

    def set_bins(self, bins: int) -> None:
        new_bins = self._clamp_bins(bins)
        if new_bins != self._params["bins"]:
            self._params["bins"] = new_bins
            self._mark_dirty()
            self._refresh((QUERY_DISTRIBUTION,))

    def set_limit(self, limit: int) -> None:
        new_limit = self._clamp_limit(limit)
        if new_limit != self._params["limit"]:
            self._params["limit"] = new_limit
            self._mark_dirty()
            self._refresh((QUERY_TABLE, QUERY_SCATTER, QUERY_DISTRIBUTION))

    def set_table_settings(
        self,
        widths: Optional[Dict[str, Any]] = None,
        row_height: int = 0,
        sort_column: int = 0,
        sort_order: int = 1,
    ) -> None:
        """Uebernimmt TablePage-Settings (19.03 E6, ohne Query-Refresh).

        Spaltenbreiten {Spaltenname: Breite} (E5), **globale Zeilenhoehe**
        (E9/19.06: ein Wert fuer die GESAMTE Tabelle – das Ziehen einer
        Zeile setzt alle Zeilen live auf diese Hoehe), Sortier-Spalte und
        -Richtung (E8). Reine UI-Zustaende der TablePage: KEIN `_refresh`/
        Debounce/Worker und keine DB-Abfrage – nur die Dirty-Markierung fuer
        die Profil-Persistenz (Option B – Explicit Save). Typ-/Werte-
        normalisiert; ohne tatsaechliche Aenderung idempotent (kein
        unnötiges Dirty-Flag bei Drag-Ereignissen).
        """
        norm_widths: Dict[str, int] = {}
        for k, v in (widths or {}).items():
            try:
                w = int(v)
            except (TypeError, ValueError):
                continue
            if w > 0:
                norm_widths[str(k)] = w
        try:
            rh = max(0, int(row_height))
        except (TypeError, ValueError):
            rh = 0
        try:
            sc = max(0, int(sort_column))
        except (TypeError, ValueError):
            sc = 0
        try:
            so_raw = int(sort_order)
        except (TypeError, ValueError):
            so_raw = 1
        so = so_raw if so_raw in (0, 1) else 1

        if (norm_widths == self._params.get("table_column_widths")
                and rh == self._params.get("table_row_height")
                and sc == self._params.get("table_sort_column")
                and so == self._params.get("table_sort_order")):
            return
        self._params["table_column_widths"] = norm_widths
        self._params["table_row_height"] = rh
        self._params["table_sort_column"] = sc
        self._params["table_sort_order"] = so
        self._mark_dirty()

    def _set_param(self, key: str, value: Any, kinds: Iterable[str]) -> None:
        if self._params.get(key) == value:
            return
        self._params[key] = value
        self._mark_dirty()
        self._refresh(kinds)

    # ------------------------------------------------------------------
    # Interna: Debounce + Worker-Verwaltung
    # ------------------------------------------------------------------
    def _refresh(self, kinds: Iterable[str]) -> None:
        for kind in kinds:
            if kind not in self._pending_kinds:
                self._pending_kinds.append(kind)
        self._debounce.start()

    def _start_next_query(self) -> None:
        """Startet die naechste gepufferte Abfrage (Debounce-Timeout)."""
        if self._worker is not None and self._worker.isRunning():
            return  # laufender Worker uebernimmt; Puffer bleibt gefuellt
        while self._pending_kinds:
            kind = self._pending_kinds.pop(0)
            params = self._current_params(kind)
            if params is None:
                continue  # kein Symbol/Timeframe -> Abfrage ueberspringen
            self._launch(kind, params)
            return
        self.busy_changed.emit(False)

    def _launch(self, kind: str, params: Dict[str, Any]) -> None:
        worker = AnalyticsAsyncWorker(self._repo, kind, params, parent=self)
        self._worker = worker
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(worker.deleteLater)
        self.busy_changed.emit(True)
        worker.start()

    def _on_finished(self, worker, kind: str, result: Dict[str, Any]) -> None:
        """Verarbeitet das Ergebnis eines Workers – NUR des aktuellen.

        Fix 15.03 (Haenger bei TF-Wechsel): Race-Condition, bei der ein
        veralteter Worker (Thread bereits beendet, finished_ok noch nicht
        zugestellt, waehrend der Debounce bereits einen neuen Worker startet)
        den self._worker-Verweis ueberschrieb und mehrere Worker parallel
        liefen. Der Guard `self._worker is worker` verwirft verspaetete
        Ergebnisse veralteter Worker; nur der zuletzt gestartete Worker darf
        weiterverarbeiten.
        """
        if self._worker is not worker:
            return
        self._worker = None
        self.data_ready.emit(kind, result)
        self._start_next_query()

    def _on_failed(self, worker, kind: str, error: str) -> None:
        """Verarbeitet einen Worker-Fehler – NUR des aktuellen (Race-Guard).

        Siehe _on_finished: Verspaetete Fehler veralteter Worker werden
        verworfen, damit der laufende/naechste Worker nicht gestoert wird.
        """
        if self._worker is not worker:
            return
        self._worker = None
        self.query_failed.emit(kind, error)
        self._start_next_query()

    def _current_params(self, kind: str) -> Optional[Dict[str, Any]]:
        """Baut die Abfrageparameter fuer einen query_kind (oder None)."""
        p = self._params
        if not p.get("symbol") or not p.get("timeframe"):
            return None
        base: Dict[str, Any] = {
            "symbol": p["symbol"],
            "timeframe": p["timeframe"],
            "feature_ids": p["feature_ids"],
            # Runde 10 (Bug 1): Varianten-Einschraenkung in die
            # Query-Params (leer = alle Varianten der feature_ids).
            "instance_hashes": p.get("instance_hashes") or [],
            # Runde 8 (Bugfix 3): Generation in die Worker-Params - der
            # Worker spiegelt sie ins Ergebnis-Dict, die UI erkennt damit
            # Stale-Payloads (Queries vor dem letzten Restore).
            "restore_generation": self._restore_generation,
            # 21.03.12 (MTF-FC auf Analytics): Optionaler Zeitfilter
            # (Wanduhr-Epochs relativ zum letzten Datenpunkt; None = alle).
            "from_ts": p.get("range_from"),
            "to_ts": p.get("range_to"),
            # 21.03.20 (Analytics Modus-Filter): source_mode-Filter
            # (GLOBAL - alle Query-Kinds, Entscheidung 1).
            "service_mode": p.get("service_mode", "all"),
        }
        if kind == QUERY_TABLE:
            base["limit"] = p["limit"]
        elif kind == QUERY_HEATMAP:
            base["metric"] = p["heatmap_metric"]
        elif kind == QUERY_HEATMAP_GENERIC:
            # 20.02: Generische 2D-Heatmap – Konfiguration aus den heatmap_*-
            # _params. 20.02-Bugfix (09.08.2026, Punkt 2): KEIN limit-Lookback
            # mehr (limit=None => ALLE verfuegbaren Daten; der Pivot-Deckel
            # MAX_HEATMAP_CELLS im Reader begrenzt die Matrix). Vorher schnitt
            # der 5000er-Lookback die Heatmap auf die letzten ~4 Tage (M1) ab.
            base["x_dim"] = p["heatmap_x_dim"]
            base["y_dim"] = p["heatmap_y_dim"]
            base["field"] = p.get("heatmap_field") or None
            base["agg"] = p["heatmap_agg"]
            # 12.08.2026 (Option A, Bug 1/2): Explizite (Service|Parameter)-
            # Auswahl des 'Feld'-Dropdowns -> der Reader filtert auf
            # PARAMETER-Ebene (feature_data-JSON-Keys je Service). Leer =
            # kein Paar-Filter (verhalten wie bisher, reiner feature_ids-
            # Filter). Wird in set_field_selection() gepflegt.
            base["field_selection"] = p.get("field_selection") or []
            # 21.01 (E1): TF-Freigabe in die Worker-Params – True entfaellt
            # im Reader die TF-WHERE-Bedingung (Preset `[📊 Service-Timeframe]`).
            # 21.03.12: OR-verknuepft mit `all_timeframes` (data_tf='multi' -
            # Analysequelle des MtfFilterBarWidget uebernimmt die Freigabe).
            base["all_timeframes"] = bool(
                p.get("heatmap_all_timeframes", False)
                or p.get("all_timeframes", False))
            # 21.03.12 (Entscheidung 6a): agg_tf -> bucket_tf fuer das
            # date-Raster der generischen Heatmap ('auto'/leer = kein
            # Bucketing, dynamische Granularitaet wie bisher).
            _agg_tf = str(p.get("agg_tf") or "auto").strip().lower()
            base["bucket_tf"] = None if _agg_tf in ("", "auto") else _agg_tf
            # Runde 12 (Option A): Preset-Modell-Snapshot fuer die
            # No-Data-Auswertung IM SELBEN Datenfluss wie die Grafik
            # (kein zweiter serieller QUERY_FEATURES-Worker-Roundtrip -
            # das Dropdown aktualisiert sich mit/knapp nach der Grafik
            # statt erst danach). Der Snapshot ist in-memory (kein DB).
            base["presets_data"] = self._no_data_presets_snapshot()
        elif kind == QUERY_OHLCV:
            # 20.02 (E9): OHLCV-Snapshot – limit=None => Reader-Default
            # (OHLCV_SNAPSHOT_LIMIT); kein feature_ids-Filter noetig.
            pass
        elif kind == QUERY_DAILY_OHLC:
            # 20.02-Bugfix (09.08.2026): Tages-Ohlc fuer das Candle-Overlay –
            # max_days=None => Reader-Default DAILY_OHLC_MAX_DAYS (4000 Tage,
            # deckt den gesamten Heatmap-Zeitraum).
            pass
        elif kind == QUERY_SCATTER:
            base["x_column"] = p["scatter_x"]
            base["y_column"] = p["scatter_y"]
            base["limit"] = p["limit"]
        elif kind == QUERY_DISTRIBUTION:
            base["column"] = p["distribution_column"]
            base["bins"] = p["bins"]
            base["limit"] = p["limit"]
        elif kind == QUERY_FEATURES:
            # Runde 11 (Bug 4, B4-1): Preset-Modell-Snapshot fuer die
            # No-Data-Auswertung im QUERY_FEATURES-Worker (kein synchroner
            # DB-Zugriff im UI-Hauptthread). Der Worker/Repo berechnet
            # `no_data_variants` als Payload-Attribut (B4-2).
            base["presets_data"] = self._no_data_presets_snapshot()
        return base

    # ------------------------------------------------------------------
    # Dirty-Flag (Option B – Explicit Save)
    # ------------------------------------------------------------------
    def _mark_dirty(self) -> None:
        """Nur bei vorhandenem aktivem Profil (sonst nichts zu speichern)."""
        if not self._dirty and self._active_profile is not None:
            self._dirty = True
            self.dirty_changed.emit(True)

    # ------------------------------------------------------------------
    # Profil-Verwaltung (CRUD + aktives Profil)
    # ------------------------------------------------------------------
    def load_profiles(self) -> None:
        """Laedt die Profil-Liste und wendet das aktive Profil an."""
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        active = self._profile_repo.get_active_profile()
        if active is not None:
            self._apply_profile(active, mark_dirty=False)
        elif self._active_profile is not None:
            self._active_profile = None
            self._dirty = False
            self.dirty_changed.emit(False)
            self.active_profile_changed.emit(None)

    def create_profile(
        self, name: str, description: str = ""
    ) -> Optional[str]:
        """Legt ein neues Profil mit den aktuellen Parametern an.

        Das neue Profil wird sofort aktiv (genau EIN aktives Profil).
        Raises ValueError bei doppeltem Namen.
        """
        name = (name or "").strip()
        if not name:
            return None
        if self._profile_repo.get_profile_by_name(name) is not None:
            raise ValueError(f"Profil '{name}' existiert bereits.")
        profile_id = self._profile_repo.create_profile(
            name, self._current_payload(), description
        )
        self._profile_repo.set_active(profile_id)
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        self._active_profile = self._profile_repo.get_profile(profile_id)
        self._dirty = False
        self.dirty_changed.emit(False)
        self.active_profile_changed.emit(dict(self._active_profile))
        self._emit_profile_changed(self._active_profile["name"])
        return profile_id

    def save_profile(self) -> bool:
        """Persistiert die aktuellen Parameter im aktiven Profil (Save).

        Returns:
            True, wenn ein aktives Profil existierte und gespeichert wurde.
        """
        if self._active_profile is None:
            return False
        profile_id = self._active_profile["profile_id"]
        ok = self._profile_repo.update_profile(
            profile_id, payload=self._current_payload()
        )
        if ok:
            self._active_profile = self._profile_repo.get_profile(profile_id)
            self._dirty = False
            self.dirty_changed.emit(False)
            self.profile_saved.emit(profile_id)
            self._emit_profile_changed(self._active_profile["name"])
        return ok

    def update_profile(
        self,
        profile_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Aktualisiert Name/Beschreibung eines Profils (additiv)."""
        ok = self._profile_repo.update_profile(
            profile_id, name=name, description=description
        )
        if ok:
            self._profiles = self._profile_repo.list_profiles()
            self.profiles_available.emit([dict(p) for p in self._profiles])
            if (self._active_profile is not None
                    and self._active_profile["profile_id"] == profile_id):
                self._active_profile = self._profile_repo.get_profile(profile_id)
                self.active_profile_changed.emit(dict(self._active_profile))
                self._emit_profile_changed(self._active_profile["name"])
        return ok

    def delete_profile(self, profile_id: str) -> bool:
        """Loescht ein Profil (hart). Aktives Profil wird zurueckgesetzt."""
        ok = self._profile_repo.delete_profile(profile_id)
        if not ok:
            return False
        was_active = (self._active_profile is not None
                      and self._active_profile["profile_id"] == profile_id)
        if was_active:
            self._active_profile = None
            self._dirty = False
            self.dirty_changed.emit(False)
            self.active_profile_changed.emit(None)
        self._profiles = self._profile_repo.list_profiles()
        self.profiles_available.emit([dict(p) for p in self._profiles])
        self.profile_deleted.emit(profile_id)
        return True

    def set_active_profile(self, profile_id: str) -> bool:
        """Setzt ein Profil als aktiv und wendet dessen Parameter an."""
        profile = self._profile_repo.get_profile(profile_id)
        if profile is None:
            return False
        self._profile_repo.set_active(profile_id)
        self._apply_profile(profile, mark_dirty=False)
        self.active_profile_changed.emit(dict(profile))
        self._emit_profile_changed(profile["name"])
        return True

    def _apply_profile(
        self, profile: Dict[str, Any], mark_dirty: bool = True
    ) -> None:
        """Uebernimmt die Profil-Parameter in die Ansicht (Explicit Save).

        20.01 (E2/E3/E5): Das Repository liefert beim Lesen bereits migrierte
        v2-Sectioned-Payloads – die flachen Sektionen werden hier auf die
        flachen `_params` abgebildet (keine VM-eigene Migration, Single
        Source of Truth im Repository). Fehlende Services (entfernte/
        umbenannte Plugins) werden per ServiceSelectorModel isoliert und via
        `missing_services_detected` gemeldet; die validen IDs werden DIREKT
        in `_params` geschrieben (kein `set_feature_ids`: kein Dirty-Flag,
        kein Doppel-Refresh, B4).
        """
        self._active_profile = dict(profile)
        payload = profile.get("payload") or {}
        flat = self._flatten_payload(payload)
        # 10.08.2026 (Punkte 3/4): UI-Layout (page_index/heatmap_mode) aus
        # dem Profil-Payload uebernehmen - die UI liest es ueber
        # workspace_layout (identischer Pfad wie restore_workspace).
        layout = payload.get("layout")
        if isinstance(layout, dict):
            self._workspace_layout.update(dict(layout))
        # Runde 11 (Bug 3, B3-2): Gemeinsamer Restore-Helper (Replace-
        # Semantik inkl. instance_hashes -> garantiert leer bei fehlendem
        # Payload-Key statt des alten Werts).
        self._restore_params_from_payload(flat)
        # 15.03-E (Profil-Migration): Alt-Payloads speicherten den Filter als
        # Einzelwert `feature_id` (String) – in `feature_ids` (Liste) wandeln.
        if "feature_ids" not in flat and flat.get("feature_id"):
            self._params["feature_ids"] = self._normalize_feature_ids(
                [flat["feature_id"]])
        # 20.02 (Luecke 5.3-6): `charts.heatmap` ist ein VERSCHACHTELTES Dict –
        # _flatten_payload() bildet es NICHT auf flache _params ab. Explizit
        # aufloesen (E3: additiv, kein Schema-Bump auf v2.1).
        self._apply_heatmap_section(flat.get("heatmap"))
        # 20.02.01 (E6): Alt-Payloads mit `dow_hour` (flach ODER via
        # charts.heatmap) auf die gueltige Dimension "hour" abbilden.
        for _hk in ("heatmap_x_dim", "heatmap_y_dim"):
            if self._params.get(_hk) == "dow_hour":
                self._params[_hk] = "hour"
        self._params["feature_ids"] = self._normalize_feature_ids(
            self._params.get("feature_ids"))
        # Runde 10 (Bug 1): instance_hashes genauso normalisieren.
        self._params["instance_hashes"] = self._normalize_instance_hashes(
            self._params.get("instance_hashes"))
        # 12.08.2026 (Option A): (Service|Parameter)-Auswahl des
        # 'Feld'-Dropdowns genauso normalisieren (Alt-Payloads ohne den
        # Key -> leer = kein Paar-Filter, Verhalten wie bisher).
        self._params["field_selection"] = self._normalize_field_pairs(
            self._params.get("field_selection"))
        # 20.01 (E5) + Runde 9 (Bug 1): Fehlende Services NUR melden -
        # die IDs bleiben im Filter (kein stilles Kuerzen des restaurierten
        # Filters; die DB liefert fuer unbekannte IDs keine Zeilen).
        if self._params["feature_ids"]:
            _, missing = self._resolve_feature_ids(self._params["feature_ids"])
            if missing:
                self.missing_services_detected.emit(list(missing))
        self._params["bins"] = self._clamp_bins(self._params.get("bins"))
        self._params["limit"] = self._clamp_limit(self._params.get("limit"))
        if not mark_dirty:
            self._dirty = False
            self.dirty_changed.emit(False)
        # Runde 8 (Bugfix 3): Generation erhoehen - die UI verwirft
        # Stale-Payloads aelterer Generation (Queries, die VOR diesem
        # Profilwechsel gestartet wurden).
        self._restore_generation += 1
        # Runde 10 (Bug 4): REIHENFOLGE - erst die UI-Combos synchronisieren
        # (params_restored), DANN die Daten anfordern. Runde 11 (A1): KEIN
        # refresh_all() mehr im Restore-Pfad - das AnalyticsWindow
        # orchestriert die Queries zentral (A6: Sync -> Query-Key-Pruefung
        # -> request_data). Ein expliziter User-Refresh (Button) darf
        # weiterhin refresh_all() nutzen.
        self.params_restored.emit()

    def _apply_heatmap_section(self, heat: Any) -> None:
        """Loest die verschachtelte `charts.heatmap`-Sektion auf (20.02).

        Luecke 5.3-6: `_flatten_payload()` bildet das verschachtelte Dict
        nicht auf die flachen `_params`-Keys ab – dieser Helfer uebernimmt
        die 20.02-Keys additiv (nur vorhandene/gueltige Werte; None bleibt
        unveraendert). Zoom-Bereiche werden geclampt (E8).
        """
        if not isinstance(heat, dict):
            return
        if heat.get("x_dim") is not None:
            self._params["heatmap_x_dim"] = self._sanitize_dim(heat["x_dim"])
        if heat.get("y_dim") is not None:
            self._params["heatmap_y_dim"] = self._sanitize_dim(heat["y_dim"])
        if heat.get("agg") is not None:
            self._params["heatmap_agg"] = str(heat["agg"]).lower()
        if heat.get("field") is not None:
            self._params["heatmap_field"] = str(heat["field"])
        # 21.01 (E1): TF-Freigabe aus dem Payload restaurieren.
        if heat.get("all_timeframes") is not None:
            self._params["heatmap_all_timeframes"] = bool(
                heat["all_timeframes"])
        if heat.get("candle_projection_enabled") is not None:
            self._params["candle_projection_enabled"] = bool(
                heat["candle_projection_enabled"])
        if isinstance(heat.get("zoom_x_range"), (list, tuple)):
            self._params["zoom_x_range"] = self._clamp_zoom(
                heat["zoom_x_range"])
        if isinstance(heat.get("zoom_y_range"), (list, tuple)):
            self._params["zoom_y_range"] = self._clamp_zoom(
                heat["zoom_y_range"])

    def _restore_params_from_payload(self, flat: Dict[str, Any]) -> None:
        """Uebernimmt flache Payload-Params per Replace-Semantik (B3-2).

        Runde 11 (Bug 3, B3-2): Gemeinsamer Restore-Pfad fuer
        `_apply_profile()` und `restore_workspace()`. Bekannte `_params`-Keys
        werden UEBERSCHRIEBEN, sofern der Payload einen nicht-None-Wert
        liefert (additiv, wie bisher). Der Varianten-Filter `instance_hashes`
        folgt echter Replace-Semantik: Fehlt der Key im Payload (Alt-Payloads
        ohne Varianten-Angabe), ist er garantiert leer ([]) statt des
        vorherigen Werts - ein gespeicherter Zustand OHNE Varianten-Ein-
        schraenkung darf nicht stillschweigend den alten Filter uebernehmen.
        Andere Keys (z. B. heatmap-Konfiguration, table-Settings) werden
        NICHT generell geleert - nur vorhandene Payload-Werte zaehlen
        (additiv, kein Datenverlust).
        """
        for key in list(self._params.keys()):
            if key in flat and flat[key] is not None:
                self._params[key] = flat[key]
        if "instance_hashes" not in flat or not flat.get("instance_hashes"):
            self._params["instance_hashes"] = []
        # 21.03.15 (Bug 3): Alt-Profile mit 'YTD'/'Benutzerdefiniert' auf den
        # neuen Range-Preset-Satz abbilden (das Custom-Panel ist entfallen).
        _preset = str(self._params.get("range_preset") or "").strip() or None
        if _preset == "YTD":
            self._params["range_preset"] = "Year"
        elif _preset == "Benutzerdefiniert":
            self._params["range_preset"] = "7d"

    def set_ui_layout(self, layout: Optional[Dict[str, Any]] = None) -> None:
        """Uebernimmt das aktuelle UI-Layout fuer die Profil-Persistenz.

        10.08.2026 (Punkte 3/4): Der ViewModel kennt keine UI-Widgets
        (MVVM-Invariante 4) - das AnalyticsWindow uebergibt page_index und
        heatmap_mode vor jedem save_profile()/create_profile(); die Werte
        wandern ueber _current_payload() (Sektion "layout") in den
        Profil-Payload und werden beim _apply_profile() in
        _workspace_layout restauriert (die UI liest sie dort ueber
        workspace_layout).
        """
        self._ui_layout = dict(layout or {})

    def _current_payload(self) -> Dict[str, Any]:
        """Profil-Payload aus den aktuellen Ansichtsparametern (v2, sectioned).

        20.01 (E3): Die v2-Sektionen sources/charts/table/styling gruppieren
        die bekannten Parameter; neue UI-Settings lassen sich spaeter additiv
        unter neuen Sektionen ergaenzen (kein Schema-Bump noetig).
        """
        p = self._params
        return {
            "schema_version": SCHEMA_VERSION_DEFAULT,
            "sources": {
                "symbol": p.get("symbol"),
                "timeframe": p.get("timeframe"),
                "feature_ids": list(p.get("feature_ids") or []),
                # Runde 11 (Bug 3, B3-1): Varianten-Einschraenkung im
                # Profil-Payload persistieren (Replace-Semantik beim
                # Restore: fehlt der Key -> garantiert leer, B3-2).
                "instance_hashes": list(p.get("instance_hashes") or []),
                # 21.03.12 (MTF-FC auf Analytics): Filterleisten-Zustand
                # (data_tf/agg_tf/range) im Profil persistieren - die
                # Analysequelle, die Aggregations-TF und der Zeitraum des
                # MtfFilterBarWidget werden beim Profilwechsel restauriert.
                # 21.03.14 (Wunsch 2): `sort_mode` kommt additiv hinzu
                # (nach dem Rueckbau der View-Template-Buttons).
                "data_tf": p.get("data_tf"),
                "agg_tf": p.get("agg_tf"),
                "range_preset": p.get("range_preset"),
                "range_from": p.get("range_from"),
                "range_to": p.get("range_to"),
                "all_timeframes": p.get("all_timeframes"),
                "sort_mode": p.get("sort_mode"),
                # 21.03.20 (Analytics Modus-Filter): source_mode-Filter
                # wird additiv in der sources-Sektion persistiert
                # (Restore ueber _restore_params_from_payload).
                "service_mode": p.get("service_mode"),
            },
            "charts": {
                "heatmap_metric": p.get("heatmap_metric"),
                "scatter_x": p.get("scatter_x"),
                "scatter_y": p.get("scatter_y"),
                "distribution_column": p.get("distribution_column"),
                "bins": p.get("bins"),
                # 20.02 (E2/E3): Generische Heatmap-Config additiv unter
                # charts.heatmap (kein Schema-Bump noetig; v2-Sektionen sind
                # fuer additive UI-Settings ausgelegt, 20.01 E3).
                "heatmap": {
                    "x_dim": p.get("heatmap_x_dim"),
                    "y_dim": p.get("heatmap_y_dim"),
                    "field": p.get("heatmap_field"),
                    "agg": p.get("heatmap_agg"),
                    # 21.01 (E1): TF-Freigabe additiv persistieren.
                    "all_timeframes": p.get("heatmap_all_timeframes"),
                    "candle_projection_enabled": p.get(
                        "candle_projection_enabled"),
                    "zoom_x_range": list(p.get("zoom_x_range")
                                         or [0.0, 1.0]),
                    "zoom_y_range": list(p.get("zoom_y_range")
                                         or [0.0, 1.0]),
                },
            },
            "table": {
                "limit": p.get("limit"),
                "table_column_widths": dict(
                    p.get("table_column_widths") or {}),
                "table_row_height": p.get("table_row_height"),
                "table_sort_column": p.get("table_sort_column"),
                "table_sort_order": p.get("table_sort_order"),
            },
            "styling": {},
            # 10.08.2026 (Punkte 3/4): UI-Layout-Anteil (page_index,
            # heatmap_mode) additiv - von der UI via set_ui_layout() gesetzt.
            "layout": dict(self._ui_layout or {}),
        }

    def restore_workspace(self, workspace: Dict[str, Any]) -> None:
        """Wendet den gespeicherten Fenster-Workspace an (20.01, E7).

        Uebernimmt die Workspace-Parameter (letzter Sitzungszustand gewinnt
        ueber das aktive Profil) verlustfrei in `_params` – OHNE Dirty-Flag
        und mit demselben Resolver-Pfad wie `_apply_profile` (fehlende
        Services werden isoliert und via `missing_services_detected`
        gemeldet). Der UI-Layout-Anteil (z. B. page_index) wird separat unter
        `workspace_layout` bereitgestellt (kein `_params`-Key). Danach
        `refresh_all()` (Daten fuer alle Seiten).

        Args:
            workspace: Payload aus `state_manager.get_workspace_state(...)`
                im Format {"params": {...}, "layout": {...}}.
        """
        if not isinstance(workspace, dict):
            return
        self._workspace_layout = dict(workspace.get("layout") or {})
        params = workspace.get("params")
        if not isinstance(params, dict):
            return
        # Runde 11 (Bug 3, B3-2): Gemeinsamer Restore-Helper (Replace-
        # Semantik inkl. instance_hashes -> garantiert leer bei fehlendem
        # Payload-Key statt des alten Werts).
        self._restore_params_from_payload(params)
        # 20.02.01 (E6): Alt-Workspaces mit `dow_hour` -> "hour" (Tageszeit).
        for _hk in ("heatmap_x_dim", "heatmap_y_dim"):
            if self._params.get(_hk) == "dow_hour":
                self._params[_hk] = "hour"
        # 20.04-Q8-Fix (User-Bugreport Punkt 1a): Auch die verschachtelte
        # `charts.heatmap`-Sektion des Workspace-Params restaurieren
        # (heatmap_agg/heatmap_field) – der flache Key-Loop uebernimmt die
        # flachen Keys, aber das verschachtelte Dict (wie im Profil-Payload)
        # muss explizit via _apply_heatmap_section aufgeloest werden.
        if isinstance(params.get("heatmap"), dict):
            self._apply_heatmap_section(params.get("heatmap"))
        self._params["feature_ids"] = self._normalize_feature_ids(
            self._params.get("feature_ids"))
        # Runde 10 (Bug 1): instance_hashes genauso normalisieren.
        self._params["instance_hashes"] = self._normalize_instance_hashes(
            self._params.get("instance_hashes"))
        # 12.08.2026 (Option A): (Service|Parameter)-Auswahl des
        # 'Feld'-Dropdowns genauso normalisieren (identisch zu
        # _apply_profile).
        self._params["field_selection"] = self._normalize_field_pairs(
            self._params.get("field_selection"))
        # Runde 9 (Bug 1): Fehlende Services NUR melden, NICHT aus dem
        # Filter entfernen - der Resolver wuerde sonst den restaurierten
        # Filter stillschweigend kuerzen (die DB liefert fuer unbekannte
        # IDs einfach keine Zeilen; Graceful Degradation ohne Datenverlust).
        if self._params["feature_ids"]:
            _, missing = self._resolve_feature_ids(self._params["feature_ids"])
            if missing:
                self.missing_services_detected.emit(list(missing))
        self._params["bins"] = self._clamp_bins(self._params.get("bins"))
        self._params["limit"] = self._clamp_limit(self._params.get("limit"))
        # Runde 8 (Bugfix 3): Generation erhoehen - die UI verwirft
        # Stale-Payloads aelterer Generation (Queries, die VOR diesem
        # Workspace-Restore gestartet wurden).
        self._restore_generation += 1
        # Runde 10 (Bug 4): REIHENFOLGE - erst die UI-Combos synchronisieren
        # (params_restored), DANN die Daten anfordern. Runde 11 (A1): KEIN
        # refresh_all() mehr im Restore-Pfad - das AnalyticsWindow
        # orchestriert die Queries zentral (A6: Sync -> Query-Key-Pruefung
        # -> request_data).
        self.params_restored.emit()

    @staticmethod
    def _emit_profile_changed(name: str) -> None:
        """Emittiert profile_changed auf dem zentralen EventBus."""
        event_bus.profile_changed.emit(name or "")

    # ------------------------------------------------------------------
    # Jump-to-Chart-Resolution (15.03 Schritt 5, Variante 2)
    # ------------------------------------------------------------------
    def resolve_latest_bar_time(
        self, symbol: str, timeframe: str
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch fuer 'Jump-to-Chart' (oder None).

        Schnelle Punktabfrage (PK-Index) fuer Klick-auf-Punkt aus dem
        Scatter – delegiert lesend an das AnalyticsRepository (kein SQL
        im ViewModel).
        """
        return self._repo.get_latest_bar_time(
            symbol, timeframe,
            feature_ids=self._params.get("feature_ids"),
        )

    def resolve_recent_bar_time_for_cell(
        self, symbol: str, timeframe: str, dow: int, hour: int
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch einer (dow, hour)-Zelle (oder None).

        Jump-to-Chart aus der Heatmap (Doppelklick auf eine Zelle) –
        delegiert lesend an das AnalyticsRepository.
        """
        return self._repo.get_recent_bar_time_for_cell(
            symbol, timeframe, dow, hour,
            feature_ids=self._params.get("feature_ids"),
        )

    # ------------------------------------------------------------------
    # Clamping (Typ- & Werte-Sicherheit)
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp_bins(value: Any) -> int:
        try:
            return max(2, int(value))
        except (TypeError, ValueError):
            return DEFAULT_BINS

    @staticmethod
    def _clamp_limit(value: Any) -> int:
        if value is None:
            return DEFAULT_LIMIT
        try:
            return max(1, min(int(value), MAX_LOOKBACK_LIMIT))
        except (TypeError, ValueError):
            return DEFAULT_LIMIT

    # ------------------------------------------------------------------
    # Lesende Zugriffe fuer UI-Pages
    # ------------------------------------------------------------------
    @property
    def params(self) -> Dict[str, Any]:
        """Kopie der aktuellen Ansichtsparameter (fuer UI-Kontrolle)."""
        return dict(self._params)

    @property
    def active_profile(self) -> Optional[Dict[str, Any]]:
        """Kopie des aktiven Profils (oder None)."""
        return dict(self._active_profile) if self._active_profile else None

    @property
    def profiles(self) -> List[Dict[str, Any]]:
        """Kopie der Profil-Liste (deterministisch nach Name sortiert)."""
        return [dict(p) for p in self._profiles]

    @property
    def is_dirty(self) -> bool:
        """True, wenn ungespeicherte Parametertrends vorliegen ('*')."""
        return self._dirty

    @property
    def workspace_layout(self) -> Dict[str, Any]:
        """UI-Layout-Anteil des zuletzt restaurierten Workspace (20.01, E7).

        Z. B. {"page_index": n} – wird von der UI nach `restore_workspace()`
        abgefragt (kein `_params`-Key).
        """
        return dict(self._workspace_layout)

    @property
    def restore_generation(self) -> int:
        """Generations-Token des letzten Restores (Runde 8, Stale-Guard).

        Wird bei jedem restore_workspace()/_apply_profile() erhoeht und vom
        Worker in jedes Ergebnis-Dict gespiegelt (`data["restore_"]`
        generation). Die UI vergleicht den Payload-Wert mit diesem Token und
        verwirft Payloads aelterer Generation (Queries, die VOR dem Restore
        gestartet wurden, ueberschreiben den synchron restaurierten Zustand
        nicht mehr).
        """
        return self._restore_generation

    def heatmap_metrics(self, symbol: str, timeframe: str) -> List[str]:
        """Verfuegbare Heatmap-Metriken fuer ein Symbol/Timeframe (19.02).

        "count" + numerische feature_data-JSON-Keys (dynamisch). Defensiv:
        ohne Daten/bei Fehler -> ["count"].
        """
        try:
            return self._repo.available_heatmap_metrics(
                str(symbol or ""), str(timeframe or ""))
        except Exception:
            return ["count"]

    def available_feature_columns(
        self, symbol: str, timeframe: str
    ) -> List[str]:
        """Numerische feature_data-JSON-Keys (Scatter-/Verteilungs-Dropdown).

        19.02 (Cleanup): Ersetzt die entfernten nativen Spalten. Defensiv:
        Fehler/leere Daten -> [].
        """
        try:
            return self._repo.available_feature_columns(
                str(symbol or ""), str(timeframe or ""))
        except Exception:
            return []

    # ------------------------------------------------------------------
    # 20.02.01 (E8): Lesbares Service-Label fuer die service_id-Dimension
    # ------------------------------------------------------------------
    def resolve_service_label(self, plugin_id: str) -> str:
        """Lesbares Service-Label '{Kategorie} / {Name}' (20.02.01, E8).

        Formatiert eine `service_id`-Dimension der generischen Heatmap:
        das `srv_`-Prefix entfaellt (metadata['display_name'], z. B.
        'Trend Breakout'), der Kategorie-Pfad (plugin_category_path,
        Slash -> ' / ') wird vorangestellt (z. B.
        'Swing Points / Trend Breakout'). Unbekannte/entfernte IDs ->
        Rohwert (defensiv). Lazy `_selector_model` (Muster
        `_resolve_feature_ids`), rein lesend, kein SQL.
        """
        key = str(plugin_id or "").strip()
        if not key:
            return ""
        # 21.03.20-Bugfix 3: Die service_id-Dimension traegt seit dem
        # Modus-Split '{service_id}::{source_mode}' (leerer Suffix =
        # Service ohne source_mode). Den Modus abspalten und als
        # ' / {Modus}' anhaengen (nur bei nicht-leerem Wert).
        mode_suffix = ""
        if "::" in key:
            key, mode_suffix = key.split("::", 1)
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            plugin = model.get_plugin(key)
            if plugin is None:
                label = key
            else:
                meta = getattr(plugin, "metadata", {}) or {}
                name = str(meta.get("display_name") or key)
                if name.lower().startswith("srv_"):
                    name = name[4:]
                category = str(model.plugin_category_path(key) or "")
                label = f"{category} / {name}" if category else name
            if mode_suffix:
                label = f"{label} / {mode_suffix}"
            return label
        except Exception:
            return key + (f" / {mode_suffix}" if mode_suffix else "")

    def resolve_service_display_name(self, plugin_id: str,
                                     preset_name: Optional[str] = None,
                                     exec_date: Optional[str] = None) -> str:
        """Service-Name OHNE Kategorie-Pfad, direkt aus dem Service-Objekt.

        09.08.2026 (User-Meldung 'Feld'-Dropdown): Der Name wird DIREKT aus
        dem Service-Objekt abgeleitet – aus dessen `plugin_id` (der
        Identitaet des Objekts): `srv_`-Prefix entfaellt, Unterstriche
        werden zu Leerzeichen, Worte title-case ('srv_swing_momentum' ->
        'Swing Momentum'). Damit steht der KORREKTE Service-Name im
        'Feld'-Dropdown der generischen Heatmap; `metadata['display_name']`
        ist nicht zuverlaessig (z. B. 'Swing Momentum Service' mit
        'Service'-Suffix, das wie ein MasterTree-Pfad-Bestandteil wirkt).
        Kein Kategorie-Pfad. Unbekannte/entfernte IDs -> lesbarer Pretty-
        Fallback (defensiv). Rein lesend, kein SQL.

        20.04 (Q2, §4): Optionaler `preset_name` ergaenzt das Label um
        ' ({Preset_Name})' – Anzeige-Format '{Service} ({Preset}) /
        {Parameter}' fuer Parameter-Varianten (Clones). Ohne preset_name
        bleibt das Label unveraendert (Zero-Regression).

        Runde 16 (Bugfix 1, 11.08.2026): Format-Vereinheitlichung auf
        '{Name} / {Preset} / {Datum}' (Schraegstrich statt Klammern;
        'Default' als Platzhalter-Preset wird uebersprungen). Optionaler
        `exec_date` haengt Datum+Uhrzeit der letzten Ausfuehrung an
        ('DD.MM.JJ HH:MM') - Grundlage der Feld-Dropdown-Anzeige.
        """
        key = str(plugin_id or "").strip()
        if not key or key.lower() in ("none", "native") \
                or key.lower().startswith("native_"):
            # 09.08.2026 (User-Meldung Feld-Dropdown, Root Cause 3) +
            # 20.03.02 (F3): Leere/fehlende/Native-Keys liefern einen
            # lesbaren Sammel-Namen statt eines Leerstrings (kein leerer
            # Prefix vor Feld-Eintraegen). `native`/`native_*` werden wie
            # `none` auf 'Allgemein' gemappt (benutzerfreundlich).
            return "Allgemein"
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            plugin = model.get_plugin(key)
            if plugin is None:
                # 09.08.2026 (Root Cause 3): Unbekannte/abgewaehlte Keys
                # (z. B. Native-Rows) -> lesbarer Pretty-Fallback statt
                # Rohwert/Leerstring ('native' -> 'Native').
                pretty = (key.replace("src_", "").replace("srv_", "")
                          .replace("ind_", "").replace("_", " ").title())
                return pretty or key
            pid = str(getattr(plugin, "plugin_id", None) or key)
            name = pid
            for prefix in ("src_", "srv_", "ind_"):
                if name.lower().startswith(prefix):
                    name = name[len(prefix):]
                    break
            pretty = name.replace("_", " ").title()
            if not pretty:
                pretty = key
            # Runde 16 (Bugfix 1): Preset-Name + Ausfuehrungsdatum per
            # Schraegstrich anhaengen ('{Name} / {Preset} / DD.MM.JJ HH:MM').
            # 'Default' ist ein Platzhalter-Preset (Standalone-Services) und
            # wird uebersprungen.
            preset = str(preset_name or "").strip()
            if preset and preset.lower() != "default":
                pretty = f"{pretty} / {preset}"
            exec_d = str(exec_date or "").strip()
            if exec_d:
                pretty = f"{pretty} / {exec_d}"
            return pretty
        except Exception:
            return key

    def checked_variant(
        self, plugin_id: str
    ) -> Optional[Dict[str, str]]:
        """Aktuell gecheckte Variante eines Services inkl. Ausfuehrungsdatum.

        Runde 16 (Bugfix 1, 11.08.2026): Grundlage der Feld-Dropdown-
        Anzeige '{Name} / {Preset} / DD.MM.JJ HH:MM' - das Dropdown haengt
        an Feld-Eintraege die im ServicePicker gecheckte Variante (Preset)
        und das Datum+Uhrzeit ihrer letzten Ausfuehrung an.

        Auswahl-Semantik (identisch zum Reader/Snapshot):
          * Ist `instance_hashes` aktiv (Varianten-Einschraenkung), gewinnt
            die gecheckte Variante (exakter Hash-Match).
          * Ohne Hash-Auswahl zaehlt die ERSTE aktive (nicht archivierte)
            Variante des Services - ist der Service ein reiner Standalone
            (keine Presets), bleibt das Ergebnis None (kein Preset-Anhang).
          * Datum+Uhrzeit: Varianten mit Hash ueber
            `last_execution_datetime_for_hash` ('DD.MM.JJ HH:MM'), hash-lose
            Services ueber `last_execution_date` (nur Datum). Ohne Eintraege
            liefern beide den '--...'-Fallback (die Anzeige laesst ihn aus).

        Returns:
            {"preset_name", "instance_hash", "exec_datetime"} oder None
            (unbekannter Service / keine Presets / Fehler - defensiv).
        """
        key = str(plugin_id or "").strip()
        if not key:
            return None
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            active_hashes = {str(h).strip().lower()
                             for h in (self._params.get("instance_hashes")
                                       or [])}
            clones = (model.plugin_presets() or {}).get(key.lower()) or []
            chosen = None
            if active_hashes:
                for c in clones:
                    if not isinstance(c, dict):
                        continue
                    h = str(c.get("instance_hash") or "").strip()
                    if h and h.lower() in active_hashes:
                        chosen = c
                        break
            else:
                for c in clones:
                    if isinstance(c, dict) and not c.get("is_archived"):
                        chosen = c
                        break
                if chosen is None and clones:
                    chosen = clones[0]
            if chosen is None or not isinstance(chosen, dict):
                return None
            h = str(chosen.get("instance_hash") or "").strip()
            if h:
                exec_date = model.last_execution_datetime_for_hash(key, h)
            else:
                exec_date = model.last_execution_date(key)
            return {
                "preset_name": str(chosen.get("preset_name") or "Default"),
                "instance_hash": h,
                "exec_datetime": exec_date,
            }
        except Exception:
            return None

    def service_execution_datetime(self, plugin_id: str) -> str:
        """Datum+Uhrzeit der letzten Ausfuehrung eines Services.

        Runde 16c (Bugfix 1, 11.08.2026, User-Meldung): Das Feld-Dropdown
        haengt an Services OHNE Varianten (Standalone, z. B.
        srv_trend_breakout - kein Preset/keine Set-Instanz) das
        Ausfuehrungsdatum an ('{Name} / {Key} / DD.MM.JJ HH:MM', z. B.
        '23.04.26 22:14'). Rein lesend ueber das ServiceSelectorModel
        (`last_execution_datetime`); Fallback '--.--.-- --:--' ohne
        Eintraege oder bei Fehlern (defensiv).
        """
        key = str(plugin_id or "").strip()
        if not key:
            return "--.--.-- --:--"
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        try:
            return model.last_execution_datetime(key)
        except Exception:
            return "--.--.-- --:--"

    def resolve_instance_hashes(self,
                                hashes: Iterable[str]) -> List[str]:
        """Loest instance_hash-Werte transparent auf plugin_ids auf (20.04, Q2).

        Quelle: Plugin-Presets/Clones des `ServiceSelectorModel`
        (`plugin_presets()`, in refresh() aus indicator_presets geladen) –
        die Zuordnung Hash -> plugin_id ist dort deterministisch ueber
        `generate_instance_hash` abgelegt. Rueckgabe: deduplizierte
        plugin_ids (Reihenfolge erhalten, case-insensitiv). Hashes ohne
        Treffer werden verworfen (defensiv). Der Filter bleibt dadurch auf
        `WHERE feature_id IN (plugin_ids)` – die Varianten-Aufloesung
        passiert transparent im ViewModel (kein SQL, rein lesend).

        Beispiel: `resolve_instance_hashes(["a91f3b"])` -> ["srv_swing_pivot"].
        """
        wanted = {str(h or "").strip()
                  for h in (hashes or []) if str(h or "").strip()}
        if not wanted:
            return []
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        result: List[str] = []
        seen: Set[str] = set()
        try:
            presets = model.plugin_presets() or {}
            for pid, clones in presets.items():
                if not clones or not isinstance(clones, list):
                    continue
                for clone in clones:
                    if not isinstance(clone, dict):
                        continue
                    h = str(clone.get("instance_hash") or "").strip()
                    if not h or h not in wanted:
                        continue
                    if str(pid).lower() not in seen:
                        seen.add(str(pid).lower())
                        result.append(str(pid))
                    # Ein plugin_id pro Hash genuegt (dedupliziert).
                    wanted.discard(h)
        except Exception:
            pass
        return result

    def _no_data_presets_snapshot(self) -> Dict[str, Any]:
        """Serialisiert die Preset-Modell-Daten fuer die No-Data-Auswertung.

        Runde 11 (Bug 4, B4-1): Die '(No Data)'-Auswertung laeuft im
        QUERY_FEATURES-Worker (Repo, Worker-Thread) - dort ist das
        ServiceSelectorModel nicht verfuegbar. Der ViewModel reicht eine
        reine Daten-Snapshot (in-memory, KEIN SQL) ueber die Query-Params:
            {"presets": {pid: [{"preset_name", "instance_hash",
                                "is_archived"}]},
             "sets": [{"services": {instance_id: {"plugin_id", "params",
                                                   "is_archived"}}}],
             "standalone": [plugin_id der registrierten Plugins ohne
                            Presets und ohne Set-Instanz (hash-lose
                            Variante, 15c)],
             "display_names": {"{pid}|{pname}": "Anzeigename"},
             "active_hashes": [instance_hash der im Picker gecheckten
                               Varianten (leer = keine Einschraenkung)]}
        Der Reader kombiniert den Snapshot mit den DB-Fakten
        (available_instance_hashes / feature_keys_by_service) im Worker-
        Thread und liefert `no_data_variants` als Payload-Attribut (B4-2).

        Runde 13 (Bugfix Dropdown-NoData): `active_hashes` macht den Payload
        VARIANTEN-GENAU - der Reader `resolve_no_data_variants()` liefert
        damit nur noch die im ServicePicker gecheckten Varianten als
        '(No Data)' (nicht-gecheckte Instanzen derselben plugin_id erscheinen
        nicht mehr; das Dropdown zeigt nicht mehr die erste Variante).

        Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026): Reine
        Standalone-Services (registrierte Plugins OHNE Presets/Clones UND
        OHNE Set-Instanz, z. B. srv_trend_breakout) wurden nie in den
        Snapshot aufgenommen - der Reader konnte sie daher nie als
        '(No Data)' markieren, obwohl der feature_store noch keine Rows
        ihrer plugin_id besitzt. Die neue Snapshot-Sektion `standalone`
        listet genau diese Plugins als hash-lose Variante (preset_name
        'Default'); der Reader prueft sie gegen `pids_with_data`.
        """
        model = self._selector_model
        if model is None:
            from analytics.engine.service_selector_model import ServiceSelectorModel
            model = ServiceSelectorModel(parent=self)
            self._selector_model = model
        presets: Dict[str, Any] = {}
        sets: List[Any] = []
        display_names: Dict[str, str] = {}
        # Runde 15c (Bugfix Standalone): Registrierte Plugins ohne Presets
        # und ohne Set-Instanz als hash-lose '(No Data)'-Kandidaten.
        standalone: List[str] = []
        # Runde 12 (Punkt 4): Nur GE CHECKTE Services in den Snapshot
        # aufnehmen (feature_ids-Filter; leer = kein Filter = alle). Nicht
        # angehakte Services duerfen keine '(No Data)'-Hinweise liefern.
        active_ids = {str(f).strip().lower()
                      for f in (self._params.get("feature_ids") or [])}
        # Runde 13c (Bugfix Dropdown-NoData, Kernwunsch): Leerer Filter
        # (feature_ids=[]) = KEINE '(No Data)'-Eintraege. Ohne aktive
        # Datenquellen-Auswahl wuerde der Snapshot ALLE Services enthalten
        # und der Reader jede NoData-Variante im Feld-Dropdown anzeigen
        # (der Button 'Aktive Filter entfernen' verspricht 'zeigt danach
        # wieder alle Features' – ohne NoData-Rauschen).
        if not active_ids:
            return {"presets": {}, "sets": [], "display_names": {},
                    "active_hashes": []}
        # Runde 13 (Bugfix Dropdown-NoData): Varianten-Einschraenkung mit
        # an den Reader geben - die '(No Data)'-Auswertung wird damit
        # variantengenau (nur im Picker gecheckte Varianten im Payload).
        active_hashes = {str(h).strip().lower()
                         for h in (self._params.get("instance_hashes") or [])}
        try:
            for pid, clones in (model.plugin_presets() or {}).items():
                pid_s = str(pid)
                if active_ids and pid_s.strip().lower() not in active_ids:
                    continue
                clone_list: List[Dict[str, Any]] = []
                for c in clones or []:
                    if not isinstance(c, dict):
                        continue
                    h_s = str(c.get("instance_hash") or "").strip().lower()
                    # Runde 13b (Bugfix Dropdown-NoData): Harte Varianten-
                    # Einschraenkung - sind Hashes gecheckt (active_hashes
                    # nicht leer), duerfen NUR diese Varianten in den
                    # Snapshot (bewusst OHNE `h_s and`-Guard: eine hash-lose
                    # Variante ist bei aktiver Einschraenkung nie Teil der
                    # Auswahl und darf kein '(No Data)' liefern - sonst
                    # erscheinen ungecheckte Instanzen weiterhin).
                    if active_hashes and h_s not in active_hashes:
                        continue
                    pname = str(c.get("preset_name") or "Default")
                    clone_list.append({
                        "preset_name": pname,
                        "instance_hash": str(c.get("instance_hash") or ""),
                        "is_archived": bool(c.get("is_archived")),
                    })
                    display_names[f"{pid_s}|{pname}"] = \
                        self.resolve_service_display_name(pid_s, pname)
                if clone_list:
                    presets[pid_s] = clone_list
            for s in model.get_sets() or []:
                if not isinstance(s, dict):
                    continue
                services = s.get("services")
                if not isinstance(services, dict):
                    continue
                if active_ids:
                    services = {
                        k: svc for k, svc in services.items()
                        if isinstance(svc, dict)
                        and str(svc.get("plugin_id") or "").strip().lower()
                        in active_ids}
                if services:
                    sets.append({"services": services})
            # Runde 15c (Bugfix Standalone, User-Meldung 10.08.2026):
            # Registrierte Plugins, die weder Presets/Clones noch eine
            # Set-Instanz besitzen (z. B. srv_trend_breakout), sind reine
            # Standalone-Services. Als hash-lose Variante (preset_name
            # 'Default') geprueft, erscheinen sie im Feld-Dropdown, sobald
            # der feature_store noch keine Rows ihrer plugin_id besitzt.
            # Beim Vorhandensein von Daten (pids_with_data) bleibt der
            # NoData-Hinweis aus (Reader-Semantik). Ausgeschlossen sind
            # Plugins mit Presets oder Set-Instanzen (dort laeuft die
            # bestehende Preset-/Set-Auswertung).
            # Runde 16 (Bugfix Mischbetrieb, User-Meldung 5/6, 11.08.2026):
            # Der Runde-15c-Guard `if not active_hashes:` ist ENTFERNT - er
            # schloss die Standalone-Sektion aus, sobald eine Hash-Auswahl
            # aktiv war (Mischbetrieb Service + Version). Standalone-
            # Services werden UEBER `feature_ids` gecheckt, NICHT ueber
            # Hashes - eine aktive Varianten-Einschraenkung darf sie daher
            # nicht aus der NoData-Auswertung verwerfen.
            try:
                all_presets = model.plugin_presets() or {}
                preset_keys = {str(k).strip().lower()
                               for k in all_presets}
                set_pids: Set[str] = set()
                for _s in model.get_sets() or []:
                    _services = (_s.get("services")
                                 if isinstance(_s, dict) else None)
                    if not isinstance(_services, dict):
                        continue
                    for _svc in _services.values():
                        if isinstance(_svc, dict) and str(
                                _svc.get("plugin_id") or "").strip():
                            set_pids.add(
                                str(_svc["plugin_id"]).strip().lower())
                for _pid in (model.get_plugins() or {}).keys():
                    _pid_l = str(_pid).strip().lower()
                    if not _pid_l:
                        continue
                    if active_ids and _pid_l not in active_ids:
                        continue
                    if _pid_l in preset_keys or _pid_l in set_pids:
                        continue
                    standalone.append(_pid)
                    display_names[f"{_pid}|Default"] = \
                        self.resolve_service_display_name(_pid)
            except Exception:
                pass
        except Exception:
            pass
        return {
            "presets": presets,
            "sets": sets,
            "standalone": standalone,
            "display_names": display_names,
            "active_hashes": sorted(active_hashes),
        }

    @property
    def max_lookback_limit(self) -> int:
        """Max-Lookback-Cap (UI-Slider-Maximum)."""
        return MAX_LOOKBACK_LIMIT

    def available_timeframes(self, symbol: str) -> List[str]:
        """Timeframes mit Feature-Store-Daten fuer ein Symbol (TF-Ausgrauung).

        Delegiert lesend an das AnalyticsRepository (kein SQL im ViewModel).
        Bei Fehlern wird eine leere Liste geliefert; die UI kann dann alle
        Timeframes aktiv lassen (Fallback).
        """
        try:
            return self._repo.available_timeframes(str(symbol or ""))
        except Exception:
            return []

```

--------------------------------------------------

### DATEI: analytics/engine/analytics_worker.py
```py
# analytics/engine/analytics_worker.py
"""
analytics_worker.py - AnalyticsAsyncWorker (Phase 15.03 Schritt 4).

Asynchroner DuckDB-Query-Worker (QThread) fuer die Analytics-UI.

Entkopplung (Invariante 4 / MVVM):
    DuckDB -> FeatureStoreReader/AnalyticsRepository -> AnalyticsAsyncWorker
    -> AnalyticsViewModel -> UI-Pages

Der Worker fuehrt EINE einzelne Datenabfrage (Tabelle, Heatmap, Scatter,
Verteilung, Metadaten) in einem separaten QThread aus, damit die GUI nicht
blockiert (Analogie: ServiceSetRunWorker / LiveAnalyzer). Die DB-Zugriffe
laufen ueber `AnalyticsRepository`/`FeatureStoreReader` – beide nutzen den
Thread-local `DbPool` (eine Connection pro Thread & DB-Datei,
Thread-Safety-Invariante 6); der Worker-Thread erhaelt dadurch automatisch
seine eigene Connection und blockiert nie den App-Hauptthread.

Max-Lookback-Cap (15.03-Spezifikation): `MAX_LOOKBACK_LIMIT = 50_000`
deckelt alle limit-Parameter hart nach oben – gegen SQL-Feuer / UI-Freeze.

Signale (werden vom Worker-Thread emittiert; Qt stellt die Queued
Connection zum ViewModel im Hauptthread her):
    finished_ok = Signal(object, str, dict)   – worker, query_kind, Ergebnis
    failed      = Signal(object, str, str)    – worker, query_kind, Fehlermeldung

Die Worker-Referenz im Signal ist Teil des Race-Fix (15.03): Das ViewModel
kann damit verspaetete Ergebnisse veralteter Worker verwerfen (Guard
`self._worker is worker`).

Der Worker ist EINWEG (eine Abfrage pro Instanz). Das ViewModel erzeugt pro
Abfrage eine neue Instanz; die Qt-Elternschaft (parent) haelt die Instanz
am Leben und `worker.finished.connect(worker.deleteLater)` raeumt auf.

Abfrage-Typen (query_kind, Single Source of Truth fuer Worker & ViewModel):
    QUERY_TABLE        – rohe Feature-Zeilen (Tabellen-Seite)
    QUERY_HEATMAP      – 2D-Matrix Wochentag x Tagesstunde (Berlin Wanduhr)
    QUERY_HEATMAP_GENERIC – 2D-Matrix mit freien Dimensionen/Aggregationen
                            (20.02, additiv)
    QUERY_OHLCV        – OHLCV-Snapshot fuer das Candle-Overlay (20.02, E9)
    QUERY_DAILY_OHLC   – Tages-Ohlc (SQL-seitig aggregiert) fuer das
                         Candle-Overlay im selben Canvas (20.02-Bugfix)
    QUERY_SCATTER      – X/Y-Paare zweier nativer Spalten
    QUERY_DISTRIBUTION – Histogramm (bins/counts)
    QUERY_FEATURES     – Metadaten (Plugin-IDs, Spalten, Zeilenzahl)
"""

from typing import Any, Dict, Optional

from PySide6.QtCore import QThread, Signal

# Abfrage-Typen (query_kind).
QUERY_TABLE = "table"
QUERY_HEATMAP = "heatmap"
# 20.02 (additiv): Generische 2D-Heatmap (freie Dimensionen/Aggregationen)
# und OHLCV-Snapshot fuer das Candle-Overlay (E9). Der bestehende QUERY_HEATMAP
# (Dow×Stunde) bleibt unveraendert.
QUERY_HEATMAP_GENERIC = "heatmap_generic"
QUERY_OHLCV = "ohlcv"
# 20.02-Bugfix (09.08.2026, Punkt 1+2): Tages-Ohlc fuer das Candle-Overlay im
# selben Canvas – SQL-seitig aggregiert (fetch_daily_ohlc), deckt den gesamten
# Heatmap-Zeitraum ab statt nur OHLCV_SNAPSHOT_LIMIT Bars.
QUERY_DAILY_OHLC = "daily_ohlc"
QUERY_SCATTER = "scatter"
QUERY_DISTRIBUTION = "distribution"
QUERY_FEATURES = "features"

# Max-Lookback-Cap (15.03-Spezifikation): Keine Abfrage darf mehr als
# 50.000 Zeilen anfordern.
MAX_LOOKBACK_LIMIT = 50_000


def cap_lookback_limit(value: Optional[int]) -> Optional[int]:
    """Deckelt einen limit-Wert hart auf MAX_LOOKBACK_LIMIT.

    None (Repo-Default) bleibt None; ungueltige Werte -> None.
    """
    if value is None:
        return None
    try:
        return max(1, min(int(value), MAX_LOOKBACK_LIMIT))
    except (TypeError, ValueError):
        return None


class AnalyticsAsyncWorker(QThread):
    """Fuehrt eine einzelne Analytics-Datenabfrage im Hintergrund aus.

    EINWEG-Worker: Eine Abfrage pro Instanz. Das ViewModel erzeugt bei
    Bedarf neue Instanzen und verbindet finished_ok/failed.
    """

    finished_ok = Signal(object, str, dict)  # worker, query_kind, Ergebnis-Dict
    failed = Signal(object, str, str)        # worker, query_kind, Fehlermeldung

    def __init__(
        self,
        repository: Any,
        query_kind: str,
        params: Optional[Dict[str, Any]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._repository = repository
        self._query_kind = query_kind
        self._params = dict(params or {})
        self._cancelled = False

    def cancel(self) -> None:
        """Bricht die Abfrage ab (Ergebnis-Signale werden unterdrueckt)."""
        self._cancelled = True

    def run(self) -> None:  # noqa: D102
        if self._cancelled:
            return
        try:
            result = self._execute()
        except Exception as e:
            if not self._cancelled:
                self.failed.emit(self, self._query_kind, str(e))
            return
        finally:
            # Connection-Leak vermeiden (Fix 15.03): Die im Worker-Thread
            # ueber DbPool geoeffnete DuckDB-Connection wird am Ende
            # freigegeben – sonst bleibt pro Abfrage ein offenes Datei-Handle
            # zurueck und die App haengt nach vielen Abfragen (TF-Wechsel).
            self._release_thread_connections()
        if not self._cancelled:
            # Runde 8 (Bugfix 3): Das Generations-Token aus den Worker-Params
            # ins Ergebnis-Dict spiegeln - die UI verwirft damit Stale-Payloads
            # (Queries, die VOR dem letzten restore_workspace()/_apply_profile()
            # gestartet wurden).
            try:
                if isinstance(result, dict):
                    result["restore_generation"] = self._params.get(
                        "restore_generation")
            except Exception:
                pass
            self.finished_ok.emit(self, self._query_kind, result)

    def _release_thread_connections(self) -> None:
        """Gibt die DuckDB-Connections des Worker-Threads frei (Leak-Fix).

        DbPool.close_all() schliesst die Thread-lokalen Connections des
        aktuellen Threads (und dekrementiert den globalen Referenzzaehler).
        Jeder neue Worker-Thread erhaelt beim naechsten Zugriff automatisch
        eine frische Connection.
        """
        try:
            from db_service import DbPool
            DbPool.close_all()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Dispatch auf die Repository-Methoden (lesend, kein SQL hier)
    # ------------------------------------------------------------------
    def _execute(self) -> Dict[str, Any]:
        repo = self._repository
        p = self._params
        symbol = str(p.get("symbol", "") or "")
        timeframe = str(p.get("timeframe", "") or "")
        # 15.03-E (Multi-Select): feature_ids (Liste) bevorzugt; Legacy-
        # Einzelwert feature_id dient als Fallback (Alt-Aufrufer/Profil).
        feature_ids = p.get("feature_ids")
        if not feature_ids and p.get("feature_id"):
            feature_ids = [p["feature_id"]]
        # Runde 10 (Bug 1): Varianten-Einschraenkung an die Repo-Methoden.
        instance_hashes = p.get("instance_hashes") or []
        # 21.03.12 (MTF-FC auf Analytics): Optionaler Zeitfilter + Bucket-TF.
        from_ts = p.get("from_ts")
        to_ts = p.get("to_ts")
        bucket_tf = p.get("bucket_tf") or None
        # 21.03.20 (Analytics Modus-Filter): globaler
        # source_mode-Filter fuer Multi-Modus-Services
        # (None/"all" = kein Filter).
        service_mode = p.get("service_mode")

        if self._query_kind == QUERY_TABLE:
            return repo.get_table(
                symbol, timeframe,
                feature_id=p.get("feature_id"),
                feature_ids=feature_ids,
                instance_hashes=instance_hashes,
                limit=cap_lookback_limit(p.get("limit")),
                from_ts=from_ts, to_ts=to_ts,
                service_mode=service_mode,
            )
        if self._query_kind == QUERY_HEATMAP:
            return repo.get_heatmap(
                symbol, timeframe,
                metric=str(p.get("metric", "count") or "count"),
                feature_id=p.get("feature_id"),
                feature_ids=feature_ids,
                instance_hashes=instance_hashes,
                from_ts=from_ts, to_ts=to_ts,
                service_mode=service_mode,
            )
        if self._query_kind == QUERY_HEATMAP_GENERIC:
            # 20.02 (additiv): Generische 2D-Heatmap – Parameter x_dim/y_dim/
            # field/agg kommen aus den ViewModel-_params (heatmap_*).
            return repo.get_generic_heatmap(
                symbol, timeframe,
                x_dim=str(p.get("x_dim", "date") or "date"),
                y_dim=str(p.get("y_dim", "hour") or "hour"),
                field=p.get("field") or None,
                agg=str(p.get("agg", "count") or "count"),
                feature_id=p.get("feature_id"),
                feature_ids=feature_ids,
                instance_hashes=instance_hashes,
                limit=cap_lookback_limit(p.get("limit")),
                # Runde 12 (Option A): Preset-Snapshot fuer die No-Data-
                # Auswertung im selben Worker (kein separater
                # QUERY_FEATURES-Roundtrip mehr).
                presets_data=p.get("presets_data") or None,
                # 21.01 (E1, 11.08.2026): TF-Freigabe fuer Timeframe-Matrizen
                # (Preset `[📊 Service-Timeframe]`) – Bool aus den Params.
                all_timeframes=bool(p.get("all_timeframes", False)),
                # 21.03.12 (Entscheidung 6a): Aggregations-TF fuer das
                # date-Raster + optionaler Zeitfilter (Wanduhr-Epochs).
                bucket_tf=bucket_tf,
                from_ts=from_ts, to_ts=to_ts,
                # 12.08.2026 (Option A, Bug 1/2): (Service|Parameter)-
                # Auswahl des 'Feld'-Dropdowns -> Reader filtert auf
                # Parameter-Ebene (feature_data-JSON-Keys je Service).
                field_pairs=p.get("field_selection") or [],
                service_mode=service_mode,
            )
        if self._query_kind == QUERY_OHLCV:
            # 20.02 (E9): OHLCV-Snapshot fuer das Candle-Overlay – limit=None
            # -> Reader-Default OHLCV_SNAPSHOT_LIMIT (5000).
            return repo.get_ohlcv_snapshot(
                symbol, timeframe,
                limit=cap_lookback_limit(p.get("limit")),
            )
        if self._query_kind == QUERY_DAILY_OHLC:
            # 20.02-Bugfix (09.08.2026): Tages-Ohlc (SQL-seitig aggregiert)
            # fuer das Candle-Overlay im selben Canvas – max_days=None ->
            # Reader-Default DAILY_OHLC_MAX_DAYS (4000 Tage).
            return repo.get_daily_ohlc(
                symbol, timeframe,
                max_days=cap_lookback_limit(p.get("max_days")),
            )
        if self._query_kind == QUERY_SCATTER:
            return repo.get_scatter(
                symbol, timeframe,
                x_column=p.get("x_column") or None,
                y_column=p.get("y_column") or None,
                feature_id=p.get("feature_id"),
                feature_ids=feature_ids,
                instance_hashes=instance_hashes,
                limit=cap_lookback_limit(p.get("limit")),
                from_ts=from_ts, to_ts=to_ts,
                service_mode=service_mode,
            )
        if self._query_kind == QUERY_DISTRIBUTION:
            return repo.get_distribution(
                symbol, timeframe,
                column=p.get("column") or None,
                bins=p.get("bins", 20),
                feature_id=p.get("feature_id"),
                feature_ids=feature_ids,
                instance_hashes=instance_hashes,
                limit=cap_lookback_limit(p.get("limit")),
                from_ts=from_ts, to_ts=to_ts,
                service_mode=service_mode,
            )
        if self._query_kind == QUERY_FEATURES:
            # Runde 11 (Bug 4, B4-1): Preset-Snapshot aus den Query-Params
            # fuer die No-Data-Auswertung (Repo berechnet no_data_variants
            # im Worker-Thread; kein DB-Zugriff im UI-Hauptthread).
            # Runde 15 (Fix 1): feature_ids/instance_hashes fuer die Feld-
            # Metadaten (metrics/field_sources) im leichten QUERY_FEATURES-
            # Pfad (Feld-Dropdown OHNE Heatmap-Pivot).
            return repo.get_available_features(
                symbol, timeframe,
                presets_data=p.get("presets_data") or None,
                feature_ids=feature_ids,
                instance_hashes=instance_hashes,
                # 21.03.20-Bugfix 3: Modus-Filter fuer die Feld-Metadaten
                # (modus-spezifische Ergebnis-Parameter im Feld-Dropdown).
                service_mode=service_mode,
            )

        raise ValueError(
            f"[AnalyticsAsyncWorker] Unbekannte Abfrage '{self._query_kind}' – "
            f"erlaubt: {QUERY_TABLE}, {QUERY_HEATMAP}, {QUERY_HEATMAP_GENERIC}, "
            f"{QUERY_OHLCV}, {QUERY_DAILY_OHLC}, {QUERY_SCATTER}, "
            f"{QUERY_DISTRIBUTION}, {QUERY_FEATURES}."
        )

```

--------------------------------------------------

### DATEI: analytics/engine/feature_store_reader.py
```py
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
    # 21.03.20-Bugfix 3: Die Service-Achse splittet je
    # (feature_id, source_mode)-Kombination - ein Multi-Modus-Service
    # (z. B. Swing Momentum mit 3 Modi) belegt bei \"alle Modi\" drei
    # Achsenpunkte. Services ohne source_mode erhalten den leeren
    # Modus-Suffix (\"srv_x::\"); das Widget/VM-Resolver zeigt nur bei
    # nicht-leerem Modus \"Service / Modus\" an. Der Modus-Filter
    # (service_mode) schraenkt die Rows VOR der Aggregation ein -
    # bei konkretem Modus bleibt genau ein Achsenpunkt je Service.
    "service_id": (
        "LOWER(feature_id) || '::' || COALESCE("
        "json_extract_string(feature_data, '$.source_mode'), '')"
    ),
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

# 21.03.12 (MTF-FC auf Analytics, Entscheidung 6a): Aggregations-TF ->
# Bucket-Sekunden fuer das date-Raster der generischen Heatmap (`agg_tf`
# fixiert auf einen konkreten TF, z. B. 'M15'/'H1'). 'auto' bedeutet KEIN
# Bucketing (Granularitaet dynamisch, bisheriges Verhalten).
TF_SECONDS = {
    "M1": 60, "M2": 120, "M5": 300, "M10": 600, "M15": 900,
    "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400,
    "W1": 604800, "MN1": 2592000,
}

# 13.08.2026 (Punkt 3, F3): Kanonische TF-Reihenfolge (fein -> grob) fuer
# Pill-Strips (TfStatusBadgeBar), TF-Dropdowns und Verfuegbarkeitslisten.
# Reihenfolge entspricht der broker-ueblichen Skala M1..MN1 inkl. M2/M10
# (vorher lieferte `ORDER BY timeframe` die ALPHABETISCHE Reihenfolge:
# D1, H1, H4, M1, M10, M15, M30, M5, MN1, W1 - falsch im UI).
CANONICAL_TIMEFRAME_ORDER = [
    "M1", "M2", "M5", "M10", "M15", "M30",
    "H1", "H4", "D1", "W1", "MN1",
]


def canonical_tf_sort(tfs) -> List[str]:
    """Sortiert Timeframe-Strings kanonisch fein -> grob (13.08.2026, F3).

    Bekannte TFs folgen CANONICAL_TIMEFRAME_ORDER; unbekannte TFs
    (z. B. neue Broker-TFs) landen deterministisch am Ende. Defensiv
    gegen None/leer (ruft beide Stellen: fetch_service_tf_status und
    get_available_timeframes).
    """
    order = {tf: i for i, tf in enumerate(CANONICAL_TIMEFRAME_ORDER)}
    return sorted(
        (str(t).strip().upper() for t in (tfs or [])
         if t is not None and str(t).strip()),
        key=lambda tf: (order.get(tf, 10 ** 6), tf),
    )


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
                    f"(instance_hash IS NULL OR instance_hash = '' OR "
                    f"LOWER(TRIM(instance_hash)) IN ({placeholders}))")
                params.extend(hashes)

    @staticmethod
    def _apply_field_pair_filter(
        field_pairs: Optional[List[str]],
        conditions: List[str],
        params: List[Any],
    ) -> None:
        """Erweitert WHERE um den (Service|Parameter)-Paar-Filter.

        12.08.2026 (Option A, Bug 1/2): Jedes Paar '{service_id}|{key}'
        des 'Feld'-Dropdowns wird zu einer OR-Bedingung
        `LOWER(TRIM(feature_id)) = ? AND json_extract_string(feature_data,
        '$.key') IS NOT NULL` - der Reader filtert damit auf PARAMETER-Ebene (nur Rows, deren
        feature_data den gewaehlten JSON-Key des jeweiligen Services
        wirklich traegt). Identifier-unsichere Keys werden defensiv
        uebersprungen (kein SQL-Injection-Risiko, Muster
        `_is_json_key_identifier`). Leere/None-Liste = kein Filter.
        """
        if not field_pairs:
            return
        clauses: List[str] = []
        for pair in field_pairs:
            s = str(pair or "")
            if "|" not in s:
                continue
            sid, key = s.split("|", 1)
            sid = sid.strip()
            key = key.strip()
            if not sid or not key or not FeatureStoreReader._is_json_key_identifier(key):
                continue
            # 12.08.2026 (Option A): `json_extract_string(..., '$.key')` statt
            # `feature_data->>'key'` - der DuckDB-Arrow-Operator kollidiert in
            # Kombination mit LOWER/TRIM-Equalities mit einem Optimizer-Bug
            # (v1.5.5: versucht die JSON-Spalte auf numerisch/BOOL zu casten
            # und wirft fuer nicht-matchende Zeilen). json_extract_string
            # liefert NULL fuer fehlende Keys (identische Semantik) und ist
            # sowohl fuer VARCHAR- als auch JSON-Spalten stabil.
            clauses.append(
                f"(LOWER(TRIM(feature_id)) = ? AND "
                f"json_extract_string(feature_data, '$.{key}') IS NOT NULL)")
            params.append(sid.lower().strip())
        if clauses:
            conditions.append("(" + " OR ".join(clauses) + ")")

    # 21.03.20 (Analytics Modus-Filter): source_mode-Filter fuer
    # Multi-Modus-Services (srv_swing_structure/srv_swing_momentum/...).
    # Nur die 6 Swing-/Trend-Services schreiben `source_mode` top-level
    # in jedes feature_data-Record; `"all"`/None/leer = kein Filter.
    # Muster-Konsistenz (21.03.16): json_extract_string statt
    # feature_data->>'source_mode' (DuckDB-v1.5.5-Arrow-Optimizer-Bug
    # in Kombination mit LOWER/TRIM-Equalities). LOWER auf beiden Seiten
    # = case-tolerantes Matching (z. B. 'ma_peak_hysteresis').
    @staticmethod
    def _apply_mode_filter(
        service_mode: Optional[str],
        conditions: List[str],
        params: List[Any],
    ) -> None:
        if not service_mode or str(service_mode).lower() in ("all", "alle", ""):
            return
        conditions.append(
            "LOWER(json_extract_string(feature_data, '$.source_mode')) = LOWER(?)")
        params.append(str(service_mode).strip())

    # 21.03.12 (MTF-FC auf Analytics): Optionaler bar_time-Zeitfilter.
    # Wird von allen Daten-Queries (fetch_rows/fetch_columns/fetch_heatmap/
    # fetch_generic_heatmap) ueber `from_ts`/`to_ts` aufgerufen.
    @staticmethod
    def _apply_time_range(
        from_ts: Optional[Any],
        to_ts: Optional[Any],
        conditions: List[str],
        params: List[Any],
    ) -> None:
        """Erweitert WHERE um einen optionalen bar_time-Zeitfilter.

        `from_ts`/`to_ts` sind Wanduhr-Epochs (int, relativ zum letzten
        Datenpunkt – `now_provider` des MtfFilterBarWidget) oder None.
        `EXTRACT('epoch' FROM bar_time)` liefert exakt die gespeicherte
        Wanduhr-Epoch (Invariante 7) – der Vergleich ist damit DST-robust
        (Wanduhr gegen Wanduhr). Ungueltige Werte werden defensiv
        ignoriert (kein Filter).
        """
        if from_ts is None and to_ts is None:
            return
        try:
            f = int(from_ts)
        except (TypeError, ValueError):
            f = None
        try:
            t = int(to_ts)
        except (TypeError, ValueError):
            t = None
        if f is not None and t is not None:
            conditions.append(
                "EXTRACT('epoch' FROM bar_time)::BIGINT BETWEEN ? AND ?")
            params.extend([f, t])
        elif f is not None:
            conditions.append("EXTRACT('epoch' FROM bar_time)::BIGINT >= ?")
            params.append(f)
        elif t is not None:
            conditions.append("EXTRACT('epoch' FROM bar_time)::BIGINT <= ?")
            params.append(t)

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
                    # 21.03.12 (bucket_tf): tz-aware Datetimes (Session-TZ)
                    # auf naive Wanduhr-UTC normalisieren - sonst zeigt das
                    # Label den Berlin-Nachbar-Datumstag (+2h/+1h).
                    try:
                        value = value.astimezone(
                            _dt_timezone.utc).replace(tzinfo=None)
                    except Exception:
                        pass
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
                    # 21.03.12 (bucket_tf): Naive Datetimes von to_timestamp
                    # sind Wanduhr-encoded - als UTC-Darstellung interpretieren
                    # (Invariante 7), sonst waere die Achse um den Berlin-
                    # Offset (+2h/+1h) verschoben.
                    if v.tzinfo is None:
                        out.append(float(int(
                            v.replace(tzinfo=_dt_timezone.utc).timestamp())))
                    else:
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

    def fetch_service_tf_status(
        self, plugin_id: str, instance_hash: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Timeframe-Verfuegbarkeit eines Services (21.01b, Schritt 1).

        Liest fuer die Pill-Badges (TfStatusBadgeBar) je Timeframe des
        Services die Anzahl der Feature-Store-Eintraege und den letzten
        Schreib-Zeitpunkt direkt aus der feature_store-Tabelle.

        Bugfix 12.08.2026 (User-Meldung 'Data only loeschen'): Ohne
        `instance_hash` ist die Abfrage service-weit (alle Varianten der
        plugin_id). Wird ein `instance_hash` uebergeben, werden NUR die
        Rows GENAU dieser Variante gezaehlt – nach dem Purge einer
        Variante verschwinden ihre TF-Pills damit korrekt (vorher zeigten
        die Pill-Badges die TFs aller Varianten des Services gemeinsam).

        SQL: SELECT LOWER(timeframe), COUNT(*), MAX(created_at)
             FROM feature_store
             WHERE LOWER(TRIM(feature_id)) = LOWER(TRIM(?))
               [AND LOWER(TRIM(instance_hash)) = LOWER(TRIM(?))]
             GROUP BY LOWER(timeframe)

        Robustheit wie `fetch_last_execution_dates`: Case-insensitiv
        (LOWER/TRIM auf feature_id UND timeframe) und defensiv gegen
        NULL/leere Rows (feature_id, timeframe, created_at).

        Args:
            plugin_id: Plugin-ID des Services (z.B. 'srv_proximity').
            instance_hash: Optionaler Varianten-Hash – werden nur gesetzt,
                zeigt der Status ausschliesslich diese Variante (Clone/
                Preset/Set-Instanz). None/leer = service-weit.

        Returns:
            Dict Timeframe (upper, z.B. 'M1') -> {'count': int, 'last_run': str}
            mit 'last_run' als 'DD.MM.JJ HH:MM' (Wanduhr, UTC-Darstellung);
            leer bei fehlender DB/Tabelle oder Fehler (defensiv).
        """
        if not plugin_id or not str(plugin_id).strip():
            return {}
        conditions = [
            "feature_id IS NOT NULL AND TRIM(feature_id) != ''",
            "LOWER(TRIM(feature_id)) = LOWER(TRIM(?))",
        ]
        params: List[Any] = [str(plugin_id)]
        # Varianten-Scope (Bugfix 12.08.2026): exakter Hash-Match (nur diese
        # Variante, keine service-weiten Alt-Rows anderer Instanzen).
        h_s = str(instance_hash or "").strip()
        if h_s:
            conditions.append("LOWER(TRIM(instance_hash)) = LOWER(TRIM(?))")
            params.append(h_s)
        con = self._get_connection()
        try:
            rows = con.execute(f"""
                SELECT LOWER(TRIM(timeframe)) AS tf, COUNT(*) AS cnt,
                       MAX(created_at) AS last_run
                FROM feature_store
                WHERE {' AND '.join(conditions)}
                GROUP BY LOWER(TRIM(timeframe))
            """, params).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_service_tf_status "
                  f"fehlgeschlagen: {e}")
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            tf_raw = r[0]
            cnt = r[1]
            created = r[2]
            if tf_raw is None or cnt is None:
                continue
            last_run = ""
            if created is not None:
                try:
                    last_run = created.strftime("%d.%m.%y %H:%M")
                except (AttributeError, ValueError):
                    last_run = ""
            out[str(tf_raw).upper()] = {"count": int(cnt), "last_run": last_run}
        # 13.08.2026 (Punkt 3, F3): Sortierte Rueckgabe (kanonisch fein ->
        # grob) - die Pill-Strips aller drei Fenster (AnalyticsWindow,
        # ServicePicker, ServiceWindow) rendern die TFs damit korrekt
        # sortiert statt alphabetisch.
        return {tf: out[tf] for tf in canonical_tf_sort(out)}

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
            """, [symbol]).fetchall()
            # 13.08.2026 (Punkt 3, F3): Kanonische Sortierung statt
            # `ORDER BY timeframe` (alphabetisch).
            return canonical_tf_sort(
                [str(r[0]) for r in rows if r[0] is not None])
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

```

--------------------------------------------------

### DATEI: analytics/ui/__init__.py
```py

```

--------------------------------------------------

### DATEI: analytics/ui/analytics_win.py
```py
# analytics/ui/analytics_win.py
"""
analytics_win.py - AnalyticsWindow (Phase 15.03).

Hauptfenster der Analytics-Engine: `PersistentWindow` mit INSTANCE_ID
"win_analytics", 1280 x 800, nicht-modal. Ersetzt das Legacy-
Statistik-Fenster (`statistic_win.py`; E-1: das Alt-Repository
`analytics/statistics_repository.py` bleibt bestehen).

MVVM-Orchestrator (Invariante 4, kein SQL in der UI):
    UI (Top-Bar CRUD, Sidebar, Pages) <-> AnalyticsViewModel <-> Worker
    <-> AnalyticsRepository/FeatureStoreReader <-> DuckDB

Aufgaben (15.03-Spezifikation):
- Top-Bar: Profil-CRUD (Option B – Explicit Save, Dirty-Flag '*').
- Sidebar-Navigation: Tabelle, Heatmap, Scatter, Verteilung, Equity.
- 15.03-E: Datenquellen-Dialog (`ServiceSelectorDialog`, Multi-Select) ersetzt
  das alte combo_feature-Dropdown UND das Service-Filter-Popover – Checkbox-
  MasterTree (Sets/Services/Standalone/Plugins), Button `[ 🛠️ Datenquellen:
  ... ▾ ]`, ViewModel `set_feature_ids(...)`, SQL `WHERE feature_id IN (...)`.
- Jump-to-Chart (Variante 2): open_chart_at_bar(symbol, tf, bar_time)
  und Chart-Fenster in den Vordergrund holen.
- E-2: Migration der win_statistics-Persistenz nach win_analytics
  (Fenstergeometrie & Instanz-Zustand).
- EventBus (Invariante 5): Profilwechsel + Favoriten-Aenderungen.
"""

from typing import Any, Dict, List, Optional

from PySide6.QtCore import QTimer, Qt, Slot
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_view_model import AnalyticsViewModel
from analytics.engine.analytics_worker import QUERY_TABLE
from analytics.engine.feature_store_reader import FeatureStoreReader
from chart.widgets.mtf_filter_bar import MtfFilterBarWidget
from analytics.engine.service_selector_model import ServiceSelectorModel
from analytics.ui.table_page import TablePage
from analytics.ui.heatmap_page import HeatmapPage
from analytics.ui.scatter_page import ScatterPage
from analytics.ui.distribution_page import DistributionPage
from analytics.ui.equity_page import EquityPage
from persistent_win import PersistentWindow, register_persistent_window
from state_manager import StateManager
from symbol_repository import SymbolRepository, get_symbol_repository
from config.event_bus import event_bus
from serviceui.common_widgets import TfStatusBadgeBar
from serviceui.service_selector_dialog import ServiceSelectorDialog
from serviceui.symbols_win import SymbolsWindow

# Im AnalyticsWindow angebotene Timeframes (Feature-Store-Auswahl).
# 15.03-Fix: ALLE MT5-Timeframes werden angeboten (der Feature-Store haelt
# z. B. fuer SILVER Daten in M1, M2, M5, M10, M15, M30, H1, H4, D1, W1, MN1).
# Timeframes ohne Feature-Store-Daten werden in der Combo ausgegraut
# (_refresh_timeframe_combo) und sind nicht auswaehlbar.
TIMEFRAMES = ["M1", "M2", "M5", "M10", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]

# 21.03.12 (MTF-FC auf Analytics): TF-Listen des MtfFilterBarWidget –
# 11 Analytics-Timeframes (M1..MN1) statt der 6 Chart-Defaults. `data_tf`
# (Analysequelle: Multi oder fixierter TF) und `agg_tf` (Aggregations-TF,
# Entscheidung 6a: Auto oder fixierter TF) sind unabhaengige Dropdowns.
MTF_DATA_TF_OPTIONS = ["🌐 Multi"] + [f"🔒 {tf}" for tf in TIMEFRAMES]
MTF_AGG_TF_OPTIONS = ["⚡ Auto"] + [f"🔒 {tf}" for tf in TIMEFRAMES]

# Fenstertitel (Option B: '*' = ungespeicherte Parametertrends).
WINDOW_TITLE_BASE = "PyTrader - Analytics"


def migrate_statistics_persistence(
    state_manager: Optional[StateManager] = None,
) -> bool:
    """E-2: Migriert Fenstergeometrie & Instanz-Zustand von win_statistics.

    Wird beim Oeffnen des AnalyticsWindow EINMALIG ausgefuehrt (idempotent):
    - Geometrie (window_instances) wird nach win_analytics kopiert (nur wenn
      dort noch kein Eintrag existiert).
    - Instanz-Zustand (instance_states: symbol/timeframe) wird kopiert.
    - Die Alt-Eintraege win_statistics werden entfernt (statistic_win ist
      durch AnalyticsWindow ersetzt).

    Hinweis (15.03): Die Fensterzustands-Persistenz wird laut Entscheidung
    E-2 in 15.04 in `window_state_repository.py` gekapselt; bis dahin nutzt
    die Migration direkt das StateManager-Persistence-Interface.

    Returns:
        True, wenn Daten von win_statistics uebernommen wurden.
    """
    sm = state_manager or StateManager()
    geom = sm.get_window_geometry("win_statistics")
    if geom is None:
        return False
    migrated = False

    # 1. Geometrie kopieren (nur wenn win_analytics noch keinen Eintrag hat)
    if sm.get_window_geometry("win_analytics") is None:
        sm.save_window_geometry(
            "win_analytics",
            geom.get("pos_x"),
            geom.get("pos_y"),
            geom.get("width"),
            geom.get("height"),
            bool(geom.get("is_maximized")),
        )
        migrated = True

    # 2. Instanz-Zustand kopieren (symbol/timeframe)
    all_inst = sm.load_all_instances()
    stats_inst = next(
        (i for i in all_inst if i.get("instance_id") == "win_statistics"), None
    )
    if stats_inst and stats_inst.get("symbol"):
        ana_inst = next(
            (i for i in all_inst if i.get("instance_id") == "win_analytics"),
            None,
        )
        if not (ana_inst and ana_inst.get("symbol")):
            sm.save_instance_state(
                "win_analytics",
                stats_inst["symbol"],
                stats_inst.get("timeframe") or "H1",
            )
            migrated = True

    # 3. Alt-Eintraege entfernen (statistic_win ist ersetzt)
    try:
        sm.delete_instance("win_statistics")
    except Exception:
        pass
    return migrated


def _params_signature(params: Dict[str, Any]) -> tuple:
    """Deterministische, hashbare Signatur der VM-Params (Runde 11, A6).

    Wird fuer die Query-Key-Pruefung in _on_page_changed genutzt: identische
    Seite + gleiche Restore-Generation + gleiche Params -> kein redundanter
    Re-Query (die Daten sind bereits frisch). Dicts/Listen werden rekursiv
    in sortierte Tupel normalisiert (deterministisch, hashbar).
    """

    def _norm(v: Any) -> Any:
        if isinstance(v, dict):
            return tuple(sorted((str(k), _norm(val))
                                for k, val in v.items()))
        if isinstance(v, (list, tuple)):
            return tuple(_norm(x) for x in v)
        return v

    return tuple(sorted((str(k), _norm(v))
                        for k, v in params.items()))


@register_persistent_window()
class AnalyticsWindow(PersistentWindow):
    """Analytics-Hauptfenster (win_analytics, 1280 x 800, nicht-modal)."""

    INSTANCE_ID = "win_analytics"
    # Bugfix 04.08.2026 (Fenster-Historie): auto_restore=True – das Fenster
    # wird beim App-Start wiederhergestellt, wenn es beim Beenden der App
    # OFFEN war.
    # 11.08.2026 (Bugfix Runde 17e, User-Meldung 2): _keep_history_on_close
    # jetzt False – ein MANUELL geschlossenes Analytics-Fenster wird aus
    # der Fenster-Historie entfernt (delete_instance) und beim naechsten
    # App-Start NICHT wiederhergestellt (Historie intakt, konsistent mit
    # ServiceWindow). Der Analytics-Workspace (vm.params + Layout)
    # ueberlebt das manuelle Schliessen ueber ein global_settings-Backup
    # ("analytics_workspace") und wird beim naechsten manuellen Oeffnen
    # wiederhergestellt (siehe _save_workspace/_restore_workspace); die
    # Fenster-Position ueberlebt ueber DIALOG_GEOMETRY_KEY (Muster
    # ServiceWindow).
    _keep_history_on_close = False
    #: Geometrie-Key fuer die POSITION, die ein manuelles Schliessen
    #: ueberlebt (global_settings, vgl. ServiceWindow-Muster).
    DIALOG_GEOMETRY_KEY = "win_analytics"

    def __init__(
        self,
        parent=None,
        view_model: Optional[AnalyticsViewModel] = None,
        analytics_repo: Any = None,
        profile_repo: Any = None,
        selector_model: Optional[ServiceSelectorModel] = None,
    ) -> None:
        super().__init__(parent)
        # 20.01 (E5): Das ServiceSelectorModel wird VOR dem ViewModel erzeugt
        # und injiziert – der VM nutzt es fuer den Fault-Tolerant-Resolver
        # (resolve_valid_feature_ids) beim Profil-/Workspace-Restore.
        self._selector_model: ServiceSelectorModel = (
            selector_model or ServiceSelectorModel(parent=self))
        self._vm = view_model or AnalyticsViewModel(
            analytics_repo=analytics_repo,
            profile_repo=profile_repo,
            selector_model=self._selector_model,
            parent=self,
        )
        self._symbol_repo: SymbolRepository = get_symbol_repository()
        self._profile_combo_syncing: bool = False
        # 06.08.2026 (Punkt 5): Default-Limit = 'Statistik-Signale' aus den
        # App-Optionen (AppSettings.statistics_signal_limit). Das Limit-Feld
        # ist seitdem ein reines Textfeld (keine Up/Down-Pfeile).
        try:
            _app_settings = self.state_manager.get_app_settings()
            self._default_limit: int = int(
                getattr(_app_settings, "statistics_signal_limit", 10_000))
            # 19.04 (Paging): Zeilen pro Seite aus den App-Optionen
            # (statistics_page_size, Default 100) – wird an die TablePage
            # injiziert (set_page_size), die die geladenen Rows seitenweise
            # rendert (Muster statistic_win.py).
            self._table_page_size: int = int(
                getattr(_app_settings, "statistics_page_size", 100))
        except Exception:
            self._default_limit = 10_000
            self._table_page_size = 100

        # 15.03-E: Datenquellen-Dialog (ServiceSelectorDialog, Multi-Select)
        # ersetzt das fruehere Service-Filter-Popover. Das
        # ServiceSelectorModel ist injizierbar (Headless-Tests); der Dialog
        # wird lazy erzeugt (nicht-modal) und beim Schliessen zerstört.
        self._service_dialog: Optional[ServiceSelectorDialog] = None
        #: Anzeigenamen des aktiven Datenquellen-Filters (fuer den Button).
        #: Beim Profilwechsel zurueckgesetzt – Namen werden dann aus den
        #: persistierten feature_ids ueber das Model re-resolved.
        self._active_display_names: List[str] = []

        self.setWindowTitle(WINDOW_TITLE_BASE)
        self.resize(1280, 800)

        # E-2: win_statistics-Persistenz migrieren – VOR restore_state(),
        # damit die wiederhergestellte Geometrie die migrierten Werte nutzt.
        try:
            migrate_statistics_persistence(self.state_manager)
        except Exception as e:
            print(f"WARN [AnalyticsWindow] E-2-Migration fehlgeschlagen: {e}")

        self._build_ui()
        self._wire_view_model()
        self._wire_controls()

        # State asynchron wiederherstellen (nach show(), damit move/resize
        # vom Window-Manager akzeptiert werden – Muster StatisticWindow).
        QTimer.singleShot(0, self.restore_state)
        # Initiale Daten + Profile laden.
        QTimer.singleShot(100, self._initial_load)

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # --- Top-Bar: Profil-CRUD (Option B – Explicit Save) ---
        # 21.01 (E5, 11.08.2026): combo_profile dehnbar (Expanding,
        # min. 560 px - User-Meldung 1, editierbar); Namens-/Beschreibungs-
        # Felder wandern in den separaten Speicher-Dialog (_on_profile_save)
        # bzw. breiten Neu-Dialog (_on_profile_new). label_dirty + Buttons
        # streng rechtsbuendig (addStretch davor).
        top = QHBoxLayout()
        self.combo_profile = QComboBox()
        self.combo_profile.setMinimumWidth(560)
        self.combo_profile.setEditable(True)
        self.combo_profile.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_profile_new = QPushButton("➕ Neu")
        self.btn_profile_save = QPushButton("💾 Speichern")
        self.btn_profile_delete = QPushButton("🗑️ Löschen")
        self.label_dirty = QLabel("")
        self.label_dirty.setStyleSheet("color: #e65100; font-weight: bold;")
        self.progress_busy = QProgressBar()
        self.progress_busy.setRange(0, 0)  # indeterminierter Spinner
        self.progress_busy.setFixedWidth(120)
        self.progress_busy.setVisible(False)

        top.addWidget(QLabel("Profil:"))
        top.addWidget(self.combo_profile, 1)
        top.addStretch(1)
        top.addWidget(self.label_dirty)
        top.addWidget(self.btn_profile_new)
        top.addWidget(self.btn_profile_save)
        top.addWidget(self.btn_profile_delete)
        top.addWidget(self.progress_busy)
        root.addLayout(top)

        # --- Filter-Zeile: Symbol / TF / Datenquellen (Multi-Select) / Limit ---
        # 15.03-E: Der Datenquellen-Button oeffnet den ServiceSelectorDialog
        # (Multi-Select, Checkbox-MasterTree) – ersetzt das alte
        # combo_feature-Dropdown UND das Service-Filter-Popover
        # (Entscheidung 06.08.2026).
        filt = QHBoxLayout()
        self.combo_symbol = QComboBox()
        self.btn_symbol_fav = QPushButton("★")
        self.btn_symbol_fav.setFixedWidth(32)
        self.btn_symbol_fav.setToolTip(
            "Favoriten verwalten – öffnet das Symbol-Fenster.")
        self.combo_tf = QComboBox()
        for tf in TIMEFRAMES:
            self.combo_tf.addItem(tf, tf)
        self.btn_data_sources = QPushButton(
            "[ 🛠️ Datenquellen: Keiner ausgewählt ▾ ]")
        self.btn_data_sources.setToolTip(
            "Datenquellen wählen – öffnet den Multi-Select-Dialog "
            "(Sets/Services/Plugins).")
        # 06.08.2026 (Punkt 5): Limit als reines TEXTFELD (keine Up/Down-
        # Pfeile). Default = 'Statistik-Signale' aus den App-Optionen
        # (statistics_signal_limit, siehe __init__).
        self.edit_limit = QLineEdit()
        self.edit_limit.setText(str(self._default_limit))
        self.edit_limit.setPlaceholderText("Signale")
        self.edit_limit.setMaximumWidth(120)
        self.edit_limit.setToolTip(
            "Maximale Signale für die Detail-Tabelle – Default aus den "
            "App-Optionen ('Statistik-Signale'). Nur Zahleneingabe.")

        filt.addWidget(QLabel("Symbol:"))
        filt.addWidget(self.combo_symbol)
        filt.addWidget(self.btn_symbol_fav)
        filt.addWidget(QLabel("Timeframe:"))
        filt.addWidget(self.combo_tf)
        filt.addWidget(QLabel("Datenquellen:"))
        filt.addWidget(self.btn_data_sources)
        # 21.01b (11.08.2026): Pill-Strip NEBEN der Datenquellen-Combo –
        # zeigt je Timeframe die feature_store-Belegung der ERSTEN aktiven
        # Datenquelle (fetch_service_tf_status); leer ohne Filter.
        self.badge_bar = TfStatusBadgeBar()
        filt.addWidget(self.badge_bar)
        filt.addWidget(QLabel("Limit:"))
        filt.addWidget(self.edit_limit)
        # 19.01 (Step 1): Status-Message direkt hinter dem Limit-Feld –
        # zeigt den Ergebnistext der Tabellen-Abfrage (total == 0 ->
        # "⚠️ Keine Daten vorhanden", sonst "✅ n Einträge"; E1). Dezent
        # orange, damit der Hinweis auffaellt, aber nicht stoert.
        self.label_status_msg = QLabel("")
        self.label_status_msg.setStyleSheet(
            "color: #b7950b; font-weight: bold;")
        filt.addWidget(self.label_status_msg)
        # 20.01 (Graceful Degradation): Warn-Hinweis bei nicht mehr
        # verfügbaren Services (fehlende plugin_ids im Profil/Workspace).
        self.label_missing_warning = QLabel("")
        self.label_missing_warning.setStyleSheet(
            "color: #c62828; font-weight: bold;")
        self.label_missing_warning.setVisible(False)
        filt.addWidget(self.label_missing_warning)
        filt.addStretch(1)
        root.addLayout(filt)

        # --- 21.03.12 (MTF-FC auf Analytics): Filterleiste des MtfFilterBarWidget ---
        # Data-TF (Analysequelle: Multi/fixiert), Agg-TF (Aggregations-TF,
        # Entscheidung 6a), Range-Picker, Sortierung + View-Templates.
        # now_provider = letzter Datenpunkt (MAX(bar_time)) statt time.time(),
        # damit Range-Presets relativ zum letzten Signal rechnen. Der
        # Chart-Modus wird auf '🔒 Fix' gesetzt, damit das Agg-TF-Dropdown
        # sofort aktiv ist (im Chart gated '⚡ Auto' das Agg-Dropdown).
        self.mtf_bar = MtfFilterBarWidget(
            data_tf_options=MTF_DATA_TF_OPTIONS,
            agg_tf_options=MTF_AGG_TF_OPTIONS,
            now_provider=self._vm.latest_data_epoch,
            parent=self,
        )
        self.mtf_bar.set_chart_mode("fix")
        root.addWidget(self.mtf_bar)

        # --- Body: Sidebar + Seiten (QStackedWidget) ---
        body = QHBoxLayout()
        # 10.08.2026 (Bugfix, UI-Splitter): Sidebar (links) und Seiten-Stack
        # (rechts) liegen in einem QSplitter - der Slider ist mit der Maus
        # frei verschiebbar (statt starrer 150px-Fixbreite + Stretch).
        self.sidebar = QListWidget()
        self.sidebar.setMinimumWidth(120)
        self.pages_stack = QStackedWidget()
        self.table_page = TablePage()
        self.heatmap_page = HeatmapPage()
        self.scatter_page = ScatterPage()
        self.distribution_page = DistributionPage()
        self.equity_page = EquityPage()
        for page in (self.table_page, self.heatmap_page, self.scatter_page,
                     self.distribution_page, self.equity_page):
            self.pages_stack.addWidget(page)
        for label in ("Tabelle", "Heatmap", "Scatter", "Verteilung", "Equity"):
            self.sidebar.addItem(QListWidgetItem(label))
        self.sidebar.setCurrentRow(0)

        self._body_splitter = QSplitter(Qt.Horizontal)
        self._body_splitter.addWidget(self.sidebar)
        self._body_splitter.addWidget(self.pages_stack)
        self._body_splitter.setStretchFactor(0, 0)
        self._body_splitter.setStretchFactor(1, 1)
        self._body_splitter.setCollapsible(0, False)
        self._body_splitter.setCollapsible(1, False)
        self._body_splitter.setSizes([150, 1200])
        body.addWidget(self._body_splitter, 1)
        root.addLayout(body, 1)

        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    # Datenquellen-Dialog (15.03-E / 18.01.01 E-4: ServiceSelectorDialog,
    # frei beweglicher Service-Picker waehrend der Analytics-Session)
    # ------------------------------------------------------------------
    @Slot()
    def _open_service_dialog(self) -> None:
        """Oeffnet den Service-Picker (nicht-modal, Singleton-Lazy).

        18.01.01 (E-4): Der Dialog ist KEIN Wegwerf-Popover mehr – er bleibt
        als Singleton erhalten (kein WA_DeleteOnClose) und kann waehrend der
        Analytics-Session frei beweglich platziert werden (Position wird
        ueber global_settings persistiert). Klick auf eine Baum-Zeile im
        Picker filtert LIVE (`selection_ids_requested` -> set_feature_ids),
        Services/Sets lassen sich dort direkt verwalten.
        """
        if self._service_dialog is None:
            self._service_dialog = ServiceSelectorDialog(
                model=self._selector_model, parent=self)
            self._service_dialog.services_selected.connect(
                self._on_services_selected)
            # 18.01.01 (E-4): Live-Filter bei Klick auf eine Baum-Zeile.
            self._service_dialog.selection_ids_requested.connect(
                self._on_picker_ids_selected)
            # Runde 10 (Bug 1): Varianten-Hashes -> VM (zusaetzlich zu
            # feature_ids; der Slot liest die aktuellen ids aus dem VM).
            self._service_dialog.selection_hashes_requested.connect(
                self._on_picker_hashes_selected)
            self._service_dialog.destroyed.connect(
                self._on_service_dialog_destroyed)
        # Runde 9 (Bug 1): Modell explizit refreshen, damit der Baum
        # sicher aufgebaut ist - das initiale data_changed des Modells
        # lief VOR der Dialog-Erstellung (Dialog ist lazy), ein leerer
        # Baum wuerde die restaurierten Haken sonst verlieren. Der
        # MasterTree faengt ein zwischenzeitlich leeres Set ueber
        # _pending_feature_ids ab (set_checked_feature_ids merkt sie).
        try:
            self._selector_model.refresh()
        except Exception as e:
            print(f"WARN [AnalyticsWindow] Picker-Modell-Refresh: {e}")
        self._service_dialog.apply_feature_ids(
            self._vm.params.get("feature_ids") or [],
            self._vm.params.get("instance_hashes") or [])
        self._service_dialog.show()
        self._service_dialog.raise_()
        self._service_dialog.activateWindow()

    @Slot()
    def _on_service_dialog_destroyed(self) -> None:
        """Setzt die Dialog-Referenz zurueck (zerstoert mit dem Parent)."""
        self._service_dialog = None

    @Slot(list)
    def _on_picker_hashes_selected(self, instance_hashes: List[str]) -> None:
        """Runde 10 (Bug 1): Varianten-Hashes aus dem Picker uebernehmen.

        feature_ids (plugin_ids) bleiben unveraendert - nur die
        Varianten-Einschraenkung wird aktualisiert. Dadurch ist ein
        Check/Uncheck EINER Variante im Datenfilter sichtbar.
        """
        self._vm.set_feature_ids(
            self._vm.params.get("feature_ids") or [],
            list(instance_hashes or []))
        self._sync_service_filter_button()
        self.label_missing_warning.setVisible(False)

    @Slot(list)
    def _on_picker_ids_selected(self, feature_ids: List[str]) -> None:
        """Live-Filter aus dem Picker (Klick auf Set/Ordner/Plugin).

        18.01.01 (E-4): Die aufgeloesten feature_ids (plugin_ids) werden
        sofort an `AnalyticsViewModel.set_feature_ids()` gereicht – die
        Charts filtern ohne 'Anwenden'. Der Button-Text wird synchronisiert
        (Anzeigenamen ueber das Modell re-resolved).
        """
        self._active_display_names = []
        self._vm.set_feature_ids(list(feature_ids or []))
        self._sync_service_filter_button()
        # 20.01: Manuelle Datenquellen-Aenderung -> Warn-Label zuruecksetzen.
        self.label_missing_warning.setVisible(False)

    @Slot(list, list)
    def _on_services_selected(
        self, display_names: List[str], feature_ids: List[str]
    ) -> None:
        """Uebernimmt die Multi-Auswahl aus dem Dialog (Signal-Vertrag).

        `display_names` werden fuer den Button-Text gemerkt; `feature_ids`
        (plugin_ids) gehen an `AnalyticsViewModel.set_feature_ids()` – das
        ViewModel filtert die Charts per `WHERE feature_id IN (...)`.
        """
        self._active_display_names = list(display_names or [])
        self._vm.set_feature_ids(list(feature_ids or []))
        self._sync_service_filter_button()
        # 20.01: Manuelle Datenquellen-Aenderung -> Warn-Label zuruecksetzen.
        self.label_missing_warning.setVisible(False)

    def _sync_service_filter_button(self) -> None:
        """Synchronisiert den Datenquellen-Button mit dem VM-Parameter.

        Wird beim Setzen/Entfernen des Filters, bei Profilwechseln
        (active_profile_changed) und ueber `event_bus.profile_changed`
        aufgerufen. Nach einem Profilwechsel liegen nur die persistierten
        feature_ids (plugin_ids) vor – die Anzeigenamen werden dann ueber
        `ServiceSelectorModel.resolve_display_names()` re-resolved.
        """
        ids = self._vm.params.get("feature_ids") or []
        if not ids:
            self.btn_data_sources.setText(
                "[ 🛠️ Datenquellen: Keiner ausgewählt ▾ ]")
            self._refresh_badge_bar()
            return
        names = (self._active_display_names
                 or self._selector_model.resolve_display_names(ids))
        self.btn_data_sources.setText(
            f"[ 🛠️ Datenquellen: {', '.join(names)} ▾ ]")
        self._refresh_badge_bar()

    def _refresh_badge_bar(self) -> None:
        """21.01b: Pill-Strip fuer die ERSTE aktive Datenquelle laden.

        Quelle: FeatureStoreReader.fetch_service_tf_status() – je Timeframe
        die Anzahl der feature_store-Eintraege und der letzte Lauf.
        """
        bar = getattr(self, "badge_bar", None)
        if bar is None:
            return
        ids = (self._vm.params.get("feature_ids") or [])
        pid = str(ids[0]) if ids else ""
        if not pid:
            bar.clear()
            return
        try:
            status = FeatureStoreReader().fetch_service_tf_status(pid)
        except Exception:
            status = {}
        bar.update_status(status)

    @Slot()
    def _sync_ui_from_restored_params(self) -> None:
        """Synchronisiert die Fenster-UI nach `params_restored`.

        10.08.2026 (Bugfix, Punkt 3): `params_restored` feuert nach einem
        Workspace-Restore UND nach einem Profilwechsel (_apply_profile).
        Hier wird die Fenster-Ebene nachgezogen: Sidebar-Seite (sofern der
        Workspace eine page_index hat), die aktuelle Page (falls sie eine
        _sync_from_params-Methode anbietet) und die Filterleiste
        (Symbol/Timeframe/Datenquellen-Button). Die Unterseiten syncen ihre
        Combos ueber eigene params_restored-Verbindungen.
        """
        try:
            page_index = int((self._vm.workspace_layout or {}).get(
                "page_index", -1))
            if 0 <= page_index < self.pages_stack.count():
                if self.sidebar.currentRow() != page_index:
                    self.sidebar.blockSignals(True)
                    self.sidebar.setCurrentRow(page_index)
                    self.sidebar.blockSignals(False)
                # 10.08.2026 (Punkt 4): Seiten-Stack EXPLIZIT umschalten
                # (blockSignals unterdrueckt currentRowChanged -> _on_page_
                # changed feuert nicht; ohne setCurrentIndex bleibt die
                # alte Seite sichtbar).
                self.pages_stack.setCurrentIndex(page_index)
        except (RuntimeError, AttributeError):
            pass
        # Runde 11 (Architektur, A3/A6): Zentraler Seiten-Sync NACH dem
        # VM-Param-Setzen (genau EIN Durchgang; die Einzel-Verbindungen der
        # Widgets auf params_restored entfallen). Danach die Daten der
        # aktiven Seite anfordern (A6: Query-Key-Pruefung -> request_data).
        self._sync_all_pages_from_params()
        self._request_current_page_data()
        # 10.08.2026 (Punkt 3): Ansichts-Modus der Heatmap-Seite auch aus
        # dem Profil-Restore uebernehmen (workspace_layout wird von
        # _apply_profile befuellt). Muster _restore_workspace.
        try:
            heatmap_mode = (self._vm.workspace_layout or {}).get(
                "heatmap_mode")
            if heatmap_mode:
                self.heatmap_page.set_mode(str(heatmap_mode))
        except Exception as e:
            print(f"WARN [AnalyticsWindow] Heatmap-Modus-Restore: {e}")
        # 10.08.2026 (Bugfix Runde 7, Bug 2): ServicePicker nach einem
        # Profilwechsel wieder oeffnen, falls das Layout es verlangt.
        try:
            if (self._vm.workspace_layout or {}).get("service_picker_open"):
                self._open_service_dialog()
        except Exception as e:
            print(f"WARN [AnalyticsWindow] ServicePicker-Restore: {e}")
        self._sync_profile_filters()
        self._sync_service_filter_button()
        # 21.03.12 (MTF-FC auf Analytics): Filterleisten-Zustand nach einem
        # Profil-/Workspace-Restore synchronisieren (data_tf/agg_tf/Range).
        self._sync_mtf_bar_from_params()

    # ------------------------------------------------------------------
    # MVVM + Steuerung verdrahten
    # ------------------------------------------------------------------
    def _wire_view_model(self) -> None:
        vm = self._vm
        for page in (self.table_page, self.heatmap_page, self.scatter_page,
                     self.distribution_page, self.equity_page):
            page.attach_view_model(vm)
        vm.profiles_available.connect(self._on_profiles_available)
        vm.active_profile_changed.connect(self._on_active_profile_changed)
        vm.dirty_changed.connect(self._on_dirty_changed)
        # 10.08.2026 (Bugfix, Punkt 3): Der ViewModel emittiert
        # params_restored nach restore_workspace() UND _apply_profile()
        # (20.04-Timing-Fix) - die Fenster-Ebene wird synchronisiert
        # (Sidebar-Seite + aktuelle Page + Filterleiste). Die Unterseiten
        # (Heatmap-Widget) syncen ihre Combos ueber eigene Verbindungen.
        if hasattr(vm, "params_restored"):
            vm.params_restored.connect(self._sync_ui_from_restored_params)
        vm.busy_changed.connect(self._on_busy_changed)
        vm.query_failed.connect(self._on_query_failed)
        # 20.01 (Graceful Degradation): fehlende Services -> Warn-Label.
        vm.missing_services_detected.connect(self._on_missing_services)
        # 19.01 (Step 1): Status-Text bei Tabellen-Abfragen (total == 0 ->
        # "Keine Daten vorhanden", E1). Nur QUERY_TABLE wird ausgewertet.
        vm.data_ready.connect(self._on_data_ready)
        # 19.01 (E3): Service-Namensaufloesung fuer die TablePage (IoC) –
        # kein SQL / keine direkte Modell-Kopplung in der Page.
        self.table_page.set_name_resolver(
            self._selector_model.resolve_display_names)
        # 19.03 (Step 1): Tabellen-Settings (Spaltenbreiten, Zeilenhoehe,
        # Sortierung) der TablePage in den ViewModel leiten (Persistenz,
        # Option B – Explicit Save; E6: kein Query-Refresh).
        self.table_page.table_settings_changed.connect(
            self._on_table_settings_changed)

        # 19.04 (Paging): Zeilen pro Seite aus den AppSettings injizieren
        # (statistics_page_size). Die TablePage rendert nur Seiten der
        # Groesse page_size; die geladenen _current_rows (bis zum Limit)
        # bleiben vollstaendig erhalten (Jump-to-Chart/Seitenwechsel).
        self.table_page.set_page_size(self._table_page_size)

        # Jump-to-Chart (Variante 2): open_chart_at_bar + Aufloesung
        self.table_page.set_navigation_handler(self._open_chart_at_bar)
        self.heatmap_page.set_navigation_handler(self._open_chart_at_bar)
        self.heatmap_page.set_cell_resolver(
            self._vm.resolve_recent_bar_time_for_cell)
        self.scatter_page.set_navigation_handler(self._open_chart_at_bar)
        self.scatter_page.set_bar_resolver(self._vm.resolve_latest_bar_time)

    def _wire_controls(self) -> None:
        self.combo_symbol.currentTextChanged.connect(self._vm.set_symbol)
        # TF-Ausgrauung (15.03-Fix): Bei Symbolwechsel die verfuegbaren
        # Timeframes aus dem Feature-Store ermitteln und TFs ohne Daten
        # ausgrauen (nicht auswaehlbar).
        self.combo_symbol.currentTextChanged.connect(self._refresh_timeframe_combo)
        self.combo_tf.currentTextChanged.connect(self._vm.set_timeframe)
        # 15.03-E: Datenquellen-Dialog (Multi-Select, ersetzt Popover)
        self.btn_data_sources.clicked.connect(self._open_service_dialog)
        event_bus.profile_changed.connect(self._sync_service_filter_button)
        # 21.03.11 (Bug 3): Nach abgeschlossenem Service-Run (der Worker
        # emittiert `service_set_changed` einmalig nach der ALLE-TFs-/
        # Einzel-Ausfuehrung) das Analytics-Hauptfenster (Heatmap/Tabelle)
        # automatisch neu laden. `refresh_all` ist im VM debounced.
        event_bus.service_set_changed.connect(self._on_service_set_changed)
        # 21.03.11/12 (MTF-FC): Sortier-Aenderung der Filterleiste (Analytics)
        # an die TablePage weiterreichen (Entkopplung via EventBus, IoC).
        event_bus.mtf_fc_sort_changed.connect(self._on_mtf_fc_sort_changed)
        # 21.03.12 (MTF-FC auf Analytics): MtfFilterBarWidget-Signale -> VM.
        self.mtf_bar.data_tf_changed.connect(self._on_mtf_data_tf_changed)
        self.mtf_bar.agg_tf_changed.connect(self._vm.set_agg_tf)
        self.mtf_bar.range_changed.connect(self._on_mtf_range_changed)
        # 21.03.14 (Wunsch 2): Sortier-Aenderung an den ViewModel
        # (Profil-Persistenz, Sektion sources) UND ueber den bestehenden
        # EventBus an die TablePage (set_external_sort_mode, IoC).
        self.mtf_bar.sort_mode_changed.connect(self._vm.set_sort_mode)
        self.mtf_bar.sort_mode_changed.connect(
            event_bus.mtf_fc_sort_changed.emit)
        # Filterleisten-Zustand aus den VM-Params initial synchronisieren
        # (data_tf='multi', agg_tf='auto', Range aus Profil/Workspace).
        self._sync_mtf_bar_from_params()

    @Slot()
    def _on_service_set_changed(self) -> None:
        """21.03.11 (Bug 3): Nach abgeschlossenem Service-Run neu laden.

        Der `ServiceRunWorker` emittiert `event_bus.service_set_changed`
        genau einmal nach Abschluss der Ausfuehrung (auch bei Teilerfolg).
        `refresh_all()` ist im ViewModel debounced (kein SQL-Feuer) und
        stösst die aktiven Seiten-Queries (Tabelle/Heatmap) neu an.
        """
        if getattr(self, "_vm", None) is None:
            return
        try:
            self._vm.refresh_all()
        except Exception as e:
            print(f"WARN [AnalyticsWindow] service_set_changed-Refresh: {e}")

    @Slot(str)
    def _on_mtf_fc_sort_changed(self, mode: str) -> None:
        """21.03.11/12 (MTF-FC): Sortier-Aenderung auf die TablePage anwenden.

        Die MTF-FC-Filterleiste (AnalyticsWindow) emittiert
        `event_bus.mtf_fc_sort_changed` ('date' | 'signal' | 'tf'). Die
        TablePage setzt daraufhin ihre Anzeige-Sortierung entsprechend
        (IoC, kein Fenster-Know-how).
        """
        if getattr(self, "table_page", None) is None:
            return
        try:
            self.table_page.set_external_sort_mode(str(mode))
        except Exception as e:
            print(f"WARN [AnalyticsWindow] MTF-FC-Sortierung: {e}")

    @Slot(str)
    def _on_mtf_data_tf_changed(self, data_tf: str) -> None:
        """21.03.12: Analysequelle des MtfFilterBarWidget uebernehmen.

        `set_data_tf` setzt bei fixiertem TF auch den `timeframe`-Filter
        (Analysequelle = Analyse-TF) - die Timeframe-Combo wird dann
        synchronisiert (Muster set_data_tf-Docstring).
        """
        self._vm.set_data_tf(str(data_tf))
        if str(data_tf).strip().lower() != "multi":
            self._sync_profile_filters()

    @Slot(str, int, int)
    def _on_mtf_range_changed(self, preset: str, from_ts: int, to_ts: int) -> None:
        """21.03.12: Zeitraum-Preset des MtfFilterBarWidget uebernehmen."""
        self._vm.set_range(int(from_ts), int(to_ts), str(preset))

    def _sync_mtf_bar_from_params(self) -> None:
        """Synchronisiert die MTF-FC-Filterleiste aus den VM-Params.

        Wird nach Profil-/Workspace-Restore (params_restored) und initial
        nach _wire_controls gerufen. `apply_external_state` setzt die Combos
        mit blockSignals und emittiert die Aenderungs-Signale danach explizit
        (der VM dedupliziert gleiche Werte, kein Doppel-Refresh).
        """
        bar = getattr(self, "mtf_bar", None)
        if bar is None:
            return
        p = self._vm.params
        try:
            # 21.03.14 (Wunsch 2): sort_mode stellt die Tabellen-Sortierung
            # wieder her. 21.03.15 (Bug 3): range_preset wird auf den neuen
            # Preset-Satz abgebildet (Alt-Werte 'YTD'/'Benutzerdefiniert'
            # migriert die Filterleiste selbst); range_from/range_to (Custom-
            # Panel) sind seit 21.03.15 entfallen.
            bar.apply_external_state(
                data_tf=str(p.get("data_tf") or "multi"),
                agg_tf=str(p.get("agg_tf") or "auto"),
                range_preset=p.get("range_preset"),
                sort_mode=p.get("sort_mode"),
            )
        except (RuntimeError, AttributeError):
            pass

    @Slot(str)
    def _on_limit_text_changed(self, text: str) -> None:
        """Uebernimmt die Limit-Texteingabe (Punkt 5, reines Textfeld).

        Nur ganzzahlige Werte werden an das ViewModel gereicht (das clamt
        auf 1..MAX_LOOKBACK_LIMIT); leere oder ungueltige Eingaben lassen den
        letzten gueltigen Wert unveraendert.
        """
        text = (text or "").strip()
        if not text:
            return
        try:
            val = int(text)
        except ValueError:
            return
        self._vm.set_limit(val)

    def _refresh_timeframe_combo(self, symbol: Optional[str] = None) -> None:
        """Graut Timeframes ohne Feature-Store-Daten aus (nicht auswaehlbar).

        Fix 15.03 (TF-Verfuegbarkeit): TFs mit Daten bleiben aktiv; TFs ohne
        Daten werden per QComboBox-Model disabled (Qt stellt sie grau dar und
        verhindert die Auswahl). Die aktuelle Auswahl wird nur beibehalten,
        wenn ihr TF Daten hat; sonst faellt sie auf den ersten verfuegbaren TF
        zurueck. Schlaegt die Abfrage fehl, bleiben alle TFs aktiv (Fallback).
        """
        if not hasattr(self, "combo_tf") or not hasattr(self, "combo_symbol"):
            return
        symbol = (symbol or self.combo_symbol.currentText()).strip()
        available: Optional[set] = None  # None = Abfrage fehlgeschlagen
        if symbol:
            try:
                tfs = self._vm.available_timeframes(symbol)
                available = {str(t) for t in tfs}
            except Exception:
                available = None
        self.combo_tf.blockSignals(True)
        first_enabled = -1
        for i in range(self.combo_tf.count()):
            tf = self.combo_tf.itemText(i)
            enabled = (available is None) or (tf in available)
            self.combo_tf.model().item(i).setEnabled(enabled)
            if enabled and first_enabled < 0:
                first_enabled = i
        current = self.combo_tf.currentText()
        cur_idx = self.combo_tf.findText(current)
        if cur_idx >= 0 and self.combo_tf.model().item(cur_idx).isEnabled():
            pass  # aktuelle Auswahl hat Daten -> behalten
        elif first_enabled >= 0:
            self.combo_tf.setCurrentIndex(first_enabled)
        self.combo_tf.blockSignals(False)

    # ------------------------------------------------------------------
    # PersistentWindow-Interface
    # ------------------------------------------------------------------
    def get_persistent_symbol(self) -> str:
        return (self.combo_symbol.currentText()
                if hasattr(self, "combo_symbol") else "SILVER")

    def get_persistent_timeframe(self) -> str:
        return (self.combo_tf.currentText()
                if hasattr(self, "combo_tf") else "M1")

    def _apply_persistent_filters(self, symbol: str, timeframe: str) -> None:
        """Wird von PersistentWindow.restore_state() gerufen."""
        if symbol and hasattr(self, "combo_symbol"):
            idx = self.combo_symbol.findText(symbol)
            if idx < 0:
                # Nicht-Favorit aus der Historie: in die Combo aufnehmen,
                # damit der gespeicherte Filter wiederhergestellt wird
                # (Fix 15.03 – zuletzt gewaehltes Symbol bleibt gemerkt).
                self.combo_symbol.blockSignals(True)
                self.combo_symbol.addItem(symbol, symbol)
                idx = self.combo_symbol.count() - 1
                self.combo_symbol.blockSignals(False)
            self.combo_symbol.setCurrentIndex(idx)
        if timeframe and hasattr(self, "combo_tf"):
            idx = self.combo_tf.findText(timeframe)
            if idx >= 0:
                self.combo_tf.setCurrentIndex(idx)
        # VM-Parameter idempotent uebernehmen (setCurrentIndex hat die
        # Signale bereits gefeuert; der ViewModel dedupliziert gleiche Werte).
        self._vm.set_symbol(self.get_persistent_symbol())
        self._vm.set_timeframe(self.get_persistent_timeframe())
        # TF-Ausgrauung nach Restore: Fall der aktuelle TF keine Daten hat,
        # faellt die Auswahl auf den ersten verfuegbaren TF zurueck.
        self._refresh_timeframe_combo(symbol)

    # ------------------------------------------------------------------
    # Symbol- & Favoriten-Verwaltung (15.01-Muster)
    # ------------------------------------------------------------------
    @Slot()
    def open_symbols_window(self) -> None:
        """Oeffnet das nicht-modale SymbolsWindow (Singleton-Verhalten)."""
        existing = SymbolsWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = SymbolsWindow(self)  # parent=self nur fuer state_manager-Zugriff
        win.show()

    def _refresh_symbol_combo(self) -> None:
        """Befuellt die Symbol-ComboBox aus den Favoriten (Fallback Defaults).

        Die aktuell gewaehlte Auswahl bleibt erhalten – auch wenn sie kein
        Favorit (mehr) ist (analog StatisticWindow) – damit der Filter nicht
        ungewollt umspringt und ein aus der Historie restauriertes Symbol
        sichtbar bleibt (Fix 15.03).
        """
        if not hasattr(self, "combo_symbol"):
            return
        favorites = self._symbol_repo.get_favorite_symbols()
        if not favorites:
            favorites = list(SymbolRepository.DEFAULT_SYMBOLS)
        current = self.combo_symbol.currentText()
        self.combo_symbol.blockSignals(True)
        self.combo_symbol.clear()
        for sym in favorites:
            self.combo_symbol.addItem(sym, sym)
        if current and current not in favorites:
            self.combo_symbol.addItem(current, current)
        idx = self.combo_symbol.findText(current)
        self.combo_symbol.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_symbol.blockSignals(False)

    # ------------------------------------------------------------------
    # Runde 11 (Architektur, A3/A6): Zentraler Seiten-Sync + Query-
    # Orchestrierung
    # ------------------------------------------------------------------
    def _sync_all_pages_from_params(self) -> None:
        """Synchronisiert ALLE Seiten-Controls aus den VM-Params (A3).

        Runde 11 (Architektur, A3): Zentraler Sync nach restore_workspace()/
        _apply_profile() - genau EIN Durchgang mit blockSignals (page-intern
        via _syncing/_set_combo_data). Die direkte params_restored-
        Verbindung des HeatmapWidgets (attach_view_model) entfaellt - das
        Window orchestriert hier.
        """
        for page in (self.table_page, self.heatmap_page, self.scatter_page,
                     self.distribution_page, self.equity_page):
            if hasattr(page, "_sync_from_params"):
                try:
                    page._sync_from_params()
                except (RuntimeError, AttributeError):
                    pass
        # 20.02: Das generische HeatmapWidget syncen seine Combos separat
        # (es ist ein Unter-Widget der HeatmapPage, keine eigene Page).
        try:
            generic = getattr(self.heatmap_page, "_generic", None)
            if generic is not None and hasattr(generic, "_sync_from_params"):
                generic._sync_from_params()
        except (RuntimeError, AttributeError):
            pass

    def _request_current_page_data(self) -> None:
        """Fordert die Daten der aktiven Seite an (A6: sync -> key -> query)."""
        row = self.sidebar.currentRow()
        if not (0 <= row < self.pages_stack.count()):
            return
        self._on_page_changed(row)

    # ------------------------------------------------------------------
    # Datenfluss (MVVM): Feature-Dropdown, Seiten, Status
    # ------------------------------------------------------------------
    def _on_page_changed(self, row: int) -> None:
        if 0 <= row < self.pages_stack.count():
            # Bugfix 08.08.2026: Seiten-Stack NIE umgeschaltet (Alt-Bug
            # seit Phase 15.03) - es fehlte setCurrentIndex. Dadurch blieb
            # unabhaengig vom Sidebar-Klick immer die Tabelle (Index 0)
            # sichtbar. Jetzt: Stack auf die geklickte Seite + lazy request.
            self.pages_stack.setCurrentIndex(row)
            page = self.pages_stack.widget(row)
            # Runde 11 (A6): Query-Key-Pruefung - identische Seite + gleiche
            # Restore-Generation + gleiche Params -> KEIN redundanter
            # Re-Query (die Daten sind bereits frisch; z. B. doppelter
            # Aufruf aus _initial_load/_request_current_page_data).
            key = (row, self._vm.restore_generation,
                   _params_signature(self._vm.params))
            if key != getattr(self, "_last_request_key", None):
                self._last_request_key = key
                if hasattr(page, "request_data"):
                    page.request_data()

    @Slot(str, str)
    def _on_query_failed(self, kind: str, error: str) -> None:
        print(f"WARN [AnalyticsWindow] Abfrage '{kind}' fehlgeschlagen: {error}")

    @Slot(list)
    def _on_missing_services(self, missing: List[str]) -> None:
        """Zeigt an, welche gespeicherten Services nicht mehr verfügbar sind.

        20.01 (Graceful Degradation): Fehlende feature_ids (entfernte/
        umbenannte Plugins) wurden beim Profil-/Workspace-Restore isoliert
        gefiltert – die verbliebenen Quellen bleiben aktiv. Das Label wird
        bei manueller Datenquellen-Aenderung oder save_profile() versteckt.
        """
        missing = [str(m) for m in missing or [] if str(m or "").strip()]
        if not missing:
            self.label_missing_warning.setVisible(False)
            return
        self.label_missing_warning.setText(
            f"⚠️ {len(missing)} Services nicht mehr verfügbar")
        self.label_missing_warning.setVisible(True)

    @Slot(str, dict)
    def _on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        """Status-Text der Tabellen-Abfrage (19.01 Step 1).

        Zeigt den Ergebnisstatus NUR fuer QUERY_TABLE (total aus dem
        Repository = LIMIT-gekappte Zeilenzahl, E1). total == 0 ->
        "Keine Daten vorhanden" (dezent orange), sonst "n Eintraege".
        Leere Zustaende der Unterseiten (Overlay-Stacks) schalten die
        Pages bereits selbst um (E5) – dieser Text ist ergaenzend.
        """
        if kind != QUERY_TABLE:
            return
        try:
            total = int(data.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        if total == 0:
            self.label_status_msg.setText("⚠️ Keine Daten vorhanden")
        else:
            self.label_status_msg.setText(f"✅ {total} Einträge")

    @Slot(dict)
    def _on_table_settings_changed(self, settings: Dict[str, Any]) -> None:
        """Uebernimmt TablePage-Settings in den ViewModel (19.03 Step 1/2).

        Spaltenbreiten {Spaltenname: Breite} (E5), **globale Zeilenhoehe**
        (E9/19.06: ein Wert fuer die GESAMTE Tabelle – das Ziehen einer
        Zeile setzt alle Zeilen live auf diese Hoehe), Sortier-Spalte/
        -Richtung (E8). Reine UI-Zustaende der TablePage: set_table_settings
        markiert nur das Profil-Dirty-Flag (E6, Option B) und loest KEINEN
        Query-Refresh aus (kein Debounce/Worker).
        """
        so = settings.get("sort_order")
        self._vm.set_table_settings(
            widths=settings.get("column_widths") or {},
            row_height=int(settings.get("row_height") or 0),
            sort_column=int(settings.get("sort_column") or 0),
            sort_order=int(so) if so is not None else 1,
        )

    @Slot(bool)
    def _on_busy_changed(self, busy: bool) -> None:
        self.progress_busy.setVisible(busy)

    # ------------------------------------------------------------------
    # Profil-CRUD (Option B – Explicit Save)
    # ------------------------------------------------------------------
    @Slot(list)
    def _on_profiles_available(self, profiles: List[Dict[str, Any]]) -> None:
        active_pid = next(
            (p.get("profile_id") for p in profiles if p.get("is_active")),
            None,
        )
        self._profile_combo_syncing = True
        self.combo_profile.blockSignals(True)
        self.combo_profile.clear()
        if not profiles:
            self.combo_profile.addItem("– kein Profil –", None)
        for p in profiles:
            self.combo_profile.addItem(
                p.get("name") or "?", p.get("profile_id"))
        target = active_pid or (self._vm.active_profile or {}).get("profile_id")
        idx = self.combo_profile.findData(target)
        self.combo_profile.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_profile.blockSignals(False)
        self._profile_combo_syncing = False

    @Slot(int)
    def _on_profile_selected(self, _index: int) -> None:
        if self._profile_combo_syncing:
            return
        profile_id = self.combo_profile.currentData()
        if profile_id:
            self._vm.set_active_profile(profile_id)

    @Slot(object)
    def _on_active_profile_changed(
        self, profile: Optional[Dict[str, Any]]
    ) -> None:
        # 21.01 (E5): Name-/Beschreibungs-Felder leben im Speicher-Dialog
        # (kein Header-Edit mehr) – hier nur noch die Combo + Filter-Sync.
        if profile is None:
            self._active_display_names = []
            self._sync_service_filter_button()
            return
        pid = profile.get("profile_id")
        idx = self.combo_profile.findData(pid)
        if idx >= 0 and self.combo_profile.currentIndex() != idx:
            self.combo_profile.blockSignals(True)
            self.combo_profile.setCurrentIndex(idx)
            self.combo_profile.blockSignals(False)
        # 15.03-E: Profilwechsel uebernimmt feature_ids in den VM – die
        # Anzeigenamen werden neu aus den persistierten IDs aufgeloest
        # (resolve_display_names) und der Button-Text synchronisiert.
        self._active_display_names = []
        self._sync_service_filter_button()
        # 06.08.2026 (Punkt 5): Limit-Feld mit dem (ggf. aus dem Profil
        # geladenen) VM-Wert synchronisieren.
        if hasattr(self, "edit_limit"):
            self.edit_limit.setText(
                str(int(self._vm.params.get("limit") or self._default_limit)))
        # Bugfix 08.08.2026 (symbol/tf-Profil-Restore): Der Profilwechsel
        # hat die VM-Parameter symbol/timeframe via _apply_profile() gesetzt –
        # die Combos muessen diesen Werten folgen (sonst zeigen sie weiter
        # die Historie-Werte und beim Schliessen wird der falsche Zustand
        # persistiert).
        self._sync_profile_filters()

    def _sync_profile_filters(self) -> None:
        """Synchronisiert Symbol-/TF-Combos mit den VM-Parametern (Bugfix).

        Beim Profilwechsel (active_profile_changed) bzw. nach load_profiles()
        wurden die VM-Parameter `symbol`/`timeframe` aus dem Profil-Payload
        uebernommen (ViewModel._apply_profile). Die Combos wuerden aber auf
        den alten (Historie-)Werten bleiben – das ergibt inkonsistente
        Abfragen und eine falsche Persistenz beim Schliessen
        (get_persistent_symbol liefert den Combo-Wert). Der Sync laeuft mit
        blockSignals(True), damit keine set_symbol/set_timeframe-Signalkette
        (und kein zusaetzlicher Query) ausgeloest wird – der Profilwechsel
        hat die Abfragen bereits via refresh_all() angestossen. Ein Symbol
        ausserhalb der Favoriten wird in die Combo aufgenommen (Muster
        _apply_persistent_filters), damit der gespeicherte Filter sichtbar
        bleibt.
        """
        if not hasattr(self, "combo_symbol") or not hasattr(self, "combo_tf"):
            return
        symbol = (self._vm.params.get("symbol") or "").strip()
        if not symbol:
            return
        self.combo_symbol.blockSignals(True)
        if self.combo_symbol.findText(symbol) < 0:
            self.combo_symbol.addItem(symbol, symbol)
        self.combo_symbol.setCurrentIndex(self.combo_symbol.findText(symbol))
        self.combo_symbol.blockSignals(False)
        timeframe = (self._vm.params.get("timeframe") or "M1").strip()
        self.combo_tf.blockSignals(True)
        idx = self.combo_tf.findText(timeframe)
        if idx >= 0:
            self.combo_tf.setCurrentIndex(idx)
        self.combo_tf.blockSignals(False)
        # TF-Ausgrauung fuer das (ggf. neue) Symbol aktualisieren.
        self._refresh_timeframe_combo(symbol)

    def _sync_profile_editor(self) -> None:
        """Synchronisiert das Limit-Feld mit dem VM (Bugfix).

        Wird beim App-Start nach `load_profiles()` gerufen: Dort emittiert der
        ViewModel KEIN `active_profile_changed` (nur set_active_profile/
        create_profile) – das Limit-Feld bliebe sonst auf dem Default, obwohl
        das aktive Profil einen abweichenden Wert haben kann.
        21.01 (E5): Die Namens-/Beschreibungs-Felder existieren nicht mehr im
        Header – Name/Beschreibung werden ausschliesslich im Speicher-Dialog
        editiert (dort mit den aktuellen Profilwerten vorbelegt).
        """
        if hasattr(self, "edit_limit"):
            self.edit_limit.setText(
                str(int(self._vm.params.get("limit")
                        or self._default_limit)))

    @staticmethod
    def _resolve_save_name(name: str, current_name: str) -> str:
        """Leerer Name beim Speichern -> aktueller Profilname (E5).

        21.01 (E5): Die Header-Namensfelder sind entfernt; der Speicher-
        Dialog wird mit dem aktuellen Profilnamen vorbelegt. Laesst der
        Anwender das Feld leer (bzw. nur Whitespace), bleibt der
        bestehende Profilname erhalten – kein '?'-Verlust in der Combo
        (Bugfix 19.05/19.06-Semantik, jetzt im Dialog statt Header-Feld).
        """
        return (str(name or "").strip()
                or str(current_name or "").strip() or "")

    @Slot(bool)
    def _on_dirty_changed(self, dirty: bool) -> None:
        self.label_dirty.setText(
            "● ungespeicherte Änderungen" if dirty else "")
        self.setWindowTitle(
            WINDOW_TITLE_BASE + (" *" if dirty else ""))

    def _current_ui_layout(self) -> Dict[str, Any]:
        """Aktuelles UI-Layout (Seite + Heatmap-Modus) fuer die
        Profil-Persistenz (10.08.2026, Punkte 3/4)."""
        return {
            "page_index": self.sidebar.currentRow()
            if hasattr(self, "sidebar") else 0,
            "heatmap_mode": self.heatmap_page.mode_id
            if hasattr(self, "heatmap_page") else "standard",
            # 10.08.2026 (Bugfix Runde 7, Bug 2): Picker-Offen-Zustand auch
            # im Profil-Payload persistieren (Muster _save_workspace).
            "service_picker_open": bool(
                self._service_dialog is not None
                and self._service_dialog.isVisible()),
        }

    @Slot()
    def _on_profile_new(self) -> None:
        # 21.01 (E3 + User-Meldung 1, 11.08.2026): Der Neu-Dialog ist ein
        # BREITER QDialog (Fenster min. 560 px, Namensfeld min. 420 px) mit
        # Name + Beschreibung in EINEM Formular (vorher zwei schmale
        # QInputDialog-Instanzen hintereinander). Der Auto-Namensgenerator
        # fuellt das Namensfeld vor (deutsch, Fallbacks; kein leeres Feld).
        suggested = ""
        try:
            suggested = self._vm.generate_profile_name_suggestion() or ""
        except Exception:
            suggested = ""
        dialog = QDialog(self)
        dialog.setWindowTitle("Neues Profil")
        dialog.setMinimumWidth(560)
        form = QFormLayout(dialog)
        edit_name = QLineEdit(suggested)
        edit_name.setMinimumWidth(420)
        edit_name.setPlaceholderText("Profil-Name")
        edit_desc = QLineEdit()
        edit_desc.setPlaceholderText("Beschreibung (optional)")
        form.addRow("Name:", edit_name)
        form.addRow("Beschreibung:", edit_desc)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Anlegen")
        form.addRow(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.Accepted:
            return
        name = (edit_name.text() or "").strip()
        if not name:
            return
        desc = (edit_desc.text() or "").strip()
        # 10.08.2026 (Punkte 3/4): UI-Layout (Seite + Heatmap-Modus) im
        # neuen Profil persistieren (create_profile ruft _current_payload).
        self._vm.set_ui_layout(self._current_ui_layout())
        try:
            self._vm.create_profile(name, desc)
        except ValueError as e:
            QMessageBox.warning(self, "Profil anlegen", str(e))

    @Slot()
    def _on_profile_save(self) -> None:
        """Explicit Save: Name/Beschreibung + aktuelle Parameter persistieren.

        21.01 (E5): Name und Beschreibung werden im SEPARATEN Speicher-Dialog
        mit den aktuellen Profilwerten vorbelegt (die Header-Edit-Felder sind
        entfernt). Ohne Namensaenderung bleibt der bestehende Name erhalten
        (kein '?'-Verlust).
        """
        if self._vm.active_profile is None:
            return
        # 20.01: save_profile() bestaetigt die aktuelle Datenquellen-Wahl ->
        # Warn-Label (fehlende Services) zuruecksetzen.
        self.label_missing_warning.setVisible(False)
        pid = self._vm.active_profile["profile_id"]
        current_name = (self._vm.active_profile.get("name") or "").strip()
        current_desc = (self._vm.active_profile.get("description")
                        or "").strip()
        dialog = QDialog(self)
        dialog.setWindowTitle("Profil speichern")
        form = QFormLayout(dialog)
        edit_name = QLineEdit(current_name)
        edit_desc = QLineEdit(current_desc)
        edit_desc.setPlaceholderText("Beschreibung (optional)")
        form.addRow("Name:", edit_name)
        form.addRow("Beschreibung:", edit_desc)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Speichern")
        form.addRow(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.Accepted:
            return
        name = self._resolve_save_name(edit_name.text(), current_name)
        desc = (edit_desc.text() or "").strip()
        self._vm.update_profile(pid, name=name, description=desc)
        # 10.08.2026 (Punkte 3/4): UI-Layout (Seite + Heatmap-Modus) in das
        # Profil persistieren (save_profile ruft _current_payload).
        self._vm.set_ui_layout(self._current_ui_layout())
        self._vm.save_profile()

    @Slot()
    def _on_profile_delete(self) -> None:
        if self._vm.active_profile is None:
            return
        name = self._vm.active_profile.get("name") or "?"
        reply = QMessageBox.question(
            self, "Profil löschen",
            f"Profil '{name}' wirklich löschen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._vm.delete_profile(self._vm.active_profile["profile_id"])

    # ------------------------------------------------------------------
    # Jump-to-Chart (Variante 2): open_chart_at_bar
    # ------------------------------------------------------------------
    def _open_chart_at_bar(
        self, symbol: str, timeframe: str, bar_time: int
    ) -> None:
        """Oeffnet/fokussiert ein Chart-Fenster an der Bar-Position."""
        main_window = self._find_main_window()
        if main_window is not None and hasattr(main_window, "open_chart_at_bar"):
            main_window.open_chart_at_bar(symbol, timeframe, bar_time)
        elif main_window is not None and hasattr(main_window, "open_chart_window"):
            main_window.open_chart_window()

    def _find_main_window(self):
        app = QApplication.instance()
        if not app:
            return None
        for widget in app.topLevelWidgets():
            if widget.metaObject().className() == "MainWindow":
                return widget
        return None

    # ------------------------------------------------------------------
    # Initiale Ladung + Lebenszyklus
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Workspace-Persistenz (20.01, E1/E7): vm.params + UI-Layout
    # ------------------------------------------------------------------
    @staticmethod
    def _snapshot_params(params: Dict[str, Any]) -> Dict[str, Any]:
        """Flache, entkoppelte Kopie der VM-Params (kein Aliasing, B3-3).

        Runde 11 (Bug 3, B3-3): Die Workspace-Persistenz darf die
        ViewModel-Referenz nicht weiterreichen - Listen/Dicts
        (feature_ids, instance_hashes, Zoom-Bereiche, table_column_widths)
        werden als Kopien uebernommen (mutierende Aufrufer aendern sonst
        die Live-Params des ViewModel).
        """
        out: Dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, list):
                out[k] = list(v)
            elif isinstance(v, dict):
                out[k] = dict(v)
            else:
                out[k] = v
        return out

    def _save_workspace(self) -> None:
        """Persistiert den Analytics-Workspace (VM-Parameter + Layout).

        20.01: Payload = {"params": vm.params, "layout": {"page_index": ...}}.
        Wird im closeEvent VOR super().closeEvent() ausgefuehrt. Seit Runde
        17e (_keep_history_on_close=False) wird die instance_states-Zeile
        beim manuellen Schliessen zwar geloescht - das Workspace-Backup in
        global_settings ("analytics_workspace") ueberlebt und wird beim
        naechsten manuellen Oeffnen wiederhergestellt.
        """
        try:
            # Runde 11 (Bug 3, B3-3): Entkoppelte Kopie statt Referenz -
            # der ViewModel._params wuerde sonst mit dem Workspace-Payload
            # aliasen (mutierende Aufrufer aendern die Live-Params).
            params_snapshot = self._snapshot_params(self._vm.params)
            payload = {
                "params": params_snapshot,
                "layout": {
                    "page_index": self.sidebar.currentRow()
                    if hasattr(self, "sidebar") else 0,
                    # 20.02 (E2): Ansichts-Modus der Heatmap-Seite
                    # (standard | generic) im Workspace mitpersistieren.
                    "heatmap_mode": self.heatmap_page.mode_id
                    if hasattr(self, "heatmap_page") else "standard",
                    # 10.08.2026 (Bugfix Runde 7, Bug 2): War der
                    # ServicePicker beim Schliessen offen? _save_workspace
                    # laeuft VOR dem close() des Dialogs im closeEvent,
                    # damit der Zustand hier noch sichtbar ist.
                    "service_picker_open": bool(
                        self._service_dialog is not None
                        and self._service_dialog.isVisible()),
                },
            }
            self.state_manager.save_workspace_state(
                self.INSTANCE_ID, payload)
            # 11.08.2026 (Bugfix Runde 17e, User-Meldung 2): Zusaetzliches
            # Backup in global_settings - es ueberlebt das MANUELLE
            # Schliessen (delete_instance loescht die instance_states-Zeile)
            # und wird beim naechsten manuellen Oeffnen wiederhergestellt
            # (Fallback in _restore_workspace).
            try:
                self.state_manager.save_global_value(
                    "analytics_workspace", payload)
            except Exception:
                pass
        except Exception as e:
            print(f"WARN [AnalyticsWindow] Workspace-Save fehlgeschlagen: {e}")

    def _restore_workspace(self) -> None:
        """Stellt den letzten Workspace wieder her (20.01, E7).

        Laeuft NACH load_profiles() (aktives Profil wird zuerst angewendet);
        der Workspace (letzter Sitzungszustand) gewinnt. Fehlende Services
        meldet der ViewModel via missing_services_detected -> Warn-Label.
        """
        try:
            payload = self.state_manager.get_workspace_state(
                self.INSTANCE_ID)
        except Exception as e:
            print(f"WARN [AnalyticsWindow] Workspace-Restore fehlgeschlagen: {e}")
            return
        # 11.08.2026 (Bugfix Runde 17e, User-Meldung 2): Nach einem MANUELLEN
        # Schliessen ist die instance_states-Zeile geloescht - Fallback auf
        # das global_settings-Backup aus _save_workspace.
        if not payload:
            try:
                payload = self.state_manager.get_global_value(
                    "analytics_workspace")
            except Exception:
                payload = None
        if not payload:
            return
        self._vm.restore_workspace(payload)
        # Combos/Button mit den restaurierten VM-Parametern synchronisieren.
        self._sync_profile_filters()
        self._sync_service_filter_button()
        page_index = int(
            (self._vm.workspace_layout or {}).get("page_index", -1))
        if 0 <= page_index < self.pages_stack.count():
            self.sidebar.setCurrentRow(page_index)
        # 20.02 (E2): Ansichts-Modus der Heatmap-Seite wiederherstellen.
        try:
            heatmap_mode = (self._vm.workspace_layout or {}).get(
                "heatmap_mode")
            if heatmap_mode:
                self.heatmap_page.set_mode(str(heatmap_mode))
        except Exception as e:
            print(f"WARN [AnalyticsWindow] Heatmap-Modus-Restore: {e}")
        # Limit-Feld mit dem VM-Wert synchronisieren (Workspace kann abweichen).
        if hasattr(self, "edit_limit"):
            self.edit_limit.setText(
                str(int(self._vm.params.get("limit")
                        or self._default_limit)))
        # 10.08.2026 (Bugfix Runde 7, Bug 2): War der ServicePicker beim
        # Schliessen offen, wird er nach dem Restore wieder geoeffnet (die
        # Position stellt der Dialog selbst aus global_settings wieder her).
        try:
            if (self._vm.workspace_layout or {}).get("service_picker_open"):
                self._open_service_dialog()
        except Exception as e:
            print(f"WARN [AnalyticsWindow] ServicePicker-Restore: {e}")

    def _initial_load(self) -> None:
        # Runde 10 (Bug 3): Deterministischer Initial-Load - die Symbol-Combo
        # wird hier nochmals gefuellt (idempotent, erhaelt die aktuelle
        # Auswahl), damit sie NICHT leer sein kann, wenn restore_state (t=0)
        # noch kein Symbol gesetzt hat. Leere Combos wurden sonst per
        # set_symbol("")/set_timeframe("") in die VM-Params uebernommen ->
        # _current_params() lieferte None -> Initial-Queries uebersprungen.
        self._refresh_symbol_combo()
        if self.combo_symbol.currentText():
            self._vm.set_symbol(self.combo_symbol.currentText())
        if self.combo_tf.currentText():
            self._vm.set_timeframe(self.combo_tf.currentText())
        self._vm.load_profiles()
        # Bugfix 08.08.2026 (symbol/tf-Profil-Restore): load_profiles()
        # emittiert active_profile_changed NICHT (nur set_active_profile/
        # create_profile) – die VM-Parameter wurden aber bereits aus dem
        # Profil-Payload gesetzt. Die Combos muessen deshalb hier explizit
        # synchronisiert werden, sonst bleiben sie auf den Historie-Werten
        # (inkonsistente Anzeige + falsche Persistenz beim Schliessen).
        self._sync_profile_filters()
        # Bugfix 08.08.2026 (Profilname '?' nach Save): Auch die Name-/
        # Beschreibungs-Felder bleiben nach load_profiles() leer (kein
        # active_profile_changed). Beim ersten Save wuerde update_profile
        # name='' persistieren und die Combo zeigt '?'. Deshalb die Felder
        # hier aus dem (ggf. geladenen) aktiven Profil synchronisieren.
        self._sync_profile_editor()
        # 20.01 (E7): Workspace NACH dem aktiven Profil anwenden – der letzte
        # Sitzungszustand gewinnt. Fehlende Services -> Warn-Label.
        self._restore_workspace()
        self._on_page_changed(self.sidebar.currentRow())
        # Runde 9 (Bug 4): Finalen Refresh sicherstellen - falls weder ein
        # aktives Profil (load_profiles) noch ein Workspace (restore_workspace)
        # existierte, wurde ggf. keine Query gestartet (set_symbol/
        # set_timeframe waren idempotent). refresh_all() stoesst die
        # Initial-Queries mit den finalen Parametern an (der Debounce
        # buegelt doppelte Refreshes ab). Der Datenquellen-Button wird
        # ebenfalls nachgezogen (fehlte nach reinem Profil-/Workspace-Start).
        self._vm.refresh_all()
        self._sync_service_filter_button()
        # 15.03-E: QUERY_FEATURES speiste das entfernte combo_feature-Dropdown –
        # ohne Feature-Dropdown ist keine Features-Metadaten-Abfrage noetig.

    def save_state(self) -> None:
        """Persistiert Fenster-POSITION und -GROESSE (inkl. Dialog-Fallback).

        11.08.2026 (Bugfix Runde 17e, User-Meldung 2): Neben window_instances
        wird die Geometrie zusaetzlich in global_settings gesichert
        (DIALOG_GEOMETRY_KEY) – sie ueberlebt damit das manuelle Schliessen
        (delete_instance loescht window_instances/instance_states) und wird
        beim naechsten manuellen Oeffnen ueber den Fallback in
        restore_state() wiederhergestellt (Muster ServiceWindow).
        """
        inst_id = self.get_instance_id()
        if not inst_id:
            return
        try:
            p = self.pos()
            self._state_manager.save_dialog_geometry(
                self.DIALOG_GEOMETRY_KEY, p.x(), p.y(),
                self.width(), self.height())
        except Exception:
            pass
        # Basis-Teil: window_instances-Geometrie + instance_states
        # (Symbol/Timeframe via get_persistent_symbol/timeframe).
        super().save_state()

    def restore_state(self) -> None:
        """Stellt Geometrie + Filter wieder her (inkl. Dialog-Fallback).

        11.08.2026 (Bugfix Runde 17e, User-Meldung 2): Nach einem MANUELLEN
        Schliessen existiert kein window_instances-Eintrag mehr – die
        Position wird dann aus global_settings (DIALOG_GEOMETRY_KEY)
        wiederhergestellt (Muster ServiceWindow). Der Rest (Symbol/
        Timeframe/Workspace) laeuft ueber super().restore_state() bzw.
        _initial_load -> _restore_workspace().
        """
        inst_id = self.get_instance_id()
        if not inst_id:
            return
        # Window-Flags korrigieren (NUR bei unsichtbarem Fenster –
        # setWindowFlags() auf sichtbarem Fenster bricht die Layout-
        # Geometrie-Verwaltung, Bugfix Runde 17c).
        if not self.isVisible():
            self._fix_window_flags()
        geom = self._state_manager.get_window_geometry(inst_id)
        if not geom:
            try:
                geom = self._state_manager.get_dialog_geometry(
                    self.DIALOG_GEOMETRY_KEY)
            except Exception:
                geom = None
        if geom:
            pos_x = geom.get("pos_x")
            pos_y = geom.get("pos_y")
            width = geom.get("width")
            height = geom.get("height")
            screen_geo = QApplication.primaryScreen().availableGeometry()
            if width and height:
                self.resize(max(int(width), 640), max(int(height), 480))
            if pos_x is not None and pos_y is not None:
                if pos_x < screen_geo.x() - 100 or pos_x > screen_geo.right() or \
                   pos_y < screen_geo.y() - 100 or pos_y > screen_geo.bottom():
                    pos_x, pos_y = 100, 100
                self.move(pos_x, pos_y)
            self._restored_is_maximized = bool(geom.get("is_maximized", False))
        # Symbol/Timeframe (instance_states) ueber die Basis wiederherstellen.
        super().restore_state()

    def closeEvent(self, event) -> None:
        """Stoppt Debounce + Worker und persistiert den Workspace.

        11.08.2026 (Bugfix Runde 17e, User-Meldung 2): _keep_history_on_close
        = False – der Fenster-Historie-Eintrag wird beim MANUELLEN
        Schliessen entfernt (kein Wiedererscheinen beim Neustart). Der
        Workspace (instance_states.workspace_state + global_settings-Backup)
        wird hier VOR super().closeEvent() gespeichert und beim naechsten
        manuellen Oeffnen wiederhergestellt.
        """
        try:
            self._vm.shutdown()
        except Exception:
            pass
        # 10.08.2026 (Bugfix Runde 7, Bug 2): Der Workspace wird VOR dem
        # Schliessen des ServicePickers gespeichert, damit `service_picker_
        # open` den Zustand des noch sichtbaren Dialogs erfasst.
        self._save_workspace()
        # 10.08.2026 (Bugfix, Punkt 3): Den ServicePicker-Singleton mit
        # schliessen, wenn das AnalyticsWindow geschlossen wird - sonst
        # bleibt der frei bewegliche Dialog als Waisenfenster haengen.
        # Das `destroyed`-Signal setzt self._service_dialog zurueck.
        try:
            if self._service_dialog is not None:
                self._service_dialog.close()
        except (RuntimeError, AttributeError):
            pass
        super().closeEvent(event)

```

--------------------------------------------------

### DATEI: analytics/ui/common.py
```py
# analytics/ui/common.py
"""
Gemeinsame UI-Helfer der Analytics-Pages (analytics/ui/*, Phase 15.03).

- format_wanduhr_time(): Wanduhr-Formatierung (Invariante 7, KEIN Offset)
- make_overlay_stack(): 'Keine Daten'-Overlay (QStackedLayout) fuer die
  Seiten mit Progress-Spinner-/No-Data-Semantik (15.03-Spezifikation).
"""

from datetime import datetime, timezone
from typing import Any, List

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QStackedLayout,
    QWidget,
)

# Ausgabeformat der Wanduhr-Zeit (z. B. '03.08.2026 12:00').
WANDUHR_FORMAT = "%d.%m.%Y %H:%M"


def format_wanduhr_time(epoch: Any) -> str:
    """Formatiert eine Wanduhr-encoded Epoch DIREKT als Berliner Wanduhrzeit.

    Invariante 7: Die gespeicherten Epochs sind Wanduhr-encoded (MT5 liefert
    Berlin-Wanduhr-Epochs; die UTC-Darstellung IST die Wanduhr-Zeit). Daher
    formatiert `fromtimestamp(epoch, tz=utc)` OHNE weiteren Berlin-Offset
    korrekt und ist automatisch DST-robust (CEST/CET sind bereits in den
    Roh-Epochs enthalten). Ein zusaetzlicher +2h/+1h-Offset waere falsch.
    """
    try:
        dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
    return dt.strftime(WANDUHR_FORMAT)


def make_overlay_stack(
    content: QWidget, message: str = "Keine Daten vorhanden."
) -> QStackedLayout:
    """Stapelt einen zentrierten 'Keine Daten'-Hinweis ueber den Inhalt.

    Index 0 = Inhalt, Index 1 = Overlay. Die Seiten schalten per
    `stack.setCurrentIndex(0 | 1)` um (No-Data-Overlay, 15.03-Spez).
    """
    stack = QStackedLayout()
    overlay = QLabel(message)
    overlay.setAlignment(Qt.AlignCenter)
    overlay.setStyleSheet("color: #808080; font-size: 14px;")
    stack.addWidget(content)
    stack.addWidget(overlay)
    stack.setCurrentWidget(content)
    return stack


class CheckableComboBox(QComboBox):
    """QComboBox mit Checkbox-Items und offen bleibendem Pop-up (20.03.02).

    Mehrfach-Auswahl ueber `QStandardItem` (`Qt.ItemIsUserCheckable`),
    Formatierung `{Service-Name} / {Parameter}` durch den Aufrufer
    (Display-Text). Das Pop-up bleibt beim Anklicken einer Checkbox geoeffnet
    (Klick im Viewport unterdrueckt `hidePopup()`), schliesst aber normal bei
    Aussenklick / Escape / Fokusverlust.

    API:
      * `add_checkable_item(display_text, user_data, checked=False)`
      * `checked_data() -> List[str]`  – user_data der angehakten Items
      * Signal `selection_changed(list)` – bei jedem CheckState-Wechsel
        (blockierbar ueber `blockSignals(True)`, Muster heatmap_widget).

    Headless instanziierbar: Der Konstruktor startet KEINEN Event-Loop
    (kein exec_()).
    """

    #: Wird bei jedem CheckState-Wechsel mit der Liste der angehakten
    #: `user_data`-Werte emittiert (in Item-Reihenfolge).
    selection_changed = Signal(list)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._popup_click = False
        # 20.03.03 (Q5): Zuletzt vom Nutzer geklicktes Item (Row-Index) –
        # Grundlage der XOR-Reconciliation im HeatmapWidget (Sammel- vs.
        # Einzel-Eintrag desselben Keys). -1 = kein Klick (programmatisch).
        self._last_click_index = -1
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.setPlaceholderText("Felder wählen…")
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        # Pop-up offen halten: Mausklick auf den Viewport setzt das Flag,
        # `hidePopup()` unterdrueckt das Schliessen dann einmalig.
        self.view().viewport().installEventFilter(self)
        # 10.08.2026 (Bugfix, Klick-Ergonomie): Bei setEditable(True) deckt
        # die LineEdit-Flaeche den Grossteil der Box ab und schluckt Klicks
        # (Textmarkierung/ignorieren) - der EventFilter oeffnet/schliesst das
        # Popup bei Klick auf die GESAMTE Flaeche (Textfeld + Pfeil/Rahmen).
        self.lineEdit().installEventFilter(self)
        self._model.itemChanged.connect(self._on_item_changed)

    # ------------------------------------------------------------------
    # Pop-up-Steuerung (offen bei Checkbox-Klick)
    # ------------------------------------------------------------------
    def hidePopup(self) -> None:
        """Unterdrueckt das Schliessen bei Klicks in den Viewport (20.03.02).

        Alle anderen Schliess-Gruende (Aussenklick, Escape, Fokusverlust)
        verhalten sich wie beim Standard-QComboBox.
        """
        if self._popup_click:
            self._popup_click = False
            return
        super().hidePopup()

    def eventFilter(self, obj, event) -> bool:
        """Setzt das Popup-Flag bei Mausklicks auf den Popup-Viewport und
        merkt sich den zuletzt geklickten Item-Index (20.03.03, Q5).

        10.08.2026 (Bugfix, Klick-Ergonomie): Zusaetzlich wird die LineEdit-
        Flaeche (editable ComboBox) abgedeckt - ein Linksklick dort oeffnet/
        schliesst das Popup wie der Pfeil-Button statt Textmarkierung."""
        if (obj is self.lineEdit()
                and event.type() == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton):
            self._popup_click = False
            if self.view().isVisible():
                self.hidePopup()
            else:
                self.showPopup()
            event.accept()
            return True
        if (obj is self.view().viewport()
                and event.type() == QEvent.MouseButtonRelease):
            self._popup_click = True
            self._last_click_index = self.view().indexAt(event.pos()).row()
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event) -> None:
        """Oeffnet/Schliesst das Popup bei Klick auf die Box (10.08.2026).

        Die LineEdit-Flaeche uebernimmt der eventFilter (editable ComboBox);
        diese Methode deckt die restliche Box (Pfeil/Rahmen) ab."""
        if event.button() == Qt.LeftButton:
            self._popup_click = False
            if self.view().isVisible():
                self.hidePopup()
            else:
                self.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)

    def last_click_index(self) -> int:
        """Row-Index des zuletzt geklickten Items (Q5, XOR-Aufloesung).

        -1, wenn der letzte CheckState-Wechsel programmatisch erfolgte
        (kein Klick) – dann findet keine XOR-Aufloesung statt.
        """
        return self._last_click_index

    # ------------------------------------------------------------------
    # Befuellung / Auslesen
    # ------------------------------------------------------------------
    def add_checkable_item(
        self, display_text: str, user_data: Any, checked: bool = False
    ) -> None:
        """Fuegt ein Checkbox-Item hinzu (display_text, user_data)."""
        item = QStandardItem(str(display_text))
        item.setData(user_data, Qt.UserRole)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._model.appendRow(item)

    def add_disabled_item(self, display_text: str) -> None:
        """Fuegt einen deaktivierten, grauen Hinweis-Eintrag hinzu (Q8-Fix).

        (No Data)-Unterstuetzung: Neue Varianten ohne feature_store-Daten
        werden als nicht-waehlbare, graue Eintraege im 'Feld'-Dropdown
        angezeigt ('{Service} ({Preset}) – (No Data)'), bis der erste
        Scan/LiveRun sie berechnet hat. Anders als `add_header_item` ist
        der Eintrag NICHT fett und traegt userData=None (kein
        selection_changed-Beitrag, nicht in checked_data()).
        """
        item = QStandardItem(str(display_text))
        item.setData(None, Qt.UserRole)
        item.setFlags(Qt.NoItemFlags)
        item.setEnabled(False)
        item.setForeground(QBrush(QColor(160, 160, 160)))  # hellgrau
        self._model.appendRow(item)

    def add_header_item(self, display_text: str) -> None:
        """Fuegt eine deaktivierte, nicht-auswaehlbare Trenn-/Kopfzeile hinzu
        (20.03.03, Q4).

        Header tragen `Qt.NoItemFlags` + `userData=None` und erscheinen daher
        weder als auswaehlbares Item noch in `checked_data()`.
        """
        item = QStandardItem(str(display_text))
        item.setData(None, Qt.UserRole)
        item.setFlags(Qt.NoItemFlags)          # nicht aktiv, nicht checkbar
        item.setEnabled(False)
        item.setForeground(QBrush(QColor(128, 128, 128)))  # grau
        f = item.font()
        f.setBold(True)
        item.setFont(f)
        self._model.appendRow(item)

    def checked_data(self) -> List[str]:
        """Liefert die `user_data`-Werte aller angehakten Items."""
        out: List[str] = []
        for i in range(self._model.rowCount()):
            item = self._model.item(i)
            if item is not None and item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out

    def set_checked_data(self, checked_values: List[str]) -> None:
        """Setzt die CheckStates anhand einer Liste von user_data-Werten.

        Items mit einem Wert aus `checked_values` werden angehakt, alle
        anderen abgewaehlt (blockiert, kein selection_changed-Emit).
        """
        wanted = {str(v) for v in (checked_values or [])}
        self.blockSignals(True)
        try:
            for i in range(self._model.rowCount()):
                item = self._model.item(i)
                if item is None:
                    continue
                on = str(item.data(Qt.UserRole) or "") in wanted
                item.setCheckState(Qt.Checked if on else Qt.Unchecked)
            self._update_line_text()
        finally:
            self.blockSignals(False)

    def _on_item_changed(self, item) -> None:
        """CheckState-Wechsel -> LineEdit-Text aktualisieren + Signal."""
        if item is None or not (item.flags() & Qt.ItemIsUserCheckable):
            return
        self._update_line_text()
        self.selection_changed.emit(self.checked_data())

    def _update_line_text(self) -> None:
        """Kompakte Zusammenfassung im (read-only) LineEdit."""
        labels = [
            self._model.item(i).text()
            for i in range(self._model.rowCount())
            if self._model.item(i) is not None
            and self._model.item(i).checkState() == Qt.Checked
        ]
        if not labels:
            self.lineEdit().setText("")
        elif len(labels) == 1:
            self.lineEdit().setText(labels[0])
        else:
            self.lineEdit().setText(f"{len(labels)} Felder gewählt")

```

--------------------------------------------------

### DATEI: analytics/ui/distribution_page.py
```py
# analytics/ui/distribution_page.py
"""
distribution_page.py - Verteilungs-Seite der Analytics-UI (Phase 15.03 / 19.02).

Zeigt das Histogramm eines feature_data-JSON-Keys (dynamisch, 19.02) als
pyqtgraph-BarGraphItem. Spalte und Bin-Anzahl sind ueber die Steuerleiste
einstellbar; die Bin-Aenderung laeuft ueber den ViewModel-Debounce
(200-300 ms, 15.03-Spezifikation).

MVVM (Invariante 4): Reine UI – Daten kommen ueber
`data_ready(QUERY_DISTRIBUTION, data)` vom ViewModel (Async-Worker); es
gibt KEIN SQL in dieser Klasse.
"""

from typing import Any, Dict

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_worker import QUERY_DISTRIBUTION
from analytics.ui.common import make_overlay_stack

_BINS_MIN = 2
_BINS_MAX = 100


class DistributionPage(QWidget):
    """Histogramm einer nativen Spalte (bins-Slider + Spalten-Dropdown)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None

        self._combo_column = QComboBox()
        self._slider_bins = QSlider(Qt.Horizontal)
        self._slider_bins.setRange(_BINS_MIN, _BINS_MAX)
        self._label_bins = QLabel("20")

        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.setLabel("left", "Anzahl")
        self._bar = pg.BarGraphItem(
            x=[], height=[], width=0.8, brush=pg.mkBrush(41, 98, 255)
        )
        self._plot.addItem(self._bar)

        content = QWidget(self)
        lay = QVBoxLayout(content)
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Spalte:"))
        ctrl.addWidget(self._combo_column)
        ctrl.addWidget(QLabel("Bins:"))
        ctrl.addWidget(self._slider_bins)
        ctrl.addWidget(self._label_bins)
        ctrl.addStretch(1)
        lay.addLayout(ctrl)
        lay.addWidget(self._plot)
        self._stack = make_overlay_stack(content)
        self.setLayout(self._stack)

        self._combo_column.currentTextChanged.connect(self._on_column_changed)
        self._slider_bins.valueChanged.connect(self._on_bins_changed)

    # ------------------------------------------------------------------
    # MVVM-Anbindung (vom AnalyticsWindow gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        self._view_model = view_model
        params = view_model.params
        # 19.02 (Cleanup): Dynamische feature_data-JSON-Keys statt nativer
        # Spalten. Prefill fuer das aktuelle Symbol/Timeframe; die Combo
        # wird bei jedem Daten-Payload aktualisiert (on_data_ready).
        columns = view_model.available_feature_columns(
            params.get("symbol", ""), params.get("timeframe", "M1"))
        self._set_columns(columns, params.get("distribution_column"))
        self._slider_bins.blockSignals(True)
        self._slider_bins.setValue(int(params.get("bins") or 20))
        self._slider_bins.blockSignals(False)
        self._label_bins.setText(str(self._slider_bins.value()))
        view_model.data_ready.connect(self.on_data_ready)

    def request_data(self) -> None:
        if self._view_model is not None:
            self._view_model.request_distribution()

    # ------------------------------------------------------------------
    # 19.02: Dynamische Spalten-Combo (feature_data-JSON-Keys)
    # ------------------------------------------------------------------
    def _set_columns(self, columns, column) -> None:
        """Fuellt die Spalten-Combo (19.02, dynamische JSON-Keys).

        Erhaelt die aktuelle Auswahl, wenn sie in `columns` verfuegbar ist;
        sonst erster Key. Signale blockiert (kein Query-Loop).
        """
        cols = [str(c) for c in (columns or [])]
        sel = str(column or "") if str(column or "") in cols else (
            cols[0] if cols else "")
        self._combo_column.blockSignals(True)
        self._combo_column.clear()
        for c in cols:
            self._combo_column.addItem(c, c)
        self._combo_column.setCurrentIndex(
            self._combo_column.findData(sel) if sel else -1)
        self._combo_column.blockSignals(False)

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind != QUERY_DISTRIBUTION:
            return
        # 19.02: Combo mit den verfuegbaren JSON-Keys aktualisieren und auf
        # die tatsaechlich verwendete Spalte synchronisieren.
        vm_params_col = (self._view_model.params.get("distribution_column")
                         if self._view_model else "")
        self._set_columns(
            data.get("columns"),
            data.get("column") or vm_params_col,
        )
        bins = data.get("bins") or []
        counts = data.get("counts") or []
        if not bins or not counts:
            self._bar.setOpts(x=[], height=[], width=0.8)
            self._stack.setCurrentIndex(1)
            return
        widths = [bins[i + 1] - bins[i] for i in range(len(counts))]
        centers = [(bins[i] + bins[i + 1]) / 2.0 for i in range(len(counts))]
        self._bar.setOpts(
            x=centers,
            height=[float(c) for c in counts],
            width=0.9 * min(widths) if widths else 0.8,
        )
        self._plot.setLabel(
            "bottom", str(data.get("column") or "")
        )
        self._plot.autoRange()
        self._stack.setCurrentIndex(0)

    # ------------------------------------------------------------------
    # Steuerung (Spalte/Bins -> ViewModel -> Debounce -> Worker)
    # ------------------------------------------------------------------
    def _on_column_changed(self, column: str) -> None:
        if self._view_model is not None and column:
            self._view_model.set_distribution_column(column)

    def _on_bins_changed(self, value: int) -> None:
        if self._view_model is not None:
            self._label_bins.setText(str(value))
            self._view_model.set_bins(value)

```

--------------------------------------------------

### DATEI: analytics/ui/equity_page.py
```py
# analytics/ui/equity_page.py
"""
equity_page.py - Equity-Seite der Analytics-UI (Phase 15.03).

Platzhalter-Seite fuer die Equity-Analyse: Es existiert noch KEINE
Equity-Datenquelle in PyTrader (geplant fuer eine spaetere Phase). Die
Seite reserviert den pyqtgraph-Plotbereich und zeigt dauerhaft das
'No Data'-Overlay (15.03-Spezifikation: 'No Data'-Overlay).

MVVM (Invariante 4): Reine UI, keine Datenabfrage (noch kein
query_kind). Sobald eine Equity-Datenquelle existiert, wird diese Seite
additiv an einen neuen QUERY_*-Kanal des ViewModels angebunden.
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

import pyqtgraph as pg

from analytics.ui.common import make_overlay_stack

_NO_DATA_MESSAGE = (
    "Equity-Analyse: noch keine Daten vorhanden "
    "(geplant fuer eine spaetere Phase)."
)


class EquityPage(QWidget):
    """Equity-Verlauf (Platzhalter mit dauerhaftem 'No Data'-Overlay)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None

        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.setLabel("bottom", "Zeit (Berlin Wanduhr)")
        self._plot.setLabel("left", "Equity")

        content = QWidget(self)
        lay = QVBoxLayout(content)
        lay.addWidget(QLabel("Equity-Verlauf"))
        lay.addWidget(self._plot)
        self._stack = make_overlay_stack(content, message=_NO_DATA_MESSAGE)
        self.setLayout(self._stack)
        # Dauerhaftes No-Data-Overlay (noch keine Equity-Datenquelle).
        self._stack.setCurrentIndex(1)

    def attach_view_model(self, view_model: Any) -> None:
        """Vorgesehen fuer die spaetere Equity-Anbindung (additiv)."""
        self._view_model = view_model

    def request_data(self) -> None:
        """No-op: noch keine Equity-Datenabfrage vorhanden."""
        return

```

--------------------------------------------------

### DATEI: analytics/ui/heatmap_page.py
```py
# analytics/ui/heatmap_page.py
"""
heatmap_page.py - Heatmap-Seite der Analytics-UI (Phase 15.03).

Zeigt die 2D-Matrix (X: Wochentage, Y: Tagesstunden Berlin Wanduhr,
Invariante 7) als pyqtgraph-ImageItem mit Farbskala. Ein Doppelklick auf
eine Zelle oeffnet das Chart an der neuesten Feature-Bar dieser Zelle
(Jump-to-Chart Variante 2, Aufloesung ueber den ViewModel).

MVVM (Invariante 4): Reine UI – Daten kommen ueber
`data_ready(QUERY_HEATMAP, data)` vom ViewModel (Async-Worker); es gibt
KEIN SQL in dieser Klasse.
"""

from typing import Any, Callable, Dict, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_worker import QUERY_HEATMAP
from analytics.engine.feature_store_reader import (
    DOW_LABELS,
    DAYS_PER_WEEK,
    HOURS_PER_DAY,
)
from analytics.ui.common import make_overlay_stack
from analytics.ui.heatmap_widget import HeatmapWidget

# Farbverlauf (pyqtgraph-intern, 'viridis').
_HEATMAP_COLORMAP = "viridis"


class HeatmapPage(QWidget):
    """Heatmap Wochentag x Stunde (Berlin Wanduhr) mit Jump-to-Chart."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None
        self._navigation_handler: Optional[Callable[[str, str, int], None]] = None
        self._cell_resolver: Optional[Callable[[str, str, int, int], Optional[int]]] = None
        self._current_symbol = ""
        self._current_timeframe = "M1"

        # Metrik-Dropdown (19.02: count | numerische feature_data-JSON-Keys)
        self._combo_metric = QComboBox()
        self._label_info = QLabel("")

        # pyqtgraph-Plot + ImageItem + Farbskala
        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.setLabel("bottom", "Wochentag")
        self._plot.setLabel("left", "Stunde (Berlin Wanduhr)")
        self._image = pg.ImageItem()
        self._plot.addItem(self._image)
        self._colormap = pg.colormap.get(_HEATMAP_COLORMAP)
        self._image.setColorMap(self._colormap)
        self._colorbar = pg.ColorBarItem(colorMap=self._colormap, values=(0.0, 1.0))
        self._colorbar.setImageItem(self._image)
        # Achsen-Ticks: X = Wochentage, Y = Stunden (Wanduhr)
        self._plot.getAxis("bottom").setTicks(
            [[(i, DOW_LABELS[i]) for i in range(DAYS_PER_WEEK)]]
        )
        self._plot.getAxis("left").setTicks(
            [[(h, f"{h:02d}") for h in range(0, HOURS_PER_DAY, 3)]]
        )

        content = QWidget(self)
        lay = QVBoxLayout(content)

        # 21.01 (User-Meldung 2, 11.08.2026): Das "Ansicht"-Dropdown enthaelt
        # jetzt die 4 Smart-Presets; "Wochentag × Stunde" entfaellt (der
        # Standard-Modus bleibt als Legacy-Code fuer Restores erhalten, ist
        # aber KEIN Dropdown-Eintrag mehr). "Generisch" ist die Basis-Ansicht
        # (Index 0); jede Preset-Option wendet das Preset an (Meldung 3: die
        # Bedien-Controls des generischen Widgets bleiben dabei sichtbar).
        self._combo_mode = QComboBox()
        self._combo_mode.addItem("Generisch", "generic")
        self._combo_mode.addItem("⚡ Signal-Confluence", "preset_confluence")
        self._combo_mode.addItem("🕒 Session-Hotspots", "preset_session")
        self._combo_mode.addItem("📏 Wert-Intensität", "preset_intensity")
        self._combo_mode.addItem("📊 Service-Timeframe", "preset_timeframe")
        self._combo_mode.setCurrentIndex(0)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Ansicht:"))
        mode_row.addWidget(self._combo_mode)
        mode_row.addStretch(1)
        lay.addLayout(mode_row)

        # --- Standard-Modus (bestehende Struktur, unveraendert) ---
        self._standard_ui = QWidget(self)
        std_lay = QVBoxLayout(self._standard_ui)
        std_lay.setContentsMargins(0, 0, 0, 0)
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Metrik:"))
        ctrl.addWidget(self._combo_metric)
        ctrl.addWidget(self._label_info)
        ctrl.addStretch(1)
        std_lay.addLayout(ctrl)
        std_lay.addWidget(self._plot)

        # --- Generischer Modus (20.02, E1/E7/E8/E9) ---
        self._generic = HeatmapWidget()

        self._stack_modes = QStackedWidget()
        self._stack_modes.addWidget(self._standard_ui)
        self._stack_modes.addWidget(self._generic)
        lay.addWidget(self._stack_modes)
        # 13.08.2026 (Bugfix, User-Meldung 'Heatmap wird nicht gezeigt'):
        # Die Basis-Ansicht ist seit 21.01 IMMER das generische Widget
        # (Stack Seite 1). set_mode()/_on_mode_changed() setzen Seite 1
        # ebenfalls, aber ohne diesen Initial-Switch blieb beim frischen
        # Start (kein Workspace-Restore mit heatmap_mode) die unsichtbare
        # Legacy-Standard-UI (Index 0) aktiv -> generische Heatmap nie
        # dargestellt und ihre Controls nicht bedienbar.
        self._stack_modes.setCurrentIndex(1)

        self._stack = make_overlay_stack(content)
        self.setLayout(self._stack)

        self._combo_metric.currentTextChanged.connect(self._on_metric_changed)
        self._plot.scene().sigMouseClicked.connect(self._on_plot_clicked)
        self._combo_mode.currentIndexChanged.connect(self._on_mode_changed)

    # ------------------------------------------------------------------
    # MVVM-Anbindung (vom AnalyticsWindow gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        self._view_model = view_model
        # 20.02: Das generische Widget erhaelt denselben ViewModel und
        # verbindet eigene data_ready-Slots (QUERY_HEATMAP_GENERIC/
        # QUERY_DAILY_OHLC, Bugfix 09.08.2026).
        self._generic.attach_view_model(view_model)
        # 21.01 (E7, 11.08.2026): Die `preset_clicked`-Verbindung wurde
        # entfernt – das generische Widget hat keine Preset-Buttons mehr
        # (Smart-Presets laufen ausschliesslich ueber das Ansicht-Dropdown).
        params = view_model.params
        # 19.02 (Cleanup): Metriken = "count" + numerische feature_data-
        # JSON-Keys (dynamisch). Prefill fuer das aktuelle Symbol/Timeframe;
        # die Combo wird bei jedem Daten-Payload aktualisiert (on_data_ready).
        metrics = view_model.heatmap_metrics(
            params.get("symbol", ""), params.get("timeframe", "M1"))
        self._set_metrics(metrics, params.get("heatmap_metric"))
        view_model.data_ready.connect(self.on_data_ready)

    def set_navigation_handler(self, fn: Callable[[str, str, int], None]) -> None:
        self._navigation_handler = fn

    def set_cell_resolver(
        self, fn: Callable[[str, str, int, int], Optional[int]]
    ) -> None:
        """Setzt die Zell-Aufloesung (dow, hour -> neuester bar_time)."""
        self._cell_resolver = fn

    def request_data(self) -> None:
        if self._view_model is None:
            return
        # 21.01 (Meldung 2): Die Heatmap-Ansicht ist seit dem Entfall von
        # "Wochentag × Stunde" IMMER generisch – die Daten kommen immer
        # aus dem generischen Widget (+ OHLCV-Snapshot bei aktivem Overlay, E9).
        self._generic.request_data()

    # ------------------------------------------------------------------
    # 20.02: Ansichts-Modus (Workspace-Persistenz, E2)
    # ------------------------------------------------------------------
    @property
    def mode_id(self) -> str:
        """Aktueller Modus ("generic" | "preset_*") fuer die Workspace-Speicherung."""
        return str(self._combo_mode.currentData() or "generic")

    def set_mode(self, mode_id: str) -> None:
        """Stellt den Ansichts-Modus wieder her (Workspace/Profil-Restore).

        21.01 (Meldung 2): Legacy-Modi ("standard"/"wochentag") werden auf
        "generic" gemappt. Signale blockiert (kein Dirty/Query beim Restore);
        der Stack zeigt immer das generische Widget (Meldung 3).
        """
        mid = str(mode_id or "").lower()
        if mid in ("standard", "wochentag", "wochentag_x_stunde",
                   "wochentag x stunde"):
            mid = "generic"
        idx = self._combo_mode.findData(mid)
        if idx < 0:
            idx = 0
        if self._combo_mode.currentIndex() != idx:
            self._combo_mode.blockSignals(True)
            self._combo_mode.setCurrentIndex(idx)
            self._combo_mode.blockSignals(False)
        self._stack_modes.setCurrentIndex(1)

    def _on_mode_changed(self, _index: int) -> None:
        """Wechselt die Ansicht: Preset anwenden bzw. generisch laden.

        21.01 (Meldung 2+3): Die Bedien-Controls (generisches Widget)
        bleiben bei JEDEM Preset-Wechsel sichtbar (Stack zeigt immer
        Seite 1). Eine Preset-Option wendet das Smart-Preset an.
        """
        mid = str(self._combo_mode.currentData() or "generic")
        self._stack_modes.setCurrentIndex(1)
        if mid.startswith("preset_"):
            self._apply_selected_preset(mid)
        else:
            self.request_data()

    def _apply_selected_preset(self, mid: str) -> None:
        """Wendet das im Ansicht-Dropdown gewaehlte Smart-Preset an.

        Bugfix-Muster 21.01 (Meldung 4/6): Nach dem VM-Preset werden die
        Combos des generischen Widgets via _sync_from_params nachgezogen
        (keine STALE-Combos), danach wird neu gerendert.
        """
        if self._view_model is None:
            return
        fn = {
            "preset_confluence": self._view_model.apply_smart_preset_confluence,
            "preset_session": self._view_model.apply_smart_preset_session,
            "preset_intensity": self._view_model.apply_smart_preset_intensity,
            "preset_timeframe": self._view_model.apply_smart_preset_timeframe,
        }.get(mid)
        if fn is None:
            return
        fn()
        generic = getattr(self, "_generic", None)
        if generic is not None and hasattr(generic, "_sync_from_params"):
            generic._sync_from_params()
        self.request_data()

    # ------------------------------------------------------------------
    # 19.02: Dynamische Metrik-Combo ("count" + feature_data-JSON-Keys)
    # ------------------------------------------------------------------
    def _set_metrics(self, metrics, metric) -> None:
        """Fuellt die Metrik-Combo (19.02, dynamische JSON-Keys).

        Erhaelt die aktuelle Auswahl, wenn sie in `metrics` verfuegbar ist;
        sonst "count". Signale blockiert (kein Query-Loop).
        """
        items = [str(m) for m in (metrics or [])]
        sel = str(metric or "") if str(metric or "") in items else (
            "count" if "count" in items else (items[0] if items else ""))
        self._combo_metric.blockSignals(True)
        self._combo_metric.clear()
        for m in items:
            self._combo_metric.addItem(m, m)
        self._combo_metric.setCurrentIndex(
            self._combo_metric.findData(sel) if sel else -1)
        self._combo_metric.blockSignals(False)

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind != QUERY_HEATMAP:
            return
        self._current_symbol = str(data.get("symbol") or "")
        self._current_timeframe = str(data.get("timeframe") or "M1")
        # 19.02: Metrik-Combo mit den verfuegbaren Metriken aktualisieren und
        # auf die tatsaechlich verwendete Metrik synchronisieren.
        vm_params_metric = (self._view_model.params.get("heatmap_metric")
                            if self._view_model else "")
        self._set_metrics(
            data.get("metrics"),
            data.get("metric") or vm_params_metric,
        )
        matrix = np.asarray(data.get("matrix"), dtype=float)
        if matrix.size == 0:
            # 13.08.2026 (Bugfix): Die Standard-Ansicht (dow x hour) ist
            # seit 21.01 NICHT mehr sichtbar (Stack zeigt immer das
            # generische Widget). Ihr Datenstand darf die Seiten-
            # Sichtbarkeit nicht mehr steuern - sonst verdeckt das
            # No-Data-Overlay das generische Widget (nicht anklickbar).
            return
        self._render(matrix)
        self._stack.setCurrentIndex(0)

    def _render(self, matrix: np.ndarray) -> None:
        """Zeichnet die 24x7-Matrix (rows=Stunde, cols=DOW)."""
        finite = matrix[np.isfinite(matrix)]
        if finite.size:
            vmin = float(finite.min())
            vmax = float(finite.max())
            if vmin == vmax:
                vmax = vmin + 1.0
        else:
            vmin, vmax = 0.0, 1.0
        self._image.setImage(matrix, levels=(vmin, vmax))
        self._colorbar.setLevels((vmin, vmax))
        self._plot.setXRange(-0.5, DAYS_PER_WEEK - 0.5, padding=0)
        self._plot.setYRange(-0.5, HOURS_PER_DAY - 0.5, padding=0)

    # ------------------------------------------------------------------
    # Jump-to-Chart (Variante 2): Doppelklick auf eine Zelle
    # ------------------------------------------------------------------
    def _on_plot_clicked(self, event) -> None:
        if not event.double() or self._cell_resolver is None \
                or self._navigation_handler is None:
            return
        vb = self._plot.plotItem.vb
        pos = vb.mapSceneToView(event.scenePos())
        dow = int(round(pos.x()))
        hour = int(round(pos.y()))
        if not (0 <= dow < DAYS_PER_WEEK and 0 <= hour < HOURS_PER_DAY):
            return
        bar_time = self._cell_resolver(
            self._current_symbol, self._current_timeframe, dow, hour
        )
        if bar_time is not None:
            self._navigation_handler(
                self._current_symbol, self._current_timeframe, int(bar_time)
            )

    # ------------------------------------------------------------------
    # Steuerung (Metrik -> ViewModel -> Debounce -> Worker)
    # ------------------------------------------------------------------
    def _on_metric_changed(self, metric: str) -> None:
        if self._view_model is not None and metric:
            self._view_model.set_heatmap_metric(metric)

```

--------------------------------------------------

### DATEI: analytics/ui/heatmap_widget.py
```py
# analytics/ui/heatmap_widget.py
"""
heatmap_widget.py - Generische 2D-Heatmap-Engine mit Confluence-Matrix,
Candle-Overlay & Dual-Axis-Zoom (Phase 20.02).

Additiv zur bestehenden HeatmapPage (Dow x Stunde, Standard-Modus): Dieses
Widget rendert die generische 2D-Matrix (freie Dimensionen + Aggregationen)
und das Kerzen-Overlay. MVVM (Invariante 4): KEIN SQL – die Daten kommen
ueber `data_ready(QUERY_HEATMAP_GENERIC | QUERY_DAILY_OHLC, data)` vom
ViewModel (Async-Worker).

Entscheidungen (Review 09.08.2026, E7-E9):
- E7: CONFLUENCE_COUNT -> diskrete Farbskala (0 = weiss, 1-2 = gelb/cyan,
  3-4 = orange, 5+ = dunkelrot); Wert-Aggregationen -> viridis (kontinuierlich).
- E8: Zoom = EIN Faktor-Slider pro Achse (Viewport-Skalierung, zentriert),
  normalisiert [0,1] (zoom_x_range/zoom_y_range), rein client-seitig via
  setXRange/setYRange (kein DB-Requery).
- E9: Candle-Overlay = Tages-Ohlc UEBER der Heatmap im SELBEN Canvas
  (rechte Preis-Achse, ViewBox-Link an die X-Achse), horizontal synchronisiert.

Bugfix 09.08.2026 (User-Meldungen 1-6):
1) Das Kerzen-Overlay ist KEIN separates Fenster mehr – die Tages-Candles
   liegen im selben PlotWidget ueber der Heatmap (rechte Preis-Achse).
2) Die generische Heatmap laedt ALLE verfuegbaren Daten (kein 5000er-
   Limit-Lookback mehr, ViewModel; Pivot-Deckel MAX_HEATMAP_CELLS begrenzt
   die Matrix). Das Overlay nutzt `QUERY_DAILY_OHLC` (SQL-seitig pro Tag
   aggregiert) und deckt damit den gesamten Heatmap-Zeitraum ab.
3) Die Achsen tragen die NATUERLICHEN Werte (date -> Mitternachts-Epochs,
   hour/dow -> Ganzzahlen, dow 1..5 Mo-Fr, kategorial -> Indizes); das
   ImageItem wird per setRect exakt auf diesen Bereich gemappt – nichts wird
   mehr ueber die Tagesgrenze hinaus gezeichnet.
4) Achsen-Zuordnung ist explizit (x_dim -> X, y_dim -> Y), kein Vertauschen
   mehr moeglich.
5) Dynamische X-Ticks je Zoom-Level: date -> Jahre/Monate/Tage -> Stunden ->
   Minuten (bis zur Minute, wie Chartfenster/TradingView) – 20.02.01 E1:
   5 Format-Stufen (YYYY / TT.MM.JJ / DDD TT.MM.JJ / DDD TT.MM.JJ HH:00 /
   DDD TT.MM.JJ HH:mm), Wanduhr-Garantie via UTC-Darstellung.
6) Dasselbe Prinzip gilt fuer die Y-Achse und alle Massstaebe (hour, dow,
   kategorial): je Zoom-Level werden mehr Zwischenwerte angezeigt.

20.02.01 (E2-E8, 09.08.2026): "Stunde" -> "Tageszeit" (E2, feste Skala
00:00-23:59, E3); Achsen-Label mit UTC-Offset (E4); `dow` strikt
Montag-Freitag (E5); `dow_hour` ersatzlos entfernt (E6); Overlay-Zoom-Lock
exklusiv bei X=date (E7); service_id-Achsen-Labels via ViewModel-Resolver
'{Kategorie} / {Name}' (E8).

20.02.01 (User-Meldungen 1-3, 09.08.2026): (1) Tageszeit-Achse bleibt beim
Rauszoomen auf die feste Skala 00:00-23:59 begrenzt (keine -/+ Werte
ausserhalb; tickValues-Clamping, kein `% 24`-Wrap mehr); (2) Wochentag-Achse
ebenso strikt Mo-Fr (1..6, halboffene Grenze); (3) 'Feld'-Dropdown deutlich
laenger (320-460 px) und jeder Eintrag traegt den Service-Namen, aus dem der
Wert stammt ('{Service} / {Key}', `srv_`-Prefix entfaellt, via
ViewModel-Resolver + Repository-`field_sources`). User-Meldung 3c (09.08.2026):
vor jedem Feld-Eintrag steht NUR der Service-NAME ohne Kategorie-Pfad
(`resolve_service_display_name`, z. B. 'Grid Lines / open' statt
'Swing Points / Grid Lines / open'); die E8-Achsen-Labels der
service_id-Dimension behalten weiterhin '{Kategorie} / {Name}'.

09.08.2026 (User-Meldungen Feld-Dropdown + Zoom-Richtung):
- Feld-Dropdown: Der Service-Name wird DIREKT aus dem Service-Objekt
  abgeleitet (`resolve_service_display_name` aus `plugin_id`, z. B.
  'Swing Momentum' statt des unzuverlaessigen metadata['display_name']
  'Swing Momentum Service'). Liefern MEHRERE Services denselben Key,
  entfaellt der Prefix KOMPLETT ('price' statt 'Swing Momentum Service /
  Swing Volume Profile Service / price' – die verkettete Namen zeigten
  einen irrefuehrenden MasterTree-'Pfad').
- Zoom-Slider X/Y: Richtung getauscht – rechts = Zoom-In, links = Zoom-Out
  (Slider-Wert 5 = volle Achse, 100 = maximale Vergroesserung;
  `_set_zoom_range`/`_set_zoom_slider` invers umgerechnet).
- Achse 'Datum': Beschriftung lautet 'Datum/Zeit' – OHNE das
  pyqtgraph-EXP-Suffix ('Datum (x1e+09)'). Ursache: `setLabel(text)`
  mit units=None erzeugt eine leere Einheit; die date-Epochs (~1.7e9)
  fallen in den SI-Bereich (1e9, inf) und pyqtgraph haengt '(x1e+09)'
  an. `_HeatmapAxis.enableAutoSIPrefix(False)` unterdrueckt das
  Suffix (die Ticks werden ohnehin von tickStrings formatiert).

20.02.01 (User-Meldung 2 - Datums-Skala LWC-v5, 09.08.2026): Die date-Achse
nutzt die Tick-Logik von Lightweight Charts v5 (aus dem LWC-JS extrahiert):
Der Mindestabstand zweier Labels betraegt ~80 px (`_DATE_TARGET_PX`) –
Zoom-In wechselt zur naechst feineren Variante (Stunden/Minuten), Zoom-Out
zur naechst groeberen (Jahr/Monat/Woche/Tag); keine Ueberlappung, keine
Riesensprünge. Weight-Hierarchie (LWC `Q_`): 70 Jahreswechsel ('2026'),
60 Monatswechsel ('Feb 26'), 55 Wochenanfang Mo (ISO '08.25'),
50 Tag ('Mo. 07.08.25'), 30 Stunde ('14:00'), 20 Minute ('14:23').
pyqtgraph uebergibt an `tickValues` die ACHSEN-LAENGE in Pixeln (3. Param)
– daraus wird der Mindestabstand in Sekunden berechnet.
"""

import math
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional, Set

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_worker import (
    QUERY_HEATMAP_GENERIC,
    QUERY_DAILY_OHLC,
    QUERY_FEATURES,
    QUERY_OHLCV,
)
from analytics.engine.feature_store_reader import (
    DOW_WEEK_LABELS,
    HEATMAP_AGGREGATIONS,
    HEATMAP_DIMENSIONS,
    HOURS_PER_DAY,
)
from analytics.ui.common import CheckableComboBox

# E7: Konfluenz-Farbskala (0 = grau, 1-2 = gelb/cyan, 3-4 = orange,
# 5+ = dunkelrot) – Positionen 0..1 (Levels 0..5).
# 21.01 (Bugfix 2, 11.08.2026): 0 = HELLGRAU statt Weiss – weisse
# 0-Treffer-Zellen waren auf dem weissen Plot-Hintergrund unsichtbar.
_CONFLUENCE_COLORS = [
    "#d9d9d9", "#ffff00", "#00ffff", "#ff8c00", "#ff6600", "#8b0000",
]
_CONFLUENCE_POS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
_CONFLUENCE_LEVELS = (0.0, 5.0)
_VIRIDIS = "viridis"

# E6: Wert-Aggregationen benoetigen einen numerischen feature_data-JSON-Key.
_VALUE_AGGS = ("avg", "sum", "min", "max")

# 13.08.2026 (Punkt 5, F5): Preisartige feature_data-Keys - SUM ueber
# Preise erzeugt unsinnig hohe Legendenwerte (z. B. SILVER ~43k/Tag bei
# 5-Min-Summen) und wird fuer diese Felder deaktiviert. Signal-Felder
# (strength_value) bleiben erlaubt. Abgleich mit den Output-Schemata der
# srv_*-Plugins (price, reference_price, poc_price, vah_price, val_price,
# lvn_price, grid_price, vwap_price, vwap_lower, atr_value, lower_band,
# lower_level, prox_level1..6).
_PRICE_LIKE_KEY_HINTS = (
    "price",      # Preisfelder (price, *price, reference_price)
    "vwap_lower",  # VWAP-Band-Unterkante
    "atr_value",  # ATR-Magnitude (Punkte)
    "band",       # lower_band (Trend-Breakout)
    "level",      # lower_level / prox_level* (Grid-Level)
)


def _is_price_like_key(key: str) -> bool:
    """True fuer preisartige feature_data-Keys (13.08.2026, F5)."""
    k = str(key or "").lower()
    return any(h in k for h in _PRICE_LIKE_KEY_HINTS) if k else False

# Tag in Sekunden (Wanduhr-Epoch-Basis fuer date-Achse).
_DAY_SECONDS = 86400
_HALF_DAY = 43200.0
# 20.02.01 (E1): Stufen-Schwellen des Datums-Formatters (Monat/Jahr).
_MONTH_SECONDS = 2_592_000
_YEAR_SECONDS = 31_536_000
# 21.01 (Bugfix 5, 11.08.2026): Timeframe -> Sekunden fuer das adaptive
# Candle-Overlay (OHLCV im Original-TF statt Tages-Aggregation).
_TF_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800,
}

# 20.02.01 (User-Meldung 2): LWC-v5-adaptierte Datums-Skala.
# Zielabstand zwischen zwei Tick-Labels in Pixel (Lightweight Charts:
# 5*(fontSize+4)/8 * (tickMarkMaxCharacterLength || 8) mit fontSize 12 =>
# 5*16/8*8 = 80 px). Die Tick-Auswahl haelt diesen Abstand ein: Zoom-In
# => feinere Variante, Zoom-Out => groebere Variante (keine Ueberlappung,
# keine Riesensprünge). Weight-Hierarchie wie LWC v5:
#   70 = Jahreswechsel, 60 = Monatswechsel, 55 = Wochenanfang Mo,
#   50 = Tageswechsel, 30 = Stundenmarke, 20 = Minutenmarke.
# 21.01 (Bugfix 4): Die LABELS folgen seitdem 1:1 der App-JS
# (TT.MM.JJ fuer Tages-Marken, HH:MM fuer Sub-Tag-Marken) - die alte
# 5-Format-Beschriftung ('2026'/'Feb 26'/'08.25'/'Di. 03.02.26') ist
# ersetzt, weil sie von der Chartfenster-Anzeige abwich.
_DATE_TARGET_PX = 80.0
_MONTHS_SHORT = ("Jan", "Feb", "Mrz", "Apr", "Mai", "Jun",
                 "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")

_DIM_LABELS = {
    "date": "Datum",
    "dow": "Wochentag",
    # 20.02.01 (E2): "Stunde" -> "Tageszeit" (feste Skala 00:00-23:59, E3).
    "hour": "Tageszeit",
    "timeframe": "Timeframe",
    "service_id": "Service",
    "symbol": "Symbol",
}
_AGG_LABELS = {
    "count": "Anzahl (COUNT)",
    "confluence_count": "Konfluenz (COUNT DISTINCT)",
    "avg": "Mittelwert (AVG)",
    "sum": "Summe (SUM)",
    "min": "Minimum (MIN)",
    "max": "Maximum (MAX)",
}


# ---------------------------------------------------------------------------
# Dynamische Achse (Bugfix 09.08.2026, Punkte 3/5/6)
# ---------------------------------------------------------------------------
def _pick_time_step(span: float, max_ticks: int) -> float:
    """Waelt einen 'sauberen' Zeit-Schritt (Sekunden) fuer den Bereich."""
    if span <= 0:
        return 0.0
    min_step = span / max(1, max_ticks)
    # 1s, 5s, 15s, 30s, 1m, 5m, 15m, 30m, 1h, 2h, 3h, 6h, 12h,
    # 1d, 2d, 1w, 2w, 1M, 3M, 6M, 1J
    steps = (1, 5, 15, 30, 60, 300, 900, 1800, 3600, 7200, 10800, 21600,
             43200, 86400, 172800, 604800, 1209600, 2592000, 7776000,
             15552000, 31536000)
    for s in steps:
        if s >= min_step:
            return float(s)
    return float(steps[-1])


def _time_ticks(min_val: float, max_val: float, step: float) -> List[float]:
    """Ganzzahlige Tick-Positionen (Vielfache von `step`) im Bereich."""
    if step <= 0:
        return []
    start = int(math.ceil(min_val / step)) * step
    out: List[float] = []
    v = start
    while v <= max_val + 1e-9:
        out.append(float(v))
        v += step
    return out


def _nice_int_step(span: float, max_ticks: int) -> float:
    """Waelt einen ganzzahligen Tick-Schritt (1,2,3,6,12,24,...) fuer den Bereich."""
    if span <= 0:
        return 1.0
    raw = span / max(1, max_ticks)
    for s in (1, 2, 3, 6, 12, 24, 48, 72, 168, 336, 730, 1460, 2920):
        if s >= raw:
            return float(s)
    return float(math.ceil(raw))


def _format_heatmap_value(val: Any) -> str:
    """Formatiert einen Heatmap-Zahlenwert OHNE Exponential-Notation.

    Bugfix 12.08.2026 (User-Meldung 'EXP-Wert in der Legende'):
    `f'{val:.2g}'` wechselt ab 100 in wissenschaftliche Notation
    ('1.2e+02'); `f'{v:g}'` ab 1e6 ('1e+06'). Ganzzahlige Werte
    (z. B. COUNT-Zaehler je Zelle/Bucket) werden in deutscher
    Tausender-Schreibweise ausgegeben ('4.380'), Bruchwerte (z. B.
    AVG/SUM/MIN/MAX) als Dezimalzahl ohne Nullen ('0.25', '62.5').
    """
    try:
        fval = float(val)
    except (TypeError, ValueError):
        return str(val)
    if not math.isfinite(fval):
        return str(val)
    if fval == int(fval) and abs(fval) < 1e15:
        return f"{int(fval):,}".replace(",", ".")
    return f"{fval:.2f}".rstrip("0").rstrip(".")


def _format_legend_value(val: Any, span: float) -> str:
    """Formatiert einen Legenden-Schwellwert mit adaptiver Genauigkeit.

    12.08.2026 (Bug 5): Bei kleinen Werte-Spannen kollabierten die
    Quartil-Schwellen der Legende unter der .2f-Rundung zu identischen
    Labels ('0.01 - 0.01' war unsinnig). Die Nachkommastellen-Zahl wird
    aus der Spanne abgeleitet, sodass die 25-%-Schritte (span/4) der
    Viridis-Legende GARANTIERT unterscheidbar bleiben. Ganzzahlige
    Schwellen ohne Nachkommastellen werden als Integer ausgegeben
    ('25'), Bruchwerte ohne Nullen ('0.0125', '0.02').
    """
    try:
        fval = float(val)
    except (TypeError, ValueError):
        return str(val)
    if not math.isfinite(fval):
        return str(val)
    if span is None or span <= 0:
        decimals = 2
    else:
        step = span / 4.0
        if step >= 1.0:
            decimals = 0
        else:
            decimals = int(math.ceil(-math.log10(step))) + 1
            decimals = max(0, min(decimals, 6))
    return f"{fval:.{decimals}f}".rstrip("0").rstrip(".")


class _HeatmapAxis(pg.AxisItem):
    """Achse mit dynamischen Ticks je Zoom-Level (Bugfix 09.08.2026).

    Die Achse traegt NATUERLICHE Werte (date -> Wanduhr-Epochs,
    hour/dow -> Ganzzahlen, kategorial -> Indizes) und formatiert die
    Tick-Beschriftung abhaengig vom sichtbaren Bereich:
      - date:  2 Formate je Zoom (TT.MM.JJ / HH:MM), 21.01 Bugfix 4 –
               1:1 mit der App-JS (Lightweight Charts tickMarkFormatter)
      - hour/dow: ganzzahlige Schritte, beim Zoom mehr Zwischenwerte
      - kategorial: Labels aus der zugehoerigen Liste
    """

    def __init__(self, orientation: str, **kwargs) -> None:
        super().__init__(orientation, **kwargs)
        self._dim: Optional[str] = None
        self._labels: List[str] = []
        # 09.08.2026 (User-Meldung): Kein automatisches SI-Prefix an das
        # Achsen-Label haengen. pyqtgraph wuerde bei date-Epochs (~1.7e9)
        # `setLabel(text)` (units=None -> leere Einheit) in den SI-Bereich
        # (1e9, inf) einsortieren und 'Datum (x1e+09)' anzeigen (das
        # 'EXP' in Klammern). Die Ticks werden ohnehin von tickStrings
        # mit echten Werten formatiert (Scale wird ignoriert) – das
        # Suffix waere also irrefuehrend.
        self.enableAutoSIPrefix(False)

    def configure(self, dim: str, labels: List[str]) -> None:
        """Setzt Dimension + Label-Liste (kategoriale Achsen)."""
        self._dim = str(dim or "")
        self._labels = list(labels or [])

    # ------------------------------------------------------------------
    def _clamped_scale_bounds(self, minVal, maxVal):
        """Clampt den sichtbaren Bereich auf die feste Skala (Meldungen 1+2).

        `hour` (Tageszeit) und `dow` (Wochentag) haben FESTE Skalen
        (0..24 bzw. 1..6, siehe `_axis_bounds`). Beim Rauszoomen (Mausrad)
        ragt der sichtbare Viewport ueber die Skala hinaus – die Ticks
        duerfen DANN nicht ausserhalb liegen (keine -/+ Werte ausserhalb
        00:00-23:59 bzw. Mo-Fr). Der Tick-Bereich wird daher auf die
        Skala geclampt. `date` bleibt unbegrenzt (datenbasiert); seit
        21.01 Bugfix 1 werden auch kategoriale Achsen (service_id/
        timeframe/symbol) auf 0..n-1 geclampt (keine Gespenster-Ticks
        -1/+2 ausserhalb des festen Wertebereichs, User-Meldung).
        """
        lo = float(minVal)
        hi = float(maxVal)
        if self._dim == "hour":
            lo = max(lo, 0.0)
            hi = min(hi, float(HOURS_PER_DAY))
        elif self._dim == "dow":
            lo = max(lo, 1.0)
            hi = min(hi, 1.0 + float(len(DOW_WEEK_LABELS)))
        elif self._dim not in ("date",):
            # 21.01 (Bugfix 1): Kategoriale Achsen haben einen FESTEN
            # Wertebereich 0..n-1 (n = Anzahl Labels). Beim Rauszoomen
            # (Mausrad) ragt der Viewport ueber die Skala hinaus - die
            # Ticks duerfen DANN nicht ausserhalb liegen.
            n = len(self._labels)
            lo = max(lo, -0.5)
            hi = min(hi, float(max(0, n)) - 0.5)
        return lo, hi

    def tickValues(self, minVal, maxVal, maxTicks=5):
        if not self._dim:
            return super().tickValues(minVal, maxVal, maxTicks)
        if self._dim == "date":
            # 20.02.01 (User-Meldung 2): LWC-v5-adaptierte Datums-Skala.
            # pyqtgraph uebergibt als dritten Parameter die ACHSEN-LAENGE in
            # Pixel (nicht die Tick-Anzahl!). Die Tick-Auswahl haelt den
            # Zielabstand _DATE_TARGET_PX ein: Zoom-In => feinere Variante,
            # Zoom-Out => groebere Variante; Jahr/Monat/Woche/Tag/Stunde/
            # Minute koexistieren als Hierarchie (per-Tick-Format in _format).
            return self._lwc_date_ticks(float(minVal), float(maxVal),
                                        float(maxTicks or 0))
        # 20.02.01 (User-Meldungen 1+2): hour/dow auf die feste Skala
        # geclampt – beim Rauszoomen bleibt der Bereich VOR/NACH der
        # Tagesstunden (bzw. der 5 Wochentage) leer. Das rechte Skalenende
        # (24 h bzw. Samstag 6) wird als halboffene Grenze ausgeschlossen,
        # damit kein Duplikat-Label ("00:00" an Position 24) entsteht.
        lo, hi = self._clamped_scale_bounds(minVal, maxVal)
        if hi <= lo:
            return []
        span = hi - lo
        step = _nice_int_step(span, int(maxTicks))
        start = int(math.ceil(lo / step)) * step
        values: List[float] = []
        v = float(start)
        while v < hi - 1e-9:
            values.append(v)
            v += step
        return [(step, values)]

    # ------------------------------------------------------------------
    # 20.02.01 (User-Meldung 2): LWC-v5-Datums-Ticks (Jahr/Monat/Woche/Tag/
    # Stunde/Minute-Hierarchie, Mindestabstand in Pixel)
    # ------------------------------------------------------------------
    def _lwc_date_ticks(self, lo: float, hi: float, axis_px: float):
        """Erzeugt die Datums-Ticks nach der LWC-v5-Selektionslogik.

        Der dritte Parameter von `tickValues` ist bei pyqtgraph die
        ACHSEN-LAENGE in Pixeln. Der Mindestabstand zweier Ticks in
        Sekunden ergibt sich aus `_DATE_TARGET_PX * span / axis_px` –
        dadurch bleiben die Labels ~80 px auseinander: Zoom-In => feinere
        Variante (Stunden/Minuten), Zoom-Out => groebere Variante (nur
        Jahr/Monat/Woche/Tag). Die Auswahl bevorzugt hoehere Weights
        (LWC `Q_`): Jahres-/Monatsmarken werden immer gesetzt, feinere
        Marken fuellen die Luecken.
        """
        # 21.03.20-Bugfix 5: Date-Epochs sind Wanduhr-Sekunden seit 1970
        # (positiv). Negative/riesige Werte (z. B. zusammengefallener
        # Auto-Range nach 'Keine Daten' -> [-0.5, 0.5]) wuerden in
        # _date_marks zu datetime.fromtimestamp(-86400) fuehren und auf
        # Windows/Python 3.14 OSError 22 werfen. Clampen verhindert das.
        lo = max(0.0, float(lo))
        hi = max(0.0, float(hi))
        span = hi - lo
        if span <= 0:
            return []
        if axis_px <= 0 or not math.isfinite(axis_px):
            axis_px = 800.0
        min_gap_sec = _DATE_TARGET_PX * span / axis_px
        min_gap_sec = max(1.0, min_gap_sec)
        marks = self._date_marks(lo, hi, min_gap_sec)
        epochs = self._select_date_marks(marks, min_gap_sec)
        if not epochs:
            return []
        return [(min_gap_sec, epochs)]

    def _date_marks(self, lo: float, hi: float,
                    min_gap_sec: float) -> List[tuple]:
        """Kandidaten-Marken der Datums-Achse (Epoch, Weight).

        Tages-Marken (Mitternacht, Wanduhr-UTC) mit Weight nach Datum:
        70 = 1. Januar (Jahreswechsel), 60 = 1. des Monats (Monatswechsel),
        55 = Montag (ISO-Wochenanfang), 50 = sonstiger Tag. Bei engem
        Zoom zusaetzlich Stunden-Marken (30) und Minuten-Marken (20) –
        die Generierung ist ueber die sichtbare Spanne begrenzt
        (Minuten nur bei < 2 Tagen, Stunden nur bei < 60 Tagen), damit
        die Kandidatenanzahl klein bleibt.
        """
        marks: List[tuple] = []
        d0 = int(math.floor(lo / _DAY_SECONDS)) * _DAY_SECONDS
        d1 = int(math.floor(hi / _DAY_SECONDS)) * _DAY_SECONDS
        d = d0
        while d <= d1:
            # 21.03.20-Bugfix 5: fromtimestamp kann auf Windows OSError 22
            # fuer ungueltige (negative/riesige) Epochs werfen - ungueltige
            # Marken ueberspringen statt zu crashen.
            try:
                dt = datetime.fromtimestamp(d, tz=dt_timezone.utc)
            except (OSError, ValueError, OverflowError):
                d += _DAY_SECONDS
                continue
            if dt.month == 1 and dt.day == 1:
                w = 70
            elif dt.day == 1:
                w = 60
            elif dt.weekday() == 0:
                w = 55
            else:
                w = 50
            marks.append((d, w))
            d += _DAY_SECONDS
        if min_gap_sec < _DAY_SECONDS and (hi - lo) <= 60 * _DAY_SECONDS:
            h0 = int(math.floor(lo / 3600.0)) * 3600
            h1 = int(math.floor(hi / 3600.0)) * 3600
            h = h0
            while h <= h1:
                if h % _DAY_SECONDS != 0:  # Mitternacht = Tages-Marke
                    marks.append((h, 30))
                h += 3600
        if min_gap_sec < 3600.0 and (hi - lo) <= 2 * _DAY_SECONDS:
            m0 = int(math.floor(lo / 60.0)) * 60
            m1 = int(math.floor(hi / 60.0)) * 60
            m = m0
            while m <= m1:
                if m % 3600 != 0:  # Stunde = Stunden-Marke
                    marks.append((m, 20))
                m += 60
        marks.sort(key=lambda x: x[0])
        return marks

    @staticmethod
    def _select_date_marks(marks: List[tuple],
                           min_gap_sec: float) -> List[float]:
        """LWC-v5-Selektion (Q_): Weight absteigend, Mindestabstand.

        Hoehere Weights (Jahr/Monat) werden bevorzugt gesetzt; feinere
        Marken werden nur uebernommen, wenn sie mindestens `min_gap_sec`
        von den bereits gewaehlten Marken entfernt sind. Ergebnis: die
        gewohnte Hierarchie (Jahreszahl + Monatswechsel + Tage) mit
        garantierter Mindest-Pixeldistanz (keine Ueberlappung, keine
        Riesensprünge).
        """
        by_weight: Dict[int, List[float]] = {}
        for epoch, weight in marks:
            by_weight.setdefault(int(weight), []).append(float(epoch))
        selected: List[float] = []
        for weight in sorted(by_weight.keys(), reverse=True):
            s = selected
            out: List[float] = []
            r = 0
            e = len(s)
            a = float("inf")
            o = float("-inf")
            for idx in by_weight[weight]:
                while r < e and s[r] < idx:
                    out.append(s[r])
                    o = s[r]
                    r += 1
                if r < e:
                    a = s[r]
                if a - idx >= min_gap_sec and idx - o >= min_gap_sec:
                    out.append(idx)
                    o = idx
            while r < e:
                out.append(s[r])
                r += 1
            selected = out
        return selected

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            out.append(self._format(float(v), float(spacing)))
        return out

    # ------------------------------------------------------------------
    def _format(self, v: float, spacing: float) -> str:
        if self._dim == "date":
            # 21.01 (Bugfix 4 + Runde 3, 11.08.2026): Datums-Format:
            #   - Tages-/Monats-/Jahres-Marken (Mitternacht) -> 'Mo. 12.06.26'
            #     (Runde 3: Wochentag + Datum, User-Wunsch wie chart_win)
            #   - Stunden-/Minuten-Marken (Sub-Tag)          -> 'HH:MM'
            # Die urspruengliche 5-Format-Weight-Hierarchie (Jahreszahl
            # '2026', Monatskuerzel 'Feb 26', ISO-Woche '08.25') ist ersetzt.
            # Wanduhr-Garantie via UTC-Darstellung der (Wanduhr-encoded)
            # Epoch (Invariante 7, KEIN Berlin-Offset). `weekday()`:
            # 0=Mo..6=So -> Index in die deutschen Wochentage.
            dt = datetime.fromtimestamp(v, tz=dt_timezone.utc)
            if dt.hour != 0 or dt.minute != 0 or dt.second != 0:
                return f"{dt.hour:02d}:{dt.minute:02d}"  # Sub-Tag '14:30'
            days = ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So.")
            return (f"{days[dt.weekday()]} {dt.day:02d}.{dt.month:02d}."
                    f"{dt.year % 100:02d}")
        if self._dim == "hour":
            # 20.02.01 (User-Meldung 1): KEIN `% 24`-Wrap mehr – Werte
            # ausserhalb der festen Skala 00:00-23:59 werden leer gelassen
            # (das tickValues-Clamping verhindert sie bereits; defensiv).
            vv = int(round(v))
            if 0 <= vv < HOURS_PER_DAY:
                return f"{vv:02d}:00"
            return ""
        if self._dim == "dow":
            idx = int(round(v))
            if 1 <= idx <= len(DOW_WEEK_LABELS):
                return DOW_WEEK_LABELS[idx - 1]
            return ""
        # Kategorial (timeframe/service_id/symbol): Labels aus der Liste.
        idx = int(round(v))
        if 0 <= idx < len(self._labels):
            # E16 (11.08.2026, Bugfix 2): Kategoriale Labels an JEDEM '/'
            # mit '\n' umbrechen (z.B. 'SILVER / M1' -> zwei Zeilen) statt
            # zu kappen – pyqtgraph rendert mehrzeilige Tick-Labels korrekt.
            # Betrifft X- und Y-Achse (dieselbe _format-Methode).
            label = str(self._labels[idx])
            if "/" in label:
                label = label.replace("/", "/\n")
            return label
        # 21.01 (Bugfix 1): Ausserhalb des festen Wertebereichs -> leer
        # (das tickValues-Clamping verhindert sie bereits; defensiv).
        return ""


class HeatmapWidget(QWidget):
    """Generische 2D-Heatmap mit Confluence-Matrix, Zoom & Candle-Overlay."""

    # 21.01 (E7, 11.08.2026): Das Signal bleibt als Vertrag erhalten, wird
    # aber NICHT mehr emittiert – die Smart-Presets laufen ausschliesslich
    # ueber das 'Ansicht'-Dropdown der HeatmapPage (keine Preset-Buttons).
    preset_clicked = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None
        self._n_cols = 0
        self._n_rows = 0
        self._x_axis: List[float] = []      # natuerliche X-Koordinaten je Spalte
        self._y_axis: List[float] = []      # natuerliche Y-Koordinaten je Zeile
        self._x_dates: List[Any] = []       # Datum je Spalte (nur X=date)
        self._x_min = -0.5
        self._x_max = 0.5
        self._y_min = -0.5
        self._y_max = 0.5
        self._candle_items: List[Any] = []
        self._colormap_mode = _VIRIDIS
        self._syncing = False
        # 20.03.03 (Q2): Key -> aktive Quellen-Services aus dem Payload
        # (`field_sources`) fuer die ALL-Expansion der Sammel-Eintraege.
        self._field_sources: Dict[str, List[str]] = {}
        # Runde 8 (Bugfix 3/4, 10.08.2026): Cache der zuletzt verfuegbaren
        # Feld-Keys (Payload-Metadaten) - Grundlage des SYNCHRONEN
        # Feld-Dropdown-Rebuilds (_rebuild_field_dropdown) ohne
        # Query-Round-Trip. Wird bei jedem Daten-Payload aktualisiert;
        # _sync_from_params/feature_ids_changed bauen daraus Items/Haken.
        self._field_keys: List[str] = []
        # Runde 11 (Bug 4, B4-2): Cache der No-Data-Varianten aus dem
        # QUERY_FEATURES-Payload. None = noch kein Payload (Loading);
        # [] = Erfolg ohne Varianten; Liste = Erfolg mit Varianten.
        # `_no_data_variants_error` markiert einen fehlgeschlagenen
        # No-Data-Check (Payload-Vertrag B4-2, 'Pruefung fehlgeschlagen').
        self._no_data_variants: Optional[List[Dict[str, Any]]] = None
        self._no_data_variants_error: bool = False

        # --- Steuerung (Zeile 1: Dimensionen/Aggregation/Feld) ---
        self._combo_x = QComboBox()
        # 20.02.01 (E8): Mindestbreite erhoeht (laengere Achsen-Beschriftungen).
        self._combo_x.setMinimumWidth(160)
        for d in HEATMAP_DIMENSIONS:
            self._combo_x.addItem(_DIM_LABELS.get(d, d), d)
        self._combo_y = QComboBox()
        self._combo_y.setMinimumWidth(160)
        for d in HEATMAP_DIMENSIONS:
            self._combo_y.addItem(_DIM_LABELS.get(d, d), d)
        self._combo_agg = QComboBox()
        for a in HEATMAP_AGGREGATIONS:
            self._combo_agg.addItem(_AGG_LABELS.get(a, a), a)
        # 21.03.20 (Analytics Modus-Filter): Modus-Dropdown fuer
        # Multi-Modus-Services (srv_swing_*/srv_trend_* schreiben
        # `source_mode` top-level in jedes feature_data-Record).
        # Wird aus dem QUERY_FEATURES-Payload befuellt
        # (`source_modes` + `has_source_mode_services`);
        # "[Alle Modi]" (data "all") = kein Filter. Deaktiviert,
        # wenn KEIN aktiver Service source_mode schreibt.
        self._combo_mode_filter = QComboBox()
        self._combo_mode_filter.addItem("[Alle Modi]", "all")
        self._combo_mode_filter.setMinimumWidth(150)
        self._combo_mode_filter.setSizeAdjustPolicy(
            QComboBox.AdjustToContents)
        self._combo_mode_filter.setToolTip(
            "Modus-Filter: grenzt die Daten auf einen source_mode "
            "der Multi-Modus-Services ein (global fuer Tabelle, "
            "Heatmaps, Scatter, Verteilung).")
        # 20.03.02 (F1c/F7): 'Feld' ist ein CheckableComboBox – die
        # Multi-Auswahl steuert den Datenquellen-Filter `feature_ids`, die
        # Aggregation nutzt genau EIN aktives Hauptfeld (currentData). Bei
        # COUNT/CONFLUENCE_COUNT bleibt die Auswahl deaktiviert (F7,
        # _update_controls).
        self._combo_field = CheckableComboBox()
        # 20.02.01 (User-Meldung 3a): 'Feld' deutlich laenger (Eintraege
        # tragen seit Meldung 3b den Service-Prefix '{Service} / {Key}').
        self._combo_field.setMinimumWidth(320)
        # Runde 16 (Bugfix 3, 11.08.2026): Kein MaximumWidth mehr - das
        # Feld-Dropdown darf in der Zoom-Y-Zeile bis zum Canvas-Ende
        # wachsen (Expanding-Policy + Layout-Stretch).
        self._combo_field.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Popup-Dropdown an den laengsten Eintrag anpassen (vollstaendige
        # '{Service} / {Key}'-Texte sichtbar statt Ellipsis).
        self._combo_field.setSizeAdjustPolicy(QComboBox.AdjustToContents)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("X-Achse:"))
        ctrl.addWidget(self._combo_x)
        ctrl.addWidget(QLabel("Y-Achse:"))
        ctrl.addWidget(self._combo_y)
        # 21.01 (E7, 11.08.2026): Die 4 Smart-Preset-Buttons wurden
        # ENTFERNT – die Presets sind ausschliesslich ueber das
        # 'Ansicht'-Dropdown der HeatmapPage erreichbar (heatmap_page.py,
        # _combo_mode / _apply_selected_preset).
        ctrl.addStretch(1)

        # --- Steuerung (Zeile 2: Overlay + Zoom) ---
        self._chk_candle = QCheckBox("Kerzen-Overlay")
        # 12.08.2026 (User-Meldung 4, 'Anzeigebalken ca. 18h breit'):
        # TF-Anzeige des Kerzen-Overlays - der Nutzer sieht, welcher
        # Timeframe die Kerzenbreite bestimmt (z. B. 'D1' -> 16,8h-Kerzen).
        self._label_overlay_tf = QLabel("")
        self._label_overlay_tf.setStyleSheet(
            "color: #808080; font-size: 11px;")
        self._label_overlay_tf.setToolTip(
            "Timeframe des Kerzen-Overlays - bestimmt die Kerzenbreite "
            "(bar_sec * 0.7). Wird aus den OHLCV-Overlay-Daten gelesen.")
        self._slider_zoom_x = QSlider(Qt.Horizontal)
        self._slider_zoom_y = QSlider(Qt.Horizontal)
        self._label_info = QLabel("")
        self._label_info.setStyleSheet("color: #808080;")
        for s in (self._slider_zoom_x, self._slider_zoom_y):
            s.setRange(5, 100)
            # 09.08.2026 (User-Meldung 2): Richtung getauscht – rechts
            # (hoher Wert) = Zoom-In, links (niedriger Wert) = Zoom-Out.
            # 5 = volle Achse (links), 100 = maximale Vergroesserung (rechts).
            s.setValue(5)
            s.setEnabled(False)
            s.setToolTip("Viewport-Zoom (zentriert): rechts = Zoom-In, "
                         "links = Zoom-Out.")

        # 21.03.20-Bugfix 1+2: Zwei-zeiliges QGridLayout. Zeile 0 traegt die
        # Werteanzeige (_label_info) EINE ZEILE UEBER der Steuerleiste,
        # linksbuendig auf Hoehe des Feld-Dropdowns (Spalte des 'Feld:'-
        # Labels). Bug 2: Modus-Dropdown steht JETZT VOR der Aggregation.
        # 'Feld' (Stretch 1) waechst weiterhin bis zum Canvas-Ende.
        ctrl2 = QGridLayout()
        ctrl2.setHorizontalSpacing(6)
        ctrl2.setVerticalSpacing(2)
        _c = 0
        ctrl2.addWidget(self._chk_candle, 1, _c); _c += 1
        ctrl2.addWidget(self._label_overlay_tf, 1, _c); _c += 1
        ctrl2.addWidget(QLabel("Zoom X:"), 1, _c); _c += 1
        ctrl2.addWidget(self._slider_zoom_x, 1, _c); _c += 1
        ctrl2.addWidget(QLabel("Zoom Y:"), 1, _c); _c += 1
        ctrl2.addWidget(self._slider_zoom_y, 1, _c); _c += 1
        # Runde 16 (Bugfix 2/3, 11.08.2026): Aggregation + Feld sind aus
        # Zeile 1 in die Zoom-Y-Zeile gewandert (rechts neben Zoom Y, mit
        # Abstand; 'Feld' stretcht bis zum Canvas-Ende).
        ctrl2.addWidget(QWidget(), 1, _c); _c += 1
        ctrl2.setColumnMinimumWidth(_c - 1, 15)
        # 21.03.20-Bugfix 2: Modus-Dropdown VOR der Aggregation (Tausch).
        ctrl2.addWidget(QLabel("Modus:"), 1, _c); _c += 1
        ctrl2.addWidget(self._combo_mode_filter, 1, _c); _c += 1
        ctrl2.addWidget(QLabel("Aggregation:"), 1, _c); _c += 1
        ctrl2.addWidget(self._combo_agg, 1, _c); _c += 1
        ctrl2.addWidget(QLabel("Feld:"), 1, _c); _c += 1
        _field_col = _c
        ctrl2.addWidget(self._combo_field, 1, _c); _c += 1
        ctrl2.setColumnStretch(_field_col, 1)
        # 21.03.20-Bugfix 1: Werteanzeige eine Zeile ueber der Steuerleiste
        # (linksbuendig auf Hoehe des Feld-Dropdowns) - die Zeile bleibt
        # ruhiger, weil das Label nicht mehr rechts am Ende wackelt.
        ctrl2.addWidget(self._label_info, 0, _field_col,
                        1, 1, Qt.AlignLeft)

        # --- Plot: Heatmap + Kerzen-Overlay im SELBEN Canvas (Bugfix 1) ---
        self._plot_hm = pg.PlotWidget()
        self._plot_hm.setBackground("w")
        # Dynamische Achsen (Bugfix 5+6): Ticks je Zoom-Level.
        self._axis_x = _HeatmapAxis("bottom")
        self._axis_y = _HeatmapAxis("left")
        self._plot_hm.plotItem.setAxisItems(
            {"bottom": self._axis_x, "left": self._axis_y})
        self._image = pg.ImageItem()
        # 21.01 (E8, 11.08.2026): pyqtgraph rendert ImageItem-Daten per
        # Default TRANSPONIERT (axisOrder='col-major') – die (rows=Services,
        # cols=Zeiten)-Matrix erschien dadurch als N duenne Y-Streifen
        # (Screenshot-Kritik Punkt 1). row-major legt die Daten 1:1 auf die
        # Zellen (Zeile = Y-Zeile = Service, Spalte = X = Zeitpunkt).
        self._image.setOpts(axisOrder="row-major")
        self._plot_hm.addItem(self._image)
        self._cmap_viridis = pg.colormap.get(_VIRIDIS)
        self._cmap_confluence = pg.ColorMap(
            pos=_CONFLUENCE_POS, color=_CONFLUENCE_COLORS)
        self._image.setColorMap(self._cmap_viridis)
        self._colorbar = pg.ColorBarItem(
            colorMap=self._cmap_viridis, values=(0.0, 1.0))
        self._colorbar.setImageItem(self._image)

        # 21.01 (Bugfix 2, 11.08.2026): Diskrete Schwellwert-Legende oben
        # rechts auf der Grafik (User: 'welche Farbe bedeutet was?'; spaeter
        # konfigurierbar). Wird in _update_legend je Aggregation befuellt.
        self._legend = pg.LegendItem(
            offset=(-10, 10), labelTextColor="k",
            pen=pg.mkPen("#b0b0b0"), brush=pg.mkBrush(255, 255, 255, 210))
        self._legend.setParentItem(self._plot_hm.plotItem)
        self._legend.hide()
        # 21.01 (Bugfix 3, 11.08.2026): Fadenkreuz wie im Chartfenster
        # (LWC-Crosshair) - zwei gestrichelte InfiniteLine, folgen dem
        # Mauszeiger ueber der Heatmap (sigMouseMoved).
        self._cross_x = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen("#808080", width=1, style=Qt.DashLine))
        self._cross_y = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen("#808080", width=1, style=Qt.DashLine))
        self._cross_x.setZValue(20)
        self._cross_y.setZValue(20)
        self._cross_x.setVisible(False)
        self._cross_y.setVisible(False)
        self._plot_hm.addItem(self._cross_x, ignoreBounds=True)
        self._plot_hm.addItem(self._cross_y, ignoreBounds=True)
        self._plot_hm.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # 21.03.11 (Bug 5): Zwei-Wege-Sync der Zoom-Slider - Maus-Zoom
        # (Mausrad/Drag) auf der Heatmap-ViewBox muss die X-/Y-Slider
        # mitbewegen (bisher nur einseitig Slider -> Range). Die Handler
        # aktualisieren Slider + VM-Params (blockSignals/_syncing-Guard
        # verhindern Endlos-Schleifen).
        self._plot_hm.plotItem.vb.sigXRangeChanged.connect(
            self._on_heatmap_x_range_changed)
        self._plot_hm.plotItem.vb.sigYRangeChanged.connect(
            self._on_heatmap_y_range_changed)

        # 21.01 (Bugfix-Runde 3, Entscheidung 2a, 11.08.2026): Senkrechte
        # Teiler je Dateneinheit (Bar-Intervall des TFs, z. B. H1 -> jede
        # Stunde). Als EIN PlotCurveItem mit connect='pairs' (schnell),
        # ueber der Heatmap aber unter dem Candle-Overlay (price_vb 10).
        self._grid_lines = pg.PlotCurveItem(
            connect="pairs", pen=pg.mkPen("#c0c0c0", width=1))
        self._grid_lines.setZValue(5)
        self._grid_lines.setVisible(False)
        self._plot_hm.addItem(self._grid_lines)

        # Kerzen-Overlay: zweite Y-Achse (Preis) rechts im selben Canvas,
        # ViewBox teilt die X-Achse mit der Heatmap (Bugfix 1).
        self._plot_hm.showAxis("right")
        self._plot_hm.getAxis("right").setLabel("Preis")
        self._price_vb = pg.ViewBox()
        self._plot_hm.scene().addItem(self._price_vb)
        self._plot_hm.getAxis("right").linkToView(self._price_vb)
        self._price_vb.setXLink(self._plot_hm.plotItem.vb)
        self._price_vb.setZValue(10)  # ueber der Heatmap zeichnen
        self._price_vb.setVisible(False)
        self._plot_hm.getAxis("right").setVisible(False)
        # 10.08.2026 (Bugfix Runde 7, Bug 1): Zweite untere Preis-Achse fuer
        # horizontale Candles, wenn 'Datum' auf der Y-Achse liegt (die
        # regulare untere Achse traegt dann die X-Dimension).
        self._price_axis_bottom = pg.AxisItem("bottom",
                                              parent=self._plot_hm.plotItem)
        self._price_axis_bottom.setLabel("Preis")
        self._plot_hm.plotItem.layout.addItem(self._price_axis_bottom, 4, 1)
        self._price_axis_bottom.linkToView(self._price_vb)
        self._price_axis_bottom.setVisible(False)
        self._plot_hm.plotItem.vb.sigResized.connect(self._update_price_view)

        lay = QVBoxLayout(self)
        lay.addLayout(ctrl)
        lay.addLayout(ctrl2)
        lay.addWidget(self._plot_hm, 1)

        # --- Signale ---
        self._combo_x.currentIndexChanged.connect(self._on_config_changed)
        self._combo_y.currentIndexChanged.connect(self._on_config_changed)
        self._combo_agg.currentIndexChanged.connect(self._on_agg_changed)
        # 21.03.20 (Analytics Modus-Filter): Aenderung im Modus-
        # Dropdown -> globaler ViewModel-Refresh (alle Datenquellen).
        self._combo_mode_filter.currentIndexChanged.connect(
            self._on_mode_filter_changed)
        self._combo_field.currentIndexChanged.connect(self._on_config_changed)
        # 20.03.02 (F1c): CheckState-Wechsel im 'Feld'-Dropdown -> Filter.
        # 21.03.15 (Bug 1): Die Verbindung ist WIEDER AKTIV - Check/Uncheck
        # im 'Feld'-Dropdown schreibt feature_ids ueber den bestehenden
        # ServicePicker-Pfad (`_on_field_selection_changed` ->
        # `_reconcile_sammel_checks` -> `_checked_field_service_ids` ->
        # `set_feature_ids`), damit ServicePicker-Auswahl und Feld-Dropdown
        # konsistent bleiben.
        self._combo_field.selection_changed.connect(
            self._on_field_selection_changed)
        self._chk_candle.toggled.connect(self._on_candle_toggled)
        self._slider_zoom_x.valueChanged.connect(self._on_zoom_x_changed)
        self._slider_zoom_y.valueChanged.connect(self._on_zoom_y_changed)

    # ------------------------------------------------------------------
    # MVVM-Anbindung (von der HeatmapPage gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        self._view_model = view_model
        view_model.data_ready.connect(self._on_data_ready)
        # Runde 11 (Architektur, A3): KEINE direkte params_restored-
        # Verbindung mehr - das AnalyticsWindow orchestriert den Seiten-Sync
        # zentral via _sync_all_pages_from_params() (genau EIN Durchgang
        # nach dem VM-Param-Setzen). _sync_from_params() wird vom Window
        # explizit aufgerufen (heatmap_page._generic). Die Initial-Sync
        # unten (self._sync_from_params()) bleibt fuer den Attach-Zeitpunkt.

        # Runde 8 (Bugfix 4): feature_ids-Aenderungen (ServicePicker
        # Check/Uncheck) -> das 'Feld'-Dropdown wird SOFORT synchron neu
        # abgeleitet (kein Debounce/Query-Round-Trip). Defensiv per hasattr
        # (Test-Mocks ohne Signal).
        if hasattr(view_model, "feature_ids_changed"):
            view_model.feature_ids_changed.connect(
                self._on_feature_ids_changed)
        # Runde 11 (Bug 4, B4-2): Fehlerzustand des No-Data-Checks
        # (QUERY_FEATURES) -> 'Pruefung fehlgeschlagen'-Hinweis im
        # Feld-Dropdown (Payload-Vertrag; vorher verschluckte Fehler).
        if hasattr(view_model, "query_failed"):
            view_model.query_failed.connect(self._on_query_failed)
        self._sync_from_params()

    def is_candle_projection_enabled(self) -> bool:
        """True, wenn das Kerzen-Overlay aktiviert ist (E9)."""
        return self._chk_candle.isChecked()

    def request_data(self) -> None:
        """Fordert generische Heatmap (+ OHLCV-Overlay bei Overlay) an.

        21.01 (Bugfix 5, 11.08.2026): Das Overlay laedt den OHLCV-Snapshot
        IM HEATMAP-TIMEFRAME (adaptiv fuer alle TFs) statt der festen
        Tages-Aggregation (fetch_daily_ohlc).

        Runde 15 (Ultra-Low-Latency, Fix 1): QUERY_FEATURES wird VOR der
        Grafik in die Puffer-Queue gelegt – der leichte Metadaten-Pfad
        (Reader-Cache, KEIN Heatmap-Pivot) fuellt das 'Feld'-Dropdown und
        die '(No Data)'-Hinweise, waehrend die teure Pivot-Aggregation
        danach in einem separaten Worker laeuft. Das Dropdown blockiert
        damit nicht mehr mehrere Sekunden auf der Grafik.
        """
        if self._view_model is None:
            return
        self._view_model.request_features()
        self._view_model.request_heatmap_generic()
        # Runde 12 (Option A): Zusaetzlich kommen die No-Data-Varianten im
        # QUERY_HEATMAP_GENERIC-Payload (Konsistenz nach dem Render).
        # 21.01 (Bugfix 5): Overlay-Bars im Heatmap-TF (OHLCV-Snapshot).
        if self._chk_candle.isChecked():
            self._view_model.request_ohlcv_snapshot()

    # ------------------------------------------------------------------
    # Sync aus den ViewModel-_params (Profil/Workspace-Restore)
    # ------------------------------------------------------------------
    def _sync_from_params(self) -> None:
        if self._view_model is None:
            return
        p = self._view_model.params
        self._syncing = True
        try:
            self._set_combo_data(
                self._combo_x, str(p.get("heatmap_x_dim") or "date"))
            self._set_combo_data(
                self._combo_y, str(p.get("heatmap_y_dim") or "hour"))
            self._set_combo_data(
                self._combo_agg,
                str(p.get("heatmap_agg") or "confluence_count"))
            # 21.03.20 (Analytics Modus-Filter): Modus-Auswahl aus
            # den VM-Params wiederherstellen (Profil-/Workspace-
            # Restore; unbekannte Werte werden additiv ergaenzt).
            self._set_combo_data(
                self._combo_mode_filter,
                str(p.get("service_mode") or "all"))
            # Runde 8 (Bugfix 3): Das 'Feld'-Dropdown wird aus den gecachten
            # Feld-Metadaten (self._field_keys/self._field_sources) + den
            # aktuellen VM-Params SYNCHRON neu abgeleitet (Items, Haken,
            # Current). Ein restaurierter heatmap_field bleibt dadurch auch
            # ohne frischen Daten-Payload sichtbar (Fallback-Roh-Item, wenn
            # noch keine Payload-Metadaten vorliegen).
            self._rebuild_field_dropdown(self._field_keys,
                                         self._field_sources)
            # 21.01 (User-Meldung 5, 11.08.2026): Das Kerzen-Overlay wird
            # NUR wiederhergestellt, wenn die X-Achse = 'date' ist. Bei
            # Y=date/anderen Achsen bleibt die Checkbox aus (verhindert
            # ein ungewolltes Dirty-Setzen via _update_controls beim
            # Profil-/Workspace-Restore).
            self._chk_candle.setChecked(bool(
                p.get("candle_projection_enabled"))
                and str(p.get("heatmap_x_dim") or "date") == "date")
            self._set_zoom_slider(self._slider_zoom_x,
                                  p.get("zoom_x_range") or [0.0, 1.0])
            self._set_zoom_slider(self._slider_zoom_y,
                                  p.get("zoom_y_range") or [0.0, 1.0])
        finally:
            self._syncing = False
        self._update_controls()

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        """Setzt die Combo auf `value` (fuegt unbekannte Werte additiv hinzu)."""
        combo.blockSignals(True)
        try:
            idx = combo.findData(value)
            if idx < 0:
                combo.addItem(str(value), value)
                idx = combo.count() - 1
            combo.setCurrentIndex(idx)
        finally:
            combo.blockSignals(False)

    @staticmethod
    def _set_zoom_slider(slider: QSlider, zrange: Any) -> None:
        """Stellt den Zoom-Slider aus einem [lo, hi]-Bereich ein (E8).

        09.08.2026 (User-Meldung 2): Inverse Umrechnung zu `_set_zoom_range`
        – volle Achse (span 1.0) => Slider 5 (links), maximale Vergroesserung
        (span 0.05) => Slider 100 (rechts).
        """
        try:
            lo, hi = float(zrange[0]), float(zrange[1])
        except (TypeError, ValueError, IndexError):
            lo, hi = 0.0, 1.0
        if hi <= lo:
            lo, hi = 0.0, 1.0
        value = int(round(105.0 - (hi - lo) * 100.0))
        slider.blockSignals(True)
        slider.setValue(max(slider.minimum(), min(slider.maximum(), value)))
        slider.blockSignals(False)

    def _update_controls(self) -> None:
        """Aktiviert/Deaktiviert Feld-Combo und Overlay (E6/E9).

        Bugfix 09.08.2026 (Punkt 6): Die Zoom-Slider gelten fuer ALLE
        Dimensionen/Massstaebe (nicht nur date) – je Zoom-Level werden
        dynamisch mehr Zwischenwerte auf den Achsen angezeigt.
        """
        if self._view_model is None:
            return
        x_dim = str(self._combo_x.currentData() or "")
        y_dim = str(self._combo_y.currentData() or "")
        agg = str(self._combo_agg.currentData() or "")
        self._slider_zoom_x.setEnabled(True)
        self._slider_zoom_y.setEnabled(True)
        is_value_agg = agg in _VALUE_AGGS
        # 13.08.2026 (Punkt 5, F5): SUM fuer preisartige Felder sperren
        # (unsinnig hohe Legendenwerte); Signal-Felder (strength_value)
        # bleiben erlaubt. Ist SUM gerade aktiv und das Feld preisartig,
        # wird implizit auf AVG gewechselt (VM-Config + Refresh idempotent).
        active_field = self._field_key(self._combo_field.currentData())
        # 13.08.2026 (Punkt 5, F5): Modul-Funktion (kein self.) - die
        # Helfer ist als reine Funktion definiert (SRP, kein Widget-Zustand).
        price_like = _is_price_like_key(active_field)
        sum_idx = self._combo_agg.findData("sum")
        if sum_idx >= 0:
            _sum_item = self._combo_agg.model().item(sum_idx)
            if _sum_item is not None:
                _sum_item.setEnabled(not price_like)
        if price_like and agg == "sum":
            self._set_combo_data(self._combo_agg, "avg")
            agg = "avg"
            is_value_agg = True
            self._apply_config()
        self._combo_field.setEnabled(is_value_agg)
        if is_value_agg:
            self._combo_field.setToolTip(
                "Numerischer feature_data-JSON-Key (Feld) fuer AVG/SUM/MIN/MAX.")
        else:
            self._combo_field.setToolTip(
                "Nur fuer AVG/SUM/MIN/MAX relevant (E6); COUNT/CONFLUENCE "
                "ignorieren das Feld.")
        # 21.01 (User-Meldung 5, 11.08.2026): Das Kerzen-Overlay ist NUR
        # bei X-Achse = 'date' aktivierbar (Y=date/vertikale Anordnungen
        # sind keine offiziellen Ansichten mehr). Bei Y=date wird die
        # Checkbox hier deaktiviert und zurueckgesetzt (Restore-Fall).
        date_on_x = x_dim == "date"
        can_overlay = date_on_x
        self._chk_candle.setEnabled(can_overlay)
        if can_overlay:
            self._chk_candle.setToolTip(
                "Tages-Ohlc ueber der Heatmap (gleicher Canvas), "
                "Datum auf der X-Achse.")
        else:
            self._chk_candle.setToolTip(
                "Kerzen-Overlay nur mit 'Datum' auf der X-Achse "
                "verfuegbar.")
            # Meldung 5: Reste eines Overlays entfernen (loest
            # _on_candle_toggled(False) aus -> set_candle_projection(False)
            # + _clear_overlay im ViewModel/Widget).
            if self._chk_candle.isChecked():
                self._chk_candle.setChecked(False)
        # Meldung 5: Der Overlay-Link folgt NUR noch der X-Achse (date).
        # Ohne Overlay werden beide Links entfernt.
        link = can_overlay and self._chk_candle.isChecked()
        linked_x = self._price_vb.linkedView(pg.ViewBox.XAxis)
        linked_y = self._price_vb.linkedView(pg.ViewBox.YAxis)
        if link and linked_x is None:
            self._price_vb.setXLink(self._plot_hm.plotItem.vb)
        if link and linked_y is not None:
            self._price_vb.setYLink(None)
        if not link:
            if linked_x is not None:
                self._price_vb.setXLink(None)
            if linked_y is not None:
                self._price_vb.setYLink(None)

    # ------------------------------------------------------------------
    # Konfiguration -> ViewModel (Debounce -> Worker)
    # ------------------------------------------------------------------
    def _on_config_changed(self, *args) -> None:
        if self._syncing or self._view_model is None:
            return
        # Identische Achsen vermeiden (degenerierte Diagonal-Matrix).
        if self._combo_x.currentData() == self._combo_y.currentData():
            self._syncing = True
            try:
                fallback = ("hour" if self._combo_x.currentData() != "hour"
                            else "dow")
                self._set_combo_data(self._combo_y, fallback)
            finally:
                self._syncing = False
        # Overlay nur bei X=date (E9 / 21.01 User-Meldung 5) – sonst
        # ausschalten (Y=date ist keine offizielle Overlay-Ansicht mehr).
        if (self._combo_x.currentData() != "date"
                and self._chk_candle.isChecked()):
            self._chk_candle.setChecked(False)
        self._update_controls()
        self._apply_config()
        self.request_data()

    def _on_agg_changed(self, *args) -> None:
        if self._syncing or self._view_model is None:
            return
        self._update_controls()
        self._apply_config()
        self.request_data()

    def _on_mode_filter_changed(self, *args) -> None:
        """21.03.20: Modus-Filter-Aenderung -> ViewModel (global).

        `set_service_mode` stoesst intern den Refresh von
        QUERY_FEATURES + allen Datenquellen an (Tabelle, beide
        Heatmaps, Scatter, Verteilung - Entscheidung 1). Der
        _syncing-Guard verhindert Endlos-Schleifen.
        """
        if self._syncing or self._view_model is None:
            return
        mode = str(self._combo_mode_filter.currentData() or "all")
        self._view_model.set_service_mode(mode)

    def _apply_config(self) -> None:
        self._view_model.set_heatmap_config(
            x_dim=str(self._combo_x.currentData() or "date"),
            y_dim=str(self._combo_y.currentData() or "hour"),
            # 20.03.02 (F2): Aus dem '{service_id}|{key}'-userData nur den
            # JSON-Key extrahieren (heatmap_field bleibt ein reiner Key).
            field=self._field_key(self._combo_field.currentData()),
            agg=str(self._combo_agg.currentData() or "confluence_count"),
        )

    @staticmethod
    def _field_key(ud: Any) -> str:
        """Extrahiert den JSON-Key aus einem userData-Wert (20.03.02).

        'srv_proximity|visit_pct' -> 'visit_pct'; reine Keys bleiben.
        """
        s = str(ud or "")
        return s.split("|", 1)[1] if "|" in s else s

    def _find_field_index(self, key: str) -> int:
        """Item-Index im 'Feld'-Dropdown, dessen Key-Teil == `key` ist.

        20.03.02: Das userData traegt '{service_id}|{key}' – findData(key)
        wuerde den reinen Key nicht finden. Gibt -1 zurueck, wenn keiner
        passt (Restore-Fallback erzeugt dann ein neues Item). 20.03.03: Bei
        gemeinsamen Keys (2+ Quellen) findet die Methode zuerst den
        Sammel-Eintrag ('ALL|key' -> Key-Teil == key).
        """
        for i in range(self._combo_field.count()):
            if self._field_key(self._combo_field.itemData(i)) == key:
                return i
        return -1

    def _first_field_index(self) -> int:
        """Erster auswaehlbarer (nicht-Header) Item-Index im Feld-Dropdown
        (20.03.03, Q4).

        Sektions-Header haben `Qt.NoItemFlags` und duerfen nicht als
        Current-Item gewaehlt werden – Index 0 kann ein Header sein.
        """
        for i in range(self._combo_field.count()):
            item = self._combo_field.model().item(i)
            if item is not None and (item.flags() & Qt.ItemIsEnabled):
                return i
        return 0

    # ------------------------------------------------------------------
    # 20.03.02 (F1c/F2): Multi-Select im 'Feld'-Dropdown -> Datenquellen-
    # Filter `feature_ids` (KEINE Signatur-Aenderung von set_heatmap_config;
    # die Aggregation nutzt GENAU EIN aktives Hauptfeld).
    # ------------------------------------------------------------------
    def _on_field_selection_changed(self, _checked: List[str]) -> None:
        """CheckState-Wechsel im 'Feld'-Dropdown -> feature_ids-Filter.

        21.03.15 (Bug 1): Die Verbindung selection_changed -> dieser
        Handler ist WIEDER aktiv (siehe __init__) - Check/Uncheck im
        'Feld'-Dropdown schreibt feature_ids ueber den ServicePicker-
        Pfad, damit ServicePicker-Auswahl und Feld-Dropdown konsistent
        bleiben (Single Source of Truth = ServicePicker + Dropdown).

        Die angehakten Items bestimmen die Datenquellen (`set_feature_ids`);
        `set_feature_ids` stoesst den Debounce-Refresh der generischen
        Heatmap (und der uebrigen Analytics-Seiten) an. Leere Auswahl =
        leerer Filter (alle Features, ViewModel-Semantik 15.03-E).

        20.03.03 (Q5): Vor der Filterableitung wird die XOR-Regel angewendet –
        Sammel- ('ALL|key') und Einzel-Eintraege ('srv_x|key') desselben Keys
        schliessen sich gegenseitig aus (keine Doppel-Haken).
        """
        if self._syncing or self._view_model is None:
            return
        # 13.08.2026 (Punkt 4, F4): Vor der Reconciliation das AKTIVE Feld
        # merken - wird es abgehakt, wechselt die Aggregations-/Anzeige-
        # auswahl implizit auf das naechste angehakte Feld (genau EIN Feld
        # wird aggregiert/angezeigt; die angehakten Paare bestimmen die
        # Verfuegbarkeit).
        prev_ud = str(self._combo_field.currentData() or "")
        self._reconcile_sammel_checks()
        new_ud = str(self._combo_field.currentData() or "")
        # 12.08.2026 (Option A, Bug 1/2): Die angehakten Items bestimmen die
        # (Service|Parameter)-Paare (`set_field_selection`) - An/Abwaehlen
        # eines Parameters aendert die Grafik auch bei unveraenderter
        # Service-Menge. Leere Auswahl = kein Paar-Filter (alle Features,
        # ViewModel-Semantik 15.03-E). Alt-/Test-ViewModel ohne
        # Parameter-Ebene fallen auf den Service-Pfad zurueck.
        pairs = self._checked_field_pairs()
        if hasattr(self._view_model, "set_field_selection"):
            self._view_model.set_field_selection(pairs)
        else:
            ids = self._checked_field_service_ids()
            self._view_model.set_feature_ids(ids)
        # P4 (F4): Das aktive Feld wurde abgehakt -> die Auswahl ist auf das
        # naechste angehakte Feld nachgezogen (_sync_field_current_after_-
        # checks in _reconcile_sammel_checks, blockSignals) -> die
        # Konfiguration/der Refresh wird hier explizit nachgezogen, damit
        # das neue Feld auch aggregiert/angezeigt wird.
        if new_ud and new_ud != prev_ud:
            self._apply_config()

    def _reconcile_sammel_checks(self) -> None:
        """XOR-Reconciliation (20.03.03, Q5): Sammel- und Einzel-Eintraege
        desselben Keys schliessen sich gegenseitig aus.

        Grundlage ist der ZULETZT geklickte Eintrag (`last_click_index`):
        - Klick auf `ALL|key` (Sammel)  -> Einzel-Eintraege von `key` abwaehlen.
        - Klick auf `srv_x|key` (Einzel) -> Sammel-Eintrag `ALL|key` abwaehlen.
        Programmatische Wechsel (kein Klick, Index -1) loesen nichts auf.
        Danach wird der Current-Index auf ein angehaktes/auswaehlbares Item
        nachgezogen.
        """
        last_idx = self._combo_field.last_click_index()
        if last_idx < 0:
            self._sync_field_current_after_checks()
            return
        item = self._combo_field.model().item(last_idx)
        if item is None or not (item.flags() & Qt.ItemIsEnabled):
            return
        ud = str(item.data(Qt.UserRole) or "")
        checked = [str(u or "") for u in self._combo_field.checked_data()]
        if ud.startswith("ALL|"):
            # Sammel gewinnt: alle Einzel-Eintraege desselben Keys abwaehlen.
            key = ud.split("|", 1)[1]
            wanted = [u for u in checked
                      if not (u.endswith(f"|{key}") and not u.startswith("ALL|"))]
            if wanted != checked:
                self._combo_field.set_checked_data(wanted)
        elif "|" in ud:
            # Einzel gewinnt: Sammel-Eintrag desselben Keys abwaehlen.
            all_ud = f"ALL|{self._field_key(ud)}"
            if all_ud in checked:
                self._combo_field.set_checked_data(
                    [u for u in checked if u != all_ud])
        self._sync_field_current_after_checks()

    def _sync_field_current_after_checks(self) -> None:
        """Stellt sicher, dass der aktuelle Feld-Index auf einem anhakbaren
        Item mit aktivem CheckState steht (20.03.03, Q5).

        Nach der XOR-Reconciliation kann der Index auf einem abgewaehlten
        oder deaktivierten (Header-)Item stehen – dann wird er (blockiert)
        auf das erste angehakte, sonst erste auswaehlbare Item nachgezogen.
        """
        idx = self._combo_field.currentIndex()
        item = self._combo_field.model().item(idx)
        if (item is not None and (item.flags() & Qt.ItemIsEnabled)
                and item.checkState() == Qt.Checked):
            return
        new_idx = -1
        for i in range(self._combo_field.count()):
            it = self._combo_field.model().item(i)
            if it is None or not (it.flags() & Qt.ItemIsEnabled):
                continue
            if it.checkState() == Qt.Checked:
                new_idx = i
                break
        if new_idx < 0:
            for i in range(self._combo_field.count()):
                it = self._combo_field.model().item(i)
                if it is not None and (it.flags() & Qt.ItemIsEnabled):
                    new_idx = i
                    break
        if 0 <= new_idx != idx:
            self._combo_field.blockSignals(True)
            self._combo_field.setCurrentIndex(new_idx)
            self._combo_field.blockSignals(False)

    def _checked_field_service_ids(self) -> List[str]:
        """Service-IDs der angehakten Feld-Items (20.03.03, Q2).

        - `ALL|<key>` (Sammel-Eintrag) wird ueber `self._field_sources[key]`
          auf ALLE Quellen-Services des Keys expandiert (Confluence).
        - `{service_id}|<key>` liefert genau seine service_id.
        Items ohne `|` (roher Legacy-Key) tragen keinen eindeutigen Service
        und bleiben aussen vor (die Quellen der Einzel-Keys decken den
        Filter ab). Dedupliziert, in Item-Reihenfolge.
        """
        ids: List[str] = []
        for ud in self._combo_field.checked_data():
            s = str(ud or "")
            if s.startswith("ALL|"):
                key = s.split("|", 1)[1]
                for sid in (self._field_sources.get(key) or []):
                    if sid and sid not in ids:
                        ids.append(sid)
            elif "|" in s:
                sid = s.split("|", 1)[0]
                if sid and sid not in ids:
                    ids.append(sid)
        return ids

    def _checked_field_pairs(self) -> List[str]:
        """(Service|Parameter)-Paare der angehakten Feld-Items (12.08.2026).

        Option A (Bug 1/2): Grundlage des Parameter-Filters
        (`set_field_selection`). `ALL|<key>` expandiert ueber
        `self._field_sources[key]` auf ALLE Quellen-Services des Keys,
        `{service_id}|<key>` liefert genau das Paar. Roh-Keys ohne `|`
        (Legacy) bleiben aussen vor (tragen keine Service-Zuordnung).
        Dedupliziert, in Item-Reihenfolge.
        """
        pairs: List[str] = []
        for ud in self._combo_field.checked_data():
            s = str(ud or "")
            if s.startswith("ALL|"):
                key = s.split("|", 1)[1]
                for sid in (self._field_sources.get(key) or []):
                    if sid and f"{sid}|{key}" not in pairs:
                        pairs.append(f"{sid}|{key}")
            elif "|" in s:
                sid, key = s.split("|", 1)
                if sid and f"{sid}|{key}" not in pairs:
                    pairs.append(f"{sid}|{key}")
        return pairs

    def _sync_field_selection_to_vm(self) -> None:
        """Spiegelt die effektive Paar-Auswahl in den ViewModel (12.08.2026).

        Wird am Ende jedes `_rebuild_field_dropdown()` gerufen: Die
        effektiven (Service|Parameter)-Paare (aus der Dropdown-Auswahl)
        werden via `set_field_selection` persistiert, damit a) die
        DEFAULT-Vorbelegung (erster Parameter je aktivem Service) auch die
        Query steuert (Bug 2) und b) verwaiste/entfernte Paare automatisch
        bereinigt werden. Nur bei aktivem Service-Filter (feature_ids nicht
        leer) - ohne Filter (alle Features) bleibt field_selection None und
        die Heatmap zeigt weiterhin alle Features ohne Paar-Filter.
        Idempotent via set_field_selection (kein Refresh bei Gleichstand).
        """
        if self._view_model is None:
            return
        p = self._view_model.params
        if not (p.get("feature_ids") or []):
            return
        if not hasattr(self._view_model, "set_field_selection"):
            return
        pairs = self._checked_field_pairs()
        # update_ids=False: feature_ids (ServicePicker) bleibt die
        # Service-Quelle - der Sync verkleinert die Service-Auswahl nie.
        self._view_model.set_field_selection(pairs, update_ids=False)

    # ------------------------------------------------------------------
    # Candle-Overlay (Bugfix 1, im selben Canvas) + Zoom (E8)
    # ------------------------------------------------------------------
    def _on_candle_toggled(self, checked: bool) -> None:
        if self._syncing or self._view_model is None:
            return
        self._view_model.set_candle_projection(bool(checked))
        # 20.02.01 (E7): Link-Zustand an den Overlay-Zustand koppeln.
        self._update_controls()
        if checked:
            # 21.01 (Bugfix 5): OHLCV im Heatmap-TF (adaptiv) statt
            # Tages-Aggregation.
            self._view_model.request_ohlcv_snapshot()
        else:
            self._clear_overlay()

    def _on_zoom_x_changed(self, value: int) -> None:
        if self._syncing or self._view_model is None:
            return
        self._set_zoom_range("zoom_x_range", value)
        self._apply_x_range()

    def _on_zoom_y_changed(self, value: int) -> None:
        if self._syncing or self._view_model is None:
            return
        self._set_zoom_range("zoom_y_range", value)
        self._apply_y_range()

    def _set_zoom_range(self, key: str, value: int) -> None:
        """Berechnet [lo, hi] (zentriert) aus dem Slider-Wert (E8).

        09.08.2026 (User-Meldung 2): Richtung getauscht – rechts (hoher
        Slider-Wert) = Zoom-In, links (niedriger Wert) = Zoom-Out. Der
        Slider-Wert ist die Zoom-Stufe 5..100; der sichtbare Anteil
        `f = (105 - value) / 100` (5 => volle Achse, 100 => maximale
        Vergroesserung, zentriert auf 0.5).
        """
        f = (105.0 - value) / 100.0
        lo = max(0.0, 0.5 - f / 2.0)
        hi = min(1.0, 0.5 + f / 2.0)
        zx = list(self._view_model.params.get("zoom_x_range") or [0.0, 1.0])
        zy = list(self._view_model.params.get("zoom_y_range") or [0.0, 1.0])
        if key == "zoom_x_range":
            zx = [lo, hi]
        else:
            zy = [lo, hi]
        self._view_model.set_heatmap_zoom(zx, zy)

    @staticmethod
    def _zoom_lo_hi(params: Dict[str, Any], key: str) -> List[float]:
        try:
            lo, hi = params[key]
            lo, hi = float(lo), float(hi)
        except (TypeError, ValueError, IndexError, KeyError):
            lo, hi = 0.0, 1.0
        if hi <= lo:
            lo, hi = 0.0, 1.0
        return [lo, hi]

    def _apply_x_range(self) -> None:
        """Wendet zoom_x_range auf die Heatmap an (E8, natuerliche Werte)."""
        if self._view_model is None:
            return
        lo, hi = self._zoom_lo_hi(self._view_model.params, "zoom_x_range")
        span = self._x_max - self._x_min
        self._plot_hm.setXRange(
            self._x_min + lo * span, self._x_min + hi * span, padding=0)

    def _apply_y_range(self) -> None:
        """Wendet zoom_y_range auf die Heatmap an (E8, natuerliche Werte)."""
        if self._view_model is None:
            return
        lo, hi = self._zoom_lo_hi(self._view_model.params, "zoom_y_range")
        span = self._y_max - self._y_min
        self._plot_hm.setYRange(
            self._y_min + lo * span, self._y_min + hi * span, padding=0)

    def _update_price_view(self) -> None:
        """Synchronisiert die Preis-ViewBox-Geometrie mit der Heatmap.

        10.08.2026 (Bugfix Runde 7, Bug 1): Je nach gekoppelter Date-Achse
        (X oder Y) wird die passende Achse benachrichtigt.
        """
        vb = self._plot_hm.plotItem.vb
        self._price_vb.setGeometry(vb.sceneBoundingRect())
        if self._price_vb.linkedView(pg.ViewBox.XAxis) is not None:
            self._price_vb.linkedViewChanged(vb, self._price_vb.XAxis)
        if self._price_vb.linkedView(pg.ViewBox.YAxis) is not None:
            self._price_vb.linkedViewChanged(vb, self._price_vb.YAxis)

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def _on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind == QUERY_HEATMAP_GENERIC:
            # Runde 12 (Option A): No-Data-Varianten aus dem HEATMAP-Payload
            # uebernehmen (Generation-Guard) VOR dem Render - die
            # '(No Data)'-Items erscheinen im selben Durchlauf wie die Grafik.
            self._cache_no_data_from_payload(data)
            self._render_generic(data)
        elif kind in (QUERY_DAILY_OHLC, QUERY_OHLCV):
            # 21.01 (Bugfix 5): QUERY_OHLCV liefert die Bars im Heatmap-TF
            # (adaptives Overlay); QUERY_DAILY_OHLC bleibt als
            # Kompatibilitaets-Pfad erhalten.
            self._render_overlay(data)
        elif kind == QUERY_FEATURES:
            # Runde 11 (Bug 4, B4-3): Kompatibilitaets-Pfad (z. B. der
            # refresh_all() der Initial-Ladung stoesst QUERY_FEATURES an).
            self._on_features_ready(data)

    def _cache_no_data_from_payload(self, data: Dict[str, Any]) -> bool:
        """Uebernimmt no_data_variants aus einem Payload (Generation-Guard).

        Runde 12 (Option A): Gemeinsamer Cache-Pfad fuer den
        QUERY_HEATMAP_GENERIC-Payload (No-Data im selben Datenfluss) und
        den QUERY_FEATURES-Kompatibilitaets-Payload. Returns False, wenn
        kein No-Data-Anteil im Payload ist (dann bleibt der Cache
        unveraendert) oder der Payload stale ist (aeltere Generation).
        """
        if self._view_model is None:
            return False
        vm = self._view_model
        payload_gen = data.get("restore_generation")
        if (payload_gen is not None
                and str(payload_gen) != str(
                    getattr(vm, "restore_generation", 0))):
            return False  # Stale-Payload (Query lief VOR dem letzten Restore)
        if "no_data_variants" not in data:
            return False  # Payload ohne No-Data-Anteil (z. B. Alt-Payload)
        variants = data.get("no_data_variants")
        self._no_data_variants = (
            [dict(v) for v in variants] if isinstance(variants, list)
            else [])
        self._no_data_variants_error = bool(
            data.get("no_data_variants_error"))
        return True

    def _on_features_ready(self, data: Dict[str, Any]) -> None:
        """Uebernimmt die No-Data-Varianten aus einem QUERY_FEATURES-Payload.

        Runde 11 (Bug 4, B4-2/B4-3): Payload-Vertrag `no_data_variants`
        IMMER vorhanden; `no_data_variants_error` markiert einen
        fehlgeschlagenen Check. Stale-Payloads werden verworfen
        (Generation-Guard). Danach wird das 'Feld'-Dropdown aus dem Cache
        neu abgeleitet (die '(No Data)'-Items erscheinen/verschwinden).

        Runde 15 (Fix 1, Ultra-Low-Latency): Der QUERY_FEATURES-Payload
        traegt jetzt zusaetzlich `metrics`/`field_sources` (Feld-Metadaten,
        Repository `_field_metadata`) – das 'Feld'-Dropdown wird damit
        BEREITS aus dem leichten Metadaten-Query gefuellt (KEIN Warten auf
        die teure Heatmap-Pivot-Aggregation).
        """
        if not self._cache_no_data_from_payload(data):
            return
        # Runde 15 (Fix 1): Feld-Metadaten aus dem Leicht-Payload uebernehmen
        # (falls vorhanden) – sonst bleibt der bestehende Widget-Cache.
        keys = [str(m) for m in (data.get("metrics") or [])
                if m not in ("count", "confluence_count")]
        field_sources = data.get("field_sources")
        if keys or field_sources:
            self._rebuild_field_dropdown(
                keys,
                field_sources if isinstance(field_sources, dict) else {})
        else:
            self._rebuild_field_dropdown(self._field_keys, self._field_sources)
        # 21.03.20 (Analytics Modus-Filter): Modus-Dropdown aus dem
        # LEICHTEN QUERY_FEATURES-Payload befuellen (`source_modes`
        # + `has_source_mode_services`; Entscheidung 2: kein Extra-
        # Roundtrip, Worker-Thread + Reader-Cache).
        self._sync_mode_filter_from_payload(data)

    def _on_query_failed(self, kind: str, _error: str) -> None:
        """Runde 11 (Bug 4, B4-2): Fehlerzustand des No-Data-Checks.

        Schlaegt die QUERY_FEATURES-Abfrage fehl (kein Payload), zeigt das
        Feld-Dropdown den 'Pruefung fehlgeschlagen'-Hinweis statt stumm zu
        bleiben (verschluckte Fehler, User-Analyse Punkt 2).
        """
        if kind == QUERY_FEATURES:
            self._no_data_variants = []
            self._no_data_variants_error = True
            self._rebuild_field_dropdown(self._field_keys,
                                         self._field_sources)

    def _sync_mode_filter_from_payload(self, data: Dict[str, Any]) -> None:
        """Befuellt das Modus-Dropdown aus dem QUERY_FEATURES-Payload.

        21.03.20 (Entscheidung 2/4): `source_modes` (distinct, case-original)
        fuellt die Items (itemData = Modus-Wert). `has_source_mode_services
        == False` deaktiviert die Combo und setzt den Filter auf "all"
        zurueck (kein aktiver Service schreibt source_mode). Stale-Payloads
        werden verworfen (Generation-Guard, Muster _sync_combos_from_payload).
        """
        if self._view_model is None:
            return
        vm = self._view_model
        payload_gen = data.get("restore_generation")
        if (payload_gen is not None
                and str(payload_gen) != str(
                    getattr(vm, "restore_generation", 0))):
            return  # Stale-Payload (Query lief VOR dem letzten Restore)
        modes = [str(m) for m in (data.get("source_modes") or [])]
        has_sm = bool(data.get("has_source_mode_services"))
        self._syncing = True
        try:
            self._combo_mode_filter.blockSignals(True)
            self._combo_mode_filter.clear()
            self._combo_mode_filter.addItem("[Alle Modi]", "all")
            for m in modes:
                if str(m).strip():
                    self._combo_mode_filter.addItem(
                        str(m).strip(), str(m).strip())
            # Deaktivierung: Combo aus + Filter auf "all" zuruecksetzen
            # (idempotent - set_service_mode("all") refresh-t nur bei
            # tatsaechlicher Aenderung).
            if not has_sm:
                self._combo_mode_filter.setEnabled(False)
                if str(vm.params.get("service_mode") or "all") != "all":
                    vm.set_service_mode("all")
            else:
                self._combo_mode_filter.setEnabled(True)
            # Auswahl aus den VM-Params wiederherstellen (Restore gewinnt).
            self._set_combo_data(
                self._combo_mode_filter,
                str(vm.params.get("service_mode") or "all"))
        finally:
            self._combo_mode_filter.blockSignals(False)
            self._syncing = False

    def _render_generic(self, data: Dict[str, Any]) -> None:
        matrix = np.asarray(data.get("matrix") or [], dtype=float)
        x_dim = str(data.get("x_dim")
                    or self._combo_x.currentData() or "date")
        y_dim = str(data.get("y_dim")
                    or self._combo_y.currentData() or "hour")
        # Natuerliche Achsen-Koordinaten (Bugfix 3: Reader liefert sie).
        x_axis = data.get("x_axis") or []
        y_axis = data.get("y_axis") or []
        self._x_dates = []
        if x_dim == "date":
            for v in (data.get("x_values") or []):
                try:
                    self._x_dates.append(
                        datetime.fromisoformat(str(v)).date())
                except (TypeError, ValueError):
                    self._x_dates.append(None)
        # Combos/Slider aus dem Payload synchronisieren (tatsaechlich
        # verwendete Werte; Repository-Fallbacks z. B. fuer `field`).
        self._sync_combos_from_payload(data)
        agg = str(data.get("agg") or "count")

        # 21.03.20-Bugfix 4: Achsen-Labels VOR dem Leer-Check konfigurieren -
        # auch bei 'Keine Daten' (gewaehlter Modus ohne DB-Rows) muss die
        # Service-Beschriftung (inkl. ' / {Modus}') auf der Achse
        # aktualisiert werden (vorher blieb der alte Zustand stehen).
        x_labels = data.get("x_labels") or []
        y_labels = data.get("y_labels") or []
        if x_dim == "service_id" and self._view_model is not None:
            x_labels = [self._view_model.resolve_service_label(str(l))
                        for l in x_labels]
        if y_dim == "service_id" and self._view_model is not None:
            y_labels = [self._view_model.resolve_service_label(str(l))
                        for l in y_labels]
        self._axis_x.configure(x_dim, x_labels)
        self._axis_y.configure(y_dim, y_labels)

        if matrix.size == 0:
            self._n_cols = self._n_rows = 0
            self._x_axis = []
            self._y_axis = []
            self._image.clear()
            # 21.03.20-Bugfix 4: 'Keine Daten'-Hinweis mit Modus-Kontext
            # (erklaert, dass der gewaehlte Modus keine DB-Rows hat).
            _mode_txt = str(self._combo_mode_filter.currentData() or "all")
            self._label_info.setText(
                "Keine Daten"
                + (f" fuer Modus '{_mode_txt}'" if _mode_txt != "all" else ""))
            self._legend.hide()  # 21.01 Bugfix 2: keine Legende ohne Daten
            self._grid_lines.setData([], [])  # 21.01 R3: keine Teiler
            self._clear_overlay()
            return

        self._n_cols = int(matrix.shape[1])
        self._n_rows = int(matrix.shape[0])
        self._x_axis = [float(v) for v in (x_axis or
                                           list(range(self._n_cols)))]
        self._y_axis = [float(v) for v in (y_axis or
                                           list(range(self._n_rows)))]

        # E7: Colormap abhaengig von der Aggregation.
        if agg == "confluence_count":
            if self._colormap_mode != "confluence":
                self._image.setColorMap(self._cmap_confluence)
                try:
                    self._colorbar.setColorMap(self._cmap_confluence)
                except Exception:
                    pass
                self._colormap_mode = "confluence"
            # 21.01 (User-Meldung 7, 11.08.2026): Die festen Levels
            # (0.0, 5.0) passten nicht zu echten Daten (Max ~1) - die
            # Farbgraduierung blieb stumpf (fast nur Weiss/Gelb). Die
            # Levels werden jetzt DATEN-GEBUNDEN gesetzt: 0 (keine
            # Konfluenz) = weiss, vmax = staerkste Farbe (dunkelrot).
            finite = matrix[np.isfinite(matrix)]
            if finite.size:
                vmax = float(finite.max())
                vmin = min(0.0, float(finite.min()))
            else:
                vmin, vmax = 0.0, 1.0
            if vmax <= vmin:
                vmax = vmin + 1.0
            self._image.setImage(matrix, levels=(vmin, vmax))
            self._colorbar.setLevels((vmin, vmax))
        else:
            if self._colormap_mode != _VIRIDIS:
                self._image.setColorMap(self._cmap_viridis)
                try:
                    self._colorbar.setColorMap(self._cmap_viridis)
                except Exception:
                    pass
                self._colormap_mode = _VIRIDIS
            finite = matrix[np.isfinite(matrix)]
            if finite.size:
                vmin = float(finite.min())
                vmax = float(finite.max())
                if vmin == vmax:
                    vmax = vmin + 1.0
            else:
                vmin, vmax = 0.0, 1.0
            self._image.setImage(matrix, levels=(vmin, vmax))
            self._colorbar.setLevels((vmin, vmax))

        # 21.01 (Bugfix 2): Diskrete Schwellwert-Legende (oben rechts)
        # an die aktuelle Colormap/Levels anpassen.
        self._update_legend()

        # ImageItem exakt auf die natuerlichen Koordinaten mappen (Bugfix 3):
        # date-Spalten = Tage (zentriert auf Mitternacht), hour/dow =
        # ganzzahlige Werte (feste Skalen, E3/E5), kategorial = Indizes.
        # Nichts wird ueber die Tagesgrenze hinaus gezeichnet (Punkt 3).
        self._x_min, self._x_max = self._axis_bounds(self._x_axis, x_dim)
        self._y_min, self._y_max = self._axis_bounds(self._y_axis, y_dim)
        self._image.setRect(QRectF(
            self._x_min, self._y_min,
            self._x_max - self._x_min, self._y_max - self._y_min))

        # 21.01 (Bugfix-Runde 3, Entscheidung 2a): Senkrechte Teiler je
        # Dateneinheit (TF-Bar-Intervall) an der X-Achse (date).
        self._update_grid_lines()

        # 20.02.01 (E4): Achsen-Label der Tageszeit mit UTC-Offset –
        # DST-robust aus dem neuesten Datumswert der Daten abgeleitet
        # (kein Berlin-Offset, Invariante 7; die Epochs sind Wanduhr-encoded).
        offset_epoch: Optional[float] = None
        if x_dim == "date" and self._x_axis:
            offset_epoch = self._x_axis[-1]
        elif y_dim == "date" and self._y_axis:
            offset_epoch = self._y_axis[-1]
        offset_text = self._utc_offset_text(offset_epoch)
        label_x = _DIM_LABELS.get(x_dim, x_dim)
        label_y = _DIM_LABELS.get(y_dim, y_dim)
        # 09.08.2026 (User-Meldung): Die date-Achse heisst 'Datum/Zeit'
        # (ohne pyqtgraph-EXP-Suffix – das unterdrueckt _HeatmapAxis via
        # enableAutoSIPrefix(False), s. o.).
        if x_dim == "date":
            label_x = "Datum/Zeit"
        if y_dim == "date":
            label_y = "Datum/Zeit"
        if x_dim == "hour":
            label_x = f"{label_x} ({offset_text})"
        if y_dim == "hour":
            label_y = f"{label_y} ({offset_text})"
        self._plot_hm.setLabel("bottom", label_x)
        self._plot_hm.setLabel("left", label_y)

        self._apply_x_range()
        self._apply_y_range()
        self._label_info.setText(f"{self._n_rows} x {self._n_cols}")

        # Bugfix 1/2 + 21.01 Bugfix 5: Bei aktivem Overlay den OHLCV-
        # Snapshot IM HEATMAP-TIMEFRAME laden (adaptiv fuer alle TFs).
        if self._chk_candle.isChecked() and self._view_model is not None:
            self._view_model.request_ohlcv_snapshot()

    @staticmethod
    def _axis_bounds(axis: List[float], dim: str):
        """Koordinaten-Bereich [lo, hi] fuer eine Achse (natuerliche Werte).

        20.02.01 (E3/E5): `hour` und `dow` haben FESTE Skalen unabhaengig
        vom Datenbereich – Tageszeit 00:00-23:59 (halboffene Zellen
        [h, h+1), Range 0..24) und Wochentag strikt Montag-Freitag
        (Mo=1..Fr=5, Range 1..6). Das garantiert stabil vergleichbare
        Achsen zwischen Symbolen/Timeframes. `date` bleibt datenabhaengig
        (Mitternachts-Epochs +/- halber Tag), kategorial = Indizes 0..n-1.
        """
        if dim == "hour":
            return 0.0, float(HOURS_PER_DAY)
        if dim == "dow":
            return 1.0, 1.0 + float(len(DOW_WEEK_LABELS))
        if not axis:
            return -0.5, 0.5
        lo = float(min(axis))
        hi = float(max(axis))
        if dim == "date":
            # Zellen = Tage, zentriert auf Mitternacht (Wanduhr).
            return lo - _HALF_DAY, hi + _HALF_DAY
        # Kategorial (timeframe/service_id/symbol): Indizes 0..n-1.
        return -0.5, float(len(axis)) - 0.5

    def _utc_offset_text(self, epoch: Optional[float]) -> str:
        """UTC-Offset der Berliner Wanduhr als Label-Text (20.02.01, E4).

        Liefert z. B. 'UTC+2' (Sommer) bzw. 'UTC+1' (Winter) – DST-robust
        aus dem UHRZEITPUNKT abgeleitet: Bevorzugt der neueste Datums-
        Epoch der Daten (falls eine date-Achse vorhanden ist), sonst die
        aktuelle Systemzeit (der Rechner laeuft in der Berliner Zeitzone,
        vgl. Invariante 7). Die Wanduhr-Epochs werden UNABHAENGIG vom
        Offset formatiert (UTC-Darstellung) – der Offset dient nur der
        Information 'Tageszeit (UTC+X)'.
        """
        try:
            if epoch is not None and epoch > 0:
                ts = datetime.fromtimestamp(float(epoch))
            else:
                ts = datetime.now()
            offset = ts.astimezone().utcoffset()
            if offset is None:
                return "UTC"
            total = int(offset.total_seconds() // 3600)
            sign = "+" if total >= 0 else "-"
            return f"UTC{sign}{abs(total)}"
        except Exception:
            return "UTC"

    def _field_label(self, key: str, service_ids: List[str]) -> str:
        """Anzeige-Text eines Feld-Eintrags (Meldung 3b/c, 09.08.2026).

        Der Service-Name wird DIREKT aus dem Service-Objekt geholt
        (`resolve_service_display_name`, plugin_id-basiert, `srv_`-Prefix
        entfaellt -> 'Swing Momentum' statt 'Swing Momentum Service').
        Ist der Key EINDEUTIG einem Service zuzuordnen, steht dessen
        korrekter Name vor dem Key ('{Name} / {Key}', z. B.
        'Grid Lines / open'). Liefern MEHRERE Services denselben Key
        (z. B. 'price' von Swing-Services), entfaellt der Prefix KOMPLETT –
        sonst wuerde eine irrefuehrende 'Pfad'-Kette ('Swing Momentum
        Service / Swing Volume Profile Service / price') entstehen
        (User-Meldung, 09.08.2026: 'Pfad im Mastertree' = absoluter
        Quatsch). Ohne bekannte Quelle bleibt der Roh-Key (defensiv).
        """
        if (len(service_ids) == 1 and self._view_model is not None):
            name = self._view_model.resolve_service_display_name(
                str(service_ids[0]))
            if name:
                label = f"{name} / {str(key)}"
                # Runde 16 (Bugfix 1, 11.08.2026): Gecheckte Variante +
                # Datum der letzten Ausfuehrung an den Eintrag anhaengen
                # ('{Name} / {Key} / {Preset} / DD.MM.JJ HH:MM' - der
                # Service-Name ohne `srv_`-Praefix, Preset 'Default' wird
                # uebersprungen, Datum ohne Eintraege wird ausgelassen).
                # Defensiv via getattr: Fake-/Alt-ViewModels (z. B. in
                # Tests) ohne `checked_variant` ergeben keinen Anhang.
                variant = None
                _cv = getattr(self._view_model, "checked_variant", None)
                if callable(_cv):
                    try:
                        variant = _cv(str(service_ids[0]))
                    except Exception:
                        variant = None
                if variant:
                    preset = str(variant.get("preset_name") or "").strip()
                    if preset and preset.lower() != "default":
                        label = f"{label} / {preset}"
                    exec_date = str(
                        variant.get("exec_datetime") or "").strip()
                    if exec_date and not exec_date.startswith("--."):
                        label = f"{label} / {exec_date}"
                else:
                    # Runde 16c (Bugfix 1, 11.08.2026, User-Meldung):
                    # Services OHNE Varianten (Standalone, keine Presets)
                    # bekommen das Datum+Uhrzeit der letzten Ausfuehrung
                    # angehaengt ('{Name} / {Key} / DD.MM.JJ HH:MM', z. B.
                    # '23.04.26 22:14'), wenn vorhanden. Defensiv via
                    # getattr: Fake-/Alt-ViewModels ohne die Methode
                    # ergeben keinen Anhang.
                    _sd = getattr(self._view_model,
                                  "service_execution_datetime", None)
                    if callable(_sd):
                        try:
                            exec_date = str(
                                _sd(str(service_ids[0])) or "").strip()
                            if exec_date and not exec_date.startswith("--."):
                                label = f"{label} / {exec_date}"
                        except Exception:
                            pass
                return label
        return str(key)

    def _rebuild_field_dropdown(
        self,
        keys: List[str],
        field_sources: Dict[str, List[str]],
        payload_agg: Optional[str] = None,
        payload_field: Optional[str] = None,
    ) -> None:
        """Baut das 'Feld'-Dropdown aus Feld-Metadaten + VM-Params (Runde 8).

        Single Source of Truth:
          * Items      -> `keys`/`field_sources` (Payload-Metadaten bzw.
                          Widget-Cache `self._field_keys/_field_sources`)
          * Haken      -> `feature_ids` (ServicePicker, aktiver Filter)
          * Current    -> `heatmap_field` (Restore/Workspace gewinnt)

        SYNCHRON (kein Query-Round-Trip): wird aus dem Datenpfad
        (_sync_combos_from_payload) UND dem VM-Pfad (_sync_from_params /
        _on_feature_ids_changed) gerufen. Ein restaurierter
        Ergebnisparameter (Bug 3) bleibt dadurch auch ohne frischen Payload
        sichtbar; ein Check/Uncheck im ServicePicker (Bug 4) aktualisiert
        das Dropdown sofort. Die Runde-7-Prioritaet (VM-Params gewinnen
        gegen einen Stale-Payload) wird hier zentral angewendet.
        """
        if self._view_model is None:
            return
        p = self._view_model.params
        # Cache aktualisieren (Payload-Metadaten bzw. uebergebene Werte).
        self._field_keys = [str(k) for k in (keys or [])]
        self._field_sources = {
            str(k): [str(s) for s in (v or [])]
            for k, v in (field_sources or {}).items()
        }
        # Agg/Feld: restaurierte VM-Params gewinnen; erst wenn der VM leer
        # ist, zaehlen Payload-Fallback bzw. aktueller Combo-Wert (Runde 7).
        agg = (str(p.get("heatmap_agg") or "") or str(payload_agg or "")
               or str(self._combo_agg.currentData() or ""))
        prev_field = (str(p.get("heatmap_field") or "")
                      or str(payload_field or "")
                      or self._field_key(self._combo_field.currentData()))
        active_ids = {str(f).strip().lower()
                      for f in (p.get("feature_ids") or [])}
        # 12.08.2026 (Option A, Bug 1/2): EXPLIZITE (Service|Parameter)-
        # Auswahl (`field_selection`) gewinnt - sie wird bei Check/Uncheck
        # persistiert und beim Aggregations-/Restore-Wechsel EXAKT wieder
        # hergestellt (Bug 2: keine 'alle Parameter'-Vorbelegung mehr; Bug 1:
        # An/Abwaehlen eines Parameters aendert die Grafik). Ohne explizite
        # Auswahl greift die DEFAULT-Vorbelegung: bei aktivem Service-Filter
        # wird je aktivem Service genau der ERSTE Parameter angehakt (fuer
        # AVG/SUM/MIN/MAX ist genau EIN aktives Hauptfeld sinnvoll), bei
        # leerem Filter (alle Features) nur der erste Eintrag insgesamt
        # (Verhalten wie bisher).
        sel_pairs = [str(x) for x in (p.get("field_selection") or [])]
        sel_map: Dict[str, Set[str]] = {}
        for _sp in sel_pairs:
            if "|" in _sp:
                _sid, _k = _sp.split("|", 1)
                sel_map.setdefault(_k, set()).add(_sid.strip().lower())
        explicit = bool(sel_pairs)
        no_filter = not active_ids
        # Default-Vorbelegung: erster Parameter je aktivem Service
        # (sortierte Key-Reihenfolge aus self._field_keys).
        first_key_by_service: Dict[str, str] = {}
        if not explicit and not no_filter:
            for k in sorted(self._field_keys):
                for sid in self._field_sources.get(k) or []:
                    sid_l = sid.strip().lower()
                    if (sid_l in active_ids
                            and sid_l not in first_key_by_service):
                        first_key_by_service[sid_l] = k
        # no_filter-Semantik: genau der ERSTE Eintrag insgesamt wird
        # vorbelegt (first_done); alle weiteren folgen `match`.
        first_done = [no_filter and not explicit]

        def _chk(match: bool) -> bool:
            if first_done[0]:
                first_done[0] = False
                return True
            return match

        def _chk_pair(sid: str, key: str) -> bool:
            """Check-Vorgabe fuer einen '{sid}|{key}'-Einzel-Eintrag."""
            sid_l = str(sid).strip().lower()
            if explicit:
                # Nur AKTIVE Services: ein Paar eines im ServicePicker
                # abgewaehlten Services darf nicht angehakt bleiben.
                return (sid_l in active_ids
                        and sid_l in sel_map.get(key, ()))
            return first_key_by_service.get(sid_l) == key

        def _chk_all(key: str, src: List[str]) -> bool:
            """Check-Vorgabe fuer den 'ALL|<key>'-Sammel-Eintrag."""
            if explicit:
                return all(str(s).strip().lower() in active_ids
                           and str(s).strip().lower() in sel_map.get(key, ())
                           for s in src)
            return all(first_key_by_service.get(str(s).strip().lower())
                       == key for s in src)

        try:
            self._combo_field.blockSignals(True)
            self._combo_field.clear()
            shared = sorted(k for k in self._field_keys
                            if len(self._field_sources.get(k) or []) >= 2)
            if shared:
                self._combo_field.add_header_item(
                    "🌐 Gleiche Parameter (alle aktiven Services):")
                for k in shared:
                    src = self._field_sources.get(k) or []
                    self._combo_field.add_checkable_item(
                        f"Alle Services / {k}", f"ALL|{k}",
                        checked=_chk(_chk_all(k, src)))
            if self._field_keys:
                self._combo_field.add_header_item("🔌 Einzelservices:")
            for k in sorted(self._field_keys):
                sids = self._field_sources.get(k) or []
                if len(sids) == 1:
                    # Eindeutiger Service: nur angehakt, wenn das
                    # (Service|Parameter)-Paar aktiv ist (Default: erster
                    # Parameter; explizit: field_selection).
                    self._combo_field.add_checkable_item(
                        self._field_label(k, sids), f"{sids[0]}|{k}",
                        checked=_chk(_chk_pair(sids[0], k)))
                elif not sids:
                    # Legacy ohne field_sources (roher Key, defensiv).
                    self._combo_field.add_checkable_item(k, k,
                                                         checked=_chk(False))
                else:
                    # Shared Key: je Quelle ein Einzel-Eintrag; der Sammel-
                    # Eintrag deckt die Quellen ab (Q5/XOR), daher nur
                    # anhaken, solange NICHT alle Quellen des Keys aktiv.
                    all_checked = _chk_all(k, sids)
                    for sid in sids:
                        self._combo_field.add_checkable_item(
                            self._field_label(k, [sid]), f"{sid}|{k}",
                            checked=_chk(_chk_pair(sid, k)
                                         and not all_checked))
            if prev_field in self._field_keys:
                self._combo_field.setCurrentIndex(
                    self._find_field_index(prev_field))
            elif self._field_keys:
                # 20.03.03 (Q4): Index 0 kann ein Header sein -> ersten
                # auswaehlbaren Eintrag waehlen.
                self._combo_field.setCurrentIndex(self._first_field_index())
            elif prev_field:
                # Kein Payload/Cache (Restore vor dem ersten Datenpaket):
                # Roh-Item anlegen, damit der restaurierte Wert sichtbar
                # und ausgewaehlt bleibt (Muster _sync_from_params).
                self._combo_field.add_checkable_item(
                    prev_field, prev_field, checked=True)
                self._combo_field.setCurrentIndex(
                    self._combo_field.count() - 1)
            # Runde 11 (Bug 4, B4-1): '(No Data)'-Hinweise kommen jetzt als
            # Payload-Attribut `no_data_variants` vom QUERY_FEATURES-Worker
            # (Cache self._no_data_variants) - KEIN synchroner DB-Zugriff
            # mehr im UI-Hauptthread. Die Anzeige unterscheidet Loading/
            # Erfolg/Fehler und filtert nach aktiven instance_hashes (B4-5).
            self._render_no_data_items()
        finally:
            self._combo_field.blockSignals(False)
        self._update_controls()
        # E6: Wert-Aggregation mit leerem/abweichendem Feld -> restauriertes
        # Feld gewinnt (falls im Datensatz verfuegbar), sonst ersten Key
        # uebernehmen und Konfiguration nachreichen (einmaliger Query-Loop).
        vm_field = str(p.get("heatmap_field") or "")
        if (agg in _VALUE_AGGS and self._combo_field.currentData()
                and vm_field != self._field_key(
                    self._combo_field.currentData())):
            if vm_field and vm_field in self._field_keys:
                fidx = self._find_field_index(vm_field)
                if fidx >= 0:
                    self._combo_field.setCurrentIndex(fidx)
            else:
                self._apply_config()
        # 12.08.2026 (Option A, Bug 1/2): Effektive Paar-Auswahl in den VM
        # spiegeln (Default-Vorbelegung materialisieren / verwaiste Paare
        # bereinigen). Idempotent; kein Refresh bei Gleichstand.
        self._sync_field_selection_to_vm()

    def _render_no_data_items(self) -> None:
        """Rendert die No-Data-Hinweise aus dem Payload-Cache (B4-2/B4-5).

        Runde 11 (Bug 4): Die '(No Data)'-Varianten kommen vom
        QUERY_FEATURES-Worker (`no_data_variants` im Payload) - kein
        synchroner DB-Zugriff mehr. Die Anzeige unterscheidet:
          * Payload ausstehend (self._no_data_variants is None) -> nichts
          * Payload-Fehler   -> '⚠️ No-Data-Prüfung ...' (deaktiviert)
          * Erfolg + Liste   -> '(No Data)'-Abschnitt (deaktivierte Items)

        Runde 13 (Bugfix Dropdown-NoData): Der Payload ist seit dem
        Reader-Hash-Filter bereits VARIANTEN-GENAU - `no_data_variants`
        enthaelt nur noch die im ServicePicker gecheckten Varianten
        (und nur Services aus `feature_ids`). Die Widget-seitigen Filter
        (active_ids/active_hashes) sind damit redundant, bleiben aber
        DEFENSIV aktiv (schuetzt z. B. gegen Alt-Payloads vom
        QUERY_FEATURES-Kompatibilitaetspfad ohne Hash-Filter). Die
        gewaehlte Variante ist in Runde 13 immer Teil des Abschnitts -
        die B4-5-Inline-Ergaenzung greift nur noch bei Defensiv-Luecken.

        Runde 13c (Kernwunsch): Bei leerem feature_ids-Filter (leer =
        kein Filter = alle Features) wird KEIN '(No Data)'-Abschnitt UND
        kein No-Data-Fehlerhinweis gerendert - der Button 'Aktive Filter
        entfernen' zeigt danach wieder alle Features ohne NoData-Rauschen
        (der VM-Snapshot liefert bei leerem Filter bereits keine
        Varianten; dieser Guard schuetzt zusaetzlich gegen Alt-/
        Stale-Payloads).
        """
        if self._view_model is None:
            return
        p = self._view_model.params
        # Runde 12 (Punkt 4) + Runde 13c (Kernwunsch): Nur Services im
        # aktiven feature_ids-Filter duerfen NoData-Hinweise liefern.
        # Leerer Filter (leer = kein Filter = alle Features) -> KEINE
        # Hinweise (auch kein Fehler-/Loading-Hinweis), damit der Button
        # 'Aktive Filter entfernen' alle Features ohne NoData-Rauschen
        # zeigt.
        active_ids = {str(f).strip().lower()
                      for f in (p.get("feature_ids") or [])}
        if not active_ids:
            return
        if self._no_data_variants_error:
            self._combo_field.add_disabled_item(
                "⚠️ No-Data-Prüfung konnte nicht durchgeführt werden")
            return
        if self._no_data_variants is None:
            return  # Loading: Payload steht noch aus (kein Hinweis noetig)
        # Runde 13: `instance_hashes` ist seit dem MasterTree-Fix auch fuer
        # Set-Instanz-Varianten (TYPE_SERVICE) gefuellt. Der Reader filtert
        # den Payload bereits danach - hier defensiv gegen Alt-Payloads.
        active_hashes = {str(h).strip().lower()
                         for h in (p.get("instance_hashes") or [])}
        variants = [dict(v) for v in self._no_data_variants]
        filtered = variants
        if active_ids:
            filtered = [v for v in filtered
                        if str(v.get("plugin_id") or "").strip().lower()
                        in active_ids]
        # Runde 16 (Bugfix Mischbetrieb, User-Meldung 5/6, 11.08.2026):
        # Hash-lose Varianten (Standalone-Services wie srv_trend_breakout
        # und NULL-Hash-Alt-Bestand) werden UEBER `feature_ids` gecheckt -
        # eine aktive Hash-Auswahl darf sie nicht aus dem '(No Data)'-
        # Abschnitt werfen (sonst verschwinden Services im Mischbetrieb
        # aus dem Feld-Dropdown, obwohl sie gecheckt sind).
        if active_hashes:
            filtered = [v for v in filtered
                        if not str(v.get("instance_hash") or "").strip()
                        or str(v.get("instance_hash") or "").strip().lower()
                        in active_hashes]
        if not filtered and self._selected_no_data_variant(variants) is None:
            return
        self._combo_field.add_header_item(
            "🕓 Noch ohne Daten (erster Scan ausstehend):")
        rendered: set = set()
        for nd in filtered:
            rendered.add((str(nd.get("plugin_id") or "").strip().lower(),
                          str(nd.get("instance_hash") or "").strip().lower()))
            # Runde 11 (B4-2): display_name enthaelt den Preset bereits
            # (resolve_service_display_name/Reader-Fallback) - keine
            # doppelte '(preset)'-Ergaenzung im Item-Text.
            self._combo_field.add_disabled_item(
                f"{nd.get('display_name') or nd.get('plugin_id')} – (No Data)")
        # B4-5 (Runde 13): Die gewaehlte Variante bleibt zusaetzlich inline
        # sichtbar (ausgegraut) - defensiv: nur wenn die Widget-Filter sie
        # wider Erwarten nicht im Abschnitt haetten (Reader-Hash-Filter
        # und Widget-Filter koennen nicht divergieren, solange beide auf
        # `instance_hashes` basieren).
        sel = self._selected_no_data_variant(variants)
        if sel is not None:
            key = (str(sel.get("plugin_id") or "").strip().lower(),
                   str(sel.get("instance_hash") or "").strip().lower())
            if key not in rendered:
                self._combo_field.add_disabled_item(
                    f"→ {sel.get('display_name') or sel.get('plugin_id')} – (No Data)")

    def _selected_no_data_variant(
        self, variants: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """No-Data-Variante des aktuell gewaehlten Feld-Items (oder None).

        Runde 12 (Punkt 3): Das Feld-Item-userData traegt '{service_id}|{key}'
        (ein Feld-Item repraesentiert einen SERVICE, nicht eine Variante) -
        die GEWAEHLTE Variante wird ueber den aktiven instance_hashes-Filter
        des ServicePickers identifiziert: Liefert der Service mehrere
        No-Data-Varianten, gewinnt die gecheckte Variante (exakter Hash-
        Match) statt immer der ersten. Runde 12 (Punkt 4): Services, die
        NICHT im aktiven feature_ids-Filter liegen, werden ignoriert
        (None - keine Inline-Markierung fuer nicht gecheckte Services).

        Runde 13 (Bugfix Dropdown-NoData): Der Payload (`no_data_variants`)
        ist seit dem Reader-Hash-Filter bereits VARIANTEN-GENAU - er enthaelt
        nur noch die im ServicePicker gecheckten Varianten. Die ausgewaehlte
        No-Data-Variante des aktuellen Feld-Services ist damit EINDEUTIG
        bestimmt (hoechstens eine Variante pro Service uebrig). Der alte
        'erste Variante des Services'-Fallback ist ersatzlos entfernt: Er
        zeigte bei aktiver Varianten-Einschraenkung faelschlich die ERSTE
        Variante (V1), obwohl eine andere (V2) gecheckt und V1 gar nicht
        aktiv war - die Runde-12b-Einschraenkung (kein Fallback bei nicht
        leerem instance_hashes) war unvollstaendig, weil `instance_hashes`
        fuer Set-Instanz-Varianten bis Runde 13 leer blieb.

        Runde 13c (Bug 1-Absicherung): Falls ein Payload aus einem Alt-/
        Kompatibilitaetspfad doch mehrere No-Data-Varianten desselben
        Services enthaelt, gewinnt DEFENSIV die im ServicePicker gecheckte
        Variante (instance_hash in `instance_hashes`) statt der ersten
        Liste. Erst ohne Hash-Match faellt die Auswahl auf den ersten
        Service-Treffer zurueck (hash-lose Variante/kein Filter).
        """
        if not variants:
            return None
        if self._view_model is None:
            return None
        p = self._view_model.params
        data = self._combo_field.currentData()
        sid = None
        if isinstance(data, str) and "|" in data:
            sid = data.split("|", 1)[0].strip().lower()
        if not sid:
            return None
        # Punkt 4: Nur Services im aktiven feature_ids-Filter (leer = alle).
        active_ids = {str(f).strip().lower()
                      for f in (p.get("feature_ids") or [])}
        if active_ids and sid not in active_ids:
            return None
        # Runde 13: Der Payload ist bereits variantengefiltert (Reader-
        # Hash-Filter auf active_hashes). Die No-Data-Variante des aktuellen
        # Feld-Services im Payload IST die ausgewaehlte - kein Fallback auf
        # die 'erste Variante' mehr (die gecheckte Variante gewinnt, weil
        # nur sie im Payload steht).
        #
        # Runde 13c (Bug 1-Absicherung): Bei mehreren No-Data-Varianten
        # desselben Services gewinnt DEFENSIV die im ServicePicker gecheckte
        # Variante (instance_hash in active_hashes) statt der ersten Liste
        # - falls der Payload aus einem Alt-/Kompatibilitaetspfad doch
        # mehrere Varianten enthaelt. Erst wenn kein Hash-Match vorliegt
        # (hash-lose Variante/kein Filter), faellt die Auswahl auf den
        # ersten Service-Treffer zurueck.
        p_hashes = {str(h).strip().lower()
                    for h in (p.get("instance_hashes") or [])}
        if p_hashes:
            for v in variants:
                if (str(v.get("plugin_id") or "").strip().lower() == sid
                        and str(v.get("instance_hash") or "").strip().lower()
                        in p_hashes):
                    return v
        for v in variants:
            if str(v.get("plugin_id") or "").strip().lower() == sid:
                return v
        return None

    def _on_feature_ids_changed(self) -> None:
        """Synchrones Neu-Ableiten des Feld-Dropdowns bei Check/Uncheck.

        Runde 8 (Bugfix 4): `set_feature_ids()` emittiert
        feature_ids_changed, sobald der ServicePicker-Haken geaendert wird -
        Items/Haken/Current werden SOFORT aus den gecachten Feld-Metadaten
        und den aktuellen feature_ids neu abgeleitet (Single Source of
        Truth = Picker; kein Debounce/Query-Round-Trip noetig).
        """
        if self._syncing or self._view_model is None:
            return
        self._syncing = True
        try:
            self._rebuild_field_dropdown(self._field_keys,
                                         self._field_sources)
        finally:
            self._syncing = False

    def _sync_combos_from_payload(self, data: Dict[str, Any]) -> None:
        """Synchronisiert die Combos mit dem tatsaechlichen Payload."""
        if self._view_model is None:
            return
        vm = self._view_model
        metrics = [str(m) for m in (data.get("metrics") or [])]
        keys = [m for m in metrics if m not in ("count", "confluence_count")]
        # 20.02.01 (User-Meldung 3b): Key -> Services, die ihn liefern
        # (Repository `field_sources`); Anzeige '{Service} / {Key}'.
        field_sources = data.get("field_sources") or {}
        # Runde 8 (Bugfix 3): Stale-Payload-Guard. Der Worker spiegelt die
        # Generation der Query-Params ins Ergebnis-Dict - Queries, die VOR
        # dem letzten restore_workspace()/_apply_profile() gestartet wurden,
        # tragen eine aeltere Generation. Deren Feld-Metadaten duerfen den
        # synchron restaurierten Zustand NICHT ueberschreiben (die x/y/agg-
        # Combos werden trotzdem mit VM-Prioritaet bestaetigt).
        payload_gen = data.get("restore_generation")
        stale = (payload_gen is not None
                 and str(payload_gen) != str(
                     getattr(vm, "restore_generation", 0)))
        # Runde 11 (Architektur, A5): Die x/y/agg-Combos werden NICHT mehr
        # aus dem Payload synchronisiert - die Controls sind Single Source
        # of Truth (Restore-/User-Auswahl gewinnt, kein Ueberschreiben).
        self._syncing = True
        try:
            if not stale:
                # Feld-Metadaten uebernehmen + 'Feld'-Dropdown synchron neu
                # ableiten (Items/Haken/Current; Runde 8, Bug 3/4). Bei
                # stale Payloads bleibt der Zustand aus _sync_from_params
                # unveraendert.
                self._rebuild_field_dropdown(
                    keys, field_sources,
                    payload_agg=str(data.get("agg") or ""),
                    payload_field=str(data.get("field") or ""))
            # Runde 11 (Bug 4, B4-1): '(No Data)'-Hinweise rendert
            # _rebuild_field_dropdown() zentral aus dem Payload-Cache
            # (self._no_data_variants aus QUERY_FEATURES).
        finally:
            self._syncing = False
        self._update_controls()

    def _render_overlay(self, data: Dict[str, Any]) -> None:
        """Zeichnet OHLCV-Bars ueber die Heatmap (selbes Canvas, Bugfix 1).

        21.01 (Bugfix 5, 11.08.2026): Das Overlay nutzt die Bars IM
        HEATMAP-TIMEFRAME (OHLCV-Snapshot, adaptiv fuer alle TFs) statt der
        festen Tages-Aggregation. Die Candle-Breite folgt dem Bar-Intervall
        (_bar_interval_seconds). Bars werden ueber ihren Wanduhr-Tag
        (Mitternachts-Epoch) dem Heatmap-Zeitraum zugeordnet und an ihrer
        ECHTEN Bar-Zeit positioniert (H1-Kerzen liegen damit korrekt in der
        jeweiligen Tageszelle).

        Die Candles liegen in der Preis-ViewBox. 'Datum' liegt auf der
        X-Achse (Y=date ist keine offizielle Overlay-Ansicht mehr, der
        horizontale Zweig bleibt defensiv erhalten). Die Spalten der
        date-Achse sind Wanduhr-Mitternachts-Epochs. Alpha 0.3-0.5 (E9).
        """
        self._clear_overlay()
        bars = data.get("bars") or []
        x_dim = str(self._combo_x.currentData() or "date")
        y_dim = str(self._combo_y.currentData() or "hour")
        # 10.08.2026 (Bugfix Runde 7, Bug 1): 'Datum' darf auf X oder Y
        # liegen - die Candles werden in der Orientierung der Date-Achse
        # gezeichnet (vertikal bei X=date, horizontal bei Y=date).
        date_on_x = x_dim == "date"
        date_axis = self._x_axis if date_on_x else self._y_axis
        if not bars or not date_axis:
            return
        # Spalten-Index je Wanduhr-Tag (Mitternachts-Epoch) - dient als
        # Filter, dass die Bar im Heatmap-Zeitraum liegt. OHLCV-Bars tragen
        # ihre ECHTE Bar-Zeit (z. B. H1 14:00) - der Wanduhr-Tag wird per
        # UTC-Division auf Mitternacht zurueckgefuehrt (Bugfix 5).
        epoch_to_col = {int(round(e)): i for i, e in enumerate(date_axis)}
        candles: List[tuple] = []
        for b in bars:
            t = b.get("time")
            if t is None:
                continue
            try:
                t = int(t)
            except (TypeError, ValueError):
                continue
            day = int(t // _DAY_SECONDS) * _DAY_SECONDS
            col = epoch_to_col.get(day)
            if col is None:
                continue  # Tag nicht in der Heatmap (Ausschnitt)
            try:
                o = float(b["open"])
                c = float(b["close"])
                h = float(b["high"])
                l = float(b["low"])
            except (TypeError, ValueError, KeyError):
                continue
            if not (np.isfinite(o) and np.isfinite(c)
                    and np.isfinite(h) and np.isfinite(l)):
                continue
            candles.append((t, o, h, l, c))
        if not candles:
            return
        pmin = min(c[3] for c in candles)
        pmax = max(c[2] for c in candles)
        if pmin == pmax:
            pmin -= 1.0
            pmax += 1.0
        pad = (pmax - pmin) * 0.05
        if date_on_x:
            self._price_vb.setYRange(pmin - pad, pmax + pad, padding=0)
        else:
            self._price_vb.setXRange(pmin - pad, pmax + pad, padding=0)
        # 21.01 (Bugfix 5): Candle-Breite/Hoehe folgt dem Bar-Intervall
        # des Heatmap-TFs (z. B. 3600s bei H1, 86400s bei D1) statt fest
        # einem Tag. x = echte Bar-Epoch (X=date) bzw. y = Bar-Epoch
        # (Y=date, defensiver Zweig).
        # 21.01 (Bugfix-Runde 3, Bug 1, 11.08.2026): NumPy-vektorisiertes
        # Rendering - statt 2 Qt-Items JE BAR nur noch 3 batched Items
        # (Wick + Bull-Koerper + Bear-Koerper) fuer ALLE Bars (vorher bei
        # 5000 Bars = 10.000 Einzel-Items -> Pan/Zoom rueckelte). Die
        # Daten werden als numpy-Arrays an BarGraphItem uebergeben.
        # 12.08.2026 (User-Meldung 4): Kerzenbreite an den DATEN-TF der
        # OHLCV-Bars koppeln + TF im UI-Label anzeigen.
        data_tf = str(data.get("timeframe") or "").strip().upper()
        bar_sec = self._bar_interval_seconds(data_tf or None)
        lbl_tf = getattr(self, "_label_overlay_tf", None)
        if lbl_tf is not None:
            if data_tf:
                lbl_tf.setText(f"Overlay: {data_tf}")
            else:
                lbl_tf.setText("Overlay: ?")
        times = np.asarray([c[0] for c in candles], dtype=np.float64)
        opens = np.asarray([c[1] for c in candles], dtype=np.float64)
        highs = np.asarray([c[2] for c in candles], dtype=np.float64)
        lows = np.asarray([c[3] for c in candles], dtype=np.float64)
        closes = np.asarray([c[4] for c in candles], dtype=np.float64)
        bull = closes >= opens
        bear = ~bull
        wick_color = pg.mkColor(128, 128, 128, 140)
        bull_color = pg.mkColor(0, 180, 0, 140)
        bear_color = pg.mkColor(220, 30, 30, 140)
        if date_on_x:
            # Vertikale Candles (Preis auf der rechten Achse).
            wick = pg.BarGraphItem(
                x=times, width=bar_sec * 0.12,
                y0=lows, height=np.maximum(highs - lows, 1e-9),
                brush=wick_color, pen=wick_color)
            body_bull = pg.BarGraphItem(
                x=times[bull], width=bar_sec * 0.7,
                y0=opens[bull],
                height=np.maximum(closes[bull] - opens[bull], 1e-9),
                brush=bull_color, pen=bull_color)
            body_bear = pg.BarGraphItem(
                x=times[bear], width=bar_sec * 0.7,
                y0=closes[bear],
                height=np.maximum(opens[bear] - closes[bear], 1e-9),
                brush=bear_color, pen=bear_color)
        else:
            # Horizontale Candles (Preis auf der unteren Achse, defensiv).
            wick = pg.BarGraphItem(
                x0=lows, width=np.maximum(highs - lows, 1e-9),
                y=times, height=bar_sec * 0.12,
                brush=wick_color, pen=wick_color)
            body_bull = pg.BarGraphItem(
                x0=opens[bull], width=np.maximum(
                    closes[bull] - opens[bull], 1e-9),
                y=times[bull], height=bar_sec * 0.7,
                brush=bull_color, pen=bull_color)
            body_bear = pg.BarGraphItem(
                x0=closes[bear], width=np.maximum(
                    opens[bear] - closes[bear], 1e-9),
                y=times[bear], height=bar_sec * 0.7,
                brush=bear_color, pen=bear_color)
        self._candle_items = [wick, body_bull, body_bear]
        for _item in self._candle_items:
            self._price_vb.addItem(_item)
        self._price_vb.setVisible(True)
        if date_on_x:
            self._plot_hm.getAxis("right").setVisible(True)
            self._price_axis_bottom.setVisible(False)
        else:
            self._price_axis_bottom.setVisible(True)
            self._plot_hm.getAxis("right").setVisible(False)
        self._update_price_view()

    def _clear_overlay(self) -> None:
        """Entfernt alle Kerzen-Items und versteckt die Preis-Achse."""
        for item in self._candle_items:
            try:
                self._price_vb.removeItem(item)
            except Exception:
                pass
        self._candle_items = []
        self._price_vb.setVisible(False)
        self._plot_hm.getAxis("right").setVisible(False)
        self._price_axis_bottom.setVisible(False)

    # ------------------------------------------------------------------
    # 21.01 Bugfix-Runde 3 (Entscheidung 2a): Senkrechte Teiler je
    # Dateneinheit (Bar-Intervall des Timeframes) an der X-Achse (date)
    # ------------------------------------------------------------------
    def _update_grid_lines(self) -> None:
        """Setzt die senkrechten Teiler je Dateneinheit (Bugfix 2a).

        Nur bei X=date. Der Abstand ist das Bar-Intervall des Heatmap-TFs
        (_bar_interval_seconds, z. B. H1 -> jede volle Stunde, D1 -> jede
        Tagesgrenze). Die Positionen sind daten-konsistent (Epochs sind
        Vielfache von 60s; Mitternachts-Epochs Vielfache von 86400s). Ein
        Dichte-Cap (max ~2000 Linien) verhindert ueberladene Raster bei
        sehr grossen Zeitraeumen (dann wird der Abstand skaliert).
        """
        x_dim = str(self._combo_x.currentData() or "date")
        if x_dim != "date" or not self._x_axis:
            self._grid_lines.setData([], [])
            self._grid_lines.setVisible(False)
            return
        bar_sec = self._bar_interval_seconds()
        lo = float(self._x_axis[0])
        hi = float(self._x_axis[-1]) + _DAY_SECONDS
        start = int(math.floor(lo / bar_sec)) * bar_sec
        step = 1
        max_lines = 2000
        while int((hi - lo) / (bar_sec * step)) > max_lines:
            step += 1
        positions = np.arange(start, hi, bar_sec * step)
        if positions.size == 0:
            self._grid_lines.setData([], [])
            self._grid_lines.setVisible(False)
            return
        y0, y1 = self._y_min, self._y_max
        n = positions.size
        xs = np.empty(n * 2, dtype=np.float64)
        xs[0::2] = positions
        xs[1::2] = positions
        ys = np.empty(n * 2, dtype=np.float64)
        ys[0::2] = y0
        ys[1::2] = y1
        self._grid_lines.setData(x=xs, y=ys, connect="pairs")
        self._grid_lines.setVisible(True)

    # ------------------------------------------------------------------
    # 21.01 Bugfix 5: Adaptives Overlay (OHLCV im Heatmap-Timeframe)
    # ------------------------------------------------------------------
    def _bar_interval_seconds(self,
                             data_tf: Optional[str] = None) -> float:
        """Bar-Intervall des Overlay-Timeframes in Sekunden (Bugfix 5).

        12.08.2026 (User-Meldung 4, 'Anzeigebalken ca. 18h breit'): Der
        TF wird zunaechst aus den OHLCV-Overlay-DATEN gelesen (diejenige
        Zeitebene, deren Kerzen tatsaechlich gerendert werden) und erst
        dann aus `params["timeframe"]` des ViewModels - die Breite folgt
        damit IMMER der angezeigten Datenbasis (Race-/Divergenz-sicher).
        Fallback 3600s, falls beide TF unbekannt/leer sind.
        """
        tf = ""
        if data_tf:
            tf = str(data_tf)
        elif self._view_model is not None:
            tf = str(self._view_model.params.get("timeframe") or "")
        return float(_TF_SECONDS.get(tf.strip().upper(), 3600.0))

    # ------------------------------------------------------------------
    # 21.03.11 (Bug 5): Zoom-Slider Zwei-Wege-Sync (Maus-Zoom -> Slider)
    # ------------------------------------------------------------------
    def _on_heatmap_x_range_changed(self, _vb, xrange) -> None:
        """Aktualisiert den X-Zoom-Slider nach Maus-Zoom auf der X-Achse."""
        if getattr(self, "_syncing", False) or self._view_model is None:
            return
        self._sync_slider_from_range(
            self._slider_zoom_x, xrange,
            self._x_min, self._x_max, "zoom_x_range")

    def _on_heatmap_y_range_changed(self, _vb, yrange) -> None:
        """Aktualisiert den Y-Zoom-Slider nach Maus-Zoom auf der Y-Achse."""
        if getattr(self, "_syncing", False) or self._view_model is None:
            return
        self._sync_slider_from_range(
            self._slider_zoom_y, yrange,
            self._y_min, self._y_max, "zoom_y_range")

    def _sync_slider_from_range(self, slider, vrange, vmin, vmax, key) -> None:
        """Setzt Slider + VM-Params aus einem ViewBox-Range (Bug 5).

        Rechnet den sichtbaren Achsen-Anteil [lo, hi] aus dem Range in den
        normalisierten [0,1]-Bereich um und stellt den Slider invers ein.
        Kein DB-Requery (set_heatmap_zoom ist rein client-seitig).
        """
        span = float(vmax) - float(vmin)
        if span <= 0:
            return
        try:
            lo = (float(vrange[0]) - float(vmin)) / span
            hi = (float(vrange[1]) - float(vmin)) / span
        except (TypeError, ValueError, IndexError):
            return
        lo = max(0.0, min(1.0, lo))
        hi = max(0.0, min(1.0, hi))
        if hi <= lo:
            return
        self._set_zoom_slider(slider, [lo, hi])
        # VM-Params aktualisieren (Persistenz) - Endlos-Schleifen-Guard via
        # _syncing (set_heatmap_zoom emittiert kein ViewBox-Range-Event).
        try:
            if getattr(self, "_syncing", False) or self._view_model is None:
                return
            self._syncing = True
            zx = list(self._view_model.params.get("zoom_x_range") or [0.0, 1.0])
            zy = list(self._view_model.params.get("zoom_y_range") or [0.0, 1.0])
            if key == "zoom_x_range":
                zx = [lo, hi]
            else:
                zy = [lo, hi]
            self._view_model.set_heatmap_zoom(zx, zy)
        except Exception:
            pass
        finally:
            self._syncing = False

    # ------------------------------------------------------------------
    # 21.01 Bugfix 3: Fadenkreuz + Zellwert-Info
    # ------------------------------------------------------------------
    def _on_mouse_moved(self, pos) -> None:
        """Bewegt das Fadenkreuz ueber die Heatmap (Bugfix 3).

        `pos` ist ein QPointF in SCENE-Koordinaten (pyqtgraph
        `sigMouseMoved`). Nur innerhalb des Plot-Viewports wird das Kreuz
        gezeigt; sonst versteckt (Maus ueber den Steuerleisten).
        """
        if self._view_model is None:
            return
        vb = self._plot_hm.plotItem.vb
        rect = vb.sceneBoundingRect()
        if rect is None or not rect.contains(pos):
            self._cross_x.setVisible(False)
            self._cross_y.setVisible(False)
            return
        try:
            p = vb.mapSceneToView(pos)
        except Exception:
            return
        self._cross_x.setPos(p.x())
        self._cross_y.setPos(p.y())
        self._cross_x.setVisible(True)
        self._cross_y.setVisible(True)
        self._update_cell_info(p.x(), p.y())

    def _update_cell_info(self, x: float, y: float) -> None:
        """Zeigt genaue Datum/Zeit + Matrix-Wert am Fadenkreuz (Bug 4).

        E15 (11.08.2026, Bugfix 1): Das DATUM ist der TAG DER ZELLE unter
        dem Fadenkreuz (self._x_axis[col], Mitternacht der Wanduhr). Die
        Zellen sind mittags-zentriert [Tag-12h, Tag+12h) – die nackte
        Cursor-Roh-Epoch wuerde sonst bei Vormittags-Zeiten (0:00-11:59)
        off-by-one-day liefern. Die ZEIT ist die exakte Cursor-HH:MM aus
        der Roh-Epoch (Wanduhr-UTC, KEIN Berlin-Offset). Das Label wird
        ausserdem IMMER aktualisiert (auch ausserhalb des Datenbereichs),
        damit kein veralteter Zellwert stehen bleibt.
        """
        if self._n_rows <= 0 or self._n_cols <= 0:
            return
        img = getattr(self._image, "image", None)
        if img is None or img.size == 0:
            return
        sx = (self._x_max - self._x_min) or 1.0
        sy = (self._y_max - self._y_min) or 1.0
        col = int((x - self._x_min) / sx * self._n_cols)
        row = int((y - self._y_min) / sy * self._n_rows)
        in_bounds = (0 <= col < self._n_cols and 0 <= row < self._n_rows)
        time_txt = ""
        if str(self._combo_x.currentData() or "date") == "date":
            try:
                day_ts = float(self._x_axis[col]) if (
                    0 <= col < len(self._x_axis)) else float(x)
                d_day = datetime.fromtimestamp(day_ts, tz=dt_timezone.utc)
                d_time = datetime.fromtimestamp(float(x), tz=dt_timezone.utc)
                days = ("Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So.")
                time_txt = (f"{days[d_day.weekday()]} {d_day.day:02d}."
                            f"{d_day.month:02d}.{d_day.year % 100:02d} "
                            f"{d_time.hour:02d}:{d_time.minute:02d}  →  ")
            except (TypeError, ValueError, OverflowError, OSError):
                time_txt = ""
        if not in_bounds:
            self._label_info.setText(
                f"{time_txt}Zelle ausserhalb des Datenbereichs")
            return
        try:
            v = float(img[row, col])
        except (TypeError, ValueError, IndexError):
            self._label_info.setText(f"{time_txt}Zelle({row},{col}) = n/a")
            return
        self._label_info.setText(f"{time_txt}Zelle({row},{col}) = {_format_heatmap_value(v)}")

    # ------------------------------------------------------------------
    # 21.01 Bugfix 2: Diskrete Schwellwert-Legende (oben rechts)
    # ------------------------------------------------------------------
    def _update_legend(self) -> None:
        """Befuellt die Schwellwert-Legende je Colormap/Levels.

        Confluence (diskret): je ganzzahligem Treffer-Wert 0..5 ein Farbfeld
        mit der AKTUELL daten-gebundenen Farbe (Levels 0..vmax), '5+' fuer
        alles darueber. Wert-Aggregationen (viridis, kontinuierlich): 5
        Stichproben min..max mit den tatsaechlichen Werten als Label.
        """
        cmap = (self._cmap_confluence
                if self._colormap_mode == "confluence"
                else self._cmap_viridis)
        levels = getattr(self._image, "levels", None)
        if levels is None or len(levels) != 2:
            self._legend.hide()
            return
        vmin = float(levels[0])
        vmax = float(levels[1])
        if vmax <= vmin:
            vmax = vmin + 1.0
        self._legend.clear()
        if self._colormap_mode == "confluence":
            max_count = max(1, int(math.ceil(vmax)))
            for c in range(0, min(max_count, 5) + 1):
                frac = (c - vmin) / (vmax - vmin)
                frac = max(0.0, min(1.0, frac))
                color = cmap.map(frac, mode="qcolor")
                # 21.03.11 (Bug 1): Operator-korrekte Beschriftung
                # (= Treffer-Wert, >=" fuer alles darueber).
                label = "= {}".format(c) if c < 5 else ">= 5"
                self._add_legend_swatch(color, label)
        else:
            # 12.08.2026 (Bug 5): Viridis als OPERATOR-Intervalle. Die
            # Schwellen v25/v50/v75/vmax werden mit adaptiver Genauigkeit
            # formatiert (_format_legend_value, Spannen-abhaengige Nach-
            # kommastellen), damit sie bei kleinen Spannen (z. B. vmin=0.01,
            # vmax=0.02) NICHT zusammenfallen ('0.01 - 0.01' war unsinnig).
            # Die Labels sind eindeutige Operator-Angaben (`<`, `<=`,
            # `>=`) statt Bindestrich-Bereichen.
            span = vmax - vmin
            v25 = vmin + 0.25 * span
            v50 = vmin + 0.50 * span
            v75 = vmin + 0.75 * span
            fmt = lambda v: _format_legend_value(v, span)
            # 13.08.2026 (Punkt 2, F2): Viridis-Operatoren VOR der Zahl,
            # kein 'x' mehr - eindeutige Schwellen-Angaben
            # (<= v25, >= v25, >= v50, >= v75, >= vmax).
            self._add_legend_swatch(cmap.map(0.0, mode="qcolor"),
                                    "<= {}".format(fmt(v25)))
            self._add_legend_swatch(cmap.map(0.25, mode="qcolor"),
                                    ">= {}".format(fmt(v25)))
            self._add_legend_swatch(cmap.map(0.5, mode="qcolor"),
                                    ">= {}".format(fmt(v50)))
            self._add_legend_swatch(cmap.map(0.75, mode="qcolor"),
                                    ">= {}".format(fmt(v75)))
            self._add_legend_swatch(cmap.map(1.0, mode="qcolor"),
                                    ">= {}".format(fmt(vmax)))
        self._legend.show()

    def _add_legend_swatch(self, color, label: str) -> None:
        """Fuegt ein Farbfeld + Label zur Legende hinzu (Bugfix 2)."""
        item = pg.PlotDataItem(
            [0], [0], pen=None,
            symbol="s", symbolSize=10,
            symbolBrush=pg.mkColor(color), symbolPen=pg.mkPen(None))
        self._legend.addItem(item, str(label))

```

--------------------------------------------------

### DATEI: analytics/ui/scatter_page.py
```py
# analytics/ui/scatter_page.py
"""
scatter_page.py - Scatter-Seite der Analytics-UI (Phase 15.03 / 19.02).

Zeigt X/Y-Paare zweier feature_data-JSON-Keys (dynamisch, 19.02) als
pyqtgraph-ScatterPlot. Ein Klick auf einen Punkt oeffnet das Chart-Fenster
an der neuesten Feature-Bar des Symbol/Timeframe (Jump-to-Chart Variante 2,
Aufloesung ueber den ViewModel).

MVVM (Invariante 4): Reine UI – Daten kommen ueber
`data_ready(QUERY_SCATTER, data)` vom ViewModel (Async-Worker); es gibt
KEIN SQL in dieser Klasse.
"""

from typing import Any, Callable, Dict, Optional

import pyqtgraph as pg
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from analytics.engine.analytics_worker import QUERY_SCATTER
from analytics.ui.common import make_overlay_stack


class ScatterPage(QWidget):
    """Scatterplot zweier nativer Spalten mit Jump-to-Chart."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None
        self._navigation_handler: Optional[Callable[[str, str, int], None]] = None
        self._bar_resolver: Optional[Callable[[str, str], Optional[int]]] = None
        self._current_symbol = ""
        self._current_timeframe = "M1"

        self._combo_x = QComboBox()
        self._combo_y = QComboBox()

        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._scatter = pg.ScatterPlotItem(
            size=6, pen=None, brush=pg.mkBrush(41, 98, 255, 180)
        )
        self._plot.addItem(self._scatter)

        content = QWidget(self)
        lay = QVBoxLayout(content)
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("X:"))
        ctrl.addWidget(self._combo_x)
        ctrl.addWidget(QLabel("Y:"))
        ctrl.addWidget(self._combo_y)
        ctrl.addStretch(1)
        lay.addLayout(ctrl)
        lay.addWidget(self._plot)
        self._stack = make_overlay_stack(content)
        self.setLayout(self._stack)

        self._combo_x.currentTextChanged.connect(self._on_columns_changed)
        self._combo_y.currentTextChanged.connect(self._on_columns_changed)
        self._scatter.sigClicked.connect(self._on_point_clicked)

    # ------------------------------------------------------------------
    # MVVM-Anbindung (vom AnalyticsWindow gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        self._view_model = view_model
        params = view_model.params
        # 19.02 (Cleanup): Dynamische feature_data-JSON-Keys statt nativer
        # Spalten. Prefill fuer das aktuelle Symbol/Timeframe; die Combos
        # werden bei jedem Daten-Payload aktualisiert (on_data_ready).
        columns = view_model.available_feature_columns(
            params.get("symbol", ""), params.get("timeframe", "M1"))
        self._set_columns(columns, params.get("scatter_x"),
                          params.get("scatter_y"))
        view_model.data_ready.connect(self.on_data_ready)

    def set_navigation_handler(self, fn: Callable[[str, str, int], None]) -> None:
        self._navigation_handler = fn

    def set_bar_resolver(self, fn: Callable[[str, str], Optional[int]]) -> None:
        """Setzt die Bar-Aufloesung (symbol, tf -> neuester bar_time)."""
        self._bar_resolver = fn

    def request_data(self) -> None:
        if self._view_model is not None:
            self._view_model.request_scatter()

    # ------------------------------------------------------------------
    # 19.02: Dynamische Achsen-Combos (feature_data-JSON-Keys)
    # ------------------------------------------------------------------
    def _set_columns(self, columns, x_col, y_col) -> None:
        """Fuellt die Achsen-Combos (19.02, dynamische JSON-Keys).

        Erhaelt die aktuelle Auswahl, wenn sie in `columns` verfuegbar ist;
        sonst Defaults (erste beiden, x != y). Signale sind blockiert, damit
        kein Query-Loop ueber _on_columns_changed entsteht.
        """
        cols = [str(c) for c in (columns or [])]
        x = str(x_col or "") if str(x_col or "") in cols else (
            cols[0] if cols else "")
        y_candidates = [c for c in cols if c != x]
        y = str(y_col or "") if (str(y_col or "") in cols
                                 and str(y_col or "") != x) else (
            y_candidates[0] if y_candidates else x)
        self._combo_x.blockSignals(True)
        self._combo_y.blockSignals(True)
        self._combo_x.clear()
        self._combo_y.clear()
        for c in cols:
            self._combo_x.addItem(c, c)
            self._combo_y.addItem(c, c)
        self._combo_x.setCurrentIndex(self._combo_x.findData(x) if x else -1)
        self._combo_y.setCurrentIndex(self._combo_y.findData(y) if y else -1)
        self._combo_x.blockSignals(False)
        self._combo_y.blockSignals(False)

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind != QUERY_SCATTER:
            return
        self._current_symbol = str(data.get("symbol") or "")
        self._current_timeframe = str(data.get("timeframe") or "M1")
        # 19.02: Combos mit den verfuegbaren JSON-Keys aktualisieren und auf
        # die tatsaechlich verwendeten Achsen (x_label/y_label) synchronisieren.
        vm_params_x = (self._view_model.params.get("scatter_x")
                       if self._view_model else "")
        vm_params_y = (self._view_model.params.get("scatter_y")
                       if self._view_model else "")
        self._set_columns(
            data.get("columns"),
            data.get("x_label") or vm_params_x,
            data.get("y_label") or vm_params_y,
        )
        points = data.get("points") or []
        xs = [p["x"] for p in points]
        ys = [p["y"] for p in points]
        self._scatter.setData(x=xs, y=ys)
        if xs:
            self._plot.setLabel("bottom", str(data.get("x_label") or ""))
            self._plot.setLabel("left", str(data.get("y_label") or ""))
            self._plot.autoRange()
            self._stack.setCurrentIndex(0)
        else:
            self._stack.setCurrentIndex(1)

    # ------------------------------------------------------------------
    # Jump-to-Chart (Variante 2): Klick auf einen Punkt
    # ------------------------------------------------------------------
    def _on_point_clicked(self, scatter_item, points, event) -> None:
        if not points or self._bar_resolver is None \
                or self._navigation_handler is None:
            return
        bar_time = self._bar_resolver(
            self._current_symbol, self._current_timeframe
        )
        if bar_time is not None:
            self._navigation_handler(
                self._current_symbol, self._current_timeframe, int(bar_time)
            )

    # ------------------------------------------------------------------
    # Steuerung (Spalten -> ViewModel -> Debounce -> Worker)
    # ------------------------------------------------------------------
    def _on_columns_changed(self, _text: str) -> None:
        if self._view_model is None:
            return
        x_col = self._combo_x.currentData()
        y_col = self._combo_y.currentData()
        if x_col and y_col:
            self._view_model.set_scatter_columns(x_col, y_col)

```

--------------------------------------------------

### DATEI: analytics/ui/table_page.py
```py
# analytics/ui/table_page.py
"""
table_page.py - Tabellen-Seite der Analytics-UI (Phase 15.03 / 19.01).

Zeigt die rohen Feature-Store-Zeilen (Tabelle) und koppelt einen
Doppelklick an 'Jump-to-Chart' (Variante 2): open_chart_at_bar(symbol, tf,
bar_time) wird aufgerufen und das Chart-Fenster in den Vordergrund geholt.

MVVM (Invariante 4): Die Page ist reine UI – Rendering + Event-Handling.
Die Daten kommen ueber `data_ready(QUERY_TABLE, data)` vom ViewModel
(Async-Worker); es gibt KEIN SQL in dieser Klasse.

19.01 (Step 2) – Multi-Service-Darstellung:
- Spalte 1 = **Service** (feature_id bzw. via injiziertem `name_resolver`
  aufgeloester Anzeigename, E3/IoC – kein SQL, keine Modell-Kopplung).
- Standard-Spaltenreihenfolge: [Zeit (Wanduhr), Service,
  ...JSON-Union-Keys alphabetisch] (E4).
- **Chronologisch ABSTEIGEND** nach bar_time (E2): Die Page sortiert die
  erhaltenen Rows deterministisch (stabil); die QTableWidget-Interaktions-
  sortierung bleibt deaktiviert, damit die Service-Mischung korrekt bleibt.
  Der `FeatureStoreReader` (ASC-Vertrag) bleibt unveraendert.
- JSON-Union: Vereinigung aller `feature_data`-Keys ueber die geladenen
  Rows; fehlende Werte bei abweichenden Services -> "-".

19.02 (Cleanup + Schrift):
- Legacy-Native-Spalten ema_diff/rsi_14/atr_normalized sind ENTFERNT –
  die Tabelle zeigt nur noch Zeit + Service + dynamische JSON-Union.
- Kleinere Schrift (9 pt): bei gleicher Fenstergroesse sind mehr Zeilen
  (Zeilenhoehe folgt der Schrift) und mehr Spalten (schmalere Spalten)
  sichtbar.

19.03 (Resizing, In-Memory-Sorting & Profil-Persistenz):
- Interaktives Resizing: Spaltenbreiten und Zeilenhoehen sind per
  QHeaderView.Interactive frei anpassbar (Step 1).
- In-Memory-Sortierung: QTableWidget-Sortierung wird NACH dem Befuellen
  aktiviert (O(n^2)-Schutz); die Zeitspalte sortiert numerisch ueber die
  Roh-Epoch (_SortableTimeItem, E2/E3). 19.01-E2 (deterministisch
  absteigende Roh-Liste `_current_rows`) bleibt fuer Jump-to-Chart unveraendert.
- Profil-Persistenz (Option B – Explicit Save): User-Aenderungen emittieren
  `table_settings_changed` (Breiten {Name: Breite}, Zeilenhoehe, Sortierung);
  das AnalyticsWindow reicht sie an `AnalyticsViewModel.set_table_settings()`
  (nur Dirty, kein Query-Refresh). Beim Befuellen werden die gespeicherten
  Settings wiederhergestellt (E1/E8/E9); Signale sind waehrenddessen blockiert
  (E4).
- Jump-to-Chart-Row-Mapping (E7): Der `_current_rows`-Einfuege-Index liegt im
  UserRole+1 des Zeit-Items – unabhaengig von der Anzeige-Sortierung.

19.04 (Paging, Bugfix 08.08.2026):
- Paging wieder eingebaut (Legacy-Muster aus statistic_win.py): Vor/Zurueck-
  Buttons + Seitenlabel unter der Tabelle. Die geladenen `_current_rows`
  (bis zum Limit aus analytics_win) werden in Seiten der Groesse
  `statistics_page_size` (AppSettings, via `set_page_size()` injiziert)
  aufgeteilt; `_current_rows` haelt weiterhin ALLE Zeilen (Jump-to-Chart/
  Seitenwechsel). Nach Daten-Update springt die Anzeige auf Seite 0.
- Beim Seitenwechsel bleibt die aktive User-Sortierung erhalten (nur die
  Anzeige-Seite wird neu gerendert, Roh-Liste unveraendert).

19.05 (Bugfix 08.08.2026): Individuelle Zeilenhöhen
- Zwischenstand (Anforderung korrigiert in 19.06): `row_height` als
  Default-Section-Size + separate `row_heights` {Row-Index: Höhe}.

19.06 (Korrektur 08.08.2026): Zeilenhöhe -> GANZE Tabelle live
- Gewuenschtes Verhalten (Anwender): Das Ziehen einer Zeilenhöhe uebertraegt
  die neue Hoehe LIVE auf die gesamte Tabelle (alle Zeilen) und speichert sie
  als globale `table_row_height` im Profil. KEIN individuelles row_heights.
- Umsetzung: `_on_vertical_section_resized` setzt nach dem Drag die neue
  Hoehe per setDefaultSectionSize + setRowHeight auf alle Zeilen (Signale
  blockiert, kein Signal-Sturm) und emittiert die globale Hoehe;
  `_apply_table_settings` stellt sie beim Refresh/Profil-Load wieder her
  (alle Zeilen auf die gespeicherte Hoehe).
"""

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_worker import QUERY_TABLE
from analytics.ui.common import format_wanduhr_time, make_overlay_stack

# 19.02 (Cleanup): Basis-Spalten OHNE Legacy-Native-Spalten – nur Zeit +
# Service. Alle Feature-Werte kommen dynamisch aus feature_data (JSON-Union).
_BASE_COLUMNS = [
    ("Zeit (Wanduhr)", 130),
    ("Service", 150),
]
# Feste Breite der dynamischen JSON-Union-Spalten (feature_data-Keys).
_EXTRA_COLUMN_WIDTH = 95
# Spalten-Indizes der Basis-Spalten (fuer Jump-to-Chart / Zeit-UserRole).
_COL_TIME = 0
_COL_SERVICE = 1
# 19.02 (Task 1): Schriftgroesse der Tabelle (kleiner -> mehr Zeilen/Spalten).
_TABLE_FONT_PT = 9


def _epoch_int(value: Any) -> Optional[int]:
    """Wandelt einen bar_time-Wert in die Wanduhr-Epoch (int) um (oder None).

    Defensiv: fetch_rows() liefert bereits int-Epochs; dieser Helfer schuetzt
    vor Alt-Rows/ungueltigen Werten beim Sortieren und im UserRole.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class _SortableTimeItem(QTableWidgetItem):
    """Zeit-Spalten-Item mit numerischem Zeitvergleich (19.03 E2).

    QTableWidget sortiert standardmaessig nach `__lt__` (= text()-Vergleich).
    Das Wanduhr-Format ('Fr 31.07.26 00:01') ist lexikografisch NICHT
    chronologisch – diese Subklasse vergleicht die Roh-Epoch aus dem
    UserRole numerisch (Fallback auf die Text-Sortierung).
    """

    def __lt__(self, other) -> bool:
        if isinstance(other, QTableWidgetItem):
            try:
                a = self.data(Qt.UserRole)
                b = other.data(Qt.UserRole)
                if a is not None and b is not None:
                    return int(a) < int(b)
            except (TypeError, ValueError):
                pass
        return super().__lt__(other)


class _SortableValueItem(QTableWidgetItem):
    """JSON-Union-Item mit numerischem Vergleich (21.03.11, Bug 6).

    Die dynamischen Feature-Werte (z. B. `signal_strength`) sind im Text
    auf 4 signifikante Stellen gekuerzt ('9.5' > '10.2' lexikografisch falsch).
    Diese Subklasse vergleicht den Rohwert aus dem UserRole numerisch,
    damit die 'Signal-Staerke'-Sortierung der MTF-FC-Filterleiste korrekt ist.
    """

    def __lt__(self, other) -> bool:
        if isinstance(other, QTableWidgetItem):
            try:
                a = self.data(Qt.UserRole)
                b = other.data(Qt.UserRole)
                if a is not None and b is not None:
                    return float(a) < float(b)
            except (TypeError, ValueError):
                pass
        return super().__lt__(other)


class TablePage(QWidget):
    """Feature-Store-Tabelle mit Jump-to-Chart (Doppelklick)."""

    # 19.03 (Step 1): UI-Change-Signal fuer Tabellen-Settings (Spaltenbreiten
    # {Name: Breite}, Zeilenhoehe, Sortier-Spalte/-Richtung). Wird vom
    # AnalyticsWindow an `AnalyticsViewModel.set_table_settings()` verdrahtet
    # (Profil-Persistenz, Option B – Explicit Save; E6: kein Query-Refresh).
    table_settings_changed = Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None
        self._navigation_handler: Optional[Callable[[str, str, int], None]] = None
        # 19.01 (E3): Injizierbarer Namensaufloeser (feature_ids -> Namen).
        # Default: feature_id selbst anzeigen (kein UI->Modell-Zwang).
        self._name_resolver: Callable[[List[str]], List[str]] = lambda ids: list(ids)
        # Roh-Rows der aktuellen Anzeige (fuer Jump-to-Chart, unabhaengig
        # von Tabellen-Spalten-Positionen). 19.04 (Paging): haelt ALLE
        # geladenen Zeilen (bis Limit); angezeigt wird nur die aktuelle Seite.
        self._current_rows: List[Dict[str, Any]] = []
        # 19.04 (Paging): Zeilen pro Seite (via set_page_size aus den
        # AppSettings statistics_page_size injiziert; Default 100), aktuelle
        # Seite und Gesamtseitenzahl.
        self._page_size: int = 100
        self._current_page: int = 0
        self._total_pages: int = 1
        # 21.03.11 (Bug 6): Externe Sortierung aus der MTF-FC-Filterleiste
        # ('date' | 'signal' | 'tf'). None = keine externe Vorgabe (die
        # TablePage sortiert wie bisher nach Profil/User-Klick). Ein gesetzter
        # Modus hat VORRANG vor der Profil-Sortierung (wird nach jedem
        # Befuellen erneut angewendet) und persistiert NICHT als User-Setting.
        self._external_sort_mode: Optional[str] = None

        self._header = QLabel("Feature-Store-Tabelle")
        self._table = QTableWidget(0, len(_BASE_COLUMNS))
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setHorizontalHeaderLabels([c[0] for c in _BASE_COLUMNS])
        header = self._table.horizontalHeader()
        # Fix 15.03 (TF-Wechsel-Haenger): KEIN ResizeToContents! Der Modus
        # berechnet bei JEDEM setItem die optimale Breite ueber ALLE Zeilen
        # (O(n^2)) – bei 5000 Zeilen blockiert das den Main-Thread minuten-
        # lang. Stattdessen deterministische Startbreiten aus _BASE_COLUMNS
        # (setColumnWidth unten); der User kann sie seit 19.03 interaktiv
        # anpassen (QHeaderView.Interactive, Step 1).
        header.setStretchLastSection(False)
        # 19.03 (Step 1): Interaktives Resizing – Spaltenbreiten und
        # Zeilenhoehen sind frei anpassbar. Die FIXEN Defaults aus
        # _BASE_COLUMNS/_EXTRA_COLUMN_WIDTH bleiben als Startbreiten beim
        # ersten Befuellen erhalten (siehe _populate / _get_settings_widths).
        header.setSectionResizeMode(QHeaderView.Interactive)
        self._table.verticalHeader().setSectionResizeMode(
            QHeaderView.Interactive)
        for i, (_, width) in enumerate(_BASE_COLUMNS):
            self._table.setColumnWidth(i, width)
        # 19.01 (E2) + 19.03 (E3): Die Page zeichnet `_current_rows`
        # deterministisch ABSTEIGEND nach bar_time (Service-Mischung bleibt
        # chronologisch korrekt). Die QTableWidget-Interaktions-Sortierung
        # (setSortingEnabled(True)) wird seit 19.03 NACH dem Befuellen
        # aktiviert (sonst O(n^2)-Re-Sort bei jedem setItem) – sie sortiert
        # nur die ANZEIGE, nicht die Roh-Liste (E7-Row-Mapping).
        self._table.setSortingEnabled(False)
        # 19.02 (Task 1): Kleinere Schrift – mehr Zeilen (Zeilenhoehe folgt
        # der Schrift) und mehr Spalten sichtbar bei gleicher Fenstergroesse.
        table_font = QFont()
        table_font.setPointSize(_TABLE_FONT_PT)
        self._table.setFont(table_font)
        header_font = QFont(table_font)
        header_font.setBold(True)
        header.setFont(header_font)
        # 19.03 (Step 1): UI-Change-Signale – Breiten-/Zeilen-Resize und
        # Sortier-Indikator emittieren table_settings_changed (Persistenz).
        # Waehrend _populate sind die Header blockiert (E4), sodass nur echte
        # User-Aktionen emittieren.
        header.sectionResized.connect(self._on_header_section_resized)
        header.sortIndicatorChanged.connect(self._on_sort_indicator_changed)
        self._table.verticalHeader().sectionResized.connect(
            self._on_vertical_section_resized)

        content = QWidget(self)
        lay = QVBoxLayout(content)
        lay.addWidget(self._header)
        lay.addWidget(self._table)
        # 19.04 (Paging): Leiste mit Zurueck/Weiter + Seitenlabel unter der
        # Tabelle (Muster statistic_win.py: btn_prev_page/btn_next_page/
        # label_page_info). Zeigt die Seite und die Gesamtzahl der geladenen
        # Zeilen; Buttons werden je nach Position ein-/ausgegraut.
        self.btn_prev = QPushButton("◀ Zurück")
        self.btn_next = QPushButton("Weiter ▶")
        self.label_page = QLabel("Seite 1 / 1")
        page_bar = QWidget(self)
        page_lay = QHBoxLayout(page_bar)
        page_lay.setContentsMargins(0, 2, 0, 0)
        page_lay.setSpacing(6)
        page_lay.addWidget(self.btn_prev)
        page_lay.addWidget(self.label_page)
        page_lay.addWidget(self.btn_next)
        page_lay.addStretch(1)
        lay.addWidget(page_bar)
        self._stack = make_overlay_stack(content)
        self.setLayout(self._stack)

        self._table.itemDoubleClicked.connect(self._on_double_clicked)
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_next.clicked.connect(self._next_page)

    # ------------------------------------------------------------------
    # MVVM-Anbindung (vom AnalyticsWindow gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        """Verbindet die Page mit dem AnalyticsViewModel (data_ready)."""
        self._view_model = view_model
        view_model.data_ready.connect(self.on_data_ready)

    def set_navigation_handler(
        self, fn: Callable[[str, str, int], None]
    ) -> None:
        """Setzt den Jump-to-Chart-Handler (open_chart_at_bar)."""
        self._navigation_handler = fn

    def set_name_resolver(
        self, fn: Callable[[List[str]], List[str]]
    ) -> None:
        """Setzt den Service-Namensaufloeser (19.01 E3, IoC).

        `fn` bildet feature_ids (plugin_ids) auf Anzeigenamen ab (z. B.
        `ServiceSelectorModel.resolve_display_names`). Default: die
        feature_id selbst anzeigen. Kein SQL / keine Modell-Kopplung.
        """
        if callable(fn):
            self._name_resolver = fn

    def request_data(self) -> None:
        """Fordert die Tabellen-Daten ueber das ViewModel an."""
        if self._view_model is not None:
            self._view_model.request_table()

    def set_page_size(self, page_size: int) -> None:
        """Setzt die Zeilen pro Seite (Paging, 19.04; IoC vom AnalyticsWindow).

        Der Wert kommt aus den AppSettings (`statistics_page_size`). Bei
        bereits geladenen Daten wird die aktuelle Seite neu gerendert (Seite
        wird auf 0 zurueckgesetzt).
        """
        try:
            ps = int(page_size)
        except (TypeError, ValueError):
            ps = 100
        if ps <= 0:
            ps = 100
        if ps == self._page_size:
            return
        self._page_size = ps
        if self._current_rows:
            self._current_page = 0
            self._render_current_page()

    # ------------------------------------------------------------------
    # 21.03.11 (Bug 6): Externe Sortierung (MTF-FC-Filterleiste via EventBus)
    # ------------------------------------------------------------------
    def set_external_sort_mode(self, mode: str) -> None:
        """Setzt die externe Sortierung ('date' | 'signal' | 'tf').

        Wird vom AnalyticsWindow aufgerufen, wenn die MTF-FC-Filterleiste
        des ChartWindows eine neue Sortierung emittiert (EventBus). Der Modus
        hat VORRANG vor der Profil-/User-Sortierung, wird nach jedem
        Befuellen erneut angewendet und persistiert NICHT als User-Setting.
        Ein leerer/ungueltiger Modus deaktiviert die externe Vorgabe.
        """
        mode = str(mode or "").strip().lower()
        if mode not in ("date", "signal", "tf"):
            mode = ""
        if mode == (self._external_sort_mode or ""):
            return
        self._external_sort_mode = mode or None
        if self._table.rowCount() > 0:
            self._apply_external_sort()

    def _apply_external_sort(self) -> None:
        """Wendet die externe Sortierung auf die Tabelle an (Bug 6).

        Spalten-Mapping: 'date' -> Zeit (absteigend, UserRole-Epoch),
        'signal' -> Header-Substring (signal/stärke/score/conf/wert) auf den
        dynamischen JSON-Union-Spalten (absteigend, numerisch via
        `_SortableValueItem`), 'tf' -> Header-Substring (timeframe/tf)
        aufsteigend. Fallback (keine passende Spalte): Zeit absteigend.
        Die QTableWidget-Sortierung (setSortingEnabled + sortItems) betrifft
        nur die ANZEIGE – `_current_rows` und das Jump-to-Chart-Mapping
        (UserRole+1) bleiben unveraendert.
        """
        mode = self._external_sort_mode or "date"
        column: int = _COL_TIME
        order: Qt.SortOrder = Qt.DescendingOrder
        if mode == "signal":
            col = self._find_dynamic_header(
                ("signal", "stärke", "staerke", "score", "conf", "wert"))
            if col is not None:
                column, order = col, Qt.DescendingOrder
        elif mode == "tf":
            col = self._find_dynamic_header(("timeframe", "tf"))
            if col is not None:
                column, order = col, Qt.AscendingOrder
        # Signale blockieren: externe Sortierung ist KEINE User-Aktion und
        # darf nicht `table_settings_changed` (Profil-Persistenz) ausloesen.
        header = self._table.horizontalHeader()
        header.blockSignals(True)
        try:
            self._table.setSortingEnabled(True)
            self._table.sortItems(column, order)
        finally:
            header.blockSignals(False)

    def _find_dynamic_header(self, needles: tuple) -> Optional[int]:
        """Findet eine dynamische JSON-Union-Spalte per Header-Substring.

        Sucht NUR die Spalten ab `_COL_SERVICE + 1` (die dynamischen
        Feature-Keys) – Basis-Spalten 'Zeit (Wanduhr)'/'Service' werden nie
        getroffen (ein 'tf'-Substring in 'Zeit' waere falsch).
        """
        for col in range(_COL_SERVICE + 1, self._table.columnCount()):
            item = self._table.horizontalHeaderItem(col)
            if item is None:
                continue
            text = str(item.text()).lower()
            if any(n in text for n in needles):
                return col
        return None

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind != QUERY_TABLE:
            return
        if not self.isVisible():
            # Fix 15.03 (TF-Wechsel-Haenger): Die Tabelle wird NUR gerendert,
            # wenn sie die aktive/ sichtbare Seite ist. data_ready feuert bei
            # jedem TF-Wechsel fuer ALLE Seiten; ein versteckter 5000-Zeilen-
            # Render (ResizeToContents + Sortierung) wuerde den Main-Thread
            # blockieren. Beim Aktivieren der Seite fordert _on_page_changed
            # die Daten erneut an (request_data -> frischer Query).
            return
        rows = data.get("rows") or []
        self._populate(rows)
        self._stack.setCurrentIndex(0 if rows else 1)

    def _populate(self, rows: List[Dict[str, Any]]) -> None:
        """Baut die Multi-Service-Tabelle (19.01 Step 2).

        Sortiert ABSTEIGEND nach bar_time (E2), bildet die JSON-Union der
        feature_data-Keys (E4) und zeigt die Service-Spalte mit aufgeloesten
        Anzeigenamen (E3). Fehlende Werte bei abweichenden Services -> "-".
        """
        # E2: Chronologisch absteigend (deterministisch, stabil). Rows ohne
        # time landen dank `or 0` am Ende der absteigenden Anzeige.
        sorted_rows = sorted(
            (r for r in rows if isinstance(r, dict)),
            key=lambda r: _epoch_int(r.get("time")) or 0,
            reverse=True,
        )
        self._current_rows = sorted_rows

        # E4: Union aller feature_data-JSON-Keys (alphabetisch).
        extra_keys = sorted(self._union_feature_keys(sorted_rows))

        # Dynamischer Spaltenaufbau: Basis + Union-Keys.
        headers = [c[0] for c in _BASE_COLUMNS] + list(extra_keys)
        default_widths = ([c[1] for c in _BASE_COLUMNS]
                          + [_EXTRA_COLUMN_WIDTH] * len(extra_keys))
        header = self._table.horizontalHeader()
        vheader = self._table.verticalHeader()

        # 19.03 (E3/E4): Signale waehrend des Befuellens blockieren – sonst
        # wuerden setColumnWidth/setSortingEnabled/sortItems als User-Aktion
        # interpretiert und ein ungewolltes Dirty-Flag/Persistieren ausloesen.
        # Die In-Memory-Sortierung wird erst NACH dem Befuellen aktiviert
        # (O(n^2)-Schutz: QTableWidget sortiert sonst bei JEDEM setItem).
        self._table.setUpdatesEnabled(False)
        blocked = (self._table, header, vheader)
        for w in blocked:
            w.blockSignals(True)
        self._table.setSortingEnabled(False)
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        header.setStretchLastSection(False)
        # 19.03 (Step 1/E5): Interactive + gespeicherte Profil-Breiten
        # {Spaltenname: Breite} ueberschreiben die Defaults (fehlende neue
        # Union-Spalten -> _BASE_COLUMNS/_EXTRA_COLUMN_WIDTH).
        settings_widths = self._get_settings_widths()
        for i, name in enumerate(headers):
            header.setSectionResizeMode(i, QHeaderView.Interactive)
            self._table.setColumnWidth(
                i, int(settings_widths.get(name, default_widths[i])))

        # 19.04 (Paging): Seite zuruecksetzen und nur die aktuelle Seite
        # rendern (Seitenaufbau in _render_current_page/_populate_rows;
        # Sortierung/Settings werden dort angewendet).
        self._current_page = 0
        self._render_current_page()
        self._table.setUpdatesEnabled(True)
        for w in blocked:
            w.blockSignals(False)

    # ------------------------------------------------------------------
    # 19.04: Paging (Muster statistic_win.py, Bugfix 08.08.2026)
    # ------------------------------------------------------------------
    def _prev_page(self) -> None:
        """Eine Seite zurueck (aktiviert sobald _current_page > 0)."""
        if self._current_page > 0:
            self._current_page -= 1
            self._render_current_page()

    def _next_page(self) -> None:
        """Eine Seite vor (aktiviert solange nicht auf der letzten Seite)."""
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._render_current_page()

    def _render_current_page(self) -> None:
        """Rendert die Zeilen der aktuellen Seite (19.04 Paging).

        `_current_rows` haelt ALLE geladenen Zeilen (bis Limit) – angezeigt
        wird nur der Ausschnitt `[current_page*page_size : +page_size]`.
        Die Signale sind waehrend des Neu-Befuellens blockiert (E4), damit
        setItem/sortItems nicht als User-Aktion (Dirty-Flag/Persistieren)
        gewertet werden. Nach dem Befuellen werden die Tabellen-Settings
        angewandt (Sortierung; bei aktiver User-Sortierung bleibt der
        Indikator erhalten).
        """
        page_size = self._page_size if self._page_size > 0 else 1
        total = len(self._current_rows)
        self._total_pages = max(1, (total + page_size - 1) // page_size)
        if self._current_page >= self._total_pages:
            self._current_page = max(0, self._total_pages - 1)
        start = self._current_page * page_size
        end = min(start + page_size, total)
        page_rows = self._current_rows[start:end]

        header = self._table.horizontalHeader()
        vheader = self._table.verticalHeader()
        blocked = (self._table, header, vheader)
        for w in blocked:
            w.blockSignals(True)
        try:
            self._table.setSortingEnabled(False)
            self._populate_rows(page_rows, start_offset=start)
            self._apply_table_settings()
        finally:
            for w in blocked:
                w.blockSignals(False)
        # 21.03.11 (Bug 6): Externe MTF-FC-Sortierung hat Vorrang vor der
        # Profil-Sortierung und wird nach JEDEM Befuellen erneut angewendet
        # (nur Anzeige, kein User-Setting, kein Dirty-Flag).
        if self._external_sort_mode:
            self._apply_external_sort()
        self._update_page_controls()

    def _populate_rows(
        self, rows: List[Dict[str, Any]], start_offset: int = 0
    ) -> None:
        """Befuellt die Tabellen-Zeilen einer Seite (19.04 Paging).

        Der UserRole+1 (E7, Jump-to-Chart-Row-Mapping) traegt den GLOBALEN
        `_current_rows`-Index (`start_offset + r`), damit ein Doppelklick
        unabhaengig von Seite und Anzeige-Sortierung die richtige Roh-Row
        trifft.
        """
        service_names = self._resolve_names(rows)
        extra_keys = sorted(self._union_feature_keys(self._current_rows))
        extra_start = len(_BASE_COLUMNS)

        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            global_r = start_offset + r
            # Zeit: Wanduhr-Formatierung (Invariante 7) + Roh-Epoch im
            # UserRole (numerische Sortierung, E2) + globaler Einfuege-Index
            # im UserRole+1 (Jump-to-Chart, E7).
            epoch = _epoch_int(row.get("time"))
            time_item = _SortableTimeItem(format_wanduhr_time(epoch))
            if epoch is not None:
                time_item.setData(Qt.UserRole, epoch)
            time_item.setData(Qt.UserRole + 1, global_r)
            self._table.setItem(r, _COL_TIME, time_item)
            # Spalte 1 = Service (feature_id bzw. Anzeigename, E3).
            self._table.setItem(r, _COL_SERVICE,
                                QTableWidgetItem(service_names[r] or "-"))
            # JSON-Union-Spalten: Wert aus feature_data, sonst "-".
            # 21.03.11 (Bug 6): Numerische Werte als `_SortableValueItem` mit
            # Rohwert im UserRole – die 'Signal-Staerke'-Sortierung der
            # MTF-FC-Filterleiste vergleicht dann numerisch statt lexiko-
            # grafisch ('9.5' < '10.2' korrekt).
            fd = row.get("feature_data")
            if not isinstance(fd, dict):
                fd = {}
            for ci, key in enumerate(extra_keys, start=extra_start):
                v = fd.get(key)
                if v is None:
                    self._table.setItem(r, ci, QTableWidgetItem("-"))
                elif isinstance(v, (int, float)):
                    item = _SortableValueItem(f"{v:.4g}")
                    item.setData(Qt.UserRole, float(v))
                    self._table.setItem(r, ci, item)
                else:
                    self._table.setItem(r, ci, QTableWidgetItem(str(v)))

    def _update_page_controls(self) -> None:
        """Synchronisiert Seitenlabel + Button-Zustaende (19.04 Paging)."""
        total = len(self._current_rows)
        self.label_page.setText(
            f"Seite {self._current_page + 1} / {max(self._total_pages, 1)}"
            f"  ({total} Zeilen)")
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(
            self._current_page < self._total_pages - 1)

    # ------------------------------------------------------------------
    # 19.03: Tabellen-Settings (Resizing / Sortierung / Profil-Persistenz)
    # ------------------------------------------------------------------
    def _on_header_section_resized(self, *args) -> None:
        """Spaltenbreite geaendert (User) -> Settings emittieren (19.03)."""
        self._emit_table_settings()

    def _on_vertical_section_resized(self, *args) -> None:
        """Zeilenhoehe geaendert (User) -> GANZE Tabelle live uebernehmen (19.06).

        Gewuenschtes Verhalten (Anwender): Das Ziehen einer Zeilenhöhe
        uebertraegt die neue Hoehe sofort auf ALLE Zeilen (live, ohne
        Refresh). Qt aendert beim Drag zunaechst nur die gezogene Zeile –
        dieser Handler uebernimmt danach die neue Hoehe (args[2] = newSize)
        per `setDefaultSectionSize` (Default fuer neue Zeilen) + `setRowHeight`
        (alle bestehenden Zeilen) auf die gesamte Tabelle. Die Header-Signale
        sind waehrenddessen blockiert (kein sectionResized-Signal-Sturm);
        danach wird die globale `row_height` emittiert (kein individuelles
        row_heights mehr, 19.06).
        """
        if len(args) >= 3:
            try:
                new_size = int(args[2])
            except (TypeError, ValueError):
                new_size = 0
        else:
            new_size = 0
        if new_size > 0:
            vheader = self._table.verticalHeader()
            vheader.blockSignals(True)
            try:
                vheader.setDefaultSectionSize(new_size)
                for r in range(self._table.rowCount()):
                    self._table.setRowHeight(r, new_size)
            finally:
                vheader.blockSignals(False)
        self._emit_table_settings()

    def _on_sort_indicator_changed(self, *args) -> None:
        """Sortier-Indikator geaendert (User) -> Settings emittieren (19.03)."""
        self._emit_table_settings()

    def _emit_table_settings(self) -> None:
        """Emittiert den kompletten Tabellen-Zustand (19.03 E5/E8/E9 / 19.06).

        Spaltenbreiten als {Header-Text: Breite} (E5 – robust gegenueber der
        dynamischen JSON-Union), **globale Zeilenhoehe** (E9/19.06: alle
        Zeilen identisch, nach einem Zeilen-Drag hat
        `_on_vertical_section_resized` die gesamte Tabelle bereits live auf
        die neue Hoehe gesetzt), Sortier-Spalte und -Richtung als Qt-Werte
        (E8). KEIN individuelles `row_heights` mehr (19.06-Korrektur: das
        Ziehen einer Zeile soll die GANZE Tabelle setzen und als globale
        `table_row_height` persistiert werden).
        """
        widths: Dict[str, int] = {}
        header = self._table.horizontalHeader()
        for i in range(self._table.columnCount()):
            item = self._table.horizontalHeaderItem(i)
            if item is not None:
                widths[str(item.text())] = int(header.sectionSize(i))
        vheader = self._table.verticalHeader()
        # 19.06: Globale Zeilenhöhe (alle Zeilen identisch). Nach einem
        # Zeilen-Drag sind alle Zeilen auf die neue Hoehe gesetzt.
        if self._table.rowCount() > 0:
            row_height = int(vheader.sectionSize(0))
        else:
            row_height = int(vheader.defaultSectionSize())
        sort_col = int(header.sortIndicatorSection())
        if sort_col < 0:
            sort_col = 0
        # PySide6: sortIndicatorOrder() liefert den Qt.SortOrder-Enum (nicht
        # direkt int-konvertierbar) – robust ueber den Enum-Vergleich mappen.
        order = header.sortIndicatorOrder()
        self.table_settings_changed.emit({
            "column_widths": widths,
            "row_height": row_height,
            "sort_column": sort_col,
            "sort_order": 1 if order == Qt.DescendingOrder else 0,
        })

    def _get_settings_widths(self) -> Dict[str, int]:
        """Gespeicherte Spaltenbreiten aus dem ViewModel (19.03 E5).

        {Spaltenname: Breite} – robust gegenueber der dynamischen JSON-Union
        (fehlende neue Spalten fallen auf _BASE_COLUMNS/_EXTRA_COLUMN_WIDTH
        zurueck). Defensiv: ohne ViewModel/leer -> {}.
        """
        if self._view_model is None:
            return {}
        raw = self._view_model.params.get("table_column_widths") or {}
        out: Dict[str, int] = {}
        for k, v in raw.items():
            try:
                w = int(v)
            except (TypeError, ValueError):
                continue
            if w > 0:
                out[str(k)] = w
        return out

    def _apply_table_settings(self) -> None:
        """Wendet die gespeicherten Tabellen-Settings an (19.03 E3/E8/E9).

        Wird am Ende von _populate gerufen (Header-Signale sind blockiert):
        **globale Zeilenhoehe** (E9/19.06: `setDefaultSectionSize` als
        Default fuer neue Zeilen + `setRowHeight` fuer ALLE bestehenden
        Zeilen – die GANZE Tabelle bekommt die gespeicherte Hoehe, keine
        individuellen Zeilenhoehen) und Sortier-Spalte/-Richtung (validiert,
        E8). Spaltenbreiten uebernimmt bereits der Spaltenaufbau aus
        _get_settings_widths(). Ohne ViewModel (z. B. Headless-Tests) bleibt
        die Sortierung deaktiviert – Settings gibt es nicht.
        """
        if self._view_model is None:
            return
        params = self._view_model.params
        # 19.06: Globale Zeilenhöhe auf die GESAMTE Tabelle anwenden
        # (Default fuer neue Zeilen + alle bestehenden Zeilen).
        try:
            row_height = int(params.get("table_row_height") or 0)
        except (TypeError, ValueError):
            row_height = 0
        if row_height > 0:
            vheader = self._table.verticalHeader()
            vheader.setDefaultSectionSize(row_height)
            for r in range(self._table.rowCount()):
                self._table.setRowHeight(r, row_height)
        # Sortierung (E8): Spalten-Index validieren, Order auf Qt-Werte klemmen.
        try:
            sort_col = int(params.get("table_sort_column") or 0)
        except (TypeError, ValueError):
            sort_col = 0
        try:
            sort_order = int(params.get("table_sort_order") or 1)
        except (TypeError, ValueError):
            sort_order = 1
        sort_order = (Qt.DescendingOrder if sort_order
                      else Qt.AscendingOrder)
        if not (0 <= sort_col < self._table.columnCount()):
            sort_col = 0
        self._table.setSortingEnabled(True)
        self._table.sortItems(sort_col, sort_order)

    # ------------------------------------------------------------------
    # 19.01 Step 2: Helfer (JSON-Union, Namensaufloesung)
    # ------------------------------------------------------------------
    @staticmethod
    def _union_feature_keys(rows: List[Dict[str, Any]]) -> set:
        """Union aller feature_data-JSON-Keys (19.01 E4 / 19.02).

        19.02: Es gibt keine nativen Spalten mehr – es werden nur noch die
        Basis-/Pflicht-Spalten (Zeit, Service) von der Union ausgenommen
        (keine Duplikat-Header); leere/Whitespace-Keys ebenfalls.
        """
        base = {c[0] for c in _BASE_COLUMNS}
        keys: set = set()
        for row in rows:
            fd = row.get("feature_data")
            if not isinstance(fd, dict):
                continue
            for k in fd.keys():
                s = str(k).strip()
                if s and s not in base:
                    keys.add(s)
        return keys

    def _resolve_names(self, rows: List[Dict[str, Any]]) -> List[str]:
        """Loest die Service-Anzeigenamen der Rows einmalig auf (19.01 E3).

        Baut die deduplizierte feature_id-Liste (Reihenfolge des ersten
        Auftretens), ruft den injizierten `name_resolver` EINMAL auf und
        bildet die Namen auf die Rows ab. Rows ohne feature_id -> "-".
        Defensiv: Fehler im Resolver / abweichende Laenge -> feature_id.
        """
        unique: List[str] = []
        index: Dict[str, int] = {}
        for row in rows:
            fid = row.get("feature_id")
            key = str(fid) if fid else ""
            if key not in index:
                index[key] = len(unique)
                unique.append(key)
        try:
            resolved = self._name_resolver(unique)
        except Exception:
            resolved = unique
        by_id = dict(zip(unique, resolved))
        out: List[str] = []
        for row in rows:
            fid = row.get("feature_id")
            key = str(fid) if fid else ""
            out.append(by_id.get(key, key) if key else "-")
        return out

    # ------------------------------------------------------------------
    # Jump-to-Chart (Variante 2)
    # ------------------------------------------------------------------
    def _on_double_clicked(self, item: QTableWidgetItem) -> None:
        if item is None or self._navigation_handler is None:
            return
        # 19.03 (E7): Bei aktiver QTableWidget-Sortierung entspricht die
        # Anzeige-Zeile nicht mehr der _current_rows-Reihenfolge – der
        # Roh-Row-Index wird stattdessen aus dem UserRole+1 des Zeit-Items
        # aufgeloest (unabhaengig von der Anzeige-Sortierung).
        time_item = self._table.item(item.row(), _COL_TIME)
        if time_item is None:
            return
        row_index = time_item.data(Qt.UserRole + 1)
        if row_index is None:
            return
        try:
            row_index = int(row_index)
        except (TypeError, ValueError):
            return
        if not (0 <= row_index < len(self._current_rows)):
            return
        # 19.01: Symbol/TF/Zeit kommen aus der Roh-Row (nicht aus festen
        # Spaltenpositionen – die Spalten sind jetzt dynamisch).
        row_data = self._current_rows[row_index]
        symbol = row_data.get("symbol")
        tf = row_data.get("timeframe")
        bar_time = row_data.get("time")
        if not symbol or not tf or bar_time is None:
            return
        try:
            bar_time = int(bar_time)
        except (TypeError, ValueError):
            return
        self._navigation_handler(str(symbol), str(tf), bar_time)

```

--------------------------------------------------

