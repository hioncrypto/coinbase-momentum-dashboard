# app.py — Crypto Tracker by hioncrypto (all-in-one)
# Streamlit single-file app. Keep requirements.txt as I sent earlier.

import json, time, ssl, smtplib, threading, queue
import datetime as dt
from typing import List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
import requests
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------- Config & constants ----------
APP_TITLE = "Crypto Tracker by hioncrypto"
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"
QUOTES = ["USD", "USDC", "USDT", "BTC", "ETH", "EUR"]
EXCHANGES = ["Coinbase", "Binance", "Kraken (coming soon)", "KuCoin (coming soon)"]
TF_LIST = ["15m", "1h", "4h", "6h", "12h", "1d"]
ALL_TFS = {"15m": 900, "1h": 3600, "4h": 14400, "6h": 21600, "12h": 43200, "1d": 86400}
MAX_DISCOVERY_GUARD = 1500  # safety guard for free hosting

PRESETS_FILE = "/tmp/crypto_tracker_presets.json"
MYPAIRS_FILE = "/tmp/crypto_tracker_mypairs.json"

# websocket optional
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

# ---------- Helpers for local state ----------
def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: str, data) -> bool:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

def _init_state():
    ss = st.session_state
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("collapse_now", False)

    # persistent-ish (disk) user data
    ss.setdefault("user_presets", load_json(PRESETS_FILE, {}))
    ss.setdefault("my_pairs", load_json(MYPAIRS_FILE, []))
_init_state()

# ---------- Indicators ----------
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    roll_dn = pd.Series(down, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / (roll_dn + 1e-12)
    return 100 - 100/(1+rs)

def macd_hist(close: pd.Series, fast=12, slow=26, signal=9) -> pd.Series:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    return macd_line - signal_line

def atr(df: pd.DataFrame, length=14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def roc(close: pd.Series, length=9) -> pd.Series:
    return (close / close.shift(length) - 1.0) * 100.0

def volume_spike(df: pd.DataFrame, window=20) -> float:
    if len(df) < window + 1:
        return np.nan
    return float(df["volume"].iloc[-1] / (df["volume"].rolling(window).mean().iloc[-1] + 1e-12))

# Trend pivots
def find_pivots(close: pd.Series, span=3) -> Tuple[pd.Index, pd.Index]:
    n=len(close); highs=[]; lows=[]; v=close.values
    for i in range(span, n-span):
        if v[i]>v[i-span:i].max() and v[i]>v[i+1:i+1+span].max(): highs.append(i)
        if v[i]<v[i-span:i].min() and v[i]<v[i+1:i+1+span].min(): lows.append(i)
    return pd.Index(highs), pd.Index(lows)

def trend_breakout_up(df: pd.DataFrame, span=3, within_bars=48) -> bool:
    if df is None or len(df) < span*2+5:
        return False
    highs,_ = find_pivots(df["close"], span)
    if len(highs)==0:
        return False
    hi = int(highs[-1]); level = float(df["close"].iloc[hi])
    cross = None
    for j in range(hi+1, len(df)):
        if float(df["close"].iloc[j]) > level:
            cross = j; break
    if cross is None:
        return False
    return (len(df)-1 - cross) <= within_bars

# ---------- Market fetch ----------
def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25)
        r.raise_for_status()
        data = r.json()
        return sorted(f"{p['base_currency']}-{p['quote_currency']}"
                      for p in data if p.get("quote_currency")==quote)
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25)
        r.raise_for_status()
        out=[]
        for s in r.json().get("symbols", []):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote:
                out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange=="Coinbase": return coinbase_list_products(quote)
    if exchange=="Binance":  return binance_list_products(quote)
    # default (coming soon) -> fallback to Coinbase
    return coinbase_list_products(quote)

