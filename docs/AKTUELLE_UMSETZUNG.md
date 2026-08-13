# Phase 21: Fachliche Feinabstimmung Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 21)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase21_step1`, `phase21_step1` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Codebase-Formatierung:** Exakt **4 Leerzeichen** Einrückung (PEP8-Standard) und **exakt 1 Leerzeile** Spacing zwischen Methoden und Funktionsblöcken. Kein Umformatieren unbeteiligter Altbestand-Dateien.
4. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`. `MasterTree`-Selektionen übergeben aufgelöste `feature_ids` sowie `instance_hashes` direkt an `view_model.set_feature_ids(ids, hashes)`.
5. **Zentraler `EventBus`:** Fenster und Worker kommunizieren schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
6. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`db/db_pool.py`) – eine Verbindung pro Thread und DB-Datei. Die Fassade `db_service.py` bleibt als Re-Export-Wrapper für bestehende Caller erhalten.
7. **Tree-Persistenz & Kategorisierung:** 
   - Service-Kategorien werden primär im Code/Plugin über `metadata["category"]` (Slash-separierter Ordnerpfad) deklariert.
   - Ordner-Kategorien für Service-Sets werden im `category`-Feld der `ServiceSetDefinition` / des `save_set()`-Payloads persistiert.
   - Parameter-Varianten (Clones/Presets) werden transparent über `indicator_presets` und `instance_hash` im FeatureStore geführt.
8. **Wanduhr-Garantie (Invariante 7):** MT5-Epochs sind bereits Berlin-Wanduhr-encoded. SQL-Extraktionen (Heatmap, DOW, Hour, Date) nutzen strikt `bar_time AT TIME ZONE 'UTC'`, um eine fehlerhafte automatische Umrechnung durch DuckDB in Lokalzeiten zu unterbinden.
9. **Concurrency-Guard & Timer-Pausierung:** Solange im ServiceWindow intensive Service-Berechnungen laufen (`ServiceRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
10. **Isolierter Test-Workspace & Cleanup:** Neue Test-Skripte und temporäre `*.duckdb`-Dateien gehören strikt nach `test/`. Nach Abschluss jedes Phasenkapitels wird `test/` aufgeräumt – es verbleibt nur der Test-Harness `test/test.py`.
11. **Open/Closed-Principle & Code-Preserving:** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden; bestehende Kern-Klassen bleiben geschützt.
12. **Naming Conventions & PineScript-Input-Zone:** 
    - Services in `analytics/features/definitions/` nutzen strikt das Präfix `srv_` (`plugin_id = "srv_..."`).
    - Indikatoren in `chart/indicators/` nutzen strikt das Präfix `ind_` (`indicator_id = "ind_..."`).
    - Füllwörter (`service`, `plugin`, `indicator`) entfallen im Dateinamen.
    - Das `parameter_schema` liegt direkt am Dateianfang unter dem Header-Docstring.
    - Jedes Service-Plugin deklariert `metadata["category"]` für die dynamische Kategorie-Ordner-Struktur im MasterTree.

---

# 21.03.21 – Confluence-Analyse & Hotspot-Orchestrierung (Multi-Service & Multi-Modus Häufung)

---

## 🎯 1. Zielstellung & Fachliche Motivation

Das Ziel dieser Erweiterung ist die optische Erkennung von **Signal-Häufungen (Hotspots / Lichtsäulen)** über verschiedene Services, Parameter-Varianten und Berechnungsmodi hinweg.

Bisherige Kennzahlen-Analysen (wie Mittelwerte oder Einzel-Filter) verkleinern die Ergebnismenge auf isolierte Werte und verdecken das eigentliche Confluence-Muster. Das Kapitel 21.03.21 spezifiziert die Entkopplung von Einzel-Wert-Analysen hin zu einer echten **Multi-Service-Überlappung**.

---

## 🔍 2. Problemstellung & Ursachenanalyse

| Problem in der Praxis | Technische Ursache im Bestand |
| --- | --- |
| **Einzel-Filter verzerren Häufung** | Strikte Filter auf genau *einen* Service oder *einen* Modus isolieren Datenpunkte und verhindern das Erkennen von Signal-Überschneidungen.

 |
| **Mittelwert-Aggregation (`AVG`) ungeeignet** | Ein Mittelwert über ein $5$-Minuten-Raster berechnet die durchschnittliche Stärke eines Ticks, zeigt aber nicht die *Anzahl* der zusammengelaufenen Indikatoren.

 |
