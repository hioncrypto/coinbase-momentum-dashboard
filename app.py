# app.py — Crypto Tracker by hioncrypto
# - Top‑10 shows ONLY green rows (meets "K gates" rule), sorted by % Change (desc)
# - All pairs sorted by % Change (desc) too; green/yellow are just colors
# - Gates chips use simple ✅/❌/– text (reliable)
# - Collapse‑all only acts when clicked, then immediately resets; expanders start collapsed
# - K/Y controls are dropdowns inside "Gates"
# - "⭐ Use My Pairs only" lives at the very top of the sidebar (outside expanders)
# - Auto‑refresh via st.rerun() timer
# - Alerts (email/webhook) fire on new Top‑10 entrants
# - Defaults are semi‑restrictive; “Reset gates to defaults” button added

import json, time, datetime as dt, threading, queue, ssl, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Tuple

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
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
ALL_TFS = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}

QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

DEFAULTS = dict(
    sort_tf = "1h",
    sort_desc = True,
    min_pct = 20.0,         # positive-only gate threshold (Sort TF)
    use_vol_spike = True,   vol_mult = 1.10, vol_window = 20,
    use_rsi = False,        rsi_len = 14,    min_rsi = 55,
    use_macd = True,        macd_fast = 12,  macd_slow = 26, macd_sig = 9, min_mhist = 0.0,
    use_atr = False,        atr_len = 14,    min_atr = 0.5,
    use_trend = True,       pivot_span = 4,  trend_within = 48,
    K_green = 3,            Y_yellow = 2,
    basis = "Daily",        amount_daily = 90, amount_hourly = 24, amount_weekly = 12,
    refresh_sec = 30,       max_pairs = 25,
    quote = "USD",          exchange = "Coinbase",
    watchlist = "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD",
)

# ----------------------------- Session state
def _init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("collapse_all_now", False)      # one-shot flag
    ss.setdefault("last_refresh", time.time())
    ss.setdefault("use_my_pairs", False)
    ss.setdefault("my_pairs", ["BTC-USD","ETH-USD","SOL-USD"])
_init_state()

# ----------------------------- Small utilities
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

# ----------------------------- HTTP / WS
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
    idx_ath=int(hist["high"].idxmax()); idx_atl=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[idx_ath]); d_ath=pd.to_datetime(hist["ts"].iloc[idx_ath]).date().isoformat()
    atl=float(hist["low"].iloc[idx_atl]);  d_atl=pd.to_datetime(hist["ts"].iloc[idx_atl]).date().isoformat()
    return {"From ATH %": (last/ath-1)*100 if ath>0 else np.nan, "ATH date": d_ath,
            "From ATL %": (last/atl-1)*100 if atl>0 else np.nan, "ATL date": d_atl}

# ----------------------------- WebSocket worker
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

# ----------------------------- Gates
def build_gate_eval(df_tf: pd.DataFrame, settings: dict) -> Tuple[dict, int, str]:
    """Return per-gate booleans at the last bar, gates_passed count, and chips string."""
    last_close = df_tf["close"].iloc[-1]
    first_close = df_tf["close"].iloc[0]
    pct = (last_close/first_close - 1.0) * 100.0
    g_delta = (pct >= settings["min_pct"] and pct > 0)

    # Optional gates
    chips = []
    passed = 0

    def chip(name, enabled, ok):
        if not enabled:
            chips.append(f"{name}–")
        else:
            chips.append(f"{name}{'✅' if ok else '❌'}")

    # Δ % Change (always considered)
    chips.append(f"Δ{'✅' if g_delta else '❌'}")
    passed += int(g_delta)

    # Volume spike ×
    if settings["use_vol_spike"]:
        volx = volume_spike(df_tf, settings["vol_window"])
        ok = bool(volx >= settings["vol_mult"])
        passed += int(ok)
        chip(" V", True, ok)
    else:
        chip(" V", False, False)

    # ROC — simple % change over last N bars (use rsi_len as ROC length for simplicity)
    roc_len = max(2, settings.get("roc_len", settings["rsi_len"]))
    if len(df_tf) > roc_len:
        roc = (df_tf["close"].iloc[-1] / df_tf["close"].iloc[-roc_len] - 1.0) * 100.0
    else:
        roc = np.nan
    use_roc = settings.get("use_roc", True)
    min_roc = settings.get("min_roc", 1.0)
    if use_roc:
        ok = bool(pd.notna(roc) and roc >= min_roc)
        passed += int(ok)
        chip(" R", True, ok)
    else:
        chip(" R", False, False)

    # Trend breakout (up)
    if settings["use_trend"]:
        ok = trend_breakout_up(df_tf, span=settings["pivot_span"], within_bars=settings["trend_within"])
        passed += int(ok)
        chip(" T", True, ok)
    else:
        chip(" T", False, False)

    # RSI
    if settings["use_rsi"]:
        ok = bool(rsi(df_tf["close"], settings["rsi_len"]).iloc[-1] >= settings["min_rsi"])
        passed += int(ok)
        chip(" S", True, ok)  # S for RSI (Strength)
    else:
        chip(" S", False, False)

    # MACD hist
    if settings["use_macd"]:
        ok = bool(macd_hist(df_tf["close"], settings["macd_fast"], settings["macd_slow"], settings["macd_sig"]).iloc[-1] >= settings["min_mhist"])
        passed += int(ok)
        chip(" M", True, ok)
    else:
        chip(" M", False, False)

    # ATR %
    if settings["use_atr"]:
        atr_pct = (atr(df_tf, settings["atr_len"]) / (df_tf["close"] + 1e-12) * 100.0).iloc[-1]
        ok = bool(atr_pct >= settings["min_atr"])
        passed += int(ok)
        chip(" A", True, ok)
    else:
        chip(" A", False, False)

    return {"pct": g_delta}, passed, " ".join(chips)

