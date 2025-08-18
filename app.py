# app.py — Movers Dashboard (Coinbase/Binance) with ATH/ATL (Daily/Weekly/Years),
# Momentum, Δ%, Top-10 highlighting, live tips for “too restrictive” settings,
# and collapsible sidebar.
#
# Exchange dropdown: Coinbase (working), Binance (working), others show “(coming soon)”.
# Quotes: USD, USDC, USDT, BTC, ETH, BUSD, EUR
# Timeframes: 1m, 5m, 15m, 30m*, 1h, 4h*, 6h, 12h*, 1d (*synthetic where not native)
# Sort TF default = 1h (descending). Fully reactive — no Apply buttons anywhere.
#
# Alerts: Audible chime + Test button; Email + Webhook live alerts.
# Spike gates consider: Price %, Volume×, RSI, MACD, ROC (momentum).
#
# SMTP secrets example (.streamlit/secrets.toml):
# [smtp]
# host = "smtp.example.com"
# port = 465
# user = "user"
# password = "pass"
# sender = "Alerts <alerts@example.com>"

import json, time, threading, queue, ssl, smtplib, datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ---------------- WebSocket (Coinbase only) ----------------
WS_AVAILABLE = True
try:
    import websocket
except Exception:
    WS_AVAILABLE = False

def init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("last_alert_hashes", set())
    ss.setdefault("diag", {})
init_state()

# ---------------- CSS & Audio ----------------
def inject_css_scale(scale: float):
    st.markdown(f"""
    <style>
      html, body {{ font-size: {scale}rem; }}
      [data-testid="stSidebar"] * {{ font-size: {scale}rem; }}
      [data-testid="stDataFrame"] * {{ font-size: {scale}rem; }}
      h1, h2, h3 {{ line-height: 1.2; }}
      .hint {{ color:#9aa3ab; font-size:0.92em; }}
      .warn {{ color:#ffcc66; }}
    </style>
    """, unsafe_allow_html=True)

def audible_bridge():
    st.markdown("""
    <script>
      window._mv_audio_ctx = window._mv_audio_ctx || null;
      function mvEnsureCtx() {
        if (!window._mv_audio_ctx) {
          window._mv_audio_ctx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (window._mv_audio_ctx.state === 'suspended') { window._mv_audio_ctx.resume(); }
      }
      function mvBeep() {
        mvEnsureCtx();
        const ctx = window._mv_audio_ctx;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine'; osc.frequency.value = 880;
        osc.connect(gain); gain.connect(ctx.destination);
        const now = ctx.currentTime;
        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.exponentialRampToValueAtTime(0.3, now + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.25);
        osc.start(now); osc.stop(now + 0.26);
      }
      const tick = () => {
        if (localStorage.getItem('mustBeep') === '1') {
          mvBeep();
          localStorage.setItem('mustBeep','0');
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      window.addEventListener('click', mvEnsureCtx, { once: true });
    </script>
    """, unsafe_allow_html=True)

def trigger_beep():
    st.markdown("<script>localStorage.setItem('mustBeep','1');</script>", unsafe_allow_html=True)

# ---------------- Indicators ----------------
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    d = close.diff()
    up = (d.where(d > 0, 0.0)).ewm(alpha=1/length, adjust=False).mean()
    dn = (-d.where(d < 0, 0.0)).ewm(alpha=1/length, adjust=False).mean()
    rs = up / (dn + 1e-9)
    return 100 - (100 / (1 + rs))

def macd(close: pd.Series, fast=12, slow=26, signal=9):
    m = ema(close, fast) - ema(close, slow)
    s = ema(m, signal)
    return m, s, m - s

def roc(close: pd.Series, length: int = 5) -> pd.Series:
    return close.pct_change(length) * 100.0

# ---------------- Adapters & TFs ----------------
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

NATIVE_COINBASE = {60:"1m",300:"5m",900:"15m",3600:"1h",21600:"6h",86400:"1d"}
NATIVE_BINANCE  = {60:"1m",300:"5m",900:"15m",1800:"30m",3600:"1h",14400:"4h",
                   21600:"6h",43200:"12h",86400:"1d"}

