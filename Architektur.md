# Architektur-Dokumentation: PyTrader System-Architektur

> **Single Point of Truth:** Dieses Dokument ist die verbindliche Architektur-Datei.
> Archiv-/Alt-Fassungen (`docs/Current/`, `docs/Archiv/`) werden nicht mehr gepflegt.
> Detaillierte Modul- und Tabellen-Beschreibungen liegen direkt im Code (Modul-Docstrings,
> `db/schema_initializer.py` als Schema-Source-of-Truth).
>
> **Stand:** 12.08.2026 (aktualisiert gegenuber Projektstand nach Refactoring 18.01.02,
> Phase 20/21 – DbPool-Modularisierung, Analytics-MVVM, Varianten/instance_hash,
> Multi-TF Execution, EventBus).

## 1. Executive Summary

Dieses Dokument beschreibt die verbindlichen Architektur-Richtlinien für das PyTrader-System. Das Kernziel ist die Bereitstellung einer hochperformanten, vollständig entkoppelten Desktop-Architektur (Python / PySide6 / DuckDB). Sie ermöglicht historische Massen-Scans, Echtzeit-Marktüberwachung (Live-Analyzer) und visuelle Chart-Analysen ohne redundante Code-Basis, Thread-Sperren oder UI-Blockaden.

Der Lösungsansatz basiert auf der **vollständigen Entkopplung von Berechnungs-Engines, Benutzeroberfläche und Speicher-Services** über DuckDB als zentrale, thread-sichere Kommunikationsschicht.

---

## 2. Architektonische Grundfesten

### 2.1. Entkopplung von Berechnung und UI (Datenbank als Brücke)

Die Benutzeroberfläche (Chart-Windows, Statistik-Fenster, Service-Fenster) darf unter keinen Umständen blockiert werden.

* **Backend (Background Worker Threads):** Hintergrund-Prozesse (`HistoricalScanner`, `LiveAnalyzer`, `DataSyncWorker`, `LiveTickWorker`) berechnen Daten und schreiben Ergebnisse asynchron in DuckDB.

* **Frontend (PySide6 / Lightweight Charts v5):** Chart-Overlays und Statistik-Widgets greifen *lesend* auf DuckDB zu oder empfangen typisierte Payloads (`ChartRenderPayload`, `FeatureStorePayload`) über die Ausführungsschicht, ohne Berechnungen auf dem GUI-Thread auszuführen.

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
 │ - analytics.duckdb   : feature_store (Hybrid, PK mit          │
 │                       instance_hash), analytics_metadata      │
 │ - app_data.duckdb    : app_config, broker_symbols,            │
 │                       analytics_profiles, chart_presets,      │
 │                       indicator_presets, instance_states,     │
 │                       kunden, service_set_history,            │
 │                       service_sets, service_sets_trash,       │
 │                       symbol_tf_states, window_instances      │
 └───────────────────────────────────────────────────────────────┘