# ----------------------------- Page
st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")
st.title("Crypto Tracker by hioncrypto")

# --------- Top-of-sidebar strip (outside expanders)
with st.sidebar:
    colA, colB = st.columns([1,1])
    with colA:
        if st.button("Collapse all menu tabs", use_container_width=True):
            st.session_state["collapse_all_now"] = True
    with colB:
        st.toggle("⭐ Use My Pairs only", key="use_my_pairs", value=st.session_state.get("use_my_pairs", False), help="Show only the pairs in your 'My Pairs' list.")

    with st.popover("Manage My Pairs"):
        st.caption("Tip: Symbols like `BTC-USD`, `ETH-USDT` etc.")
        current = st.text_area("Edit list (comma‑separated)", ", ".join(st.session_state["my_pairs"]))
        if st.button("Save My Pairs"):
            new_list = [p.strip().upper() for p in current.split(",") if p.strip()]
            if new_list:
                st.session_state["my_pairs"] = new_list
                st.success("Saved.")
        st.write("Current:", st.session_state["my_pairs"])

# --------- Helper: expander that starts collapsed; collapse-all is one-shot
def expander(title: str, key: Optional[str] = None):
    opened = False
    if st.session_state.get("collapse_all_now", False):
        opened = False
    e = st.sidebar.expander(title, expanded=opened)
    return e

# --------- MARKET
with expander("Market", "exp_market"):
    exchange = st.selectbox("Exchange", EXCHANGES, index=EXCHANGES.index(DEFAULTS["exchange"]))
    effective_exchange = exchange if "coming soon" not in exchange else "Coinbase"
    if "coming soon" in exchange:
        st.info("This exchange is coming soon. Using Coinbase for data.")
    quote = st.selectbox("Quote currency", QUOTES, index=QUOTES.index(DEFAULTS["quote"]))
    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    watchlist = st.text_area("Watchlist (comma‑separated)", DEFAULTS["watchlist"])
    max_pairs = st.slider("Max pairs to evaluate", 10, 50, DEFAULTS["max_pairs"], 1)

# --------- MODE
with expander("Mode", "exp_mode"):
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0, horizontal=True)
    ws_chunk = st.slider("WS subscribe chunk (Coinbase)", 2, 20, 5, 1)

# --------- TIMEFRAMES
with expander("Timeframes", "exp_tfs"):
    sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=TF_LIST.index(DEFAULTS["sort_tf"]))
    sort_desc = st.checkbox("Sort descending (largest first)", value=True)

