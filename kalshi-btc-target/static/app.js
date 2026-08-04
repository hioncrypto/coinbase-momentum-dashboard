(() => {
  const TARGET_POLL_MS = 1_200;
  const CANDLE_POLL_MS = 10_000;
  const SPOT_POLL_MS = 1_500;
  const BOUNDARY_PAD_MS = 250;
  const ROLLOVER_BURST_MS = 60_000;
  const ROLLOVER_TICK_MS = 750;
  const TF_KEY = "kalshiChartTf";
  const CHIME_KEY = "kalshiChimeEnabled";
  const BG_ARMED_KEY = "kalshiBgAlertsArmed";

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
    bgStatus: document.getElementById("bg-status"),
    pushBadge: document.getElementById("push-badge"),
    rotateGate: document.getElementById("rotate-gate"),
    oddsRow: document.getElementById("odds-row"),
    yesPct: document.getElementById("yes-pct"),
    noPct: document.getElementById("no-pct"),
    yesBook: document.getElementById("yes-book"),
    noBook: document.getElementById("no-book"),
    oddsHint: document.getElementById("odds-hint"),
    edgeLine: document.getElementById("edge-line"),
    roiPanel: document.getElementById("roi-panel"),
    stakeSlider: document.getElementById("stake-slider"),
    stakeValue: document.getElementById("stake-value"),
    roiAbovePrice: document.getElementById("roi-above-price"),
    roiAboveSummary: document.getElementById("roi-above-summary"),
    roiAboveDetail: document.getElementById("roi-above-detail"),
    roiBelowPrice: document.getElementById("roi-below-price"),
    roiBelowSummary: document.getElementById("roi-below-summary"),
    roiBelowDetail: document.getElementById("roi-below-detail"),
    settleBanner: document.getElementById("settle-banner"),
    settleTitle: document.getElementById("settle-title"),
    settleAvg: document.getElementById("settle-avg"),
    settleMeta: document.getElementById("settle-meta"),
    kalshiLink: document.getElementById("kalshi-link"),
  };

  let chart = null;
  let series = null;
  let targetLine = null;
  let settleLine = null;
  let lastTicker = null;
  let lastTarget = null;
  let lastFifteenTarget = null;
  let lastFifteenTicker = null;
  let lastKalshiUrl = "https://kalshi.com/markets/kxbtc15m";
  let lastYesPct = null;
  let lastSettlementAvg = null;
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
      const reg = await navigator.serviceWorker.register("/sw.js?v=2.2", { scope: "/" });
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

  function setPushBadge(on) {
    if (!el.pushBadge) return;
    el.pushBadge.classList.toggle("is-on", !!on);
    el.pushBadge.setAttribute("aria-pressed", on ? "true" : "false");
    el.pushBadge.title = on ? "Alerts on — tap to turn off" : "Alerts off — tap to turn on";
  }

  function setBgStatus(ok, text) {
    if (!el.bgStatus) return;
    if (!text) {
      el.bgStatus.hidden = true;
      el.bgStatus.textContent = "";
      return;
    }
    el.bgStatus.hidden = false;
    el.bgStatus.textContent = text;
    el.bgStatus.classList.toggle("ok", !!ok);
    el.bgStatus.classList.toggle("warn", !ok);
  }

  function isBgArmed() {
    if (localStorage.getItem(BG_ARMED_KEY) === "1") return true;
    return (
      "Notification" in window &&
      Notification.permission === "granted" &&
      localStorage.getItem(BG_ARMED_KEY) !== "0"
    );
  }

  function alertsAreOn() {
    return (
      chimeOn &&
      isBgArmed() &&
      "Notification" in window &&
      Notification.permission === "granted"
    );
  }

  function syncAlertsUi() {
    setPushBadge(alertsAreOn());
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

  async function turnAlertsOn() {
    ensureAudio();
    chimeOn = true;
    localStorage.setItem(CHIME_KEY, "1");
    postToSW({ type: "set-chime", enabled: true });
    const allowed = await ensureNotificationPermission();
    if (!allowed) {
      setPushBadge(false);
      setStatus("warn", "Allow Notifications to enable alerts");
      setBgStatus(false, "Notifications blocked in Chrome site settings.");
      return false;
    }
    const ok = await subscribePush();
    if (!ok) {
      setPushBadge(false);
      setStatus("warn", "Could not enable push alerts");
      return false;
    }
    localStorage.setItem(BG_ARMED_KEY, "1");
    setPushBadge(true);
    setBgStatus(null, "");
    await runChimeTest();
    setStatus("ok", "Alerts on");
    return true;
  }

  async function turnAlertsOff() {
    chimeOn = false;
    localStorage.setItem(CHIME_KEY, "0");
    localStorage.setItem(BG_ARMED_KEY, "0");
    postToSW({ type: "set-chime", enabled: false });
    await unsubscribePush();
    setPushBadge(false);
    setBgStatus(null, "");
    setStatus("ok", "Alerts off");
  }

  async function toggleAlerts() {
    if (alertsAreOn()) await turnAlertsOff();
    else await turnAlertsOn();
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

  function bookText(bid, ask) {
    if (bid == null && ask == null) return "book —";
    if (bid != null && ask != null) return `bid ${bid}¢ · ask ${ask}¢`;
    if (bid != null) return `bid ${bid}¢`;
    return `ask ${ask}¢`;
  }

  let lastRoiAsks = { above: null, below: null };
  const STAKE_KEY = "kalshiTradeStake";
  let tradeStake = Number(localStorage.getItem(STAKE_KEY));
  if (!Number.isFinite(tradeStake)) tradeStake = 50;
  tradeStake = Math.max(0, Math.min(100, Math.round(tradeStake)));

  function dollars(n) {
    if (n == null || !Number.isFinite(n)) return "—";
    return n.toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  /** Kalshi taker fee ≈ round_up(0.07 × C × P × (1 − P)) to the next cent. */
  function kalshiTakerFee(contracts, priceDollars) {
    const C = Math.max(0, contracts);
    const P = Math.min(0.99, Math.max(0.01, priceDollars));
    const raw = 0.07 * C * P * (1 - P);
    return Math.ceil(raw * 100 - 1e-9) / 100;
  }

  /**
   * Spend about `stakeUsd` buying this side at the ask (taker).
   * Returns null if we can't price it.
   */
  function roiForStake(askCents, stakeUsd) {
    if (askCents == null || !Number.isFinite(askCents)) return null;
    const P = askCents / 100;
    if (!(P > 0 && P < 1)) return null;
    if (!(stakeUsd > 0)) {
      return {
        askCents: Math.round(askCents),
        contracts: 0,
        cost: 0,
        fee: 0,
        total: 0,
        winPayout: 0,
        profitIfWin: 0,
        roiIfWin: null,
        empty: true,
      };
    }
    const contracts = Math.max(1, Math.floor(stakeUsd / P));
    const cost = contracts * P;
    const fee = kalshiTakerFee(contracts, P);
    const total = cost + fee;
    const winPayout = contracts * 1;
    const profitIfWin = winPayout - total;
    const roiIfWin = total > 0 ? (profitIfWin / total) * 100 : null;
    return {
      askCents: Math.round(askCents),
      contracts,
      cost,
      fee,
      total,
      winPayout,
      profitIfWin,
      roiIfWin,
      empty: false,
    };
  }

  function fillRoiCard(priceEl, summaryEl, detailEl, askCents, stakeUsd) {
    if (priceEl) {
      priceEl.textContent =
        askCents != null && Number.isFinite(askCents)
          ? `Ask ${Math.round(askCents)}¢`
          : "Ask —";
    }
    const r = roiForStake(askCents, stakeUsd);
    if (!r) {
      if (summaryEl) summaryEl.textContent = "—";
      if (detailEl) detailEl.textContent = "Need a live ask";
      return false;
    }
    if (r.empty) {
      if (summaryEl) summaryEl.textContent = "Slide to size a trade";
      if (detailEl) detailEl.textContent = "Set a dollar amount above";
      return true;
    }
    const roiTxt =
      r.roiIfWin != null
        ? `${r.roiIfWin >= 0 ? "+" : ""}${r.roiIfWin.toFixed(0)}%`
        : "—";
    if (summaryEl) {
      summaryEl.textContent = `Win ${dollars(r.profitIfWin)} · ${roiTxt}`;
    }
    if (detailEl) {
      detailEl.innerHTML =
        `${r.contracts} contracts<br>` +
        `Cost ${dollars(r.cost)} + fee ${dollars(r.fee)}<br>` +
        `Total ${dollars(r.total)} · lose = ${dollars(r.total)}`;
    }
    return true;
  }

  function syncStakeUi() {
    if (el.stakeSlider) {
      el.stakeSlider.value = String(tradeStake);
      el.stakeSlider.setAttribute("aria-valuenow", String(tradeStake));
    }
    if (el.stakeValue) el.stakeValue.textContent = `$${tradeStake}`;
  }

  function renderRoi() {
    if (!el.roiPanel) return;
    syncStakeUi();
    const okA = fillRoiCard(
      el.roiAbovePrice,
      el.roiAboveSummary,
      el.roiAboveDetail,
      lastRoiAsks.above,
      tradeStake
    );
    const okB = fillRoiCard(
      el.roiBelowPrice,
      el.roiBelowSummary,
      el.roiBelowDetail,
      lastRoiAsks.below,
      tradeStake
    );
    el.roiPanel.hidden = !(okA || okB);
  }

  function setTradeStake(n) {
    tradeStake = Math.max(0, Math.min(100, Math.round(Number(n) || 0)));
    localStorage.setItem(STAKE_KEY, String(tradeStake));
    renderRoi();
  }

  function updateRoi(data) {
    let aboveAsk = data && data.yes_ask_pct;
    let belowAsk = data && data.no_ask_pct;
    if (aboveAsk == null && data && data.yes_pct != null) aboveAsk = data.yes_pct;
    if (belowAsk == null && data && data.no_pct != null) belowAsk = data.no_pct;
    if (belowAsk == null && data && data.yes_bid_pct != null) {
      belowAsk = Math.max(1, 100 - data.yes_bid_pct);
    }
    if (aboveAsk == null && data && data.no_bid_pct != null) {
      aboveAsk = Math.max(1, 100 - data.no_bid_pct);
    }
    lastRoiAsks = { above: aboveAsk, below: belowAsk };
    renderRoi();
  }

  function updateOdds(data) {
    if (!el.oddsRow || !el.yesPct || !el.noPct) return;
    const yes = data && data.yes_pct;
    const no = data && data.no_pct;
    if (yes == null || no == null || !Number.isFinite(yes) || !Number.isFinite(no)) {
      el.oddsRow.hidden = true;
      el.yesPct.textContent = "—";
      el.noPct.textContent = "—";
      if (el.yesBook) el.yesBook.textContent = "—";
      if (el.noBook) el.noBook.textContent = "—";
      lastYesPct = null;
      if (el.roiPanel) el.roiPanel.hidden = true;
      return;
    }
    el.oddsRow.hidden = false;
    el.yesPct.textContent = `${Math.round(yes)}%`;
    el.noPct.textContent = `${Math.round(no)}%`;
    lastYesPct = Math.round(yes);
    if (el.yesBook) {
      el.yesBook.textContent = bookText(data.yes_bid_pct, data.yes_ask_pct);
    }
    if (el.noBook) {
      el.noBook.textContent = bookText(data.no_bid_pct, data.no_ask_pct);
    }
    if (el.oddsHint) {
      if (data.thin_book) el.oddsHint.textContent = "Wide spread · thin book";
      else if (data.odds_fresh) el.oddsHint.textContent = "Fresh window · book mid";
      else if (data.spread_cents != null) {
        el.oddsHint.textContent = `Spread ${data.spread_cents}¢`;
      } else el.oddsHint.textContent = "What traders are pricing";
    }
    updateRoi(data);
  }

  function updateEdgeLine(spot) {
    if (!el.edgeLine) return;
    if (
      spot == null ||
      !Number.isFinite(spot) ||
      lastTarget == null ||
      !Number.isFinite(lastTarget) ||
      lastYesPct == null
    ) {
      el.edgeLine.hidden = true;
      el.edgeLine.textContent = "";
      return;
    }
    const delta = spot - lastTarget;
    const side = delta >= 0 ? "above" : "below";
    const abs = Math.abs(delta);
    let left = "—";
    if (closeTimeIso) {
      const ms = Date.parse(closeTimeIso) - Date.now();
      if (Number.isFinite(ms) && ms > 0) {
        const sec = Math.floor(ms / 1000);
        left = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
      } else if (Number.isFinite(ms) && ms <= 0) left = "0:00";
    }
    el.edgeLine.hidden = false;
    el.edgeLine.textContent = `Live is $${abs.toFixed(2)} ${side} beat · Above ${lastYesPct}% · ${left} left`;
  }

  function updateSettlement(data) {
    if (!el.settleBanner) return;
    const mode = !!(data && data.settlement_mode);
    if (!mode) {
      el.settleBanner.hidden = true;
      el.settleBanner.classList.remove("is-above", "is-below");
      lastSettlementAvg = null;
      applySettleLine(null);
      return;
    }
    el.settleBanner.hidden = false;
    const avg = data.settlement_avg;
    lastSettlementAvg = avg;
    const side = data.settlement_side;
    el.settleBanner.classList.toggle("is-above", side === "above");
    el.settleBanner.classList.toggle("is-below", side === "below");
    if (el.settleTitle) {
      el.settleTitle.textContent =
        side === "above"
          ? "Last minute · average is ABOVE"
          : side === "below"
            ? "Last minute · average is BELOW"
            : "Last minute · settling now";
    }
    if (el.settleAvg) {
      el.settleAvg.textContent =
        avg != null && Number.isFinite(avg)
          ? `${money(avg)} avg`
          : "Collecting samples…";
    }
    if (el.settleMeta) {
      const n = data.settlement_samples || 0;
      const d = data.settlement_delta;
      const deltaTxt =
        d != null && Number.isFinite(d)
          ? ` · ${d >= 0 ? "+" : "-"}$${Math.abs(d).toFixed(2)} vs beat`
          : "";
      el.settleMeta.textContent = `Kalshi settles on a 60-second average, not the last tick · ${n}/60 samples${deltaTxt}`;
    }
    applySettleLine(avg);
  }

  function updateSpot(lastClose) {
    if (!el.spotValue) return;
    if (lastClose == null || !Number.isFinite(lastClose)) {
      el.spotValue.textContent = "—";
      if (el.spotDelta) {
        el.spotDelta.textContent = "—";
        el.spotDelta.className = "spot-delta";
      }
      updateEdgeLine(null);
      return;
    }
    el.spotValue.textContent = money(lastClose);
    el.spotValue.dataset.last = String(lastClose);

    if (prevSpot != null && Number.isFinite(prevSpot)) {
      if (lastClose > prevSpot) el.spotValue.style.color = "#1ac96b";
      else if (lastClose < prevSpot) el.spotValue.style.color = "#d45454";
    }
    prevSpot = lastClose;

    if (el.spotDelta) {
      if (lastTarget != null && Number.isFinite(lastTarget)) {
        const delta = lastClose - lastTarget;
        const sign = delta >= 0 ? "+" : "-";
        el.spotDelta.textContent = `${sign}$${Math.abs(delta).toFixed(2)}`;
        el.spotDelta.className = "spot-delta " + (delta >= 0 ? "up" : "down");
      } else {
        el.spotDelta.textContent = "—";
        el.spotDelta.className = "spot-delta";
      }
    }
    updateEdgeLine(lastClose);
  }

  function updateCountdown() {
    if (!el.countdown) return;
    if (!closeTimeIso) {
      el.countdown.textContent = "—:—";
      el.countdown.classList.remove("urgent");
      if (el.countdownMeta) el.countdownMeta.textContent = "Until this 15m window ends";
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
      if (el.countdownMeta) {
        el.countdownMeta.textContent = "Window closed · loading next…";
      }
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
        totalSec <= 60
          ? "Final minute — settlement average decides the winner"
          : "Until this 15m window ends";
    }
    if (totalSec <= 25) startRolloverBurst();
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
    if (!chart || !el.chart) return;
    // Prefer layout size — getBoundingClientRect is wrong under CSS portrait lock.
    const width = el.chart.clientWidth || el.chart.offsetWidth;
    const height = el.chart.clientHeight || el.chart.offsetHeight;
    chart.applyOptions({
      width: Math.max(280, Math.floor(width || 280)),
      height: Math.max(320, Math.floor(height || 320)),
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

  function clearSettleLine() {
    if (settleLine && series) {
      try {
        series.removePriceLine(settleLine);
      } catch {
        // ignore
      }
    }
    settleLine = null;
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
      title: title || "BEAT",
    };
    clearTargetLine();
    targetLine = series.createPriceLine(opts);
  }

  function applySettleLine(avg) {
    if (!series || avg == null || !Number.isFinite(avg)) {
      clearSettleLine();
      return;
    }
    const opts = {
      price: avg,
      color: "#ffd28a",
      lineWidth: 2,
      lineStyle: (ensureChart.LineStyle && ensureChart.LineStyle.Solid) || 0,
      axisLabelVisible: true,
      title: "AVG",
    };
    clearSettleLine();
    settleLine = series.createPriceLine(opts);
  }

  async function refreshTarget(opts = {}) {
    const forceCandles = !!opts.forceCandles;
    try {
      const res = await fetch(`/api/target?tf=15m&_=${Date.now()}`, {
        cache: "no-store",
      });
      const data = await res.json();
      const beat = data.price_to_beat ?? data.target;
      const prevClose = closeTimeIso;
      const prevTicker = lastTicker;
      closeTimeIso = data.close_time || null;
      updateCountdown();
      updateSettlement(data);

      if (data.kalshi_url && el.kalshiLink) {
        lastKalshiUrl = data.kalshi_url;
        el.kalshiLink.href = data.kalshi_url;
      }

      const rolled =
        (prevTicker && data.ticker && prevTicker !== data.ticker) ||
        (prevClose && closeTimeIso && prevClose !== closeTimeIso) ||
        !!data.stale_previous ||
        !!data.waiting_next;

      if (rolled && (data.odds_fresh || data.stale_previous || data.yes_pct == null)) {
        updateOdds({
          yes_pct: data.yes_pct != null && !data.stale_previous ? data.yes_pct : 50,
          no_pct: data.no_pct != null && !data.stale_previous ? data.no_pct : 50,
          yes_bid_pct: data.yes_bid_pct,
          yes_ask_pct: data.yes_ask_pct,
          no_bid_pct: data.no_bid_pct,
          no_ask_pct: data.no_ask_pct,
          spread_cents: data.spread_cents,
          thin_book: data.thin_book,
          odds_fresh: true,
        });
      } else {
        updateOdds(data);
      }

      if (el.targetLabel) {
        el.targetLabel.textContent = "Price to beat";
      }

      if ((!data.ok && beat == null) || data.waiting_next) {
        setStatus("warn", data.error || "Waiting for next window");
        el.targetValue.textContent = beat != null ? money(beat) : "—";
        el.targetMeta.textContent = data.error || "Next Kalshi 15m opening…";
        if (beat == null) applyTargetLine(null);
        startRolloverBurst();
        scheduleBoundaryRefresh(data.close_time);
        return;
      }

      if (beat == null) {
        setStatus("warn", "Price to beat TBD");
        el.targetValue.textContent = "TBD";
        el.targetMeta.textContent = data.error || "Waiting for Kalshi to post the beat";
        applyTargetLine(null);
        updateOdds({ yes_pct: 50, no_pct: 50, odds_fresh: true });
        maybeChimeNewFifteenTarget(null, data.ticker, data.source, data.close_et);
        startRolloverBurst();
      } else {
        lastTicker = data.ticker;
        setStatus(
          "ok",
          data.settlement_mode
            ? "Settling…"
            : data.stale_previous
              ? "Rolling…"
              : rolled
                ? "New 15m window"
                : "Live"
        );
        el.targetValue.textContent = money(beat);
        const win = formatWindow(data.close_time, data.close_et);
        el.targetMeta.textContent = win
          ? `This window settles ${win}`
          : "Kalshi 15-minute market";
        applyTargetLine(beat, "BEAT");
        maybeChimeNewFifteenTarget(beat, data.ticker, data.source, data.close_et);
        if (el.spotValue && el.spotValue.dataset.last) {
          updateSpot(Number(el.spotValue.dataset.last));
        }
        if (rolled || forceCandles || data.settlement_mode) refreshCandles();
        if (rolled || data.settlement_mode) startRolloverBurst();
        if (
          rolled &&
          !data.stale_previous &&
          closeTimeIso &&
          Date.parse(closeTimeIso) > Date.now() + 5_000
        ) {
          rolloverUntil = Math.max(rolloverUntil, Date.now() + 25_000);
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
    if (el.clock) {
      el.clock.textContent = new Date().toLocaleTimeString([], {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
      });
    }
    updateCountdown();
  }

  function isLandscapeNow() {
    try {
      const type = String((screen.orientation && screen.orientation.type) || "");
      if (type.startsWith("landscape")) return true;
      if (type.startsWith("portrait")) return false;
    } catch {
      // fall through
    }
    return window.matchMedia("(orientation: landscape)").matches;
  }

  function syncRotateGate() {
    if (!el.rotateGate) return;
    const landscape = isLandscapeNow();
    el.rotateGate.hidden = !landscape;
  }

  async function lockOrientationPortrait() {
    const orient = screen.orientation;
    if (!orient || typeof orient.lock !== "function") return false;
    try {
      await orient.lock("portrait-primary");
      return true;
    } catch {
      try {
        await orient.lock("portrait");
        return true;
      } catch {
        return false;
      }
    }
  }

  async function enterFullscreenIfNeeded() {
    if (document.fullscreenElement) return true;
    const root = document.documentElement;
    try {
      if (typeof root.requestFullscreen === "function") {
        await root.requestFullscreen({ navigationUI: "hide" });
        return true;
      }
    } catch {
      // ignore
    }
    try {
      if (typeof root.webkitRequestFullscreen === "function") {
        root.webkitRequestFullscreen();
        return true;
      }
    } catch {
      // ignore
    }
    return !!document.fullscreenElement;
  }

  async function ensurePortraitLock(fromGesture) {
    // Chrome only allows orientation.lock from a gesture, and usually only
    // after fullscreen — unless the app is an installed fullscreen/standalone PWA.
    if (fromGesture) {
      await enterFullscreenIfNeeded();
    }
    await lockOrientationPortrait();
    syncRotateGate();
    setTimeout(resizeChart, 100);
    setTimeout(resizeChart, 350);
  }

  function tryLockPortrait() {
    ensurePortraitLock(false);
  }

  function afterOrientationSettle() {
    ensurePortraitLock(false);
    setTimeout(resizeChart, 50);
    setTimeout(resizeChart, 250);
    setTimeout(resizeChart, 600);
  }

  function boot() {
    if (!window.LightweightCharts) {
      setStatus("warn", "Chart library failed to load");
      return;
    }
    syncRotateGate();
    tryLockPortrait();
    if (el.timeframe) {
      syncTfButtons();
      el.timeframe.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".tf-btn");
        if (!btn || !el.timeframe.contains(btn)) return;
        setTimeframe(btn.dataset.tf);
        ensureAudio();
        ensurePortraitLock(true);
      });
    }
    if (el.pushBadge) {
      el.pushBadge.addEventListener("click", () => {
        ensurePortraitLock(true);
        toggleAlerts();
      });
    }
    if (el.rotateGate) {
      el.rotateGate.addEventListener("click", () => {
        ensurePortraitLock(true);
      });
    }
    if (el.stakeSlider) {
      syncStakeUi();
      const onStake = () => setTradeStake(el.stakeSlider.value);
      el.stakeSlider.addEventListener("input", onStake);
      el.stakeSlider.addEventListener("change", onStake);
    }
    syncAlertsUi();
    const unlock = () => {
      ensureAudio();
      ensurePortraitLock(true);
    };
    window.addEventListener("pointerdown", unlock, { passive: true });
    window.addEventListener("touchstart", unlock, { passive: true });
    window.addEventListener("keydown", unlock);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        ensureAudio();
        ensurePortraitLock(true);
        startRolloverBurst();
        refreshTarget({ forceCandles: true });
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
    refreshCandles().then(refreshTarget).then(refreshSpot);
    setInterval(refreshTarget, TARGET_POLL_MS);
    setInterval(refreshCandles, CANDLE_POLL_MS);
    setInterval(refreshSpot, SPOT_POLL_MS);
    setInterval(tickClock, 250);
    // Keep fighting landscape — Android can ignore a single lock call.
    setInterval(() => {
      syncRotateGate();
      if (isLandscapeNow()) ensurePortraitLock(false);
    }, 700);
    tickClock();
    window.addEventListener("resize", () => {
      syncRotateGate();
      tryLockPortrait();
      resizeChart();
    });
    window.addEventListener("orientationchange", afterOrientationSettle);
    if (screen.orientation && typeof screen.orientation.addEventListener === "function") {
      screen.orientation.addEventListener("change", afterOrientationSettle);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    window.addEventListener("load", boot);
  }
})();
