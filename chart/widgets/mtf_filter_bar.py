# chart/widgets/mtf_filter_bar.py
"""
MTF-FC v4 (Kapitel 21.03.07) – MtfFilterBarWidget & Control-Panel.

Filterleiste mit Source-Data-TF, Chart-Overlay-TF, Aggregations-TF,
Range-Picker (Presets + benutzerdefinierter Zeitraum mit Von-/Bis-
Date/Time-Pickern, 21.03.14), Tabellen-Sortierung und Session-Filter
(§4 Säule 1). 21.03.14 (Wunsch 2): Die zusaetzlichen View-Template-
Buttons wurden rueckgebaut – die Filter-Konfiguration laeuft ueber das
vorhandene Profil-Management (`sort_mode` wird ebenfalls persistiert).

MVVM (Grundsatz 4): KEINE SQL-Queries, KEINE DB-Connects in der UI.
Der Zustand wird ausschliesslich über den `MtfFcProvider` im isolierten
Namespace `shared_state["mtf_fc"]` gelesen/geschrieben. Die Kommunikation
mit Orchestratoren läuft über Signale (keine direkten Fenster-Referenzen,
Grundsatz 2/5).

Das Widget ist bewusst zustandsarm: Es rendert die Steuerungselemente und
emittiert Signale; die eigentliche Verarbeitung (Boundary, Kaskade, Guards)
liegt in den Engine-Modulen (21.03.02-21.03.05).
"""

from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
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

#: Range-Presets.
RANGE_PRESETS = ["24h", "7d", "30d", "YTD", "Benutzerdefiniert"]

#: Tabellen-Sortierung.
SORT_MODES = ["Datum 🠇", "Signal 🠇", "TF 🠅"]

#: Session-Filter (Farbbalken im M1/M5-Zoom, 21.03.08).
SESSION_OPTIONS = ["London", "New York", "Tokio"]

