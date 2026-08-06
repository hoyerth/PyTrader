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

---

# P16.01 - Architektur-Refactoring: Visualisierungs-Entkopplung

## 1. Konzept & Zielarchitektur
* **Problem (Ist-Zustand):** Backend-Services (`analytics/features/definitions/`) erzeugen Hex-Farben, Sichtbarkeits-Flags (`show_*`) und Zeichen-Objekte (`lines`, `hit_circles`). Das verletzt das Single Responsibility Principle (SRP).
* **Lösung (Soll-Zustand):**
  * **Analytics-Services:** Verarbeiten ausschließlich reine Rohdaten (Raster-Preise, Distanzen, Booleans) $\rightarrow$ liefern ausschließlich `feature_store_payload`.
  * **Indikator (`chart/indicators/fixed_grid_proximity.py`):** Verwaltet UI-Farben und Styling-Parameter $\rightarrow$ transformiert Rohdaten in `chart_render_payload`.
  * **Frontend (`chart/js/03_chart_rendering.js`):** Rendert das `chart_render_payload` auf der Canvas.

## 2. Transitions-Plan
1. **Phase 1 (Indikator):** Visualisierungs-Parameter und Payload-Erzeugung in `FixedGridProximityIndicator` verlagern.
2. **Phase 2 (Services):** UI-Parameter und Grafik-Objekte aus `grid_lines_service.py` und `proximity_service.py` entfernen.
3. **Phase 3 (Bereinigung):** Alt-Dateien löschen/bereinigen.
4. **Abwärtskompatibilität:** Der `PluginExecutor` akzeptiert weiterhin leere Grafik-Payloads von Services.

## 3. IDE-AI Schritt-für-Schritt Anleitung

### P16.01 – Entscheidungen (Konsolidierung vor Umsetzung)

 **E1 (Farb-Semantik):** Gültig ist die Implementierungs-/Label-Semantik:
 `circle_color_std` = Hit IM Zeitfenster, `circle_color_active` = Hit
 AUSSERHALB (bzw. bei inaktivem Time-Filter). P16.01 Schritt 2 wird
 entsprechend korrigiert (Formulierung „_active wenn is_time_window_active=True"
 ist falsch).

 **E2 (Level-Weitergabe):** Nach Entkopplung liefert `grid_lines_service` KEINE
 Linienliste mehr im `chart_render_payload`, schreibt aber weiterhin eine REINE
 Level-Liste (`[{price}, ...]`, ohne color/width/style) unter
 `shared_state[instance_id]`. `proximity_service` liest diese unverändert
 (depends_on). Das Render-Styling entfällt damit vollständig aus den Services.

 **E3 (Feature-Store-Schema, unverändert gültig):** `proximity`-Records bleiben
 `{bar_time, levels_hit, is_hit, in_time_window, time_window_mins,
 use_time_filter, visit_pct}`; die P16.01-Feldnamen (`nearest_level`,
 `distance`, `is_time_window_active`) werden NICHT eingeführt
 (`distance` entfällt ersatzlos). Der Indikator-Lesepfad
 `read_proximity_from_feature_store()` bleibt damit unverändert.

 **E4 (status_info):** `status_info {in_time_window, active_hits}` bleibt
 Bestandteil des `proximity`-Service-Ergebnisses (nur als Feature-Daten, KEINE
 Farben) und wird vom Indikator in `build_chart_render_payload()` übernommen.

 **E5 (Capabilities):** Beide Services setzen `"render": False`; nur der
 Indikator liefert `chart_render_payload`.

### Schritt 1: Alt-Dateien löschen
* Ordner/Datei `.backup_grid_liquidity/analytics/features/definitions/grid_liquidity.py` (falls vorhanden) löschen.

### Schritt 2: Indikator erweitern (`chart/indicators/fixed_grid_proximity.py`)
* Styling-Parameter im `parameter_schema` ergänzen: `show_lines`, `line_color`, `show_circles`, `circle_color_std`, `circle_color_active`.
* Methode `build_chart_render_payload(raw_features, ui_params)` implementieren:
  * `raw_features` = Service-Ergebnisse (`results["grid_1"]`,
    `results["prox_1"]`) + `context.shared_state["grid_1"]` (reine Level-Liste).
  * Liest die Grid-Level aus `shared_state["grid_1"]` → erzeugt `lines`-Array
    unter Anwendung von `show_lines`/`line_color` (leere Farbe =
    Paritäts-Styling des Alt-Grid: `rgba(33,150,243,0.9)` für Custom-Levels
    mit width 1, `rgba(33,150,243,0.5)` für Normal-Levels mit width 3,
    Style Solid – bisher in `grid_lines_service.calculate()`, wird in den
    Indikator übernommen).
  * Liest `proximity`-Hits (`levels_hit`, `is_hit`, `in_time_window`) →
    erzeugt `hit_circles` mit `priority=10` und Farbe:
    `circle_color_std` wenn `in_window=True` (bzw. Time-Filter inaktiv),
    `circle_color_active` sonst.
  * `status_info` wird aus dem `proximity`-Feature-Payload
    `metadata["statistics"]` (E4) übernommen (`in_time_window`,
    `active_hits`).
 
