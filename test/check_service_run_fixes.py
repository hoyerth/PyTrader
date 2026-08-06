# test/check_service_run_fixes.py
# Headless-Validierung der beiden Service-Run-Bugfixes (05.08.2026):
#
#   Bugfix 1: "ausfuehren service proximity -> fertig (kein Feature-Store-
#             Payload)". UI-angelegte Sets speichern KEIN depends_on. Die
#             Worker-Aufbereitung prepare_worker_definition() loest die
#             implizite Abhaengigkeit proximity -> grid_lines anhand der
#             Plugin-dependencies auf (naechste VORHERIGE Instanz in
#             execution_order). Explizit gesetzte depends_on bleiben unveraendert.
#
#   Bugfix 2: "Scanner-Candles (max) aus den App-Optionen als max Lookback
#             fuer ALLE Services". prepare_worker_definition() ueberschreibt
#             den Service-lookback mit scanner_candle_limit (statt des
#             gespeicherten 1000). Der Worker laedt OHLCV mit
#             settings.scanner_candle_limit statt feature_builder_limit.
#
# KEINE UI-/DB-Tests: reine Logik auf synthetischen DataFrames (kein Schreiben
# in data/), Evaluator-Pfad ohne Feature-Store-Persistenz.
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

ok = True
failures = []


def check(cond, msg):
    global ok
    if cond:
        print(f"   ✅ {msg}")
    else:
        ok = False
        failures.append(msg)
        print(f"   ❌ {msg}")


def main() -> int:
    global ok
    print("=" * 70)
    print("Service-Run-Bugfixes (depends_on-Aufloesung + Scanner-Lookback)")
    print("=" * 70)

    from serviceui.service_set_utils import prepare_worker_definition
    from analytics.features.definitions.proximity_service import ProximityService

    # ---------------------------------------------------------------- [1]
    print("\n[1] ProximityService.dependencies deklariert grid_lines:")
    svc = ProximityService()
    check(svc.dependencies == ["grid_lines"],
          f"ProximityService.dependencies == ['grid_lines'] (ist {svc.dependencies})")

    # ---------------------------------------------------------------- [2]
    print("\n[2] prepare_worker_definition – depends_on-Aufloesung:")
    definition = {
        "set_id": "s1",
        "display_name": "UI-Set",
        "execution_order": ["grid_lines", "proximity"],
        "services": {
            "grid_lines": {"plugin_id": "grid_lines", "lookback": 1000,
                           "params": {"step_size": 0.5}},
            "proximity": {"plugin_id": "proximity", "lookback": 500,
                          "params": {"visit_pct": 0.05}},
        },
    }
    prepared = prepare_worker_definition(definition, 100_000)

    # Original bleibt unveraendert (Kopie)
    check(definition["services"]["proximity"].get("depends_on") is None,
          "Original-Definition unveraendert (kein depends_on nachgetragen)")
    # proximity erhaelt implizites depends_on auf die VORHERIGE grid_lines-Instanz
    deps = (prepared["services"]["proximity"] or {}).get("depends_on")
    check(deps == ["grid_lines"],
          f"proximity.depends_on automatisch auf ['grid_lines'] (ist {deps})")
    # grid_lines (ohne dependencies) bekommt KEIN depends_on
    check("depends_on" not in (prepared["services"]["grid_lines"] or {}),
          "grid_lines ohne depends_on (keine Upstream-Plugins)")

    # Lookback-Override fuer ALLE Services
    lb_p = (prepared["services"]["proximity"] or {}).get("lookback")
    lb_g = (prepared["services"]["grid_lines"] or {}).get("lookback")
    check(lb_p == 100_000 and lb_g == 100_000,
          f"Lookback-Override auf 100000 fuer alle Services (prox={lb_p}, grid={lb_g})")

    # ---------------------------------------------------------------- [3]
    print("\n[3] Explizites depends_on bleibt unveraendert:")
    indi_def = {
        "set_id": "ind_fixed_grid_proximity_internal",
        "execution_order": ["grid_1", "prox_1"],
        "services": {
            "grid_1": {"plugin_id": "grid_lines", "lookback": 1000, "params": {}},
            "prox_1": {"plugin_id": "proximity", "lookback": 1000,
                       "depends_on": ["grid_1"], "params": {}},
        },
    }
    prep2 = prepare_worker_definition(indi_def, 50_000)
    check((prep2["services"]["prox_1"] or {}).get("depends_on") == ["grid_1"],
          "explizites depends_on ['grid_1'] nicht ueberschrieben")

    # ---------------------------------------------------------------- [4]
    print("\n[4] End-to-End: Evaluator-Pipeline (depends_on-Aufloesung aktiv):")
    from analytics.engine.set_evaluator import ServiceSetEvaluator
    from analytics.features.plugins.base_plugin import PluginContext

    # Synthetische OHLCV: 5 M1-Bars um 30.0 -> Grid-Level 30.0 wird getroffen
    base = 1600000000
    df = pd.DataFrame({
        "time": [base + i * 60 for i in range(5)],
        "open": [30.0] * 5,
        "high": [30.02] * 5,
        "low": [29.98] * 5,
        "close": [30.0] * 5,
    })
    df_plugin = df.copy()
    df_plugin["time"] = df_plugin["time"].astype(int)

    evaluator = ServiceSetEvaluator()
    ctx = PluginContext(symbol="SILVER", timeframe="M1", mode="batch")
    results = evaluator.execute_set(prepared, df_plugin, context=ctx)

    prox_res = results.get("proximity") or {}
    fsp = prox_res.get("feature_store_payload") or {}
    records = fsp.get("records") or []
    check(bool(records), f"proximity liefert Feature-Store-Records (n={len(records)})")
    check(fsp.get("feature_id") == "proximity",
          f"feature_id='proximity' (ist {fsp.get('feature_id')})")
    check(bool(fsp.get("metadata", {}).get("depends_on")),
          f"metadata.depends_on im Payload gesetzt (ist {fsp.get('metadata', {}).get('depends_on')})")
    grid_res = results.get("grid_lines") or {}
    grid_recs = (grid_res.get("feature_store_payload") or {}).get("records") or []
    check(len(grid_recs) == 5, f"grid_lines Records ueber 5 Bars (n={len(grid_recs)})")

    # ---------------------------------------------------------------- [5]
    print("\n[5] Worker-Load-Limit nutzt scanner_candle_limit (Code-Inspektion):")
    rw_src = (Path(__file__).resolve().parent.parent / "serviceui" / "run_worker.py").read_text(
        encoding="utf-8", errors="replace")
    check("limit=settings.scanner_candle_limit" in rw_src,
          "run_worker.py: load_ohlcv mit scanner_candle_limit")
    check("prepare_worker_definition" in rw_src,
          "run_worker.py ruft prepare_worker_definition() auf")

    print()
    if ok:
        print("RESULT: ALLE CHECKS BESTANDEN ✅")
        return 0
    print(f"RESULT: {len(failures)} CHECK(S) FEHLGESCHLAGEN ❌")
    for f in failures:
        print(f"   - {f}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
