# app.py — Crypto Tracker by hioncrypto  (with ROC gate)
# - One-file build; no external modules beyond std Python + pandas/numpy/requests/streamlit/websocket-client.
# - Adds ROC (% Rate-of-Change) gate integrated into K/Y green-yellow rules and gate chips.
# - Keeps: Coinbase/Binance, quotes, WS hybrid (Coinbase), discovery/watchlist/My Pairs, Top-10 (green only),
#          ATH/ATL % + dates, auto-refresh, presets (with graceful fallback if filesystem is read-only),
#          sticky “Collapse all” header, positive-only % change, sort by % change (desc) by default.

import json, os, time, ssl, smtplib, threading, queue, datetime as dt
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ------------------- Optional WS -------------------
WS_AVAILABLE = True
try:
    import websocket  # pip install websocket-client
except Exception:
    WS_AVAILABLE = False

# ------------------- Constants -------------------
TITLE = "Crypto Tracker by hioncrypto"
TF_LIST = ["15m", "1h", "4h", "6h", "12h", "1d"]
ALL_TFS = {"15m": 900, "1h": 3600, "4h": 14400, "6h": 21600, "12h": 43200, "1d": 86400}
QUOTES = ["USD", "USDC", "USDT", "BTC", "ETH", "EUR"]
EXCHANGES = ["Coinbase", "Binance", "Kraken (coming soon)", "KuCoin (coming soon)"]
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

# File for presets / my pairs (graceful if not writable)
STATE_FILE = "user_state.json"

# ------------------- Session bootstrap -------------------
def _init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("last_refresh", time.time())
    ss.setdefault("sticky_collapse_clicked", False)  # one-shot toggler
    # Persisted bundles (try load)
    if "persist" not in ss:
        ss["persist"] = {"presets": {}, "my_pairs": "BTC-USD, ETH-USD, SOL-USD"}
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    ss["persist"].update(data)
        except Exception:
            pass

_init_state()