ALL_TFS = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}
DEFAULT_TFS = ["1m","5m","15m","30m","1h","4h","6h","12h","1d"]
QUOTES = ["USD","USDC","USDT","BTC","ETH","BUSD","EUR"]
EXCHANGES = [
    "Coinbase",
    "Binance",
    "Kraken (coming soon)","KuCoin (coming soon)","OKX (coming soon)",
    "Bitstamp (coming soon)","Gemini (coming soon)","Bybit (coming soon)"
]

def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=15); r.raise_for_status()
        data = r.json()
        return sorted([f"{p['base_currency']}-{p['quote_currency']}" for p in data if p.get("quote_currency")==quote])
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=20); r.raise_for_status()
        info = r.json()
        out = []
        for s in info.get("symbols", []):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote:
                out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange == "Coinbase": return coinbase_list_products(quote)
    if exchange == "Binance":  return binance_list_products(quote)
    return []

# ---------------- Candles & Resampling ----------------
def fetch_candles_coinbase(pair_dash: str, granularity_sec: int,
                           start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    url = f"{CB_BASE}/products/{pair_dash}/candles?granularity={granularity_sec}"
    params = {}
    if start: params["start"] = start.replace(tzinfo=dt.timezone.utc).isoformat()
    if end:   params["end"]   = end.replace(tzinfo=dt.timezone.utc).isoformat()
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code != 200: return None
        arr = r.json()
        if not arr: return None
        df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
        return df.sort_values("ts").reset_index(drop=True)
    except Exception:
        return None

def fetch_candles_binance(pair_dash: str, granularity_sec: int,
                          start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    base, quote = pair_dash.split("-")
    symbol = f"{base}{quote}"
    interval = NATIVE_BINANCE.get(granularity_sec)
    if not interval: return None
    params = {"symbol":symbol, "interval":interval, "limit":1000}
    if start: params["startTime"] = int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
    if end:   params["endTime"]   = int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
    try:
        r = requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=20)
        if r.status_code != 200: return None
        arr = r.json()
        if not arr: return None
        rows = []
        for a in arr:
            rows.append({"ts": pd.to_datetime(a[0], unit="ms", utc=True),
                         "open": float(a[1]), "high": float(a[2]),
                         "low": float(a[3]),  "close": float(a[4]),
                         "volume": float(a[5])})
        return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    except Exception:
        return None

def fetch_candles(exchange: str, pair_dash: str, granularity_sec: int,
                  start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    if exchange=="Coinbase": return fetch_candles_coinbase(pair_dash, granularity_sec, start, end)
    if exchange=="Binance":  return fetch_candles_binance(pair_dash, granularity_sec, start, end)
    return None

def resample_ohlcv(df: pd.DataFrame, target_sec: int) -> Optional[pd.DataFrame]:
    if df is None or df.empty: return None
    d = df.set_index(pd.DatetimeIndex(df["ts"]))
    agg = {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    out = d.resample(f"{target_sec}s", label="right", closed="right").agg(agg).dropna()
    return out.reset_index().rename(columns={"index":"ts"})

# ---------------- ATH/ATL history (Daily / Weekly / Years) ----------------
@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    """
    basis: 'Daily' -> amount in days, 'Weekly' -> amount in weeks,
           'Years' -> amount in years (daily candles)
    """
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis == "Daily":
        start_cutoff = end - dt.timedelta(days=amount)
        gran = 86400
    elif basis == "Weekly":
        start_cutoff = end - dt.timedelta(weeks=amount)
        gran = 86400
    else:  # Years
        start_cutoff = end - dt.timedelta(days=365*amount)
        gran = 86400

    out = []; step = 300
    cursor_end = end
    while True:
        win = dt.timedelta(seconds=step*gran)
        cursor_start = max(start_cutoff, cursor_end - win)
        if (cursor_end - cursor_start).total_seconds() < gran: break
        df = fetch_candles(exchange, pair, gran, start=cursor_start, end=cursor_end)
        if df is None or df.empty: break
        out.append(df)
        cursor_end = df["ts"].iloc[0]
        if cursor_end <= start_cutoff: break
    if not out: return None
    hist = pd.concat(out, ignore_index=True).drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    if basis == "Weekly":
        hist = resample_ohlcv(hist, 7*86400)
    return hist

def ath_atl_info(hist: pd.DataFrame) -> dict:
    last = float(hist["close"].iloc[-1])
    i_ath = int(hist["high"].idxmax()); i_atl = int(hist["low"].idxmin())
    ath = float(hist["high"].iloc[i_ath]); d_ath = pd.to_datetime(hist["ts"].iloc[i_ath]).date().isoformat()
    atl = float(hist["low"].iloc[i_atl]);  d_atl = pd.to_datetime(hist["ts"].iloc[i_atl]).date().isoformat()
    return {
        "ATH": ath, "ATH date": d_ath, "From ATH %": (last/ath - 1.0)*100.0 if ath>0 else np.nan,
        "ATL": atl, "ATL date": d_atl, "From ATL %": (last/atl - 1.0)*100.0 if atl>0 else np.nan,
    }

# ---------------- Trend ----------------
def trend_state(close: pd.Series, ema_fast=50, ema_slow=200) -> pd.Series:
    e50, e200 = ema(close, ema_fast), ema(close, ema_slow)
    s = pd.Series(0, index=close.index, dtype=int)
    s[(close > e50) & (e50 > e200)] = 1
    s[(close < e50) & (e50 < e200)] = -1
    return s

def last_trend_break(ts: pd.Series, state: pd.Series) -> Tuple[Optional[pd.Timestamp], str]:
    if state.empty: return None, "Neutral"
    label = "Up" if state.iloc[-1]==1 else ("Down" if state.iloc[-1]==-1 else "Neutral")
    diffs = state.diff().fillna(0).astype(int)
    idxs = np.flatnonzero(diffs.values)
    if idxs.size==0: return None, label
    return ts.iloc[idxs[-1]], label

def pretty_duration(seconds: float) -> str:
    if seconds is None or np.isnan(seconds): return "—"
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400); h, rem = divmod(rem, 3600); m, _ = divmod(rem, 60)
    out=[]; 
    if d: out.append(f"{d}d")
    if h: out.append(f"{h}h")
    if m and not d: out.append(f"{m}m")
    return " ".join(out) if out else "0m"

# ---------------- Alerts ----------------
def send_email_alert(subject, body, recipient):
    try:
        cfg = st.secrets["smtp"]
    except Exception:
        return False, "SMTP not configured in st.secrets"
    try:
        msg = MIMEMultipart()
        msg["From"] = cfg["sender"]; msg["To"] = recipient; msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port",465), context=ctx) as server:
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["sender"], recipient, msg.as_string())
        return True, "Email sent"
    except Exception as e:
        return False, f"Email error: {e}"

def post_webhook(url, payload):
    try:
        r = requests.post(url, json=payload, timeout=10)
        ok = (200 <= r.status_code < 300)
        return ok, (r.text if not ok else "OK")
    except Exception as e:
        return False, str(e)

# ---------------- Coinbase WebSocket ----------------
def ws_worker(product_ids, channel="ticker", endpoint="wss://ws-feed.exchange.coinbase.com"):
    ss = st.session_state
    try:
        ws = websocket.WebSocket()
        ws.connect(endpoint, timeout=10); ws.settimeout(1.0)
        ws.send(json.dumps({"type":"subscribe","channels":[{"name":channel,"product_ids":product_ids}]}))
        ss["ws_alive"] = True
        while ss.get("ws_alive", False):
            try:
                msg = ws.recv()
                if not msg: continue
                ss["ws_q"].put_nowait(("msg", time.time(), msg))
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as e:
                ss["ws_q"].put_nowait(("err", time.time(), str(e))); break
    except Exception as e:
        ss["ws_q"].put_nowait(("err", time.time(), str(e)))
    finally:
        try: ws.close()
        except Exception: pass
        ss["ws_alive"] = False

def drain_ws_queue():
    q = st.session_state["ws_q"]; prices = st.session_state["ws_prices"]; err = None
    while True:
        try: kind, _, payload = q.get_nowait()
        except queue.Empty: break
        if kind=="msg":
            try:
                d = json.loads(payload)
                if d.get("type")=="ticker":
                    pid = d.get("product_id"); px = d.get("price")
                    if pid and px: prices[pid]=float(px)
            except Exception: pass
        else:
            err = payload
    if err: st.session_state["diag"]["ws_error"] = err

# ---------------- Spikes ----------------
def build_spike_mask(df: pd.DataFrame, sort_tf: str,
                     price_thresh: float, vol_mult: float,
                     all_must_pass: bool,
                     rsi_overb: float, rsi_overs: float,
                     macd_abs: float, roc_abs: float) -> pd.Series:
    pt_col = f"% {sort_tf}"
    vs_col = f"Vol x {sort_tf}"
    rsi_col = f"RSI {sort_tf}"
    macd_col = f"MACD {sort_tf}"
    roc_col = f"ROC {sort_tf}"

    m_price = df[pt_col].abs() >= price_thresh
    m_vol   = df[vs_col] >= vol_mult
    m_rsi   = (df[rsi_col] >= rsi_overb) | (df[rsi_col] <= rsi_overs) if rsi_col in df else False
    m_macd  = df[macd_col].abs() >= macd_abs if macd_col in df else False
    m_roc   = df[roc_col].abs() >= roc_abs if roc_col in df else False

    conds = [m_price, m_vol, m_rsi, m_macd, m_roc]
    conds = [c for c in conds if isinstance(c, pd.Series)]

    if not conds:
        return pd.Series(False, index=df.index)

    if all_must_pass:
        m = conds[0]
        for c in conds[1:]: m = m & c
    else:
        m = conds[0]
        for c in conds[1:]: m = m | c
    return m

def style_spikes(df: pd.DataFrame, spike_mask: pd.Series):
    def _row_style(r):
        return ["background-color: rgba(0,255,0,0.18); font-weight:600;" if spike_mask.loc[r.name] else "" for _ in r]
    return df.style.apply(_row_style, axis=1)

# ---------------- Compute View ----------------
def get_df_for_tf(exchange: str, pair: str, tf: str,
                  cache_1m: Dict[str, pd.DataFrame], cache_1h: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    sec = ALL_TFS[tf]
    is_native = sec in (NATIVE_BINANCE if exchange=="Binance" else NATIVE_COINBASE)
    if is_native:
        return fetch_candles(exchange, pair, sec)
    # synthetic
    if tf == "30m":
        if pair not in cache_1m: cache_1m[pair] = fetch_candles(exchange, pair, ALL_TFS["1m"])
        return resample_ohlcv(cache_1m[pair], sec)
    if tf in ("4h","12h"):
        if pair not in cache_1h: cache_1h[pair] = fetch_candles(exchange, pair, ALL_TFS["1h"])
        return resample_ohlcv(cache_1h[pair], sec)
    return None

def compute_view(exchange: str, pairs: List[str], timeframes: List[str],
                 rsi_len: int, macd_fast: int, macd_slow: int, macd_sig: int) -> pd.DataFrame:
    rows = []; cache_1m={}; cache_1h={}
    for pid in pairs:
        rec = {"Pair": pid}; last_close = None
        for tf in timeframes:
            df = get_df_for_tf(exchange, pid, tf, cache_1m, cache_1h)
            if df is None or len(df)<30:
                for c in [f"% {tf}", f"Δ% {tf}", f"Vol x {tf}", f"RSI {tf}", f"MACD {tf}", f"ROC {tf}"]:
                    rec[c] = np.nan
                continue
            df = df.tail(200).copy()
            last_close = float(df["close"].iloc[-1]); first_close = float(df["close"].iloc[0])
            rec[f"% {tf}"]  = (last_close/first_close - 1.0)*100.0
            prev_close = float(df["close"].iloc[-2]) if len(df)>=2 else np.nan
            rec[f"Δ% {tf}"] = ((last_close/prev_close - 1.0)*100.0) if prev_close>0 else np.nan
            rec[f"RSI {tf}"]  = float(rsi(df["close"], rsi_len).iloc[-1])
            m,s,_ = macd(df["close"], macd_fast, macd_slow, macd_sig)
            rec[f"MACD {tf}"] = float((m - s).iloc[-1])
            rec[f"ROC {tf}"]  = float(roc(df["close"], 5).iloc[-1])
            rec[f"Vol x {tf}"] = float(df["volume"].iloc[-1] / (df["volume"].rolling(20).mean().iloc[-1] + 1e-9))
        rec["Last"] = last_close if last_close is not None else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)

# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Movers — Multi-Timeframe (Exchanges)", layout="wide")
st.title("Movers — Multi-Timeframe")

with st.sidebar:
    with st.expander("Market", expanded=False):
        exchange = st.selectbox("Exchange", EXCHANGES, index=0,
                                help="Coinbase & Binance work now; others are listed as coming soon.")
        if "(coming soon)" in exchange:
            st.info("This exchange is coming soon. Please use Coinbase or Binance for now.")
        effective_exchange = "Coinbase" if "(coming soon)" in exchange else exchange

        quote = st.selectbox("Quote currency", QUOTES, index=QUOTES.index("USD"))
        use_watch = st.checkbox("Use watchlist only", value=False)
        watchlist = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
        max_pairs = st.slider("Max pairs", 10, 1000, 200, 10)

    with st.expander("Timeframes", expanded=False):
        pick_tfs = st.multiselect("Select timeframes", DEFAULT_TFS, default=DEFAULT_TFS)
        sort_tf = st.selectbox("Primary sort timeframe", pick_tfs, index=pick_tfs.index("1h") if "1h" in pick_tfs else 0)
        sort_desc = st.checkbox("Sort descending (largest first)", value=True)

    with st.expander("Signals", expanded=False):
        rsi_len = st.number_input("RSI period", 5, 50, 14, 1)
        macd_fast = st.number_input("MACD fast EMA", 3, 50, 12, 1)
        macd_slow = st.number_input("MACD slow EMA", 5, 100, 26, 1)
        macd_sig = st.number_input("MACD signal", 3, 50, 9, 1)

        # Softer defaults to avoid “no pairs”
        price_thresh = st.slider("Price spike threshold (% on sort TF)", 0.5, 20.0, 1.5, 0.5)
        vol_mult     = st.slider("Volume spike multiple (×20-SMA)", 1.0, 10.0, 2.0, 0.1)
        rsi_overb    = st.number_input("RSI overbought", 50, 100, 70, 1)
        rsi_overs    = st.number_input("RSI oversold", 0, 50, 30, 1)
        macd_abs     = st.number_input("MACD abs ≥", 0.0, 10.0, 0.0, 0.1)
        roc_abs      = st.number_input("ROC abs ≥", 0.0, 20.0, 0.5, 0.5)
        all_must_pass= st.checkbox("Spike Gates (ALL must pass)", value=True)

        # Inline guidance to make less restrictive
        st.markdown(
            "<div class='hint'>If nothing appears, try: "
            "<ul>"
            "<li>Lower <b>Price %</b> and <b>Vol×</b> (e.g., Price ≤ 1.0%, Vol× ≤ 1.5)</li>"
            "<li>Set <b>MACD abs ≥</b> and <b>ROC abs ≥</b> closer to 0</li>"
            "<li>Widen RSI bounds (e.g., Overb ≥ 75, Overs ≤ 25)</li>"
            "<li>Switch gates from <b>ALL</b> to <b>Any</b></li>"
            "</ul></div>",
            unsafe_allow_html=True
        )

    with st.expander("Columns", expanded=False):
        show_from_ath = st.checkbox("Show From ATH% + date", True)
        show_from_atl = st.checkbox("Show From ATL% + date", True)
        show_trend    = st.checkbox("Show Trend / Broken / Since", True)

    with st.expander("Notifications", expanded=False):
        enable_sound = st.checkbox("Audible chime (browser)", value=True)
        st.caption("Tip: click once in the page to enable audio if your browser blocks autoplay.")
        email_to = st.text_input("Email recipient (optional)", "")
        webhook_url = st.text_input("Webhook URL (optional)", "", help="Discord/Slack/Telegram/Pushover/ntfy, etc.")
        if st.button("Test Alerts"):
            if enable_sound: trigger_beep()
            sub = "[Movers] Test alert"
            body = "This is a test alert from the app."
            if email_to:
                ok, info = send_email_alert(sub, body, email_to)
                st.success("Test email sent") if ok else st.warning(info)
            if webhook_url:
                ok, info = post_webhook(webhook_url, {"title": sub, "lines": [body]})
                st.success("Test webhook sent") if ok else st.warning(f"Webhook error: {info}")

    with st.expander("ATH/ATL History Depth", expanded=False):
        hist_basis = st.selectbox("Basis", ["Daily","Weekly","Years"], index=2)
        if hist_basis == "Daily":
            hist_amount = st.slider("Days to fetch", 30, 3650, 365, 30)
        elif hist_basis == "Weekly":
            hist_amount = st.slider("Weeks to fetch", 4, 520, 104, 4)
        else:
            hist_amount = st.slider("Years to fetch (daily)", 1, 15, 5, 1)

    with st.expander("Display", expanded=False):
        tz = st.selectbox("Time zone", ["UTC","America/New_York","America/Chicago","America/Denver","America/Los_Angeles"], index=1)
        font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05)

    with st.expander("Advanced", expanded=False):
        mode = st.radio("Data source mode", ["REST only", "WebSocket + REST (hybrid)"], index=0)
        chunk = st.slider("Coinbase WebSocket subscribe chunk", 2, 200, 10, 1)
        if st.button("Restart stream"):
            st.session_state["ws_alive"] = False
            time.sleep(0.2)
            st.rerun()

    # Dynamic Troubleshooting tips (react to your selections)
    with st.expander("Troubleshooting: Why nothing is appearing?", expanded=False):
        st.markdown(
            "<div class='hint'>"
            "<b>Common causes</b><br>"
            "• Quote not popular on selected exchange (e.g., USDT on Coinbase). Try Binance or change Quote.<br>"
            "• Watchlist-only with empty/rare pairs. Uncheck or add common pairs (BTC, ETH, SOL...).<br>"
            "• Gates too strict. Lower thresholds or change gates to <b>Any</b>.<br>"
            "• Too few pairs allowed. Increase <b>Max pairs</b>.<br>"
            "</div>",
            unsafe_allow_html=True
        )
        st.write("Your current gate thresholds:")
        st.code(f"Price ≥ {price_thresh:.2f}% | Vol× ≥ {vol_mult:.2f} | MACD abs ≥ {macd_abs:.2f} | ROC abs ≥ {roc_abs:.2f} | RSI [{rsi_overs}, {rsi_overb}] | Gates: {'ALL' if all_must_pass else 'Any'}")

