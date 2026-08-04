# Konzept Phase 15: Service UI und Analytics (Vorbereitung auf finale Roadmap)

## 1. Übersicht & Zielsetzung

Ziel von **Phase 15** ist die Weiterentwicklung der **Service-UI** (`service_win.py`)
und des **gesamten Analytics-Moduls** (`../../analytics`) auf Basis der etablierten
Plugin-/Service-Architektur (Phasen 12–14). Abgeleitete Modul-Struktur:

* **15.1 Service-UI:** Modularisierung der gewachsenen `service_win.py` (≈ 1.400
  Zeilen) und Bedien-Feinschliff. Bestehende Funktionen bleiben erhalten
  (Set-Editor, Parameter-Controls, Papierkorb, Set-/Service-Sperren).
* **15.2 Analytics-Lesepfade:** `schema_version` vervollständigen (Invariante 5);
  Chart-Entkopplung abschließen (Invariante 10: Pipeline-Fallback im Indikator additiv abbauen).
* **15.3 Alt-Pfad-Rückbau:** Alt-Signal-Mechanik (`signal_results`, Signal-Sets,
  Alt-Scan-Pfade in LiveAnalyzer/HistoricalScanner) additiv abwickeln.
* **15.4 ML-Signale (optional):** `lightgbm_v1` / `xgboost_v1` aktivieren und
  dokumentieren oder explizit als „future" deklarieren.

Jedes Modul enthält direkt im Anschluss die vollständige, isolierte **Schritt-für-Schritt AI-Implementierungsanweisung** inklusive automatischer Git-Backup-Regeln, Architektur-Constraints, des zentralen Grundsatzkapitels und der headless Validierung.

---

## 2. Allgemeine Grundsätze & Workflow-Vereinbarungen (Agents.md / Architektur.md)

1. **HARTE VERBOTSREGEL (Bestands-Pfade):**
   Geschützte Dateien (niemals beschädigen, bestehende Aufrufe unverändert lassen):
   * `../../chart/indicators/grid_liquidity.py` – Plugin-Indikator (Service-Pipeline-Adapter, Cache, feature_store-Lesepfad).
   Neue Logiken werden **additiv** integriert (Wrapper/Schnittstellen).

2. **Git-Backup & Fallback vor JEDEM Kapitel:**
Vor Beginn jedes Kapitels erstellt die AI / der User automatisch einen Git-Commit und Tag: `phase15_step1`, `phase15_step2`, etc. Bei Fehlern wird sofort per `git reset --hard` auf das jeweilige Tag zurückgerollt.

3. **Headless-Validierung (Keine UI- und Keine unnötigen (Regressions-)tests):**
Validierungen erfolgen rein headless (kein `QApplication.exec()`, keine manuellen Klicks) über gezielte PyTest- / Headless-Python-Skripte im Ordner `../../test`. Es werden ausschließlich die für den jeweiligen Schritt absolut notwendigen Tests ausgeführt – keine unnötigen (Regressions-)tests.

4. **Modulare Herauskoppelbarkeit:**
Jedes Kapitel ist so aufgebaut, dass Beschreibung, Schema-Änderung, Implementierungsanleitung, die allgemeinen Grundsätze und der notwendige Test als zusammenhängender Block an die IDE-AI übergeben werden können.

5. **Struktur & Refactoring:**
Phase 15 bleibt **rein additiv**. Die Harte Verbotsregel (Bestands-Pfade) gilt
uneingeschränkt; die bereits erfolgte Entfernung von `grid.py` ist die einzige
Ausnahme (Einzelanweisung, dokumentiert in Punkt 1). Existing Subsysteme werden
nicht gebrochen, sondern um Schnittstellen/Wrapper erweitert.

---

## 3. Architektur-Invarianten (Kapitel 15.0 - Fundament)

Vor jeglicher Code-Implementierung gelten folgende unumstößliche System-Regeln zur Sicherstellung der Konsistenz:

1. **PluginRegistry Ownership:** Genau eine Singleton-Instanz der `PluginRegistry` pro Prozess.
2. **Feature Store vs. Cache (Source of Truth):**
`Plugin` $\rightarrow$ `PluginContext.shared_state` (Live-RAM) $\rightarrow$ `feature_store` (DuckDB, persistenter Vorberechnungs-Speicher) $\rightarrow$ `Indicator` (GUI-Lesepfad).
Der Indicator ruft niemals direkt Plugins zur Neuberechnung auf.
**Präzisierung (Empfehlung 1):** Die Konzeptklasse heißt `PluginContext` (Begriff
„EvaluationContext" ist vereinheitlicht; die reale Klasse liegt in
`../../analytics/features/plugins/base_plugin.py`). Abbauziel 15.2: Der noch vorhandene
Pipeline-Fallback in `grid_liquidity.calculate()` wird additiv durch einen reinen
DB-Lesepfad ersetzt.
3. **ID-Semantik:**
* `depends_on` referenziert ausschließlich `instance_id` (z. B. `"grid_1"`).
* `plugin_id` ist strikt case-insensitiv eindeutig (`plugin_id.lower()`).
4. **Quarantäne-Lebensdauer:** Quarantäne (`quarantined = True`) gilt ausschließlich im RAM für die aktuell laufende Session und wird nicht in der Datenbank persistiert.
5. **Versionierung & Schema:**
* Jeder Plugin-Output und Feature-Payload enthält ein `schema_version`.
  **Präzisierung (Empfehlung 2):** `schema_version` wird Pflichtfeld im
  `FeatureStorePayload`-TypedDict (`base_plugin.py`) und von ALLEN
  `feature_store=True`-Plugins gestempelt (inkl. Alt-Plugin
  `definitions/grid_liquidity.py`; bisher nur `ProximityService` – U15-A1).
