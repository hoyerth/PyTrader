# analytics/engine/service_set_repository.py
"""
Phase 13 Schritt 2 – ServiceSetRepository.

Kapselt das Laden/Speichern von Service-Sets in einer eigenen Tabelle
`service_sets` in app_data.duckdb. Der StateManager wird NICHT angefasst –
das Repository hält seine Persistenz vollständig selbst.

Tabelle service_sets:
    set_id        VARCHAR PRIMARY KEY
    display_name  VARCHAR
    definition    JSON (vollständige ServiceSetDefinition)
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP

Pflicht-API (Roadmap §Schritt 2.2):
    save_set()   – speichert/überschreibt ein Set (Upsert); generiert bei
                   leerem display_name einen Default-Namen aus instance_ids
                   (z.B. "grid_1 + prox_1"). Liefert die set_id zurück.
    get_set()    – lädt eine Definition per set_id (oder None).
    list_sets()  – liefert ALLE gespeicherten Sets (Quelle für die
                   Set-Dropdowns im Prop-/Service-Fenster).
    delete_set() – entfernt ein Set sauber (liefert bool).
"""

import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from db_service import DbPool, _parse_json_field
from analytics.engine.schema_migrator import MigrationError

# Projekt-Root = 3 Ebenen über dieser Datei (engine/ → analytics/ → Projekt-Root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
APP_DB_PATH = str(BASE_DIR / "data" / "app_data.duckdb")


