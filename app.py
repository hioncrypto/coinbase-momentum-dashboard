# app.py — Crypto Tracker by hioncrypto
# - Micro+Macro trend windows (Hourly/Daily/Weekly) under "Trend Break (ATH/ATL window)"
# - No cap on discovered pairs (not sliced) — caution: can be heavy on huge exchanges
# - MACD histogram default threshold = 0.025
# - Stronger blue for sidebar controls
# - Instant-apply for all settings + safe preset handoff
# - Discovery fallback always shows something if gates hide all

import os, json, time, ssl, smtplib, threading, datetime as dt
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

TITLE = "Crypto Tracker by hioncrypto"
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
TF_TO_SEC = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}
QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"
PRESET_PATH = Path("/tmp/crypto_tracker_presets.json")

def _init_state():
    ss = st.session_state
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("last_refresh", time.time())
    ss.setdefault("collapse_all_now", False)
    ss.setdefault("__pending_preset", None)
    ss.setdefault("my_pairs", set())
    ss.setdefault("gate_presets", {})
    ss.setdefault("refresh_sec", 30)
_init_state()

# ----- Beginner hints for UI
HINT = {
    "mode": "Pick data source. Hybrid WS+REST shows fresher prices on Coinbase; REST works everywhere.",
    "exchange": "Choose the venue. ‘Coming soon’ entries fall back to Coinbase for now.",
    "quote": "Only pairs that end with this quote (e.g., *-USD, *-USDT) are considered.",
    "watchlist_only": "If ON, ignore discovery and scan ONLY the comma‑separated list below.",
    "watchlist": "Comma‑separated pairs like BTC-USD, ETH-USD. Use with ‘Use watchlist only’.",
    "tfs": "Timeframes to compute % change from the first to last candle in each window.",
    "sort_tf": "This timeframe’s % change is used for sorting and the % Change column.",
    "sort_desc": "If ON, biggest gainers first.",
    "logic": "ALL = every active gate must pass. ANY = at least one active gate passes.",
    "min_pct": "Positive change only. Lower this if nothing shows.",
    "vol_spike": "Compares last bar volume to its SMA window. Higher × is stricter.",
    "rsi": "Relative Strength Index threshold (optional gate).",
    "macd": "MACD histogram threshold (optional gate).",
    "atr": "ATR as % of price (volatility) threshold (optional gate).",
    "trend": "Looks for a close above last pivot high (up‑break) within a recent bar window.",
    "pivot_span": "How many bars on each side to confirm a pivot high/low.",
    "trend_within": "A breakout must have happened within this many bars to count.",
    "len_rsi": "RSI length (bars).",
    "len_macd": "MACD EMAs and signal lengths.",
    "len_atr": "ATR length (bars).",
    "len_vol": "Volume SMA window length (bars).",
    "trend_basis": "How far back we search to compute local ATH/ATL and anchor trend‑break pivots (macro Weekly, micro Hourly).",
    "trend_amount": "Size of the window for the selected basis.",
    "font": "Zoom the entire UI text size.",
    "email": "Send email alerts when a pair enters Top‑10. Configure SMTP in secrets.",
    "webhook": "Send webhook (Slack/Discord/Telegram/etc.) when a pair enters Top‑10.",
    "refresh": "Automatically refresh data every N seconds.",
    "k_green": "How many active gates must pass to turn a row green (Strong Buy).",
    "k_yellow": "How many (but fewer than K) must pass to turn a row yellow.",
}

