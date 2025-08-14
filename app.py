# Coinbase Movers — Hybrid (WebSocket + REST) v3.0
# - Choose REST-only or WebSocket+REST (hybrid) from the sidebar
# - Timeframes: 1m, 5m, 15m, 1h, 4h, 6h, 12h, 1d
# - Percent change columns + aggregate sort (% ALL avg, % ALL max_abs)
# - Watchlist + max pairs + auto-refresh
# - WebSocket chunk subscribe with start/stop button

from __future__ import annotations

import math
import time
import json
import threading
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta

import requests
import pandas as pd
import streamlit as st

# -------------------- REST config --------------------
BASE_URL = "https://api.exchange.coinbase.com"

# UI timeframes (label -> seconds)
TIMEFRAME_CHOICES = {
    "1m" : 60,
    "5m" : 300,
    "15m": 900,
    "1h" : 3600,
    "4h" : 14400,   # computed from 1h buckets
    "6h" : 21600,
    "12h": 43200,   # computed from 1h buckets
    "1d" : 86400,
}
# Coinbase REST-supported granularities (seconds)
CB_GRANS = [60, 300, 900, 3600, 21600, 86400]  # 1m,5m,15m,1h,6h,1d

# -------------------- Page --------------------
st.set_page_config(page_title="Coinbase Movers — Hybrid (WS + REST)", layout="wide")
st.title("Coinbase Movers — Hybrid (WebSocket + REST)")

# -------------------- Sidebar --------------------
with st.sidebar:
    st.subheader("Mode")
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0)

    st.subheader("Universe")
    quote_currency = st.selectbox("Quote currency", ["USD", "USDT", "BTC"], index=0)
    use_watchlist = st.checkbox("Use watchlist only (ignore discovery)", False)
    wl_text = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
    max_pairs = st.slider("Max pairs", 10, 1000, 200, step=10)

    st.subheader("Timeframes")
    tf_selected = st.multiselect(
        "Select timeframes (one or more)",
        list(TIMEFRAME_CHOICES.keys()),
        default=["1m", "5m", "15m", "1h", "4h", "6h", "12h", "1d"],
    )

    st.subheader("Ranking / sort")
    sort_metric = st.selectbox(
        "Sort by",
        ["% ALL avg", "% ALL max_abs"] + [f"% {t}" for t in tf_selected],
        index=0,
    )
    descending = st.checkbox("Sort descending (largest first)", True)

    st.subheader("Auto-refresh")
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 15, step=5)
    st.caption("Auto-refresh re-runs the app. Data is cached to reduce rate limits.")

    if mode.startswith("WebSocket"):
        st.subheader("WebSocket")
        ws_chunk = st.slider("Subscribe chunk size", 2, 50, 10)
        col_a, col_b = st.columns(2)
        with col_a:
            start_ws = st.button("Start WebSocket", use_container_width=True)
        with col_b:
            stop_ws = st.button("Stop WebSocket", use_container_width=True)

# Auto-refresh
st.autorefresh(interval=refresh_sec * 1000, key="auto_refresh_key")

# -------------------- Session state init --------------------
if "ws_thread" not in st.session_state:
    st.session_state.ws_thread = None
if "ws_running" not in st.session_state:
    st.session_state.ws_running = False
if "ws_prices" not in st.session_state:
    st.session_state.ws_prices = {}   # pair -> latest float price
if "ws_last_err" not in st.session_state:
    st.session_state.ws_last_err = ""
if "ws_diag" not in st.session_state:
    st.session_state.ws_diag = []

# -------------------- Helpers --------------------
def best_granularity(seconds: int) -> int:
    """Pick the largest supported Coinbase granularity <= requested seconds."""
    cands = [g for g in CB_GRANS if g <= seconds]
    return cands[-1] if cands else 60

@st.cache_data(ttl=600)
def discover_pairs(quote: str) -> List[str]:
    """Discover tradable product IDs ending in the selected quote currency."""
    try:
        r = requests.get(f"{BASE_URL}/products", timeout=15)
        r.raise_for_status()
        data = r.json()
        out = []
        for it in data:
            pid = it.get("id")
            q = it.get("quote_currency", "")
            if pid and q and q.upper() == quote.upper():
                out.append(pid)
        return sorted(set(out))
    except Exception:
        return ["BTC-USD", "ETH-USD", "SOL-USD"]

