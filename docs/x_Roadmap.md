# Implementierungs-Roadmap: PyTrader Signal- & ML-Engine

## Phase 1: Datenbankschema & Ordnerstruktur
**Ziel:** Die infrastrukturelle Grundlage schaffen.
* [ ] Erstellen der neuen Ordnerstruktur (`../analytics`, `../analytics/engine`, `../analytics/features`, `../analytics/signals`, `../analytics/background_workers`).
* [ ] Erstellen/Initialisieren der `analytics.duckdb`[cite: 3].
* [ ] Anlegen der SQL-Tabellen[cite: 3]:
  * `feature_store`[cite: 3]
  * `signal_definitions`[cite: 3]
  * `signal_sets`[cite: 3]
  * `signal_results`[cite: 3]

---

## Phase 2: Feature Store Builder
**Ziel:** Vektorisierte Merkmalsextraktion aus OHLCV-Rohdaten in `market_data.duckdb`[cite: 3].
* [ ] Implementierung der Basisklasse für Features.
* [ ] Erstellung erster Standard-Features (z. B. EMA-Steigungen, ATR-Normierung, RSI, Swing Highs/Lows).
* [ ] Aufbau des `feature_builder.py`: Liest OHLCV aus `market_data.duckdb`, berechnet Features vektorisiert (via Pandas/Numpy) und schreibt sie per Bulk-Insert in `analytics.duckdb` (`feature_store`)[cite: 3].

---
docs ordner
## Phase 2.1: Multi-Dimensionale Feature Store Erweiterung (Grid, Levels & Kontext)

Ziel: Erweiterung des feature_builder.py zur vektorisierten Berechnung und Speicherung multidimensionaler Markt-Merkmale (Y-Achse / Price Levels, X-Achse / Zeit-Sessions, Markt-Regimes und Cross-Symbol-Kontext) direkt auf der bar_time-Zeitachse im feature_store.

### 1. Dimensionen-Architektur im feature_store

Neben klassischen Indikator-Features (EMA, ATR) berechnet der FeatureBuilder nun vier spezialisierte Merkmal-Kategorien, die als Spalten in analytics.duckdb (feature_store) abgelegt werden:

    Y-Achsen Level-Features (Preis & Zonen):
    * Grid-Raster-Levels (grid_nearest_level, grid_dist_abs).
    * Pivot Highs/Lows, Liquidity Pool Zonen.
    * Perioden-Ankerpunkte (Session / Daily / Weekly High, Low, POC, VAH, VAL).

    X-Achsen & Zeit-Features (Sessions & Zonen):
    * Session-Klassifizierung (session_type: Asia, London, NY Overlap).
    * Tageszeit-Indikatoren (tod_minute: 0–1439 Mins).
    * Zeitfenster-Flags (is_time_window_active: Volle/Halbe Stunde Filter).

    Markt-Regime-Features (Phasen-Score):
    * Trend- vs. Range-Identifikation (regime_trend_score).
    * Volatilitäts-Expansions-Klassifizierung (regime_volatility).

    Cross-Symbol & Multi-Timeframe-Features:
    * Zeitreihengenaue Joins paralleler Symbole (z. B. gold_m1_close, gold_m1_diff auf SILVER M1).
    * Übergeordnete Trend-Biases (z. B. h4_ema_trend, d1_bias).

### 2. Datenfluss & Entkopplung (Features vs. Overlay vs. Signal)

 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ 1. BERECHNUNG & STORE (analytics/features/definitions/)                    │
 │    FeatureBuilder berechnet Y/X-Level, Regimes & Cross-Data vektorisiert    │
 │    und speichert sie als Spalten in analytics.duckdb (feature_store).        │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │
             ┌──────────────────────────┴──────────────────────────┐
             ▼                                                     ▼
 ┌───────────────────────────────────────┐   ┌─────────────────────────────────┐
 │ 2. DYNAMISCHES OVERLAY (Frontend)     │   │ 3. COMPOSITE SIGNALS (Engine)   │
 │    GridIndicator & Visual Plugins     │   │    CompositeSignals laden die   │
 │    berechnen/zeichnen Linien & Zonen │   │    Kontext-Matrix, evaluieren   │
 │    on-demand im Chart-Window.         │   │    Proximity/Touches & schreiben │
 └───────────────────────────────────────┘   │    in signal_results.           │
                                             └─────────────────────────────────┘
### Aufgaben-Checkliste Phase 2.1

* [ ] Erweiterung der Feature-Basisklasse (analytics/features/base_feature.py):
* Unterstützung für Multi-Spalten-Rückgaben (DataFrames) aus einzelnen Feature-Modulen.
* [ ] Implementierung von Level-Features (analytics/features/definitions/grid_levels.py):
* Vektorisiertes Berechnen von nächstgelegenen Grid-Levels, Abständen und zeitlichen Fenster-Flags (is_time_window_active).
* [ ] Implementierung von Zeit- & Session-Features (analytics/features/definitions/time_context.py):
* Extraktion von Handels-Sessions (Asia/London/NY) und Time-of-Day-Minuten aus TIMESTAMPTZ.
* [ ] Implementierung von Cross-Symbol-Joins im FeatureBuilder (analytics/features/feature_builder.py):
* Vektorisiertes Mergen von Datenreihen anderer Symbole/Timeframes auf exakte bar_time-Timestamps.
* [ ] Anpassung der Bulk-Upsert-Logik (feature_builder.py):
* Erweiterung der dynamischen SQL-Generierung (INSERT INTO feature_store) für erweiterte Schema-Spalten.
* [ ] Integrationstest für multidimensionale Feature-Stores (test.py / test_core_logic.py):
* Validierung der korrekten Berechnung von Grid-Abständen, Zeit-Flags und Cross-Symbol-Zuordnungen.

