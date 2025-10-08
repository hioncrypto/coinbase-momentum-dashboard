# Enhanced Crypto Tracker by hioncrypto
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
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    /* Keep sidebar toggle button floating/fixed while scrolling */
    [data-testid="collapsedControl"] {
        position: fixed !important;
        top: 1rem;
        left: 1rem;
        z-index: 999;
    }
    
  /* Force sidebar header to stay at top */
    section[data-testid="stSidebar"] > div {
        position: relative !important;
    }
    
    section[data-testid="stSidebar"] > div > div:first-child {
        position: sticky !important;
        top: 0 !important;
        z-index: 1000 !important;
        background: #262730 !important;
    } 
    
    /* Mobile-friendly adjustments */
    @media (max-width: 768px) {
        .stDataFrame { font-size: 11px; }
        [data-testid="stMetricValue"] { font-size: 18px; }
        [data-testid="stMetricLabel"] { font-size: 11px; }
        .block-container { padding: 0.5rem; }
    }
    </style>
    """, unsafe_allow_html=True)
import json
import time
import datetime as dt
import threading
import queue
import ssl
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Tuple, Dict, Any

import numpy as np
import pandas as pd
import requests
import streamlit.components.v1 as components
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from datetime import datetime
# Track alerted pairs to avoid spam
if 'alerted_pairs' not in st.session_state:
    st.session_state.alerted_pairs = set()
# Optional dependencies
try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

try:
    import websocket
    WS_AVAILABLE = True
except ImportError:
    # Track alerted pairs to avoid spam
    WS_AVAILABLE = False

# =============================================================================
# CONFIGURATION & CONSTANTS
# =============================================================================

class Config:
    """Application configuration"""
    COINBASE_BASE = "https://api.exchange.coinbase.com"
    BINANCE_BASE = "https://api.binance.com"
    COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"
    
    TIMEFRAMES = {"15m": 900, "1h": 3600}
    QUOTES = ["USD", "USDC", "USDT", "BTC", "ETH", "EUR"]
    EXCHANGES = ["Coinbase", "Binance", "Kraken (coming soon)", "KuCoin (coming soon)"]

CONFIG = Config()

# =============================================================================
# STREAMLIT PAGE SETUP
# =============================================================================


# Custom CSS
st.markdown("""
<style>
[data-testid="stAppViewContainer"] > .main > div.block-container {
    max-width: 100vw !important;
    padding-left: 12px !important;
    padding-right: 12px !important;
}

div[data-testid="stDataFrame"],
div[data-testid="stDataFrame"] *,
div[data-testid="stDataEditor"],
div[data-testid="stDataEditor"] * {
    opacity: 1 !important;
    filter: none !important;
    transition: none !important;
    animation: none !important;
}

section[data-testid="stSidebar"],
section[data-testid="stSidebar"] * {
    pointer-events: auto !important;
    opacity: 1 !important;
    z-index: 999;
}

.row-green {
    background-color: #16a34a !important;
    color: white !important;
    font-weight: 600;
}

.row-yellow {
    background-color: #eab308 !important;
    color: black !important;
}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# STATE MANAGEMENT
# =============================================================================

def init_session_state():
    """Initialize session state variables - only sets defaults if not present"""
    
    # Mark initialization and load URL params ONLY on first run
    if "_initialized" not in st.session_state:
        st.session_state["_initialized"] = True
        
        # Load discover_cap from URL first (only on initial load)
        if "discover_cap" in st.query_params:
            try:
                st.session_state["discover_cap"] = int(st.query_params["discover_cap"])
            except:
                pass
    
    # Define defaults
    defaults = {
        # Market settings
        "exchange": "Coinbase",
        "quote": "USD",
        "discover_cap": 400,
        
        # Mode
        "mode": "REST only",
        "ws_chunk": 5,
        
        # Timeframes
        "sort_tf": "1h",
        "sort_desc": True,
        "min_bars": 1,
        
        # Gates
        "lookback_candles": 3,
        "min_pct": 3.0,
        "use_vol_spike": True,
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
        "use_macd_cross": True,
        "macd_cross_bars": 5,
        "macd_cross_only_bull": True,
        "macd_cross_below_zero": True,
        "macd_hist_confirm_bars": 3,
        "gate_mode": "ANY",
        "hard_filter": False,
        "K_green": 3,
        "Y_yellow": 2,
        "preset": "Spike Hunter",
        
        # Display
        "font_scale": 1.0,
        "refresh_sec": 30,
        "email_to": "",
        "webhook_url": "",
        
        # ATH/ATL
        "do_ath": False,
        "basis": "Daily",
        "amount_daily": 90,
        "amount_hourly": 24,
        "amount_weekly": 12,
        
        # UI state
        "collapse_all": False,
        
        # WebSocket
        "ws_thread": None,
        "ws_alive": False,
        "ws_prices": {},
        
        # Alerts
        "alerted_pairs": set(),
        
        # Listing Radar
        "lr_enabled": False,
        "lr_baseline": {"Coinbase": set(), "Binance": set()},
        "lr_events": [],
        "lr_unacked": 0,
    }
    
    # CRITICAL: Only set defaults for keys that DON'T exist
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    # CRITICAL: Only set defaults for keys that DON'T exist
    # This preserves user changes across refreshes
for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

# Initialize state
init_session_state()

# CRITICAL DEBUG - Check if values persist after init
if "min_pct" in st.session_state and st.session_state["min_pct"] != 3.0:
    st.warning(f"⚠️ min_pct was changed to {st.session_state['min_pct']} but may reset")

# =============================================================================
# TECHNICAL INDICATORS
# =============================================================================   
# =============================================================================
# TECHNICAL INDICATORS            
    st.session_state[key] = value

# Initialize state
init_session_state()
# Initialize state
init_session_state()

# =============================================================================
# TECHNICAL INDICATORS
# =============================================================================

