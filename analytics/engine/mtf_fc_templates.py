# analytics/engine/mtf_fc_templates.py
"""
MTF-FC v4 (Kapitel 21.03.07) – View-Template-Persistenz (Pure Logik).

Speichern/Laden kompletter Filter-Konfigurationen des MtfFilterBarWidget
über den bestehenden `SchemaMigrator` (`analytics/engine/schema_migrator.py`):
Gespeicherte Preset-JSONs werden IN-MEMORY validiert und abwärtskompatibel
um neue TFs/Session-Keys erweitert (Payload-Key `mtf_fc_schema_version =
"1.0.0"`). Rollback-Schutz: Eine fehlerhafte Migration wirft TemplateError,
der Aufrufer behält das Original.

Reine Logik (kein UI-Import, Grundsatz 4/11). Kein Persistenz-Medium wird
hier festgeschrieben – die UI/der Aufrufer entscheidet über die Ablage
(Default: in-memory Dict-Registry für die Sitzung).
"""

from typing import Any, Dict, Optional

from analytics.engine.schema_migrator import MigrationError, _needs_migration
from analytics.engine.mtf_fc_confluence import WEIGHTS

#: Aktuelle Template-Schema-Version (Payload-Key).
MTF_FC_SCHEMA_VERSION = "1.0.0"

#: Bekannte Template-Keys (Whitelist für die Migration).
_TEMPLATE_KNOWN_KEYS = (
    "mtf_fc_schema_version", "name", "data_tf", "chart_tf",
    "range_preset", "custom_range", "sort_mode", "session_filters",
    "confluence_weighting", "volatility_adaption", "view_templates_meta",
)

#: Defaults für fehlende/neue Keys (abwärtskompatible Erweiterung).
_TEMPLATE_DEFAULTS: Dict[str, Any] = {
    "data_tf": "multi",
    "chart_tf": "auto",
    "range_preset": "7d",
    "custom_range": {"from_ts": None, "to_ts": None},
    "sort_mode": "date",
    "session_filters": [],
    "confluence_weighting": dict(WEIGHTS),
    "volatility_adaption": False,
    "view_templates_meta": {"created": None, "updated": None},
}


class TemplateError(Exception):
    """Wird bei einer fehlgeschlagenen Template-Migration geworfen.

    Der Aufrufer behält dann das ORIGINAL-Template (Rollback-Schutz).
    """


def create_template(name: str, **filters: Any) -> Dict[str, Any]:
    """Erzeugt ein neues View-Template (Schema-Version + Defaults + Filters)."""
    template: Dict[str, Any] = {"mtf_fc_schema_version": MTF_FC_SCHEMA_VERSION}
    template.update(_TEMPLATE_DEFAULTS)
    template["name"] = name
    for key, value in filters.items():
        if key in _TEMPLATE_KNOWN_KEYS:
            template[key] = value
    return template


def migrate_template(raw: Any) -> Dict[str, Any]:
    """Validieret/migriert ein Template-JSON in-memory (SchemaMigrator-Semantik).

    Ablauf (analog `SchemaMigrator.migrate_instance_config`):
      1. Fehlende bekannte Keys werden mit ihren Defaults ergänzt.
      2. Unbekannte Keys (nicht in der Whitelist) werden entfernt.
      3. `mtf_fc_schema_version` wird auf die aktuelle Version angehoben.

    Raises:
        TemplateError: Bei nicht-Dict-Eingabe oder Migrationsfehler –
        der Aufrufer führt den Rollback auf das Original aus.
    """
    try:
        if not isinstance(raw, dict):
            raise TemplateError(
                f"Template ist kein JSON-Objekt: {type(raw).__name__}")
        result: Dict[str, Any] = dict(raw)
        current = str(result.get("mtf_fc_schema_version") or "0.0.0")

        if not _needs_migration(current, MTF_FC_SCHEMA_VERSION):
            # Nicht-migrationsbedürftig: trotzdem sicherstellen, dass alle
            # Pflicht-Keys existieren (defensive Ergänzung, non-destruktiv).
            for key, default in _TEMPLATE_DEFAULTS.items():
                result.setdefault(key, default)
            return result

        # 1) Fehlende Schema-Keys mit Defaults ergänzen.
        for key, default in _TEMPLATE_DEFAULTS.items():
            if key not in result:
                result[key] = default

        # 2) Unbekannte Keys entfernen (Whitelist = Single Source of Truth).
        for key in list(result.keys()):
            if key not in _TEMPLATE_KNOWN_KEYS:
                result.pop(key, None)

        # 3) Schema-Version anheben.
        result["mtf_fc_schema_version"] = MTF_FC_SCHEMA_VERSION
        return result
    except MigrationError:
        raise
    except TemplateError:
        raise
    except Exception as e:
        raise TemplateError(f"Template-Migration fehlgeschlagen: {e}") from e


class MtfFcTemplateStore:
    """In-memory Template-Registry (Sitzungs-Scope).

    Die Persistenz-Entscheidung (JSON-Datei, DB, Settings) trifft der
    Aufrufer – der Store hält lediglich eine flache Dict-Registry
    (name -> Template) und migriert beim Laden über `migrate_template`.
    """

    def __init__(self) -> None:
        self._templates: Dict[str, Dict[str, Any]] = {}

    def save(self, template: Dict[str, Any]) -> None:
        """Speichert ein (bereits migriertes) Template unter seinem Namen."""
        name = str(template.get("name") or "Unbenannt")
        self._templates[name] = dict(template)

    def load(self, name: str) -> Optional[Dict[str, Any]]:
        """Lädt und migriert ein Template (Rollback-Schutz bei Fehler)."""
        raw = self._templates.get(name)
        if raw is None:
            return None
        try:
            return migrate_template(raw)
        except TemplateError as e:
            print(f"WARN [MtfFcTemplateStore] Template '{name}' verworfen: {e}")
            return None

    def names(self) -> list:
        """Alle gespeicherten Template-Namen (sortiert)."""
        return sorted(self._templates.keys())

    def delete(self, name: str) -> bool:
        """Entfernt ein Template. Rueckgabe: True, wenn es existierte."""
        return self._templates.pop(name, None) is not None