# Display tweaks
inject_css_scale(font_scale)
audible_bridge()

# Discover
if use_watch and watchlist.strip():
    pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs = list_products(effective_exchange, quote)
if "(coming soon)" in exchange:
    st.info("Selected exchange is coming soon; discovery is disabled. Switch to Coinbase or Binance.")
pairs = [p for p in pairs if p.endswith(f"-{quote}")]
pairs = pairs[:max_pairs]

if not pairs:
    st.info("No pairs for this selection. Try a different Quote, uncheck watchlist-only, or increase Max pairs.")
    st.stop()

# WebSocket
diag = {"WS lib": WS_AVAILABLE, "exchange": effective_exchange, "mode": mode}
if effective_exchange!="Coinbase" and mode.startswith("WebSocket"):
    st.warning("WebSocket is only available on Coinbase. Using REST.")
    mode = "REST only"
if mode.startswith("WebSocket") and WS_AVAILABLE and effective_exchange=="Coinbase":
    if not st.session_state["ws_alive"]:
        pick = pairs[:max(2, min(chunk, len(pairs)))]
        t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start(); time.sleep(0.2)
    drain_ws_queue()
diag["ws_alive"] = bool(st.session_state["ws_alive"])
st.session_state["diag"] = diag

# Build view
try:
    view = compute_view(effective_exchange, pairs, pick_tfs, rsi_len, macd_fast, macd_slow, macd_sig)
