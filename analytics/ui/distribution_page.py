# analytics/ui/distribution_page.py
"""
distribution_page.py - Verteilungs-Seite der Analytics-UI (Phase 15.03).

Zeigt das Histogramm einer nativen Feature-Spalte (ema_diff, rsi_14,
atr_normalized) als pyqtgraph-BarGraphItem. Spalte und Bin-Anzahl sind
ueber die Steuerleiste einstellbar; die Bin-Aenderung laeuft ueber den
ViewModel-Debounce (200-300 ms, 15.03-Spezifikation).

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
        self._combo_column.blockSignals(True)
        for col in view_model.native_columns:
            self._combo_column.addItem(col, col)
        idx = self._combo_column.findData(params.get("distribution_column"))
        self._combo_column.setCurrentIndex(idx if idx >= 0 else 0)
        self._combo_column.blockSignals(False)
        self._slider_bins.blockSignals(True)
        self._slider_bins.setValue(int(params.get("bins") or 20))
        self._slider_bins.blockSignals(False)
        self._label_bins.setText(str(self._slider_bins.value()))
        view_model.data_ready.connect(self.on_data_ready)

    def request_data(self) -> None:
        if self._view_model is not None:
            self._view_model.request_distribution()

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind != QUERY_DISTRIBUTION:
            return
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
