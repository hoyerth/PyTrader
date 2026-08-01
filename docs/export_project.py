# docs/export_project.py
"""
export_project.py - Exportiert ALLE Projekt-Quellen nach docs/x_Exports.md

- Projekt-Root wird stabil ueber __file__ bestimmt (unabhaengig vom CWD).
- Ausgabe erfolgt IMMER in den docs-Ordner.
- Inkludiert alle Quellen: .py, .js, .ui, .sql, .json, .yaml/.yml, .toml, .md.
- Der komplette docs-Ordner (Konzepte/Roadmaps) wird NICHT exportiert.
"""

import os
from pathlib import Path

# Projekt-Root: Elternverzeichnis von docs/ (stabil, unabhaengig vom Arbeitsverzeichnis)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Ausgabedatei: immer im docs-Ordner
OUTPUT_PATH: Path = Path(__file__).resolve().parent / "x_Exports.md"

# Dateiendungen, die in den Export aufgenommen werden (inkl. .js und .md)
ALLOWED_EXTENSIONS = {
    '.py', '.js', '.ui', '.sql', '.json', '.yaml', '.yml', '.toml', '.md',
}

# Ordner, die ignoriert werden sollen (keine Quellen)
# docs/ wird komplett ausgeschlossen: Konzepte/Roadmaps (x_*.md, Agents.md)
# gehoeren nicht in den Code-Export. Damit faellt auch x_Exports.md selbst weg.
IGNORE_DIRS = {
    '.git', '.idea', '__pycache__', 'venv', 'env', 'build', 'dist', '.venv',
    'node_modules', '.pytest_cache', 'docs',
}

# Dateien, die ignoriert werden sollen (Ausnahme: x_Exports.md selbst)
IGNORE_FILES = {'x_Exports.md'}


def _collect_files() -> list:
    """Sammelt alle zu exportierenden Dateien (relativer Pfad) in fester Reihenfolge."""
    collected = []
    for root, dirs, files in os.walk(PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for file in files:
            if file in IGNORE_FILES:
                continue
            ext = Path(file).suffix.lower()
            if ext not in ALLOWED_EXTENSIONS:
                continue
            full_path = Path(root) / file
            collected.append(full_path.relative_to(PROJECT_ROOT))
    # Sortiert nach (Ordner, Dateiname) fuer eine stabile, reproduzierbare Ausgabe
    collected.sort(key=lambda p: (p.parent.as_posix().lower(), p.name.lower()))
    return collected


def build_project_export() -> None:
    output_path: Path = OUTPUT_PATH

    with open(output_path, 'w', encoding='utf-8') as out_file:
        out_file.write(f"# PROJEKT-ÜBERSICHT: {PROJECT_ROOT.name}\n\n")

        # 1. Dateibaum generieren (nur Dateien mit erlaubten Endungen)
        out_file.write("## 1. ORDNERSTRUKTUR\n```\n")
        for root, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            level = len(Path(root).relative_to(PROJECT_ROOT).parts)
            indent = ' ' * 4 * level
            out_file.write(f"{indent}{Path(root).name}/\n")
            sub_indent = ' ' * 4 * (level + 1)
            for f in sorted(files, key=str.lower):
                if f not in IGNORE_FILES and Path(f).suffix.lower() in ALLOWED_EXTENSIONS:
                    out_file.write(f"{sub_indent}{f}\n")
        out_file.write("```\n\n")

        # 2. Dateiinhalte anhängen
        out_file.write("## 2. QUELLCODE\n\n")
        files = _collect_files()
        for rel_path in files:
            full_path = PROJECT_ROOT / rel_path
            ext = rel_path.suffix.lower()

            # Sprachbezeichnung für Markdown-Codeblock (.ui ist XML)
            lang = "xml" if ext == ".ui" else ext.replace(".", "")

            out_file.write(f"### DATEI: {rel_path.as_posix()}\n")
            out_file.write(f"```{lang}\n")

            try:
                with open(full_path, 'r', encoding='utf-8') as src_file:
                    out_file.write(src_file.read())
            except Exception as e:
                out_file.write(f"# Fehler beim Lesen der Datei: {e}\n")

            out_file.write("\n```\n\n" + "-" * 50 + "\n\n")

    print(f"Fertig! x_Exports.md erfolgreich erstellt unter:\n{output_path}")
    print(f"Inkludierte Dateien: {len(files)}")


if __name__ == '__main__':
    build_project_export()
