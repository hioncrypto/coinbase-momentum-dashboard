# app.py — Crypto Tracker by hioncrypto (Presets persisted to disk)
# - Gate Presets now persist across sessions at /mnt/data/gate_presets.json
# - Everything else from the previous working build is retained.

import os, json, time, datetime as dt, threading, queue, ssl, smtplib
from typing import List, Optional, Tuple, Dict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ----------------------------- Optional WebSocket
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

# ----------------------------- Constants
TITLE = "Crypto Tracker by hioncrypto"
PRESETS_PATH = "/mnt/data/gate_presets.json"

TF_LIST = ["15m","1h","4h","6h","12h","1d"]
TF_SEC  = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}

QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

# ----------------------------- Disk persistence for presets
def load_presets_from_disk() -> Dict[str, dict]:
    try:
        if os.path.exists(PRESETS_PATH):
            with open(PRESETS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}

def save_presets_to_disk(presets: Dict[str, dict]):
    try:
        os.makedirs(os.path.dirname(PRESETS_PATH), exist_ok=True)
        with open(PRESETS_PATH, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2)
    except Exception as e:
        st.sidebar.warning(f"Could not save presets: {e}")

# ----------------------------- Session state
def _init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("collapse_all_now", False)
    ss.setdefault("last_refresh", time.time())
    ss.setdefault("my_pairs", set())

    # Load presets from disk (once)
    if "gate_presets" not in ss:
        disk = load_presets_from_disk()
        ss["gate_presets"] = disk if disk else {}

    # Seed default preset if missing
    if "hioncrypto (starter)" not in ss["gate_presets"]:
        ss["gate_presets"]["hioncrypto (starter)"] = {
            "min_pct": 20.0,
            "use_vol_spike": True,  "vol_mult": 1.10,
            "use_rsi": False,       "min_rsi": 55,
            "use_macd": True,       "min_mhist": 0.0,
            "use_atr": False,       "min_atr": 0.5,
            "use_trend": True,      "pivot_span": 4, "trend_within": 48,
            "gates_needed_green": 3,
            "yellow_min": 1,
            "rsi_len": 14, "macd_fast": 12, "macd_slow": 26, "macd_sig": 9,
            "atr_len": 14, "vol_window": 20,
        }
        save_presets_to_disk(ss["gate_presets"])

    ss.setdefault("selected_preset", "hioncrypto (starter)")
_init_state()

# ----------------------------- Indicators / helpers
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
    h, l, c = df["high"], df["low"], df["close"]
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
    cross = None
    for j in range(hi+1, len(df)):
        if float(df["close"].iloc[j]) > level:
            cross = j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# ----------------------------- Discovery
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

# ----------------------------- OHLCV fetch
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

# ----------------------------- History for ATH/ATL
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

def start_ws_if_needed(exchange: str, pairs: List[str], chunk: int):
    if exchange!="Coinbase" or not WS_AVAILABLE: return
    if not st.session_state["ws_alive"]:
        pick = pairs[:max(2, min(chunk, len(pairs)))]
        t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start(); time.sleep(0.2)

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

# ----------------------------- Gates / Masks
def build_gate_masks(df_tf: pd.DataFrame, settings: dict) -> Tuple[dict, int]:
    last_close = float(df_tf["close"].iloc[-1])
    first_close = float(df_tf["close"].iloc[0])
    pct_up = (last_close/first_close - 1.0) * 100.0

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

    checks = []
    checks.append(("Δ", pct_up >= settings["min_pct"]))
    if settings["use_vol_spike"]:
        checks.append(("V", (volx >= settings["vol_mult"])))
    if settings["use_rsi"]:
        checks.append(("S", (float(rsi_ser.iloc[-1]) >= settings["min_rsi"])))
    if settings["use_macd"]:
        checks.append(("M", (float(mh_ser.iloc[-1]) >= settings["min_mhist"])))
    if settings["use_atr"]:
        checks.append(("A", (float(atr_ser.iloc[-1]) >= settings["min_atr"])))
    if settings["use_trend"]:
        checks.append(("T", bool(tr_up)))

    passed = sum(1 for _, ok in checks if ok)
    return {
        "pct_value": pct_up,
        "chips": "".join([f"{name}✅ " if ok else f"{name}❌ " for name, ok in checks]).strip(),
        "passed": passed
    }, passed

