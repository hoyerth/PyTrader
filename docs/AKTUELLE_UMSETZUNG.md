# Phase 19: Analytics-Finalisierung

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 19)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase19_step1`, `phase19_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Codebase-Formatierung:** Exakt **4 Leerzeichen** Einrückung (PEP8-Standard) und **exakt 1 Leerzeile** Spacing zwischen Methoden und Funktionsblöcken. Kein Umformatieren unbeteiligter Altbestand-Dateien.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`. `MasterTree`-Selektionen übergeben aufgelöste `feature_ids` direkt an `view_model.set_feature_ids()`.
5. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`db/db_pool.py`) – eine Verbindung pro Thread und DB-Datei. Die Fassade `db_service.py` bleibt als Re-Export-Wrapper für bestehende Caller erhalten.
7. **Tree-Persistenz & Kollisionsschutz (18.01.03):** 
   - Standalone-Service-Parameter nutzen exklusiv `plugin_params_<id>`.
   - Ordner-Kategorie-Overrides für Plugins nutzen exklusiv `plugin_category_<id>`.
   - Ordner-Kategorien für Service-Sets werden additiv im `category`-Feld der `ServiceSetDefinition` / des `save_set()`-Payloads persistiert.
8. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
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

# 19.01 Analytics UI: Status-Feedback, Empty-State & Multi-Service Table Handling

### 1. Architektur & Datenfluss

[AnalyticsWindow] ──(ViewModel `data_ready`)──► Status-Check (total == 0?)
        │
        ├── Ist Total == 0 ──► label_status_msg: "⚠️ Keine Daten vorhanden"
        │                      Pages -> clear_data() / Empty State
        │
        └── Multi-Select   ──► TablePage: Spalte 1 = "Service" (feature_id/display_name)
                               + Chronologische Sortierung + JSON-Union-Key-Spalten

---

### 2. Betroffene Dateien

* `analytics/ui/analytics_win.py`: Status-Message (`label_status_msg`) hinter Limit-Feld einbauen, Auswertung von `data_ready(kind, data)`.
* `analytics/ui/table_page.py`: Multi-Service-Darstellung anpassen (Spalte 1 = Service, dynamische JSON-Spalten-Union, chronologische Sortierung).
* `analytics/engine/analytics_view_model.py`: Bereitstellung typisierter Datenströme bei Einzel- und Multi-`feature_ids`.

---

### 3. Schritt-für-Schritt Anleitung (IDE-AI)

#### Step 1: Status-Message im Filterbereich (`analytics_win.py`)

* [x] Platziere ein `QLabel` (`label_status_msg`) direkt neben/hinter dem Limit-Input-Feld (`spin_limit`).
* [x] Verbinde den Event-Handler für `view_model.data_ready(kind, data)`:
* Falls `data.get("total", 0) == 0`:
* Setze `label_status_msg.setText("⚠️ Keine Daten vorhanden")` (Farbton: dezent gelb/orange).
* Blende leere Zustände auf den Unterseiten (`table_page`, `heatmap_page`, `scatter_page`, `distribution_page`) sauber aus/zurück.

* Falls `data.get("total", 0) > 0`:
* Setze `label_status_msg.setText(f"✅ {total} Einträge")` oder leere den Text.

#### Step 2: Multi-Service Spaltenaufbereitung (`table_page.py`)

* [x] Erweitere das Layout der `TablePage`:
1. Füge als **Spalte 1** das Feld **`Service`** ein (Anzeige der `feature_id` bzw. des via `service_selector_model.resolve_display_names()` aufgelösten Namens).
2. Standard-Spaltenreihenfolge festlegen: `[Zeitstempel, Service, ema_diff, rsi_14, atr_normalized, ...]`.
3. Bei Zusatzfeldern aus `feature_data`: Bilde die Union aller JSON-Keys über die geladenen Rows; fülle fehlende Werte bei abweichenden Services mit `"-"`.
4. Erzwinge eine chronologisch absteigende Sortierung nach `bar_time`, damit Signale verschiedener Services zeitlich korrekt gemischt dargestellt werden.

#### Step 3: Quality Gate & Verifikation

* [x] Syntax-Check via Terminal ausführen:
`python -m py_compile analytics/ui/analytics_win.py analytics/ui/table_page.py analytics/engine/analytics_view_model.py`

* [x] Headless-Test in `test/test.py` für `AnalyticsViewModel`-Abfragen ausführen:
* Testfall A: Abfrage für ungescannte Symbole/Services liefert `total == 0`.
* Testfall B: Multi-`feature_ids`-Abfrage liefert gemischte Ergebnissätze.

---

## Prüfprotokoll 19.01 (08.08.2026 15:46) – Konsistenz, Vollständigkeit & Entscheidungen

### Konsistenz-Prüfung

* **Inhalte deckungsgleich:** Das Kapitel 19.01 in `docs/AKTUELLE_UMSETZUNG.md` ist
  **identisch** mit der uncommitteten Ergänzung in `docs/Current/x_Roadmap_Phase19.md`
  (Architektur, betroffene Dateien, Steps 1–3). Keine Widersprüche, kein Doku-Drift.
* **Datenverträge passen zum Ist-Code:** Alle im Kapitel referenzierten Verträge existieren
  bereits in der Codebase:
  * `AnalyticsRepository.get_table()` liefert `{"rows": [...], "total": len(rows)}` →
    Datenbasis für den `total == 0`-Status-Check ist vorhanden.
  * `FeatureStoreReader.fetch_rows()` liefert pro Row `time`, `symbol`, `timeframe`,
    `feature_id`, `plugin_version`, `ema_diff/rsi_14/atr_normalized` und geparstes
    `feature_data` (inkl. `schema_version`-Default) → JSON-Union-Spalten sind möglich.
  * `ServiceSelectorModel.resolve_display_names(ids)` existiert und wird bereits im
    AnalyticsWindow (Button-Text-Sync, Zeile 390) genutzt.
  * Multi-Select ist vollständig verdrahtet: `AnalyticsViewModel.set_feature_ids()`
    → `WHERE feature_id IN (...)` im Reader; `ServiceSelectorDialog` + Button-Sync aktiv.

### Vollständigkeit (Ist-Zustand vs. Kapitel)

| Step | Anforderung | Ist-Zustand |
|---|---|---|
| 1 | `QLabel label_status_msg` hinter `spin_limit`/`edit_limit` | **OFFEN** – kein `label_status_msg` in `analytics_win.py` |
| 1 | `data_ready(kind, data)`-Handler im AnalyticsWindow | **OFFEN** – nur Pages verbinden sich via `attach_view_model` |
| 1 | Status-Text `⚠️ Keine Daten vorhanden` / `✅ {n} Einträge` | **OFFEN** – nicht implementiert |
| 1 | Leere Zustände auf den Unterseiten sauber aus-/einblenden | **VORHANDEN** – Overlay-Stack in `table_page`, `heatmap_page`, `scatter_page`, `distribution_page` blendet bei leeren Daten bereits auf Empty-Index um |
| 2 | Spalte 1 = `Service` (feature_id/display_name) | **OFFEN** – fixe Spalten `[Zeit, Symbol, TF, Feature, Version, ema_diff, rsi_14, atr_normalized]` |
| 2 | Standard-Reihenfolge `[Zeitstempel, Service, ema_diff, ...]` | **OFFEN** |
| 2 | JSON-Union aller `feature_data`-Keys, Fehlwerte `"-"` | **OFFEN** – `feature_data` wird nicht dargestellt |
| 2 | Chronologisch absteigende Sortierung nach `bar_time` | **OFFEN** – Reader liefert ASC (`ORDER BY bar_time ASC`), Page nutzt ungezwungene QTableWidget-Sortierung |
| 3 | `py_compile` der 3 Dateien | **OFFEN** – nicht gelaufen (keine Änderung) |
| 3 | Headless-Tests A (total==0) & B (Multi-Mix) in `test/test.py` | **OFFEN** – keine 19.01-Testfälle vorhanden |

### Befunde (Lücken)

* **L1 – Status-Message fehlt komplett:** `analytics_win.py` besitzt weder
  `label_status_msg` noch einen `data_ready`-Handler; der Status-Check (Step 1) ist
  vollständig offen. Der Window-taugliche Anschluss ist `_wire_view_model()` /
  Filter-Zeile (`filt.addWidget(self.edit_limit)`).
* **L2 – Multi-Service-Darstellung fehlt:** `table_page.py` ist auf die fixen
  Alt-Spalten eingestellt; `feature_data` (JSON) wird verworfen. Step 2 ist offen.
* **L3 – Qualitäts-Gate fehlt:** Keine 19.01-spezifischen Tests in `test/test.py`
  (Testfall A/B); `py_compile` nicht ausgeführt (folgt mit der Umsetzung).
* **L4 – Sortier-Kontrakt:** `fetch_rows()` liefert deterministisch `ASC`
  (bestehender Reader-Vertrag, von bestehenden Tests/Callern genutzt). Die
  absteigend-chronologische Darstellung darf den Reader NICHT ändern – sie muss in
  der Page (Rendering) erfolgen.
* **L5 – `total`-Semantik (Limit-Cap):** `get_table()["total"]` ist `len(rows)`
  **nach** `LIMIT`, nicht die Gesamttrefferzahl. Testfall A (ungescannt → 0) ist
  davon unberührt, der Text bei `total > 0` ist aber als „angezeigte Einträge" zu
  verstehen (ggf. Formulierung „✅ {n} Einträge" mit Platzhalter für die Anzeige-Limit).

### Entscheidungen (19.01)

1. **E1 – Status-Message nutzt bestehenden `total`-Vertrag:** `label_status_msg`
   zeigt `data["total"]` aus `QUERY_TABLE` (LIMIT-gekappte Zeilenzahl). Text:
   `total == 0` → `"⚠️ Keine Daten vorhanden"` (dezent orange, z. B. `#b7950b`),
   `total > 0` → `"✅ {total} Einträge"`. **Kein** zusätzlicher COUNT-Query
   (bleibt lesend/leichtgewichtig, MVVM-Invariante 4).
