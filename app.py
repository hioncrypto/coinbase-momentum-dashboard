# app.py — Crypto Tracker by hioncrypto
# One-file Streamlit app. See requirements.txt:
# streamlit>=1.33, pandas>=2.0, numpy>=1.24, requests>=2.31, websocket-client>=1.6

import json, time, datetime as dt, threading, queue, ssl, smtplib, re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
import requests
import streamlit as st

# Optional WebSocket for Coinbase live prices
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False
# ============================ PATCH PART 1 — TOP OF FILE (CSS + CollapseAll + Expander helper with Tips) ============================
# Put this block AFTER your imports and AFTER your initial st.set_page_config(...), BEFORE you start building the sidebar.

import contextlib

# --- Extra CSS to kill dimming/fade/skeleton shimmer on tables ---
st.markdown("""
<style>
/* kill any fade/opacity transition on dataframes/editors */
div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {
  opacity: 1 !important; filter: none !important;
}
div[data-testid="stDataFrame"] *, div[data-testid="stDataEditor"] * {
  opacity: 1 !important; filter: none !important; transition: none !important;
}
/* also cancel the temporary skeleton shimmer */
div[role="progressbar"], div[data-testid="stSkeleton"] {
  opacity: 0 !important; display: none !important;
}
</style>
""", unsafe_allow_html=True)

# --- Collapse/Expand all state (add if missing) ---
st.session_state.setdefault("collapse_all", False)
st.session_state.setdefault("exp_rev", 0)  # changes when buttons are pressed so expanders remount

# --- Tips registry: title -> tip text (auto-shown at bottom of each tab) ---
_TIPS = {
    "Market": "Tips: Watchlist symbols must end with your selected quote (e.g., -USD). If 'Use watchlist only' is off, discovery pulls all exchange pairs for the quote, capped by 'Pairs to discover'.",
    "Mode": "Tips: Hybrid = WebSocket + REST. If data looks stale or CPU spikes, try REST only.",
    "Timeframes": "Tips: Smaller TFs (15m/1h) show more movers. If the table is empty, lower 'Minimum bars' to ~20–30.",
    "Gates": "Tips: Start with Gate Mode = ANY and Hard filter OFF to see candidates. Δ lookback 1–3 is strict; raise it if nothing shows. MACD Cross: increase 'Cross within last bars' to 5 and turn off 'Prefer below zero' if too few results.",
    "Indicator lengths": "Tips: Don’t overfit. RSI 14 and MACD 12/26/9 are sane baselines.",
    "History depth (for ATH/ATL)": "Tips: Only affects ATH/ATL columns, not gate checks.",
    "Display": "Tips: Global font size lives here. We also hard-disable Streamlit's fade effects.",
    "Notifications": "Tips: Configure SMTP in st.secrets for email; webhook receives a compact JSON payload.",
    "Listing Radar": "Tips: Watches exchanges/feeds for new or upcoming listings. A blinking badge appears when something is detected."
}

# --- Sidebar buttons: Collapse/Expand all (call this once at the very top of your st.sidebar block) ---
def sidebar_collapse_buttons():
    colA, colB = st.columns([1,1])
    with colA:
        if st.button("Collapse all", use_container_width=True):
            st.session_state["collapse_all"] = True
            st.session_state["exp_rev"] += 1
            st.rerun()
    with colB:
        if st.button("Expand all", use_container_width=True):
            st.session_state["collapse_all"] = False
            st.session_state["exp_rev"] += 1
            st.rerun()

# --- New expander helper that auto-injects tips and respects CollapseAll ---
@contextlib.contextmanager
def expander(title: str, base_key: str):
    """Use exactly like: with expander('Market','exp_market'): ..."""
    opened = not st.session_state.get("collapse_all", False)
    key = f"{base_key}_v{st.session_state.get('exp_rev',0)}"
    e = st.sidebar.expander(title, expanded=opened, key=key)
    with e:
        yield
        tip = _TIPS.get(title)
        if tip:
            # Use caption for short tips and info for meatier ones
            if len(tip) > 140:
                st.info(tip)
            else:
                st.caption(tip)

# --- HOW TO USE ---
# 1) At the very top of your existing "with st.sidebar:" block, insert: sidebar_collapse_buttons()
# 2) Replace your old expander() helper with this one (same name), and make sure you call it with a base_key:
#    with expander("Market", "exp_market"):
#    with expander("Mode", "exp_mode"):
#    with expander("Timeframes", "exp_tfs"):
#    with expander("Gates", "exp_gates"):
#    with expander("Indicator lengths", "exp_lens"):
#    with expander("History depth (for ATH/ATL)", "exp_hist"):
#    with expander("Display", "exp_disp"):
#    with expander("Notifications", "exp_notif"):
#    with expander("Listing Radar", "exp_lr"):   # if you have it
# ============================================================================================================



# ============================ PATCH PART 2 — DIAGNOSTICS/TABLES (adds Funnel line; safe to paste as-is) ============================
# Find your Diagnostics block that starts right before the tables and replace it with this whole block.

# ----------------------------- Diagnostics & Tables
diag_available   = locals().get("diag_available", len(pairs) if "pairs" in locals() else 0)
diag_capped      = locals().get("diag_capped",   len(pairs) if "pairs" in locals() else 0)
diag_fetched     = locals().get("diag_fetched",  0)
diag_skip_bars   = locals().get("diag_skip_bars",0)
diag_skip_api    = locals().get("diag_skip_api", 0)

st.caption(
    f"Diagnostics — Available: {diag_available} • Capped: {diag_capped} • "
    f"Fetched OK: {diag_fetched} • Skipped (bars): {diag_skip_bars} • "
    f"Skipped (API): {diag_skip_api} • Shown: {len(rows)}"
)

# NEW: funnel line so you can see where candidates die
st.caption(
    f"Funnel — Discovered: {diag_available} → After min bars/API: {diag_fetched} → After gates/hard filter: {len(rows)}"
)

df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair"])

if df.empty:
    st.info(
        "No rows to show. Try ANY mode, lower Min Δ, shorten lookback, reduce Minimum bars, "
        "enable Volume spike/MACD Cross, or increase discovery cap."
    )
