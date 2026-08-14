# PROJEKT-ÜBERSICHT: PyTrader — Datenzugriff, Sync & Repositories

> Teil-Export (sachbezogen). Vollständiger Export: export_Full.md
> Dateien in dieser Datei: 11

## 1. ORDNERSTRUKTUR
```
PyTrader/
    analytics_profile_repository.py
    data_sync/
        __init__.py
        mt5_sync_service.py
    db/
        __init__.py
        db_pool.py
        schema_initializer.py
    repositories/
        __init__.py
        grabber_repository.py
        market_data_repository.py
    symbol_repository.py
    window_state_repository.py
```

## 2. QUELLCODE

### DATEI: analytics_profile_repository.py
```py
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

from db_service import DB_APP_DATA, DbPool, _parse_json_field

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

```

--------------------------------------------------

### DATEI: symbol_repository.py
```py
# symbol_repository.py
"""
symbol_repository.py - Symbol- & Favoriten-Repository (Phase 15.01).

Kapselt den Lese-/Schreibzugriff auf die `broker_symbols`-Tabelle in
`app_data.duckdb` – entkoppelt aus `state_manager.py` (SRP: Repository-
Schicht). Die UI (SymbolsWindow, ServiceWindow/AnalyticsWindow-Dropdowns)
greift ausschliesslich ueber dieses Repository auf Symbole zu.

Datenfluss (Invariante 4, Kein SQL in UI):
    DuckDB (broker_symbols) <-- SymbolRepository <-- UI-Fenster

Verhalten:
- `ensure_defaults()`    : legt SILVER/GOLD/BTCUSD als Favoriten an (idempotent).
- `sync_from_broker()`   : liest Symbole live via mt5.symbols_get() (lazy
  MT5-Import), schreibt sie per Upsert in die DB und gibt die DB-Liste
  zurueck. Bei MT5-Ausfall (initialize()==False / Exception) automatischer
  Fallback auf die DB-Tabelle – die App bleibt voll funktionsfaehig.
  Seit 15.01-Nachtrag 3 (04.08.2026) wird der Fetch NUR noch EINMALIG beim
  App-Start (main.py) aufgerufen – die UI-Fenster (SymbolsWindow) lesen
  ausschliesslich die gespeicherte Liste ueber `get_symbols()`.
- `toggle_favorite()`    : kippt das Favoriten-Flag eines Symbols.
"""

import os
from typing import Any, Dict, List, Optional, Tuple

from db_service import DB_APP_DATA, DbPool

# Komfort-Konstante fuer UI-Fallback (Dropdown nie leer), identisch zu den
# Defaults in db_service.check_and_init_databases().
DEFAULT_SYMBOLS: Tuple[str, ...] = ("SILVER", "GOLD", "BTCUSD")


class SymbolRepository:
    """Kapselt den Zugriff auf die broker_symbols-Tabelle (app_data.duckdb)."""

    def __init__(self, db_path: str = DB_APP_DATA) -> None:
        self.db_path = db_path
        self._ensure_table()

    # ------------------------------------------------------------------
    # Interne Helfer
    # ------------------------------------------------------------------
    def _get_connection(self):
        return DbPool.get(self.db_path)

    def _ensure_table(self) -> None:
        """Legt die Tabelle (falls noetig) an und stellt die Defaults sicher.

        Additiv/idempotent: bestehende Zeilen und Favoriten-Flags werden
        nicht angetastet (Verbotsregel: Bestandsdaten nicht beschädigen).
        """
        con = self._get_connection()
        con.execute("""
            CREATE TABLE IF NOT EXISTS broker_symbols (
                symbol      VARCHAR PRIMARY KEY,
                path        VARCHAR,
                is_favorite BOOLEAN DEFAULT FALSE,
                updated_at  TIMESTAMP DEFAULT current_timestamp
            );
        """)
        self.ensure_defaults()

    def ensure_defaults(self) -> None:
        """Legt SILVER/GOLD/BTCUSD als Favoriten an (falls noch nicht vorhanden)."""
        con = self._get_connection()
        con.execute("""
            INSERT INTO broker_symbols (symbol, path, is_favorite)
            VALUES ('SILVER', '', TRUE), ('GOLD', '', TRUE), ('BTCUSD', '', TRUE)
            ON CONFLICT (symbol) DO NOTHING;
        """)

    # ------------------------------------------------------------------
    # Lese-API
    # ------------------------------------------------------------------
    def get_symbols(self) -> List[Dict[str, Any]]:
        """Liefert alle Broker-Symbole (aufsteigend nach Name).

        Rückgabe: [{"symbol", "path", "is_favorite", "updated_at"}, ...]
        """
        con = self._get_connection()
        rows = con.execute("""
            SELECT symbol, path, is_favorite, updated_at
            FROM broker_symbols
            ORDER BY symbol ASC
        """).fetchall()
        return [
            {
                "symbol": str(r[0]),
                "path": str(r[1]) if r[1] is not None else "",
                "is_favorite": bool(r[2]),
                "updated_at": r[3],
            }
            for r in rows
        ]

    def get_favorite_symbols(self) -> List[str]:
        """Liefert nur die Favoriten-Symbole (is_favorite == TRUE), sortiert."""
        con = self._get_connection()
        rows = con.execute("""
            SELECT symbol FROM broker_symbols
            WHERE is_favorite = TRUE
            ORDER BY symbol ASC
        """).fetchall()
        return [str(r[0]) for r in rows]

    def get_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Liefert ein einzelnes Symbol (oder None)."""
        con = self._get_connection()
        row = con.execute("""
            SELECT symbol, path, is_favorite, updated_at
            FROM broker_symbols
            WHERE LOWER(symbol) = LOWER(?)
        """, [symbol]).fetchone()
        if row is None:
            return None
        return {
            "symbol": str(row[0]),
            "path": str(row[1]) if row[1] is not None else "",
            "is_favorite": bool(row[2]),
            "updated_at": row[3],
        }

    def count(self) -> int:
        """Anzahl der gespeicherten Symbole."""
        con = self._get_connection()
        res = con.execute("SELECT COUNT(*) FROM broker_symbols").fetchone()
        return int(res[0]) if res and res[0] is not None else 0

    # ------------------------------------------------------------------
    # Schreib-API
    # ------------------------------------------------------------------
    def toggle_favorite(self, symbol: str) -> bool:
        """Kippt das Favoriten-Flag eines Symbols.

        Args:
            symbol: Symbol-Name (case-insensitive).

        Returns:
            Der NEUE Favoriten-Zustand (True = jetzt Favorit).
            Ist das Symbol unbekannt, wird es mit is_favorite=TRUE angelegt.
        """
        con = self._get_connection()
        current = self.get_symbol(symbol)
        if current is None:
            con.execute("""
                INSERT INTO broker_symbols (symbol, path, is_favorite)
                VALUES (?, '', TRUE)
                ON CONFLICT (symbol) DO NOTHING;
            """, [symbol])
            return True
        new_state = not current["is_favorite"]
        con.execute("""
            UPDATE broker_symbols
            SET is_favorite = ?, updated_at = current_timestamp
            WHERE LOWER(symbol) = LOWER(?)
        """, [new_state, symbol])
        return new_state

    def upsert_from_broker(self, broker_symbols: List[Tuple[str, str]]) -> int:
        """Schreibt Broker-Symbole per Upsert in die DB.

        Bestehende Zeilen werden aktualisiert (path/updated_at), Favoriten-
        Flags bleiben dabei unangetastet (additiv, keine Datenverluste).

        Args:
            broker_symbols: Liste von (symbol, path)-Paaren aus MT5.

        Returns:
            Anzahl der verarbeiteten Symbole.
        """
        if not broker_symbols:
            return 0
        con = self._get_connection()
        seen: Dict[str, str] = {}
        for symbol, path in broker_symbols:
            sym = str(symbol).strip()
            if not sym:
                continue
            # Letzter Eintrag pro Symbol gewinnt (MT5 kann Duplikate liefern)
            seen[sym] = str(path or "")
        for sym, path in seen.items():
            con.execute("""
                INSERT INTO broker_symbols (symbol, path, is_favorite)
                VALUES (?, ?, FALSE)
                ON CONFLICT (symbol) DO UPDATE SET
                    path = EXCLUDED.path,
                    updated_at = DEFAULT;
            """, [sym, path])
        return len(seen)

    def sync_from_broker(self) -> List[Dict[str, Any]]:
        """Synchronisiert Symbole live aus MT5 (mit automatischem DB-Fallback).

        - Versucht mt5.symbols_get() (lazy import; schaltet MT5 NICHT ein,
          wenn das Terminal geschlossen ist).
        - Bei Erfolg: Upsert aller Symbole in die DB, Rückgabe der DB-Liste.
        - Bei MT5-Ausfall (initialize()==False, Exception): Fallback auf die
          DB-Tabelle – die App bleibt voll funktionsfaehig (Roadmap 15.01).

        Detaillierter Status (live/fallback + Fehlermeldung) ist ueber
        `sync_from_broker_with_status()` verfuegbar.
        """
        symbols, _status, _error = self.sync_from_broker_with_status()
        return symbols

    def sync_from_broker_with_status(self) -> Tuple[List[Dict[str, Any]], str, Optional[str]]:
        """Wie sync_from_broker(), liefert zusaetzlich Status & Fehlermeldung.

        Erweiterung fuer den App-Start-Sync (main.py, 15.01-Nachtrag 3): Die
        Liste aller verfuegbaren Symbole wird EINMALIG beim App-Start live von
        MT5 geladen; schlaegt der MT5-Zugriff fehl, wird der Grund als
        Fehlermeldung geliefert, damit der Aufrufer eine Log-Meldung ausgeben
        kann, statt still auf den DB-Stand zurueckzufallen. Die UI-Fenster
        (SymbolsWindow) rufen diese Methode seit Nachtrag 3 NICHT mehr auf –
        sie lesen ausschliesslich die gespeicherte Liste (get_symbols()).

        Returns:
            (symbols, status, error)
            - symbols: immer die DB-Symbol-Liste (Fallback inklusive).
            - status:  "live" bei erfolgreichem MT5-Fetch,
                       "fallback" bei MT5-Ausfall (DB-Stand).
            - error:   Fehlertext (oder None bei Erfolg).
        """
        try:
            import MetaTrader5 as _mt5
        except Exception as exc:
            return self.get_symbols(), "fallback", f"MetaTrader5-Import fehlgeschlagen: {exc}"

        try:
            initialized = bool(_mt5.initialize())
        except Exception as exc:
            return self.get_symbols(), "fallback", f"mt5.initialize() Fehler: {exc}"
        if not initialized:
            return self.get_symbols(), "fallback", "MT5-Terminal nicht verfügbar (initialize() == False)"

        try:
            symbols = _mt5.symbols_get()
        except Exception as exc:
            return self.get_symbols(), "fallback", f"mt5.symbols_get() Fehler: {exc}"
        if not symbols:
            return self.get_symbols(), "fallback", "MT5 liefert keine Symbole (symbols_get() leer)"

        try:
            pairs = [(s.name, getattr(s, "path", "")) for s in symbols]
            self.upsert_from_broker(pairs)
        except Exception as exc:
            return self.get_symbols(), "fallback", f"Upsert in broker_symbols fehlgeschlagen: {exc}"

        return self.get_symbols(), "live", None


# Bequeme Default-Instanz (kapselt app_data.duckdb) – fuer UI-Fenster.
_symbol_repo_default: Optional[SymbolRepository] = None


def get_symbol_repository() -> SymbolRepository:
    """Liefert die app-weite Standard-Instanz (lazy, gebunden an app_data.duckdb)."""
    global _symbol_repo_default
    if _symbol_repo_default is None:
        _symbol_repo_default = SymbolRepository()
    return _symbol_repo_default

```

