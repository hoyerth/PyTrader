# analytics_profile_repository.py
"""
analytics_profile_repository.py - Analytics-Profile-Repository (Phase 15.03).

Kapselt den Lese-/Schreibzugriff auf die `analytics_profiles`-Tabelle in
`app_data.duckdb` – die Persistenz-Schicht fuer die Analytics-UI
(AnalyticsWindow, 15.03). Ein Profil haelt eine benannte Parametrisierung
der Analytics-Ansichten (Option B – Explicit Save: Slider-/Parametertrends
setzen ein Dirty-Flag `*`; gespeichert wird erst auf `[💾 Save]`).

Datenfluss (Invariante 4, Kein SQL in UI):
    DuckDB (analytics_profiles) <-- AnalyticsProfileRepository <-- ViewModel/UI

Schema (analytics_profiles):
    profile_id  VARCHAR PRIMARY KEY   – uuid4-hex (generiert)
    name        VARCHAR NOT NULL      – eindeutiger Profil-Name (case-insensitiv)
    description VARCHAR               – optionale Beschreibung
    payload     JSON                  – Profil-Payload INKL. Pflichtfeld
                                        `schema_version` (20.01-Spez: 2)
    is_active   BOOLEAN DEFAULT FALSE – genau EIN aktives Profil
    created_at  TIMESTAMP DEFAULT current_timestamp
    updated_at  TIMESTAMP DEFAULT current_timestamp

Payload-Schema (20.01, E3 – sectioned, verlustfrei):
    schema_version: 2
    sources:  symbol, timeframe, feature_ids
    charts:   heatmap_metric, scatter_x, scatter_y, distribution_column, bins
    table:    limit, table_column_widths, table_row_height,
              table_sort_column, table_sort_order
    styling:  {}  (Reserve fuer zukuenftige visuelle Settings)

Alt-Payloads (schema_version: 1, flach) werden beim Lesen (_row_to_profile)
UND beim Schreiben (_ensure_schema_version) verlustfrei nach v2 migriert
(E2/E4, Single Source of Truth im Repository – das ViewModel erhaelt IMMER
v2-Sections). Unbekannte v1-Top-Level-Keys bleiben erhalten.

Verhalten:
- `create_profile()`   : legt ein neues Profil an; ergaenzt den Payload
  additiv um `schema_version` (Pflichtfeld, 15.03-Spezifikation).
- `get_profile()`      : liest ein Profil per profile_id (oder None).
- `get_profile_by_name()`: liest per Name (case-insensitive).
- `list_profiles()`    : alle Profile (deterministisch nach Name sortiert).
- `update_profile()`   : aktualisiert name/description/payload (Payload
  behaelt sein schema_version-Pflichtfeld).
- `delete_profile()`   : entfernt ein Profil (liefert bool).
- `set_active()`       : setzt genau EIN aktives Profil (andere auf False).
- `get_active_profile()`: liefert das aktive Profil (oder None).
- `count()`            : Anzahl der Profile.
"""

import json
import os
import uuid
from typing import Any, Dict, List, Optional

from db.db_pool import DB_APP_DATA, DbPool
from db.db_utils import _parse_json_field

# Pflichtfeld im Profil-Payload (20.01-Spezifikation: `schema_version: 2`).
SCHEMA_VERSION_DEFAULT: int = 2

#: Sektions-Zuordnung der bekannten Analytics-Parameter (v2-Payload, E3).
_V1_SECTION_KEYS = {
    "sources": {"symbol", "timeframe", "feature_ids", "feature_id"},
    "charts": {"heatmap_metric", "scatter_x", "scatter_y",
               "distribution_column", "bins"},
    "table": {"limit", "table_column_widths", "table_row_height",
              "table_sort_column", "table_sort_order"},
    "styling": set(),
}


