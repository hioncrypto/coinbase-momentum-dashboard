// ==UserScript==
// @name         Kalshi BTC 15m Target → TradingView
// @namespace    kalshi-btc-target
// @version      1.1.0
// @description  Auto-draws Kalshi KXBTC15M Target Price as a horizontal line on TradingView BTCUSD (works on Android via Firefox + Tampermonkey)
// @author       hioncrypto
// @match        https://www.tradingview.com/*
// @match        https://tradingview.com/*
// @match        https://*.tradingview.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM.xmlHttpRequest
// @connect      api.elections.kalshi.com
// @connect      localhost
// @connect      127.0.0.1
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  /**
   * Optional: if Kalshi blocks direct calls, set your deployed proxy base, e.g.
   *   "https://your-host.example"  (serves GET /api/target from kalshi-btc-target)
   * Leave empty to call Kalshi directly via GM_xmlhttpRequest.
   */
  const PROXY_BASE = "";

  const KALSHI_URL =
    "https://api.elections.kalshi.com/trade-api/v2/markets?limit=5&status=open&series_ticker=KXBTC15M";
  const POLL_MS = 10_000;
  const ROOT_ID = "kalshi-tv-target-root";

  let state = {
    target: null,
    ticker: null,
    closeTime: null,
    windowLabel: null,
    error: null,
  };
  let rafPending = false;
  let boundaryTimer = null;

  function gmRequest(url) {
    const xhr = typeof GM_xmlhttpRequest === "function"
      ? GM_xmlhttpRequest
      : GM && GM.xmlHttpRequest
        ? GM.xmlHttpRequest.bind(GM)
        : null;
    if (!xhr) {
      return fetch(url, { cache: "no-store" }).then(async (r) => {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
    }
    return new Promise((resolve, reject) => {
      xhr({
        method: "GET",
        url,
        headers: { Accept: "application/json" },
        anonymous: true,
        onload: (res) => {
          if (res.status < 200 || res.status >= 300) {
            reject(new Error("HTTP " + res.status));
            return;
          }
          try {
            resolve(JSON.parse(res.responseText));
          } catch (e) {
            reject(e);
          }
        },
        onerror: () => reject(new Error("network error")),
        ontimeout: () => reject(new Error("timeout")),
      });
    });
  }

  function parseTarget(market) {
    if (!market) return null;
    if (typeof market.floor_strike === "number" && Number.isFinite(market.floor_strike)) {
      return market.floor_strike;
    }
    const sub = market.yes_sub_title || market.no_sub_title || "";
    const m = sub.match(/Target\s*Price:\s*\$?\s*([0-9,]+(?:\.\d+)?)/i);
    if (!m) return null;
    const n = Number(m[1].replace(/,/g, ""));
    return Number.isFinite(n) ? n : null;
  }

  function windowLabel(closeIso) {
    if (!closeIso) return null;
    try {
      return (
        new Date(closeIso).toLocaleString(undefined, {
          hour: "numeric",
          minute: "2-digit",
          hour12: true,
        }) + " close"
      );
    } catch {
      return closeIso;
    }
  }

  async function fetchTarget() {
    if (PROXY_BASE) {
      const data = await gmRequest(PROXY_BASE.replace(/\/$/, "") + "/api/target");
      return {
        target: data.target,
        ticker: data.ticker,
        closeTime: data.close_time,
        windowLabel: windowLabel(data.close_time),
        error: data.error || null,
      };
    }
    const data = await gmRequest(KALSHI_URL);
    const markets = data.markets || [];
    const market =
      markets.find((m) => m.status === "active" || m.status === "open") || markets[0];
    if (!market) {
      return { target: null, ticker: null, closeTime: null, windowLabel: null, error: "No open KXBTC15M market" };
    }
    const target = parseTarget(market);
    return {
      target,
      ticker: market.ticker || null,
      closeTime: market.close_time || null,
      windowLabel: windowLabel(market.close_time),
      error: target == null ? "Target price TBD" : null,
    };
  }

  function scheduleBoundary(closeIso) {
    if (boundaryTimer) clearTimeout(boundaryTimer);
    if (!closeIso) return;
    const closeMs = Date.parse(closeIso);
    if (!Number.isFinite(closeMs)) return;
    const wait = Math.max(5000, closeMs + 3000 - Date.now());
    boundaryTimer = setTimeout(() => refresh(), wait);
  }

  async function refresh() {
    try {
      state = await fetchTarget();
      scheduleBoundary(state.closeTime);
      scheduleRender();
    } catch (err) {
      state = { ...state, error: String(err.message || err) };
      scheduleRender();
    }
  }

  function pageHaystack() {
    const chunks = [location.href, document.title];
    const selectors = [
      "[data-name='legend-source-item']",
      "[class*='legendSource']",
      "#header-toolbar-symbol-search",
      "[data-name='legend-series-item']",
      "div[class*='titleWrapper']",
      "[class*='chart-controls-bar']",
    ];
    for (const sel of selectors) {
      document.querySelectorAll(sel).forEach((el) => {
        const t = (el.textContent || "").trim();
        if (t && t.length < 80) chunks.push(t);
      });
    }
    return chunks.join(" ").toLowerCase();
  }

  function isBtcUsdChart() {
    const hay = pageHaystack();
    return [
      "btcusd",
      "btcusdt",
      "btc/usd",
      "btc-usd",
      "xbtusd",
      "coinbase:btc",
      "binance:btc",
      "bitstamp:btc",
      "kraken:xbt",
    ].some((n) => hay.includes(n));
  }

  function ensureDom() {
    let root = document.getElementById(ROOT_ID);
    if (!root) {
      root = document.createElement("div");
      root.id = ROOT_ID;
      root.innerHTML = `
        <div id="kalshi-tv-target-line"></div>
        <div id="kalshi-tv-target-label"></div>
        <div id="kalshi-tv-target-badge"></div>
      `;
      const style = document.createElement("style");
      style.textContent = `
        #kalshi-tv-target-root{position:fixed;inset:0;pointer-events:none;z-index:2147483646;font-family:IBM Plex Sans,Segoe UI,sans-serif}
        #kalshi-tv-target-line{position:fixed;left:0;right:56px;height:0;border-top:1.5px dashed #1ac96b;opacity:.95}
        #kalshi-tv-target-label{position:fixed;right:60px;transform:translateY(-50%);background:rgba(10,18,14,.9);color:#1ac96b;border:1px solid rgba(26,201,107,.55);padding:2px 8px;font-size:11px;font-weight:600;border-radius:2px;white-space:nowrap}
        #kalshi-tv-target-badge{position:fixed;top:max(8px, env(safe-area-inset-top));left:50%;transform:translateX(-50%);background:rgba(10,18,14,.92);color:#d7ffe8;border:1px solid rgba(26,201,107,.45);padding:4px 10px;font-size:11px;border-radius:4px;max-width:92vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
        #kalshi-tv-target-badge[data-status="warn"]{color:#ffd28a;border-color:rgba(255,210,138,.5)}
      `;
      document.documentElement.appendChild(style);
      document.documentElement.appendChild(root);
    }
    return {
      root,
      line: document.getElementById("kalshi-tv-target-line"),
      label: document.getElementById("kalshi-tv-target-label"),
      badge: document.getElementById("kalshi-tv-target-badge"),
    };
  }

  function priceToY(targetPrice) {
    const axisCandidates = [
      ...document.querySelectorAll('[class*="price-axis"]'),
      ...document.querySelectorAll('[data-name="price-axis"]'),
    ];
    const points = [];
    const take = (node) => {
      if (!node || node.children.length > 0) return;
      const raw = (node.textContent || "").trim();
      if (!raw || raw.length > 18) return;
      let price = null;
      const plain = raw.replace(/,/g, "");
      if (/^-?\d+(\.\d+)?$/.test(plain)) price = Number(plain);
      else {
        const km = plain.match(/^(-?\d+(?:\.\d+)?)[Kk]$/);
        if (km) price = Number(km[1]) * 1000;
      }
      if (price == null || !Number.isFinite(price) || price < 1000 || price > 5e6) return;
      const rect = node.getBoundingClientRect();
      if (rect.height <= 0 || rect.width <= 0) return;
      points.push({ price, y: rect.top + rect.height / 2 });
    };
    if (axisCandidates.length) {
      axisCandidates.forEach((ax) => ax.querySelectorAll("div,span").forEach(take));
    } else {
      document.querySelectorAll("div,span").forEach((node) => {
        const rect = node.getBoundingClientRect();
        if (rect.left < window.innerWidth - 100) return;
        take(node);
      });
    }
    points.sort((a, b) => a.price - b.price);
    const unique = [];
    for (const p of points) {
      const prev = unique[unique.length - 1];
      if (!prev || Math.abs(prev.price - p.price) > 0.01) unique.push(p);
    }
    if (unique.length < 2) return null;
    let lo = unique[0];
    let hi = unique[unique.length - 1];
    for (let i = 0; i < unique.length - 1; i++) {
      if (unique[i].price <= targetPrice && unique[i + 1].price >= targetPrice) {
        lo = unique[i];
        hi = unique[i + 1];
        break;
      }
    }
    if (Math.abs(hi.price - lo.price) < 1e-9) return lo.y;
    const t = (targetPrice - lo.price) / (hi.price - lo.price);
    return lo.y + t * (hi.y - lo.y);
  }

  function money(n) {
    return n.toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function render() {
    rafPending = false;
    const { root, line, label, badge } = ensureDom();
    root.style.display = "block";
    const onBtc = isBtcUsdChart();
    if (!onBtc) {
      line.style.display = "none";
      label.style.display = "none";
      badge.dataset.status = "warn";
      badge.textContent = "Kalshi target: open BTCUSD on TradingView";
      return;
    }
    if (state.error && state.target == null) {
      line.style.display = "none";
      label.style.display = "none";
      badge.dataset.status = "warn";
      badge.textContent = "Kalshi: " + state.error;
      return;
    }
    if (state.target == null) {
      line.style.display = "none";
      label.style.display = "none";
      badge.dataset.status = "warn";
      badge.textContent = "Kalshi: waiting for target…";
      return;
    }
    const y = priceToY(state.target);
    const bit = state.windowLabel ? " · " + state.windowLabel : "";
    if (y == null) {
      line.style.display = "none";
      label.style.display = "none";
      badge.dataset.status = "warn";
      badge.textContent = "TARGET " + money(state.target) + " (axis loading…)";
      return;
    }
    line.style.display = "block";
    label.style.display = "block";
    line.style.top = Math.round(y) + "px";
    label.style.top = Math.round(y) + "px";
    label.textContent = "TARGET " + money(state.target) + bit;
    badge.dataset.status = "ok";
    badge.textContent = "Kalshi 15m TARGET " + money(state.target) + bit;
  }

  function scheduleRender() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(render);
  }

  ensureDom();
  refresh();
  setInterval(refresh, POLL_MS);
  window.addEventListener("resize", scheduleRender, { passive: true });
  window.addEventListener("scroll", scheduleRender, { passive: true, capture: true });
  new MutationObserver(() => scheduleRender()).observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
  });
})();
