# Enhanced Crypto Tracker by hioncrypto
# Requirements (add to requirements.txt):
# streamlit>=1.33
# pandas>=2.0
# numpy>=1.24
# requests>=2.31
# websocket-client>=1.6 
# plotly>=5.0

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

@dataclass
class GateSettings:
    """Configuration for trading gates/filters"""
    # Core settings
    lookback_candles: int = 3
    min_pct: float = 3.0
    
    # Volume spike
    use_vol_spike: bool = True
    vol_mult: float = 1.10
    vol_window: int = 20
    
    # RSI
    use_rsi: bool = False
    rsi_len: int = 14
    min_rsi: int = 55
    
    # MACD
    use_macd: bool = False
    macd_fast: int = 12
    macd_slow: int = 26
    macd_sig: int = 9
    min_mhist: float = 0.0
    
    # ATR
    use_atr: bool = False
    atr_len: int = 14
    min_atr: float = 0.5
    
    # Trend breakout
    use_trend: bool = False
    pivot_span: int = 4
    trend_within: int = 48
    
    # ROC
    use_roc: bool = False
    min_roc: float = 1.0
    
    # MACD Cross
    use_macd_cross: bool = True
    macd_cross_bars: int = 5
    macd_cross_only_bull: bool = True
    macd_cross_below_zero: bool = True
    macd_hist_confirm_bars: int = 3
    
    # Gate mode
    gate_mode: str = "ANY"  # "ALL", "ANY", "Custom (K/Y)"
    hard_filter: bool = False
    K_green: int = 3
    Y_yellow: int = 2

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

/* Responsive design */
@media (max-width: 768px) {
    [data-testid="stAppViewContainer"] > .main > div.block-container {
        padding-left: 8px !important;
        padding-right: 8px !important;
    }
}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# STATE MANAGEMENT
# =============================================================================

class StateManager:
    """Handles session state and URL parameter persistence"""
    
    PERSIST_KEYS = {
        # Market settings
        "exchange": ("Coinbase", str),
        "quote": ("USD", str),
        "use_watch": (False, bool),
        "watchlist": ("BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD", str),
        "use_my_pairs": (False, bool),
        "my_pairs": ("BTC-USD, ETH-USD, SOL-USD", str),
        "discover_cap": (400, int),
        
        # Mode
        "mode": ("REST only", str),
        "ws_chunk": (5, int),
        
        # Timeframes
        "sort_tf": ("1h", str),
        "sort_desc": (True, bool),
        "min_bars": (1, int),
        
        # Display
        "font_scale": (1.0, float),
        "refresh_sec": (30, int),
        
        # Notifications
        "email_to": ("", str),
        "webhook_url": ("", str),
        
        # ATH/ATL
        "do_ath": (False, bool),
        "basis": ("Daily", str),
        "amount_daily": (90, int),
        "amount_hourly": (24, int),
        "amount_weekly": (12, int),
        
        # UI state
        "collapse_all": (False, bool),
        
        # Listing Radar
        "lr_enabled": (False, bool),
        "lr_watch_coinbase": (True, bool),
        "lr_watch_binance": (True, bool),
        "lr_watch_quotes": ("USD, USDT, USDC", str),
        "lr_poll_sec": (30, int),
    }
    
    @classmethod
    def init_state(cls):
        """Initialize session state from URL parameters"""
        query_params = st.query_params
        
        for key, (default, typ) in cls.PERSIST_KEYS.items():
            if key in query_params:
                raw_value = query_params[key]
                if isinstance(raw_value, list):
                    raw_value = raw_value[0]
                value = cls._coerce_type(raw_value, typ, default)
            else:
                value = default
            st.session_state.setdefault(key, value)
        
        # Initialize runtime state
        cls._init_runtime_state()
    
    @classmethod
    def _coerce_type(cls, value: Any, typ: type, default: Any) -> Any:
        """Safely coerce value to target type"""
        try:
            if typ is bool:
                return str(value).strip().lower() in {"1", "true", "yes", "on"}
            elif typ is int:
                return int(str(value).strip())
            elif typ is float:
                return float(str(value).strip())
            else:
                return str(value).strip()
        except (ValueError, TypeError):
            return default
    
    @classmethod
    def _init_runtime_state(cls):
        """Initialize runtime-only state variables"""
        runtime_defaults = {
            "ws_thread": None,
            "ws_alive": False,
            "ws_q": queue.Queue(),
            "ws_prices": {},
            "alert_seen": set(),
            "lr_baseline": {"Coinbase": set(), "Binance": set()},
            "lr_events": [],
            "lr_unacked": 0,
            "lr_last_poll": 0.0,
        }
        
        for key, default in runtime_defaults.items():
            st.session_state.setdefault(key, default)
    
    @classmethod
    def sync_to_url(cls):
        """Sync session state to URL parameters"""
        payload = {}
        for key in cls.PERSIST_KEYS.keys():
            value = st.session_state.get(key)
            if value is not None:
                if isinstance(value, (list, tuple)):
                    payload[key] = ", ".join(map(str, value))
                else:
                    payload[key] = value
        
        if payload:
            st.query_params.update(payload)