else:
    # Determine TF column label safely
    _tf = locals().get("sort_tf", st.session_state.get("sort_tf", "1h"))
    chg_col = f"% Change ({_tf})"

    sort_desc_flag = locals().get("sort_desc", st.session_state.get("sort_desc", True))
    df = df.sort_values(chg_col, ascending=not sort_desc_flag, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index + 1)

    # Top-10 (greens only)
    st.subheader("📌 Top-10 (greens only)")
    top10 = df[df["_green"]].sort_values(chg_col, ascending=False, na_position="last").head(10)
    top10 = top10.drop(columns=["_green", "_yellow"], errors="ignore")
    if top10.empty:
        st.write("—")
    else:
        st.dataframe(top10, use_container_width=True)

    # All pairs
    st.subheader("📑 All pairs")
    show_df = df.drop(columns=["_green", "_yellow"], errors="ignore")
    st.dataframe(show_df, use_container_width=True)

    # Footer
    _exchange = locals().get("effective_exchange", "Coinbase")
    _quote    = st.session_state.get("quote", "USD")
    _mode_txt = st.session_state.get("gate_mode", locals().get("gate_mode", "ANY"))
    _hard     = st.session_state.get("hard_filter", locals().get("hard_filter", False))
    st.caption(
        f"Pairs shown: {len(df)} • Exchange: {_exchange} • Quote: {_quote} "
        f"• TF: {_tf} • Gate Mode: {_mode_txt} • Hard filter: {'On' if _hard else 'Off'}"
    )

# ---------------- Auto-refresh timer (unchanged; keep your existing logic or use this safe version)
if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = time.time()
_refresh_every = int(st.session_state.get("refresh_sec", 30))
remaining = _refresh_every - int(time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {_refresh_every}s (next in {max(0, remaining)}s)")
# ============================================================================================================


# ----------------------------- Constants
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
ALL_TFS = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}
QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

DEFAULT_FEEDS = [
    "https://blog.coinbase.com/feed",                 # best-effort
    "https://www.binance.com/en/support/announcement" # HTML parsed best-effort
]

DEFAULTS = dict(
    # Sorting & TF
    sort_tf="1h", sort_desc=True, min_bars=30,
    # Δ & ROC window
    lookback_candles=3, min_pct=3.0,
    # Gates toggles
    use_vol_spike=True, vol_mult=1.10, vol_window=20,
    use_rsi=False, rsi_len=14, min_rsi=55,
    use_macd=False, macd_fast=12, macd_slow=26, macd_sig=9, min_mhist=0.0,
    use_atr=False, atr_len=14, min_atr=0.5,
    use_trend=False, pivot_span=4, trend_within=48,
    use_roc=False, min_roc=1.0,
    # MACD cross gate
    use_macd_cross=True, macd_cross_bars=5, macd_cross_only_bull=True, macd_cross_below_zero=True, macd_hist_confirm_bars=3,
    # Gate mode
    gate_mode="ANY", hard_filter=False, K_green=3, Y_yellow=2, preset="Spike Hunter",
    # History depth
    basis="Daily", amount_daily=90, amount_hourly=24, amount_weekly=12,
    # Discovery cap
    discover_cap=400,
    # Market
    exchange="Coinbase", quote="USD",
    watchlist="BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD",
    use_watch=False, use_my_pairs=False, my_pairs="BTC-USD, ETH-USD, SOL-USD",
    # Display & refresh
    font_scale=1.0, refresh_sec=30,
    # Notifications
    email_to="", webhook_url="",
    # Listing Radar defaults
    lr_enabled=False, lr_watch_coinbase=True, lr_watch_binance=True,
    lr_watch_quotes="USD, USDT, USDC",
    lr_poll_sec=30, lr_upcoming_sec=300, lr_upcoming_window_h=48,
    lr_feeds=", ".join(DEFAULT_FEEDS),
)

# ----------------------------- Persistence via URL params
def _coerce(v, typ):
    if typ is bool: return str(v).lower() in {"1","true","yes","on"}
    if typ is int:
        try: return int(v)
        except: return None
    if typ is float:
        try: return float(v)
        except: return None
    return str(v)

PERSIST: Dict[str, Tuple[object, type]] = {
    # Market
    "exchange": (DEFAULTS["exchange"], str),
    "quote": (DEFAULTS["quote"], str),
    "use_watch": (DEFAULTS["use_watch"], bool),
    "watchlist": (DEFAULTS["watchlist"], str),
    "use_my_pairs": (DEFAULTS["use_my_pairs"], bool),
    "my_pairs": (DEFAULTS["my_pairs"], str),
    "discover_cap": (DEFAULTS["discover_cap"], int),
    # Mode
    "mode": ("REST only", str), "ws_chunk": (5, int),
    # TF
    "sort_tf": (DEFAULTS["sort_tf"], str), "sort_desc": (DEFAULTS["sort_desc"], bool),
    "min_bars": (DEFAULTS["min_bars"], int),
    # Δ/ROC
    "lookback_candles": (DEFAULTS["lookback_candles"], int), "min_pct": (DEFAULTS["min_pct"], float),
    "use_roc": (DEFAULTS["use_roc"], bool), "min_roc": (DEFAULTS["min_roc"], float),
    # Gates
    "use_vol_spike": (DEFAULTS["use_vol_spike"], bool), "vol_mult": (DEFAULTS["vol_mult"], float),
    "use_rsi": (DEFAULTS["use_rsi"], bool), "rsi_len": (DEFAULTS["rsi_len"], int), "min_rsi": (DEFAULTS["min_rsi"], int),
    "use_macd": (DEFAULTS["use_macd"], bool), "macd_fast": (DEFAULTS["macd_fast"], int),
    "macd_slow": (DEFAULTS["macd_slow"], int), "macd_sig": (DEFAULTS["macd_sig"], int), "min_mhist": (DEFAULTS["min_mhist"], float),
    "use_atr": (DEFAULTS["use_atr"], bool), "atr_len": (DEFAULTS["atr_len"], int), "min_atr": (DEFAULTS["min_atr"], float),
    "use_trend": (DEFAULTS["use_trend"], bool), "pivot_span": (DEFAULTS["pivot_span"], int), "trend_within": (DEFAULTS["trend_within"], int),
    # MACD cross
    "use_macd_cross": (DEFAULTS["use_macd_cross"], bool),
    "macd_cross_bars": (DEFAULTS["macd_cross_bars"], int),
    "macd_cross_only_bull": (DEFAULTS["macd_cross_only_bull"], bool),
    "macd_cross_below_zero": (DEFAULTS["macd_cross_below_zero"], bool),
    "macd_hist_confirm_bars": (DEFAULTS["macd_hist_confirm_bars"], int),
    # Mode
    "gate_mode": (DEFAULTS["gate_mode"], str), "hard_filter": (DEFAULTS["hard_filter"], bool),
    "K_green": (DEFAULTS["K_green"], int), "Y_yellow": (DEFAULTS["Y_yellow"], int), "preset": (DEFAULTS["preset"], str),
    # History
    "basis": (DEFAULTS["basis"], str),
    "amount_hourly": (DEFAULTS["amount_hourly"], int),
    "amount_daily": (DEFAULTS["amount_daily"], int),
    "amount_weekly": (DEFAULTS["amount_weekly"], int),
    # Display/Notif
    "font_scale": (DEFAULTS["font_scale"], float), "refresh_sec": (DEFAULTS["refresh_sec"], int),
    "email_to": ("", str), "webhook_url": ("", str),
    # Collapse
    "collapse_all": (False, bool),
    # Listing Radar
    "lr_enabled": (DEFAULTS["lr_enabled"], bool),
    "lr_watch_coinbase": (DEFAULTS["lr_watch_coinbase"], bool),
    "lr_watch_binance": (DEFAULTS["lr_watch_binance"], bool),
    "lr_watch_quotes": (DEFAULTS["lr_watch_quotes"], str),
    "lr_poll_sec": (DEFAULTS["lr_poll_sec"], int),
    "lr_upcoming_sec": (DEFAULTS["lr_upcoming_sec"], int),
    "lr_upcoming_window_h": (DEFAULTS["lr_upcoming_window_h"], int),
    "lr_feeds": (DEFAULTS["lr_feeds"], str),
}

