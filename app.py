# app.py — Crypto Tracker by hioncrypto
# One-file build with: Collapse-all, Resets, Presets/My Pairs persistence, Coinbase+Binance,
# timeframes (15m,1h,4h,6h,12h,1d), positive-only % change, K/Y gates, Top-10, Alerts, Auto-refresh.
#
# If disk is read-only, the app still runs (presets/My Pairs won't persist but no crashes).

import os, json, time, ssl, smtplib, datetime as dt, threading, queue
from typing import List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
import requests
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ----------------------------- Optional WebSocket
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

APP_TITLE = "Crypto Tracker by hioncrypto"

# ----------------------------- Globals / Constants
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
TF_SEC  = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}

QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

STATE_PATH = "./user_state.json"  # for presets & my pairs

# ----------------------------- Session init
def _init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("last_refresh", time.time())

    # UI behaviors
    ss.setdefault("collapse_now", False)

    # persistent buckets we try to load/save
    ss.setdefault("presets", {})
    ss.setdefault("my_pairs", [])

    # one-time disk load
    if not ss.get("disk_loaded", False):
        try:
            if os.path.exists(STATE_PATH):
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        ss["presets"] = data.get("presets", {})
                        ss["my_pairs"] = data.get("my_pairs", [])
        except Exception:
            pass
        # seed a helpful preset if empty
        if not ss["presets"]:
            ss["presets"]["hioncrypto (starter)"] = {
                "min_pct": 20.0,
                "use_vol_spike": True,  "vol_mult": 1.10,
                "use_rsi": False,       "min_rsi": 55,
                "use_macd": True,       "min_mhist": 0.0,
                "use_atr": False,       "min_atr": 0.5,
                "use_trend": True,      "pivot_span": 4, "trend_within": 48,
                "rsi_len": 14, "macd_fast":12, "macd_slow":26, "macd_sig":9,
                "atr_len":14, "vol_window":20,
                "gates_to_green": 3, "yellow_needed": 1
            }
        ss["disk_loaded"] = True

_init_state()

def save_state_to_disk():
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"presets": st.session_state["presets"],
                       "my_pairs": st.session_state["my_pairs"]}, f, indent=2)
        return True, "Saved"
    except Exception as e:
        return False, str(e)

# ----------------------------- Reset & Defaults
DEFAULTS = {
    # Market / Mode
    "use_watch_only": False, "watchlist": "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD",
    "all_pairs_toggle": True, "max_pairs": 200,
    "mode": "REST only", "ws_chunk": 10,
    # TF & sorting
    "sort_tf": "1h", "sort_desc": True,
    # Gates core
    "min_pct": 20.0,
    "use_vol_spike": True, "vol_mult": 1.10,
    "use_rsi": False, "min_rsi": 55,
    "use_macd": True, "min_mhist": 0.0,
    "use_atr": False, "min_atr": 0.5,
    "use_trend": True, "pivot_span": 4, "trend_within": 48,
    # Gate color thresholds
    "gates_to_green": 3, "yellow_needed": 1,  # K and Y
    # Indicator lengths
    "rsi_len": 14, "macd_fast": 12, "macd_slow": 26, "macd_sig": 9,
    "atr_len": 14, "vol_window": 20,
    # History depth
    "basis": "Daily", "amount": 90,
    # Display & refresh
    "font_scale": 1.0, "refresh_sec": 30,
}

def reset_all():
    for k, v in DEFAULTS.items():
        st.session_state[k] = v
    # do not wipe presets/my_pairs here; separate buttons handle those

def reset_gates_only():
    for k in ["min_pct","use_vol_spike","vol_mult","use_rsi","min_rsi",
              "use_macd","min_mhist","use_atr","min_atr","use_trend","pivot_span","trend_within",
              "gates_to_green","yellow_needed"]:
        st.session_state[k] = DEFAULTS[k]

def reset_indicator_lengths():
    for k in ["rsi_len","macd_fast","macd_slow","macd_sig","atr_len","vol_window"]:
        st.session_state[k] = DEFAULTS[k]

def reset_history_depth():
    st.session_state["basis"] = DEFAULTS["basis"]
    st.session_state["amount"] = DEFAULTS["amount"]

def reset_display():
    st.session_state["font_scale"] = DEFAULTS["font_scale"]

