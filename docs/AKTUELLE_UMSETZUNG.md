# Konzept Phase 14: Advanced Infrastructure, Dynamic Discovery & System-Resilience

## 1. Übersicht & Zielsetzung

Ziel von **Phase 14** ist die Finalisierung der Infrastruktur, Architektur und System-Resilienz für den produktiven Einsatz der PyTrader-Applikation. Der Schwerpunkt liegt auf der **vollständigen Dokumentierbarkeit** von Services & Sets, der **vollautomatischen Plugin-Entdeckung** (Dynamic Discovery/Hot-Reload), einem **resilienten Fehlerhandling** (Skip-Logic, Caches, Quarantäne) sowie **Versionierung & Papierkorb-Sicherheit**.

Jedes Modul enthält direkt im Anschluss die vollständige, isolierte **Schritt-für-Schritt AI-Implementierungsanweisung** inklusive automatischer Git-Backup-Regeln, Architektur-Constraints, des zentralen Grundsatzkapitels und der headless Validierung.

---

## 2. Allgemeine Grundsätze & Workflow-Vereinbarungen (Agents.md / Architektur.md)

1. **HARTE VERBOTSREGEL (Alt-Grid & Bestands-Pfade):**
Die Alt-Dateien `chart/indicators/grid.py`, `chart/indicators/grid_liquidity.py` sowie bestehende Kernmodule dürfen unter keinen Umständen beschädigt oder in ihrer Funktionsweise für bestehende Aufrufe verändert werden. Neue Logiken werden additiv integriert.


2. **Git-Backup & Fallback vor JEDEM Kapitel:**
Vor Beginn jedes Kapitels erstellt die AI / der User automatisch einen Git-Commit und Tag: `phase14_step1`, `phase14_step2`, etc. Bei Fehlern wird sofort per `git reset --hard` auf das jeweilige Tag zurückgerollt.


3. **Headless-Validierung (Keine UI- und Keine unnötigen (Regressions-)tests):**
Validierungen erfolgen rein headless (kein `QApplication.exec()`, keine manuellen Klicks) über gezielte PyTest- / Headless-Python-Skripte im Ordner `test/`. Es werden ausschließlich die für den jeweiligen Schritt absolut notwendigen Tests ausgeführt – keine unnötigen (Regressions-)tests.


4. **Modulare Herauskoppelbarkeit:**
Jedes Kapitel ist so aufgebaut, dass Beschreibung, Schema-Änderung, Implementierungsanleitung, die allgemeinen Grundsätze und der notwendige Test als zusammenhängender Block an die IDE-AI übergeben werden können.


5. **Struktur & Refactoring:**
Phase 14 bleibt **rein additiv**. Die Harte Verbotsregel (Schutz der Alt-Grid-Dateien und Bestands-Pfade) gilt uneingeschränkt. Existing Subsysteme werden nicht gebrochen, sondern um Schnittstellen/Wrapper erweitert.



---

## 3. Architektur-Invarianten (Kapitel 14.0 - Fundament)

Vor jeglicher Code-Implementierung gelten folgende unumstößliche System-Regeln zur Sicherstellung der Konsistenz:

1. **PluginRegistry Ownership:** Genau eine Singleton-Instanz der `PluginRegistry` pro Prozess.
2. **Feature Store vs. Cache (Source of Truth):**
`Plugin` $\rightarrow$ `EvaluationContext.shared_state` (Live-RAM) $\rightarrow$ `feature_store` (DuckDB Cache) $\rightarrow$ `Indicator` (GUI-Lesepfad).
Der Indicator ruft niemals direkt Plugins zur Neuberechnung auf.
3. **ID-Semantik:**
* `depends_on` referenziert ausschließlich `instance_id` (z. B. `"grid_1"`).
* `plugin_id` ist strikt case-insensitiv eindeutig (`plugin_id.lower()`).

4. **Quarantäne-Lebensdauer:** Quarantäne (`quarantined = True`) gilt ausschließlich im RAM für die aktuell laufende Session und wird nicht in der Datenbank persistiert.
5. **Versionierung & Schema:**
* Jeder Plugin-Output und Feature-Payload enthält ein `schema_version`.
* Jedes Plugin deklariert explizit eine `api_version` (z. B. `api_version="1"`).
* Versionsvergleiche nutzen Semantic Versioning (`major.minor.patch`). Reine Patch-Updates (z. B. `1.0.0` $\rightarrow$ `1.0.1`) lösen keine Schema-Migration aus.

