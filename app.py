# Coinbase Price Movers — SIMPLE v1.3 (multi-timeframe w/ your presets)
# - Exchange feed (wss://ws-feed.exchange.coinbase.com), channel "ticker"
# - Tracks all pairs (or watchlist) and computes movement over multiple timeframes
# - Sort by chosen timeframe & metric (% or absolute Δ), ascending/descending
# - One long list, minimal UI, continuous reconnects (websocket-client)

import collections
import json
import queue
import threading
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytz
import requests
import streamlit as st

# -------------------- Constants --------------------
EXC_WS_URL = "wss://ws-feed.exchange.coinbase.com"
DEFAULT_WATCHLIST = ["BTC-USD", "ETH-USD", "SOL-USD"]

# Your requested timeframe choices (label -> seconds)
TIMEFRAME_CHOICES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
}

# -------------------- Page --------------------
st.set_page_config(page_title="Coinbase Price Movers — SIMPLE", layout="wide")
st.title("Coinbase Price Movers — SIMPLE (Multi‑Timeframe)")

# -------------------- Optional websocket-client import --------------------
WS_OK = True
try:
    import websocket  # websocket-client
except Exception:
    WS_OK = False

# -------------------- Product discovery --------------------
@st.cache_data(ttl=3600)
def discover_products(quote="USD"):
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
        return sorted(set(out)) or DEFAULT_WATCHLIST
    except Exception:
        return DEFAULT_WATCHLIST

# -------------------- Movement helpers --------------------
def pct_and_delta_over_window(records, now_ts, window_sec):
    """Return (% change, delta) from price at now-window to last price, or (nan, nan) if not enough data."""
    target = now_ts - window_sec
    ref_price, last_price = None, None
    for ts, price in reversed(records):
        if last_price is None:
            last_price = price
        if ts <= target:
            ref_price = price
            break
    if ref_price is None or ref_price == 0 or last_price is None:
        return np.nan, np.nan
    delta = last_price - ref_price
    pct = (delta / ref_price) * 100.0
    return pct, delta

def human_label_for_seconds(sec: int) -> str:
    if sec % 86400 == 0:
        d = sec // 86400
        return f"{d}d"
    if sec % 3600 == 0:
        h = sec // 3600
        return f"{h}h"
    if sec % 60 == 0:
        m = sec // 60
        return f"{m}m"
    return f"{sec}s"

# -------------------- Shared state --------------------
class Store:
    def __init__(self):
        # deques: pid -> deque[(ts, price)]
        self.deques = {}
        # row queue: (pid, ts, price)
        self.rows_q = queue.Queue()

        # connection & diagnostics
        self.connected = False
        self.last_msg_ts = 0.0
        self.reconnections = 0
        self.err = ""
        self.last_subscribe = ""
        self.active_url = ""
        self.connect_attempt = 0
        self.debug = collections.deque(maxlen=300)

        # safe preset config
        self.safe_cfg = None

state = Store()

def dbg(msg: str):
    try:
        state.debug.append(f"{time.strftime('%H:%M:%S')} {msg}")
    except Exception:
        pass

