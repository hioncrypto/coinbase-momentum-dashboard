# Coinbase Momentum & Volume Dashboard — CLOUD v5.8 (clean full file)
# - Exchange-first connection with handshake headers
# - Hardened worker thread (own asyncio loop + full try/except + breadcrumbs)
# - Safe tiny config + Restart stream + Force connect (hot-fix)
# - Ticker stream only (stable), tolerant subscribe, compact movers panel
# - Clean table formatting (no unterminated strings), robust to missing columns

import asyncio, collections, json, math, queue, threading, time, traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytz
import requests
import streamlit as st

# -------------------- Constants --------------------
ADV_WS_URL = "wss://advanced-trade-ws.coinbase.com"
EXC_WS_URLS = [
    "wss://ws-feed.exchange.coinbase.com",
    "wss://ws-feed.pro.coinbase.com",
    "wss://ws-feed-public.sandbox.exchange.coinbase.com",
]

DEFAULT_PRODUCTS = ["BTC-USD", "ETH-USD", "SOL-USD"]
HISTORY_SECONDS = 20 * 60
REFRESH_MS = 800
FIRST_TICK_TIMEOUT = 8.0
NO_MSG_GRACE = 20.0

# -------------------- Page --------------------
st.set_page_config(page_title="Momentum & Volume — CLOUD v5.8", layout="wide")
st.markdown("""
<style>
html, body, [class*="css"]{font-size:16px}
div[data-testid="stMetricValue"]{font-size:18px!important}
div[data-testid="stDataFrame"]{padding-top:.25rem}
.small-table td,.small-table th{padding:.25rem .5rem!important;font-size:14px}
section[data-testid="stSidebar"]{overscroll-behavior:contain}
</style>
""", unsafe_allow_html=True)

st.markdown("# Momentum & Volume Dashboard — **CLOUD v5.8**")
st.caption("Exchange‑first, hardened worker, safe tiny config, restart stream, force connect, movers & alerts, clean formatting.")

# -------------------- Websockets availability --------------------
try:
    import websockets
    from websockets.exceptions import InvalidStatusCode, InvalidMessage
    WEBSOCKETS_OK = True
except Exception:
    WEBSOCKETS_OK = False

# -------------------- Helpers --------------------
@st.cache_data(ttl=3600)
def discover_products(quote="USD"):
    try:
        r = requests.get("https://api.exchange.coinbase.com/products", timeout=10)
        r.raise_for_status()
        out = []
        for it in r.json():
            pid = it.get("id")
            if not pid: continue
            if it.get("trading_disabled"): continue
            if pid.endswith(f"-{quote}"):
                out.append(pid)
        return sorted(set(out)) or DEFAULT_PRODUCTS
    except Exception:
        return DEFAULT_PRODUCTS

def rsi(series: pd.Series, period: int = 14):
    d = series.diff()
    g = d.clip(lower=0).rolling(period).mean()
    l = (-d.clip(upper=0)).rolling(period).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def pct_change_over_window(records, now_ts, window_sec):
    target = now_ts - window_sec
    ref_price, last_price = None, None
    for ts, price, _ in reversed(records):
        if last_price is None: last_price = price
        if ts <= target:
            ref_price = price
            break
    if ref_price is None or last_price is None or ref_price == 0:
        return np.nan
    return (last_price - ref_price) / ref_price * 100.0

def volume_in_window(records, now_ts, window_sec):
    cutoff = now_ts - window_sec
    vol = 0.0
    for ts, _, size in reversed(records):
        if ts < cutoff: break
        vol += size or 0.0
    return vol

# -------------------- Shared state --------------------
class Store:
    def __init__(self):
        self.deques = {}
        self.rows_q = queue.Queue()
        self.alert_last_ts = {}
        self.alert_log = collections.deque(maxlen=50)
        self.vol_cache = {}
        self.connected = False
        self.last_msg_ts = 0.0
        self.reconnections = 0
        self.err = ""
        self.active_url = ""
        self.endpoint_mode = ""
        self.connect_attempt = 0
        self.last_subscribe = ""
        self.debug = collections.deque(maxlen=200)
        self.safe_cfg = None

state = Store()

def dbg(msg: str):
    try:
        state.debug.append(f"{time.strftime('%H:%M:%S')} {msg}")
    except Exception:
        pass