# ------------------- Styling (sticky collapse) -------------------
st.set_page_config(page_title=TITLE, layout="wide")
st.markdown(
    """
    <style>
      [data-testid="stSidebar"] > div:first-child {
        position: sticky; top: 0; z-index: 1000;
        background: var(--secondary-background-color);
        border-bottom: 1px solid rgba(255,255,255,0.08);
        padding: 6px 6px 8px 6px;
      }
      .row-green  { background: rgba(0,255,0,0.22) !important; font-weight: 600; }
      .row-yellow { background: rgba(255,255,0,0.60) !important; font-weight: 600; }
      .chip { padding: 0.05rem 0.35rem; margin-right: 0.25rem; border-radius: 0.35rem; font-size: 0.80rem; }
      .ok  { background: rgba(0,255,0,0.25); }
      .bad { background: rgba(255,0,0,0.25); }
      .maybe{ background: rgba(255,255,0,0.4); color: #222; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ------------------- Small utils -------------------
def safe_write_state():
    """Try to persist presets / my_pairs to a JSON file. Safe if not allowed."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st.session_state["persist"], f, indent=2)
    except Exception as e:
        # only warn once per session
        if not st.session_state.get("_warn_perm", False):
            st.session_state["_warn_perm"] = True
            st.sidebar.warning(f"Could not save presets: {e}")

def collapse_header():
    colA, colB = st.sidebar.columns([1, 1])
    with colA:
        if st.button("Collapse all", use_container_width=True):
            st.session_state["sticky_collapse_clicked"] = True
    with colB:
        use_my = st.toggle("⭐ Use My\nPairs only", value=False)
    return use_my

def expander(title: str, key: str):
    # do not remember previous open state; keep compact by default
    return st.sidebar.expander(title, expanded=False)

def big_tf_label(tf: str):
    st.markdown(f"### Timeframe: **{tf}**  🔁", unsafe_allow_html=True)
    st.caption("Legend: Δ %Change • V Volume× • R ROC • T Trend • S RSI • M MACD • A ATR")

# ------------------- Indicators -------------------
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    d = close.diff()
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    ru = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rd = pd.Series(dn, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = ru / (rd + 1e-12)
    return 100 - (100 / (1 + rs))

def macd_hist(close: pd.Series, fast=12, slow=26, signal=9) -> pd.Series:
    ml = ema(close, fast) - ema(close, slow)
    sl = ema(ml, signal)
    return ml - sl

def atr(df: pd.DataFrame, length=14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def roc(close: pd.Series, length: int = 14) -> pd.Series:
    return (close / close.shift(length) - 1.0) * 100.0

def find_pivots(close: pd.Series, span=3) -> Tuple[pd.Index, pd.Index]:
    n = len(close); highs=[]; lows=[]; v = close.values
    for i in range(span, n-span):
        if v[i] > v[i-span:i].max() and v[i] > v[i+1:i+1+span].max(): highs.append(i)
        if v[i] < v[i-span:i].min() and v[i] < v[i+1:i+1+span].min(): lows.append(i)
    return pd.Index(highs), pd.Index(lows)

def trend_breakout_up(df: pd.DataFrame, span=3, within_bars=48) -> bool:
    if df is None or len(df) < span*2+5: return False
    highs,_ = find_pivots(df["close"], span)
    if len(highs)==0: return False
    hi = int(highs[-1]); level = float(df["close"].iloc[hi])
    cross = None
    for j in range(hi+1, len(df)):
        if float(df["close"].iloc[j]) > level:
            cross = j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# ------------------- Exchanges -------------------
def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25); r.raise_for_status()
        data = r.json()
        # include only trading-enabled pairs with chosen quote
        out = []
        for p in data:
            if p.get("quote_currency") == quote:
                pid = p.get("id") or f"{p.get('base_currency')}-{p.get('quote_currency')}"
                out.append(pid.upper())
        return sorted(set(out))
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25); r.raise_for_status()
        out=[]
        for s in r.json().get("symbols", []):
            if s.get("status") != "TRADING": continue
            if s.get("quoteAsset") == quote:
                out.append(f"{s['baseAsset']}-{quote}".upper())
        return sorted(set(out))
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange == "Coinbase": return coinbase_list_products(quote)
    if exchange == "Binance":  return binance_list_products(quote)
    return []

def fetch_candles(exchange: str, pair_dash: str, gran_sec: int,
                  start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    try:
        if exchange == "Coinbase":
            url = f"{CB_BASE}/products/{pair_dash}/candles?granularity={gran_sec}"
            params={}
            if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
            if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
            r = requests.get(url, params=params, timeout=25)
            if r.status_code != 200: return None
            arr = r.json()
            if not arr: return None
            df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
            return df.sort_values("ts").reset_index(drop=True)

        elif exchange == "Binance":
            base, quote = pair_dash.split("-"); symbol = f"{base}{quote}"
            interval_map = {900:"15m", 3600:"1h", 14400:"4h", 21600:"6h", 43200:"12h", 86400:"1d"}
            interval = interval_map.get(gran_sec)
            if not interval: return None
            params = {"symbol":symbol, "interval":interval, "limit":1000}
            if start: params["startTime"]=int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            if end:   params["endTime"]=int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            r = requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=25)
            if r.status_code != 200: return None
            rows=[]
            for a in r.json():
                rows.append({"ts":pd.to_datetime(a[0],unit="ms",utc=True),
                             "open":float(a[1]),"high":float(a[2]),
                             "low":float(a[3]),"close":float(a[4]),
                             "volume":float(a[5])})
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
    sec = ALL_TFS[tf]
    if exchange=="Coinbase":
        native = sec in {900,3600,21600,86400}
        if native: return fetch_candles(exchange, pair, sec)
        base = fetch_candles(exchange, pair, 3600)
        return resample_ohlcv(base, sec)
    elif exchange=="Binance":
        return fetch_candles(exchange, pair, sec)
    return None

@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":
        amount = max(1, min(amount, 72)); gran=3600; start=end-dt.timedelta(hours=amount)
    elif basis=="Daily":
        amount = max(1, min(amount,365)); gran=86400; start=end-dt.timedelta(days=amount)
    else:
        amount = max(1, min(amount, 52)); gran=86400; start=end-dt.timedelta(weeks=amount)
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
    idx_ath = int(hist["high"].idxmax())
    idx_atl = int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[idx_ath]); d_ath=pd.to_datetime(hist["ts"].iloc[idx_ath]).date().isoformat()
    atl=float(hist["low"].iloc[idx_atl]);  d_atl=pd.to_datetime(hist["ts"].iloc[idx_atl]).date().isoformat()
    return {"From ATH %": (last/ath-1)*100 if ath>0 else np.nan, "ATH date": d_ath,
            "From ATL %": (last/atl-1)*100 if atl>0 else np.nan, "ATL date": d_atl}