* Jedes Plugin deklariert explizit eine `api_version` (z. B. `api_version="1"`).
* Versionsvergleiche nutzen Semantic Versioning (`major.minor.patch`). Reine Patch-Updates (z. B. `1.0.0` $\rightarrow$ `1.0.1`) lösen keine Schema-Migration aus.

6. **Hot-Reload-Semantik:** `PluginRegistry.reload()` ersetzt nur zukünftige Service-Instanziierungen; bereits laufende Hintergrund-Auswertungen laufen ungestört auf ihren bisherigen Objektinstanzen weiter. Custom Plugins werden isoliert entladen/neu importiert.
7. **Thread Safety:** Der Zugriff auf `PluginRegistry`, `ServiceSetEvaluator`
(Session-State, Quarantäne) und `FeatureStore` (Cache-Invalidierung) erfolgt über
`RLock` (Thread-Safety).
**Präzisierung (Empfehlung 3):** DB-Zugriff erfolgt bewusst **lock-frei** über
Thread-local `DbPool` (`../../db_service.py`, eine Connection pro Thread & DB) – globale
Threading-Locks auf Datenbankebene sind kontraproduktiv und werden nicht verwendet.
8. **Logging & Migration Rollback:**
* Logging verwendet strukturierte Fehlerobjekte (inkl. `timestamp`, `plugin`, `instance`, `symbol`, `timeframe`, `bar`, `exception`, `traceback`).
* Schlägt eine Schema-Migration fehl (`SchemaMigrator` Exception), wird die Transaktion abgebrochen, das alte Set im Speicher belassen und ein Rollback durchgeführt.

9. **Snapshot-Historie:** Ein historischer Snapshot in `service_set_history` wird ausschließlich beim erfolgreichen Überschreiben eines bereits existierenden Sets erzeugt.
10. **Chart-Entkopplung:** Der Chart führt niemals Berechnungen aus, sondern liest
ausschließlich vorberechnete Daten aus DuckDB (mit definiertem Fallback).
**Stand 04.08.2026:** Alt-Indikator `grid.py` entfernt; verbleibender Plugin-Indikator
`grid_liquidity` liest primär `feature_store` (`read_proximity_from_feature_store`).
Der noch vorhandene Service-Pipeline-Fallback in `calculate()` ist **Abbauziel 15.2**
(U15-A2).
11. **Quarantäne-Recovery (Lebensdauer):** Der `_failure_counters`-Zähler jeder Service-Instanz wird nach 300 Sekunden (5 Minuten) ohne weiteren Fehler automatisch zurückgesetzt (`_recovery_timer`). Eine einmalige Quarantäne (`quarantined = True`) bleibt für die laufende Session bestehen, bis der Evaluator einen vollständigen Neustart der Pipeline durchläuft (`reset()`).
12. **Hot-Reload Lifecycle:** `PluginRegistry.reload()` führt folgende atomare Schritte unter dem `RLock()` aus:
    a) Erfassen der aktuell geladenen Custom-Modul-Namen (`../../data/custom_plugins`).
    b) Gezieltes `importlib.reload(sys.modules[mod_name])` NUR für diese Module.
    c) Erneute Ausführung von `discover_plugins()` mit anschließendem Überschreiben des internen `plugins`-Dictionaries.
    d) WICHTIG: Bereits laufende Service-Instanzen (`LiveAnalyzer`, historische Berechnungen) behalten ihre alte Objekt-Referenz; neue Service-Instanzen nutzen die neuen Klassen.

13. **Cache-Invalidierung (Feature Store):** Der `FeatureBuilder` führt bei jedem `store_plugin_payload()` eine explizite Invalidation des In-Memory-Caches für das betroffene `(symbol, timeframe)` durch, um veraltete Zustände in `PluginContext.shared_state` zu verhindern.

---

# 15.01  Symbol-Auswahl und Favoriten

## 1. ANALYSE DER ANFORDERUNG (15.01)

