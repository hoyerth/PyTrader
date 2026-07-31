// chart/js/05_measurement.js
// Messfunktion: Strg + linke Maustaste zieht eine Box auf,
// die Messwerte (Preisdiff, Zeitdiff, Start/Ende) werden live angezeigt.
// Die Box ist NUR eine temporaere Anzeige: Nach dem Loslassen bleibt sie
// stehen, verschwindet aber beim naechsten normalen Klick (linke Maustaste
// ohne Strg) auf den Chart. Escape loescht sie ebenfalls.//
// WICHTIG (Reintegration des alten Mess-Codes in die neue Modul-Struktur):
//  - Bedienung wie im alten Code: STRG + linke Maustaste (e.ctrlKey).
//  - Koordinaten-Umrechnung wie im alten Code: candleSeries.coordinateToPrice(y)
//    und candleSeries.priceToCoordinate(price). Der Weg über
//    chart.priceScale('right').coordinateToPrice() ist in LWC v5 NICHT
//    verfügbar (IPriceScaleApi hat nur applyOptions/options/width/
//    setVisibleRange/getVisibleRange/setAutoScale) – dadurch lieferte die
//    Umrechnung immer null (keine Messwerte, keine stehenbleibende Box).
//  - Zeitachse: chart.timeScale().coordinateToLogical(x)/logicalToCoordinate(l)
//    (vorhanden in v5).
//
// Design:
//  - Die Box wird als reines CSS-Overlay gezeichnet (#measurement-region +
//    #measurement-box) – konsistent zum DaySeparator-Modul und robust gegen
//    Chart-Rebuilds.
//  - Der Messzustand wird als logische Indizes + Preise gespeichert (nicht
//    als Pixel), damit die Box bei Scroll/Zoom/Resize folgt (updatePositions).
//  - Der Zustand geht an Python via pyBridge.onMeasurementChanged(JSON) und
//    wird beim nächsten Chart-Refresh wiederhergestellt (applyFullChartUpdate
//    -> Measurement.restore).
//  - Escape loescht die Messung (sendet '' an Python -> State = None).
//
// Koordinaten-Hinweis (LWC v5):
//  - timeScale().coordinateToLogical(x) / logicalToCoordinate(logical) arbeiten
//    relativ zur linken Pane-Kante. Da der Chart KEINE linke Preisskala hat,
//    ist Pane-X == Container-X.
//  - candleSeries.coordinateToPrice(y) / priceToCoordinate(price) arbeiten
//    relativ zur OBERKANTE des Pane (Zeitskala unten ausgenommen).
//    Das Pane beginnt oben bei Container-Y 0.
//  - Die Zeitskala unten wird beim Umrechnen ausgenommen (Pane-Bounds).
//
// Die internen Helfer (computeMeasurementData, formatDuration, formatMeasurementText,
// contTimeAtLogical) sind pure Funktionen und separat testbar.