def reset_autorefresh():
    st.session_state["refresh_sec"] = DEFAULTS["refresh_sec"]

# ----------------------------- UI helpers
def sticky_collapse_header():
    st.sidebar.markdown("""
    <style>
      [data-testid="stSidebar"] > div:first-child {position: sticky; top: 0; z-index: 1000;}
      .hio-sticky {background: var(--secondary-background-color); padding: 8px; border-bottom: 1px solid rgba(255,255,255,0.1);}
    </style>
    """, unsafe_allow_html=True)
    with st.sidebar.container():
        st.markdown('<div class="hio-sticky">', unsafe_allow_html=True)
        c1, c2 = st.columns([1,1])
        with c1:
            if st.button("Collapse all", use_container_width=True):
                st.session_state["collapse_now"] = True
        with c2:
            st.toggle("⭐ Use My Pairs", key="use_my_pairs_global", value=False)
        st.markdown('</div>', unsafe_allow_html=True)
    # consume the flag just for this render (no auto-behavior on next rerun)
    flag = st.session_state.get("collapse_now", False)
    st.session_state["collapse_now"] = False
    return flag

def expander(title: str):
    # if user clicked collapse this render, start closed; else keep default behavior
    expanded = not st.session_state.get("collapse_once_used", False)
    return st.sidebar.expander(title, expanded=expanded)

def big_timeframe_label(tf: str):
    st.markdown(f"<div style='font-size:1.4rem;font-weight:700;margin:8px 0 4px 2px;'>Timeframe: {tf}</div>", unsafe_allow_html=True)

# ----------------------------- Indicators
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    roll_down = pd.Series(down, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / (roll_down + 1e-12)
    return 100 - (100 / (1 + rs))

def macd_hist(close: pd.Series, fast=12, slow=26, signal=9) -> pd.Series:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    return macd_line - signal_line

def atr(df: pd.DataFrame, length=14) -> pd.Series:
    h,l,c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def volume_spike(df: pd.DataFrame, window=20) -> float:
    if len(df) < window + 1: return np.nan
    return float(df["volume"].iloc[-1] / (df["volume"].rolling(window).mean().iloc[-1] + 1e-12))

def find_pivots(close: pd.Series, span=3) -> Tuple[pd.Index, pd.Index]:
    n=len(close); highs=[]; lows=[]; v=close.values
    for i in range(span, n-span):
        if v[i]>v[i-span:i].max() and v[i]>v[i+1:i+1+span].max(): highs.append(i)
        if v[i]<v[i-span:i].min() and v[i]<v[i+1:i+1+span].min(): lows.append(i)
    return pd.Index(highs), pd.Index(lows)

def trend_breakout_up(df: pd.DataFrame, span=3, within_bars=48) -> bool:
    if df is None or len(df) < span*2+5: return False
    highs,_ = find_pivots(df["close"], span)
    if len(highs)==0: return False
    hi = int(highs[-1]); level = float(df["close"].iloc[hi])
    cross=None
    for j in range(hi+1, len(df)):
        if float(df["close"].iloc[j]) > level:
            cross=j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# ----------------------------- Exchanges & data
def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25); r.raise_for_status()
        data = r.json()
        return sorted(f"{p['base_currency']}-{p['quote_currency']}" for p in data if p.get("quote_currency")==quote)
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r=requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25); r.raise_for_status()
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
            base, quote = pair_dash.split("-"); symbol=f"{base}{quote}"
            interval_map = {900:"15m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
            interval = interval_map.get(gran_sec)
            if not interval: return None
            params = {"symbol":symbol, "interval":interval, "limit":1000}
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
    sec = TF_SEC[tf]
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
    idx_ath=int(hist["high"].idxmax()); idx_atl=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[idx_ath]); d_ath=pd.to_datetime(hist["ts"].iloc[idx_ath]).date().isoformat()
    atl=float(hist["low"].iloc[idx_atl]);  d_atl=pd.to_datetime(hist["ts"].iloc[idx_atl]).date().isoformat()
    return {"From ATH %": (last/ath-1)*100 if ath>0 else np.nan, "ATH date": d_ath,
            "From ATL %": (last/atl-1)*100 if atl>0 else np.nan, "ATL date": d_atl}