def fetch_candles(exchange: str, pair_dash: str, gran_sec: int,
                  start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    try:
        if exchange=="Coinbase" or "coming soon" in exchange:
            url = f"{CB_BASE}/products/{pair_dash}/candles?granularity={gran_sec}"
            params={}
            if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
            if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
            r = requests.get(url, params=params, timeout=25)
            if r.status_code!=200: return None
            arr = r.json()
            if not arr: return None
            df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
            return df.sort_values("ts").reset_index(drop=True)
        elif exchange=="Binance":
            base, quote = pair_dash.split("-")
            interval_map = {900:"15m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
            interval = interval_map.get(gran_sec)
            if not interval: return None
            params = {"symbol": f"{base}{quote}", "interval": interval, "limit": 1000}
            if start: params["startTime"]=int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            if end:   params["endTime"]=int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            r = requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=25)
            if r.status_code!=200: return None
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
    sec=ALL_TFS[tf]
    if exchange=="Coinbase" or "coming soon" in exchange:
        native = sec in {900,3600,21600,86400}
        if native: return fetch_candles("Coinbase", pair, sec)
        base = fetch_candles("Coinbase", pair, 3600)
        return resample_ohlcv(base, sec)
    elif exchange=="Binance":
        return fetch_candles("Binance", pair, sec)
    return None

@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    """Window for macro/micro ATH/ATL and breakout recency."""
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":
        amount = max(1,min(amount,72)); gran=3600; start=end-dt.timedelta(hours=amount)
    elif basis=="Daily":
        amount = max(1,min(amount,365)); gran=86400; start=end-dt.timedelta(days=amount)
    else:
        amount = max(1,min(amount,52)); gran=86400; start=end-dt.timedelta(weeks=amount)
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

def ath_atl_info(hist: pd.DataFrame) -> Dict[str,object]:
    last=float(hist["close"].iloc[-1])
    idx_ath=int(hist["high"].idxmax()); idx_atl=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[idx_ath]); d_ath=pd.to_datetime(hist["ts"].iloc[idx_ath]).date().isoformat()
    atl=float(hist["low"].iloc[idx_atl]);  d_atl=pd.to_datetime(hist["ts"].iloc[idx_atl]).date().isoformat()
    return {"ath_pct": (last/ath-1)*100 if ath>0 else np.nan, "ath_date": d_ath,
            "atl_pct": (last/atl-1)*100 if atl>0 else np.nan, "atl_date": d_atl}

# ---------- Gate logic ----------
def build_gate_outcomes(df_tf: pd.DataFrame, hist: Optional[pd.DataFrame], S: dict) -> Tuple[int, Dict[str,bool], Dict[str,float]]:
    """Return count of passed checks, detail booleans, and numeric values."""
    last = float(df_tf["close"].iloc[-1]); first = float(df_tf["close"].iloc[0])
    pct = (last/first - 1.0) * 100.0  # positive-only considered later
    passes = {}
    values = {"pct": pct}

    # Δ% positive and threshold
    passes["pct"] = (pct >= S["min_pct"]) and (pct > 0)

    # volume spike
    sp = volume_spike(df_tf, S["vol_window"])
    values["volx"] = sp
    passes["vol"] = (sp >= S["vol_mult"]) if S["use_vol_spike"] else True

    # ROC
    roc_ser = roc(df_tf["close"], S["roc_len"])
    roc_now = float(roc_ser.iloc[-1]) if not roc_ser.isna().iloc[-1] else np.nan
    values["roc"] = roc_now
    passes["roc"] = (roc_now >= S["min_roc"]) if S["use_roc"] else True

    # trend breakout
    tb = trend_breakout_up(df_tf, S["pivot_span"], S["trend_within"])
    passes["trend"] = tb if S["use_trend"] else True

    # RSI
    r = rsi(df_tf["close"], S["rsi_len"])
    r_now = float(r.iloc[-1]) if not r.isna().iloc[-1] else np.nan
    values["rsi"] = r_now
    passes["rsi"] = (r_now >= S["min_rsi"]) if S["use_rsi"] else True

    # MACD hist
    mh = macd_hist(df_tf["close"], S["macd_fast"], S["macd_slow"], S["macd_sig"])
    mh_now = float(mh.iloc[-1]) if not mh.isna().iloc[-1] else np.nan
    values["mh"] = mh_now
    passes["macd"] = (mh_now >= S["min_mhist"]) if S["use_macd"] else True

    # ATR%
    at = atr(df_tf, S["atr_len"]) / (df_tf["close"] + 1e-12) * 100.0
    at_now = float(at.iloc[-1]) if not at.isna().iloc[-1] else np.nan
    values["atrp"] = at_now
    passes["atr"] = (at_now >= S["min_atr"]) if S["use_atr"] else True

    # Count “enabled” checks actually evaluated (for legend text)
    enabled = sum([
        1,  # pct
        1 if S["use_vol_spike"] else 0,
        1 if S["use_roc"] else 0,
        1 if S["use_trend"] else 0,
        1 if S["use_rsi"] else 0,
        1 if S["use_macd"] else 0,
        1 if S["use_atr"] else 0,
    ])
    passes_count = sum(bool(passes[k]) for k in passes if (k!="pct" or True))  # pct always considered
    return enabled, passes, values

