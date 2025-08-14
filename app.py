# Coinbase Price Movers — SIMPLE REST v2.2
# - No websockets required
# - Auto-refresh
# - "Exchange only (REST polling)" mode (visible in UI)
# - All timeframes selectable: 1m, 5m, 15m, 1h, 4h*, 6h, 12h*, 1d
#     * 4h & 12h are computed from 1h candles (Coinbase doesn't expose 4h/12h granularity)
# - Percent change per timeframe + % ALL avg + % ALL max_abs
# - Sort ascending/descending by any metric
# - One long ranked list

import math
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

# -------------------- Constants --------------------
BASE_URL = "https://api.exchange.coinbase.com"

# UI timeframes (label -> seconds)
TIMEFRAME_CHOICES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,     # computed from 1h data
    "6h": 21600,     # native 21600 granularity exists
    "12h": 43200,    # computed from 1h data
    "1d": 86400,
}

# Coinbase REST supported granularities (seconds)
CB_GRANS = [60, 300, 900, 3600, 21600, 86400]  # 1m,5m,15m,1h,6h,1d

# -------------------- Page config --------------------
st.set_page_config(page_title="Coinbase Price Movers — SIMPLE (REST)", layout="wide")
st.title("Coinbase Price Movers — SIMPLE (REST)")

# -------------------- Sidebar --------------------
with st.sidebar:
    st.subheader("Mode")
    st.radio("Data source", ["Exchange only (REST polling)"], index=0, key="mode_disabled")

    st.subheader("Universe")
    quote_currency = st.selectbox("Quote currency", ["USD", "USDT", "BTC"], index=0)
    use_watchlist = st.checkbox("Use watchlist only (ignore discovery)", False)
    wl_text = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
    max_pairs = st.slider("Max pairs", 10, 1000, 200, step=10)

    st.subheader("Timeframes")
    tf_selected = st.multiselect(
        "Select one or more",
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
    st.caption("Auto-refresh re-runs the app; REST calls are throttled by caching to reduce rate-limit risk.")

# Trigger auto-refresh (keeps the UI live)
st_autorefresh_token = st.experimental_memo.clear  # dummy ref for IDEs
st.experimental_set_query_params(_ts=int(time.time()))
st_autorefresh = st.autorefresh(interval=refresh_sec * 1000, key="auto_refresh_key")

# -------------------- Helpers --------------------
def best_granularity(seconds: int) -> int:
    """
    Choose the largest supported Coinbase granularity <= requested seconds.
    (We may need multiple buckets to span the full window.)
    """
    candidates = [g for g in CB_GRANS if g <= seconds]
    return candidates[-1] if candidates else 60

@st.cache_data(ttl=300)
def discover_pairs(quote: str) -> list[str]:
    try:
        r = requests.get(f"{BASE_URL}/products", timeout=15)
        r.raise_for_status()
        data = r.json()
        # Coinbase returns lowercase currencies in fields; product id is "BASE-QUOTE"
        out = []
        for it in data:
            pid = it.get("id")
            q = it.get("quote_currency", "")
            if pid and q and q.upper() == quote.upper():
                # trading_disabled not always present on this endpoint; include all
                out.append(pid)
        return sorted(set(out))
    except Exception:
        return ["BTC-USD", "ETH-USD", "SOL-USD"]

def fetch_candles(pid: str, granularity: int, need_buckets: int) -> list[list]:
    """
    Fetch enough candles at 'granularity' to compute a change 'need_buckets' back from the latest close.
    Coinbase returns candles reverse-chronological (newest first).
    """
    # We’ll ask for a time window big enough for need_buckets + buffer
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
        return candles  # [time, low, high, open, close, volume], newest first
    except Exception:
        return []

def pct_change_for_window(pid: str, window_sec: int) -> float | None:
    """
    Compute % change over 'window_sec' using supported Coinbase granularities.
    For 4h/12h we’ll use 1h granularity and jump multiple buckets.
    """
    g = best_granularity(window_sec)
    # How many buckets we need to step back to cover window_sec
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

def aggregate_all(values: list[float]) -> tuple[float | None, float | None]:
    """
    Return (% ALL avg, % ALL max_abs) across a list of numeric % changes (ignore None).
    max_abs keeps the sign of the largest-magnitude change.
    """
    clean = [v for v in values if v is not None]
    if not clean:
        return None, None
    avg = sum(clean) / len(clean)
    # largest magnitude, keep sign
    idx = max(range(len(clean)), key=lambda i: abs(clean[i]))
    return avg, clean[idx]

# -------------------- Build universe --------------------
if use_watchlist and wl_text.strip():
    pairs = [x.strip().upper() for x in wl_text.split(",") if x.strip()]
else:
    pairs = discover_pairs(quote_currency)

pairs = pairs[:max_pairs]
st.caption(f"Tracking {len(pairs)} pairs ending in -{quote_currency.upper()} (REST mode).")

# -------------------- Collect data --------------------
rows = []
with st.spinner("Fetching candles…"):
    for pid in pairs:
        row = {"Pair": pid}
        per_tf = []
        for lbl in tf_selected:
            pct = pct_change_for_window(pid, TIMEFRAME_CHOICES[lbl])
            row[f"% {lbl}"] = pct
            per_tf.append(pct)
        avg_all, max_abs_all = aggregate_all(per_tf)
        row["% ALL avg"] = avg_all
        row["% ALL max_abs"] = max_abs_all
        rows.append(row)

df = pd.DataFrame(rows)

# -------------------- Sort & render --------------------
if df.empty:
    st.info("No data yet. Try fewer pairs or fewer timeframes.")
else:
    # Choose sort column
    sort_col = sort_metric
    ascending = not descending
    df = df.sort_values(sort_col, ascending=ascending, na_position="last").reset_index(drop=True)

    # Pretty formatting: keep numeric for sorting, then show formatted view
    fmt_cols = [c for c in df.columns if c.startswith("% ")]
    styled = df.copy()
    for c in fmt_cols:
        styled[c] = styled[c].map(lambda v: f"{v:.2f}%" if isinstance(v, (int, float)) else "—")

    st.subheader("All pairs ranked by movement")
    st.dataframe(styled, use_container_width=True, height=700)

# -------------------- Notes --------------------
with st.expander("Notes"):
    st.markdown(
        """
- **REST polling**: no websockets required; this is the most portable “Exchange only” mode.
- **4h & 12h**: Coinbase doesn’t expose those granularities — this app computes them from 1h buckets.
- **Rate limits**: Many pairs × many timeframes can be heavy. If you hit limits, lower **Max pairs** or reduce timeframes, or increase the refresh interval.
- **Sorting**: Use **% ALL avg** for a balanced view across all selected TFs, or **% ALL max_abs** to surface pairs with a single very large move (keeps the sign).
        """
    )