# ----------------------------- UI
st.set_page_config(page_title=TITLE, layout="wide")
st.title(TITLE)

# Collapse all
c1, c2 = st.sidebar.columns([1,1])
with c1:
    if st.button("Collapse all menu tabs", use_container_width=True):
        st.session_state["collapse_all_now"] = True
with c2:
    use_my_pairs = st.toggle("⭐ Use My Pairs only", value=False)

def expander(title: str, key: str):
    opened = not st.session_state.get("collapse_all_now", False)
    exp = st.sidebar.expander(title, expanded=opened)
    return exp

# My Pairs manager
with st.sidebar.expander("Manage My Pairs"):
    st.caption("Add/remove comma‑separated pairs (e.g., BTC-USD, ETH-USD).")
    mp_text = st.text_area("My Pairs", ", ".join(sorted(st.session_state["my_pairs"])))
    if st.button("Save My Pairs"):
        st.session_state["my_pairs"] = set([p.strip().upper() for p in mp_text.split(",") if p.strip()])

# Market
with expander("Market","exp_market"):
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    effective_exchange = exchange if "coming soon" not in exchange else "Coinbase"
    if "coming soon" in exchange:
        st.info("This exchange is coming soon. Using Coinbase for data.")
    quote = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    watchlist = st.text_area("Watchlist (comma-separated)",
                             "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")
    st.markdown("---")
    all_pairs_switch = st.checkbox("Evaluate **all** discovered pairs", value=True)
    max_pairs = st.slider("Max pairs to evaluate (if not 'All')", 10, 1000, 200, 10)

# Mode
with expander("Mode","exp_mode"):
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0, horizontal=True)
    ws_chunk = st.slider("WS subscribe chunk (Coinbase)", 2, 50, 10, 1)

# Timeframes
with expander("Timeframes","exp_tfs"):
    pick_tfs = st.multiselect("Available timeframes", TF_LIST, default=TF_LIST)
    sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=1)
    sort_desc = st.checkbox("Sort descending (largest first)", value=True)