# =============================================================================
# TECHNICAL INDICATORS
# =============================================================================

class TechnicalIndicators:
    """Collection of technical analysis indicators"""
    
    @staticmethod
    def ema(series: pd.Series, span: int) -> pd.Series:
        """Exponential Moving Average"""
        return series.astype("float64").ewm(span=span, adjust=False).mean()
    
    @staticmethod
    def rsi(close: pd.Series, length: int = 14) -> pd.Series:
        """Relative Strength Index"""
        delta = close.diff()
        up = np.where(delta > 0, delta, 0.0)
        dn = np.where(delta < 0, -delta, 0.0)
        
        ru = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
        rd = pd.Series(dn, index=close.index).ewm(alpha=1/length, adjust=False).mean()
        
        rs = ru / (rd + 1e-12)
        return 100 - 100 / (1 + rs)
    
    @staticmethod
    def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """MACD indicator"""
        macd_line = TechnicalIndicators.ema(close, fast) - TechnicalIndicators.ema(close, slow)
        signal_line = TechnicalIndicators.ema(macd_line, signal)
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    @staticmethod
    def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
        """Average True Range"""
        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)
        
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return true_range.ewm(alpha=1/length, adjust=False).mean()
    
    @staticmethod
    def volume_spike(df: pd.DataFrame, window: int = 20) -> float:
        """Calculate volume spike ratio"""
        if len(df) < window + 1:
            return np.nan
        
        current_vol = df["volume"].iloc[-1]
        avg_vol = df["volume"].rolling(window).mean().iloc[-1]
        
        return float(current_vol / (avg_vol + 1e-12))
    
    @staticmethod
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
    
    @staticmethod
    def trend_breakout_up(df: pd.DataFrame, span: int = 3, within_bars: int = 48) -> bool:
        """Detect upward trend breakout"""
        if df is None or len(df) < span * 2 + 5:
            return False
        
        highs, _ = TechnicalIndicators.find_pivots(df["close"], span)
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