| **Starres Feld-Dropdown** | Bei reinen Signal-Zählungen ist die Auswahl eines konkreten JSON-Feldes (z. B. `strength_value`) mathematisch irrelevant und verwirrt den Anwender.

 |

---

## 🏗️ 3. Architektur- & Bedienkonzept

### 3.1 Das 3-Ebenen-Bedienmodell für Confluence

┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 1. SERVICE PICKER: Multi-Select active                                                │
│    [x] srv_trend_breakout  [x] srv_swing_structure  [x] srv_proximity                  │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 2. HEATMAP-WIDGET STEUERZEILE                                                           │
│    [ Aggregation: Confluence (COUNT DISTINCT) ▾ ]  [ Modus: 🌐 Alle Modi (Confluence) ▾ ] │
│    [ Feld: (deaktiviert / alle Felder) ▾ ]                                             │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ 3. VISUELLE HOTSPOT-HEATMAP (Diskrete Farbskala E7)                                     │
│    0 Services = Hellgrau  |  1 Service = Gelb  |  2 = Cyan  |  3–4 = Orange  |  5+ = Rot  │
└────────────────────────────────────────────────────────────────────────────────────────┘


### 3.2 Modus-Dropdown (`_combo_mode`) im Confluence-Kontext

* **Standard-Einstellung:** `🌐 Alle Modi (Confluence)` (`service_mode = "all"`).
* **Verhalten:** Das System filtert nicht auf einen einzelnen Berechnungsmodus (`source_mode`), sondern fasst alle im Service Picker gecheckten Services und deren aktive Modi in einer gemeinsamen Matrix zusammen.
* **Fokussierter Modus:** Eine konkrete Modus-Auswahl (z. B. `ZigZag_ATR`) erfolgt nur, wenn gezielt isolierte Modus-Überlappungen analysiert werden sollen.



### 3.3 Status des Feld-Dropdowns (`_combo_field`) bei Confluence

* **Regel:** Sobald als Aggregation **`confluence_count`** oder **`count`** gewählt ist, wird das Feld-Dropdown **deaktiviert (ausgegraut)**.
* **Begründung:** Bei Zählungen untersucht die Engine das Vorhandensein von Signalen (Rows/Services). Ein konkretes Datenfeld wird nur bei Wert-Aggregationen (`AVG`, `SUM`, `MIN`, `MAX`) benötigt.



---

## 🧮 4. Aggregations-Typen im Vergleich

Für die visuelle Darstellung von Häufungen werden drei spezifische Aggregations-Verfahren unterstützt:

### 1. Standard-Confluence (`confluence_count` / `COUNT DISTINCT`)

* **SQL:** `COUNT(DISTINCT feature_id)`
* **Bedeutung:** Zählt exakt, wie viele *unterschiedliche* Services/Plugins im Zeit-/Preis-Raster ein Signal geliefert haben.
* **Einsatz:** Primäre Standard-Analyse für Hotspots.

### 2. Gewichtete Confluence (`weighted_confluence`)

* **Formel:** $\text{Score} = \sum (W_{\text{Service}} \cdot \text{Signal})$ mit $W_{\text{D1}} = 3.0, W_{\text{H4}} = 2.0, W_{\text{M1}} = 1.0$.
* **Bedeutung:** Übergeordnete Makro-Signale wiegen schwerer als Mikro-Signale.
* **Einsatz:** Verhindert, dass reine M1-Rauschen-Häufungen dominieren.

### 3. Intensitäts-Confluence (`intensity_confluence`)

* **Formel:** $\text{Score} = \sum (\text{strength\_value}_{\text{Service\_i}})$.
* **Bedeutung:** Summiert die berechnete Signalstärke aller beteiligten Services.
* **Einsatz:** Unterscheidet zwischen schwachen Konsolidierungs-Hits und hoch-dynamischen Impuls-Überlappungen.


---

## 🛠️ 5. Schritt-für-Schritt Umsetzungsanleitung für die IDE

### Schritt 1: Reader-Erweiterung für `COUNT DISTINCT` (`analytics/engine/feature_store_reader.py`)

In `fetch_generic_heatmap()` die Aggregation für Confluence absichern:

# analytics/engine/feature_store_reader.py

if agg_key == "confluence_count":
    # Zählt die Anzahl unterschiedlicher Services pro Raster-Zelle
    agg_sql = "COUNT(DISTINCT feature_id) AS val"
