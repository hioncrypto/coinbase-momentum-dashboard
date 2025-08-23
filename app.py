# app.py — Crypto Tracker by hioncrypto
# Fixes:
#  - Presets now save to ./user_presets/presets.json (instead of /mnt/data)
#  - Sticky "Collapse all menu tabs" in sidebar; no auto-open on reruns
#  - Discovery no longer stuck on 'A' symbols (supports "All pairs" toggle)
#
# Notes:
#  - Keeps your gates/green-yellow K+Y rules, Top-10 (% change desc), alerts,
#    “My Pairs”, emails/webhooks, multiple quotes, Coinbase/Binance, etc.

import os, json, time, ssl, smtplib, datetime as dt, threading, queue
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# -------------------- Optional WS
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

# -------------------- Constants
APP_TITLE = "Crypto Tracker by hioncrypto"
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
ALL_TFS = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}
QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

# -------------------- Preset storage (file-based, writable folder)
PRESET_DIR = os.path.join(".", "user_presets")
PRESET_FILE = os.path.join(PRESET_DIR, "presets.json")


def _init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    # Expander control: we do NOT auto-open/close on reruns
    ss.setdefault("collapse_all_now", False)
    # Presets
    ss.setdefault("gate_presets", {})
    ss.setdefault("loaded_default_presets", False)
    # refresh
    ss.setdefault("last_refresh", time.time())
_init_state()

# -------------------- UI helpers
def sticky_collapse_button():
    # CSS to keep the first block in sidebar sticky (button + My Pairs toggle row)
    st.sidebar.markdown("""
    <style>
      [data-testid="stSidebar"] > div:first-child {position: sticky; top: 0; z-index: 999;}
      .hio-sticky-wrap {background: var(--secondary-background-color); padding: 8px 8px 0 8px; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.1);}
      .hio-row {display:flex; gap:10px; align-items:center;}
    </style>
    """, unsafe_allow_html=True)
    with st.sidebar.container():
        with st.sidebar.container():
            st.markdown('<div class="hio-sticky-wrap">', unsafe_allow_html=True)
            cols = st.columns([1,1])
            with cols[0]:
                if st.button("Collapse all\nmenu tabs", use_container_width=True):
                    st.session_state["collapse_all_now"] = True
            with cols[1]:
                st.toggle("⭐ Use My\nPairs only", key="use_my_pairs_global", value=False)
            st.markdown('</div>', unsafe_allow_html=True)
    # Reset the flag immediately after read—no auto-behavior on next rerun
    flag = st.session_state.get("collapse_all_now", False)
    st.session_state["collapse_all_now"] = False
    return flag  # we only use it *this* render, not future ones


def expander(title: str, key: str):
    # Honor *current* collapse request only; otherwise leave Streamlit's default behavior
    expanded = not st.session_state.get("collapse_all_now_now_used", False)
    return st.sidebar.expander(title, expanded=expanded)


def big_timeframe_label(tf: str):
    st.markdown(f"<div style='font-size:1.4rem;font-weight:700;margin:8px 0 4px 2px;'>Timeframe: {tf}</div>", unsafe_allow_html=True)


# -------------------- Indicators
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    d = close.diff()
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    roll_up = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    roll_dn = pd.Series(dn, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / (roll_dn + 1e-12)
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

# -------------------- Exchanges
def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=20); r.raise_for_status()
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

        if exchange=="Binance":
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
    d = df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    out = d.resample(f"{target_sec}s", label="right", closed="right").agg(agg).dropna()
    return out.reset_index()

def df_for_tf(exchange: str, pair: str, tf: str) -> Optional[pd.DataFrame]:
    sec = ALL_TFS[tf]
    if exchange=="Coinbase":
        native = sec in {900,3600,21600,86400}
        if native: return fetch_candles(exchange, pair, sec)
        base = fetch_candles(exchange, pair, 3600)
        return resample_ohlcv(base, sec)
    if exchange=="Binance":
        return fetch_candles(exchange, pair, sec)
    return None

@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":
        amount = max(1, min(amount,72)); gran=86400//24; start=end-dt.timedelta(hours=amount)
    elif basis=="Daily":
        amount = max(1, min(amount,365)); gran=86400; start=end-dt.timedelta(days=amount)
    else:
        amount = max(1, min(amount,52)); gran=86400; start=end-dt.timedelta(weeks=amount)
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

