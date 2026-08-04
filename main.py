# main.py
"""
main.py - Haupt-Orchestrator für PyTrader mit Multi-Monitor-Sicherheitsprüfung, WebEngine Render-Fix & Main-Window Geometry Persistence
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

# CHROMIUM MULTI-MONITOR & OCCLUSION RENDER FIX (Vor QApplication Import setzen)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-features=CalculateNativeWinOcclusion "
    "--enable-gpu-rasterization "
    "--ignore-gpu-blocklist "
    "--disable-backgrounding-occluded-windows "
    "--disable-renderer-backgrounding "
    "--num-raster-threads=4"
)

import MetaTrader5 as mt5
import duckdb
from PySide6.QtCore import QFile, QIODevice, QThread, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QScreen
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from chart.chart_win import PyTraderChartWindow
from state_manager import StateManager
from persistent_win import PersistentWindow
from db_service import get_timeframes, TF_SECONDS_MAP, MT5_LOCK, DbPool
import db_service
from serviceui.service_win import ServiceWindow
from statistic_win import StatisticWindow
from properties_win import PropertiesWindow
from config.app_settings import AppSettings
from analytics.background_workers.live_analyzer import LiveAnalyzer

# ==============================================================================
# KONSOLE: UTF-8 erzwingen – verhindert UnicodeEncodeError bei Emojis/Log-Ausgaben
# unter Windows (CP1252). Ein solcher Fehler in kritischen Pfaden (z. B. Chart-Refresh)
# kann den Chart dauerhaft blockieren, weil _is_loading_data nicht zurueckgesetzt wird.
# ==============================================================================
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent


class DataSyncWorker(QThread):
    sync_completed = Signal(object)

    def run(self) -> None:
        """Führt den Hintergrund-Sync für alle historischen Daten aus."""
        try:
            updated_pairs: Set[Tuple[str, str]] = db_service.sync_market_data()
            self.sync_completed.emit(updated_pairs)
        except Exception as e:
            print(f"❌ Fehler im DataSyncWorker: {e}")
            self.sync_completed.emit(set())


class LiveTickWorker(QThread):
    ticks_ready = Signal(str)

    def __init__(self, get_active_pairs_callback: Callable[[], Set[Tuple[str, str]]]) -> None:
        super().__init__()
        self.get_active_pairs: Callable[[], Set[Tuple[str, str]]] = get_active_pairs_callback
        self._running: bool = True
        self._last_bar_times: Dict[str, int] = {}  # Für Bar-Close-Erkennung
        self._last_bar_data: Dict[str, Dict[str, Any]] = {}  # OHLCV der letzten abgeschlossenen Kerze

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        """Kontinuierliche Polling-Schleife für MT5-Ticks mit try/finally Freigabe.
        Erkennt Bar-Close-Events und schreibt abgeschlossene Kerzen in market_data.duckdb."""
        try:
            with MT5_LOCK:
                if not mt5.initialize():
                    # MT5 ist möglicherweise bereits von MainWindow initialisiert
                    print("⚠️ [LiveTickWorker] mt5.initialize() war False, versuche trotzdem weiter...")

            while self._running:
                active_pairs: Set[Tuple[str, str]] = self.get_active_pairs()
                if not active_pairs:
                    self.msleep(200)
                    continue

                results: Dict[str, Dict[str, float | int]] = {}
                try:
                    for symbol, tf_str in active_pairs:
                        mt5_tf: Optional[int] = get_timeframes().get(tf_str)
                        if mt5_tf is None:
                            continue

                        with MT5_LOCK:
                            tick = mt5.symbol_info_tick(symbol)
                            rates = mt5.copy_rates_from_pos(symbol, mt5_tf, 0, 1)

                        if tick and rates is not None and len(rates) > 0:
                            rate = rates[0]
                            key: str = f"{symbol}|{tf_str}"
                            current_bar_time = int(rate['time'])

                            # Bar-Close erkennen: neue Bar-Time != letzte Bar-Time
                            last_bar = self._last_bar_times.get(key, 0)
                            if last_bar > 0 and current_bar_time > last_bar:
                                # Alte (abgeschlossene) Kerze aus dem Zwischenspeicher in DB schreiben
                                last_data = self._last_bar_data.get(key)
                                if last_data:
                                    self._persist_bar(symbol, tf_str, last_bar, last_data)

                            # Aktuelle Kerze zwischenspeichern (wird beim nächsten Bar-Close persistiert)
                            self._last_bar_times[key] = current_bar_time
                            self._last_bar_data[key] = {
                                'open': float(rate[1]),  # open
                                'high': float(rate[2]),  # high
                                'low': float(rate[3]),   # low
                                'close': float(rate[4]), # close
                                'tick_volume': int(rate[5]) if len(rate) > 5 else 0,
                                'spread': int(rate[6]) if len(rate) > 6 else 0,
                                'real_volume': int(rate[7]) if len(rate) > 7 else 0,
                            }

                            # JEDEN Tick an die Charts senden (für Live-Candle-Updates)
                            results[key] = {
                                "time": current_bar_time,
                                "open": float(rate['open']),
                                "high": max(float(rate['high']), float(tick.bid)),
                                "low": min(float(rate['low']), float(tick.bid)),
                                "close": float(tick.bid)
                            }
                except Exception as e:
                    print(f"⚠️ [LiveTickWorker] Fehler in Poll-Schleife: {e}")

                if results:
                    self.ticks_ready.emit(json.dumps(results))

                self.msleep(500)

        finally:
            with MT5_LOCK:
                try:
                    mt5.shutdown()
                except Exception:
                    pass

    def _persist_bar(self, symbol: str, tf_str: str, bar_time: int, bar_data: Dict[str, Any]) -> None:
        """Schreibt eine abgeschlossene Kerze per INSERT OR REPLACE in market_data.duckdb."""
        try:
            from db_service import DB_MARKET_DATA, DbPool
            con = DbPool.get(DB_MARKET_DATA)
            con.execute("""
                INSERT OR REPLACE INTO ohlcv_bars (symbol, timeframe, time, open, high, low, close, tick_volume, spread, real_volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                symbol,
                tf_str,
                datetime.fromtimestamp(bar_time, tz=timezone.utc),
                bar_data['open'],
                bar_data['high'],
                bar_data['low'],
                bar_data['close'],
                bar_data['tick_volume'],
                bar_data['spread'],
                bar_data['real_volume'],
            ])
        except Exception as e:
            print(f"⚠️ [LiveTickWorker] Fehler beim Persistieren von {symbol} {tf_str} @ {bar_time}: {e}")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.state_manager: StateManager = StateManager()
        self.settings: AppSettings = self.state_manager.get_app_settings()
        self.chart_windows: List[PyTraderChartWindow] = []
        self.persistent_sub_windows: List[PersistentWindow] = []
        self.sync_thread: Optional[DataSyncWorker] = None
        self.pending_ticks_buffer: Dict[str, Dict[str, float | int]] = {}
        self._pending_ticks_timer: QTimer = QTimer(self)
        self._pending_ticks_timer.setSingleShot(True)
        self._pending_ticks_timer.setInterval(30000)
        self._pending_ticks_timer.timeout.connect(self._flush_pending_ticks)

        ui_file_name: str = str(BASE_DIR / "ui" / "main_win.ui")
        ui_file: QFile = QFile(ui_file_name)
        if not ui_file.open(QIODevice.ReadOnly):
            print(f"❌ Konnte UI nicht öffnen: {ui_file_name}")
            sys.exit(1)

        loader: QUiLoader = QUiLoader()
        self.ui = loader.load(ui_file)
        ui_file.close()

        self.setCentralWidget(self.ui)
        self.setWindowTitle("PyTrader - Trading Terminal")

        self.btn_open_chart: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_open_chart")
        if self.btn_open_chart:
            self.btn_open_chart.clicked.connect(self.open_chart_window)

        self.btn_refresh_db: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_refresh_db")
        if self.btn_refresh_db:
            self.btn_refresh_db.clicked.connect(self.trigger_background_sync)

        self.btn_service: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_service")
        if self.btn_service:
            self.btn_service.clicked.connect(self.open_service_window)

        self.btn_statistics: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_statistics")
        if self.btn_statistics:
            self.btn_statistics.clicked.connect(self.open_statistic_window)

        self.btn_properties: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_properties")
        if self.btn_properties:
            self.btn_properties.clicked.connect(self.open_properties_window)

        # Datenbanken initialisieren (Tabellen anlegen/updaten) bevor irgendetwas
        # auf analytics.duckdb oder andere DBs zugreift.
        db_service.check_and_init_databases()

        db_service.check_mt5_connection()

        self.db: duckdb.DuckDBPyConnection = DbPool.get(
            str(BASE_DIR / "data" / "app_data.duckdb")
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS kunden (id INT, name VARCHAR, umsatz DOUBLE)")

        self.load_initial_table_data()

        self.restore_main_window_geometry()

        QTimer.singleShot(200, self.restore_all_windows)

        self.sync_timer: QTimer = QTimer(self)
        self.sync_timer.setInterval(45000)
        self.sync_timer.timeout.connect(self.trigger_background_sync)
        self.sync_timer.start()

        self.tick_worker: LiveTickWorker = LiveTickWorker(self.get_currently_active_pairs)
        self.tick_worker.ticks_ready.connect(self.on_ticks_ready)
        self.tick_worker.start()

        # LiveAnalyzer für SILVER M1 (Bar-Close-Analyse)
        self.live_analyzer: LiveAnalyzer = LiveAnalyzer(
            symbol="SILVER",
            timeframe="M1",
            lookback_bars=self.settings.feature_builder_limit,
        )
        self.live_analyzer.new_live_signal.connect(self.on_live_signal)
        self.live_analyzer.log_message.connect(self._on_live_analyzer_log)
        self.live_analyzer.start()

        # Ersten Sync erst starten, wenn alle Charts geladen sind
        QTimer.singleShot(2000, self.trigger_background_sync)

    def load_initial_table_data(self) -> None:
        table: Optional[QTableWidget] = self.ui.findChild(QTableWidget, "table_result")
        if table:
            data = self.db.execute("SELECT id, name, umsatz FROM kunden").fetchall()
            table.setRowCount(len(data))
            table.setColumnCount(3)
            table.setHorizontalHeaderLabels(["ID", "Name", "Umsatz (€)"])
            for row_idx, row_data in enumerate(data):
                for col_idx, col_data in enumerate(row_data):
                    table.setItem(row_idx, col_idx, QTableWidgetItem(str(col_data)))

    def restore_main_window_geometry(self) -> None:
        geom = self.state_manager.get_window_geometry("win_main")
        if geom:
            pos_x = geom.get("pos_x")
            pos_y = geom.get("pos_y")
            width = geom.get("width") or 1000
            height = geom.get("height") or 600

            screen_geo = QApplication.primaryScreen().availableGeometry()
            if pos_x is not None and pos_y is not None:
                if pos_x < screen_geo.x() - 100 or pos_x > screen_geo.right() or \
                        pos_y < screen_geo.y() - 100 or pos_y > screen_geo.bottom():
                    pos_x, pos_y = 100, 100

            self.move(pos_x, pos_y)
            self.resize(width, height)

            if geom.get("is_maximized"):
                self.showMaximized()
        else:
            self.resize(1000, 600)

    def restore_all_windows(self) -> None:
        """Stellt ALLE gespeicherten Fenster vollautomatisch und generisch wieder her.
        
        Nutzt die Klassen-Registry aus persistent_win.py, um ohne Hardcoding
        zwischen PersistentWindow-Subklassen (Service, Statistik) und
        dynamischen Chart-Fenstern zu unterscheiden.
        """
        all_instances: List[Dict[str, Any]] = self.state_manager.load_all_instances()
        if not all_instances:
            print("✨ Keine gespeicherten Instanzen vorhanden.")
            return

        print(f"🔄 Prüfe {len(all_instances)} gespeicherte Fenster-Einträge...")

        for inst in all_instances:
            inst_id = str(inst.get("instance_id", ""))
            if not inst_id or inst_id == "win_main":
                continue

            # 1. Fall: Registrierte PersistentWindow-Subklasse (Service, Statistik, etc.)
            window_cls = PersistentWindow.get_registered_class(inst_id)
            if window_cls is not None:
                if not PersistentWindow.should_auto_restore(inst_id):
                    print(f"  → Überspringe {inst_id} ({window_cls.__name__}): auto_restore=False")
                    continue
                print(f"  → Öffne registriertes Fenster: {inst_id} ({window_cls.__name__})")
                # WICHTIG: parent=self nur für state_manager-Zugriff, nicht als Qt-Parent!
                # PersistentWindow.__init__() übergibt kein Parent an QMainWindow,
                # damit das Fenster einen eigenen Taskleisten-Eintrag hat.
                win = window_cls(parent=self)
                self.persistent_sub_windows.append(win)
                # Ohne Fokus anzeigen (damit MainWindow den Fokus behält)
                win.setAttribute(Qt.WA_ShowWithoutActivating, True)
                win.show()
                win.setAttribute(Qt.WA_ShowWithoutActivating, False)
                # Maximiert wiederherstellen (nach show(), ohne Fokus-Klau)
                if getattr(win, '_restored_is_maximized', False):
                    win.showMaximized()
                continue

            # 2. Fall: Dynamische Chart-Fenster (win_1, win_2, ...)
            if inst_id.startswith("win_"):
                print(f"  → Öffne Chart-Fenster: {inst_id}")
                win = PyTraderChartWindow(
                    instance_id=inst_id,
                    symbol=inst.get("symbol") or "SILVER",
                    timeframe=inst.get("timeframe") or "H1",
                    visible_from=inst.get("visible_range_from"),
                    visible_to=inst.get("visible_range_to"),
                    state_manager=self.state_manager
                )
                win.closed_signal.connect(self.handle_chart_closed)

                # Geometrie anwenden
                screen_geo = QApplication.primaryScreen().availableGeometry()
                pos_x, pos_y = inst.get("pos_x"), inst.get("pos_y")
                width = inst.get("width") or 900
                height = inst.get("height") or 600

                if pos_x is not None and pos_y is not None:
                    if pos_x < screen_geo.x() - 100 or pos_x > screen_geo.right() or \
                       pos_y < screen_geo.y() - 100 or pos_y > screen_geo.bottom():
                        pos_x, pos_y = 100, 100
                    win.move(pos_x, pos_y)
                    win.resize(width, height)

                if inst.get("is_maximized"):
                    win.showMaximized()
                else:
                    win.setAttribute(Qt.WA_ShowWithoutActivating, True)
                    win.show()
                    win.setAttribute(Qt.WA_ShowWithoutActivating, False)

                self.chart_windows.append(win)

        # MainWindow NICHT in den Vordergrund holen – die WA_ShowWithoutActivating-Logik
        # bei den Sub-Fenstern verhindert bereits Fokus-Klau. Ein erzwungenes
        # raise_() + activateWindow() würde nur stören, falls der User inzwischen
        # eine andere Anwendung fokussiert hat.

    def open_chart_window(self) -> None:
        new_id: str = self.state_manager.get_next_instance_id()
        win = PyTraderChartWindow(
            instance_id=new_id,
            symbol="SILVER",
            timeframe="H1",
            visible_from=None,
            visible_to=None,
            state_manager=self.state_manager
        )
        win.closed_signal.connect(self.handle_chart_closed)
        win.show()
        self.chart_windows.append(win)

    @Slot(str)
    def handle_chart_closed(self, instance_id: str) -> None:
        app = QApplication.instance()
        if getattr(app, '_is_quitting', False): return
        self.chart_windows = [w for w in self.chart_windows if w.instance_id != instance_id]

    def open_service_window(self) -> None:
        # Singleton: Bestehendes Fenster in den Vordergrund holen
        existing = ServiceWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = ServiceWindow(self)  # parent=self nur für state_manager-Zugriff
        self.persistent_sub_windows.append(win)
        win.show()

    def open_statistic_window(self) -> None:
        # Singleton: Bestehendes Fenster in den Vordergrund holen
        existing = StatisticWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = StatisticWindow(self)  # parent=self nur für state_manager-Zugriff
        self.persistent_sub_windows.append(win)
        win.show()

    def open_properties_window(self) -> None:
        # Singleton: Bestehendes Fenster in den Vordergrund holen
        existing = PropertiesWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = PropertiesWindow(self)
        self.persistent_sub_windows.append(win)
        win.show()

    def open_chart_at_bar(self, symbol: str, timeframe: str, bar_time: int) -> None:
        """Oeffnet oder fokussiert ein Chart-Fenster und scrollt zur angegebenen Bar-Position."""
        # Bestehendes Chart-Fenster mit passendem Symbol/TF suchen
        for win in self.chart_windows:
            try:
                if win.current_symbol == symbol and win.current_tf == timeframe and win.isVisible():
                    win.raise_()
                    win.activateWindow()
                    # Chart zur Position scrollen
                    win.visible_from = bar_time
                    win.visible_to = None
                    win.refresh_chart_data()
                    return
            except (RuntimeError, AttributeError):
                pass

        # Kein passendes Fenster gefunden -> neues oeffnen
        from chart.chart_win import PyTraderChartWindow
        new_id: str = self.state_manager.get_next_instance_id()
        win = PyTraderChartWindow(
            instance_id=new_id,
            symbol=symbol,
            timeframe=timeframe,
            visible_from=bar_time,
            visible_to=None,
            state_manager=self.state_manager
        )
        win.closed_signal.connect(self.handle_chart_closed)
        win.show()
        self.chart_windows.append(win)

    def get_currently_active_pairs(self) -> Set[Tuple[str, str]]:
        active_pairs = set()
        for win in list(self.chart_windows):
            try:
                if win.isVisible():
                    active_pairs.add((win.current_symbol, win.current_tf))
            except (RuntimeError, AttributeError):
                pass
        return active_pairs

    def trigger_background_sync(self) -> None:
        if self.sync_thread is not None and self.sync_thread.isRunning():
            return
        self.sync_thread = DataSyncWorker()
        self.sync_thread.sync_completed.connect(self.on_sync_completed)
        self.sync_thread.start()

    def _dispatch_tick_map(self, ticks_map: Dict[str, Dict[str, float | int]]) -> None:
        """Verteilt Ticks an alle geöffneten Chartfenster."""
        for win in list(self.chart_windows):
            try:
                if win.isVisible():
                    key = f"{win.current_symbol}|{win.current_tf}"
                    if key in ticks_map:
                        win.update_live_candle(ticks_map[key])
            except (RuntimeError, AttributeError):
                continue

    def on_ticks_ready(self, ticks_json_str: str) -> None:
        if not ticks_json_str: return

        try:
            ticks_map = json.loads(ticks_json_str)

            # Falls gerade ein DB-Sync läuft, Ticks im Puffer zwischenspeichern statt verwerfen
            if self.sync_thread is not None and self.sync_thread.isRunning():
                self.pending_ticks_buffer.update(ticks_map)
                self._pending_ticks_timer.start()  # Timeout als Fallback falls Sync fehlschlägt
                return

            self._dispatch_tick_map(ticks_map)
        except Exception as e:
            print(f"❌ Fehler bei on_ticks_ready: {e}")

    def _flush_pending_ticks(self) -> None:
        """Leert den Puffer als Fallback, falls der Sync nie completed."""
        if self.pending_ticks_buffer:
            self._dispatch_tick_map(self.pending_ticks_buffer)
            self.pending_ticks_buffer.clear()

    def on_sync_completed(self, updated_pairs: Set[Tuple[str, str]]) -> None:
        # 1. Gepufferte Live-Ticks nach dem Sync an die Charts ausliefern
        if self.pending_ticks_buffer:
            self._dispatch_tick_map(self.pending_ticks_buffer)
            self.pending_ticks_buffer.clear()

        # 2. Charts nur refreshen, wenn sie nicht gerade interagiert werden (_is_loading_data)
        #    Der Refresh passiert asynchron mit 2s Verzögerung, damit der Sync komplett abgeschlossen ist
        if updated_pairs:
            QTimer.singleShot(2000, lambda: self._refresh_updated_charts(updated_pairs))

    def _refresh_updated_charts(self, updated_pairs: Set[Tuple[str, str]]) -> None:
        """Aktualisiert Charts für die aktualisierten Symbol/TF-Paare."""
        for win in list(self.chart_windows):
            try:
                if (win.isVisible() and win._page_loaded and 
                    not win._is_loading_data and
                    (win.current_symbol, win.current_tf) in updated_pairs):
                    win.refresh_chart_data()
            except (RuntimeError, AttributeError):
                pass

    # ==============================================================================
    # LiveAnalyzer Integration
    # ==============================================================================

    @Slot(str, str, int, float, str)
    def on_live_signal(self, symbol: str, timeframe: str, bar_time: int, confidence: float, source_id: str) -> None:
        """Wird vom LiveAnalyzer emittiert, wenn ein neues Live-Signal erkannt wurde.
        Aktualisiert das Chart-Overlay für das betroffene Symbol/TF."""
        print(f"🔔 Live-Signal empfangen: {symbol} {timeframe} @ {bar_time} (conf={confidence:.2f})")

        # Direkt an die Chart-Fenster weiterleiten (on_live_signal_received)
        for win in list(self.chart_windows):
            try:
                if win.isVisible():
                    win.on_live_signal_received(symbol, timeframe, bar_time, confidence, source_id)
            except (RuntimeError, AttributeError):
                pass

    @Slot(str)
    def _on_live_analyzer_log(self, message: str) -> None:
        """Loggt Nachrichten des LiveAnalyzer."""
        print(f"📡 [LiveAnalyzer] {message}")

    def closeEvent(self, event) -> None:
        print("🚪 Beende PyTrader...")
        app = QApplication.instance()
        setattr(app, '_is_quitting', True)

        self.sync_timer.stop()
        if hasattr(self, "tick_worker"):
            self.tick_worker.stop()
            self.tick_worker.wait(1000)

        if hasattr(self, "live_analyzer"):
            self.live_analyzer.stop()
            self.live_analyzer.wait(2000)

        p, s = self.pos(), self.size()
        print("💾 Speichere Hauptfenster win_main...")
        self.state_manager.save_window_geometry(
            "win_main", p.x(), p.y(), s.width(), s.height(), self.isMaximized()
        )

        # Alle offenen PersistentWindow-Instanzen speichern und schliessen
        # (ServiceWindow, StatisticWindow, etc. - haben keinen Qt-Parent mehr,
        #  daher muessen sie explizit geschlossen werden)
        from persistent_win import _open_windows as pw_open_windows
        for sub_win in list(pw_open_windows):
            try:
                sub_win.save_state()
                sub_win.close()
            except Exception as e:
                print(f"⚠️ Fehler beim Schliessen von Sub-Window: {e}")

        # Chart-Fenster schliessen (die haben eigene save_state-Logik)
        for win in list(self.chart_windows):
            try:
                win.close()
            except Exception as e:
                print(f"⚠️ Fehler beim Schliessen von Fenster {win.instance_id}: {e}")

        event.accept()


if __name__ == "__main__":
    # Kapitel 7.3 AKTUELLE_UMSETZUNG: Deployment-Check "python main.py
    # --check-plugins" – headless Validierung der Core Protection Rule
    # (kein Custom-Plugin ueberschreibt eine Core-Plugin-ID). Endet mit
    # exit 0 (OK) bzw. exit 1 (Konflikt) OHNE GUI-Start. Additiv: der
    # normale App-Start bleibt unveraendert.
    if "--check-plugins" in sys.argv:
        from analytics.features.feature_builder import PluginRegistry, PluginLoader
        registry = PluginRegistry()
        print(f"[check-plugins] Core-Plugins: {sorted(registry.plugins.keys())}")
        try:
            conflicts = PluginLoader().find_custom_conflicts()
        except Exception as e:
            print(f"[check-plugins] FEHLER bei der Konflikt-Pruefung: {e}")
            sys.exit(1)
        if conflicts:
            print(f"[check-plugins] KONFLIKT: {len(conflicts)} Custom-Plugin(s) "
                  f"ueberschreiben Core-IDs:")
            for c in conflicts:
                print(f"  - '{c['plugin_id']}' aus {c['custom_module']}")
            print("[check-plugins] Core Protection Rule verletzt – bereinige "
                  "die Custom-Plugins.")
            sys.exit(1)
        print("[check-plugins] OK: keine Custom-Plugins ueberschreiben "
              "Core-IDs (Core Protection Rule aktiv).")
        sys.exit(0)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())