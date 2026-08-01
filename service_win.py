# service_win.py
"""
Service-Kontrollfenster für PyTrader.
Steuert den Historical Scanner (Full-Scan / Delta-Update) über ein separates Fenster.
Mit automatischem State Persistence via PersistentWindow.

Phase 13 Schritt 4: Zusätzlich Service-Set-Verwaltung (ServiceSetRepository +
ServiceSetEvaluator): Set-Auswahl (list_sets()), execution_order-Anzeige mit
Up/Down-Umsortierung, Name (leer → Auto-Name), Speichern/Löschen (mit
QMessageBox-Rückfrage) und Ausführen (ServiceSetEvaluator im Hintergrund).
"""

from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QFile, QIODevice, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QTextEdit, QWidget,
)

from analytics.background_workers.historical_scanner import HistoricalScanner
from analytics.engine.service_set_repository import ServiceSetRepository
from analytics.engine.set_evaluator import ServiceSetEvaluator
from persistent_win import PersistentWindow, register_persistent_window

BASE_DIR = Path(__file__).resolve().parent


class ServiceSetRunWorker(QThread):
    """Phase 13 Schritt 4: Führt ein Service-Set im Hintergrund aus.

    Lädt OHLCV (Symbol/Timeframe) und ruft ServiceSetEvaluator.execute_set()
    in einem separaten Thread auf, damit die GUI nicht blockiert.
    """

    log_message = Signal(str)
    run_finished = Signal(str, int)  # set_id, Anzahl erfolgreicher Services
    run_failed = Signal(str, str)    # set_id, Fehlermeldung

    def __init__(self, evaluator: ServiceSetEvaluator, symbol: str, timeframe: str,
                 set_definition: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.evaluator = evaluator
        self.symbol = symbol
        self.timeframe = timeframe
        self.set_definition = set_definition

    def run(self):
        try:
            from analytics.features.feature_builder import FeatureBuilder, prepare_plugin_df
            from analytics.features.plugins.base_plugin import PluginContext
            from state_manager import StateManager

            settings = StateManager().get_app_settings()
            fb = FeatureBuilder()
            df = fb.load_ohlcv(self.symbol, self.timeframe, limit=settings.feature_builder_limit)
            if df is None or df.empty:
                self.run_failed.emit(
                    self.set_definition.get("set_id", ""),
                    f"Keine OHLCV-Daten fuer {self.symbol} {self.timeframe}.",
                )
                return

            df_plugin = prepare_plugin_df(df)
            context = PluginContext(
                symbol=self.symbol,
                timeframe=self.timeframe,
                mode="batch",
                timestamp=int(df_plugin["time"].iloc[-1]) if len(df_plugin) else None,
                settings=settings,
            )
            display = self.set_definition.get("display_name") or self.set_definition.get("set_id") or "Unbenannt"
            self.log_message.emit(f"Ausfuehren: {display} ({self.symbol} {self.timeframe})")

            results = self.evaluator.execute_set(self.set_definition, df_plugin, context=context)
            for iid in results:
                self.log_message.emit(f"  {iid}: fertig")
            self.run_finished.emit(self.set_definition.get("set_id", ""), len(results))
        except Exception as e:
            self.run_failed.emit(self.set_definition.get("set_id", ""), str(e))


@register_persistent_window(auto_restore=False)
class ServiceWindow(PersistentWindow):
    INSTANCE_ID = "win_service"

    def __init__(self, parent=None, service_set_repo: Optional[ServiceSetRepository] = None):
        super().__init__(parent)
        self.scanner: Optional[HistoricalScanner] = None
        self._elapsed_timer = QTimer(self)
        self._elapsed_seconds = 0
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        # Phase 13 Schritt 4: Service-Set-Verwaltung
        self.set_repo: ServiceSetRepository = service_set_repo or ServiceSetRepository()
        self.set_evaluator = ServiceSetEvaluator()
        self._set_run_worker: Optional[ServiceSetRunWorker] = None
        self._current_set_id: Optional[str] = None

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

        # Phase 13 Schritt 4: Service-Set-Controls
        self.combo_set: QComboBox = self.ui.findChild(QComboBox, "combo_set")
        self.combo_tf_set: QComboBox = self.ui.findChild(QComboBox, "combo_tf_set")
        self.btn_refresh_sets: QPushButton = self.ui.findChild(QPushButton, "btn_refresh_sets")
        self.edit_set_name: QLineEdit = self.ui.findChild(QLineEdit, "edit_set_name")
        self.list_execution_order: QListWidget = self.ui.findChild(QListWidget, "list_execution_order")
        self.btn_move_up: QPushButton = self.ui.findChild(QPushButton, "btn_move_up")
        self.btn_move_down: QPushButton = self.ui.findChild(QPushButton, "btn_move_down")
        self.btn_remove_instance: QPushButton = self.ui.findChild(QPushButton, "btn_remove_instance")
        self.edit_new_instance: QLineEdit = self.ui.findChild(QLineEdit, "edit_new_instance")
        self.btn_add_instance: QPushButton = self.ui.findChild(QPushButton, "btn_add_instance")
        self.btn_save_set: QPushButton = self.ui.findChild(QPushButton, "btn_save_set")
        self.btn_delete_set: QPushButton = self.ui.findChild(QPushButton, "btn_delete_set")
        self.btn_execute_set: QPushButton = self.ui.findChild(QPushButton, "btn_execute_set")

        if self.btn_start:
            self.btn_start.clicked.connect(self.start_scan)

        # Phase 13 Schritt 4: Service-Set-Signale
        if self.combo_set:
            self.combo_set.currentIndexChanged.connect(self._on_set_selected)
        if self.btn_refresh_sets:
            self.btn_refresh_sets.clicked.connect(self.refresh_set_list)
        if self.btn_move_up:
            self.btn_move_up.clicked.connect(lambda: self.move_order_item(-1))
        if self.btn_move_down:
            self.btn_move_down.clicked.connect(lambda: self.move_order_item(1))
        if self.btn_remove_instance:
            self.btn_remove_instance.clicked.connect(self.remove_instance)
        if self.btn_add_instance:
            self.btn_add_instance.clicked.connect(self.add_instance)
            if self.edit_new_instance:
                self.edit_new_instance.returnPressed.connect(self.add_instance)
        if self.btn_save_set:
            self.btn_save_set.clicked.connect(self.save_set)
        if self.btn_delete_set:
            self.btn_delete_set.clicked.connect(self.delete_set)
        if self.btn_execute_set:
            self.btn_execute_set.clicked.connect(self.execute_set)

        # Sofort speichern bei Symbol-Änderung
        if self.combo_symbol:
            self.combo_symbol.currentTextChanged.connect(self.save_state)

        # Set-Dropdown initial befüllen (list_sets() als Quelle)
        self.refresh_set_list()

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

    # =========================================================================
    # Phase 13 Schritt 4: Service-Set-Verwaltung
    # =========================================================================

    def refresh_set_list(self) -> None:
        """Befüllt das Set-Dropdown aus ServiceSetRepository.list_sets().

        Quelle für die Set-Auswahl (Roadmap §4.2). Behält die aktuelle
        Auswahl bei, sofern sie noch existiert; andernfalls wird das erste
        Set geladen und in den Editor übertragen.
        """
        if not self.combo_set:
            return
        sets = self.set_repo.list_sets()
        current = self.combo_set.currentData()

        self.combo_set.blockSignals(True)
        self.combo_set.clear()
        for s in sets:
            label = s.get("display_name") or s.get("set_id") or "Unbenannt"
            self.combo_set.addItem(label, s.get("set_id"))
        self.combo_set.blockSignals(False)

        # Aktuelle Auswahl beibehalten, falls noch vorhanden.
        selected_id: Optional[str] = None
        if current is not None:
            idx = self.combo_set.findData(current)
            if idx >= 0:
                self.combo_set.setCurrentIndex(idx)
                selected_id = current

        if selected_id is None and sets:
            # Achtung: addItem() setzt das erste Item automatisch auf Index 0,
            # während die Signale blockiert sind -> setCurrentIndex(0) löst KEIN
            # currentIndexChanged aus. Daher explizit in den Editor laden.
            self.combo_set.setCurrentIndex(0)
            selected_id = self.combo_set.itemData(0)

        if selected_id:
            definition = self.set_repo.get_set(selected_id)
            if definition:
                self.load_set_into_editor(definition)
        else:
            # Kein Set (mehr) vorhanden -> Editor leeren
            self._clear_set_editor()

    def _clear_set_editor(self) -> None:
        """Leert Name-Feld und execution_order-Liste des Set-Editors."""
        self._current_set_id = None
        if self.edit_set_name:
            self.edit_set_name.clear()
        if self.list_execution_order:
            self.list_execution_order.clear()

    @Slot(int)
    def _on_set_selected(self, index: int) -> None:
        """Lädt das im Dropdown gewählte Set in den Editor."""
        if index < 0 or not self.combo_set:
            return
        set_id = self.combo_set.itemData(index)
        if not set_id:
            return
        definition = self.set_repo.get_set(set_id)
        if definition:
            self.load_set_into_editor(definition)
            self.log(f"Set geladen: {set_id}")

    def load_set_into_editor(self, definition: Dict[str, Any]) -> None:
        """Überträgt eine ServiceSetDefinition in Name-Feld + execution_order-Liste."""
        self._current_set_id = definition.get("set_id")
        if self.edit_set_name:
            self.edit_set_name.setText(definition.get("display_name") or "")
        if self.list_execution_order:
            self.list_execution_order.clear()
            services = definition.get("services") or {}
            for iid in (definition.get("execution_order") or []):
                cfg = services.get(iid, {})
                plugin_id = cfg.get("plugin_id", "?")
                item = QListWidgetItem(f"{iid}  [{plugin_id}]")
                item.setData(Qt.UserRole, iid)
                item.setData(Qt.UserRole + 1, plugin_id)
                self.list_execution_order.addItem(item)

    def collect_current_order(self) -> list:
        """Liefert die instance_ids aus der Liste (aktuelle execution_order)."""
        if not self.list_execution_order:
            return []
        return [
            self.list_execution_order.item(i).data(Qt.UserRole)
            for i in range(self.list_execution_order.count())
        ]

    @Slot()
    def move_order_item(self, delta: int) -> None:
        """Verschiebt das markierte Listenelement um delta (-1 = hoch, +1 = runter)."""
        lw = self.list_execution_order
        if not lw:
            return
        row = lw.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= lw.count():
            return
        item = lw.takeItem(row)
        lw.insertItem(new_row, item)
        lw.setCurrentRow(new_row)

    @Slot()
    def remove_instance(self) -> None:
        """Entfernt den markierten Service aus der Ausführungs-Reihenfolge."""
        lw = self.list_execution_order
        if not lw or lw.currentRow() < 0:
            return
        lw.takeItem(lw.currentRow())

    @Slot()
    def add_instance(self) -> None:
        """Fügt eine Service-Instanz 'instance_id [plugin_id]' zur Liste hinzu.

        Plugin muss in der PluginRegistry existieren (Default-Params werden
        beim Speichern eines neuen Sets verwendet). Duplikate werden abgelehnt.
        """
        if not self.edit_new_instance or not self.list_execution_order:
            return
        text = self.edit_new_instance.text().strip()
        if not text:
            return
        # Formate: "instance_id [plugin_id]", "instance_id:plugin_id" oder "instance_id"
        import re
        m = re.match(r"^([\w\-]+)\s*[\[:]\s*([\w\-]+)\s*\]?$", text)
        if m:
            iid, plugin_id = m.group(1), m.group(2)
        else:
            iid = text
            plugin_id = text

        try:
            from analytics.features.feature_builder import PluginRegistry
            PluginRegistry().get(plugin_id)
        except KeyError:
            self.log(f"Plugin '{plugin_id}' nicht gefunden (verfügbar: grid_liquidity).")
            return

        for i in range(self.list_execution_order.count()):
            if self.list_execution_order.item(i).data(Qt.UserRole) == iid:
                self.log(f"instance_id '{iid}' existiert bereits.")
                return

        item = QListWidgetItem(f"{iid}  [{plugin_id}]")
        item.setData(Qt.UserRole, iid)
        item.setData(Qt.UserRole + 1, plugin_id)
        self.list_execution_order.addItem(item)
        self.edit_new_instance.clear()
        self.log(f"Service hinzugefügt: {iid} [{plugin_id}]")

    def collect_set_definition(self) -> Dict[str, Any]:
        """Baut aus dem Editor eine ServiceSetDefinition.

        Für ein geladenes Set werden die services aus der DB übernommen.
        Für ein NEUES Set werden die services aus den Listeneinträgen
        aufgebaut (plugin_id + Default-Params aus der Registry).
        """
        order = self.collect_current_order()
        services: Dict[str, Any] = {}
        if self._current_set_id:
            existing = self.set_repo.get_set(self._current_set_id) or {}
            services = dict(existing.get("services") or {})

        if not services:
            from analytics.features.feature_builder import PluginRegistry
            registry = PluginRegistry()
            if self.list_execution_order:
                for i in range(self.list_execution_order.count()):
                    item = self.list_execution_order.item(i)
                    iid = item.data(Qt.UserRole)
                    plugin_id = item.data(Qt.UserRole + 1)
                    if not iid or not plugin_id:
                        continue
                    try:
                        plugin = registry.get(plugin_id)
                        cfg: Dict[str, Any] = {
                            "plugin_id": plugin_id,
                            "lookback": 1000,
                            "params": dict(plugin.default_params),
                        }
                    except KeyError:
                        cfg = {"plugin_id": plugin_id, "lookback": 1000, "params": {}}
                    services[iid] = cfg

        return {
            "set_id": self._current_set_id or "",
            "display_name": self.edit_set_name.text().strip() if self.edit_set_name else "",
            "execution_order": order,
            "services": services,
        }

    @Slot()
    def save_set(self) -> None:
        """Speichert das aktive Set über ServiceSetRepository.save_set().

        Leerer Name → automatischer Name aus den instance_ids (z.B. 'grid_1 + prox_1').
        """
        definition = self.collect_set_definition()
        if not definition.get("execution_order"):
            self.log("Keine Services in der Ausführungs-Reihenfolge – Speichern abgebrochen.")
            return
        if not definition.get("services"):
            self.log("WARNUNG: Set hat keine services-Konfiguration (nur Reihenfolge wird gespeichert).")

        set_id = self.set_repo.save_set(definition)
        self._current_set_id = set_id
        self.log(f"Set gespeichert: {set_id}")
        self.refresh_set_list()
        if self.combo_set:
            idx = self.combo_set.findData(set_id)
            if idx >= 0:
                self.combo_set.setCurrentIndex(idx)

    @Slot()
    def delete_set(self) -> None:
        """Löscht das gewählte Set – mit zwingender QMessageBox-Rückfrage."""
        if not self.combo_set:
            return
        set_id = self.combo_set.currentData()
        if not set_id:
            self.log("Kein Set zum Löschen ausgewählt.")
            return
        name = self.combo_set.currentText()

        ret = QMessageBox.warning(
            self,
            "Set löschen",
            f"Service-Set '{name}' wirklich löschen?\n"
            f"Dies kann nicht rückgängig gemacht werden.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ret != QMessageBox.Yes:
            self.log("Löschen abgebrochen.")
            return

        if self.set_repo.delete_set(set_id):
            self.log(f"Set gelöscht: {set_id}")
        else:
            self.log(f"Set '{set_id}' nicht gefunden.")

        self._clear_set_editor()
        self.refresh_set_list()

    @Slot()
    def execute_set(self) -> None:
        """Startet den ServiceSetEvaluator für das aktive Set (Hintergrund-Thread)."""
        definition = self.collect_set_definition()
        if not definition.get("execution_order"):
            self.log("Keine Services in der Ausführungs-Reihenfolge.")
            return
        if not definition.get("services"):
            self.log("Set hat keine services-Konfiguration – Ausführung nicht möglich.")
            return
        if self._set_run_worker and self._set_run_worker.isRunning():
            self.log("Set-Ausführung läuft bereits.")
            return

        symbol = self.combo_symbol.currentText() if self.combo_symbol else "SILVER"
        timeframe = self.combo_tf_set.currentText() if self.combo_tf_set else "H1"

        if self.btn_execute_set:
            self.btn_execute_set.setEnabled(False)
        self._set_run_worker = ServiceSetRunWorker(
            self.set_evaluator, symbol, timeframe, definition, parent=self,
        )
        self._set_run_worker.log_message.connect(self.log)
        self._set_run_worker.run_finished.connect(self._on_set_run_finished)
        self._set_run_worker.run_failed.connect(self._on_set_run_failed)
        self._set_run_worker.start()

    @Slot(str, int)
    def _on_set_run_finished(self, set_id: str, count: int) -> None:
        if self.btn_execute_set:
            self.btn_execute_set.setEnabled(True)
        self.log(f"Set-Ausführung abgeschlossen: {count} Services.")

    @Slot(str, str)
    def _on_set_run_failed(self, set_id: str, error: str) -> None:
        if self.btn_execute_set:
            self.btn_execute_set.setEnabled(True)
        self.log(f"FEHLER bei Set-Ausführung: {error}")

    def closeEvent(self, event):
        # PersistentWindow.save_state() wird in super().closeEvent gerufen
        if self.scanner and self.scanner.isRunning():
            self.scanner.stop()
            self.scanner.wait(2000)
        if self._set_run_worker and self._set_run_worker.isRunning():
            self._set_run_worker.wait(2000)
        self._elapsed_timer.stop()
        super().closeEvent(event)
