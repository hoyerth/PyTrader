// chart/js/04_live_updates.js
// Live-Tick-Updates, Countdown-Badge, Price-Badge, Range-Sync & Resize-Handling

function syncRanges() {
    if (!chart || !pyBridge || isUpdatingChart) return;
    try {
        var lr = chart.timeScale().getVisibleLogicalRange();
        if (lr && lr.from !== null && lr.to !== null && !isNaN(lr.from) && !isNaN(lr.to)) {
            pyBridge.onRangeChanged(Math.floor(lr.from), Math.floor(lr.to));
        }
        var pr = chart.priceScale('right').getVisibleRange();
        if (pr && pr.from !== null && pr.to !== null && !isNaN(pr.from) && !isNaN(pr.to)) {
            pyBridge.onPriceRangeChanged(pr.from, pr.to);
        }
    } catch(e) {}
}

function updateCountdownDisplay() {
    if (isUpdatingChart || !candleSeries || !chart || lastClosePrice === null || lastClosePrice === undefined) return;
    if (!isWindowActive || document.hidden) return;

    try {
        var priceBadge = document.getElementById('price-badge');
        var countdownBadge = document.getElementById('countdown-badge');
        if (!priceBadge || !countdownBadge) return;

        var showCountdown = (currentTfInSeconds > 0 && currentTfInSeconds < 86400);

        // PriceLine auf der candleSeries
        if (!currentPriceLine) {
            currentPriceLine = candleSeries.createPriceLine({
                price: lastClosePrice,
                color: '#2962FF',
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dotted,
                axisLabelVisible: false,
                title: ''
            });
            lastRenderedPrice = lastClosePrice;
        } else if (lastRenderedPrice !== lastClosePrice) {
            currentPriceLine.applyOptions({ price: lastClosePrice, title: '' });
            lastRenderedPrice = lastClosePrice;
        }

        var y = candleSeries.priceToCoordinate(lastClosePrice);
        if (y !== null && !isNaN(y)) {
            var formattedPrice = lastClosePrice.toFixed(currentPrecision);
            var topPos = (y - 9) + 'px';

            if (lastFormattedPriceStr !== formattedPrice) {
                priceBadge.innerText = formattedPrice;
                lastFormattedPriceStr = formattedPrice;
            }
            if (lastRenderedTop !== topPos) {
                priceBadge.style.top = topPos;
                countdownBadge.style.top = topPos;
                lastRenderedTop = topPos;
            }
            if (priceBadge.style.display !== 'block') {
                priceBadge.style.display = 'block';
            }

            if (showCountdown) {
                var now = Math.floor(Date.now() / 1000);
                var rem = currentTfInSeconds - (now % currentTfInSeconds);
                var formattedTime = String(Math.floor(rem/60)).padStart(2,'0') + ':' + String(rem%60).padStart(2,'0');
                if (lastFormattedTimeStr !== formattedTime) {
                    countdownBadge.innerText = formattedTime;
                    lastFormattedTimeStr = formattedTime;
                }
                var priceWidth = priceBadge.offsetWidth || 50;
                var rightPos = (priceWidth + 8) + 'px';
                if (countdownBadge.style.right !== rightPos) {
                    countdownBadge.style.right = rightPos;
                }
                if (countdownBadge.style.display !== 'block') {
                    countdownBadge.style.display = 'block';
                }
            } else {
                if (countdownBadge.style.display !== 'none') countdownBadge.style.display = 'none';
            }
        } else {
            if (priceBadge.style.display !== 'none') priceBadge.style.display = 'none';
            if (countdownBadge.style.display !== 'none') countdownBadge.style.display = 'none';
        }
    } catch(e) {
        var p = document.getElementById('price-badge');
        var c = document.getElementById('countdown-badge');
        if (p && p.style.display !== 'none') p.style.display = 'none';
        if (c && c.style.display !== 'none') c.style.display = 'none';
    }
}

