# app.py — Crypto Tracker by hioncrypto
# Single-file Streamlit app.
# New in this build:
# - Timeframes: Minimum bars slider (5–200, default 30)
# - Diagnostics: Available • Capped • Fetched • Skipped (bars) • Skipped (API) • Shown
# - Listing Radar: detects newly listed pairs (Coinbase/Binance) + parses announcement feeds for upcoming go-live
#   - Blinking badge when unacknowledged events exist
#   - Alerts via existing email/webhook settings

import json, time, datetime as dt, threading, queue, ssl, smtplib, re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
import requests
import streamlit as st

# Optional WebSocket
WS_AVAILABLE = True
try:
    import websocket
except Exception:
    WS_AVAILABLE = False

# ---------------- Constants
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
ALL_TFS = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}
QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

# RSS/announcement defaults (editable in UI). These are best-effort and may change.
DEFAULT_FEEDS = [
    # Coinbase blog RSS often includes listing posts
    "https://blog.coinbase.com/feed",
    # Binance announcements RSS-like feed (fallback to HTML if needed)
    "https://www.binance.com/en/support/announcement",
]

DEFAULTS = dict(
    sort_tf="1h", sort_desc=True,
    min_pct=3.0, lookback_candles=3,
    use_vol_spike=True, vol_mult=1.10, vol_window=20,
    use_rsi=False, rsi_len=14, min_rsi=55,
    use_macd=False, macd_fast=12, macd_slow=26, macd_sig=9, min_mhist=0.0,
    use_atr=False, atr_len=14, min_atr=0.5,
    use_trend=False, pivot_span=4, trend_within=48,
    use_roc=False, min_roc=1.0,
    # MACD Cross gate
    use_macd_cross=True, macd_cross_bars=5, macd_cross_only_bull=True,
    macd_cross_below_zero=True, macd_hist_confirm_bars=3,
    # Color rules
    K_green=3, Y_yellow=2,
    gate_mode="ANY", hard_filter=False, preset="Spike Hunter",
    # History depth
    basis="Daily", amount_daily=90, amount_hourly=24, amount_weekly=12,
    # Timeframes guard
    min_bars=30,
    refresh_sec=30, font_scale=1.0,
    quote="USD", exchange="Coinbase",
    watchlist="BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD",
    discover_cap=400,
    # Listing Radar defaults
    lr_enabled=False, lr_watch_coinbase=True, lr_watch_binance=True,
    lr_watch_quotes="USD, USDT, USDC",
    lr_poll_sec=30, lr_upcoming_sec=300,
    lr_feeds=", ".join(DEFAULT_FEEDS),
    lr_alert_new=True, lr_alert_upcoming=True, lr_upcoming_window_h=48,
)

# ---------------- Persistence via URL params
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
    "use_watch": (False, bool),
    "watchlist": (DEFAULTS["watchlist"], str),
    "discover_cap": (DEFAULTS["discover_cap"], int),
    "use_my_pairs": (False, bool),
    "my_pairs": ("BTC-USD, ETH-USD, SOL-USD", str),

    # Mode
    "mode": ("REST only", str), "ws_chunk": (5, int),

    # TF & sort
    "sort_tf": (DEFAULTS["sort_tf"], str), "sort_desc": (True, bool),
    "min_bars": (DEFAULTS["min_bars"], int),

    # Gates core
    "gate_mode": (DEFAULTS["gate_mode"], str),
    "hard_filter": (DEFAULTS["hard_filter"], bool),
    "preset": (DEFAULTS["preset"], str),
    "lookback_candles": (DEFAULTS["lookback_candles"], int),
    "min_pct": (DEFAULTS["min_pct"], float),

    # Indicators toggles/params
    "use_vol_spike": (DEFAULTS["use_vol_spike"], bool), "vol_mult": (DEFAULTS["vol_mult"], float),
    "use_rsi": (DEFAULTS["use_rsi"], bool), "rsi_len": (DEFAULTS["rsi_len"], int), "min_rsi": (DEFAULTS["min_rsi"], int),
    "use_macd": (DEFAULTS["use_macd"], bool), "macd_fast": (DEFAULTS["macd_fast"], int),
    "macd_slow": (DEFAULTS["macd_slow"], int), "macd_sig": (DEFAULTS["macd_sig"], int), "min_mhist": (DEFAULTS["min_mhist"], float),
    "use_atr": (DEFAULTS["use_atr"], bool), "atr_len": (DEFAULTS["atr_len"], int), "min_atr": (DEFAULTS["min_atr"], float),
    "use_trend": (DEFAULTS["use_trend"], bool), "pivot_span": (DEFAULTS["pivot_span"], int), "trend_within": (DEFAULTS["trend_within"], int),
    "use_roc": (DEFAULTS["use_roc"], bool), "min_roc": (DEFAULTS["min_roc"], float),

    # MACD Cross params
    "use_macd_cross": (DEFAULTS["use_macd_cross"], bool),
    "macd_cross_bars": (DEFAULTS["macd_cross_bars"], int),
    "macd_cross_only_bull": (DEFAULTS["macd_cross_only_bull"], bool),
    "macd_cross_below_zero": (DEFAULTS["macd_cross_below_zero"], bool),
    "macd_hist_confirm_bars": (DEFAULTS["macd_hist_confirm_bars"], int),

    # Color rules (Custom)
    "K_green": (DEFAULTS["K_green"], int), "Y_yellow": (DEFAULTS["Y_yellow"], int),

    # History
    "basis": (DEFAULTS["basis"], str),
    "amount_hourly": (DEFAULTS["amount_hourly"], int),
    "amount_daily": (DEFAULTS["amount_daily"], int),
    "amount_weekly": (DEFAULTS["amount_weekly"], int),

    # Display/Notif
    "font_scale": (DEFAULTS["font_scale"], float),
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
    "lr_feeds": (DEFAULTS["lr_feeds"], str),
    "lr_alert_new": (DEFAULTS["lr_alert_new"], bool),
    "lr_alert_upcoming": (DEFAULTS["lr_alert_upcoming"], bool),
    "lr_upcoming_window_h": (DEFAULTS["lr_upcoming_window_h"], int),
}

