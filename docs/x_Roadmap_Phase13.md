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


4. **Dynamische Fenster- & Box-Größen (VERBINDLICH – KEINE fixen Pixelangaben):**
   Die Höhe UND die Breite des Prop-Fensters sowie alle Boxen darin sind **vollständig dynamisch** und leiten sich ausschließlich aus ihrem Inhalt ab. Es dürfen **keine fixen Pixelwerte** für Höhe oder Breite von Fenster oder Boxen verwendet werden. Konkret:
   * **Anzeige & Farben (Indi-Props oben):** Die Höhe dieses Bereichs ist dynamisch und richtet sich nach der Anzahl der vorhandenen Parameter.
   * **Box „Service-Parameter":** Die Höhe der Box ist dynamisch und richtet sich nach der Anzahl der enthaltenen Parameter (z. B. endet sie exakt unter dem letzten Parameter wie Level 6 – unabhängig davon, wie viele Level existieren).
   * **Preset-Block (ganz unten):** Der Preset-Block wird dynamisch **direkt unter die höchste Box** (Service-Parameter ODER Experten-Optionen) geplottet – ohne großen Abstand.
   * **Gesamte Fensterhöhe:** Das Prop-Fenster ist in seiner Höhe vollständig dynamisch und endet **direkt unter dem Preset-Block** (so kompakt wie möglich – kein leerer Platz darunter). Beim Vergrößern des Fensters dürfen die Boxen NICHT mitwachsen; sie bleiben auf Inhalt-Höhe (dynamisch).

---

### 5.2.4 DOKUMENTATION – Delta aller UI-Änderungen (Ist-Zustand, umgesetzt)

> Diese Sektion dokumentiert die tatsächlich umgesetzten UI-Änderungen am
> `IndicatorSettingsDialog` (`chart/indicator_dialog.py`) als Ergänzung zu den
> oberen Vorgaben. Sie ist der verbindliche Referenzstand für Punkt 4.

#### a) Vollständig dynamische Größen (Kernumsetzung Punkt 4)
* **Keine fixen Pixelwerte mehr:** `self.setMinimumWidth(520)` wurde entfernt. In `_restore_geometry()` wird nur noch die **Position** des Dialogs wiederhergestellt – die Größe (bisher `self.resize(max(440, …), max(100, …))`) wird bewusst NICHT mehr restauriert (Größe = Inhalt, siehe `_save_geometry()`).
* **Haupt-Layout** (`QVBoxLayout` in `init_ui`): `setSpacing(6)`, `setSizeConstraint(QLayout.SetFixedSize)` (Fenster schmiegt sich an Inhalt an, kein leerer Raum unten) und `setAlignment(Qt.AlignTop)` (Boxen bleiben beim manuellen Aufziehen auf Inhalt-Höhe am oberen Rand verankert – 4.6).
* **Size-Policies (4.2.4):** `QGroupBox` „Service-Parameter" vertikal `Maximum`; `QStackedWidget` vertikal `Maximum`; „Anzeige & Farben", „Service-Set Aktionen" und „Experten-Optionen" horizontal `Expanding` + vertikal `Maximum`.
* **Neue Klasse `_ServiceStack(QStackedWidget)`:** Der Standard-QStackedWidget liefert als `sizeHint` das Maximum aller Seiten. `_ServiceStack` liefert stattdessen `sizeHint`/`minimumSizeHint` der **aktuell sichtbaren Seite** und ruft `updateGeometry()` bei `setCurrentIndex()` – dadurch endet die Box „Service-Parameter" exakt unter dem letzten Parameter der AKTUELLEN Service-Seite (auch bei nicht angezeigtem Dialog).
* **Wirklich kollabierbarer Expert-Bereich (4.4):** Neue Methode `_setup_collapsible(group)`: Beim Checkbox-Toggle der `QGroupBox` werden die Kind-Widgets ein-/ausgeblendet und `_reflow()` gerufen; gilt für den Plugin-Expert-Bereich UND die per-Service-Expert-Gruppen im Stack.
* **Neue Methode `_reflow()`:** Bei nicht angezeigten Dialogen werden Show-Events nicht zugestellt → Haupt-Layout sonst veraltet. `_reflow()` invalidert das Layout explizit und ruft `adjustSize()` (z. B. nach Expert-Toggle, Service-Seitenwechsel, Stack-Neuaufbau).

