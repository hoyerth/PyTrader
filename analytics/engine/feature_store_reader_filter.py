"""
feature_store_reader_filter.py - Normalisierung, Filter, Formatierung (statische Helfer)

23.05 God-File-Split (15.08.2026): Aus analytics/engine/feature_store_reader.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der FeatureStoreReader
als Mixin (Klasse FeatureStoreFilterMixin).
"""

from datetime import (
    datetime as _dt_datetime,
)

from datetime import (
    timezone as _dt_timezone,
)

from typing import (
    Any,
    Dict,
    List,
    Optional,
)

from db_service import (
    _parse_json_field,
)

from analytics.engine.feature_store_reader_constants import (
    DOW_WEEK_LABELS,
    SCHEMA_VERSION_DEFAULT,
)

class FeatureStoreFilterMixin:

    @staticmethod
    def _normalize_feature_data(raw: Any) -> Dict[str, Any]:
        """Parst feature_data (str->dict) und stellt schema_version sicher.

        E-3: Fehlt das Pflichtfeld `schema_version` (Alt-Rows), wird es beim
        Lesen additiv mit dem Default `"1.0.0"` ergaenzt – die DB-Zeile bleibt
        unveraendert (rein lesender Reader).
        """
        data = _parse_json_field(raw) or {}
        data = dict(data)
        data.setdefault("schema_version", SCHEMA_VERSION_DEFAULT)
        return data

    @staticmethod
    def _apply_feature_filter(
        feature_ids: Optional[List[str]],
        feature_id: Optional[str],
        conditions: List[str],
        params: List[Any],
        instance_hashes: Optional[List[str]] = None,
    ) -> None:
        """Erweitert WHERE um einen feature_id-Filter (IN-Clause bzw. Einzel-ID).

        15.03-E (Multi-Select): Bevorzugt wird `feature_ids` – die
        Analytics-Engine filtert per `WHERE feature_id IN (...)` ueber alle
        gewaehlten Datenquellen. Der Legacy-Parameter `feature_id` bleibt
        fuer Alt-Aufrufer (z. B. test/check_p15_s4_infra.py) erhalten.
        Leere Liste/None = KEIN Filter (alle Rows).

        Bugfix 08.08.2026 (Bug 1: 'keine Anzeige ausgewaehlter Services'):
        Der Filter ist case-insensitiv UND whitespace-tolerant –
        `LOWER(TRIM(feature_id))` auf der DB-Spalte sowie `LOWER(TRIM(..))`
        auf den Parameterwerten. Muster: `fetch_last_execution_dates`
        normalisiert bereits so (historisch reale Gross-/Kleinschreibungs-
        und Leerzeichen-Abweichungen zwischen Registry-plugin_ids und
        gespeicherten feature_store-Werten). Vorher matchte die nackte
        `feature_id IN (...)`-Clause bei solchen Abweichungen nichts und
        Tabelle/Heatmap blieben leer.
        """
        ids = [str(i).strip().lower() for i in (feature_ids or [])
               if str(i).strip()]
        if ids:
            placeholders = ", ".join("?" for _ in ids)
            conditions.append(f"LOWER(TRIM(feature_id)) IN ({placeholders})")
            params.extend(ids)
        elif feature_id:
            conditions.append("LOWER(TRIM(feature_id)) = LOWER(TRIM(?))")
            params.append(feature_id)
        # Runde 10 (Bug 1): Varianten-Einschraenkung - werden
        # instance_hashes uebergeben, bleiben NUR die Rows der gewaehlten
        # Varianten (exakter Hash-Match, case-insensitiv) plus Alt-Bestand
        # OHNE Hash (NULL) - letztere gehoeren der plugin_id als Ganzes
        # und werden nie durch die Varianten-Auswahl ausgeblendet.
        if instance_hashes:
            hashes = [str(h).strip().lower() for h in instance_hashes
                      if str(h).strip()]
            if hashes:
                placeholders = ", ".join("?" for _ in hashes)
                conditions.append(
                    f"(instance_hash IS NULL OR instance_hash = '' OR "
                    f"LOWER(TRIM(instance_hash)) IN ({placeholders}))")
                params.extend(hashes)

    @staticmethod
    def _apply_field_pair_filter(
        field_pairs: Optional[List[str]],
        conditions: List[str],
        params: List[Any],
    ) -> None:
        """Erweitert WHERE um den (Service|Parameter)-Paar-Filter.

        12.08.2026 (Option A, Bug 1/2): Jedes Paar '{service_id}|{key}'
        des 'Feld'-Dropdowns wird zu einer OR-Bedingung
        `LOWER(TRIM(feature_id)) = ? AND json_extract_string(feature_data,
        '$.key') IS NOT NULL` - der Reader filtert damit auf PARAMETER-Ebene (nur Rows, deren
        feature_data den gewaehlten JSON-Key des jeweiligen Services
        wirklich traegt). Identifier-unsichere Keys werden defensiv
        uebersprungen (kein SQL-Injection-Risiko, Muster
        `_is_json_key_identifier`). Leere/None-Liste = kein Filter.
        """
        if not field_pairs:
            return
        clauses: List[str] = []
        for pair in field_pairs:
            s = str(pair or "")
            if "|" not in s:
                continue
            sid, key = s.split("|", 1)
            sid = sid.strip()
            key = key.strip()
            if not sid or not key or not FeatureStoreReader._is_json_key_identifier(key):
                continue
            # 12.08.2026 (Option A): `json_extract_string(..., '$.key')` statt
            # `feature_data->>'key'` - der DuckDB-Arrow-Operator kollidiert in
            # Kombination mit LOWER/TRIM-Equalities mit einem Optimizer-Bug
            # (v1.5.5: versucht die JSON-Spalte auf numerisch/BOOL zu casten
            # und wirft fuer nicht-matchende Zeilen). json_extract_string
            # liefert NULL fuer fehlende Keys (identische Semantik) und ist
            # sowohl fuer VARCHAR- als auch JSON-Spalten stabil.
            clauses.append(
                f"(LOWER(TRIM(feature_id)) = ? AND "
                f"json_extract_string(feature_data, '$.{key}') IS NOT NULL)")
            params.append(sid.lower().strip())
        if clauses:
            conditions.append("(" + " OR ".join(clauses) + ")")

    # 21.03.20 (Analytics Modus-Filter): source_mode-Filter fuer
    # Multi-Modus-Services (srv_swing_structure/srv_swing_momentum/...).
    # Nur die 6 Swing-/Trend-Services schreiben `source_mode` top-level
    # in jedes feature_data-Record; `"all"`/None/leer = kein Filter.
    # Muster-Konsistenz (21.03.16): json_extract_string statt
    # feature_data->>'source_mode' (DuckDB-v1.5.5-Arrow-Optimizer-Bug
    # in Kombination mit LOWER/TRIM-Equalities). LOWER auf beiden Seiten
    # = case-tolerantes Matching (z. B. 'ma_peak_hysteresis').
    @staticmethod
    def _apply_mode_filter(
        service_mode: Optional[str],
        conditions: List[str],
        params: List[Any],
    ) -> None:
        if not service_mode or str(service_mode).lower() in ("all", "alle", ""):
            return
        conditions.append(
            "LOWER(json_extract_string(feature_data, '$.source_mode')) = LOWER(?)")
        params.append(str(service_mode).strip())

    # 21.03.12 (MTF-FC auf Analytics): Optionaler bar_time-Zeitfilter.
    # Wird von allen Daten-Queries (fetch_rows/fetch_columns/fetch_heatmap/
    # fetch_generic_heatmap) ueber `from_ts`/`to_ts` aufgerufen.
    @staticmethod
    def _apply_time_range(
        from_ts: Optional[Any],
        to_ts: Optional[Any],
        conditions: List[str],
        params: List[Any],
    ) -> None:
        """Erweitert WHERE um einen optionalen bar_time-Zeitfilter.

        `from_ts`/`to_ts` sind Wanduhr-Epochs (int, relativ zum letzten
        Datenpunkt – `now_provider` des MtfFilterBarWidget) oder None.
        `EXTRACT('epoch' FROM bar_time)` liefert exakt die gespeicherte
        Wanduhr-Epoch (Invariante 7) – der Vergleich ist damit DST-robust
        (Wanduhr gegen Wanduhr). Ungueltige Werte werden defensiv
        ignoriert (kein Filter).
        """
        if from_ts is None and to_ts is None:
            return
        try:
            f = int(from_ts)
        except (TypeError, ValueError):
            f = None
        try:
            t = int(to_ts)
        except (TypeError, ValueError):
            t = None
        if f is not None and t is not None:
            conditions.append(
                "EXTRACT('epoch' FROM bar_time)::BIGINT BETWEEN ? AND ?")
            params.extend([f, t])
        elif f is not None:
            conditions.append("EXTRACT('epoch' FROM bar_time)::BIGINT >= ?")
            params.append(f)
        elif t is not None:
            conditions.append("EXTRACT('epoch' FROM bar_time)::BIGINT <= ?")
            params.append(t)

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        """Konvertiert einen DB-Wert in float (None/ungueltig -> None)."""
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Lesen: Dynamische JSON-Keys (Scatter / Verteilung / Heatmap, 19.02)
    # ------------------------------------------------------------------
    @staticmethod
    def _is_json_key_identifier(key: Any) -> bool:
        """True, wenn der JSON-Key ein sicheres DuckDB-Identifier-Format hat.

        Wird fuer SQL-Einbettungen (feature_data->>'key') verwendet – nur
        [A-Za-z_][A-Za-z0-9_]* wird akzeptiert (kein SQL-Injection-/Quoting-
        Risiko). JSON-Keys aus den Service-Payloads sind alle identifier-sicher.
        """
        import re
        return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key or "")))

    @staticmethod
    def _format_dim_value(dim: str, value: Any) -> str:
        """Formatiert einen Dimensions-Rohwert fuer Achsen-Beschriftungen.

        20.02 (generische Heatmap): `date` -> 'TT.MM.', `hour` -> 'HH:00',
        `dow` -> Mo-Fr-Kurzname (20.02.01 E5, DOW_WEEK_LABELS; Sonntag/
        Samstag werden per SQL-Filter ausgeschlossen). Alle anderen
        Dimensionen (timeframe/service_id/symbol) -> Rohwert-String.
        """
        try:
            if dim == "date":
                if hasattr(value, "strftime"):
                    # 21.03.12 (bucket_tf): tz-aware Datetimes (Session-TZ)
                    # auf naive Wanduhr-UTC normalisieren - sonst zeigt das
                    # Label den Berlin-Nachbar-Datumstag (+2h/+1h).
                    try:
                        value = value.astimezone(
                            _dt_timezone.utc).replace(tzinfo=None)
                    except Exception:
                        pass
                    return value.strftime("%d.%m.")
                return str(value)
            if dim == "hour":
                return f"{int(value):02d}:00"
            if dim == "dow":
                v = int(value)
                if 1 <= v <= len(DOW_WEEK_LABELS):
                    return DOW_WEEK_LABELS[v - 1]
                return str(value)
        except (TypeError, ValueError):
            pass
        return str(value)

    @staticmethod
    def _axis_coords(dim: str, values: List[Any]) -> List[float]:
        """Achsen-Koordinaten (natuerliche Werte) je Matrix-Zeile/-Spalte.

        20.02-Bugfix (09.08.2026, Punkte 3-6/User-Meldung): Fuer die
        TradingView-aehnliche Achsen-Darstellung tragen die Achsen die
        NATUERLICHEN Werte statt Zell-Indizes:
          - `date`      -> Wanduhr-Mitternachts-Epoch (Sekunden)
          - hour        -> die ganzzahligen Stunden (0-23)
          - dow         -> 1..5 (Montag-Freitag, 20.02.01 E5)
          - kategorial  -> Indizes 0..n-1 (timeframe/service_id/symbol)
        Das Widget mappt das ImageItem per setRect auf diesen Bereich und
        erzeugt dynamische Ticks je Zoom-Level (bis zur Minute bei Datum).
        """
        if dim == "date":
            out: List[float] = []
            for v in values:
                if isinstance(v, _dt_datetime):
                    # 21.03.12 (bucket_tf): Naive Datetimes von to_timestamp
                    # sind Wanduhr-encoded - als UTC-Darstellung interpretieren
                    # (Invariante 7), sonst waere die Achse um den Berlin-
                    # Offset (+2h/+1h) verschoben.
                    if v.tzinfo is None:
                        out.append(float(int(
                            v.replace(tzinfo=_dt_timezone.utc).timestamp())))
                    else:
                        out.append(float(int(v.timestamp())))
                elif hasattr(v, "year") and hasattr(v, "month") \
                        and hasattr(v, "day"):
                    # date-Objekt (CAST AS DATE): Mitternacht Wanduhr-UTC
                    out.append(float(int(_dt_datetime(
                        v.year, v.month, v.day,
                        tzinfo=_dt_timezone.utc).timestamp())))
                else:
                    try:
                        out.append(float(int(_dt_datetime.fromisoformat(
                            str(v)).replace(tzinfo=_dt_timezone.utc)
                            .timestamp())))
                    except (TypeError, ValueError):
                        out.append(0.0)
            return out
        if dim in ("hour", "dow"):
            try:
                return [float(int(v)) for v in values]
            except (TypeError, ValueError):
                return [float(i) for i in range(len(values))]
        # Kategorial (timeframe/service_id/symbol): Indizes 0..n-1.
        return [float(i) for i in range(len(values))]
