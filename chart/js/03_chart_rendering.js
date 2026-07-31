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

// NOTE: _storedSignalMarkersData/_storedCircleMarkers sind getrennte Layer.
// _applyAllMarkers() kombiniert BEIDE Caches und setzt sie via setMarkers –
// damit kann ein Grid-Render die Signal-Marker nie verdrängen und umgekehrt.
function clearGridCircles() {
    _storedCircleMarkers = [];
    _applyAllMarkers();
}

function renderGridCircles(circles) {
    if (!candleSeries || !circles) return;
    var data = (typeof circles === 'string') ? JSON.parse(circles) : circles;
    _storedCircleMarkers = data || [];
    // Circles werden via _applyAllMarkers() mit den Signal-Markern kombiniert
    _applyAllMarkers();
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
// _storedSignalMarkersData/_storedCircleMarkers sind IMMER Arrays (nie null),
// damit _applyAllMarkers() beide Layer zuverlässig kombinieren kann.
var _storedSignalMarkersData = [];

function clearSignalMarkers() {
    // Nur das Signal-Layer leeren – Circles bleiben aus dem Cache erhalten.
    // (Im Chart-Refresh wird das Plugin anschliessend ohnehin neu aufgebaut.)
    _storedSignalMarkersData = [];
    _applyAllMarkers();
}

function renderSignalMarkers(markers) {
    var data = (typeof markers === 'string') ? JSON.parse(markers) : markers;
    // Cache IMMER aktualisieren (auch bei leerer Liste) – verhindert, dass
    // ein veralteter Cache nach dem Ausschalten der Signale wieder auftaucht.
    _storedSignalMarkersData = data || [];
    _applyAllMarkers();
}

function _applyAllMarkers() {
    if (!candleSeries) return;
    try {
        var allMarkers = [];

        // 1. Signal-Marker (aus dem Signal-Cache)
        if (_storedSignalMarkersData && _storedSignalMarkersData.length > 0) {
            for (var i = 0; i < _storedSignalMarkersData.length; i++) {
                var m = _storedSignalMarkersData[i];
                allMarkers.push({
                    time: m.time,
                    position: m.position || 'aboveBar',
                    color: m.color || '#26a69a',
                    shape: m.shape || 'arrowDown',
                    size: (m.size !== undefined) ? m.size : 1,
                    text: m.text || '',
                    // priority steuert die Stapel-Reihenfolge bei gleicher Kerze
                    // (niedriger = näher an der Kerze, höher = weiter oben).
                    // Wird von der LWC-Engine ignoriert (explizite Feldliste) –
                    // dient NUR unserer Sortierung.
                    priority: (m.priority !== undefined && m.priority !== null) ? m.priority : 0
                });
            }
        }

        // 2. Circle-Marker (aus dem Grid-Cache)
        if (_storedCircleMarkers && _storedCircleMarkers.length > 0) {
            for (var j = 0; j < _storedCircleMarkers.length; j++) {
                var c = _storedCircleMarkers[j];
                allMarkers.push({
                    time: c.time,
                    position: 'inBar',
                    color: c.color || '#FFEB3B',
                    shape: 'circle',
                    size: 1,
                    priority: (c.priority !== undefined && c.priority !== null) ? c.priority : 10
                });
            }
        }

        // LWC v5: candleSeries.setMarkers() wurde entfernt → SeriesMarkers-Plugin nutzen.
        // Das Plugin wird pro Chart-Instanz einmalig erzeugt (Reset in applyFullChartUpdate).
        // WICHTIG (v5.2.0-Engine): setMarkers() erwartet ein NACH ZEIT SORTIERTES Array:
        //  - Die interne Suche nach dem sichtbaren Bereich ist eine Binärsuche (unsortiert = falsche Grenzen).
        //  - Mehrere Marker DERSELBEN Kerze werden nur vertikal gestapelt, wenn sie im Array
        //    BENACHBART sind (Stack-Offset resettet bei jedem Zeitsprung). Unsortiert überdecken
        //    sich Marker derselben Kerze exakt – Grid-Circles verdeckten so die EMA-Signale.
        // Sortierung (stabil seit ES2019):
        //   1. Kriterium: Zeit (Pflicht für die Engine).
        //   2. Kriterium: priority (Stapel-Reihenfolge bei gleicher Kerze).
        //      Niedrige priority = näher an der Kerze, hohe = weiter oben.
        //      Gleiche priority => Einfüge-Reihenfolge bleibt erhalten (Signale vor Circles).
        allMarkers.sort(function(a, b) {
            if (a.time !== b.time) return a.time - b.time;
            var pa = (typeof a.priority === 'number') ? a.priority : 0;
            var pb = (typeof b.priority === 'number') ? b.priority : 0;
            return pa - pb;
        });

        if (!seriesMarkersPlugin) {
            seriesMarkersPlugin = LightweightCharts.createSeriesMarkers(candleSeries, []);
        }
        seriesMarkersPlugin.setMarkers(allMarkers);
    } catch(e) {
        console.error('[setMarkers] Error:', e.message || e);
    }
}

function reapplySignalMarkers() {
    _applyAllMarkers();
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