#### b) Angepasste Layout-Struktur (User-Anpassungen nach Punkt 4)
Das Plugin-Layout ist auf ein **`QGridLayout` (2 Zeilen × 2 Spalten)** umgestellt
(`content_grid`, Spacing 6, Spalte 0 stretch=1):

```
Zeile 0: [ Anzeige & Farben  ] [ Preset                ]
Zeile 1: [ Service-Parameter ] [ Service-Set Aktionen  ]
         [                   ] [ Experten-Optionen     ]
```

* **Rahmen um die Preset-Box:** Neue Methode `_build_preset_group()` – die Preset-Auswahl (ComboBox + „💾 Speichern" + „❌ Löschen") liegt jetzt in einer `QGroupBox("Preset")`. Legacy-Modus (Alt-Indikatoren ohne Plugin): Preset-Box unten (bisherige Position, jetzt im Rahmen). Plugin-Modus: rechts oben.
* **„Anzeige & Farben" Breite = „Service-Parameter" Breite:** Beide liegen in derselben linken Grid-Spalte → identische Breite (headless gemessen: 360 == 360 px), horizontal `Expanding` beidseitig.
* **„Service-Set Aktionen" direkt auf Höhe „Service-Parameter" (rechts daneben):** Beide in Grid-Zeile 1, `Qt.AlignTop` → gleiche Y-Position (gemessen: beide y=108).
* **„Experten-Optionen" direkt unter „Service-Set Aktionen":** In derselben rechten Spalte (`right_bottom`, `AlignTop`), unmittelbar darunter (y = Aktionen-Ende + 6 px Spacing), horizontal `Expanding` → gleiche Breite wie Preset/Aktionen.
* **Trennlinie (`QFrame.HLine`) nur noch, wenn Indi-Props vorhanden** sind (kein verwaister Strich bei Plugins ohne Sichtbarkeits-/Farb-Props).

#### c) Headless-Verifikation (Grün)
* `py_compile` auf `chart/indicator_dialog.py` und `test/check_dialog_geometry.py` ✓
* Code-Inspektion (4.7.2): keine `resize(`, `setFixedSize/Height/Width(`, `setMinimumWidth/Height(` im Dialog ✓
* `test/check_dialog_geometry.py` (erweitert um Teil 2): Fensterhöhe == `sizeHint` (kein leerer Raum), Expert-Toggle ändert `sizeHint().height()` dynamisch (z. B. 281 → 327 → 281), Service-Parameter-Box == `sizeHint` ✓
* `test/check_p13_s5.py` sowie alle weiteren Phase-13- und Kompatibilitätstests ✓

# AI-Implementierungsanweisung: Dynamische UI-Layouts für das Prop-Fenster