### 1.1 Zielsetzung & Anwendungsbereich
Die Anforderung definiert eine zentral wiederverwendbare Symbol-Verwaltung mit Favoriten-Unterstützung für PyTrader.
* **Kernaufgabe:** Dynamische Ermittlung aller Broker-Symbole über MetaTrader5 (MT5), Persistierung in `app_data.duckdb` (als Cache/Offline-Fallback), Verwaltung einer Favoriten-Liste und Bereitstellung einer generischen UI-Komponente für alle Fenster (`ServiceWindow`, `StatisticWindow`/Analytics etc.).
* **Entkopplungs-Garantie:** Gemäß den Architektur-Regeln (OOP, IoC) wird die Symbol-Logik in Repositories/Helfer gekapselt (`../../db_service.py` / `../../state_manager.py`). Es entstehen keine zirkulären Abhängigkeiten.

### 1.2 Detaillierte Bausteine & Spezifikation
1. **Broker-Fetch & Persistenz (`get_symbols`):**
   * Liest alle verfügbaren Symbole live via `MetaTrader5.symbols_get()` aus.
   * Speichert/aktualisiert die vollständige Liste sowie den Favoriten-Status (`is_favorite` boolean) in der DuckDB `../../data/app_data.duckdb` (neue Tabelle `broker_symbols`).
   * Falls MT5 offline ist oder fehlschlägt: Ausgabe einer Log-Warnung und automatisches Ausweichen auf den zuletzt persistierten Datenstand in `app_data.duckdb`.
2. **Favoriten-Dropdown in den Hauptfenstern (`service_win`, `statistic_win` etc.):**
   * Zeigt in den UI-ComboBoxen ausschließlich Symbole an, deren Favoriten-Status `is_favorite == True` ist.
   * Wenn keine Favoriten definiert sind oder nach Erstinstallation: Fallback auf Default-Favoriten (z. B. `["SILVER", "GOLD", "BTCUSD"]`).
3. **Favoriten-Auswahl-Button (`*`):**
   * Ein kompakter Button mit Text/Icon `*` (oder `★`), direkt rechts neben der Symbol-ComboBox platziert.
   * Klick öffnet das nicht-modale Verwaltungsfenster `SymbolsWindow` (`symbols_win`).
4. **Auswahlfenster `SymbolsWindow` (`symbols_win`):**
   * Erbt von `PersistentWindow` (für Geometrie-Persistenz, z. B. `win_symbols`).
   * Nicht-modal (`show()`), verhindert Blockieren der Haupt-UI.
   * **Suchfeld oben:** Live-Eingabe (Case-Insensitive Prefix-/Sub-Match). Scrollt die Tabelle/Listbox automatisch zum ersten Treffer und markiert ihn/macht ihn sichtbar (`ensureWidgetVisible` / `scrollToItem`).
   * **Zweispaltige Tabelle/Listbox:**
     * Spalte 1: Symbolname (z. B. `SILVER`, `EURUSD`).
     * Spalte 2: Favoriten-Status (`*` oder `★` für Favorit, leer für Nicht-Favorit).
   * **Mausklick-Interaktion:** Ein Klick in Spalte 2 schaltet den Favoriten-Status sofort um (`True`/`False`), speichert die Änderung asynchron in DuckDB und löst ein Signal aus, um verbundene DropDowns live zu aktualisieren.
   * **Schließen-Mechanismus:** Über `Schließen`-Button, Windows-X oder `ESC`-Taste.

---

## 2. VORBEREITUNG, BACKUP & TESTING-STRATEGIE (OHNE UI)

### 2.1 Sicherheits-Backup (Vorab-Schritt)
Vor Code-Änderungen wird ein lokaler Git-Commit erzeugt und der `../../test`-Ordner gesichert.
```bash
git add -A
git commit -m "backup: vor Umsetzung Phase 15.01 Symbol-Auswahl und Favoriten"

```

### 2.2 Testing-Strategie (Strikte Einhaltung der "Keine UI-Tests"-Regel)

Gemäß den System-Instruktionen werden **keine PySide6-GUI-Tests** ausgeführt.
Die Verifizierung erfolgt ausschließlich über:

1. **Headless DB- & Logik-Tests (`test/check_p15_s1_symbols.py`):**
* Testet `get_symbols()` mit MT5-Mock/Live-Connection.
* Testet Schreiben & Lesen der Favoriten in `app_data.duckdb`.
* Testet Fallback-Verhalten bei fehlender MT5-Verbindung.


2. **Statische Analyse & Syntax-Checks:**
* `python -m py_compile` über alle geänderten `.py`-Dateien.


3. **Sorgfältige Code-Inspektion:**
* Überprüfung der Qt Signal/Slot-Verbindungen und Nicht-Modalität.



---

## 3. SCHRITT-FÜR-SCHRITT UMSETZUNGSANLEITUNG

### Schritt 1: Datenbank-Schema in `../../db_service.py` & `../../state_manager.py` erweitern