---

## Phase 3: Signal Engine & Erste Regel-Signale (Heuristiken)
**Ziel:** Ein klares, einheitliches Interface für alle Signale definieren, gewichtete Signal-Sets unterstützen und erste Regeln auf Basis von EMA und ATR testen (ohne ML)[cite: 3].

### Getroffene Architekturentscheidungen
1. **Signal-Rückgabe (Option A):** Die `SignalDefinition` liefert primär schlanke Zeitreihen mit einem `confidence`-Score ($0.0$ bis $1.0$)[cite: 3]. Zusätzliche Preisdaten (High/Low/Close) werden bei Bedarf direkt aus der DuckDB nachgeladen[cite: 3].
2. **Kombinationslogik (`WEIGHTED`):** Der `set_evaluator.py` nutzt gewichtete Summen zur Auswertung von Signal-Sets (inkl. Schwellenwert/Threshold)[cite: 3]. Damit lassen sich klassische `AND`/`OR`-Bedingungen abbilden und spätere ML-Wahrscheinlichkeiten nahtlos integrieren[cite: 3].
3. **Erste Test-Signale:** Umsetzung von `ema_trend.py` (Trendrichtung/Steigung) und `atr_filter.py` (Volatilität/Abstand) als Referenz-Implementierungen.

### Aufgaben-Checkliste
* [ ] **Implementierung der Basisklasse (`../analytics/engine/base_definition.py`):**
  * Abstrakte Klasse `SignalDefinition` definieren (`signal_id`, `version`, `params`)[cite: 3].
  * Abstrakte Methode `evaluate(df_features)` erzwingen, die eine Pandas Series/DataFrame mit `confidence`-Scores zurückgibt[cite: 3].
* [ ] **Erstellung der ersten Regel-Signale:**
  * `../analytics/signals/heuristics/ema_trend.py`: Nimmt `ema_20`, `ema_50` oder `ema_slope` aus dem Feature Store und bewertet die Trendstärke[cite: 3].
  * `../analytics/signals/heuristics/atr_filter.py`: Evaluierte `atr_norm` zur Bestimmung relevanter Volatilitäts- bzw. Ausbruchszustände[cite: 3].
* [ ] **Aufbau des Set-Evaluators (`../analytics/engine/set_evaluator.py`):**
  * Einlesen von JSON-Konfigurationen für `signal_sets`[cite: 3].
  * Berechnung des gewichteten Gesamt-Scores pro Bar:
    $$\text{Score}_{\text{gesamt}} = \sum (\text{confidence}_i \times \text{weight}_i)$$
  * Evaluierung gegen den definierten Schwellenwert (`threshold`)[cite: 3].
* [ ] **Stand-Alone Integrationstest (`test_signal_engine.py`):**
  * Laden der vorberechneten Merkmale aus `feature_store`[cite: 3].
  * Ausführen des `set_evaluator.py` mit einem Test-Set aus EMA + ATR[cite: 3].
  * Überprüfung der korrekten Score-Berechnung in der Konsole.

---

## Phase 4: Historischer Scanner & Chart-Overlay
**Ziel:** Das System End-to-End über historische Daten im Chart sichtbar machen. Die Steuerung erfolgt entkoppelt über ein Service-Kontrollfenster, während das Rendering über einen dynamischen Signal-Button im Chart gestartet wird[cite: 3].

### Getroffene Architekturentscheidungen
1. **Service-Steuerung (Main Window):** 
   * Ein "Service"-Button im Hauptfenster öffnet das Service-Fenster (`service_window.ui`).
   * **Symbol-Auswahl:** Dropdown-Auswahl für Symbole (aktuell `SILVER` und `GOLD`).
   * **Timeframe-Strategie:** Ein Scan verarbeitet immer automatisch *alle* verfügbaren Timeframes für das gewählte Symbol.
   * **Scan-Modus (Checkbox "New Scan"):**
     * **Aktiviert (`Checked`):** Löscht bestehende Signale für das Symbol/TF in `signal_results` komplett und führt einen vollständigen Re-Scan über die gesamte Historie durch.
     * **Deaktiviert (`Unchecked` / Update-Modus):** Prüft die Zeitstempel vorhandener Signale und scannt nur den fehlenden Zeitraum ab dem letzten Signalstempel bis zur neuesten verfügbaren Kerze in `market_data.duckdb`.
   * **Performance-Anzeige:** Echtzeit-Zeitmessung (Laufzeit-Timer / *Elapsed Time*) während des Scans.
2. **Chart-Integration ("Signale"-Button):** 
   * Ein "Signale"-Button im Chart-Fenster (`chart_window.ui`) öffnet einen Auswahl-Dialog/Dropdown.
   * Der User kann gezielt auswählen, *welches* konfigurierte `signal_set_id` im aktuellen Chart gerendert werden soll (ideal zum Vergleichen und Testen neuer Signale).
3. **Chart-Rendering (Phase 4):**
   * **Initial-Phase (Option A):** Verwendung der nativen Standard-Marker von Lightweight Charts (z. B. Pfeile/Shapes oben und unten an der Kerze) über die JavaScript-Bridge.
   * **Ausblick (Zukunft):** Vorbereitung der Architektur darauf, später benutzerspezifische Visualisierungen (Custom Shapes, Zonen, Boxen) außerhalb der Standard-Chart-Objekte pro Signal-Typ zu unterstützen.
