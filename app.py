# Coinbase Momentum & Volume Dashboard — CLOUD v4.5 (mobile + Top Movers + Restart stream)
# Deploy: app.py + requirements.txt + README.md in a GitHub repo → Streamlit Cloud.
# Cloud tip: in Deploy → Advanced settings, set Python version to 3.12.

import asyncio, collections, json, math, queue, threading, time, os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytz
import requests
import streamlit as st

# Try to import websockets (installed from requirements.txt on Cloud)
try:
    import websockets
    WEBSOCKETS_OK = True
except Exception:
    WEBSOCKETS_OK = False

WS_URL = "wss://advanced-trade-ws.coinbase.com"
DEFAULT_PRODUCTS = [
    "BTC-USD","ETH-USD","SOL-USD","ADA-USD","AVAX-USD","LINK-USD","DOGE-USD",
    "XRP-USD","LTC-USD","BCH-USD","MATIC-USD","ATOM-USD","AAVE-USD","UNI-USD"
]

HISTORY_SECONDS = 20 * 60
REFRESH_MS = 750
NO_MSG_GRACE = 20  # seconds without messages before we display '-' and allow restart

st.set_page_config(page_title="Momentum & Volume — CLOUD v4.5", layout="wide")

# Light CSS for better mobile usability
st.markdown("""
<style>
html, body, [class*="css"] { font-size: 16px; }
div[data-testid="stMetricValue"] { font-size: 18px !important; }
div[data-testid="stDataFrame"] { padding-top: 0.25rem; }
section[data-testid="stSidebar"] { overscroll-behavior: contain; }
.small-table td, .small-table th { padding: 0.25rem 0.5rem !important; font-size: 14px; }
</style>
""", unsafe_allow_html=True)

st.markdown("# Momentum & Volume Dashboard — **CLOUD v4.5**")
st.caption("Mobile‑friendly build with status bar, sidebar controls, WebSocket test, Top Movers, and a Restart stream button.")

# ---------- Discovery ----------
@st.cache_data(ttl=3600)
def discover_products(quote_filter="USD"):
    try:
        resp = requests.get("https://api.exchange.coinbase.com/products", timeout=10)
        resp.raise_for_status()
        product_ids = []
        for it in resp.json():
            pid = it.get("id")
            if not pid:
                continue
            status = (it.get("status") or "").lower()
            if it.get("trading_disabled", False) or status not in ("online","active",""):
                continue
            if pid.endswith(f"-{quote_filter}"):
                product_ids.append(pid)
        return sorted(set(product_ids)) or sorted(DEFAULT_PRODUCTS)
    except Exception:
        return sorted(DEFAULT_PRODUCTS)

# ---------- Indicators ----------
def ema(series: pd.Series, span: int):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14):
    d = series.diff()
    g = d.clip(lower=0).rolling(period).mean()
    l = (-d.clip(upper=0)).rolling(period).mean()
    rs = g / l.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def pct_change_over_window(records, now_ts, window_sec):
    target = now_ts - window_sec
    ref_price = None
    last_price = None
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
    vol = 0.0
    for ts, _, size in reversed(records):
        if ts < cutoff:
            break
        vol += size or 0.0
    return vol

# ---------- State ----------
class Store:
    def __init__(self):
        self.deques = {}            # pid -> deque[(ts, price, size)]
        self.alert_last_ts = {}
        self.connected = False
        self.last_msg_ts = 0.0
        self.reconnections = 0
        self.err = ""
        self.rows_q = queue.Queue()

state = Store()

# ---------- WebSocket worker ----------
async def ws_loop(product_ids, channel, chunk_size):
    import websockets  # ensure present at runtime
    def chunks(lst, n):
        for i in range(0, len(lst), n):
            yield lst[i:i+n]
    try:
        async with websockets.connect(WS_URL, ping_interval=20) as ws:
            state.connected = True
            state.err = ""
            for group in chunks(product_ids, chunk_size):
                await ws.send(json.dumps({"type":"subscribe","channel":channel,"product_ids":group}))
            while True:
                raw = await ws.recv()
                msg = json.loads(raw)
                state.last_msg_ts = time.time()
                t = state.last_msg_ts
                mtype = msg.get("type")
                if mtype == "ticker_batch":
                    for ev in msg.get("events") or []:
                        for tk in ev.get("tickers") or []:
                            pid = tk.get("product_id")
                            price = float(tk.get("price") or 0)
                            size = float(tk.get("last_size") or 0)
                            state.rows_q.put((pid, t, price, size))
                elif mtype == "ticker":
                    pid = msg.get("product_id")
                    price = float(msg.get("price") or 0)
                    size = float(msg.get("last_size") or 0)
                    state.rows_q.put((pid, t, price, size))
    except Exception as e:
        state.connected = False
        state.err = str(e)
        state.reconnections += 1