# ----------------------------- Gates (persisted presets)
with expander("Gates","exp_gates"):

    # main gate widgets (use stable keys)
    st.number_input("Min +% change (Sort TF)", key="g_min_pct", min_value=0.0, max_value=100.0, value=20.0, step=0.5)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.toggle("Use Volume spike×", key="g_use_vol_spike", value=True)
        st.number_input("Spike multiple ×", key="g_vol_mult", min_value=1.0, max_value=8.0, value=1.10, step=0.05)
    with c2:
        st.toggle("Use RSI", key="g_use_rsi", value=False)
        st.slider("Min RSI", key="g_min_rsi", min_value=40, max_value=90, value=55, step=1)
        st.toggle("Use MACD hist", key="g_use_macd", value=True)
        st.number_input("Min MACD hist", key="g_min_mhist", min_value=0.0, max_value=2.0, value=0.0, step=0.05)
    with c3:
        st.toggle("Use ATR %", key="g_use_atr", value=False, help="ATR/close × 100")
        st.number_input("Min ATR %", key="g_min_atr", min_value=0.0, max_value=10.0, value=0.5, step=0.1)
        st.toggle("Use Trend breakout (up)", key="g_use_trend", value=True)
        st.slider("Pivot span (bars)", key="g_pivot_span", min_value=2, max_value=10, value=4, step=1)
        st.slider("Breakout within (bars)", key="g_trend_within", min_value=5, max_value=96, value=48, step=1)

    st.markdown("---")
    st.markdown("**Color rules (beginner‑friendly)**")
    colg, coly = st.columns(2)
    with colg:
        st.selectbox("Gates needed to turn **green (K)**", key="g_k_green",
                     options=[1,2,3,4,5,6], index=2)
    with coly:
        st.selectbox("Yellow needs **≥ Y** (but < K)", key="g_yellow_min",
                     options=[0,1,2,3,4,5], index=1)
        if st.session_state["g_yellow_min"] >= st.session_state["g_k_green"]:
            st.warning("Yellow must be less than K (green). Lower Y or increase K.")

    st.markdown("---")
    st.markdown("### Presets (persisted)")
    st.caption(f"Stored at: `{PRESETS_PATH}`")

    def collect_gate_settings() -> Dict:
        return {
            "min_pct": float(st.session_state["g_min_pct"]),
            "use_vol_spike": bool(st.session_state["g_use_vol_spike"]),
            "vol_mult": float(st.session_state["g_vol_mult"]),
            "use_rsi": bool(st.session_state["g_use_rsi"]),
            "min_rsi": int(st.session_state["g_min_rsi"]),
            "use_macd": bool(st.session_state["g_use_macd"]),
            "min_mhist": float(st.session_state["g_min_mhist"]),
            "use_atr": bool(st.session_state["g_use_atr"]),
            "min_atr": float(st.session_state["g_min_atr"]),
            "use_trend": bool(st.session_state["g_use_trend"]),
            "pivot_span": int(st.session_state["g_pivot_span"]),
            "trend_within": int(st.session_state["g_trend_within"]),
            "gates_needed_green": int(st.session_state["g_k_green"]),
            "yellow_min": int(st.session_state["g_yellow_min"]),
            # lengths
            "rsi_len": st.session_state.get("len_rsi", 14),
            "macd_fast": st.session_state.get("len_macd_fast", 12),
            "macd_slow": st.session_state.get("len_macd_slow", 26),
            "macd_sig": st.session_state.get("len_macd_sig", 9),
            "atr_len": st.session_state.get("len_atr", 14),
            "vol_window": st.session_state.get("len_vol_window", 20),
        }

    def apply_gate_settings(s: Dict):
        st.session_state["g_min_pct"] = float(s.get("min_pct", 20.0))
        st.session_state["g_use_vol_spike"] = bool(s.get("use_vol_spike", True))
        st.session_state["g_vol_mult"] = float(s.get("vol_mult", 1.10))
        st.session_state["g_use_rsi"] = bool(s.get("use_rsi", False))
        st.session_state["g_min_rsi"] = int(s.get("min_rsi", 55))
        st.session_state["g_use_macd"] = bool(s.get("use_macd", True))
        st.session_state["g_min_mhist"] = float(s.get("min_mhist", 0.0))
        st.session_state["g_use_atr"] = bool(s.get("use_atr", False))
        st.session_state["g_min_atr"] = float(s.get("min_atr", 0.5))
        st.session_state["g_use_trend"] = bool(s.get("use_trend", True))
        st.session_state["g_pivot_span"] = int(s.get("pivot_span", 4))
        st.session_state["g_trend_within"] = int(s.get("trend_within", 48))
        st.session_state["g_k_green"] = int(s.get("gates_needed_green", 3))
        st.session_state["g_yellow_min"] = int(s.get("yellow_min", 1))
        # lengths
        st.session_state["len_rsi"] = int(s.get("rsi_len", 14))
        st.session_state["len_macd_fast"] = int(s.get("macd_fast", 12))
        st.session_state["len_macd_slow"] = int(s.get("macd_slow", 26))
        st.session_state["len_macd_sig"] = int(s.get("macd_sig", 9))
        st.session_state["len_atr"] = int(s.get("atr_len", 14))
        st.session_state["len_vol_window"] = int(s.get("vol_window", 20))

    # Selector & actions
    preset_names = sorted(st.session_state["gate_presets"].keys())
    st.session_state["selected_preset"] = st.selectbox(
        "Select preset",
        options=preset_names,
        index=preset_names.index(st.session_state["selected_preset"]) if st.session_state["selected_preset"] in preset_names else 0
    )

    cpa, cpb, cpc, cpd = st.columns([1,1,1,2])
    with cpa:
        if st.button("Apply preset"):
            apply_gate_settings(st.session_state["gate_presets"][st.session_state["selected_preset"]])
            st.rerun()
    with cpb:
        new_name = st.text_input("Save as (new name)", "", placeholder="e.g., My Aggressive v1")
        if st.button("Save as new") and new_name.strip():
            st.session_state["gate_presets"][new_name.strip()] = collect_gate_settings()
            save_presets_to_disk(st.session_state["gate_presets"])
            st.session_state["selected_preset"] = new_name.strip()
            st.rerun()
    with cpc:
        if st.button("Update selected"):
            st.session_state["gate_presets"][st.session_state["selected_preset"]] = collect_gate_settings()
            save_presets_to_disk(st.session_state["gate_presets"])
            st.success("Preset updated.")
    with cpd:
        if st.button("Delete selected"):
            name = st.session_state["selected_preset"]
            if name == "hioncrypto (starter)":
                st.warning("Default preset cannot be deleted.")
            else:
                st.session_state["gate_presets"].pop(name, None)
                save_presets_to_disk(st.session_state["gate_presets"])
                st.session_state["selected_preset"] = "hioncrypto (starter)"
                st.rerun()