4. **Qt Designer Integration:** Alle Fenster und Dialoge werden strikt als `.ui`-Dateien erstellt und dynamisch über PySide6 geladen[cite: 3].

### Aufgaben-Checkliste

* [ ] **Erstellung des Service-Kontrollfensters (`ui/service_window.ui` & `../service_win.py`):**
  * QComboBox für Symbol (`SILVER`, `GOLD`).
  * QCheckBox ("New Scan").
  * QLabel für die Laufzeitanzeige (*Elapsed Time*) & QProgressBar.
  * Anbindung des "Service"-Buttons im `main_window.ui`.

* [ ] **Implementierung des Background-Scanners (`../analytics/background_workers/historical_scanner.py`):**
  * `QThread`-Worker mit Stoppuhr-Timer[cite: 3].
  * Logik für **Delete & Re-Scan** vs. **Delta-Update** (Zeitstempel-Abgleich zwischen `ohlcv_bars` und `signal_results`).
  * Schleife über alle Timeframes für das ausgewählte Symbol.
  * Ausführung von `feature_builder` und `set_evaluator`[cite: 3].
  * Schreiben in `signal_results` (`analytics.duckdb`)[cite: 3].

* [ ] **Erweiterung des Chart-Fensters (`ui/chart_window.ui` & `chart_win.py`):**
  * Hinzufügen des "Signale"-Buttons in die Chart-UI.
  * Öffnen eines Auswahl-Dialogs zur Selektion des gewünschten `signal_set_id`.

* [ ] **Implementierung des Signal-Indikators (`ui/chart/overlays/signal_overlay.py`):**
  * Liest gefiltert aus `signal_results` für Symbol, Timeframe & gewähltes `set_id`[cite: 3].
  * Übergabe der Daten als Standard-Marker an Lightweight Charts.

* [ ] **End-to-End Integrationstest:**
  1. Testlauf Update-Scan vs. Full-Scan für `SILVER` (Zeitmessung prüfen).
  2. Chart für `SILVER` öffnen -> Klick auf "Signale" -> Signal-Set auswählen -> Marker im Chart prüfen.

---

## Phase 5: Statistikfenster & SQL-Auswertung
**Ziel:** Schaffung einer entkoppelten, nicht-modalen Analyse-Umgebung zur Auswertung historischer Signal-Treffer, Forward-Performances und Signal-Verteilungen über direkte DuckDB-SQL-Abfragen[cite: 3].

### Getroffene Architekturentscheidungen
1. **Fenster-Architektur (Nicht-Modales QMainWindow):** 
   * Aufruf über den neuen Button **"Statistik"** (Icon: 📊) im Hauptfenster (`main_window.ui`).
   * Das Fenster läuft völlig unabhängig vom Chart-Betrieb (nicht-modal), um den aktiven Trading-Workflow nicht zu blockieren und die freie Platzierung auf mehreren Monitoren zu ermöglichen.
2. **Entwicklungs-Fokus (Interface & Exemplarische Analyse):**
   * **Stufe 1 (Interface):** Aufbau des vollständigen UI-Layouts inklusive dynamischer Filterung und Auswertungs-Karten.
   * **Stufe 2 (Exemplarische Forward-Analyse):** Implementierung einer ersten Beispiel-Auswertung, die für jedes Signal prüft, wie sich der Kurs $N$ Kerzen in die Zukunft (aus `market_data.duckdb`) entwickelt hat (z.B. Erreichen eines $1.5 \times \text{ATR}$-Ziels).
3. **Interaktivität ("Jump-to-Bar"):** Ein Doppelklick auf eine Signal-Zeile in der Statistik-Tabelle fokussiert oder öffnet das entsprechende Chart-Fenster exakt an der Position des gewählten Zeitstempels (`bar_time`).
4. **Qt Designer Integration:** Das Fenster-Layout wird strikt als `.ui`-Datei (`statistics_window.ui`) angelegt und dynamisch geladen[cite: 3].

### Aufgaben-Checkliste

* [ ] **Erstellung des UI-Layouts (`ui/statistics_window.ui` & `ui/statistics_window.py`):**
  * **Filter-Header:**
    * `QComboBox` für Symbol-Filter (`SILVER`, `GOLD`, `ALLE`).
    * `QComboBox` für Timeframe-Filter (`H1`, `M5`, `ALLE`).
    * `QComboBox` für `source_id` (Auswahl des Signal-Sets).
  * **Summary Cards (Kennzahlen-Karten):**
    * Quick-Stats: *Gesamtzahl Signale*, *Ø Confidence*, *Trefferquote (Win-Rate %)*, *Bester Timeframe*.
  * **Detail-Tabelle (`QTableWidget`):**
    * Spalten: `Time`, `Symbol`, `Timeframe`, `Signal-Set`, `Confidence`, `Outcome (Win/Loss)`.
  * **Anbindung im Hauptfenster:** Hinzufügen des Buttons "Statistik" in `main_window.ui` und Verknüpfung mit der Instanziierung von `StatisticsWindow`.

* [ ] **Implementierung des Statistik-Repositorys (`../analytics/statistics_repository.py`):**
  * **Aggregations-Queries:** SQL-Abfragen auf `signal_results` in `analytics.duckdb` für Signalanordnungen, Häufigkeiten und Confidence-Mittelwerte[cite: 3].
  * **Exemplarische Forward-Performance-Engine:**
    * Verknüpfung von `signal_results` (`analytics.duckdb`) mit `ohlcv_bars` (`market_data.duckdb`) über `bar_time`[cite: 3].
    * Bestimmung der Kursveränderung nach $N$ Bars (z. B. $N=10$) zur Berechnung einer beispielhaften Erfolgsquote.

