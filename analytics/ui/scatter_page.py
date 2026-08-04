# analytics/ui/scatter_page.py
"""
scatter_page.py - Scatter-Seite der Analytics-UI (Phase 15.03).

Zeigt X/Y-Paare zweier nativer Feature-Spalten (ema_diff, rsi_14,
atr_normalized) als pyqtgraph-ScatterPlot. Ein Klick auf einen Punkt
oeffnet das Chart-Fenster an der neuesten Feature-Bar des Symbol/Timeframe
(Jump-to-Chart Variante 2, Aufloesung ueber den ViewModel).

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
        columns = view_model.native_columns
        params = view_model.params
        self._combo_x.blockSignals(True)
        self._combo_y.blockSignals(True)
        for col in columns:
            self._combo_x.addItem(col, col)
            self._combo_y.addItem(col, col)
        idx_x = self._combo_x.findData(params.get("scatter_x"))
        idx_y = self._combo_y.findData(params.get("scatter_y"))
        self._combo_x.setCurrentIndex(idx_x if idx_x >= 0 else 0)
        self._combo_y.setCurrentIndex(idx_y if idx_y >= 0 else 0)
        self._combo_x.blockSignals(False)
        self._combo_y.blockSignals(False)
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
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind != QUERY_SCATTER:
            return
        self._current_symbol = str(data.get("symbol") or "")
        self._current_timeframe = str(data.get("timeframe") or "M1")
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
