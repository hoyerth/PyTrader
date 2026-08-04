# Konzept Phase 15: Service UI und Analytics (Vorbereitung auf finale Roadmap)

> **Status (04.08.2026):** Dieses Dokument ist die **Vorbereitung** auf die finale
> Phase-15-Roadmap. Die Empfehlungen 1–4 aus `docs/Bericht_Phase15_Rumpf_Check.md`
> sind eingearbeitet; die Entfernung des Alt-Grid-Indikators (`chart/indicators/grid.py`)
> ist berücksichtigt. Die resultierende Umsetzungsliste (Abschnitt 4) ist die Basis
> für die finale Kapitelstruktur (15.x).

## 1. Übersicht & Zielsetzung

Ziel von **Phase 15** ist die Weiterentwicklung der **Service-UI** (`service_win.py`)
und des **gesamten Analytics-Moduls** (`analytics/`) auf Basis der etablierten
Plugin-/Service-Architektur (Phasen 12–14). Abgeleitete Modul-Struktur:

* **15.1 Service-UI:** Modularisierung der gewachsenen `service_win.py` (≈ 1.400
  Zeilen) und Bedien-Feinschliff. Bestehende Funktionen bleiben erhalten
  (Set-Editor, Parameter-Controls, Papierkorb, Set-/Service-Sperren).
* **15.2 Analytics-Lesepfade:** `schema_version` vervollständigen (Invariante 5);
  Chart-Entkopplung abschließen (Invariante 10: Pipeline-Fallback im Indikator additiv abbauen).
* **15.3 Alt-Pfad-Rückbau:** Alt-Signal-Mechanik (`signal_results`, Signal-Sets,
  Alt-Scan-Pfade in LiveAnalyzer/HistoricalScanner) additiv abwickeln.
* **15.4 ML-Signale (optional):** `lightgbm_v1` / `xgboost_v1` aktivieren und
  dokumentieren oder explizit als „future" deklarieren.

Jedes Modul enthält direkt im Anschluss die vollständige, isolierte **Schritt-für-Schritt AI-Implementierungsanweisung** inklusive automatischer Git-Backup-Regeln, Architektur-Constraints, des zentralen Grundsatzkapitels und der headless Validierung.

---

## 2. Allgemeine Grundsätze & Workflow-Vereinbarungen (Agents.md / Architektur.md)

1. **HARTE VERBOTSREGEL (Bestands-Pfade):**
   Geschützte Dateien (niemals beschädigen, bestehende Aufrufe unverändert lassen):
   * `../chart/indicators/grid_liquidity.py` – Plugin-Indikator (Service-Pipeline-Adapter, Cache, feature_store-Lesepfad).
   * `../analytics/features/definitions/grid_liquidity.py` – Alt-Plugin (Schema-Quelle fürs Prop-Fenster).
   Neue Logiken werden **additiv** integriert (Wrapper/Schnittstellen).
   **Bereits ausgebaut (04.08.2026, Einzelanweisung des Users):**
   `../chart/indicators/grid.py` (Alt-Grid-Indikator, nicht-Plugin) – die Verbotsregel
   gilt für diesen Pfad nicht mehr. Paritäts-Referenzen auf dieses Modul werden auf
   eigenständige Kopien umgestellt (U15-B3, Abschnitt 4).

2. **Git-Backup & Fallback vor JEDEM Kapitel:**
Vor Beginn jedes Kapitels erstellt die AI / der User automatisch einen Git-Commit und Tag: `phase15_step1`, `phase15_step2`, etc. Bei Fehlern wird sofort per `git reset --hard` auf das jeweilige Tag zurückgerollt.

3. **Headless-Validierung (Keine UI- und Keine unnötigen (Regressions-)tests):**
Validierungen erfolgen rein headless (kein `QApplication.exec()`, keine manuellen Klicks) über gezielte PyTest- / Headless-Python-Skripte im Ordner `../test`. Es werden ausschließlich die für den jeweiligen Schritt absolut notwendigen Tests ausgeführt – keine unnötigen (Regressions-)tests.

