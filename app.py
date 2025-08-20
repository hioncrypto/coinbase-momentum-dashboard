# app.py — Crypto Tracker by: hioncrypto (simple UI, hidden-indicator gates, dual REST/WS)
# - Title only "Crypto Tracker" (no version tag)
# - Auto-scan on open (no Apply)
# - Discovery ON by default (+ optional "Use watchlist only")
# - Exchanges: Coinbase, Binance (others shown as "coming soon")
# - Quotes: USD, USDC, USDT, BTC, ETH, EUR
# - Timeframes: 15m, 1h, 4h, 6h, 12h, 1d (choose Sort TF)
# - Gates engine uses hidden indicators (Trend break, RSI, MACD hist, ATR%, Vol spike) + % change (positive-only)
#   * These indicators DO NOT show as columns, but DO influence Strong Buy & Top-10
# - Tables:
#   * Top‑10 (ALL gates) — green rows only
#   * All pairs — green (all gates), yellow (partial), neutral otherwise
#   * Visible columns ONLY: # | Pair | Price | % Change (Sort TF) | From ATH % | ATH date | From ATL % | ATL date | Strong Buy
# - Sortable headers: click any column (Streamlit native)
# - Alerts: Email + Webhook when a pair first enters Top‑10 (deduped)
# - Auto-refresh: ALWAYS ON (configurable seconds; no toggle)
# - Minimal WebSocket: Coinbase ticker (optional, hybrid), tucked into Advanced

import json, time, datetime as dt, threading, queue, ssl, smtplib
from typing import List, Optional, Tuple
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import numpy as np
import pandas as pd
import requests
import streamlit as st

# -------------------------- Session / Globals
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

def _init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())   # keys of already-alerted Top-10 rows
    ss.setdefault("collapse_all_now", False)
_init_state()

# -------------------------- Static config
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
ALL_TFS = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}

QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

# -------------------------- UI helpers
def collapse_all_button():
    with st.sidebar:
        if st.button("Collapse all menu tabs", use_container_width=True):
            st.session_state["collapse_all_now"] = True
        # Note: we reset this flag to False later in the script, after building the sidebar

def expander(title: str):
    opened = not st.session_state.get("collapse_all_now", False)
    return st.sidebar.expander(title, expanded=opened)

def big_timeframe_label(tf: str):
    st.markdown(
        f"<div style='font-size:1.4rem;font-weight:700;margin:4px 0 10px 2px;'>Timeframe: {tf}</div>",
        unsafe_allow_html=True
    )

# -------------------------- Indicators (hidden; used for gates only)
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
    # "breakout" if close > last pivot high and that cross happened within the last N bars
    if df is None or len(df) < span*2+5: return False
    highs,_ = find_pivots(df["close"], span)
    if len(highs)==0: return False
    hi = int(highs[-1]); level = float(df["close"].iloc[hi])
    # find first time we crossed above that level after the pivot
    cross = None
    for j in range(hi+1, len(df)):
        if float(df["close"].iloc[j]) > level:
            cross = j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# -------------------------- Discovery
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

# -------------------------- Candles
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
        # 4h/12h resample from 1h
        base = fetch_candles(exchange, pair, 3600)
        return resample_ohlcv(base, sec)
    elif exchange=="Binance":
        return fetch_candles(exchange, pair, sec)
    return None

# -------------------------- ATH/ATL history (cached)
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

# -------------------------- WebSocket (minimal, Coinbase)
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
        t.start()
        time.sleep(0.2)

# -------------------------- Notifications
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