function updateLiveCandle(json) {
    if (!candleSeries || isUpdatingChart) return;
    try {
        var c = JSON.parse(json);
        if (!c || typeof c.time !== 'number' || isNaN(c.time)) return;
        // Race-Guard: Live-Tick nur anwenden, wenn Symbol/TF noch zum Chart passen.
        // Verhindert, dass ein verspaeteter Tick vom alten Symbol/TF nach einem
        // schnellen Wechsel an den falschen Chart angehaengt wird.
        if (c.symbol !== undefined && c.symbol !== null && c.symbol !== currentSymbol) return;
        if (c.timeframe !== undefined && c.timeframe !== null && c.timeframe !== currentTimeframe) return;
        if (c.open === null || c.high === null || c.low === null || c.close === null) return;
        if (rawCandleData.length > 0 && c.time < rawCandleData[rawCandleData.length-1].time) return;
        candleSeries.update(c);
        lastClosePrice = c.close;
        updateCountdownDisplay();
    } catch(e) {}
}

function fitChartContent() { if(chart) chart.timeScale().fitContent(); }

// =============================================================================
// RESIZE-HANDLING
// =============================================================================
function handleResize() {
    if (!chart) return;
    var container = document.getElementById('chart-container');
    if (!container) return;
    var w = container.clientWidth;
    var h = container.clientHeight;
    if (w > 0 && h > 0) {
        chart.resize(w, h);
        try { _updateDaySeparatorPositions(); } catch(e) {}
    }
}

var _resizeObserver = null;
function setupResizeObserver() {
    var container = document.getElementById('chart-container');
    if (!container) return;
    if (_resizeObserver) _resizeObserver.disconnect();
    _resizeObserver = new ResizeObserver(function() { handleResize(); });
    _resizeObserver.observe(container);
}

