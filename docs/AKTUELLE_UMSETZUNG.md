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

# Phase 20.04: Parameter-Varianten, Instanziierung, Hash-IDs & Archivierung

## 1. Architektur & Invarianten
* **Code-Style:** Exakt 4 Leerzeichen Einrückung, 1 Leerzeile zwischen Methoden.
* **Testing:** **STRIKT HEADLESS** via `py_compile` & `test/test.py` (`QApplication.exec()` STRIKT VERBOTEN).
* **Entkopplung:** MVVM & IoC. MasterTree im `ServiceWindow` gekoppelt via `EventBus` (20.02/20.03).
* **Datenbank-Konsistenz:** Single Source of Truth im `ServiceSetRepository` / `FeatureStoreReader`.

---

## 1a. Vollständigkeitsprüfung & Bestandsaufnahme (09.08.2026, Code-Inspektion)

Verifiziert gegen den tatsächlichen Quellcode (keine UI-Ausführung):

| Befund | Status | Details |
|---|---|---|
| Referenzierte Dateien existieren | ✅ | `service_models.py` (`ServiceInstanceConfig` TypedDict, total=False), `tree_builder.py` (`build_tree`), `service_selector_model.py` (`ServiceSelectorModel.build_tree`, `resolve_display_names`, `resolve_valid_feature_ids`), `analytics_view_model.py` (`resolve_service_display_name`, `set_feature_ids`), `feature_store_reader.py`, `master_tree.py`, `feature_builder.py` (`store_plugin_payload`). |
| `indicator_presets` | ✅ | Existiert in `state_manager.py` (PK `indicator_id, preset_name` + `plugin_id`/`version`/`is_active_batch`). |
| `service_sets` | ✅ | `ServiceSetRepository` (PK `set_id`, JSON-Definition, Trash/History-Tabellen). |
| `feature_store`-Schema | ✅ | PK `(symbol, timeframe, bar_time, feature_id)`; `feature_id` = `plugin_id` (Sentinel `'native'`); `created_at` mit `now()` beim Upsert. **KEINE `instance_hash`-Spalte.** |
| MasterTree-Node-Typen | ✅ | `TYPE_PLUGIN` / `TYPE_SERVICE` – heute **keine** Parent-Child-Hierarchie (Service → Clones); Plugins sind flache Blätter. |
| `ServiceDescriptionEditDialog` | ✅ | Arbeitet bereits mit `ServiceInstanceConfig.description`; `doc_log` analog ergänzbar. |
| Schreib-/Lese-Trennung | ✅ | Lesen: `FeatureStoreReader` (read-only); Schreiben: `FeatureBuilder.store_plugin_payload` (aufgerufen von `run_worker.py`, `historical_scanner.py`, `live_analyzer.py`). |
| Lese-Pfad | ✅ | `_apply_feature_filter` (WHERE feature_id IN …), `feature_keys_by_service`, `fetch_last_execution_dates`, `available_feature_keys`, `set_feature_ids`/`resolve_valid_feature_ids` arbeiten ALLE mit `plugin_id` als `feature_id`. |

**Gefundene Lücken/Konflikte im Kapitel (vor den Entscheidungen):**
1. `instance_hash` vs. `feature_id` – unklar, wo der Hash im `feature_store` landet (fehlende Spalte).
2. `userData "{instance_hash_oder_id}|{key}"` kollidiert mit 20.03.02/03 (`{plugin_id}|{key}`, `ALL|{key}` + `field_sources`-Expansion).
3. Hash-Definition ohne `lookback`, obwohl §2 den Clone mit `lookback` beschreibt → Kollisionsgefahr.
4. `json_sorted(params)` nicht definiert (numpy-Typen/None/verschachtelte Dicts).
5. `purge_instance_data` im `FeatureStoreReader` → verletzt Read-only-Invariante.
6. Archiv-Persistenz und Archiv-Einheit undefiniert.
7. `indicator_presets` vs. Service-Instanzen (Geltungsbereich unklar).
8. Kein Varianten-Erzeugungspfad (Clone/Duplikat) definiert.
9. Hash-Übergabe an den Writer (`store_plugin_payload`) fehlt.

---

## 1b. Entscheidungen Q1–Q9 (verbindlich, Anwender 09.08.2026)

