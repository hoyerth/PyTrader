// chart/js/03_chart_rendering.js
// Chart-Initialisierung (leer – chart wird via applyFullChartUpdate aus Python erstellt),
// Tages-Separatoren, Grid-Linien/Marker & Range-Steuerung

function clearGridLines() {
    if (!candleSeries) return;
    gridPriceLines.forEach(function(l) { try { candleSeries.removePriceLine(l); } catch(e){} });
    gridPriceLines = [];
}

function renderGridLines(lines) {
    clearGridLines();
    if (!candleSeries || !lines) return;
    var data = (typeof lines === 'string') ? JSON.parse(lines) : lines;
    (data || []).forEach(function(l) {
        if (l && typeof l.price === 'number' && !isNaN(l.price)) {
            var pl = candleSeries.createPriceLine({
                price: l.price, color: l.color, lineWidth: l.width,
                lineStyle: LightweightCharts.LineStyle.Solid, axisLabelVisible: true,
                title: l.is_custom ? '\u2605' : ''
            });
            gridPriceLines.push(pl);
        }
    });
}

function clearGridCircles() {
    _storedCircleMarkers = null;
}

function renderGridCircles(circles) {
    clearGridCircles();
    if (!candleSeries || !circles) return;
    var data = (typeof circles === 'string') ? JSON.parse(circles) : circles;
    if (!data || data.length === 0) return;
    _storedCircleMarkers = data;
    // Circles werden via _applyAllMarkers() auf candleSeries gesetzt
    _applyAllMarkers(_storedSignalMarkersData);
}

function applyRange(rangeFrom, rangeTo, priceFrom, priceTo) {
    if (!chart) return;
    var timeScale = chart.timeScale();
    var priceScale = chart.priceScale('right');

    if (rangeFrom && rangeTo && rangeFrom !== rangeTo) {
        try {
            timeScale.setVisibleLogicalRange({ from: Number(rangeFrom), to: Number(rangeTo) });
        } catch(e) {
            console.warn("[applyRange] Failed to set logical range:", e);
            try { timeScale.fitContent(); } catch(e2) {}
        }
    } else {
        try { timeScale.fitContent(); } catch(e) {}
    }

    if (priceFrom !== undefined && priceTo !== undefined && priceFrom !== priceTo) {
        try { priceScale.setVisibleRange({ from: Number(priceFrom), to: Number(priceTo) }); } catch(e) {}
    }
}

// Signal-Marker + Circles: combined auf candleSeries.setMarkers()
var _storedSignalMarkersData = null;

function clearSignalMarkers() {
    _storedSignalMarkersData = null;
    if (seriesMarkersPlugin) {
        try { seriesMarkersPlugin.setMarkers([]); } catch(e) {}
    }
}

function renderSignalMarkers(markers) {
    var data = (typeof markers === 'string') ? JSON.parse(markers) : markers;
    if (data && data.length > 0) {
        _storedSignalMarkersData = data;
    }
    _applyAllMarkers(data || []);
}

function _applyAllMarkers(signalMarkers) {
    if (!candleSeries) return;
    try {
        var allMarkers = [];

        // 1. Signal-Marker
        if (signalMarkers && signalMarkers.length > 0) {
            for (var i = 0; i < signalMarkers.length; i++) {
                var m = signalMarkers[i];
                allMarkers.push({
                    time: m.time,
                    position: m.position || 'aboveBar',
                    color: m.color || '#26a69a',
                    shape: m.shape || 'arrowDown',
                    size: (m.size !== undefined) ? m.size : 1,
                    text: m.text || ''
                });
            }
        }

        // 2. Circle-Marker
        if (_storedCircleMarkers && _storedCircleMarkers.length > 0) {
            for (var j = 0; j < _storedCircleMarkers.length; j++) {
                var c = _storedCircleMarkers[j];
                allMarkers.push({
                    time: c.time,
                    position: 'inBar',
                    color: c.color || '#FFEB3B',
                    shape: 'circle',
                    size: 1,
                });
            }
        }

        // LWC v5: candleSeries.setMarkers() wurde entfernt → SeriesMarkers-Plugin nutzen.
        // Das Plugin wird pro Chart-Instanz einmalig erzeugt (Reset in applyFullChartUpdate).
        if (!seriesMarkersPlugin) {
            seriesMarkersPlugin = LightweightCharts.createSeriesMarkers(candleSeries, []);
        }
        seriesMarkersPlugin.setMarkers(allMarkers);
    } catch(e) {
        console.error('[setMarkers] Error:', e.message || e);
    }
}

function reapplySignalMarkers() {
    _applyAllMarkers(_storedSignalMarkersData);
}

// =============================================================================
// Tages-Separatoren
// -----------------------------------------------------------------------------
// Früher: LineSeries mit 2 Extrem-Punkten (-1000/1000000). Bei LWC v5 rendert
// eine fast senkrechte 2-Punkt-Linie den Dash NICHT zuverlässig (fällt auf
// Solid zurück – deshalb war die Linie "durchgezogen").
// Heute: rein additives CSS-Overlay (border-left: dashed). Garantiert
// gestrichelt, keine Änderung der Zeitskala, keine Phantom-Index-Slots.
// =============================================================================
var daySeparatorContainer = null;
var _storedDaySeparatorTimes = [];