# -------------------------- Gates engine (ALL/ANY with visibility toggles)
def build_gate_masks(
    df_tf: pd.DataFrame, df_hist: Optional[pd.DataFrame],
    settings: dict
) -> dict:
    """
    Returns dict with boolean Series:
      - m_pct_pos   : % change >= min_pct (positive-only)
      - m_vol_spike : spike >= mult           (if enabled)
      - m_rsi       : rsi >= min_rsi          (if enabled)
      - m_macd      : macd_hist >= min_mhist  (if enabled)
      - m_atr       : atr_pct >= min_atr      (if enabled)
      - m_trend     : breakout_up True        (if enabled)
      - m_all, m_any
    """
    n = len(df_tf)
    last_close = df_tf["close"].iloc[-1]
    first_close = df_tf["close"].iloc[0]
    pct = (last_close/first_close - 1.0) * 100.0
    m_pct_pos = pd.Series([pct >= settings["min_pct"] and pct > 0] * n, index=df_tf.index)

    # Compute indicators on df_tf (hidden)
    rsi_len   = settings["rsi_len"]
    macd_fast = settings["macd_fast"]; macd_slow = settings["macd_slow"]; macd_sig=settings["macd_sig"]
    atr_len   = settings["atr_len"]
    piv_span  = settings["pivot_span"]; within_bars=settings["trend_within"]
    vol_win   = settings["vol_window"]; vol_mult=settings["vol_mult"]

    # Prepare series
    rsi_ser  = rsi(df_tf["close"], rsi_len)
    mh_ser   = macd_hist(df_tf["close"], macd_fast, macd_slow, macd_sig)
    atr_ser  = atr(df_tf, atr_len) / (df_tf["close"] + 1e-12) * 100.0
    volx     = volume_spike(df_tf, vol_win)
    tr_up    = trend_breakout_up(df_tf, span=piv_span, within_bars=within_bars)

    # Build individual masks (uniform length == n)
    def uni(val: bool): return pd.Series([bool(val)]*n, index=df_tf.index)

    m_vol_spike = uni((volx >= vol_mult)) if settings["use_vol_spike"] else uni(True)
    m_rsi       = uni((rsi_ser.iloc[-1] >= settings["min_rsi"])) if settings["use_rsi"] else uni(True)
    m_macd      = uni((mh_ser.iloc[-1] >= settings["min_mhist"])) if settings["use_macd"] else uni(True)
    m_atr       = uni((atr_ser.iloc[-1] >= settings["min_atr"])) if settings["use_atr"] else uni(True)
    m_trend     = uni(tr_up) if settings["use_trend"] else uni(True)

    # Combine
    parts = [m_pct_pos, m_vol_spike, m_rsi, m_macd, m_atr, m_trend]
    enabled = [
        True, settings["use_vol_spike"], settings["use_rsi"],
        settings["use_macd"], settings["use_atr"], settings["use_trend"]
    ]
    # If gate is disabled, treat as always True
    masks_considered = [m for m, en in zip(parts, enabled) if True]  # all masks included; disabled already True

    if settings["logic"] == "ALL":
        m_all = masks_considered[0].copy()
        for m in masks_considered[1:]:
            m_all = m_all & m
        m_any = masks_considered[0].copy()
        for m in masks_considered[1:]:
            m_any = m_any | m
    else:
        # ANY logic
        m_any = masks_considered[0].copy()
        for m in masks_considered[1:]:
            m_any = m_any | m
        m_all = m_any.copy()  # for consistency

    return {
        "pct": m_pct_pos, "vol": m_vol_spike, "rsi": m_rsi, "macd": m_macd, "atr": m_atr, "trend": m_trend,
        "all": m_all, "any": m_any, "pct_value": pct
    }

# -------------------------- UI: Page & Sidebar
st.set_page_config(page_title="Crypto Tracker", layout="wide")
st.title("Crypto Tracker")

collapse_all_button()

with expander("Market"):
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    effective_exchange = exchange if "coming soon" not in exchange else "Coinbase"
    if "coming soon" in exchange: st.info("This exchange is coming soon. Using Coinbase for data.")
    quote = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    watchlist = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")
    max_pairs = st.slider("Max pairs to evaluate", 10, 50, 20, 1)

with expander("Mode"):
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0, horizontal=True)
    with st.popover("Advanced (Coinbase WS)"):
        ws_chunk = st.slider("WS subscribe chunk", 2, 20, 5, 1,
                             help="Very small subscription chunk to keep WS minimal.")

with expander("Timeframes"):
    pick_tfs = st.multiselect("Available timeframes", TF_LIST, default=TF_LIST)
    sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=1)  # default 1h
    sort_desc = st.checkbox("Sort descending (largest first)", value=True)

with expander("Gates"):
    logic = st.radio("Gate logic", ["ALL","ANY"], index=0, horizontal=True)
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 20.0, 0.5, 0.1)
    st.caption("💡 If nothing shows, lower this threshold.")

    st.markdown("**Indicators to include (used internally; NOT shown as columns):**")
    cols1 = st.columns(3)
    with cols1[0]:
        use_vol_spike = st.toggle("Volume spike×", value=True, help="Last volume vs 20-SMA.")
        vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, 1.10, 0.05)
    with cols1[1]:
        use_rsi = st.toggle("RSI", value=False)
        min_rsi = st.slider("Min RSI", 40, 90, 55, 1)
    with cols1[2]:
        use_macd = st.toggle("MACD hist", value=True)
        min_mhist = st.slider("Min MACD hist", 0.0, 2.0, 0.0, 0.05)

    cols2 = st.columns(3)
    with cols2[0]:
        use_atr = st.toggle("ATR %", value=False, help="ATR/close × 100")
        min_atr = st.slider("Min ATR %", 0.0, 10.0, 0.5, 0.1)
    with cols2[1]:
        use_trend = st.toggle("Trend breakout (up)", value=True,
                              help="Close > last pivot high, occurred recently.")
        pivot_span = st.slider("Pivot span (bars)", 2, 10, 4, 1)
        trend_within = st.slider("Breakout within (bars)", 5, 96, 48, 1)
    with cols2[2]:
        st.caption("📝 Gates are used for **Strong Buy** & **Top‑10**.\n"
                   "If too few pairs pass, loosen thresholds above.")