| ID | Entscheidung |
|---|---|
| Q1 | **`feature_id` bleibt `plugin_id`; NEUE additive Spalte `instance_hash VARCHAR` in `feature_store`.** Zero-Regression: Lese-Pfad/Alt-Profile bleiben intakt. |
| Q2 | **Dropdown:** `userData` primär `{plugin_id}|{key}`; `instance_hash` optional im Label. Das ViewModel löst selektierte Hashes transparent auf `feature_ids` (plugin_ids) auf. Anzeige: `{Service} ({Preset-Name}) / {Parameter}`. |
| Q3 | **`lookback` BEWUSST NICHT im Hash** – Ergebnis einer Kerze hängt nur von Algorithmus-Logik + `params` ab; `lookback` ist ein Laufzeit-Fenster (Performance) und kein Inhalts-Identitätsmerkmal. |
| Q4 | **Typ-Sanitizer vor dem Hashing:** Rekursive Umwandlung in native Python-Typen (`int`, `float`, `str`, `bool`), `None`-Handling, dann `json.dumps(params, sort_keys=True)` (kanonisch). |
| Q5 | **`purge_instance_data` in `analytics/features/feature_builder.py`** (Schreib-/Store-Kontext). `FeatureStoreReader` bleibt 100 % read-only. Kein neues Repository. |
| Q6 | **`is_archived: bool` in `ServiceInstanceConfig`** + dynamischer `📁 Archiv`-Ordner im `tree_builder` (`Qt.ItemIsUserCheckable = False`). Archiv-Einheit: einzelne Instanz/Clone ODER ganze Sets. |
| Q7 | **Geltungsbereich:** Primär Service-Instanzen (`service_sets` + `feature_store`), additiv `indicator_presets` (Archivierung ⇒ `is_active_batch = False`, aus Scans isoliert). §5B adressiert beide Stores. |
| Q8 | **Varianten-Erzeugung:** Kontextmenü `Als Variante duplizieren` (Service-Knoten) + Set-Editor `Service-Instanz clonen`. Neue `instance_id`, kopierte Params, öffnet Parameter-Editor, berechnet neuen `instance_hash`. |
| Q9 | **Writer-Übergabe:** `SetEvaluator` / `HistoricalScanner` / `LiveAnalyzer` übergeben `instance_hash` an `store_plugin_payload` → neue Spalte, damit Signal-/Metrik-Ergebnisse verschiedener Clones in DuckDB getrennt und einzeln auswertbar sind. |

---

## 2. Parent-Child Modell & Hash-ID (Model C)
* **Template (Parent):** Reines Code-Template (`PluginFeature` / `plugin_id`). Nicht direkt als Instanz ausführen[cite: 4].
* **Executable Clone (Child):** Ausführbare Instanz = `plugin_id` + `params` + `lookback`[cite: 4].
* **Deterministic Hash (`instance_hash`):**
  - Short-Hash (8-stellig, hex): `SHA256(plugin_id + json_sorted(sanitized_params))[:8]`[cite: 4].
  - **`lookback` BEWUSST NICHT im Hash (Q3):** Das Kerzen-Ergebnis hängt nur von
    Algorithmus-Logik + `params` ab; `lookback` ist ein Laufzeit-Fenster
    (Performance) und kein Inhalts-Identitätsmerkmal.
  - **Typ-Sanitizer vor dem Hashing (Q4):** Rekursive Umwandlung in native
    Python-Typen (`int`/`float`/`str`/`bool`, `None`-Handling, numpy → Python)
    und erst dann `json.dumps(params, sort_keys=True)` als kanonische
    Serialisierung – sonst `TypeError: Object of type int64 is not JSON
    serializable` und instabile Hashes bei verschachtelten Dicts.
  - Stabile Identifikation im `feature_store` für Multi-Varianten-Statistiken[cite: 4]
    (neue additive Spalte `instance_hash`, Q1).
* **Negativ-Wissen (`doc_log`):** Freitextfeld pro Instanz/Preset für Dokumentation von Fehlschlägen[cite: 4] (z. B. *"85% false signals in chop markets"*)[cite: 4].

---

## 3. MasterTree Hierarchie & Archiv-Logik

