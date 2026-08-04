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
  const TRADE_HISTORY_KEY = "beatlineTradeHistory";
  const HISTORY_LIMIT = 40;
  const DEMO_DEFAULT_START = 1000;
  const APP_VERSION = "8.0";
  const TUTORIAL_KEY = "beatlineTutorialSeen";
  const OPEN_PL_COLLAPSE_KEY = "beatlineOpenPlCollapsed";
  const EPHEMERAL_DISMISS_KEY = "beatlineEphemeralDismissedAt";

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
      body: "Market chance shows Above/Below pricing. Best Side scores distance from the beat, time left, ask, and fees — then suggests a dollar size for high ROI with limited bankroll risk. When a clear edge appears, BeatLine chimes; tap Best to open the buy sheet pre-filled.",
    },
    {
      title: "Set size, then buy",
      body: "Use the Trade size slider ($0–$100). Then tap Buy Above, Best, or Buy Below at the bottom. Enter dollars if needed and slide to confirm — release early to cancel. After a fill, tap the same side again to add size (averages into the open position).",
    },
    {
      title: "Rolling P/L",
      body: "After a buy, an Open trade card tracks live P/L as price and odds move: entry, bid, fees, vs beat, time left, and hold outcomes. Add more on the same side anytime. Close at bid anytime, or hold to window settle.",
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
    bestSideSuggest: document.getElementById("best-side-suggest"),
    bestSideSuggestAmount: document.getElementById("best-side-suggest-amount"),
    bestSideSuggestMeta: document.getElementById("best-side-suggest-meta"),
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
    appVersionLine: document.getElementById("app-version-line"),
    appUpdate: document.getElementById("app-update"),
    pullRefresh: document.getElementById("pull-refresh"),
    pullRefreshLabel: document.getElementById("pull-refresh-label"),
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
    tradeHistoryList: document.getElementById("trade-history-list"),
    tradeHistorySummary: document.getElementById("trade-history-summary"),
    tradeHistoryClear: document.getElementById("trade-history-clear"),
    accountExport: document.getElementById("account-export"),
    accountImport: document.getElementById("account-import"),
    accountImportFile: document.getElementById("account-import-file"),
    ephemeralBanner: document.getElementById("ephemeral-banner"),
    ephemeralExport: document.getElementById("ephemeral-export"),
    ephemeralDismiss: document.getElementById("ephemeral-dismiss"),
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
    openPlAdd: document.getElementById("open-pl-add"),
    openPlClose: document.getElementById("open-pl-close"),
    openPlToggle: document.getElementById("open-pl-toggle"),
    openPlPeek: document.getElementById("open-pl-peek"),
    openPlBody: document.getElementById("open-pl-body"),
    buyBackdrop: document.getElementById("buy-backdrop"),
    buySheet: document.getElementById("buy-sheet"),
    buySheetTitle: document.getElementById("buy-sheet-title"),
    buySheetMeta: document.getElementById("buy-sheet-meta"),
    buySheetX: document.getElementById("buy-sheet-x"),
    buyAmount: document.getElementById("buy-amount"),
    buyRange: document.getElementById("buy-range"),
    buyRangeValue: document.getElementById("buy-range-value"),
    buySuggest: document.getElementById("buy-suggest"),
    buySuggestAmount: document.getElementById("buy-suggest-amount"),
    buySuggestMeta: document.getElementById("buy-suggest-meta"),
    buySuggestUse: document.getElementById("buy-suggest-use"),
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
  let targetSeries = null;
  let targetLine = null;
  let settleLine = null;
  let breakevenLine = null;
  let entryLine = null;
  let lastCandleData = [];
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
  let lastClearEdgeGoneAt = 0;
  const EDGE_ALERT_COOLDOWN_MS = 120_000;
  const EDGE_GONE_RESET_MS = 60_000;
  let openPlCollapsed = localStorage.getItem(OPEN_PL_COLLAPSE_KEY) === "1";
  let lastBreakevenPrice = null;
  let settleHintByTicker = {};
  let optionsOpen = false;
  let buySheetOpen = false;
  let buySheetSide = null; // above | below
  let buySheetAmount = 1;
  let buySuggestStake = null;
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
  let lastCandleCount = 0;
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

  function loadTradeHistory() {
    try {
      const raw = localStorage.getItem(TRADE_HISTORY_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((h) => h && typeof h === "object").slice(0, HISTORY_LIMIT);
    } catch {
      return [];
    }
  }

  function persistTradeHistory(list) {
    try {
      localStorage.setItem(
        TRADE_HISTORY_KEY,
        JSON.stringify((list || []).slice(0, HISTORY_LIMIT))
      );
    } catch {
      // ignore quota
    }
  }

  function demoLooksFresh(state) {
    if (!state) return true;
    const hist = Array.isArray(state.history) ? state.history : [];
    const realized = Number(state.realizedPl) || 0;
    const start = Number(state.start) || DEMO_DEFAULT_START;
    const bal = Number(state.balance);
    return (
      !state.position &&
      hist.length === 0 &&
      realized === 0 &&
      Number.isFinite(bal) &&
      Math.abs(bal - start) < 0.01
    );
  }

  function applyDemoState(next, { syncServer } = {}) {
    if (!next || typeof next !== "object") return;
    demo = {
      on: !!next.on,
      start:
        Number.isFinite(next.start) && next.start > 0
          ? next.start
          : DEMO_DEFAULT_START,
      balance: Number.isFinite(next.balance) ? next.balance : DEMO_DEFAULT_START,
      realizedPl: Number.isFinite(next.realizedPl) ? next.realizedPl : 0,
      position:
        next.position && typeof next.position === "object" ? next.position : null,
      lastResult:
        next.lastResult && typeof next.lastResult === "object"
          ? next.lastResult
          : null,
      history: Array.isArray(next.history)
        ? next.history.filter((h) => h && typeof h === "object").slice(0, HISTORY_LIMIT)
        : [],
      updatedAt: Number(next.updatedAt) || Date.now(),
    };
    persistTradeHistory(demo.history);
    try {
      localStorage.setItem(DEMO_KEY, JSON.stringify(demo));
    } catch {
      // ignore
    }
    if (syncServer) queueServerDemoSave();
    renderDemoUi();
    renderTradeHistory();
  }

  let serverSaveTimer = null;
  let serverSaveInFlight = false;

  function queueServerDemoSave() {
    if (serverSaveTimer) clearTimeout(serverSaveTimer);
    serverSaveTimer = setTimeout(() => {
      serverSaveTimer = null;
      pushDemoStateToServer().catch(() => {});
    }, 250);
  }

  async function pushDemoStateToServer() {
    if (serverSaveInFlight) {
      queueServerDemoSave();
      return;
    }
    serverSaveInFlight = true;
    try {
      const payload = {
        ...demo,
        history: Array.isArray(demo.history) ? demo.history : [],
        updatedAt: Date.now(),
      };
      demo.updatedAt = payload.updatedAt;
      await fetch("/api/demo-account", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: payload }),
        cache: "no-store",
      });
    } catch {
      // keep local; retry on next save
    } finally {
      serverSaveInFlight = false;
    }
  }

  function isEphemeralHost() {
    const host = (location.hostname || "").toLowerCase();
    return (
      host.endsWith(".loca.lt") ||
      host.endsWith(".trycloudflare.com") ||
      host.endsWith(".lhr.life") ||
      host.endsWith(".localhost.run")
    );
  }

  function setupEphemeralBanner() {
    if (!el.ephemeralBanner || !isEphemeralHost()) return;
    try {
      const dismissedAt = Number(localStorage.getItem(EPHEMERAL_DISMISS_KEY) || 0);
      // Re-show every 6h so the permanent-host reminder stays visible.
      if (dismissedAt && Date.now() - dismissedAt < 6 * 60 * 60 * 1000) return;
    } catch {
      // ignore
    }
    el.ephemeralBanner.hidden = false;
    if (el.ephemeralExport) {
      el.ephemeralExport.addEventListener("click", () => exportAccountBackup());
    }
    if (el.ephemeralDismiss) {
      el.ephemeralDismiss.addEventListener("click", () => {
        el.ephemeralBanner.hidden = true;
        try {
          localStorage.setItem(EPHEMERAL_DISMISS_KEY, String(Date.now()));
        } catch {
          // ignore
        }
      });
    }
  }

  async function hydrateDemoFromServer() {
    try {
      const res = await fetch("/api/demo-account", { cache: "no-store" });
      const data = await res.json();
      const remote = data && data.state;
      if (remote && typeof remote === "object") {
        const remoteFresh = demoLooksFresh(remote);
        const localFresh = demoLooksFresh(demo);
        const remoteAt = Number(remote.updatedAt) || 0;
        const localAt = Number(demo.updatedAt) || 0;
        // Empty local always loses to a server account with real history/P/L.
        const preferRemote =
          (localFresh && !remoteFresh) ||
          (!remoteFresh && remoteAt >= localAt) ||
          (remoteFresh && localFresh && remoteAt > localAt);
        if (preferRemote) {
          applyDemoState(remote, { syncServer: false });
          setStatus(
            "ok",
            `Account restored · ${money(demo.balance)}${
              demo.history && demo.history.length
                ? ` · ${demo.history.length} trades`
                : ""
            }`
          );
          return;
        }
      }
      // Seed server from this browser if it has anything useful.
      if (!demoLooksFresh(demo) || !remote) {
        await pushDemoStateToServer();
      }
    } catch {
      // offline / tunnel blip — keep localStorage
    }
  }

  function loadDemoState() {
    const fallback = {
      on: false,
      start: DEMO_DEFAULT_START,
      balance: DEMO_DEFAULT_START,
      realizedPl: 0,
      position: null,
      lastResult: null,
      history: loadTradeHistory(),
      updatedAt: 0,
    };
    try {
      const raw = localStorage.getItem(DEMO_KEY);
      if (!raw) return fallback;
      const parsed = JSON.parse(raw);
      let history = Array.isArray(parsed.history)
        ? parsed.history.filter((h) => h && typeof h === "object")
        : [];
      const external = loadTradeHistory();
      if (external.length && (!history.length || external.length >= history.length)) {
        history = external;
      }
      // Seed one row from lastResult if history is still empty (pre-history sessions).
      if (
        !history.length &&
        parsed.lastResult &&
        typeof parsed.lastResult === "object" &&
        parsed.lastResult.text
      ) {
        history = [
          {
            id: `seed-${Date.now()}`,
            at: Date.now(),
            kind: parsed.lastResult.won ? "settle" : "close",
            side: parsed.lastResult.side || "above",
            ticker: parsed.lastResult.ticker || null,
            contracts: null,
            askCents: null,
            total: null,
            fills: 1,
            exitCents: null,
            pl: Number(parsed.lastResult.pl),
            won: !!parsed.lastResult.won,
            accounted: false,
            text: parsed.lastResult.text,
          },
        ];
      }
      history = history.slice(0, HISTORY_LIMIT);
      persistTradeHistory(history);
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
        history,
        updatedAt: Number(parsed.updatedAt) || 0,
      };
    } catch {
      return fallback;
    }
  }

  function saveDemoState() {
    try {
      if (!Array.isArray(demo.history)) demo.history = [];
      demo.updatedAt = Date.now();
      persistTradeHistory(demo.history);
      localStorage.setItem(DEMO_KEY, JSON.stringify(demo));
    } catch {
      // ignore quota
    }
    queueServerDemoSave();
  }

  function pushTradeHistory(entry) {
    if (!entry || typeof entry !== "object") return;
    if (!Array.isArray(demo.history)) demo.history = [];
    demo.history.unshift({
      id: entry.id || `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      at: entry.at || Date.now(),
      ...entry,
    });
    if (demo.history.length > HISTORY_LIMIT) {
      demo.history = demo.history.slice(0, HISTORY_LIMIT);
    }
    persistTradeHistory(demo.history);
  }

  function clearTradeHistory() {
    demo.history = [];
    persistTradeHistory([]);
    saveDemoState();
    renderTradeHistory();
    setStatus("ok", "Trade history cleared");
  }

  function exportAccountBackup() {
    const payload = {
      version: 1,
      exportedAt: new Date().toISOString(),
      state: {
        on: !!demo.on,
        start: demo.start,
        balance: demo.balance,
        realizedPl: demo.realizedPl,
        position: demo.position,
        lastResult: demo.lastResult,
        history: Array.isArray(demo.history) ? demo.history : [],
        updatedAt: Date.now(),
      },
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    a.href = url;
    a.download = `beatline-account-${stamp}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
    setStatus("ok", "Account backup downloaded");
  }

  function importAccountBackupFile(file) {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result || "{}"));
        const state =
          parsed && parsed.state && typeof parsed.state === "object"
            ? parsed.state
            : parsed;
        if (!state || typeof state !== "object") {
          throw new Error("Invalid backup file");
        }
        if (
          !window.confirm(
            "Replace current demo account, open trade, and history with this backup?"
          )
        ) {
          return;
        }
        applyDemoState(
          {
            on: state.on !== false,
            start: state.start,
            balance: state.balance,
            realizedPl: state.realizedPl,
            position: state.position,
            lastResult: state.lastResult,
            history: state.history,
            updatedAt: Date.now(),
          },
          { syncServer: true }
        );
        setStatus(
          "ok",
          `Backup restored · ${money(demo.balance)} · ${(demo.history || []).length} trades`
        );
      } catch (err) {
        setStatus("warn", `Import failed: ${err.message || err}`);
      }
    };
    reader.onerror = () => setStatus("warn", "Could not read backup file");
    reader.readAsText(file);
  }

  function formatHistoryTime(ts) {
    if (!ts) return "";
    try {
      return new Date(ts).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      });
    } catch {
      return "";
    }
  }

  function renderTradeHistory() {
    if (!Array.isArray(demo.history)) demo.history = loadTradeHistory();
    const list = demo.history;
    const open = demo.position;
    const openMark = open ? markOpenPosition(open) : null;

    if (el.tradeHistorySummary) {
      if (!list.length && !open) {
        el.tradeHistorySummary.textContent = "No trades yet";
        el.tradeHistorySummary.classList.remove("is-up", "is-down");
      } else {
        const wins = list.filter((t) => t.won).length;
        const closed = list.length;
        const totalPl = list.reduce(
          (sum, t) => sum + (Number.isFinite(Number(t.pl)) ? Number(t.pl) : 0),
          0
        );
        const openBit = open
          ? ` · open ${open.side === "above" ? "Above" : "Below"}`
          : "";
        el.tradeHistorySummary.textContent = closed
          ? `${closed} closed · ${wins}W-${closed - wins}L · ${formatPl(
              totalPl
            )}${openBit}`
          : `Open ${open.side === "above" ? "Above" : "Below"} · ${
              open.contracts
            } cts`;
        el.tradeHistorySummary.classList.toggle("is-up", totalPl > 0);
        el.tradeHistorySummary.classList.toggle("is-down", totalPl < 0);
      }
    }
    if (!el.tradeHistoryList) return;

    const rows = [];
    if (open) {
      const side = open.side === "above" ? "Above" : "Below";
      const pl = openMark && openMark.unrealized;
      const plClass =
        pl == null ? "" : pl >= 0 ? "is-win" : "is-loss";
      rows.push(
        `<article class="trade-history-item is-open ${plClass}">` +
          `<div class="trade-history-top">` +
          `<span class="trade-history-kind">OPEN ${side}</span>` +
          `<span class="trade-history-pl">${
            pl == null ? "—" : formatPl(pl)
          }</span>` +
          `</div>` +
          `<div class="trade-history-meta">${formatHistoryTime(
            open.openedAt || open.lastAddedAt || Date.now()
          )} · ${open.contracts} cts @ avg ${
            open.askCents != null ? open.askCents + "¢" : "—"
          }${open.fills > 1 ? ` · ${open.fills} fills` : ""} · paid ${money(
            open.total
          )}</div>` +
          `</article>`
      );
    }

    for (const t of list) {
      const side = t.side === "above" ? "Above" : t.side === "below" ? "Below" : "—";
      let kind = "CLOSED";
      if (t.kind === "settle") kind = t.won ? "WIN" : "LOSS";
      else if (t.kind === "buy") kind = "BOUGHT";
      else if (t.kind === "add") kind = "ADDED";
      else if (t.kind === "close") kind = "CLOSED";
      const plClass =
        t.pl == null ? "" : t.won || t.pl >= 0 ? "is-win" : "is-loss";
      const fills = t.fills > 1 ? ` · ${t.fills} fills` : "";
      const exit = t.exitCents != null ? ` @ ${t.exitCents}¢` : "";
      const mode = t.accounted ? "" : " · paper";
      const plTxt =
        t.pl == null || !Number.isFinite(Number(t.pl))
          ? t.text || "—"
          : formatPl(Number(t.pl));
      rows.push(
        `<article class="trade-history-item ${plClass}">` +
          `<div class="trade-history-top">` +
          `<span class="trade-history-kind">${kind} ${side}${exit}</span>` +
          `<span class="trade-history-pl">${plTxt}</span>` +
          `</div>` +
          `<div class="trade-history-meta">${formatHistoryTime(t.at)} · ${
            t.contracts != null ? t.contracts : "—"
          } cts @ avg ${t.askCents != null ? t.askCents + "¢" : "—"}${fills} · paid ${
            t.total != null ? money(t.total) : "—"
          }${mode}</div>` +
          `</article>`
      );
    }

    if (!rows.length) {
      el.tradeHistoryList.innerHTML =
        '<div class="trade-history-empty">Buy, add, close, or settle — trades will list here.</div>';
      return;
    }
    el.tradeHistoryList.innerHTML = rows.join("");
  }

  function openOptions() {
    optionsOpen = true;
    if (el.optionsSheet) el.optionsSheet.hidden = false;
    if (el.optionsBackdrop) el.optionsBackdrop.hidden = false;
    if (el.menuBtn) el.menuBtn.setAttribute("aria-expanded", "true");
    renderDemoUi();
    renderTradeHistory();
    // Keep history in view near the top of the ⋮ sheet.
    if (el.optionsSheet) el.optionsSheet.scrollTop = 0;
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

  function setOpenPlCollapsed(collapsed) {
    openPlCollapsed = !!collapsed;
    try {
      localStorage.setItem(OPEN_PL_COLLAPSE_KEY, openPlCollapsed ? "1" : "0");
    } catch {
      // ignore
    }
    document.body.classList.toggle("open-pl-collapsed", openPlCollapsed);
    if (el.openPlBar) el.openPlBar.classList.toggle("is-collapsed", openPlCollapsed);
    if (el.openPlToggle) {
      el.openPlToggle.setAttribute("aria-expanded", openPlCollapsed ? "false" : "true");
      el.openPlToggle.title = openPlCollapsed
        ? "Show trade metrics"
        : "Slide trade metrics away";
    }
    setTimeout(resizeChart, 60);
  }

  /** Approximate inverse error function for model break-even spot. */
  function erfinvApprox(x) {
    const a = 0.147;
    const sign = x < 0 ? -1 : 1;
    const z = Math.min(0.999, Math.max(-0.999, x));
    const ln = Math.log(1 - z * z);
    const t = 2 / (Math.PI * a) + ln / 2;
    return sign * Math.sqrt(Math.sqrt(t * t - ln / a) - t);
  }

  function modelBreakevenSpot(pos, secsLeft) {
    if (!pos || pos.beat == null || !Number.isFinite(pos.beat)) return null;
    if (!(pos.contracts > 0) || !(pos.total > 0)) return null;
    const costPer = pos.total / pos.contracts;
    let needAbove = Math.min(0.92, Math.max(0.08, costPer));
    // Above needs P(above) >= costPer; Below needs P(below) >= costPer
    // => P(above) <= 1 - costPer
    if (pos.side === "below") needAbove = 1 - needAbove;
    const t = Math.max(1, Number(secsLeft) || 1);
    const sigma = Math.max(
      8,
      Math.abs(pos.beat) * 0.55 * Math.sqrt(t / (365.25 * 24 * 3600))
    );
    const z = Math.SQRT2 * erfinvApprox(2 * needAbove - 1);
    if (!Number.isFinite(z)) return null;
    return Math.round((pos.beat + sigma * z) * 100) / 100;
  }

  function renderOpenPlBar(pos, mark) {
    if (!el.openPlBar) return;
    if (!pos) {
      el.openPlBar.hidden = true;
      document.body.classList.remove("has-open-pl");
      document.body.classList.remove("open-pl-collapsed");
      clearBreakevenLines();
      if (lastTarget != null) applyTargetLine(lastTarget, "TO BEAT");
      return;
    }
    el.openPlBar.hidden = false;
    document.body.classList.add("has-open-pl");
    setOpenPlCollapsed(openPlCollapsed);
    const side = pos.side === "above" ? "Above" : "Below";
    const accounted = pos.accounted !== false && demo.on;
    const sess = sessionPlBreakdown(mark);
    const beSpot = modelBreakevenSpot(pos, mark && mark.secs);
    lastBreakevenPrice = beSpot;
    applyBreakevenLines(pos.beat, pos.entrySpot, beSpot, pos.side);
    // Price to beat must stay visible while a trade is open.
    const beatKeep =
      pos.beat != null && Number.isFinite(Number(pos.beat))
        ? Number(pos.beat)
        : lastTarget;
    if (beatKeep != null && Number.isFinite(beatKeep)) {
      applyTargetLine(beatKeep, "TO BEAT");
    }

    if (el.openPlSide) {
      const fills = pos.fills > 1 ? ` · ${pos.fills} fills` : "";
      el.openPlSide.textContent = `Buy ${side} · ${pos.contracts} cts @ avg ${pos.askCents}¢${fills}`;
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
    if (el.openPlPeek) {
      const plTxt =
        mark && mark.unrealized != null ? formatPl(mark.unrealized) : "—";
      el.openPlPeek.textContent = `Open ${side} ${plTxt} · tap to expand`;
      el.openPlPeek.classList.toggle("is-up", !!(mark && mark.unrealized > 0));
      el.openPlPeek.classList.toggle("is-down", !!(mark && mark.unrealized < 0));
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
      if (beSpot != null) {
        bits.push(`B/E $${beSpot.toFixed(0)}`);
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
    if (el.openPlAdd) {
      const side = pos.side === "above" ? "Above" : "Below";
      el.openPlAdd.disabled = !canBuySide(pos.side);
      el.openPlAdd.textContent = `Add ${side}`;
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
        el.demoPosition.textContent = formatPositionSummary(pos);
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
    renderTradeHistory();
    const busyAbove = !!demo.position && !canBuySide("above");
    const busyBelow = !!demo.position && !canBuySide("below");
    if (el.demoBuyBest) {
      const bestSide = lastBestPick && lastBestPick.side;
      el.demoBuyBest.disabled =
        !bestSide || (demo.position ? !canBuySide(bestSide) : false);
    }
    if (el.demoBuyAbove) el.demoBuyAbove.disabled = !demo.on || busyAbove;
    if (el.demoBuyBelow) el.demoBuyBelow.disabled = !demo.on || busyBelow;
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
    pushTradeHistory({
      id: `${Date.now()}-${pos.ticker || "x"}`,
      at: Date.now(),
      kind: "close",
      side: pos.side,
      ticker: pos.ticker || null,
      contracts: pos.contracts,
      askCents: pos.askCents,
      total: pos.total,
      fills: pos.fills || 1,
      exitCents: mark.bidCents,
      pl,
      won,
      accounted: !!accounted,
    });
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
    // Keep trade history across bankroll resets (use Clear in Options to wipe).
    saveDemoState();
    renderDemoUi();
    setStatus("ok", `Demo reset · ${money(start)}`);
  }

  const BUY_AMOUNT_MIN = 1;
  const BUY_AMOUNT_MAX = 100;

  function buyAmountCap() {
    const hard = BUY_AMOUNT_MAX;
    if (demo.on) {
      return Math.max(
        BUY_AMOUNT_MIN,
        Math.min(hard, Math.floor(demo.balance) || BUY_AMOUNT_MIN)
      );
    }
    return hard;
  }

  function clampBuyAmount(n) {
    const cap = buyAmountCap();
    let v = Number(n);
    if (!Number.isFinite(v)) v = buySheetAmount;
    return Math.max(BUY_AMOUNT_MIN, Math.min(cap, Math.round(v)));
  }

  /** Same-side adds are always allowed; only opposite side is locked. */
  function canBuySide(side) {
    const pos = demo.position;
    if (!pos) return true;
    if (side !== "above" && side !== "below") return false;
    return pos.side === side;
  }

  function formatPositionSummary(pos) {
    if (!pos) return "Flat";
    const side = pos.side === "above" ? "Above" : "Below";
    const fills = pos.fills > 1 ? ` · ${pos.fills} fills` : "";
    return `Buy ${side} · ${pos.contracts} cts @ avg ${pos.askCents}¢ · paid ${money(
      pos.total
    )}${fills}`;
  }

  function demoBuy(side, amountUsd) {
    const existing = demo.position;
    if (existing && existing.side !== side) {
      setStatus(
        "warn",
        `Already long ${existing.side === "above" ? "Above" : "Below"} — close first to flip`
      );
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
    const accounted = existing
      ? existing.accounted !== false && demo.on
      : !!demo.on;
    if (accounted && sized.total > demo.balance + 1e-9) {
      setStatus("warn", "Not enough demo balance");
      return false;
    }
    if (accounted) {
      demo.balance = Math.round((demo.balance - sized.total) * 100) / 100;
    }
    const spotRaw = el.spotValue && el.spotValue.dataset.last;
    const spotN = spotRaw != null ? Number(spotRaw) : null;
    const entrySpot =
      spotN != null && Number.isFinite(spotN) ? spotN : null;

    if (existing) {
      const nextContracts = existing.contracts + sized.contracts;
      const nextCost = Math.round((existing.cost + sized.cost) * 100) / 100;
      const nextFee = Math.round((existing.fee + sized.fee) * 100) / 100;
      const nextTotal = Math.round((existing.total + sized.total) * 100) / 100;
      const avgAsk =
        nextContracts > 0
          ? Math.round(
              (existing.askCents * existing.contracts +
                sized.askCents * sized.contracts) /
                nextContracts
            )
          : sized.askCents;
      let nextEntry = existing.entrySpot;
      if (entrySpot != null && Number.isFinite(entrySpot)) {
        if (existing.entrySpot != null && Number.isFinite(existing.entrySpot)) {
          nextEntry =
            Math.round(
              ((existing.entrySpot * existing.contracts +
                entrySpot * sized.contracts) /
                nextContracts) *
                100
            ) / 100;
        } else {
          nextEntry = entrySpot;
        }
      }
      demo.position = {
        ...existing,
        ticker: lastTicker || existing.ticker,
        askCents: avgAsk,
        contracts: nextContracts,
        cost: nextCost,
        fee: nextFee,
        total: nextTotal,
        beat: lastTarget != null ? lastTarget : existing.beat,
        entrySpot: nextEntry,
        fills: (existing.fills || 1) + 1,
        lastAddedAt: Date.now(),
        accounted: existing.accounted !== false ? accounted : false,
      };
    } else {
      demo.position = {
        ticker: lastTicker,
        side,
        askCents: sized.askCents,
        contracts: sized.contracts,
        cost: sized.cost,
        fee: sized.fee,
        total: sized.total,
        beat: lastTarget,
        entrySpot,
        openedAt: Date.now(),
        fills: 1,
        accounted,
      };
    }
    // Keep main trade-size slider in sync for Best Side sizing ($1–$100).
    if (stake >= BUY_AMOUNT_MIN && stake <= BUY_AMOUNT_MAX) {
      setTradeStake(Math.round(stake));
    }
    const added = !!existing;
    pushTradeHistory({
      id: `${Date.now()}-${added ? "add" : "buy"}-${lastTicker || "x"}`,
      at: Date.now(),
      kind: added ? "add" : "buy",
      side,
      ticker: lastTicker || null,
      contracts: sized.contracts,
      askCents: sized.askCents,
      total: sized.total,
      fills: 1,
      exitCents: null,
      pl: null,
      won: null,
      accounted: !!accounted,
    });
    saveDemoState();
    refreshBestSide();
    renderDemoUi();
    const sideLabel = side === "above" ? "Above" : "Below";
    setStatus(
      "ok",
      accounted
        ? `${added ? "Added to" : "Demo bought"} ${sideLabel} · ${sized.contracts} cts${
            added ? ` · now ${demo.position.contracts}` : ""
          }`
        : `${added ? "Added to" : "Paper bought"} ${sideLabel} · ${sized.contracts} cts${
            added ? ` · now ${demo.position.contracts}` : ""
          }`
    );
    return true;
  }

  function setBuyAmountUi(n, syncStake) {
    const amt = clampBuyAmount(n);
    buySheetAmount = amt;
    if (el.buyAmount && document.activeElement !== el.buyAmount) {
      el.buyAmount.value = String(amt);
    } else if (el.buyAmount && document.activeElement === el.buyAmount) {
      // Keep typing free; commit on change/blur via callers.
    } else if (el.buyAmount) {
      el.buyAmount.value = String(amt);
    }
    if (el.buyRange) {
      const cap = buyAmountCap();
      el.buyRange.min = String(BUY_AMOUNT_MIN);
      el.buyRange.max = String(cap);
      el.buyRange.value = String(Math.min(amt, cap));
      el.buyRange.setAttribute("aria-valuenow", String(amt));
      el.buyRange.setAttribute("aria-valuemax", String(cap));
    }
    if (el.buyRangeValue) el.buyRangeValue.textContent = `$${amt}`;
    document.querySelectorAll(".buy-chip").forEach((btn) => {
      const chipAmt = Number(btn.dataset.amt);
      btn.classList.toggle("is-active", chipAmt === amt);
    });
    if (syncStake) setTradeStake(amt);
    return amt;
  }

  function readBuyAmount() {
    const n = clampBuyAmount(el.buyAmount && el.buyAmount.value);
    setBuyAmountUi(n, false);
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
      const adding = !!(demo.position && demo.position.side === side);
      el.buySheetMeta.textContent = adding
        ? `Add ${side === "above" ? "Above" : "Below"} · ${askTxt} · now ${
            demo.position.contracts
          } cts @ avg ${demo.position.askCents}¢`
        : `${side === "above" ? "Above" : "Below"} · ${askTxt} · live Kalshi book`;
    }
    if (el.buyPreview) {
      if (!sized || sized.empty) {
        el.buyPreview.textContent = "Enter an amount to preview contracts + fees";
      } else {
        const adding = !!(demo.position && demo.position.side === side);
        const afterCts = adding
          ? demo.position.contracts + sized.contracts
          : sized.contracts;
        el.buyPreview.textContent =
          `${sized.contracts} contracts · cost ${money(sized.cost)} + fee ${money(
            sized.fee
          )} · total ${money(sized.total)} · win ${money(sized.profitIfWin)} (${
            sized.roiIfWin != null
              ? `${sized.roiIfWin >= 0 ? "+" : ""}${sized.roiIfWin.toFixed(0)}%`
              : "—"
          })${adding ? ` · position → ${afterCts} cts` : ""}`;
      }
    }
    if (el.buySlideLabel && !buyConfirming) {
      const adding = !!(demo.position && demo.position.side === side);
      const label = adding
        ? side === "above"
          ? "Slide to add Above"
          : "Slide to add Below"
        : side === "above"
          ? "Slide to buy Above"
          : "Slide to buy Below";
      el.buySlideLabel.textContent = label;
    }
    renderBuySuggest(side, amount);
  }

  function renderBuySuggest(side, currentAmount) {
    if (!el.buySuggest) return;
    const s = suggestForSide(side);
    buySuggestStake =
      s && !s.lowProb && s.stake >= BUY_AMOUNT_MIN ? s.stake : null;
    if (buySuggestStake == null) {
      el.buySuggest.hidden = true;
      return;
    }
    el.buySuggest.hidden = false;
    const atSuggested = Math.round(Number(currentAmount) || 0) === buySuggestStake;
    el.buySuggest.classList.toggle("is-active", atSuggested);
    if (el.buySuggestAmount) {
      el.buySuggestAmount.textContent = `$${buySuggestStake}${
        s.contracts ? ` · ${s.contracts} cts` : ""
      }`;
    }
    if (el.buySuggestMeta) {
      const roi =
        s.roiIfWin != null
          ? `${s.roiIfWin >= 0 ? "+" : ""}${s.roiIfWin.toFixed(0)}% if win`
          : "";
      const conf = s.pWin != null ? `${Math.round(s.pWin * 100)}% model` : "";
      const bankTxt = bankPctText(s.bankPct);
      const bank = bankTxt ? `${bankTxt} of balance` : "";
      el.buySuggestMeta.textContent = [conf, roi, bank]
        .filter(Boolean)
        .join(" · ");
    }
    if (el.buySuggestUse) {
      el.buySuggestUse.textContent = atSuggested ? "Set" : "Use";
      el.buySuggestUse.disabled = atSuggested;
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

  function openBuySheet(side, opts = {}) {
    if (side !== "above" && side !== "below") return;
    if (demo.position && !canBuySide(side)) {
      setStatus(
        "warn",
        `Already long ${demo.position.side === "above" ? "Above" : "Below"} — close first to flip`
      );
      return;
    }
    const ask = side === "above" ? lastRoiAsks.above : lastRoiAsks.below;
    if (ask == null || !(ask >= 1 && ask <= 99)) {
      setStatus("warn", "Need a live ask");
      return;
    }
    closeOptions();
    buySheetSide = side;
    buySheetOpen = true;
    const adding = !!(demo.position && demo.position.side === side);
    const sideSuggest = suggestForSide(side);
    const suggested = !opts.useSuggest
      ? null
      : lastBestPick &&
          lastBestPick.side === side &&
          lastBestPick.suggestedStake >= BUY_AMOUNT_MIN
        ? lastBestPick.suggestedStake
        : sideSuggest && sideSuggest.stake >= BUY_AMOUNT_MIN
          ? sideSuggest.stake
          : null;
    // Prefer Best Side suggestion when buying the suggested side.
    const preferred =
      suggested != null
        ? suggested
        : buySheetAmount >= BUY_AMOUNT_MIN
          ? buySheetAmount
          : tradeStake >= BUY_AMOUNT_MIN
            ? tradeStake
            : BUY_AMOUNT_MIN;
    if (el.buyAmount) {
      el.buyAmount.min = String(BUY_AMOUNT_MIN);
      el.buyAmount.max = String(buyAmountCap());
    }
    setBuyAmountUi(preferred, suggested != null);
    if (el.buySheet) {
      el.buySheet.hidden = false;
      el.buySheet.classList.remove("is-done");
      el.buySheet.classList.toggle("is-below", side === "below");
    }
    if (el.buyBackdrop) el.buyBackdrop.hidden = false;
    if (el.buySheetTitle) {
      el.buySheetTitle.textContent = adding
        ? side === "above"
          ? "Add to Above"
          : "Add to Below"
        : side === "above"
          ? "Buy Above"
          : "Buy Below";
    }
    const kicker = document.querySelector(".buy-sheet-kicker");
    if (kicker) {
      kicker.textContent =
        suggested != null
          ? demo.on
            ? `Suggested $${suggested} · high ROI / low risk`
            : `Suggested $${suggested} · high ROI / low risk`
          : adding
            ? demo.on
              ? "Demo add · averages into open position"
              : "Paper add · averages into open position"
            : demo.on
              ? "Demo order"
              : "Paper order · rolling P/L";
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
    if (el.buySlideLabel) {
      el.buySlideLabel.textContent =
        demo.position && demo.position.side === buySheetSide ? "Added" : "Bought";
    }
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
    openBuySheet(lastBestPick.side, { useSuggest: true });
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
    pushTradeHistory({
      id: `${Date.now()}-${pos.ticker || "x"}`,
      at: Date.now(),
      kind: "settle",
      side: pos.side,
      ticker: pos.ticker || null,
      contracts: pos.contracts,
      askCents: pos.askCents,
      total: pos.total,
      fills: pos.fills || 1,
      exitCents: null,
      pl,
      won,
      accounted: !!accounted,
      outcome,
    });
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
      const reg = await navigator.serviceWorker.register("/sw.js?v=3.0", { scope: "/" });
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
    // Foreground: chime only. Background: system notification (+ server push).
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
    }
  }

  function alertClearEdge(best) {
    if (!best || !best.side) return;
    if (!chimeOn) return;
    // If already long the opposite side, skip spam. Same-side clear edge
    // still alerts — useful when deciding whether to add.
    if (demo.position && demo.position.side !== best.side) return;

    const side = best.side;
    const ask = Math.round(Number(best.askCents) || 0);
    const alertKey = `${side}:${ask}`;
    const now = Date.now();
    // Hard cooldown stops alert loops when Best Side flickers around the threshold.
    if (now - lastClearEdgeAlertAt < EDGE_ALERT_COOLDOWN_MS) return;

    const prev = lastClearEdgeAlertKey;
    const sideChanged =
      prev && prev !== "none" && !String(prev).startsWith(`${side}:`);
    const newlyClear = !prev || prev === "none";
    const askMoved =
      prev &&
      String(prev).startsWith(`${side}:`) &&
      Math.abs(Number(String(prev).split(":")[1]) - ask) >= 5;

    if (!(newlyClear || sideChanged || askMoved)) return;

    lastClearEdgeAlertKey = alertKey;
    lastClearEdgeAlertAt = now;
    lastClearEdgeGoneAt = 0;
    ensureAudio();
    playEdgeChime();
    const sideLabel = side === "above" ? "Above" : "Below";
    const sug =
      lastBestPick && lastBestPick.side === side && lastBestPick.suggestedStake
        ? lastBestPick.suggestedStake
        : null;
    setStatus(
      "ok",
      sug != null
        ? `Clear edge · Buy ${sideLabel} · suggest $${sug}${ask ? ` @ ${ask}¢` : ""}`
        : `Clear edge · Buy ${sideLabel}${ask ? ` @ ${ask}¢` : ""}`
    );
    // System notification only when backgrounded — avoids foreground alert loops.
    if (document.visibilityState !== "visible") {
      postToSW({
        type: "edge-notify",
        side,
        askCents: ask || null,
        pWin: best.pWin,
        ticker: lastTicker || lastFifteenTicker,
        beat: lastTarget,
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
    // Ignore tiny float / book jitter — only real window rolls should chime.
    const beatChanged =
      beatReady &&
      lastFifteenTarget != null &&
      tickerChanged &&
      Math.abs(lastFifteenTarget - beat) > 1;

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
  if (!Number.isFinite(tradeStake)) tradeStake = 1;
  tradeStake = Math.max(1, Math.min(100, Math.round(tradeStake)));
  if (tradeStake < 1) tradeStake = 1;

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
      costPer,
      roiIfWin: bought && !bought.empty ? bought.roiIfWin : sized.roiIfWin,
      contracts: bought && !bought.empty ? bought.contracts : 0,
      total: bought && !bought.empty ? bought.total : 0,
      profitIfWin: bought && !bought.empty ? bought.profitIfWin : 0,
    };
  }

  /** Bankroll used for suggested sizing (demo balance when on). */
  function sizingBankroll() {
    if (demo.on && Number.isFinite(demo.balance)) {
      return Math.max(0, demo.balance);
    }
    const start = Number(demo.start);
    return Number.isFinite(start) && start > 0 ? start : DEMO_DEFAULT_START;
  }

  const SUGGEST_STEPS = [1, 2, 3, 5, 8, 10, 15, 20, 25, 30, 40, 50, 60, 75, 100];

  function snapSuggestStake(n, cap) {
    const target = Math.max(BUY_AMOUNT_MIN, Math.min(cap, Math.round(n)));
    let best = BUY_AMOUNT_MIN;
    let bestDist = Infinity;
    for (const step of SUGGEST_STEPS) {
      if (step > cap) break;
      const d = Math.abs(step - target);
      if (d < bestDist || (d === bestDist && step <= target)) {
        best = step;
        bestDist = d;
      }
    }
    // Prefer not rounding *up* past Kelly target when risk-averse.
    if (best > target && bestDist > 0) {
      const lower = SUGGEST_STEPS.filter((s) => s <= target && s <= cap);
      if (lower.length) best = lower[lower.length - 1];
    }
    return Math.max(BUY_AMOUNT_MIN, Math.min(cap, best));
  }

  /**
   * Suggest $ for a clear Best Side: fractional Kelly sized for high ROI /
   * low bankroll risk, clamped to $1–$100 and available balance.
   */
  function suggestStakeForEdge(best) {
    if (!best || best.askCents == null) return null;
    const bank = sizingBankroll();
    const hardCap = Math.max(
      BUY_AMOUNT_MIN,
      Math.min(BUY_AMOUNT_MAX, Math.floor(bank) || BUY_AMOUNT_MIN)
    );
    const unit = roiForStake(best.askCents, Math.min(10, hardCap));
    if (!unit || unit.empty || !(unit.contracts > 0)) return null;
    const costPer = unit.total / unit.contracts;
    if (!(costPer > 0 && costPer < 1)) return null;

    const pWin = Math.max(0.01, Math.min(0.99, Number(best.pWin) || 0.5));
    const edge = pWin - costPer;
    if (!(edge > 0)) {
      const minSized = roiForStake(best.askCents, BUY_AMOUNT_MIN);
      return {
        stake: BUY_AMOUNT_MIN,
        contracts: minSized && !minSized.empty ? minSized.contracts : 0,
        total: minSized && !minSized.empty ? minSized.total : BUY_AMOUNT_MIN,
        profitIfWin: minSized && !minSized.empty ? minSized.profitIfWin : 0,
        roiIfWin:
          minSized && !minSized.empty ? minSized.roiIfWin : unit.roiIfWin,
        bankPct: bank > 0 ? (BUY_AMOUNT_MIN / bank) * 100 : 0,
        pWin,
        lowProb: pWin < 0.5,
        note: "no edge at this ask",
      };
    }

    // Full Kelly for $1 payout contracts priced at costPer.
    const kellyFull = edge / (1 - costPer);
    // Stronger model edge → allow a bit more of Kelly; still fractional.
    const edgeStrength = Math.min(
      1,
      Math.max(0, (Number(best.score) - 0.04) / 0.18)
    );
    const kellyShare = 0.22 + 0.18 * edgeStrength; // ~22–40% Kelly
    // Cap bankroll risk: ~3–10% (minimal risk / balance).
    let maxBankPct = 0.03 + 0.07 * edgeStrength;
    // Cheap ask (high ROI) can use more of the risk budget; expensive ask less.
    const roi = Number(best.roiIfWin);
    if (Number.isFinite(roi)) {
      if (roi >= 120) maxBankPct *= 1.15;
      else if (roi < 40) maxBankPct *= 0.7;
    }
    maxBankPct = Math.min(0.12, Math.max(0.025, maxBankPct));

    const kellyUsd = bank * kellyFull * kellyShare;
    const riskUsd = bank * maxBankPct;
    let raw = Math.min(kellyUsd, riskUsd, hardCap);
    // Need at least one contract after fees.
    const minForOne = Math.ceil(costPer * 100) / 100;
    raw = Math.max(raw, Math.min(hardCap, Math.max(BUY_AMOUNT_MIN, minForOne)));

    const stake = snapSuggestStake(raw, hardCap);
    const sized = roiForStake(best.askCents, stake);
    return {
      stake,
      pWin,
      // Cheap longshots can screen as +EV on model noise; never present them
      // as a "minimize risk" size.
      lowProb: pWin < 0.5,
      contracts: sized && !sized.empty ? sized.contracts : 0,
      total: sized && !sized.empty ? sized.total : stake,
      profitIfWin: sized && !sized.empty ? sized.profitIfWin : 0,
      roiIfWin: sized && !sized.empty ? sized.roiIfWin : unit.roiIfWin,
      bankPct: bank > 0 ? (stake / bank) * 100 : 0,
      note: "¼-Kelly bal",
    };
  }

  /**
   * Suggested size for either side (not just Best Side) so the buy sheet can
   * always recommend a stake: maximize ROI while capping bankroll risk.
   */
  function suggestForSide(side) {
    if (side !== "above" && side !== "below") return null;
    const ask = side === "above" ? lastRoiAsks.above : lastRoiAsks.below;
    if (ask == null || !Number.isFinite(ask)) return null;
    const spotRaw = el.spotValue && el.spotValue.dataset.last;
    const spot = spotRaw != null ? Number(spotRaw) : null;
    const beat = lastTarget;
    const secs = secondsLeft();
    if (spot == null || beat == null || secs == null) return null;
    const modelP = modelProbAbove(spot, beat, secs);
    if (modelP == null) return null;
    const scored = scoreSide(side, ask, modelP, tradeStake);
    if (!scored) return null;
    const suggestion = suggestStakeForEdge(scored);
    if (!suggestion) return null;
    return { ...suggestion, side, pWin: scored.pWin, ev: scored.ev };
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

  async function refreshVersionLine() {
    if (!el.appVersionLine) return;
    let server = null;
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      const data = await res.json();
      server = data && data.version;
    } catch {
      // offline — show what we have
    }
    el.appVersionLine.textContent = server
      ? `App ${APP_VERSION} · server ${server}`
      : `App ${APP_VERSION}`;
  }

  /**
   * Drop the service worker + caches and hard-reload, so a home-screen PWA
   * picks up new code without digging through Android settings.
   * Saved balance/history live in localStorage + the server, so they survive.
   */
  async function forceAppUpdate() {
    if (el.appUpdate) {
      el.appUpdate.disabled = true;
      el.appUpdate.textContent = "Updating…";
    }
    setStatus("ok", "Fetching latest BeatLine…");
    try {
      await pushDemoStateToServer();
    } catch {
      // keep going; local copy still intact
    }
    try {
      if ("caches" in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      }
    } catch {
      // ignore
    }
    try {
      if (navigator.serviceWorker) {
        const regs = await navigator.serviceWorker.getRegistrations();
        await Promise.all(regs.map((r) => r.unregister()));
      }
    } catch {
      // ignore
    }
    const url = new URL(window.location.href);
    url.searchParams.set("fresh", String(Date.now()));
    window.location.replace(url.toString());
  }

  /**
   * Pull-to-refresh. The shell is a fixed-height flex layout with no page
   * scroll, so Chrome's native gesture never fires — track it ourselves.
   */
  const PULL_TRIGGER_PX = 72;
  const PULL_MAX_PX = 110;
  let pullStartY = null;
  let pullActive = false;
  let pullDistance = 0;
  let pullRunning = false;

  function setPullIndicator(distance, ready) {
    if (!el.pullRefresh) return;
    const shown = distance > 6;
    el.pullRefresh.classList.toggle("is-visible", shown);
    el.pullRefresh.classList.toggle("is-ready", !!ready);
    const y = Math.min(distance, PULL_MAX_PX);
    el.pullRefresh.style.transform = `translate(-50%, ${Math.max(
      -120,
      y - 44
    )}px)`;
    if (el.pullRefreshLabel && !pullRunning) {
      el.pullRefreshLabel.textContent = ready
        ? "Release to update"
        : "Pull to refresh";
    }
  }

  function resetPullIndicator() {
    pullStartY = null;
    pullActive = false;
    pullDistance = 0;
    if (!el.pullRefresh) return;
    el.pullRefresh.classList.remove("is-visible", "is-ready", "is-loading");
    el.pullRefresh.style.transform = "translate(-50%, -120%)";
  }

  /** Only start the gesture where a downward drag isn't already meaningful. */
  function pullAllowedFrom(target) {
    if (pullRunning || buySheetOpen || optionsOpen || tutorialOpen) return false;
    if (!(target instanceof Element)) return true;
    if (target.closest("#chart, .chart-wrap, .buy-sheet, .options-sheet, .tutorial"))
      return false;
    if (target.closest("input, button, a, .open-pl-bar")) return false;
    // Respect scrollable panels that aren't already at the top.
    const scroller = target.closest(".summary-panel, .trade-panel");
    if (scroller && scroller.scrollTop > 2) return false;
    return true;
  }

  function onPullStart(ev) {
    const t = ev.touches && ev.touches[0];
    if (!t) return;
    if (!pullAllowedFrom(ev.target)) {
      pullStartY = null;
      return;
    }
    pullStartY = t.clientY;
    pullActive = false;
    pullDistance = 0;
  }

  function onPullMove(ev) {
    if (pullStartY == null || pullRunning) return;
    const t = ev.touches && ev.touches[0];
    if (!t) return;
    const dy = t.clientY - pullStartY;
    if (dy <= 0) {
      if (pullActive) resetPullIndicator();
      return;
    }
    pullActive = true;
    // Rubber-band so it never feels like a free-scrolling page.
    pullDistance = dy < PULL_MAX_PX ? dy : PULL_MAX_PX + (dy - PULL_MAX_PX) * 0.15;
    setPullIndicator(pullDistance, pullDistance >= PULL_TRIGGER_PX);
  }

  function onPullEnd() {
    if (pullStartY == null || pullRunning) return;
    const trigger = pullActive && pullDistance >= PULL_TRIGGER_PX;
    if (!trigger) {
      resetPullIndicator();
      return;
    }
    pullRunning = true;
    if (el.pullRefresh) {
      el.pullRefresh.classList.add("is-visible", "is-ready", "is-loading");
      el.pullRefresh.style.transform = "translate(-50%, 12px)";
    }
    if (el.pullRefreshLabel) el.pullRefreshLabel.textContent = "Updating…";
    forceAppUpdate();
  }

  function bankPctText(pct) {
    if (pct == null || !Number.isFinite(pct)) return null;
    if (pct > 0 && pct < 1) return "<1%";
    return `${pct.toFixed(0)}%`;
  }

  /** Suggested-buy row inside the Best Side block. */
  function renderBestSideSuggest(side, suggestion, opts = {}) {
    if (!el.bestSideSuggest) return;
    const s = suggestion || (side ? suggestForSide(side) : null);
    if (!side || !s || !(s.stake >= BUY_AMOUNT_MIN)) {
      el.bestSideSuggest.hidden = true;
      return;
    }
    const waiting = !!opts.waiting || !!s.lowProb;
    el.bestSideSuggest.hidden = false;
    el.bestSideSuggest.classList.toggle("is-waiting", waiting);
    el.bestSideSuggest.classList.toggle("is-below", !waiting && side === "below");
    const conf = s.pWin != null ? Math.round(s.pWin * 100) : null;
    if (el.bestSideSuggestAmount) {
      el.bestSideSuggestAmount.textContent = s.lowProb
        ? "Sit out"
        : `$${s.stake}${s.contracts ? ` · ${s.contracts} cts` : ""}`;
    }
    if (el.bestSideSuggestMeta) {
      if (s.lowProb) {
        el.bestSideSuggestMeta.textContent = `${
          side === "above" ? "Above" : "Below"
        } is the underdog${conf != null ? ` at ${conf}%` : ""} — no size worth risking`;
      } else {
        const roi =
          s.roiIfWin != null
            ? `${s.roiIfWin >= 0 ? "+" : ""}${s.roiIfWin.toFixed(0)}% if win`
            : "";
        const bankTxt = bankPctText(s.bankPct);
        const bank = bankTxt ? `risks ${bankTxt} of balance` : "";
        const lead = opts.waiting
          ? `${side === "above" ? "Above" : "Below"} if you enter`
          : `${side === "above" ? "Above" : "Below"}`;
        el.bestSideSuggestMeta.textContent = [lead, roi, bank]
          .filter(Boolean)
          .join(" · ");
      }
    }
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

  function markClearEdgeGone() {
    const now = Date.now();
    if (!lastClearEdgeGoneAt) lastClearEdgeGoneAt = now;
    if (now - lastClearEdgeGoneAt >= EDGE_GONE_RESET_MS) {
      lastClearEdgeAlertKey = "none";
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
      renderBestSideSuggest(null, null);
      setRoiCardBest(null);
      setDockBestDetail("—", null);
      lastBestSideKey = null;
      lastBestPick = null;
      markClearEdgeGone();
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
      renderBestSideSuggest(null, null);
      setRoiCardBest(null);
      setDockBestDetail("—", null);
      lastBestPick = null;
      markClearEdgeGone();
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
      // Still show what we'd risk on the better-priced side, marked as a wait.
      renderBestSideSuggest(best.side, suggestStakeForEdge(best), {
        waiting: true,
      });
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
      markClearEdgeGone();
      return;
    }

    lastClearEdgeGoneAt = 0;
    const suggestion = suggestStakeForEdge(best);
    const suggestStake =
      suggestion && suggestion.stake >= BUY_AMOUNT_MIN ? suggestion.stake : null;
    if (suggestStake != null && suggestion) {
      best = {
        ...best,
        contracts: suggestion.contracts || best.contracts,
        total: suggestion.total || best.total,
        profitIfWin: suggestion.profitIfWin || best.profitIfWin,
        roiIfWin:
          suggestion.roiIfWin != null ? suggestion.roiIfWin : best.roiIfWin,
      };
    }
    lastBestPick = {
      side: best.side,
      askCents: best.askCents,
      pWin: best.pWin,
      suggestedStake: suggestStake,
      suggestion,
    };
    const openPos = demo.position;
    const sameAsOpen = !!(openPos && openPos.side === best.side);
    const oppositeOpen = !!(openPos && openPos.side !== best.side);
    const label = oppositeOpen
      ? best.side === "above"
        ? "BEST ABOVE"
        : "BEST BELOW"
      : sameAsOpen
        ? best.side === "above"
          ? "ADD ABOVE"
          : "ADD BELOW"
        : best.side === "above"
          ? "BUY ABOVE"
          : "BUY BELOW";
    if (el.bestSideLabel) el.bestSideLabel.textContent = label;
    if (el.bestSideAmount) {
      if (oppositeOpen) {
        el.bestSideAmount.textContent = `Edge vs your ${
          openPos.side === "above" ? "Above" : "Below"
        } · close to flip`;
      } else if (suggestStake != null) {
        el.bestSideAmount.textContent = `Tap to buy $${suggestStake}`;
      } else if (tradeStake <= 0) {
        el.bestSideAmount.textContent = "Set a trade size";
      } else {
        el.bestSideAmount.textContent = `${
          sameAsOpen ? "Add" : "Buy"
        } $${tradeStake} · ${best.contracts} contract${
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
      const openNote = sameAsOpen
        ? ` · open ${openPos.contracts} cts`
        : oppositeOpen
          ? ` · opposite your open ${openPos.side === "above" ? "Above" : "Below"}`
          : "";
      const sizeNote =
        suggestion && suggestStake != null && !oppositeOpen
          ? ` · ~${suggestion.bankPct.toFixed(0)}% bal`
          : "";
      el.bestSideMeta.textContent =
        `${conf}% model · ask ${best.askCents}¢ · ${roiTxt}${sizeNote} · live ${
          lead >= 0 ? "+" : ""
        }$${lead.toFixed(0)} · ${m}:${String(s).padStart(2, "0")} left${openNote}`;
    }
    renderBestSideSuggest(best.side, suggestion, {
      waiting: oppositeOpen,
    });
    setRoiCardBest(best.side);
    setDockBestDetail(
      suggestStake != null
        ? `${best.side === "above" ? "Above" : "Below"} $${suggestStake}`
        : `${best.side === "above" ? "Above" : "Below"} ${best.askCents}¢`,
      best.side
    );

    const key = clear
      ? `${best.side}:${suggestStake || tradeStake}:${best.contracts}:${
          openPos ? openPos.side : "flat"
        }`
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
    const pos = demo.position;
    const canAbove = canBuySide("above");
    const canBelow = canBuySide("below");
    if (el.dockAbovePct) {
      el.dockAbovePct.textContent =
        lastRoiAsks.above != null ? `${Math.round(lastRoiAsks.above)}¢` : "—";
    }
    if (el.dockBelowPct) {
      el.dockBelowPct.textContent =
        lastRoiAsks.below != null ? `${Math.round(lastRoiAsks.below)}¢` : "—";
    }
    if (el.dockBuyAbove) {
      // Same-side add must stay tappable while a position is open.
      el.dockBuyAbove.disabled = !canAbove;
      el.dockBuyAbove.setAttribute("aria-disabled", canAbove ? "false" : "true");
      const label = el.dockBuyAbove.querySelector(".dock-label");
      if (label) {
        label.textContent =
          pos && pos.side === "above" ? "Add Above" : "Buy Above";
      }
    }
    if (el.dockBuyBelow) {
      el.dockBuyBelow.disabled = !canBelow;
      el.dockBuyBelow.setAttribute("aria-disabled", canBelow ? "false" : "true");
      const label = el.dockBuyBelow.querySelector(".dock-label");
      if (label) {
        label.textContent =
          pos && pos.side === "below" ? "Add Below" : "Buy Below";
      }
    }
    if (el.dockBuyBest) {
      const bestSide = lastBestPick && lastBestPick.side;
      const canBest = !!(bestSide && canBuySide(bestSide));
      el.dockBuyBest.disabled = !canBest;
      const label = el.dockBuyBest.querySelector(".dock-label");
      if (label) {
        label.textContent =
          pos && bestSide && pos.side === bestSide ? "Add Best" : "Best";
      }
    }
  }

  function setTradeStake(n) {
    tradeStake = Math.max(1, Math.min(100, Math.round(Number(n) || 1)));
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
        attributionLogo: false,
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
        // Pack more history into the first viewport; user can still pinch-zoom.
        barSpacing: 3.25,
        minBarSpacing: 1.25,
        rightOffset: 4,
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
        const extras = [
          lastTarget,
          lastSettlementAvg,
          lastBreakevenPrice,
          demo.position && demo.position.entrySpot,
          demo.position && demo.position.beat,
        ].filter((v) => v != null && Number.isFinite(v));
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

  function clearTargetSeries() {
    if (targetSeries && chart) {
      try {
        chart.removeSeries(targetSeries);
      } catch {
        // ignore
      }
    }
    targetSeries = null;
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

  function clearBreakevenLines() {
    if (breakevenLine && series) {
      try {
        series.removePriceLine(breakevenLine);
      } catch {
        // ignore
      }
    }
    if (entryLine && series) {
      try {
        series.removePriceLine(entryLine);
      } catch {
        // ignore
      }
    }
    breakevenLine = null;
    entryLine = null;
    lastBreakevenPrice = null;
  }

  function buildFlatLineData(price) {
    if (!Number.isFinite(price) || !lastCandleData.length) return [];
    const t0 = lastCandleData[0].time;
    const t1 = lastCandleData[lastCandleData.length - 1].time;
    if (t0 == null || t1 == null) return [];
    if (t0 === t1) return [{ time: t0, value: price }];
    return [
      { time: t0, value: price },
      { time: t1, value: price },
    ];
  }

  function applyBreakevenLines(beat, entrySpot, modelBe, side) {
    ensureChart();
    clearBreakevenLines();
    if (!series || !demo.position) return;

    // Price to beat stays on TARGET — only add trade-specific model / entry lines.
    const winAt = beat != null && Number.isFinite(Number(beat)) ? Number(beat) : null;
    lastBreakevenPrice = winAt;

    if (
      modelBe != null &&
      Number.isFinite(modelBe) &&
      (winAt == null || Math.abs(modelBe - winAt) > 8)
    ) {
      entryLine = series.createPriceLine({
        price: modelBe,
        color: "#ffd28a",
        lineWidth: 2,
        lineStyle: (ensureChart.LineStyle && ensureChart.LineStyle.Dotted) || 1,
        axisLabelVisible: true,
        title: "MODEL B/E",
      });
      lastBreakevenPrice = modelBe;
    } else if (entrySpot != null && Number.isFinite(entrySpot)) {
      entryLine = series.createPriceLine({
        price: entrySpot,
        color: "#8ab4ff",
        lineWidth: 1,
        lineStyle: (ensureChart.LineStyle && ensureChart.LineStyle.Dotted) || 1,
        axisLabelVisible: true,
        title: "ENTRY",
      });
    }

    try {
      series.applyOptions({});
    } catch {
      // ignore
    }
  }

  function applyTargetLine(target, title) {
    const price = target == null || target === "" ? NaN : Number(target);
    lastTarget = Number.isFinite(price) ? price : null;
    ensureChart();
    if (!chart) return;

    if (lastTarget == null) {
      clearTargetLine();
      if (targetSeries) {
        try {
          targetSeries.setData([]);
        } catch {
          // ignore
        }
      }
      return;
    }

    const label = title || "TO BEAT";
    const dash =
      (ensureChart.LineStyle && ensureChart.LineStyle.Dashed) || 2;

    // Single axis label via candle price line (avoid a second series label).
    if (series) {
      clearTargetLine();
      targetLine = series.createPriceLine({
        price: lastTarget,
        color: "#f4fff8",
        lineWidth: 2,
        lineStyle: dash,
        axisLabelVisible: true,
        title: label,
      });
    }

    // Full-width dashed line — no last-value label (that caused the double TO BEAT).
    if (!targetSeries) {
      targetSeries = chart.addLineSeries({
        color: "rgba(244,255,248,0.95)",
        lineWidth: 2,
        lineStyle: dash,
        crosshairMarkerVisible: false,
        lastValueVisible: false,
        priceLineVisible: false,
        title: "",
      });
    }
    const flat = buildFlatLineData(lastTarget);
    if (flat.length) {
      try {
        targetSeries.setData(flat);
      } catch {
        // ignore
      }
    }

    try {
      if (series) series.applyOptions({});
    } catch {
      // ignore
    }
  }

  function reapplyChartOverlays() {
    if (lastTarget != null && Number.isFinite(lastTarget)) {
      applyTargetLine(lastTarget, "TO BEAT");
    }
    if (lastSettlementAvg != null && Number.isFinite(lastSettlementAvg)) {
      applySettleLine(lastSettlementAvg);
    }
    if (demo.position) {
      const beSpot = modelBreakevenSpot(demo.position, secondsLeft());
      applyBreakevenLines(
        demo.position.beat,
        demo.position.entrySpot,
        beSpot,
        demo.position.side
      );
      const beatKeep =
        demo.position.beat != null && Number.isFinite(Number(demo.position.beat))
          ? Number(demo.position.beat)
          : lastTarget;
      if (beatKeep != null && Number.isFinite(beatKeep)) {
        applyTargetLine(beatKeep, "TO BEAT");
      }
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
      const beatRaw = data.price_to_beat ?? data.target;
      const beat =
        beatRaw == null || beatRaw === "" ? null : Number(beatRaw);
      const beatOk = beat != null && Number.isFinite(beat) ? beat : null;
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

      if ((!data.ok && beatOk == null) || data.waiting_next) {
        if (prevTicker) settleDemoPosition(prevTicker);
        else if (demo.position) settleDemoPosition(demo.position.ticker);
        setStatus("warn", data.error || "Waiting for next window");
        el.targetValue.textContent = beatOk != null ? money(beatOk) : "—";
        el.targetMeta.textContent = data.error || "Next Kalshi 15m opening…";
        if (beatOk == null) applyTargetLine(null);
        else applyTargetLine(beatOk, "TO BEAT");
        startRolloverBurst();
        scheduleBoundaryRefresh(data.close_time);
        return;
      }

      if (beatOk == null) {
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
        el.targetValue.textContent = money(beatOk);
        const win = formatWindow(data.close_time, data.close_et);
        el.targetMeta.textContent = win
          ? `This window settles ${win}`
          : "Kalshi 15-minute market";
        applyTargetLine(beatOk, "TO BEAT");
        maybeChimeNewFifteenTarget(beatOk, data.ticker, data.source, data.close_et);
        if (el.spotValue && el.spotValue.dataset.last) {
          updateSpot(Number(el.spotValue.dataset.last));
        }
        if (rolled || forceCandles || data.settlement_mode) {
          refreshCandles().then(() => applyTargetLine(beatOk, "TO BEAT"));
        } else {
          applyTargetLine(beatOk, "TO BEAT");
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
      lastCandleData = candles;
      const grew =
        candles.length > lastCandleCount + 20 ||
        (lastCandleCount > 0 && candles.length < lastCandleCount - 20);
      series.setData(candles);
      // Price lines can drop on setData — always redraw beat / overlays.
      reapplyChartOverlays();
      if (!el.spotValue?.dataset.last && candles.length) {
        updateSpot(candles[candles.length - 1].close);
      }
      resizeChart();
      // Re-fit when history depth jumps (e.g. BRTI-only → merged Coinbase history).
      if (!fittedOnce || grew) {
        chart.timeScale().fitContent();
        fittedOnce = true;
        lastCandleCount = candles.length;
        // Fit can run before overlays paint; redraw beat once more.
        reapplyChartOverlays();
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
    lastCandleCount = 0;
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
    if (el.tradeHistoryClear) {
      el.tradeHistoryClear.addEventListener("click", () => clearTradeHistory());
    }
    if (el.buySuggestUse) {
      el.buySuggestUse.addEventListener("click", () => {
        if (buySuggestStake != null) setBuyAmountUi(buySuggestStake, true);
      });
    }
    if (el.appUpdate) {
      el.appUpdate.addEventListener("click", () => forceAppUpdate());
      refreshVersionLine();
    }
    document.addEventListener("touchstart", onPullStart, { passive: true });
    document.addEventListener("touchmove", onPullMove, { passive: true });
    document.addEventListener("touchend", onPullEnd, { passive: true });
    document.addEventListener("touchcancel", () => resetPullIndicator(), {
      passive: true,
    });
    if (el.accountExport) {
      el.accountExport.addEventListener("click", () => exportAccountBackup());
    }
    if (el.accountImport && el.accountImportFile) {
      el.accountImport.addEventListener("click", () => el.accountImportFile.click());
      el.accountImportFile.addEventListener("change", () => {
        const file = el.accountImportFile.files && el.accountImportFile.files[0];
        importAccountBackupFile(file);
        el.accountImportFile.value = "";
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
    if (el.openPlAdd) {
      el.openPlAdd.addEventListener("click", () => {
        const pos = demo.position;
        if (!pos || !pos.side) {
          setStatus("warn", "No open position to add to");
          return;
        }
        openBuySheet(pos.side);
      });
    }
    if (el.openPlToggle) {
      el.openPlToggle.addEventListener("click", () => {
        setOpenPlCollapsed(!openPlCollapsed);
      });
    }
    if (el.openPlBar) {
      let dragY = null;
      const onStart = (y) => {
        dragY = y;
      };
      const onEnd = (y) => {
        if (dragY == null) return;
        const dy = y - dragY;
        dragY = null;
        if (dy > 28) setOpenPlCollapsed(true);
        else if (dy < -28) setOpenPlCollapsed(false);
      };
      el.openPlBar.addEventListener(
        "touchstart",
        (ev) => {
          if (ev.touches && ev.touches[0]) onStart(ev.touches[0].clientY);
        },
        { passive: true }
      );
      el.openPlBar.addEventListener(
        "touchend",
        (ev) => {
          const t = ev.changedTouches && ev.changedTouches[0];
          if (t) onEnd(t.clientY);
        },
        { passive: true }
      );
    }
    if (el.buySheetX) {
      el.buySheetX.addEventListener("click", () => dismissBuySheet());
    }
    if (el.buyBackdrop) {
      el.buyBackdrop.addEventListener("click", () => dismissBuySheet());
    }
    if (el.buyAmount) {
      const syncAmt = () => {
        const amt = clampBuyAmount(el.buyAmount.value);
        el.buyAmount.value = String(amt);
        setBuyAmountUi(amt, true);
        refreshBuySheetPreview();
      };
      el.buyAmount.addEventListener("input", () => {
        // Allow free typing; clamp lightly only when valid number.
        const raw = Number(el.buyAmount.value);
        if (Number.isFinite(raw) && raw >= BUY_AMOUNT_MIN) {
          setBuyAmountUi(Math.min(buyAmountCap(), Math.round(raw)), false);
          refreshBuySheetPreview();
        }
      });
      el.buyAmount.addEventListener("change", syncAmt);
      el.buyAmount.addEventListener("blur", syncAmt);
    }
    if (el.buyRange) {
      const onRange = () => {
        setBuyAmountUi(el.buyRange.value, true);
        if (el.buyAmount) el.buyAmount.value = String(buySheetAmount);
        refreshBuySheetPreview();
      };
      el.buyRange.addEventListener("input", onRange);
      el.buyRange.addEventListener("change", onRange);
    }
    document.querySelectorAll(".buy-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const amt = Number(btn.dataset.amt);
        if (!Number.isFinite(amt)) return;
        setBuyAmountUi(amt, true);
        if (el.buyAmount) el.buyAmount.value = String(buySheetAmount);
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
      el.bestSide.title = "Tap to buy suggested size";
      el.bestSide.addEventListener("click", () => {
        if (lastBestPick && lastBestPick.side) {
          openBuySheet(lastBestPick.side, { useSuggest: true });
        } else if (demo.on) setStatus("warn", "No clear Best Side yet");
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
    setupEphemeralBanner();
    hydrateDemoFromServer().finally(() => {
      refreshTarget()
        .then(() => refreshCandles())
        .then(refreshSpot);
    });
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