with expander("Indicator lengths"):
    rsi_len = st.slider("RSI length", 5, 50, 14, 1)
    macd_fast = st.slider("MACD fast EMA", 3, 50, 12, 1)
    macd_slow = st.slider("MACD slow EMA", 5, 100, 26, 1)
    macd_sig  = st.slider("MACD signal", 3, 50, 9, 1)
    atr_len   = st.slider("ATR length", 5, 50, 14, 1)
    vol_window= st.slider("Volume SMA window", 5, 50, 20, 1)

with expander("History depth (for ATH/ATL)"):
    basis = st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=1)
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1)
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 90, 1)
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 12, 1)

with expander("Display"):
    font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05)

with expander("Notifications"):
    email_to = st.text_input("Email recipient (optional)", "")
    webhook_url = st.text_input("Webhook URL (optional)", "")

with expander("Auto-refresh"):
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 30, 1)
    st.caption("Auto-refresh is always on.")

# Reset collapse flag now that sidebar is built
st.session_state["collapse_all_now"] = False

# Global CSS for row colors + font scale
st.markdown(f"""
<style>
  html, body {{ font-size: {font_scale}rem; }}
  .row-green {{ background: rgba(0,255,0,0.22) !important; font-weight: 600; }}
  .row-yellow {{ background: rgba(255,255,0,0.60) !important; font-weight: 600; }}
</style>
""", unsafe_allow_html=True)

# -------------------------- Main content
big_timeframe_label(sort_tf)

# Discover pairs (discovery ON by default)
if use_watch and watchlist.strip():
    pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs = list_products(effective_exchange, quote)
pairs = [p for p in pairs if p.endswith(f"-{quote}")]
pairs = pairs[:max_pairs]
if not pairs:
    st.info("No pairs found. Try different Quote, lower Max pairs, or use a watchlist.")
    # still fall through to refresh loop at the bottom

# Start WS if selected & available
if pairs and mode.startswith("WebSocket") and effective_exchange=="Coinbase" and WS_AVAILABLE:
    start_ws_if_needed(effective_exchange, pairs, ws_chunk)

# Build rows for display + compute gates (hidden indicators)
rows = []
green_flags = []   # all gates pass
yellow_flags = []  # partial gates pass

if pairs:
    for pid in pairs:
        dft = df_for_tf(effective_exchange, pid, sort_tf)
        if dft is None or len(dft) < 30:
            continue
        dft = dft.tail(400).copy()

        # Live price override (if WS active for Coinbase)
        last_price = float(dft["close"].iloc[-1])
        if effective_exchange=="Coinbase" and st.session_state["ws_prices"].get(pid):
            last_price = float(st.session_state["ws_prices"][pid])

        first_price = float(dft["close"].iloc[0])
        pct = (last_price/first_price - 1.0) * 100.0

        # ATH/ATL (history depth)
        hist = get_hist(effective_exchange, pid, basis, amount)
        if hist is None or len(hist)<10:
            athp, athd, atlp, atld = np.nan, "—", np.nan, "—"
        else:
            aa = ath_atl_info(hist)
            athp, athd, atlp, atld = aa["From ATH %"], aa["ATH date"], aa["From ATL %"], aa["ATL date"]

        # Gate masks for this pair (hidden indicators used here)
        m = build_gate_masks(
            dft,
            hist,
            {
                "logic": logic,
                "min_pct": min_pct,
                "use_vol_spike": use_vol_spike, "vol_window": vol_window, "vol_mult": vol_mult,
                "use_rsi": use_rsi, "min_rsi": min_rsi, "rsi_len": rsi_len,
                "use_macd": use_macd, "min_mhist": min_mhist,
                "use_atr": use_atr, "min_atr": min_atr, "atr_len": atr_len,
                "use_trend": use_trend, "pivot_span": pivot_span, "trend_within": trend_within,
                "macd_fast": macd_fast, "macd_slow": macd_slow, "macd_sig": macd_sig,
            }
        )
        # Decide pass/partial for this row
        all_pass = bool(m["all"].iloc[-1])
        any_pass = bool(m["any"].iloc[-1])
        green_flags.append(all_pass)
        yellow_flags.append((not all_pass) and any_pass)

        rows.append({
            "Pair": pid,
            "Price": last_price,
            f"% Change ({sort_tf})": pct,
            "From ATH %": athp, "ATH date": athd,
            "From ATL %": atlp, "ATL date": atld,
            "Strong Buy": "YES" if all_pass else "—",
        })