--------------------------------------------------

### DATEI: window_state_repository.py
```py
# window_state_repository.py
"""
window_state_repository.py - Zentraler Repository-Zugriff auf die
instanz-/fensterbezogenen Tabellen der app_data.duckdb (Phase 15.04).

Kapselt die SQL-Zugriffe auf `window_instances`, `instance_states` UND
`symbol_tf_states` (alle instanz-/fensterbezogenen Tabellen – nicht nur die
zwei im Ursprungsentwurf genannten). Das Repository ist REIN lesend/
schreibend: Die Schema-Anlage und -Migration (DDL in `StateManager._init_db()`)
verbleibt im StateManager (keine Verantwortungs-Verdopplung).

Nutzt zwingend `DbPool.get(db_path)` (Thread-local, lock-frei, wie
StateManager) – KEINE eigene Connection-Verwaltung. Der DB-Pfad wird vom
StateManager (bzw. Test-Aufrufer) aufgelöst und an das Repository
durchgereicht, damit Test-Isolation (Temp-DBs unter test/) und die laufende
App strikt getrennt bleiben.

Phase 15.04: `state_manager.py` ist seitdem eine additive Fassade – alle
Bestands-Methoden delegieren intern an dieses Repository (identische
Signaturen, keine Aufrufer-Aenderung in main.py, persistent_win.py,
chart_win.py, service_win.py, Analytics, Tests).
"""

import json
import os
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd

from db_service import _parse_json_field, DbPool

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DB_PATH = os.path.join(BASE_DIR, "data", "app_data.duckdb")


class WindowStateRepository:
    """Kapselt die SQL-Zugriffe auf die instanz-/fensterbezogenen Tabellen.

    Methoden (Phase 15.04, Bestandsverhalten EXAKT reproduziert):
        save_window_geometry / get_window_geometry  (window_instances)
        save_instance_state / load_all_instances    (instance_states, join)
        delete_instance                             (beide Tabellen)
        get_next_instance_id                        (window_instances)
        save_symbol_tf_state / get_symbol_tf_state /
        delete_symbol_tf_state                      (symbol_tf_states)

    Das Repository fuehrt KEINE Schema-Anlage/-Migration durch – die
    Tabellenstruktur wird ausschliesslich vom StateManager (`_init_db()`)
    verwaltet (Invariante: keine Verantwortungs-Verdopplung).
    """

    def __init__(self, db_path: str = APP_DB_PATH) -> None:
        self.db_path = db_path

    # ------------------------------------------------------------------
    # Connection (Thread-local DbPool, lock-frei)
    # ------------------------------------------------------------------
    def _get_connection(self) -> duckdb.DuckDBPyConnection:
        return DbPool.get(self.db_path)

    # ------------------------------------------------------------------
    # window_instances: Geometrie
    # ------------------------------------------------------------------
    def save_window_geometry(
        self,
        instance_id: str,
        x: int,
        y: int,
        width: int,
        height: int,
        is_maximized: bool,
        preset_id: Optional[str] = None
    ) -> None:
        con = self._get_connection()
        con.execute("""
            INSERT INTO window_instances (
                instance_id, preset_id, window_title, pos_x, pos_y, width, height, is_maximized
            ) VALUES (?, ?, 'PyTrader Window', ?, ?, ?, ?, ?)
            ON CONFLICT (instance_id) DO UPDATE SET
                pos_x = EXCLUDED.pos_x,
                pos_y = EXCLUDED.pos_y,
                width = EXCLUDED.width,
                height = EXCLUDED.height,
                is_maximized = EXCLUDED.is_maximized,
                preset_id = EXCLUDED.preset_id;
        """, [instance_id, preset_id, x, y, width, height, is_maximized])

    def get_window_geometry(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Liest die gespeicherte Fenstergeometrie einer spezifischen Instanz aus."""
        con = self._get_connection()
        res = con.execute("""
            SELECT pos_x, pos_y, width, height, is_maximized
            FROM window_instances
            WHERE instance_id = ?
        """, [instance_id]).fetchone()
        if res and res[0] is not None:
            return {
                "pos_x": res[0],
                "pos_y": res[1],
                "width": res[2],
                "height": res[3],
                "is_maximized": bool(res[4])
            }
        return None

    def get_next_instance_id(self) -> str:
        con = self._get_connection()
        res = con.execute("SELECT instance_id FROM window_instances").fetchall()
        existing_ids = [r[0] for r in res]
        count = 1
        while f"win_{count}" in existing_ids:
            count += 1
        return f"win_{count}"

    # ------------------------------------------------------------------
    # instance_states: Instanz-Zustand (Symbol/Timeframe/Viewport/Indikatoren)
    # ------------------------------------------------------------------
    def save_instance_state(
        self,
        instance_id: str,
        symbol: str,
        timeframe: str,
        visible_range_from: Optional[int] = None,
        visible_range_to: Optional[int] = None,
        visible_price_from: Optional[float] = None,
        visible_price_to: Optional[float] = None,
        indicators_state: Optional[Dict[str, Any]] = None,
        measurement_state: Optional[Dict[str, Any]] = None
    ) -> None:
        con = self._get_connection()
        ind_json = json.dumps(indicators_state) if indicators_state is not None else None
        meas_json = json.dumps(measurement_state) if measurement_state is not None else None
        con.execute("""
            INSERT INTO instance_states (
                instance_id, symbol, timeframe, visible_range_from, visible_range_to,
                visible_price_from, visible_price_to, indicators_state, measurement_state, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (instance_id) DO UPDATE SET
                symbol = EXCLUDED.symbol,
                timeframe = EXCLUDED.timeframe,
                visible_range_from = EXCLUDED.visible_range_from,
                visible_range_to = EXCLUDED.visible_range_to,
                visible_price_from = EXCLUDED.visible_price_from,
                visible_price_to = EXCLUDED.visible_price_to,
                indicators_state = EXCLUDED.indicators_state,
                measurement_state = EXCLUDED.measurement_state,
                updated_at = EXCLUDED.updated_at;
        """, [
            instance_id, symbol, timeframe, visible_range_from, visible_range_to,
            visible_price_from, visible_price_to, ind_json, meas_json
        ])

    def load_all_instances(self) -> List[Dict[str, Any]]:
        """Reproduziert das Bestandsverhalten EXAKT (pandas-`.df()`-Leseart +
        String-Normalisierung von symbol/timeframe)."""
        con = self._get_connection()
        query = """
            SELECT
                w.instance_id, w.preset_id, w.pos_x, w.pos_y, w.width, w.height, w.is_maximized,
                CAST(s.symbol AS VARCHAR) AS symbol,
                CAST(s.timeframe AS VARCHAR) AS timeframe,
                s.visible_range_from, s.visible_range_to,
                s.visible_price_from, s.visible_price_to, s.indicators_state, s.measurement_state,
                s.updated_at
            FROM window_instances w
            LEFT JOIN instance_states s ON w.instance_id = s.instance_id
            ORDER BY s.updated_at ASC;
        """
        df = con.execute(query).df()
        records = df.to_dict(orient="records")
        for rec in records:
            if "symbol" in rec and rec["symbol"] is not None and not isinstance(rec["symbol"], str):
                rec["symbol"] = str(rec["symbol"]) if not pd.isna(rec["symbol"]) else None
            if "timeframe" in rec and rec["timeframe"] is not None and not isinstance(rec["timeframe"], str):
                rec["timeframe"] = str(rec["timeframe"]) if not pd.isna(rec["timeframe"]) else None
        return records

    def delete_instance(self, instance_id: str) -> None:
        con = self._get_connection()
        con.execute("DELETE FROM instance_states WHERE instance_id = ?", [instance_id])
        con.execute("DELETE FROM window_instances WHERE instance_id = ?", [instance_id])

    # ------------------------------------------------------------------
    # symbol_tf_states: Symbol-/Timeframe-Zustand (Viewport/Indikatoren)
    # ------------------------------------------------------------------
    def save_symbol_tf_state(
        self,
        symbol: str,
        timeframe: str,
        visible_range_from: Optional[int] = None,
        visible_range_to: Optional[int] = None,
        visible_price_from: Optional[float] = None,
        visible_price_to: Optional[float] = None,
        indicators_state: Optional[Dict[str, Any]] = None,
        measurement_state: Optional[Dict[str, Any]] = None
    ) -> None:
        con = self._get_connection()
        ind_json = json.dumps(indicators_state) if indicators_state is not None else None
        meas_json = json.dumps(measurement_state) if measurement_state is not None else None
        con.execute("""
            INSERT INTO symbol_tf_states (
                symbol, timeframe, visible_range_from, visible_range_to,
                visible_price_from, visible_price_to, indicators_state, measurement_state, updated_at
            ) VALUES (CAST(? AS VARCHAR), CAST(? AS VARCHAR), ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (symbol, timeframe) DO UPDATE SET
                visible_range_from = EXCLUDED.visible_range_from,
                visible_range_to = EXCLUDED.visible_range_to,
                visible_price_from = EXCLUDED.visible_price_from,
                visible_price_to = EXCLUDED.visible_price_to,
                indicators_state = EXCLUDED.indicators_state,
                measurement_state = EXCLUDED.measurement_state,
                updated_at = EXCLUDED.updated_at;
        """, [
            symbol, timeframe, visible_range_from, visible_range_to,
            visible_price_from, visible_price_to, ind_json, meas_json
        ])

    def get_symbol_tf_state(self, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
        con = self._get_connection()
        res = con.execute("""
            SELECT visible_range_from, visible_range_to, visible_price_from, visible_price_to, indicators_state, measurement_state
            FROM symbol_tf_states
            WHERE symbol = CAST(? AS VARCHAR) AND timeframe = CAST(? AS VARCHAR)
        """, [symbol, timeframe]).fetchone()

        if res:
            v_from, v_to, p_from, p_to, ind_json, meas_json = res
            ind_state = _parse_json_field(ind_json)
            meas_state = _parse_json_field(meas_json)
            return {
                "visible_range_from": v_from,
                "visible_range_to": v_to,
                "visible_price_from": p_from,
                "visible_price_to": p_to,
                "indicators_state": ind_state,
                "measurement_state": meas_state
            }
        return None

    def delete_symbol_tf_state(self, symbol: str, timeframe: str) -> None:
        con = self._get_connection()
        con.execute(
            "DELETE FROM symbol_tf_states WHERE symbol = CAST(? AS VARCHAR) AND timeframe = CAST(? AS VARCHAR)",
            [symbol, timeframe]
        )

    # ------------------------------------------------------------------
    # workspace_state: Fenster-Workspace (Phase 20.01, win_analytics)
    # ------------------------------------------------------------------
    def save_workspace_state(
        self, instance_id: str, state: Dict[str, Any]
    ) -> None:
        """Upsertet `workspace_state` (JSON) auf die instance_states-Zeile.

        Phase 20.01 (E6, NOT-NULL-konform): `instance_states.symbol`/
        `timeframe` sind NOT NULL. Fuer eine noch nicht existierende Row
        werden die bestehenden Werte uebernommen (Fallback ''/'M1'), damit
        der reine Workspace-Upsert keinen NOT-NULL-Constraint verletzt.
        Vorhandene symbol/timeframe/indicator-Zustaende bleiben unberuehrt
        (ON CONFLICT aktualisiert nur workspace_state + updated_at).
        """
        con = self._get_connection()
        existing = con.execute(
            "SELECT symbol, timeframe FROM instance_states "
            "WHERE instance_id = ?",
            [instance_id],
        ).fetchone()
        symbol = str(existing[0]) if existing and existing[0] is not None else ""
        timeframe = (
            str(existing[1]) if existing and existing[1] is not None else "M1"
        )
        con.execute("""
            INSERT INTO instance_states (
                instance_id, symbol, timeframe, workspace_state, updated_at
            ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (instance_id) DO UPDATE SET
                workspace_state = EXCLUDED.workspace_state,
                updated_at = EXCLUDED.updated_at;
        """, [instance_id, symbol, timeframe, json.dumps(state)])

    def get_workspace_state(
        self, instance_id: str
    ) -> Optional[Dict[str, Any]]:
        """Liest den gespeicherten Fenster-Workspace einer Instanz (oder None).

        Workspace-Payload (Phase 20.01, E7):
            {"params": {...}, "layout": {"page_index": n}}
        """
        con = self._get_connection()
        row = con.execute(
            "SELECT workspace_state FROM instance_states "
            "WHERE instance_id = ?",
            [instance_id],
        ).fetchone()
        if row and row[0] is not None:
            parsed = _parse_json_field(row[0])
            return parsed if isinstance(parsed, dict) else None
        return None

```

