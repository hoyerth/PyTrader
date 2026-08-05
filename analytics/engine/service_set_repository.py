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
from datetime import datetime, timezone
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
        # Phase 14 P14-05: Papierkorb- & Historien-Tabellen (Soft-Delete &
        # Deterministische Snapshots). Idempotent – bestehende DBs werden
        # additiv erweitert (Invariante 9: Snapshot nur bei Überschreiben).
        con.execute("""
            CREATE TABLE IF NOT EXISTS service_sets_trash (
                set_id       VARCHAR PRIMARY KEY,
                display_name VARCHAR,
                definition   JSON,
                deleted_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS service_set_history (
                history_id VARCHAR PRIMARY KEY,
                set_id     VARCHAR,
                version    VARCHAR,
                definition JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
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
                # P14-05: record_snapshot=False – die Bestands-Migration ist ein
                # interner Verwaltungsschreibvorgang (nur description ergänzen)
                # und darf KEINE Snapshot-Historie erzeugen (Invariante 9:
                # Snapshot nur bei Nutzer-Überschreiben).
                self.save_set(definition, record_snapshot=False)
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

    @staticmethod
    def _semver_bump_patch(version: str) -> str:
        """Erhoeht die Patch-Stufe einer Semantic-Version (1.2.3 -> 1.2.4).

        Dient dem Set-Level `version`-Feld (Kap 5 AKTUELLE_UMSETZUNG): Bei jedem
        Ueberschreiben eines Sets wird die Patch-Stufe automatisch angehoben,
        sofern der Aufrufer keine explizite Version mitgibt. Ungueltige/leere
        Versionen werden als "0.0.1" behandelt (defensiv).
        """
        parts = str(version or "0.0.0").split(".")
        try:
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
        except (ValueError, IndexError):
            return "0.0.1"
        return f"{major}.{minor}.{patch + 1}"

    # -------------------------------------------------------------------------
    # Pflicht-API
    # -------------------------------------------------------------------------
    def save_set(self, definition: Dict[str, Any], record_snapshot: bool = True) -> str:
        """Speichert ein Service-Set (Upsert) und liefert die set_id zurück.

        - set_id leer → wird als uuid4-hex generiert.
        - display_name leer → Default-Name aus instance_ids (z.B. 'grid_1 + prox_1').
        - Gleiche set_id überschreibt die bestehende Zeile (kein Duplikat).

        Phase 14 P14-05 (Deterministische Snapshot-Historie): Existiert das Set
        bereits in service_sets (Überschreiben), wird UNMITTELBAR VOR dem
        Überschreiben der bisherige Stand als Snapshot in service_set_history
        gesichert (version = fortlaufender Zähler je set_id). Bei reinen
        Neuanlagen oder Schreibfehlern entsteht KEIN Snapshot (Invariante 9).

        Kap 5 AKTUELLE_UMSETZUNG (Set-Level Metadaten, additiv): Jede Definition
        erhält automatisch die Felder
          - version         Set-Level Semantic Version (major.minor.patch).
                            Aufrufer-Version gewinnt; sonst Patch-Bump beim
                            Überschreiben, "1.0.0" bei Neuanlage.
          - schema_version  Format-Version der Definition ("1.0", Default).
          - created_at      Erstellungs-Zeitstempel (ISO-8601 UTC); wird bei
                            Überschreiben aus dem Bestand übernommen.
        Bestehende Sets werden beim nächsten Speichern automatisch auf diese
        Felder nachgezogen (idempotent, kein Datenverlust).

        Args:
            definition: ServiceSetDefinition.
            record_snapshot: False unterdrückt die Snapshot-Erzeugung für
                interne Verwaltungsschreibvorgänge (z. B. die P14-04
                Bestands-Migration, die Bestands-Sets nur um description
                ergänzt und dafür keinen Historie-Eintrag erzeugen darf).
        """
        set_id = str(definition.get("set_id") or uuid.uuid4().hex)
        display_name = str(definition.get("display_name") or "").strip()
        if not display_name:
            display_name = self._default_display_name(definition)
        # Phase 14 P14-01: description optional – wird in der eigenen Spalte
        # UND im JSON-Payload persistiert (Definition bleibt vollständig).
        description = definition.get("description")
        description = str(description).strip() if description is not None else None

        con = self._get_connection()

        # Kap 5 AKTUELLE_UMSETZUNG: Set-Level Metadaten (version/schema_version/
        # created_at). Bestand lesen, damit created_at bei Überschreiben erhalten
        # bleibt und die Snapshot-Historie denselben Lesezugriff nutzen kann.
        existing_row = con.execute(
            "SELECT definition FROM service_sets WHERE set_id = ?", [set_id]
        ).fetchone()
        existing_def = _parse_json_field(existing_row[0]) if existing_row else {}

        if definition.get("version"):
            version = str(definition["version"])
        elif existing_def.get("version"):
            version = self._semver_bump_patch(str(existing_def["version"]))
        else:
            version = "1.0.0"
        schema_version = str(
            definition.get("schema_version")
            or existing_def.get("schema_version")
            or "1.0"
        )
        created_at = definition.get("created_at") or existing_def.get("created_at")
        if not created_at:
            created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        payload = {
            "set_id": set_id,
            "display_name": display_name,
            "description": description,
            # Bugfix 05.08.2026: Explizite Indikator-Zuordnung (Anlage-Dialog)
            # wird in der Definition persistiert (kein Service noetig).
            "indicator_id": definition.get("indicator_id"),
            "version": version,
            "schema_version": schema_version,
            "created_at": created_at,
            "execution_order": definition.get("execution_order", []),
            "services": definition.get("services", {}),
        }

        # P14-05: Snapshot-Historie – NUR bei erfolgreichem Überschreiben eines
        # BEREITS EXISTIERENDEN Sets (vor dem Upsert).
        if record_snapshot:
            if existing_row:
                old_definition = existing_def or {}
                history_count = con.execute(
                    "SELECT COUNT(*) FROM service_set_history WHERE set_id = ?",
                    [set_id],
                ).fetchone()
                count = int(history_count[0]) if history_count and history_count[0] else 0
                con.execute("""
                    INSERT INTO service_set_history (history_id, set_id, version, definition, created_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, [uuid.uuid4().hex, set_id, str(count + 1),
                      json.dumps(old_definition)])

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

    def delete_set(self, set_id: str, soft_delete: bool = True) -> bool:
        """Entfernt ein Set. Liefert True, wenn eine Zeile existierte.

        Phase 14 P14-05 (Soft-Delete): Bei soft_delete=True wird das Set in
        die Papierkorb-Tabelle `service_sets_trash` verschoben (mit
        deleted_at-Zeitstempel) statt hart gelöscht. Die Wiederherstellung
        erfolgt über restore_set_from_trash(). Bei soft_delete=False wird das
        Set ENDGÜLTIG entfernt (z. B. für die Papierkorb-Bereinigung).
        """
        con = self._get_connection()
        res = con.execute(
            "SELECT set_id, display_name, definition FROM service_sets WHERE set_id = ?",
            [set_id],
        ).fetchone()
        if not res:
            return False
        db_set_id, db_display_name, definition_json = res
        if soft_delete:
            # Kopie nach service_sets_trash (Upsert – erneutes Löschen eines
            # bereits im Papierkorb liegenden Sets aktualisiert den Zeitstempel).
            con.execute("""
                INSERT INTO service_sets_trash (set_id, display_name, definition, deleted_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT (set_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    definition   = EXCLUDED.definition,
                    deleted_at   = EXCLUDED.deleted_at
            """, [db_set_id, db_display_name or "", definition_json])
        con.execute("DELETE FROM service_sets WHERE set_id = ?", [set_id])
        return True

    def list_trash(self) -> List[Dict[str, Any]]:
        """Liefert ALLE im Papierkorb befindlichen Service-Sets.

        Analog list_sets() – deterministisch nach deleted_at sortiert
        (älteste zuerst). Enthält zusätzlich das Feld 'deleted_at' und ist
        die Quelle für den Papierkorb-Dialog im Service-Fenster.
        """
        con = self._get_connection()
        rows = con.execute(
            "SELECT set_id, display_name, definition, deleted_at "
            "FROM service_sets_trash ORDER BY deleted_at ASC"
        ).fetchall()
        items: List[Dict[str, Any]] = []
        for db_set_id, db_display_name, definition_json, db_deleted_at in rows:
            definition = _parse_json_field(definition_json) or {}
            definition["set_id"] = str(db_set_id)
            if not definition.get("display_name"):
                definition["display_name"] = db_display_name or ""
            definition["deleted_at"] = db_deleted_at
            items.append(definition)
        return items

    def restore_set_from_trash(self, set_id: str) -> bool:
        """Stellt ein Set aus dem Papierkorb wieder her (Trash → service_sets).

        Liefert True, wenn ein Trash-Eintrag existierte und wiederhergestellt
        wurde. Existiert die set_id in service_sets bereits (z. B. weil sie
        zwischenzeitlich neu angelegt wurde), wird sie überschrieben.
        """
        con = self._get_connection()
        res = con.execute(
            "SELECT set_id, display_name, definition FROM service_sets_trash WHERE set_id = ?",
            [set_id],
        ).fetchone()
        if not res:
            return False
        db_set_id, db_display_name, definition_json = res
        definition = _parse_json_field(definition_json) or {}
        definition["set_id"] = str(db_set_id)
        if not definition.get("display_name"):
            definition["display_name"] = db_display_name or ""
        description = definition.get("description")
        description = str(description).strip() if description is not None else None
        # Wiederherstellen (Upsert auf service_sets)
        con.execute("""
            INSERT INTO service_sets (set_id, display_name, definition, description, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (set_id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                definition   = EXCLUDED.definition,
                description  = EXCLUDED.description,
                updated_at   = EXCLUDED.updated_at
        """, [db_set_id, definition.get("display_name") or "", json.dumps(definition), description])
        con.execute("DELETE FROM service_sets_trash WHERE set_id = ?", [set_id])
        return True

    def purge_trash_set(self, set_id: str) -> bool:
        """Entfernt ein Set ENDGÜLTIG aus dem Papierkorb (hartes Löschen).

        Liefert True, wenn ein Trash-Eintrag existierte und entfernt wurde.
        Dieser Vorgang ist nicht umkehrbar – die UI verlangt daher eine
        doppelte Sicherheitsabfrage.
        """
        con = self._get_connection()
        res = con.execute(
            "SELECT COUNT(*) FROM service_sets_trash WHERE set_id = ?", [set_id]
        ).fetchone()
        exists = bool(res and res[0] and res[0] > 0)
        if exists:
            con.execute("DELETE FROM service_sets_trash WHERE set_id = ?", [set_id])
        return exists

    def purge_trash(self) -> int:
        """Leert den Papierkorb vollständig (Endgültige Bereinigung der DB).

        Liefert die Anzahl endgültig entfernter Sets. Nicht umkehrbar – die
        UI verlangt daher eine doppelte Sicherheitsabfrage.
        """
        con = self._get_connection()
        res = con.execute("SELECT COUNT(*) FROM service_sets_trash").fetchone()
        count = int(res[0]) if res and res[0] else 0
        if count:
            con.execute("DELETE FROM service_sets_trash")
        return count
