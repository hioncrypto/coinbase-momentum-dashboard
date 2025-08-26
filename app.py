# Crypto Tracker by hioncrypto — one-file app
# Key features:
# - Discovery (Coinbase, Binance) + optional watchlist
# - "⭐ My Pairs" list (toggle All markets / My Pairs; editor, add/replace, JSON import/export, pin from tables)
# - Timeframes: 15m, 1h, 4h, 6h, 12h, 1d
# - Gates engine (Δ %Change mandatory, Volume×, ROC, Trend, RSI, MACD hist, ATR%)
# - NEW: Color rules nested in Gates: "Gates needed to turn green (K)" and "Yellow needs ≥ Y"
# - Compact "Gates" chips column: Δ V R T S M A (filled = pass; outline = fail; muted = disabled)
# - Consistent coloring: Green (meets K), Yellow (≥Y but <K), everywhere (Top‑10 + All pairs)
# - Top‑10 = rows that are Green (by current K) sorted by %Change desc; alerts fire on new entrants
# - Listings Monitor (proposed tokens → alert when they list)
# - Alerts: None / Browser chime / Email / Webhook (with Test)
# - Auto-refresh (always on) + WS ticker (Coinbase) hybrid
# - Beginner notes + legend

import json, time, datetime as dt, threading, queue, ssl, smtplib, base64
from typing import List, Optional, Tuple, Dict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import numpy as np
import pandas as pd
import requests
import streamlit as st

# -------------- Optional WebSocket (Coinbase)
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

# -------------- Session init
def _init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())       # Top-10 entrants (de-dupe per session)
    ss.setdefault("listings_seen", {})       # token -> {"coinbase":bool,"binance":bool}
    ss.setdefault("listings_first_seen", {}) # token -> iso ts (session)
    ss.setdefault("collapse_all_now", False)
    ss.setdefault("last_refresh", time.time())
    ss.setdefault("trigger_beep", False)
    ss.setdefault("my_pairs", [])            # ⭐ user-curated list
    ss.setdefault("use_my_pairs", False)     # toggle
    ss.setdefault("detail_pair", None)       # “Why?” inspector
_init_state()

# -------------- Constants / Exchanges / TFs
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
ALL_TFS = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}
QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]

# Minimum number of gates (besides %Change) to turn YELLOW; you can expose later if desired
DEFAULT_YELLOW_MIN = 2

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

# -------------- Audio bridge (browser chime)
BEEP_WAV = base64.b64encode(
    requests.get("https://cdn.jsdelivr.net/gh/anars/blank-audio/1-second-of-silence.wav").content
).decode()

def inject_audio_bridge():
    st.markdown(f"""
    <audio id="mv-beep" src="data:audio/wav;base64,{BEEP_WAV}"></audio>
    <script>
      const audio = document.getElementById('mv-beep');
      const tick = () => {{
        const tag = window.localStorage.getItem('mv_beep');
        if (tag === '1') {{
          audio.volume = 1.0;
          audio.play().catch(()=>{{}});
          window.localStorage.setItem('mv_beep','0');
        }}
        requestAnimationFrame(tick);
      }};
      requestAnimationFrame(tick);
    </script>
    """, unsafe_allow_html=True)

def trigger_beep():
    st.markdown("<script>window.localStorage.setItem('mv_beep','1');</script>", unsafe_allow_html=True)

# -------------- UI helpers
def collapse_all_button():
    with st.sidebar:
        if st.button("Collapse all menu tabs", use_container_width=True):
            st.session_state["collapse_all_now"] = True

def expander(title: str):
    opened = not st.session_state.get("collapse_all_now", False)
    return st.sidebar.expander(title, expanded=opened)

def big_timeframe_label(tf: str):
    st.markdown(
        f"<div style='font-size:1.25rem;font-weight:700;margin:6px 0 8px 2px;'>Timeframe: {tf}</div>",
        unsafe_allow_html=True
    )

# -------------- Indicators
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

def roc(close: pd.Series, length=10) -> float:
    if len(close) <= length: return np.nan
    return float(close.iloc[-1] / (close.iloc[-length-1] + 1e-12) - 1.0) * 100.0

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