def _apply_preset_dict(P: dict):
    s = st.session_state
    s["gate_min_pct"]   = float(P.get("min_pct", 5.0))
    s["gate_use_vol"]   = bool(P.get("use_vol_spike", True))
    s["gate_vol_mult"]  = float(P.get("vol_mult", 1.05))
    s["gate_use_rsi"]   = bool(P.get("use_rsi", False))
    s["gate_min_rsi"]   = int(P.get("min_rsi", 55))
    s["rsi_len"]        = int(P.get("rsi_len", 14))
    s["gate_use_macd"]  = bool(P.get("use_macd", True))
    s["gate_min_mhist"] = float(P.get("min_mhist", 0.025))  # default 0.025
    s["gate_use_atr"]   = bool(P.get("use_atr", False))
    s["gate_min_atr"]   = float(P.get("min_atr", 0.3))
    s["atr_len"]        = int(P.get("atr_len", 14))
    s["gate_use_trend"] = bool(P.get("use_trend", True))
    s["gate_pivot_span"]= int(P.get("pivot_span", 3))
    s["gate_trend_within"]=int(P.get("trend_within", 72))
    s["gate_use_roc"]   = bool(P.get("use_roc", False))
    s["gate_roc_len"]   = int(P.get("roc_len", 10))
    s["gate_min_roc"]   = float(P.get("min_roc", 0.5))
    s["gate_K"]         = int(P.get("K", 2))
    s["gate_Y"]         = int(P.get("Y", 1))

if st.session_state["__pending_preset"] is not None:
    _apply_preset_dict(st.session_state["__pending_preset"])
    st.session_state["__pending_preset"] = None

# ----------------- indicators
def ema(s, span): return s.ewm(span=span, adjust=False).mean()
def rsi(close, length=14):
    d=close.diff()
    up=pd.Series(np.where(d>0,d,0.0), index=close.index).ewm(alpha=1/length, adjust=False).mean()
    dn=pd.Series(np.where(d<0,-d,0.0), index=close.index).ewm(alpha=1/length, adjust=False).mean()
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

# ----------------- exchange helpers
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
    return coinbase_list_products(quote)

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
            interval=imap.get(gran_sec)
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

def df_for_any_tf(exchange, pair, primary_tf):
    for tf in [primary_tf, "1h", "4h", "12h"]:
        d=df_for_tf(exchange, pair, tf)
        if d is not None and len(d)>=2:
            return d, tf
    return None, None

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

def load_presets_from_disk():
    try:
        if PRESET_PATH.exists(): return json.loads(PRESET_PATH.read_text())
    except Exception: pass
    return {}
def save_presets_to_disk(p):
    try: PRESET_PATH.write_text(json.dumps(p, indent=2))
    except Exception: pass

# -------------- page / css
st.set_page_config(page_title=TITLE, layout="wide")
st.markdown("""
<style>
/* Stronger deep blue for sidebar controls */
section[data-testid="stSidebar"] .stButton > button,
section[data-testid="stSidebar"] button,
section[data-testid="stSidebar"] div [role="button"] {
  background-color:#0d47a1 !important;color:#fff !important;border:0;border-radius:6px;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary {
  background:#0d47a122;border-radius:8px;
}
</style>
""", unsafe_allow_html=True)
st.title(TITLE)

with st.sidebar:
    if st.button("Collapse all", use_container_width=True):
        st.session_state["collapse_all_now"]=True
        st.rerun()

    use_my_pairs = st.toggle("⭐ Use My Pairs only", value=False, help="If ON, scan only the pairs you pin below.")
    with st.expander("Manage My Pairs", expanded=False):
        cur=", ".join(sorted(st.session_state["my_pairs"])) if st.session_state["my_pairs"] else ""
        txt=st.text_area("Pinned pairs (comma-separated)", cur, height=80)
        if st.button("Save My Pairs"):
            st.session_state["my_pairs"] = set(p.strip().upper() for p in txt.split(",") if p.strip())
            st.success("Saved")

def expander(title, key):
    opened = not st.session_state.get("collapse_all_now", False)
    return st.sidebar.expander(title, expanded=opened)

with expander("Market", "exp_market"):
    exchange = st.selectbox("Exchange", EXCHANGES, index=0, help=HINT["exchange"])
    effective_exchange = exchange if "coming soon" not in exchange else "Coinbase"
    if "coming soon" in exchange:
        st.info("Coming soon. Using Coinbase for now.")
    quote = st.selectbox("Quote currency", QUOTES, index=0, help=HINT["quote"])
    use_watch_only = st.checkbox("Use watchlist only (ignore discovery)", value=False, help=HINT["watchlist_only"])
    watchlist = st.text_area("Watchlist (comma-separated)",
                             "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD",
                             help=HINT["watchlist"])

