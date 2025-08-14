# Coinbase Momentum & Volume Dashboard — CLOUD v5.7
# - Worker uses a dedicated asyncio loop (no asyncio.run in thread)
# - Auto tries Exchange endpoints first, then Advanced
# - Friendly WS handshake headers + 6s connect timeout + 12s per-attempt cap
# - Tolerant subscribe / first-ticker logic
# - Safe config overrides (no writes into st.session_state)
# - Restart stream, Top Movers, RSI/EMA, Alerts, Diagnostics

import asyncio, collections, json, math, queue, threading, time, traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytz
import requests
import streamlit as st

st.set_page_config(page_title="Momentum & Volume — CLOUD v5.7", layout="wide")

# -------------------- endpoints --------------------
ADV_WS_URL = "wss://advanced-trade-ws.coinbase.com"
EXC_WS_URLS = [
    "wss://ws-feed.exchange.coinbase.com",
    "wss://ws-feed.pro.coinbase.com",
    "wss://ws-feed-public.sandbox.exchange.coinbase.com",
]

DEFAULT_PRODUCTS = ["BTC-USD", "ETH-USD", "SOL-USD"]
HISTORY_SECONDS   = 20 * 60
REFRESH_MS        = 750
FIRST_TICK_TIMEOUT = 8.0
NO_MSG_GRACE       = 20.0

# -------------------- css --------------------
st.markdown("""
<style>
html, body, [class*="css"] { font-size: 16px; }
div[data-testid="stMetricValue"] { font-size: 18px !important; }
div[data-testid="stDataFrame"] { padding-top: 0.25rem; }
.small-table td, .small-table th { padding: 0.25rem 0.5rem !important; font-size: 14px; }
section[data-testid="stSidebar"] { overscroll-behavior: contain; }
</style>
""", unsafe_allow_html=True)

st.markdown("# Momentum & Volume Dashboard — **CLOUD v5.7**")
st.caption("Exchange‑first, safer handshake, tolerant subscribe, restart, safe config, movers, alerts, diagnostics.")

# -------------------- websockets import --------------------
try:
    import websockets
    from websockets.exceptions import InvalidStatusCode, InvalidMessage
    WEBSOCKETS_OK = True
except Exception:
    WEBSOCKETS_OK = False

# -------------------- discovery --------------------
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

# -------------------- indicators --------------------
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
            ref_price = price; break
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

# -------------------- global store --------------------
class Store:
    def __init__(self):
        self.deques = {}            # pid -> deque[(ts, price, size)]
        self.rows_q = queue.Queue()
        self.alert_last_ts = {}
        self.alert_log = collections.deque(maxlen=50)
        self.vol_cache = {}         # pid -> {"last": minute_key, "vals": deque(maxlen=20)}
        # connection status
        self.connected = False
        self.last_msg_ts = 0.0
        self.reconnections = 0
        self.err = ""
        self.active_url = ""
        self.endpoint_mode = ""
        self.connect_attempt = 0
        self.last_subscribe = ""
        self.debug = collections.deque(maxlen=200)
        # sidebar safe overrides (local only)
        self.safe_cfg = None

state = Store()
def dbg(msg: str):
    try:
        state.debug.append(f"{time.strftime('%H:%M:%S')} {msg}")
    except Exception:
        pass