var Measurement = (function() {

    // ---- Zustand ----------------------------------------------------------
    // state: { from: { logical, price }, to: { logical, price } } oder null
    var state = null;
    var dragging = false;
    var draft = null; // { x1, y1, x2, y2 } in Container-Pixeln (während Drag)

    // ---- kleine Helfer ----------------------------------------------------
    function _hide(el) { if (el && el.style.display !== 'none') el.style.display = 'none'; }
    function _show(el) { if (el && el.style.display !== 'block') el.style.display = 'block'; }
    function _round(x, decimals) {
        if (typeof x !== 'number' || !isFinite(x)) return x;
        var f = Math.pow(10, decimals);
        return Math.round(x * f) / f;
    }

    // ---- Pure Funktionen (testbar) ----------------------------------------

    // logischer Index (float) -> kontinuierliche Zeit (Interpolation über die
    // sortierten cont-Schlüssel; außerhalb des Datensatzes wird geclampt).
    function contTimeAtLogical(logical) {
        if (typeof logical !== 'number' || !isFinite(logical)) return null;
        if (!_continuousKeys || _continuousKeys.length === 0) return null;
        var last = _continuousKeys.length - 1;
        if (logical <= 0) return _continuousKeys[0];
        if (logical >= last) return _continuousKeys[last];
        var f = Math.floor(logical);
        var c = Math.ceil(logical);
        if (f === c) return _continuousKeys[f];
        return _continuousKeys[f] + (logical - f) * (_continuousKeys[c] - _continuousKeys[f]);
    }

    function computeMeasurementData(fromLogical, fromPrice, toLogical, toPrice) {
        var fromCont = contTimeAtLogical(fromLogical);
        var toCont = contTimeAtLogical(toLogical);
        var deltaPrice = toPrice - fromPrice;
        var pct = (fromPrice && fromPrice !== 0) ? (deltaPrice / fromPrice * 100) : 0;
        return {
            from: {
                logical: fromLogical,
                price: fromPrice,
                contTime: fromCont,
                realTime: (fromCont !== null) ? toReal(fromCont) : null
            },
            to: {
                logical: toLogical,
                price: toPrice,
                contTime: toCont,
                realTime: (toCont !== null) ? toReal(toCont) : null
            },
            deltaLogical: toLogical - fromLogical,
            deltaPrice: deltaPrice,
            pctChange: pct,
            candleCount: Math.round(Math.abs(toLogical - fromLogical)),
            durationSeconds: Math.abs(toLogical - fromLogical) * (currentTfInSeconds || 0)
        };
    }

    // Format Dauer als DD:HH:MM (Tage:Stunden:Minuten, jeweils 2-stellig) –
    // Sekunden werden NICHT angezeigt.
    function formatDuration(seconds) {
        seconds = Math.max(0, Math.round(seconds || 0));
        var d = Math.floor(seconds / SECONDS_PER_DAY);
        var h = Math.floor((seconds % SECONDS_PER_DAY) / 3600);
        var m = Math.floor((seconds % 3600) / 60);
        function p(n) { return String(n).padStart(2, '0'); }
        return p(d) + ':' + p(h) + ':' + p(m);
    }

    function formatMeasurementText(data) {
        var prec = currentPrecision;
        var dp = data.deltaPrice;
        var dpStr = (dp >= 0 ? '+' : '') + dp.toFixed(prec);
        var pctStr = (data.pctChange >= 0 ? '+' : '') + data.pctChange.toFixed(2) + '%';
        var fromT = (data.from.realTime !== null && data.from.realTime !== undefined) ? formatDT(data.from.realTime) : '--';
        var toT = (data.to.realTime !== null && data.to.realTime !== undefined) ? formatDT(data.to.realTime) : '--';
        var lines = [];
        // 1) Δ Preis: zuerst Prozentwert, die exakte Differenz in Klammern
        lines.push('Δ Preis: ' + pctStr + '  (' + dpStr + ')');
        // 2) Δ Zeit: Anzahl Bars + Dauer im Format DD:HH:MM (ohne Sekunden)
        lines.push('Δ Zeit:  ' + data.candleCount + ' Bars · ' + formatDuration(data.durationSeconds));
        // 3) Start/Ende: Preis (auf Symbol-Nachkommastellen begrenzt) + Zeit
        lines.push('Start:   ' + data.from.price.toFixed(prec) + '  ' + fromT);
        lines.push('Ende:    ' + data.to.price.toFixed(prec) + '  ' + toT);
        return lines.join('\n');
    }

    // ---- LWC-Koordinaten-Helfer ------------------------------------------

    function _paneBounds() {
        var host = document.getElementById('chart-container');
        var w = host ? host.clientWidth : 0;
        var h = host ? host.clientHeight : 0;
        var tsH = 0;
        try { tsH = chart.timeScale().height() || 0; } catch(e) { tsH = 0; }
        return { left: 0, top: 0, width: Math.max(0, w), height: Math.max(0, h - tsH) };
    }

    // Pixel -> logischer Index + Preis (y wird auf den Pane-Bereich geclampt,
    // damit Klicks in der Zeitskala unten nicht zu null führen).
    // WICHTIG: Preis-Umrechnung NUR über die Serie (ISeriesApi), wie im alten
    // Code – priceScale('right') kann das in LWC v5 NICHT (siehe Kopf).
    function _toLogicalPrice(x, y) {
        if (!chart || !candleSeries) return { logical: null, price: null };
        var bounds = _paneBounds();
        if (y < bounds.top) y = bounds.top;
        if (y > bounds.top + bounds.height) y = bounds.top + bounds.height;
        var logical = null, price = null;
        try { logical = chart.timeScale().coordinateToLogical(x); } catch(e) { logical = null; }
        try { price = candleSeries.coordinateToPrice(y); } catch(e) { price = null; }
        return { logical: logical, price: price };
    }

    function _toPixel(logical, price) {
        if (!chart || !candleSeries) return { x: 0, y: 0 };
        var x = 0, y = 0;
        try {
            var v = chart.timeScale().logicalToCoordinate(logical);
            if (v !== null && isFinite(v)) x = v;
        } catch(e) {}
        try {
            var v2 = candleSeries.priceToCoordinate(price);
            if (v2 !== null && isFinite(v2)) y = v2;
        } catch(e) {}
        return { x: x, y: y };
    }

    // ---- Rendering ---------------------------------------------------------

    function render() {
        var region = document.getElementById('measurement-region');
        var box = document.getElementById('measurement-box');
        if (!region || !box) return;
        if (!chart || !candleSeries || isUpdatingChart) { _hide(region); _hide(box); return; }

        var pts = null;
        if (dragging && draft) {
            pts = { x1: draft.x1, y1: draft.y1, x2: draft.x2, y2: draft.y2 };
        } else if (state) {
            var p1 = _toPixel(state.from.logical, state.from.price);
            var p2 = _toPixel(state.to.logical, state.to.price);
            pts = { x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y };
        }

        if (!pts) { _hide(region); _hide(box); return; }

        var left = Math.min(pts.x1, pts.x2);
        var top = Math.min(pts.y1, pts.y2);
        var width = Math.abs(pts.x2 - pts.x1);
        var height = Math.abs(pts.y2 - pts.y1);

        region.style.display = 'block';
        region.style.left = left + 'px';
        region.style.top = top + 'px';
        region.style.width = Math.max(width, 1) + 'px';
        region.style.height = Math.max(height, 1) + 'px';

        var fromLP = _toLogicalPrice(pts.x1, pts.y1);
        var toLP = _toLogicalPrice(pts.x2, pts.y2);
        if (fromLP.logical === null || fromLP.price === null || toLP.logical === null || toLP.price === null) {
            _hide(box);
            return;
        }
        var data = computeMeasurementData(fromLP.logical, fromLP.price, toLP.logical, toLP.price);
        var text = formatMeasurementText(data);
        if (box.innerText !== text) box.innerText = text;
        _show(box);

        // Info-Box neben dem Endpunkt (Mauszeiger) positionieren – wie im alten
        // Code, aber im Container geclampt, damit sie nie aus dem Chart läuft.
        var host = document.getElementById('chart-container');
        var hostW = host ? host.clientWidth : 0;
        var hostH = host ? host.clientHeight : 0;
        var boxW = box.offsetWidth || 200;
        var boxH = box.offsetHeight || 70;
        var bx = pts.x2 + 15;
        var by = pts.y2 + 15;
        if (bx + boxW > hostW) bx = Math.max(2, pts.x2 - boxW - 15);
        if (by + boxH > hostH) by = Math.max(2, pts.y2 - boxH - 15);
        box.style.left = bx + 'px';
        box.style.top = by + 'px';
    }

    // ---- Python-Sync --------------------------------------------------------

    function _syncToPython() {
        if (!pyBridge) return;
        try {
            var payload = '';
            if (state) {
                payload = JSON.stringify({
                    from: { logical: _round(state.from.logical, 4), price: state.from.price },
                    to: { logical: _round(state.to.logical, 4), price: state.to.price }
                });
            }
            pyBridge.onMeasurementChanged(payload);
        } catch(e) {
            console.warn('[Measurement] pyBridge sync fehlgeschlagen:', e.message || e);
        }
    }

    // ---- Event-Handler -------------------------------------------------------

    function _containerRect() {
        var host = document.getElementById('chart-container');
        return host ? host.getBoundingClientRect() : { left: 0, top: 0 };
    }

    function onMouseDown(e) {
        if (!chart || !candleSeries || isUpdatingChart) return;
        // Nur Strg + linke Maustaste startet eine Messung
        if (e.ctrlKey && e.button === 0) {
            e.preventDefault();
            e.stopPropagation();
            var rect = _containerRect();
            var x = e.clientX - rect.left;
            var y = e.clientY - rect.top;
            dragging = true;
            draft = { x1: x, y1: y, x2: x, y2: y };
            render();
            return;
        }
        // Temporäre Messanzeige: Ein normaler Klick (linke Maustaste ohne Strg)
        // auf den Chart schliesst die Messbox. Die Box selbst hat pointer-events:
        // none, daher landen alle Klicks auf dem Chart – die Messung ist damit
        // genau "bis zur nächsten Aktion" sichtbar. Strg-Klicks (neue Messung)
        // werden oben bereits behandelt.
        if (e.button === 0 && state) {
            state = null;
            draft = null;
            dragging = false;
            render();
            _syncToPython();
        }
    }

    function onMouseMove(e) {
        if (!dragging || !draft) return;
        e.preventDefault();
        var rect = _containerRect();
        draft.x2 = e.clientX - rect.left;
        draft.y2 = e.clientY - rect.top;
        render();
    }

    function onMouseUp(e) {
        if (!dragging) return;
        e.preventDefault();
        dragging = false;
        if (draft) {
            var fromLP = _toLogicalPrice(draft.x1, draft.y1);
            var toLP = _toLogicalPrice(draft.x2, draft.y2);
            if (fromLP.logical !== null && fromLP.price !== null && toLP.logical !== null && toLP.price !== null) {
                state = {
                    from: { logical: fromLP.logical, price: fromLP.price },
                    to: { logical: toLP.logical, price: toLP.price }
                };
            }
            draft = null;
        }
        render();
        _syncToPython();
    }

    function onKeyDown(e) {
        if (e.key === 'Escape' || e.keyCode === 27) {
            state = null;
            draft = null;
            dragging = false;
            render();
            _syncToPython();
        }
    }

    function _bind() {
        var host = document.getElementById('chart-container');
        if (!host) return;
        host.removeEventListener('mousedown', onMouseDown, true);
        host.addEventListener('mousedown', onMouseDown, true);
        window.removeEventListener('mousemove', onMouseMove);
        window.addEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
        window.addEventListener('mouseup', onMouseUp);
        window.removeEventListener('keydown', onKeyDown);
        window.addEventListener('keydown', onKeyDown);
    }

    // ---- Öffentliche API -----------------------------------------------------

    function restore(jsonState) {
        try {
            var s = (typeof jsonState === 'string') ? JSON.parse(jsonState) : jsonState;
            if (s && s.from && s.to &&
                typeof s.from.logical === 'number' && typeof s.from.price === 'number' &&
                typeof s.to.logical === 'number' && typeof s.to.price === 'number') {
                state = {
                    from: { logical: s.from.logical, price: s.from.price },
                    to: { logical: s.to.logical, price: s.to.price }
                };
            } else {
                state = null;
            }
        } catch(e) {
            state = null;
        }
        render();
    }

    function updatePositions() {
        // Bei Scroll/Zoom/Resize: Box neu aus logischen Koordinaten berechnen
        if (!state) return;
        if (!chart || !candleSeries || isUpdatingChart) return;
        render();
    }

    function clear() {
        state = null;
        draft = null;
        dragging = false;
        var region = document.getElementById('measurement-region');
        var box = document.getElementById('measurement-box');
        _hide(region);
        _hide(box);
    }

    function hasState() {
        return state !== null;
    }

    // Initial binden (DOM ist beim Skriptende bereits fertig – Skript steht am Body-Ende)
    try { _bind(); } catch(e) {}

    return {
        render: render,
        restore: restore,
        updatePositions: updatePositions,
        clear: clear,
        hasState: hasState,
        // pure Funktionen für Tests exportieren
        computeMeasurementData: computeMeasurementData,
        formatDuration: formatDuration,
        formatMeasurementText: formatMeasurementText,
        contTimeAtLogical: contTimeAtLogical,
        _state: function() { return state; },
        _setStateForTest: function(s) { state = s; },
        _syncToPython: _syncToPython
    };
})();
