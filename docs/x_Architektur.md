# Architektur-Dokumentation: Einheitliche Signal- und ML-Engine für PyTrader

## 1. Executive Summary

Dieses Dokument beschreibt die Architektur-Richtlinien für die Erweiterung des PyTrader-Systems um Mustererkennung und Machine-Learning-gestützte Signalanalyse. Das Kernziel ist die Schaffung einer hochperformanten, entkoppelten Desktop-Architektur (Python/PySide6), die historische Analysen, Live-Marktüberwachung und Statistik-Auswertungen ohne redundante Code-Basis ermöglicht.

Der Lösungsansatz basiert auf einer **einheitlichen Signal-Engine** mit einem vorgeschalteten **Feature Store** und einer strikten **Trennung von Berechnung und Visualisierung** über DuckDB als Kommunikationsschicht.

---

## 2. Architektonische Grundprinzipien

### 2.1. Entkopplung von Berechnung und UI (Datenbank als Brücke)
Die UI (Chart-Ansicht, Statistik-Fenster) darf unter keinen Umständen blockiert werden. Daher berechnen Indikatoren im Chart keine eigenen Signale.
*   **Backend (Worker-Prozesse):** Analysieren historische Daten oder Live-Ticks und schreiben alle gefundenen Ereignisse (Patterns, Trends, ML-Signale) kontinuierlich in eine Analytics-Datenbank.
*   **Frontend (PySide6 / Lightweight Charts):** Die Chart-Overlays und Statistik-Widgets greifen ausschließlich *lesend (read-only)* auf diese Datenbank zu und visualisieren fertige Ergebnisse.

### 2.2. Einheitliche Signal-Engine (`SignalDefinition`)
Es gibt keine architektonische Trennung zwischen "klassischen Indikator-Regeln", "Chart-Mustern" oder "Machine Learning".
*   Alle Analyse-Methoden implementieren dieselbe abstrakte Basisklasse (`SignalDefinition`).
*   Für das System macht es keinen Unterschied, ob ein Signal durch einen gleitenden Durchschnitt (Heuristik) oder durch ein Gradient-Boosting-Modell (ML) generiert wird.
*   Signale können beliebig in **Signal-Sets** gebündelt und gewichtet werden.

### 2.3. Der Feature Store als Fundament
Um die Rechenlast im Desktop-Betrieb zu minimieren und das ML-Training zu optimieren, werden Rohdaten (OHLCV) vorab in strukturierte Features transformiert.
*   Die Feature-Extraktion (z. B. Momentum, Volatilität, Swing-Strukturen, gleitende Durchschnitte) erfolgt nur *einmal*.
*   Diese berechneten Merkmale werden dauerhaft im *Feature Store* gespeichert.
*   Sowohl deterministische Regeln als auch ML-Modelle greifen zur Evaluation ausschließlich auf den Feature Store zu, nicht auf rohe Kerzendaten.

### 2.4. Lokale Execution First
In der Initialphase werden alle Berechnungen lokal innerhalb der nativen Python-Desktop-Umgebung ausgeführt. Komplexe ML-Modelle werden über performante lokale Runtimes eingebunden. Ein ausgelagerter Microservice (z.B. FastAPI/Docker) wird nur bei zukünftigen Skalierungsanforderungen (z.B. massive GPU-Nutzung) in Betracht gezogen.

---

## 3. Datenbank-Architektur (DuckDB)

Die bestehende `market_data.duckdb` (für OHLCV-Rohdaten) wird um eine spezifische `analytics.duckdb` erweitert.

### Tabellen-Struktur (analytics.duckdb)

**1. `feature_store`** (Persistente Speicherung der vorberechneten Merkmale)
*   `symbol` (VARCHAR)
*   `timeframe` (VARCHAR)
*   `bar_time` (TIMESTAMPTZ)
*   `ema_diff` (DOUBLE), `rsi_14` (DOUBLE), `atr_normalized` (DOUBLE) ... (weitere Features)

