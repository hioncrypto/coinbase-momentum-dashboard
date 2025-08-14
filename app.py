# Coinbase Movers — Hybrid (WebSocket + REST)
# v3.1 – single-file app (drop-in) with safe auto-refresh and WS diagnostics
# - Modes: REST only OR WebSocket + REST (hybrid)
# - Timeframes: 1m, 5m, 15m, 1h, 4h, 6h, 12h, 1d
# - Columns: % per timeframe + % ALL avg + % ALL max_abs
# - Sorting, watchlist, max pairs, chunked WS subscribe

from __future__ import annotations

import json
import math
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st

# -------------------- CONFIG --------------------
BASE_URL = "https://api.exchange.coinbase.com"  # classic exchange REST

# UI timeframes (label -> seconds)
TIMEFRAME_CHOICES: Dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,   # computed using 1h buckets
    "6h": 21600,   # native 6h supported by REST
    "12h": 43200,  # computed using 1h buckets
    "1d": 86400,
}

# Coinbase REST granularity options (seconds)
CB_GRANS = [60, 300, 900, 3600, 21600, 86400]  # 1m,5m,15m,1h,6h,1d

st.set_page_config(page_title="Coinbase Movers — Hybrid (WS + REST)", layout="wide")
st.title("Coinbase Movers — Hybrid (WebSocket + REST)")

# -------------------- SIDEBAR --------------------
with st.sidebar:
    st.subheader("Mode")
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0)

    st.subheader("Universe")
    quote_currency = st.selectbox("Quote currency", ["USD", "USDT", "BTC"], index=0)
    use_watchlist = st.checkbox("Use watchlist only (ignore discovery)", False)
    wl_text = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
    max_pairs = st.slider("Max pairs to include", 10, 1000, 200, step=10)

    st.subheader("Timeframes")
    tf_selected = st.multiselect(
        "Select timeframes (pick one or more)",
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

    st.subheader("Auto‑refresh")
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 15, step=5)
    # Safe auto-refresh for older Streamlit versions:
    try:
        st.autorefresh(interval=refresh_sec * 1000, key="auto_refresh_key")
    except Exception:
        st.caption("Auto‑refresh unavailable on this Streamlit version; use the ↻ Rerun button or upgrade Streamlit.")

    if mode.startswith("WebSocket"):
        st.subheader("WebSocket — Exchange feed (ticker)")
        ws_chunk = st.slider("Subscribe chunk size", 2, 50, 10)
        c1, c2 = st.columns(2)
        with c1:
            start_ws = st.button("Start WebSocket", use_container_width=True)
        with c2:
            stop_ws = st.button("Stop WebSocket", use_container_width=True)
    else:
        start_ws = stop_ws = False  # no-op in REST only

# -------------------- SESSION STATE --------------------
if "ws_thread" not in st.session_state:
    st.session_state.ws_thread = None
if "ws_running" not in st.session_state:
    st.session_state.ws_running = False
if "ws_prices" not in st.session_state:
    st.session_state.ws_prices: Dict[str, float] = {}
if "ws_last_err" not in st.session_state:
    st.session_state.ws_last_err = ""
if "ws_diag" not in st.session_state:
    st.session_state.ws_diag: List[str] = []

# -------------------- HELPERS --------------------
def best_granularity(seconds: int) -> int:
    """Pick the largest supported Coinbase granularity <= requested seconds."""
    allowed = [g for g in CB_GRANS if g <= seconds]
    return allowed[-1] if allowed else 60

@st.cache_data(ttl=600)
def discover_pairs(quote: str) -> List[str]:
    """Discover tradable product IDs ending in the selected quote currency."""
    try:
        r = requests.get(f"{BASE_URL}/products", timeout=15)
        r.raise_for_status()
        out = []
        for it in r.json():
            pid = it.get("id")
            q = it.get("quote_currency", "")
            if pid and q and q.upper() == quote.upper():
                out.append(pid)
        return sorted(set(out))
    except Exception:
        return ["BTC-USD", "ETH-USD", "SOL-USD"]

