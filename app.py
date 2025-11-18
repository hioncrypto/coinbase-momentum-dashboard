import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime

# Page config
st.set_page_config(page_title="Crypto Momentum Tracker", layout="wide", initial_sidebar_state="expanded")

# Custom CSS
st.markdown("""
<style>
    .main {padding: 1rem;}
    .stDataFrame {font-size: 0.9rem;}
    @media (max-width: 768px) {
        .main {padding: 0.5rem;}
        .stDataFrame {font-size: 0.8rem;}
        [data-testid="stSidebar"] {min-width: 280px;}
    }
    .alert-high {background-color: #ff4444; color: white; padding: 0.5rem; border-radius: 5px; font-weight: bold;}
    .alert-med {background-color: #ff9933; color: white; padding: 0.5rem; border-radius: 5px; font-weight: bold;}
    .alert-low {background-color: #ffcc00; color: black; padding: 0.5rem; border-radius: 5px; font-weight: bold;}
</style>
""", unsafe_allow_html=True)

# Configuration
COINBASE_BASE = "https://api.exchange.coinbase.com"
BINANCE_BASE = "https://api.binance.com"
TIMEFRAMES = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}

# URL parameter handling
def get_url_params():
    try:
        return {k: v for k, v in st.query_params.items()}
    except:
        return {}

def set_url_params(params):
    try:
        st.query_params.update(params)
    except:
        pass

url_params = get_url_params()

# Initialize session state from URL
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.exchange = url_params.get('exchange', 'Coinbase')
    st.session_state.quote = url_params.get('quote', 'USD')
    st.session_state.timeframe = url_params.get('timeframe', '1h')
    st.session_state.lookback = int(url_params.get('lookback', '24'))
    st.session_state.min_pct = float(url_params.get('min_pct', '10'))
    st.session_state.macd_enabled = url_params.get('macd', 'true').lower() == 'true'
    st.session_state.histogram_enabled = url_params.get('histogram', 'true').lower() == 'true'
    st.session_state.rsi_enabled = url_params.get('rsi', 'false').lower() == 'true'
    st.session_state.rsi_threshold = float(url_params.get('rsi_threshold', '30'))
    st.session_state.volume_enabled = url_params.get('volume', 'false').lower() == 'true'
    st.session_state.volume_threshold = float(url_params.get('volume_threshold', '1.5'))
    st.session_state.pairs_limit = int(url_params.get('pairs_limit', '50'))

# Technical indicators
def calculate_macd(close_prices, fast=12, slow=26, signal=9):
    ema_fast = close_prices.ewm(span=fast, adjust=False).mean()
    ema_slow = close_prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]

def calculate_rsi(close_prices, period=14):
    delta = close_prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

# API functions
def get_coinbase_products(quote):
    try:
        response = requests.get(f"{COINBASE_BASE}/products", timeout=25)
        response.raise_for_status()
        products = []
        for product in response.json():
            if (product.get("quote_currency") == quote.upper() and 
                product.get("status") == "online" and 
                not product.get("trading_disabled", False) and 
                not product.get("cancel_only", False)):
                pair = f"{product['base_currency']}-{product['quote_currency']}"
                products.append(pair)
        return sorted(products)
    except:
        return []

def get_binance_products(quote):
    try:
        response = requests.get(f"{BINANCE_BASE}/api/v3/exchangeInfo", timeout=25)
        response.raise_for_status()
        products = []
        quote_upper = quote.upper()
        for symbol in response.json().get("symbols", []):
            if (symbol.get("status") == "TRADING" and 
                symbol.get("quoteAsset") == quote_upper):
                pair = f"{symbol['baseAsset']}-{quote_upper}"
                products.append(pair)
        return sorted(products)
    except:
        return []

def fetch_coinbase_data(pair, timeframe, limit):
    tf_seconds = TIMEFRAMES.get(timeframe)
    if not tf_seconds:
        return None
    
    url = f"{COINBASE_BASE}/products/{pair}/candles"
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
        except:
            time.sleep(0.4 * (attempt + 1))
    return None