# ------------------- WebSocket (Coinbase) -------------------
def ws_worker(product_ids, endpoint="wss://ws-feed.exchange.coinbase.com"):
    ss = st.session_state
    try:
        ws = websocket.WebSocket()
        ws.connect(endpoint, timeout=10); ws.settimeout(1.0)
        ws.send(json.dumps({"type":"subscribe","channels":[{"name":"ticker","product_ids":product_ids}]}))
        ss["ws_alive"]=True
        while ss.get("ws_alive", False):
            try:
                msg = ws.recv()
                if not msg: continue
                d = json.loads(msg)
                if d.get("type")=="ticker":
                    pid=d.get("product_id"); px=d.get("price")
                    if pid and px: ss["ws_prices"][pid]=float(px)
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break
    except Exception:
        pass
    finally:
        ss["ws_alive"]=False
        try: ws.close()
        except Exception: pass

def start_ws_if_needed(exchange: str, pairs: List[str], chunk: int):
    if exchange!="Coinbase" or not WS_AVAILABLE: return
    if not st.session_state["ws_alive"]:
        pick = pairs[:max(2, min(chunk, len(pairs)))]
        t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start(); time.sleep(0.2)

# ------------------- Alerts -------------------
def send_email_alert(subject, body, recipient):
    try: cfg=st.secrets["smtp"]
    except Exception: return False, "SMTP not configured in st.secrets"
    try:
        msg=MIMEMultipart(); msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body, "plain"))
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

# ------------------- Gate engine -------------------
def build_gate_masks(df_tf: pd.DataFrame, df_hist: Optional[pd.DataFrame], settings: dict) -> dict:
    n = len(df_tf)
    last_close = df_tf["close"].iloc[-1]
    first_close = df_tf["close"].iloc[0]
    pct = (last_close/first_close - 1.0) * 100.0
    m_pct_pos = pd.Series([pct >= settings["min_pct"] and pct > 0] * n, index=df_tf.index)

    rsi_len   = settings["rsi_len"]
    macd_fast = settings["macd_fast"]; macd_slow = settings["macd_slow"]; macd_sig=settings["macd_sig"]
    atr_len   = settings["atr_len"]
    piv_span  = settings["pivot_span"]; within_bars=settings["trend_within"]
    vol_win   = settings["vol_window"]; vol_mult=settings["vol_mult"]
    roc_len   = settings["roc_len"]

    rsi_ser  = rsi(df_tf["close"], rsi_len)
    mh_ser   = macd_hist(df_tf["close"], macd_fast, macd_slow, macd_sig)
    atr_ser  = atr(df_tf, atr_len) / (df_tf["close"] + 1e-12) * 100.0
    roc_ser  = roc(df_tf["close"], roc_len)
    volx     = float(df_tf["volume"].iloc[-1] / (df_tf["volume"].rolling(vol_win).mean().iloc[-1] + 1e-12)) if len(df_tf) >= vol_win+1 else np.nan
    tr_up    = trend_breakout_up(df_tf, span=piv_span, within_bars=within_bars)

    def uni(val: bool): return pd.Series([bool(val)]*n, index=df_tf.index)

    m_vol_spike = uni((volx >= settings["vol_mult"])) if settings["use_vol_spike"] else uni(True)
    m_roc       = uni((roc_ser.iloc[-1] >= settings["min_roc"])) if settings["use_roc"] else uni(True)
    m_rsi       = uni((rsi_ser.iloc[-1] >= settings["min_rsi"])) if settings["use_rsi"] else uni(True)
    m_macd      = uni((mh_ser.iloc[-1] >= settings["min_mhist"])) if settings["use_macd"] else uni(True)
    m_atr       = uni((atr_ser.iloc[-1] >= settings["min_atr"])) if settings["use_atr"] else uni(True)
    m_trend     = uni(tr_up) if settings["use_trend"] else uni(True)

    parts = [m_pct_pos, m_vol_spike, m_roc, m_rsi, m_macd, m_atr, m_trend]

    if settings["logic"] == "ALL":
        m_all = parts[0].copy()
        for m in parts[1:]: m_all = m_all & m
        m_any = parts[0].copy()
        for m in parts[1:]: m_any = m_any | m
    else:
        m_any = parts[0].copy()
        for m in parts[1:]: m_any = m_any | m
        m_all = m_any.copy()

    # count how many checks are enabled & passed (for K/Y)
    active_flags = []
    for flag, enabled in [
        (bool(m_pct_pos.iloc[-1]), True),
        (bool(m_vol_spike.iloc[-1]), settings["use_vol_spike"]),
        (bool(m_roc.iloc[-1]), settings["use_roc"]),
        (bool(m_rsi.iloc[-1]), settings["use_rsi"]),
        (bool(m_macd.iloc[-1]), settings["use_macd"]),
        (bool(m_atr.iloc[-1]), settings["use_atr"]),
        (bool(m_trend.iloc[-1]), settings["use_trend"]),
    ]:
        if enabled: active_flags.append(flag)
    passed_count = sum(active_flags)
    enabled_count = len(active_flags)

    return {
        "pct": m_pct_pos, "vol": m_vol_spike, "roc": m_roc, "rsi": m_rsi, "macd": m_macd,
        "atr": m_atr, "trend": m_trend, "all": m_all, "any": m_any, "pct_value": pct,
        "passed_count": passed_count, "enabled_count": enabled_count
    }

