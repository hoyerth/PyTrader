# Phase 16: Architektur Servive/Indikator - Feinarbeit Analytics

## 1. Allgemeine Grundsätze & Architektur-Invarianten (Phase 16)

1. **Git-Backup vor jedem Schritt:** Vor Beginn jedes Teilkapitels automatischen Git-Commit/Tag setzen (`phase16_step1`, `phase16_step2` usw.).
2. **Headless-Validierung (Keine UI-Tests):** Validierungen erfolgen rein headless (kein `QApplication.exec()`) über gezielte PyTest-/Python-Skripte im Unterordner `test/`.
3. **Strikte Trennung & MVVM (Kein SQL in UI):** UI-Klassen enthalten **keine SQL-Queries**. Datenfluss: `DuckDB` $\rightarrow$ `FeatureStoreReader` / `Repositories` $\rightarrow$ `Worker/ViewModel` $\rightarrow$ `UI-Pages`.
4. **Zentraler `EventBus`:** Fenster und Worker communicaten schwellenfrei über Events (`favorites_changed`, `profile_changed`, `service_set_changed`), um zirkuläre Abhängigkeiten zu vermeiden.
5. **Thread-Safety & DbPool:** DB-Zugriff erfolgt lock-frei über den Thread-local `DbPool` (`../../db_service.py`) – eine Verbindung pro Thread und DB-Datei.
6. **Wanduhr-Garantie:** Achsen, Zeitfilter und Visualisierungen formatieren streng die Berliner Wanduhrzeit aus MT5-Epochs ohne doppelte UTC-Offsets.
7. **Concurrency-Guard & Timer-Pausierung (Ergänzung 1):** Solange im ServiceWindow intensive Service-Berechnungen laufen (`SetRunWorker` / `HistoricalScanner`), wird der 45s-`sync_timer` entkoppelt via `EventBus` pausiert, um Locking-Konflikte und UI-Ruckler zu verhindern.
8. **Isolierter Test-Workspace (Ergänzung 2):** Alle neuen Test-Python-Dateien und temporären Test-Datenbanken (`*.duckdb`) müssen strikt im Unterordner `test/` erzeugt, gelesen und abgelegt werden – niemals im Projekt-Root oder im `data/`-Ordner.
9. **Open/Closed-Principle & Code-Preserving (Ergänzung 3):** Erweiterungen erfolgen strikt additiv durch neue Dateien. Auskommentierter Bestandscode darf nicht gelöscht werden und bestehende Kern-Klassen bleiben geschützt.
10. **Test-Cleanup (Ergänzung 4, Entscheidung 06.08.2026):** Tests werden NICHT aufbewahrt. Nach Abschluss jedes Phasenkapitels wird der Ordner `test/` aufgeräumt – es bleibt ausschließlich die Datei `test/test.py` (dauerhafter Test-Harness) bestehen. Alle temporären Check-Skripte (`check_*.py`/`*.js`), einmaligen Migrations-/Bereinigungsskripte, Test-Datenbanken (`*.duckdb`) und generierten Dateien (`tmp_*.json` u. Ä.) werden entfernt. Die Verifikation eines Kapitels erfolgt daher VOR der Bereinigung; danach existieren die Prüfskripte nicht mehr.

---
# Kapitel 16.07: Two-Tier Caching & Dynamic Range Management

## 1. Executive Summary & Zielsetzung
Zweistufige Datenarchitektur (**Two-Tier Caching**), die das Laden und Berechnen historischer Marktdaten (OHLCV) und Indikator-Overlays beim Scrollen in die Vergangenheit entkoppelt. Sie kombiniert minimale JS-Render-Last im Chart (Tier 1) mit einem erweiterten RAM-Datenpuffer im Python-Backend (Tier 2), um nahtloses, latenzfreies Scrollen ohne Performance-Einbußen zu gewährleisten.

---

## 2. Die Zwei-Stufen-Architektur (Two-Tier Concept)

* **Tier 1: Frontend Render Window (JS / LWC v5)**
  * **Umfang:** Hält strikt nur das aktive Darstellungsfenster (z. B. $N = \text{chart\_candle\_limit} \approx 1.000$ Kerzen) im DOM/Canvas.
  * **Aufgabe:** Gewährleistet flüssiges Rendering mit 60 FPS ohne Memory-Leaks.
  * **Verhalten:** Erhält synchrone, bereits berechnete Gesamt-Pakete (OHLCV-Candles + fertige Indikator-Payloads) direkt von Python per JS-Bridge.

