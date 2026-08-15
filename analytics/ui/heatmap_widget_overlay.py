"""
heatmap_widget_overlay.py - Candle-Overlay, Preis-View, Grid-Linien, Overlay-Clear

23.09 God-File-Split (15.08.2026): Aus analytics/ui/heatmap_widget.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der HeatmapWidget-
Klasse als Mixin (Klasse HeatmapWidgetOverlayMixin).
"""

import math

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import numpy as np

import pyqtgraph as pg

from analytics.ui.heatmap_widget_constants import (
    _DAY_SECONDS,
    _TF_SECONDS,
)

class HeatmapWidgetOverlayMixin:

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
