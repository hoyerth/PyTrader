# serviceui/__init__.py
"""
Service-UI-Paket (Phase 15, Kapitel 15.1 – U15-D1 + 15.02).

Modularisierte Service-UI: Die gewachsene service_win.py wurde in den
Unterordner serviceui/ verschoben und in SRP-Module zerlegt:

  * service_set_utils.py   – _available_plugin_ids, _sets_using_plugin
  * set_run_worker.py      – ServiceSetRunWorker (QThread)
  * set_item_adapter.py    – ServiceSetItemAdapter (NamedItemAdapter)
  * param_columns.py       – ServiceParamColumnsMixin (Parameter-Column-Builder)
  * trash_dialog.py        – ServiceSetTrashDialog (Papierkorb-Dialog)
  * service_win.py         – ServiceWindow (Hauptfenster, re-exportiert API)

Phase 15.02 (Master-Tree & generischer ServiceSelector):
  * master_tree.py             – 2-Spalten MasterTree (Hierarchie + Badges)
  * toolbar.py                 – ServiceToolbar (Aktions-Buttons)
  * status_panel.py            – StatusPanel (Laufzeit/Fortschritt/Log)
  * service_selector_widget.py – ServiceSelectorWidget (SELECT_ONLY/FULL_EDIT)
  * new_set_dialog.py          – NewServiceSetDialog (Set + Indikator)
  * analytics/engine/service_selector_model.py – lesendes Datenmodell
"""

from serviceui.service_win import (
    ServiceWindow,
    ServiceSetRunWorker,
    ServiceSetItemAdapter,
    _ServiceSetItemAdapter,
    _available_plugin_ids,
    _sets_using_plugin,
    BASE_DIR,
)

# Phase 15.02: Wiederverwendbare Sub-Widgets
from serviceui.master_tree import MasterTree
from serviceui.toolbar import ServiceToolbar
from serviceui.status_panel import StatusPanel
from serviceui.service_selector_widget import ServiceSelectorWidget
from serviceui.new_set_dialog import NewServiceSetDialog

__all__ = [
    "ServiceWindow",
    "ServiceSetRunWorker",
    "ServiceSetItemAdapter",
    "_ServiceSetItemAdapter",
    "_available_plugin_ids",
    "_sets_using_plugin",
    "BASE_DIR",
    # Phase 15.02
    "MasterTree",
    "ServiceToolbar",
    "StatusPanel",
    "ServiceSelectorWidget",
    "NewServiceSetDialog",
]
