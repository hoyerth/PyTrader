# Phase 21: Fachliche Feinabstimmung Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 21)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase21_step1`, `phase21_step1` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Codebase-Formatierung:** Exakt **4 Leerzeichen** Einrückung (PEP8-Standard) und **exakt 1 Leerzeile** Spacing zwischen Methoden und Funktionsblöcken. Kein Umformatieren unbeteiligter Altbestand-Dateien.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`. `MasterTree`-Selektionen übergeben aufgelöste `feature_ids` sowie `instance_hashes` direkt an `view_model.set_feature_ids(ids, hashes)`.
5. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`db/db_pool.py`) – eine Verbindung pro Thread und DB-Datei. Die Fassade `db_service.py` bleibt als Re-Export-Wrapper für bestehende Caller erhalten.
7. **Tree-Persistenz & Kategorisierung:** 
   - Service-Kategorien werden primär im Code/Plugin über `metadata["category"]` (Slash-separierter Ordnerpfad) deklariert.
   - Ordner-Kategorien für Service-Sets werden im `category`-Feld der `ServiceSetDefinition` / des `save_set()`-Payloads persistiert.
   - Parameter-Varianten (Clones/Presets) werden transparent über `indicator_presets` und `instance_hash` im FeatureStore geführt.
8. **Wanduhr-Garantie (Invariante 7):** MT5-Epochs sind bereits Berlin-Wanduhr-encoded. SQL-Extraktionen (Heatmap, DOW, Hour, Date) nutzen strikt `bar_time AT TIME ZONE 'UTC'`, um eine fehlerhafte automatische Umrechnung durch DuckDB in Lokalzeiten zu unterbinden.
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

# 21.03 – Multi-Timeframe Focus & Context (MTF-FC v4)

---

## 🎯 1. Zielstellung & System-Anforderungen

Das MTF-FC-System bietet eine mathematisch und visuell konsistente Multi-Timeframe-Analyse für PyTrader. Es löst Inkongruenzen zwischen Kerzen- und Service-Timeframes, verhindert UI-Flackern beim Zoomen, schützt vor Datenverlusten bei engem Zoom-Fokus und führt den Benutzer transparent durch unvollständige Datenhistorien.

* **Hinweis:** „MTF-FC v4“ ist eine interne Revisionsbezeichnung der Spezifikation (iterativer Entwurfsprozess v1 → v2 → v3 → v4). Es fehlen keine früheren Quellcode-Kapitel; das Modul ordnet sich als Kapitel 21.03 nahtlos nach der DB-Maintenance (21.02) in die Dokumentationsstruktur ein.

---

## 🏗️ 2. Schichten-Architektur & System-Schnittstellen

Das System trennt strikt zwischen drei Funktionsschichten:

┌────────────────────────────────────────────────────────────────────────────────────────┐
│  SCHICHT 3: UI- / Chart-Orchestrierung (Frontend & PyLWC)                              │
│  - MtfFilterBarWidget (Data-TF, Chart-TF, Range, View-Templates, Confluence-Slider)   │
│  - Hysterese-Engine (Range-Monitoring, Breadcrumb-Puls)                                │
│  - Interaktive Badges, Geister-Marker & Temporary Guard Override                       │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼ (Lese-Pfade & EventBus)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  SCHICHT 2: MTF-FC Data Provider & Partition Manager (Middleware)                    │
│  - Namespace-Isolierung: shared_state["mtf_fc"] (Active TF, Boundaries, Generation)     │
│  - Cache-Versionierung: (symbol, timeframe, partition) + source_max_timestamp          │
│  - Partitioned DuckDB-Reads (fetch_daily_ohlc, fetch_ohlcv_snapshot)                    │
│  - Precision-Aware Boundary Policy (Native vs. Fallback Flags)                         │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼ (Feature Calculate & Pipeline)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  SCHICHT 1: Backend- & Analytics-Engine (Core Infrastructure)                         │
│  - ServiceSetEvaluator (execute_set_resilient() vs. execute_set() Fail-Fast)           │
│  - PluginExecutor & PluginContext.shared_state                                         │
│  - LiveAnalyzer (tail(2)-Evaluation & RAM-State-Buffer)                                │
│  - SchemaMigrator (Transparente In-Memory-Migration & Rollback-Schutz)                 │
└────────────────────────────────────────────────────────────────────────────────────────┘


---

## 🚦 3. Formale State-Machine & Prioritäts-Kette

### 3.1 Zustandstabelle (Data-TF vs. Chart-TF)

| Data-TF (Filter) | Kaskade (Auto) | Resultierendes Chart-TF | System-Verhalten / Guard-Aktion |
| --- | --- | --- | --- |
| **🌐 Multi (M1..D1)** | ⚡ Auto | **Dynamisch (M1..D1)** | Standard. Kaskade wählt TF vollautomatisch nach Zoom-Level. |
| **🔒 Fixiert auf M15** | ⚡ Auto | **$\le$ M15 (M1, M5, M15)** | **Guard aktiv:** Chart-TF schaltet nie höher als M15. Kaskade nach unten erlaubt. |
| **🔒 Fixiert auf H4** | ⚡ Auto | **$\le$ H4 (M1..H4)** | **Guard aktiv:** Schaltet bei Zoom-Out maximal bis H4. D1-Upgrade gesperrt. |
| **🔒 Fixiert auf M15** | 🔒 Manuell D1 | **M15 (Forced)** | **Inkongruenz-Warnung:** *"D1-Kerzen nicht möglich, da Data-TF auf M15 fixiert. Kerzen auf M15 gesetzt."* |
| **Jeder Fix-State** | 📍 Klick Geister-Marker (D1) | **D1 (Temporär)** | **Guard Override:** Temporary Unlock mit Reset-Badge `[ 🌐 Data-TF gelockert ]`. |