* [ ] **Implementierung der "Jump-to-Bar"-Schnittstelle:**
  * Event-Handler für `itemDoubleClicked` auf der Signal-Tabelle.
  * Senden eines Signals an das Hauptfenster, um das passende Chart (`PyTraderChartWindow`) auf das Symbol/TF umzustellen und zum exakten Timestamp zu scrollen (`visible_range`).

* [ ] **Integrationstest Phase 5:**
  1. Klick auf "Statistik" im Main-Window -> Nicht-modales Fenster öffnet sich parallel.
  2. Filter auf `SILVER` / `H1` setzen -> Tabelle und Summary-Karten aktualisieren sich ohne Verzögerung.
  3. Doppelklick auf einen Tabelleneintrag -> Chart-Fenster springt zur entsprechenden Kerze.

---

# Phase 6: Live-Erkennung, ML-Integration & Property-Steuerung

## 1. Übersicht & Zielsetzung
In Phase 6 wird das PyTrader-System um die **Live-Analyse bei Kerzenschluss (Bar-Close Event)** und die **Integration von ML-Inferenzmodellen (XGBoost / LightGBM)** erweitert. Zudem wird eine globale Eigenschafts-Steuerung über ein neues, nicht-modales **Properties-Fenster** geschaffen, deren Einstellungen konsistent über den erweiterten `StateManager` in der Tabelle `app_config` (`app_data.duckdb`) persistenziert werden.

Als Prototyp und Funktionstest dient ein dynamisches, experimentelles **Test-Signal (Alternierende Pfeile)** auf **SILVER (M1)**, um die gesamte Pipeline (Tick $\rightarrow$ Bar-Close $\rightarrow$ Feature Store $\rightarrow$ ML/Signal-Engine $\rightarrow$ Persistence $\rightarrow$ UI-Overlay) ohne Hardcoding auf Lauffähigkeit zu prüfen.


## 2. Architektonische Vorgaben & Festlegungen

### 2.1. Konsistente Property-Persistierung (`AppSettings` & `StateManager`)
1. **Kein Regelbruch / Keine Redundanz:** Anstatt ein neues Repository zu erfinden, wird der bestehende `StateManager` (`../state_manager.py`) als zentraler I/O-Verwalter für `app_data.duckdb` genutzt. Er wird um die Methoden `get_app_settings()` und `save_app_settings()` erweitert, die auf die bestehende Tabelle `app_config` zugreifen.
2. **Klassenmodell (`AbstractStateModel` & `AppSettings`):**
   * Erstellung der typsicheren Data-Class `AppSettings` (`../config/app_settings.py`), die von einer abstrakten Basisklasse `AbstractStateModel` erbt (implementiert `to_dict()` und `from_dict()`).
   * Bündelt globale Anwendungs-Defaults (z. B. `lookback_warmup_bars: int = 500`).
3. **Properties-Button & Nicht-modales Fenster (`PropertiesWindow`):**
   * Im Hauptfenster (`win_main`) wird ein Button "Properties" mit dem Icon `settings` (oder `gear`/`sliders`) integriert.
   * Das Fenster erbt von `PersistentWindow` (`win_properties`), öffnet sich nicht-modal (`show()`) und registriert sich über den `@register_persistent_window`-Dekorator in `persistent_window.py`.
   * Ändert der User Werte im Properties-Fenster, werden sie direkt über `StateManager.save_app_settings()` in `app_data.duckdb` geschrieben.
4. **Zwei-Ebenen-Hierarchie (App-Defaults vs. Chart-Instanz):**
   * `AppSettings.lookback_warmup_bars` dient als **globaler Standardwert** (Default = 500).
   * Jedes `PyTraderChartWindow` liest bei seiner Erstellung diesen Wert in eine eigene Instanz-Variable (`self.lookback_warmup_bars`) ein. Spätere chart-spezifische Optionensdialoge können diesen Instanzwert überschreiben.
   * Der `live_analyzer` Worker erhält seinen Lookback-Wert per **Dependency Injection** direkt aus der Instanz-Variable des aufrufenden Chart-Fensters.

### 2.2. Feature Store Persistierung (Option A: Sofort-Persistierung)
1. Sobald eine Live-Kerze schließt, berechnet der `live_analyzer` deren Features via `FeatureBuilder`.
2. Die Zeile wird **sofort** per `INSERT` in die Tabelle `feature_store` (`analytics.duckdb`) geschrieben.
3. **Latenz- & Duplikatsschutz:** Da unter Windows 11 / System-Events kurze Latenz-Spitzen auftreten können, wird die Datenbank-Integrität über ein Eindeutigkeits-Constraint geschützt:
   * Unique Key: `(symbol, timeframe, bar_time)`
   * Bei Time-Collision greift `INSERT OR REPLACE` bzw. `ON CONFLICT DO NOTHING`.
   *(Hinweis: Sollte sich der DB-I/O im Live-Betrieb künftig als Flaschenhals erweisen, kann die Evaluierung auf RAM-Only umgestellt werden).*

### 2.3. ML-Modell-Nomenklatur & ONNX-Perspektive
1. **Modell-Namenskonvention:** Modell-Dateien folgen strikt dem Schema:
   `model_<algo>_<symbol>_<timeframe>_<created_YYYYMMDD>_<updated_YYYYMMDD>.<ext>`
   * *Beispiel:* `model_lgb_SILVER_M1_20260730_20260730.json`