1. In `../../db_service.py` (`check_and_init_databases`) die Tabelle `broker_symbols` in `app_data.duckdb` anlegen:
```sql
CREATE TABLE IF NOT EXISTS broker_symbols (
    symbol VARCHAR PRIMARY KEY,
    path VARCHAR,
    is_favorite BOOLEAN DEFAULT FALSE,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

```


2. Standard-Favoriten (`SILVER`, `GOLD`, `BTCUSD`) bei leerer Tabelle initial per Upsert einfügen (`is_favorite = TRUE`).

### Schritt 2: Kerndaten-Logik in `../../db_service.py` implementieren

1. Funktion `get_broker_symbols(force_fetch: bool = False) -> List[Dict[str, Any]]` erstellen:
* **Primary:** Versucht MT5-Verbindung via `check_mt5_connection()` und `mt5.symbols_get()`. Speichert gefundene Symbole per `INSERT OR REPLACE` in `broker_symbols` (Favoriten-Status `is_favorite` bestehender Symbole bleibt erhalten).
* **Fallback:** Bei MT5-Fehler/Offline Log-Ausgabe (`⚠️ MT5 nicht erreichbar – nutze lokale Symbol-Datenbank`) und Auslesen aller Symbole aus `app_data.duckdb`.


2. Hilfsfunktionen zur Favoriten-Verwaltung in `../../state_manager.py` / `../../db_service.py`:
* `get_favorite_symbols() -> List[str]`: Liefert nur Symbole mit `is_favorite == TRUE`.
* `toggle_symbol_favorite(symbol: str, is_fav: bool) -> None`: Aktualisiert den Status in `app_data.duckdb`.



### Schritt 3: Erstellung der UI-Komponente `SymbolsWindow` in `serviceui/symbols_win.py`

1. Erstellung der neuen Datei `serviceui/symbols_win.py`:
* Erbt von `PersistentWindow` (INSTANCE_ID = `"win_symbols"`, `auto_restore = False`).
* Nicht-modal konfiguriert (`Qt.Window`).
* Beinhaltet ein `QLineEdit` (Suchfeld), ein `QTableWidget` (2 Spalten: Symbol, Favorit) und einen `QPushButton` ("Schließen").
* Überschreibt `keyPressEvent` für `Qt.Key_Escape` zum sauberen Schließen.


2. **Such- & Scroll-Logik:**
* Signal `textChanged` des `QLineEdit` an Such-Slot koppeln: Iteriert über die Tabellenzeilen, sucht den ersten Prefix-/Sub-Match, selektiert die Zeile und ruft `table.scrollToItem(item)` auf.


3. **Favoriten-Toggle-Logik:**
* Signal `cellClicked(row, col)` auswerten. Wenn `col == 1` (Spalte Favorit), Status umschalten (`*` <-> ` `), DB-Update ausführen und ein benutzerdefiniertes PyQt-Signal `favorites_changed = Signal()` emittieren.



### Schritt 4: Integration in `ServiceWindow` (`../../serviceui/service_win.py`)

1. In der UI/Layout-Erstellung neben `combo_symbol` einen kleinen Button `btn_symbol_fav` mit Beschriftung `★` einbauen.
2. Klick auf `btn_symbol_fav` öffnet `SymbolsWindow` als nicht-modale Singleton-Instanz (`SymbolsWindow.get_existing_instance()`).
3. Koppelung von `symbols_win.favorites_changed` an die Aktualisierung von `combo_symbol` (lädt `get_favorite_symbols()` neu und behält aktuelle Auswahl bei).

### Schritt 5: Integration in `StatisticWindow` (`../../statistic_win.py`) / Analytics

1. Gleichen Favoriten-Button (`★`) neben dem Symbol-Filter-Combo platzieren.
2. Signal-Koppelung analog zu Schritt 4 zur dynamischen Aktualisierung der Favoriten-Auswahl.

### Schritt 6: Verifikation & Headless Tests

1. Erstellung und Ausführung von `test/check_p15_s1_symbols.py`:
* Prüft DB-Table-Creation, Symbol-Fetch, Favoriten-Toggle und Fallback-Handling ohne MT5.


2. Syntax-Check auf allen geänderten/neuen Modulen (`../../main.py`, `../../db_service.py`, `../../state_manager.py`, `serviceui/symbols_win.py`, `../../serviceui/service_win.py`, `../../statistic_win.py`).

---

## 4. DATEI-ÄNDERUNGSÜBERSICHT

| Datei | Status | Beschreibung |
| --- | --- | --- |
| `../../db_service.py` | **Anpassung** | Tabelle `broker_symbols` initialisieren, `get_broker_symbols()` mit MT5/DB-Fallback & `toggle_symbol_favorite()` |
| `../../state_manager.py` | **Anpassung** | Helper-Methoden `get_favorite_symbols()` & `set_symbol_favorite()` ergänzen |
| `serviceui/symbols_win.py` | **NEU** | Nicht-modales `SymbolsWindow` (PersistentWindow) mit Suchfeld, 2-Spalten-Tabelle & Favoriten-Toggle |
| `../../serviceui/service_win.py` | **Anpassung** | Favoriten-Button (`★`) einbauen, DropDown auf Favoriten umstellen, Sync-Signal verbinden |
| `../../statistic_win.py` | **Anpassung** | Favoriten-Button (`★`) einbauen, DropDown auf Favoriten umstellen, Sync-Signal verbinden |
| `test/check_p15_s1_symbols.py` | **NEU** | Headless-Test für Symbol-Fetch, DB-Persistenz und Favoriten-Logik (ohne UI) |

