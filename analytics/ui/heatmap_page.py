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
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from analytics.engine.analytics_worker import QUERY_HEATMAP
from analytics.engine.feature_store_reader import (
    DOW_LABELS,
    DAYS_PER_WEEK,
    HOURS_PER_DAY,
)
from analytics.ui.common import make_overlay_stack

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

        # Metrik-Dropdown (count | native Spalten)
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
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Metrik:"))
        ctrl.addWidget(self._combo_metric)
        ctrl.addWidget(self._label_info)
        ctrl.addStretch(1)
        lay.addLayout(ctrl)
        lay.addWidget(self._plot)
        self._stack = make_overlay_stack(content)
        self.setLayout(self._stack)

        self._combo_metric.currentTextChanged.connect(self._on_metric_changed)
        self._plot.scene().sigMouseClicked.connect(self._on_plot_clicked)

    # ------------------------------------------------------------------
    # MVVM-Anbindung (vom AnalyticsWindow gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        self._view_model = view_model
        # Metrik-Dropdown befuellen (count + native Spalten)
        self._combo_metric.blockSignals(True)
        for metric in view_model.heatmap_metrics:
            self._combo_metric.addItem(metric, metric)
        idx = self._combo_metric.findData(view_model.params.get("heatmap_metric"))
        self._combo_metric.setCurrentIndex(idx if idx >= 0 else 0)
        self._combo_metric.blockSignals(False)
        view_model.data_ready.connect(self.on_data_ready)

    def set_navigation_handler(self, fn: Callable[[str, str, int], None]) -> None:
        self._navigation_handler = fn

    def set_cell_resolver(
        self, fn: Callable[[str, str, int, int], Optional[int]]
    ) -> None:
        """Setzt die Zell-Aufloesung (dow, hour -> neuester bar_time)."""
        self._cell_resolver = fn

    def request_data(self) -> None:
        if self._view_model is not None:
            self._view_model.request_heatmap()

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind != QUERY_HEATMAP:
            return
        self._current_symbol = str(data.get("symbol") or "")
        self._current_timeframe = str(data.get("timeframe") or "M1")
        matrix = np.asarray(data.get("matrix"), dtype=float)
        if matrix.size == 0:
            self._stack.setCurrentIndex(1)
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
