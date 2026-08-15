"""
analytics_view_model_setters.py - Setter: Symbol, Timeframes, Sort/Service-Modus, Range, Epoch

23.07 God-File-Split (15.08.2026): Aus analytics/engine/analytics_view_model.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der AnalyticsViewModel-
Klasse als Mixin (Klasse AnalyticsViewModelSetterMixin).
"""

from typing import (
    Optional,
)

from analytics.engine.analytics_worker import (
    QUERY_TABLE,
    QUERY_HEATMAP,
    QUERY_HEATMAP_GENERIC,
    QUERY_OHLCV,
    QUERY_SCATTER,
    QUERY_DISTRIBUTION,
    QUERY_FEATURES,
)

from analytics.engine.analytics_view_model_constants import (
    _ALL_QUERIES,
)

class AnalyticsViewModelSetterMixin:

    # ------------------------------------------------------------------
    # Parameter setzen (UI-Pages) – markieren Dirty + feuern betroffen ab
    # ------------------------------------------------------------------
    def set_symbol(self, symbol: str) -> None:
        self._set_param("symbol", str(symbol or ""),
                        (QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                         QUERY_OHLCV, QUERY_SCATTER, QUERY_DISTRIBUTION,
                         QUERY_FEATURES))

    def set_timeframe(self, timeframe: str) -> None:
        self._set_param("timeframe", str(timeframe or "M1"),
                        (QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                         QUERY_OHLCV, QUERY_SCATTER, QUERY_DISTRIBUTION,
                         QUERY_FEATURES))

    # ------------------------------------------------------------------
    # 21.03.12 (MTF-FC auf Analytics): Filterleisten-Parameter
    # ------------------------------------------------------------------
    def set_data_tf(self, data_tf: str) -> None:
        """Setzt die Analysequelle des MtfFilterBarWidget ('multi' | TF).

        'multi'  -> alle Timeframes in EINER Query (`all_timeframes=True`,
                    der `timeframe`-Filter entfaellt im Reader).
        'M15' o.ae. -> Fixiert auf diesen TF: `all_timeframes=False` und der
                    `timeframe`-Filter uebernimmt den fixierten TF (die UI
                    synchronisiert combo_tf daraus).
        """
        data_tf = str(data_tf or "").strip() or "multi"
        if data_tf == "multi":
            if (self._params.get("data_tf") == "multi"
                    and not self._params.get("all_timeframes")):
                self._params["all_timeframes"] = True
                self._mark_dirty()
                self._refresh(_ALL_QUERIES)
            elif self._params.get("data_tf") != "multi":
                self._params["data_tf"] = "multi"
                self._params["all_timeframes"] = True
                self._mark_dirty()
                self._refresh(_ALL_QUERIES)
            return
        # Fixiert auf einen konkreten TF.
        tf = data_tf.upper()
        changed = (self._params.get("data_tf") != tf
                   or self._params.get("timeframe") != tf
                   or self._params.get("all_timeframes"))
        if not changed:
            return
        self._params["data_tf"] = tf
        self._params["all_timeframes"] = False
        self._params["timeframe"] = tf
        self._mark_dirty()
        self._refresh(_ALL_QUERIES)

    def set_agg_tf(self, agg_tf: str) -> None:
        """Setzt den Aggregations-TF (Entscheidung 6a: 'auto' | TF).

        'auto' -> Granularitaet wird dynamisch aus dem Zeitraum abgeleitet
                  (kein Zeit-Bucketing; Verhalten wie bisher).
        'H1' o.ae. -> Die generische Heatmap fasst die date-Achse starr auf
                  diesem TF-Raster zusammen (bucket_tf im Reader).
        """
        agg_tf = str(agg_tf or "").strip().lower() or "auto"
        self._set_param("agg_tf", agg_tf, (QUERY_HEATMAP_GENERIC,))

    def set_sort_mode(self, mode: str) -> None:
        """21.03.14 (Wunsch 2): Speichert die Tabellen-Sortierung.

        `sort_mode` ist 'date' | 'signal' | 'tf' und wird fuer die
        Profil-Persistenz gemerkt (Sektion sources). Reiner UI-Zustand
        (die TablePage wendet die Sortierung ueber den EventBus an) -
        KEIN Query-Refresh, nur Dirty-Markierung (Option B - Explicit
        Save). Idempotent ohne Aenderung.
        """
        mode = str(mode or "").strip().lower()
        if mode not in ("date", "signal", "tf"):
            mode = "date"
        if mode == self._params.get("sort_mode"):
            return
        self._params["sort_mode"] = mode
        self._mark_dirty()

    def set_service_mode(self, mode: str) -> None:
        """21.03.20: Setzt den Modus-Filter (z. B. 'MA_Peak_Hysteresis').

        `"all"` (Default) = kein Filter (alle Modi). Wirkt GLOBAL auf
        alle Analytics-Datenquellen (Entscheidung 1): Tabelle, beide
        Heatmaps, Scatter, Verteilung. `QUERY_FEATURES` wird mitrefreshed,
        damit die dynamische Modus-Liste / das Deaktivierungs-Flag
        (`has_source_mode_services`) synchron zur Auswahl bleibt. Idempotent
        ohne Aenderung (kein Refresh/Dirty).
        """
        mode = str(mode or "all").strip()
        if mode == self._params.get("service_mode"):
            return
        self._params["service_mode"] = mode
        self._mark_dirty()
        self._refresh((QUERY_FEATURES, QUERY_TABLE, QUERY_HEATMAP,
                       QUERY_HEATMAP_GENERIC, QUERY_SCATTER,
                       QUERY_DISTRIBUTION))

    def set_range(self, from_ts, to_ts, preset: Optional[str] = None) -> None:
        """Setzt den Zeitraum-Filter (optional, bar_time BETWEEN).

        `from_ts`/`to_ts` sind Wanduhr-Epochs (int) oder None (kein Filter).
        `preset` ist der Range-Preset-Name des MtfFilterBarWidget (z. B.
        '7d'/'90d'/'Year', 21.03.15) und wird fuer die Profil-Persistenz
        gemerkt. Alt-Werte 'YTD' (bis 21.03.15) bzw. 'Benutzerdefiniert'
        (entfallenes Custom-Panel) werden auf den neuen Preset-Satz
        abgebildet. Wird vom Range-Picker des MtfFilterBarWidget gesetzt
        (Basis = letzter Datenpunkt statt time.time()).
        """
        f = int(from_ts) if from_ts is not None else None
        t = int(to_ts) if to_ts is not None else None
        preset = str(preset or "").strip() or None
        # 21.03.15 (Bug 3): Alt-Profile mit 'YTD'/'Benutzerdefiniert' auf den
        # neuen Preset-Satz (24h/7d/30d/90d/Year) abbilden.
        if preset == "YTD":
            preset = "Year"
        elif preset == "Benutzerdefiniert":
            preset = "7d"
        if (f == self._params.get("range_from")
                and t == self._params.get("range_to")
                and preset == self._params.get("range_preset")):
            return
        self._params["range_from"] = f
        self._params["range_to"] = t
        self._params["range_preset"] = preset
        self._mark_dirty()
        self._refresh((QUERY_TABLE, QUERY_HEATMAP, QUERY_HEATMAP_GENERIC,
                       QUERY_SCATTER, QUERY_DISTRIBUTION))

    def clear_range(self) -> None:
        """Entfernt den Zeitraum-Filter (kein Zeitfilter mehr)."""
        self.set_range(None, None)

    def latest_data_epoch(self) -> Optional[int]:
        """Neuester Wanduhr-Epoch der Feature-Daten (Range-Referenzpunkt).

        Delegiert lesend an das Repository (`fetch_latest_bar_time` fuer das
        aktuelle Symbol/Timeframe) – der `now_provider` des MtfFilterBarWidget
        rechnet die Presets relativ zum letzten Datenpunkt statt zu
        time.time(). Defensiv: ohne Symbol/Timeframe oder bei Fehler -> None
        (das Widget faellt dann auf time.time() zurueck).
        """
        symbol = str(self._params.get("symbol") or "")
        timeframe = str(self._params.get("timeframe") or "")
        if not symbol or not timeframe:
            return None
        try:
            return self._repo.get_latest_bar_time(symbol, timeframe)
        except Exception:
            return None