elif agg_key == "count":
    agg_sql = "COUNT(*) AS val"

### Schritt 2: Deaktivierungs-Steuerung im UI-Widget (`analytics/ui/heatmap_widget.py`)

In `_update_controls()` des `HeatmapWidget` die Feld-Freigabe an die Aggregation koppeln[cite: 5]:

# analytics/ui/heatmap_widget.py

def _update_controls(self) -> None:
    agg = str(self._combo_agg.currentData() or "confluence_count")
    is_value_agg = agg in ("avg", "sum", "min", "max")
    
    # Feld-Dropdown nur aktivieren, wenn eine Wert-Aggregation gewählt ist
    self._combo_field.setEnabled(is_value_agg)
    if not is_value_agg:
        self._combo_field.setToolTip("Bei Confluence/Count-Aggregation nicht erforderlich.")


### Schritt 3: ViewModel-Anpassung für Multi-Modus-Freigabe (`analytics/engine/analytics_view_model.py`)

Sicherstellen, dass `service_mode = "all"` bei Confluence-Queries keine `source_mode`-Einschränkung in SQL einfügt[cite: 5]:

# analytics/engine/analytics_view_model.py

def apply_smart_preset_confluence(self) -> None:
    """Schaltet auf Multi-Service-Confluence um."""
    self.set_service_mode("all")  # Alle Modi einbeziehen
    self.set_heatmap_config("date", "service_id", "", "confluence_count")

---

## 📊 6. Akzeptanzkriterien für die Headless-Validierung (`test/test.py`)

1. **Confluence-Distinct-Test:** Bei 3 verschiedenen Services, die auf derselben Bar feuern, liefert `fetch_generic_heatmap(..., agg="confluence_count")` exakt den Wert $3.0$ für die Zelle[cite: 5].
2. **Multi-Modus-Inklusion-Test:** Bei `service_mode = "all"` enthält das SQL-Ergebnis Signale aus *allen* aktiven Modi der gewählten Services (kein Ausschluss einzelner Modi)[cite: 5].
3. **Control-State-Test:** Bei Auswahl von `agg = "confluence_count"` schaltet die UI `_combo_field` auf `enabled = False`[cite: 5].

---

# 21.03.21 – Entscheidungsprotokoll & Umsetzungs-Spezifikation (13.08.2026 20:06)

## 1. Review-Ergebnis (Kapitel vs. Ist-Stand)

| Kapitel-Abschnitt | Status im Bestand |
| --- | --- |
| §4.1 / §5 Schritt 1: `COUNT(DISTINCT feature_id)` | ✅ vorhanden (`analytics/engine/feature_store_reader.py` Z. 1283-1286, `HEATMAP_AGGREGATIONS` Z. 117) |
| §5 Schritt 2 / §3.3: Feld-Dropdown-Deaktivierung (F7) | ✅ vorhanden (`analytics/ui/heatmap_widget.py` `_update_controls` / `_VALUE_AGGS`) |
| §5 Schritt 3: `apply_smart_preset_confluence()` | ⚠️ vorhanden, aber OHNE `set_service_mode("all")` |
| §3.2 Modus-Dropdown Standard "all" | ✅ vorhanden als `_combo_mode_filter` / „[Alle Modi]" (data "all") |
| §4.2 `weighted_confluence` | ❌ nicht vorhanden |
| §4.3 `intensity_confluence` | ❌ nicht vorhanden (Datenbasis `strength_value` existiert in `srv_swing_*`) |
| E7-Farbskala | ⚠️ vorhanden, aber daten-gebunden (0..vmax, „Meldung 7") statt fest 0..5 |
| §6 AK1 (Distinct-Count) | ✅ test.py „37 b1" (2 Services → 2.0) |
| §6 AK2 (Modus-"all"-Inklusion) | ❌ kein Test vorhanden |
| §6 AK3 (Control-State) | ✅ test.py „20.03.02 o) F7" |

## 2. Entscheidungen (Benutzer-Freigabe + fachliche Bewertung)

