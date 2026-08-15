# ARCHITEKTUR-MAP (PyTrader)

> **Zweck:** Bugfixes & Erweiterungen auf das **minimale Set an Dateien** reduzieren.
> **Anwendung (KI-Prompt):** Bei einem Bug/Feature IMMER zuerst diese Map lesen (einmalig, ~2k Tokens), dann NUR die in der Routing-Tabelle (Teil C) genannten Dateien öffnen. Nicht die ganze Codebasis durchsuchen.
> **Stand:** 15.08.2026 (aktualisiert nach 23.10) – Generiert aus Docstrings + Import-Graphen (174 Py-Dateien / 50.623 Zeilen, 6 JS-Dateien / 1.837 Zeilen).

---

## Teil A – Layering & Invarianten (Import-Richtung)

```
DuckDB (data/*.duckdb)
   ↑
db/ + repositories/                          (einzige SQL-Schicht)
   ↑
analytics/engine/ + analytics/features/      (Business-Logik, ViewModel, Evaluatoren)
   ↑
serviceui/ + analytics/ui/ + chart/ + ui/ + main.py (UI-Fenster, Orchestratoren)
```

| Regel | Bedeutung |
|---|---|
| **Kein SQL in UI** | UI-Klassen rufen NUR Repositories/Reader/ViewModel auf (MVVM, Invariante 4). |
| **Fenster-Kommunikation nur via EventBus** | `config/event_bus.py` – kein direktes Fenster-zu-Fenster-Wissen (Invariante 5). |
| **DbPool statt Direkt-Connections** | `db/db_pool.py` (thread-local). Fassade liegt in `repositories/db_service.py`; Root-`db_service.py` = Shim/Re-Export ohne Logik. |
| **Plugins sind Blätter** | `srv_*.py` / `ind_*.py` werden NIE importiert – Laden nur über Registry (`PluginRegistry`/`PluginLoader` in `feature_builder.py`). Neue Features = neue Datei, keine Kern-Datei anfassen (Open/Closed). |
| **Wanduhr-Garantie** | MT5-Epochs sind Berlin-Wanduhr-encoded. Chart/JS formatiert DIREKT, kein +2h/+1h-Offset. SQL nutzt `bar_time AT TIME ZONE 'UTC'`. |
| **Naming** | Services `srv_*` (in `analytics/features/definitions`), Indikatoren `ind_*` (in `chart/indicators`), `parameter_schema` am Dateianfang, `metadata["category"]` = Slash-Pfad. |
| **Tests** | Nur `test` (kein PyTest): `test/test.py`-Harness + `check_*.py`. Keine UI-/Regressionstests ohne ausdrückliche Anweisung. |

---

## Teil B – Domänen-Karte (Datei → Verantwortlichkeit)

### B1. App-Start & Lifecycle
| Datei | Zeilen | Verantwortlichkeit |
|---|---|---|
| `main.py` | 365 | Orchestrator: UI-Load, 45s-`sync_timer`, Tick-Dispatch (`on_ticks_ready`), LiveAnalyzer-Start, Exit-Vacuum, `--check-plugins` |
| `ui/window_manager.py` | 201 | Fenster-Lifecycle, Restore, Jump-to-Bar (kennt MainWindow NICHT) |
| `persistent_win.py` | 232 | `PersistentWindow`-Basis (Geometry/State-Save/Restore), `_open_windows`-Registry |
| `state_manager.py` | 588 | Persistence-Manager: App-Settings, Fenster-Geometrien, Schema-Migration, Symbol/TF-Reset |
| `config/app_settings.py` | 42 | `AppSettings`-DataClass (persistiert in app_data.duckdb) |
| `config/base_state_model.py` | 18 | `AbstractStateModel` (Serialisierung) |
| `config/event_bus.py` | 74 | **EventBus-Singleton**: `favorites_changed`, `profile_changed(str)`, `service_set_changed`, `mtf_fc_sort_changed(str)`, `service_run_started/finished`, `grabber_toggle(dict)`, `grabber_event(object)`, `sync_pause_count` |
| `scrollable_content.py` | 238 | `ContentScrollMixin` (Scroll/Größendynamik) |
| `ui/properties_win.py` | 123 | Properties-Fenster (App-Einstellungen + DB-Kompaktierung, Concurrency-Guard über `sync_pause_count`) |
### B2. DB-Basisschicht & Repositories (einzige SQL-Schicht)
| Datei | Zeilen | Verantwortlichkeit |
|---|---|---|
| `db/db_pool.py` | 177 | `DbPool` (thread-local, eine Verbindung pro Thread/DB), DB-Pfad-Konstanten, `with_db_lock` |
| `db/db_utils.py` | 112 | `_parse_json_field`, `_ensure_epoch` |
| `db/schema_initializer.py` | 225 | `check_and_init_databases` (market_data/analytics/app_data), DDL, Migrationen |
| `repositories/db_service.py` | 48 | Fassade/Re-Export-Wrapper (keine Logik mehr); Root-`db_service.py` = Shim |
| `repositories/market_data_repository.py` | 165 | Lese-Zugriff `ohlcv_bars`, `get_symbol_precision` |
| `repositories/grabber_repository.py` | 61 | Grabber-Ergebnis-Persistenz (18-Spalten-Batch-Upsert) |
| `repositories/symbol_repository.py` | 224 | `broker_symbols` (Symbole + Favoriten, MT5-Start-Sync) |
| `repositories/window_state_repository.py` | 272 | `window_instances`/`instance_state` (Fenster-Persistenz) |
| `repositories/analytics_profile_repository.py` | 371 | `analytics_profiles` (Profile für Analytics-UI) |
| `analytics/statistics_repository.py` | 192 | SQL-Aggregationen auf `feature_data` (srv_proximity) + Forward-Performance (legacy Statistik) |