def chip_row(passes: Dict[str,bool]) -> str:
    # Order: Δ V R T S M A  (pct, vol, roc, trend, rsi, macd, atr)
    def sym(ok): return "✅" if ok else "❌"
    return f"Δ {sym(passes['pct'])}  V {sym(passes['vol'])}  R {sym(passes['roc'])}  T {sym(passes['trend'])}  S {sym(passes['rsi'])}  M {sym(passes['macd'])}  A {sym(passes['atr'])}"

# ---------- Alerts ----------
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

# ---------- Websocket (optional; Coinbase only) ----------
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
            except Exception:
                continue
    except Exception:
        pass
    finally:
        ss["ws_alive"]=False
        try: ws.close()
        except Exception: pass

def start_ws_if_needed(exchange: str, pairs: List[str], chunk: int=10):
    if exchange!="Coinbase" or not WS_AVAILABLE: return
    if not st.session_state["ws_alive"]:
        pick = pairs[:max(2, min(chunk, len(pairs)))]
        t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start(); time.sleep(0.2)

# ---------- UI ----------
st.set_page_config(page_title=APP_TITLE, layout="wide")

# Stronger blue buttons + row colors + sidebar tweaks
st.markdown("""
<style>
/* Buttons & widgets in sidebar */
section[data-testid="stSidebar"] .stButton button {background:#1e6bff!important; color:white!important; border:0!important;}
section[data-testid="stSidebar"] .stButton button:hover {filter:brightness(0.9);}
section[data-testid="stSidebar"] .stSelectbox, 
section[data-testid="stSidebar"] .stTextInput, 
section[data-testid="stSidebar"] .stNumberInput,
section[data-testid="stSidebar"] .stTextArea {border-radius:8px;}
/* Row highlights */
.row-green {background:rgba(0,255,0,0.22)!important; font-weight:600;}
.row-yellow {background:rgba(255,255,0,0.60)!important; font-weight:600;}
/* Make collapse button stick on top a bit */
div[data-testid="stSidebarNav"] {padding-top:0!important;}
</style>
""", unsafe_allow_html=True)

st.title(APP_TITLE)

# ---- Top-of-sidebar controls ----
with st.sidebar:
    colA, colB = st.columns([0.6,0.4])
    with colA:
        if st.button("Collapse all menu tabs", use_container_width=True):
            st.session_state["collapse_now"] = True
    with colB:
        use_my_pairs_only = st.toggle("⭐ Use My Pairs only", value=False, help="Show only the pairs you pin/save below.")

    # Simple Manage My Pairs expander
    with st.expander("Manage My Pairs", expanded=False):
        st.caption("Add pairs like `BTC-USD, ETH-USDT`. Click save to persist this session.")
        my_pairs_text = st.text_area("My Pairs", value=", ".join(st.session_state["my_pairs"]), height=80)
        if st.button("Save My Pairs"):
            lst=[p.strip().upper() for p in my_pairs_text.split(",") if p.strip()]
            st.session_state["my_pairs"] = list(dict.fromkeys(lst))
            if not save_json(MYPAIRS_FILE, st.session_state["my_pairs"]):
                st.warning("Could not persist My Pairs to disk (readonly). They remain for this session.")

def expander(title, key):
    opened = not st.session_state.get("collapse_now", False)
    return st.sidebar.expander(title, expanded=opened)

