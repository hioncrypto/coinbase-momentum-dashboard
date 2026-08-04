/**
 * Overlay Kalshi's 15-minute BTC Target Price as a horizontal line on
 * TradingView charts. Re-renders whenever storage updates (new 15m window).
 */

(() => {
  const ROOT_ID = "kalshi-tv-target-root";
  const LINE_ID = "kalshi-tv-target-line";
  const LABEL_ID = "kalshi-tv-target-label";
  const BADGE_ID = "kalshi-tv-target-badge";

  /** @type {null | {target:number|null, enabled:boolean, ticker:string|null, windowLabel:string|null, error:string|null, closeTime:string|null}} */
  let state = null;
  let rafPending = false;
  let lastY = null;

  function pageHaystack() {
    const chunks = [location.href, document.title];
    // TradingView often keeps the symbol out of the URL (/chart/XXXX/) —
    // pull common header / legend nodes so BTCUSD still matches.
    const selectors = [
      "[data-name='legend-source-item']",
      "[class*='legendSource']",
      "[class*='chart-controls-bar']",
      "#header-toolbar-symbol-search",
      "[data-name='legend-series-item']",
      "div[class*='titleWrapper']",
    ];
    for (const sel of selectors) {
      for (const el of document.querySelectorAll(sel)) {
        const t = (el.textContent || "").trim();
        if (t && t.length < 80) chunks.push(t);
      }
    }
    return chunks.join(" ").toLowerCase();
  }

  function isBtcUsdChart() {
    const hay = pageHaystack();
    // Common TradingView BTCUSD / BTCUSDT symbol forms
    const needles = [
      "btcusd",
      "btcusdt",
      "btc/usd",
      "btc-usd",
      "xbtusd",
      "coinbase:btc",
      "binance:btc",
      "bitstamp:btc",
      "kraken:xbt",
      "symbol=btc",
    ];
    return needles.some((n) => hay.includes(n));
  }

  function ensureDom() {
    let root = document.getElementById(ROOT_ID);
    if (!root) {
      root = document.createElement("div");
      root.id = ROOT_ID;
      root.setAttribute("data-kalshi-target", "1");
      document.documentElement.appendChild(root);
    }

    let line = document.getElementById(LINE_ID);
    if (!line) {
      line = document.createElement("div");
      line.id = LINE_ID;
      root.appendChild(line);
    }

    let label = document.getElementById(LABEL_ID);
    if (!label) {
      label = document.createElement("div");
      label.id = LABEL_ID;
      root.appendChild(label);
    }

    let badge = document.getElementById(BADGE_ID);
    if (!badge) {
      badge = document.createElement("div");
      badge.id = BADGE_ID;
      root.appendChild(badge);
    }

    return { root, line, label, badge };
  }

  function hideOverlay() {
    const root = document.getElementById(ROOT_ID);
    if (root) root.style.display = "none";
  }

  /**
   * Map a price to a Y pixel by reading TradingView's right price-axis labels.
   * Returns null if the axis can't be parsed yet.
   */
  function priceToY(targetPrice) {
    const axisCandidates = [
      ...document.querySelectorAll('[class*="price-axis"]'),
      ...document.querySelectorAll('[data-name="price-axis"]'),
      ...document.querySelectorAll(".chart-markup-table .price-axis"),
    ];

    /** @type {{price:number, y:number}[]} */
    const points = [];

    const collectFrom = (el) => {
      const labels = el.querySelectorAll("div, span");
      for (const node of labels) {
        if (node.children.length > 0) continue;
        const raw = (node.textContent || "").trim();
        if (!raw || raw.length > 18) continue;
        // Accept 63335.98 / 63,335.98 / 63.335K style
        let price = null;
        const plain = raw.replace(/,/g, "");
        if (/^-?\d+(\.\d+)?$/.test(plain)) {
          price = Number(plain);
        } else {
          const km = plain.match(/^(-?\d+(?:\.\d+)?)[Kk]$/);
          if (km) price = Number(km[1]) * 1000;
        }
        if (price == null || !Number.isFinite(price) || price <= 0) continue;
        // BTC price sanity for a USD chart
        if (price < 1000 || price > 5_000_000) continue;

        const rect = node.getBoundingClientRect();
        if (rect.height <= 0 || rect.width <= 0) continue;
        const y = rect.top + rect.height / 2;
        points.push({ price, y });
      }
    };

    if (axisCandidates.length) {
      for (const ax of axisCandidates) collectFrom(ax);
    } else {
      // Fallback: scan rightmost strip of the viewport for numeric labels
      const all = document.querySelectorAll("div, span");
      for (const node of all) {
        if (node.children.length > 0) continue;
        const rect = node.getBoundingClientRect();
        if (rect.left < window.innerWidth - 120) continue;
        collectFrom(node.parentElement || node);
      }
    }

    // Dedupe near-identical labels
    points.sort((a, b) => a.price - b.price);
    const unique = [];
    for (const p of points) {
      const prev = unique[unique.length - 1];
      if (!prev || Math.abs(prev.price - p.price) > 0.01) unique.push(p);
    }

    if (unique.length < 2) return null;

    // Prefer two labels that bracket the target; else extrapolate from extremes
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

  function formatUsd(n) {
    return n.toLocaleString("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function render() {
    rafPending = false;
    if (!state || !state.enabled) {
      hideOverlay();
      return;
    }

    const onBtc = isBtcUsdChart();
    const { root, line, label, badge } = ensureDom();
    root.style.display = "block";

    badge.className = "kalshi-tv-badge";
    if (!onBtc) {
      line.style.display = "none";
      label.style.display = "none";
      badge.textContent = "Kalshi target: open a BTCUSD chart";
      badge.dataset.status = "idle";
      return;
    }

    if (state.error && state.target == null) {
      line.style.display = "none";
      label.style.display = "none";
      badge.textContent = `Kalshi: ${state.error}`;
      badge.dataset.status = "warn";
      return;
    }

    if (state.target == null) {
      line.style.display = "none";
      label.style.display = "none";
      badge.textContent = "Kalshi: waiting for target…";
      badge.dataset.status = "warn";
      return;
    }

    const y = priceToY(state.target);
    if (y == null) {
      line.style.display = "none";
      label.style.display = "none";
      badge.textContent = `Kalshi TARGET ${formatUsd(state.target)} (axis loading…)`;
      badge.dataset.status = "loading";
      return;
    }

    lastY = y;
    line.style.display = "block";
    label.style.display = "block";
    line.style.top = `${Math.round(y)}px`;
    label.style.top = `${Math.round(y)}px`;

    const windowBit = state.windowLabel ? ` · ${state.windowLabel}` : "";
    label.textContent = `TARGET ${formatUsd(state.target)}${windowBit}`;
    badge.textContent = `Kalshi 15m TARGET ${formatUsd(state.target)}${windowBit}`;
    badge.dataset.status = "ok";
  }

  function scheduleRender() {
    if (rafPending) return;
    rafPending = true;
    requestAnimationFrame(render);
  }

  async function loadState() {
    try {
      const res = await chrome.runtime.sendMessage({ type: "get-target" });
      if (res) {
        state = res;
        scheduleRender();
      }
    } catch {
      // Extension context may be restarting
    }
  }

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local" || !changes.kalshiTarget) return;
    state = changes.kalshiTarget.newValue;
    scheduleRender();
  });

  // Reposition on scroll/resize/chart zoom (DOM mutations on price axis)
  window.addEventListener("resize", scheduleRender, { passive: true });
  window.addEventListener("scroll", scheduleRender, { passive: true, capture: true });

  const mo = new MutationObserver(() => scheduleRender());
  mo.observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
  });

  // Lightweight poll in case storage events are missed after SW sleep
  setInterval(loadState, 15_000);

  loadState();
  chrome.runtime.sendMessage({ type: "refresh-target" }).catch(() => {});
})();
