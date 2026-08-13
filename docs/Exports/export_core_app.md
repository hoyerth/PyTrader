# PROJEKT-ÜBERSICHT: PyTrader — Core App & Infrastruktur

> Teil-Export (sachbezogen). Vollständiger Export: export_Full.md
> Dateien in dieser Datei: 6

## 1. ORDNERSTRUKTUR
```
PyTrader/
    db/
        db_utils.py
    db_service.py
    main.py
    persistent_win.py
    properties_win.py
    state_manager.py
```

## 2. QUELLCODE

### DATEI: db_service.py
```py
# db_service.py
"""
db_service.py - FASSADE (Re-Export-Wrapper), seit 18.01.02 (E2/E3).

Diese Datei enthaelt KEINE Logik mehr – die Implementierung wurde im Rahmen
von 18.01.02 (Refactoring & Modularisierung) auf folgende Module aufgeteilt:

  * db/db_pool.py                    – DATA_DIR, DB_*-Pfad-Konstanten, DbPool,
                                       _LockedConnection, db_connect, with_db_lock
  * db/db_utils.py                   – _parse_json_field, _ensure_epoch
  * db/schema_initializer.py         – check_and_init_databases
  * data_sync/mt5_sync_service.py    – SYMBOLS, _TIMEFRAMES_CACHE, get_timeframes,
                                       TF_SECONDS_MAP, MT5_LOCK, check_mt5_connection,
                                       get_latest_timestamp, sync_market_data
  * repositories/market_data_repository.py – MarketDataRepository, get_symbol_precision

Die Bestands-Caller (20 Dateien, u. a. chart_win, state_manager, symbol_repository,
analytics_profile_repository, service_selector_model) importieren weiterhin
unveraendert aus `db_service` (E2). Der CLI-Einstieg `python db_service.py`
(fuehrt den MT5-Sync aus) bleibt erhalten.
"""

from db.db_pool import (
    DATA_DIR,
    DB_ANALYTICS,
    DB_APP_DATA,
    DB_MARKET_DATA,
    DbPool,
    _LockedConnection,
    db_connect,
    with_db_lock,
)
from db.db_utils import _ensure_epoch, _parse_json_field
from db.schema_initializer import check_and_init_databases
from data_sync.mt5_sync_service import (
    SYMBOLS,
    TF_SECONDS_MAP,
    MT5_LOCK,
    check_mt5_connection,
    get_latest_timestamp,
    get_timeframes,
    sync_market_data,
)
from repositories.market_data_repository import (
    MarketDataRepository,
    get_symbol_precision,
)


def main() -> None:
    """CLI-Einstieg (Kompatibilitaet): fuehrt den MT5-Sync aus."""
    sync_market_data()


if __name__ == "__main__":
    main()

```

--------------------------------------------------

### DATEI: main.py
```py
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
from symbol_repository import get_symbol_repository
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
```

--------------------------------------------------

