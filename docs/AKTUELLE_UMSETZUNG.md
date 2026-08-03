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

---

### Kapitel 4.3-E [P14-03]: Ergänzung – Konzeptionelle Erklärung & Schritt-Anleitung (Live-Engine-Resilienz & Flackerfreies Overlay-Rendering)

Konzeptionelle Erklärung & Schritt-Anleitung für Roadmap P14-03 (Ergänzungsanweisung auf
Basis der Live-Tests & Code-Inspektion der Kette main.py → chart_win.py → grid_liquidity
→ JS). Rein additiv; Alt-Grid (`grid.py`, `grid_liquidity.py`) und die B-Anleitung
(Schritte 0-4) bleiben unangetastet.

#### A. Konzeptionelle Erklärung & Flacker-Analyse

##### Das Flacker- & Unterbrechungsproblem

Bisher führte das Eintreffen einer offenen Live-Kerze in `chart_win.py` dazu, dass der
Timestamp der offenen Kerze nicht in den historischen Maps (`_time_real_to_cont`) gefunden
wurde. Dies löste einen Re-Build des gesamten Charts (`refresh_chart_data()`) aus. Da die
offene Kerze noch nicht in DuckDB persistiert war (Persistierung erst bei Bar-Close durch
`LiveTickWorker._persist_bar`), warfen der Re-Build und JS (`applyFullChartUpdate` →
`chart.remove()` + Neuaufbau NUR aus DB-Kerzen) die Live-Kerze sofort wieder aus dem Chart.
Jeder 500-ms-Tick (Polling-Intervall `LiveTickWorker`) erzeugte so ein Wechselspiel aus
Anhängen (`elif self._time_cont_to_real` in `update_live_candle`) und Löschen
(`applyFullChartUpdate`) der Kerze → sichtbares Flackern zwischen zwei Zuständen, das erst
endet, wenn die Kerze geschlossen/gesynct ist (dann ist ihr Timestamp beim nächsten Refresh
in den Maps enthalten).

Zusätzlich war die Kette zur Übertragung von Indikator-Ergebnissen (Grid-Circles /
Proximity-Marker) an drei Stellen unterbrochen:
1. Der Resilienz-Seam `_process_plugin_bars_resilient()` im LiveAnalyzer war **nicht
   verdrahtet** (nur Definition + Docstring, kein Aufruf in `run()`).
2. Der Alt-Pfad `_process_plugin_bars()` übergab **keinen `PluginContext`** →
   `GridLinesService` schrieb kein Raster in `shared_state`, `ProximityService` fand keine
   Linien (`return empty`) → keine Hit-Records im `feature_store` für Live-Bars.
3. JS `updateLiveCandle()` verwarf die Live-Rückgabe (nur `candleSeries.update(c)`);
   `renderGridCircles()` wurde ausschließlich aus `applyFullChartUpdate` gerufen.

##### Die Architektur-Lösung

1. **Incremental Time Map Expansion:** Neue Live-Bar-Timestamps erweitern die bestehenden
   Maps (`_time_real_to_cont` / `_time_cont_to_real`) dynamisch In-Memory. Ein Aufruf von
   `refresh_chart_data()` entfällt beim Live-Tick vollständig.
2. **Resilient Bar-Close Pipeline:** Der `LiveAnalyzer` nutzt exklusiv
   `_process_plugin_bars_resilient()` unter Übergabe eines vollständigen `PluginContext`
   (inkl. `shared_state` = `self._live_shared_state`).
3. **Generisches Live-Overlay Rendering:** Der Live-Tick transportiert gerenderte
   Live-Overlays (Circles/Marker) im Payload. JS verarbeitet diese in `updateLiveCandle()`
   ohne kompletten Chart-Rebuild.
4. **Pflicht-Re-Injektion der offenen Live-Kerze:** Der (einmalige) New-Candle-Refresh
   baut die Time-Maps in `_do_refresh_chart_data` neu auf. Die offene Live-Kerze wird
   NACH dem Rebuild zwingend in die Maps (`_time_real_to_cont`/`_time_cont_to_real`),
   in `continuous_candles` (mit letzter Live-OHLC) und in die `_known_times` des
   Indikators re-injiziert – sonst feuert der New-Candle-Callback bei jedem Tick erneut
   und die Flacker-Schleife bleibt bestehen (siehe Prüfprotokoll P5).

#### B. Generische Entkopplungs-Regel

