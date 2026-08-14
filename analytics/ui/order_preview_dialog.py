# analytics/ui/order_preview_dialog.py
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QPushButton


class OrderPreviewDialog(QDialog):
    """Order-Vorschau (keine Platzierung, kein SQL – MVVM)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Order-Vorschau (Peak Grabber)")
        self.setMinimumWidth(420)
        self._label = QLabel(self)
        self._close_btn = QPushButton("Schließen", self)
        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        layout.addWidget(self._close_btn)
        self._close_btn.clicked.connect(self.accept)

    def show_record(self, record) -> None:
        risk_pct = (abs(record.entry_price - record.sl_price)
                    / record.entry_price * 100.0)
        flag = "[UPDATE]" if record.is_update else "[NEW TRIGGER]"
        self._label.setText(
            f"{'=' * 56}\n"
            f"  ORDER PREVIEW {flag}\n"
            f"  Action   : {record.direction.value} {record.symbol} "
            f"@ {record.entry_price:.4f}\n"
            f"  StopLoss : {record.sl_price:.4f} ({risk_pct:.2f}% Risk)\n"
            f"  Peak Ref : {record.peak_price:.4f} | "
            f"Yellow Window: {record.is_yellow_window}\n"
            f"{'=' * 56}\n"
            f"  Run: {record.run_id} | {record.gate_source}")
        self.show()
        self.raise_()
        self.activateWindow()