# -------------- Discovery & data fetch
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

# -------------- ATH/ATL history
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

# -------------- Coinbase WebSocket
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

# -------------- Alerts
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

def push_alert(alert_type: str, subject: str, lines: List[str], email_to: str, webhook_url: str):
    if alert_type == "Browser chime":
        trigger_beep()
    if alert_type == "Email" and email_to:
        ok, info = send_email_alert(subject, "\n".join(lines), email_to)
        if not ok: st.sidebar.warning(info)
    if alert_type == "Webhook" and webhook_url:
        ok, info = post_webhook(webhook_url, {"title": subject, "lines": lines})
        if not ok: st.sidebar.warning(f"Webhook error: {info}")

# -------------- Gates engine
GATE_KEYS = ["chg","vol","roc","trend","rsi","macd","atr"]
GATE_LABELS = {"chg":"Δ","vol":"V","roc":"R","trend":"T","rsi":"S","macd":"M","atr":"A"}

def compute_gates_lastbar(dft: pd.DataFrame, settings: dict) -> Dict[str, Dict]:
    """
    Returns a dict with:
      - 'values': raw numbers per gate (for explain)
      - 'enabled': which gates are enabled (bool)
      - 'passes': which gates pass (bool)
      - 'k_pass': total count of passing enabled gates
      - 'pct_change': float % over the sort TF (positive only gate)
    """
    out = {"values":{}, "enabled":{}, "passes":{}, "k_pass":0, "pct_change":np.nan}
    close = dft["close"]; last = float(close.iloc[-1]); first = float(close.iloc[0])

    # % Change (mandatory in your model, enabled by design)
    pct = (last/first - 1.0) * 100.0
    out["values"]["chg"] = pct
    out["enabled"]["chg"] = True
    out["passes"]["chg"]  = (pct > 0) and (pct >= settings["min_pct"])
    out["pct_change"]     = pct

    # Volume spike×
    volx = volume_spike(dft, settings["vol_window"])
    v_ok = (volx >= settings["vol_mult"]) if not np.isnan(volx) else False
    out["values"]["vol"] = volx
    out["enabled"]["vol"] = settings["use_vol_spike"]
    out["passes"]["vol"]  = (settings["use_vol_spike"] and v_ok)

    # ROC
    roc_val = roc(close, settings["roc_len"])
    roc_ok  = (roc_val >= settings["min_roc"]) if not np.isnan(roc_val) else False
    out["values"]["roc"] = roc_val
    out["enabled"]["roc"] = settings["use_roc"]
    out["passes"]["roc"]  = (settings["use_roc"] and roc_ok)

    # Trend breakout
    tr_ok = trend_breakout_up(dft, span=settings["pivot_span"], within_bars=settings["trend_within"])
    out["values"]["trend"] = 1.0 if tr_ok else 0.0
    out["enabled"]["trend"] = settings["use_trend"]
    out["passes"]["trend"]  = (settings["use_trend"] and tr_ok)

    # RSI
    rsi_ser = rsi(close, settings["rsi_len"])
    rsi_ok  = (float(rsi_ser.iloc[-1]) >= settings["min_rsi"]) if len(rsi_ser) else False
    out["values"]["rsi"] = float(rsi_ser.iloc[-1]) if len(rsi_ser) else np.nan
    out["enabled"]["rsi"] = settings["use_rsi"]
    out["passes"]["rsi"]  = (settings["use_rsi"] and rsi_ok)

    # MACD hist
    mh = macd_hist(close, settings["macd_fast"], settings["macd_slow"], settings["macd_sig"])
    mh_ok = (float(mh.iloc[-1]) >= settings["min_mhist"]) if len(mh) else False
    out["values"]["macd"] = float(mh.iloc[-1]) if len(mh) else np.nan
    out["enabled"]["macd"] = settings["use_macd"]
    out["passes"]["macd"]  = (settings["use_macd"] and mh_ok)

    # ATR%
    atrp = atr(dft, settings["atr_len"]) / (close + 1e-12) * 100.0
    atr_ok = (float(atrp.iloc[-1]) >= settings["min_atr"]) if len(atrp) else False
    out["values"]["atr"] = float(atrp.iloc[-1]) if len(atrp) else np.nan
    out["enabled"]["atr"] = settings["use_atr"]
    out["passes"]["atr"]  = (settings["use_atr"] and atr_ok)

    # Count passing enabled gates (all 7 are counted; Δ included)
    out["k_pass"] = sum(1 for k in GATE_KEYS if out["enabled"].get(k, False) and out["passes"].get(k, False))
    return out

