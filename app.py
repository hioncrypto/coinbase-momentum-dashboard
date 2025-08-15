# app.py — Coinbase Movers (REST-first, Multi-timeframe)
# Dependencies for requirements.txt: streamlit pandas numpy requests

import time
import math
import smtplib
import hashlib
import textwrap
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone

import requests
import numpy as np
import pandas as pd
import streamlit as st

# ------------------------------
# Config & helpers
# ------------------------------
st.set_page_config(
    page_title="Coinbase Movers — Multi‑Timeframe",
    layout="wide",
)

COINBASE_PRODUCTS_URL = "https://api.exchange.coinbase.com/products"
COINBASE_CANDLES_URL = "https://api.exchange.coinbase.com/products/{pid}/candles"

# Supported granularities by Coinbase: 60, 300, 900, 3600, 21600, 86400
# We'll derive 4h/12h from 1h candles when needed.
TF_TO_SECONDS = {
    "1m":   60,
    "5m":   300,
    "15m":  900,
    "1h":   3600,
    "4h":   3600 * 4,   # derived from 1h
    "6h":   21600,
    "12h":  3600 * 12,  # derived from 1h
    "1d":   86400,
}

SUPPORTED_SERVER_GRAN = {60, 300, 900, 3600, 21600, 86400}

HEADERS = {
    "User-Agent": "streamlit-coinbase-movers",
    "Accept": "application/json",
}

