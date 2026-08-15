"""
analytics_view_model_query.py - Query-Orchestrierung, Refresh, Async-Worker-Management, Shutdown

23.07 God-File-Split (15.08.2026): Aus analytics/engine/analytics_view_model.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der AnalyticsViewModel-
Klasse als Mixin (Klasse AnalyticsViewModelQueryMixin).
"""

from typing import (
    Any,
    Dict,
    Iterable,
    Optional,
)

from analytics.engine.analytics_worker import (
    QUERY_TABLE,
    QUERY_HEATMAP,
    QUERY_HEATMAP_GENERIC,
    QUERY_OHLCV,
    QUERY_DAILY_OHLC,
    QUERY_SCATTER,
    QUERY_DISTRIBUTION,
    QUERY_FEATURES,
    AnalyticsAsyncWorker,
)

class AnalyticsViewModelQueryMixin:

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
