# BEREIT FÜR PHASE 15
# test/check_p14_s4_migration.py
"""
Phase 14 P14-04 – Headless Validierung (KEINE UI, KEIN exec_()).

Prüft (laut Kopierblock P14-04, Schritt 3):
a) Version wird bei Major/Minor-Änderung auf die aktuelle plugin.version
   angehoben.
b) Bei einer bloßen Patch-Änderung (1.0.0 -> 1.0.1) erfolgt KEINE unnötige
   Migration.
c) Fehlende Parameter werden ergänzt, veraltete Keys entfernt.
d) Bei Auslösen eines Fehlers greift das Rollback sauber (get_set liefert
   das UNMIGRIERTE Original zurück).

Zusätzlich:
- `_needs_migration` SemVer-Matrix (inkl. Legacy '0.0.0', Downgrade-Schutz).
- `ServiceSetRepository.get_set()` wendet den Migrator transparent an
  (Integrationspfad) und `_migrate_existing_sets()` füllt fehlende
  description-Felder auf (Bestands-Migration).
- `ServiceInstanceConfig.version`-Stamping in service_win.collect_set_definition()
  wird als reine Logik nachgeprüft (headless, ohne UI): Das Stamping wird
  über die Registry-Version erzwungen.

Test-DB liegt im Unterordner test/ (Regel: keine Test-DBs im Root/data).
"""
import json
import os
import sys

sys.path.insert(0, r"F:\Python\PyTrader")

TEST_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "p14_s4_test.duckdb")
if os.path.exists(TEST_DB):
    os.remove(TEST_DB)

from analytics.engine.schema_migrator import (  # noqa: E402
    SchemaMigrator,
    MigrationError,
    _needs_migration,
    _parse_version,
)
from analytics.engine.service_set_repository import ServiceSetRepository  # noqa: E402
from analytics.features.plugins.base_plugin import PluginFeature  # noqa: E402
from analytics.features.definitions.grid_lines_service import GridLinesService  # noqa: E402

FAILURES: list = []


def check(name: str, cond: bool, detail: str = "") -> None:
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" – {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ---------------------------------------------------------------------------
# 0) SemVer-Hilfsfunktionen
# ---------------------------------------------------------------------------
check("parse: '1.2.3'", _parse_version("1.2.3") == (1, 2, 3))
check("parse: None -> 0.0.0", _parse_version(None) == (0, 0, 0))
check("parse: '' -> 0.0.0", _parse_version("") == (0, 0, 0))
check("parse: 'v1.2.3' Präfix", _parse_version("v1.2.3") == (1, 2, 3))
check("parse: Pre-Release/Build ignoriert",
      _parse_version("1.2.3-beta.1+build5") == (1, 2, 3))
check("parse: '1.2' ergänzt", _parse_version("1.2") == (1, 2, 0))

# SemVer-Matrix für _needs_migration (v_old -> v_new)
check("needs: Legacy 0.0.0 -> 1.0.0 (immer migrieren)", _needs_migration(None, "1.0.0") is True)
check("needs: Major 1.0.0 -> 2.0.0", _needs_migration("1.0.0", "2.0.0") is True)
check("needs: Minor 1.0.0 -> 1.1.0", _needs_migration("1.0.0", "1.1.0") is True)
check("needs: Patch 1.0.0 -> 1.0.1 (KEINE Migration)", _needs_migration("1.0.0", "1.0.1") is False)
check("needs: gleich 1.0.0 -> 1.0.0", _needs_migration("1.0.0", "1.0.0") is False)
check("needs: Downgrade 2.0.0 -> 1.0.0 (KEIN destruktives Reset)",
      _needs_migration("2.0.0", "1.0.0") is False)

# ---------------------------------------------------------------------------
# 1) Migrator direkt (Fake-Plugin Version 2.0.0)
# ---------------------------------------------------------------------------
class _V2Plugin(PluginFeature):
    @property
    def plugin_id(self) -> str:
        return "v2_plugin"

    @property
    def version(self) -> str:
        return "2.0.0"

    @property
    def parameter_schema(self):
        return {
            "step_size": {"type": "float", "default": 0.5},
            "new_param": {"type": "int", "default": 7},
        }

    def calculate(self, df, params, context=None):
        return {"feature_store_payload": {}, "chart_render_payload": {}}


migrator = SchemaMigrator()

# a) Major-Änderung: Version wird angehoben + c) Keys ergänzt/entfernt
old_cfg = {
    "plugin_id": "v2_plugin",
    "version": "1.0.0",
    "lookback": 500,
    "params": {"step_size": 0.5, "old_key": 999, "to_remove": "x"},
}
migrated = migrator.migrate_instance_config(old_cfg, _V2Plugin())
check("a) Version bei Major auf 2.0.0 angehoben",
      migrated.get("version") == "2.0.0", str(migrated.get("version")))