# -------------------- WS subscribe & connect --------------------
async def subscribe_and_expect_first_tick(ws, mode, channel, product_ids, chunk):
    """
    Send subscribe payload(s), then wait for first *ticker*.
    Tolerates non-ticker first frame; keeps reading briefly to find one.
    """
    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i+n]

    sent = 0
    chunk = max(1, min(int(chunk or 1), 50))

    if mode == "advanced":
        for group in chunks(product_ids, chunk):
            payload = {"type": "subscribe", "channel": channel, "product_ids": group}
            await ws.send(json.dumps(payload))
            state.last_subscribe = json.dumps(payload)
            sent += len(group)
    else:
        for group in chunks(product_ids, chunk):
            payload = {"type": "subscribe", "channels": [{"name": channel, "product_ids": group}]}
            await ws.send(json.dumps(payload))
            state.last_subscribe = json.dumps(payload)
            sent += len(group)
    dbg(f"subscribed {sent} {mode}:{channel}")

    # Wait up to FIRST_TICK_TIMEOUT for any frame,
    # then up to +2s more for a real ticker if first wasn't one.
    deadline = time.time() + FIRST_TICK_TIMEOUT
    first = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
    try:
        msg = json.loads(first)
    except Exception:
        msg = {}

    # already a ticker?
    if (mode != "advanced" and msg.get("type") == "ticker") or \
       (mode == "advanced" and msg.get("channel") in ("ticker", "ticker_batch")):
        return first

    extra_deadline = time.time() + 2.0
    while time.time() < extra_deadline:
        try:
            nxt = await asyncio.wait_for(ws.recv(), timeout=max(0.1, extra_deadline - time.time()))
            try:
                m2 = json.loads(nxt)
            except Exception:
                continue
            if (mode != "advanced" and m2.get("type") == "ticker") or \
               (mode == "advanced" and m2.get("channel") in ("ticker", "ticker_batch")):
                return nxt
        except asyncio.TimeoutError:
            break

    raise asyncio.TimeoutError("No ticker message after subscribe")

async def ws_once(url, mode, channel, products, chunk):
    """
    Attempt one connection; return True once any tick is parsed.
    Hard per-attempt cap so we always fall through to the next URL.
    """
    if not WEBSOCKETS_OK:
        state.err = "websockets module unavailable"
        return False

    import websockets
    from websockets.exceptions import InvalidStatusCode, InvalidMessage

    state.connect_attempt += 1
    dbg(f"begin_connect {mode} -> {url}")

    async def _run_one():
        try:
            dbg("opening websocket...")

            # --- open with headers + 6s handshake timeout ---
            connect_coro = websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=2**22,
                extra_headers={
                    "User-Agent": "Mozilla/5.0 (compatible; StreamlitCloud; +https://streamlit.io)",
                    "Origin": "https://share.streamlit.io",
                    "Accept": "*/*",
                },
            )
            conn = await asyncio.wait_for(connect_coro, timeout=6.0)

            async with conn as ws:
                dbg("socket open; subscribing...")
                state.active_url = url
                first = await subscribe_and_expect_first_tick(ws, mode, channel, products, chunk)
                ok_parsed = False

                async def handle_one(raw: str):
                    nonlocal ok_parsed
                    now_ts = time.time()
                    state.last_msg_ts = now_ts
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        return

                    if mode == "advanced":
                        chan = msg.get("channel")
                        if chan in ("ticker", "ticker_batch"):
                            for ev in msg.get("events") or []:
                                for tk in ev.get("tickers") or []:
                                    pid = tk.get("product_id")
                                    try: price = float(tk.get("price") or 0)
                                    except Exception: price = 0.0
                                    try: size = float(tk.get("last_size") or 0)
                                    except Exception: size = 0.0
                                    if pid in state.deques:
                                        state.rows_q.put((pid, now_ts, price, size))
                                        ok_parsed = True
                    else:
                        if msg.get("type") == "ticker":
                            pid = msg.get("product_id")
                            try: price = float(msg.get("price") or 0)
                            except Exception: price = 0.0
                            try: size = float(msg.get("last_size") or 0)
                            except Exception: size = 0.0
                            if pid in state.deques:
                                state.rows_q.put((pid, now_ts, price, size))
                                ok_parsed = True

                # process first, then a small burst
                await handle_one(first)
                for _ in range(30):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        await handle_one(raw)
                    except asyncio.TimeoutError:
                        break

                if not ok_parsed:
                    raise asyncio.TimeoutError("Got messages but no tickers parsed")
                return True

        except InvalidStatusCode as e:
            state.err = f"HTTP {getattr(e, 'status_code', '?')} during upgrade"
            dbg(state.err); return False
        except InvalidMessage as e:
            state.err = f"Invalid WS handshake message: {e}"
            dbg(state.err); return False
        except asyncio.TimeoutError as e:
            state.err = f"Timeout: {e}"
            dbg(state.err); return False
        except Exception as e:
            state.err = f"{type(e).__name__}: {e}"
            dbg(f"connect error: {state.err}")
            dbg(traceback.format_exc().splitlines()[-1])
            return False

    # Hard cap per attempt (so Auto/Exchange can fall through)
    try:
        return await asyncio.wait_for(_run_one(), timeout=12.0)
    except asyncio.TimeoutError:
        state.err = "Timeout: attempt exceeded 12s overall"
        dbg(state.err); return False