# --------- GATES
with expander("Gates", "exp_gates"):
    st.caption("These checks decide green/yellow; values below are beginner‑friendly defaults.")
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 50.0, DEFAULTS["min_pct"], 0.5)
    st.caption("💡 If nothing shows, lower this threshold.")

    cols1 = st.columns(3)
    with cols1[0]:
        use_vol_spike = st.toggle("Volume spike×", value=DEFAULTS["use_vol_spike"])
        vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, DEFAULTS["vol_mult"], 0.05)
    with cols1[1]:
        use_rsi = st.toggle("RSI", value=DEFAULTS["use_rsi"])
        min_rsi = st.slider("Min RSI", 40, 90, DEFAULTS["min_rsi"], 1)
    with cols1[2]:
        use_macd = st.toggle("MACD hist", value=DEFAULTS["use_macd"])
        min_mhist = st.slider("Min MACD hist", 0.0, 2.0, DEFAULTS["min_mhist"], 0.05)

    cols2 = st.columns(3)
    with cols2[0]:
        use_atr = st.toggle("ATR %", value=DEFAULTS["use_atr"], help="ATR/close × 100")
        min_atr = st.slider("Min ATR %", 0.0, 10.0, DEFAULTS["min_atr"], 0.1)
    with cols2[1]:
        use_trend = st.toggle("Trend breakout (up)", value=DEFAULTS["use_trend"],
                              help="Close > last pivot high, occurred recently.")
        pivot_span = st.slider("Pivot span (bars)", 2, 10, DEFAULTS["pivot_span"], 1)
        trend_within = st.slider("Breakout within (bars)", 5, 96, DEFAULTS["trend_within"], 1)
    with cols2[2]:
        use_roc = st.toggle("ROC (rate of change)", value=True)
        min_roc = st.slider("Min ROC % (over ~RSI length)", 0.0, 50.0, 1.0, 0.5)

    st.markdown("---")
    st.subheader("Color rules — beginner friendly")
    K_green = st.selectbox("Gates needed to turn green (K)", list(range(1,8)), index=DEFAULTS["K_green"]-1)
    Y_yellow = st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0, K_green)), index=min(DEFAULTS["Y_yellow"], K_green-1))
    st.caption("Enabled checks: Δ + any toggled gates • Green needs ≥ K • Yellow needs ≥ Y (but < K)")

    # Reset to defaults button
    if st.button("Reset gates to defaults"):
        st.session_state.update({
            "min_pct": DEFAULTS["min_pct"], "use_vol_spike": DEFAULTS["use_vol_spike"],
            "vol_mult": DEFAULTS["vol_mult"], "use_rsi": DEFAULTS["use_rsi"], "min_rsi": DEFAULTS["min_rsi"],
            "use_macd": DEFAULTS["use_macd"], "min_mhist": DEFAULTS["min_mhist"], "use_atr": DEFAULTS["use_atr"],
            "min_atr": DEFAULTS["min_atr"], "use_trend": DEFAULTS["use_trend"],
            "pivot_span": DEFAULTS["pivot_span"], "trend_within": DEFAULTS["trend_within"],
            "K_green": DEFAULTS["K_green"], "Y_yellow": DEFAULTS["Y_yellow"],
        })
        st.rerun()

# --------- INDICATOR LENGTHS
with expander("Indicator lengths", "exp_lens"):
    rsi_len = st.slider("RSI length", 5, 50, DEFAULTS["rsi_len"], 1)
    macd_fast = st.slider("MACD fast EMA", 3, 50, DEFAULTS["macd_fast"], 1)
    macd_slow = st.slider("MACD slow EMA", 5, 100, DEFAULTS["macd_slow"], 1)
    macd_sig  = st.slider("MACD signal", 3, 50, DEFAULTS["macd_sig"], 1)
    atr_len   = st.slider("ATR length", 5, 50, DEFAULTS["atr_len"], 1)

# --------- HISTORY DEPTH
with expander("History depth (for ATH/ATL)", "exp_hist"):
    basis = st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=["Hourly","Daily","Weekly"].index(DEFAULTS["basis"]))
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, DEFAULTS["amount_hourly"], 1)
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, DEFAULTS["amount_daily"], 1)
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, DEFAULTS["amount_weekly"], 1)

# --------- DISPLAY
with expander("Display", "exp_disp"):
    font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05)

# --------- NOTIFICATIONS
with expander("Notifications", "exp_notif"):
    email_to = st.text_input("Email recipient (optional)", "")
    webhook_url = st.text_input("Webhook URL (optional)", "")

# --------- AUTO REFRESH
with expander("Auto-refresh", "exp_auto"):
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, DEFAULTS["refresh_sec"], 1)
    st.caption("Auto-refresh is always on.")

# One-shot collapse: apply then clear
if st.session_state.get("collapse_all_now", False):
    st.session_state["collapse_all_now"] = False  # clear immediately

# Global CSS
st.markdown(f"""
<style>
  html, body {{ font-size: {font_scale}rem; }}
  .row-green  {{ background: rgba(0,255,0,0.22) !important; font-weight: 600; }}
  .row-yellow {{ background: rgba(255,255,0,0.60) !important; font-weight: 600; }}
</style>
""", unsafe_allow_html=True)

# Big timeframe label
st.markdown(f"<div style='font-size:1.3rem;font-weight:700;margin:4px 0 10px 2px;'>Timeframe: {sort_tf}</div>", unsafe_allow_html=True)

# ----------------------------- Discovery
if st.session_state["use_my_pairs"]:
    pairs = st.session_state["my_pairs"][:]
else:
    if use_watch and watchlist.strip():
        pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
    else:
        pairs = list_products(effective_exchange, quote)
    pairs = [p for p in pairs if p.endswith(f"-{quote}")]
pairs = pairs[:max_pairs]

# WS start
if pairs and mode.startswith("WebSocket") and effective_exchange=="Coinbase" and WS_AVAILABLE:
    start_ws_if_needed(effective_exchange, pairs, ws_chunk)