# -------------------- WS subscribe & run --------------------
async def subscribe_expect_ticker(ws, mode, product_ids, chunk):
    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i+n]

    chunk = max(1, min(int(chunk or 1), 50))
    sent = 0
    for group in chunks(product_ids, chunk):
        if mode == "advanced":
            payload = {"type": "subscribe", "channel": "ticker", "product_ids": group}
        else:
            payload = {"type": "subscribe", "channels": [{"name": "ticker", "product_ids": group}]}
        await ws.send(json.dumps(payload))
        state.last_subscribe = json.dumps(payload)
        sent += len(group)
    dbg(f"subscribed {sent} {mode}:ticker")

    deadline = time.time() + FIRST_TICK_TIMEOUT
    while time.time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
        try:
            m = json.loads(raw)
        except Exception:
            continue
        if (mode == "advanced" and m.get("channel") in ("ticker", "ticker_batch")) or \
           (mode != "advanced" and m.get("type") == "ticker"):
            return raw
    raise asyncio.TimeoutError("No ticker data after subscribe")

async def ws_once(url, mode, products, chunk):
    if not WEBSOCKETS_OK:
        state.err = "websockets not available"
        return False

    import websockets
    state.connect_attempt += 1
    dbg(f"begin_connect {mode} -> {url}")

    async def _run():
        try:
            connect_coro = websockets.connect(
                url,
                ping_interval=20, ping_timeout=20, close_timeout=5, max_size=2**22,
                extra_headers={
                    "User-Agent": "Mozilla/5.0 (compatible; StreamlitCloud)",
                    "Origin": "https://share.streamlit.io",
                    "Accept": "*/*",
                },
            )
            conn = await asyncio.wait_for(connect_coro, timeout=6.0)
            async with conn as ws:
                state.active_url = url
                first = await subscribe_expect_ticker(ws, mode, products, chunk)

                ok_any = False
                async def handle(raw: str):
                    nonlocal ok_any
                    now_ts = time.time()
                    state.last_msg_ts = now_ts
                    try:
                        m = json.loads(raw)
                    except Exception:
                        return
                    if mode == "advanced":
                        if m.get("channel") in ("ticker", "ticker_batch"):
                            for ev in m.get("events") or []:
                                for tk in ev.get("tickers") or []:
                                    pid = tk.get("product_id")
                                    price = float(tk.get("price") or 0)
                                    size = float(tk.get("last_size") or 0)
                                    if pid in state.deques:
                                        state.rows_q.put((pid, now_ts, price, size))
                                        ok_any = True
                    else:
                        if m.get("type") == "ticker":
                            pid = m.get("product_id")
                            price = float(m.get("price") or 0)
                            size = float(m.get("last_size") or 0)
                            if pid in state.deques:
                                state.rows_q.put((pid, now_ts, price, size))
                                ok_any = True

                await handle(first)
                # drain a handful to confirm data
                for _ in range(30):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        await handle(raw)
                    except asyncio.TimeoutError:
                        break

                if not ok_any:
                    raise asyncio.TimeoutError("Parsed no tickers")
                return True

        except InvalidStatusCode as e:
            state.err = f"HTTP {getattr(e, 'status_code', '?')}"
            dbg(state.err); return False
        except InvalidMessage as e:
            state.err = f"Invalid WS handshake: {e}"
            dbg(state.err); return False
        except asyncio.TimeoutError as e:
            state.err = f"Timeout: {e}"
            dbg(state.err); return False
        except Exception as e:
            state.err = f"{type(e).__name__}: {e}"
            dbg(state.err); dbg(traceback.format_exc().splitlines()[-1]); return False

    try:
        return await asyncio.wait_for(_run(), timeout=12.0)
    except asyncio.TimeoutError:
        state.err = "Timeout: attempt exceeded 12s overall"
        dbg(state.err); return False

def worker(products, chunk, mode_select):
    """Hardened worker with its own event loop and breadcrumb logging."""
    try:
        state.endpoint_mode = mode_select
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        dbg("worker: loop created")

        while True:
            try:
                if mode_select == "Advanced only":
                    try_list = [(ADV_WS_URL, "advanced")]
                elif mode_select == "Exchange only":
                    try_list = [(u, "exchange") for u in EXC_WS_URLS]
                else:  # Auto
                    try_list = [(u, "exchange") for u in EXC_WS_URLS] + [(ADV_WS_URL, "advanced")]

                any_ok = False
                for url, mode in try_list:
                    state.connected = False
                    state.err = ""
                    state.active_url = url
                    dbg(f"attempt {mode} {url}")
                    try:
                        ok = loop.run_until_complete(ws_once(url, mode, products, chunk))
                    except Exception as e:
                        ok = False
                        state.err = f"Runner error: {type(e).__name__}: {e}"
                        dbg(state.err); dbg(traceback.format_exc().splitlines()[-1])

                    if ok:
                        state.connected = True
                        any_ok = True
                        dbg("connected; keeping alive briefly")
                        time.sleep(2.0)
                        break
                    else:
                        dbg("failed attempt; next")
                        state.reconnections += 1

                if not any_ok:
                    time.sleep(2.0)
            except Exception as e:
                state.err = f"Worker loop error: {type(e).__name__}: {e}"
                dbg(state.err); dbg(traceback.format_exc().splitlines()[-1])
                time.sleep(2.0)
    except Exception as e:
        state.err = f"Worker init error: {type(e).__name__}: {e}"
        dbg(state.err); dbg(traceback.format_exc().splitlines()[-1])

