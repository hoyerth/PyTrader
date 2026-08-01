# Konzept Phase 13: Service- & Plugin-Architektur 

## 1. Abgrenzung: Phase 13 vs. Phase 14

Um die Komplexität beherrschbar zu halten und die Stabilität zu garantieren, wird der Scope strikt getrennt.

| Feature / Anforderung | Status Phase 13 | Ausgelagert in Phase 14 |
| --- | --- | --- |
| **Plugin Discovery** | Hardcoded/Manuelle Registrierung im Code. | Dynamischer Folder-Scan / Reflection. |
| **Fehlerbehandlung** | Fail-Fast: Stürzt ein Service ab, stoppt die Pipeline, Fehler wird geloggt. | Skip-Logic, Fallback-Caches, Auto-Recovery. |
| **Versionierung & Migration** | Keine Auto-Migration. Inkompatible Parameter fallen auf Defaults zurück. | Intelligente Migration alter Service-Sets. |
| **Undo / Papierkorb** | Löschen ist final (mit QMessageBox Bestätigung). | Papierkorb, Versionierung von Sets. |
| **UI: Status & Pipeline** | Einfache Liste (Up/Down) im Service-Fenster. | Visuelle Graphen (Nodes), Status-Icons (aktiv/veraltet). |
| **Kommunikation** | Direkter Funktionsaufruf via PluginExecutor. | Globaler asynchroner EventBus. |

## 2. Architektur & Datenmodell