# -------------------- Gates
def build_gate_masks(df_tf: pd.DataFrame, settings: dict) -> dict:
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

    rsi_ser  = rsi(df_tf["close"], rsi_len)
    mh_ser   = macd_hist(df_tf["close"], macd_fast, macd_slow, macd_sig)
    atr_ser  = atr(df_tf, atr_len) / (df_tf["close"] + 1e-12) * 100.0
    volx     = volume_spike(df_tf, vol_win)
    tr_up    = trend_breakout_up(df_tf, span=piv_span, within_bars=within_bars)

    def uni(val: bool): return pd.Series([bool(val)]*n, index=df_tf.index)
    m_vol_spike = uni((volx >= vol_mult)) if settings["use_vol_spike"] else uni(True)
    m_rsi       = uni((rsi_ser.iloc[-1] >= settings["min_rsi"])) if settings["use_rsi"] else uni(True)
    m_macd      = uni((mh_ser.iloc[-1] >= settings["min_mhist"])) if settings["use_macd"] else uni(True)
    m_atr       = uni((atr_ser.iloc[-1] >= settings["min_atr"])) if settings["use_atr"] else uni(True)
    m_trend     = uni(tr_up) if settings["use_trend"] else uni(True)

    # How many checks enabled & passed now?
    checks = [
        ("Δ", bool(m_pct_pos.iloc[-1])),
        ("V", bool(m_vol_spike.iloc[-1])),
        ("R", bool(m_rsi.iloc[-1])),
        ("M", bool(m_macd.iloc[-1])),
        ("A", bool(m_atr.iloc[-1])),
        ("T", bool(m_trend.iloc[-1])),
    ]
    enabled = [c for c,(lab,ok) in zip([settings["use_pct"],settings["use_vol_spike"],settings["use_rsi"],settings["use_macd"],settings["use_atr"],settings["use_trend"]], checks) if c]
    passed  = [ok for (lab,ok) in checks if True]  # we’ll count below

    return {
        "pct": m_pct_pos, "vol": m_vol_spike, "rsi": m_rsi, "macd": m_macd, "atr": m_atr, "trend": m_trend,
        "pct_value": pct,
        "checks_enabled": [lab for (lab,_ok) in checks if True and (
            (lab=="Δ" and settings["use_pct"]) or
            (lab=="V" and settings["use_vol_spike"]) or
            (lab=="R" and settings["use_rsi"]) or
            (lab=="M" and settings["use_macd"]) or
            (lab=="A" and settings["use_atr"]) or
            (lab=="T" and settings["use_trend"])
        )],
        "checks_passed": [lab for (lab,ok) in checks if ok],
    }

# -------------------- Alerts
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

# -------------------- Preset helpers
def _ensure_preset_dir():
    try:
        os.makedirs(PRESET_DIR, exist_ok=True)
        return True, ""
    except Exception as e:
        return False, str(e)

def save_presets_to_disk(presets: dict):
    ok, msg = _ensure_preset_dir()
    if not ok: return False, msg
    try:
        with open(PRESET_FILE, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2)
        return True, "Saved"
    except Exception as e:
        return False, f"{e}"

def load_presets_from_disk() -> dict:
    try:
        if os.path.exists(PRESET_FILE):
            with open(PRESET_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

# -------------------- App UI
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.title(APP_TITLE)

# Sticky tools
collapse_clicked = sticky_collapse_button()
# Consume this run's collapse request *only* for expanders right below
st.session_state["collapse_all_now_now_used"] = collapse_clicked

# --- Manage My Pairs (top of sidebar)
with st.sidebar.expander("Manage My Pairs", expanded=False):
    st.caption("Tip: pin/unpin from tables or paste here.")
    mypairs_text = st.text_area("My Pairs (comma-separated)", st.session_state.get("mypairs_text", "BTC-USD, ETH-USD, SOL-USD"))
    st.session_state["mypairs_text"] = mypairs_text
    my_pairs = [p.strip().upper() for p in mypairs_text.split(",") if p.strip()]
    if st.button("Clear My Pairs"):
        st.session_state["mypairs_text"] = ""
        my_pairs = []

# --- Market
with st.sidebar.expander("Market", expanded=False):
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    effective_exchange = exchange if "coming soon" not in exchange else "Coinbase"
    if "coming soon" in exchange: st.info("Coming soon — using Coinbase for now.")
    quote = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch_only = st.checkbox("Use watchlist only (ignore discovery)")
    watchlist = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")

    cols = st.columns([1,1])
    with cols[0]:
        all_pairs_toggle = st.toggle("All pairs (discovery)", value=True,
                                     help="If ON, use ALL discovered pairs; if OFF, limit by the slider.")
    with cols[1]:
        max_pairs = st.slider("Max pairs (if not All)", 10, 2000, 200, 10)

# --- Timeframes
with st.sidebar.expander("Timeframes", expanded=False):
    pick_tfs = st.multiselect("Available timeframes", TF_LIST, default=TF_LIST)
    sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=1)  # default 1h
    sort_desc = st.checkbox("Sort descending (largest first)", value=True)

