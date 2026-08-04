# serviceui/toolbar.py
"""
Service-UI: Aktions-Toolbar (Phase 15 15.02).

Entkoppelte Button-Leiste fuer Struktur-Aktionen des Service-Fensters
(Modus B / FULL_EDIT des ServiceSelectorWidget):

  * [➕ Service]   – oeffnet ein Popup-Menue mit allen verfuegbaren Plugins
                     (Auswahl emittiert `add_service_requested(plugin_id)`).
  * [▲] / [▼]      – Aenderung der execution_order im aktiven Set.
  * [🗑️ Entfernen] – Entfernen des markierten Services (P14-04-Sperrpruefung
                     fuehrt der Orchestrator durch).
  * [🔄 Plugins]   – Hot-Reload der Custom-Plugins (P14-02).

Die Toolbar emittiert NUR Signale – sie kennt weder das Repository noch die
Datenbank (Invariante 4: kein SQL in UI; SRP: eine Aufgabe pro Klasse).
"""

from typing import List, Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QMenu, QPushButton, QWidget,
)


class ServiceToolbar(QWidget):
    """Aktions-Buttons der Service-Verwaltung (schwellenfrei entkoppelt)."""

    #: Emittiert mit der plugin_id, wenn im [➕ Service]-Popup ein Plugin gewaehlt wird
    add_service_requested = Signal(str)
    #: Ausfuehrungs-Reihenfolge: um -1 (hoch) bzw. +1 (runter) verschieben
    move_up_requested = Signal()
    move_down_requested = Signal()
    #: Markierten Service entfernen (Orchestrator fuehrt P14-04-Sperrpruefung aus)
    remove_requested = Signal()
    #: Plugins neu laden (P14-02 Hot-Reload)
    reload_plugins_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._menu: Optional[QMenu] = None

        self.btn_add = QPushButton("➕ Service")
        self.btn_add.setToolTip(
            "Service zum aktiven Set hinzufuegen – waehlt das Plugin aus einem Popup.")
        self.btn_move_up = QPushButton("▲")
        self.btn_move_up.setToolTip("Service in der Reihenfolge nach oben verschieben.")
        self.btn_move_down = QPushButton("▼")
        self.btn_move_down.setToolTip("Service in der Reihenfolge nach unten verschieben.")
        self.btn_remove = QPushButton("🗑️ Entfernen")
        self.btn_remove.setToolTip(
            "Markierten Service aus dem Set entfernen (P14-04-Sperrpruefung).")
        self.btn_reload = QPushButton("🔄 Plugins")
        self.btn_reload.setToolTip(
            "P14-02: Custom-Plugins aus data/custom_plugins/ neu laden (Hot-Reload).")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.btn_add)
        lay.addWidget(self.btn_move_up)
        lay.addWidget(self.btn_move_down)
        lay.addWidget(self.btn_remove)
        lay.addStretch(1)
        lay.addWidget(self.btn_reload)

        self.btn_add.clicked.connect(self._on_add_clicked)
        self.btn_move_up.clicked.connect(self.move_up_requested)
        self.btn_move_down.clicked.connect(self.move_down_requested)
        self.btn_remove.clicked.connect(self.remove_requested)
        self.btn_reload.clicked.connect(self.reload_plugins_requested)

    # -------------------------------------------------------------------------
    # Popup-Auswahl der Plugins ([➕ Service])
    # -------------------------------------------------------------------------

    def show_add_menu(self, plugin_ids: List[str],
                      anchor: Optional[QWidget] = None) -> None:
        """Zeigt das Popup-Menue mit den verfuegbaren Plugins.

        Args:
            plugin_ids: sortierte Liste der Plugin-IDs (aus dem Modell).
            anchor:     Widget, an dem das Menue ausgerichtet wird (Default:
                        der [➕ Service]-Button).
        """
        self._menu = QMenu(self)
        if not plugin_ids:
            self._menu.addAction("(keine Plugins verfuegbar)").setEnabled(False)
        else:
            for pid in plugin_ids:
                action = self._menu.addAction(pid)
                action.setData(pid)
        target = anchor or self.btn_add
        chosen = self._menu.exec(
            target.mapToGlobal(QPoint(0, target.height())))
        if chosen is not None and chosen.data():
            self.add_service_requested.emit(str(chosen.data()))

    def _on_add_clicked(self) -> None:
        """[➕ Service] geklickt – das Popup wird vom Orchestrator befuellt
        (er kennt das Modell/die Registry). Ohne Plugin-Liste passiert nichts."""
        if hasattr(self, "request_add_popup") and callable(self.request_add_popup):
            self.request_add_popup()

    # -------------------------------------------------------------------------
    # Aktions-Zustaende (Orchestrator steuert die Aktivierung)
    # -------------------------------------------------------------------------

    def set_actions_enabled(self, enabled: bool) -> None:
        """Aktiviert/deaktiviert Struktur-Buttons (z.B. bei laufender Set-
        Ausfuehrung oder leerem Set)."""
        for btn in (self.btn_add, self.btn_move_up, self.btn_move_down,
                    self.btn_remove):
            btn.setEnabled(enabled)