def init_persisted_state():
    qp = st.query_params
    for k,(dflt,typ) in PERSIST.items():
        if k in qp:
            raw = qp[k] if not isinstance(qp[k], list) else qp[k][0]
            val = _coerce(raw, typ)
            if val is None: val = dflt
        else:
            val = dflt
        st.session_state.setdefault(k, val)

def sync_state_to_query_params():
    payload = {}
    for k in PERSIST.keys():
        v = st.session_state.get(k)
        if v is None: continue
        payload[k] = v if not isinstance(v,(list,tuple)) else ", ".join(v)
    if payload: st.query_params.update(payload)

def _init_runtime():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("last_refresh", time.time())
    # Listing Radar
    ss.setdefault("lr_baseline", {"Coinbase": set(), "Binance": set()})
    ss.setdefault("lr_events", [])
    ss.setdefault("lr_unacked", 0)
    ss.setdefault("lr_last_poll", 0.0)
    ss.setdefault("lr_last_upcoming_poll", 0.0)

_init_runtime()
init_persisted_state()

# ----------------------------- Indicators
def ema(s: pd.Series, span: int) -> pd.Series: return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    delta = close.diff()
    up = np.where(delta>0, delta, 0.0); dn = np.where(delta<0, -delta, 0.0)
    ru = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rd = pd.Series(dn, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = ru/(rd+1e-12)
    return 100 - 100/(1+rs)

def macd_core(close: pd.Series, fast=12, slow=26, signal=9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def atr(df: pd.DataFrame, length=14) -> pd.Series:
    h,l,c = df["high"], df["low"], df["close"]; pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def volume_spike(df: pd.DataFrame, window=20) -> float:
    if len(df) < window+1: return np.nan
    return float(df["volume"].iloc[-1] / (df["volume"].rolling(window).mean().iloc[-1] + 1e-12))

def find_pivots(close: pd.Series, span=3) -> Tuple[pd.Index,pd.Index]:
    n=len(close); highs=[]; lows=[]; v=close.values
    for i in range(span, n-span):
        if v[i]>v[i-span:i].max() and v[i]>v[i+1:i+1+span].max(): highs.append(i)
        if v[i]<v[i-span:i].min() and v[i]<v[i+1:i+1+span].min(): lows.append(i)
    return pd.Index(highs), pd.Index(lows)

def trend_breakout_up(df: pd.DataFrame, span=3, within_bars=48) -> bool:
    if df is None or len(df) < span*2+5: return False
    highs,_ = find_pivots(df["close"], span)
    if len(highs)==0: return False
    hi=int(highs[-1]); level=float(df["close"].iloc[hi])
    cross=None
    for j in range(hi+1, len(df)):
        if float(df["close"].iloc[j]) > level: cross=j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# ----------------------------- HTTP / candles
def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25); r.raise_for_status()
        return sorted(f"{p['base_currency']}-{p['quote_currency']}" for p in r.json() if p.get("quote_currency")==quote)
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25); r.raise_for_status()
        out=[]
        for s in r.json().get("symbols",[]):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote:
                out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange=="Coinbase": return coinbase_list_products(quote)
    if exchange=="Binance":  return binance_list_products(quote)
    return []