### B3. MT5-Sync & Worker
| Datei | Zeilen | Verantwortlichkeit |
|---|---|---|
| `data_sync/mt5_sync_service.py` | 201 | MT5-Verbindung, Zeitrahmen, `sync_market_data` (Wanduhr-Encoding!), `MT5_LOCK` |
| `workers/data_sync_worker.py` | 33 | `DataSyncWorker` (Historie-Sync, QThread) |
| `workers/live_tick_worker.py` | 110 | `LiveTickWorker` (Tick-Polling, Bar-Close) |
| `analytics/background_workers/historical_scanner.py` | 146 | Batch-Scans über historische Daten |
| `analytics/background_workers/live_analyzer.py` | 240 | `LiveAnalyzer` (SILVER M1, Bar-Close-Evaluierung) |

### B4. Chart-Engine (Python-Seite)
| Datei | Zeilen | Verantwortlichkeit |
|---|---|---|
| `chart/chart_win.py` | 399 | **PyTraderChartWindow** (Kern): `__init__`, aggregiert 6 Mixins ⚠️HOTSPOT |
| `chart/chart_win_workers.py` | 153 | `ChartBridge`/`ChartDataSerializer`/`GridDataSerializer`/`OlderDataWorker`/`WebEngineConsolePage` |
| `chart/chart_win_indicators.py` | 330 | `ChartIndicatorMixin` (17): Indikator-/Grabber-Methoden, Settings |
| `chart/chart_win_refresh.py` | 233 | `ChartRefreshMixin` (8): Seiten-Load, Refresh |
| `chart/chart_win_render.py` | 244 | `ChartRenderMixin` (6): Render-/Serializer-Payload |
| `chart/chart_win_symboltf.py` | 298 | `ChartSymbolTfMixin` (12): Symbol/Timeframe/Live-Candle |
| `chart/chart_win_twotier.py` | 263 | `ChartTwoTierMixin` (9): Two-Tier-Caching, Warmup |
| `chart/chart_basics.py` | 81 | HTML-Template, `JS_FILES`-Ladereihenfolge |
| `chart/indicators/base_indicator.py` | 56 | `BaseIndicator` (ABC) |
| `chart/indicators/ind_moving_averages.py` | 446 | Multi-MA (8 MAs, selbstcontained) |
| `chart/indicators/ind_fixed_grid_proximity.py` | 797 | Grid-Indikator = visueller Adapter über `srv_grid_lines` + `srv_proximity` |
| `chart/indicators/ind_peak.py` | 890 | Peak-Grabber-Indikator (Live-State-Machine, Ringpuffer) ⚠️HOTSPOT (importiert `analytics.engine`) |
| `chart/indicators/utils/chart_data_buffer.py` | 302 | Two-Tier Tier-2-RAM-Puffer |
| `chart/indicators/utils/ma_template.py` | 490 | Generisches MA-Template (von Indikatoren UND Services genutzt) |
| `chart/overlays/style_models.py` | 141 | Overlay-Style-Modelle |
| `chart/widgets/mtf_filter_bar.py` | 376 | MTF-FC-Filterleiste (Source-TF, Overlay-TF, Agg-TF, Range-Picker, Tabellen-Sort) |
| `chart/widgets/named_item_actions.py` | 163 | `NamedItemActionsMixin` (Preset/Service-Set Verwaltung) |
| `chart/widgets/style_picker_widget.py` | 558 | Style-Picker |
| `chart/indicator_dialog.py` | 181 | **IndicatorSettingsDialog** (Kern): `__init__` + Klassen-Konstante `DIALOG_GEOMETRY_KEY`, aggregiert 7 Mixins |
| `chart/indicator_dialog_plugin.py` | 54 | `IndicatorSettingsDialogPluginMixin` (3): Plugin-/Engine-Zugriff (PluginRegistry, Repo, Evaluator) |
| `chart/indicator_dialog_schema.py` | 249 | `IndicatorSettingsDialogSchemaMixin` (7): Schema-/Precision-Helper, `create_schema_control` |
| `chart/indicator_dialog_ui.py` | 531 | `IndicatorSettingsDialogUiMixin` (7): UI-Aufbau (init_ui Legacy/Plugin/Params-only), Collapsible, Reflow, Control-Widget |
| `chart/indicator_dialog_sets.py` | 380 | `IndicatorSettingsDialogSetsMixin` (10): Service-Set-Liste/-Auswahl, Tooltip, Stack-Rebuild |
| `chart/indicator_dialog_run.py` | 364 | `IndicatorSettingsDialogRunMixin` (13): Set-Logik/Run, Set-CRUD, Run-Worker, Commit |
| `chart/indicator_dialog_presets.py` | 262 | `IndicatorSettingsDialogPresetsMixin` (8): Preset-Verwaltung, Params aus/in UI |
| `chart/indicator_dialog_geometry.py` | 66 | `IndicatorSettingsDialogGeometryMixin` (3): Geometrie-Restore/-Save, `done` |

