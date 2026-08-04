# AKTUELLE UMSETZUNG – Phase 15: Service UI und Analytics

> **Status (04.08.2026):** Dieses Dokument ist die **verbindliche Hauptanweisung**
> (System-Regel 0c) für alle aktuellen Umsetzungen. Die ausführliche
> Kapitel-Struktur, die Architektur-Invarianten und die vollständige
> Umsetzungsliste stehen in **`docs/x_roadmap_Phase15.md`** – dieses Dokument
> ist die Kurzfassung mit dem **aktuellen Arbeitsstand** und der
> **Reihenfolge** der nächsten Schritte. Bei Konflikten hat dieses Dokument
> Vorrang (einzige Ausnahme: die System-Instruktionen selbst).

---

## 1. Zielsetzung (Phase 15)

Weiterentwicklung der **Service-UI** (`service_win.py` → neuer Unterordner
`serviceui/`) und des **Analytics-Moduls** (`analytics/`) auf Basis der
etablierten Plugin-/Service-Architektur (Phasen 12–14):

* **15.1 Service-UI:** Modularisierung der gewachsenen `service_win.py` in den
  neuen Unterordner `serviceui/` (inkl. `service_win.py` selbst) und
  Bedien-Feinschliff. Bestehende Funktionen bleiben erhalten (Set-Editor,
  Parameter-Controls, Papierkorb, Set-/Service-Sperren).
* **15.2 Analytics-Lesepfade:** `schema_version` vervollständigen;
  Chart-Entkopplung abschließen (Pipeline-Fallback additiv abbauen).
* **15.3 Alt-Pfad-Rückbau:** Alt-Signal-Mechanik (`signal_results`, Signal-Sets,
  Alt-Scan-Pfade in LiveAnalyzer/HistoricalScanner) additiv abwickeln.
* **15.4 ML-Signale (optional):** `lightgbm_v1` / `xgboost_v1` aktivieren und
  dokumentieren oder explizit als „future" deklarieren.

---

## 2. Grundsätze & Workflow (gültig für alle Schritte)

1. **HARTE VERBOTSREGEL (Bestands-Pfade):** Geschützte Dateien (niemals
   beschädigen, bestehende Aufrufe unverändert lassen):
   `chart/indicators/grid_liquidity.py`,
   `analytics/features/definitions/grid_liquidity.py`. Neue Logiken werden
   **additiv** integriert. Der Alt-Grid-Indikator `chart/indicators/grid.py`
   ist bereits entfernt (Einzelanweisung, dokumentiert).
2. **Git-Backup & Fallback vor JEDEM Kapitel:** Vor jedem Kapitel Git-Commit
   + Tag: `phase15_step1`, `phase15_step2`, etc. Bei Fehlern sofort per
   `git reset --hard` auf das jeweilige Tag zurückrollen.
3. **Headless-Validierung (Keine UI- und keine unnötigen (Regressions-)tests):**
   Validierungen erfolgen rein headless (kein `QApplication.exec()`) über
   gezielte Skripte im Ordner `test/`. Nur die für den Schritt absolut
   notwendigen Tests – keine Regressionstests.
4. **Struktur & Refactoring:** Phase 15 bleibt **rein additiv** – bestehende
   Subsysteme werden nicht gebrochen, sondern um Schnittstellen/Wrapper
   erweitert.
5. **Test-Dateien:** Alle neuen Test-Python-Dateien und Test-DB (`*.duckdb`)
   liegen ausschließlich im Unterordner `test/` – niemals im Projekt-Root
   oder im `data`-Ordner.

---

## 3. Arbeitsstand (04.08.2026)

### 3.1 Erledigt (Phase 15)

- [x] **U15-A1** `schema_version` als Pflichtfeld im `FeatureStorePayload`-
  TypedDict (`analytics/features/plugins/base_plugin.py`); Stempelung in ALLEN
  `feature_store=True`-Plugins (inkl. Alt-Plugin `definitions/grid_liquidity.py`).
- [x] **U15-A2** Chart-Entkopplung: `read_proximity_from_feature_store()` als
  Primärpfad in `chart/indicators/grid_liquidity.py`; definierter Fallback
  dokumentiert; Farb-Anreicherung additiv.
- [x] **U15-B1** Tests umgestellt (headless): `test/grid_ref.py` (neu, gemeinsame
  Alt-Referenz aus `grid_math.py`), `check_grid_parity.py`, `check_grid_circles.py`,
  `check_p13_s6.py`, `check_plugin_time_filter.py`.
- [x] **U15-B2** `check_grid_buttons.py`, `check_grid_liquidity_indicator.py`
  auf neuen Stand (nur `grid_liquidity`, kein `grid`-Button) umgestellt.
- [x] **U15-B3** Paritäts-Logik in `analytics/features/definitions/grid_math.py`
  extrahiert; Kommentare in `proximity_service.py`, `grid_levels.py`,
  `grid_lines_service.py` auf `grid_math.py` umgestellt.
- [x] **U15-B4** UI-State-Bereinigung: `state_manager.py` löscht
  `indicator_presets`-Zeilen (`indicator_id='grid'`) idempotent; `chart_win.py`
  entfernt `indicators_state.pop("grid")` (3 Stellen).
- [x] **U15-C1** `LiveAnalyzer`: Zielzustand `_process_plugin_bars_resilient()`
  dokumentiert (Modul-Docstring + run()-Docstring).
- [x] **U15-C2** `HistoricalScanner`: Plugin-Batch als Zielzustand dokumentiert
  (Modul-Docstring + run()).
