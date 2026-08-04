# test/check_p15_s3_profiles.py
"""
Phase 15 15.03 Schritt 2 – Headless Validierung (KEINE UI, KEIN QApplication).

Prueft das Analytics-Profile-Repository (analytics_profile_repository.py)
rein auf Logik-/DB-Ebene:

A) DB-Schema:
   - analytics_profiles-Tabelle wird angelegt (idempotent).
   - Pflichtfeld schema_version im Payload (Default 1).

B) CRUD:
   - create_profile() legt an, liefert profile_id (uuid4-hex).
   - get_profile() / get_profile_by_name() (case-insensitive).
   - list_profiles() sortiert nach Name.
   - update_profile() (name/description/payload) – nur uebergebene Felder.
   - delete_profile() liefert bool und entfernt.
   - count().

C) Aktives Profil (Explicit Save):
   - set_active() setzt genau EIN aktives Profil (andere auf False).
   - get_active_profile() liefert das aktive.

D) Schema-Konvention:
   - schema_version wird beim create/update additiv ergaenzt (Default 1).
   - Alt-Rows OHNE schema_version erhalten beim Lesen den Default.

Test-DB liegt im Unterordner test/ (Regel: keine Test-DBs im Root/data).
"""
import json
import os
import sys

sys.path.insert(0, r"F:\Python\PyTrader")

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "p15_s3_profiles_test.duckdb")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

from analytics_profile_repository import (  # noqa: E402
    AnalyticsProfileRepository,
    SCHEMA_VERSION_DEFAULT,
)
from db_service import DbPool  # noqa: E402

FAILURES: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


repo = AnalyticsProfileRepository(db_path=TEST_DB)

# ---------------------------------------------------------------------------
# A) DB-Schema
# ---------------------------------------------------------------------------
con = DbPool.get(TEST_DB)
tables = [r[0] for r in con.execute(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_name = 'analytics_profiles'").fetchall()]
check("A1) analytics_profiles-Tabelle angelegt", "analytics_profiles" in tables)

# Idempotenz: zweite Instanz darf nichts zerstoeren
repo2 = AnalyticsProfileRepository(db_path=TEST_DB)
check("A2) _ensure_table() idempotent", repo2.count() == repo.count() == 0)

# ---------------------------------------------------------------------------
# B) CRUD
# ---------------------------------------------------------------------------
pid = repo.create_profile(
    name="Standard",
    payload={"lookback": 5000, "view": "heatmap"},
    description="Default-Profil",
)
check("B1) create_profile liefert profile_id",
      isinstance(pid, str) and len(pid) > 0, str(pid))
check("B2) count() == 1", repo.count() == 1, str(repo.count()))

p = repo.get_profile(pid)
check("B3) get_profile liefert Profil",
      p is not None and p["name"] == "Standard"
      and p["description"] == "Default-Profil")

p_by_name = repo.get_profile_by_name("standard")  # case-insensitive
check("B4) get_profile_by_name case-insensitive",
      p_by_name is not None and p_by_name["profile_id"] == pid)

check("B5) get_profile unbekannt -> None", repo.get_profile("gibtsnicht") is None)
check("B6) get_profile_by_name unbekannt -> None",
      repo.get_profile_by_name("NIX") is None)

# Payload wird korrekt persistiert
p_payload = repo.get_profile(pid)["payload"]
check("B7) Payload persistiert (lookback/view)",
      p_payload.get("lookback") == 5000 and p_payload.get("view") == "heatmap")

# Zweites Profil -> list_profiles sortiert nach Name
pid2 = repo.create_profile(name="Alpha", payload={"view": "scatter"})
profiles = repo.list_profiles()
names = [x["name"] for x in profiles]
check("B8) list_profiles sortiert nach Name",
      names == sorted(names) and len(profiles) == 2, str(names))

# update_profile: nur name
check("B9) update name", repo.update_profile(pid, name="Standard 2") is True)
check("B10) name aktualisiert",
      repo.get_profile(pid)["name"] == "Standard 2")

# update_profile: nur payload (description bleibt)
repo.update_profile(pid, payload={"view": "distribution"})
p_upd = repo.get_profile(pid)
check("B11) payload aktualisiert",
      p_upd["payload"].get("view") == "distribution")
check("B12) description blieb erhalten (additiv)",
      p_upd["description"] == "Default-Profil")

# update_profile unbekannt -> False
check("B13) update unbekannt -> False",
      repo.update_profile("gibtsnicht", name="x") is False)

# delete_profile
check("B14) delete liefert True", repo.delete_profile(pid2) is True)
check("B15) delete unbekannt -> False", repo.delete_profile(pid2) is False)
check("B16) count() == 1 nach delete", repo.count() == 1, str(repo.count()))

# ---------------------------------------------------------------------------
# C) Aktives Profil (Explicit Save)
# ---------------------------------------------------------------------------
pid3 = repo.create_profile(name="Aktiv-Profil", payload={"view": "equity"})
check("C1) anfangs kein aktives Profil", repo.get_active_profile() is None)

check("C2) set_active liefert True", repo.set_active(pid3) is True)
check("C3) set_active unbekannt -> False", repo.set_active("gibtsnicht") is False)

active = repo.get_active_profile()
check("C4) get_active_profile liefert das aktive",
      active is not None and active["profile_id"] == pid3
      and active["is_active"] is True)

# set_active auf anderes Profil -> genau EIN aktives
repo.set_active(pid)
active2 = repo.get_active_profile()
check("C5) genau EIN aktives Profil",
      active2 is not None and active2["profile_id"] == pid)
other = repo.get_profile(pid3)
check("C6) vorheriges Profil ist nicht mehr aktiv",
      other is not None and other["is_active"] is False)

# ---------------------------------------------------------------------------
# D) Schema-Konvention (schema_version Pflichtfeld)
# ---------------------------------------------------------------------------
p_new = repo.get_profile(pid)
check("D1) create ergaenzt schema_version",
      p_new["payload"].get("schema_version") == SCHEMA_VERSION_DEFAULT,
      str(p_new["payload"].get("schema_version")))

# Explizit uebergebene schema_version gewinnt
pid4 = repo.create_profile(
    name="Neu-Version",
    payload={"schema_version": 2, "view": "table"},
)
check("D2) explizite schema_version gewinnt",
      repo.get_profile(pid4)["payload"]["schema_version"] == 2)

# update ergaenzt schema_version additiv
repo.update_profile(pid, payload={"view": "heatmap"})
check("D3) update ergaenzt schema_version additiv",
      repo.get_profile(pid)["payload"]["schema_version"] == SCHEMA_VERSION_DEFAULT)

# Alt-Row OHNE schema_version -> Lesen ergaenzt Default
con.execute("""
    UPDATE analytics_profiles
    SET payload = CAST(? AS JSON)
    WHERE profile_id = ?
""", [json.dumps({"view": "alt"}), pid4])
alt = repo.get_profile(pid4)
check("D4) Alt-Row ohne schema_version erhaelt Default beim Lesen",
      alt is not None and alt["payload"].get("schema_version") == SCHEMA_VERSION_DEFAULT,
      str(alt["payload"].get("schema_version")) if alt else "None")

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
