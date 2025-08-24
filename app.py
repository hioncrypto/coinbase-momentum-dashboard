# app.py — Crypto Tracker by hioncrypto
# Live exchanges: Coinbase, Binance, Kraken, KuCoin, Bybit (public endpoints only)
# Pairs are discovered regardless of presets (loose defaults; gating never hides discovery table).
# Starter toggle sits above K; email/webhook alerts on NEW Top‑10; lighter blue UI; Collapse All works.

import json, time, datetime as dt, ssl, smtplib
from typing import List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
import requests
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------------- Page + softer blue CSS ----------------
st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")
st.markdown("""
<style>
:root{
  --mv-blue:#7EB3FF;         /* lighter, ~half intensity */
  --mv-blue-2:#5C97E6;
  --mv-true-yellow: rgba(255,255,0,.70);
  --mv-true-green: rgba(0,200,0,.22);
}
section[data-testid="stSidebar"] button, section[data-testid="stSidebar"] .stButton button{
  background: var(--mv-blue)!important; color:#fff!important; border:0!important; border-radius:10px!important;
  box-shadow: 0 1px 0 rgba(0,0,0,.10);
}
section[data-testid="stSidebar"] details>summary{
  background: linear-gradient(90deg, var(--mv-blue), #A9CBFF);
  color:#0b1a33 !important; padding:10px 12px; border-radius:10px; margin:6px 0; font-weight:800; letter-spacing:.2px;
}
section[data-testid="stSidebar"] details[open]>summary{ background: linear-gradient(90deg, var(--mv-blue-2), #7EB3FF); color:#fff!important;}
.mv-chip{display:inline-block;padding:2px 6px;margin-right:6px;border-radius:6px;font-size:.78rem;color:#111;background:#f1f6ff;border:1px solid #d3e4ff}
.mv-ok{background:#d8f6d8;border-color:#9be39b}
.mv-bad{background:#ffe3e3;border-color:#ffb1b1}
.mv-row-green{background: var(--mv-true-green)!important; font-weight:700;}
.mv-row-yellow{background: var(--mv-true-yellow)!important; font-weight:700;}
.mv-topline{position:sticky;top:0;z-index:5; padding:10px 8px; background:rgba(22,24,29,.85); backdrop-filter: blur(6px); color:#fff;}
</style>
""", unsafe_allow_html=True)

# ---------------- Session defaults ----------------
def _init_state():
    ss = st.session_state
    ss.setdefault("collapse_all_now", False)
    ss.setdefault("my_pairs", set())
    ss.setdefault("use_my_pairs_only", False)
    ss.setdefault("alert_seen", set())
    ss.setdefault("page_size", 50)
    ss.setdefault("page_idx", 0)
_init_state()

# ---------------- Exchanges & TFs ----------------
EXCHANGES = ["Coinbase", "Binance", "Kraken", "KuCoin", "Bybit"]
DEFAULT_QUOTE = {"Coinbase":"USD", "Binance":"USDT", "Kraken":"USD", "KuCoin":"USDT", "Bybit":"USDT"}
QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]

TF_SEC = {"15m":900, "1h":3600, "4h":14400, "6h":21600, "12h":43200, "1d":86400}
DEFAULT_TFS = ["15m","1h","4h","6h","12h","1d"]

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"
KR_BASE = "https://api.kraken.com"
KC_BASE = "https://api.kucoin.com"
BB_BASE = "https://api.bybit.com"

# ---------------- Discovery: products ----------------
def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25); r.raise_for_status()
        return sorted(set(f"{p['base_currency']}-{p['quote_currency']}"
                          for p in r.json() if p.get("quote_currency")==quote))
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=30); r.raise_for_status()
        out=[]
        for s in r.json().get("symbols", []):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote:
                out.append(f"{s['baseAsset']}-{quote}")
        return sorted(set(out))
    except Exception:
        return []

