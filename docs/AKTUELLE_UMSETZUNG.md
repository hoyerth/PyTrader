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

> **Status:** Umgesetzt und headless validiert (Runden 11–15 der Analytics-Pipeline, Stand 10.08.2026). Rein konzeptionelles Kapitel – kein Arbeitsschrittplan; die Umsetzung ist in den Runden 11–15 vollständig realisiert (Runde 15: Performance-Diagnose Dropdown – Metadaten-Cache & QUERY_FEATURES-Leichtpfad).
> **Primäres Ziel:** Absolut latenzfreie Bedienung aller Steuerelemente (Aggregationen, Dropdown-Checklisten, Profil-Speicherung, Workspace-Mechanismus, ServicePicker-Haken) unabhängig von Datenbank-Ladezeiten und Grafik-Rendern.

Prämissen:

1. **Latenzfreie Control-Schicht (Optimistic UI):** Jede Benutzeraktion an Bedienelementen schlägt *sofort* im lokalen State (ViewModel) durch und wird *sofort* optisch dargestellt. Es gibt keine Blockaden durch DB-Abfragen im Hauptthread.
2. **Vollständige Erhaltung der Historie:** Die gesamte Speicher-/Restore-Logik für Fenster, Workspaces und Profile bleibt über das State-Management (`StateManager`, Repositories) lückenlos intakt.
3. **Isolierte Grafik-Welt:** Slider-Aktionen, Maus-Zooms oder Canvas-Neuaufbauten triggern *nur* die visuelle Darstellung (Rendering-Welt). Sie manipulieren niemals das State-Management oder die Event-Logik der Controls.
4. **Asynchrone Datennachführung:** Daten-Queries und Canvas-Renderings laufen asynchron über Worker-Threads. Sie „beobachten“ den aktuellen Control-State, blockieren ihn aber zu keinem Zeitpunkt.

> **Prämissen-Check (Codebasis, 10.08.2026):** Alle vier Prämissen sind in der Implementierung verifiziert: (1) `set_feature_ids()`/Picker-Haken schlagen sofort im VM-State durch und triggern nur den Debounce-Timer – kein Hauptthread-DB-Zugriff; (2) Profile (`_current_payload()` v2-sectioned inkl. `instance_hashes`) und Workspaces (`StateManager` → `WindowStateRepository.workspace_state`, `_keep_history_on_close=True`, `INSTANCE_ID="win_analytics"`) sind lückenlos persistent; (3) Grafik-Interaktionen (z. B. `set_heatmap_zoom()`) werden rein client-seitig angewandt – kein DB-Requery, keine Event-Logik der Controls; (4) alle Daten-Queries laufen über `AnalyticsAsyncWorker` (QThread) mit Debounce-Pufferung und DbPool-Connections.

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

* **Keine Hauptthread-DB-Abfragen beim Klick:** Methoden wie die No-Data-Auswertung oder komplexe Validierungen laufen *niemals* synchron im Hauptthread, wenn der Anwender eine Checkbox klickt oder ein Dropdown bedient. Sie wurden in die asynchronen Worker-Abfragen verlagert – `QUERY_FEATURES` für das Feature-Dropdown sowie `QUERY_HEATMAP_GENERIC` für die generische Heatmap (Runde 12, Option A: No-Data-Auswertung im selben Grafik-Payload, kein zweiter serieller Roundtrip).
* **Sofortige UI-Sync (Optimistic Local State):** Ein Klick im ServicePicker ändert *sofort* den internen Zustand im ViewModel und schaltet das Control um. Das ViewModel emittiert ein leichtgewichtiges Signal (`feature_ids_changed` oder `params_restored` mit blockierten Signalen via `blockSignals(True)`), damit verbundene Combos ohne Wartezeit aktualisiert werden.
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
* **Umsetzung (Runden 11–14):**
1. **Worker-Auslagerung (Runde 11, B4-1/B4-2):** Die Ermittlung von `no_data_variants` läuft ausschließlich im Worker-Thread (eigener Thread, eigene DB-Connection) – sowohl im `QUERY_FEATURES`-Pfad als auch im `QUERY_HEATMAP_GENERIC`-Pfad (Runde 12, Option A: Auswertung im selben Grafik-Payload, damit aktualisiert sich das Dropdown mit/knapp nach der Grafik statt erst nach einem zweiten seriellen Roundtrip).
2. **Snapshot-Übergabe:** Das ViewModel übergibt einen leichten, rein im RAM liegenden Preset-Snapshot (`_no_data_presets_snapshot()`) an die Query-Parameter; die DB-Fakten (`available_instance_hashes` / `feature_keys_by_service`) ermittelt der Reader im Worker-Thread.
3. **Varianten-Genauigkeit (Runde 13/13b):** Der Reader prüft über `active_hashes` *nur noch* die im ServicePicker tatsächlich aktivierten Varianten; bei aktiver Einschränkung liefert auch eine hash-lose Variante nie "(No Data)" – falsche "(No Data)"-Anzeigen oder das versehentliche Vorauswählen falscher Einträge im Dropdown sind damit physikalisch ausgeschlossen.
4. **Alt-Bestand & leerer Filter (Runde 13c/14):** Ein leerer Datenquellen-Filter (`feature_ids=[]`) erzeugt keinerlei "(No Data)"-Einträge (der Button „Aktive Filter entfernen“ zeigt danach wieder alle Features ohne Rauschen); undifferenzierte Alt-Rows ohne `instance_hash` decken ausschließlich die Original-Variante einer `plugin_id` ab (z. B. `srv_proximity`-Altbestand) – weitere Varianten derselben `plugin_id` erscheinen weiterhin korrekt als "(No Data)", bis der erste Scan lief.