// =============================================================================
// applyFullChartUpdate – Hauptfunktion
// =============================================================================
function applyFullChartUpdate(data) {
    // =========================================================================
    // RACE-GUARD: Python sendet eine monotone updateId mit jedem Refresh.
    // Veraltete Payloads (z. B. langsamer Serializer-Thread aus einem frueheren
    // Symbol/TF-Stand) werden sofort verworfen, bevor sie den Chart anfassen.
    // =========================================================================
    var myId = ++_updateId;
    var updateId = (data && typeof data.updateId === 'number') ? data.updateId : myId;

    if (updateId < _lastAppliedUpdateId) {
        console.warn('[applyFullChartUpdate] Veraltetes Update verworfen (id=' + updateId + ' < letzte=' + _lastAppliedUpdateId + ')');
        isUpdatingChart = false;
        return;
    }
    _lastAppliedUpdateId = updateId;

    try {
        isUpdatingChart = true;

        // TimeMap speichern (kontinuierliche Zeit -> echte epoch)
        _continuousTimeMap = data.timeMap || {};
        // Sortierte Schluessel fuer resolveRealTime() (naechster Zeitpunkt)
        _continuousKeys = Object.keys(_continuousTimeMap).map(Number).sort(function(a, b) { return a - b; });

        currentSymbol = data.symbol;
        currentTimeframe = data.timeframe;
        if (data.timeframe && TF_SECONDS_MAP[data.timeframe]) {
            currentTfInSeconds = TF_SECONDS_MAP[data.timeframe];
        }

        var candles = (typeof data.candles === 'string') ? JSON.parse(data.candles) : (data.candles || []);

        var validCandles = candles.filter(function(c) {
            return c &&
                typeof c.time === 'number' && !isNaN(c.time) && c.time > 0 &&
                typeof c.open === 'number' && !isNaN(c.open) && c.open > 0 &&
                typeof c.high === 'number' && !isNaN(c.high) && c.high > 0 &&
                typeof c.low === 'number' && !isNaN(c.low) && c.low > 0 &&
                typeof c.close === 'number' && !isNaN(c.close) && c.close > 0;
        });

        if (validCandles.length === 0) {
            console.warn('[applyFullChartUpdate] Keine gueltigen Candles');
            if (chart) chart.timeScale().fitContent();
            isUpdatingChart = false;
            return;
        }

        // Alte Resourcen entfernen
        try { clearGridCircles(); } catch(e) {}
        try { clearGridLines(); } catch(e) {}
        try { clearSignalMarkers(); } catch(e) {}
        if (currentPriceLine) {
            try { if (candleSeries) candleSeries.removePriceLine(currentPriceLine); } catch(e) {}
            currentPriceLine = null;
        }
        if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }

        if (_resizeObserver) {
            try { _resizeObserver.disconnect(); } catch(e) {}
            _resizeObserver = null;
        }

        try {
            if (chart) chart.remove();
        } catch(e) {
            console.warn('[applyFullChartUpdate] chart.remove() fehlgeschlagen:', e.message || e);
        }
        chart = null;
        candleSeries = null;
        dayLinesSeries = [];
        gridPriceLines = [];
        _storedCircleMarkers = null;
        seriesMarkersPlugin = null;
        try { _clearDaySeparatorOverlay(); } catch(e) {}

        var container = document.getElementById('chart-container');
        if (!container) {
            isUpdatingChart = false;
            return;
        }
        try { container.querySelectorAll('table, canvas').forEach(function(el) { el.remove(); }); } catch(e) {}

        var isDailyOrHigher = (currentTfInSeconds >= 86400);

        // Schritt 1: Chart erstellen
        try {
            chart = LightweightCharts.createChart(container, {
                width: container.clientWidth || 800,
                height: container.clientHeight || 600,
                layout: { background: { type: 'solid', color: '#131722' }, textColor: '#d1d4dc' },
                grid: { vertLines: { visible: false }, horzLines: { visible: false } },
                crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
                rightPriceScale: { borderColor: '#2B2B43' },
                timeScale: { 
                    borderColor: '#2B2B43', 
                    timeVisible: !isDailyOrHigher,
                    secondsVisible: false,
                    fixRightEdge: false,
                    fixLeftEdge: false,
                    shiftVisibleRangeOnNewBar: false,
                    tickMarkFormatter: function(time, tickMarkType) {
                        // time ist kontinuierlich (Fake-Zeit). Real-Epoch aus Map holen
                        // (resolveRealTime statt raw-Map-Zugriff -> kein Fake-Label).
                        var realTime = resolveRealTime(time);
                        var p = getBerlinParts(realTime);
                        if (isDailyOrHigher || tickMarkType <= 2) {
                            return p.day + '.' + p.month + '.' + p.year.slice(-2);
                        }
                        return p.hour + ':' + p.minute;
                    }
                },
                localization: { locale: 'de-DE', timeFormatter: function(t) { 
                    // t ist bei Zeit-basierten Serien ein UTCTimestamp (Zahl),
                    // NICHT ein Objekt mit .time – sonst laeuft formatDT ins Leere.
                    var ts = (t !== null && typeof t === 'object') ? t.time : t;
                    return formatDT(resolveRealTime(ts)); 
                } }
            });
        } catch(e) {
            console.error('[applyFullChartUpdate] Schritt 1 (createChart) fehlgeschlagen:', e.message || e);
            isUpdatingChart = false;
            return;
        }

        try { setupResizeObserver(); } catch(e) {}

        var precision = (data.precision !== undefined && data.precision !== null) ? data.precision : currentPrecision;
        currentPrecision = precision;
        var minMove = (typeof precision === 'number' && precision > 0 && precision < 10) 
            ? 1 / Math.pow(10, precision) 
            : 0.01;

        // Schritt 2: CandlestickSeries
        try {
            candleSeries = chart.addSeries(LightweightCharts.CandlestickSeries, {
                upColor: '#26a69a', downColor: '#ef5350', borderVisible: false,
                wickUpColor: '#26a69a', wickDownColor: '#ef5350', priceLineVisible: false, lastValueVisible: false,
                priceFormat: { type: 'price', precision: precision, minMove: minMove }
            });
            if (!candleSeries) throw new Error('candleSeries ist null');
        } catch(e) {
            console.error('[applyFullChartUpdate] Schritt 2 (addSeries) fehlgeschlagen:', e.message || e);
            isUpdatingChart = false;
            return;
        }

        // Schritt 3: setData
        try {
            candleSeries.setData(validCandles);
        } catch(e) {
            console.error('[applyFullChartUpdate] Schritt 3 (setData) fehlgeschlagen:', e.message || e);
            isUpdatingChart = false;
            return;
        }
        rawCandleData = validCandles;
        lastClosePrice = validCandles[validCandles.length - 1].close;

        // Schritt 4: TimeScale Subscription
        try {
            chart.timeScale().subscribeVisibleLogicalRangeChange(function() { 
                if(!isUpdatingChart) {
                    try { syncRanges(); } catch(e) {}
                    try { updateCountdownDisplay(); } catch(e) {}
                    try { _updateDaySeparatorPositions(); } catch(e) {}
                }
            });
        } catch(e) {
            console.warn('[applyFullChartUpdate] Schritt 4 (subscribe) fehlgeschlagen:', e.message || e);
        }

        // Countdown-Timer (1s Intervall)
        if (countdownTimer) clearInterval(countdownTimer);
        countdownTimer = setInterval(function() {
            try { updateCountdownDisplay(); } catch(e) {}
        }, 1000);

        // Schritt 5: Grid-Linien
        try { if (data.gridLines) renderGridLines(data.gridLines); } catch(e) {
            console.warn('[applyFullChartUpdate] Schritt 5 (gridLines) fehlgeschlagen:', e.message || e);
        }

        // Schritt 6: Grid-Circles (speichert nur, Marker setzen via setMarkers)
        try { if (data.gridCircles) renderGridCircles(data.gridCircles); } catch(e) {
            console.warn('[applyFullChartUpdate] Schritt 6 (gridCircles) fehlgeschlagen:', e.message || e);
        }

        // Schritt 7: Signal-Marker + Circles (combined via candleSeries.setMarkers)
        try {
            _storedSignalMarkersData = data.signalMarkers || [];
            _applyAllMarkers(_storedSignalMarkersData);
        } catch(e) {
            console.warn('[applyFullChartUpdate] Schritt 7 (signalMarkers) fehlgeschlagen:', e.message || e);
        }

        // Schritt 8: Range
        try {
            if (data.rangeFrom !== undefined && data.rangeTo !== undefined &&
                data.rangeFrom !== null && data.rangeTo !== null &&
                data.rangeFrom !== data.rangeTo) {
                pendingRange = { rangeFrom: data.rangeFrom, rangeTo: data.rangeTo, priceFrom: data.priceFrom, priceTo: data.priceTo };
                applyRange(data.rangeFrom, data.rangeTo, data.priceFrom, data.priceTo);
            } else {
                if (chart) chart.timeScale().fitContent();
            }
        } catch(e) {
            console.warn('[applyFullChartUpdate] Schritt 8 (applyRange) fehlgeschlagen:', e.message || e);
        }

        // Schritt 9: Day Separators
        try { updateDaySeparators(rawCandleData); } catch(e) {
            console.warn('[applyFullChartUpdate] Schritt 9 (daySeparators) fehlgeschlagen:', e.message || e);
        }

        // Fertig – isUpdatingChart freigeben + initialen sync
        isUpdatingChart = false;
        try { syncRanges(); } catch(e) {}
        try { updateCountdownDisplay(); } catch(e) {}

    } catch(e) {
        console.error('[applyFullChartUpdate] GLOBAL Error:', e.message || e);
        isUpdatingChart = false;
    }
}