```

**Hinweis:** Die Legacy-Tabelle `signal_results` existiert nicht mehr; der `feature_store` ist seit Phase 12/13 die einzige Analytics-Schreibziel-Tabelle.

### 2.2. Plugin-Architektur (`PluginFeature` & `PluginExecutor`)

Berechnungs-Engines sind strikt zustandslos (*stateless*).

* **Zustandslosigkeit:** Jede Berechnung ist eine reine Funktion `calculate(df, params, context)`.
* **Einheitliches Interface:** Neue Features und Service-Plugins erben von `PluginFeature` unter `analytics/features/plugins/base_plugin.py`.
* **Zentrale Ausführungsschicht (`PluginExecutor`):** Der Zugriff durch Scanner, LiveAnalyzer oder Chart-UI erfolgt ausschließlich über `PluginExecutor` (`analytics/features/feature_builder.py`), der Parametervalidierung (`ParameterSchema`), Dependency-Ordering und Logging übernimmt.
* **Service-Pipeline (`ServiceSetEvaluator`):** Führt Service-Sets (`ServiceSetDefinition` in `analytics/engine/service_models.py`) in `execution_order` aus; Abhängigkeiten laufen über `depends_on`/`instance_id` und `PluginContext.shared_state` (Namespace-isoliert).

### 2.3. Hybrid Feature Store

Um Rechenlast zu minimieren, werden Rohdaten (OHLCV) vorab transformiert:

* **Native High-Speed Spalten:** Häufig abgefragte Werte (`ema_diff`, `atr_normalized`, `grid_nearest_level`) liegen als native Tabellenspalten für maximale Query-Performance vor.
* **Generisches JSON-Payload:** Beliebige dynamische Zusatzdaten neuer Plugins werden im Feld `feature_data JSON` abgelegt, verknüpft mit der stabilen `feature_id` und `plugin_version`.
* **Parameter-Varianten (`instance_hash`):** Jede Parameter-Variante eines Plugins erhält einen stabilen 8-stelligen SHA256-Short-Hash (`instance_hash`, aus `generate_instance_hash`, ohne Lookback). Der Primärschlüssel des `feature_store` lautet `(symbol, timeframe, bar_time, feature_id, instance_hash)` – dadurch koexistieren beliebig viele Presets/Clones desselben Plugins ohne Kollision, inkl. gezieltem Daten-Purge je Variante.

### 2.4. Thread-Sicherer Database Connection Pool (`DbPool`)

* DuckDB-Connections sind nicht thread-safe. PyTrader verwendet das Thread-Local Singleton `DbPool` (**`db/db_pool.py`**), bei dem jeder Thread seine eigene Verbindung je DB-Datei hält.
* Dies verhindert File-Locking-Fehler unter Windows und erübrigt globale Threading-Locks auf Datenbankebene (lock-freier Zugriff; `with_db_lock` nur für wenige kritische Stellen).
* `db_service.py` ist seit 18.01.02 eine **Fassade (Re-Export-Wrapper)** ohne eigene Logik – Bestands-Caller importieren unverändert aus dem Root-Shim `db_service`, die Implementierung liegt in `db/db_pool.py`, `db/db_utils.py`, `db/schema_initializer.py`, `data_sync/mt5_sync_service.py`, `repositories/db_service.py` und `repositories/market_data_repository.py`.

---

## 3. Ordner- & Modul-Layout

Domain-Struktur (Ebene 1). Detaillierte Modulübersichten liegen direkt im Code (Modul-Docstrings):

```text
PyTrader/
├── analytics/                      # Berechnungsdomäne
│   ├── background_workers/         # QThread-Hintergrundprozesse (historical_scanner.py, live_analyzer.py)
│   ├── engine/                     # Evaluierung, Service-Sets & Lesepfad:
│   │                               #  set_evaluator.py, service_models.py, service_set_repository.py,
│   │                               #  service_selector_model.py, feature_store_reader.py, tree_builder.py,
│   │                               #  analytics_repository.py, analytics_view_model.py, analytics_worker.py,
│   │                               #  schema_migrator.py, description_dialog.py
│   ├── features/                   # Feature-Generierung & Plugin-System (feature_builder.py, definitions/, plugins/)
│   │   └── definitions/            # Service-Plugins mit srv_-Präfix (srv_grid_lines, srv_proximity, ...)
│   ├── ui/                         # Analytics-Fenster & Seiten (analytics_win.py, heatmap_page.py,
│   │                               #  heatmap_widget.py, scatter_page.py, table_page.py,
│   │                               #  distribution_page.py, equity_page.py, common.py)
│   └── statistics_repository.py    # SQL-Aggregationen auf feature_data (Statistik)
├── chart/                          # Visualisierungsdomäne
│   ├── js/                         # Lightweight-Charts-Bridge (01_core, 02_time_utils, 03_chart_rendering,
│   │                               #  04_live_updates, 05_measurement, 06_two_tier)
│   ├── indicators/                 # Indikator-Plugins mit ind_-Präfix (base_indicator.py, ind_moving_averages,
│   │                               #  ind_fixed_grid_proximity, utils/)
│   ├── overlays/                   # Overlay-Stilmodelle (style_models.py)
│   ├── widgets/                    # UI-Widgets (style_picker_widget, named_item_actions)
│   ├── chart_win.py                # PyTraderChartWindow + ChartBridge (JS-Bridge) + Serializer-Worker
│   ├── chart_basics.py             # Chart-Grundlagen
│   └── indicator_dialog.py         # Indikator-Dialog
├── config/                         # App-Einstellungen, State-Modelle & EventBus (app_settings, base_state_model, event_bus)
├── data/                           # DuckDB-Datenbanken (*.duckdb) + custom_plugins/
├── db/                             # DB-Schicht (db_pool.py, db_utils.py, schema_initializer.py) – Basis-Schicht, kein Projekt-Import
├── data_sync/                      # MT5-Sync-Service (mt5_sync_service.py: SYMBOLS, TF_SECONDS_MAP, get_timeframes, sync_market_data)
├── repositories/                   # Repository-Schicht (market_data_repository.py, db_service.py-Fassade,
│   │                               #  grabber_repository.py, symbol_repository.py, window_state_repository.py,
│   │                               #  analytics_profile_repository.py)
├── workers/                        # Threads (data_sync_worker.py, live_tick_worker.py)
├── serviceui/                      # Service-UI-Paket (Phase 15): service_win.py, service_selector_dialog.py,
│   │                               #  service_selector_widget.py, master_tree.py, run_worker.py, common_widgets.py,
│   │                               #  status_panel.py, new_set_dialog.py, param_columns.py, symbols_win.py,
│   │                               #  trash_dialog.py, service_set_utils.py
├── ui/                             # Qt-Designer-Dateien (*.ui) + Fenster (window_manager.py, statistic_win.py,
│   │                               #  properties_win.py)
├── db_service.py                   # SHIM (Re-Export aus repositories/db_service.py), MT5-Sync-CLI (python db_service.py)
├── main.py                         # Haupt-Orchestrator (MainWindow)
├── persistent_win.py               # Fenster-Persistence & Registry (@register_persistent_window)
├── scrollable_content.py           # Scrollbare Content-Mixin
├── state_manager.py                # UI-Status, Fenstergeometrien & Presets
└── test/                           # Test-/Check-Skripte (headless; nicht produktiv, wird nicht exportiert)
```

---

## 4. Kern-Workflows

### 4.1. Historischer Scan (Batch)

1. `HistoricalScanner` (QThread, `analytics/background_workers/historical_scanner.py`) lädt OHLCV aus `market_data.duckdb` (`ohlcv_bars`) und führt aktive Service-Sets/Presets über den `PluginExecutor` aus.
2. `FeatureStorePayload` wird per Bulk-Upsert in den `feature_store` geschrieben (`feature_id`, `plugin_version`, `instance_hash`, `feature_data`).
3. Chart-Marker und Statistik lesen ausschließlich aus dem `feature_store` – **keine `signal_results`-Writes** (seit Phase 13; die Tabelle existiert nicht mehr).
4. **Multi-TF Execution (Phase 21):** Der `ServiceRunWorker` (`serviceui/run_worker.py`) mit Sentinel `ALL_TIMEFRAMES = "ALLE Timeframes"` iteriert sequentiell über alle verfügbaren Timeframes (`get_timeframes()`, M1–MN1). Je Timeframe feuert er die Signale `tf_started`/`tf_finished`; die `TfStatusBadgeBar` (`serviceui/common_widgets.py`) zeigt den Status je Timeframe (Daten vorhanden / läuft / Fehler).

### 4.2. Echtzeit-Analyse (Live-Stream)

1. `LiveTickWorker` erkennt Bar-Closes; `LiveAnalyzer` bewertet die neue Kerze über den resilienten Pfad (`execute_set_resilient`, Skip-Logic, RAM-Quarantäne) gegen das im `PluginContext.shared_state` gepufferte Raster.
2. Ergebnisse werden in den `feature_store` geschrieben; der Chart liest sie über den feature_id-Lesepfad (New-Candle-Callback, debounced).
3. Das Chart-Fenster aktualisiert ausschließlich Overlays/Marker via JS-Bridge (`applyChartRenderPayload`), ohne den Chart neu aufzubauen.

### 4.3. Analytics MVVM (Heatmap, Scatter, Tabellen)

* **MVVM-Datenfluss:** `DuckDB → FeatureStoreReader/Repositories → AnalyticsAsyncWorker/AnalyticsViewModel → UI-Pages` (Heatmap, Scatter, Table, Distribution, Equity).
* **Kein SQL in UI:** UI-Klassen (`analytics/ui/*`) enthalten keine SQL-Queries; `AnalyticsViewModel.request_*`-Methoden und `set_feature_ids(ids, hashes)` orchestrieren asynchron über Signale.
* `FeatureStoreReader` (`analytics/engine/feature_store_reader.py`) ist der zentrale Lesezugriff: `fetch_rows`, `fetch_columns`, `fetch_heatmap`, `fetch_generic_heatmap`, `fetch_service_tf_status`, `fetch_last_execution_dates`, `fetch_latest_bar_time` u. a.

---

## 5. Goldene Regeln der Objektorientierung & Entkopplung (OOP Principles)

Jedes Refactoring und jede Code-Generierung muss strikt folgenden Prinzipien entsprechen:

1. **Abstraktion durch Basisklassen:**
* Jede Kern-Komponente erbt zwingend von ihrer abstrakten Klasse (`PluginFeature`, `PersistentWindow`, `BaseIndicator`).
* Aufrufende Schichten interagieren ausschließlich mit dem Interface, nicht mit konkreten Implementierungen.

2. **Entkopplung & Inversion of Control (IoC):**
* Keine zirkulären Abhängigkeiten: Sub-Module und Background-Worker dürfen niemals Kenntnis von konkreten UI-Orchestratoren (`MainWindow`) haben.
* Sub-Fenster erben von `PersistentWindow` und registrieren sich über den Dekoratormechanismus (`@register_persistent_window`).
* Kommunikation erfolgt asynchron über Qt-Signals/Slots, den zentralen **`EventBus`** (`config/event_bus.py`: `favorites_changed`, `profile_changed`, `service_set_changed`, `service_run_started`, `service_run_finished`) oder Read-Only DB-Abfragen.
* **Concurrency-Guard:** Solange intensive Service-Berechnungen laufen, wird der Sync-Timer über den EventBus pausiert (Locking-Konflikte/UI-Ruckler).

3. **Single Responsibility Principle (SRP):**
* **UI-Klassen (`PySide6`):** Nur Event-Handling, Rendering und State-Persistenz. Keine mathematischen Berechnungen.
* **Worker/Engine-Klassen:** Nur Datenverarbeitung und Logik. Kein GUI-Code oder PySide-UI-Import.
* **Repository/Service-Klassen:** Kapseln den Datenbank-Zugriff (`db/db_pool.py`, `repositories/market_data_repository.py`, `analytics/statistics_repository.py`, `FeatureStoreReader`, `ServiceSetRepository`, `AnalyticsProfileRepository`, ...).

4. **Open/Closed Principle:**
* Neue Service-Plugins werden durch Hinzufügen neuer Dateien unter `analytics/features/definitions/` (`srv_`-Präfix), neue Indikatoren unter `chart/indicators/` (`ind_`-Präfix) implementiert. Bestehender Rumpfcode darf dafür nicht geändert werden; Erweiterungen erfolgen strikt additiv (Wrapper/Schnittstellen).

5. **Typsicherheit:**
* Strikte Nutzung von Python Type Hints (`typing`, `TypedDict`).
* Der Datenaustausch zwischen Plugins und UI/Services folgt typisierten Verträgen (`ChartRenderPayload`, `FeatureStorePayload`, `ServiceSetDefinition`, `ServiceInstanceConfig`).

6. **Naming Conventions (Phase 21):**
* Services: `srv_`-Präfix in `analytics/features/definitions/`; Indikatoren: `ind_`-Präfix in `chart/indicators/`. Füllwörter (`service`, `plugin`, `indicator`) entfallen im Dateinamen.
* Jedes Service-Plugin deklariert `metadata["category"]` (Slash-separierter Ordnerpfad) für die dynamische Kategorie-Ordner-Struktur im MasterTree (`analytics/engine/tree_builder.py`).

7. **Wanduhr-Garantie (Invariante):**
* MT5-Epochs sind Berlin-Wanduhr-encoded. SQL-Extraktionen (Heatmap, DOW, Hour, Date) nutzen strikt `bar_time AT TIME ZONE 'UTC'`, um eine fehlerhafte automatische Umrechnung durch DuckDB in Lokalzeiten zu unterbinden.

8. **Knappe In-Code-Dokumentation bei Anforderungsänderungen:**
* Bei allen neuen oder angepassten Logiken (insbesondere manuellen User-Vorgaben) muss direkt in den geänderten Sourcedateien an der betroffenen Stelle ein knapper Inline-Kommentar (1–2 Zeilen, z. B. `# USER-REQ: [Kurzbeschreibung der Anforderung]`) gesetzt werden, der den Grund der Code-Anpassung nachvollziehbar dokumentiert.