def worker(products, channel, chunk, mode_select):
    """
    Auto tries Exchange URLs first (more reliable), then Advanced.
    Uses a dedicated event loop in this thread (no asyncio.run()).
    Always moves to next URL on failure and logs breadcrumbs.
    """
    state.endpoint_mode = mode_select

    # Create a private asyncio loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    while True:
        if mode_select == "Advanced only":
            try_list = [(ADV_WS_URL, "advanced")]
        elif mode_select == "Exchange only":
            try_list = [(u, "exchange") for u in EXC_WS_URLS]
        else:  # Auto prefers Exchange, then Advanced
            try_list = [(u, "exchange") for u in EXC_WS_URLS] + [(ADV_WS_URL, "advanced")]

        any_ok = False

        for url, mode in try_list:
            state.connected = False
            state.err = ""
            state.active_url = url

            dbg(f"attempting connect to {url} as {mode}")

            try:
                ok = loop.run_until_complete(ws_once(url, mode, channel, products, chunk))
            except Exception as e:
                ok = False
                state.err = f"Runner error: {type(e).__name__}: {e}"
                dbg(state.err)
                dbg(traceback.format_exc().splitlines()[-1])

            if ok:
                state.connected = True
                any_ok = True
                dbg("first ticks parsed — stream is connected")
                time.sleep(2.0)  # small settle
                break
            else:
                dbg("attempt failed; trying next endpoint")
                state.reconnections += 1

        if not any_ok:
            time.sleep(2.0)  # short backoff then retry

# -------------------- sidebar --------------------
with st.sidebar:
    st.subheader("Source & Universe")
    quote = st.selectbox("Quote currency preset", ["USD", "USDC", "USDT", "BTC"], index=0, key="quote_sel")
    discovered = discover_products(quote)
    st.caption(f"Discovered {len(discovered)} products ending with -{quote}")
    use_watchlist = st.checkbox("Use watchlist only (ignore discovery)", True, key="use_watchlist_only")
    watchlist = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD", key="watchlist_text")
    max_products = st.slider("Max products to subscribe", 10, 200, min(50, max(10, len(discovered))), step=5, key="max_products_val")

    st.subheader("WebSocket")
    mode_select = st.selectbox("Mode", ["Auto", "Advanced only", "Exchange only"], index=0)
    channel = st.selectbox("Channel", ["ticker", "ticker_batch"], index=0, key="channel_val")
    chunk_size = st.slider("Subscribe chunk size", 2, 200, 10, step=1, key="chunk_size_val")
    pause = st.checkbox("Pause streaming (UI keeps last values)", value=False, key="pause_val")
    restart_stream = st.button("🔄 Restart stream")

    # SAFE tiny config: local overrides (no writes to st.session_state)
    if st.button("🛟 Use safe tiny config"):
        state.safe_cfg = {
            "use_watchlist_only": True,
            "watchlist_text": "BTC-USD, ETH-USD, SOL-USD",
            "max_products_val": 3,
            "channel_val": "ticker",
            "chunk_size_val": 3,
        }
        st.success("Safe tiny config applied. Set Mode='Exchange only', then click 🔄 Restart stream.")
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

    st.subheader("Top Movers")
    show_movers = st.checkbox("Show Top Movers", value=True)
    movers_rows = st.slider("Rows in movers panel", 3, 10, 5)

