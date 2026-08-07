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

# 16.08.02 Nachtrag Bereinigung: Umstellung Parameter Position in Definitionsdateien
### Schritt 5: Schema-Platzierung (PineScript-Input-Zone)
* In allen `srv_*.py` und `ind_*.py` Dateien muss das `parameter_schema` / `default_params` **direkt auf Klassenebene unter dem Header-Docstring** platziert werden.
* Jeder Parameter im Schema MUSS einen aussagekräftigen Kommentar bzw. ein `"description"`-Feld enthalten, damit der Anwender Inputs und Defaults wie in PineScript direkt am Dateianfang manuell anpassen kann.

---

# Kapitel 16.08.02 – Review & Entscheidungen (07.08.2026, kritische Prüfung gegen Ist-Code)

> **Status:** Kapitel 16.08.02 ist ein **Konzept/Plan**, keine Umsetzung. Der Ist-Code wurde kritisch geprüft (alle `srv_*.py`/`ind_*.py`-Definitionsdateien, Basisklassen `base_plugin.py`/`base_indicator.py`). Es wurden **5 Entscheidungen (M1–M5)** getroffen. Die Entscheidungen **M1–M5 sind final** und verbindlich für die Umsetzung. **Coding startet erst nach ausdrücklichem Startbefehl des Anwenders.**

## 1. Ist-Zustand (Schema-Platzierung je Definitionsdatei)

| Datei | Schema-Quelle | Aktuelle Position | `description` je Key? |
|---|---|---|---|
| `analytics/features/definitions/srv_grid_lines.py` | `@property def parameter_schema` (Z. 210) | Klassenkörper (am Ende) | ✓ 9 Keys |
| `analytics/features/definitions/srv_proximity.py` | `@property def parameter_schema` (Z. 178) | Klassenkörper | ✓ 3 Keys |
| `chart/indicators/ind_fixed_grid_proximity.py` | Modul-Konstante `_FIXED_GRID_PROXIMITY_SCHEMA` (Z. 108) | Dateianfang (vor der Klasse, nach den Helfern) | ✓ 13 Keys |
| `chart/indicators/ind_moving_averages.py` | `@staticmethod _build_schema()` (Z. 142) – programmatisch (66 Keys, Schleife `for x in range(1, 9)`) | Klassenkörper | ✓ 66 Keys (generiert) |

Zusätzlich geprüft:
* **`default_params`** ist in beiden Basisklassen eine **generische, abgeleitete Methode** (`base_plugin.py:309`, `base_indicator.py:29`), die die Defaults aus `full_parameter_schema()` extrahiert – **kein** Datenattribut in den Definitionsdateien.
* **`grid_levels.py` / `ema_diff.py` / `atr_normalized.py`** (BaseFeature, N1 aus 16.08.01) besitzen **kein** `parameter_schema`/`default_params` → **nicht betroffen** (Scan über alle Projekt-Python-Dateien).
* **`parameter_schema`** ist in `PluginFeature` ein `@abstractmethod`-Vertrag (`base_plugin.py:243–244`); alle 4 Dateien implementieren ihn als `@property` und liefern flache Kopien (`{k: dict(v) ...}`).

## 2. Entscheidungen (M1–M5)

### M1: `parameter_schema` bleibt `@property` (ABC-Vertrag) – KEIN Klassenattribut-Dict
* **Begründung:** `base_plugin.py:243–244` verlangt `parameter_schema` als (property-artige) Methode; `full_parameter_schema` (`base_plugin.py:272`) und `validate_params` (`base_plugin.py:319`) rufen `self.parameter_schema` lesend auf. Ein Klassenattribut-Dict wäre ein **geteiltes, mutables Objekt** über alle Instanzen – die Property erzeugt pro Aufruf eine frische flache Kopie und schützt vor Cross-Plugin-Mutation. Das einheitliche Property-Muster aller Plugins/Indikatoren bleibt unangetastet (Ergänzung 3: keine bestehenden Kern-Strukturen überschreiben).
* **Wirkung:** „Auf Klassenebene" ist bereits erfüllt (Property = Methode auf Klassenebene). Die PineScript-Intention wird über M3 erfüllt.

### M2: `default_params` wird NICHT ausgerollt
* **Begründung:** `default_params` leitet sich generisch aus dem Schema ab (siehe Ist-Zustand). Wer das Schema am Dateianfang sieht, sieht damit implizit alle Defaults. Ein statisches Ausrollen wäre Duplikation ohne fachlichen Nutzen und würde die Basis-API verändern.

