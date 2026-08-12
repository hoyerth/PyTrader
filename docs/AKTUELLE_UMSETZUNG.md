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
2. **DB-Pflege beim App-Exit:** `main.py` `closeEvent` führt für jede DB-Datei `CHECKPOINT;` **gefolgt von** `VACUUM;` aus (WAL-Flush, konsistenter Zustand – keine Datei-Verkleinerung).
3. **Kompaktierung (Button):** Button `[ 🧹 DB Service ]` in `PropertiesWindow` führt die **`COPY FROM DATABASE`-Kompaktierung** aus (echte Verkleinerung, Bloat entfernen). **Nicht** `VACUUM`-Button.
4. **Concurrency-Guard:** Kompaktierung sperren, solange `_sync_pause_count > 0` (laufende Scans/Worker) – Zugriff über **EventBus-Zähler** (konsistent zu Phase 16, nicht `self.parent()`).

---

## 🛠️ 2. Schritt-für-Schritt Umsetzungsanleitung

### Schritt 1: Core Engine (`db/db_utils.py`)

Füge folgende Funktionen in `db/db_utils.py` ein (**korrigierte Fassung, Stand 12.08.2026** – F1: `res[2]/res[4]`, F2: CHECKPOINT+VACUUM, `copy_database`-Helper):

# db/db_utils.py
import os
from pathlib import Path
from db.db_pool import DbPool

def get_db_fragmentation_info(db_path: str) -> dict:
    if not os.path.exists(db_path):
        return {"pct": 0, "bloat_mb": 0, "size_mb": 0}
    file_bytes = os.path.getsize(db_path)
    try:
        con = DbPool.get(db_path)
        res = con.execute("PRAGMA database_size;").fetchone()
        # Spalten: 0 database_name, 1 database_size, 2 block_size,
        #          3 total_blocks, 4 used_blocks, 5 free_blocks, ...
        block_size, used_blocks = (res[2], res[4]) if res else (262144, 0)
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
    """DB-Pflege beim App-Exit (Stufe 1): CHECKPOINT gefolgt von VACUUM.

    CHECKPOINT flusht die WAL in die Hauptdatei (konsistenter Zustand);
    VACUUM ist in DuckDB ohne Dateigrößen-Effekt (Kompaktierung siehe
    copy_database).
    """
    con = DbPool.get(db_path)
    con.execute("CHECKPOINT;")
    con.execute("VACUUM;")

def copy_database(src_db_path: str, dst_db_path: str) -> None:
    """Kompaktierung (Stufe 2): COPY FROM DATABASE in frische, minimale Datei.

    Katalogname der Quelle = Datei-Basename ohne .duckdb (ggf. gequotet).
    dst_db_path sollte ein absoluter Pfad sein (BASE_DIR-basiert).
    """
    con = DbPool.get(src_db_path)
    src_catalog = Path(src_db_path).stem  # z. B. 'analytics'
    con.execute(f"ATTACH '{dst_db_path}' AS new_db")
    con.execute(f'COPY FROM DATABASE "{src_catalog}" TO new_db')
    con.execute("DETACH new_db")

---

### Schritt 2: Startup Status (`main.py`)
Beim App-Start in `main.py` aufrufen und UI-Label unter Optionen-Button befüllen (absoluter Pfad via `BASE_DIR`):

# main.py
from db.db_utils import get_db_fragmentation_info

info = get_db_fragmentation_info(str(BASE_DIR / "data" / "analytics.duckdb"))
# UI-Label setzen (label_db_status – in ui/main_win.ui ergänzen oder per Code erzeugen)
self.label_db_status.setText(f"DB Status: {info['pct']}% fragmentiert ({info['bloat_mb']} MB frei)")

---

### Schritt 3: UI, Concurrency-Guard & Kompaktierung (`properties_win.py`)
Button `[ 🧹 DB Service ]` in `PropertiesWindow` für die **Kompaktierung** (COPY FROM DATABASE) einbauen. Guard über den **EventBus-Zähler** (konsistent zu Phase 16; NICHT `self.parent()`, da `PersistentWindow` kein Qt-Parent hat):

