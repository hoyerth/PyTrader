# db/db_utils.py
"""
db/db_utils.py - Gemeinsame DB-Hilfsfunktionen.

Ausgelagert aus db_service.py im Rahmen von 18.01.02 (E3): `_parse_json_field`
(DuckDB liefert JSON teils als str, teils als dict) und `_ensure_epoch`
(DEPRECATED, backward-compat). Basis-Schicht (E4) – kein Projekt-Import.
"""

import calendar
import json
from datetime import datetime
from typing import Any


def _ensure_epoch(val: Any) -> int:
    """DEPRECATED: Nutze stattdessen EXTRACT('epoch' FROM time)::BIGINT in SQL.
    Diese Funktion zerstört die Zeitzone bei TIMESTAMPTZ (timetuple() verliert offset).
    Nur noch für backward-compat in Test-Dateien."""
    if isinstance(val, datetime):
        return calendar.timegm(val.timetuple())
    return int(val)


def _parse_json_field(val: Any) -> Any:
    """Wandelt JSON aus DuckDB in Python-Objekt um (str->dict, dict bleibt)."""
    if isinstance(val, str):
        return json.loads(val) if val else None
    return val
