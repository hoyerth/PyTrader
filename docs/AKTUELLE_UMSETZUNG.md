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

# Phase 20.04: Parameter-Varianten, Instanziierung, Hash-IDs & Archivierung

## 1. Architektur & Invarianten
* **Code-Style:** Exakt 4 Leerzeichen EinrÃ¼ckung, 1 Leerzeile zwischen Methoden.
* **Testing:** **STRIKT HEADLESS** via `py_compile` & `test/test.py` (`QApplication.exec()` STRIKT VERBOTEN).
* **Entkopplung:** MVVM & IoC. MasterTree im `ServiceWindow` gekoppelt via `EventBus` (20.02/20.03).
* **Datenbank-Konsistenz:** Single Source of Truth im `ServiceSetRepository` / `FeatureStoreReader`.

---

## 1a. VollstÃ¤ndigkeitsprÃ¼fung & Bestandsaufnahme (09.08.2026, Code-Inspektion)

Verifiziert gegen den tatsÃ¤chlichen Quellcode (keine UI-AusfÃ¼hrung):

| Befund | Status | Details |
|---|---|---|
| Referenzierte Dateien existieren | âœ… | `service_models.py` (`ServiceInstanceConfig` TypedDict, total=False), `tree_builder.py` (`build_tree`), `service_selector_model.py` (`ServiceSelectorModel.build_tree`, `resolve_display_names`, `resolve_valid_feature_ids`), `analytics_view_model.py` (`resolve_service_display_name`, `set_feature_ids`), `feature_store_reader.py`, `master_tree.py`, `feature_builder.py` (`store_plugin_payload`). |
| `indicator_presets` | âœ… | Existiert in `state_manager.py` (PK `indicator_id, preset_name` + `plugin_id`/`version`/`is_active_batch`). |
| `service_sets` | âœ… | `ServiceSetRepository` (PK `set_id`, JSON-Definition, Trash/History-Tabellen). |
| `feature_store`-Schema | âœ… | PK `(symbol, timeframe, bar_time, feature_id)`; `feature_id` = `plugin_id` (Sentinel `'native'`); `created_at` mit `now()` beim Upsert. **KEINE `instance_hash`-Spalte.** |
| MasterTree-Node-Typen | âœ… | `TYPE_PLUGIN` / `TYPE_SERVICE` â€“ heute **keine** Parent-Child-Hierarchie (Service â†’ Clones); Plugins sind flache BlÃ¤tter. |
| `ServiceDescriptionEditDialog` | âœ… | Arbeitet bereits mit `ServiceInstanceConfig.description`; `doc_log` analog ergÃ¤nzbar. |
| Schreib-/Lese-Trennung | âœ… | Lesen: `FeatureStoreReader` (read-only); Schreiben: `FeatureBuilder.store_plugin_payload` (aufgerufen von `run_worker.py`, `historical_scanner.py`, `live_analyzer.py`). |
| Lese-Pfad | âœ… | `_apply_feature_filter` (WHERE feature_id IN â€¦), `feature_keys_by_service`, `fetch_last_execution_dates`, `available_feature_keys`, `set_feature_ids`/`resolve_valid_feature_ids` arbeiten ALLE mit `plugin_id` als `feature_id`. |

**Gefundene LÃ¼cken/Konflikte im Kapitel (vor den Entscheidungen):**
1. `instance_hash` vs. `feature_id` â€“ unklar, wo der Hash im `feature_store` landet (fehlende Spalte).
2. `userData "{instance_hash_oder_id}|{key}"` kollidiert mit 20.03.02/03 (`{plugin_id}|{key}`, `ALL|{key}` + `field_sources`-Expansion).
3. Hash-Definition ohne `lookback`, obwohl Â§2 den Clone mit `lookback` beschreibt â†’ Kollisionsgefahr.
4. `json_sorted(params)` nicht definiert (numpy-Typen/None/verschachtelte Dicts).
5. `purge_instance_data` im `FeatureStoreReader` â†’ verletzt Read-only-Invariante.
6. Archiv-Persistenz und Archiv-Einheit undefiniert.
7. `indicator_presets` vs. Service-Instanzen (Geltungsbereich unklar).
8. Kein Varianten-Erzeugungspfad (Clone/Duplikat) definiert.
9. Hash-Ãœbergabe an den Writer (`store_plugin_payload`) fehlt.

---

## 1b. Entscheidungen Q1â€“Q9 (verbindlich, Anwender 09.08.2026)

| ID | Entscheidung |
|---|---|
| Q1 | **`feature_id` bleibt `plugin_id`; NEUE additive Spalte `instance_hash VARCHAR` in `feature_store`.** Zero-Regression: Lese-Pfad/Alt-Profile bleiben intakt. |
| Q2 | **Dropdown:** `userData` primÃ¤r `{plugin_id}|{key}`; `instance_hash` optional im Label. Das ViewModel lÃ¶st selektierte Hashes transparent auf `feature_ids` (plugin_ids) auf. Anzeige: `{Service} ({Preset-Name}) / {Parameter}`. |
| Q3 | **`lookback` BEWUSST NICHT im Hash** â€“ Ergebnis einer Kerze hÃ¤ngt nur von Algorithmus-Logik + `params` ab; `lookback` ist ein Laufzeit-Fenster (Performance) und kein Inhalts-IdentitÃ¤tsmerkmal. |
| Q4 | **Typ-Sanitizer vor dem Hashing:** Rekursive Umwandlung in native Python-Typen (`int`, `float`, `str`, `bool`), `None`-Handling, dann `json.dumps(params, sort_keys=True)` (kanonisch). |
| Q5 | **`purge_instance_data` in `analytics/features/feature_builder.py`** (Schreib-/Store-Kontext). `FeatureStoreReader` bleibt 100 % read-only. Kein neues Repository. |
| Q6 | **`is_archived: bool` in `ServiceInstanceConfig`** + dynamischer `ðŸ“ Archiv`-Ordner im `tree_builder` (`Qt.ItemIsUserCheckable = False`). Archiv-Einheit: einzelne Instanz/Clone ODER ganze Sets. |
| Q7 | **Geltungsbereich:** PrimÃ¤r Service-Instanzen (`service_sets` + `feature_store`), additiv `indicator_presets` (Archivierung â‡’ `is_active_batch = False`, aus Scans isoliert). Â§5B adressiert beide Stores. |
| Q8 | **Varianten-Erzeugung:** KontextmenÃ¼ `Als Variante duplizieren` (Service-Knoten) + Set-Editor `Service-Instanz clonen`. Neue `instance_id`, kopierte Params, Ã¶ffnet Parameter-Editor, berechnet neuen `instance_hash`. |
| Q9 | **Writer-Ãœbergabe:** `SetEvaluator` / `HistoricalScanner` / `LiveAnalyzer` Ã¼bergeben `instance_hash` an `store_plugin_payload` â†’ neue Spalte, damit Signal-/Metrik-Ergebnisse verschiedener Clones in DuckDB getrennt und einzeln auswertbar sind. |

---

## 2. Parent-Child Modell & Hash-ID (Model C)
* **Template (Parent):** Reines Code-Template (`PluginFeature` / `plugin_id`). Nicht direkt als Instanz ausfÃ¼hren[cite: 4].
* **Executable Clone (Child):** AusfÃ¼hrbare Instanz = `plugin_id` + `params` + `lookback`[cite: 4].
* **Deterministic Hash (`instance_hash`):**
  - Short-Hash (8-stellig, hex): `SHA256(plugin_id + json_sorted(sanitized_params))[:8]`[cite: 4].
  - **`lookback` BEWUSST NICHT im Hash (Q3):** Das Kerzen-Ergebnis hÃ¤ngt nur von
    Algorithmus-Logik + `params` ab; `lookback` ist ein Laufzeit-Fenster
    (Performance) und kein Inhalts-IdentitÃ¤tsmerkmal.
  - **Typ-Sanitizer vor dem Hashing (Q4):** Rekursive Umwandlung in native
    Python-Typen (`int`/`float`/`str`/`bool`, `None`-Handling, numpy â†’ Python)
    und erst dann `json.dumps(params, sort_keys=True)` als kanonische
    Serialisierung â€“ sonst `TypeError: Object of type int64 is not JSON
    serializable` und instabile Hashes bei verschachtelten Dicts.
  - Stabile Identifikation im `feature_store` fÃ¼r Multi-Varianten-Statistiken[cite: 4]
    (neue additive Spalte `instance_hash`, Q1).
* **Negativ-Wissen (`doc_log`):** Freitextfeld pro Instanz/Preset fÃ¼r Dokumentation von FehlschlÃ¤gen[cite: 4] (z. B. *"85% false signals in chop markets"*)[cite: 4].

---

## 3. MasterTree Hierarchie & Archiv-Logik