### M3: PineScript-Input-Zone via **Modul-Konstanten** (einheitliches Muster, analog `_FIXED_GRID_PROXIMITY_SCHEMA`)
* Die **Schema-Dicts** werden als benannte Modul-Konstanten **direkt unter dem Header-Docstring** (bzw. im Konstanten-Block am Dateianfang) platziert; die `parameter_schema`-Property gibt `{k: dict(v) for k, v in _XXX_SCHEMA.items()}` zurück (flache Kopie – Verhalten identisch, getestete Invarianzen bleiben).
* Betroffene Dateien (nur **Umsetzung nach Startbefehl**):
  * `srv_grid_lines.py`: Schema-Inhalt der Property (Z. 210–224) → neue Modul-Konstante `_GRID_LINES_SCHEMA` (8+1 Keys, `custom_levels` bleibt im Schema, nicht in `parameter_order`).
  * `srv_proximity.py`: Schema-Inhalt der Property (Z. 178–190) → neue Modul-Konstante `_PROXIMITY_SCHEMA` (3 Keys).
  * `ind_fixed_grid_proximity.py`: **bereits konform** (`_FIXED_GRID_PROXIMITY_SCHEMA` am Dateianfang). Optional nur: Konstante **vor** die privaten Helfer-Funktionen (Z. 49–102) ziehen, damit die „Input-Zone" unmittelbar nach dem Header beginnt (rein kosmetisch).
  * `ind_moving_averages.py`: `_build_schema()` **bleibt programmatisch** (66 Keys, MA1-Spezial + MA2..8, Sibling-Defaults 16.06, Kontrastfarben D4). Eine statische Ausrollung wäre ein Wartungsdesaster und würde die in `test/test.py` hart getesteten Invarianzen (M1: 66 Keys, Sibling-Defaults) gefährden. Optional: `_build_schema` als **Modul-Funktion** in den Konstanten-Block am Dateianfang ziehen (referenziert nur Modul-Konstanten `MA_TYPES`/`LINE_STYLES`/`_MA_*`).

### M4: `description`-Vollständigkeit ist BEREITS erfüllt
* Alle Parameter in allen 4 Definitionsdateien tragen bereits ein aussagekräftiges `"description"`-Feld (geprüft, s. Ist-Zustand). Kein Nachrüsten nötig.
* Optional (Komfort, im Zuge von M3): Die Header-Docstrings der `srv_*.py`-Dateien erhalten einen **PARAMETER-Referenzblock** (PineScript-Stil), der die Konstanten-Namen referenziert.

### M5: Keine DB-Migration / keine test.py-Änderung nötig
* Die Schemas werden **inhaltlich nicht verändert** (nur Position des Dict-Literals) → keine DB-Migration, keine Verhaltensänderung, `test/test.py` bleibt unverändert grün.
* `docs/x_Exports.md` wird nicht angefasst.

## 3. Verifikation (headless, Regel 4 – NUR nach Startbefehl)

1. **`py_compile`:** `srv_grid_lines.py`, `srv_proximity.py`, `ind_fixed_grid_proximity.py`, `ind_moving_averages.py`.
2. **`test/test.py`:** unverändert grün (Teile 4–13; Schemas inhaltlich identisch).
3. **Konsistenz-Scan:** `parameter_schema`-Properties liefern flache Kopien; keine doppelten Dict-Objekte.
4. **Keine UI-/Regressionstests** (Regel 4).

> **Kein Coding:** Die Entscheidungen sind dokumentiert. Eine Umsetzung von 16.08.02 erfolgt erst nach ausdrücklichem Startbefehl des Anwenders.

---

# Kapitel 16.08.02 – Implementierungs-Log (Umsetzung, 07.08.2026 16:46)

> **Status:** UMSGESETZT (Anwender-Startbefehl "umsetzen" / "commit und push" 07.08.2026). M3 + M4-Komfort sind umgesetzt und headless verifiziert. M1/M2/M5 als reine Entscheidungen ohne Coding.

## 1. Umgesetzte Änderungen

### 1.1 `analytics/features/definitions/srv_grid_lines.py`
* **Neue Modul-Konstante `_GRID_LINES_SCHEMA`** direkt nach den Imports (PineScript-Input-Zone unter dem Header-Docstring) – Inhalt = ehemaliges Inline-Schema der `parameter_schema`-Property (9 Keys: `step_size`, `steps_around`, `custom_levels`, `prox_level1..6`).
* **`parameter_schema`-Property** gibt jetzt eine flache Kopie zurück: `{k: dict(v) for k, v in _GRID_LINES_SCHEMA.items()}` (M1: kein geteiltes mutable Dict, ABC-Vertrag `base_plugin.py:243–244` unverändert).
* **Header-Docstring:** PARAMETER-Referenzblock ergänzt (verweist auf `_GRID_LINES_SCHEMA`, M4-Komfort).