# helper to read either override or session value
def cfg_get(key, default=None):
    if state.safe_cfg and key in state.safe_cfg:
        return state.safe_cfg[key]
    return st.session_state.get(key, default)

# -------------------- WS tester --------------------
st.markdown("### 🔌 Test Coinbase WebSocket")
if not WEBSOCKETS_OK:
    st.warning("`websockets` installs from requirements.txt. If the test fails now, try again after rebuild.")
else:
    async def quick_test_once(url, mode):
        try:
            connect_coro = websockets.connect(
                url,
                ping_interval=10,
                ping_timeout=10,
                close_timeout=5,
                extra_headers={
                    "User-Agent": "Mozilla/5.0 (compatible; StreamlitCloud; +https://streamlit.io)",
                    "Origin": "https://share.streamlit.io",
                    "Accept": "*/*",
                },
            )
            ws = await asyncio.wait_for(connect_coro, timeout=6.0)
            async with ws:
                if mode == "advanced":
                    await ws.send(json.dumps({"type": "subscribe", "channel": "ticker", "product_ids": ["BTC-USD"]}))
                else:
                    await ws.send(json.dumps({"type": "subscribe", "channels": [{"name": "ticker", "product_ids": ["BTC-USD"]}]}))
                await asyncio.wait_for(ws.recv(), timeout=10)
                return True, f"{mode} responded"
        except asyncio.TimeoutError:
            return False, "Connected but no data within timeout"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def test_with_retries(url, mode, n=2):
        last = (False, "not tried")
        for i in range(1, n+1):
            try:
                ok, info = asyncio.run(quick_test_once(url, mode))
            except Exception as e:
                ok, info = False, f"Runner: {e}"
            st.caption(f"{mode} test {i}/{n}: {'✅' if ok else '❌'} — {info}")
            last = (ok, info)
            if ok: break
            time.sleep(1.2)
        return last

    if st.button("Run WS test (both)"):
        test_with_retries(ADV_WS_URL, "advanced")
        for u in EXC_WS_URLS:
            test_with_retries(u, "exchange", n=1)

# -------------------- build product list --------------------
use_watchlist_only_val = cfg_get("use_watchlist_only", True)
watchlist_text_val     = cfg_get("watchlist_text", "")
max_products_val       = cfg_get("max_products_val", 50)

if use_watchlist_only_val and watchlist_text_val.strip():
    products = [x.strip() for x in watchlist_text_val.split(",") if x.strip()]
else:
    products = discover_products(st.session_state.get("quote_sel", "USD"))[:max_products_val]

# init deques
for pid in products:
    if pid not in state.deques:
        state.deques[pid] = collections.deque(maxlen=5000)

# -------------------- thread management --------------------
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
        channel_val = cfg_get("channel_val", "ticker")
        chunk_val   = cfg_get("chunk_size_val", 10)
        thr = threading.Thread(
            target=worker,
            args=(products, channel_val, chunk_val, mode_select),
            daemon=True, name="coinbase-ws-worker"
        )
        thr.start()
        st.session_state["ws_thread"] = thr
        st.info("Streaming thread started.")
        dbg(f"thread started: alive={thr.is_alive()}")
    except Exception as e:
        state.err = f"Start error: {e}"
        dbg(state.err)

