# test/check_p14_s5_trash.py
"""
Phase 14 P14-05 – Headless Validierung (KEINE UI, KEIN exec_()).

Prueft das Papierkorb- & Snapshot-System (Soft-Delete & Deterministische
Snapshots) im ServiceSetRepository:

A) Deterministische Snapshot-Historie (Invariante 9):
   - Neuanlage eines Sets erzeugt KEINEN Snapshot (service_set_history leer).
   - Ueberschreiben eines BEREITS EXISTIERENDEN Sets erzeugt GENAU 1 Snapshot
     mit fortlaufender Version (version = Zaehler je set_id).

B) Soft-Delete (service_sets_trash):
   - delete_set(set_id) verschiebt das Set in den Papierkorb:
       * list_sets() enthaelt das Set NICHT mehr,
       * list_trash() enthaelt es MIT deleted_at-Zeitstempel,
       * display_name/definition bleiben vollstaendig erhalten.

C) Wiederherstellung (restore_set_from_trash):
   - Set ist danach wieder in list_sets() (vollstaendige Definition),
   - list_trash() enthaelt es nicht mehr.

D) Endgueltiges Loeschen (purge_trash_set / purge_trash):
   - purge_trash_set entfernt EIN Set unwiderruflich (liefert bool).
   - purge_trash leert den gesamten Papierkorb (liefert Anzahl).

Test-DB liegt im Unterordner test/ (Regel: keine Test-DBs im Root/data).
"""
import os
import sys

sys.path.insert(0, r"F:\Python\PyTrader")

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "p14_s5_trash_test.duckdb")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

from analytics.engine.service_set_repository import ServiceSetRepository  # noqa: E402
from db_service import DbPool  # noqa: E402

FAILURES: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def count_history(repo: ServiceSetRepository, set_id: str) -> int:
    con = DbPool.get(repo.db_path)
    res = con.execute(
        "SELECT COUNT(*) FROM service_set_history WHERE set_id = ?", [set_id]
    ).fetchone()
    return int(res[0]) if res and res[0] else 0


def count_trash(repo: ServiceSetRepository) -> int:
    return len(repo.list_trash())


def count_sets(repo: ServiceSetRepository) -> int:
    return len(repo.list_sets())


def trash_table_exists(repo: ServiceSetRepository) -> bool:
    con = DbPool.get(repo.db_path)
    res = con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
        "AND name='service_sets_trash'"
    ).fetchone()
    return bool(res and res[0] and res[0] > 0)


# ---------------------------------------------------------------------------
# Fixture: Repository mit frischer Test-DB
# ---------------------------------------------------------------------------
repo = ServiceSetRepository(db_path=TEST_DB)

base_def = {
    "set_id": "set-alpha",
    "display_name": "Alpha Scalper",
    "description": "Erstes Testset",
    "execution_order": ["grid_1", "prox_1"],
    "services": {
        "grid_1": {"plugin_id": "grid_lines", "lookback": 1000, "params": {}},
        "prox_1": {"plugin_id": "proximity", "lookback": 1000, "params": {}},
    },
}

# ---------------------------------------------------------------------------
# A) Deterministische Snapshot-Historie (Invariante 9)
# ---------------------------------------------------------------------------
check("A1) Tabellen angelegt (service_sets_trash)",
      trash_table_exists(repo))

# --- Neuanlage: KEIN Snapshot ---
set_id = repo.save_set(dict(base_def))
check("A2) Neuanlage liefert set_id", set_id == "set-alpha", set_id)
check("A3) Neuanlage erzeugt KEINEN Snapshot",
      count_history(repo, set_id) == 0, str(count_history(repo, set_id)))

# --- Ueberschreiben: GENAU 1 Snapshot (mit Version 1) ---
changed = dict(base_def)
changed["display_name"] = "Alpha Scalper v2"
repo.save_set(changed)
check("A4) Ueberschreiben erzeugt GENAU 1 Snapshot",
      count_history(repo, set_id) == 1, str(count_history(repo, set_id)))
con = DbPool.get(repo.db_path)
hist = con.execute(
    "SELECT version, definition FROM service_set_history WHERE set_id = ?",
    [set_id],
).fetchall()
check("A5) Snapshot-Version laeuft (Version 1)",
      hist and str(hist[0][0]) == "1", str(hist[0][0]) if hist else "keine")
check("A6) Snapshot sichert ALTEN Stand (display_name 'Alpha Scalper')",
      hist and "Alpha Scalper" in str(hist[0][1]),
      str(hist[0][1])[:80] if hist else "keine")

# --- Erneutes Ueberschreiben: GENAU 2 Snapshots (Version 1, 2) ---
changed["description"] = "Zweites Ueberschreiben"
repo.save_set(changed)
check("A7) 2. Ueberschreiben -> 2 Snapshots, Version fortlaufend",
      count_history(repo, set_id) == 2, str(count_history(repo, set_id)))
hist2 = con.execute(
    "SELECT version FROM service_set_history WHERE set_id = ? ORDER BY version",
    [set_id],
).fetchall()
check("A8) Versionsfolge 1,2",
      [str(r[0]) for r in hist2] == ["1", "2"],
      str([str(r[0]) for r in hist2]))

