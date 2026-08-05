# serviceui/trash_dialog.py
"""
Service-UI: Papierkorb-Dialog für Service-Sets (Soft-Delete).

Phase 15, Kapitel 15.1 (U15-D1): Aus service_win.py ausgelagert –
Verhalten unverändert (inkl. doppelter Sicherheitsnachfrage, P14-05).

Der Dialog ist eine reine UI-Komponente: Er spricht ausschließlich die
Repository-API an (keine direkten SQL-Zugriffe) und protokolliert jede
Aktion über eine Log-Callback. Das endgültige Löschen/Bereinigen erfolgt
IMMER mit doppelter Sicherheitsnachfrage (User-Vorgabe P14-05).
"""

from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from analytics.engine.service_set_repository import ServiceSetRepository
from config.event_bus import event_bus

#: Deutsche Wochenkürzel (Index = datetime.weekday(), 0=Montag) für das
#: Datumsformat 'E. DD.MM.JJ HH:MM' (z.B. 'Mo. 04.07.26 14:34').
_GERMAN_WEEKDAYS = ["Mo.", "Di.", "Mi.", "Do.", "Fr.", "Sa.", "So."]


def _format_deleted_at(value: object) -> str:
    """Formatiert den deleted_at-Zeitstempel als 'E. DD.MM.JJ HH:MM'.

    DuckDB liefert TIMESTAMP als datetime-Objekt; alternativ werden
    ISO-Strings (mit/ohne Z) akzeptiert. Nicht parsebare Werte werden als
    Rohwert zurueckgegeben, fehlende Werte als leerer String (defensiv).
    """
    if isinstance(value, datetime):
        dt = value
    elif value:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return str(value)
    else:
        return ""
    return f"{_GERMAN_WEEKDAYS[dt.weekday()]} {dt.strftime('%d.%m.%y %H:%M')}"


def _deleted_at_sort_key(value: object) -> datetime:
    """Normalisiert deleted_at zu einem vergleichbaren datetime für die
    absteigende Sortierung (neueste zuerst). Nicht parsebare/fehlende Werte
    gelten als älteste (datetime.min)."""
    if isinstance(value, datetime):
        return value
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return datetime.min
    return datetime.min