---

## 5. RECHTE & BEFEHLE FÜR NÄCHSTE SCHRITTE

Sobald der Anwender den expliziten Startschuss gibt, werden die Schritte 1 bis 6 der Reihe nach isoliert und ohne UI-Tests umgesetzt.


Vielen Dank für diese hervorragenden Präzisierungen! Damit gewinnen wir eine enorm leistungsfähige und flexible Grundlage für die spätere Analytics-Engine.

Hier ist das aktualisierte und erweiterte Konzept für **Phase 15.02 (Anpassungen ServiceUI)** unter Berücksichtigung aller neuen Punkte:

---

# Phase 15.02 – Master-Detail ServiceUI mit Drag & Drop und Indikator-Status

---

## 1. Detaillierte Spezifikationen der Erweiterungen

### A) Drag & Drop für Service-Set-Erstellung (zu Punkt 3)

* **Funktionsweise:** Aus der Gruppe **"📦 Alle verfügbaren Plugins / Services"** kann ein Einzel-Service/Plugin per **Drag & Drop** in ein bestehendes **Service-Set** (oder einen Bereich "Neues Service-Set erstellen") gezogen werden.
* **Wirkung:**
1. Der Service wird mit seinen Standard-Parametern am Zielort eingefügt.
2. Die `execution_order` des Sets wird automatisch aktualisiert.
3. Die Änderung wird direkt in `ServiceSetRepository` / `app_data.duckdb` gespeichert und das Parameter-Formular rechts aktualisiert.



### B) Standalone-Services unterstützen (zu Punkt 4)

* **Funktionsweise:** Ein Einzel-Service muss nicht zwingend in einem Set verpackt sein.
* Standalone-Services erhalten einen eigenen Bereich **"⚡ Standalone Executable Services"**.
* Diese können direkt im `ServiceWindow` konfiguriert und einzeln als ad-hoc Task oder Hintergrund-Job ausgeführt werden.

### C) Kompakte Indikator-Anzeige & Live-Status (zu Punkt 2 Erweiterung)

Jedes Service-Set bzw. jeder Service im Master-Tree erhält eine **kompakte, zweistufige Indikator-Statusanzeige** in der Spalte *Info / Status*:

1. **Zuordnung (`Gehört zu Indikator`):**
* Symbol/Badge: `📌 [Indikator: <Name>]` (Zeigt, dass das Set die mathematische Basis für diesen Indikator bildet).


2. **Aktiv-Status (`Ist gerade aktiv in Indikator`):**
* Symbol/Badge: `🟢 [Aktiv: <Name>]` (wenn der Indikator im aktuellen Chart-Fenster aktiv geschaltet ist).
* Symbol/Badge: `⚪ [Inaktiv: <Name>]` (wenn der Indikator im Chart existiert, aber derzeit ausgeschaltet ist).



**Kompakte Darstellung im Tree-Row-Label:**

> `📈 grid_liquidity` $\rightarrow$ `📌 Indikator: grid_liquidity | 🟢 Aktiv in Chart`

---

## 2. VORBEREITUNG, BACKUP & TESTING-STRATEGIE (OHNE UI)

### 2.1 Sicherheits-Backup (Vorab-Schritt)

Vor Beginn der Arbeiten wird ein lokales Backup via Git erstellt:

```bash
git add -A
git commit -m "backup: vor Umsetzung Phase 15.02 (Master-Tree mit DragNDrop & Live-Status)"

```

### 2.2 Testing-Strategie (Strikte Einhaltung der "Keine UI-Tests"-Regel)

Gemäß den System-Instruktionen werden **keine PySide6-GUI-Tests** ausgeführt.
Die Verifizierung erfolgt ausschließlich über:

1. **Headless DB- & Logik-Tests (`test/check_p15_s2_service_tree.py`):**
* Testet die Zuordnung von Services zu Sets via Backend-Logik (Drag-and-Drop-Entsprechung im Model).
* Testet das Erkennen von Standalone-Services.
* Testet das Auslesen des Live-Indikator-Status (`is_active`) aus den `instance_states` / `symbol_tf_states` der Chart-Fenster.


2. **Statische Analyse & Syntax-Checks:**
* `python -m py_compile` über alle geänderten/neuen Dateien.


3. **Code-Inspektion.**

---

## 3. SCHRITT-FÜR-SCHRITT UMSETZUNGSANLEITUNG

### Schritt 1: Layout-Erweiterung & Vergrößerung in `../../serviceui/service_win.py`