with expander("Mode", "exp_mode"):
    mode = st.radio("Data source", ["REST only","WebSocket + REST (hybrid)"], index=0, horizontal=True, help=HINT["mode"])
    ws_chunk = st.slider("WS subscribe chunk (Coinbase)", 2, 20, 5, 1, help="Fewer = lighter websocket load.")

with expander("Timeframes", "exp_tf"):
    sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=1, help=HINT["sort_tf"])  # default 1h
    sort_desc = st.checkbox("Sort descending (largest first)", True, help=HINT["sort_desc"])

with expander("Gates", "exp_gates"):
    st.caption("Green when at least **K** gates pass (Δ always counted). Yellow shows near‑miss (≥ **Y** but < K).")

    # Hion starter toggle (applies instantly)
    HION = {
        "min_pct": 5.0,
        "use_vol_spike": True, "vol_mult": 1.05,
        "use_rsi": False, "min_rsi": 55, "rsi_len": 14,
        "use_macd": True, "min_mhist": 0.025,
        "use_atr": False, "min_atr": 0.3, "atr_len": 14,
        "use_trend": True, "pivot_span": 3, "trend_within": 72,
        "use_roc": False, "roc_len": 10, "min_roc": 0.5,
        "K": 2, "Y": 1
    }
    if st.toggle("Use hioncrypto (starter)", value=False, help="Apply micro+macro friendly, semi‑loose defaults."):
        st.session_state["__pending_preset"]=HION
        st.rerun()

    logic   = st.radio("Gate logic", ["ALL","ANY"], index=0, horizontal=True, help=HINT["logic"])
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 80.0, st.session_state.get("gate_min_pct",5.0), 0.5, help=HINT["min_pct"], key="gate_min_pct")

    c1,c2,c3 = st.columns(3)
    with c1:
        st.toggle("Volume spike×", st.session_state.get("gate_use_vol",True), key="gate_use_vol", help=HINT["vol_spike"])
        st.slider("Spike multiple ×", 1.0, 6.0, st.session_state.get("gate_vol_mult",1.05), 0.05, key="gate_vol_mult", help=HINT["vol_spike"])
        st.toggle("RSI", st.session_state.get("gate_use_rsi",False), key="gate_use_rsi", help=HINT["rsi"])
        st.slider("Min RSI", 40, 90, st.session_state.get("gate_min_rsi",55), 1, key="gate_min_rsi", help=HINT["rsi"])
    with c2:
        st.toggle("MACD hist", st.session_state.get("gate_use_macd",True), key="gate_use_macd", help=HINT["macd"])
        st.slider("Min MACD hist", 0.0, 2.0, st.session_state.get("gate_min_mhist",0.025), 0.005, key="gate_min_mhist", help=HINT["macd"])
        st.toggle("ATR %", st.session_state.get("gate_use_atr",False), key="gate_use_atr", help=HINT["atr"])
        st.slider("Min ATR %", 0.0, 10.0, st.session_state.get("gate_min_atr",0.3), 0.1, key="gate_min_atr", help=HINT["atr"])
    with c3:
        st.toggle("Trend breakout (up)", st.session_state.get("gate_use_trend",True), key="gate_use_trend", help=HINT["trend"])
        st.slider("Pivot span (bars)", 2, 10, st.session_state.get("gate_pivot_span",3), 1, key="gate_pivot_span", help=HINT["pivot_span"])
        st.slider("Breakout within (bars)", 5, 144, st.session_state.get("gate_trend_within",72), 1, key="gate_trend_within", help=HINT["trend_within"])
        st.toggle("ROC %", st.session_state.get("gate_use_roc",False), key="gate_use_roc", help="Rate of Change gate.")
        st.slider("ROC length (bars)", 2, 60, st.session_state.get("gate_roc_len",10), 1, key="gate_roc_len")
        st.slider("Min ROC %", 0.0, 50.0, st.session_state.get("gate_min_roc",0.5), 0.5, key="gate_min_roc")

    st.divider()
    st.selectbox("Gates needed to turn **green** (K)", list(range(1,8)), index=1, key="gate_K", help=HINT["k_green"])
    st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0,7)), index=1, key="gate_Y", help=HINT["k_yellow"])

    enabled_checks = 1 + sum([st.session_state["gate_use_vol"], st.session_state["gate_use_roc"],
                              st.session_state["gate_use_trend"], st.session_state["gate_use_rsi"],
                              st.session_state["gate_use_macd"], st.session_state["gate_use_atr"]])
    K_eff = max(1, min(st.session_state["gate_K"], enabled_checks))
    Y_eff = max(0, min(st.session_state["gate_Y"], max(0, K_eff-1)))
    st.caption(f"Enabled now: {enabled_checks} • Green uses K={K_eff} • Yellow uses Y={Y_eff}")
    st.caption("Tips: lower Min %+ / reduce K / toggle off gates if nothing shows.")

