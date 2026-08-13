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

---

# 21.03.11 – Buglist-Auswertung & Fix-Plan (12.08.2026, Stand: Analyse)

> Vom Anwender gemeldete Buglist (6 Punkte). Analyse-Ergebnisse gegen den Code,
> **noch keine Umsetzung** (nur Doku, kein Coding). Verifikation teilweise headless
> (Strukturcheck der Filterleiste), UI-Nachprüfung durch den Anwender.

## 📋 Bug 1 – Heatmap-Legende: korrekte Operator-Beschriftung

**Meldung:** Legende muss korrekt mit `=`, `>`, `<`, `>=` oder `<=` beschriftet sein.
**Klarstellung:** Die **Heatmap-Legende** (`analytics/ui/heatmap_widget.py`, `_update_legend`).

**Befund (Code):** Die diskrete Confluence-Legende beschriftet die Farbfelder aktuell
nur mit Zahlen (`0`, `1`, …, `4`, `5+`); die kontinuierliche Viridis-Legende mit
Rohwerten. Keine Operator-Semantik.

**Fix-Plan:** Confluence-Modus je ganzzahligem Treffer-Wert `c` → Label `= 0`, `= 1`,
…, `= 4`; letztes Feld `≥ 5`. Viridis-Modus: Intervall-Labels (z. B. `≤ min+0.25span`,
`min+0.25span … min+0.5span`, …, `≥ min+0.75span`) – Formatierung über
`_format_heatmap_value`. Keine Logik-Änderung, nur Labels.

## 📋 Bug 2 – H1 + Zoom-In: kein Wechsel in kleinere Timeframes

**Meldung:** Bei H1-Auswahl wird beim Zoom-In nicht in kleinere TFs gebohrt, obwohl sie vorhanden sind.

**Befund (Code):** `analytics/engine/mtf_fc_cascade.py` (Band 2): `range_days < 2.0 d`
→ Kandidat `M5` (Zoom-In), darunter M1. Die Hysterese hält zwischen 2.0 d und 3.5 d
stabil. Zusätzlich greift der Transition Guard (`CROSSFADE_DURATION_MS = 250`), nach
einer Schaltung ist 250 ms lang keine weitere erlaubt. Logik headless verifiziert
(Tests 1+2 PASS).

**Fix-Plan (verifizieren im UI-Test):** Prüfen, ob der Wechsel unterhalb 2.0 d im
laufenden Chart wirklich ausbleibt. Mögliche Ursachen: `tf_combo`-Sync/Refresh-Race
nach `_mtf_fc_switch_tf`, Debounce (150 ms JS) oder Guard-Fenster. Falls reproduzierbar:
Flow nachziehen (kein Kaskaden-Logik-Fix nötig, da Engine headless grün).

## 📋 Bug 3 – „Alle TF ausführen" aktualisiert das Analytics-Hauptfenster nicht

**Meldung:** Wenn im Service „alle TF ausgeführt" wird, wird das Focus Widget nicht aktualisiert.
**Klarstellung:** **Analytics-Hauptfenster** (`analytics/ui/analytics_win.py`, Heatmap/Tabelle).

**Befund (Code):** `ServiceRunWorker` emittiert `event_bus.service_set_changed` genau
**einmal** nach Abschluss des Runs (`serviceui/run_worker.py`, `_emit_service_changed`).
Das `AnalyticsWindow` verbindet sich jedoch **nicht** auf `service_set_changed` (nur auf
`profile_changed`, `favorites_changed`). Das `ServiceSelectorModel` refreshed sich, die
Analytics-Queries aber nicht.

**Fix-Plan:** `AnalyticsWindow.__init__`: `event_bus.service_set_changed.connect(...)` →
debounced `self._vm.refresh_all()` (Bestehender VM-Pfad, kein neues SQL). Damit wird die
Heatmap/Tabelle nach jedem abgeschlossenen Service-Run automatisch neu geladen.

## 📋 Bug 4 – TF M15: X-Achse zeigt weiterhin 12h-Blöcke

**Meldung:** Bei M15 (statt H1) ist je Block auf der Achse immer noch 12-Stunden-x-teiler; sollte angepasst werden.

**Befund (Code):** `chart/js/04_live_updates.js` (`tickMarkFormatter`) ist **TF-unabhängig**
– er formatiert nur (`TT.MM.JJ` vs. `HH:MM`). Die Tick-Dichte bestimmt LWC v5 aus der
Viewport-Breite, nicht aus dem gewählten TF. Es gibt keine TF-spezifische Achsen-Granularität.

**Fix-Plan:** TF-abhängige Achsen-Skalierung: je `currentTfInSeconds` Ziel-Abstand der
Ticks (z. B. M15 → 15-min-Marken, H1 → 1h-Marken) im `tickMarkFormatter` bzw. via
`timeScale().applyOptions()`; Format bleibt Wanduhr (Invariante 7). Reine JS-Erweiterung
in `04_live_updates.js` (Additiv, kein Kern-Umbau).

## 📋 Bug 5 – Heatmap-Zoom-Slider X/Y korrelieren nicht mit Maus-Zoom

**Meldung:** Die Zoom-Slider an der Heatmap (einer für X, einer für Y) sollten mit dem Maus-Zoom korrelieren und verbunden sein.

**Befund (Code):** `analytics/ui/heatmap_widget.py` hat X/Y-Slider
(`_slider_zoom_x`/`_slider_zoom_y`, 5..100). Die Verdrahtung ist **einseitig**:
Slider-Änderung → `_on_zoom_x/y_changed` → `_set_zoom_range` → `_apply_x/y_range`
(`setXRange`/`setYRange`). Es gibt **keinen** `sigRangeChanged`-Hook der Plot-ViewBox
→ Maus-Zoom (Mausrad) bewegt die Slider nicht.

**Fix-Plan:** Zwei-Wege-Sync: `self._plot_hm.plotItem.vb.sigRangeChanged` → Slider via
`_set_zoom_slider` aktualisieren (blockSignals + `_syncing`-Guard gegen Endlos-Schleife).
Richtungskonvention (rechts = Zoom-In, links = Zoom-Out) beibehalten. ViewModel-Params
`zoom_x_range`/`zoom_y_range` bleiben die Quelle.

## 📋 Bug 6 – Filterleiste (Data-TF, Chart-TF, Range-Picker) nicht sichtbar

**Meldung:** Source-Data-TF, Chart-Overlay-TF und Range-Picker sind definitiv NICHT
sichtbar; weitere Elemente vermutlich ebenfalls nicht nutzbar. Der Range-Picker ist wichtig
(nicht immer alle Jahre sehen).

**Befund (Code + headless Strukturcheck):** Die `MtfFilterBarWidget` wird in
`chart/chart_win.py` (Zeile ~486-490) an `verticalLayout_toolbar` angehängt – Strukturcheck
offscreen bestätigt: Layout gefunden, 2→3 Items, Einfügen OK. **Ursache der Nicht-Sichtbarkeit:**
`sizeHint` der Leiste = **w 2248 px** (bei 1200 px Fensterbreite) → die Zeile läuft über,
wird abgeschnitten/geclippt, die Controls sind nicht erreichbar.

Zusätzlich fehlen in `chart_win.py` die Signal-Verdrahtungen:
- `sort_mode_changed` → **nicht verbunden**
- `sessions_changed` → **nicht verbunden**
- `template_applied` → **nicht verbunden**
(nur `data_tf_changed`, `chart_tf_changed`, `range_changed`, `guard_override_requested`).

**Fix-Plan:**
1. `MtfFilterBarWidget` kompakt umbauen (kleinere Controls, kürzere Labels, ggf.
   zwei Zeilen/Flow) – Ziel: `sizeHint`-Breite ≤ ~1100 px, sichtbar bei 1200 px Fenster.
2. Fehlende Signal-Verdrahtung in `chart_win.py` nachrüsten (Sortierung an den
   Analytics-/Tabellen-Kontext, Sessions an den Chart, Template-Anwendung).
3. Range-Picker wirkt bereits (`_on_mtf_fc_range_changed` → `_mtfFcApplyRange`) –
   nach Sichtbarkeits-Fix benutzbar.

---

# Implementierungs-Log 21.03 (MTF-FC v4) – 12.08.2026

> Taxonomie 21.03, Format MD. Einträge je umgesetztem Schritt nach Anwender-Bestätigung. Headless-Validierung ohne UI-Ausführung (Grundsatz 2).

## 21.03.01 – Data Provider & `shared_state`-Namespace (12.08.2026 17:11)

- **Umgesetzt:** `analytics/engine/mtf_fc_state.py` (Namespace-Factory `default_mtf_fc_state()`, `ensure_mtf_fc_namespace()` – alle Keys aus §5), `analytics/engine/mtf_fc_provider.py` (`MtfFcProvider` mit `get_earliest_timestamp`/`get_latest_timestamp` via MIN/MAX `"time"`, Cache-Key `(symbol, timeframe, partition)`, `is_cache_valid`, `read_namespace`/`write_namespace`, `clear_partition`).
- **Verifikation:** Namespace-Default-Struktur (alle §5-Keys), `get_earliest_timestamp("SILVER", "M1")` ≈ 2013-06-05 (reale DB, Wanduhr), Cache-Stale-Erkennung bei veraltetem `source_max_timestamp` – Test 1-Teilblock in `test/test.py` PASS.
- **Commit:** `4217e71`

## 21.03.02 – Boundary Policy & Historien-Detection (12.08.2026 17:11)

- **Umgesetzt:** `analytics/engine/mtf_fc_boundary.py` (`MtfFcBoundary` mit `resolve_boundary`, `evaluate_coverage` native/fallback, `format_available_date` als `DD.MM.JJJJ`, Wanduhr-Formatierung ohne Berlin-Offset, Fallback-Kandidaten M5/M15/H1/H4/D1). Regel: höhere Aggregationsstufe wird nie als M1 deklariert.
- **Verifikation:** Test 3 (Daten vor M1-Grenze → `fallback`/`source_tf = "H1"`, nach Grenze → `"native"`) PASS.
- **Commit:** `4217e71`

## 21.03.03 – Hysterese-Kaskaden-Engine (12.08.2026 17:11)

- **Umgesetzt:** `analytics/engine/mtf_fc_cascade.py` – Schwellwerte (M1/M5→H1 bei 3.5 d, H1→M5 bei <2.0 d, H1→H4 bei >10 d, H4→D1 bei >35 d, D1→H4 bei <28 d), `CROSSFADE_DURATION_MS = 250`, `evaluate_cascade`, `transition_guard_ok`, `apply_transition`, Telemetrie `(trigger, from_tf, to_tf, range_days)`.
- **Verifikation:** Test 1 (Hysterese-Boundary 1.99/2.01/3.49/3.51 d) + Test 2 (20-fach Anti-Oszillation im Fenster [1.9 d, 3.6 d]) PASS.
- **Commit:** `4217e71`

## 21.03.04 – Confluence-Gewichtung & Normalisierung (12.08.2026 17:11)

- **Umgesetzt:** `analytics/engine/mtf_fc_confluence.py` – Gewichte (D1=3.0, H4=2.5, H1=2.0, M15/M30=1.5, M5=1.2, M1=1.0), `min_max_normalize` mit Constant-Matrix-Policy (flache Matrix → 0.5, keine Division durch Null), `volatility_ratio` mit Clamp 0.2–5.0 und Deaktivierung bei ATR ≤ 1e-6.
- **Verifikation:** Test 5 (flache Matrix → 0.5; W-D1-Übermacht vor Min-Max) PASS.
- **Commit:** `4217e71`

## 21.03.05 – State-Machine & Prioritäts-Kette (Guards & Override) (12.08.2026 17:11)

- **Umgesetzt:** `analytics/engine/mtf_fc_guards.py` – `apply_priority_chain` (Ebene 1 Hard Data Availability Guard → Ebene 2 Temporary User Override → Ebene 3 Fixed Data-TF Guard → Ebene 4 Auto Cascade → Ebene 5 Visual Preference), `start_override`/`reset_override` mit Transaktions-Semantik (`previous_data_tf`, `target_tf`, `reason`), `override_badge_text`, Inkongruenz-Warnung `WARNING_INCONGRUENT`.
- **Verifikation:** Test 4 (M15-Fix + D1-Geister-Marker-Klick → `previous_data_tf = "M15"`, Reset stellt exakt wieder her) PASS.
- **Commit:** `4217e71`