--------------------------------------------------

### DATEI: data_sync/__init__.py
```py
# data_sync/__init__.py
"""
data_sync-Paket (18.01.02, E3): MT5-Synchronisation.

  * mt5_sync_service.py – get_timeframes, TF_SECONDS_MAP, MT5_LOCK,
                          check_mt5_connection, get_latest_timestamp, sync_market_data

Importiert nur die db-Basisschicht (E4); kein Import von main.py/db_service.py.
"""

```

--------------------------------------------------

### DATEI: data_sync/mt5_sync_service.py
```py
# data_sync/mt5_sync_service.py
"""
data_sync/mt5_sync_service.py - MT5-Sync-Service (Zeitrahmen, Verbindung, Import).

Ausgelagert aus db_service.py im Rahmen von 18.01.02 (E3): SYMBOLS,
get_timeframes/TF_SECONDS_MAP/MT5_LOCK (MT5-Konfiguration),
check_mt5_connection (Verbindungspruefung), get_latest_timestamp und
sync_market_data (Voll-/Update-Import der MT5-Historie).

Lazy-Import-Prinzip (E3): `MetaTrader5` wird weiterhin erst beim Aufruf
importiert – kein MT5-DLL-Load beim Modul-Import.

Abhaengigkeiten (E4): db/db_pool (DB_MARKET_DATA, db_connect),
db/schema_initializer (check_and_init_databases).
"""

import threading
import time
from typing import Dict, List, Optional, Set, Tuple

import duckdb
import pandas as pd

from db.db_pool import DB_MARKET_DATA, db_connect
from db.schema_initializer import check_and_init_databases

SYMBOLS = ["SILVER", "GOLD", "BTCUSD"]

# TIMEFRAMES als Lazy-Initialisierung (vermeidet MT5-DLL-Load beim Import)
_TIMEFRAMES_CACHE: Optional[Dict[str, int]] = None


def get_timeframes() -> Dict[str, int]:
    """Gibt das Timeframe-Mapping zurueck (lazy, importiert mt5 nur bei Bedarf)."""
    global _TIMEFRAMES_CACHE
    if _TIMEFRAMES_CACHE is None:
        import MetaTrader5 as _mt5
        _TIMEFRAMES_CACHE = {
            "MN1": _mt5.TIMEFRAME_MN1,
            "W1": _mt5.TIMEFRAME_W1,
            "D1": _mt5.TIMEFRAME_D1,
            "H4": _mt5.TIMEFRAME_H4,
            "H1": _mt5.TIMEFRAME_H1,
            "M30": _mt5.TIMEFRAME_M30,
            "M15": _mt5.TIMEFRAME_M15,
            "M10": _mt5.TIMEFRAME_M10,
            "M5": _mt5.TIMEFRAME_M5,
            "M2": _mt5.TIMEFRAME_M2,
            "M1": _mt5.TIMEFRAME_M1,
        }
    return _TIMEFRAMES_CACHE

TF_SECONDS_MAP: Dict[str, int] = {
    "M1": 60,
    "M2": 120,
    "M5": 300,
    "M10": 600,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
    "W1": 604800,
    "MN1": 2592000,
}

MT5_LOCK = threading.Lock()


# ==============================================================================
# 2) MT5 VERBINDUNG PRÜFEN
# ==============================================================================
def check_mt5_connection() -> None:
    """Prüft die MT5-Verbindung mit abgesicherter Fehlerbehandlung (lazy mt5 import)."""
    import MetaTrader5 as _mt5

    print("\n🔗 [2/3] Prüfe MT5-Verbindung...")

    with MT5_LOCK:
        if not _mt5.initialize():
            error_code = _mt5.last_error()
            try:
                _mt5.shutdown()
            except Exception:
                pass
            raise SystemExit(
                f"❌ KRITISCHER FEHLER: MT5-Verbindung fehlgeschlagen!\n"
                f"   Fehlercode: {error_code}\n"
                f"   Bitte stelle sicher, dass das MT5 Terminal geöffnet und eingeloggt ist."
            )

        account = _mt5.account_info()
        if account is None:
            try:
                _mt5.shutdown()
            except Exception:
                pass
            raise SystemExit("❌ KRITISCHER FEHLER: Im MT5-Terminal ist kein Konto eingeloggt!")

        for symbol in SYMBOLS:
            if not _mt5.symbol_select(symbol, True):
                try:
                    _mt5.shutdown()
                except Exception:
                    pass
                raise SystemExit(f"❌ KRITISCHER FEHLER: Symbol '{symbol}' konnte im MT5 nicht aktiviert werden.")

    print(f"   ✅ Verbunden mit Broker: {account.company} (Server: {account.server}, Login: {account.login})")


# ==============================================================================
# 3 & 4) DATEN HILFSFUNKTIONEN & IMPORT-SCHLEIFE
# ==============================================================================
def get_latest_timestamp(con: duckdb.DuckDBPyConnection, symbol: str, timeframe_str: str) -> Optional[datetime]:
    """Liefert den neuesten Zeitstempel eines Symbol/Timeframe in ohlcv_bars."""
    res = con.execute("""
        SELECT MAX(time)
        FROM ohlcv_bars
        WHERE symbol = ? AND timeframe = ?
    """, [symbol, timeframe_str]).fetchone()

    return res[0] if res and res[0] is not None else None


def sync_market_data(target_pairs: Optional[Set[Tuple[str, str]]] = None) -> Set[Tuple[str, str]]:
    """Synchronisiert die MT5-Historie (VOLLIMPORT oder UPDATE) je Symbol/Timeframe.

    Phase 21.03.22 (Full Market-Data Sync Button): Optionaler `target_pairs`-
    Filter. Ist das Set uebergeben (nicht None), werden exakt diese
    (symbol, timeframe)-Paare synchronisiert (statt des Standard-Rasters);
    bei None/leer greift der Fallback auf das bisherige Standard-Raster
    (SYMBOLS x get_timeframes()). Der Delta-Sync-Abgleich via
    get_latest_timestamp() bleibt pro Paar voll erhalten.
    """
    import MetaTrader5 as _mt5
    timeframes = get_timeframes()

    check_and_init_databases()
    check_mt5_connection()

    # 21.03.22: Paar-Filter (UPPER-normalisiert, unbekannte Timeframes
    # werden ignoriert); None/leer -> Standard-Raster (Abwaertskompatibilitaet).
    filtered_pairs: Optional[Set[Tuple[str, str]]] = None
    symbols_to_sync: List[str] = list(SYMBOLS)
    if target_pairs:
        filtered_pairs = {
            (str(s).upper(), str(tf).upper())
            for s, tf in target_pairs
            if str(tf).upper() in timeframes
        }
        symbols_to_sync = sorted({s for s, _ in filtered_pairs})

    print(f"\n📥 [3/3] Starte Synchronisation für {', '.join(symbols_to_sync)} über {len(timeframes)} Timeframes...")

    start_time_total = time.perf_counter()
    total_bars_downloaded = 0
    updated_pairs: Set[Tuple[str, str]] = set()

    for symbol in symbols_to_sync:
        print(f"\n--- Synchronisiere {symbol} ---")
        # Connection pro Symbol öffnen/schließen, damit andere Threads (LiveTickWorker)
        # zwischendurch ebenfalls auf die DB zugreifen können
        con = db_connect(DB_MARKET_DATA)
        try:
            for tf_str, tf_mt5 in timeframes.items():
                # 21.03.22: Bei target_pairs-Filter exakt diese Paare abgleichen.
                if filtered_pairs is not None and (symbol, tf_str) not in filtered_pairs:
                    continue
                tf_start = time.perf_counter()

                last_time = get_latest_timestamp(con, symbol, tf_str)

                with MT5_LOCK:
                    if last_time is not None:
                        rates = _mt5.copy_rates_from_pos(symbol, tf_mt5, 0, 5_000)
                        update_type = "UPDATE"
                    else:
                        rates = _mt5.copy_rates_from_pos(symbol, tf_mt5, 0, 10_000_000)
                        update_type = "VOLLIMPORT"

                    if rates is None:
                        err = _mt5.last_error()
                        print(f"   [--] {tf_str:<4} | MT5 Fehler beim Abrufen der Kerzen: {err}")
                        continue

                if len(rates) == 0:
                    print(f"   [--] {tf_str:<4} | Keine Kerzen von MT5 empfangen.")
                    continue

                df = pd.DataFrame(rates)
                df["symbol"] = symbol
                df["timeframe"] = tf_str
                df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                df = df.drop_duplicates(subset=["time"], keep="last")

                df_to_insert = df[
                    [
                        "symbol",
                        "timeframe",
                        "time",
                        "open",
                        "high",
                        "low",
                        "close",
                        "tick_volume",
                        "spread",
                        "real_volume",
                    ]
                ]

                con.register("df_temp", df_to_insert)

                # NATIVE UPSERT VIA PRIMÄRSCHLÜSSEL (symbol, timeframe, time)
                con.execute("""
                    INSERT OR REPLACE INTO ohlcv_bars (
                        symbol, timeframe, time, open, high, low, close, tick_volume, spread, real_volume
                    )
                    SELECT
                        symbol, timeframe, "time", open, high, low, close, tick_volume, spread, real_volume
                    FROM df_temp
                """)

                con.unregister("df_temp")

                tf_elapsed = time.perf_counter() - tf_start
                bars_count = len(df_to_insert)
                total_bars_downloaded += bars_count

                if bars_count > 0:
                    updated_pairs.add((symbol, tf_str))

                print(f"   [✅] {tf_str:<4} | {update_type:<10} | {bars_count:>8,} Kerzen verarbeitet in {tf_elapsed:.2f}s")
        finally:
            con.close()

    total_elapsed = time.perf_counter() - start_time_total

    print("\n" + "=" * 60)
    print("⏱️  ERGEBNIS & ZEITMESSUNG")
    print("=" * 60)
    print(f"Gesamtdauer Process:    {total_elapsed:.2f} Sekunden")
    print(f"Gesamtanzahl Kerzen:    {total_bars_downloaded:,}")
    print(f"Durchschnittliche Rate: {total_bars_downloaded / max(total_elapsed, 0.001):,.0f} Kerzen/Sekunde")
    print("=" * 60)
    return updated_pairs

```