[MasterTree (Active)]
 â”œâ”€â”€ ðŸ“ [Swing Algos]
 â”‚     â””â”€â”€ âš™ï¸ [srv_swing_pivot]
 â”‚           â”œâ”€â”€ ðŸŸ¢ [M15_Fast] (hash: #a91f3b) [X]
 â”‚           â””â”€â”€ ðŸŸ¢ [H1_Slow]  (hash: #b82e4c) [X]
 â””â”€â”€ ðŸ“ [Archiv (Checkboxes Disabled)]
       â””â”€â”€ ðŸ”´ [srv_breakout_v1] (Archiviert)
             â”œâ”€â”€ ðŸ“ Doc Log: "85% false signals in chop markets"
             â””â”€â”€ ðŸ”¹ [Default] (hash: #c73d5d) [ ] (Disabled)


### Safety & Checkbox-Regel (Archive Safety)

* Knoten im Archiv-Ordner besitzen das Flag `Qt.ItemIsUserCheckable = False`.
* Checkboxen sind schreibgeschÃ¼tzt und ausgegraut. Archivierte Hashes/IDs werden vom `AnalyticsViewModel` und von Scans (`HistoricalScanner` / `LiveAnalyzer`) strikt ignoriert.

---

## 4. Multi-Select Dropdown Integration (Kopplung mit 20.03.02/20.03.03)

* **Label-Format:** `{Service-Name} ({Preset}) / {Parameter}` (z. B. `Swing Pivot (M15_Fast) / pivot_level`).
* **UserData-Key (Q2):** PrimÃ¤r `"{plugin_id}|{param_key}"` (kompatibel zu
  20.03.02/03 inkl. `ALL|{key}`-Sammel-EintrÃ¤gen und `field_sources`-Expansion).
  `instance_hash` ist **optional im Label** (`{Preset}`), NICHT im `userData`.
* **Hash-AuflÃ¶sung (Q2):** Das `AnalyticsViewModel` lÃ¶st selektierte Hashes
  transparent auf `feature_ids` (plugin_ids) auf â€“ der Filter bleibt
  `WHERE feature_id IN (â€¦)` auf `plugin_id`-Basis.
* **Multi-Clone-Vergleich:** Erlaubt den direkten Vergleich verschiedener Parameter-Varianten desselben Services in Heatmap, Scatter und Tabellen (getrennt Ã¼ber die `instance_hash`-Spalte im `feature_store`, Q9).

---

## 5. Wartung & KontextmenÃ¼-Aktionen (Archiv)

### A. "Delete Data Only" (Daten bereinigen)

* LÃ¶scht in `analytics.duckdb` alle `feature_store`-Rows mit `instance_hash = <hash>`
  (Q1: neue Spalte; `feature_id` bleibt `plugin_id` und wird NICHT gelÃ¶scht).
* Implementierung in `analytics/features/feature_builder.py`
  (`purge_instance_data(instance_hash)`, Q5) â€“ `FeatureStoreReader` bleibt 100 %
  read-only (MVVM-Invariante).
* BehÃ¤lt MasterTree-Struktur, Parameter-Settings und `doc_log` vollstÃ¤ndig bei.

### B. "Delete Complete" (VollstÃ¤ndige LÃ¶schung)

* Zweistufige Sicherheitsabfrage (*"MÃ¶chten Sie diese Instanz inkl. aller Notizen und DB-Daten unwiderruflich lÃ¶schen?"*).
* Entfernt Preset aus `service_sets` / `indicator_presets` UND lÃ¶scht alle zugehÃ¶rigen Rows im `feature_store`.

### C. "Doc Log bearbeiten" (Negativ-Wissen)

* Ã–ffnet `ServiceDescriptionEditDialog`. Speichert Freitext in `ServiceInstanceConfig.doc_log`.



---

## 6. Schritt-fÃ¼r-Schritt Implementierung

### Schritt 0: DB-Schema (`db/schema_initializer.py`) â€“ Q1
* Additive Spalte: `ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS instance_hash VARCHAR;`
  (idempotent, bestehende Rows bleiben unangetastet â€“ `feature_id` bleibt `plugin_id`).

### Schritt 1: Model-Erweiterung (`analytics/engine/service_models.py`)

* Erweitere `ServiceInstanceConfig` TypedDict um:
* `doc_log: Optional[str]`
* `instance_hash: Optional[str]`
* `is_archived: bool` (Q6, Default False)

### Schritt 2: Hash-Gen & Baumaufbau (`analytics/engine/tree_builder.py` & `service_selector_model.py`)

* `generate_instance_hash(plugin_id, params) -> str`: Erzeuge 8-stelligen SHA256-Short-Hash
  (Q3: ohne `lookback`; Q4: Typ-Sanitizer + `json.dumps(sort_keys=True)` kanonisch).
* Erweitere `build_tree()`: Rendere Parent-Child-Struktur (`Service` $\rightarrow$ `Clones/Presets`).

* FÃ¼r Knoten mit `is_archived=True` bzw. im Pfad `/Archiv`: Setze Checkboxen auf non-checkable
  (Q6: `Qt.ItemIsUserCheckable = False`); dynamischer Ordner `ðŸ“ Archiv` statt statischem Pfad.

### Schritt 3: Dropdown-Integration (`analytics/engine/analytics_view_model.py`)

* Erweitere `resolve_service_display_name()`:
* BerÃ¼cksichtige Preset-Namen: `{Service} ({Preset_Name})`.
* Mappe `native`/`none`/kein Prefix auf `"Allgemein"`.
* Neue Resolver-Methode `resolve_instance_hashes(hashes) -> feature_ids` (Q2):
  lÃ¶st selektierte `instance_hash`-Werte transparent auf `plugin_id`-Basis auf.

### Schritt 4: Wartungs-Aktionen (`analytics/features/feature_builder.py` & `serviceui/master_tree.py`)

* `FeatureBuilder.purge_instance_data(instance_hash)`: SQL
  `DELETE FROM feature_store WHERE instance_hash = ?` (Q5; NICHT im Reader).
* In `master_tree.py`: KontextmenÃ¼-Aktionen `Data Only LÃ¶schen`, `VollstÃ¤ndig LÃ¶schen`
  und `Doc Log bearbeiten` einbinden.
* **Varianten-Erzeugung (Q8):** KontextmenÃ¼ `Als Variante duplizieren` (Service-Knoten) +
  Set-Editor `Service-Instanz clonen` â†’ neue `instance_id`, kopierte Params,
  Parameter-Editor Ã¶ffnen, `instance_hash` neu berechnen.

### Schritt 5: Writer-Ãœbergabe (Q9) â€“ `SetEvaluator` / `HistoricalScanner` / `LiveAnalyzer`

* `store_plugin_payload` um optionalen Parameter `instance_hash` erweitern; der Aufrufer
  (`set_evaluator`/Scanner/LiveAnalyzer) Ã¼bergibt den Hash der ausgefÃ¼hrten Instanz.
* SQL-Upsert schreibt `instance_hash` in die neue Spalte (nur wenn gesetzt, sonst NULL).
* Archiv-Ignoranz: `HistoricalScanner`/`LiveAnalyzer` skippen Instanzen/Presets mit
  `is_archived=True` bzw. `is_active_batch=False` (Q6/Q7).

---

## 7. Verification Checklist (`test/test.py`) â€“ 20.04 VERIFIZIERT (09.08.2026)

* [x] **Hash-Check:** `generate_instance_hash(plugin_id, params)` â€“ deterministischer
      8-stelliger SHA256-Short-Hash, Typ-Sanitizer (numpy/None/verschachtelt),
      `sort_keys=True`, ohne `lookback` (Q3/Q4). GeprÃ¼ft in
      `test/check_2004_ctxmenu.py` (Q2/Q4) und `test/check_2004_tree.py` (Q4).
* [x] **Schema-Check (Q1):** `instance_hash`-Spalte additiv/idempotent
      (`schema_initializer.py`); bestehende Rows `NULL`, `feature_id` bleibt
      `plugin_id`. GeprÃ¼ft in `test/check_2004_schema.py` (7/7).
* [x] **Hash-AuflÃ¶sung (Q2):** `resolve_instance_hashes(hashes)` liefert
      deduplizierte `plugin_ids`; Filter weiter `feature_id IN (â€¦)`.
      GeprÃ¼ft in `test/check_2004_viewmodel.py` (7/7).
* [x] **Archive Safety (Q6):** Archivierte Knoten/Clones/Sets non-checkable;
      `run_worker` Ã¼berspringt archivierte Sets/Instanzen (Q6);
      `HistoricalScanner`/`LiveAnalyzer` filtern Ã¼ber `list_active_batch_presets`
      (is_active_batch=False). GeprÃ¼ft in `test/check_2004_tree.py` (13/13) und
      `test/check_2004_writers.py` (8/8).
* [x] **Data-Purge Check (Q5):** `FeatureBuilder.purge_instance_data(instance_hash)`
      lÃ¶scht nur Rows mit dem Hash; Struktur/`doc_log` bleiben intakt;
      `FeatureStoreReader` bleibt read-only. GeprÃ¼ft in
      `test/check_2004_purge.py` (8/8).
* [x] **Varianten-Erzeugung (Q8):** KontextmenÃ¼ `Als Variante duplizieren`
      (Service-/Clone-/Plugin-Zeile) erzeugt neue Instanz/Preset-Kopie,
      kopierte Params, neuen `instance_hash` (`_duplicate_set_instance` /
      `_duplicate_preset`). GeprÃ¼ft in `test/check_2004_ctxmenu.py` (34/34).
* [x] **Writer-Ãœbergabe (Q9):** `store_plugin_payload(..., instance_hash)` schreibt
      den Hash in die neue Spalte; run_worker/HistoricalScanner/LiveAnalyzer
      Ã¼bergeben ihn. Archiv-Presets (`is_active_batch=False`) werden von Scans
      ignoriert (Q7). GeprÃ¼ft in `test/check_2004_writers.py` (8/8) und
      `test/check_2004_purge.py` (COALESCE).
* [x] **Naming-Check:** Multi-Select Dropdown formatiert `{Service} ({Preset}) / {Parameter}`
      fehlerfrei (`resolve_service_display_name`, `test/check_2004_viewmodel.py`).


---

## 8. Implementierungs-Log (09.08.2026, ~22:08; Commit `b57244b`, Tag `20.04`)

**Phase 20.04 â€“ Parameter-Varianten, Instanz-Hashes & Archivierung** â€“ alle 9
Entscheidungen Q1â€“Q9 umgesetzt. Headless-Verifikation (keine UI-Tests):
`py_compile` aller geÃ¤nderten Dateien, `test/test.py` (964 PASS / 6 Baseline-
Geometrie-FAILs unverÃ¤ndert), temporÃ¤re Checks `test/check_2004_*.py`
(alle PASS; Cleanup nach Abschluss der Phase).

### Ã„nderungen je Datei

* **`analytics/engine/service_models.py`** (Schritt 1/2a):
  * `_sanitize_for_hash()` (rekursiv â†’ native Typen, Q4) +
    `generate_instance_hash(plugin_id, params)` (8-stelliger SHA256-Short-Hash,
    ohne `lookback` Q3, `sort_keys=True`).
  * `ServiceInstanceConfig` erweitert um `instance_hash`, `doc_log`, `is_archived`;
    `ServiceSetDefinition` um `is_archived` (Q6).

* **`db/schema_initializer.py`** (Schritt 0, Q1):
  * `ALTER TABLE feature_store ADD COLUMN IF NOT EXISTS instance_hash VARCHAR`
    (additiv/idempotent; `feature_id` bleibt `plugin_id`).

* **`state_manager.py`** (Schritt 4b, Q7):
  * `indicator_presets` um Spalte `doc_log VARCHAR` erweitert (additiv).
  * `list_plugin_presets()` liefert zusÃ¤tzlich `doc_log`.
  * Neu: `set_plugin_preset_doc_log(indicator_id, preset_name, doc_log)`.
  * `save_indicator_preset()` akzeptiert optional `doc_log`.

* **`analytics/engine/service_selector_model.py`** (Schritt 2b/3, Q2/Q7):
  * `_plugin_presets` (plugin_id â†’ Clones aus `indicator_presets` via
    `StateManager.list_plugin_presets`), `_load_plugin_presets()` berechnet
    `instance_hash` + `is_archived = not is_active_batch`.
  * `build_tree()`/`plugin_presets()` reichen die Presets an den Baum durch.

* **`analytics/engine/tree_builder.py`** (Schritt 2b, Q6/Q7):
  * `ARCHIVE_LABEL = "ðŸ“ Archiv"`; Archiv-Ordner ans Sortier-Ende.
  * Plugins MIT Presets â†’ Parent-Knoten mit Clone-Kindern (`_clones_for`);
    archivierte Clones/Sets wandern in den `ðŸ“ Archiv`-Ordner.

* **`serviceui/master_tree.py`** (Schritt 2b/4b/5b, Q5/Q6/Q8):
  * Neue Rollen `ROLE_INSTANCE_HASH` (UserRole+4), `ROLE_ARCHIVED` (UserRole+5);
    neuer Knotentyp `TYPE_CLONE`.
  * `_build_clone_item`: `ðŸŸ¢/ðŸ”¹ <Preset> (#<hash>)`; aktive anhakbar, archivierte
    non-checkable; Tooltip mit Parametern + Doc-Log.
  * KontextmenÃ¼: 4 neue Signale (`data_only_purge_requested`,
    `delete_complete_requested`, `doc_log_requested`, `duplicate_variant_requested`)
    in den Branches TYPE_SERVICE / TYPE_CLONE / TYPE_PLUGIN; Archiv-Guards
    (archivierte Sets: Run/Umbenennen/HinzufÃ¼gen deaktiviert).

* **`serviceui/service_win.py`** (Schritt 4b, Q5/Q6/Q8):
  * 4 verbundene Handler + Helfer: `_on_data_only_purge`,
    `_on_delete_complete`, `_on_doc_log_requested`, `_on_duplicate_variant`,
    `_find_preset_for_hash`, `_next_preset_copy_name`, `_save_instance_doc_log`,
    `_save_plugin_doc_log`, `_delete_complete_set_instance`,
    `_delete_complete_preset`, `_duplicate_set_instance`, `_duplicate_preset`.
  * Data-Only-Purge â†’ `FeatureBuilder.purge_instance_data` (Q5); Voll-LÃ¶schen
    mit 2-stufiger Sicherheitsabfrage + P14-04-E-Sperre; Doc Log Ã¼ber
    `ServiceDescriptionEditDialog`.

* **`analytics/features/feature_builder.py`** (Schritt 4, Q5/Q9):
  * `store_plugin_payload(..., instance_hash=None)` schreibt den Hash in die
    neue Spalte; UPSERT erhÃ¤lt vorhandenen Hash via
    `COALESCE(EXCLUDED.instance_hash, feature_store.instance_hash)`.
  * Neu: `purge_instance_data(instance_hash) -> int` (Q5, FeatureBuilder,
    nicht im Reader).

* **`analytics/engine/analytics_view_model.py`** (Schritt 3, Q2):
  * `resolve_service_display_name(plugin_id, preset_name=None)` â†’
    `{Service} ({Preset})`; neu `resolve_instance_hashes(hashes)` â†’
    deduplizierte `plugin_ids`.

* **`serviceui/run_worker.py`** (Schritt 5/5b, Q6/Q9):
  * `instance_hash`-Ãœbergabe an `store_plugin_payload` (bevorzugt
    `cfg.instance_hash`, sonst `generate_instance_hash`).
  * Archiv-Guards: archivierte Sets/Instanzen werden mit Log +
    `run_finished(0)` Ã¼bersprungen.

* **`analytics/background_workers/historical_scanner.py`** und
  **`analytics/background_workers/live_analyzer.py`** (Schritt 5, Q7/Q9):
  * `instance_hash` aus `generate_instance_hash(plugin_id, preset.params)` an
    `store_plugin_payload` Ã¼bergeben; Archiv-Ignoranz via
    `list_active_batch_presets()` (is_active_batch=False ausgeschlossen).

* **`test/test.py`** (Test-Harness):
  * 5 `feature_store`-Temp-Tabellen um `instance_hash VARCHAR` ergÃ¤nzt;
    `_FakeFB.store_plugin_payload` um `instance_hash`-Kwarg erweitert.

### TemporÃ¤re Checks (nach Phasenabschluss Cleanup)

* `test/check_2004_schema.py` (7/7), `test/check_2004_tree.py` (13/13),
  `test/check_2004_viewmodel.py` (7/7), `test/check_2004_purge.py` (8/8),
  `test/check_2004_ctxmenu.py` (34/34), `test/check_2004_writers.py` (8/8).

---

## 8a. Implementierungs-Log â€“ Bugfix Q8 â€žAls Variante duplizieren zeigt kein Ergebnis" (09.08.2026, Commit `0a1baea`)

**Problem:** `Als Variante duplizieren` schrieb korrekt in die DB (Set-Instanz- und
Clone-Pfad verifiziert), lieferte aber KEIN sichtbares Ergebnis:

1. Der Parameter-Editor wurde nur bei bereits geladenem Set aktualisiert
   (Q8 verlangt â€žÃ¶ffnet Parameter-Editor").
2. Clones wurden als unsichtbares (kollabiertes) Child angelegt.
3. Namens-Bug: flaches Plugin â†’ Preset wurde `Default (Kopie)` statt `Default`
   benannt, weil `_next_preset_copy_name` auf `list_indicator_presets` zugriff,
   das den UI-Default â€žDefault" immer fabriziert.

### Ã„nderungen

* **`serviceui/master_tree.py`**:
  * Neu (public, nach `_restore_selection`): `select_instance(set_id, service_id)`
    und `select_clone(plugin_id, instance_hash)` plus gemeinsames
    `_select_by(predicate)` â€“ expandiert die Eltern-Kette (`_expand_ancestors`),
    selektiert unter `blockSignals` und scrollt in den sichtbaren Bereich.

* **`serviceui/service_win.py`**:
  * `_duplicate_set_instance`: lÃ¤dt das Ziel-Set IMMER in den Parameter-Editor
    (statt nur wenn `_current_set_id == set_id`) und selektiert die neue Instanz
    via `tree.select_instance(...)`.
  * `_duplicate_preset`: selektiert den neuen Clone via `tree.select_clone(...)`.
  * `_next_preset_copy_name(sm, plugin_id, base)`: Quelle jetzt
    `list_plugin_presets(plugin_id)` (nur echte Preset-Rows) statt
    `list_indicator_presets`; ist der Basis-Name noch GAR NICHT vergeben
    (flaches Plugin-Blatt), wird er direkt verwendet â€“ sonst
    `<base> (Kopie)`, `(Kopie 2)`, ...

### Verifikation (headless, keine UI-Tests)

* `test/check_2004_dupl3.py`: **8/8 PASS** (Set-Instanz-Pfad, Editor-Spalte,
  Baum-Selektion + Expansion, Clone-Pfad, Namens-Fix) â€“ danach Cleanup.
* `test/test.py`: 964 PASS / 6 FAIL (nur vorbestehende Geometrie-Baseline
  P2/P5/H3-H7, unverÃ¤ndert).
* `test/check_2004_ctxmenu.py` (34/34), `test/check_2004_writers.py` (8/8),
  `test/check_2004_purge.py` (8/8).
* `py_compile` + CRLF-Konsistenz (0 lone LF) aller geÃ¤nderten Dateien.
---

## 8b. Implementierungs-Log â€“ Bugfix â€žAggregation & Ergebnisparameter nicht in Fensterhistorie/Profil" (09.08.2026)

**Problem (User-Bugreport 09.08.2026, beobachtet unter â€žGenerisch"):** Nach
Fenster-Schliessen/Wiederherstellen UND bei Profilwechseln wurden die
Aggregation und die Konfiguration des Ergebnisparameter-Dropdowns (Feld) in
der generischen Heatmap NICHT wiederhergestellt. X-Achse, Y-Achse und der
Metrik-/Modus-Selektor blieben korrekt. Die Werte WURDEN gespeichert
(Workspace `instance_states.workspace_state` und Profil-Payload
`charts.heatmap` enthalten `heatmap_agg`/`heatmap_field` vollstÃ¤ndig) â€“ der
Restore-Verlust entstand in der UI-Sync-Schicht.

**Root Cause (Timing-Problem beim App-Start):**

1. `attach_view_model()` laeuft VOR `restore_workspace()`/`_apply_profile()` â€“
   die Combos werden beim Start mit Defaults/leerem Zustand befuellt.
2. Der Restore setzt NUR die VM-Params â€“ die UI-Combos werden nicht neu
   synchronisiert (kein `_sync_from_params()`-Aufruf nach dem Restore).
3. Der erste Daten-Payload ruft `_sync_combos_from_payload()`:
   * X-/Y-Achse und Aggregation werden aus dem Payload gesetzt â€“ der Payload
     reflektiert die restaurierten Params â†’ bleiben korrekt.
   * `prev_field` wurde aus `self._combo_field.currentData()` (leer beim
     Start) abgeleitet statt aus dem Payload-`field` â†’ fiel auf den ersten
     verfuegbaren Key (`is_hit` statt `visit_pct`).
   * Der E6-Loop (`_apply_config` bei AVG/SUM/MIN/MAX) ueberschrieb
     `heatmap_field` AKTIV mit dem falschen Key.
4. Dasselbe Divergenz-Muster bei der Aggregation: Ein veralteter/erster
   Payload (Initial-Query mit Default-Params) konnte die Aggregations-Combo
   auf `confluence_count` zurueckstellen; sobald der User danach ein Control
   anfasste, las `_apply_config` die Combo (falscher Wert) und ueberschrieb
   `params["heatmap_agg"]`.

**Loesung (Variante A + B + D, wie empfohlen):**

* **`analytics/ui/heatmap_widget.py`** â€“ `_sync_combos_from_payload()` (A+B):
  `agg` und `prev_field` bevorzugen jetzt primaer den Daten-Payload
  (`data.get("agg")` / `data.get("field")`), sekundaer die restaurierten
  VM-Params (`heatmap_agg`/`heatmap_field`) und erst am Ende den
  Combo-Zustand. Der E6-Loop laesst einen restaurierten Wert unangetastet.

* **`analytics/engine/analytics_view_model.py`** (D):
  Neues Signal `params_restored = Signal()` (MVVM-konform, kein UI-Import).
  Emission am Ende von `_apply_profile()` (deckt Profilwechsel +
  `load_profiles()`) und `restore_workspace()` (deckt Fenster-Schliessen/
  Wiederherstellen).

* **`analytics/ui/heatmap_widget.py`** â€“ `attach_view_model()` (D):
  Verbindet `params_restored` mit dem bereits vorhandenen
  `_sync_from_params()` (defensiv per `hasattr` fuer Test-Mocks). Dadurch
  stehen die UI-Combos sofort nach dem Restore synchron zu den
  VM-Parameters; Signale bleiben blockiert â†’ kein Query-Loop.

**Verifikation (headless, keine UI-Tests):**

* `test/check_2004_timing.py`: **3/3 PASS** (vorher 1/3 â€“ FAIL
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

## 8c. Implementierungs-Log â€“ Bugfix Varianten-Anzeige/-Anlage/-Umbenennung (10.08.2026)

**Problem (User-Bugreport 10.08.2026, analytics_win / Service-Picker):** Drei
Schwaechen im MasterTree-Varianten-Konzept (20.04):

1. **Varianten-Anzeige:** Clone-Zeilen zeigten die technische ID (`#<hash>`)
   statt des letzten Ausfuehrungsdatums; der Plugin-Parent-Knoten trug
   zusaetzlich ein eigenes Ausfuehrungsdatum, das mit den Varianten-Daten
   verwechselbar war.
2. **Varianten-Anlage:** 'Als Variante duplizieren' vergab den Namen stumm
   ueber das Auto-Schema ('<base> (Kopie)') â€“ ein neuer Name MUSS vom User
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
    {instance_hash: 'DD.MM.JJ'}]` â€“ `MAX(created_at) GROUP BY
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
  * `_build_clone_item`: Label `ðŸŸ¢/ðŸ”¹ <Preset> (DD.MM.JJ)` â€“ Hash entfaellt,
    Datum der letzten Ausfuehrung dieser Variante direkt am Namen.
  * Neues Signal `rename_variant_requested(plugin_id, instance_hash,
    new_name)`; `_on_rename_clone(item)` fragt den neuen Namen via
    `QInputDialog` ab (vorbelegt mit `ROLE_PRESET_NAME`) und emittiert das
    Signal. Kontextmenue-Branch TYPE_CLONE: Aktion 'Variante umbenennen'
    (bei archivierten deaktiviert).

* **`state_manager.py`** (V3):
  * Neu: `rename_indicator_preset(indicator_id, old_name, new_name)` â€“
    `UPDATE indicator_presets SET preset_name = ? WHERE indicator_id = ?
    AND preset_name = ?`. Alle weiteren Spalten bleiben unangetastet; der
    Aufrufer prueft vorher auf Kollisionen (Unique-Constraint).

* **`serviceui/service_win.py`** (V2/V3):
  * Verbindung `rename_variant_requested` -> neuer Handler `_on_rename_variant`
    (Kollisionspruefung via `list_plugin_presets`, Persistenz via
    `rename_indicator_preset`, Live-Sync via `event_bus.service_set_changed`).
  * `_duplicate_preset`: `QInputDialog` 'Name fuer die neue Variante (aus
    '<base>')' â€“ vorbelegt mit dem freien Kopiernamen; Leer-/Abbruch-Guard
    und Kollisionspruefung vor `save_indicator_preset`.

* **`serviceui/service_selector_dialog.py`** (V2/V3):
  * Gleiche Verkabelung fuer den Analytics-Datenquellen-Picker:
    `_on_rename_variant` (QMessageBox-basiert) + Namensdialog in
    `_duplicate_preset`.

### Verifikation (headless, keine UI-Tests)

* `test/check_variant_bugfix.py`: **17/17 PASS** â€“ per-Hash-Daten (1a-1d),
  Clone-`last_execution` im Baum (2a-2c), MasterTree-Labels (3a-3e:
  Parent ohne Datum, Clone mit Datum ohne Hash, ROLE_PRESET_NAME, flaches
  Blatt-Regression, Archiv-Clone), `rename_indicator_preset`-Persistenz
  (4a-4d). Temp-Verzeichnisse danach entfernt.
* Real-Modell-Integration (offscreen): `ServiceSelectorModel` laedt Presets
  mit `last_execution` aus dem echten Feature-Store (z. B.
  `srv_swing_volume_profile` -> 'Default'/'Default (Kopie)' mit
  `exec=10.08.26`).
* `py_compile` + CRLF-Konsistenz (0 lone LF) aller geaenderten Dateien.

---

## 8d. Implementierungs-Log - Bugfix UI-Splitter/Dropdown/Save-Restore-Pipeline (10.08.2026)

**Problem (User-Bugreport 10.08.2026, Runden 2-4):** Sechs Punkte aus den
Analytics-UI-Bugfix-Runden nach 20.04 (Varianten-Params, Dropdown-Hitbox,
Splitter, Save-Collapse, Slider, Log-Hoehe) sowie vier Punkte der
Save/Restore-Pipeline (nested heatmap, Picker-Live-Filter, UI-Sync nach
Restore, Profil-Restore).

### Runde 2: Varianten-Params, Dropdown-Hitbox, UI-Splitter

* **Bug 1 (Varianten-Params):** Klick auf einen Clone-Knoten (Preset/
  Variante) lud die GLOBALEN Standalone-Parameter statt der
  presetspezifischen Params; Save schrieb in global_settings statt in das
  Preset (indicator_presets).
  * `serviceui/service_win.py`: `_current_preset_editing`,
    `_load_clone_editor()` (Clone-Klick -> presetparams laden), Save via
    `save_indicator_preset`.
  * `serviceui/service_selector_dialog.py`: `_entries_for_scope` liefert
    `preset_params` + `preset`; `_DialogParamHost._save_plugin_params`
    Preset-Branch (schreibt in indicator_presets statt
    plugin_params_<id>, is_active_batch/doc_log bleiben erhalten);
    `_current_preset_editing` im Host + Ruecksetz im Panel-Rebuild.

* **Bug 2 (CheckableComboBox-Hitbox):** Klick auf die LineEdit-Flaeche der
  CheckableComboBox oeffnete das Popup nicht (nur Pfeil/Rahmen).
  `analytics/ui/common.py`: `lineEdit().installEventFilter(self)`,
  Event-Filter (LineEdit-Klick togglet das Popup) +
  `mousePressEvent`-Override (Box/Rahmen togglet ebenfalls).

* **Bug 3 (UI-Splitter):** Tree/Sidebar waren starr fixiert
  (`setFixedWidth(300)` im Picker, `setFixedWidth(150)` im AnalyticsWindow).
  `service_selector_dialog.py`: `_splitter` (QSplitter, Tree links mit
  minWidth 180, Panel rechts, Stretch-Faktoren 0/1, nicht kollabierbar)
  statt `setFixedWidth`; `_fit_dialog_width` misst die rechte Kante
  splitter-relativ (Tree-Breite + Handle + Panel-Minimum).
  `analytics/ui/analytics_win.py`: `_body_splitter` (Sidebar minWidth 120 +
  Seiten-Stack, `setSizes([150, 1200])`).

### Runde 3: Save-Collapse, Slider, Log-Hoehe

* **Punkt 1 (Save klappt Knoten zu):** Nach einem Speichern (EventBus-
  Refresh) kollabierte jeder zugeklappte Plugin-Knoten mit Clones.
  `serviceui/master_tree.py`: `_collect_expanded_state`/`_apply_expanded_
  state` tracken jetzt auch `TYPE_PLUGIN`-Knoten MIT Kindern
  (`("plugin", plugin_id)`) - Expansion bleibt ueber Neuaufbauten erhalten.

* **Punkt 3 (Slider service_win):** Das ServiceWindow war mit
  `setMinimumWidth(960)` zu breit. `serviceui/service_win.py`:
  `setMinimumWidth(520)` statt 960, initiale Splitter-Sizes
  `main_splitter.setSizes([460, 820])`.
  `serviceui/param_columns.py`: Grow-only-`setSizes` (beim Panel-Rebuild
  waechst das Panel nur, der Tree bleibt an der User-Position).

* **Punkt 4 (Log-Hoehe):** Das Scroll-Log war zwei Zeilen zu hoch.
  `serviceui/service_win.py`: `lineSpacing() * 2 + 12` statt `* 4 + 12`.

### Runde 4: Save/Restore-Pipeline (4 Punkte)

**Analyse-Ergebnis:** Die Punkte 1 und 4 (nested heatmap-Dict aufloesen +
`params_restored` emittieren) waren bereits im ViewModel implementiert
(Commit `7ffc1f7` - `_apply_heatmap_section` in `restore_workspace()` UND
`_apply_profile()`, Emission `params_restored` in beiden Pfaden). Keine
Aenderung noetig - nur verifiziert.

* **Punkt 2 (ECHTER BUG - Check/Uncheck im ServicePicker):** Die
  `checked_changed`-Verbindung wurde in Bugfix-Runde 3 (06.08.2026)
  entfernt ("Punkte 1-7"), damit das Read-Only-Panel dem Klick folgt.
  Dadurch folgte aber AUCH der Live-Filter nicht mehr den Haken - die
  Resultatparameter-Dropdowns (heatmap field/agg) aktualisierten sich bei
  Checkbox-Aenderungen nicht. `serviceui/service_selector_dialog.py`:
  Verbindung `tree.checked_changed` -> neuer Handler `_on_checked_changed`,
  der `selection_ids_requested(checked_feature_ids())` emittiert ->
  AnalyticsWindow `_on_picker_ids_selected` -> `set_feature_ids()`.
  Das Read-Only-Panel bleibt klickgesteuert (Punkte 1-7 unveraendert).

* **Punkt 3 (UI-Sync nach Restore):** `heatmap_widget.py` verband
  `params_restored` -> `_sync_from_params` bereits, aber die
  Fenster-Ebene (AnalyticsWindow) hatte keine Verbindung.
  `analytics/ui/analytics_win.py`: `_wire_view_model()` verbindet
  `vm.params_restored` -> neuer Handler `_sync_ui_from_restored_params`
  (Sidebar-Seite via `workspace_layout.page_index` unter blockSignals,
  aktuelle Page falls `_sync_from_params` existiert, danach
  `_sync_profile_filters()` + `_sync_service_filter_button()`).

### Verifikation (headless, keine UI-Tests)

* `test/check_ui3_bugfix.py`: **19/19 PASS** (Save-Collapse-Fix
  TYPE_PLUGIN-Expansion, service_win-Slider 520/Grow-only, Log-Hoehe
  2 Zeilen).
* `test/check_variant_bugfix.py`: **17/17 PASS** (per-Hash-Daten,
  Clone-Labels, Rename-Persistenz - Runde 1).
* `test/check_variant_params_bugfix.py`: **29/29 PASS** (Varianten-Params,
  CheckableComboBox-Hitbox, QSplitter in Picker/AnalyticsWindow).
* `test/check_restore_pipeline_bugfix.py` (neu): **27/27 PASS** - P1/P4
  (nested heatmap + params_restored in restore_workspace/_apply_profile),
  P2 (Anhaken/Abhaken -> selection_ids_requested mit checked_feature_ids),
  P3 (params_restored -> Sidebar folgt page_index, Datenquellen-Button
  synchron).
* `test/check_2004_ctxmenu.py`: **34/34 PASS**, `test/check_2004_restore.py`:
  **4/4 PASS** (Regression Restore-Pipeline).
* `py_compile` aller geaenderten Dateien + CRLF-Konsistenz.
## 8e. Implementierungs-Log - Bugfix UI-Layout-Persistenz & Klick-Konflikt (10.08.2026)

**Problem (User-Bugreport 10.08.2026, Runden 5+6):** Fuenf Punkte aus den
Analytics-UI-Bugfix-Runden nach 20.04 (heatmap_mode im Profil, page_index
im Profil, Muster-/Live-Filter bei Plugin-Parent ohne Checkbox) sowie drei
Punkte der Restore-Pipeline (angehakte Services in Historie/Profil,
Check/Uncheck aktualisiert Dropdowns, ServicePicker-Waisenfenster).

### Runde 5: UI-Layout-Persistenz (3 Punkte)

* **Punkt 3 (heatmap_mode im Profil):** Der Ansichts-Modus der Heatmap-
  Seite (standard/delta) wurde beim Speichern eines Profils nicht
  persistiert und beim Restore nicht wiederhergestellt.
  `analytics/engine/analytics_view_model.py`: Neue Methode
  `set_ui_layout(layout)` (uebernimmt die UI-Layout-Sektion in
  `_workspace_layout`); `_current_payload()` erhaelt die Sektion
  `"layout"`; `_apply_profile()` legt sie in `_workspace_layout`.
  `analytics/ui/analytics_win.py`: Neue Methode `_current_ui_layout()`
  (liefert `page_index` + `heatmap_mode`); `set_ui_layout(...)` wird vor
  `save_profile()`/`create_profile()` aufgerufen; der Sync-Handler
  `_sync_ui_from_restored_params` setzt `heatmap_page.set_mode(...)`
  aus `workspace_layout.heatmap_mode` (Muster `_restore_workspace`).

* **Punkt 4 (page_index im Profil):** Die aktive Sidebar-Seite wurde im
  Profil nicht gespeichert/wiederhergestellt.
  Gleicher Mechanismus wie Punkt 3 (Sektion `"layout"` enthaelt
  `page_index`). Im Sync-Handler wird die Seite jetzt EXPLIZIT via
  `self.pages_stack.setCurrentIndex(page_index)` umgeschaltet
  (blockSignals unterdrueckt `currentRowChanged` -> `_on_page_changed`;
  ohne `setCurrentIndex` bliebe die alte Seite sichtbar).

* **Punkt 6 (Plugin-Parent ohne Checkbox):** Ein Plugin-Knoten OHNE
  Kinder (nur ein Plugin, keine Varianten) hatte keine Checkbox, konnte
  aber via Muster-/Live-Filter nicht mehr angesprochen werden.
  `serviceui/master_tree.py`: `childCount() == 0`-Guard in
  `set_checked_feature_ids` und `_sync_checked_items` - bei kinderlosen
  Plugin-Knoten wird das Item selbst statt der Kinder gesetzt (die
  `setCheckState`-Semantik mit `childCount()` schlug sonst fehl).

### Runde 6: Klick-Konflikt in der Restore-Pipeline (3 Punkte)

* **Bug 1+2 (GEMEINSAME ROOT CAUSE - Klick ueberschrieb Checkboxen):**
  Der ServicePicker hatte zwei konkurrierende Live-Filter-Pfade:
  (1) Checkbox-Pfad (seit Runde 4): `checked_changed` ->
  `_on_checked_changed` -> `selection_ids_requested(checked_feature_ids())`
  - korrekt. (2) Klick-Pfad: `master_tree.mousePressEvent` emittierte bei
  JEDEM Mausklick `selection_details` -> `_on_tree_selection_details`
  emittierte zusaetzlich `selection_ids_requested(ids)` mit dem
  Zeilen-Scope und ueberschrieb damit den angehakten Filter. Folge:
  Nach dem Anhaken von A+B genuegte ein Klick auf eine Zeile, und die
  Historie/das Profil speicherten den letzten Klick-Scope statt der Haken
  (Bug 1); die Ergebnisparameter-Dropdowns folgten dem Klick statt den
  Haken (Bug 2).
  `serviceui/service_selector_dialog.py`: Der Klick-Handler emittiert
  KEIN `selection_ids_requested` mehr (der Filter folgt ausschliesslich
  den Checkboxen); das Read-Only-Panel folgt weiterhin dem Klick
  (Punkte 1-7 unveraendert). `_resolve_selection_ids` bleibt als
  ungenutzter Bestandscode erhalten.

* **Bug 3 (ServicePicker-Waisenfenster):** Der ServicePicker-Singleton
  (`_service_dialog`, kein WA_DeleteOnClose) blieb beim Schliessen des
  AnalyticsWindow als frei bewegliches Waisenfenster haengen.
  `analytics/ui/analytics_win.py`: `closeEvent` schliesst
  `self._service_dialog.close()` vor `_save_workspace()`; das
  `destroyed`-Signal setzt die Referenz via `_on_service_dialog_destroyed`
  zurueck (RuntimeError/AttributeError abgefangen).

### Verifikation (headless, keine UI-Tests)

* `test/check_restore_pipeline_round2.py` (neu, Runde 5): **29/29 PASS** -
  Workspace- und Profil-Restore mit feature_ids, Layout-Sektion
  (heatmap_mode + page_index) in Profil-Payload und Restore, Plugin-Parent
  ohne Kinder setzt CheckState korrekt (Muster-/Live-Filter).
* `test/check_restore_pipeline_round3.py` (neu, Runde 6): **17/17 PASS** -
  Zeilen-Klick emittiert KEIN selection_ids_requested, Checkbox-Anhaken
  emittiert `[pid]`, Abhaken emittiert `[]`, Clone-Klick ohne Filter-Emit,
  destroyed-Mechanismus (Referenz auf None) + close()-Semantik ohne
  Waisenfenster, Quell-Marker fuer alle drei Fixes.
* Regressionen: `test/check_2004_ctxmenu.py` **34/34 PASS**,
  `test/check_variant_bugfix.py` **OK**, `test/check_ui3_bugfix.py`
  **19/19 PASS**.
* `py_compile` aller geaenderten Dateien + CRLF-Konsistenz.

---

## 8f. Implementierungs-Log - Bugfix Kerzen-Overlay, ServicePicker-Restore, Dropdown-Sync (10.08.2026)

**Problem (User-Bugreport 10.08.2026, Runde 7):** 5 Punkte - Kerzen-Overlay
nur bei Datum auf einer Achse, ServicePicker-Position nicht in Historie
gemerkt (restore fails), Ergebnisparameter-Dropdown nicht restored, Dropdown
nicht aktualisiert bei Check/Uncheck, Check/Uncheck nicht in Historie
gemerkt (restore fails). Der Runde-6-Fix (Klick-Pfad entfernt) war korrekt,
deckte die echten Ursachen aber nicht ab: Der Checkbox-Pfad und die
VM-Speicherkette funktionieren (headless verifiziert); die Wurzeln lagen in
der Heatmap-UI-Sync (Stale-Payloads), zwei konkurrierenden feature_ids-
Quellen (Picker vs. 'Feld'-Dropdown) und fehlender Picker-Open-Persistenz.

### Bug 1 (Kerzen-Overlay nur bei Datum auf einer Achse)

* `analytics/ui/heatmap_widget.py`: `_update_controls()` erlaubt das Overlay
  jetzt bei `date` auf der X- ODER Y-Achse (vorher hart `can_overlay =
  x_dim == "date"`). `_on_config_changed()` schaltet das Overlay nur noch
  aus, wenn `date` auf KEINER Achse liegt. `_render_overlay()` zeichnet
  vertikale Candles bei X=date (Preis auf der rechten Achse) und
  horizontale Candles bei Y=date (Preis auf einer NEUEN zweiten unteren
  Preis-Achse, `_price_axis_bottom` via `plotItem.layout.addItem(axis, 4,
  1)`); `pg.BarGraphItem` nutzt `x0`/`width` fuer horizontale Dochte/Bodies.
  Der Preis-ViewBox-Link folgt der Date-Achse (XLink vs. YLink),
  `_update_price_view()` benachrichtigt die passende Achse.

### Bug 2 (ServicePicker-Position/Restore)

* `analytics/ui/analytics_win.py`: `_save_workspace()` persistiert
  `layout.service_picker_open` (Dialog noch offen?); `closeEvent()` speichert
  den Workspace VOR dem Schliessen des Dialogs (der Zustand muss noch
  sichtbar sein). `_current_ui_layout()` persistiert den Picker-Offen-Zustand
  auch im Profil-Payload. `_restore_workspace()` und
  `_sync_ui_from_restored_params()` oeffnen den Picker nach dem Restore
  wieder - die Position stellt der Dialog selbst aus global_settings wieder
  her (Roundtrip war bereits korrekt, es fehlte nur das Wieder-Oeffnen).

### Bug 3 (Ergebnisparameter-Dropdown nicht restored)

* `analytics/ui/heatmap_widget.py` `_sync_combos_from_payload()`: Die
  Prioritaet wurde gedreht - die RESTAURIERTEN VM-Params (Workspace/Profil)
  gewinnen jetzt gegen einen Stale-Payload (Query lief VOR dem Restore mit
  Default-Params), der Payload bestaetigt nur noch die tatsaechlich
  verwendeten Werte (`agg`/`prev_field`). Der E6-Loop ueberschreibt
  `heatmap_field` nicht mehr, wenn ein gueltiger Restore-Wert im aktuellen
  Datensatz existiert (`_find_field_index`).

### Bug 4 (Dropdown nicht aktualisiert bei Check/Uncheck)

* Root Cause: ZWEI konkurrierende `feature_ids`-Quellen - ServicePicker-
  Checkboxen (`checked_changed` -> `selection_ids_requested`) UND das
  'Feld'-CheckableComboBox (`_on_field_selection_changed` ->
  `set_feature_ids`). Loesung (Single Source of Truth = Picker): Die
  `selection_changed`-Verbindung ist ENTFERNT (Bestandscode bleibt),
  `_sync_combos_from_payload()` leitet die initialen CheckStates aus dem
  aktiven `feature_ids`-Filter ab - nur Services aus dem Filter erscheinen
  angehakt; Shared-Keys nutzen die XOR-Regel (Sammel-Eintrag ALL|key deckt
  alle aktiven Quellen ab, sonst Einzel-Eintraege).

### Bug 5 (Check/Uncheck nicht in Historie gemerkt)

* Durch den Bug-4-Fix (kein feature_ids-Write-Back des Feld-Dropdowns) kann
  der Restore die gespeicherten `feature_ids` nicht mehr ueberschreiben; der
  Picker wird nach dem Restore wieder geoeffnet (Bug 2) und zeigt die
  restaurierten Haken.

### Verifikation (headless, keine UI-Tests)

* `test/check_round7_fixes.py` (neu): **28/28 PASS** - Overlay X=date UND
  Y=date (Candles, Achsen-Sichtbarkeit, ViewBox-Link, Auto-Abschaltung ohne
  date-Achse), Stale-Payload kloppt VM-Params nicht (agg/field bleiben),
  Feld-Dropdown-CheckStates folgen feature_ids (srv_a / srv_a+srv_b /
  XOR-Sammel), kein feature_ids-Write-Back, Picker-Persistenz-Quell-Marker.
* `test/check_round7_picker_runtime.py` (neu): **PASS** - echtes
  AnalyticsWindow mit Temp-DBs: Picker open -> save -> restore -> wieder
  sichtbar.
* Regressionen: `test/check_restore_pipeline_round2.py` **29/29 PASS**,
  `test/check_restore_pipeline_round3.py` **17/17 PASS**,
  `test/check_2004_ctxmenu.py` **34/34 PASS**,
  `test/check_variant_bugfix.py` **OK**, `test/check_ui3_bugfix.py`
  **19/19 PASS**, `test/check_2004_timing.py` **3/3 PASS**.
* `py_compile` aller geaenderten Dateien + CRLF-Konsistenz.

---

## 8g. Implementierungs-Log - Bugfix Runde 8: Feld-Dropdown-Restore, synchroner Check/Uncheck-Sync, Picker-Feedback-Schleife (10.08.2026)

**Problem (User-Bugreport 10.08.2026, Runde 8):** Die Runde-7-Fixes
(Commit f39cbcb) waren korrekt, aber drei Bugs bestanden fort:
(1) Das Ergebnisparameter-Dropdown (Feld) wurde bei open/restore der
Analytics-Sicht nicht zuverlaessig restauriert (Restore-Pfad erzeugte nur
Roh-Items, der naechste Payload-Rebuild warf sie wieder weg - kein
synchroner Pfad 'Params geaendert -> UI neu abgeleitet').
(2) Das Feld-Dropdown wurde bei Check/Uncheck im ServicePicker nicht
aktualisiert (set_feature_ids() hatte KEIN Signal ans Widget; das Update
lief nur ueber Debounce + serielle Worker-Kette - langsam, fragil, stale).
(3) Check/Uncheck wurde nicht in die Historie gemerkt: Beim Oeffnen des
Pickers nach einem Restore ueberschrieb die Feedback-Schleife
(set_checked_feature_ids -> checked_changed -> selection_ids_requested ->
set_feature_ids) den restaurierten Filter - Plugin-Parents MIT Clones
(Template-Knoten, non-checkable) fielen aus checked_feature_ids() und
kuerzten den Filter.

### Loesung (generisch, Single Source of Truth)

* `analytics/engine/analytics_view_model.py`: Neues Signal
  `feature_ids_changed = Signal()` - `set_feature_ids()` emittiert es nach
  `_mark_dirty()`, vor `_refresh(...)`. Neues Generations-Token
  `_restore_generation: int` - wird in `_apply_profile()` und
  `restore_workspace()` erhoeht, in `_current_params()` als
  `"restore_generation"` mitgegeben. Neue Property `restore_generation`.
* `analytics/engine/analytics_worker.py`: Spiegelt das Generations-Token
  aus den Worker-Params ins Ergebnis-Dict
  (`result["restore_generation"]`, try/except-defensiv) - die UI kann
  damit Queries, die VOR dem letzten Restore/Profil gestartet wurden, als
  stale erkennen.
* `analytics/ui/heatmap_widget.py`: Neue zentrale Methode
  `_rebuild_field_dropdown(keys, field_sources, payload_agg, payload_field)`
  - Single Source of Truth fuer das 'Feld'-Dropdown: Items aus
  Feld-Metadaten-Cache (`_field_keys`/`_field_sources`), Haken aus
  `feature_ids` (XOR-Sammel-Regel, active_ids/no_filter), Current aus
  `heatmap_field` (Restore gewinnt), E6-Feld-Nachreichung, Fallback-
  Roh-Item bei leerem Cache. SYNCHRON aus dem Datenpfad
  (`_sync_combos_from_payload`) UND dem VM-Pfad (`_sync_from_params` /
  neuer `_on_feature_ids_changed`-Handler) gerufen. `_sync_combos_from_payload`
  enthaelt einen Stale-Guard: `restore_generation`-Mismatch => Feld- und
  Agg-/Field-Metadaten bleiben unveraendert (nur x/y/agg mit VM-Prioritaet
  bestaetigt). `attach_view_model()` verbindet `feature_ids_changed` mit
  `_on_feature_ids_changed` (hasattr-Guard).
* `serviceui/master_tree.py`: `set_checked_feature_ids()` emittiert KEIN
  `checked_changed` mehr (programmatisches Set beim Oeffnen des
  Picker-Dialogs darf keine Feedback-Schleife ausloesen: checked_changed
  -> selection_ids_requested -> set_feature_ids wuerde den restaurierten
  Filter ueberschreiben). Nur Nutzer-Aktionen (`_on_item_changed`) und
  `clear_checks()` emittieren weiterhin. Plugin-Parents MIT Clones werden
  beim Reverse-Mapping weiterhin uebersprungen, die Clone-Haken folgen
  aber der plugin_id - der Filter bleibt vollstaendig erhalten.

### Verifikation (headless, keine UI-Tests)

* `test/check_round8_bug345.py` (neu): **20/20 PASS** - synchroner
  Feld-Rebuild bei Check/Uncheck (srv_a / srv_a+srv_b / srv_b, XOR-
  Sammelregel), Stale-Payload mit alter Generation kloppt restauriertes
  Feld/Agg nicht, frischer Payload (Gen == aktuell) uebernimmt Feld-
  Metadaten, set_checked_feature_ids emittiert KEIN checked_changed,
  Reverse-Mapping erhaelt Filter ueber Clone-Haken (Plugin-Parent mit
  Clones non-checkable, 2 Clone-Haken), clear_checks emittiert weiterhin.
* Regressionen: `test/check_round7_fixes.py` **28/28 PASS**,
  `test/check_round7_picker_runtime.py` **PASS**,
  `test/check_restore_pipeline_bugfix.py` **30/30 PASS** (P2-Testblock an
  die neue Semantik angepasst: programmatisches Set ohne Signal,
  Nutzeraktion via _on_item_changed), `test/check_restore_pipeline_round2.py`
  **29/29 PASS**, `test/check_restore_pipeline_round3.py` **19/19 PASS**
  (P1+2 analog angepasst), `test/check_bug345_chain.py` **15/15 PASS**,
  `test/check_bug345_stale_hook.py` **PASS**, `test/check_bugfix_0808.py`
  **PASS**.
* `py_compile` aller 4 geaenderten Dateien: EXIT=0.

---

## 8h. Implementierungs-Log - Bugfix Runde 9+10: Varianten-granularer ServicePicker-Filter, No-Data-Differenzierung, Restore-Reihenfolge (10.08.2026)

**Problem (User-Bugreport 10.08.2026, Runden 9+10):**
(1) Check/Uncheck im ServicePicker filterte nur plugin_id-granular - das
Uncheck EINER Variante (Clone) zeigte keinen Effekt, weil die
Varianten-Einschraenkung (instance_hashes) nicht durch die Kette
MasterTree -> Dialog -> Window -> ViewModel -> Worker -> Repo -> Reader-SQL
gereicht wurde.
(2) resolve_no_data_variants markierte Varianten faelschlich als
'(No Data)', wenn die Daten unter einem anderen/veralteten Hash oder ohne
Hash (NULL, Alt-Bestand) geschrieben wurden; Set-Instanz-Varianten fehlten
komplett.
(3) Restore-Reihenfolge: Queries starteten VOR der UI-Combo-Synchronisierung
(leere/alte Controls -> _current_params() None -> Queries uebersprungen).
(4) Deterministischer Initial-Load: leere Symbol-Combo fuehrte zu
set_symbol("") und uebersprungenen Initial-Queries.
(5) Geometrie-Restore pruefte nur gegen primaryScreen - Positionen auf
Monitor 2 fielen auf den Fallback zurueck.

### Loesung

* `serviceui/master_tree.py` + `serviceui/service_selector_dialog.py`:
  Neue `selection_hashes_requested`-Kette (Runde 10, Bug 1) - der Dialog
  liefert die instance_hashes der gecheckten Clone-Varianten; das Window
  reicht sie an `set_feature_ids(ids, hashes)`.
* `analytics/engine/analytics_view_model.py`: `instance_hashes` als
  `_params`-Key + `_normalize_instance_hashes()`; `set_feature_ids()` mit
  optionalem `instance_hashes`-Parameter (None = bestehende Einschraenkung
  behalten); `_current_params()` gibt die Hashes in die Query-Params.
* `analytics/engine/analytics_worker.py` + `analytics_repository.py`:
  reichen `instance_hashes` an alle 5 Daten-Repo-Methoden durch.
* `analytics/engine/feature_store_reader.py`: `_apply_feature_filter()`
  baut die Hash-Bedingung `(instance_hash IS NULL OR LOWER(TRIM(instance_hash))
  IN (...))`; `available_instance_hashes()` liefert die Hash-Menge mit
  feature_data. `resolve_no_data_variants` differenziert (Bug 2): benannte
  Variante zaehlt NUR mit exaktem Hash-Match, pids_with_data-Fallback nur
  fuer NULL-Hash-Bestand; Set-Instanz-Varianten werden ueber
  generate_instance_hash erfasst.
* `analytics/ui/heatmap_widget.py`: '(No Data)'-Hinweise zentral in
  `_rebuild_field_dropdown()` gerendert (deckt Cache-Rebuild-Pfad ab);
  Hash-Filter im Payload-Pfad.
* `analytics/engine/analytics_view_model.py` (Bug 4): REIHENFOLGE
  `params_restored.emit()` VOR `refresh_all()` in `_apply_profile()` UND
  `restore_workspace()`.
* `analytics/ui/analytics_win.py` (Bug 3): Deterministischer `_initial_load`
  - Symbol-Combo wird vor dem Restore gefuellt (idempotent), Non-Empty-
  Guards, dann load_profiles()/restore_workspace()/_on_page_changed()/
  refresh_all().
* `persistent_win.py` + `serviceui/service_selector_dialog.py` (Bug 5):
  Geometrie-Restore prueft gegen ALLE Screens (`QApplication.screens()`),
  nicht nur primaryScreen.

### Verifikation (headless, keine UI-Tests)

* `test/check_round10.py` (neu): **34/34 PASS** - Varianten-Filter-Kette
  (MasterTree -> Dialog -> VM -> Worker -> Repo -> Reader-SQL),
  No-Data-Differenzierung (exakter Hash-Match), Restore-Reihenfolge,
  Multi-Screen-Geometrie.
* Regressionen: `test/check_round9.py` **19/19 PASS**, Restore-Pipeline
  30/30+29/29+19/19 PASS, bug345-Kette 15/15 PASS, stale_hook PASS,
  check_round7_fixes 28/28 PASS, check_round8_bug345 20/20 PASS,
  picker_runtime PASS, check_bugfix_0808 PASS.
* `py_compile` aller geaenderten Dateien: EXIT=0.

## 8i. Implementierungs-Log - Bugfix Runde 11: No-Data-Auswertung in den Worker verlagert, Persistenz/Aliasing, zentrale Restore-Orchestrierung (10.08.2026)

**Problem (User-Analyse 10.08.2026, Punkte 1-5):**
(1) Kein zentraler Zustands-Sync: 3+ Quellen setzten die Controls
(params_restored -> _sync_from_params direkt im HeatmapWidget UND
_sync_ui_from_restored_params im Window; _sync_combos_from_payload im
Payload-Pfad; feature_ids_changed -> _rebuild_field_dropdown) - bis zu 3
Control-Paesse pro Restore plus Hauptthread-DB-Zugriffe.
(2) Datenvertrag-Luecke: `instance_hashes` fehlte im Profil-Payload
(Workspace-Datei persistierte die ViewModel-Referenz -> Aliasing); die
No-Data-Pruefung lief synchron im UI-Hauptthread mit verschluckten Fehlern.
(3) Restore-Pfade stiessen selbst refresh_all() an (Query-Orchestrierung
an mehreren Stellen, redundante Re-Queries).

### Loesung

* **Bug 3 (Persistenz/Aliasing):**
  - B3-1: `_current_payload()` (VM) persistiert `sources.instance_hashes`.
  - B3-2: Gemeinsamer Restore-Helper `_restore_params_from_payload()`
    (VM) fuer `_apply_profile()` UND `restore_workspace()` - fehlt
    `instance_hashes` im Payload (Alt-Payloads), ist der Filter garantiert
    leer (Replace-Semantik statt stillem Alt-Wert); uebrige Keys additiv.
  - B3-3: `_save_workspace` (Window) kopiert die VM-Params via neuem
    `_snapshot_params()` (kein Aliasing mit den Live-Params).
* **Bug 4 (No-Data in den Worker):**
  - B4-1: Synchroner `resolve_no_data_variants()`-Aufruf aus dem
    UI-Hauptthread entfernt. Neue Kette: VM `_no_data_presets_snapshot()`
    (in-memory Preset-Modell-Daten) -> `_current_params(QUERY_FEATURES)`
    -> Worker -> Repo `get_available_features(presets_data=...)` ->
    Reader `resolve_no_data_variants()` (im Worker-Thread).
  - B4-2: Payload-Vertrag `no_data_variants` IMMER vorhanden (+
    `no_data_variants_error`); UI unterscheidet loading / Erfolg+[] /
    Erfolg+[x] / Fehler ('No-Data-Pruefung konnte nicht durchgefuehrt
    werden').
  - B4-3: Generation-Guard in `_on_features_ready` (Stale-Payloads
    aelterer Restore-Generation werden verworfen).
  - B4-5: `_render_no_data_items()` filtert nach aktiven instance_hashes;
    gewaehlte No-Data-Variante bleibt zusaetzlich inline sichtbar.
* **Architektur (A1-A6):**
  - A1: `refresh_all()` aus `_apply_profile()`/`restore_workspace()`
    entfernt (kein Query mehr aus dem VM-Restore-Pfad; das Window
    orchestriert).
  - A3: Zentraler `_sync_all_pages_from_params()` (Window, genau EIN
    Durchgang); die direkte `params_restored`-Verbindung des
    HeatmapWidgets (attach_view_model) entfaellt.
  - A5: `_sync_combos_from_payload` schreibt die x/y/agg-Combos nicht
    mehr (Payload darf Controls nie ueberschreiben).
  - A6: `_on_page_changed` mit Query-Key-Pruefung (row +
    restore_generation + `_params_signature`) - kein redundanter
    Re-Query nach Restore/Sync.

### Verifikation (headless, keine UI-Tests)

* `test/check_round11.py` (neu): **35/35 PASS** - B3-1..B3-3
  (Payload-Roundtrip, Replace-Semantik, Aliasing), B4-1..B4-5
  (No-Data-Kette, Payload-Vertrag, Generation-Guard, Hash-Filter),
  A1-A6 (kein refresh_all im VM, zentraler Seiten-Sync genau 1x,
  Payload schreibt keine Controls, Query-Key-Pruefung).
* Regressionen (an neues Design angepasst): `test/check_round10.py`
  **34/34 PASS** (B4-Assertions auf A1-Vertrag: params_restored ohne
  refresh_all), `test/check_round9.py` **19/19 PASS**,
  `test/check_round7_fixes.py` **28/28 PASS** +
  `test/check_round8_bug345.py` **20/20 PASS** (Restore-Sync via
  `_sync_from_params()` statt params_restored-Verbindung, A3; Mock-VMs um
  request_features ergaenzt), Restore-Pipeline 30/30+29/29+19/19 PASS,
  bug345-Kette 15/15 PASS, stale_hook PASS, picker_runtime PASS,
  check_bugfix_0808 PASS.
* `py_compile` aller 6 geaenderten Dateien: EXIT=0.
* Commit `9bb52f4` (Runde 11), Commit `3a61790` (Runde 9+10).

---