**2. `signal_definitions`** (Metadaten zu allen verfügbaren Algorithmen)
*   `signal_id` (VARCHAR) - Primärschlüssel (z.B. 'trend_ema_cross_v1')
*   `category` (VARCHAR) - 'rule', 'pattern', 'ml'
*   `version` (VARCHAR)
*   `params` (JSON) - Standard-Parameter

**3. `signal_sets`** (Dynamische JSON-Konfiguration kombinierter Signale)
*   `set_id` (VARCHAR) - Primärschlüssel
*   `configuration` (JSON) - Enthält die IDs und Gewichtungen der Signale
*   `logic` (VARCHAR) - 'AND', 'OR', 'WEIGHTED'

**4. `signal_results`** (Zentrale Tabelle für alle erkannten Events – Historie & Live)
*   `event_id` (VARCHAR) - Primärschlüssel
*   `symbol` (VARCHAR)
*   `timeframe` (VARCHAR)
*   `bar_time` (TIMESTAMPTZ)
*   `source_id` (VARCHAR) - Verweis auf `signal_id` oder `set_id`
*   `confidence` (DOUBLE) - Wahrscheinlichkeit / Stärke des Signals
*   `context_type` (VARCHAR) - 'historical_batch' oder 'live_stream'
*   `metadata_payload` (JSON) - Zusätzliche Kontextdaten

---

## 4. Software-Struktur & Ordner-Layout

Das Projekt (PyTrader) sollte in eine klare Domain-Struktur unterteilt werden:

```text
PyTrader/
├── analytics/
│   ├── engine/                     # Kernlogik der Analyse
│   │   ├── signal_runtime.py       # Orchestrierung (Tick/Bar -> Features -> Signals -> DB)
│   │   ├── set_evaluator.py        # Kombinationslogik für Signal-Sets
│   │   └── base_definition.py      # Abstrakte Klasse SignalDefinition
│   ├── features/                   # Logik zur Generierung des Feature Stores
│   │   ├── feature_builder.py
│   │   └── definitions/            # (z.B. volatility.py, momentum.py, structure.py)
│   ├── signals/                    # Die konkreten Algorithmen (Implementierungen)
│   │   ├── heuristics/             # (z.B. ema_crossover.py)
│   │   ├── patterns/               # (z.B. pullback.py)
│   │   └── machine_learning/       # (Inferenz, z.B. xgboost_model.py)
│   └── background_workers/         # QThread Prozesse
│       ├── historical_scanner.py   # Batch-Verarbeitung über Historie
│       └── live_analyzer.py        # Polling/Event-Listener für neue Bars
├── ui/                             # PySide6 Frontend
│   ├── chart/                      
│   │   └── overlays/               # Indikatoren, die aus `signal_results` lesen
│   └── statistics/                 # Fenster für DuckDB SQL-Aggregationsabfragen
└── data/                           # Lokale DuckDB Dateien

## 5. Kernprozesse

### 5.1. Historischer Backtest & Scanner
1. Ein User triggert einen Scan für ein bestimmtes Signal-Set.
2. Der `historical_scanner` Worker lädt OHLCV-Daten.
3. Die `feature_builder` Logik berechnet fehlende Features und speichert sie im `feature_store`.
4. Die `signal_runtime` evaluiert alle Signale des Sets anhand der Features.
5. Ergebnisse werden via *Bulk-Insert* als 'historical_batch' in `signal_results` geschrieben.

### 5.2. Live-Erkennung
1. Neue Ticks aggregieren zu einer abgeschlossenen Kerze (Bar-Close).
2. Der `live_analyzer` Worker extrahiert nur für diese *neue* Kerze die Features.
3. Die Features werden an die aktive `signal_runtime` übergeben.
4. Identifizierte Signale werden in `signal_results` als 'live_stream' geschrieben.
5. Über einen PyQt-Signal-Slot-Mechanismus wird das Chart-Fenster benachrichtigt, die neuen Overlays aus der Datenbank zu laden.

---

## 6. Richtlinien für die KI-gestützte Weiterentwicklung

Wenn Sie diese Dokumentation nutzen, um mit verschiedenen KIs Teilkomponenten auszuarbeiten, beachten Sie folgende Anweisungen für den Prompt-Kontext:

*   **Keine Logik-Vermischung:** Weisen Sie die KI an, Logik für UI-Aktualisierungen strikt von der Signal-Evaluation zu trennen.
*   **Fokus auf DuckDB:** Fordern Sie effiziente vektorisierte Pandas/Numpy-Operationen, die gut mit DuckDB harmonieren.
*   **Abstrakte Vererbung:** Bestehen Sie darauf, dass neue Signale zwingend von der `SignalDefinition` Basisklasse erben müssen.
*   **Desktop-Kompatibilität:** Schließen Sie Lösungen aus, die komplexe verteilte Systeme (Kafka, Redis, Kubernetes) fordern, solange es sich um eine Desktop-Anwendung (Windows 11) handelt.

## 7. Goldene Regeln der Objektorientierung & System-Entkopplung (OOP Principles)

Jede Code-Generierung und Refactoring-Aufgabe durch KI-Assistenten muss strikt den folgenden objektorientierten Design-Prinzipien folgen:

1. **Abstraktion durch Abstrakte Basisklassen (ABC & Polymorphie):**
   * Keine isolierten Funktionen oder ad-hoc Klassen für Business-Logik.
   * Jede Kern-Komponente (z. B. Signale, Features, Fenster, Indikatoren) **muss** von ihrer jeweiligen abstrakten Basisklasse erben (`SignalDefinition`, `BaseFeature`, `PersistentWindow`, `BaseIndicator`).
   * Die aufrufende Engine interagiert **ausschließlich** mit dem abstrakten Interface, niemals mit konkreten Implementierungen[cite: 3].

2. **Vollständige Entkopplung & Inversion of Control (IoC):**
   * **Keine Zirkulären Abhängigkeiten:** Sub-Module (z. B. Worker oder Dialoge) dürfen niemal Kenntnis von konkreten Orchestratoren (wie `MainWindow`) haben.
   * **Kommunikation über Signals/Sockets & Repositories:** UI-Komponenten und Datenverarbeiter kommunizieren strikt asynchron über PyQt-Signals oder Read-Only-Datenbankabfragen[cite: 3].
   * Verboten: Hardcoded Klassennamen-Checks (z. B. `if name == "win_statistics"`) in zentralen Repositories. Fenstertypen müssen sich generisch/dynamisch über Dekoratoren oder Registrys registrieren.

3. **Single Responsibility Principle (SRP - Eine Aufgabe pro Klasse):**
   * **UI-Klassen (`PySide6`):** Verantwortlich *nur* für Event-Handling und Rendering[cite: 3]. Keine Berechnungen, Indikator-Logik oder direkte DB-Verbindungsaufbauten.
   * **Worker/Engine-Klassen:** Verantwortlich *nur* für Datenverarbeitung und mathematische Evaluierung[cite: 3]. Absolut kein UI-Import oder GUI-Code.
   * **Repository-Klassen:** Kapseln den Datenbank-Zugriff exklusiv (SQL-Abfragen, Connection-Handling)[cite: 3].

4. **Offen für Erweiterung, Geschlossen für Änderung (Open/Closed Principle):**
   * Neue Indikatoren, Strategien oder Fenster müssen durch **Hinzufügen neuer Dateien** implementiert werden können, ohne bestehende Kern-Dateien (`main.py`, `set_evaluator.py`, `feature_builder.py`) modifizieren zu müssen[cite: 3].

5. **Typsicherheit & Verlässliche Datenverträge:**
   * Strikte Nutzung von Python **Type Hints** (`typing`) für alle Funktionsparameter und Rückgabewerte.
   * Keine impliziten Dictionaries als Datenverträge zwischen Modulen; Datenströme nutzen definierte Dataframes, Primitive oder Typ-Aliase[cite: 3].