4. **Modulare Herauskoppelbarkeit:**
Jedes Kapitel ist so aufgebaut, dass Beschreibung, Schema-Änderung, Implementierungsanleitung, die allgemeinen Grundsätze und der notwendige Test als zusammenhängender Block an die IDE-AI übergeben werden können.

5. **Struktur & Refactoring:**
Phase 15 bleibt **rein additiv**. Die Harte Verbotsregel (Bestands-Pfade) gilt
uneingeschränkt; die bereits erfolgte Entfernung von `grid.py` ist die einzige
Ausnahme (Einzelanweisung, dokumentiert in Punkt 1). Existing Subsysteme werden
nicht gebrochen, sondern um Schnittstellen/Wrapper erweitert.

---

## 3. Architektur-Invarianten (Kapitel 15.0 - Fundament)

Vor jeglicher Code-Implementierung gelten folgende unumstößliche System-Regeln zur Sicherstellung der Konsistenz:

1. **PluginRegistry Ownership:** Genau eine Singleton-Instanz der `PluginRegistry` pro Prozess.
2. **Feature Store vs. Cache (Source of Truth):**
`Plugin` $\rightarrow$ `PluginContext.shared_state` (Live-RAM) $\rightarrow$ `feature_store` (DuckDB, persistenter Vorberechnungs-Speicher) $\rightarrow$ `Indicator` (GUI-Lesepfad).
Der Indicator ruft niemals direkt Plugins zur Neuberechnung auf.
**Präzisierung (Empfehlung 1):** Die Konzeptklasse heißt `PluginContext` (Begriff
„EvaluationContext" ist vereinheitlicht; die reale Klasse liegt in
`analytics/features/plugins/base_plugin.py`). Abbauziel 15.2: Der noch vorhandene
Pipeline-Fallback in `grid_liquidity.calculate()` wird additiv durch einen reinen
DB-Lesepfad ersetzt.
3. **ID-Semantik:**
* `depends_on` referenziert ausschließlich `instance_id` (z. B. `"grid_1"`).
* `plugin_id` ist strikt case-insensitiv eindeutig (`plugin_id.lower()`).
4. **Quarantäne-Lebensdauer:** Quarantäne (`quarantined = True`) gilt ausschließlich im RAM für die aktuell laufende Session und wird nicht in der Datenbank persistiert.
5. **Versionierung & Schema:**
* Jeder Plugin-Output und Feature-Payload enthält ein `schema_version`.
  **Präzisierung (Empfehlung 2):** `schema_version` wird Pflichtfeld im
  `FeatureStorePayload`-TypedDict (`base_plugin.py`) und von ALLEN
  `feature_store=True`-Plugins gestempelt (inkl. Alt-Plugin
  `definitions/grid_liquidity.py`; bisher nur `ProximityService` – U15-A1).
* Jedes Plugin deklariert explizit eine `api_version` (z. B. `api_version="1"`).
* Versionsvergleiche nutzen Semantic Versioning (`major.minor.patch`). Reine Patch-Updates (z. B. `1.0.0` $\rightarrow$ `1.0.1`) lösen keine Schema-Migration aus.

6. **Hot-Reload-Semantik:** `PluginRegistry.reload()` ersetzt nur zukünftige Service-Instanziierungen; bereits laufende Hintergrund-Auswertungen laufen ungestört auf ihren bisherigen Objektinstanzen weiter. Custom Plugins werden isoliert entladen/neu importiert.
7. **Thread Safety:** Der Zugriff auf `PluginRegistry`, `ServiceSetEvaluator`
(Session-State, Quarantäne) und `FeatureStore` (Cache-Invalidierung) erfolgt über
`RLock` (Thread-Safety).
**Präzisierung (Empfehlung 3):** DB-Zugriff erfolgt bewusst **lock-frei** über
Thread-local `DbPool` (`db_service.py`, eine Connection pro Thread & DB) – globale
Threading-Locks auf Datenbankebene sind kontraproduktiv und werden nicht verwendet.
8. **Logging & Migration Rollback:**
* Logging verwendet strukturierte Fehlerobjekte (inkl. `timestamp`, `plugin`, `instance`, `symbol`, `timeframe`, `bar`, `exception`, `traceback`).
* Schlägt eine Schema-Migration fehl (`SchemaMigrator` Exception), wird die Transaktion abgebrochen, das alte Set im Speicher belassen und ein Rollback durchgeführt.