def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential Moving Average"""
    return series.astype("float64").ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Relative Strength Index"""
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    
    ru = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rd = pd.Series(dn, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    
    rs = ru / (rd + 1e-12)
    return 100 - 100 / (1 + rs)

def macd_core(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD indicator"""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def volume_spike(df: pd.DataFrame, window: int = 20) -> float:
    """Calculate volume spike ratio"""
    if len(df) < window + 1:
        return np.nan
    
    current_vol = df["volume"].iloc[-1]
    avg_vol = df["volume"].rolling(window).mean().iloc[-1]
    
    return float(current_vol / (avg_vol + 1e-12))

def find_pivots(close: pd.Series, span: int = 3) -> Tuple[List[int], List[int]]:
    """Find pivot highs and lows"""
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
    """Detect upward trend breakout"""
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

# =============================================================================
# DATA FETCHING
# =============================================================================

def get_bars_limit(timeframe: str) -> int:
    """Get appropriate number of bars for timeframe"""
    limits = {"15m": 96, "1h": 48}
    return limits.get(timeframe, 24)

def fetch_coinbase_data(pair: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
    """Fetch data from Coinbase API"""
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
                
                df = pd.DataFrame(data, columns=["time", "low", "high", "open", "close", "volume"])
                df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                df = df.sort_values("time").reset_index(drop=True)
                df = df[["time", "open", "high", "low", "close", "volume"]]
                
                if len(df) > limit:
                    df = df.iloc[-limit:].reset_index(drop=True)
                
                return df if not df.empty else None
            
            elif response.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.6 * (attempt + 1))
                continue
            else:
                return None
                
        except Exception:
            time.sleep(0.4 * (attempt + 1))
    
    return None

def fetch_binance_data(pair: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
    """Fetch data from Binance API"""
    try:
        base, quote = pair.split("-")
        symbol = f"{base}{quote}"
    except ValueError:
        return None
    
    interval = "15m" if timeframe == "15m" else "1h"
    params = {"symbol": symbol, "interval": interval, "limit": max(50, limit)}
    
    try:
        response = requests.get(f"{CONFIG.BINANCE_BASE}/api/v3/klines", params=params, timeout=20)
        
        if response.status_code != 200:
            return None
        
        rows = []
        for kline in response.json():
            rows.append({
                "time": pd.to_datetime(kline[0], unit="ms", utc=True),
                "open": float(kline[1]),
                "high": float(kline[2]),
                "low": float(kline[3]),
                "close": float(kline[4]),
                "volume": float(kline[5])
            })
        
        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        return df if not df.empty else None
        
    except Exception:
        return None

def fetch_data(exchange: str, pair: str, timeframe: str, limit: Optional[int] = None) -> Optional[pd.DataFrame]:
    """Fetch data from specified exchange"""
    if limit is None:
        limit = get_bars_limit(timeframe)
    
    limit = max(1, min(300, limit))
    exchange_lower = exchange.lower()
    
    if exchange_lower.startswith("coinbase"):
        return fetch_coinbase_data(pair, timeframe, limit)
    elif exchange_lower.startswith("binance"):
        return fetch_binance_data(pair, timeframe, limit)
    else:
        return fetch_coinbase_data(pair, timeframe, limit)

# =============================================================================
# CACHING WITH FORCED REFRESH
# =============================================================================


# derive TTL from the Auto-refresh slider dynamically
_refresh_ttl = int(max(5, st.session_state.get("refresh_sec", 15)))

@st.cache_data(show_spinner=False, ttl=_refresh_ttl)
def get_cached_data(exchange: str, pair: str, timeframe: str) -> Optional[pd.DataFrame]:
    """Cached data fetching function — TTL follows the Auto-refresh slider."""
    try:
        limit = get_bars_limit(timeframe)
        return fetch_data(exchange, pair, timeframe, limit)
    except Exception as e:
        st.error(f"Error fetching data for {pair}: {e}")
        return None

# clear the cache so TTL changes take effect immediately


# Add a manual refresh button for user control
col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    if st.button("🔄 Refresh Now", type="primary"):
        get_cached_data.clear()
        st.session_state["ws_prices"] = {}  # Clear WebSocket prices too
        st.rerun()

with col2:
    if st.button("🧹 Clear Cache"):
        get_cached_data.clear()
        st.session_state.clear()  # Clear all session state
        st.rerun()

with col3:
    # Show real-time status
    is_ws_active = st.session_state.get("ws_alive", False)
    ws_symbol = "🟢" if is_ws_active else "🔴"
    st.caption(f"WebSocket: {ws_symbol} | Pairs in cache: {len(st.session_state.get('ws_prices', {}))}")

# =============================================================================
# PRODUCT LISTING
# =============================================================================

def get_coinbase_products(quote: str) -> List[str]:
    """Get Coinbase trading pairs for quote currency"""
    try:
        response = requests.get(f"{CONFIG.COINBASE_BASE}/products", timeout=25)
        response.raise_for_status()
        
        products = []
        for product in response.json():
            if product.get("quote_currency") == quote.upper() and product.get("status") == "online" and not product.get("trading_disabled", False) and not product.get("cancel_only", False):
                pair = f"{product['base_currency']}-{product['quote_currency']}"
                products.append(pair)
        
        return sorted(products)
    except Exception:
        return []

def get_binance_products(quote: str) -> List[str]:
    """Get Binance trading pairs for quote currency"""
    try:
        response = requests.get(f"{CONFIG.BINANCE_BASE}/api/v3/exchangeInfo", timeout=25)
        response.raise_for_status()
        
        products = []
        quote_upper = quote.upper()
        
        for symbol in response.json().get("symbols", []):
            if (symbol.get("status") == "TRADING" and 
                symbol.get("quoteAsset") == quote_upper):
                pair = f"{symbol['baseAsset']}-{quote_upper}"
                products.append(pair)
        
        return sorted(products)
    except Exception:
        return []

def get_products(exchange: str, quote: str) -> List[str]:
    """Get products for specified exchange and quote"""
    exchange_lower = exchange.lower()
    
    if exchange_lower.startswith("coinbase"):
        return get_coinbase_products(quote)
    elif exchange_lower.startswith("binance"):
        return get_binance_products(quote)
    else:
        return get_coinbase_products(quote)

# =============================================================================
# GATE EVALUATION
# =============================================================================

def check_macd_cross(macd_line: pd.Series, signal_line: pd.Series, 
                    hist: pd.Series, settings: dict) -> Tuple[bool, Optional[int]]:
    """Check for MACD cross signal"""
    bars_to_check = settings.get("macd_cross_bars", 5)
    only_bull = settings.get("macd_cross_only_bull", True)
    need_below = settings.get("macd_cross_below_zero", True)
    confirm_bars = settings.get("macd_hist_confirm_bars", 3)
    
    for i in range(1, min(bars_to_check + 1, len(hist))):
        prev_diff = macd_line.iloc[-i-1] - signal_line.iloc[-i-1]
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
    """Evaluate all gates for a given dataframe and settings"""
    n = len(df)
    lookback = max(1, min(settings.get("lookback_candles", 3), 100, n - 1))
    
    last_close = float(df["close"].iloc[-1])
    ref_close = float(df["close"].iloc[-lookback])
    delta_pct = (last_close / ref_close - 1.0) * 100.0
    
    macd_line, signal_line, hist = macd_core(
        df["close"], 
        settings.get("macd_fast", 12), 
        settings.get("macd_slow", 26), 
        settings.get("macd_sig", 9)
    )
    
    gates_passed = 0
    gates_enabled = 0
    gate_chips = []
    
    # Delta gate (always enabled, show pass/fail status)
    delta_pass = delta_pct >= settings.get("min_pct", 3.0)
    gates_passed += int(delta_pass)
    gates_enabled += 1
    gate_chips.append(f"Δ{'✅' if delta_pass else '❌'}({delta_pct:+.2f}%)")
    
    # Volume spike gate
    if settings.get("use_vol_spike", True):
        vol_spike_ratio = volume_spike(df, settings.get("vol_window", 20))
        vol_pass = pd.notna(vol_spike_ratio) and vol_spike_ratio >= settings.get("vol_mult", 1.10)
        gates_passed += int(vol_pass)
        gates_enabled += 1
        vol_display = f"({vol_spike_ratio:.2f}×)" if pd.notna(vol_spike_ratio) else "(N/A)"
        gate_chips.append(f" V{'✅' if vol_pass else '❌'}{vol_display}")
    else:
        gate_chips.append(" V–")
    
    # RSI gate
    if settings.get("use_rsi", False):
        rsi_values = rsi(df["close"], settings.get("rsi_len", 14))
        current_rsi = float(rsi_values.iloc[-1])
        rsi_pass = current_rsi >= settings.get("min_rsi", 55)
        gates_passed += int(rsi_pass)
        gates_enabled += 1
        gate_chips.append(f" S{'✅' if rsi_pass else '❌'}({current_rsi:.1f})")
    else:
        gate_chips.append(" S–")
    
    # MACD histogram gate
    if settings.get("use_macd", False):
        macd_hist = float(hist.iloc[-1])
        macd_pass = macd_hist >= settings.get("min_mhist", 0.0)
        gates_passed += int(macd_pass)
        gates_enabled += 1
        gate_chips.append(f" M{'✅' if macd_pass else '❌'}({macd_hist:.3f})")
    else:
        gate_chips.append(" M–")
    
    # ATR gate
    if settings.get("use_atr", False):
        # Calculate ATR manually
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift())
        low_close = abs(df['low'] - df['close'].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr_values = true_range.rolling(window=settings.get("atr_len", 14)).mean()
        
        current_atr = float(atr_values.iloc[-1]) if not atr_values.empty else 0
        atr_pct = (current_atr / last_close * 100) if last_close > 0 else 0
        atr_pass = atr_pct >= settings.get("min_atr", 0.5)
        gates_passed += int(atr_pass)
        gates_enabled += 1
        gate_chips.append(f" A{'✅' if atr_pass else '❌'}({atr_pct:.2f}%)")
    else:
        gate_chips.append(" A–")
    
    # Trend breakout gate
    if settings.get("use_trend", False):
        trend_pass = trend_breakout_up(
            df, settings.get("pivot_span", 4), settings.get("trend_within", 48)
        )
        gates_passed += int(trend_pass)
        gates_enabled += 1
        gate_chips.append(f" T{'✅' if trend_pass else '❌'}")
    else:
        gate_chips.append(" T–")
    
    # ROC gate
    if settings.get("use_roc", False):
        roc = (df["close"].iloc[-1] / df["close"].iloc[-lookback] - 1.0) * 100.0 if n > lookback else np.nan
        roc_pass = pd.notna(roc) and roc >= settings.get("min_roc", 1.0)
        gates_passed += int(roc_pass)
        gates_enabled += 1
        roc_display = f"({roc:+.2f}%)" if pd.notna(roc) else "(N/A)"
        gate_chips.append(f" R{'✅' if roc_pass else '❌'}{roc_display}")
    else:
        gate_chips.append(" R–")
    
    # MACD Cross gate
    cross_info = {"ok": False, "bars_ago": None}
    if settings.get("use_macd_cross", True):
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

# =============================================================================
# SIDEBAR CONTROLS
# =============================================================================

def expander(title: str):
    """Create sidebar expander with collapse/expand state"""
    return st.sidebar.expander(title, expanded=not st.session_state.get("collapse_all", False))

def expander(title: str):
    """Create sidebar expander with collapse/expand state - no refresh on state change"""
    expanded = not st.session_state.get("collapse_all", False)
    return st.sidebar.expander(title, expanded=expanded)

# Sidebar header with improved collapse/expand logic
with st.sidebar:
    st.title("🚀 Crypto Tracker")
    
    # Track previous collapse state to detect changes
    prev_collapse_state = st.session_state.get("_prev_collapse_state", None)
    current_collapse_state = st.session_state.get("collapse_all", False)
    
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("Collapse All", use_container_width=True, key="collapse_btn"):
            st.session_state["collapse_all"] = True
            st.session_state["_ui_only_change"] = True  # Mark as UI-only change
    with c2:
        if st.button("Expand All", use_container_width=True, key="expand_btn"):
            st.session_state["collapse_all"] = False
            st.session_state["_ui_only_change"] = True  # Mark as UI-only change
    with c3:
        st.toggle("⭐ My Pairs Only", key="use_my_pairs")

    # Store current state for next comparison
    st.session_state["_prev_collapse_state"] = current_collapse_state

    # My Pairs management
    with st.popover("Manage My Pairs"):
        st.caption("Comma-separated (e.g., BTC-USD, ETH-USDT)")
        current = st.text_area("Edit list", st.session_state.get("my_pairs", ""))
        if st.button("Save My Pairs"):
            st.session_state["my_pairs"] = ", ".join([p.strip().upper() for p in current.split(",") if p.strip()])
            st.success("Saved!")

    with expander("Market Settings"):
        exchanges_list = ["Coinbase", "Binance", "Kraken (coming soon)", "KuCoin (coming soon)"]
        quotes_list = ["USD", "USDC", "USDT", "BTC", "ETH", "EUR"]
    
        st.selectbox("Exchange", exchanges_list, 
                key="exchange")
    
        st.selectbox("Quote Currency", quotes_list,  
                key="quote")
    
        st.checkbox("Use watchlist only", key="use_watch", 
                value=st.session_state.get("use_watch", False))

    # Watchlist Management (separate from My Pairs)
    with expander("Watchlist"):
        st.caption("Watchlist is different from 'My Pairs'. Use this for broader monitoring.")
        current_watchlist = st.text_area(
        "Watchlist pairs", 
        st.session_state.get("watchlist", "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD"),
        key="watchlist_edit",
        help="Comma-separated pairs like BTC-USD, ETH-USDT"
    )
    
    if st.button("Update Watchlist"):
        cleaned = ", ".join([p.strip().upper() for p in current_watchlist.split(",") if p.strip()])
        st.session_state["watchlist"] = cleaned
        st.success("Watchlist updated!")
        st.rerun()

    # Calculate available pairs
    if st.session_state.get("use_my_pairs", False):
        avail_pairs = [p.strip().upper() for p in st.session_state.get("my_pairs", "").split(",") if p.strip()]
    elif st.session_state.get("use_watch", False):
        avail_pairs = [p.strip().upper() for p in st.session_state.get("watchlist", "").split(",") if p.strip()]
    else:
        effective_exchange = "Coinbase" if "coming soon" in st.session_state["exchange"].lower() else st.session_state["exchange"]
        avail_pairs = get_products(effective_exchange, st.session_state["quote"])
    
   # ---------------- Sidebar › Discover (sticky) ----------------
# Unique key: "pairs_to_discover"  (do NOT reuse "discover_cap")

# One-time init from URL ?ptd=... else default=100
if "pairs_to_discover" not in st.session_state:
    try:
        qv = st.query_params.get("ptd")
    except Exception:
        qv = st.experimental_get_query_params().get("ptd", [None])[0]
    try:
        st.session_state.pairs_to_discover = int(qv)
    except Exception:
        st.session_state.pairs_to_discover = 100
    st.session_state.pairs_to_discover = int(min(500, max(5, st.session_state.pairs_to_discover)))


# Persist to URL on change
try:
    st.query_params["ptd"] = str(ptd)
except Exception:
 
    
    # Calculate available pairs
    if st.session_state["use_watch"] and st.session_state.get("watchlist", "").strip():
        avail_pairs = [p.strip().upper() for p in st.session_state["watchlist"].split(",") if p.strip()]
        avail_pairs = [p for p in avail_pairs if p.endswith(f"-{st.session_state['quote']}")]
    elif st.session_state.get("use_my_pairs", False):
        avail_pairs = [p.strip().upper() for p in st.session_state.get("my_pairs", "").split(",") if p.strip()]
        avail_pairs = [p for p in avail_pairs if p.endswith(f"-{st.session_state['quote']}")]
    else:
        effective_exchange = "Coinbase" if "coming soon" in st.session_state["exchange"].lower() else st.session_state["exchange"]
        avail_pairs = get_products(effective_exchange, st.session_state["quote"])
    
    
    
    if st.session_state["use_my_pairs"]:
        pairs_pool = [p.strip().upper() for p in st.session_state.get("my_pairs", "").split(",") if p.strip()]
        pairs_pool = [p for p in pairs_pool if p.endswith(f"-{st.session_state['quote']}")]
    elif st.session_state["use_watch"]:
        pairs_pool = [p.strip().upper() for p in st.session_state.get("watchlist", "").split(",") if p.strip()]
        pairs_pool = [p for p in pairs_pool if p.endswith(f"-{st.session_state['quote']}")]
    else:
        effective_exchange = "Coinbase" if "coming soon" in st.session_state["exchange"].lower() else st.session_state["exchange"]
        pairs_pool = get_products(effective_exchange, st.session_state["quote"])
    
 # compute a safe available count for the label
avail_count = len(locals().get("avail_pairs", locals().get("pairs_pool", [])))

# ---------------- Sidebar › Discover ----------------
st.sidebar.subheader("Discover Settings")

# compute available pairs count if list exists
avail_count = len(locals().get("avail_pairs", locals().get("pairs_pool", [])))

# one-time init from ?ptd= or fallback
if "pairs_to_discover" not in st.session_state:
    qp = (getattr(st, "query_params", {}) or {}).get("ptd")
    if qp is None:
        qp = st.experimental_get_query_params().get("ptd", [None])[0]
    try:
        st.session_state.pairs_to_discover = int(qp)
    except Exception:
        st.session_state.pairs_to_discover = 100
    st.session_state.pairs_to_discover = int(
        min(500, max(5, st.session_state.pairs_to_discover))
    )

# single sticky slider
ptd = st.sidebar.slider(
    f"Pairs to discover{f' (Available: {avail_count})' if avail_count else ''}",
    min_value=5,
    max_value=500,
    step=5,
    value=st.session_state.pairs_to_discover,
    key="ui_pairs_to_discover",   # unique widget key
    help="Persists via URL ?ptd= and session state."
)

# sync UI value back into sticky state
st.session_state.pairs_to_discover = int(ptd)

# persist to URL (place immediately after the slider)
value_to_persist = int(st.session_state.get("pairs_to_discover", 100))
try:
    st.query_params["ptd"] = str(value_to_persist)
except Exception:
    st.experimental_set_query_params(ptd=str(value_to_persist))

    st.session_state.pairs_to_discover = int(min(500, max(5, st.session_state.pairs_to_discover)))



# persist to URL and drop any old param like discover_cap
try:
    st.query_params.clear()
    st.query_params["ptd"] = str(ptd)
except Exception:
    st.experimental_set_query_params(ptd=str(ptd))


# Save to URL when value changes
# Mode Settings
with expander("Mode & Timeframes"):
    st.radio("Data Source", ["REST only", "WebSocket + REST"], key="mode")
    st.slider("WebSocket chunk size", 2, 20, st.session_state["ws_chunk"], key="ws_chunk")
    
    st.selectbox("Sort Timeframe", ["5m", "15m", "1h"], 
                key="sort_tf")
    st.toggle("Sort Descending", key="sort_desc")

# Gates Settings
    with expander("Gates"):
        presets = ["Spike Hunter", "Early MACD Cross", "Confirm Rally", "hioncrypto's Velocity Mode", "None"]
        st.radio("Preset", presets,
         key="preset", 
         horizontal=True,
         help="Quick filter configurations: Spike Hunter (fast momentum), Early MACD Cross (trend reversals), Confirm Rally (strict multi-gate), Velocity Mode (explosive moves), None (manual)")
        
        st.markdown("**Tips:** Gate Mode 'ALL' requires every enabled gate. 'ANY' needs at least one. "
                   "'Custom (K/Y)' colors rows based on how many gates pass (K=green, Y=yellow).")
        
        # Apply presets ONLY when selection changes
        if "_last_preset" not in st.session_state:
            st.session_state["_last_preset"] = st.session_state["preset"]
        
        if st.session_state["preset"] != st.session_state["_last_preset"]:
            st.session_state["_last_preset"] = st.session_state["preset"]
            
            # NOW apply the preset (only when it changes)
            if st.session_state["preset"] == "Spike Hunter":
                st.session_state.update({
                    "use_vol_spike": True, "vol_mult": 1.10, "use_rsi": False, "use_macd": False,
                    "use_trend": False, "use_roc": False, "use_macd_cross": False
                })
            elif st.session_state["preset"] == "Early MACD Cross":
                st.session_state.update({
                    "use_vol_spike": True, "vol_mult": 1.10, "use_rsi": True, "min_rsi": 50,
                    "use_macd": False, "use_trend": False, "use_roc": False, "use_macd_cross": True,
                    "macd_cross_bars": 5, "macd_cross_only_bull": True, "macd_cross_below_zero": True,
                    "macd_hist_confirm_bars": 3
                })
        elif st.session_state["preset"] == "Confirm Rally":
            st.session_state.update({
                "use_vol_spike": True, "vol_mult": 1.20, "use_rsi": True, "min_rsi": 60,
                "use_macd": True, "min_mhist": 0.0, "use_trend": True, "pivot_span": 4, "trend_within": 48,
                "use_roc": False, "use_macd_cross": False, "K_green": 3, "Y_yellow": 2
            })
        elif st.session_state["preset"] == "hioncrypto's Velocity Mode":
            st.session_state.update({
                "use_vol_spike": True, "vol_mult": 2.5, "vol_window": 20,
                "use_rsi": False, "use_macd": False, "use_trend": False, "use_atr": False,
                "use_roc": True, "min_roc": 5.0,
                "use_macd_cross": True, "macd_cross_bars": 3, "macd_cross_only_bull": True,
                "macd_cross_below_zero": True, "macd_hist_confirm_bars": 2,
                "K_green": 2, "Y_yellow": 1
            })
        
        st.radio("Gate Mode", ["ALL", "ANY", "Custom (K/Y)"],
                index=["ALL", "ANY", "Custom (K/Y)"].index(st.session_state["gate_mode"]),
                key="gate_mode", horizontal=True)
        st.toggle("Hard filter (hide non-passers)", key="hard_filter")
        
        st.slider("Δ lookback (candles)", 1, 100, step=1, key="lookback_candles")
        st.slider("Min +% change (Δ gate)", 0.0, 50.0, step=0.5, key="min_pct")
        
        c1, c2, c3 = st.columns(3)
        with c1:
           st.toggle("Volume spike ✕", key="use_vol_spike", help="Passes if current volume exceeds average volume by the spike multiple (e.g., 2.5x means current volume is 250% of average)")
        
        st.slider("Spike multiple ✕", 1.0, 5.0, step=0.05, key="vol_mult", help="Multiplier threshold. 2.5 means current volume must be at least 2.5 times the average volume over the lookback period")
        st.slider("Min RSI", 40, 90, step=1, key="min_rsi")
        with c3:
            st.toggle("MACD hist", key="use_macd")
            st.slider("Min MACD hist", 0.0, 2.0, step=0.05, key="min_mhist")
        
        c4, c5, c6 = st.columns(3)
        with c4:
            st.toggle("ATR %", key="use_atr")
            st.slider("Min ATR %", 0.0, 10.0, step=0.1, key="min_atr")
        with c5:
            st.toggle("Trend breakout (up)", key="use_trend")
            st.slider("Pivot span (bars)", 2, 10, step=1, key="pivot_span")
            st.slider("Breakout within (bars)", 5, 96, step=1, key="trend_within")
        with c6:
            st.toggle("ROC (rate of change)", key="use_roc")
            st.slider("Min ROC %", 0.0, 50.0, step=0.5, key="min_roc")
        
        st.markdown("**MACD Cross (early entry)**")
        c7, c8, c9, c10 = st.columns(4)
        with c7:
            st.toggle("Enable MACD Cross", key="use_macd_cross")
        with c8:
            st.slider("Cross within last (bars)", 1, 10, st.session_state["macd_cross_bars"], 1, key="macd_cross_bars")
        with c9:
            st.toggle("Bullish only", key="macd_cross_only_bull")
        with c10:
            st.toggle("Prefer below zero", key="macd_cross_below_zero")
        st.slider("Histogram > 0 within (bars)", 0, 10, st.session_state["macd_hist_confirm_bars"], 1, key="macd_hist_confirm_bars")
        
        st.markdown("---")
        st.subheader("Color rules (Custom only)")
        st.selectbox("Gates needed to turn green (K)", list(range(1, 8)),
                    index=st.session_state["K_green"] - 1, key="K_green")
        st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0, st.session_state["K_green"])),
                    index=min(st.session_state["Y_yellow"], st.session_state["K_green"] - 1), key="Y_yellow")
# Indicator Lengths
with expander("Indicator lengths"):
    st.caption("Longer = smoother; shorter = more reactive.")
    st.slider("RSI length", 5, 50, st.session_state["rsi_len"], 1, key="rsi_len")
    st.slider("MACD fast EMA", 3, 50, st.session_state["macd_fast"], 1, key="macd_fast")
    st.slider("MACD slow EMA", 5, 100, st.session_state["macd_slow"], 1, key="macd_slow")
    st.slider("MACD signal", 3, 50, st.session_state["macd_sig"], 1, key="macd_sig")
    st.slider("ATR length", 5, 50, st.session_state.get("atr_len", 14), 1, key="atr_len")
    st.slider("Volume window", 5, 50, st.session_state["vol_window"], 1, key="vol_window")

# ATH/ATL History
with expander("History depth (for ATH/ATL)"):
    st.toggle("Compute ATH/ATL", key="do_ath")
    basis_options = ["Hourly", "Daily", "Weekly"]
    st.selectbox("Basis", basis_options, 
                index=basis_options.index(st.session_state["basis"]), key="basis")
    
    if st.session_state["basis"] == "Hourly":
        st.slider("Hours (≤72)", 1, 72, st.session_state["amount_hourly"], 1, key="amount_hourly")
    elif st.session_state["basis"] == "Daily":
        st.slider("Days (≤365)", 1, 365, st.session_state["amount_daily"], 1, key="amount_daily")
    else:
        st.slider("Weeks (≤52)", 1, 52, st.session_state["amount_weekly"], 1, key="amount_weekly")

# Display Settings
with expander("Display"):
    st.slider("Font size (global)", 0.8, 1.6, st.session_state["font_scale"], 0.05, key="font_scale")
    st.slider("Auto-refresh (seconds)", 5, 120, st.session_state["refresh_sec"], 1, key="refresh_sec")

# Notifications
with expander("Notifications"):
    st.caption("Tips: Email requires SMTP in st.secrets; webhook posts JSON to your endpoint.")
    st.text_input("Email recipient (optional)", st.session_state["email_to"], key="email_to")
    st.text_input("Webhook URL (optional)", st.session_state["webhook_url"], key="webhook_url")

# Listing Radar
with expander("Listing Radar"):
    st.caption("'New' listings are detected by symbol diffs. 'Upcoming' scraped from feeds within a window.")
    if st.session_state.get("lr_unacked", 0) > 0:
        st.markdown('<span style="background-color: #ff4444; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px;">New/Upcoming listings</span>', unsafe_allow_html=True)
    
    st.toggle("Enable Listing Radar", key="lr_enabled")
    
    if st.session_state.get("lr_enabled", False):
        c1, c2 = st.columns(2)
        with c1:
            st.toggle("Watch Coinbase", key="lr_watch_coinbase", value=st.session_state.get("lr_watch_coinbase", True))
        with c2:
            st.toggle("Watch Binance", key="lr_watch_binance", value=st.session_state.get("lr_watch_binance", True))
        
        st.text_input("Watch quotes", 
                     st.session_state.get("lr_watch_quotes", "USD, USDT, USDC"), 
                     key="lr_watch_quotes",
                     help="Comma-separated quote currencies to monitor")
        
        st.slider("Poll interval (seconds)", 10, 300, 
                 st.session_state.get("lr_poll_sec", 30), 5, 
                 key="lr_poll_sec")
        
        st.slider("Upcoming window (hours)", 1, 168, 
                 st.session_state.get("lr_upcoming_window_h", 48), 1,
                 key="lr_upcoming_window_h")
        
        st.text_area("News feeds (URLs)", 
                    st.session_state.get("lr_feeds", "https://blog.coinbase.com/feed\nhttps://www.binance.com/en/support/announcement"),
                    key="lr_feeds",
                    help="One URL per line for scraping upcoming listing announcements")


# =============================================================================
# MAIN DISPLAY
# =============================================================================

st.title("🚀 hioncrypto's: Crypto Tracker")

# DEBUG - Remove after testing
with st.expander("🐛 DEBUG_INFO", expanded=True):
    st.write("Preset:", st.session_state.get("preset", "NOT SET"))
    st.write("Last Preset:", st.session_state.get("_last_preset", "NOT SET"))
    st.write("min_pct:", st.session_state.get("min_pct", "NOT SET"))
    st.write("lookback_candles:", st.session_state.get("lookback_candles", "NOT SET"))
    st.write("vol_mult:", st.session_state.get("vol_mult", "NOT SET"))
    st.write("_initialized:", st.session_state.get("_initialized", "NOT SET"))
    st.write("---")
    st.write("**Session Keys Count:**", len(st.session_state.keys()))
    st.write("**First 30 Keys:**", list(st.session_state.keys())[:30])

# Get trading pairs
# Get trading pairs
if st.session_state["use_my_pairs"]:
    pairs = [p.strip().upper() for p in st.session_state.get("my_pairs", "").split(",") if p.strip()]
elif st.session_state["use_watch"]:
    pairs = [p.strip().upper() for p in st.session_state["watchlist"].split(",") if p.strip()]
else:
    effective_exchange = "Coinbase" if "coming soon" in st.session_state["exchange"].lower() else st.session_state["exchange"]
    pairs = get_products(effective_exchange, st.session_state["quote"])

# Apply discovery cap
# Apply discovery limit
cap = max(5, min(500, st.session_state.get("pairs_to_discover", 100)))
if cap > 0:
    pairs = pairs[:cap]

# Build gate settings
gate_settings = {
    "lookback_candles": st.session_state["lookback_candles"],
    "min_pct": st.session_state["min_pct"],
    "use_vol_spike": st.session_state["use_vol_spike"],
    "vol_mult": st.session_state["vol_mult"],
    "vol_window": st.session_state["vol_window"],
    "use_rsi": st.session_state["use_rsi"],
    "rsi_len": st.session_state["rsi_len"],
    "min_rsi": st.session_state["min_rsi"],
    "use_macd": st.session_state["use_macd"],
    "macd_fast": st.session_state["macd_fast"],
    "macd_slow": st.session_state["macd_slow"],
    "macd_sig": st.session_state["macd_sig"],
    "min_mhist": st.session_state["min_mhist"],
    "use_atr": st.session_state.get("use_atr", False),
    "atr_len": st.session_state.get("atr_len", 14),
    "min_atr": st.session_state.get("min_atr", 0.5),
    "use_trend": st.session_state["use_trend"],
    "pivot_span": st.session_state["pivot_span"],
    "trend_within": st.session_state["trend_within"],
    "use_roc": st.session_state["use_roc"],
    "min_roc": st.session_state["min_roc"],
    "use_macd_cross": st.session_state["use_macd_cross"],
    "macd_cross_bars": st.session_state["macd_cross_bars"],
    "macd_cross_only_bull": st.session_state["macd_cross_only_bull"],
    "macd_cross_below_zero": st.session_state["macd_cross_below_zero"],
    "macd_hist_confirm_bars": st.session_state["macd_hist_confirm_bars"],
}

# Process pairs and build rows
rows = []
sort_tf = st.session_state["sort_tf"]
mode = st.session_state["gate_mode"]
hard_filter = st.session_state["hard_filter"]
k_required = st.session_state["K_green"]
y_required = st.session_state["Y_yellow"]

effective_exchange = "Coinbase" if "coming soon" in st.session_state["exchange"].lower() else st.session_state["exchange"]

# Show processing status
if pairs:
    status_placeholder = st.empty()
    progress_placeholder = st.empty()
    
    # Process each pair with real-time updates
    for i, pair in enumerate(pairs):
        # Update progress
        progress = (i + 1) / len(pairs)
        progress_placeholder.progress(progress)
        status_placeholder.text(f"Processing {pair}... ({i + 1}/{len(pairs)})")
        
        # Get fresh data for each pair
        df = get_cached_data(effective_exchange, pair, sort_tf)
        if df is None or df.empty or len(df) < st.session_state["min_bars"]:
            continue
        
        # Evaluate gates
        meta, passed, chips, enabled = evaluate_gates(df, gate_settings)
        
        # Determine inclusion and signal based on gate mode
        if mode == "ALL":
            include = (enabled > 0 and passed == enabled)
            is_green = include
            is_yellow = (0 < passed < enabled) and (passed >= enabled - 1)  # Close matches
        elif mode == "ANY":
            include = True
            is_green = (passed >= 1)
            is_yellow = False  # ANY mode doesn't use yellow
        else:  # Custom (K/Y)
            include = True
            is_green = (passed >= k_required)
            is_yellow = (not is_green) and (passed >= y_required)
            # Also mark close matches as yellow if they're just 1 gate short of green
            if not is_green and not is_yellow and passed >= (k_required - 1) and passed > 0:
                is_yellow = True
        
        # Apply hard filter
        if hard_filter:
            if mode in {"ALL", "ANY"} and not include:
                continue
            if mode == "Custom (K/Y)" and not (is_green or is_yellow):
                continue
        
        # Get current price (WebSocket override or last close)
        ws_price = st.session_state.get("ws_prices", {}).get(pair)
        last_price = float(ws_price) if ws_price else float(df["close"].iloc[-1])
        lookback = min(st.session_state["lookback_candles"], len(df) - 1)
        first_price = float(df["close"].iloc[-lookback]) if lookback > 0 else float(df["close"].iloc[0])
        pct_change = (last_price / (first_price + 1e-12) - 1.0) * 100.0
        
        # Determine signal text
        signal = ""
        if is_green:
            signal = "Strong Buy"
        elif is_yellow:
            signal = "Watch"
        
        # Add ATH/ATL data if enabled
        ath_data = {}
        if st.session_state.get("do_ath", False):
            # Get longer history for ATH/ATL calculation
            basis = st.session_state["basis"]
            if basis == "Hourly":
                history_limit = st.session_state["amount_hourly"] * 4  # 15min bars
            elif basis == "Daily":
                history_limit = st.session_state["amount_daily"] * 24  # hourly bars  
            else:  # Weekly
                history_limit = st.session_state["amount_weekly"] * 7 * 24  # hourly bars
            
            history_df = get_cached_data(effective_exchange, pair, "1h")
            from_ath, ath_date, from_atl, atl_date = compute_ath_atl(history_df)
            ath_data = {
                "ATH %": f"{from_ath:+.1f}%" if not pd.isna(from_ath) else "N/A",
                "ATL %": f"{from_atl:+.1f}%" if not pd.isna(from_atl) else "N/A"
                }
        
        # Build row data
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
            "_ws_active": ws_price is not None
        }
        
        # Add ATH/ATL columns if enabled
        row_data.update(ath_data)
            
            # Send alerts if pair meets velocity criteria
        if is_green:  # Only alert on strong signals
                email_recipient = st.session_state.get("email_alert", "")
                webhook_url = st.session_state.get("webhook_url", "")
                
                # Only alert once per pair per session
                if pair not in st.session_state.alerted_pairs:
                    if email_recipient:
                        send_email_alert(email_recipient, pair, last_price, pct_change)
                    if webhook_url:
                        send_webhook_alert(webhook_url, pair, last_price, pct_change, chips)
                    
                    st.session_state.alerted_pairs.add(pair)
            
        rows.append(row_data)
    
    # Clear progress indicators
    progress_placeholder.empty()
    status_placeholder.empty()
    
    st.success(f"✅ Processed {len(rows)} pairs successfully!")

# Create DataFrame
if rows:
    df_results = pd.DataFrame(rows)
    
    # Sort by % change
    chg_col = f"% Change ({sort_tf})"
    ascending = not st.session_state["sort_desc"]
    df_results = df_results.sort_values(chg_col, ascending=ascending).reset_index(drop=True)
        
        # Filter to only pairs meeting minimum % change threshold (delta gate)
    min_pct = st.session_state["min_pct"]
    df_results = df_results[df_results[chg_col] >= min_pct]
        
    df_results.insert(0, "#", range(1, len(df_results) + 1))
    
    # Show current time and summary
    st.caption(f"Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    green_count = df_results["_green"].sum()
    yellow_count = df_results["_yellow"].sum()
    total_count = len(df_results)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Pairs", total_count)
    with col2:
        st.metric("Strong Buy", green_count)
    with col3:
        st.metric("Watch", yellow_count)
    with col4:
        st.metric("Neutral", total_count - green_count - yellow_count)
    
    st.subheader("🔥 Top 10 Opportunities")
    
    # Always sort by percentage change as primary criteria
    chg_col = f"% Change ({sort_tf})"
    top_10 = df_results.head(10)
    # Remove the # column if it exists to avoid duplication
    if "#" in top_10.columns:
        top_10 = top_10.drop(columns=["#"])
    top_10.insert(0, "Rank", range(1, len(top_10) + 1))
    
    if not top_10.empty:
        # Style rows based on gate status
        def style_top10_rows(row):
            idx = row.name
            if "_green" in top_10.columns and top_10.iloc[idx]["_green"]:
                return ['background-color: #1ea34e; color: white; font-weight: 600'] * len(row)
            elif "_yellow" in top_10.columns and top_10.iloc[idx]["_yellow"]:
                return ['background-color: #eab308; color: black'] * len(row)
            return [''] * len(row)
        
        display_cols = [col for col in top_10.columns if not col.startswith('_')]
        styled_df = top_10[display_cols].style.apply(style_top10_rows, axis=1)
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    # Display options
    col1, col2 = st.columns([3, 1])
    with col1:
        show_all = st.checkbox("Show all pairs (not just signals)", value=not hard_filter)
    with col2:
        sort_option = st.selectbox("Sort by", ["% Change", "Signal", "Pair"], index=0)
    
    # Filter for display
    if not show_all:
        display_df = df_results[df_results["_green"] | df_results["_yellow"]]
    else:
        display_df = df_results
    
    # Re-sort if needed
    if sort_option == "Signal":
        display_df = display_df.sort_values(["_green", "_yellow"], ascending=[False, False])
    elif sort_option == "Pair":
        display_df = display_df.sort_values("Pair")
    
    if not display_df.empty:
        # Display columns (hide internal columns)
        display_cols = [col for col in display_df.columns if not col.startswith('_')]
        final_display = display_df[display_cols].reset_index(drop=True)
        
        # Style the dataframe
        def style_all_rows(row):
            if row.name < len(display_df):
                original_idx = display_df.index[row.name]
                if display_df.loc[original_idx, "_green"]:
                    return ['background-color: #16a34a; color: white; font-weight: 600'] * len(row)
                elif display_df.loc[original_idx, "_yellow"]:
                    return ['background-color: #eab308; color: black'] * len(row)
            return [''] * len(row)
        
        styled_all = final_display.style.apply(style_all_rows, axis=1)
        st.dataframe(styled_all, use_container_width=True, hide_index=True, height=600)
    else:
        st.info("No pairs match the current filter criteria.")

else:
    st.info("No trading pairs found. Adjust your market settings or increase the discovery cap.")

# WebSocket Management for real-time updates
if st.session_state["mode"].startswith("WebSocket") and effective_exchange == "Coinbase" and WS_AVAILABLE:
    if not st.session_state.get("ws_alive", False) and pairs:
        # Start WebSocket for top pairs
        ws_pairs = pairs[:st.session_state["ws_chunk"]]
        
        def ws_worker(product_ids):
            try:
                ws = websocket.WebSocket()
                ws.connect(CONFIG.COINBASE_WS, timeout=10)
                ws.settimeout(1.0)
                
                subscribe_msg = {
                    "type": "subscribe",
                    "channels": [{"name": "ticker", "product_ids": product_ids}]
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
                                    st.session_state["ws_prices"][product_id] = float(price)
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
        
        if not st.session_state.get("ws_thread") or not st.session_state["ws_thread"].is_alive():
            ws_thread = threading.Thread(target=ws_worker, args=(ws_pairs,), daemon=True)
            st.session_state["ws_thread"] = ws_thread
            ws_thread.start()

# Smart cache clearing - avoid refreshing data on UI-only changes
current_time = int(time.time())
if "last_update" not in st.session_state:
    st.session_state["last_update"] = 0

time_since_update = current_time - st.session_state["last_update"]
refresh_interval = st.session_state["refresh_sec"]

# Check if this is just a UI state change (like expand/collapse)
is_ui_only_change = st.session_state.get("_ui_only_change", False)
if is_ui_only_change:
    st.session_state["_ui_only_change"] = False  # Reset the flag
    # Don't refresh data, just continue with existing data

# Only refresh data if enough time has passed AND it's not a UI-only change
elif time_since_update >= refresh_interval:
    st.session_state["last_update"] = current_time
    st.rerun()

# Auto-refresh mechanism
#if st_autorefresh:
#    refresh_interval_ms = max(5, st.session_state["refresh_sec"]) * 1000
#    st_autorefresh(interval=refresh_interval_ms, key="auto_refresh", debounce=False)
else:
        # Use Streamlit's native rerun instead of JavaScript reload
        # JavaScript reloads destroy session state!
        pass  # The st.rerun() on line 1373 already handles refresh
# Live update indicator
st.markdown(f"""
<div style="position: fixed; top: 10px; right: 10px; background: rgba(0,0,0,0.7); color: white; padding: 5px 10px; border-radius: 15px; font-size: 12px; z-index: 1000;">
    🔄 Last: {time.strftime('%H:%M:%S')} | Next: {refresh_interval}s
</div>
""", unsafe_allow_html=True)

# Footer
st.markdown("---")
st.caption("🚀 Enhanced Crypto Tracker — Real-time momentum scanner by hioncrypto")