* **Tier 2: Backend Memory Buffer (Python / `MATemplateEngine` & FeatureBuilder)**
  * **Umfang:** Puffert ein erweitertes Historien-Fenster im RAM (z. B. $M = N \cdot 10 \approx 10.000$ Kerzen).
  * **Aufgabe:** Führt Indikator-Berechnungen durch und bedient Nachlade-Anfragen des Frontends verzögerungsfrei (0 ms I/O-Latenz).
  * **Storage Fallback:** Lädt asynchron Blöcke aus `market_data.duckdb` (`ohlcv_bars`) nach, sobald der Tier-2-RAM-Puffer nach links erschöpft ist.

---

## 3. Dynamisches Nachladen, Warmup & Range Management

[ DuckDB Storage ] ──(Async Chunk)──> [ Tier 2: RAM Buffer (10.000) ] ──(Sliding View)──> [ Tier 1: JS Canvas (1.000) ]
│                                       │
[DB-Lookback]                           [Warmup Vorlauf]



1. **Sliding Window Shift (Tier 1 ↔ Tier 2):**
   * Das Frontend überwacht den Scroll-Rand via `visibleLogicalRangeChanged`.
   * Nähert sich die Viewport-Position dem linken Rand ($< 100$ verbleibende Kerzen im Canvas), fordert JS per Bridge den nächsten Daten-Ausschnitt aus dem Tier-2-RAM-Puffer an.
   * Der sichtbare Bereich in JS wird unter Beibehaltung der `visibleLogicalRange` nahtlos aktualisiert, ohne dass der Chart springt.

2. **Backend Chunk Fetch (Tier 2 ↔ DuckDB):**
   * Erreicht der Tier-1-Viewport die $20\%$-Grenze des Tier-2-RAM-Puffers, stößt Python im Hintergrund (QThread) das Nachladen des nächsten Chunks aus `market_data.duckdb` an.
   * DB-Fetches werden bei schnellem Scrollen debounced (300 ms).

3. **Lookback / Warmup Buffer (Mathematische Nahtstellen-Garantie):**
   * Zur Vermeidung von Indikator-Verzerrungen (z. B. bei rekursiven Alpha-EMAs / EHMA / Smoothed MA) liest Tier 2 aus DuckDB immer eine erweiterte Historie aus:
     $$\text{Warmup-Vorlauf} = \text{period} \cdot 4 + \text{smoothing} \cdot 3$$
   * Dieser reine Warmup-Vorlauf wird für die mathematische Einschwingphase genutzt und danach verworfen; nur valide Indikator-Punkte fließen in den Tier-2-Puffer und an Tier 1.

4. **Live-Tick-Entkopplung bei Historien-Ansicht:**
   * Befindet sich der Anwender in der Historie (nicht am rechten Rand), aktualisieren eingehende Live-Ticks den Tier-2-Puffer im Hintergrund, verändern jedoch nicht den aktiven Historien-Viewport in Tier 1.

---

# 16.08 Meta-Ordner im MasterTree (Dynamic Category Trees)

## 1. Executive Summary & Zielsetzung
Dynamische Verschachtelung von Service-Plugins und Standalone-Services im 2-Spalten-MasterTree (`ServiceSelectorWidget`) basierend auf dem Metadaten-Feld `"category"` der Plugins (z. B. `category: "Swing Points/Fraktale"`)[cite: 1]. Ermöglicht freie, beliebig tiefe Ordnerstrukturen ohne manuelle DB-Persistenz oder UI-Hardcoding (Open/Closed Principle)[cite: 1].

---

## 2. Metadaten-Spezifikation (Plugin-Ebene)
Jedes `PluginFeature` unter `analytics/features/definitions/` (bzw. `custom_plugins/`) kann in seinem `metadata`-Dict einen Slash-separierten Kategorienpfad deklarieren[cite: 1]:


# Beispiel: analytics/features/definitions/supertrend.py
metadata = {
    "display_name": "Supertrend (ATR Stop)",
    "category": "Trend Services/Volatilität & Bänder",  # <-- Dynamischer Pfad
    "description": "Dynamischer Trailing Stop auf ATR-Basis",
}

