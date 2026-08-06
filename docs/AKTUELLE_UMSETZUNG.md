# Phase 16: Architektur Servive/Indikator - Feinarbeit Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 16)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase16_step1`, `phase16_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
4. **Zentraler `EventBus`:** Fenster und Worker communicaten schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
5. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`../../db_service.py`) – eine Verbindung pro Thread und DB-Datei.
6. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
7. **Concurrency-Guard & Timer-Pausierung (Ergänzung 1):** Solange im ServiceWindow intensive Service-Berechnungen laufen (`SetRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
8. **Isolierter Test-Workspace (Ergänzung 2):** Alle neuen Test-Python-Dateien und temporären Test-Datenbanken (`*.duckdb`) müssen strikt im Unterordner `test/` erzeugt, gelesen und abgelegt werden – niemals im Projekt-Root oder im `data/`-Ordner.
9. **Open/Closed-Principle & Code-Preserving (Ergänzung 3):** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden und bestehende Kern-Klassen bleiben geschützt.
10. **Test-Cleanup (Ergänzung 4, Entscheidung 06.08.2026):** Tests werden NICHT aufbewahrt. Nach Abschluss jedes Phasenkapitels wird der Ordner `test/` aufgeräumt – es bleibt ausschließlich die Datei `test/test.py` (dauerhafter Test-Harness) bestehen. Alle temporären Check-Skripte (`check_*.py`/`*.js`), einmaligen Migrations-/Bereinigungsskripte, Test-Datenbanken (`*.duckdb`) und generierten Dateien (`tmp_*.json` u. Ä.) werden entfernt. Die Verifikation eines Kapitels erfolgt daher VOR der Bereinigung; danach existieren die Prüfskripte nicht mehr.

---

## 16.01.02 ⚠️ Nachgelagerte Arbeiten 

> **Hinweis:** Diese optionalen Bereinigungs- und Pflegearbeiten dürfen erst nach expliziter Anforderung und Prüfung nach Abschluss der Schritte 1–4 durchgeführt werden.

### 1. Code- & Parameter-Bereinigung
* **Backend-Services (`grid_lines_service.py`, `proximity_service.py`):**
  * Finale Entfernung ungenutzter Rendering-Keys (`lines`, `hit_circles`, `show_lines`, `line_color`, `show_circles`, `circle_color_std`, `circle_color_active`) aus den Rückgabe-Dictionaries von `calculate()`.

### 2. DB- & Preset-Bereinigung (`app_data.duckdb`)
* **Service-Sets & Presets (`indicator_presets`, `service_sets`):**
  * *Automatischer Puffer:* Der `SchemaMigrator` filtert veraltete UI-Keys beim Laden transparent im Arbeitsspeicher heraus (kein Handlungsbedarf für den Betrieb).
  * *Endgültige Bereinigung:* **DURCHGEFÜHRT (06.08.2026, Entscheidung Benutzer).** Einmaliges Skript `test/cleanup_p16_legacy_rendering_keys.py` hat die veralteten Rendering-Keys (`show_lines`, `line_color`, `show_circles`, `circle_color_std`, `circle_color_active`, `hit_circles`, `lines`) rekursiv aus den JSON-Payloads von `service_sets`, `service_sets_trash` und `indicator_presets` entfernt. Betroffen war 1 Zeile (Set „test", `grid_lines`-params: `show_lines` + `line_color`). `service_set_history` bleibt als unveränderliches Snapshot-Protokoll unangetastet.

### 3. Verifikation & Test-Cleanup
* **Isolierter Test-Check (VOR der Bereinigung):**
  * `test/check_p16_s1_decoupling.py`: 31/31 Checks PASS – `feature_store_payload` frei von Canvas-Objekten, `FixedGridProximityIndicator` baut das `chart_render_payload` korrekt.
  * Statische Syntaxprüfung via `python -m py_compile` (5 Dateien): OK.
  * Read-only-DB-Check nach der Bereinigung: keine Legacy-Keys mehr in `service_sets`/`service_sets_trash`/`indicator_presets` (exakte Key-Prüfung).
* **Test-Cleanup (Ergänzung 4):** Nach Abschluss von 16.01.02 wurde der Ordner `test/` aufgeräumt – alle Check-/Migrations-/Temp-Dateien entfernt, verbleibend: `test/test.py`.

### 4. Prüfstand 16.01.02 (abgeschlossen 06.08.2026)
* **Punkt 1 – Code- & Parameter-Bereinigung: UMGESETZT (P16.01, Commit `1632787`).**
  * `grid_lines_service.calculate()` liefert ausschließlich `feature_store_payload` – keine Rendering-Keys mehr (`lines`, `hit_circles`, `show_lines`, `line_color`). `show_lines`/`line_color` sind weder in `parameter_order`/`param_labels` noch in `parameter_schema`.
  * `proximity_service.calculate()` liefert ausschließlich `feature_store_payload` – keine Rendering-Keys mehr (`hit_circles`, `show_circles`, `circle_color_std`, `circle_color_active`); `status_info` liegt als Feature-Daten in `metadata["statistics"]`.
  * Die Keys existieren nur noch dort, wo sie architektonisch hingehören: im Indikator-Schema `chart/indicators/fixed_grid_proximity.py` (UI-Styling) sowie in Kommentaren/Docstrings (Dokumentation der Entkopplung).
* **Punkt 2 – DB- & Preset-Bereinigung: ABGESCHLOSSEN (finale Bereinigung durchgeführt).**
  * *Automatischer Puffer:* `analytics/engine/schema_migrator.py` entfernt veraltete Keys transparent im Speicher (verifiziert durch Code-Inspektion).
  * *Finale Bereinigung:* Einmaliges Skript (`test/cleanup_p16_legacy_rendering_keys.py`, danach gemäß Ergänzung 4 entfernt) bereinigte 1 Zeile – Set „test" (`grid_lines`-params: `show_lines` + `line_color`). Read-only-Verifikation danach: exakte Key-Prüfung über `service_sets`/`service_sets_trash`/`indicator_presets` → KEINE Legacy-Keys mehr.
* **Punkt 3 – Verifikation & Test-Cleanup: ABGESCHLOSSEN.**
  * `test/check_p16_s1_decoupling.py`: 31/31 Checks PASS (G1–G11, P1–P10, I1–I16; I14–I16 liefen über den Rohdaten-Fallback, da `data/analytics.duckdb` während des Checks von der laufenden App gelockt war).
  * `python -m py_compile` der 5 betroffenen Dateien (`grid_lines_service.py`, `proximity_service.py`, `schema_migrator.py`, `service_set_repository.py`, `fixed_grid_proximity.py`): OK.
  * Test-Cleanup gemäß Entscheidung (Ergänzung 4): `test/` aufgeräumt, verbleibend `test/test.py`.

## Implementierungs-Log

- **16.01.02 – Nachgelagerte Arbeiten (Prüfstand, Entscheidungen & Abschluss)**
  - Datum/Uhrzeit: 06.08.2026 14:43 / 14:50 (MD)
  - Entscheidungen Benutzer:
    1. **Finale DB-Bereinigung** durchführen (nicht nur Puffer).
    2. **Tests werden nicht aufbewahrt** – nach Abschluss jedes Phasenkapitels wird der Ordner `test/` aufgeräumt (nur `test/test.py` bleibt) → als neue Architektur-Invariante 10 (Ergänzung 4) dokumentiert.
  - Umgesetzt:
    * Prüfung der drei Punkte von 16.01.02 gegen den Ist-Stand (Code-Inspektion, Tests, DB-Zugriff).
    * Punkt 1 als bereits durch P16.01 umgesetzt bestätigt (kein Code-Aufwand mehr).
    * Punkt 2: Einmaliges Skript `test/cleanup_p16_legacy_rendering_keys.py` → finale DB-Bereinigung (1 Zeile: Set „test", `grid_lines`-params `show_lines`/`line_color` entfernt); Read-only-Verifikation: exakte Key-Prüfung über `service_sets`/`service_sets_trash`/`indicator_presets` → KEINE Legacy-Keys mehr.
    * Punkt 3: Verifikation ausgeführt (31/31 PASS + py_compile OK); danach `test/`-Cleanup gemäß Entscheidung 2 (25 Dateien entfernt, nur `test.py` verbleibt).
  - Validierung: `test/check_p16_s1_decoupling.py` (31/31 PASS); `python -m py_compile` (5 Dateien OK); DB-Read-only-Check (keine Legacy-Keys).
  - Abgeschlossen: 16.01.02 vollständig erledigt (Code, DB, Verifikation, Test-Cleanup, Doku).

