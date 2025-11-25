# Enhanced Crypto Tracker by hioncrypto - Updated Version
# Requirements (add to requirements.txt):
# streamlit>=1.33
# pandas>=2.0
# numpy>=1.24
# requests>=2.31
# websocket-client>=1.6

import streamlit as st

# ---------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------
st.set_page_config(
    page_title="hioncrypto's: Crypto Tracker",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------
# GLOBAL CSS (SIDEBAR + FLOATING TOGGLE + RESIZABLE SIDEBAR)
# ---------------------------------------------------------------------
st.markdown(
    """
<style>
/* Floating sidebar collapse / expand button */
[data-testid="collapsedControl"] {
    position: fixed !important;
    top: 1rem !important;
    left: 0.75rem !important;
    transform: translateX(0) !important;
    z-index: 1001 !important;
}

/* SIDEBAR: wider by default + resizable */
section[data-testid="stSidebar"] {
    width: 320px !important;
    min-width: 260px !important;
    max-width: 560px !important;
    resize: horizontal !important;       /* user can drag right edge */
    overflow: auto !important;
    border-right: 1px solid #444 !important;
}

/* Keep sidebar header pinned within the sidebar scroll */
section[data-testid="stSidebar"] > div:first-child {
    padding: 0.75rem 0.75rem 1rem 0.75rem !important;
}

/* Make sidebar content use full available width */
section[data-testid="stSidebar"] * {
    max-width: 100% !important;
}

/* MAIN AREA: always use full viewport width */
[data-testid="stAppViewContainer"] .main {
    max-width: 100vw !important;
}

/* Main block container padding */
[data-testid="stAppViewContainer"] > .main > div.block-container {
    max-width: 100vw !important;
    padding-left: 1rem !important;
    padding-right: 1rem !important;
}

/* Dataframes fully opaque */
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

    section[data-testid="stSidebar"] {
        width: 280px !important;
        min-width: 240px !important;
        max-width: 100% !important;
    }
}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------
# IMPORTS
# ---------------------------------------------------------------------
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

# ---------------------------------------------------------------------
# CONFIGURATION & CONSTANTS
# ---------------------------------------------------------------------
class Config:
    COINBASE_BASE = "https://api.exchange.coinbase.com"
    BINANCE_BASE = "https://api.binance.com"
    COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"

    TIMEFRAMES = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
    QUOTES = ["USD", "USDC", "USDT", "BTC", "ETH", "EUR"]
    EXCHANGES = [
        "Coinbase",
        "Binance",
        "Kraken (coming soon)",
        "KuCoin (coming soon)",
    ]

    # Alert tracking file
    ALERT_FILE = Path("/tmp/alerted_pairs.json")


CONFIG = Config()

# ---------------------------------------------------------------------
# URL PARAM HELPERS
# ---------------------------------------------------------------------
URL_PARAM_MAP = {
    # Market settings
    "exchange": "ex",
    "quote": "q",
    "pairs_to_discover": "ptd",
    # Mode & timeframes
    "mode": "md",
    "ws_chunk": "wsc",
    "sort_tf": "tf",
    "sort_desc": "sd",
    # Gates
    "lookback_candles": "lb",
    "min_pct": "mp",
    "min_bars": "mb",
    "use_vol_spike": "vs",
    "vol_mult": "vm",
    "vol_window": "vw",
    "use_rsi": "ur",
    "rsi_len": "rl",
    "min_rsi": "mr",
    "use_macd": "um",
    "macd_fast": "mf",
    "macd_slow": "ms",
    "macd_sig": "mg",
    "min_mhist": "mh",
    "use_atr": "ua",
    "atr_len": "al",
    "min_atr": "ma",
    "use_trend": "ut",
    "pivot_span": "ps",
    "trend_within": "tw",
    "use_roc": "uro",
    "min_roc": "mro",
    "use_macd_cross": "umc",
    "macd_cross_bars": "mcb",
    "macd_cross_only_bull": "mcob",
    "macd_cross_below_zero": "mcbz",
    "macd_hist_confirm_bars": "mhcb",
    "gate_mode": "gm",
    "hard_filter": "hf",
    "K_green": "kg",
    "Y_yellow": "yy",
    "preset": "pr",
    # Alert settings
    "alert_mode": "am",
    "email_to": "et",
    "webhook_url": "wu",
    # Display
    "font_scale": "fs",
    "refresh_sec": "rs",
    # ATH/ATL
    "do_ath": "da",
    "basis": "bs",
    "amount_daily": "ad",
    "amount_hourly": "ah",
    "amount_weekly": "aw",
    # Listing Radar
    "lr_enabled": "lre",
    "lr_watch_coinbase": "lrwc",
    "lr_watch_binance": "lrwb",
    "lr_watch_quotes": "lrwq",
    "lr_poll_sec": "lrps",
    "lr_upcoming_window_h": "lruwh",
    "lr_feeds": "lrf",
    # UI state
    "use_watch": "uw",
    "use_my_pairs": "ump",
    "watchlist": "wl",
    "my_pairs": "myp",
    "collapse_all": "ca",
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


# ---------------------------------------------------------------------
# ALERT FILE PERSISTENCE
# ---------------------------------------------------------------------
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


# ---------------------------------------------------------------------
# SESSION STATE INIT
# ---------------------------------------------------------------------
def init_session_state():
    if "_initialized" not in st.session_state:
        st.session_state["_initialized"] = True

    # defaults – updated min_bars + lookback
    defaults = {
        # Market
        "exchange": "Coinbase",
        "quote": "USD",
        "pairs_to_discover": 400,
        # Mode
        "mode": "REST only",
        "ws_chunk": 5,
        "sort_tf": "1h",
        "sort_desc": True,
        "min_bars": 6,  # <= 20 now
        # Gates
        "lookback_candles": 3,  # <= 20 now
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
        # UI / lists
        "collapse_all": False,
        "use_watch": False,
        "use_my_pairs": False,
        "watchlist": "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD",
        "my_pairs": "",
        # WebSocket
        "ws_thread": None,
        "ws_alive": False,
        "ws_prices": {},
        # Listing Radar
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

# ---------------------------------------------------------------------
# INDICATORS
# ---------------------------------------------------------------------
def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype("float64").ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    ru = pd.Series(up, index=close.index).ewm(alpha=1 / length, adjust=False).mean()
    rd = pd.Series(dn, index=close.index).ewm(alpha=1 / length, adjust=False).mean()
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
        if (
            values[i] > values[i - span : i].max()
            and values[i] > values[i + 1 : i + 1 + span].max()
        ):
            highs.append(i)
        if (
            values[i] < values[i - span : i].min()
            and values[i] < values[i + 1 : i + 1 + span].min()
        ):
            lows.append(i)
    return highs, lows


def trend_breakout_up(df: pd.DataFrame, span: int = 3, within_bars: int = 48) -> bool:
    if df is None or len(df) < span * 2 + 5:
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


# ---------------------------------------------------------------------
# DATA FETCH
# ---------------------------------------------------------------------
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
            response = requests.get(url, params=params, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if not data:
                    return None
                df = pd.DataFrame(
                    data, columns=["time", "low", "high", "open", "close", "volume"]
                )
                df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                df = df.sort_values("time").reset_index(drop=True)
                df = df[["time", "open", "high", "low", "close", "volume"]]
                if len(df) > limit:
                    df = df.iloc[-limit:].reset_index(drop=True)
                return df if not df.empty else None

            if response.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.6 * (attempt + 1))
                continue
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

    interval_map = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h"}
    interval = interval_map.get(timeframe, "1h")
    params = {"symbol": symbol, "interval": interval, "limit": max(50, limit)}

    try:
        response = requests.get(
            f"{CONFIG.BINANCE_BASE}/api/v3/klines", params=params, timeout=20
        )
        if response.status_code != 200:
            return None
        rows = []
        for kline in response.json():
            rows.append(
                {
                    "time": pd.to_datetime(kline[0], unit="ms", utc=True),
                    "open": float(kline[1]),
                    "high": float(kline[2]),
                    "low": float(kline[3]),
                    "close": float(kline[4]),
                    "volume": float(kline[5]),
                }
            )
        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        return df if not df.empty else None
    except Exception:
        return None


def fetch_data(
    exchange: str, pair: str, timeframe: str, limit: Optional[int] = None
) -> Optional[pd.DataFrame]:
    if limit is None:
        limit = get_bars_limit(timeframe)
    limit = max(1, min(300, limit))
    exchange_lower = exchange.lower()
    if exchange_lower.startswith("coinbase"):
        return fetch_coinbase_data(pair, timeframe, limit)
    if exchange_lower.startswith("binance"):
        return fetch_binance_data(pair, timeframe, limit)
    return fetch_coinbase_data(pair, timeframe, limit)


# ---------------------------------------------------------------------
# CACHED FETCH
# ---------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def get_cached_data(exchange: str, pair: str, timeframe: str) -> Optional[pd.DataFrame]:
    try:
        limit = get_bars_limit(timeframe)
        return fetch_data(exchange, pair, timeframe, limit)
    except Exception:
        return None


# ---------------------------------------------------------------------
# PRODUCT LISTING
# ---------------------------------------------------------------------
def get_coinbase_products(quote: str) -> List[str]:
    try:
        response = requests.get(f"{CONFIG.COINBASE_BASE}/products", timeout=25)
        response.raise_for_status()
        products = []
        for product in response.json():
            if (
                product.get("quote_currency") == quote.upper()
                and product.get("status") == "online"
                and not product.get("trading_disabled", False)
                and not product.get("cancel_only", False)
            ):
                pair = f"{product['base_currency']}-{product['quote_currency']}"
                products.append(pair)
        return sorted(products)
    except Exception:
        return []


def get_binance_products(quote: str) -> List[str]:
    try:
        response = requests.get(
            f"{CONFIG.BINANCE_BASE}/api/v3/exchangeInfo", timeout=25
        )
        response.raise_for_status()
        products = []
        quote_upper = quote.upper()
        for symbol in response.json().get("symbols", []):
            if (
                symbol.get("status") == "TRADING"
                and symbol.get("quoteAsset") == quote_upper
            ):
                pair = f"{symbol['baseAsset']}-{quote_upper}"
                products.append(pair)
        return sorted(products)
    except Exception:
        return []


def get_products(exchange: str, quote: str) -> List[str]:
    exchange_lower = exchange.lower()
    if exchange_lower.startswith("coinbase"):
        return get_coinbase_products(quote)
    if exchange_lower.startswith("binance"):
        return get_binance_products(quote)
    return get_coinbase_products(quote)


# ---------------------------------------------------------------------
# PROGRESSIVE STAGES + ALERTS
# ---------------------------------------------------------------------
def check_progressive_stages(df: pd.DataFrame, settings: dict) -> Dict[str, Any]:
    result = {
        "stage1_met": False,
        "stage1_bars_ago": None,
        "stage2_met": False,
        "stage2_bars_ago": None,
        "stage3_met": False,
        "current_pct": 0.0,
    }
    if df is None or len(df) < 10:
        return result

    macd_line, signal_line, hist = macd_core(
        df["close"],
        settings.get("macd_fast", 12),
        settings.get("macd_slow", 26),
        settings.get("macd_sig", 9),
    )

    bars_to_check = settings.get("macd_cross_bars", 5)
    for i in range(1, min(bars_to_check + 1, len(hist))):
        prev_diff = macd_line.iloc[-i - 1] - signal_line.iloc[-i - 1]
        curr_diff = macd_line.iloc[-i] - signal_line.iloc[-i]
        if prev_diff < 0 and curr_diff > 0:
            if macd_line.iloc[-i] < 0 and signal_line.iloc[-i] < 0:
                result["stage1_met"] = True
                result["stage1_bars_ago"] = i
                break

    hist_confirm = settings.get("macd_hist_confirm_bars", 3)
    for i in range(0, min(hist_confirm, len(hist))):
        if hist.iloc[-(i + 1)] > 0:
            result["stage2_met"] = True
            result["stage2_bars_ago"] = i
            break

    lookback = max(1, min(settings.get("lookback_candles", 3), len(df) - 1))
    current_close = float(df["close"].iloc[-1])

    if lookback > 1:
        window = df.iloc[-(lookback - 1) :].copy()
        lowest_low = float(window["low"].min())
    else:
        lowest_low = float(df["low"].iloc[-1])

    delta_pct = ((current_close - lowest_low) / lowest_low) * 100.0
    result["current_pct"] = delta_pct
    result["stage3_met"] = delta_pct >= settings.get("min_pct", 3.0)
    return result


def should_send_alert(
    pair: str, stage_check: dict, alert_mode: str, alerted_pairs: dict
) -> Tuple[bool, str]:
    if not alert_mode or alert_mode not in ["Conservative", "Balanced", "Aggressive"]:
        return False, ""
    pair_history = alerted_pairs.get(pair, {})
    if alert_mode == "Conservative":
        if (
            stage_check["stage1_met"]
            and stage_check["stage2_met"]
            and stage_check["stage3_met"]
        ):
            if not pair_history.get("stage3", False):
                return True, "stage3"
    elif alert_mode == "Balanced":
        if stage_check["stage1_met"]:
            if stage_check["stage3_met"] and not pair_history.get("stage3", False):
                return True, "stage3"
            if stage_check["stage2_met"] and not pair_history.get("stage2", False):
                return True, "stage2"
    elif alert_mode == "Aggressive":
        if stage_check["stage3_met"] and not pair_history.get("stage3", False):
            return True, "stage3"
        if stage_check["stage2_met"] and not pair_history.get("stage2", False):
            return True, "stage2"
        if stage_check["stage1_met"] and not pair_history.get("stage1", False):
            return True, "stage1"
    return False, ""


def send_email_alert(pairs_data: List[dict]) -> Tuple[bool, str]:
    try:
        smtp_host = st.secrets.get("email", {}).get("smtp_host", "smtp.gmail.com")
        smtp_port = st.secrets.get("email", {}).get("smtp_port", 587)
        sender_email = st.secrets.get("email", {}).get("sender_email")
        sender_password = st.secrets.get("email", {}).get("sender_password")
        recipient = st.session_state.get("email_to", "")
        if not all([sender_email, sender_password, recipient]):
            return False, "Email not configured"

        subject = f"🚀 {len(pairs_data)} Alert{'s' if len(pairs_data) > 1 else ''}"
        parts = []
        stage_names = {
            "stage1": "MACD Cross",
            "stage2": "Histogram+",
            "stage3": "Threshold Hit",
        }
        for data in pairs_data:
            parts.append(
                f"""{data['pair']} - {stage_names.get(data['stage'], data['stage'])}
Price: ${data['price']:.6f}
Change: {data['pct']:+.2f}%
Timeframe: {data['timeframe']}
Exchange: {data['exchange']}
Signal: {data['signal']}
"""
            )
        body = "\n---\n".join(parts)
        body += (
            f"\n\nTimestamp: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        body += "\n\nhioncrypto's Crypto Tracker"

        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return True, ""
    except Exception as e:
        return False, str(e)


def send_webhook_alert(pairs_data: List[dict]) -> Tuple[bool, str]:
    try:
        webhook_url = st.session_state.get("webhook_url", "")
        if not webhook_url:
            return False, "Webhook URL not set"
        payload = {
            "alerts": pairs_data,
            "count": len(pairs_data),
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code not in [200, 201, 202, 204]:
            return False, f"HTTP {response.status_code}"
        return True, ""
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------
# GATE EVALUATION
# ---------------------------------------------------------------------
def check_macd_cross(
    macd_line: pd.Series, signal_line: pd.Series, hist: pd.Series, settings: dict
) -> Tuple[bool, Optional[int]]:
    bars_to_check = settings.get("macd_cross_bars", 5)
    only_bull = settings.get("macd_cross_only_bull", True)
    need_below = settings.get("macd_cross_below_zero", True)
    confirm_bars = settings.get("macd_hist_confirm_bars", 3)
    for i in range(1, min(bars_to_check + 1, len(hist))):
        prev_diff = macd_line.iloc[-i - 1] - signal_line.iloc[-i - 1]
        curr_diff = macd_line.iloc[-i] - signal_line.iloc[-i]
        crossed_up = prev_diff < 0 and curr_diff > 0
        crossed_down = prev_diff > 0 and curr_diff < 0
        if only_bull and not crossed_up:
            continue
        if not only_bull and not (crossed_up or crossed_down):
            continue
        if need_below and (
            macd_line.iloc[-i] > 0 or signal_line.iloc[-i] > 0
        ):
            continue
        if confirm_bars > 0:
            conf_start = max(0, len(hist) - i)
            conf_end = min(len(hist), conf_start + confirm_bars)
            has_positive_hist = any(hist.iloc[j] > 0 for j in range(conf_start, conf_end))
            if not has_positive_hist:
                continue
        return True, i
    return False, None


def evaluate_gates(df: pd.DataFrame, settings: dict) -> Tuple[dict, int, str, int]:
    n = len(df)
    lookback = max(
        1, min(settings.get("lookback_candles", 3), 20, n - 1)
    )  # capped at 20
    current_close = float(df["close"].iloc[-1])

    if lookback > 1:
        window = df.iloc[-(lookback - 1) :].copy()
        lowest_low = float(window["low"].min())
    else:
        lowest_low = float(df["low"].iloc[-1])

    delta_pct = ((current_close - lowest_low) / lowest_low) * 100.0

    macd_line, signal_line, hist = macd_core(
        df["close"],
        settings.get("macd_fast", 12),
        settings.get("macd_slow", 26),
        settings.get("macd_sig", 9),
    )

    gates_passed = 0
    gates_enabled = 0
    gate_chips = []

    # Delta gate
    delta_pass = delta_pct >= settings.get("min_pct", 3.0)
    gates_passed += int(delta_pass)
    gates_enabled += 1
    gate_chips.append(f"Δ{'✅' if delta_pass else '❌'}({delta_pct:+.2f}%)")

    # Volume
    if settings.get("use_vol_spike", False):
        vol_spike_ratio = volume_spike(df, settings.get("vol_window", 20))
        vol_pass = (
            pd.notna(vol_spike_ratio)
            and vol_spike_ratio >= settings.get("vol_mult", 1.10)
        )
        gates_passed += int(vol_pass)
        gates_enabled += 1
        vol_display = (
            f"({vol_spike_ratio:.2f}×)" if pd.notna(vol_spike_ratio) else "(N/A)"
        )
        gate_chips.append(f" V{'✅' if vol_pass else '❌'}{vol_display}")
    else:
        gate_chips.append(" V–")

    # RSI
    if settings.get("use_rsi", False):
        rsi_values = rsi(df["close"], settings.get("rsi_len", 14))
        current_rsi = float(rsi_values.iloc[-1])
        rsi_pass = current_rsi >= settings.get("min_rsi", 55)
        gates_passed += int(rsi_pass)
        gates_enabled += 1
        gate_chips.append(f" S{'✅' if rsi_pass else '❌'}({current_rsi:.1f})")
    else:
        gate_chips.append(" S–")

    # MACD hist
    if settings.get("use_macd", False):
        macd_hist = float(hist.iloc[-1])
        macd_pass = macd_hist >= settings.get("min_mhist", 0.0)
        gates_passed += int(macd_pass)
        gates_enabled += 1
        gate_chips.append(f" M{'✅' if macd_pass else '❌'}({macd_hist:.3f})")
    else:
        gate_chips.append(" M–")

    # ATR
    if settings.get("use_atr", False):
        high_low = df["high"] - df["low"]
        high_close = abs(df["]()_
