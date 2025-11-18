import streamlit as st
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
from urllib.parse import urlencode, parse_qs

# Page config
st.set_page_config(page_title="Crypto Momentum Tracker", layout="wide", initial_sidebar_state="expanded")

# Custom CSS for mobile optimization
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

# Initialize exchanges
@st.cache_resource
def init_exchanges():
    return {
        'coinbase': ccxt.coinbase(),
        'binance': ccxt.binance()
    }

exchanges = init_exchanges()

# URL parameter handling
def get_url_params():
    try:
        query_params = st.query_params
        return {k: v for k, v in query_params.items()}
    except:
        return {}

def set_url_params(params):
    try:
        st.query_params.update(params)
    except:
        pass

url_params = get_url_params()

# Initialize session state from URL params
if 'initialized' not in st.session_state:
    st.session_state.initialized = True
    st.session_state.exchange = url_params.get('exchange', 'coinbase')
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

# Sidebar
st.sidebar.title("⚡ Crypto Momentum Tracker")

# Exchange selection
exchange_name = st.sidebar.selectbox(
    "Exchange",
    ['coinbase', 'binance'],
    index=0 if st.session_state.exchange == 'coinbase' else 1,
    key='exchange_select'
)
st.session_state.exchange = exchange_name

# Timeframe selection
timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
timeframe = st.sidebar.selectbox(
    "Timeframe",
    timeframes,
    index=timeframes.index(st.session_state.timeframe),
    key='timeframe_select'
)
st.session_state.timeframe = timeframe

# Lookback period
lookback = st.sidebar.slider(
    "Lookback Period (candles)",
    min_value=5,
    max_value=100,
    value=st.session_state.lookback,
    key='lookback_slider'
)
st.session_state.lookback = lookback

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

st.sidebar.markdown("---")
st.sidebar.markdown("### 🚨 Alert Gates")

# MACD Gate
macd_enabled = st.sidebar.checkbox(
    "MACD Cross Below Zero",
    value=st.session_state.macd_enabled,
    key='macd_check'
)
st.session_state.macd_enabled = macd_enabled

# Histogram Gate
histogram_enabled = st.sidebar.checkbox(
    "Histogram Turning Positive",
    value=st.session_state.histogram_enabled,
    key='histogram_check'
)
st.session_state.histogram_enabled = histogram_enabled

# RSI Gate
rsi_enabled = st.sidebar.checkbox(
    "RSI Filter",
    value=st.session_state.rsi_enabled,
    key='rsi_check'
)
st.session_state.rsi_enabled = rsi_enabled

if rsi_enabled:
    rsi_threshold = st.sidebar.slider(
        "RSI Threshold",
        min_value=20,
        max_value=50,
        value=int(st.session_state.rsi_threshold),
        key='rsi_slider'
    )
    st.session_state.rsi_threshold = rsi_threshold

# Volume Gate
volume_enabled = st.sidebar.checkbox(
    "Volume Spike",
    value=st.session_state.volume_enabled,
    key='volume_check'
)
st.session_state.volume_enabled = volume_enabled

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

# Update URL params
params = {
    'exchange': st.session_state.exchange,
    'timeframe': st.session_state.timeframe,
    'lookback': str(st.session_state.lookback),
    'min_pct': str(st.session_state.min_pct),
    'macd': str(st.session_state.macd_enabled).lower(),
    'histogram': str(st.session_state.histogram_enabled).lower(),
    'rsi': str(st.session_state.rsi_enabled).lower(),
    'rsi_threshold': str(st.session_state.rsi_threshold),
    'volume': str(st.session_state.volume_enabled).lower(),
    'volume_threshold': str(st.session_state.volume_threshold),
    'pairs_limit': str(st.session_state.pairs_limit)
}
set_url_params(params)

# Functions
def calculate_macd(close_prices, fast=12, slow=26, signal=9):
    """Calculate MACD indicator"""
    ema_fast = close_prices.ewm(span=fast, adjust=False).mean()
    ema_slow = close_prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line.iloc[-1], signal_line.iloc[-1], histogram.iloc[-1]

def calculate_rsi(close_prices, period=14):
    """Calculate RSI indicator"""
    delta = close_prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]

def get_pairs(exchange_name):
    """Get trading pairs from exchange"""
    try:
        exchange = exchanges[exchange_name]
        markets = exchange.load_markets()
        pairs = [symbol for symbol in markets.keys() if '/USD' in symbol or '/USDT' in symbol]
        return pairs[:st.session_state.pairs_limit]
    except Exception as e:
        st.error(f"Error loading pairs: {e}")
        return []

def fetch_ohlcv(exchange_name, pair, timeframe, lookback):
    """Fetch OHLCV data from exchange"""
    try:
        exchange = exchanges[exchange_name]
        ohlcv = exchange.fetch_ohlcv(pair, timeframe, limit=lookback + 50)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        return None

def calculate_percentage_change(df, lookback):
    """Calculate percentage change from lowest low in lookback period"""
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
    """Check if pair passes all enabled gates"""
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
    """Determine alert level based on percentage change"""
    if pct_change >= 30:
        return "🔴 HIGH", "alert-high"
    elif pct_change >= 20:
        return "🟠 MEDIUM", "alert-med"
    elif pct_change >= 10:
        return "🟡 LOW", "alert-low"
    else:
        return "⚪ WEAK", ""

def scan_market():
    """Scan market for momentum opportunities"""
    exchange_name = st.session_state.exchange
    timeframe = st.session_state.timeframe
    lookback = st.session_state.lookback
    min_pct = st.session_state.min_pct
    
    pairs = get_pairs(exchange_name)
    results = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, pair in enumerate(pairs):
        status_text.text(f"Scanning {pair}... ({idx + 1}/{len(pairs)})")
        progress_bar.progress((idx + 1) / len(pairs))
        
        df = fetch_ohlcv(exchange_name, pair, timeframe, lookback)
        if df is None or len(df) < lookback:
            continue
        
        # Calculate percentage change
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
        
        time.sleep(0.1)  # Rate limiting
    
    progress_bar.empty()
    status_text.empty()
    
    return pd.DataFrame(results)

# Main interface
st.title("⚡ Crypto Momentum Tracker")
st.markdown(f"**Exchange:** {st.session_state.exchange.upper()} | **Timeframe:** {st.session_state.timeframe} | **Lookback:** {st.session_state.lookback} candles")

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
    
    # Sort by percentage change
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
st.markdown("**Settings are automatically saved in URL - bookmark this page to save your configuration!**")