### 1.2 `analytics/features/definitions/srv_proximity.py`
* **Neue Modul-Konstante `_PROXIMITY_SCHEMA`** direkt nach den Imports (3 Keys: `visit_pct`, `time_window_mins`, `use_time_filter`).
* **`parameter_schema`-Property** → flache Kopie (`{k: dict(v) for k, v in _PROXIMITY_SCHEMA.items()}`).
* **Header-Docstring:** PARAMETER-Referenzblock ergänzt (M4-Komfort; Hinweis: visuelle Parameter gehören zum Indikator).

### 1.3 Bewusst NICHT verändert (gemäß M3/M5)
* `chart/indicators/ind_fixed_grid_proximity.py`: bereits konform (`_FIXED_GRID_PROXIMITY_SCHEMA` am Dateianfang, Z. 108) – keine Änderung.
* `chart/indicators/ind_moving_averages.py`: `_build_schema()` bleibt programmatisch (66 Keys, Schleife `for x in range(1, 9)`) – keine statische Ausrollung (Wartungsdesaster, test-geschützte Invarianzen M1).
* `default_params`: bleibt generisch in den Basisklassen abgeleitet (M2), kein Ausrollen.
* Keine DB-Migration, keine Änderung an `test/test.py` (M5).

## 2. Verifikation (headless, Regel 4)

1. **`py_compile`:** `srv_grid_lines.py`, `srv_proximity.py` OK.
2. **Gezielter Schema-Check** (`test/_tmp_160802_check.py`, danach entfernt): **14/14 PASS** – Konstanten == Property-Inhalt, flache Kopien (getrennte Dict-Objekte), Defaults korrekt (`step_size=0.5`, `visit_pct=0.05`, `prox_level1=0.0`), `description` je Key, `default_params` funktionsfähig (generische Basisableitung).
3. **`test/test.py`** (offscreen): alle Tests grün; exakt dieselben 6 vorbestehenden Offscreen-Geometrie-Fehler (P2/P5/H3/H4/H5/H7) – keine Verhaltensänderung (M5 bestätigt).
4. **Keine UI-/Regressionstests** (Regel 4).

## 3. Abweichungen / Hinweise
* Keine Abweichungen von den Review-Entscheidungen M1–M5.
* `docs/Old/x_Roadmap_Phase16.md` wurde **nicht** angefasst (Anwender-Änderung, nicht Teil dieser Umsetzung).
* `docs/x_Exports.md` bleibt unberührt (keine Quelle).

## 4. Commit
- Commit mit Signatur `Generated with [Continue](https://continue.dev)` + `Co-Authored-By: Continue <noreply@continue.dev>`.


# 16.08.01 Nachtrag Bereinigung: Naming Conventions (`srv_` & `ind_`)

## 1. Zielsetzung & Naming-Regeln
Vereinheitlichung aller Dateinamen, Klassen-Identifier, Plugin-IDs und Datenbank-Einträge für Services und Indikatoren nach strikter Naming Convention.

1. **Services (Plugins/Features):**
   * **Präfix:** `srv_`
   * **Regel:** Wörter wie `service`, `plugin` oder `feature` **entfallen** vollständig aus Dateinamen und Identifiern.
   * **Beispiel:** `grid_lines_service.py` -> `srv_grid_lines.py` | `plugin_id = "grid_lines"` -> `plugin_id = "srv_grid_lines"`
2. **Indikatoren:**
   * **Präfix:** `ind_`
   * **Regel:** Wörter wie `indicator` oder `ind` (doppelt) **entfallen** vollständig aus Dateinamen und Identifiern.
   * **Beispiel:** `fixed_grid_proximity.py` -> `ind_fixed_grid_proximity.py` | `indicator_id = "fixed_grid_proximity"` -> `indicator_id = "ind_fixed_grid_proximity"`

---

## 2. Zuordnung der Dateinamen & Identifier (Refactoring Matrix)

### A. Services (`analytics/features/definitions/`)
| Alter Dateiname | Neuer Dateiname | Alte `plugin_id` | Neue `plugin_id` |
| :--- | :--- | :--- | :--- |
| `grid_lines_service.py` | `srv_grid_lines.py` | `grid_lines` | `srv_grid_lines` |
| `proximity_service.py` | `srv_proximity.py` | `proximity` | `srv_proximity` |
| `grid_levels.py` | `srv_grid_levels.py` | `grid_levels` | `srv_grid_levels` |
| `ema_diff.py` | `srv_ema_diff.py` | `ema_diff` | `srv_ema_diff` |
| `atr_normalized.py` | `srv_atr_normalized.py` | `atr_normalized` | `srv_atr_normalized` |

