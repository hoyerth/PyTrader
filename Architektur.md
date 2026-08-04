# Architektur-Dokumentation: PyTrader System-Architektur

> **Single Point of Truth:** Dieses Dokument ist die verbindliche Architektur-Datei.
> Archiv-/Alt-Fassungen (`docs/Old/`) werden nicht mehr gepflegt. Detaillierte
> Modul- und Tabellen-Beschreibungen liegen direkt im Code (Modul-Docstrings,
> `db_service.py` als Schema-Source-of-Truth).

## 1. Executive Summary

Dieses Dokument beschreibt die verbindlichen Architektur-Richtlinien für das PyTrader-System. Das Kernziel ist die Bereitstellung einer hochperformanten, vollständig entkoppelten Desktop-Architektur (Python / PySide6 / DuckDB). Sie ermöglicht historische Massen-Scans, Echtzeit-Marktüberwachung (Live-Analyzer) und visuelle Chart-Analysen ohne redundante Code-Basis, Thread-Sperren oder UI-Blockaden.

Der Lösungsansatz basiert auf der **vollständigen Entkopplung von Berechnungs-Engines, Benutzeroberfläche und Speicher-Services** über DuckDB als zentrale, thread-sichere Kommunikationsschicht.

---

## 2. Architektonische Grundfesten

### 2.1. Entkopplung von Berechnung und UI (Datenbank als Brücke)

Die Benutzeroberfläche (Chart-Windows, Statistik-Fenster, Service-Fenster) darf unter keinen Umständen blockiert werden.

* **Backend (Background Worker Threads):** Hintergrund-Prozesse (`HistoricalScanner`, `LiveAnalyzer`) berechnen Daten und schreiben Ergebnisse asynchron in DuckDB.

* **Frontend (PySide6 / Lightweight Charts v5):** Chart-Overlays und Statistik-Widgets greifen *lesend* auf DuckDB zu oder empfangen typisierte Payloads (`ChartRenderPayload`) über die Ausführungsschicht, ohne Berechnungen auf dem GUI-Thread auszuführen.



```
 ┌─────────────────────────┐          ┌──────────────────────────┐
 │  PyTrader Chart-UI      │          │ Background Worker        │
 │  (PyTraderChartWindow)  │          │ (Scanner / LiveAnalyzer) │
 └────────────┬────────────┘          └────────────┬─────────────┘
              │                                    │
              │ read-only / Payloads               │ write (Bulk / Upsert)
              ▼                                    ▼
 ┌───────────────────────────────────────────────────────────────┐
 │                     DuckDB Data Layer                         │
 │ - market_data.duckdb : ohlcv_bars                             │
 │ - analytics.duckdb   : feature_store (Hybrid),                │
 │                       signal_results (Legacy)                 │
 │ - app_data.duckdb    : indicator_presets, service_sets,       │
 │                       window_instances                        │
 └───────────────────────────────────────────────────────────────┘

```

### 2.2. Plugin-Architektur (`PluginFeature` & `PluginExecutor`)

Berechnungs-Engines sind strikt zustandslos (*stateless*).

* **Zustandslosigkeit:** Jede Berechnung ist eine reine Funktion `calculate(df, params, context)`.
* **Einheitliches Interface:** Neue Features und Indikator-Engines erben von `PluginFeature` unter `analytics/features/plugins/base_plugin.py`.
* **Zentrale Ausführungsschicht (`PluginExecutor`):** Der Zugriff durch Scanner, LiveAnalyzer oder Chart-UI erfolgt ausschließlich über `PluginExecutor`, der Parametervalidierung (`ParameterSchema`), Dependency-Ordering und Logging übernimmt.
* **Service-Pipeline (`ServiceSetEvaluator`):** Führt Service-Sets (`ServiceSetDefinition`) in `execution_order` aus; Abhängigkeiten laufen über `depends_on`/`instance_id` und `PluginContext.shared_state` (Namespace-isoliert).

### 2.3. Hybrid Feature Store

Um Rechenlast zu minimieren, werden Rohdaten (OHLCV) vorab transformiert:

* **Native High-Speed Spalten:** Häufig abgefragte Werte (`ema_diff`, `atr_normalized`, `grid_nearest_level`) liegen als native Tabellenspalten für maximale Query-Performance vor.
* **Generisches JSON-Payload:** Beliebige dynamische Zusatzdaten neuer Plugins werden im Feld `feature_data JSON` abgelegt, verknüpft mit der stabilen `feature_id` und `plugin_version`.

### 2.4. Thread-Sicherer Database Connection Pool (`DbPool`)

* DuckDB-Connections sind nicht thread-safe. PyTrader verwendet das Thread-Local Singleton `DbPool` (`db_service.py`), bei dem jeder Thread seine eigene Verbindung hält.
* Dies verhindert File-Locking-Fehler unter Windows und erübrigt globale Threading-Locks auf Datenbankebene.

---

## 3. Ordner- & Modul-Layout

Domain-Struktur (Ebene 1). Detaillierte Modulübersichten liegen direkt im Code (Modul-Docstrings):