def chips_for_row(enabled: Dict[str,bool], passes: Dict[str,bool]) -> str:
    # Filled chip = pass, outline = fail, dim = disabled
    chips = []
    for k in GATE_KEYS:
        label = GATE_LABELS[k]
        if not enabled.get(k, False):
            chips.append(f"<span style='opacity:0.35;border:1px solid #999;border-radius:6px;padding:0 6px;margin-right:3px;'>{label}</span>")
        else:
            if passes.get(k, False):
                chips.append(f"<span style='background:#111;color:#fff;border-radius:6px;padding:0 6px;margin-right:3px;'>{label}</span>")
            else:
                chips.append(f"<span style='border:1px solid #111;border-radius:6px;padding:0 6px;margin-right:3px;'>{label}</span>")
    return "<div>" + "".join(chips) + "</div>"

# -------------- UI
st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")
st.title("Crypto Tracker by hioncrypto")
inject_audio_bridge()
collapse_all_button()

# Beginner purpose line
st.caption("This tool finds crypto pairs making strong upward moves. Green rows meet your rules; yellow rows are close.")

# ---- Market
with expander("Market"):
    colM1, colM2 = st.columns([1,1])
    with colM1:
        exchange = st.selectbox("Exchange", EXCHANGES, index=0)
        effective_exchange = exchange if "coming soon" not in exchange else "Coinbase"
        if "coming soon" in exchange:
            st.info("This exchange is coming soon. Using Coinbase for data.")
        quote = st.selectbox("Quote currency", QUOTES, index=0)
        use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
        watchlist = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")
        max_pairs = st.slider("Max pairs to evaluate", 10, 50, 25, 1)
    with colM2:
        st.toggle("⭐ Use My Pairs only", key="use_my_pairs", value=False, help="Only scan your saved pairs.")
        st.caption("Tip: pin from tables or edit below in ⭐ My Pairs.")
    # My Pairs editor
    with st.expander("⭐ My Pairs (save your favorites)"):
        # Will be filled after discovery so we can offer multiselect

        st.write("Use this to track only your favorite pairs. You can add from discovery or paste manually.")
        mp_text = st.text_area("Edit manually (comma-separated)", ",".join(st.session_state["my_pairs"]))
        col_mp = st.columns(4)
        with col_mp[0]:
            if st.button("Save manual list"):
                st.session_state["my_pairs"] = [p.strip().upper() for p in mp_text.split(",") if p.strip()]
                st.success(f"Saved {len(st.session_state['my_pairs'])} pairs.")
        with col_mp[1]:
            if st.button("Clear My Pairs"):
                st.session_state["my_pairs"] = []
        with col_mp[2]:
            st.download_button("Download JSON", data=json.dumps(st.session_state["my_pairs"], indent=2),
                               file_name="my_pairs.json", mime="application/json")
        with col_mp[3]:
            up = st.file_uploader("Upload JSON", type="json", label_visibility="collapsed")
            if up is not None:
                try:
                    st.session_state["my_pairs"] = [p.strip().upper() for p in json.load(up) if isinstance(p,str)]
                    st.success(f"Loaded {len(st.session_state['my_pairs'])} pairs.")
                except Exception as e:
                    st.error(f"Invalid JSON: {e}")

# ---- Mode
with expander("Mode"):
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0, horizontal=True)
    with st.popover("Advanced (Coinbase WS)"):
        ws_chunk = st.slider("WS subscribe chunk", 2, 20, 5, 1)

