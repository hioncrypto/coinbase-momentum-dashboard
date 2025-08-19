# Momentum & Volume Dashboard — CLOUD v6.1 (Exchange-only continuous)
# - Exchange feed (ws-feed.exchange.coinbase.com), channel "ticker"
# - Worker runs a continuous read-loop (not a short probe)
# - Reconnects if we stop hearing data or any exception occurs
# - Safe tiny config, Restart stream, Force connect hot‑fix
# - Clean table formatting (no unterminated strings), movers & simple alerts

import asyncio, collections, json, queue, threading, time, traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytz
import requests
import streamlit as st

# -------------------- Page --------------------
st.set_page_config(page_title="Momentum & Volume — CLOUD", layout="wide")
st.title("Momentum & Volume Dashboard — CLOUD v6.1")

st.markdown(
    "<style>html,body,[class*='css']{font-size:16px} div[data-testid='stMetricValue']{font-size:18px!important}</style>",
    unsafe_allow_html=True,
)

# -------------------- Constants --------------------
EXC_WS_URL = "wss://ws-feed.exchange.coinbase.com"
DEFAULT_PRODUCTS = ["BTC-USD", "ETH-USD", "SOL-USD"]

HISTORY_SECONDS = 20 * 60
REFRESH_MS = 800
FIRST_TICK_TIMEOUT = 8.0
NO_MSG_GRACE = 20.0  # seconds without a message -> consider stale

# -------------------- Optional websocket import --------------------
try:
    import websockets
    from websockets.exceptions import InvalidStatusCode, InvalidMessage
    WEBSOCKETS_OK = True
except Exception:
    WEBSOCKETS_OK = False

# -------------------- Helpers --------------------
@st.cache_data(ttl=3600)
def discover_products(quote="USD") -> list[str]:
    try:
        r = requests.get("https://api.exchange.coinbase.com/products", timeout=10)
        r.raise_for_status()
        out = []
        for it in r.json():
            pid = it.get("id")
            if not pid:
                continue
            if it.get("trading_disabled"):
                continue
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
        if last_price is None:
            last_price = price
        if ts <= target:
            ref_price = price
            break
    if ref_price is None or last_price is None or ref_price == 0:
        return np.nan
    return (last_price - ref_price) / ref_price * 100.0

def volume_in_window(records, now_ts, window_sec):
    cutoff = now_ts - window_sec
    v = 0.0
    for ts, _, size in reversed(records):
        if ts < cutoff: break
        v += size or 0.0
    return v

# -------------------- State --------------------
class Store:
    def __init__(self):
        self.deques: dict[str, collections.deque] = {}
        self.rows_q: queue.Queue = queue.Queue()
        self.alert_last_ts: dict[str, float] = {}
        self.alert_log: collections.deque = collections.deque(maxlen=50)
        self.vol_cache: dict[str, dict] = {}

        self.connected: bool = False
        self.last_msg_ts: float = 0.0
        self.reconnections: int = 0
        self.err: str = ""
        self.active_url: str = ""
        self.connect_attempt: int = 0
        self.last_subscribe: str = ""
        self.debug: collections.deque = collections.deque(maxlen=200)
        self.safe_cfg: dict | None = None

state = Store()

def dbg(msg: str):
    try:
        state.debug.append(f"{time.strftime('%H:%M:%S')} {msg}")
    except Exception:
        pass

# -------------------- WebSocket core --------------------
async def subscribe_ticker(ws, products: list[str], chunk_size: int):
    """Subscribe in chunks and wait for the first ticker message."""
    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i+n]

    sent = 0
    chunk_size = max(1, min(int(chunk_size or 1), 50))
    for group in chunks(products, chunk_size):
        payload = {"type": "subscribe", "channels": [{"name": "ticker", "product_ids": group}]}
        txt = json.dumps(payload)
        await ws.send(txt)
        state.last_subscribe = txt
        sent += len(group)
    dbg(f"subscribed ticker for {sent} products")

    # Wait for any ticker to confirm
    deadline = time.time() + FIRST_TICK_TIMEOUT
    while time.time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
        try:
            m = json.loads(raw)
        except Exception:
            continue
        if m.get("type") == "ticker":
            return True
    raise asyncio.TimeoutError("No ticker after subscribe()")

