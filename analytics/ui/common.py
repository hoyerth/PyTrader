# analytics/ui/common.py
"""
Gemeinsame UI-Helfer der Analytics-Pages (analytics/ui/*, Phase 15.03).

- format_wanduhr_time(): Wanduhr-Formatierung (Invariante 7, KEIN Offset)
- make_overlay_stack(): 'Keine Daten'-Overlay (QStackedLayout) fuer die
  Seiten mit Progress-Spinner-/No-Data-Semantik (15.03-Spezifikation).
"""

from datetime import datetime, timezone
from typing import Any, List

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QStackedLayout,
    QWidget,
)

# Ausgabeformat der Wanduhr-Zeit (z. B. '03.08.2026 12:00').
WANDUHR_FORMAT = "%d.%m.%Y %H:%M"


def format_wanduhr_time(epoch: Any) -> str:
    """Formatiert eine Wanduhr-encoded Epoch DIREKT als Berliner Wanduhrzeit.

    Invariante 7: Die gespeicherten Epochs sind Wanduhr-encoded (MT5 liefert
    Berlin-Wanduhr-Epochs; die UTC-Darstellung IST die Wanduhr-Zeit). Daher
    formatiert `fromtimestamp(epoch, tz=utc)` OHNE weiteren Berlin-Offset
    korrekt und ist automatisch DST-robust (CEST/CET sind bereits in den
    Roh-Epochs enthalten). Ein zusaetzlicher +2h/+1h-Offset waere falsch.
    """
    try:
        dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
    return dt.strftime(WANDUHR_FORMAT)


def make_overlay_stack(
    content: QWidget, message: str = "Keine Daten vorhanden."
) -> QStackedLayout:
    """Stapelt einen zentrierten 'Keine Daten'-Hinweis ueber den Inhalt.

    Index 0 = Inhalt, Index 1 = Overlay. Die Seiten schalten per
    `stack.setCurrentIndex(0 | 1)` um (No-Data-Overlay, 15.03-Spez).
    """
    stack = QStackedLayout()
    overlay = QLabel(message)
    overlay.setAlignment(Qt.AlignCenter)
    overlay.setStyleSheet("color: #808080; font-size: 14px;")
    stack.addWidget(content)
    stack.addWidget(overlay)
    stack.setCurrentWidget(content)
    return stack