# -------------------- status bar --------------------
now = time.time()
has_recent = (now - state.last_msg_ts) <= NO_MSG_GRACE if state.last_msg_ts else False
c1, c2, c3, c4 = st.columns(4)
c1.metric("Connected", "Yes" if (state.connected and has_recent) else "No")
c2.metric("Reconnections", state.reconnections)
c3.metric("Last message", "-" if not has_recent else datetime.fromtimestamp(state.last_msg_ts, tz=timezone.utc).strftime("%H:%M:%S UTC"))
c4.metric("Subscribed pairs", len(state.deques))
if state.err:
    st.error(f"Last error: {state.err}")

# -------------------- diagnostics --------------------
with st.expander("Diagnostics (temporary)"):
    thr = st.session_state.get("ws_thread")
    diag = {
        "WEBSOCKETS_OK": WEBSOCKETS_OK,
        "thread_alive": (thr.is_alive() if thr else False),
        "thread": repr(thr),
        "endpoint_mode": mode_select,
        "connect_attempt": state.connect_attempt,
        "channel": cfg_get("channel_val", "ticker"),
        "chunk_size": cfg_get("chunk_size_val", 10),
        "active_ws_url": state.active_url,
        "last_subscribe": state.last_subscribe,
        "queue_size": state.rows_q.qsize(),
        "state.connected": state.connected,
        "state.last_msg_ts": state.last_msg_ts,
        "state.err": state.err,
        "products_first3": products[:3],
        "products_count": len(products),
        "debug_tail": list(state.debug)[-15:],
        "safe_cfg_active": bool(state.safe_cfg),
    }
    st.json(diag)

# -------------------- compute / render --------------------
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

    # rolling vol Z cached in state (not session_state)
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
        "Pair": pid, "Last Update": last_ts.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "Price": prices[-1], "ROC 1m %": roc_1, "ROC 5m %": roc_5, "ROC 15m %": roc_15,
        "RSI": rsi_v, "EMA fast": ema_f, "EMA slow": ema_s, "Vol 1m": vol_1, "Vol Z": vol_z
    }

alerts_panel = st.container()
placeholder_movers = st.container()
placeholder_table = st.empty()
last_render = 0.0