### 3.2 Prioritäts-Kette (Konflikt-Hierarchie)

Trifft die Steuerung auf widersprüchliche Eingaben oder Beschränkungen, entscheidet folgende Kette (Ebene 1 gewinnt immer):

1. **Ebene 1 – Hard Data Availability Guard:** Fehlen M1-Daten vor der tatsächlichen Daten-Grenze des Symbols (z. B. für frisch angelegte Symbole oder nach einem partiellen History-Purge), erzwingt das System `coverage_status = "fallback"` mit nächst-höherem TF (z. B. H1). Die Grenze wird dynamisch ermittelt: `m1_available_from = get_earliest_timestamp(symbol, "M1")` (reale SILVER-Daten: M1-Historie ab 2013-06-05). Die Boundary-Policy greift exakt an dem Punkt, an dem das älteste M1-Bar des gewählten Symbols liegt. Eine höhere Aggregationsstufe darf niemals als M1 deklariert werden ($H1 \to M1$ ist strikt verboten).
2. **Ebene 2 – Temporary User Override (Geister-Marker Klick):** Klickt der Nutzer bei fixiertem `Data-TF = M15` auf einen D1-Geister-Marker, greift die Transaktions-Semantik:
* `override.active = True`
* `override.previous_data_tf = "M15"`
* `override.target_tf = "D1"`
* Das `Data-TF` wird gelockert und ein Badge `[ 🌐 Data-TF temporär gelockert auf D1 | Reset ]` erscheint. Klick auf *Reset* stellt exakt `previous_data_tf` wieder her.

3. **Ebene 3 – Fixed Data-TF Guard:** Ohne temporären Override erzwingt ein auf M15 fixiertes `Data-TF`, dass das `Chart-TF` maximal M15 oder feiner ist.

4. **Ebene 4 – Auto Cascade:** Standard-Hysterese schaltet den Chart-TF basierend auf der Viewport-Breite.

5. **Ebene 5 – Visual Rendering Preference:** Benutzerdefinierte Farbschemas und Labels.

---

## 🧱 4. Die 3 Architektur-Säulen

### Säule 1: MtfFilterBarWidget & Control-Panel

1. **Steuerungselemente:**
* **Source-Data-TF:** `🌐 Alle Timeframes` (Multi) vs. `🔒 Fixiert auf [TF]`.

* **Chart-Overlay-TF:** `⚡ Auto (Kaskade)` vs. `🔒 Manuell Fix`.

* **Range-Picker:** Presets (`24h`, `7d`, `30d`, `YTD`) & Benutzerdefiniert.

* **View-Templates (Presets):** Speichern und Laden von kompletten Filter-Konfigurationen. Das `MtfFilterBarWidget` nutzt den bestehenden `SchemaMigrator` (`analytics/engine/schema_migrator.py`), um gespeicherte Preset-JSONs in-memory zu validieren und abwärtskompatibel um neue TFs/Session-Keys zu erweitern (Payload-Key `mtf_fc_schema_version = "1.0.0"`).
* **Tabellen-Sortierung:** Dropdown für `[ Datum 🠇 ]`, `[ Signal-Stärke 🠇 ]`, `[ TF 🠅 ]`.

2. **Session-Filter & DST-Normalisierung:**
* Handelssessions (London, New York, Tokio) als Farbbalken im M1/M5-Zoom.
* **DST-Invariante:** Alle Session-Grenzen werden strikt in **UTC-Epochs** berechnet und erst beim Rendern formatiert (Invariante 7).

3. **Transparente Historien-Anzeige & Boundary Policy:**
* Anzeigeelement: `ℹ️ M1 verfügbar ab DD.MM.JJJJ`.
* **Boundary Policy:** Zoomt der Nutzer vor die Verfügbarkeitsgrenze, zeigt der Chart nahtlos H1-Kerzen mit dem Flag `coverage_status = "fallback"` und der Schraffur *"Keine M1-Rohdaten für diesen Zeitraum"* (keine Lücke, kein Absturz).

4. **Confluence-Gewichtung & Normalisierung:**
* **Formel:** $Score_j = \sum (W_{TF} \cdot Signal_{TF})$ mit vollständigem Gewichtungs-Schema:
  * $W_{\text{D1}} = 3.0$
  * $W_{\text{H4}} = 2.5$
  * $W_{\text{H1}} = 2.0$
  * $W_{\text{M15/M30}} = 1.5$
  * $W_{\text{M5}} = 1.2$
  * $W_{\text{M1}} = 1.0$
* Die Gewichte fließen **un-normalisiert** in die Summe ein und werden anschließend durch die **Constant-Matrix-Policy / Min-Max-Skalierung** auf das Farb-Intervall $[0.0, 1.0]$ abgebildet.
* **Constant-Matrix-Policy (Min-Max-Fix):** Ist $\text{max\_score} == \text{min\_score}$, gilt $\text{normalized\_score} = 0.5$ (verhindert Divisionen durch Null).
* **Volatilitäts-Adaption (Toggle) mit Clamp-Protection:**

$$ratio = \text{clamp}\left(\frac{\text{ATR}_{\text{TF}}}{\text{ATR}_{\text{Current}}}, \, 0.2, \, 5.0\right)$$