def ws_worker(product_ids, channel, chunk_size):
    while True:
        try:
            asyncio.run(ws_loop(product_ids, channel, chunk_size))
        except Exception as e:
            state.err = f"Worker error: {e}"
        time.sleep(2)

# ---------- Sidebar ----------
with st.sidebar:
    st.subheader("Source & Universe")
    quote = st.selectbox("Quote currency preset", ["USD","USDC","USDT","BTC"], index=0)
    discovered = discover_products(quote)
    st.caption(f"Discovered {len(discovered)} products ending with -{quote}")
    use_watchlist = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    watchlist = st.text_area("Watchlist (comma-separated)", value="BTC-USD, ETH-USD")
    max_products = st.slider("Max products to subscribe", 10, 1000, min(200, max(10,len(discovered))), step=10)

    st.subheader("WebSocket")
    channel = st.selectbox("Channel", ["ticker_batch","ticker"], index=0)
    chunk_size = st.slider("Subscribe chunk size", 25, 500, 150, step=25)
    pause = st.checkbox("Pause streaming (UI keeps last values)", value=False)
    # NEW: manual restart
    restart_stream = st.button("🔄 Restart stream")

    st.subheader("Indicators")
    rsi_period = st.number_input("RSI period", value=14, step=1)
    ema_fast = st.number_input("EMA fast", value=12, step=1)
    ema_slow = st.number_input("EMA slow", value=26, step=1)

    st.subheader("Alerts")
    enable_alerts = st.checkbox("Enable alerts", value=True)
    roc_thr = st.number_input("Alert if |ROC 1m| ≥ (%)", value=0.7, step=0.1)
    volz_thr = st.number_input("Alert if Volume Z ≥", value=3.0, step=0.5)
    rsi_up = st.number_input("RSI crosses above", value=60, step=1)
    rsi_dn = st.number_input("RSI crosses below", value=40, step=1)
    cooldown = st.number_input("Alert cooldown (sec)", value=45, step=5)

    st.subheader("Display")
    tz_name = st.selectbox("Time zone", ["UTC","US/Pacific","US/Eastern"], index=0)
    max_rows = st.slider("Max rows shown", 20, 1000, 300, step=20)
    search = st.text_input("Search filter (e.g., BTC or -USD)", value="")
    mobile_mode = st.checkbox("📱 Mobile mode (compact view)", value=True)

    st.subheader("Top Movers")
    show_movers = st.checkbox("Show Top Movers strip", value=True)
    movers_rows = st.slider("Rows per movers panel", 3, 10, 5)

# ---------- WebSocket Connectivity Test ----------
# ---------- WebSocket Connectivity Test ----------
st.markdown("### 🔌 Test Coinbase WebSocket")

if not WEBSOCKETS_OK:
    st.warning("`websockets` installs from requirements.txt on first build. If test fails, try again after the app fully rebuilds.")
else:
    import contextlib

    async def quick_test_once():
        """
        One quick attempt to open the Coinbase Advanced Trade WS and receive a ticker msg.
        """
        try:
            import websockets
            async with websockets.connect(WS_URL, ping_interval=10) as ws:
                # subscribe to a single busy pair to maximize chance of a fast tick
                await ws.send(json.dumps({
                    "type": "subscribe",
                    "channel": "ticker",
                    "product_ids": ["BTC-USD"]
                }))
                # wait up to 10s for any message
                msg = await asyncio.wait_for(ws.recv(), timeout=10)
                return True, "Received a message."
        except asyncio.TimeoutError:
            return False, "Connected but no data within 10s (try Channel='ticker' and a tiny watchlist)."
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def quick_test_with_retries(max_tries: int = 3, delay_sec: float = 1.5):
        """
        Runs up to max_tries attempts; returns first success or last failure.
        """
        last = (False, "Not attempted")
        for i in range(1, max_tries + 1):
            try:
                ok, info = asyncio.run(quick_test_once())
            except Exception as e:
                ok, info = False, f"Runner error: {e}"
            # show per‑attempt status inline (non‑blocking)
            st.caption(f"WS test attempt {i}/{max_tries}: {'✅ success' if ok else '❌ fail'} — {info}")
            last = (ok, info)
            if ok:
                break
            # small pause between attempts (don’t block Streamlit event loop)
            with contextlib.suppress(Exception):
                time.sleep(delay_sec)
        return last

    if st.button("Run WebSocket connectivity test"):
        ok, info = quick_test_with_retries(max_tries=3, delay_sec=1.5)
        if ok:
            st.success(f"CONNECTED ✅ — {info}")
        else:
            st.error(f"FAILED ❌ — {info if info else 'No connection established'}")