_STRIP_PREFIX = ("🌐 ", "🔒 ", "⚡ ", "🠇", "🠅", " (Multi)", " (Kaskade)", " Manuell Fix", "Benutzerdefiniert")


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
        # 21.03.14 (Wunsch 1): Zuletzt emittierter Range (Preset oder
        # benutzerdefiniert) fuer die Vorbelegung der Von-/Bis-Picker sowie
        # der zuletzt benutzte benutzerdefinierte Zeitraum (ueberlebt das
        # Umschalten zwischen Preset und "Benutzerdefiniert").
        self._last_range: Optional[tuple] = None
        self._custom_from: Optional[int] = None
        self._custom_to: Optional[int] = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # 21.03.11 (Bug 6, 2. Fix): ZWEI-ZEILEN-Layout statt einer Zeile.
        # Der 1-Zeilen-Umbau (max. Breiten) war noch zu breit: sizeHint=1281,
        # minimumSizeHint=1209 -> das Fenster wird auf ~1220 px aufgezwungen,
        # Range (x 837+) und Sortierung (x 1173+, Ende > Fenster) waren rechts
        # abgeschnitten/unsichtbar. Zeile 1 = Kern-Steuerung (Data/Chart/
        # Range/Sort), Zeile 2 = Sessions + Templates -> sizeHint < 700 px.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)

        # --- Zeile 1: Source-Data-TF / Chart-Overlay-TF / Range / Sort --
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
            "Zeitfenster-Preset (24h/7d/30d/YTD) – filtert den anzuzeigenden Zeitraum")
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

        row1.addStretch(1)
        outer.addLayout(row1)

        # --- Zeile 2: Session-Filter + benutzerdefinierter Range ---------
        # 21.03.14 (Wunsch 1): Die View-Template-Steuerelemente wurden
        # rueckgebaut (Wunsch 2, Profil-Management traegt die Filter-Config);
        # stattdessen liegt hier der benutzerdefinierte Von-/Bis-Zeitraum
        # (nur sichtbar, wenn der Range-Combo auf "Benutzerdefiniert" steht).
        row2 = QHBoxLayout()
        row2.setSpacing(4)

        self._session_checks: Dict[str, QCheckBox] = {}
        for session in SESSION_OPTIONS:
            cb = QCheckBox(session)
            cb.setToolTip("Session-Farbbalken im M1/M5-Zoom (UTC-Epochs)")
            cb.stateChanged.connect(self._on_sessions_changed)
            self._session_checks[session.lower()] = cb
            row2.addWidget(cb)

        row2.addSpacing(6)
        self._custom_panel = QWidget()
        custom_lay = QHBoxLayout(self._custom_panel)
        custom_lay.setContentsMargins(0, 0, 0, 0)
        custom_lay.setSpacing(2)
        custom_lay.addWidget(QLabel("Von:"))
        self._dt_from = QDateTimeEdit()
        self._dt_from.setCalendarPopup(True)
        self._dt_from.setDisplayFormat("dd.MM.yyyy HH:mm")
        self._dt_from.setMaximumWidth(150)
        self._dt_from.setToolTip(
            "Startzeitpunkt (Berlin-Wanduhr) des benutzerdefinierten Zeitraums")
        custom_lay.addWidget(self._dt_from)
        custom_lay.addWidget(QLabel("Bis:"))
        self._dt_to = QDateTimeEdit()
        self._dt_to.setCalendarPopup(True)
        self._dt_to.setDisplayFormat("dd.MM.yyyy HH:mm")
        self._dt_to.setMaximumWidth(150)
        self._dt_to.setToolTip(
            "Endzeitpunkt (Berlin-Wanduhr) des benutzerdefinierten Zeitraums")
        custom_lay.addWidget(self._dt_to)
        self._dt_from.dateTimeChanged.connect(self._on_custom_range_changed)
        self._dt_to.dateTimeChanged.connect(self._on_custom_range_changed)
        self._custom_panel.setVisible(False)
        row2.addWidget(self._custom_panel)

        row2.addStretch(1)
        outer.addLayout(row2)

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

    # 21.03.12 (Analytics-Integration): Externe Filterwerte anwenden (z. B.
    # Profil-/Workspace-Restore des AnalyticsWindow). Setzt die Combos mit
    # blockSignals und emittiert die Signale danach EXPLIZIT. None = Eintrag
    # unveraendert lassen.
    # 21.03.14 (Wunsch 1/2): `range_from`/`range_to` stellen einen gespeicherten
    # benutzerdefinierten Zeitraum in den Von-/Bis-Pickern wieder her;
    # `sort_mode` stellt die Tabellen-Sortierung nach Profil-/Workspace-Restore
    # wieder her (die View-Template-Buttons wurden rueckgebaut).
    def apply_external_state(
        self,
        data_tf: Optional[str] = None,
        agg_tf: Optional[str] = None,
        range_preset: Optional[str] = None,
        range_from: Optional[int] = None,
        range_to: Optional[int] = None,
        sort_mode: Optional[str] = None,
    ) -> None:
        """Wendet externe Filterwerte auf die Combos/Picker an (in-memory)."""
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
            self._range_combo.blockSignals(True)
            self._range_combo.setCurrentText(str(range_preset))
            self._range_combo.blockSignals(False)
            if str(range_preset) == "Benutzerdefiniert":
                # Restore eines benutzerdefinierten Zeitraums (21.03.14):
                # Picker mit den gespeicherten Wanduhr-Epochs vorbelegen und
                # den Range explizit emittieren (VM dedupliziert gleiche Werte).
                self._apply_custom_range_state(range_from, range_to)
            elif range_preset:
                self._on_range_changed(str(range_preset))

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
        """Range-Combo-Wechsel: Preset-Zeitraum oder benutzerdefinierter Range.

        21.03.14 (Wunsch 1): Bei "Benutzerdefiniert" werden die Von-/Bis-
        Picker eingeblendet und mit dem zuletzt genutzten Zeitraum vorbelegt
        (Basis = letzter emittierter Range bzw. `now_provider` = letzter
        Datenpunkt statt time.time()). Die Validierung from_ts <= to_ts
        uebernimmt `_emit_custom_range` (Swap).
        """
        if preset == "Benutzerdefiniert":
            self._show_custom_pickers()
            if self._custom_from is None or self._custom_to is None:
                f, t = self._default_custom_range()
                self._custom_from, self._custom_to = f, t
            self._set_custom_pickers(self._custom_from, self._custom_to)
            self._emit_custom_range()
            return
        self._hide_custom_pickers()
        # 21.03.12 (Analytics): Referenzpunkt injizierbar – im Analytics der
        # letzte Datenpunkt (MAX(bar_time)) statt time.time(), damit Presets
        # relativ zum letzten Signal und nicht zur Wanduhr rechnen. Defensiv:
        # None/Fehler (z. B. noch kein Symbol/Timeframe gewaehlt) -> time.time().
        try:
            now = int(self._now_provider())
        except (TypeError, ValueError):
            now = int(_now_epoch())
        seconds = {"24h": 86400, "7d": 7 * 86400, "30d": 30 * 86400,
                   "YTD": _ytd_epoch_offset(now)}.get(preset, 86400)
        f, t = now - seconds, now
        self._last_range = (f, t)
        self.range_changed.emit(preset, f, t)

    # ------------------------------------------------------------------
    # 21.03.14 (Wunsch 1): Benutzerdefinierter Range (Von-/Bis-Picker)
    # ------------------------------------------------------------------
    def _apply_custom_range_state(
        self, from_ts: Optional[int], to_ts: Optional[int]
    ) -> None:
        """Setzt die Von-/Bis-Picker aus einem gespeicherten Custom-Range.

        Wird vom Profil-/Workspace-Restore (`apply_external_state`) gerufen:
        fehlende Werte werden aus dem letzten Range bzw. `now_provider`
        abgeleitet (Vorbelegung statt leerer Picker).
        """
        self._custom_from = int(from_ts) if from_ts is not None else None
        self._custom_to = int(to_ts) if to_ts is not None else None
        if self._custom_from is None or self._custom_to is None:
            f, t = self._default_custom_range()
            self._custom_from, self._custom_to = f, t
        self._set_custom_pickers(self._custom_from, self._custom_to)
        self._show_custom_pickers()
        self._emit_custom_range()

    def _default_custom_range(self) -> tuple:
        """Default-Zeitraum fuer die Vorbelegung (letzter Range/Preset)."""
        if self._last_range is not None:
            return self._last_range
        try:
            now = int(self._now_provider())
        except (TypeError, ValueError):
            now = int(_now_epoch())
        return now - 7 * 86400, now

    def _set_custom_pickers(self, from_ts: int, to_ts: int) -> None:
        """Setzt beide Picker ohne Signal-Loop (blockSignals)."""
        self._dt_from.blockSignals(True)
        self._dt_to.blockSignals(True)
        self._dt_from.setDateTime(self._epoch_to_qdt(from_ts))
        self._dt_to.setDateTime(self._epoch_to_qdt(to_ts))
        self._dt_from.blockSignals(False)
        self._dt_to.blockSignals(False)

    def _show_custom_pickers(self) -> None:
        self._custom_panel.setVisible(True)

    def _hide_custom_pickers(self) -> None:
        self._custom_panel.setVisible(False)

    def _on_custom_range_changed(self, _dt) -> None:
        """Picker-Aenderung: neuen benutzerdefinierten Zeitraum emittieren.

        Kein Programmatic-Setup-Loop noetig: Alle Vorbelegungen/Restores
        laufen ueber `_set_custom_pickers`/`_emit_custom_range` mit
        blockSignals - ein `isVisible()`-Guard ist dadurch ueberfluessig
        und wuerde User-Edits verpassen, solange der Widget-Baum (noch)
        nicht sichtbar ist (z. B. Restore vor dem Fenster-Shown).
        """
        self._emit_custom_range()

    def _emit_custom_range(self) -> None:
        """Emittiert den benutzerdefinierten Zeitraum (from <= to, Swap)."""
        f = self._qdt_to_epoch(self._dt_from.dateTime())
        t = self._qdt_to_epoch(self._dt_to.dateTime())
        if f > t:
            # Validierung from <= to (21.03.14): Werte vertauschen und die
            # Picker konsistent nachziehen (blockSignals gegen Signal-Loop).
            f, t = t, f
            self._dt_from.blockSignals(True)
            self._dt_to.blockSignals(True)
            self._dt_from.setDateTime(self._epoch_to_qdt(f))
            self._dt_to.setDateTime(self._epoch_to_qdt(t))
            self._dt_from.blockSignals(False)
            self._dt_to.blockSignals(False)
        self._custom_from, self._custom_to = f, t
        self._last_range = (f, t)
        self.range_changed.emit("Benutzerdefiniert", f, t)

    @staticmethod
    def _epoch_to_qdt(epoch: int) -> QDateTime:
        """Wandelt eine Wanduhr-Epoch in QDateTime (Felder = Berlin-Wanduhr).

        Invariante 7: MT5-Epochs sind Berlin-Wanduhr-encoded – die UTC-
        Darstellung der Epoch IST die Wanduhr-Zeit. Die Feldwerte des
        QDateTime werden aus dieser UTC-Darstellung uebernommen, damit der
        Picker die Wanduhr-Zeit anzeigt (kein stiller OS-TZ-Offset).
        """
        from datetime import datetime, timezone
        dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        return QDateTime(dt.year, dt.month, dt.day, dt.hour, dt.minute,
                         dt.second)

    @staticmethod
    def _qdt_to_epoch(qdt: QDateTime) -> int:
        """Wandelt QDateTime (Wanduhr-Felder) in eine Wanduhr-Epoch.

        Die im Picker angezeigten Feldwerte sind die Berlin-Wanduhr-Zeit;
        sie werden als UTC-encoded Epoch interpretiert (Invariante 7) –
        unabhaengig von der System-Zeitzone.
        """
        from datetime import timezone
        dt = qdt.toPython()  # naive datetime, Felder = Wanduhr
        return int(dt.replace(tzinfo=timezone.utc).timestamp())

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


def _ytd_epoch_offset(now: int) -> int:
    """Sekunden seit Jahresbeginn (Wanduhr)."""
    from datetime import datetime, timezone
    dt = datetime.fromtimestamp(now, tz=timezone.utc)
    start = datetime(dt.year, 1, 1, tzinfo=timezone.utc)
    return int(now - start.timestamp())
