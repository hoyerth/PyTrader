# statistic_win.py
"""
Statistik-Fenster für PyTrader – Nicht-modale Analyse-Umgebung
mit dynamischer Filterung, Summary-Karten, Detail-Tabelle und Paging.
Mit automatischem State Persistence via PersistentWindow.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QFile, QIODevice, QTimer, Slot
from PySide6.QtGui import QColor
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHeaderView, QLabel, QMainWindow,
    QPushButton, QTableWidget, QTableWidgetItem, QWidget,
)

from analytics.statistics_repository import StatisticsRepository
from persistent_win import PersistentWindow, register_persistent_window
from state_manager import StateManager

BASE_DIR = Path(__file__).resolve().parent


@register_persistent_window()
class StatisticWindow(PersistentWindow):
    INSTANCE_ID = "win_statistics"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.repo = StatisticsRepository()
        self._state_mgr: StateManager = getattr(parent, 'state_manager', None) or StateManager()
        self.settings = self._state_mgr.get_app_settings()

        # Paging-State
        self._all_signals: List[Dict[str, Any]] = []
        self._current_page: int = 0
        self._total_pages: int = 0

        # UI laden
        ui_file = QFile(str(BASE_DIR / "ui" / "statistic_win.ui"))
        if ui_file.open(QIODevice.ReadOnly):
            loader = QUiLoader()
            self.ui = loader.load(ui_file)
            ui_file.close()
            self.setCentralWidget(self.ui)
        else:
            self.ui = QWidget(self)
            self.setCentralWidget(self.ui)

        self.setWindowTitle("PyTrader - Signal-Statistik")

        # Controls
        self.combo_symbol: QComboBox = self.ui.findChild(QComboBox, "combo_symbol_filter")
        self.combo_tf: QComboBox = self.ui.findChild(QComboBox, "combo_tf_filter")
        self.combo_signal: QComboBox = self.ui.findChild(QComboBox, "combo_signal_filter")
        self.btn_refresh: QPushButton = self.ui.findChild(QPushButton, "btn_refresh_stats")

        self.label_total: QLabel = self.ui.findChild(QLabel, "label_total_signals")
        self.label_avg_conf: QLabel = self.ui.findChild(QLabel, "label_avg_confidence")
        self.label_win_rate: QLabel = self.ui.findChild(QLabel, "label_win_rate")
        self.label_best_tf: QLabel = self.ui.findChild(QLabel, "label_best_tf")

        self.table: QTableWidget = self.ui.findChild(QTableWidget, "table_signals")

        # Paging-Controls aus der UI
        self.btn_prev: QPushButton = self.ui.findChild(QPushButton, "btn_prev_page")
        self.btn_next: QPushButton = self.ui.findChild(QPushButton, "btn_next_page")
        self.label_page: QLabel = self.ui.findChild(QLabel, "label_page_info")

        # Signal-Sets laden
        self._load_signal_sets()

        # Events (nach restore_state, damit die gesetzten Filter keine refresh-Explosion auslösen)
        if self.combo_symbol:
            self.combo_symbol.currentTextChanged.connect(self._on_filter_changed)
        if self.combo_tf:
            self.combo_tf.currentTextChanged.connect(self._on_filter_changed)
        if self.combo_signal:
            self.combo_signal.currentTextChanged.connect(self.refresh)
        if self.btn_refresh:
            self.btn_refresh.clicked.connect(self.refresh)
        if self.btn_prev:
            self.btn_prev.clicked.connect(self._prev_page)
        if self.btn_next:
            self.btn_next.clicked.connect(self._next_page)
        if self.table:
            self.table.itemDoubleClicked.connect(self.on_item_double_clicked)

        # State asynchron wiederherstellen (nach show(), damit move/resize vom Window-Manager akzeptiert werden)
        QTimer.singleShot(0, self.restore_state)

        # Initial laden
        QTimer.singleShot(100, self.refresh)

    # --- PersistentWindow-Interface ---

    def get_persistent_symbol(self) -> str:
        return self.combo_symbol.currentText() if self.combo_symbol else "SILVER"

    def get_persistent_timeframe(self) -> str:
        return self.combo_tf.currentText() if self.combo_tf else "H1"

    def _apply_persistent_filters(self, symbol: str, timeframe: str) -> None:
        """Wird von PersistentWindow.restore_state() gerufen."""
        self._restore_filters(symbol, timeframe)

    def _on_filter_changed(self):
        """Speichert sofort bei Filter-Änderung und löst refresh aus."""
        self.save_state()
        self.refresh()

    def _restore_filters(self, symbol: Optional[str] = None, timeframe: Optional[str] = None):
        """Setzt Filter aus gespeicherten Werten (blockiert Signale)."""
        if self.combo_symbol:
            self.combo_symbol.blockSignals(True)
        if self.combo_tf:
            self.combo_tf.blockSignals(True)

        if symbol and self.combo_symbol:
            idx = self.combo_symbol.findText(symbol)
            if idx >= 0:
                self.combo_symbol.setCurrentIndex(idx)
        if timeframe and self.combo_tf:
            idx = self.combo_tf.findText(timeframe)
            if idx >= 0:
                self.combo_tf.setCurrentIndex(idx)

        if self.combo_symbol:
            self.combo_symbol.blockSignals(False)
        if self.combo_tf:
            self.combo_tf.blockSignals(False)

    # --- Paging ---

    def _update_page_controls(self):
        if not self.btn_prev or not self.btn_next or not self.label_page:
            return
        self.label_page.setText(f"Seite {self._current_page + 1} / {max(self._total_pages, 1)}")
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(self._current_page < self._total_pages - 1)

    @Slot()
    def _prev_page(self):
        if self._current_page > 0:
            self._current_page -= 1
            self._render_current_page()

    @Slot()
    def _next_page(self):
        if self._current_page < self._total_pages - 1:
            self._current_page += 1
            self._render_current_page()

    def _render_current_page(self):
        page_size = self.settings.statistics_page_size
        start = self._current_page * page_size
        end = min(start + page_size, len(self._all_signals))
        page_signals = self._all_signals[start:end]
        self._populate_table(page_signals, start)
        self._update_page_controls()

    # --- Daten laden ---

    def _load_signal_sets(self):
        if not self.combo_signal:
            return
        self.combo_signal.blockSignals(True)
        self.combo_signal.clear()
        self.combo_signal.addItem("ALLE")
        for s in self.repo.get_available_sets():
            self.combo_signal.addItem(s)
        self.combo_signal.blockSignals(False)

    @Slot()
    def refresh(self):
        symbol = self.combo_symbol.currentText() if self.combo_symbol else "ALLE"
        tf = self.combo_tf.currentText() if self.combo_tf else "ALLE"
        source = self.combo_signal.currentText() if self.combo_signal else None
        if source == "ALLE":
            source = None

        # Summary
        summary = self.repo.get_summary(symbol, tf, source)
        if self.label_total:
            self.label_total.setText(str(summary["total_signals"]))
        if self.label_avg_conf:
            self.label_avg_conf.setText(f"{summary['avg_confidence']:.2f}")
        if self.label_win_rate:
            self.label_win_rate.setText(f"{summary['win_rate']:.1f}%")
        if self.label_best_tf:
            self.label_best_tf.setText(summary["best_tf"])

        # Signale mit Paging
        self._all_signals = self.repo.fetch_signals(symbol, tf, source, limit=self.settings.statistics_signal_limit)
        self._total_pages = max(1, (len(self._all_signals) + self.settings.statistics_page_size - 1) // self.settings.statistics_page_size)
        self._current_page = 0
        self._render_current_page()

    def _populate_table(self, signals: List[Dict[str, Any]], row_offset: int = 0):
        if not self.table:
            return

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(signals))
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Time", "Symbol", "Timeframe", "Signal-Set", "Confidence", "Outcome"
        ])

        for row_idx, sig in enumerate(signals):
            global_row = row_offset + row_idx + 1
            self.table.setVerticalHeaderItem(row_idx, QTableWidgetItem(str(global_row)))

            dt = datetime.fromtimestamp(sig["time"])
            self.table.setItem(row_idx, 0, QTableWidgetItem(dt.strftime("%Y-%m-%d %H:%M")))
            self.table.setItem(row_idx, 1, QTableWidgetItem(sig["symbol"]))
            self.table.setItem(row_idx, 2, QTableWidgetItem(sig["timeframe"]))
            self.table.setItem(row_idx, 3, QTableWidgetItem(sig["source_id"]))

            conf_item = QTableWidgetItem(f"{sig['confidence']:.2f}")
            conf_item.setData(0, sig["confidence"])
            self.table.setItem(row_idx, 4, conf_item)

            outcome = sig.get("outcome", "N/A")
            outcome_item = QTableWidgetItem(outcome)
            if outcome == "Win":
                outcome_item.setForeground(QColor("#26a69a"))
            elif outcome == "Loss":
                outcome_item.setForeground(QColor("#ef5350"))
            self.table.setItem(row_idx, 5, outcome_item)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        self.table.setUpdatesEnabled(True)

    # --- Jump-to-Bar ---

    def on_item_double_clicked(self, item: QTableWidgetItem):
        row = item.row()
        if row < 0:
            return

        symbol_item = self.table.item(row, 1)
        tf_item = self.table.item(row, 2)
        time_item = self.table.item(row, 0)

        if not symbol_item or not tf_item or not time_item:
            return

        symbol = symbol_item.text()
        tf = tf_item.text()

        try:
            dt = datetime.strptime(time_item.text(), "%Y-%m-%d %H:%M")
            bar_time = int(dt.timestamp())
        except ValueError:
            return

        main_window = self._find_main_window()
        if main_window and hasattr(main_window, 'open_chart_at_bar'):
            main_window.open_chart_at_bar(symbol, tf, bar_time)
        elif main_window and hasattr(main_window, 'open_chart_window'):
            main_window.open_chart_window()

    def _find_main_window(self):
        app = QApplication.instance()
        if not app:
            return None
        for widget in app.topLevelWidgets():
            if widget.metaObject().className() == "MainWindow":
                return widget
        return None
