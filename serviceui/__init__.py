# serviceui/__init__.py
"""
Service-UI-Paket (Phase 15, Kapitel 15.1 – U15-D1 + 15.02).

Modularisierte Service-UI: Die gewachsene service_win.py wurde in den
Unterordner serviceui/ verschoben und in SRP-Module zerlegt:

  * service_set_utils.py   – _available_plugin_ids, _sets_using_plugin
  * set_run_worker.py      – ServiceSetRunWorker (QThread)
  * run_worker.py          – ServiceRunWorker (QThread, gezielter Kontextmenue-
                             Run mit FeatureStore-Persistenz, 05.08.2026)
  * set_item_adapter.py    – ServiceSetItemAdapter (NamedItemAdapter)
  * param_columns.py       – ServiceParamColumnsMixin (Parameter-Column-Builder)
  * trash_dialog.py        – ServiceSetTrashDialog (Papierkorb-Dialog)
  * service_win.py         – ServiceWindow (Hauptfenster, re-exportiert API)

Phase 15.02 (Master-Tree & generischer ServiceSelector):
  * master_tree.py             – 2-Spalten MasterTree (Hierarchie + Badges,
                                 Ausfuehrungsdatum, Kontextmenue-Run-Aktionen)
  * service_selector_widget.py – ServiceSelectorWidget (SELECT_ONLY/FULL_EDIT)
  * new_set_dialog.py          – NewServiceSetDialog (Set + Indikator)
  * analytics/engine/service_selector_model.py – lesendes Datenmodell

Die fruehere Aktions-Toolbar (serviceui/toolbar.py, ServiceToolbar) ist seit
05.08.2026 komplett entfernt – alle Struktur-Aktionen laufen ueber das
MasterTree-Kontextmenue. Die Datei ist unter .backup_service_toolbar/
archiviert (gitignored, Konvention wie .backup_grid_liquidity und
.backup_parameter_panel).
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

# 05.08.2026: Gezielter Run-Worker (MasterTree-Kontextmenue 'Service(s)
# ausführen') – FeatureStore-Persistenz + EventBus-Sync.
from serviceui.run_worker import ServiceRunWorker

# Phase 15.02: Wiederverwendbare Sub-Widgets
from serviceui.master_tree import MasterTree
from serviceui.status_panel import StatusPanel
from serviceui.service_selector_widget import ServiceSelectorWidget
from serviceui.new_set_dialog import NewServiceSetDialog

__all__ = [
    "ServiceWindow",
    "ServiceSetRunWorker",
    "ServiceRunWorker",
    "ServiceSetItemAdapter",
    "_ServiceSetItemAdapter",
    "_available_plugin_ids",
    "_sets_using_plugin",
    "BASE_DIR",
    # Phase 15.02
    "MasterTree",
    "StatusPanel",
    "ServiceSelectorWidget",
    "NewServiceSetDialog",
]
