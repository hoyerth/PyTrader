# Phase 21: Fachliche Feinabstimmung Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 21)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase21_step1`, `phase21_step1` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Codebase-Formatierung:** Exakt **4 Leerzeichen** Einrückung (PEP8-Standard) und **exakt 1 Leerzeile** Spacing zwischen Methoden und Funktionsblöcken. Kein Umformatieren unbeteiligter Altbestand-Dateien.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`. `MasterTree`-Selektionen übergeben aufgelöste `feature_ids` sowie `instance_hashes` direkt an `view_model.set_feature_ids(ids, hashes)`.
5. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`db/db_pool.py`) – eine Verbindung pro Thread und DB-Datei. Die Fassade `db_service.py` bleibt als Re-Export-Wrapper für bestehende Caller erhalten.
7. **Tree-Persistenz & Kategorisierung:** 
   - Service-Kategorien werden primär im Code/Plugin über `metadata["category"]` (Slash-separierter Ordnerpfad) deklariert.
   - Ordner-Kategorien für Service-Sets werden im `category`-Feld der `ServiceSetDefinition` / des `save_set()`-Payloads persistiert.
   - Parameter-Varianten (Clones/Presets) werden transparent über `indicator_presets` und `instance_hash` im FeatureStore geführt.
8. **Wanduhr-Garantie (Invariante 7):** MT5-Epochs sind bereits Berlin-Wanduhr-encoded. SQL-Extraktionen (Heatmap, DOW, Hour, Date) nutzen strikt `bar_time AT TIME ZONE 'UTC'`, um eine fehlerhafte automatische Umrechnung durch DuckDB in Lokalzeiten zu unterbinden.
9. **Concurrency-Guard & Timer-Pausierung:** Solange im ServiceWindow intensive Service-Berechnungen laufen (`ServiceRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
10. **Isolierter Test-Workspace & Cleanup:** Neue Test-Skripte und temporäre `*.duckdb`-Dateien gehören strikt nach `test/`. Nach Abschluss jedes Phasenkapitels wird `test/` aufgeräumt – es verbleibt nur der Test-Harness `test/test.py`.
11. **Open/Closed-Principle & Code-Preserving:** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden; bestehende Kern-Klassen bleiben geschützt.
12. **Naming Conventions & PineScript-Input-Zone:** 
    - Services in `analytics/features/definitions/` nutzen strikt das Präfix `srv_` (`plugin_id = "srv_..."`).
    - Indikatoren in `chart/indicators/` nutzen strikt das Präfix `ind_` (`indicator_id = "ind_..."`).
    - Füllwörter (`service`, `plugin`, `indicator`) entfallen im Dateinamen.
    - Das `parameter_schema` liegt direkt am Dateianfang unter dem Header-Docstring.
    - Jedes Service-Plugin deklariert `metadata["category"]` für die dynamische Kategorie-Ordner-Struktur im MasterTree.

---

# 21.02 – DB Bloat Analysis & Maintenance (VACUUM)

## 🎯 1. Kern-Anforderungen

1. **Bloat-Analyse:** Startup-Anzeige auf `MainWindow` unter Optionen-Button via `PRAGMA database_size`.
2. **Vacuum Execution:** Button `[ 🧹 DB Service (VACUUM) ]` in `PropertiesWindow` führt `VACUUM;` aus.
3. **Concurrency-Guard:** `VACUUM` sperren, solange `_sync_pause_count > 0` (laufende Scans/Worker).

---

## 🛠️ 2. Schritt-für-Schritt Umsetzungsanleitung

### Schritt 1: Core Engine (`db/db_utils.py`)

Füge folgende Funktionen in `db/db_utils.py` ein:

# db/db_utils.py
import os
from db.db_pool import DbPool

def get_db_fragmentation_info(db_path: str) -> dict:
    if not os.path.exists(db_path):
        return {"pct": 0, "bloat_mb": 0, "size_mb": 0}
    file_bytes = os.path.getsize(db_path)
    try:
        con = DbPool.get(db_path)
        res = con.execute("PRAGMA database_size;").fetchone()
        block_size, used_blocks = (res[1], res[3]) if res else (262144, 0)
        netto_bytes = used_blocks * block_size
        bloat_bytes = max(0, file_bytes - netto_bytes)
        return {
            "pct": round((bloat_bytes / file_bytes * 100), 1) if file_bytes else 0,
            "bloat_mb": round(bloat_bytes / (1024 * 1024), 1),
            "size_mb": round(file_bytes / (1024 * 1024), 1)
        }
    except Exception:
        return {"pct": 0, "bloat_mb": 0, "size_mb": round(file_bytes / (1024 * 1024), 1)}

def execute_db_vacuum(db_path: str) -> None:
    con = DbPool.get(db_path)
    con.execute("VACUUM;")

---

### Schritt 2: Startup Status (`main.py`)[cite: 1]
Beim App-Start in `main.py` aufrufen und UI-Label unter Optionen-Button befüllen:


# main.py
from db.db_utils import get_db_fragmentation_info

info = get_db_fragmentation_info("data/analytics.duckdb")
# UI-Label setzen (z. B. label_db_status)
self.label_db_status.setText(f"DB Status: {info['pct']}% fragmentiert ({info['bloat_mb']} MB frei)")

---

### Schritt 3: UI & Concurrency Guard (`properties_win.py`)[cite: 1]
Button `[ 🧹 DB Service (VACUUM) ]` einbauen und mit Concurrency Guard schützen:


# properties_win.py
from db.db_utils import execute_db_vacuum, get_db_fragmentation_info

def _on_btn_vacuum_clicked(self) -> None:
    # Concurrency-Guard
    if getattr(self.parent(), "_sync_pause_count", 0) > 0:
        print("⚠️ VACUUM gesperrt: Scans/Worker laufen aktuell.")
        return

    execute_db_vacuum("data/analytics.duckdb")
    execute_db_vacuum("data/market_data.duckdb")
    print("✅ DB Vacuum erfolgreich ausgeführt.")

---

## 📊 3. Akzeptanzkriterien (`test/test.py`)[cite: 1]
1. `get_db_fragmentation_info()` liefert Prozent-, Bloat- und Größen-MB-Werte ohne Exception zurück[cite: 1].
2. `execute_db_vacuum()` schließt fehlerfrei ab[cite: 1].

---

## 📝 4. Prüfung & Entscheidungen (12.08.2026)

> Implementierungs-Log: Konsistenz-/Korrektheits-/Vollständigkeits-Prüfung von Kap. 21.02 gegen den Code-Stand (Commit `bfaf971`). **Kein Coding** – reine Doku der Befunde und getroffenen Entscheidungen.

### 4.1 Status
- Kap. 21.02 ist eine **Spezifikation/Umsetzungsanleitung** – die Umsetzung ist **offen** (kein Code vorhanden).
- **Beschluss (12.08.2026):** Kein Coding jetzt; Umsetzung erst nach expliziter Anweisung. Die Prüf-/Arbeitsmethode (headless-Verifikation + Doku-Log) wird weiterhin ausgearbeitet.

### 4.2 Vollständigkeit (Code-Befund)
| Schritt | Doku-Vorgabe | Stand |
|---|---|---|
| Schritt 1 | `get_db_fragmentation_info()` / `execute_db_vacuum()` in `db/db_utils.py` | ❌ nicht vorhanden (`db_utils.py`: nur `_ensure_epoch`/`_parse_json_field`) |
| Schritt 2 | Startup-Aufruf `main.py` + `label_db_status` | ❌ nicht vorhanden; Label existiert auch nicht in `ui/main_win.ui` |
| Schritt 3 | VACUUM-Button in `properties_win.py` + Guard | ❌ nicht vorhanden |
| AK 1–2 | Headless-Tests | ❌ nicht verifizierbar (Code fehlt) |

✅ Vorhanden als Grundlage: `_sync_pause_count` in `main.py:166` (Phase-16-EventBus-Guard, Signale `service_run_started`/`service_run_finished`).

### 4.3 Befunde der Konsistenz-/Korrektheits-Prüfung
- **K1 (Guard wirkungslos):** `PersistentWindow.__init__` übergibt **kein Qt-Parent** (`super().__init__()` ohne parent, Logik-Parent nur für `state_manager`) → `self.parent()` ist `None` → `getattr(self.parent(), "_sync_pause_count", 0)` greift **nie** (immer Default 0).
- **K2 (Label fehlt):** `label_db_status` existiert nicht in `ui/main_win.ui` (dort nur `status_label`); kein dedizierter Platz „unter dem Optionen-Button".
- **F1 (falscher PRAGMA-Spalten-Index):** `PRAGMA database_size` (DuckDB 1.5.5) liefert: `0 database_name, 1 database_size (VARCHAR), 2 block_size, 3 total_blocks, 4 used_blocks, 5 free_blocks, 6 wal_size, 7 memory_usage, 8 memory_limit`. Der Snippet nutzt `res[1], res[3]` = **`database_size` (String!)** + **`total_blocks`** → falsch.
- **F2 (VACUUM wirkungslos, empirisch belegt):** `INSERT 500k → DELETE → VACUUM;` sowie `CHECKPOINT;` ändern die Dateigröße **nicht** (0 % Reduktion); `PRAGMA database_size` vor/nach identisch. DuckDB 1.5.5 besitzt **kein echtes VACUUM** wie SQLite – das Ziel „Bloat reduzieren" ist mit `VACUUM;` nicht erreichbar. AK2 („verringert/konsolidiert Blöcke") ist damit nicht erfüllbar.

### 4.4 Entscheidungen (12.08.2026)
| Punkt | Entscheidung |
|---|---|
| **F1** (PRAGMA-Index) | ✅ **Bestätigt:** Korrektur auf `block_size, used_blocks = res[2], res[4]` |
| **K1** (Concurrency-Guard) | ✅ **Bestätigt:** Guard über `EventBus`-Zähler (konsistent zu Phase 16) statt `self.parent()` |
| **K2** (Status-Label) | ✅ **Bestätigt:** `label_db_status` wird ergänzt (in `ui/main_win.ui` oder per Code – Detail bei Umsetzung) |
| **F2** (VACUUM-Ziel) | ✅ **Entschieden:** Zweistufige Lösung – **CHECKPOINT + VACUUM beim App-Exit** (reguläre Pflege) + **COPY FROM DATABASE-Methode** (echte Kompaktierung). Siehe 4.6 |
| Umsetzung allgemein | ⏸️ **Zurückgestellt:** Kein Coding jetzt |

### 4.5 Ergänzungen (bei späterer Umsetzung zu beachten)
- `db/db_utils.py`: fehlendes `import os` im Snippet beachten; `DbPool`-Import ist innerhalb des `db`-Pakets zulässig (Basis-Schicht E4 bleibt sonst ohne Projekt-Import).
- Markdown-Artefakte `[cite: 1]` im Kapitel bereinigen.
- AK2-Formulierung folgt der F2-Lösung (siehe 4.6): `CHECKPOINT`/`VACUUM` allein verkleinern die Datei nicht – die **Kompaktierung** leistet `COPY FROM DATABASE`.

### 4.6 Lösungsweg F2: DB-Pflege beim App-Exit + Kompaktierung per COPY FROM DATABASE

**Beschluss (12.08.2026):** Die DB-Pflege wird zweistufig umgesetzt. Empirisch belegt (DuckDB 1.5.5): `VACUUM;` und `CHECKPOINT;` verkleinern die Datei **nicht** (0 % Reduktion, `PRAGMA database_size` unverändert). Die tatsächliche Kompaktierung leistet die **`COPY FROM DATABASE`-Methode**.

#### Stufe 1 – Beim Verlassen der App (regulär, `main.py` `closeEvent`)
Beim App-Exit wird für jede DuckDB-Datei ausgeführt:
```sql
CHECKPOINT;   -- WAL in Hauptdatei flushen (konsistenter Zustand)
VACUUM;       -- formale Defragmentierung (in DuckDB 1.5.5 ohne Dateigrößen-Effekt)
```
* Zweck: WAL wird aufgeräumt, die Datei in einen sauberen Zustand versetzt (kein WAL-Replay beim nächsten Start).
* Aufruf über `execute_db_vacuum(db_path)`-Erweiterung in `db/db_utils.py` (führt `CHECKPOINT;` **gefolgt von** `VACUUM;` aus).
* Gilt für `analytics.duckdb` und `market_data.duckdb` (bei Bedarf auch `app_data.duckdb`).
* **Keine UI-Blockade:** App-Exit läuft, wenn keine Scans/Worker mehr aktiv sind (Referenzzähler `_sync_pause_count == 0`).

#### Stufe 2 – Kompaktierung (Variante A: `COPY FROM DATABASE`, DuckDB ≥ 0.9.0)
Für eine echte Verkleinerung (Bloat entfernen) wird die Datenbank in eine frische, minimale Datei übertragen:

```sql
-- 1. Neue, leere Datenbank-Datei anheften
ATTACH 'data/analytics_compacted.duckdb' AS new_db;

-- 2. Alle Daten/Schema/Indizes in die neue DB kopieren (lückenlose Datei)
--    WICHTIG: korrekte DuckDB-Syntax = COPY FROM DATABASE <src> TO <dst>
COPY FROM DATABASE analytics TO new_db;

-- 3. Neue DB wieder trennen
DETACH new_db;
```

* Danach wird im Dateisystem die alte `analytics.duckdb` durch die kompakte `analytics_compacted.duckdb` ersetzt (Löschen/Umbenennen).
* **Katalogname:** entspricht dem Datei-Basename ohne `.duckdb` (z. B. `analytics` für `analytics.duckdb`, `market_data` für `market_data.duckdb`). Bei Sonderzeichen (führender Unterstrich o. Ä.) ist der Katalogname in doppelte Anführungszeichen zu setzen: `COPY FROM DATABASE "_copy_src" TO new_db`.
* **Empirisch verifiziert** (headless, `test/check_copy_database.py`, nur Test-Dateien): Reduktion **85,4 %** gegen Bloat; Schema, Tabellen, Constraints und Daten werden **vollständig** übertragen (PASS).
* **Guard:** Kompaktierung nur bei `_sync_pause_count == 0` (keine laufenden Scans/Worker); sinnvoller Einstieg: der `[ 🧹 DB Service ]`-Button in `PropertiesWindow`.

#### Akzeptanzkriterien (angepasst an F2-Lösung)
1. `get_db_fragmentation_info()` liefert Prozent-, Bloat- und Größen-MB-Werte ohne Exception zurück.
2. `execute_db_vacuum()` (CHECKPOINT + VACUUM) schließt fehlerfrei ab und erzeugt eine konsistente Datei (kein WAL-Replay beim nächsten Öffnen).
3. `copy_database(src, dst)`-Helper (Kompaktierung): Kopie ist kleiner als die Bloat-Datei und enthält Schema + Daten vollständig (headless-Test wie `test/check_copy_database.py`).


