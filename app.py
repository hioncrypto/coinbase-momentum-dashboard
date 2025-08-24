# app.py — Crypto Tracker by hioncrypto
# Fixes:
# - Collapse-all works (sets flag then reruns; expanders start closed).
# - Presets applied safely via __pending_preset (no StreamlitAPIException).
# - "Use hioncrypto (starter)" toggle is at TOP of Presets. Applies immediately via pending handoff.
# - Looser defaults so rows appear: Min %+ = 4, K=2, Y=1, Max Pairs=800; Δ/Vol×/Trend/MACD enabled.
# - Always shows an unfiltered Discovery table if gates hide everything.
# - Blue buttons in sidebar.

import os, json, time, ssl, smtplib, threading, queue, datetime as dt
from pathlib import Path
from typing import List, Optional, Tuple
import numpy as np, pandas as pd, requests, streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

WS_AVAILABLE = True
try:
    import websocket
except Exception:
    WS_AVAILABLE = False

# ---------- constants ----------
TITLE = "Crypto Tracker by hioncrypto"
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
TF_TO_SEC = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}
QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"
PRESET_PATH = Path("/tmp/crypto_tracker_presets.json")

# ---------- init state ----------
def _init_state():
    ss = st.session_state
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("last_refresh", time.time())
    ss.setdefault("collapse_all_now", False)     # for collapse button
    ss.setdefault("__pending_preset", None)      # safe handoff for presets
    ss.setdefault("my_pairs", set())
    ss.setdefault("gate_presets", {})
    ss.setdefault("refresh_sec", 30)
_init_state()

# ---------- apply pending preset BEFORE widgets render ----------
def _apply_preset_dict(P: dict):
    """Write all gate settings into session_state."""
    s = st.session_state
    s["gate_min_pct"]   = float(P.get("min_pct", 4.0))
    s["gate_use_vol"]   = bool(P.get("use_vol_spike", True))
    s["gate_vol_mult"]  = float(P.get("vol_mult", 1.05))
    s["gate_use_rsi"]   = bool(P.get("use_rsi", False))
    s["gate_min_rsi"]   = int(P.get("min_rsi", 55))
    s["rsi_len"]        = int(P.get("rsi_len", 14))
    s["gate_use_macd"]  = bool(P.get("use_macd", True))
    s["gate_min_mhist"] = float(P.get("min_mhist", 0.0))
    s["gate_use_atr"]   = bool(P.get("use_atr", False))
    s["gate_min_atr"]   = float(P.get("min_atr", 0.3))
    s["atr_len"]        = int(P.get("atr_len", 14))
    s["gate_use_trend"] = bool(P.get("use_trend", True))
    s["gate_pivot_span"]= int(P.get("pivot_span", 4))
    s["gate_trend_within"]=int(P.get("trend_within", 72))
    s["gate_use_roc"]   = bool(P.get("use_roc", False))
    s["gate_roc_len"]   = int(P.get("roc_len", 10))
    s["gate_min_roc"]   = float(P.get("min_roc", 0.5))
    s["gate_K"]         = int(P.get("K", 2))
    s["gate_Y"]         = int(P.get("Y", 1))

if st.session_state["__pending_preset"] is not None:
    _apply_preset_dict(st.session_state["__pending_preset"])
    st.session_state["__pending_preset"] = None