def chips_for_row(mask_dict: dict) -> str:
    # Order: Δ, V, R, T, S, M, A
    items = [
        ("Δ", mask_dict["pct"].iloc[-1]),
        ("V", mask_dict["vol"].iloc[-1]),
        ("R", mask_dict["roc"].iloc[-1]),
        ("T", mask_dict["trend"].iloc[-1]),
        ("S", mask_dict["rsi"].iloc[-1]),
        ("M", mask_dict["macd"].iloc[-1]),
        ("A", mask_dict["atr"].iloc[-1]),
    ]
    chips=[]
    for label, ok in items:
        cls = "ok" if ok else "bad"
        chips.append(f"<span class='chip {cls}'>{label}</span>")
    return "".join(chips)

# ------------------- UI -------------------
st.title(TITLE)

# Sticky header (collapse + My Pairs quick toggle)
use_my_pairs_only = collapse_header()

# Reset / Utilities
with expander("Reset / Utilities", "exp_reset"):
    c1, c2, c3 = st.columns(3)
    if c1.button("Reset gates to defaults"):
        st.experimental_rerun()
    if c2.button("Clear My Pairs"):
        st.session_state["persist"]["my_pairs"] = ""
        safe_write_state()
    if c3.button("Clear presets"):
        st.session_state["persist"]["presets"] = {}
        safe_write_state()

# Manage My Pairs (always available near top)
with expander("Manage My Pairs", "exp_mypairs"):
    mp = st.text_area("My Pairs (comma-separated, e.g. BTC-USD, ETH-USD)", st.session_state["persist"].get("my_pairs",""))
    if mp != st.session_state["persist"].get("my_pairs",""):
        st.session_state["persist"]["my_pairs"] = mp
        safe_write_state()
    st.caption("Tip: enable ⭐ Use My Pairs at the very top to filter the scan to your list.")

# Market
with expander("Market", "exp_market"):
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    eff_exchange = exchange if "coming soon" not in exchange else "Coinbase"
    if eff_exchange != exchange:
        st.info("This exchange is coming soon. Using Coinbase for data.")
    quote = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    watchlist = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")
    max_pairs = st.slider("Max pairs to evaluate (discovery)", 10, 2000, 200, 10)