### B5. Chart-Engine (JS-Seite – `chart/js`, Laden in chart_basics.JS_FILES)
| Datei | Zeilen | Verantwortlichkeit |
|---|---|---|
| `01_core.js` | 74 | Chart-Init, `window.onerror`, Zeit-Maps `_continuousTimeMap`/`_continuousKeys`, **`resolveRealTime(ts)`** (Binary-Search → nächster realer Zeitpunkt), `toCont`/`toReal` |
| `02_time_utils.js` | 103 | `getBerlinParts`/`formatDT` (Wanduhr-Direktformatierung, KEIN Berlin-Offset), Pause 23:00–23:59 (22:59→00:01), `formatDuration` |
| `03_chart_rendering.js` | 484 | Candle-Rendering, `DaySeparator` (echte Candle-Zeiten, keine Phantom-Slots), `renderLineSeries`/`renderMarkers`/`renderPriceLines`, `applyChartRenderPayload`, `applyFullChartUpdate`, Overlay-Guard `_overlayTimeBounds` |
| `04_live_updates.js` | 418 | `syncRanges`, `updateLiveCandle`, Tick-Formatierung, DaySeparator-Tag-Berechnung, Hooks an 06 |
| `05_measurement.js` | 353 | Messung (Abstand/Dauer/Text), `pyBridge.onMeasurementChanged` |
| `06_two_tier.js` | 252 | Two-Tier-Caching: Sliding Window (N=1000), `_maybeRequestOlderData` (Debounce 300ms), `applyOlderDataChunk` (Race-Guards, Prepend), `_isHistoryView`, Live-Button |

**pyBridge-Vertrag (Python ↔ JS):** `onRequestOlderData(fromEpoch,count,serial,winRight)`, `onJumpToLive()`, `onMeasurementChanged(payload)`, `onPriceRangeChanged(from,to)`. JS-Hooks: `_onFullChartUpdateApplied(data)`, `_onVisibleRangeChanged()`, `_isHistoryView()`.

### B6. Analytics-Engine (Business-Logik / ViewModel)
| Datei | Zeilen | Verantwortlichkeit |
|---|---|---|
| `analytics/engine/feature_store_reader.py` | 93 | **FeatureStoreReader** (Kern): `__init__`, aggregiert 6 Mixins, Re-Export aller 17 Konstanten + `canonical_tf_sort` |
| `analytics/engine/feature_store_reader_constants.py` | 141 | Konstanten (BASE_DIR, DB_ANALYTICS, TF_SECONDS, DOW_LABELS, DIM_MAPPINGS, …) + `canonical_tf_sort` |
| `analytics/engine/feature_store_reader_meta.py` | 207 | `FeatureStoreMetaMixin` (8): Meta-Cache, Connection, Epoch |
| `analytics/engine/feature_store_reader_filter.py` | 305 | `FeatureStoreFilterMixin` (9): Normalisierung, Filter, Formatierung |
| `analytics/engine/feature_store_reader_query.py` | 479 | `FeatureStoreQueryMixin` (8): Row-/Column-/Key-Fetch, Verfügbarkeitslisten |
| `analytics/engine/feature_store_reader_heatmap.py` | 492 | `FeatureStoreHeatmapMixin` (4): Heatmap-Fetch (klassisch + generisch) |
| `analytics/engine/feature_store_reader_ohlcv.py` | 637 | `FeatureStoreOhlcvMixin` (11): OHLCV-Snapshots, Execution-Dates/Hashes, TF-Status |
| `analytics/engine/feature_store_reader_plugin.py` | 464 | `FeatureStorePluginMixin` (5): No-Data-Varianten, Proximity/Plugin-Records, exists |
| `analytics/engine/analytics_repository.py` | 780 | High-Level-Lese-Datenmethoden für Analytics-UI |
| `analytics/engine/analytics_view_model.py` | 225 | **AnalyticsViewModel** (Kern): `__init__` + 11 Signale, aggregiert 6 Mixins, Re-Export der Konstanten |
| `analytics/engine/analytics_view_model_constants.py` | 30 | Konstanten (DEBOUNCE_MS, DEFAULT_BINS, DEFAULT_LIMIT, _ALL_QUERIES) |
| `analytics/engine/analytics_view_model_query.py` | 253 | `AnalyticsViewModelQueryMixin` (18): Tabellen-/Daten-Abfragen |
| `analytics/engine/analytics_view_model_setters.py` | 180 | `AnalyticsViewModelSetterMixin` (9): Setter/State-Sync |
| `analytics/engine/analytics_view_model_fields.py` | 244 | `AnalyticsViewModelFieldMixin` (9): Feld-Auswahl/Sortierung |
| `analytics/engine/analytics_view_model_heatmap.py` | 296 | `AnalyticsViewModelHeatmapMixin` (17): Heatmap-Config/Metriken |
| `analytics/engine/analytics_view_model_profile.py` | 427 | `AnalyticsViewModelProfileMixin` (13): Profile/Presets/Workspace |
| `analytics/engine/analytics_view_model_resolve.py` | 586 | `AnalyticsViewModelResolveMixin` (20): Auflösung/Normalisierung |
| `analytics/engine/analytics_worker.py` | 263 | `AnalyticsAsyncWorker` (QThread-Query) |
| `analytics/engine/service_models.py` | 143 | `ServiceSetDefinition` TypedDicts (JSON-persistiert) |
| `analytics/engine/service_set_repository.py` | 433 | `service_sets`-Tabelle (Laden/Speichern) |
| `analytics/engine/set_evaluator.py` | 351 | `ServiceSetEvaluator`: führt Sets in `execution_order` über PluginExecutor aus |
| `analytics/engine/service_selector_model.py` | 839 | Lesendes Datenmodell Service/Set-Hierarchie ⚠️HOTSPOT (importiert `chart.indicators` + `serviceui`) |
| `analytics/engine/tree_builder.py` | 473 | Rekursiver Baumaufbau + Kategorie-Auflösung |
| `analytics/engine/schema_migrator.py` | 123 | Schema-Migration für Service-Sets (SemVer) |
| `analytics/engine/description_dialog.py` | 313 | ServiceDescriptionDialog |
| `analytics/engine/peak_models.py` | 74 | Peak-Grabber Dataclasses/Enums/Configs |
| `analytics/engine/peak_backtest_runner.py` | 143 | Serientests/Backtest-Orchestrierung (headless) |
| `analytics/engine/mtf_fc_state.py` | 75 | MTF-FC: `shared_state["mtf_fc"]`-Namespace (Single Source of Truth) |
| `analytics/engine/mtf_fc_provider.py` | 157 | MTF-FC: Data Provider + Cache-Versionierung (liest `ohlcv_bars`) |
| `analytics/engine/mtf_fc_boundary.py` | 104 | MTF-FC: Boundary Policy (`native`/`fallback`), M1-Verfügbarkeitsgrenze |
| `analytics/engine/mtf_fc_cascade.py` | 147 | MTF-FC: Hysterese-Kaskaden-Engine (M1→M5→H1→H4→D1) |
| `analytics/engine/mtf_fc_confluence.py` | 109 | MTF-FC: Confluence-Gewichtung/-Normalisierung |
| `analytics/engine/mtf_fc_guards.py` | 131 | MTF-FC: State-Machine & Prioritäts-Kette (Guards) |
| `analytics/engine/mtf_fc_partition.py` | 56 | MTF-FC: Event-Partitionierung + Cache-Invalidierung |
| `analytics/engine/mtf_fc_templates.py` | 136 | MTF-FC: View-Template-Persistenz (pure Logik) |