---

## 4. Ergänzende Mechanismen der Latenzfreiheit (implementiert)

* **Debounce & Query-Pufferung:** Der ViewModel puffert angeforderte Queries in `_pending_kinds` und startet sie seriell über einen Single-Shot-`QTimer` (200–300 ms). Klick-Serien erzeugen keinen Query-Stau; ein laufender Worker wird durch den nächsten Start nie abgebrochen (Race-Guard `self._worker is worker` verwirft verspätete Ergebnisse alter Worker).
* **`restore_generation` (Stale-Payload-Schutz):** Bei jedem `restore_workspace()`/`_apply_profile()` erhöht der ViewModel ein Generations-Token, das über die Query-Params in die Worker wandert und im Ergebnis gespiegelt wird. Die UI verwirft Payloads älterer Generation – Queries, die VOR einem Restore gestartet wurden, überschreiben den synchron restaurierten Zustand nicht.
* **Query-Key-Deduplizierung:** Das AnalyticsWindow fordert Seitendaten nur an, wenn sich der Query-Key ändert (Seiten-Index + `restore_generation` + Params-Signatur) – identische Anforderungen lösen keinen redundanten Re-Query aus.
* **Zentraler UI-Sync statt `refresh_all()` im Restore:** Nach `params_restored` synchronisiert das AnalyticsWindow die Seiten-Combos in genau einem Durchgang mit `blockSignals(True)` (`_sync_ui_from_restored_params` → `_sync_all_pages_from_params` → `_request_current_page_data`). `refresh_all()` bleibt nur dem expliziten User-Refresh vorbehalten.
* **UI-Zustände ohne Query:** Reine UI-Settings (Tabellen-Spaltenbreiten, Zeilenhöhe, Sortierung, Zoom-Bereiche) markieren nur das Dirty-Flag bzw. werden client-seitig angewandt – kein DB-Requery, keine Worker-Runde.
* **`busy_changed` & `missing_services_detected`:** Laufende Queries zeigen einen Spinner; fehlende (entfernte/umbenannte) Services im Restore werden gemeldet, ohne den restaurierten Filter stillschweigend zu kürzen (Graceful Degradation).

## 5. Bekannte Grenzen (bewusst unverändert)

* **Entfernter synchroner Altbestand (Runde 15):** Die ViewModel-Methode `resolve_no_data_variants(symbol, timeframe)` (synchroner Reader-Zugriff im aufrufenden Thread, zuletzt `analytics_view_model.py` ~Z. 1413) wurde in Runde 15 **entfernt** – sie hatte seit Runde 11 keinen einzigen Aufrufer mehr (der produktive Pfad läuft vollständig über den Worker-Snapshot `presets_data`). Die Open/Closed-Regel schützt aktive Logik; toter Code ohne Aufrufer ist davon ausdrücklich ausgenommen. Verifiziert über `check_round9.py`/`check_round10.py` (19/19, 34/34), die vollständig auf dem Reader-/Worker-Pfad laufen.
* **Abgrenzung der Latenzgarantie:** Die Aussage „läuft niemals synchron im Hauptthread" gilt für den tatsächlich verdrahteten Pfad (Controls → VM → Debounce → Worker) als Code-Invariante – mit dem entfernten Altbestand existiert im Analytics-Pfad kein synchroner DB-Zugriff mehr.


---

## 6. Implementierungs-Log – Runde 15: Performance-Diagnose Dropdown (10.08.2026)