# --- Gates (same behavior as last working version)
with st.sidebar.expander("Gates", expanded=False):
    # logic is implicit now (we use counts K and Y), but keep min +% change and toggles
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 100.0, 20.0, 0.5)
    st.caption("💡 If nothing shows, lower this threshold.")
    cols = st.columns(3)
    with cols[0]:
        use_vol_spike = st.toggle("Volume spike×", value=True)
        vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, 1.10, 0.05)
    with cols[1]:
        use_rsi = st.toggle("RSI", value=False)
        min_rsi = st.slider("Min RSI", 40, 90, 55, 1)
    with cols[2]:
        use_macd = st.toggle("MACD hist", value=True)
        min_mhist = st.slider("Min MACD hist", 0.0, 2.0, 0.0, 0.05)

    cols2 = st.columns(3)
    with cols2[0]:
        use_atr = st.toggle("ATR %", value=False, help="ATR/close × 100")
        min_atr = st.slider("Min ATR %", 0.0, 10.0, 0.5, 0.1)
    with cols2[1]:
        use_trend = st.toggle("Trend breakout (up)", value=True)
        pivot_span = st.slider("Pivot span (bars)", 2, 10, 4, 1)
        trend_within = st.slider("Breakout within (bars)", 5, 96, 48, 1)

    st.markdown("---")
    st.markdown("**Color rules (beginner‑friendly)**")
    k_choices = [1,2,3,4,5,6]  # 6 gates: Δ, V, R, M, A, T
    gates_to_green = st.selectbox("Gates needed to turn GREEN (K)", k_choices, index=2)
    y_max = gates_to_green-1
    yellow_needed = st.selectbox("YELLOW needs ≥ Y (but < K)", list(range(0, max(1,y_max)+1)), index=min(2,y_max))

# --- Indicator lengths
with st.sidebar.expander("Indicator lengths", expanded=False):
    rsi_len = st.slider("RSI length", 5, 50, 14, 1)
    macd_fast = st.slider("MACD fast EMA", 3, 50, 12, 1)
    macd_slow = st.slider("MACD slow EMA", 5, 100, 26, 1)
    macd_sig  = st.slider("MACD signal", 3, 50, 9, 1)
    atr_len   = st.slider("ATR length", 5, 50, 14, 1)
    vol_window= st.slider("Volume SMA window", 5, 50, 20, 1)

# --- History depth
with st.sidebar.expander("History depth (for ATH/ATL)", expanded=False):
    basis = st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=1)
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1)
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 90, 1)
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 12, 1)

# --- Notifications
with st.sidebar.expander("Notifications", expanded=False):
    email_to = st.text_input("Email recipient (optional)", "")
    webhook_url = st.text_input("Webhook URL (optional)", "")

# --- Auto-refresh
with st.sidebar.expander("Auto-refresh", expanded=False):
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 30, 1)
    st.caption("Auto-refresh is always on.")

