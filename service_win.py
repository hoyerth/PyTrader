# service_win.py
"""
Service-Kontrollfenster für PyTrader.
Steuert den Historical Scanner (Full-Scan / Delta-Update) über ein separates Fenster.
Mit automatischem State Persistence via PersistentWindow.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QFile, QIODevice, QTimer, Slot
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QLabel, QMainWindow,
    QProgressBar, QPushButton, QTextEdit, QWidget,
)

from analytics.background_workers.historical_scanner import HistoricalScanner
from persistent_win import PersistentWindow, register_persistent_window

BASE_DIR = Path(__file__).resolve().parent


@register_persistent_window(auto_restore=False)
class ServiceWindow(PersistentWindow):
    INSTANCE_ID = "win_service"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scanner: Optional[HistoricalScanner] = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_seconds = 0
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        # UI laden
        ui_file = QFile(str(BASE_DIR / "ui" / "service_win.ui"))
        if ui_file.open(QIODevice.ReadOnly):
            loader = QUiLoader()
            self.ui = loader.load(ui_file)
            ui_file.close()
            self.setCentralWidget(self.ui)
        else:
            self.ui = QWidget(self)
            self.setCentralWidget(self.ui)

        self.setWindowTitle("PyTrader - Service Kontrolle")

        # Controls
        self.combo_symbol: QComboBox = self.ui.findChild(QComboBox, "combo_symbol")
        self.check_new_scan: QCheckBox = self.ui.findChild(QCheckBox, "check_new_scan")
        self.check_grid_scan: QCheckBox = self.ui.findChild(QCheckBox, "check_grid_scan")
        self.btn_start: QPushButton = self.ui.findChild(QPushButton, "btn_start_scan")
        self.label_elapsed: QLabel = self.ui.findChild(QLabel, "label_elapsed_value")
        self.progress_bar: QProgressBar = self.ui.findChild(QProgressBar, "progress_bar")
        self.text_log: QTextEdit = self.ui.findChild(QTextEdit, "text_log")

        if self.btn_start:
            self.btn_start.clicked.connect(self.start_scan)

        # Sofort speichern bei Symbol-Änderung
        if self.combo_symbol:
            self.combo_symbol.currentTextChanged.connect(self.save_state)

        # State asynchron wiederherstellen (nach show(), damit move/resize vom Window-Manager akzeptiert werden)
        QTimer.singleShot(0, self.restore_state)

    # --- PersistentWindow-Interface ---

    def get_persistent_symbol(self) -> str:
        return self.combo_symbol.currentText() if self.combo_symbol else "SILVER"

    def get_persistent_timeframe(self) -> str:
        return "H1"

    def _apply_persistent_filters(self, symbol: str, timeframe: str) -> None:
        if self.combo_symbol:
            idx = self.combo_symbol.findText(symbol)
            if idx >= 0:
                self.combo_symbol.setCurrentIndex(idx)

    # --- Scanner ---

    @Slot()
    def start_scan(self):
        if self.scanner and self.scanner.isRunning():
            self.log("Scan laeuft bereits.")
            return

        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        new_scan = self.check_new_scan.isChecked() if self.check_new_scan else False
        grid_scan = self.check_grid_scan.isChecked() if self.check_grid_scan else False

        mode = "GRID PROXIMITY" if grid_scan else "EMA+ATR STANDARD"
        self.log(f"Starte {mode}-Scan: {symbol}, New Scan = {new_scan}")
        self.btn_start.setEnabled(False)
        self._elapsed_seconds = 0
        self.label_elapsed.setText("00:00:00")
        self.progress_bar.setValue(0)
        self._elapsed_timer.start(1000)

        self.scanner = HistoricalScanner(symbol, new_scan, grid_scan)
        self.scanner.progress_updated.connect(self.on_progress)
        self.scanner.scan_finished.connect(self.on_finished)
        self.scanner.log_message.connect(self.log)
        self.scanner.start()

    @Slot(str, int, int)
    def on_progress(self, message: str, current: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.log(message)

    @Slot(str, int)
    def on_finished(self, symbol: str, count: int):
        self._elapsed_timer.stop()
        self.btn_start.setEnabled(True)
        self.log(f"Scan für {symbol} beendet: {count} Signale geschrieben.")

    @Slot(str)
    def log(self, message: str):
        if self.text_log:
            self.text_log.append(message)

    def _update_elapsed(self):
        self._elapsed_seconds += 1
        h = self._elapsed_seconds // 3600
        m = (self._elapsed_seconds % 3600) // 60
        s = self._elapsed_seconds % 60
        self.label_elapsed.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def closeEvent(self, event):
        # PersistentWindow.save_state() wird in super().closeEvent gerufen
        if self.scanner and self.scanner.isRunning():
            self.scanner.stop()
            self.scanner.wait(2000)
        self._elapsed_timer.stop()
        super().closeEvent(event)
