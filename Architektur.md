# Architektur-Dokumentation: PyTrader System-Architektur

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
 │ - analytics.duckdb   : feature_store, signal_results          │
 │ - app_data.duckdb    : indicator_presets, window_instances    │
 └───────────────────────────────────────────────────────────────┘

```

### 2.2. Plugin-Architektur (`PluginFeature` & `PluginExecutor`)

Berechnungs-Engines sind strikt zustandslos (*stateless*).

* **Zustandslosigkeit:** Jede Berechnung ist eine reine Funktion `calculate(df, params)`.
* **Einheitliches Interface:** Neue Features und Indikator-Engines erben von `PluginFeature` unter `analytics/features/plugins/base_plugin.py`.
* **Zentrale Ausführungsschicht (`PluginExecutor`):** Der Zugriff durch Scanner, LiveAnalyzer oder Chart-UI erfolgt ausschließlich über `PluginExecutor`, der Parametervalidierung (`ParameterSchema`), Dependency-Ordering und Logging übernimmt.


### 2.3. Hybrid Feature Store

Um Rechenlast zu minimieren, werden Rohdaten (OHLCV) vorab transformiert:

* **Native High-Speed Spalten:** Häufig abgefragte Werte (`ema_diff`, `rsi_14`, `atr_normalized`) liegen als native Tabellenspalten für maximale Query-Performance vor.
* **Generisches JSON-Payload:** Beliebige dynamische Zusatzdaten neuer Plugins werden im Feld `feature_data JSON` abgelegt, verknüpft mit der stabilen `feature_id`.



### 2.4. Thread-Sicherer Database Connection Pool (`DbPool`)

* DuckDB-Connections sind nicht thread-safe. PyTrader verwendet das Thread-Local Singleton `DbPool` (`db_service.py`), bei dem jeder Thread seine eigene Verbindung hält.
* Dies verhindert File-Locking-Fehler unter Windows und erübrigt globale Threading-Locks auf Datenbankebene.

### 2.5. Verbindliche UI-Regel: Farbwahl ausschließlich über `ColorButton`

Farbwerte im gesamten UI werden **ausschließlich** über das kompakte Custom-Widget `ColorButton` (`chart/widgets/color_button.py`) erfasst – **niemals** über freie Texteingabefelder (`QLineEdit`) oder andere Eingabe-Typen.

* **Geltungsbereich (VERBINDLICH):** Jeder Parameter vom Typ `"color"` im `ParameterSchema` einer Plugin- oder Service-Definition wird **IMMER** als `ColorButton` gerendert – in allen Formular-Generatoren (`indicator_dialog.py`, `service_win.py`) und für alle aktuellen wie zukünftigen Plugin-/Service-Definitionen. Ein Farbparameter ohne `ColorButton` ist ein Fehler.
* **Alpha-Kanal:** Das optionale Schema-Flag `allow_alpha: bool` (Default `True`) schaltet den Transparenz-Slider im `QColorDialog` frei (`ShowAlphaChannel`).
* **String-Format (CSS/Chart-kompatibel):**
  * Alpha = 255 (volle Deckkraft) → Hex-Format `#RRGGBB`.
  * Alpha < 255 (Teil-Transparenz) → `rgba(r, g, b, a)` (a als Float 0..1).
  * Beide Formate sind 1:1 kompatibel mit TradingView Lightweight Charts v5 (WebEngine) und HTML/CSS.
* **Persistenz:** Die von `ColorButton.color()` gelieferten Strings werden unversehrt in Presets, Service-Sets und Chart-State (`display_params`) gespeichert und über den `chart_render_payload` an die Chart-Overlays weitergereicht.
* **Kompaktes Layout:** `ColorButton` hat eine feste Kompaktgröße (60×24 px) und `QSizePolicy.Fixed` – es blockiert die dynamische Höhen-/Breiten-Berechnung des Prop-Fensters nicht (Roadmap 5.5.2.1 Prämisse 3).
* **Interaktion:** `colorChanged = Signal(str)` ist mit der Parameter-Aktualisierungs-Logik des Dialogs verknüpft (gleicher Callback wie alle anderen Controls).