* **Multi-Use Plugins:** Ein Plugin (z.B. EMA) kann mehrfach in einem Set vorkommen. Jede Nutzung erhält eine eindeutige instance_id (z.B. ema_1, ema_2).
* **ServiceSet JSON-Struktur:**
{
"set_id": "uuid-oder-name",
"display_name": "Mein Scalper",
"execution_order": ["grid_1", "prox_1", "ema_1"],
"services": {
"grid_1": {"plugin_id": "grid_lines", "lookback": 1000, "params": {"step_size": 0.5, "steps_around": 4, "custom_levels": []}},
"prox_1": {"plugin_id": "proximity", "lookback": 10000, "depends_on": ["grid_1"], "params": {"visit_pct": 0.05, "time_window_mins": 5}}
}
}
  * **lookback-Scan-Fenster (Korrektur):** Der Proximity-lookback ist ein Scan-Fenster über die Historie („von rechts nach links" bis Statistic-Signale-Max aus den App-Optionen). Er beträgt min(statistics_signal_limit, len(df)) – NICHT 1. Hinweis Datenumfang: df.tail(lookback) kann nie über len(df) hinausreichen; da der Chart df_data mit chart_candle_limit (Default 3000) lädt, statistics_signal_limit aber 10.000 ist, muss für den vollständigen Scan entweder die Chart-Lastgrenze angehoben werden oder der Evaluator lädt fehlende Bars aus market_data.duckdb nach.
* **Service→Service-Abhängigkeit (depends_on):** execution_order bestimmt nur die Reihenfolge, nicht die Referenz. Ein Service deklariert explizit, welche instance_ids er aus dem shared_state liest (z. B. Proximity liest die Linien von grid_1). Der Evaluator validiert vor der Ausführung: Alle depends_on-IDs müssen früher in execution_order stehen und deren shared_state-Einträge müssen vorhanden sein (sonst Fail-Fast).
* **Dependency Injection & Context:** Services greifen niemals direkt auf Datenbanken oder globale Settings zu. Alles wird über den immutablen PluginContext bereitgestellt. PluginContext (Data Class): symbol, timeframe, mode ("chart"|"batch"|"live"), timestamp (epoch-Sekunden des aktuellen Live-Ticks / der letzten Bar), shared_state, settings (AppSettings als Kopie – damit erhält der Proximity-Service z. B. statistics_signal_limit ohne globalen Zugriff).
* **Shared State Konfliktlösung:** Der shared_state im Context ist mutable, aber strikt per Namespace gekapselt. Service A schreibt ausschließlich nach context.shared_state[self.instance_id].
* **PluginCapabilities (ersetzt live_op):** TypedDict mit 5 Feldern: chart: bool (als Chart-Indikator verfügbar), batch: bool (in der Batch-Pipeline ausführbar), live: bool (unterstützt Live-Ticks), feature_store: bool (schreibt feature_data in feature_store), render: bool (liefert chart_render_payload). live_op wird deprecated.
* **Feature-Store-Writer (wer schreibt wohin):** Im Grid-Set schreibt ausschließlich der Proximity-Service die Hit-Records nach feature_data (feature_store=True); der Grid-Lines-Service rendert nur (render=True, feature_store=False). Damit sind die Daten für Schritt 7 (Marker/Statistik auf feature_store-Basis) sauber definiert.
* **Repository Pattern:** Das Laden und Speichern von Sets übernimmt ein neues ServiceSetRepository, um den StateManager nicht weiter aufzublähen. Persistenz in eigener Tabelle service_sets in app_data.duckdb. Pflicht-API: save_set(), get_set(), delete_set() UND list_sets() (Quelle für die Set-Dropdowns im Prop-/Service-Fenster). Default-Name beim Speichern, wenn display_name leer: automatisch aus instance_ids (z. B. "grid_1 + prox_1").
* **Schicksal Alt-Plugin grid_liquidity:** analytics/features/definitions/grid_liquidity.py und der Indikator-Adapter chart/indicators/grid_liquidity.py bleiben UNVERÄNDERT als Referenz-Parallelbetrieb (analog zu grid.py). Die neuen Services grid_lines / proximity laufen zusätzlich. Kein Umbau, kein Löschen.

## 3. UI/UX & Validierung

* **Strikte Parameter-Validierung:** Die Parameter-Eingaben (Wertebereich min/max, step) werden aus dem Schema 1:1 auf die PySide6-Widgets (QDoubleSpinBox, QSpinBox) übertragen.
* **Expert-Fenster:** Parameter mit expert: True (inkl. des Service-lookback) werden in einem ausklappbaren Sub-Bereich versteckt. Hier werden auch die Plugin-Metadaten (Autor, Version, Beschreibung) als Read-Only-Texte oder Tooltips angezeigt.
* **Definitionsdateien (Req: manuelle Anpassung):** Die Darstellungs-Reihenfolge der Props (parameter_order: List[str]) und die Label-Namen (param_labels: Dict[str, str]) liegen AN DEN ANFANG jeder Plugin-/Service-Definition – NICHT mehr im Chart-Adapter (chart/indicators/grid_liquidity.py). Das Prop-Fenster generiert daraus; manuelle Anpassung direkt in den Definitionsdateien.
* **Prop-Fenster-Aktionen (Req: Dropdown + Aktionen):** Oben reine Indi-Props (Sichtbarkeit, Farben), Trennlinie, darunter die Service-Props (mehrere möglich). Set-Dropdown aller gespeicherten Konfigs (aus list_sets()). Aktionen: Name vergeben / Speichern / Ausführen / Löschen – Löschen zwingend mit QMessageBox-Gegenfrage. Ausführen startet den ServiceSetEvaluator, der die Services nacheinander in execution_order abarbeitet.
* **Namensfrage Sets (Req):** Eigener Name im QLineEdit; wenn leer, automatischer Name aus instance_ids (z. B. "grid_1 + prox_1").

---

# Phase 13: Service- & Plugin-Architektur – Schritt-für-Schritt AI Guide

## 1. Prämissen, Sicherheitsregeln & Workflow-Vereinbarungen (Verbindlich)

1. **Inkrementelle Umsetzung & Stopp-Punkte:** Die AI arbeitet **exakt einen definierten Schritt** ab, stoppt dann und wartet auf den expliziten Startschuss des Anwenders für den nächsten Schritt.
2. **HARTE VERBOTSREGEL (Alt-Grid):** Die Datei chart/indicators/grid.py (der alte Grid Indikator) darf **unter keinen Umständen editiert, umbenannt oder gelöscht werden**. Er bleibt als Referenz völlig unangetastet. Das Refactoring findet im neuen chart/indicators/grid_liquidity.py statt.
3. **Backup & Rollback-Regel:**
* Vor jedem Schritt erstellt der Anwender ein Git-Tag (z.B. phase13_stepX).
* Wenn bei der Umsetzung eines Schrittes Architektur-Checks oder Tests fehlschlagen, wird **sofort ein Rollback** durchgeführt. Die AI darf nicht auf einem fehlerhaften Stand weiterarbeiten.


4. **Architektur-Checks nach jedem Schritt:** Die AI muss nach ihren Code-Änderungen prüfen:
* Keine Circular Imports.
* Keine ungenutzten Imports.
* Gewährleistung der Abwärtskompatibilität.


5. **Keine automatischen UI-Tests:** Die Validierung erfolgt **ausschließlich headless** via Python-Testskripte oder DB-Inspektionen.
6. **PARITY-PFLICHT (Gegenkontrolle):** Jede Änderung am Grid-Pfad wird gegen den Alt-Indikator chart/indicators/grid.py auf identische Ergebnisse geprüft (test/check_grid_parity.py, Pflichtbestandteil von Schritt 6). Nur mit Parität erfüllt die Gegenkontrolle ihren Zweck – ohne Parität kein Fortschritt.

---

## Schritt 1: Core-Interfaces (Service, Context, Capabilities)

### 1.1 Ziel & Kapselung

Scharfe Definition der Interfaces. Plugins erhalten einen Namespace-geschützten Context, UI-Metadaten und Validierungsgrenzen.

### 1.2 Anweisung an die AI

1. Öffne analytics/features/plugins/base_plugin.py.
2. Ergänze folgende Strukturen (additiv):
* PluginCapabilities (TypedDict mit 5 Feldern: chart: bool, batch: bool, live: bool, feature_store: bool, render: bool). Ersetzt live_op (wird deprecated; bestehende Plugins behalten ihr live_op bis zum Cleanup in Schritt 7).
* PluginContext (Data Class): symbol: str, timeframe: str, mode: Literal["chart","batch","live"], timestamp: Optional[int] (epoch-Sekunden des aktuellen Live-Ticks / der letzten Bar), shared_state: Dict[str, Any], settings: AppSettings (Kopie – kein anderer globaler Zugriff auf Settings erlaubt).


3. Optimiere das ParameterSchema:
* Erzwinge die Auswertung von min, max, step (float/int hart clippen; step als Widget-Schrittweite).
* Füge expert: bool (Default: False) hinzu.


4. Modifiziere die Basisklasse PluginFeature:
* Aktualisiere die Signatur: calculate(self, df: pd.DataFrame, params: Dict[str, Any], context: Optional[PluginContext] = None).
* Ergänze als abstrakte Metadaten (Definitionsdatei, an den Anfang jeder Plugin-/Service-Definition): parameter_order: List[str] (Darstellungs-Reihenfolge der Props) und param_labels: Dict[str, str] (Label-Namen). Damit sind Reihenfolge/Labels manuell anpassbar und Single Source of Truth für das Prop-Fenster.
* Rückwärtskompatibilität Phase 12: calculate(df, params) ohne context bleibt gültig (context ist Optional). Auch der Docstring-Kopf „Der Chart liest NIE direkt aus dem Feature-Store" ist so zu präzisieren, dass er die Indikator-Berechnung (GUI) betrifft – Overlay-Konsumenten (SignalOverlay, Statistik) lesen feature_store in Schritt 7.


5. Ergänze analytics/features/feature_builder.py (PluginExecutor):
* PluginExecutor.execute(plugin_id, df, params, context=None) reicht den Context (inkl. shared_state) an plugin.calculate() durch. Ohne diese Durchreichung erreicht der shared_state die Services nie (sonst Konflikt mit Schritt 3).

### 1.3 Headless-Validierung

* Erstelle test/check_p13_s1.py: Instanziiere ein Plugin und rufe calculate mit und ohne Context auf. Prüfe zusätzlich: (a) Capabilities-Felder vorhanden, (b) Context enthält symbol/timeframe/mode/timestamp/settings/shared_state, (c) expert im Schema ist bool, (d) parameter_order/param_labels vollständig.

---

## Schritt 2: ServiceSetRepository & Datenmodell

### 2.1 Ziel & Kapselung

Trennung der Service-Speicherung vom StateManager.

### 2.2 Anweisung an die AI

1. Erstelle analytics/engine/service_models.py für die TypedDicts:
* ServiceInstanceConfig (plugin_id, lookback, params, depends_on: Optional[List[str]] – instance_ids, deren shared_state-Einträge dieser Service liest).
* ServiceSetDefinition (set_id, display_name, execution_order [List of instance_ids], services [Dict instance_id -> ServiceInstanceConfig]).


2. Erstelle analytics/engine/service_set_repository.py:
* Klasse ServiceSetRepository(db_path).
* Implementiere save_set(), get_set(), delete_set() UND list_sets() (Pflicht – Quelle für die Set-Dropdowns im Prop-/Service-Fenster).
* Persistenz: eigene Tabelle service_sets in app_data.duckdb (set_id PRIMARY KEY, display_name, definition JSON) – StateManager wird nicht angefasst.
* Logik: Generiere einen Default-Namen beim Speichern, wenn display_name leer ist (automatisch aus instance_ids, z. B. "grid_1 + prox_1").

### 2.3 Headless-Validierung

* Erstelle test/check_p13_s2.py: Speichere ein JSON mit Multi-Use-Plugins (zweimal das gleiche Plugin mit unterschiedlichen instance_ids) und lade es erfolgreich zurück. Prüfe zusätzlich: list_sets() liefert alle gespeicherten Sets, delete_set() entfernt sauber.

---

## Schritt 3: ServiceSet Evaluator (Pipeline-Ausführung)

### 3.1 Ziel & Kapselung

Sichere Ausführung der Pipeline mit Namespace-Isolation im shared_state.

### 3.2 Anweisung an die AI

1. Erstelle analytics/engine/set_evaluator.py mit der NEUEN Klasse ServiceSetEvaluator. Der bestehende SetEvaluator (Signal-Sets) bleibt UNVERÄNDERT und läuft parallel weiter.
2. Implementiere execute_set(set_definition, df, context):
* Iteriere über execution_order.
* Schneide den Dataframe je Service exakt auf dessen lookback-Wert zu (df.tail(lookback)).
* Führe den Service via PluginExecutor aus – MIT Context-Durchreichung (context.shared_state[self.instance_id] ist les-/schreibbar, Namespace-isoliert).
* Validierung der Abhängigkeiten VOR der Ausführung: Alle depends_on-IDs müssen früher in execution_order stehen und deren shared_state-Einträge müssen nach deren Ausführung vorhanden sein (sonst Fail-Fast).
* **Fail-Fast:** Bricht ein Service mit Exception ab, logge den Fehler und brich die Ausführung der restlichen Pipeline ab.

### 3.3 Headless-Validierung

* Erstelle test/check_p13_s3.py: Mock-Pipeline mit 2 Services. Prüfe: (a) Service 2 greift nur auf den beschnittenen df zu, (b) shared_state wird per instance_id isoliert, (c) Abstürze werden sauber abgefangen (Fail-Fast), (d) depends_on-Verletzung (nachgelagerte Referenz) wirft vor der Ausführung.

---

## Schritt 4: UI-Integration – Service-Fenster

### 4.1 Ziel & Kapselung

Visuelle Verwaltung der Sets ohne die eigentlichen Indikatoren zu beeinflussen.

### 4.2 Anweisung an die AI

1. Erweitere service_win.py (oder zugehörige UI-Datei):
* Ein QListWidget für die Anzeige der aktuellen execution_order (Reihenfolge).
* Up/Down QPushButton zur Änderung der Ausführungsreihenfolge in der Liste.
* Ein QLineEdit für den Set-Namen (leer → Auto-Name aus instance_ids beim Speichern).
* Buttons zum Speichern/Löschen. Beim Löschen zwingend eine QMessageBox.warning implementieren.
* Zusätzlich ein „Ausführen"-Button: startet den ServiceSetEvaluator.execute_set für das aktive Set (Services nacheinander in execution_order).


2. Binde das neue ServiceSetRepository ein (list_sets() als Quellen für die Set-Auswahl).

### 4.3 Headless-Validierung

* Führe py_compile auf den UI-Klassen aus. Rufe Controller-Methoden ohne exec_() der GUI auf, um Crash-Freiheit zu verifizieren.

---

## Schritt 5: UI-Integration – Indikator Prop-Fenster & Expert-Modus

### 5.1 Ziel & Kapselung

Platzsparende UI mit strikter Wert-Validierung und Metadaten-Anzeige.

### 5.2 Anweisung an die AI

1. Passe das Indikator-Einstellungs-Panel (IndicatorSettingsDialog) an.
2. Layout-Vorgaben:
* Reine Indi-Props (Sichtbarkeit, Farben) oberhalb der Trennlinie (QFrame.HLine); darunter die Service-Props (mehrere möglich).
* QComboBox zur Auswahl des aktiven Services aus dem Set – Quelle: list_sets() des ServiceSetRepository.
* Ein QStackedWidget, das pro Service eine eigene Formular-Seite generiert.


3. Dynamische Generierung & Validierung:
* Übertrage min, max, step aus dem ParameterSchema exakt auf die generierten QDoubleSpinBox / QSpinBox.
* Reihenfolge und Label-Namen der Props kommen aus parameter_order / param_labels der Plugin-/Service-Definition (Definitionsdatei, manuell anpassbar) – NICHT mehr aus dem Chart-Adapter.
* Felder mit expert: True (inkl. des Service-lookback) in ein separates, ausklappbares QGroupBox oder QWidget packen.
* Zeige im Expert-Bereich die Plugin-Metadaten (description, author, version) als QLabel an.
* Set-Aktionen im Prop-Fenster: Name vergeben / Speichern / Ausführen (via ServiceSetEvaluator) / Löschen – Löschen zwingend mit QMessageBox-Gegenfrage.



### 5.3 Headless-Validierung

* Erstelle test/check_p13_s5.py: Simuliere die Formulargenerierung anhand eines Schemas und verifiziere, dass expert-Felder im korrekten Unter-Layout landen.

---

## Schritt 6: Grid Indikator Refactoring (Thread-sicherer Cache)

### 6.1 Ziel & Kapselung

Aufteilung in Service-Sets und Thread-sichere Live-Verarbeitung im neuen Indikator.

### 6.2 Anweisung an die AI

1. Erstelle analytics/features/definitions/grid_lines_service.py und proximity_service.py.
* GridLinesService (capabilities: render=True, feature_store=False): baut das Raster in PARITÄT zur Alt-Implementierung grid.py – Zentrierung auf dem letzten Close (center ± steps_around * step_size, exakt wie grid.py: f_round_to_custom_step + range(-steps_around, steps_around+1)), dazu die 6 Custom-Levels (prox_level1..6, nur > 0). Das native UTC-Zeitfenster (Minute 0/30 ± time_window_mins) bleibt unangetastet (keine eigenen Zeitkonzepte). Schreibt die Linienliste nach context.shared_state[self.instance_id].
* ProximityService (capabilities: render=True, feature_store=True): liest die Linien aus context.shared_state[depends_on[0]] (z. B. grid_1), läuft über die Historie von rechts nach links und wendet die PROZENTUALE visit%-Semantik von grid.py an (lvl ± visit_pct/100, Touch-High/Low- und Pierce-Logik) – NICHT die absolute threshold-Distanz des Alt-Plugins grid_liquidity. lookback = Scan-Fenster bis min(statistics_signal_limit, len(df)) aus context.settings. Schreibt die Hit-Records nach feature_data (feature_store=True) für Schritt 7 (Marker/Statistik). Zusätzlich bleibt die Live-Frage beantwortet: Der Indikator rechnet die Differenz Live-Tick vs. gecachte Liq-Line rein mathematisch – der Lines-Service wird NICHT pro Tick getriggert, sondern einmal pro neuem Close (Cache-Neuaufbau).


2. Refactore chart/indicators/grid_liquidity.py:
* Instanziiere ein ServiceSetDefinition für den Historical-Run (Set: grid_1 → grid_lines, prox_1 → proximity, Reihenfolge + depends_on).
* Speichere die Resultate (Linien) thread-sicher in self._cached_grid_lines (atomare Zuweisung).
* In der update_live_candle-Methode wird die Pipeline nicht aufgerufen. Es wird ausschließlich die mathematische Differenz zwischen dem Live-Tick und self._cached_grid_lines berechnet, um Live-Punkte zu setzen.
* CACHE-NEUAUFBAU (beantwortete Klärungsfrage): update_live_candle erkennt eine neue Candle daran, dass ihre gerundete Time nicht in self._time_real_to_cont liegt (bestehende Logik in chart_win.py). Genau dann wird NUR ein debounced Refresh angestoßen, der den Cache einmal neu aufbaut – nicht bei jedem Tick.


3. Alt-Bestand bleibt unberührt: analytics/features/definitions/grid_liquidity.py (Alt-Plugin) und der Indikator-Adapter chart/indicators/grid_liquidity.py laufen als Referenz weiter (Parallelbetrieb wie grid.py). Die neuen Services laufen zusätzlich.

### 6.3 Headless-Validierung

* Erstelle test/check_p13_s6.py: Führe den Indikator historisch aus (Cache wird gefüllt) und simuliere danach 100 Live-Ticks, um zu verifizieren, dass die Pipeline-Execution dabei nicht getriggert wird.
* PFICHT-PARITY-TEST test/check_grid_parity.py: Auf denselben Daten liefern die neuen Services (grid_lines + proximity) IDENTISCHE Linien/Circles wie grid.py. Parameter-Äquivalenz: step_size ↔ prox_stepSize, steps_around ↔ prox_stepsAround, visit_pct ↔ prox_visitPct, custom_levels ↔ prox_level1..6, time_window_mins ↔ prox_timeWindowMins, use_time_filter ↔ prox_useTimeFilter. Nur mit Parität erfüllt die Gegenkontrolle ihren Zweck.

---

## Schritt 7: Cleanup & Systemweiter Regressionstest

### 7.1 Ziel & Kapselung

Abschließende Bereinigung der Signal-Kopplungen. **Alte Indikatoren bleiben unberührt.**

Umfang erweitert: Es werden ALLE signal_results-Konsumenten umgestellt (SignalOverlay UND StatisticsRepository). Der Rückbau der Alt-Signal-Mechanik (SetEvaluator / signal_results-Schreiber) wird konkret geplant und erfolgt AUSDRÜCKLICH erst nach einem erfolgreichen manuellen User-Test der neuen Marker/Statistik.

### 7.2 Anweisung an die AI

1. Passe SignalOverlay an, um Marker aus den neuen Feature-Store-Daten zu laden (statt aus signal_results). Die Set-Auswahl (get_available_sets) basiert künftig auf den feature_data-Einträgen der Proximity-Services (feature_id='proximity', plugin_version), nicht mehr auf `SELECT DISTINCT source_id FROM signal_results`.

2. Nimm analytics/statistics_repository.py MIT in die Umstellung (zweiter Konsument von signal_results): Die SQL-Aggregations-Queries (fetch_signals, Kennzahlen, Forward-Performance) lesen künftig aus feature_data (feature_id='proximity') statt aus signal_results. statistic_win.py bleibt API-stabil – es ändert sich nur die Datenquelle, nicht das Fenster.

3. Plane den Rückbau der Signal-Mechanik konkret – NUR nach erfolgreichem manuellem User-Test (gesonderter Startschuss):
   * SetEvaluator-Konsumenten deaktivieren/entfernen: analytics/background_workers/live_analyzer.py (set_config["signals"] ist bereits leer, aber evaluator/set_active_signals werden weiterhin instanziiert; fill_gaps_for_pair wird aus chart_win.py:54/787/823 aufgerufen und schreibt weiterhin signal_results) und analytics/background_workers/historical_scanner.py (schreibt signal_results, Z. 210/250/279).
   * analytics/engine/set_evaluator.py (SetEvaluator) bleibt bis zum Rückbau unverändert – der neue ServiceSetEvaluator (Schritt 3) läuft parallel.
   * Nach Schritt 1+2 lesen chart/overlays/signal_overlay.py und analytics/statistics_repository.py KEINE signal_results mehr.
   * Tabelle signal_results wird NICHT gelöscht (Daten bleiben als Referenz), es finden nur keine neuen Schreibvorgänge mehr statt.

4. Führe alle Phase-13-Tests sowie die Kompatibilitätstests von Phase 12 aus.

5. Prüfe explizit, ob chart/indicators/grid.py im Git-Tree als "unmodified" markiert ist.