# --- Interner Schreibvorgang (record_snapshot=False): KEIN Snapshot ---
repo.save_set(changed, record_snapshot=False)
check("A9) record_snapshot=False erzeugt KEINEN Snapshot",
      count_history(repo, set_id) == 2, str(count_history(repo, set_id)))

# ---------------------------------------------------------------------------
# B) Soft-Delete (Papierkorb)
# ---------------------------------------------------------------------------
repo.delete_set(set_id)
check("B1) Set nach Soft-Delete NICHT in list_sets()",
      all(s.get("set_id") != set_id for s in repo.list_sets()))
trash = repo.list_trash()
check("B2) Set in list_trash()",
      any(t.get("set_id") == set_id for t in trash))
trash_item = next(t for t in trash if t.get("set_id") == set_id)
check("B3) Trash-Eintrag behaelt display_name",
      trash_item.get("display_name") == "Alpha Scalper v2",
      str(trash_item.get("display_name")))
check("B4) Trash-Eintrag behaelt description",
      trash_item.get("description") == "Zweites Ueberschreiben",
      str(trash_item.get("description")))
check("B5) Trash-Eintrag hat deleted_at",
      bool(trash_item.get("deleted_at")), str(trash_item.get("deleted_at")))
check("B6) Trash-Eintrag behaelt execution_order",
      trash_item.get("execution_order") == ["grid_1", "prox_1"],
      str(trash_item.get("execution_order")))
check("B7) Trash-Eintrag behaelt services",
      bool(trash_item.get("services")) and "grid_1" in (trash_item.get("services") or {}))
check("B8) Aktive Sets unveraendert (0 aktiv, 1 im Papierkorb)",
      count_sets(repo) == 0 and count_trash(repo) == 1,
      f"sets={count_sets(repo)} trash={count_trash(repo)}")

# --- Doppel-Soft-Delete: kein Duplikat, Zeitstempel aktualisiert ---
repo.delete_set(set_id)
check("B9) Erneutes Soft-Delete erzeugt KEIN Duplikat",
      count_trash(repo) == 1, str(count_trash(repo)))

# ---------------------------------------------------------------------------
# C) Wiederherstellung (restore_set_from_trash)
# ---------------------------------------------------------------------------
ok = repo.restore_set_from_trash(set_id)
check("C1) restore liefert True", ok)
check("C2) Set wieder in list_sets()",
      any(s.get("set_id") == set_id for s in repo.list_sets()))
check("C3) Trash danach leer (fuer dieses Set)",
      not any(t.get("set_id") == set_id for t in repo.list_trash()))
restored = next(s for s in repo.list_sets() if s.get("set_id") == set_id)
check("C4) Wiederhergestelltes Set: display_name erhalten",
      restored.get("display_name") == "Alpha Scalper v2",
      str(restored.get("display_name")))
check("C5) Wiederhergestelltes Set: description erhalten",
      restored.get("description") == "Zweites Ueberschreiben",
      str(restored.get("description")))
check("C6) Wiederhergestelltes Set: services erhalten",
      (restored.get("services") or {}).get("grid_1", {}).get("plugin_id") == "grid_lines")
check("C7) restore von unbekannter set_id liefert False",
      repo.restore_set_from_trash("gibts-nicht") is False)

# ---------------------------------------------------------------------------
# D) Endgueltiges Loeschen (purge_trash_set / purge_trash)
# ---------------------------------------------------------------------------
# Nochmals soft-deleten, dann ENDGUELTIG loeschen
repo.delete_set(set_id)
repo.delete_set(repo.save_set({
    "set_id": "set-beta", "display_name": "Beta Set",
    "execution_order": ["ema_1"],
    "services": {"ema_1": {"plugin_id": "ema_atr_set_v1", "lookback": 500, "params": {}}},
}))
check("D1) 2 Sets im Papierkorb", count_trash(repo) == 2, str(count_trash(repo)))

check("D2) purge_trash_set liefert True",
      repo.purge_trash_set("set-alpha") is True)
check("D3) purge_trash_set entfernt das Set unwiderruflich",
      not any(t.get("set_id") == "set-alpha" for t in repo.list_trash())
      and count_trash(repo) == 1)
check("D4) purge_trash_set auf unbekannte set_id liefert False",
      repo.purge_trash_set("set-alpha") is False)

count = repo.purge_trash()
check("D5) purge_trash liefert Anzahl entfernte Sets (1)",
      count == 1, str(count))
check("D6) Papierkorb nach purge_trash leer",
      count_trash(repo) == 0 and not repo.list_trash())
check("D7) Papierkorb nach purge_trash NICHT wiederherstellbar",
      repo.restore_set_from_trash("set-beta") is False)

# ---------------------------------------------------------------------------
print("-" * 60)
if FAILURES:
    print(f"FEHLER: {len(FAILURES)} Pruefung(en) fehlgeschlagen: {FAILURES}")
    sys.exit(1)
print("ALLE PRUEFUNGEN BESTANDEN (OK)")
sys.exit(0)