# ---------- Determine product list ----------
if use_watchlist and watchlist.strip():
    products = [x.strip() for x in watchlist.split(",") if x.strip()]
else:
    products = discovered[:max_products]

# ---------- Initialize deques ----------
for pid in products:
    if pid not in state.deques:
        state.deques[pid] = collections.deque(maxlen=5000)

# ---------- Start / Restart WS thread (robust) ----------
if "ws_started_cloud" not in st.session_state:
    st.session_state["ws_started_cloud"] = False

should_start = WEBSOCKETS_OK and not pause and (
    not st.session_state["ws_started_cloud"] or restart_stream
)

if should_start:
    try:
        t = threading.Thread(target=ws_worker, args=(products, channel, chunk_size), daemon=True)
        t.start()
        st.session_state["ws_started_cloud"] = True
        st.toast("Streaming started ✅", icon="✅")
    except Exception as e:
        st.session_state["ws_started_cloud"] = False
        st.error(f"Could not start streaming: {e}")

# ---------- Status Bar ----------
now_ts = time.time()
has_recent_msg = (now_ts - state.last_msg_ts) <= NO_MSG_GRACE if state.last_msg_ts else False
c1,c2,c3,c4 = st.columns(4)
c1.metric("Connected", "Yes" if (state.connected and has_recent_msg) else "No")
c2.metric("Reconnections", state.reconnections)
c3.metric("Last message", "-" if not has_recent_msg else datetime.fromtimestamp(state.last_msg_ts, tz=timezone.utc).strftime("%H:%M:%S UTC"))
c4.metric("Subscribed pairs", len(state.deques))
if state.err:
    st.error(f"Last error: {state.err}")