async def handle_message(m, now_ts):
    """Parse a single exchange 'ticker' message."""
    if m.get("type") != "ticker":
        return False
    pid = m.get("product_id")
    if pid not in state.deques:
        return False
    price = float(m.get("price") or 0)
    size = float(m.get("last_size") or 0)
    state.rows_q.put((pid, now_ts, price, size))
    state.last_msg_ts = now_ts
    return True

async def ws_run(url: str, products: list[str], chunk_size: int):
    """Connect, subscribe, then CONTINUOUSLY read and push into queue."""
    import websockets
    state.connect_attempt += 1
    dbg(f"connect -> {url}")

    connect_coro = websockets.connect(
        url,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=5,
        max_size=2**22,
        extra_headers={
            "User-Agent": "Mozilla/5.0 (StreamlitCloud)",
            "Origin": "https://share.streamlit.io",
            "Accept": "*/*",
        },
    )
    conn = await asyncio.wait_for(connect_coro, timeout=6.0)
    async with conn as ws:
        state.active_url = url
        ok = await subscribe_ticker(ws, products, chunk_size)
        if not ok:
            raise asyncio.TimeoutError("Subscribe confirmed False")

        state.connected = True
        dbg("subscribed; entering continuous read loop")

        # Continuous read loop — if we go silent for NO_MSG_GRACE, reconnect
        silent_since = time.time()
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                # no message for 5s: check longer grace window
                if (time.time() - state.last_msg_ts) > NO_MSG_GRACE:
                    raise asyncio.TimeoutError("No messages for grace window")
                continue

            now_ts = time.time()
            try:
                m = json.loads(raw)
            except Exception:
                continue
            changed = await handle_message(m, now_ts)
            if changed:
                silent_since = now_ts