6. **Hot-Reload-Semantik:** `PluginRegistry.reload()` ersetzt nur zukünftige Service-Instanziierungen; bereits laufende Hintergrund-Auswertungen laufen ungestört auf ihren bisherigen Objektinstanzen weiter. Custom Plugins werden isoliert entladen/neu importiert.
7. **Thread Safety:** Der Zugriff auf `PluginRegistry` und `FeatureStore` durch `LiveAnalyzer`, `HistoricalScanner` und Charts erfolgt über explizite Thread-Locks (Thread-Safety).
8. **Logging & Migration Rollback:**
* Logging verwendet strukturierte Fehlerobjekte (inkl. `timestamp`, `plugin`, `instance`, `symbol`, `timeframe`, `bar`, `exception`, `traceback`).
* Schlägt eine Schema-Migration fehl (`SchemaMigrator` Exception), wird die Transaktion abgebrochen, das alte Set im Speicher belassen und ein Rollback durchgeführt.

  9. **Snapshot-Historie:** Ein historischer Snapshot in `service_set_history` wird ausschließlich beim erfolgreichen Überschreiben eines bereits existierenden Sets erzeugt.
10. **Chart-Entkopplung:** Der Chart führt niemals Berechnungen aus, sondern liest ausschließlich vorberechnete Daten aus DuckDB (mit definiertem Fallback).
11. **Quarantäne-Recovery (Lebensdauer):** Der `_failure_counters`-Zähler jeder Service-Instanz wird nach 300 Sekunden (5 Minuten) ohne weiteren Fehler automatisch zurückgesetzt (`_recovery_timer`). Eine einmalige Quarantäne (`quarantined = True`) bleibt für die laufende Session bestehen, bis der Evaluator einen vollständigen Neustart der Pipeline durchläuft (`reset()`).

12. **Hot-Reload Lifecycle:** `PluginRegistry.reload()` führt folgende atomare Schritte unter dem `RLock()` aus:
    a) Erfassen der aktuell geladenen Custom-Modul-Namen (`data/custom_plugins/`).
    b) Gezieltes `importlib.reload(sys.modules[mod_name])` NUR für diese Module.
    c) Erneute Ausführung von `discover_plugins()` mit anschließendem Überschreiben des internen `plugins`-Dictionaries.
    d) WICHTIG: Bereits laufende Service-Instanzen (`LiveAnalyzer`, historische Berechnungen) behalten ihre alte Objekt-Referenz; neue Service-Instanzen nutzen die neuen Klassen.

13. **Cache-Invalidierung (Feature Store):** Der `FeatureBuilder` führt bei jedem `store_plugin_payload()` eine explizite Invalidation des In-Memory-Caches für das betroffene `(symbol, timeframe)` durch, um veraltete Zustände in `EvaluationContext.shared_state` zu verhindern.
---

## 4. Spezifikation & Schritt-für-Schritt-Anleitungen der Kernmodule (Phase 14)

---

### Kapitel 4.3 [P14-03]: Erweiterte Pipeline-Fehlerbehandlung, Auto-Recovery & Live-Feature-Store-Entkopplung

#### A. Konzept & Datenmodell

Ablösung des strikten Fail-Fast-Prinzips durch ein elastisches, fehlerfreies Pipeline-Handling sowie die saubere architektonische Trennung zwischen **Live-Tick-Performance**, **Feature-Store-Caching** und **Bar-Close-Service-Evaluierungen**.

1. **Architektur & Live-Entkopplung (Garantie der Phase-13-Performance):**
* **Live-Ticks in der GUI (`update_live_candle`):** Führen **keine** Service-Pipeline und keine DB-Abfragen aus. Der Indikator berechnet für den allerletzten Tick lediglich die mathematische Differenz zu den bereits im Arbeitsspeicher gecachten Grid-Linien.
* **Bar-Close Polling (`LiveAnalyzer`):** Der `LiveAnalyzer` evaluiert geschlossene Kerzen im Hintergrund. Er nutzt hierfür einen **stark verkürzten Lookback (1 bis 2 Bars)** gegen das im `EvaluationContext.shared_state` gepufferte Raster, um Rechnerlast und DB-I/O minimal zu halten.
* **Indikator-Lesepfad (`feature_store`):** Beim Chart-Re-Render / Refresh liest der `GridLiquidityIndicator` fertige Daten primär aus dem JSON-Feld `feature_data` (inkl. `schema_version`) der Tabelle `feature_store` in DuckDB aus, anstatt die Pipeline synchron auf der GUI neu zu berechnen.