# ---- Timeframes
with expander("Timeframes"):
    pick_tfs = st.multiselect("Available timeframes", TF_LIST, default=TF_LIST)
    sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=1)  # default 1h
    sort_desc = st.checkbox("Sort descending (largest first)", value=True)

# ---- Gates (with nested Color Rules)
with expander("Gates"):
    st.markdown("**Checks used to qualify pairs** (turn items on/off and adjust thresholds).")
    # Simple, novice-friendly defaults
    colG1, colG2, colG3 = st.columns(3)
    with colG1:
        min_pct = st.slider("Δ Min +% change (Sort TF)", 0.0, 50.0, 6.0, 0.5,
                            help="Lower to see more results. Only positive moves count.")
        use_vol_spike = st.toggle("V Volume spike×", value=True, help="Current volume vs recent average.")
        vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, 1.10, 0.05)
    with colG2:
        use_roc = st.toggle("R ROC (momentum)", value=True, help="Rate of change vs N bars ago.")
        roc_len = st.slider("ROC length (bars)", 3, 60, 10, 1)
        min_roc = st.slider("Min ROC %", 0.0, 10.0, 0.5, 0.1)
        use_trend = st.toggle("T Trend breakout (up)", value=True, help="Close > last pivot high recently.")
    with colG3:
        # Advanced toggles kept here but visible (novice can ignore)
        use_rsi = st.toggle("S RSI", value=False)
        min_rsi = st.slider("Min RSI", 40, 90, 55, 1)
        use_macd = st.toggle("M MACD hist", value=True)
        min_mhist = st.slider("Min MACD hist", 0.0, 2.0, 0.0, 0.05)
        use_atr = st.toggle("A ATR %", value=False, help="ATR/close × 100")
        atr_len = st.slider("ATR length", 5, 50, 14, 1)
        min_atr = st.slider("Min ATR %", 0.0, 10.0, 0.5, 0.1)
        pivot_span = st.slider("Pivot span (bars)", 2, 10, 4, 1)
        trend_within = st.slider("Breakout within (bars)", 5, 96, 48, 1)

    st.markdown("---")
    st.markdown("**Color rules (green/yellow)** — beginner friendly")
    # Count enabled gates dynamically
    enabled_flags = {
        "chg": True,
        "vol": use_vol_spike,
        "roc": use_roc,
        "trend": use_trend,
        "rsi": use_rsi,
        "macd": use_macd,
        "atr": use_atr,
    }
    enabled_count = sum(1 for k,v in enabled_flags.items() if v)

    # Nested controls: K and Y
    K = st.slider("Gates needed to turn green (K)", 1, 7, 3, 1,
                  help="Green = at least K enabled checks pass.")
    # Auto-cap K to enabled_count to avoid impossible green
    if K > enabled_count:
        st.info(f"Only {enabled_count} checks are enabled. Green K auto-capped to {enabled_count}.")
        K_eff = max(1, enabled_count)
    else:
        K_eff = K

    Y = st.slider("Yellow needs ≥ Y (but < K)", 0, max(0, K_eff-1), min(DEFAULT_YELLOW_MIN, max(0, K_eff-1)), 1,
                  help="Yellow shows near-misses. Set 0 to disable yellow.")
    st.caption(f"Enabled checks: **{enabled_count}** • Green needs ≥ **{K_eff}** • Yellow needs ≥ **{Y}** (but < **{K_eff}**).")

# ---- Indicator lengths (exposed ones above already include ATR length)
with expander("Indicator lengths (MACD)"):
    macd_fast = st.slider("MACD fast EMA", 3, 50, 12, 1)
    macd_slow = st.slider("MACD slow EMA", 5, 100, 26, 1)
    macd_sig  = st.slider("MACD signal", 3, 50, 9, 1)
    vol_window= st.slider("Volume SMA window", 5, 50, 20, 1)

# ---- History depth for ATH/ATL
with expander("History depth (for ATH/ATL)"):
    basis = st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=1)
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1)
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 90, 1)
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 12, 1)

# ---- Display
with expander("Display"):
    font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05)