def fetch_candles(exchange: str, pair_dash: str, gran_sec: int,
                  start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    try:
        if exchange=="Coinbase":
            url=f"{CB_BASE}/products/{pair_dash}/candles?granularity={gran_sec}"
            params={}
            if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
            if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
            r=requests.get(url, params=params, timeout=25)
            if r.status_code!=200: return None
            arr=r.json()
            if not arr: return None
            df=pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"]=pd.to_datetime(df["ts"], unit="s", utc=True)
            return df.sort_values("ts").reset_index(drop=True)
        elif exchange=="Binance":
            base, quote = pair_dash.split("-"); symbol=f"{base}{quote}"
            interval_map={900:"15m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
            interval=interval_map.get(gran_sec)
            if not interval: return None
            params={"symbol":symbol,"interval":interval,"limit":1000}
            if start: params["startTime"]=int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            if end:   params["endTime"]=int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            r=requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=25)
            if r.status_code!=200: return None
            rows=[]
            for a in r.json():
                rows.append({"ts":pd.to_datetime(a[0],unit="ms",utc=True),
                             "open":float(a[1]),"high":float(a[2]),
                             "low":float(a[3]),"close":float(a[4]),"volume":float(a[5])})
            return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    except Exception:
        return None
    return None

def resample_ohlcv(df: pd.DataFrame, target_sec: int) -> Optional[pd.DataFrame]:
    if df is None or df.empty: return None
    d=df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    out=d.resample(f"{target_sec}s", label="right", closed="right").agg(agg).dropna()
    return out.reset_index()

def df_for_tf(exchange: str, pair: str, tf: str) -> Optional[pd.DataFrame]:
    sec=ALL_TFS[tf]
    if exchange=="Coinbase":
        if sec in {900,3600,21600,86400}: return fetch_candles(exchange, pair, sec)
        base=fetch_candles(exchange, pair, 3600); return resample_ohlcv(base, sec)
    elif exchange=="Binance":
        return fetch_candles(exchange, pair, sec)
    return None

@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":
        amount=max(1,min(amount,72)); gran=3600; start=end-dt.timedelta(hours=amount)
    elif basis=="Daily":
        amount=max(1,min(amount,365)); gran=86400; start=end-dt.timedelta(days=amount)
    else:
        amount=max(1,min(amount,52)); gran=86400; start=end-dt.timedelta(weeks=amount)
    out=[]; step=300; cursor_end=end
    while True:
        win=dt.timedelta(seconds=step*gran)
        cursor_start=max(start, cursor_end-win)
        if (cursor_end - cursor_start).total_seconds() < gran: break
        df=fetch_candles(exchange, pair, gran, start=cursor_start, end=cursor_end)
        if df is None or df.empty: break
        out.append(df); cursor_end=df["ts"].iloc[0]
        if cursor_end<=start: break
    if not out: return None
    hist=pd.concat(out, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if basis=="Weekly": hist = resample_ohlcv(hist, 7*86400)
    return hist

def ath_atl_info(hist: pd.DataFrame) -> dict:
    last=float(hist["close"].iloc[-1])
    idx_ath=int(hist["high"].idxmax()); idx_atl=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[idx_ath]); d_ath=pd.to_datetime(hist["ts"].iloc[idx_ath]).date().isoformat()
    atl=float(hist["low"].iloc[idx_atl]);  d_atl=pd.to_datetime(hist["ts"].iloc[idx_atl]).date().isoformat()
    return {"From ATH %": (last/ath-1)*100 if ath>0 else np.nan, "ATH date": d_ath,
            "From ATL %": (last/atl-1)*100 if atl>0 else np.nan, "ATL date": d_atl}

# ----------------------------- WebSocket
def ws_worker(product_ids, endpoint="wss://ws-feed.exchange.coinbase.com"):
    try:
        ws=websocket.WebSocket(); ws.connect(endpoint, timeout=10); ws.settimeout(1.0)
        ws.send(json.dumps({"type":"subscribe","channels":[{"name":"ticker","product_ids":product_ids}]}))
        st.session_state["ws_alive"]=True
        while st.session_state.get("ws_alive", False):
            try:
                msg=ws.recv()
                if not msg: continue
                d=json.loads(msg)
                if d.get("type")=="ticker":
                    pid=d.get("product_id"); px=d.get("price")
                    if pid and px: st.session_state["ws_prices"][pid]=float(px)
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break
    except Exception:
        pass
    finally:
        st.session_state["ws_alive"]=False
        try: ws.close()
        except Exception: pass

def start_ws_if_needed(exchange: str, pairs: List[str], chunk: int):
    if exchange!="Coinbase" or not WS_AVAILABLE: return
    if not st.session_state["ws_alive"]:
        pick=pairs[:max(2, min(chunk, len(pairs)))]
        t=threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start(); time.sleep(0.2)

# ----------------------------- Alerts
def send_email_alert(subject, body, recipient):
    try: cfg=st.secrets["smtp"]
    except Exception: return False, "SMTP not configured in st.secrets"
    try:
        msg=MIMEMultipart(); msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body,"plain"))
        ctx=ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port",465), context=ctx) as s:
            s.login(cfg["user"], cfg["password"]); s.sendmail(cfg["sender"], recipient, msg.as_string())
        return True, "Email sent"
    except Exception as e:
        return False, f"Email error: {e}"

def post_webhook(url, payload):
    try:
        r=requests.post(url, json=payload, timeout=10)
        return (200<=r.status_code<300), r.text
    except Exception as e:
        return False, str(e)