1. Fenstergröße auf **1280 x 800 Pixel** anpassen.
2. Umbau des Hauptfensters mit `QSplitter` (horizontal):
* **Links:** Custom `QTreeWidget` mit aktivierter Drag & Drop Unterstützung (`setDragEnabled(True)`, `setAcceptDrops(True)`, `setDropIndicatorShown(True)`).
* **Rechts:** Inhaltsbereich (`ContentScrollMixin`) für Parameter-Spalten und Detail-Formulare.



### Schritt 2: Aufbau der Baum-Hierarchie (`_populate_master_tree`)

Aufbau des TreeWidgets mit folgenden Hauptknoten:

1. **📁 Service-Sets:**
* Alle Sets aus `ServiceSetRepository`.
* **Kompaktes Indikator-Badge in Spalte 2:**
* Liest aus `StateManager`, ob eine `set_id` einem Indikator zugeordnet ist.
* Liest aus `instance_states`, ob der Indikator im Chart aktuell den Schalter `active == True` hat.
* Render-Beispiel: `📌 grid_liquidity | 🟢 Aktiv` oder `📌 grid_liquidity | ⚪ Inaktiv`.


* **Unterknoten:** Services im Set mit Abhängigkeits-Pfeilen (`🔗 depends_on: <id>`).


2. **⚡ Standalone Services:**
* Ausführbare Einzel-Services ohne Set-Verpackung.


3. **📦 Alle verfügbaren Plugins (Repository):**
* Vollständige Liste aller in PyTrader registrierten Plugins aus `PluginRegistry`.
* Dienen als Quelle für Drag & Drop Aktionen.



### Schritt 3: Drag & Drop Logik implementieren

1. Überschreiben von `dropEvent` und `dragMoveEvent` im TreeWidget:
* **Drop-Quelle:** Muss ein Item aus "📦 Alle verfügbaren Plugins" sein.
* **Drop-Ziel:** Muss ein Service-Set-Knoten sein.


2. Beim Drop:
* Extrahieren der `plugin_id`.
* Erzeugen einer neuen `ServiceConfiguration` im Ziel-Set.
* Speichern des aktualisierten Service-Sets via `ServiceSetRepository.save_set()`.
* Aktualisieren der Tree-Darstellung und Selektion des neu hinzugefügten Services im rechten Parameter-Panel.



### Schritt 4: Headless Verifikation

1. Erstellung und Ausführung von `test/check_p15_s2_service_tree.py`:
* Überprüft die programmatische Set-Erweiterung (Drag&Drop-Äquivalent im Backend).
* Überprüft die korrekte Ermittlung des Aktiv-Status von Indikatoren aus den Persistenzdaten.


2. Syntax-Check aller geänderten Dateien (`python -m py_compile serviceui/service_win.py`).

---

## 4. DATEI-ÄNDERUNGSÜBERSICHT

| Datei | Status | Beschreibung |
| --- | --- | --- |
| `../../serviceui/service_win.py` | **Anpassung** | Umbau auf Splitter (1280x800), Master-Tree (`QTreeWidget`) mit Drag & Drop, Standalone-Services & kompakter Indikator-Statusanzeige |
| `../../analytics/engine/service_set_repository.py` | **Anpassung** | Helper zum schnellen Hinzufügen/Einfügen von Einzel-Services in bestehende Sets |
| `test/check_p15_s2_service_tree.py` | **NEU** | Headless-Test für Tree-Datenstrukturen, Indikator-Live-Status & Set-Updates (ohne UI) |

---

## 5. STATUS

Das Konzept für **Phase 15.02** ist vollständig ausgearbeitet. Ich warte nun auf deinen expliziten Startschuss zur schrittweisen Umsetzung.


# Phase 15.03 – Analytics-Engine & UI

## 1. SPEZIFIKATION & ARCHITEKTUR (15.03)

### 1.1 Zielsetzung & Modul-Ablage
Das alte `StatisticWindow` (`../../statistic_win.py`) wird vollständig durch das neue, modulare `AnalyticsWindow` ersetzt[cite: 1, 2].
* **Speicherort:** `analytics/ui/analytics_win.py`
* **Fenster-Typ:** Nicht-modales `PersistentWindow` (INSTANCE_ID = `"win_analytics"`, Min-Größe `1280 x 800` Pixel)[cite: 1, 2].
* **Architektur:** Master-Stacked Layout (`QSplitter` + `QStackedWidget` für Lazy Loading) mit strikter Trennung von UI-Rendering (`pyqtgraph` / `QTableWidget`) und Hintergrund-Berechnung (`DuckDB` + `PySide6 Async Worker`).

### 1.2 Detaillierte Bausteine