# ---- Notifications
with expander("Notifications (Top‑10 & Listings)"):
    alert_type = st.selectbox("Alert type", ["None","Browser chime","Email","Webhook"], index=1)
    colN1, colN2, colN3 = st.columns([1,1,1])
    with colN1:
        if st.button("Test sound"):
            trigger_beep()
    with colN2:
        email_to = st.text_input("Email recipient (for Email)", "")
    with colN3:
        webhook_url = st.text_input("Webhook URL (for Webhook)", "")
    alert_only_my = st.checkbox("Alert only for ⭐ My Pairs", value=False)

# ---- Auto-refresh
with expander("Auto-refresh"):
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 30, 1)
    st.caption("Auto-refresh is always on.")

# ---- Listings Monitor
with expander("Listings Monitor (proposed → live)"):
    st.caption("Type tokens you’re waiting for (e.g., SOL, AVAX). I’ll alert when they become tradable with your selected quote on Coinbase/Binance.")
    proposed_text = st.text_area("Proposed tokens (base symbols)", "SOL, AVAX, ADA, DOGE, MATIC")
    check_coinbase = st.checkbox("Check Coinbase", True)
    check_binance  = st.checkbox("Check Binance", True)
st.session_state["collapse_all_now"] = False

# ---- Global style + legend
st.markdown(f"""
<style>
  html, body {{ font-size: {font_scale}rem; }}
  .row-green {{ background: rgba(0,255,0,0.22) !important; font-weight: 600; }}
  .row-yellow {{ background: rgba(255,255,0,0.60) !important; font-weight: 600; }}
  .dfcell-html p {{ margin: 0; }}
</style>
""", unsafe_allow_html=True)

st.caption("Legend: Δ %Change • V Volume× • R ROC • T Trend • S RSI • M MACD • A ATR")

# ==================== Scanner ====================
big_timeframe_label(sort_tf)

# Discovery and My Pairs multiselect source list
if use_watch and watchlist.strip():
    discovered_pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    discovered_pairs = list_products(effective_exchange, quote)
discovered_pairs = [p for p in discovered_pairs if p.endswith(f"-{quote}")]

# Offer Add/Replace to My Pairs from discovery
with st.sidebar.expander("Add from discovery → ⭐ My Pairs"):
    picks = st.multiselect("Select pairs to add/replace", discovered_pairs, [])
    colD1, colD2 = st.columns(2)
    with colD1:
        if st.button("Add selected"):
            st.session_state["my_pairs"] = sorted(list(set(st.session_state["my_pairs"]) | set([p.upper() for p in picks])))
            st.success(f"Added. ⭐ My Pairs = {len(st.session_state['my_pairs'])}")
    with colD2:
        if st.button("Replace with selected"):
            st.session_state["my_pairs"] = [p.upper() for p in picks]
            st.success(f"Replaced. ⭐ My Pairs = {len(st.session_state['my_pairs'])}")

# Final pair universe
if st.session_state["use_my_pairs"] and st.session_state["my_pairs"]:
    pairs = [p for p in st.session_state["my_pairs"] if p.endswith(f"-{quote}")]
else:
    pairs = discovered_pairs

pairs = pairs[:max_pairs]

# Optional WebSocket ticker
if pairs and mode.startswith("WebSocket") and effective_exchange=="Coinbase" and WS_AVAILABLE:
    start_ws_if_needed(effective_exchange, pairs, ws_chunk)

rows = []
flags_green = []
flags_yellow = []