### Schritt 3: Services bereinigen (`analytics/features/definitions/`)
* **`grid_lines_service.py`:**
   * UI-Parameter (`show_lines`, `line_color`) aus `parameter_order`/
     `param_labels`/`parameter_schema` entfernen (nur noch
     `step_size`, `steps_around`, `custom_levels`, `prox_level1..6`).
   * `lines_payload` aus `calculate()` entfernen; `chart_render_payload`
     entfällt ersatzlos.
   * ABER (E2): weiterhin reine Level-Liste `[{price: float}, ...]` unter
     `context.shared_state[self.instance_id]` schreiben (für depends_on-Proximity).
   * `capabilities["render"] = False`.
* **`proximity_service.py`:**
  * `hit_circles` und `status_info` aus `calculate()` entfernen → Rückgabe
    NUR `feature_store_payload` (E3: `levels_hit`, `is_hit`,
    `in_time_window`, ...).
  * `status_info`-Logik (letzte Bar, `active_hits`) in `metadata["statistics"]`
    des Feature-Payloads auslagern (E4).
  * `plugin_id = "proximity"` und
    `metadata["indicator_name"] = "Ind_FixedGridProximity"` sicherstellen.
  * `capabilities["render"] = False`.

### Schritt 4: Verifikation & Headless-Testing
* Statische Syntax-Prüfung via `python -m py_compile` durchführen.
* **`test/test.py` anpassen (bestehende Asserts):** V5/V6/V8 (proximity
  `hit_circles`/`status_info` im `chart_render_payload`) entfallen oder werden
  auf die neuen Pfade umgestellt (Rohdaten → `build_chart_render_payload`).
* **Neue Test-Datei `test/check_p16_s1_decoupling.py`:**
   * `grid_lines_service.calculate()` liefert KEIN `chart_render_payload` mehr
     und enthält `show_lines`/`line_color` nicht mehr in
     `parameter_order`/`parameter_schema`.
   * `proximity_service.calculate()` liefert KEIN `chart_render_payload` mehr
     (nur `feature_store_payload`), `plugin_id == "proximity"`,
     `metadata["indicator_name"] == "Ind_FixedGridProximity"`.
   * `FixedGridProximityIndicator.build_chart_render_payload()` baut aus
     `shared_state["grid_1"]` (Levels) + Proximity-Records die korrekten
     Canvas-Objekte (lines inkl. Farbe/width/Style, hit_circles mit
     `priority=10` und korrekter Farbzuteilung gemäß E1).
   * `capabilities["render"] is False` für beide Services.

 ## Implementierungs-Log (nach Freigabe auszufüllen)

- **P16.01 – Architektur-Refactoring Visualisierungs-Entkopplung**
  - Datum/Uhrzeit: 06.08.2026 13:38 (MD)
  - Umgesetzt:
    * Schritt 2: `FixedGridProximityIndicator.build_chart_render_payload()`
      implementiert (Lines inkl. Paritäts-Styling, hit_circles mit
      `priority=10` + E1-Farbzuteilung, status_info aus
      `metadata["statistics"]`); `calculate()` baut den Render-Payload nur
      noch aus Rohdaten (shared_state-Levels + Feature-Records).
    * Schritt 3: `grid_lines_service.py` (UI-Parameter `show_lines`/
      `line_color` aus Schema/Order/Labels entfernt, `render=False`,
      `chart_render_payload` ersatzlos entfernt, reine Level-Liste
      `[{price}, ...]` in shared_state gemäß E2); `proximity_service.py`
      (`hit_circles`/`status_info` aus `calculate()` entfernt, nur
      `feature_store_payload` mit E3-Schema, `status_info` →
      `metadata["statistics"]` gemäß E4, `render=False` gemäß E5).
    * Schritt 4: `test/check_p16_s1_decoupling.py` neu (32 Checks, alle
      PASS); `test/test.py` V5/V6/V8 auf die neuen Pfade umgestellt
      (kein chart_render_payload im Service, hit_circles via
      `build_chart_render_payload`).
  - Validierung: `python -m py_compile` der 4 geänderten Dateien (OK);
    `test/check_p16_s1_decoupling.py` (32/32 PASS);
    `test/test.py` Teil 7 V4–V8 (PASS; Teil 1–3 P2/P5/H3/H4/H5/H7 sind
    vorbestehende offscreen-Screen-Größen-/keep_history-Divergenzen,
    unabhängig von P16.01);
    `test/check_p15_s4_infra.py` + `test/check_p16_rename_migration.py`
    (PASS).
  - Commit/Tag: `phase16_p16-01`.