9. **Snapshot-Historie:** Ein historischer Snapshot in `service_set_history` wird ausschließlich beim erfolgreichen Überschreiben eines bereits existierenden Sets erzeugt.
10. **Chart-Entkopplung:** Der Chart führt niemals Berechnungen aus, sondern liest
ausschließlich vorberechnete Daten aus DuckDB (mit definiertem Fallback).
**Stand 04.08.2026:** Alt-Indikator `grid.py` entfernt; verbleibender Plugin-Indikator
`grid_liquidity` liest primär `feature_store` (`read_proximity_from_feature_store`).
Der noch vorhandene Service-Pipeline-Fallback in `calculate()` ist **Abbauziel 15.2**
(U15-A2).
11. **Quarantäne-Recovery (Lebensdauer):** Der `_failure_counters`-Zähler jeder Service-Instanz wird nach 300 Sekunden (5 Minuten) ohne weiteren Fehler automatisch zurückgesetzt (`_recovery_timer`). Eine einmalige Quarantäne (`quarantined = True`) bleibt für die laufende Session bestehen, bis der Evaluator einen vollständigen Neustart der Pipeline durchläuft (`reset()`).
12. **Hot-Reload Lifecycle:** `PluginRegistry.reload()` führt folgende atomare Schritte unter dem `RLock()` aus:
    a) Erfassen der aktuell geladenen Custom-Modul-Namen (`../data/custom_plugins`).
    b) Gezieltes `importlib.reload(sys.modules[mod_name])` NUR für diese Module.
    c) Erneute Ausführung von `discover_plugins()` mit anschließendem Überschreiben des internen `plugins`-Dictionaries.
    d) WICHTIG: Bereits laufende Service-Instanzen (`LiveAnalyzer`, historische Berechnungen) behalten ihre alte Objekt-Referenz; neue Service-Instanzen nutzen die neuen Klassen.

13. **Cache-Invalidierung (Feature Store):** Der `FeatureBuilder` führt bei jedem `store_plugin_payload()` eine explizite Invalidation des In-Memory-Caches für das betroffene `(symbol, timeframe)` durch, um veraltete Zustände in `PluginContext.shared_state` zu verhindern.

---

## 4. Resultierende Umsetzungsliste (noch zu implementieren)

Basis: Empfehlungen 5–6 aus `docs/Bericht_Phase15_Rumpf_Check.md` + Konsequenzen aus
der Entfernung des Alt-Grid-Indikators + abgeleitete Kapitel-Arbeiten (15.1–15.4).

### A. Empfehlungen aus dem Bericht (noch offen)

- [ ] **U15-A1** `schema_version` als Pflichtfeld im `FeatureStorePayload`-TypedDict
  (`analytics/features/plugins/base_plugin.py`) ergänzen; Stempelung in ALLEN
  `feature_store=True`-Plugins sicherstellen (Alt-Plugin
  `analytics/features/definitions/grid_liquidity.py` ergänzen; `ProximityService`
  ist bereits konform). → Kapitel 15.2
- [ ] **U15-A2** Chart-Entkopplung abschließen (Invariante 10): Pipeline-Fallback in
  `chart/indicators/grid_liquidity.py` `calculate()` additiv durch reinen
  DB-Lesepfad ersetzen; `read_proximity_from_feature_store()` als Primärpfad
  festigen, definierter Fallback dokumentieren. → Kapitel 15.2