--------------------------------------------------

### DATEI: db/__init__.py
```py
# db/__init__.py
"""
db-Paket (18.01.02, E3): Datenbank-Basisschicht.

  * db_pool.py            – DbPool, db_connect, _LockedConnection, with_db_lock, DB-Pfade
  * db_utils.py           – _parse_json_field, _ensure_epoch
  * schema_initializer.py – check_and_init_databases

Kein Modul dieses Pakets importiert main.py oder db_service.py (E4).
"""

```

--------------------------------------------------

### DATEI: db/db_pool.py
```py
# db/db_pool.py
"""
db/db_pool.py - Thread-lokaler DuckDB-Verbindungspool & DB-Pfad-Konstanten.

Ausgelagert aus db_service.py im Rahmen von 18.01.02 (Refactoring &
Modularisierung, Pruefprotokoll-Entscheidung E3). Enthaelt:

  * `DATA_DIR` / `DB_MARKET_DATA` / `DB_ANALYTICS` / `DB_APP_DATA` (Pfad-Konstanten)
  * `DbPool` (Thread-local Singleton: eine Connection pro Thread & DB-Datei)
  * `_LockedConnection` (LEGACY-Wrapper) und `db_connect` (LEGACY)
  * `with_db_lock` (No-op Decorator, API-Kompatibilitaet)

Basis-Schicht (E4): kein Import anderer Projekt-Module.
"""

import datetime
import os
import shutil
import threading
from typing import Dict

import duckdb

# ==============================================================================
# CONFIGURATION & THREAD SAFETY
# ==============================================================================
DATA_DIR = "data"
DB_MARKET_DATA = os.path.join(DATA_DIR, "market_data.duckdb")
DB_ANALYTICS = os.path.join(DATA_DIR, "analytics.duckdb")
DB_APP_DATA = os.path.join(DATA_DIR, "app_data.duckdb")

# ==============================================================================
# DB LOCK-FREIER CONNECTION-HELPER
# ==============================================================================
# DuckDB unterstützt Multiple Connections innerhalb eines Prozesses nativ.
# Threading-Locks sind hier kontraproduktiv, da sie z. B. eine dauerhaft
# offene Haupt-Connection (self.db in MainWindow) blockieren.
# Cross-Prozess-Konflikte (IO Error: file is already open) werden durch
# sauberes Beenden vorheriger Prozesse gelöst, nicht durch threading.Lock.


def with_db_lock(db_path: str):
    """No-op decorator (Lock-frei). Beibehalten für API-Kompatibilität."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ==============================================================================
# DB CONNECTION POOL (Thread-local Singleton) – eine Connection pro Thread & DB
# ==============================================================================
# Loest drei Kernprobleme unter Windows:
#   1. "Can't open a connection with a different configuration" – immer gleiche Config
#   2. "Cannot open file – file used by another process" – keine Open/Close-Zyklen
#   3. DuckDB-Connections sind nicht thread-safe – eigenes Connection pro Thread
#
# Nutzung: DbPool.get(db_path) statt db_connect(db_path)
# Connections werden automatisch via atexit geschlossen.

_db_pool_lock = threading.Lock()
_db_pool_global: Dict[str, int] = {}  # abs_path -> Referenzzähler (fuer atexit)


class DbPool:
    """Thread-sicherer Connection-Pool: eine persistente Connection pro Thread & DB-Datei."""

    _local = threading.local()

    @staticmethod
    def _open_with_wal_recovery(abs_path: str) -> duckdb.DuckDBPyConnection:
        """Oeffnet eine DuckDB-Connection mit defensivem WAL-Recovery.

        Bugfix 09.08.2026 (wiederkehrender Start-Abbruch unter Windows):
        `duckdb.connect()` schlug mit "INTERNAL Error: Failure while replaying
        WAL file .../analytics.duckdb.wal: Calling DatabaseManager::
        GetDefaultDatabase with no default database set" fehl, wenn die WAL
        (z. B. durch hartes Beenden der App) korrupt war. Statt die gesamte
        App am Start scheitern zu lassen, wird die korrupte WAL-Datei unter
        `<db>.wal.corrupt_<YYYYMMDD_HHMMSS>` wegsichert und der Connect
        erneut versucht. Verloren gehen dabei nur un-checkpointete
        Transaktionen – die Haupt-DB (letzter Checkpoint) bleibt intakt.

        Raises:
            Exception: Wenn auch der zweite Versuch fehlschlaegt (kein
                WAL-Problem oder die DB selbst ist beschädigt).
        """
        try:
            return duckdb.connect(abs_path)
        except duckdb.InternalException as exc:
            if "Failure while replaying WAL" not in str(exc):
                raise
            wal_path = abs_path + ".wal"
            if os.path.exists(wal_path):
                stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                corrupt_path = f"{wal_path}.corrupt_{stamp}"
                try:
                    shutil.move(wal_path, corrupt_path)
                except OSError:
                    # Wegsichern fehlgeschlagen (z. B. Datei gesperrt) –
                    # dann wenigstens umbenennen, sonst Retry schlaegt erneut fehl.
                    try:
                        os.replace(wal_path, corrupt_path)
                    except OSError:
                        pass
            # Zweiter Versuch nach Entfernen der korrupten WAL.
            return duckdb.connect(abs_path)

    @staticmethod
    def get(db_path: str) -> duckdb.DuckDBPyConnection:
        """Gibt eine persistente Connection zur DB-Datei zurueck (eine pro Thread).
        Die Connection lebt bis Prozess-Ende und wird nie geschlossen."""
        abs_path = os.path.abspath(db_path)
        # Thread-local Storage: Jeder Thread hat seine eigenen Connections
        if not hasattr(DbPool._local, 'conns'):
            DbPool._local.conns = {}
        if abs_path not in DbPool._local.conns:
            DbPool._local.conns[abs_path] = DbPool._open_with_wal_recovery(abs_path)
            # Globalen Referenzzähler erhöhen (für atexit)
            with _db_pool_lock:
                if _db_pool_global.get(abs_path, 0) == 0:
                    import atexit
                    atexit.register(lambda p=abs_path: DbPool._close_all_for(p))
                _db_pool_global[abs_path] = _db_pool_global.get(abs_path, 0) + 1
        return DbPool._local.conns[abs_path]

    @staticmethod
    def _close_all_for(abs_path: str) -> None:
        """Schliesst ALLE Connections zu einer DB-Datei (fuer atexit)."""
        # Kann nur die Connections des aktuellen Threads schliessen
        if hasattr(DbPool._local, 'conns'):
            con = DbPool._local.conns.pop(abs_path, None)
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass

    @staticmethod
    def close_all() -> None:
        """Schliesst ALLE Connections des aktuellen Threads.

        Dekrementiert dabei den globalen Referenzzaehler, damit der
        atexit-Bookkeeping-Dict (Fix 15.03, Worker-Connection-Leak) nicht
        unbegrenzt waechst. Wird u. a. von AnalyticsAsyncWorker nach jeder
        Abfrage aufgerufen (Worker-Thread gibt seine Connection frei; ein
        neuer Worker-Thread erhaelt automatisch eine frische Connection).
        """
        if hasattr(DbPool._local, 'conns'):
            for abs_path in list(DbPool._local.conns.keys()):
                try:
                    DbPool._local.conns[abs_path].close()
                except Exception:
                    pass
                with _db_pool_lock:
                    _db_pool_global[abs_path] = max(
                        0, _db_pool_global.get(abs_path, 0) - 1)
            DbPool._local.conns = {}

    @staticmethod
    def release(abs_path: str) -> None:
        """Schliesst die Connection des aktuellen Threads zu EINER DB-Datei.

        Phase 21.02 (12.08.2026): Benoetigt fuer den Datei-Ersatz bei der
        Kompaktierung (Windows File-Locking). Anders als `close_all()`
        bleiben Connections zu anderen DB-Dateien (z. B. app_data.duckdb)
        unangetastet. Die Connection wird beim naechsten `DbPool.get()`
        lazy wieder geoeffnet (Referenzzaehler wird dekrementiert).
        """
        abs_path = os.path.abspath(abs_path)
        if hasattr(DbPool._local, 'conns'):
            con = DbPool._local.conns.pop(abs_path, None)
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
                with _db_pool_lock:
                    _db_pool_global[abs_path] = max(
                        0, _db_pool_global.get(abs_path, 0) - 1)


class _LockedConnection:
    """Wrapper um DuckDBPyConnection (LEGACY – nur noch fuer sync_market_data & MarketDataRepository).
    Oeffnet/schliesst die Connection bei jedem Aufruf.
    """

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self._con = con

    def __getattr__(self, name):
        return getattr(self._con, name)

    def close(self):
        try:
            self._con.close()
        finally:
            pass


def db_connect(db_path: str, read_only: bool = False) -> _LockedConnection:
    """LEGACY: Oeffnet eine neue Connection (wird geschlossen nach Gebrauch).

    Warnung: Nicht fuer haeufige Zugriffe verwenden!
    Nutze stattdessen: DbPool.get(db_path)
    """
    con = duckdb.connect(db_path, read_only=read_only)
    return _LockedConnection(con)

```

