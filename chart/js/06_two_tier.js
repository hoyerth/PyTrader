// chart/js/06_two_tier.js
// Phase 16.07 – Two-Tier Caching & Dynamic Range Management (JS-Tier)
//
// D1/D3/D4/D5/D7/D8/D9/D10 – Sliding Window auf der JS-Seite:
//   * Tier-1-Fenster N = 1000 (initial + Chunk-Grösse), linke Kante wird
//     beim Scrollen dynamisch erweitert (kein Full-Chart-Rebuild).
//   * Trigger (D7): < 100 verbleibende Kerzen links im Canvas -> Request an
//     Python (pyBridge.onRequestOlderData), debounced mit 300 ms.
//   * Antwort (D4): applyOlderDataChunk(payload) mit updateId (Request-Serial,
//     Race-Guard), candles (Prepend), timeMapDelta, chartRenderPayloadDelta,
//     windowRightEpoch (Sliding-Window-Kante), hasMoreHistory (D8).
//   * Die Candles werden vorne angehängt (setData, KEIN chart.remove()/
//     createChart), die logische Range um +k verschoben -> Viewport bleibt
//     stabil (kein Sprung).
//   * Linien/Marker (D5): Python sendet das VOLLSTÄNDIG neu berechnete
//     Render-Payload für das aktuelle Fenster; JS ersetzt per renderLineSeries
//     / renderMarkers (bestehende inkrementelle Serien-Registry, kein
//     Full-Layer-Rebuild).
//   * Live-Ticks (D9): Befindet sich der Viewport nicht am rechten Rand
//     (_atLiveEdge == false), wird updateLiveCandle() in 04_live_updates.js
//     unterdrückt (stummer Tier-2-Update); ein dezenter „Live"-Button springt
//     bei Klick ans Live-Ende (Python-Full-Refresh via onJumpToLive).
//   * D10: syncRanges liefert zusätzlich die Gesamt-Kerzenzahl, damit Python
//     den Viewport offsetbasiert (Abstand vom rechten Rand) persistieren kann.
//
// Dieses Modul wird NACH 04_live_updates.js geladen (chart_basics.JS_FILES)
// und hängt sich über optionale Hooks in 04 ein:
//   window._onFullChartUpdateApplied(data) – State-Reset nach Full-Update
//   window._onVisibleRangeChanged()        – Range-Änderung (Live-Detektion +
//                                            Nachlade-Trigger)
//   window._isHistoryView()                – Live-Tick-Suppression (D9)

// =============================================================================
// Konstanten (D1/D7)
// =============================================================================
const TIER1_WINDOW = 1000;        // N: Tier-1-Fenster-/Chunk-Grösse (D1)
const LEFT_EDGE_THRESHOLD = 100;  // D7: < 100 verbleibende Kerzen im Canvas
const OLDER_REQUEST_DEBOUNCE_MS = 300; // D7: JS-Debounce

// =============================================================================
// Zustand (durch applyFullChartUpdate via Hook zurückgesetzt)
// =============================================================================
let _hasMoreHistory = true;       // D8: Stop-Flag (kein Endlos-Loop)
let _atLiveEdge = true;           // D9: Viewport am rechten Rand (Live)
let _requestSerial = 0;           // monoton steigendes Request-Serial (D4)
let _pendingRequestSerial = 0;    // letztes an Python gesendetes Serial
let _olderRequestTimer = null;    // JS-Debounce-Timer (D7)

// =============================================================================
// Live-Button (D9) – dezenter Overlay-Button, nur in der Historie sichtbar
// =============================================================================
function _updateLiveButton() {
    var btn = document.getElementById('live-button');
    if (!btn) return;
    btn.style.display = _atLiveEdge ? 'none' : 'block';
}

var _liveButtonEl = document.getElementById('live-button');
if (_liveButtonEl) {
    _liveButtonEl.addEventListener('click', function() {
        try {
            if (pyBridge && pyBridge.onJumpToLive) pyBridge.onJumpToLive();
        } catch(e) {}
    });
}

// =============================================================================
// Hook: Full-Update angewendet (04_live_updates.js ruft optional auf)
// =============================================================================
function _onFullChartUpdateApplied(data) {
    _hasMoreHistory = (data && data.hasMoreHistory !== false);
    _atLiveEdge = true;
    _requestSerial = 0;
    _pendingRequestSerial = 0;
    if (_olderRequestTimer) { clearTimeout(_olderRequestTimer); _olderRequestTimer = null; }
    _updateLiveButton();
}