# ---------- indicators ----------
def ema(s, span): return s.ewm(span=span, adjust=False).mean()
def rsi(close, length=14):
    d=close.diff()
    up=pd.Series(np.where(d>0, d, 0.0), index=close.index).ewm(alpha=1/length, adjust=False).mean()
    dn=pd.Series(np.where(d<0,-d, 0.0), index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs=up/(dn+1e-12)
    return 100-(100/(1+rs))
def macd_hist(close, fast=12, slow=26, signal=9):
    line=ema(close, fast)-ema(close, slow)
    return line-ema(line, signal)
def atr(df, length=14):
    h,l,c=df["high"],df["low"],df["close"]; pc=c.shift(1)
    tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()
def roc(close, n=10): return (close/close.shift(n)-1.0)*100.0
def volume_spike(df, window=20):
    if len(df)<window+1: return np.nan
    return float(df["volume"].iloc[-1]/(df["volume"].rolling(window).mean().iloc[-1]+1e-12))
def find_pivots(close, span=3):
    v=close.values; n=len(v); hi=[]; lo=[]
    for i in range(span, n-span):
        if v[i]>v[i-span:i].max() and v[i]>v[i+1:i+1+span].max(): hi.append(i)
        if v[i]<v[i-span:i].min() and v[i]<v[i+1:i+1+span].min(): lo.append(i)
    return pd.Index(hi), pd.Index(lo)
def trend_breakout_up(df, span=3, within_bars=72):
    if df is None or len(df)<span*2+5: return False
    highs,_=find_pivots(df["close"], span)
    if len(highs)==0: return False
    hi=int(highs[-1]); level=float(df["close"].iloc[hi])
    cross=None
    for j in range(hi+1,len(df)):
        if float(df["close"].iloc[j])>level: cross=j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# ---------- exchange helpers ----------
def coinbase_list_products(quote):
    try:
        r=requests.get(f"{CB_BASE}/products", timeout=25); r.raise_for_status()
        return sorted(f"{p['base_currency']}-{p['quote_currency']}" for p in r.json() if p.get("quote_currency")==quote)
    except Exception: return []
def binance_list_products(quote):
    try:
        r=requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=30); r.raise_for_status()
        out=[]
        for s in r.json().get("symbols", []):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote: out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception: return []
def list_products(exchange, quote):
    if exchange=="Coinbase": return coinbase_list_products(quote)
    if exchange=="Binance":  return binance_list_products(quote)
    return coinbase_list_products(quote)  # fallback

def fetch_candles(exchange, pair_dash, gran_sec, start=None, end=None):
    try:
        if exchange=="Coinbase":
            params={"granularity":gran_sec}
            if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
            if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
            r=requests.get(f"{CB_BASE}/products/{pair_dash}/candles", params=params, timeout=25)
            if r.status_code!=200: return None
            arr=r.json()
            if not arr: return None
            df=pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"]=pd.to_datetime(df["ts"], unit="s", utc=True)
            return df.sort_values("ts").reset_index(drop=True)
        elif exchange=="Binance":
            base,quote=pair_dash.split("-"); symbol=f"{base}{quote}"
            imap={900:"15m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
            interval=imap.get(gran_sec); 
            if not interval: return None
            params={"symbol":symbol,"interval":interval,"limit":1000}
            if start: params["startTime"]=int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            if end:   params["endTime"]=int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            r=requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=25)
            if r.status_code!=200: return None
            rows=[{"ts":pd.to_datetime(a[0],unit="ms",utc=True),"open":float(a[1]),"high":float(a[2]),
                   "low":float(a[3]),"close":float(a[4]),"volume":float(a[5])} for a in r.json()]
            return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    except Exception:
        return None
    return None

def resample_ohlcv(df, sec):
    if df is None or df.empty: return None
    d=df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    out=d.resample(f"{sec}s", label="right", closed="right").agg(agg).dropna()
    return out.reset_index()

def df_for_tf(exchange, pair, tf):
    sec=TF_TO_SEC[tf]
    if exchange=="Coinbase":
        native=sec in {900,3600,21600,86400}
        base=fetch_candles(exchange, pair, sec if native else 3600)
        return base if native else resample_ohlcv(base, sec)
    elif exchange=="Binance":
        return fetch_candles(exchange, pair, sec)
    return None

@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange, pair, basis, amount):
    end=dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":
        amount=max(1,min(amount,72)); gran=3600; start=end-dt.timedelta(hours=amount)
    elif basis=="Daily":
        amount=max(1,min(amount,365)); gran=86400; start=end-dt.timedelta(days=amount)
    else:
        amount=max(1,min(amount,52)); gran=86400; start=end-dt.timedelta(weeks=amount)
    out=[]; step=300; cursor=end
    while True:
        win=dt.timedelta(seconds=step*gran)
        s=max(start, cursor-win)
        if (cursor-s).total_seconds()<gran: break
        df=fetch_candles(exchange, pair, gran, start=s, end=cursor)
        if df is None or df.empty: break
        out.append(df); cursor=df["ts"].iloc[0]
        if cursor<=start: break
    if not out: return None
    hist=pd.concat(out, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if basis=="Weekly": hist=resample_ohlcv(hist, 7*86400)
    return hist

def ath_atl_info(hist):
    last=float(hist["close"].iloc[-1])
    ia=int(hist["high"].idxmax()); ib=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[ia]); d_ath=pd.to_datetime(hist["ts"].iloc[ia]).date().isoformat()
    atl=float(hist["low"].iloc[ib]);  d_atl=pd.to_datetime(hist["ts"].iloc[ib]).date().isoformat()
    return {"From ATH %":(last/ath-1)*100 if ath>0 else np.nan,"ATH date":d_ath,
            "From ATL %":(last/atl-1)*100 if atl>0 else np.nan,"ATL date":d_atl}

