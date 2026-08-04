(() => {
  const TARGET_POLL_MS = 2_000;
  const CANDLE_POLL_MS = 10_000;
  const SPOT_POLL_MS = 2_000;
  const BOUNDARY_PAD_MS = 500;
  const ROLLOVER_BURST_MS = 45_000;
  const ROLLOVER_TICK_MS = 1_000;
  const TF_KEY = "kalshiChartTf";
  const CHIME_KEY = "kalshiChimeEnabled";
  const BG_ARMED_KEY = "kalshiBgAlertsArmed";

  const TF_LABELS = {
    "1m": "1m BRTI",
    "5m": "5m BRTI",
    "15m": "15m BRTI",
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
    chimeEnabled: document.getElementById("chime-enabled"),
    chimeToggleLabel: document.getElementById("chime-toggle-label"),
    enableBg: document.getElementById("enable-bg"),
    bgStatus: document.getElementById("bg-status"),
    bgSetup: document.getElementById("bg-setup"),
    pushBadge: document.getElementById("push-badge"),
    oddsRow: document.getElementById("odds-row"),
    yesPct: document.getElementById("yes-pct"),
    noPct: document.getElementById("no-pct"),
  };

  let chart = null;
  let series = null;
  let targetLine = null;
  let lastTicker = null;
  let lastTarget = null;
  let lastFifteenTarget = null;
  let lastFifteenTicker = null;
  let closeTimeIso = null;
  let boundaryTimer = null;
  let rolloverTimer = null;
  let rolloverUntil = 0;
  let fittedOnce = false;
  let prevSpot = null;
  let audioCtx = null;
  // Chart candle size only — Price to beat is always Kalshi 15m.
  let currentTf = localStorage.getItem(TF_KEY) || "15m";
  if (!["1m", "5m", "15m"].includes(currentTf)) currentTf = "15m";
  let chimeOn = localStorage.getItem(CHIME_KEY);
  chimeOn = chimeOn === null ? true : chimeOn === "1";

  function money(n) {
    if (n == null || !Number.isFinite(n)) return "—";
    return n.toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function ensureAudio() {
    if (!audioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      audioCtx = new AC();
    }
    if (audioCtx.state === "suspended") {
      audioCtx.resume().catch(() => {});
    }
    return audioCtx;
  }

  function playChime(force) {
    if (!chimeOn && !force) return;
    const ctx = ensureAudio();
    if (!ctx) return;
    const now = ctx.currentTime;
    const tones = [
      { f: 880, t: 0.0, d: 0.18 },
      { f: 1174.7, t: 0.14, d: 0.28 },
    ];
    for (const tone of tones) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = tone.f;
      gain.gain.setValueAtTime(0.0001, now + tone.t);
      gain.gain.exponentialRampToValueAtTime(0.22, now + tone.t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + tone.t + tone.d);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now + tone.t);
      osc.stop(now + tone.t + tone.d + 0.02);
    }
    if (navigator.vibrate) {
      try {
        navigator.vibrate([40, 60, 80]);
      } catch {
        // ignore
      }
    }
  }

  function urlBase64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  async function ensureServiceWorker() {
    if (!("serviceWorker" in navigator)) return null;
    try {
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
      await navigator.serviceWorker.ready;
      return reg;
    } catch (err) {
      console.warn("SW register failed", err);
      return null;
    }
  }

  function postToSW(msg) {
    const ctrl = navigator.serviceWorker && navigator.serviceWorker.controller;
    if (ctrl) ctrl.postMessage(msg);
    else if (swReg && swReg.active) swReg.active.postMessage(msg);
  }

  function setBgStatus(ok, text) {
    if (!el.bgStatus) return;
    el.bgStatus.textContent = text;
    el.bgStatus.classList.toggle("ok", !!ok);
    el.bgStatus.classList.toggle("warn", !ok);
  }

  function setPushBadge(on) {
    if (!el.pushBadge) return;
    if (on) {
      el.pushBadge.hidden = false;
      // Next frame so fade/scale transition plays.
      requestAnimationFrame(() => el.pushBadge.classList.add("is-on"));
    } else {
      el.pushBadge.classList.remove("is-on");
      const hide = () => {
        if (!el.pushBadge.classList.contains("is-on")) el.pushBadge.hidden = true;
      };
      el.pushBadge.addEventListener("transitionend", hide, { once: true });
      setTimeout(hide, 320);
    }
  }

  function hideBgSetup(animated) {
    if (!el.bgSetup) return;
    if (!animated) {
      el.bgSetup.classList.add("is-hidden");
      return;
    }
    void el.bgSetup.offsetWidth;
    el.bgSetup.classList.add("is-hidden");
  }

  function showBgSetup() {
    if (!el.bgSetup) return;
    el.bgSetup.classList.remove("is-hidden");
  }

  function isBgArmed() {
    if (localStorage.getItem(BG_ARMED_KEY) === "1") return true;
    return (
      "Notification" in window &&
      Notification.permission === "granted" &&
      localStorage.getItem(BG_ARMED_KEY) !== "0"
    );
  }

  function syncPushUi(armed) {
    const on =
      !!armed &&
      chimeOn &&
      "Notification" in window &&
      Notification.permission === "granted";
    setPushBadge(on);
    if (on) hideBgSetup(true);
    else showBgSetup();
  }

  async function runChimeTest() {
    ensureAudio();
    playChime(true);
    if ("Notification" in window && Notification.permission === "granted") {
      postToSW({
        type: "test-notify",
        beat: lastFifteenTarget,
        ticker: lastFifteenTicker || "TEST",
        closeEt: closeTimeIso,
      });
    }
    setStatus("ok", "Test chime");
  }

  async function ensureNotificationPermission() {
    if (!("Notification" in window)) return false;
    if (Notification.permission === "granted") return true;
    if (Notification.permission === "denied") return false;
    const res = await Notification.requestPermission();
    return res === "granted";
  }

  async function enableBackgroundAlerts() {
    ensureAudio();
    chimeOn = true;
    localStorage.setItem(CHIME_KEY, "1");
    if (el.chimeEnabled) el.chimeEnabled.checked = true;
    setBgStatus(false, "Requesting notification permission…");
    const allowed = await ensureNotificationPermission();
    if (!allowed) {
      setBgStatus(
        false,
        "Notifications blocked. Chrome → site settings → Notifications → Allow, then try again."
      );
      setStatus("warn", "Notifications blocked");
      showBgSetup();
      return false;
    }
    const ok = await subscribePush();
    await runChimeTest();
    try {
      await fetch("/api/push/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          beat: lastFifteenTarget,
          close_et: closeTimeIso,
        }),
      });
    } catch {
      // ignore
    }
    if (ok) {
      localStorage.setItem(BG_ARMED_KEY, "1");
      setBgStatus(true, "Background alerts on");
      setStatus("ok", "Background alerts on");
      setTimeout(() => {
        hideBgSetup(true);
        setPushBadge(true);
      }, 500);
    } else {
      setBgStatus(false, "Could not subscribe to push. Stay on HTTPS / installed app and retry.");
      setStatus("warn", "Push subscribe failed");
      showBgSetup();
      setPushBadge(false);
    }
    return ok;
  }

  async function subscribePush() {
    const reg = swReg || (await ensureServiceWorker());
    if (!reg || !reg.pushManager) return false;
    const allowed = await ensureNotificationPermission();
    if (!allowed) return false;
    try {
      const keyRes = await fetch("/api/push/vapid-public", { cache: "no-store" });
      const keyData = await keyRes.json();
      if (!keyData.ok || !keyData.publicKey) return false;
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(keyData.publicKey),
        });
      }
      await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subscription: sub.toJSON() }),
      });
      postToSW({ type: "set-chime", enabled: chimeOn });
      return true;
    } catch (err) {
      console.warn("push subscribe failed", err);
      return false;
    }
  }

  async function unsubscribePush() {
    try {
      const reg = swReg || (await ensureServiceWorker());
      if (!reg) return;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await fetch("/api/push/unsubscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: sub.endpoint }),
        });
        await sub.unsubscribe();
      }
      postToSW({ type: "set-chime", enabled: false });
    } catch {
      // ignore
    }
  }

  async function alertNewTarget(beat, ticker, closeEt) {
    // Foreground: Web Audio chime. Background: system notification (+ push from server).
    playChime();
    postToSW({
      type: "arm-state",
      ticker,
      target: beat,
      chimeOn,
    });
    if (!chimeOn) return;
    if (document.visibilityState !== "visible") {
      postToSW({
        type: "test-notify",
        beat,
        ticker,
        closeEt,
      });
    } else if ("Notification" in window && Notification.permission === "granted") {
      // Still ping notification so Android can ring if audio is muted/blocked.
      postToSW({
        type: "test-notify",
        beat,
        ticker,
        closeEt,
      });
    }
  }

  function maybeChimeNewFifteenTarget(beat, ticker, source, closeEt) {
    const isFifteen =
      source === "kalshi" || (ticker && String(ticker).includes("KXBTC15M"));
    if (!isFifteen) return;

    const tickerChanged =
      lastFifteenTicker && ticker && lastFifteenTicker !== ticker;
    const beatReady = beat != null && Number.isFinite(beat);
    const beatChanged =
      beatReady &&
      lastFifteenTarget != null &&
      Math.abs(lastFifteenTarget - beat) > 0.005;

    if (tickerChanged || beatChanged) {
      alertNewTarget(beat, ticker, closeEt);
      setStatus("ok", "New 15m target · chime");
    }

    if (ticker) lastFifteenTicker = ticker;
    if (beatReady) lastFifteenTarget = beat;
    postToSW({
      type: "arm-state",
      ticker: lastFifteenTicker,
      target: lastFifteenTarget,
      chimeOn,
    });
  }

  let swReg = null;

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

  function updateOdds(data) {
    if (!el.oddsRow || !el.yesPct || !el.noPct) return;
    const yes = data && data.yes_pct;
    const no = data && data.no_pct;
    if (yes == null || no == null || !Number.isFinite(yes) || !Number.isFinite(no)) {
      el.oddsRow.hidden = true;
      el.yesPct.textContent = "—";
      el.noPct.textContent = "—";
      return;
    }
    el.oddsRow.hidden = false;
    el.yesPct.textContent = `${Math.round(yes)}%`;
    el.noPct.textContent = `${Math.round(no)}%`;
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
      if (el.countdownMeta) el.countdownMeta.textContent = "Until Kalshi 15m window ends";
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
      startRolloverBurst();
      return;
    }
    const totalSec = Math.floor(ms / 1000);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    el.countdown.textContent = `${m}:${String(s).padStart(2, "0")}`;
    el.countdown.classList.toggle("urgent", totalSec <= 60);
    if (el.countdownMeta) {
      el.countdownMeta.textContent =
        totalSec <= 60 ? "Under 1 minute left" : "Until Kalshi 15m window ends";
    }
    if (totalSec <= 20) startRolloverBurst();
  }

  function clearRolloverBurst() {
    if (rolloverTimer) {
      clearInterval(rolloverTimer);
      rolloverTimer = null;
    }
    rolloverUntil = 0;
  }

  function startRolloverBurst() {
    const until = Date.now() + ROLLOVER_BURST_MS;
    if (rolloverUntil > Date.now() && until - rolloverUntil < 5_000) {
      rolloverUntil = Math.max(rolloverUntil, until);
      return;
    }
    rolloverUntil = until;
    if (rolloverTimer) return;
    const tick = () => {
      if (Date.now() > rolloverUntil) {
        clearRolloverBurst();
        return;
      }
      refreshTarget({ forceCandles: true });
      refreshSpot();
    };
    tick();
    rolloverTimer = setInterval(tick, ROLLOVER_TICK_MS);
  }

  function scheduleBoundaryRefresh(closeIso) {
    if (boundaryTimer) {
      clearTimeout(boundaryTimer);
      boundaryTimer = null;
    }
    if (!closeIso) return;
    const closeMs = Date.parse(closeIso);
    if (!Number.isFinite(closeMs)) return;
    const wait = Math.max(250, closeMs + BOUNDARY_PAD_MS - Date.now());
    boundaryTimer = setTimeout(() => {
      startRolloverBurst();
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

  function clearTargetLine() {
    if (targetLine && series) {
      try {
        series.removePriceLine(targetLine);
      } catch {
        // ignore
      }
    }
    targetLine = null;
  }

  function applyTargetLine(target, title) {
    lastTarget = target;
    if (!series || target == null || !Number.isFinite(target)) {
      clearTargetLine();
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
    clearTargetLine();
    targetLine = series.createPriceLine(opts);
  }

  async function refreshTarget(opts = {}) {
    const forceCandles = !!opts.forceCandles;
    try {
      // Always Kalshi 15m — never switch target with chart buttons.
      const res = await fetch(`/api/target?tf=15m&_=${Date.now()}`, {
        cache: "no-store",
      });
      const data = await res.json();
      const beat = data.price_to_beat ?? data.target;
      const prevClose = closeTimeIso;
      closeTimeIso = data.close_time || null;
      updateCountdown();
      updateOdds(data);
      if (el.targetLabel) {
        el.targetLabel.textContent = data.label || "Price to beat · Kalshi 15m";
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
        el.targetMeta.textContent = data.error || "Waiting for Kalshi 15m window";
        applyTargetLine(null);
        maybeChimeNewFifteenTarget(null, data.ticker, data.source, data.close_et);
        startRolloverBurst();
      } else {
        const rolled =
          (lastTicker && data.ticker && lastTicker !== data.ticker) ||
          (prevClose && closeTimeIso && prevClose !== closeTimeIso);
        lastTicker = data.ticker;
        setStatus(
          "ok",
          data.stale_previous
            ? "Rolling…"
            : rolled
              ? "New 15m price to beat"
              : "Live · Kalshi 15m"
        );
        el.targetValue.textContent = money(beat);
        const win = formatWindow(data.close_time, data.close_et);
        el.targetMeta.textContent = win
          ? `Kalshi 15m · settles ${win}`
          : "Kalshi 15m";
        applyTargetLine(beat, "TARGET");
        maybeChimeNewFifteenTarget(beat, data.ticker, data.source, data.close_et);
        if (el.spotValue && el.spotValue.dataset.last) {
          updateSpot(Number(el.spotValue.dataset.last));
        }
        if (rolled || forceCandles) refreshCandles();
        if (
          rolled &&
          !data.stale_previous &&
          closeTimeIso &&
          Date.parse(closeTimeIso) > Date.now() + 5_000
        ) {
          clearRolloverBurst();
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
      const res = await fetch(`/api/spot?_=${Date.now()}`, { cache: "no-store" });
      const data = await res.json();
      if (!data.ok || data.price == null) return;
      updateSpot(Number(data.price));
    } catch {
      // keep last spot
    }
  }

  async function refreshCandles() {
    try {
      const res = await fetch(
        `/api/candles?tf=${encodeURIComponent(currentTf)}&_=${Date.now()}`,
        { cache: "no-store" }
      );
      const data = await res.json();
      if (!data.ok) {
        setStatus("warn", data.error || "Candles error");
        return;
      }
      ensureChart();
      if (!series) return;
      const candles = data.candles || [];
      clearTargetLine();
      series.setData([]);
      series.setData(candles);
      if (lastTarget != null) applyTargetLine(lastTarget, "TARGET");
      if (!el.spotValue?.dataset.last && candles.length) {
        updateSpot(candles[candles.length - 1].close);
      }
      if (!fittedOnce) {
        chart.timeScale().fitContent();
        fittedOnce = true;
      }
    } catch (err) {
      setStatus("warn", "Candle fetch failed");
    }
  }

  function syncTfButtons() {
    if (!el.timeframe) return;
    el.timeframe.querySelectorAll(".tf-btn").forEach((btn) => {
      const on = btn.dataset.tf === currentTf;
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }

  function setTimeframe(tf) {
    if (!["1m", "5m", "15m"].includes(tf) || tf === currentTf) {
      syncTfButtons();
      return;
    }
    currentTf = tf;
    localStorage.setItem(TF_KEY, currentTf);
    fittedOnce = false;
    syncTfButtons();
    setTfLabel();
    setStatus("loading", `Loading ${currentTf} chart…`);
    // Only candles change — keep Kalshi 15m target/odds/countdown.
    refreshCandles();
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
      syncTfButtons();
      el.timeframe.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".tf-btn");
        if (!btn || !el.timeframe.contains(btn)) return;
        setTimeframe(btn.dataset.tf);
        ensureAudio();
      });
    }
    if (el.chimeEnabled) {
      el.chimeEnabled.checked = chimeOn;
      el.chimeEnabled.addEventListener("change", async () => {
        chimeOn = el.chimeEnabled.checked;
        localStorage.setItem(CHIME_KEY, chimeOn ? "1" : "0");
        ensureAudio();
        postToSW({ type: "set-chime", enabled: chimeOn });
        if (chimeOn) {
          const ok = await subscribePush();
          playChime(true);
          if (!ok) {
            setStatus("warn", "Allow Notifications for background chime");
            showBgSetup();
            setPushBadge(false);
          } else {
            localStorage.setItem(BG_ARMED_KEY, "1");
            setStatus("ok", "Background chime enabled");
            hideBgSetup(true);
            setPushBadge(true);
          }
        } else {
          await unsubscribePush();
          localStorage.setItem(BG_ARMED_KEY, "0");
          showBgSetup();
          setPushBadge(false);
          setBgStatus(false, "Chime off. Turn it back on, then enable background alerts again.");
        }
      });
    }
    // Long-press chime label = test (no permanent Test button).
    if (el.chimeToggleLabel) {
      let pressTimer = null;
      const clearPress = () => {
        if (pressTimer) {
          clearTimeout(pressTimer);
          pressTimer = null;
        }
      };
      el.chimeToggleLabel.addEventListener("pointerdown", (ev) => {
        if (ev.pointerType === "mouse" && ev.button !== 0) return;
        clearPress();
        pressTimer = setTimeout(() => {
          pressTimer = null;
          runChimeTest();
        }, 550);
      });
      el.chimeToggleLabel.addEventListener("pointerup", clearPress);
      el.chimeToggleLabel.addEventListener("pointerleave", clearPress);
      el.chimeToggleLabel.addEventListener("pointercancel", clearPress);
      el.chimeToggleLabel.addEventListener("contextmenu", (ev) => ev.preventDefault());
    }
    if (el.enableBg) {
      el.enableBg.addEventListener("click", () => {
        enableBackgroundAlerts();
      });
    }
    if (isBgArmed() && Notification.permission === "granted") {
      hideBgSetup(false);
      setPushBadge(true);
    } else {
      setPushBadge(false);
    }
    const unlock = () => ensureAudio();
    window.addEventListener("pointerdown", unlock, { passive: true });
    window.addEventListener("touchstart", unlock, { passive: true });
    window.addEventListener("keydown", unlock);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        ensureAudio();
        startRolloverBurst();
      } else {
        // Page hidden — rely on SW poll + server Web Push.
        postToSW({ type: "check-now" });
        postToSW({
          type: "arm-state",
          ticker: lastFifteenTicker,
          target: lastFifteenTarget,
          chimeOn,
        });
      }
    });

    setTfLabel();
    ensureChart();
    resizeChart();
    ensureServiceWorker().then(async (reg) => {
      swReg = reg;
      postToSW({ type: "set-chime", enabled: chimeOn });
      if (chimeOn) {
        // Don't block UI; request permission on first gesture via Test/toggle too.
        subscribePush().catch(() => {});
      }
      if (reg && "periodicSync" in reg) {
        try {
          await reg.periodicSync.register("kalshi-15m-check", {
            minInterval: 15 * 60 * 1000,
          });
        } catch {
          // unsupported / not granted
        }
      }
    });
    const liveUrl = document.getElementById("live-url");
    if (liveUrl) {
      liveUrl.href = window.location.origin + "/";
      liveUrl.textContent = window.location.origin + "/";
    }
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
