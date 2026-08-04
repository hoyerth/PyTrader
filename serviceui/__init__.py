# serviceui/__init__.py
"""
Service-UI-Paket (Phase 15, Kapitel 15.1 – U15-D1).

Modularisierte Service-UI: Die gewachsene service_win.py wurde in den
Unterordner serviceui/ verschoben und in SRP-Module zerlegt:

  * service_set_utils.py   – _available_plugin_ids, _sets_using_plugin
  * set_run_worker.py      – ServiceSetRunWorker (QThread)
  * set_item_adapter.py    – ServiceSetItemAdapter (NamedItemAdapter)
  * param_columns.py       – ServiceParamColumnsMixin (Parameter-Column-Builder)
  * trash_dialog.py        – ServiceSetTrashDialog (Papierkorb-Dialog)
  * service_win.py         – ServiceWindow (Hauptfenster, re-exportiert API)

Verhalten unverändert gegenüber der alten service_win.py.
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

__all__ = [
    "ServiceWindow",
    "ServiceSetRunWorker",
    "ServiceSetItemAdapter",
    "_ServiceSetItemAdapter",
    "_available_plugin_ids",
    "_sets_using_plugin",
    "BASE_DIR",
]