### DATEI: persistent_win.py
```py
# persistent_win.py
"""
Basisklasse fuer Fenster mit automatischem State Persistence (Save/Restore).
Jedes Fenster mit einer INSTANCE_ID erbt von PersistentWindow und
bekommt automatisch:
- Geometrie-Save/Restore (Position, Groesse, Maximiert)
- Symbol/Timeframe-Save/Restore (fuer Filter)
- Automatisches Speichern beim Schliessen
- Zentrale Registry fuer MainWindow.closeEvent
- Klassen-Registry fuer generische Wiederherstellung ohne Hardcoding
"""

from typing import Any, Dict, Optional, ClassVar, Set, Type
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QApplication

from state_manager import StateManager


# Registry aller offenen PersistentWindow-Instanzen
_open_windows: Set['PersistentWindow'] = set()

# Klassen-Registry fuer automatische Wiederherstellung (instance_id -> Klasse)
_window_registry: Dict[str, Type['PersistentWindow']] = {}


def register_persistent_window(
    auto_restore: bool = True,
) -> callable:
    """
    Dekorator zur Registrierung von PersistentWindow-Subklassen.
    
    Args:
        auto_restore: Ob das Fenster beim App-Start automatisch geöffnet werden soll.
                      (z.B. ServiceWindow soll gespeichert, aber nicht automatisch geöffnet werden)
    """
    def decorator(cls: Type['PersistentWindow']) -> Type['PersistentWindow']:
        if cls.INSTANCE_ID:
            _window_registry[cls.INSTANCE_ID] = cls
            cls._auto_restore = auto_restore
        return cls
    return decorator


def save_all_persistent_windows():
    """Speichert alle offenen PersistentWindow-Instanzen (wird von MainWindow.closeEvent gerufen)."""
    for w in list(_open_windows):
        try:
            w.save_state()
        except (RuntimeError, AttributeError):
            pass


class PersistentWindow(QMainWindow):
    """Basisklasse fuer Fenster mit automatischem State Persistence."""

    INSTANCE_ID: ClassVar[str] = ""
    _auto_restore: ClassVar[bool] = True
    # True: Fenster bleibt nach manuellem Schliessen in der Fenster-Historie
    # (window_instances + instance_states bleiben erhalten – Symbol/Timeframe
    # werden fuer das naechste Oeffnen gemerkt). False (Default): Eintrag wird
    # beim manuellen Schliessen entfernt (Standard-Verhalten).
    _keep_history_on_close: ClassVar[bool] = False

    def __init__(self, parent=None, state_manager: Optional[StateManager] = None):
        # WICHTIG: KEIN Parent übergeben! Ein Fenster mit Parent (z.B. MainWindow)
        # hat unter Windows keinen eigenen Taskleisten-Eintrag und bleibt immer
        # über dem Parent-Fenster. Stattdessen wird parent nur für die Logik
        # (Zugriff auf state_manager) verwendet.
        super().__init__()
        self._state_manager: StateManager = state_manager or getattr(parent, 'state_manager', None) or StateManager()
        self._restored_is_maximized: bool = False

        # In Registry eintragen
        _open_windows.add(self)
        # 11.08.2026 (Bugfix Runde 17c, User-Meldungen 3+4): Window-Flags
        # HIER setzen - das Fenster ist zu diesem Zeitpunkt noch NICHT
        # sichtbar. setWindowFlags() auf einem SICHTBAREN Fenster bricht die
        # Layout-Geometrie-Verwaltung des QMainWindow-Layouts: Die
        # ContentScrollArea 'friert' auf der alten Groesse ein und folgt dem
        # manuellen Grossziehen/Maximieren nicht mehr. Der deferred Aufruf in
        # restore_state() ist damit nur noch eine defensive Wiederholung.
        self._fix_window_flags()

    @classmethod
    def get_registered_class(cls, instance_id: str) -> Optional[Type['PersistentWindow']]:
        """Gibt die registrierte Klasse fuer eine INSTANCE_ID zurueck (oder None)."""
        return _window_registry.get(instance_id)

    @classmethod
    def should_auto_restore(cls, instance_id: str) -> bool:
        """Ob ein Fenster mit dieser ID automatisch wiederhergestellt werden soll."""
        cls_type = _window_registry.get(instance_id)
        if cls_type is not None:
            return getattr(cls_type, '_auto_restore', True)
        return True

    @classmethod
    def get_existing_instance(cls) -> Optional['PersistentWindow']:
        """Gibt die erste offene Instanz dieser Klasse zurueck (oder None).
        
        Ermoeglicht Singleton-Verhalten fuer Subklassen (z.B. ServiceWindow,
        StatisticWindow): Statt ein neues Fenster zu oeffnen, wird die
        bestehende Instanz in den Vordergrund geholt.
        """
        for w in list(_open_windows):
            try:
                if type(w) is cls and w.isVisible():
                    return w
            except (RuntimeError, AttributeError):
                continue
        return None

    def _fix_window_flags(self) -> None:
        """Stellt sicher, dass das Fenster als normales Top-Level-Fenster
        (Qt.Window) konfiguriert ist und nicht als Tool/Dialog.

        Wichtig: Qt.Dialog | Qt.Tool sind bei QMainWindow immer gesetzt
        und können nicht entfernt werden. Das ist normales Qt-Verhalten.
        Ein Fenster ohne Parent hat automatisch einen Taskleisten-Eintrag.
        """
        # 11.08.2026 (Bugfix Runde 17d, User-Meldung 3): Int-basierte
        # Flag-Arithmetik (PySide6-Flag-Operatoren droppen Bits ausserhalb
        # des Enum-Domains, z. B. 0x08000000 bei '& ~WindowType_Mask').
        # 1) Typ explizit auf Qt.Window setzen: Qt.Dialog-/Qt.Tool-Fenster
        #    haben unter Windows KEINE Minimize/Maximize-Buttons.
        # 2) VOLLSTAENDIGEN Standard-Button-Satz setzen (Title, SystemMenu,
        #    Minimize, Maximize, Close) - fehlt ein Hint, graut Windows den
        #    Maximize-Button aus bzw. zeigt ihn gar nicht.
        # 3) MSWindowsFixedSizeDialogHint entfernen - dieses Flag deaktiviert
        #    den Maximize-Button auf Windows (Fenster gilt als fest gross).
        #    Qt setzt es ggf. automatisch, wenn das Fenster zeitweise als
        #    fixed erkannt wurde.
        flags = int(self.windowFlags())
        type_mask = 0xFF
        wanted = (flags & ~type_mask) | int(Qt.Window)
        wanted |= (int(Qt.WindowTitleHint) | int(Qt.WindowSystemMenuHint)
                   | int(Qt.WindowMinimizeButtonHint)
                   | int(Qt.WindowMaximizeButtonHint)
                   | int(Qt.WindowCloseButtonHint))
        wanted &= ~int(Qt.MSWindowsFixedSizeDialogHint)
        if wanted != flags:
            self.setWindowFlags(Qt.WindowFlags(int(wanted)))

    @property
    def state_manager(self) -> StateManager:
        return self._state_manager

    def get_instance_id(self) -> str:
        return self.INSTANCE_ID

    def get_persistent_symbol(self) -> str:
        """Ueberschreiben in Subklassen fuer Symbol-Filter-Restore."""
        return ""

    def get_persistent_timeframe(self) -> str:
        """Ueberschreiben in Subklassen fuer Timeframe-Filter-Restore."""
        return ""

    def restore_state(self) -> None:
        """Stellt Fenstergeometrie und Filter wieder her.
        
        Achtung: Ruft NICHT showMaximized() auf, da dies das Fenster in den
        Vordergrund bringen wuerde. Der Aufrufer (z.B. restore_all_windows)
        muss showMaximized() separat aufrufen, wenn is_maximized=True ist.
        """
        inst_id = self.get_instance_id()
        if not inst_id:
            return

        # Window-Flags korrigieren (QUiLoader setzt oft Qt.Tool | Qt.Dialog,
        # was Taskleisten-Eintrag unterdrückt und Fenster über Parent hält).
        # 11.08.2026 (Bugfix Runde 17c): NUR wenn das Fenster noch NICHT
        # sichtbar ist – setWindowFlags() auf einem sichtbaren Fenster bricht
        # die Layout-Geometrie-Verwaltung (Inhalt folgt dem Resize nicht
        # mehr). Die Flags werden seit Runde 17c bereits im Konstruktor
        # (PersistentWindow.__init__, Fenster unsichtbar) gesetzt; dieser
        # Aufruf ist nur noch eine defensive Wiederholung.
        if not self.isVisible():
            self._fix_window_flags()

        # Geometrie
        geom = self._state_manager.get_window_geometry(inst_id)
        if geom:
            pos_x = geom.get("pos_x")
            pos_y = geom.get("pos_y")
            width = geom.get("width") or self.width()
            height = geom.get("height") or self.height()

            # Runde 10 (Bug 5): Gegen ALLE Screens pruefen - eine Position
            # auf dem 2. Monitor ist NICHT off-screen (Fallback nur, wenn
            # sie auf KEINEM Screen liegt). Vorher wurde nur der Primary-
            # Screen geprueft -> Position auf Monitor 2 fiel auf (100,100)
            # zurueck.
            screens = [s.availableGeometry()
                       for s in QApplication.screens()]
            if pos_x is not None and pos_y is not None:
                on_screen = any(
                    (scr.x() - 100 <= pos_x <= scr.right())
                    and (scr.y() - 100 <= pos_y <= scr.bottom())
                    for scr in screens)
                if not on_screen:
                    pos_x, pos_y = 100, 100
                self.move(pos_x, pos_y)
                self.resize(width, height)

            # is_maximized wird NICHT hier ausgewertet, sondern vom Aufrufer
            self._restored_is_maximized = geom.get("is_maximized", False)

        # Symbol/Timeframe aus instance_states
        all_inst = self._state_manager.load_all_instances()
        matched = next((i for i in all_inst if i.get("instance_id") == inst_id), None)
        if matched:
            raw_symbol = matched.get("symbol")
            raw_tf = matched.get("timeframe")
            symbol = str(raw_symbol) if raw_symbol is not None else self.get_persistent_symbol()
            tf = str(raw_tf) if raw_tf is not None else self.get_persistent_timeframe()
            self._apply_persistent_filters(symbol, tf)

    def _apply_persistent_filters(self, symbol: str, timeframe: str) -> None:
        """Ueberschreiben in Subklassen um Filter anzuwenden."""
        pass

    def save_state(self) -> None:
        """Speichert Fenstergeometrie (und ggf. Filter)."""
        inst_id = self.get_instance_id()
        if not inst_id:
            return

        p, s = self.pos(), self.size()
        self._state_manager.save_window_geometry(
            inst_id, p.x(), p.y(), s.width(), s.height(), self.isMaximized()
        )

        symbol = self.get_persistent_symbol()
        tf = self.get_persistent_timeframe()
        if symbol and tf:
            self._state_manager.save_instance_state(
                instance_id=inst_id,
                symbol=symbol,
                timeframe=tf,
            )

    def closeEvent(self, event) -> None:
        """Beim manuellen Schliessen: State speichern, DB-Eintrag loeschen.
        
        Nur beim App-Beenden (_is_quitting) bleibt der Eintrag erhalten,
        damit das Fenster beim naechsten Start wiederhergestellt wird.
        Fenster mit `_keep_history_on_close = True` (z. B. AnalyticsWindow)
        bleiben auch nach manuellem Schliessen in der Historie, damit ihr
        Symbol/Timeframe-Zustand fuer das naechste Oeffnen gemerkt bleibt.
        """
        self.save_state()

        # DB-Eintrag nur loeschen, wenn die App NICHT insgesamt beendet wird
        # UND das Fenster nicht dauerhaft in der Historie bleiben soll.
        app = QApplication.instance()
        is_quitting = getattr(app, '_is_quitting', False) if app else False
        if not is_quitting and not self._keep_history_on_close:
            inst_id = self.get_instance_id()
            if inst_id:
                try:
                    self._state_manager.delete_instance(inst_id)
                except Exception:
                    pass

        _open_windows.discard(self)
        super().closeEvent(event)

```