def fetch_binance_data(pair, timeframe, limit):
    try:
        base, quote = pair.split("-")
        symbol = f"{base}{quote}"
    except ValueError:
        return None
    
    interval_map = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h"}
    interval = interval_map.get(timeframe, "1h")
    params = {"symbol": symbol, "interval": interval, "limit": max(50, limit)}
    
    try:
        response = requests.get(f"{BINANCE_BASE}/api/v3/klines", params=params, timeout=20)
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
    except:
        return None

def fetch_data(exchange, pair, timeframe, limit):
    if exchange.lower().startswith("coinbase"):
        return fetch_coinbase_data(pair, timeframe, limit)
    elif exchange.lower().startswith("binance"):
        return fetch_binance_data(pair, timeframe, limit)
    else:
        return fetch_coinbase_data(pair, timeframe, limit)

def calculate_percentage_change(df, lookback):
    if len(df) < lookback:
        return None
    recent_data = df.tail(lookback)
    lowest_low = recent_data['low'].min()
    current_price = df['close'].iloc[-1]
    pct_change = ((current_price - lowest_low) / lowest_low) * 100
    return {
        'lowest_low': lowest_low,
        'current_price': current_price,
        'pct_change': pct_change
    }

def check_gates(df, lookback):
    if len(df) < max(lookback, 26):
        return False, "Insufficient data"
    close_prices = df['close']
    
    # MACD Gate
    if st.session_state.macd_enabled:
        macd, signal, histogram = calculate_macd(close_prices)
        if macd >= 0:
            return False, "MACD not below zero"
    
    # Histogram Gate
    if st.session_state.histogram_enabled:
        macd, signal, histogram = calculate_macd(close_prices)
        if histogram <= 0:
            return False, "Histogram not positive"
    
    # RSI Gate
    if st.session_state.rsi_enabled:
        rsi = calculate_rsi(close_prices)
        if rsi > st.session_state.rsi_threshold:
            return False, f"RSI above {st.session_state.rsi_threshold}"
    
    # Volume Gate
    if st.session_state.volume_enabled:
        recent_volume = df['volume'].iloc[-1]
        avg_volume = df['volume'].tail(20).mean()
        if recent_volume < (avg_volume * st.session_state.volume_threshold):
            return False, f"Volume below {st.session_state.volume_threshold}x"
    
    return True, "All gates passed"

def get_alert_level(pct_change):
    if pct_change >= 30:
        return "🔴 HIGH", "alert-high"
    elif pct_change >= 20:
        return "🟠 MEDIUM", "alert-med"
    elif pct_change >= 10:
        return "🟡 LOW", "alert-low"
    else:
        return "⚪ WEAK", ""

def scan_market():
    exchange = st.session_state.exchange
    quote = st.session_state.quote
    timeframe = st.session_state.timeframe
    lookback = st.session_state.lookback
    min_pct = st.session_state.min_pct
    
    # Get pairs
    if exchange.lower().startswith("coinbase"):
        pairs = get_coinbase_products(quote)
    else:
        pairs = get_binance_products(quote)
    
    pairs = pairs[:st.session_state.pairs_limit]
    results = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, pair in enumerate(pairs):
        status_text.text(f"Scanning {pair}... ({idx + 1}/{len(pairs)})")
        progress_bar.progress((idx + 1) / len(pairs))
        
        df = fetch_data(exchange, pair, timeframe, lookback + 50)
        if df is None or len(df) < lookback:
            continue
        
        pct_data = calculate_percentage_change(df, lookback)
        if pct_data is None:
            continue
        
        pct_change = pct_data['pct_change']
        
        # Filter positive only
        if pct_change <= 0:
            continue
        
        # Check minimum percentage
        if pct_change < min_pct:
            continue
        
        # Check gates
        gates_passed, gate_msg = check_gates(df, lookback)
        if not gates_passed:
            continue
        
        # Get alert level
        alert_level, alert_class = get_alert_level(pct_change)
        
        # Get additional metrics
        close_prices = df['close']
        macd, signal, histogram = calculate_macd(close_prices)
        rsi = calculate_rsi(close_prices) if len(df) >= 14 else 0
        
        results.append({
            'Pair': pair,
            'Alert': alert_level,
            '% Change': round(pct_change, 2),
            'Current Price': round(pct_data['current_price'], 8),
            'Lowest Low': round(pct_data['lowest_low'], 8),
            'MACD': round(macd, 6),
            'Histogram': round(histogram, 6),
            'RSI': round(rsi, 2),
            'Volume': round(df['volume'].iloc[-1], 2),
            'Alert Class': alert_class
        })
        
        time.sleep(0.1)
    
    progress_bar.empty()
    status_text.empty()
    
    return pd.DataFrame(results)

