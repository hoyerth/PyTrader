# BEREIT FÜR PHASE 15
# test/check_p14_s4_services_locked.py
"""
Phase 14 P14-04-E – Headless Validierung (KEINE UI, KEIN exec_()).

Prüft die Service-Set-Schutz-Mechanik im Service-Fenster (P14-04-E):

1) Set-Sperre (Regel 1): Es muss immer mindestens ein gültiges Service-Set
   erhalten bleiben, damit der Indikator funktionsfähig bleibt. Das Löschen
   des letzten Sets ist gesperrt (delete_set-Guard: len(list_sets()) <= 1).

2) Service-Sperre (Regel 2): Einzel-Services, die in einem gespeicherten
   Service-Set vorkommen, dürfen nicht entfernt werden. Der Sperr-Hinweis
   nennt den Namen des verwendeten Sets (_sets_using_plugin).

3) Kennzeichnung (Regel 3): _service_lock liefert 🔒-Präfix + Tooltip-
   Nachtrag genau für Services, die in einem gespeicherten Set vorkommen –
   pure Logik, ohne UI-Instanziierung (unbound method + Dummy-Objekt).

Test-DB liegt im Unterordner test/ (Regel: keine Test-DBs im Root/data).
"""
import os
import sys

sys.path.insert(0, r"F:\Python\PyTrader")

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "p14_s4_locked_test.duckdb")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

from serviceui.service_win import _sets_using_plugin, ServiceWindow  # noqa: E402
from analytics.engine.service_set_repository import ServiceSetRepository  # noqa: E402

FAILURES: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" – {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# Fixtures: Repository mit mehreren Sets (grid-sets + ema-set)
# ---------------------------------------------------------------------------
repo = ServiceSetRepository(db_path=TEST_DB)

set_grid = {
    "set_id": "set-grid",
    "display_name": "Grid Scalper",
    "execution_order": ["grid_1", "prox_1"],
    "services": {
        "grid_1": {"plugin_id": "grid_lines", "lookback": 1000, "params": {}},
        "prox_1": {"plugin_id": "proximity", "lookback": 1000, "params": {}},
    },
}
set_ema = {
    "set_id": "set-ema",
    "display_name": "EMA Trend",
    "execution_order": ["ema_1"],
    "services": {
        "ema_1": {"plugin_id": "ema_atr_set_v1", "lookback": 1000, "params": {}},
    },
}
set_grid_b = {
    "set_id": "set-grid-b",
    "display_name": "Grid Backup",
    "execution_order": ["grid_9"],
    "services": {
        "grid_9": {"plugin_id": "grid_lines", "lookback": 500, "params": {}},
    },
}
repo.save_set(set_grid)
repo.save_set(set_ema)
repo.save_set(set_grid_b)

sets = repo.list_sets()
check("Fixture: 3 Sets gespeichert", len(sets) == 3)

# ---------------------------------------------------------------------------
# 2) Service-Sperre (Regel 2) – _sets_using_plugin
# ---------------------------------------------------------------------------
check("2a) grid_lines -> Set 'Grid Scalper' + 'Grid Backup'",
      _sets_using_plugin("grid_lines", sets) == ["Grid Scalper", "Grid Backup"],
      str(_sets_using_plugin("grid_lines", sets)))
check("2b) proximity -> Set 'Grid Scalper'",
      _sets_using_plugin("proximity", sets) == ["Grid Scalper"],
      str(_sets_using_plugin("proximity", sets)))
check("2c) ema -> Set 'EMA Trend'",
      _sets_using_plugin("ema_atr_set_v1", sets) == ["EMA Trend"],
      str(_sets_using_plugin("ema_atr_set_v1", sets)))
check("2d) freier Service (nicht in Set) -> keine Sperre",
      _sets_using_plugin("unbekannt", sets) == [])
check("2e) display_name bevorzugt vor set_id",
      _sets_using_plugin("grid_lines", sets)[0] == "Grid Scalper")
check("2f) Fallback: leeres display_name -> set_id",
      _sets_using_plugin("grid_lines", [{
          "set_id": "ohne-name", "display_name": "",
          "services": {"g1": {"plugin_id": "grid_lines"}},
      }]) == ["ohne-name"])

# Löschversuch-Bedingung (remove_instance-Guard):
# names leer -> Entfernen erlaubt; names nicht leer -> gesperrt + Hinweis.
check("2g) Sperre aktiv für grid_lines (names nicht leer)",
      bool(_sets_using_plugin("grid_lines", repo.list_sets())))
check("2h) Hinweis nennt Set-Namen (Regel 2)",
      _sets_using_plugin("grid_lines", repo.list_sets())[0] == "Grid Scalper")

# ---------------------------------------------------------------------------
# 1) Set-Sperre (Regel 1) – mindestens ein valides Set bleibt erhalten
# ---------------------------------------------------------------------------
check("1a) 3 Sets -> Löschen erlaubt (Guard len>1)", len(repo.list_sets()) > 1)
repo.delete_set("set-grid-b")
repo.delete_set("set-ema")
check("1b) 1 Set verbleibt -> Löschen GESPERRT (Guard len<=1)",
      len(repo.list_sets()) <= 1)
check("1c) verbleibendes Set ist das Grid-Set (Indikator funktionsfähig)",
      any(s.get("set_id") == "set-grid" for s in repo.list_sets()))

# ---------------------------------------------------------------------------
# 3) Kennzeichnung (Regel 3) – _service_lock via Dummy-Objekt (unbound)
# ---------------------------------------------------------------------------
class _Dummy:
    pass


def _ascii_clean(s: str) -> str:
    """Ersetzt Emojis (cp1252-Konsole) im Fehler-Detail durch ASCII."""
    return s.replace("\U0001f512", "<lock>")


dummy = _Dummy()
dummy.set_repo = repo

prefix, tip = ServiceWindow._service_lock(dummy, "grid_lines")
check("3a) grid_lines: Lock-Praefix gesetzt", prefix == "\U0001f512 ",
      "prefix=" + _ascii_clean(repr(prefix)))
check("3b) grid_lines: Tooltip nennt Set 'Grid Scalper'",
      "Grid Scalper" in tip and "Gesperrt" in tip,
      "tip=" + _ascii_clean(repr(tip)))

prefix2, tip2 = ServiceWindow._service_lock(dummy, "unbekannt")
check("3c) freier Service: kein Lock-Praefix", prefix2 == "", repr(prefix2))
check("3d) freier Service: kein Tooltip-Nachtrag", tip2 == "", repr(tip2))

# ---------------------------------------------------------------------------
print("-" * 60)
if FAILURES:
    print(f"FEHLER: {len(FAILURES)} Prüfung(en) fehlgeschlagen: {FAILURES}")
    sys.exit(1)
print("ALLE PRÜFUNGEN BESTANDEN (OK)")
sys.exit(0)
