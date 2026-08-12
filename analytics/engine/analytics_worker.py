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

        if self._query_kind == QUERY_TABLE:
            return repo.get_table(
                symbol, timeframe,
                feature_id=p.get("feature_id"),
                feature_ids=feature_ids,
                instance_hashes=instance_hashes,
                limit=cap_lookback_limit(p.get("limit")),
                from_ts=from_ts, to_ts=to_ts,
            )
        if self._query_kind == QUERY_HEATMAP:
            return repo.get_heatmap(
                symbol, timeframe,
                metric=str(p.get("metric", "count") or "count"),
                feature_id=p.get("feature_id"),
                feature_ids=feature_ids,
                instance_hashes=instance_hashes,
                from_ts=from_ts, to_ts=to_ts,
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
            )

        raise ValueError(
            f"[AnalyticsAsyncWorker] Unbekannte Abfrage '{self._query_kind}' – "
            f"erlaubt: {QUERY_TABLE}, {QUERY_HEATMAP}, {QUERY_HEATMAP_GENERIC}, "
            f"{QUERY_OHLCV}, {QUERY_DAILY_OHLC}, {QUERY_SCATTER}, "
            f"{QUERY_DISTRIBUTION}, {QUERY_FEATURES}."
        )