--------------------------------------------------

### DATEI: properties_win.py
```py
# properties_win.py
"""
Properties-Fenster für PyTrader – nicht-modale Konfiguration der App-Einstellungen.
Mit automatischem State Persistence via PersistentWindow.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from config.app_settings import AppSettings
from config.event_bus import event_bus
from db.db_utils import compact_database
from persistent_win import PersistentWindow, register_persistent_window
from state_manager import StateManager

BASE_DIR = Path(__file__).resolve().parent


@register_persistent_window()
class PropertiesWindow(PersistentWindow):
    INSTANCE_ID = "win_properties"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state_mgr: StateManager = getattr(parent, 'state_manager', None) or StateManager()
        self._settings: AppSettings = self._state_mgr.get_app_settings()

        self.setWindowTitle("PyTrader - Optionen")
        self.setMinimumWidth(420)

        # Zentral-Widget
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Form
        form = QFormLayout()
        form.setSpacing(8)

        self.spin_chart_limit = QSpinBox()
        self.spin_chart_limit.setRange(100, 50000)
        self.spin_chart_limit.setSingleStep(100)
        self.spin_chart_limit.setValue(self._settings.chart_candle_limit)
        form.addRow("Chart-Candles (max):", self.spin_chart_limit)

        self.spin_feature_limit = QSpinBox()
        self.spin_feature_limit.setRange(100, 50000)
        self.spin_feature_limit.setSingleStep(100)
        self.spin_feature_limit.setValue(self._settings.feature_builder_limit)
        form.addRow("Feature-Builder Candles:", self.spin_feature_limit)

        self.spin_scanner_limit = QSpinBox()
        self.spin_scanner_limit.setRange(1000, 500000)
        self.spin_scanner_limit.setSingleStep(1000)
        self.spin_scanner_limit.setValue(self._settings.scanner_candle_limit)
        form.addRow("Scanner Candles (max):", self.spin_scanner_limit)

        self.spin_stats_limit = QSpinBox()
        self.spin_stats_limit.setRange(100, 100000)
        self.spin_stats_limit.setSingleStep(100)
        self.spin_stats_limit.setValue(self._settings.statistics_signal_limit)
        form.addRow("Statistik-Signale (max):", self.spin_stats_limit)

        self.spin_marker_limit = QSpinBox()
        self.spin_marker_limit.setRange(50, 5000)
        self.spin_marker_limit.setSingleStep(50)
        self.spin_marker_limit.setValue(self._settings.signal_marker_limit)
        form.addRow("Chart-Marker (max):", self.spin_marker_limit)

        self.spin_page_size = QSpinBox()
        self.spin_page_size.setRange(10, 500)
        self.spin_page_size.setSingleStep(10)
        self.spin_page_size.setValue(self._settings.statistics_page_size)
        form.addRow("Statistik-Seitengröße:", self.spin_page_size)

        layout.addLayout(form)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_save = QPushButton("💾 Speichern")
        btn_save.clicked.connect(self._save_settings)
        btn_layout.addWidget(btn_save)

        # Phase 21.02 (12.08.2026): DB-Service-Button für die Kompaktierung
        # (COPY FROM DATABASE – echte Verkleinerung). NICHT VACUUM: Die
        # reguläre DB-Pflege (CHECKPOINT+VACUUM) läuft beim App-Exit.
        btn_db_service = QPushButton("🧹 DB Service")
        btn_db_service.clicked.connect(self._on_btn_vacuum_clicked)
        btn_db_service.setToolTip(
            "Kompaktiert analytics.duckdb und market_data.duckdb "
            "(COPY FROM DATABASE). Gesperrt, solange Scans/Worker laufen."
        )
        btn_layout.addWidget(btn_db_service)

        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(self.close)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)
        layout.addStretch()

        # State asynchron wiederherstellen
        QTimer.singleShot(0, self.restore_state)

    def _save_settings(self) -> None:
        self._settings = AppSettings(
            chart_candle_limit=self.spin_chart_limit.value(),
            feature_builder_limit=self.spin_feature_limit.value(),
            scanner_candle_limit=self.spin_scanner_limit.value(),
            statistics_signal_limit=self.spin_stats_limit.value(),
            signal_marker_limit=self.spin_marker_limit.value(),
            statistics_page_size=self.spin_page_size.value(),
        )
        self._state_mgr.save_app_settings(self._settings)
        print(f"✅ Einstellungen gespeichert: {self._settings}")

    # ------------------------------------------------------------------
    # Phase 21.02 (12.08.2026): DB-Service / Kompaktierung
    # ------------------------------------------------------------------
    def _on_btn_vacuum_clicked(self) -> None:
        """Kompaktiert analytics.duckdb & market_data.duckdb (COPY FROM DATABASE).

        Concurrency-Guard über den EventBus-Zähler (Phase 21.02 K1): NICHT
        `self.parent()` – PersistentWindow übergibt kein Qt-Parent. Der
        Zähler wird von MainWindow in service_run_started/finished gepflegt.
        """
        if getattr(event_bus, "sync_pause_count", 0) > 0:
            print("⚠️ DB-Service gesperrt: Scans/Worker laufen aktuell.")
            return
        for _db_name in ("analytics", "market_data"):
            db_path = str(BASE_DIR / "data" / f"{_db_name}.duckdb")
            try:
                info = compact_database(db_path)
                print(f"✅ DB-Service: {_db_name}.duckdb kompaktiert "
                      f"({info['size_mb']} MB, {info['pct']}% fragmentiert)")
            except Exception as exc:
                print(f"❌ DB-Service: {_db_name}.duckdb fehlgeschlagen: {exc}")

    def get_settings(self) -> AppSettings:
        """Gibt die aktuell geladenen Einstellungen zurück."""
        return self._settings

    def closeEvent(self, event):
        super().closeEvent(event)

```