// =============================================================================
// Hook: sichtbare logische Range geändert (04_live_updates.js ruft optional auf)
// =============================================================================
function _onVisibleRangeChanged() {
    try {
        var lr = chart.timeScale().getVisibleLogicalRange();
        if (lr && lr.from !== null && lr.to !== null && !isNaN(lr.from) && !isNaN(lr.to)) {
            // D9: Live-Ende, wenn die rechte Viewport-Kante nahe dem Datenende liegt.
            _atLiveEdge = (rawCandleData.length > 0 && lr.to >= rawCandleData.length - 5);
            _updateLiveButton();
        }
    } catch(e) {}
    _maybeRequestOlderData();
}

// =============================================================================
// D7: Nachlade-Trigger (debounced, < 100 Kerzen links im Canvas)
// =============================================================================
function _maybeRequestOlderData() {
    if (!pyBridge || !chart || !rawCandleData || rawCandleData.length === 0) return;
    if (!_hasMoreHistory) return;   // D8: Stop-Flag
    if (isUpdatingChart) return;
    try {
        var lr = chart.timeScale().getVisibleLogicalRange();
        if (!lr || lr.from === null || isNaN(lr.from)) return;
        if (lr.from > LEFT_EDGE_THRESHOLD) return;

        var leftReal = toReal(rawCandleData[0].time);
        var rightReal = toReal(rawCandleData[rawCandleData.length - 1].time);

        // Debounce (300 ms): nur der letzte Request innerhalb des Fensters.
        if (_olderRequestTimer) clearTimeout(_olderRequestTimer);
        _pendingRequestSerial = ++_requestSerial;
        var serial = _pendingRequestSerial;
        var fromEpoch = leftReal;
        var count = TIER1_WINDOW;
        var winRight = rightReal;
        _olderRequestTimer = setTimeout(function() {
            _olderRequestTimer = null;
            try {
                if (pyBridge && pyBridge.onRequestOlderData) {
                    pyBridge.onRequestOlderData(fromEpoch, count, serial, winRight);
                }
            } catch(e) {}
        }, OLDER_REQUEST_DEBOUNCE_MS);
    } catch(e) {}
}

