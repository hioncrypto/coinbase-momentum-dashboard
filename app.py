# Enhanced Crypto Tracker by hioncrypto - Updated Version

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
# SIDEBAR RESIZE + FLOATING COLLAPSE ARROW (CSS + JS)
# ---------------------------------------------------------------------
st.markdown(
    """
<style>
:root {
    /* default sidebar width; user can resize between ~260-520px */
    --sidebar-width: 420px;
}

/* Sidebar uses CSS variable width */
section[data-testid="stSidebar"] {
    width: var(--sidebar-width) !important;
    min-width: var(--sidebar-width) !important;
    max-width: var(--sidebar-width) !important;
    overflow: hidden !important;
}

/* Inner sidebar scrolls; full viewport height */
section[data-testid="stSidebar"] > div:first-child {
    height: 100vh !important;
    overflow-y: auto !important;
}

/* Main area takes the rest of the width */
[data-testid="stAppViewContainer"] .main {
    max-width: 100vw !important;
}

/* Resizer bar between sidebar and main */
#sidebar-resizer {
    position: fixed;
    top: 0;
    bottom: 0;
    left: var(--sidebar-width);
    width: 6px;
    cursor: col-resize;
    z-index: 998;
    background: transparent;
}

/* Floating collapse/expand arrow */
[data-testid="collapsedControl"] {
    position: fixed !important;
    top: 0.75rem;
    left: calc(var(--sidebar-width) - 28px);
    z-index: 999;
}

/* Make all sidebar widgets use full width */
section[data-testid="stSidebar"] .element-container,
section[data-testid="stSidebar"] .stMarkdown,
section[data-testid="stSidebar"] .row-widget,
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"],
section[data-testid="stSidebar"] .stButton,
section[data-testid="stSidebar"] .stButton > button,
section[data-testid="stSidebar"] .stSelectbox,
section[data-testid="stSidebar"] .stSlider,
section[data-testid="stSidebar"] .stNumberInput,
section[data-testid="stSidebar"] .stTextInput,
section[data-testid="stSidebar"] .stTextArea,
section[data-testid="stSidebar"] .stRadio,
section[data-testid="stSidebar"] .stCheckbox {
    width: 100% !important;
}

/* Main container padding */
[data-testid="stAppViewContainer"] > .main > div.block-container {
    max-width: 100vw !important;
    padding-left: 12px !important;
    padding-right: 12px !important;
}

/* Dataframe clarity */
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
    :root {
        --sidebar-width: 300px;
    }

    section[data-testid="stSidebar"] {
        width: var(--sidebar-width) !important;
        min-width: var(--sidebar-width) !important;
        max-width: var(--sidebar-width) !important;
    }

    #sidebar-resizer {
        display: none;
    }

    .stDataFrame { font-size: 11px; }
    [data-testid="stMetricValue"] { font-size: 18px; }
    [data-testid="stMetricLabel"] { font-size: 11px; }
    .block-container { padding: 0.5rem; }

    [data-testid="collapsedControl"] {
        left: 0.5rem;
    }
}
</style>

<div id="sidebar-resizer"></div>

<script>
(function() {
    const root = document.documentElement;
    const resizer = document.getElementById("sidebar-resizer");
    if (!resizer) return;

    let startX = 0;
    let startWidth = 0;
    let dragging = false;

    function getSidebarWidth() {
        const styles = getComputedStyle(root);
        const w = styles.getPropertyValue("--sidebar-width").trim();
        return parseInt(w.replace("px","")) || 360;
    }

    resizer.addEventListener("mousedown", function(e) {
        dragging = true;
        startX = e.clientX;
        startWidth = getSidebarWidth();
        document.body.style.userSelect = "none";
    });

    window.addEventListener("mousemove", function(e) {
        if (!dragging) return;
        const dx = e.clientX - startX;
        let newWidth = startWidth + dx;

        if (newWidth < 260) newWidth = 260;
        if (newWidth > 520) newWidth = 520;

        root.style.setProperty("--sidebar-width", newWidth + "px");
    });

    window.addEventListener("mouseup", function() {
        if (!dragging) return;
        dragging = false;
        document.body.style.userSelect = "";
    });
})();
</script>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------
# PYTHON IMPORTS & CONSTANTS
# ---------------------------------------------------------------------
import json
import time
import datetime as dt
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from streamlit_autorefresh import st_autorefresh  # noqa: F401
except ImportError:
    st_autorefresh = None

try:
    import websocket  # type: ignore

    WS_AVAILABLE = True
except ImportError:  # pragma: no cover
    WS_AVAILABLE = False


class Config:
    COINBASE_BASE = "https://api.exchange.coinbase.com"
    BINANCE_BASE = "https://api.binance.com"
    COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"

    TIMEFRAMES = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}
    QUOTES = ["USD", "USDC", "USDT", "BTC", "ETH", "EUR"]
    EXCHANGES = ["Coinbase", "Binance", "Kraken (coming soon)", "KuCoin (coming soon)"]

    ALERT_FILE = Path("/tmp/alerted_pairs.json")


CONFIG = Config()

# ---------------------------------------------------------------------
# URL PARAM HELPERS
# ---------------------------------------------------------------------
URL_PARAM_MAP = {
    "exchange": "ex",
    "quote": "q",
    "pairs_to_discover": "ptd",
    "mode": "md",
    "ws_chunk": "wsc",
    "sort_tf": "tf",
    "sort_desc": "sd",
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
    "alert_mode": "am",
    "email_to": "et",
    "webhook_url": "wu",
    "font_scale": "fs",
    "refresh_sec": "rs",
    "do_ath": "da",
    "basis": "bs",
    "amount_daily": "ad",
    "amount_hourly": "ah",
    "amount_weekly": "aw",
    "lr_enabled": "lre",
    "lr_watch_coinbase": "lrwc",
    "lr_watch_binance": "lrwb",
    "lr_watch_quotes": "lrwq",
    "lr_poll_sec": "lrps",
    "lr_upcoming_window_h": "lruwh",
    "lr_feeds": "lrf",
    "use_watch": "uw",
    "use_my_pairs": "ump",
    "watchlist": "wl",
    "my_pairs": "myp",
}


def save_to_url(key: str, value: Any) -> None:
    try:
        param_name = URL_PARAM_MAP.get(key, key)
        st.query_params[param_name] = str(value)
    except Exception:
        pass


def load_from_url(key: str, default_value: Any, value_type=str):
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
# ALERTED PAIRS FILE
# ---------------------------------------------------------------------
def load_alerted_pairs() -> dict:
    try:
        if CONFIG.ALERT_FILE.exists():
            with open(CONFIG.ALERT_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_alerted_pairs(pairs: dict) -> None:
    try:
        with open(CONFIG.ALERT_FILE, "w") as f:
            json.dump(pairs, f)
    except Exception:
        pass


def clear_alerted_pairs() -> None:
    try:
        if CONFIG.ALERT_FILE.exists():
            CONFIG.ALERT_FILE.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------
# SESSION STATE INITIALIZATION (STICKY DEFAULTS)
# ---------------------------------------------------------------------
def init_session_state() -> None:
    if "_initialized" in st.session_state:
        return

    defaults = {
        "exchange": "Coinbase",
        "quote": "USD",
        "pairs_to_discover": 400,
        "mode": "REST only",
        "ws_chunk": 5,
        "sort_tf": "1h",
        "sort_desc": True,
        "min_bars": 10,  # <= 20 (new cap)
        "lookback_candles": 3,  # <= 20 (new cap)
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
        "alert_mode": "",
        "email_to": "",
        "webhook_url": "",
        "font_scale": 1.0,
        "refresh_sec": 30,
        "do_ath": False,
        "basis": "Daily",
        "amount_daily": 90,
        "amount_hourly": 24,
        "amount_weekly": 12,
        "collapse_all": False,
        "use_watch": False,
        "use_my_pairs": False,
        "watchlist": "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD",
        "my_pairs": "",
        "ws_thread": None,
        "ws_alive": False,
        "ws_prices": {},
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
        "last_update": 0,
    }

    for key, default in defaults.items():
        st.session_state[key] = load_from_url(key, default, type(default))

    st.session_state["_initialized"] = True


init_session_state()

# ---------------------------------------------------------------------
# TECHNICAL INDICATORS
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
        if values[i] > values[i - span : i].max() and values[i] > values[i + 1 : i + 1 + span].max():
            highs.append(i)
        if values[i] < values[i - span : i].min() and values[i] < values[i + 1 : i + 1 + span].min():
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
# DATA FETCHING
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
        response = requests.get(f"{CONFIG.BINANCE_BASE}/api/v3/klines", params=params, timeout=20)
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


def fetch_data(exchange: str, pair: str, timeframe: str, limit: Optional[int] = None):
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
        products: List[str] = []
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
        response = requests.get(f"{CONFIG.BINANCE_BASE}/api/v3/exchangeInfo", timeout=25)
        response.raise_for_status()
        products: List[str] = []
        quote_upper = quote.upper()
        for symbol in response.json().get("symbols", []):
            if symbol.get("status") == "TRADING" and symbol.get("quoteAsset") == quote_upper:
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
# PROGRESSIVE ALERT LOGIC
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
        if stage_check["stage1_met"] and stage_check["stage2_met"] and stage_check["stage3_met"]:
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


# ---------------------------------------------------------------------
# ALERT SENDING
# ---------------------------------------------------------------------
def send_email_alert(pairs_data: List[dict]) -> Tuple[bool, str]:
    try:
        email_cfg = st.secrets.get("email", {})
        smtp_host = email_cfg.get("smtp_host", "smtp.gmail.com")
        smtp_port = email_cfg.get("smtp_port", 587)
        sender_email = email_cfg.get("sender_email")
        sender_password = email_cfg.get("sender_password")
        recipient = st.session_state.get("email_to", "")
        if not all([sender_email, sender_password, recipient]):
            return False, "Email not configured"

        subject = f"🚀 {len(pairs_data)} Alert{'s' if len(pairs_data) > 1 else ''}"
        parts = []
        stage_names = {"stage1": "MACD Cross", "stage2": "Histogram+", "stage3": "Threshold Hit"}
        for data in pairs_data:
            parts.append(
                f"""\n{data['pair']} - {stage_names.get(data['stage'], data['stage'])}
Price: ${data['price']:.6f}
Change: {data['pct']:+.2f}%
Timeframe: {data['timeframe']}
Exchange: {data['exchange']}
Signal: {data['signal']}
"""
            )
        body = "\n---\n".join(parts)
        body += f"\n\nTimestamp: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
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
    except Exception as e:  # pragma: no cover
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
    except Exception as e:  # pragma: no cover
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
        if need_below and (macd_line.iloc[-i] > 0 or signal_line.iloc[-i] > 0):
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
    lookback = max(1, min(settings.get("lookback_candles", 3), 100, n - 1))

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
    gate_chips: List[str] = []

    # Delta gate (always on)
    delta_pass = delta_pct >= settings.get("min_pct", 3.0)
    gates_passed += int(delta_pass)
    gates_enabled += 1
    gate_chips.append(f"Δ{'✅' if delta_pass else '❌'}({delta_pct:+.2f}%)")

    if settings.get("use_vol_spike", False):
        vol_spike_ratio = volume_spike(df, settings.get("vol_window", 20))
        vol_pass = pd.notna(vol_spike_ratio) and vol_spike_ratio >= settings.get("vol_mult", 1.10)
        gates_passed += int(vol_pass)
        gates_enabled += 1
        vol_display = f"({vol_spike_ratio:.2f}×)" if pd.notna(vol_spike_ratio) else "(N/A)"
        gate_chips.append(f" V{'✅' if vol_pass else '❌'}{vol_display}")
    else:
        gate_chips.append(" V–")

    if settings.get("use_rsi", False):
        rsi_values = rsi(df["close"], settings.get("rsi_len", 14))
        current_rsi = float(rsi_values.iloc[-1])
        rsi_pass = current_rsi >= settings.get("min_rsi", 55)
        gates_passed += int(rsi_pass)
        gates_enabled += 1
        gate_chips.append(f" S{'✅' if rsi_pass else '❌'}({current_rsi:.1f})")
    else:
        gate_chips.append(" S–")

    if settings.get("use_macd", False):
        macd_hist = float(hist.iloc[-1])
        macd_pass = macd_hist >= settings.get("min_mhist", 0.0)
        gates_passed += int(macd_pass)
        gates_enabled += 1
        gate_chips.append(f" M{'✅' if macd_pass else '❌'}({macd_hist:.3f})")
    else:
        gate_chips.append(" M–")

    if settings.get("use_atr", False):
        high_low = df["high"] - df["low"]
        high_close = abs(df["high"] - df["close"].shift())
        low_close = abs(df["low"] - df["close"].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr_values = true_range.rolling(window=settings.get("atr_len", 14)).mean()
        current_atr = float(atr_values.iloc[-1]) if not atr_values.empty else 0
        atr_pct = (current_atr / current_close * 100) if current_close > 0 else 0
        atr_pass = atr_pct >= settings.get("min_atr", 0.5)
        gates_passed += int(atr_pass)
        gates_enabled += 1
        gate_chips.append(f" A{'✅' if atr_pass else '❌'}({atr_pct:.2f}%)")
    else:
        gate_chips.append(" A–")

    if settings.get("use_trend", False):
        trend_pass = trend_breakout_up(
            df, settings.get("pivot_span", 4), settings.get("trend_within", 48)
        )
        gates_passed += int(trend_pass)
        gates_enabled += 1
        gate_chips.append(f" T{'✅' if trend_pass else '❌'}")
    else:
        gate_chips.append(" T–")

    if settings.get("use_roc", False):
        if lookback > 1:
            ref_close = float(df["close"].iloc[-(lookback - 1)])
        else:
            ref_close = float(df["close"].iloc[-1])
        roc = ((current_close / ref_close) - 1.0) * 100.0 if n > lookback else np.nan
        roc_pass = pd.notna(roc) and roc >= settings.get("min_roc", 1.0)
        gates_passed += int(roc_pass)
        gates_enabled += 1
        roc_display = f"({roc:+.2f}%)" if pd.notna(roc) else "(N/A)"
        gate_chips.append(f" R{'✅' if roc_pass else '❌'}{roc_display}")
    else:
        gate_chips.append(" R–")

    cross_info = {"ok": False, "bars_ago": None}
    if settings.get("use_macd_cross", False):
        cross_pass, bars_ago = check_macd_cross(macd_line, signal_line, hist, settings)
        cross_info.update({"ok": cross_pass, "bars_ago": bars_ago})
        gates_passed += int(cross_pass)
        gates_enabled += 1
        cross_display = f" ({bars_ago} bars ago)" if bars_ago is not None else ""
        gate_chips.append(f" C{'✅' if cross_pass else '❌'}{cross_display}")
    else:
        gate_chips.append(" C–")

    metadata = {"delta_pct": delta_pct, "macd_cross": cross_info}
    return metadata, gates_passed, " ".join(gate_chips), gates_enabled


# ---------------------------------------------------------------------
# SIDEBAR UI
# ---------------------------------------------------------------------
def expander(title: str):
    expanded = not st.session_state.get("collapse_all", False)
    return st.sidebar.expander(title, expanded=expanded)


with st.sidebar:
    st.title("🚀 Crypto Tracker")

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("Collapse All", use_container_width=True, key="collapse_btn"):
            st.session_state["collapse_all"] = True
            st.rerun()
    with c2:
        if st.button("Expand All", use_container_width=True, key="expand_btn"):
            st.session_state["collapse_all"] = False
            st.rerun()
    with c3:
        use_my_pairs = st.toggle("⭐ My Pairs", key="use_my_pairs")
        if use_my_pairs != load_from_url("use_my_pairs", False, bool):
            save_to_url("use_my_pairs", use_my_pairs)

    with st.popover("Manage My Pairs"):
        st.caption("Comma-separated (e.g., BTC-USD, ETH-USDT)")
        current = st.text_area("Edit list", st.session_state.get("my_pairs", ""))
        if st.button("Save My Pairs"):
            st.session_state["my_pairs"] = ", ".join(
                [p.strip().upper() for p in current.split(",") if p.strip()]
            )
            save_to_url("my_pairs", st.session_state["my_pairs"])
            st.success("Saved!")

    with expander("Market Settings"):
        new_exch = st.selectbox(
            "Exchange",
            CONFIG.EXCHANGES,
            index=CONFIG.EXCHANGES.index(st.session_state["exchange"])
            if st.session_state["exchange"] in CONFIG.EXCHANGES
            else 0,
            key="exchange_widget",
        )
        if new_exch != st.session_state.get("exchange"):
            st.session_state["exchange"] = new_exch
            save_to_url("exchange", new_exch)

        new_quote = st.selectbox(
            "Quote Currency",
            CONFIG.QUOTES,
            index=CONFIG.QUOTES.index(st.session_state["quote"])
            if st.session_state["quote"] in CONFIG.QUOTES
            else 0,
            key="quote_widget",
        )
        if new_quote != st.session_state.get("quote"):
            st.session_state["quote"] = new_quote
            save_to_url("quote", new_quote)

        new_use_watch = st.checkbox(
            "Use watchlist only",
            value=st.session_state.get("use_watch", False),
            key="use_watch_widget",
        )
        if new_use_watch != st.session_state.get("use_watch"):
            st.session_state["use_watch"] = new_use_watch
            save_to_url("use_watch", new_use_watch)

    with expander("Watchlist"):
        st.caption("Monitor specific pairs")
        current_watchlist = st.text_area(
            "Watchlist pairs",
            st.session_state.get(
                "watchlist", "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD"
            ),
            key="watchlist_edit",
        )
        if st.button("Update Watchlist"):
            cleaned = ", ".join(
                [p.strip().upper() for p in current_watchlist.split(",") if p.strip()]
            )
            st.session_state["watchlist"] = cleaned
            save_to_url("watchlist", cleaned)
            st.success("Updated!")
            st.rerun()

    if st.session_state.get("use_my_pairs", False):
        avail_pairs = [
            p.strip().upper()
            for p in st.session_state.get("my_pairs", "").split(",")
            if p.strip()
        ]
    elif st.session_state.get("use_watch", False):
        avail_pairs = [
            p.strip().upper()
            for p in st.session_state.get("watchlist", "").split(",")
            if p.strip()
        ]
    else:
        effective_exchange = (
            "Coinbase"
            if "coming soon" in st.session_state["exchange"].lower()
            else st.session_state["exchange"]
        )
        avail_pairs = get_products(effective_exchange, st.session_state["quote"])
    avail_count = len(avail_pairs)

    st.sidebar.subheader("Discover Settings")
    ptd = st.sidebar.slider(
        f"Pairs to discover{f' (Available: {avail_count})' if avail_count else ''}",
        min_value=5,
        max_value=500,
        step=5,
        value=int(st.session_state.get("pairs_to_discover", 400)),
        key="ui_pairs_to_discover",
    )
    if ptd != st.session_state.get("pairs_to_discover"):
        st.session_state["pairs_to_discover"] = int(ptd)
        save_to_url("pairs_to_discover", ptd)

with expander("Mode & Timeframes"):
    new_mode = st.radio(
        "Data Source",
        ["REST only", "WebSocket + REST"],
        index=0 if st.session_state["mode"] == "REST only" else 1,
        key="mode_widget",
    )
    if new_mode != st.session_state.get("mode"):
        st.session_state["mode"] = new_mode
        save_to_url("mode", new_mode)

    new_ws_chunk = st.slider(
        "WebSocket chunk size",
        2,
        20,
        value=int(st.session_state.get("ws_chunk", 5)),
        step=1,
        key="ws_chunk_widget",
    )
    if new_ws_chunk != st.session_state.get("ws_chunk"):
        st.session_state["ws_chunk"] = new_ws_chunk
        save_to_url("ws_chunk", new_ws_chunk)

    timeframe_options = ["5m", "15m", "1h", "4h"]
    current_tf_index = (
        timeframe_options.index(st.session_state.get("sort_tf", "1h"))
        if st.session_state.get("sort_tf") in timeframe_options
        else 2
    )
    new_tf = st.selectbox(
        "Sort Timeframe",
        timeframe_options,
        index=current_tf_index,
        key="sort_tf_widget",
    )
    if new_tf != st.session_state.get("sort_tf"):
        st.session_state["sort_tf"] = new_tf
        save_to_url("sort_tf", new_tf)

    new_sort_desc = st.toggle(
        "Sort Descending",
        value=st.session_state.get("sort_desc", True),
        key="sort_desc_widget",
    )
    if new_sort_desc != st.session_state.get("sort_desc"):
        st.session_state["sort_desc"] = new_sort_desc
        save_to_url("sort_desc", new_sort_desc)

with expander("Gates"):
    presets = ["Spike Hunter", "Early MACD Cross", "Confirm Rally", "hioncrypto's Velocity Mode", "None"]
    current_preset_idx = (
        presets.index(st.session_state.get("preset", "None"))
        if st.session_state.get("preset") in presets
        else 4
    )
    new_preset = st.radio(
        "Preset",
        presets,
        index=current_preset_idx,
        key="preset_widget",
        horizontal=True,
    )
    if new_preset != st.session_state.get("preset"):
        st.session_state["preset"] = new_preset
        save_to_url("preset", new_preset)
        if new_preset == "Spike Hunter":
            st.session_state.update(
                {
                    "use_vol_spike": True,
                    "vol_mult": 1.10,
                    "use_rsi": False,
                    "use_macd": False,
                    "use_trend": False,
                    "use_roc": False,
                    "use_macd_cross": False,
                }
            )
        elif new_preset == "Early MACD Cross":
            st.session_state.update(
                {
                    "use_vol_spike": True,
                    "vol_mult": 1.10,
                    "use_rsi": True,
                    "min_rsi": 50,
                    "use_macd": True,
                    "use_macd_cross": True,
                    "macd_cross_bars": 1,
                    "macd_cross_only_bull": True,
                    "macd_hist_confirm_bars": 3,
                }
            )
        elif new_preset == "Confirm Rally":
            st.session_state.update(
                {
                    "use_vol_spike": True,
                    "vol_mult": 1.20,
                    "use_rsi": True,
                    "min_rsi": 60,
                    "use_macd": True,
                    "use_trend": True,
                }
            )
        elif new_preset == "hioncrypto's Velocity Mode":
            st.session_state.update(
                {
                    "use_vol_spike": True,
                    "vol_mult": 2.5,
                    "use_roc": True,
                    "min_roc": 5.0,
                    "use_macd_cross": True,
                    "macd_cross_bars": 3,
                    "K_green": 2,
                    "Y_yellow": 1,
                }
            )

    st.markdown("**Δ (Delta) gate is always active.** Other gates optional.")

    new_lookback = st.slider(
        "Δ lookback (candles)",
        1,
        20,  # NEW MAX 20
        value=int(st.session_state["lookback_candles"]),
        step=1,
        key="lookback_widget",
    )
    if new_lookback != st.session_state.get("lookback_candles"):
        st.session_state["lookback_candles"] = new_lookback
        save_to_url("lookback_candles", new_lookback)

    new_min_pct = st.slider(
        "Min +% change (Δ gate)",
        0.0,
        50.0,
        value=float(st.session_state["min_pct"]),
        step=0.5,
        key="min_pct_widget",
    )
    if new_min_pct != st.session_state.get("min_pct"):
        st.session_state["min_pct"] = new_min_pct
        save_to_url("min_pct", new_min_pct)

    new_min_bars = st.slider(
        "Min rows (bars)",
        1,
        20,  # NEW MAX 20
        value=int(st.session_state.get("min_bars", 10)),
        step=1,
        key="min_bars_widget",
    )
    if new_min_bars != st.session_state.get("min_bars"):
        st.session_state["min_bars"] = new_min_bars
        save_to_url("min_bars", new_min_bars)

    c1, c2, c3 = st.columns(3)
    with c1:
        new_use_vol = st.toggle("Volume spike", key="use_vol_spike")
        if new_use_vol != load_from_url("use_vol_spike", False, bool):
            save_to_url("use_vol_spike", new_use_vol)
        if st.session_state.get("use_vol_spike"):
            new_vm = st.slider(
                "Spike multiple",
                1.0,
                20.0,  # NEW MAX 20
                value=float(st.session_state.get("vol_mult", 1.10)),
                step=0.05,
                key="vol_mult",
            )
            if new_vm != st.session_state.get("vol_mult"):
                st.session_state["vol_mult"] = new_vm
                save_to_url("vol_mult", new_vm)
    with c2:
        new_use_rsi = st.toggle("RSI", key="use_rsi")
        if new_use_rsi != load_from_url("use_rsi", False, bool):
            save_to_url("use_rsi", new_use_rsi)
        if st.session_state.get("use_rsi"):
            new_mr = st.slider(
                "Min RSI",
                40,
                90,
                value=int(st.session_state.get("min_rsi", 55)),
                step=1,
                key="min_rsi",
            )
            if new_mr != st.session_state.get("min_rsi"):
                st.session_state["min_rsi"] = new_mr
                save_to_url("min_rsi", new_mr)
    with c3:
        new_use_macd = st.toggle("MACD hist", key="use_macd")
        if new_use_macd != load_from_url("use_macd", False, bool):
            save_to_url("use_macd", new_use_macd)
        if st.session_state.get("use_macd"):
            new_mh = st.slider(
                "Min MACD hist",
                0.0,
                2.0,
                value=float(st.session_state.get("min_mhist", 0.0)),
                step=0.05,
                key="min_mhist",
            )
            if new_mh != st.session_state.get("min_mhist"):
                st.session_state["min_mhist"] = new_mh
                save_to_url("min_mhist", new_mh)

    c4, c5, c6 = st.columns(3)
    with c4:
        new_use_atr = st.toggle("ATR %", key="use_atr")
        if new_use_atr != load_from_url("use_atr", False, bool):
            save_to_url("use_atr", new_use_atr)
        if st.session_state.get("use_atr"):
            new_ma = st.slider(
                "Min ATR %",
                0.0,
                10.0,
                value=float(st.session_state.get("min_atr", 0.5)),
                step=0.1,
                key="min_atr",
            )
            if new_ma != st.session_state.get("min_atr"):
                st.session_state["min_atr"] = new_ma
                save_to_url("min_atr", new_ma)
    with c5:
        new_use_trend = st.toggle("Trend breakout", key="use_trend")
        if new_use_trend != load_from_url("use_trend", False, bool):
            save_to_url("use_trend", new_use_trend)
        if st.session_state.get("use_trend"):
            new_ps = st.slider(
                "Pivot span",
                2,
                10,
                value=int(st.session_state.get("pivot_span", 4)),
                step=1,
                key="pivot_span",
            )
            st.session_state["pivot_span"] = new_ps
            save_to_url("pivot_span", new_ps)

            new_tw = st.slider(
                "Breakout within",
                5,
                96,
                value=int(st.session_state.get("trend_within", 48)),
                step=1,
                key="trend_within",
            )
            st.session_state["trend_within"] = new_tw
            save_to_url("trend_within", new_tw)
    with c6:
        new_use_roc = st.toggle("ROC", key="use_roc")
        if new_use_roc != load_from_url("use_roc", False, bool):
            save_to_url("use_roc", new_use_roc)
        if st.session_state.get("use_roc"):
            new_mro = st.slider(
                "Min ROC %",
                0.0,
                50.0,
                value=float(st.session_state.get("min_roc", 1.0)),
                step=0.5,
                key="min_roc",
            )
            if new_mro != st.session_state.get("min_roc"):
                st.session_state["min_roc"] = new_mro
                save_to_url("min_roc", new_mro)

    st.markdown("**MACD Cross (early entry)**")
    c7, c8, c9, c10 = st.columns(4)
    with c7:
        new_umc = st.toggle("Enable", key="use_macd_cross")
        if new_umc != load_from_url("use_macd_cross", False, bool):
            save_to_url("use_macd_cross", new_umc)
    with c8:
        if st.session_state.get("use_macd_cross"):
            new_mcb = st.slider(
                "Cross within",
                1,
                10,
                value=int(st.session_state.get("macd_cross_bars", 5)),
                step=1,
                key="macd_cross_bars",
            )
            st.session_state["macd_cross_bars"] = new_mcb
            save_to_url("macd_cross_bars", new_mcb)
    with c9:
        if st.session_state.get("use_macd_cross"):
            mco = st.toggle("Bullish only", key="macd_cross_only_bull")
            st.session_state["macd_cross_only_bull"] = mco
            save_to_url("macd_cross_only_bull", mco)
    with c10:
        if st.session_state.get("use_macd_cross"):
            mcbz = st.toggle(
                "Below zero",
                key="macd_cross_below_zero",
            )
            st.session_state["macd_cross_below_zero"] = mcbz
            save_to_url("macd_cross_below_zero", mcbz)

    if st.session_state.get("use_macd_cross"):
        mhcb = st.slider(
            "Histogram > 0 within",
            0,
            10,
            value=int(st.session_state.get("macd_hist_confirm_bars", 3)),
            step=1,
            key="macd_hist_confirm_bars",
        )
        st.session_state["macd_hist_confirm_bars"] = mhcb
        save_to_url("macd_hist_confirm_bars", mhcb)

    st.markdown("---")
    gate_modes = ["ALL", "ANY", "Custom (K/Y)"]
    current_mode_idx = (
        gate_modes.index(st.session_state.get("gate_mode", "ANY"))
        if st.session_state.get("gate_mode") in gate_modes
        else 1
    )
    new_gm = st.radio(
        "Gate Mode",
        gate_modes,
        index=current_mode_idx,
        key="gate_mode_widget",
        horizontal=True,
    )
    if new_gm != st.session_state.get("gate_mode"):
        st.session_state["gate_mode"] = new_gm
        save_to_url("gate_mode", new_gm)

    new_hf = st.toggle("Hard filter (hide non-passers)", key="hard_filter")
    if new_hf != load_from_url("hard_filter", False, bool):
        st.session_state["hard_filter"] = new_hf
        save_to_url("hard_filter", new_hf)

    if st.session_state.get("gate_mode") == "Custom (K/Y)":
        st.subheader("Color rules")
        kg = st.selectbox(
            "Gates for green (K)",
            list(range(1, 8)),
            index=int(st.session_state.get("K_green", 3)) - 1,
            key="K_green",
        )
        st.session_state["K_green"] = kg
        save_to_url("K_green", kg)

        yy = st.selectbox(
            "Yellow needs ≥ Y (< K)",
            list(range(0, kg)),
            index=min(int(st.session_state.get("Y_yellow", 2)), max(0, kg - 1)),
            key="Y_yellow",
        )
        st.session_state["Y_yellow"] = yy
        save_to_url("Y_yellow", yy)

with expander("🎯 Alert Strategy"):
    alert_modes = ["Conservative", "Balanced", "Aggressive"]
    current_mode = st.session_state.get("alert_mode", "")
    mode_index = alert_modes.index(current_mode) if current_mode in alert_modes else 0
    new_alert_mode = st.radio(
        "Alert Mode",
        alert_modes,
        index=mode_index,
        key="alert_mode_widget",
    )
    if new_alert_mode != st.session_state.get("alert_mode"):
        st.session_state["alert_mode"] = new_alert_mode
        save_to_url("alert_mode", new_alert_mode)
    if st.session_state.get("alert_mode"):
        st.info(f"✅ Alerts active in {st.session_state['alert_mode']} mode")

with expander("🔔 Notifications"):
    new_email = st.text_input(
        "Email recipient",
        value=st.session_state.get("email_to", ""),
        key="email_to_widget",
    )
    if new_email != st.session_state.get("email_to", ""):
        st.session_state["email_to"] = new_email
        save_to_url("email_to", new_email)

    new_webhook = st.text_input(
        "Webhook URL",
        value=st.session_state.get("webhook_url", ""),
        key="webhook_url_widget",
    )
    if new_webhook != st.session_state.get("webhook_url", ""):
        st.session_state["webhook_url"] = new_webhook
        save_to_url("webhook_url", new_webhook)

with expander("Display"):
    new_fs = st.slider(
        "Font size",
        0.8,
        1.6,
        value=float(st.session_state.get("font_scale", 1.0)),
        step=0.05,
        key="font_scale",
    )
    if new_fs != st.session_state.get("font_scale"):
        st.session_state["font_scale"] = new_fs
        save_to_url("font_scale", new_fs)

    new_rs = st.slider(
        "Auto-refresh (seconds)",
        5,
        120,
        value=int(st.session_state.get("refresh_sec", 30)),
        step=1,
        key="refresh_sec",
    )
    if new_rs != st.session_state.get("refresh_sec"):
        st.session_state["refresh_sec"] = new_rs
        save_to_url("refresh_sec", new_rs)

with expander("Listing Radar"):
    new_lre = st.toggle("Enable Listing Radar", key="lr_enabled")
    if new_lre != load_from_url("lr_enabled", False, bool):
        st.session_state["lr_enabled"] = new_lre
        save_to_url("lr_enabled", new_lre)
    if st.session_state.get("lr_enabled"):
        c1, c2 = st.columns(2)
        with c1:
            wc = st.toggle(
                "Watch Coinbase",
                key="lr_watch_coinbase",
                value=st.session_state.get("lr_watch_coinbase", True),
            )
            st.session_state["lr_watch_coinbase"] = wc
            save_to_url("lr_watch_coinbase", wc)
        with c2:
            wb = st.toggle(
                "Watch Binance",
                key="lr_watch_binance",
                value=st.session_state.get("lr_watch_binance", True),
            )
            st.session_state["lr_watch_binance"] = wb
            save_to_url("lr_watch_binance", wb)

        wq = st.text_input(
            "Watch quotes",
            st.session_state.get("lr_watch_quotes", "USD, USDT, USDC"),
            key="lr_watch_quotes",
        )
        st.session_state["lr_watch_quotes"] = wq
        save_to_url("lr_watch_quotes", wq)

        ps = st.slider(
            "Poll interval (seconds)",
            10,
            300,
            st.session_state.get("lr_poll_sec", 30),
            5,
            key="lr_poll_sec",
        )
        st.session_state["lr_poll_sec"] = ps
        save_to_url("lr_poll_sec", ps)

        uw = st.slider(
            "Upcoming window (hours)",
            1,
            168,
            st.session_state.get("lr_upcoming_window_h", 48),
            1,
            key="lr_upcoming_window_h",
        )
        st.session_state["lr_upcoming_window_h"] = uw
        save_to_url("lr_upcoming_window_h", uw)

        lf = st.text_area(
            "News feeds (URLs)",
            st.session_state.get("lr_feeds", ""),
            key="lr_feeds",
        )
        st.session_state["lr_feeds"] = lf
        save_to_url("lr_feeds", lf)

# ---------------------------------------------------------------------
# MAIN BODY
# ---------------------------------------------------------------------
st.title("🚀 hioncrypto's: Crypto Tracker")

col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    if st.button("🔄 Refresh Now", type="primary"):
        get_cached_data.clear()
        st.session_state["ws_prices"] = {}
        st.rerun()
with col2:
    if st.button("🧹 Clear Cache"):
        get_cached_data.clear()
        st.session_state["ws_prices"] = {}
        st.session_state["ws_alive"] = False
        st.rerun()
with col3:
    is_ws_active = st.session_state.get("ws_alive", False)
    ws_symbol = "🟢" if is_ws_active else "🔴"
    st.caption(
        f"WebSocket: {ws_symbol} | Pairs in cache: {len(st.session_state.get('ws_prices', {}))}"
    )

if st.session_state["use_my_pairs"]:
    pairs = [
        p.strip().upper()
        for p in st.session_state.get("my_pairs", "").split(",")
        if p.strip()
    ]
elif st.session_state["use_watch"]:
    pairs = [
        p.strip().upper()
        for p in st.session_state["watchlist"].split(",")
        if p.strip()
    ]
else:
    effective_exchange = (
        "Coinbase"
        if "coming soon" in st.session_state["exchange"].lower()
        else st.session_state["exchange"]
    )
    pairs = get_products(effective_exchange, st.session_state["quote"])

cap = max(5, min(500, st.session_state.get("pairs_to_discover", 400)))
pairs = pairs[:cap]

gate_settings = {
    "lookback_candles": int(st.session_state.get("lookback_candles", 3)),
    "min_pct": float(st.session_state.get("min_pct", 3.0)),
    "use_vol_spike": bool(st.session_state.get("use_vol_spike", False)),
    "vol_mult": float(st.session_state.get("vol_mult", 1.10)),
    "vol_window": int(st.session_state.get("vol_window", 20)),
    "use_rsi": bool(st.session_state.get("use_rsi", False)),
    "rsi_len": int(st.session_state.get("rsi_len", 14)),
    "min_rsi": int(st.session_state.get("min_rsi", 55)),
    "use_macd": bool(st.session_state.get("use_macd", False)),
    "macd_fast": int(st.session_state.get("macd_fast", 12)),
    "macd_slow": int(st.session_state.get("macd_slow", 26)),
    "macd_sig": int(st.session_state.get("macd_sig", 9)),
    "min_mhist": float(st.session_state.get("min_mhist", 0.0)),
    "use_atr": bool(st.session_state.get("use_atr", False)),
    "atr_len": int(st.session_state.get("atr_len", 14)),
    "min_atr": float(st.session_state.get("min_atr", 0.5)),
    "use_trend": bool(st.session_state.get("use_trend", False)),
    "pivot_span": int(st.session_state.get("pivot_span", 4)),
    "trend_within": int(st.session_state.get("trend_within", 48)),
    "use_roc": bool(st.session_state.get("use_roc", False)),
    "min_roc": float(st.session_state.get("min_roc", 1.0)),
    "use_macd_cross": bool(st.session_state.get("use_macd_cross", False)),
    "macd_cross_bars": int(st.session_state.get("macd_cross_bars", 5)),
    "macd_cross_only_bull": bool(st.session_state.get("macd_cross_only_bull", True)),
    "macd_cross_below_zero": bool(st.session_state.get("macd_cross_below_zero", True)),
    "macd_hist_confirm_bars": int(st.session_state.get("macd_hist_confirm_bars", 3)),
}

rows: List[Dict[str, Any]] = []
alerts_to_send: List[dict] = []
sort_tf = st.session_state["sort_tf"]
mode = st.session_state["gate_mode"]
hard_filter = st.session_state["hard_filter"]
k_required = st.session_state.get("K_green", 3)
y_required = st.session_state.get("Y_yellow", 2)
alert_mode = st.session_state.get("alert_mode", "")
effective_exchange = (
    "Coinbase"
    if "coming soon" in st.session_state["exchange"].lower()
    else st.session_state["exchange"]
)
alerted_pairs = load_alerted_pairs()

if pairs:
    status_placeholder = st.empty()
    progress_placeholder = st.empty()
    for i, pair in enumerate(pairs):
        progress = (i + 1) / len(pairs)
        progress_placeholder.progress(progress)
        status_placeholder.text(f"Processing {pair}... ({i + 1}/{len(pairs)})")

        df = get_cached_data(effective_exchange, pair, sort_tf)
        if df is None or df.empty or len(df) < st.session_state["min_bars"]:
            continue

        meta, passed, chips, enabled = evaluate_gates(df, gate_settings)

        if mode == "ALL":
            include = enabled > 0 and passed == enabled
            is_green = include
            is_yellow = 0 < passed < enabled and passed >= enabled - 1
        elif mode == "ANY":
            include = True
            is_green = passed >= 1
            is_yellow = False
        else:
            include = True
            is_green = passed >= k_required
            is_yellow = (not is_green) and (passed >= y_required)

        if hard_filter:
            if mode in {"ALL", "ANY"} and not include:
                continue
            if mode == "Custom (K/Y)" and not (is_green or is_yellow):
                continue

        ws_price = st.session_state.get("ws_prices", {}).get(pair)
        last_price = float(ws_price) if ws_price else float(df["close"].iloc[-1])
        pct_change = meta["delta_pct"]

        signal = ""
        if is_green:
            signal = "Strong Buy"
        elif is_yellow:
            signal = "Watch"

        row_data = {
            "Pair": pair,
            "Price": f"${last_price:.6f}",
            f"% Change ({sort_tf})": pct_change,
            "Signal": signal,
            "Gates": chips,
            "_passed": passed,
            "_enabled": enabled,
            "_green": is_green,
            "_yellow": is_yellow,
            "_ws_active": ws_price is not None,
        }
        rows.append(row_data)

        if alert_mode and is_green:
            stage_check = check_progressive_stages(df, gate_settings)
            should_alert, stage_name = should_send_alert(
                pair, stage_check, alert_mode, alerted_pairs
            )
            if should_alert:
                alerts_to_send.append(
                    {
                        "pair": pair,
                        "price": last_price,
                        "pct": pct_change,
                        "timeframe": sort_tf,
                        "exchange": effective_exchange,
                        "signal": signal,
                        "stage": stage_name,
                    }
                )
                if pair not in alerted_pairs:
                    alerted_pairs[pair] = {}
                alerted_pairs[pair][stage_name] = True

    progress_placeholder.empty()
    status_placeholder.empty()

    if alerts_to_send and rows:
        temp_df = pd.DataFrame(rows)
        chg_col = f"% Change ({sort_tf})"
        temp_df = temp_df.sort_values(chg_col, ascending=False)
        min_pct_threshold = st.session_state["min_pct"]
        top_10_pairs = (
            temp_df[(temp_df["_green"] == True) & (temp_df[chg_col] >= min_pct_threshold)]  # noqa: E712
            .head(10)["Pair"]
            .tolist()
        )
        alerts_to_send = [a for a in alerts_to_send if a["pair"] in top_10_pairs]

    save_alerted_pairs(alerted_pairs)

    if alerts_to_send:
        if st.session_state.get("email_to"):
            send_email_alert(alerts_to_send)
        if st.session_state.get("webhook_url"):
            send_webhook_alert(alerts_to_send)

    st.success(f"✅ Processed {len(rows)} pairs successfully!")

if rows:
    df_results = pd.DataFrame(rows)
    chg_col = f"% Change ({sort_tf})"
    ascending = not st.session_state["sort_desc"]
    df_results = df_results.sort_values(chg_col, ascending=ascending).reset_index(drop=True)
    df_results.insert(0, "#", range(1, len(df_results) + 1))

    green_count = df_results["_green"].sum()
    yellow_count = df_results["_yellow"].sum()
    total_count = len(df_results)
    max_pct = df_results[chg_col].max() if not df_results.empty else 0

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Pairs", total_count)
    with c2:
        st.metric("Strong Buy", green_count)
    with c3:
        st.metric("Watch", yellow_count)
    with c4:
        st.metric("Max % Change", f"{max_pct:.2f}%")

    st.subheader("🔥 Top 10 Opportunities")
    min_pct = st.session_state["min_pct"]
    top_10_filtered = df_results[df_results[chg_col] >= min_pct].head(10).copy()
    top_10_filtered.reset_index(drop=True, inplace=True)
    if "#" in top_10_filtered.columns:
        top_10_filtered = top_10_filtered.drop(columns=["#"])
    top_10_filtered.insert(0, "Rank", range(1, len(top_10_filtered) + 1))

    if not top_10_filtered.empty:

        def style_top10_rows(row):
            idx = row.name
            if (
                "_green" in top_10_filtered.columns
                and top_10_filtered.iloc[idx]["_green"]
            ):
                return [
                    "background-color: #16a34a; color: white; font-weight: 600"
                ] * len(row)
            if (
                "_yellow" in top_10_filtered.columns
                and top_10_filtered.iloc[idx]["_yellow"]
            ):
                return ["background-color: #eab308; color: black"] * len(row)
            return [""] * len(row)

        display_cols = [c for c in top_10_filtered.columns if not c.startswith("_")]
        styled_df = top_10_filtered[display_cols].style.apply(
            style_top10_rows, axis=1
        )
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        st.info(f"ℹ️ No pairs exceed {min_pct:.1f}% threshold.")

    col1, col2 = st.columns([3, 1])
    with col1:
        show_all = st.checkbox("Show all pairs", value=not hard_filter)
    with col2:
        sort_option = st.selectbox("Sort by", ["% Change", "Signal", "Pair"], index=0)

    if not show_all:
        display_df = df_results[df_results["_green"] | df_results["_yellow"]]
    else:
        display_df = df_results

    if sort_option == "Signal":
        display_df = display_df.sort_values(
            ["_green", "_yellow"], ascending=[False, False]
        )
    elif sort_option == "Pair":
        display_df = display_df.sort_values("Pair")

    if not display_df.empty:
        display_cols = [c for c in display_df.columns if not c.startswith("_")]
        final_display = display_df[display_cols].reset_index(drop=True)

        def style_all_rows(row):
            if row.name < len(display_df):
                original_idx = display_df.index[row.name]
                if display_df.loc[original_idx, "_green"]:
                    return [
                        "background-color: #16a34a; color: white; font-weight: 600"
                    ] * len(row)
                if display_df.loc[original_idx, "_yellow"]:
                    return ["background-color: #eab308; color: black"] * len(row)
            return [""] * len(row)

        styled_all = final_display.style.apply(style_all_rows, axis=1)
        st.dataframe(
            styled_all,
            use_container_width=True,
            hide_index=True,
            height=600,
        )
    else:
        st.info("No pairs match filters.")
else:
    st.info("No pairs found. Adjust settings.")

if (
    st.session_state["mode"].startswith("WebSocket")
    and effective_exchange == "Coinbase"
    and WS_AVAILABLE
):
    if not st.session_state.get("ws_alive", False) and pairs:
        ws_pairs = pairs[: st.session_state["ws_chunk"]]

        def ws_worker(product_ids):
            try:
                ws = websocket.WebSocket()
                ws.connect(CONFIG.COINBASE_WS, timeout=10)
                ws.settimeout(1.0)
                subscribe_msg = {
                    "type": "subscribe",
                    "channels": [{"name": "ticker", "product_ids": product_ids}],
                }
                ws.send(json.dumps(subscribe_msg))
                st.session_state["ws_alive"] = True
                while st.session_state.get("ws_alive", False):
                    try:
                        message = ws.recv()
                        if message:
                            data = json.loads(message)
                            if data.get("type") == "ticker":
                                product_id = data.get("product_id")
                                price = data.get("price")
                                if product_id and price:
                                    st.session_state["ws_prices"][product_id] = float(
                                        price
                                    )
                    except websocket.WebSocketTimeoutException:
                        continue
                    except Exception:
                        break
            except Exception:
                pass
            finally:
                st.session_state["ws_alive"] = False
                try:
                    ws.close()
                except Exception:
                    pass

        if not st.session_state.get("ws_thread") or not st.session_state[
            "ws_thread"
        ].is_alive():
            ws_thread = threading.Thread(
                target=ws_worker, args=(ws_pairs,), daemon=True
            )
            st.session_state["ws_thread"] = ws_thread
            ws_thread.start()

current_time = int(time.time())
time_since_update = current_time - st.session_state["last_update"]
refresh_interval = st.session_state["refresh_sec"]
if time_since_update >= refresh_interval:
    st.session_state["last_update"] = current_time
    st.rerun()

st.markdown(
    f"""
<div style="position: fixed; top: 10px; right: 10px; background: rgba(0,0,0,0.7); color: white; padding: 5px 10px; border-radius: 15px; font-size: 12px; z-index: 1000;">
    🔄 Next: {max(0, refresh_interval - time_since_update)}s
</div>
""",
    unsafe_allow_html=True,
)

st.markdown("---")
st.caption("🚀 Enhanced Crypto Tracker with Progressive Alerts — by hioncrypto")