- [x] **U15-A3** `docs/AKTUELLE_UMSETZUNG.md` wieder aufsetzen bzw. die
  Phase-15-Roadmap als neue Hauptanweisung etablieren (Abstimmung mit
  System-Regel 0c). → vor Kapitel 15.1
  **Umgesetzt (04.08.2026):** `docs/AKTUELLE_UMSETZUNG.md` neu aufgesetzt –
  enthält Zielsetzung, Grundsätze, Arbeitsstand (erledigt/offen in
  Reihenfolge), Legacy-Tabellen-Entscheidung (U15-C3), ML-Entscheidung
  (U15-A4) und die neue `serviceui/`-Modularisierungs-Anweisung (U15-D1).
- [x] **U15-A4** ML-Signale: Entscheidung aktivieren vs. deaktivieren
  (`analytics/signals/machine_learning/`); bei Aktivierung `lightgbm`/`xgboost`
  in `requirements.txt` ergänzen und Signale in Worker/UI verdrahten.
  → Kapitel 15.4
  **Entscheidung (04.08.2026): DEAKTIVIERT / explizit als „future" deklariert.**
  * `LightGBMSignal`/`XGBoostSignal` (`analytics/signals/machine_learning/`)
    sind eigenständige `SignalDefinition`-Subklassen mit LAZY-Imports
    (`import lightgbm`/`import xgboost` erst beim `_load_model`-Aufruf) – sie
    brechen den Import nicht, sind aber nirgends registriert/verdrahtet.
  * `requirements.txt` enthält weder `lightgbm` noch `xgboost`; eine
    Aktivierung würde Modell-Dateien (`model_file`), Feature-Konfiguration und
    Worker/UI-Verdrahtung erfordern – bewusst NICHT Teil von Phase 15.
  * Die Klassen bleiben als „future"-Baustein erhalten (kein Löschen, kein
    Registrieren). → Kapitel 15.4 bei Bedarf reaktivierbar.

### B. Konsequenzen aus der Entfernung des Alt-Grid-Indikators

- [ ] **U15-B1** Test-Anpassung (headless): `check_grid_parity.py`,
  `check_grid_circles.py`, `check_p13_s6.py`, `check_plugin_time_filter.py`
  importieren `GridIndicator` (entfernt) → auf Plugin-Pfad
  (`GridLiquidityIndicator` + Services `grid_lines`/`proximity`) umstellen oder
  entfernen.
- [ ] **U15-B2** Code-Inspektionstests anpassen: `check_grid_buttons.py`,
  `check_grid_liquidity_indicator.py` prüfen `'"grid": GridIndicator()'` in der
  Registry → Assertions auf neuen Stand (nur `grid_liquidity`, kein `grid`-Button)
  umstellen.
- [ ] **U15-B3** Paritäts-Logik vereinheitlichen: Kommentare in
  `grid_lines_service.py`, `proximity_service.py`, `grid_levels.py` verweisen auf
  das gelöschte `grid.py`. Paritätsfunktionen in ein eigenständiges Modul
  extrahieren (z. B. `analytics/features/definitions/grid_math.py`) oder als
  eingefrorenen Referenz-Snapshot fixieren; Kommentare aktualisieren. → Kapitel 15.2
- [ ] **U15-B4** UI-State-Bereinigung: persistierte `indicators_state['grid']`-Einträge
  und `indicator_presets`-Zeilen (`indicator_id='grid'`) in `app_data.duckdb`
  ignorieren/bereinigen. Der Legacy-Pfad in `_resolve_indicator_params()` bleibt
  bestehen (Abwärtskompatibilität), erhält aber keine Registry-Instanz mehr.

### C. Alt-Pfad-Rückbau (additiv, Kapitel 15.3)