class AnalyticsProfileRepository:
    """Persistenz-Layer fuer Analytics-Profile (app_data.duckdb)."""

    def __init__(self, db_path: str = DB_APP_DATA) -> None:
        self.db_path = db_path
        self._ensure_table()

    # ------------------------------------------------------------------
    # Interna
    # ------------------------------------------------------------------
    def _get_connection(self):
        return DbPool.get(self.db_path)

    def _ensure_table(self) -> None:
        """Legt die Tabelle (falls noetig) an – additiv/idempotent.

        Bestehende Profile und Flags werden nicht angetastet (Verbotsregel:
        Bestandsdaten nicht beschädigen). Dieselbe Tabelle wird auch in
        db_service.check_and_init_databases() angelegt (App-Start); das
        CREATE TABLE IF NOT EXISTS hier macht das Repository unabhaengig.
        """
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        con = self._get_connection()
        con.execute("""
            CREATE TABLE IF NOT EXISTS analytics_profiles (
                profile_id  VARCHAR PRIMARY KEY,
                name        VARCHAR NOT NULL,
                description VARCHAR,
                payload     JSON,
                is_active   BOOLEAN DEFAULT FALSE,
                created_at  TIMESTAMP DEFAULT current_timestamp,
                updated_at  TIMESTAMP DEFAULT current_timestamp
            );
        """)

    @staticmethod
    def _ensure_schema_version(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Stellt das Pflichtfeld `schema_version` im Profil-Payload sicher.

        Phase 20.01 (E4): Beim Erzeugen/Aktualisieren werden flache
        v1-Payloads VOR dem Speichern verlustfrei nach v2 migriert
        (_migrate_v1_to_v2) – es entstehen keine neuen v1-Rows. Ein vom
        Aufrufer bereits mitgegebenes schema_version >= 2 gewinnt
        (Aufwaertskompatibilitaet).
        """
        payload = dict(payload or {})
        try:
            version = int(payload.get("schema_version", 1) or 1)
        except (TypeError, ValueError):
            version = 1
        if version < 2:
            return AnalyticsProfileRepository._migrate_v1_to_v2(payload)
        return payload

    @staticmethod
    def _migrate_v1_to_v2(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Wandelt ein flaches v1-Profil-Payload verlustfrei in v2-Sections.

        Phase 20.01 (E2/E3): V1-Payloads (schema_version: 1) speichern alle
        Analytics-Parameter flach auf Top-Level-Ebene. Die Migration gruppiert
        die bekannten Keys in die Sektionen sources/charts/table/styling und
        wandelt den Alt-Einzelwert `feature_id` nach `feature_ids` (Liste,
        kanonisches v2). UNBEKANNTE Top-Level-Keys bleiben erhalten
        (verlustfrei), damit Fremd-Felder nicht zerstoert werden. Ein bereits
        v2-Payload wird unveraendert zurueckgegeben.

        Returns:
            Das migrierte v2-Payload (immer mit `schema_version: 2`).
        """
        if not isinstance(payload, dict):
            return {}
        payload = dict(payload)
        try:
            version = int(payload.get("schema_version", 1) or 1)
        except (TypeError, ValueError):
            version = 1
        if version >= 2:
            return payload

        sections: Dict[str, Dict[str, Any]] = {
            name: {} for name in _V1_SECTION_KEYS
        }
        rest: Dict[str, Any] = {}
        for key, value in payload.items():
            if key == "schema_version":
                continue
            placed = False
            for name, keys in _V1_SECTION_KEYS.items():
                if key in keys:
                    sections[name][key] = value
                    placed = True
                    break
            if not placed:
                rest[key] = value

        # Alt-Einzelwert feature_id -> feature_ids (Liste), kanonisches v2.
        fid = sections["sources"].pop("feature_id", None)
        if fid and not sections["sources"].get("feature_ids"):
            if isinstance(fid, (list, tuple)):
                sections["sources"]["feature_ids"] = [
                    str(f) for f in fid if str(f or "").strip()]
            else:
                sections["sources"]["feature_ids"] = [str(fid)]

        out: Dict[str, Any] = {"schema_version": 2}
        for name in ("sources", "charts", "table", "styling"):
            if sections[name]:
                out[name] = sections[name]
            elif name == "styling":
                # Reserve (E3) immer anlegen – zukuenftige visuelle Settings.
                out[name] = {}
        out.update(rest)
        return out

    @staticmethod
    def _row_to_profile(row) -> Dict[str, Any]:
        """Wandelt eine DB-Zeile in ein Profil-Dict (JSON geparst).

        Phase 20.01 (E2): Alt-Rows ohne `schema_version` oder mit
        schema_version 1 (flach) werden beim Lesen verlustfrei nach v2
        migriert – der ViewModel erhaelt IMMER v2-Sections (Single Source
        of Truth im Repository). Der Payload in der DB bleibt unveraendert
        (Migration nur beim Lesen; beim naechsten Save wird v2 geschrieben).
        """
        profile_id, name, description, payload_json, is_active, created_at, updated_at = row
        payload = _parse_json_field(payload_json) or {}
        payload = dict(payload)
        try:
            version = int(payload.get("schema_version", 1) or 1)
        except (TypeError, ValueError):
            version = 1
        if version < 2:
            payload = AnalyticsProfileRepository._migrate_v1_to_v2(payload)
        return {
            "profile_id": str(profile_id),
            "name": str(name),
            "description": str(description) if description is not None else "",
            "payload": payload,
            "is_active": bool(is_active),
            "created_at": created_at,
            "updated_at": updated_at,
        }

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    def create_profile(
        self,
        name: str,
        payload: Optional[Dict[str, Any]] = None,
        description: str = "",
    ) -> str:
        """Legt ein neues Profil an und liefert dessen profile_id.

        Args:
            name: Eindeutiger Profil-Name (case-insensitiv; ein bestehendes
                Profil mit demselben Namen wird NICHT ueberschrieben –
                Aufrufer prueft mit get_profile_by_name()).
            payload: Profil-Payload (Slider-/Parametertrends der Analytics-
                UI). Wird additiv um `schema_version` ergaenzt (Pflichtfeld).
            description: Optionale Beschreibung.

        Returns:
            Die neue profile_id (uuid4-hex).
        """
        profile_id = uuid.uuid4().hex
        safe_payload = self._ensure_schema_version(payload)
        con = self._get_connection()
        con.execute("""
            INSERT INTO analytics_profiles
                (profile_id, name, description, payload, is_active)
            VALUES (?, ?, ?, ?, FALSE)
        """, [
            profile_id,
            str(name).strip(),
            str(description or "").strip(),
            json.dumps(safe_payload),
        ])
        return profile_id

    def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """Liefert ein Profil per profile_id (oder None)."""
        if not profile_id:
            return None
        con = self._get_connection()
        row = con.execute("""
            SELECT profile_id, name, description, payload, is_active,
                   created_at, updated_at
            FROM analytics_profiles
            WHERE profile_id = ?
        """, [profile_id]).fetchone()
        if row is None:
            return None
        return self._row_to_profile(row)

    def get_profile_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Liefert ein Profil per Name (case-insensitive) oder None."""
        if not name:
            return None
        con = self._get_connection()
        row = con.execute("""
            SELECT profile_id, name, description, payload, is_active,
                   created_at, updated_at
            FROM analytics_profiles
            WHERE LOWER(name) = LOWER(?)
            ORDER BY created_at ASC
            LIMIT 1
        """, [name]).fetchone()
        if row is None:
            return None
        return self._row_to_profile(row)

    def list_profiles(self) -> List[Dict[str, Any]]:
        """Liefert ALLE Profile (deterministisch nach Name sortiert)."""
        con = self._get_connection()
        rows = con.execute("""
            SELECT profile_id, name, description, payload, is_active,
                   created_at, updated_at
            FROM analytics_profiles
            ORDER BY name ASC
        """).fetchall()
        return [self._row_to_profile(r) for r in rows]

    def update_profile(
        self,
        profile_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Aktualisiert name/description/payload eines Profils.

        Nur uebergebene Felder werden geaendert (additiv). Wird ein Payload
        uebergeben, behaelt er sein `schema_version`-Pflichtfeld (additiv,
        falls der Aufrufer es nicht mitgibt).

        Returns:
            True, wenn ein Profil existierte und aktualisiert wurde.
        """
        if not profile_id:
            return False
        con = self._get_connection()
        existing = self.get_profile(profile_id)
        if existing is None:
            return False

        new_name = str(name).strip() if name is not None else existing["name"]
        new_desc = (
            str(description or "").strip()
            if description is not None
            else existing["description"]
        )
        if payload is not None:
            new_payload = self._ensure_schema_version(payload)
            new_payload_json = json.dumps(new_payload)
        else:
            new_payload_json = json.dumps(existing["payload"])

        con.execute("""
            UPDATE analytics_profiles
            SET name = ?, description = ?, payload = ?,
                updated_at = current_timestamp
            WHERE profile_id = ?
        """, [new_name, new_desc, new_payload_json, profile_id])
        return True

    def delete_profile(self, profile_id: str) -> bool:
        """Entfernt ein Profil (hartes Loeschen).

        Returns:
            True, wenn eine Zeile existierte und entfernt wurde.
        """
        if not profile_id:
            return False
        con = self._get_connection()
        res = con.execute(
            "SELECT COUNT(*) FROM analytics_profiles WHERE profile_id = ?",
            [profile_id],
        ).fetchone()
        exists = bool(res and res[0] and res[0] > 0)
        if exists:
            con.execute("DELETE FROM analytics_profiles WHERE profile_id = ?",
                        [profile_id])
        return exists

    # ------------------------------------------------------------------
    # Aktives Profil (Explicit Save – genau EIN aktives Profil)
    # ------------------------------------------------------------------
    def set_active(self, profile_id: str) -> bool:
        """Setzt genau EIN aktives Profil (alle anderen auf False).

        Returns:
            True, wenn das Profil existiert und aktiviert wurde.
        """
        if not profile_id:
            return False
        con = self._get_connection()
        res = con.execute(
            "SELECT COUNT(*) FROM analytics_profiles WHERE profile_id = ?",
            [profile_id],
        ).fetchone()
        exists = bool(res and res[0] and res[0] > 0)
        if not exists:
            return False
        con.execute("UPDATE analytics_profiles SET is_active = FALSE")
        con.execute("""
            UPDATE analytics_profiles
            SET is_active = TRUE, updated_at = current_timestamp
            WHERE profile_id = ?
        """, [profile_id])
        return True

    def get_active_profile(self) -> Optional[Dict[str, Any]]:
        """Liefert das aktive Profil (oder None, wenn keines aktiv ist)."""
        con = self._get_connection()
        row = con.execute("""
            SELECT profile_id, name, description, payload, is_active,
                   created_at, updated_at
            FROM analytics_profiles
            WHERE is_active = TRUE
            ORDER BY updated_at DESC
            LIMIT 1
        """).fetchone()
        if row is None:
            return None
        return self._row_to_profile(row)

    # ------------------------------------------------------------------
    # Zaehler
    # ------------------------------------------------------------------
    def count(self) -> int:
        """Anzahl der gespeicherten Profile."""
        con = self._get_connection()
        res = con.execute("SELECT COUNT(*) FROM analytics_profiles").fetchone()
        return int(res[0]) if res and res[0] is not None else 0


# Bequeme Default-Instanz (kapselt app_data.duckdb) – fuer ViewModel/UI.
_profile_repo_default: Optional[AnalyticsProfileRepository] = None


def get_analytics_profile_repository() -> AnalyticsProfileRepository:
    """Liefert die app-weite Standard-Instanz (lazy, app_data.duckdb)."""
    global _profile_repo_default
    if _profile_repo_default is None:
        _profile_repo_default = AnalyticsProfileRepository()
    return _profile_repo_default