### B7. Analytics-UI
| Datei | Zeilen | Verantwortlichkeit |
|---|---|---|
| `analytics/ui/analytics_win.py` | 1500 | **AnalyticsWindow**: Hauptfenster, Profil-Verwaltung, Jump-to-Chart ⚠️HOTSPOT (3× importiert `serviceui`) |
| `analytics/ui/common.py` | 225 | `format_wanduhr_time`, Overlay-Stack-Helfer |
| `analytics/ui/heatmap_widget.py` | 424 | **HeatmapWidget** (Kern): `__init__` + Signal `preset_clicked`, aggregiert 6 Mixins, Re-Export der 15 Konstanten + `_HeatmapAxis` |
| `analytics/ui/heatmap_widget_constants.py` | 86 | Konstanten (_CONFLUENCE_*, _VIRIDIS, _VALUE_AGGS, _TF_SECONDS, _DIM_LABELS, _AGG_LABELS) |
| `analytics/ui/heatmap_widget_axis.py` | 333 | `_HeatmapAxis` (9): dynamische Achse (LWC-v5-Ticks) + 3 Tick-Helper |
| `analytics/ui/heatmap_widget_controls.py` | 344 | `HeatmapWidgetControlsMixin` (11): Config-Sync, Combos, Slider, Modus-Sync + `_is_price_like_key` |
| `analytics/ui/heatmap_widget_fields.py` | 432 | `HeatmapWidgetFieldMixin` (10): Feld-Auswahl/Dropdown, Checked-Pairs, VM-Sync |
| `analytics/ui/heatmap_widget_zoom.py` | 167 | `HeatmapWidgetZoomMixin` (10): Zoom-Slider X/Y, Range-Apply, Achsen-Bounds |
| `analytics/ui/heatmap_widget_data.py` | 512 | `HeatmapWidgetDataMixin` (10): Daten-Anfrage/-Empfang, Render-Generic, No-Data |
| `analytics/ui/heatmap_widget_overlay.py` | 273 | `HeatmapWidgetOverlayMixin` (6): Candle-Overlay, Preis-View, Grid-Linien |
| `analytics/ui/heatmap_widget_info.py` | 305 | `HeatmapWidgetInfoMixin` (6): Info-Zeile, Maus-Tracking, Zell-Info, Legende + 2 Format-Helper |
| `analytics/ui/heatmap_page.py` | 288 | Heatmap-Seite (Dow×Stunde) |
| `analytics/ui/table_page.py` | 732 | Tabellen-Seite (Doppelklick → Jump-to-Chart) |
| `analytics/ui/scatter_page.py` | 151 | Scatter-Seite |
| `analytics/ui/distribution_page.py` | 137 | Histogramm-Seite |
| `analytics/ui/equity_page.py` | 41 | Platzhalter (keine Datenquelle) |
| `analytics/ui/order_preview_dialog.py` | 31 | Order-Preview (Grabber-Event) |

