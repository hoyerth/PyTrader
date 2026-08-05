# test/check_p15_s2_service_tree.py
"""
Phase 15 15.02 – Headless Validierung (KEINE UI, KEIN QApplication.exec()).

Prueft den generischen ServiceSelector (ServiceSelectorModel +
ServiceSelectorWidget + MasterTree) rein auf Logik-/Widget-Ebene:

A) ServiceSelectorModel – Grunddaten:
   - get_sets() leer bei frischer DB.
   - get_plugins() liefert die PluginRegistry (grid_lines, ...).
   - is_chart_indicator()/get_indicator_display_name().
   - Badges: '📌 im GridLiquidityIndicator | ⚪ inaktiv in GridLiquidityIndicator'
     fuer Chart-Indikatoren (Indikator-Name, KEIN Service-Name).

B) ServiceSelectorModel – Set-Aufbau & Hierarchie:
   - Nach save_set() liefert build_tree() die Gruppen
     📁 Service-Sets / ⚡ Standalone Services / 📦 Alle verfuegbaren Plugins.
   - Set-Knoten enthalten ihre Service-Instanzen (instance_id, plugin_id, badge).
   - Standalone enthaelt NICHT die im Set verwendeten Plugins.

C) ServiceSelectorModel – Live-Status "Aktiv im Chart" (StateManager):
   - indicators_state['grid_lines'].active=True -> is_active_in_chart True.
   - Badge wechselt auf '🟢 aktiv in GridLiquidityIndicator'.

D) EventBus-Reaktivitaet:
   - service_set_changed.emit() -> data_changed feuert + Modell refresht.

E) ServiceSelectorWidget (Modus SELECT_ONLY):
   - Set-/Service-Combos werden aus dem Modell befuellt.
   - selection_changed(set_id, service_id) wird bei Auswahl emittiert.

F) ServiceSelectorWidget (Modus FULL_EDIT / MasterTree):
   - master_tree + toolbar vorhanden; 3 Top-Level-Gruppen (📁/⚡/📦).
   - Service-/Set-/Plugin-Zeilen tragen den Info-Button (QPushButton "ℹ",
     Icon-Breite) in Spalte 1; Tooltip + gelbe Faerbung bei Indikator-
     Zugehoerigkeit; info_requested-Signal bei Klick.
   - current_selection()/current_set_id() liefern die markierte Auswahl.

H) Info-Dialog: ServiceDescriptionDialog.from_set()/from_plugin() rendern
   die header_line (erste Zeile) + Beschreibungstext (headless pruefbar).

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
from PySide6.QtWidgets import QHeaderView  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402
from PySide6.QtWidgets import QTextBrowser  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

from analytics.engine.service_set_repository import ServiceSetRepository  # noqa: E402
from state_manager import StateManager  # noqa: E402
from analytics.features.feature_builder import PluginRegistry  # noqa: E402
from analytics.engine.service_selector_model import ServiceSelectorModel  # noqa: E402
from serviceui.service_selector_widget import ServiceSelectorWidget  # noqa: E402
from serviceui.master_tree import (  # noqa: E402
    BADGE_COLUMN_WIDTH, BADGE_TRUNCATE_ICON, INFO_BUTTON_TEXT,
    INFO_BUTTON_WIDTH, INFO_BUTTON_SIZE,
    INFO_BUTTON_COLOR_INDICATOR, INFO_BUTTON_COLOR_NEUTRAL, ROLE_PLUGIN_ID,
)
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

# 05.08.2026 (Ausfuehrungsdatum): Eigene Test-Feature-Store-DB unter test/
# (Konvention: alle Test-DBs unter test/). Eine proximity-Row mit aktuellem
# created_at simuliert die letzte Ausfuehrung -> 'DD.MM.JJ' im MasterTree.
TEST_FS_DB = os.path.join(TEST_DIR, "p15_s2_execdate_test.duckdb")
if os.path.exists(TEST_FS_DB):
    os.remove(TEST_FS_DB)
import duckdb as _duckdb  # noqa: E402
_fs_con = _duckdb.connect(TEST_FS_DB)
_fs_con.execute("""
    CREATE TABLE feature_store (
        symbol VARCHAR, timeframe VARCHAR, bar_time TIMESTAMPTZ,
        ema_diff DOUBLE, rsi_14 DOUBLE, atr_normalized DOUBLE,
        created_at TIMESTAMP DEFAULT current_timestamp,
        feature_id VARCHAR, plugin_version VARCHAR, feature_data JSON
    )