2. **Ganzheitliche Fehlerkapselung (`PluginExecutor`):**
* Sämtliche Exceptions in der Ausführungskette eines Plugins – inklusive `validate_params()`, interner Dependency-Aufrufe (`depends_on` auf `instance_id`) und `calculate()` – werden innerhalb von `PluginExecutor.execute()` isoliert abgefangen.
* Fehler werden in ein strukturiertes Fehlerobjekt umgewandelt (inkl. Exception, Traceback, Symbol, Timeframe, Bar) und geloggt.

3. **Resiliente Evaluator-Schleife (`ServiceSetEvaluator`):**
* **Skip-Logic:** Schlägt ein unkritischer Service fehl, wird er geloggt und übersprungen. Unabhängige Services laufen weiter.
* **Dependency Skip:** Services, die per `depends_on` von der fehlerhaften `instance_id` abhängen, werden kontrolliert mit `skip_reason="dependency_failed"` übersprungen.

4. **State-Fallback & Session-Quarantäne:**
* **State-Fallback:** Tritt beim Bar-Close-Intervall oder Chart-Refresh ein Fehler auf, greift der Evaluator exklusiv auf `EvaluationContext.shared_state.get(instance_id)` der vorherigen Kerze zurück.
* **RAM-Quarantäne-System:** Fällt eine Service-Instanz in 3 aufeinanderfolgenden Ausführungen aus, wird sie im RAM für die laufende Session quarantänisiert (`quarantined = True`) und dauerhaft übersprungen. Quarantäne-Zustände werden **nicht** in DuckDB persistiert.


---

#### B. Schritt-für-Schritt AI-Anleitung (Kopierblock P14-03)

### AI-Auftrag: Implementierung P14-03 (Pipeline-Fehlerbehandlung, Feature-Store-Lesepfad & Live-Resilience)

#### 2. Allgemeine Grundsätze & Workflow-Vereinbarungen (Agents.md / Architektur.md)

1. **HARTE VERBOTSREGEL (Alt-Grid & Bestands-Pfade):**
Die Alt-Dateien `chart/indicators/grid.py`, `chart/indicators/grid_liquidity.py` sowie bestehende Kernmodule dürfen unter keinen Umständen beschädigt oder in ihrer Funktionsweise für bestehende Aufrufe verändert werden. Neue Logiken werden additiv integriert.

2. **Git-Backup & Fallback vor JEDEM Kapitel:**
Vor Beginn jedes Kapitels erstellt die AI / der User automatisch einen Git-Commit und Tag: `phase14_step1`, `phase14_step2`, etc. Bei Fehlern wird sofort per `git reset --hard` auf das jeweilige Tag zurückgerollt.

3. **Headless-Validierung (Keine UI- und Keine unnötigen (Regressions-)tests):**
Validierungen erfolgen rein headless (kein `QApplication.exec()`, keine manuellen Klicks) über gezielte PyTest- / Headless-Python-Skripte im Ordner `test/`. Es werden ausschließlich die für den jeweiligen Schritt absolut notwendigen Tests ausgeführt – keine unnötigen (Regressions-)tests.

4. **Modulare Herauskoppelbarkeit:**
Jedes Kapitel ist so aufgebaut, dass Beschreibung, Schema-Änderung, Implementierungsanleitung, die allgemeinen Grundsätze und der notwendige Test als zusammenhängender Block an die IDE-AI übergeben werden können.



#### Schritt 0: Fallback & Backup

1. Führe vor Code-Änderungen folgendes Git-Backup aus:
git add -A && git commit -m "backup: pre P14-03" && git tag -f phase14_step3

#### Schritt 1: Absicherung im PluginExecutor & Evaluator