* **Fallback:** Fehlt das Feld `category` oder ist es leer, wird das Plugin direkt in der jeweiligen Hauptgruppe (`⚡ Standalone Services` bzw. `📦 Alle verfügbaren Plugins`) auf oberster Ebene einsortiert.

---

## 3. Anpassungs-Anleitung für die IDE-AI

### Schritt 1: `ServiceSelectorModel.build_tree()` in `analytics/engine/service_selector_model.py` anpassen

Erweitere die Baum-Aufbaulogik für die Gruppen `GROUP_STANDALONE` und `GROUP_PLUGINS` um eine Pfad-Knoten-Helper-Funktion (z. B. `_insert_into_category_tree`):

1. **Pfad-Parsing:**
* Lese `category = plugin.metadata.get("category", "")` aus.


* Ist `category` vorhanden, spalte den String am Slasher: `parts = [p.strip() for p in category.split("/") if p.strip()]`.


2. **Rekursive Knoten-Erzeugung:**
* Traverse/Erstelle Ordnerknoten entlang der Pfad-Teile `parts`.
* Ein Ordnerknoten besitzt das Format:

{
    "group": "category_node",
    "label": "📁 Ordnername",
    "children": [...]
}


3. **Einsortierung:**
* Platziere das finale Plugin-Node-Dict (mit `plugin_id`, `badge`, `last_execution`) im tiefsten Zielordner.

---

### Schritt 2: MasterTree UI-Rendering in `serviceui/master_tree.py` absichern

Stelle sicher, dass der `MasterTree` Category-Nodes (`group == "category_node"`) korrekt als nicht-auswählbare, aufklappbare Ordner mit Icon (`📁`) darstellt:

* Ordnerknoten erhalten das Ordner-Icon `📁` und sind expandierbar.
* Die Mehrfachauswahl / Checkbox-Logik ignoriert Ordnerknoten oder reicht den Check-Zustand kaskadierend an die Kind-Elemente weiter.

---

## 4. Verifikation (Backend & Tests)

1. **Statischer Check (Keine UI-Tests, Harte Regel 4):**
python -m py_compile analytics/engine/service_selector_model.py serviceui/master_tree.py

2. **Isolierter Logik-Test in `test/test.py`:**
* Teste `ServiceSelectorModel().build_tree()` mit gemockten Plugins, die geschachtelte Kategorien (`"A/B/C"`) besitzen.
* Assert: Die erzeugte Baumstruktur enthält die entsprechenden Ordnerknoten und Kinder in deterministischer Reihenfolge.

---

# Kapitel 16.08 – Review & Finale Entscheidungen (07.08.2026, kritische Prüfung gegen Ist-Code)

> **Status:** Kapitel 16.08 ist ein **Konzept/Plan**, keine Umsetzung. Der Ist-Code wurde kritisch geprüft (service_selector_model.py, master_tree.py, base_plugin.py, feature_builder.py). Die Entscheidungen **K1–K10 sind final** (Anwender-Review, 07.08.2026) und verbindlich für die Umsetzung. **Coding startet erst nach ausdrücklichem Startbefehl des Anwenders.**

## 1. Konsistenz mit dem Ist-Code (Abweichungen)

1. **`category` existiert bereits als Metadaten-Feld – aber mit Default `"General"`:**
   `PluginMetadata` (`analytics/features/plugins/base_plugin.py:157`) enthält schon das Feld `category`; `PluginFeature.metadata` (Zeile 209) liefert als **Default `"General"`**. Die Ist-Plugins setzen `"Grid"` (grid_lines_service.py / proximity_service.py). **Abweichung zum Kapitel:** Das Kapitel sagt „Fehlt `category` oder ist es leer → oberste Ebene". Mit dem Ist-Default würden Plugins ohne explizite Kategorie in einen Ordner `📁 General` einsortiert – nicht auf oberster Ebene. Der Fallback muss den Default `"General"` (und leere Strings) als „keine Kategorie" behandeln.