--------------------------------------------------

### DATEI: db/schema_initializer.py
```py
# db/schema_initializer.py
"""
db/schema_initializer.py - Pruefen, Anlegen & Migrieren der Kern-Datenbanken.

Ausgelagert aus db_service.py im Rahmen von 18.01.02 (E3): `check_and_init_databases`
legt die drei DuckDB-Dateien (market_data, analytics, app_data) mit ihrem
Schema idempotent an und fuehrt additive Migrationen aus. Importiert die
Basis-Schicht db/db_pool (E4); kein MT5-Import (Lazy-Import-Prinzip).
"""

import os

from db.db_pool import DATA_DIR, DB_ANALYTICS, DB_APP_DATA, DB_MARKET_DATA, DbPool


def check_and_init_databases() -> None:
    """Prüft, initialisiert und migriert die Kern-Datenbanken bei Bedarf."""
    print("🔍 [1/3] Prüfe und initialisiere Ordnerstruktur und Datenbanken...")
    os.makedirs(DATA_DIR, exist_ok=True)

    con_market = DbPool.get(DB_MARKET_DATA)
    con_market.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv_bars (
            symbol      VARCHAR NOT NULL,
            timeframe   VARCHAR NOT NULL,
            time        TIMESTAMPTZ NOT NULL,
            open        DOUBLE NOT NULL,
            high        DOUBLE NOT NULL,
            low         DOUBLE NOT NULL,
            close       DOUBLE NOT NULL,
            tick_volume BIGINT,
            spread      INTEGER,
            real_volume BIGINT,
            created_at  TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (symbol, timeframe, time)
        );
    """)

    try:
        col_type_row = con_market.execute("""
            SELECT data_type
            FROM information_schema.columns
            WHERE LOWER(table_name) = 'ohlcv_bars' AND LOWER(column_name) = 'time'
        """).fetchone()

        if col_type_row and col_type_row[0].upper() == "TIMESTAMP":
            print("⚠️ [MIGRATION] Konvertiere 'time' Spalte in ohlcv_bars von TIMESTAMP zu TIMESTAMPTZ...")
            con_market.execute("ALTER TABLE ohlcv_bars ALTER time TYPE TIMESTAMPTZ")
            print("✅ [MIGRATION] Konvertierung erfolgreich abgeschlossen.")
    except Exception as e:
        print(f"⚠️ [MIGRATION WARNUNG] Migration konnte nicht durchgeführt werden: {e}")

    con_analytics = DbPool.get(DB_ANALYTICS)
    con_analytics.execute("""
        CREATE TABLE IF NOT EXISTS analytics_metadata (
            created_at TIMESTAMP DEFAULT current_timestamp,
            info VARCHAR
        );
    """)

    # Analytics-Tabelle für Feature-/Plugin-Daten
    # 17.01 (E-1, 07.08.2026): 4-Spalten-PK (symbol, timeframe, bar_time,
    # feature_id) – erlaubt die konfliktfreie Speicherung MEHRERER Services auf
    # derselben Kerze (feature_id identifiziert das erzeugende Plugin, Default
    # 'native' fuer den klassischen Feature-Builder-Pfad). Bei bestehenden DBs
    # ist CREATE TABLE IF NOT EXISTS ein No-op; die Migration existierender
    # Tabellen erfolgt ueber test/migrate_pk.py (Table-Rewrite + RENAME, da
    # DuckDB 1.5.5 kein DROP PRIMARY KEY unterstuetzt).
    # 19.02 (Cleanup): Die Legacy-Native-Spalten ema_diff/rsi_14/
    # atr_normalized entfallen im NEUSCHEMA – alle Feature-Werte liegen im
    # feature_data-JSON. Bestehende DB-Dateien (mit den Alt-Spalten) werden
    # durch den Additiv-Pfad (ALTER TABLE ADD COLUMN IF NOT EXISTS) nicht
    # angetastet; der Reader greift nur noch auf feature_data zu.
    con_analytics.execute("""
        CREATE TABLE IF NOT EXISTS feature_store (
            symbol      VARCHAR NOT NULL,
            timeframe   VARCHAR NOT NULL,
            bar_time    TIMESTAMPTZ NOT NULL,
            created_at  TIMESTAMP DEFAULT current_timestamp,
            feature_id  VARCHAR NOT NULL DEFAULT 'native',
            plugin_version VARCHAR,
            feature_data JSON,
            instance_hash VARCHAR NOT NULL DEFAULT '',
            PRIMARY KEY (symbol, timeframe, bar_time, feature_id,
                         instance_hash)
        );
    """)

    # Phase 12 (Hybrid-Schema): Additive Erweiterung des feature_store um die
    # Plugin-Architektur. feature_id identifiziert das erzeugende Plugin
    # (z.B. 'srv_grid_lines'), plugin_version dessen Version und feature_data
    # haelt den vollstaendigen FeatureStorePayload (JSON). Bestehende Spalten
    # und Daten bleiben unangetastet.
    con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_id VARCHAR;")
    con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS plugin_version VARCHAR;")
    con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS feature_data JSON;")
    # 20.04 (Q1/Q9, 09.08.2026): Additive Spalte instance_hash – stabile
    # Identifikation von Parameter-Varianten eines Plugins (8-stelliger
    # SHA256-Short-Hash aus generate_instance_hash, ohne lookback – Q3).
    # Ermoeglicht Multi-Varianten-Statistiken und gezieltes Daten-Purge
    # (purge_instance_data, Q5), ohne die feature_id (plugin_id) anzutasten.
    # Bestehende Rows bleiben NULL; feature_id bleibt plugin_id (Zero-Regression).
    con_analytics.execute("ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS instance_hash VARCHAR;")
    # 11.08.2026 (Bugfix Varianten-Kollision): Der feature_store-PK wird um
    # instance_hash erweitert - (symbol, timeframe, bar_time, feature_id,
    # instance_hash). Damit koexistieren Parameter-Varianten eines Plugins
    # auf derselben Bar (vorher ueberschrieb der letzte Lauf die gemeinsame
    # Row; Kontextmenue-Run + Ausfuehrungsdatum trafen alle Varianten
    # gemeinsam). DuckDB 1.5.5 kann PRIMARY KEY nicht AENDERN - Migration als
    # Table-Rewrite (CREATE TABLE AS + EXCLUDE/COALESCE) + ALTER SET NOT
    # NULL/SET DEFAULT + ALTER ADD PRIMARY KEY + DROP/RENAME. Idempotent:
    # laeuft nur, wenn der aktuelle PK noch KEIN instance_hash enthaelt.
    try:
        _pk_rows = con_analytics.execute(
            "SELECT constraint_column_indexes FROM duckdb_constraints() "
            "WHERE table_name='feature_store' "
            "AND constraint_type='PRIMARY KEY'").fetchall()
        _fs_cols = [r[0].lower() for r in con_analytics.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='feature_store' ORDER BY ordinal_position"
        ).fetchall()]
        # duckdb_constraints liefert pro Zeile ein Tupel (index_list,) -
        # der Spalten-Index liegt in Zeile[0].
        _pk_has_hash = any(
            _fs_cols[i].lower() == "instance_hash"
            for _row in _pk_rows for i in (_row[0] or []))
        if not _pk_has_hash:
            con_analytics.execute("""
                CREATE TABLE feature_store_pk2 AS
                SELECT * EXCLUDE (instance_hash),
                       COALESCE(instance_hash, '') AS instance_hash
                FROM feature_store
            """)
            con_analytics.execute(
                "ALTER TABLE feature_store_pk2 ALTER instance_hash SET NOT NULL")
            con_analytics.execute(
                "ALTER TABLE feature_store_pk2 ALTER instance_hash SET DEFAULT ''")
            con_analytics.execute(
                "ALTER TABLE feature_store_pk2 ADD PRIMARY KEY "
                "(symbol, timeframe, bar_time, feature_id, instance_hash)")
            con_analytics.execute("DROP TABLE feature_store")
            con_analytics.execute(
                "ALTER TABLE feature_store_pk2 RENAME TO feature_store")
            print("MIGRATION: feature_store-PK um instance_hash erweitert.")
    except Exception as e:
        print(f"MIGRATION WARNUNG: feature_store-PK-Migration "
              f"fehlgeschlagen: {e}")
    # Bugfix 07.08.2026 (Phase 17 Bugfix-Runde 2): Der Spalten-DEFAULT von
    # created_at wurde durch die PK-Migration (17.01 E-1, test/migrate_pk.py –
    # Table-Rewrite + RENAME) entfernt. Seitdem bleiben NEUE feature_store-Rows
    # ohne explizites created_at NULL und das 'Datum der letzten Ausfuehrung'
    # (MasterTree, MAX(created_at) je feature_id) zeigt '--.--.--'. Der DEFAULT
    # wird hier idempotent wiederhergestellt (No-op bei korrekter DB).
    try:
        con_analytics.execute(
            "ALTER TABLE feature_store ALTER created_at "
            "SET DEFAULT current_timestamp")
    except Exception as e:
        print(f"⚠️ [MIGRATION WARNUNG] created_at-Default des feature_store "
              f"konnte nicht wiederhergestellt werden: {e}")
    # 22.01 (14.08.2026): Peak-Grabber-Serientests. Die Outcome-Spalten
    # (outcome_status/pnl_r_multiple/max_favorable_exc/max_adverse_exc)
    # sind PENDING/NULL-Platzhalter (Frage 4) – die Exit-/Forward-Evaluation
    # folgt als separates Modul in einem spaeteren Kapitel (peak_outcome.py).
    # Schreibzugriff ausschliesslich ueber repositories/grabber_repository.py
    # (DbPool-Muster, Praeambel 4/6). run_id-Konvention: "LIVE-<YYYYmmdd-HHMMSS>"
    # fuer Live-Laeufe, "BT-<YYYYmmdd-HHMMSS>" fuer Serientests.
    con_analytics.execute("""
        CREATE TABLE IF NOT EXISTS grabber_test_results (
            signal_id           VARCHAR PRIMARY KEY,
            run_id              VARCHAR NOT NULL,
            timestamp           TIMESTAMPTZ NOT NULL,   -- Wanduhr-Epochs (Praemabel 8)
            symbol              VARCHAR NOT NULL,
            timeframe           VARCHAR NOT NULL,
            direction           VARCHAR NOT NULL,
            entry_price         DOUBLE NOT NULL,
            sl_price            DOUBLE NOT NULL,
            peak_price          DOUBLE NOT NULL,
            peak_bar_index      BIGINT NOT NULL,
            is_update           BOOLEAN NOT NULL,
            reversal_pct        FLOAT NOT NULL,
            is_yellow_window    BOOLEAN NOT NULL,
            gate_source         VARCHAR NOT NULL,
            outcome_status      VARCHAR DEFAULT 'PENDING',
            pnl_r_multiple      FLOAT,
            max_favorable_exc   FLOAT,
            max_adverse_exc     FLOAT
        );
    """)
    con_analytics.execute(
        "CREATE INDEX IF NOT EXISTS idx_grabber_run "
        "ON grabber_test_results (run_id);")

    con_app = DbPool.get(DB_APP_DATA)
    con_app.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            key VARCHAR PRIMARY KEY,
            value VARCHAR,
            updated_at TIMESTAMP DEFAULT current_timestamp
        );
    """)

    # Phase 15 (15.01): Symbol- & Favoriten-Verwaltung. broker_symbols haelt
    # die Broker-Symbole (aus mt5.symbols_get()) inkl. Favoriten-Flag und
    # dient als Fallback, wenn MT5 nicht verfuegbar ist. Standard-Defaults
    # (SILVER, GOLD, BTCUSD) werden als Favoriten vorbelegt, damit die
    # Favoriten-Dropdowns (ServiceWindow/AnalyticsWindow) nie leer starten.
    con_app.execute("""
        CREATE TABLE IF NOT EXISTS broker_symbols (
            symbol      VARCHAR PRIMARY KEY,
            path        VARCHAR,
            is_favorite BOOLEAN DEFAULT FALSE,
            updated_at  TIMESTAMP DEFAULT current_timestamp
        );
    """)
    con_app.execute("""
        INSERT INTO broker_symbols (symbol, path, is_favorite)
        VALUES ('SILVER', '', TRUE), ('GOLD', '', TRUE), ('BTCUSD', '', TRUE)
        ON CONFLICT (symbol) DO NOTHING;
    """)

    # Phase 15 (15.03): Analytics-Profile. analytics_profiles haelt benannte
    # Parametrisierungen der Analytics-UI (Option B – Explicit Save: Slider-/
    # Parametertrends setzen Dirty-Flag, Speichern erst auf [Save]). Das
    # Profil-Payload-JSON (Spalte payload) enthaelt als Pflichtfeld
    # `schema_version` (15.03-Spezifikation: 1). Additiv/idempotent –
    # bestehende Profile bleiben unangetastet.
    con_app.execute("""
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
    print(f"   ✅ Ordner '{DATA_DIR}/' und alle 3 DBs sind einsatzbereit.")

```