### B. Indikatoren (`chart/indicators/`)
| Alter Dateiname | Neuer Dateiname | Alte `indicator_id` | Neue `indicator_id` |
| :--- | :--- | :--- | :--- |
| `fixed_grid_proximity.py` | `ind_fixed_grid_proximity.py` | `fixed_grid_proximity` / `grid_liquidity` | `ind_fixed_grid_proximity` |
| `multi_ma.py` | `ind_multi_ma.py` | `multi_ma` | `ind_multi_ma` |

---

## 3. Schritt-für-Schritt-Anleitung für die IDE-AI

### Schritt 1: Physikalische Dateien umbenennen
Benenne die Dateien in `analytics/features/definitions/` und `chart/indicators/` gemäß Tabelle in Abschnitt 2 um. Aktualisiere die jeweiligen `__init__.py`-Dateien in den beiden Ordnern mit den neuen Modulimporten.

### Schritt 2: In-Code-Identifier & Metadaten anpassen
1. In allen umbenannten `srv_*.py`-Dateien:
   * Setze `plugin_id = "srv_<name>"` (z. B. `srv_grid_lines`).
   * Falls `dependencies` angegeben sind, passe diese ebenfalls an (z. B. `dependencies = ["srv_grid_lines"]`).
2. In allen umbenannten `ind_*.py`-Dateien:
   * Setze `indicator_id = "ind_<name>"` (z. B. `ind_fixed_grid_proximity`).
   * Passe `service_plugin_ids` an (z. B. `service_plugin_ids = ["srv_grid_lines", "srv_proximity"]`).
3. Passe alle Code-Imports im Projekt an (`FeatureBuilder`, `LiveAnalyzer`, `HistoricalScanner`, `ServiceSelectorModel`, Tests).

### Schritt 3: Datenbank-Migration (`app_data.duckdb` & `analytics.duckdb`)
Füge in `state_manager.py` (`_init_db()`) eine idempotente Schema-Migration ein, um bestehende Presets, Window-States und Feature-Store-Einträge bruchfrei auf die neuen Präfixe umzustellen:


# In StateManager._init_db():
renames_plugins = {
    "grid_lines": "srv_grid_lines",
    "proximity": "srv_proximity",
    "grid_levels": "srv_grid_levels",
    "ema_diff": "srv_ema_diff",
    "atr_normalized": "srv_atr_normalized",
}
renames_indicators = {
    "fixed_grid_proximity": "ind_fixed_grid_proximity",
    "grid_liquidity": "ind_fixed_grid_proximity",
    "multi_ma": "ind_multi_ma",
}

# 1. indicator_presets mappen
for old_id, new_id in renames_indicators.items():
    con.execute("UPDATE indicator_presets SET indicator_id = ? WHERE indicator_id = ?", [new_id, old_id])

for old_id, new_id in renames_plugins.items():
    con.execute("UPDATE indicator_presets SET plugin_id = ? WHERE plugin_id = ?", [new_id, old_id])

# 2. analytics.duckdb -> feature_store.feature_id mappen
con_analytics = DbPool.get(DB_ANALYTICS)
for old_id, new_id in renames_plugins.items():
    con_analytics.execute("UPDATE feature_store SET feature_id = ? WHERE feature_id = ?", [new_id, old_id])



### Schritt 4: Header-Standardisierung

Stelle sicher, dass in allen umbenannten Dateien ganz oben ein einheitlicher Kommentar-Header vorhanden ist:


# ==============================================================================
# DEFINITION: [srv_grid_lines / ind_fixed_grid_proximity]
# ==============================================================================
# NAME:        [z. B. Grid Lines Service]
# KATEGORIE:   [z. B. Swing Points/Preis-Grid]
# BESCHREIBUNG: [Kurze Beschreibung]
#
# PARAMETER:
#   - step_size (float, Def: 0.5): Schrittweite der Grid-Rasterlinien
# ==============================================================================


## 4. Verifikation (Harte Projekt-Regeln)

1. **Statischer Check (Keine UI-Tests):**

python -m py_compile analytics/features/definitions/srv_*.py chart/indicators/ind_*.py state_manager.py




2. **Backend-/DB-Test in `test/test.py`:**
* Teste das Laden von Plugins über `PluginRegistry().get("srv_grid_lines")`.
* Teste das Laden von Indikator-Presets mit den neuen `ind_`-Präfixen.
* **Rule 4:** Keine GUI starten; Verifikation erfolgt per Terminal/py_compile.



