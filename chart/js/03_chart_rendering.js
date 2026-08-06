// chart/js/03_chart_rendering.js
// Chart-Initialisierung (leer – chart wird via applyFullChartUpdate aus Python erstellt),
// Tages-Separatoren, Grid-Linien/Marker & Range-Steuerung

function clearGridLines() {
    if (!candleSeries) return;
    gridPriceLines.forEach(function(l) { try { candleSeries.removePriceLine(l); } catch(e){} });
    gridPriceLines = [];
}

// P16.03-Bugfix: Python-Linienart (lowercase: solid/dashed/dotted/dashdotted)
// auf LWC-v5-LineStyle mappen. 'dashdotted' -> LargeDashed (beste Naeherung).
function _lwcLineStyle(styleName) {
    switch ((styleName || 'solid').toLowerCase()) {
        case 'dashed': return LightweightCharts.LineStyle.Dashed;
        case 'dotted': return LightweightCharts.LineStyle.Dotted;
        case 'dashdotted': return LightweightCharts.LineStyle.LargeDashed;
        case 'solid':
        default: return LightweightCharts.LineStyle.Solid;
    }
}

function renderGridLines(lines) {
    clearGridLines();
    if (!candleSeries || !lines) return;
    var data = (typeof lines === 'string') ? JSON.parse(lines) : lines;
    (data || []).forEach(function(l) {
        if (l && typeof l.price === 'number' && !isNaN(l.price)) {
            var pl = candleSeries.createPriceLine({
                price: l.price, color: l.color, lineWidth: l.width,
                lineStyle: _lwcLineStyle(l.style), axisLabelVisible: true,
                title: l.is_custom ? '\u2605' : ''
            });
            gridPriceLines.push(pl);
        }
    });
}

// NOTE: Die Proximity-Circles werden auf der ZUGEHOERIGEN LIQ-LINE geplottet:
// Je Level-Preis wird eine UNSICHTBARE LineSeries erzeugt (lineVisible:false,
// autoscaleInfoProvider:null, rechte Preisskala), deren Datenpunkte exakt auf
// dem Level-Preis liegen. Die Circle-Marker (Standard-Marker der Engine, shape
// 'circle') haengen an dieser Serie -> die Engine positioniert sie direkt auf
// der Liq-Line. Das folgt Zoom/Scroll/Resize nativ (kein CSS-Overlay, kein
// Redraw-Bug).
function clearGridCircles() {
    for (var i = 0; i < _circleSeries.length; i++) {
        try { chart.removeSeries(_circleSeries[i]); } catch(e) {}
    }
    _circleSeries = [];
    _circleMarkerPlugins = [];
    _circleLevelSeries = {};
}

