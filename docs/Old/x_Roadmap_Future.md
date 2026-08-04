---

# ZUKÜNFTIGE PHASEN (Post-Phase 14 / Separates Dokument)

Die folgenden Themen sind für den schnellen operative Einsatz der App nicht zwingend erforderlich. Sie wurden aus dem Implementierungsumfang von Phase 14 herausgelöst und für spätere Erweiterungsphasen reserviert.

---

### Modul Z-01 (ehemals 3.6): Visueller Node-Editor für Service-Pipelines

#### A. Zielsetzung & Abgrenzung

* Grafische Aufbereitung von Service-Abhängigkeiten als Knoten-Netzwerk (Node Graph) mittels `QGraphicsScene` / `QGraphicsItem`.


* **Grund für Verschiebung:** Die listenbasierte Verwaltung in `service_win.py` deckt alle Anforderungen ab. Ein Node-Editor bietet rein visuellen Zusatzkomfort, verändert jedoch nicht das zugrundeliegende Ausführungs-JSON.



#### B. Technisches Konzept

1. **Visual Graph:** `ServiceNodeItem` mit Ports für `depends_on`-Verbindungen.


2. **Bidirektionale Synchronisation:** Das visuelle Netzwerk dient lediglich als alternative Ansicht auf dasselbe `ServiceSetDefinition`-JSON.



---

### Modul Z-02 (ehemals 3.7): Prozessweiter Asynchroner EventBus

#### A. Zielsetzung & Abgrenzung

* Vollständige Entkopplung der Systemkomponenten über ein Publish/Subscribe Event-System.


* **Grund für Verschiebung:** Das bestehende PySide6-Signals/Slots-System verarbeitet Thread-Übergänge (Worker zu GUI) bereits stabil. Die Einführung eines globalen EventBus birgt kurzfristig Over-Engineering-Risiken.



#### B. Technisches Konzept

1. **EventBus Engine:** Thread-sicherer Singleton mit `subscribe()`, `unsubscribe()` und `publish()`.


2. **Event Typen:** `ServiceSetExecutedEvent`, `PluginReloadedEvent`, `LiveSignalDetectedEvent`.


Others Topics -

- optional 24/7 background service for closed charts (same interface as manual trigger) — would keep statistics data fresh without user action.
- ONNX as future option: native lightgbm/xgboost Python APIs for the initial phase; the inference classes may later transparently switch to `onnxruntime` (no app/signal-set changes needed).
- working out existing structure:
  `analytics/signals/machine_learning/` contains two fully implemented inference signals (both inherit SignalDefinition from analytics/engine/base_definition.py):

  | Object | signal_id | Model loading | Params |
  |---|---|---|---|
  | LightGBMSignal (lightgbm_signal.py) | lightgbm_v1 | lgb.Booster(model_file=...) (.txt) | model_file, feature_columns, threshold (0.5) |
  | XGBoostSignal (xgboost_signal.py) | xgboost_v1 | xgb.XGBClassifier().load_model() (.json) | same schema |

- überwachung von live charts nach meinen anweisungen mit diversen Alarmen und ggf. autom. Traden

- code signale entfernen, wenn wir sie nicht zur Darstellung von Services gebrauchen können

- Feature-Store-vs.-Cache-Kette (`Plugin → shared_state → feature_store → Indicator`) | ⚠️ **Teil-Delta** | Kette existiert grundsätzlich. Aber: (a) Konzeptname **„EvaluationContext" existiert nicht als Klasse** – nur Kommentare in `live_analyzer.py`, `set_evaluator.py`, `feature_builder.py` erwähnen ihn; die reale Klasse heißt `PluginContext`. (b) Der Indikator **ruft sehr wohl Plugins direkt auf** (Fallback, s. Invariante 10). |
- Versionierung & Schema (SemVer; `api_version`; `schema_version` in Payloads) | ⚠️ **teilweise** | `api_version` ✅ (`PluginMetadata`, Default „1"). SemVer + `SchemaMigrator` ✅ (`schema_migrator.py`, Patch löst keine Migration aus). **Lücke:** `schema_version` wird nur vom `ProximityService` in `metadata` geschrieben; das `FeatureStorePayload`-TypedDict (`base_plugin.py`) hat **kein** `schema_version`-Feld; das Alt-Plugin `grid_liquidity` (`definitions/grid_liquidity.py`) schreibt nur `plugin_version`. |
- Thread Safety über explizite Thread-Locks | ⚠️ **Formulierung** | Registry/Evaluator haben RLocks ✅. **Aber:** Der DB-Zugriff ist bewusst **lock-frei** über Thread-local `DbPool` (Thread-local Singleton, `db_service.py` Z. 85–115: „Threading-Locks sind hier kontraproduktiv"). Die Invarianten-Formulierung „explizite Thread-Locks" entspricht nicht dem Ist-Design. |

- Chart-Entkopplung (Chart rechnet nie, liest nur vorberechnete Daten) | ⚠️ **teilweise** | Primärpfad ✅: `grid_liquidity.read_proximity_from_feature_store()` liest `feature_store`. **Aber:** `grid_liquidity.calculate()` führt weiterhin die komplette Service-Pipeline im Chart aus (`ServiceSetEvaluator.execute_set`, Fallback bei leerem Store). „Der Indicator ruft niemals direkt Plugins zur Neuberechnung auf" ist damit **nicht vollständig** erreicht. |