# ----------------------------- Gates / masks
def build_gate_checks(df_tf: pd.DataFrame, settings: dict) -> Tuple[float, List[str], int]:
    """Return (pct_up, passed_labels, passed_count) for enabled gates.
       Gates: Δ, V, R, M, A, T
    """
    last_close = float(df_tf["close"].iloc[-1])
    first_close = float(df_tf["close"].iloc[0])
    pct_up = (last_close/first_close - 1.0) * 100.0

    # indicators
    rsi_len   = settings["rsi_len"]
    macd_fast = settings["macd_fast"]; macd_slow = settings["macd_slow"]; macd_sig=settings["macd_sig"]
    atr_len   = settings["atr_len"]
    piv_span  = settings["pivot_span"]; within_bars=settings["trend_within"]
    vol_win   = settings["vol_window"]; vol_mult=settings["vol_mult"]

    rsi_ser  = rsi(df_tf["close"], rsi_len)
    mh_ser   = macd_hist(df_tf["close"], macd_fast, macd_slow, macd_sig)
    atr_ser  = atr(df_tf, atr_len) / (df_tf["close"] + 1e-12) * 100.0
    volx     = volume_spike(df_tf, vol_win)
    tr_up    = trend_breakout_up(df_tf, span=piv_span, within_bars=within_bars)

    enabled_labels = []
    passed_labels  = []

    # Δ: min +% change, positive-only
    if settings["use_pct"]:
        enabled_labels.append("Δ")
        if pct_up >= settings["min_pct"] and pct_up > 0:
            passed_labels.append("Δ")

    if settings["use_vol_spike"]:
        enabled_labels.append("V")
        if (volx >= settings["vol_mult"]): passed_labels.append("V")

    if settings["use_rsi"]:
        enabled_labels.append("R")
        if float(rsi_ser.iloc[-1]) >= settings["min_rsi"]: passed_labels.append("R")

    if settings["use_macd"]:
        enabled_labels.append("M")
        if float(mh_ser.iloc[-1]) >= settings["min_mhist"]: passed_labels.append("M")

    if settings["use_atr"]:
        enabled_labels.append("A")
        if float(atr_ser.iloc[-1]) >= settings["min_atr"]: passed_labels.append("A")

    if settings["use_trend"]:
        enabled_labels.append("T")
        if bool(tr_up): passed_labels.append("T")

    # only count gates that are enabled
    passed_count = len([lab for lab in passed_labels if lab in enabled_labels])
    return pct_up, passed_labels, passed_count

# ----------------------------- Alerts
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

# ----------------------------- WebSocket (Coinbase)
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

def start_ws_if_needed(exchange: str, pairs: List[str], chunk: int=10):
    if exchange!="Coinbase" or not WS_AVAILABLE: return
    if not st.session_state["ws_alive"]:
        pick = pairs[:max(2, min(chunk, len(pairs)))]
        t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start(); time.sleep(0.2)

# ----------------------------- STREAMLIT APP
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)

# Sticky header (Collapse + My Pairs toggle)
collapse_clicked = sticky_collapse_header()
st.session_state["collapse_once_used"] = collapse_clicked

# Reset / Utilities
with st.sidebar.expander("Reset / Utilities", expanded=False):
    c1,c2 = st.columns(2)
    if c1.button("Reset ALL", use_container_width=True, type="primary"):
        reset_all(); st.rerun()
    if c2.button("Reset Gates", use_container_width=True):
        reset_gates_only(); st.rerun()

    c3,c4,c5 = st.columns(3)
    if c3.button("Indicators", use_container_width=True):
        reset_indicator_lengths(); st.rerun()
    if c4.button("History", use_container_width=True):
        reset_history_depth(); st.rerun()
    if c5.button("Refresh", use_container_width=True):
        reset_autorefresh(); st.rerun()

    c6,c7 = st.columns(2)
    if c6.button("Clear My Pairs", use_container_width=True):
        st.session_state["my_pairs"] = []
        save_state_to_disk()
        st.rerun()
    if c7.button("Clear Presets", use_container_width=True):
        st.session_state["presets"] = {}
        save_state_to_disk()
        st.rerun()