2. **E2 – Sortierung in der Page, nicht im Reader:** `TablePage._populate()`
   sortiert die erhaltenen Rows nach `bar_time` **absteigend** (deterministisch,
   stabil) und zeichnet in dieser Reihenfolge; die QTableWidget-Interaktions-
   sortierung bleibt deaktiviert (`setSortingEnabled(False)`), damit die
   Service-Mischung chronologisch korrekt bleibt. `FeatureStoreReader` unverändert
   (L4-Fix).
3. **E3 – Service-Namensauflösung IoC-konform:** Die `TablePage` erhält eine
   injizierte `name_resolver: Callable[[List[str]], List[str]]` (Default: `feature_id`
   selbst). Das `AnalyticsWindow` verknüpft sie in `_wire_view_model()` mit
   `self._selector_model.resolve_display_names` → kein SQL und keine direkte
   Modell-Kopplung in der Page (Invariante 4 / Open-Closed).
4. **E4 – JSON-Union ohne Kollision:** Union aller `feature_data`-Keys über die
   geladenen Rows; fehlende Werte → `"-"`. Keys, die mit nativen Spalten
   (`ema_diff`, `rsi_14`, `atr_normalized`) oder Pflichtspalten kollidieren, werden
   ignoriert (defensiv, keine Duplikat-Header). Spaltenreihenfolge:
   `[Zeit, Service, native Spalten..., Union-Keys alphabetisch]`.
