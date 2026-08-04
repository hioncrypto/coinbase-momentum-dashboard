(() => {
  const TARGET_POLL_MS = 5_000;
  const CANDLE_POLL_MS = 15_000;
  const SPOT_POLL_MS = 2_000;
  const BOUNDARY_PAD_MS = 2_000;
  const TF_KEY = "kalshiChartTf";

  const TF_LABELS = {
    "1m": "1m candles",
    "5m": "5m candles",
    "15m": "15m candles",
  };

  const el = {
    chart: document.getElementById("chart"),
    timeframe: document.getElementById("timeframe"),
    chartTfLabel: document.getElementById("chart-tf-label"),
    targetLabel: document.getElementById("target-label"),
    targetValue: document.getElementById("target-value"),
    targetMeta: document.getElementById("target-meta"),
    spotValue: document.getElementById("spot-value"),
    spotDelta: document.getElementById("spot-delta"),
    countdown: document.getElementById("countdown"),
    countdownMeta: document.getElementById("countdown-meta"),
    status: document.getElementById("status"),
    clock: document.getElementById("clock"),
  };

  let chart = null;
  let series = null;
  let targetLine = null;
  let lastTicker = null;
  let lastTarget = null;
  let closeTimeIso = null;
  let boundaryTimer = null;
  let fittedOnce = false;
  let prevSpot = null;
  let currentTf = localStorage.getItem(TF_KEY) || "15m";
  if (!["1m", "5m", "15m"].includes(currentTf)) currentTf = "15m";

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

  function setTfLabel() {
    if (el.chartTfLabel) {
      el.chartTfLabel.textContent = `Chart · ${TF_LABELS[currentTf] || currentTf}`;
    }
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
    el.spotValue.dataset.last = String(lastClose);

    if (prevSpot != null && Number.isFinite(prevSpot)) {
      if (lastClose > prevSpot) el.spotValue.style.color = "#1ac96b";
      else if (lastClose < prevSpot) el.spotValue.style.color = "#d45454";
    }
    prevSpot = lastClose;

    if (lastTarget != null && Number.isFinite(lastTarget)) {
      const delta = lastClose - lastTarget;
      const sign = delta >= 0 ? "+" : "-";
      el.spotDelta.textContent = `${sign}$${Math.abs(delta).toFixed(2)} vs beat`;
      el.spotDelta.className = "spot-delta " + (delta >= 0 ? "up" : "down");
    } else {
      el.spotDelta.textContent = "";
      el.spotDelta.className = "spot-delta";
    }
  }

  function updateCountdown() {
    if (!el.countdown) return;
    if (!closeTimeIso) {
      el.countdown.textContent = "—:—";
      el.countdown.classList.remove("urgent");
      if (el.countdownMeta) el.countdownMeta.textContent = `Until ${currentTf} window ends`;
      return;
    }
    const end = Date.parse(closeTimeIso);
    if (!Number.isFinite(end)) {
      el.countdown.textContent = "—:—";
      return;
    }
    let ms = end - Date.now();
    if (ms <= 0) {
      el.countdown.textContent = "0:00";
      el.countdown.classList.add("urgent");
      if (el.countdownMeta) el.countdownMeta.textContent = "Window rolling…";
      return;
    }
    const totalSec = Math.floor(ms / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    el.countdown.textContent = `${m}:${String(s).padStart(2, "0")}`;
    el.countdown.classList.toggle("urgent", totalSec <= 60);
    if (el.countdownMeta) {
      el.countdownMeta.textContent =
        totalSec <= 60 ? "Under 1 minute left" : `Until ${currentTf} window ends`;
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
    const wait = Math.max(3_000, closeMs + BOUNDARY_PAD_MS - Date.now());
    boundaryTimer = setTimeout(() => {
      refreshTarget();
      refreshCandles();
      refreshSpot();
    }, wait);
  }

  function ensureChart() {
    if (chart || !window.LightweightCharts) return;
    const { createChart, CrosshairMode, LineStyle } = window.LightweightCharts;
    chart = createChart(el.chart, {
      layout: {
        background: { color: "#121c18" },
        textColor: "#8fa399",
        fontFamily: "IBM Plex Sans, Segoe UI, sans-serif",
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
    ensureChart.LineStyle = LineStyle;
    resizeChart();
  }

  function resizeChart() {
    if (!chart) return;
    const rect = el.chart.getBoundingClientRect();
    chart.applyOptions({
      width: Math.max(280, Math.floor(rect.width)),
      height: Math.max(320, Math.floor(rect.height)),
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
    if (!targetLine) targetLine = series.createPriceLine(opts);
    else targetLine.applyOptions(opts);
  }

  async function refreshTarget() {
    try {
      const res = await fetch(
        `/api/target?tf=${encodeURIComponent(currentTf)}`,
        { cache: "no-store" }
      );
      const data = await res.json();
      const beat = data.price_to_beat ?? data.target;
      closeTimeIso = data.close_time || null;
      updateCountdown();
      if (el.targetLabel) el.targetLabel.textContent = data.label || "Price to beat";

      if (!data.ok && beat == null) {
        setStatus("warn", data.error || "Kalshi error");
        el.targetValue.textContent = "—";
        el.targetMeta.textContent = data.error || "Unavailable";
        return;
      }

      if (beat == null) {
        setStatus("warn", "Price to beat TBD");
        el.targetValue.textContent = "TBD";
        el.targetMeta.textContent = data.error || `Waiting for ${currentTf} window`;
        applyTargetLine(null);
      } else {
        const rolled = lastTicker && data.ticker && lastTicker !== data.ticker;
        lastTicker = data.ticker;
        setStatus(
          "ok",
          data.stale_previous
            ? "Rolling…"
            : rolled
              ? `New ${currentTf} price to beat`
              : `Live · ${currentTf}`
        );
        el.targetValue.textContent = money(beat);
        const win = formatWindow(data.close_time, data.close_et);
        const src = data.source === "kalshi" ? "Kalshi" : "Window";
        el.targetMeta.textContent = win ? `${src} · settles ${win}` : src;
        applyTargetLine(beat, "TARGET");
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

  async function refreshSpot() {
    try {
      const res = await fetch("/api/spot", { cache: "no-store" });
      const data = await res.json();
      if (!data.ok || data.price == null) return;
      updateSpot(Number(data.price));
    } catch {
      // keep last spot
    }
  }

  async function refreshCandles() {
    try {
      const res = await fetch(`/api/candles?tf=${encodeURIComponent(currentTf)}`, {
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
      // Hard reset so timeframe switches are obvious
      series.setData([]);
      series.setData(candles);
      targetLine = null;
      if (lastTarget != null) applyTargetLine(lastTarget, "TARGET");
      if (!el.spotValue?.dataset.last && candles.length) {
        updateSpot(candles[candles.length - 1].close);
      }
      chart.timeScale().fitContent();
      fittedOnce = true;
    } catch (err) {
      setStatus("warn", "Candle fetch failed");
    }
  }

  function onTimeframeChange() {
    currentTf = el.timeframe.value;
    localStorage.setItem(TF_KEY, currentTf);
    fittedOnce = false;
    lastTicker = null;
    lastTarget = null;
    closeTimeIso = null;
    setTfLabel();
    setStatus("loading", `Loading ${currentTf}…`);
    if (el.countdownMeta) {
      el.countdownMeta.textContent = `Until ${currentTf} window ends`;
    }
    Promise.all([refreshCandles(), refreshTarget(), refreshSpot()]);
  }

  function tickClock() {
    el.clock.textContent = new Date().toLocaleTimeString();
    updateCountdown();
  }

  function boot() {
    if (!window.LightweightCharts) {
      setStatus("warn", "Chart library failed to load");
      return;
    }
    if (el.timeframe) {
      el.timeframe.value = currentTf;
      el.timeframe.addEventListener("change", onTimeframeChange);
    }
    setTfLabel();
    ensureChart();
    resizeChart();
    refreshCandles().then(refreshTarget).then(refreshSpot);
    setInterval(refreshTarget, TARGET_POLL_MS);
    setInterval(refreshCandles, CANDLE_POLL_MS);
    setInterval(refreshSpot, SPOT_POLL_MS);
    setInterval(tickClock, 250);
    tickClock();
    window.addEventListener("resize", resizeChart);
    window.addEventListener("orientationchange", () => setTimeout(resizeChart, 250));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    window.addEventListener("load", boot);
  }
})();