# ---------- alerts/presets IO ----------
def send_email_alert(subject, body, recipient):
    try: cfg=st.secrets["smtp"]
    except Exception: return False, "SMTP not configured"
    try:
        msg=MIMEMultipart(); msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body,"plain"))
        ctx=ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port",465), context=ctx) as s:
            s.login(cfg["user"], cfg["password"]); s.sendmail(cfg["sender"], recipient, msg.as_string())
        return True,"Email sent"
    except Exception as e: return False, str(e)

def load_presets_from_disk():
    try:
        if PRESET_PATH.exists(): return json.loads(PRESET_PATH.read_text())
    except Exception: pass
    return {}
def save_presets_to_disk(p):
    try: PRESET_PATH.write_text(json.dumps(p, indent=2))
    except Exception: pass

# ---------- page & CSS ----------
st.set_page_config(page_title=TITLE, layout="wide")
st.markdown("""
<style>
/* BLUE buttons in sidebar */
section[data-testid="stSidebar"] .stButton > button,
section[data-testid="stSidebar"] button,
section[data-testid="stSidebar"] div [role="button"] {
  background-color: #1e88e5 !important; color: #fff !important; border: 0 !important; border-radius: 6px !important;
}
/* prettier expander header */
section[data-testid="stSidebar"] [data-testid="stExpander"] summary { background:#1e88e522; border-radius:8px; }
/* chips mono */
.chips { font-family: ui-monospace, Menlo, Consolas, monospace; }
</style>
""", unsafe_allow_html=True)
st.title(TITLE)

# ---------- Sidebar: collapse + My Pairs ----------
with st.sidebar:
    if st.button("Collapse all", use_container_width=True):
        st.session_state["collapse_all_now"] = True
        st.rerun()   # important: rerun before expanders are drawn

    use_my_pairs = st.toggle("⭐ Use My Pairs only", value=False)
    with st.expander("Manage My Pairs", expanded=False):
        cur = ", ".join(sorted(st.session_state["my_pairs"])) if st.session_state["my_pairs"] else ""
        txt = st.text_area("Pinned pairs (comma-separated)", cur, height=80)
        if st.button("Save My Pairs"):
            st.session_state["my_pairs"] = set(p.strip().upper() for p in txt.split(",") if p.strip())
            st.success("Saved")

def expander(title, key):
    open_state = not st.session_state.get("collapse_all_now", False)
    return st.sidebar.expander(title, expanded=open_state)

# ---------- Market / Mode / TF ----------
with expander("Market", "exp_market"):
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    effective_exchange = exchange if "coming soon" not in exchange else "Coinbase"
    if "coming soon" in exchange: st.info("Coming soon. Using Coinbase for now.")
    quote = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch_only = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    watchlist = st.text_area("Watchlist (comma-separated)",
                             "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")
    max_pairs = st.slider("Max pairs to evaluate (discovery)", 10, 3000, 800, 10)

with expander("Mode", "exp_mode"):
    mode = st.radio("Data source", ["REST only","WebSocket + REST (hybrid)"], index=0, horizontal=True)
    ws_chunk = st.slider("WS subscribe chunk (Coinbase)", 2, 20, 5, 1)

with expander("Timeframes", "exp_tf"):
    sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=1)
    sort_desc = st.checkbox("Sort descending (largest first)", True)