// P14-03-E (Flacker-Fix): renderGridCircles() ist jetzt INKREMENTELL. Bestehende
// Level-Serien werden per setData/setMarkers in-place aktualisiert; nur ver-
// schwundene Level werden entfernt, nur neue erzeugt. Kein removeSeries/addSeries
// für unveränderte Level => kein Full-Layer-Rebuild pro Live-Tick (bisher rief
// jede applyLiveOverlays renderGridCircles -> clearGridCircles auf, das ALLE
// Circle-Serien wegwarf und neu aufbaute = Flackern bei erfüllter Proximity).
function renderGridCircles(circles) {
    if (!chart || !circles) return;
    var data = (typeof circles === 'string') ? JSON.parse(circles) : circles;
    if (!data || data.length === 0) {
        clearGridCircles();
        return;
    }

    // Nach Level-Preis gruppieren: LWC-Serien brauchen eindeutige Zeiten,
    // daher je Level eine Serie (im selben Level gibt es max. 1 Treffer/Bar).
    var byLevel = {};
    for (var i = 0; i < data.length; i++) {
        var c = data[i];
        if (!c || typeof c.time !== 'number' || isNaN(c.time) ||
            typeof c.price !== 'number' || isNaN(c.price)) continue;
        var key = String(c.price);
        if (!byLevel[key]) byLevel[key] = [];
        byLevel[key].push(c);
    }

    // 1) Level entfernen, die im neuen Satz nicht mehr existieren – OHNE den
    //    Rest anzutasten.
    for (var oldKey in _circleLevelSeries) {
        if (!byLevel[oldKey]) {
            var gone = _circleLevelSeries[oldKey];
            try { if (gone.series) chart.removeSeries(gone.series); } catch(e) {}
            var gidx = _circleSeries.indexOf(gone.series);
            if (gidx >= 0) _circleSeries.splice(gidx, 1);
            if (gone.plugin) {
                var pidx = _circleMarkerPlugins.indexOf(gone.plugin);
                if (pidx >= 0) _circleMarkerPlugins.splice(pidx, 1);
            }
            delete _circleLevelSeries[oldKey];
        }
    }

    // 2) Upsert pro Level: existierende Serie in-place aktualisieren.
    var keys = Object.keys(byLevel);
    for (var j = 0; j < keys.length; j++) {
        var levelCircles = byLevel[keys[j]];
        // LWC v5: Markers und Serie brauchen NACH ZEIT SORTIERTE Daten.
        levelCircles.sort(function(a, b) { return a.time - b.time; });

        var sd = [];
        var markers = [];
        for (var k = 0; k < levelCircles.length; k++) {
            var cc = levelCircles[k];
            // Datenpunkt exakt auf dem Level-Preis -> Marker der Engine
            // erscheint auf der zugehoerigen Liq-Line.
            sd.push({ time: cc.time, value: cc.price });
            markers.push({
                time: cc.time,
                position: 'inBar',
                color: cc.color || '#E91E63',
                // P16.03-Bugfix: Form/Groesse aus dem Python-Payload uebernehmen
                // (vorher hart 'circle'/1) - die Auswahl im StylePickerWidget
                // (circle/square/arrowUp/arrowDown) wirkt damit endlich.
                shape: cc.shape || 'circle',
                size: (cc.size && cc.size > 0) ? cc.size : 1,
                priority: 10
            });
        }

        var key = keys[j];
        var existing = _circleLevelSeries[key];
        if (existing) {
            // Inkrementell: Serie/Plugin existiert bereits -> nur Daten ersetzen
            // (kein removeSeries/addSeries -> kein Flackern).
            try { existing.series.setData(sd); } catch(e) { continue; }
            if (existing.plugin) {
                try { existing.plugin.setMarkers(markers); } catch(e) { continue; }
            }
        } else {
            var series = null;
            try {
                series = chart.addSeries(LightweightCharts.LineSeries, {
                    lineVisible: false,
                    pointMarkersVisible: false,
                    lastValueVisible: false,
                    priceLineVisible: false,
                    crosshairMarkerVisible: false,
                    color: 'rgba(0,0,0,0)',
                    priceScaleId: 'right',
                    autoscaleInfoProvider: function() { return null; }
                });
            } catch(e) { continue; }

            var plugin = null;
            try {
                plugin = LightweightCharts.createSeriesMarkers(series, []);
            } catch(e) { plugin = null; }

            _circleLevelSeries[key] = { series: series, plugin: plugin };
            _circleSeries.push(series);
            if (plugin) _circleMarkerPlugins.push(plugin);

            try { series.setData(sd); } catch(e) { continue; }
            if (plugin) {
                try { plugin.setMarkers(markers); } catch(e) {}
            }
        }
    }
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

// =============================================================================
// Tages-Separatoren – GEKAPSELTES MODUL (DaySeparator)
// -----------------------------------------------------------------------------
// API:
//   DaySeparator.render(candleData)   – Trennlinien aus Candle-Daten berechnen
//                                       und als CSS-Overlay zeichnen (0:00 der
//                                       ersten Kerze des neuen Tages)
//   DaySeparator.updatePositions()    – Positionen nach Scroll/Zoom/Resize neu
//                                       berechnen (rein additiv, keine Änderung
//                                       der Zeitskala)
//   DaySeparator.clear()              – alle Trennlinien entfernen
//
// Warum gekapselt: Zukünftige Chart-Änderungen (linke Preisskala, Pane-Layout,
// Zeitachse) berühren nur dieses Modul – der Rest des Codes kennt nur die API.
//
// Früher: LineSeries mit 2 Extrem-Punkten (-1000/1000000). Bei LWC v5 rendert
// eine fast senkrechte 2-Punkt-Linie den Dash NICHT zuverlässig (fällt auf
// Solid zurück – deshalb war die Linie "durchgezogen").
// Heute: rein additives CSS-Overlay (border-left: dashed). Garantiert
// gestrichelt, keine Änderung der Zeitskala, keine Phantom-Index-Slots.
// =============================================================================
var DaySeparator = (function() {
    var container = null;      // Overlay-Div über dem Chart-Pane
    var times = [];            // kontinuierliche Zeiten der Trennlinien (0:00)
    var lines = [];            // erzeugte Div-Elemente

    // Breite einer eventuellen linken Preisskala (aktuell keine im Chart,
    // aber robust vorbereitet – C3)
    function _leftPriceWidth() {
        try {
            var leftPS = chart.priceScale('left');
            if (!leftPS) return 0;
            var opts = leftPS.options();
            if (opts && opts.visible) {
                return leftPS.width() || 0;
            }
        } catch(e) {}
        return 0;
    }

    function _ensureContainer() {
        var host = document.getElementById('chart-container');
        if (!host) return null;
        if (!container) {
            container = document.createElement('div');
            container.style.position = 'absolute';
            container.style.top = '0';
            container.style.left = '0';
            container.style.pointerEvents = 'none';
            container.style.zIndex = '100';
            host.appendChild(container);
        }
        return container;
    }

    function clear() {
        if (container) container.innerHTML = '';
        times = [];
        lines = [];
    }

    // Kernlogik: Tageswechsel-Erkennung (pure Funktion, separat testbar)
    function computeDaySeparatorTimes(candleData) {
        var result = [];
        if (!candleData || candleData.length === 0) return result;
        var lastLineTime = 0;
        for (var i = 1; i < candleData.length; i++) {
            var prevTime = candleData[i - 1].time;
            var currTime = candleData[i].time;

            // Echte epoch für Wanduhr-Tag-Berechnung verwenden (toReal statt
            // rohem Map-Zugriff -> nie Fake-Zeiten bei fehlendem Mapping).
            // Die Roh-Epochs sind bereits Berlin-Wanduhr-encoded, daher ergibt
            // Math.floor(real/SECONDS_PER_DAY) den Wanduhr-Tag (Wechsel 00:00).
            var prevReal = toReal(prevTime);
            var currReal = toReal(currTime);

            var prevUtcDay = Math.floor(prevReal / SECONDS_PER_DAY);
            var currUtcDay = Math.floor(currReal / SECONDS_PER_DAY);

            var isUtcDayChange = (currUtcDay !== prevUtcDay);
            var isWeekendGap = (currReal - prevReal > WEEKEND_GAP_SECONDS);
            var isTooCloseToPrevious = (lastLineTime > 0 && (currTime - lastLineTime) < MIN_SEPARATOR_SPACING_SECONDS);

            if ((isUtcDayChange || isWeekendGap) && !isTooCloseToPrevious) {
                lastLineTime = currTime;
                // 0:00 des neuen Tages = Zeit der ersten Kerze des neuen Tages
                result.push(currTime);
            }
        }
        return result;
    }

    function render(candleData) {
        if (!chart) return;
        clear();
        if (currentTfInSeconds >= SECONDS_PER_DAY || !candleData || candleData.length === 0) return;

        times = computeDaySeparatorTimes(candleData);

        var sepContainer = _ensureContainer();
        if (!sepContainer) return;
        for (var j = 0; j < times.length; j++) {
            var div = document.createElement('div');
            div.style.position = 'absolute';
            div.style.top = '0';
            div.style.bottom = '0';
            div.style.width = '0';
            div.style.borderLeft = '1px dashed rgba(33, 150, 243, 0.55)';
            div.style.pointerEvents = 'none';
            sepContainer.appendChild(div);
            lines.push(div);
        }
        updatePositions();
    }

    // Positionen nach Scroll/Zoom/Resize neu berechnen.
    // - x = timeToCoordinate (relativ zum Chart-Pane) + linke Preisskala-Breite
    // - Offscreen-Zeiten (null von timeToCoordinate) werden ausgeblendet (C4)
    function updatePositions() {
        if (!chart || !container) return;
        try {
            var host = document.getElementById('chart-container');
            var leftW = _leftPriceWidth();
            var width = host ? host.clientWidth : 800;
            var height = host ? host.clientHeight : 600;
            var tsHeight = 0;
            try { tsHeight = chart.timeScale().height() || 0; } catch(e) { tsHeight = 0; }

            container.style.left = leftW + 'px';
            container.style.top = '0px';
            container.style.width = Math.max(0, width - leftW) + 'px';
            container.style.height = Math.max(0, height - tsHeight) + 'px';

            for (var i = 0; i < times.length && i < lines.length; i++) {
                var x = null;
                try { x = chart.timeScale().timeToCoordinate(times[i]); } catch(e) { x = null; }
                if (x === null || x === undefined || isNaN(x)) {
                    lines[i].style.display = 'none';
                } else {
                    lines[i].style.display = 'block';
                    lines[i].style.left = (x + leftW) + 'px';
                }
            }
        } catch(e) {
            console.warn('[DaySeparator.updatePositions] Error:', e);
        }
    }

    return {
        render: render,
        updatePositions: updatePositions,
        clear: clear,
        computeDaySeparatorTimes: computeDaySeparatorTimes
    };
})();
