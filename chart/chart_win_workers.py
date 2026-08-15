"""
chart/chart_win_workers.py - Worker-/Serializer-/Bridge-Klassen fuer das Chart-Fenster

23.03 God-File-Split (15.08.2026): Aus chart/chart_win.py extrahiert,
KEINE Logik-Aenderung. Enthaelt WebEngineConsolePage, ChartBridge,
ChartDataSerializer, GridDataSerializer und OlderDataWorker.
"""

import json

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWebEngineCore import QWebEnginePage


class WebEngineConsolePage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        print(f"🌐 [JS Console L{lineNumber}]: {message}")


class ChartBridge(QObject):
    """QWebChannel-Bridge zwischen JS (LWC v5) und Python (GUI-Thread).

    Phase 16.07 (D3/D4/D10): Additiv erweitert um
      * rangeChanged(f, t, totalBars) – totalBars für D10-Offset-Restore
      * olderDataRequested(from_time_epoch, count, request_id, window_right_epoch)
        – JS fordert ältere Daten an (zeitbasiert, Wanduhr-Epoch, D4)
      * jumpToLiveRequested – D9 „Live"-Button (Rücksprung ans Live-Ende)
    """
    rangeChanged = Signal(float, float, float)
    priceRangeChanged = Signal(float, float)
    measurementChanged = Signal(str)
    olderDataRequested = Signal(int, int, int, int)
    jumpToLiveRequested = Signal()

    @Slot(float, float, float)
    def onRangeChanged(self, f, t, total): self.rangeChanged.emit(f, t, total)

    @Slot(float, float)
    def onPriceRangeChanged(self, f, t): self.priceRangeChanged.emit(f, t)

    @Slot(str)
    def onMeasurementChanged(self, m): self.measurementChanged.emit(m)

    @Slot(int, int, int, int)
    def onRequestOlderData(self, from_time_epoch, count, request_id, window_right_epoch):
        self.olderDataRequested.emit(from_time_epoch, count, request_id, window_right_epoch)

    @Slot()
    def onJumpToLive(self): self.jumpToLiveRequested.emit()


class ChartDataSerializer(QThread):
    """Serialisiert Chart-Update-Pakete im Hintergrund-Thread (JSON-Encoding)."""
    serialized = Signal(str, int)  # fertiges JSON, updateId

    def __init__(self, update_package: dict, update_id: int, parent=None):
        super().__init__(parent)
        self.update_package = update_package
        self.update_id = update_id

    def run(self):
        try:
            payload = json.dumps(self.update_package, allow_nan=False)
            self.serialized.emit(payload, self.update_id)
        except (ValueError, TypeError) as e:
            print(f"⚠️ [Serializer] JSON-Fehler: {e}")
            self.serialized.emit("", self.update_id)


class GridDataSerializer(QThread):
    """Serialisiert das aggregierte Indikator-Render-Payload im Hintergrund-Thread.

    P16.05 (F4-Beschluss): Threading-Muster exakt beibehalten (QThread +
    done-Signal + Generations-Guard), nur das Payload-Format ist generisch:
    done liefert EIN payload_json (das komplette aggregierte Render-Payload
    {"lines", "price_lines", "hit_circles"}) statt getrennter lines/circles.
    """
    done = Signal(str, int)  # payload_json, gridGen

    def __init__(self, payload: dict, grid_gen: int, parent=None):
        super().__init__(parent)
        self.payload = payload
        self.grid_gen = grid_gen

    def run(self):
        try:
            pj = json.dumps(self.payload, allow_nan=False)
            self.done.emit(pj, self.grid_gen)
        except (ValueError, TypeError) as e:
            print(f"⚠️ [GridSerializer] JSON-Fehler: {e}")
            self.done.emit("", self.grid_gen)


class OlderDataWorker(QThread):
    """Phase 16.07 (D7): Holt den nächsten DB-Chunk (ältere Kerzen) im
    Hintergrund-Thread – der GUI-Thread bleibt reaktionsfähig.

    Führt NUR den reinen Lese-Fetch aus (MarketDataRepository,
    before_epoch-Pfad). Die Puffer-Merge und das Delta-Payload werden im
    GUI-Thread erledigt (Buffer/Indikator-Zustand ist nicht thread-safe).

    Generations-Guard über request_id: Veraltete Worker-Ergebnisse (schneller
    Wechsel / neuerer Request) werden in _on_older_db_fetched verworfen.
    """
    done = Signal(int, list, bool)  # request_id, candles, success

    def __init__(self, repo, symbol, timeframe, before_epoch, count, request_id, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.symbol = symbol
        self.timeframe = timeframe
        self.before_epoch = before_epoch
        self.count = count
        self.request_id = request_id

    def run(self):
        try:
            candles, _precision = self.repo.fetch_historical_candles(
                self.symbol, self.timeframe, limit=self.count,
                before_epoch=self.before_epoch)
            self.done.emit(self.request_id, candles, True)
        except Exception as e:
            print(f"⚠️ [OlderDataWorker] DB-Fetch-Fehler: {e}")
            self.done.emit(self.request_id, [], False)