1. **Kein Chart-Rebuild bei Live-Ticks:** Ein Live-Tick darf **niemals**
   `refresh_chart_data()` aufrufen! (Der einzige Refresh pro neuer Kerze erfolgt über den
   New-Candle-Callback `set_new_candle_callback(self.refresh_chart_data)` des
   `GridLiquidityIndicator` – genau einmal pro neuer Kerze, debounced 400 ms. Siehe
   Prüfprotokoll P5.)
2. **In-Memory Map-Append:** Wenn ein neuer Bar-Timestamp im Live-Betrieb auftaucht, wird
   er In-Memory an `_time_real_to_cont` angehängt, **ohne** die Maps zu löschen (`clear()`).
3. **Pflicht-Re-Injektion (Flacker-Fix):** Die offene Live-Kerze (noch nicht in DuckDB)
   wird bei jedem Chart-Refresh zwingend in die Time-Maps, in `continuous_candles` und in
   die `_known_times` des Indikators re-injiziert. Erst dann ist der (einmalige)
   New-Candle-Refresh nicht mehr die Ursache einer Flacker-Schleife (siehe Prüfprotokoll P5).
4. **Generische JS-Push-Schnittstelle (Open/Closed):** `JS updateLiveCandle(payload)`
   verarbeitet `c.overlays` dynamisch (Schema: `{kind, layer, time, price, color,
   priority}`). Ein generischer Dispatcher (`applyLiveOverlays`) rendert vorhandene
   Plugin-Layer punktuell – OHNE kompletten Chart-Rebuild und OHNE die historischen
   Overlays zu verwerfen. Spätere Indikator-Plugins docken über neue `kind`/`layer`-Werte
   an, ohne `updateLiveCandle` zu ändern.
5. **Generischer Overlay-Hook (`BaseIndicator.get_live_overlays()`):** Jedes Indikator-
   Plugin liefert seine Live-Overlays über einen gemeinsamen Hook (Default `[]`). Die
   Engine (`chart_win`) sammelt die Overlays ALLER aktiven Indikatoren generisch ein –
   kein `hasattr(plugin, "_live_points")`-Sonderfall pro Plugin.

#### C. Schritt-für-Schritt Anleitung zur Behebung (P14-03 Refactoring)

##### Schritt 1: Flackern stoppen & Time-Maps dynamisch erweitern (`chart/chart_win.py`)

In `PyTraderChartWindow.update_live_candle()` den Aufruf von `self.refresh_chart_data()`
im `elif self._time_cont_to_real:`-Zweig entfernen. Stattdessen den neuen Timestamp
kontinuierlich an die bestehenden Maps anhängen.

##### Schritt 2: Resilienz-Seam verdrahten (`analytics/background_workers/live_analyzer.py`)

In `LiveAnalyzer.run()` den Aufruf `self._process_plugin_bars()` durch
`self._process_plugin_bars_resilient()` ersetzen. Sicherstellen, dass ein gültiger
`PluginContext` (der bereits vorhandene `self._live_context` mit
`shared_state=self._live_shared_state`) durchgereicht wird.

##### Schritt 3: Generisches Live-Overlay-Rendering (`chart/chart_win.py`, `chart/indicators/base_indicator.py` & `chart/js/04_live_updates.js`)

1. `BaseIndicator` erhält den generischen Hook `get_live_overlays(candle) -> List[Dict]`
   (Default `[]`). `GridLiquidityIndicator` überschreibt ihn und liefert seine
   Live-Punkte als Circle-Overlays (`kind='circle', layer=indicator_id`).
2. In `update_live_candle()` sammelt `chart_win` die Overlays ALLER aktiven Indikatoren
   generisch ein und bettet sie als `c.overlays` in das JSON-Payload ein (Zeiten
   real→kontinuierlich gemappt).
3. In `chart/js/04_live_updates.js` `updateLiveCandle(json)` erweitern: generischer
   Dispatcher `applyLiveOverlays(overlays)` rendert `kind='circle'`-Einträge als Merged-
   Render mit dem historischen Circle-Cache (siehe D.3).

##### Schritt 4: Chart-Lesepfad auf Feature-Store umstellen (`chart/indicators/grid_liquidity.py`)

