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