4.1. Ziel & Prämissen
Das Eigenschaften-Fenster (z. B. `IndicatorSettingsDialog` / `PropertiesWindow`) muss bezüglich Höhe und Breite **vollständig dynamisch** aufgebaut werden. Jegliche harten Pixelangaben für Fenstergrößen (`resize(x, y)`, `setFixedSize()`, etc.) oder Boxgrößen werden gestrichen. Die GUI schmiegt sich exakt an ihren Inhalt an und vermeidet leeren Raum.
4.2 Layout-Hierarchie & Stretch-Verhalten festlegen
Anweisung an die AI
1. Öffne die Datei `chart/indicator_dialog.py` (bzw. das entsprechende Prop-Fenster-Modul).
2. Stelle sicher, dass das Central-Widget bzw. das Haupt-Layout ein `QVBoxLayout` nutzt.
3. Entferne alle Aufrufe wie `self.resize(...)`, `self.setFixedHeight(...)`, `self.setFixedWidth(...)` oder `widget.setMinimumHeight(...)` mit festen Pixelwerten.
4. Setze die Size-Policy der Container-Widgets/Boxen (`QGroupBox`, `QFrame`) explizit auf `Maximum` oder `Preferred` für die vertikale Richtung:
```python
widget.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

```
5. Setze `layout.setSizeConstraint(QLayout.SetFixedSize)` auf dem Haupt-Layout des Dialogs/Fensters. Dadurch passt sich das Fenster automatisch der minimal benötigten Größe seines Inhalts an und verhindert leeren Raum am unteren Fensterrand.

4.3 Dynamische Sektion "Anzeige & Farben" (Indi-Props oben)
Anweisung an die AI
1. Baue die obere Sektion für Indikator-Darstellungsparameter (Farben, Sichtbarkeit) in ein eigenes `QWidget` oder `QGroupBox` ein.
2. Verwende für die Formularfelder ein `QFormLayout` mit `fieldGrowthPolicy = QFormLayout.AllNonFixedFieldsGrow`.
3. Füge **keine** vertikalen Spacer (`addSpacer` / `addStretch`) innerhalb dieser oberen Sektion ein. Die Höhe muss sich rein aus der Summe der generierten Formularzeilen ergeben.
4. Füge unterhalb der Sektion eine visuelle Trennlinie per `QFrame` ein:
```python
line = QFrame()
line.setFrameShape(QFrame.HLine)
line.setFrameShadow(QFrame.Sunken)

```
4.4 Dynamische Sektion "Service-Parameter" & "Expert-Options"
Anweisung an die AI
1. Erstelle die `QGroupBox` "Service-Parameter".
2. Die Höhe der Box muss dynamisch mit der Anzahl der sichtbaren Parameter skalieren. Das Unter-Layout (`QFormLayout`) darf keine festen Zeilenhöhen aufweisen.
3. Die Box endet exakt unter dem letzten Eingabefeld (z. B. `prox_level6`).
4. Falls der "Expert Mode" (ausklappbarer Bereich / Sub-Widget) aktiviert oder eingeblendet wird:
* Das Ausklappen/Einblenden ruft automatisch `self.adjustSize()` auf dem Hauptfenster auf, damit sich die Gesamthöhe nahtlos erweitert oder verkleinert.
* Das `QStackedWidget` für die Services nutzt `QSizePolicy.Preferred` / `QSizePolicy.Maximum`, damit ungenutzter Platz nicht durch leere Ränder auffällt.

4.5 Dynamischer "Preset-Block" (Ganz unten)
Anweisung an die AI
1. Plaziere den Preset-Block (Dropdown für Presets, Buttons "Speichern", "Löschen", "Schließen") in einem eigenen `QHBoxLayout` bzw. `QWidget`.
2. Füge diesen Block im Haupt-`QVBoxLayout` **direkt** unter die Service-Box / den Expert-Bereich ein.
3. Setze `layout.setSpacing(6)` (oder ähnlich geringen Wert), um den Abstand zwischen der Service-Box und dem Preset-Block minimal zu halten.
4. Stelle sicher, dass **kein** `addStretch()` vor oder nach dem Preset-Block eingefügt wird, das das Fenster künstlich aufblähen würde.

4.6 Fenster-Resizing & Maximierungs-Schutz
Anweisung an die AI
1. Wenn der Anwender das Fenster manuell vergrößert, dürfen die Inhalts-Boxen (`QGroupBox`) vertikal **nicht mitwachsen**.
2. Erreiche dies, indem am Ende des Haupt-`QVBoxLayout` (unter dem Preset-Block) ein einzelnes `layout.addStretch(1)` platziert wird ODER die `alignTop`-Eigenschaft auf dem Haupt-Layout gesetzt wird:
```python
main_layout.setAlignment(Qt.AlignTop)

```
3. Dadurch bleiben alle Boxen und der Preset-Block auf ihrer inhaltlich berechneten Kompakthöhe am oberen Rand verankert, wenn das Fenster manuell aufgezogen wird.

4.7 Validierung (Headless)
AI-Prüfauftrag nach der Umsetzung
1. **Syntax & Import-Check:** Führe `py_compile` auf allen angepassten UI-Dateien aus.
2. **Code-Inspektion auf Pixel-Hardcoding:**
* Suche im Code nach `resize(`, `setFixedHeight`, `setFixedWidth`, `setFixedSize` und verifiziere, dass keine festen Pixelwerte für Fenster- oder Box-Dimensionen mehr existieren.
3. **Headless-Layout-Test (`test/check_dialog_geometry.py`):**
* Instanziiere den Dialog/das Fenster headless.
* Blende testweise Zusatzfelder aus/ein und verifiziere via `dialog.sizeHint().height()`, dass sich die empfohlene Gesamthöhe dynamisch mit der Anzahl der Elemente ändert.

### 5.3 Headless-Validierung

* Erstelle test/check_p13_s5.py: Simuliere die Formulargenerierung anhand eines Schemas und verifiziere, dass expert-Felder im korrekten Unter-Layout landen.


### Kapitel 5.4: Anpassungen Speicherverhalten, Presets & Servicefenster-Dynamik

---

#### 5.4.1 Konzepte & Architektur

##### 5.4.1.1 Breiten- und Höhendynamik im Servicefenster (service_win.py)

Das Servicefenster wird von statischen Einzelsteuerelementen auf ein mehrspaltiges, vollkommen dynamisches Layout umgestellt.

* **Horizontale Spalten-Skalierung (Breite):** Für jedes im Service-Set definierte Element (z. B. grid_1, prox_1) wird eine eigene vertikale Spalte (QGroupBox) nebeneinander im QHBoxLayout angeordnet. Die Fensterbreite passt sich automatisch an die Anzahl der Spalten an (wächst nach rechts).
* **Vertikale Inhalts-Skalierung (Höhe):** Die Höhe jeder Spalte leitet sich exakt aus der Anzahl ihrer Formularfelder ab. Es gibt keine festen Pixelhöhen.
* **Experten-Modus:** Parameter mit expert: True (z. B. individueller lookback) werden in eine einklappbare QGroupBox am Fuß der jeweiligen Spalte gelegt. Das Ein-/Ausklappen verändert die Höhe dynamisch per adjustSize().
* **Dynamische Grenzen:** Es werden keine harten Pixelwerte für min/max-Höhe oder -Breite verwendet. Das Haupt-Layout nutzt setSizeConstraint(QLayout.SetFixedSize) in Kombination mit QSizePolicy.Preferred / QSizePolicy.Maximum.

##### 5.4.1.2 Entkopplung der Indikator-Presets & Speichermechanik

Um Konflikte zwischen der Berechnungslogik (Service-Sets) und der visuellen Darstellung zu vermeiden, werden die Presets strikt entkoppelt:

* **Service-Set (service_sets):** Speichert rein die mathematische Berechnungslogik (Grid-Steps, Proximity-Schwellen, Lookbacks, Zeitfilter).
* **Indikator-Preset / State (instance_states / symbol_tf_states):** Speichert für den Indikator (z. B. grid_liquidity) nur noch:
  1. Die Referenz auf das genutzte Service-Set (set_id).
  2. Reine Darstellungs-Parameter des Charts (Farben, Linienstärken, Sichtbarkeiten).