`GridLiquidityIndicator.calculate()` so anpassen, dass die Hit-Circles primär aus dem
Feature-Store gelesen werden (DuckDB `feature_store.feature_data`, feature_id='proximity',
inkl. `schema_version`); die Heavy-Berechnung über die Service-Pipeline bleibt als
Fallback. Der Leser `read_proximity_from_feature_store()` wird um den Parameter
`feature_id: str = "proximity"` generalisiert, damit spätere Plugins dieselbe
Lesearchitektur nutzen können (siehe D.4).

#### D. AI-Arbeitsauftrag: Behebung der Live-Circle & Flacker-Befunde (P14-03 Ergänzung)

##### Context & Zielsetzung

Behebung der 5 Befunde bezüglich des Flackerns der Live-Kerze, der fehlenden
Circle-Anzeige auf der offenen Kerze sowie der unterbrochenen Service-Pipeline im
Live-Pfad.

---

##### Code-Anpassungen

##### 1. `chart/chart_win.py` – Live-Tick ohne Rebuild, Pflicht-Re-Injektion & generische Overlays:

a) In `__init__` den Live-Kerzen-State ergänzen:

```python
# P14-03-E: Live-Kerzen-State für die Pflicht-Re-Injektion (Flacker-Fix).
self._live_bar_time: Optional[int] = None   # reale, gerundete Bar-Zeit der offenen Kerze
self._live_candle_cont: Optional[Dict[str, Any]] = None  # letzter Live-Candle (kont. Zeit + OHLC)
```

b) In `update_live_candle()` den `elif self._time_cont_to_real:`-Zweig ersetzen –
   Refresh ENTFERNEN, Maps erweitern, Live-State merken:

```python
# BEFORE:
#     self.refresh_chart_data()  # <-- KERNPROBLEM (Flacker-Loop, Loeschen!)

# AFTER:
last_cont = max(self._time_cont_to_real.keys())
c_copy["time"] = last_cont + t_sec
self._time_cont_to_real[c_copy["time"]] = rounded_t
self._time_real_to_cont[rounded_t] = c_copy["time"]
# P14-03-E: Live-Kerzen-State für die Pflicht-Re-Injektion merken.
self._live_bar_time = rounded_t
self._live_candle_cont = dict(c_copy)
# KEIN refresh_chart_data() Aufruf bei Live-Ticks!
```

c) Generisches Overlay-Einsammeln über den `get_live_overlays()`-Hook (Open/Closed):
   Die bisherige `liq_ind.update_live_candle(...)`-Sonderbehandlung entfällt; die Engine
   iteriert über ALLE aktiven Indikatoren:

```python
# P14-03-E: Overlays ALLER aktiven Indikatoren generisch einsammeln.
overlays: List[Dict[str, Any]] = []
for ind_id, plugin in self.indicators.items():
    st = self.indicators_state.get(ind_id, {})
    if not st.get("active"):
        continue
    getter = getattr(plugin, "get_live_overlays", None)
    if not callable(getter):
        continue
    try:
        ov = getter(dict(c_copy, time=rounded_t)) or []
    except Exception:
        continue
    for item in ov:
        item = dict(item)
        t = item.get("time")
        if t is not None:
            try:
                item["time"] = self._time_real_to_cont.get(int(t), int(t))
            except (TypeError, ValueError):
                pass
        overlays.append(item)
c_copy["overlays"] = overlays
```

d) In `_do_refresh_chart_data()` NACH dem Map-Aufbau (nach dem `for i, c in
   enumerate(clean_candles):`-Block, vor dem Erstellen von `update_package`) – die
   PFLICHT-Re-Injektion der offenen Live-Kerze (Map + Candle):

```python
# P14-03-E (PFLICHT, Pruefprotokoll P5): Offene Live-Kerze nach dem Map-Rebuild
# re-injizieren – sonst feuert der New-Candle-Callback bei jedem Tick erneut
# und die Flacker-Schleife bleibt bestehen.
# (Die remember_live_time-Re-Injektion erfolgt GENERISCH NACH dem calculate()-
# Loop weiter unten – calculate setzt die _known_times der Indikatoren aus den
# DB-Bars zurueck und wuerde eine Re-Injektion VOR dem Loop wieder zunichte machen.)
if (self._live_bar_time is not None
        and self._live_bar_time not in self._time_real_to_cont):
    last_cont = max(self._time_cont_to_real.keys())
    cont = last_cont + t_sec
    self._time_cont_to_real[cont] = self._live_bar_time
    self._time_real_to_cont[self._live_bar_time] = cont
    if self._live_candle_cont is not None:
        lc = dict(self._live_candle_cont)
        lc["time"] = cont
        continuous_candles.append(lc)
```