#### 1. Header: Globale Aktionsleiste (Top-Bar)
`[ Profile: ▾ Profile_Name ]` `[➕ New]` `[💾 Save]` `[📋 Clone]` `[🗑️ Delete]` `|` `Symbol: [ SILVER ▾ ] [★]` `TF: [ M1 ▾ ]` `[ Refresh 🔄 ]`
* **Profil-Management (CRUD):**
  * `analytics_profiles`-Tabelle in `../../data/app_data.duckdb` speichert Konfigurationen als JSON (`profile_id`, `name`, `symbols`, `timeframes`, `service_sets`, `time_filters`, `ml_models`, `is_active`).
  * **Explicit Save (Option B):** Nach Parameter- / Slider-Änderungen wird der Profilname mit einem Dirty-State Marker versehen (`*` im Titel / Profile-Combo). Änderungen werden erst beim Klick auf `[💾 Save]` in DuckDB geschrieben.
* **Symbol & Timeframe:** Nutzt die in 15.01 erstellten Favoriten-Logiken[cite: 1, 2, 3].

#### 2. Navigation: Sidebar (Left Master)
Kompaktes `QListWidget` / Icon-Text-Bar schaltet das `QStackedWidget` um (Lazy Loading: SQL-Query wird erst beim Aktivieren der Page angestoßen):
* 📋 **Tabelle:** Detailed Signal-Viewer (Paginierte Daten + Jump-to-Chart)[cite: 1, 2].
* 🌡️ **Heatmap:** 2D-Session & Day Matrix (X: Wochentage Mo–Fr, Y: Tagesstunden 00–23 Uhr Berlin Wanduhr)[cite: 1, 2, 3].
* 📈 **Scatter:** Feature-Korrelation & N-Bar Outcome.
* 📊 **Verteilung:** Histogramme & Percentile-Cutoffs.
* 💰 **Equity:** Performance-Kurven (In Vorbereitung).

#### 3. Main-Panel: Ansichts-Container (Right Detail)
* **Obere Filterleiste (Ansichts-Spezifisch):** Stellt lokale Regler (Confidence-Slider, Bins, Time-Window) bereit.
* **Event-Debouncing:** Alle Slider/Regler nutzen einen **QTimer-Debounce (200–300 ms)**, um Mehrfach-Abfragen bei kontinuierlicher Mausbewegung zu verhindern.
* **Plot-/Daten-Bereich:** 100% verbleibende Fläche, Hardware-beschleunigt via `pyqtgraph`.
* **Wanduhrzeit-Garantie:** Alle Achsen und zeitlichen Matrizen formatieren streng die Berliner Wanduhrzeit (aus den MT5-Epochs ohne doppelte UTC-Offsets)[cite: 1, 2, 3].
* **Jump-to-Chart (Variante 2):** Jeder Klick/Doppelklick in der Tabelle, auf Heatmap-Kacheln oder Scatter-Punkte ermittelt den Zeitstempel der Kerze und ruft direkt `open_chart_at_bar(symbol, tf, bar_time)` auf, um das Chart-Fenster in den Vordergrund zu holen (`raise_()` + `activateWindow()`)[cite: 1, 2].

#### 4. Performance & Safe-Guards
* **Asynchrone Lade-Indikatoren & "No Data" States:** Visueller Progress-Spinner während DuckDB-Queries sowie ein klares *"Keine Daten für die gewählten Filter"*-Overlay bei 0 Zeilen Ergebnis.
* **Max-Lookback-Protection:** Sicherheitsfilter (`scanner_candle_limit` / max. 50.000 Kerzen aus `app_settings`) verhindert das Überladen des Grafikspeichers bei großen Datenmengen[cite: 1, 2, 3].

---

## 2. VORBEREITUNG, BACKUP & TESTING-STRATEGIE (OHNE UI)

### 2.1 Sicherheits-Backup (Vorab-Schritt)
Vor Beginn der Arbeiten wird ein lokales Backup via Git erstellt:

git add -A
git commit -m "backup: vor Umsetzung Phase 15.03 Analytics Engine & UI"

### 2.2 Testing-Strategie (Strikte Einhaltung der "Keine UI-Tests"-Regel)

Gemäß den System-Instruktionen werden **keine PySide6-GUI-Tests** ausgeführt.
Die Verifizierung erfolgt ausschließlich über:

1. **Headless DB- & Logik-Tests (`test/check_p15_s3_analytics.py`):**
* Testet das Anlegen der Tabelle `analytics_profiles` in `app_data.duckdb`.
* Testet das Profil-CRUD (`NEW`, `EDIT`, `CLONE`, `DELETE`).
* Testet die SQL-Aggregationen für Heatmap (Hour x Weekday), Verteilung und Scatter-Daten auf `feature_store`.
* Testet das Debouncing-Verhalten und die Max-Lookback-Einschränkung.

2. **Statische Analyse & Syntax-Checks:**
* `python -m py_compile` über alle geänderten/neuen Module.

3. **Sorgfältige Code-Inspektion.**

---

## 3. SCHRITT-FÜR-SCHRITT UMSETZUNGSANLEITUNG

### Schritt 1: DB-Schema & Repository erweitern

