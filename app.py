# Enhanced Crypto Tracker by hioncrypto
# Requirements (add to requirements.txt):
# streamlit>=1.33
# pandas>=2.0
# numpy>=1.24
# requests>=2.31
# websocket-client>=1.6 

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
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

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

@dataclass
class AppConfig:
    """Central configuration for the application"""
    # API endpoints
    COINBASE_BASE: str = "https://api.exchange.coinbase.com"
    BINANCE_BASE: str = "https://api.binance.com"
    COINBASE_WS: str = "wss://ws-feed.exchange.coinbase.com"
    
    # Market data
    TIMEFRAMES: Dict[str, int] = None
    QUOTES: List[str] = None
    EXCHANGES: List[str] = None
    
    # Default settings
    DEFAULT_REFRESH_SEC: int = 30
    DEFAULT_FONT_SCALE: float = 1.0
    MAX_PAIRS_LIMIT: int = 500
    
    def __post_init__(self):
        if self.TIMEFRAMES is None:
            self.TIMEFRAMES = {"15m": 900, "1h": 3600}
        if self.QUOTES is None:
            self.QUOTES = ["USD", "USDC", "USDT", "BTC", "ETH", "EUR"]
        if self.EXCHANGES is None:
            self.EXCHANGES = ["Coinbase", "Binance", "Kraken (coming soon)", "KuCoin (coming soon)"]

# Initialize global config
CONFIG = AppConfig()

# =============================================================================
# STREAMLIT PAGE SETUP
# =============================================================================

st.set_page_config(
    page_title="Enhanced Crypto Tracker", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
/* Full width layout */
[data-testid="stAppViewContainer"] > .main > div.block-container {
    max-width: 100vw !important;
    padding-left: 12px !important;
    padding-right: 12px !important;
}

/* Remove animations and opacity changes */
div[data-testid="stDataFrame"],
div[data-testid="stDataFrame"] *,
div[data-testid="stDataEditor"],
div[data-testid="stDataEditor"] * {
    opacity: 1 !important;
    filter: none !important;
    transition: none !important;
    animation: none !important;
}

/* Keep sidebar interactive */
section[data-testid="stSidebar"],
section[data-testid="stSidebar"] * {
    pointer-events: auto !important;
    opacity: 1 !important;
    z-index: 999;
}

/* Table styling */
.sortable-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 1rem;
}

.sortable-table th {
    background-color: #f0f2f6;
    padding: 0.5rem;
    text-align: left;
    cursor: pointer;
    border-bottom: 2px solid #ddd;
}

