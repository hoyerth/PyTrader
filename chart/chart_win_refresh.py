"""
chart/chart_win_refresh.py - Refresh-/Lade-Methoden des Chart-Fensters (Seiten-Load, Refresh-Pipeline, Chart-Update)

23.03 God-File-Split (15.08.2026): Aus chart/chart_win.py extrahiert,
KEINE Logik-Aenderung. Enthaelt die Methoden der PyTraderChartWindow
als Mixin (Klasse ChartRefreshMixin).
"""

from PySide6.QtCore import QTimer

from chart.chart_win_workers import _clean_nan, find_null_fields, ChartDataSerializer
from db_service import TF_SECONDS_MAP

class ChartRefreshMixin:

    def _on_page_loaded(self, ok: bool) -> None:
        if ok:
            self._page_loaded = True
            # Initialer Refresh direkt (ohne Debounce), danach nur noch via Debounce
            self._safe_refresh_chart_data()

    def _safe_refresh_chart_data(self) -> None:
        """Startet den Chart-Refresh mit Fehler-Schutz.
        Stellt sicher, dass _is_loading_data bei einem Fehler zurueckgesetzt wird –
        sonst bleibt der Chart dauerhaft blockiert (keine Charts, TF/Symbol-Wechsel tot)."""
        try:
            self._do_refresh_chart_data()
        except Exception as e:
            print(f"❌ [ChartRefresh] Fehler: {e}")
            self._set_loading(False)

    def _set_loading(self, loading: bool) -> None:
        """Setzt _is_loading_data und startet/stoppt den Watchdog konsistent."""
        self._is_loading_data = loading
        if loading:
            self._loading_watchdog.start()
        else:
            self._loading_watchdog.stop()

    def _on_loading_watchdog(self) -> None:
        """Watchdog-Timeout: Ein Chart-Refresh haengt zu lange (z. B. durch Fehler).
        Setzt das Flag zurueck, damit TF-/Symbol-Wechsel wieder funktionieren."""
        print(f"⚠️ [ChartRefresh] Watchdog: Refresh haengt ({self.current_symbol} {self.current_tf}), setze zurueck")
        self._is_loading_data = False

    def refresh_chart_data(self) -> None:
        """Debounced: Startet Chart-Refresh mit 400ms Verzögerung.
        Bei schnellen Mehrfach-Aufrufen wird nur der letzte ausgeführt."""
        if not self._page_loaded:
            QTimer.singleShot(200, self.refresh_chart_data)
            return
        self._debounce_timer.start()

    def _do_refresh_chart_data(self) -> None:
        """Führt den tatsächlichen Chart-Refresh aus (nur via Debounce-Timer).

        Phase 16.07 (Two-Tier, D1/D2/D5/D6/D8/D10):
          * Tier 2: `ChartDataBuffer.load_initial()` lädt M + Warmup aus
            DuckDB (D2: M=10000; D6: reiner Lese-Vorlauf für MAs).
          * Tier 1: JS erhält das letzte Tier-1-Fenster (D1: N=1000).
          * Indikator-Berechnung läuft über den vollen Tier-2-Puffer (D5),
            das Render-Payload wird auf das Tier-1-Fenster begrenzt.
          * `hasMoreHistory` (D8) und `rangeFrom/rangeTo` (D10, offsetbasiert
            relativ zum rechten Rand) gehen in den Payload.
        """
        if self._is_loading_data:
            self._debounce_timer.start()
            return

        self._set_loading(True)

        print(f"📊 Lade Chart-Daten (Two-Tier): {self.current_symbol} {self.current_tf}")

        # D6: Warmup-Vorlauf (period*4 + smoothing*3) nur für aktive
        # Gleitdurchschnitts-Indikatoren; Grid/Proximity => 0.
        warmup = self._compute_warmup()

        # Tier 2: RAM-Puffer (M + Warmup) aus DuckDB füllen (D2/D6).
        self.chart_buffer.load_initial(
            self.current_symbol, self.current_tf, warmup=warmup,
            limit=self.chart_buffer.TIER2_CAPACITY)
        # D6: Datenfenster-Grösse (M + Warmup) an den MA-Indikator melden,
        # damit die Berechnung über den vollen Tier-2-Puffer läuft (D5).
        self._apply_data_window_size()
        self.df_data = self.chart_buffer.df

        # Tier-1-Fenster (D1: letzte N Kerzen) mit kontinuierlichen Zeiten.
        continuous_candles = self.chart_buffer.window_candles(
            self.chart_buffer.TIER1_WINDOW)
        precision = self.chart_buffer.precision
        print(f"   → Tier2={len(self.chart_buffer.candles)} (warmup={warmup}), "
              f"Tier1={len(continuous_candles)} Candles, precision={precision}")

        # JS-Fenster-Bounds (reale Wanduhr-Epochs) für Render-Payload-Filter.
        n_win = min(self.chart_buffer.TIER1_WINDOW, len(self.chart_buffer.candles))
        self._js_window_first_real = (
            int(self.chart_buffer.candles[-n_win]["time"]) if n_win > 0 else None)
        self._js_window_last_real = self.chart_buffer.last_real

        # P14-03-E (PFLICHT, Pruefprotokoll P5): Offene Live-Kerze nach dem
        # Map-Rebuild (load_initial hat die Maps IN-PLACE neu aufgebaut)
        # re-injizieren – sonst feuert der New-Candle-Callback bei jedem Tick
        # erneut und die Flacker-Schleife bleibt bestehen.
        t_sec = self.chart_buffer.tf_seconds
        if (self._live_bar_time is not None
                and self._live_bar_time not in self._time_real_to_cont):
            last_cont = max(self._time_cont_to_real.keys()) if self._time_cont_to_real else 0
            cont = last_cont + t_sec
            self._time_cont_to_real[cont] = self._live_bar_time
            self._time_real_to_cont[self._live_bar_time] = cont
            if self._live_candle_cont is not None:
                lc = dict(self._live_candle_cont)
                lc["time"] = cont
                continuous_candles.append(lc)

        # P16.05 (Prework Schritt 1): Generische Payload-Aggregation über
        # ALLE aktiven Indikatoren (P-D1/F1/P-C2). Phase 16.07 (D1): auf das
        # Tier-1-Fenster begrenzt (die Berechnung lief über den vollen Puffer).
        render_payload = self._collect_render_payload(
            time_from=self._js_window_first_real,
            time_to=self._js_window_last_real)

        # P14-03-E (Flacker-Fix, generisch): plugin.calculate() setzt die
        # _known_times der Indikatoren auf die DB-Bars zurück – die offene
        # Live-Bar (noch nicht in DuckDB) geht dabei verloren. Würde sie nicht
        # DANACH wieder eingefügt, feuert der New-Candle-Callback bei jedem
        # Live-Tick (500ms) erneut und der Chart flackert im Wechsel
        # Live-Plot <-> Chart-Rebuild (alte/leere Kerze). Re-Injektion über
        # ALLE Indikatoren mit remember_live_time()-Hook (Open/Closed, kein
        # Plugin-Sonderfall).
        self._reinject_live_bar_to_indicators()

        update_package = {
            "symbol": self.current_symbol,
            "timeframe": self.current_tf,
            "candles": continuous_candles,
            "precision": precision,
            # P16.05 (P-C3/F4): chartRenderPayload (analog gridLines/
            # gridCircles) – applyFullChartUpdate ruft die generische
            # JS-Pipeline applyChartRenderPayload(chartRenderPayload) auf.
            "chartRenderPayload": render_payload,
            "measurementState": self.measurement_state,
            "timeMap": self._time_cont_to_real,
            # TF_SECONDS_MAP: Python ist die Single Source of Truth. JS nutzt
            # diesen Payload, statt sich auf seine eingebettete Offline-Map zu
            # verlassen (kein Duplikat-Pflege-Problem mehr).
            "tfSecondsMap": TF_SECONDS_MAP,
            # D8: Stop-Flag – JS stellt am linken Rand keine weiteren
            # Nachlade-Requests, wenn die DB keine ältere Geschichte mehr hat.
            "hasMoreHistory": self.chart_buffer.has_more_history,
        }

        # Generations-Guard: monotone Update-ID für Race-Schutz im JS.
        # WICHTIG: Wird VOR dem Serializer-Start inkrementiert, damit jeder
        # Refresh eine eindeutig hoehere ID als der vorherige erhaelt.
        self._update_generation += 1
        update_id = self._update_generation
        update_package["updateId"] = update_id

        # D10: Restore offsetbasiert relativ zum rechten Rand (Chunk-
        # Koordinaten, umbruchfest) – in logische Indizes übersetzen.
        range_from, range_to = self._resolve_visible_logical_range(
            len(continuous_candles))
        if range_from is not None and range_to is not None:
            update_package["rangeFrom"] = range_from
            update_package["rangeTo"] = range_to

        if self.visible_price_from is not None and self.visible_price_to is not None:
            update_package["priceFrom"] = float(self.visible_price_from)
            update_package["priceTo"] = float(self.visible_price_to)

        # NaN/Inf-Werte aus dem gesamten Payload entfernen (sonst JSON-Fehler im Serializer)
        update_package = _clean_nan(update_package)

        # JSON-Encoding im Hintergrund-Thread, um GUI-Ruckler zu vermeiden
        # Alten Serializer cleanen falls noch aktiv
        if self._chart_serializer is not None:
            try:
                self._chart_serializer.serialized.disconnect(self._apply_chart_update)
            except (RuntimeError, TypeError):
                pass
            if self._chart_serializer.isRunning():
                self._chart_serializer.quit()
                self._chart_serializer.wait(500)
            self._chart_serializer = None

        self._chart_serializer = ChartDataSerializer(update_package, update_id)
        self._chart_serializer.serialized.connect(self._apply_chart_update)
        self._chart_serializer.start()

    def _apply_chart_update(self, payload: str, update_id: int) -> None:
        """Empfängt fertiges JSON aus dem Serializer-Thread und prüft es auf nulls.
        Generations-Guard: veraltete Payloads (langsamer Thread aus einem
        frueheren Symbol/TF-Stand) werden verworfen, bevor sie JS erreichen."""
        # Veraltetes Update verwerfen – ein neuerer Refresh hat bereits begonnen
        if update_id < self._update_generation:
            print(f"⚠️ [ChartUpdate] Veraltetes Update verworfen (id={update_id} < {self._update_generation})")
            return
        if not payload:
            self._set_loading(False)
            return

        # ======================================================================
        # DEBUG-CHECK: Identifiziert das exakte null-Objekt in Python!
        # ======================================================================
        try:
            import json as _json
            data = _json.loads(payload)
            null_paths = find_null_fields(data)
            if null_paths:
                print(f"🚨 [NULL DETECTED in {self.current_symbol} {self.current_tf}] Gefundene null-Pfade:")
                for p in null_paths[:15]:  # Zeige die ersten 15 Treffer
                    print(f"   -> {p}")
        except Exception as debug_err:
            print(f"⚠️ [NullCheck] Fehler: {debug_err}")
        # ======================================================================

        try:
            if hasattr(self, "web_view") and self.web_view and self.web_view.page():
                self.web_view.page().runJavaScript(
                    f"if(window.applyFullChartUpdate) applyFullChartUpdate({payload});"
                )
        except (RuntimeError, AttributeError):
            pass
        finally:
            QTimer.singleShot(500, self._unlock_tracking)

    def _unlock_tracking(self):
        try:
            self._set_loading(False)
            self.update_indicator_button_style()
        except (RuntimeError, AttributeError):
            pass