# -------------------- Sidebar --------------------
with st.sidebar:
    st.subheader("Universe")
    quote = st.selectbox("Quote currency", ["USD", "USDC", "USDT", "BTC"], index=0, key="quote_sel")
    discovered = discover_products(quote)
    st.caption(f"Found {len(discovered)} tradable pairs ending with -{quote}")

    use_watchlist = st.checkbox("Use watchlist only (ignore discovery)", True)
    wl_text = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
    max_pairs = st.slider("Max pairs", 10, 1000, min(200, max(50, len(discovered))), step=10)

    st.subheader("Timeframes")
    # Default selection: your list
    tf_default = ["1m", "5m", "15m", "1h", "4h", "6h", "12h", "1d"]
    tf_selected = st.multiselect(
        "Select timeframes (you can choose multiple)",
        options=list(TIMEFRAME_CHOICES.keys()),
        default=tf_default,
    )
    # Optional custom timeframe (seconds)
    custom_tf = st.number_input("Add custom timeframe (seconds)", min_value=0, max_value=7*24*3600, value=0, step=5)
    if custom_tf > 0:
        custom_label = human_label_for_seconds(int(custom_tf))
        if custom_label not in tf_selected:
            tf_selected.append(custom_label)

    # Build mapping label->seconds for selected set
    timeframe_map = {}
    for lbl in tf_selected:
        if lbl in TIMEFRAME_CHOICES:
            timeframe_map[lbl] = TIMEFRAME_CHOICES[lbl]
        else:
            # Parse simple labels (e.g., 90s, 7m, 2h, 3d) or fallback to custom_tf value
            base = custom_tf if custom_tf > 0 else 60
            try:
                if lbl.endswith("s") and lbl[:-1].isdigit():
                    timeframe_map[lbl] = int(lbl[:-1])
                elif lbl.endswith("m") and lbl[:-1].isdigit():
                    timeframe_map[lbl] = int(lbl[:-1]) * 60
                elif lbl.endswith("h") and lbl[:-1].isdigit():
                    timeframe_map[lbl] = int(lbl[:-1]) * 3600
                elif lbl.endswith("d") and lbl[:-1].isdigit():
                    timeframe_map[lbl] = int(lbl[:-1]) * 86400
                else:
                    timeframe_map[lbl] = int(base)
            except Exception:
                timeframe_map[lbl] = int(base)

    st.subheader("Ranking")
    sort_metric = st.selectbox("Rank by", ["% change", "absolute delta"], index=0)
    # ensure the sort timeframe comes from selected list
    sort_tf_label = st.selectbox("Sort timeframe", tf_selected if tf_selected else ["1m"], index=0)
    descending = st.checkbox("Sort descending (largest first)", True)

    st.subheader("WebSocket")
    chunk_size = st.slider("Subscribe chunk size", 2, 200, 10, step=1)
    restart = st.button("🔄 Restart stream")
    if st.button("🛟 Safe tiny config"):
        state.safe_cfg = {
            "use_watchlist": True,
            "wl_text": "BTC-USD, ETH-USD, SOL-USD",
            "max_pairs": 3,
            "chunk_size": 3,
            "tf_selected": ["1m", "5m"],
        }
        st.success("Applied tiny config. Click 🔄 Restart stream.")
    if st.button("Clear safe config"):
        state.safe_cfg = None
        st.info("Safe config cleared.")

    st.subheader("Display")
    tz_name = st.selectbox("Time zone", ["UTC", "US/Pacific", "US/Eastern"], index=0)
    max_rows = st.slider("Show top rows", 10, 5000, 1000, step=10)
    search = st.text_input("Filter (e.g., 'BTC' or '-USD')", "")

# apply safe config if present
def cfg_get(key, default=None):
    if state.safe_cfg and key in state.safe_cfg:
        return state.safe_cfg[key]
    return st.session_state.get(key, default)

use_watchlist_v = state.safe_cfg["use_watchlist"] if state.safe_cfg and "use_watchlist" in state.safe_cfg else use_watchlist
wl_text_v      = state.safe_cfg["wl_text"]       if state.safe_cfg and "wl_text" in state.safe_cfg else wl_text
max_pairs_v    = state.safe_cfg["max_pairs"]     if state.safe_cfg and "max_pairs" in state.safe_cfg else max_pairs
chunk_size_v   = state.safe_cfg["chunk_size"]    if state.safe_cfg and "chunk_size" in state.safe_cfg else chunk_size
tf_selected_v  = state.safe_cfg["tf_selected"]   if state.safe_cfg and "tf_selected" in state.safe_cfg else tf_selected

# Ensure timeframe_map aligns with final selected
if state.safe_cfg and "tf_selected" in state.safe_cfg:
    timeframe_map = {lbl: TIMEFRAME_CHOICES.get(lbl, 60) for lbl in tf_selected_v}

# -------------------- Build product list --------------------
if use_watchlist_v and wl_text_v.strip():
    products = [x.strip() for x in wl_text_v.split(",") if x.strip()]
else:
    products = discover_products(quote)[:max_pairs_v]

# Init deques
for pid in products:
    if pid not in state.deques:
        state.deques[pid] = collections.deque(maxlen=5000)

# History buffer large enough for the largest timeframe selected (+buffer)
max_tf_seconds = max(timeframe_map.values()) if timeframe_map else 60
HISTORY_SECONDS = int(max_tf_seconds * 1.2) + 30

