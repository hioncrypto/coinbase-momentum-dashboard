
# app.py — Coinbase Movers (REST-first + optional WebSocket), multi-timeframe % change,
# RSI / MACD / Volume Z-score, top spikes, alerts, and row highlighting.
import os
import time
import json
import math
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import requests
import streamlit as st
from pytz import timezone as tz

# ---------- Optional WebSocket import (safe) ----------
HAS_WS = False
try:
    import websocket  # provided by 'websocket-client'
    HAS_WS = True
except Exception:
    HAS_WS = False

# -------------------------- UI / Page setup --------------------------
st.set_page_config(page_title="Coinbase Movers — Multi‑Timeframe", layout="wide")
st.markdown(
    """
    <style>
      /* Allow adjustable font size via a CSS var we set below */
      :root { --table-font-size: 14px; }
      .stDataFrame, .stTable, .dataframe { font-size: var(--table-font-size) !important; }
      .top-spikes .stTable { font-size: calc(var(--table-font-size) + 2px) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------------- Constants --------------------------
CBX = "https://api.exchange.coinbase.com"  # Coinbase Exchange (public)
DEFAULT_HEADERS = {"User-Agent": "movers/1.0 (streamlit)"}

SUPPORTED_FRAMES = {
    # name : (seconds, built_in_granularity, needs_aggregation)
    "1m":   (60,    60,    False),
    "5m":   (300,   300,   False),
    "15m":  (900,   900,   False),
    "1h":   (3600,  3600,  False),
    "4h":   (14400, 3600,  True),   # aggregate 1h → 4h
    "6h":   (21600, 21600, False),
    "12h":  (43200, 3600,  True),   # aggregate 1h → 12h
    "1d":   (86400, 86400, False),
}

# how many candles we fetch for indicators (EMA/RSI/MACD need some history)
FRAME_FETCH_BARS = 210

# ------------------------------------------------ Utility ----------
def safe_get(url: str, params: Optional[dict] = None, timeout: int = 15) -> Optional[requests.Response]:
    try:
        r = requests.get(url, params=params or {}, headers=DEFAULT_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r
        return None
    except Exception:
        return None


def get_products(quote_ccy: str = "USD", use_watchlist_only: bool = False, watchlist: Optional[List[str]] = None) -> List[str]:
    """Return list of product_ids (like BTC-USD) that end with selected quote currency."""
    resp = safe_get(f"{CBX}/products")
    if not resp:
        return watchlist or []
    prods = resp.json()
    all_pairs = []
    for p in prods:
        pid = p.get("id")
        if pid and pid.endswith(f"-{quote_ccy}"):
            all_pairs.append(pid)
    if use_watchlist_only:
        watchlist = watchlist or []
        wl = [w.strip().upper() for w in watchlist if w.strip()]
        return [p for p in all_pairs if p in wl]
    return all_pairs


def get_candles(product_id: str, frame: str, bars: int = FRAME_FETCH_BARS) -> Optional[pd.DataFrame]:
    """Fetch candles for a product and timeframe; aggregate if needed."""
    if frame not in SUPPORTED_FRAMES:
        return None
    seconds, base_gran, needs_agg = SUPPORTED_FRAMES[frame]

    # If aggregation needed (4h or 12h), fetch at 1h and resample
    gran = base_gran
    fetch_gran = gran
    if needs_agg:
        fetch_gran = 3600  # fetch hourly; we'll resample to 4h/12h

    # coinbase exchange supports start/end params, but easiest is to fetch sufficient recent bars
    # We'll just call once; API returns recent candles (latest first).
    url = f"{CBX}/products/{product_id}/candles"
    r = safe_get(url, params={"granularity": fetch_gran})
    if not r:
        return None

    data = r.json()
    # data rows: [time, low, high, open, close, volume] latest-first
    if not isinstance(data, list) or len(data) == 0:
        return None
    df = pd.DataFrame(data, columns=["ts", "low", "high", "open", "close", "volume"])
    df["dt"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    df = df.sort_values("dt").reset_index(drop=True)
    if needs_agg:
        # resample to desired seconds (4h or 12h)
        df = df.set_index("dt")
        rule = f"{seconds}s"
        agg = {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "ts": "last",
        }
        df = df.resample(rule, label="right", closed="right").agg(agg).dropna().reset_index()
    # keep only last N bars for performance
    if len(df) > bars:
        df = df.iloc[-bars:].reset_index(drop=True)
    return df


# ---------------------- Indicators ----------------------
def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up).ewm(alpha=1/period, adjust=False).mean()
    roll_down = pd.Series(down).ewm(alpha=1/period, adjust=False).mean()
    rs = roll_up / (roll_down + 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def vol_zscore(volume: pd.Series, window: int = 50) -> pd.Series:
    m = volume.rolling(window).mean()
    s = volume.rolling(window).std(ddof=0)
    z = (volume - m) / (s + 1e-9)
    return z

# ---------------------- Alerts (email via SMTP) ----------------------
def try_send_email(to_addr: str, subject: str, body: str, host: str, port: int, user: str, pwd: str) -> Tuple[bool, str]:
    """Minimal SMTP send (optional)."""
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to_addr
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.starttls()
            s.login(user, pwd)
            s.sendmail(user, [to_addr], msg.as_string())
        return True, "sent"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

# ---------------------- Sidebar ----------------------
st.sidebar.header("Mode")
data_src = st.sidebar.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"])
st.sidebar.header("Universe")
quote = st.sidebar.selectbox("Quote currency", ["USD", "USDC"], index=0)
use_watch = st.sidebar.checkbox("Use watchlist only (ignore discovery)", value=False)
watch_raw = st.sidebar.text_area("Watchlist (comma-separated)", value="BTC-USD, ETH-USD, SOL-USD")
watchlist = [w.strip().upper() for w in watch_raw.split(",") if w.strip()]

max_pairs = st.sidebar.slider("Max pairs to include", 10, 1000, 200, step=10)

st.sidebar.header("Timeframes (for % change)")
# pick at least one
chosen_frames = st.sidebar.multiselect(
    "Select timeframes (pick ≥1)",
    list(SUPPORTED_FRAMES.keys()),
    default=["1m", "5m", "15m", "1h", "4h", "6h", "12h", "1d"]
)
if not chosen_frames:
    st.sidebar.warning("Select at least one timeframe.")
    st.stop()

st.sidebar.header("Ranking / sort")
rank_by = st.sidebar.selectbox("Rank by", options=["% 1m", "% 5m", "% 15m", "% 1h", "% 4h", "% 6h", "% 12h", "% 1d", "% ALL max_abs", "% ALL avg"], index=0)
sort_desc = st.sidebar.checkbox("Sort descending (largest first)", value=True)

st.sidebar.header("WebSocket")
chunk = st.sidebar.slider("Subscribe chunk size", 2, 200, 10)
safe_cfg = st.sidebar.checkbox("Safe tiny config (lower load)", value=False)
restart_btn = st.sidebar.button("🔁 Restart stream")

st.sidebar.header("Display")
tz_name = st.sidebar.selectbox("Time zone", ["UTC", "US/Eastern", "US/Pacific", "Europe/London", "Asia/Tokyo"], index=0)
top_n_rows = st.sidebar.slider("Show top rows", 10, 5000, 1000, step=10)
filter_text = st.sidebar.text_input("Filter (e.g., 'BTC' or '-USD')", value="")
font_size = st.sidebar.slider("Table font size (px)", 10, 22, 14)

st.sidebar.header("Spikes & Alerts")
spike_thresh = st.sidebar.slider("Highlight rows with max |% change| ≥", 0.0, 30.0, 5.0, step=0.5)
show_top_spikes = st.sidebar.checkbox("Show Top Spike List", value=True)
top_spike_size = st.sidebar.slider("Top Spike List size", 3, 50, 10)

notify_method = st.sidebar.selectbox("Notification method", ["None", "Email (SMTP)"], index=0)
email_to = email_host = email_user = email_pwd = ""
email_port = 587
if notify_method == "Email (SMTP)":
    st.sidebar.caption("Tip: put credentials in st.secrets for safety.")
    email_to = st.sidebar.text_input("To address", value=st.secrets.get("EMAIL_TO", ""))
    email_host = st.sidebar.text_input("SMTP host", value=st.secrets.get("SMTP_HOST", ""))
    email_port = st.sidebar.number_input("SMTP port", min_value=1, max_value=65535, value=int(st.secrets.get("SMTP_PORT", 587)))
    email_user = st.sidebar.text_input("SMTP user", value=st.secrets.get("SMTP_USER", ""))
    email_pwd = st.sidebar.text_input("SMTP password", value=st.secrets.get("SMTP_PASSWORD", ""), type="password")
    if st.sidebar.button("Send test email"):
        ok, info = try_send_email(email_to, "Coinbase Movers test", "Hello from Streamlit!", email_host, int(email_port), email_user, email_pwd)
        st.sidebar.success(f"Email: {info}") if ok else st.sidebar.error(f"Email failed: {info}")

# set table font via CSS var
st.markdown(f"<style>:root {{ --table-font-size: {font_size}px; }}</style>", unsafe_allow_html=True)

# ---------------------- Diagnostics box ----------------------
diag = {
    "WS_OK": False,
    "thread_alive": False,
    "connect_attempt": 0,
    "active_ws_url": "",
    "last_subscribe": "",
    "queue_size": 0,
    "state.connected": False,
    "state.last_msg_ts": 0,
    "state.err": "",
    "products_first3": [],
}
dbg_tail: List[str] = []

def dbg(msg: str):
    if len(dbg_tail) > 200:
        dbg_tail.pop(0)
    dbg_tail.append(f"{datetime.utcnow().strftime('%H:%M:%S')} {msg}")

# ---------------------- WebSocket (optional) ----------------------
class WSState:
    def __init__(self):
        self.connected = False
        self.last_ts = 0
        self.err = ""
        self.thread: Optional[threading.Thread] = None
        self.stop_flag = threading.Event()

ws_state = WSState()

def ws_worker(products: List[str], channel: str = "ticker", endpoint_mode: str = "auto"):
    """Minimal streaming of tickers — diagnostics only; REST remains primary for table."""
    if not HAS_WS:
        diag["state.err"] = "websocket-client not installed. Add 'websocket-client' to requirements.txt"
        dbg("websocket-client not installed.")
        return

    # Exchange-only feed (public)
    url = "wss://ws-feed.exchange.coinbase.com"
    diag["active_ws_url"] = url
    dbg(f"connect -> {url}")

    try:
        ws = websocket.WebSocket()
        ws.settimeout(10)
        ws.connect(url)
        ws_state.connected = True
        diag["state.connected"] = True
        dbg("ws connected")

        # subscribe in small chunks
        subs = []
        chunked = [products[i:i+chunk] for i in range(0, len(products), chunk)]
        for grp in chunked:
            sub = {"type": "subscribe", "channels": [{"name": channel, "product_ids": grp}]}
            ws.send(json.dumps(sub))
            subs.append(grp)
            diag["last_subscribe"] = f"{len(grp)} ids"
            time.sleep(0.15)

        while not ws_state.stop_flag.is_set():
            try:
                msg = ws.recv()
                if not msg:
                    continue
                diag["state.last_msg_ts"] = int(time.time())
            except Exception:
                # we keep diagnostics only; REST does the heavy lifting
                time.sleep(0.2)
                continue
    except Exception as e:
        ws_state.err = f"{type(e).__name__}: {e}"
        diag["state.err"] = ws_state.err
        ws_state.connected = False
        diag["state.connected"] = False
        dbg(f"ws error: {ws_state.err}")
    finally:
        try:
            ws.close()
        except Exception:
            pass

# --------------- Data assembly (REST) ----------------
def percent_change(series: pd.Series, lookback_bars: int = 1) -> float:
    if len(series) <= lookback_bars or series.iloc[-lookback_bars] == 0:
        return np.nan
    return (series.iloc[-1] / series.iloc[-lookback_bars] - 1.0) * 100.0

def compute_row(product_id: str, frames: List[str]) -> Optional[Dict]:
    """Fetch & compute metrics for one product."""
    row: Dict[str, float] = {"Pair": product_id}
    base_for_ind = frames[0]  # use the first chosen timeframe for indicators
    dfind = get_candles(product_id, base_for_ind)
    if dfind is None or dfind.empty or len(dfind) < 35:
        return None

    # indicators from the base frame
    close = dfind["close"].astype(float)
    volume = dfind["volume"].astype(float)
    rsi_series = rsi(close, 14)
    macd_line, macd_signal, macd_hist = macd(close, 12, 26, 9)
    volz = vol_zscore(volume, 50)

    row["Last price"] = float(close.iloc[-1])
    row["RSI"] = float(rsi_series.iloc[-1])
    row["MACD"] = float(macd_line.iloc[-1])
    row["MACD_Signal"] = float(macd_signal.iloc[-1])
    row["MACD_Hist"] = float(macd_hist.iloc[-1])
    row["VolZ"] = float(volz.iloc[-1])

    # Percent change columns (one-bar change in each timeframe)
    all_pc = []
    for fr in frames:
        df_fr = dfind if fr == base_for_ind else get_candles(product_id, fr)
        if df_fr is None or len(df_fr) < 2:
            pc = np.nan
        else:
            pc = percent_change(df_fr["close"].astype(float), 1)
        col = f"% {fr}"
        row[col] = float(pc) if not pd.isna(pc) else np.nan
        all_pc.append(row[col])

    # aggregate helpers
    good = [abs(v) for v in all_pc if not pd.isna(v)]
    row["% ALL max_abs"] = max(good) if good else np.nan
    row["% ALL avg"] = float(np.mean(good)) if good else np.nan
    return row


def gather_table(products: List[str], frames: List[str], max_rows: int) -> pd.DataFrame:
    rows: List[Dict] = []
    for pid in products[:max_rows]:
        r = compute_row(pid, frames)
        if r is not None:
            rows.append(r)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # enforce numeric
    num_cols = [c for c in df.columns if c not in ["Pair"]]
    df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce")
    return df


# ---------------------- Main UI ----------------------
st.title("Coinbase Movers — Multi‑Timeframe")
st.caption("REST-first (hybrid WS optional). Percent change across timeframes + RSI / MACD / VolZ. Top spikes highlighted.")

# Start WebSocket diagnostics thread only if requested
if data_src.startswith("WebSocket") and HAS_WS:
    products_full = get_products(quote, use_watch, watchlist)
    if not products_full:
        st.error("No products discovered.")
        st.stop()
    if ws_state.thread and ws_state.thread.is_alive():
        if restart_btn:
            ws_state.stop_flag.set()
            time.sleep(0.5)
            ws_state = WSState()
    if not (ws_state.thread and ws_state.thread.is_alive()):
        ws_state.stop_flag.clear()
        ws_state.thread = threading.Thread(
            target=ws_worker, args=(products_full[:min(len(products_full), 5*chunk)], "ticker", "exchange only"), daemon=True
        )
        ws_state.thread.start()
        dbg("starting ws thread")
else:
    if data_src.startswith("WebSocket") and not HAS_WS:
        diag["state.err"] = "websocket-client not installed. Add 'websocket-client' to requirements.txt"
        dbg("websocket-client not installed.")

# Diagnostics
diag["WS_OK"] = HAS_WS
diag["thread_alive"] = bool(ws_state.thread and ws_state.thread.is_alive())
diag["products_first3"] = (watchlist or [])[:3]
diag["history_seconds"] = sum(SUPPORTED_FRAMES[f][0] for f in chosen_frames)
diag["debug_tail"] = dbg_tail[-5:]

with st.expander("Diagnostics"):
    st.json(diag)

# Build universe
universe = get_products(quote, use_watch, watchlist)
if not universe:
    st.warning("No products found for your settings.")
    st.stop()

# REST table build
st.info("Streaming thread started." if data_src.startswith("WebSocket") else "REST mode")
pairs = universe[:max_pairs]

df = gather_table(pairs, chosen_frames, max_pairs)
if df.empty:
    st.warning("Waiting for data… Try a small watchlist and chunk≃3–10.")
    st.stop()

# Ranking & sorting
if rank_by not in df.columns and rank_by.startswith("% "):
    st.warning(f"{rank_by} not present; using % ALL max_abs")
    rank_by = "% ALL max_abs"

df = df.sort_values(by=rank_by if rank_by in df.columns else "% ALL max_abs", ascending=not sort_desc, na_position="last")
if filter_text.strip():
    ft = filter_text.strip().upper()
    if ft.startswith("-"):
        df = df[~df["Pair"].str.contains(ft[1:], case=False, na=False)]
    else:
        df = df[df["Pair"].str.contains(ft, case=False, na=False)]

# Top spike list (safe Arrow types + st.table)
if show_top_spikes:
    spike_df = df.copy()
    by_col = rank_by if rank_by in spike_df.columns else "% ALL max_abs"
    spike_df = spike_df.sort_values(by=by_col, ascending=False, na_position="last").head(top_spike_size)
    cols_to_show = ["Pair", "Last price", "VolZ", "RSI", "MACD_Hist", "% ALL max_abs", "% ALL avg"] + [c for c in df.columns if c.startswith("% ")]
    cols_to_show = [c for c in cols_to_show if c in spike_df.columns]

    view = spike_df[cols_to_show].copy()
    for c in view.columns:
        if c.startswith("% ") or c in ["% ALL max_abs", "% ALL avg"]:
            view[c] = view[c].apply(lambda v: f"{v:.2f}%" if pd.notna(v) else "—")
        elif c in ["Last price", "VolZ", "RSI", "MACD", "MACD_Signal", "MACD_Hist"]:
            view[c] = view[c].apply(lambda v: f"{v:.6g}" if pd.notna(v) else "—")
        else:
            view[c] = view[c].astype(str)

    st.subheader("🔥 Top Spikes")
    with st.container():
        st.markdown('<div class="top-spikes">', unsafe_allow_html=True)
        st.table(view)
        st.markdown('</div>', unsafe_allow_html=True)

# Row highlighting for spikes
def row_style(r: pd.Series) -> List[str]:
    v = r.get("% ALL max_abs", np.nan)
    if pd.notna(v) and abs(v) >= spike_thresh:
        # green highlight for spikes
        return ["background-color: #0b5; color: white;"] * len(r)
    return [""] * len(r)

# Final table
display_cols = ["Pair", "Last price", "VolZ", "RSI", "MACD_Hist", "% ALL max_abs", "% ALL avg"] + [c for c in df.columns if c.startswith("% ")]
display_cols = [c for c in display_cols if c in df.columns]
styled = df[display_cols].head(top_n_rows).style.apply(row_style, axis=1).format(
    {c: "{:.2f}%" for c in display_cols if c.startswith("% ") or c in ["% ALL max_abs", "% ALL avg"]} |
    {"Last price": "{:.6g}", "VolZ": "{:.2f}", "RSI": "{:.1f}", "MACD_Hist": "{:.4f}"}
)
st.dataframe(styled, use_container_width=True)

# Optional: send email alerts for current run (rows exceeding spike threshold)
if notify_method == "Email (SMTP)" and email_to and email_host and email_user and email_pwd:
    alerts = df[df["% ALL max_abs"].abs() >= spike_thresh].copy()
    if not alerts.empty:
        sample = alerts.sort_values(by="% ALL max_abs", ascending=False).head(10)
        lines = [f"{r.Pair}: {r['% ALL max_abs']:.2f}% (last={r['Last price']:.6g})" for _, r in sample.iterrows()]
        ok, info = try_send_email(
            email_to,
            "Coinbase Movers – spike alert",
            "Top spikes:\n" + "\n".join(lines),
            email_host, int(email_port), email_user, email_pwd
        )
        st.success("Alert email sent.") if ok else st.warning(f"Email not sent: {info}")

# Footer / note
st.caption("Note: For stability the table uses REST. WebSocket mode is diagnostics‑only unless you install 'websocket-client'.")