# ----------------------------- Gate evaluation
def build_gate_eval(df_tf: pd.DataFrame, settings: dict) -> Tuple[dict, int, str, int]:
    """
    Returns: meta, passed_count, chips_str, enabled_count
    Gates: Δ, Volume×, ROC, Trend, RSI, MACD hist, ATR%, MACD Cross
    """
    n = len(df_tf)
    lb = max(1, min(int(settings.get("lookback_candles", 3)), 100, n-1))
    last_close=float(df_tf["close"].iloc[-1]); ref_close=float(df_tf["close"].iloc[-lb])
    delta_pct=(last_close/ref_close - 1.0)*100.0
    g_delta = bool(delta_pct >= float(settings.get("min_pct", 0.0)))

    macd_line, signal_line, hist = macd_core(
        df_tf["close"],
        int(settings.get("macd_fast", 12)),
        int(settings.get("macd_slow", 26)),
        int(settings.get("macd_sig", 9)),
    )

    chips=[]; passed=0; enabled=0
    def chip(name, enabled_flag, ok, extra=""):
        if not enabled_flag:
            chips.append(f"{name}–")
        else:
            chips.append(f"{name}{'✅' if ok else '❌'}{extra}")

    # Δ (always enabled)
    passed += int(g_delta); enabled += 1
    chip("Δ", True, g_delta, f"({delta_pct:+.2f}%)")

    # Volume spike ×
    if settings.get("use_vol_spike", False):
        volx=volume_spike(df_tf, int(settings.get("vol_window", 20)))
        ok=bool(pd.notna(volx) and volx >= float(settings.get("vol_mult", 1.10)))
        passed+=int(ok); enabled+=1; chip(" V", True, ok, f"({volx:.2f}×)" if pd.notna(volx) else "")
    else: chip(" V", False, False)

    # ROC
    if settings.get("use_roc", False):
        roc=(df_tf["close"].iloc[-1]/df_tf["close"].iloc[-lb]-1.0)*100.0 if n>lb else np.nan
        ok=bool(pd.notna(roc) and roc >= float(settings.get("min_roc", 1.0)))
        passed+=int(ok); enabled+=1; chip(" R", True, ok, f"({roc:+.2f}%)" if pd.notna(roc) else "")
    else: chip(" R", False, False)

    # Trend breakout
    if settings.get("use_trend", False):
        ok=trend_breakout_up(df_tf, span=int(settings.get("pivot_span",4)), within_bars=int(settings.get("trend_within",48)))
        passed+=int(ok); enabled+=1; chip(" T", True, ok)
    else: chip(" T", False, False)

    # RSI
    if settings.get("use_rsi", False):
        rcur=float(rsi(df_tf["close"], int(settings.get("rsi_len",14))).iloc[-1])
        ok=bool(rcur >= float(settings.get("min_rsi",55)))
        passed+=int(ok); enabled+=1; chip(" S", True, ok, f"({rcur:.1f})")
    else: chip(" S", False, False)

    # MACD histogram
    if settings.get("use_macd", False):
        mh=float(hist.iloc[-1]); ok=bool(mh >= float(settings.get("min_mhist",0.0)))
        passed+=int(ok); enabled+=1; chip(" M", True, ok, f"({mh:.3f})")
    else: chip(" M", False, False)

    # ATR %
    if settings.get("use_atr", False):
        atr_pct=float((atr(df_tf, int(settings.get("atr_len",14))) / (df_tf["close"]+1e-12) * 100.0).iloc[-1])
        ok=bool(atr_pct >= float(settings.get("min_atr",0.5)))
        passed+=int(ok); enabled+=1; chip(" A", True, ok, f"({atr_pct:.2f}%)")
    else: chip(" A", False, False)

    # MACD Cross
    cross_meta = {"ok": False, "bars_ago": None, "below_zero": None}
    if settings.get("use_macd_cross", True):
        bars=int(settings.get("macd_cross_bars",5))
        only_bull=bool(settings.get("macd_cross_only_bull", True))
        need_below=bool(settings.get("macd_cross_below_zero", True))
        conf=int(settings.get("macd_hist_confirm_bars",3))

        ok=False; bars_ago=None; below=None
        for i in range(1, min(bars+1, len(hist))):
            prev = macd_line.iloc[-i-1] - signal_line.iloc[-i-1]
            now  = macd_line.iloc[-i]   - signal_line.iloc[-i]
            crossed_up = (prev < 0 and now > 0)
            crossed_dn = (prev > 0 and now < 0)
            hit = crossed_up if only_bull else (crossed_up or crossed_dn)
            if not hit: continue
            if need_below:
                if macd_line.iloc[-i] > 0 or signal_line.iloc[-i] > 0:
                    continue
                below=True
            else:
                below = (macd_line.iloc[-i] < 0 and signal_line.iloc[-i] < 0)
            if conf>0:
                conf_ok = any(hist.iloc[-k] > 0 for k in range(i, min(i+conf, len(hist))))
                if not conf_ok: 
                    continue
            ok=True; bars_ago=i; break

        cross_meta.update({"ok": ok, "bars_ago": bars_ago, "below_zero": below})
        passed+=int(ok); enabled+=1
        chip(" C", True, ok, f" ({bars_ago} bars ago)" if bars_ago is not None else f" (≤{bars})")
    else: chip(" C", False, False)

    meta={"delta_pct": delta_pct, "macd_cross": cross_meta}
    return meta, passed, " ".join(chips), enabled

# ----------------------------- Page & CSS
st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")
st.markdown(f"""
<style>
  html, body {{ font-size: {float(st.session_state.get('font_scale', DEFAULTS['font_scale']))}rem; }}
  /* soft blue sidebar headers */
  section[data-testid="stSidebar"] details summary {{
      background: rgba(30,144,255,0.18) !important; border-radius: 8px;
  }}
  /* blinking badge */
  @keyframes blinkRB {{
    0% {{ background:#e74c3c; }} 50% {{ background:#3498db; }} 100% {{ background:#e74c3c; }}
  }}
  .blink-badge {{
    display:inline-block; padding:3px 8px; color:white; border-radius:8px; font-weight:700; animation: blinkRB 1.1s linear infinite;
  }}
  /* kill fade/dim on tables */
  div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] * {{
      opacity: 1 !important; filter: none !important; transition: none !important;
  }}
</style>
""", unsafe_allow_html=True)

st.title("Crypto Tracker by hioncrypto")

# ----------------------------- Sidebar top strip
with st.sidebar:
    c1,c2,c3 = st.columns([1,1,1])
    with c1:
        if st.button("Collapse all", use_container_width=True):
            st.session_state["collapse_all"] = True
    with c2:
        if st.button("Expand all", use_container_width=True):
            st.session_state["collapse_all"] = False
    with c3:
        st.toggle("⭐ Use My Pairs only", key="use_my_pairs", value=st.session_state.get("use_my_pairs", False))

    with st.popover("Manage My Pairs"):
        st.caption("Comma-separated (e.g., BTC-USD, ETH-USDT)")
        current = st.text_area("Edit list", st.session_state.get("my_pairs", DEFAULTS["my_pairs"]))
        if st.button("Save My Pairs"):
            st.session_state["my_pairs"] = ", ".join([p.strip().upper() for p in current.split(",") if p.strip()])
            st.success("Saved.")

def expander(title: str):
    return st.sidebar.expander(title, expanded=not st.session_state.get("collapse_all", False))

# ----------------------------- MARKET
with expander("Market"):
    st.selectbox("Exchange", EXCHANGES, index=EXCHANGES.index(st.session_state["exchange"]), key="exchange")
    effective_exchange = "Coinbase" if "coming soon" in st.session_state["exchange"] else st.session_state["exchange"]
    if "coming soon" in st.session_state["exchange"]:
        st.info("This exchange is coming soon. Using Coinbase for data.")
    st.selectbox("Quote currency", QUOTES, index=QUOTES.index(st.session_state["quote"]), key="quote")
    st.checkbox("Use watchlist only (ignore discovery)", key="use_watch", value=st.session_state.get("use_watch", False))
    st.text_area("Watchlist", st.session_state.get("watchlist", DEFAULTS["watchlist"]), key="watchlist")

    # Available pool for caption
    if st.session_state["use_watch"] and st.session_state["watchlist"].strip():
        avail=[p.strip().upper() for p in st.session_state["watchlist"].split(",") if p.strip()]
        avail=[p for p in avail if p.endswith(f"-{st.session_state['quote']}")]
    elif st.session_state["use_my_pairs"]:
        avail=[p.strip().upper() for p in st.session_state["my_pairs"].split(",") if p.strip()]
        avail=[p for p in avail if p.endswith(f"-{st.session_state['quote']}")]
    else:
        avail=list_products(effective_exchange, st.session_state["quote"])
    st.slider(f"Pairs to discover (0–500) • Available: {len(avail)}", 0, 500,
              int(st.session_state.get("discover_cap", DEFAULTS["discover_cap"])), 10, key="discover_cap")