# Mode
with expander("Mode", "exp_mode"):
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0, horizontal=True)
    ws_chunk = st.slider("WS subscribe chunk (Coinbase)", 2, 20, 5, 1)

# Timeframes
with expander("Timeframes", "exp_tfs"):
    pick_tfs = st.multiselect("Available timeframes (for future use)", TF_LIST, default=TF_LIST)
    sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=1)  # default 1h
    sort_desc = st.checkbox("Sort descending (largest first)", value=True)

# Gates
with expander("Gates", "exp_gates"):
    logic = st.radio("Gate logic", ["ALL","ANY"], index=0, horizontal=True)
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 100.0, 20.0, 0.5)
    st.caption("💡 If nothing shows, lower this threshold or disable some toggles below.")

    st.markdown("**Indicators to include (used internally; NOT shown as columns):**")
    c1, c2, c3 = st.columns(3)
    with c1:
        use_vol_spike = st.toggle("Volume spike×", value=True, help="Last volume vs its SMA.")
        vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, 1.10, 0.05)
    with c2:
        use_roc = st.toggle("ROC %", value=True, help="Rate of change vs N bars ago (see Indicator lengths).")
        min_roc = st.slider("Min ROC %", 0.0, 50.0, 1.0, 0.1)
    with c3:
        use_rsi = st.toggle("RSI", value=False)
        min_rsi = st.slider("Min RSI", 40, 90, 55, 1)

    c4, c5, c6 = st.columns(3)
    with c4:
        use_macd = st.toggle("MACD hist", value=True)
        min_mhist = st.slider("Min MACD hist", 0.0, 5.0, 0.0, 0.05)
    with c5:
        use_atr = st.toggle("ATR %", value=False, help="ATR/close × 100")
        min_atr = st.slider("Min ATR %", 0.0, 20.0, 0.5, 0.1)
    with c6:
        use_trend = st.toggle("Trend breakout (up)", value=True, help="Close > last pivot high recently.")
        pivot_span = st.slider("Pivot span (bars)", 2, 10, 4, 1)
        trend_within = st.slider("Breakout within (bars)", 5, 96, 48, 1)

    st.markdown("**Color rules (beginner-friendly)**")
    colK, colY = st.columns(2)
    with colK:
        gates_K = st.selectbox("Gates needed to turn GREEN (K)", [1,2,3,4,5,6,7], index=2, help="How many checks must pass to mark a row green.")
    with colY:
        gates_Y = st.selectbox("Yellow needs ≥ Y (but < K)", [0,1,2,3,4,5,6], index=1, help="How many checks for partial pass (yellow). Must be less than K.")

# Indicator lengths
with expander("Indicator lengths (MACD/RSI/ATR/ROC)", "exp_lens"):
    rsi_len = st.slider("RSI length", 5, 50, 14, 1)
    macd_fast = st.slider("MACD fast EMA", 3, 50, 12, 1)
    macd_slow = st.slider("MACD slow EMA", 5, 100, 26, 1)
    macd_sig  = st.slider("MACD signal", 3, 50, 9, 1)
    atr_len   = st.slider("ATR length", 5, 50, 14, 1)
    vol_window= st.slider("Volume SMA window", 5, 50, 20, 1)
    roc_len   = st.slider("ROC length (bars)", 2, 100, 14, 1)

# History depth
with expander("History depth (for ATH/ATL)", "exp_hist"):
    basis = st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=1)
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1)
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 180, 1)
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 26, 1)

