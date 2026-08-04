# analytics/ui/table_page.py
"""
table_page.py - Tabellen-Seite der Analytics-UI (Phase 15.03).

Zeigt die rohen Feature-Store-Zeilen (Tabelle) und koppelt einen
Doppelklick an 'Jump-to-Chart' (Variante 2): open_chart_at_bar(symbol, tf,
bar_time) wird aufgerufen und das Chart-Fenster in den Vordergrund geholt.

MVVM (Invariante 4): Die Page ist reine UI – Rendering + Event-Handling.
Die Daten kommen ueber `data_ready(QUERY_TABLE, data)` vom ViewModel
(Async-Worker); es gibt KEIN SQL in dieser Klasse.
"""

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.analytics_worker import QUERY_TABLE
from analytics.ui.common import format_wanduhr_time, make_overlay_stack

# Datenvertrag der Tabellen-Spalten (feature_store-Zeilen).
_TABLE_COLUMNS = [
    ("Zeit (Wanduhr)", 150),
    ("Symbol", 90),
    ("TF", 60),
    ("Feature", 110),
    ("Version", 80),
    ("ema_diff", 90),
    ("rsi_14", 80),
    ("atr_normalized", 100),
]


class TablePage(QWidget):
    """Feature-Store-Tabelle mit Jump-to-Chart (Doppelklick)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._view_model = None
        self._navigation_handler: Optional[Callable[[str, str, int], None]] = None

        self._header = QLabel("Feature-Store-Tabelle")
        self._table = QTableWidget(0, len(_TABLE_COLUMNS))
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QTableWidget.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setHorizontalHeaderLabels([c[0] for c in _TABLE_COLUMNS])
        header = self._table.horizontalHeader()
        # Fix 15.03 (TF-Wechsel-Haenger): KEIN ResizeToContents! Der Modus
        # berechnet bei JEDEM setItem die optimale Breite ueber ALLE Zeilen
        # (O(n^2)) – bei 5000 Zeilen blockiert das den Main-Thread minuten-
        # lang. Stattdessen FIXE Spaltenbreiten aus _TABLE_COLUMNS
        # (deterministisch schnell, unabhaengig von der Zeilenanzahl).
        header.setStretchLastSection(False)
        for i, (_, width) in enumerate(_TABLE_COLUMNS):
            header.setSectionResizeMode(i, QHeaderView.Fixed)
            self._table.setColumnWidth(i, width)

        content = QWidget(self)
        lay = QVBoxLayout(content)
        lay.addWidget(self._header)
        lay.addWidget(self._table)
        self._stack = make_overlay_stack(content)
        self.setLayout(self._stack)

        self._table.itemDoubleClicked.connect(self._on_double_clicked)

    # ------------------------------------------------------------------
    # MVVM-Anbindung (vom AnalyticsWindow gesetzt)
    # ------------------------------------------------------------------
    def attach_view_model(self, view_model: Any) -> None:
        """Verbindet die Page mit dem AnalyticsViewModel (data_ready)."""
        self._view_model = view_model
        view_model.data_ready.connect(self.on_data_ready)

    def set_navigation_handler(
        self, fn: Callable[[str, str, int], None]
    ) -> None:
        """Setzt den Jump-to-Chart-Handler (open_chart_at_bar)."""
        self._navigation_handler = fn

    def request_data(self) -> None:
        """Fordert die Tabellen-Daten ueber das ViewModel an."""
        if self._view_model is not None:
            self._view_model.request_table()

    # ------------------------------------------------------------------
    # Datenfluss (UI rendert, KEIN SQL)
    # ------------------------------------------------------------------
    def on_data_ready(self, kind: str, data: Dict[str, Any]) -> None:
        if kind != QUERY_TABLE:
            return
        if not self.isVisible():
            # Fix 15.03 (TF-Wechsel-Haenger): Die Tabelle wird NUR gerendert,
            # wenn sie die aktive/ sichtbare Seite ist. data_ready feuert bei
            # jedem TF-Wechsel fuer ALLE Seiten; ein versteckter 5000-Zeilen-
            # Render (ResizeToContents + Sortierung) wuerde den Main-Thread
            # blockieren. Beim Aktivieren der Seite fordert _on_page_changed
            # die Daten erneut an (request_data -> frischer Query).
            return
        rows = data.get("rows") or []
        self._populate(rows)
        self._stack.setCurrentIndex(0 if rows else 1)

    def _populate(self, rows: List[Dict[str, Any]]) -> None:
        self._table.setUpdatesEnabled(False)
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            # Zeit: Wanduhr-Formatierung (Invariante 7) + Roh-Epoch im
            # UserRole fuer Jump-to-Chart.
            epoch = row.get("time")
            time_item = QTableWidgetItem(format_wanduhr_time(epoch))
            if epoch is not None:
                time_item.setData(Qt.UserRole, int(epoch))
            self._table.setItem(r, 0, time_item)
            self._table.setItem(r, 1, QTableWidgetItem(str(row.get("symbol") or "")))
            self._table.setItem(r, 2, QTableWidgetItem(str(row.get("timeframe") or "")))
            self._table.setItem(r, 3, QTableWidgetItem(str(row.get("feature_id") or "-")))
            self._table.setItem(r, 4, QTableWidgetItem(str(row.get("plugin_version") or "-")))
            for ci, key in enumerate(("ema_diff", "rsi_14", "atr_normalized"),
                                     start=5):
                v = row.get(key)
                if isinstance(v, (int, float)):
                    self._table.setItem(r, ci, QTableWidgetItem(f"{v:.4f}"))
                else:
                    self._table.setItem(r, ci, QTableWidgetItem("-"))
        self._table.setSortingEnabled(True)
        self._table.setUpdatesEnabled(True)

    # ------------------------------------------------------------------
    # Jump-to-Chart (Variante 2)
    # ------------------------------------------------------------------
    def _on_double_clicked(self, item: QTableWidgetItem) -> None:
        row = item.row()
        if row < 0 or self._navigation_handler is None:
            return
        symbol = self._table.item(row, 1)
        tf = self._table.item(row, 2)
        time_item = self._table.item(row, 0)
        if not symbol or not tf or not time_item:
            return
        bar_time = time_item.data(Qt.UserRole)
        if bar_time is None:
            return
        try:
            bar_time = int(bar_time)
        except (TypeError, ValueError):
            return
        self._navigation_handler(symbol.text(), tf.text(), bar_time)