### B8. Service-UI
| Datei | Zeilen | Verantwortlichkeit |
|---|---|---|
| `serviceui/service_win.py` | 946 | **ServiceWindow** (Kern): `__init__` + Orchestrierung, aggregiert 5 Mixins ⚠️HOTSPOT |
| `serviceui/service_win_editor.py` | 802 | `ServiceEditorMixin` (23): Parameter-/Set-Editor, Plugin-Config |
| `serviceui/service_win_presets.py` | 791 | `ServicePresetMixin` (18): Presets/Varianten/Doc-Log, Purge |
| `serviceui/service_win_run.py` | 516 | `ServiceRunMixin` (17): Run-Worker, Sync-Guard, Fortschritt |
| `serviceui/service_win_sets.py` | 373 | `ServiceSetsMixin` (9): Set-Verwaltung (CRUD, Verschieben) |
| `serviceui/service_win_tree.py` | 259 | `ServiceTreeMixin` (9): MasterTree-Handler (Selection, Ordner, Kategorien) |
| `serviceui/master_tree.py` | 318 | **MasterTree** (Kern): `__init__`, aggregiert 6 Mixins, Re-Export der Konstanten |
| `serviceui/master_tree_constants.py` | 167 | Konstanten (TYPE_*, ROLE_*, MIME_*) + `TreeItemIterator` |
| `serviceui/master_tree_ui.py` | 298 | `MasterTreeUiMixin` (9): UI-Aufbau, Spalten, Badge-Zellen |
| `serviceui/master_tree_selection.py` | 139 | `MasterTreeSelectionMixin` (8): Auswahl/Selection-Details |
| `serviceui/master_tree_events.py` | 499 | `MasterTreeEventsMixin` (6): Kontextmenü-Signale, Klick-Events |
| `serviceui/master_tree_dragdrop.py` | 275 | `MasterTreeDragDropMixin` (9): Drag&Drop, MIME-Handling |
| `serviceui/master_tree_build.py` | 717 | `MasterTreeBuildMixin` (16): Baumaufbau, Checkbox-Tri-State |
| `serviceui/master_tree_checks.py` | 524 | `MasterTreeChecksMixin` (10): Checkbox-Logik, checked_items |
| `serviceui/service_selector_dialog.py` | 414 | **ServiceSelectorDialog** (Kern): `__init__` + 4 Signale, aggregiert 6 Mixins, Re-Export der 4 Konstanten + `_DialogParamHost` |
| `serviceui/service_selector_dialog_constants.py` | 22 | Konstanten (DIALOG_GEOMETRY_KEY, PANEL_BUFFER, BODY_SPACING, TREE_DEFAULT_WIDTH) |
| `serviceui/service_selector_dialog_host.py` | 217 | `_DialogParamHost` (8): Param-Panel-Host, Speichern-Button |
| `serviceui/service_selector_dialog_selection.py` | 198 | `ServiceSelectorDialogSelectionMixin` (10): Filter/Apply, Info-Dialoge |
| `serviceui/service_selector_dialog_presets.py` | 468 | `ServiceSelectorDialogPresetMixin` (12): Varianten/Presets, Duplizieren, Purge |
| `serviceui/service_selector_dialog_sets.py` | 336 | `ServiceSelectorDialogSetMixin` (13): Set-/Ordner-CRUD, Move/Remove |
| `serviceui/service_selector_dialog_run.py` | 529 | `ServiceSelectorDialogRunMixin` (18): Checkbox-Filter, Run-Worker, Fortschritt |
| `serviceui/service_selector_dialog_badge.py` | 222 | `ServiceSelectorDialogBadgeMixin` (7): closeEvent, TF-Pills, Modell-Refresh |
| `serviceui/service_selector_dialog_panel.py` | 388 | `ServiceSelectorDialogPanelMixin` (12): Param-Panel, Splitter, Geometrie |
| `serviceui/service_selector_widget.py` | 198 | Generisches Auswahl-Widget (Modus A SELECT_ONLY / Modus B) |
| `serviceui/param_columns.py` | 891 | `ServiceParamColumnsMixin` (dynamische Service-Spalten) |
| `serviceui/run_worker.py` | 368 | `ServiceRunWorker` (gezielte Service-Ausführung) |
| `serviceui/service_set_utils.py` | 420 | Helfer (`EMPTY_FOLDERS_KEY`, Set-Hash, Kopier-Logik) |
| `serviceui/common_widgets.py` | 162 | `TfStatusBadgeBar` u. a. |
| `serviceui/status_panel.py` | 73 | Status-/Log-Panel (reines Anzeige-Widget) |
| `serviceui/symbols_win.py` | 133 | SymbolsWindow (Symbole + Favoriten-Toggle) |
| `serviceui/new_set_dialog.py` | 60 | Dialog „Neues Service-Set" |
| `serviceui/trash_dialog.py` | 215 | Papierkorb (Soft-Delete, doppelte Sicherheitsabfrage) |