# ---------- Gates (incl. hioncrypto toggle at TOP + safe apply) ----------
with expander("Gates", "exp_gates"):
    st.caption("Turn **green** when at least K gates are met (Δ always counted). **Yellow** shows near-miss (≥ Y but < K).")

    HION = {
        "min_pct": 4.0,
        "use_vol_spike": True, "vol_mult": 1.05,
        "use_rsi": False, "min_rsi": 55, "rsi_len": 14,
        "use_macd": True, "min_mhist": 0.0,
        "use_atr": False, "min_atr": 0.3, "atr_len": 14,
        "use_trend": True, "pivot_span": 4, "trend_within": 72,
        "use_roc": False, "roc_len": 10, "min_roc": 0.5,
        "K": 2, "Y": 1
    }
    if st.toggle("Use hioncrypto (starter)", value=False, help="Apply loose starter settings now"):
        st.session_state["__pending_preset"] = HION
        st.rerun()

    # manual controls (bound to state so presets can fill them)
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 80.0, st.session_state.get("gate_min_pct", 4.0), 0.5, key="gate_min_pct")
    c1,c2,c3 = st.columns(3)
    with c1:
        use_vol_spike = st.toggle("Volume spike×", st.session_state.get("gate_use_vol", True), key="gate_use_vol")
        vol_mult = st.slider("Spike multiple ×", 1.0, 6.0, st.session_state.get("gate_vol_mult", 1.05), 0.05, key="gate_vol_mult")
        use_rsi = st.toggle("RSI", st.session_state.get("gate_use_rsi", False), key="gate_use_rsi")
        min_rsi = st.slider("Min RSI", 40, 90, st.session_state.get("gate_min_rsi", 55), 1, key="gate_min_rsi")
    with c2:
        use_macd = st.toggle("MACD hist", st.session_state.get("gate_use_macd", True), key="gate_use_macd")
        min_mhist = st.slider("Min MACD hist", 0.0, 2.0, st.session_state.get("gate_min_mhist", 0.0), 0.05, key="gate_min_mhist")
        use_atr = st.toggle("ATR %", st.session_state.get("gate_use_atr", False), key="gate_use_atr")
        min_atr = st.slider("Min ATR %", 0.0, 10.0, st.session_state.get("gate_min_atr", 0.3), 0.1, key="gate_min_atr")
    with c3:
        use_trend = st.toggle("Trend breakout (up)", st.session_state.get("gate_use_trend", True), key="gate_use_trend")
        pivot_span = st.slider("Pivot span (bars)", 2, 10, st.session_state.get("gate_pivot_span", 4), 1, key="gate_pivot_span")
        trend_within = st.slider("Breakout within (bars)", 5, 96, st.session_state.get("gate_trend_within", 72), 1, key="gate_trend_within")
        use_roc = st.toggle("ROC %", st.session_state.get("gate_use_roc", False), key="gate_use_roc")
        roc_len = st.slider("ROC length (bars)", 2, 60, st.session_state.get("gate_roc_len", 10), 1, key="gate_roc_len")
        min_roc = st.slider("Min ROC %", 0.0, 50.0, st.session_state.get("gate_min_roc", 0.5), 0.5, key="gate_min_roc")

    st.divider()
    K = st.selectbox("Gates needed to turn **green** (K)", list(range(1,8)), index=1, key="gate_K")
    Y = st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0,7)), index=1, key="gate_Y")
    enabled_checks = 1 + sum([use_vol_spike, use_roc, use_trend, use_rsi, use_macd, use_atr])
    K_eff = max(1, min(K, enabled_checks)); Y_eff = max(0, min(Y, K_eff-1))
    st.caption(f"Enabled now: {enabled_checks} • Green uses K={K_eff} • Yellow uses Y={Y_eff}")
    st.caption("Tips: lower Min %+ / reduce K / toggle off gates if nothing shows.")

    # curated + user presets (safe apply via pending)
    st.markdown("---")
    st.markdown("#### Presets (Aggressive / Balanced / Conservative)")
    curated = {
        "Aggressive": {"min_pct":4.0,"use_vol_spike":True,"vol_mult":1.03,"use_rsi":False,"min_rsi":50,"rsi_len":14,
                       "use_macd":True,"min_mhist":0.0,"use_atr":False,"min_atr":0.0,"atr_len":14,"use_trend":True,
                       "pivot_span":3,"trend_within":96,"use_roc":True,"roc_len":8,"min_roc":0.3,"K":2,"Y":1},
        "Balanced":   {"min_pct":8.0,"use_vol_spike":True,"vol_mult":1.07,"use_rsi":True,"min_rsi":55,"rsi_len":14,
                       "use_macd":True,"min_mhist":0.0,"use_atr":False,"min_atr":0.2,"atr_len":14,"use_trend":True,
                       "pivot_span":4,"trend_within":72,"use_roc":True,"roc_len":10,"min_roc":0.8,"K":3,"Y":1},
        "Conservative":{"min_pct":12.0,"use_vol_spike":True,"vol_mult":1.12,"use_rsi":True,"min_rsi":60,"rsi_len":14,
                       "use_macd":True,"min_mhist":0.2,"use_atr":True,"min_atr":0.6,"atr_len":14,"use_trend":True,
                       "pivot_span":5,"trend_within":48,"use_roc":True,"roc_len":12,"min_roc":1.2,"K":4,"Y":2},
    }
    if not st.session_state["gate_presets"]:
        st.session_state["gate_presets"] = {**load_presets_from_disk()}
    changed=False
    for k,v in curated.items():
        if k not in st.session_state["gate_presets"]:
            st.session_state["gate_presets"][k]=v; changed=True
    if changed: save_presets_to_disk(st.session_state["gate_presets"])

    choices = ["(choose)"] + sorted(st.session_state["gate_presets"].keys())
    sel = st.selectbox("Apply preset", choices, index=0, key="active_preset_choice")
    if st.button("Apply selected"):
        if sel != "(choose)" and sel in st.session_state["gate_presets"]:
            st.session_state["__pending_preset"] = st.session_state["gate_presets"][sel]
            st.rerun()
        else:
            st.warning("Pick a preset first.")

    cA, cB = st.columns([2,1])
    with cA:
        name = st.text_input("Save current as…", "", key="preset_save_name")
        if st.button("Save preset"):
            nm=name.strip()
            if nm:
                s=st.session_state
                st.session_state["gate_presets"][nm]={
                    "min_pct": s["gate_min_pct"],
                    "use_vol_spike": s["gate_use_vol"], "vol_mult": s["gate_vol_mult"],
                    "use_rsi": s["gate_use_rsi"], "min_rsi": s["gate_min_rsi"], "rsi_len": s.get("rsi_len",14),
                    "use_macd": s["gate_use_macd"], "min_mhist": s["gate_min_mhist"],
                    "use_atr": s["gate_use_atr"], "min_atr": s["gate_min_atr"], "atr_len": s.get("atr_len",14),
                    "use_trend": s["gate_use_trend"], "pivot_span": s["gate_pivot_span"], "trend_within": s["gate_trend_within"],
                    "use_roc": s["gate_use_roc"], "roc_len": s["gate_roc_len"], "min_roc": s["gate_min_roc"],
                    "K": s["gate_K"], "Y": s["gate_Y"]
                }
                save_presets_to_disk(st.session_state["gate_presets"])
                st.success(f"Saved preset: {nm}")
            else:
                st.warning("Enter a name to save.")
    with cB:
        del_choice = st.selectbox("Delete preset", ["(choose)"]+[k for k in choices if k!="(choose)"])
        if st.button("Delete selected"):
            if del_choice!="(choose)" and del_choice in st.session_state["gate_presets"]:
                del st.session_state["gate_presets"][del_choice]
                save_presets_to_disk(st.session_state["gate_presets"])
                st.success(f"Deleted: {del_choice}")
            else:
                st.warning("Pick a preset to delete.")

