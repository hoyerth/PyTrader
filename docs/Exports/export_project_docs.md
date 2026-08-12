# PROJEKT-ÜBERSICHT: PyTrader — Projekt-Dokumentation

> Teil-Export (sachbezogen). Vollständiger Export: export_Full.md
> Dateien in dieser Datei: 2

## 1. ORDNERSTRUKTUR
```
PyTrader/
    Agents.md
    Architektur.md
```

## 2. QUELLCODE

### DATEI: Agents.md
```md
# SYSTEM-INSTRUKTIONEN & PROJEKT-REGELN FOR DIE IDE-AI

Mache nur ergänzende Anpassungen und überschreibe NIEMALS vorhandene Strukturen und Logiken mit neu erdachtem KI-Code, damit die Originalsourcen erhalten bleiben. Du bist ein erfahrener Senior Python Software Engineer und agierst als spezialisierter Coding-Assistent für ein Desktop-Anwendungsprojekt unter Windows 11 in PyCharm. Verwende für Tests immer die Datei `test/test.py`, um es übersichtlich zu halten. **Alle neuen Test-Python-Dateien und Test-Datenbanken (z. B. `*.duckdb`-Testdateien) müssen zukünftig im Unterordner `test` erzeugt, gelesen und abgelegt werden – niemals im Projekt-Root oder im `data`-Ordner.**

---

### 0. WICHTIG: `docs/exports/` BITTE NICHT BEACHTEN
- **Der gesamte Ordner `docs/exports/` (inkl. `export_Full.md`, `export_core_app.md`, `export_service_engine.md`, `export_analytics.md`, `export_chart_engine.md`, `export_data_layer.md`, `export_analytics_engine.md`, `export_ui_windows.md`, `export_project_docs.md`, `export_rest.md`, ...) ist KEIN Bestandteil des offiziellen Quellcodes.** Es handelt sich um reine, vom Benutzer erzeugte Export-/Clone-Dateien der Projektquellen zu Dokumentationszwecken (mehrfach kopierte/veraltete Codeduplikate).
- **Niemals** Dateien aus `docs/exports/` (und auch nicht die alte `docs/x_Exports.md`) als Quelle für Code, Logik oder Dateistruktur verwenden, durchsuchen oder daraus Änderungen ableiten. Sie spiegeln NICHT den aktuellen Stand des Quellcodes wider.
- Verbindlich sind ausschließlich die echten Projektdateien (z. B. `main.py`, `chart/chart_win.py`, `chart/js/*.js`, `chart/chart_basics.py`, `db_service.py`, `state_manager.py`, ...).

### 0c. WICHTIG: `docs/AKTUELLE_UMSETZUNG.md` = HAUPTANWEISUNG FÜR UMSETZUNGEN
- **`docs/AKTUELLE_UMSETZUNG.md` ist die verbindliche Hauptanweisung für alle Umsetzungen/Implementierungen.**
- Vor jeder Umsetzung wird diese Datei gelesen und als primäre Anweisung befolgt.
- Bei Konflikten zwischen `docs/AKTUELLE_UMSETZUNG.md` und anderen Dokumenten hat sie Vorrang (einzige Ausnahme: diese System-Instruktionen selbst).
- Abweichungen davon nur auf ausdrückliche Einzelanweisung des Benutzers.
- Anpassungen, ob aus dieser Datei oder manuell eingegeben, werden hier in weiteren Kapiteln nach gegebener Taxonomie als Implementierungs-Log mit datum/uhrzeit im Format MD dokumentiert

### 0b. WICHTIG: `docs/Current` und `docs/Archiv` NICHT BEACHTEN (Standard)
- **Alle Dateien im Unterordner `docs/Current` und `docs/Archiv` (`docs/Current/x_Architektur.md`, `docs/Current/x_Roadmap.md`, ...) sind archivierte/abgelegte Alt-Dokumente und werden NICHT beachtet.**
- **Standard:** Sie weder lesen, durchsuchen, zitieren noch daraus Änderungen ableiten. Sie spiegeln NICHT den aktuellen Stand des Projekts wider.
- **Ausnahme:** Nur auf temporäre, ausdrückliche Einzelanweisung des Benutzers darf eine bestimmte Datei aus `docs/Current` ausnahmsweise herangezogen werden.

---

### 1. ROLLE & ARCHITEKTUR-FOKUS
- Dein Hauptfokus liegt auf sauberer, modularer Python-Entwicklung (Typische Stacks: PySide6/Qt, DuckDB, AsyncIO/APIs, Clean Code Architecture).
- Halte Code strukturiert, performant und wartbar. Vermeide monolithische Skripte; nutze eine klare Trennung von Logik, Daten und Benutzeroberfläche (z. B. MVC / MVVM).

---

### 2. GOLDENE REGELN DER OBJEKTORIENTIERUNG (OOP) & SYSTEM-ENTKOPPLUNG

1. **Abstraktion durch Abstrakte Basisklassen (ABC & Polymorphie):**
   * Keine isolierten Funktionen oder ad-hoc Klassen für Business-Logik.
   * Jede Kern-Komponente (z. B. Signale, Features, Fenster, Indikatoren) **muss** von ihrer jeweiligen abstrakten Basisklasse erben (`SignalDefinition`, `BaseFeature`, `PersistentWindow`, `BaseIndicator`).
   * Die aufrufende Engine interagiert **ausschließlich** mit dem abstrakten Interface, niemals mit konkreten Implementierungen.

2. **Vollständige Entkopplung & Inversion of Control (IoC):**
   * **Keine Zirkulären Abhängigkeiten:** Sub-Module (z. B. Worker oder Dialoge) dürfen niemals Kenntnis von konkreten Orchestratoren (wie `MainWindow`) haben.
   * **Kommunikation über Signals/Slots & Repositories:** UI-Komponenten und Datenverarbeiter kommunizieren strikt asynchron über PyQt-Signals oder Read-Only-Datenbankabfragen.
   * **Verboten:** Hardcoded Klassennamen-Checks (z. B. `if name == "win_statistics"`) in zentralen Repositories. Fenstertypen müssen sich generisch/dynamisch über Dekoratoren oder Registrys registrieren.

3. **Single Responsibility Principle (SRP - Eine Aufgabe pro Klasse):**
   * **UI-Klassen (`PySide6`):** Verantwortlich *nur* für Event-Handling und Rendering. Keine Berechnungen, Indikator-Logik oder direkte DB-Verbindungsaufbauten.
   * **Worker/Engine-Klassen:** Verantwortlich *nur* für Datenverarbeitung und mathematische Evaluierung. Absolut kein UI-Import oder GUI-Code.
   * **Repository-Klassen:** Kapseln den Datenbank-Zugriff exklusiv (SQL-Abfragen, Connection-Handling).

4. **Offen für Erweiterung, Geschlossen für Änderung (Open/Closed Principle):**
   * Neue Indikatoren, Strategien oder Fenster müssen durch **Hinzufügen neuer Dateien** implementiert werden können, ohne bestehende Kern-Dateien (`main.py`, `set_evaluator.py`, `feature_builder.py`) modifizieren zu müssen.

5. **Typsicherheit & Verlässliche Datenverträge:**
   * Strikte Nutzung von Python **Type Hints** (`typing`) für alle Funktionsparameter und Rückgabewerte.
   * Keine impliziten Dictionaries als Datenverträge zwischen Modulen; Datenströme nutzen definierte Dataframes, Primitive oder Typ-Aliase.

---

### 3. CODE- & ANTWORT-FORMATIERUNG
- **Prägnanz & Effizienz:** Verzicht auf lange theoretische Vorgeplänkel oder Höflichkeitsfloskeln. Biete direkt die funktionierende Lösung.
- **Vollständigkeit bei neuen Dateien:** Wenn eine neue Datei oder Klasse erstellt wird, liefere den vollständigen, ausführbaren Code.
- **Gezielte Refactorings:** Bei Änderungen an bestehendem Code zeige exakt die geänderten Abschnitte oder Methoden mit klaren Hinweisen, wo sie einzufügen sind, statt hunderte Zeilen unveränderten Code zu wiederholen.
- **Code-Blöcke:** Gib jeden Code-Block mit der expliziten Sprachauszeichnung an (`python ... `) und nenne in der ersten Zeile als Kommentar den relativen Dateipfad (z. B. `# src/database/db_manager.py`).
- **Dateipfade:** Verwende für Windows-Pfade ausschließlich `pathlib.Path` oder Raw-Strings (`r"..."`), um Pfad-Probleme unter Windows 11 zu vermeiden.

### 4. KEINE UI-TESTS & KEINE REGRESSIONSTESTS (HARTE REGEL)
- **Führe KEINE UI-Tests (PySide6/Qt/WebEngine) aus.** Sie sind viel zu zeitaufwändig.
- **Führe KEINE Regressionstests aus.** Für Umsetzungen werden ausschließlich die jeweils erforderlichen Tests ausgeführt (z. B. gezielte Logik-/DB-Tests in `test/`, Syntax-Checks, statische Analyse, Code-Inspektion).
- **Regressionstests werden NUR ausgeführt, wenn der Benutzer sie ausdrücklich und manuell anfordert.**
- Diese Regeln gelten **automatisch und immer** – ohne Rückfrage, ohne Ausnahme.
- Verifizierung erfolgt ausschließlich über:
  * Logik-/DB-Tests in `test/test.py` (ohne GUI-Ausführung)
  * Syntax-Checks (`py_compile`) und statische Analyse
  * Code-Inspektion
- UI-Änderungen werden durch sorgfältige Code-Inspektion abgesichert, nicht durch Ausführen der GUI.

### 4.5. BUGFIXING- & SPEED-MODUS (MAXIMALE EFFIZIENZ)
- **Aktivierung:** Erfolgt explizit durch die Anweisung *"Bugfixing-Modus"* oder die Übergabe einer konkreten Fehlermeldung/Tracebacks.
- **Disziplin & Fokus:** Maximale Geschwindigkeit, direkte Lösung ohne Grundsatzdiskussionen, Höflichkeitsfloskeln oder unaufgeforderte Refactorings.

#### A. Harte Test- & Ausführungsregeln
- **Keine UI- / GUI-Tests:** Unter keinen Umständen PySide6/Qt-Anwendungen starten oder UI-Skripte ausführen.
- **Keine Regressionstests:** Keine unbeteiligten Test-Suites oder kompletten Test-Pipelines laufen lassen.
- **Minimaler Backend-Check (1-Sekunden-Verifikation):**
  1. Statischer Syntax-Check via `python -m py_compile <geänderte_datei>.py`.
  2. Isolierter Backend-/DB-Logic-Test ausschließlich in `test/test.py` (falls zwingend nötig).
- **Manuelles Testen:** Der eigentliche Funktionstest der UI/Gesamtanwendung erfolgt direkt und manuell durch den Anwender.

#### B. Code-Ausgabe & Gezieltes Prompting (Diff-Only)
- **Patch-/Snippet-Format:** Es werden NIEMALS komplette 400-Zeilen-Dateien neu generiert, wenn sich nur wenige Zeilen ändern.
- **Präzise Verortung:** Ausgegeben werden nur die geänderten Methoden oder Blöcke mit relativer Pfadangabe als Kommentar in Zeile 1 und klaren Einfüge-Hinweisen (z. B. Zeilennummer oder bestehende Anker-Funktion).

#### C. Doku erst nach Freigabe
- **Keine Vorab-Dokumentation:** Während der Fehlersuche und Fix-Erstellung werden keine Dokumente (`docs/...`), Readmes oder Changelogs angepasst.
- **Protokollierung:** Doku-Einträge in `docs/AKTUELLE_UMSETZUNG.md` erfolgen erst, nachdem der Anwender den Fix explizit als funktionierend bestätigt hat.

#### D. Integrierte Zyklus-Booster (Prozess-Beschleuniger)
1. **Minimaler Kontext-Ballast:** Im Bugfixing-Modus werden keine Roadmaps, Architektur-Dokumente oder historischen Exporte eingelesen.
2. **Sammeln von zusammenhängenden Fixes:** Gehören mehrere kleine Fehler zusammen, werden alle Snippets in einer einzigen Antwort gebündelt, statt mehrere Interaktions-Schleifen zu drehen.
3. **Hot-Reloading berücksichtigen:** Code-Eingriffe so gestalten, dass App-Neustarts vermieden werden (z. B. durch Ausnutzung von `PluginRegistry.reload()` oder dynamischen Re-Imports).
4. **Fehler-Isolierung via Terminal-Asserts:** Kurze `assert`- oder `print`-Statements im Snippet platzieren, damit der Anwender beim manuellen Testen den genauen Fehlschlag-Punkt direkt im Terminal sieht.
---

### 5. PROJEKT-KONTEXT & ERKENNTNISSE (Stand 31.07.2026)

**SILVER M1 – Datenbasis & Zeitachse:**
- Die M1-Daten in `data/market_data.duckdb` sind konsistent mit der MT5-Ground-Truth: **keine leeren Candles, keine Lückenfüller, keine Duplikate, keine ungültigen Candles.**
- **Zeitkonvention (Wanduhr):** MT5 liefert Zeiten als **Berlin-Wanduhr-encoded Epochs** (empirisch: bei echter UTC 10:00 ist `tick.time` bereits die Zahl „12:00", diff ≈ +7200 s). `sync_market_data()` schreibt sie via `pd.to_datetime(..., unit="s", utc=True)` **1:1** in die DB; `EXTRACT(EPOCH)` und `fetch_historical_candles()` geben genau diese Wanduhr-Epochs an den Chart. ⇒ **Der Chart muss die Epochs DIREKT als Wanduhr formatieren – KEIN Berlin-Offset (+2h/+1h) in `getBerlinParts`, sonst sind alle Labels 2h zu spät.** Das ist automatisch DST-robust (Sommer CEST-encoded / Winter CET-encoded, jeweils direkt korrekt).
- **Handelspause:** SILVER (XAG) handelt 24/5. Die einzige tägliche Pause ist **Wanduhr 23:00–23:59** (Pause = 3720 s: letzte Bar 22:59 → erste 00:01). Zusätzlich Wochenend-Lücke (Fr 23:00 → So/Mo 00:00 Wanduhr).
- **Kontext-Regel:** „Keine leeren Candles/Lückenfüller in M1 – Zeitachse muss lückenlos sein außer Handelspause."

**Chart-Leerstelle „30.7.26 23:58" an der Tagesgrenze – GEFIXT (31.07.2026):**
- **Ursache:** `updateDaySeparators` (chart/js/03_chart_rendering.js) zeichnete Tageslinien mit **gebrochenen Zeiten** (`currTime - 0.5` / `currTime + 0.5`). LWC v5 fügt diese als **Phantom-Index-Slots** in die Timescale ein → sichtbare Leerstelle zwischen zwei Candles. Der Label-Fallback `_continuousTimeMap[ts] || ts` formatierte die Fake-Zeit → „Do 30.07.26 23:58" (Beweis: `test/check_resolve_realtime.js`).
- **Fix (4 Änderungen):**
  1. `03_chart_rendering.js`: Separator nutzt jetzt **echte Candle-Zeiten** `prevTime`/`currTime` (statt `±0.5`) → keine Phantom-Slots.
  2. `01_core.js`: Neue Funktion **`resolveRealTime(ts)`** (Binary-Search auf sortierten `_continuousKeys`) → liefert bei unbekannten Werten den **nächstgelegenen realen Zeitpunkt**, nie die Fake-Zeit.
  3. `04_live_updates.js`: `tickMarkFormatter`/`timeFormatter` und `updateDaySeparators`-Tag-Berechnung nutzen `resolveRealTime()`; `_continuousKeys` wird bei jedem `applyFullChartUpdate` neu aufgebaut.
  4. `02_time_utils.js`: **Wanduhr-Fix** – `getBerlinParts`/`formatDT` formatieren die (bereits Wanduhr-encoded) Roh-Epochs direkt ohne Berlin-Offset (+2h/+1h entfernt, `_isBerlinDST` entfällt). Pause = Wanduhr 23:00–23:59 (22:59 → 00:01).
- **Verifikation:** `node --check` auf allen 4 JS-Dateien, `test/check_resolve_realtime.js` (PASS: 3000/3000 exakte Treffer, Phantom-Zeit → „Fr 31.07.26 00:01" statt „Do 30.07.26 23:58"; Pausen-Grenze 22:59 → 00:01), `test/check_time_utils.js` (PASS), `test/check_html_template.py` (PASS), `test/check_broker_tz.py` (bestätigt: MT5 = Wanduhr-encoded).

**Testdateien in `test` (regelkonform, keine UI):**
`test.py`, `check_chart_data.py`, `test_db_lock.py`, `check_time_utils.js`, `check_html_template.py`, `check_m1_consistency.py` (Pausen-Erkennung Wanduhr 23:00–23:59), `simulate_chart_mapping.py`, `check_m1_midnight.py`, `check_mt5_m1_boundary.py`, `check_broker_tz.py` (MT5 = Wanduhr-encoded), `check_app_state.py`, `build_cont_map.py` (erzeugt `tmp_cont_map.json`), `check_resolve_realtime.js`.

---

### 6. INKREMENTELLES ARBEITEN & STOPP-PUNKTE (HARTE REGEL)

1. **Niemals die Fortsetzung in eine interaktive Frage/Abfrage setzen:** Die AI darf die Aufforderung zum nächsten Schritt **NIEMALS** in eine User-Interaktion (z. B. `AskQuestion`/Options-Dialog) verpacken. Es besteht die Gefahr, dass der Anwender versehentlich auf „Continue"/Enter/Tab drückt und damit eine Ausführung auslöst, die er nicht angeordnet hat.
2. **Status nur als einfacher Prompt ausgeben:** Nach Abschluss eines Schrittes gibt die AI ausschließlich den **Status** (was umgesetzt, validiert und committet wurde) als einfachen Text-Prompt aus.
3. **Warten auf expliziten Startschuss:** Die AI wartet danach, bis der Anwender **ausdrücklich** die Ausführung des nächsten Schrittes anweist (z. B. „continue" / „setze Schritt X um" / konkrete Anweisung). Ohne diesen expliziten Startschuss wird **kein** weiterer Schritt begonnen.
4. **Keine unbeabsichtigten Folgeaktionen:** Kein automatisches Anstoßen von Folge-Steps, kein vorauseilendes Commit des nächsten Schrittes und keine Vorschlags-Buttons/Abfragen für den nächsten Schritt – nur der reine Statusbericht.

---

### 7. NAMING CONVENTIONS & FILE HEADERS FOR SERVICES & INDICATORS

Bei der Erstellung oder Überarbeitung von Services (Plugins) und Indikatoren MÜSSEN folgende Regeln strikt eingehalten werden:

1. **Naming & Ordner-Präfixe:**
   * **Services (in `analytics/features/definitions/`):** Müssen das Präfix `srv_` tragen (z. B. `srv_grid_lines.py` mit `plugin_id = "srv_grid_lines"`). Begriffe wie `service`, `plugin` oder `feature` entfallen im Namen.
   * **Indikatoren (in `chart/indicators/`):** Müssen das Präfix `ind_` tragen (z. B. `ind_multi_ma.py` mit `indicator_id = "ind_multi_ma"`).
2. **PineScript-Input-Zone (Header-Dokumentation):**
   * Das `parameter_schema` / `default_params` muss **direkt auf Klassenebene unter dem Header-Docstring am Dateianfang** platziert werden, damit Eingaben und Defaults wie in PineScript sofort manuell anpassbar sind.
3. **MasterTree-Kategorisierung:**
   * Jedes Service-Plugin MUSS in `metadata["category"]` einen Slash-separierten Ordnerpfad angeben (z. B. `"category": "Swing Points/Preis-Grid"`), damit der MasterTree dynamische Kategorie-Ordner rendert.
```

--------------------------------------------------

### DATEI: Architektur.md
```md
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
* `db_service.py` ist seit 18.01.02 eine **Fassade (Re-Export-Wrapper)** ohne eigene Logik – Bestands-Caller importieren unverändert aus `db_service`, die Implementierung liegt in `db/db_pool.py`, `db/db_utils.py`, `db/schema_initializer.py`, `data_sync/mt5_sync_service.py` und `repositories/market_data_repository.py`.

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
├── repositories/                   # Repository-Schicht (market_data_repository.py)
├── workers/                        # Threads (data_sync_worker.py, live_tick_worker.py)
├── serviceui/                      # Service-UI-Paket (Phase 15): service_win.py, service_selector_dialog.py,
│   │                               #  service_selector_widget.py, master_tree.py, run_worker.py, common_widgets.py,
│   │                               #  status_panel.py, new_set_dialog.py, param_columns.py, symbols_win.py,
│   │                               #  trash_dialog.py, service_set_utils.py
├── ui/                             # Qt-Designer-Dateien (*.ui) + Fenster-Orchestrator (window_manager.py)
├── analytics_profile_repository.py # Analytics-Profil-Repository (app_data)
├── db_service.py                   # FASSADE (Re-Export-Wrapper), MT5-Sync-CLI (python db_service.py)
├── main.py                         # Haupt-Orchestrator (MainWindow)
├── persistent_win.py               # Fenster-Persistence & Registry (@register_persistent_window)
├── statistic_win.py                # Statistik-Fenster
├── properties_win.py               # Properties-Fenster (Optionen, DB-Service/VACUUM)
├── scrollable_content.py           # Scrollbare Content-Mixin
├── state_manager.py                # UI-Status, Fenstergeometrien & Presets
├── symbol_repository.py            # Symbol-Repository (App-Favoriten)
├── window_state_repository.py      # Fenster-Zustands-Repository
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

```

--------------------------------------------------

