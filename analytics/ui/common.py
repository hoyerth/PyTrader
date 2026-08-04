# analytics/ui/common.py
"""
Gemeinsame UI-Helfer der Analytics-Pages (analytics/ui/*, Phase 15.03).

- format_wanduhr_time(): Wanduhr-Formatierung (Invariante 7, KEIN Offset)
- make_overlay_stack(): 'Keine Daten'-Overlay (QStackedLayout) fuer die
  Seiten mit Progress-Spinner-/No-Data-Semantik (15.03-Spezifikation).
"""

from datetime import datetime, timezone
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QStackedLayout, QWidget

# Ausgabeformat der Wanduhr-Zeit (z. B. '03.08.2026 12:00').
WANDUHR_FORMAT = "%d.%m.%Y %H:%M"


def format_wanduhr_time(epoch: Any) -> str:
    """Formatiert eine Wanduhr-encoded Epoch DIREKT als Berliner Wanduhrzeit.

    Invariante 7: Die gespeicherten Epochs sind Wanduhr-encoded (MT5 liefert
    Berlin-Wanduhr-Epochs; die UTC-Darstellung IST die Wanduhr-Zeit). Daher
    formatiert `fromtimestamp(epoch, tz=utc)` OHNE weiteren Berlin-Offset
    korrekt und ist automatisch DST-robust (CEST/CET sind bereits in den
    Roh-Epochs enthalten). Ein zusaetzlicher +2h/+1h-Offset waere falsch.
    """
    try:
        dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
    return dt.strftime(WANDUHR_FORMAT)


def make_overlay_stack(
    content: QWidget, message: str = "Keine Daten vorhanden."
) -> QStackedLayout:
    """Stapelt einen zentrierten 'Keine Daten'-Hinweis ueber den Inhalt.

    Index 0 = Inhalt, Index 1 = Overlay. Die Seiten schalten per
    `stack.setCurrentIndex(0 | 1)` um (No-Data-Overlay, 15.03-Spez).
    """
    stack = QStackedLayout()
    overlay = QLabel(message)
    overlay.setAlignment(Qt.AlignCenter)
    overlay.setStyleSheet("color: #808080; font-size: 14px;")
    stack.addWidget(content)
    stack.addWidget(overlay)
    stack.setCurrentWidget(content)
    return stack