Bei $\text{ATR}_{\text{Current}} \le 10^{-6}$ wird die Anpassung deaktiviert ($ratio = 1.0$).

### Säule 2: Smart PyLWC-Zoom-Kaskade & Performance

1. **Hysterese-Schaltlogik & Parameter:**
* **Haupt-Stufen der Auto-Kaskade:** M1 → M5 → H1 → H4 → D1 (prägnante Stufen gegen visuelles Dauer-Flackern und unnötige Cache-Sprünge bei kleineren Zoom-Bewegungen).
* **Zoom-Bänder (Auto):**
  * **Band 1 ($< 2.0$ Tage):** Umschaltung M1 ↔ M5
  * **Band 2 ($2.0$ bis $10.0$ Tage):** Umschaltung M15 ↔ H1 (Fein-Stufe M15)
  * **Band 3 ($10.0$ bis $35.0$ Tage):** H4
  * **Band 4 ($> 35.0$ Tage):** D1
* **Schwellwerte (Hysterese zwischen den Bändern):**
  * `ZOOM_OUT_THRESHOLD_M1` = $3.5\text{ Tage}$ ($84.0\text{ h}$) — M1/M5 → H1 (Zoom-Out)
  * `ZOOM_IN_THRESHOLD_M1` = $2.0\text{ Tage}$ ($48.0\text{ h}$) — H1 → M1/M5 (Zoom-In)
  * `ZOOM_OUT_THRESHOLD_H4` = $10.0\text{ Tage}$ — H1 → H4 (Grenze Band 2→3)
  * `ZOOM_OUT_THRESHOLD_H1` = $35.0\text{ Tage}$ — H4 → D1 (Zoom-Out)
  * `ZOOM_IN_THRESHOLD_H1` = $28.0\text{ Tage}$ — D1 → H4 (Zoom-In)
* `CROSSFADE_DURATION_MS` = $250\text{ ms}$ (UI-Parameter)
* **Manueller Modus (`Chart-TF` = 🔒 Fix):** Erlaubt das Erzwingen *jeder* beliebigen Zwischenstufe (z. B. M30 oder H2) – M15/M30/H2 sind nicht verboten, sondern dienen als Fein-Stufen innerhalb der Bänder.

Zoom-Out (Zeitfenster vergrößern):
   M1/M5 ───( > 3,5 Tage )───> H1 ───( > 10,0 Tage )───> H4 ───( > 35 Tage )───> D1

Zoom-In (Zeitfenster verkleinern):
   D1   ───( < 28 Tage )───> H4  ───( < 10,0 Tage )───> H1  ───( < 2,0 Tage )───> M1/M5


2. **Transition Guard & Telemetrie:**
* Ein Umschalten erfolgt erst, wenn $\text{now}() - transition\_started\_at \ge \frac{CROSSFADE\_DURATION\_MS}{1000.0}$.
* Jedes Kaskaden-Event emittiert ein strukturiertes Telemetrie-Log (`trigger`, `from_tf`, `to_tf`, `range_days`).
* **Puls-Breadcrumb:** Transparenter Badge oben rechts im Canvas (`[ ⚡ Kerzen: M5 ]`), der bei Umschaltung kurz hellblau aufleuchtet.


3. **RAM-Caching & Event-basierte Invalidierung:**
* Nutzt vorgepufferte Tages- und Stunden-Snapshots: `fetch_daily_ohlc` = echte SQL-Aggregation über das Wanduhr-Datum (Tages-Ohlc); „Stunden-Snapshot“ = direkte H1-Roh-Bar-Abfrage via `fetch_ohlcv_snapshot(symbol, "H1", limit)` (read-only auf `ohlcv_bars` in `market_data.duckdb`).
* **Event-Partitionierung bei Late-Arriving Ticks:**

$$affected\_partition = partition(symbol, timeframe, t_{\text{event}})$$

Nachträglich eingehende Ticks invalidieren ausschließlich die RAM-Partition ihrer eigenen Event-Zeit $t_{\text{event}}$, nicht den gesamten Cache.

### Säule 3: Interaktives Layering & Geister-Marker

1. **Interaktive TF-Badges:**
* Klick auf ein Badge (`[ H4-Swing ]`) filtert die aktuelle Ansicht synchron auf diesen Timeframe.
* Strg + Klick ermöglicht Multi-Select.

2. **Geister-Marker (Off-Screen Level):**
* Übergeordnete Level (z. B. D1-Widerstand) außerhalb des Zoom-Blicks werden am Rand des Viewports als verblasster Pfeil gerendert: `▲ D1-Widerstand (27.85)`.
* Klick löst den Guard-Override nach Ebene 2 aus und animiert den Viewport sanft zum Ziel-Level.

---

## 💾 5. Data-Provider & `shared_state`-Spezifikation

Das System nutzt einen dedizierten, isolierten Namespace unter `PluginContext.shared_state["mtf_fc"]`:

shared_state["mtf_fc"] = {
    "active_data_tf": "M15",
    "active_chart_tf": "M5",
    "viewport_range": {"from_ts": 1785500000, "to_ts": 1785972000},  # ~5,4 Tage
    "cascade_state": {
        "current_tf": "M5",
        "candidate_tf": "H1",
        "direction": "zoom_out",
        "transition_started_at": 1785971900.5,
        "last_transition_at": 1785970000.0,
        "range_days": 5.4,  # > 3.5 Tage (auslösender Zoom-Out-Bereich)
    },
    "history_boundaries": {
        "m1_available_from": get_earliest_timestamp("SILVER", "M1"),  # dynamisch (real: 2013-06-05)
        "coverage_status": "fallback",    # "native" | "fallback"
        "source_tf": "H1",
    },
    "cache_generation": 42,
    "temporary_guard_override": {
        "active": True,
        "previous_data_tf": "M15",
        "target_tf": "D1",
        "reason": "ghost_marker_click",
    }
}