# Kraken helpers: map wsname/altname to nice BASE-QUOTE and to altname for OHLC
def _kraken_pairs_map() -> Dict[str, Dict[str,str]]:
    # returns { "BTC-USD": {"alt":"XBTUSD"}, ... }
    try:
        r = requests.get(f"{KR_BASE}/0/public/AssetPairs", timeout=30); r.raise_for_status()
        data=r.json().get("result",{})
        m={}
        # Simple symbol normalization (XBT->BTC, XDG->DOGE)
        sym_map={"XBT":"BTC","XDG":"DOGE"}
        for k,v in data.items():
            ws=v.get("wsname")  # e.g., "XBT/USD"
            alt=v.get("altname") # e.g., "XBTUSD"
            if not ws or not alt: continue
            try:
                base,quote = ws.split("/")
                base=sym_map.get(base, base); quote=sym_map.get(quote, quote)
                pretty=f"{base}-{quote}".upper()
                m[pretty]={"alt":alt}
            except Exception:
                continue
        return m
    except Exception:
        return {}

_KRAKEN_MAP = None

def kraken_list_products(quote: str) -> List[str]:
    global _KRAKEN_MAP
    if _KRAKEN_MAP is None:
        _KRAKEN_MAP = _kraken_pairs_map()
    return sorted([p for p in _KRAKEN_MAP.keys() if p.endswith(f"-{quote}")])

def kucoin_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{KC_BASE}/api/v1/symbols", timeout=30); r.raise_for_status()
        out=[]
        for s in r.json().get("data", []):
            if not s.get("enableTrading"): continue
            if s.get("quoteCurrency")==quote:
                out.append(s.get("symbol"))  # already like BTC-USDT
        return sorted(set(out))
    except Exception:
        return []

def bybit_list_products(quote: str) -> List[str]:
    try:
        # v5 instruments info (spot)
        r = requests.get(f"{BB_BASE}/v5/market/instruments-info",
                         params={"category":"spot"}, timeout=30)
        r.raise_for_status()
        arr = r.json().get("result",{}).get("list",[])
        out=[]
        for it in arr:
            sym = it.get("symbol","")   # e.g., BTCUSDT
            if not sym: continue
            if not sym.endswith(quote): continue
            base = sym[:-len(quote)]
            out.append(f"{base}-{quote}")
        return sorted(set(out))
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange=="Coinbase": return coinbase_list_products(quote)
    if exchange=="Binance":  return binance_list_products(quote)
    if exchange=="Kraken":   return kraken_list_products(quote)
    if exchange=="KuCoin":   return kucoin_list_products(quote)
    if exchange=="Bybit":    return bybit_list_products(quote)
    return []

# ---------------- Candles (all 5) ----------------
def fetch_candles_coinbase(pair: str, gran: int,
                           start: Optional[dt.datetime]=None,
                           end: Optional[dt.datetime]=None)->Optional[pd.DataFrame]:
    try:
        url=f"{CB_BASE}/products/{pair}/candles?granularity={gran}"
        params={}
        if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
        if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
        r=requests.get(url, params=params, timeout=30)
        if r.status_code!=200: return None
        arr=r.json()
        if not arr: return None
        df=pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
        df["ts"]=pd.to_datetime(df["ts"], unit="s", utc=True)
        return df.sort_values("ts").reset_index(drop=True)
    except Exception:
        return None

def fetch_candles_binance(pair_dash: str, sec: int)->Optional[pd.DataFrame]:
    try:
        base, quote = pair_dash.split("-")
        symbol = f"{base}{quote}"
        interval_map = {900:"15m", 3600:"1h", 14400:"4h", 21600:"6h", 43200:"12h", 86400:"1d"}
        itv = interval_map.get(sec)
        if not itv: return None
        r = requests.get(f"{BN_BASE}/api/v3/klines",
                         params={"symbol":symbol, "interval":itv, "limit":1000}, timeout=30)
        if r.status_code!=200: return None
        rows=[]
        for a in r.json():
            rows.append({"ts":pd.to_datetime(a[0], unit="ms", utc=True),
                         "open":float(a[1]), "high":float(a[2]), "low":float(a[3]),
                         "close":float(a[4]), "volume":float(a[5])})
        return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    except Exception:
        return None