# -------------------- Worker thread --------------------
def worker(products: list[str], chunk_size: int):
    """Hardened worker loop: run ws_run(), reconnect on any failure."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        dbg("worker loop created")
        while True:
            try:
                state.connected = False
                state.err = ""
                state.active_url = EXC_WS_URL
                loop.run_until_complete(ws_run(EXC_WS_URL, products, chunk_size))
            except InvalidStatusCode as e:
                state.err = f"HTTP {getattr(e, 'status_code', '?')}"
                dbg(state.err); state.reconnections += 1; time.sleep(2.0)
            except InvalidMessage as e:
                state.err = f"Invalid WS handshake: {e}"
                dbg(state.err); state.reconnections += 1; time.sleep(2.0)
            except asyncio.TimeoutError as e:
                state.err = f"Timeout: {e}"
                dbg(state.err); state.reconnections += 1; time.sleep(2.0)
            except Exception as e:
                state.err = f"{type(e).__name__}: {e}"
                dbg(state.err); dbg(traceback.format_exc().splitlines()[-1])
                state.reconnections += 1; time.sleep(2.0)
    except Exception as e:
        state.err = f"Worker init error: {type(e).__name__}: {e}"
        dbg(state.err); dbg(traceback.format_exc().splitlines()[-1])

# -------------------- Sidebar --------------------
with st.sidebar:
    st.subheader("Source & Universe")
    quote = st.selectbox("Quote currency preset", ["USD", "USDC", "USDT", "BTC"], index=0, key="quote")
    discovered = discover_products(quote)
    st.caption(f"Discovered {len(discovered)} products ending with -{quote}")

    use_wl_only = st.checkbox("Use watchlist only (ignore discovery)", True, key="wl_only")
    wl_text = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD", key="wl_text")
    max_products = st.slider("Max products to subscribe", 10, 200, min(50, max(10, len(discovered))), step=5, key="maxp")

    st.subheader("WebSocket (Exchange feed)")
    st.caption("Mode fixed to Exchange feed • Channel: ticker")
    chunk_size = st.slider("Subscribe chunk size", 2, 200, 10, step=1, key="chunk")
    pause = st.checkbox("Pause streaming (UI keeps last values)", value=False, key="pause")
    restart = st.button("🔄 Restart stream")

    # Safe tiny config
    if st.button("🛟 Use safe tiny config"):
        state.safe_cfg = {"wl_only": True, "wl_text": "BTC-USD, ETH-USD, SOL-USD", "maxp": 3, "chunk": 3}
        st.success("Applied tiny config. Click 🔄 Restart stream.")
    if st.button("Clear safe config"):
        state.safe_cfg = None
        st.info("Safe config cleared.")

    # Force connect
    def force_connect():
        def _runner():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                dbg("FORCE: one-shot exchange connect")
                loop.run_until_complete(ws_run(EXC_WS_URL, products, st.session_state.get("chunk", 10)))
            except Exception as e:
                state.err = f"Force error: {type(e).__name__}: {e}"
                dbg(state.err)
        threading.Thread(target=_runner, daemon=True).start()

    if st.button("⚡ Force connect (hot‑fix)"):
        force_connect()
        st.info("Force connect started (background).")

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
use_wl_only = cfg_get("wl_only", True)
wl_text_val = cfg_get("wl_text", "")
maxp_val = cfg_get("maxp", 50)

if use_wl_only and wl_text_val.strip():
    products = [x.strip() for x in wl_text_val.split(",") if x.strip()]
else:
    products = discover_products(st.session_state.get("quote", "USD"))[:maxp_val]

for pid in products:
    if pid not in state.deques:
        state.deques[pid] = collections.deque(maxlen=5000)

# -------------------- Start/restart worker --------------------
if "ws_thread" not in st.session_state:
    st.session_state["ws_thread"] = None

thr = st.session_state["ws_thread"]
need_restart = (thr is None) or (not getattr(thr, "is_alive", lambda: False)())

if WEBSOCKETS_OK and (not st.session_state.get("pause", False)) and (need_restart or restart):
    try:
        state.err = ""
        state.active_url = ""
        state.connect_attempt = 0
        dbg("starting worker")
        thr = threading.Thread(
            target=worker,
            args=(products, cfg_get("chunk", 10)),
            daemon=True,
            name="coinbase-ws-worker",
        )
        thr.start()
        st.session_state["ws_thread"] = thr
        st.info("Streaming thread started.")
        dbg(f"thread alive={thr.is_alive()}")
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

# -------------------- Ingest queue --------------------
def drain_queue():
    dirty = False
    while True:
        try:
            pid, ts, price, size = state.rows_q.get_nowait()
        except queue.Empty:
            break
        dq = state.deques.get(pid)
        if dq is None:
            dq = collections.deque(maxlen=5000)
            state.deques[pid] = dq
        dq.append((ts, price, size))
        cutoff = ts - HISTORY_SECONDS
        while dq and dq[0][0] < cutoff:
            dq.popleft()
        dirty = True
    return dirty

_ = drain_queue()

# -------------------- Compute table --------------------
tz_obj = pytz.timezone(tz_name)
rows = []
now_ts = time.time()

for pid, dq in state.deques.items():
    if not dq:
        continue

    prices = [p for _, p, _ in dq]
    s = pd.Series(prices)

    ema_f = s.ewm(span=ema_fast, adjust=False).mean().iloc[-1]
    ema_s = s.ewm(span=ema_slow, adjust=False).mean().iloc[-1]
    rsi_v = rsi(s, rsi_period).iloc[-1]

    roc_1 = pct_change_over_window(dq, now_ts, 60)
    roc_5 = pct_change_over_window(dq, now_ts, 300)
    roc_15 = pct_change_over_window(dq, now_ts, 900)

    vol_1 = volume_in_window(dq, now_ts, 60)

    minute_key = int(now_ts // 60)
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

    rows.append({
        "Pair": pid,
        "Last Update": last_ts.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "Price": float(s.iloc[-1]),
        "ROC 1m %": float(roc_1),
        "ROC 5m %": float(roc_5),
        "ROC 15m %": float(roc_15),
        "RSI": float(rsi_v),
        "EMA fast": float(ema_f),
        "EMA slow": float(ema_s),
        "Vol 1m": float(vol_1),
        "Vol Z": float(vol_z),
    })

df = pd.DataFrame(rows)

# Filter search
f = search.strip()
if f:
    keep = pd.Series([True] * len(df))
    for tok in f.split():
        if tok.startswith("-"):
            keep &= ~df["Pair"].str.contains(tok[1:].upper(), na=False)
        else:
            keep &= df["Pair"].str.contains(tok.upper(), na=False)
    df = df[keep]

# Movers (optional)
if show_movers and not df.empty:
    st.subheader("🚀 Top Movers")
    gainers = df.sort_values("ROC 1m %", ascending=False).head(movers_rows)
    losers = df.sort_values("ROC 1m %", ascending=True).head(movers_rows)
    cg, cl = st.columns(2)
    cg.dataframe(gainers[["Pair", "Price", "ROC 1m %", "Vol Z"]], use_container_width=True, height=200)
    cl.dataframe(losers[["Pair", "Price", "ROC 1m %", "Vol Z"]], use_container_width=True, height=200)

# Alerts
def maybe_alert(pid: str, reason: str):
    if not enable_alerts: return
    now = time.time()
    last = state.alert_last_ts.get(pid, 0.0)
    if now - last >= cooldown:
        state.alert_last_ts[pid] = now
        state.alert_log.append((datetime.utcnow().strftime("%H:%M:%S UTC"), pid, reason))

if enable_alerts and not df.empty:
    for _, r in df.iterrows():
        pid = r["Pair"]
        v = abs(r.get("ROC 1m %", np.nan))
        if not np.isnan(v) and v >= roc_thr: maybe_alert(pid, f"ROC1m≥{roc_thr}")
        vz = r.get("Vol Z", np.nan)
        if not np.isnan(vz) and vz >= volz_thr: maybe_alert(pid, f"VolZ≥{volz_thr}")
        rv = r.get("RSI", np.nan)
        if not np.isnan(rv):
            if rv >= rsi_up: maybe_alert(pid, f"RSI≥{rsi_up}")
            if rv <= rsi_dn: maybe_alert(pid, f"RSI≤{rsi_dn}")

if len(state.alert_log):
    st.subheader("🔔 Recent alerts")
    st.table(pd.DataFrame(list(state.alert_log), columns=["Time", "Pair", "Reason"]))

# Main table
st.subheader("Market table")
if not df.empty:
    show_cols = (
        ["Pair", "Price", "ROC 1m %", "Vol Z", "RSI", "Last Update"]
        if mobile_mode else
        ["Pair", "Last Update", "Price", "ROC 1m %", "ROC 5m %", "ROC 15m %", "RSI", "EMA fast", "EMA slow", "Vol 1m", "Vol Z"]
    )
    show_cols = [c for c in show_cols if c in df.columns]
    df_show = df[show_cols].sort_values("Pair").head(max_rows)

    fmt_all = {"Price":"{:.6f}","ROC 1m %":"{:.2f}","ROC 5m %":"{:.2f}","ROC 15m %":"{:.2f}","RSI":"{:.1f}",
               "EMA fast":"{:.6f}","EMA slow":"{:.6f}","Vol 1m":"{:.2f}","Vol Z":"{:.2f}"}
    fmt_use = {k:v for k,v in fmt_all.items() if k in df_show.columns}

    def sty_roc(v):
        if pd.isna(v): return ""
        return "color:#0f993e;" if v>0 else ("color:#d43f3a;" if v<0 else "")

    def sty_rsi(v):
        if pd.isna(v): return ""
        if v>=70: return "background-color:#ead7ff;"
        if v<=30: return "background-color:#ffe0e0;"
        return ""

    roc_cols = [c for c in ["ROC 1m %","ROC 5m %","ROC 15m %"] if c in df_show.columns]
    style_obj = df_show.style.format(fmt_use)
    if roc_cols: style_obj = style_obj.applymap(sty_roc, subset=roc_cols)
    if "RSI" in df_show.columns: style_obj = style_obj.applymap(sty_rsi, subset=["RSI"])
    st.dataframe(style_obj, use_container_width=True)
else:
    st.info("Waiting for data or no rows match the filter… Try a tiny watchlist and chunk=3–10.")

# (Streamlit will rerun automatically on user actions; no manual autorefresh here)