---

## 🧼 6. Fehler-Differenzierung & Resilienz-Mapping

Das System differenziert strikt zwischen fünf Fehlerklassen und verknüpft sie mit der bestehenden Backend-Resilienz (`ServiceSetEvaluator`):

                      ┌────────────────────────────────────────┐
                      │   Eingehender Fehler / Abweichung      │
                      └───────────────────┬────────────────────┘
                                          │
        ┌─────────────────┬───────────────┼───────────────┬────────────────┐
        ▼                 ▼               ▼               ▼                ▼
 [ DATA_MISSING ]  [ CACHE_STALE ] [ CACHE_CORRUPT ] [ SERVICE_FAILED ] [ NO_SOURCE ]
        │                 │               │               │                │
        ▼                 ▼               ▼               ▼                ▼
 Boundary-Policy    Kaskade invalid   Cache verwerfen   Bestehender State-   UI-Degraded-
 (Umschaltung auf   & Partial Re-     & DB-Rebuild      Fallback des        State mit Lade-
 nächstes TF mit    Load über         anstoßen          ServiceSet-         Hinweis &
 Fallback-Badge)    Event-Time-                         Evaluators          Retry-Button
                    Partition                           (RAM-Quarantäne)

---

## 📊 7. Headless-Validierung (`test/test.py`)

Folgende Tests verifizieren das System in `test/test.py` ohne GUI-Ausführung:

1. **Hysterese-Boundary-Test:**
* Testet exakt die Schwellwerte: $1.99\text{ d} \to M1$, $2.01\text{ d} \to$ kein Wechsel, $3.49\text{ d} \to$ kein Wechsel, $3.51\text{ d} \to H1$.


2. **20-fach Anti-Oszillations-Test:**
* Oszilliert den Viewport 20-mal im Fenster $[1.9\text{ d}, 3.6\text{ d}]$ und verifiziert, dass `transition_started_at` fehlerfreies Schalten garantiert.


3. **M1-Historien-Boundary-Test:**
* Prüft Daten vor der dynamischen M1-Grenze des Symbols (`get_earliest_timestamp(symbol, "M1")`) auf `coverage_status = "fallback"` und `source_tf = "H1"`.


4. **State-Machine & Guard-Override-Test:**
* Fixiert `Data-TF = M15`, simuliert Klick auf D1-Geister-Marker, prüft `previous_data_tf = M15` sowie die korrekte Wiederherstellung nach `Reset`.


5. **Constant-Matrix & Weight-Effect-Test:**
* Prüft, dass eine flache Matrix den Wert $0.5$ liefert und dass $W_{\text{D1}}=3.0$ vor der Min-Max-Skalierung die proportionale Übermacht behält.


6. **Late-Arriving Tick Partition-Test:**
* Injiziert einen historischen Tick ($t_{\text{event}} = \text{vor 5 Tagen}$) und verifiziert, dass exakt die betroffene Zeit-Partition invalidiert wird.


7. **Service-Failure-Degradation-Integrationstest:**
* Validiert, dass drei aufeinanderfolgende Fehler von Service A zur RAM-Quarantäne führen, Service B weiterläuft, Service C `dependency_failed` meldet, der alte `shared_state` erhalten bleibt und `reset()` die Quarantäne aufhebt.

---

## 📋 8. Umsetzungsplan (Übersicht & Reihenfolge)

Der Umsetzungsplan folgt der Schichten-Architektur **bottom-up** (Schicht 2 → Schicht 3) und ist strikt nach Abhängigkeiten gereiht: Jeder Schritt baut auf den vorhergehenden auf und ist einzeln headless verifizierbar (Grundsatz 2). Die bestehenden Schicht-1-Bausteine (`ServiceSetEvaluator.execute_set_resilient()`, `PluginContext.shared_state`, `LiveAnalyzer` tail(2), `SchemaMigrator`) werden **nicht verändert**, sondern konsumiert (Grundsatz 11, Open/Closed).

| Schritt | Kapitel | Inhalt | Baut auf | Verifikation (§7) |
|---|---|---|---|---|
| 1 | 21.03.01 | MTF-FC Data Provider & `shared_state`-Namespace (Schicht 2) | – | Namespace-/DB-Smoke |
| 2 | 21.03.02 | Boundary Policy & Historien-Detection | 21.03.01 | Test 3 |
| 3 | 21.03.03 | Hysterese-Kaskaden-Engine (Auto Cascade) | 21.03.01 | Test 1 + 2 |
| 4 | 21.03.04 | Confluence-Gewichtung & Normalisierung | 21.03.01 | Test 5 |
| 5 | 21.03.05 | State-Machine & Prioritäts-Kette (Guards & Override) | 21.03.01, 21.03.02 | Test 4 |
| 6 | 21.03.06 | Event-Partitionierung & Cache-Invalidierung | 21.03.01 | Test 6 |
| 7 | 21.03.07 | MtfFilterBarWidget & Control-Panel (UI) | 21.03.01, 21.03.02, 21.03.05 | py_compile + Inspektion |
| 8 | 21.03.08 | Chart-Integration: Kaskade, Puls-Breadcrumb, Historien-Anzeige | 21.03.03, 21.03.07 | node --check + py_compile + Inspektion |
| 9 | 21.03.09 | Interaktives Layering: TF-Badges & Geister-Marker | 21.03.05, 21.03.08 | node --check + py_compile + Inspektion |
| 10 | 21.03.10 | Abschluss: Integrationstest & Cleanup | 21.03.01–21.03.09 | Test 7 + Gesamtlauf |