2. **`build_tree()` liefert heute FLACHE Kinder:** `standalone_nodes`/`plugin_nodes` (`service_selector_model.py:439/451`) sind flache Listen aus `{plugin_id, badge, last_execution}`. Es gibt **keine** Ordner-/Verschachtelungsstruktur, keinen Pfad-Parser, keinen Kategorie-Lookup. Das Kapitel-Knotenformat `{"group": "category_node", "label": "...", "children": [...]}` ist neu – `build_tree` muss es erzeugen (additiv, Bestandsverhalten bleibt für `GROUP_SETS`).
3. **`MasterTree._build_child_item` kennt nur 3 Gruppen:** Der Dispatch (`master_tree.py:348–354`) behandelt `GROUP_SETS`/`GROUP_STANDALONE`/`GROUP_PLUGINS` und gibt sonst `None`. `category_node`-Kinder würden verworfen. Für Ordner braucht es **Rekursion** (`_build_child_item` ruft sich für `children` selbst auf) + einen neuen Node-Typ.
4. **Kein `TYPE_CATEGORY`:** Es existieren `TYPE_GROUP`/`TYPE_SET`/`TYPE_SERVICE`/`TYPE_PLUGIN` (`master_tree.py:95–98`). Ordnerknoten benötigen einen eigenen Typ, damit Selektion, Info-Buttons, Checkboxen und Kontextmenü sie korrekt behandeln (oder bewusst ignorieren).
5. **Kapitel sagt `custom_plugins/` – Ist-Pfad ist `data/custom_plugins/`:** Der `PluginLoader` (`feature_builder.py`) scannt `DATA_DIR / "custom_plugins"`. Das Kapitel muss den Pfad präzisieren.
6. **Nur `PluginFeature`-Subklassen erscheinen im Tree:** `ATRNormalizedFeature`, `EMADiffFeature`, `GridLevelsFeature` sind `BaseFeature` (kein `PluginFeature`) und werden vom Loader **nicht** entdeckt. Das Kapitel impliziert korrekt „Jedes `PluginFeature`" – es sind aktuell nur `grid_lines` und `proximity` (plus Custom). Kein Handlungsbedarf, aber als Randbedingung dokumentiert.
7. **Verifikations-Test braucht einen Registry-Stub:** `ServiceSelectorModel.__init__` akzeptiert `registry=` (`service_selector_model.py:41–49`); `get_plugins()` liest `self.registry.plugins`, `get_plugin()` ruft `registry.get()`. Für den gemockten Plugin-Test muss ein **Duck-Typ-Stub** mit `.plugins`-Dict und `.get()` übergeben werden – nicht `PluginRegistry()` selbst.

## 2. Vollständigkeit – fehlende Aspekte

