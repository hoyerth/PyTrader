# Architektur-Dokumentation: Einheitliche Berechnungs- und Service-Engine für PyTrader

> Hinweis: Diese Datei liegt unter `docs/Old` und ist ein archiviertes Konzept-Dokument.
> Verbindliche, aktuell gepflegte Architektur: `Architektur.md` (Projekt-Root) sowie
> `Agents.md`. Dieser Stand wurde am 04.08.2026 gegen den Ist-Code (Phase 14,
> Commit `fc27094`) abgeglichen und faktisch korrigiert.

## 1. Executive Summary

Dieses Dokument beschreibt die Architektur-Richtlinien für das PyTrader-System. Das Kernziel ist die Schaffung einer hochperformanten, entkoppelten Desktop-Architektur (Python/PySide6), die historische Analysen, Live-Marktüberwachung und Statistik-Auswertungen ohne redundante Code-Basis ermöglicht.

Der Lösungsansatz basiert auf einer **einheitlichen Berechnungs-Engine** (Plugin-/Service-Pipeline) mit einem vorgeschalteten **Hybrid-Feature-Store** und einer strikten **Trennung von Berechnung und Visualisierung** über DuckDB als Kommunikationsschicht.

> Stand-Korrektur (04.08.2026): Die frühere „einheitliche Signal-Engine" (`SignalDefinition`
> / Signal-Sets) ist seit Phase 13 Schritt 7.B **deaktiviert** (keine `signal_results`-Writes
> mehr). Marktentscheidend ist heute die Plugin-/Service-Architektur (`PluginFeature`,
> `PluginExecutor`, `ServiceSetEvaluator`) mit dem `feature_store` als Lesequelle für
> Chart-Marker und Statistik.

---

## 2. Architektonische Grundprinzipien

### 2.1. Entkopplung von Berechnung und UI (Datenbank als Brücke)
Die UI (Chart-Ansicht, Statistik-Fenster, Service-Fenster) darf unter keinen Umständen blockiert werden. Der Chart führt keine Berechnungen aus, sondern liest ausschließlich vorberechnete Daten aus DuckDB (mit definiertem Fallback).
*   **Backend (Worker-Prozesse):** Analysieren historische Daten oder Live-Ticks und schreiben alle gefundenen Ereignisse kontinuierlich in den `feature_store` (`analytics.duckdb`).
*   **Frontend (PySide6 / Lightweight Charts v5):** Die Chart-Overlays und Statistik-Widgets greifen ausschließlich *lesend (read-only)* auf diese Datenbank zu und visualisieren fertige Ergebnisse (`ChartRenderPayload`).

### 2.2. Einheitliche Berechnungs-Engine (Plugin-Architektur)
Die zentrale Schnittstelle aller Berechnungen ist das **stateless Plugin** (`PluginFeature`, `analytics/features/plugins/base_plugin.py`):
*   Jede Berechnung ist eine reine Funktion `calculate(df, params, context)`.
*   Der **`PluginExecutor`** übernimmt Plugin-Auflösung (Registry), Parametervalidierung (`ParameterSchema`), Dependency-Ordering und strukturiertes Fehler-Logging.
*   Der **`ServiceSetEvaluator`** führt Service-Sets (`ServiceSetDefinition`) in `execution_order` aus; Abhängigkeiten laufen über `depends_on`/`instance_id` und `PluginContext.shared_state` (Namespace-isoliert).
*   Die frühere Trennung nach Signal-Typen (klassische Regeln / Muster / ML) entfällt im aktiven Pfad; `SignalDefinition`-Sets sind deaktiviert (Phase 13 7.B).

### 2.3. Der Hybrid Feature Store als Fundament
Um die Rechenlast im Desktop-Betrieb zu minimieren, werden Rohdaten (OHLCV) vorab in strukturierte Features transformiert:
*   **Native High-Speed-Spalten:** Häufig abgefragte Werte (`ema_diff`, `atr_normalized`, `grid_nearest_level`) liegen als native Tabellenspalten für maximale Query-Performance vor.
*   **Generisches JSON-Payload:** Beliebige dynamische Zusatzdaten neuer Plugins werden im Feld `feature_data JSON` abgelegt, verknüpft mit stabiler `feature_id` und `plugin_version` (Hybrid-Schema, Phase 12).
*   Die Feature-Extraktion erfolgt nur *einmal*; diese berechneten Merkmale werden dauerhaft gespeichert.
*   Sowohl deterministische Regeln als auch (zukünftige) ML-Modelle greifen ausschließlich auf den Feature-Store zu, nicht auf rohe Kerzendaten.

### 2.4. Lokale Execution First
In der Initialphase werden alle Berechnungen lokal innerhalb der nativen Python-Desktop-Umgebung ausgeführt. Komplexe ML-Modelle werden über performante lokale Runtimes eingebunden. Ein ausgelagerter Microservice (z. B. FastAPI/Docker) wird nur bei zukünftigen Skalierungsanforderungen in Betracht gezogen.

---

## 3. Datenbank-Architektur (DuckDB)

