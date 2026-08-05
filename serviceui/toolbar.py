# serviceui/toolbar.py
"""
Service-UI: Aktions-Toolbar (Phase 15 15.02, bifunktional 05.08.2026).

Entkoppelte Button-Leiste fuer Struktur-Aktionen des Service-Fensters
(Modus B / FULL_EDIT des ServiceSelectorWidget):

  * [➕ Set] / [➕ Service] / [➕] – bifunktionaler Hinzufuegen-Button. Der
    Orchestrator schaltet den Modus ueber `set_add_mode()`:
      "set"     -> Text '[➕ Set]'     -> emittiert `add_set_requested`
                   (neues leeres Service-Set anlegen)
      "service" -> Text '[➕ Service]' -> oeffnet das Plugin-Popup
                   (`request_add_popup`, emittiert `add_service_requested`)
      "none"    -> Text '[➕]', deaktiviert
  * [Order ▲] / [Order ▼] – Aenderung der execution_order im aktiven Set.
    Nur aktiv, wenn ein Service innerhalb eines Sets gewaehlt ist
    (`set_order_enabled()`).
  * [🗑️ Set löschen] / [➖ Service entfernen] / [🗑️] – bifunktionaler
    Entfernen-Button. Der Orchestrator schaltet den Modus ueber
    `set_remove_mode()` und emittiert `remove_requested` (der Orchestrator
    fuehrt die P14-04-Sperrpruefung aus und entscheidet, ob das Set oder der
    Service entfernt wird).

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
    #: Emittiert im Modus 'set' des bifunktionalen Hinzufuegen-Buttons
    #: (neues leeres Service-Set anlegen – Orchestrator fuehrt die Aktion aus).
    add_set_requested = Signal()
    #: Ausfuehrungs-Reihenfolge: um -1 (hoch) bzw. +1 (runter) verschieben
    move_up_requested = Signal()
    move_down_requested = Signal()
    #: Markierten Service / das markierte Set entfernen (Orchestrator fuehrt
    #: die P14-04-Sperrpruefung aus und entscheidet ueber Set vs. Service).
    remove_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._menu: Optional[QMenu] = None
        #: Modus des bifunktionalen Hinzufuegen-Buttons ("set"/"service"/"none")
        self._add_mode: str = "none"

        self.btn_add = QPushButton("➕")
        self.btn_add.setToolTip(
            "Hinzufuegen – abhaengig von der Auswahl: neues Set oder Service.")
        self.btn_move_up = QPushButton("Order ▲")
        self.btn_move_up.setToolTip("Service in der Reihenfolge nach oben verschieben.")
        self.btn_move_down = QPushButton("Order ▼")
        self.btn_move_down.setToolTip("Service in der Reihenfolge nach unten verschieben.")
        self.btn_remove = QPushButton("🗑️")
        self.btn_remove.setToolTip(
            "Entfernen – abhaengig von der Auswahl: Set (Papierkorb) oder "
            "Service (P14-04-Sperrpruefung).")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.btn_add)
        lay.addWidget(self.btn_move_up)
        lay.addWidget(self.btn_move_down)
        lay.addWidget(self.btn_remove)
        lay.addStretch(1)

        self.btn_add.clicked.connect(self._on_add_clicked)
        self.btn_move_up.clicked.connect(self.move_up_requested)
        self.btn_move_down.clicked.connect(self.move_down_requested)
        self.btn_remove.clicked.connect(self.remove_requested)

        # Bifunktional: ohne Auswahl sind alle Struktur-Buttons deaktiviert
        self.set_add_mode("none")
        self.set_remove_mode("none")
        self.set_order_enabled(False)

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
        """[➕]-Button geklickt – der bifunktionale Modus entscheidet:

        * "set"     -> neues leeres Service-Set (add_set_requested)
        * "service" -> Plugin-Popup (request_add_popup, vom Orchestrator
                       befuellt; ohne Plugin-Liste passiert nichts)
        * "none"    -> Button ist deaktiviert (kein Signal)
        """
        mode = getattr(self, "_add_mode", "none")
        if mode == "set":
            self.add_set_requested.emit()
        elif mode == "service":
            if hasattr(self, "request_add_popup") and callable(self.request_add_popup):
                self.request_add_popup()

    # -------------------------------------------------------------------------
    # Bifunktionale Aktions-Zustaende (Orchestrator steuert Modus + Aktivierung)
    # -------------------------------------------------------------------------

    def set_add_mode(self, mode: str) -> None:
        """Schaltet den bifunktionalen [➕]-Button (Text + Funktion).

        Args:
            mode: "set"     -> '[➕ Set]'    (neues leeres Set anlegen)
                  "service" -> '[➕ Service]' (Plugin zum aktiven Set hinzufuegen)
                  "none"    -> '[➕]' deaktiviert
        """
        self._add_mode = mode
        if mode == "set":
            self.btn_add.setText("➕ Set")
            self.btn_add.setEnabled(True)
            self.btn_add.setToolTip("Neues leeres Service-Set anlegen.")
        elif mode == "service":
            self.btn_add.setText("➕ Service")
            self.btn_add.setEnabled(True)
            self.btn_add.setToolTip(
                "Service zum aktiven Set hinzufuegen – waehlt das Plugin aus "
                "einem Popup.")
        else:
            self.btn_add.setText("➕")
            self.btn_add.setEnabled(False)
            self.btn_add.setToolTip(
                "Keine gueltige Auswahl – bitte ein Set oder einen Service "
                "im Baum markieren.")

    def set_remove_mode(self, mode: str) -> None:
        """Schaltet den bifunktionalen [🗑️]-Button (Text + Funktion).

        Args:
            mode: "set"     -> '[🗑️ Set löschen]' (Papierkorb / Soft-Delete)
                  "service" -> '[➖ Service entfernen]' (P14-04-Sperrpruefung)
                  "none"    -> '[🗑️]' deaktiviert
        """
        if mode == "set":
            self.btn_remove.setText("🗑️ Set löschen")
            self.btn_remove.setEnabled(True)
            self.btn_remove.setToolTip(
                "Markiertes Service-Set in den Papierkorb verschieben (P14-05).")
        elif mode == "service":
            self.btn_remove.setText("➖ Service entfernen")
            self.btn_remove.setEnabled(True)
            self.btn_remove.setToolTip(
                "Markierten Service aus dem Set entfernen (P14-04-Sperrpruefung).")
        else:
            self.btn_remove.setText("🗑️")
            self.btn_remove.setEnabled(False)
            self.btn_remove.setToolTip(
                "Keine gueltige Auswahl – bitte ein Set oder einen Service "
                "im Baum markieren.")

    def set_order_enabled(self, enabled: bool) -> None:
        """Aktiviert/deaktiviert die [Order ▲]/[Order ▼]-Buttons.

        Nur aktiv, wenn ein Service INNERHALB eines Sets gewaehlt ist
        (sonst gibt es keine execution_order zu schalten).
        """
        self.btn_move_up.setEnabled(enabled)
        self.btn_move_down.setEnabled(enabled)