# ---- Market ----
with expander("Market", "exp_market"):
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    if "coming soon" in exchange:
        st.info("This exchange is coming soon — using Coinbase data temporarily.")
    effective_exchange = exchange if "coming soon" not in exchange else "Coinbase"

    quote = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    watchlist = st.text_area("Watchlist (comma-separated)",
                             "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD",
                             help="Only used if the box above is checked, or if '⭐ Use My Pairs only' is enabled.")
    # No hard cap; just a big guard in code
    st.caption("Discovery will try to include **all** tradable pairs for this quote on the selected exchange.")

# ---- Timeframes ----
with expander("Timeframes", "exp_tf"):
    sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=1, help="This TF drives the % Change column.")
    st.caption(f"Legend: Δ %Change • V Volume× • R ROC • T Trend • S RSI • M MACD • A ATR")

# ---- Gates & Presets ----
with expander("Gates", "exp_gates"):
    st.markdown("##### Hioncrypto presets")
    use_hion = st.toggle("Use hioncrypto’s preset", value=True, help="Toggle ON to load a pre-tuned set instantly.")
    preset_name = st.selectbox("Preset", ["Aggressive", "Balanced", "Conservative"], index=1)

    st.divider()

    logic = st.radio("Gate logic (for info)", ["ALL","ANY"], index=0, horizontal=True,
                     help="Coloring uses K/Y below; this logic label is informative to your strategy mindset.")

    # Defaults are semi-permissive
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 50.0, 5.0, 0.5,
                        help="If nothing shows, lower this threshold.")
    col1,col2,col3 = st.columns(3)
    with col1:
        use_vol_spike = st.toggle("Volume spike×", value=True, help="Last volume vs SMA window.")
        vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, 1.05, 0.05)
    with col2:
        use_roc = st.toggle("ROC %", value=True, help="Rate of change over N bars.")
        roc_len = st.slider("ROC length (bars)", 3, 60, 8, 1)
        min_roc = st.slider("Min ROC %", 0.0, 20.0, 0.30, 0.05)
    with col3:
        use_trend = st.toggle("Trend breakout (up)", value=True,
                              help="Close crosses above most recent pivot high within N bars.")

    col4,col5,col6 = st.columns(3)
    with col4:
        use_rsi = st.toggle("RSI", value=False); min_rsi = st.slider("Min RSI", 40, 90, 55, 1)
    with col5:
        use_macd = st.toggle("MACD hist", value=True)
        min_mhist = st.slider("Min MACD hist", 0.0, 2.0, 0.025, 0.005)
    with col6:
        use_atr = st.toggle("ATR %", value=False, help="ATR/close × 100")
        min_atr = st.slider("Min ATR %", 0.0, 10.0, 0.30, 0.1)

    st.markdown("**Color rules (green/yellow)** — beginner friendly")
    # K/Y as selectboxes (your request)
    k_green = st.selectbox("Gates needed to turn green (K)", list(range(1,8)), index=1)
    y_yellow = st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0,k_green)), index=0)

    # If using hion preset, override interactively (no apply)
    if use_hion:
        if preset_name=="Aggressive":
            min_pct, vol_mult, use_rsi, min_rsi, min_mhist, use_atr, min_atr = 3.0, 1.03, False, 55, 0.02, False, 0.3
            use_roc, roc_len, min_roc, use_trend = True, 6, 0.2, True
            k_green, y_yellow = 2, 1
        elif preset_name=="Balanced":
            min_pct, vol_mult, use_rsi, min_rsi, min_mhist, use_atr, min_atr = 5.0, 1.05, False, 55, 0.025, False, 0.3
            use_roc, roc_len, min_roc, use_trend = True, 8, 0.3, True
            k_green, y_yellow = 3, 1
        else:  # Conservative
            min_pct, vol_mult, use_rsi, min_rsi, min_mhist, use_atr, min_atr = 8.0, 1.1, True, 60, 0.05, True, 0.8
            use_roc, roc_len, min_roc, use_trend = True, 12, 0.5, True
            k_green, y_yellow = 4, 2

# ---- Indicator lengths ----
with expander("Indicator lengths", "exp_lens"):
    rsi_len = st.slider("RSI length", 5, 50, 14, 1)
    macd_fast = st.slider("MACD fast EMA", 3, 50, 12, 1)
    macd_slow = st.slider("MACD slow EMA", 5, 100, 26, 1)
    macd_sig  = st.slider("MACD signal", 3, 50, 9, 1)
    atr_len   = st.slider("ATR length", 5, 50, 14, 1)
    vol_window= st.slider("Volume SMA window", 5, 50, 20, 1)

