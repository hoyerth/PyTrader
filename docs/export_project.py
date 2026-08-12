# docs/export_project.py
"""
export_project.py - Exportiert Projekt-Quellen nach docs/exports/

Aufteilung (sachbezogene Teil-Exporte + Gesamt-Export):
  export_Full.md             - Gesamt-Export (ALLE Projekt-Quellen)
  export_core_app.md         - Core App & Infrastruktur (main, persistent_win,
                                state_manager, properties_win, db_service,
                                db/db_utils)
  export_service_engine.md   - Service-UI & Service-Engine (serviceui/,
                                analytics/engine/service_*, historical_scanner)
  export_analytics.md        - Analytics-UI & Feature Store (analytics/ui/,
                                analytics/engine/analytics_*, feature_store_reader)
  export_chart_engine.md     - Chart-Fenster & Lightweight Charts (chart/)
  export_data_layer.md       - Datenzugriff, Sync & Repositories (db/, data_sync/,
                                repositories/, *_repository.py)
  export_analytics_engine.md - Analytics-Engine, Features & Auswertung
  export_ui_windows.md       - Weitere Fenster, Worker & Konfiguration (ui/,
                                workers/, config/, statistic_win, scrollable_content)
  export_tests.md            - Tests & Checks (test/)
  export_project_docs.md     - Projekt-Dokumentation (Agents.md, Architektur.md)

Invariante: Die Summe aller Teil-Exporte ergibt exakt den Gesamt-Export
(export_Full.md) - jede exportierte Datei erscheint in genau einem Teil-Export.
Nicht zugeordnete Dateien werden automatisch in export_rest.md aufgenommen,
damit die Invariante auch bei neuen Dateien erhalten bleibt.

Regeln: ALLOWED_EXTENSIONS / IGNORE_DIRS / IGNORE_FILES gelten identisch fuer
alle erzeugten Dateien. docs/exports/ wird nie mit-exporiert.

- Projekt-Root wird stabil ueber __file__ bestimmt (unabhaengig vom CWD).
- Ausgabe erfolgt IMMER in den Ordner docs/exports/.
"""

import os
from pathlib import Path
from typing import Dict, List

# Projekt-Root: Elternverzeichnis von docs/ (stabil, unabhaengig vom Arbeitsverzeichnis)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Ausgabeordner: immer docs/exports/
EXPORT_DIR: Path = Path(__file__).resolve().parent / "exports"
FULL_EXPORT: Path = EXPORT_DIR / "export_Full.md"

# Dateiendungen, die in den Export aufgenommen werden (inkl. .js und .md)
ALLOWED_EXTENSIONS = {
    '.py', '.js', '.ui', '.sql', '.json', '.yaml', '.yml', '.toml', '.md',
}

# Ordner, die ignoriert werden sollen (keine Quellen)
# docs/ wird komplett ausgeschlossen: Konzepte/Roadmaps (x_*.md, Agents.md)
# gehoeren nicht in den Code-Export. Damit faellt auch docs/exports/ (eigene
# Exportdateien) mit weg - wird zusaetzlich explizit gefuehrt, damit sie
# selbst dann nicht in den Export geraten, wenn die docs-Ausnahme entfaellt.
IGNORE_DIRS = {
    '.git', '.idea', '__pycache__', 'venv', 'env', 'build', 'dist', '.venv',
    'node_modules', '.pytest_cache', 'docs', 'exports', 'test',
}

# Dateien, die ignoriert werden sollen (Exportdateien, egal wo abgelegt)
IGNORE_FILES = {'x_Exports.md', 'export_Full.md'}