1. **Sortierregel für Ordner:** Das Kapitel fordert „deterministische Reihenfolge", definiert aber keine Sortierung. Festzulegen: Ordner alphabetisch, innerhalb eines Ordners wieder Ordner → Blätter (alphabetisch, case-insensitiv).
2. **Leere Ordner:** Ein deklarierter Kategorienpfad ohne Plugin-Kinder (z. B. nach Plugin-Entfernung) darf **keinen** leeren Ordner erzeugen – Ordner nur mit ≥ 1 Kind.
3. **Ordner-Kollision Ordner/Blatt:** Was, wenn ein Ordner (`📁 Grid`) und ein Blatt-Plugin dieselbe Anzeige-Ebene teilen? `_insert_into_category_tree` muss Ordner- und Blatt-Knoten auf derselben Ebene mischen können (deterministisch: Ordner zuerst, dann Blätter).
4. **Checkbox-/Multi-Select-Verhalten:** Das Kapitel lässt offen („ignoriert ODER kaskadierend"). Festzulegen: Ordnerknoten sind **nicht anhakbar** (kein `ItemIsUserCheckable`); die bestehende Plugin-Key-Logik (`TYPE_PLUGIN`, "", plugin_id) bleibt unverändert gültig – auch für Plugins innerhalb von Ordnern.
5. **Info-Buttons (Spalte 1):** Ordnerknoten dürfen **keinen** Info-Button tragen. `_attach_item_buttons` (`master_tree.py:479–533`) hängt Buttons nur an `TYPE_SERVICE/TYPE_SET/TYPE_PLUGIN` – Ordner werden automatisch übersprungen (kein Eingriff nötig, aber als Absicherung dokumentieren).
6. **Kontextmenü:** `_show_context_menu` (`master_tree.py:887`) behandelt Gruppe/Set/Service/Plugin. Ordnerknoten: **kein Kontextmenü** (oder nur ausgegraute Struktur-Aktionen) – kein `run_service_requested`/`info_requested` auf Ordnern.
7. **Selektion/Restore:** `current_selection()`/`_restore_selection()`/`_emit_selection_details()` behandeln `TYPE_SERVICE/TYPE_SET` (bzw. `TYPE_PLUGIN` für details). Ordnerknoten liefern nur `node_type` (set_id/service_id/plugin_id leer) → vorhandene Default-Pfade greifen automatisch (kein Crash-Risiko), muss aber im Test abgesichert werden.
8. **`badge`/`last_execution` in Ordnern:** Ordnerknoten haben **keine** Badges/Datum – nur die Plugin-Blätter tragen sie. Die bestehende `_build_plugin_item`-Logik bleibt pro Blatt unverändert.

## 3. Finale Entscheidungen K1–K10 (verbindlich für die Umsetzung)

### K1: Kategorie-Quelle & Fallback → `metadata.get("category")` mit Default-„General"-Behandlung
* Lese `category = str((plugin.metadata or {}).get("category") or "").strip()`.
* **Fallback (oberste Ebene):** `category` ist leer ODER `"General"` (Ist-Default aus `base_plugin.py:209`). Damit bleiben Plugins ohne explizite Kategorie auf der obersten Ebene der Hauptgruppe – exakt wie das Kapitel es verlangt, ohne Änderung des Base-Defaults.
* **Pfad-Parsing:** `parts = [p.strip() for p in category.split("/") if p.strip()]` (wie im Kapitel).

### K2: `build_tree()`-Struktur → Ordner-Dicts verschachtelt, additiv
* `GROUP_STANDALONE`/`GROUP_PLUGINS`: Kinder sind eine **Mischung** aus Blatt-Dicts (`{plugin_id, badge, last_execution}` – unverändert) und Ordner-Dicts (`{"group": "category_node", "label": "📁 <Name>", "children": [...]}` – rekursiv).
* `GROUP_SETS` bleibt unverändert (keine Kategorien für Set-Services).

### K3: Rekursion im MasterTree → `_build_child_item` rekursiv + `TYPE_CATEGORY`
* Neuer Node-Typ `TYPE_CATEGORY = "category"`.
* `_build_child_item`: erkennt Ordner-Dicts an `group == "category_node"` (oder `"children" in child`), erzeugt einen nicht-auswählbaren, expandierbaren Ordner-Knoten (📁 im Label, `~Qt.ItemIsSelectable`, kein `ROLE_PLUGIN_ID`) und ruft sich rekursiv für `children` auf.
* Plugin-Blätter innerhalb von Ordnern nutzen unverändert `_build_plugin_item`.

### K4: Checkbox/Multi-Select → Ordner nicht anhakbar
* Ordnerknoten erhalten **kein** `ItemIsUserCheckable`.
* `_on_item_changed` (Zeile 601): `TYPE_CATEGORY` wird von der Verarbeitung ausgenommen (Guard `node_type not in (TYPE_SET, TYPE_SERVICE, TYPE_PLUGIN)` reicht aus – `TYPE_CATEGORY` fällt durch).
* Plugin-Kinder in Ordnern: bestehende `(TYPE_PLUGIN, "", pid)`-Keys funktionieren unverändert (checked_services/checked_feature_ids/set_checked_feature_ids).

### K5: Info-Buttons → Ordner ohne Button
* `_attach_item_buttons` bleibt unverändert (skip für `TYPE_CATEGORY` automatisch). Absicherung: Test, dass ein Ordner-Knoten `itemWidget(item, 1) is None` liefert.

### K6: Kontextmenü → Ordner ohne Aktionen
* `_show_context_menu`: `TYPE_CATEGORY` erhält **kein** eigenes Menü (leere/Ausgrau-Struktur). Kein `run_service`/`info`/`move`/`remove` auf Ordnern.

### K7: Selektion/Restore → vorhandene Defaults
* `TYPE_CATEGORY` wird in `current_selection`/`_restore_selection`/`_emit_selection_details` nicht speziell behandelt → Default-Pfade liefern `{"set_id":"", "service_id":""}` bzw. nur `node_type`. Test absichern.

### K8: Sortierregel → Ordner vor Blättern, alphabetisch
* Je Ebene: **Ordner zuerst** (alphabetisch, case-insensitiv), danach **Blätter** (alphabetisch, case-insensitiv). Deterministisch über die bestehenden `sorted(...)`-Muster.
* Innerhalb eines Ordners gilt dieselbe Regel rekursiv.

### K9: Keine leeren Ordner
* `_insert_into_category_tree` erzeugt Ordner nur, wenn mindestens ein Plugin-Blatt (oder Unterordner) eingefügt wird. Leere Kategorienpfade erzeugen keine Knoten.

### K10: Verifikation (Kapitel-Erweiterung)
* `py_compile` auf `analytics/engine/service_selector_model.py` + `serviceui/master_tree.py`.
* Logik-Test in `test/test.py` (Teil 13, P16.08) mit **Duck-Typ-Registry-Stub** (`plugins`-Dict + `get()`):
  1. Plugin mit `category="A/B/C"` → Ordner A → B → C, Blatt im tiefsten Ordner.
  2. Plugin ohne/leerer/`"General"`-category → oberste Ebene (K1).
  3. Ordner-vor-Blatt-Sortierung + case-insensitiv (K8).
  4. Kein leerer Ordner bei Kategorie ohne Kinder (K9).
  5. MasterTree (offscreen): Ordner nicht auswählbar, kein Info-Button, Checkbox-Modus ignoriert Ordner; Plugin-Blatt in Ordner bleibt `checked_services`-fähig (K3/K4/K5/K7).
* Keine UI-Tests / keine Regressionstests (Regel 4).

> **Zusammenfassung (Anwender-Urteil):** Das Konzept 16.08 ist schlüssig und vollständig kompatibel mit dem Open/Closed-Prinzip. Kritisch zu prüfen war der **Ist-Default `"General"`** (K1), die **flache `build_tree()`-Struktur** (K2) und die **fehlende Rekursion im MasterTree** (K3). Alle offenen Detailfragen (Checkbox, Kontextmenü, Sortierung, leere Ordner, Verifikation) sind in K4–K10 final entschieden.
>
> **Kein Coding:** Die Entscheidungen sind dokumentiert. Eine Umsetzung von 16.08 erfolgt erst nach ausdrücklichem Startbefehl des Anwenders. *(Inzwischen erfolgt – siehe unten: Implementierungs-Log 16.08, 07.08.2026.)*

---
# Kapitel 16.08 – Implementierungs-Log (07.08.2026, 15:42 Uhr)

> **Status:** Kapitel 16.08 ist **umgesetzt** (K1–K10, siehe Review oben). Implementierungs-Log gemäß Regel 0c – Datum/Uhrzeit 07.08.2026 15:42 Uhr. Verifikation headless (Regel 4: keine UI-Tests, keine Regressionstests) über `test/test.py` Teil 13 (P16.08) sowie `py_compile` auf allen geänderten Dateien.

## 1. Umgesetzte Architektur (Ist-Stand)

* **Metadaten-Quelle (K1):** `metadata.get("category")` der Plugins (Slash-separierter Pfad). **Fallback:** leere Kategorie ODER der Ist-Default `"General"` (`base_plugin.py`) → Plugin bleibt auf der obersten Ebene der Hauptgruppe. Die Ist-Plugins `grid_lines`/`proximity` tragen `category="Grid"` → erscheinen seit 16.08 in einem `📁 Grid`-Ordner.
* **Baumstruktur (K2):** `build_tree()` erzeugt für die Gruppen `⚡ Standalone Services` / `📦 Alle verfügbaren Plugins` eine Mischung aus flachen Blatt-Dicts (`{plugin_id, badge, last_execution}` – unverändert) und verschachtelten Ordner-Dicts `{"group": "category_node", "label": "📁 <Name>", "children": [...]}` (rekursiv). `GROUP_SETS` bleibt unverändert.
* **MasterTree (K3):** Neuer Knotentyp `TYPE_CATEGORY`; `_build_child_item` ist jetzt rekursiv. Ordner sind nicht auswählbar, expandierbar, ohne Info-Button (K5), ohne Kontextmenü (K6) und im Checkbox-Modus nicht anhakbar (K4).

## 2. Umsetzung K1–K10 im Detail

* **K1:** `_category_parts(plugin)` – liest `metadata['category']`, zerlegt am Slash, `""`/`"General"` → `[]` (oberste Ebene).
* **K2:** `_insert_into_category_tree(nodes, parts, leaf)` – rekursive Ordner-Erzeugung entlang des Pfads; Ordner-Dicts im K2-Format.
* **K3:** `_build_child_item` erkennt `group == GROUP_CATEGORY` → `_build_category_item` (rekursiv, nicht auswählbar); Plugin-Blätter in Ordnern nutzen weiterhin `_build_plugin_item` (Badge/Datum unverändert).
* **K4:** Ordnerknoten erhalten `& ~(ItemIsSelectable | ItemIsUserCheckable)` – Qt setzt `ItemIsUserCheckable` standardmäßig (nach Testlauf behoben). `_on_item_changed`/`_sync_checked_from_tree`/`set_checked_feature_ids`/`clear_checks` verarbeiten `TYPE_CATEGORY` automatisch nicht (Guard auf SERVICE/SET/PLUGIN); Plugin-Kinder in Ordnern bleiben `checked_services`-fähig.
* **K5:** `_attach_item_buttons` überspringt `TYPE_CATEGORY` automatisch (kein Info-Button auf Ordnern) – per Test abgesichert.
* **K6:** `_show_context_menu` early-return für `TYPE_CATEGORY` (kein Menü, kein run/info/move/remove auf Ordnern).
* **K7:** `current_selection`/`_restore_selection`/`_emit_selection_details` liefern für Ordner den Default (`{"set_id":"","service_id":""}` bzw. nur `node_type`) – per Test abgesichert.
* **K8:** `_sort_category_nodes` – je Ebene Ordner zuerst (alphabetisch, case-insensitiv via `_cat_key`), dann Blätter; rekursiv in Unterordnern.
* **K9:** Ordner entstehen nur durch tatsächliche Blatt-Einfügung (`_insert_into_category_tree`) → keine leeren Ordner.
* **K10:** `py_compile` + `test/test.py` Teil 13 (P16.08) mit Duck-Typ-Registry-Stub.

## 3. Geänderte Dateien

| Datei | Änderung |
|---|---|
| `analytics/engine/service_selector_model.py` | `GROUP_CATEGORY`, `_cat_key`, `_category_parts`, `_insert_into_category_tree`, `_sort_category_nodes`, `_category_nodes`; `build_tree()`-Kinder via `_category_nodes` (additiv, Sets unverändert) |
| `serviceui/master_tree.py` | `TYPE_CATEGORY`, rekursiver `_build_child_item`, `_build_category_item`, Kontextmenü-Guard |
| `test/test.py` | Teil 13 (P16.08, T1–T5); Teil 5 an 16.08 angepasst (Plugin-Blätter rekursiv statt direkte Gruppen-Kinder – `grid_lines`/`proximity` liegen jetzt in `📁 Grid`) |

## 4. Verifikation (headless, 07.08.2026)

* `py_compile` auf `service_selector_model.py`/`master_tree.py`/`test.py` → EXIT=0.
* `test/test.py` (offscreen, venv, UTF-8): **Teil 13 (P16.08) alle 14 Checks PASS** – T1 verschachtelte Kategorie A/B/C (Ordner-Labels `📁 A/B/C`, Blatt im tiefsten Ordner, Blatt-Dict unverändert), T2 `General`-Fallback → oberste Ebene, T3 Ordner-vor-Blatt alphabetisch (abc/Grid/Trend, Blatt `middle`), T4 keine leeren Ordner, T5 MasterTree offscreen (Ordner nicht auswählbar, kein Info-Button, nicht anhakbar, Plugin-Blatt `checked_services`-fähig, Ordner-Selektion → Default).
* Teile 1–12 unverändert grün; weiterhin exakt **6 vorbestehende ServiceWindow-Fails** (P2/P5/H3/H4/H5/H7 – dokumentiert in E6, betrifft `serviceui/service_win.py` unverändert).
* Keine UI-Tests / keine Regressionstests ausgeführt (Regel 4).

## 5. Offene Punkte (bewusst, nicht Teil dieser Umsetzung)

* Manuelle GUI-Verifikation des User-Erlebnisses (Ordner-Einklappen, Kontextmenü-Klick auf Ordnern) durch den Anwender.
* Weitere Kategorienvergabe für künftige Plugins (z. B. `custom_plugins/` – Pfad ist `data/custom_plugins/`); die Registry-Entdeckung bleibt unverändert.