def fetch_candles_kraken(pair_dash: str, sec: int)->Optional[pd.DataFrame]:
    # Kraken OHLC intervals: 15m=15, 1h=60, 4h=240, 6h=360, 12h=720, 1d=1440
    try:
        global _KRAKEN_MAP
        if _KRAKEN_MAP is None:
            _KRAKEN_MAP = _kraken_pairs_map()
        alt = _KRAKEN_MAP.get(pair_dash, {}).get("alt")
        if not alt: return None
        itv_map = {900:15, 3600:60, 14400:240, 21600:360, 43200:720, 86400:1440}
        itv = itv_map.get(sec)
        if not itv: return None
        r = requests.get(f"{KR_BASE}/0/public/OHLC", params={"pair":alt, "interval":itv}, timeout=30)
        if r.status_code!=200: return None
        result = r.json().get("result", {})
        # result has a key equal to 'alt' or another code; pick the first list
        k = next((k for k in result.keys() if k != "last"), None)
        if not k: return None
        rows=[]
        for a in result[k]:
            # a = [time, open, high, low, close, vwap, volume, count]
            rows.append({"ts":pd.to_datetime(int(a[0]), unit="s", utc=True),
                         "open":float(a[1]), "high":float(a[2]), "low":float(a[3]),
                         "close":float(a[4]), "volume":float(a[6])})
        return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    except Exception:
        return None

def fetch_candles_kucoin(pair_dash: str, sec: int)->Optional[pd.DataFrame]:
    # KuCoin types: 15min, 1hour, 4hour, 6hour, 12hour, 1day
    try:
        type_map = {900:"15min", 3600:"1hour", 14400:"4hour", 21600:"6hour", 43200:"12hour", 86400:"1day"}
        t = type_map.get(sec)
        if not t: return None
        r = requests.get(f"{KC_BASE}/api/v1/market/candles",
                         params={"type":t, "symbol":pair_dash}, timeout=30)
        if r.status_code!=200: return None
        # KuCoin returns newest first
        rows=[]
        for a in r.json().get("data", []):
            # [time, open, close, high, low, volume, turnover]
            rows.append({"ts":pd.to_datetime(int(a[0]), unit="s", utc=True),
                         "open":float(a[1]), "high":float(a[3]), "low":float(a[4]),
                         "close":float(a[2]), "volume":float(a[5])})
        if not rows: return None
        return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    except Exception:
        return None

def fetch_candles_bybit(pair_dash: str, sec: int)->Optional[pd.DataFrame]:
    # Bybit v5 kline (spot): interval: 15, 60, 240, 360, 720, D
    try:
        base, quote = pair_dash.split("-")
        symbol = f"{base}{quote}"
        itv_map = {900:"15", 3600:"60", 14400:"240", 21600:"360", 43200:"720", 86400:"D"}
        itv = itv_map.get(sec)
        if not itv: return None
        r = requests.get(f"{BB_BASE}/v5/market/kline",
                         params={"category":"spot","symbol":symbol,"interval":itv,"limit":1000}, timeout=30)
        if r.status_code!=200: return None
        lst = r.json().get("result",{}).get("list",[])
        rows=[]
        for a in lst:
            # [start, open, high, low, close, volume, turnover]
            rows.append({"ts":pd.to_datetime(int(a[0]), unit="ms", utc=True),
                         "open":float(a[1]), "high":float(a[2]), "low":float(a[3]),
                         "close":float(a[4]), "volume":float(a[5])})
        if not rows: return None
        return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    except Exception:
        return None

def resample_ohlcv(df: pd.DataFrame, target_sec: int)->Optional[pd.DataFrame]:
    if df is None or df.empty: return None
    d=df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    out=d.resample(f"{target_sec}s", label="right", closed="right").agg(agg).dropna()
    return out.reset_index()