# Manage My Pairs
with st.sidebar.expander("Manage My Pairs", expanded=False):
    st.caption("Comma‑separated, e.g., BTC-USD, ETH-USD")
    mp_text = st.text_area("My Pairs", ", ".join(st.session_state["my_pairs"]))
    if st.button("Save My Pairs"):
        st.session_state["my_pairs"] = [p.strip().upper() for p in mp_text.split(",") if p.strip()]
        save_state_to_disk()
        st.success("Saved.")

# Market
with expander("Market"):
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    effective_exchange = exchange if "coming soon" not in exchange else "Coinbase"
    if "coming soon" in exchange:
        st.info("This exchange is coming soon. Using Coinbase for data.")
    quote = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch_only = st.checkbox("Use watchlist only (ignore discovery)",
                                 value=DEFAULTS["use_watch_only"])
    watchlist = st.text_area("Watchlist (comma-separated)",
                             DEFAULTS["watchlist"])
    co = st.columns([1,1])
    with co[0]:
        all_pairs_toggle = st.toggle("All pairs (discovery)", value=DEFAULTS["all_pairs_toggle"],
                                     help="ON = use all discovered pairs; OFF = limit via slider")
    with co[1]:
        max_pairs = st.slider("Max pairs (if not All)", 10, 2000, DEFAULTS["max_pairs"], 10)

# Mode
with expander("Mode"):
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0, horizontal=True)
    ws_chunk = st.slider("WS subscribe chunk (Coinbase)", 2, 50, DEFAULTS["ws_chunk"], 1)

# Timeframes
with expander("Timeframes"):
    pick_tfs = st.multiselect("Available timeframes", TF_LIST, default=TF_LIST)
    sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=1)  # default 1h
    sort_desc = st.checkbox("Sort descending (largest % first)", value=True)

# Gates
with expander("Gates"):
    st.slider("Min +% change (Sort TF)", 0.0, 100.0, DEFAULTS["min_pct"], 0.5, key="min_pct")
    c = st.columns(3)
    with c[0]:
        st.toggle("Volume spike×", value=DEFAULTS["use_vol_spike"], key="use_vol_spike")
        st.slider("Spike multiple ×", 1.0, 8.0, DEFAULTS["vol_mult"], 0.05, key="vol_mult")
    with c[1]:
        st.toggle("RSI", value=DEFAULTS["use_rsi"], key="use_rsi")
        st.slider("Min RSI", 40, 90, DEFAULTS["min_rsi"], 1, key="min_rsi")
        st.toggle("MACD hist", value=DEFAULTS["use_macd"], key="use_macd")
        st.number_input("Min MACD hist", min_value=0.0, max_value=3.0, value=DEFAULTS["min_mhist"], step=0.05, key="min_mhist")
    with c[2]:
        st.toggle("ATR %", value=DEFAULTS["use_atr"], key="use_atr", help="ATR/close × 100")
        st.slider("Min ATR %", 0.0, 10.0, DEFAULTS["min_atr"], 0.1, key="min_atr")
        st.toggle("Trend breakout (up)", value=DEFAULTS["use_trend"], key="use_trend")
        st.slider("Pivot span (bars)", 2, 10, DEFAULTS["pivot_span"], 1, key="pivot_span")
        st.slider("Breakout within (bars)", 5, 96, DEFAULTS["trend_within"], 1, key="trend_within")

    st.markdown("---")
    st.markdown("**Color rules**")
    K = st.selectbox("Gates needed to turn **GREEN** (K)", [1,2,3,4,5,6], index=DEFAULTS["gates_to_green"]-1, key="gates_to_green")
    Ymax = max(0, K-1)
    Y = st.selectbox("**YELLOW** needs ≥ Y (but < K)", list(range(0, Ymax+1)),
                     index=min(DEFAULTS["yellow_needed"], Ymax), key="yellow_needed")
    if Y >= K:
        st.warning("Yellow must be less than K (green). Lower Y or increase K.")

# Indicator lengths
with expander("Indicator lengths"):
    st.slider("RSI length", 5, 50, DEFAULTS["rsi_len"], 1, key="rsi_len")
    st.slider("MACD fast EMA", 3, 50, DEFAULTS["macd_fast"], 1, key="macd_fast")
    st.slider("MACD slow EMA", 5, 100, DEFAULTS["macd_slow"], 1, key="macd_slow")
    st.slider("MACD signal", 3, 50, DEFAULTS["macd_sig"], 1, key="macd_sig")
    st.slider("ATR length", 5, 50, DEFAULTS["atr_len"], 1, key="atr_len")
    st.slider("Volume SMA window", 5, 50, DEFAULTS["vol_window"], 1, key="vol_window")