def init_persisted_state():
    q = st.query_params
    for k,(dflt,typ) in PERSIST.items():
        if k in q:
            raw = q[k] if not isinstance(q[k], list) else q[k][0]
            val = _coerce(raw, typ)
            if val is None: val = dflt
        else:
            val = dflt
        st.session_state.setdefault(k, val)

def sync_state_to_query_params():
    qp = {k: (", ".join(v) if isinstance(v,(list,tuple)) else str(v)) for k in PERSIST.keys() if (v:=st.session_state.get(k)) is not None}
    if qp: st.query_params.update(qp)

def _init_runtime():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("last_refresh", time.time())

    # Listing Radar runtime
    ss.setdefault("lr_baseline", {"Coinbase": set(), "Binance": set()})
    ss.setdefault("lr_events", [])     # list of dicts
    ss.setdefault("lr_unacked", 0)
    ss.setdefault("lr_last_poll", 0.0)
    ss.setdefault("lr_last_upcoming_poll", 0.0)

_init_runtime()
init_persisted_state()

# ---------------- Indicators
def ema(s: pd.Series, span: int) -> pd.Series: return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    d = close.diff()
    up = np.where(d>0, d, 0.0); dn = np.where(d<0, -d, 0.0)
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
        if float(df["close"].iloc[j])>level: cross=j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# ---------------- HTTP/WS
def coinbase_list_products(quote: str) -> List[str]:
    try:
        r=requests.get(f"{CB_BASE}/products", timeout=25); r.raise_for_status()
        return sorted(f"{p['base_currency']}-{p['quote_currency']}" for p in r.json() if p.get("quote_currency")==quote)
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r=requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25); r.raise_for_status()
        out=[]
        for s in r.json().get("symbols",[]):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote: out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange=="Coinbase": return coinbase_list_products(quote)
    if exchange=="Binance": return binance_list_products(quote)
    return []

def fetch_candles(exchange: str, pair_dash: str, gran_sec: int,
                  start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    try:
        if exchange=="Coinbase":
            url=f"{CB_BASE}/products/{pair_dash}/candles?granularity={gran_sec}"
            params={}
            if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
            if end: params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
            r=requests.get(url, params=params, timeout=25)
            if r.status_code!=200: return None
            arr=r.json()
            if not arr: return None
            df=pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"]=pd.to_datetime(df["ts"], unit="s", utc=True)
            return df.sort_values("ts").reset_index(drop=True)
        elif exchange=="Binance":
            base,quote=pair_dash.split("-"); symbol=f"{base}{quote}"
            interval_map={900:"15m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
            interval=interval_map.get(gran_sec)
            if not interval: return None
            params={"symbol":symbol,"interval":interval,"limit":1000}
            if start: params["startTime"]=int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            if end: params["endTime"]=int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            r=requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=25)
            if r.status_code!=200: return None
            rows=[{"ts":pd.to_datetime(a[0],unit="ms",utc=True),"open":float(a[1]),"high":float(a[2]),
                   "low":float(a[3]),"close":float(a[4]),"volume":float(a[5])} for a in r.json()]
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

# ---------------- WebSocket worker
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

# ---------------- Alerts
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

# ---------------- Gate evaluation
def build_gate_eval(df_tf: pd.DataFrame, settings: dict) -> Tuple[dict,int,str,int]:
    """
    Returns: meta, passed_count, chips_str, enabled_count
    Gates: Δ, Volume×, ROC, Trend, RSI, MACD hist, ATR%, MACD Cross
    """
    n=len(df_tf)
    lb=max(1, min(int(settings["lookback_candles"]), 100, n-1))
    last_close=float(df_tf["close"].iloc[-1])
    ref_close=float(df_tf["close"].iloc[-lb])
    delta_pct=(last_close/ref_close - 1.0)*100.0
    g_delta = bool(delta_pct >= settings["min_pct"])

    macd_line, signal_line, hist = macd_core(df_tf["close"], settings["macd_fast"], settings["macd_slow"], settings["macd_sig"])

    chips=[]; passed=0; enabled=0
    def chip(name, enabled_flag, ok, extra=""):
        if not enabled_flag:
            chips.append(f"{name}–")
        else:
            mark = "✅" if ok else "❌"
            chips.append(f"{name}{mark}{extra}")

    # Δ
    passed += int(g_delta); enabled += 1
    chip("Δ", True, g_delta, f"({delta_pct:+.2f}%)")

    # Volume spike
    if settings["use_vol_spike"]:
        volx=volume_spike(df_tf, settings["vol_window"]); ok=bool(volx >= settings["vol_mult"])
        passed+=int(ok); enabled+=1; chip(" V", True, ok, f"({volx:.2f}×)" if pd.notna(volx) else "")
    else: chip(" V", False, False)

    # ROC
    if settings.get("use_roc", False):
        roc=(df_tf["close"].iloc[-1]/df_tf["close"].iloc[-lb]-1.0)*100.0 if n>lb else np.nan
        ok=bool(pd.notna(roc) and roc >= settings.get("min_roc",1.0))
        passed+=int(ok); enabled+=1; chip(" R", True, ok, f"({roc:+.2f}%)" if pd.notna(roc) else "")
    else: chip(" R", False, False)

    # Trend breakout
    if settings["use_trend"]:
        ok=trend_breakout_up(df_tf, settings["pivot_span"], settings["trend_within"])
        passed+=int(ok); enabled+=1; chip(" T", True, ok)
    else: chip(" T", False, False)

    # RSI
    if settings["use_rsi"]:
        rcur=rsi(df_tf["close"], settings["rsi_len"]).iloc[-1]
        ok=bool(rcur >= settings["min_rsi"])
        passed+=int(ok); enabled+=1; chip(" S", True, ok, f"({rcur:.1f})")
    else: chip(" S", False, False)

    # MACD histogram
    if settings["use_macd"]:
        mh=hist.iloc[-1]
        ok=bool(mh >= settings["min_mhist"])
        passed+=int(ok); enabled+=1; chip(" M", True, ok, f"({mh:.3f})")
    else: chip(" M", False, False)

    # ATR %
    if settings["use_atr"]:
        atr_pct=(atr(df_tf, settings["atr_len"]) / (df_tf["close"]+1e-12) * 100.0).iloc[-1]
        ok=bool(atr_pct >= settings["min_atr"])
        passed+=int(ok); enabled+=1; chip(" A", True, ok, f"({atr_pct:.2f}%)")
    else: chip(" A", False, False)

    # MACD Cross
    cross_meta = {"ok": False, "bars_ago": None, "below_zero": None}
    if settings.get("use_macd_cross", True):
        bars=int(settings.get("macd_cross_bars",5))
        ok=False; bars_ago=None; below=None
        for i in range(1, min(bars+1, len(hist))):
            prev = macd_line.iloc[-i-1] - signal_line.iloc[-i-1]
            now  = macd_line.iloc[-i]   - signal_line.iloc[-i]
            if prev==0: continue
            crossed_up = (prev < 0 and now > 0)
            crossed_dn = (prev > 0 and now < 0)
            if settings.get("macd_cross_only_bull", True):
                hit = crossed_up
            else:
                hit = crossed_up or crossed_dn
            if not hit: continue
            if settings.get("macd_cross_below_zero", True):
                if float(macd_line.iloc[-i]) > 0 or float(signal_line.iloc[-i]) > 0:
                    continue
                below=True
            else:
                below = (float(macd_line.iloc[-i]) < 0 and float(signal_line.iloc[-i]) < 0)
            conf=int(settings.get("macd_hist_confirm_bars",3))
            if conf>0:
                conf_ok = any(hist.iloc[-k] > 0 for k in range(i, min(i+conf, len(hist))))
                if not conf_ok: 
                    continue
            ok=True; bars_ago=i; break
        cross_meta.update({"ok": ok, "bars_ago": bars_ago, "below_zero": below})
        passed+=int(ok); enabled+=1
        display = f"({bars_ago} bars ago)" if bars_ago is not None else f"(≤{bars})"
        chip(" C", True, ok, f" {display}")
    else:
        chip(" C", False, False)

    meta={"delta_pct": delta_pct, "macd_cross": cross_meta}
    return meta, passed, " ".join(chips), enabled

# ---------------- Page & CSS
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
    display:inline-block; padding:3px 8px; color:white; border-radius:8px; font-weight:700; animation: blinkRB 1.2s linear infinite;
  }}
  /* kill fade/dim on renders */
  div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] * {{
      opacity: 1 !important; filter: none !important; transition: none !important;
  }}