--------------------------------------------------

### DATEI: repositories/__init__.py
```py
# repositories/__init__.py
"""
repositories-Paket (18.01.02, E3): Exklusive Lese-Repositories.

  * market_data_repository.py – MarketDataRepository, get_symbol_precision

Importiert nur die db-Basisschicht (E4); kein Import von main.py/db_service.py.
"""

```

--------------------------------------------------

### DATEI: repositories/grabber_repository.py
```py
# repositories/grabber_repository.py
from typing import List

import pandas as pd

from analytics.engine.peak_models import GrabberResultRecord
from db_service import DB_ANALYTICS, DbPool


class GrabberRepository:
    """Kapselt den DB-Zugriff auf grabber_test_results (MVVM, Präambel 4/6)."""

    def __init__(self, db_path: str = DB_ANALYTICS) -> None:
        self.db_path = db_path

    _COLS = [
        "signal_id", "run_id", "timestamp", "symbol", "timeframe",
        "direction", "entry_price", "sl_price", "peak_price",
        "peak_bar_index", "is_update", "reversal_pct",
        "is_yellow_window", "gate_source", "outcome_status",
        "pnl_r_multiple", "max_favorable_exc", "max_adverse_exc",
    ]

    def save_records(self, records: List[GrabberResultRecord]) -> int:
        """Batch-Upsert (18 Spalten, B1). ON CONFLICT aktualisiert nur
        die Outcome-Felder (nachlaufende Serientest-Bewertung)."""
        if not records:
            return 0
        rows = [
            (
                r.signal_id, r.run_id, r.timestamp, r.symbol, r.timeframe,
                r.direction.value, r.entry_price, r.sl_price, r.peak_price,
                r.peak_bar_index, r.is_update, r.reversal_pct,
                r.is_yellow_window, r.gate_source, r.outcome_status,
                r.pnl_r_multiple, r.max_favorable_exc, r.max_adverse_exc,
            )
            for r in records
        ]
        con = DbPool.get(self.db_path)
        df = pd.DataFrame(rows, columns=self._COLS)
        con.register("df_grabber", df)
        cols = ", ".join(self._COLS)
        try:
            con.execute(f"""
                INSERT INTO grabber_test_results ({cols})
                SELECT {cols} FROM df_grabber
                ON CONFLICT (signal_id) DO UPDATE SET
                    outcome_status = EXCLUDED.outcome_status,
                    pnl_r_multiple = EXCLUDED.pnl_r_multiple,
                    max_favorable_exc = EXCLUDED.max_favorable_exc,
                    max_adverse_exc = EXCLUDED.max_adverse_exc
            """)
        finally:
            con.unregister("df_grabber")
        return len(rows)

    def fetch_records(self, run_id: str) -> List[dict]:
        con = DbPool.get(self.db_path)
        rows = con.execute(
            "SELECT * FROM grabber_test_results WHERE run_id = ? "
            "ORDER BY timestamp", [run_id]).fetchall()
        cols = [d[0] for d in con.description]
        return [dict(zip(cols, r)) for r in rows]

    def delete_run(self, run_id: str) -> int:
        con = DbPool.get(self.db_path)
        res = con.execute(
            "DELETE FROM grabber_test_results WHERE run_id = ?",
            [run_id])
        return len(res.fetchall() or [])

```