# --- Presets (save/load)
with st.sidebar.expander("Gate presets", expanded=False):
    # Load from disk once
    if not st.session_state["loaded_default_presets"]:
        st.session_state["gate_presets"].update(load_presets_from_disk())
        # include a gentle default "hioncrypto" example if missing
        st.session_state["gate_presets"].setdefault("hioncrypto (starter)", {
            "min_pct": 20.0, "use_vol_spike": True, "vol_mult": 1.1,
            "use_rsi": False, "min_rsi": 55,
            "use_macd": True, "min_mhist": 0.0,
            "use_atr": False, "min_atr": 0.5,
            "use_trend": True, "pivot_span": 4, "trend_within": 48,
            "rsi_len": 14, "macd_fast":12, "macd_slow":26, "macd_sig":9,
            "atr_len":14, "vol_window":20,
            "gates_to_green":3, "yellow_needed":2
        })
        st.session_state["loaded_default_presets"] = True

    presets = st.session_state["gate_presets"]
    preset_names = sorted(presets.keys())
    if preset_names:
        sel = st.selectbox("Load preset", preset_names, index=0, key="preset_sel")
        if st.button("Apply preset"):
            p = presets[st.session_state["preset_sel"]]
            # apply to current controls
            min_pct = p["min_pct"]
            use_vol_spike = p["use_vol_spike"]; vol_mult = p["vol_mult"]
            use_rsi = p["use_rsi"]; min_rsi = p["min_rsi"]
            use_macd = p["use_macd"]; min_mhist = p["min_mhist"]
            use_atr = p["use_atr"]; min_atr = p["min_atr"]
            use_trend = p["use_trend"]; pivot_span = p["pivot_span"]; trend_within = p["trend_within"]
            rsi_len = p["rsi_len"]; macd_fast = p["macd_fast"]; macd_slow = p["macd_slow"]; macd_sig = p["macd_sig"]
            atr_len = p["atr_len"]; vol_window = p["vol_window"]
            gates_to_green = p["gates_to_green"]; yellow_needed = p["yellow_needed"]
            st.success(f"Applied preset: {st.session_state['preset_sel']}")

    st.markdown("—")
    newname = st.text_input("Save as", "")
    if st.button("Save current as preset") and newname.strip():
        presets[newname.strip()] = {
            "min_pct": min_pct,
            "use_vol_spike": use_vol_spike, "vol_mult": vol_mult,
            "use_rsi": use_rsi, "min_rsi": min_rsi,
            "use_macd": use_macd, "min_mhist": min_mhist,
            "use_atr": use_atr, "min_atr": min_atr,
            "use_trend": use_trend, "pivot_span": pivot_span, "trend_within": trend_within,
            "rsi_len": rsi_len, "macd_fast":macd_fast, "macd_slow":macd_slow, "macd_sig":macd_sig,
            "atr_len": atr_len, "vol_window": vol_window,
            "gates_to_green": gates_to_green, "yellow_needed": yellow_needed
        }
        ok, info = save_presets_to_disk(presets)
        if ok: st.success("Preset saved.")
        else:  st.warning(f"Could not save presets: {info}")

# -------------------- Apply “collapse once” semantics
st.session_state["collapse_all_now_now_used"] = False

# -------------------- Display & fonts
with st.sidebar.expander("Display", expanded=False):
    font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05)

st.markdown(f"""
<style>
  html, body {{ font-size: {font_scale}rem; }}
  .row-green {{ background: rgba(0,255,0,0.22) !important; font-weight: 600; }}
  .row-yellow {{ background: rgba(255,255,0,0.65) !important; font-weight: 600; }}
</style>
""", unsafe_allow_html=True)

# -------------------- Data Discovery
big_timeframe_label(sort_tf)

# universe
if st.session_state.get("use_my_pairs_global") and my_pairs:
    base_pairs = my_pairs[:]
else:
    if use_watch_only and watchlist.strip():
        base_pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
    else:
        base_pairs = list_products(effective_exchange, quote)

base_pairs = [p for p in base_pairs if p.endswith(f"-{quote}")]
if not all_pairs_toggle:
    base_pairs = base_pairs[:max_pairs]  # user-limited
pairs = base_pairs[:]  # final list to evaluate

# Optional WS start
def ws_worker(pids, endpoint="wss://ws-feed.exchange.coinbase.com"):
    ss = st.session_state
    try:
        ws = websocket.WebSocket()
        ws.connect(endpoint, timeout=10); ws.settimeout(1.0)
        ws.send(json.dumps({"type":"subscribe","channels":[{"name":"ticker","product_ids":pids}]}))
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

if pairs and WS_AVAILABLE and effective_exchange=="Coinbase":
    start_ws_if_needed(effective_exchange, pairs, chunk=10)

# -------------------- Build rows
settings_common = dict(
    use_pct=True,
    min_pct=min_pct,
    use_vol_spike=use_vol_spike, vol_window=vol_window, vol_mult=vol_mult,
    use_rsi=use_rsi, min_rsi=min_rsi, rsi_len=rsi_len,
    use_macd=use_macd, min_mhist=min_mhist, macd_fast=macd_fast, macd_slow=macd_slow, macd_sig=macd_sig,
    use_atr=use_atr, min_atr=min_atr, atr_len=atr_len,
    use_trend=use_trend, pivot_span=pivot_span, trend_within=trend_within,
)

rows=[]
badge_info=[]  # to style green/yellow

