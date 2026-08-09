# analytics/features/definitions/srv_swing_volume_profile.py
# ==============================================================================
# DEFINITION: srv_swing_volume_profile
# ==============================================================================
# NAME:        Swing Volume Profile Service
# KATEGORIE:   Swing Points/Volumen & Grid
# BESCHREIBUNG: Berechnet POC/VAH/VAL, LVN-Rejections, Grid-Proximity und Anchored VWAP
# ==============================================================================
"""
Service: SwingVolumeProfile (Phase 17.01) – Naming Convention 16.08.01: srv_

Berechnet POC/VAH/VAL, Low Volume Nodes (LVNs), Raster-Annäherungen
(Grid_Proximity) und Anchored VWAP Bänder. Reiner Datenlieferant fuer die
Analytics-UI und spaetere ML-Pipelines – KEINE Chart-Visualisierung in
diesem Kapitel (17.01, §1).

Causal Timestamping (Kein Look-ahead Bias, 17.01 §2.4):
  * event_bar_time:        Zeitpunkt des tatsaechlichen Extremums (z. B.
                           Session_Start beim Anchored VWAP).
  * confirmation_bar_time: Zeitpunkt, an dem das Signal kausal feststand.
  * confirmation_lag_bars: dynamische Differenz in Bars (Modus-Verzoegerung).
  * Profile am Serienanfang ohne ausreichenden Lookback erhalten
    calculation_status = 'INSUFFICIENT_DATA'.

Persistenz: feature_store_payload mit feature_id='srv_swing_volume_profile'
(Datenvertrag 17.01 §4, modus-spezifische Zusatzfelder §4.2). Seit 17.01
(E-1, PK-Migration) koennen mehrere Services konfliktfrei auf derselben
Kerze gespeichert werden.

Capabilities (E-5, 07.08.2026): chart=False, batch=True, live=False,
feature_store=True, render=False.
metadata['category'] = 'Swing Points/Volumen & Grid' fuer den MasterTree.

PARAMETER (PineScript-Input-Zone, 17.01 §2.2): Alle Inputs/Defaults stehen
als Modul-Konstante `_SWING_VOLUME_PROFILE_SCHEMA` direkt unter diesem Header.
`parameter_schema` gibt eine flache Kopie zurueck (M1).
E-2 (07.08.2026): type-Werte als Strings.

Hinweis (17.01.02): 'Sessions' wird ohne Session-Kalender als Kalendertag
(24h-Periode) behandelt – Dokumentation der Vereinfachung fuer den
Batch-Datenlieferanten.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from analytics.features.plugins.base_plugin import (
    FeatureCalculateResult,
    ParameterSchema,
    PluginCapabilities,
    PluginContext,
    PluginFeature,
)

# ---------------------------------------------------------------------------
# PARAMETER (PineScript-Input-Zone, 17.01): Single Source of Truth fuer das
# Prop-Fenster. Inputs/Defaults stehen hier direkt am Dateianfang.
# `parameter_schema` gibt eine flache Kopie zurueck (M1).
# E-2 (07.08.2026): type-Werte als Strings.
# ---------------------------------------------------------------------------
_SWING_VOLUME_PROFILE_SCHEMA: Dict[str, ParameterSchema] = {
    "mode": {
        "type": "str",
        "default": "Volume_Profile",
        "options": ["Volume_Profile", "Grid_Proximity", "Anchored_VWAP"],
        "description": "Haupt-Berechnungsmodus",
    },
    "profile_period": {
        "type": "str",
        "default": "Sessions",
        "options": ["Bars", "Sessions", "Days", "Weeks", "Months"],
        "description": "Profil-Zeitraum (nur aktiv bei mode == 'Volume_Profile')",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "period_val": {
        "type": "int", "default": 1, "min": 1,
        "description": "Multiplier für profile_period",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "volume_source": {
        "type": "str",
        "default": "tick_volume",
        "options": ["tick_volume", "real_volume"],
        "description": "Volumenquelle aus MT5 (standardmäßig tick_volume)",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "volume_thresh_pct": {
        "type": "float", "default": 5.0, "min": 0.5,
        "description": "Mindestvolumenanteil in % für Cluster",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "value_area_pct": {
        "type": "float", "default": 0.70, "min": 0.1, "max": 1.0,
        "description": "Value Area Abdeckung (0.70 = 70%)",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "lvn_sensitivity": {
        "type": "float", "default": 0.20, "min": 0.05,
        "description": "Schwellwert für Low Volume Nodes",
        "visible_when": {"mode": "Volume_Profile"},
    },
    "grid_step": {
        "type": "float", "default": 0.5, "min": 0.01,
        "description": "Rasterabstand (nur bei mode == 'Grid_Proximity')",
        "visible_when": {"mode": "Grid_Proximity"},
    },
    "vwap_anchor": {
        "type": "str",
        "default": "Session_Start",
        "options": ["Session_Start", "Week_Start", "Month_Start"],
        "description": "Ankerpunkt (nur bei mode == 'Anchored_VWAP')",
        "visible_when": {"mode": "Anchored_VWAP"},
    },
    "vwap_band_mult": {
        "type": "float", "default": 2.0, "min": 0.1,
        "description": "StDev-Multiplikator für VWAP-Bänder",
        "visible_when": {"mode": "Anchored_VWAP"},
    },
}

# ---------------------------------------------------------------------------
# OUTPUT-SCHEMA (20.03): Resultatfelder je feature_data-Record (Datenvertrag
# 17.01 §4, modus-spezifische Zusatzfelder §4.2). `bar_time` ist eine native
# DB-Spalte und wird NICHT deklariert (E4). `type` sind freie Strings (E5).
# `technical: True` -> kompakte Anzeige im Unterblock `🔧 System-Metrik` (E2).
# ---------------------------------------------------------------------------
_SWING_VOLUME_PROFILE_OUTPUT_SCHEMA: Dict[str, Dict[str, Any]] = {
    "result_type": {
        "type": "str",
        "description": "Klassifikation des Records ('LEVEL' | 'VWAP')",
        "technical": True,
    },
    "source_mode": {
        "type": "str",
        "description": "Aktiver Modus (Volume_Profile/Grid_Proximity/Anchored_VWAP)",
        "technical": True,
    },
    "calculation_status": {
        "type": "str",
        "description": "Berechnungsstatus ('OK' | 'INSUFFICIENT_DATA')",
        "technical": True,
    },
    "is_swing_high": {
        "type": "bool",
        "description": "True, wenn der Close über VAH bzw. über Upper-Band liegt",
    },
    "is_swing_low": {
        "type": "bool",
        "description": "True, wenn der Close unter VAL bzw. unter Lower-Band liegt",
    },
    "is_rejection": {
        "type": "bool",
        "description": "True bei LVN-Rejection (Close nahe LVN) – nur Volume_Profile",
    },
    "event_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch des Events (Session_Start beim VWAP, sonst Bar selbst)",
        "technical": True,
    },
    "confirmation_bar_time": {
        "type": "int",
        "description": "Wanduhr-Epoch, an der das Signal kausal feststand",
        "technical": True,
    },
    "confirmation_lag_bars": {
        "type": "int",
        "description": "Bestätigungs-Verzögerung in Bars (VWAP: Bars seit Anker)",
        "technical": True,
    },
    "confirmation_type": {
        "type": "str",
        "description": "Bestätigungsart (immer 'CAUSAL')",
        "technical": True,
    },
    "price": {
        "type": "float",
        "description": "Close-Preis der Bar",
    },
    "strength_value": {
        "type": "float",
        "description": "Signalstärke (VOLUME_RATIO: Volumen/POC-Volumen; NORMALIZED: |Distanz|/grid_step; PRICE_DISTANCE: |Close-VWAP|/StDev)",
    },
    "strength_type": {
        "type": "str",
        "description": "Stärke-Maßstab ('VOLUME_RATIO' | 'NORMALIZED' | 'PRICE_DISTANCE')",
        "technical": True,
    },
    "volume_source": {
        "type": "str",
        "description": "Volumenquelle (tick_volume/real_volume) – nur Volume_Profile",
        "technical": True,
    },
    "poc_price": {
        "type": "float",
        "description": "Point of Control (volumenstärkste Preisstufe) – nur Volume_Profile, nullbar",
    },
    "vah_price": {
        "type": "float",
        "description": "Value Area High (obere Wertbereichsgrenze) – nur Volume_Profile, nullbar",
    },
    "val_price": {
        "type": "float",
        "description": "Value Area Low (untere Wertbereichsgrenze) – nur Volume_Profile, nullbar",
    },
    "lvn_price": {
        "type": "float",
        "description": "Nächstgelegener Low Volume Node zum Close – nur Volume_Profile, nullbar",
    },
    "is_lvn_swing": {
        "type": "bool",
        "description": "True bei LVN-Rejection – nur Volume_Profile",
    },
    "grid_price": {
        "type": "float",
        "description": "Nächstes Raster-Level (round(close/grid_step) × grid_step) – nur Grid_Proximity",
    },
    "vwap_price": {
        "type": "float",
        "description": "Anchored VWAP (kumulativ ab Perioden-Start) – nur Anchored_VWAP",
    },
    "vwap_upper": {
        "type": "float",
        "description": "Oberes VWAP-Band (VWAP + band_mult × StDev) – nur Anchored_VWAP",
    },
    "vwap_lower": {
        "type": "float",
        "description": "Unteres VWAP-Band (VWAP - band_mult × StDev) – nur Anchored_VWAP",
    },
}

# ---------------------------------------------------------------------------
# Modul-Helfer (17.01.02: echte Erkennung statt Scaffold)
# ---------------------------------------------------------------------------

def _volume_series(work: pd.DataFrame, source: str) -> np.ndarray:
    """Volumen-Serie (tick_volume/real_volume); fehlt die Spalte, Fallback
    auf gleichbleibendes Volumen 1.0 (defensiv, kein Crash)."""
    col = "real_volume" if source == "real_volume" else "tick_volume"
    if col in work.columns:
        v = pd.to_numeric(work[col], errors="coerce").fillna(0.0).to_numpy()
    else:
        v = np.ones(len(work), dtype=float)
    return v


def _profile_for(hi: np.ndarray, lo: np.ndarray, close: np.ndarray,
                 vol: np.ndarray, value_area_pct: float,
                 lvn_sensitivity: float, n_bins: int = 80,
                 ) -> Optional[Tuple[float, float, float, List[float],
                                     float, float]]:
    """Baut ein Volume-Profil ueber die uebergebenen Bars (entwickelnd).

    Rueckgabe: (poc_price, vah_price, val_price, lvn_prices, total_vol,
    max_bin_vol) oder None, wenn kein sinnvolles Profil konstruierbar ist
    (weniger als 2 Bars, flache Range oder Null-Gesamtvolumen)."""
    n = len(hi)
    if n < 2:
        return None
    hi_min = float(np.nanmin(hi))
    lo_max = float(np.nanmax(lo))
    lo_min = float(np.nanmin(lo))
    hi_max = float(np.nanmax(hi))
    total = float(np.sum(vol))
    if not np.isfinite(total) or total <= 0.0:
        return None
    lower = lo_min
    upper = hi_max
    if not (np.isfinite(lower) and np.isfinite(upper)) or upper <= lower:
        return None
    edges = np.linspace(lower, upper, n_bins + 1)
    typ = (hi + lo + close) / 3.0
    idx = np.clip(np.floor((typ - lower) / (upper - lower) * n_bins),
                  0, n_bins - 1).astype(int)
    bins_vol = np.zeros(n_bins, dtype=float)
    np.add.at(bins_vol, idx, vol)
    poc_bin = int(np.argmax(bins_vol))
    poc = float((edges[poc_bin] + edges[poc_bin + 1]) / 2.0)
    max_vol = float(bins_vol[poc_bin])
    # Value Area: ab POC beidseitig expandieren bis value_area_pct erreicht.
    cum = bins_vol[poc_bin]
    lo_b = hi_b = poc_bin
    target = total * float(value_area_pct)
    while cum < target and (lo_b > 0 or hi_b < n_bins - 1):
        left_v = bins_vol[lo_b - 1] if lo_b > 0 else -1.0
        right_v = bins_vol[hi_b + 1] if hi_b < n_bins - 1 else -1.0
        if lo_b > 0 and left_v >= right_v:
            lo_b -= 1
            cum += left_v
        elif hi_b < n_bins - 1:
            hi_b += 1
            cum += right_v
        else:
            break
    vah = float(edges[hi_b + 1])
    val = float(edges[lo_b])
    # LVN: Bins mit Volumen < lvn_sensitivity × POC-Volumen (aber > 0).
    lvn_mask = (bins_vol > 0.0) & (bins_vol < lvn_sensitivity * max_vol)
    lvn_prices = [float((edges[b] + edges[b + 1]) / 2.0)
                  for b in np.where(lvn_mask)[0]]
    return poc, vah, val, lvn_prices, total, max_vol


def _group_ids(times: np.ndarray, spec: str, period_val: int,
               ) -> np.ndarray:
    """Gruppen-IDs je Bar fuer die Profilperioden.

    * Bars:     i // period_val
    * Sessions: Kalendertag (Vereinfachung ohne Session-Kalender, 24h).
    * Days:     Kalendertag.
    * Weeks:    ISO-Jahr-Woche.
    * Months:   Kalender-Jahr-Monat.
    """
    n = len(times)
    if spec == "Bars":
        return np.floor(np.arange(n) / max(1, int(period_val))).astype(np.int64)
    # pd.to_datetime(...) liefert einen DatetimeIndex (kein Series) -> .dt
    # existiert dort nicht; die Formatierung erfolgt direkt via .strftime
    # (17.01.02 Bugfix, identisch zu srv_swing_structure).
    dates = pd.to_datetime(times, unit="s", utc=True)
    if spec in ("Sessions", "Days"):
        return dates.strftime("%Y-%m-%d").to_numpy()
    if spec == "Weeks":
        return dates.strftime("%G-W%V").to_numpy()
    if spec == "Months":
        return dates.strftime("%Y-%m").to_numpy()
    return dates.strftime("%Y-%m-%d").to_numpy()


def _anchored_vwap(work: pd.DataFrame, times: np.ndarray, vol: np.ndarray,
                   anchor: str, band_mult: float,
                   ) -> Tuple[np.ndarray, np.ndarray, np.ndarray,
                              np.ndarray, np.ndarray]:
    """Anchored VWAP (entwickelnd ab Perioden-Start).

    Rueckgabe: (vwap, upper, lower, anchor_idx, stdev). anchor_idx[i] =
    Index der Anker-Bar (Session/Week/Month-Start), 0 fuer die erste Bar.
    """
    n = len(work)
    hi = work["high"].to_numpy(dtype=float)
    lo = work["low"].to_numpy(dtype=float)
    close = work["close"].to_numpy(dtype=float)
    typ = (hi + lo + close) / 3.0
    if anchor == "Week_Start":
        spec = "Weeks"
    elif anchor == "Month_Start":
        spec = "Months"
    else:
        spec = "Sessions"
    groups = _group_ids(times, spec, 1)
    # Neue Periode erkennen (causal: letzte Gruppe bis i).
    new_period = np.zeros(n, dtype=bool)
    new_period[0] = True
    for i in range(1, n):
        if groups[i] != groups[i - 1]:
            new_period[i] = True
    anchor_idx = np.zeros(n, dtype=np.int64)
    cur = 0
    for i in range(n):
        if new_period[i]:
            cur = i
        anchor_idx[i] = cur
    # Kumulativ ab Anker: Summe(typ*vol) / Summe(vol).
    cum_pv = np.zeros(n, dtype=float)
    cum_v = np.zeros(n, dtype=float)
    pv = 0.0
    cv = 0.0
    for i in range(n):
        if new_period[i]:
            pv = 0.0
            cv = 0.0
        pv += typ[i] * vol[i]
        cv += vol[i]
        cum_pv[i] = pv
        cum_v[i] = cv
    vwap = np.where(cum_v > 0.0, cum_pv / np.maximum(cum_v, 1e-12), 0.0)
    # Entwickelnde Varianz (gewichtete Quadrat-Abweichung ab Anker).
    dev2 = ((typ - vwap) ** 2) * vol
    cum_d2 = np.zeros(n, dtype=float)
    cd2 = 0.0
    for i in range(n):
        if new_period[i]:
            cd2 = 0.0
        cd2 += dev2[i]
        cum_d2[i] = cd2
    var = np.where(cum_v > 0.0, cum_d2 / np.maximum(cum_v, 1e-12), 0.0)
    stdev = np.sqrt(np.maximum(var, 0.0))
    upper = vwap + band_mult * stdev
    lower = vwap - band_mult * stdev
    return vwap, upper, lower, anchor_idx, stdev


class SrvSwingVolumeProfile(PluginFeature):
    """Volumen-, Grid- & VWAP-Swings.

    Stateless (Basisklassen-Vertrag): Berechnung ist eine reine Funktion
    calculate(df, params, context) – keine eigenen Zustaende.
    """

    @property
    def plugin_id(self) -> str:
        return "srv_swing_volume_profile"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "category": "Swing Points/Volumen & Grid",
            "display_name": "Swing Volume Profile Service",
            "description": "Volumengewichtetes Profil mit POC/VAH/VAL, LVNs, Grid & Anchored VWAP",
            "author": "PyTrader AI",
            "tags": ["swing", "volume", "profile", "lvn", "vwap", "grid"],
            # Phase 14 P14-01: Erweiterte Beschreibungsfelder
            "description_long": "Reiner Datenlieferant (feature_store=True) für "
                                "die Analytics-UI und ML-Pipelines. Berechnet "
                                "POC/VAH/VAL und Low Volume Nodes (LVNs) je "
                                "Profil, Raster-Annäherungen (Grid_Proximity) "
                                "und Anchored-VWAP-Bänder. Keine "
                                "Chart-Visualisierung in Kapitel 17.01.",
            "condition_rules": [
                "Volume_Profile: POC/VAH/VAL über value_area_pct, Cluster ab volume_thresh_pct, LVNs ab lvn_sensitivity",
                "Grid_Proximity: Abstand des Preises zum naechsten Rasterlevel (grid_step)",
                "Anchored_VWAP: VWAP ab Session/Week/Month_Start ± vwap_band_mult × StDev",
                "volume_source: tick_volume (Standard) oder real_volume",
                "Causal Timestamps: event/confirmation_bar_time, confirmation_lag_bars, INSUFFICIENT_DATA/MISSING_MTF_CONTEXT",
            ],
            "api_version": "1",
        }

    @property
    def capabilities(self) -> PluginCapabilities:
        return {
            "chart": False,   # E-5: kein Indikator in Kapitel 17.01
            "batch": True,
            "live": False,
            "feature_store": True,
            "render": False,  # E-5: reine Datenlieferanten
        }

    # --- Single Source of Truth fürs Prop-Fenster (17.01 §2.2, PineScript-Zone)
    @property
    def parameter_order(self) -> List[str]:
        return list(_SWING_VOLUME_PROFILE_SCHEMA.keys())

    @property
    def param_labels(self) -> Dict[str, str]:
        return {
            "mode": "Haupt-Berechnungsmodus",
            "profile_period": "Profil-Zeitraum (Volume_Profile)",
            "period_val": "Multiplier (Profil-Zeitraum)",
            "volume_source": "Volumenquelle",
            "volume_thresh_pct": "Mindestvolumenanteil % (Cluster)",
            "value_area_pct": "Value Area Abdeckung",
            "lvn_sensitivity": "LVN-Schwellwert",
            "grid_step": "Rasterabstand (Grid_Proximity)",
            "vwap_anchor": "VWAP-Ankerpunkt",
            "vwap_band_mult": "VWAP-Band-Multiplikator",
        }

    @property
    def parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Flache Kopie der Modul-Konstante `_SWING_VOLUME_PROFILE_SCHEMA`
        (PineScript-Input-Zone am Dateianfang, M1: kein geteiltes Dict)."""
        return {k: dict(v) for k, v in _SWING_VOLUME_PROFILE_SCHEMA.items()}

    @property
    def output_schema(self) -> Dict[str, Dict[str, Any]]:
        """Output-Schema (20.03): flache Kopie der Modul-Konstante
        `_SWING_VOLUME_PROFILE_OUTPUT_SCHEMA` (PineScript-Input-Zone, M1:
        kein geteiltes mutable Dict)."""
        return {k: dict(v) for k, v in _SWING_VOLUME_PROFILE_OUTPUT_SCHEMA.items()}

    # 2. SCHEMA-EXPOSURE FÜR DIE UI (07.08.2026, Bugfix): Die Spalten-UI
    # (serviceui/param_columns.py & ServiceSelectorWidget) liest Parameter-
    # Definitionen über `default_params` / `full_parameter_schema()`. Diese
    # expliziten Overrides stellen das Schema unabhängig von der jeweiligen
    # parameter_schema-Definition (Property/Klassen-Attribut) bereit und
    # erhalten den Basisklassen-Vertrag (Basis-Parameter wie lookback + 
    # plugin-spezifische Parameter, vgl. base_plugin.PluginFeature).
    @property
    def default_params(self) -> Dict[str, Any]:
        """Extrahiert die Default-Werte aus dem parameter_schema für die Engine."""
        return {k: v.get("default") for k, v in self.parameter_schema.items()
                if "default" in v}

    def full_parameter_schema(self) -> Dict[str, ParameterSchema]:
        """Liefert das vollständige Schema (Basis + plugin-spezifisch) inkl.
        Min/Max/Typ für die UI-Spalten (Basisklassen-Vertrag)."""
        merged = dict(self.base_parameter_schema)
        merged.update(dict(self.parameter_schema or {}))
        return merged

    def calculate(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        context: Optional[PluginContext] = None,
    ) -> FeatureCalculateResult:
        """Berechnet Volume-Profile/Grid/VWAP-Swings.

        17.01.02 (Bugfix-Runde): Echte Erkennung ersetzt den Scaffold
        (vorher records=[], daher '0 Feature-Row(s)' im Store + irrefuehrende
        Meldung 'Keine OHLCV-Daten' im ServiceRunWorker).

        Datenvertrag (17.01 §4): JEDER Bar entspricht genau EIN Record.
        Modus-spezifische Zusatzfelder (§4.2):
          * Volume_Profile:  volume_source, poc_price, vah_price, val_price,
                             lvn_price, is_lvn_swing (result_type LEVEL).
          * Grid_Proximity:  grid_price (result_type LEVEL).
          * Anchored_VWAP:   vwap_price, vwap_upper, vwap_lower
                             (result_type VWAP).
        """
        empty: FeatureCalculateResult = {"feature_store_payload": {}}
        if df is None or df.empty:
            return empty

        # Defensive Normalisierung: 'time'-Spalte (epoch) sicherstellen.
        work = df.copy()
        if "time" not in work.columns:
            if "bar_time" in work.columns:
                work["time"] = work["bar_time"].apply(
                    lambda v: int(v.timestamp())
                    if hasattr(v, "timestamp") else int(v))
            else:
                return empty

        p = self.validate_params(params)
        mode = str(p.get("mode") or "Volume_Profile")
        profile_period = str(p.get("profile_period") or "Sessions")
        period_val = int(p.get("period_val") or 1)
        volume_source = str(p.get("volume_source") or "tick_volume")
        value_area_pct = float(p.get("value_area_pct") or 0.70)
        lvn_sensitivity = float(p.get("lvn_sensitivity") or 0.20)
        grid_step = float(p.get("grid_step") or 0.5)
        vwap_anchor = str(p.get("vwap_anchor") or "Session_Start")
        vwap_band_mult = float(p.get("vwap_band_mult") or 2.0)

        n = len(work)
        times = work["time"].to_numpy(dtype=np.int64)
        close = work["close"].to_numpy(dtype=float)
        hi = work["high"].to_numpy(dtype=float)
        lo = work["low"].to_numpy(dtype=float)
        vol = _volume_series(work, volume_source)

        records: List[Dict[Any, Any]] = []
        total_high = 0
        total_low = 0

        if mode == "Volume_Profile":
            groups = _group_ids(times, profile_period, period_val)
            # Serienanfang: erste Bar jeder Gruppe ohne Historie.
            is_first = np.zeros(n, dtype=bool)
            is_first[0] = True
            for i in range(1, n):
                if groups[i] != groups[i - 1]:
                    is_first[i] = True
            group_start = 0
            for i in range(n):
                if is_first[i]:
                    group_start = i
                prof = _profile_for(hi[group_start:i + 1], lo[group_start:i + 1],
                                    close[group_start:i + 1], vol[group_start:i + 1],
                                    value_area_pct, lvn_sensitivity)
                if prof is None or is_first[i]:
                    records.append({
                        "bar_time": int(times[i]),
                        "result_type": "LEVEL",
                        "source_mode": mode,
                        "calculation_status": "INSUFFICIENT_DATA",
                        "is_swing_high": False,
                        "is_swing_low": False,
                        "is_rejection": False,
                        "event_bar_time": int(times[i]),
                        "confirmation_bar_time": int(times[i]),
                        "confirmation_lag_bars": 0,
                        "confirmation_type": "CAUSAL",
                        "price": float(close[i]),
                        "strength_value": 0.0,
                        "strength_type": "VOLUME_RATIO",
                        "volume_source": volume_source,
                        "poc_price": None,
                        "vah_price": None,
                        "val_price": None,
                        "lvn_price": None,
                        "is_lvn_swing": False,
                    })
                    continue
                poc, vah, val, lvn_prices, total, max_vol = prof
                # Naechster LVN am aktuellen Preis (kausal).
                lvn_price: Optional[float] = None
                if lvn_prices:
                    lvn_price = min(lvn_prices,
                                    key=lambda x: abs(x - float(close[i])))
                is_lvn_swing = lvn_price is not None and abs(
                    float(close[i]) - lvn_price) <= (vah - val) / 20.0
                is_sh = float(close[i]) >= vah
                is_sl = float(close[i]) <= val
                total_high += int(is_sh)
                total_low += int(is_sl)
                records.append({
                    "bar_time": int(times[i]),
                    "result_type": "LEVEL",
                    "source_mode": mode,
                    "calculation_status": "OK",
                    "is_swing_high": bool(is_sh),
                    "is_swing_low": bool(is_sl),
                    "is_rejection": bool(is_lvn_swing),
                    "event_bar_time": int(times[i]),
                    "confirmation_bar_time": int(times[i]),
                    "confirmation_lag_bars": 0,
                    "confirmation_type": "CAUSAL",
                    "price": float(close[i]),
                    "strength_value": float(vol[i] / max_vol) if max_vol > 0 else 0.0,
                    "strength_type": "VOLUME_RATIO",
                    "volume_source": volume_source,
                    "poc_price": poc,
                    "vah_price": vah,
                    "val_price": val,
                    "lvn_price": lvn_price,
                    "is_lvn_swing": bool(is_lvn_swing),
                })

        elif mode == "Grid_Proximity":
            grid_price = np.round(close / grid_step) * grid_step
            for i in range(n):
                gp = float(grid_price[i])
                dist = float(close[i]) - gp
                is_sh = i > 0 and float(close[i]) >= gp and float(close[i - 1]) < gp
                is_sl = i > 0 and float(close[i]) <= gp and float(close[i - 1]) > gp
                total_high += int(is_sh)
                total_low += int(is_sl)
                records.append({
                    "bar_time": int(times[i]),
                    "result_type": "LEVEL",
                    "source_mode": mode,
                    "calculation_status": "OK",
                    "is_swing_high": bool(is_sh),
                    "is_swing_low": bool(is_sl),
                    "is_rejection": False,
                    "event_bar_time": int(times[i]),
                    "confirmation_bar_time": int(times[i]),
                    "confirmation_lag_bars": 0,
                    "confirmation_type": "CAUSAL",
                    "price": float(close[i]),
                    "strength_value": abs(dist) / grid_step if grid_step > 0 else 0.0,
                    "strength_type": "NORMALIZED",
                    "grid_price": gp,
                })

        elif mode == "Anchored_VWAP":
            vwap, upper, lower, anchor_idx, stdev = _anchored_vwap(
                work, times, vol, vwap_anchor, vwap_band_mult)
            for i in range(n):
                vw = float(vwap[i])
                up = float(upper[i])
                lw = float(lower[i])
                is_sh = float(close[i]) > up
                is_sl = float(close[i]) < lw
                total_high += int(is_sh)
                total_low += int(is_sl)
                status = "INSUFFICIENT_DATA" if i == int(anchor_idx[i]) else "OK"
                records.append({
                    "bar_time": int(times[i]),
                    "result_type": "VWAP",
                    "source_mode": mode,
                    "calculation_status": status,
                    "is_swing_high": bool(is_sh),
                    "is_swing_low": bool(is_sl),
                    "is_rejection": False,
                    "event_bar_time": int(times[int(anchor_idx[i])]),
                    "confirmation_bar_time": int(times[i]),
                    "confirmation_lag_bars": int(i - int(anchor_idx[i])),
                    "confirmation_type": "CAUSAL",
                    "price": float(close[i]),
                    "strength_value": (float(close[i]) - vw) / stdev[i]
                    if np.isfinite(stdev[i]) and stdev[i] > 0 else 0.0,
                    "strength_type": "PRICE_DISTANCE",
                    "vwap_price": vw,
                    "vwap_upper": up,
                    "vwap_lower": lw,
                })

        else:
            # Unbekannter Modus: defensiv leer (kein Crash, 0 Rows).
            return empty

        return {
            "feature_store_payload": {
                "feature_id": self.plugin_id,
                "plugin_version": self.version,
                "records": records,
                "metadata": {
                    # E-7 / base_plugin (U15-A1, Invariante 5): schema_version
                    # ist Pflichtfeld fuer alle feature_store=True-Plugins.
                    "schema_version": "1.0.0",
                    "source_mode": mode,
                    "total_swing_highs": total_high,
                    "total_swing_lows": total_low,
                    "bars": n,
                },
            },
        }