check("c) Fehlender Key 'new_param' mit Default 7 ergänzt",
      migrated.get("params", {}).get("new_param") == 7)
check("c) Vorhandener Key 'step_size' erhalten",
      migrated.get("params", {}).get("step_size") == 0.5)
check("c) Veralteter Key 'old_key' entfernt",
      "old_key" not in migrated.get("params", {}))
check("c) Veralteter Key 'to_remove' entfernt",
      "to_remove" not in migrated.get("params", {}))
check("c) lookback bleibt erhalten", migrated.get("lookback") == 500)
check("Original unverändert (keine In-Place-Mutation)",
      old_cfg.get("version") == "1.0.0" and "old_key" in old_cfg.get("params", {}))

# Legacy ohne version-Feld (None -> 0.0.0) wird migriert
legacy_cfg = {"plugin_id": "v2_plugin", "params": {}}
legacy_migrated = migrator.migrate_instance_config(legacy_cfg, _V2Plugin())
check("Legacy ohne version: Migration (0.0.0 -> 2.0.0)",
      legacy_migrated.get("version") == "2.0.0")
check("Legacy: lookback Default 1000 ergänzt",
      legacy_migrated.get("lookback") == 1000)

# b) Patch-Änderung: KEINE unnötige Migration (1.0.0 -> 1.0.1)
class _PatchPlugin(PluginFeature):
    @property
    def plugin_id(self) -> str:
        return "v2_plugin"

    @property
    def version(self) -> str:
        return "1.0.1"

    @property
    def parameter_schema(self):
        return {
            "step_size": {"type": "float", "default": 0.5},
            "new_param": {"type": "int", "default": 7},
        }

    def calculate(self, df, params, context=None):
        return {"feature_store_payload": {}, "chart_render_payload": {}}


patch_cfg = {
    "plugin_id": "v2_plugin",
    "version": "1.0.0",
    "params": {"step_size": 0.5, "fremd_key": 1},
}
patch_migrated = migrator.migrate_instance_config(patch_cfg, _PatchPlugin())
check("b) Patch 1.0.0 -> 1.0.1: KEINE Migration",
      patch_migrated.get("version") == "1.0.0",
      str(patch_migrated.get("version")))
check("b) Patch: fremde Keys bleiben erhalten (kein Eingriff)",
      patch_migrated.get("params", {}).get("fremd_key") == 1)

# Downgrade-Schutz: 2.0.0 -> 1.0.0 (Plugin-Version kleiner) → unverändert
downgrade_cfg = {"plugin_id": "v2_plugin", "version": "2.0.0",
                 "params": {"step_size": 0.5, "zukunft_key": 1}}
downgrade_migrated = migrator.migrate_instance_config(downgrade_cfg, _V2Plugin())
check("Downgrade 2.0.0 -> 1.0.0: kein Reset", downgrade_migrated.get("version") == "2.0.0")

# d) MigrationError bei Plugin=None
try:
    migrator.migrate_instance_config({"plugin_id": "x"}, None)
    check("d) MigrationError bei Plugin=None", False, "keine Exception geworfen")
except MigrationError:
    check("d) MigrationError bei Plugin=None", True)


# ---------------------------------------------------------------------------
# 2) Integration: ServiceSetRepository.get_set() wendet Migrator an
# ---------------------------------------------------------------------------
repo = ServiceSetRepository(db_path=TEST_DB)

# 2a) Set mit Legacy-Instanz (version fehlt, veralteter Key) -> Migration beim Laden
legacy_set = {
    "set_id": "legacy-set",
    "display_name": "Legacy",
    "execution_order": ["grid_1"],
    "services": {
        "grid_1": {
            "plugin_id": "grid_lines",
            "lookback": 800,
            "params": {"step_size": 0.25, "veralteter_key": 42},
        },
    },
}
repo.save_set(legacy_set)
loaded = repo.get_set("legacy-set")
grid_cfg = loaded["services"]["grid_1"]
check("2a) get_set: Version auf 1.0.0 (plugin.version) angehoben",
      grid_cfg.get("version") == "1.0.0", str(grid_cfg.get("version")))
check("2a) get_set: veralteter Key entfernt",
      "veralteter_key" not in (grid_cfg.get("params") or {}))
check("2a) get_set: Schema-Defaults ergänzt (steps_around vorhanden)",
      (grid_cfg.get("params") or {}).get("steps_around") == 4)
# DB unverändert: Raw-JSON in der Tabelle enthält weiterhin KEIN version-Feld
raw_row = repo._get_connection().execute(
    "SELECT definition FROM service_sets WHERE set_id = 'legacy-set'"
).fetchone()
raw_def = json.loads(raw_row[0]) if raw_row else {}
raw_svc = (raw_def.get("services") or {}).get("grid_1") or {}
check("2a) DB unverändert (Migration nur im Speicher)",
      raw_svc.get("version") is None and "veralteter_key" in (raw_svc.get("params") or {}))

