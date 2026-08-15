# ui/window_manager.py
"""
ui/window_manager.py - Zentraler Fenster-Lifecycle-Manager (18.01.02, E5).

Kapselt die Sub-/Chart-Fenster-Verwaltung des MainWindow (Single Responsibility
Principle, Inversion of Control):

  * Wiederherstellung aller gespeicherten Fenster (restore_all_windows)
  * Oeffnen/Fokussieren von Chart-, Service-, Analytics- und Properties-Fenstern
  * Jump-to-Bar (open_chart_at_bar)
  * Ermittlung der aktuell aktiven Symbol/Timeframe-Paare (LiveTickWorker-Callback)

Der WindowManager kennt MainWindow NICHT (kein Import von main.py). Die
Kopplung erfolgt ueber Konstruktor-Parameter (parent + state_manager +
Listen-Referenzen). `restore_main_window_geometry` und die Tick-Verteilung
bleiben im MainWindow (E5).
"""

from typing import Any, Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QApplication

from analytics.ui.analytics_win import AnalyticsWindow
from chart.chart_win import PyTraderChartWindow
from persistent_win import PersistentWindow
from ui.properties_win import PropertiesWindow
from serviceui.service_win import ServiceWindow
from state_manager import StateManager


class WindowManager:
    """Verwaltet alle Sub-/Chart-Fenster des MainWindow (Fenster-Lifecycle)."""

    def __init__(self, parent, state_manager: StateManager,
                 chart_windows: List[PyTraderChartWindow],
                 persistent_sub_windows: List[PersistentWindow]) -> None:
        """Erstellt den Fenster-Manager.

        Args:
            parent: Qt-Parent fuer neu erzeugte Fenster (duck-typed, z. B. das
                    MainWindow – wird NIE importiert, E5/IoC).
            state_manager: StateManager – Persistenz (Instanzen, Geometrien).
            chart_windows: Referenz auf die Chart-Fenster-Liste des Aufrufers
                           (gemeinsames List-Objekt, in-place-Mutationen).
            persistent_sub_windows: Referenz auf die PersistentWindow-Liste
                           des Aufrufers (gemeinsames List-Objekt).
        """
        self._parent = parent
        self.state_manager = state_manager
        self.chart_windows = chart_windows
        self.persistent_sub_windows = persistent_sub_windows

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
                win = window_cls(parent=self._parent)
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
        if getattr(app, '_is_quitting', False):
            return
        # In-place-Filter (gemeinsames List-Objekt mit dem Aufrufer, E5)
        self.chart_windows[:] = [w for w in self.chart_windows if w.instance_id != instance_id]

    def open_service_window(self) -> None:
        # Singleton: Bestehendes Fenster in den Vordergrund holen
        existing = ServiceWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = ServiceWindow(self._parent)  # parent nur für state_manager-Zugriff
        self.persistent_sub_windows.append(win)
        win.show()

    def open_analytics_window(self) -> None:
        # Phase 15 15.03: Statistik-Fenster durch AnalyticsWindow ersetzt
        # (win_statistics-Persistenz wird per E-2 nach win_analytics migriert).
        # Singleton: Bestehendes Fenster in den Vordergrund holen
        existing = AnalyticsWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = AnalyticsWindow(self._parent)  # parent nur für state_manager-Zugriff
        self.persistent_sub_windows.append(win)
        win.show()

    def open_properties_window(self) -> None:
        # Singleton: Bestehendes Fenster in den Vordergrund holen
        existing = PropertiesWindow.get_existing_instance()
        if existing is not None:
            existing.raise_()
            existing.activateWindow()
            return
        win = PropertiesWindow(self._parent)
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
        active_pairs: Set[Tuple[str, str]] = set()
        for win in list(self.chart_windows):
            try:
                if win.isVisible():
                    active_pairs.add((win.current_symbol, win.current_tf))
            except (RuntimeError, AttributeError):
                pass
        return active_pairs
