# Coinbase Momentum & Volume Dashboard (Streamlit)
# ------------------------------------------------
# What this does
# - Discovers Coinbase spot trading pairs (best-effort public endpoint fallback)
# - Subscribes to Advanced Trade WebSocket (ticker_batch) for many products
# - Computes momentum (ROC 1m/5m/15m), RSI(14), EMAs, and a simple volume spike score
# - Renders an interactive, spreadsheet-like live table with filters & alerts
#
# How to run locally
#   1) pip install -r requirements.txt
#   2) streamlit run app.py
#   3) For phone on same Wi‑Fi: streamlit run app.py --server.address 0.0.0.0 --server.port 8501
#
# Notes
# - Public discovery uses the legacy Exchange products endpoint as a fallback. If it fails,
#   we fall back to a small default list. You can paste your own list in the sidebar.
# - Advanced Trade Market Data WS is public; no API key required for ticker/ticker_batch.

import asyncio
import collections
import json
import math
import queue
import threading
import time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import pytz
import requests
import streamlit as st
import websockets

# ---------------------- Config ----------------------
WS_URL = "wss://advanced-trade-ws.coinbase.com"
DEFAULT_PRODUCTS = [
    "BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "AVAX-USD", "LINK-USD", "DOGE-USD",
    "XRP-USD", "LTC-USD", "BCH-USD", "MATIC-USD", "ATOM-USD", "AAVE-USD", "UNI-USD"
]
CHANNEL = "ticker_batch"  # or "ticker"
HISTORY_SECONDS = 20 * 60   # keep ~20 minutes of tick history per product
RSI_PERIOD = 14
REFRESH_MS = 750

# ----------------- Discovery helpers ----------------
@st.cache_data(ttl=60 * 60)
def discover_products(quote_filter="USD"):
    """Attempt to discover tradable products. Returns a sorted list of product IDs.
    Uses public Coinbase Exchange endpoint as a fallback; filters to {BASE}-{quote_filter}.
    """
    try:
        # Public Coinbase Exchange products endpoint (fallback-only)
        resp = requests.get("https://api.exchange.coinbase.com/products", timeout=10)
        resp.raise_for_status()
        items = resp.json()
        product_ids = []
        for it in items:
            pid = it.get("id")  # e.g., "BTC-USD"
            status = it.get("status", "")
            trading_disabled = it.get("trading_disabled", False)
            if not pid or trading_disabled or status.lower() not in ("online", "active", ""):
                continue
            if pid.endswith(f"-{quote_filter}"):
                product_ids.append(pid)
        if not product_ids:
            return sorted(DEFAULT_PRODUCTS)
        return sorted(set(product_ids))
    except Exception:
        return sorted(DEFAULT_PRODUCTS)

# ----------------- Indicator functions --------------