```text
PyTrader/
├── analytics/                      # Berechnungsdomäne
│   ├── background_workers/         # QThread-Hintergrundprozesse (historical_scanner, live_analyzer)
│   ├── engine/                     # Evaluierung & Service-Set-Logik (set_evaluator, service_models,
│   │                               #  service_set_repository, schema_migrator, base_definition)
│   ├── features/                   # Feature-Generierung & Plugin-System (feature_builder, definitions/, plugins/)
│   ├── signals/                    # Signal-Algorithmen (Alt-Pfad, deaktiviert)
│   └── statistics_repository.py    # SQL-Aggregationen auf feature_data (Statistik)
├── chart/                          # Visualisierungsdomäne (js/, indicators/, overlays/, widgets/,
│   │                               #  chart_win.py, indicator_dialog.py)
├── config/                         # App-Einstellungen & State-Modelle
├── ui/                             # Qt-Designer-Dateien (*.ui)
├── data/                           # DuckDB-Datenbanken (*.duckdb) + custom_plugins/
├── db_service.py                   # MT5-Sync, DbPool & Schema-Migrationen
├── main.py                         # Haupt-Orchestrator (MainWindow)
├── persistent_win.py               # Fenster-Persistence & Registry
├── service_win.py                  # Service-Fenster (Set-Editor, Papierkorb, Sperren)
├── statistic_win.py                # Statistik-Fenster
├── properties_win.py               # Properties-Fenster
├── scrollable_content.py           # Scrollbare Content-Mixin
└── state_manager.py                # UI-Status, Fenstergeometrien & Presets

```

---

## 4. Kern-Workflows

### 4.1. Historischer Scan (Batch)

1. `HistoricalScanner` (QThread) lädt OHLCV aus `market_data.duckdb` und führt aktive Batch-Presets/Service-Sets über den `PluginExecutor` aus.
2. `FeatureStorePayload` wird per Bulk-Upsert in den `feature_store` geschrieben (`feature_id`, `plugin_version`, `feature_data`).
3. Chart-Marker und Statistik lesen ausschließlich aus dem `feature_store` – **keine `signal_results`-Writes** (seit Phase 13 Schritt 7.B; die Tabelle bleibt als Legacy erhalten).

### 4.2. Echtzeit-Analyse (Live-Stream)

1. `LiveTickWorker` erkennt Bar-Closes; `LiveAnalyzer` bewertet die neue Kerze über den resilienten Pfad (`execute_set_resilient`, Skip-Logic, RAM-Quarantäne) gegen das im `PluginContext.shared_state` gepufferte Raster.
2. Ergebnisse werden in den `feature_store` geschrieben; der Chart liest sie über den feature_id-Lesepfad (New-Candle-Callback, debounced).
3. Das Chart-Fenster aktualisiert ausschließlich Overlays/Marker via JS-Bridge, ohne den Chart neu aufzubauen.

---

## 5. Goldene Regeln der Objektorientierung & Entkopplung (OOP Principles)

Jedes Refactoring und jede Code-Generierung muss strikt folgenden Prinzipien entsprechen:

1. **Abstraktion durch Basisklassen:**
* Jede Kern-Komponente erbt zwingend von ihrer abstrakten Klasse (`PluginFeature`, `PersistentWindow`, `BaseIndicator`).
* Aufrufende Schichten interagieren ausschließlich mit dem Interface, nicht mit konkreten Implementierungen.

2. **Entkopplung & Inversion of Control (IoC):**
* Keine zirkulären Abhängigkeiten: Sub-Module und Background-Worker dürfen niemals Kenntnis von konkreten UI-Orchestratoren (`MainWindow`) haben.
* Sub-Fenster erben von `PersistentWindow` und registrieren sich über den Dekoratormechanismus (`@register_persistent_window`).
* Kommunikation erfolgt asynchron über Qt-Signals/Slots oder Read-Only DB-Abfragen.

3. **Single Responsibility Principle (SRP):**
* **UI-Klassen (`PySide6`):** Nur Event-Handling, Rendering und State-Persistenz. Keine mathematischen Berechnungen.
* **Worker/Engine-Klassen:** Nur Datenverarbeitung und Logik. Kein GUI-Code oder PySide-UI-Import.
* **Repository/Service-Klassen:** Kapseln den Datenbank-Zugriff (`db_service.py`, `StatisticsRepository`, `MarketDataRepository`).

4. **Open/Closed Principle:**
* Neue Indikatoren oder Feature-Plugins werden durch Hinzufügen neuer Dateien unter `analytics/features/definitions` implementiert. Bestehender Rumpfcode darf dafür nicht geändert werden; Erweiterungen erfolgen strikt additiv (Wrapper/Schnittstellen).

5. **Typsicherheit:**
* Strikte Nutzung von Python Type Hints (`typing`, `TypedDict`).
* Der Datenaustausch zwischen Plugins und UI/Services folgt typisierten Verträgen (`ChartRenderPayload`, `FeatureStorePayload`, `ServiceSetDefinition`).

6. **Knappe In-Code-Dokumentation bei Anforderungsänderungen:**
* Bei allen neuen oder angepassten Logiken (insbesondere manuellen User-Vorgaben) muss direkt in den geänderten Sourcedateien an der betroffenen Stelle ein knapper Inline-Kommentar (1–2 Zeilen, z. B. `# USER-REQ: [Kurzbeschreibung der Anforderung]`) gesetzt werden, der den Grund der Code-Anpassung nachvollziehbar dokumentiert.