- [ ] **U15-C1** `LiveAnalyzer`: Zielzustand festlegen; Alt-Signal-Pfade
  (`_fill_gaps`, `_process_new_bars`, `analyze_single_bar`,
  `_process_plugin_bars`, `set_config['signals']=[]`) additiv abwickeln;
  resilienter Pfad (`_process_plugin_bars_resilient`) als Zielzustand.
- [ ] **U15-C2** `HistoricalScanner`: Alt-Scan (grid/standard) vs. Plugin-Batch –
  Zielzustand festlegen; `signal_results`-Schreibpfade endgültig abwickeln.
- [x] **U15-C3** Legacy-Tabellen `signal_definitions`, `signal_sets`,
  `signal_results` in `analytics.duckdb`: nach Abschluss des Alt-Pfad-Rückbaus
  entscheiden (löschen vs. als Referenz behalten). `signal_results` bleibt bis dahin
  unverändert erhalten.
  **Entscheidung (04.08.2026): Alle drei Tabellen werden ALS REFERENZ BEHALTEN**
  (kein DROP). Begründung:
  * `db_service.py` legt sie bei jedem Init per `CREATE TABLE IF NOT EXISTS`
    (Z. 246/254/261) ohnehin neu an – ein DROP wäre wirkungslos und würde beim
    nächsten Start automatisch re-erzeugt.
  * `signal_results` wird noch von den DEAKTIVIERTEN Alt-Pfaden in
    `live_analyzer.py` referenziert (`_fill_gaps`/`_process_plugin_bars`,
    Early-Return, `set_config['signals']=[]`). Erst wenn diese Alt-Pfade
    physisch abgewickelt sind (U15-C1/C2), entfällt die letzte Referenz.
  * Aktive Lese-/Schreibpfade existieren nicht mehr: `statistics_repository.py`
    liest `feature_store` (feature_id), `chart/overlays/signal_overlay.py` hat
    den signal_results-Fallback entfernt (Phase 13 7.B), `historical_scanner.py`
    schreibt nicht mehr in `signal_results`. Die Tabellen sind ungenutzt und
    dienen als Schema-Referenz der Alt-Signal-Mechanik.

### D. Service-UI-Modularisierung (Kapitel 15.1)

- [x] **U15-D1** `service_win.py` modularisieren: Set-Editor, Parameter-Column-Builder,
  Papierkorb-Dialog, Info-/Beschreibungs-Dialoge in eigene Widgets/Dialoge extrahieren
  (SRP, Invariante-Konformität); Verhalten unverändert.
  **Umgesetzt (04.08.2026, User-Anweisung):** Neuer Unterordner **`serviceui/`**
  – die gewachsene Datei wurde dorthin verschoben (inkl. `service_win.py`
  selbst) und in SRP-Module zerlegt:
  * `serviceui/service_win.py` – `ServiceWindow` (re-exportiert die öffentliche
    API: `ServiceSetRunWorker`, `ServiceSetItemAdapter`, `_available_plugin_ids`,
    `_sets_using_plugin`; `BASE_DIR = parent.parent` für `ui/service_win.ui`).
  * `serviceui/service_set_utils.py` – `_available_plugin_ids`, `_sets_using_plugin`.
  * `serviceui/set_run_worker.py` – `ServiceSetRunWorker` (QThread).
  * `serviceui/set_item_adapter.py` – `ServiceSetItemAdapter` (Set-Editor-Adapter,
    NamedItemActionsMixin-Mechanik).
  * `serviceui/param_columns.py` – `ServiceParamColumnsMixin`
    (Parameter-Column-Builder, dynamische Service-Spalten).
  * `serviceui/trash_dialog.py` – `ServiceSetTrashDialog` (Papierkorb-Dialog,
    P14-05, doppelte Sicherheitsnachfrage).
  * `serviceui/__init__.py` – Paket-Re-Exports.
  Imports aktualisiert: `main.py` (Z. 42), `chart/widgets/__init__.py`
  (Kommentar), `Architektur.md` (Z. 91) sowie die Test-Dateien
  `check_p13_s4.py`, `check_p13_service_win_geometry.py`, `check_p13_ui_plugins.py`,
  `check_p14_precision_levels.py`, `check_p14_s4_services_locked.py`.
  **Headless-Validierung:** py_compile OK; alle 5 betroffenen Checks BESTANDEN
  (`check_p14_s4_services_locked.py`, `check_p13_s4.py`, `check_p13_ui_plugins.py`,
  `check_p13_service_win_geometry.py`, `check_p14_precision_levels.py`).
  Dabei 2 vorbestehende (P14-01/P14-04-E-bedingte) Test-Staleness-Fixes:
  * `check_p13_s4.py` [7]: Service-Sperre (P14-04-E) blockiert Entfernen von
    `grid_liquidity` (gesperrt durch gespeichertes Set) – Test nutzt für den
    Remove-Mechanik-Check jetzt `grid_lines` (frei) + prüft die Sperre
    (QMessageBox.warning gemockt).
  * `check_p13_ui_plugins.py` [4]+[11]: Instanz-Platzhalter-Auswahl (P14-01,
    mehrere placeholderText) + Stack-Count 2 statt 3 (P14-01: keine
    Plugin-Live-Seite 0).