2. **Inferenz-Klassen:** 
   * `LightGBMSignal` und `XGBoostSignal` erben von `SignalDefinition` (`../analytics/signals/machine_learning`).
   * Die zu ladende Modell-Datei wird dynamisch über den `params`-Block im JSON-Signal-Set definiert.
3. **Zukunfts-Option (ONNX):** Für die Initialphase werden die nativen Python-APIs (`lightgbm` / `xgboost`) genutzt. Bei sehr großen Datenmengen oder extremen Taktzeiten kann die Inferenzklasse intern transparent auf `onnxruntime` umgestellt werden, ohne den Anwendungscode oder die Signal-Sets anzupassen.


## 3. Test-Signal (Experimental Signal) & Live-Ticker Anbindung

1. **Kein Hardcoding / Kein simples EMA-Cross:** Da einfache EMAs im M1-Chart zu wenige Signale generieren, wird ein experimentelles Test-Signal implementiert (`../analytics/signals/experimental/alternating_arrow_signal.py`).
2. **Signal-Logik:**
   * Erbt von `SignalDefinition`.
   * Bewertet die geschlossene Kerze im `live_analyzer` und liefert wechselnde Signale (`+1.0` für Buy/Pfeil oben, `-1.0` für Sell/Pfeil unten).
3. **Live-Ticker Kaskade bei Bar-Close:**
   * Der Live-Ticker / Feed erkennt das Bar-Close-Event der M1-Kerze auf `SILVER`.
   * Triggert den `live_analyzer` Worker-Thread.
   * `live_analyzer` $\rightarrow$ Berechnet Features $\rightarrow$ Schreibt in `feature_store` $\rightarrow$ Invoziert Signal-Engine/ML $\rightarrow$ Schreibt Resultat in `signal_results` (`context_type = 'live_stream'`) $\rightarrow$ Emittiert PyQt-Signal.
   * Das Chart-Overlay empfängt das Signal, liest den neuen Eintrag aus `analytics.duckdb` und rendert den neuen Pfeil über/unter der aktuellen Kerze.

## Phase 3.1: Signal-Aktualisierung & Betriebsmodi (`liveOp`)

**Ziel:** Erfassung und Aktualisierung von Signalen bei Lücken (Offline-Phasen, geschlossene Charts) sowie die strikte Trennung zwischen dynamisch zu aktualisierenden Live-Signalen und statischen Modellen für historische Untersuchungen.

### 1. Modell-Klassifizierung (`liveOp`)

Jede `SignalDefinition` erhält eine explizite Konfigurationseinstellung `live_op: bool` (Default = `True`), um das Verhalten bei der Signalverarbeitung festzulegen:

*   **`liveOp = True` (Dynamischer Live-Modus, z. B. `AlternatingArrowSignal`):**
    *   Signale werden kontinuierlich im Live-Betrieb verarbeitet und aktualisiert.
    *   Beim Öffnen oder Wechseln eines Symbol:Timeframe-Pärchens im Chartfenster wird das Signal für dieses Pärchen automatisch geprüft und auf den neuesten Stand gebracht.
*   **`liveOp = False` (Statischer Benchmark-Modus, z. B. `EMATrendSignal`):**
    *   Signale dienen ausschließlich als unveränderliche historische Datengrundlage für statistische Auswertungen und Backtests.
    *   Es erfolgt kein automatisches Tracking oder Update beim Aufruf im Chartfenster.

---

### 2. Aktualisierungs-Pfade (Automatik vs. Manuell)

Die Schließung von Datenlücken in `analytics.duckdb` erfolgt über zwei klar getrennte Pfade ohne die Notwendigkeit eines dauerhaften 24/7-Hintergrunddienstes:


                          ┌───────────────────────────────────────┐
                          │         Signal-Aktualisierung         │
                          └───────────────────┬───────────────────┘
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      ▼                                               ▼
             [ AUTOMATISCH ]                                     [ MANUELL ]
    (Chart-Aufruf mit liveOp = True)                    (ServiceWindow / Service-Call)
                      │                                               │
 - Reagiert auf aktives Chartfenster.            - Manueller Trigger im Service-Fenster.
 - Aktualisiert gewähltes Symbol/TF-Pärchen.     - Verarbeitet beliebige Symbol/TF-Pärchen
 - Ausgeführt über den LiveAnalyzer.              unabhängig von geöffneten Charts.
 
 
 3. **Automatisch (Chart-Trigger):**
   * Sobald ein Chart für ein Symbol:Timeframe-Pärchen geöffnet wird, prüft das System, ob aktive Signal-Sets den Modus `liveOp = True` besitzen.
   * Fehlende Signale seit dem letzten DB-Zeitstempel werden direkt für dieses Pärchen neu berechnet und nachgeführt.
4. **Manuell (Service-Trigger):**
   * Über das `ServiceWindow` (`../service_win.py`) und den `HistoricalScanner` können beliebige Datenreihen manuell aktualisiert werden – sowohl für inaktive Charts als auch für Modelle mit `liveOp = False`.
5. **Optionaler Background-Service (Zukunfts-Option):**
   * Ein vollautomatischer 24/7-Background-Service für geschlossene Charts kann zu einem späteren Zeitpunkt als eigener Worker nachgerüstet werden, nutzt aber dieselbe Schnittstelle wie der manuelle Service-Trigger.


### Aufgaben-Checkliste Phase 3.1