5. **E5 – Status/Empty-State-Verschmelzung:** Die vorbestehenden Overlay-Empty-
   States der Pages bleiben unangetastet (bereits erfüllt); der neue
   `label_status_msg` ist eine **ergänzende** Kopfzeilen-Info und ersetzt keinen
   Page-Zustand.

### Status

* **Umsetzung abgeschlossen (08.08.2026, Implementierungs-Log unten).**

---

## Implementierungs-Log 19.01 (08.08.2026 16:35) – Status-Feedback, Empty-State & Multi-Service Table

Umgesetzt (alle Checklisten-Punkte des Kapitels abgearbeitet; Entscheidungen E1–E5
des Prüfprotokolls 19.01 als verbindliche Spezifikation):

### Step 1 – Status-Message im Filterbereich (`analytics/engine/analytics_win.py`)

* `label_status_msg` (QLabel, dezent orange `#b7950b`, fett) direkt hinter dem
  Limit-Feld (`edit_limit`) in der Filter-Zeile eingebaut.
* `_on_data_ready(kind, data)`-Handler verbunden (`vm.data_ready` in
  `_wire_view_model`): wertet ausschließlich `QUERY_TABLE` aus (E1, kein
  zusätzlicher COUNT-Query). `total == 0` → `"⚠️ Keine Daten vorhanden"`,
  `total > 0` → `"✅ {n} Einträge"` (LIMIT-gekappte Zeilenzahl, L5).