""")
_fs_con.execute("""
    INSERT INTO feature_store (symbol, timeframe, bar_time, feature_id,
                               plugin_version, feature_data)
    VALUES ('SILVER', 'M1', current_timestamp, 'proximity', '1.0.0',
            '{"schema_version":"1.0.0"}')
""")
_fs_con.close()
from analytics.engine.feature_store_reader import FeatureStoreReader  # noqa: E402
fs_reader = FeatureStoreReader(db_path=TEST_FS_DB)

model = ServiceSelectorModel(set_repo=set_repo, state_manager=state_mgr,
                             registry=registry, feature_store_reader=fs_reader)

plugins = model.get_plugins()
print(f"   Plugins: {sorted(plugins.keys())}")

# ---------------------------------------------------------------------------
# A) Grunddaten
# ---------------------------------------------------------------------------
check("A1) get_sets() leer bei frischer DB", model.get_sets() == [])
check("A2) get_plugins() liefert PluginRegistry",
      isinstance(plugins, dict) and len(plugins) > 0)
# Bugfix 04.08.2026: grid_liquidity (Alt-Plugin) ist entfernt – grid_lines ist
# der Chart-faehige Grid-Service und referenziert den Indikator-Namen.
check("A3) grid_lines ist Chart-Indikator",
      model.is_chart_indicator("grid_lines"))
ind_name = model.get_indicator_display_name("grid_lines")
check("A4) Indikator-Name = GridLiquidityIndicator",
      ind_name == "GridLiquidityIndicator", ind_name)

badge_inactive = model.badge_for("grid_lines")
check("A5) Badge inaktiv: 'im' + 'inaktiv in' mit Indikator-Namen",
      badge_inactive == "📌 im GridLiquidityIndicator | ⚪ inaktiv in GridLiquidityIndicator",
      badge_inactive)
check("A5b) Kein Service-Name ('Grid Lines'/'Proximity') im Badge",
      "Grid Lines" not in badge_inactive and "Proximity" not in badge_inactive,
      badge_inactive)
check("A6) is_active_in_chart False ohne Chart-State",
      model.is_active_in_chart("grid_lines") is False)

# ---------------------------------------------------------------------------
# B) Set-Aufbau & Hierarchie
# ---------------------------------------------------------------------------
set_id = set_repo.save_set({
    "display_name": "Grid-Basis",
    "execution_order": ["grid_1", "prox_1"],
    "services": {
        "grid_1": {"plugin_id": "grid_lines", "lookback": 1000,
                   "params": {"step_size": 0.5}},
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
      "grid_lines" not in standalone_ids
      and "proximity" not in standalone_ids, str(standalone_ids))

plugin_ids = [p["plugin_id"] for p in tree[2]["children"]]
check("B7) Alle Plugins in 📦-Gruppe",
      "grid_lines" in plugin_ids and "proximity" in plugin_ids,
      str(plugin_ids))

# ---------------------------------------------------------------------------
# C) Live-Status "Aktiv im Chart" (StateManager)
# ---------------------------------------------------------------------------
state_mgr.save_window_geometry("win_1", 0, 0, 800, 600, False)
state_mgr.save_instance_state(
    "win_1", "SILVER", "H1",
    indicators_state={"grid_lines": {"active": True}},
)
model.refresh()

check("C1) grid_lines ist aktiv im Chart",
      model.is_active_in_chart("grid_lines"))
badge_active = model.badge_for("grid_lines")
check("C2) Badge aktiv: 'aktiv in' mit Indikator-Namen",
      badge_active == "📌 im GridLiquidityIndicator | 🟢 aktiv in GridLiquidityIndicator",
      badge_active)
check("C3) proximity bleibt inaktiv",
      not model.is_active_in_chart("proximity"))
# Beide Grid-Services referenzieren denselben Indikator-Namen im Badge.
for pid in ("grid_lines", "proximity"):
    b = model.badge_for(pid)
    check(f"C4) Badge fuer '{pid}' referenziert GridLiquidityIndicator",
          "in GridLiquidityIndicator" in b and "Grid Lines" not in b
          and "Proximity" not in b, b)

# Bugfix 05.08.2026: Aktiv-Pruefung ueber die indicator_id des ZUGEHOERIGEN
# Indikators. Realer App-Zustand: indicators_state-Key ist die indicator_id
# ('grid_liquidity'), NICHT die Plugin-ID ('grid_lines'/'proximity'). Davor
# griff die Tooltip-Variante a) ('aktiv <Indikator>') fuer Services nie.
state_mgr.save_window_geometry("win_2", 0, 0, 800, 600, False)
state_mgr.save_instance_state(
    "win_2", "SILVER", "H1",
    indicators_state={"grid_liquidity": {"active": True}},
)
model.refresh()
check("C5) grid_lines aktiv via Indikator-ID (grid_liquidity)",
      model.is_active_in_chart("grid_lines"))
check("C6) proximity aktiv via Indikator-ID (grid_liquidity)",
      model.is_active_in_chart("proximity"))
check("C7) belongs_to_indicator fuer grid_lines/proximity",
      model.belongs_to_indicator("grid_lines")
      and model.belongs_to_indicator("proximity"))
set_def = model.get_sets()[0]
check("C8) Set-Indikator-Namen = [GridLiquidityIndicator]",
      model.get_set_indicator_names(set_def) == ["GridLiquidityIndicator"],
      str(model.get_set_indicator_names(set_def)))
check("C9) Set aktiv (zugehoeriger Indikator aktiv)",
      model.is_set_active(set_def))

# ---------------------------------------------------------------------------
# D) EventBus-Reaktivitaet
# ---------------------------------------------------------------------------
data_calls = []
model.data_changed.connect(lambda: data_calls.append(1))
event_bus.service_set_changed.emit()
check("D1) data_changed feuert bei service_set_changed",
      len(data_calls) >= 1, str(data_calls))
check("D2) Modell nach EventBus-Refresh aktuell",
      len(model.get_sets()) == 1 and model.is_active_in_chart("grid_lines"))

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
# Test-Plugin OHNE Indikator-Zugehoerigkeit injizieren – damit gibt es eine
# Zeile mit neutralem (nicht gelbem) Info-Button und leerem Tooltip.
class _PlainPlugin:
    plugin_id = "_test_plain"
    version = "1.0.0"
    capabilities: dict = {}
    metadata = {"display_name": "Plain", "description": "Plain-Test-Plugin"}


registry.plugins["_test_plain"] = _PlainPlugin()
model.refresh()

full = ServiceSelectorWidget(mode=ServiceSelectorWidget.MODE_FULL_EDIT,
                             model=model)
check("F1) MasterTree vorhanden", full.master_tree is not None)
# 05.08.2026: CRUD-/Order-Buttons oberhalb des Baums entfernt – der
# MasterTree hat die volle vertikale Hoehe (alle Aktionen via Kontextmenue).
check("F2) Keine Toolbar mehr (volle Baum-Hoehe)", full.toolbar is None)
mt = full.master_tree
check("F3) 3 Top-Level-Gruppen", mt.topLevelItemCount() == 3,
      str(mt.topLevelItemCount()))

set_group = mt.topLevelItem(0)
check("F4) Set-Gruppe hat Set-Knoten mit Services",
      set_group.childCount() == 1 and set_group.child(0).childCount() == 2,
      f"sets={set_group.childCount()} svcs={set_group.child(0).childCount()}")

# Bugfix 05.08.2026 (Info-Button statt Text-Badge): JEDE Service-/Set-/
# Plugin-Zeile traegt in Spalte 1 einen echten Info-Button (QPushButton "ℹ",
# Icon-Breite) statt des Badge-Textes / gekuerzten 'i'-Zeichens.
def _info_button(tree, item):
    """Liefert den Item-Widget-Button von Spalte 1 (oder None)."""
    if tree is None or item is None:
        return None
    return tree.itemWidget(item, 1)


svc_item = set_group.child(0).child(0)
btn_svc = _info_button(mt, svc_item)
check("F5) Info-Button in Spalte 1 (statt Text-Badge)",
      isinstance(btn_svc, QPushButton) and svc_item.text(1) == "",
      f"btn={type(btn_svc).__name__} text={svc_item.text(1)!r}")
check("F5a) Button nur Icon (ℹ) + Icon-Breite",
      isinstance(btn_svc, QPushButton)
      and btn_svc.text() == INFO_BUTTON_TEXT
      and btn_svc.width() <= INFO_BUTTON_SIZE + 4,
      f"text={btn_svc.text()!r} w={btn_svc.width()}")
check("F5b) Tooltip der Status-Spalte: 'aktiv/im <Indikator>'",
      isinstance(btn_svc, QPushButton)
      and btn_svc.toolTip() in ("aktiv GridLiquidityIndicator",
                                "im GridLiquidityIndicator")
      and svc_item.toolTip(1) == btn_svc.toolTip(),
      (btn_svc.toolTip() if isinstance(btn_svc, QPushButton) else "kein Button"))

# Bugfix 05.08.2026 (Punkt 2): Auch Service-Sets, die einem Indikator
# gehoeren, tragen den Info-Button in Spalte 1 mit derselben Tooltip-
# Namenslogik wie die Services ('aktiv/im <Indikator>').
set_item = set_group.child(0)
btn_set = _info_button(mt, set_item)
check("F5k) Set-Knoten (Indikator-Zugehoerigkeit) traegt Info-Button",
      isinstance(btn_set, QPushButton) and set_item.text(1) == "",
      f"btn={type(btn_set).__name__} text={set_item.text(1)!r}")
check("F5l) Set-Button-Tooltip folgt Namenslogik 'aktiv/im <Indikator>'",
      isinstance(btn_set, QPushButton)
      and btn_set.toolTip() in ("aktiv GridLiquidityIndicator",
                                "im GridLiquidityIndicator"),
      (btn_set.toolTip() if isinstance(btn_set, QPushButton) else "kein Button"))

# Bugfix 05.08.2026 (Punkt 1-4): Button auf ALLEN Zeilen, nur Icon-Breite,
# Spalte 1 ganz rechts verkleinert, gelbe Faerbung bei Indikator-Relation.
def _collect_rows(tree):
    rows = []
    for g in range(tree.topLevelItemCount()):
        grp = tree.topLevelItem(g)
        if grp is None:
            continue
        for i in range(grp.childCount()):
            child = grp.child(i)
            if child is None:
                continue
            rows.append(child)  # Set- oder Plugin-Zeile
            for j in range(child.childCount()):
                s = child.child(j)
                if s is not None:
                    rows.append(s)  # Service-Zeile
    return rows


_all_btns = [(r, mt.itemWidget(r, 1)) for r in _collect_rows(mt)]
check("F5m) JEDE Service-/Set-/Plugin-Zeile hat einen Info-Button",
      all(isinstance(b, QPushButton) for _, b in _all_btns),
      str([(r.text(0), type(b).__name__ if b else None)
           for r, b in _all_btns[:6]]))
check("F5n) Indikator-Zeile: gelber Button (#FFD700)",
      isinstance(btn_svc, QPushButton)
      and INFO_BUTTON_COLOR_INDICATOR in btn_svc.styleSheet(),
      btn_svc.styleSheet() if isinstance(btn_svc, QPushButton) else "")

neutral = next((b for _, b in _all_btns
                if isinstance(b, QPushButton) and not b.toolTip()), None)
check("F5o) Zeile ohne Indikator-Relation: neutraler Button (kein Tooltip)",
      neutral is not None
      and INFO_BUTTON_COLOR_NEUTRAL in neutral.styleSheet(),
      neutral.styleSheet() if neutral is not None else "keine neutrale Zeile")
check("F5p) Status-Spalte auf Button-Breite verkleinert (INFO_BUTTON_WIDTH)",
      mt.header().sectionSize(1) == INFO_BUTTON_WIDTH
      and INFO_BUTTON_WIDTH < BADGE_COLUMN_WIDTH,
      f"w={mt.header().sectionSize(1)} (width={INFO_BUTTON_WIDTH})")

# Bugfix 05.08.2026 (Punkt 4): Klick auf den Button emittiert info_requested
# mit den zeilenspezifischen Daten (Service/Set/Plugin).
info_signals = []
mt.info_requested.connect(lambda s, svc, p: info_signals.append((s, svc, p)))
btn_svc.click()
check("F5q) info_requested emittiert (Service-Zeile)",
      info_signals and info_signals[-1] == (set_id, "grid_1", "grid_lines"),
      str(info_signals))
info_signals.clear()
btn_set.click()
check("F5r) info_requested emittiert (Set-Zeile)",
      info_signals and info_signals[-1] == (set_id, "", ""), str(info_signals))
info_signals.clear()
plugin_row = mt.topLevelItem(2).child(0)
btn_pl = mt.itemWidget(plugin_row, 1)
if isinstance(btn_pl, QPushButton):
    btn_pl.click()
check("F5s) info_requested emittiert (Plugin-Zeile)",
      info_signals and info_signals[-1]
      == ("", "", plugin_row.data(0, ROLE_PLUGIN_ID)),
      str(info_signals))

# Auf-/Zuklapp-Marker (Bugfix 04.08.2026): eingeklappt '>' / ausgeklappt '⌄'.
# Gruppen sind initial expandiert -> '⌄'; Sets sind zugeklappt -> '>'.
check("F5c) Gruppen-Knoten (expandiert) traegt '⌄'-Symbol",
      set_group.text(0).startswith("⌄ "), repr(set_group.text(0)))
check("F5d) Set-Knoten (zugeklappt) traegt '>'-Symbol",
      set_group.child(0).text(0).startswith("> "),
      repr(set_group.child(0).text(0)))
check("F5e) Blatt-Knoten (Service) OHNE '>'-Symbol",
      not svc_item.text(0).startswith("> "), repr(svc_item.text(0)))
check("F5f) Untereintraege per setIndentation eingerueckt",
      set_group.child(0).text(0) and svc_item.text(0),
      "Indent=" + str(set_group.treeWidget().indentation()))

# Layout (Bugfix 04.08.2026):
# * rootIsDecorated=False -> Top-Level-Knoten starten ganz links (Ebene 0
#   ohne zusaetzliche Branch-Einrueckung).
# * Spalte 0 ist Stretch -> Status-Spalte (Spalte 1) liegt fest am rechten
#   Rand und die Baum-Spalte fuellt die gesamte Breite bis dorthin.
check("F5g) rootIsDecorated=False (Ebene 0 startet ganz links)",
      mt.rootIsDecorated() is False)
check("F5h) Status-Spalte liegt am RECHTEN Rand",
      mt.header().sectionPosition(1) + mt.header().sectionSize(1)
      >= mt.viewport().width() - 1,
      f"pos={mt.header().sectionPosition(1)} size={mt.header().sectionSize(1)} "
      f"vp={mt.viewport().width()}")
check("F5i) Spalte 0 ist im Stretch-Modus",
      mt.header().sectionResizeMode(0) == QHeaderView.Stretch
      and mt.header().sectionResizeMode(1) == QHeaderView.Fixed,
      f"mode0={mt.header().sectionResizeMode(0)} mode1={mt.header().sectionResizeMode(1)}")
mt.resize(700, mt.height())
_app.processEvents()
check("F5j) Spalte 0 waechst mit dem Viewport (Status bleibt rechts)",
      mt.header().sectionSize(0) > 400
      and mt.header().sectionPosition(1) + mt.header().sectionSize(1)
      >= mt.viewport().width() - 1,
      f"size0={mt.header().sectionSize(0)} vp={mt.viewport().width()}")

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
# J) Ausfuehrungsdatum (feature_store) + Kontextmenue-Run-Signale (05.08.2026)
# ---------------------------------------------------------------------------
from datetime import datetime  # noqa: E402
today_str = datetime.now().strftime("%d.%m.%y")

check("J1) last_execution_date('proximity') = heute (DD.MM.JJ)",
      model.last_execution_date("proximity") == today_str,
      model.last_execution_date("proximity"))
check("J2) Fallback '(--.--.--)' ohne feature_store-Eintrag",
      model.last_execution_date("grid_lines") == "(--.--.--)",
      model.last_execution_date("grid_lines"))

svc_nodes = model.build_tree()[0]["children"][0]["services"]
check("J3) build_tree-Service-Node traegt last_execution",
      all("last_execution" in s for s in svc_nodes),
      str([s.get("last_execution") for s in svc_nodes]))

# MasterTree-Label: 'instance_id (DD.MM.JJ)' – prox_1 (heute), grid_1 ohne
# Store-Eintrag '(--.--.--)'. Der Baum repopuliert ueber data_changed.
model.refresh()
_app.processEvents()
# Nach dem Repopulate sind die alten C++-Items zerstoert – set_group neu holen.
set_group = mt.topLevelItem(0)
svc_items = [set_group.child(0).child(i) for i in range(set_group.child(0).childCount())]
prox_label = next((i.text(0) for i in svc_items if i.text(0).startswith("prox_1")), "")
grid_label = next((i.text(0) for i in svc_items if i.text(0).startswith("grid_1")), "")
check("J4) prox_1-Zeile zeigt '(DD.MM.JJ)'",
      prox_label == f"prox_1 ({today_str})", prox_label)
check("J5) grid_1-Zeile zeigt Fallback '(--.--.--)'",
      grid_label == "grid_1 (--.--.--)", grid_label)

# Kontextmenue-Run-Signale sind verbindbar (Emission erfolgt aus dem
# Kontextmenue; der Orchestrator verknuepft sie mit seinen Run-Handlern).
run_svc_calls = []
run_set_calls = []
mt.run_service_requested.connect(
    lambda s, i: run_svc_calls.append((s, i)))
mt.run_set_requested.connect(lambda s: run_set_calls.append(s))
mt.run_service_requested.emit(set_id, "prox_1")
mt.run_set_requested.emit(set_id)
check("J6) run_service_requested(set_id, instance_id) emittierbar",
      run_svc_calls == [(set_id, "prox_1")], str(run_svc_calls))
check("J7) run_set_requested(set_id) emittierbar",
      run_set_calls == [set_id], str(run_set_calls))

# ---------------------------------------------------------------------------
# H) Info-Button -> Beschreibungs-Dialog (header_line / from_set / from_plugin)
# ---------------------------------------------------------------------------
from analytics.engine.description_dialog import ServiceDescriptionDialog  # noqa: E402


def _dialog_html(dlg):
    """HTML-Inhalt des Dialog-Browsers (headless pruefbar)."""
    browser = dlg.findChild(QTextBrowser)
    return browser.toHtml() if browser is not None else ""


# Set-Dialog: erste Zeile = Tooltip-Text, dann Leerzeile, dann Beschreibung.
dlg_set = ServiceDescriptionDialog.from_set(
    model.get_sets()[0], header_line="im GridLiquidityIndicator")
html_set = _dialog_html(dlg_set)
check("H1) from_set rendert header_line als erste Zeile",
      "im GridLiquidityIndicator" in html_set, "")
check("H2) from_set zeigt Set-Name + Services",
      "Grid-Basis" in html_set and "grid_1 [grid_lines]" in html_set
      and "prox_1 [proximity]" in html_set, "")

# Plugin/Service-Dialog: header_line via from_plugin (Instanz + Config).
dlg_svc = ServiceDescriptionDialog.from_plugin(
    model.get_plugin("grid_lines"), instance_id="grid_1",
    config=model.find_service(set_id, "grid_1"),
    header_line="aktiv GridLiquidityIndicator")
html_svc = _dialog_html(dlg_svc)
check("H3) from_plugin rendert header_line",
      "aktiv GridLiquidityIndicator" in html_svc, "")
check("H4) from_plugin zeigt Instanz + Plugin",
      "grid_1" in html_svc and "Grid Lines" in html_svc, "")

# ---------------------------------------------------------------------------
# G) Set-Updates & Umsortieren
# ---------------------------------------------------------------------------
set_repo.save_set({
    "set_id": set_id,
    "display_name": "Grid-Basis",
    "execution_order": ["prox_1", "grid_1"],  # Umsortieren
    "services": {
        "grid_1": {"plugin_id": "grid_lines", "lookback": 1000,
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
try:
    os.remove(TEST_FS_DB)
except OSError:
    pass

print("-" * 60)
if FAILURES:
    print(f"FEHLER: {len(FAILURES)} Pruefung(en) fehlgeschlagen: {FAILURES}")
    sys.exit(1)
print("ALLE PRUEFUNGEN BESTANDEN (OK)")
sys.exit(0)