# -------------------- Sidebar --------------------
with st.sidebar:
    st.subheader("Source & Universe")
    quote = st.selectbox("Quote currency preset", ["USD", "USDC", "USDT", "BTC"], index=0, key="quote_sel")
    discovered = discover_products(quote)
    st.caption(f"Discovered {len(discovered)} products ending with -{quote}")
    use_watchlist_only = st.checkbox("Use watchlist only (ignore discovery)", True, key="use_watchlist_only")
    watchlist = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD", key="watchlist_text")
    max_products = st.slider("Max products to subscribe", 10, 200, min(50, max(10, len(discovered))), step=5, key="max_products_val")

    st.subheader("WebSocket")
    mode_select = st.selectbox("Mode", ["Auto", "Advanced only", "Exchange only"], index=2)  # default Exchange only
    chunk_size = st.slider("Subscribe chunk size", 2, 200, 10, step=1, key="chunk_size_val")
    pause = st.checkbox("Pause streaming (UI keeps last values)", value=False, key="pause_val")
    restart_stream = st.button("🔄 Restart stream")

    def _force_connect():
        def _runner():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                url = EXC_WS_URLS[0]
                dbg("FORCE: one-shot connect to exchange feed")
                loop.run_until_complete(ws_once(url, "exchange", products, st.session_state.get("chunk_size_val", 10)))
            except Exception as e:
                state.err = f"Force error: {type(e).__name__}: {e}"
                dbg(state.err)
        threading.Thread(target=_runner, daemon=True).start()

    if st.button("⚡ Force connect (hot‑fix)"):
        _force_connect()
        st.info("Force connect started (background).")

    # Safe tiny config
    if st.button("🛟 Use safe tiny config"):
        state.safe_cfg = {
            "use_watchlist_only": True,
            "watchlist_text": "BTC-USD, ETH-USD, SOL-USD",
            "max_products_val": 3,
            "chunk_size_val": 3,
        }
        st.success("Applied tiny config. Keep Mode='Exchange only' then click 🔄 Restart stream.")
    if st.button("Clear safe config"):
        state.safe_cfg = None
        st.info("Safe config cleared.")

    st.subheader("Indicators")
    rsi_period = st.number_input("RSI period", 14, step=1)
    ema_fast = st.number_input("EMA fast", 12, step=1)
    ema_slow = st.number_input("EMA slow", 26, step=1)

    st.subheader("Alerts")
    enable_alerts = st.checkbox("Enable alerts", True)
    roc_thr = st.number_input("Alert if |ROC 1m| ≥ (%)", value=0.7, step=0.1)
    volz_thr = st.number_input("Alert if Volume Z ≥", value=3.0, step=0.5)
    rsi_up = st.number_input("RSI crosses above", value=60, step=1)
    rsi_dn = st.number_input("RSI crosses below", value=40, step=1)
    cooldown = st.number_input("Alert cooldown (sec)", value=45, step=5)

    st.subheader("Display")
    tz_name = st.selectbox("Time zone", ["UTC", "US/Pacific", "US/Eastern"], index=0)
    max_rows = st.slider("Max rows shown", 10, 1000, 300, step=10)
    search = st.text_input("Search filter (e.g., BTC or -USD)", "")
    mobile_mode = st.checkbox("📱 Mobile mode (compact)", True)
    show_movers = st.checkbox("Show Top Movers", value=True)
    movers_rows = st.slider("Rows in movers panel", 3, 10, 5)

def cfg_get(key, default=None):
    if state.safe_cfg and key in state.safe_cfg:
        return state.safe_cfg[key]
    return st.session_state.get(key, default)