### Begründung der Reihenfolge

1. **21.03.01 → 21.03.02:** Die Boundary-Policy liest die Daten-Grenzen aus dem Data Provider (`get_earliest_timestamp`) – ohne Provider keine Boundary.
2. **21.03.03–21.03.06:** Pure-Logik-Engines (Kaskade, Confluence, Guards, Partitionierung) hängen nur am State/Provider und sind headless vollständig testbar, bevor UI entsteht.
3. **21.03.07:** Das Control-Panel konsumiert State, Boundary und SchemaMigrator (kein SQL in UI, MVVM-Grundsatz 4).
4. **21.03.08:** Die Kaskaden-Anbindung an PyLWC braucht die Engine (21.03.03) und das Panel (21.03.07).
5. **21.03.09:** Badges/Geister-Marker brauchen die State-Machine (21.03.05) und das Chart-Rendering (21.03.08).
6. **21.03.10:** Integrationstests laufen erst, wenn alle Bausteine stehen; danach Cleanup von `test/` (Grundsatz 10).

---

# 21.03.01 – MTF-FC Data Provider & `shared_state`-Namespace (Schicht 2)

## 🎯 Ziel

Bereitstellung des dedizierten, isolierten Namespace `PluginContext.shared_state["mtf_fc"]` (Spezifikation §5) sowie des Datenzugriffs-Moduls mit Cache-Versionierung und Partitioned Reads. Grundlage für alle weiteren Schritte (Boundary, Kaskade, Guards, UI).

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_state.py` – Default-Factory/Struktur des `shared_state["mtf_fc"]`-Namespaces.
- **Neu:** `analytics/engine/mtf_fc_provider.py` – Cache-Versionierung `(symbol, timeframe, partition)` + `source_max_timestamp`, `get_earliest_timestamp(symbol, timeframe)`, gekapselte Reads über `fetch_daily_ohlc` / `fetch_ohlcv_snapshot` (read-only, DbPool).
- **Geändert:** keine Bestands-Kernklassen (Grundsatz 11).

## 🛠️ Umsetzungsschritte

1. `MtfFcState` als Default-Dict mit exakt den Keys aus §5:
   - `active_data_tf`, `active_chart_tf`, `viewport_range` (`from_ts`, `to_ts`)
   - `cascade_state` (`current_tf`, `candidate_tf`, `direction`, `transition_started_at`, `last_transition_at`, `range_days`)
   - `history_boundaries` (`m1_available_from`, `coverage_status`, `source_tf`)
   - `cache_generation`, `temporary_guard_override` (`active`, `previous_data_tf`, `target_tf`, `reason`).
2. `get_earliest_timestamp(symbol, timeframe)`: `SELECT MIN("time")` über `ohlcv_bars` in `market_data.duckdb`, Wanduhr-Epoch (Invariante 7, Muster `_epoch_of()` aus `feature_store_reader.py`). Defensiv `None` bei Fehler/leerer DB.
3. Cache-Versionierung: Schlüssel `(symbol, timeframe, partition)`; ein Eintrag trägt `source_max_timestamp`. Gültig nur, wenn `source_max_timestamp` ≤ aktuelles DB-Maximum (sonst stale).
4. Namespace-Schreibzugriff ausschließlich über den Provider (`read_namespace(context)` / `write_namespace(context, **changes)`) – keine UI-Direktzugriffe auf `shared_state`.
5. Wanduhr-Garantie: alle Zeiten als Wanduhr-Epochs, keine Berlin-Offset-Umrechnung (Invariante 7).

## ✅ Headless-Verifikation

- `test/test.py`: Namespace-Default-Struktur (alle Keys aus §5 vorhanden), `get_earliest_timestamp("SILVER", "M1")` ≈ 2013-06-05 (reale DB), Cache-Eintrag bildet `(symbol, timeframe, partition)` korrekt ab, stale-Erkennung bei veraltetem `source_max_timestamp`.

---

# 21.03.02 – Boundary Policy & Historien-Detection

## 🎯 Ziel

Präzise Ermittlung der M1-Verfügbarkeitsgrenze und Umsetzung der Boundary Policy (`coverage_status = "native" | "fallback"`, `source_tf`) gemäß §3.2 Ebene 1 und §4 Säule 1.3.

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_boundary.py` – Boundary-Evaluierung (reine Logik, kein UI-Import).
- **Geändert:** `test/test.py` (Test 3).

## 🛠️ Umsetzungsschritte

1. `resolve_boundary(symbol)` → `history_boundaries["m1_available_from"] = get_earliest_timestamp(symbol, "M1")` (aus 21.03.01).
2. `evaluate_coverage(symbol, from_ts)`:
   - `from_ts ≥ m1_available_from` → `coverage_status = "native"`, `source_tf = "M1"`.
   - `from_ts < m1_available_from` → `coverage_status = "fallback"`, `source_tf` = nächst-höherer TF mit Daten (z. B. H1).
   - **Regel:** Eine höhere Aggregationsstufe darf niemals als M1 deklariert werden ($H1 \to M1$ strikt verboten).
