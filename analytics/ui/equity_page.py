# analytics/ui/equity_page.py
"""
equity_page.py - Equity-Seite der Analytics-UI (Phase 15.03).

Platzhalter-Seite fuer die Equity-Analyse: Es existiert noch KEINE
Equity-Datenquelle in PyTrader (geplant fuer eine spaetere Phase). Die
Seite reserviert den pyqtgraph-Plotbereich und zeigt dauerhaft das
'No Data'-Overlay (15.03-Spezifikation: 'No Data'-Overlay).

MVVM (Invariante 4): Reine UI, keine Datenabfrage (noch kein
query_kind). Sobald eine Equity-Datenquelle existiert, wird diese Seite
additiv an einen neuen QUERY_*-Kanal des ViewModels angebunden.
"""

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

import pyqtgraph as pg

from analytics.ui.common import make_overlay_stack

_NO_DATA_MESSAGE = (
    "Equity-Analyse: noch keine Daten vorhanden "
    "(geplant fuer eine spaetere Phase)."
)


class EquityPage(QWidget):
    """Equity-Verlauf (Platzhalter mit dauerhaftem 'No Data'-Overlay)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None

        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.setLabel("bottom", "Zeit (Berlin Wanduhr)")
        self._plot.setLabel("left", "Equity")

        content = QWidget(self)
        lay = QVBoxLayout(content)
        lay.addWidget(QLabel("Equity-Verlauf"))
        lay.addWidget(self._plot)
        self._stack = make_overlay_stack(content, message=_NO_DATA_MESSAGE)
        self.setLayout(self._stack)
        # Dauerhaftes No-Data-Overlay (noch keine Equity-Datenquelle).
        self._stack.setCurrentIndex(1)

    def attach_view_model(self, view_model: Any) -> None:
        """Vorgesehen fuer die spaetere Equity-Anbindung (additiv)."""
        self._view_model = view_model

    def request_data(self) -> None:
        """No-op: noch keine Equity-Datenabfrage vorhanden."""
        return