---

## 3. Ordner- & Modul-Layout

Das Projekt folgt einer klaren Domain-Struktur:

```text
PyTrader/
├── analytics/                      # Analyse- & Berechnungsdomäne
│   ├── background_workers/         # QThread Hintergrund-Prozesse (Scanner, LiveAnalyzer)
│   ├── engine/                     # Signal-Evaluierung & Set-Logik (set_evaluator.py)
│   ├── features/                   # Feature-Generierung & Plugin-System
│   │   ├── feature_builder.py      # PluginLoader, PluginRegistry, PluginExecutor
│   │   ├── definitions/            # Konkrete Plugins (grid_liquidity.py, ema_diff.py)
│   │   └── plugins/                # Plugin-Schnittstellen (base_plugin.py)
│   └── signals/                    # Signal-Algorithmen (heuristics, ML)
├── chart/                          # Visualisierungsdomäne
│   ├── js/                         # Lightweight Charts v5 Module (01_core.js - 05_measurement.js)
│   ├── indicators/                 # Chart-Indikatoren (grid.py, grid_liquidity.py)
│   ├── overlays/                   # Signal-Marker Overlays
│   ├── widgets/                    # Wiederverwendbare UI-Widgets (color_button.py)
│   ├── chart_win.py                # PyTraderChartWindow (WebEngine-Container)
│   └── indicator_dialog.py         # Generischer Einstellungs-Dialog
├── config/                         # App-Einstellungen & State-Modelle
├── data/                           # DuckDB Datenbanken (*.duckdb)
├── db_service.py                   # MT5-Sync, DB-Pool & Schema-Migrationen
├── main.py                         # Haupt-Orchestrator (MainWindow)
├── persistent_win.py               # Basisklasse für Fenster-Persistence & Registry
└── state_manager.py                # UI-Status, Fenstergeometrien & Presets

```

---

## 4. Kern-Workflows

### 4.1. Historischer Scan (Batch)

1. User startet den Scan im Service-Fenster (`service_win.py`).
2. `HistoricalScanner` (QThread) lädt OHLCV-Daten aus `market_data.duckdb`.
3. Aktive Presets werden anhand von `plugin_id` aus `indicator_presets` gelesen.
4. Der `PluginExecutor` führt `plugin.calculate(df, params)` aus.
5. `FeatureStorePayload` wird via Bulk-Insert/Upsert in den `feature_store` geschrieben.
6. `SignalEngine` evaluiert Signale und schreibt Ergebnisse in `signal_results`.


### 4.2. Echtzeit-Analyse (Live-Stream)

1. `LiveTickWorker` empfängt MT5-Ticks, erkennt Bar-Closes und persistiert geschlossene Kerzen.
2. `LiveAnalyzer` evaluiert für die neue Kerze das Plugin via `PluginExecutor`.
3. Erzeugte Signale werden in `signal_results` gespeichert und per Qt-Signal (`on_live_signal`) an offene `PyTraderChartWindow`-Instanzen emittiert.
4. Das Chart-Fenster aktualisiert ausschließlich das Marker-Overlay via JS-Bridge, ohne den Chart neu aufzubauen.

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
* Neue Indikatoren oder Feature-Plugins werden durch Hinzufügen neuer Dateien unter `analytics/features/definitions` implementiert. Bestehender Rumpfcode darf dafür nicht geändert werden.


5. **Typsicherheit:**
* Strikte Nutzung von Python Type Hints (`typing`, `TypedDict`).
* Der Datenaustausch zwischen Plugins und UI/Services folgt typisierten Verträgen (`ChartRenderPayload`, `FeatureStorePayload`).
* 