1. In `../../state_manager.py` / `../../db_service.py` die Tabelle `analytics_profiles` anlegen:

CREATE TABLE IF NOT EXISTS analytics_profiles (
    profile_id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL UNIQUE,
    configuration JSON NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


2. Repository-Helper zur Verwaltung von Analytics-Profilen (`get_profile`, `save_profile`, `delete_profile`, `list_profiles`) in `../../state_manager.py` implementieren.


### Schritt 2: Analytics Data Worker (`analytics/engine/analytics_worker.py`) erstellen

1. Erzeugung eines `QThread`-Background-Workers für asynchrone DuckDB-Analysen.
2. Implementierung von Hochleistungs-SQL-Abfragen auf `feature_store`:
* **Heatmap Query:** `SELECT EXTRACT(hour FROM bar_time) AS hr, EXTRACT(dayofweek FROM bar_time) AS dw, COUNT(*), AVG(...) FROM feature_store GROUP BY hr, dw`
* **Distribution Query:** Binned Feature-Data Abfrage für Histogramme.
* **Scatter Query:** Pairwise Extraction `(feature_data->>'val', next_close_return)`.
* **Table Query:** Paginierter Abruf mit `LIMIT` / `OFFSET` für den Detail-Viewer.


### Schritt 3: Erstellung von `analytics/ui/analytics_win.py`

1. Erstellung der Datei `analytics/ui/analytics_win.py`:
* Erbt von `PersistentWindow` (INSTANCE_ID = `"win_analytics"`, `auto_restore = True`).
* Nicht-modal konfiguriert (`Qt.Window`).
* Baut das Top-Bar Profil-CRUD Layout und die `QSplitter`-Struktur (Sidebar + `QStackedWidget`) auf.

2. **Einbindung von `pyqtgraph` & Sub-Widgets:**
* Instanziierung der 4 Sub-Views (Tabelle, Heatmap, Scatter, Verteilung).
* Verknüpfung aller lokalen Slider/Filter mit `QTimer.singleShot(250, ...)` für sauberes Event-Debouncing.

3. **Jump-to-Chart Anbindung:**
* Klick-Events auf Tabellenzeilen, Heatmap-Zellen oder Scatter-Punkte erfassen und `open_chart_at_bar(symbol, tf, bar_time)` des Main-Windows auslösen.

4. **Ersetzung in `../../main.py`:**
* Import von `StatisticWindow` in `../../main.py` entfernen und durch `AnalyticsWindow` aus `analytics/ui/analytics_win.py` ersetzen.



### Schritt 4: Headless Verifikation

1. Erstellung und Ausführung von `test/check_p15_s3_analytics.py`:
* Überprüft DB-Profil-Persistenz, SQL-Queries, Asynchronität und Datenaufbereitung.

2. Syntax-Check aller betroffenen Module (`python -m py_compile analytics/ui/analytics_win.py main.py`).

---

## 4. DATEI-ÄNDERUNGSÜBERSICHT

| Datei | Status | Beschreibung |
| --- | --- | --- |
| `analytics/ui/analytics_win.py` | **NEU** | Hauptfenster für Analytics (Master-Stacked, pyqtgraph Plots, Top-Bar Profil-CRUD)

 |
| `analytics/engine/analytics_worker.py` | **NEU** | Asynchroner QThread-Worker für DuckDB-SQL-Aggregationen auf `feature_store`<br> |
| `../../state_manager.py` | **Anpassung** | Tabelle & Helper `analytics_profiles` ergänzen

 |
| `../../main.py` | **Anpassung** | Ersetzung von `StatisticWindow` durch `AnalyticsWindow`<br> |
| `../../statistic_win.py` | **Entfernt/Deprecated** | Altes Statistik-Fenster wird durch `AnalyticsWindow` ersetzt

 |
| `test/check_p15_s3_analytics.py` | **NEU** | Headless-Test für Analytics-Profile, SQL-Queries & Performance (ohne UI)

 |

---

## 5. NACHGELAGERTE ARBEITEN (ERST SPÄTER IMPLEMENTIERT)

Folgende Themen sind bewusst **nicht Bestandteil von Phase 15.03** und werden gesammelt in späteren Phasen umgesetzt:

1. **Exporte:**
* Export von gefilterten Daten und Matrizen als CSV, Excel oder PNG/SVG-Grafik.

2. **Multi-Symbol und Multi-Timeframe:**
* Gezielter Vergleich mehrerer Symbole/Timeframes nebeneinander in einer Matrix oder Kurve.

3. **Massentests & Parameter-Optimierung:**
* Automatische Parameter-Sweeps über verschiedene Zeiträume, Service-Parameter und ML-Variablen.

4. **Aktive ML-Inferenz:**
* In Phase 15.03 wird ML noch nicht aktiv eingebunden; die bestehenden Profil-Strukturen (`"ml_models"` im JSON-Payload) bleiben rein vorbereitend vorhanden.