##### 2. `analytics/background_workers/live_analyzer.py` – `run(self)`:

Ersetze die Ausführung des Alt-Pfads durch den Resilienz-Seam:

```python
# BEFORE:
#     self._process_plugin_bars()

# AFTER:
self._process_plugin_bars_resilient()
```

Der `PluginContext` existiert bereits als `self._live_context` (Mode `'live'`,
`shared_state=self._live_shared_state`) und wird im Seam pro Service per
`dataclasses.replace()` instanziiert (`instance_id=plugin_id`, bei
`plugin_id == "proximity"` zusätzlich `depends_on=["grid_lines"]`). KEIN neues Attribut
`self.shared_state` anlegen – es existiert nicht (siehe Prüfprotokoll P3). Ein expliziter
Neuaufbau ist nur nötig, falls der Context-Buffer zurückgesetzt wurde:

```python
if self._live_context is None:
    self._live_shared_state = {}
    self._live_context = PluginContext(
        symbol=self.symbol,
        timeframe=self.timeframe,
        mode="live",
        shared_state=self._live_shared_state,
    )
```

##### 3. `chart/js/04_live_updates.js` – generischer Overlay-Dispatcher:

`updateLiveCandle(json)` verarbeitet `c.overlays` generisch über `applyLiveOverlays()`.
Der Merged-Render fasst Live-Circles mit dem historischen Circle-Cache
`_gridCirclesCache` zusammen und übergibt ihn an das INKREMENTELLE
`renderGridCircles()` (siehe Prüfprotokoll P1/P8). Zusätzlich greift eine
**Change-Detection**: Unveränderte Live-Circle-Sets zwischen Ticks lösen KEINEN
Re-Render aus, und beim Wechsel auf eine neue Live-Bar werden die Kreise der
VORHERIGEN Live-Zeit aus dem Cache entfernt (`_lastLiveOverlayTime`):

```javascript
function updateLiveCandle(json) {
    if (!candleSeries || isUpdatingChart) return;
    try {
        var c = JSON.parse(json);
        if (!c || typeof c.time !== 'number' || isNaN(c.time)) return;
        if (c.symbol !== undefined && c.symbol !== null && c.symbol !== currentSymbol) return;
        if (c.timeframe !== undefined && c.timeframe !== null && c.timeframe !== currentTimeframe) return;
        if (c.open === null || c.high === null || c.low === null || c.close === null) return;

        // Live-Candle in Serie aktualisieren
        candleSeries.update(c);
        lastClosePrice = c.close;
        updateCountdownDisplay();

        // GENERISCHES LIVE-OVERLAY RENDERING (Open/Closed-Dispatcher)
        if (c.overlays && Array.isArray(c.overlays) && c.overlays.length > 0) {
            applyLiveOverlays(c.overlays);
        }
    } catch(e) {
        console.error('[updateLiveCandle] Error:', e);
    }
}

// Generischer Overlay-Dispatcher (P14-03-E): Spätere Plugins docken über neue
// kind/layer-Werte an, ohne updateLiveCandle zu ändern.
function applyLiveOverlays(overlays) {
    if (typeof renderGridCircles !== 'function') return;
    var circles = [];
    for (var i = 0; i < overlays.length; i++) {
        var o = overlays[i];
        if (o && o.kind === 'circle' && typeof o.time === 'number' &&
            typeof o.price === 'number' && !isNaN(o.time) && !isNaN(o.price)) {
            circles.push(o);
        }
    }
    if (circles.length === 0) return;

    // FLACKER-FIX (P8): Change-Detection – identische Live-Circle-Sets zwischen
    // Ticks (gleiche Level-Hits, gleiche Farben) lösen KEINEN Re-Render aus.
    var nowJson = JSON.stringify(circles);
    if (nowJson === _lastLiveCirclesJson) return;
    _lastLiveCirclesJson = nowJson;

    // Merged-Render: nur die Live-Zeit ersetzen, historische Circles behalten.
    var liveTime = circles[0].time;
    // FLACKER-FIX (P8): Bei neuer Live-Bar zusätzlich die Kreise der VORHERIGEN
    // Live-Zeit entfernen (sonst hängen veraltete Live-Kreise der Vor-Bar).
    if (_lastLiveOverlayTime !== null && _lastLiveOverlayTime !== liveTime) {
        _gridCirclesCache = _gridCirclesCache.filter(function(x) { return x.time !== _lastLiveOverlayTime; });
    }
    _lastLiveOverlayTime = liveTime;
    _gridCirclesCache = _gridCirclesCache.filter(function(x) { return x.time !== liveTime; });
    for (var j = 0; j < circles.length; j++) { _gridCirclesCache.push(circles[j]); }
    renderGridCircles(_gridCirclesCache);
}
```

