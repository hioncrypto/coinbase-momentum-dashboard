/**
 * Polls Kalshi KXBTC15M ("BTC Up or Down - 15 minutes") and keeps the
 * active Target Price in extension storage so TradingView content scripts
 * can draw / refresh the horizontal TARGET line on an ongoing basis.
 */

const KALSHI_MARKETS_URL =
  "https://api.elections.kalshi.com/trade-api/v2/markets?limit=5&status=open&series_ticker=KXBTC15M";
const SERIES = "KXBTC15M";
const POLL_ALARM = "kalshi-target-poll";
const BOUNDARY_ALARM = "kalshi-target-boundary";
const POLL_MINUTES = 1; // Chrome MV3 minimum; boundary alarm hits each 15m rollover

const DEFAULT_STATE = {
  enabled: true,
  series: SERIES,
  target: null,
  ticker: null,
  eventTicker: null,
  windowLabel: null,
  openTime: null,
  closeTime: null,
  fetchedAt: null,
  error: null,
};

async function getState() {
  const { kalshiTarget } = await chrome.storage.local.get("kalshiTarget");
  return { ...DEFAULT_STATE, ...(kalshiTarget || {}) };
}

async function setState(patch) {
  const prev = await getState();
  const next = { ...prev, ...patch };
  await chrome.storage.local.set({ kalshiTarget: next });
  return next;
}

function parseTargetFromMarket(market) {
  if (!market) return null;

  if (typeof market.floor_strike === "number" && Number.isFinite(market.floor_strike)) {
    return market.floor_strike;
  }

  const subtitle = market.yes_sub_title || market.no_sub_title || "";
  const match = subtitle.match(/Target\s*Price:\s*\$?\s*([0-9,]+(?:\.\d+)?)/i);
  if (match) {
    const n = Number(match[1].replace(/,/g, ""));
    if (Number.isFinite(n)) return n;
  }

  return null;
}

function windowLabelFromMarket(market) {
  const close = market.close_time ? new Date(market.close_time) : null;
  if (!close || Number.isNaN(close.getTime())) return null;
  try {
    const stamp = close
      .toLocaleString("en-US", {
        timeZone: "America/New_York",
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      })
      .replace(" AM", "am")
      .replace(" PM", "pm");
    return `Price to beat • ${stamp} ET`;
  } catch {
    return close.toISOString();
  }
}

async function fetchActiveTarget() {
  const res = await fetch(KALSHI_MARKETS_URL, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Kalshi HTTP ${res.status}`);
  }
  const data = await res.json();
  const markets = Array.isArray(data.markets) ? data.markets : [];
  const withBeat = markets.find(
    (m) =>
      (m.status === "active" || m.status === "open") &&
      parseTargetFromMarket(m) != null
  );
  const market =
    withBeat ||
    markets.find((m) => m.status === "active" || m.status === "open") ||
    markets[0];

  if (!market) {
    return {
      target: null,
      ticker: null,
      eventTicker: null,
      windowLabel: null,
      openTime: null,
      closeTime: null,
      error: "No open KXBTC15M market yet",
    };
  }

  const target = parseTargetFromMarket(market);
  if (target == null) {
    const prev = await getState();
    if (prev.target != null) {
      return {
        target: prev.target,
        ticker: market.ticker || prev.ticker,
        eventTicker: market.event_ticker || prev.eventTicker,
        windowLabel: windowLabelFromMarket(market) || prev.windowLabel,
        openTime: market.open_time || prev.openTime,
        closeTime: market.close_time || prev.closeTime,
        error: "Waiting for new 15m Price to beat…",
      };
    }
    return {
      target: null,
      ticker: market.ticker || null,
      eventTicker: market.event_ticker || null,
      windowLabel: windowLabelFromMarket(market),
      openTime: market.open_time || null,
      closeTime: market.close_time || null,
      error: "Price to beat TBD (waiting for window open)",
    };
  }

  return {
    target,
    ticker: market.ticker || null,
    eventTicker: market.event_ticker || null,
    windowLabel: windowLabelFromMarket(market),
    openTime: market.open_time || null,
    closeTime: market.close_time || null,
    error: null,
  };
}

function scheduleBoundaryAlarm(closeTimeIso) {
  if (!closeTimeIso) {
    chrome.alarms.clear(BOUNDARY_ALARM);
    return;
  }
  const closeMs = Date.parse(closeTimeIso);
  if (!Number.isFinite(closeMs)) return;

  // Refresh a few seconds after the window rolls so the new target is live.
  const when = Math.max(Date.now() + 5_000, closeMs + 3_000);
  chrome.alarms.create(BOUNDARY_ALARM, { when });
}

async function refreshTarget(reason = "poll") {
  const state = await getState();
  if (!state.enabled) {
    return state;
  }

  try {
    const live = await fetchActiveTarget();
    const next = await setState({
      ...live,
      series: SERIES,
      fetchedAt: new Date().toISOString(),
    });
    scheduleBoundaryAlarm(next.closeTime);
    console.debug("[kalshi-target]", reason, next.target, next.ticker, next.error);
    return next;
  } catch (err) {
    const next = await setState({
      error: String(err?.message || err),
      fetchedAt: new Date().toISOString(),
    });
    console.warn("[kalshi-target] fetch failed", err);
    return next;
  }
}

chrome.runtime.onInstalled.addListener(async () => {
  await setState(DEFAULT_STATE);
  chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
  await refreshTarget("install");
});

chrome.runtime.onStartup.addListener(async () => {
  chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
  await refreshTarget("startup");
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === POLL_ALARM || alarm.name === BOUNDARY_ALARM) {
    await refreshTarget(alarm.name);
  }
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    if (msg?.type === "get-target") {
      sendResponse(await getState());
      return;
    }
    if (msg?.type === "refresh-target") {
      sendResponse(await refreshTarget("manual"));
      return;
    }
    if (msg?.type === "set-enabled") {
      const next = await setState({ enabled: Boolean(msg.enabled) });
      if (next.enabled) await refreshTarget("enable");
      sendResponse(next);
      return;
    }
    sendResponse(null);
  })();
  return true;
});

// Kick a first fetch if the SW wakes without install/startup.
chrome.alarms.create(POLL_ALARM, { periodInMinutes: POLL_MINUTES });
refreshTarget("wake");