# ---------- Row computation ----------
def compute_row(pid, dq, tz, rsi_p, e_fast, e_slow):
    now = time.time()
    if not dq:
        return None
    prices = [p for _,p,_ in dq]
    s = pd.Series(prices)
    ema_f = s.ewm(span=e_fast, adjust=False).mean().iloc[-1]
    ema_s = s.ewm(span=e_slow, adjust=False).mean().iloc[-1]
    rsi_v = rsi(s, rsi_p).iloc[-1]

    def pctwin(w): 
        return pct_change_over_window(dq, now, w)
    roc_1 = pctwin(60); roc_5 = pctwin(300); roc_15 = pctwin(900)

    vol_1 = volume_in_window(dq, now, 60)
    # Simple rolling baseline (last 20 minutes of 1-min buckets)
    minute_key = int(now // 60)
    if "_vol" not in st.session_state:
        st.session_state["_vol"] = {}
    vs = st.session_state["_vol"].setdefault(pid, {"last": minute_key, "vals": collections.deque(maxlen=20)})
    if vs["last"] != minute_key:
        prev_min = volume_in_window(dq, (minute_key * 60), 60)
        vs["vals"].append(prev_min)
        vs["last"] = minute_key
    vols = np.array(vs["vals"]) if len(vs["vals"]) else np.array([vol_1])
    vmean = float(vols.mean())
    vstd = float(vols.std(ddof=1) if len(vols)>1 else 0.0)
    vol_z = 0.0 if vstd == 0 else (vol_1 - vmean) / vstd

    last_ts = datetime.fromtimestamp(dq[-1][0], tz=timezone.utc).astimezone(pytz.timezone(tz_name))
    return {
        "Pair": pid,
        "Last Update": last_ts.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "Price": prices[-1],
        "ROC 1m %": roc_1,
        "ROC 5m %": roc_5,
        "ROC 15m %": roc_15,
        "RSI": rsi_v,
        "EMA fast": ema_f,
        "EMA slow": ema_s,
        "Vol 1m": vol_1,
        "Vol Z": vol_z,
    }

# ---------- Main loop ----------
placeholder_movers = st.container()
placeholder_table = st.empty()
last_render = 0

while True:
    # drain queue
    try:
        while True:
            pid, ts, price, size = state.rows_q.get_nowait()
            if pause:
                continue
            if pid not in state.deques:
                continue
            dq = state.deques[pid]
            dq.append((ts, price, size))
            cutoff = ts - HISTORY_SECONDS
            while dq and dq[0][0] < cutoff:
                dq.popleft()
    except queue.Empty:
        pass

    now = time.time()
    if now - last_render >= REFRESH_MS/1000.0:
        tz = pytz.timezone(tz_name)
        rows = []
        for pid, dq in state.deques.items():
            r = compute_row(pid, dq, tz, rsi_period, ema_fast, ema_slow)
            if r: rows.append(r)

        df = pd.DataFrame(rows)
        if search.strip():
            df = df[df["Pair"].str.contains(search.strip(), case=False, na=False)]

        # ---- Top Movers strip (compact, above table) ----
        if show_movers and not df.empty:
            with placeholder_movers:
                st.subheader("🚀 Top Movers (live)")
                mcols = st.columns(4) if not mobile_mode else st.columns(2)

                def tiny(tbl, cols_keep, title, col):
                    t = tbl[cols_keep].head(movers_rows).reset_index(drop=True)
                    col.markdown(f"**{title}**")
                    col.dataframe(t.style.hide(axis='index'), use_container_width=True, height=200)

                by_roc1_up   = df.sort_values("ROC 1m %", ascending=False)
                by_roc1_down = df.sort_values("ROC 1m %", ascending=True)
                by_volz      = df.sort_values("Vol Z", ascending=False)
                by_rsi_high  = df.sort_values("RSI", ascending=False)

                if not mobile_mode:
                    tiny(by_roc1_up,   ["Pair","ROC 1m %","Price"], "1‑min Gainers", mcols[0])
                    tiny(by_roc1_down, ["Pair","ROC 1m %","Price"], "1‑min Losers",  mcols[1])
                    tiny(by_volz,      ["Pair","Vol Z","Vol 1m"],   "Vol‑Z Spikes",  mcols[2])
                    tiny(by_rsi_high,  ["Pair","RSI","Price"],      "RSI Highs",     mcols[3])
                else:
                    tiny(by_roc1_up,   ["Pair","ROC 1m %","Price"], "1‑min Gainers", mcols[0])
                    tiny(by_roc1_down, ["Pair","ROC 1m %","Price"], "1‑min Losers",  mcols[1])
                    mcols2 = st.columns(2)
                    tiny(by_volz,      ["Pair","Vol Z","Vol 1m"],   "Vol‑Z Spikes",  mcols2[0])
                    tiny(by_rsi_high,  ["Pair","RSI","Price"],      "RSI Highs",     mcols2[1])
        else:
            placeholder_movers.empty()

        # ---- Main table ----
        if not df.empty:
            # Alerts
            if enable_alerts:
                for _, row in df.iterrows():
                    pid = row["Pair"]; reasons=[]
                    v=row.get("ROC 1m %")
                    if isinstance(v,float) and not math.isnan(v) and abs(v)>=roc_thr: reasons.append(f"ROC1m {v:.2f}%")
                    vz=row.get("Vol Z")
                    if isinstance(vz,float) and vz>=volz_thr: reasons.append(f"VolZ {vz:.1f}")
                    rsi_val=row.get("RSI")
                    if isinstance(rsi_val,float):
                        if rsi_val>=rsi_up: reasons.append(f"RSI≥{rsi_up}")
                        if rsi_val<=rsi_dn: reasons.append(f"RSI≤{rsi_dn}")
                    if reasons:
                        lt = state.alert_last_ts.get(pid, 0)
                        if now - lt > cooldown:
                            st.toast(f"⚡ {pid}: " + ", ".join(reasons), icon="🔥")
                            state.alert_last_ts[pid] = now

            if mobile_mode:
                cols = ["Pair","Price","ROC 1m %","Vol Z","RSI","Last Update"]
            else:
                cols = ["Pair","Last Update","Price","ROC 5m %","ROC 15m %","ROC 1m %","RSI","EMA fast","EMA slow","Vol 1m","Vol Z"]

            df_show = df[cols].sort_values("Pair").head(max_rows)

            def sty_roc(v):
                if pd.isna(v): return ""
                return "color:#0f993e;" if v>0 else ("color:#d43f3a;" if v<0 else "")
            def sty_rsi(v):
                if pd.isna(v): return ""
                if v>=70: return "background-color:#ead7ff;"
                if v<=30: return "background-color:#ffe0e0;"
                return ""

            styled = (df_show.style
                        .format({
                            "Price":"{:.6f}",
                            "ROC 1m %":"{:.2f}",
                            **({"ROC 5m %":"{:.2f}","ROC 15m %":"{:.2f}"} if not mobile_mode else {}),
                            "RSI":"{:.1f}",
                            **({"EMA fast":"{:.6f}","EMA slow":"{:.6f}","Vol 1m":"{:.2f}"} if not mobile_mode else {}),
                            "Vol Z":"{:.2f}"
                        })
                        .applymap(sty_roc, subset=[c for c in ["ROC 1m %","ROC 5m %","ROC 15m %"] if c in df_show.columns])
                        .applymap(sty_rsi, subset=["RSI"])
                     )
            placeholder_table.dataframe(styled, use_container_width=True)
        else:
            placeholder_table.info("Waiting for data or no rows match the filter… Try Channel='ticker' and a small watchlist if needed.")

        last_render = now

    time.sleep(0.05)