--------------------------------------------------

### DATEI: state_manager.py
```py
# state_manager.py

"""
state_manager.py - Persistence Manager with Symbol/TF Reset Support, Robust Schema Migration & Type Validation
"""

import json
import os
from typing import Any, Dict, List, Optional
import duckdb

from db_service import _parse_json_field, DbPool
from config.base_state_model import AbstractStateModel
from config.app_settings import AppSettings
# Phase 15.04: Instanz-/Fenster-SQL-Zugriffe sind in das
# WindowStateRepository ausgelagert (window_state_repository.py). Der
# StateManager ist seitdem eine additive Fassade – alle Bestands-Methoden
# bleiben mit identischen Signaturen erhalten und delegieren intern.
from window_state_repository import WindowStateRepository

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DB_PATH = os.path.join(BASE_DIR, "data", "app_data.duckdb")

KEY_APP_SETTINGS = "app_settings"


class StateManager:

    def __init__(self, db_path: str = APP_DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()
        # Phase 15.04: Fassaden-Delegation an das WindowStateRepository.
        # Die DB-Pfad-Aufloesung verbleibt beim StateManager und wird an das
        # Repository durchgereicht (Test-Isolation: Temp-DBs bleiben getrennt).
        self._window_repo = WindowStateRepository(db_path)

    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        return DbPool.get(self.db_path)

    def _init_db(self) -> None:
        """Initialisiert die Tabellenstrukturen und f\u00fchrt eine saubere Schema-Migration durch."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        con = self._get_connection()
        con.execute("""
            CREATE TABLE IF NOT EXISTS window_instances (
                instance_id VARCHAR PRIMARY KEY,
                preset_id VARCHAR,
                window_title VARCHAR,
                pos_x INTEGER,
                pos_y INTEGER,
                width INTEGER,
                height INTEGER,
                is_maximized BOOLEAN DEFAULT FALSE
            );

            CREATE TABLE IF NOT EXISTS instance_states (
                instance_id VARCHAR PRIMARY KEY,
                symbol VARCHAR NOT NULL,
                timeframe VARCHAR NOT NULL,
                visible_range_from BIGINT,
                visible_range_to BIGINT,
                visible_price_from DOUBLE,
                visible_price_to DOUBLE,
                indicators_state JSON,
                measurement_state JSON,
                workspace_state JSON,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS symbol_tf_states (
                symbol VARCHAR NOT NULL,
                timeframe VARCHAR NOT NULL,
                visible_range_from BIGINT,
                visible_range_to BIGINT,
                visible_price_from DOUBLE,
                visible_price_to DOUBLE,
                indicators_state JSON,
                measurement_state JSON,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, timeframe)
            );

            CREATE TABLE IF NOT EXISTS indicator_presets (
                indicator_id VARCHAR NOT NULL,
                preset_name VARCHAR NOT NULL,
                params JSON NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (indicator_id, preset_name)
            );

            CREATE TABLE IF NOT EXISTS global_settings (
                key VARCHAR PRIMARY KEY,
                value JSON NOT NULL
            );
        """)

        # Phase 12 (Hybrid-Schema): Additive Erweiterung der indicator_presets
        # um die Plugin-Verknuepfung. plugin_id verknuepft ein Preset mit einem
        # Plugin (z.B. 'srv_grid_lines'), version fuehrt die Plugin-Version und
        # is_active_batch markiert Presets, die von den Batch-Services
        # (HistoricalScanner/LiveAnalyzer) ueber den PluginExecutor aktiv
        # verarbeitet werden. Bestehende Presets und Daten bleiben unangetastet.
        con.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS plugin_id VARCHAR;")
        con.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS version VARCHAR DEFAULT '1.0.0';")
        con.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS is_active_batch BOOLEAN DEFAULT FALSE;")
        # 20.04 (Q7, 09.08.2026): Doc-Log-Spalte fuer Presets/Clones –
        # Freitextfeld (Negativ-Wissen) analog ServiceInstanceConfig.doc_log.
        # Additiv/idempotent – bestehende Presets bleiben unangetastet.
        con.execute("ALTER TABLE indicator_presets ADD COLUMN IF NOT EXISTS doc_log VARCHAR;")
        
        # Phase 20.01 (09.08.2026): Analytics-Workspace-Persistenz – additive
        # JSON-Spalte `workspace_state` in instance_states (win_analytics:
        # vm.params + UI-Layout). Idempotent – bestehende Zeilen/Spalten
        # bleiben unangetastet.
        con.execute("ALTER TABLE instance_states ADD COLUMN IF NOT EXISTS workspace_state JSON;")

        # Phase 15 (U15-B4): Alt-Indikator 'grid' (chart/indicators/grid.py)
        # wurde am 04.08.2026 entfernt. Persistierte Presets mit
        # indicator_id='grid' werden idempotent bereinigt (einmalig pro
        # App-Start, additiv – bestehende 'ind_fixed_grid_proximity'-Presets
        # bleiben unangetastet). Der Legacy-Pfad in _resolve_indicator_params()
        # bleibt fuer Abwaertskompatibilitaet bestehen.
        con.execute("DELETE FROM indicator_presets WHERE indicator_id = 'grid'")

        # Phase 16 (06.08.2026): Rollen- und Namens-Klarheit – der Indikator
        # 'grid_liquidity' wurde in 'ind_fixed_grid_proximity' umbenannt
        # (indicator_id/indicators_state-Key). Persistierte Alt-Referenzen
        # (indicator_presets.indicator_id sowie indicators_state-JSON in
        # instance_states/symbol_tf_states) werden idempotent migriert.
        _legacy_ind_id = "grid_liquidity"
        _new_ind_id = "ind_fixed_grid_proximity"
        try:
            con.execute(
                "UPDATE indicator_presets SET indicator_id = ? WHERE indicator_id = ?",
                [_new_ind_id, _legacy_ind_id])
            # indicators_state-JSON: Legacy-Key auf neuen Indikator-Key mappen.
            for _row in con.execute(
                    "SELECT instance_id, indicators_state FROM instance_states").fetchall():
                _rid, _raw = _row[0], _row[1]
                if _raw is None:
                    continue
                _data = _parse_json_field(_raw) if isinstance(_raw, str) else _raw
                if not isinstance(_data, dict) or _legacy_ind_id not in _data:
                    continue
                _data.setdefault(_new_ind_id, _data.pop(_legacy_ind_id))
                con.execute(
                    "UPDATE instance_states SET indicators_state = ? WHERE instance_id = ?",
                    [json.dumps(_data), _rid])
            for _row in con.execute(
                    "SELECT symbol, timeframe, indicators_state FROM symbol_tf_states").fetchall():
                _sym, _tf, _raw = _row[0], _row[1], _row[2]
                if _raw is None:
                    continue
                _data = _parse_json_field(_raw) if isinstance(_raw, str) else _raw
                if not isinstance(_data, dict) or _legacy_ind_id not in _data:
                    continue
                _data.setdefault(_new_ind_id, _data.pop(_legacy_ind_id))
                con.execute(
                    "UPDATE symbol_tf_states SET indicators_state = ? WHERE symbol = ? AND timeframe = ?",
                    [json.dumps(_data), _sym, _tf])
        except Exception as e:
            print(f"WARN [StateManager] Phase-16-Migration (grid_liquidity -> "
                  f"ind_fixed_grid_proximity) fehlgeschlagen: {e}")

        # Phase 16.08.01 (Naming Conventions): Service-Plugin-IDs wurden in
        # 'srv_grid_lines'/'srv_proximity' umbenannt (Datei-/Klassen-Renames).
        # Persistierte Alt-Referenzen werden idempotent nachgezogen:
        #   * service_sets / service_sets_trash / service_set_history
        #     (definition JSON -> services[].plugin_id)
        #   * indicator_presets.plugin_id
        #   * analytics.duckdb/feature_store.feature_id
        # Additiv und defensiv: nur exakte Alt-Werte werden ersetzt, fehlende
        # Tabellen/Spalten/DBs werden stillschweigend uebersprungen.
        _plugin_id_map = {"grid_lines": "srv_grid_lines",
                          "proximity": "srv_proximity"}

        def _map_plugin_ids_in_definition(definition: Any) -> bool:
            """Migriert services[].plugin_id in einer Set-Definition (JSON).
            Liefert True, wenn mindestens ein Wert geaendert wurde."""
            if not isinstance(definition, dict):
                return False
            services = definition.get("services")
            if not isinstance(services, dict):
                return False
            changed = False
            for cfg in services.values():
                if not isinstance(cfg, dict):
                    continue
                pid = cfg.get("plugin_id")
                if pid in _plugin_id_map:
                    cfg["plugin_id"] = _plugin_id_map[pid]
                    changed = True
            return changed

        try:
            for _tbl in ("service_sets", "service_sets_trash", "service_set_history"):
                try:
                    _rows = con.execute(
                        f"SELECT set_id, definition FROM {_tbl}").fetchall()
                except Exception:
                    continue  # Tabelle existiert nicht -> ueberspringen
                for _rid, _raw in _rows:
                    if _raw is None:
                        continue
                    _data = _parse_json_field(_raw) if isinstance(_raw, str) else _raw
                    if not _map_plugin_ids_in_definition(_data):
                        continue
                    con.execute(
                        f"UPDATE {_tbl} SET definition = ? WHERE set_id = ?",
                        [json.dumps(_data), _rid])
        except Exception as e:
            print(f"WARN [StateManager] 16.08.01-Migration (service_sets-"
                  f"plugin_ids) fehlgeschlagen: {e}")

        try:
            for _old_pid, _new_pid in _plugin_id_map.items():
                con.execute(
                    "UPDATE indicator_presets SET plugin_id = ? WHERE plugin_id = ?",
                    [_new_pid, _old_pid])
        except Exception as e:
            print(f"WARN [StateManager] 16.08.01-Migration (indicator_presets-"
                  f"plugin_id) fehlgeschlagen: {e}")

        # analytics.duckdb/feature_store.feature_id (separate DB, defensiv)
        try:
            _ana_path = os.path.join(
                os.path.dirname(self.db_path), "analytics.duckdb")
            if os.path.exists(_ana_path):
                _ana_con = DbPool.get(_ana_path)
                for _old_fid, _new_fid in _plugin_id_map.items():
                    _ana_con.execute(
                        "UPDATE feature_store SET feature_id = ? WHERE feature_id = ?",
                        [_new_fid, _old_fid])
        except Exception as e:
            print(f"WARN [StateManager] 16.08.01-Migration (feature_store-"
                  f"feature_id) fehlgeschlagen: {e}")

        # Explicit Column Check via information_schema
        tables_to_migrate = ["instance_states", "symbol_tf_states"]
        columns_to_check = ["indicators_state", "measurement_state"]

        for table in tables_to_migrate:
            existing_cols = con.execute(f"""
                SELECT LOWER(column_name)
                FROM information_schema.columns
                WHERE LOWER(table_name) = '{table.lower()}'
            """).fetchall()
            existing_col_names = [col[0] for col in existing_cols]

            for col_name in columns_to_check:
                if col_name.lower() not in existing_col_names:
                    try:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} JSON")
                        print(f"[MIGRATION] Spalte '{col_name}' (JSON) zur Tabelle '{table}' hinzugefuegt.")
                    except Exception as e:
                        print(f"[MIGRATION WARNUNG] Spalte '{col_name}' konnte nicht hinzugefuegt werden: {e}")

    def get_next_instance_id(self) -> str:
        # Phase 15.04: Delegation an das WindowStateRepository.
        return self._window_repo.get_next_instance_id()

    def delete_instance(self, instance_id: str) -> None:
        # Phase 15.04: Delegation an das WindowStateRepository.
        self._window_repo.delete_instance(instance_id)

    def delete_symbol_tf_state(self, symbol: str, timeframe: str) -> None:
        # Phase 15.04: Delegation an das WindowStateRepository.
        self._window_repo.delete_symbol_tf_state(symbol, timeframe)

    def save_instance_state(
        self,
        instance_id: str,
        symbol: str,
        timeframe: str,
        visible_range_from: Optional[int] = None,
        visible_range_to: Optional[int] = None,
        visible_price_from: Optional[float] = None,
        visible_price_to: Optional[float] = None,
        indicators_state: Optional[Dict[str, Any]] = None,
        measurement_state: Optional[Dict[str, Any]] = None
    ) -> None:
        # Phase 15.04: Delegation an das WindowStateRepository.
        self._window_repo.save_instance_state(
            instance_id, symbol, timeframe,
            visible_range_from, visible_range_to,
            visible_price_from, visible_price_to,
            indicators_state, measurement_state,
        )

    def save_symbol_tf_state(
        self,
        symbol: str,
        timeframe: str,
        visible_range_from: Optional[int] = None,
        visible_range_to: Optional[int] = None,
        visible_price_from: Optional[float] = None,
        visible_price_to: Optional[float] = None,
        indicators_state: Optional[Dict[str, Any]] = None,
        measurement_state: Optional[Dict[str, Any]] = None
    ) -> None:
        # Phase 15.04: Delegation an das WindowStateRepository.
        self._window_repo.save_symbol_tf_state(
            symbol, timeframe,
            visible_range_from, visible_range_to,
            visible_price_from, visible_price_to,
            indicators_state, measurement_state,
        )

    def get_symbol_tf_state(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        # Phase 15.04: Delegation an das WindowStateRepository.
        return self._window_repo.get_symbol_tf_state(symbol, timeframe)

    def save_window_geometry(
        self,
        instance_id: str,
        x: int,
        y: int,
        width: int,
        height: int,
        is_maximized: bool,
        preset_id: Optional[str] = None
    ) -> None:
        # Phase 15.04: Delegation an das WindowStateRepository.
        self._window_repo.save_window_geometry(
            instance_id, x, y, width, height, is_maximized, preset_id,
        )

    def get_window_geometry(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Liest die gespeicherte Fenstergeometrie einer spezifischen Instanz aus.

        Phase 15.04: Delegation an das WindowStateRepository (Bestandsverhalten
        exakt reproduziert).
        """
        return self._window_repo.get_window_geometry(instance_id)

    # Phase 20.01: Workspace-Persistenz (win_analytics) – Fassaden-Delegation
    # an das WindowStateRepository (Muster 15.04, identische Signaturen).
    def save_workspace_state(
        self, instance_id: str, state: Dict[str, Any]
    ) -> None:
        """Persistiert einen Fenster-Workspace (E6, NOT-NULL-konform).

        `workspace_state` (JSON) wird auf die instance_states-Zeile der
        Instanz ge-upsertet; symbol/timeframe der Zeile bleiben erhalten
        (Fallback ''/'M1' bei noch nicht existierender Row).
        """
        self._window_repo.save_workspace_state(instance_id, state)

    def get_workspace_state(
        self, instance_id: str
    ) -> Optional[Dict[str, Any]]:
        """Liest den gespeicherten Fenster-Workspace (oder None)."""
        return self._window_repo.get_workspace_state(instance_id)

    def load_all_instances(self) -> List[Dict[str, Any]]:
        # Phase 15.04: Delegation an das WindowStateRepository (pandas-.df()-
        # Leseart + String-Normalisierung exakt wie im Bestand).
        return self._window_repo.load_all_instances()

    def get_indicator_preset(self, indicator_id: str, preset_name: str) -> Optional[Dict[str, Any]]:
        """Liest die Parametervalue eines Indikator-Presets (RÜCKWÄRTSKOMPATIBEL:
        gibt direkt das params-Dict zurück, wie vom bestehenden indicator_dialog erwartet)."""
        con = self._get_connection()
        res = con.execute(
            "SELECT params FROM indicator_presets WHERE indicator_id = ? AND preset_name = ?",
            [indicator_id, preset_name]
        ).fetchone()
        if res and res[0]:
            return _parse_json_field(res[0])
        return None

    def get_indicator_preset_meta(self, indicator_id: str, preset_name: str) -> Optional[Dict[str, Any]]:
        """Liest ein Indikator-Preset INKL. Plugin-Verknüpfung (Phase 12 Hybrid-Schema).
        Rückgabe: {"params": ..., "plugin_id": ..., "version": ..., "is_active_batch": ...}."""
        con = self._get_connection()
        res = con.execute(
            "SELECT params, plugin_id, version, is_active_batch FROM indicator_presets WHERE indicator_id = ? AND preset_name = ?",
            [indicator_id, preset_name]
        ).fetchone()
        if res and res[0]:
            params = _parse_json_field(res[0])
            data = {"params": params}
            # Neue Hybrid-Schema-Spalten (können NULL sein bei Alt-Presets)
            if len(res) > 1 and res[1] is not None:
                data["plugin_id"] = str(res[1])
            if len(res) > 2 and res[2] is not None:
                data["version"] = str(res[2])
            if len(res) > 3 and res[3] is not None:
                data["is_active_batch"] = bool(res[3])
            return data
        return None

    def save_indicator_preset(
        self,
        indicator_id: str,
        preset_name: str,
        params: Dict[str, Any],
        plugin_id: Optional[str] = None,
        version: Optional[str] = None,
        is_active_batch: bool = False,
        doc_log: Optional[str] = None,
    ) -> None:
        """Speichert ein Indikator-Preset. Unterstützt zusätzlich plugin_id,
        version und is_active_batch (Phase 12 Hybrid-Schema) sowie das
        Doc-Log (20.04, Q7)."""
        con = self._get_connection()
        con.execute("""
            INSERT INTO indicator_presets (indicator_id, preset_name, params, plugin_id, version, is_active_batch, doc_log)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (indicator_id, preset_name) DO UPDATE SET
                params = EXCLUDED.params,
                plugin_id = EXCLUDED.plugin_id,
                version = EXCLUDED.version,
                is_active_batch = EXCLUDED.is_active_batch,
                doc_log = EXCLUDED.doc_log;
        """, [
            indicator_id, preset_name, json.dumps(params),
            plugin_id, version, bool(is_active_batch), doc_log,
        ])

    def delete_indicator_preset(self, indicator_id: str, preset_name: str) -> None:
        con = self._get_connection()
        con.execute(
            "DELETE FROM indicator_presets WHERE indicator_id = ? AND preset_name = ?",
            [indicator_id, preset_name]
        )

    def rename_indicator_preset(self, indicator_id: str, old_name: str,
                                new_name: str) -> None:
        """Benennt ein Indikator-/Plugin-Preset um (10.08.2026, Bugfix).

        'Variante umbenennen' im MasterTree-Kontextmenue (Clone/Preset):
        Der Primaerschluessel von indicator_presets ist (indicator_id,
        preset_name) – der Rename ist ein UPDATE des preset_name. Alle
        weiteren Spalten (params, plugin_id, version, is_active_batch,
        doc_log) bleiben unangetastet. Der Aufrufer muss zuvor auf
        Namenskollisionen pruefen (sonst Unique-Constraint-Fehler).
        """
        con = self._get_connection()
        con.execute(
            "UPDATE indicator_presets SET preset_name = ? "
            "WHERE indicator_id = ? AND preset_name = ?",
            [new_name, indicator_id, old_name]
        )

    def list_plugin_presets(self, plugin_id: str) -> List[Dict[str, Any]]:
        """Liefert alle Presets eines Plugins (20.04, Q7).

        Quelle: indicator_presets (Spalte plugin_id, Phase-12-Hybrid-Schema).
        Rueckgabe pro Eintrag: {"indicator_id", "preset_name", "params",
        "plugin_id", "version", "is_active_batch", "doc_log"} –
        deterministisch (preset_name ASC). Grundlage der Parent-Child-Clone-
        Ansicht im MasterTree (Services-Gruppe: Plugin -> Presets/Clones)
        und der Archiv-Logik (Q7: Archivierung eines Presets =>
        is_active_batch = False; die Scans isolieren is_active_batch=False-
        Presets).
        """
        con = self._get_connection()
        res = con.execute("""
            SELECT indicator_id, preset_name, params, plugin_id, version,
                   is_active_batch, doc_log
            FROM indicator_presets
            WHERE plugin_id = ?
            ORDER BY preset_name ASC
        """, [plugin_id]).fetchall()
        presets: List[Dict[str, Any]] = []
        for indicator_id, preset_name, params_json, pid, version, is_active, doc_log in res:
            presets.append({
                "indicator_id": indicator_id,
                "preset_name": preset_name,
                "params": _parse_json_field(params_json) if params_json else {},
                "plugin_id": pid,
                "version": version,
                "is_active_batch": bool(is_active),
                "doc_log": str(doc_log) if doc_log else "",
            })
        return presets

    def set_plugin_preset_doc_log(self, indicator_id: str, preset_name: str,
                                  doc_log: str) -> None:
        """Persistiert das Doc-Log (Negativ-Wissen) eines Plugin-Presets.

        20.04 (Q7): analog ServiceInstanceConfig.doc_log – Freitextfeld,
        das im MasterTree-Clone-Tooltip angezeigt wird. Additiv: bestehende
        Presets ohne Eintrag bleiben unangetastet (doc_log = NULL).
        """
        con = self._get_connection()
        con.execute(
            "UPDATE indicator_presets SET doc_log = ? "
            "WHERE indicator_id = ? AND preset_name = ?",
            [(doc_log or "").strip() or None, indicator_id, preset_name])

    def list_indicator_presets(self, indicator_id: str) -> List[str]:
        con = self._get_connection()
        res = con.execute(
            "SELECT preset_name FROM indicator_presets WHERE indicator_id = ? ORDER BY preset_name ASC",
            [indicator_id]
        ).fetchall()
        presets = [r[0] for r in res]
        if "Default" not in presets:
            presets.insert(0, "Default")
        return presets

    def list_active_batch_presets(self) -> List[Dict[str, Any]]:
        """Liefert alle Batch-aktiven Plugin-Presets (Phase 12 Hybrid-Schema).

        Selektiert aus indicator_presets nur Presets mit is_active_batch = TRUE
        und gesetzter plugin_id. Diese steuern den Plugin-Modus der
        Batch-Services (HistoricalScanner / LiveAnalyzer) über den
        PluginExecutor – der Alt-Pfad bleibt davon unberührt.

        Rückgabe: Liste von {"indicator_id", "preset_name", "plugin_id",
        "version", "params"}.
        """
        con = self._get_connection()
        res = con.execute("""
            SELECT indicator_id, preset_name, params, plugin_id, version, is_active_batch
            FROM indicator_presets
            WHERE is_active_batch = TRUE AND plugin_id IS NOT NULL
            ORDER BY preset_name ASC
        """).fetchall()
        presets: List[Dict[str, Any]] = []
        for indicator_id, preset_name, params_json, plugin_id, version, is_active in res:
            presets.append({
                "indicator_id": indicator_id,
                "preset_name": preset_name,
                "plugin_id": plugin_id,
                "version": version,
                "params": _parse_json_field(params_json) if params_json else {},
            })
        return presets

    def get_app_settings(self) -> AppSettings:
        """L\u00e4dt AppSettings aus der DB oder gibt Defaults zur\u00fcck."""
        con = self._get_connection()
        row = con.execute(
            "SELECT value FROM global_settings WHERE key = ?",
            [KEY_APP_SETTINGS]
        ).fetchone()
        if row and row[0]:
            raw = row[0]
            data = _parse_json_field(raw)
            return AppSettings.from_dict(data)
        return AppSettings()

    def save_app_settings(self, settings: AppSettings) -> None:
        """Speichert AppSettings in der DB."""
        con = self._get_connection()
        con.execute("""
            INSERT INTO global_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, [KEY_APP_SETTINGS, json.dumps(settings.to_dict())])

    # =========================================================================
    # Generische global_settings-Zugriffe (17.01.04, Plugin-Parameter-Presets)
    # -------------------------------------------------------------------------
    # Speichert/liest beliebige JSON-Werte unter einem Key in global_settings.
    # Verwendet fuer die Standalone-Plugin-Parameter des ServiceWindows
    # (Key 'plugin_params_<plugin_id>'): Parameter + lookback + Beschreibung
    # eines Plugin ohne Set werden hier persistiert, damit die Parameter-Spalte
    # beim Klick auf eine Plugin-Zeile unter 'Services' die gespeicherten
    # Werte anzeigt und die Ausfuehrung sie nutzt.
    # =========================================================================
    def save_global_value(self, key: str, value: Any) -> None:
        """Speichert einen beliebigen JSON-faehigen Wert unter `key`."""
        con = self._get_connection()
        con.execute("""
            INSERT INTO global_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, [key, json.dumps(value)])

    def get_global_value(self, key: str, default: Any = None) -> Any:
        """Liest den unter `key` gespeicherten Wert (oder `default`)."""
        con = self._get_connection()
        row = con.execute(
            "SELECT value FROM global_settings WHERE key = ?", [key]
        ).fetchone()
        if row and row[0]:
            return _parse_json_field(row[0])
        return default

    # =========================================================================
    # Dialog-Geometrie (nicht-modale Dialoge, z. B. IndicatorSettingsDialog)
    # -------------------------------------------------------------------------
    # Speichert Position/Groesse eines nicht-modalen Dialogs in global_settings,
    # damit er beim erneuten Oeffnen an der letzten Position erscheint.
    # dialog_key: z. B. "indicator_settings" (gilt generisch fuer alle Indikatoren)
    # =========================================================================
    def save_dialog_geometry(self, dialog_key: str, x: int, y: int, width: int, height: int) -> None:
        con = self._get_connection()
        key = f"dialog_geometry_{dialog_key}"
        con.execute("""
            INSERT INTO global_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, [key, json.dumps({"pos_x": x, "pos_y": y, "width": width, "height": height})])

    def get_dialog_geometry(self, dialog_key: str) -> Optional[Dict[str, Any]]:
        """Liest die gespeicherte Dialog-Geometrie eines dialog_key aus (oder None)."""
        con = self._get_connection()
        key = f"dialog_geometry_{dialog_key}"
        row = con.execute("SELECT value FROM global_settings WHERE key = ?", [key]).fetchone()
        if row and row[0]:
            data = _parse_json_field(row[0])
            if isinstance(data, dict):
                return data
        return None

    # =========================================================================
    # Splitter-Persistenz (13.08.2026, Runde 3d): Grafikteiler Tree|Parameter
    # -------------------------------------------------------------------------
    # Speichert die zuletzt vom Anwender eingestellte Splitter-Position
    # (z. B. MasterTree | Parameter-Panel) unter global_settings
    # (Key 'splitter_<dialog_key>'). Sie wird beim erneuten Oeffnen des
    # Fensters/Dialogs wiederhergestellt (Gesamt-Historie) und zusaetzlich
    # ueber den Analytics-Workspace + Profil-Payload (service_picker_splitter)
    # persistiert. dialog_key: z. B. "service_selector" / "win_service".
    # =========================================================================
    def save_splitter_state(self, dialog_key: str, sizes) -> None:
        """Persistiert die Splitter-Position (Liste von Pixel-Breiten)."""
        con = self._get_connection()
        key = f"splitter_{dialog_key}"
        try:
            sizes = [int(x) for x in (sizes or [])]
        except (TypeError, ValueError):
            sizes = []
        con.execute("""
            INSERT INTO global_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """, [key, json.dumps(sizes)])

    def get_splitter_state(self, dialog_key: str) -> Optional[List[int]]:
        """Liest die gespeicherte Splitter-Position eines dialog_key (oder None)."""
        con = self._get_connection()
        key = f"splitter_{dialog_key}"
        row = con.execute(
            "SELECT value FROM global_settings WHERE key = ?", [key]).fetchone()
        if row and row[0]:
            data = _parse_json_field(row[0])
            if isinstance(data, list):
                try:
                    return [int(x) for x in data]
                except (TypeError, ValueError):
                    return None
        return None

```