Die bestehende `market_data.duckdb` (OHLCV-Rohdaten) wird um `analytics.duckdb` (Features/Signale) und `app_data.duckdb` (UI-Status, Presets, Service-Sets) ergänzt.

### Tabellen-Struktur (analytics.duckdb) – konzeptionell

**1. `feature_store`** (Persistente Speicherung der vorberechneten Merkmale – **zentrale Lesequelle für Chart & Statistik**)
*   `symbol` (VARCHAR), `timeframe` (VARCHAR), `bar_time` (TIMESTAMPTZ) – Primärschlüssel
*   Native Feature-Spalten (z. B. `ema_diff`, `atr_normalized`, `grid_nearest_level`)
*   Hybrid-Schema (Phase 12): `feature_id` (VARCHAR), `plugin_version` (VARCHAR), `feature_data` (JSON)
*   **Schema-Detail (verbindlich):** `db_service.py` `check_and_init_databases()` – Single Source of Truth

**2. `signal_definitions`** (Legacy-Tabelle, Phase 1)
*   Metadaten zu Signal-Algorithmen. Wird seit Phase 13 7.B **nicht mehr aktiv gelesen**; Signale sind in den Workern als Hardcoded-Dicts definiert.

**3. `signal_sets`** (Legacy-Tabelle, Phase 1)
*   JSON-Konfiguration kombinierter Signale. Wird nicht mehr aktiv gelesen. Die aktiven Service-Sets liegen in `app_data.duckdb` → Tabelle `service_sets` (Phase 13, `ServiceSetRepository`).

**4. `signal_results`** (Legacy-Tabelle, Phase 1 – Writes deaktiviert)
*   War die zentrale Tabelle für erkannte Events (hist. & live). Seit Phase 13 7.B werden **keine `signal_results`-Writes** mehr erzeugt; Marker und Statistik lesen den `feature_store` (`feature_data` der Plugins/Services, z. B. `feature_id='proximity'`). Die Tabelle bleibt als Referenz erhalten.

---

## 4. Software-Struktur & Ordner-Layout

Das Projekt (PyTrader) folgt einer klaren Domain-Struktur. Verbindlich und aktuell gepflegt ist das Layout in `Architektur.md` (Root, §3); nachfolgend der konzeptionelle Überblick:

```
PyTrader/
├── analytics/                     # Analyse- & Berechnungsdomäne
│   ├── engine/                    # set_evaluator.py (SetEvaluator + ServiceSetEvaluator),
│   │                              # service_models.py, service_set_repository.py,
│   │                              # schema_migrator.py, base_definition.py
│   ├── features/                  # Feature-Generierung & Plugin-System
│   │   ├── feature_builder.py     # PluginLoader, PluginRegistry, PluginExecutor, FeatureBuilder
│   │   ├── definitions/           # Konkrete Plugins (grid_lines, proximity, grid_liquidity, ema_diff, atr_normalized, grid_levels)
│   │   └── plugins/               # Plugin-Schnittstellen (base_plugin.py)
│   ├── signals/                   # Signal-Algorithmen (Alt-Pfad, deaktiviert): heuristics/,
│   │                              # composite/, experimental/, machine_learning/ (Inferenz)
│   ├── statistics_repository.py   # SQL-Aggregationen auf feature_data (Statistik-Fenster)
│   └── background_workers/        # QThread-Prozesse: historical_scanner.py, live_analyzer.py
├── chart/                         # Visualisierungsdomäne
│   ├── js/                        # Lightweight Charts v5 Module (01_core.js – 05_measurement.js)
│   ├── indicators/                # Chart-Indikatoren (grid_liquidity.py; Alt-Indikator grid.py entfernt)
│   ├── overlays/                  # Signal-Marker Overlay (signal_overlay.py)
│   ├── widgets/                   # Wiederverwendbare UI-Widgets (color_button.py)
│   ├── chart_win.py               # PyTraderChartWindow (WebEngine-Container)
│   └── indicator_dialog.py        # Generischer Einstellungs-Dialog
├── config/                        # App-Einstellungen & State-Modelle (app_settings.py)
├── ui/                            # Qt-Designer-Dateien (*.ui: chart_win, main_win, service_win, statistic_win)
├── data/                          # Lokale DuckDB-Dateien (market_data, analytics, app_data, custom_plugins)
├── db_service.py                  # MT5-Sync, DbPool (Thread-local) & Schema-Migrationen
├── main.py                        # Haupt-Orchestrator (MainWindow)
├── persistent_win.py              # Basisklasse für Fenster-Persistence & Registry
├── service_win.py                 # Service-Fenster (Set-Editor, Papierkorb, Sperren)
├── statistic_win.py               # Statistik-Fenster
└── state_manager.py               # UI-Status, Fenstergeometrien & Presets
```

## 5. Kernprozesse

### 5.1. Historischer Backtest & Scanner
1. Ein User triggert einen Scan (Service-Fenster).
2. Der `historical_scanner`-Worker lädt OHLCV-Daten aus `market_data.duckdb`.
3. Der `PluginExecutor` führt aktive Batch-Presets / Service-Sets aus.
4. Ergebnisse werden als FeatureStorePayload (Bulk-Upsert) in den `feature_store` geschrieben (inkl. `feature_id`, `plugin_version`, `feature_data`).
5. Statistik und Chart-Marker lesen diese Daten aus dem `feature_store` (keine `signal_results`-Writes).