class CheckableComboBox(QComboBox):
    """QComboBox mit Checkbox-Items und offen bleibendem Pop-up (20.03.02).

    Mehrfach-Auswahl ueber `QStandardItem` (`Qt.ItemIsUserCheckable`),
    Formatierung `{Service-Name} / {Parameter}` durch den Aufrufer
    (Display-Text). Das Pop-up bleibt beim Anklicken einer Checkbox geoeffnet
    (Klick im Viewport unterdrueckt `hidePopup()`), schliesst aber normal bei
    Aussenklick / Escape / Fokusverlust.

    API:
      * `add_checkable_item(display_text, user_data, checked=False)`
      * `checked_data() -> List[str]`  – user_data der angehakten Items
      * Signal `selection_changed(list)` – bei jedem CheckState-Wechsel
        (blockierbar ueber `blockSignals(True)`, Muster heatmap_widget).

    Headless instanziierbar: Der Konstruktor startet KEINEN Event-Loop
    (kein exec_()).
    """

    #: Wird bei jedem CheckState-Wechsel mit der Liste der angehakten
    #: `user_data`-Werte emittiert (in Item-Reihenfolge).
    selection_changed = Signal(list)

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._popup_click = False
        # 20.03.03 (Q5): Zuletzt vom Nutzer geklicktes Item (Row-Index) –
        # Grundlage der XOR-Reconciliation im HeatmapWidget (Sammel- vs.
        # Einzel-Eintrag desselben Keys). -1 = kein Klick (programmatisch).
        self._last_click_index = -1
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.setPlaceholderText("Felder wählen…")
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        # Pop-up offen halten: Mausklick auf den Viewport setzt das Flag,
        # `hidePopup()` unterdrueckt das Schliessen dann einmalig.
        self.view().viewport().installEventFilter(self)
        self._model.itemChanged.connect(self._on_item_changed)

    # ------------------------------------------------------------------
    # Pop-up-Steuerung (offen bei Checkbox-Klick)
    # ------------------------------------------------------------------
    def hidePopup(self) -> None:
        """Unterdrueckt das Schliessen bei Klicks in den Viewport (20.03.02).

        Alle anderen Schliess-Gruende (Aussenklick, Escape, Fokusverlust)
        verhalten sich wie beim Standard-QComboBox.
        """
        if self._popup_click:
            self._popup_click = False
            return
        super().hidePopup()

    def eventFilter(self, obj, event) -> bool:
        """Setzt das Popup-Flag bei Mausklicks auf den Popup-Viewport und
        merkt sich den zuletzt geklickten Item-Index (20.03.03, Q5)."""
        if (obj is self.view().viewport()
                and event.type() == QEvent.MouseButtonRelease):
            self._popup_click = True
            self._last_click_index = self.view().indexAt(event.pos()).row()
        return super().eventFilter(obj, event)

    def last_click_index(self) -> int:
        """Row-Index des zuletzt geklickten Items (Q5, XOR-Aufloesung).

        -1, wenn der letzte CheckState-Wechsel programmatisch erfolgte
        (kein Klick) – dann findet keine XOR-Aufloesung statt.
        """
        return self._last_click_index

    # ------------------------------------------------------------------
    # Befuellung / Auslesen
    # ------------------------------------------------------------------
    def add_checkable_item(
        self, display_text: str, user_data: Any, checked: bool = False
    ) -> None:
        """Fuegt ein Checkbox-Item hinzu (display_text, user_data)."""
        item = QStandardItem(str(display_text))
        item.setData(user_data, Qt.UserRole)
        item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._model.appendRow(item)

    def add_disabled_item(self, display_text: str) -> None:
        """Fuegt einen deaktivierten, grauen Hinweis-Eintrag hinzu (Q8-Fix).

        (No Data)-Unterstuetzung: Neue Varianten ohne feature_store-Daten
        werden als nicht-waehlbare, graue Eintraege im 'Feld'-Dropdown
        angezeigt ('{Service} ({Preset}) – (No Data)'), bis der erste
        Scan/LiveRun sie berechnet hat. Anders als `add_header_item` ist
        der Eintrag NICHT fett und traegt userData=None (kein
        selection_changed-Beitrag, nicht in checked_data()).
        """
        item = QStandardItem(str(display_text))
        item.setData(None, Qt.UserRole)
        item.setFlags(Qt.NoItemFlags)
        item.setEnabled(False)
        item.setForeground(QBrush(QColor(160, 160, 160)))  # hellgrau
        self._model.appendRow(item)

    def add_header_item(self, display_text: str) -> None:
        """Fuegt eine deaktivierte, nicht-auswaehlbare Trenn-/Kopfzeile hinzu
        (20.03.03, Q4).

        Header tragen `Qt.NoItemFlags` + `userData=None` und erscheinen daher
        weder als auswaehlbares Item noch in `checked_data()`.
        """
        item = QStandardItem(str(display_text))
        item.setData(None, Qt.UserRole)
        item.setFlags(Qt.NoItemFlags)          # nicht aktiv, nicht checkbar
        item.setEnabled(False)
        item.setForeground(QBrush(QColor(128, 128, 128)))  # grau
        f = item.font()
        f.setBold(True)
        item.setFont(f)
        self._model.appendRow(item)

    def checked_data(self) -> List[str]:
        """Liefert die `user_data`-Werte aller angehakten Items."""
        out: List[str] = []
        for i in range(self._model.rowCount()):
            item = self._model.item(i)
            if item is not None and item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out

    def set_checked_data(self, checked_values: List[str]) -> None:
        """Setzt die CheckStates anhand einer Liste von user_data-Werten.

        Items mit einem Wert aus `checked_values` werden angehakt, alle
        anderen abgewaehlt (blockiert, kein selection_changed-Emit).
        """
        wanted = {str(v) for v in (checked_values or [])}
        self.blockSignals(True)
        try:
            for i in range(self._model.rowCount()):
                item = self._model.item(i)
                if item is None:
                    continue
                on = str(item.data(Qt.UserRole) or "") in wanted
                item.setCheckState(Qt.Checked if on else Qt.Unchecked)
            self._update_line_text()
        finally:
            self.blockSignals(False)

    def _on_item_changed(self, item) -> None:
        """CheckState-Wechsel -> LineEdit-Text aktualisieren + Signal."""
        if item is None or not (item.flags() & Qt.ItemIsUserCheckable):
            return
        self._update_line_text()
        self.selection_changed.emit(self.checked_data())

    def _update_line_text(self) -> None:
        """Kompakte Zusammenfassung im (read-only) LineEdit."""
        labels = [
            self._model.item(i).text()
            for i in range(self._model.rowCount())
            if self._model.item(i) is not None
            and self._model.item(i).checkState() == Qt.Checked
        ]
        if not labels:
            self.lineEdit().setText("")
        elif len(labels) == 1:
            self.lineEdit().setText(labels[0])
        else:
            self.lineEdit().setText(f"{len(labels)} Felder gewählt")