* **Save/Restore-Verhalten im Chart-Window (chart_win.py):**
  * **Speichern:** Der IndicatorSettingsDialog übergibt dem Chart-Window ein getrenntes Dictionary aus set_id und display_params.
  * **Laden/Rendern:** render_indicators liest die set_id, holt die aktuellen Berechnungs-Parameter über das ServiceSetRepository und verknüpft sie mit den Darstellungs-Parametern für den ServiceSetEvaluator.
  * **Vorteil:** Wird ein Service-Set im Servicefenster angepasst, übernehmen alle offenen Charts mit dieser set_id automatisch die neue Logik, ohne ihre individuellen Farbeinstellungen zu verlieren.

---

#### 5.4.2 Schritt-für-Schritt AI-Anleitung

##### 5.4.2.1 Prämissen & Sicherheitsregeln (Verbindlich)

1. **Inkrementelle Umsetzung:** Die AI arbeitet **exakt einen definierten Schritt** ab, stoppt danach und wartet auf den expliziten Startschuss des Anwenders.
2. **HARTE VERBOTSREGEL (Alt-Grid):** Die Datei chart/indicators/grid.py darf **unter keinen Umständen editiert, umbenannt oder gelöscht werden**.
3. **Keine fixen Pixelangaben:** Jegliche Layouts (Höhe und Breite) leiten sich dynamisch aus dem Inhalt ab (setSizeConstraint(QLayout.SetFixedSize) bzw. QSizePolicy.Maximum).
4. **Validierung:** Alle Prüfungen erfolgen headless (ohne GUI-Start) via py_compile und eigene Test-Skripte.

---

##### 5.4.2.2 Schritt 1: Breiten- & Höhendynamisches Layout im Servicefenster (service_win.py)

###### 5.4.2.2.1 Ziel & Kapselung

Umstellung von service_win.py auf ein mehrspaltiges Layout, das sowohl in der Breite (Anzahl der Services) als auch in der Höhe (Anzahl der Parameter) flexibel skaliert.

###### 5.4.2.2.2 Anweisung an die AI

1. Öffne service_win.py und passe den zentralen Bereich des Fensters an:
* Ersetze statische Parameter-Felder durch ein QHBoxLayout (service_columns_layout).

2. Implementiere die dynamische Spalten-Generierung (_build_service_columns(set_definition)):
* Für jede instance_id in execution_order wird eine QGroupBox als vertikale Spalte erzeugt.
* Innerhalb der Spalte wird ein QFormLayout für die Parameter des jeweiligen Services gerendert (float -> QDoubleSpinBox, int -> QSpinBox, bool -> QCheckBox).
* Parameter mit expert: True werden in eine einklappbare QGroupBox ("Experten-Optionen") am unteren Ende der Spalte platziert.

3. Dynamische Breiten- & Höhensteuerung:
* Setze für jede Service-Spalte:
```python
column_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
```
* Das Haupt-Layout des Service-Fensters erhält:
```python
main_layout.setSizeConstraint(QLayout.SetFixedSize)
main_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
```
* Dadurch wächst das Fenster beim Hinzufügen von Services nach rechts (Breite) und beim Ausklappen von Experten-Optionen nach unten (Höhe) – ohne leeren Raum.

###### 5.4.2.2.3 Headless-Validierung

* Erstelle test/check_p13_service_win_geometry.py.
* Instanziiere ServiceWindow headless und erstelle/lade nacheinander ein Set mit 1 Service und ein Set mit 3 Services.
* Prüfe via sizeHint(), dass width mit der Anzahl der Spalten skaliert und height bei Einklappen des Expert-Modus schrumpft.

---

##### 5.4.2.3 Schritt 2: Entkopplung der Indikator-Presets & Speichermechanik (chart_win.py & indicator_dialog.py)

###### 5.4.2.3.1 Ziel & Kapselung

Saubere Trennung von Logik (set_id aus service_sets) und Darstellung (Farben, Sichtbarkeiten) im Indikator-Preset.

###### 5.4.2.3.2 Anweisung an die AI