3. Anzeige-Datum: `m1_available_from` als `DD.MM.JJJJ` formatieren (Wanduhr, Invariante 7) – Grundlage für das UI-Element `ℹ️ M1 verfügbar ab DD.MM.JJJJ` (Umsetzung in 21.03.08).

## ✅ Headless-Verifikation

- Test 3: Daten vor der dynamischen M1-Grenze → `coverage_status = "fallback"` und `source_tf = "H1"`; Daten nach der Grenze → `"native"`.

---

# 21.03.03 – Hysterese-Kaskaden-Engine (Auto Cascade)

## 🎯 Ziel

Zoom-Kaskade mit Haupt-Stufen M1 → M5 → H1 → H4 → D1, Zoom-Bändern, Hysterese-Schwellwerten, Transition Guard und Telemetrie (§4 Säule 2).

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_cascade.py` – reine Logik, keinerlei UI-Import (Grundsatz 4/11).
- **Geändert:** `test/test.py` (Test 1 + 2).

## 🛠️ Umsetzungsschritte

1. Konstanten (Schwellwerte):
   - `ZOOM_OUT_THRESHOLD_M1 = 3.5` Tage (84.0 h) — M1/M5 → H1 (Zoom-Out)
   - `ZOOM_IN_THRESHOLD_M1 = 2.0` Tage (48.0 h) — H1 → M1/M5 (Zoom-In)
   - `ZOOM_OUT_THRESHOLD_H4 = 10.0` Tage — H1 → H4 (Grenze Band 2→3)
   - `ZOOM_OUT_THRESHOLD_H1 = 35.0` Tage — H4 → D1 (Zoom-Out)
   - `ZOOM_IN_THRESHOLD_H1 = 28.0` Tage — D1 → H4 (Zoom-In)
   - `CROSSFADE_DURATION_MS = 250`.
2. Zoom-Bänder (Auto): Band 1 (< 2.0 d, M1↔M5), Band 2 (2.0–10.0 d, M15↔H1), Band 3 (10.0–35.0 d, H4), Band 4 (> 35.0 d, D1).
3. `evaluate_cascade(viewport_from_ts, viewport_to_ts, current_tf, state)` → `candidate_tf`, `direction` (`zoom_in`/`zoom_out`), `range_days`.
4. Transition Guard: Umschalten erst, wenn $\text{now}() - transition\_started\_at \ge \frac{CROSSFADE\_DURATION\_MS}{1000.0}$; nach Umschaltung `last_transition_at` aktualisieren.
5. Telemetrie-Log je Kaskaden-Event: `(trigger, from_tf, to_tf, range_days)`.
6. Hysterese: Zwischen 2.0 d und 3.5 d ist der Zustand stabil (kein Wechsel) – verhindert Oszillation.

## ✅ Headless-Verifikation

- Test 1 (Hysterese-Boundary): 1.99 d → M1, 2.01 d → kein Wechsel, 3.49 d → kein Wechsel, 3.51 d → H1.
- Test 2 (Anti-Oszillation): 20× Oszillation im Fenster [1.9 d, 3.6 d] → `transition_started_at` garantiert fehlerfreies Schalten.

---

# 21.03.04 – Confluence-Gewichtung & Normalisierung

## 🎯 Ziel

Gewichtete Confluence-Scores mit vollständigem Gewichtungs-Schema, Min-Max-Normalisierung, Constant-Matrix-Policy und Volatilitäts-Adaption (§4 Säule 1.4).

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_confluence.py` – Score-Berechnung (reine Logik).
- **Geändert:** `test/test.py` (Test 5).

## 🛠️ Umsetzungsschritte

1. Gewichte: $W_{\text{D1}} = 3.0$, $W_{\text{H4}} = 2.5$, $W_{\text{H1}} = 2.0$, $W_{\text{M15/M30}} = 1.5$, $W_{\text{M5}} = 1.2$, $W_{\text{M1}} = 1.0$.
2. $Score_j = \sum (W_{TF} \cdot Signal_{TF})$ – un-normalisiert.
3. Min-Max-Skalierung auf $[0.0, 1.0]$; **Constant-Matrix-Policy:** $\text{max\_score} == \text{min\_score}$ → $\text{normalized\_score} = 0.5$ (keine Division durch Null).
4. Volatilitäts-Adaption (Toggle): $ratio = \text{clamp}(\frac{\text{ATR}_{\text{TF}}}{\text{ATR}_{\text{Current}}}, 0.2, 5.0)$; bei $\text{ATR}_{\text{Current}} \le 10^{-6}$ → $ratio = 1.0$ (deaktiviert).

## ✅ Headless-Verifikation

- Test 5: flache Matrix liefert 0.5; $W_{\text{D1}}=3.0$ behält vor der Min-Max-Skalierung die proportionale Übermacht.

---

# 21.03.05 – State-Machine & Prioritäts-Kette (Guards & Override)

## 🎯 Ziel