# -------------------- WebSocket (threaded) --------------------
def subscribe_in_chunks(ws, product_ids, chunk):
    chunk = max(1, min(int(chunk or 1), 50))
    for i in range(0, len(product_ids), chunk):
        grp = product_ids[i:i+chunk]
        payload = {"type": "subscribe", "channels": [{"name": "ticker", "product_ids": grp}]}
        txt = json.dumps(payload)
        ws.send(txt)
        state.last_subscribe = txt
        dbg(f"subscribe sent ({len(grp)})")

def on_open_factory(product_ids, chunk):
    def _on_open(ws):
        dbg("on_open")
        try:
            subscribe_in_chunks(ws, product_ids, chunk)
            state.connected = True
            state.active_url = EXC_WS_URL
        except Exception as e:
            state.err = f"on_open error: {e}"
            dbg(state.err)
    return _on_open

def on_message(ws, message):
    try:
        m = json.loads(message)
    except Exception:
        return
    if m.get("type") != "ticker":
        return
    pid = m.get("product_id")
    if pid not in state.deques:
        return
    try:
        price = float(m.get("price") or 0)
    except Exception:
        return
    ts = time.time()
    state.rows_q.put((pid, ts, price))
    state.last_msg_ts = ts

def on_error(ws, error):
    state.err = f"on_error: {error}"
    dbg(state.err)

def on_close(ws, status_code, msg):
    state.connected = False
    dbg(f"on_close code={status_code} msg={msg}")

def ws_loop(product_ids, chunk):
    if not WS_OK:
        state.err = "websocket-client not installed. Add 'websocket-client' to requirements.txt"
        dbg(state.err)
        return
    import websocket
    websocket.enableTrace(False)
    while True:
        try:
            state.connect_attempt += 1
            dbg(f"connecting -> {EXC_WS_URL} (attempt {state.connect_attempt})")
            ws = websocket.WebSocketApp(
                EXC_WS_URL,
                on_open=on_open_factory(product_ids, chunk),
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                header=[
                    "User-Agent: Mozilla/5.0 (StreamlitCloud)",
                    "Origin: https://share.streamlit.io",
                    "Accept: */*",
                ],
            )
            ws.run_forever(ping_interval=20, ping_timeout=10)
        except Exception as e:
            state.err = f"loop exception: {type(e).__name__}: {e}"
            dbg(state.err)
        finally:
            state.connected = False
            state.reconnections += 1
            dbg("reconnecting in 2s…")
            time.sleep(2)

def start_ws(product_ids, chunk):
    try:
        ws_loop(product_ids, chunk)
    except Exception as e:
        state.err = f"start_ws error: {e}"
        dbg(state.err)

# manage thread handle
if "ws_thread" not in st.session_state:
    st.session_state["ws_thread"] = None

thr = st.session_state["ws_thread"]
need_restart = (thr is None) or (not getattr(thr, "is_alive", lambda: False)())

if need_restart or restart:
    try:
        state.err = ""
        state.active_url = ""
        state.connect_attempt = 0
        dbg("starting ws thread")
        thr = threading.Thread(
            target=start_ws,
            args=(products, chunk_size_v),
            daemon=True,
            name="cb-ws",
        )
        thr.start()
        st.session_state["ws_thread"] = thr
        st.info("Streaming thread started.")
    except Exception as e:
        state.err = f"Start error: {e}"
        dbg(state.err)

# -------------------- Status --------------------
now = time.time()
has_recent = (now - state.last_msg_ts) <= 20.0 if state.last_msg_ts else False
c1, c2, c3, c4 = st.columns(4)
c1.metric("Connected", "Yes" if (state.connected and has_recent) else "No")
c2.metric("Reconnections", state.reconnections)
c3.metric("Last message", "-" if not has_recent else datetime.fromtimestamp(state.last_msg_ts, tz=timezone.utc).strftime("%H:%M:%S %Z"))
c4.metric("Subscribed pairs", len(state.deques))
if state.err:
    st.error(f"Last error: {state.err}")