# History
with expander("History depth (for ATH/ATL)"):
    basis = st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=1, key="basis")
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1, key="amount")
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 90, 1, key="amount")
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 12, 1, key="amount")

# Presets
with expander("Gate presets (persisted)"):
    presets = st.session_state["presets"]
    names = sorted(presets.keys())
    if names:
        sel = st.selectbox("Load preset", names, index=0)
        if st.button("Apply preset"):
            p = presets[sel]
            # Apply into current widgets
            st.session_state["min_pct"] = float(p.get("min_pct", DEFAULTS["min_pct"]))
            st.session_state["use_vol_spike"] = bool(p.get("use_vol_spike", DEFAULTS["use_vol_spike"]))
            st.session_state["vol_mult"] = float(p.get("vol_mult", DEFAULTS["vol_mult"]))
            st.session_state["use_rsi"] = bool(p.get("use_rsi", DEFAULTS["use_rsi"]))
            st.session_state["min_rsi"] = int(p.get("min_rsi", DEFAULTS["min_rsi"]))
            st.session_state["use_macd"] = bool(p.get("use_macd", DEFAULTS["use_macd"]))
            st.session_state["min_mhist"] = float(p.get("min_mhist", DEFAULTS["min_mhist"]))
            st.session_state["use_atr"] = bool(p.get("use_atr", DEFAULTS["use_atr"]))
            st.session_state["min_atr"] = float(p.get("min_atr", DEFAULTS["min_atr"]))
            st.session_state["use_trend"] = bool(p.get("use_trend", DEFAULTS["use_trend"]))
            st.session_state["pivot_span"] = int(p.get("pivot_span", DEFAULTS["pivot_span"]))
            st.session_state["trend_within"] = int(p.get("trend_within", DEFAULTS["trend_within"]))
            st.session_state["rsi_len"] = int(p.get("rsi_len", DEFAULTS["rsi_len"]))
            st.session_state["macd_fast"] = int(p.get("macd_fast", DEFAULTS["macd_fast"]))
            st.session_state["macd_slow"] = int(p.get("macd_slow", DEFAULTS["macd_slow"]))
            st.session_state["macd_sig"]  = int(p.get("macd_sig",  DEFAULTS["macd_sig"]))
            st.session_state["atr_len"] = int(p.get("atr_len", DEFAULTS["atr_len"]))
            st.session_state["vol_window"] = int(p.get("vol_window", DEFAULTS["vol_window"]))
            st.session_state["gates_to_green"] = int(p.get("gates_to_green", DEFAULTS["gates_to_green"]))
            st.session_state["yellow_needed"]  = int(p.get("yellow_needed",  DEFAULTS["yellow_needed"]))
            st.success(f"Applied preset: {sel}")

    st.markdown("—")
    newname = st.text_input("Save current as", "")
    if st.button("Save preset") and newname.strip():
        presets[newname.strip()] = {
            "min_pct": float(st.session_state["min_pct"]),
            "use_vol_spike": bool(st.session_state["use_vol_spike"]),
            "vol_mult": float(st.session_state["vol_mult"]),
            "use_rsi": bool(st.session_state["use_rsi"]),
            "min_rsi": int(st.session_state["min_rsi"]),
            "use_macd": bool(st.session_state["use_macd"]),
            "min_mhist": float(st.session_state["min_mhist"]),
            "use_atr": bool(st.session_state["use_atr"]),
            "min_atr": float(st.session_state["min_atr"]),
            "use_trend": bool(st.session_state["use_trend"]),
            "pivot_span": int(st.session_state["pivot_span"]),
            "trend_within": int(st.session_state["trend_within"]),
            "rsi_len": int(st.session_state["rsi_len"]),
            "macd_fast": int(st.session_state["macd_fast"]),
            "macd_slow": int(st.session_state["macd_slow"]),
            "macd_sig":  int(st.session_state["macd_sig"]),
            "atr_len":   int(st.session_state["atr_len"]),
            "vol_window":int(st.session_state["vol_window"]),
            "gates_to_green": int(st.session_state["gates_to_green"]),
            "yellow_needed":  int(st.session_state["yellow_needed"]),
        }
        ok, info = save_state_to_disk()
        if not ok:
            st.warning(f"Could not persist to disk: {info}")
        else:
            st.success("Preset saved.")