# Sidebar
st.sidebar.title("⚡ Crypto Momentum Tracker")

# Exchange selection
exchange_name = st.sidebar.selectbox(
    "Exchange",
    ['Coinbase', 'Binance'],
    index=0 if st.session_state.exchange == 'Coinbase' else 1,
    key='exchange_select'
)
st.session_state.exchange = exchange_name
set_url_params({'exchange': exchange_name})

# Quote selection
quote = st.sidebar.selectbox(
    "Quote Currency",
    ['USD', 'USDT', 'USDC', 'BTC', 'ETH'],
    index=['USD', 'USDT', 'USDC', 'BTC', 'ETH'].index(st.session_state.quote) if st.session_state.quote in ['USD', 'USDT', 'USDC', 'BTC', 'ETH'] else 0,
    key='quote_select'
)
st.session_state.quote = quote
set_url_params({'quote': quote})

# Timeframe selection
timeframes = ['5m', '15m', '1h', '4h']
timeframe = st.sidebar.selectbox(
    "Timeframe",
    timeframes,
    index=timeframes.index(st.session_state.timeframe) if st.session_state.timeframe in timeframes else 2,
    key='timeframe_select'
)
st.session_state.timeframe = timeframe
set_url_params({'timeframe': timeframe})

# Lookback period
lookback = st.sidebar.slider(
    "Lookback Period (candles)",
    min_value=5,
    max_value=100,
    value=st.session_state.lookback,
    key='lookback_slider'
)
st.session_state.lookback = lookback
set_url_params({'lookback': str(lookback)})

# Minimum percentage
min_pct = st.sidebar.slider(
    "Min % Change",
    min_value=0.0,
    max_value=100.0,
    value=st.session_state.min_pct,
    step=0.5,
    key='min_pct_slider'
)
st.session_state.min_pct = min_pct
set_url_params({'min_pct': str(min_pct)})

# Pairs discovery limit
pairs_limit = st.sidebar.slider(
    "Max Pairs to Scan",
    min_value=10,
    max_value=200,
    value=st.session_state.pairs_limit,
    step=10,
    key='pairs_limit_slider'
)
st.session_state.pairs_limit = pairs_limit
set_url_params({'pairs_limit': str(pairs_limit)})

st.sidebar.markdown("---")
st.sidebar.markdown("### 🚨 Alert Gates")

# MACD Gate
macd_enabled = st.sidebar.checkbox(
    "MACD Cross Below Zero",
    value=st.session_state.macd_enabled,
    key='macd_check'
)
st.session_state.macd_enabled = macd_enabled
set_url_params({'macd': str(macd_enabled).lower()})

# Histogram Gate
histogram_enabled = st.sidebar.checkbox(
    "Histogram Turning Positive",
    value=st.session_state.histogram_enabled,
    key='histogram_check'
)
st.session_state.histogram_enabled = histogram_enabled
set_url_params({'histogram': str(histogram_enabled).lower()})