except Exception as e:
    st.error(f"Compute error: {e}"); st.stop()
if view.empty:
    st.info("No data returned. Try fewer pairs or different TFs."); st.stop()

# ATH/ATL + Trend
ath_rows, tr_rows = [], []
if show_from_ath or show_from_atl or show_trend:
    for pid in pairs:
        h = get_hist(effective_exchange, pid, hist_basis, hist_amount)
        if h is not None and len(h)>=10:
            ath_rows.append({"Pair":pid, **ath_atl_info(h)})
        else:
            ath_rows.append({"Pair":pid, "ATH":np.nan,"ATH date":"—","From ATH %":np.nan,"ATL":np.nan,"ATL date":"—","From ATL %":np.nan})
        if show_trend:
            # trend on sort_tf; for synthetic 4h/12h evaluate from 1h base
            base_tf = "1h" if sort_tf in ("4h","12h") else sort_tf
            dft = fetch_candles(effective_exchange, pid, ALL_TFS[base_tf])
            if dft is not None and len(dft)>=220:
                stv = trend_state(dft["close"])
                brk_ts, label = last_trend_break(dft["ts"], stv)
                if brk_ts is None:
                    tr_rows.append({"Pair":pid, "Trend":"Neutral", "Broken?":"No", "Broken since":"—"})
                else:
                    since = pretty_duration((dft["ts"].iloc[-1] - brk_ts).total_seconds())
                    tr_rows.append({"Pair":pid, "Trend":label, "Broken?":"Yes", "Broken since":since})
            else:
                tr_rows.append({"Pair":pid, "Trend":"Neutral", "Broken?":"—", "Broken since":"—"})