for pid in pairs:
    dft = df_for_tf(effective_exchange, pid, sort_tf)
    if dft is None or len(dft)<30:
        continue
    dft = dft.tail(400).copy()

    last_price = float(dft["close"].iloc[-1])
    if effective_exchange=="Coinbase" and st.session_state["ws_prices"].get(pid):
        last_price = float(st.session_state["ws_prices"][pid])
    first_price = float(dft["close"].iloc[0])
    pct = (last_price/first_price - 1.0) * 100.0

    hist = get_hist(effective_exchange, pid, basis, amount)
    if hist is None or len(hist)<10:
        aa={"From ATH %": np.nan, "ATH date":"—","From ATL %": np.nan, "ATL date":"—"}
    else:
        aa = ath_atl_info(hist)

    m = build_gate_masks(dft, settings_common)
    enabled_labels = [lab for lab in ["Δ","V","R","M","A","T"]
                      if ((lab=="Δ" and settings_common["use_pct"]) or
                          (lab=="V" and settings_common["use_vol_spike"]) or
                          (lab=="R" and settings_common["use_rsi"]) or
                          (lab=="M" and settings_common["use_macd"]) or
                          (lab=="A" and settings_common["use_atr"]) or
                          (lab=="T" and settings_common["use_trend"]))]

    passed_labels = [lab for lab in m["checks_passed"] if lab in ["Δ","V","R","M","A","T"]]
    passed_count = len([lab for lab in passed_labels if (
        (lab=="Δ" and settings_common["use_pct"]) or
        (lab=="V" and settings_common["use_vol_spike"]) or
        (lab=="R" and settings_common["use_rsi"]) or
        (lab=="M" and settings_common["use_macd"]) or
        (lab=="A" and settings_common["use_atr"]) or
        (lab=="T" and settings_common["use_trend"])
    )])
    enabled_count = len(enabled_labels)

    is_green = passed_count >= gates_to_green
    is_yellow = (yellow_needed <= passed_count < gates_to_green)

    rows.append({
        "Pair": pid,
        "Price": last_price,
        f"% Change ({sort_tf})": pct,
        "From ATH %": aa["From ATH %"], "ATH date": aa["ATH date"],
        "From ATL %": aa["From ATL %"], "ATL date": aa["ATL date"],
        "Gates": "".join([f"{'✅' if lab in passed_labels else '❌'}{lab} " for lab in enabled_labels]).strip(),
        "Strong Buy": "YES" if is_green else "—",
        "_green": is_green, "_yellow": is_yellow,
    })

# -------------------- Tables
df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair"])

if df.empty:
    st.info("No rows to show. Loosen gates or choose a different timeframe.")
else:
    chg_col = f"% Change ({sort_tf})"
    # Sort: % change desc (your default)
    df = df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index+1)

    # Top‑10: green rule + % change desc
    st.subheader("📌 Top‑10 (meets green rule)")
    top10 = df[df["_green"]].sort_values(chg_col, ascending=False, na_position="last").head(10).reset_index(drop=True)

    def style_green(x):
        styles = pd.DataFrame("background-color: rgba(0,255,0,0.22); font-weight: 600;", index=x.index, columns=x.columns)
        return styles

    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, loosen gates (lower Min +% change or disable some toggles).")
    else:
        show_cols = ["#","Pair","Price",chg_col,"From ATH %","ATH date","From ATL %","ATL date","Gates","Strong Buy"]
        st.dataframe(top10[show_cols].style.apply(style_green, axis=None), use_container_width=True)

    # All pairs with green/yellow styling
    st.subheader("📑 All pairs")
    def style_full(x):
        styles = pd.DataFrame("", index=x.index, columns=x.columns)
        gm = df["_green"].reindex(x.index, fill_value=False)
        ym = df["_yellow"].reindex(x.index, fill_value=False)
        styles.loc[gm, :] = "background-color: rgba(0,255,0,0.22); font-weight: 600;"
        styles.loc[ym, :] = "background-color: rgba(255,255,0,0.65); font-weight: 600;"
        return styles

    show_cols = ["#","Pair","Price",chg_col,"From ATH %","ATH date","From ATL %","ATL date","Gates","Strong Buy"]
    st.dataframe(df[show_cols].style.apply(style_full, axis=None), use_container_width=True)

    # Alerts when a pair enters Top‑10 green
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

    st.caption(f"Pairs evaluated: {len(df)} • Exchange: {effective_exchange} • Quote: {quote} • Sort TF: {sort_tf}")

# -------------------- Auto-refresh
remaining = refresh_sec - (time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {refresh_sec}s (next in {int(remaining)}s)")