def df_for_tf(exchange: str, pair: str, tf: str)->Optional[pd.DataFrame]:
    sec = TF_SEC[tf]
    if exchange=="Coinbase":
        native = sec in {900,3600,21600,86400}
        base = fetch_candles_coinbase(pair, sec if native else 3600)
        return base if native else resample_ohlcv(base, sec)
    if exchange=="Binance":  return fetch_candles_binance(pair, sec)
    if exchange=="Kraken":   return fetch_candles_kraken(pair, sec)
    if exchange=="KuCoin":   return fetch_candles_kucoin(pair, sec)
    if exchange=="Bybit":    return fetch_candles_bybit(pair, sec)
    return None

# ---------------- Indicators ----------------
def ema(s: pd.Series, span:int)->pd.Series: return s.ewm(span=span, adjust=False).mean()
def rsi(close: pd.Series, length=14)->pd.Series:
    d=close.diff()
    up=np.where(d>0,d,0.0); dn=np.where(d<0,-d,0.0)
    ru=pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rd=pd.Series(dn, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs=ru/(rd+1e-12); return 100-(100/(1+rs))
def macd_hist(close: pd.Series, fast=12, slow=26, sig=9)->pd.Series:
    m=ema(close,fast)-ema(close,slow); s=ema(m,sig); return m-s
def atr(df: pd.DataFrame, length=14)->pd.Series:
    h,l,c=df["high"],df["low"],df["close"]; pc=c.shift(1)
    tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()
def volume_spike_x(df: pd.DataFrame, window=20)->float:
    if len(df)<window+1: return np.nan
    return float(df["volume"].iloc[-1] / (df["volume"].rolling(window).mean().iloc[-1] + 1e-12))
def roc(close: pd.Series, length=10)->pd.Series:
    return (close/close.shift(length)-1.0)*100.0
def find_pivots(close: pd.Series, span=3)->Tuple[pd.Index,pd.Index]:
    n=len(close); v=close.values; hi=[]; lo=[]
    for i in range(span,n-span):
        if v[i]>v[i-span:i].max() and v[i]>v[i+1:i+1+span].max(): hi.append(i)
        if v[i]<v[i-span:i].min() and v[i]<v[i+1:i+1+span].min(): lo.append(i)
    return pd.Index(hi), pd.Index(lo)
def trend_breakout_up(df: pd.DataFrame, span=3, within_bars=96)->bool:
    if df is None or len(df)<span*2+5: return False
    highs,_=find_pivots(df["close"], span)
    if len(highs)==0: return False
    hi=int(highs[-1]); level=float(df["close"].iloc[hi])
    cross=None
    for j in range(hi+1, len(df)):
        if float(df["close"].iloc[j])>level:
            cross=j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# ---------------- ATH/ATL window ----------------
def hist_for_window(exchange: str, pair: str, basis:str, amt:int)->Optional[pd.DataFrame]:
    end=dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":  gran=3600;  start=end-dt.timedelta(hours=amt)
    elif basis=="Daily": gran=86400; start=end-dt.timedelta(days=amt)
    else:                gran=86400; start=end-dt.timedelta(weeks=amt)
    out=[]; cursor=end
    while True:
        # Use each exchange's native granularity where possible
        if exchange=="Coinbase":
            df=fetch_candles_coinbase(pair, gran, start=max(start, cursor-dt.timedelta(days=30)), end=cursor)
        elif exchange=="Binance":
            df=fetch_candles_binance(pair, gran)
            # Binance kline ignores start/end in this simplified call; acceptable for window context
        elif exchange=="Kraken":
            df=fetch_candles_kraken(pair, gran)
        elif exchange=="KuCoin":
            df=fetch_candles_kucoin(pair, gran)
        else:
            df=fetch_candles_bybit(pair, gran)
        if df is None or df.empty: break
        df=df[(df["ts"]<=cursor) & (df["ts"]>=max(start, cursor-dt.timedelta(days=30)))]
        if df.empty: break
        out.append(df); cursor=df["ts"].iloc[0]
        if cursor<=start: break
        if exchange in ("Binance","KuCoin","Bybit"): break  # already got up to 1000 bars
    if not out: return None
    hist=pd.concat(out, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if basis=="Weekly":
        hist = resample_ohlcv(hist, 7*86400)
    return hist

def ath_atl_info(hist: pd.DataFrame)->Dict[str,object]:
    last=float(hist["close"].iloc[-1])
    ia=int(hist["high"].idxmax()); iz=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[ia]); atd=pd.to_datetime(hist["ts"].iloc[ia]).date().isoformat()
    atl=float(hist["low"].iloc[iz]);  ztd=pd.to_datetime(hist["ts"].iloc[iz]).date().isoformat()
    return {"From ATH %":(last/ath-1.0)*100 if ath>0 else np.nan,"ATH date":atd,"From ATL %":(last/atl-1.0)*100 if atl>0 else np.nan,"ATL date":ztd}

# ---------------- Alerts ----------------
def send_email_alert(subject, body, recipient):
    try: cfg=st.secrets["smtp"]
    except Exception: return False,"SMTP not configured (set st.secrets['smtp'])"
    try:
        msg=MIMEMultipart(); msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body,"plain"))
        ctx=ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port",465), context=ctx) as s:
            s.login(cfg["user"], cfg["password"]); s.sendmail(cfg["sender"], recipient, msg.as_string())
        return True,"OK"
    except Exception as e:
        return False, str(e)