6. **Erweiterung der Signal-Basisklasse (`../analytics/engine/base_definition.py`):**
   * Hinzufügen des Property `live_op: bool` zur Klasse `SignalDefinition`.
7. **Anpassung der Live-Engine (`../analytics/background_workers/live_analyzer.py`):**
   * Filtern der zu evaluierenden Signale vor der Ausführung: Nur Signale mit `live_op == True` werden im Live-Pipeline-Durchlauf verarbeitet.
8. **Chart-Trigger-Integration (`../chart/chart_win.py`):**
   * Beim Wechsel von Symbol oder Timeframe automatischen Update-Check anstoßen, sofern für das Pärchen `liveOp = True` gesetzt ist.


## 4. Aufgaben-Checkliste für die IDE AI

* [ ] **1. Settings-Klassenstruktur & StateManager-Erweiterung:**
  * Erstellung von `../config/base_state_model.py` (`AbstractStateModel` ABC).
  * Erstellung von `../config/app_settings.py` (`AppSettings` Data-Class erbt von `AbstractStateModel`, `lookback_warmup_bars: int = 500`).
  * Erweiterung von `../state_manager.py` um `get_app_settings()` und `save_app_settings()` (nutzt die bestehende Tabelle `app_config` in `app_data.duckdb`).

* [ ] **2. UI & Properties-Steuerung:**
  * Erstellung / Anpassung von `ui/properties_win.ui` und `properties_window.py` (erbt von `PersistentWindow`).
  * Hinzufügen des Dekorators `@register_persistent_window` zur Klasse `PropertiesWindow`.
  * Integration des "Properties"-Buttons mit Icon (`settings`) im Hauptfenster `win_main`.
  * Einbau der Interaktion: SpinBox für `lookback_warmup_bars` liest über `state_manager.get_app_settings()` und speichert Änderungen direkt über `state_manager.save_app_settings()`.

* [ ] **3. Integration in `PyTraderChartWindow`:**
  * Liest bei Initialisierung `app_settings.lookback_warmup_bars` in die Instanz-Variable `self.lookback_warmup_bars`.
  * Injiziert `self.lookback_warmup_bars` über den Konstruktor an den `live_analyzer` Worker.

* [ ] **4. Experimental Signal (`../analytics/signals/experimental/alternating_arrow_signal.py`):**
  * Erstellung der Klasse `AlternatingArrowSignal` (erbt von `SignalDefinition`).
  * Implementierung der `evaluate()`-Methode mit deterministisch alternierendem Status basierend auf dem `bar_time`-Index oder State.

* [ ] **5. ML Inferenz-Klassen (`../analytics/signals/machine_learning`):**
  * Erstellung von `lightgbm_signal.py` und `xgboost_signal.py` (erben von `SignalDefinition`).
  * Dynamisches Laden der Modell-Datei aus `params['model_file']` unter Beachtung der neuen Datums-Nomenklatur.

* [ ] **6. Worker-Thread `live_analyzer.py` (`../analytics/background_workers`):**
  * Empfängt `lookback_warmup_bars` im Konstruktor.
  * Bar-Close Event Handling für `SILVER` `M1`.
  * Feature-Berechnung und sofortiger `INSERT OR REPLACE`-Write in `feature_store` (`analytics.duckdb`).
  * Signal-Evaluierung über die geladenen Signal-Sets (`SetEvaluator`).
  * Insert der Treffer in `signal_results` (`context_type = 'live_stream'`) und Auslösen des PyQt-Signals `new_live_signal_emitted`.

* [ ] **7. Live-Integration & Chart-Drawing Test:**
  * Anbindung des PyQt-Signals an das Chart-Overlay in `PyTraderChartWindow`.
  * Simulation/Durchlauf auf `SILVER M1`: Verifizieren, dass nach jedem Bar-Close vollautomatisch ein Pfeil über/unter der geschlossenen Kerze erscheint, ohne dass das UI einfriert.


## Phase 7: System- & Logic-Testing
**Ziel:** Absicherung der mathematischen Kernkomponenten, Indikator-Features und Datenbank-Mengenoperationen über token-schonende, isolierte Unit-Tests.

### Getroffene Architekturentscheidungen
1. **Pragmatische Testing-Strategie (Slim Core-Testing):**
   * Strikter Verzicht auf GUI- oder MT5-Live-Tests zur Minimierung der Prompt-Länge und des Token-Verbrauchs.
   * Konsolidierte, isolierte Unit-Tests ausschließlich für mathematische Kernkomponenten (`BaseFeature`, `SignalDefinition`, `SetEvaluator` und DuckDB-Queries) in schlanken Testskripten (`test_core_logic.py`).

### Aufgaben-Checkliste

* [ ] **Aufbau des mathematischen Core-Testings (`test_core_logic.py`):**
  * Unit-Tests für `FeatureBuilder`: Prüfen der Korrektheit vektorisierter Indikatorberechnungen (z. B. `ema_diff`, `atr_normalized`) auf festen synthetischen Arrays.
  * Unit-Tests für `SetEvaluator`: Evaluierung der gewichteten Score-Berechnung und Threshold-Schwellen.
  * Integrationstest für DuckDB-Mengenoperationen und Zeitstempel-Sortierungen (`signal_results` / `feature_store`).

---

## Phase 8: Erweiterte Statistik-Visualisierung (Signals & Zones)
**Ziel:** Erweiterung des Statistik-Moduls um visuelle Grafiken (Zeitzonen-Heatmaps & Parameter-Grid-Surfaces) zur reinen Signal- und Performance-Analyse (ohne finanzielle Equity-Bewertung)[cite: 3].