# ---- Trend Break window (ATH/ATL history) ----
with expander("Trend Break window (for ATH/ATL)", "exp_hist"):
    basis = st.selectbox("Window basis", ["Hourly","Daily","Weekly"], index=1,
                         help="Macro + micro: use Weekly for big picture extremes, Hourly for recent swings.")
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1)
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 90, 1)
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 12, 1)

# ---- Notifications ----
with expander("Notifications", "exp_notif"):
    email_to = st.text_input("Email recipient (optional)", "", help="Configure SMTP in st.secrets to enable.")
    webhook_url = st.text_input("Webhook URL (optional)", "", help="Discord/Slack/etc. URL if you like.")

# ---- Auto-refresh ----
with expander("Auto-refresh", "exp_refresh"):
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 30, 1)
    st.caption("Auto-refresh is always on. Use smaller values for faster scanning.")

# reset collapse flag after building sidebar
st.session_state["collapse_now"] = False

# ---------- Build settings dict ----------
S = dict(
    logic=logic, min_pct=min_pct,
    use_vol_spike=use_vol_spike, vol_window=vol_window, vol_mult=vol_mult,
    use_roc=use_roc, roc_len=roc_len, min_roc=min_roc,
    use_trend=use_trend, pivot_span=4, trend_within=72,  # span fixed; recency generous
    use_rsi=use_rsi, min_rsi=min_rsi, rsi_len=rsi_len,
    use_macd=use_macd, min_mhist=min_mhist, macd_fast=macd_fast, macd_slow=macd_slow, macd_sig=macd_sig,
    use_atr=use_atr, min_atr=min_atr, atr_len=atr_len,
    k_green=k_green, y_yellow=y_yellow,
)

# ---------- Discover pairs ----------
if use_my_pairs_only and st.session_state["my_pairs"]:
    pairs = st.session_state["my_pairs"]
elif use_watch and watchlist.strip():
    pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs = list_products(effective_exchange, quote)

pairs = [p for p in pairs if p.endswith(f"-{quote}")]
pairs = list(dict.fromkeys(pairs))  # unique, preserve order
if len(pairs) > MAX_DISCOVERY_GUARD:
    st.warning(f"Discovered {len(pairs)} pairs; limiting to {MAX_DISCOVERY_GUARD} to keep your app responsive.")
    pairs = pairs[:MAX_DISCOVERY_GUARD]

# Optional websocket for faster prices
if pairs and effective_exchange=="Coinbase" and WS_AVAILABLE:
    start_ws_if_needed(effective_exchange, pairs, 10)

# ---------- Scan ----------
rows=[]
top10_msgs=[]
trend_break_msgs=[]

for pid in pairs:
    dft = df_for_tf(effective_exchange, pid, sort_tf)
    if dft is None or len(dft)<30: 
        continue
    dft = dft.tail(400).copy()

    # Price: override with WS tick if available
    last_price = float(dft["close"].iloc[-1])
    if effective_exchange=="Coinbase" and st.session_state["ws_prices"].get(pid):
        last_price = float(st.session_state["ws_prices"][pid])

    first_price = float(dft["close"].iloc[0])
    pct = (last_price/first_price - 1.0)*100.0

    # Macro/micro window for ATH/ATL
    hist = get_hist(effective_exchange, pid, basis, amount)
    if hist is None or len(hist)<10:
        ath_pct, ath_date, atl_pct, atl_date = np.nan, "—", np.nan, "—"
    else:
        aa = ath_atl_info(hist)
        ath_pct, ath_date, atl_pct, atl_date = aa["ath_pct"], aa["ath_date"], aa["atl_pct"], aa["atl_date"]

    enabled, passes, vals = build_gate_outcomes(dft, hist, S)
    passes_count = sum(1 for k in passes if passes[k])
    is_green  = passes_count >= S["k_green"]
    is_yellow = (passes_count >= S["y_yellow"]) and (passes_count < S["k_green"])

    # Chips
    gates_chip = chip_row(passes)

    # Build row
    rows.append(dict(
        Pair=pid, Price=last_price,
        **{f"% Change ({sort_tf})": pct},
        **{"From ATH %": ath_pct, "ATH date": ath_date, "From ATL %": atl_pct, "ATL date": atl_date},
        Gates=gates_chip, StrongBuy=("YES" if is_green else "—"),
        _green=is_green, _yellow=is_yellow
    ))