# Indicator lengths (keys so presets can include them)
with expander("Indicator lengths","exp_lens"):
    st.slider("RSI length", key="len_rsi", min_value=5, max_value=50, value=14, step=1)
    st.slider("MACD fast EMA", key="len_macd_fast", min_value=3, max_value=50, value=12, step=1)
    st.slider("MACD slow EMA", key="len_macd_slow", min_value=5, max_value=100, value=26, step=1)
    st.slider("MACD signal", key="len_macd_sig", min_value=3, max_value=50, value=9, step=1)
    st.slider("ATR length", key="len_atr", min_value=5, max_value=50, value=14, step=1)
    st.slider("Volume SMA window", key="len_vol_window", min_value=5, max_value=50, value=20, step=1)

# History for ATH/ATL
with expander("History depth (for ATH/ATL)","exp_hist"):
    basis = st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=1)
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1)
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 90, 1)
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 12, 1)

# Display
with expander("Display","exp_disp"):
    font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05)

# Notifications
with expander("Notifications","exp_notif"):
    send_alerts = st.checkbox("Send Email/Webhook alerts this session", value=False)
    email_to = st.text_input("Email recipient (optional)", "")
    webhook_url = st.text_input("Webhook URL (optional)", "")

# Auto‑refresh
with expander("Auto-refresh","exp_auto"):
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 30, 1)
    st.caption("Auto-refresh is always on.")
st.session_state["collapse_all_now"] = False

# Global style
st.markdown(f"""
<style>
  html, body {{ font-size: {font_scale}rem; }}
  .row-green  {{ background: rgba(0,255,0,0.22) !important; font-weight: 600; }}
  .row-yellow {{ background: rgba(255,255,0,0.60) !important; font-weight: 600; }}
</style>
""", unsafe_allow_html=True)

# Timeframe headline
st.markdown(f"### Timeframe: **{sort_tf}**")
st.caption("Legend: Δ %Change • V Volume× • S RSI • M MACD • A ATR • T Trend")

# ----------------------------- Build universe
if use_watch and watchlist.strip():
    pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs = list_products(effective_exchange, quote)
pairs = [p for p in pairs if p.endswith(f"-{quote}")]
if use_my_pairs and st.session_state["my_pairs"]:
    pairs = [p for p in pairs if p in st.session_state["my_pairs"]]
if not all_pairs_switch:
    pairs = pairs[:max_pairs]