## 21.03.06 – Event-Partitionierung & Cache-Invalidierung (12.08.2026 17:11)

- **Umgesetzt:** `analytics/engine/mtf_fc_partition.py` – `partition`, `invalidate_partition` (+ `cache_generation`-Inkrement), `invalidate_partition_via_provider`; Integration mit Provider-Cache-Versionierung (21.03.01).
- **Verifikation:** Test 6 (historischer Tick t = vor 5 Tagen → exakt die betroffene Zeit-Partition wird invalidiert, alle übrigen bleiben) PASS.
- **Commit:** `4217e71`

## 21.03.07 – MtfFilterBarWidget & Control-Panel (UI) (12.08.2026 17:16)

- **Umgesetzt:** `chart/widgets/mtf_filter_bar.py` (`MtfFilterBarWidget`, MVVM – keine SQL/DB in UI): Source-Data-TF (`multi`/Fixiert), Chart-Overlay-TF (Auto/Manuell), Range-Picker (24h/7d/30d/YTD/benutzerdefiniert), Sortierung, Sessions (London/NY/Tokio), Presets; Signale für Data-TF/Range/TF-Wechsel. `analytics/engine/mtf_fc_templates.py` (`create_template`, `migrate_template` mit SchemaMigrator-Semantik, Payload-Key `mtf_fc_schema_version = "1.0.0"`, `MtfFcTemplateStore` in-memory).
- **Verifikation:** `py_compile` aller Dateien; Code-Inspektion (kein SQL in UI, EventBus-Entkopplung); Template-Migration headless (T7v1/v2) PASS.
- **Commit:** `4425bc9`

## 21.03.08 – Chart-Integration: Kaskade, Puls-Breadcrumb & Historien-Anzeige (12.08.2026 17:16)

- **Umgesetzt:** `chart/js/07_mtf_fc.js` (Zoom-Hook `pyBridge.onViewportChanged`, `_mtfFcApplyRange`, Puls-Breadcrumb, Boundary-UI), `chart/js/04_live_updates.js` (optionale Hooks `_onMtfFcFullUpdate`/`_onMtfFcVisibleRangeChanged`), `chart/chart_basics.py` (`JS_FILES` erweitert), `chart/chart_win.py` (`ChartBridge.viewportChanged`, MTF-FC-Init, `_on_mtf_fc_viewport_changed`, `_on_mtf_fc_range_changed`, `_mtf_fc_switch_tf`, `mtfFcState` im Update-Payload).
- **Verifikation:** `node --check` auf allen JS-Dateien; `py_compile`; Code-Inspektion.
- **Commit:** `4425bc9`

## 21.03.09 – Interaktives Layering: TF-Badges & Geister-Marker (12.08.2026 17:16)

- **Umgesetzt:** `chart/js/08_mtf_layers.js` (TF-Badges `onBadgeClick`, Geister-Marker `onGhostMarkerClick`, Reset-Badge, `animateToGhostLevel`), `chart/chart_win.py` (`badgeClicked`, `ghostMarkerClicked`, `guardOverrideReset`, `_push_mtf_fc_override_ui`, Handler `_on_mtf_fc_badge_clicked`, `_on_mtf_fc_ghost_marker_clicked`, `_on_mtf_fc_guard_reset`).
- **Verifikation:** `node --check`; `py_compile`; Code-Inspektion (Guard-Override-Trigger über 21.03.05, Reset stellt `previous_data_tf` wieder her).
- **Commit:** `4425bc9`

## 21.03.10 – Abschluss: Integrationstest & Cleanup (12.08.2026 17:20)

- **Umgesetzt:** Test 7 (Service-Failure-Degradation) standalone verifiziert und als Tests 1–7 (inkl. T7v1/v2 Template-Migration) in `test/test.py` integriert; Gesamtlauf ausgeführt; Cleanup temporärer Skripte (`check_mtf_fc.py`, `check_mtf_fc_test7.py`, `check_mtf_fc_ui.py`, `test_output_stderr.txt`) – verbleibt nur der Harness `test/test.py` (Grundsatz 10).
- **Verifikation:** `py_compile test/test.py` EXIT 0; Gesamtlauf: **alle 21.03 MTF-FC-Checks PASS** (T1a–T7.7, T7v1/v2). 26 vorbestehende FAILs (Fenster-/Reflow-, JSON-Feld-Auflösung, `instance_hash`-Binder in den 20.03-Analytics-Tests) sind Bestandszustand und nicht durch MTF-FC verursacht – der 21.03-Block ist vollständig grün. Keine neuen Quell-Commits nötig (Code bereits in `4217e71`/`4425bc9`, `test/` gitignored).
- **Commit:** – (nur Doku)

## 21.03.11 – Buglist-Auswertung & Fix-Plan (12.08.2026, Analyse)

- **Umgesetzt:** **Nur Doku/Analyse (kein Coding).** Die vom Anwender gemeldete Buglist (6 Punkte) wurde gegen den Code ausgewertet; Fix-Pläne in `docs/AKTUELLE_UMSETZUNG.md` (Kapitel 21.03.11) dokumentiert. Zusätzlich eine beschädigte Zeile in der Doku (Zeile 107, „Steuerungselemente:6) definiti") bereinigt.
- **Befunde (Kurzfassung):**
  - **Bug 1:** Heatmap-Legende (`_update_legend`) ohne Operator-Labels (`0..5+`) → Fix: `= 0..= 4`, `≥ 5`; Viridis-Intervall-Labels.
  - **Bug 2:** Kaskaden-Logik headless grün (Zoom-In < 2.0 d → M5); UI-Nachprüfung nötig (Flow-Race vermutet).
  - **Bug 3:** `AnalyticsWindow` verbindet sich NICHT auf `event_bus.service_set_changed` (vom Worker einmalig nach Run emittiert) → Fix: EventBus-Anbindung + debounced `refresh_all()`.
  - **Bug 4:** `tickMarkFormatter` TF-unabhängig → Fix: TF-spezifische Achsen-Ticks in `04_live_updates.js`.
  - **Bug 5:** Heatmap-Zoom-Slider einseitig (Slider→Range); kein `sigRangeChanged`-Hook → Fix: Zwei-Wege-Sync mit `_syncing`-Guard.
  - **Bug 6:** Filterleiste wird eingefügt, aber `sizeHint` w=2248 px (verifiziert, offscreen Strukturcheck) → Überlauf/Clipping; 3 Signale unverdrahtet → Fix: kompakter Umbau + Verdrahtung.
- **Verifikation:** `test/check_filterbar_layout.py` (temporär, offscreen, danach gelöscht): `verticalLayout_toolbar` gefunden, Items 2→3, `MtfFilterBarWidget` sizeHint w=2248 px – Ursache für Bug 6 bestätigt. Keine Code-Änderungen.
- **Commit:** – (nur Doku)

## 21.03.11 - Bug-Fix-Umsetzung (12.08.2026, nach Anwender-Bestätigung)

> Die vom Anwender gemeldete Buglist (6 Punkte) wurde umgesetzt. Nach der
> reinen Analyse (`eb78ee4`) wurden alle Fixes implementiert und headless
> verifiziert (Grundsatz 2, keine UI-Ausführung).

### Bug 4 - TF-spezifische X-Achsen-Ticks (M15/H1) - FERTIG

- **Neu:** `chart/js/09_mtf_axis.js` - Overlay-Layer `#mtf-axis-layer` rendert TF-alignierte
  Tick-Labels (M15 → 15/30-min-Marken, H1 → 1h-Marken), `MTF_AXIS_STEPS`,
  `MTF_AXIS_MIN_LABEL_PX = 90`, nur Intraday (TF < 86400 s), Tagesgrenzen (00:00) an LWC;
  API `mtfAxisSetTf`/`mtfAxisClear`; Hooks `_onMtfAxisFullUpdate`/`_onMtfAxisVisibleRangeChanged`;
  `window._mtfAxisActive`-Flag.
- **Geändert:** `chart/js/04_live_updates.js` (`tickMarkFormatter` gibt bei aktivem Overlay
  Intraday-Labels ab, 2 optionale Hooks), `chart/chart_basics.py` (`JS_FILES` um `09_mtf_axis.js`).
- **Verifikation:** `test/check_mtf_axis.js` (permanent, 14/14 PASS); `node --check` alle 9 JS;
  HTML-Template-Checks PASS. Wichtig: `window.TF_SECONDS_MAP` ist `const` (kein window-Property).

### Bug 2 - H1 + Zoom-In: kein Wechsel in kleinere TFs - FERTIG

- **Geändert:** `chart/chart_win.py` - Viewport-Transfer-Bug behoben: Bei pending
  MTF-FC-Epochs wird `_resolve_epoch_logical_range` statt alter Bar-Offsets verwendet
  (Binärsuche auf `_time_cont_to_real`, geklemmt). `chart_tf_mode == "fix"` unterbindet
  die Auto-Kaskade (`_on_mtf_fc_viewport_changed`-Guard). Neuer State
  `_mtf_fc_pending_epochs`, gesetzt durch `_mtf_fc_switch_tf` aus `_mtf_fc_last_viewport`.
- **Verifikation:** `py_compile`; Engine-H1-Zoom-In-Checks PASS; JS-Trigger-Checks PASS;
  Epoch-Range-Checks 8/8 PASS.

### Bug 3 - "Alle TF ausführen" aktualisiert Analytics-Fenster nicht - FERTIG

- **Geändert:** `analytics/ui/analytics_win.py` -
  `event_bus.service_set_changed.connect(self._on_service_set_changed)` + debounced `refresh_all()`.
- **Verifikation:** `py_compile`; Code-Inspektion (EventBus-Entkopplung, Grundsatz 2/5).

### Bug 1 + Bug 5 - Heatmap-Legende & Zoom-Slider-Sync - FERTIG

- **Geändert:** `analytics/ui/heatmap_widget.py` - `sigXRangeChanged`/`sigYRangeChanged`
  → `_sync_slider_from_range()` mit `_syncing`-Guard (Bug 5, Zwei-Wege-Sync);
  Confluence-Legende mit `=`/`>=`-Operatoren (Bug 1).
- **Verifikation:** `py_compile`; Code-Inspektion.

### Bug 6 - Filterleiste nicht sichtbar / Sortierung wirkungslos - FERTIG

- **Befund:** (1) 1-Zeilen-Layout zu breit (sizeHint 1281 px) → Fenster wurde auf ~1220 px
  aufgezwungen, Range (x 837+) und Sortierung (x 1173+, Ende > Fenster) rechts abgeschnitten;
  (2) `sort_mode_changed` speicherte nur im Namespace - die Analytics-Tabelle hatte keinerlei
  Verbindung (Konzept-Lücke).
- **Geändert:** `chart/widgets/mtf_filter_bar.py` - ZWEI-ZEILEN-Layout (row1: Data-TF/
  Chart-TF/Range/Sort, row2: Sessions/Templates) → sizeHint 699 px, alle Controls sichtbar
  bei `resize(1000,700)`. `config/event_bus.py` - neues Signal `mtf_fc_sort_changed(str)`.
  `chart/chart_win.py` - `_on_mtf_fc_sort_mode_changed` emittiert zusätzlich auf dem
  EventBus (Entkopplung, kein Fenster-Know-how). `analytics/ui/analytics_win.py` - Slot
  `_on_mtf_fc_sort_changed` → `table_page.set_external_sort_mode()`. `analytics/ui/table_page.py` -
  `set_external_sort_mode()`/`_apply_external_sort()`/`_find_dynamic_header()`,
  `_SortableValueItem` (numerische JSON-Union-Sortierung: 10.2 > 9.5 korrekt statt lexikografisch),
  Anwendung nach jedem Befüllen (Vorrang vor Profil-Sortierung, kein User-Setting/Dirty-Flag).
- **Sortier-Semantik:** `Datum 🠇` → Zeit absteigend (UserRole-Epoch);
  `Signal 🠇` → Header-Substring (signal/stärke/score/conf/wert) numerisch
  absteigend; `TF 🠅` → timeframe aufsteigend; Fallback (keine Spalte) → Zeit.
