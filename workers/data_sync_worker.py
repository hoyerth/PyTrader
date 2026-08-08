# workers/data_sync_worker.py
"""
workers/data_sync_worker.py - Hintergrund-Sync der historischen Marktdaten.

Ausgelagert aus main.py im Rahmen von 18.01.02 (E7). Der Worker fuehrt den
Voll-/Update-Import der MT5-Historie in einem QThread aus und emittiert die
aktualisierten Symbol/Timeframe-Paare. Keine UI-Logik (SRP).
"""

from typing import Set, Tuple

from PySide6.QtCore import QThread, Signal

from data_sync.mt5_sync_service import sync_market_data


class DataSyncWorker(QThread):
    """Führt den Hintergrund-Sync für alle historischen Daten aus."""

    sync_completed = Signal(object)

    def run(self) -> None:
        """Führt den Hintergrund-Sync für alle historischen Daten aus."""
        try:
            updated_pairs: Set[Tuple[str, str]] = sync_market_data()
            self.sync_completed.emit(updated_pairs)
        except Exception as e:
            print(f"❌ Fehler im DataSyncWorker: {e}")
            self.sync_completed.emit(set())