# Notifications
with expander("Notifications"):
    st.caption("Alerts send when a pair enters **Top‑10** (Green). Configure here:")
    email_to = st.text_input("Email recipient (optional)", "")
    webhook_url = st.text_input("Webhook URL (optional)", "")

# Display
with expander("Display"):
    font_scale = st.slider("Font size (global)", 0.8, 1.6, DEFAULTS["font_scale"], 0.05, key="font_scale")

# Auto-refresh
with expander("Auto-refresh"):
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, DEFAULTS["refresh_sec"], 1, key="refresh_sec")
    st.caption("Auto-refresh is always on (no deprecated APIs).")

# End collapse request
st.session_state["collapse_once_used"] = False

# Global style
st.markdown(f"""
<style>
  html, body {{ font-size: {st.session_state['font_scale']}rem; }}
  .row-green  {{ background: rgba(0,255,0,0.22) !important; font-weight: 600; }}
  .row-yellow {{ background: rgba(255,255,0,0.65) !important; font-weight: 600; }}
</style>
""", unsafe_allow_html=True)

# Timeframe headline
big_timeframe_label(sort_tf)
st.caption("Legend: Δ %Change • V Volume× • R RSI • M MACD • A ATR • T Trend")

# ----------------------------- Build universe
if st.session_state.get("use_my_pairs_global") and st.session_state["my_pairs"]:
    pairs = st.session_state["my_pairs"][:]
else:
    if use_watch_only and watchlist.strip():
        pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
    else:
        pairs = list_products(effective_exchange, quote)

pairs = [p for p in pairs if p.endswith(f"-{quote}")]

if not st.session_state["all_pairs_toggle"]:
    pairs = pairs[:st.session_state["max_pairs"]]  # user cap

# Start WS if requested (Coinbase only)
if pairs and mode.startswith("WebSocket") and effective_exchange=="Coinbase" and WS_AVAILABLE:
    start_ws_if_needed(effective_exchange, pairs, ws_chunk)

# ----------------------------- Compute rows
rows=[]
for pid in pairs:
    dft = df_for_tf(effective_exchange, pid, sort_tf)
    if dft is None or len(dft) < 30:
        continue
    dft = dft.tail(400).copy()

    last_price = float(dft["close"].iloc[-1])
    if effective_exchange=="Coinbase" and st.session_state["ws_prices"].get(pid):
        last_price = float(st.session_state["ws_prices"][pid])
    first_price = float(dft["close"].iloc[0])
    pct = (last_price/first_price - 1.0) * 100.0

    hist = get_hist(effective_exchange, pid, st.session_state["basis"], st.session_state["amount"])
    if hist is None or len(hist)<10:
        aa={"From ATH %": np.nan, "ATH date":"—","From ATL %": np.nan, "ATL date":"—"}
    else:
        aa = ath_atl_info(hist)

    settings_pack = {
        "use_pct": True,
        "min_pct": float(st.session_state["min_pct"]),
        "use_vol_spike": bool(st.session_state["use_vol_spike"]),
        "vol_window": int(st.session_state["vol_window"]),
        "vol_mult": float(st.session_state["vol_mult"]),
        "use_rsi": bool(st.session_state["use_rsi"]),
        "min_rsi": int(st.session_state["min_rsi"]),
        "rsi_len": int(st.session_state["rsi_len"]),
        "use_macd": bool(st.session_state["use_macd"]),
        "min_mhist": float(st.session_state["min_mhist"]),
        "macd_fast": int(st.session_state["macd_fast"]),
        "macd_slow": int(st.session_state["macd_slow"]),
        "macd_sig": int(st.session_state["macd_sig"]),
        "use_atr": bool(st.session_state["use_atr"]),
        "min_atr": float(st.session_state["min_atr"]),
        "atr_len": int(st.session_state["atr_len"]),
        "use_trend": bool(st.session_state["use_trend"]),
        "pivot_span": int(st.session_state["pivot_span"]),
        "trend_within": int(st.session_state["trend_within"]),
    }
    pct_up, passed_labels, passed_count = build_gate_checks(dft, settings_pack)

    K = int(st.session_state["gates_to_green"])
    Y = int(st.session_state["yellow_needed"])
    is_green  = (passed_count >= K) and (pct_up > 0)
    is_yellow = (passed_count >= Y) and (passed_count < K)

    enabled_labels = [lab for lab in ["Δ","V","R","M","A","T"]
                      if ((lab=="Δ" and settings_pack["use_pct"]) or
                          (lab=="V" and settings_pack["use_vol_spike"]) or
                          (lab=="R" and settings_pack["use_rsi"]) or
                          (lab=="M" and settings_pack["use_macd"]) or
                          (lab=="A" and settings_pack["use_atr"]) or
                          (lab=="T" and settings_pack["use_trend"]))]

    gate_chips = "".join([f"{'✅' if lab in passed_labels else '❌'}{lab} " for lab in enabled_labels]).strip()

    rows.append({
        "Pair": pid,
        "Price": last_price,
        f"% Change ({sort_tf})": pct_up,
        "From ATH %": aa["From ATH %"], "ATH date": aa["ATH date"],
        "From ATL %": aa["From ATL %"], "ATL date": aa["ATL date"],
        "Gates": gate_chips,
        "Strong Buy": "YES" if is_green else "—",
        "_green": is_green, "_yellow": is_yellow
    })