- **Verifikation:** `test/check_mtf_sort_binding.py` (permanent, 21/21 PASS: EventBus, alle 3
  Modi, Numerik, Fallback, Refresh-Persistenz, kein User-Setting, Row-Mapping intakt);
  `test/check_filterbar_visible.py` (permanent): sizeHint 699 px, Range/Sort sichtbar innerhalb
  990 px fb bei 1000 px Fenster; `py_compile` aller geänderten Dateien PASS.
  DPI-Artefakt geklärt: `devicePixelRatio` = 1.0, aber `mapTo`-global-x ≈ 2× intern
  (offscreen-Render-Artefakt) - logische Koordinaten maßgeblich.

- **Commit:** `5194107`

---

# 21.03.12 - Architektur-Korrektur: MTF-FC-Ziel = Analytics (nicht Chart) (12.08.2026, Stand: Analyse & Entscheidung)

> **Anwender-Feststellung (12.08.2026):** Kapitel 21.03 (MTF-FC) ist **ausschliesslich** fuer das
> `AnalyticsWindow` (`analytics_win.py`) gedacht und macht zusaetzlich im `ServiceWindow`
> (`service_win.py`) Sinn - **niemals im Chart-Fenster**, das bereits vollstaendig und perfekt
> implementiert ist. Die bisherige Umsetzung (Commits `4425bc9`, `5194107`) hat das Widget
> fehlerhaft in `chart/chart_win.py` verbaut.
>
> **Stand:** Nur Doku/Analyse (kein Coding). Wartet auf den expliziten Startschuss des Anwenders.

## ?? 1. Befund (Code-verifiziert)

1. **21.03 ist umgesetzt, aber im falschen Fenster:** Das `MtfFilterBarWidget`, die Engine-Module
   (`mtf_fc_*`) und die JS-Layer (`07_mtf_fc.js`, `08_mtf_layers.js`, `09_mtf_axis.js`) wurden in
   das Chart-Fenster integriert statt in das Analytics-Fenster.
2. **Fehlende Imports in `chart/chart_win.py`:** Die MTF-FC-Klassen werden ohne Import referenziert
   (`MtfFcProvider`, `MtfFcBoundary`, `default_mtf_fc_state`, `MtfFilterBarWidget`,
   `evaluate_cascade`, `apply_transition`) - `NameError` beim Oeffnen eines Chart-Fensters
   (Z. 337/338/340/495/1800/1812). `import chart.chart_win` bestaetigt: alle Namen fehlen im Modul.
3. **Revert-Ziel verifiziert:** `chart/chart_win.py` ist zwischen `4217e71` (Stand vor 21.03) und
   HEAD **+416/-2** - ausschliesslich 21.03-Adds + Bug-2-Refactor (Cascade-Viewport). Ein Revert
   auf `4217e71` ist verlustfrei (kein Nicht-21.03-Verlust).
4. **JS-Hooks additiv:** `chart/js/04_live_updates.js` enthaelt nur optionale, guarded Hooks
   (`try { if (window._onMtfFc... ) }`) - ausschliesslich 21.03, sauber zuruecknehmbar.
5. **Widget ist chart-frei:** `chart/widgets/mtf_filter_bar.py` importiert nur `analytics.engine.*` -
   architektonisch problemlos nach `analytics_win` verschiebbar. Die Ablage unter `chart/widgets/`
   war der einzige Fehlgriff.

## ?? 2. Entscheidung 6(a) - Semantik-Vertrag fuer Analytics (fixiert)

> Zu klären war: Woher nimmt `chart_tf` im Analytics-Kontext den konkreten Timeframe, wenn
> `chart_tf_changed` nur `'auto' | 'fix'` emittiert? **Entscheidung des Anwenders: 6(a).**

- **`data_tf` (Analysequelle / Filter):** Steuert `WHERE timeframe IN (...)`. `Multi` =
  `all_timeframes=True` (21.01 E1, bereits implementiert in Reader/Worker), `Fixiert auf [M15]` =
  `timeframe='M15'`.
- **`chart_tf` (Anzeige-/Aggregations-Ebene):** `Auto` = Granularitaet dynamisch an den Range
  anpassen (neue Reader-Logik, Zeit-Bucketing); `Fix` = **eigenes zweites TF-Dropdown**
  (Aggregations-TF, unabhaengig von `data_tf`). Das bestehende `chart_tf`-Combo liefert nur
  `'auto'|'fix'` - der konkrete TF kommt aus dem **neuen separaten Aggregations-TF-Dropdown**.
- **Range:** Presets (`24h`/`7d`/`30d`/`YTD`) relativ zum **letzten Datenpunkt** (`MAX(bar_time)`
  der feature_store-Daten) statt `time.time()` (im Chart ok, im Analytics koennten die letzten
  Signale Tage alt sein -> leere Ergebnisse).
- **Sort:** bestehende EventBus-Kette (`event_bus.mtf_fc_sort_changed` ->
  `table_page.set_external_sort_mode`) - kein neuer Code.
- **Nicht verdrahten im Analytics:** Guard-Override/Geister-Marker/Session-Farbbalken
  (chart-spezifisch, 21.03.09). Sessions: Prio 2 (kein Session-Konzept im `feature_store_reader`).
- **Templates:** Persistenz via `AnalyticsProfileRepository` (neue Sektion, z. B. `filters`);
  `MtfFcTemplateStore` ist aktuell nur in-memory.
- **TF-Liste:** `DATA_TF_OPTIONS` (6 Eintraege: Multi/M1/M5/M15/H1/H4) vs. Analytics-`TIMEFRAMES`
  (11: M1..MN1) - fuer Analytics konfigurierbar erweitern.

## ?? 3. Umsetzungsplan (abgeschlossen)

1. **[x] Chart-Revert (1 Vorgang):** (umgesetzt, Commit `85a0c7c`)
   ```
   git checkout 4217e71 -- chart/chart_win.py chart/chart_basics.py chart/js/04_live_updates.js
   git rm chart/js/07_mtf_fc.js chart/js/08_mtf_layers.js chart/js/09_mtf_axis.js
   ```
   Nicht anfassen: `mtf_filter_bar.py`, `mtf_fc_*`, `event_bus.py`, `analytics_win.py`,
   `table_page.py`, `heatmap_widget.py`.
2. **[x] Analytics-Integration:** (umgesetzt, Commit `eae1d7b`) `MtfFilterBarWidget` in `analytics_win._build_ui()` (Filter-Zeile),
   Signal-Verdrahtung (data_tf/chart_tf/range/template -> VM), `AnalyticsViewModel`-Parameter
   (`data_tf`, `chart_tf`/`agg_tf`, `range_from`, `range_to`), `analytics_repository`-Option
   `from_ts`/`to_ts`, Aggregations-TF-Dropdown fuer `Fix` (6a).
3. **[-] service_win (eigener Schritt, reduziert):** (entfaellt - `service_win.py` enthaelt keine MTF-FC-Integration) nur `data_tf` (Multi <-> `ALLE Timeframes`-Sentinel,
   U15-E) + optional Range; keine Sort/Sessions/Templates.
4. **[x] Doku:** (dieses Kapitel) 21.03-Kapitel in `docs/AKTUELLE_UMSETZUNG.md` auf Analytics-Ziel ausrichten.

## ?? 4. Verifikation (headless, Grundsatz 2)

- `py_compile` aller geaenderten Dateien; `import chart.chart_win` (kein GUI-Start);
  `node --check` fuer die JS-Ruecknahme; Logik-/DB-Tests in `test/test.py`.
- Keine UI-/Regressionstests (harte Regel).

## ?? 5. Umsetzung durchgefuehrt (12.08.2026, abgeschlossen)

> Nach dem Startschuss des Anwenders wurde die Architektur-Korrektur umgesetzt:
> Kapitel 21.03 ist vollstaendig auf das Analytics-Ziel ausgerichtet (der
> Chart-Revert lief in 21.03.11-Fix als Commit `85a0c7c`).

1. **Chart-Revert (Commit `85a0c7c`):** `chart/chart_win.py`, `chart/chart_basics.py`
   und `chart/js/04_live_updates.js` wurden auf `4217e71` zurueckgesetzt; die JS-Layer
   `07_mtf_fc.js`/`08_mtf_layers.js`/`09_mtf_axis.js` wurden entfernt (`git rm`). Damit
   sind die fehlenden Imports (NameError beim Chart-Oeffnen) und alle 21.03-Hooks aus
   dem Chart entfernt.
2. **Analytics-Integration (Commit `eae1d7b`):** `MtfFilterBarWidget` in
   `analytics_win._build_ui()` (Filter-Zeile, 11 Analytics-TFs statt 6 Chart-Defaults),
   Signal-Verdrahtung (data_tf/agg_tf/range/sort -> VM bzw. EventBus),
   `AnalyticsViewModel`-Parameter (`data_tf`, `agg_tf`, `range_from`, `range_to`,
   `all_timeframes`), Zeitfilter `from_ts`/`to_ts` in `FeatureStoreReader`/
   `AnalyticsRepository`/`AnalyticsWorker`, Aggregations-TF-Dropdown mit `bucket_tf`
   fuer die generische Heatmap (Entscheidung 6a), `now_provider` = `MAX(bar_time)`
   statt `time.time()`.
3. **service_win:** entfaellt - das `ServiceWindow` enthaelt keine MTF-FC-Integration
   (kein `MtfFilterBarWidget`, keine MTF-FC-Signale); es gibt nichts zu reduzieren.
4. **Doku:** 21.03-Kapitel auf das Analytics-Ziel ausgerichtet (dieses Kapitel).

- **Commit:** `85a0c7c` (Chart-Revert), `eae1d7b` (Analytics-Integration)

---

# Implementierungs-Log 21.03 (MTF-FC v4) - 12.08.2026 (Fortsetzung)

## 21.03.12 - Chart-Revert: MTF-FC aus dem Chart entfernt (12.08.2026)

- **Umgesetzt:** `git checkout 4217e71 -- chart/chart_win.py chart/chart_basics.py chart/js/04_live_updates.js`
  + `git rm chart/js/07_mtf_fc.js chart/js/08_mtf_layers.js chart/js/09_mtf_axis.js`.
  Damit sind die fehlenden MTF-FC-Imports (`MtfFcProvider`, `MtfFcBoundary`,
  `default_mtf_fc_state`, `MtfFilterBarWidget`, `evaluate_cascade`, `apply_transition`)
  und alle 21.03-JS-Hooks vollstaendig aus dem Chart entfernt (Revert-Ziel `4217e71`,
  fuer die 3 Ziel-Dateien identisch mit `69ae3a6`).
- **Verifikation:** Code-Suche in `chart/chart_win.py`/`chart/chart_basics.py`:
  keine `MtfFilterBarWidget`-/`mtf_fc`-Referenzen und keine Verweise auf die entfernten
  JS-Dateien mehr; `git status` zeigt die geloeschten JS-Dateien.
- **Commit:** `85a0c7c`

## 21.03.13 - Analytics-Integration: Filterleiste + Zeitfilter + Aggregations-TF (12.08.2026 20:06)