* Empty-States der Unterseiten (Overlay-Stacks) waren bereits vorhanden (E5) –
  unverändert gelassen.

### Step 2 – Multi-Service Spaltenaufbereitung (`analytics/ui/table_page.py`)

* **Spalte 1 = Service** (E3): Injizierbarer `name_resolver` (Default = feature_id
  selbst); das AnalyticsWindow verknüpft `ServiceSelectorModel.resolve_display_names`
  IoC-konform (kein SQL, keine Modell-Kopplung in der Page).
* Standard-Spaltenreihenfolge `[Zeit (Wanduhr), Service, ema_diff, rsi_14,
  atr_normalized, ...JSON-Union-Keys alphabetisch]`; dynamischer Spaltenaufbau
  pro Abfrage.
* **JSON-Union** (E4): Vereinigung aller `feature_data`-Keys über die geladenen
  Rows; Kollisionen mit Basis-/nativen Spalten ignoriert; fehlende Werte → `"-"`.
* **Chronologisch ABSTEIGEND** (E2): `_populate()` sortiert die Rows deterministisch
  (stabil) nach `bar_time`; `setSortingEnabled(False)` bleibt dauerhaft deaktiviert
  (Service-Mischung korrekt, kein O(n^2)-Interaktions-Sort). `FeatureStoreReader`
  unverändert (ASC-Vertrag, L4).
* `_on_double_clicked` (Jump-to-Chart) liest Symbol/TF/Zeit jetzt aus der Roh-Row
  (`_current_rows`) statt aus festen Spaltenpositionen (dynamische Spalten).

### Step 3 – Quality Gate & Verifikation (headless, kein UI)

* `python -m py_compile analytics/ui/analytics_win.py analytics/ui/table_page.py
  analytics/engine/analytics_view_model.py` → **PASS** (exit 0).
* `test/test.py` (Teil 31, neu): 11 Prüfungen **PASS** –
  * Testfall A (`31 A1`): ungescanntes Symbol → `total == 0`.
  * Testfall B (`31 B1–B3`): Multi-`feature_ids` → 4 gemischte Rows
    (`srv_a`+`srv_b`), Einzel-Filter `srv_a` → nur 2 srv_a-Rows.
  * TablePage (`31 C1–C5`): absteigende Sortierung, Spalte-1-Anzeigename,
    JSON-Union-Spalten (`grid_step`, `lookback`, `schema_version`),
    Fehlwert `"-"` bei abweichendem Service.
* Gesamtlauf `test/test.py`: **559 PASS / 6 FAIL** – die 6 Fehler sind die
  dokumentierten **Baseline-Vorbefunde** P2/P5/H3/H4/H5/H7 (Geometrie-Tests,
  offscreen `800x582`, Reflow-/Scrollbar-Umbau 07./08.08.2026) – nicht durch
  19.01 verursacht, ohne 19.01-Änderungen identisch.
* Test-Workspace aufgeräumt (Invariante 10): nur `test/test.py` verbleibt.

### Abweichungen vom Plan-Kapitel (per Prüfprotokoll-Entscheidungen)

* Plan-Punkt „Spalte 1 = `feature_id`/`display_name`" → E3: injizierter
  `name_resolver` statt direkter Modell-Referenz.
* Plan-Punkt „chronologisch absteigende Sortierung" → E2: Sortierung in der Page
  (Reader-Sortierung bleibt ASC, L4).
* Plan-Punkt „Farbton dezent gelb/orange" → E1: `#b7950b` (QSS auf
  `label_status_msg`).

### Status

* **Alle Steps 1–3 abgeschlossen und headless verifiziert.** Keine UI-/Regressionstests
  ausgeführt (Regel 4); Baseline-Vorbefunde P2/P5/H3/H4/H5/H7 sind dokumentiert.