.sortable-table td {
    padding: 0.5rem;
    border-bottom: 1px solid #eee;
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
    """Initialize session state variables"""
    defaults = {
        # Market settings
        "exchange": "Coinbase",
        "quote": "USD",
        "use_watch": False,
        "watchlist": "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD",
        "use_my_pairs": False,
        "my_pairs": "BTC-USD, ETH-USD, SOL-USD",
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
        "ws_q": queue.Queue(),
        "ws_prices": {},
        
        # Alerts
        "alert_seen": set(),
        
        # Listing Radar
        "lr_enabled": False,
        "lr_baseline": {"Coinbase": set(), "Binance": set()},
        "lr_events": [],
        "lr_unacked": 0,
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

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

def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    """Average True Range"""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(alpha=1/length, adjust=False).mean()

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
        # Pivot high
        if (values[i] > values[i-span:i].max() and 
            values[i] > values[i+1:i+1+span].max()):
            highs.append(i)
        
        # Pivot low
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
    
    # Get most recent pivot high
    latest_high_idx = highs[-1]
    resistance_level = float(df["close"].iloc[latest_high_idx])
    
    # Check for breakout
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
    headers = {
        "User-Agent": "crypto-tracker/2.0",
        "Accept": "application/json"
    }
    
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
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": max(50, limit)
    }
    
    try:
        response = requests.get(f"{CONFIG.BINANCE_BASE}/api/v3/klines", 
                              params=params, timeout=20)
        
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
        # Default to Coinbase for unsupported exchanges
        return fetch_coinbase_data(pair, timeframe, limit)

# =============================================================================
# CACHING
# =============================================================================

def get_cache_key() -> int:
    """Generate cache key based on refresh interval"""
    refresh_sec = max(1, int(st.session_state.get("refresh_sec", 30)))
    return int(time.time() // refresh_sec)

@st.cache_data(show_spinner=False)
def get_cached_data(exchange: str, pair: str, timeframe: str, cache_key: int) -> Optional[pd.DataFrame]:
    """Cached data fetching function"""
    try:
        limit = get_bars_limit(timeframe)
        return fetch_data(exchange, pair, timeframe, limit)
    except Exception:
        return None

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
            if product.get("quote_currency") == quote.upper():
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
        # Default to Coinbase
        return get_coinbase_products(quote)

# =============================================================================
# WEBSOCKET MANAGER
# =============================================================================

def ws_worker(product_ids: List[str], endpoint: str = None):
    """WebSocket worker thread"""
    if endpoint is None:
        endpoint = CONFIG.COINBASE_WS
    
    try:
        ws = websocket.WebSocket()
        ws.connect(endpoint, timeout=10)
        ws.settimeout(1.0)
        
        # Subscribe to ticker channel
        subscribe_msg = {
            "type": "subscribe",
            "channels": [{
                "name": "ticker",
                "product_ids": product_ids
            }]
        }
        ws.send(json.dumps(subscribe_msg))
        
        st.session_state["ws_alive"] = True
        
        while st.session_state.get("ws_alive", False):
            try:
                message = ws.recv()
                if not message:
                    continue
                
                data = json.loads(message)
                if data.get("type") == "ticker":
                    product_id = data.get("product_id")
                    price = data.get("price")
                    
                    if product_id and price:
                        st.session_state["ws_q"].put((product_id, float(price)))
                        
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

def start_ws(exchange: str, pairs: List[str], chunk_size: int):
    """Start WebSocket connection"""
    if (not WS_AVAILABLE or 
        exchange != "Coinbase" or 
        not pairs or 
        st.session_state.get("ws_alive")):
        return
    
    selected_pairs = pairs[:max(2, min(chunk_size, len(pairs)))]
    
    thread = threading.Thread(
        target=ws_worker,
        args=(selected_pairs,),
        daemon=True
    )
    st.session_state["ws_thread"] = thread
    thread.start()
    time.sleep(0.2)  # Brief pause for connection

def stop_ws():
    """Stop WebSocket connection"""
    if st.session_state.get("ws_alive"):
        st.session_state["ws_alive"] = False

def drain_ws_queue():
    """Process WebSocket price updates"""
    queue_obj = st.session_state.get("ws_q")
    prices = st.session_state.get("ws_prices", {})
    
    if not queue_obj:
        return
    
    try:
        while True:
            product_id, price = queue_obj.get_nowait()
            prices[product_id] = price
    except queue.Empty:
        pass
    
    st.session_state["ws_prices"] = prices

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
        
        # Check for cross
        crossed_up = prev_diff < 0 and curr_diff > 0
        crossed_down = prev_diff > 0 and curr_diff < 0
        
        if only_bull and not crossed_up:
            continue
        if not only_bull and not (crossed_up or crossed_down):
            continue
        
        # Check below zero requirement
        if need_below and (macd_line.iloc[-i] > 0 or signal_line.iloc[-i] > 0):
            continue
        
        # Check histogram confirmation
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
    
    # Calculate basic metrics
    last_close = float(df["close"].iloc[-1])
    ref_close = float(df["close"].iloc[-lookback])
    delta_pct = (last_close / ref_close - 1.0) * 100.0
    
    # MACD calculation
    macd_line, signal_line, hist = macd_core(
        df["close"], 
        settings.get("macd_fast", 12), 
        settings.get("macd_slow", 26), 
        settings.get("macd_sig", 9)
    )
    
    gates_passed = 0
    gates_enabled = 0
    gate_chips = []
    
    # Delta gate (always enabled)
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
    
    metadata = {
        "delta_pct": delta_pct,
        "macd_cross": cross_info
    }
    
    return metadata, gates_passed, " ".join(gate_chips), gates_enabled

# =============================================================================
# NOTIFICATIONS
# =============================================================================

def send_email_alert(subject: str, body: str, recipient: str) -> Tuple[bool, str]:
    """Send email alert"""
    try:
        cfg = st.secrets.get("smtp", {})
        if not cfg:
            return False, "SMTP not configured in st.secrets"
        
        msg = MIMEMultipart()
        msg["From"] = cfg["sender"]
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port", 465), context=ctx) as server:
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["sender"], recipient, msg.as_string())
        
        return True, "Email sent successfully"
    except Exception as e:
        return False, f"Email error: {e}"

def post_webhook(url: str, payload: dict) -> Tuple[bool, str]:
    """Post webhook notification"""
    try:
        response = requests.post(url, json=payload, timeout=10)
        return (200 <= response.status_code < 300), response.text
    except Exception as e:
        return False, str(e)

# =============================================================================
# SORTABLE TABLE COMPONENT
# =============================================================================

def render_sortable_table(df: pd.DataFrame, table_id: str, height: int = 480):
    """Render a sortable table with row styling"""
    if df.empty:
        st.info("No data to display")
        return
    
    # Create HTML table with styling
    html_rows = []
    
    # Header
    header_cells = []
    for col in df.columns:
        if not col.startswith('_'):  # Skip internal columns
            header_cells.append(f'<th onclick="sortTable(\'{table_id}\', {len(header_cells)})">{col}</th>')
    html_rows.append(f'<tr>{"".join(header_cells)}</tr>')
    
    # Data rows
    for idx, row in df.iterrows():
        signal = str(row.get('Signal', '')).strip().upper()
        
        if signal == 'STRONG BUY':
            row_class = 'row-green'
        elif signal == 'WATCH':
            row_class = 'row-yellow'
        else:
            row_class = ''
        
        cells = []
        for col in df.columns:
            if not col.startswith('_'):  # Skip internal columns
                value = row[col]
                if isinstance(value, (int, float)):
                    if col.startswith('%') or 'Change' in col:
                        cells.append(f'<td>{value:+.2f}%</td>')
                    elif 'Price' in col:
                        cells.append(f'<td>${value:.6f}</td>')
                    else:
