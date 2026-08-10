# Phase 19: Analytics-Finalisierung

## 1. Allgemeine GrundsÃ¤tze & Architektur-Invarianten (Phase 19)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase19_step1`, `phase19_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) Ã¼ber gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Codebase-Formatierung:** Exakt **4 Leerzeichen** EinrÃ¼ckung (PEP8-Standard) und **exakt 1 Leerzeile** Spacing zwischen Methoden und FunktionsblÃ¶cken. Kein Umformatieren unbeteiligter Altbestand-Dateien.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`. `MasterTree`-Selektionen Ã¼bergeben aufgelÃ¶ste `feature_ids` direkt an `view_model.set_feature_ids()`.
5. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei Ã¼ber Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkulÃ¤re AbhÃ¤ngigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei Ã¼ber den Thread-local `DbPool` (`db/db_pool.py`) â€“ eine Verbindung pro Thread und DB-Datei. Die Fassade `db_service.py` bleibt als Re-Export-Wrapper fÃ¼r bestehende Caller erhalten.
7. **Tree-Persistenz & Kollisionsschutz (18.01.03):** 
   - Standalone-Service-Parameter nutzen exklusiv `plugin_params_<id>`.
   - Ordner-Kategorie-Overrides fÃ¼r Plugins nutzen exklusiv `plugin_category_<id>`.
   - Ordner-Kategorien fÃ¼r Service-Sets werden additiv im `category`-Feld der `ServiceSetDefinition` / des `save_set()`-Payloads persistiert.
8. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
9. **Concurrency-Guard & Timer-Pausierung:** Solange im ServiceWindow intensive Service-Berechnungen laufen (`ServiceRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
10. **Isolierter Test-Workspace & Cleanup:** Neue Test-Skripte und temporÃ¤re `*.duckdb`-Dateien gehÃ¶ren strikt nach `test/`. Nach Abschluss jedes Phasenkapitels wird `test/` aufgerÃ¤umt â€“ es verbleibt nur der Test-Harness `test/test.py`.
11. **Open/Closed-Principle & Code-Preserving:** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelÃ¶scht werden; bestehende Kern-Klassen bleiben geschÃ¼tzt.
12. **Naming Conventions & PineScript-Input-Zone:** 
    - Services in `analytics/features/definitions/` nutzen strikt das PrÃ¤fix `srv_` (`plugin_id = "srv_..."`).
    - Indikatoren in `chart/indicators/` nutzen strikt das PrÃ¤fix `ind_` (`indicator_id = "ind_..."`).
    - FÃ¼llwÃ¶rter (`service`, `plugin`, `indicator`) entfallen im Dateinamen.
    - Das `parameter_schema` liegt direkt am Dateianfang unter dem Header-Docstring.
    - Jedes Service-Plugin deklariert `metadata["category"]` fÃ¼r die dynamische Kategorie-Ordner-Struktur im MasterTree.


---

# 20.05 Architektur-Konzept: Ultra-Low-Latency Control & Rendering Pipeline

> **Status:** Verbindlich neu gefasst für sofortige, latenzfreie UI-Bedienung.
> **Primäres Ziel:** Absolut latenzfreie Bedienung aller Steuerelemente (Aggregationen, Dropdown-Checklisten, Profil-Speicherung, Workspace-Mechanismus, ServicePicker-Haken) unabhängig von Datenbank-Ladezeiten und Grafik-Rendern.

Prämissen:

1. **Latenzfreie Control-Schicht (Optimistic UI):** Jede Benutzeraktion an Bedienelementen schlägt *sofort* im lokalen State (ViewModel) durch und wird *sofort* optisch dargestellt. Es gibt keine Blockaden durch DB-Abfragen im Hauptthread.
2. **Vollständige Erhaltung der Historie:** Die gesamte Speicher-/Restore-Logik für Fenster, Workspaces und Profile bleibt über das State-Management (`StateManager`, Repositories) lückenlos intakt.
3. **Isolierte Grafik-Welt:** Slider-Aktionen, Maus-Zooms oder Canvas-Neuaufbauten triggern *nur* die visuelle Darstellung (Rendering-Welt). Sie manipulieren niemals das State-Management oder die Event-Logik der Controls.
4. **Asynchrone Datennachführung:** Daten-Queries und Canvas-Renderings laufen asynchron über Worker-Threads. Sie „beobachten“ den aktuellen Control-State, blockieren ihn aber zu keinem Zeitpunkt.

---

## 1. Die entkoppelten Drei-Welten-Architektur

```
 ┌───────────────────────────────────────────────────────────┐
 │ 1. CONTROL- & INPUT-WELT (Latenzfrei, Sofort-Feedback)    │
 │    - Dropdowns, Checklisten, ServicePicker, Profile       │
 │    - Aktualisiert den lokalen VM-State in Mikrosekunden   │
 └─────────────────────────────┬─────────────────────────────┘
                               │ (Direktes State-Update & Sofort-Sync)
                               ▼
 ┌───────────────────────────────────────────────────────────┐
 │ 2. PERSISTENZ- & STATE-WELT (ViewModel & Repositories)    │
 │    - Verwaltet Profile, Workspaces, Instanzen (DuckDB)    │
 │    - Dispatcht asynchrone Background-Worker               │
 └─────────────────────────────┬─────────────────────────────┘
                               │ (Asynchrone Payloads & no_data_variants)
                               ▼
 ┌───────────────────────────────────────────────────────────┐
 │ 3. RENDERING-WELT (Canvas, Charts & UI-Pages)             │
 │    - Zeigt Daten an, verarbeitet Zooms & Maus-Aktionen     │
 │    - Völlig unabhängig von der Bedienbarkeit der Controls │
 └───────────────────────────────────────────────────────────┘

```

---

## 2. Die Regeln für latenzfreie Bedienelemente (Control-Logik)

* **Keine Hauptthread-DB-Abfragen beim Klick:** Methoden wie `resolve_no_data_variants()` oder komplexe Validierungen laufen *niemals* synchron im Hauptthread, wenn der Anwender eine Checkbox klickt oder ein Dropdown bedient. Sie wurden in den asynchronen `QUERY_FEATURES`-Worker verlagert.
* **Sofortige UI-S وَRTPU (Optimistic Local State):** Ein Klick im ServicePicker ändert *sofort* den internen Zustand im ViewModel und schaltet das Control um. Das ViewModel emittiert ein leichtgewichtiges Signal (`feature_ids_changed` oder `params_restored` mit blockierten Signalen via `blockSignals(True)`), damit verbundene Combos ohne Wartezeit aktualisiert werden.
* **Getrennte Grafik-Interaktionen:** Interagiert der Anwender mit dem Canvas (z. B. Zoom, Ausschnitt verschieben, Chart-Skalierung), verarbeitet die Rendering-Welt das *lokal*. Das ViewModel bekommt davon nichts mit, es sei denn, es handelt sich um eine finale Bereichs-Auswahl. Das verhindert das gegenseitige Aufschaukeln von Event-Schleifen.

---

## 3. Behebung der Persistenz- & Varianten-Lücken (Bugs 3 & 4)

### Bug 3: Lückenlose Varianten-Persistenz (Clones & `instance_hashes`)

* **Problem:** `instance_hashes` wurden im Profil-Payload (`_current_payload()`) vergessen, wodurch beim Laden von Profilen die feingranularen Clone-Auswahlfilter verloren gingen.
* **Umsetzung:**
1. `_current_payload()` sichert `instance_hashes` in der `sources`-Sektion ab.
2. `_apply_profile()` und `restore_workspace()` nutzen einen gemeinsamen Helfer (`_restore_params_from_payload`), der fehlende Keys in Alt-Profilen strikt auf `[]` zurücksetzt (kein Mitschleppen alter Hashes).
3. `_save_workspace` sichert Parameter als saubere flache Kopie (`dict(...)` mit `list(...)`), um jegliches Python-Dict-Aliasing auszuschließen.



### Bug 4: Asynchrone "(No Data)"-Erkennung ohne UI-Latenz

* **Problem:** Der Versuch, fehlende Datenvarianten synchron während des UI-Aufbaus im Hauptthread zu berechnen, führte zu UI-Hängern und verdeckten Fehlern.
* **Umsetzung:**
1. **Worker-Auslagerung:** Die Ermittlung von `no_data_variants` läuft ausschließlich im asynchronen `QUERY_FEATURES`-Worker (eigener Thread, eigene DB-Connection).
2. **Snapshot-Übergabe:** Das ViewModel übergibt einen leichten, rein im RAM liegenden Preset-Snapshot (`_no_data_presets_snapshot()`) an die Query-Parameter.
3. **Varianten-Genauigkeit:** Der Reader prüft über `active_hashes` *nur noch* die im ServicePicker tatsächlich aktivierten Varianten, wodurch falsche "(No Data)"-Anzeigen oder das versehentliche Vorauswählen falscher Einträge im Dropdown physikalisch unmöglich werden.

---

## 4. Verbindlicher Abarbeitungsplan

| Schritt | Modul / Bereich | Beschreibung | Ziel / Auswirkung |
| --- | --- | --- | --- |
| **1. Persistenz-Sicherung (Bug 3)** | `analytics_view_model.py`, `analytics_win.py` | `instance_hashes` in `_current_payload()` aufnehmen; `_restore_params_from_payload()` für saubere Replace-Semantik bei Profilen & Workspaces; Aliasing-Schutz. | Gespeicherte Varianten-Filter überleben jeden Neustart und Profilwechsel fehlerfrei. |
| **2. Asynchrone No-Data-Pipeline (Bug 4)** | `feature_store_reader.py`, `analytics_worker.py`, `analytics_view_model.py` | Verlagerung der No-Data-Prüfung in den Async-Worker mittels Snapshot. Beseitigung aller synchronen Hauptthread-DB-Queries bei Control-Rebuilds. | Dropdowns und ServicePicker bleiben beim Anklicken absolut latenzfrei und flackern nicht. |
| **3. UI-Event-Entkopplung & Rendering** | `analytics_win.py`, Pages, Widgets | Entfernen von `refresh_all()` aus VM-Restores. Zentrales UI-Sync mit `blockSignals(True)`. Trennung von Grafik-Mausaktionen und Control-State. | Canvas-Neuaufbauten oder Zooms stören niemals die Steuerelemente; Seitenwechsel laden bedarfsgesteuert (Lazy). |
| **4. Headless-Verifikation** | `test/check_round11.py` | Statische Syntax-Prüfung (`py_compile`), reine Backend-Logik-Tests für Profile, Hashes und Async-Payloads (**keine GUI-Tests**). | Technische Absicherung der Pipeline ohne UI-Overhead. |


---

