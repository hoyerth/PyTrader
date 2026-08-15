"""
chart/chart_win_twotier.py - Two-Tier-Caching-Methoden des Chart-Fensters (Warmup, Datenfenster, Older-Data-Chunks)

23.03 God-File-Split (15.08.2026): Aus chart/chart_win.py extrahiert,
KEINE Logik-Aenderung. Enthaelt die Methoden der PyTraderChartWindow
als Mixin (Klasse ChartTwoTierMixin).
"""

import json

from typing import Any, Dict, List

from chart.chart_win_workers import _clean_nan, OlderDataWorker

class ChartTwoTierMixin:

    # ======================================================================
    # Phase 16.07 – Two-Tier Caching (D1–D10)
    # ======================================================================

    def _compute_warmup(self) -> int:
        """D6: Warmup-Vorlauf = period*4 + smoothing*3 – NUR für aktive
        Gleitdurchschnitts-Indikatoren (Multi-MA). Grid-/Proximity-
        Indikatoren brauchen keinen Vorlauf (Warmup = 0).

        Der Vorlauf ist ein REINER LESE-Vorlauf (verworfen; der NaN-Vertrag
        period−1 bleibt unverändert) – er stellt sicher, dass die MA-Werte an
        der linken Tier-1-Kante voll eingeschwungen sind."""
        warmup = 0
        st = self.indicators_state.get("ind_moving_averages", {})
        if not st.get("active"):
            return 0
        try:
            params = self._resolve_indicator_params("ind_moving_averages", st)
        except Exception:
            return 0
        for x in range(1, 9):
            show = params.get(f"show_ma{x}")
            if x == 1:
                if show in (False, 0, "false", "False"):
                    continue
            else:
                if not show or show in (False, 0, "false", "False"):
                    continue
            try:
                period = int(params.get(f"ma{x}_period") or 0)
            except (TypeError, ValueError):
                period = 0
            try:
                smoothing = int(params.get(f"ma{x}_smoothing") or 0)
            except (TypeError, ValueError):
                smoothing = 0
            warmup = max(warmup, period * 4 + smoothing * 3)
        return warmup

    def _apply_data_window_size(self) -> None:
        """D6: Meldet die Tier-2-Datenfenster-Grösse (M + Warmup) an den
        Multi-MA-Indikator, damit die Berechnung über den VOLLEN Puffer läuft
        (D5) statt über den alten chart_candle_limit-Zuschnitt (3000)."""
        ind = self.indicators.get("ind_moving_averages")
        setter = getattr(ind, "set_data_window_size", None)
        if not callable(setter):
            return
        size = len(self.chart_buffer.df) if self.chart_buffer.df is not None else None
        try:
            setter(size)
        except Exception:
            pass

    def _resolve_visible_logical_range(self, total: int):
        """D10: Übersetzt die persistierten visible_from/visible_to in
        logische Indizes des aktuellen Tier-1-Fensters.

        NEUES Format (16.07): Offsets relativ zum rechten Rand (Chunk-
        Koordinaten, umbruchfest) – erkennbar an `visible_from > visible_to`
        (logisches from < to, daher ist der Abstand-von-rechts von from
        grösser als der von to).
        ALTES Format (Bestand): absolute logische Indizes (from < to) – wird
        auf das aktuelle Fenster geklemmt (Abwärtskompatibilität).

        Returns:
            (range_from, range_to) als ints oder (None, None).
        """
        if self.visible_from is None or self.visible_to is None:
            return None, None
        if not total or total <= 0:
            return None, None
        vf, vt = int(self.visible_from), int(self.visible_to)
        if vf > vt:
            # Neues Offset-Format: Abstand vom rechten Rand.
            f = max(0, total - vf)
            t = min(total - 1, total - vt)
            if t < f:
                f, t = total - 1, total - 1
            return f, t
        # Alt-Format: absolute Indizes -> klemmen.
        f = max(0, min(vf, total - 1))
        t = max(f + 1, min(vt, total))
        return f, t

    def _on_jump_to_live(self) -> None:
        """D9: „Live"-Button in JS -> vollständiger Refresh. Der Tier-2-Puffer
        wird aus DuckDB neu geladen, das Fenster springt ans Live-Ende."""
        if self._is_loading_data:
            return
        self.refresh_chart_data()

    def _on_older_data_requested(self, from_time_epoch: int, count: int,
                                 request_id: int, window_right_epoch: int) -> None:
        """D3/D4/D7: JS fordert ältere Daten an (zeitbasiert, Wanduhr-Epoch).

        Debounce (300 ms, D7): Nur der letzte Request innerhalb des
        Debounce-Fensters wird ausgeführt (schnelles Wischen erzeugt viele
        Range-Events). `request_id` = JS-seitiges Serial (Race-Guard)."""
        if self._is_loading_data:
            return
        self._older_request_serial = int(request_id)
        self._pending_older = (
            int(from_time_epoch), int(count), int(request_id),
            int(window_right_epoch or 0))
        self._older_debounce_timer.start()

    def _do_older_data_load(self) -> None:
        """Führt den debounced Nachlade-Request aus (GUI-Thread).

        Priorität 1: RAM-Serve aus dem Tier-2-Puffer (0 ms I/O, D3/D4).
        Priorität 2: Puffer nach links erschöpft -> DB-Chunk im
        OlderDataWorker (D7, Hintergrund-Thread), danach merge + serve.
        """
        if not self._pending_older:
            return
        from_epoch, count, request_id, _wr = self._pending_older
        self._pending_older = None
        if self._is_loading_data:
            return

        # Priorität 1: RAM-Serve (Tier 2 -> Tier 1, keine DB-I/O).
        result = self.chart_buffer.serve_older(from_epoch, count)
        if result is not None:
            new_candles, window_right, has_more = result
            first_cont = int(new_candles[0]["time"])
            self._js_window_first_real = self._time_cont_to_real.get(
                first_cont, first_cont)
            self._send_older_chunk(new_candles, window_right, has_more, request_id)
            return

        # Priorität 2: Puffer erschöpft -> DB-Chunk (D7).
        self._last_older_count = int(count)
        self._last_older_warmup = self._compute_warmup()
        if self._older_worker is not None and self._older_worker.isRunning():
            # Ein alter Fetch läuft noch – abbrechen (neuer Request gewinnt).
            try:
                self._older_worker.done.disconnect(self._on_older_db_fetched)
            except (RuntimeError, TypeError):
                pass
            self._older_worker.quit()
            self._older_worker.wait(300)
        worker = OlderDataWorker(
            self.market_repo, self.current_symbol, self.current_tf,
            from_epoch, self._last_older_count + self._last_older_warmup,
            request_id, self)
        self._older_worker = worker
        worker.done.connect(self._on_older_db_fetched)
        worker.start()

    def _on_older_db_fetched(self, request_id: int, fetched: list, success: bool) -> None:
        """Merge + Serve nach DB-Fetch (GUI-Thread).

        Generations-Guard über request_id (D7): Veraltete Worker-Ergebnisse
        (inzwischen neuerer Request / Symbol/TF-Wechsel) werden verworfen."""
        worker = self._older_worker
        self._older_worker = None
        if not success or request_id != self._older_request_serial:
            return
        if self._is_loading_data:
            return
        new_candles, window_right, has_more = self.chart_buffer.merge_older(
            fetched, serve_count=self._last_older_count,
            warmup=self._last_older_warmup)
        self._apply_data_window_size()
        self.df_data = self.chart_buffer.df
        if new_candles:
            first_cont = int(new_candles[0]["time"])
            self._js_window_first_real = self._time_cont_to_real.get(
                first_cont, first_cont)
        # D10/Right-Edge-Sync: Nach evtl. Capacity-Trim ist die Puffer-Rechts-
        # kante die neue JS-Fenster-Rechtskante (JS kürzt in applyOlderDataChunk).
        if window_right:
            self._js_window_last_real = int(window_right)
        self._send_older_chunk(new_candles, window_right, has_more, request_id)

    def _send_older_chunk(self, new_candles: List[Dict[str, Any]],
                          window_right: int, has_more: bool, request_id: int) -> None:
        """Baut das Delta-Payload (D4) und sendet es an JS.

        Vertrag: {updateId, symbol, timeframe, candles, timeMapDelta,
        windowRightEpoch, hasMoreHistory, chartRenderPayloadDelta}.

        `chartRenderPayloadDelta.lines/hit_circles` = vollständig neu
        berechnetes Render-Payload über den vollen Tier-2-Puffer (D5),
        begrenzt auf das aktuelle Tier-1-Fenster [neue linke Kante, rechte
        Kante] – JS ersetzt die Linien/Marker damit nahtlos (kein Seam)."""
        if not new_candles:
            # DB-Ende / keine neuen Daten -> nur Stop-Flag senden (D8).
            payload = {
                "updateId": int(request_id),
                "symbol": self.current_symbol,
                "timeframe": self.current_tf,
                "candles": [],
                "timeMapDelta": {},
                "windowRightEpoch": int(window_right or 0),
                "hasMoreHistory": False,
                "chartRenderPayloadDelta": {"lines": [], "hit_circles": []},
            }
            self._send_older_json(payload)
            return

        first_cont = int(new_candles[0]["time"])
        window_left_real = self._time_cont_to_real.get(first_cont, first_cont)
        window_right_real = int(window_right or self._js_window_last_real or 0)

        render_payload = self._collect_render_payload(
            time_from=window_left_real, time_to=window_right_real)

        # P14-03-E (Flacker-Fix): Live-Bar-Re-Injektion nach dem calculate()-Loop.
        self._reinject_live_bar_to_indicators()

        # timeMapDelta: NUR die neuen (geprependeten) cont->real Einträge –
        # die bestehenden Kerzen behalten ihre cont-Zeiten (JS erweitert nur).
        time_map_delta: Dict[int, int] = {}
        for c in new_candles:
            cont = int(c["time"])
            real = self._time_cont_to_real.get(cont)
            if real is not None:
                time_map_delta[cont] = real

        payload = {
            "updateId": int(request_id),
            "symbol": self.current_symbol,
            "timeframe": self.current_tf,
            "candles": new_candles,
            "timeMapDelta": time_map_delta,
            "windowRightEpoch": window_right_real,
            "hasMoreHistory": bool(has_more),
            "chartRenderPayloadDelta": {
                "lines": render_payload.get("lines") or [],
                "hit_circles": render_payload.get("hit_circles") or [],
            },
        }
        self._send_older_json(_clean_nan(payload))

    def _send_older_json(self, payload: dict) -> None:
        """Serialisiert und sendet ein Chunk-Payload an JS (mit Fehler-Schutz)."""
        try:
            payload_json = json.dumps(payload, allow_nan=False)
        except (ValueError, TypeError) as e:
            print(f"⚠️ [OlderData] JSON-Fehler: {e}")
            return
        try:
            self.web_view.page().runJavaScript(
                f"if(window.applyOlderDataChunk) applyOlderDataChunk({payload_json});")
        except (RuntimeError, AttributeError):
            pass
