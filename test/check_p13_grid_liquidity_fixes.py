# test/check_p13_grid_liquidity_fixes.py
# Headless-Validierung für Phase 13 5.5 (3 Bugfixes am grid_liquidity-Indikator)
#
# Bugfix #1: Änderungen in 'Anzeige' ODER 'Service-Parameter' werden SOFORT auf
#            dem Chart umgesetzt. Der Dialog liefert im Payload zusätzlich
#            logic_params (Live-Overlay der Service-Parameter); chart_win
#            speichert sie im indicators_state und _resolve_indicator_params
#            überlagert die Set-Logik damit.
# Bugfix #2: prox_level1-6 müssen Nachkommastellen ermöglichen (step 0.01 im
#            Schema + _decimal_places-Minimum 2 für Floats).
# Bugfix #3: Beim Restore/Neuaufbau von chart_win wird die zuletzt gewählte
#            set_id an den Dialog übergeben (Set-Combo vorbelegt) und die
#            Service-Params (Set-Logik + Live-Overlay + Preset-logic_params)
#            werden sauber wiederhergestellt.
#
# WICHTIG: Keine GUI-Ausführung. Offscreen-QApplication; chart_win-Logik über
# object.__new__-Objekte (kein QWebEngineView nötig). Echte app_data.duckdb
# bleibt unberührt (temporäre DBs).
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import py_compile

from analytics.engine.service_set_repository import ServiceSetRepository

ok = True
failures = []


def check(cond, msg):
    global ok
    if cond:
        print(f"   \u2705 {msg}")
    else:
        ok = False
        failures.append(msg)
        print(f"   \u274c {msg}")


class FakeStateManager:
    """StateManager-Fake für den Dialog (Presets, Geometrie, keine DB)."""

    def __init__(self):
        self.saved_presets: dict = {}
        self.presets: list = ["Default"]

    def get_dialog_geometry(self, *a, **k):
        return None

    def save_dialog_geometry(self, *a, **k):
        pass

    def list_indicator_presets(self, *a, **k):
        return list(self.presets)

    def get_indicator_preset(self, indicator_id, name):
        return self.saved_presets.get(name)

    def save_indicator_preset(self, indicator_id, name, payload):
        self.saved_presets[name] = payload
        if name not in self.presets:
            self.presets.append(name)

    def delete_indicator_preset(self, *a, **k):
        pass


class FakePlugin:
    """grid_liquidity-artiges Plugin inkl. prox_level1-6 (Bugfix #2)."""

    plugin_id = "grid_liquidity"
    indicator_id = "grid_liquidity"
    display_name = "Grid Liquidity (Plugin)"
    param_options = {}
    version = "1.0.0"
    metadata = {"display_name": "Grid Liquidity", "description": "D", "author": "A"}

    base_parameter_schema = {
        "lookback": {"type": "int", "default": 1000, "min": 100, "max": 100000,
                     "step": 50, "expert": True},
    }
    parameter_schema = {
        # Reine Darstellung (display_params)
        "show_lines": {"type": "bool", "default": True},
        "show_circles": {"type": "bool", "default": True},
        "line_color": {"type": "color", "default": "#2196F3"},
        "circle_color_std": {"type": "color", "default": "#FFEB3B"},
        "circle_color_active": {"type": "color", "default": "#E91E63"},
        # Berechnungslogik (lebt im Service-Set / als Live-Overlay)
        "grid_step": {"type": "float", "default": 0.5, "min": 0.01, "max": 100.0,
                      "step": 0.05},
        "proximity_threshold": {"type": "float", "default": 0.05, "min": 0.001,
                                "max": 10.0, "step": 0.005},
        "use_time_filter": {"type": "bool", "default": True},
        "time_window_mins": {"type": "int", "default": 5, "min": 0, "max": 30},
        # Custom-Level: Nachkommastellen via step 0.01 (Bugfix #2)
        "prox_level1": {"type": "float", "default": 0.0, "min": 0.0,
                        "max": 100000.0, "step": 0.01},
        "prox_level2": {"type": "float", "default": 0.0, "min": 0.0,
                        "max": 100000.0, "step": 0.01},
        "prox_level3": {"type": "float", "default": 0.0, "min": 0.0,
                        "max": 100000.0, "step": 0.01},
        "prox_level4": {"type": "float", "default": 0.0, "min": 0.0,
                        "max": 100000.0, "step": 0.01},
        "prox_level5": {"type": "float", "default": 0.0, "min": 0.0,
                        "max": 100000.0, "step": 0.01},
        "prox_level6": {"type": "float", "default": 0.0, "min": 0.0,
                        "max": 100000.0, "step": 0.01},
    }
    parameter_order = [
        "show_lines", "show_circles",
        "line_color", "circle_color_std", "circle_color_active",
        "grid_step", "proximity_threshold", "use_time_filter", "time_window_mins",
        "prox_level1", "prox_level2", "prox_level3",
        "prox_level4", "prox_level5", "prox_level6",
        "lookback",
    ]
    param_labels = {}

    @property
    def default_params(self):
        d = {k: v["default"] for k, v in self.parameter_schema.items()}
        d.update({k: v["default"] for k, v in self.base_parameter_schema.items()})
        return d