1. **Vorgehen: Option (a)** – Bestand nutzen und ergänzen; keine Neu-Implementierung bereits vorhandener Funktionalität.
2. **`weighted_confluence`: NICHT umsetzen (zurückgestellt).** Fachliche Begründung: Der Confluence-Preset läuft mit `all_timeframes=False` (genau EIN Timeframe). Die TF-Gewichte (D1=3.0/H4=2.0/M1=1.0) wären damit konstant → `weighted_confluence` degeneriert zu `confluence_count × Konstante` und liefert keinerlei Zusatzinformation. Eine sinnvolle Umsetzung erfordert eine Multi-TF-Query (`all_timeframes=True`), was außerhalb des Scopes dieses Kapitels liegt (dort existiert bereits das Preset „Service-Timeframe" mit `count`).
3. **`intensity_confluence`: NICHT als eigene Aggregation.** Fachliche Begründung: Die Intensitäts-Analyse ist bereits vollständig über die bestehende Kombination „Aggregation = `SUM` + Feld = `strength_value`" abgedeckt (`srv_swing_momentum`, `srv_swing_structure`, `srv_swing_volume_profile` schreiben den Key). Eine eigene Aggregation wäre nur ein Alias mit fixem Feld, würde aber die §3.3-Feld-Logik brechen (bei Zählungen deaktiviert; bei einer Wert-Aggregation wäre ein implizit fixes Feld inkonsistent) und Services ohne `strength_value` (z. B. `srv_trend_breakout`, `srv_proximity`) still ausblenden → irreführend. Wert-Aggregationen nutzen ohnehin die Viridis-Skala (`heatmap_widget.py` Z. 1638ff), die für Summenwerte kalibriert ist; die diskrete E7-Konfluenz-Skala bleibt Zählungen vorbehalten.
4. **`apply_smart_preset_confluence()`: `set_service_mode("all")` ergänzen (JA).** Fachliche Begründung: Der Kern des Kapitels ist die Hotspot-Orchestrierung über ALLE Modi hinweg (§3.2-Standard = "all"). Hat der Nutzer vorher einen konkreten Modus gefiltert, muss der Preset diesen zurücksetzen, sonst zeigt „[? Signal-Confluence]" still nur den gefilterten Modus (widerspricht der Kapitel-Spezifikation).
5. **AK2-Test ergänzen (JA).** Fachliche Begründung: Die Modus-Inklusion bei `service_mode = "all"` ist das Kernverhalten von §3.2/§6 AK2 und aktuell ungetestet.
6. **E7-Farbskala: Verhalten beibehalten** (daten-gebundene Levels 0..vmax, „Meldung 7" vom 11.08.2026). Nur Kapiteltext wird an das Ist-Verhalten angepasst – die feste 0..5-Skala ist überholt.
7. **Naming: Anpassung an den IST-Stand** – `_combo_mode_filter` / „[Alle Modi]" (data "all") statt Kapitel-`_combo_mode` / „🌐 Alle Modi (Confluence)"; funktional gleichwertig.

## 3. Umsetzungs-Spezifikation (Coding – wird NUR auf manuellen Startbefehl ausgeführt)

### Schritt A: Preset-Reset des Modus-Filters (`analytics/engine/analytics_view_model.py`)
In `apply_smart_preset_confluence()` VOR `set_heatmap_config(...)` ergänzen:
- `self.set_service_mode("all")` – bereits idempotent (early-return bei aktuellem `"all"`); bei echter Änderung Dirty-Flag + Refresh von `QUERY_FEATURES` und allen Datenquellen (Tabelle, beide Heatmaps, Scatter, Verteilung).

### Schritt B: AK2-Headless-Test (`test/test.py`)
- Temporäre `analytics.duckdb` (im Unterordner `test/`!) mit `feature_store`-Rows inkl. top-level `source_mode` (z. B. 2 Services × je 2 Modi = 4 Zeilen auf derselben Bar).
- `fetch_generic_heatmap(..., x_dim="date", y_dim="hour", agg="count", service_mode="all")` → Zellenwert exakt `4.0` (alle Modi inkludiert, kein `source_mode`-WHERE).
- `fetch_generic_heatmap(..., agg="count", service_mode="<Modus1>")` → Zellenwert exakt `2.0` (nur ein Modus je Service).
- Kein UI-Test (Regel 4), reiner Reader-Test.

## 4. Implementierungs-Log (Doku-Teil, erledigt)

- **13.08.2026 20:06:** Kapitel 21.03.21 gründlich gegen den Ist-Stand analysiert (Review-Tabelle); Entscheidungsprotokoll + Umsetzungs-Spezifikation (Schritt A/B) in `docs/AKTUELLE_UMSETZUNG.md` dokumentiert; Git-Commit `phase21_step1` gesetzt. **Kein Coding ausgeführt** – Umsetzung wartet auf den manuellen Startbefehl des Anwenders.