- **Umgesetzt:** Vollstaendige Umsetzung der Entscheidung 6a im Analytics-Fenster:
  * `chart/widgets/mtf_filter_bar.py`: eigenes Aggregations-TF-Dropdown (`agg_tf`,
    unabhaengig von `data_tf`), konfigurierbare TF-Listen (`data_tf_options`/
    `agg_tf_options`), injizierbarer `now_provider`, `apply_external_state()` und
    `set_chart_mode()` fuer den Profil-/Workspace-Restore, `_on_range_changed` nutzt
    den `now_provider` (Fallback `time.time()`).
  * `analytics/engine/analytics_view_model.py`: MTF-FC-Parameter `data_tf`/`agg_tf`/
    `range_preset`/`range_from`/`range_to`/`all_timeframes`; `set_data_tf` (multi ->
    `all_timeframes=True`, fixiert -> `timeframe`-Uebernahme), `set_agg_tf` -> `bucket_tf`
    in `_current_params`, `set_range`/`clear_range`, `latest_data_epoch` (MAX(bar_time));
    Persistenz ueber `_current_payload` (Sektion `sources`).
  * `analytics/engine/feature_store_reader.py`: `from_ts`/`to_ts`-Zeitfilter
    (`bar_time BETWEEN`, Wanduhr-Epochs) in fetch_rows/fetch_columns/fetch_heatmap/
    fetch_generic_heatmap; `bucket_tf`-date-Bucketing (FLOOR(EXTRACT(epoch)/secs)*secs)
    fuer die generische Heatmap; `_axis_coords`-/`_format_dim_value`-tz-Fixes.
  * `analytics/engine/analytics_repository.py` + `analytics_worker.py`: `from_ts`/
    `to_ts`/`bucket_tf` an alle Methoden durchgereicht.
  * `analytics/ui/analytics_win.py`: `mtf_bar` in `_build_ui`, Signal-Verdrahtung
    (data_tf/agg_tf/range/sort -> VM/EventBus), `_sync_mtf_bar_from_params` nach
    Profil-/Workspace-Restore, TF-Listen `MTF_DATA_TF_OPTIONS`/`MTF_AGG_TF_OPTIONS`
    (11 TFs M1..MN1).
  * `analytics/engine/mtf_fc_templates.py`: `agg_tf` in `_TEMPLATE_KNOWN_KEYS` +
    `_TEMPLATE_DEFAULTS` ergaenzt (View-Templates in-memory, wie im Chart).
- **Verifikation:** `py_compile` aller 7 geaenderten Dateien EXIT 0;
  `test/check_analytics_mtffc.py` (13 Checks: Zeitfilter, Bucketing, VM-Durchreichung)
  13/13 PASS; `test/check_analytics_mtffc_win.py` (22 Checks: Widget-VM-Integration,
  apply_external_state, Payload-Persistenz, Restore) 22/22 PASS; `test/test.py`
  Teil 21.03.12 T1-T10 PASS (26 vorbestehende FAILs in Test-32/36/37/20.03/Geometrie
  sind Bestandszustand: Test-DB-Fixtures ohne `instance_hash`-Spalte bzw. Qt-offscreen-
  Geometrie - nicht durch MTF-FC verursacht).
- **Commit:** `eae1d7b`

## 21.03.14 - Entscheidungen: 3 Anpassungswuensche (Range-Picker, Preset-Rueckbau, Kursluecken) (12.08.2026 20:42, Stand: Analyse & Entscheidung, KEIN Coding)

> **Anwender-Vorgabe (12.08.2026):** Drei Anpassungswuensche an der MTF-FC-Filterleiste
> (`MtfFilterBarWidget` im AnalyticsWindow) bzw. an der Heatmap-Darstellung wurden
> analysiert. Stand: Nur Analyse + Entscheidungs-Doku (kein Coding). Umsetzung erst
> nach explizitem Startschuss des Anwenders (Schritt 5).

### Wunsch 1 - "Benutzerdefiniert"-Range: Von-/Bis-Felder mit Date/Time-Picker (BESTAETIGT)

- **Entscheidung:** Bei benutzerdefiniertem Range werden ZWEI Eingabeboxen "Von" / "Bis"
  mit Date/Time-Picker-Widget (`QDateTimeEdit` mit `setCalendarPopup(True)`) angezeigt.
- **Zeitkonvention:** Bedienung als **Berlin-Wanduhr** (MT5-Epochs sind Wanduhr-encoded,
  Invariante 7) - die Konvertierung muss die Wanduhr-Konvention explizit abbilden
  (kein stiller OS-TZ-Offset wie bei Qt-Default).
- **Vorbelegung:** Beim Wechsel auf "Benutzerdefiniert" werden die Picker mit dem
  aktuellen Zeitraum (letzter gewaehlter Preset; Basis = letzter Datenpunkt
  `MAX(bar_time)` des `now_provider`, nicht `time.time()`) vorbelegt, nicht leer.
- **Validierung:** `from_ts <= to_ts` muss sichergestellt werden (Clamp/Swap oder
  UI-Warnung) - sonst liefert `bar_time BETWEEN f AND t` still leere Ergebnisse.
- **Backend-Status (bereits vorhanden):** `AnalyticsViewModel.set_range(from_ts, to_ts,
  preset)` + `FeatureStoreReader._apply_time_range` (`bar_time BETWEEN`, Wanduhr-Epochs)
  existieren; es fehlen nur UI + Restore. Aktuell wird der Eintrag "Benutzerdefiniert"
  in `_on_range_changed`/`apply_external_state` (mtf_filter_bar.py) uebersprungen.
- **UI-Platz:** Zwei Picker muessen platzsparend eingebaut werden (Bug-6-Hintergrund:
  sizeHint der Leiste darf nicht aufbrechen; ggf. Zeile 2).

### Wunsch 2 - Zusaetzliche Preset-Buttons rueckbauen + `sort_mode` ins Profil (BESTAETIGT)

- **Entscheidung:** Die zusaetzlichen View-Template-Steuerelemente des
  `MtfFilterBarWidget` ("Preset"-Namensfeld + 💾/📂-Buttons + Template-Combo, Zeile 2)
  werden ENTFERNT. Die Filter-Konfiguration laeuft ausschliesslich ueber das
  vorhandene Profil-Management (`AnalyticsProfileRepository`, Sektion `sources` im
  Profil-Payload, Option-B-Explicit-Save).
- **Begruendung:** `data_tf`/`agg_tf`/`range_preset`/`range_from`/`range_to` werden
  bereits pro Profil persistiert (`_current_payload`); `MtfFcTemplateStore` ist nur
  in-memory (Sitzungs-Scope) und ueberlebt keinen App-Neustart.
- **Ergaenzung:** `sort_mode` wird ZUSAETZLICH in den Profil-Payload aufgenommen
  (Sektion `sources`) - bisher laeuft die Sortierung nur ueber
  `event_bus.mtf_fc_sort_changed` -> `table_page.set_external_sort_mode` (in-memory).
  Ohne die Aufnahme ginge die Sortier-Auswahl nach dem Template-Rueckbau verloren.
- **Sessions:** Die Session-Checkboxen (London/New York/Tokio) werden NICHT entfernt -
  sie koennen zukuenftig wieder wichtig werden (bleiben im Analytics zunaechst
  unverdrahtet/angezeigt).
- **Hinweis:** `analytics/engine/mtf_fc_templates.py` wird nach dem Rueckbau toter
  Code (bleibt gemaess Code-Preserving-Regel erhalten, wird aber nicht mehr aufgerufen).

### Wunsch 3 - Durchgehende Kerzen- & Signalchart ohne Kursluecken (NICHT UMZUSETZEN)

- **Entscheidung:** Wird **NICHT umgesetzt** und es wird **keine Doku** dazu gefuehrt
  (kein Umsetzungs-Kapitel, kein Implementierungs-Log-Eintrag ueber eine Umsetzung).
- **Begruendung:** Architektur-Eingriff (kategoriales Heatmap-Grid vs. kontinuierliche
  Slot-Achse) bzw. neue Chart-Komponente; der Anwender hat den Wunsch nach Rueckfrage
  zurueckgezogen. Die bestehende Luecken-Darstellung (echte Bar-Epochs, Wochenend-/
  Handelspausen-Luecken) bleibt unveraendert.

---

- **Status:** Analyse + Entscheidungs-Doku abgeschlossen. KEIN Coding (wird nicht
  angefasst). Umsetzung der Schritte (1) und (2) erst nach explizitem Startschuss.
- **Commit:** `b00fd60`

---

# 21.03.14 - Umsetzung: Benutzerdefinierter Range + Preset-Rueckbau + sort_mode-Profilsierung (12.08.2026, nach Anwender-Startschuss)

> Nach dem Startschuss des Anwenders ("umsetzung 1. und 2.") wurden die
> Entscheidungen aus dem 21.03.14-Entscheidungs-Kapitel umgesetzt. Wunsch 3
> (durchgehende Kerzen-/Signalchart) bleibt - wie entschieden - unumgesetzt
> und undokumentiert.

## Umsetzung Wunsch 1 - Benutzerdefinierter Range mit Von-/Bis-Date/Time-Pickern (FERTIG)

- **Geaendert:** `chart/widgets/mtf_filter_bar.py` - In Zeile 2 (Session-Filter-Zeile)
  ersetzt ein `_custom_panel` (QWidget) die rueckgebauten View-Template-Controls:
  * Zwei `QDateTimeEdit`-Picker "Von:" / "Bis:" mit `setCalendarPopup(True)` und
    Anzeigeformat `dd.MM.yyyy HH:mm` (max. 150 px breit, platzsparend, sizeHint
    der Leiste bleibt klein).
  * Panel nur sichtbar, wenn der Range-Combo auf "Benutzerdefiniert" steht
    (`_show_custom_pickers`/`_hide_custom_pickers`).
  * **Wanduhr-Konvention (Invariante 7):** `_epoch_to_qdt`/`_qdt_to_epoch` bilden
    die (bereits Berlin-Wanduhr-encoded) Epochs direkt auf die QDateTime-FELDER ab
    (UTC-Darstellung der Epoch = Wanduhr, kein stiller OS-TZ-Offset).
  * **Vorbelegung:** Beim Wechsel auf "Benutzerdefiniert" werden die Picker mit dem
    letzten emittierten Zeitraum vorbelegt (`_last_range`); Basis = `now_provider`
    (letzter Datenpunkt `MAX(bar_time)` statt `time.time()`), Fallback 7 Tage.
  * **Validierung:** `_emit_custom_range` stellt `from_ts <= to_ts` sicher (Swap der
    Werte + Picker-Nachziehen, blockSignals gegen Signal-Loop).
  * `apply_external_state` um `range_from`/`range_to` erweitert: Restore eines
    gespeicherten benutzerdefinierten Zeitraums (Profil-/Workspace-Restore).
  * `_on_custom_range_changed` ohne `isVisible()`-Guard: Alle programmatischen
    Picker-Sets laufen ueber `_set_custom_pickers` (blockSignals) - der Guard war
    redundant und verpasste User-Edits, solange der Widget-Baum noch nicht sichtbar
    war (Restore vor Fenster-Shown).

## Umsetzung Wunsch 2 - Preset-Buttons rueckgebaut + `sort_mode` im Profil (FERTIG)

- **Geaendert:** `chart/widgets/mtf_filter_bar.py` - View-Template-Steuerelemente
  entfernt (Namens-`QLineEdit`, 💾/📂-Buttons, Template-`QComboBox`, Signal
  `template_applied`, Methoden `refresh_templates`/`_save_template`/`_load_template`/
  `_on_template_selected`/`_apply_template`); `template_store`-Parameter aus
  `__init__` entfernt; ungenutzter `QPushButton`-Import entfernt.
  `analytics/engine/mtf_fc_templates.py` bleibt gemaess Code-Preserving-Regel
  erhalten, wird aber nicht mehr aufgerufen (toter Code).
- **Geaendert:** `analytics/engine/analytics_view_model.py` - Default-Param
  `"sort_mode": "date"`; neue Methode `set_sort_mode(mode)` ('date'|'signal'|'tf',
  validiert, nur Dirty-Markierung - reiner UI-Zustand ohne Query-Refresh);
  `_current_payload` persistiert `sort_mode` additiv in der Sektion `sources`.
- **Geaendert:** `analytics/ui/analytics_win.py` - `_wire_controls` verbindet
  `mtf_bar.sort_mode_changed` zusaetzlich mit `_vm.set_sort_mode` (Profil-Persistenz;
  die EventBus-Kette zur TablePage bleibt); `_sync_mtf_bar_from_params` reicht
  `range_from`/`range_to`/`sort_mode` an `apply_external_state` weiter.
- **Sessions:** bleiben erhalten (unverdrahtet angezeigt), wie entschieden.

## Verifikation (headless, Grundsatz 2 - keine UI-/Regressionstests)