# properties_win.py
from pathlib import Path
from config.event_bus import event_bus
from db.db_utils import copy_database

BASE_DIR = Path(__file__).resolve().parent

def _on_btn_vacuum_clicked(self) -> None:
    # Concurrency-Guard über EventBus-Zähler (MainWindow aktualisiert ihn
    # in service_run_started/finished; Eigentum: Phase-16-Referenzzähler)
    if getattr(event_bus, "sync_pause_count", 0) > 0:
        print("⚠️ DB-Service gesperrt: Scans/Worker laufen aktuell.")
        return

    # Kompaktierung analytics + market_data (absolute Pfade, BASE_DIR)
    copy_database(str(BASE_DIR / "data" / "analytics.duckdb"),
                  str(BASE_DIR / "data" / "analytics_compacted.duckdb"))
    copy_database(str(BASE_DIR / "data" / "market_data.duckdb"),
                  str(BASE_DIR / "data" / "market_data_compacted.duckdb"))
    # Datei-Ersatz NUR bei geschlossenen DbPool-Verbindungen (Windows File-Lock!)
    # → Verbindungen schliessen/neu öffnen (DbPool-Methode), alte Datei löschen,
    #   kompakte Datei umbenennen, DB erneut öffnen.
    print("✅ DB-Kompaktierung erfolgreich ausgeführt.")

---

## 📊 3. Akzeptanzkriterien (`test/test.py`)
1. `get_db_fragmentation_info()` liefert Prozent-, Bloat- und Größen-MB-Werte ohne Exception zurück.
2. `execute_db_vacuum()` (CHECKPOINT + VACUUM) schließt fehlerfrei ab und erzeugt eine konsistente Datei (kein WAL-Replay beim nächsten Öffnen).
3. `copy_database(src, dst)`-Helper (Kompaktierung): Kopie ist kleiner als die Bloat-Datei und enthält Schema + Daten vollständig (headless-Test wie `test/check_copy_database.py`).

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
- `db/db_utils.py`: `import os` (für `get_db_fragmentation_info`) und `from pathlib import Path` (für `copy_database`) im Snippet ergänzt; `DbPool`-Import ist innerhalb des `db`-Pakets zulässig (Basis-Schicht E4 bleibt sonst ohne Projekt-Import).
- ✅ **Markdown-Artefakte `[cite: 1]` im Kapitel bereinigt** (12.08.2026, Abschnitte 2/3).
- ✅ **Umsetzungsplan nachgezogen** (12.08.2026): Schritt 1–3 + AK entsprechen jetzt der F2-Lösung (CHECKPOINT+VACUUM, COPY FROM DATABASE, EventBus-Guard, `res[2]/res[4]`).
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
-- 1. Neue, leere Datenbank-Datei anheften (absoluter Pfad, BASE_DIR-basiert!)
ATTACH 'C:/Pfad/zum/Projekt/data/analytics_compacted.duckdb' AS new_db;

-- 2. Alle Daten/Schema/Indizes in die neue DB kopieren (lückenlose Datei)
--    WICHTIG: korrekte DuckDB-Syntax = COPY FROM DATABASE <src> TO <dst>
COPY FROM DATABASE analytics TO new_db;

