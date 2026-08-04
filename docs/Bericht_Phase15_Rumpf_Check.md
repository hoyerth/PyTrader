# Bericht: Prüfung des Phase-15-Rumpfs (`docs/x_roadmap_Phase15.md`)

Stand: 04.08.2026 · Basis: Git HEAD `fc27094` (P14 abgeschlossen, Phase 15 noch nicht begonnen)

---

## 1. Auftrag & Vorgehen

Geprüft wurde, ob die im Rumpf von Phase 15 gesetzten Voraussetzungen
(Kap. 2 „Allgemeine Grundsätze & Workflow-Vereinbarungen", Kap. 3 „Architektur-Invarianten")
**noch aktuell und angemessen** für die Weiterentwicklung der **Service-UI** (`service_win.py`)
und des **gesamten Analytics-Moduls** (`analytics/`) sind.

Vorgehen: reine Code-Inspektion des Ist-Stands (keine UI-/Regressionstests, gemäß System-Regel 4).
Geprüfte Module u. a.: `analytics/features/feature_builder.py`, `analytics/features/plugins/base_plugin.py`,
`analytics/engine/set_evaluator.py`, `analytics/engine/schema_migrator.py`,
`analytics/engine/service_set_repository.py`, `analytics/engine/service_models.py`,
`analytics/background_workers/live_analyzer.py`, `analytics/background_workers/historical_scanner.py`,
`analytics/statistics_repository.py`, `chart/indicators/grid_liquidity.py`, `db_service.py`.

---

## 2. Ausgangslage

- **Phase 15 ist ein unvollständiger Rumpf:** Kap. 1 enthält den Platzhalter `<auformulieren>`
  (Zielsetzung fehlt), Kap. 2 + 3 sind formuliert, konkrete Kapitel/Module (15.x) existieren noch nicht.