- `py_compile` aller 3 geaenderten Dateien EXIT 0.
- **Neu:** `test/check_custom_range_sortmode.py` (permanent, 42/42 PASS):
  * Teil A: Wanduhr-Konvertierung - QDateTime-Felder = UTC-Darstellung der Epoch,
    12:00-Epoch zeigt Stunde 12 (kein +2h-Shift), Round-Trip exakt.
  * Teil B: Custom-Panel - Combo-Wechsel blendet Picker ein, Vorbelegung aus
    letztem Range, Picker-Aenderung emittiert neu, Swap-Validierung (from<=to,
    Picker nachgezogen), Preset-Wechsel versteckt Panel, Custom-Werte ueberleben
    den Wechsel.
  * Teil C: Restore via `apply_external_state(range_preset="Benutzerdefiniert",
    range_from, range_to)` - Picker + Signal + Combo korrekt; None-Fallback ohne
    Crash (Default now-7d..now).
  * Teil D: `set_sort_mode` - Persistenz, Case-Normalisierung, Ungueltig->'date',
    Payload sources.sort_mode, `_restore_params_from_payload`.
  * Teil E: `apply_external_state(sort_mode=...)` setzt Combo + emittiert Signal.
  * Teil F: Integrationspfad Filterleiste -> VM - Custom-Range und sort_mode via
    Signale im VM, Payload-Roundtrip, Restore in ein neues Widget.
  * Teil G: AnalyticsWindow-Quelltext-Inspektion - sort_mode-Verdrahtung,
    EventBus-Kette, `_sync_mtf_bar_from_params` reicht range_from/to/sort_mode,
    keine View-Template-Reste im Widget.
- `test/check_analytics_mtffc_win.py` 22/22 PASS, `test/check_analytics_mtffc.py`
  13/13 PASS, `test/check_mtf_sort_binding.py` 21/21 PASS,
  `test/check_filterbar_visible.py` (sizeHint/sizeHint-Layout) PASS.
- `test/test.py`: Baseline-Vergleich per `git stash` - dieselben 26 vorbestehenden
  FAILs (Fenster-/Reflow-Geometrie, JSON-Feld-Aufloesung, instance_hash-Binder der
  20.03-Tests, Qt-offscreen-Artefakte) mit und ohne die Aenderung; die 21.03.14-
  Aenderung fuegt KEINE neuen FAILs hinzu.

- **Commit:** `1ed270c`

## 21.03.15 - Bug-Runde 5 Bugs: Range-Presets 90d/Year, Feld-Dropdown, Session-Zeile (FERTIG)

Umsetzung der 5 gemeldeten Bugs mit den Benutzer-Entscheidungen (21.03.15):
Bug 3 -> 'Year' (365-Tage-Fenster) statt 'YTD' + neues Preset '90d'; Bug 4 ->
Custom-Panel komplett entfernt (Sessions in Zeile 1 rechts neben Sort).

### Bug 1 - Heatmap 'Feld'-Dropdown schreibt wieder feature_ids (FIX)
- **Geaendert:** `analytics/ui/heatmap_widget.py` - die seit 10.08.2026
  (Runde 7) auskommentierte Verbindung `_combo_field.selection_changed ->
  _on_field_selection_changed` ist WIEDER AKTIV. Check/Uncheck im
  'Feld'-Dropdown schreibt `feature_ids` ueber den bestehenden
  ServicePicker-Pfad (`_reconcile_sammel_checks` -> `_checked_field_service_ids`
  -> `set_feature_ids`), damit ServicePicker-Auswahl und Feld-Dropdown
  konsistent bleiben. Docstring von `_on_field_selection_changed` aktualisiert.

### Bug 2 - Feld-Dropdown: bei leerem Filter NUR erster Parameter (FIX)
- **Geaendert:** `analytics/ui/heatmap_widget.py` - `_rebuild_field_dropdown`
  haengte bei leerem `feature_ids`-Filter JEDE Checkbox an (`no_filter=True`).
  Neu: lokaler Helper `_chk(match)` - im `no_filter`-Modus wird genau der
  ERSTE Parameter (erster Checkable-Eintrag) angehakt, alle weiteren leer
  (fuer AVG/SUM/MIN/MAX ist genau EIN aktives Hauptfeld sinnvoll). Bei
  aktivem Filter unveraendert (nur passende Haken).

### Bug 3 - Range-Presets: 'YTD' -> 'Year' (365 Tage) + '90d' (FIX)
- **Geaendert:** `chart/widgets/mtf_filter_bar.py` - `RANGE_PRESETS` =
  `["24h", "7d", "30d", "90d", "Year"]`; `_on_range_changed` rechnet
  `90d = 90*86400` und `Year = 365*86400` (kein Jahresbeginn-Fenster mehr,
  wie entschieden). `_ytd_epoch_offset` entfernt, ToolTip aktualisiert.
- **Migration:** Alt-Profile mit `'YTD'` -> `'Year'` und `'Benutzerdefiniert'`
  -> `'7d'` werden an 3 Stellen abgebildet: Widget `apply_external_state`
  (defensiv vor `setCurrentText`), VM `set_range` und VM
  `_restore_params_from_payload` (Restore-Pfad). Dadurch ueberleben
  gespeicherte Profile den Preset-Umbau.

### Bug 4 - Custom-Panel entfernt, Sessions in Zeile 1 (FIX)
- **Geaendert:** `chart/widgets/mtf_filter_bar.py` - das benutzerdefinierte
  Von-/Bis-Panel (QDateTimeEdit-Picker, Zeile 2) ist KOMPLETT entfernt:
  Imports (`QDateTime`/`QDateTimeEdit`), State-Vars (`_last_range`,
  `_custom_from`, `_custom_to`), Methoden (`_apply_custom_range_state`,
  `_default_custom_range`, `_set_custom_pickers`, `_show_custom_pickers`,
  `_hide_custom_pickers`, `_on_custom_range_changed`, `_emit_custom_range`,
  `_epoch_to_qdt`, `_qdt_to_epoch`), `apply_external_state`-Parameter
  `range_from`/`range_to` und der `"Benutzerdefiniert"`-Zweig. Die
  Session-Checkboxen stehen jetzt in ZEILE 1 rechts neben der Sortierung
  (eine Zeile, sizeHint 1152x26).
- **Geaendert:** `analytics/ui/analytics_win.py` - `_sync_mtf_bar_from_params`
  ruft `apply_external_state` ohne `range_from`/`range_to`.
- **Geaendert:** `analytics/engine/analytics_view_model.py` - Docstring von
  `set_range` aktualisiert ('7d'/'90d'/'Year'); `range_from`/`range_to`
  bleiben als effektiver Zeitfilter in den Params/Payload erhalten.
- **Geaendert:** `analytics/engine/mtf_fc_templates.py` - `custom_range` aus
  `_TEMPLATE_KNOWN_KEYS`/`_TEMPLATE_DEFAULTS` entfernt; neue Helper-Funktion
  `_normalize_obsolete` entfernt `custom_range` auch aus Alt-Templates mit
  bereits aktueller Schema-Version und mappt `YTD`/`Benutzerdefiniert`.

### Bug 5 - Viridis-Legende: Intervalle ohne ueberlappende Kanten (FIX)
- **Geaendert:** `analytics/ui/heatmap_widget.py` - `_update_legend`
  (Viridis-Zweig): die alten Labels `<= v25 / v25-v50 / v50-v75 / v75-vmax /
  >= v75` ueberlappten an v50/v75/vmax. Neu halboffene Intervalle [a,b):
  `< v25`, `v25-v50`, `v50-v75`, `v75-vmax`, `>= vmax` - jede Schwelle
  gehoert exakt zu EINEM Intervall.

### Verifikation (headless, Grundsatz 2 - keine UI-/Regressionstests)
- `py_compile` aller geaenderten Dateien EXIT 0 (mtf_filter_bar.py,
  analytics_win.py, analytics_view_model.py, heatmap_widget.py,
  mtf_fc_templates.py).
- **Neu/umgebaut:** `test/check_custom_range_sortmode.py` (permanent,
  47/47 PASS):
  * Teil A: Preset-Satz 24h/7d/30d/90d/Year, Sekunden exakt (90d/Year),
    'YTD'/'Benutzerdefiniert' entfallen, kein `_custom_panel`/`_dt_from`.
  * Teil B: `apply_external_state` migriert 'YTD'->'Year' und
    'Benutzerdefiniert'->'7d'; Signatur ohne range_from/range_to.
  * Teil C: VM-Migration `set_range` + `_restore_params_from_payload`.
  * Teil D: Session-Checkboxen (Bug 4) - London/New York/Tokio,
    `sessions_changed` emittiert korrekt.
  * Teil E-H: sort_mode-Persistenz (21.03.14 erhalten), Integrationspfad,
    AnalyticsWindow-Quelltext-Inspektion (kein range_from/to mehr, kein
    Custom-Picker-Code).
- **Neu:** `test/check_heatmap_field_checks.py` (permanent, 4/4 PASS):
  * Bug 1: `selection_changed` -> `set_feature_ids` (Verbindung aktiv).
  * Bug 2: no_filter -> genau EIN Haken (erster Parameter); aktiver Filter
    -> passende Haken.
- Unveraendert gruen: `test/check_analytics_mtffc_win.py` 22/22,
  `test/check_analytics_mtffc.py` 13/13, `test/check_mtf_sort_binding.py`
  21/21; `test/check_filterbar_visible.py` (Diagnose) zeigt die neue
  EIN-Zeilen-Leiste (sizeHint 1152x26, alle Controls sichtbar).
- `test/test.py` referenziert keine entfernten APIs (kein Custom-Panel/
  YTD-Code); die MTF-FC-Kette bleibt unveraendert.

- **Commit:** 22e2b66

## 21.03.16 - Option A Feld-Dropdown (Parameter-Ebene, Bug 1/2) + Viridis-Legende (Bug 5) (12.08.2026 23:20, FERTIG)

> Nach dem Anwender-Startschuss wurde Option A (echte Parameter-Filterung) umgesetzt.
> Der User hatte die 3 Bugs (Feld-Dropdown wirkt nicht / wird nicht restored,
> falsche Vorbelegung bei Aggregations-Wechsel, unsinnige Legenden-Wertebereiche)
> als zu 100% weiterbestehend gemeldet. Entscheidung: Bug 1/2 = Parameter-Ebene
> wirklich filtern (Option A), Bug 5 = Operator-Labels + adaptive Genauigkeit.

### Kern-Architektur (Option A): (Service|Parameter)-Paare statt Service-IDs
- Die Checkboxen im 'Feld'-Dropdown repr?sentieren `{service_id}|{key}`-Paare
  (bisher wurden daraus NUR Service-IDs abgeleitet und auf Service-Ebene
  gefiltert - Abw?hlen eines Parameters bei 2 Parametern eines Services
  ?nderte nichts, weil die Service-Menge gleich blieb; Bug 1).
- **Neu:** `field_selection` (Liste `"{service_id}|{key}"`) wird als
  effektive Paar-Auswahl persistiert (Profil/Workspace) und beim
  Aggregations-/Restore-Wechsel EXAKT wieder hergestellt (Bug 2: keine
  'alle Parameter'-Vorbelegung mehr).
- **Reader-Filter:** `_apply_field_pair_filter()` erweitert die WHERE-Clause
  der generischen Heatmap um eine OR-Bedingung je Paar
  (`LOWER(TRIM(feature_id)) = ? AND json_extract_string(feature_data,
  '$.key') IS NOT NULL`) - An/Abw?hlen eines Parameters ?ndert die Grafik
  wirklich (nur Rows, deren feature_data den gew?hlten JSON-Key des
  jeweiligen Services tr?gt). Identifier-unsichere Keys werden defensiv
  ?bersprungen (kein SQL-Injection-Risiko, Muster `_is_json_key_identifier`).
- **DuckDB-Arrow-Bug (v1.5.5):** `feature_data->>'key'` kollidiert in
  Kombination mit `LOWER(TRIM(feature_id))`-Equalities mit einem
  Optimizer-Bug (versucht die JSON-Spalte auf numerisch/BOOL zu casten und
  wirft f?r nicht-matchende Zeilen). `json_extract_string(feature_data,
  '$.key')` liefert identische NULL-Semantik und ist auf JSON- UND
  VARCHAR-Spalten stabil.