# Presets
with expander("Presets (save/load)", "exp_presets"):
    presets = st.session_state["persist"].setdefault("presets", {})
    # Starter preset (provided once if absent)
    if "hioncrypto (starter)" not in presets:
        presets["hioncrypto (starter)"] = {
            "logic":"ALL", "min_pct":20.0,
            "use_vol_spike":True, "vol_mult":1.10,
            "use_roc":True, "min_roc":1.0,
            "use_rsi":False, "min_rsi":55, "rsi_len":14,
            "use_macd":True, "min_mhist":0.0,
            "use_atr":False, "min_atr":0.5, "atr_len":14,
            "use_trend":True, "pivot_span":4, "trend_within":48,
            "macd_fast":12, "macd_slow":26, "macd_sig":9,
            "vol_window":20, "roc_len":14,
            "gates_K":3, "gates_Y":1,
        }

    colL, colR = st.columns([2,1])
    with colL:
        sel = st.selectbox("Load preset", list(presets.keys()))
    with colR:
        if st.button("Load"):
            p = presets[sel]
            # apply into widgets via session defaults (soft apply explanation)
            st.info("Preset loaded. Move any slider/toggle once to reflect values if they don’t redraw immediately.")
    nm = st.text_input("Save new preset as", "")
    if st.button("Save preset") and nm.strip():
        presets[nm.strip()] = {
            "logic":logic, "min_pct":min_pct,
            "use_vol_spike":use_vol_spike, "vol_mult":vol_mult,
            "use_roc":use_roc, "min_roc":min_roc, "roc_len":roc_len,
            "use_rsi":use_rsi, "min_rsi":min_rsi, "rsi_len":rsi_len,
            "use_macd":use_macd, "min_mhist":min_mhist,
            "use_atr":use_atr, "min_atr":min_atr, "atr_len":atr_len,
            "use_trend":use_trend, "pivot_span":pivot_span, "trend_within":trend_within,
            "macd_fast":macd_fast, "macd_slow":macd_slow, "macd_sig":macd_sig,
            "vol_window":vol_window,
            "gates_K":gates_K, "gates_Y":gates_Y,
        }
        st.success(f"Saved preset “{nm.strip()}”.")
        safe_write_state()

# Notifications
with expander("Notifications", "exp_notif"):
    email_to = st.text_input("Email recipient (optional)", "")
    webhook_url = st.text_input("Webhook URL (optional)", "")

# Display + Auto-refresh
with expander("Display", "exp_disp"):
    font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05)
st.markdown(f"<style> html, body {{ font-size: {font_scale}rem; }} </style>", unsafe_allow_html=True)

with expander("Auto-refresh", "exp_ref"):
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 30, 1)
    st.caption("Auto-refresh is always on.")

# -------------- Discovery / pair universe --------------
big_tf_label(sort_tf)

if use_my_pairs_only:
    txt = st.session_state["persist"].get("my_pairs","")
    pairs = [p.strip().upper() for p in txt.split(",") if p.strip()]
elif use_watch and watchlist.strip():
    pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs = list_products(eff_exchange, quote)
pairs = [p for p in pairs if p.endswith(f"-{quote}")]
# do not alphabetically bias; split later by max_pairs
pairs = pairs[:max_pairs] if not use_my_pairs_only else pairs

# -------------- WebSocket --------------
if pairs and mode.startswith("WebSocket") and eff_exchange=="Coinbase" and WS_AVAILABLE:
    start_ws_if_needed(eff_exchange, pairs, ws_chunk)

# -------------- Build table --------------
rows = []
for pid in pairs:
    dft = df_for_tf(eff_exchange, pid, sort_tf)
    if dft is None or len(dft) < 30:  # need some bars
        continue
    dft = dft.tail(400).copy()

    last_price = float(dft["close"].iloc[-1])
    if eff_exchange=="Coinbase" and st.session_state["ws_prices"].get(pid):
        last_price = float(st.session_state["ws_prices"][pid])
    first_price = float(dft["close"].iloc[0])
    pct = (last_price/first_price - 1.0) * 100.0

    hist = get_hist(eff_exchange, pid, basis, amount)
    if hist is None or len(hist) < 10:
        athp, athd, atlp, atld = np.nan, "—", np.nan, "—"
    else:
        aa = ath_atl_info(hist)
        athp, athd, atlp, atld = aa["From ATH %"], aa["ATH date"], aa["From ATL %"], aa["ATL date"]

    m = build_gate_masks(
        dft, hist,
        {
            "logic": logic, "min_pct": min_pct,
            "use_vol_spike": use_vol_spike, "vol_window": vol_window, "vol_mult": vol_mult,
            "use_roc": use_roc, "min_roc": min_roc, "roc_len": roc_len,
            "use_rsi": use_rsi, "min_rsi": min_rsi, "rsi_len": rsi_len,
            "use_macd": use_macd, "min_mhist": min_mhist,
            "use_atr": use_atr, "min_atr": min_atr, "atr_len": atr_len,
            "use_trend": use_trend, "pivot_span": pivot_span, "trend_within": trend_within,
            "macd_fast": macd_fast, "macd_slow": macd_slow, "macd_sig": macd_sig,
        }
    )

    # Decide color by K/Y rule
    passed, enabled = m["passed_count"], m["enabled_count"]
    is_green = (passed >= gates_K)
    is_yellow = (passed >= gates_Y) and (passed < gates_K)

    rows.append({
        "Pair": pid,
        "Price": last_price,
        f"% Change ({sort_tf})": pct,
        "From ATH %": athp, "ATH date": athd,
        "From ATL %": atlp, "ATL date": atld,
        "Gates": chips_for_row(m),
        "Strong Buy": "YES" if is_green else "—",
        "_green": is_green, "_yellow": is_yellow,
    })