def post_webhook(url, payload):
    try:
        r=requests.post(url, json=payload, timeout=10)
        return (200<=r.status_code<300), r.text
    except Exception as e:
        return False, str(e)

# ---------------- Sidebar header ----------------
with st.sidebar:
    c1, c2 = st.columns([1,1])
    if c1.button("Collapse all", use_container_width=True, help="Collapse every section in the sidebar."):
        st.session_state["collapse_all_now"]=True
    st.session_state["use_my_pairs_only"] = c2.toggle("⭐ Use My Pairs only", value=st.session_state["use_my_pairs_only"],
                                                     help="When ON, only scan pairs you pinned in ‘Manage My Pairs’.")
    st.divider()

def expander(title, key):
    opened = not st.session_state.get("collapse_all_now", False)
    return st.sidebar.expander(title, expanded=opened, key=key)

# ---------------- Manage My Pairs ----------------
with expander("Manage My Pairs", "exp_my"):
    st.caption("Add/remove pins; use the ⭐ toggle above to scan only these.")
    pins = sorted(st.session_state["my_pairs"])
    st.write("Pinned:", ", ".join(pins) if pins else "—")
    npair = st.text_input("Add pair (e.g., SOL-USDT)")
    cc = st.columns([1,1,1])
    if cc[0].button("Add"):
        if npair.strip(): st.session_state["my_pairs"].add(npair.strip().upper())
    if cc[1].button("Clear"):
        st.session_state["my_pairs"]=set()
    if cc[2].button("Load BTC/ETH/SOL"):
        # Add both USD and USDT versions for cross-exchange convenience
        st.session_state["my_pairs"].update({"BTC-USD","ETH-USD","SOL-USD","BTC-USDT","ETH-USDT","SOL-USDT"})

# ---------------- Market ----------------
with expander("Market", "exp_market"):
    st.caption("Pick exchange & quote. Typical: Coinbase→USD, Binance/KuCoin/Bybit→USDT, Kraken→USD.")
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    def_q = DEFAULT_QUOTE.get(exchange, "USD")
    quote = st.selectbox("Quote currency", QUOTES, index=QUOTES.index(def_q) if def_q in QUOTES else 0,
                         help="Use USDT on Binance/KuCoin/Bybit; USD on Coinbase/Kraken for best coverage.")
    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False,
                            help="ON = only scan the comma-separated list below.")
    default_watch = "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD, BTC-USDT, ETH-USDT, SOL-USDT"
    watchlist = st.text_area("Watchlist (comma-separated)", default_watch, height=80)