### B9. Feature-/Service-Plugins (Registry-geladen, Blätter)
| Datei | Zeilen | Verantwortlichkeit |
|---|---|---|
| `analytics/features/base_feature.py` | 48 | `BaseFeature` (ABC für Feature-Store-Features) |
| `analytics/features/feature_builder.py` | 829 | `FeatureBuilder` (OHLCV laden → Features berechnen → Bulk-Upsert) + `PluginRegistry`/`PluginLoader`/`PluginExecutor` |
| `analytics/features/plugins/base_plugin.py` | 316 | Plugin-Basisklasse (ZUSTANDSLOS), `PluginContext`, `shared_state` |
| `analytics/features/definitions/srv_grid_lines.py` | 367 | Grid-Linien-Raster (Parität zu Alt-Grid) |
| `analytics/features/definitions/srv_proximity.py` | 386 | %-Proximity zu Grid-Linien (liest `depends_on`-Linien) |
| `analytics/features/definitions/srv_swing_structure.py` | 604 | Fraktale, Pivots, Gann Swings, PDH/PWH, ZigZag |
| `analytics/features/definitions/srv_swing_momentum.py` | 521 | Richtungswechsel via MA-Hysteresen, Trailing-Stops ⚠️HOTSPOT (importiert `chart`) |
| `analytics/features/definitions/srv_swing_volume_profile.py` | 659 | POC/VAH/VAL, LVNs, Anchored VWAP |
| `analytics/features/definitions/srv_trend_regime.py` | 532 | Statistische Trend-Regimes ⚠️HOTSPOT (importiert `chart`) |
| `analytics/features/definitions/srv_trend_breakout.py` | 492 | ATR-Trailings, Supertrend, Donchian/Keltner ⚠️HOTSPOT (importiert `chart`) |
| `analytics/features/definitions/srv_trend_hma_pivot.py` | 418 | HMA/EHMA-Pivot-Detektor ⚠️HOTSPOT (importiert `chart`) |
| `analytics/features/definitions/srv_peak_finder.py` | 169 | Peak-Finder (Yellow-Mode) |
| `analytics/features/definitions/srv_peak_grabber.py` | 211 | Peak-Grabber-Service |
| `analytics/features/definitions/grabber_kernel.py` | 99 | Numba/NumPy State-Machine (B2/B3/B6) |
| `analytics/features/definitions/grid_levels.py` | 168 | Grid-Levels Feature (Y-Achse) + Zeitfenster-Flags |
| `analytics/features/definitions/grid_math.py` | 68 | Paritäts-Mathematik Grid (eingefrorene Referenz) |
| `analytics/features/definitions/atr_normalized.py` | 33 | Feature ATR-normalisiert |
| `analytics/features/definitions/ema_diff.py` | 24 | Feature EMA-Differenz |

### B10. Legacy
| Datei | Zeilen | Verantwortlichkeit |
|---|---|---|
| `ui/statistic_win.py` | 279 | Statistik-Fenster (legacy, von AnalyticsWindow abgelöst) |

---

## Teil C – Bug-Routing-Tabelle (Symptom → Dateien in Lese-Reihenfolge)

> **Regel:** Nur die genannten Dateien lesen. Steht die Datei nicht in der Zeile, ist sie für das Symptom irrelevant.

