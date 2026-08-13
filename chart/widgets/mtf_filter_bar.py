# chart/widgets/mtf_filter_bar.py
"""
MTF-FC v4 (Kapitel 21.03.07) – MtfFilterBarWidget & Control-Panel.

Filterleiste mit Source-Data-TF, Chart-Overlay-TF, Aggregations-TF,
Range-Picker (Presets 24h/7d/30d/90d/Year, 21.03.15), Tabellen-
Sortierung und Session-Filter (§4 Säule 1). 21.03.14 (Wunsch 2): Die
zusaetzlichen View-Template-Buttons wurden rueckgebaut – die Filter-
Konfiguration laeuft ueber das vorhandene Profil-Management (`sort_mode`
wird ebenfalls persistiert). 21.03.15 (Bug 3/4): 'YTD' wurde in 'Year'
umbenannt (365-Tage-Fenster) + '90d' ergaenzt; der benutzerdefinierte
Von-/Bis-Zeitraum entfaellt, die Session-Checkboxen stehen in Zeile 1
rechts neben der Sortierung (eine Zeile, keine Zeile 2 mehr).

MVVM (Grundsatz 4): KEINE SQL-Queries, KEINE DB-Connects in der UI.
Der Zustand wird ausschliesslich über den `MtfFcProvider` im isolierten
Namespace `shared_state["mtf_fc"]` gelesen/geschrieben. Die Kommunikation
mit Orchestratoren läuft über Signale (keine direkten Fenster-Referenzen,
Grundsatz 2/5).

Das Widget ist bewusst zustandsarm: Es rendert die Steuerungselemente und
emittiert Signale; die eigentliche Verarbeitung (Boundary, Kaskade, Guards)
liegt in den Engine-Modulen (21.03.02-21.03.05).
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from analytics.engine.mtf_fc_provider import MtfFcProvider

#: Data-TF-Auswahl (Multi + fixierte Timeframes). 21.03.11 (Bug 6):
#: Labels kompakt, damit die Leiste in 1200-px-Fenster passt (sizeHint war
#: w=2248 px -> Uberlauf/Clipping, Controls unsichtbar).
DATA_TF_OPTIONS = ["🌐 Multi", "🔒 M1", "🔒 M5", "🔒 M15", "🔒 H1", "🔒 H4"]

#: Chart-Overlay-TF (Auto-Kaskade vs. manuell fix).
CHART_TF_OPTIONS = ["⚡ Auto", "🔒 Fix"]

#: Aggregations-TF (21.03.12, Entscheidung 6a): '⚡ Auto' = Granularitaet
#: dynamisch an den Range anpassen; '🔒 [TF]' = Daten starr auf diesem
#: TF-Raster zusammenfassen. Konfigurierbar via `agg_tf_options`.
AGG_TF_OPTIONS = ["⚡ Auto", "🔒 M1", "🔒 M5", "🔒 M15", "🔒 H1", "🔒 H4", "🔒 D1"]

#: Range-Presets (21.03.15, Bug 3): '90d' ergaenzt; 'YTD' (seit
#: Jahresbeginn) wurde auf 'Year' (letzte 365 Tage) umbenannt.
RANGE_PRESETS = ["24h", "7d", "30d", "90d", "Year"]

#: Tabellen-Sortierung.
SORT_MODES = ["Datum 🠇", "Signal 🠇", "TF 🠅"]

#: Session-Filter (Farbbalken im M1/M5-Zoom, 21.03.08).
SESSION_OPTIONS = ["London", "New York", "Tokio"]

_STRIP_PREFIX = ("🌐 ", "🔒 ", "⚡ ", "🠇", "🠅", " (Multi)", " (Kaskade)", " Manuell Fix")


def _parse_data_tf(text: str) -> str:
    """Konvertiert ein Data-TF-Dropdown-Label in den Wert ('multi' | 'M15')."""
    for prefix in ("🌐 ", "🔒 "):
        if text.startswith(prefix):
            text = text[len(prefix):]
    stripped = text.strip()
    if not stripped or stripped.lower() in ("multi", "alle timeframes",
                                            "alle tf", "alle timeframes (multi)"):
        return "multi"
    return stripped


def _data_tf_label(data_tf: str) -> str:
    """Erzeugt das kompakte Data-TF-Dropdown-Label aus dem Wert."""
    return "🌐 Multi" if str(data_tf).lower() == "multi" else f"🔒 {data_tf}"


def _parse_chart_tf(text: str) -> str:
    """Konvertiert ein Chart-TF-Dropdown-Label in 'auto' oder fixierten TF."""
    if text.startswith("⚡"):
        return "auto"
    return "fix"


class MtfFilterBarWidget(QWidget):
    """Filterleiste des MTF-FC-Systems (QWidget, reines Event-Handling).

    Signale (Entkopplung über den Aufrufer, kein Fenster-Know-how):
      * `data_tf_changed(str)`     – 'multi' oder fixierter TF (z. B. 'M15').
      * `chart_tf_changed(str)`    – 'auto' (Kaskade) oder 'fix'.
      * `agg_tf_changed(str)`      – 'auto' oder konkreter Aggregations-TF
                                     (21.03.12, Entscheidung 6a).
      * `range_changed(str, int, int)` – Preset-Name, from_ts, to_ts.
      * `sort_mode_changed(str)`   – 'date' | 'signal' | 'tf'.
      * `sessions_changed(list)`   – aktive Sessions (z. B. ['london']).
      * `guard_override_requested(str, str)` – target_tf, reason (21.03.05).
    """

    data_tf_changed = Signal(str)
    chart_tf_changed = Signal(str)
    agg_tf_changed = Signal(str)
    range_changed = Signal(str, int, int)
    sort_mode_changed = Signal(str)
    sessions_changed = Signal(list)
    guard_override_requested = Signal(str, str)

    def __init__(
        self,
        provider: Optional[MtfFcProvider] = None,
        parent: Optional[QWidget] = None,
        # 21.03.12 (Analytics-Integration): Die TF-Listen sind konfigurierbar
        # (Analytics hat 11 TFs M1..MN1 statt der 6 Chart-Defaults) und der
        # Range-Referenzpunkt kann injiziert werden (`now_provider` – im
        # Analytics der letzte Datenpunkt MAX(bar_time) statt time.time()).
        data_tf_options: Optional[List[str]] = None,
        agg_tf_options: Optional[List[str]] = None,
        now_provider: Optional[Callable[[], int]] = None,
    ) -> None:
        super().__init__(parent)
        # Provider ist die EINZIGE Brücke zum shared_state-Namespace (MVVM).
        self._provider = provider or MtfFcProvider()
        self._sessions: List[str] = []
        self._data_tf_options = (
            list(data_tf_options) if data_tf_options else list(DATA_TF_OPTIONS))
        self._agg_tf_options = (
            list(agg_tf_options) if agg_tf_options else list(AGG_TF_OPTIONS))
        self._now_provider = now_provider or _now_epoch
        self._build_ui()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # 21.03.11 (Bug 6, 2. Fix): Kompakte EIN-Zeilen-Leiste. Der
        # 1-Zeilen-Umbau (max. Breiten) war noch zu breit: sizeHint=1281,
        # minimumSizeHint=1209 -> das Fenster wird auf ~1220 px aufgezwungen,
        # Range (x 837+) und Sortierung (x 1173+, Ende > Fenster) waren rechts
        # abgeschnitten/unsichtbar. Seit 21.03.15 (Bug 4) liegen Data/Chart/
        # Agg/Range/Sort/Sessions in EINER Zeile (die fruehere Zeile 2 mit
        # dem benutzerdefinierten Von-/Bis-Panel ist entfallen); die Combos
        # sind kompakt, die Session-Checkboxen schmal.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)

        # --- Zeile 1: Data / Chart / Agg / Range / Sort / Sessions ------
        row1 = QHBoxLayout()
        row1.setSpacing(4)

        row1.addWidget(QLabel("Data:"))
        self._data_tf_combo = QComboBox()
        self._data_tf_combo.addItems(self._data_tf_options)
        self._data_tf_combo.setMaximumWidth(105)
        self._data_tf_combo.setToolTip(
            "Source-Data-TF: 🌐 alle Timeframes (Multi) vs. 🔒 fixiert auf einen TF")
        self._data_tf_combo.currentTextChanged.connect(self._on_data_tf_changed)
        row1.addWidget(self._data_tf_combo)

        row1.addSpacing(6)
        row1.addWidget(QLabel("Chart:"))
        self._chart_tf_combo = QComboBox()
        self._chart_tf_combo.addItems(CHART_TF_OPTIONS)
        self._chart_tf_combo.setMaximumWidth(85)
        self._chart_tf_combo.setToolTip(
            "Chart-Overlay-TF: ⚡ Auto (Kaskade) vs. 🔒 manuell fixiert")
        self._chart_tf_combo.currentTextChanged.connect(self._on_chart_tf_changed)
        row1.addWidget(self._chart_tf_combo)

        # 21.03.12 (Entscheidung 6a): Aggregations-TF-Dropdown – nur bei
        # '🔒 Fix' aktiv; bei '⚡ Auto' deaktiviert und auf 'Auto' gesetzt.
        row1.addSpacing(6)
        row1.addWidget(QLabel("Agg:"))
        self._agg_tf_combo = QComboBox()
        self._agg_tf_combo.addItems(self._agg_tf_options)
        self._agg_tf_combo.setMaximumWidth(95)
        self._agg_tf_combo.setToolTip(
            "Aggregations-TF (21.03.12, 6a): ⚡ Auto = Granularitaet dynamisch "
            "an den Zeitraum anpassen; 🔒 Fix = Daten starr auf diesem TF-Raster "
            "zusammenfassen (eigenes Dropdown, unabhaengig von Data-TF).")
        self._agg_tf_combo.currentTextChanged.connect(self._on_agg_tf_changed)
        self._agg_tf_combo.setEnabled(False)
        row1.addWidget(self._agg_tf_combo)

        row1.addSpacing(6)
        row1.addWidget(QLabel("Range:"))
        self._range_combo = QComboBox()
        self._range_combo.addItems(RANGE_PRESETS)
        self._range_combo.setMaximumWidth(100)
        self._range_combo.setToolTip(
            "Zeitfenster-Preset (24h/7d/30d/90d/Year) – filtert den anzuzeigenden Zeitraum")
        self._range_combo.currentTextChanged.connect(self._on_range_changed)
        row1.addWidget(self._range_combo)

        row1.addSpacing(6)
        row1.addWidget(QLabel("Sort:"))
        self._sort_combo = QComboBox()
        self._sort_combo.addItems(SORT_MODES)
        self._sort_combo.setMaximumWidth(95)
        self._sort_combo.setToolTip(
            "Tabellen-Sortierung: Datum, Signal-Stärke oder Timeframe")
        self._sort_combo.currentTextChanged.connect(self._on_sort_changed)
        row1.addWidget(self._sort_combo)

        # 21.03.15 (Bug 4): Session-Filter rechts neben der Sortierung in
        # Zeile 1 (die fruehere Zeile 2 mit dem benutzerdefinierten
        # Von-/Bis-Panel ist entfallen - Platzgewinn, eine Zeile).
        row1.addSpacing(6)
        self._session_checks: Dict[str, QCheckBox] = {}
        for session in SESSION_OPTIONS:
            cb = QCheckBox(session)
            cb.setToolTip("Session-Farbbalken im M1/M5-Zoom (UTC-Epochs)")
            cb.stateChanged.connect(self._on_sessions_changed)
            self._session_checks[session.lower()] = cb
            row1.addWidget(cb)

        row1.addStretch(1)
        outer.addLayout(row1)

    # ------------------------------------------------------------------
    # Public API (State-Sync über Provider, kein SQL)
    # ------------------------------------------------------------------
    def apply_namespace_state(self, context: Any) -> None:
        """Synchronisiert die Widgets aus dem MTF-FC-Namespace des Contexts.

        Wird z. B. nach `applyFullChartUpdate` aufgerufen, damit die
        Filterleiste die aktiven Werte (Data-TF, Chart-TF) anzeigt.
        """
        ns = self._provider.read_namespace(context)
        data_tf = str(ns.get("active_data_tf") or "M15")
        chart_tf = str(ns.get("active_chart_tf") or "M5")

        self._data_tf_combo.blockSignals(True)
        self._data_tf_combo.setCurrentText(_data_tf_label(data_tf))
        self._data_tf_combo.blockSignals(False)

        # 'auto' wird im Chart über die Kaskade bestimmt; bei fixiertem
        # aktiven Chart-TF bleibt die Auswahl auf '⚡ Auto (Kaskade)'.
        self._chart_tf_combo.blockSignals(True)
        self._chart_tf_combo.setCurrentText(CHART_TF_OPTIONS[0])
        self._chart_tf_combo.blockSignals(False)

    def current_data_tf(self) -> str:
        """Aktiver Source-Data-TF ('multi' oder z. B. 'M15')."""
        return _parse_data_tf(self._data_tf_combo.currentText())

    def current_chart_tf(self) -> str:
        """Aktiver Chart-Overlay-TF ('auto' oder 'fix')."""
        return _parse_chart_tf(self._chart_tf_combo.currentText())

    def current_agg_tf(self) -> str:
        """Aktiver Aggregations-TF ('auto' oder konkreter TF, z. B. 'H1')."""
        text = self._agg_tf_combo.currentText()
        for prefix in ("⚡ ", "🔒 "):
            if text.startswith(prefix):
                text = text[len(prefix):]
        stripped = text.strip()
        if not stripped or stripped.lower() in ("auto", "kaskade"):
            return "auto"
        return stripped

    def current_sort_mode(self) -> str:
        """Aktive Sortierung ('date' | 'signal' | 'tf')."""
        text = self._sort_combo.currentText()
        if text.startswith("Signal"):
            return "signal"
        if text.startswith("TF"):
            return "tf"
        return "date"

    # 13.08.2026 (Punkt 3, Teil 2, Bugfix Profile): Oeffentliche Lesemethoden
    # fuer den aktuellen Range-Zustand. Werden vom AnalyticsWindow beim
    # Profil-Speichern genutzt, um den ANGEZEIGTEN Filterleisten-Stand explizit
    # in die VM-Params zu uebernehmen (defensiver Sync vor save_profile()).
    def current_range_preset(self) -> str:
        """Aktiver Range-Preset-Name (z. B. '7d')."""
        return self._range_combo.currentText()

    def current_range_epochs(self) -> Tuple[int, int]:
        """Wanduhr-Epochs (from_ts, to_ts) fuer den aktuellen Preset.

        Gleiche Logik wie `_on_range_changed`: Referenzpunkt ist der
        injizierte `now_provider` (im Analytics der letzte Datenpunkt
        MAX(bar_time)), defensiv time.time(). None/leerer Preset -> 24h.
        """
        preset = self.current_range_preset()
        try:
            now = int(self._now_provider())
        except (TypeError, ValueError):
            now = int(_now_epoch())
        seconds = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400,
                   "90d": 90 * 86400, "Year": 365 * 86400}.get(
                       preset, 86400)
        return now - seconds, now

    # 21.03.12 (Analytics-Integration): Externe Filterwerte anwenden (z. B.
    # Profil-/Workspace-Restore des AnalyticsWindow). Setzt die Combos mit
    # blockSignals und emittiert die Signale danach EXPLIZIT. None = Eintrag
    # unveraendert lassen.
    # 21.03.14 (Wunsch 2): `sort_mode` stellt die Tabellen-Sortierung nach
    # Profil-/Workspace-Restore wieder her (die View-Template-Buttons wurden
    # rueckgebaut). 21.03.15 (Bug 3): Alt-Profile mit 'YTD'/'Benutzerdefiniert'
    # werden auf den neuen Preset-Satz (90d/Year, kein Custom-Panel) gemappt.
    def apply_external_state(
        self,
        data_tf: Optional[str] = None,
        agg_tf: Optional[str] = None,
        range_preset: Optional[str] = None,
        sort_mode: Optional[str] = None,
    ) -> None:
        """Wendet externe Filterwerte auf die Combos an (in-memory)."""
        if data_tf is not None:
            self._data_tf_combo.blockSignals(True)
            self._data_tf_combo.setCurrentText(_data_tf_label(data_tf))
            self._data_tf_combo.blockSignals(False)
            self.data_tf_changed.emit(self.current_data_tf())
        if agg_tf is not None:
            self._agg_tf_combo.blockSignals(True)
            if str(agg_tf).strip().lower() == "auto":
                self._agg_tf_combo.setCurrentText("⚡ Auto")
            else:
                self._agg_tf_combo.setCurrentText(_data_tf_label(agg_tf))
            self._agg_tf_combo.blockSignals(False)
            self.agg_tf_changed.emit(self.current_agg_tf())
        if sort_mode is not None:
            self._sort_combo.blockSignals(True)
            self._sort_combo.setCurrentText(
                {"date": SORT_MODES[0], "signal": SORT_MODES[1],
                 "tf": SORT_MODES[2]}.get(str(sort_mode), SORT_MODES[0]))
            self._sort_combo.blockSignals(False)
            self.sort_mode_changed.emit(self.current_sort_mode())
        if range_preset is not None:
            preset = str(range_preset).strip() or None
            if preset is not None:
                # 21.03.15 (Bug 3): Alt-Profile (YTD/Custom-Panel) auf den
                # neuen Preset-Satz abbilden, damit setCurrentText greift.
                if preset == "YTD":
                    preset = "Year"
                elif preset == "Benutzerdefiniert":
                    preset = "7d"
                self._range_combo.blockSignals(True)
                self._range_combo.setCurrentText(preset)
                self._range_combo.blockSignals(False)
                self._on_range_changed(preset)

    def set_chart_mode(self, mode: str) -> None:
        """Setzt den Chart-Modus ('auto'|'fix') – externer Kontext (Analytics).

        'fix' aktiviert das Aggregations-TF-Dropdown (Entscheidung 6a) und
        stellt einen konkreten Agg-TF sicher; 'auto' deaktiviert es (dynamische
        Granularitaet). Loeuft ueber die bestehende _on_chart_tf_changed-Logik
        (Enable/Disable + Vorbelegung) und emittiert chart_tf_changed +
        agg_tf_changed.
        """
        mode = "fix" if str(mode).strip().lower() == "fix" else "auto"
        self._chart_tf_combo.setCurrentText(
            CHART_TF_OPTIONS[1] if mode == "fix" else CHART_TF_OPTIONS[0])

    def active_sessions(self) -> List[str]:
        """Aktive Session-Filter (klein geschrieben)."""
        return [s for s, cb in self._session_checks.items() if cb.isChecked()]

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    def _on_data_tf_changed(self, _text: str) -> None:
        self.data_tf_changed.emit(self.current_data_tf())

    def _on_chart_tf_changed(self, _text: str) -> None:
        """Aktiviert/deaktiviert das Aggregations-TF-Dropdown (Entscheidung 6a).

        '⚡ Auto'  -> Agg-Combo deaktiviert und auf 'Auto' gesetzt (Granularitaet
                     wird dynamisch aus dem Zeitraum abgeleitet).
        '🔒 Fix'   -> Agg-Combo aktiv; ist noch kein konkreter TF gewaehlt,
                     wird der erste fixierte Eintrag vorbelegt (damit 'Fix'
                     IMMER einen konkreten Aggregations-TF liefert).
        """
        mode = self.current_chart_tf()
        self._agg_tf_combo.blockSignals(True)
        if mode == "auto":
            self._agg_tf_combo.setCurrentText("⚡ Auto")
            self._agg_tf_combo.setEnabled(False)
        else:
            if self.current_agg_tf() == "auto":
                for opt in self._agg_tf_options:
                    if not opt.startswith("⚡"):
                        self._agg_tf_combo.setCurrentText(opt)
                        break
            self._agg_tf_combo.setEnabled(True)
        self._agg_tf_combo.blockSignals(False)
        self.chart_tf_changed.emit(mode)
        self.agg_tf_changed.emit(self.current_agg_tf())

    def _on_agg_tf_changed(self, _text: str) -> None:
        self.agg_tf_changed.emit(self.current_agg_tf())

    def _on_range_changed(self, preset: str) -> None:
        """Range-Combo-Wechsel: Preset-Zeitraum emittieren.

        21.03.12 (Analytics): Referenzpunkt injizierbar – im Analytics der
        letzte Datenpunkt (MAX(bar_time)) statt time.time(), damit Presets
        relativ zum letzten Signal und nicht zur Wanduhr rechnen. Defensiv:
        None/Fehler (z. B. noch kein Symbol/Timeframe gewaehlt) -> time.time().
        21.03.15 (Bug 3): Preset-Satz 24h/7d/30d/90d/Year; 'Year' = letzte
        365 Tage (kein Jahresbeginn-Fenster mehr). Das benutzerdefinierte
        Von-/Bis-Panel ist entfallen. 13.08.2026 (Punkt 3): Die Epoch-
        Berechnung wurde in `current_range_epochs()` extrahiert (wird auch
        vom Profil-Save-Sync des AnalyticsWindow genutzt).
        """
        f, t = self.current_range_epochs()
        self.range_changed.emit(preset, f, t)

    def _on_sort_changed(self, _text: str) -> None:
        self.sort_mode_changed.emit(self.current_sort_mode())

    def _on_sessions_changed(self, _state: int) -> None:
        self._sessions = self.active_sessions()
        self.sessions_changed.emit(list(self._sessions))

    # ------------------------------------------------------------------
    # Guard-Override (Ebene 2, 21.03.05) – Klick auf Reset-Badge
    # ------------------------------------------------------------------
    def request_guard_override(self, target_tf: str, reason: str = "ghost_marker_click") -> None:
        """Leitet einen Geister-Marker-Klick an die State-Machine weiter."""
        self.guard_override_requested.emit(target_tf, reason)


def _now_epoch() -> int:
    """Aktuelle Wanduhr-Epoch (Sekunden)."""
    import time
    return int(time.time())