# ---------------- Timeframes ----------------
with expander("Timeframes", "exp_tf"):
    pick_tfs = st.multiselect("Available timeframes", list(TF_SEC.keys()), default=DEFAULT_TFS,
                              help="Choose timeframes to show; the ‘Primary’ controls % Change and ranks.")
    sort_tf  = st.selectbox("Primary sort timeframe", list(TF_SEC.keys()), index=1,
                            help="Used for % Change and Top‑10. Default 1h.")
    sort_desc = st.checkbox("Sort descending (largest first)", value=True)

# ---------------- Gates (with Hioncrypto starter above K) ----------------
with expander("Gates", "exp_gates"):
    gate_logic = st.radio("Gate logic", ["ALL","ANY"], index=0, horizontal=True,
                          help="ALL = must satisfy multiple gates; ANY = passes if any gate is satisfied.")
    # Loose defaults even with starter OFF → pairs still appear
    min_pct = st.slider("Min +% change (Primary TF)", 0.0, 50.0, 1.0, 0.5,
                        help="Positive‑only % change over the Primary timeframe.")

    cA = st.columns(3)
    with cA[0]:
        use_vol = st.toggle("Volume spike×", value=False, help="Last volume vs 20‑bar average. Leave OFF to be looser.")
        vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, 1.02, 0.02)
    with cA[1]:
        use_macd = st.toggle("MACD hist", value=False, help="Momentum acceleration. Keep OFF to be looser.")
        min_mhist = st.slider("Min MACD hist", 0.0, 2.0, 0.02, 0.005)
    with cA[2]:
        use_trend = st.toggle("Trend breakout (up)", value=False,
                              help="Close breaks the last pivot high within N bars (see Trend Break window).")
        pivot_span = st.slider("Pivot span (bars)", 2, 10, 3, 1)
        trend_within = st.slider("Breakout within (bars)", 5, 120, 96, 1)

    cB = st.columns(3)
    with cB[0]:
        use_rsi = st.toggle("RSI", value=False, help="Min RSI (e.g., 55+) for strength.")
        min_rsi = st.slider("Min RSI", 40, 90, 55, 1)
    with cB[1]:
        use_atr = st.toggle("ATR %", value=False, help="ATR/close ×100; higher = more range/movement.")
        min_atr = st.slider("Min ATR %", 0.0, 10.0, 0.30, 0.05)
    with cB[2]:
        use_roc = st.toggle("ROC %", value=False, help="Rate of Change over N bars (momentum).")
        roc_len = st.slider("ROC length (bars)", 2, 60, 10, 1)
        min_roc = st.slider("Min ROC %", -10.0, 50.0, 0.0, 0.5)

    st.markdown("---")
    # >>> HIONCRYPTO STARTER (exact placement) <<<
    starter_on = st.toggle("Use hioncrypto (starter)", value=False,
                           help="Friendly defaults so rows appear immediately. Turn OFF to fine‑tune.")
    if starter_on:
        gate_logic = "ALL"
        min_pct    = 1.0
        use_vol, vol_mult = True, 1.02
        use_macd, min_mhist = False, 0.02
        use_trend, pivot_span, trend_within = False, 3, 96
        use_rsi, min_rsi = False, 55
        use_atr, min_atr = False, 0.30
        use_roc, roc_len, min_roc = False, 10, 0.0
        st.info("Starter ON: very loose. You should see pairs. Tighten gates as needed.", icon="✨")

    # K / Y — placed right under starter (as requested)
    k_needed = st.selectbox("Gates needed to turn green (K)", [1,2,3,4,5,6,7], index=0,
                            help="How many of the enabled gates must be true to mark the row GREEN.")
    y_needed = st.selectbox("Yellow needs ≥ Y (but < K)", [0,1,2,3,4,5,6], index=0,
                            help="If not green but at least Y gates pass, row turns YELLOW (watchlist).")
    st.caption("💡 If nothing shows: lower Min %+; set K=1; or toggle off some gates.")

# ---------------- Trend Break window ----------------
with expander("Trend Break window", "exp_window"):
    st.caption("Controls ATH/ATL context and how recent the breakout must be. Hourly = micro; Weekly = macro.")
    basis = st.selectbox("Window basis", ["Hourly","Daily","Weekly"], index=1)
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1)
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 90, 1)
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 12, 1)