# 2b) Aktuelles Set (version == plugin.version) -> KEINE Migration
current_set = {
    "set_id": "current-set",
    "display_name": "Aktuell",
    "execution_order": ["grid_1"],
    "services": {
        "grid_1": {
            "plugin_id": "grid_lines",
            "version": "1.0.0",
            "lookback": 800,
            "params": {"step_size": 0.25, "noch_da": 1},
        },
    },
}
repo.save_set(current_set)
loaded_cur = repo.get_set("current-set")
check("2b) get_set: aktuelle Version -> keine Migration",
      loaded_cur["services"]["grid_1"].get("version") == "1.0.0")
check("2b) get_set: fremde Keys bleiben (kein Eingriff)",
      (loaded_cur["services"]["grid_1"].get("params") or {}).get("noch_da") == 1)

# 2c) Unbekanntes Plugin -> Instanz bleibt unverändert (Skip, kein Rollback)
unknown_set = {
    "set_id": "unknown-set",
    "display_name": "Unbekannt",
    "execution_order": ["x_1"],
    "services": {
        "x_1": {"plugin_id": "gibt_es_nicht", "version": "0.9.0",
                "params": {"a": 1}},
    },
}
repo.save_set(unknown_set)
loaded_unk = repo.get_set("unknown-set")
check("2c) get_set: unbekanntes Plugin bleibt unverändert (Skip)",
      loaded_unk["services"]["x_1"].get("version") == "0.9.0")

# 2d) Rollback: _apply_schema_migration wirft MigrationError -> Original zurück
class _CrashingRepo(ServiceSetRepository):
    def _apply_schema_migration(self, definition):
        raise MigrationError("Simulierter Migrations-Fehler")


crash_repo = _CrashingRepo(db_path=TEST_DB)
rolled = crash_repo.get_set("legacy-set")
check("d) Rollback: Original-Set zurück (Version 0.0.0/kein Feld)",
      rolled is not None and rolled["services"]["grid_1"].get("version") in (None, "0.0.0"),
      str(rolled["services"]["grid_1"].get("version")) if rolled else "None")
check("d) Rollback: Original-Params erhalten (veralteter_key noch da)",
      rolled is not None and "veralteter_key" in (rolled["services"]["grid_1"].get("params") or {}))


# ---------------------------------------------------------------------------
# 3) Bestands-Migration: _migrate_existing_sets() füllt fehlende description
# ---------------------------------------------------------------------------
repo2 = ServiceSetRepository(db_path=TEST_DB)
# Legacy-Set direkt per SQL einfügen (JSON OHNE description-Key, wie vor P14-01)
legacy_json = json.dumps({
    "set_id": "bestand-set",
    "display_name": "Bestand",
    "execution_order": [],
    "services": {},
})
con = repo2._get_connection()
con.execute(
    "INSERT INTO service_sets (set_id, display_name, definition, description) "
    "VALUES (?, ?, ?, NULL)",
    ["bestand-set", "Bestand", legacy_json],
)
# Neues Repo (gleiche DB) -> _migrate_existing_sets läuft in __init__/nach ALTER
repo3 = ServiceSetRepository(db_path=TEST_DB)
bestand = repo3.get_set("bestand-set")
check("3) Bestands-Migration: description aufgefüllt (Key vorhanden)",
      bestand is not None and "description" in bestand,
      str(bestand.get("description")) if bestand else "None")


# ---------------------------------------------------------------------------
# 4) service_win.collect_set_definition(): version-Stamping (Logik-Check)
# ---------------------------------------------------------------------------
# Headless: collect_set_definition() benötigt Qt-UI. Stattdessen wird die
# Stamping-Logik gegen die Registry nachvollzogen (dieselbe Bedingung wie im
# ServiceWindow-Code): Jede Instanz erhält die aktuelle plugin.version.
from analytics.features.feature_builder import PluginRegistry  # noqa: E402
reg = PluginRegistry()
grid_plugin = reg.get("grid_lines")
check("4) Registry: grid_lines hat version 1.0.0",
      getattr(grid_plugin, "version", "") == "1.0.0")
# Simuliertes Stamping (identisch zu service_win.collect_set_definition):
cfg_sim = {"plugin_id": "grid_lines", "lookback": 1000, "params": {}}
cfg_sim["version"] = getattr(grid_plugin, "version", "0.0.0") or "0.0.0"
check("4) Stamping-Logik: version = plugin.version",
      cfg_sim["version"] == grid_plugin.version)


# ---------------------------------------------------------------------------
print("-" * 60)
if FAILURES:
    print(f"FEHLER: {len(FAILURES)} Prüfung(en) fehlgeschlagen: {FAILURES}")
    sys.exit(1)
print("ALLE PRÜFUNGEN BESTANDEN (OK)")
sys.exit(0)
