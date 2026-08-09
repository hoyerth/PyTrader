# analytics/engine/service_models.py
"""
Phase 13 Schritt 2 – Service-Set-Datenmodell (TypedDicts).

Diese Strukturen sind JSON-konform und werden direkt (als JSON) vom
ServiceSetRepository in app_data.duckdb persistiert. Bewusst KEINE
Dataclasses – der ServiceSetEvaluator (Schritt 3) und die UI (Schritte 4/5)
arbeiten auf denselben Dict-Strukturen wie die JSON-Speicherung.

Multi-Use-Prinzip: Ein Plugin (z.B. srv_grid_lines) kann MEHRFACH in einem Set
vorkommen. Jede Nutzung erhält eine eindeutige instance_id (z.B. grid_1,
grid_2). execution_order bestimmt die Ausführungs-Reihenfolge, depends_on
deklariert explizit, welche instance_ids der Service aus dem shared_state
liest (Service→Service-Abhängigkeit).
"""

from typing import Any, Dict, List, Optional, TypedDict

import hashlib
import json


# ------------------------------------------------------------------
# 20.04 (Q4): Kanonische Hash-Serialisierung
# ------------------------------------------------------------------
def _sanitize_for_hash(value: Any) -> Any:
    """Rekursive Umwandlung in JSON-feste native Python-Typen (20.04, Q4).

    numpy-Skalare (np.int64/np.float64), None, verschachtelte Dicts/Listen
    und datetime-Werte werden deterministisch in native Typen überführt –
    Grundlage der stabilen `instance_hash`-Berechnung (sonst
    `TypeError: Object of type int64 is not JSON serializable` bzw.
    instabile Hashes bei wechselnder Speicherreihenfolge).
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    # numpy-Skalare (np.int64, np.float64, np.bool_) -> native Python-Typen.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _sanitize_for_hash(item())
        except Exception:
            pass
    if isinstance(value, dict):
        return {str(k): _sanitize_for_hash(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_hash(v) for v in value]
    # datetime/date -> ISO-String (deterministisch).
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def generate_instance_hash(
    plugin_id: str, params: Optional[Dict[str, Any]] = None
) -> str:
    """8-stelliger deterministischer SHA256-Short-Hash einer Instanz (20.04).

    `SHA256("<plugin_id>|" + json.dumps(sanitized_params, sort_keys=True))[:8]`

    * **Q3:** `lookback` fließt BEWUSST NICHT ein – das Kerzen-Ergebnis hängt
      nur von Algorithmus-Logik + `params` ab; `lookback` ist ein Laufzeit-
      Fenster (Performance) und kein Inhalts-Identitätsmerkmal.
    * **Q4:** `_sanitize_for_hash` überführt numpy-Werte/None/verschachtelte
      Dicts vorher in native Python-Typen; `sort_keys=True` macht die
      Serialisierung kanonisch (unabhängig von der Speicherreihenfolge).
    """
    canonical = json.dumps(
        _sanitize_for_hash(params or {}),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(
        f"{plugin_id}|{canonical}".encode("utf-8")
    ).hexdigest()
    return digest[:8]


class ServiceInstanceConfig(TypedDict, total=False):
    """Konfiguration einer einzelnen Service-Instanz innerhalb eines Sets.

    Attribute:
        plugin_id:  Dauerhaft stabile Plugin-ID (z.B. 'srv_grid_lines', 'srv_proximity').
        lookback:   Scan-Fenster über die Historie (Anzahl Bars, df.tail(lookback)).
        params:     Plugin-Parameter (werden gegen das parameter_schema validiert).
        depends_on: Optional. instance_ids, deren shared_state-Einträge dieser
                    Service liest (muss früher in execution_order stehen).
        description: Optional (Phase 14 P14-01). Individuelle Anmerkung für
                    diese Instanz (wird im Tooltip/Info-Dialog angezeigt).
        version:    Optional (Phase 14 P14-01). Plugin-Version dieser Instanz,
                    Default "1.0.0" (Semantic Versioning major.minor.patch).
        instance_hash: Optional (20.04). 8-stelliger Hash der Parameter-
                    Variante (generate_instance_hash); stabile Identifikation
                    im feature_store (Spalte instance_hash) für
                    Multi-Varianten-Statistiken.
        doc_log:    Optional (20.04). Freitextfeld (Negativ-Wissen) – z. B.
                    "85% false signals in chop markets".
        is_archived: Optional (20.04, Q6). True = Instanz ist archiviert
                    (MasterTree: non-checkable, unter 📁 Archiv).
    """
    plugin_id: str
    lookback: int
    params: Dict[str, Any]
    depends_on: Optional[List[str]]
    description: Optional[str]
    version: Optional[str]
    instance_hash: Optional[str]
    doc_log: Optional[str]
    is_archived: bool


class ServiceSetDefinition(TypedDict, total=False):
    """Vollständige Definition eines Service-Sets (JSON-konform).

    Beispiel (Roadmap Phase 13 §2):
    {
      "set_id": "uuid-oder-name",
      "display_name": "Mein Scalper",
      "execution_order": ["grid_1", "prox_1", "ema_1"],
      "services": {
        "grid_1": {"plugin_id": "srv_grid_lines", "lookback": 1000,
                   "params": {"step_size": 0.5, "steps_around": 4, "custom_levels": []}},
        "prox_1": {"plugin_id": "srv_proximity", "lookback": 10000,
                   "depends_on": ["grid_1"],
                   "params": {"visit_pct": 0.05, "time_window_mins": 5}}
      }
    }
    """
    set_id: str                      # Eindeutige ID (uuid oder Name)
    display_name: str                # Anzeigename (leer → Auto-Name aus instance_ids)
    description: Optional[str]       # Phase 14 P14-01: Ausführliche Set-/Strategie-Beschreibung
    category: Optional[str]          # Phase 18.01.03 (E2): Kategorie-Pfad für den
                                     # MasterTree-Sets-Ordner (z.B. 'Swing Points/Geometrie',
                                     # Slash-separiert OHNE '📁 '-Präfixe; leer/"General" =
                                     # Root-Ebene der Sets-Gruppe). Persistiert additiv
                                     # in save_set().
    version: Optional[str]           # Kap 5: Set-Level Semantic Version (major.minor.patch)
    schema_version: Optional[str]    # Kap 5: Schema-Format-Version der Definition (z.B. "1.0")
    created_at: Optional[str]        # Kap 5: Erstellungs-Zeitstempel (ISO-8601 UTC)
    is_archived: bool                # 20.04 (Q6): True = gesamtes Set archiviert
                                     # (MasterTree: non-checkable, unter 📁 Archiv)
    execution_order: List[str]       # Ausführungs-Reihenfolge der instance_ids
    services: Dict[str, ServiceInstanceConfig]  # instance_id → Konfiguration