</style>
""", unsafe_allow_html=True)

st.title("Crypto Tracker by hioncrypto")

# ---------------- Sidebar top
with st.sidebar:
    c1,c2,c3 = st.columns([1,1,1])
    with c1:
        if st.button("Collapse all", use_container_width=True):
            st.session_state["collapse_all"]=True
    with c2:
        if st.button("Expand all", use_container_width=True):
            st.session_state["collapse_all"]=False
    with c3:
        st.toggle("⭐ Use My Pairs only", key="use_my_pairs",
                  value=st.session_state.get("use_my_pairs", False),
                  help="Only show pairs in your list below.")

    with st.popover("Manage My Pairs"):
        st.caption("Symbols like BTC-USD, ETH-USDT")
        cur = st.text_area("Edit list (comma-separated)", st.session_state.get("my_pairs",""))
        if st.button("Save My Pairs"):
            st.session_state["my_pairs"] = ", ".join([p.strip().upper() for p in cur.split(",") if p.strip()])
            st.success("Saved.")

def expander(title:str):
    return st.sidebar.expander(title, expanded=not st.session_state.get("collapse_all", False))

# ---------------- MARKET
with expander("Market"):
    st.selectbox("Exchange", EXCHANGES, index=EXCHANGES.index(st.session_state["exchange"]), key="exchange",
                 help="Data source for symbols. 'Coming soon' falls back to Coinbase.")
    effective_exchange = "Coinbase" if "coming soon" in st.session_state["exchange"] else st.session_state["exchange"]
    if "coming soon" in st.session_state["exchange"]:
        st.info("This exchange is coming soon. Using Coinbase for data.")
    st.selectbox("Quote currency", QUOTES, index=QUOTES.index(st.session_state["quote"]), key="quote",
                 help="Only pairs with this quote are considered.")
    st.checkbox("Use watchlist only (ignore discovery)", key="use_watch",
                value=st.session_state.get("use_watch", False),
                help="If on, only evaluate the comma-separated list below.")
    st.text_area("Watchlist", st.session_state.get("watchlist", DEFAULTS["watchlist"]), key="watchlist",
                 help="Comma-separated list like BTC-USD, ETH-USD.")

    # available count (pre-cap)
    if st.session_state.get("use_watch") and st.session_state["watchlist"].strip():
        avail = [p.strip().upper() for p in st.session_state["watchlist"].split(",") if p.strip()]
        avail = [p for p in avail if p.endswith(f"-{st.session_state['quote']}")]
    elif st.session_state.get("use_my_pairs"):
        avail = [p.strip().upper() for p in st.session_state.get("my_pairs","").split(",") if p.strip()]
        avail = [p for p in avail if p.endswith(f"-{st.session_state['quote']}")]
    else:
        avail = list_products(effective_exchange, st.session_state["quote"])

    st.slider(f"Pairs to discover (0–500) • Available: {len(avail)}",
              0, 500, int(st.session_state.get("discover_cap", DEFAULTS["discover_cap"])), 10, key="discover_cap",
              help="Caps how many discovered pairs to evaluate when not using watchlist/My Pairs.")

# ---------------- MODE
with expander("Mode"):
    st.radio("Data source", ["REST only","WebSocket + REST (hybrid)"],
             index=0 if st.session_state.get("mode","REST only")=="REST only" else 1, horizontal=True, key="mode",
             help="WebSocket provides fresher last prices on Coinbase.")
    st.slider("WS subscribe chunk (Coinbase)", 2, 20, st.session_state.get("ws_chunk",5), 1, key="ws_chunk",
              help="How many tickers to subscribe to in one chunk.")

# ---------------- TIMEFRAMES
with expander("Timeframes"):
    st.selectbox("Primary sort timeframe", TF_LIST, index=TF_LIST.index(st.session_state.get("sort_tf", DEFAULTS["sort_tf"])), key="sort_tf",
                 help="Determines which candles are fetched and the % Change column.")
    st.checkbox("Sort descending (largest first)", value=st.session_state.get("sort_desc", True), key="sort_desc",
                help="Uncheck to see the laggards first.")
    st.slider("Minimum bars required (per pair)", 5, 200, int(st.session_state.get("min_bars", DEFAULTS["min_bars"])), 1, key="min_bars",
              help="Pairs with fewer candles than this on the chosen timeframe are skipped. Lower this on 1d to include newer listings.")

# ---------------- GATES
with expander("Gates"):
    with st.expander("Quick start tips", expanded=False):
        st.markdown(
            "- **Spike Hunter**: find movers fast. Use with Hard filter OFF.\n"
            "- **Early MACD Cross**: catch MACD crosses **below zero** in last few bars, plus Δ and Volume.\n"
            "- **Confirm Rally**: keep only strong breakouts. Use with Hard filter ON.\n"
            "- **Gate Mode**: ANY shows if **any** gate passes; ALL requires every enabled gate; Custom uses K/Y thresholds."
        )

    st.radio("Preset", ["Spike Hunter","Early MACD Cross","Confirm Rally","None"],
             index=["Spike Hunter","Early MACD Cross","Confirm Rally","None"].index(st.session_state.get("preset","Spike Hunter")),
             horizontal=True, key="preset")

    if st.session_state["preset"]=="Spike Hunter":
        st.session_state.update({
            "gate_mode":"ANY", "hard_filter": False,
            "lookback_candles": max(1,int(st.session_state.get("lookback_candles",3))),
            "min_pct": 3.0,
            "use_vol_spike": True, "vol_mult": 1.10,
            "use_rsi": False, "use_macd": False, "use_trend": False, "use_roc": False,
            "use_macd_cross": False
        })
    elif st.session_state["preset"]=="Early MACD Cross":
        st.session_state.update({
            "gate_mode":"ANY", "hard_filter": False,
            "lookback_candles": 3, "min_pct": 3.0,
            "use_vol_spike": True, "vol_mult": 1.10,
            "use_rsi": True, "min_rsi": 50,
            "use_macd": False,
            "use_trend": False, "use_roc": False,
            "use_macd_cross": True, "macd_cross_bars": 5,
            "macd_cross_only_bull": True, "macd_cross_below_zero": True, "macd_hist_confirm_bars": 3
        })
    elif st.session_state["preset"]=="Confirm Rally":
        st.session_state.update({
            "gate_mode":"Custom (K/Y)", "hard_filter": True,
            "lookback_candles": 2, "min_pct": 5.0,
            "use_vol_spike": True, "vol_mult": 1.20,
            "use_rsi": True, "min_rsi": 60,
            "use_macd": True, "min_mhist": 0.0,
            "use_trend": True, "pivot_span": 4, "trend_within": 48,
            "use_roc": False, "use_macd_cross": False, "K_green": 3, "Y_yellow": 2
        })

    st.radio("Gate Mode", ["ALL","ANY","Custom (K/Y)"],
             index=["ALL","ANY","Custom (K/Y)"].index(st.session_state.get("gate_mode","ANY")),
             horizontal=True, key="gate_mode",
             help="How strict to be when deciding if a row 'passes'.")

    st.toggle("Hard filter (hide non-passers)", key="hard_filter",
              value=st.session_state.get("hard_filter", False),
              help="Off = show all rows but highlight passers; On = hide rows that fail the chosen rule.")

    # Δ & Volume
    st.slider("Δ lookback (candles)", 0, 100, int(st.session_state.get("lookback_candles", DEFAULTS["lookback_candles"])), 1, key="lookback_candles",
              help="Bars back for % change; 0 is treated as 1.")
    st.slider("Min +% change (Δ gate)", 0.0, 50.0, float(st.session_state.get("min_pct", DEFAULTS["min_pct"])), 0.5, key="min_pct",
              help="Lower to see more candidates; raise to see only fast movers.")
    c1,c2,c3 = st.columns(3)
    with c1:
        st.toggle("Volume spike ×", key="use_vol_spike", value=st.session_state.get("use_vol_spike", True),
                  help="Require last candle's volume above its recent average.")
        st.slider("Spike multiple ×", 1.0, 5.0, float(st.session_state.get("vol_mult", DEFAULTS["vol_mult"])), 0.05, key="vol_mult",
                  help="1.10 means 10% above average.")
    with c2:
        st.toggle("RSI", key="use_rsi", value=st.session_state.get("use_rsi", False),
                  help="Strength filter. Use ~50 for 'rising', 60+ for stronger trend.")
        st.slider("Min RSI", 40, 90, int(st.session_state.get("min_rsi", DEFAULTS["min_rsi"])), 1, key="min_rsi")
    with c3:
        st.toggle("MACD hist", key="use_macd", value=st.session_state.get("use_macd", False),
                  help="Late confirmation; often after price already moved.")
        st.slider("Min MACD hist", 0.0, 2.0, float(st.session_state.get("min_mhist", DEFAULTS["min_mhist"])), 0.05, key="min_mhist")

    c4,c5,c6 = st.columns(3)
    with c4:
        st.toggle("ATR %", key="use_atr", value=st.session_state.get("use_atr", False),
                  help="Volatility floor. ATR/Close × 100 must exceed this.")
        st.slider("Min ATR %", 0.0, 10.0, float(st.session_state.get("min_atr", DEFAULTS["min_atr"])), 0.1, key="min_atr")
    with c5:
        st.toggle("Trend breakout (up)", key="use_trend", value=st.session_state.get("use_trend", False),
                  help="Close > last pivot high within N bars.")
        st.slider("Pivot span (bars)", 2, 10, int(st.session_state.get("pivot_span", DEFAULTS["pivot_span"])), 1, key="pivot_span")
        st.slider("Breakout within (bars)", 5, 96, int(st.session_state.get("trend_within", DEFAULTS["trend_within"])), 1, key="trend_within")
    with c6:
        st.toggle("ROC (rate of change)", key="use_roc", value=st.session_state.get("use_roc", False),
                  help="Same window as Δ. Leave off if Δ is already on.")
        st.slider("Min ROC %", 0.0, 50.0, float(st.session_state.get("min_roc", DEFAULTS["min_roc"])), 0.5, key="min_roc")

    st.markdown("**MACD Cross (early entry)**")
    c7,c8,c9,c10 = st.columns([1,1,1,1])
    with c7:
        st.toggle("Enable MACD Cross", key="use_macd_cross", value=st.session_state.get("use_macd_cross", True),
                  help="Detect MACD line crossing signal line recently.")
    with c8:
        st.slider("Cross within last (bars)", 1, 10, int(st.session_state.get("macd_cross_bars", DEFAULTS["macd_cross_bars"])), 1, key="macd_cross_bars",
                  help="Freshness of the cross.")
    with c9:
        st.toggle("Bullish only", key="macd_cross_only_bull", value=st.session_state.get("macd_cross_only_bull", True),
                  help="If off, accepts bearish crosses too.")
    with c10:
        st.toggle("Prefer below zero", key="macd_cross_below_zero", value=st.session_state.get("macd_cross_below_zero", True),
                  help="Consider only crosses when MACD & signal are below 0.")
    st.slider("Histogram > 0 within (bars)", 0, 10, int(st.session_state.get("macd_hist_confirm_bars", DEFAULTS["macd_hist_confirm_bars"])), 1, key="macd_hist_confirm_bars",
              help="0 disables. If >0, require MACD histogram turns positive within this many bars after the cross.")

    st.markdown("---")
    st.subheader("Color rules (Custom only)")
    st.selectbox("Gates needed to turn green (K)", list(range(1,8)),
                 index=int(st.session_state.get("K_green", DEFAULTS["K_green"]))-1, key="K_green")
    st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0, int(st.session_state.get("K_green", DEFAULTS["K_green"])))),
                 index=min(int(st.session_state.get("Y_yellow", DEFAULTS["Y_yellow"])),
                           int(st.session_state.get("K_green", DEFAULTS["K_green"]))-1), key="Y_yellow")

# ---------------- INDICATOR LENGTHS
with expander("Indicator lengths"):
    st.slider("RSI length", 5, 50, int(st.session_state.get("rsi_len", DEFAULTS["rsi_len"])), 1, key="rsi_len")
    st.slider("MACD fast EMA", 3, 50, int(st.session_state.get("macd_fast", DEFAULTS["macd_fast"])), 1, key="macd_fast")
    st.slider("MACD slow EMA", 5, 100, int(st.session_state.get("macd_slow", DEFAULTS["macd_slow"])), 1, key="macd_slow")
    st.slider("MACD signal", 3, 50, int(st.session_state.get("macd_sig", DEFAULTS["macd_sig"])), 1, key="macd_sig")
    st.slider("ATR length", 5, 50, int(st.session_state.get("atr_len", DEFAULTS["atr_len"])), 1, key="atr_len")

# ---------------- HISTORY DEPTH
with expander("History depth (for ATH/ATL)"):
    st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=["Hourly","Daily","Weekly"].index(st.session_state.get("basis","Daily")), key="basis")
    if st.session_state["basis"]=="Hourly":
        st.slider("Hours (≤72)", 1, 72, int(st.session_state.get("amount_hourly", DEFAULTS["amount_hourly"])), 1, key="amount_hourly")
    elif st.session_state["basis"]=="Daily":
        st.slider("Days (≤365)", 1, 365, int(st.session_state.get("amount_daily", DEFAULTS["amount_daily"])), 1, key="amount_daily")
    else:
        st.slider("Weeks (≤52)", 1, 52, int(st.session_state.get("amount_weekly", DEFAULTS["amount_weekly"])), 1, key="amount_weekly")

# ---------------- DISPLAY
with expander("Display"):
    st.slider("Font size (global)", 0.8, 1.6, float(st.session_state.get("font_scale", DEFAULTS["font_scale"])), 0.05, key="font_scale")

# ---------------- NOTIFICATIONS
with expander("Notifications"):
    st.text_input("Email recipient (optional)", st.session_state.get("email_to",""), key="email_to")
    st.text_input("Webhook URL (optional)", st.session_state.get("webhook_url",""), key="webhook_url")

# ---------------- LISTING RADAR (bottom)
with expander("Listing Radar"):
    # badge if unread
    if st.session_state.get("lr_unacked", 0) > 0:
        st.markdown('<span class="blink-badge">New/Upcoming listings</span>', unsafe_allow_html=True)

    st.toggle("Enable Listing Radar", key="lr_enabled",
              value=st.session_state.get("lr_enabled", False),
              help="Alert when new pairs go live or upcoming listings are announced.")
    cols = st.columns(2)
    with cols[0]:
        st.toggle("Watch Coinbase", key="lr_watch_coinbase", value=st.session_state.get("lr_watch_coinbase", True))
        st.toggle("Watch Binance", key="lr_watch_binance", value=st.session_state.get("lr_watch_binance", True))
        st.text_input("Quotes to watch (CSV)", st.session_state.get("lr_watch_quotes", DEFAULTS["lr_watch_quotes"]), key="lr_watch_quotes",
                      help="Only notify for pairs with these quotes, e.g., USD, USDT, USDC")
        st.slider("Poll interval (seconds)", 10, 120, int(st.session_state.get("lr_poll_sec", DEFAULTS["lr_poll_sec"])), 5, key="lr_poll_sec")
    with cols[1]:
        st.text_area("Announcement feeds (one or more URLs, comma-separated)",
                     st.session_state.get("lr_feeds", DEFAULTS["lr_feeds"]), key="lr_feeds",
                     help="RSS/announcement pages to scan for upcoming listings.")
        st.slider("Re-scan feeds every (seconds)", 60, 900, int(st.session_state.get("lr_upcoming_sec", DEFAULTS["lr_upcoming_sec"])), 30, key="lr_upcoming_sec")
        st.slider("Upcoming alert window (hours)", 6, 168, int(st.session_state.get("lr_upcoming_window_h", DEFAULTS["lr_upcoming_window_h"])), 6, key="lr_upcoming_window_h")
    st.toggle("Email on NEW listing", key="lr_alert_new", value=st.session_state.get("lr_alert_new", True))
    st.toggle("Email on UPCOMING listing", key="lr_alert_upcoming", value=st.session_state.get("lr_alert_upcoming", True))

    if st.button("Acknowledge all alerts"):
        st.session_state["lr_unacked"] = 0
        st.success("Alerts acknowledged.")

# persist to URL
sync_state_to_query_params()

# Header
st.markdown(f"<div style='font-size:1.3rem;font-weight:700;margin:4px 0 10px 2px;'>Timeframe: {st.session_state['sort_tf']}</div>", unsafe_allow_html=True)

# ---------------- Discovery list
if st.session_state["use_my_pairs"]:
    pairs=[p.strip().upper() for p in st.session_state.get("my_pairs","").split(",") if p.strip()]
else:
    if st.session_state["use_watch"] and st.session_state["watchlist"].strip():
        pairs=[p.strip().upper() for p in st.session_state["watchlist"].split(",") if p.strip()]
    else:
        pairs=list_products("Coinbase" if "coming soon" in st.session_state["exchange"] else st.session_state["exchange"], st.session_state["quote"])
        pairs=[p for p in pairs if p.endswith(f"-{st.session_state['quote']}")]
        cap=max(0, min(500, int(st.session_state.get("discover_cap", DEFAULTS["discover_cap"]))))
        pairs=pairs[:cap] if cap>0 else []

# WS boot
if pairs and st.session_state["mode"].startswith("WebSocket") and (st.session_state["exchange"]=="Coinbase" or "coming soon" in st.session_state["exchange"]) and WS_AVAILABLE:
    start_ws_if_needed("Coinbase", pairs, st.session_state.get("ws_chunk",5))

# ---------------- Build rows with diagnostics
diag_available = len(pairs)
diag_capped = len(pairs)
diag_fetched = 0
diag_skip_bars = 0
diag_skip_api = 0

rows=[]
for pid in pairs:
    dft = df_for_tf("Coinbase" if "coming soon" in st.session_state["exchange"] else st.session_state["exchange"], pid, st.session_state["sort_tf"])
    if dft is None:
        diag_skip_api += 1
        continue
    if len(dft) < int(st.session_state.get("min_bars", DEFAULTS["min_bars"])):
        diag_skip_bars += 1
        continue
    diag_fetched += 1
    dft = dft.tail(400).copy()

    last_price=float(dft["close"].iloc[-1])
    if st.session_state["exchange"]=="Coinbase" and st.session_state["ws_prices"].get(pid):
        last_price=float(st.session_state["ws_prices"][pid])

    # display-wide % change for context
    first_price=float(dft["close"].iloc[0])
    pct_display=(last_price/first_price - 1.0)*100.0

    # ATH/ATL
    basis=st.session_state["basis"]
    amt=dict(Hourly=st.session_state["amount_hourly"],
             Daily=st.session_state["amount_daily"],
             Weekly=st.session_state["amount_weekly"])[basis]
    histdf=get_hist("Coinbase" if "coming soon" in st.session_state["exchange"] else st.session_state["exchange"], pid, basis, amt)
    if histdf is None or len(histdf)<10:
        athp,athd,atlp,atld=np.nan,"—",np.nan,"—"
    else:
        aa=ath_atl_info(histdf); athp,athd,atlp,atld=aa["From ATH %"],aa["ATH date"],aa["From ATL %"],aa["ATL date"]

    meta, passed, chips, enabled_cnt = build_gate_eval(dft, dict(
        lookback_candles=int(st.session_state["lookback_candles"]), min_pct=float(st.session_state["min_pct"]),
        use_vol_spike=st.session_state["use_vol_spike"], vol_mult=float(st.session_state["vol_mult"]), vol_window=DEFAULTS["vol_window"],
        use_rsi=st.session_state["use_rsi"], rsi_len=int(st.session_state.get("rsi_len",14")), min_rsi=int(st.session_state["min_rsi"]),
        use_macd=st.session_state["use_macd"], macd_fast=int(st.session_state.get("macd_fast",12")), macd_slow=int(st.session_state.get("macd_slow",26")),
        macd_sig=int(st.session_state.get("macd_sig",9")), min_mhist=float(st.session_state["min_mhist"]),
        use_atr=st.session_state["use_atr"], atr_len=int(st.session_state.get("atr_len",14")), min_atr=float(st.session_state["min_atr"]),
        use_trend=st.session_state["use_trend"], pivot_span=int(st.session_state["pivot_span"]), trend_within=int(st.session_state["trend_within"]),
        use_roc=st.session_state["use_roc"], min_roc=float(st.session_state["min_roc"]),
        # macd cross
        use_macd_cross=st.session_state.get("use_macd_cross", True),
        macd_cross_bars=int(st.session_state.get("macd_cross_bars",5)),
        macd_cross_only_bull=st.session_state.get("macd_cross_only_bull", True),
        macd_cross_below_zero=st.session_state.get("macd_cross_below_zero", True),
        macd_hist_confirm_bars=int(st.session_state.get("macd_hist_confirm_bars",3)),
    ))

    mode=st.session_state.get("gate_mode","ANY")
    if mode=="ALL":
        include=(passed==enabled_cnt) and enabled_cnt>0
        is_green=include; is_yellow=(0<passed<enabled_cnt)
    elif mode=="ANY":
        include=(passed>=1)
        is_green=include; is_yellow=False
    else:  # Custom
        K=int(st.session_state["K_green"]); Y=int(st.session_state["Y_yellow"])
        include=True
        is_green=(passed>=K); is_yellow=(passed>=Y and passed<K)

    if st.session_state.get("hard_filter", False):
        if mode in {"ALL","ANY"} and not include: 
            continue
        if mode=="Custom (K/Y)" and not (is_green or is_yellow):
            continue

    rows.append({
        "Pair": pid, "Price": last_price,
        f"% Change ({st.session_state['sort_tf']})": pct_display,
        f"Δ% (last {max(1,int(st.session_state['lookback_candles']))} bars)": meta["delta_pct"],
        "From ATH %": athp, "ATH date": athd, "From ATL %": atlp, "ATL date": atld,
        "Gates": chips, "Strong Buy": "YES" if is_green else "—",
        "_green": is_green, "_yellow": is_yellow
    })

# ---------------- Tables + diagnostics
df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair"])
diag_shown = len(df)

st.caption(f"Diagnostics — Available: {diag_available} • Capped: {diag_capped} • Fetched OK: {diag_fetched} • "
           f"Skipped (bars): {diag_skip_bars} • Skipped (API): {diag_skip_api} • Shown: {diag_shown}")

if df.empty:
    st.info("No rows to show. Try ANY mode, lower Min Δ, shorter lookback, reduce Minimum bars, enable Volume spike/MACD Cross, or increase discovery cap.")
else:
    chg_col=f"% Change ({st.session_state['sort_tf']})"
    df=df.sort_values(chg_col, ascending=not st.session_state["sort_desc"], na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index+1)

    st.subheader("📌 Top-10 (greens only)")
    top10=df[df["_green"]].sort_values(chg_col, ascending=False, na_position="last").head(10).drop(columns=["_green","_yellow"])
    if top10.empty:
        st.write("—")
    else:
        st.data_editor(top10, use_container_width=True, hide_index=True, disabled=True)

    st.subheader("📑 All pairs")
    show_df=df.drop(columns=["_green","_yellow"])
    st.data_editor(show_df, use_container_width=True, hide_index=True, disabled=True)

    st.caption(
        f"Pairs shown: {len(df)} • Exchange: {st.session_state['exchange']} • Quote: {st.session_state['quote']} "
        f"• TF: {st.session_state['sort_tf']} • Gate Mode: {st.session_state['gate_mode']} • Hard filter: {'On' if st.session_state['hard_filter'] else 'Off'}"
    )

# ---------------- Listing Radar engine
def lr_parse_quotes(csv_text: str) -> set:
    return set(x.strip().upper() for x in (csv_text or "").split(",") if x.strip())

def lr_fetch_symbols(exchange: str, quotes: set) -> set:
    try:
        if exchange=="Coinbase":
            r=requests.get(f"{CB_BASE}/products", timeout=25); r.raise_for_status()
            return set(f"{p['base_currency']}-{p['quote_currency']}" for p in r.json() if p.get("quote_currency") in quotes)
        elif exchange=="Binance":
            r=requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25); r.raise_for_status()
            out=set()
            for s in r.json().get("symbols",[]):
                if s.get("status")!="TRADING": continue
                q=s.get("quoteAsset","")
                if q in quotes:
                    out.add(f"{s['baseAsset']}-{q}")
            return out
    except Exception:
        return set()
    return set()

def lr_note_event(kind:str, exchange:str, pair:str, when:Optional[str], link:str):
    ev_id = f"{kind}|{exchange}|{pair}|{when or ''}"
    existing = {e.get("id") for e in st.session_state["lr_events"]}
    if ev_id in existing: return False
    st.session_state["lr_events"].insert(0, {"id": ev_id, "kind": kind, "exchange": exchange, "pair": pair, "when": when, "link": link, "ts": dt.datetime.utcnow().isoformat()+"Z"})
    st.session_state["lr_unacked"] += 1
    # alerts
    subject = f"[Listing Radar] {kind}: {exchange} {pair}" + (f" at {when}" if when else "")
    body = f"{kind} detected\nExchange: {exchange}\nPair: {pair}\nWhen: {when or 'unknown'}\nLink: {link or 'n/a'}"
    if st.session_state.get("email_to"):
        if (kind=="NEW" and st.session_state.get("lr_alert_new")) or (kind=="UPCOMING" and st.session_state.get("lr_alert_upcoming")):
            send_email_alert(subject, body, st.session_state["email_to"])
    if st.session_state.get("webhook_url"):
        post_webhook(st.session_state["webhook_url"], {"title": subject, "details": body})
    return True

def lr_scan_new_listings():
    if not st.session_state.get("lr_enabled"): return
    quotes = lr_parse_quotes(st.session_state.get("lr_watch_quotes", DEFAULTS["lr_watch_quotes"]))
    now = time.time()
    if now - st.session_state.get("lr_last_poll", 0) < int(st.session_state.get("lr_poll_sec", DEFAULTS["lr_poll_sec"])): return
    st.session_state["lr_last_poll"] = now

    for exch, enabled in [("Coinbase", st.session_state.get("lr_watch_coinbase", True)),
                          ("Binance", st.session_state.get("lr_watch_binance", True))]:
        if not enabled: continue
        current = lr_fetch_symbols(exch, quotes)
        base = st.session_state["lr_baseline"].get(exch, set())
        if not base:
            # first run: initialize baseline so we don't spam with every symbol
            st.session_state["lr_baseline"][exch] = current
            continue
        new_syms = sorted(list(current - base))
        if new_syms:
            for sy in new_syms:
                lr_note_event("NEW", exch, sy, None, "")
        # update baseline
        st.session_state["lr_baseline"][exch] = current

def lr_parse_feed_items(text:str) -> List[Tuple[str,str]]:
    # Extremely simple RSS-ish parser: extract titles and dates if present
    items=[]
    # titles
    for m in re.finditer(r"<title>(.*?)</title>", text, re.I|re.S):
        title = re.sub(r"\s+", " ", m.group(1)).strip()
        items.append(("title", title))
    # pubDate
    dates = re.findall(r"<pubDate>(.*?)</pubDate>", text, re.I|re.S)
    # Pair items with dates if lengths match; otherwise keep titles only
    return items, dates

def lr_extract_upcoming_from_text(txt:str) -> List[Tuple[str, Optional[str]]]:
    # Heuristics: look for "list(s|ing|ed)" and phrases like "trading starts", capture dates if present
    out=[]
    lines = re.split(r"[\r\n]+", txt)
    for ln in lines:
        low = ln.lower()
        if any(k in low for k in ["list", "listing", "will list", "trading opens", "trading will open", "launches", "goes live"]):
            # try to extract a date-ish substring
            m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?)?)", ln)
            when = m.group(1) if m else None
            out.append((ln.strip(), when))
    return out

def lr_scan_upcoming():
    if not st.session_state.get("lr_enabled"): return
    now = time.time()
    if now - st.session_state.get("lr_last_upcoming_poll", 0) < int(st.session_state.get("lr_upcoming_sec", DEFAULTS["lr_upcoming_sec"])): return
    st.session_state["lr_last_upcoming_poll"] = now

    feeds = [u.strip() for u in st.session_state.get("lr_feeds", "").split(",") if u.strip()]
    for url in feeds:
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200: continue
            txt = r.text
            # very light parsing
            items, _ = lr_parse_feed_items(txt)
            # fallback: just scan whole text
            found = lr_extract_upcoming_from_text(txt)
            horizon_h = int(st.session_state.get("lr_upcoming_window_h", DEFAULTS["lr_upcoming_window_h"]))
            horizon = dt.datetime.utcnow() + dt.timedelta(hours=horizon_h)
            for snippet, when in found:
                # Try to pull a symbol-like token (e.g., ABC/USDT, ABC-USD, ABC)
                sym_m = re.search(r"([A-Z0-9]{2,10})[-/ ](USD|USDC|USDT|BTC|ETH|EUR)\b", snippet)
                pair = sym_m.group(0).replace(" ", "-").replace("/", "-") if sym_m else "UNKNOWN"
                when_iso = None
                if when:
                    try:
                        # Try a few naive parses
                        dt_guess = pd.to_datetime(when, utc=True)
                        if dt_guess.tzinfo is None:
                            dt_guess = dt_guess.tz_localize("UTC")
                        if dt_guess.to_pydatetime(tzinfo=None) <= horizon:
                            when_iso = dt_guess.isoformat()
                    except Exception:
                        when_iso = None
                lr_note_event("UPCOMING", "Unknown", pair, when_iso, url)
        except Exception:
            continue

# Kick the radar every render (rate limited by its own timers)
lr_scan_new_listings()
lr_scan_upcoming()

# Show Listing Radar events on main (so it’s visible even if sidebar is closed)
if st.session_state.get("lr_enabled"):
    st.subheader("🛰️ Listing Radar events")
    if not st.session_state["lr_events"]:
        st.caption("No events yet.")
    else:
        evdf = pd.DataFrame(st.session_state["lr_events"])
        cols = ["ts","kind","exchange","pair","when","link"]
        evdf = evdf.reindex(columns=cols)
        st.data_editor(evdf, use_container_width=True, hide_index=True, disabled=True)

# ---------------- Auto-refresh
remaining = st.session_state["refresh_sec"] - (time.time() - st.session_state.get("last_refresh", time.time()))
if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {int(st.session_state['refresh_sec'])}s (next in {int(remaining)}s)")