`_gridCirclesCache` wird in `applyFullChartUpdate()` beim Setzen von `data.gridCircles`
befüllt: `_gridCirclesCache = (data.gridCircles || []).slice();` (neben
`rawCandleData = validCandles;`).

##### 4. `chart/indicators/grid_liquidity.py` – Feature-Store primär + generische Hooks:

a) `read_proximity_from_feature_store()` um den Parameter `feature_id` generalisieren
   (Standard `'proximity'` – spätere Plugins lesen über denselben Lesepfad):

```python
def read_proximity_from_feature_store(
    self,
    symbol: str,
    timeframe: str,
    limit: Optional[int] = None,
    db_path: Optional[str] = None,
    feature_id: str = "proximity",
) -> List[Dict[str, Any]]:
    # ... SQL: WHERE symbol=? AND timeframe=? AND feature_id=? ...
```

b) Feature-Store-Lesepfad PRIMÄR in den bestehenden `calculate()`-Body integrieren
   (rein additiv; `super().calculate()` existiert NICHT – `BaseIndicator.calculate` ist
   `@abstractmethod`, siehe Prüfprotokoll P4). Nur bei leerem Feature-Store auf die
   Pipeline-Hit-Circles zurückfallen:

```python
# Im try-Body von calculate(), NACH dem Auslesen von grid_lines:
prox_result = results.get("prox_1") or {}
prox_crp = prox_result.get("chart_render_payload") or {}

# P14-03-E (Schritt 4): PRIMÄR gecachte Proximity-Hits aus dem feature_store lesen.
cached_circles = self.read_proximity_from_feature_store(
    self._symbol or "", self._timeframe or ""
)
if cached_circles:
    circles = cached_circles
else:
    circles_raw = prox_crp.get("hit_circles") or []
    # ... bestehende Farb-/priority-Anreicherung unverändert weiterführen ...
```

c) Generische Live-Overlay-Hooks (Open/Closed) ergänzen:

```python
# chart/indicators/base_indicator.py – generischer Hook (Basis-Default []):
def get_live_overlays(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
    """P14-03-E: Liefert die Live-Overlays des Plugins als Liste von Overlay-Items
    {kind, layer, time, price, color, priority, ...}. Basis-Default: [].
    Plugin-Klassen überschreiben diesen Hook (Open/Closed)."""
    return []

# chart/indicators/grid_liquidity.py – Überschreibung (Circle-Overlays):
def get_live_overlays(self, candle: Dict[str, Any]) -> List[Dict[str, Any]]:
    pts = self.update_live_candle(candle)
    return [dict(p, kind="circle", layer=self.indicator_id) for p in pts]

# chart/indicators/grid_liquidity.py – Live-Bar merken (Pflicht-Re-Injektion):
def remember_live_time(self, ts: int) -> None:
    """P14-03-E: Merkt eine offene Live-Bar-Zeit im _known_times-Set, damit der
    New-Candle-Callback über den Refresh hinweg NICHT erneut feuert (Flacker-Fix)."""
    try:
        self._known_times.add(int(ts))
    except (TypeError, ValueError):
        pass
```

#### E. Headless Validierung (Ergänzung)

Erstelle und führe aus: `test/check_p14_live_fixes.py` (headless, kein `exec_()`):

1. Simuliere das Senden von 10 Live-Ticks im Abstand von 500 ms (Mock `update_live_candle`).
2. Verifiziere, dass `refresh_chart_data()` 0-mal aufgerufen wurde.
3. Verifiziere, dass `_time_real_to_cont` kontinuierlich gewachsen ist (kein `clear()`).
4. Verifiziere, dass `_process_plugin_bars_resilient()` aufgerufen wurde und den
   `feature_store` beschreibt (feature_id='proximity'-Zeile vorhanden).
5. Verifiziere, dass `update_live_candle()` des Indikators Live-Punkte liefert und diese
   als `live_circles` im Payload ankommen.

#### F. Prüfprotokoll (Korrekturen am Rohentwurf)