### Bug 1 - Feld-Dropdown: An/Abw?hlen wirkt auf Grafik + wird restored (FIX)
- **Ge?ndert:** `analytics/ui/heatmap_widget.py` - `_on_field_selection_changed`
  ruft jetzt `set_field_selection(pairs)` (statt nur `set_feature_ids(ids)`).
  Neue Helfer `_checked_field_pairs()` (ALL|key-Expansion ?ber
  `_field_sources`) und `_sync_field_selection_to_vm()` (materialisiert die
  effektive Paar-Auswahl am Ende jedes Rebuilds).
- **Ge?ndert:** `analytics/engine/analytics_view_model.py` - neue Methode
  `set_field_selection(field_pairs, update_ids=True)`:
  * `update_ids=True` (User-Interaktion): `feature_ids` werden aus den
    Paaren abgeleitet (Dropdown/Picker konsistent; Abw?hlen des letzten
    Parameters entfernt den Service aus dem Picker).
  * `update_ids=False` (programmatischer Sync): `feature_ids` bleiben
    UNANGETASTET - der ServicePicker ist die Service-Quelle; Services ohne
    numerische Feld-Keys fallen dadurch nie aus der Auswahl.
  * Refresh auch bei UNVER?NDERTER Service-Menge, wenn sich die
    Parameter-Auswahl ge?ndert hat (Bug 1).
- **Persistenz:** `field_selection` wird in `_current_payload`/Restore-Pfaden
  via `_normalize_field_pairs` normalisiert (Alt-Payloads ohne Key = leer =
  kein Paar-Filter, Verhalten wie bisher).
- **Ge?ndert:** `analytics/engine/analytics_worker.py` /
  `analytics/engine/analytics_repository.py` /
  `analytics/engine/feature_store_reader.py` - `field_pairs`-Param
  durchgereicht bis `fetch_generic_heatmap` + Filter-Anwendung.

### Bug 2 - Aggregations-Wechsel: EXAKTE Vorbelegung statt 'alle Parameter' (FIX)
- **Ge?ndert:** `analytics/ui/heatmap_widget.py` - `_rebuild_field_dropdown`:
  EXPLIZITE `field_selection` gewinnt (sel_map; Rebuild stellt die
  gew?hlten Paare exakt wieder her). Ohne explizite Auswahl greift die
  DEFAULT-Vorbelegung: je AKTIVEM Service genau der ERSTE Parameter
  (sortierte Key-Reihenfolge), bei leerem Filter (alle Features) nur der
  erste Eintrag insgesamt (Verhalten wie bisher). Der fr?here 21.03.15-Fix
  (`_chk` im no_filter-Modus) wurde durch die generalisierte Logik ersetzt.
- Explizit-Pfad-Guard: Paare INAKTIVER Services (nicht in feature_ids)
  werden nicht angehakt und beim Sync beschnitten.

### Bug 5 - Viridis-Legende: Operator-Labels + adaptive Genauigkeit (FIX)
- **Ge?ndert:** `analytics/ui/heatmap_widget.py` - neuer Helper
  `_format_legend_value(val, span)`: Nachkommastellen-Zahl wird aus der
  Spanne abgeleitet (25-%-Schritte `span/4` GARANTIERT unterscheidbar;
  kleine Spannen vmin=0.01/vmax=0.02 -> 0.0125/0.015/0.0175/0.02 statt
  kollabierter '0.01 - 0.01'). `_update_legend` (Viridis-Zweig) nutzt
  eindeutige Operator-Labels: `< v25`, `v25 ? x < v50`, `v50 ? x < v75`,
  `v75 ? x ? vmax`, `? vmax` (statt Bindestrich-Intervallen).

### Verifikation (headless, Grundsatz 2 - keine UI-/Regressionstests)
- `py_compile` aller 5 ge?nderten Dateien EXIT 0 (analytics_view_model.py,
  analytics_worker.py, analytics_repository.py, feature_store_reader.py,
  heatmap_widget.py).
- **Neu:** `test/check_field_selection.py` (permanent, 19/19 PASS):
  Default-Vorbelegung (leerer Filter / erster Parameter je aktivem
  Service), EXPLIZITE Restaurierung nach Aggregations-Wechsel, ALL-
  Expansion in `_checked_field_pairs`, `set_field_selection`-Pfade
  (update_ids=True/False), Sync-Guards (inaktive Paare, Services ohne
  Keys bleiben in feature_ids), `_format_legend_value`.
- **Neu:** `test/check_field_pairs_db.py` (permanent, 5/5 PASS, temp.
  duckdb in test/ und danach gel?scht): Paar-Filter greift in echter
  DuckDB-Query (COUNT/AVG, feature_ids orthogonal, unsichere Keys
  defensiv).
- Bestehende Tests unver?ndert gr?n (Spot-Check): `test/check_heatmap_field_checks.py`
  (4/4, Service-Pfad bleibt ?ber den Fallback `hasattr(set_field_selection)`
  kompatibel), `test/check_custom_range_sortmode.py` (47/47).

- **Commit:** `33c33ce`

---

# 21.03.20 – Analytics Modus-Filter für Multi-Modus-Services (UI Enhancement)

---

## 🎯 1. Problemstellung & Ursachenanalyse

| Symptom / Problem | Technische Ursache im Quellcode |
| --- | --- |
| **Vermischung unterschiedlicher Berechnungsverfahren** | Services wie `srv_swing_structure` oder `srv_swing_momentum` besitzen einen `mode`-Parameter mit völlig unterschiedlichen Logiken und Messskalen (z. B. `Williams_Fractal` vs. `ZigZag_ATR` oder `MA_Peak_Hysteresis` vs. `Chande_Kroll_Ratchet`). In `analytics_win.py` / `heatmap_widget.py` fehlte bisher ein Filter-Dropdown für `source_mode`. Dadurch wurden die Ergebnisse verschiedener Modi desselben Services in einer Heatmap-Matrix/Tabelle vermischt und verfälscht. |

**Prämisse (Code-verifiziert, 13.08.2026):** Das Feld `source_mode` wird top-level in **jedes** `feature_data`-JSON-Record geschrieben – verifiziert in 6 Services:
`analytics/features/definitions/srv_swing_structure.py` (Z. 631, Modi u. a. `Williams_Fractal`, `Standard_Pivot`, `Gann_Mechanical`, `ZigZag_ATR`, `ZigZag_Pct`, `Period_Extrema`), `srv_swing_momentum.py` (Z. 541/564, Modi u. a. `MA_Peak_Hysteresis`, `MA_Slope_Change`, `Chande_Kroll_Ratchet`), sowie `srv_swing_volume_profile.py`, `srv_trend_breakout.py`, `srv_trend_hma_pivot.py`, `srv_trend_regime.py`. Der `mode`-Parameter liegt in `parameter_schema["mode"]["options"]` der jeweiligen Service-Definition.

---

## ✅ 2. Fixierte Entscheidungen des Anwenders (13.08.2026)

> Die Anforderung wurde auf Integrität, Korrektheit, Vollständigkeit und fachliche
> Sinnhaftigkeit geprüft. Die offenen Punkte wurden vom Anwender wie folgt entschieden:

1. **Scope = GLOBAL:** Der `service_mode`-Filter wirkt auf **alle** Analytics-Datenquellen:
   * Legacy-Heatmap (`fetch_heatmap`, Dow×Stunde),
   * generische Heatmap (`fetch_generic_heatmap`),
   * Tabelle (`fetch_rows`),
   * Scatter (`fetch_columns`),
   * Verteilung (`fetch_columns`).
   Die Refresh-Liste von `set_service_mode` umfasst daher `QUERY_FEATURES`, `QUERY_TABLE`, `QUERY_HEATMAP`, `QUERY_HEATMAP_GENERIC`, `QUERY_SCATTER` und `QUERY_DISTRIBUTION` (analog zu `set_range`/`set_feature_ids`).
2. **Dropdown-Quelle = DYNAMISCH (Performance-Lösung):** Um keinen teuren Extra-Scan pro UI-Event auszulösen, wird die `SELECT DISTINCT`-Abfrage für `source_mode` **direkt in den leichten `QUERY_FEATURES`-Metadaten-Scan im `FeatureStoreReader` integriert**, der ohnehin im Worker-Thread gecacht läuft. Kein separater DB-Roundtrip für das Dropdown.
3. **Nur SQL-Filterung (keine Kaskadierung auf das 'Feld'-Dropdown):** Das 'Feld'-Dropdown bleibt unverändert. Die Mode-Auswahl filtert ausschließlich die SQL-WHERE-Bedingung. Ergebnis: Wenn ein angehakter Parameter (`field_pairs`) vom gewählten Modus nicht produziert wird, liefern die betroffenen Zellen/Zeilen leer (0/NaN) – korrekt, keine Fehlermeldung, kein verfälschter Mix.
4. **Leerer-Modus-Fall = Dropdown ausgrauen/deaktivieren:** Wenn die aktive Service-Auswahl (`feature_ids`/`instance_hashes`) keinen einzigen Service enthält, der `source_mode` in seine Records schreibt, wird `_combo_mode_filter` **deaktiviert (disabled)** und auf `[ Alle Modi ]` zurückgesetzt. Bei `feature_ids = []` (kein Filter = alle Services) gilt das Dropdown als aktiv, sobald im Datenbestand mindestens ein Service `source_mode` schreibt.
5. **Threading-Kette = VOLLSTÄNDIG (ja):** `service_mode` wird vollständig durchgereicht:
   `AnalyticsViewModel._current_params()` → `AnalyticsAsyncWorker._execute()` → `AnalyticsRepository.get_table()/get_heatmap()/get_generic_heatmap()/get_scatter()/get_distribution()` → `FeatureStoreReader.fetch_rows()/fetch_columns()/fetch_heatmap()/fetch_generic_heatmap()`.

---

## 🏗️ 3. Fachliches Konzept & Lösungsarchitektur

1. **Einbau `_combo_mode_filter` in `HeatmapWidget`:**
* **Platzierung:** In der zweiten Steuerzeile (`ctrl2`) von `HeatmapWidget` direkt zwischen **Aggregation** (`_combo_agg`, `COUNT`, `AVG` ...) und **Feld** (`_combo_field`, Ergebnis-Parameter).
* **Inhalt:** `[ Alle Modi ]` (Item-Data `"all"`) sowie alle dynamisch ermittelten `source_mode`-Werte der aktuellen Datenlage.
* **Platz-Budget:** Bug-6-Hintergrund beachten – Label + Combo (min. 150 px) müssen in `ctrl2` platzsparend bleiben (sizeHint der Steuerzeile darf nicht aufbrechen).

2. **SQL-Filterung über `source_mode` (GLOBAL):**
Der `FeatureStoreReader` erweitert die SQL-WHERE-Bedingung aller 4 Daten-Pfade bei gewähltem Modus um:

AND LOWER(json_extract_string(feature_data, '$.source_mode')) = LOWER(?)

* **Muster-Konsistenz (21.03.16):** `json_extract_string` statt `feature_data->>'source_mode'` – der DuckDB-Arrow-Operator (v1.5.5) kollidiert in Kombination mit LOWER/TRIM-Equalities mit einem Optimizer-Bug (Cast-Versuch der JSON-Spalte auf numerisch/BOOL). `json_extract_string` liefert identische NULL-Semantik und ist auf JSON- UND VARCHAR-Spalten stabil.
* **Case-Toleranz:** `LOWER` auf beiden Seiten; ungewöhnliche Schreibweisen (z. B. `ma_peak_hysteresis` vs. `MA_Peak_Hysteresis`) matchen zuverlässig.

3. **Dynamische Modus-Liste ohne Extra-Scan (Performance-Lösung):**
* Der `QUERY_FEATURES`-Leichtpfad (bestehender Feld-Metadaten-Scan im `FeatureStoreReader`, läuft im Worker-Thread und wird gecacht) liefert additiv ein Payload-Attribut `source_modes: [...]` (distinct, case-original, leer = keine Modi vorhanden) sowie ein Flag `has_source_mode_services: bool`.
* SQL: `SELECT DISTINCT json_extract_string(feature_data, '$.source_mode') ... WHERE <gleiche Filter wie Metadaten-Scan> AND json_extract_string(feature_data, '$.source_mode') IS NOT NULL` (Wanduhr/Zeitfilter unkritisch – Metadaten-Scan ist ohnehin zeitlich ungefiltert).
* Das HeatmapWidget befüllt `_combo_mode_filter` aus diesem Attribut (blockSignals, `_syncing`-Guard) – kein separater DB-Zugriff im UI-Thread (Grundsatz 4/MVVM).