class ServiceSetRepository:
    """Persistenz-Layer für Service-Sets (eigene Tabelle in app_data.duckdb)."""

    def __init__(self, db_path: str = APP_DB_PATH) -> None:
        self.db_path = db_path
        self._init_db()

    # -------------------------------------------------------------------------
    # Interna
    # -------------------------------------------------------------------------
    def _get_connection(self) -> Any:
        return DbPool.get(self.db_path)

    def _init_db(self) -> None:
        """Legt die Tabelle service_sets an (lazy, idempotent)."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        con = self._get_connection()
        con.execute("""
            CREATE TABLE IF NOT EXISTS service_sets (
                set_id       VARCHAR PRIMARY KEY,
                display_name VARCHAR,
                definition   JSON NOT NULL,
                description  VARCHAR,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        # Phase 14 P14-01: Additive Spalte für bestehende Datenbanken (idempotent)
        con.execute("ALTER TABLE service_sets ADD COLUMN IF NOT EXISTS description VARCHAR;")
        # Phase 14 P14-04 (Bestands-Migration): Nach dem ALTER TABLE laufende
        # Sets bereinigen (fehlende description-Felder mit "" auffüllen).
        self._migrate_existing_sets()

    def _migrate_existing_sets(self) -> None:
        """Phase 14 P14-04 (Bestands-Migration, idempotent).

        Lädt alle vorhandenen Service-Sets und prüft, ob das `description`-
        Feld fehlt. Fehlt es, wird es mit `""` aufgefüllt und das Set erneut
        gespeichert. Damit haben alle Bestands-Sets nach dem Öffnen ein
        konsistentes Beschreibungsfeld (P14-01-Spalte + JSON-Payload).

        Läuft direkt nach dem `ALTER TABLE` in `_init_db()`. Fehler einzelner
        Sets brechen die Initialisierung nicht ab (Skip-Logik).
        """
        try:
            con = self._get_connection()
            rows = con.execute(
                "SELECT set_id, definition FROM service_sets"
            ).fetchall()
        except Exception as e:
            print(f"WARN [ServiceSetRepository] Bestands-Migration Lesen "
                  f"fehlgeschlagen: {e}")
            return
        for set_id, definition_json in rows:
            if not set_id:
                continue
            definition = _parse_json_field(definition_json) or {}
            if "description" in definition:
                continue
            definition["description"] = ""
            try:
                self.save_set(definition)
                print(f"  . Bestandsset '{set_id}': description aufgefuellt (P14-04)")
            except Exception as e:
                print(f"WARN [ServiceSetRepository] Bestands-Migration Set "
                      f"'{set_id}' fehlgeschlagen: {e}")

    @staticmethod
    def _default_display_name(definition: Dict[str, Any]) -> str:
        """Default-Name aus den instance_ids der execution_order.

        Beispiel: execution_order=["grid_1", "prox_1"] → "grid_1 + prox_1".
        Nur instance_ids, die auch in services existieren, werden verwendet.
        """
        order = definition.get("execution_order") or []
        services = definition.get("services") or {}
        names = [iid for iid in order if iid in services]
        if not names:
            names = list(services.keys())
        return " + ".join(names) if names else "Unbenanntes Set"

    # -------------------------------------------------------------------------
    # Pflicht-API
    # -------------------------------------------------------------------------
    def save_set(self, definition: Dict[str, Any]) -> str:
        """Speichert ein Service-Set (Upsert) und liefert die set_id zurück.

        - set_id leer → wird als uuid4-hex generiert.
        - display_name leer → Default-Name aus instance_ids (z.B. 'grid_1 + prox_1').
        - Gleiche set_id überschreibt die bestehende Zeile (kein Duplikat).
        """
        set_id = str(definition.get("set_id") or uuid.uuid4().hex)
        display_name = str(definition.get("display_name") or "").strip()
        if not display_name:
            display_name = self._default_display_name(definition)
        # Phase 14 P14-01: description optional – wird in der eigenen Spalte
        # UND im JSON-Payload persistiert (Definition bleibt vollständig).
        description = definition.get("description")
        description = str(description).strip() if description is not None else None

        payload = {
            "set_id": set_id,
            "display_name": display_name,
            "description": description,
            "execution_order": definition.get("execution_order", []),
            "services": definition.get("services", {}),
        }

        con = self._get_connection()
        con.execute("""
            INSERT INTO service_sets (set_id, display_name, definition, description, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (set_id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                definition   = EXCLUDED.definition,
                description  = EXCLUDED.description,
                updated_at   = EXCLUDED.updated_at
        """, [set_id, display_name, json.dumps(payload), description])
        return set_id

    def get_set(self, set_id: str) -> Optional[Dict[str, Any]]:
        """Lädt eine Service-Set-Definition per set_id (oder None).

        Phase 14 P14-04: Wendet den SchemaMigrator TRANSPARENT IM SPEICHER an
        (Semantic Versioning): Abweichende Instanz-Konfigurationen werden
        gegen das aktuelle Plugin-Schema migriert (Defaults ergänzt, veraltete
        Keys entfernt, Version angehoben). Die Datenbank bleibt unverändert.

        ROLLBACK-SCHUTZ: Tritt während der Migration ein MigrationError auf,
        wird die Migration abgebrochen und das UNMIGRIERTE Original-Set
        zurückgegeben (Rollback auf Datenbank-Ebene, Invariante 8).
        """
        con = self._get_connection()
        res = con.execute(
            "SELECT set_id, display_name, definition, description FROM service_sets WHERE set_id = ?",
            [set_id],
        ).fetchone()
        if not res:
            return None
        db_set_id, db_display_name, definition_json, db_description = res
        definition = _parse_json_field(definition_json) or {}
        # DB-Spalten sind die Single Source of Truth für set_id/display_name
        definition["set_id"] = str(db_set_id)
        if not definition.get("display_name"):
            definition["display_name"] = db_display_name or ""
        # Phase 14 P14-01: description aus der DB-Spalte nachziehen
        if not definition.get("description") and db_description:
            definition["description"] = db_description

        # P14-04: Original für den Rollback tief kopieren, DANN migrieren.
        original = copy.deepcopy(definition)
        try:
            definition = self._apply_schema_migration(definition)
        except MigrationError as e:
            print(f"WARN [ServiceSetRepository] Schema-Migration fuer Set "
                  f"'{set_id}' abgebrochen - Original wird geladen. {e}")
            return original
        return definition

    def _apply_schema_migration(self, definition: Dict[str, Any]) -> Dict[str, Any]:
        """Phase 14 P14-04: Wendet den SchemaMigrator auf alle Instanzen an.

        Iteriert über alle Service-Instanzen des Sets und migriert jede
        Konfiguration gegen ihr Plugin (PluginRegistry). Plugins, die nicht
        (mehr) registriert sind, bleiben unverändert (Skip – ein fehlendes
        Plugin darf das Laden des restlichen Sets nicht brechen).

        Raises:
            MigrationError: bei jedem Fehler der Migrations-Engine – der
            Aufrufer (get_set) führt dann den Rollback auf das Original aus.
        """
        from analytics.features.feature_builder import PluginRegistry
        from analytics.engine.schema_migrator import SchemaMigrator

        services = definition.get("services") or {}
        migrator = SchemaMigrator()
        registry = PluginRegistry()
        for iid, cfg in services.items():
            if not isinstance(cfg, dict):
                continue
            pid = cfg.get("plugin_id") or iid
            try:
                plugin = registry.get(pid)
            except KeyError:
                # Plugin nicht (mehr) registriert → Instanz unverändert lassen.
                continue
            services[iid] = migrator.migrate_instance_config(cfg, plugin)
        definition["services"] = services
        return definition

    def list_sets(self) -> List[Dict[str, Any]]:
        """Liefert ALLE gespeicherten Service-Sets (volle Definitionen).

        Quelle für die Set-Dropdowns im Prop-/Service-Fenster. Deterministisch
        nach updated_at sortiert (älteste zuerst, analog load_all_instances).
        """
        con = self._get_connection()
        rows = con.execute(
            "SELECT set_id, display_name, definition, description FROM service_sets ORDER BY updated_at ASC"
        ).fetchall()
        sets: List[Dict[str, Any]] = []
        for db_set_id, db_display_name, definition_json, db_description in rows:
            definition = _parse_json_field(definition_json) or {}
            definition["set_id"] = str(db_set_id)
            if not definition.get("display_name"):
                definition["display_name"] = db_display_name or ""
            # Phase 14 P14-01: description aus der DB-Spalte nachziehen
            if not definition.get("description") and db_description:
                definition["description"] = db_description
            sets.append(definition)
        return sets

    def delete_set(self, set_id: str) -> bool:
        """Entfernt ein Set sauber. Liefert True, wenn eine Zeile existierte."""
        con = self._get_connection()
        res = con.execute(
            "SELECT COUNT(*) FROM service_sets WHERE set_id = ?", [set_id]
        ).fetchone()
        exists = bool(res and res[0] and res[0] > 0)
        if exists:
            con.execute("DELETE FROM service_sets WHERE set_id = ?", [set_id])
        return exists