1. Öffne `analytics/features/feature_builder.py` (`PluginExecutor`):
* Umschließe in `execute()` die gesamte Kette mit `try...except Exception as e`.
* Prüfe `depends_on`-Abhängigkeiten strikt gegen vorhandene `instance_id`-Keys.
* Erzeuge bei Fehlern ein strukturiertes Fehlerobjekt (mit `timestamp`, `plugin`, `instance_id`, `symbol`, `timeframe`, `bar`, `exception`, `traceback`) im Log und liefere ein Error-Result-Dict `{"success": False, "error": str(e), "instance_id": instance_id}` zurück.

2. Öffne `analytics/engine/set_evaluator.py` (`ServiceSetEvaluator`):
* Ergänze Konfigurations-Flag `allow_skip_errors: bool = True` in `execute_set()`.
* Bei Fehler einer `instance_id`:
* Markiere davon per `depends_on` abhängige Instanzen als übersprungen (`skip_reason="dependency_failed"`).
* Führe unabhängige Services regulär fort.

#### Schritt 2: State-Fallback, Session-Quarantäne & Recovery (Erweitert)

1. Erweitere `ServiceSetEvaluator`:
   * Führe ein internes RAM-Dict `_failure_counters: Dict[str, int]` und `_last_failure_time: Dict[str, float]` für Service-Instanzen.
   * Bei Fehler:
     * Greife im Bar-Close-Betrieb exklusiv auf `context.shared_state.get(instance_id)` zurück.
     * Inkrementiere `_failure_counters[instance_id] += 1` und setze `_last_failure_time[instance_id] = time.time()`.
     * **Recovery-Logik:** Prüfe vor jedem Inkrement, ob `time.time() - _last_failure_time.get(iid, 0) > 300`. Falls ja, setze den Counter zurück (Self-Healing nach 5 Minuten).
   * Bei 3 aufeinanderfolgenden Fehlern (innerhalb von 5 Minuten): Setze `quarantined = True` im RAM für die laufende Session und überspringe die Instanz mit Log-Warnung. (Nicht DB-persistieren).

2. **Strukturierte Fehlerobjekte (P14-03.1):**
   * Definiere in `base_plugin.py` ein `TypedDict` (`ServiceErrorLog`) mit den Pflichtfeldern: `timestamp`, `plugin_id`, `instance_id`, `symbol`, `timeframe`, `bar_time`, `exception`, `traceback`.
   * Nutze dieses Dict ausschließlich für das Logging in `PluginExecutor` und `ServiceSetEvaluator`, um maschinelle Auswertung zu ermöglichen.


#### Schritt 3: Verkürzter Live-Lookback & Indikator-Feature-Store-Lesepfad

1. Öffne `analytics/background_workers/live_analyzer.py`:
* Optimiere `_process_plugin_bars()`: Setze den `lookback_bars`-Parameter bei laufenden Bar-Close-Evaluierungen gezielt auf `limit = 2` (1 unvollständige, 1 frisch geschlossene Kerze) gegen das gepufferte `shared_state`-Raster.

2. Öffne `chart/indicators/grid_liquidity.py` (`GridLiquidityIndicator`):
* Ergänze in `calculate()` einen primären DB-Lesepfad: Lade gepufferte Daten aus `feature_store.feature_data` (DuckDB), sofern aktuelle Daten und passendes `schema_version` vorhanden sind.
* Nutze Heavy-Berechnung über `FeatureBuilder` nur als Fallback, wenn `feature_store` leer ist.
* Architektur-Constraint wahren: Stelle sicher, dass `update_live_candle()` weiterhin KEINE Pipeline ausführt, sondern performant auf gecachte Daten zugreift.

#### Schritt 4: Headless Validierung

1. Erstelle und führe aus: `test/check_p14_s3_resilience.py`:
* Erzeuge einen Test mit:
a) Service mit defekter Parameter-Validierung.
b) Service mit fehlerhafter `depends_on` Reference (`instance_id`).
c) Service, der 3x nacheinander abstürzt (Prüfe RAM-Quarantäne und State-Fallback).
d) Verifikation, dass `GridLiquidityIndicator` Daten korrekt aus `feature_store.feature_data` liest.
* Verifiziere, dass das Gesamtsystem stabil bleibt und unabhängige Services weiterlaufen.

