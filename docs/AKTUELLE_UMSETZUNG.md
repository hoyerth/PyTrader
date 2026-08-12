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

# 21.02 – Multi-TF Execution, Status Pill-Strip & DB Maintenance

## 🎯 1. Ziel & Fachliche Kern-Anforderungen

1. **Multi-TF Execution im Service Picker / Window:**
* Action-Button / Combo in Toolbar: `[ Aktueller TF ]` vs. `[ 🌐 Alle Timeframes (6 TFs) ]`.
* Klick führt den `HistoricalScanner` schrittweise über alle 6 Timeframes (`M1`, `M5`, `M15`, `H1`, `H4`, `D1`) aus.

2. **Kompaktes Status-Widget (`TfStatusBadgeBar` / Pill-Strip):**
* Extrem platzsparend ($170 \times 16\text{ px}$) in `ServiceWindow` / `MasterTree` sowie `AnalyticsWindow` eingebettet.
* Visuelle 6-TF Badges (`M1`–`D1`): Grau (`⚪` = No Data), Grün (`✅` = Berechnet/Rows vorhanden), Rot (`❌` = Fehler), Blau Blinken (`🔄` = Scan läuft).
* Detail-Tooltip beim Hover: Zeigt exakte Zeilenzahl und Datum/Uhrzeit der letzten Ausführung (`DD.MM.JJ HH:MM`).

3. **DB-Bloat & Maintenance (VACUUM):**
* Status-Ermittlung via `PRAGMA database_size` beim App-Start: Zeigt Fragmentierung auf `MainWindow` unter dem Optionen-Button an (z. B. `DB Status: 28% fragmentiert (85 MB frei)`).
* `[ 🧹 DB Service (VACUUM) ]`-Button im `PropertiesWindow` (`properties_win.py`).
* Concurrency-Guard: `VACUUM` ist gesperrt, solange Scans/Worker laufen (`_sync_pause_count > 0`).

---

## 🚀 2. Übersicht UI-Komponenten & Status-Logik

| Komponente | Ort / Trigger | Logik / Auswirkung |
| --- | --- | --- |
| **Pill-Strip Bar** | `ServiceWindow` / `MasterTree` / `AnalyticsWindow` | Zeigt $6$ Micro-Badges (`M1`..`D1`). Tooltip zeigt `count` + `last_run`. |
| **Multi-TF Run** | Toolbar `ServiceWindow` | Führt Batch-Run sequentiell für alle 6 TFs aus. Updates auf Badges via `scan_finished`. |
| **DB-Status Label** | `MainWindow` (unter Optionen-Button) | Zeigt Fragmentierung in % und Bloat in MB an (via `PRAGMA database_size`). |
| **DB Service Button** | `PropertiesWindow` | Führt `VACUUM;` auf `analytics.duckdb` & `market_data.duckdb` aus (sofern keine Scans laufen). |

---

## 🛠️ 3. Schritt-für-Schritt Umsetzungsanleitung für die IDE

### Schritt 1: DB-Utilities & Maintenance-Engine (`db/db_utils.py` & `analytics/engine/feature_store_reader.py`)

* **1.1 Bloat-Analysis & Vacuum-Funktion (`db/db_utils.py`):**

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


* **1.2 TF-Status-Query (`analytics/engine/feature_store_reader.py`):**
Implementiere `fetch_service_tf_status(plugin_id: str) -> Dict[str, dict]`:
Liefert `SELECT LOWER(timeframe), COUNT(*), MAX(created_at) FROM feature_store WHERE LOWER(TRIM(feature_id)) = LOWER(TRIM(?)) GROUP BY 1`.

### Schritt 2: Status-Pill-Strip Widget (`serviceui/common_widgets.py` / `master_tree.py`)

* **2.1 `TfStatusBadgeBar`-Widget erstellen:**
* Kompaktes `QWidget` ($170 \times 16\text{ px}$) mit 6 `QLabel`-Badges für `M1`, `M5`, `M15`, `H1`, `H4`, `D1`.
* Method `update_status(tf_map)`: Führt Color-Mapping durch (Grün `#1e4620`/`#26a69a` bei Daten; Grau `#2a2a2a` ohne Daten) und setzt `setToolTip()` mit `count` und `last_run`.

### Schritt 3: Multi-TF Ausführung (`serviceui/service_win.py`)

* **3.1 Toolbar-Combo & Execution Loop:**
* Füge ComboBox `combo_run_tf` ein (`[ Aktueller TF ]`, `[ 🌐 Alle Timeframes (6 TFs) ]`).
* Bei Auswahl *"Alle Timeframes"* führt der `ServiceRunWorker` / `HistoricalScanner` die Iteration über `["M1", "M5", "M15", "H1", "H4", "D1"]` durch.
* Nach jedem TF-Abschluss Signal zur Aktualisierung der `TfStatusBadgeBar` senden.

### Schritt 4: UI-Integration Main-Window & Properties-Window

* **4.1 `MainWindow` (`main.py`):**
* Beim Startup `get_db_fragmentation_info("data/analytics.duckdb")` aufrufen und `label_db_status` unter dem Optionen-Button befüllen (z. B. `DB Status: 18% fragmentiert`).

* **4.2 `PropertiesWindow` (`properties_win.py`):**
* Button `[ 🧹 DB Service (VACUUM) ]` einbauen.
* Guard-Prüfung: Falls `_sync_pause_count > 0`, Button sperren / Hinweis ausgeben.
* Führt `execute_db_vacuum()` für `analytics.duckdb` und `market_data.duckdb` aus und aktualisiert die Status-Anzeige.

---

## 📊 4. Akzeptanzkriterien für die Headless-Validierung (`test/test.py`)

1. **Bloat-Check-Test:** `get_db_fragmentation_info()` liefert gültige Prozent- und MB-Werte für bestehende `.duckdb`-Dateien.
2. **Vacuum-Execution-Test:** `execute_db_vacuum()` schließt ohne Exception ab und verringert/konsolidiert die Dateiblöcke.
3. **TF-Status-Test:** `fetch_service_tf_status()` gibt für existierende Plugins ein valides Dict mit `count` und `last_run` je Timeframe zurück.
4. **Badge-Widget-Test:** `TfStatusBadgeBar` aktualisiert Farben und Tooltips fehlerfrei bei Übergabe eines Status-Dicts.

