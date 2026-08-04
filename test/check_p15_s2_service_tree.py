# test/check_p15_s2_service_tree.py
"""
Phase 15 15.02 – Headless Validierung (KEINE UI, KEIN QApplication.exec()).

Prueft den generischen ServiceSelector (ServiceSelectorModel +
ServiceSelectorWidget + MasterTree) rein auf Logik-/Widget-Ebene:

A) ServiceSelectorModel – Grunddaten:
   - get_sets() leer bei frischer DB.
   - get_plugins() liefert die PluginRegistry (grid_liquidity, ...).
   - is_chart_indicator()/get_indicator_display_name().
   - Badges: '📌 Indikator: <Name> | ⚪ Inaktiv in Chart' fuer Chart-Indikatoren.

B) ServiceSelectorModel – Set-Aufbau & Hierarchie:
   - Nach save_set() liefert build_tree() die Gruppen
     📁 Service-Sets / ⚡ Standalone Services / 📦 Alle verfuegbaren Plugins.
   - Set-Knoten enthalten ihre Service-Instanzen (instance_id, plugin_id, badge).
   - Standalone enthaelt NICHT die im Set verwendeten Plugins.

C) ServiceSelectorModel – Live-Status "Aktiv im Chart" (StateManager):
   - indicators_state['grid_liquidity'].active=True -> is_active_in_chart True.
   - Badge wechselt auf '🟢 Aktiv in Chart'.

D) EventBus-Reaktivitaet:
   - service_set_changed.emit() -> data_changed feuert + Modell refresht.

E) ServiceSelectorWidget (Modus SELECT_ONLY):
   - Set-/Service-Combos werden aus dem Modell befuellt.
   - selection_changed(set_id, service_id) wird bei Auswahl emittiert.

F) ServiceSelectorWidget (Modus FULL_EDIT / MasterTree):
   - master_tree + toolbar vorhanden; 3 Top-Level-Gruppen (📁/⚡/📦).
   - Service-Knoten tragen das Status-Badge in Spalte 1.
   - current_selection()/current_set_id() liefern die markierte Auswahl.

G) Set-Updates & Umsortieren:
   - execution_order-Aenderung erscheint nach refresh() in der Hierarchie.

Test-DB liegt im Unterordner test/ (Regel: keine Test-DBs im Root/data).
"""
import os
import sys

sys.path.insert(0, r"F:\Python\PyTrader")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_DB = os.path.join(TEST_DIR, "p15_s2_service_tree_test.duckdb")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from analytics.engine.service_set_repository import ServiceSetRepository  # noqa: E402
from state_manager import StateManager  # noqa: E402
from analytics.features.feature_builder import PluginRegistry  # noqa: E402
from analytics.engine.service_selector_model import ServiceSelectorModel  # noqa: E402
from serviceui.service_selector_widget import ServiceSelectorWidget  # noqa: E402
from config.event_bus import event_bus  # noqa: E402

FAILURES: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Test-Infrastruktur (frische Test-DB, injizierte Repos)
# ---------------------------------------------------------------------------
set_repo = ServiceSetRepository(db_path=TEST_DB)
state_mgr = StateManager(db_path=TEST_DB)
registry = PluginRegistry()

model = ServiceSelectorModel(set_repo=set_repo, state_manager=state_mgr,
                             registry=registry)

plugins = model.get_plugins()
print(f"   Plugins: {sorted(plugins.keys())}")

# ---------------------------------------------------------------------------
# A) Grunddaten
# ---------------------------------------------------------------------------
check("A1) get_sets() leer bei frischer DB", model.get_sets() == [])
check("A2) get_plugins() liefert PluginRegistry",
      isinstance(plugins, dict) and len(plugins) > 0)
check("A3) grid_liquidity ist Chart-Indikator",
      model.is_chart_indicator("grid_liquidity"))
check("A4) get_indicator_display_name liefert lesbaren Namen",
      bool(model.get_indicator_display_name("grid_liquidity")))

