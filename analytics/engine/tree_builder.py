# analytics/engine/tree_builder.py
"""
analytics/engine/tree_builder.py - Rekursiver Baumaufbau der Service-Hierarchie.

Ausgelagert aus service_selector_model.py im Rahmen von 18.01.02 (E6): alle
Baum-Konstruktions- und Kategorie-Aufloesungsfunktionen als REINE Modul-
Funktionen (kein Klassenzustand, keine Qt-Signale, kein Import von
ServiceSelectorModel – keine Zirkularitaet).

Eingangsdaten (Sets, Plugins, Kategorie-Overrides, Empty-Folder-Pfade,
Badges, Last-Execution-Daten) werden als Parameter uebergeben. Der
ServiceSelectorModel bleibt die oeffentliche API und delegiert hierher
(dünne Wrapper).

Gruppen-Kennungen (Spiegel der ServiceSelectorModel-Konstanten):
  * GROUP_SETS = "sets"      – Root-Gruppe '📁 Sets'
  * GROUP_PLUGINS = "plugins" – Root-Gruppe '📦 Services'
  * GROUP_CATEGORY = "category_node" – 📁-Ordner-Knoten
"""

from typing import Any, Dict, List, Optional

#: Root-Gruppe der gespeicherten Service-Sets.
GROUP_SETS = "sets"
#: Root-Gruppe aller registrierten Plugins/Services.
GROUP_PLUGINS = "plugins"
#: Kategorie-Ordner-Knoten (Dynamic Category Trees).
GROUP_CATEGORY = "category_node"
# 20.04 (Q6): Label des dynamischen Archiv-Ordners. Enthaelt archivierte
# Knoten (is_archived=True / Presets mit is_active_batch=False) – alle
# darin liegenden Knoten sind non-checkable (Archive Safety).
ARCHIVE_LABEL = "📁 Archiv"


# ------------------------------------------------------------------
# Kategorie-Bausteine (K1/K2/K8/K9)
# ------------------------------------------------------------------
def _cat_key(label: str) -> str:
    """Case-insensitiver Sortier-/Vergleichsschluessel eines Ordners.

    Entfernt das '📁 '-Praefix des Ordnerlabels (K2-Format), damit
    Sortierung (K8) und Pfad-Lookup stabil auf dem reinen Namen laufen.
    """
    s = str(label or "").strip()
    if s.startswith("📁"):
        s = s[len("📁"):].lstrip()
    return s.lower()


def _category_parts(plugin_id: str, plugin: Optional[Any],
                    overrides: Dict[str, str]) -> List[str]:
    """Kategorienpfad eines Plugins (K1, 16.08 / 18.01.03 E1).

    Ein gesetzter Kategorie-Override (global_settings, Key
    'plugin_category_<plugin_id>', Quelle des Drag & Drop) hat VORRANG vor
    `metadata['category']` – auch ein leerer String "" hebt die metadata-
    Kategorie auf (Root-Ebene). Ohne Override gilt das metadata-Feld wie
    bisher. Leer ODER der Ist-Default `"General"` (base_plugin.py) gelten
    als "keine Kategorie" -> das Plugin bleibt auf der obersten Ebene der
    Hauptgruppe.
    """
    category = ""
    if plugin_id:
        override = overrides.get(str(plugin_id).lower())
        if override is not None:
            category = str(override or "").strip()
    if not category:
        try:
            meta = getattr(plugin, "metadata", None) or {}
            category = str(meta.get("category") or "").strip()
        except Exception:
            category = ""
    if not category or category.lower() == "general":
        return []
    return [p.strip() for p in category.split("/") if p.strip()]


def _insert_into_category_tree(nodes: List[Dict[str, Any]],
                               parts: List[str],
                               leaf: Dict[str, Any]) -> None:
    """Fuegt ein Plugin-Blatt rekursiv in die Ordnerstruktur ein (K2).

    Erzeugt fehlende Ordner entlang des Pfads. Ordner entstehen NUR
    durch eine tatsaechliche Blatt-Einfuegung -> keine leeren Ordner
    (K9). Ordner-Label folgt dem K2-Format '📁 <Name>'.
    """
    if not parts:
        nodes.append(leaf)
        return
    key = _cat_key(parts[0])
    folder = None
    for n in nodes:
        if (n.get("group") == GROUP_CATEGORY
                and _cat_key(n.get("label")) == key):
            folder = n
            break
    if folder is None:
        folder = {"group": GROUP_CATEGORY,
                  "label": f"📁 {parts[0]}", "children": []}
        nodes.append(folder)
    _insert_into_category_tree(folder["children"], parts[1:], leaf)


