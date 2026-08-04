(() => {
  const TARGET_POLL_MS = 10_000;
  const CANDLE_POLL_MS = 20_000;
  const BOUNDARY_PAD_MS = 3_000;

  const el = {
    chart: document.getElementById("chart"),
    targetValue: document.getElementById("target-value"),
    targetMeta: document.getElementById("target-meta"),
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

  function formatWindow(closeIso) {
    if (!closeIso) return "";
    try {
      const d = new Date(closeIso);
      return (
        d.toLocaleString(undefined, {
          hour: "numeric",
          minute: "2-digit",
          hour12: true,
        }) + " close"
      );
    } catch {
      return closeIso;
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
      color: "#1ac96b",
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
      if (!data.ok && data.target == null) {
        setStatus("warn", data.error || "Kalshi error");
        el.targetValue.textContent = "—";
        el.targetMeta.textContent = data.error || "Unavailable";
        return;
      }

      if (data.target == null) {
        setStatus("warn", "Target TBD");
        el.targetValue.textContent = "TBD";
        el.targetMeta.textContent = data.error || "Waiting for next window";
        applyTargetLine(null);
      } else {
        const rolled = lastTicker && data.ticker && lastTicker !== data.ticker;
        lastTicker = data.ticker;
        setStatus("ok", rolled ? "New 15m target" : "Live");
        el.targetValue.textContent = money(data.target);
        const bits = [];
        const win = formatWindow(data.close_time);
        if (win) bits.push(win);
        if (data.ticker) bits.push(data.ticker);
        el.targetMeta.textContent = bits.join(" · ");
        applyTargetLine(data.target, "TARGET");
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
      series.setData(data.candles || []);
      if (lastTarget != null) applyTargetLine(lastTarget, "TARGET");
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