- [x] **U15-D2** Bedien-Feinschliff: offen für User-Vorgaben (Sammelliste während 15.1).
  **Umgesetzt (04.08.2026, User-Vorgabe „Alle Punkte nacheinander"):**
  * **(1) Doppeltes Ausführen eines Sets verhindern (Button-Lock):** Der Guard
    (`_set_run_worker.isRunning()` → „Set-Ausführung läuft bereits.") bestand
    bereits; zusätzlich zeigt `btn_execute_set` jetzt während der Laufzeit
    „Läuft..." (deaktiviert) und nach `run_finished`/`run_failed` wieder
    „Ausführen" (aktiviert).
  * **(2) Set-Dropdown lädt nach Löschen/Umbenennen automatisch das nächste
    gültige Set:** war bereits über die generische Mechanik implementiert
    (`delete_named_item` → `_item_select(None)` → `refresh_set_list()` lädt das
    erste verbleibende Set; nach Umbenennen wird das gespeicherte Set
    selektiert) – per Headless-Test verifiziert, keine Code-Änderung nötig.
  * **(3) Log-Bereich:** `log()` scrollt jetzt automatisch ans Log-Ende
    (`verticalScrollBar().setValue(maximum())`); Kontext-Rechtsklick
    (CustomContextMenu) mit „Kopieren" (nur bei Textauswahl) und
    „Log leeren" (`_on_log_context_menu`).
  * **(4) Bestätigungsdialog vor Voll-Scan:** Bei `new_scan=True`
    (FULL SCAN = bestehende Signale werden gelöscht, unwiderruflich) fragt
    `start_scan` per `QMessageBox.question` nach (Default: No). Delta-Scan
    (`new_scan=False`) startet ohne Rückfrage.
  **Validierung:** py_compile OK; alle 5 betroffenen Headless-Checks BESTANDEN
  (`check_p13_s4.py`, `check_p13_ui_plugins.py`, `check_p14_s4_services_locked.py`,
  `check_p14_precision_levels.py`, `check_p13_service_win_geometry.py`) plus
  gezielte U15-D2-Headless-Verifikation (Button-Lock, Set-Nachladen, Auto-Scroll,
  Scan-Bestätigung: 14/14 PASS).

---

## 5. Git- & Dokumentationsstand (Vorbereitung)

* Stand 04.08.2026: `grid.py` entfernt, `chart_win.py`/`__init__.py`/`ui/chart_win.ui`
  bereinigt, `Architektur.md` (Root) aktualisiert, `docs/Old/x_Architektur.md`
  faktisch korrigiert (Archiv, wird nicht mehr gepflegt).
* Commit/Backup der Vorbereitung: `phase15_prep` (empfohlen vor Kapitel 15.1).