# Collapse flag is one-shot
st.session_state["collapse_all_now"] = False

# ---------- Indicator lengths & History ----------
with expander("Indicator lengths", "exp_lens"):
    st.slider("RSI length", 5, 50, st.session_state.get("rsi_len",14), 1, key="rsi_len")
    st.slider("MACD fast EMA", 3, 50, st.session_state.get("macd_fast",12), 1, key="macd_fast")
    st.slider("MACD slow EMA", 5, 100, st.session_state.get("macd_slow",26), 1, key="macd_slow")
    st.slider("MACD signal", 3, 50, st.session_state.get("macd_sig",9), 1, key="macd_sig")
    st.slider("ATR length", 5, 50, st.session_state.get("atr_len",14), 1, key="atr_len")
    st.slider("Volume SMA window", 5, 50, st.session_state.get("vol_window",20), 1, key="vol_window")

with expander("History depth (for ATH/ATL)", "exp_hist"):
    basis = st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=1)
    amount = (st.slider("Hours (≤72)", 1, 72, 24, 1) if basis=="Hourly"
              else st.slider("Days (≤365)", 1, 365, 90, 1) if basis=="Daily"
              else st.slider("Weeks (≤52)", 1, 52, 12, 1))

# ---------- discovery set ----------
def parse_watchlist(s): return [p.strip().upper() for p in s.split(",") if p.strip()]
watch_pairs = parse_watchlist(watchlist)
if use_my_pairs and st.session_state["my_pairs"]:
    watch_pairs = list(sorted(set(watch_pairs).union(st.session_state["my_pairs"])))