def fetch_candles(pid: str, granularity: int, need_buckets: int) -> List[List[float]]:
    """
    Fetch enough candles at 'granularity' to compute a change 'need_buckets'
    back from latest close. Coinbase returns newest-first arrays.
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
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []

def pct_change_from_candles(pid: str, window_sec: int) -> Optional[float]:
    """Compute % change over 'window_sec' using candles at best matching granularity."""
    g = best_granularity(window_sec)
    steps = max(1, math.ceil(window_sec / g))
    candles = fetch_candles(pid, g, steps)
    if len(candles) < steps + 1:
        return None
    latest_close = candles[0][4]
    ref_close = candles[steps][4]
    try:
        return (latest_close - ref_close) / ref_close * 100.0
    except Exception:
        return None

def aggregate_all(values: List[Optional[float]]) -> Tuple[Optional[float], Optional[float]]:
    """Return (average of non-null values, element with max absolute value)."""
    clean = [v for v in values if isinstance(v, (float, int))]
    if not clean:
        return None, None
    avg = sum(clean) / len(clean)
    max_abs = max(clean, key=lambda x: abs(x))
    return avg, max_abs

@st.cache_data(ttl=15)
def rest_spot_price(pid: str) -> Optional[float]:
    """Get last traded price via REST ticker; used for hybrid display/diagnostics."""
    try:
        r = requests.get(f"{BASE_URL}/products/{pid}/ticker", timeout=10)
        if r.status_code != 200:
            return None
        return float(r.json().get("price"))
    except Exception:
        return None

# -------------------- WEBSOCKET WORKER --------------------
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
        m = f"{datetime.utcnow():%H:%M:%S} error: {err}"
        st.session_state.ws_last_err = m
        st.session_state.ws_diag.append(m)

    def on_close(ws, *args):
        st.session_state.ws_running = False
        st.session_state.ws_diag.append(f"{datetime.utcnow():%H:%M:%S} closed ws")

    def on_open(ws):
        st.session_state.ws_diag.append(f"{datetime.utcnow():%H:%M:%S} ws open")
        chunks = [product_ids[i:i + chunk_size] for i in range(0, len(product_ids), chunk_size)]
        for ch in chunks:
            sub = {"type": "subscribe", "channels": [{"name": "ticker", "product_ids": ch}]}
            ws.send(json.dumps(sub))
            time.sleep(0.25)

    ws = WebSocketApp(url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
    st.session_state.ws_running = True
    try:
        ws.run_forever(ping_interval=25, ping_timeout=10)
    except Exception as e:
        st.session_state.ws_last_err = f"Exception: {e}"
    st.session_state.ws_running = False

def control_ws(product_ids: List[str], chunk_size: int, want_start: bool, want_stop: bool):
    """Start/stop websocket based on sidebar buttons."""
    if want_start and not st.session_state.ws_running:
        st.session_state.ws_prices = {}  # clean slate
        t = threading.Thread(target=ws_worker, args=(product_ids, chunk_size), daemon=True)
        t.start()
        st.session_state.ws_thread = t
    if want_stop and st.session_state.ws_running:
        # No direct close from here; let it time out. Provide feedback.
        st.session_state.ws_last_err = "Stop requested. Refresh page to fully disconnect."
        st.session_state.ws_running = False

# -------------------- UNIVERSE --------------------
if use_watchlist and wl_text.strip():
    pairs = [x.strip().upper() for x in wl_text.split(",") if x.strip()]
else:
    pairs = discover_pairs(quote_currency)

pairs = pairs[:max_pairs]
st.caption(f"Tracking {len(pairs)} pairs ending in -{quote_currency.upper()}.")

if mode.startswith("WebSocket"):
    control_ws(pairs, ws_chunk, start_ws, stop_ws)

# -------------------- DATA GATHER --------------------
rows: List[Dict] = []
if not tf_selected:
    st.warning("Please select at least one timeframe.")
else:
    with st.spinner("Computing percent changes…"):
        for pid in pairs:
            row: Dict[str, Optional[float]] = {"Pair": pid}

            # (Optional) expose latest price for hybrid display/diag (not needed for % calc)
            if mode.startswith("WebSocket"):
                latest_px = st.session_state.ws_prices.get(pid)
                if latest_px is None:
                    latest_px = rest_spot_price(pid)
                row["Last price"] = latest_px

            per_tf: List[Optional[float]] = []
            for lbl in tf_selected:
                pct = pct_change_from_candles(pid, TIMEFRAME_CHOICES[lbl])
                row[f"% {lbl}"] = pct
                per_tf.append(pct)

            avg_all, max_abs_all = aggregate_all(per_tf)
            row["% ALL avg"] = avg_all
            row["% ALL max_abs"] = max_abs_all

            rows.append(row)

# -------------------- DIAGNOSTICS --------------------
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

# -------------------- RENDER --------------------
df = pd.DataFrame(rows)
if df.empty:
    st.info("Waiting for data or try fewer pairs/timeframes.")
else:
    ascending = not descending
    df_sorted = df.sort_values(sort_metric, ascending=ascending, na_position="last").reset_index(drop=True)

    # pretty print % columns
    pretty = df_sorted.copy()
    for c in [col for col in pretty.columns if col.startswith("% ")] + ["% ALL avg", "% ALL max_abs"]:
        if c in pretty:
            pretty[c] = pretty[c].map(lambda v: f"{v:.2f}%" if isinstance(v, (float, int)) else "—")

    st.subheader("All pairs ranked by movement")
    st.dataframe(pretty, use_container_width=True, height=700)

with st.expander("Notes"):
    st.markdown(
        """
- **REST only** mode uses Coinbase candle endpoints.  
- **WebSocket + REST (hybrid)** streams live ticks from the **exchange feed (ticker)** and still uses REST
  to compute multi‑timeframe baselines.  
- **4h** and **12h** are computed from **1h** candles; **6h** and **1d** are native.  
- If you hit rate limits, reduce **Max pairs** or the number of **Timeframes**, or increase **Refresh**.  
- For WebSocket mode, begin with a **small watchlist** (e.g., 3–10 pairs) and raise gradually.
        """
    )
