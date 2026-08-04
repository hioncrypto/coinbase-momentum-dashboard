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
  const DEMO_KEY = "kalshiDemoState";
  const DEMO_DEFAULT_START = 1000;
  const TUTORIAL_KEY = "beatlineTutorialSeen";

  const TUTORIAL_STEPS = [
    {
      title: "Welcome to BeatLine",
      body: "BeatLine tracks Kalshi’s 15-minute BTC Price to beat. Live price, countdown, odds, and a TARGET line on the chart — all in one portrait screen.",
    },
    {
      title: "Read the window",
      body: "Price to beat is the line BTC must finish above or below. Live now is the current index. Time left is when this 15m window settles. The chart shows that TARGET as a dashed line.",
    },
    {
      title: "Odds & Best Side",
      body: "Market chance shows Above/Below pricing. Best Side scores distance from the beat, time left, ask, and fees. When a clear edge appears, BeatLine chimes and notifies you automatically — tap Best to trade it.",
    },
    {
      title: "Set size, then buy",
      body: "Use the Trade size slider ($0–$100). Then tap Buy Above, Best, or Buy Below at the bottom. Enter dollars if needed and slide to confirm — release early to cancel.",
    },
    {
      title: "Rolling P/L",
      body: "After a buy, an Open trade card tracks live P/L as price and odds move: entry, bid, fees, vs beat, time left, and hold outcomes. Close at bid anytime, or hold to window settle.",
    },
    {
      title: "Demo & alerts",
      body: "⋮ Options → Demo mode turns on a paper bankroll and session P/L. The bell enables automatic alerts for new 15m targets and clear-edge Best Side moments.",
    },
  ];

  let tutorialIndex = 0;
  let tutorialOpen = false;

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
    bestSide: document.getElementById("best-side"),
    bestSideLabel: document.getElementById("best-side-label"),
    bestSideAmount: document.getElementById("best-side-amount"),
    bestSideMeta: document.getElementById("best-side-meta"),
    roiAbovePrice: document.getElementById("roi-above-price"),
    roiAboveSummary: document.getElementById("roi-above-summary"),
    roiAboveDetail: document.getElementById("roi-above-detail"),
    roiBelowPrice: document.getElementById("roi-below-price"),
    roiBelowSummary: document.getElementById("roi-below-summary"),
    roiBelowDetail: document.getElementById("roi-below-detail"),
    dockBuyAbove: document.getElementById("dock-buy-above"),
    dockBuyBelow: document.getElementById("dock-buy-below"),
    dockBuyBest: document.getElementById("dock-buy-best"),
    dockAbovePct: document.getElementById("dock-above-pct"),
    dockBelowPct: document.getElementById("dock-below-pct"),
    dockBestDetail: document.getElementById("dock-best-detail"),
    settleBanner: document.getElementById("settle-banner"),
    settleTitle: document.getElementById("settle-title"),
    settleAvg: document.getElementById("settle-avg"),
    settleMeta: document.getElementById("settle-meta"),
    menuBtn: document.getElementById("menu-btn"),
    optionsBackdrop: document.getElementById("options-backdrop"),
    optionsSheet: document.getElementById("options-sheet"),
    optionsClose: document.getElementById("options-close"),
    tutorial: document.getElementById("tutorial"),
    tutorialBackdrop: document.getElementById("tutorial-backdrop"),
    tutorialTitle: document.getElementById("tutorial-title"),
    tutorialBody: document.getElementById("tutorial-body"),
    tutorialStepNum: document.getElementById("tutorial-step-num"),
    tutorialStepTotal: document.getElementById("tutorial-step-total"),
    tutorialNext: document.getElementById("tutorial-next"),
    tutorialSkip: document.getElementById("tutorial-skip"),
    tutorialOpen: document.getElementById("tutorial-open"),
    demoToggle: document.getElementById("demo-toggle"),
    demoAccount: document.getElementById("demo-account"),
    demoBalance: document.getElementById("demo-balance"),
    demoPl: document.getElementById("demo-pl"),
    demoStart: document.getElementById("demo-start"),
    demoReset: document.getElementById("demo-reset"),
    demoPosition: document.getElementById("demo-position"),
    demoBuyBest: document.getElementById("demo-buy-best"),
    demoBuyAbove: document.getElementById("demo-buy-above"),
    demoBuyBelow: document.getElementById("demo-buy-below"),
    demoLast: document.getElementById("demo-last"),
    demoMark: document.getElementById("demo-mark"),
    demoMarkPl: document.getElementById("demo-mark-pl"),
    demoMarkMeta: document.getElementById("demo-mark-meta"),
    demoClose: document.getElementById("demo-close"),
    demoLive: document.getElementById("demo-live"),
    demoLiveKicker: document.getElementById("demo-live-kicker"),
    demoLiveSide: document.getElementById("demo-live-side"),
    demoLivePl: document.getElementById("demo-live-pl"),
    demoLivePct: document.getElementById("demo-live-pct"),
    demoLiveFactors: document.getElementById("demo-live-factors"),
    demoLiveMeta: document.getElementById("demo-live-meta"),
    demoLiveClose: document.getElementById("demo-live-close"),
    openPlBar: document.getElementById("open-pl-bar"),
    openPlSide: document.getElementById("open-pl-side"),
    openPlValue: document.getElementById("open-pl-value"),
    openPlSub: document.getElementById("open-pl-sub"),
    openPlClose: document.getElementById("open-pl-close"),
    buyBackdrop: document.getElementById("buy-backdrop"),
    buySheet: document.getElementById("buy-sheet"),
    buySheetTitle: document.getElementById("buy-sheet-title"),
    buySheetMeta: document.getElementById("buy-sheet-meta"),
    buySheetX: document.getElementById("buy-sheet-x"),
    buyAmount: document.getElementById("buy-amount"),
    buyBalanceHint: document.getElementById("buy-balance-hint"),
    buyPreview: document.getElementById("buy-preview"),
    buySlide: document.getElementById("buy-slide"),
    buySlideFill: document.getElementById("buy-slide-fill"),
    buySlideLabel: document.getElementById("buy-slide-label"),
    buySlideThumb: document.getElementById("buy-slide-thumb"),
    kalshiLink: null,
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
  let lastSettlementSide = null;
  let lastSettlementMode = false;
  let lastThinBook = false;
  let closeTimeIso = null;
  let lastBestSideKey = null;
  let bestSideFlashTimer = null;
  let lastBestPick = null; // { side } | null when clear edge
  let lastClearEdgeAlertKey = null;
  let lastClearEdgeAlertAt = 0;
  let settleHintByTicker = {};
  let optionsOpen = false;
  let buySheetOpen = false;
  let buySheetSide = null; // above | below
  let buySheetAmount = 50;
  let buySlideDragging = false;
  let buySlideStartX = 0;
  let buySlideProgress = 0;
  let buySlideMax = 0;
  let buyConfirming = false;
  let demo = loadDemoState();
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

  function loadDemoState() {
    const fallback = {
      on: false,
      start: DEMO_DEFAULT_START,
      balance: DEMO_DEFAULT_START,
      realizedPl: 0,
      position: null,
      lastResult: null,
    };
    try {
      const raw = localStorage.getItem(DEMO_KEY);
      if (!raw) return fallback;
      const parsed = JSON.parse(raw);
      return {
        on: !!parsed.on,
        start:
          Number.isFinite(parsed.start) && parsed.start > 0
            ? parsed.start
            : DEMO_DEFAULT_START,
        balance: Number.isFinite(parsed.balance) ? parsed.balance : DEMO_DEFAULT_START,
        realizedPl: Number.isFinite(parsed.realizedPl) ? parsed.realizedPl : 0,
        position: parsed.position && typeof parsed.position === "object" ? parsed.position : null,
        lastResult:
          parsed.lastResult && typeof parsed.lastResult === "object"
            ? parsed.lastResult
            : null,
      };
    } catch {
      return fallback;
    }
  }

  function saveDemoState() {
    try {
      localStorage.setItem(DEMO_KEY, JSON.stringify(demo));
    } catch {
      // ignore quota
    }
  }

  function openOptions() {
    optionsOpen = true;
    if (el.optionsSheet) el.optionsSheet.hidden = false;
    if (el.optionsBackdrop) el.optionsBackdrop.hidden = false;
    if (el.menuBtn) el.menuBtn.setAttribute("aria-expanded", "true");
    renderDemoUi();
  }

  function closeOptions() {
    optionsOpen = false;
    if (el.optionsSheet) el.optionsSheet.hidden = true;
    if (el.optionsBackdrop) el.optionsBackdrop.hidden = true;
    if (el.menuBtn) el.menuBtn.setAttribute("aria-expanded", "false");
  }

  function toggleOptions() {
    if (optionsOpen) closeOptions();
    else openOptions();
  }

  function renderTutorialStep() {
    const step = TUTORIAL_STEPS[tutorialIndex];
    if (!step) return;
    if (el.tutorialStepNum) el.tutorialStepNum.textContent = String(tutorialIndex + 1);
    if (el.tutorialStepTotal) el.tutorialStepTotal.textContent = String(TUTORIAL_STEPS.length);
    if (el.tutorialTitle) el.tutorialTitle.textContent = step.title;
    if (el.tutorialBody) el.tutorialBody.textContent = step.body;
    if (el.tutorialNext) {
      el.tutorialNext.textContent =
        tutorialIndex >= TUTORIAL_STEPS.length - 1 ? "Got it" : "Next";
    }
  }

  function openTutorial(fromStart) {
    closeOptions();
    dismissBuySheet();
    tutorialOpen = true;
    tutorialIndex = fromStart === false ? tutorialIndex : 0;
    if (el.tutorial) el.tutorial.hidden = false;
    if (el.tutorialBackdrop) el.tutorialBackdrop.hidden = false;
    renderTutorialStep();
  }

  function closeTutorial(markSeen) {
    tutorialOpen = false;
    if (el.tutorial) el.tutorial.hidden = true;
    if (el.tutorialBackdrop) el.tutorialBackdrop.hidden = true;
    if (markSeen) {
      try {
        localStorage.setItem(TUTORIAL_KEY, "1");
      } catch {
        // ignore
      }
    }
  }

  function nextTutorial() {
    if (tutorialIndex >= TUTORIAL_STEPS.length - 1) {
      closeTutorial(true);
      return;
    }
    tutorialIndex += 1;
    renderTutorialStep();
  }

  function getPositionBidCents(pos) {
    if (!pos) return null;
    const bid = pos.side === "above" ? lastRoiBids.above : lastRoiBids.below;
    if (bid != null && Number.isFinite(bid) && bid >= 1 && bid <= 99) {
      return Math.round(bid);
    }
    const ask = pos.side === "above" ? lastRoiAsks.above : lastRoiAsks.below;
    if (ask != null && Number.isFinite(ask) && ask >= 1 && ask <= 99) {
      return Math.round(ask);
    }
    return null;
  }

  function markOpenPosition(pos) {
    if (!pos) return null;
    const bidCents = getPositionBidCents(pos);
    const spotRaw = el.spotValue && el.spotValue.dataset.last;
    const spot = spotRaw != null ? Number(spotRaw) : null;
    const secs = secondsLeft();
    const marketAsk =
      pos.side === "above" ? lastRoiAsks.above : lastRoiAsks.below;
    const marketPct =
      pos.side === "above"
        ? lastYesPct
        : lastYesPct != null
          ? 100 - lastYesPct
          : null;
    const beat = pos.beat != null ? pos.beat : lastTarget;
    const delta =
      spot != null && Number.isFinite(spot) && beat != null && Number.isFinite(beat)
        ? spot - beat
        : null;
    const leadingSide =
      delta == null ? null : delta >= 0 ? "above" : "below";
    const settleNowWin = leadingSide != null && leadingSide === pos.side;
    const modelP =
      spot != null && beat != null ? modelProbAbove(spot, beat, secs) : null;
    const pWin =
      modelP == null ? null : pos.side === "above" ? modelP : 1 - modelP;

    const heldPlIfWin = Math.round((pos.contracts * 1 - pos.total) * 100) / 100;
    const heldPlIfLose = Math.round((0 - pos.total) * 100) / 100;
    const modelEvPl =
      pWin != null && Number.isFinite(pWin)
        ? Math.round((pWin * heldPlIfWin + (1 - pWin) * heldPlIfLose) * 100) / 100
        : null;

    if (bidCents == null) {
      return {
        bidCents: null,
        markValue: null,
        unrealized: null,
        unrealizedPct: null,
        exitFee: 0,
        proceeds: null,
        spot,
        beat,
        delta,
        secs,
        marketAsk,
        marketPct,
        settleNowWin,
        pWin,
        modelEvPl,
        heldWinPayout: pos.contracts * 1,
        heldPlIfWin,
        heldPlIfLose,
      };
    }
    const P = bidCents / 100;
    const gross = pos.contracts * P;
    const exitFee = kalshiTakerFee(pos.contracts, Math.min(0.99, Math.max(0.01, P)));
    const proceeds = Math.max(0, Math.round((gross - exitFee) * 100) / 100);
    const unrealized = Math.round((proceeds - pos.total) * 100) / 100;
    const unrealizedPct =
      pos.total > 0 ? Math.round((unrealized / pos.total) * 1000) / 10 : null;
    return {
      bidCents,
      markValue: Math.round(gross * 100) / 100,
      unrealized,
      unrealizedPct,
      exitFee,
      proceeds,
      spot,
      beat,
      delta,
      secs,
      marketAsk,
      marketPct,
      settleNowWin,
      pWin,
      modelEvPl,
      heldWinPayout: pos.contracts * 1,
      heldPlIfWin,
      heldPlIfLose,
    };
  }

  function markDemoPosition() {
    return markOpenPosition(demo.position);
  }

  function formatPl(n) {
    if (n == null || !Number.isFinite(n)) return "—";
    const sign = n > 0 ? "+" : "";
    return `${sign}${money(n)}`;
  }

  function factorCell(label, value, span2) {
    return (
      `<div class="demo-live-factor${span2 ? " span2" : ""}">` +
      `<span class="fk">${label}</span>` +
      `<span class="fv">${value}</span></div>`
    );
  }

  function sessionPlBreakdown(mark) {
    const realized = Number(demo.realizedPl) || 0;
    const open =
      mark && mark.unrealized != null && Number.isFinite(mark.unrealized)
        ? mark.unrealized
        : 0;
    const total = Math.round((realized + open) * 100) / 100;
    return { realized, open, total, hasOpen: !!(demo.position && mark) };
  }

  function renderOpenPlBar(pos, mark) {
    if (!el.openPlBar) return;
    if (!pos) {
      el.openPlBar.hidden = true;
      document.body.classList.remove("has-open-pl");
      return;
    }
    el.openPlBar.hidden = false;
    document.body.classList.add("has-open-pl");
    const side = pos.side === "above" ? "Above" : "Below";
    const accounted = pos.accounted !== false && demo.on;
    const sess = sessionPlBreakdown(mark);
    if (el.openPlSide) {
      el.openPlSide.textContent = `Buy ${side} · ${pos.contracts} cts @ ${pos.askCents}¢`;
      el.openPlSide.classList.toggle("is-up", pos.side === "above");
      el.openPlSide.classList.toggle("is-down", pos.side === "below");
    }
    if (el.openPlValue) {
      el.openPlValue.textContent =
        mark && mark.unrealized != null ? formatPl(mark.unrealized) : "—";
      el.openPlValue.classList.toggle(
        "is-up",
        !!(mark && mark.unrealized > 0)
      );
      el.openPlValue.classList.toggle(
        "is-down",
        !!(mark && mark.unrealized < 0)
      );
    }
    if (el.openPlSub) {
      const bits = [];
      if (mark && mark.bidCents != null) bits.push(`bid ${mark.bidCents}¢`);
      if (mark && mark.unrealizedPct != null) {
        const sign = mark.unrealizedPct > 0 ? "+" : "";
        bits.push(`${sign}${mark.unrealizedPct.toFixed(1)}%`);
      }
      if (mark && mark.modelEvPl != null) {
        bits.push(`EV ${formatPl(mark.modelEvPl)}`);
      }
      if (mark && mark.pWin != null) {
        bits.push(`${Math.round(mark.pWin * 100)}% win`);
      }
      if (mark && mark.delta != null) {
        bits.push(
          `${mark.delta >= 0 ? "+" : ""}$${mark.delta.toFixed(0)} vs beat`
        );
      }
      if (mark && mark.secs != null) {
        bits.push(
          `${Math.floor(mark.secs / 60)}:${String(mark.secs % 60).padStart(2, "0")} left`
        );
      }
      if (mark && mark.settleNowWin != null) {
        bits.push(mark.settleNowWin ? "winning now" : "losing now");
      }
      bits.push(`session ${formatPl(sess.total)}`);
      el.openPlSub.textContent = bits.join(" · ");
    }
    if (el.openPlClose) {
      el.openPlClose.disabled = !mark || mark.bidCents == null;
      el.openPlClose.textContent = accounted
        ? "Close at bid · post P/L"
        : "Close at bid · clear mark";
    }
  }

  function renderOpenPositionUi() {
    const pos = demo.position;
    const mark = markOpenPosition(pos);
    renderOpenPlBar(pos, mark);
    // Keep the chart clear: factor card lives in Options / bottom strip, not summary.
    if (el.demoLive) el.demoLive.hidden = true;
    return mark;
  }

  function renderDemoUi() {
    if (el.menuBtn) el.menuBtn.classList.toggle("is-demo", !!demo.on);
    if (el.demoToggle) el.demoToggle.checked = !!demo.on;
    if (el.demoAccount) el.demoAccount.hidden = !demo.on;
    if (el.demoStart && document.activeElement !== el.demoStart) {
      el.demoStart.value = String(Math.round(demo.start));
    }
    if (el.demoBalance) el.demoBalance.textContent = money(demo.balance);
    if (el.demoPl) {
      const markPreview = markOpenPosition(demo.position);
      const sess = sessionPlBreakdown(markPreview);
      if (sess.hasOpen) {
        el.demoPl.textContent =
          `Session ${formatPl(sess.total)} · realized ${formatPl(
            sess.realized
          )} · open ${formatPl(sess.open)}`;
      } else {
        el.demoPl.textContent = `Session P/L ${formatPl(sess.realized)}`;
      }
      el.demoPl.classList.toggle("is-up", sess.total > 0);
      el.demoPl.classList.toggle("is-down", sess.total < 0);
    }

    const pos = demo.position;
    const mark = renderOpenPositionUi();

    if (el.demoPosition) {
      if (!pos) {
        el.demoPosition.textContent = "Flat";
      } else {
        const side = pos.side === "above" ? "Above" : "Below";
        el.demoPosition.textContent =
          `Buy ${side} · ${pos.contracts} cts @ ${pos.askCents}¢ · paid ${money(pos.total)}`;
      }
    }

    if (el.demoMark) el.demoMark.hidden = !pos;
    if (el.demoClose) el.demoClose.hidden = !pos;
    if (pos && mark) {
      if (el.demoMarkPl) {
        el.demoMarkPl.textContent =
          mark.unrealized == null
            ? "Mark —"
            : `Open P/L ${formatPl(mark.unrealized)}`;
        el.demoMarkPl.classList.toggle("is-up", mark.unrealized > 0);
        el.demoMarkPl.classList.toggle("is-down", mark.unrealized < 0);
      }
      if (el.demoMarkMeta) {
        const timeTxt =
          mark.secs != null
            ? `${Math.floor(mark.secs / 60)}:${String(mark.secs % 60).padStart(2, "0")} left`
            : "— left";
        const deltaTxt =
          mark.delta != null
            ? `live ${mark.delta >= 0 ? "+" : ""}$${mark.delta.toFixed(0)} vs beat`
            : "live —";
        el.demoMarkMeta.textContent =
          mark.bidCents == null
            ? `Waiting for bid · ${deltaTxt} · ${timeTxt}`
            : `Bid ${mark.bidCents}¢ · exit ~${money(mark.proceeds)} · ${deltaTxt} · ${timeTxt}`;
      }
    }

    if (el.demoLast) {
      const r = demo.lastResult;
      el.demoLast.classList.remove("is-win", "is-loss");
      if (!r) {
        el.demoLast.textContent = "No trades yet";
      } else {
        el.demoLast.textContent = r.text;
        el.demoLast.classList.toggle("is-win", !!r.won);
        el.demoLast.classList.toggle("is-loss", !r.won);
      }
    }
    const busy = !!demo.position;
    if (el.demoBuyBest) el.demoBuyBest.disabled = busy;
    if (el.demoBuyAbove) el.demoBuyAbove.disabled = !demo.on || busy;
    if (el.demoBuyBelow) el.demoBuyBelow.disabled = !demo.on || busy;
    if (el.demoClose) el.demoClose.disabled = !pos || !mark || mark.bidCents == null;
    syncBuyDock();
  }

  function closeDemoPosition() {
    const pos = demo.position;
    if (!pos) return;
    const mark = markOpenPosition(pos);
    if (!mark || mark.bidCents == null || mark.proceeds == null) {
      setStatus("warn", "No live bid to close against");
      return;
    }
    const pl = mark.unrealized;
    const accounted = pos.accounted !== false && demo.on;
    if (accounted) {
      demo.balance = Math.round((demo.balance + mark.proceeds) * 100) / 100;
      demo.realizedPl = Math.round((demo.realizedPl + pl) * 100) / 100;
    }
    const sideLabel = pos.side === "above" ? "Above" : "Below";
    const won = pl >= 0;
    demo.lastResult = {
      won,
      pl,
      side: pos.side,
      ticker: pos.ticker,
      text: accounted
        ? `CLOSED ${sideLabel} @ ${mark.bidCents}¢ · ${formatPl(pl)} · bal ${money(
            demo.balance
          )}`
        : `CLOSED ${sideLabel} @ ${mark.bidCents}¢ · ${formatPl(pl)} · paper`,
    };
    demo.position = null;
    saveDemoState();
    renderDemoUi();
    setStatus(won ? "ok" : "warn", demo.lastResult.text);
  }

  function setDemoOn(on) {
    demo.on = !!on;
    saveDemoState();
    renderDemoUi();
    setStatus("ok", demo.on ? "Demo on" : "Demo off");
  }

  function resetDemoAccount() {
    let start = Number(el.demoStart && el.demoStart.value);
    if (!Number.isFinite(start) || start < 10) start = DEMO_DEFAULT_START;
    start = Math.min(100000, Math.round(start));
    demo.start = start;
    demo.balance = start;
    demo.realizedPl = 0;
    demo.position = null;
    demo.lastResult = null;
    saveDemoState();
    renderDemoUi();
    setStatus("ok", `Demo reset · ${money(start)}`);
  }

  function demoBuy(side, amountUsd) {
    if (demo.position) {
      setStatus("warn", "Already in an open position");
      return false;
    }
    const stake = amountUsd != null ? Number(amountUsd) : tradeStake;
    if (!(stake > 0)) {
      setStatus("warn", "Enter a dollar amount");
      return false;
    }
    if (!lastTicker || lastTarget == null) {
      setStatus("warn", "Wait for a live window");
      return false;
    }
    const ask = side === "above" ? lastRoiAsks.above : lastRoiAsks.below;
    const sized = roiForStake(ask, stake);
    if (!sized || sized.empty) {
      setStatus("warn", "Need a live ask");
      return false;
    }
    const accounted = !!demo.on;
    if (accounted && sized.total > demo.balance + 1e-9) {
      setStatus("warn", "Not enough demo balance");
      return false;
    }
    if (accounted) {
      demo.balance = Math.round((demo.balance - sized.total) * 100) / 100;
    }
    demo.position = {
      ticker: lastTicker,
      side,
      askCents: sized.askCents,
      contracts: sized.contracts,
      cost: sized.cost,
      fee: sized.fee,
      total: sized.total,
      beat: lastTarget,
      openedAt: Date.now(),
      accounted,
    };
    // Keep main trade-size slider in sync for Best Side sizing.
    if (stake <= 100) setTradeStake(Math.round(stake));
    saveDemoState();
    renderDemoUi();
    setStatus(
      "ok",
      accounted
        ? `Demo bought ${side === "above" ? "Above" : "Below"} · ${sized.contracts} cts`
        : `Paper bought ${side === "above" ? "Above" : "Below"} · rolling P/L on`
    );
    return true;
  }

  function readBuyAmount() {
    let n = Number(el.buyAmount && el.buyAmount.value);
    if (!Number.isFinite(n)) n = buySheetAmount;
    const cap = demo.on
      ? Math.max(1, Math.floor(demo.balance) || 1)
      : 100000;
    n = Math.max(1, Math.min(cap, Math.round(n)));
    buySheetAmount = n;
    return n;
  }

  function refreshBuySheetPreview() {
    if (!buySheetOpen || !buySheetSide) return;
    const side = buySheetSide;
    const amount = readBuyAmount();
    const ask = side === "above" ? lastRoiAsks.above : lastRoiAsks.below;
    const sized = roiForStake(ask, amount);
    if (el.buyBalanceHint) {
      el.buyBalanceHint.textContent = demo.on
        ? `Bal ${money(demo.balance)}`
        : "Paper · rolling P/L";
    }
    if (el.buySheetMeta) {
      const askTxt = ask != null ? `${Math.round(ask)}¢ ask` : "ask —";
      el.buySheetMeta.textContent =
        `${side === "above" ? "Above" : "Below"} · ${askTxt} · live Kalshi book`;
    }
    if (el.buyPreview) {
      if (!sized || sized.empty) {
        el.buyPreview.textContent = "Enter an amount to preview contracts + fees";
      } else {
        el.buyPreview.textContent =
          `${sized.contracts} contracts · cost ${money(sized.cost)} + fee ${money(
            sized.fee
          )} · total ${money(sized.total)} · win ${money(sized.profitIfWin)} (${
            sized.roiIfWin != null
              ? `${sized.roiIfWin >= 0 ? "+" : ""}${sized.roiIfWin.toFixed(0)}%`
              : "—"
          })`;
      }
    }
    if (el.buySlideLabel && !buyConfirming) {
      const label = side === "above" ? "Slide to buy Above" : "Slide to buy Below";
      el.buySlideLabel.textContent = label;
    }
  }

  function setBuySlideProgress(pct) {
    buySlideProgress = Math.max(0, Math.min(1, pct));
    const thumbTravel = Math.max(0, buySlideMax);
    const x = buySlideProgress * thumbTravel;
    if (el.buySlideThumb) {
      el.buySlideThumb.style.transform = `translateX(${x}px)`;
    }
    if (el.buySlideFill) {
      el.buySlideFill.style.width = `${Math.max(
        0,
        ((x + 48) / Math.max(1, (el.buySlide && el.buySlide.clientWidth) || 1)) * 100
      )}%`;
    }
    if (el.buySlide) {
      el.buySlide.setAttribute("aria-valuenow", String(Math.round(buySlideProgress * 100)));
    }
  }

  function resetBuySlide() {
    buySlideDragging = false;
    buyConfirming = false;
    if (el.buySlide) el.buySlide.classList.remove("is-complete");
    setBuySlideProgress(0);
    refreshBuySheetPreview();
  }

  function measureBuySlide() {
    if (!el.buySlide || !el.buySlideThumb) {
      buySlideMax = 0;
      return;
    }
    buySlideMax = Math.max(0, el.buySlide.clientWidth - el.buySlideThumb.offsetWidth - 8);
  }

  function openBuySheet(side) {
    if (demo.position) {
      setStatus("warn", "Already in an open position");
      return;
    }
    if (side !== "above" && side !== "below") return;
    const ask = side === "above" ? lastRoiAsks.above : lastRoiAsks.below;
    if (ask == null || !(ask >= 1 && ask <= 99)) {
      setStatus("warn", "Need a live ask");
      return;
    }
    closeOptions();
    buySheetSide = side;
    buySheetOpen = true;
    const cap = demo.on
      ? Math.max(1, Math.floor(demo.balance) || 50)
      : 100;
    buySheetAmount = Math.max(
      1,
      Math.min(cap, tradeStake > 0 ? tradeStake : 50)
    );
    if (el.buyAmount) el.buyAmount.value = String(buySheetAmount);
    if (el.buySheet) {
      el.buySheet.hidden = false;
      el.buySheet.classList.remove("is-done");
      el.buySheet.classList.toggle("is-below", side === "below");
    }
    if (el.buyBackdrop) el.buyBackdrop.hidden = false;
    if (el.buySheetTitle) {
      el.buySheetTitle.textContent = side === "above" ? "Buy Above" : "Buy Below";
    }
    const kicker = document.querySelector(".buy-sheet-kicker");
    if (kicker) {
      kicker.textContent = demo.on ? "Demo order" : "Paper order · rolling P/L";
    }
    resetBuySlide();
    requestAnimationFrame(() => {
      measureBuySlide();
      setBuySlideProgress(0);
      refreshBuySheetPreview();
    });
  }

  function dismissBuySheet(afterMs) {
    const finish = () => {
      buySheetOpen = false;
      buySheetSide = null;
      buyConfirming = false;
      if (el.buySheet) {
        el.buySheet.hidden = true;
        el.buySheet.classList.remove("is-done", "is-below");
      }
      if (el.buyBackdrop) el.buyBackdrop.hidden = true;
      resetBuySlide();
    };
    if (afterMs && el.buySheet && buySheetOpen) {
      el.buySheet.classList.add("is-done");
      setTimeout(finish, afterMs);
    } else {
      finish();
    }
  }

  function confirmBuyFromSheet() {
    if (buyConfirming || !buySheetSide) return;
    buyConfirming = true;
    if (el.buySlide) el.buySlide.classList.add("is-complete");
    if (el.buySlideLabel) el.buySlideLabel.textContent = "Bought";
    setBuySlideProgress(1);
    const ok = demoBuy(buySheetSide, readBuyAmount());
    if (!ok) {
      buyConfirming = false;
      if (el.buySlide) el.buySlide.classList.remove("is-complete");
      resetBuySlide();
      return;
    }
    dismissBuySheet(380);
  }

  function onBuySlidePointerDown(ev) {
    if (!buySheetOpen || buyConfirming) return;
    measureBuySlide();
    buySlideDragging = true;
    const point = ev.touches ? ev.touches[0] : ev;
    buySlideStartX = point.clientX - buySlideProgress * buySlideMax;
    if (el.buySlide && el.buySlide.setPointerCapture && ev.pointerId != null) {
      try {
        el.buySlide.setPointerCapture(ev.pointerId);
      } catch {
        // ignore
      }
    }
    ev.preventDefault();
  }

  function onBuySlidePointerMove(ev) {
    if (!buySlideDragging || buyConfirming) return;
    const point = ev.touches ? ev.touches[0] : ev;
    const x = point.clientX - buySlideStartX;
    setBuySlideProgress(buySlideMax > 0 ? x / buySlideMax : 0);
    ev.preventDefault();
  }

  function onBuySlidePointerUp(ev) {
    if (!buySlideDragging) return;
    buySlideDragging = false;
    if (buySlideProgress >= 0.92) {
      confirmBuyFromSheet();
    } else {
      setBuySlideProgress(0);
    }
    if (ev && el.buySlide && el.buySlide.releasePointerCapture && ev.pointerId != null) {
      try {
        el.buySlide.releasePointerCapture(ev.pointerId);
      } catch {
        // ignore
      }
    }
  }

  function demoBuyBest() {
    if (!lastBestPick || !lastBestPick.side) {
      setStatus("warn", "No clear Best Side yet");
      return;
    }
    openBuySheet(lastBestPick.side);
  }

  function resolveOutcomeForTicker(ticker, beatHint) {
    const hinted = settleHintByTicker[ticker];
    if (hinted === "above" || hinted === "below") return hinted;
    if (lastSettlementSide === "above" || lastSettlementSide === "below") {
      if (!ticker || ticker === lastTicker) return lastSettlementSide;
    }
    const spotRaw = el.spotValue && el.spotValue.dataset.last;
    const spot = spotRaw != null ? Number(spotRaw) : null;
    const beat =
      beatHint != null && Number.isFinite(beatHint)
        ? beatHint
        : lastTarget;
    if (spot != null && Number.isFinite(spot) && beat != null && Number.isFinite(beat)) {
      return spot >= beat ? "above" : "below";
    }
    return null;
  }

  function settleDemoPosition(tickerJustClosed) {
    const pos = demo.position;
    if (!pos) return;
    if (tickerJustClosed && pos.ticker && pos.ticker !== tickerJustClosed) return;
    const outcome = resolveOutcomeForTicker(pos.ticker, pos.beat);
    if (!outcome) return;
    const won = outcome === pos.side;
    const payout = won ? pos.contracts * 1 : 0;
    const pl = Math.round((payout - pos.total) * 100) / 100;
    const accounted = pos.accounted !== false && demo.on;
    if (accounted) {
      demo.balance = Math.round((demo.balance + payout) * 100) / 100;
      demo.realizedPl = Math.round((demo.realizedPl + pl) * 100) / 100;
    }
    const sideLabel = pos.side === "above" ? "Above" : "Below";
    demo.lastResult = {
      won,
      pl,
      side: pos.side,
      ticker: pos.ticker,
      text: accounted
        ? won
          ? `WIN ${sideLabel} · ${money(pl)} · bal ${money(demo.balance)}`
          : `LOSS ${sideLabel} · ${money(pl)} · bal ${money(demo.balance)}`
        : won
          ? `WIN ${sideLabel} · ${money(pl)} · paper`
          : `LOSS ${sideLabel} · ${money(pl)} · paper`,
    };
    demo.position = null;
    saveDemoState();
    renderDemoUi();
    setStatus(won ? "ok" : "warn", demo.lastResult.text);
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

  /** Distinct ascending chime for clear-edge Best Side. */
  function playEdgeChime(force) {
    if (!chimeOn && !force) return;
    const ctx = ensureAudio();
    if (!ctx) return;
    const now = ctx.currentTime;
    const tones = [
      { f: 740, t: 0.0, d: 0.12 },
      { f: 988, t: 0.11, d: 0.14 },
      { f: 1319, t: 0.24, d: 0.28 },
    ];
    for (const tone of tones) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.value = tone.f;
      gain.gain.setValueAtTime(0.0001, now + tone.t);
      gain.gain.exponentialRampToValueAtTime(0.2, now + tone.t + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + tone.t + tone.d);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now + tone.t);
      osc.stop(now + tone.t + tone.d + 0.02);
    }
    if (navigator.vibrate) {
      try {
        navigator.vibrate([30, 40, 30, 40, 90]);
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
      const reg = await navigator.serviceWorker.register("/sw.js?v=2.7", { scope: "/" });
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
    el.pushBadge.title = on
      ? "Alerts on — new targets + clear edge"
      : "Alerts off — tap to turn on";
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

  function alertClearEdge(best) {
    if (!best || !best.side) return;
    if (!chimeOn) return;
    // Already in a trade — don't spam; UI still updates.
    if (demo.position) return;

    const side = best.side;
    const ask = Math.round(Number(best.askCents) || 0);
    const conf = best.pWin != null ? Math.round(best.pWin * 100) : null;
    const alertKey = `${side}:${ask}`;
    const now = Date.now();
    const prev = lastClearEdgeAlertKey;
    const sideChanged = prev && prev !== "none" && !String(prev).startsWith(`${side}:`);
    const newlyClear = !prev || prev === "none";
    const askMoved =
      prev &&
      String(prev).startsWith(`${side}:`) &&
      Math.abs(Number(String(prev).split(":")[1]) - ask) >= 3;
    const cooled = now - lastClearEdgeAlertAt > 75_000;

    if (!(newlyClear || sideChanged || (askMoved && cooled))) {
      return;
    }

    lastClearEdgeAlertKey = alertKey;
    lastClearEdgeAlertAt = now;
    ensureAudio();
    playEdgeChime();
    const sideLabel = side === "above" ? "Above" : "Below";
    setStatus(
      "ok",
      `Clear edge · Buy ${sideLabel}${ask ? ` @ ${ask}¢` : ""}`
    );
    postToSW({
      type: "edge-notify",
      side,
      askCents: ask || null,
      pWin: best.pWin,
      ticker: lastTicker || lastFifteenTicker,
      beat: lastTarget,
    });
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
  let lastRoiBids = { above: null, below: null };
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

  /** Standard normal CDF (Abramowitz & Stegun 26.2.17). */
  function normalCdf(x) {
    if (!Number.isFinite(x)) return 0.5;
    const sign = x < 0 ? -1 : 1;
    const z = Math.abs(x) / Math.SQRT2;
    const t = 1 / (1 + 0.3275911 * z);
    const a1 = 0.254829592;
    const a2 = -0.284496736;
    const a3 = 1.421413741;
    const a4 = -1.453152027;
    const a5 = 1.061405429;
    const erf =
      1 -
      ((((a5 * t + a4) * t + a3) * t + a2) * t + a1) * t * Math.exp(-z * z);
    return 0.5 * (1 + sign * erf);
  }

  /**
   * Model P(Above) from live vs beat and time left.
   * Uses ~55% annualized BTC vol; settlement mode trusts the running avg.
   */
  function modelProbAbove(spot, beat, secsLeft) {
    if (spot == null || beat == null || !Number.isFinite(spot) || !Number.isFinite(beat)) {
      return null;
    }
    if (lastSettlementMode && lastSettlementSide === "above") return 0.97;
    if (lastSettlementMode && lastSettlementSide === "below") return 0.03;
    if (lastSettlementMode && lastSettlementAvg != null && Number.isFinite(lastSettlementAvg)) {
      const d = lastSettlementAvg - beat;
      // Soft settle lean while samples accumulate.
      return normalCdf(d / Math.max(8, Math.abs(beat) * 0.00015));
    }
    const t = Math.max(1, Number(secsLeft) || 1);
    // Dollar sigma over remaining window (~55% ann. vol), floored for noise.
    const sigma = Math.max(
      8,
      Math.abs(beat) * 0.55 * Math.sqrt(t / (365.25 * 24 * 3600))
    );
    return normalCdf((spot - beat) / sigma);
  }

  function scoreSide(side, askCents, modelProb, stakeUsd) {
    if (askCents == null || modelProb == null || !Number.isFinite(modelProb)) {
      return null;
    }
    const sized = roiForStake(askCents, Math.max(1, stakeUsd || 1));
    if (!sized) return null;
    const bought = stakeUsd > 0 ? roiForStake(askCents, stakeUsd) : null;
    const pWin = side === "above" ? modelProb : 1 - modelProb;
    const costPer = sized.total / Math.max(1, sized.contracts);
    const ev = pWin * 1 - costPer;
    const risk = Math.max(0.04, 1 - pWin);
    return {
      side,
      askCents: sized.askCents,
      pWin,
      ev,
      risk,
      score: ev / risk,
      roiIfWin: bought && !bought.empty ? bought.roiIfWin : sized.roiIfWin,
      contracts: bought && !bought.empty ? bought.contracts : 0,
      total: bought && !bought.empty ? bought.total : 0,
      profitIfWin: bought && !bought.empty ? bought.profitIfWin : 0,
    };
  }

  function secondsLeft() {
    if (!closeTimeIso) return null;
    const end = Date.parse(closeTimeIso);
    if (!Number.isFinite(end)) return null;
    return Math.max(0, Math.floor((end - Date.now()) / 1000));
  }

  function flashBestSide() {
    if (!el.bestSide) return;
    el.bestSide.classList.remove("is-flash");
    // Restart CSS animation.
    void el.bestSide.offsetWidth;
    el.bestSide.classList.add("is-flash");
    if (bestSideFlashTimer) clearTimeout(bestSideFlashTimer);
    bestSideFlashTimer = setTimeout(() => {
      if (el.bestSide) el.bestSide.classList.remove("is-flash");
    }, 1200);
  }

  function setRoiCardBest(side) {
    const above = document.querySelector(".roi-card.above");
    const below = document.querySelector(".roi-card.below");
    if (above) above.classList.toggle("is-best", side === "above");
    if (below) below.classList.toggle("is-best", side === "below");
  }

  function setDockBestDetail(text, side) {
    if (el.dockBestDetail) el.dockBestDetail.textContent = text || "—";
    if (el.dockBuyBest) {
      el.dockBuyBest.classList.toggle("is-above", side === "above");
      el.dockBuyBest.classList.toggle("is-below", side === "below");
      el.dockBuyBest.classList.toggle("is-none", !side);
    }
  }

  function refreshBestSide() {
    if (!el.bestSide) return;
    const spotRaw = el.spotValue && el.spotValue.dataset.last;
    const spot = spotRaw != null ? Number(spotRaw) : null;
    const beat = lastTarget;
    const secs = secondsLeft();
    const aboveAsk = lastRoiAsks.above;
    const belowAsk = lastRoiAsks.below;

    if (
      spot == null ||
      !Number.isFinite(spot) ||
      beat == null ||
      !Number.isFinite(beat) ||
      secs == null ||
      (aboveAsk == null && belowAsk == null)
    ) {
      el.bestSide.hidden = true;
      setRoiCardBest(null);
      setDockBestDetail("—", null);
      lastBestSideKey = null;
      lastBestPick = null;
      lastClearEdgeAlertKey = "none";
      return;
    }

    const modelP = modelProbAbove(spot, beat, secs);
    const scored = [];
    const a = scoreSide("above", aboveAsk, modelP, tradeStake);
    const b = scoreSide("below", belowAsk, modelP, tradeStake);
    if (a) scored.push(a);
    if (b) scored.push(b);
    if (!scored.length) {
      el.bestSide.hidden = true;
      setRoiCardBest(null);
      setDockBestDetail("—", null);
      lastBestPick = null;
      lastClearEdgeAlertKey = "none";
      return;
    }

    scored.sort((x, y) => y.score - x.score);
    let best = scored[0];
    // Haircut noisy/thin books and early-window coin flips with tiny edge.
    if (lastThinBook) best = { ...best, score: best.score - 0.08 };
    const clear =
      best.ev > 0.01 &&
      best.score > 0.04 &&
      best.pWin >= 0.52 &&
      !(secs > 12 * 60 && Math.abs(best.ev) < 0.03);

    el.bestSide.hidden = false;
    el.bestSide.classList.toggle("is-below", clear && best.side === "below");
    el.bestSide.classList.toggle("is-none", !clear);
    el.bestSide.classList.toggle("is-above", clear && best.side === "above");

    if (!clear) {
      if (el.bestSideLabel) el.bestSideLabel.textContent = "No clear edge";
      if (el.bestSideAmount) {
        el.bestSideAmount.textContent =
          tradeStake > 0 ? `Holding $${tradeStake}` : "Set a trade size";
      }
      if (el.bestSideMeta) {
        const lead = spot - beat;
        const mAbove = modelP != null ? Math.round(modelP * 100) : null;
        el.bestSideMeta.textContent =
          `Live ${lead >= 0 ? "+" : ""}$${lead.toFixed(0)} · model Above ${
            mAbove != null ? mAbove + "%" : "—"
          } · ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")} left · wait for better ask`;
      }
      setRoiCardBest(null);
      setDockBestDetail("Wait", null);
      lastBestPick = null;
      const noneKey = "none";
      if (lastBestSideKey !== noneKey) {
        lastBestSideKey = noneKey;
        flashBestSide();
      }
      lastClearEdgeAlertKey = "none";
      return;
    }

    lastBestPick = { side: best.side, askCents: best.askCents, pWin: best.pWin };
    const label = best.side === "above" ? "BUY ABOVE" : "BUY BELOW";
    if (el.bestSideLabel) el.bestSideLabel.textContent = label;
    if (el.bestSideAmount) {
      if (tradeStake <= 0) {
        el.bestSideAmount.textContent = "Set a trade size";
      } else {
        el.bestSideAmount.textContent = `Buy $${tradeStake} · ${best.contracts} contract${
          best.contracts === 1 ? "" : "s"
        }`;
      }
    }
    if (el.bestSideMeta) {
      const roiTxt =
        best.roiIfWin != null
          ? `${best.roiIfWin >= 0 ? "+" : ""}${best.roiIfWin.toFixed(0)}% if win`
          : "";
      const conf = Math.round(best.pWin * 100);
      const m = Math.floor(secs / 60);
      const s = secs % 60;
      const lead = spot - beat;
      el.bestSideMeta.textContent =
        `${conf}% model · ask ${best.askCents}¢ · ${roiTxt} · live ${
          lead >= 0 ? "+" : ""
        }$${lead.toFixed(0)} · ${m}:${String(s).padStart(2, "0")} left`;
    }
    setRoiCardBest(best.side);
    setDockBestDetail(
      `${best.side === "above" ? "Above" : "Below"} ${best.askCents}¢`,
      best.side
    );

    const key = clear
      ? `${best.side}:${tradeStake}:${best.contracts}`
      : "none";
    if (key !== lastBestSideKey) {
      lastBestSideKey = key;
      flashBestSide();
    }
    alertClearEdge(best);
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
    refreshBestSide();
    renderDemoUi();
    syncBuyDock();
  }

  function syncBuyDock() {
    const busy = !!demo.position;
    if (el.dockAbovePct) {
      el.dockAbovePct.textContent =
        lastRoiAsks.above != null ? `${Math.round(lastRoiAsks.above)}¢` : "—";
    }
    if (el.dockBelowPct) {
      el.dockBelowPct.textContent =
        lastRoiAsks.below != null ? `${Math.round(lastRoiAsks.below)}¢` : "—";
    }
    if (el.dockBuyAbove) el.dockBuyAbove.disabled = busy;
    if (el.dockBuyBelow) el.dockBuyBelow.disabled = busy;
    if (el.dockBuyBest) el.dockBuyBest.disabled = busy;
  }

  function setTradeStake(n) {
    tradeStake = Math.max(0, Math.min(100, Math.round(Number(n) || 0)));
    localStorage.setItem(STAKE_KEY, String(tradeStake));
    renderRoi();
  }

  function updateRoi(data) {
    let aboveAsk = data && data.yes_ask_pct;
    let belowAsk = data && data.no_ask_pct;
    let aboveBid = data && data.yes_bid_pct;
    let belowBid = data && data.no_bid_pct;
    if (aboveAsk == null && data && data.yes_pct != null) aboveAsk = data.yes_pct;
    if (belowAsk == null && data && data.no_pct != null) belowAsk = data.no_pct;
    if (belowAsk == null && data && data.yes_bid_pct != null) {
      belowAsk = Math.max(1, 100 - data.yes_bid_pct);
    }
    if (aboveAsk == null && data && data.no_bid_pct != null) {
      aboveAsk = Math.max(1, 100 - data.no_bid_pct);
    }
    // Reject locked/extreme asks (settlement 0–1¢) — prefer mid %.
    const usable = (c) => c != null && Number.isFinite(c) && c >= 1 && c <= 99;
    const midOk = (c) => usable(c) && c >= 5 && c <= 95;
    if ((!usable(aboveAsk) || (aboveAsk <= 2 && midOk(data && data.yes_pct))) && usable(data && data.yes_pct)) {
      aboveAsk = data.yes_pct;
    }
    if ((!usable(belowAsk) || (belowAsk <= 2 && midOk(data && data.no_pct))) && usable(data && data.no_pct)) {
      belowAsk = data.no_pct;
    }
    if (!usable(aboveAsk)) aboveAsk = null;
    if (!usable(belowAsk)) belowAsk = null;
    if (aboveBid == null && data && data.yes_pct != null) {
      aboveBid = Math.max(1, Math.round(data.yes_pct) - 1);
    }
    if (belowBid == null && data && data.no_pct != null) {
      belowBid = Math.max(1, Math.round(data.no_pct) - 1);
    }
    if (belowBid == null && aboveAsk != null) {
      belowBid = Math.max(1, 100 - aboveAsk);
    }
    if (aboveBid == null && belowAsk != null) {
      aboveBid = Math.max(1, 100 - belowAsk);
    }
    if (!usable(aboveBid)) aboveBid = aboveAsk != null ? Math.max(1, aboveAsk - 1) : null;
    if (!usable(belowBid)) belowBid = belowAsk != null ? Math.max(1, belowAsk - 1) : null;
    lastRoiAsks = { above: aboveAsk, below: belowAsk };
    lastRoiBids = { above: aboveBid, below: belowBid };
    renderRoi();
    if (buySheetOpen) refreshBuySheetPreview();
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
      if (el.bestSide) el.bestSide.hidden = true;
      setRoiCardBest(null);
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
    lastThinBook = !!(data && data.thin_book);
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
    lastSettlementMode = mode;
    lastSettlementSide = (data && data.settlement_side) || null;
    if (
      lastTicker &&
      (lastSettlementSide === "above" || lastSettlementSide === "below")
    ) {
      settleHintByTicker[lastTicker] = lastSettlementSide;
    }
    if (!mode) {
      el.settleBanner.hidden = true;
      el.settleBanner.classList.remove("is-above", "is-below");
      lastSettlementAvg = null;
      applySettleLine(null);
      refreshBestSide();
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
    refreshBestSide();
    if (demo.position) renderDemoUi();
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
    refreshBestSide();
    if (demo.position) renderDemoUi();
  }

  function updateCountdown() {
    if (!el.countdown) return;
    if (!closeTimeIso) {
      el.countdown.textContent = "—:—";
      el.countdown.classList.remove("urgent");
      if (el.countdownMeta) el.countdownMeta.textContent = "Until this 15m window ends";
      refreshBestSide();
      return;
    }
    const end = Date.parse(closeTimeIso);
    if (!Number.isFinite(end)) {
      el.countdown.textContent = "—:—";
      refreshBestSide();
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
      refreshBestSide();
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
    refreshBestSide();
    if (demo.position) renderDemoUi();
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
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.08)",
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.08)",
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: true,
      },
      handleScale: {
        axisPressedMouseMove: true,
        axisDoubleClickReset: true,
        mouseWheel: true,
        pinch: true,
      },
    });
    series = chart.addCandlestickSeries({
      upColor: "#1ac96b",
      downColor: "#d45454",
      borderVisible: false,
      wickUpColor: "#1ac96b",
      wickDownColor: "#d45454",
      // Keep Price to beat (and settle avg) inside the visible scale.
      autoscaleInfoProvider: (original) => {
        const res = original();
        if (!res) return res;
        const extras = [lastTarget, lastSettlementAvg].filter(
          (v) => v != null && Number.isFinite(v)
        );
        if (!extras.length) return res;
        let min = res.priceRange ? res.priceRange.minValue : extras[0];
        let max = res.priceRange ? res.priceRange.maxValue : extras[0];
        for (const v of extras) {
          min = Math.min(min, v);
          max = Math.max(max, v);
        }
        const pad = Math.max((max - min) * 0.1, 25);
        return {
          ...res,
          priceRange: {
            minValue: min - pad,
            maxValue: max + pad,
          },
        };
      },
    });
    ensureChart.LineStyle = LineStyle;
    resizeChart();
  }

  function resizeChart() {
    if (!chart || !el.chart) return;
    const wrap = el.chart.parentElement;
    const width = el.chart.clientWidth || (wrap && wrap.clientWidth) || 0;
    let height = el.chart.clientHeight || 0;
    if ((height < 120 || width < 40) && wrap) {
      const tf = wrap.querySelector(".tf-btns");
      const tfH = tf ? tf.offsetHeight : 0;
      height = Math.max(height, wrap.clientHeight - tfH - 2);
    }
    const w = Math.max(1, Math.floor(width || 1));
    const h = Math.max(1, Math.floor(height || 1));
    if (w < 40 || h < 80) return;
    chart.applyOptions({ width: w, height: h });
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
    ensureChart();
    if (!series || target == null || !Number.isFinite(target)) {
      clearTargetLine();
      return;
    }
    const opts = {
      price: target,
      color: "#ffffff",
      lineWidth: 3,
      lineStyle: (ensureChart.LineStyle && ensureChart.LineStyle.Dashed) || 2,
      axisLabelVisible: true,
      title: title || "TARGET",
    };
    clearTargetLine();
    targetLine = series.createPriceLine(opts);
    // Nudge autoscale so the TARGET line is on-screen.
    try {
      series.applyOptions({});
    } catch {
      // ignore
    }
  }

  function applySettleLine(avg) {
    ensureChart();
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
    try {
      series.applyOptions({});
    } catch {
      // ignore
    }
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

      if (prevTicker && data.ticker && prevTicker !== data.ticker) {
        if (
          data.settlement_side === "above" ||
          data.settlement_side === "below"
        ) {
          // Rare: payload already carries prior outcome.
          settleHintByTicker[prevTicker] = data.settlement_side;
        }
        settleDemoPosition(prevTicker);
      } else if (
        demo.position &&
        data.settlement_mode &&
        (data.settlement_side === "above" || data.settlement_side === "below") &&
        demo.position.ticker === data.ticker
      ) {
        settleHintByTicker[data.ticker] = data.settlement_side;
        // Hold until window actually rolls so late fills aren't cut mid-settle.
      }

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
        if (prevTicker) settleDemoPosition(prevTicker);
        else if (demo.position) settleDemoPosition(demo.position.ticker);
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
        applyTargetLine(beat, "TARGET");
        maybeChimeNewFifteenTarget(beat, data.ticker, data.source, data.close_et);
        if (el.spotValue && el.spotValue.dataset.last) {
          updateSpot(Number(el.spotValue.dataset.last));
        }
        if (rolled || forceCandles || data.settlement_mode) {
          refreshCandles().then(() => applyTargetLine(beat, "TARGET"));
        } else {
          // Keep TARGET line visible even when candles aren't refreshed.
          applyTargetLine(beat, "TARGET");
        }
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
      const keepTarget = lastTarget;
      series.setData(candles);
      if (keepTarget != null && Number.isFinite(keepTarget)) {
        applyTargetLine(keepTarget, "TARGET");
      }
      if (lastSettlementAvg != null && Number.isFinite(lastSettlementAvg)) {
        applySettleLine(lastSettlementAvg);
      }
      if (!el.spotValue?.dataset.last && candles.length) {
        updateSpot(candles[candles.length - 1].close);
      }
      resizeChart();
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
    if (el.menuBtn) {
      el.menuBtn.addEventListener("click", () => {
        ensurePortraitLock(true);
        toggleOptions();
      });
    }
    if (el.optionsClose) {
      el.optionsClose.addEventListener("click", closeOptions);
    }
    if (el.optionsBackdrop) {
      el.optionsBackdrop.addEventListener("click", closeOptions);
    }
    if (el.demoToggle) {
      el.demoToggle.addEventListener("change", () => {
        setDemoOn(el.demoToggle.checked);
      });
    }
    if (el.demoReset) {
      el.demoReset.addEventListener("click", () => {
        resetDemoAccount();
      });
    }
    if (el.demoBuyBest) {
      el.demoBuyBest.addEventListener("click", () => demoBuyBest());
    }
    if (el.demoBuyAbove) {
      el.demoBuyAbove.addEventListener("click", () => openBuySheet("above"));
    }
    if (el.demoBuyBelow) {
      el.demoBuyBelow.addEventListener("click", () => openBuySheet("below"));
    }
    if (el.dockBuyAbove) {
      el.dockBuyAbove.addEventListener("click", () => openBuySheet("above"));
    }
    if (el.dockBuyBelow) {
      el.dockBuyBelow.addEventListener("click", () => openBuySheet("below"));
    }
    if (el.dockBuyBest) {
      el.dockBuyBest.addEventListener("click", () => demoBuyBest());
    }
    if (el.demoClose) {
      el.demoClose.addEventListener("click", () => closeDemoPosition());
    }
    if (el.demoLiveClose) {
      el.demoLiveClose.addEventListener("click", () => closeDemoPosition());
    }
    if (el.openPlClose) {
      el.openPlClose.addEventListener("click", () => closeDemoPosition());
    }
    if (el.buySheetX) {
      el.buySheetX.addEventListener("click", () => dismissBuySheet());
    }
    if (el.buyBackdrop) {
      el.buyBackdrop.addEventListener("click", () => dismissBuySheet());
    }
    if (el.buyAmount) {
      const syncAmt = () => {
        readBuyAmount();
        if (el.buyAmount) el.buyAmount.value = String(buySheetAmount);
        refreshBuySheetPreview();
      };
      el.buyAmount.addEventListener("input", syncAmt);
      el.buyAmount.addEventListener("change", syncAmt);
    }
    document.querySelectorAll(".buy-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const amt = Number(btn.dataset.amt);
        if (!Number.isFinite(amt)) return;
        buySheetAmount = amt;
        if (el.buyAmount) el.buyAmount.value = String(amt);
        refreshBuySheetPreview();
      });
    });
    if (el.buySlide) {
      el.buySlide.addEventListener("pointerdown", onBuySlidePointerDown);
      el.buySlide.addEventListener("pointermove", onBuySlidePointerMove);
      el.buySlide.addEventListener("pointerup", onBuySlidePointerUp);
      el.buySlide.addEventListener("pointercancel", onBuySlidePointerUp);
      el.buySlide.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === "ArrowRight") {
          ev.preventDefault();
          setBuySlideProgress(1);
          confirmBuyFromSheet();
        } else if (ev.key === "Escape") {
          dismissBuySheet();
        }
      });
    }
    if (el.bestSide) {
      el.bestSide.style.cursor = "pointer";
      el.bestSide.title = "Tap to place demo buy";
      el.bestSide.addEventListener("click", () => {
        if (lastBestPick && lastBestPick.side) openBuySheet(lastBestPick.side);
        else if (demo.on) setStatus("warn", "No clear Best Side yet");
        else {
          setStatus("warn", "Turn on Demo in Options");
          openOptions();
        }
      });
    }
    document.querySelectorAll(".roi-card.above").forEach((card) => {
      card.style.cursor = "pointer";
      card.addEventListener("click", () => openBuySheet("above"));
    });
    document.querySelectorAll(".roi-card.below").forEach((card) => {
      card.style.cursor = "pointer";
      card.addEventListener("click", () => openBuySheet("below"));
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && tutorialOpen) closeTutorial(false);
      else if (ev.key === "Escape" && buySheetOpen) dismissBuySheet();
      else if (ev.key === "Escape" && optionsOpen) closeOptions();
    });
    if (el.tutorialOpen) {
      el.tutorialOpen.addEventListener("click", () => openTutorial(true));
    }
    if (el.tutorialNext) {
      el.tutorialNext.addEventListener("click", () => nextTutorial());
    }
    if (el.tutorialSkip) {
      el.tutorialSkip.addEventListener("click", () => closeTutorial(true));
    }
    if (el.tutorialBackdrop) {
      el.tutorialBackdrop.addEventListener("click", () => closeTutorial(false));
    }
    renderDemoUi();
    syncAlertsUi();
    try {
      if (localStorage.getItem(TUTORIAL_KEY) !== "1") {
        setTimeout(() => openTutorial(true), 700);
      }
    } catch {
      // ignore
    }
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
    // Target first so Price-to-beat line exists when candles paint.
    refreshTarget()
      .then(() => refreshCandles())
      .then(refreshSpot);
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
    if (typeof ResizeObserver === "function" && el.chart) {
      const ro = new ResizeObserver(() => resizeChart());
      ro.observe(el.chart);
      if (el.chart.parentElement) ro.observe(el.chart.parentElement);
    }
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