df = pd.DataFrame(rows)

# ----------------------------- Render
if df.empty:
    st.info("No rows to show. Loosen gates or choose a different timeframe.")
else:
    chg_col = f"% Change ({sort_tf})"
    # Default sort by % change desc; headers in st.dataframe aren’t clickable-sort, so this is the source of truth.
    df = df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index+1)

    def style_green(x):
        return pd.DataFrame("background-color: rgba(0,255,0,0.22); font-weight: 600;", index=x.index, columns=x.columns)

    def style_full(x):
        styles = pd.DataFrame("", index=x.index, columns=x.columns)
        gm = df["_green"].reindex(x.index, fill_value=False)
        ym = df["_yellow"].reindex(x.index, fill_value=False)
        styles.loc[gm, :] = "background-color: rgba(0,255,0,0.22); font-weight: 600;"
        styles.loc[ym, :] = "background-color: rgba(255,255,0,0.65); font-weight: 600;"
        return styles

    st.subheader("📌 Top‑10 (Green only)")
    top10 = df[df["_green"]].sort_values(chg_col, ascending=False, na_position="last").head(10).reset_index(drop=True)
    show_cols = ["#","Pair","Price",chg_col,"From ATH %","ATH date","From ATL %","ATL date","Gates","Strong Buy"]

    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, loosen gates (lower Min +% change or disable some toggles).")
    else:
        st.dataframe(top10[show_cols].style.apply(style_green, axis=None), use_container_width=True)

    st.subheader("📑 All pairs")
    st.dataframe(df[show_cols].style.apply(style_full, axis=None), use_container_width=True)

    # Alerts for Top‑10 entrants
    new_msgs=[]
    for _, r in top10.iterrows():
        key = f"{r['Pair']}|{sort_tf}|{round(float(r[chg_col]),2)}"
        if key not in st.session_state["alert_seen"]:
            st.session_state["alert_seen"].add(key)
            new_msgs.append(f"{r['Pair']}: {float(r[chg_col]):+.2f}% ({sort_tf})")

    if new_msgs:
        subject = f"[{effective_exchange}] Top‑10 Crypto Tracker"
        body    = "\n".join(new_msgs)
        if email_to:
            ok, info = send_email_alert(subject, body, email_to)
            if not ok: st.sidebar.warning(info)
        if webhook_url:
            ok, info = post_webhook(webhook_url, {"title": subject, "lines": new_msgs})
            if not ok: st.sidebar.warning(f"Webhook error: {info}")

    st.caption(f"Pairs: {len(df)} • Exchange: {effective_exchange} • Quote: {quote} • Sort TF: {sort_tf} • Mode: {'WS+REST' if (mode.startswith('WebSocket') and effective_exchange=='Coinbase' and WS_AVAILABLE) else 'REST only'}")

# ----------------------------- Auto-refresh
remaining = st.session_state["refresh_sec"] - (time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {st.session_state['refresh_sec']}s (next in {int(remaining)}s)")
