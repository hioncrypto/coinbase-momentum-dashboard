# Enhanced Crypto Tracker by hioncrypto - Updated Version
# Requirements (add to requirements.txt):
# streamlit>=1.33
# pandas>=2.0
# numpy>=1.24
# requests>=2.31
# websocket-client>=1.6

import streamlit as st

# Page configuration - MUST be first Streamlit command
st.set_page_config(
    page_title="hioncrypto's: Crypto Tracker",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------------------------------------------------------
# GLOBAL + LAYOUT CSS
# ---------------------------------------------------------------------
st.markdown("""
<style>
/* Make page + app view use full width */
html, body, [data-testid="stAppViewContainer"] {
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
    overflow-x: hidden !important;
}

/* MAIN AREA: always take full viewport width.
   When sidebar is collapsed, this fills the whole screen. */
[data-testid="stAppViewContainer"] > .main {
    width: 100vw !important;
    max-width: 100vw !important;
    margin: 0 !important;
}

/* Inner block container: no centered column, full width with padding */
[data-testid="stAppViewContainer"] > .main > div.block-container {
    max-width: 100% !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
    padding-top: 1rem !important;
}

/* SIDEBAR: resizable horizontally */
section[data-testid="stSidebar"] {
    resize: horizontal !important;
    overflow: hidden auto !important;
    min-width: 260px !important;
    max-width: 600px !important;
}

/* Sidebar padding */
section[data-testid="stSidebar"] > div:first-child {
    padding: 1rem !important;
}

/* Ensure sidebar content never overflows its width */
section[data-testid="stSidebar"] * {
    max-width: 100% !important;
}

/* Collapse / expand arrow: pin to far-left of screen so it never
   gets stuck in the middle when sidebar is collapsed. */
[data-testid="collapsedControl"] {
    position: fixed !important;
    top: 0.75rem !important;
    left: 0.75rem !important;
    z-index: 1100 !important;
}

/* Tables fully opaque */
div[data-testid="stDataFrame"],
div[data-testid="stDataFrame"] *,
div[data-testid="stDataEditor"],
div[data-testid="stDataEditor"] * {
    opacity: 1 !important;
}

/* Row highlight colors */
.row-green {
    background-color: #16a34a !important;
    color: white !important;
    font-weight: 600;
}
.row-yellow {
    background-color: #eab308 !important;
    color: black !important;
}

/* Mobile tweaks */
@media (max-width: 768px) {
    .stDataFrame { font-size: 11px; }
    [data-testid="stMetricValue"] { font-size: 18px; }
    [data-testid="stMetricLabel"] { font-size: 11px; }
    .block-container { padding: 0.5rem !important; }
}
</style>
""", unsafe_allow_html=True)

import json
import time
import datetime as dt
import threading
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# Optional dependencies
try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

try:
    import websocket
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False

# =============================================================================
# CONFIGURATION & CONSTANTS
# =============================================================================
class Config:
    """Application configuration"""
    COINBASE_BASE = "https://api.exchange.coinbase.com"
    BINANCE_BASE = "https://api.binance.com"
    COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"

    TIMEFRAMES = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
    QUOTES = ["USD", "USDC", "USDT", "BTC", "ETH", "EUR"]
    EXCHANGES = ["Coinbase", "Binance", "Kraken (coming soon)", "KuCoin (coming soon)"]

    # Alert tracking file
    ALERT_FILE = Path("/tmp/alerted_pairs.json")


CONFIG = Config()

# =============================================================================
# URL PARAMETER MAPPING (Shortened names)
# =============================================================================

URL_PARAM_MAP = {
    # Market settings
    "exchange": "ex", "quote": "q", "pairs_to_discover": "ptd",

    # Mode & timeframes
    "mode": "md", "ws_chunk": "wsc", "sort_tf": "tf", "sort_desc": "sd",

    # Gates
    "lookback_candles": "lb", "min_pct": "mp", "min_bars": "mb",
    "use_vol_spike": "vs", "vol_mult": "vm", "vol_window": "vw",
    "use_rsi": "ur", "rsi_len": "rl", "min_rsi": "mr",
    "use_macd": "um", "macd_fast": "mf", "macd_slow": "ms", "macd_sig": "mg", "min_mhist": "mh",
    "use_atr": "ua", "atr_len": "al", "min_atr": "ma",
    "use_trend": "ut", "pivot_span": "ps", "trend_within": "tw",
    "use_roc": "uro", "min_roc": "mro",
    "use_macd_cross": "umc", "macd_cross_bars": "mcb", "macd_cross_only_bull": "mcob",
    "macd_cross_below_zero": "mcbz", "macd_hist_confirm_bars": "mhcb",
    "gate_mode": "gm", "hard_filter": "hf", "K_green": "kg", "Y_yellow": "yy",
    "preset": "pr",

    # Alert settings
    "alert_mode": "am", "email_to": "et", "webhook_url": "wu",

    # Display
    "font_scale": "fs", "refresh_sec": "rs",

    # ATH/ATL
    "do_ath": "da", "basis": "bs", "amount_daily": "ad", "amount_hourly": "ah", "amount_weekly": "aw",

    # Listing Radar
    "lr_enabled": "lre", "lr_watch_coinbase": "lrwc", "lr_watch_binance": "lrwb",
    "lr_watch_quotes": "lrwq", "lr_poll_sec": "lrps", "lr_upcoming_window_h": "lruwh",
    "lr_feeds": "lrf",

    # UI state
    "use_watch": "uw", "use_my_pairs": "ump", "watchlist": "wl", "my_pairs": "myp"
}

def save_to_url(key: str, value):
    try:
        param_name = URL_PARAM_MAP.get(key, key)
        st.query_params[param_name] = str(value)
    except Exception:
        pass

def load_from_url(key: str, default_value, value_type=str):
    try:
        param_name = URL_PARAM_MAP.get(key, key)
        qv = st.query_params.get(param_name)
        if qv is not None:
            if value_type == bool:
                return qv.lower() in ("true", "1", "yes", "on")
            if value_type == int:
                return int(qv)
            if value_type == float:
                return float(qv)
            return qv
    except Exception:
        pass
    return default_value

# =============================================================================
# ALERT FILE MANAGEMENT
# =============================================================================

def load_alerted_pairs() -> dict:
    try:
        if CONFIG.ALERT_FILE.exists():
            with open(CONFIG.ALERT_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_alerted_pairs(pairs: dict):
    try:
        with open(CONFIG.ALERT_FILE, "w") as f:
            json.dump(pairs, f)
    except Exception:
        pass

def clear_alerted_pairs():
    try:
        if CONFIG.ALERT_FILE.exists():
            CONFIG.ALERT_FILE.unlink()
    except Exception:
        pass

# =============================================================================
# STATE MANAGEMENT
# =============================================================================

def init_session_state():
    if "_initialized" not in st.session_state:
        st.session_state["_initialized"] = True

    defaults = {
        # Market settings
        "exchange": "Coinbase",
        "quote": "USD",
        "pairs_to_discover": 400,

        # Mode
        "mode": "REST only",
        "ws_chunk": 5,

        # Timeframes
        "sort_tf": "1h",
        "sort_desc": True,
        "min_bars": 30,

        # Gates
        "lookback_candles": 3,
        "min_pct": 3.0,
        "use_vol_spike": False,
        "vol_mult": 1.10,
        "vol_window": 20,
        "use_rsi": False,
        "rsi_len": 14,
        "min_rsi": 55,
        "use_macd": False,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_sig": 9,
        "min_mhist": 0.0,
        "use_atr": False,
        "atr_len": 14,
        "min_atr": 0.5,
        "use_trend": False,
        "pivot_span": 4,
        "trend_within": 48,
        "use_roc": False,
        "min_roc": 1.0,
        "use_macd_cross": False,
        "macd_cross_bars": 5,
        "macd_cross_only_bull": True,
        "macd_cross_below_zero": True,
        "macd_hist_confirm_bars": 3,
        "gate_mode": "ANY",
        "hard_filter": False,
        "K_green": 3,
        "Y_yellow": 2,
        "preset": "None",

        # Alerts
        "alert_mode": "",
        "email_to": "",
        "webhook_url": "",

        # Display
        "font_scale": 1.0,
        "refresh_sec": 30,

        # ATH/ATL
        "do_ath": False,
        "basis": "Daily",
        "amount_daily": 90,
        "amount_hourly": 24,
        "amount_weekly": 12,

        # UI
        "collapse_all": False,
        "use_watch": False,
        "use_my_pairs": False,
        "watchlist": "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD",
        "my_pairs": "",

        # WS
        "ws_thread": None,
        "ws_alive": False,
        "ws_prices": {},

        # Listing radar
        "lr_enabled": False,
        "lr_baseline": {"Coinbase": set(), "Binance": set()},
        "lr_events": [],
        "lr_unacked": 0,
        "lr_watch_coinbase": True,
        "lr_watch_binance": True,
        "lr_watch_quotes": "USD, USDT, USDC",
        "lr_poll_sec": 30,
        "lr_upcoming_window_h": 48,
        "lr_feeds": "https://blog.coinbase.com/feed\nhttps://www.binance.com/en/support/announcement",
    }

    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = load_from_url(key, default, type(default))

init_session_state()

# =============================================================================
# INDICATORS / DATA / GATES / ALERTS
# (UNCHANGED FROM PREVIOUS VERSION)
# =============================================================================
# --- everything below here is identical logic to the last code I gave you ---
# I’m keeping it as-is so we don’t touch your trading logic / alerts at all.
# (For brevity I’m not commenting every line again.)

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype("float64").ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    ru = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rd = pd.Series(dn, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = ru / (rd + 1e-12)
    return 100 - 100 / (1 + rs)

def macd_core(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def volume_spike(df: pd.DataFrame, window: int = 20) -> float:
    if len(df) < window + 1:
        return np.nan
    current_vol = df["volume"].iloc[-1]
    avg_vol = df["volume"].rolling(window).mean().iloc[-1]
    return float(current_vol / (avg_vol + 1e-12))

def find_pivots(close: pd.Series, span: int = 3) -> Tuple[List[int], List[int]]:
    n = len(close)
    highs, lows = [], []
    values = close.values
    for i in range(span, n - span):
        if (values[i] > values[i-span:i].max() and
            values[i] > values[i+1:i+1+span].max()):
            highs.append(i)
        if (values[i] < values[i-span:i].min() and
            values[i] < values[i+1:i+1+span].min()):
            lows.append(i)
    return highs, lows

def trend_breakout_up(df: pd.DataFrame, span: int = 3, within_bars: int = 48) -> bool:
    if df is None or len(df) < span*2 + 5:
        return False
    highs, _ = find_pivots(df["close"], span)
    if not highs:
        return False
    latest_high_idx = highs[-1]
    resistance_level = float(df["close"].iloc[latest_high_idx])
    for i in range(latest_high_idx + 1, len(df)):
        if float(df["close"].iloc[i]) > resistance_level:
            bars_since_breakout = len(df) - 1 - i
            return bars_since_breakout <= within_bars
    return False

def get_bars_limit(timeframe: str) -> int:
    limits = {"5m": 120, "15m": 96, "1h": 48, "4h": 24}
    return limits.get(timeframe, 48)

def fetch_coinbase_data(pair: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
    tf_seconds = CONFIG.TIMEFRAMES.get(timeframe)
    if not tf_seconds:
        return None
    url = f"{CONFIG.COINBASE_BASE}/products/{pair}/candles"
    params = {"granularity": tf_seconds}
    headers = {"User-Agent": "crypto-tracker/2.0", "Accept": "application/json"}
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                if not data:
                    return None
                df = pd.DataFrame(
                    data,
                    columns=["time", "low", "high", "open", "close", "volume"]
                )
                df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                df = df.sort_values("time").reset_index(drop=True)
                df = df[["time", "open", "high", "low", "close", "volume"]]
                if len(df) > limit:
                    df = df.iloc[-limit:].reset_index(drop=True)
                return df if not df.empty else None
            elif r.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.6 * (attempt + 1))
                continue
            else:
                return None
        except Exception:
            time.sleep(0.4 * (attempt + 1))
    return None

def fetch_binance_data(pair: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
    try:
        base, quote = pair.split("-")
        symbol = f"{base}{quote}"
    except ValueError:
        return None
    interval = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h"}.get(timeframe, "1h")
    params = {"symbol": symbol, "interval": interval, "limit": max(50, limit)}
    try:
        r = requests.get(f"{CONFIG.BINANCE_BASE}/api/v3/klines", params=params, timeout=20)
        if r.status_code != 200:
            return None
        rows = []
        for k in r.json():
            rows.append({
                "time": pd.to_datetime(k[0], unit="ms", utc=True),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
            })
        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        return df if not df.empty else None
    except Exception:
        return None

def fetch_data(exchange: str, pair: str, timeframe: str,
               limit: Optional[int] = None) -> Optional[pd.DataFrame]:
    if limit is None:
        limit = get_bars_limit(timeframe)
    limit = max(1, min(300, limit))
    ex = exchange.lower()
    if ex.startswith("coinbase"):
        return fetch_coinbase_data(pair, timeframe, limit)
    if ex.startswith("binance"):
        return fetch_binance_data(pair, timeframe, limit)
    return fetch_coinbase_data(pair, timeframe, limit)

_refresh_ttl = int(max(5, st.session_state.get("refresh_sec", 30)))

@st.cache_data(show_spinner=False, ttl=_refresh_ttl)
def get_cached_data(exchange: str, pair: str, timeframe: str) -> Optional[pd.DataFrame]:
    try:
        limit = get_bars_limit(timeframe)
        return fetch_data(exchange, pair, timeframe, limit)
    except Exception:
        return None

def get_coinbase_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CONFIG.COINBASE_BASE}/products", timeout=25)
        r.raise_for_status()
        products = []
        for p in r.json():
            if (p.get("quote_currency") == quote.upper() and
                p.get("status") == "online" and
                not p.get("trading_disabled", False) and
                not p.get("cancel_only", False)):
                products.append(f"{p['base_currency']}-{p['quote_currency']}")
        return sorted(products)
    except Exception:
        return []

def get_binance_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CONFIG.BINANCE_BASE}/api/v3/exchangeInfo", timeout=25)
        r.raise_for_status()
        products = []
        q = quote.upper()
        for s in r.json().get("symbols", []):
            if s.get("status") == "TRADING" and s.get("quoteAsset") == q:
                products.append(f"{s['baseAsset']}-{q}")
        return sorted(products)
    except Exception:
        return []

def get_products(exchange: str, quote: str) -> List[str]:
    ex = exchange.lower()
    if ex.startswith("coinbase"):
        return get_coinbase_products(quote)
    if ex.startswith("binance"):
        return get_binance_products(quote)
    return get_coinbase_products(quote)

# progressive stages, alerts, gate evaluation, sidebar expanders,
# main processing loop, websocket, auto-refresh, etc.
# (identical to the last full version I sent; I’m not cutting any logic)

# -------------- FROM HERE DOWN, KEEP YOUR EXISTING LOGIC --------------
# To keep this answer from being 100+ pages, reuse the previous code body
# starting at check_progressive_stages(...) all the way to the end,
# with no changes.

# Just paste **all the remaining code from your last working file**
# after this comment block. The only edits needed for your layout bug
# are the CSS at the very top of this file.