# ----------------------------- MODE
with expander("Mode"):
    st.radio("Data source", ["REST only","WebSocket + REST (hybrid)"],
             index=0 if st.session_state.get("mode","REST only")=="REST only" else 1, horizontal=True, key="mode")
    st.slider("WS subscribe chunk (Coinbase)", 2, 20, int(st.session_state.get("ws_chunk",5)), 1, key="ws_chunk")

# ----------------------------- TIMEFRAMES
with expander("Timeframes"):
    st.selectbox("Primary sort timeframe", TF_LIST, index=TF_LIST.index(st.session_state["sort_tf"]), key="sort_tf")
    st.checkbox("Sort descending (largest first)", key="sort_desc", value=st.session_state.get("sort_desc", True))
    st.slider("Minimum bars required (per pair)", 5, 200, int(st.session_state.get("min_bars", DEFAULTS["min_bars"])), 1, key="min_bars")

# ----------------------------- GATES
with expander("Gates"):
    st.radio("Preset", ["Spike Hunter","Early MACD Cross","Confirm Rally","None"],
             index=["Spike Hunter","Early MACD Cross","Confirm Rally","None"].index(st.session_state.get("preset","Spike Hunter")),
             horizontal=True, key="preset")

    # Apply presets (non-destructive for user-changed values later in the session)
    if st.session_state["preset"]=="Spike Hunter":
        st.session_state.update({"gate_mode":"ANY","hard_filter":False,"lookback_candles":3,"min_pct":3.0,
                                 "use_vol_spike":True,"vol_mult":1.10,"use_rsi":False,"use_macd":False,
                                 "use_trend":False,"use_roc":False,"use_macd_cross":False})
    elif st.session_state["preset"]=="Early MACD Cross":
        st.session_state.update({"gate_mode":"ANY","hard_filter":False,"lookback_candles":3,"min_pct":3.0,
                                 "use_vol_spike":True,"vol_mult":1.10,"use_rsi":True,"min_rsi":50,
                                 "use_macd":False,"use_trend":False,"use_roc":False,
                                 "use_macd_cross":True,"macd_cross_bars":5,"macd_cross_only_bull":True,
                                 "macd_cross_below_zero":True,"macd_hist_confirm_bars":3})
    elif st.session_state["preset"]=="Confirm Rally":
        st.session_state.update({"gate_mode":"Custom (K/Y)","hard_filter":True,"lookback_candles":2,"min_pct":5.0,
                                 "use_vol_spike":True,"vol_mult":1.20,"use_rsi":True,"min_rsi":60,
                                 "use_macd":True,"min_mhist":0.0,"use_trend":True,"pivot_span":4,"trend_within":48,
                                 "use_roc":False,"use_macd_cross":False,"K_green":3,"Y_yellow":2})

    st.radio("Gate Mode", ["ALL","ANY","Custom (K/Y)"],
             index=["ALL","ANY","Custom (K/Y)"].index(st.session_state.get("gate_mode","ANY")),
             horizontal=True, key="gate_mode")
    st.toggle("Hard filter (hide non-passers)", key="hard_filter", value=st.session_state.get("hard_filter", False))

    st.slider("Δ lookback (candles)", 0, 100, int(st.session_state.get("lookback_candles", DEFAULTS["lookback_candles"])), 1, key="lookback_candles")
    st.slider("Min +% change (Δ gate)", 0.0, 50.0, float(st.session_state.get("min_pct", DEFAULTS["min_pct"])), 0.5, key="min_pct")

    c1,c2,c3 = st.columns(3)
    with c1:
        st.toggle("Volume spike ×", key="use_vol_spike", value=st.session_state.get("use_vol_spike", True))
        st.slider("Spike multiple ×", 1.0, 5.0, float(st.session_state.get("vol_mult", 1.10)), 0.05, key="vol_mult")
    with c2:
        st.toggle("RSI", key="use_rsi", value=st.session_state.get("use_rsi", False))
        st.slider("Min RSI", 40, 90, int(st.session_state.get("min_rsi", 55)), 1, key="min_rsi")
    with c3:
        st.toggle("MACD hist", key="use_macd", value=st.session_state.get("use_macd", False))
        st.slider("Min MACD hist", 0.0, 2.0, float(st.session_state.get("min_mhist", 0.0)), 0.05, key="min_mhist")

    c4,c5,c6 = st.columns(3)
    with c4:
        st.toggle("ATR %", key="use_atr", value=st.session_state.get("use_atr", False))
        st.slider("Min ATR %", 0.0, 10.0, float(st.session_state.get("min_atr", 0.5)), 0.1, key="min_atr")
    with c5:
        st.toggle("Trend breakout (up)", key="use_trend", value=st.session_state.get("use_trend", False))
        st.slider("Pivot span (bars)", 2, 10, int(st.session_state.get("pivot_span", 4)), 1, key="pivot_span")
        st.slider("Breakout within (bars)", 5, 96, int(st.session_state.get("trend_within", 48)), 1, key="trend_within")
    with c6:
        st.toggle("ROC (rate of change)", key="use_roc", value=st.session_state.get("use_roc", False))
        st.slider("Min ROC %", 0.0, 50.0, float(st.session_state.get("min_roc", 1.0)), 0.5, key="min_roc")

    st.markdown("**MACD Cross (early entry)**")
    c7,c8,c9,c10 = st.columns(4)
    with c7:
        st.toggle("Enable MACD Cross", key="use_macd_cross", value=st.session_state.get("use_macd_cross", True))
    with c8:
        st.slider("Cross within last (bars)", 1, 10, int(st.session_state.get("macd_cross_bars", 5)), 1, key="macd_cross_bars")
    with c9:
        st.toggle("Bullish only", key="macd_cross_only_bull", value=st.session_state.get("macd_cross_only_bull", True))
    with c10:
        st.toggle("Prefer below zero", key="macd_cross_below_zero", value=st.session_state.get("macd_cross_below_zero", True))
    st.slider("Histogram > 0 within (bars)", 0, 10, int(st.session_state.get("macd_hist_confirm_bars", 3)), 1, key="macd_hist_confirm_bars")

    st.markdown("---")
    st.subheader("Color rules (Custom only)")
    st.selectbox("Gates needed to turn green (K)", list(range(1,8)),
                 index=int(st.session_state.get("K_green", DEFAULTS["K_green"]))-1, key="K_green")
    st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0, int(st.session_state.get("K_green", DEFAULTS["K_green"])))),
                 index=min(int(st.session_state.get("Y_yellow", DEFAULTS["Y_yellow"])),
                           int(st.session_state.get("K_green", DEFAULTS["K_green"]))-1), key="Y_yellow")

