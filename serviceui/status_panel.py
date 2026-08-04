# serviceui/status_panel.py
"""
Service-UI: Status- & Log-Panel (Phase 15 15.02).

Entkoppelte Anzeige fuer Laufzeit, Fortschritt und das Scan-/Set-Log.
Reines Anzeige-Widget ohne Geschaeftslogik (SRP): Der Orchestrator
(service_win.py) versorgt es ueber Methoden mit Werten.

Enthaelt:
  * Statuszeile (Laufzeit / Fortschritt)
  * Log-View (QTextEdit, readonly) mit Auto-Scroll ans Ende
"""

from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QTextEdit, QVBoxLayout, QWidget,
)


class StatusPanel(QWidget):
    """Status- & Log-Anzeige des Service-Fensters."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self.label_elapsed = QLabel("Laufzeit:")
        self.label_elapsed_value = QLabel("00:00:00")
        self.label_progress = QLabel("Fortschritt:")
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.text_log = QTextEdit()
        self.text_log.setReadOnly(True)
        self.text_log.setPlaceholderText("Scan-/Set-Log wird hier angezeigt...")

        status_row = QHBoxLayout()
        status_row.addWidget(self.label_elapsed)
        status_row.addWidget(self.label_elapsed_value)
        status_row.addStretch(1)
        status_row.addWidget(self.label_progress)
        status_row.addWidget(self.progress_bar, 1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addLayout(status_row)
        lay.addWidget(self.text_log, 1)

    # -------------------------------------------------------------------------
    # Laufzeit
    # -------------------------------------------------------------------------

    @Slot(int)
    def set_elapsed_seconds(self, seconds: int) -> None:
        """Setzt die Laufzeit-Anzeige (h:mm:ss)."""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        self.label_elapsed_value.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def reset_elapsed(self) -> None:
        self.set_elapsed_seconds(0)

    # -------------------------------------------------------------------------
    # Fortschritt
    # -------------------------------------------------------------------------

    @Slot(int)
    def set_progress(self, current: int, total: int) -> None:
        """Setzt die Fortschritts-Anzeige."""
        self.progress_bar.setMaximum(max(total, 1))
        self.progress_bar.setValue(current)

    @Slot(int)
    def set_progress_value(self, value: int) -> None:
        self.progress_bar.setValue(value)

    # -------------------------------------------------------------------------
    # Log
    # -------------------------------------------------------------------------

    @Slot(str)
    def log(self, message: str) -> None:
        """Haengt eine Meldung ans Log an und scrollt ans Ende."""
        self.text_log.append(message)
        bar = self.text_log.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def clear_log(self) -> None:
        self.text_log.clear()