if use_watch_only:
    pairs = [p for p in watch_pairs if p.endswith(f"-{quote}")]
    disc_count = 0
else:
    discovered = list_products(effective_exchange, quote)
    if not discovered and effective_exchange!="Coinbase":
        discovered = list_products("Coinbase", quote); effective_exchange="Coinbase"
    disc_count = len(discovered)
    pairs = sorted(set(discovered).union(watch_pairs))
    pairs = [p for p in pairs if p.endswith(f"-{quote}")][:max_pairs]

st.caption(f"Discovery: found {disc_count} exchange pairs • merged set {len(pairs)}")

if not pairs:
    st.info("No pairs to scan. Try turning OFF 'Use watchlist only', change Quote to USD, and increase Max pairs.")
    st.stop()

# ---------- optional WS ----------
if (mode.startswith("WebSocket") and effective_exchange=="Coinbase" and WS_AVAILABLE):
    pick=pairs[:min(10,len(pairs))]
    if not st.session_state["ws_alive"]:
        def ws_worker(product_ids, endpoint="wss://ws-feed.exchange.coinbase.com"):
            try:
                ws=websocket.WebSocket(); ws.connect(endpoint, timeout=10); ws.settimeout(1.0)
                ws.send(json.dumps({"type":"subscribe","channels":[{"name":"ticker","product_ids":product_ids}]}))
                st.session_state["ws_alive"]=True
                while st.session_state["ws_alive"]:
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
            except Exception: pass
            finally:
                st.session_state["ws_alive"]=False
                try: ws.close()
                except Exception: pass
        threading.Thread(target=ws_worker, args=(pick,), daemon=True).start()

# ---------- build table ----------
def build_row(pid):
    dft=df_for_tf(effective_exchange, pid, sort_tf)
    if dft is None or len(dft)<30: return None
    dft=dft.tail(400).copy()
    last=float(dft["close"].iloc[-1])
    if effective_exchange=="Coinbase" and st.session_state["ws_prices"].get(pid):
        last=float(st.session_state["ws_prices"][pid])
    first=float(dft["close"].iloc[0])
    pct=(last/first-1.0)*100.0

    hist=get_hist(effective_exchange, pid, basis, amount)
    if hist is None or len(hist)<10:
        athp,athd,atlp,atld=np.nan,"—",np.nan,"—"
    else:
        aa=ath_atl_info(hist); athp,athd,atlp,atld=aa["From ATH %"], aa["ATH date"], aa["From ATL %"], aa["ATL date"]

    rsi_ser=rsi(dft["close"], st.session_state.get("rsi_len",14))
    mh_ser=macd_hist(dft["close"], st.session_state.get("macd_fast",12), st.session_state.get("macd_slow",26), st.session_state.get("macd_sig",9))
    atr_pct=atr(dft, st.session_state.get("atr_len",14))/(dft["close"]+1e-12)*100.0
    volx=volume_spike(dft, st.session_state.get("vol_window",20))
    tr_up=trend_breakout_up(dft, st.session_state.get("gate_pivot_span",4), st.session_state.get("gate_trend_within",72))
    roc_ser=roc(dft["close"], st.session_state.get("gate_roc_len",10))

    ok_delta=(pct>0) and (pct>=st.session_state.get("gate_min_pct",4.0))
    ok_vol=(volx>=st.session_state.get("gate_vol_mult",1.05))
    ok_roc=(roc_ser.iloc[-1]>=st.session_state.get("gate_min_roc",0.5))
    ok_trend=bool(tr_up)
    ok_rsi=(rsi_ser.iloc[-1]>=st.session_state.get("gate_min_rsi",55))
    ok_macd=(mh_ser.iloc[-1]>=st.session_state.get("gate_min_mhist",0.0))
    ok_atr=(atr_pct.iloc[-1]>=st.session_state.get("gate_min_atr",0.3))

    enabled=[True, st.session_state.get("gate_use_vol",True), st.session_state.get("gate_use_roc",False),
             st.session_state.get("gate_use_trend",True), st.session_state.get("gate_use_rsi",False),
             st.session_state.get("gate_use_macd",True), st.session_state.get("gate_use_atr",False)]
    values=[ok_delta, ok_vol, ok_roc, ok_trend, ok_rsi, ok_macd, ok_atr]
    counted=[v for v,e in zip(values, enabled) if e]
    K_eff=max(1, min(st.session_state.get("gate_K",2), len(counted))) if counted else 1
    Y_eff=max(0, min(st.session_state.get("gate_Y",1), max(0, K_eff-1)))
    met=int(sum(bool(x) for x in counted))
    green=met>=K_eff
    yellow=(not green) and (met>=Y_eff) and (pct>0)

    def chip(val,en): return "✅" if en and bool(val) else ("❌" if en else "·")
    chips=(f"Δ{chip(ok_delta,True)} V{chip(ok_vol,enabled[1])} R{chip(ok_roc,enabled[2])} "
           f"T{chip(ok_trend,enabled[3])} S{chip(ok_rsi,enabled[4])} M{chip(ok_macd,enabled[5])} A{chip(ok_atr,enabled[6])}")

    return {"Pair":pid,"Price":last,f"% Change ({sort_tf})":pct,"From ATH %":athp,"ATH date":athd,
            "From ATL %":atlp,"ATL date":atld,"Gates":chips,"Strong Buy":"YES" if green else "—",
            "_green":green,"_yellow":yellow}