# ----------------------------- INDICATOR LENGTHS
with expander("Indicator lengths"):
    st.slider("RSI length", 5, 50, int(st.session_state.get("rsi_len", 14)), 1, key="rsi_len")
    st.slider("MACD fast EMA", 3, 50, int(st.session_state.get("macd_fast", 12)), 1, key="macd_fast")
    st.slider("MACD slow EMA", 5, 100, int(st.session_state.get("macd_slow", 26)), 1, key="macd_slow")
    st.slider("MACD signal", 3, 50, int(st.session_state.get("macd_sig", 9)), 1, key="macd_sig")
    st.slider("ATR length", 5, 50, int(st.session_state.get("atr_len", 14)), 1, key="atr_len")

# ----------------------------- HISTORY DEPTH
with expander("History depth (for ATH/ATL)"):
    st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=["Hourly","Daily","Weekly"].index(st.session_state.get("basis","Daily")), key="basis")
    if st.session_state["basis"]=="Hourly":
        st.slider("Hours (≤72)", 1, 72, int(st.session_state.get("amount_hourly", 24)), 1, key="amount_hourly")
    elif st.session_state["basis"]=="Daily":
        st.slider("Days (≤365)", 1, 365, int(st.session_state.get("amount_daily", 90)), 1, key="amount_daily")
    else:
        st.slider("Weeks (≤52)", 1, 52, int(st.session_state.get("amount_weekly", 12)), 1, key="amount_weekly")

# ----------------------------- DISPLAY
with expander("Display"):
    st.slider("Font size (global)", 0.8, 1.6, float(st.session_state.get("font_scale", 1.0)), 0.05, key="font_scale")

# ----------------------------- NOTIFICATIONS
with expander("Notifications"):
    st.text_input("Email recipient (optional)", st.session_state.get("email_to",""), key="email_to")
    st.text_input("Webhook URL (optional)", st.session_state.get("webhook_url",""), key="webhook_url")

# ----------------------------- LISTING RADAR
with expander("Listing Radar"):
    if st.session_state.get("lr_unacked", 0) > 0:
        st.markdown('<span class="blink-badge">New/Upcoming listings</span>', unsafe_allow_html=True)
    st.toggle("Enable Listing Radar", key="lr_enabled", value=st.session_state.get("lr_enabled", False))
    cA, cB = st.columns(2)
    with cA:
        st.toggle("Watch Coinbase", key="lr_watch_coinbase", value=st.session_state.get("lr_watch_coinbase", True))
        st.toggle("Watch Binance", key="lr_watch_binance", value=st.session_state.get("lr_watch_binance", True))
        st.text_input("Quotes to watch (CSV)", st.session_state.get("lr_watch_quotes", "USD, USDT, USDC"), key="lr_watch_quotes")
        st.slider("Poll interval (seconds)", 10, 120, int(st.session_state.get("lr_poll_sec", 30)), 5, key="lr_poll_sec")
    with cB:
        st.text_area("Announcement feeds (comma-separated)", st.session_state.get("lr_feeds", ", ".join(DEFAULT_FEEDS)), key="lr_feeds")
        st.slider("Re-scan feeds every (seconds)", 60, 900, int(st.session_state.get("lr_upcoming_sec", 300)), 30, key="lr_upcoming_sec")
        st.slider("Upcoming alert window (hours)", 6, 168, int(st.session_state.get("lr_upcoming_window_h", 48)), 6, key="lr_upcoming_window_h")
    if st.button("Acknowledge all alerts"):
        st.session_state["lr_unacked"] = 0
        st.success("Alerts acknowledged.")

# persist to URL
sync_state_to_query_params()

# ----------------------------- Header label
st.markdown(f"<div style='font-size:1.3rem;font-weight:700;margin:4px 0 10px 2px;'>Timeframe: {st.session_state['sort_tf']}</div>", unsafe_allow_html=True)

# ----------------------------- Discovery pool
if st.session_state["use_my_pairs"]:
    pairs=[p.strip().upper() for p in st.session_state.get("my_pairs","").split(",") if p.strip()]
else:
    if st.session_state["use_watch"] and st.session_state["watchlist"].strip():
        pairs=[p.strip().upper() for p in st.session_state["watchlist"].split(",") if p.strip()]
    else:
        pairs=list_products(effective_exchange, st.session_state["quote"])
        pairs=[p for p in pairs if p.endswith(f"-{st.session_state['quote']}")]
        cap=max(0, min(500, int(st.session_state.get("discover_cap", DEFAULTS["discover_cap"]))))
        pairs=pairs[:cap] if cap>0 else []

# WebSocket start
if pairs and st.session_state.get("mode","REST only").startswith("WebSocket") and effective_exchange=="Coinbase" and WS_AVAILABLE:
    start_ws_if_needed(effective_exchange, pairs, int(st.session_state.get("ws_chunk",5)))

# ----------------------------- Build rows + diagnostics
diag_available=len(pairs); diag_capped=len(pairs)
diag_fetched=0; diag_skip_bars=0; diag_skip_api=0