# RSI Gate
rsi_enabled = st.sidebar.checkbox(
    "RSI Filter",
    value=st.session_state.rsi_enabled,
    key='rsi_check'
)
st.session_state.rsi_enabled = rsi_enabled
set_url_params({'rsi': str(rsi_enabled).lower()})

if rsi_enabled:
    rsi_threshold = st.sidebar.slider(
        "RSI Threshold",
        min_value=20,
        max_value=50,
        value=int(st.session_state.rsi_threshold),
        key='rsi_slider'
    )
    st.session_state.rsi_threshold = rsi_threshold
    set_url_params({'rsi_threshold': str(rsi_threshold)})

# Volume Gate
volume_enabled = st.sidebar.checkbox(
    "Volume Spike",
    value=st.session_state.volume_enabled,
    key='volume_check'
)
st.session_state.volume_enabled = volume_enabled
set_url_params({'volume': str(volume_enabled).lower()})

if volume_enabled:
    volume_threshold = st.sidebar.slider(
        "Volume Multiplier",
        min_value=1.0,
        max_value=5.0,
        value=st.session_state.volume_threshold,
        step=0.1,
        key='volume_slider'
    )
    st.session_state.volume_threshold = volume_threshold
    set_url_params({'volume_threshold': str(volume_threshold)})

st.sidebar.markdown("---")

# Presets
st.sidebar.markdown("### 🎯 Quick Presets")
if st.sidebar.button("hioncrypto velocity mode"):
    st.session_state.timeframe = '1h'
    st.session_state.lookback = 24
    st.session_state.min_pct = 15.0
    st.session_state.macd_enabled = True
    st.session_state.histogram_enabled = True
    st.session_state.rsi_enabled = False
    st.session_state.volume_enabled = True
    st.session_state.volume_threshold = 2.0
    st.rerun()

if st.sidebar.button("Conservative Scanner"):
    st.session_state.timeframe = '4h'
    st.session_state.lookback = 48
    st.session_state.min_pct = 5.0
    st.session_state.macd_enabled = True
    st.session_state.histogram_enabled = False
    st.session_state.rsi_enabled = True
    st.session_state.rsi_threshold = 30
    st.session_state.volume_enabled = False
    st.rerun()

# Main interface
st.title("⚡ Crypto Momentum Tracker")
st.markdown(f"**Exchange:** {st.session_state.exchange.upper()} | **Quote:** {st.session_state.quote} | **Timeframe:** {st.session_state.timeframe} | **Lookback:** {st.session_state.lookback} candles")

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🔍 Scan Market", use_container_width=True):
        with st.spinner("Scanning market..."):
            results_df = scan_market()
            st.session_state.results = results_df

with col2:
    auto_refresh = st.checkbox("Auto-Refresh (60s)")

with col3:
    if st.button("🔗 Copy URL", use_container_width=True):
        st.info("URL updated with current settings - bookmark this page!")

# Display results
if 'results' in st.session_state and not st.session_state.results.empty:
    df = st.session_state.results.copy()
    df = df.sort_values('% Change', ascending=False)
    
    st.markdown(f"### 🎯 Found {len(df)} opportunities")
    
    # Display with color coding
    for _, row in df.iterrows():
        alert_class = row['Alert Class']
        if alert_class:
            st.markdown(f"<div class='{alert_class}'>{row['Pair']} - {row['Alert']} - {row['% Change']}%</div>", unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Display full dataframe
    display_df = df.drop('Alert Class', axis=1)
    st.dataframe(display_df, use_container_width=True, height=600)
    
    # Export
    csv = display_df.to_csv(index=False)
    st.download_button(
        "📥 Download Results (CSV)",
        csv,
        "crypto_momentum_results.csv",
        "text/csv"
    )
else:
    st.info("👆 Click 'Scan Market' to find momentum opportunities")

# Auto-refresh
if auto_refresh and 'results' in st.session_state:
    time.sleep(60)
    st.rerun()

# Footer
st.markdown("---")
st.markdown("**Settings automatically saved in URL - bookmark this page!**")