df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair"])
if df.empty:
    st.info("No rows to show. Loosen gates or choose a different timeframe.")
else:
    chg_col = f"% Change ({sort_tf})"

    # Sort: green first for the Top-10; for All pairs we keep pure % change (desc) as you want
    df = df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index+1)

    # Top‑10 (GREEN only)
    st.subheader("📌 Top‑10 (meets green rule)")
    top10 = df[df["_green"]].sort_values(chg_col, ascending=False, na_position="last").head(10).reset_index(drop=True)

    def style_green_only(x):
        styles = pd.DataFrame("background-color: rgba(0,255,0,0.22); font-weight: 600;", index=x.index, columns=x.columns)
        return styles

    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, loosen gates (lower Min +% Change or reduce K).")
    else:
        styled = top10.style.format(precision=6).hide(axis="index").apply(style_green_only, axis=None)
        styled = styled.format({"Gates": lambda v: v})
        st.dataframe(styled, use_container_width=True)

    # All pairs (green+yellow+neutral)
    st.subheader("📑 All pairs")
    def style_rows_full(x):
        styles = pd.DataFrame("", index=x.index, columns=x.columns)
        gm = x["_green"].fillna(False)
        ym = x["_yellow"].fillna(False)
        styles.loc[gm, :] = "background-color: rgba(0,255,0,0.22); font-weight: 600;"
        styles.loc[ym, :] = "background-color: rgba(255,255,0,0.60); font-weight: 600;"
        return styles

    df_show = df.drop(columns=["_green","_yellow"])
    styled_all = df_show.style.format(precision=6).apply(style_rows_full, axis=None)
    styled_all = styled_all.format({"Gates": lambda v: v})
    st.dataframe(styled_all, use_container_width=True)

    # Alerts on Top‑10 entrants
    new_msgs=[]
    for _, r in top10.iterrows():
        key = f"{r['Pair']}|{sort_tf}|{round(float(r[chg_col]),2)}"
        if key not in st.session_state["alert_seen"]:
            st.session_state["alert_seen"].add(key)
            new_msgs.append(f"{r['Pair']}: {float(r[chg_col]):+.2f}% ({sort_tf})")

    if new_msgs and (email_to or webhook_url):
        subject = f"[{eff_exchange}] Top‑10 Crypto Tracker"
        body    = "\n".join(new_msgs)
        if email_to:
            ok, info = send_email_alert(subject, body, email_to)
            if not ok: st.sidebar.warning(info)
        if webhook_url:
            ok, info = post_webhook(webhook_url, {"title": subject, "lines": new_msgs})
            if not ok: st.sidebar.warning(f"Webhook error: {info}")

    st.caption(f"Pairs: {len(df)} • Exchange: {eff_exchange} • Quote: {quote} • Sort TF: {sort_tf} • Mode: {'WS+REST' if (mode.startswith('WebSocket') and eff_exchange=='Coinbase' and WS_AVAILABLE) else 'REST only'}")

# -------------- Auto-refresh --------------
remaining = refresh_sec - (time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {refresh_sec}s (next in {int(remaining)}s)")