1. Passe chart/indicator_dialog.py an:
* Trenne das Rückgabe-Dictionary beim Speichern eines Presets auf:
```python
preset_payload = {
    "set_id": selected_service_set_id,
    "display_params": {
        "line_color": "#2196F3",
        "show_lines": True,
        "circle_color_std": "#FFEB3B"
    }
}
```

2. Passe chart/chart_win.py an:
* **Save-State (save_state):** In indicators_state wird für grid_liquidity nur noch die set_id sowie das display_params-Dict abgelegt.
* **Render-Logik (render_indicators):**
  1. Liest set_id aus indicators_state.
  2. Lädt die Logik-Parameter über ServiceSetRepository().get_set(set_id).
  3. Mergt display_params (Darstellung) und Logik-Parameter zusammen.
  4. Übergibt das zusammengesetzte Dict an den ServiceSetEvaluator / Indikator-Adapter.

###### 5.4.2.3.3 Headless-Validierung

* Erstelle test/check_p13_preset_decoupling.py.
* Simuliere den Preset-Speicher- und Ladevorgang in chart_win.py.
* Verifiziere, dass eine Änderung an der Farbstufe im Indikator-Dialog nicht die service_sets-Tabelle überschreibt, und eine Änderung am Grid-Raster im Servicefenster sofort von allen Charts übernommen wird, die diese set_id nutzen.


---

# Kapitel 5.5: Farbauswahl & Transparenz-Unterstützung (ColorButton mit Alpha-Kanal)

## 5.5.1 Konzept & Architektur

### 5.5.1.1 Problemstellung & Anforderungen

Bisher wurden Farbwerte teilweise als Hex-Strings manuell eingegeben oder über simple Standard-Inputs abgefragt. Für moderne Chart-Overlay-Grafiken (z. B. Farbzonen, schattierte Level, semi-transparente Marker/Circles) ist eine **stufenlose Transparenz-Steuerung (Alpha-Kanal)** essenziell.
Zudem darf ein Farbwähler das dynamische Layout des Prop-Fensters nicht durch ein riesiges Farbrad aufblähen, sondern muss sich kompakt in das `QFormLayout` einfügen.

### 5.5.1.2 Die Lösung: Kompaktes Custom-Widget (`ColorButton`)

* **Bordmittel-Nutzung:** Baut zu 100 % auf PySide6 / PyQt (`QColorDialog` und `QPushButton`) auf – keine externen UI-Bibliotheken erforderlich.
* **Platzeffizient:** Der `ColorButton` ist ein kleines Farbquadrat (festgelegte Kompaktgröße z. B. 60×24 px), das die aktuell gewählte Farbe inklusive Deckkraft als Hintergrund anzeigt.
* **Transparenz (Alpha-Kanal):** Über die Option `QColorDialog.ShowAlphaChannel` wird im Dialog ein zusätzlicher Schieberegler für Transparenz (0–255 bzw. 0.0–1.0) freigeschaltet.
* **CSS / Chart-Kompatibilität:**
* Bei **100 % Deckkraft** (Alpha = 255) liefert der Button ein Standard-Hex-Format (`#RRGGBB`).
* Bei **Teil-Transparenz** (Alpha < 255) liefert der Button automatisch einen `rgba(r, g, b, alpha)`-String. Dieser ist direkt 1:1 kompatibel mit TradingView Lightweight Charts v5 (WebEngine) und HTML/CSS.


* **Schema-Integration:** Das `ParameterSchema` eines Plugins unterstützt beim Typ `"color"` das optionale Flag `allow_alpha: bool` (Default: `True`).

---

## 5.5.2 Schritt-für-Schritt AI-Anleitung

### 5.5.2.1 Prämissen & Sicherheitsregeln (Verbindlich)

