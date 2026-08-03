# analytics/engine/schema_migrator.py
"""
Phase 14 P14-04 – Schema-Migrator (Semantic Versioning & Rollback-Schutz).

Sicherstellung der dauerhaften Lauffähigkeit alter Service-Sets bei
Weiterentwicklung von Plugins. Jede ServiceInstanceConfig trägt ein
`version`-Feld (Semantic Versioning major.minor.patch, z. B. "1.0.0").
Wird ein Set geladen, dessen Instanz-Version hinter der aktuellen
Plugin-Version zurückliegt (Major-/Minor-Abweichung), migriert der
SchemaMigrator die Instanz-Konfiguration IM SPEICHER (transparent, ohne
die Datenbank zu verändern):

  1. fehlende Parameter-Keys werden mit ihren Schema-Defaults ergänzt,
  2. veraltete, nicht mehr im Parameter-Schema enthaltene Keys werden entfernt,
  3. die Instanz-Version wird auf die aktuelle plugin.version angehoben.

Reine Patch-Abweichungen (z. B. 1.0.0 -> 1.0.1) lösen KEINE Migration aus
(Architektur-Invariante 5). Ein fehlendes `version`-Feld wird als
Legacy-Stand "0.0.0" interpretiert und daher immer migriert.

ROLLBACK-SCHUTZ: Wirft der Migrator während der Aufbereitung eine Exception,
wird die Migration abgebrochen und ein MigrationError geworfen. Der Aufrufer
(ServiceSetRepository.get_set()) gibt dann das UNMIGRIERTE Original-Set
zurück (Rollback auf Datenbank-Ebene, Invariante 8).
"""

from typing import Any, Dict

from analytics.features.plugins.base_plugin import PluginFeature


class MigrationError(Exception):
    """Wird vom SchemaMigrator geworfen, wenn die Migration fehlschlägt.

    Löst beim Aufrufer (ServiceSetRepository.get_set()) den Rollback aus:
    das originale, unveränderte Set wird zurückgegeben und geloggt.
    """


def _parse_version(version: Any) -> tuple:
    """Parsed eine SemVer-Zeichenkette in (major, minor, patch) – numerisch.

    Robust: None/leer/ungültig → (0, 0, 0). Optionales 'v'-Präfix sowie
    Pre-Release-/Build-Segmente (z. B. '1.2.3-beta.1+build5') werden
    ignoriert. Nur die ersten drei numerischen Segmente zählen.
    """
    if version is None:
        return (0, 0, 0)
    s = str(version).strip()
    if not s:
        return (0, 0, 0)
    if s[:1].lower() == "v":
        s = s[1:]
    core = s.split("+")[0].split("-")[0]
    nums: list = []
    for part in core.split("."):
        try:
            nums.append(int(part))
        except (TypeError, ValueError):
            nums.append(0)
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def _needs_migration(v_old: str, v_new: str) -> bool:
    """True, wenn eine Migration nötig ist (Major-/Minor-Abweichung).

    Reine Patch-Abweichungen (z. B. 1.0.0 -> 1.0.1) lösen KEINE Migration aus.
    Migriert wird ausschließlich, wenn die gespeicherte Version HINTER der
    aktuellen Plugin-Version liegt (Legacy "0.0.0" → immer). Ein Downgrade
    (gespeicherte Version über der Plugin-Version) wird NICHT migriert –
    kein destruktives Rücksetzen lauffähiger Sets.
    """
    old = _parse_version(v_old)
    new = _parse_version(v_new)
    if old[0] < new[0]:
        return True
    if old[0] > new[0]:
        return False
    return old[1] < new[1]


class SchemaMigrator:
    """Migriert Service-Instanz-Konfigurationen gegen das Plugin-Schema."""

    def migrate_instance_config(
        self,
        config: Dict[str, Any],
        plugin: PluginFeature,
    ) -> Dict[str, Any]:
        """Bereitet eine ServiceInstanceConfig für das aktuelle Plugin-Schema auf.

        Args:
            config: ServiceInstanceConfig (plugin_id, lookback, params, ...).
            plugin: Aktuelle PluginFeature-Instanz (plugin.version + Schema).

        Returns:
            Migrierte (tiefe) Kopie der Konfiguration – das Original bleibt
            unverändert (der Aufrufer entscheidet über die Übernahme).

        Raises:
            MigrationError: Bei jedem Fehler während der Aufbereitung –
            der Aufrufer führt dann den Rollback auf das Original aus.
        """
        if plugin is None:
            raise MigrationError("Plugin ist None – Migration nicht möglich.")
        try:
            result: Dict[str, Any] = dict(config or {})
            current_ver = result.get("version") or "0.0.0"
            new_ver = getattr(plugin, "version", "0.0.0") or "0.0.0"

            # Kein Handlungsbedarf: nur Patch-Differenz oder gleiche/höhere
            # Version → Instanz unverändert zurückgeben.
            if not _needs_migration(current_ver, new_ver):
                return result

            schema = plugin.full_parameter_schema()
            params: Dict[str, Any] = dict(result.get("params") or {})

            # 1) Fehlende Schema-Keys mit Default-Werten ergänzen.
            for key, spec in schema.items():
                if key in params:
                    continue
                if "default" in spec:
                    params[key] = spec["default"]

            # 2) Veraltete Keys entfernen, die nicht mehr im Parameter-Schema
            #    enthalten sind (Parameter-Schema = Single Source of Truth).
            known = set(schema.keys())
            for key in list(params.keys()):
                if key not in known:
                    params.pop(key, None)

            result["params"] = params

            # lookback ist Service-Instanz-Einstellung (top-level) und gehört
            # zum Basis-Schema – fehlt er, wird der Schema-Default ergänzt.
            if "lookback" not in result and "lookback" in schema:
                result["lookback"] = int(schema["lookback"].get("default", 1000))

            # 3) Instanz-Version auf die aktuelle Plugin-Version anheben.
            result["version"] = new_ver
            return result
        except MigrationError:
            raise
        except Exception as e:
            raise MigrationError(
                f"Schema-Migration fehlgeschlagen (Instanz "
                f"'{config.get('plugin_id', '?')}'): {e}"
            ) from e