--------------------------------------------------

### DATEI: repositories/market_data_repository.py
```py
# repositories/market_data_repository.py
"""
repositories/market_data_repository.py - Exklusiver Lesezugriff auf Marktdaten.

Ausgelagert aus db_service.py im Rahmen von 18.01.02 (E3): `MarketDataRepository`
(kapselt den exklusiven Lesezugriff auf die Marktdatenbank) und
`get_symbol_precision` (identische Precision-Query, DRY – Grundlage der
Custom-Level-Eingabefelder). Importiert nur db/db_pool (E4).
"""

import os
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from db.db_pool import DB_MARKET_DATA, DbPool, db_connect


# ==============================================================================
# HELPER: Symbol-Preision (fixer Wert je Symbol, identisch zur Preisskala)
# ==============================================================================
def get_symbol_precision(symbol: str, timeframe: str,
                         db_path: str = DB_MARKET_DATA) -> int:
    """Liefert die Preisskala-Praezision (Nachkommastellen) eines Symbols.

    Identische Query wie MarketDataRepository.fetch_historical_candles()
    (die Preisskala im Chart nutzt exakt diesen Wert) – jedoch OHNE die
    Candles zu laden. Wird fuer die Custom-Level-Eingabefelder (prox_level1..6)
    verwendet, damit die Eingabe dieselbe Dezimalanzahl wie die Preisskala hat.

    Fallback: 2 bei fehlender DB / leerer Tabelle / Fehler.
    """
    default = 2
    if not os.path.exists(db_path):
        return default
    try:
        con = DbPool.get(db_path)
        p_row = con.execute("""
            SELECT COALESCE(MAX(
                CASE
                    WHEN POSITION('.' IN CAST(ROUND(close, 5) AS VARCHAR)) > 0
                    THEN LENGTH(RTRIM(CAST(ROUND(close, 5) AS VARCHAR), '0'))
                         - POSITION('.' IN CAST(ROUND(close, 5) AS VARCHAR))
                    ELSE 0
                END
            ), 2) AS precision
            FROM (
                SELECT close
                FROM ohlcv_bars
                WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
                  AND close IS NOT NULL
                LIMIT 1000
            );
        """, [symbol, timeframe]).fetchone()
        if p_row and p_row[0] is not None:
            return int(p_row[0])
    except Exception:
        pass
    return default


# ==============================================================================
# REPOSITORY MIT ROBUSTER STATISTISCHER PRECISION-ERMITTLUNG
# ==============================================================================
class MarketDataRepository:
    """Kapselt den exklusiven Lesezugriff auf die Marktdatenbank."""

    def __init__(self, db_path: str = DB_MARKET_DATA) -> None:
        self.db_path = db_path

    def fetch_historical_candles(self, symbol: str, timeframe: str, limit: int = 3000,
                                 before_epoch: Optional[int] = None) -> Tuple[List[Dict[str, Any]], int]:
        """Liest OHLCV-Kerzen aus der Marktdatenbank (aufsteigend sortiert).

        Phase 16.07 (Two-Tier Caching, D4): Additiver Parameter `before_epoch`.
        Ist er gesetzt, werden ausschliesslich KERZEN GELADEN, DIE ÄLTER ALS
        diese Wanduhr-Epoch sind (WHERE "time" < to_timestamp(?)) – das
        Chunk-Nachladen des `ChartDataBuffer` (Tier 2 -> DuckDB) nutzt genau
        diesen Pfad, um den naechsten Block alter Geschichte vorzuladen.
        Ohne `before_epoch` ist das Verhalten unveraendert (letzte `limit`
        Kerzen, Abwaertskompatibilitaet).
        """
        candles: List[Dict[str, Any]] = []
        precision: int = 2

        if not os.path.exists(self.db_path):
            return candles, precision

        for attempt in range(3):
            try:
                con = db_connect(self.db_path)

                precision_query = """
                    SELECT COALESCE(MAX(
                        CASE
                            WHEN POSITION('.' IN CAST(ROUND(close, 5) AS VARCHAR)) > 0
                            THEN LENGTH(RTRIM(CAST(ROUND(close, 5) AS VARCHAR), '0')) - POSITION('.' IN CAST(ROUND(close, 5) AS VARCHAR))
                            ELSE 0
                        END
                    ), 2) AS precision
                    FROM (
                        SELECT close
                        FROM ohlcv_bars
                        WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
                          AND close IS NOT NULL
                        LIMIT 1000
                    );
                """
                p_row = con.execute(precision_query, [symbol, timeframe]).fetchone()
                if p_row and p_row[0] is not None:
                    precision = int(p_row[0])

                # Phase 16.07: before_epoch filtert additiv auf ältere Kerzen
                # (Wanduhr-Epoch; "time" ist TIMESTAMPTZ, daher to_timestamp-
                # Vergleich). Die WHERE-Bedingung wird nur bei gesetztem
                # before_epoch ergänzt (Abwaertskompatibilität).
                older_filter = ""
                params: List[Any] = [symbol, timeframe]
                if before_epoch is not None:
                    older_filter = ' AND "time" < to_timestamp(?)'
                    params.append(int(before_epoch))
                params.append(limit)

                query = """
                    SELECT EXTRACT('epoch' FROM "time")::BIGINT AS time_epoch,
                           open, high, low, close, tick_volume
                    FROM (
                        SELECT "time", open, high, low, close, tick_volume
                        FROM ohlcv_bars
                        WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
                          AND "time" IS NOT NULL
                          AND open IS NOT NULL
                          AND high IS NOT NULL
                          AND low IS NOT NULL
                          AND close IS NOT NULL
                        """ + older_filter + """
                        ORDER BY "time" DESC
                        LIMIT ?
                    )
                    ORDER BY "time" ASC;
                """
                rows = con.execute(query, params).fetchall()
                con.close()

                for r in rows:
                    t_epoch = int(r[0])  # Bereits epoch-Integer aus DuckDB
                    # P16.05 VWMA-Fix (P-D4): tick_volume wird mitgeliefert.
                    # Entscheidung F3: NaN/None -> 0, Candle bleibt gueltig
                    # (kein WHERE-Filter auf tick_volume, damit Candles mit
                    # NULL-Volumen nicht wegfallen).
                    vol_raw = r[5]
                    candles.append({
                        "time": t_epoch,
                        "open": float(r[1]),
                        "high": float(r[2]),
                        "low": float(r[3]),
                        "close": float(r[4]),
                        "tick_volume": float(vol_raw) if vol_raw is not None else 0.0
                    })
                break

            except Exception as e:
                if attempt == 2:
                    print(f"❌ [Repository Error] Fehler beim Laden von {symbol} {timeframe}: {e}")
                else:
                    time.sleep(0.1)

        return candles, precision

    def get_all_stored_symbol_tf_pairs(self) -> Set[Tuple[str, str]]:
        """Liefert alle (symbol, timeframe)-Paare, für die bereits Daten in ohlcv_bars existieren.

        Phase 21.03.22 (Full Market-Data Sync Button): Grundlage fuer den
        manuellen Sync aller lokal gespeicherten Paare im ServiceWindow.
        UPPER-normalisiert (DISTINCT); Muster: DbPool.get (Thread-local,
        kein manuelles close(), konsistent mit get_symbol_precision).
        """
        try:
            con = DbPool.get(self.db_path)
            rows = con.execute("""
                SELECT DISTINCT UPPER(symbol), UPPER(timeframe)
                FROM ohlcv_bars
                WHERE symbol IS NOT NULL AND timeframe IS NOT NULL
            """).fetchall()
            return {(str(r[0]), str(r[1])) for r in rows if r[0] and r[1]}
        except Exception as e:
            print(f"WARN [MarketDataRepository] Pair-Abfrage fehlgeschlagen: {e}")
            return set()

```

--------------------------------------------------

