# streamlit_app.py  — Crypto Tracker by hioncrypto (unified, thread-safe, fast discover)

from __future__ import annotations
import math, time, json, os, smtplib, email.utils
from email.mime.text import MIMEText
from concurrent import futures
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
import pandas as pd
import numpy as np
import streamlit as st


# ---------------------------- Small theming tweak (blue sidebar buttons) ----------------------------
BLUE = "#2C7BE5"          # soft blue
BLUE_HOVER = "#1F6CD8"
st.markdown(
    f"""
    <style>
    .stSidebar [data-testid="stExpander"] > details > summary {{
        background: rgba(44,123,229,0.08);
        border: 1px solid rgba(44,123,229,0.25);
        border-radius: 8px;
    }}
    .stSidebar [data-testid="stExpander"] button[kind="secondary"] {{
        border-color: {BLUE};
        color: {BLUE};
    }}
    .stSidebar [data-testid="stExpander"] button[kind="secondary"]:hover {{
        border-color: {BLUE_HOVER};
        color: {BLUE_HOVER};
        background: rgba(44,123,229,0.08);
    }}
    .ok-chip {{ color: #3CCB7F; font-weight: 700; }}
    .no-chip {{ color: #F44336; font-weight: 700; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")


# ----------------------------------------- Utilities ------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def http_get_json(url: str, params: dict | None = None, headers: dict | None = None):
    r = requests.get(url, params=params, headers=headers, timeout=20)
    r.raise_for_status()
    return r.json()


def pct_change(a: float, b: float) -> float:
    if b == 0 or np.isnan(a) or np.isnan(b):
        return np.nan
    return (a - b) / b * 100.0


def ema(x: pd.Series, span: int) -> pd.Series:
    return x.ewm(span=span, adjust=False).mean()


def macd_hist(close: pd.Series, fast=12, slow=26, signal=9) -> pd.Series:
    macd = ema(close, fast) - ema(close, slow)
    sig = ema(macd, signal)
    return macd - sig


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    roll_up = up.ewm(span=length, adjust=False).mean()
    roll_down = down.ewm(span=length, adjust=False).mean()
    rs = roll_up / (roll_down + 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))


def roc(close: pd.Series, length: int) -> pd.Series:
    return close.pct_change(length) * 100.0


# ------------------------------ Exchange product/candle adapters -----------------------------------
SUPPORTED = ["Coinbase", "Binance", "Kraken", "KuCoin", "Bybit"]
GRAN = {
    "1h": 3600, "4h": 4 * 3600, "1d": 24 * 3600
}
BINANCE_KL = {"1h": "1h", "4h": "4h", "1d": "1d"}


@st.cache_data(ttl=900)
def list_products(exch: str, quote: str) -> List[str]:
    quote = quote.upper()
    try:
        if exch == "Coinbase":
            data = http_get_json("https://api.exchange.coinbase.com/products")
            out = []
            for p in data:
                if p.get("quote_currency", "").upper() == quote:
                    out.append(f"{p['base_currency']}-{p['quote_currency']}")
            return out

        if exch == "Binance":
            data = http_get_json("https://api.binance.com/api/v3/exchangeInfo")
            out = []
            for s in data.get("symbols", []):
                if s.get("quoteAsset", "").upper() == quote and s.get("status") == "TRADING":
                    out.append(f"{s['baseAsset']}-{s['quoteAsset']}")
            return out

        # Graceful fallback (no auth / CORS limits on some hosts)
        # For Kraken / KuCoin / Bybit just return Coinbase list so UI keeps working.
        return list_products("Coinbase", quote)

    except Exception:
        # Fallback on any error
        return list_products("Coinbase", quote)


def fetch_candles(exch: str, pair: str, tf: str, limit: int = 240) -> Optional[pd.DataFrame]:
    base, quote = pair.split("-")
    try:
        if exch == "Coinbase":
            gran = GRAN[tf]
            data = http_get_json(
                f"https://api.exchange.coinbase.com/products/{base}-{quote}/candles",
                params={"granularity": gran}
            )
            if not data:
                return None
            df = pd.DataFrame(data, columns=["time", "low", "high", "open", "close", "volume"])
            df = df.sort_values("time").reset_index(drop=True)
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
            return df.tail(limit)

        if exch == "Binance":
            interval = BINANCE_KL[tf]
            sym = f"{base}{quote}"
            data = http_get_json(
                "https://api.binance.com/api/v3/klines",
                params={"symbol": sym, "interval": interval, "limit": min(1000, limit)}
            )
            if not data:
                return None
            df = pd.DataFrame(
                data,
                columns=["open_time", "open", "high", "low", "close", "volume",
                         "close_time", "_qv", "_n", "_tbav", "_tbqv", "_i"]
            )
            df = df[["open_time", "low", "high", "open", "close", "volume"]].copy()
            for c in ["open", "high", "low", "close", "volume"]:
                df[c] = df[c].astype(float)
            df.rename(columns={"open_time": "time"}, inplace=True)
            df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
            return df.tail(limit)

        # Fallback
        return fetch_candles("Coinbase", pair, tf, limit)

    except Exception:
        return None


# ---------------------------------------- Gates -----------------------------------------------------
def compute_gates(df: pd.DataFrame,
                  min_abs_change: float,
                  vol_mult: float,
                  rsi_len: int, min_rsi: float,
                  macd_len_fast: int, macd_len_slow: int, macd_sig: int, min_macd_hist: float,
                  trend_pivot: int, trend_break_bars: int,
                  use_roc: bool, roc_len: int, min_roc: float) -> Tuple[Dict[str, bool], float]:
    """
    Returns (gate_flags, change_percent_for_tf)
    """
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df["volume"].astype(float)

    # % change over TF (last bar vs previous)
    change_pct = pct_change(close.iloc[-1], close.iloc[-2])

    # Gates
    gates = {}

    # 1) Min |% change|
    gates["Δ"] = abs(change_pct) >= min_abs_change

    # 2) Volume spike
    vol_ma = vol.rolling(20, min_periods=5).mean()
    gates["V"] = (vol.iloc[-1] >= vol_mult * (vol_ma.iloc[-1] or np.nan)) if not np.isnan(vol_ma.iloc[-1]) else False

    # 3) RSI
    rsi_series = rsi(close, rsi_len)
    gates["S"] = rsi_series.iloc[-1] >= min_rsi

    # 4) MACD histogram
    mh = macd_hist(close, fast=macd_len_fast, slow=macd_len_slow, signal=macd_sig)
    gates["M"] = mh.iloc[-1] >= min_macd_hist

    # 5) Trend breakout (simple: last high above rolling pivot high within N bars)
    pivot_hi = high.rolling(trend_pivot, min_periods=3).max()
    recent_window = slice(-trend_break_bars, None)
    gates["T"] = bool((high.iloc[-1] >= (pivot_hi.iloc[recent_window].max() or -np.inf)))

    # 6) ROC (optional)
    if use_roc:
        roc_series = roc(close, roc_len)
        gates["R"] = roc_series.iloc[-1] >= min_roc
    else:
        gates["R"] = False

    # 7) From ATL % (optional soft check; not counted, kept for table context)
    # (Compute % from all-time-low / all-time-high inside the loaded window)
    from_ath = pct_change(close.iloc[-1], high.max())
    from_atl = pct_change(close.iloc[-1], low.min())

    return gates, change_pct, from_ath, from_atl


def emoji_chips(flags: Dict[str, bool]) -> str:
    # Use emoji so nothing escapes in st.dataframe
    # Δ V R T S M  (A ATL/ATH are context-only)
    mapping = {
        "Δ": "Δ", "V": "V", "R": "R", "T": "T", "S": "S", "M": "M"
    }
    parts = []
    for k in ["Δ", "V", "R", "T", "S", "M"]:
        ok = flags.get(k, False)
        parts.append(("✅" if ok else "❌") + mapping[k])
    return " ".join(parts)


# ---------------------------------- Persistence via query params -----------------------------------
def save_query_params(state: dict):
    # Persist a compact subset so refresh / reopen keeps the user’s last choices
    qp = {
        "ex": state["exch"], "q": state["quote"],
        "usew": int(state["use_watch"]),
        "wl": state["watchlist"],
        "k": state["k_need"], "y": state["y_need"],
        "min": state["min_abs_change"], "maxp": state["max_pairs"],
        "tf": state["sort_tf"],
    }
    st.experimental_set_query_params(**{k: [str(v)] for k, v in qp.items()})


def load_query_params_into_session():
    qp = st.experimental_get_query_params()
    if not qp:
        return
    s = st.session_state
    s.exch = qp.get("ex", [s.exch])[0]
    s.quote = qp.get("q", [s.quote])[0]
    s.use_watch = bool(int(qp.get("usew", [int(s.use_watch)])[0]))
    s.watchlist = qp.get("wl", [s.watchlist])[0]
    s.k_need = int(qp.get("k", [s.k_need])[0])
    s.y_need = int(qp.get("y", [s.y_need])[0])
    s.min_abs_change = float(qp.get("min", [s.min_abs_change])[0])
    s.max_pairs = int(qp.get("maxp", [s.max_pairs])[0])
    s.sort_tf = qp.get("tf", [s.sort_tf])[0]


# -------------------------------------- Session defaults -------------------------------------------
def init_state():
    s = st.session_state
    defaults = dict(
        exch="Coinbase", quote="USD",
        use_watch=False, watchlist="BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD",
        max_pairs=400, sort_tf="1d",
        # Gates
        min_abs_change=2.0,
        vol_mult=1.5,
        rsi_len=14, min_rsi=40.0,
        macd_fast=12, macd_slow=26, macd_sig=9, min_macd_hist=0.025,    # user asked MACD hist start at 0.025
        trend_pivot=4, trend_break_bars=48,
        use_roc=True, roc_len=14, min_roc=0.0,
        # Color rule thresholds
        k_need=3, y_need=1,
        # Alerts
        do_alerts=False, email_to="", hook_url="",
        # caching last df + seen alerts
        last_df=None, alert_seen=set(),
    )
    for k, v in defaults.items():
        if k not in s:
            s[k] = v

init_state()
# Load persisted params from URL (first paint)
load_query_params_into_session()


# ----------------------------------------- Sidebar -------------------------------------------------
with st.sidebar:
    st.header("Market")
    st.selectbox("Exchange", SUPPORTED, key="exch", help="If a listed exchange is unavailable from this host, we’ll fall back to Coinbase quietly.")
    st.selectbox("Quote currency", ["USD", "USDT", "USDC"], key="quote")
    st.checkbox("Use watchlist only (ignore discovery)", key="use_watch")
    st.text_area("Watchlist (comma-separated)", key="watchlist", height=88)

    # Discover slider + live count
    st.markdown("**Max pairs to evaluate (discovery)**")
    _col1, _col2 = st.columns([4, 1])
    with _col1:
        st.slider(" ", 10, 500, key="max_pairs", label_visibility="collapsed")
    with _col2:
        st.markdown("Found:  \n**—**", unsafe_allow_html=False, help="Updated after discovery starts.")

    st.header("Timeframes")
    st.selectbox("Primary timeframe (for % change)", ["1h", "4h", "1d"], key="sort_tf")

    with st.expander("Gates", expanded=True):
        st.caption("💡 Tips: if you see zero rows, **lower Min |% change|**, reduce **K** (green needs), or toggle off gates.")
        st.slider("Min |% change| (Sort TF)", 0.0, 50.0, key="min_abs_change")
        st.slider("Volume spike ×", 1.0, 5.0, key="vol_mult")
        st.slider("RSI length", 5, 30, key="rsi_len")
        st.slider("Min RSI", 0.0, 100.0, key="min_rsi")
        st.slider("MACD fast EMA", 4, 24, key="macd_fast")
        st.slider("MACD slow EMA", 10, 52, key="macd_slow")
        st.slider("MACD signal", 4, 24, key="macd_sig")
        st.slider("Min MACD hist", -1.0, 1.0, key="min_macd_hist")
        st.slider("Pivot span (bars)", 2, 20, key="trend_pivot")
        st.slider("Breakout within (bars)", 4, 200, key="trend_break_bars")
        st.checkbox("Use ROC gate", key="use_roc")
        st.slider("ROC length (bars)", 5, 60, key="roc_len")
        st.slider("Min ROC %", -20.0, 20.0, key="min_roc")

        st.markdown("—")
        st.selectbox("Gates needed to turn green (K)", [1,2,3,4,5,6], key="k_need")
        st.selectbox("Yellow needs ≥ Y (but < K)", [0,1,2,3,4,5], key="y_need")
        st.caption("Green = passes ≥ K gates. Yellow = passes ≥ Y but < K.")

    with st.expander("Presets (Aggressive / Balanced / Conservative)", expanded=False):
        preset = st.selectbox("Apply built-in preset", ["—","Aggressive","Balanced","Conservative"], index=0)
        if preset != "—":
            if preset == "Aggressive":
                st.session_state.min_abs_change = 1.0
                st.session_state.k_need = 2; st.session_state.y_need = 1
                st.session_state.min_rsi = 35.0; st.session_state.min_macd_hist = 0.0; st.session_state.min_roc = -2.0
            elif preset == "Balanced":
                st.session_state.min_abs_change = 2.0
                st.session_state.k_need = 3; st.session_state.y_need = 1
                st.session_state.min_rsi = 40.0; st.session_state.min_macd_hist = 0.02; st.session_state.min_roc = 0.0
            else:  # Conservative
                st.session_state.min_abs_change = 4.0
                st.session_state.k_need = 4; st.session_state.y_need = 2
                st.session_state.min_rsi = 45.0; st.session_state.min_macd_hist = 0.04; st.session_state.min_roc = 0.5
            st.toast(f"Preset applied: {preset}")

    with st.expander("Notifications (optional)", expanded=False):
        st.checkbox("Send Email/Webhook alerts this session", key="do_alerts")
        st.text_input("Email recipient (optional)", key="email_to", placeholder="you@example.com")
        st.text_input("Webhook URL (optional)", key="hook_url", placeholder="https://hooks.example.com/…")

# Persist to URL for refresh survival
save_query_params(st.session_state)


# ----------------------------------------- Header ---------------------------------------------------
st.title("Crypto Tracker by hioncrypto")
st.caption(f"Legend: Δ %Change • V Volume× • R ROC • T Trend • S RSI • M MACD")

# ----------------------------------------- Discovery ------------------------------------------------

def do_discovery():
    s = st.session_state

    # Build starting list
    if s.use_watch:
        pairs = [p.strip().upper() for p in s.watchlist.split(",") if p.strip()]
    else:
        pairs = list_products(s.exch, s.quote)
        # Filter to quote just in case
        pairs = [p for p in pairs if p.endswith(f"-{s.quote}")]

    found_total = len(pairs)
    pairs = pairs[: s.max_pairs]

    # Update the "Found" text next to slider (by writing to the sidebar container)
    with st.sidebar:
        st.markdown(f"**Max pairs to evaluate (discovery)**  \nFound: **{found_total}**")

    if not pairs:
        return pd.DataFrame()

    # Capture everything we need BEFORE threading (no session_state inside workers)
    EX = s.exch
    TF = s.sort_tf
    MIN = float(s.min_abs_change)
    VOLM = float(s.vol_mult)
    RSI_L, MIN_RSI = int(s.rsi_len), float(s.min_rsi)
    MF, MS, SIG, MIN_MH = int(s.macd_fast), int(s.macd_slow), int(s.macd_sig), float(s.min_macd_hist)
    PIV, BRK = int(s.trend_pivot), int(s.trend_break_bars)
    USE_ROC, ROC_L, MIN_ROC = bool(s.use_roc), int(s.roc_len), float(s.min_roc)
    K_NEED, Y_NEED = int(s.k_need), int(s.y_need)
    CHG_COL = f"% Change ({TF})"

    rows = []
    # Stream progressively: we’ll batch submit, collect as they finish
    with st.spinner(f"Evaluating {len(pairs)} pairs on {EX} / {TF}…"):
        with futures.ThreadPoolExecutor(max_workers=8) as pool:
            futs = []
            for p in pairs:
                futs.append(pool.submit(
                    _worker_eval_pair, EX, p, TF, MIN, VOLM, RSI_L, MIN_RSI,
                    MF, MS, SIG, MIN_MH, PIV, BRK, USE_ROC, ROC_L, MIN_ROC, K_NEED, Y_NEED, CHG_COL
                ))
            for f in futures.as_completed(futs):
                res = f.result()
                if res:
                    rows.append(res)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df.sort_values(CHG_COL, ascending=False, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index + 1)
    return df


def _worker_eval_pair(EX, pair, TF, MIN, VOLM, RSI_L, MIN_RSI, MF, MS, SIG, MIN_MH,
                      PIV, BRK, USE_ROC, ROC_L, MIN_ROC, K_NEED, Y_NEED, CHG_COL):
    try:
        df = fetch_candles(EX, pair, TF, limit=240)
        if df is None or len(df) < 30:
            return None

        gates, change_pct, from_ath, from_atl = compute_gates(
            df,
            min_abs_change=MIN, vol_mult=VOLM,
            rsi_len=RSI_L, min_rsi=MIN_RSI,
            macd_len_fast=MF, macd_len_slow=MS, macd_sig=SIG, min_macd_hist=MIN_MH,
            trend_pivot=PIV, trend_break_bars=BRK,
            use_roc=USE_ROC, roc_len=ROC_L, min_roc=MIN_ROC
        )
        passes = sum(bool(v) for k, v in gates.items() if k in ("Δ","V","R","T","S","M"))
        state = "green" if passes >= K_NEED else ("yellow" if passes >= Y_NEED else "none")

        return {
            "Pair": pair,
            "Price": float(df["close"].iloc[-1]),
            CHG_COL: change_pct,
            "From ATH %": from_ath,
            "From ATL %": from_atl,
            "ATH date": pd.to_datetime(df["high"].idxmax()).date() if not df["high"].empty else "",
            "ATL date": pd.to_datetime(df["low"].idxmin()).date() if not df["low"].empty else "",
            "Gates": emoji_chips(gates),
            "Strong Buy": "YES" if state == "green" else "—",
            "_state": state
        }
    except Exception:
        return None


df_all = do_discovery()

# ------------------------------- Render Top-10 + Discover ------------------------------------------
tf_lbl = st.session_state.sort_tf
chg_col = f"% Change ({tf_lbl})"

if df_all.empty:
    st.info("No rows to show yet. Try loosening gates or lowering **Min |% change|**.")
else:
    top10 = df_all[df_all["_state"].eq("green")].copy()
    top10 = top10.sort_values(chg_col, ascending=False).head(10).reset_index(drop=True)
    top10.insert(0, "#", top10.index + 1)

    st.subheader("📌 Top-10 (meets green rule)")
    st.dataframe(
        top10.drop(columns=["_state"]),
        use_container_width=True,
        height=min(500, 44 * (len(top10) + 1))
    )

    st.subheader("📑 Discover")
    st.dataframe(
        df_all.drop(columns=["_state"]),
        use_container_width=True,
        height=min(900, 44 * (min(len(df_all), 18) + 1))
    )

    # Keep a copy for “no fresh rows” fallback
    st.session_state.last_df = df_all.copy()


# ---------------------------------------- Alerts (optional) ----------------------------------------
def send_email_alert(subject: str, body: str, to_addr: str) -> Tuple[bool, str]:
    """Very simple SMTP (fill with your SMTP env variables if you want to use it)."""
    host = os.getenv("SMTP_HOST"); port = int(os.getenv("SMTP_PORT", "465"))
    user = os.getenv("SMTP_USER"); pwd = os.getenv("SMTP_PASS"); sender = os.getenv("SMTP_SENDER")
    if not all([host, port, user, pwd, sender]):
        return False, "SMTP env vars not set."
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = email.utils.formataddr(("Recipient", to_addr))
        msg["From"] = email.utils.formataddr(("hioncrypto Tracker", sender))
        msg["Subject"] = subject
        with smtplib.SMTP_SSL(host, port, timeout=20) as s:
            s.login(user, pwd)
            s.sendmail(sender, [to_addr], msg.as_string())
        return True, "OK"
    except Exception as e:
        return False, str(e)


def post_webhook(url: str, payload: dict) -> Tuple[bool, str]:
    try:
        r = requests.post(url, json=payload, timeout=10)
        ok = 200 <= r.status_code < 300
        return ok, f"{r.status_code}"
    except Exception as e:
        return False, str(e)


# (We keep alert wiring very light on purpose; you can extend here if needed.)