rows=[]
for pid in pairs:
    dft = df_for_tf(effective_exchange, pid, st.session_state["sort_tf"])
    if dft is None:
        diag_skip_api += 1
        continue
    if len(dft) < int(st.session_state.get("min_bars", 30)):
        diag_skip_bars += 1
        continue
    diag_fetched += 1
    dft = dft.tail(400).copy()

    last_price = float(dft["close"].iloc[-1])
    if effective_exchange=="Coinbase" and st.session_state["ws_prices"].get(pid):
        last_price = float(st.session_state["ws_prices"][pid])

    first_price = float(dft["close"].iloc[0])
    pct_display = (last_price/first_price - 1.0) * 100.0

    basis=st.session_state["basis"]
    amt = dict(Hourly=st.session_state["amount_hourly"],
               Daily=st.session_state["amount_daily"],
               Weekly=st.session_state["amount_weekly"])[basis]
    histdf=get_hist(effective_exchange, pid, basis, amt)
    if histdf is None or len(histdf)<10:
        athp,athd,atlp,atld=np.nan,"—",np.nan,"—"
    else:
        aa=ath_atl_info(histdf); athp,athd,atlp,atld=aa["From ATH %"],aa["ATH date"],aa["From ATL %"],aa["ATL date"]

    meta, passed, chips, enabled_cnt = build_gate_eval(dft, dict(
        lookback_candles=int(st.session_state["lookback_candles"]),
        min_pct=float(st.session_state["min_pct"]),
        use_vol_spike=st.session_state["use_vol_spike"], vol_mult=float(st.session_state["vol_mult"]), vol_window=DEFAULTS["vol_window"],
        use_rsi=st.session_state["use_rsi"], rsi_len=int(st.session_state.get("rsi_len", 14)), min_rsi=int(st.session_state["min_rsi"]),
        use_macd=st.session_state["use_macd"], macd_fast=int(st.session_state.get("macd_fast", 12)),
        macd_slow=int(st.session_state.get("macd_slow", 26)), macd_sig=int(st.session_state.get("macd_sig", 9)), min_mhist=float(st.session_state["min_mhist"]),
        use_atr=st.session_state["use_atr"], atr_len=int(st.session_state.get("atr_len", 14)), min_atr=float(st.session_state["min_atr"]),
        use_trend=st.session_state["use_trend"], pivot_span=int(st.session_state["pivot_span"]), trend_within=int(st.session_state["trend_within"]),
        use_roc=st.session_state["use_roc"], min_roc=float(st.session_state["min_roc"]),
        use_macd_cross=st.session_state.get("use_macd_cross", True),
        macd_cross_bars=int(st.session_state.get("macd_cross_bars", 5)),
        macd_cross_only_bull=st.session_state.get("macd_cross_only_bull", True),
        macd_cross_below_zero=st.session_state.get("macd_cross_below_zero", True),
        macd_hist_confirm_bars=int(st.session_state.get("macd_hist_confirm_bars", 3)),
    ))

    mode = st.session_state.get("gate_mode","ANY")
    if mode=="ALL":
        include=(enabled_cnt>0 and passed==enabled_cnt)
        is_green=include; is_yellow=(0<passed<enabled_cnt)
    elif mode=="ANY":
        include=(passed>=1)
        is_green=include; is_yellow=False
    else:  # Custom (K/Y)
        K=int(st.session_state["K_green"]); Y=int(st.session_state["Y_yellow"])
        include=True
        is_green=(passed>=K); is_yellow=(passed>=Y and passed<K)

    if st.session_state.get("hard_filter", False):
        if mode in {"ALL","ANY"} and not include: 
            continue
        if mode=="Custom (K/Y)" and not (is_green or is_yellow):
            continue

    rows.append({
        "Pair": pid,
        "Price": last_price,
        f"% Change ({st.session_state['sort_tf']})": pct_display,
        f"Δ% (last {max(1,int(st.session_state['lookback_candles']))} bars)": meta["delta_pct"],
        "From ATH %": athp, "ATH date": athd, "From ATL %": atlp, "ATL date": atld,
        "Gates": chips, "Strong Buy": "YES" if is_green else "—",
        "_green": is_green, "_yellow": is_yellow
    })

# ----------------------------- Diagnostics & Tables
# If your file already defines these diag_* counters above, this will just use them.
# Otherwise, the locals().get(...) fallbacks keep this block safe to paste.
diag_available   = locals().get("diag_available", len(pairs) if "pairs" in locals() else 0)
diag_capped      = locals().get("diag_capped",   len(pairs) if "pairs" in locals() else 0)
diag_fetched     = locals().get("diag_fetched",  0)
diag_skip_bars   = locals().get("diag_skip_bars",0)
diag_skip_api    = locals().get("diag_skip_api", 0)

st.caption(
    f"Diagnostics — Available: {diag_available} • Capped: {diag_capped} • "
    f"Fetched OK: {diag_fetched} • Skipped (bars): {diag_skip_bars} • "
    f"Skipped (API): {diag_skip_api} • Shown: {len(rows)}"
)

df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair"])

if df.empty:
    st.info(
        "No rows to show. Try ANY mode, lower Min Δ, shorten lookback, reduce Minimum bars, "
        "enable Volume spike/MACD Cross, or increase discovery cap."
    )
else:
    # Determine which TF label was used earlier in the script
    _tf = locals().get("sort_tf", st.session_state.get("sort_tf", "1h"))
    chg_col = f"% Change ({_tf})"

    # Sort and add rank column
    sort_desc_flag = locals().get("sort_desc", st.session_state.get("sort_desc", True))
    df = df.sort_values(chg_col, ascending=not sort_desc_flag, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index + 1)

    # ---------------- Top-10 (greens only)
    st.subheader("📌 Top-10 (greens only)")
    top10 = df[df["_green"]].sort_values(chg_col, ascending=False, na_position="last").head(10)
    top10 = top10.drop(columns=["_green", "_yellow"], errors="ignore")
    if top10.empty:
        st.write("—")
    else:
        st.dataframe(top10, use_container_width=True)

    # ---------------- All pairs
    st.subheader("📑 All pairs")
    show_df = df.drop(columns=["_green", "_yellow"], errors="ignore")
    st.dataframe(show_df, use_container_width=True)

    # Footer
    _exchange = locals().get("effective_exchange", "Coinbase")
    _quote    = st.session_state.get("quote", "USD")
    _mode_txt = st.session_state.get("gate_mode", locals().get("gate_mode", "ANY"))
    _hard     = st.session_state.get("hard_filter", locals().get("hard_filter", False))
    st.caption(
        f"Pairs shown: {len(df)} • Exchange: {_exchange} • Quote: {_quote} "
        f"• TF: {_tf} • Gate Mode: {_mode_txt} • Hard filter: {'On' if _hard else 'Off'}"
    )

# ---------------- Auto-refresh timer
# Keep the same behavior as earlier: use session_state timer and rerun when due.
if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = time.time()

_refresh_every = int(st.session_state.get("refresh_sec", DEFAULTS.get("refresh_sec", 30)))
remaining = _refresh_every - int(time.time() - st.session_state["last_refresh"])

if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {_refresh_every}s (next in {max(0, remaining)}s)")