Die Anweisungen wurden gegen den Quellcode geprüft; Abweichungen sind korrigiert
eingearbeitet:

- **P1 (JS-Render):** `renderGridCircles(live_circles)` allein löscht die historischen
  Circles (`clearGridCircles()` intern). Korrektur: Merged-Render über `_gridCirclesCache`
  (siehe D.3).
- **P2 (Indikator-Rückgabe):** `GridLiquidityIndicator.update_live_candle()` liefert eine
  LISTE `[{time, price, color, priority}]`, kein Dict mit `hit_circles`.
  `get_live_overlays()` verpackt diese Liste in generische Overlay-Items
  (`kind='circle'`); `chart_win` greift NICHT mehr direkt auf `_live_points` zu
  (siehe D.4c).
- **P3 (LiveAnalyzer-Context):** `self.shared_state` existiert nicht – korrekt ist
  `self._live_shared_state` bzw. der bereits vorhandene `self._live_context` (siehe D.2).
- **P4 (calculate-Super):** `super().calculate(df, params)` existiert nicht
  (`BaseIndicator.calculate` ist `@abstractmethod`); `self._last_lines` existiert nicht.
  Korrektur: Feature-Store-Read additiv in den bestehenden `calculate()`-Body (siehe D.4).
- **P5 (New-Candle-Refresh bleibt + RE-INJEKTION IST PFLICHT):** Der
  `GridLiquidityIndicator` ruft über `set_new_candle_callback(self.refresh_chart_data)`
  genau EINEN debounced Refresh pro neuer Kerze auf (Grid-Cache-Neuaufbau) – dieser ist
  NICHT zu entfernen. Entfernt wird nur der Refresh bei JEDEM Tick in
  `chart_win.update_live_candle()`. DA der Refresh die Maps in `_do_refresh_chart_data`
  komplett neu baut (Z. 678-679) und `applyFullChartUpdate` den Chart nur aus DB-Kerzen
  neu aufbaut, MUSS die offene Live-Kerze (noch nicht in DuckDB) beim Refresh zwingend
  re-injiziert werden: (1) in `_time_real_to_cont`/`_time_cont_to_real`, (2) in
  `continuous_candles` (mit letzter Live-OHLC aus `_live_candle_cont`), (3) in die
  `_known_times` des Indikators via `remember_live_time()`. Erst dann feuert der
  New-Candle-Callback pro neuer Kerze GENAU 1× und die Flacker-Schleife endet.
  Siehe D.1d.
- **P6 (Generisches Overlay-Schema):** Statt `live_circles` (circle-spezifisch) transportiert
  der Live-Tick `c.overlays` mit `{kind, layer, time, price, color, priority}`. Der JS-
  Dispatcher `applyLiveOverlays()` routet je `kind`; der Python-Hook
  `BaseIndicator.get_live_overlays()` (Default `[]`) ist die offene Erweiterungsstelle für
  spätere Indikator-Plugins (Open/Closed). Siehe D.1c/D.3/D.4c.
- **P7 (Overlay-Zeit-Mapping):** Live-Overlays tragen die reale, gerundete Bar-Zeit des
  Indikators; `chart_win` mappt sie beim Einsammeln über `_time_real_to_cont` auf die
  kontinuierliche Chart-Zeit, bevor sie als `c.overlays` an JS gehen (siehe D.1c).