4. **Keine Kaskadierung auf das 'Feld'-Dropdown (Entscheidung 3):** `_rebuild_field_dropdown` bleibt unverändert; die `field_pairs`-Logik (21.03.16) und der Mode-Filter wirken unabhängig voneinander als UND-Bedingungen.

5. **ViewModel- & Profil-Persistenz:**
Der gewählte `service_mode` wird im `AnalyticsViewModel` (`_params`, Default `"all"`) verwaltet und additiv in der `sources`-Sektion des Profil-Payloads persistiert/restauriert (Muster `sort_mode`, 21.03.14). Der Restore erfolgt automatisch über die generische Key-Schleife in `_restore_params_from_payload` (Replace-Semantik, B3-2).

---

## 🛠️ 4. Schritt-für-Schritt Umsetzungsanleitung für die IDE

### Schritt 1: ViewModel-Erweiterung (`analytics/engine/analytics_view_model.py`)

1. **Parameter `service_mode` hinzufügen:** In `_params` den Default `"all"` hinterlegen:

# analytics/engine/analytics_view_model.py
self._params["service_mode"] = "all"

2. **Setter-Methode `set_service_mode` implementieren (GLOBALER Refresh):**

# analytics/engine/analytics_view_model.py
def set_service_mode(self, mode: str) -> None:
    """Setzt den Modus-Filter (z. B. 'MA_Peak_Hysteresis' oder 'all').

    Global: Der Filter wirkt auf Tabelle, beide Heatmaps, Scatter und
    Verteilung (Entscheidung 1). QUERY_FEATURES wird mitrefreshed, damit
    die dynamische Modus-Liste / das Deaktivierungs-Flag (has_source_mode_
    services) synchron zur Auswahl bleibt.
    """
    mode = str(mode or "all").strip()
    if mode == self._params.get("service_mode"):
        return
    self._params["service_mode"] = mode
    self._mark_dirty()
    self._refresh((QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP,
                   QUERY_HEATMAP_GENERIC, QUERY_SCATTER,
                   QUERY_DISTRIBUTION))

3. **In `_current_params()` durchreichen – für ALLE Query-Kinds (global):**

# analytics/engine/analytics_view_model.py (in _current_params, Basis-Dict)
base["service_mode"] = p.get("service_mode", "all")

4. **Persistenz (`_current_payload`), Sektion `sources` – additiv:**

# analytics/engine/analytics_view_model.py (in _current_payload, sources)
"service_mode": p.get("service_mode"),

   (Restore läuft automatisch über `_restore_params_from_payload`, sobald der Key im Payload steht – kein Sonderfall.)

### Schritt 2: Reader-SQL-Filterung (`analytics/engine/feature_store_reader.py`)

1. **SQL-Helper für `source_mode` hinzufügen:**

# analytics/engine/feature_store_reader.py
@staticmethod
def _apply_mode_filter(service_mode: Optional[str], conditions: List[str], params: List[Any]) -> None:
    if not service_mode or str(service_mode).lower() in ("all", "alle", ""):
        return
    conditions.append("LOWER(json_extract_string(feature_data, '$.source_mode')) = LOWER(?)")
    params.append(str(service_mode).strip())

2. **In ALLEN 4 Daten-Pfaden aufrufen (global, Entscheidung 1):**

# analytics/engine/feature_store_reader.py (in fetch_rows / fetch_columns /
# fetch_heatmap / fetch_generic_heatmap, jeweils nach _apply_field_pair_filter/
# _apply_time_range)
self._apply_mode_filter(service_mode, conditions, params)

   Dafür bekommen alle 4 Methoden einen neuen Parameter `service_mode: Optional[str] = None`.

3. **Dynamischer Modus-Scan (Performance-Lösung, Entscheidung 2) – im `QUERY_FEATURES`-Leichtpfad:**

# analytics/engine/feature_store_reader.py
def fetch_available_source_modes(self, symbol, timeframe, feature_ids=None,
                                 instance_hashes=None) -> Dict[str, Any]:
    """DISTINCT source_mode-Werte (case-original) + Has-Flag für das
    Modus-Dropdown. Kein separater DB-Roundtrip: wird im bestehenden
    QUERY_FEATURES-Metadaten-Scan (Worker-Thread, gecacht) mitgeliefert.
    """
    # SELECT DISTINCT json_extract_string(feature_data, '$.source_mode')
    #   FROM feature_store
    #  WHERE <feature_ids/instance_hashes-Filter wie _apply_feature_filter>
    #    AND json_extract_string(feature_data, '$.source_mode') IS NOT NULL
    # return {"source_modes": [...], "has_source_mode_services": bool}

   Integration: `AnalyticsRepository` (QUERY_FEATURES-Pfad bzw. `_field_metadata`) ruft den Scan auf und hängt `source_modes` + `has_source_mode_services` an den Payload. Leere Liste = kein Service mit `source_mode` → UI deaktiviert das Dropdown (Entscheidung 4).

### Schritt 3: Worker- & Repository-Durchreichung (Threading-Kette, Entscheidung 5)

1. **`analytics/engine/analytics_worker.py` (`_execute`):** `service_mode = p.get("service_mode")` einmalig lesen und an **alle 5** Repo-Methoden übergeben:
   `get_table(..., service_mode=service_mode)`, `get_heatmap(...)`, `get_generic_heatmap(...)`, `get_scatter(...)`, `get_distribution(...)`.
2. **`analytics/engine/analytics_repository.py`:** Alle 5 Methoden erhalten `service_mode: Optional[str] = None` und reichen ihn an den Reader durch. Der `QUERY_FEATURES`-Pfad liefert zusätzlich `source_modes`/`has_source_mode_services` aus Schritt 2.3.

### Schritt 4: UI-Integration (`analytics/ui/heatmap_widget.py`)

1. **Dropdown in `__init__` anlegen und im Layout platzieren:**

# analytics/ui/heatmap_widget.py
self._combo_mode_filter = QComboBox()
self._combo_mode_filter.setMinimumWidth(150)
self._combo_mode_filter.addItem("Alle Modi", "all")
self._combo_mode_filter.setEnabled(False)  # bis zum ersten Payload mit Modi

# In Layout ctrl2 zwischen _combo_agg und _combo_field einfügen:
ctrl2.addWidget(QLabel("Modus:"))
ctrl2.addWidget(self._combo_mode_filter)

2. **Event-Verbindung & Sync:**

# analytics/ui/heatmap_widget.py
self._combo_mode_filter.currentIndexChanged.connect(self._on_mode_filter_changed)

def _on_mode_filter_changed(self) -> None:
    if self._syncing or self._view_model is None:
        return
    mode = str(self._combo_mode_filter.currentData() or "all")
    self._view_model.set_service_mode(mode)

3. **Dynamische Befüllung + Deaktivierung aus dem Payload (Entscheidungen 2 + 4):**
   Bei eingehendem Payload (in der bestehenden `_apply_payload`-Kette, analog `_rebuild_field_dropdown`):
   * `source_modes` aus dem Payload lesen; Combo unter `blockSignals`/`_syncing` neu befüllen (`[ Alle Modi ]` + Modi, Item-Data = case-originaler Wert).
   * `has_source_mode_services == False` → `_combo_mode_filter.setEnabled(False)` und auf `"all"` zurücksetzen (kein stiller Filter); sonst `setEnabled(True)`.
   * Restore: In der VM-Sync-Methode (Muster `_sync_controls_from_vm` bzw. `_on_params_restored`) wird der Combo-Index aus `vm.params["service_mode"]` gesetzt (blockSignals) – Profil-/Workspace-Restore.
   * Entfernen veralteter Modi (nicht mehr im Payload) bei jedem Rebuild – keine verwaisten Auswahlwerte.

### Schritt 5: Keine Änderungen (bewusst)

* **Keine Kaskadierung auf `_rebuild_field_dropdown`** (Entscheidung 3 – nur SQL-Filterung).
* **`analytics/ui/analytics_win.py`:** nur falls der Profil-/Workspace-Restore den Combo-Zustand außerhalb der VM-Params synchronisieren muss (Muster `_sync_mtf_bar_from_params`) – voraussichtlich nicht nötig, da das HeatmapWidget die Combo direkt aus `vm.params` restauriert.

---

## 📊 5. Akzeptanzkriterien für die Validierung (`test/test.py`)

1. **Modus-Filter-SQL-Test (global):** `fetch_generic_heatmap(..., service_mode="MA_Peak_Hysteresis")` UND `fetch_rows`/`fetch_columns`/`fetch_heatmap` erzeugen in der SQL-WHERE-Klausel den Ausdruck `LOWER(json_extract_string(feature_data, '$.source_mode')) = LOWER(?)` mit Parameter `'MA_Peak_Hysteresis'` und filtern abweichende Modi aus (`"all"`/None/leer = kein Filter).
2. **ViewModel-State-Test:** `set_service_mode("ZigZag_ATR")` setzt das Dirty-Flag, aktualisiert `_params["service_mode"]` und stößt die Datenabfragen neu an – Refresh-Liste enthält `QUERY_FEATURES`, `QUERY_TABLE`, `QUERY_HEATMAP`, `QUERY_HEATMAP_GENERIC`, `QUERY_SCATTER`, `QUERY_DISTRIBUTION` (global, Entscheidung 1).
3. **Threading-Ketten-Test:** `_current_params` → Worker → alle 5 Repo-Methoden → alle 4 Reader-Pfade – `service_mode` erreicht jede Query (Entscheidung 5).
4. **Metadaten-Scan-Test (Performance-Lösung):** `QUERY_FEATURES`-Payload enthält `source_modes` (distinct, case-original, ohne NULL) und `has_source_mode_services`; der Scan wird **ohne** separaten Roundtrip im bestehenden Metadaten-Scan-Pfad geliefert (Entscheidung 2).
5. **Deaktivierungs-Test (Entscheidung 4):** `feature_ids` ausschließlich mit Services ohne `source_mode` (z. B. `srv_grid_lines`) → `has_source_mode_services == False` → Combo disabled + auf `"all"` zurückgesetzt; mit `source_mode`-Service → enabled.
6. **Persistenz-Test:** `sources.service_mode` im Profil-Payload-Roundtrip; `_restore_params_from_payload` stellt `"all"`-Default bzw. gespeicherten Modus korrekt wieder her.
7. **Leerer-Modus-Ergebnis-Test:** Gewählter Modus, der in den aktiven Services nicht vorkommt → leere Matrix/Tabelle (0/NaN), kein Crash, keine Fehlermeldung.

## 📁 6. Dateien (Übersicht)

| Datei | Art | Inhalt |
| --- | --- | --- |
| `analytics/engine/analytics_view_model.py` | geändert | `service_mode`-Param + Setter (globaler Refresh) + `_current_params` + `_current_payload` (sources) |
| `analytics/engine/analytics_worker.py` | geändert | Durchreichung `service_mode` an alle 5 Repo-Methoden |
| `analytics/engine/analytics_repository.py` | geändert | `service_mode`-Parameter an 5 Methoden; `source_modes`/`has_source_mode_services` im QUERY_FEATURES-Pfad |
| `analytics/engine/feature_store_reader.py` | geändert | `_apply_mode_filter` + `service_mode`-Param an 4 Reader-Pfade + `fetch_available_source_modes` |
| `analytics/ui/heatmap_widget.py` | geändert | `_combo_mode_filter` (Layout, Signal, Payload-Befüllung, Deaktivierung, Restore) |
| `analytics/ui/analytics_win.py` | ggf. geändert | nur falls Restore den Combo außerhalb der VM-Params braucht (voraussichtlich nicht) |

## ✅ Verifikations-Rahmen (Grundsatz 2)

- Headless: `py_compile` aller geänderten Dateien; Logik-/DB-Tests in `test/` (temporäre `*.duckdb` nur in `test/`, danach Cleanup).
- Keine UI-/Regressionstests (harte Regel). UI-Verhalten (Dropdown-Sichtbarkeit/Deaktivierung) per Code-Inspektion + manueller Anwender-Prüfung.
- Implementierungs-Log: Eintrag 21.03.20 in `docs/AKTUELLE_UMSETZUNG.md` nach Anwender-Bestätigung.