if pairs:
    for pid in pairs:
        dft = df_for_tf(effective_exchange, pid, sort_tf)
        if dft is None or len(dft) < 30:
            continue
        dft = dft.tail(400).copy()
        last_price = float(dft["close"].iloc[-1])
        if effective_exchange=="Coinbase" and st.session_state["ws_prices"].get(pid):
            last_price = float(st.session_state["ws_prices"][pid])

        hist = get_hist(effective_exchange, pid, basis, amount)
        if hist is None or len(hist)<10:
            athp, athd, atlp, atld = np.nan, "—", np.nan, "—"
        else:
            aa = ath_atl_info(hist)
            athp, athd, atlp, atld = aa["From ATH %"], aa["ATH date"], aa["From ATL %"], aa["ATL date"]

        # Evaluate gates
        g = compute_gates_lastbar(dft, {
            "min_pct": min_pct,
            "use_vol_spike": use_vol_spike, "vol_window": vol_window, "vol_mult": vol_mult,
            "use_roc": use_roc, "roc_len": roc_len, "min_roc": min_roc,
            "use_trend": use_trend, "pivot_span": pivot_span, "trend_within": trend_within,
            "use_rsi": use_rsi, "min_rsi": min_rsi, "rsi_len": st.session_state.get("rsi_len", 14),
            "use_macd": use_macd, "min_mhist": min_mhist,
            "atr_len": atr_len, "use_atr": use_atr, "min_atr": min_atr,
            "macd_fast": macd_fast, "macd_slow": macd_slow, "macd_sig": macd_sig,
        })

        # Effective K (cap to enabled gates)
        enabled_count = sum(1 for k in GATE_KEYS if g["enabled"].get(k, False))
        K_eff = min(K, max(1, enabled_count))
        Y_eff = min(Y, max(0, K_eff-1))

        green = (g["passes"]["chg"] and (g["k_pass"] >= K_eff))
        yellow = (g["passes"]["chg"] and (g["k_pass"] >= Y_eff) and (g["k_pass"] < K_eff) and (Y_eff > 0))

        flags_green.append(green)
        flags_yellow.append(yellow)

        chips_html = chips_for_row(g["enabled"], g["passes"])

        rows.append({
            "Pair": pid,
            "Price": last_price,
            f"% Change ({sort_tf})": g["pct_change"],
            "From ATH %": athp, "ATH date": athd,
            "From ATL %": atlp, "ATL date": atld,
            "Gates": chips_html,  # HTML chips
            "Strong Buy": "YES" if green else "—",
        })

df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair"])

# ----- Render tables
if not df.empty:
    chg_col = f"% Change ({sort_tf})"
    df = df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index+1)

    # Style masks aligned to df length
    gm = pd.Series(flags_green).reindex(range(len(df)), fill_value=False)
    ym = pd.Series(flags_yellow).reindex(range(len(df)), fill_value=False)

    def style_rows(x):
        styles = pd.DataFrame("", index=x.index, columns=x.columns)
        styles.loc[gm, :] = "background-color: rgba(0,255,0,0.22); font-weight: 600;"
        styles.loc[ym, :] = "background-color: rgba(255,255,0,0.60); font-weight: 600;"
        return styles

    # Ensure HTML chips render in st.dataframe
    df_disp = df.copy()
    # Convert chips HTML to markdown-friendly; st.dataframe won't render HTML, but st.markdown will.
    # Workaround: show a slim legend + explain panel, and keep the chips column as plain text hints.
    # If you use st.data_editor in newer Streamlit, you can set column_config to Markdown — optional later.
    df_disp["Gates"] = df_disp["Gates"].str.replace("<","&lt;").str.replace(">","&gt;")

    # Top‑10 = green rows by %Change desc
    st.subheader("📌 Top‑10 (meets green rule)")
    top10 = df[gm].sort_values(chg_col, ascending=False, na_position="last").head(10).reset_index(drop=True)
    if top10.empty:
        st.write("—")
        st.caption("No pairs meet your green rule yet. Try lowering Δ % change or reduce K.")
    else:
        st.dataframe(top10.style.apply(style_rows, axis=None), use_container_width=True)

    # Alerts for new Top‑10 entrants (scope to My Pairs if chosen)
    new_msgs=[]
    scope_set = set(st.session_state["my_pairs"]) if (alert_only_my and st.session_state["my_pairs"]) else None
    for _, r in top10.iterrows():
        if scope_set is not None and r["Pair"] not in scope_set:
            continue
        msg = f"{r['Pair']}: {float(r[chg_col]):+.2f}% ({sort_tf})"
        key = f"TOP10|{msg}"
        if key not in st.session_state["alert_seen"]:
            st.session_state["alert_seen"].add(key)
            new_msgs.append(msg)
    if new_msgs and alert_type!="None":
        push_alert(alert_type, f"[{effective_exchange}] Top‑10 entrant(s)", new_msgs, email_to, webhook_url)

    # All pairs table
    st.subheader("📑 All pairs")
    st.caption("Tip: Sort any column by clicking its header. Green = meets your K gates. Yellow = near‑miss (≥Y but <K).")
    st.dataframe(df_disp.style.apply(style_rows, axis=None), use_container_width=True)

    # Quick pin-to-My-Pairs tool (dropdown + button)
    with st.expander("⭐ Pin from All pairs to My Pairs"):
        sel_pair = st.selectbox("Pick a pair to add", df["Pair"].tolist())
        if st.button("Add to ⭐ My Pairs"):
            if sel_pair not in st.session_state["my_pairs"]:
                st.session_state["my_pairs"].append(sel_pair)
                st.success(f"Added {sel_pair} to ⭐ My Pairs.")

    st.caption(f"Pairs: {len(df)} • Exchange: {effective_exchange} • Quote: {quote} • TF: {sort_tf} • Mode: {'WS+REST' if (mode.startswith('WebSocket') and effective_exchange=='Coinbase' and WS_AVAILABLE) else 'REST only'}")