class DataFetcher:
    """Handles fetching market data from various exchanges"""
    
    @staticmethod
    def get_bars_limit(timeframe: str) -> int:
        """Get appropriate number of bars for timeframe"""
        limits = {"15m": 96, "1h": 48}
        return limits.get(timeframe, 24)
    
    @classmethod
    def fetch_coinbase_data(cls, pair: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
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
    
    @classmethod
    def fetch_binance_data(cls, pair: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
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
    
    @classmethod
    def fetch_data(cls, exchange: str, pair: str, timeframe: str, limit: Optional[int] = None) -> Optional[pd.DataFrame]:
        """Fetch data from specified exchange"""
        if limit is None:
            limit = cls.get_bars_limit(timeframe)
        
        limit = max(1, min(300, limit))
        
        exchange_lower = exchange.lower()
        
        if exchange_lower.startswith("coinbase"):
            return cls.fetch_coinbase_data(pair, timeframe, limit)
        elif exchange_lower.startswith("binance"):
            return cls.fetch_binance_data(pair, timeframe, limit)
        else:
            # Default to Coinbase for unsupported exchanges
            return cls.fetch_coinbase_data(pair, timeframe, limit)

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
        limit = DataFetcher.get_bars_limit(timeframe)
        return DataFetcher.fetch_data(exchange, pair, timeframe, limit)
    except Exception:
        return None

# =============================================================================
# PRODUCT LISTING
# =============================================================================

class ProductLister:
    """Handles fetching available trading pairs"""
    
    @staticmethod
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
    
    @staticmethod
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
    
    @classmethod
    def get_products(cls, exchange: str, quote: str) -> List[str]:
        """Get products for specified exchange and quote"""
        exchange_lower = exchange.lower()
        
        if exchange_lower.startswith("coinbase"):
            return cls.get_coinbase_products(quote)
        elif exchange_lower.startswith("binance"):
            return cls.get_binance_products(quote)
        else:
            # Default to Coinbase
            return cls.get_coinbase_products(quote)

# =============================================================================
# WEBSOCKET MANAGER
# =============================================================================

class WebSocketManager:
    """Manages WebSocket connections for real-time price updates"""
    
    @staticmethod
    def worker(product_ids: List[str], endpoint: str = None):
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
    
    @classmethod
    def start(cls, exchange: str, pairs: List[str], chunk_size: int):
        """Start WebSocket connection"""
        if (not WS_AVAILABLE or 
            exchange != "Coinbase" or 
            not pairs or 
            st.session_state.get("ws_alive")):
            return
        
        selected_pairs = pairs[:max(2, min(chunk_size, len(pairs)))]
        
        thread = threading.Thread(
            target=cls.worker,
            args=(selected_pairs,),
            daemon=True
        )
        st.session_state["ws_thread"] = thread
        thread.start()
        time.sleep(0.2)  # Brief pause for connection
    
    @staticmethod
    def stop():
        """Stop WebSocket connection"""
        if st.session_state.get("ws_alive"):
            st.session_state["ws_alive"] = False
    
    @staticmethod
    def drain_queue():
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

class GateEvaluator:
    """Evaluates trading gates/signals for pairs"""
    
    @staticmethod
    def evaluate_gates(df: pd.DataFrame, settings: GateSettings) -> Tuple[Dict, int, str, int]:
        """Evaluate all gates for a given dataframe and settings"""
        n = len(df)
        lookback = max(1, min(settings.lookback_candles, 100, n - 1))
        
        # Calculate basic metrics
        last_close = float(df["close"].iloc[-1])
        ref_close = float(df["close"].iloc[-lookback])
        delta_pct = (last_close / ref_close - 1.0) * 100.0
        
        # MACD calculation
        macd_line, signal_line, hist = TechnicalIndicators.macd(
            df["close"], settings.macd_fast, settings.macd_slow, settings.macd_sig
        )
        
        gates_passed = 0
        gates_enabled = 0
        gate_chips = []
        
        # Delta gate (always enabled)
        delta_pass = delta_pct >= settings.min_pct
        gates_passed += int(delta_pass)
        gates_enabled += 1
        gate_chips.append(f"Δ{'✅' if delta_pass else '❌'}({delta_pct:+.2f}%)")
        
        # Volume spike gate
        if settings.use_vol_spike:
            vol_spike = TechnicalIndicators.volume_spike(df, settings.vol_window)
            vol_pass = pd.notna(vol_spike) and vol_spike >= settings.vol_mult
            gates_passed += int(vol_pass)
            gates_enabled += 1
            vol_display = f"({vol_spike:.2f}×)" if pd.notna(vol_spike) else "(N/A)"
            gate_chips.append(f" V{'✅' if vol_pass else '❌'}{vol_display}")
        else:
            gate_chips.append(" V–")
        
        # RSI gate
        if settings.use_rsi:
            rsi_values = TechnicalIndicators.rsi(df["close"], settings.rsi_len)
            current_rsi = float(rsi_values.iloc[-1])
            rsi_pass = current_rsi >= settings.min_rsi
            gates_passed += int(rsi_pass)
            gates_enabled += 1
            gate_chips.append(f" S{'✅' if rsi_pass else '❌'}({current_rsi:.1f})")
        else:
            gate_chips.append(" S–")
        
        # MACD histogram gate
        if settings.use_macd:
            macd_hist = float(hist.iloc[-1])
            macd_pass = macd_hist >= settings.min_mhist
            gates_passed += int(macd_pass)
            gates_enabled += 1
            gate_chips.append(f" M{'✅' if macd_pass else '❌'}({macd_hist:.3f})")
        else:
            gate_chips.append(" M–")
        
        # Trend breakout gate
        if settings.use_trend:
            trend_pass = TechnicalIndicators.trend_breakout_up(
                df, settings.pivot_span, settings.trend_within
            )
            gates_passed += int(trend_pass)
            gates_enabled += 1
            gate_chips.append(f" T{'✅' if trend_pass else '❌'}")
        else:
            gate_chips.append(" T–")
        
        # ROC gate
        if settings.use_roc:
            roc = (df["close"].iloc[-1] / df["close"].iloc[-lookback] - 1.0) * 100.0 if n > lookback else np.nan
            roc_pass = pd.notna(roc) and roc >= settings.min_roc
            gates_passed += int(roc_pass)
            gates_enabled += 1
            roc_display = f"({roc:+.2f}%)" if pd.notna(roc) else "(N/A)"
            gate_chips.append(f" R{'✅' if roc_pass else '❌'}{roc_display}")
        else:
            gate_chips.append(" R–")
        
        # MACD Cross gate
        cross_info = {"ok": False, "bars_ago": None}
        if settings.use_macd_cross:
            cross_pass, bars_ago = GateEvaluator._check_macd_cross(
                macd_line, signal_line, hist, settings
            )
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
    
    @staticmethod
    def _check_macd_cross(macd_line: pd.Series, signal_line: pd.Series, 
                         hist: pd.Series, settings: GateSettings) -> Tuple[bool, Optional[int]]:
        """Check for MACD cross signal"""
        bars_to_check = settings.macd_cross_bars
        
        for i in range(1, min(bars_to_check + 1, len(hist