with expander("Indicator lengths", "exp_lens"):
    st.slider("RSI length", 5, 50, st.session_state.get("rsi_len",14), 1, key="rsi_len", help=HINT["len_rsi"])
    st.slider("MACD fast EMA", 3, 50, st.session_state.get("macd_fast",12), 1, key="macd_fast", help=HINT["len_macd"])
    st.slider("MACD slow EMA", 5, 100, st.session_state.get("macd_slow",26), 1, key="macd_slow", help=HINT["len_macd"])
    st.slider("MACD signal", 3, 50, st.session_state.get("macd_sig",9), 1, key="macd_sig", help=HINT["len_macd"])
    st.slider("ATR length", 5, 50, st.session_state.get("atr_len",14), 1, key="atr_len", help=HINT["len_atr"])
    st.slider("Volume SMA window", 5, 50, st.session_state.get("vol_window",20), 1, key="vol_window", help=HINT["len_vol"])

with expander("Trend Break (ATH/ATL window)", "exp_hist"):
    basis = st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=1, help=HINT["trend_basis"])
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1, help=HINT["trend_amount"])
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 90, 1, help=HINT["trend_amount"])
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 12, 1, help=HINT["trend_amount"])

with expander("Display", "exp_disp"):
    font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05, help=HINT["font"])

with expander("Notifications", "exp_notif"):
    email_to    = st.text_input("Email recipient (optional)", "", help=HINT["email"])
    webhook_url = st.text_input("Webhook URL (optional)", "", help=HINT["webhook"])

with expander("Auto-refresh", "exp_auto"):
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 30, 1, help=HINT["refresh"])
    st.caption("Auto‑refresh is always on.")

# Collapse flag is one-shot
st.session_state["collapse_all_now"]=False

# Show active TF + Trend window under title
st.caption(f"Timeframe: {sort_tf} • Trend Break window: {basis} {amount}")

# ---------- discovery set (NO CAP)
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
    pairs = [p for p in pairs if p.endswith(f"-{quote}")]
st.caption(f"Discovery: found {disc_count} exchange pairs • merged set {len(pairs)}")
if not pairs:
    st.info("No pairs to scan. Turn OFF 'Use watchlist only', set Quote=USD, or adjust gates.")
    st.stop()

# optional WS
if (mode.startswith("WebSocket") and effective_exchange=="Coinbase" and WS_AVAILABLE and not st.session_state["ws_alive"]):
    pick=pairs[:min(10,len(pairs))]
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

# ---------- builders
def ath_atl_for_pair(exchange, pid, basis, amount):
    hist=get_hist(exchange, pid, basis, amount)
    if hist is None or len(hist)<10:
        return np.nan,"—",np.nan,"—"
    aa=ath_atl_info(hist)
    return aa["From ATH %"], aa["ATH date"], aa["From ATL %"], aa["ATL date"]

def df_for_any_tf(exchange, pair, primary_tf):
    for tf in [primary_tf, "1h", "4h", "12h"]:
        d=df_for_tf(exchange, pair, tf)
        if d is not None and len(d)>=2:
            return d, tf
    return None, None

def build_row(pid):
    dft, used_tf = df_for_any_tf(effective_exchange, pid, sort_tf)
    if dft is None or len(dft)<30: return None
    dft=dft.tail(400).copy()
    last=float(dft["close"].iloc[-1])
    if effective_exchange=="Coinbase" and st.session_state["ws_prices"].get(pid):
        last=float(st.session_state["ws_prices"][pid])
    first=float(dft["close"].iloc[0])
    pct=(last/first-1.0)*100.0

    athp,athd,atlp,atld=ath_atl_for_pair(effective_exchange, pid, basis, amount)

    rsi_ser=rsi(dft["close"], st.session_state.get("rsi_len",14))
    mh_ser=macd_hist(dft["close"], st.session_state.get("macd_fast",12), st.session_state.get("macd_slow",26), st.session_state.get("macd_sig",9))
    atr_pct=atr(dft, st.session_state.get("atr_len",14))/(dft["close"]+1e-12)*100.0
    volx=volume_spike(dft, st.session_state.get("vol_window",20))
    tr_up=trend_breakout_up(dft, st.session_state.get("gate_pivot_span",3), st.session_state.get("gate_trend_within",72))
    roc_ser=roc(dft["close"], st.session_state.get("gate_roc_len",10))

    ok_delta=(pct>0) and (pct>=st.session_state.get("gate_min_pct",5.0))
    ok_vol= (volx>=st.session_state.get("gate_vol_mult",1.05)) if st.session_state.get("gate_use_vol",True) else True
    ok_roc= (roc_ser.iloc[-1]>=st.session_state.get("gate_min_roc",0.5)) if st.session_state.get("gate_use_roc",False) else True
    ok_trend=bool(tr_up) if st.session_state.get("gate_use_trend",True) else True
    ok_rsi=(rsi_ser.iloc[-1]>=st.session_state.get("gate_min_rsi",55)) if st.session_state.get("gate_use_rsi",False) else True
    ok_macd=(mh_ser.iloc[-1]>=st.session_state.get("gate_min_mhist",0.025)) if st.session_state.get("gate_use_macd",True) else True
    ok_atr=(atr_pct.iloc[-1]>=st.session_state.get("gate_min_atr",0.3)) if st.session_state.get("gate_use_atr",False) else True

    enabled=[True, st.session_state.get("gate_use_vol",True), st.session_state.get("gate_use_roc",False),
             st.session_state.get("gate_use_trend",True), st.session_state.get("gate_use_rsi",False),
             st.session_state.get("gate_use_macd",True), st.session_state.get("gate_use_atr",False)]
    values=[ok_delta, ok_vol, ok_roc, ok_trend, ok_rsi, ok_macd, ok_atr]
    counted=[v for v,e in zip(values,enabled) if e]
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

# Build rows (NO CAP)
rows=[r for p in pairs if (r:=build_row(p))]

df=pd.DataFrame(rows)
chg_col=f"% Change ({sort_tf})"

# Discovery fallback if gates hide everything or candles failed
if df.empty:
    mini=[]
    for pid in pairs:
        dft, tf_used = df_for_any_tf(effective_exchange, pid, sort_tf)
        if dft is None or len(dft)<2: continue
        dft=dft.tail(200)
        last=float(dft["close"].iloc[-1]); first=float(dft["close"].iloc[0])
        mini.append({"Pair":pid,"Price":last,f"% Change ({tf_used})":(last/first-1.0)*100.0})
    if mini:
        st.warning("No rows passed gates. Showing Discovery (unfiltered). Loosen Min %+ / reduce K / toggle off gates.")
        mdf=pd.DataFrame(mini)
        # find the change column we created above:
        chcols=[c for c in mdf.columns if c.startswith("% Change")]
        sortc=chcols[0] if chcols else "Price"
        mdf=mdf.sort_values(sortc, ascending=False)
        mdf.insert(0,"#",range(1,len(mdf)+1))
        st.dataframe(mdf, use_container_width=True)
    else:
        st.error("No candle data available. Try TF=1h and Quote=USD.")
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

mode_label='WS+REST' if (mode.startswith('WebSocket') and effective_exchange=='Coinbase' and WS_AVAILABLE) else 'REST only'
st.caption(f"Pairs: {len(df)} • Exchange: {effective_exchange} • Quote: {quote} • Sort TF: {sort_tf} • Mode: {mode_label}")

remaining = st.session_state["refresh_sec"] - (time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"]=time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh ~{st.session_state['refresh_sec']}s (next in {int(remaining)}s)")


