# Target Architecture & ML-Pipeline Roadmap

> **PyTrader ist eine entkoppelte, hochperformante quantitative Trading-Plattform, die Marktdaten lückenlos in einem kausalen Feature Store aggregiert, um über KI-gestützte Analytics und Machine Learning statistisch erforschte Vorteile in echtzeitfähige Live-Indikatoren und Handelsentscheidungen zu übersetzen.**

---

## 1. Data Foundation & Market Sync (MT5 & DuckDB)
* **High-Speed Ingestion:** Der `DataSyncWorker` liest tickgenaue OHLCV- und Volumendaten aus MetaTrader 5 und synchronisiert diese redundant in `market_data.duckdb`[cite: 1, 2].
* **Strict Time Alignment:** Alle Zeitstempel werden als DST-robuste Berlin-Wanduhr-Epochs gespeichert, um Zeitzonen-Offsets und Lücken auf den Chart-Timeframes zu eliminieren[cite: 1, 2].
* **Thread-Safe Pooling:** Sämtliche Datenbank-Zugriffe erfolgen sperrfrei über den Thread-local `DbPool` (eine Connection pro Thread und DB-Datei)[cite: 1, 2].

---

## 2. Feature Store & Causal Service Layer (`srv_...`)
* **Grouped Backend Services:** Konsolidierte, zustandlose Berechnungs-Engines (`srv_swing_structure`, `srv_swing_momentum`, `srv_swing_volume_profile`) verarbeiten die Marktdaten batchweise über den `HistoricalScanner`[cite: 1, 2].
* **No Look-ahead Bias:** Strikte Trennung von Ereignis-Zeitpunkt (`event_bar_time`) und mathematischem Bestätigungs-Zeitpunkt (`confirmation_bar_time`) garantiert kausale, repainting-freie Trainingsdaten[cite: 1].
* **Hybrid Feature Store:** Speicherung strukturierter Ergebnisse (Pivots, POC/VAH/VAL, LVNs, VWAP, Grid) im 4-spaltigen Primary-Key-Schema `(symbol, timeframe, bar_time, feature_id)` der `analytics.duckdb`[cite: 1, 2].
* **PineScript-Zone & UI-Exposure:** Parameter-Schemata sind am Dateianfang klassenlokal definiert und exposen Enums als dynamische `QComboBox`-Dropdowns im Frontend[cite: 1, 2].

---

## 3. Natural Language AI Orchestrator & Analytics UI
* **ViewModel-Decoupling:** Eine KI-Promptbox übersetzt natürliche Sprachfragen via Function Calling / Tool Use in strukturierte JSON-Aufrufe an das `AnalyticsViewModel`[cite: 1, 2].
* **Zero-GUI-Freeze:** Die KI steuert rein die ViewModel-Parameter (`set_symbol`, `set_feature_ids`); der `AnalyticsAsyncWorker` berechnet Heatmaps, Scatterplots und Verteilungen asynchron im Hintergrund[cite: 1, 2].
* **Interactive Exploration:** Das AnalyticsWindow bietet klickbare Charthoppings (`open_chart_at_bar`) und explicit verwalbare Analyse-Profile (`analytics_profiles`)[cite: 1, 2].

---

## 4. Scenario Backtesting & Simulation Engine
* **Multivariate Entry-Testing:** Ausführung vektorisierter Simulatoren über M5/M1-Hierarchien zur Evaluierung komplexer Einstiegs-Trigger (z. B. M1-Breakout-Limit nach M5-Swing-Signal).
* **Quantified Risk Management:** Automatische Verrechnung vordefinierter SL/TP-Modelle, Hysterese-Trailings, Kommissionen und Slippage.
* **Deterministic Results:** Rückgabe standardisierter Performancemetriken (Profit Factor, Winrate, Max Drawdown) direkt an die KI-Promptbox und Analytics-UI.

---

## 5. ML-Training & Feature Engineering (XGBoost / LightGBM)
* **Unbiased Datasets:** Generierung historischer Trainings-Matrixen aus den exakten `confirmation_lag_bars` und Stärkewerten (`strength_value`, `strength_type`) des Feature Stores[cite: 1].
* **Pattern Recognition:** Supervised Learning erkennt multivariate Muster und stochastische Kanten ($P(\text{Win}) > \text{Threshold}$), ohne durch optische Täuschungen menschlicher Chartanalyse zu verzerren.
* **Compact Model Export:** Export der validierten Machine-Learning-Gewichte als hochoptimierte ONNX-Dateien oder speichereffiziente Inferenz-Arrays.

---

## 6. Live Execution & Visual Frontend (`ind_...`)
* **Schlanke Live-Indikatoren:** Zweckgebundene Chart-Indikatoren (`ind_...`) verzichten im Live-Betrieb auf schwere Historien-Scans und lesen ausschließlich die vorberechneten ML-Inferenz-Ergebnisse[cite: 1, 2].
* **Zero-Repainting Guarantee:** Da ML-Modelle rein auf kausal bestätigten Feature-Daten trainieren, zeichnen Live-Indikatoren finale, unveränderliche Signale auf den Canvas[cite: 1].
* **MasterTree & Set Integration:** Nahtlose Verwaltung aller Services und Sets in einer 2-Root-Hierarchie (`📁 Sets`, `📦 Services`) mit Einlick in den Live-Chart-Status (`🟢 aktiv`) und das Datum der letzten Ausführung[cite: 1, 2].