def main() -> int:
    global ok
    print("=" * 70)
    print("Phase 13 5.5 - grid_liquidity Bugfixes #1-#3 (headless)")
    print("=" * 70)

    # [1] py_compile
    print("\n[1] py_compile:")
    for f in ("chart/chart_win.py", "chart/indicator_dialog.py",
              "analytics/features/definitions/grid_liquidity.py"):
        try:
            py_compile.compile(str(ROOT / f), doraise=True)
            check(True, f"{f} kompiliert fehlerfrei")
        except Exception as e:
            check(False, f"py_compile {f}: {e}")

    # [2] Setup (offscreen, temp DB, 2 Sets mit grid_liquidity-Service)
    print("\n[2] Setup (offscreen, temp DB):")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

    QInputDialog.getText = staticmethod(lambda *a, **k: ("MeinFixPreset", True))
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

    app = QApplication.instance() or QApplication(sys.argv)
    check(app is not None, "QApplication (offscreen) erstellt")

    tmp_dir = tempfile.mkdtemp(prefix="p13_55_fixes_")
    tmp_db = os.path.join(tmp_dir, "tmp_app_data.duckdb")
    repo = ServiceSetRepository(db_path=tmp_db)
    repo.save_set({
        "set_id": "set_a",
        "display_name": "Set A",
        "execution_order": ["gl_1"],
        "services": {
            "gl_1": {"plugin_id": "grid_liquidity", "lookback": 1000,
                     "params": {"grid_step": 0.5, "proximity_threshold": 0.05,
                                "use_time_filter": True, "time_window_mins": 5}},
        },
    })
    repo.save_set({
        "set_id": "set_b",
        "display_name": "Set B",
        "execution_order": ["gl_1"],
        "services": {
            "gl_1": {"plugin_id": "grid_liquidity", "lookback": 500,
                     "params": {"grid_step": 0.3, "proximity_threshold": 0.02,
                                "use_time_filter": False, "time_window_mins": 10}},
        },
    })
    check(repo.get_set("set_a") is not None and repo.get_set("set_b") is not None,
          "Service-Sets 'set_a'/'set_b' in Temp-DB gespeichert")

    import chart.indicator_dialog as indicator_dialog
    import chart.chart_win as chart_win

    ind = FakePlugin()
    sm = FakeStateManager()

    def _pump(dlg):
        dlg.show()
        app.processEvents()
        QTimer.singleShot(0, app.quit)
        app.exec()
        app.processEvents()

    # =====================================================================
    # Bugfix #1: Live-Update der Service-Parameter (logic_params-Pfad)
    # =====================================================================
    print("\n[3] Bugfix #1: Service-Param-Änderung erreicht das Chart sofort:")
    captured = {}

    def _cb(p, pr):
        captured["payload"] = p
        captured["preset"] = pr

    dlg = indicator_dialog.IndicatorSettingsDialog(
        ind, dict(ind.default_params), "Default", sm,
        _cb, symbol="SILVER", timeframe="H1", service_set_repo=repo,
    )
    _pump(dlg)
    # Set A auswaehlen -> Set-Logik (grid_step=0.5) in self.params
    dlg.combo_service_set.setCurrentIndex(dlg.combo_service_set.findData("set_a"))
    app.processEvents()
    check(abs(float(dlg.params.get("grid_step", 0)) - 0.5) < 1e-9,
          "Set A geladen: grid_step=0.5 im Dialog")

    # Service-Parameter grid_step auf 0.9 aendern -> Callback + Payload
    spin = dlg.param_controls.get("grid_step")
    check(spin is not None and hasattr(spin, "setValue"), "grid_step-SpinBox vorhanden")
    if spin is not None and hasattr(spin, "setValue"):
        spin.setValue(0.9)
    dlg.on_param_control_changed()
    payload = captured.get("payload") or {}
    check(payload.get("set_id") == "set_a", "Payload set_id == 'set_a'")
    check(abs(float(payload.get("logic_params", {}).get("grid_step", 0)) - 0.9) < 1e-9,
          f"Payload logic_params.grid_step == 0.9 (ist {payload.get('logic_params', {}).get('grid_step')})")
    check(payload.get("logic_params", {}).get("proximity_threshold") is not None,
          "logic_params enthaelt weitere Service-Params (proximity_threshold)")
    check("line_color" not in payload.get("logic_params", {}),
          "logic_params enthaelt KEINE Darstellung (line_color fehlt)")
    check(payload.get("display_params", {}).get("line_color") is not None,
          "display_params enthaelt weiterhin die Darstellung")

    # chart_win: Payload speichern -> Resolver liefert das neue grid_step
    win = chart_win.PyTraderChartWindow.__new__(chart_win.PyTraderChartWindow)
    win._service_set_repo = repo
    win.indicators_state = {}
    win.save_state = lambda: None
    win.render_indicators = lambda: None
    win._on_indicator_params_updated("grid_liquidity", payload, "Default")
    st = win.indicators_state["grid_liquidity"]
    check(abs(float(st.get("logic_params", {}).get("grid_step", 0)) - 0.9) < 1e-9,
          "indicators_state speichert logic_params.grid_step == 0.9")
    merged = win._resolve_indicator_params("grid_liquidity", st)
    check(abs(float(merged.get("grid_step", 0)) - 0.9) < 1e-9,
          f"_resolve_indicator_params liefert grid_step=0.9 (Set sagt 0.5) -> Live-Overlay wirkt")

    # Reine Anzeige-Aenderung (Bugfix #1, Box 'Anzeige'): auch ohne set_id wirkt sie
    win2 = chart_win.PyTraderChartWindow.__new__(chart_win.PyTraderChartWindow)
    win2._service_set_repo = repo
    win2.indicators_state = {}
    win2.save_state = lambda: None
    win2.render_indicators = lambda: None
    win2._on_indicator_params_updated(
        "grid_liquidity",
        {"set_id": "", "logic_params": {"grid_step": 0.7},
         "display_params": {"line_color": "#123456"}},
        "Default",
    )
    merged_noset = win2._resolve_indicator_params(
        "grid_liquidity", win2.indicators_state["grid_liquidity"])
    check(abs(float(merged_noset.get("grid_step", 0)) - 0.7) < 1e-9,
          "Ohne set_id: display+logic_params werden gemergt (grid_step=0.7)")
    check(merged_noset.get("line_color") == "#123456",
          "Ohne set_id: line_color aus display_params gemergt")

    # =====================================================================
    # Bugfix #2: prox_level-SpinBoxen mit Nachkommastellen
    # =====================================================================
    print("\n[4] Bugfix #2: prox_level1-6 mit Nachkommastellen:")
    check(indicator_dialog.IndicatorSettingsDialog._decimal_places(0.0) == 2,
          "_decimal_places(0.0) == 2 (Minimum für Floats)")
    check(indicator_dialog.IndicatorSettingsDialog._decimal_places(0.01) == 2,
          "_decimal_places(0.01) == 2 (aus step)")
    prox_ctrl = dlg.param_controls.get("prox_level1")
    check(prox_ctrl is not None, "prox_level1-Control im Dialog vorhanden")
    if prox_ctrl is not None and hasattr(prox_ctrl, "decimals"):
        dec = prox_ctrl.decimals()
        check(dec >= 2, f"prox_level1-SpinBox hat {dec} Nachkommastellen (>= 2)")
    # Schema-Check: step 0.01 in der echten Definition
    from analytics.features.definitions.grid_liquidity import GridLiquidityFeature
    glf = GridLiquidityFeature()
    schema = glf.parameter_schema
    check(all(schema.get(f"prox_level{i}", {}).get("step") == 0.01 for i in range(1, 7)),
          "Echtes grid_liquidity-Schema: prox_level1-6 haben step=0.01")

    # =====================================================================
    # Bugfix #3: Restore (set_id-Vorbelegung + Service-Params wiederherstellen)
    # =====================================================================
    print("\n[5] Bugfix #3: Restore des Fensters (set_id + Service-Params):")
    # 5a) _open_indicator_settings uebergibt current_set_id (Code-Inspektion)
    src_win = (ROOT / "chart" / "chart_win.py").read_text(encoding="utf-8")
    check("current_set_id=st.get(\"set_id\") or None" in src_win,
          "chart_win._open_indicator_settings uebergibt current_set_id")
    check("logic_params=st.get(\"logic_params\") or None" in src_win,
          "chart_win._open_indicator_settings uebergibt logic_params (Live-Overlay)")

    # 5b) Dialog mit current_set_id='set_a' + getrennt uebergebenem Live-Overlay
    #     (logic_params grid_step=0.9) - exakt so, wie chart_win beim Restore
    #     den Dialog oeffnet: aufgeloeste Params (Set-Logik + Darstellung) und
    #     das gespeicherte Overlay als separaten Parameter.
    restore_params = {
        "grid_step": 0.5, "proximity_threshold": 0.05, "use_time_filter": True,
        "time_window_mins": 5, "lookback": 1000,
        "line_color": "#123456", "show_lines": True, "show_circles": True,
        "circle_color_std": "#FFEB3B", "circle_color_active": "#E91E63",
        "prox_level1": 0.0, "prox_level2": 0.0, "prox_level3": 0.0,
        "prox_level4": 0.0, "prox_level5": 0.0, "prox_level6": 0.0,
    }
    dlg3 = indicator_dialog.IndicatorSettingsDialog(
        ind, dict(restore_params), "Default", sm,
        lambda p, pr: None, symbol="SILVER", timeframe="H1",
        service_set_repo=repo, current_set_id="set_a",
        logic_params={"grid_step": 0.9},
    )
    _pump(dlg3)
    check(dlg3.combo_service_set.currentData() == "set_a",
          "Set-Combo beim Restore vorbelegt (set_a)")
    check(abs(float(dlg3.params.get("grid_step", 0)) - 0.9) < 1e-9,
          f"Restore: grid_step=0.9 (Overlay) bleibt erhalten (ist {dlg3.params.get('grid_step')})")
    check(int(dlg3.params.get("lookback", 0)) == 1000,
          "Restore: lookback=1000 aus Set A (kein Overlay-Fremdwert)")
    check(dlg3.params.get("line_color") == "#123456",
          "Restore: line_color aus display_params erhalten")

    # 5c) Set-Wechsel: Overlay (0.9) bleibt ueber Set B (0.3) erhalten
    dlg3.combo_service_set.setCurrentIndex(dlg3.combo_service_set.findData("set_b"))
    app.processEvents()
    check(abs(float(dlg3.params.get("grid_step", 0)) - 0.9) < 1e-9,
          f"Set-Wechsel: Overlay grid_step=0.9 bleibt (Set B sagt 0.3, ist {dlg3.params.get('grid_step')})")
    check(int(dlg3.params.get("lookback", 0)) == 500,
          "Set-Wechsel: lookback=500 aus Set B geladen")

    # 5d) Preset speichern (enthaelt logic_params) + laden -> Overlay wiederhergestellt
    dlg3.combo_service_set.setCurrentIndex(dlg3.combo_service_set.findData("set_b"))
    app.processEvents()
    spin_b = dlg3.param_controls.get("grid_step")
    if spin_b is not None and hasattr(spin_b, "setValue"):
        spin_b.setValue(0.42)
    dlg3.on_param_control_changed()
    dlg3.save_current_preset()
    saved = sm.saved_presets.get("MeinFixPreset")
    check(saved is not None, "Preset 'MeinFixPreset' gespeichert")
    check(abs(float((saved.get("logic_params") or {}).get("grid_step", 0)) - 0.42) < 1e-9,
          "Gespeichertes Preset enthaelt logic_params.grid_step=0.42")

    dlg4 = indicator_dialog.IndicatorSettingsDialog(
        ind, dict(ind.default_params), "Default", sm,
        lambda p, pr: None, symbol="SILVER", timeframe="H1", service_set_repo=repo,
    )
    _pump(dlg4)
    dlg4.on_preset_selected("MeinFixPreset")
    app.processEvents()
    check(dlg4.combo_service_set.currentData() == "set_b",
          "Preset-Laden: Set-Auswahl 'set_b' wiederhergestellt")
    check(abs(float(dlg4.params.get("grid_step", 0)) - 0.42) < 1e-9,
          f"Preset-Laden: grid_step=0.42 (logic_params) wiederhergestellt (ist {dlg4.params.get('grid_step')})")

    # 5e) chart_win: Restore ruft Dialog mit aufgeloesten Params + set_id auf
    win3 = chart_win.PyTraderChartWindow.__new__(chart_win.PyTraderChartWindow)
    win3._service_set_repo = repo
    win3.indicators_state = {"grid_liquidity": {
        "active": True, "preset": "Default", "set_id": "set_a",
        "logic_params": {"grid_step": 0.9},
        "display_params": {"line_color": "#ABCDEF"},
    }}
    st3 = win3.indicators_state["grid_liquidity"]
    restored = win3._resolve_indicator_params("grid_liquidity", st3)
    check(abs(float(restored.get("grid_step", 0)) - 0.9) < 1e-9,
          "chart_win-Restore: grid_step=0.9 (logic_params ueber Set-Logik 0.5)")
    check(restored.get("line_color") == "#ABCDEF",
          "chart_win-Restore: line_color aus display_params")

    # Aufraeumen
    try:
        os.remove(tmp_db)
        os.rmdir(tmp_dir)
    except Exception:
        pass

    print()
    if ok:
        print("RESULT: ALLE CHECKS BESTANDEN \u2705")
        return 0
    print(f"RESULT: {len(failures)} CHECK(S) FEHLGESCHLAGEN \u274c")
    for f in failures:
        print(f"   - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
