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
        # Nur prüfen, ob Qt.Window gesetzt ist (sollte immer der Fall sein)
        if not (self.windowFlags() & Qt.Window):
            self.setWindowFlags(self.windowFlags() | Qt.Window)

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
        # was Taskleisten-Eintrag unterdrückt und Fenster über Parent hält)
        self._fix_window_flags()

        # Geometrie
        geom = self._state_manager.get_window_geometry(inst_id)
        if geom:
            pos_x = geom.get("pos_x")
            pos_y = geom.get("pos_y")
            width = geom.get("width") or self.width()
            height = geom.get("height") or self.height()

            screen_geo = QApplication.primaryScreen().availableGeometry()
            if pos_x is not None and pos_y is not None:
                if pos_x < screen_geo.x() - 100 or pos_x > screen_geo.right() or \
                   pos_y < screen_geo.y() - 100 or pos_y > screen_geo.bottom():
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
        """
        self.save_state()

        # DB-Eintrag nur loeschen, wenn die App NICHT insgesamt beendet wird
        app = QApplication.instance()
        is_quitting = getattr(app, '_is_quitting', False) if app else False
        if not is_quitting:
            inst_id = self.get_instance_id()
            if inst_id:
                try:
                    self._state_manager.delete_instance(inst_id)
                except Exception:
                    pass

        _open_windows.discard(self)
        super().closeEvent(event)