if ath_rows: view = view.merge(pd.DataFrame(ath_rows), on="Pair", how="left")
if tr_rows:  view = view.merge(pd.DataFrame(tr_rows), on="Pair", how="left")

# Sort
sort_col = f"% {sort_tf}"
if sort_col in view.columns:
    view = view.sort_values(sort_col, ascending=not sort_desc, na_position="last")
else:
    st.warning(f"Sort column {sort_col} missing.")

# Spike mask (with momentum & volume)
spike_mask = build_spike_mask(view, sort_tf, price_thresh, vol_mult, all_must_pass,
                              rsi_overb, rsi_overs, macd_abs, roc_abs)

# Top-10 list (green when passed)
top_cols = ["Pair", sort_col, f"Δ% {sort_tf}", f"Vol x {sort_tf}", f"ROC {sort_tf}"]
top_cols = [c for c in top_cols if c in view.columns]
top_now = view.loc[spike_mask, top_cols].head(10)

# Layout
c1, c2 = st.columns([1,3])
with c1:
    st.subheader("Top-10 (meets gates)")
    if top_now.empty:
        st.write("—")
        st.caption("Tip: Loosen gates (lower Price/Vol× or toggle gates to Any) to surface candidates.")
    else:
        st.dataframe(style_spikes(top_now, pd.Series([True]*len(top_now), index=top_now.index)),
                     use_container_width=True)