function _ensureDaySeparatorContainer() {
    var container = document.getElementById('chart-container');
    if (!container) return null;
    if (!daySeparatorContainer) {
        daySeparatorContainer = document.createElement('div');
        daySeparatorContainer.style.position = 'absolute';
        daySeparatorContainer.style.top = '0';
        daySeparatorContainer.style.left = '0';
        daySeparatorContainer.style.pointerEvents = 'none';
        daySeparatorContainer.style.zIndex = '100';
        container.appendChild(daySeparatorContainer);
    }
    return daySeparatorContainer;
}

function _clearDaySeparatorOverlay() {
    if (daySeparatorContainer) {
        daySeparatorContainer.innerHTML = '';
    }
    _storedDaySeparatorTimes = [];
}

function _updateDaySeparatorPositions() {
    if (!chart || !daySeparatorContainer) return;
    try {
        var container = document.getElementById('chart-container');
        var top = 0;
        var width = container ? container.clientWidth : 800;
        var height = container ? container.clientHeight : 600;
        // Pane-Höhe = Container-Höhe minus Zeitachsen-Höhe (Zeitachse liegt unten)
        var tsHeight = 0;
        try { tsHeight = chart.timeScale().height() || 0; } catch(e) { tsHeight = 0; }
        height = Math.max(0, height - tsHeight);

        daySeparatorContainer.style.top = top + 'px';
        daySeparatorContainer.style.left = '0px';
        daySeparatorContainer.style.width = width + 'px';
        daySeparatorContainer.style.height = height + 'px';

        var children = daySeparatorContainer.children;
        for (var i = 0; i < _storedDaySeparatorTimes.length && i < children.length; i++) {
            var x = null;
            try { x = chart.timeScale().timeToCoordinate(_storedDaySeparatorTimes[i]); } catch(e) { x = null; }
            if (x === null || x === undefined || isNaN(x)) {
                children[i].style.display = 'none';
            } else {
                children[i].style.display = 'block';
                // pane.left ist hier 0 (keine linke Preisskala). Falls jemals
                // eine linke Preisskala ergänzt wird: (x - pane.left) verwenden.
                children[i].style.left = x + 'px';
            }
        }
    } catch(e) {
        console.warn("[_updateDaySeparatorPositions] Error:", e);
    }
}

function updateDaySeparators(candleData) {
    if (!chart) return;
    try {
        // Alte Separator-Serien (Legacy) entfernen + Overlay leeren
        dayLinesSeries.forEach(function(s) { try { chart.removeSeries(s); } catch(e){} });
        dayLinesSeries = [];
        _clearDaySeparatorOverlay();
        if (currentTfInSeconds >= 86400 || !candleData || candleData.length === 0) return;

        var lastLineTime = 0;

        for (var i = 1; i < candleData.length; i++) {
            var prevTime = candleData[i - 1].time;
            var currTime = candleData[i].time;

            // Echte epoch für Wanduhr-Tag-Berechnung verwenden (resolveRealTime
            // statt rohem Map-Zugriff -> nie Fake-Zeiten bei fehlendem Mapping).
            // Die Roh-Epochs sind bereits Berlin-Wanduhr-encoded, daher ergibt
            // Math.floor(real/86400) den Wanduhr-Tag (Wechsel um 00:00 Berlin).
            var prevReal = resolveRealTime(prevTime);
            var currReal = resolveRealTime(currTime);

            var prevUtcDay = Math.floor(prevReal / 86400);
            var currUtcDay = Math.floor(currReal / 86400);

            var isUtcDayChange = (currUtcDay !== prevUtcDay);
            var isWeekendGap = (currReal - prevReal > 43200);
            var isTooCloseToPrevious = (lastLineTime > 0 && (currTime - lastLineTime) < 21600);

            if ((isUtcDayChange || isWeekendGap) && !isTooCloseToPrevious) {
                lastLineTime = currTime;
                // 0:00 des neuen Tages = Zeit der ersten Kerze des neuen Tages
                _storedDaySeparatorTimes.push(currTime);
            }
        }

        // CSS-Overlay-Divs anlegen (garantiert gestrichelt via border-left)
        var sepContainer = _ensureDaySeparatorContainer();
        if (!sepContainer) return;
        for (var j = 0; j < _storedDaySeparatorTimes.length; j++) {
            var div = document.createElement('div');
            div.style.position = 'absolute';
            div.style.top = '0';
            div.style.bottom = '0';
            div.style.width = '0';
            div.style.borderLeft = '1px dashed rgba(33, 150, 243, 0.55)';
            div.style.pointerEvents = 'none';
            sepContainer.appendChild(div);
        }
        _updateDaySeparatorPositions();
    } catch(e) {
        console.error("[updateDaySeparators] Error:", e);
    }
}