- [x] **U15-C3** Legacy-Tabellen-Entscheidung dokumentiert (→ §3.3 unten):
  `signal_definitions`, `signal_sets`, `signal_results` bleiben **als Referenz**
  erhalten (kein DROP).
- [x] **U15-A3** `docs/AKTUELLE_UMSETZUNG.md` neu aufgesetzt (dieses Dokument
  als verbindliche Hauptanweisung, System-Regel 0c).
- [x] **U15-A4** ML-Signale-Entscheidung dokumentiert (→ §4 unten): deaktiviert
  / future.
- [x] **U15-D1** `service_win.py` modularisiert in den **neuen Unterordner
  `serviceui/`** (inkl. `service_win.py` selbst) – Details siehe §5.
- [x] **U15-D2** Bedien-Feinschliff umgesetzt (Details Roadmap §4 D):
  Button-Lock bei Set-Ausführung, Set-Nachladen nach Löschen (verifiziert),
  Log-Auto-Scroll + Kontextmenü (Kopieren/Leeren), Voll-Scan-Bestätigung.

### 3.2 Noch offen (Reihenfolge)

1. Headless-Validierung (py_compile + gezielte Tests) + Commit(s) mit Tags
   `phase15_stepN` – der aktuelle Stand ist validiert und wird als
   `phase15_step3` committet.

### 3.3 Legacy-Tabellen (U15-C3 – Entscheidung)

`signal_definitions`, `signal_sets`, `signal_results` in `analytics.duckdb`
werden **als Referenz behalten** (kein DROP):

* `db_service.py` legt sie bei jedem Init per `CREATE TABLE IF NOT EXISTS`
  (Z. 246/254/261) ohnehin neu an – ein DROP wäre wirkungslos.
* `signal_results` wird noch von den DEAKTIVIERTEN Alt-Pfaden in
  `live_analyzer.py` referenziert (Early-Return, `set_config['signals']=[]`).
  Erst nach physischem Rückbau (U15-C1/C2) entfällt die letzte Referenz.
* Aktive Lese-/Schreibpfade existieren nicht mehr: `statistics_repository.py`
  liest `feature_store` (feature_id), `chart/overlays/signal_overlay.py` hat
  den signal_results-Fallback entfernt (Phase 13 7.B), `historical_scanner.py`
  schreibt nicht mehr in `signal_results`.

---

## 4. U15-A4 – ML-Signale (Entscheidung)

**Status:** Entscheidung dokumentiert in `docs/x_roadmap_Phase15.md` §4 A
(siehe dort). `analytics/signals/machine_learning/` bleibt **deaktiviert**
(future), solange `lightgbm`/`xgboost` nicht in `requirements.txt` stehen.

---

## 5. U15-D1 – Modularisierung der Service-UI in `serviceui/` (NEUE ANWEISUNG)

**User-Anweisung (04.08.2026):** Neuen Unterordner `serviceui/` erstellen und
dort die zugehörigen Module hineinpacken – **inklusive `service_win.py`
selbst**.

### Umgesetzte Struktur

```
serviceui/
  __init__.py           # Paket-Re-Exports (ServiceWindow, ServiceSetRunWorker, ...)
  service_win.py        # ServiceWindow (Hauptklasse, aus Root verschoben)
  service_set_utils.py  # _available_plugin_ids, _sets_using_plugin
  set_run_worker.py     # ServiceSetRunWorker (QThread)
  set_item_adapter.py   # ServiceSetItemAdapter (NamedItemAdapter)
  param_columns.py      # ServiceParamColumnsMixin (Parameter-Column-Builder)
  trash_dialog.py       # ServiceSetTrashDialog (Papierkorb-Dialog)
```

### Regeln (eingehalten)

* **Verhalten unverändert**: Alle Methoden wurden 1:1 verschoben; keine
  Logik-Änderung.
* **BASE_DIR**: `Path(__file__).resolve().parent.parent` (Projekt-Root), damit
  `BASE_DIR / "ui" / "service_win.ui"` weiterhin die UI-Datei findet.
* **Imports aktualisiert**: `main.py` (Z. 42),
  `chart/widgets/__init__.py` (Kommentar), `Architektur.md` (Z. 91) sowie die
  Test-Dateien `check_p13_s4.py`, `check_p13_service_win_geometry.py`,
  `check_p13_ui_plugins.py`, `check_p14_precision_levels.py`,
  `check_p14_s4_services_locked.py`.
* **Kompatibilität**: `service_win.py` (neu) re-exportiert
  `ServiceSetRunWorker`, `ServiceSetItemAdapter`, `_available_plugin_ids`,
  `_sets_using_plugin`, damit bestehende Aufrufe (`service_win.X`) weiter
  funktionieren.
* **Validierung**: py_compile OK; alle 5 betroffenen Headless-Checks BESTANDEN
  (`check_p14_s4_services_locked.py`, `check_p13_s4.py`, `check_p13_ui_plugins.py`,
  `check_p13_service_win_geometry.py`, `check_p14_precision_levels.py`).
  Zusätzlich 2 vorbestehende Test-Staleness-Fixes (P14-01/P14-04-E) in
  `check_p13_s4.py` und `check_p13_ui_plugins.py` (Details in Roadmap U15-D1).

---

## 6. Git-Stand

* Backup vor Phase-15-Umsetzung: `phase15_prep` (Commit 72f3327).
* U15-A/B/C gebündelt: `phase15_step1` (Commit 84f020f).
* U15-A3/A4/C3 + D1 (serviceui/): `phase15_step2` (Rollback-Punkt).
* Weitere Schritte: `phase15_step3`, ... (vor jedem Kapitel, Rollback-Punkt).
