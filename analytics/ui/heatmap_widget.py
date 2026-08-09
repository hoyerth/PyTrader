# analytics/ui/heatmap_widget.py
"""
heatmap_widget.py - Generische 2D-Heatmap-Engine mit Confluence-Matrix,
Candle-Overlay & Dual-Axis-Zoom (Phase 20.02).

Additiv zur bestehenden HeatmapPage (Dow x Stunde, Standard-Modus): Dieses
Widget rendert die generische 2D-Matrix (freie Dimensionen + Aggregationen)
und den Preis-Strip (Candle-Overlay). MVVM (Invariante 4): KEIN SQL – die
Daten kommen ueber `data_ready(QUERY_HEATMAP_GENERIC | QUERY_OHLCV, data)`
vom ViewModel (Async-Worker).

Entscheidungen (Review 09.08.2026, E7-E9):
- E7: CONFLUENCE_COUNT -> diskrete Farbskala (0 = weiss, 1-2 = gelb/cyan,
  3-4 = orange, 5+ = dunkelrot); Wert-Aggregationen -> viridis (kontinuierlich).
- E8: Zoom = EIN Faktor-Slider pro Achse (Viewport-Skalierung, zentriert),
  normalisiert [0,1] (zoom_x_range/zoom_y_range), rein client-seitig via
  setXRange/setYRange (kein DB-Requery). Aktiv nur bei `date`-Achsen.
- E9: Candle-Overlay = Preis-Strip UNTER der Heatmap (Tages-Ohlc je
  Datums-Spalte, Alpha 0.3-0.5), horizontal mit der Heatmap synchronisiert
  (Zoom X wirkt auf beide). Aktiv nur bei X-Dimension `date`.
"""

from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_worker import (
    QUERY_HEATMAP_GENERIC,
    QUERY_OHLCV,
)
from analytics.engine.feature_store_reader import (
    HEATMAP_AGGREGATIONS,
    HEATMAP_DIMENSIONS,
)

# E7: Konfluenz-Farbskala (0 = weiss/transparent, 1-2 = gelb/cyan,
# 3-4 = orange, 5+ = dunkelrot) – Positionen 0..1 (Levels 0..5).
_CONFLUENCE_COLORS = [
    "#ffffff", "#ffff00", "#00ffff", "#ff8c00", "#ff6600", "#8b0000",
]
_CONFLUENCE_POS = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
_CONFLUENCE_LEVELS = (0.0, 5.0)
_VIRIDIS = "viridis"

# E6: Wert-Aggregationen benoetigen einen numerischen feature_data-JSON-Key.
_VALUE_AGGS = ("avg", "sum", "min", "max")
# E8: Zoom nur bei Achsen mit vielen diskreten Werten (date).
_ZOOMABLE_DIMS = ("date",)

# Max. Achsen-Beschriftungen vor Sparse-Ticks.
_MAX_TICK_LABELS = 24

