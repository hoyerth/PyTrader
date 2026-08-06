---

# ZUKÜNFTIGE PHASEN (Post-Phase 14 / Separates Dokument)

Die folgenden Themen sind für den schnellen operative Einsatz der App nicht zwingend erforderlich. Sie wurden aus dem Implementierungsumfang von Phase 14 herausgelöst und für spätere Erweiterungsphasen reserviert.

---


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


- ## ANALYTICS NACHGELAGERTE ARBEITEN (ERST SPÄTER IMPLEMENTIERT)


- Multiservice Darstellung in Analytics mit Legenden auf den Graphics
- Analytics Service Parameter editierbar (What-If, in-memory calculation) -  ggf. auch persistieren und in Chart_win

1. **Exporte:** Export von gefilterten Daten und Matrizen als CSV, Excel oder PNG/SVG-Grafik.
2. **Multi-Symbol und Multi-Timeframe:** Gezielter Vergleich mehrerer Symbole/Timeframes nebeneinander in einer Matrix oder Kurve.
3. **Massentests & Parameter-Optimierung:** Automatische Parameter-Sweeps über verschiedene Zeiträume, Service-Parameter und ML-Variablen.
4. **Aktive ML-Inferenz:** In Phase 15 wird ML noch nicht aktiv eingebunden; die bestehenden Profil-Strukturen (`"ml_models"` im JSON-Payload) bleiben rein vorbereitend vorhanden.
6. **VectorBT: ** Einsatz prüfen für Massentests und Matrix-Analysen - Als Engine im analytics_worker.py für blitzschnelle N-Bar Outcomes, Heatmaps & Indikator-Sweeps.