class ServiceSetTrashDialog(QDialog):
    """Phase 14 P14-05: Papierkorb-Dialog für Service-Sets (Soft-Delete).

    Zeigt alle soft-gelöschten Sets (list_trash()) mit Name und
    Lösch-Zeitstempel. Aktionen:
      - Wiederherstellen  : restore_set_from_trash() verschiebt das Set
                            zurück nach service_sets (das Set-Dropdown des
                            Hauptfensters wird anschließend refresht).
      - Endgültig löschen : purge_trash_set() mit doppelter Sicherheits-
                            abfrage (Vorgang ist nicht umkehrbar).
      - Papierkorb leeren : purge_trash() mit doppelter Sicherheits-
                            abfrage (Vorgang ist nicht umkehrbar).
    """

    def __init__(
        self,
        repo: ServiceSetRepository,
        log_fn: Callable[[str], None],
        refresh_fn: Callable[[], None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._repo = repo
        self._log = log_fn
        self._refresh = refresh_fn

        self.setWindowTitle("Papierkorb - Service-Sets")
        self.setMinimumSize(440, 340)

        layout = QVBoxLayout(self)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        # Bugfix 05.08.2026: Tabelle statt Liste – das Löschdatum steht als
        # EIGENE Spalte GANZ VORN ("Gelöscht am"), danach nur der Name des
        # gelöschten Objekts (kein Datum hinter dem Namen). Sortierung:
        # neueste zuerst (absteigend nach deleted_at, siehe _reload).
        self.trash_table = QTableWidget()
        self.trash_table.setColumnCount(2)
        self.trash_table.setHorizontalHeaderLabels(["Gelöscht am", "Name"])
        self.trash_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.trash_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.trash_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.trash_table.verticalHeader().setVisible(False)
        header = self.trash_table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.trash_table, 1)

        btn_row = QHBoxLayout()
        self.btn_restore = QPushButton("Wiederherstellen")
        self.btn_purge_one = QPushButton("Löschen")
        self.btn_purge_all = QPushButton("Papierkorb leeren")
        btn_close = QPushButton("Schliessen")
        for b in (self.btn_restore, self.btn_purge_one, self.btn_purge_all, btn_close):
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.btn_restore.clicked.connect(self._restore)
        self.btn_purge_one.clicked.connect(self._purge_selected)
        self.btn_purge_all.clicked.connect(self._purge_all)
        btn_close.clicked.connect(self.accept)

        self._reload()

    # --- intern ---

    def _reload(self) -> None:
        self.trash_table.setRowCount(0)
        trash_items = list(self._repo.list_trash())
        # Bugfix 05.08.2026: Neueste zuerst – absteigend nach deleted_at
        # (das Repository liefert aufsteigend).
        trash_items.sort(
            key=lambda it: _deleted_at_sort_key(it.get("deleted_at")),
            reverse=True,
        )
        for row, item in enumerate(trash_items):
            set_id = item.get("set_id")
            name = item.get("display_name") or set_id or "Unbenannt"
            deleted_at = _format_deleted_at(item.get("deleted_at"))
            date_item = QTableWidgetItem(deleted_at)
            date_item.setData(Qt.UserRole, set_id)
            self.trash_table.insertRow(row)
            self.trash_table.setItem(row, 0, date_item)
            self.trash_table.setItem(row, 1, QTableWidgetItem(name))
        has_items = self.trash_table.rowCount() > 0
        self.btn_restore.setEnabled(has_items)
        self.btn_purge_one.setEnabled(has_items)
        self.btn_purge_all.setEnabled(has_items)
        self.hint.setText(
            "Der Papierkorb ist leer."
            if not has_items
            else "Soft-geloeschte Service-Sets (P14-05). Wiederherstellen "
                 "verschiebt das Set zurueck in die aktive Liste; "
                 "endgueltiges Loeschen ist nicht umkehrbar."
        )

    def _selected_id(self) -> Optional[str]:
        row = self.trash_table.currentRow()
        if row < 0:
            return None
        item = self.trash_table.item(row, 0)
        return item.data(Qt.UserRole) if item else None

    def _restore(self) -> None:
        set_id = self._selected_id()
        if not set_id:
            return
        if self._repo.restore_set_from_trash(set_id):
            self._log(f"Set wiederhergestellt (P14-05): {set_id}")
            self._reload()
            self._refresh()
            # Phase 15.02: Struktur-Aenderung -> EventBus (Live-Sync aller
            # ServiceSelectorModel-Instanzen, Invariante 5).
            event_bus.service_set_changed.emit()
        else:
            self._log(f"Set '{set_id}' nicht im Papierkorb gefunden.")

    def _purge_selected(self) -> None:
        set_id = self._selected_id()
        if not set_id:
            return
        # Doppelte Sicherheitsnachfrage - endgueltiges Loeschen ist nicht
        # umkehrbar (User-Vorgabe P14-05).
        first = QMessageBox.question(
            self, "Endgueltig loeschen?",
            "Das Set wird ENDGUELTIG geloescht und kann nicht "
            "wiederhergestellt werden. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if first != QMessageBox.Yes:
            return
        second = QMessageBox.question(
            self, "Wirklich endgueltig loeschen?",
            "Dieser Vorgang ist NICHT umkehrbar. Das Set wird unwiderruflich "
            "aus dem Papierkorb entfernt. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if second != QMessageBox.Yes:
            return
        if self._repo.purge_trash_set(set_id):
            self._log(f"Set endgueltig geloescht (P14-05): {set_id}")
            self._reload()
            # Phase 15: Struktur-Aenderung -> EventBus (Live-Sync aller
            # ServiceSelectorModel-Instanzen, Invariante 5).
            event_bus.service_set_changed.emit()
        else:
            self._log(f"Set '{set_id}' nicht im Papierkorb gefunden.")

    def _purge_all(self) -> None:
        if self.trash_table.rowCount() == 0:
            return
        # Doppelte Sicherheitsnachfrage - endgueltiges Loeschen ist nicht
        # umkehrbar (User-Vorgabe P14-05).
        first = QMessageBox.question(
            self, "Papierkorb leeren?",
            f"Alle {self.trash_table.rowCount()} Sets im Papierkorb werden "
            "ENDGUELTIG geloescht und koennen nicht wiederhergestellt "
            "werden. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if first != QMessageBox.Yes:
            return
        second = QMessageBox.question(
            self, "Wirklich Papierkorb leeren?",
            "Dieser Vorgang ist NICHT umkehrbar. Alle Sets werden "
            "unwiderruflich entfernt. Fortfahren?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if second != QMessageBox.Yes:
            return
        count = self._repo.purge_trash()
        self._log(f"Papierkorb geleert (P14-05): {count} Set(s) endgueltig entfernt.")
        self._reload()
        # Phase 15: Struktur-Aenderung -> EventBus (Live-Sync aller
        # ServiceSelectorModel-Instanzen, Invariante 5).
        event_bus.service_set_changed.emit()