def fetch_candles(pid: str, granularity: int, need_buckets: int) -> list:
    """
    Fetch enough candles at 'granularity' to compute a change 'need_buckets'
    back from latest close. Coinbase returns newest-first.
    """
    end = datetime.utcnow()
    start = end - timedelta(seconds=granularity * (need_buckets + 3))
    params = {
        "granularity": granularity,
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
    }
    try:
        r = requests.get(f"{BASE_URL}/products/{pid}/candles", params=params, timeout=15)
        if r.status_code != 200:
            return []
        candles = r.json()
        if not isinstance(candles, list):
            return []
        return candles
    except Exception:
        return []

def pct_change_for_window_from_candles(pid: str, window_sec: int) -> Optional[float]:
    g = best_granularity(window_sec)
    steps = max(1, math.ceil(window_sec / g))
    candles = fetch_candles(pid, g, steps)
    if len(candles) < steps + 1:
        return None
    latest = candles[0][4]   # close
    ref = candles[steps][4]  # close N buckets back
    if not ref:
        return None
    try:
        return (latest - ref) / ref * 100.0
    except Exception:
        return None

def aggregate_all(values: list) -> Tuple[Optional[float], Optional[float]]:
    clean = [v for v in values if isinstance(v, (float, int))]
    if not clean:
        return None, None
    avg = sum(clean) / len(clean)
    idx = max(range(len(clean)), key=lambda i: abs(clean[i]))
    return avg, clean[idx]