- **Git-Status:** `docs/x_roadmap_Phase15.md` ist im Zustand „AM" (neu gestaged + modifiziert).
- **Wichtig:** `docs/AKTUELLE_UMSETZUNG.md` (laut System-Regeln die verbindliche Hauptanweisung)
  ist seit Commit `fc27094` („x", 03.08.2026) **leer (0 Bytes)** – die Hauptanweisung fehlt derzeit.
- P14 ist vollständig umgesetzt (P14-01 … P14-05, Abschluss-Doku in `f2fb88f`/`5212b3a`).
  Die Invarianten des Rumpfs sind großteils bereits in P14 im Code verankert.

---

## 3. Kap. 2 – Allgemeine Grundsätze: Bewertung

| # | Grundsatz | Status | Befund |
|---|-----------|--------|--------|
| 1 | Harte Verbotsregel (grid.py, grid_liquidity.py) | ✅ aktuell | Beide Dateien sind aktiv in Nutzung (`chart/indicators/`). Schutz ist weiterhin nötig. **Hinweis:** `grid_liquidity.py` ist zugleich die Datei, die noch eine Service-Pipeline im Chart ausführt (→ Invariante 2/10, s. u.). |
| 2 | Git-Backup & Tag je Kapitel (`phase15_stepN`) | ✅ angemessen | Bewährtes Muster (historische Tags `phase14_step1…6` vorhanden). |
| 3 | Headless-Validierung in `test/` | ✅ angemessen | Konsistent mit System-Regeln; `test/` enthält zahlreiche `check_p14_*.py`-Skripte, an die Phase 15 anknüpfen kann. |
| 4 | Modulare Herauskoppelbarkeit | ✅ angemessen | Passt zum bisherigen Vorgehen (Kapitel als eigenständige Blöcke). |
| 5 | Rein additiv / Open-Closed | ✅ angemessen | Passt zum Ist-Design (Wrapper/Schnittstellen statt Umbau). |

**Fazit Kap. 2:** Alle 5 Punkte sind aktuell und angemessen. Kein Änderungsbedarf.

---

## 4. Kap. 3 – Architektur-Invarianten: Status im Ist-Code

| # | Invariante | Status | Befund (Datei/Zeile) |
|---|-----------|--------|----------------------|
| 1 | PluginRegistry-Singleton (1 pro Prozess) | ✅ erfüllt | `feature_builder.py`: `PluginRegistry.__new__` mit Klassen-Attribut `_instance` + `RLock`. |
| 2 | Feature-Store-vs.-Cache-Kette (`Plugin → shared_state → feature_store → Indicator`) | ⚠️ **Teil-Delta** | Kette existiert grundsätzlich. Aber: (a) Konzeptname **„EvaluationContext" existiert nicht als Klasse** – nur Kommentare in `live_analyzer.py`, `set_evaluator.py`, `feature_builder.py` erwähnen ihn; die reale Klasse heißt `PluginContext`. (b) Der Indikator **ruft sehr wohl Plugins direkt auf** (Fallback, s. Invariante 10). |
| 3 | ID-Semantik (`depends_on` → `instance_id`; `plugin_id.lower()`) | ✅ erfüllt | `base_plugin.py` (`PluginContext.instance_id/depends_on`), `feature_builder.py` (`pid.lower()`). |
| 4 | Quarantäne nur RAM, keine DB-Persistenz | ✅ erfüllt | `set_evaluator.py`: `_quarantined`-Set, keine Persistenz. |
| 5 | Versionierung & Schema (SemVer; `api_version`; `schema_version` in Payloads) | ⚠️ **teilweise** | `api_version` ✅ (`PluginMetadata`, Default „1"). SemVer + `SchemaMigrator` ✅ (`schema_migrator.py`, Patch löst keine Migration aus). **Lücke:** `schema_version` wird nur vom `ProximityService` in `metadata` geschrieben; das `FeatureStorePayload`-TypedDict (`base_plugin.py`) hat **kein** `schema_version`-Feld; das Alt-Plugin `grid_liquidity` (`definitions/grid_liquidity.py`) schreibt nur `plugin_version`. |
| 6 | Hot-Reload-Semantik (laufende Instanzen behalten Referenzen) | ✅ erfüllt | `feature_builder.py`: `PluginRegistry.reload()` dokumentiert/implementiert (Custom-Module gezielt neu, Rest bleibt). |
| 7 | Thread Safety über explizite Thread-Locks | ⚠️ **Formulierung** | Registry/Evaluator haben RLocks ✅. **Aber:** Der DB-Zugriff ist bewusst **lock-frei** über Thread-local `DbPool` (Thread-local Singleton, `db_service.py` Z. 85–115: „Threading-Locks sind hier kontraproduktiv"). Die Invarianten-Formulierung „explizite Thread-Locks" entspricht nicht dem Ist-Design. |
| 8 | Strukturierte Fehlerobjekte + Migrations-Rollback | ✅ erfüllt | `ServiceErrorLog`/`PluginExecutionErrorInfo` (`base_plugin.py`/`feature_builder.py`); `MigrationError` → Rollback in `service_set_repository.get_set()`. |
| 9 | Snapshot-Historie nur bei Überschreiben existierender Sets | ✅ erfüllt | `service_set_repository.save_set(record_snapshot=True)` mit `service_set_history` (P14-05). |
| 10 | Chart-Entkopplung (Chart rechnet nie, liest nur vorberechnete Daten) | ⚠️ **teilweise** | Primärpfad ✅: `grid_liquidity.read_proximity_from_feature_store()` liest `feature_store`. **Aber:** `grid_liquidity.calculate()` führt weiterhin die komplette Service-Pipeline im Chart aus (`ServiceSetEvaluator.execute_set`, Fallback bei leerem Store). „Der Indicator ruft niemals direkt Plugins zur Neuberechnung auf" ist damit **nicht vollständig** erreicht. |
| 11 | Quarantäne-Recovery (300 s Zähler-Reset, Quarantäne bis `reset()`) | ✅ erfüllt | `set_evaluator.py`: `_recovery_seconds = 300.0`, `_is_quarantined()`-Reset, Quarantäne bleibt bis `reset()`. |
| 12 | Hot-Reload-Lifecycle a–d (Custom-Module erfassen, reload, discover, Referenzen) | ✅ erfüllt | `feature_builder.py`: `PluginRegistry.reload()` unter `RLock`, Schritte a–d identisch. |
| 13 | Cache-Invalidierung bei `store_plugin_payload()` | ✅ erfüllt | `feature_builder.py`: `invalidate_feature_cache(symbol, timeframe)` in `store_plugin_payload()`. |

**Zählung:** 9 von 13 Invarianten vollständig im Code verankert.
4 mit Delta: **#2 (Namens-/Konzept-Delta), #5 (schema_version lückenhaft), #7 (Lock-Formulierung), #10 (Chart rechnet im Fallback noch)**.

---

## 5. Befunde mit Relevanz für die Weiterentwicklung

1. **Chart-Entkopplung ist das zentrale offene Arbeitspaket.**
   Die geschützte Alt-Datei `chart/indicators/grid_liquidity.py` hält intern
   `PluginExecutor` + `ServiceSetEvaluator` (Z. 67–68) und führt in `calculate()`
   eine vollständige `execute_set()`-Pipeline aus (Fallback, wenn der
   `feature_store` leer ist). Da die Harte Verbotsregel genau diese Datei schützt,
   muss Phase 15 die vollständige Entkopplung **additiv** lösen (Wrapper/Interface),
   nicht durch Änderung der Datei. Der Primärpfad (DB-Lesepfad) ist bereits vorhanden.

2. **Namens-Delta „EvaluationContext" vs. `PluginContext`.**
   Invariante 2 nennt `EvaluationContext.shared_state`; die reale Klasse heißt
   `PluginContext.shared_state`. Vor der Ausformulierung der Kapitel sollte der
   Begriff in der Roadmap vereinheitlicht werden (oder ein echtes
   `EvaluationContext`-Alias eingeführt werden), um Missverständnisse zu vermeiden.

3. **„feature_store (DuckDB Cache)" ist semantisch ein Dauer-Speicher.**
   Der `feature_store` ist eine persistente Tabelle in `analytics.duckdb` mit den
   vorberechneten Werten (Source of Truth für GUI-Lesepfade), kein flüchtiger Cache.
   Wortwahl in Invariante 2 ggf. präzisieren („Feature-Store (persistenter
   Vorberechnungs-Speicher)").

4. **`schema_version` (Invariante 5) ist nicht flächendeckend umgesetzt.**
   Nur der ProximityService schreibt `schema_version` in `payload.metadata`.
   Das `FeatureStorePayload`-TypedDict enthält kein Pflichtfeld; das Alt-Plugin
   `grid_liquidity` (definitions) schreibt nur `plugin_version`. Für Phase 15
   empfehlenswert: `schema_version` als Pflichtfeld im TypedDict + in allen
   `feature_store=True`-Plugins (inkl. Bestands-Plugin) stempeln.

5. **Alt-Pfade laufen teils parallel weiter (bewusst, aber zu klären).**
   `LiveAnalyzer` hat `_process_plugin_bars` (Alt) + `_process_plugin_bars_resilient`
   (Neu); `HistoricalScanner` hat Alt-Scan (grid/standard) + Plugin-Batch. Die
   Testsignal-Konfiguration (`set_config["signals"] = []`) ist deaktiviert. Phase 15
   sollte festlegen, welcher Pfad Zielzustand ist und welche Rückbauten additiv
   möglich sind.

6. **ML-Signale sind vorhanden, aber nicht nutzbar/verdrahtet.**
   `analytics/signals/machine_learning/` (lightgbm_v1/xgboost_v1) existiert;
   `lightgbm`/`xgboost` sind jedoch **nicht installiert** (venv) und **nicht in
   `requirements.txt`**. Kein Aufrufer im App-Code nutzt die Signale. Wenn Phase 15
   Analytics ausbauen will, ist hier eine bewusste Entscheidung nötig (aktivieren +
   Dependencies dokumentieren oder deklariert „future").

7. **`docs/AKTUELLE_UMSETZUNG.md` ist leer.**
   Die laut System-Regeln verbindliche Hauptanweisung ist seit Commit `fc27094`
   (246 Zeilen entfernt) nicht mehr vorhanden. Vor der Umsetzung von
   Phase-15-Kapiteln muss geklärt werden, ob die Datei neu aufgesetzt oder die
   Phase-15-Roadmap selbst zur neuen Hauptanweisung wird.

8. **Service-UI ist bereits groß.**
   `service_win.py` (≈ 1390 Zeilen) enthält Set-Editor, Parameter-Controls,
   Papierkorb (P14-05), Set-/Service-Sperren (P14-04-E), Info-Dialoge,
   `ServiceSetRunWorker`. Die Weiterentwicklung sollte auf Modularisierung achten
   (z. B. Extraktion in Widgets/Dialoge), sonst wächst die UI-Klasse weiter.

9. **Testbasis ist vorhanden.**
   `test/` bietet headless `check_*.py`-Skripte für fast jedes P14-Kapitel
   (s1…s5, resilience, migration, trash, performance). Phase-15-Kapitel können
   dieses Muster nahtlos fortsetzen.

---

## 6. Empfehlungen für die Ausformulierung der Phase-15-Kapitel

1. **Invariante 2/10 präzisieren:** „EvaluationContext" → `PluginContext`;
   Kette klar als Ist-Design beschreiben und den noch vorhandenen
   Pipeline-Fallback im Chart als explizites Abbauziel von Phase 15 deklarieren.
2. **Invariante 5 vervollständigen:** `schema_version` als Pflichtfeld in
   `FeatureStorePayload` aufnehmen und für alle `feature_store=True`-Plugins
   (inkl. Alt-Plugin) verbindlich stempeln.
3. **Invariante 7 an das Ist-Design anpassen:** Formulierung „explizite
   Thread-Locks" ersetzen durch „RLock für Registry/Evaluator/Session-State;
   DB-Zugriff lock-frei über Thread-local `DbPool`".
4. **Kap. 1 Zielsetzung ausformulieren** und die Modul-/Kapitelstruktur (15.x)
   definieren – z. B.:
   - 15.1: Service-UI-Modularisierung & Bedien-Feinschliff,
   - 15.2: Analytics-Lesepfade vervollständigen (schema_version, Entkopplung),
   - 15.3: Alt-Pfad-Rückbau (LiveAnalyzer/Scanner) additiv abschließen,
   - 15.4: optional ML-Signale aktivieren/dokumentieren.
5. **AKTUELLE_UMSETZUNG.md wieder aufsetzen** bzw. die Phase-15-Roadmap als
   neue Hauptanweisung etablieren (Abstimmung mit System-Regel 0c).
6. **ML-Dependencies** bei Aktivierung der ML-Signale in `requirements.txt`
   ergänzen (`lightgbm`, `xgboost`).

---

## 7. Fazit

- Der **Rumpf ist inhaltlich aktuell**: 9 der 13 Architektur-Invarianten sind
  vollständig im Code verankert (v. a. aus P14), die 5 Grundsätze von Kap. 2
  bedürfen keiner Änderung.
- Die Voraussetzungen sind für die Weiterentwicklung der **Service-UI und des
  Analytics-Moduls angemessen** – unter der Voraussetzung, dass die 4 Deltas
  (**#2 Namens-Delta, #5 schema_version, #7 Lock-Formulierung, #10 Chart-Fallback**)
  bei der Ausformulierung der Kapitel berücksichtigt werden.
- **Größtes inhaltliches Risiko:** die leere `AKTUELLE_UMSETZUNG.md` (fehlende
  Hauptanweisung) und die noch nicht vollständige Chart-Entkopplung in der
  geschützten Datei `chart/indicators/grid_liquidity.py` (additiv lösen).