rows=[r for p in pairs if (r:=build_row(p))]

df=pd.DataFrame(rows)
chg_col=f"% Change ({sort_tf})"

# fallback discovery if filtered out
if df.empty:
    mini=[]
    for pid in pairs[:400]:
        dft=df_for_tf(effective_exchange, pid, sort_tf)
        if dft is None or len(dft)<2: continue
        dft=dft.tail(200)
        last=float(dft["close"].iloc[-1]); first=float(dft["close"].iloc[0])
        mini.append({"Pair":pid,"Price":last,f"% Change ({sort_tf})":(last/first-1.0)*100.0})
    if mini:
        st.warning("No rows passed gates. Discovery (unfiltered) shown below—loosen gates or lower K.")
        mdf=pd.DataFrame(mini).sort_values(chg_col, ascending=False)
        mdf.insert(0,"#",range(1,len(mdf)+1))
        st.dataframe(mdf, use_container_width=True)
    else:
        st.error("No candle data for the selected TF/quote. Try 1h and Quote=USD.")
    st.stop()

df=df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
df.insert(0,"#",df.index+1)

def style_rows_full(x):
    styles=pd.DataFrame("", index=x.index, columns=x.columns)
    if "_green" in x.columns: styles.loc[x["_green"].fillna(False),:]="background-color: rgba(0,255,0,0.22); font-weight:600;"
    if "_yellow" in x.columns:
        idx=x["_yellow"].fillna(False) & ~x["_green"].fillna(False)
        styles.loc[idx,:]="background-color: rgba(255,255,0,0.60); font-weight:600;"
    if "Gates" in x.columns: styles["Gates"]=styles["Gates"]+"; font-family: ui-monospace, Menlo, Consolas, monospace;"
    return styles
def style_rows_green_only(x):
    return pd.DataFrame("background-color: rgba(0,255,0,0.22); font-weight:600;", index=x.index, columns=x.columns)

st.markdown(f"**Timeframe:** {sort_tf}  \n*Legend: Δ %Change • V Volume× • R ROC • T Trend • S RSI • M MACD • A ATR*")

st.subheader("📌 Top‑10 (meets green rule)")
top10=df[df["_green"]].copy()
if not top10.empty:
    top10=top10.sort_values(chg_col, ascending=False).head(10).reset_index(drop=True)
    show_cols=[c for c in top10.columns if c not in ["_green","_yellow"]]
    st.dataframe(top10[show_cols].style.apply(style_rows_green_only, axis=None), use_container_width=True)
else:
    st.write("—")
    st.caption("Loosen settings if empty.")

st.subheader("📑 All pairs")
show_cols=[c for c in df.columns if c not in ["_green","_yellow"]]
st.dataframe(df[show_cols].style.apply(style_rows_full, axis=None), use_container_width=True)

# footer + auto-refresh
mode_label='WS+REST' if (mode.startswith('WebSocket') and effective_exchange=='Coinbase' and WS_AVAILABLE) else 'REST only'
st.caption(f"Pairs: {len(df)} • Exchange: {effective_exchange} • Quote: {quote} • Sort TF: {sort_tf} • Mode: {mode_label}")
remaining = st.session_state["refresh_sec"] - (time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"]=time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh ~{st.session_state['refresh_sec']}s (next in {int(remaining)}s)")