@st.cache_data(ttl=15)
def rest_spot_price(pid: str) -> Optional[float]:
    """Get last traded price via REST ticker; used in REST-only mode and hybrid fallback."""
    try:
        r = requests.get(f"{BASE_URL}/products/{pid}/ticker", timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        px = float(data.get("price"))
        return px
    except Exception:
        return None

# -------------------- WebSocket worker --------------------
def ws_worker(product_ids: List[str], chunk_size: int):
    """Background thread: connect to ws-feed.exchange.coinbase.com and stream 'ticker'."""
    try:
        from websocket import WebSocketApp
    except Exception:
        st.session_state.ws_last_err = "websocket-client not installed. Add 'websocket-client' to requirements.txt"
        st.session_state.ws_running = False
        return

    url = "wss://ws-feed.exchange.coinbase.com"
    st.session_state.ws_last_err = ""
    st.session_state.ws_diag.append(f"{datetime.utcnow():%H:%M:%S} starting ws thread")

    def on_message(ws, msg):
        try:
            data = json.loads(msg)
            # Expected ticker message has 'type': 'ticker' and fields 'product_id', 'price'
            if isinstance(data, dict) and data.get("type") == "ticker":
                pid = data.get("product_id")
                price = data.get("price")
                if pid and price is not None:
                    try:
                        st.session_state.ws_prices[pid] = float(price)
                    except Exception:
                        pass
        except Exception:
            pass

    def on_error(ws, err):
        st.session_state.ws_last_err = f"{datetime.utcnow():%H:%M:%S} error: {err}"
        st.session_state.ws_diag.append(st.session_state.ws_last_err)

    def on_close(ws, *args):
        st.session_state.ws_running = False
        st.session_state.ws_diag.append(f"{datetime.utcnow():%H:%M:%S} closed ws")

    def on_open(ws):
        st.session_state.ws_diag.append(f"{datetime.utcnow():%H:%M:%S} ws open")
        # Subscribe in chunks to avoid too-large payloads
        chunks = [product_ids[i:i+chunk_size] for i in range(0, len(product_ids), chunk_size)]
        for ch in chunks:
            sub = {
                "type": "subscribe",
                "channels": [{"name": "ticker", "product_ids": ch}],
            }
            ws.send(json.dumps(sub))
            time.sleep(0.25)

    ws = WebSocketApp(url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
    st.session_state.ws_running = True
    try:
        ws.run_forever(ping_interval=25, ping_timeout=10)
    except Exception as e:
        st.session_state.ws_last_err = f"Exception: {e}"
    st.session_state.ws_running = False

def ensure_ws(product_ids: List[str], chunk_size: int):
    """Start WS thread if not running; stop if requested."""
    # Start
    if start_ws and not st.session_state.ws_running:
        # clear prices for a clean start
        st.session_state.ws_prices = {}
        t = threading.Thread(target=ws_worker, args=(product_ids, chunk_size), daemon=True)
        t.start()
        st.session_state.ws_thread = t
    # Stop
    if stop_ws and st.session_state.ws_running:
        # websocket-client doesn't provide a direct stop from here; letting thread die on close
        st.session_state.ws_last_err = "Requested stop. Reload page to fully close."
        st.session_state.ws_running = False

# -------------------- Build universe --------------------
if use_watchlist and wl_text.strip():
    pairs = [x.strip().upper() for x in wl_text.split(",") if x.strip()]
else:
    pairs = discover_pairs(quote_currency)

pairs = pairs[:max_pairs]
st.caption(f"Tracking {len(pairs)} pairs ending in -{quote_currency.upper()}.")

# Manage WS if chosen
if mode.startswith("WebSocket"):
    ensure_ws(pairs, ws_chunk)

# -------------------- Collect data --------------------
rows = []
if not tf_selected:
    st.warning("Please select at least one timeframe from the sidebar.")
else:
    with st.spinner("Computing percent changes…"):
        for pid in pairs:
            row = {"Pair": pid}

            # For hybrid mode: latest price from WS if available (not strictly required for % changes,
            # since %s use candle closes, but we keep it as an extra column in the future if desired).
            latest_px = None
            if mode.startswith("WebSocket"):
                latest_px = st.session_state.ws_prices.get(pid)
                if latest_px is None:
                    # fallback to REST ticker
                    latest_px = rest_spot_price(pid)

            # Compute % change per timeframe based on candles
            per_tf = []
            for lbl in tf_selected:
                pct = pct_change_for_window_from_candles(pid, TIMEFRAME_CHOICES[lbl])
                row[f"% {lbl}"] = pct
                per_tf.append(pct)

            avg_all, max_abs_all = aggregate_all(per_tf)
            row["% ALL avg"] = avg_all
            row["% ALL max_abs"] = max_abs_all

            rows.append(row)

# -------------------- Diagnostics --------------------
with st.expander("Diagnostics"):
    diag = {
        "mode": mode,
        "ws_running": st.session_state.ws_running,
        "ws_err": st.session_state.ws_last_err,
        "products_first3": pairs[:3],
        "ws_prices_count": len(st.session_state.ws_prices),
        "ts": int(time.time()),
    }
    st.json(diag)
    if st.session_state.ws_diag:
        st.write("debug_tail:", st.session_state.ws_diag[-5:])

if st.session_state.ws_last_err:
    st.error(st.session_state.ws_last_err)

# -------------------- Render table --------------------
df = pd.DataFrame(rows)
if df.empty:
    st.info("Waiting for data or try fewer pairs/timeframes.")
else:
    ascending = not descending
    df = df.sort_values(sort_metric, ascending=ascending, na_position="last").reset_index(drop=True)

    pretty = df.copy()
    for c in [x for x in pretty.columns if x.startswith("% ")] + ["% ALL avg", "% ALL max_abs"]:
        if c in pretty:
            pretty[c] = pretty[c].map(lambda v: f"{v:.2f}%" if isinstance(v, (float, int)) else "—")

    st.subheader("All pairs ranked by movement")
    st.dataframe(pretty, use_container_width=True, height=720)

with st.expander("Notes"):
    st.markdown(
        """
- **REST only** uses Coinbase candle endpoints; **WebSocket + REST** streams live ticks (ticker channel)
  and still uses REST for multi-timeframe baselines.
- **4h & 12h** are computed from 1h candles (stepping back 4 or 12 buckets).
- If you hit rate limits, reduce **Max pairs** or the number of **Timeframes**, or increase **Refresh**.
- Start with a **tiny watchlist** when using WebSocket (e.g., 3–10 pairs) and increase slowly.
        """
    )