| # | Symptom-Bereich | Dateien (Lese-Reihenfolge) | Validierung in `test` |
|---|---|---|---|
| 1 | Chart-Zeiten/Labels/Pause falsch | `chart/js/02_time_utils.js` → `chart/js/01_core.js` → `chart/js/04_live_updates.js` → `chart/chart_win.py` → `chart/chart_win_symboltf.py` (Live-Candle) | `check_time_utils.js`, `check_resolve_realtime.js` |
| 2 | Chart-Rendering/Overlays/Linien/Marker | `chart/js/03_chart_rendering.js` → `chart/js/04_live_updates.js` → `chart/chart_win_render.py` (Render-Payload) → `chart/chart_win.py` → betroffener `chart/indicators/ind_*.py` | `check_2201h_overlay_guard.js`, `check_2201c_overlay_clearing.js`, `check_mtf_axis.js` |
| 3 | Chart-Crash „Value is null" / Phantom-Slots / Timescale | `chart/js/03_chart_rendering.js` → `chart/js/06_two_tier.js` (Overlay-Guard) → `chart/js/01_core.js` (Maps) → `chart/chart_win_render.py` | `diag_lwc_crash.js`, `diag_prod_repro.js`, `check_2201h_bounds.py` |
| 4 | Live-Ticks / Live-Update / Bar-Close | `workers/live_tick_worker.py` → `main.py` (`on_ticks_ready`/`_dispatch_tick_map`) → `chart/chart_win_symboltf.py` (`update_live_candle`) → `chart/js/04_live_updates.js` | `check_2201g_live_marker.py` |
| 5 | Nachladen alter Daten (Two-Tier, Scroll nach links) | `chart/js/06_two_tier.js` → `chart/indicators/utils/chart_data_buffer.py` → `chart/chart_win_twotier.py` (Warmup/Feeds) → `chart/chart_win_workers.py` (OlderDataWorker) | `check_2201h_pipeline.py` |
| 6 | MT5-Sync / Historie / M1-Konsistenz | `data_sync/mt5_sync_service.py` → `workers/data_sync_worker.py` → `db/schema_initializer.py` → `repositories/market_data_repository.py` | `check_m1_consistency.py`, `check_broker_tz.py`, `check_mt5_m1_boundary.py`, `check_21322_full_sync.py` |
| 7 | Service-Ausführung / Set-Run / Fehler im Run | `serviceui/run_worker.py` → `analytics/engine/set_evaluator.py` → `analytics/features/feature_builder.py` (PluginExecutor) → `analytics/features/plugins/base_plugin.py` → betroffenes `srv_*.py` | `check_2201_runner.py` |
| 8 | Service-Sets speichern/laden/löschen/Papierkorb | `analytics/engine/service_set_repository.py` → `analytics/engine/service_models.py` → `serviceui/service_set_utils.py` → `serviceui/trash_dialog.py` | `check_bugfix_2132*.py` |
| 9 | MasterTree (Anzeige, Kategorien, Modi, Kontextmenü) | `serviceui/master_tree.py` → `analytics/engine/service_selector_model.py` → `analytics/engine/tree_builder.py` → `srv_*.py` (`metadata["category"]`) | `check_tree_mode_fix.py`, `check_tree_mode_fix2.py`, `check_modes_registry.py` |
| 10 | Parameter-Editor / Prop-Fenster / Expert-Modus | `chart/indicator_dialog.py` (Kern) → `chart/indicator_dialog_plugin/schema/ui/sets/run/presets/geometry.py` → `serviceui/param_columns.py` → `chart/widgets/named_item_actions.py` | `check_clone_*.py`, `check_plugin_names.py` |
| 11 | Analytics-Daten falsch/leer (Heatmap/Table/Scatter/Distribution) | `analytics/engine/feature_store_reader.py` + Mixins (`feature_store_reader_query.py` / `_ohlcv.py` / `_heatmap.py` / `_filter.py`) → `analytics/engine/analytics_repository.py` → `analytics/engine/analytics_view_model.py` → `analytics/engine/analytics_worker.py` → UI-Page | `check_heatmap_e2e.py`, `check_field_selection.py`, `check_field_pairs_db.py`, `check_mode_filter_*.py` |
| 12 | Analytics-Fenster (Layout, Profile, Buttons, Jump-to-Chart) | `analytics/ui/analytics_win.py` → `analytics/engine/analytics_view_model.py` (Profile) → `repositories/analytics_profile_repository.py` | `check_custom_range_sortmode.py`, `check_heatmap_page_stack.py` |
| 13 | Heatmap-Widget (Zoom, Matrix, Overlay, Achsen) | `analytics/ui/heatmap_widget.py` (Kern) → `analytics/ui/heatmap_widget_controls/fields/zoom/data/overlay/info.py` + `heatmap_widget_axis.py` → `analytics/ui/heatmap_page.py` → `analytics/engine/analytics_view_model.py` (Config) | `check_heatmap_render.py`, `check_heatmap_field_checks.py` |
| 14 | MTF-FC (Filterleiste, Kaskade, Confluence, Sortierung) | `chart/widgets/mtf_filter_bar.py` → `analytics/engine/mtf_fc_state.py` → `analytics/engine/mtf_fc_provider.py` → `mtf_fc_guards.py` → `mtf_fc_cascade.py` → `mtf_fc_confluence.py` → `mtf_fc_boundary.py` → `mtf_fc_templates.py` → `mtf_fc_partition.py` | `check_analytics_mtffc.py`, `check_analytics_mtffc_win.py`, `check_mtf_sort_binding.py`, `check_filterbar_visible.py` |
| 15 | Peak-Grabber (komplett) | `analytics/engine/peak_models.py` → `analytics/features/definitions/grabber_kernel.py` → `srv_peak_finder.py` → `srv_peak_grabber.py` → `chart/indicators/ind_peak.py` → `repositories/grabber_repository.py` → `analytics/engine/peak_backtest_runner.py` → `analytics/ui/order_preview_dialog.py` | `check_2201_peak_grabber.py`, `check_2201_runner.py`, `check_2201_reader.py`, `check_2201_schema.py`, `check_2201_viewback.py`, `check_2201_parity.py` |
| 16 | Fenster-Persistenz (Geometrie/State verloren, Restore) | `persistent_win.py` → `repositories/window_state_repository.py` → `state_manager.py` → `ui/window_manager.py` | `check_app_state.py`, `check_splitter_persist.py`, `check_2201f_state_sync.py` |
| 17 | App-Einstellungen / Properties-Fenster | `config/app_settings.py` → `ui/properties_win.py` → `state_manager.py` | `check_app_state.py` |
| 18 | Symbole / Favoriten | `repositories/symbol_repository.py` → `serviceui/symbols_win.py` → `main.py` (Start-Sync) | – |
| 19 | Sync-Timer / Concurrency-Guard / DB-Kompaktierung | `main.py` (`sync_timer`, `_sync_pause_count`) → `config/event_bus.py` (`service_run_started/finished`, `sync_pause_count`) → `ui/properties_win.py` | – |
| 20 | DB-Bloat / Vacuum / Schema / Migration | `db/schema_initializer.py` → `db/db_pool.py` → `db/db_utils.py` → `main.py` (Exit-Vacuum) → `ui/properties_win.py` (Button) | `check_2201_schema.py` |
| 21 | Statistik-Fenster (legacy) | `ui/statistic_win.py` → `analytics/statistics_repository.py` | – |
| 22 | **NEUES Service-Plugin / Feature / Indikator** | NUR neue Datei in `analytics/features/definitions` bzw. `chart/indicators` + `parameter_schema` + `metadata["category"]`. Keine Kern-Datei anfassen. | `check_plugin_names.py` |
| 23 | EventBus-Kommunikation (Event fehlt/doppelt) | `config/event_bus.py` (Signal-Definition) + per `.connect(`/`.emit(` im Code die Emitter/Subscriber finden | – |
| 24 | App-Start / Exit (Worker stoppen, DB-Pflege) | `main.py` (kompletter Lifecycle) | `check_21322_full_sync.py` |
| 25 | Datenquellen-Picker (Service-Auswahl, Varianten, Sets verwalten) | `serviceui/service_selector_dialog.py` → `serviceui/service_selector_dialog_selection.py` / `_presets.py` / `_sets.py` / `_run.py` / `_badge.py` / `_panel.py` → `serviceui/service_selector_dialog_host.py` → `analytics/ui/analytics_win.py` | – |

---

## Teil D – Bekannte Hotspots & God-Files (kein Code anfassen ohne Not)