_DIM_LABELS = {
    "date": "Datum",
    "dow": "Wochentag",
    "hour": "Stunde",
    "dow_hour": "Wochentag × Stunde",
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


class HeatmapWidget(QWidget):
    """Generische 2D-Heatmap mit Confluence-Matrix, Zoom & Candle-Overlay."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None
        self._n_cols = 0
        self._n_rows = 0
        self._x_dates: List[Any] = []      # Datum je Spalte (nur X=date)
        self._candle_items: List[Any] = []
        self._colormap_mode = _VIRIDIS
        self._syncing = False

        # --- Steuerung (Zeile 1: Dimensionen/Aggregation/Feld) ---
        self._combo_x = QComboBox()
        for d in HEATMAP_DIMENSIONS:
            self._combo_x.addItem(_DIM_LABELS.get(d, d), d)
        self._combo_y = QComboBox()
        for d in HEATMAP_DIMENSIONS:
            self._combo_y.addItem(_DIM_LABELS.get(d, d), d)
        self._combo_agg = QComboBox()
        for a in HEATMAP_AGGREGATIONS:
            self._combo_agg.addItem(_AGG_LABELS.get(a, a), a)
        self._combo_field = QComboBox()
        self._combo_field.setMinimumWidth(140)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("X-Achse:"))
        ctrl.addWidget(self._combo_x)
        ctrl.addWidget(QLabel("Y-Achse:"))
        ctrl.addWidget(self._combo_y)
        ctrl.addWidget(QLabel("Aggregation:"))
        ctrl.addWidget(self._combo_agg)
        ctrl.addWidget(QLabel("Feld:"))
        ctrl.addWidget(self._combo_field)
        ctrl.addStretch(1)

        # --- Steuerung (Zeile 2: Overlay + Zoom) ---
        self._chk_candle = QCheckBox("Kerzen-Overlay")
        self._slider_zoom_x = QSlider(Qt.Horizontal)
        self._slider_zoom_y = QSlider(Qt.Horizontal)
        self._label_info = QLabel("")
        self._label_info.setStyleSheet("color: #808080;")
        for s in (self._slider_zoom_x, self._slider_zoom_y):
            s.setRange(5, 100)
            s.setValue(100)
            s.setEnabled(False)
            s.setToolTip("Viewport-Zoom (zentriert): 100 % = volle Achse.")

        ctrl2 = QHBoxLayout()
        ctrl2.addWidget(self._chk_candle)
        ctrl2.addWidget(QLabel("Zoom X:"))
        ctrl2.addWidget(self._slider_zoom_x)
        ctrl2.addWidget(QLabel("Zoom Y:"))
        ctrl2.addWidget(self._slider_zoom_y)
        ctrl2.addWidget(self._label_info)
        ctrl2.addStretch(1)

        # --- Plot: Heatmap (oben) + Preis-Strip (unten, E9) ---
        self._plot_hm = pg.PlotWidget()
        self._plot_hm.setBackground("w")
        self._image = pg.ImageItem()
        self._plot_hm.addItem(self._image)
        self._cmap_viridis = pg.colormap.get(_VIRIDIS)
        self._cmap_confluence = pg.ColorMap(
            pos=_CONFLUENCE_POS, color=_CONFLUENCE_COLORS)
        self._image.setColorMap(self._cmap_viridis)
        self._colorbar = pg.ColorBarItem(
            colorMap=self._cmap_viridis, values=(0.0, 1.0))
        self._colorbar.setImageItem(self._image)

        self._plot_px = pg.PlotWidget()
        self._plot_px.setBackground("w")
        self._plot_px.setLabel("left", "Preis")
        self._plot_px.setLabel("bottom", "Datum")
        self._plot_px.setVisible(False)

        lay = QVBoxLayout(self)
        lay.addLayout(ctrl)
        lay.addLayout(ctrl2)
        lay.addWidget(self._plot_hm, 1)
        lay.addWidget(self._plot_px, 1)

        # --- Signale ---
        self._combo_x.currentIndexChanged.connect(self._on_config_changed)
        self._combo_y.currentIndexChanged.connect(self._on_config_changed)
        self._combo_agg.currentIndexChanged.connect(self._on_agg_changed)
        self._combo_field.currentIndexChanged.connect(self._on_config_changed)
        self._chk_candle.toggled.connect(self._on_candle_toggled)
        self._slider_zoom_x.valueChanged.connect(self._on_zoom_x_changed)
        self._slider_zoom_y.valueChanged.connect(self._on_zoom_y_changed)

    # ------------------------------------------------------------------
    # MVVM-Anbindung (von der HeatmapPage gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        self._view_model = view_model
        view_model.data_ready.connect(self._on_data_ready)
        self._sync_from_params()

    def is_candle_projection_enabled(self) -> bool:
        """True, wenn das Kerzen-Overlay aktiviert ist (E9)."""
        return self._chk_candle.isChecked()

    def request_data(self) -> None:
        """Fordert generische Heatmap (+ OHLCV-Snapshot bei Overlay) an."""
        if self._view_model is None:
            return
        self._view_model.request_heatmap_generic()
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
            field = str(p.get("heatmap_field") or "")
            if field and self._combo_field.findData(field) < 0:
                self._combo_field.addItem(field, field)
            self._set_combo_data(self._combo_field, field)
            self._chk_candle.setChecked(bool(
                p.get("candle_projection_enabled")))
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
        """Stellt den Zoom-Slider aus einem [lo, hi]-Bereich ein (E8)."""
        try:
            lo, hi = float(zrange[0]), float(zrange[1])
        except (TypeError, ValueError, IndexError):
            lo, hi = 0.0, 1.0
        if hi <= lo:
            lo, hi = 0.0, 1.0
        value = int(round((hi - lo) * 100.0))
        slider.blockSignals(True)
        slider.setValue(max(slider.minimum(), min(slider.maximum(), value)))
        slider.blockSignals(False)

    def _update_controls(self) -> None:
        """Aktiviert/Deaktiviert Zoom-Slider, Feld-Combo und Overlay (E6/E8/E9)."""
        if self._view_model is None:
            return
        x_dim = str(self._combo_x.currentData() or "")
        y_dim = str(self._combo_y.currentData() or "")
        agg = str(self._combo_agg.currentData() or "")
        self._slider_zoom_x.setEnabled(x_dim in _ZOOMABLE_DIMS)
        self._slider_zoom_y.setEnabled(y_dim in _ZOOMABLE_DIMS)
        is_value_agg = agg in _VALUE_AGGS
        self._combo_field.setEnabled(is_value_agg)
        if is_value_agg:
            self._combo_field.setToolTip(
                "Numerischer feature_data-JSON-Key (Feld) fuer AVG/SUM/MIN/MAX.")
        else:
            self._combo_field.setToolTip(
                "Nur fuer AVG/SUM/MIN/MAX relevant (E6); COUNT/CONFLUENCE "
                "ignorieren das Feld.")
        can_overlay = x_dim == "date"
        self._chk_candle.setEnabled(can_overlay)
        if can_overlay:
            self._chk_candle.setToolTip(
                "Preis-Strip (Tages-Ohlc) unter der Heatmap, horizontal "
                "synchronisiert (E9).")
        else:
            self._chk_candle.setToolTip(
                "Kerzen-Overlay nur bei X-Achse 'Datum' verfuegbar (E9).")

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
        # Overlay nur bei X=date (E9) – sonst ausschalten.
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

    def _apply_config(self) -> None:
        self._view_model.set_heatmap_config(
            x_dim=str(self._combo_x.currentData() or "date"),
            y_dim=str(self._combo_y.currentData() or "hour"),
            field=str(self._combo_field.currentData() or ""),
            agg=str(self._combo_agg.currentData() or "confluence_count"),
        )

    # ------------------------------------------------------------------
    # Candle-Overlay (E9) + Zoom (E8)
    # ------------------------------------------------------------------
    def _on_candle_toggled(self, checked: bool) -> None:
        if self._syncing or self._view_model is None:
            return
        self._view_model.set_candle_projection(bool(checked))
        if checked:
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
        """Berechnet [lo, hi] (zentriert) aus dem Slider-Wert (E8)."""
        f = value / 100.0
        lo = max(0.0, 0.5 - f / 2.0)
        hi = min(1.0, 0.5 + f / 2.0)
        zx = list(self._view_model.params.get("zoom_x_range") or [0.0, 1.0])
        zy = list(self._view_model.params.get("zoom_y_range") or [0.0, 1.0])
        if key == "zoom_x_range":
            zx = [lo, hi]
        else:
            zy = [lo, hi]
        self._view_model.set_heatmap_zoom(zx, zy)

    def _apply_x_range(self) -> None:
        """Wendet zoom_x_range auf Heatmap + Preis-Strip an (E8/E9)."""
        if self._view_model is None or self._n_cols <= 0:
            return
        try:
            lo, hi = self._view_model.params["zoom_x_range"]
            lo, hi = float(lo), float(hi)
        except (TypeError, ValueError, IndexError, KeyError):
            lo, hi = 0.0, 1.0
        n = float(self._n_cols)
        self._plot_hm.setXRange(-0.5 + lo * n, -0.5 + hi * n, padding=0)
        if self._plot_px.isVisible():
            self._plot_px.setXRange(-0.5 + lo * n, -0.5 + hi * n, padding=0)

    def _apply_y_range(self) -> None:
        """Wendet zoom_y_range auf die Heatmap an (E8)."""
        if self._view_model is None or self._n_rows <= 0:
            return
        try:
            lo, hi = self._view_model.params["zoom_y_range"]
            lo, hi = float(lo), float(hi)
        except (TypeError, ValueError, IndexError, KeyError):
            lo, hi = 0.0, 1.0
        m = float(self._n_rows)
        self._plot_hm.setYRange(-0.5 + lo * m, -0.5 + hi * m, padding=0)

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def _on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind == QUERY_HEATMAP_GENERIC:
            self._render_generic(data)
        elif kind == QUERY_OHLCV:
            self._render_overlay(data)

    def _render_generic(self, data: Dict[str, Any]) -> None:
        matrix = np.asarray(data.get("matrix") or [], dtype=float)
        x_dim = str(data.get("x_dim") or self._combo_x.currentData() or "date")
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

        if matrix.size == 0:
            self._n_cols = self._n_rows = 0
            self._image.clear()
            self._label_info.setText("Keine Daten")
            self._clear_overlay()
            return

        self._n_cols = int(matrix.shape[1])
        self._n_rows = int(matrix.shape[0])

        # E7: Colormap abhaengig von der Aggregation.
        if agg == "confluence_count":
            if self._colormap_mode != "confluence":
                self._image.setColorMap(self._cmap_confluence)
                try:
                    self._colorbar.setColorMap(self._cmap_confluence)
                except Exception:
                    pass
                self._colormap_mode = "confluence"
            self._image.setImage(matrix, levels=_CONFLUENCE_LEVELS)
            self._colorbar.setLevels(_CONFLUENCE_LEVELS)
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

        self._plot_hm.getAxis("bottom").setTicks(
            [self._sparse_ticks(data.get("x_labels") or [])])
        self._plot_hm.getAxis("left").setTicks(
            [self._sparse_ticks(data.get("y_labels") or [])])
        self._plot_hm.setXRange(-0.5, self._n_cols - 0.5, padding=0)
        self._plot_hm.setYRange(-0.5, self._n_rows - 0.5, padding=0)
        self._apply_x_range()
        self._apply_y_range()
        self._label_info.setText(f"{self._n_rows} x {self._n_cols}")

        # E9: Bei aktivem Overlay den OHLCV-Snapshot (nach-)laden.
        if self._chk_candle.isChecked() and self._view_model is not None:
            self._view_model.request_ohlcv_snapshot()

    def _sync_combos_from_payload(self, data: Dict[str, Any]) -> None:
        """Synchronisiert die Combos mit dem tatsaechlichen Payload."""
        if self._view_model is None:
            return
        metrics = [str(m) for m in (data.get("metrics") or [])]
        keys = [m for m in metrics if m not in ("count", "confluence_count")]
        agg = str(data.get("agg") or "")
        prev_field = str(self._combo_field.currentData() or "")
        self._syncing = True
        try:
            self._combo_field.blockSignals(True)
            self._combo_field.clear()
            for k in keys:
                self._combo_field.addItem(k, k)
            if prev_field in keys:
                self._combo_field.setCurrentIndex(
                    self._combo_field.findData(prev_field))
            elif keys:
                self._combo_field.setCurrentIndex(0)
            self._combo_field.blockSignals(False)
            self._set_combo_data(
                self._combo_x, str(data.get("x_dim") or "date"))
            self._set_combo_data(
                self._combo_y, str(data.get("y_dim") or "hour"))
            self._set_combo_data(self._combo_agg, str(agg or "count"))
        finally:
            self._syncing = False
        self._update_controls()
        # E6: Wert-Aggregation mit noch leerem Feld -> ersten Key uebernehmen
        # und Konfiguration nachreichen (einmaliger Query-Loop).
        if (agg in _VALUE_AGGS and self._combo_field.currentData()
                and self._view_model.params.get("heatmap_field")
                != self._combo_field.currentData()):
            self._apply_config()

    def _render_overlay(self, data: Dict[str, Any]) -> None:
        """Zeichnet den Preis-Strip (Tages-Ohlc je Datums-Spalte, E9)."""
        self._clear_overlay()
        bars = data.get("bars") or []
        if not bars or not self._x_dates:
            return
        date_to_col = {d: i for i, d in enumerate(self._x_dates)
                       if d is not None}
        if not date_to_col:
            return
        # Bars nach Wanduhr-Datum gruppieren (Epochs als UTC dekodieren).
        by_date: Dict[Any, List[Dict[str, Any]]] = {}
        for b in bars:
            t = b.get("time")
            if t is None:
                continue
            try:
                d = datetime.fromtimestamp(int(t),
                                           tz=dt_timezone.utc).date()
            except (TypeError, ValueError, OSError, OverflowError):
                continue
            by_date.setdefault(d, []).append(b)
        # Tages-Ohlc je Spalte.
        candles: List[tuple] = []
        for d, col in date_to_col.items():
            day_bars = by_date.get(d)
            if not day_bars:
                continue
            try:
                o = float(day_bars[0]["open"])
                c = float(day_bars[-1]["close"])
                h = max(float(x["high"]) for x in day_bars)
                l = min(float(x["low"]) for x in day_bars)
            except (TypeError, ValueError, KeyError):
                continue
            if not (np.isfinite(o) and np.isfinite(c)
                    and np.isfinite(h) and np.isfinite(l)):
                continue
            candles.append((col, o, h, l, c))
        if not candles:
            return
        ymin = min(c[3] for c in candles)
        ymax = max(c[2] for c in candles)
        if ymin == ymax:
            ymin -= 1.0
            ymax += 1.0
        pad = (ymax - ymin) * 0.05
        ymin -= pad
        ymax += pad
        for col, o, h, l, c in candles:
            up = c >= o
            color = pg.mkColor(0, 180, 0, 140) if up \
                else pg.mkColor(220, 30, 30, 140)
            wick = pg.BarGraphItem(x=[col + 0.5], width=0.12,
                                   top=h, bottom=l, brush=color, pen=color)
            body = pg.BarGraphItem(x=[col + 0.5], width=0.7,
                                   top=max(o, c), bottom=min(o, c),
                                   brush=color, pen=color)
            self._plot_px.addItem(wick)
            self._plot_px.addItem(body)
            self._candle_items.extend((wick, body))
        self._plot_px.setYRange(ymin, ymax, padding=0)
        self._plot_px.setXRange(-0.5, max(1, self._n_cols) - 0.5, padding=0)
        self._plot_px.show()
        self._apply_x_range()

    def _clear_overlay(self) -> None:
        """Entfernt alle Kerzen-Items und versteckt den Preis-Strip."""
        for item in self._candle_items:
            try:
                self._plot_px.removeItem(item)
            except Exception:
                pass
        self._candle_items = []
        self._plot_px.setVisible(False)

    # ------------------------------------------------------------------
    # Helfer
    # ------------------------------------------------------------------
    @staticmethod
    def _sparse_ticks(labels: List[str]) -> List[tuple]:
        """Achsen-Ticks mit Sparse-Verfahren bei vielen Labels (z. B. date)."""
        n = len(labels)
        if n == 0:
            return []
        if n <= _MAX_TICK_LABELS:
            return [(i, str(labels[i])) for i in range(n)]
        step = max(1, n // _MAX_TICK_LABELS)
        ticks = [(i, str(labels[i])) for i in range(0, n, step)]
        if ticks[-1][0] != n - 1:
            ticks.append((n - 1, str(labels[-1])))
        return ticks
