"""
feature_store_reader_ohlcv.py - OHLCV-Snapshots, Tages-Ohlc, Execution-Dates/Hashes, TF-Status

23.05 God-File-Split (15.08.2026): Aus analytics/engine/feature_store_reader.py
extrahiert, KEINE Logik-Aenderung. Enthaelt die Methoden der FeatureStoreReader
als Mixin (Klasse FeatureStoreOhlcvMixin).
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
    DbPool,
)

from analytics.engine.feature_store_reader_constants import (
    DAILY_OHLC_MAX_DAYS,
    DAYS_PER_WEEK,
    DB_MARKET,
    HOURS_PER_DAY,
    OHLCV_SNAPSHOT_LIMIT,
    SENTINEL_NATIVE,
    canonical_tf_sort,
)

class FeatureStoreOhlcvMixin:

    # ------------------------------------------------------------------
    # Lesen: OHLCV-Snapshot fuer das Candle-Overlay (20.02, E9)
    # ------------------------------------------------------------------
    def fetch_ohlcv_snapshot(
        self,
        symbol: str,
        timeframe: str,
        limit: Optional[int] = None,
        market_db_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Liest OHLCV-Bars aus market_data.duckdb (read-only, Wanduhr).

        20.02 (E9, Candle-Overlay): Quelle sind die OHLCV-Rohdaten
        (`ohlcv_bars` in `data/market_data.duckdb`, Spalten
        time/open/high/low/close/tick_volume – Muster
        FeatureBuilder.load_ohlcv()). Der Preis-Strip im HeatmapWidget
        gruppiert die Bars pro Spalte (Datum) zu Tages-Ohlc.

        Wanduhr-Garantie (Invariante 7): Die Epochs sind Wanduhr-encoded –
        `_epoch_of()` (UTC-Darstellung) liefert exakt die gespeicherte
        Wanduhr-Epoch; das Widget dekodiert sie als UTC-Datum.

        Args:
            symbol/timeframe: Filter (case-insensitive)
            limit: Max. Bars (Default OHLCV_SNAPSHOT_LIMIT = 5000), die
                NEUESTEN zuerst (ORDER BY time DESC).
            market_db_path: Testbarkeit (Seam) – Default DB_MARKET.

        Returns:
            {"bars": [{"time": int(Wanduhr-Epoch), "open": float, "high": float,
                       "low": float, "close": float, "volume": float}, ...]
             (aufsteigend chronologisch), "symbol", "timeframe"}
        """
        if not symbol or not timeframe:
            return {"bars": [], "symbol": symbol, "timeframe": timeframe}
        if limit is None:
            limit = OHLCV_SNAPSHOT_LIMIT
        con = DbPool.get(market_db_path or DB_MARKET)
        try:
            rows = con.execute("""
                SELECT "time", open, high, low, close, tick_volume
                FROM ohlcv_bars
                WHERE LOWER(symbol) = LOWER(?) AND LOWER(timeframe) = LOWER(?)
                  AND "time" IS NOT NULL
                  AND open IS NOT NULL AND high IS NOT NULL
                  AND low IS NOT NULL AND close IS NOT NULL
                ORDER BY "time" DESC
                LIMIT ?
            """, [symbol, timeframe, int(limit)]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_ohlcv_snapshot "
                  f"fehlgeschlagen: {e}")
            return {"bars": [], "symbol": symbol, "timeframe": timeframe}

        bars: List[Dict[str, Any]] = []
        for r in rows:
            try:
                bars.append({
                    "time": self._epoch_of(r[0]),
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                    "volume": float(r[5]) if r[5] is not None else 0.0,
                })
            except (TypeError, ValueError):
                continue
        # Aufsteigend (chronologisch) – das Widget rendert von links nach rechts.
        bars.reverse()
        return {"bars": bars, "symbol": symbol, "timeframe": timeframe}

    # ------------------------------------------------------------------
    # Lesen: Tages-OHLC fuer das Candle-Overlay (20.02-Bugfix, 09.08.2026)
    # ------------------------------------------------------------------
    def fetch_daily_ohlc(
        self,
        symbol: str,
        timeframe: str,
        max_days: Optional[int] = None,
        market_db_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Tages-Ohlc je Wanduhr-Datum (SQL-seitig aggregiert, read-only).

        20.02-Bugfix (09.08.2026, Punkt 1+2/User-Meldung): Das Candle-Overlay
        muss im GLEICHEN Canvas ueber der Heatmap liegen und den GESAMTEN
        Heatmap-Zeitraum abdecken. Dafuer werden die ohlcv_bars SQL-seitig pro
        Wanduhr-Datum zu einem Tages-Candle aggregiert (GROUP BY Datum in
        UTC-Darstellung – die Epochs sind Wanduhr-encoded, Invariante 7) –
        um Groessenordnungen schneller als das Laden aller Bars + Python-
        Gruppierung (bei M1 wären das sonst > 1 Mio. Bars).

        Wanduhr-Garantie (Invariante 7): `CAST("time" AT TIME ZONE 'UTC' AS
        DATE)` liefert das Wanduhr-Datum; die Mitternachts-Epoch wird als
        UTC-Darstellung berechnet (exakt die Wanduhr-Epoch des Tages).

        Args:
            symbol/timeframe: Filter (case-insensitive)
            max_days: Max. Anzahl Tage (Default DAILY_OHLC_MAX_DAYS = 4000;
                deckt ~11 Jahre M1 bzw. den gesamten Heatmap-Zeitraum).
            market_db_path: Testbarkeit (Seam) – Default DB_MARKET.

        Returns:
            {"bars": [{"time": int(Wanduhr-Mitternachts-Epoch), "open": float,
                       "high": float, "low": float, "close": float}, ...]
             (aufsteigend chronologisch), "symbol", "timeframe"}
        """
        if not symbol or not timeframe:
            return {"bars": [], "symbol": symbol, "timeframe": timeframe}
        if max_days is None:
            max_days = DAILY_OHLC_MAX_DAYS
        con = DbPool.get(market_db_path or DB_MARKET)
        try:
            rows = con.execute("""
                SELECT
                    CAST("time" AT TIME ZONE 'UTC' AS DATE) AS d,
                    FIRST(open ORDER BY "time") AS open,
                    MAX(high) AS high,
                    MIN(low) AS low,
                    LAST(close ORDER BY "time") AS close
                FROM ohlcv_bars
                WHERE LOWER(symbol) = LOWER(?)
                  AND LOWER(timeframe) = LOWER(?)
                  AND "time" IS NOT NULL
                  AND open IS NOT NULL AND high IS NOT NULL
                  AND low IS NOT NULL AND close IS NOT NULL
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT ?
            """, [symbol, timeframe, int(max_days)]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_daily_ohlc "
                  f"fehlgeschlagen: {e}")
            return {"bars": [], "symbol": symbol, "timeframe": timeframe}

        bars: List[Dict[str, Any]] = []
        for r in rows:
            d = r[0]
            if d is None:
                continue
            try:
                if hasattr(d, "year") and hasattr(d, "month") and hasattr(d, "day"):
                    epoch = int(_dt_datetime(
                        d.year, d.month, d.day,
                        tzinfo=_dt_timezone.utc).timestamp())
                else:
                    epoch = int(_dt_datetime.fromisoformat(
                        str(d)).replace(tzinfo=_dt_timezone.utc).timestamp())
                bars.append({
                    "time": epoch,
                    "open": float(r[1]),
                    "high": float(r[2]),
                    "low": float(r[3]),
                    "close": float(r[4]),
                })
            except (TypeError, ValueError):
                continue
        # Aufsteigend (chronologisch) – das Widget rendert von links nach rechts.
        bars.reverse()
        return {"bars": bars, "symbol": symbol, "timeframe": timeframe}

    # ------------------------------------------------------------------
    # Lesen: Datum der letzten Ausfuehrung (MasterTree, 05.08.2026)
    # ------------------------------------------------------------------
    def fetch_last_execution_dates(self) -> Dict[str, str]:
        """Neuester Schreib-Zeitpunkt je feature_id – formatiert als 'DD.MM.JJ'.

        Wird vom ServiceSelectorModel fuer die MasterTree-Anzeige
        'Service_Name (DD.MM.JJ)' gelesen (Datum der letzten Ausfuehrung).
        Quelle: MAX(created_at) je feature_id ueber ALLE Symbole/Timeframes.
        store_plugin_payload() aktualisiert created_at bei jedem Upsert
        (ON CONFLICT DO UPDATE), damit der Zeitstempel die LETZTE Ausfuehrung
        widerspiegelt (nicht den Erst-Schreibzeitpunkt der Bar).

        Robustheit (Bugfix 05.08.2026, Punkt 1):
          * Case-insensitiv: feature_id wird per LOWER(TRIM(...)) normalisiert –
            Registry-/Plugin-IDs (z.B. 'srv_proximity') werden unabhaengig von der
            in der DB gespeicherten Gross-/Kleinschreibung gefunden.
          * Whitespace-tolerant: fuehrende/trailing Leerzeichen (z.B. durch
            Alt-Schreibpfade) werden ignoriert.
          * Defensiv: Zeilen mit NULL/leerer feature_id ODER NULL created_at
            werden uebersprungen (Alt-Rows ohne Zeitstempel koennen kein
            gueltiges Datum liefern).

        Returns:
            Dict feature_id (lower) -> 'DD.MM.JJ' (z.B. {'srv_proximity': '05.08.26'});
            leer bei fehlender DB/Tabelle oder Fehler (defensiv).
        """
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT LOWER(TRIM(feature_id)) AS fid, MAX(created_at)
                FROM feature_store
                WHERE feature_id IS NOT NULL AND TRIM(feature_id) != ''
                  AND feature_id != ?
                GROUP BY LOWER(TRIM(feature_id))
            """, [SENTINEL_NATIVE]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_last_execution_dates "
                  f"fehlgeschlagen: {e}")
            return {}
        out: Dict[str, str] = {}
        for r in rows:
            if r[0] is None or r[1] is None:
                continue
            try:
                out[str(r[0])] = r[1].strftime("%d.%m.%y")
            except (AttributeError, ValueError):
                continue
        return out

    def fetch_service_tf_status(
        self, plugin_id: str, instance_hash: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Timeframe-Verfuegbarkeit eines Services (21.01b, Schritt 1).

        Liest fuer die Pill-Badges (TfStatusBadgeBar) je Timeframe des
        Services die Anzahl der Feature-Store-Eintraege und den letzten
        Schreib-Zeitpunkt direkt aus der feature_store-Tabelle.

        Bugfix 12.08.2026 (User-Meldung 'Data only loeschen'): Ohne
        `instance_hash` ist die Abfrage service-weit (alle Varianten der
        plugin_id). Wird ein `instance_hash` uebergeben, werden NUR die
        Rows GENAU dieser Variante gezaehlt – nach dem Purge einer
        Variante verschwinden ihre TF-Pills damit korrekt (vorher zeigten
        die Pill-Badges die TFs aller Varianten des Services gemeinsam).

        SQL: SELECT LOWER(timeframe), COUNT(*), MAX(created_at)
             FROM feature_store
             WHERE LOWER(TRIM(feature_id)) = LOWER(TRIM(?))
               [AND LOWER(TRIM(instance_hash)) = LOWER(TRIM(?))]
             GROUP BY LOWER(timeframe)

        Robustheit wie `fetch_last_execution_dates`: Case-insensitiv
        (LOWER/TRIM auf feature_id UND timeframe) und defensiv gegen
        NULL/leere Rows (feature_id, timeframe, created_at).

        Args:
            plugin_id: Plugin-ID des Services (z.B. 'srv_proximity').
            instance_hash: Optionaler Varianten-Hash – werden nur gesetzt,
                zeigt der Status ausschliesslich diese Variante (Clone/
                Preset/Set-Instanz). None/leer = service-weit.

        Returns:
            Dict Timeframe (upper, z.B. 'M1') -> {'count': int, 'last_run': str}
            mit 'last_run' als 'DD.MM.JJ HH:MM' (Wanduhr, UTC-Darstellung);
            leer bei fehlender DB/Tabelle oder Fehler (defensiv).
        """
        if not plugin_id or not str(plugin_id).strip():
            return {}
        conditions = [
            "feature_id IS NOT NULL AND TRIM(feature_id) != ''",
            "LOWER(TRIM(feature_id)) = LOWER(TRIM(?))",
        ]
        params: List[Any] = [str(plugin_id)]
        # Varianten-Scope (Bugfix 12.08.2026): exakter Hash-Match (nur diese
        # Variante, keine service-weiten Alt-Rows anderer Instanzen).
        h_s = str(instance_hash or "").strip()
        if h_s:
            conditions.append("LOWER(TRIM(instance_hash)) = LOWER(TRIM(?))")
            params.append(h_s)
        con = self._get_connection()
        try:
            rows = con.execute(f"""
                SELECT LOWER(TRIM(timeframe)) AS tf, COUNT(*) AS cnt,
                       MAX(created_at) AS last_run
                FROM feature_store
                WHERE {' AND '.join(conditions)}
                GROUP BY LOWER(TRIM(timeframe))
            """, params).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_service_tf_status "
                  f"fehlgeschlagen: {e}")
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            tf_raw = r[0]
            cnt = r[1]
            created = r[2]
            if tf_raw is None or cnt is None:
                continue
            last_run = ""
            if created is not None:
                try:
                    last_run = created.strftime("%d.%m.%y %H:%M")
                except (AttributeError, ValueError):
                    last_run = ""
            out[str(tf_raw).upper()] = {"count": int(cnt), "last_run": last_run}
        # 13.08.2026 (Punkt 3, F3): Sortierte Rueckgabe (kanonisch fein ->
        # grob) - die Pill-Strips aller drei Fenster (AnalyticsWindow,
        # ServicePicker, ServiceWindow) rendern die TFs damit korrekt
        # sortiert statt alphabetisch.
        return {tf: out[tf] for tf in canonical_tf_sort(out)}

    def fetch_last_execution_dates_by_hash(
        self,
    ) -> Dict[str, Dict[str, str]]:
        """Neuester Schreib-Zeitpunkt je (feature_id, instance_hash).

        Bugfix 10.08.2026 (Varianten-Ausfuehrungsdatum): Varianten/Clones
        (indicator_presets) haben EIGENE Feature-Store-Rows (Spalte
        `instance_hash`, 20.04 Q9). Fuer die MasterTree-Anzeige
        '<Preset> (DD.MM.JJ)' wird das Datum der letzten Ausfuehrung je
        Parameter-Variante benoetigt – nicht das der plugin_id insgesamt.

        Quelle: MAX(created_at) GROUP BY feature_id + instance_hash ueber
        ALLE Symbole/Timeframes. Case-insensitiv/whitespace-tolerant wie
        `fetch_last_execution_dates`; Rows ohne instance_hash (nicht
        Varianten-gesteuerte Services) und ohne created_at werden
        uebersprungen.

        Returns:
            Dict feature_id (lower) -> {instance_hash: 'DD.MM.JJ'} – leer
            bei fehlender DB/Tabelle oder Fehler (defensiv).
        """
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT LOWER(TRIM(feature_id)) AS fid, instance_hash,
                       MAX(created_at)
                FROM feature_store
                WHERE feature_id IS NOT NULL AND TRIM(feature_id) != ''
                  AND feature_id != ?
                  AND instance_hash IS NOT NULL AND instance_hash != ''
                GROUP BY LOWER(TRIM(feature_id)), instance_hash
            """, [SENTINEL_NATIVE]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] "
                  f"fetch_last_execution_dates_by_hash fehlgeschlagen: {e}")
            return {}
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            if r[0] is None or r[1] is None or r[2] is None:
                continue
            try:
                out.setdefault(str(r[0]), {})[str(r[1])] = r[2].strftime(
                    "%d.%m.%y")
            except (AttributeError, ValueError):
                continue
        return out

    def fetch_source_modes_by_hash(
        self,
    ) -> Dict[str, Dict[str, str]]:
        """Letzter source_mode je (feature_id, instance_hash).

        13.08.2026 (Punkt 2, MasterTree-Modus): Die Clone-/Varianten-Labels
        sollen den AKTUELLEN Modus zeigen. Da die Preset-Params haeufig
        KEINEN 'mode'-Key enthalten (der Modus wird erst beim Run bestimmt),
        wird hier der source_mode der JEWEILS LETZTEN Ausfuehrung je
        (feature_id, instance_hash) gelesen (JSON-Key in feature_data,
        DuckDB arg_max(..., bar_time)). Read-only, ueber ALLE Symbole/
        Timeframes; case-insensitiv wie die Datums-Geschwister.

        Returns:
            Dict feature_id (lower) -> {instance_hash: source_mode} - leer
            bei fehlender DB/Tabelle oder Fehler (defensiv).
        """
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT LOWER(TRIM(feature_id)) AS fid, instance_hash,
                       arg_max(json_extract_string(
                           feature_data, '$.source_mode'), bar_time) AS mode
                FROM feature_store
                WHERE feature_id IS NOT NULL AND TRIM(feature_id) != ''
                  AND feature_id != ?
                  AND instance_hash IS NOT NULL AND instance_hash != ''
                  AND json_extract_string(feature_data, '$.source_mode')
                      IS NOT NULL
                GROUP BY LOWER(TRIM(feature_id)), instance_hash
            """, [SENTINEL_NATIVE]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] "
                  f"fetch_source_modes_by_hash fehlgeschlagen: {e}")
            return {}
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            if r[0] is None or r[1] is None or r[2] is None:
                continue
            out.setdefault(str(r[0]), {})[str(r[1])] = str(r[2])
        return out

    def fetch_last_execution_datetimes_by_hash(
        self,
    ) -> Dict[str, Dict[str, str]]:
        """Neuester Schreib-Zeitpunkt je (feature_id, instance_hash) mit Uhrzeit.

        Bugfix 11.08.2026 (Dropdown-Anzeige, User-Meldung 1): Das
        Feld-Dropdown haengt an gecheckte Varianten das Datum+Uhrzeit der
        letzten Ausfuehrung an ('{Name} / {Preset} / DD.MM.JJ HH:MM').
        `fetch_last_execution_dates_by_hash` liefert nur das Datum - diese
        Methode ergaenzt die Uhrzeit (Format 'DD.MM.JJ HH:MM', z. B.
        '23.04.26 22:14'). Quelle/Filter/Semantik identisch zur
        Datums-Variante (MAX(created_at) GROUP BY feature_id +
        instance_hash ueber ALLE Symbole/Timeframes; case-insensitiv/
        whitespace-tolerant; Rows ohne instance_hash/created_at werden
        uebersprungen).

        Returns:
            Dict feature_id (lower) -> {instance_hash: 'DD.MM.JJ HH:MM'} -
            leer bei fehlender DB/Tabelle oder Fehler (defensiv).
        """
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT LOWER(TRIM(feature_id)) AS fid, instance_hash,
                       MAX(created_at)
                FROM feature_store
                WHERE feature_id IS NOT NULL AND TRIM(feature_id) != ''
                  AND feature_id != ?
                  AND instance_hash IS NOT NULL AND instance_hash != ''
                GROUP BY LOWER(TRIM(feature_id)), instance_hash
            """, [SENTINEL_NATIVE]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] "
                  f"fetch_last_execution_datetimes_by_hash fehlgeschlagen: "
                  f"{e}")
            return {}
        out: Dict[str, Dict[str, str]] = {}
        for r in rows:
            if r[0] is None or r[1] is None or r[2] is None:
                continue
            try:
                out.setdefault(str(r[0]), {})[str(r[1])] = r[2].strftime(
                    "%d.%m.%y %H:%M")
            except (AttributeError, ValueError):
                continue
        return out

    def fetch_last_execution_datetimes(self) -> Dict[str, str]:
        """Neuester Schreib-Zeitpunkt je feature_id MIT Uhrzeit.

        Bugfix 11.08.2026 (Runde 16c, Dropdown-Anzeige, User-Meldung):
        Das Feld-Dropdown haengt an Services OHNE Varianten (Standalone,
        z. B. srv_trend_breakout) das Datum+Uhrzeit der letzten Ausfuehrung
        an ('{Name} / {Key} / DD.MM.JJ HH:MM', z. B. '23.04.26 22:14').
        `fetch_last_execution_dates` liefert nur das Datum - diese Methode
        ergaenzt die Uhrzeit. Quelle/Filter/Semantik identisch zur
        Datums-Variante (MAX(created_at) GROUP BY feature_id ueber ALLE
        Symbole/Timeframes; case-insensitiv/whitespace-tolerant; Rows ohne
        created_at werden uebersprungen).

        Returns:
            Dict feature_id (lower) -> 'DD.MM.JJ HH:MM' - leer bei
            fehlender DB/Tabelle oder Fehler (defensiv).
        """
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT LOWER(TRIM(feature_id)) AS fid, MAX(created_at)
                FROM feature_store
                WHERE feature_id IS NOT NULL AND TRIM(feature_id) != ''
                  AND feature_id != ?
                GROUP BY LOWER(TRIM(feature_id))
            """, [SENTINEL_NATIVE]).fetchall()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_last_execution_datetimes "
                  f"fehlgeschlagen: {e}")
            return {}
        out: Dict[str, str] = {}
        for r in rows:
            if r[0] is None or r[1] is None:
                continue
            try:
                out[str(r[0])] = r[1].strftime("%d.%m.%y %H:%M")
            except (AttributeError, ValueError):
                continue
        return out

    # ------------------------------------------------------------------
    # Lesen: Metadaten
    # ------------------------------------------------------------------
    def get_available_timeframes(self, symbol: str) -> List[str]:
        """Liefert die Timeframes mit Feature-Store-Daten fuer ein Symbol.

        Dient der TF-Combo-Ausgrauung (15.03-Fix): Timeframes ohne Daten im
        feature_store werden in der UI ausgegraut und sind nicht auswaehlbar.

        Returns:
            Liste der Timeframe-Strings (z. B. ["M1", "H1", ...]) – leer,
            wenn das Symbol keine Feature-Daten hat.
        """
        if not symbol:
            return []
        con = self._get_connection()
        try:
            rows = con.execute("""
                SELECT DISTINCT timeframe FROM feature_store
                WHERE LOWER(symbol) = LOWER(?)
            """, [symbol]).fetchall()
            # 13.08.2026 (Punkt 3, F3): Kanonische Sortierung statt
            # `ORDER BY timeframe` (alphabetisch).
            return canonical_tf_sort(
                [str(r[0]) for r in rows if r[0] is not None])
        except Exception as e:
            print(f"WARN [FeatureStoreReader] get_available_timeframes "
                  f"fehlgeschlagen: {e}")
            return []

    # ------------------------------------------------------------------
    # Lesen: Jump-to-Chart-Helfer (15.03 Schritt 5, open_chart_at_bar)
    # ------------------------------------------------------------------
    def fetch_latest_bar_time(
        self,
        symbol: str,
        timeframe: str,
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch (int) der Feature-Rows (oder None).

        Wird fuer 'Jump-to-Chart' (Variante 2) aus Scatter/Heatmap genutzt:
        Ein Klick auf einen Punkt/eine Zelle oeffnet das Chart-Fenster an der
        zugehoerigen Bar-Position. Wanduhr-Garantie: EXTRACT('epoch') liefert
        exakt die gespeicherte Wanduhr-Epoch (Invariante 7).

        15.03-E (Multi-Select): Ueber `feature_ids` wird der neueste
        bar_time ueber ALLE gewaehlten Datenquellen gesucht (OR-Semantik).
        """
        if not symbol or not timeframe:
            return None
        conditions = ["LOWER(symbol) = LOWER(?)", "LOWER(timeframe) = LOWER(?)"]
        params: List[Any] = [symbol, timeframe]
        self._apply_feature_filter(
            feature_ids, feature_id, conditions, params,
            instance_hashes=instance_hashes)
        con = self._get_connection()
        try:
            row = con.execute(f"""
                SELECT EXTRACT('epoch' FROM MAX(bar_time))::BIGINT
                FROM feature_store
                WHERE {' AND '.join(conditions)}
            """, params).fetchone()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_latest_bar_time "
                  f"fehlgeschlagen: {e}")
            return None
        if row and row[0] is not None:
            return int(row[0])
        return None

    def fetch_recent_bar_time_for_cell(
        self,
        symbol: str,
        timeframe: str,
        dow: int,
        hour: int,
        feature_id: Optional[str] = None,
        feature_ids: Optional[List[str]] = None,
        # Runde 10 (Bug 1): Varianten-Einschraenkung (optional).
        instance_hashes: Optional[List[str]] = None,
    ) -> Optional[int]:
        """Neuester Wanduhr-Epoch einer (dow, hour)-Heatmap-Zelle (oder None).

        Jump-to-Chart aus der Heatmap: Ein Doppelklick auf eine Zelle
        (Wochentag x Tagesstunde) oeffnet das Chart an der neuesten
        Feature-Bar dieser Zelle. DOW/HOUR werden mit
        `bar_time AT TIME ZONE 'UTC'` extrahiert (Wanduhr-Garantie,
        Invariante 7 – identisch zu fetch_heatmap).

        15.03-E (Multi-Select): Ueber `feature_ids` wird die Zelle ueber
        ALLE gewaehlten Datenquellen abgefragt (OR-Semantik).
        """
        if not symbol or not timeframe:
            return None
        try:
            dow = int(dow)
            hour = int(hour)
        except (TypeError, ValueError):
            return None
        if not (0 <= dow < DAYS_PER_WEEK and 0 <= hour < HOURS_PER_DAY):
            return None
        conditions = [
            "LOWER(symbol) = LOWER(?)",
            "LOWER(timeframe) = LOWER(?)",
            "EXTRACT(DOW FROM bar_time AT TIME ZONE 'UTC')::INTEGER = ?",
            "EXTRACT(HOUR FROM bar_time AT TIME ZONE 'UTC')::INTEGER = ?",
        ]
        params: List[Any] = [symbol, timeframe, dow, hour]
        self._apply_feature_filter(
            feature_ids, feature_id, conditions, params,
            instance_hashes=instance_hashes)
        con = self._get_connection()
        try:
            row = con.execute(f"""
                SELECT EXTRACT('epoch' FROM MAX(bar_time))::BIGINT
                FROM feature_store
                WHERE {' AND '.join(conditions)}
            """, params).fetchone()
        except Exception as e:
            print(f"WARN [FeatureStoreReader] fetch_recent_bar_time_for_cell "
                  f"fehlgeschlagen: {e}")
            return None
        if row and row[0] is not None:
            return int(row[0])
        return None