// =============================================================================
// D4: Chunk-Antwort aus Python – inkrementelles Prepend (Sliding Window)
// =============================================================================
function applyOlderDataChunk(payload) {
    if (!payload || typeof payload !== 'object') return;
    // Race-Guard 1 (D4): nur der NEUESTE Request wird angewendet (doppelte
    // Requests bei schnellem Scrollen / verspätete Antworten).
    if (typeof payload.updateId === 'number' && payload.updateId !== _pendingRequestSerial) {
        console.warn('[TwoTier] Veraltete Chunk-Antwort verworfen (id=' + payload.updateId + ' != ' + _pendingRequestSerial + ')');
        return;
    }
    // Race-Guard 2: Chunk aus einem früheren Symbol/TF-Stand verwerfen.
    if (payload.symbol !== undefined && payload.symbol !== null && payload.symbol !== currentSymbol) return;
    if (payload.timeframe !== undefined && payload.timeframe !== null && payload.timeframe !== currentTimeframe) return;

    var newCandles = payload.candles || [];
    var k = newCandles.length;
    _hasMoreHistory = (payload.hasMoreHistory !== false);  // D8
    if (k === 0) {
        // Keine ältere Geschichte mehr (DB-Ende) – Stop-Flag gesetzt.
        return;
    }

    try {
        // Aktuelle logische Range VOR dem Prepend merken (Viewport-Stabilität).
        var lr = null;
        try { lr = chart.timeScale().getVisibleLogicalRange(); } catch(e) {}

        // TimeMap erweitern: nur NEUE Einträge (bestehende cont-Zeiten bleiben
        // unverändert, daher bleibt der Chart-Zeitstrahl konsistent).
        var delta = payload.timeMapDelta || {};
        for (var key in delta) {
            if (Object.prototype.hasOwnProperty.call(delta, key)) {
                var cKey = Number(key);
                _continuousTimeMap[cKey] = delta[key];
                _realToContMap[delta[key]] = cKey;
            }
        }
        _continuousKeys = Object.keys(_continuousTimeMap).map(Number).sort(function(a, b) { return a - b; });

        // Candles vorne anhängen (aufsteigend, kontinuierliche Zeit).
        rawCandleData = newCandles.concat(rawCandleData);

        // Sliding Window (D2): Rechte Kante ggf. kürzen, falls der Tier-2-
        // Puffer nach links geschoben wurde (windowRightEpoch < bisheriges
        // Fenster-Ende). Sonst bleibt das Live-Ende erhalten.
        if (payload.windowRightEpoch && payload.windowRightEpoch > 0) {
            var rightCont = toCont(payload.windowRightEpoch);
            if (rightCont !== undefined && rawCandleData.length) {
                var lastCont = rawCandleData[rawCandleData.length - 1].time;
                if (lastCont > rightCont) {
                    var keepIdx = 0;
                    for (var i = 0; i < rawCandleData.length; i++) {
                        if (rawCandleData[i].time <= rightCont) keepIdx = i + 1;
                    }
                    var dropped = rawCandleData.slice(keepIdx);
                    rawCandleData = rawCandleData.slice(0, keepIdx);
                    for (var d = 0; d < dropped.length; d++) {
                        var dCont = dropped[d].time;
                        var dReal = _continuousTimeMap[dCont];
                        if (dReal !== undefined) {
                            delete _continuousTimeMap[dCont];
                            delete _realToContMap[dReal];
                        }
                    }
                    _continuousKeys = Object.keys(_continuousTimeMap).map(Number).sort(function(a, b) { return a - b; });
                }
            }
        }

        // Candle-Serie ersetzen – KEIN chart.remove()/createChart (kein Sprung).
        candleSeries.setData(rawCandleData);

        // D5: Render-Delta anwenden – Python sendet das VOLLSTÄNDIG neu
        // berechnete Fenster-Payload; JS ersetzt Linien/Marker nahtlos über
        // die bestehenden inkrementellen Serien-Registrys.
        // 22.01i (Bugfix "Value is null"): Wie applyChartRenderPayload werden
        // Overlay-Punkte ausserhalb des Kerzenbereichs VOR dem Rendering
        // verworfen. Der Chunk-Pfad hatte diesen Guard bisher NICHT – Punkte
        // mit ungemappten Roh-Epochs (bar_time nicht in der Zeit-Map) konnten
        // als riesige Zeiten (~1.7e9) zwischen kont-Zeiten landen; LWC crasht
        // dann in PlotList._bsearch mit "Value is null" (unsortierte Daten).
        var rp = payload.chartRenderPayloadDelta || {};
        var _cb = _overlayTimeBounds();
        if (_cb) {
            if (Array.isArray(rp.lines)) {
                var _keptLines = [];
                for (var _li = 0; _li < rp.lines.length; _li++) {
                    var _line = rp.lines[_li];
                    if (!_line || !Array.isArray(_line.data)) continue;
                    _line.data = _line.data.filter(function(pt) {
                        return pt && typeof pt.time === 'number' &&
                            pt.time >= _cb.min && pt.time <= _cb.max;
                    });
                    if (_line.data.length > 0) _keptLines.push(_line);
                }
                rp.lines = _keptLines;
            }
            if (Array.isArray(rp.hit_circles)) {
                rp.hit_circles = rp.hit_circles.filter(function(c) {
                    return c && typeof c.time === 'number' &&
                        c.time >= _cb.min && c.time <= _cb.max;
                });
            }
        }
        if (rp.lines) {
            try { renderLineSeries(rp.lines); } catch(e) {
                console.warn('[TwoTier] lines fehlgeschlagen:', e.message || e);
            }
        }
        if (rp.hit_circles) {
            _gridCirclesCache = rp.hit_circles.slice();
            _lastLiveCirclesJson = '[]';
            try { renderMarkers(_gridCirclesCache); } catch(e) {
                console.warn('[TwoTier] hit_circles fehlgeschlagen:', e.message || e);
            }
        }

        // DaySeparator neu berechnen (Tagesgrenzen im vorderen Bereich).
        try { DaySeparator.render(rawCandleData); } catch(e) {}

        // Viewport stabil halten: logische Range um k nach rechts verschieben
        // (die bestehenden Kerzen sind durch das Prepend um k Indizes gerutscht).
        if (lr && lr.from !== null && lr.to !== null && !isNaN(lr.from) && !isNaN(lr.to)) {
            var newFrom = lr.from + k;
            var newTo = lr.to + k;
            if (newTo > rawCandleData.length - 1) newTo = rawCandleData.length - 1;
            if (newFrom > newTo) newFrom = newTo;
            if (newFrom < 0) newFrom = 0;
            try { chart.timeScale().setVisibleLogicalRange({ from: newFrom, to: newTo }); } catch(e) {}
        }

        // Nun in der Historie (nicht am Live-Ende) – D9: Ticks stumm.
        _atLiveEdge = false;
        _updateLiveButton();

        try { syncRanges(); } catch(e) {}
    } catch(e) {
        console.error('[TwoTier] applyOlderDataChunk Error:', e.message || e);
    }
}

// =============================================================================
// D9: Live-Tick-Suppression – 04_live_updates.js fragt optional ab
// =============================================================================
function _isHistoryView() {
    return _atLiveEdge === false;
}