### 5.2. Live-Erkennung
1. Neue Ticks aggregieren zu einer abgeschlossenen Kerze (Bar-Close).
2. Der `live_analyzer`-Worker bewertet die neue Kerze über den resilienten Pfad (`execute_set_resilient`, Skip-Logic, RAM-Quarantäne) gegen ein im `PluginContext.shared_state` gepuffertes Raster.
3. Ergebnisse werden in den `feature_store` geschrieben; der Chart liest sie per Re-Render/Refresh (feature_id-Lesepfad).
4. Die UI wird bei neuen Bar-Closes über den New-Candle-Callback (debounced Refresh) benachrichtigt.

---

## 6. Richtlinien für die KI-gestützte Weiterentwicklung

Wenn Sie diese Dokumentation nutzen, um mit verschiedenen KIs Teilkomponenten auszuarbeiten, beachten Sie folgende Anweisungen für den Prompt-Kontext (verbindliche Details: `Architektur.md` §5, `Agents.md`, System-Instruktionen):

*   **Keine Logik-Vermischung:** UI-Aktualisierungen strikt von der Berechnungs-Logik trennen.
*   **Fokus auf DuckDB:** Effiziente vektorisierte Pandas/Numpy-Operationen, die gut mit DuckDB harmonieren.
*   **Abstrakte Vererbung:** Neue Komponenten erben zwingend von ihrer Basisklasse (`PluginFeature`, `PersistentWindow`, `BaseIndicator`).
*   **Additive Erweiterung (Open/Closed):** Neue Plugins/Services/Fenster durch neue Dateien; Bestandsmodule nicht brechen.
*   **Desktop-Kompatibilität:** Keine komplexen verteilten Systeme (Kafka, Redis, Kubernetes) – Desktop-Anwendung (Windows 11).

## 7. Goldene Regeln der Objektorientierung & System-Entkopplung (OOP Principles)

Jede Code-Generierung und Refactoring-Aufgabe durch KI-Assistenten muss strikt den folgenden objektorientierten Design-Prinzipien folgen:

1. **Abstraktion durch Abstrakte Basisklassen (ABC & Polymorphie):**
   * Keine isolierten Funktionen oder ad-hoc Klassen für Business-Logik.
   * Jede Kern-Komponente (z. B. Plugins, Features, Fenster, Indikatoren) **muss** von ihrer jeweiligen abstrakten Basisklasse erben (`PluginFeature`, `BaseFeature`, `PersistentWindow`, `BaseIndicator`).
   * Die aufrufende Engine interagiert **ausschließlich** mit dem abstrakten Interface, niemals mit konkreten Implementierungen.

2. **Vollständige Entkopplung & Inversion of Control (IoC):**
   * **Keine zirkulären Abhängigkeiten:** Sub-Module (z. B. Worker oder Dialoge) dürfen niemals Kenntnis von konkreten Orchestratoren (wie `MainWindow`) haben.
   * **Kommunikation über Signals/Slots & Repositories:** UI-Komponenten und Datenverarbeiter kommunizieren strikt asynchron über PyQt-Signals oder Read-Only-Datenbankabfragen.
   * **Verboten:** Hardcoded Klassennamen-Checks in zentralen Repositories. Fenstertypen registrieren sich generisch/dynamisch über Dekoratoren/Registrys (`@register_persistent_window`).

3. **Single Responsibility Principle (SRP - Eine Aufgabe pro Klasse):**
   * **UI-Klassen (`PySide6`):** Verantwortlich *nur* für Event-Handling, Rendering und State-Persistenz. Keine Berechnungen, Indikator-Logik oder direkte DB-Verbindungsaufbauten.
   * **Worker/Engine-Klassen:** Verantwortlich *nur* für Datenverarbeitung und mathematische Evaluierung. Absolut kein UI-Import oder GUI-Code.
   * **Repository-Klassen:** Kapseln den Datenbank-Zugriff exklusiv (SQL-Abfragen, Connection-Handling).

4. **Offen für Erweiterung, Geschlossen für Änderung (Open/Closed Principle):**
   * Neue Indikatoren, Strategien, Plugins oder Fenster müssen durch **Hinzufügen neuer Dateien** implementiert werden können, ohne bestehende Kern-Dateien brechen zu müssen. Erweiterungen bestehender Module erfolgen strikt additiv (Wrapper/Schnittstellen).

5. **Typsicherheit & Verlässliche Datenverträge:**
   * Strikte Nutzung von Python **Type Hints** (`typing`, `TypedDict`) für alle Funktionsparameter und Rückgabewerte.
   * Keine impliziten Dictionaries als Datenverträge zwischen Modulen; Datenströme nutzen definierte TypedDict-Verträge (`ChartRenderPayload`, `FeatureStorePayload`, `ServiceSetDefinition`), Dataframes, Primitive oder Typ-Aliase.