- **P8 (Flacker-Fix – inkrementelles Circle-Rendering & Change-Detection):** User-Befund
  nach D.1–D.4: Circles werden live korrekt gesetzt und das generelle Flackern ist weg,
  ABER sobald die Proximity-Bedingung erfüllt ist, flackert es erneut bei jedem Tick.
  Ursache: `renderGridCircles()` rief intern `clearGridCircles()` auf, das ALLE
  Circle-Serien via `removeSeries()` entfernte und neu aufbaute – bei jedem Live-Tick
  mit erfüllter Bedingung ein Full-Layer-Rebuild (destruktiv, kein Einzelfall).
  Fix (rein JS, additiv):
  1. `03_chart_rendering.js`: `renderGridCircles()` ist jetzt INKREMENTELL – neue
     Registry `_circleLevelSeries` (01_core.js) je Level-Preis; bestehende Level werden
     per `series.setData()`/`plugin.setMarkers()` in-place aktualisiert, nur verschwundene
     Level entfernt, nur neue erzeugt. `clearGridCircles()` leert zusätzlich die Registry.
     Alle Call-Sites (`applyFullChartUpdate` Schritt 6, `applyLiveOverlays`) bleiben
     unverändert.
  2. `04_live_updates.js`: `applyLiveOverlays()` – Change-Detection über
     `_lastLiveCirclesJson` (JSON-Vergleich): identische Circle-Sets zwischen Ticks
     lösen KEINEN Re-Render aus. `_lastLiveOverlayTime` entfernt beim Live-Bar-Wechsel
     auch die Kreise der VORHERIGEN Live-Zeit aus dem Cache. Beide werden in
     `applyFullChartUpdate` zurückgesetzt (`'[]'` bzw. `null`).
  Verifikation: `node --check` auf allen 3 JS-Dateien, headless
  `test/check_p14_grid_incremental.js` (14 Checks: Serien-Identität bei identischen/
  Live-Updates, nur verschwundene Level entfernt, leere Liste räumt auf, Change-Detection,
  Bar-Wechsel-Cache), Regression `check_p14_live_fixes.py` (14/14), `check_grid_parity.py`,
  `check_p14_precision_levels.py`, `check_time_utils.js`, `check_resolve_realtime.js`.
- **P9 (Flacker-Fix – New-Candle-Callback-Zyklus nach neuer Kerze):** User-Befund nach P8:
  direkt nach dem Erzeugen einer neuen Kerze flackert der Chart periodisch (~500ms) –
  die neue Kerze wird aufgebaut, aber abwechselnd wird die ALTE Kerze ohne Neuplot
  (meist als dünne Linie) gezeigt; das Flackern verschwindet erst nach einem
  Service-Update. ROOT CAUSE (2 Stellen in `chart_win.py`):
  1. **Reihenfolge-Fehler:** `_do_refresh_chart_data` rief `liq_ind.remember_live_time()`
     VOR dem `calculate()`-Loop auf. `calculate()` setzt `self._known_times` aus den
     DB-Bars zurück (`grid_liquidity.py: self._known_times = self._compute_known_times(df)`)
     – die offene Live-Bar (noch NICHT in DuckDB) ging dabei verloren. Damit feuert der
     New-Candle-Callback bei JEDEM Live-Tick (LiveTickWorker, main.py: 500ms) erneut →
     debounce (400ms) → Chart-Rebuild → Flackern im Wechsel Live-Plot (neue Kerze) <-> Rebuild
     (alte/leere Kerze). Erst wenn die Live-Bar durch einen Service-Update in der DB steht,
     enthält `_known_times` sie → Callback stoppt → "Flackern verschwindet nach Service-Update".
  2. **Hardcoding:** Die Re-Injektion war auf `self.indicators.get("grid_liquidity")`
     hardcoded (Verstoß gegen die Generik-Regel).
  3. **Veraltete Live-Kerze:** `_live_candle_cont` wurde nur beim ERSTEN Tick einer neuen
     Bar gesetzt – der Rebuild reinjizierte die Kerze mit veraltetem OHLC-Stand (dünne Linie).
  FIX (generisch):
  1. `base_indicator.py`: `remember_live_time(ts)` als generischer Base-Hook (no-op Default),
     analog zu `get_live_overlays` (Open/Closed).
  2. `chart_win.py`: neue Methode `_reinject_live_bar_to_indicators()` – führt die
     Live-Bar-Zeit generisch über ALLE Indikatoren mit `remember_live_time()`-Hook wieder ein
     (kein Plugin-Sonderfall). Aufgerufen NACH JEDEM `calculate()`-Loop
     (`_do_refresh_chart_data` UND `render_indicators`).
  3. `chart_win.py update_live_candle`: `_live_candle_cont` wird bei JEDEM Tick der offenen
     Bar aktualisiert (aktueller OHLC-Stand für die Re-Injektion).
  Verifikation: `py_compile` auf den 3 Python-Dateien, headless
  `test/check_p14_flacker_zyklus.py` (4 Checks: Base-Hook, Callback-1x-Logik +
  calculate-Resetszenario + remember_live_time bricht Zyklus, Generik über alle Indikatoren,
  statische Regression Reihenfolge/Hardcoding/`_live_candle_cont`), Regression
  `check_p14_live_fixes.py` (14/14), `check_p14_grid_incremental.js` (14/14),
  `check_grid_parity.py`, `check_p14_precision_levels.py`, `check_time_utils.js`,
  `check_resolve_realtime.js`.