df = pd.DataFrame(rows)

# ---------- Display ----------
st.markdown(f"**Timeframe:** {sort_tf}  \n"
            f"**Discovery:** found {len(pairs)} exchange pairs • merged set {len(df) if not df.empty else 0}")

if df.empty:
    st.info("No rows to show. Tips: lower **Min +% change**, reduce **K** or toggle off some gates.")
else:
    chg_col = f"% Change ({sort_tf})"
    # Top-10 (ALL green)
    st.subheader("📌 Top‑10 (meets green rule)")
    top10 = df[df["_green"]].sort_values(chg_col, ascending=False, na_position="last").head(10).reset_index(drop=True)
    top10.insert(0, "#", top10.index+1)

    def style_green(x):
        styles = pd.DataFrame("background-color: rgba(0,255,0,0.22); font-weight:600;", index=x.index, columns=x.columns)
        return styles

    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, loosen gates (lower **Min +% change** or reduce **K**).")
    else:
        st.dataframe(top10[["#", "Pair", "Price", chg_col, "From ATH %", "ATH date", "From ATL %", "ATL date", "Gates", "StrongBuy"]]
                     .style.apply(style_green, axis=None), use_container_width=True)

    # All pairs with green/yellow coloring
    st.subheader("📑 All pairs")
    df_sorted = df.sort_values(chg_col, ascending=False, na_position="last").reset_index(drop=True)
    df_sorted.insert(0, "#", df_sorted.index+1)

    green_mask = df_sorted["_green"].fillna(False).values
    yellow_mask = df_sorted["_yellow"].fillna(False).values

    def style_rows(x):
        styles = pd.DataFrame("", index=x.index, columns=x.columns)
        styles.loc[green_mask, :]  = "background-color: rgba(0,255,0,0.22); font-weight:600;"
        styles.loc[yellow_mask, :] = "background-color: rgba(255,255,0,0.60); font-weight:600;"
        return styles

    show_cols = ["#", "Pair", "Price", chg_col, "From ATH %", "ATH date", "From ATL %", "ATL date", "Gates", "StrongBuy"]
    st.dataframe(df_sorted[show_cols].style.apply(style_rows, axis=None), use_container_width=True)

    # Alerts
    new_msgs=[]
    for _, r in top10.iterrows():
        key = f"TOP10|{r['Pair']}|{sort_tf}|{round(float(r[chg_col]),2)}"
        if key not in st.session_state["alert_seen"]:
            st.session_state["alert_seen"].add(key)
            new_msgs.append(f"Top‑10: {r['Pair']} {float(r[chg_col]):+.2f}% ({sort_tf})")
    # Trend-break alerts (from df rows) — simplistic: if green & trend passed
    for _, r in df.iterrows():
        if "T ✅" in r["Gates"]:  # naive parse
            key = f"TREND|{r['Pair']}|{sort_tf}"
            if key not in st.session_state["alert_seen"]:
                st.session_state["alert_seen"].add(key)
                trend_break_msgs.append(f"Trend‑break: {r['Pair']} ({sort_tf})")

    if new_msgs or trend_break_msgs:
        subject = f"[{effective_exchange}] Crypto Tracker"
        lines = new_msgs + trend_break_msgs
        if email_to:
            ok, info = send_email_alert(subject, "\n".join(lines), email_to)
            if not ok: st.warning(info)
        if webhook_url:
            ok, info = post_webhook(webhook_url, {"title": subject, "lines": lines})
            if not ok: st.warning(f"Webhook error: {info}")

# ---------- Auto-refresh ----------
remaining = refresh_sec - (time.time() - st.session_state.get("last_refresh", 0))
if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {refresh_sec}s (next in {int(remaining)}s)")