while True:
    # drain queue
    try:
        while True:
            pid, ts, price, size = state.rows_q.get_nowait()
            if st.session_state.get("pause_val", False): continue
            if pid not in state.deques: continue
            dq = state.deques[pid]
            dq.append((ts, price, size))
            cutoff = ts - HISTORY_SECONDS
            while dq and dq[0][0] < cutoff:
                dq.popleft()
    except queue.Empty:
        pass

    now = time.time()
    if now - last_render >= REFRESH_MS / 1000.0:
        tz_obj = pytz.timezone(tz_name)
        rows = []
        for pid, dq in state.deques.items():
            r = compute_row(pid, dq, tz_obj, rsi_period, ema_fast, ema_slow)
            if r: rows.append(r)
        df = pd.DataFrame(rows)

        if search.strip():
            df = df[df["Pair"].str.contains(search.strip(), case=False, na=False)]

        # ---- Alerts (panel only)
        if enable_alerts and not df.empty:
            for _, row in df.iterrows():
                reasons = []
                v = row.get("ROC 1m %")
                if isinstance(v, float) and not math.isnan(v) and abs(v) >= roc_thr: reasons.append(f"ROC1m {v:.2f}%")
                vz = row.get("Vol Z")
                if isinstance(vz, float) and vz >= volz_thr: reasons.append(f"VolZ {vz:.1f}")
                rsi_v = row.get("RSI")
                if isinstance(rsi_v, float):
                    if rsi_v >= rsi_up: reasons.append(f"RSI≥{rsi_up}")
                    if rsi_v <= rsi_dn: reasons.append(f"RSI≤{rsi_dn}")
                if reasons:
                    lt = state.alert_last_ts.get(row["Pair"], 0)
                    if now - lt > cooldown:
                        state.alert_last_ts[row["Pair"]] = now
                        state.alert_log.append(
                            (datetime.utcnow().strftime("%H:%M:%S UTC"), row["Pair"], ", ".join(reasons))
                        )

        with alerts_panel:
            if state.alert_log:
                st.subheader("🔔 Recent alerts")
                adf = pd.DataFrame(list(state.alert_log), columns=["Time", "Pair", "Reason"])
                st.dataframe(adf.tail(12), use_container_width=True, height=260)

        # ---- Top Movers
        if show_movers and not df.empty:
            with placeholder_movers:
                st.subheader("🚀 Top Movers")
                cols = st.columns(4) if not mobile_mode else st.columns(2)
                def tiny(tbl, keep, title, col):
                    t = tbl[keep].head(movers_rows).reset_index(drop=True)
                    col.markdown(f"**{title}**")
                    col.dataframe(t.style.hide(axis='index'), use_container_width=True, height=200)
                by_roc_up = df.sort_values("ROC 1m %", ascending=False)
                by_roc_dn = df.sort_values("ROC 1m %", ascending=True)
                by_volz   = df.sort_values("Vol Z", ascending=False)
                by_rsi_hi = df.sort_values("RSI", ascending=False)
                if not mobile_mode:
                    tiny(by_roc_up, ["Pair","ROC 1m %","Price"], "1‑min Gainers", cols[0])
                    tiny(by_roc_dn, ["Pair","ROC 1m %","Price"], "1‑min Losers",  cols[1])
                    tiny(by_volz,   ["Pair","Vol Z","Vol 1m"],   "Vol‑Z Spikes",  cols[2])
                    tiny(by_rsi_hi, ["Pair","RSI","Price"],      "RSI Highs",     cols[3])
                else:
                    tiny(by_roc_up, ["Pair","ROC 1m %","Price"], "1‑min Gainers", cols[0])
                    tiny(by_roc_dn, ["Pair","ROC 1m %","Price"], "1‑min Losers",  cols[1])
                    rcols = st.columns(2)
                    tiny(by_volz,   ["Pair","Vol Z","Vol 1m"],   "Vol‑Z Spikes",  rcols[0])
                    tiny(by_rsi_hi, ["Pair","RSI","Price"],      "RSI Highs",     rcols[1])

        # ---- Main table
        if not df.empty:
            show_cols = ["Pair","Price","ROC 1m %","Vol Z","RSI","Last Update"] if mobile_mode else \
                        ["Pair","Last Update","Price","ROC 1m %","ROC 5m %","ROC 15m %","RSI","EMA fast","EMA slow","Vol 1m","Vol Z"]
            df_show = df[show_cols].sort_values("Pair").head(max_rows)

            def sty_roc(v):
                if pd.isna(v): return ""
                return "color:#0f993e;" if v>0 else ("color:#d43f3a;" if v<0 else "")
            def sty_rsi(v):
                if pd.isna(v): return ""
                if v>=70: return "background-color:#ead7ff;"
                if v<=30: return "background-color:#ffe0e0;"
                return ""

            styled = (df_show.style
                        .format({"Price":"{:.6f}","ROC 1m %":"{:.2f}",
                                **({"ROC 5m %":"{:.2f}","ROC 15m %":"{:.2f}"} if not mobile_mode else {}),
                                "RSI":"{:.1f}",
                                **({"EMA fast":"{:.6f}","EMA slow":"{:.6f}","Vol 1m":"{:.2f}"} if not mobile_mode else {}),
                                "Vol Z":"{:.2f}"})
                        .applymap(sty_roc, subset=[c for c in ["ROC 1m %","ROC 5m %","ROC 15m %"] if c in df_show.columns])
                        .applymap(sty_rsi, subset=["RSI"]))
            placeholder_table.dataframe(styled, use_container_width=True)
        else:
            placeholder_table.info(
                "Waiting for data or no rows match the filter… "
                "Try Mode='Exchange only', Channel='ticker', and a tiny watchlist."
            )

        last_render = now
    time.sleep(0.05)