# ---------------- Display & Notifications ----------------
with expander("Display", "exp_display"):
    st.session_state["page_size"] = st.slider("Rows per page (table only)", 25, 200, st.session_state["page_size"], 25,
                                              help="Paging affects display only; scanner still processes all pairs.")
    st.session_state["page_idx"]  = st.number_input("Page index (0‑based)", min_value=0, value=st.session_state["page_idx"], step=1)

with expander("Notifications", "exp_notif"):
    alerts_on = st.checkbox("Send Email/Webhook alerts for NEW Top‑10 entrants", value=False)
    email_to  = st.text_input("Email recipient (optional)")
    hook_url  = st.text_input("Webhook URL (optional)")

# ---------------- Build Universe ----------------
if use_watch and watchlist.strip():
    universe = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    universe = list_products(exchange, quote)

if st.session_state["use_my_pairs_only"] and st.session_state["my_pairs"]:
    universe = sorted(set(universe).intersection(st.session_state["my_pairs"]))

if not universe:
    st.warning("No pairs discovered. Try a different quote (USDT for Binance/KuCoin/Bybit, USD for Coinbase/Kraken).")
    st.stop()

# ---------------- Indicators helpers ----------------
def chips_from_checks(checks: List[Tuple[str,bool]])->str:
    out=[]
    for name, ok in checks:
        out.append(f"<span class='mv-chip {'mv-ok' if ok else 'mv-bad'}'>{name[0]}</span>")
    return "".join(out)

# ---------------- Compute rows ----------------
rows=[]
for pid in universe:
    dft = df_for_tf(exchange, pid, sort_tf)
    if dft is None or len(dft)<30: continue
    dft = dft.tail(500).copy()

    last=float(dft["close"].iloc[-1]); first=float(dft["close"].iloc[0])
    pct = (last/first - 1.0)*100.0  # positive-only gating below

    # Micro/macro context for ATH/ATL
    hist = hist_for_window(exchange, pid, basis, amount)
    if hist is None or len(hist)<10:
        athp, atd, atlp, atld = np.nan, "—", np.nan, "—"
    else:
        info = ath_atl_info(hist)
        athp, atd, atlp, atld = info["From ATH %"], info["ATH date"], info["From ATL %"], info["ATL date"]

    checks=[]
    checks.append(("Δ%Change", bool(pct>0 and pct>=min_pct)))
    if use_vol:
        sp = volume_spike_x(dft, 20); checks.append(("Volume×", bool(sp>=vol_mult)))
    if use_roc:
        rc = float(roc(dft["close"], roc_len).iloc[-1]); checks.append(("ROC", bool(rc>=min_roc)))
    if use_trend:
        tb = trend_breakout_up(dft, span=pivot_span, within_bars=trend_within); checks.append(("Trend", bool(tb)))
    if use_rsi:
        rv = float(rsi(dft["close"]).iloc[-1]); checks.append(("RSI", bool(rv>=min_rsi)))
    if use_macd:
        mh = float(macd_hist(dft["close"]).iloc[-1]); checks.append(("MACD", bool(mh>=min_mhist)))
    if use_atr:
        ap = float(atr(dft).iloc[-1])/(last+1e-12)*100.0; checks.append(("ATR", bool(ap>=min_atr)))

    cnt_true = sum(ok for _,ok in checks)
    green = (cnt_true >= k_needed)
    yellow = (not green) and (cnt_true >= y_needed)

    rows.append({
        "Pair": pid, "Price": last, f"% Change ({sort_tf})": pct,
        "From ATH %": athp, "ATH date": atd, "From ATL %": atlp, "ATL date": atld,
        "Gates": chips_from_checks(checks),
        "Strong Buy": "YES" if green else ("PARTIAL" if yellow else "—"),
        "_g": green, "_y": yellow
    })

df = pd.DataFrame(rows)
if df.empty:
    st.warning("Discovery found pairs but candles were unavailable for the chosen TF. Try another TF or quote.")
    st.stop()