# ---------------------------------------------------------------------------
# Paket-Definitionen (Dateiname, Titel, Quellen als Relativpfade bzw. Ordner)
# ---------------------------------------------------------------------------
EXPORT_PACKAGES: List[Dict[str, object]] = [
    {
        "file": "export_core_app.md",
        "title": "Core App & Infrastruktur",
        "paths": [
            "main.py",
            "persistent_win.py",
            "state_manager.py",
            "properties_win.py",
            "db_service.py",
            "db/db_utils.py",
        ],
    },
    {
        "file": "export_service_engine.md",
        "title": "Service-UI & Service-Engine",
        "paths": [
            "serviceui/",
            "analytics/engine/service_models.py",
            "analytics/engine/service_selector_model.py",
            "analytics/engine/service_set_repository.py",
            "analytics/background_workers/historical_scanner.py",
        ],
    },
    {
        "file": "export_analytics.md",
        "title": "Analytics-UI & Feature Store",
        "paths": [
            "analytics/ui/",
            "analytics/engine/analytics_repository.py",
            "analytics/engine/analytics_view_model.py",
            "analytics/engine/analytics_worker.py",
            "analytics/engine/feature_store_reader.py",
        ],
    },
    {
        "file": "export_chart_engine.md",
        "title": "Chart-Fenster & Lightweight Charts",
        "paths": ["chart/"],
    },
    {
        "file": "export_data_layer.md",
        "title": "Datenzugriff, Sync & Repositories",
        "paths": [
            "db/__init__.py",
            "db/db_pool.py",
            "db/schema_initializer.py",
            "data_sync/",
            "repositories/",
            "symbol_repository.py",
            "window_state_repository.py",
            "analytics_profile_repository.py",
        ],
    },
    {
        "file": "export_analytics_engine.md",
        "title": "Analytics-Engine, Features & Auswertung",
        "paths": [
            "analytics/__init__.py",
            "analytics/statistics_repository.py",
            "analytics/background_workers/__init__.py",
            "analytics/background_workers/live_analyzer.py",
            "analytics/engine/__init__.py",
            "analytics/engine/description_dialog.py",
            "analytics/engine/schema_migrator.py",
            "analytics/engine/set_evaluator.py",
            "analytics/engine/tree_builder.py",
            "analytics/features/",
        ],
    },
    {
        "file": "export_ui_windows.md",
        "title": "Weitere Fenster, Worker & Konfiguration",
        "paths": [
            "ui/",
            "workers/",
            "scrollable_content.py",
            "statistic_win.py",
            "config/",
        ],
    },
    {
        "file": "export_project_docs.md",
        "title": "Projekt-Dokumentation",
        "paths": ["Agents.md", "Architektur.md"],
    },
]


def _is_allowed(rel: Path) -> bool:
    """Prueft die Export-Regeln fuer einen Relativpfad (Endung, IGNORE_FILES,
    Elternordner). Gilt identisch fuer alle erzeugten Dateien."""
    if rel.name in IGNORE_FILES:
        return False
    if rel.suffix.lower() not in ALLOWED_EXTENSIONS:
        return False
    for part in rel.parts[:-1]:
        if part in IGNORE_DIRS:
            return False
    return True


def _sort_key(p: Path):
    """Stabile, reproduzierbare Sortierung nach (Ordner, Dateiname)."""
    return (p.parent.as_posix().lower(), p.name.lower())


def _collect_files() -> list:
    """Sammelt alle zu exportierenden Dateien (relativer Pfad) in fester Reihenfolge."""
    collected = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for file in files:
            full_path = Path(root) / file
            rel = full_path.relative_to(PROJECT_ROOT)
            if _is_allowed(rel):
                collected.append(rel)
    collected.sort(key=_sort_key)
    return collected


def _resolve_paths(specs: List[str]) -> List[Path]:
    """Loest Paket-Spezifikationen (Datei ODER Ordner) zu Relativpfaden auf.

    Ordner werden rekursiv mit denselben Regeln (IGNORE_DIRS/IGNORE_FILES/
    ALLOWED_EXTENSIONS) gescannt wie der Voll-Export.
    """
    result: List[Path] = []
    for spec in specs:
        base = PROJECT_ROOT / spec
        if base.is_dir():
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                for name in files:
                    rel = (Path(root) / name).relative_to(PROJECT_ROOT)
                    if _is_allowed(rel):
                        result.append(rel)
        elif base.is_file():
            rel = base.relative_to(PROJECT_ROOT)
            if _is_allowed(rel):
                result.append(rel)
        else:
            print(f"WARN [export_project] Spezifikation nicht gefunden: {spec}")
    result = sorted(set(result), key=_sort_key)
    return result


def _partition_files() -> List[Dict[str, object]]:
    """Berechnet die Datei-Listen je Paket und prueft die Vollstaendigkeits-Invariante.

    Invariante: Summe der Teil-Exporte == Voll-Export (jede Datei in genau
    einem Paket). Fehlende Zuordnungen landen automatisch in export_rest.md.
    """
    full = set(_collect_files())
    packages: List[Dict[str, object]] = []
    seen: set = set()
    for pkg in EXPORT_PACKAGES:
        files = _resolve_paths(pkg["paths"])  # type: ignore[arg-type]
        dupes = sorted(set(files) & seen)
        if dupes:
            raise SystemExit(f"FEHLER [export_project] Dateien in mehreren Paketen: {dupes}")
        seen.update(files)
        packages.append({**pkg, "files": files})
    missing = sorted(full - seen)
    if missing:
        print(f"WARN [export_project] {len(missing)} Datei(en) ohne Paket "
              f"-> automatisch in export_rest.md")
        packages.append({
            "file": "export_rest.md",
            "title": "Rest (automatisch ergaenzt)",
            "paths": [],
            "files": missing,
        })
        seen.update(missing)
    overlap = sorted(seen - full)
    if overlap:
        print(f"WARN [export_project] Pakete enthalten nicht exportierbare "
              f"Dateien: {overlap}")
    exact = seen == full
    print(f"[export_project] Partition: {len(full)} Dateien im Voll-Export, "
          f"{len(packages)} Pakete, Summe={len(seen)}, exakt={exact}")
    return packages


