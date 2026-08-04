# config/event_bus.py
"""
config/event_bus.py - Zentraler Signal-Hub (EventBus-Singleton) fuer die
schwellenfreie Entkopplung der Fenster (Phase 15, Invariante 5).

Fenster kommunizieren NIE direkt miteinander (keine zirkulaeren
Abhaengigkeiten, kein Hardcoding von Fensterklassen). Stattdessen emittieren
sie Events auf dem zentralen EventBus und andere Fenster/Module abonnieren
diese Signale.

Phase 15.01: `favorites_changed` wird vom SymbolsWindow nach jedem
Favoriten-Toggle emittiert; ServiceWindow (und spaeter AnalyticsWindow)
befuellen daraufhin ihre Symbol-Dropdowns neu.

Verwendungsbeispiel:
    from config.event_bus import event_bus
    event_bus.favorites_changed.connect(self._refresh_symbol_combo)
    event_bus.favorites_changed.emit()
"""

from typing import ClassVar, Optional

from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    """Zentraler Signal-Hub (Singleton) fuer fensteruebergreifende Events.

    Signaldefinitionen (minimal gehalten, Phase-15-Entscheidungs-Protokoll):
    - favorites_changed : Favoriten-Liste wurde geaendert (SymbolsWindow).
    - profile_changed   : Analytics-Profil wurde geaendert (15.03, Payload =
                          Profil-Name/-ID).
    - service_set_changed: Service-Set wurde gespeichert/geloescht (15.02).
    """

    favorites_changed = Signal()
    profile_changed = Signal(str)
    service_set_changed = Signal()

    _instance: ClassVar[Optional["EventBus"]] = None

    def __init__(self) -> None:
        # QObject ohne Parent: Der Singleton lebt app-weit und wird nie
        # geloescht (gehoert keiner Fenster-Hierarchie an).
        super().__init__(None)

    @classmethod
    def instance(cls) -> "EventBus":
        """Liefert die app-weite Singleton-Instanz (lazy)."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# Bequeme Modul-Level-Instanz: `from config.event_bus import event_bus`
event_bus = EventBus.instance()
