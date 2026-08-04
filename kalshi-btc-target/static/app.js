(() => {
  const TARGET_POLL_MS = 10_000;
  const CANDLE_POLL_MS = 20_000;
  const BOUNDARY_PAD_MS = 3_000;

  const el = {
    chart: document.getElementById("chart"),
    targetLabel: document.getElementById("target-label"),
    targetValue: document.getElementById("target-value"),
    targetMeta: document.getElementById("target-meta"),
    spotValue: document.getElementById("spot-value"),
    spotDelta: document.getElementById("spot-delta"),
    status: document.getElementById("status"),
    clock: document.getElementById("clock"),
  };

  /** @type {import('lightweight-charts').IChartApi | null} */
  let chart = null;
  /** @type {import('lightweight-charts').ISeriesApi<'Candlestick'> | null} */
  let series = null;
  /** @type {ReturnType<import('lightweight-charts').ISeriesApi<'Candlestick'>['createPriceLine']> | null} */
  let targetLine = null;
  let lastTicker = null;
  let lastTarget = null;
  let boundaryTimer = null;

  function money(n) {
    if (n == null || !Number.isFinite(n)) return "—";
    return n.toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function setStatus(state, text) {
    el.status.dataset.state = state;
    el.status.textContent = text;
  }

  function formatWindow(closeIso, closeEt) {
    if (closeEt) return closeEt;
    if (!closeIso) return "";
    try {
      return new Date(closeIso).toLocaleString("en-US", {
        timeZone: "America/New_York",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
        timeZoneName: "short",
      });
    } catch {
      return closeIso;
    }
  }

  function updateSpot(lastClose) {
    if (!el.spotValue) return;
    if (lastClose == null || !Number.isFinite(lastClose)) {
      el.spotValue.textContent = "—";
      el.spotDelta.textContent = "";
      el.spotDelta.className = "spot-delta";
      return;
    }
    el.spotValue.textContent = money(lastClose);
    if (lastTarget != null && Number.isFinite(lastTarget)) {
      const delta = lastClose - lastTarget;
      const sign = delta >= 0 ? "+" : "-";
      el.spotDelta.textContent = `${sign}$${Math.abs(delta).toFixed(2)}`;
      el.spotDelta.className = "spot-delta " + (delta >= 0 ? "up" : "down");
    } else {
      el.spotDelta.textContent = "";
      el.spotDelta.className = "spot-delta";
    }
  }

  function scheduleBoundaryRefresh(closeIso) {
    if (boundaryTimer) {
      clearTimeout(boundaryTimer);
      boundaryTimer = null;
    }
    if (!closeIso) return;
    const closeMs = Date.parse(closeIso);
    if (!Number.isFinite(closeMs)) return;
    const wait = Math.max(5_000, closeMs + BOUNDARY_PAD_MS - Date.now());
    boundaryTimer = setTimeout(() => {
      refreshTarget();
      refreshCandles();
    }, wait);
  }

  function ensureChart() {
    if (chart || !window.LightweightCharts) return;
    const { createChart, CrosshairMode, LineStyle } = window.LightweightCharts;
    chart = createChart(el.chart, {
      layout: {
        background: { color: "#121c18" },
        textColor: "#8fa399",
        fontFamily: 'IBM Plex Sans, Segoe UI, sans-serif',
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      timeScale: {
        borderColor: "rgba(255,255,255,0.08)",
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: { vertTouchDrag: false },
    });
    series = chart.addCandlestickSeries({
      upColor: "#1ac96b",
      downColor: "#d45454",
      borderVisible: false,
      wickUpColor: "#1ac96b",
      wickDownColor: "#d45454",
    });
    // stash for applyOptions
    ensureChart.LineStyle = LineStyle;
    resizeChart();
  }

  function resizeChart() {
    if (!chart) return;
    const rect = el.chart.getBoundingClientRect();
    chart.applyOptions({
      width: Math.max(280, Math.floor(rect.width)),
      height: Math.max(280, Math.floor(rect.height)),
    });
  }

  function applyTargetLine(target, title) {
    lastTarget = target;
    if (!series || target == null || !Number.isFinite(target)) {
      if (targetLine && series) {
        series.removePriceLine(targetLine);
        targetLine = null;
      }
      return;
    }
    const opts = {
      price: target,
      color: "#ffffff",
      lineWidth: 2,
      lineStyle: (ensureChart.LineStyle && ensureChart.LineStyle.Dashed) || 2,
      axisLabelVisible: true,
      title: title || "TARGET",
    };
    if (!targetLine) {
      targetLine = series.createPriceLine(opts);
    } else {
      targetLine.applyOptions(opts);
    }
  }

  async function refreshTarget() {
    try {
      const res = await fetch("/api/target", { cache: "no-store" });
      const data = await res.json();
      const beat = data.price_to_beat ?? data.target;
      if (el.targetLabel) {
        el.targetLabel.textContent = data.label || "Price to beat";
      }
      if (!data.ok && beat == null) {
        setStatus("warn", data.error || "Kalshi error");
        el.targetValue.textContent = "—";
        el.targetMeta.textContent = data.error || "Unavailable";
        return;
      }

      if (beat == null) {
        setStatus("warn", "Price to beat TBD");
        el.targetValue.textContent = "TBD";
        el.targetMeta.textContent = data.error || "Waiting for next 15m window";
        applyTargetLine(null);
        updateSpot(null);
      } else {
        const rolled = lastTicker && data.ticker && lastTicker !== data.ticker;
        lastTicker = data.ticker;
        setStatus("ok", rolled ? "New 15m price to beat" : "Live · KXBTC15M");
        el.targetValue.textContent = money(beat);
        const win = formatWindow(data.close_time, data.close_et);
        el.targetMeta.textContent = win
          ? `Kalshi 15m · settles ${win}`
          : "Kalshi 15m";
        applyTargetLine(beat, "TARGET");
        // refresh delta if we already have a spot
        if (el.spotValue && el.spotValue.dataset.last) {
          updateSpot(Number(el.spotValue.dataset.last));
        }
      }
      scheduleBoundaryRefresh(data.close_time);
    } catch (err) {
      setStatus("warn", "Target fetch failed");
      el.targetMeta.textContent = String(err.message || err);
    }
  }

  async function refreshCandles() {
    try {
      const res = await fetch("/api/candles?granularity=60&limit=300", {
        cache: "no-store",
      });
      const data = await res.json();
      if (!data.ok) {
        setStatus("warn", data.error || "Candles error");
        return;
      }
      ensureChart();
      if (!series) return;
      const candles = data.candles || [];
      series.setData(candles);
      if (lastTarget != null) applyTargetLine(lastTarget, "TARGET");
      const last = candles.length ? candles[candles.length - 1].close : null;
      if (el.spotValue && last != null) el.spotValue.dataset.last = String(last);
      updateSpot(last);
      chart.timeScale().scrollToRealTime();
    } catch (err) {
      setStatus("warn", "Candle fetch failed");
    }
  }

  function tickClock() {
    el.clock.textContent = new Date().toLocaleTimeString();
  }

  function boot() {
    if (!window.LightweightCharts) {
      setStatus("warn", "Chart library failed to load");
      return;
    }
    ensureChart();
    resizeChart();
    refreshCandles().then(refreshTarget);
    setInterval(refreshTarget, TARGET_POLL_MS);
    setInterval(refreshCandles, CANDLE_POLL_MS);
    setInterval(tickClock, 1000);
    tickClock();
    window.addEventListener("resize", resizeChart);
    window.addEventListener("orientationchange", () => setTimeout(resizeChart, 250));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    // lightweight-charts is deferred; wait a tick for it
    window.addEventListener("load", boot);
  }
})();