with c2:
    st.subheader("All pairs ranked by movement")
    disp = view.copy()
    if not show_from_ath:
        for c in ["From ATH %","ATH date","ATH"]:
            if c in disp.columns: disp = disp.drop(columns=[c])
    if not show_from_atl:
        for c in ["From ATL %","ATL date","ATL"]:
            if c in disp.columns: disp = disp.drop(columns=[c])
    if not show_trend:
        for c in ["Trend","Broken?","Broken since"]:
            if c in disp.columns: disp = disp.drop(columns=[c])
    st.dataframe(style_spikes(disp, spike_mask.reindex(disp.index, fill_value=False)),
                 use_container_width=True, height=680)

# New-spike alerts
new_spikes = []
if not top_now.empty:
    for _, r in top_now.iterrows():
        key = f"{r['Pair']}|{sort_tf}|{round(float(r[sort_col]),2)}"
        if key not in st.session_state["last_alert_hashes"]:
            new_spikes.append((r["Pair"], float(r[sort_col])))
            st.session_state["last_alert_hashes"].add(key)

if enable_sound and new_spikes:
    trigger_beep()
if new_spikes and (email_to or webhook_url):
    sub = f"[{effective_exchange}] Spike(s) on {sort_tf}"
    body_lines = [f"{p}: {pct:+.2f}% on {sort_tf}" for p, pct in new_spikes]
    if email_to:
        ok, info = send_email_alert(sub, "\n".join(body_lines), email_to)
        if not ok: st.warning(info)
    if webhook_url:
        ok, info = post_webhook(webhook_url, {"title": sub, "lines": body_lines})
        if not ok: st.warning(f"Webhook error: {info}")

st.caption(f"Pairs: {len(view)} • Exchange: {effective_exchange} • Quote: {quote} • Sort TF: {sort_tf} • Mode: {mode}")
