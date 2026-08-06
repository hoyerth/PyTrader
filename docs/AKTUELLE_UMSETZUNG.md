# Phase 15: Service UI, Symbol-Verwaltung & Analytics Engine

## 1. Übersicht & Zielsetzung

Ziel von **Phase 15** ist die Weiterentwicklung der Service-UI (`service_win.py`), die Bereitstellung einer zentralen Symbol- und Favoritenverwaltung, der systematische Abbau von Alt-Pfaden sowie der Aufbau einer hochperformanten, entkoppelten Analytics-Engine auf Basis der Plugin- und Service-Architektur (Phasen 12–14).

* **15.01 Symbol-Auswahl & Favoriten:** Broker-Fetch via MT5, Persistierung in `app_data.duckdb`, Favoriten-Dropdowns & nicht-modales `SymbolsWindow`.
* **15.02 Service-UI Refactoring & Master-Tree:** Modularisierung der gewachsenen `service_win.py` in Orchestrator + Sub-Widgets (`MasterTree`, `ParameterPanel`, `Toolbar`), Einführung von `ServiceTreeModel`, 2-Spalten-TreeWidget mit Indikator-Live-Status (`📌` / `🟢`) & Buttons für Struktur-Aktionen.
* **15.03 Analytics Engine & UI:** Ersetzung von `../../statistic_win.py` durch `AnalyticsWindow` (`analytics/ui/analytics_win.py`), Entkopplung via MVVM (`AnalyticsViewModel`, `AnalyticsRepository`, `FeatureStoreReader`), `pyqtgraph`-Visualisierungen (Tabelle, Heatmap, Scatter, Verteilung), Profil-CRUD mit Explicit Save (`*`) & `schema_version` im Profil-JSON, Entkopplung über einen zentralen `EventBus`.

---

## 2. Allgemeine Grundsätze & Architektur-Invarianten

2. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase15_step1`, `phase15_step2` usw.).
3. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte in `test`.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
5. **Zentraler `EventBus`:** Fenster kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`../../db_service.py`).
7. **Wanduhr-Garantie:** Achsen und Zeitfilter formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.

### Entscheidungs-Protokoll Phase 15 (Beschluss 04.08.2026)

| # | Thema | Entscheidung |
| --- | --- | --- |
| E-1 | Legacy-Alias `../../analytics/statistics_repository.py` | Bleibt bis auf Weiteres unverändert bestehen; kompletter Ersatz erst in einer späteren Phase |
| E-2 | Persistenz `win_statistics` | Fenstergeometrie & Instanz-Zustände werden beim Ersetzen nach `win_analytics` migriert |
| E-3 | `schema_version` Pflichtfeld | Pflichtfeld im `FeatureStorePayload`; alte `feature_store`-Rows erhalten beim Lesen den Default `"1.0.0"` (harmonisiert am 06.08.2026) |
| E-4 | Schutzregel Grid-Liquidity | Schutz für `../../chart/indicators/grid_liquidity.py` aufgehoben; Anpassungen erlaubt, wenn der Fallback-Abbau sie erfordert |
| E-5 | Zeilenzahl `service_win.py` | Doku-Korrektur: 864 Zeilen (statt 1.400) |
| E-6 | Pfad-Konvention | Dateien werden einheitlich vom Projekt-Root referenziert (ohne `../..`) |

---

# TASK: Phase 15.04 – Infrastructure & EventBus Hardening

Bitte setze das Infrastruktur-Upgrading und das Cleanup der Repositories/Payloads gemäß den folgenden Spezifikationen um:

---

 ### 1. EventBus verifizieren statt ergänzen (config/event_bus.py) – STATUS: bereits umgesetzt

 ACHTUNG (Ist-Analyse 05.08.2026): Alle geforderten Core-Signale existieren
 bereits in `config/event_bus.py` – inkl. des Concurrency-Guards (Phase 16,
 getestet in test/test.py S1–S8). Dieser Abschnitt ist KEIN Implementierungs-
 auftrag mehr, sondern eine reine Bestands-Verifikation:

 - `favorites_changed = Signal()`
 - `profile_changed = Signal(str)`
 - `service_set_changed = Signal()`
 - `service_run_started = Signal()`   # Concurrency-Guard (Timer-Stop, main.py)
 - `service_run_finished = Signal()`  # Concurrency-Guard (Timer-Start, main.py)

 Erwartete Aktion:
 - KEINE Änderung an config/event_bus.py.
 - Verifikation nur über den Headless-Check (Abschnitt 4): prüft, dass alle
   5 Signale existieren und per connect/emit empfangen werden können.

---

### 2. WindowStateRepository herauslösen (window_state_repository.py) – UMGESETZT (06.08.2026)

 1. **Erstelle `window_state_repository.py` im Root:**
    - Kapselt die SQL-Zugriffe auf `window_instances`, `instance_states` UND
      `symbol_tf_states` aus `app_data.duckdb` (alle instanz-/fensterbezogenen
      Tabellen – nicht nur die zwei im Ursprungsentwurf genannten).
    - Nutzt zwingend `DbPool.get(db_path)` (Thread-local, lock-frei, wie
      StateManager) – KEINE eigene Connection-Verwaltung.
    - Methoden: `save_window_geometry()`, `get_window_geometry()`,
      `save_instance_state()`, `load_all_instances()`, `delete_instance()`,
      `get_next_instance_id()`, `save_symbol_tf_state()`,
      `get_symbol_tf_state()`, `delete_symbol_tf_state()`.
    - `load_all_instances()` reproduziert das Bestandsverhalten EXAKT
      (pandas-`.df()`-Leseart + String-Normalisierung von symbol/timeframe).
    - Das Repository ist REIN lesend/schreibend – die Schema-Anlage und
      -Migration (DDL in `_init_db()`) verbleibt im StateManager
      (keine Verantwortungs-Verdopplung).

 2. **`state_manager.py` zur additiven Fassade verschlanken (Verbotsregel):**
    - ALLE bestehenden Methoden bleiben mit identischen Signaturen erhalten
      (Rückwärtskompatibilität – keine Aufrufer-Änderung in main.py,
      persistent_win.py, chart_win.py, service_win.py, Analytics, Tests).
    - Die Instanz-/Fenster-Methoden delegieren intern an das neue
      WindowStateRepository; die DB-Pfad-Auflösung bleibt beim StateManager
      und wird an das Repository durchgereicht (Test-Isolation!).
    - NICHT umsetzen (falsche Prämisse im Ursprungsentwurf): „Delegiert
      Profil-Abfragen an AnalyticsProfileRepository und Symbol-Abfragen an
      SymbolRepository" – StateManager hat KEINE solchen Methoden; beide
      Repositories sind bereits eigenständig im Root vorhanden und werden
      direkt genutzt. Es gibt nichts zu delegieren.

 3. **Test-Isolation sicherstellen:**
    - `test/test.py` patcht `StateManager.__init__` auf eine Temp-DB. Diese
      Patch-Strategie wird auf das neue WindowStateRepository erweitert
      (gleiche Temp-DB), damit alle Fenster-/Repository-Checks weiterhin
      unabhängig von der laufenden App laufen (DuckDB-Single-Writer).

---

### 3. Schema-Version & FeatureStore-Payload – UMGESETZT (06.08.2026)

 1. **Pflichtfeld `schema_version` im Payload – BEREITS ERFÜLLT (nur verifiziert):**
    - `grid_lines_service.py` und `proximity_service.py` setzen bereits
      `"schema_version": "1.0.0"` in `feature_store_payload["metadata"]`.
    - KEINE Änderung an den Plugins nötig; verifiziert im Headless-Check
      (`test/check_p15_s4_infra.py`, V2/V3).

 2. **Alt-Data Default im Lesepfad – HARMONISIERT (1 konkrete Änderung):**
    - `feature_store_reader.py` nutzte `SCHEMA_VERSION_DEFAULT = "1.0"`
      (zweistellig) – die Spezifikation und die Plugins verwenden `"1.0.0"`
      (dreistellig). Seit 06.08.2026 ist der Default auf `"1.0.0"`
      vereinheitlicht (inkl. Docstring/Kommentar E-3 in `feature_store_reader.py`
      und diesem Dokument).
    - Verhalten bleibt additiv: `_normalize_feature_data()` ergänzt fehlende
      `schema_version` beim Lesen – die DB-Zeile wird NICHT überschrieben
      (verifiziert in V4–V7).

 3. **Konzeptionelle Lücke dokumentiert (abgeschlossen 06.08.2026):**
    - `store_plugin_payload()` persistiert NUR die Records in `feature_data`;
      das `metadata`-Dict inkl. `schema_version` wird NICHT in die DB
      geschrieben. Der Reader-Default greift daher beim Lesen immer.
    - **`schema_version` ist ein reiner In-Memory-Vertrag des
      `feature_store_payload`** (Plugin-Ausgabe → Evaluator → Indikator-Lesepfad).
      Die Persistenzschicht kennt sie nicht; die DB enthält die Records inkl.
      nativer Spalten, aber ohne das metadata-Payload. Dieser Umstand ist
      gewollt und wird bewusst nicht geändert – Abschnitt 3 ist damit
      vollständig abgeschlossen.

---

### 4. Headless Verifikation (test/check_p15_s4_infra.py) – UMGESETZT (06.08.2026)

 Erstellt: `test/check_p15_s4_infra.py` (offscreen, Temp-DBs unter test/ –
 Regel: Tests nur in test/). Prüft – angepasst an den Ist-Stand:

 1. **EventBus-Bestand (statt Implementierung):**
    - Alle 5 Signale existieren auf `event_bus` und sind per `connect` +
      `emit` empfängbar (favorites_changed, profile_changed(str),
      service_set_changed, service_run_started, service_run_finished).

 2. **WindowStateRepository (Temp-DB, Patch analog test/test.py):**
    - `save_window_geometry`/`get_window_geometry`-Roundtrip (inkl.
      is_maximized), `save_instance_state` + `load_all_instances`
      (String-Normalisierung), `delete_instance` (beide Tabellen),
      `get_next_instance_id` (win_1, win_2, ...), symbol_tf_state-Roundtrip.
    - Fassaden-Delegation: `StateManager` liefert über seine Bestands-Methoden
      identische Werte wie das Repository (gleiche DB).

 3. **schema_version (harmonisiert):**
    - `GridLinesService.calculate()` und `ProximityService.calculate()`
      (synthetischer OHLCV-DataFrame) liefern
      `payload["metadata"]["schema_version"] == "1.0.0"`.
    - `FeatureStoreReader._normalize_feature_data(None)` bzw. Alt-Row ohne
      Feld → `"1.0.0"` (Default); vorhandenes Feld bleibt unangetastet;
      DB-Zeile unverändert.

---

### ⚠️ Richtlinien
- **Keine UI-Tests starten!** Verifikation ausschließlich über den Headless-Check (`python test/check_p15_s4_infra.py`) und `py_compile`.
- Erzeuge gezielte, saubere Code-Snippets/Patches.

---

## Implementierungs-Log (Taxonomie: Phase 15.04)

### 06.08.2026 – 15.04 Infrastructure & EventBus Hardening (UMGESETZT)

**1) EventBus verifiziert (keine Änderung an `config/event_bus.py`):**
Alle 5 Signale (`favorites_changed`, `profile_changed(str)`,
`service_set_changed`, `service_run_started`, `service_run_finished`)
existieren und sind per connect/emit empfängbar (Check B1–B5 in
`test/check_p15_s4_infra.py`).

**2) `window_state_repository.py` im Root erstellt:**
- Kapselt alle instanz-/fensterbezogenen SQL-Zugriffe (`window_instances`,
  `instance_states`, `symbol_tf_states`) aus `app_data.duckdb`.
- Nutzt `DbPool.get(db_path)` (Thread-local, lock-frei) – keine eigene
  Connection-Verwaltung.
- 9 Methoden (save/get_window_geometry, save_instance_state,
  load_all_instances, delete_instance, get_next_instance_id,
  save/get/delete_symbol_tf_state). `load_all_instances()` reproduziert das
  Bestandsverhalten EXAKT (pandas-`.df()`-Leseart + String-Normalisierung).
- Schema-Anlage/-Migration bleibt im StateManager (keine DDL im Repository).

**3) `state_manager.py` als additive Fassade:**
- Alle Bestands-Methoden mit identischen Signaturen erhalten (Rückwärts-
  kompatibilität – keine Aufrufer-Änderung). Die 9 Instanz-/Fenster-Methoden
  delegieren intern an das WindowStateRepository.
- DB-Pfad-Auflösung bleibt beim StateManager und wird an das Repository
  durchgereicht (Test-Isolation). Patch-Strategie aus `test/test.py` auf
  WindowStateRepository erweitert (gleiche Temp-DB, Check I1/F7).

**4) `schema_version` harmonisiert:**
- `feature_store_reader.py`: `SCHEMA_VERSION_DEFAULT` von `"1.0"` auf
  `"1.0.0"` vereinheitlicht (E-3-Kommentare + Docstring aktualisiert).
- Reader-Default und Plugin-Vertrag (grid_lines/proximity, `metadata`) sind
  jetzt identisch. `_normalize_feature_data()` bleibt additiv – DB-Zeile wird
  nicht überschrieben.

**5) Headless-Verifikation (`test/check_p15_s4_infra.py`):**
- 33 Checks bestanden: EventBus (B1–B5), WindowStateRepository (W1–W13,
  I1), Fassaden-Delegation (F1–F7), schema_version (V1–V7).
- Zusätzlich `python test/test.py` ausgeführt: keine neuen Regressionen
  (die 3 vorbestehenden Breiten-Checks P2/P5/H7 scheitern auch ohne diese
  Änderung – offscreen-Screen 800×800 vs. Breiten-Annahme ≥ 1300 px).

**Git:** Tag `phase15_04_backup` vor der Umsetzung; Commit nach Freigabe.