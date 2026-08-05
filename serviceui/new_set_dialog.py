# serviceui/new_set_dialog.py
"""
Service-UI: Dialog zum Anlegen neuer Service-Sets (Bugfix 05.08.2026).

Einfache Bedienung: ein Namensfeld + eine Indikator-Auswahl. Wird ein
Indikator gewaehlt, legt der Aufrufer (ServiceWindow._on_add_set) die
Basis-Services des Indikators (service_plugin_ids, z.B. grid_lines +
proximity) automatisch im neuen Set an – das Set ist damit sofort gueltig
fuer den Indikator.

Reine UI-Klasse (SRP): kein SQL, kein Repository-Zugriff – die Indikator-
Liste wird vom Aufrufer als Daten uebergeben.
"""

from typing import Any, Dict, List, Optional

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QMessageBox, QVBoxLayout, QWidget,
)


class NewServiceSetDialog(QDialog):
    """Namens- + Indikator-Auswahl fuer ein neues Service-Set."""

    def __init__(self, indicators: List[Dict[str, Any]],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Neues Service-Set anlegen")

        self.edit_name = QLineEdit(self)
        self.edit_name.setPlaceholderText("Name (z.B. 'Grid Basis')")

        self.combo_indicator = QComboBox(self)
        self.combo_indicator.addItem("(kein Indikator)", None)
        for info in indicators:
            ind_id = str(info.get("indicator_id") or "")
            if not ind_id:
                continue
            label = str(info.get("display_name") or ind_id)
            self.combo_indicator.addItem(label, ind_id)

        form = QFormLayout()
        form.addRow("Name:", self.edit_name)
        form.addRow("Indikator:", self.combo_indicator)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------
    # Validierung & Ergebnis-API
    # ------------------------------------------------------------------

    def _on_accept(self) -> None:
        """OK: Name ist Pflicht (Bugfix 05.08.2026 – 'ein neuer Name soll
        eingegeben werden'). Leerer Name bleibt im Dialog offen."""
        if not self.edit_name.text().strip():
            QMessageBox.warning(
                self, "Name fehlt",
                "Bitte einen Namen für das neue Service-Set eingeben.")
            return
        self.accept()

    def result_name(self) -> str:
        """Der eingegebene Set-Name (getrimmt)."""
        return self.edit_name.text().strip()

    def result_indicator_id(self) -> str:
        """Die gewaehlte Indikator-ID ('' = kein Indikator)."""
        return str(self.combo_indicator.currentData() or "")