def ema(series: pd.Series, span: int):
    return series.ewm(span=span, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out

def pct_change_over_window(records, now_ts, window_sec):
    """records: deque of (ts, price, size)
    return pct change vs price at (now - window_sec)."""
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

# ----------------- App state ------------------------
class Store:
    def __init__(self):
        self.products = []
        self.deques = {}  # product_id -> deque[(ts, price, size)]
        self.last_row = {}  # product_id -> dict for table
        self.alert_last_ts = {}

state = Store()
rows_q = queue.Queue()

# ----------------- WebSocket loop -------------------
async def ws_loop(product_ids):
    subscribe_msg = {
        "type": "subscribe",
        "channel": CHANNEL,
        "product_ids": product_ids,
    }
    async with websockets.connect(WS_URL, ping_interval=20) as ws:
        await ws.send(json.dumps(subscribe_msg))
        while True:
            raw = await ws.recv()
            msg = json.loads(raw)
            mtype = msg.get("type")
            now = time.time()
            if mtype == "ticker_batch":
                # Expected: {type: 'ticker_batch', events: [{... tickers: [{product_id, price, time, last_size, ...}, ...]}]}
                events = msg.get("events") or []
                for ev in events:
                    tickers = ev.get("tickers") or []
                    for t in tickers:
                        pid = t.get("product_id")
                        price = float(t.get("price") or 0)
                        size = float(t.get("last_size") or 0)
                        rows_q.put((pid, now, price, size))
            elif mtype == "ticker":
                pid = msg.get("product_id")
                price = float(msg.get("price") or 0)
                size = float(msg.get("last_size") or 0)
                rows_q.put((pid, now, price, size))
            # else ignore other messages

def start_ws(product_ids):
    asyncio.run(ws_loop(product_ids))

# ----------------- UI -------------------------------
st.set_page_config(page_title="Coinbase Momentum & Volume Monitor", layout="wide")
st.title("Momentum & Volume Dashboard — Coinbase")

with st.sidebar:
    st.subheader("Settings")
    quote = st.selectbox("Quote currency filter (for discovery)", ["USD", "USDC", "USDT", "BTC"], index=0)
    discovered = discover_products(quote_filter=quote)
    st.caption(f"Discovered {len(discovered)} products ending with -{quote}")
    custom_products = st.text_area("Products (comma-separated) — leave blank to use discovered", value="")
    if custom_products.strip():
        products = [x.strip() for x in custom_products.split(",") if x.strip()]
    else:
        products = discovered

    st.divider()
    st.caption("Alert thresholds")
    roc_1m_thr = st.number_input("Alert if |ROC 1m| ≥ (%)", value=0.7, step=0.1)
    vol_z_thr = st.number_input("Alert if Volume Z ≥", value=3.0, step=0.5)
    rsi_up = st.number_input("Alert if RSI crosses above", value=60, step=1)
    rsi_down = st.number_input("Alert if RSI crosses below", value=40, step=1)
    alert_cooldown = st.number_input("Per-pair alert cooldown (sec)", value=45, step=5)

    st.divider()
    st.caption("Display")
    tz_name = st.selectbox("Time zone", ["UTC", "US/Pacific", "US/Eastern"], index=0)
    max_rows = st.slider("Max rows shown", min_value=20, max_value=1000, value=300, step=20)

# Initialize store deques
if not state.products:
    state.products = products
    for pid in products:
        state.deques[pid] = collections.deque(maxlen=5000)

# Start WS thread (once)
if "ws_thread" not in st.session_state:
    t = threading.Thread(target=start_ws, args=(products,), daemon=True)
    t.start()
    st.session_state["ws_thread"] = True

# Main table placeholder
placeholder = st.empty()

# Rolling volume stats support
vol_stats = {}  # pid -> deque of last N 1m volumes for z-score
VOL_BASE_WINDOWS = 20

# Helper: compute per-pair indicators into a DataFrame row
def compute_row(pid, dq, tz):
    now = time.time()
    if not dq:
        return None
    # Extract series of (ts, price)
    times = [ts for ts, _, _ in dq]
    prices = [pr for _, pr, _ in dq]
    sizes = [sz for _, _, sz in dq]
    s = pd.Series(prices)
    ema12 = ema(s, 12).iloc[-1]
    ema26 = ema(s, 26).iloc[-1]
    rsi14 = rsi(s, RSI_PERIOD).iloc[-1]

    roc_1m = pct_change_over_window(dq, now, 60)
    roc_5m = pct_change_over_window(dq, now, 5 * 60)
    roc_15m = pct_change_over_window(dq, now, 15 * 60)

    vol_1m = volume_in_window(dq, now, 60)
    # Track minute buckets for baseline
    minute_key = int(now // 60)
    if pid not in vol_stats:
        vol_stats[pid] = {"last_key": minute_key, "deque": collections.deque(maxlen=VOL_BASE_WINDOWS)}
    vs = vol_stats[pid]
    if vs["last_key"] != minute_key:
        # push previous minute's volume sum
        prev_min_vol = volume_in_window(dq, (minute_key * 60), 60)
        vs["deque"].append(prev_min_vol)
        vs["last_key"] = minute_key
    # z-score
    vols = np.array(vs["deque"]) if len(vs["deque"]) else np.array([vol_1m])
    vmean, vstd = float(vols.mean()), float(vols.std(ddof=1) if len(vols) > 1 else 0.0)
    if vstd == 0:
        vol_z = 0.0
    else:
        vol_z = (vol_1m - vmean) / vstd

    last_price = prices[-1]
    last_ts = datetime.fromtimestamp(times[-1], tz=timezone.utc).astimezone(tz)

    return {
        "Pair": pid,
        "Last Update": last_ts.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "Price": last_price,
        "ROC 1m %": roc_1m,
        "ROC 5m %": roc_5m,
        "ROC 15m %": roc_15m,
        "RSI(14)": rsi14,
        "EMA12": ema12,
        "EMA26": ema26,
        "Vol 1m": vol_1m,
        "Vol Z": vol_z,
    }

# Ingest loop
last_render = 0
while True:
    # Drain queue quickly
    drained = 0
    try:
        while True:
            pid, ts, price, size = rows_q.get_nowait()
            if pid not in state.deques:
                continue
            dq = state.deques[pid]
            dq.append((ts, price, size))
            # prune old history
            cutoff = ts - HISTORY_SECONDS
            while dq and dq[0][0] < cutoff:
                dq.popleft()
            drained += 1
    except queue.Empty:
        pass

    # Refresh UI
    now = time.time()
    if now - last_render >= REFRESH_MS / 1000.0:
        tz = pytz.timezone(tz_name)
        rows = []
        for pid, dq in state.deques.items():
            r = compute_row(pid, dq, tz)
            if r:
                rows.append(r)
        if rows:
            df = pd.DataFrame(rows)
            # Alerts
            alerts = []
            for _, row in df.iterrows():
                pid = row["Pair"]
                trig = False
                reasons = []
                if isinstance(row["ROC 1m %"], float) and not math.isnan(row["ROC 1m %"]):
                    if abs(row["ROC 1m %"]) >= roc_1m_thr:
                        trig = True; reasons.append(f"ROC1m {row['ROC 1m %']:.2f}%")
                if isinstance(row["Vol Z"], float) and row["Vol Z"] >= vol_z_thr:
                    trig = True; reasons.append(f"VolZ {row['Vol Z']:.1f}")
                if isinstance(row["RSI(14)"], float):
                    if row["RSI(14)"] >= rsi_up:
                        trig = True; reasons.append(f"RSI≥{rsi_up}")
                    if row["RSI(14)"] <= rsi_down:
                        trig = True; reasons.append(f"RSI≤{rsi_down}")
                if trig:
                    last_t = state.alert_last_ts.get(pid, 0)
                    if now - last_t > alert_cooldown:
                        st.toast(f"⚡ {pid}: " + ", ".join(reasons), icon="🔥")
                        state.alert_last_ts[pid] = now
                        # Optional: webhook
                        # try:
                        #     requests.post(WEBHOOK_URL, json={"content": f"⚡ {pid}: {', '.join(reasons)}"}, timeout=3)
                        # except Exception:
                        #     pass

            # Format & sort
            df = df.sort_values("Pair")
            # Highlight movers
            def style_df(sdf: pd.DataFrame):
                styled = sdf.style.format({
                    "Price": "{:.6f}",
                    "ROC 1m %": "{:.2f}",
                    "ROC 5m %": "{:.2f}",
                    "ROC 15m %": "{:.2f}",
                    "RSI(14)": "{:.1f}",
                    "EMA12": "{:.6f}",
                    "EMA26": "{:.6f}",
                    "Vol 1m": "{:.2f}",
                    "Vol Z": "{:.2f}",
                })
                # color map for ROC and RSI
                def color_roc(val):
                    if pd.isna(val): return ""
                    if val > 0: return "color: #0f993e;"
                    if val < 0: return "color: #d43f3a;"
                    return ""
                def color_rsi(val):
                    if pd.isna(val): return ""
                    if val >= 70: return "background-color: #ead7ff;"
                    if val <= 30: return "background-color: #ffe0e0;"
                    return ""
                styled = styled.applymap(color_roc, subset=["ROC 1m %", "ROC 5m %", "ROC 15m %"]) 
                styled = styled.applymap(color_rsi, subset=["RSI(14)"])
                return styled

            # Limit rows shown
            show_df = df.head(max_rows)
            placeholder.dataframe(style_df(show_df), use_container_width=True)
        else:
            placeholder.info("Waiting for data…")

        last_render = now

    time.sleep(0.05)