**Problem (User-Meldung, 10.08.2026):** Das Analytics-'Feld'-Dropdown und die '(No Data)'-Hinweise brauchten beim Öffnen mehrere Sekunden – die Feature-Metadaten wurden erst NACH der teuren Heatmap-Pivot-Aggregation sichtbar.

**Root-Cause-Analyse (4 Engpässe):**
1. **Root Cause 1:** `QUERY_FEATURES` war deaktiviert; das Feld-Dropdown wartete auf das Grafik-Payload (`QUERY_HEATMAP_GENERIC` inkl. Pivot-Aggregation).
2. **Root Cause 2:** `feature_keys_by_service` / `available_feature_keys` / `available_instance_hashes` / `plugin_ids_with_hashes` scannten den feature_store bis zu 6× pro Update (Voll-Scans inkl. feature_data-JSON-Parsing).
3. **Root Cause 3:** Kein Caching der stabilen Metadaten (ändern sich nur bei `store_plugin_payload()`).
4. **Root Cause 4:** `feature_keys_by_service` lief je Zyklus doppelt (Dropdown + No-Data-Auswertung).

### Lösung (Fixes 1–3)

* **Fix 3 (Metadaten-Cache, `feature_store_reader.py`):** Gemeinsamer Basis-Scan `_feature_meta_base(symbol, timeframe)` – **GENAU EIN** DuckDB-Zugriff für alle 4 Metadaten-Methoden. In-Memory-Cache (`_meta_cache` + `_meta_lock`, threadsicher für die gemeinsame Reader-Instanz) mit Invalidation via `feature_cache_last_invalidated` (feature_builder, Invariante 13 – wird bei jedem `store_plugin_payload()` aktualisiert); defensiver Notausgang `invalidate_meta_cache()`. Die `feature_ids`/`instance_hashes`-Filter laufen als Python-Filter auf dem Cache (Semantik identisch zur bisherigen SQL-IN-Clause: case-insensitiv, whitespace-tolerant, NULL-Hash-Pass-through – Runde-10/13c-Vertrag unverändert).
* **Fix 1 (QUERY_FEATURES-Leichtpfad, `analytics_repository.py` / `analytics_worker.py` / `heatmap_widget.py`):** Neuer Helfer `_field_metadata(symbol, timeframe, feature_ids, instance_hashes)` → `(metrics, field_sources)`, genutzt von `get_generic_heatmap` UND `get_available_features`. Der QUERY_FEATURES-Payload trägt jetzt `metrics` + `field_sources` – das Feld-Dropdown + '(No Data)' kommen ohne die teure Heatmap-Pivot-Aggregation. `heatmap_widget.request_data()` reaktiviert `request_features()` **vor** `request_heatmap_generic()`.
* **Fix 2 (durch Fix 3 abgedeckt):** Beide Aufrufer (`_field_metadata` / `resolve_no_data_variants`) teilen sich den gecachten Basis-Scan – keine doppelte Scan-Last mehr; kein Signatur-Umbau nötig.
* **Code-Cleanup (separat committet):** Toter synchroner VM-Code `resolve_no_data_variants` (`analytics_view_model.py`, seit Runde 11 ohne Aufrufer) entfernt – siehe §5.

### Verifikation (headless, keine UI-Tests)

* `test/check_round15_perf.py` (neu): **27/27 PASS** – Basis-Scan = 1 DB-Zugriff für 4 Metadaten-Methoden, Zweitaufruf = 0 Zugriffe (Cache), Invalidation via `store_plugin_payload` (neuer Key sichtbar), Python-Filter-Semantik (case-insensitiv/whitespace, NULL-Hash-Pass-through, numeric_only-Trennung), No-Data-Semantik, QUERY_FEATURES-Leichtpfad (metrics/field_sources identisch zum Heatmap-Pfad), defensiver Notausgang.
* Regression: `check_round12.py` (23/23 – A5: `request_features()` vor `request_heatmap_generic()` in der Quelldatei), `check_round11.py` (35/35), `check_round9.py` (19/19), `check_round10.py` (34/34), `check_2004_bugfix3.py` (15/15), `check_round14.py` (8/8). `py_compile` aller geänderten Dateien OK.
* `check_round13c.py` war während der Verifikation **nicht ausführbar**: `data/analytics.duckdb` war von der laufenden App exklusiv gesperrt (PID 32608, IO-Error „File is already open") – der Test liest die echte DB und wird nach App-Ende nachgeholt.
* **Offen (manuell):** Funktions-/Latenztest des Dropdowns in der laufenden App durch den Anwender.

