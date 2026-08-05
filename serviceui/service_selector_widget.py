# serviceui/service_selector_widget.py
"""
Service-UI: Generisches Service-Auswahl-Widget (Phase 15 15.02).

Konfigurierbares PySide6-Widget mit zwei Betriebsmodi:

  * Modus A (SELECT_ONLY): Kompakte Dropdown-Auswahl (Set-Combo + Service-
    Combo) fuer die schwellenfreie Wiederverwendung in Analytics (15.03),
    Backtester oder Charts. Emittiert `selection_changed(set_id, service_id)`.
  * Modus B (FULL_EDIT):  Vollstaendiges Master-Tree-Widget mit Aktions-
    Toolbar fuer service_win.py (Erstellen, Umsortieren, Loeschen).

Beide Modi werden ausschliesslich aus dem `ServiceSelectorModel` befuellt
(lesendes Datenmodell, EventBus-Live-Sync, Invariante 4/5).
"""

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from analytics.engine.service_selector_model import ServiceSelectorModel
from serviceui.master_tree import MasterTree
from serviceui.toolbar import ServiceToolbar


class ServiceSelectorWidget(QWidget):
    """Wiederverwendbares Auswahl-Widget fuer Service-Sets & Services."""

    #: Betriebsmodi
    MODE_SELECT_ONLY = "SELECT_ONLY"
    MODE_FULL_EDIT = "FULL_EDIT"

    #: Emittiert (set_id, service_id) – service_id leer, wenn nur ein Set
    #: gewaehlt wurde (bzw. in SELECT_ONLY ohne aktives Set).
    selection_changed = Signal(str, str)
    #: Bugfix 05.08.2026: Klick auf den Info-Button im MasterTree (FULL_EDIT)
    #: wird an den Aufrufer weitergereicht (set_id, service_id, plugin_id).
    info_requested = Signal(str, str, str)

    def __init__(self, mode: str = MODE_SELECT_ONLY, model: Optional[ServiceSelectorModel] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.model = model or ServiceSelectorModel()

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Modus-Bausteine (werden je nach Modus erzeugt/eingefuegt)
        self._compact_row: Optional[QWidget] = None
        self.master_tree: Optional[MasterTree] = None
        self.toolbar: Optional[ServiceToolbar] = None

        self.model.data_changed.connect(self._on_model_changed)
        self.set_mode(mode)

    # -------------------------------------------------------------------------
    # Modus-Umschaltung
    # -------------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """Baut das Widget fuer den gewuenschten Betriebsmodus auf.

        Args:
            mode: MODE_SELECT_ONLY (Dropdown) oder MODE_FULL_EDIT (Tree+Toolbar).
        """
        mode = mode or self.MODE_SELECT_ONLY
        # Alte Bausteine entfernen
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._compact_row = None
        self.master_tree = None
        self.toolbar = None

        if mode == self.MODE_FULL_EDIT:
            self._build_full_edit()
        else:
            self._build_select_only()

    def _build_select_only(self) -> None:
        """Modus A: kompakte Set-/Service-Combos."""
        self._compact_row = QWidget(self)
        row = QHBoxLayout(self._compact_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(QLabel("Set:"))
        self.combo_set = QComboBox()
        self.combo_set.setMinimumWidth(140)
        row.addWidget(self.combo_set, 1)
        row.addWidget(QLabel("Service:"))
        self.combo_service = QComboBox()
        self.combo_service.setMinimumWidth(140)
        row.addWidget(self.combo_service, 1)

        self.combo_set.currentIndexChanged.connect(self._on_set_combo_changed)
        self.combo_service.currentIndexChanged.connect(self._emit_combo_selection)
        self._layout.addWidget(self._compact_row)
        self._repopulate_select_only()

    def _build_full_edit(self) -> None:
        """Modus B: MasterTree (2 Spalten) + ServiceToolbar."""
        self.master_tree = MasterTree(self.model, parent=self)
        self.toolbar = ServiceToolbar(parent=self)
        self._layout.addWidget(self.toolbar)
        self._layout.addWidget(self.master_tree, 1)

        self.master_tree.selection_changed.connect(self.selection_changed)
        # Bugfix 05.08.2026: Info-Button-Klicks im MasterTree re-emittieren.
        self.master_tree.info_requested.connect(self.info_requested)

    # -------------------------------------------------------------------------
    # Modell-Sync
    # -------------------------------------------------------------------------

    def _on_model_changed(self) -> None:
        """Modell-Aenderung (EventBus): SELECT_ONLY-Combos neu befuellen;
        im FULL_EDIT aktualisiert der MasterTree sich selbst."""
        if self._compact_row is not None:
            self._repopulate_select_only()

    def _repopulate_select_only(self) -> None:
        """Befuellt Set- und Service-Combo aus dem Modell (deterministisch)."""
        current_set = self.combo_set.currentData() if hasattr(self, "combo_set") else None
        sets = self.model.get_sets()

        self.combo_set.blockSignals(True)
        self.combo_set.clear()
        self.combo_set.addItem("(kein Set)", None)
        for s in sets:
            self.combo_set.addItem(
                str(s.get("display_name") or s.get("set_id") or "Unbenannt"),
                s.get("set_id"))
        if current_set is not None:
            idx = self.combo_set.findData(current_set)
            if idx >= 0:
                self.combo_set.setCurrentIndex(idx)
        self.combo_set.blockSignals(False)

        self._fill_service_combo(self.combo_set.currentData())

    def _fill_service_combo(self, set_id: Optional[str]) -> None:
        """Befuellt die Service-Combo mit den Services des gewaehlten Sets."""
        self.combo_service.blockSignals(True)
        self.combo_service.clear()
        self.combo_service.addItem("(Service wählen)", None)
        if set_id:
            s = self.model.find_set(set_id)
            services = (s or {}).get("services") or {}
            for iid in (s or {}).get("execution_order") or []:
                cfg = services.get(iid) or {}
                pid = cfg.get("plugin_id") or iid
                self.combo_service.addItem(f"{iid} [{pid}]", iid)
        self.combo_service.blockSignals(False)

    def _on_set_combo_changed(self, _index: int) -> None:
        self._fill_service_combo(self.combo_set.currentData())
        self._emit_combo_selection()

    def _emit_combo_selection(self) -> None:
        set_id = self.combo_set.currentData() or ""
        service_id = self.combo_service.currentData() or ""
        self.selection_changed.emit(set_id, service_id)

    # -------------------------------------------------------------------------
    # Oeffentliche Auswahl-API
    # -------------------------------------------------------------------------

    def current_set_id(self) -> str:
        if self._compact_row is not None:
            return self.combo_set.currentData() or ""
        if self.master_tree is not None:
            return self.master_tree.current_set_id()
        return ""

    def current_service_id(self) -> str:
        if self._compact_row is not None:
            return self.combo_service.currentData() or ""
        if self.master_tree is not None:
            return self.master_tree.current_service_id()
        return ""

    def get_plugin_ids(self) -> List[str]:
        """Alle verfuegbaren Plugin-IDs (sortiert) – fuer das [➕]-Popup."""
        return sorted(self.model.get_plugins().keys())

    def refresh(self) -> None:
        """Erzwingt einen Modell-Refresh (z.B. nach manuellen DB-Aenderungen)."""
        self.model.refresh()