# Build DataFrame
if rows:
    df = pd.DataFrame(rows)
    chg_col = f"% Change ({sort_tf})"
    # Default sort by % change desc
    df = df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index+1)

    # Styling masks
    green_mask = pd.Series(green_flags, index=df.index)
    yellow_mask = pd.Series(yellow_flags, index=df.index)

    def style_rows(x):
        styles = pd.DataFrame("", index=x.index, columns=x.columns)
        styles.loc[green_mask, :]  = "background-color: rgba(0,255,0,0.22); font-weight: 600;"
        styles.loc[yellow_mask, :] = "background-color: rgba(255,255,0,0.60); font-weight: 600;"
        return styles

    # Top‑10 (ALL gates)
    st.subheader("📌 Top‑10 (ALL gates)")
    top10 = df[df["Strong Buy"].eq("YES")].head(10).reset_index(drop=True)
    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, loosen gates (e.g., lower Min +% change, turn off some indicator toggles).")
    else:
        st.dataframe(top10.style.apply(style_rows, axis=None), use_container_width=True)

    # All pairs
    st.subheader("📑 All pairs")
    st.dataframe(df.style.apply(style_rows, axis=None), use_container_width=True)

    # Alerts: fire when a pair first appears in Top‑10
    new_msgs=[]
    for _, r in top10.iterrows():
        key = f"{r['Pair']}|{sort_tf}|{round(float(r[chg_col]),2)}"
        if key not in st.session_state["alert_seen"]:
            st.session_state["alert_seen"].add(key)
            new_msgs.append(f"{r['Pair']}: {float(r[chg_col]):+.2f}% ({sort_tf})")

    if new_msgs:
        subject = f"[{effective_exchange}] Top‑10 Crypto Tracker"
        body    = "\n".join(new_msgs)
        if st.sidebar.checkbox("Send Email/Webhook alerts this session", value=False, help="Enable to actually send alerts."):
            if st.sidebar.text_input("Email recipient (optional)", key="alerts_email"):
                ok, info = send_email_alert(subject, body, st.session_state["alerts_email"])
                if not ok: st.sidebar.warning(info)
            if st.sidebar.text_input("Webhook URL (optional)", key="alerts_hook"):
                ok, info = post_webhook(st.session_state["alerts_hook"], {"title": subject, "lines": new_msgs})
                if not ok: st.sidebar.warning(f"Webhook error: {info}")

    st.caption(f"Pairs: {len(df)} • Exchange: {effective_exchange} • Quote: {quote} • Sort TF: {sort_tf} • Mode: {'WS+REST' if (mode.startswith('WebSocket') and effective_exchange=='Coinbase' and WS_AVAILABLE) else 'REST only'}")
else:
    st.info("No rows to show. Loosen gates or choose a different timeframe.")
    st.caption(f"Exchange: {effective_exchange} • Quote: {quote} • Sort TF: {sort_tf}")

# -------------------------- Auto-refresh (always on)
# Use Streamlit's built-in autorefresh helper
try:
    from streamlit.runtime.scriptrunner import add_script_run_ctx  # noqa
    st.experimental_rerun  # keep reference alive for older versions
except Exception:
    pass

# st_autorefresh is available in modern Streamlit; fall back to a simple countdown+rerun if not.
try:
    from streamlit import experimental_rerun as _rerun
    if "last_autorefresh" not in st.session_state:
        st.session_state["last_autorefresh"] = time.time()
    # Use a small empty placeholder to prevent layout jump
    ph = st.empty()
    # Lightweight timer bar
    remaining = max(0, int(refresh_sec - (time.time() - st.session_state["last_autorefresh"])))
    ph.caption(f"Auto-refresh every {refresh_sec}s (next in {remaining}s)")
    if remaining <= 0:
        st.session_state["last_autorefresh"] = time.time()
        _rerun()
except Exception:
    # Basic fallback
    import time as _t
    ph = st.empty()
    for i in range(refresh_sec, 0, -1):
        ph.caption(f"Auto-refresh in {i}s…")
        _t.sleep(1)
    st.experimental_rerun()