### Getroffene Architekturentscheidungen
1. **Visuelle Analyse-Modi (Statistik-Subtabs):**
   * Einbindung von Subtabs im `StatisticsWindow` (`../ui/statistic_win.ui`) für grafische Auswertungen über Highcharts/Chart.js (via `QWebEngineView`) oder Seaborn/Matplotlib-Rendition.
2. **Visualisierungs-Fokus (Pure Signal Stats):**
   * **Handelszeiten-Heatmap:** Signal-Trefferquote & Dichte-Matrix nach Wochentagen (Mo–Fr) $\times$ Tagesstunden (0–23 Uhr).
   * **Parameter-Grid-Surface:** 2D-Heatmap zur Evaluierung von Reihen-Tests / Grid-Search (Sichtbarmachung von Sweet-Spots & Vermeidung von Curve-Fitting).
   * *Hinweis:* Finanzielle Metriken (Kontostand, Drawdowns) sind explizit ausgeklammert und folgen in späteren Phasen.

### Aufgaben-Checkliste

* [ ] **Erweiterung des Statistik-Repositorys (`../analytics/statistics_repository.py`):**
  * SQL-Abfrage für Stunden-/Wochentags-Aggregationen (Tageszeit-Heatmap) auf `signal_results` in `analytics.duckdb`.
  * Aggregations-Query für Parameter-Grid-Matrizen aus Reihen-Tests (Grid-Search).

* [ ] **Erweiterung des Statistik-UI (`../ui/statistic_win.ui` & `statistic_window.py`):**
  * Integration von Subtabs (z. B. `Tab 1: Tabelle`, `Tab 2: Zeitzonen-Heatmap`, `Tab 3: Grid-Search Surface`).
  * Einbau eines `QWebEngineView`-Widgets zur Darstellung interaktiver HTML/JS-Grafiken (oder Rendering statischer Seaborn-Heatmaps).


## Phase 9: Automatisierte Reihen-Tests & Grid-Search Engine
**Ziel:** Vollautomatische Evaluierung von Parameter-Bandbreiten (Grid-Search) über historische Daten, um optimale Parameter-Kombinationen sowie ideale Handelszeiten (Green/Red Zones) datengetrieben ohne manuelle Eingriffe zu ermitteln.

### Getroffene Architekturentscheidungen
1. **Parameter-Matrix (Grid-Search Schema):**
   * Übergabe von Parameter-Bandbreiten (Start, Ende, Schrittweite) in der JSON-Set-Konfiguration anstelle von Einzelwerten.
   * Der `historical_scanner` generiert aus der Matrix alle möglichen Parameter-Kombinationen.
2. **Vektorisierte Batch-Evaluierung (High Performance):**
   * Die mathematischen Features werden pro Symbol/TF **nur ein einziges Mal** aus dem `feature_store` geladen.
   * Der `set_evaluator` rechnet alle Parameter-Variationen im Arbeitsspeicher vektorisiert durch und schreibt die Ergebnisse mit variierten `source_id`-Kennungen (oder spezifischer `run_id`) in `signal_results` (`analytics.duckdb`).
3. **Automatisierte Zonen-Generierung:**
   * Nach Abschluss eines Reihen-Tests analysiert eine SQL-Aggregationslogik die Trefferverteilung nach Wochentagen und Tagesstunden.
   * Erzeugung eines dynamischen Time-of-Day-Filters (Ausschluss von Red/Filter-Zones mit hoher Fehlsignal-Quote), der direkt als JSON-Regel in das optimierte Signal-Set zurückgespeichert werden kann.

### Aufgaben-Checkliste

* [ ] **Erweiterung des Historical Scanners (`../analytics/background_workers/historical_scanner.py`):**
  * Parser für Parameter-Grid-Konfigurationen (Erzeugung der Kombinations-Matrix via `itertools.product`).
  * Iterative Ausführung von `set_evaluator` über die geladenen Features.
  * Speicherung der Testreihen-Ergebnisse mit Zuordnung zur jeweiligen Testlauf-ID (`run_id`).

* [ ] **Erweiterung der Service-Steuerung (`ui/service_window.ui` & `service_window.py`):**
  * Checkbox / Umschalter für "Reihen-Test (Grid-Search)".
  * Eingabemaske oder JSON-Ladefunktion für Parameter-Bandbreiten.
  * Fortschrittsanzeige für die verarbeiteten Parameter-Kombinationen.

* [ ] **Implementierung der Zonen-Analyse Engine (`analytics/engine/zone_analyzer.py`):**
  * SQL-gestützte Auswertung der Reihen-Tests nach Win-Rate pro Stunde (0–23 Uhr) und Wochentag.
  * Automatische Extraktion signifikanter "Green Zones" (hohe Trefferquote) und "Red Zones" (Sperrzeiten).
  * Export-Funktion zur Aktualisierung der `active_time_windows` in der `signal_sets`-Tabelle.

* [ ] **Integrationstest Phase 9:**
  1. Start eines Reihen-Tests über `SILVER` / `H1` mit 20 Parameter-Variationen im Service-Fenster.
  2. Überprüfung der geschriebenen Signale in `signal_results`.
  3. Ausführung des Zonen-Analyzers und Generierung des optimierten Signal-Sets mit integriertem Zeitfenster-Filter.