else:
    st.info("No rows to show. Lower Δ % change, reduce K, or enable fewer checks.")
    st.caption(f"Exchange: {effective_exchange} • Quote: {quote} • TF: {sort_tf}")

# ==================== Listings Monitor ====================
def check_listed_on_exchange(base: str, quote: str, exch: str) -> bool:
    if exch=="Coinbase":
        return f"{base}-{quote}" in coinbase_list_products(quote)
    if exch=="Binance":
        try:
            syms = binance_list_products(quote)
            return f"{base}-{quote}" in syms
        except Exception:
            return False
    return False

proposed_tokens = [t.strip().upper() for t in (proposed_text or "").split(",") if t.strip()]
if proposed_tokens:
    table_rows = []
    newly_listed_msgs = []
    for tok in proposed_tokens:
        cb = check_listed_on_exchange(tok, quote, "Coinbase") if check_coinbase else False
        bn = check_listed_on_exchange(tok, quote, "Binance") if check_binance else False

        prev = st.session_state["listings_seen"].get(tok, {"coinbase":False,"binance":False})
        now  = {"coinbase":cb, "binance":bn}
        st.session_state["listings_seen"][tok] = now

        if (cb or bn) and tok not in st.session_state["listings_first_seen"]:
            st.session_state["listings_first_seen"][tok] = dt.datetime.utcnow().isoformat(timespec="seconds")

        if (not prev.get("coinbase",False) and cb) or (not prev.get("binance",False) and bn):
            newly = []
            if (not prev.get("coinbase",False) and cb): newly.append("Coinbase")
            if (not prev.get("binance",False) and bn): newly.append("Binance")
            newly_listed_msgs.append(f"{tok} listed on {', '.join(newly)} (quote {quote})")

        table_rows.append({
            "Token": tok,
            "Coinbase": "Listed" if cb else "Not listed",
            "Binance":  "Listed" if bn else "Not listed",
            "First seen": st.session_state["listings_first_seen"].get(tok, "—"),
        })

    st.sidebar.markdown("**Proposed tokens status (this session):**")
    st.sidebar.dataframe(pd.DataFrame(table_rows), use_container_width=True, height=220)

    if newly_listed_msgs and alert_type!="None":
        if not alert_only_my or not st.session_state["my_pairs"]:
            push_alert(alert_type, "New listing detected", newly_listed_msgs, email_to, webhook_url)
        else:
            # If scoping alerts to My Pairs, we only alert if token base appears in My Pairs bases
            base_set = set(p.split("-")[0] for p in st.session_state["my_pairs"])
            msgs = [m for m in newly_listed_msgs if m.split()[0] in base_set]
            if msgs:
                push_alert(alert_type, "New listing detected (in ⭐ My Pairs universe)", msgs, email_to, webhook_url)

# -------------- Auto-refresh
remaining = refresh_sec - (time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {refresh_sec}s (next in {int(remaining)}s)")