### D1. Quer-Kopplungen (⚠️ – Bugs hier involvieren IMMER mehrere Schichten)
| Hotspot | Richtung | Bedeutung |
|---|---|---|
| `chart/chart_win.py` | → `serviceui.symbols_win`, `analytics.ui.order_preview_dialog`, `analytics.engine.service_set_repository` | Chart kennt Service-UI & Analytics-Engine direkt (Grabber-Pipeline). |
| `analytics/ui/analytics_win.py` | → 3× `serviceui` | Analytics-Fenster nutzt Service-Auswahl direkt. |
| `analytics/engine/service_selector_model.py` | → `chart.indicators.ind_fixed_grid_proximity`, `serviceui.service_set_utils` | Engine → UI/Chart (Layer-Verletzung, historisch gewachsen). |
| `chart/indicators/ind_peak.py` | → `analytics.engine` (peak_models, feature_builder, set_evaluator, plugins.base_plugin) | Indikator nutzt Engine direkt (Grabber). |
| `analytics/features/definitions/srv_trend_*.py`, `srv_swing_momentum.py` | → `chart` (ma_template) | Services importieren Chart-Utils. |
| `serviceui/service_win.py` | → `chart`, `analytics`, `repositories`, `workers`, `scrollable_content`, `repositories.symbol_repository` | Der Orchestrator berührt alle Schichten. |
| `analytics/features/feature_builder.py` | → `state_manager` | Feature-Layer → State-Layer. |

### D2. God-Files (Split-Kandidaten – Ziel Ø 150–400 Zeilen, 1 Verantwortlichkeit)
| Datei | Zeilen | Vorschlag |
|---|---|---|
| ~~`serviceui/service_win.py`~~ | ~~3.264~~ | ✅ GESPLITTET (23.04, 15.08.2026) → 5 Mixins (Teil B8) |
| ~~`serviceui/master_tree.py`~~ | ~~2.511~~ | ✅ GESPLITTET (23.06, 15.08.2026) → 6 Mixins + constants (Teil B8) |
| ~~`serviceui/service_selector_dialog.py`~~ | ~~2.414~~ | ✅ GESPLITTET (23.08, 15.08.2026) → 6 Mixins + constants + host (Teil B8) |
| ~~`analytics/ui/heatmap_widget.py`~~ | ~~2.656~~ | ✅ GESPLITTET (23.09, 15.08.2026) → 6 Mixins + constants + axis (Teil B7) |
| ~~`analytics/engine/feature_store_reader.py`~~ | ~~2.410~~ | ✅ GESPLITTET (23.05, 15.08.2026) → 6 Mixins + constants (Teil B6) |
| ~~`chart/indicator_dialog.py`~~ | ~~1.867~~ | ✅ GESPLITTET (23.10, 15.08.2026) → 7 Mixins (Teil B4) |
| ~~`analytics/engine/analytics_view_model.py`~~ | ~~1.886~~ | ✅ GESPLITTET (23.07, 15.08.2026) → 6 Mixins + constants (Teil B6) |
| ~~`chart/chart_win.py`~~ | ~~1.630~~ | ✅ GESPLITTET (23.03, 15.08.2026) → 6 Mixins (Teil B4) |

> **Split-Regel (inkrementell, kein Big-Bang):** Nur Dateien splitten, die für einen Bugfix ohnehin geöffnet werden. Mixins-Herausziehen folgt dem bestehenden Muster (`ServiceParamColumnsMixin`, `ContentScrollMixin`, `NamedItemActionsMixin`).

---

## Teil E – Wartung dieser Karte (HARTE REGEL)

> **Pflicht, keine Empfehlung:** Bei JEDER der folgenden Aktionen MUSS die Map im selben Arbeitsschritt aktualisiert werden. Ein Split, eine neue Datei, eine Verschiebung oder eine Routing-Änderung OHNE Map-Update ist unvollständig und wird nicht committet.

1. **Split einer God-File (Muss, VORHER + NACHHER):**
   * VOR dem Split: betroffene Teil-B-Zeile notieren, alle Teil-C-Routing-Zeilen identifizieren, die diese Datei nennen, Zielgruppen/Dateinamen festlegen.
   * NACH dem Split: Teil B aktualisieren (neue Mixin-/Support-Dateien mit Zeilen + 1-Zeilen-Verantwortlichkeit eintragen, Zeilenzahl der Hauptdatei korrigieren), Teil C (alle betroffenen Routing-Zeilen zeigen auf die neuen Dateien), Teil D2 (Kandidat als erledigt markieren/entfernen, Zeilenzahlen der verbleibenden Kandidaten neu auszählen).
2. **Neue Datei** (Mixin, Worker, Repository, Plugin, Indikator, Utils): In Teil B der passenden Domäne eintragen (Datei, Zeilen, 1-Zeilen-Verantwortlichkeit). Plugins/Indikatoren zusätzlich in Teil B9 prüfen (Naming `srv_`/`ind_`).
3. **Neuer Bug-Bereich / neues Routing:** In Teil C neue Routing-Zeile ergänzen (Symptom → Dateien in Lese-Reihenfolge → Test-Validator).
4. **Datei-Verschiebung / -Umbenennung** (z. B. Root-Orphans): Teil-B-Pfade + ALLE betroffenen Routing-Zeilen in Teil C aktualisieren.
5. **Zeilenzahlen:** Nach jedem Split/Update neu auszählen – sie steuern die Token-Erwartung der KI und müssen aktuell bleiben.
6. **Commit-Regel:** Das Map-Update gehört in den Split-Commit (oder direkt in den unmittelbar folgenden Commit – nie erst später).
7. **Ziel:** Diese Map ersetzt das Volltext-Suchen. Ein Bugfix-Prompt beginnt IMMER mit: *„Lies Architektur_map.md (Projekt-Root), dann nur die Dateien aus Zeile #X."*