def _render_tree(files: List[Path]) -> str:
    """Baut den Ordnerbaum aus einer Dateiliste (Relativpfade)."""
    tree: dict = {}
    for p in files:
        node = tree
        for part in p.parts:
            node = node.setdefault(part, {})
    lines = [PROJECT_ROOT.name + "/"]

    def _walk(node, prefix):
        for name in sorted(node, key=str.lower):
            sub = node[name]
            lines.append(prefix + (name + "/" if sub else name))
            if sub:
                _walk(sub, prefix + "    ")

    _walk(tree, "    ")
    return "\n".join(lines)


def _write_export(path: Path, title: str, files: List[Path],
                  is_full: bool = False,
                  package_index: List[Dict[str, object]] = None) -> None:
    """Schreibt eine Exportdatei (Voll- oder Teil-Export) mit gleichem Layout.

    Layout: Kopf (Titel/Zweck), 1. ORDNERSTRUKTUR (nur eigene Dateien),
    2. QUELLCODE (alle Dateien mit Markdown-Codeblock).
    """
    with open(path, 'w', encoding='utf-8') as out:
        out.write(f"# PROJEKT-ÜBERSICHT: {PROJECT_ROOT.name} — {title}\n\n")
        if is_full:
            names = ", ".join(str(p["file"]) for p in (package_index or []))
            out.write(f"> Gesamt-Export (alle Projekt-Quellen). Teil-Exporte: {names}\n")
        else:
            out.write(f"> Teil-Export (sachbezogen). Vollständiger Export: {FULL_EXPORT.name}\n")
        out.write(f"> Dateien in dieser Datei: {len(files)}\n\n")

        if is_full and package_index:
            out.write("## 0. EXPORT-ÜBERSICHT\n\n")
            out.write("| Datei | Inhalt | Dateien |\n|---|---|---|\n")
            out.write(f"| {FULL_EXPORT.name} | Gesamt-Export (diese Datei) | {len(files)} |\n")
            for p in package_index:
                out.write(f"| {p['file']} | {p['title']} | {len(p['files'])} |\n")
            out.write("\n")

        out.write("## 1. ORDNERSTRUKTUR\n```\n")
        out.write(_render_tree(files))
        out.write("\n```\n\n")

        out.write("## 2. QUELLCODE\n\n")
        for rel in files:
            full_path = PROJECT_ROOT / rel
            ext = rel.suffix.lower()
            # Sprachbezeichnung für Markdown-Codeblock (.ui ist XML)
            lang = "xml" if ext == ".ui" else ext.replace(".", "")
            out.write(f"### DATEI: {rel.as_posix()}\n")
            out.write(f"```{lang}\n")
            try:
                with open(full_path, 'r', encoding='utf-8') as src_file:
                    out.write(src_file.read())
            except Exception as e:
                out.write(f"# Fehler beim Lesen der Datei: {e}\n")
            out.write("\n```\n\n" + "-" * 50 + "\n\n")


def build_project_export() -> None:
    """Erzeugt den Gesamt-Export und alle Teil-Exporte in docs/exports/."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    packages = _partition_files()
    full_files = sorted(_collect_files(), key=_sort_key)

    # 1. Gesamt-Export
    _write_export(FULL_EXPORT, "Gesamt-Export (alle Projekt-Quellen)",
                  full_files, is_full=True, package_index=packages)

    # 2. Teil-Exporte (Summe == Voll-Export)
    for pkg in packages:
        target = EXPORT_DIR / str(pkg["file"])
        _write_export(target, str(pkg["title"]), pkg["files"], is_full=False)

    print("Fertig! Exporte erzeugt in:")
    print(f"  {FULL_EXPORT}  ({len(full_files)} Dateien)")
    for pkg in packages:
        print(f"  {EXPORT_DIR / str(pkg['file'])}  ({len(pkg['files'])} Dateien)")


if __name__ == '__main__':
    build_project_export()