--------------------------------------------------

### DATEI: db/db_utils.py
```py
# db/db_utils.py
"""
db/db_utils.py - Gemeinsame DB-Hilfsfunktionen.

Ausgelagert aus db_service.py im Rahmen von 18.01.02 (E3): `_parse_json_field`
(DuckDB liefert JSON teils als str, teils als dict) und `_ensure_epoch`
(DEPRECATED, backward-compat). Basis-Schicht (E4) – kein Projekt-Import.

Phase 21.02 (12.08.2026): DB-Bloat-Analyse & Maintenance (Kap. 21.02
AKTUELLE_UMSETZUNG):
  * get_db_fragmentation_info() – PRAGMA database_size (F1: res[2]/res[4])
  * execute_db_vacuum()         – CHECKPOINT gefolgt von VACUUM (App-Exit)
  * copy_database()             – COPY FROM DATABASE (echte Kompaktierung)
  * compact_database()          – Kompaktierung inkl. Datei-Ersatz
                                 (Windows File-Locking-sicher, F2)
"""

import calendar
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from db.db_pool import DbPool


def _ensure_epoch(val: Any) -> int:
    """DEPRECATED: Nutze stattdessen EXTRACT('epoch' FROM time)::BIGINT in SQL.
    Diese Funktion zerstört die Zeitzone bei TIMESTAMPTZ (timetuple() verliert offset).
    Nur noch für backward-compat in Test-Dateien."""
    if isinstance(val, datetime):
        return calendar.timegm(val.timetuple())
    return int(val)


def _parse_json_field(val: Any) -> Any:
    """Wandelt JSON aus DuckDB in Python-Objekt um (str->dict, dict bleibt)."""
    if isinstance(val, str):
        return json.loads(val) if val else None
    return val


# ---------------------------------------------------------------------------
# Phase 21.02 (12.08.2026): DB-Bloat-Analyse & Maintenance
# ---------------------------------------------------------------------------
def get_db_fragmentation_info(db_path: str) -> dict:
    """Liefert Fragmentierung/Bloat einer DuckDB-Datei (21.02, Schritt 1).

    Basis: `PRAGMA database_size` (DuckDB 1.5.5). Spaltenreihenfolge:
        0 database_name, 1 database_size (VARCHAR), 2 block_size,
        3 total_blocks, 4 used_blocks, 5 free_blocks, ...
    Bloat = Dateigröße - (used_blocks * block_size). Bei nicht vorhandener
    Datei oder Fehler werden Null-Werte geliefert (defensiv).

    Returns:
        {"pct": float, "bloat_mb": float, "size_mb": float}
    """
    if not os.path.exists(db_path):
        return {"pct": 0, "bloat_mb": 0, "size_mb": 0}
    file_bytes = os.path.getsize(db_path)
    try:
        con = DbPool.get(db_path)
        res = con.execute("PRAGMA database_size;").fetchone()
        # F1 (12.08.2026): korrekte Indizes res[2]/res[4] statt res[1]/res[3]
        block_size, used_blocks = (res[2], res[4]) if res else (262144, 0)
        netto_bytes = used_blocks * block_size
        bloat_bytes = max(0, file_bytes - netto_bytes)
        return {
            "pct": round((bloat_bytes / file_bytes * 100), 1) if file_bytes else 0,
            "bloat_mb": round(bloat_bytes / (1024 * 1024), 1),
            "size_mb": round(file_bytes / (1024 * 1024), 1)
        }
    except Exception:
        return {"pct": 0, "bloat_mb": 0, "size_mb": round(file_bytes / (1024 * 1024), 1)}


def execute_db_vacuum(db_path: str) -> None:
    """DB-Pflege beim App-Exit (21.02, Stufe 1): CHECKPOINT gefolgt von VACUUM.

    CHECKPOINT flusht die WAL in die Hauptdatei (konsistenter Zustand, kein
    WAL-Replay beim nächsten Start); VACUUM ist in DuckDB ohne
    Dateigrößen-Effekt (echte Kompaktierung siehe compact_database).
    """
    con = DbPool.get(db_path)
    con.execute("CHECKPOINT;")
    con.execute("VACUUM;")


def copy_database(src_db_path: str, dst_db_path: str) -> None:
    """Kompaktierung (21.02, Stufe 2): COPY FROM DATABASE in frische Datei.

    Erzeugt eine 100 % lückenlose Kopie inkl. Schema/Constraints/Indizes.
    Katalogname der Quelle = Datei-Basename ohne .duckdb (ggf. gequotet).
    dst_db_path sollte ein absoluter Pfad sein (BASE_DIR-basiert).
    """
    src_db_path = os.path.abspath(src_db_path)
    dst_db_path = os.path.abspath(dst_db_path)
    if not os.path.exists(src_db_path):
        raise FileNotFoundError(f"Quell-DB nicht gefunden: {src_db_path}")
    # Alte Ziel-Datei entfernen, falls vorhanden (sonst ATTACH auf bestehende Datei)
    if os.path.exists(dst_db_path):
        os.remove(dst_db_path)
    con = DbPool.get(src_db_path)
    src_catalog = Path(src_db_path).stem  # z. B. 'analytics'
    dst_sql = dst_db_path.replace("\\", "/")
    con.execute(f"ATTACH '{dst_sql}' AS new_db")
    con.execute(f'COPY FROM DATABASE "{src_catalog}" TO new_db')
    con.execute("DETACH new_db")


def compact_database(db_path: str) -> dict:
    """Kompaktiert eine DuckDB-Datei inkl. Datei-Ersatz (21.02, Stufe 2).

    Windows File-Locking: Vor dem Löschen/Umbenennen wird die DbPool-
    Verbindung des aktuellen Threads zur DB geschlossen (DbPool.release).
    Andere Threads (Scans/Worker) müssen beendet sein – der Aufrufer stellt
    das über den Concurrency-Guard sicher (_sync_pause_count == 0).

    Returns:
        dict von get_db_fragmentation_info() NACH der Kompaktierung.
    """
    db_path = os.path.abspath(db_path)
    if not os.path.exists(db_path):
        return {"pct": 0, "bloat_mb": 0, "size_mb": 0}
    tmp_path = f"{db_path}.compacted.duckdb"
    # 1) Kopieren (COPY FROM DATABASE)
    copy_database(db_path, tmp_path)
    # 2) Verbindung(en) des aktuellen Threads zur DB schliessen (File-Lock)
    DbPool.release(db_path)
    # 3) Alte Datei ersetzen
    os.remove(db_path)
    os.replace(tmp_path, db_path)
    return get_db_fragmentation_info(db_path)

```

--------------------------------------------------

