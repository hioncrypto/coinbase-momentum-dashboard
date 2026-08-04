/* BeatLine service worker — background 15m target + clear-edge alerts */
const SW_VERSION = "2.8-edge";
const TARGET_URL = "/api/target?tf=15m";
const STATE_KEY = "kalshiFifteenState";

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(caches.open(SW_VERSION));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k !== SW_VERSION).map((k) => caches.delete(k)));
      await self.clients.claim();
      startPollLoop();
    })()
  );
});

// Never break page loads — always go to network for navigations.
self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  // Pass-through; do not serve a broken offline shell.
  event.respondWith(
    fetch(req).catch(() => {
      if (req.mode === "navigate") {
        return new Response(
          "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><body style='font-family:sans-serif;background:#0b1210;color:#e7f6ee;padding:24px'><h1>Link expired</h1><p>This home-screen shortcut points at an old Cloudflare tunnel.</p><p>Open the latest app URL in Chrome, then Add to Home screen again.</p></body>",
          { headers: { "Content-Type": "text/html; charset=utf-8" } }
        );
      }
      return Response.error();
    })
  );
});

async function readState() {
  const cache = await caches.open(SW_VERSION);
  const res = await cache.match(STATE_KEY);
  if (!res) return { ticker: null, target: null, chimeOn: true, edgeKey: null };
  try {
    return await res.json();
  } catch {
    return { ticker: null, target: null, chimeOn: true, edgeKey: null };
  }
}

async function writeState(state) {
  const cache = await caches.open(SW_VERSION);
  await cache.put(
    STATE_KEY,
    new Response(JSON.stringify(state), {
      headers: { "Content-Type": "application/json" },
    })
  );
}

async function showTargetNotification(payload) {
  const title = "BeatLine · new 15m target";
  const body =
    payload && payload.beat != null
      ? `Price to beat $${Number(payload.beat).toLocaleString("en-US", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}${payload.closeEt ? ` · settles ${payload.closeEt}` : ""}`
      : "A new 15-minute window just opened";
  const opts = {
    body,
    icon: "/icons/icon-192.png?v=2.6",
    badge: "/icons/icon-192.png?v=2.6",
    vibrate: [80, 40, 80, 40, 160],
    tag: "kalshi-15m-target",
    renotify: false,
    requireInteraction: false,
    silent: false,
    data: { url: "/", ticker: payload && payload.ticker },
  };
  await self.registration.showNotification(title, opts);
}

async function showEdgeNotification(payload) {
  const side = payload && payload.side === "below" ? "Below" : "Above";
  const ask =
    payload && payload.askCents != null ? Math.round(Number(payload.askCents)) : null;
  const conf =
    payload && payload.pWin != null ? Math.round(Number(payload.pWin) * 100) : null;
  const title = `BeatLine · clear edge · Buy ${side}`;
  const bits = [];
  if (ask != null) bits.push(`ask ${ask}¢`);
  if (conf != null) bits.push(`${conf}% model`);
  if (payload && payload.beat != null) {
    bits.push(
      `beat $${Number(payload.beat).toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`
    );
  }
  const body = bits.length
    ? bits.join(" · ")
    : "Best Side found a clear edge — open BeatLine";
  await self.registration.showNotification(title, {
    body,
    icon: "/icons/icon-192.png?v=2.6",
    badge: "/icons/icon-192.png?v=2.6",
    vibrate: [60, 40, 60, 40, 120],
    tag: "kalshi-clear-edge",
    renotify: false,
    requireInteraction: false,
    silent: false,
    data: { url: "/", ticker: payload && payload.ticker, kind: "clear_edge" },
  });
}

async function checkTarget(forceNotify) {
  const state = await readState();
  if (!state.chimeOn && !forceNotify) return;
  let data;
  try {
    const res = await fetch(`${TARGET_URL}&_=${Date.now()}`, { cache: "no-store" });
    data = await res.json();
  } catch {
    return;
  }
  const beat = data.price_to_beat ?? data.target;
  const ticker = data.ticker || null;
  const changed =
    state.ticker &&
    ticker &&
    state.ticker !== ticker &&
    (data.source === "kalshi" || String(ticker).includes("KXBTC15M"));

  if (changed || forceNotify) {
    await showTargetNotification({
      beat,
      ticker,
      closeEt: data.close_et,
    });
  }

  state.ticker = ticker || state.ticker;
  if (beat != null) state.target = beat;
  await writeState(state);
}

let pollTimer = null;
function startPollLoop() {
  if (pollTimer) return;
  // Keep checking even if the page is backgrounded (while SW is allowed to run).
  pollTimer = setInterval(() => {
    checkTarget(false);
  }, 15_000);
  checkTarget(false);
}

self.addEventListener("message", (event) => {
  const msg = event.data || {};
  if (msg.type === "set-chime") {
    event.waitUntil(
      (async () => {
        const state = await readState();
        state.chimeOn = !!msg.enabled;
        await writeState(state);
        startPollLoop();
      })()
    );
  }
  if (msg.type === "arm-state") {
    event.waitUntil(
      (async () => {
        const state = await readState();
        if (msg.ticker) state.ticker = msg.ticker;
        if (msg.target != null) state.target = msg.target;
        if (typeof msg.chimeOn === "boolean") state.chimeOn = msg.chimeOn;
        await writeState(state);
        startPollLoop();
      })()
    );
  }
  if (msg.type === "check-now") {
    event.waitUntil(checkTarget(!!msg.forceNotify));
  }
  if (msg.type === "test-notify") {
    event.waitUntil(
      showTargetNotification({
        beat: msg.beat,
        ticker: msg.ticker || "TEST",
        closeEt: msg.closeEt,
      })
    );
  }
  if (msg.type === "edge-notify") {
    event.waitUntil(
      (async () => {
        const state = await readState();
        if (!state.chimeOn) return;
        const key = `${msg.side}:${Math.round(Number(msg.askCents) || 0)}`;
        const now = Date.now();
        const lastAt = Number(state.edgeAt) || 0;
        if (state.edgeKey === key) return;
        if (now - lastAt < 120000) return;
        state.edgeKey = key;
        state.edgeAt = now;
        await writeState(state);
        await showEdgeNotification(msg);
      })()
    );
  }
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data ? event.data.text() : "" };
  }
  const kind = payload.type || payload.kind || "new_target";
  if (kind === "clear_edge") {
    event.waitUntil(
      showEdgeNotification({
        side: payload.side,
        askCents: payload.ask_cents ?? payload.askCents,
        pWin: payload.p_win ?? payload.pWin,
        beat: payload.beat ?? payload.price_to_beat ?? payload.target,
        ticker: payload.ticker,
      })
    );
    return;
  }
  event.waitUntil(
    showTargetNotification({
      beat: payload.beat ?? payload.price_to_beat ?? payload.target,
      ticker: payload.ticker,
      closeEt: payload.close_et || payload.closeEt,
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    (async () => {
      const all = await clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of all) {
        if ("focus" in client) {
          await client.focus();
          if ("navigate" in client) {
            try {
              await client.navigate(url);
            } catch {
              // ignore
            }
          }
          return;
        }
      }
      await clients.openWindow(url);
    })()
  );
});
