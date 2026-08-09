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
   hour/dow_hour -> Ganzzahlen, kategorial -> Indizes); das ImageItem wird
   per setRect exakt auf diesen Bereich gemappt – nichts wird mehr ueber
   die Tagesgrenze hinaus gezeichnet.
4) Achsen-Zuordnung ist explizit (x_dim -> X, y_dim -> Y), kein Vertauschen
   mehr moeglich.
5) Dynamische X-Ticks je Zoom-Level: date -> Jahre/Monate/Tage -> Stunden ->
   Minuten (bis zur Minute, wie Chartfenster/TradingView).
6) Dasselbe Prinzip gilt fuer die Y-Achse und alle Massstaebe (hour,
   dow_hour, kategorial): je Zoom-Level werden mehr Zwischenwerte angezeigt.
"""

import math
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
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
    QUERY_DAILY_OHLC,
)
from analytics.engine.feature_store_reader import (
    DOW_LABELS,
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

# Tag in Sekunden (Wanduhr-Epoch-Basis fuer date-Achse).
_DAY_SECONDS = 86400
_HALF_DAY = 43200.0

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


class _HeatmapAxis(pg.AxisItem):
    """Achse mit dynamischen Ticks je Zoom-Level (Bugfix 09.08.2026).

    Die Achse traegt NATUERLICHE Werte (date -> Wanduhr-Epochs,
    hour/dow_hour -> Ganzzahlen, kategorial -> Indizes) und formatiert die
    Tick-Beschriftung abhaengig vom sichtbaren Bereich:
      - date:  Tage (grober Zoom) -> Stunden -> Minuten (enger Zoom)
      - hour/dow_hour: ganzzahlige Schritte, beim Zoom mehr Zwischenwerte
      - kategorial: Labels aus der zugehoerigen Liste
    """

    def __init__(self, orientation: str, **kwargs) -> None:
        super().__init__(orientation, **kwargs)
        self._dim: Optional[str] = None
        self._labels: List[str] = []

    def configure(self, dim: str, labels: List[str]) -> None:
        """Setzt Dimension + Label-Liste (kategoriale Achsen)."""
        self._dim = str(dim or "")
        self._labels = list(labels or [])

    # ------------------------------------------------------------------
    def tickValues(self, minVal, maxVal, maxTicks=5):
        if not self._dim:
            return super().tickValues(minVal, maxVal, maxTicks)
        if self._dim == "date":
            step = _pick_time_step(float(maxVal) - float(minVal),
                                   int(maxTicks))
            if step <= 0:
                return super().tickValues(minVal, maxVal, maxTicks)
            return [(step, _time_ticks(float(minVal), float(maxVal), step))]
        span = float(maxVal) - float(minVal)
        step = _nice_int_step(span, int(maxTicks))
        start = int(math.ceil(minVal / step)) * step
        values = [float(start + i * step)
                  for i in range(0, int((maxVal - start) / step) + 1)]
        return [(step, values)]

    def tickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            out.append(self._format(float(v), float(spacing)))
        return out

    # ------------------------------------------------------------------
    def _format(self, v: float, spacing: float) -> str:
        if self._dim == "date":
            dt = datetime.fromtimestamp(v, tz=dt_timezone.utc)
            if spacing >= _DAY_SECONDS:
                return dt.strftime("%d.%m.%y")
            if spacing >= 3600:
                return dt.strftime("%d.%m. %H:%M")
            return dt.strftime("%H:%M")
        if self._dim == "hour":
            return f"{int(round(v)) % 24:02d}:00"
        if self._dim == "dow":
            idx = int(round(v))
            if 0 <= idx < len(DOW_LABELS):
                return DOW_LABELS[idx]
            return str(idx)
        if self._dim == "dow_hour":
            vv = int(round(v))
            dow, hour = divmod(vv, 24)
            if 0 <= dow < 7 and 0 <= hour < 24:
                return f"{DOW_LABELS[dow]}_{hour:02d}"
            return str(vv)
        # Kategorial (timeframe/service_id/symbol): Labels aus der Liste.
        idx = int(round(v))
        if 0 <= idx < len(self._labels):
            return str(self._labels[idx])
        return str(int(round(v)))


class HeatmapWidget(QWidget):
    """Generische 2D-Heatmap mit Confluence-Matrix, Zoom & Candle-Overlay."""

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

        # --- Plot: Heatmap + Kerzen-Overlay im SELBEN Canvas (Bugfix 1) ---
        self._plot_hm = pg.PlotWidget()
        self._plot_hm.setBackground("w")
        # Dynamische Achsen (Bugfix 5+6): Ticks je Zoom-Level.
        self._axis_x = _HeatmapAxis("bottom")
        self._axis_y = _HeatmapAxis("left")
        self._plot_hm.plotItem.setAxisItems(
            {"bottom": self._axis_x, "left": self._axis_y})
        self._image = pg.ImageItem()
        self._plot_hm.addItem(self._image)
        self._cmap_viridis = pg.colormap.get(_VIRIDIS)
        self._cmap_confluence = pg.ColorMap(
            pos=_CONFLUENCE_POS, color=_CONFLUENCE_COLORS)
        self._image.setColorMap(self._cmap_viridis)
        self._colorbar = pg.ColorBarItem(
            colorMap=self._cmap_viridis, values=(0.0, 1.0))
        self._colorbar.setImageItem(self._image)

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
        self._plot_hm.plotItem.vb.sigResized.connect(self._update_price_view)

        lay = QVBoxLayout(self)
        lay.addLayout(ctrl)
        lay.addLayout(ctrl2)
        lay.addWidget(self._plot_hm, 1)

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
        """Fordert generische Heatmap (+ Tages-Ohlc bei Overlay) an."""
        if self._view_model is None:
            return
        self._view_model.request_heatmap_generic()
        if self._chk_candle.isChecked():
            self._view_model.request_daily_ohlc()

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
        """Aktiviert/Deaktiviert Feld-Combo und Overlay (E6/E9).

        Bugfix 09.08.2026 (Punkt 6): Die Zoom-Slider gelten fuer ALLE
        Dimensionen/Massstaebe (nicht nur date) – je Zoom-Level werden
        dynamisch mehr Zwischenwerte auf den Achsen angezeigt.
        """
        if self._view_model is None:
            return
        x_dim = str(self._combo_x.currentData() or "")
        agg = str(self._combo_agg.currentData() or "")
        self._slider_zoom_x.setEnabled(True)
        self._slider_zoom_y.setEnabled(True)
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
                "Tages-Ohlc ueber der Heatmap (gleicher Canvas, rechte "
                "Preis-Achse), horizontal synchronisiert (Bugfix 1).")
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
    # Candle-Overlay (Bugfix 1, im selben Canvas) + Zoom (E8)
    # ------------------------------------------------------------------
    def _on_candle_toggled(self, checked: bool) -> None:
        if self._syncing or self._view_model is None:
            return
        self._view_model.set_candle_projection(bool(checked))
        if checked:
            self._view_model.request_daily_ohlc()
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
        """Synchronisiert die Preis-ViewBox-Geometrie mit der Heatmap."""
        vb = self._plot_hm.plotItem.vb
        self._price_vb.setGeometry(vb.sceneBoundingRect())
        self._price_vb.linkedViewChanged(vb, self._price_vb.XAxis)

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def _on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind == QUERY_HEATMAP_GENERIC:
            self._render_generic(data)
        elif kind == QUERY_DAILY_OHLC:
            self._render_overlay(data)

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

        if matrix.size == 0:
            self._n_cols = self._n_rows = 0
            self._x_axis = []
            self._y_axis = []
            self._image.clear()
            self._label_info.setText("Keine Daten")
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

        # ImageItem exakt auf die natuerlichen Koordinaten mappen (Bugfix 3):
        # date-Spalten = Tage (zentriert auf Mitternacht), hour/dow_hour =
        # ganzzahlige Werte, kategorial = Indizes. Nichts wird ueber die
        # Tagesgrenze hinaus gezeichnet (Punkt 3).
        self._x_min, self._x_max = self._axis_bounds(self._x_axis, x_dim)
        self._y_min, self._y_max = self._axis_bounds(self._y_axis, y_dim)
        self._image.setRect(QRectF(
            self._x_min, self._y_min,
            self._x_max - self._x_min, self._y_max - self._y_min))

        # Dynamische Achsen konfigurieren (Bugfix 5+6).
        self._axis_x.configure(x_dim, data.get("x_labels") or [])
        self._axis_y.configure(y_dim, data.get("y_labels") or [])
        self._plot_hm.setLabel("bottom", _DIM_LABELS.get(x_dim, x_dim))
        self._plot_hm.setLabel("left", _DIM_LABELS.get(y_dim, y_dim))

        self._apply_x_range()
        self._apply_y_range()
        self._label_info.setText(f"{self._n_rows} x {self._n_cols}")

        # Bugfix 1/2: Bei aktivem Overlay den Tages-Ohlc-Snapshot laden.
        if self._chk_candle.isChecked() and self._view_model is not None:
            self._view_model.request_daily_ohlc()

    @staticmethod
    def _axis_bounds(axis: List[float], dim: str):
        """Koordinaten-Bereich [lo, hi] fuer eine Achse (natuerliche Werte)."""
        if not axis:
            return -0.5, 0.5
        lo = float(min(axis))
        hi = float(max(axis))
        if dim == "date":
            # Zellen = Tage, zentriert auf Mitternacht (Wanduhr).
            return lo - _HALF_DAY, hi + _HALF_DAY
        if dim in ("hour", "dow", "dow_hour"):
            # Ganzzahlige Werte (0-23 bzw. 0-167): Zellenbreite 1.
            return lo - 0.5, hi + 0.5
        # Kategorial (timeframe/service_id/symbol): Indizes 0..n-1.
        return -0.5, float(len(axis)) - 0.5

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
        """Zeichnet Tages-Ohlc ueber die Heatmap (selbes Canvas, Bugfix 1).

        Die Candles liegen in der Preis-ViewBox (rechte Y-Achse = Preis),
        X = Wanduhr-Mitternachts-Epoch je Tag – exakt die Spalten der
        date-Heatmap. Alpha 0.3-0.5 (E9).
        """
        self._clear_overlay()
        bars = data.get("bars") or []
        if not bars or not self._x_axis:
            return
        # Spalten-Index je Wanduhr-Tag (Mitternachts-Epoch).
        epoch_to_col = {int(round(e)): i for i, e in enumerate(self._x_axis)}
        candles: List[tuple] = []
        for b in bars:
            t = b.get("time")
            if t is None:
                continue
            try:
                t = int(t)
            except (TypeError, ValueError):
                continue
            col = epoch_to_col.get(t)
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
        ymin = min(c[3] for c in candles)
        ymax = max(c[2] for c in candles)
        if ymin == ymax:
            ymin -= 1.0
            ymax += 1.0
        pad = (ymax - ymin) * 0.05
        self._price_vb.setYRange(ymin - pad, ymax + pad, padding=0)
        # Candles: x = Mitternachts-Epoch, Breite in Tages-Sekunden.
        for t, o, h, l, c in candles:
            up = c >= o
            color = pg.mkColor(0, 180, 0, 140) if up \
                else pg.mkColor(220, 30, 30, 140)
            # Bugfix 08.08.2026: pg.BarGraphItem kennt KEIN top/bottom –
            # die pyqtgraph-API verlangt y0 + height.
            wick = pg.BarGraphItem(
                x=[float(t)], width=_DAY_SECONDS * 0.12,
                y0=l, height=max(h - l, 1e-9), brush=color, pen=color)
            body = pg.BarGraphItem(
                x=[float(t)], width=_DAY_SECONDS * 0.7,
                y0=min(o, c),
                height=max(max(o, c) - min(o, c), 1e-9),
                brush=color, pen=color)
            self._price_vb.addItem(wick)
            self._price_vb.addItem(body)
            self._candle_items.extend((wick, body))
        self._price_vb.setVisible(True)
        self._plot_hm.getAxis("right").setVisible(True)
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