# -------------------- Build universe --------------------
use_watchlist_only_val = cfg_get("use_watchlist_only", True)
watchlist_text_val = cfg_get("watchlist_text", "")
max_products_val = cfg_get("max_products_val", 50)

if use_watchlist_only_val and watchlist_text_val.strip():
    products = [x.strip() for x in watchlist_text_val.split(",") if x.strip()]
else:
    products = discover_products(st.session_state.get("quote_sel", "USD"))[:max_products_val]

for pid in products:
    if pid not in state.deques:
        state.deques[pid] = collections.deque(maxlen=5000)

# -------------------- Start/Restart worker --------------------
if "ws_thread" not in st.session_state:
    st.session_state["ws_thread"] = None

thr = st.session_state["ws_thread"]
need_restart = (thr is None) or (not getattr(thr, "is_alive", lambda: False)())

if WEBSOCKETS_OK and (not st.session_state.get("pause_val", False)) and (need_restart or restart_stream):
    try:
        state.err = ""
        state.active_url = ""
        state.connect_attempt = 0
        dbg("starting worker thread")
        thr = threading.Thread(
            target=worker,
            args=(products, cfg_get("chunk_size_val", 10), mode_select),
            daemon=True, name="coinbase-ws-worker"
        )
        thr.start()
        st.session_state["ws_thread"] = thr
        st.info("Streaming thread started.")
        dbg(f"thread started: alive={thr.is_alive()}")
    except Exception as e:
        state.err = f"Start error: {e}"
        dbg(state.err)

# -------------------- Status bar --------------------
now = time.time()
has_recent = (now - state.last_msg_ts) <= NO_MSG_GRACE if state.last_msg_ts else False
c1, c2, c3, c4 = st.columns(4)
c1.metric("Connected", "Yes" if (state.connected and has_recent) else "No")
c2.metric("Reconnections", state.reconnections)
c3.metric("Last message", "-" if not has_recent else datetime.fromtimestamp(state.last_msg_ts, tz=timezone.utc).strftime("%H:%M:%S UTC"))
c4.metric("Subscribed pairs", len(state.deques))
if state.err:
    st.error(f"Last error: {state.err}")

with st.expander("Diagnostics (temporary)"):
    thr = st.session_state.get("ws_thread")
    st.json({
        "WEBSOCKETS_OK": WEBSOCKETS_OK,
        "thread_alive": (thr.is_alive() if thr else False),
        "thread": repr(thr),
        "endpoint_mode": mode_select,
        "connect_attempt": state.connect_attempt,
        "active_ws_url": state.active_url,
        "last_subscribe": state.last_subscribe,
        "queue_size": state.rows_q.qsize(),
        "state.connected": state.connected,
        "state.last_msg_ts": state.last_msg_ts,
        "state.err": state.err,
        "products_first3": products[:3],
        "products_count": len(products),
        "debug_tail": list(state.debug)[-20:],
        "safe_cfg_active": bool(state.safe_cfg),
    })

# -------------------- Compute & render loop --------------------
def compute_row(pid, dq, tz_obj, rsi_p, e_fast, e_slow):
    if not dq: return None
    now = time.time()
    prices = [p for _, p, _ in dq]
    s = pd.Series(prices)
    ema_f = s.ewm(span=e_fast, adjust=False).mean().iloc[-1]
    ema_s = s.ewm(span=e_slow, adjust=False).mean().iloc[-1]
    rsi_v = rsi(s, rsi_p).iloc[-1]
    roc_1 = pct_change_over_window(dq, now, 60)
    roc_5 = pct_change_over_window(dq, now, 300)
    roc_15 = pct_change_over_window(dq, now, 900)
    vol_1 = volume_in_window(dq, now, 60)

    minute_key = int(now // 60)
    vc = state.vol_cache.setdefault(pid, {"last": minute_key, "vals": collections.deque(maxlen=20)})
    if vc["last"] != minute_key:
        prev_min = volume_in_window(dq, (minute_key * 60), 60)
        vc["vals"].append(prev_min)
        vc["last"] = minute_key
    vols = np.array(vc["vals"]) if len(vc["vals"]) else np.array([vol_1])
    vmean = float(vols.mean())
    vstd = float(vols.std(ddof=1) if len(vc["vals"]) > 1 else 0.0)
    vol_z = 0.0 if vstd == 0 else (vol_1 - vmean) / vstd

    last_ts = datetime.fromtimestamp(dq[-1][0], tz=timezone.utc).astimezone(tz_obj)
    return {
        "Pair": pid, "Last Update": last_ts.strftime("%Y-%m-%d %H