## Phase 10: Signal- & Rule-Management Engine (Set-Editor & Ruling)
**Ziel:** Schaffung einer flexible Verknüpfungs- und Verwaltungslogik (Ruling) für Einzelsignale und komposite Signal-Sets über einen Hybrid-Ansatz aus Python-Regelmodulen und JSON-Regelschemata.

### Getroffene Architekturentscheidungen
1. **Hybrid-Ruling-Architektur:**
   * **Komplexe Bedingungslogik (`../analytics/signals/composite`):** Wenn-Dann-Abfragen, Prozent-Abweichungen, Multi-Bar-Rückblicke und Abhängigkeiten zwischen verschiedenen Indikatoren/Signalen werden sauber in entkoppelten Python-Klassen (erben von `SignalDefinition`) umgesetzt.
   * **Dynamische Parameter & Gewichtung (JSON):** Schwellenwerte, Signal-Gewichtungen (`WEIGHTED`), Richtungs-Filter und aktive Handelszeitfenster (`active_time_windows`) werden in JSON-Regelschemata in `analytics.duckdb` (`signal_sets`) gespeichert.
2. **Kombinations- & Auswertungs-Logik (`SetEvaluator`):**
   * Vektorisierte Auswertung aller im Set definierten Signale.
   * Berechnung des gewichteten Gesamt-Confidence-Scores pro Kerze.
   * Harte zeitliche Sperren (Red-Zone Filter) setzen den Confidence-Score außerhalb der erlaubten Zeitfenster automatisch auf `0.0`.
3. **Persistenz & Entkopplung:**
   * Das Ruling-System arbeitet vollständig entkoppelt vom Chart-Window. Modifikationen an Regeln oder Sets können über eine UI oder JSON-Dateien vorgenommen werden, ohne bestehende Kern-Systeme zu verändern (Open/Closed Principle).

---

### Aufgaben-Checkliste

* [ ] **Aufbau der Composite-Signal-Struktur (`../analytics/signals/composite`):**
  * Erstellung komplexer Regel-Klassen (z. B. `trend_pullback_rule.py`), die mehrere Features (z. B. `ema_diff`, `atr_normalized`, `close`) verknüpfen und logische Sequenzen über mehrere Kerzen auswerten.

* [ ] **Erweiterung des Set-Evaluators (`../analytics/engine/set_evaluator.py`):**
  * Einbau der Time-of-Day- und Wochentags-Sperrfilter (`active_time_windows`).
  * Unterstützung komplexer Regelverknüpfungen (z. B. Mindest-Confidence einzelner Teilsignale als Bedingung für das Gesamt-Set).

* [ ] **Erstellung des Signal-Set-Management-Repositorys (`analytics/rule_repository.py`):**
  * CRUD-Operationen (Erstellen, Lesen, Aktualisieren, Löschen) für `signal_definitions` und `signal_sets` in `analytics.duckdb`.
  * JSON-Validierung von Set-Konfigurationen beim Speichern.

* [ ] **Integrationstest Phase 10:**
  1. Erstellen eines komplexen Hybrid-Sets aus Python-Composite-Signal + Heuristiken mit JSON-Gewichtung.
  2. Ausführung der Evaluierung über `SetEvaluator` und Validierung der zeitlichen und logischen Sperrfilter.


## Phase 11: Refactoring Grid-Indikator & Multi-Dimensional Composite Signal

Ziel: Vollständige Transformation des bestehenden GridIndicator aus dem Prototypen-Status in das neue multidimensionale Architektur-Muster (Trennung in Feature-Berechnung, Frontend-Overlay und Composite-Signal).

### 1. Entkoppelte Grid-Architektur

    Feature Module (analytics/features/definitions/grid_levels.py):
        Berechnet Y-Achsen-Grid-Levels, Preisabstände und X-Achsen-Zeitfenster (is_time_window_active).
        Wird vom FeatureBuilder in den feature_store geschrieben.

    Chart Overlay (chart/indicators/grid.py):
        Verbleibt als leichtgewichtiges Rendering-Plugin für Lightweight Charts.
        Zeichnet Linien und Proximity-Circles weiterhin dynamisch on-demand auf dem Canvas.

    Composite Signal (analytics/signals/composite/grid_proximity_signal.py):
        Neues Signalmodell (erbt von SignalDefinition).
        Verknüpft Y-Abstand, X-Zeitfenster und Volatilitäts-Regime (atr_normalized) aus dem feature_store.
        Evaluiert Proximity-Touches und schreibt Ergebnisse mit Confidence-Score in signal_results.

Aufgaben-Checkliste Phase 11

    [ ] Erstellung des Grid-Level-Features (analytics/features/definitions/grid_levels.py):
        Vektorisierte Berechnung von Raster-Preisen und zeitlichen Aktivitäts-Flags.
        Einbindung in den FeatureBuilder (Phase 2.1).

    [ ] Refactoring des Chart-Indikators (chart/indicators/grid.py):
        Bereinigung der reinen Visualisierungslogik (Entkopplung von DB-Schreibzugriffen).
        Optimierte On-Demand-Vektor-Berechnung für das Front-End-Rendering.

    [ ] Implementierung des Signalmodells (analytics/signals/composite/grid_proximity_signal.py):
        Erstellung der Klasse GridProximitySignal (ABC SignalDefinition).
        Implementierung der evaluate()-Methode mit multi-dimensionaler Verknüpfung (Preis-Abstand + Zeitfenster + ATR-Regime).

    [ ] Integrationstest & Service-Scan:
        Durchlauf eines Scans im ServiceWindow über grid_proximity_v1.
        Auswertung der Trefferquote und Verteilung im StatisticWindow (statistic_win.py)