@st.cache_data(ttl=300)
def fetch_products() -> pd.DataFrame:
    r = requests.get(COINBASE_PRODUCTS_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    # Normalize to DataFrame
    df = pd.DataFrame(data)
    # Ensure typical fields exist
    for c in ["id", "display_name", "base_currency", "quote_currency", "status"]:
        if c not in df.columns:
            df[c] = np.nan
    return df

@st.cache_data(ttl=120)
def fetch_candles(pid: str, granularity: int, start: datetime | None = None, end: datetime | None = None) -> pd.DataFrame:
    """Fetch candles for product id at granularity. Returns oldest..newest (ascending) DataFrame."""
    params = {"granularity": granularity}
    # If you pass start/end, Coinbase expects UNIX times in seconds
    if start and end:
        params["start"] = int(start.replace(tzinfo=timezone.utc).timestamp())
        params["end"] = int(end.replace(tzinfo=timezone.utc).timestamp())

    url = COINBASE_CANDLES_URL.format(pid=pid)
    r = requests.get(url, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    arr = r.json()

    # API returns [ time, low, high, open, close, volume ] newest-first
    cols = ["time", "low", "high", "open", "close", "volume"]
    df = pd.DataFrame(arr, columns=cols)
    if df.empty:
        return df
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.sort_values("time").reset_index(drop=True)
    return df

def derive_from_1h(df_1h: pd.DataFrame, hours: int) -> pd.DataFrame:
    """Aggregate 1h candles to N-hour OHLCV. E.g., 4h/12h."""
    if df_1h.empty:
        return df_1h
    # Group by blocks of N hours
    # Align on last timestamp block boundary
    g = df_1h.copy()
    # Create block id by integer division of unix hour
    block = (g["time"].view("int64") // 10**9) // 3600 // hours
    g["block"] = block
    agg = (
        g.groupby("block", as_index=False)
         .agg(
            time=("time", "last"),
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
    )
    return agg.drop(columns=["block"], errors="ignore")

def pct_change_from_series(close_series: pd.Series, periods_back: int) -> float | None:
    """Return percentage change from last close to N periods back (close)."""
    if len(close_series) <= periods_back:
        return None
    curr = close_series.iloc[-1]
    prev = close_series.iloc[-1 - periods_back]
    if prev == 0 or pd.isna(prev) or pd.isna(curr):
        return None
    return (curr - prev) / prev * 100.0

def compute_RSI(series: pd.Series, length: int = 14) -> float | None:
    if len(series) < length + 1:
        return None
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up).rolling(length).mean()
    roll_down = pd.Series(down).rolling(length).mean()
    rs = roll_up.iloc[-1] / (roll_down.iloc[-1] + 1e-12)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return float(rsi)

def compute_MACD(series: pd.Series, fast=12, slow=26, signal=9) -> float | None:
    if len(series) < slow + signal + 1:
        return None
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return float(hist.iloc[-1])

def safe_format_table(view: pd.DataFrame) -> pd.DataFrame:
    """Elementwise format for percent & numeric — safe for multi-column slices."""
    df = view.copy()
    pct_cols = [c for c in df.columns if c.startswith("%_")]
    # Other numeric columns to format lightly (exclude price for better precision)
    num_cols = [c for c in df.columns if c not in pct_cols and pd.api.types.is_numeric_dtype(df[c])]

    _fmt_pct = lambda v: f"{v:.2f}%" if pd.notna(v) else "–"
    _fmt_num = lambda v: f"{v:.4f}" if pd.notna(v) else "–"

    if pct_cols:
        df[pct_cols] = df[pct_cols].applymap(_fmt_pct)
    # Lightly format some columns; price we keep 6 decimals for small coins
    if "last_price" in df.columns:
        df["last_price"] = df["last_price"].apply(lambda v: f"{v:.6f}" if pd.notna(v) else "–")
    if num_cols:
        tmp = [c for c in num_cols if c not in ["last_price"]]
        if tmp:
            df[tmp] = df[tmp].applymap(_fmt_num)
    return df

def send_email_alert(smtp_host, smtp_port, smtp_user, smtp_pass, to_addr, subject, body):
    msg = EmailMessage()
    msg["From"] = smtp_user or to_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP_SSL(smtp_host, int(smtp_port)) as s:
        if smtp_user and smtp_pass:
            s.login(smtp_user, smtp_pass)
        s.send_message(msg)

# ------------------------------
# Sidebar controls
# ------------------------------
st.sidebar.header("Mode")
mode = st.sidebar.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0)
st.sidebar.caption("WebSocket is optional — this app uses REST for reliability. Hybrid toggle is for future use.")

st.sidebar.header("Universe")
quote = st.sidebar.selectbox("Quote currency", ["USD", "USDC", "USDT"], index=0)
use_watchlist_only = st.sidebar.checkbox("Use watchlist only (ignore discovery)", value=True)
watchlist = st.sidebar.text_area("Watchlist (comma‑separated)", value="BTC-USD, ETH-USD, SOL-USD")
max_pairs = st.sidebar.slider("Max pairs to include", 5, 500, 200, step=5)

st.sidebar.header("Timeframes (for % change)")
tf_choices = ["1m", "5m", "15m", "1h", "4h", "6h", "12h", "1d"]
selected_tfs = st.sidebar.multiselect("Select timeframes (pick ≥1)", tf_choices, default=["1m", "5m", "15m", "1h"])

st.sidebar.header("Ranking / sort")
sort_tf = st.sidebar.selectbox("Rank by timeframe", options=selected_tfs if selected_tfs else tf_choices, index=0)
sort_desc = st.sidebar.checkbox("Sort descending (largest first)", value=True)

st.sidebar.header("WebSocket")
sub_chunk = st.sidebar.slider("Subscribe chunk size", 2, 200, 10)
st.sidebar.caption("For REST mode this is unused, but kept for consistency.")

st.sidebar.header("Display")
tz_opt = st.sidebar.selectbox("Time zone", ["UTC"], index=0)
top_rows = st.sidebar.slider("Show top rows", 10, 5000, 1000, step=10)
filter_text = st.sidebar.text_input("Filter (e.g., 'BTC' or '-USD')", "")

st.sidebar.header("Spikes & Alerts")
spike_pct = st.sidebar.slider("Spike threshold (abs %)", 0.5, 20.0, 3.0, step=0.5)
vol_spike_ratio = st.sidebar.slider("Volume spike ratio (vs avg)", 1.0, 10.0, 2.0, step=0.1)
font_px = st.sidebar.slider("Table font size (px)", 10, 24, 14)
st.sidebar.divider()
enable_email = st.sidebar.checkbox("Enable email alerts", value=False)
to_email = st.sidebar.text_input("Alert to (email)", "", placeholder="you@example.com", disabled=not enable_email)
smtp_host = st.sidebar.text_input("SMTP host", "smtp.gmail.com", disabled=not enable_email)
smtp_port = st.sidebar.text_input("SMTP port", "465", disabled=not enable_email)
smtp_user = st.sidebar.text_input("SMTP user", "", disabled=not enable_email)
smtp_pass = st.sidebar.text_input("SMTP password (app password)", "", type="password", disabled=not enable_email)

col_btn1, col_btn2 = st.sidebar.columns(2)
with col_btn1:
    test_email = st.button("Test email", disabled=not enable_email)
with col_btn2:
    auto_refresh_sec = st.number_input("Auto refresh (sec)", min_value=0, max_value=3600, value=0, step=5)

# ------------------------------
# Title & diagnostics
# ------------------------------
st.title("Coinbase Movers — Multi‑Timeframe")
st.caption("REST‑first scanning of % change across timeframes + RSI / MACD / Volume spike. Top spikes highlighted. Exchange feed only (no auth).")

diag = {
    "WS_OK": False,
    "thread_alive": False,
    "connect_attempt": 0,
    "active_ws_url": "",
    "last_subscribe": "",
    "queue_size": 0,
    "state_connected": False,
    "state_last_msg_ts": 0,
    "state_err": "",
    "products_first3": [],
    "history_seconds": int(sum(TF_TO_SECONDS[tf] for tf in selected_tfs)) if selected_tfs else 0,
    "debug_tail": [],
}

with st.expander("Diagnostics", expanded=False):
    st.json(diag)

if auto_refresh_sec > 0:
    st.experimental_singleton.clear()  # no-op on new Streamlit versions, safe
    st.experimental_rerun  # to hint IDE; real refresh below
    st.experimental_set_query_params(_=int(time.time()))
    st.autorefresh(interval=auto_refresh_sec * 1000, key="auto_refresh_key")

# ------------------------------
# Load universe
# ------------------------------
df_products = fetch_products()

if use_watchlist_only:
    wl = [w.strip() for w in watchlist.split(",") if w.strip()]
    products = [p for p in wl if p.endswith(f"-{quote}")]
else:
    products = (
        df_products.loc[df_products["quote_currency"] == quote, "id"]
                   .dropna().tolist()
    )

# De-dup + limit
seen = set()
uniq = []
for p in products:
    if p not in seen:
        uniq.append(p)
        seen.add(p)
products = uniq[:max_pairs]

# Useful preview in diagnostics
diag_preview = products[:3]
with st.expander("Universe preview", expanded=False):
    st.write(f"{len(products)} products (first 10):", products[:10])

if test_email and enable_email and to_email:
    try:
        send_email_alert(
            smtp_host, smtp_port, smtp_user, smtp_pass, to_email,
            "Coinbase Movers — Test alert",
            "This is a test email from your Streamlit dashboard.",
        )
        st.success("Test email sent.")
    except Exception as e:
        st.error(f"Email failed: {e}")

# ------------------------------
# Scan function (REST)
# ------------------------------
@st.cache_data(ttl=30, show_spinner=False)
def scan_once(product_ids: list[str], tfs: list[str]) -> pd.DataFrame:
    rows = []
    now = datetime.now(timezone.utc)
    need_1h_for = []
    for tf in tfs:
        sec = TF_TO_SECONDS[tf]
        if sec not in SUPPORTED_SERVER_GRAN and tf in {"4h", "12h"}:
            need_1h_for.append(tf)

    for pid in product_ids:
        tf_to_close = {}
        tf_to_vol = {}

        # Fetch individual granularities we can request directly
        fetched = {}
        for tf in tfs:
            sec = TF_TO_SECONDS[tf]
            if sec in SUPPORTED_SERVER_GRAN:
                # Fetch enough candles to compute a change (we need last 2)
                gran = sec
                # Pull ~200 candles for robust RSI/MACD on fastest tf hit among selected
                limit_look = 200
                start = now - timedelta(seconds=limit_look * gran + gran * 5)
                df = fetch_candles(pid, gran, start=start, end=now)
                fetched[tf] = df

        # If we need 1h base for 4h/12h, fetch 1h once and derive
        if need_1h_for:
            start_1h = now - timedelta(hours=200 + 5)
            df1h = fetch_candles(pid, 3600, start=start_1h, end=now)
            for tf in need_1h_for:
                h = 4 if tf == "4h" else 12
                agg = derive_from_1h(df1h, hours=h)
                fetched[tf] = agg

        # Compute last price (prefer 1m, else any tf fetched)
        last_price = None
        for pref in ["1m", "5m", "15m", "1h", "4h", "6h", "12h", "1d"]:
            if pref in fetched and not fetched[pref].empty:
                last_price = float(fetched[pref]["close"].iloc[-1])
                break

        # If nothing fetched, skip
        if last_price is None:
            continue

        # Percent changes
        pct_cols = {}
        for tf in tfs:
            df = fetched.get(tf, pd.DataFrame())
            if df.empty:
                pct_cols[f"%_{tf}"] = None
                tf_to_close[tf] = None
                tf_to_vol[tf] = None
                continue
            closes = df["close"]
            vols = df["volume"]
            # One period back at this granularity means 1 candle
            pct = pct_change_from_series(closes, 1)
            pct_cols[f"%_{tf}"] = pct
            tf_to_close[tf] = float(closes.iloc[-1])
            tf_to_vol[tf] = float(vols.iloc[-1])

        # RSI & MACD on the fastest selected tf that we have
        rsi_val = None
        macd_hist = None
        for tf in ["1m", "5m", "15m", "1h"]:
            if tf in tfs and not fetched.get(tf, pd.DataFrame()).empty:
                closes = fetched[tf]["close"]
                rsi_val = compute_RSI(closes, length=14)
                macd_hist = compute_MACD(closes, 12, 26, 9)
                break

        # Volume spike — compare last vol to rolling avg on the fastest tf
        vol_ratio = None
        for tf in ["1m", "5m", "15m", "1h"]:
            df = fetched.get(tf, pd.DataFrame())
            if not df.empty and len(df) >= 30:
                last_vol = df["volume"].iloc[-1]
                avg_vol = df["volume"].rolling(30).mean().iloc[-1]
                if avg_vol and not pd.isna(avg_vol) and avg_vol > 0:
                    vol_ratio = float(last_vol / avg_vol)
                break

        rows.append(
            {
                "pair": pid,
                "last_price": last_price,
                "RSI14": rsi_val,
                "MACD_hist": macd_hist,
                "Vol_ratio": vol_ratio,
                **pct_cols,
            }
        )

    df = pd.DataFrame(rows)
    # Sort columns nicely
    pct_order = [f"%_{tf}" for tf in tfs]
    other_cols = ["pair", "last_price", "RSI14", "MACD_hist", "Vol_ratio"]
    final_cols = other_cols + pct_order
    df = df.reindex(columns=[c for c in final_cols if c in df.columns])
    return df

# ------------------------------
# Run scan
# ------------------------------
if not selected_tfs:
    st.warning("Pick at least one timeframe.")
    st.stop()

run_btn = st.button("Run scan / refresh", type="primary")
if run_btn:
    st.session_state["_force_run"] = True

if st.session_state.get("_force_run") or auto_refresh_sec > 0:
    with st.spinner("Scanning…"):
        base_df = scan_once(products, selected_tfs)
else:
    base_df = pd.DataFrame()

if base_df.empty:
    st.info("Waiting for data… Try a small watchlist and 1–2 timeframes.")
    st.stop()

# Optional filter
if filter_text.strip():
    mask = base_df["pair"].str.contains(filter_text.strip(), case=False, na=False)
    base_df = base_df.loc[mask].copy()

# Build spike mask (any selected timeframe hitting threshold, or vol spike)
pct_cols = [c for c in base_df.columns if c.startswith("%_")]
def is_spike_row(row) -> bool:
    spike = False
    for c in pct_cols:
        v = row.get(c, None)
        if v is not None and not pd.isna(v) and abs(v) >= spike_pct:
            spike = True
            break
    if not spike and row.get("Vol_ratio") is not None and not pd.isna(row["Vol_ratio"]):
        if row["Vol_ratio"] >= vol_spike_ratio:
            spike = True
    return spike

base_df["_is_spike"] = base_df.apply(is_spike_row, axis=1)

# Top strip (up to 6)
top_view = base_df.sort_values(by=f"%_{sort_tf}", ascending=not sort_desc, na_position="last")
top_n = top_view.loc[top_view["_is_spike"]].head(6)

st.subheader("Top Spikes")
if top_n.empty:
    st.caption("No rows exceeded the spike thresholds yet.")
else:
    mcols = st.columns(min(6, len(top_n)))
    for i, (_, r) in enumerate(top_n.iterrows()):
        txt = f"{r['pair']}"
        sub = f"Last: {r['last_price']:.6f}"
        sub2 = ", ".join(
            f"{c[2:]}: {r[c]:+.2f}%"
            for c in pct_cols if isinstance(r[c], (int, float, np.floating))
        )
        mcols[i].metric(txt, sub, sub2)

# Sort table
sort_col = f"%_{sort_tf}"
if sort_col not in base_df.columns:
    sort_col = pct_cols[0] if pct_cols else "last_price"

table_df = base_df.sort_values(by=sort_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
table_df = table_df.head(top_rows)

# Email alerts (send for new spikes only)
if enable_email and to_email:
    spikes_only = table_df.loc[table_df["_is_spike"]].copy()
    if not spikes_only.empty:
        # Build a stable hash of pair+timeframe values to dedupe sends
        payload = spikes_only[["pair"] + pct_cols].fillna(0).to_string(index=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        last_digest = st.session_state.get("last_alert_hash")
        if digest != last_digest:
            try:
                body = "Top spike rows:\n\n" + spikes_only.to_string(index=False)
                send_email_alert(
                    smtp_host, smtp_port, smtp_user, smtp_pass, to_email,
                    "Coinbase Movers — Spike Alert", body
                )
                st.success("Alert email sent.")
                st.session_state["last_alert_hash"] = digest
            except Exception as e:
                st.error(f"Email failed: {e}")

# Format table for display (safe elementwise)
display_df = table_df.drop(columns=["_is_spike"]).copy()
fmt_df = safe_format_table(display_df)

# Row highlight style
def highlight_spikes(row):
    if "_is_spike" in table_df.columns:
        idx = row.name
        if bool(table_df.loc[idx, "_is_spike"]):
            return ["background-color: rgba(0, 200, 100, 0.15)"] * len(row)
    return [""] * len(row)

st.subheader("All pairs ranked by movement")
st.caption("Green rows meet the spike thresholds. Use the sidebar to adjust thresholds, sorting, and columns.")

# Apply style & show
styled = fmt_df.style.apply(highlight_spikes, axis=1)
st.write(
    f"<style>div[data-testid='stDataFrame'] table{{font-size:{font_px}px;}}</style>",
    unsafe_allow_html=True,
)
st.dataframe(styled, use_container_width=True)