chg_col = f"% Change ({sort_tf})"
df = df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
df.insert(0, "#", df.index+1)

gmask = df["_g"].copy(); ymask = df["_y"].copy()
df = df.drop(columns=["_g","_y"])

# ---------------- Topline + Legend ----------------
st.markdown(
    f"<div class='mv-topline'>Timeframe: <b>{sort_tf}</b> • Trend Break window: <b>{basis} {amount}</b> • Exchange: <b>{exchange}</b> • Quote: <b>{quote}</b></div>",
    unsafe_allow_html=True
)
st.markdown(
    "<div class='mv-chip mv-ok'>Δ</div> %Change &nbsp;"
    "<div class='mv-chip mv-ok'>V</div> Volume× &nbsp;"
    "<div class='mv-chip mv-ok'>R</div> ROC &nbsp;"
    "<div class='mv-chip mv-ok'>T</div> Trend &nbsp;"
    "<div class='mv-chip mv-ok'>S</div> RSI &nbsp;"
    "<div class='mv-chip mv-ok'>M</div> MACD &nbsp;"
    "<div class='mv-chip mv-ok'>A</div> ATR",
    unsafe_allow_html=True
)

# ---------------- Top‑10 (green only) + alerts ----------------
st.subheader("📌 Top‑10 (meets green rule)")
top10 = df[gmask].copy().sort_values(chg_col, ascending=False).head(10).reset_index(drop=True)

def _style_green(x: pd.DataFrame):
    s=pd.DataFrame("", index=x.index, columns=x.columns)
    s.loc[:,:]="background-color: var(--mv-true-green); font-weight:700;"
    return s

if top10.empty:
    st.write("—")
else:
    st.dataframe(top10.style.apply(_style_green, axis=None), use_container_width=True,
                 height=min(600, 80+len(top10)*35))

# Alerts for NEW Top‑10 entries
if top10 is not None and not top10.empty:
    msgs=[]
    for _, r in top10.iterrows():
        key=f"{r['Pair']}|{round(float(r[chg_col]),2)}|{sort_tf}"
        if key not in st.session_state["alert_seen"]:
            st.session_state["alert_seen"].add(key)
            msgs.append(f"{r['Pair']}: {float(r[chg_col]):+.2f}% ({sort_tf})  • Strong Buy")
    if msgs and (email_to.strip() or hook_url.strip()):
        subject="Crypto Tracker — NEW Top‑10 entry"
        body="\n".join(msgs)
        if email_to.strip():
            ok,info=send_email_alert(subject, body, email_to.strip())
            if not ok: st.warning(f"Email failed: {info}")
        if hook_url.strip():
            ok,info=post_webhook(hook_url.strip(), {"title":subject, "lines":msgs})
            if not ok: st.warning(f"Webhook failed: {info}")

# ---------------- All pairs (paged) ----------------
st.subheader("📑 All pairs")
ps=st.session_state["page_size"]; pi=st.session_state["page_idx"]
start=pi*ps; end=start+ps
p_df=df.iloc[start:end].copy()
p_g=gmask.iloc[start:end].reset_index(drop=True)
p_y=ymask.iloc[start:end].reset_index(drop=True)

def _style_full(x: pd.DataFrame):
    s=pd.DataFrame("", index=x.index, columns=x.columns)
    for i in range(len(x)):
        if p_g.iloc[i]: s.iloc[i,:]="background-color: var(--mv-true-green); font-weight:700;"
        elif p_y.iloc[i]: s.iloc[i,:]="background-color: var(--mv-true-yellow); font-weight:700;"
    return s

p_df["Gates"]=p_df["Gates"].astype(str)
st.dataframe(p_df.style.apply(_style_full, axis=None), use_container_width=True,
             height=min(900, 120+len(p_df)*35))
st.caption(f"Discovery: {len(universe)} pairs • showing rows {start+1}–{min(end,len(df))} of {len(df)}")

# ---------------- finalize collapse state ----------------
st.session_state["collapse_all_now"]=False