[MasterTree (Active)]
 ├── 📁 [Swing Algos]
 │     └── ⚙️ [srv_swing_pivot]
 │           ├── 🟢 [M15_Fast] (hash: #a91f3b) [X]
 │           └── 🟢 [H1_Slow]  (hash: #b82e4c) [X]
 └── 📁 [Archiv (Checkboxes Disabled)]
       └── 🔴 [srv_breakout_v1] (Archiviert)
             ├── 📝 Doc Log: "85% false signals in chop markets"
             └── 🔹 [Default] (hash: #c73d5d) [ ] (Disabled)


### Safety & Checkbox-Regel (Archive Safety)

* Knoten im Archiv-Ordner besitzen das Flag `Qt.ItemIsUserCheckable = False`.
* Checkboxen sind schreibgeschützt und ausgegraut. Archivierte Hashes/IDs werden vom `AnalyticsViewModel` und von Scans (`HistoricalScanner` / `LiveAnalyzer`) strikt ignoriert.

---

## 4. Multi-Select Dropdown Integration (Kopplung mit 20.03.02/20.03.03)

* **Label-Format:** `{Service-Name} ({Preset}) / {Parameter}` (z. B. `Swing Pivot (M15_Fast) / pivot_level`).
* **UserData-Key (Q2):** Primär `"{plugin_id}|{param_key}"` (kompatibel zu
  20.03.02/03 inkl. `ALL|{key}`-Sammel-Einträgen und `field_sources`-Expansion).
  `instance_hash` ist **optional im Label** (`{Preset}`), NICHT im `userData`.
* **Hash-Auflösung (Q2):** Das `AnalyticsViewModel` löst selektierte Hashes
  transparent auf `feature_ids` (plugin_ids) auf – der Filter bleibt
  `WHERE feature_id IN (…)` auf `plugin_id`-Basis.
* **Multi-Clone-Vergleich:** Erlaubt den direkten Vergleich verschiedener Parameter-Varianten desselben Services in Heatmap, Scatter und Tabellen (getrennt über die `instance_hash`-Spalte im `feature_store`, Q9).

---

## 5. Wartung & Kontextmenü-Aktionen (Archiv)

### A. "Delete Data Only" (Daten bereinigen)

* Löscht in `analytics.duckdb` alle `feature_store`-Rows mit `instance_hash = <hash>`
  (Q1: neue Spalte; `feature_id` bleibt `plugin_id` und wird NICHT gelöscht).
* Implementierung in `analytics/features/feature_builder.py`
  (`purge_instance_data(instance_hash)`, Q5) – `FeatureStoreReader` bleibt 100 %
  read-only (MVVM-Invariante).
* Behält MasterTree-Struktur, Parameter-Settings und `doc_log` vollständig bei.

### B. "Delete Complete" (Vollständige Löschung)

* Zweistufige Sicherheitsabfrage (*"Möchten Sie diese Instanz inkl. aller Notizen und DB-Daten unwiderruflich löschen?"*).
* Entfernt Preset aus `service_sets` / `indicator_presets` UND löscht alle zugehörigen Rows im `feature_store`.

### C. "Doc Log bearbeiten" (Negativ-Wissen)

* Öffnet `ServiceDescriptionEditDialog`. Speichert Freitext in `ServiceInstanceConfig.doc_log`.



---

## 6. Schritt-für-Schritt Implementierung

### Schritt 0: DB-Schema (`db/schema_initializer.py`) – Q1
* Additive Spalte: `ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS instance_hash VARCHAR;`
  (idempotent, bestehende Rows bleiben unangetastet – `feature_id` bleibt `plugin_id`).

### Schritt 1: Model-Erweiterung (`analytics/engine/service_models.py`)

* Erweitere `ServiceInstanceConfig` TypedDict um:
* `doc_log: Optional[str]`
* `instance_hash: Optional[str]`
* `is_archived: bool` (Q6, Default False)

### Schritt 2: Hash-Gen & Baumaufbau (`analytics/engine/tree_builder.py` & `service_selector_model.py`)

* `generate_instance_hash(plugin_id, params) -> str`: Erzeuge 8-stelligen SHA256-Short-Hash
  (Q3: ohne `lookback`; Q4: Typ-Sanitizer + `json.dumps(sort_keys=True)` kanonisch).
* Erweitere `build_tree()`: Rendere Parent-Child-Struktur (`Service` $\rightarrow$ `Clones/Presets`).

* Für Knoten mit `is_archived=True` bzw. im Pfad `/Archiv`: Setze Checkboxen auf non-checkable
  (Q6: `Qt.ItemIsUserCheckable = False`); dynamischer Ordner `📁 Archiv` statt statischem Pfad.

### Schritt 3: Dropdown-Integration (`analytics/engine/analytics_view_model.py`)

* Erweitere `resolve_service_display_name()`:
* Berücksichtige Preset-Namen: `{Service} ({Preset_Name})`.
* Mappe `native`/`none`/kein Prefix auf `"Allgemein"`.
* Neue Resolver-Methode `resolve_instance_hashes(hashes) -> feature_ids` (Q2):
  löst selektierte `instance_hash`-Werte transparent auf `plugin_id`-Basis auf.

### Schritt 4: Wartungs-Aktionen (`analytics/features/feature_builder.py` & `serviceui/master_tree.py`)

* `FeatureBuilder.purge_instance_data(instance_hash)`: SQL
  `DELETE FROM feature_store WHERE instance_hash = ?` (Q5; NICHT im Reader).
* In `master_tree.py`: Kontextmenü-Aktionen `Data Only Löschen`, `Vollständig Löschen`
  und `Doc Log bearbeiten` einbinden.
* **Varianten-Erzeugung (Q8):** Kontextmenü `Als Variante duplizieren` (Service-Knoten) +
  Set-Editor `Service-Instanz clonen` → neue `instance_id`, kopierte Params,
  Parameter-Editor öffnen, `instance_hash` neu berechnen.

### Schritt 5: Writer-Übergabe (Q9) – `SetEvaluator` / `HistoricalScanner` / `LiveAnalyzer`

* `store_plugin_payload` um optionalen Parameter `instance_hash` erweitern; der Aufrufer
  (`set_evaluator`/Scanner/LiveAnalyzer) übergibt den Hash der ausgeführten Instanz.
* SQL-Upsert schreibt `instance_hash` in die neue Spalte (nur wenn gesetzt, sonst NULL).
* Archiv-Ignoranz: `HistoricalScanner`/`LiveAnalyzer` skippen Instanzen/Presets mit
  `is_archived=True` bzw. `is_active_batch=False` (Q6/Q7).

---

## 7. Verification Checklist (`test/test.py`) – 20.04 VERIFIZIERT (09.08.2026)

* [x] **Hash-Check:** `generate_instance_hash(plugin_id, params)` – deterministischer
      8-stelliger SHA256-Short-Hash, Typ-Sanitizer (numpy/None/verschachtelt),
      `sort_keys=True`, ohne `lookback` (Q3/Q4). Geprüft in
      `test/check_2004_ctxmenu.py` (Q2/Q4) und `test/check_2004_tree.py` (Q4).
* [x] **Schema-Check (Q1):** `instance_hash`-Spalte additiv/idempotent
      (`schema_initializer.py`); bestehende Rows `NULL`, `feature_id` bleibt
      `plugin_id`. Geprüft in `test/check_2004_schema.py` (7/7).
* [x] **Hash-Auflösung (Q2):** `resolve_instance_hashes(hashes)` liefert
      deduplizierte `plugin_ids`; Filter weiter `feature_id IN (…)`.
      Geprüft in `test/check_2004_viewmodel.py` (7/7).
* [x] **Archive Safety (Q6):** Archivierte Knoten/Clones/Sets non-checkable;
      `run_worker` überspringt archivierte Sets/Instanzen (Q6);
      `HistoricalScanner`/`LiveAnalyzer` filtern über `list_active_batch_presets`
      (is_active_batch=False). Geprüft in `test/check_2004_tree.py` (13/13) und
      `test/check_2004_writers.py` (8/8).
* [x] **Data-Purge Check (Q5):** `FeatureBuilder.purge_instance_data(instance_hash)`
      löscht nur Rows mit dem Hash; Struktur/`doc_log` bleiben intakt;
      `FeatureStoreReader` bleibt read-only. Geprüft in
      `test/check_2004_purge.py` (8/8).
* [x] **Varianten-Erzeugung (Q8):** Kontextmenü `Als Variante duplizieren`
      (Service-/Clone-/Plugin-Zeile) erzeugt neue Instanz/Preset-Kopie,
      kopierte Params, neuen `instance_hash` (`_duplicate_set_instance` /
      `_duplicate_preset`). Geprüft in `test/check_2004_ctxmenu.py` (34/34).
* [x] **Writer-Übergabe (Q9):** `store_plugin_payload(..., instance_hash)` schreibt
      den Hash in die neue Spalte; run_worker/HistoricalScanner/LiveAnalyzer
      übergeben ihn. Archiv-Presets (`is_active_batch=False`) werden von Scans
      ignoriert (Q7). Geprüft in `test/check_2004_writers.py` (8/8) und
      `test/check_2004_purge.py` (COALESCE).
* [x] **Naming-Check:** Multi-Select Dropdown formatiert `{Service} ({Preset}) / {Parameter}`
      fehlerfrei (`resolve_service_display_name`, `test/check_2004_viewmodel.py`).


---

## 8. Implementierungs-Log (09.08.2026, ~22:08; Commit `b57244b`, Tag `20.04`)

**Phase 20.04 – Parameter-Varianten, Instanz-Hashes & Archivierung** – alle 9
Entscheidungen Q1–Q9 umgesetzt. Headless-Verifikation (keine UI-Tests):
`py_compile` aller geänderten Dateien, `test/test.py` (964 PASS / 6 Baseline-
Geometrie-FAILs unverändert), temporäre Checks `test/check_2004_*.py`
(alle PASS; Cleanup nach Abschluss der Phase).

### Änderungen je Datei

* **`analytics/engine/service_models.py`** (Schritt 1/2a):
  * `_sanitize_for_hash()` (rekursiv → native Typen, Q4) +
    `generate_instance_hash(plugin_id, params)` (8-stelliger SHA256-Short-Hash,
    ohne `lookback` Q3, `sort_keys=True`).
  * `ServiceInstanceConfig` erweitert um `instance_hash`, `doc_log`, `is_archived`;
    `ServiceSetDefinition` um `is_archived` (Q6).

* **`db/schema_initializer.py`** (Schritt 0, Q1):
  * `ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS instance_hash VARCHAR`
    (additiv/idempotent; `feature_id` bleibt `plugin_id`).

* **`state_manager.py`** (Schritt 4b, Q7):
  * `indicator_presets` um Spalte `doc_log VARCHAR` erweitert (additiv).
  * `list_plugin_presets()` liefert zusätzlich `doc_log`.
  * Neu: `set_plugin_preset_doc_log(indicator_id, preset_name, doc_log)`.
  * `save_indicator_preset()` akzeptiert optional `doc_log`.

* **`analytics/engine/service_selector_model.py`** (Schritt 2b/3, Q2/Q7):
  * `_plugin_presets` (plugin_id → Clones aus `indicator_presets` via
    `StateManager.list_plugin_presets`), `_load_plugin_presets()` berechnet
    `instance_hash` + `is_archived = not is_active_batch`.
  * `build_tree()`/`plugin_presets()` reichen die Presets an den Baum durch.

* **`analytics/engine/tree_builder.py`** (Schritt 2b, Q6/Q7):
  * `ARCHIVE_LABEL = "📁 Archiv"`; Archiv-Ordner ans Sortier-Ende.
  * Plugins MIT Presets → Parent-Knoten mit Clone-Kindern (`_clones_for`);
    archivierte Clones/Sets wandern in den `📁 Archiv`-Ordner.

* **`serviceui/master_tree.py`** (Schritt 2b/4b/5b, Q5/Q6/Q8):
  * Neue Rollen `ROLE_INSTANCE_HASH` (UserRole+4), `ROLE_ARCHIVED` (UserRole+5);
    neuer Knotentyp `TYPE_CLONE`.
  * `_build_clone_item`: `🟢/🔹 <Preset> (#<hash>)`; aktive anhakbar, archivierte
    non-checkable; Tooltip mit Parametern + Doc-Log.
  * Kontextmenü: 4 neue Signale (`data_only_purge_requested`,
    `delete_complete_requested`, `doc_log_requested`, `duplicate_variant_requested`)
    in den Branches TYPE_SERVICE / TYPE_CLONE / TYPE_PLUGIN; Archiv-Guards
    (archivierte Sets: Run/Umbenennen/Hinzufügen deaktiviert).

* **`serviceui/service_win.py`** (Schritt 4b, Q5/Q6/Q8):
  * 4 verbundene Handler + Helfer: `_on_data_only_purge`,
    `_on_delete_complete`, `_on_doc_log_requested`, `_on_duplicate_variant`,
    `_find_preset_for_hash`, `_next_preset_copy_name`, `_save_instance_doc_log`,
    `_save_plugin_doc_log`, `_delete_complete_set_instance`,
    `_delete_complete_preset`, `_duplicate_set_instance`, `_duplicate_preset`.
  * Data-Only-Purge → `FeatureBuilder.purge_instance_data` (Q5); Voll-Löschen
    mit 2-stufiger Sicherheitsabfrage + P14-04-E-Sperre; Doc Log über
    `ServiceDescriptionEditDialog`.

* **`analytics/features/feature_builder.py`** (Schritt 4, Q5/Q9):
  * `store_plugin_payload(..., instance_hash=None)` schreibt den Hash in die
    neue Spalte; UPSERT erhält vorhandenen Hash via
    `COALESCE(EXCLUDED.instance_hash, feature_store.instance_hash)`.
  * Neu: `purge_instance_data(instance_hash) -> int` (Q5, FeatureBuilder,
    nicht im Reader).

* **`analytics/engine/analytics_view_model.py`** (Schritt 3, Q2):
  * `resolve_service_display_name(plugin_id, preset_name=None)` →
    `{Service} ({Preset})`; neu `resolve_instance_hashes(hashes)` →
    deduplizierte `plugin_ids`.

* **`serviceui/run_worker.py`** (Schritt 5/5b, Q6/Q9):
  * `instance_hash`-Übergabe an `store_plugin_payload` (bevorzugt
    `cfg.instance_hash`, sonst `generate_instance_hash`).
  * Archiv-Guards: archivierte Sets/Instanzen werden mit Log +
    `run_finished(0)` übersprungen.

* **`analytics/background_workers/historical_scanner.py`** und
  **`analytics/background_workers/live_analyzer.py`** (Schritt 5, Q7/Q9):
  * `instance_hash` aus `generate_instance_hash(plugin_id, preset.params)` an
    `store_plugin_payload` übergeben; Archiv-Ignoranz via
    `list_active_batch_presets()` (is_active_batch=False ausgeschlossen).

* **`test/test.py`** (Test-Harness):
  * 5 `feature_store`-Temp-Tabellen um `instance_hash VARCHAR` ergänzt;
    `_FakeFB.store_plugin_payload` um `instance_hash`-Kwarg erweitert.

### Temporäre Checks (nach Phasenabschluss Cleanup)

* `test/check_2004_schema.py` (7/7), `test/check_2004_tree.py` (13/13),
  `test/check_2004_viewmodel.py` (7/7), `test/check_2004_purge.py` (8/8),
  `test/check_2004_ctxmenu.py` (34/34), `test/check_2004_writers.py` (8/8).

---

## 8a. Implementierungs-Log – Bugfix Q8 „Als Variante duplizieren zeigt kein Ergebnis" (09.08.2026, Commit `0a1baea`)

**Problem:** `Als Variante duplizieren` schrieb korrekt in die DB (Set-Instanz- und
Clone-Pfad verifiziert), lieferte aber KEIN sichtbares Ergebnis:

1. Der Parameter-Editor wurde nur bei bereits geladenem Set aktualisiert
   (Q8 verlangt „öffnet Parameter-Editor").
2. Clones wurden als unsichtbares (kollabiertes) Child angelegt.
3. Namens-Bug: flaches Plugin → Preset wurde `Default (Kopie)` statt `Default`
   benannt, weil `_next_preset_copy_name` auf `list_indicator_presets` zugriff,
   das den UI-Default „Default" immer fabriziert.

### Änderungen

* **`serviceui/master_tree.py`**:
  * Neu (public, nach `_restore_selection`): `select_instance(set_id, service_id)`
    und `select_clone(plugin_id, instance_hash)` plus gemeinsames
    `_select_by(predicate)` – expandiert die Eltern-Kette (`_expand_ancestors`),
    selektiert unter `blockSignals` und scrollt in den sichtbaren Bereich.

* **`serviceui/service_win.py`**:
  * `_duplicate_set_instance`: lädt das Ziel-Set IMMER in den Parameter-Editor
    (statt nur wenn `_current_set_id == set_id`) und selektiert die neue Instanz
    via `tree.select_instance(...)`.
  * `_duplicate_preset`: selektiert den neuen Clone via `tree.select_clone(...)`.
  * `_next_preset_copy_name(sm, plugin_id, base)`: Quelle jetzt
    `list_plugin_presets(plugin_id)` (nur echte Preset-Rows) statt
    `list_indicator_presets`; ist der Basis-Name noch GAR NICHT vergeben
    (flaches Plugin-Blatt), wird er direkt verwendet – sonst
    `<base> (Kopie)`, `(Kopie 2)`, ...

### Verifikation (headless, keine UI-Tests)

* `test/check_2004_dupl3.py`: **8/8 PASS** (Set-Instanz-Pfad, Editor-Spalte,
  Baum-Selektion + Expansion, Clone-Pfad, Namens-Fix) – danach Cleanup.
* `test/test.py`: 964 PASS / 6 FAIL (nur vorbestehende Geometrie-Baseline
  P2/P5/H3-H7, unverändert).
* `test/check_2004_ctxmenu.py` (34/34), `test/check_2004_writers.py` (8/8),
  `test/check_2004_purge.py` (8/8).
* `py_compile` + CRLF-Konsistenz (0 lone LF) aller geänderten Dateien.
---

## 8b. Implementierungs-Log – Bugfix „Aggregation & Ergebnisparameter nicht in Fensterhistorie/Profil" (09.08.2026)

**Problem (User-Bugreport 09.08.2026, beobachtet unter „Generisch"):** Nach
Fenster-Schliessen/Wiederherstellen UND bei Profilwechseln wurden die
Aggregation und die Konfiguration des Ergebnisparameter-Dropdowns (Feld) in
der generischen Heatmap NICHT wiederhergestellt. X-Achse, Y-Achse und der
Metrik-/Modus-Selektor blieben korrekt. Die Werte WURDEN gespeichert
(Workspace `instance_states.workspace_state` und Profil-Payload
`charts.heatmap` enthalten `heatmap_agg`/`heatmap_field` vollständig) – der
Restore-Verlust entstand in der UI-Sync-Schicht.

**Root Cause (Timing-Problem beim App-Start):**

1. `attach_view_model()` laeuft VOR `restore_workspace()`/`_apply_profile()` –
   die Combos werden beim Start mit Defaults/leerem Zustand befuellt.
2. Der Restore setzt NUR die VM-Params – die UI-Combos werden nicht neu
   synchronisiert (kein `_sync_from_params()`-Aufruf nach dem Restore).
3. Der erste Daten-Payload ruft `_sync_combos_from_payload()`:
   * X-/Y-Achse und Aggregation werden aus dem Payload gesetzt – der Payload
     reflektiert die restaurierten Params → bleiben korrekt.
   * `prev_field` wurde aus `self._combo_field.currentData()` (leer beim
     Start) abgeleitet statt aus dem Payload-`field` → fiel auf den ersten
     verfuegbaren Key (`is_hit` statt `visit_pct`).
   * Der E6-Loop (`_apply_config` bei AVG/SUM/MIN/MAX) ueberschrieb
     `heatmap_field` AKTIV mit dem falschen Key.
4. Dasselbe Divergenz-Muster bei der Aggregation: Ein veralteter/erster
   Payload (Initial-Query mit Default-Params) konnte die Aggregations-Combo
   auf `confluence_count` zurueckstellen; sobald der User danach ein Control
   anfasste, las `_apply_config` die Combo (falscher Wert) und ueberschrieb
   `params["heatmap_agg"]`.

**Loesung (Variante A + B + D, wie empfohlen):**

* **`analytics/ui/heatmap_widget.py`** – `_sync_combos_from_payload()` (A+B):
  `agg` und `prev_field` bevorzugen jetzt primaer den Daten-Payload
  (`data.get("agg")` / `data.get("field")`), sekundaer die restaurierten
  VM-Params (`heatmap_agg`/`heatmap_field`) und erst am Ende den
  Combo-Zustand. Der E6-Loop laesst einen restaurierten Wert unangetastet.

* **`analytics/engine/analytics_view_model.py`** (D):
  Neues Signal `params_restored = Signal()` (MVVM-konform, kein UI-Import).
  Emission am Ende von `_apply_profile()` (deckt Profilwechsel +
  `load_profiles()`) und `restore_workspace()` (deckt Fenster-Schliessen/
  Wiederherstellen).

* **`analytics/ui/heatmap_widget.py`** – `attach_view_model()` (D):
  Verbindet `params_restored` mit dem bereits vorhandenen
  `_sync_from_params()` (defensiv per `hasattr` fuer Test-Mocks). Dadurch
  stehen die UI-Combos sofort nach dem Restore synchron zu den
  VM-Parameters; Signale bleiben blockiert → kein Query-Loop.

**Verifikation (headless, keine UI-Tests):**

* `test/check_2004_timing.py`: **3/3 PASS** (vorher 1/3 – FAIL
  `heatmap_field='is_hit'` nach Payload + E6-`_apply_config`-Ueberschreiben).
* `test/check_2004_uiflow.py`: 6/6 PASS (User-Interaktion + Payload-Sync).
* D-Wiring-Check (headless): X/Y/Aggregations/Feld-Combos korrekt aus den
  restaurierten Params nach `params_restored`-Emission.
* `py_compile` + CRLF-Konsistenz (0 lone LF) beider geaenderten Dateien.

**Hinweis:** Die DB-abhaengigen Regressionstests (`test.py`-Baseline 964/6,
`check_2004_restore`/`snapshot`/`bugfix3`) waren zum Verifikationszeitpunkt
nicht ausfuehrbar, weil die laufende App `data/app_data.duckdb` haelt
(DB-Lock, rein umgebungsbedingt). Sie liefen in derselben Sitzung vor der
Umsetzung gruen und sind von dieser additiven Aenderung unberuehrt.
---

## 8c. Implementierungs-Log – Bugfix Varianten-Anzeige/-Anlage/-Umbenennung (10.08.2026)

**Problem (User-Bugreport 10.08.2026, analytics_win / Service-Picker):** Drei
Schwaechen im MasterTree-Varianten-Konzept (20.04):

1. **Varianten-Anzeige:** Clone-Zeilen zeigten die technische ID (`#<hash>`)
   statt des letzten Ausfuehrungsdatums; der Plugin-Parent-Knoten trug
   zusaetzlich ein eigenes Ausfuehrungsdatum, das mit den Varianten-Daten
   verwechselbar war.
2. **Varianten-Anlage:** 'Als Variante duplizieren' vergab den Namen stumm
   ueber das Auto-Schema ('<base> (Kopie)') – ein neuer Name MUSS vom User
   vergeben werden.
3. **Varianten-Rename:** Es fehlte eine 'Variante umbenennen'-Aktion im
   Kontextmenue (UPDATE auf den Primaerschluessel `(indicator_id,
   preset_name)`).

**Anforderungen (verbindlich, Anwender 10.08.2026):**

| # | Anforderung |
|---|---|
| V1 | Existiert eine Variante, haengt das letzte Ausfuehrungsdatum am Varianten-Namen (`<Preset> (DD.MM.JJ)`); die ID (`#hash`) entfaellt aus dem Label; der Plugin-Parent-Knoten zeigt KEIN Ausfuehrungsdatum mehr. |
| V2 | Beim Anlegen einer neuen Variante MUSS ein neuer Name eingegeben werden (kein stummes Auto-Naming). |
| V3 | Kontextmenue-Aktion 'Variante umbenennen' vorhanden. |

### Aenderungen je Datei

* **`analytics/engine/feature_store_reader.py`** (V1):
  * Neu (read-only, nach `fetch_last_execution_dates`):
    `fetch_last_execution_dates_by_hash() -> Dict[feature_id_lower,
    {instance_hash: 'DD.MM.JJ'}]` – `MAX(created_at) GROUP BY
    feature_id + instance_hash` ueber alle Symbole/Timeframes. Rows ohne
    `instance_hash` und der Sentinel `'native'` werden uebersprungen;
    case-insensitiv/whitespace-tolerant wie die Plugin-Variante. Defensiv:
    Fehler/Tabelle fehlt -> `{}`.

* **`analytics/engine/service_selector_model.py`** (V1):
  * Neuer State `_last_execution_dates_by_hash` (`Dict[pid_lower,
    {hash: date}]`), geladen in `refresh()` NACH den Plugin-Daten
    (`_load_last_execution_dates_by_hash()` delegiert an den
    FeatureStoreReader; Fehler -> `{}`).
  * `_load_plugin_presets()`: jedes Clone-Dict erhaelt
    `last_execution` (per-Hash-Datum, Fallback `'--.--.--'`).
  * Neu (public): `last_execution_date_for_hash(plugin_id, instance_hash)`
    -> `'DD.MM.JJ'` oder `'--.--.--'`.

* **`serviceui/master_tree.py`** (V1/V3):
  * Neue Rolle `ROLE_PRESET_NAME` (UserRole+6) traegt den Anzeigenamen eines
    Clone-Knotens (fuer den Rename-Dialog ohne DB-Lookup).
  * `_build_plugin_item`: Hat das Plugin Clones, ist das Parent-Label nur die
    Plugin-ID (KEIN Datum); flache Blaetter behalten `pid (DD.MM.JJ)`.
  * `_build_clone_item`: Label `🟢/🔹 <Preset> (DD.MM.JJ)` – Hash entfaellt,
    Datum der letzten Ausfuehrung dieser Variante direkt am Namen.
  * Neues Signal `rename_variant_requested(plugin_id, instance_hash,
    new_name)`; `_on_rename_clone(item)` fragt den neuen Namen via
    `QInputDialog` ab (vorbelegt mit `ROLE_PRESET_NAME`) und emittiert das
    Signal. Kontextmenue-Branch TYPE_CLONE: Aktion 'Variante umbenennen'
    (bei archivierten deaktiviert).

* **`state_manager.py`** (V3):
  * Neu: `rename_indicator_preset(indicator_id, old_name, new_name)` –
    `UPDATE indicator_presets SET preset_name = ? WHERE indicator_id = ?
    AND preset_name = ?`. Alle weiteren Spalten bleiben unangetastet; der
    Aufrufer prueft vorher auf Kollisionen (Unique-Constraint).

* **`serviceui/service_win.py`** (V2/V3):
  * Verbindung `rename_variant_requested` -> neuer Handler `_on_rename_variant`
    (Kollisionspruefung via `list_plugin_presets`, Persistenz via
    `rename_indicator_preset`, Live-Sync via `event_bus.service_set_changed`).
  * `_duplicate_preset`: `QInputDialog` 'Name fuer die neue Variante (aus
    '<base>')' – vorbelegt mit dem freien Kopiernamen; Leer-/Abbruch-Guard
    und Kollisionspruefung vor `save_indicator_preset`.

* **`serviceui/service_selector_dialog.py`** (V2/V3):
  * Gleiche Verkabelung fuer den Analytics-Datenquellen-Picker:
    `_on_rename_variant` (QMessageBox-basiert) + Namensdialog in
    `_duplicate_preset`.

### Verifikation (headless, keine UI-Tests)

* `test/check_variant_bugfix.py`: **17/17 PASS** – per-Hash-Daten (1a-1d),
  Clone-`last_execution` im Baum (2a-2c), MasterTree-Labels (3a-3e:
  Parent ohne Datum, Clone mit Datum ohne Hash, ROLE_PRESET_NAME, flaches
  Blatt-Regression, Archiv-Clone), `rename_indicator_preset`-Persistenz
  (4a-4d). Temp-Verzeichnisse danach entfernt.
* Real-Modell-Integration (offscreen): `ServiceSelectorModel` laedt Presets
  mit `last_execution` aus dem echten Feature-Store (z. B.
  `srv_swing_volume_profile` -> 'Default'/'Default (Kopie)' mit
  `exec=10.08.26`).
* `py_compile` + CRLF-Konsistenz (0 lone LF) aller geaenderten Dateien.
