# main.py
"""
main.py - Haupt-Orchestrator für PyTrader mit Multi-Monitor-Sicherheitsprüfung, WebEngine Render-Fix & Main-Window Geometry Persistence
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# CHROMIUM MULTI-MONITOR & OCCLUSION RENDER FIX (Vor QApplication Import setzen)
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    "--disable-features=CalculateNativeWinOcclusion "
    "--enable-gpu-rasterization "
    "--ignore-gpu-blocklist "
    "--disable-backgrounding-occluded-windows "
    "--disable-renderer-backgrounding "
    "--num-raster-threads=4"
)

import duckdb
from PySide6.QtCore import QFile, QIODevice, QTimer, Slot
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from chart.chart_win import PyTraderChartWindow
from state_manager import StateManager
from persistent_win import PersistentWindow
from repositories.symbol_repository import get_symbol_repository
from config.app_settings import AppSettings
from config.event_bus import event_bus
from analytics.background_workers.live_analyzer import LiveAnalyzer

# 18.01.02 (E7): db-Basisschicht, Sync-Service, Worker & WindowManager
from db.db_pool import DbPool
from db.schema_initializer import check_and_init_databases
from db.db_utils import execute_db_vacuum, get_db_fragmentation_info
from data_sync.mt5_sync_service import check_mt5_connection
from workers.data_sync_worker import DataSyncWorker
from workers.live_tick_worker import LiveTickWorker
from ui.window_manager import WindowManager

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


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.state_manager: StateManager = StateManager()
        self.settings: AppSettings = self.state_manager.get_app_settings()
        self.chart_windows: List[PyTraderChartWindow] = []
        self.persistent_sub_windows: List[PersistentWindow] = []
        # 18.01.02 (E5): Fenster-Lifecycle in WindowManager ausgelagert
        # (gemeinsame Listen-Referenzen, in-place-Mutationen).
        self.window_manager: WindowManager = WindowManager(
            parent=self,
            state_manager=self.state_manager,
            chart_windows=self.chart_windows,
            persistent_sub_windows=self.persistent_sub_windows,
        )
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
            self.btn_open_chart.clicked.connect(self.window_manager.open_chart_window)

        self.btn_refresh_db: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_refresh_db")
        if self.btn_refresh_db:
            self.btn_refresh_db.clicked.connect(self.trigger_background_sync)

        self.btn_service: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_service")
        if self.btn_service:
            self.btn_service.clicked.connect(self.window_manager.open_service_window)

        self.btn_statistics: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_statistics")
        if self.btn_statistics:
            self.btn_statistics.clicked.connect(self.window_manager.open_analytics_window)

        self.btn_properties: Optional[QPushButton] = self.ui.findChild(QPushButton, "btn_properties")
        if self.btn_properties:
            self.btn_properties.clicked.connect(self.window_manager.open_properties_window)

        # Datenbanken initialisieren (Tabellen anlegen/updaten) bevor irgendetwas
        # auf analytics.duckdb oder andere DBs zugreift.
        check_and_init_databases()

        check_mt5_connection()

        # Phase 21.02 (12.08.2026): DB-Bloat-Status beim App-Start anzeigen
        # (Kap. 21.02 Schritt 2, label_db_status unter dem Optionen-Button).
        self.label_db_status = self.ui.findChild(QLabel, "label_db_status")
        if self.label_db_status:
            _db_info = get_db_fragmentation_info(
                str(BASE_DIR / "data" / "analytics.duckdb"))
            self.label_db_status.setText(
                f"DB Status: {_db_info['pct']}% fragmentiert "
                f"({_db_info['bloat_mb']} MB frei)"
            )

        # Phase 15 15.01-Nachtrag 3 (User-Anweisung 04.08.2026): Alle Broker-
        # Symbole werden NUR beim App-Start EINMALIG live von MT5 geladen und
        # per Upsert in broker_symbols persistiert. Das SymbolsWindow liest
        # danach ausschliesslich diese gespeicherte Liste (get_symbols()) –
        # kein MT5-Fetch beim Oeffnen des Fensters (keine Verzoegerungen).
        # MT5 ist hier bereits initialisiert (check_mt5_connection), daher ist
        # der Fetch einmalig und schnell.
        try:
            _symbols, _status, _error = get_symbol_repository().sync_from_broker_with_status()
            if _status == "live":
                print(f"✅ [Symbol-Sync] {len(_symbols)} Symbole beim App-Start "
                      f"von MT5 geladen.")
            else:
                print(f"⚠️ [Symbol-Sync] MT5-Fetch beim App-Start fehlgeschlagen "
                      f"– nutze DB-Stand ({len(_symbols)} Symbole). "
                      f"{_error or 'Unbekannter Fehler'}")
        except Exception as exc:
            print(f"⚠️ [Symbol-Sync] Fehler beim App-Start-Sync: {exc}")

        self.db: duckdb.DuckDBPyConnection = DbPool.get(
            str(BASE_DIR / "data" / "app_data.duckdb")
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS kunden (id INT, name VARCHAR, umsatz DOUBLE)")

        self.load_initial_table_data()

        self.restore_main_window_geometry()

        QTimer.singleShot(200, self.window_manager.restore_all_windows)

        self.sync_timer: QTimer = QTimer(self)
        self.sync_timer.setInterval(45000)
        self.sync_timer.timeout.connect(self.trigger_background_sync)
        self.sync_timer.start()

        # Phase 16 (05.08.2026): Concurrency-Guard – solange im ServiceWindow
        # intensive Service-Berechnungen laufen (SetRunWorker /
        # ServiceRunWorker / HistoricalScanner), wird der 45s-sync_timer
        # pausiert (EventBus, entkoppelt – kein Fenster-Wissen). Referenz-
        # zaehler, damit mehrere parallele Runs den Timer nur EINMAL stoppen
        # und erst nach dem letzten Abschluss wieder starten.
        self._sync_pause_count: int = 0
        event_bus.service_run_started.connect(self._on_service_run_started)
        event_bus.service_run_finished.connect(self._on_service_run_finished)

        self.tick_worker: LiveTickWorker = LiveTickWorker(
            self.window_manager.get_currently_active_pairs)
        self.tick_worker.ticks_ready.connect(self.on_ticks_ready)
        self.tick_worker.start()

        # LiveAnalyzer für SILVER M1 (Plugin-Bar-Close-Evaluierung)
        self.live_analyzer: LiveAnalyzer = LiveAnalyzer(
            symbol="SILVER",
            timeframe="M1",
            lookback_bars=self.settings.feature_builder_limit,
        )
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

    def open_chart_window(self) -> None:
        """Delegation an WindowManager (18.01.02 E5).

        API-Kompatibilitaet fuer statistic_win/analytics_win
        (Jump-to-Chart-Variante 2, hasattr-Check).
        """
        self.window_manager.open_chart_window()

    def open_chart_at_bar(self, symbol: str, timeframe: str, bar_time: int) -> None:
        """Delegation an WindowManager (18.01.02 E5).

        API-Kompatibilitaet fuer statistic_win/analytics_win
        (Jump-to-Chart-Variante 2, hasattr-Check).
        """
        self.window_manager.open_chart_at_bar(symbol, timeframe, bar_time)

    def trigger_background_sync(self) -> None:
        if self.sync_thread is not None and self.sync_thread.isRunning():
            return
        self.sync_thread = DataSyncWorker()
        self.sync_thread.sync_completed.connect(self.on_sync_completed)
        self.sync_thread.start()

    # -------------------------------------------------------------------------
    # Phase 16 (05.08.2026): Concurrency-Guard für den 45s-sync_timer
    # -------------------------------------------------------------------------
    @Slot()
    def _on_service_run_started(self) -> None:
        """Pausiert den sync_timer, sobald eine Service-Berechnung startet."""
        self._sync_pause_count += 1
        # 21.02 (12.08.2026): EventBus-Zähler mitpflegen – PropertiesWindow
        # nutzt ihn als Concurrency-Guard für die DB-Kompaktierung.
        event_bus.sync_pause_count = self._sync_pause_count
        if self._sync_pause_count == 1 and self.sync_timer.isActive():
            self.sync_timer.stop()

    @Slot()
    def _on_service_run_finished(self) -> None:
        """Startet den sync_timer, sobald die letzte Service-Berechnung
        abgeschlossen ist (Referenzzähler auf 0)."""
        if self._sync_pause_count > 0:
            self._sync_pause_count -= 1
        event_bus.sync_pause_count = self._sync_pause_count  # 21.02
        if self._sync_pause_count != 0:
            return
        app = QApplication.instance()
        if getattr(app, '_is_quitting', False):
            return
        if not self.sync_timer.isActive():
            self.sync_timer.start()

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
        # (ServiceWindow, AnalyticsWindow, etc. - haben keinen Qt-Parent mehr,
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

        # Phase 21.02 (12.08.2026): DB-Pflege beim App-Exit (Kap. 21.02
        # Stufe 1) – CHECKPOINT gefolgt von VACUUM fuer alle DuckDB-Dateien.
        # Zweck: WAL in Hauptdatei flushen (konsistenter Zustand, kein
        # WAL-Replay beim nächsten Start). Keine Datei-Verkleinerung –
        # echte Kompaktierung nur per DB-Service-Button (compact_database).
        for _db_name in ("analytics", "market_data", "app_data"):
            try:
                execute_db_vacuum(str(BASE_DIR / "data" / f"{_db_name}.duckdb"))
            except Exception as exc:
                print(f"⚠️ [DB-Pflege] {_db_name}.duckdb: {exc}")

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