badge_inactive = model.badge_for("grid_liquidity")
check("A5) Badge inaktiv enthaelt Indikator + ⚪",
      badge_inactive.startswith("📌 Indikator:")
      and "⚪ Inaktiv in Chart" in badge_inactive, badge_inactive)
check("A6) is_active_in_chart False ohne Chart-State",
      model.is_active_in_chart("grid_liquidity") is False)

# ---------------------------------------------------------------------------
# B) Set-Aufbau & Hierarchie
# ---------------------------------------------------------------------------
set_id = set_repo.save_set({
    "display_name": "Grid-Basis",
    "execution_order": ["grid_1", "prox_1"],
    "services": {
        "grid_1": {"plugin_id": "grid_liquidity", "lookback": 1000,
                   "params": {"grid_step": 0.5}},
        "prox_1": {"plugin_id": "proximity", "lookback": 500,
                   "params": {"prox_level1": 1.0}},
    },
})
model.refresh()

check("B1) Set nach save_set() im Modell", len(model.get_sets()) == 1)

tree = model.build_tree()
group_labels = [g["label"] for g in tree]
check("B2) 3 Gruppen (📁/⚡/📦)",
      any("📁" in l for l in group_labels)
      and any("⚡" in l for l in group_labels)
      and any("📦" in l for l in group_labels), str(group_labels))

set_nodes = tree[0]["children"]
check("B3) Set-Knoten vorhanden", len(set_nodes) == 1)
svcs = set_nodes[0]["services"]
svc_ids = [s["instance_id"] for s in svcs]
check("B4) Set enthaelt beide Services",
      svc_ids == ["grid_1", "prox_1"], str(svc_ids))
check("B5) Service-Badge gesetzt",
      all(s["badge"] for s in svcs), str([s["badge"] for s in svcs]))

standalone_ids = [s["plugin_id"] for s in tree[1]["children"]]
check("B6) verwendete Plugins NICHT in Standalone",
      "grid_liquidity" not in standalone_ids
      and "proximity" not in standalone_ids, str(standalone_ids))

plugin_ids = [p["plugin_id"] for p in tree[2]["children"]]
check("B7) Alle Plugins in 📦-Gruppe",
      "grid_liquidity" in plugin_ids and "proximity" in plugin_ids,
      str(plugin_ids))

# ---------------------------------------------------------------------------
# C) Live-Status "Aktiv im Chart" (StateManager)
# ---------------------------------------------------------------------------
state_mgr.save_window_geometry("win_1", 0, 0, 800, 600, False)
state_mgr.save_instance_state(
    "win_1", "SILVER", "H1",
    indicators_state={"grid_liquidity": {"active": True}},
)
model.refresh()

check("C1) grid_liquidity ist aktiv im Chart",
      model.is_active_in_chart("grid_liquidity"))
badge_active = model.badge_for("grid_liquidity")
check("C2) Badge aktiv enthaelt 🟢",
      "🟢 Aktiv in Chart" in badge_active, badge_active)
check("C3) proximity bleibt inaktiv",
      not model.is_active_in_chart("proximity"))

# ---------------------------------------------------------------------------
# D) EventBus-Reaktivitaet
# ---------------------------------------------------------------------------
data_calls = []
model.data_changed.connect(lambda: data_calls.append(1))
event_bus.service_set_changed.emit()
check("D1) data_changed feuert bei service_set_changed",
      len(data_calls) >= 1, str(data_calls))
check("D2) Modell nach EventBus-Refresh aktuell",
      len(model.get_sets()) == 1 and model.is_active_in_chart("grid_liquidity"))

# ---------------------------------------------------------------------------
# E) ServiceSelectorWidget – Modus SELECT_ONLY
# ---------------------------------------------------------------------------
sel = ServiceSelectorWidget(mode=ServiceSelectorWidget.MODE_SELECT_ONLY,
                            model=model)
emitted = []
sel.selection_changed.connect(lambda sid, svc: emitted.append((sid, svc)))