-- 3. Neue DB wieder trennen
DETACH new_db;
```

* Danach wird im Dateisystem die alte `analytics.duckdb` durch die kompakte `analytics_compacted.duckdb` ersetzt (Löschen/Umbenennen).
* **Katalogname:** entspricht dem Datei-Basename ohne `.duckdb` (z. B. `analytics` für `analytics.duckdb`, `market_data` für `market_data.duckdb`). Bei Sonderzeichen (führender Unterstrich o. Ä.) ist der Katalogname in doppelte Anführungszeichen zu setzen: `COPY FROM DATABASE "_copy_src" TO new_db`.
* **⚠️ Windows File-Locking:** Der Datei-Ersatz (alte Datei löschen/umbenennen) funktioniert **nur**, wenn **alle offenen DbPool-Verbindungen** zu dieser DB geschlossen sind – sonst wirft Windows `PermissionError` (Datei in Verwendung). Ablauf: (1) `copy_database()` ausführen, (2) **DbPool-Verbindung schliessen/leeren** (Methode in `db/db_pool.py`), (3) alte Datei löschen, (4) kompakte Datei umbenennen, (5) DB neu öffnen. Kein laufender Scan/Worker darf zugreifen (Guard `_sync_pause_count == 0`).
* **⚠️ Absoluter Pfad:** `ATTACH`/`copy_database` immer mit **absolutem Pfad** (`BASE_DIR / "data" / ...`) aufrufen – relative Pfade hängen vom CWD ab (Desktop-Start vs. IDE unterscheidet sich).
* **Empirisch verifiziert** (headless, `test/check_copy_database.py`, nur Test-Dateien): Reduktion **85,4 %** gegen Bloat (Testfall mit vollständig gelöschten Daten); Schema, Tabellen, Constraints und Daten werden **vollständig** übertragen (PASS). Die reale Reduktion hängt vom tatsächlichen Bloat ab.
* **Guard:** Kompaktierung nur bei `_sync_pause_count == 0` (keine laufenden Scans/Worker); sinnvoller Einstieg: der `[ 🧹 DB Service ]`-Button in `PropertiesWindow` (nur Kompaktierung; App-Exit macht CHECKPOINT+VACUUM).

#### Akzeptanzkriterien (angepasst an F2-Lösung)
1. `get_db_fragmentation_info()` liefert Prozent-, Bloat- und Größen-MB-Werte ohne Exception zurück.
2. `execute_db_vacuum()` (CHECKPOINT + VACUUM) schließt fehlerfrei ab und erzeugt eine konsistente Datei (kein WAL-Replay beim nächsten Öffnen).
3. `copy_database(src, dst)`-Helper (Kompaktierung): Kopie ist kleiner als die Bloat-Datei und enthält Schema + Daten vollständig (headless-Test wie `test/check_copy_database.py`).




---

# 21.03 - Bugfix-Runde 12.08.2026 (Service-UI & Heatmap)

> Implementierungs-Log (Commit `271a81b`, 12.08.2026): 5 neue User-Meldungen
> aus dem Bugfixing-Modus (Fortschrittsbalken, Data-Only-Loeschen,
> Heatmap-Legende, Overlay-Balken) + Crash `srv_trend_hma_pivot`.
> Verifikation headless (keine UI): `test/check_hma_pivot_bug.py`,
> `test/check_purge_legacy.py` (5/5), `test/check_heatmap_format.py`,
> `test/check_overlay_tf_precedence.py` - alle PASS.

## ?? 1. Punkt 0 - `srv_trend_hma_pivot` LiveAnalyzer-Crash (Broadcast-Fehler)

**Meldung:** `ValueError: could not broadcast input array from shape (4,) into shape (0,)`
bei `SILVER/M1` im LiveAnalyzer (`df_short = df_plugin.tail(2)` -> 1-2 Bars).

**Ursache:** `chart/indicators/utils/ma_template.py`: `_sma_values`, `_wma_values`,
`_alma_values`, `_vwma_values` nutzen `np.convolve(..., "valid")` + Zuweisung
`result[period-1:] = conv`. Ist die Serie kuerzer als `period`, liefert convolve
ein Array der Laenge `period-n+1` (z. B. 4), waehrend `result[period-1:]` leer
ist -> Broadcast-Fehler.

**Fix:** Guard `if len(values) < period: return np.full(len(values), np.nan)`
in allen 4 Funktionen (Warmup-Vertrag: kurze Serien = NaN, kein Crash).

**Verifikation:** `py_compile` OK; `test/check_hma_pivot_bug.py` - n=2/3/4/5/10
OK; alle 12 MA-Typen mit n=2 OK; EHMA n=100 finite ab Index 9.

## ?? 2. Punkt 1 - "Data only loeschen" loeschte ALLE Varianten

**Meldung:** "Data only loeschen" entfernte die Daten ALLER Varianten
(DB-Befund: `srv_swing_volume_profile` mit 3 Presets; UI-Varianten-Hashes
69141755/8c21542a/7341c563, Legacy-Pools 4eec2b02/7d636c36/074ec5bb).

**Ursache:** `purge_instance_data` (feature_builder.py) loeschte IMMER auch den
Params-only-Legacy-Pool (`generate_instance_hash(plugin_id, params)` ohne
preset_name). Teilen sich Varianten denselben Params-only-Hash (identische
Params), gehoert der Pool ALLEN - der Purge einer einzelnen Variante entfernte
damit die Daten der uebrigen.

**Fix (Runde 6):**
1. `feature_builder.py`: Signatur `purge_instance_data(..., purge_legacy=False)`.
   Legacy-Purge laeuft NUR noch auf explizite Anforderung.
2. `service_win.py` + `service_selector_dialog.py`: neuer Helper
   `_purge_legacy_allowed(plugin_id, params)` - zaehlt aktive Varianten
   (Presets + Set-Instanzen) mit identischem Params-only-Hash. `owners == 1`
   => Pool eindeutig => Legacy-Purge erlaubt; `owners > 1` => Pool geteilt
   => bleibt unangetastet.

**Teil 2 ("M1 wird immer noch angezeigt"):** Die Badge-Bar liest
`fetch_service_tf_status` (feature_store_reader.py:1327) nach `feature_id`
(SERVICE-weit, nicht varianten-scoped). Nach Purge einer Variante verbleiben
die M1-Rows der uebrigen Varianten -> M1-Pill bleibt korrekt sichtbar. Erst
wenn ALLE Varianten gepurged sind (jede mit eindeutigem Legacy-Pool), loescht
sich M1. **Verifiziert** (test/_tmp_verify_badge.py, read-only): erwartetes
Verhalten.

**Verifikation:** `test/check_purge_legacy.py` (5/5): Default-False schuetzt
geteilte Pools, purge_legacy=True loescht eindeutige Pools, Altsignatur
kompatibel.

## ?? 3. Punkt 2 - Fortschrittsbalken fehlt

**2a ("nicht bei alle services ausfuehren"):** `ServiceSelectorDialog` (Picker)
verband KEIN `service_progress`-Signal und hatte keinen QProgressBar.

**Fix:** Progress-Zeile (progress_label + QProgressBar, Muster service_win)
unter der badge_bar im Panel-Layout; `service_progress`-Verbindung im
`_start_run_worker`; neue Slots `_on_service_progress` / `_reset_run_progress`;
Reset bei Start/Ende/Fehler (finished + failed).

**2b ("nicht loeschen"):** Nach 'Data Only Loeschen' / Voll-Loeschung blieb ein
veralteter Balkenzustand stehen.

**Fix:** `_reset_run_progress()` in service_win nach erfolgreichem Purge
(`_on_data_only_purge`, `_delete_complete_set_instance`, `_delete_complete_preset`).

## ?? 4. Punkt 3 - Heatmap-Legende auf 2 Nachkommastellen begrenzen

**Fix:** `_format_heatmap_value` (heatmap_widget.py): Bruchwerte mit
`f"{fval:.2f}"` statt `f"{fval:.6f}"` (gerundet, Nullen gestrippt).
Ganzzahlen unveraendert (deutsche Tausender-Trennung '4.380').

**Verifikation:** `test/check_heatmap_format.py` - 62.5567 -> '62.56',
0.005 -> '0.01', 4380 -> '4.380', Nicht-Numerisch unveraendert (ALL PASS).

## ?? 5. Punkt 4 - Anzeigebalken ca. 18 Stunden breit (Swing Momentum AVG)

**Befund (empirisch):** Die "18h-Balken" sind die Candle-Overlay-Koerper im
D1-Timeframe: `bar_sec * 0.7` = 86400 * 0.7 = 60480s = **16,8h** (~70 % der
Tages-Spalte). `_bar_interval_seconds` las den TF nur aus
`params["timeframe"]` - ohne sichtbare Anzeige, welcher TF die Breite
bestimmt.

**Fix:**
1. `_bar_interval_seconds(data_tf)` bevorzugt den **Daten-TF des OHLCV-
   Payloads** (Kerzenbreite folgt der Datenbasis, Race-/Divergenz-sicher).
2. Neues Label `_label_overlay_tf` in der Steuerzeile zeigt den Overlay-TF
   live an (z. B. 'Overlay: D1' / 'Overlay: H1') - beantwortet "welcher TF
   wird angelegt / wo sehen".

**Verifikation:** `test/check_overlay_tf_precedence.py` - data_tf hat Vorrang
(D1->86400, M1->60), Fallback 3600s, D1-Koerper 16,80h (ALL PASS).

## ?? 6. Geaenderte Dateien (Commit `271a81b`)

| Datei | Aenderung |
|---|---|
| `chart/indicators/utils/ma_template.py` | 4x Warmup-Guard (Serie < period -> NaN) |
| `analytics/features/feature_builder.py` | `purge_instance_data(..., purge_legacy=False)` |
| `serviceui/service_win.py` | `_purge_legacy_allowed` + purge_legacy + Progress-Reset |
| `serviceui/service_selector_dialog.py` | `_purge_legacy_allowed` + Progress-Bar + Reset |
| `analytics/ui/heatmap_widget.py` | `_format_heatmap_value` (2 NK), `_bar_interval_seconds(data_tf)`, Overlay-TF-Label |
| `test/` | `check_hma_pivot_bug.py`, `check_purge_legacy.py`, `check_heatmap_format.py`, `check_overlay_tf_precedence.py` |

**Nicht angefasst:** 21.02-Working-Tree-Dateien (`db/db_utils.py`, `db/db_pool.py`,
`config/event_bus.py`, `main.py`, `properties_win.py`, `ui/main_win.ui`).

---

# 21.04 - Bugfix-Runde 12.08.2026 (Fortschrittsbalken & TF-Badges)

> Implementierungs-Log (Commit `ef81fb0`, 12.08.2026): 2 neue User-Meldungen
> aus dem Bugfixing-Modus (Folge-Runde zu 21.03):
>   1) "Fortschrittsbalken laeuft dauerhaft -> Fehler?"
>   2) "Data only loeschen: nur in einer Variante alles geloescht (Datum nie),
>      aber alle TF wird immer noch angezeigt; Fehler bei Kopie 99 (swing volume)"
> Verifikation headless (keine UI): `py_compile` (3 Dateien),
> `test/check_2101b.py` (18/18 PASS), read-only-DB-Check gegen die reale
> `analytics.duckdb` (Varianten-Hashes von `srv_swing_volume_profile`).

## ?? 1. Punkt 1 - Fortschrittsbalken laeuft dauerhaft

**Meldung:** Der Fortschrittsbalken unter dem MasterTree laeuft dauerhaft
(kein Fehler, aber endlose Animation).

**Ursache:** `QProgressBar.setMaximum(0)` startet eine **indeterminate
Busy-Animation**, die nie endet. In `service_win.py` (Init Zeile ~255) und
`service_selector_dialog.py` (Init Zeile ~453) sowie nach jedem
`_reset_run_progress()` (`bar.setMaximum(0)`) wurde damit eine Endlos-Animation
angestossen - unabhaengig von laufenden Service-Runs.

**Fix (beide Dateien):**
1. **Init:** `setMaximum(0)` ersetzt durch `setRange(0, 1)` + `setValue(0)`
   (determinate leere Range statt Busy-Loop).
2. **`_reset_run_progress()`:** `setMaximum(0)` ersetzt durch
   `setRange(0, 1)` + `setValue(0)`.
3. `_on_service_progress` setzt beim Run weiterhin die echte Range
   (`setMaximum(max(total, 1))`) - unveraendert.

Damit ist der Balken ausserhalb von Runs ruhig (leer) und zeigt nur waehrend
eines echten Service-Runs Fortschritt an.

**Verifikation:** `py_compile` OK; keine `setMaximum(0)`-Aufrufe mehr im Code
(nur Kommentar-Hinweise in den neuen Kommentaren).

## ?? 2. Punkt 2 - "Data only loeschen": TF-Pills bleiben sichtbar

**Meldung:** Nach "Data only loeschen" einer Variante (Kopie 99 von
`srv_swing_volume_profile`) wurde das Datum korrekt auf "nie" gesetzt
(Purge OK), aber ALLE TF-Pills werden weiterhin angezeigt.

**Befund (DB, read-only):** Der Pill-Strip wurde SERVICE-weit geladen:
`fetch_service_tf_status` (feature_store_reader.py:1327) gruppierte nur nach
`feature_id`, NICHT nach `instance_hash`. Die Variante 8c21542a (Kopie 99)
war nach dem Purge aus der DB entfernt, aber die uebrigen Varianten
(69141755 "Default (Kopie)", 7341c563 "srv_swing 34566") besassen weiterhin
je ~100k Rows pro TF -> die Pills blieben korrekt (aber verwirrend) sichtbar.
Antwort auf die User-Frage: Die TFs wurden bisher NICHT je Variante einzeln
angezeigt.

**Fix (Varianten-Scope):**
1. `feature_store_reader.py`: `fetch_service_tf_status(plugin_id,
   instance_hash=None)` - optionaler Hash filtert die Rows exakt auf GENAU
   diese Variante (`AND LOWER(TRIM(instance_hash)) = LOWER(TRIM(?))`).
   Ohne Hash bleibt das service-weite Verhalten erhalten (Alt-Caller
   kompatibel: `analytics_win.py`, `check_2101b.py`).
2. `service_win.py` + `service_selector_dialog.py`: `_resolve_badge_plugin`
   umbenannt zu `_resolve_badge_scope` (liefert Tuple
   `(plugin_id, instance_hash)`):
   * Clone-Knoten: instance_hash aus dem `service_id`-Slot
     (MasterTree._emit_selection_details, 20.04 Q7).
   * Set-/Service-Zeilen: `cfg['instance_hash']` aus der Set-Definition,
     sonst `generate_instance_hash(plugin_id, params)` (Params-only).
   * Plugin/Standalone: Hash = None (service-weit, wie bisher).
3. `_refresh_badge_bar(plugin_id, instance_hash=None)` merkt sich den Hash
   (`_badge_instance_hash`) und uebergibt ihn an den Reader.

**Effekt:** Nach "Data only loeschen" einer Variante verschwinden ihre TF-Pills
sofort; die Pills der uebrigen Varianten zeigen nur noch deren eigene Daten.

**Verifikation (read-only, reale DB):**
* `fetch_service_tf_status(PID)` -> 9 TFs (D1..M5), Summe = alle Varianten.
* `fetch_service_tf_status(PID, "69141755")` -> 9 TFs, Summe < service-weit
  (nur eigene ~100k/TF).
* `fetch_service_tf_status(PID, "8c21542a")` -> **{}** (purged, korrekt leer).
* `fetch_service_tf_status(PID, "does_not_exist")` -> {} ; leere Parameter -> {}.
* `test/check_2101b.py` -> 18/18 PASS (Alt-Signatur kompatibel).

## ?? 3. Geaenderte Dateien (Commit `ef81fb0`)

| Datei | Aenderung |
|---|---|
| `analytics/engine/feature_store_reader.py` | `fetch_service_tf_status(plugin_id, instance_hash=None)` - Varianten-Filter |
| `serviceui/service_win.py` | Progress-Bar determinate (Init + Reset); `_resolve_badge_scope` + `_refresh_badge_bar(pid, hash)` |
| `serviceui/service_selector_dialog.py` | Progress-Bar determinate (Init + Reset); `_resolve_badge_scope` + `_refresh_badge_bar(pid, hash)` |

**Nicht angefasst:** 21.02-Working-Tree-Dateien (`db/db_utils.py`, `db/db_pool.py`,
`config/event_bus.py`, `main.py`, `properties_win.py`, `ui/main_win.ui`).