1. **Inkrementelle Umsetzung:** Die AI arbeitet **exakt einen definierten Schritt** ab, stoppt danach und wartet auf den expliziten Startschuss des Anwenders.
2. **HARTE VERBOTSREGEL (Alt-Grid):** Die Datei `chart/indicators/grid.py` darf **unter keinen Umständen editiert, umbenannt oder gelöscht werden**.
3. **Kompaktes Layout:** Der `ColorButton` darf die vertikale oder horizontale Dynamik des Prop-Fensters nicht blockieren (`setSizePolicy` des Buttons beachten).
4. **Validierung:** Alle Prüfungen erfolgen headless (ohne GUI-Start) via `py_compile` und eigene Test-Skripte.

---

### 5.5.2.2 Schritt 1: Erstellung der `ColorButton`-Klasse

#### 5.5.2.2.1 Ziel & Kapselung

Erstellung einer wiederverwendbaren UI-Komponente `ColorButton` unter `chart/widgets/color_button.py` (oder direkt in `chart/indicator_dialog.py`).

#### 5.5.2.2.2 Anweisung an die AI

1. Erstelle die Klasse `ColorButton(QPushButton)`:
* **Attributes:** `_color: QColor`, `_enable_alpha: bool`.
* **Signal:** `colorChanged = Signal(str)` (emittiert den Farb-String bei jeder Änderung).


2. Implementiere die Methoden:
* `color() -> str`: Gibt bei `alpha < 255` einen `rgba(r, g, b, a)`-String (z. B. `rgba(33, 150, 243, 0.35)`) zurück, sonst `#RRGGBB`.
* `setColor(color_str: str)`: Setzt die Farbe aus Hex oder `rgba(...)`-String und aktualisiert das Styling.
* `update_style()`: Setzt das Button-Stylesheet dynamisch auf `background-color: rgba(...)`, um die gewählte Farbe und Deckkraft direkt im Button zu visualisieren.
* `_open_color_dialog()`: Öffnet `QColorDialog.getColor()`. Setzt bei `_enable_alpha=True` das Flag `QColorDialog.ShowAlphaChannel`. Bei gültiger Auswahl wird `colorChanged` emittiert.



#### 5.5.2.2.3 Headless-Validierung

* Erstelle `test/check_p13_color_button.py`.
* Instanziiere `ColorButton` headless. Teste `setColor("#FF0000")` und `setColor("rgba(255, 0, 0, 0.5)")` und verifiziere, dass `color()` jeweils den korrekten String-Typ liefert.

---

### 5.5.2.3 Schritt 2: Anbindung an das dynamische Prop-Fenster (`indicator_dialog.py` & `service_win.py`)

#### 5.5.2.3.1 Ziel & Kapselung

Erweiterung der automatischen Formular-Generierung, sodass Parameter vom Typ `"color"` automatisch als `ColorButton` gerendert werden.

#### 5.5.2.3.2 Anweisung an die AI

1. Passe die Formular-Generierungs-Logik in `IndicatorSettingsDialog` (und ggf. `ServiceWindow`) an:
* Wenn `spec.get("type") == "color"`:
* Lese `allow_alpha = spec.get("allow_alpha", True)` aus dem `ParameterSchema`.
* Erzeuge ein `widget = ColorButton(default_color=val, enable_alpha=allow_alpha)`.
* Verknüpfe `widget.colorChanged` mit der Parameter-Aktualisierungs-Logik des Dialogs.
* Füge das Widget in das `QFormLayout` der jeweiligen Sektion ein.

2. Stelle sicher, dass die übergebenen `rgba(...)`-Farben beim Speichern von Presets oder Service-Sets unversehrt als String in der Datenbank landen und vom `ServiceSetEvaluator` / Indikator an den `chart_render_payload` weitergereicht werden.

#### 5.5.2.3.3 Headless-Validierung

* Erstelle `test/check_p13_color_integration.py`.
* Generiere ein Test-Formular aus einem `ParameterSchema` mit `type: "color"`.
* Verifiziere, dass der Formular-Generator den `ColorButton` erzeugt und Farbänderungen inklusive Alpha-Kanal korrekt im Parameter-Dictionary ankommen.

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