with st.expander("Diagnostics"):
    th = st.session_state.get("ws_thread")
    st.json({
        "WS_OK": WS_OK,
        "thread_alive": (th.is_alive() if th else False),
        "connect_attempt": state.connect_attempt,
        "active_ws_url": state.active_url,
        "last_subscribe": state.last_subscribe[:200] + ("..." if len(state.last_subscribe) > 200 else ""),
        "queue_size": state.rows_q.qsize(),
        "state.connected": state.connected,
        "state.last_msg_ts": state.last_msg_ts,
        "state.err": state.err,
        "products_first3": products[:3],
        "history_seconds": HISTORY_SECONDS,
        "debug_tail": list(state.debug)[-12:],
    })

# -------------------- Drain queue & trim history --------------------
def drain_queue(history_seconds):
    dirty = False
    while True:
        try:
            pid, ts, price = state.rows_q.get_nowait()
        except queue.Empty:
            break
        dq = state.deques.get(pid)
        if dq is None:
            dq = collections.deque(maxlen=5000)
            state.deques[pid] = dq
        dq.append((ts, price))
        cutoff = ts - history_seconds
        while dq and dq[0][0] < cutoff:
            dq.popleft()
        dirty = True
    return dirty

_ = drain_queue(HISTORY_SECONDS)

# -------------------- Build table with multiple timeframes --------------------
def build_table(timeframe_map: dict[str, int], sort_metric: str, sort_tf_label: str, descending: bool, tz_name: str):
    tz_obj = pytz.timezone(tz_name)
    now_ts = time.time()
    rows = []
    for pid, dq in state.deques.items():
        if not dq:
            continue
        last_price = dq[-1][1]
        last_ts = datetime.fromtimestamp(dq[-1][0], tz=timezone.utc).astimezone(tz_obj)
        row = {
            "Pair": pid,
            "Price": float(last_price),
            "Last Update": last_ts.strftime("%Y-%m-%d %H:%M:%S %Z"),
        }
        # Compute all selected timeframes
        for lbl, secs in timeframe_map.items():
            pct, delta = pct_and_delta_over_window(dq, now_ts, int(secs))
            row[f"% {lbl}"] = float(pct) if not np.isnan(pct) else np.nan
            row[f"Δ {lbl}"] = float(delta) if not np.isnan(delta) else np.nan
        rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Optional search filter
    s = (st.session_state.get("search") or "").strip()
    if s:
        keep = pd.Series([True] * len(df))
        for tok in s.split():
            if tok.startswith("-"):
                keep &= ~df["Pair"].str.contains(tok[1:].upper(), na=False)
            else:
                keep &= df["Pair"].str.contains(tok.upper(), na=False)
        df = df[keep]

    # Determine sort column
    if sort_metric == "% change":
        sort_col = f"% {sort_tf_label}"
    else:
        sort_col = f"Δ {sort_tf_label}"

    if sort_col not in df.columns:
        # fallback to first selected timeframe
        first_lbl = next(iter(timeframe_map.keys()))
        sort_col = (f"% {first_lbl}" if sort_metric == "% change" else f"Δ {first_lbl}")

    df = df.sort_values(sort_col, ascending=not descending, na_position="last")
    return df

df = build_table(timeframe_map, sort_metric, sort_tf_label, descending, tz_name)

# -------------------- Render --------------------
st.subheader("All pairs ranked by movement")
if df.empty:
    st.info("Waiting for data… Try a small watchlist and chunk=3–10.")
else:
    basic = ["Pair", "Price"]
    tf_cols = []
    for lbl in timeframe_map.keys():
        pct_col = f"% {lbl}"
        dlt_col = f"Δ {lbl}"
        if pct_col in df.columns: tf_cols.append(pct_col)
        if dlt_col in df.columns: tf_cols.append(dlt_col)
    cols = basic + tf_cols + ["Last Update"]
    cols = [c for c in cols if c in df.columns]

    # Respect sidebar max_rows
    max_rows_val = st.session_state.get("max_rows", 1000)
    df_show = df[cols].head(max_rows_val)

    # Formats
    fmt = {"Price": "{:.6f}"}
    for c in df_show.columns:
        if c.startswith("% "):
            fmt[c] = "{:.2f}"
        elif c.startswith("Δ "):
            fmt[c] = "{:.6f}"

    st.dataframe(df_show.style.format(fmt), use_container_width=True, height=640)