---

# Implementierungs-Log 21.03.20 - Analytics Modus-Filter (13.08.2026 10:41)

- **Umgesetzt (Entscheidungen 1-5):**
  - `analytics/engine/analytics_view_model.py`: `_params["service_mode"] = "all"` Default, `set_service_mode(mode)` mit globalem Refresh (QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC, QUERY_SCATTER, QUERY_DISTRIBUTION; idempotent), `_current_params` Basis-Dict `service_mode` fuer ALLE Query-Kinds, `_current_payload` sources-Sektion `service_mode` (Restore ueber generische Key-Schleife).
  - `analytics/engine/feature_store_reader.py`: `_apply_mode_filter` (json_extract_string + LOWER, `"all"`/None/leer = kein Filter) an allen 4 Daten-Pfaden (`fetch_rows`/`fetch_columns`/`fetch_heatmap`/`fetch_generic_heatmap`); `service_mode`-Parameter an alle 4 Signaturen; `_feature_meta_base` sammelt additiv `source_modes_by_service` (gleicher gecachter Basis-Scan, kein Extra-Roundtrip); neue Methode `fetch_available_source_modes(symbol, timeframe, feature_id, feature_ids, instance_hashes) -> (source_modes, has_source_mode_services)` mit feature_ids-/Hash-Filter (Muster `feature_keys_by_service`).
  - `analytics/engine/analytics_worker.py`: `service_mode = p.get("service_mode")` einmalig lesen, Durchreichung an alle 5 Repo-Methoden (`get_table`/`get_heatmap`/`get_generic_heatmap`/`get_scatter`/`get_distribution`).
  - `analytics/engine/analytics_repository.py`: `service_mode`-Parameter an alle 5 Methoden + Reader-Durchreichung; `get_available_features` liefert im QUERY_FEATURES-Leichtpfad `source_modes` + `has_source_mode_services` (defensiv leere Liste/False bei Fehler).
  - `analytics/ui/heatmap_widget.py`: `_combo_mode_filter` (QComboBox, `[ Alle Modi ]` = data "all", min 150 px) in ctrl2 zwischen Aggregation und Feld; Signal `currentIndexChanged` -> `_on_mode_filter_changed` -> `vm.set_service_mode`; `_sync_mode_filter_from_payload` (blockSignals/_syncing, Stale-Guard via restore_generation) befuellt die Items aus `source_modes` (case-original), deaktiviert + resettet auf `"all"` bei `has_source_mode_services == False`, Restore aus `vm.params["service_mode"]`; `_sync_from_params` restauriert die Auswahl.
- **Verifikation (headless, keine UI):**
  - `py_compile` aller 5 geaenderten Quelldateien + 4 neuen Testdateien OK.
  - `test/check_mode_filter_db.py` (26 Checks): `fetch_available_source_modes` (distinct/sortiert, feature_ids-Filter, has-Flag), alle 4 Reader-Filter-Pfade (rows/columns/heatmap/generic), Repo-Payload (`source_modes`/`has_source_mode_services`), `get_table`/`get_heatmap`/`get_scatter`/`get_distribution`-Durchreichung - ALLE PASS.
  - `test/check_mode_filter_worker.py` (6 Checks): Dispatch-Kette _execute -> alle 5 Repo-Methoden - PASS.
  - `test/check_mode_filter_vm.py` (11 Checks): Default, Idempotenz, globaler Refresh, Dirty-Flag, `_current_params` fuer 6 Kinds, `_current_payload` sources - PASS.
  - `test/check_mode_filter_widget.py` (10 Checks): Items, enabled/disabled (Entscheidung 4), Reset auf all, `_on_mode_filter_changed`, Stale-Guard - PASS.
  - Bestehende Tests gruen: `check_analytics_mtffc.py` (13), `check_analytics_mtffc_win.py` (22), `check_field_pairs_db.py` (5), `check_field_selection.py` (19), `check_heatmap_field_checks.py`, `check_mtf_sort_binding.py` (21). `check_custom_range_sortmode.py` NICHT lauffaehig (externe DB-Sperre data/app_data.duckdb durch laufende App - unabhaengig von dieser Umsetzung).
- **Commit:** ceb2351
# Implementierungs-Log 21.03.20 - Bugfixing Runde: Layout / Modus-Dropdown / Service-Achse (13.08.2026)

- **Bug 1 (Layout, Mauszeiger-Werteanzeige):** `analytics/ui/heatmap_widget.py` - `_label_info` (Werteanzeige) liegt jetzt VOR `_combo_field` in ctrl2 (Spacing 6), `_combo_field` behaelt Stretch 1 (wachst bis Canvas-Ende). Verifiziert: `test/check_bugfix_2132_layout.py` PASS (info=15, field=17, stretch=1).
- **Bug 2 (Modus-Dropdown zeigte nur DB-geschriebene Modi):** `analytics/engine/analytics_repository.py` - neue `_registry_source_modes()` (classmethod) liest `parameter_schema["mode"]["options"]` der aktiven Services (PluginRegistry-Singleton, in-Memory) und merged per `dict.fromkeys`-UNION in `source_modes` (DB-Modi zuerst, dann Registry-Modi sortiert); `has_source_mode_services = bool(has_sm or registry_modes)`; `Set`-Import ergaenzt.
- **Bug 3 (Service-Achse mit Modus-Suffix):**
  - `analytics/engine/feature_store_reader.py`: `DIM_MAPPINGS["service_id"]` = `LOWER(feature_id) || '::' || COALESCE(json_extract_string(feature_data, '$.source_mode'), '')` (source_mode case-original); `fetch_generic_heatmap` neuer Parameter `extra_service_modes: Optional[List[str]] = None` ergaenzt fehlende `{feature_id}::{mode}`-Kombinationen als Achsenpunkte (nur service_id-Dimension, leere Zellen = fill).
  - `analytics/engine/analytics_repository.py`: neue `_registry_service_mode_pairs()` (liefert `{plugin_id_lower}::{mode}`), `_registry_source_modes` darauf refactored; `get_generic_heatmap` reicht `extra_service_modes` durch NUR bei `service_mode` in ("", "all", "alle").
  - `analytics/engine/analytics_view_model.py`: `resolve_service_label` parst `::`-Suffix, haengt `' / {Modus}'` nur bei nicht-leerem Modus an (auch im Exception-Fallback).
  - Verifiziert: `test/check_bugfix_2132.py` (8 PASS: 3 Achsenpunkte, grid leerer Suffix, 4 Matrix-Spalten, Modus-Filter begrenzt auf 1), `test/check_bugfix_2132_label.py` (5 PASS).
- **Verifikation (headless, keine UI):**
  - `py_compile` aller 4 geaenderten Quelldateien + Testdatei OK.
  - `test/check_mode_filter_db.py` (25 Checks, inkl. 3 neuer Registry-Payload-Checks), `test/check_bugfix_2132.py` (8), `test/check_bugfix_2132_label.py` (5), `test/check_bugfix_2132_layout.py`, `test/check_mode_filter_worker.py` (6), `test/check_mode_filter_vm.py` (11), `test/check_mode_filter_widget.py` (10) - ALLE PASS.
  - `test/check_mode_filter_db.py`: Payload-Erwartung von exakt auf "enthaelt" umgestellt (Bugfix 2 liefert zusaetzlich Registry-Modi der realen Plugins).
  - Temporaere Patch-Skripte (`test/_fix_bug*.py`) nach Verifikation geloescht.
- **Commit:** ce534c5
# Implementierungs-Log 21.03.20 - Bugfixing Runde 2: Layout / Modus-Parameter / Achsen / OSError (13.08.2026)

- **Bug 1 (Layout, Werteanzeige ueber dem Feld-Dropdown):** `analytics/ui/heatmap_widget.py` - `ctrl2` ist jetzt ein 2-zeiliges QGridLayout: Zeile 0 traegt `_label_info` EINE ZEILE UEBER der Steuerleiste, linksbuendig in derselben Spalte wie `_combo_field` (Spalte des 'Feld:'-Labels). `_combo_field` (Stretch 1) waechst weiterhin bis zum Canvas-Ende.
- **Bug 2 (Layout, Dropdown-Tausch):** Modus-Dropdown (`_combo_mode_filter`) steht jetzt VOR der Aggregation (`_combo_agg`). Verifiziert: `test/check_bugfix_2132_layout.py` (8 PASS, Grid-Semantik: info=(0,12) field=(1,12) gleiche Spalte, mode=(1,8) agg=(1,10)).
- **Bug 3 (Modus-spezifische Ergebnis-Parameter im Feld-Dropdown):**
  - `analytics/engine/feature_store_reader.py`: `_feature_meta_base` sammelt zusaetzlich `keys_by_service_mode` (JSON-Keys je (Service, source_mode), ROW-GENAU statt bucket-weit - bucket aggregiert ueber alle Modi); `feature_keys_by_service` erhaelt `service_mode`-Parameter und liefert nur die Keys der Rows mit diesem Modus (numeric_only weiter aktiv).
  - `analytics/engine/analytics_repository.py`: `_field_metadata` erhaelt `service_mode` + reicht ihn an `feature_keys_by_service` durch; bei gewaehltem, aber noch nicht berechnetem Modus (leere modus-gefilterte Keys) Fallback auf die nicht-technischen `output_schema`-Keys der selektierten Services (neuer Helper `_registry_output_keys`, Muster `_registry_service_mode_pairs`); `get_available_features` erhaelt `service_mode` und reicht ihn in die Feld-Metadaten.
  - `analytics/engine/analytics_worker.py`: QUERY_FEATURES reicht `service_mode` an `get_available_features`.
- **Bug 4 (MA_Slope_Change / 'Keine Daten vorhanden'):** Achsen-Labels (`resolve_service_label` inkl. ' / {Modus}') werden in `_render_generic` jetzt VOR dem Leer-Check konfiguriert - Beschriftung + Achseneintrag aktualisieren sich auch bei leerer Matrix (vorher blieb der alte Zustand stehen). 'Keine Daten'-Meldung nennt den gewaehlten Modus ('Keine Daten fuer Modus 'X''). DB-Abgleich (read-only): `source_mode LIKE %MA_Slope_Change%` = 0 Zeilen im gesamten Store - das Dropdown zeigt Registry-Modi (alle moeglichen), obwohl tatsaechlich nur MA_Peak_Hysteresis (hash 489c5ece) berechnet wurde. Die 'Keine Daten'-Meldung ist fachlich korrekt; die Ursache liegt in der Ausfuehrung/Persistenz des Modus, nicht in der Anzeige.
- **Bug 5 (OSError 22 beim Mausfahren):** `_lwc_date_ticks` clampt `lo`/`hi` auf >= 0 (Date-Epochs sind Wanduhr-Sekunden seit 1970; negative Werte aus dem zusammengefallenen Auto-Range nach 'Keine Daten' [-0.5, 0.5] wuerden `fromtimestamp(-86400)` ausloesen); `_date_marks` umschliesst `datetime.fromtimestamp` mit `(OSError, ValueError, OverflowError)` und ueberspringt ungueltige Marken; `_update_cell_info` faengt zusaetzlich `OSError` ab.
- **Verifikation (headless, keine UI):**
  - `py_compile` aller 4 geaenderten Quelldateien OK.
  - `test/check_bugfix_2132b.py` (17 Checks): keys_by_service_mode row-genau (Peak/Slope getrennt), feature_keys_by_service mit service_mode (numeric_only), _field_metadata modus-gefiltert, output_schema-Fallback fuer unbekannten Modus, get_available_features-Durchreichung, _date_marks ohne OSError bei negativen Epochs - ALLE PASS.
  - `test/check_bugfix_2132_layout.py` (8 Checks, umgestellt auf QGridLayout-Semantik), `test/check_bugfix_2132.py` (8), `test/check_bugfix_2132_label.py` (5), `test/check_mode_filter_db.py` (25), `test/check_mode_filter_worker.py` (6), `test/check_mode_filter_vm.py` (11), `test/check_mode_filter_widget.py` (10) - ALLE PASS.
- **Commit:** f71690f
