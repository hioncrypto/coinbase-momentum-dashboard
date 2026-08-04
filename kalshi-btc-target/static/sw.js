/* Kalshi BTC Target service worker — background 15m target alerts */
const SW_VERSION = "1.7-chime";
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

async function readState() {
  const cache = await caches.open(SW_VERSION);
  const res = await cache.match(STATE_KEY);
  if (!res) return { ticker: null, target: null, chimeOn: true };
  try {
    return await res.json();
  } catch {
    return { ticker: null, target: null, chimeOn: true };
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
  const title = "New Kalshi 15m target";
  const body =
    payload && payload.beat != null
      ? `Price to beat $${Number(payload.beat).toLocaleString("en-US", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })}${payload.closeEt ? ` · settles ${payload.closeEt}` : ""}`
      : "A new 15-minute window just opened";
  const opts = {
    body,
    icon: "/icons/icon.svg",
    badge: "/icons/icon.svg",
    vibrate: [80, 40, 80, 40, 160],
    tag: "kalshi-15m-target",
    renotify: true,
    requireInteraction: true,
    silent: false,
    data: { url: "/", ticker: payload && payload.ticker },
  };
  await self.registration.showNotification(title, opts);
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
});

self.addEventListener("push", (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data ? event.data.text() : "" };
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
      const all = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of all) {
        if ("focus" in client) {
          await client.focus();
          return;
        }
      }
      if (self.clients.openWindow) await self.clients.openWindow(url);
    })()
  );
});

self.addEventListener("periodicsync", (event) => {
  if (event.tag === "kalshi-15m-check") {
    event.waitUntil(checkTarget(false));
  }
});

startPollLoop();