check("E1) Set-Combo befuellt", sel.combo_set.count() == 2, str(sel.combo_set.count()))
idx = sel.combo_set.findData(set_id)
check("E2) Set auswaehlbar", idx >= 0)
if idx >= 0:
    sel.combo_set.setCurrentIndex(idx)
check("E3) Service-Combo befuellt", sel.combo_service.count() == 3,
      str(sel.combo_service.count()))  # Platzhalter + grid_1 + prox_1
if sel.combo_service.count() > 1:
    sel.combo_service.setCurrentIndex(1)
check("E4) selection_changed emittiert (set_id, service_id)",
      emitted and emitted[-1][0] == set_id and emitted[-1][1] == "grid_1",
      str(emitted))
check("E5) current_set_id/current_service_id",
      sel.current_set_id() == set_id and sel.current_service_id() == "grid_1",
      f"{sel.current_set_id()}/{sel.current_service_id()}")

# ---------------------------------------------------------------------------
# F) ServiceSelectorWidget – Modus FULL_EDIT (MasterTree)
# ---------------------------------------------------------------------------
full = ServiceSelectorWidget(mode=ServiceSelectorWidget.MODE_FULL_EDIT,
                             model=model)
check("F1) MasterTree vorhanden", full.master_tree is not None)
check("F2) Toolbar vorhanden", full.toolbar is not None)
mt = full.master_tree
check("F3) 3 Top-Level-Gruppen", mt.topLevelItemCount() == 3,
      str(mt.topLevelItemCount()))

set_group = mt.topLevelItem(0)
check("F4) Set-Gruppe hat Set-Knoten mit Services",
      set_group.childCount() == 1 and set_group.child(0).childCount() == 2,
      f"sets={set_group.childCount()} svcs={set_group.child(0).childCount()}")

# Service-Knoten: Badge in Spalte 1 (📌/🟢)
svc_item = set_group.child(0).child(0)
badge_text = svc_item.text(1)
check("F5) Service-Badge in Spalte 1",
      "📌" in badge_text and ("🟢" in badge_text or "⚪" in badge_text),
      badge_text)

# Selektion: Set-Knoten markieren
mt.setCurrentItem(set_group.child(0))
check("F6) current_set_id aus MasterTree", mt.current_set_id() == set_id,
      str(mt.current_set_id()))
mt.setCurrentItem(svc_item)
sel2 = mt.current_selection()
check("F7) current_selection() liefert Set+Service",
      sel2["set_id"] == set_id and sel2["service_id"] == "grid_1",
      str(sel2))

# ---------------------------------------------------------------------------
# G) Set-Updates & Umsortieren
# ---------------------------------------------------------------------------
set_repo.save_set({
    "set_id": set_id,
    "display_name": "Grid-Basis",
    "execution_order": ["prox_1", "grid_1"],  # Umsortieren
    "services": {
        "grid_1": {"plugin_id": "grid_liquidity", "lookback": 1000,
                   "params": {}},
        "prox_1": {"plugin_id": "proximity", "lookback": 500,
                   "params": {}},
    },
})
model.refresh()
set_nodes = model.build_tree()[0]["children"]
check("G1) Umsortieren sichtbar (prox_1 zuerst)",
      [s["instance_id"] for s in set_nodes[0]["services"]] == ["prox_1", "grid_1"],
      str([s["instance_id"] for s in set_nodes[0]["services"]]))

event_bus.service_set_changed.emit()
check("G2) Modell reagiert auf EventBus (Set-Update)",
      [s["instance_id"] for s in model.build_tree()[0]["children"][0]["services"]]
      == ["prox_1", "grid_1"])

# ---------------------------------------------------------------------------
# Aufraeumen
# ---------------------------------------------------------------------------
try:
    os.remove(TEST_DB)
except OSError:
    pass

print("-" * 60)
if FAILURES:
    print(f"FEHLER: {len(FAILURES)} Pruefung(en) fehlgeschlagen: {FAILURES}")
    sys.exit(1)
print("ALLE PRUEFUNGEN BESTANDEN (OK)")
sys.exit(0)