# Start WS if requested
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

    hist = get_hist(effective_exchange, pid, basis, amount)
    if hist is None or len(hist)<10:
        athp, athd, atlp, atld = np.nan, "—", np.nan, "—"
    else:
        aa = ath_atl_info(hist)
        athp, athd, atlp, atld = aa["From ATH %"], aa["ATH date"], aa["From ATL %"], aa["ATL date"]

    settings_pack = {
        "min_pct": float(st.session_state["g_min_pct"]),
        "use_vol_spike": bool(st.session_state["g_use_vol_spike"]),
        "vol_window": int(st.session_state["len_vol_window"]),
        "vol_mult": float(st.session_state["g_vol_mult"]),
        "use_rsi": bool(st.session_state["g_use_rsi"]),
        "min_rsi": int(st.session_state["g_min_rsi"]),
        "rsi_len": int(st.session_state["len_rsi"]),
        "use_macd": bool(st.session_state["g_use_macd"]),
        "min_mhist": float(st.session_state["g_min_mhist"]),
        "macd_fast": int(st.session_state["len_macd_fast"]),
        "macd_slow": int(st.session_state["len_macd_slow"]),
        "macd_sig": int(st.session_state["len_macd_sig"]),
        "use_atr": bool(st.session_state["g_use_atr"]),
        "min_atr": float(st.session_state["g_min_atr"]),
        "atr_len": int(st.session_state["len_atr"]),
        "use_trend": bool(st.session_state["g_use_trend"]),
        "pivot_span": int(st.session_state["g_pivot_span"]),
        "trend_within": int(st.session_state["g_trend_within"]),
    }
    gate_info, passed = build_gate_masks(dft, settings_pack)

    K = int(st.session_state["g_k_green"])
    Y = int(st.session_state["g_yellow_min"])
    strong = "YES" if (passed >= K) and (pct > 0) else "—"

    rows.append({
        "Pair": pid,
        "Price": last_price,
        f"% Change ({sort_tf})": pct,
        "From ATH %": athp, "ATH date": athd,
        "From ATL %": atlp, "ATL date": atld,
        "Gates": gate_info["chips"],
        "Passed": passed,
        "Strong Buy": strong,
    })

df = pd.DataFrame(rows)

# ----------------------------- Render tables
if df.empty:
    st.info("No rows to show. Loosen gates or choose a different timeframe.")
else:
    chg_col = f"% Change ({sort_tf})"
    df = df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index+1)

    K = int(st.session_state["g_k_green"])
    Y = int(st.session_state["g_yellow_min"])

    def colorize(x: pd.DataFrame):
        styles = pd.DataFrame("", index=x.index, columns=x.columns)
        gm = (x["Strong Buy"] == "YES")
        ym = (x["Strong Buy"] != "YES") & (x["Passed"] >= Y) & (x["Passed"] < K)
        styles.loc[gm, :] = "background-color: rgba(0,255,0,0.22); font-weight: 600;"
        styles.loc[ym, :] = "background-color: rgba(255,255,0,0.60); font-weight: 600;"
        return styles

    st.subheader("📌 Top‑10 (meets green rule)")
    top10 = df[df["Strong Buy"].eq("YES")] \
              .sort_values(chg_col, ascending=False, na_position="last") \
              .head(10) \
              .reset_index(drop=True)
    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, loosen gates (e.g., lower Min +% change).")
    else:
        st.dataframe(top10.style.apply(colorize, axis=None), use_container_width=True)

    st.subheader("📑 All pairs")
    st.dataframe(df.style.apply(colorize, axis=None), use_container_width=True)

    # Alerts on Top‑10 entrants
    new_msgs=[]
    for _, r in top10.iterrows():
        key = f"{r['Pair']}|{sort_tf}|{round(float(r[chg_col]),2)}"
        if key not in st.session_state["alert_seen"]:
            st.session_state["alert_seen"].add(key)
            new_msgs.append(f"{r['Pair']}: {float(r[chg_col]):+.2f}% ({sort_tf})")
    if new_msgs and st.sidebar.checkbox("Send Email/Webhook alerts this session", value=False, key="alerts_toggle"):
        email_rec = st.sidebar.text_input("Email recipient (optional)", key="alerts_email")
        hook_url  = st.sidebar.text_input("Webhook URL (optional)", key="alerts_hook")
        subject = f"[{effective_exchange}] Top‑10 Crypto Tracker"
        body    = "\n".join(new_msgs)
        if email_rec:
            ok, info = send_email_alert(subject, body, email_rec)
            if not ok: st.sidebar.warning(info)
        if hook_url:
            ok, info = post_webhook(hook_url, {"title": subject, "lines": new_msgs})
            if not ok: st.sidebar.warning(f"Webhook error: {info}")

    st.caption(
        f"Pairs: {len(df)} • Exchange: {effective_exchange} • Quote: {quote} "
        f"• Sort TF: {sort_tf} • Mode: {'WS+REST' if (mode.startswith('WebSocket') and effective_exchange=='Coinbase' and WS_AVAILABLE) else 'REST only'}"
    )

# ----------------------------- Auto‑refresh
remaining = refresh_sec - (time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {refresh_sec}s (next in {int(remaining)}s)")