def _sort_category_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sortiert eine Ordner-Ebene (K8, 16.08 / 18.01.03).

    Deterministisch: Ordner zuerst, dann Blaetter; jeweils alphabetisch
    (case-insensitiv). Innerhalb der Ordner rekursiv dieselbe Regel.
    Blaetter koennen sowohl Plugin-Dicts ({plugin_id, ...}) als auch
    Sets-Dicts ({set_id, display_name, ...}) sein – als Sortiername gilt
    plugin_id, sonst display_name/set_id.
    """
    def sort_key(n: Dict[str, Any]) -> tuple:
        is_folder = n.get("group") == GROUP_CATEGORY
        if is_folder:
            name = _cat_key(n.get("label"))
            # 20.04 (Q6): '📁 Archiv' immer ans ENDE der Gruppe (nach allen
            # normalen Ordnern UND Blaettern) – markiert ueber 'archived'.
            if n.get("archived"):
                return (2, name)
            return (0, name)
        else:
            name = str(n.get("plugin_id")
                       or n.get("display_name")
                       or n.get("set_id") or "").lower()
        return (0 if is_folder else 1, name)

    result = sorted(nodes, key=sort_key)
    for n in result:
        if n.get("group") == GROUP_CATEGORY:
            n["children"] = _sort_category_nodes(n.get("children") or [])
    return result


def _set_category_parts(definition: Dict[str, Any]) -> List[str]:
    """Kategorienpfad eines Service-Sets (18.01.03, E2).

    Lese das optionale Feld `category` der Set-Definition (Slash-Pfad,
    z.B. 'Swing Points/Geometrie'). Leer ODER der Ist-Default "General"
    gelten als "keine Kategorie" -> das Set bleibt auf der obersten
    Ebene der Sets-Gruppe (Spiegel der Plugin-Logik K1).
    """
    category = str((definition or {}).get("category") or "").strip()
    if not category or category.lower() == "general":
        return []
    return [p.strip() for p in category.split("/") if p.strip()]


def _insert_set_into_category_tree(nodes: List[Dict[str, Any]],
                                   parts: List[str],
                                   leaf: Dict[str, Any]) -> None:
    """Fuegt ein Set-Blatt rekursiv in die Ordnerstruktur ein (18.01.03).

    Analoge Mechanik zu `_insert_into_category_tree` (K2), aber fuer
    Sets-Blatt-Dicts ({set_id, display_name, definition, services}).
    Ordner entstehen NUR durch eine tatsaechliche Blatt-Einfuegung ->
    keine leeren Ordner (K9).
    """
    if not parts:
        nodes.append(leaf)
        return
    key = _cat_key(parts[0])
    folder = None
    for n in nodes:
        if (n.get("group") == GROUP_CATEGORY
                and _cat_key(n.get("label")) == key):
            folder = n
            break
    if folder is None:
        folder = {"group": GROUP_CATEGORY,
                  "label": f"📁 {parts[0]}", "children": []}
        nodes.append(folder)
    _insert_set_into_category_tree(folder["children"], parts[1:], leaf)


def _ensure_category_path(nodes: List[Dict[str, Any]],
                          parts: List[str]) -> None:
    """Stellt sicher, dass die Ordnerkette fuer `parts` existiert
    (18.01.03, E3-revidiert).

    Erzeugt fehlende Ordner entlang des Pfads OHNE Blatt-Einfuegung
    (K2-Format '📁 <Name>', children leer). Dient der Einmischung
    persistierter benutzererzeugter (ggf. leerer) Ordner in build_tree():
    Ein bereits vorhandener Ordner (aus echten Blatt-Kategorien) wird
    wiederverwendet – kein Duplikat, keine Kinder-Aenderung.
    """
    if not parts:
        return
    key = _cat_key(parts[0])
    folder = None
    for n in nodes:
        if (n.get("group") == GROUP_CATEGORY
                and _cat_key(n.get("label")) == key):
            folder = n
            break
    if folder is None:
        folder = {"group": GROUP_CATEGORY,
                  "label": f"📁 {parts[0]}", "children": []}
        nodes.append(folder)
    _ensure_category_path(folder["children"], parts[1:])


def _clones_for(presets: Optional[Dict[str, List[Dict[str, Any]]]],
                plugin_id: str) -> List[Dict[str, Any]]:
    """Preset-/Clone-Liste eines Plugins (20.04, Q7) oder [].

    `presets` mappt plugin_id.lower() -> Liste von
    {"preset_name", "params", "instance_hash", "is_archived"}. Plugins
    ohne Eintrag liefern [] (keine Clones -> flaches Blatt).
    """
    if not presets:
        return []
    key = str(plugin_id or "").lower()
    clones = presets.get(key)
    if not clones:
        clones = presets.get(str(plugin_id or ""))
    return list(clones or [])


def _category_nodes(plugin_ids: List[str],
                    plugins: Dict[str, Any],
                    overrides: Dict[str, str],
                    badges: Dict[str, str],
                    last_executions: Dict[str, str],
                    presets: Optional[Dict[str, List[Dict[str, Any]]]] = None
                    ) -> List[Dict[str, Any]]:
    """Baut die (ggf. verschachtelte) Kinderliste einer Plugin-Gruppe.

    Plugins mit Kategorienpfad werden in 📁-Ordner einsortiert; Plugins
    ohne Kategorie (bzw. Default 'General') bleiben auf oberster Ebene
    (K1). Blatt-Dicts unveraendert ({plugin_id, badge, last_execution}).
    Sortierung pro Ebene: Ordner vor Blaettern, alphabetisch (K8).

    20.04 (Q7): Plugins MIT Presets/Clones werden als Parent-Knoten
    gerendert – das Blatt-Dict erhaelt zusaetzlich `clones` (Liste der
    AKTIVEN Clones, is_archived=False). Plugins OHNE Presets bleiben
    flache Blaetter (Blatt-Struktur identisch, Zero-Regression). Die
    ARCHIVIERTEN Clones (is_archived=True) wandern in den dynamischen
    '📁 Archiv'-Ordner (Q6, Archiv-Einheit: einzelne Clone) – das
    Archiv-Blatt traegt das 'archived'-Flag (non-checkable im MasterTree).
    """
    root: List[Dict[str, Any]] = []
    archive_entries: List[Dict[str, Any]] = []
    for pid in plugin_ids:
        plugin = plugins.get(pid)
        parts = _category_parts(pid, plugin, overrides)
        clones = _clones_for(presets, pid)
        leaf = {
            "plugin_id": pid,
            "badge": badges.get(pid, ""),
            "last_execution": last_executions.get(pid, "--.--.--"),
        }
        if not clones:
            # Plugin ohne Presets: flaches Blatt (Bestandsverhalten).
            _insert_into_category_tree(root, parts, leaf)
            continue
        active = [c for c in clones if not c.get("is_archived")]
        archived = [c for c in clones if c.get("is_archived")]
        if active:
            leaf_with_clones = dict(leaf, clones=active)
            _insert_into_category_tree(root, parts, leaf_with_clones)
        if archived:
            archive_entries.append(dict(
                leaf, clones=archived, archived=True))
    if archive_entries:
        archive_folder: Dict[str, Any] = {
            "group": GROUP_CATEGORY,
            "label": ARCHIVE_LABEL,
            "children": sorted(
                archive_entries,
                key=lambda e: str(e.get("plugin_id") or "").lower()),
            "archived": True,
        }
        root.append(archive_folder)
    return _sort_category_nodes(root)


# ------------------------------------------------------------------
# Kategorie-Aufloesung
# ------------------------------------------------------------------
def category_plugin_ids(plugins: Dict[str, Any],
                        overrides: Dict[str, str],
                        category_path: str) -> List[str]:
    """Alle Plugin-IDs unter einem Kategorie-Pfad (rekursiv, 17.01.02).

    Liefert deterministisch (alphabetisch) alle Plugins, deren Kategorie-
    Pfad mit `category_path` beginnt – d.h. auch Plugins in UNTER-Ordnern
    (z.B. Pfad 'Swing Points' liefert auch Plugins aus 'Swing Points/
    Geometrie'). Pfad-Format: slash-separiert OHNE '📁 '-Praefixe
    (z.B. 'Swing Points/Geometrie'), case-insensitiv.

    Grundlage fuer:
      * Kontextmenue '▶️ Alle Services ausführen' auf Ordner-Knoten
        (run_category_requested).
      * Info-Button auf Ordner-Knoten (category_info_requested).
    """
    target = [p.strip().lower() for p in str(category_path or "").split("/")
              if p.strip()]
    if not target:
        return []
    result: List[str] = []
    for pid in sorted(plugins.keys()):
        parts = [p.lower() for p in _category_parts(pid, plugins.get(pid),
                                                    overrides)]
        if len(parts) >= len(target) and parts[:len(target)] == target:
            result.append(pid)
    return result


def _find_set(sets_data: List[Dict[str, Any]], set_id: str) -> Optional[Dict[str, Any]]:
    """Liefert die Set-Definition zur set_id (oder None)."""
    for s in sets_data:
        if s.get("set_id") == set_id:
            return s
    return None


def category_set_ids(sets_data: List[Dict[str, Any]],
                     category_path: str) -> List[str]:
    """Alle set_ids unter einem Kategorie-Pfad (rekursiv, 18.01.03).

    Liefert deterministisch (Set-Reihenfolge = display_name) alle Sets,
    deren `category`-Pfad mit `category_path` beginnt – d.h. auch Sets in
    UNTER-Ordnern (z.B. Pfad 'Swing Points' liefert auch Sets aus
    'Swing Points/Geometrie'). Pfad-Format: slash-separiert OHNE
    '📁 '-Praefixe, case-insensitiv. Analog `category_plugin_ids` fuer
    die Sets-Gruppe.
    """
    target = [p.strip().lower() for p in str(category_path or "").split("/")
              if p.strip()]
    if not target:
        return []
    result: List[str] = []
    for s in sorted(sets_data, key=lambda x: str(
            x.get("display_name") or x.get("set_id") or "").lower()):
        parts = [p.lower() for p in _set_category_parts(s)]
        if len(parts) >= len(target) and parts[:len(target)] == target:
            result.append(str(s.get("set_id") or ""))
    return result


def plugin_category_path(plugin_id: str, plugin: Optional[Any],
                         overrides: Dict[str, str]) -> str:
    """Aktueller Kategorie-Pfad eines Plugins (lesend, 18.01.03).

    Liefert den voll aufgeloesten Pfad (Override -> metadata['category'])
    slash-separiert OHNE '📁 '-Praefix (z.B. 'Swing Points/Geometrie');
    leer = Root-Ebene. Ist das Plugin nicht registriert, gilt leer
    (Spiegel der Original-Semantik: Override wird nur bei vorhandenem
    Plugin ausgewertet).
    """
    if not plugin_id:
        return ""
    parts = _category_parts(plugin_id, plugin, overrides) if plugin else []
    return "/".join(parts)


def category_service_plugin_ids(group: str,
                                sets_data: List[Dict[str, Any]],
                                plugins: Dict[str, Any],
                                overrides: Dict[str, str],
                                category_path: str) -> List[str]:
    """Alle plugin_ids unter einem Kategorie-Ordner (rekursiv, 18.01.03).

    Gruppenspezifische Aufloesung (L3):
      * group == GROUP_SETS    -> Sets unter dem Pfad
        (category_set_ids), dann alle plugin_ids ihrer Services
        (execution_order, dedupliziert, deterministisch).
      * group == GROUP_PLUGINS -> Plugins unter dem Pfad
        (category_plugin_ids).
    Leerer Pfad/leere Gruppe -> [] (defensiv). Wird von den Run-/Info-
    Aktionen des ServiceWindow und der Picker-Aufloesung genutzt.
    """
    if str(group or "") == str(GROUP_SETS):
        ids: List[str] = []
        for set_id in category_set_ids(sets_data, category_path):
            definition = _find_set(sets_data, set_id) or {}
            services = definition.get("services") or {}
            order = definition.get("execution_order") \
                or list(services.keys())
            for iid in order:
                cfg = services.get(iid) or {}
                pid = str(cfg.get("plugin_id") or iid)
                if pid and pid not in ids:
                    ids.append(pid)
        return ids
    return category_plugin_ids(plugins, overrides, category_path)


# ------------------------------------------------------------------
# Baumaufbau
# ------------------------------------------------------------------
def build_tree(sets_data: List[Dict[str, Any]],
               plugins: Dict[str, Any],
               overrides: Dict[str, str],
               empty_folders: Dict[str, List[str]],
               badges: Dict[str, str],
               last_executions: Dict[str, str],
               presets: Optional[Dict[str, List[Dict[str, Any]]]] = None
               ) -> List[Dict[str, Any]]:
    """Baut die vollstaendige Hierarchie fuer das 2-Spalten-MasterTree.

    17.01.01: NUR noch 2 Root-Gruppen – die ehemalige Gruppe
    '⚡ Standalone Services' (GROUP_STANDALONE) entfaellt ersatzlos, da
    alle Plugins ueber metadata['category'] in Ordner einsortiert werden.
    Root-Label kompakt: '📁 Sets' und '📦 Services'.

    20.04 (Q6/Q7): Plugins MIT Presets werden als Parent-Knoten mit
    Clone-Kindern gerendert (`clones` im Blatt-Dict); archivierte Clones
    bzw. archivierte Sets/Instanzen (is_archived=True) wandern in den
    dynamischen '📁 Archiv'-Ordner (per 'archived'-Flag markiert,
    non-checkable im MasterTree).

    Rueckgabe (pro Gruppe ein Dict):
        [{"group": "sets", "label": "📁 Sets", "children": [
             {"set_id": ..., "display_name": ..., "definition": {...},
              "services": [{"instance_id": ..., "plugin_id": ...,
                            "badge": ...}, ...]}, ...]},
         {"group": "plugins", "label": "📦 Services",
          "children": [Blatt- und/oder Ordner-Knoten ...]}]

    Deterministisch sortiert (Sets nach display_name; Plugins/Ordner
    alphabetisch, 16.08 K8; '📁 Archiv' immer am Ende). Die Kinder der
    Plugin-Gruppen sind eine Mischung aus flachen Blatt-Dicts
    ({plugin_id, badge, last_execution}) und verschachtelten Ordner-Dicts
    ({"group": GROUP_CATEGORY, "label": "📁 <Name>", "children": [...]} –
    rekursiv), gesteuert ueber das Metadaten-Feld `category` der Plugins
    (K1). Dieselbe Ordner-Mechanik gilt fuer die Sets-Gruppe (18.01.03):
    Set-Definitionen mit `category`-Feld werden in identische Ordner-Dicts
    einsortiert, Sets ohne Kategorie bleiben flache Blaetter. Seit 18.01.03
    (E3-revidiert) werden zusaetzlich benutzererzeugte (ggf. leere) Ordner
    aus `empty_folders` (global_settings Key 'tree_folders_<group>') in die
    Gruppen-Kinder eingemischt – leere Ordner bleiben ueber Refreshs
    erhalten und verschwinden NUR bei manueller Loeschung im Kontextmenue.
    """
    sets = sorted(sets_data,
                  key=lambda s: str(s.get("display_name") or s.get("set_id") or "").lower())
    # Sets-Kategorien (Dynamic Category Trees fuer GROUP_SETS). Set-
    # Definitionen mit `category`-Pfad werden in 📁-Ordner einsortiert
    # (rekursiv, gleiche K2/K8/K9-Regeln wie die Plugins); ohne Kategorie
    # bleiben sie flache Blaetter auf oberster Ebene.
    set_nodes: List[Dict[str, Any]] = []
    # 20.04 (Q6): Archivierte Sets/Instanzen (is_archived=True) – sie
    # wandern in den '📁 Archiv'-Ordner der Sets-Gruppe (non-checkable).
    archive_set_nodes: List[Dict[str, Any]] = []
    for s in sets:
        services = s.get("services") or {}
        order = s.get("execution_order") or []
        set_archived = bool(s.get("is_archived"))
        service_nodes: List[Dict[str, Any]] = []
        archived_service_nodes: List[Dict[str, Any]] = []
        for iid in order:
            cfg = services.get(iid) or {}
            pid = str(cfg.get("plugin_id") or iid)
            svc_node = {
                "instance_id": iid,
                "plugin_id": pid,
                "badge": badges.get(pid, ""),
                "last_execution": last_executions.get(pid, "--.--.--"),
                "instance_hash": str(cfg.get("instance_hash") or ""),
                "is_archived": bool(cfg.get("is_archived")),
                "doc_log": str(cfg.get("doc_log") or ""),
                "params": cfg.get("params") or {},
            }
            if set_archived or svc_node["is_archived"]:
                archived_service_nodes.append(svc_node)
            else:
                service_nodes.append(svc_node)
        set_leaf = {
            "set_id": s.get("set_id"),
            "display_name": s.get("display_name") or s.get("set_id") or "Unbenannt",
            "definition": s,
            "services": service_nodes,
        }
        if set_archived:
            # Ganzes Set archiviert -> komplett in den Archiv-Ordner.
            archive_set_nodes.append(dict(set_leaf, archived=True))
        else:
            _insert_set_into_category_tree(
                set_nodes, _set_category_parts(s), set_leaf)
            # 20.04 (Q6): Einzeln archivierte Instanzen eines AKTIVEN Sets
            # erscheinen als eigene Eintraege im Archiv-Ordner (Anzeige
            # '<Set> / <instance_id>').
            for svc_node in archived_service_nodes:
                archive_set_nodes.append({
                    "set_id": s.get("set_id"),
                    "display_name": f"{s.get('display_name') or s.get('set_id') or 'Unbenannt'} / {svc_node['instance_id']}",
                    "definition": s,
                    "services": [svc_node],
                    "archived": True,
                })
    set_nodes = _sort_category_nodes(set_nodes)

    # EINE kategorisierte Services-Gruppe – Plugins mit `category`-Metadatum
    # werden in 📁-Ordner verschachtelt (K1), ohne Kategorie bleiben sie
    # flache Blaetter auf oberster Ebene. Die fruehere Standalone-Gruppe
    # (separate Knoten) ist entfallen. 20.04 (Q7): presets steuern die
    # Parent-Child-Clone-Ansicht + den Archiv-Ordner.
    plugin_nodes = _category_nodes(sorted(plugins.keys()), plugins,
                                   overrides, badges, last_executions,
                                   presets)

    # 18.01.03 (E3-revidiert): Persistierte benutzererzeugte (ggf. leere)
    # Ordner in die Gruppen-Kinder einmischen – leere Ordner verschwinden
    # damit NICHT beim Refresh, sondern nur bei manueller Loeschung
    # (Kontextmenue 'Ordner löschen'). Bereits vorhandene Ordner (aus
    # echten Blatt-Kategorien) werden wiederverwendet (kein Duplikat).
    for group, nodes in ((GROUP_SETS, set_nodes), (GROUP_PLUGINS, plugin_nodes)):
        for path in empty_folders.get(group, []) or []:
            parts = [p.strip() for p in str(path or "").split("/")
                     if p.strip()]
            if parts:
                _ensure_category_path(nodes, parts)

    # 20.04 (Q6): Archiv-Ordner der Sets-Gruppe (falls vorhanden) ans Ende.
    if archive_set_nodes:
        archive_set_nodes.sort(
            key=lambda n: str(n.get("display_name") or "").lower())
        set_nodes.append({
            "group": GROUP_CATEGORY,
            "label": ARCHIVE_LABEL,
            "children": archive_set_nodes,
            "archived": True,
        })
    set_nodes = _sort_category_nodes(set_nodes)
    plugin_nodes = _sort_category_nodes(plugin_nodes)

    return [
        {"group": GROUP_SETS, "label": "📁 Sets", "children": set_nodes},
        {"group": GROUP_PLUGINS, "label": "📦 Services",
         "children": plugin_nodes},
    ]