# ----------------------------- Build rows
rows = []
green_rows = []
top10_msgs = []

for pid in pairs:
    dft = df_for_tf(effective_exchange, pid, sort_tf)
    if dft is None or len(dft) < 30:  # not enough data
        continue
    dft = dft.tail(400).copy()

    # Live price override (WS)
    last_price = float(dft["close"].iloc[-1])
    if effective_exchange=="Coinbase" and st.session_state["ws_prices"].get(pid):
        last_price = float(st.session_state["ws_prices"][pid])

    # % change (Sort TF)
    first_price = float(dft["close"].iloc[0])
    pct = (last_price/first_price - 1.0) * 100.0

    # ATH/ATL based on chosen history
    hist = get_hist(effective_exchange, pid, basis, amount)
    if hist is None or len(hist)<10:
        athp, athd, atlp, atld = np.nan, "—", np.nan, "—"
    else:
        aa = ath_atl_info(hist)
        athp, athd, atlp, atld = aa["From ATH %"], aa["ATH date"], aa["From ATL %"], aa["ATL date"]

    # Gates (evaluate last bar only)
    gates, passed, chips = build_gate_eval(dft, dict(
        min_pct=min_pct,
        use_vol_spike=use_vol_spike, vol_mult=vol_mult, vol_window=DEFAULTS["vol_window"],
        use_rsi=use_rsi, rsi_len=rsi_len, min_rsi=min_rsi,
        use_macd=use_macd, macd_fast=macd_fast, macd_slow=macd_slow, macd_sig=macd_sig, min_mhist=min_mhist,
        use_atr=use_atr, atr_len=atr_len, min_atr=min_atr,
        use_trend=use_trend, pivot_span=pivot_span, trend_within=trend_within,
        use_roc=True, min_roc=min_roc, roc_len=rsi_len,
    ))

    is_green = (passed >= K_green)
    is_yellow = (passed >= Y_yellow) and (passed < K_green) and gates["pct"]

    rows.append({
        "Pair": pid,
        "Price": last_price,
        f"% Change ({sort_tf})": pct,
        "From ATH %": athp, "ATH date": athd,
        "From ATL %": atlp, "ATL date": atld,
        "Gates": chips,
        "Strong Buy": "YES" if is_green else "—",
        "_green": is_green, "_yellow": is_yellow,
    })

# DataFrames
df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair"])
if df.empty:
    st.info("No rows to show. Loosen gates or try a different timeframe.")
else:
    chg_col = f"% Change ({sort_tf})"

    # Sort by % change (desc) ALWAYS
    df = df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index+1)

    # Masks
    green_mask = df["_green"].fillna(False).astype(bool)
    yellow_mask = df["_yellow"].fillna(False).astype(bool)

    def style_rows_full(x):
        styles = pd.DataFrame("", index=x.index, columns=x.columns)
        gm = green_mask.reindex(x.index, fill_value=False)
        ym = yellow_mask.reindex(x.index, fill_value=False)
        styles.loc[gm, :] = "background-color: rgba(0,255,0,0.22); font-weight: 600;"
        styles.loc[ym, :] = "background-color: rgba(255,255,0,0.60); font-weight: 600;"
        return styles

    # Top‑10: ONLY green
    st.subheader("📌 Top‑10 (meets green rule)")
    top10 = df[df["_green"]].sort_values(chg_col, ascending=False, na_position="last").head(10)
    top10 = top10.drop(columns=["_green","_yellow"])
    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, lower Min +% change, or reduce K (gates needed), or disable some gates.")
    else:
        def style_rows_green_only(x):
            return pd.DataFrame("background-color: rgba(0,255,0,0.22); font-weight: 600;", index=x.index, columns=x.columns)
        st.dataframe(top10.style.apply(style_rows_green_only, axis=None), use_container_width=True)

        # Alerts for new entrants
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

    # All pairs
    st.subheader("📑 All pairs")
    show_df = df.drop(columns=["_green","_yellow"])
    st.dataframe(show_df.style.apply(style_rows_full, axis=None), use_container_width=True)

    # Footer
    st.caption(f"Pairs: {len(df)} • Exchange: {effective_exchange} • Quote: {quote} • Sort TF: {sort_tf} • Mode: {'WS+REST' if (mode.startswith('WebSocket') and effective_exchange=='Coinbase' and WS_AVAILABLE) else 'REST only'}")

# ---------------- Auto-refresh timer
remaining = DEFAULTS["refresh_sec"] if 'refresh_sec' not in locals() else refresh_sec
remaining = remaining - (time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {refresh_sec if 'refresh_sec' in locals() else DEFAULTS['refresh_sec']}s (next in {int(remaining)}s)")