Umsetzung der Zustandstabelle (§3.1) und der Prioritäts-Kette (§3.2): Hard Data Availability Guard, Temporary User Override, Fixed Data-TF Guard, Auto Cascade, Visual Preference.

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_guards.py` – Prioritaäts-Kette (reine Logik).
- **Geändert:** `test/test.py` (Test 4).

## 🛠️ Umsetzungsschritte

1. `apply_priority_chain(data_tf, requested_chart_tf, cascade_state, override)` → effektiver Chart-TF.
2. **Ebene 1 – Hard Data Availability Guard:** aus 21.03.02 (`evaluate_coverage`); bei `fallback` wird der nächst-höhere TF erzwungen.
3. **Ebene 2 – Temporary User Override (Geister-Marker Klick):** Transaktions-Semantik:
   - `override.active = True`, `override.previous_data_tf` (z. B. `"M15"`), `override.target_tf` (z. B. `"D1"`), `override.reason = "ghost_marker_click"`.
   - Badge `[ 🌐 Data-TF temporär gelockert auf D1 | Reset ]`; **Reset** stellt exakt `previous_data_tf` wieder her.
4. **Ebene 3 – Fixed Data-TF Guard:** ohne Override ist das Chart-TF ≤ Data-TF (z. B. M15-Fix → max. M15); D1-Upgrade gesperrt.
5. **Ebene 4 – Auto Cascade:** aus 21.03.03 (`evaluate_cascade`).
6. **Ebene 5 – Visual Rendering Preference:** Farbschemata/Labels (UI, 21.03.09).
7. Inkongruenz-Warnung: Manuelles D1 bei M15-Fix → *"D1-Kerzen nicht möglich, da Data-TF auf M15 fixiert. Kerzen auf M15 gesetzt."*

## ✅ Headless-Verifikation

- Test 4: Fixiert `Data-TF = M15`, simulierter Klick auf D1-Geister-Marker → `previous_data_tf = "M15"`; nach `Reset` korrekte Wiederherstellung.

---

# 21.03.06 – Event-Partitionierung & Cache-Invalidierung (Late-Arriving Ticks)

## 🎯 Ziel

Partitionierte RAM-Cache-Invalidierung: $affected\_partition = partition(symbol, timeframe, t_{event})$ – nachträglich eingehende Ticks invalidieren nur ihre eigene Zeit-Partition, nie den gesamten Cache (§4 Säule 2.3).

## 📁 Dateien

- **Neu:** `analytics/engine/mtf_fc_partition.py` – Partitionierung + Invalidierung (reine Logik).
- **Geändert:** `test/test.py` (Test 6).

## 🛠️ Umsetzungsschritte

1. `partition(symbol, timeframe, ts)` → Partitions-Schlüssel (z. B. Wanduhr-Datum der Event-Zeit, Invariante 7).
2. `invalidate_partition(cache, symbol, timeframe, t_event)`: entfernt ausschließlich den Eintrag der eigenen Event-Zeit-Partition; alle übrigen Partitions-Einträge bleiben unangetastet.
3. Integration mit der Cache-Versionierung aus 21.03.01: nach Invalidierung wird `cache_generation` inkrementiert.

## ✅ Headless-Verifikation

- Test 6: historischer Tick ($t_{event}$ = vor 5 Tagen) → exakt die betroffene Zeit-Partition wird invalidiert, alle anderen bleiben bestehen.

---

# 21.03.07 – MtfFilterBarWidget & Control-Panel (UI)

## 🎯 Ziel

Filterleiste mit Source-Data-TF, Chart-Overlay-TF, Range-Picker, View-Templates (über `SchemaMigrator`), Tabellen-Sortierung und Session-Filter (§4 Säule 1). MVVM: **keine SQL-Queries in der UI** (Grundsatz 4).

## 📁 Dateien

- **Neu:** `chart/widgets/mtf_filter_bar.py` – `MtfFilterBarWidget` (QWidget, reines Event-Handling/Rendering).
- **Neu:** `analytics/engine/mtf_fc_templates.py` – View-Template-Persistenz via `SchemaMigrator` (Payload-Key `mtf_fc_schema_version = "1.0.0"`, in-memory, abwärtskompatibel).
- **Geändert:** `chart/chart_win.py` (Integration der Filterleiste), `analytics/ui/analytics_win.py` (Tabellen-Sortierung, falls betroffen).

## 🛠️ Umsetzungsschritte

1. Steuerungselemente:
   - **Source-Data-TF:** `🌐 Alle Timeframes` (Multi) vs. `🔒 Fixiert auf [TF]`.
   - **Chart-Overlay-TF:** `⚡ Auto (Kaskade)` vs. `🔒 Manuell Fix`.
   - **Range-Picker:** Presets (`24h`, `7d`, `30d`, `YTD`) & Benutzerdefiniert.
   - **Tabellen-Sortierung:** Dropdown `[ Datum 🢇 ]`, `[ Signal-Stärke 🢇 ]`, `[ TF 🡅 ]`.
2. View-Templates: Speichern/Laden kompletter Filter-Konfigurationen über den bestehenden `SchemaMigrator` (migriert fehlende/veraltete TFs und Session-Keys in-memory; Rollback-Schutz bleibt).
3. Session-Filter & DST-Normalisierung: London/NY/Tokio als Farbbalken (nur M1/M5-Zoom); Session-Grenzen strikt als **UTC-Epochs** berechnet, Formatierung erst beim Rendern (Invariante 7).
4. EventBus-Anbindung (`favorites_changed`, `profile_changed`, `service_set_changed`) statt direkter Orchestrator-Referenzen (Grundsatz 5).
5. Zustand: UI liest/schreibt `shared_state["mtf_fc"]` ausschließlich über den Provider (21.03.01).

## ✅ Headless-Verifikation

- `py_compile` aller neuen/geänderten Dateien; Code-Inspektion (kein SQL, keine DB-Connects in der UI, EventBus-Entkopplung).

---

# 21.03.08 – Chart-Integration: Kaskade, Puls-Breadcrumb & Historien-Anzeige

## 🎯 Ziel

Anbindung der Kaskaden-Engine an die PyLWC-Zoom-Interaktion, Puls-Breadcrumb und transparente Historien-Anzeige mit Boundary Policy (§4 Säule 2.1/2.2 + Säule 1.3).

## 📁 Dateien

- **Neu:** `chart/js/07_mtf_fc.js` – Zoom-Hook auf `visibleRangeChanged`, Kaskaden-Trigger, Puls-Breadcrumb, Boundary-UI.
- **Geändert:** `chart/js/04_live_updates.js` (optionaler Hook-Aufruf, Muster `06_two_tier.js`), `chart/chart_win.py` (Kaskaden-Umschaltung + `tf_combo`-Sync), `chart/chart_basics.py` (`JS_FILES`-Liste erweitern).

## 🛠️ Umsetzungsschritte

1. JS-Hook: bei `visibleRangeChanged` wird `range_days` an Python übergeben (`pyBridge.onViewportChanged`); Python ruft `evaluate_cascade()` (21.03.03) auf und liefert `{current_tf, candidate_tf}` zurück.
2. `chart_win.py`: bei Kaskaden-Wechsel `current_tf` umschalten und `tf_combo` synchronisieren (Konsistenz mit bestehender TF-Auswahl, `on_tf_changed`); Transition Guard über `transition_started_at` (CROSSFADE 250 ms).
3. Puls-Breadcrumb: transparenter Badge `[ ⚡ Kerzen: M5 ]` oben rechts im Canvas; leuchtet bei Umschaltung kurz hellblau auf.
4. Boundary-UI: Anzeigeelement `ℹ️ M1 verfügbar ab DD.MM.JJJJ` (aus 21.03.02); bei `coverage_status = "fallback"` H1-Kerzen mit Schraffur *"Keine M1-Rohdaten für diesen Zeitraum"* (keine Lücke, kein Absturz).
5. Telemetrie: jedes Kaskaden-Event loggt `(trigger, from_tf, to_tf, range_days)`.

## ✅ Headless-Verifikation

- `node --check` auf neuen/geänderten JS-Dateien; `py_compile` auf Python-Dateien; Code-Inspektion (keine UI-Ausführung).

---

# 21.03.09 – Interaktives Layering: TF-Badges & Geister-Marker

## 🎯 Ziel

Interaktive TF-Badges (Klick = Filter, Strg+Klick = Multi-Select) und Geister-Marker mit Guard-Override und Viewport-Animation (§4 Säule 3).

## 📁 Dateien

- **Neu:** `chart/js/08_mtf_layers.js` – Badges, Geister-Marker, sanfte Viewport-Animation.
- **Geändert:** `chart/chart_win.py` (Guard-Override-Trigger über 21.03.05), `chart/js/03_chart_rendering.js` (Ghost-Pfeil am Viewport-Rand), `chart/chart_basics.py` (`JS_FILES`).

## 🛠️ Umsetzungsschritte

1. Interaktive TF-Badges (z. B. `[ H4-Swing ]`): Klick filtert die aktuelle Ansicht synchron auf diesen Timeframe; Strg+Klick = Multi-Select.
2. Geister-Marker (Off-Screen Level): übergeordnete Level außerhalb des Zoom-Blicks als verblasster Pfeil am Viewport-Rand: `▲ D1-Widerstand (27.85)`.
3. Klick auf einen Geister-Marker → Ebene-2-Guard-Override (21.03.05) auslösen und den Viewport sanft zum Ziel-Level animieren.
4. Reset-Badge `[ 🌐 Data-TF gelockert ]`: Klick auf *Reset* stellt `previous_data_tf` exakt wieder her und deaktiviert den Override.

## ✅ Headless-Verifikation

- `node --check` auf neuen/geänderten JS-Dateien; `py_compile` auf Python-Dateien; Code-Inspektion (kein SQL in UI, Entkopplung über EventBus).

---

# 21.03.10 – Abschluss: Integrationstest & Cleanup

## 🎯 Ziel

Service-Failure-Degradation-Integrationstest (§7 Test 7) sowie Gesamtlauf aller Tests und Cleanup von `test/` (Grundsatz 10).

## 📁 Dateien

- **Geändert:** `test/test.py` (Test 7).

## 🛠️ Umsetzungsschritte

1. Test 7 (Service-Failure-Degradation): drei aufeinanderfolgende Fehler von Service A → RAM-Quarantäne; Service B läuft weiter; Service C meldet `dependency_failed`; der alte `shared_state` bleibt erhalten; `reset()` hebt die Quarantäne auf. Basis: bestehendes `execute_set_resilient()` in `set_evaluator.py` – kein Umbau der Engine nötig.
2. Alle 7 Tests aus §7 in `test/test.py` ausführen (headless, kein `QApplication.exec()`, Grundsatz 2).
3. Cleanup: temporäre Test-Skripte und `*.duckdb`-Dateien aus `test/` entfernen – es verbleibt nur der Harness `test/test.py` (Grundsatz 10).
4. Implementierungs-Log: Einträge je 21.03.xx in `docs/AKTUELLE_UMSETZUNG.md` nach Bestätigung des Anwenders (Taxonomie 21.03, Format MD).

## ✅ Headless-Verifikation

- Gesamtlauf `test/test.py` (alle Checks PASS); `test/`-Inhalt = nur `test.py`.
