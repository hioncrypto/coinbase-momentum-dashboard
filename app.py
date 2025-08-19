# app.py — Coinbase/Binance Movers (Multi-Timeframe, ATH/ATL, Trend Breaks)
# - Exchange dropdown (Coinbase, Binance)
# - Quote currencies: USD, USDC, USDT, BTC, ETH, BUSD, EUR
# - Timeframes: 1m, 5m, 15m, 30m*, 1h, 4h*, 6h, 12h*, 1d   (* = synthetic if not native)
# - Default Sort TF = 1h (descending)
# - Top Spikes panel; Spike Gates (ALL must pass) optional
# - Audible chime + Test Alerts; Email + Webhook alerts
# - ATH/ATL % with dates; Trend state & “Broken since”
# - Collapsible (expander) sidebar to reduce visual clutter
# - Keeps your REST/WebSocket hybrid (Coinbase WS; Binance uses REST)
#
# NOTE: For email, set Streamlit secrets:
# [smtp]
# host = "smtp.example.com"
# port = 465
# user = "user"
# password = "pass"
# sender = "Alerts <alerts@example.com>"

import os, json, time, math, threading, queue, ssl, smtplib, datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ------------------------------- Optional: WebSocket client (Coinbase only) ---------------
WS_AVAILABLE = True
try:
    import websocket  # pip install websocket-client
except Exception:
    WS_AVAILABLE = False

# ---------------------------------- Session State ----------------------------------------
def init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})           # { "BTC-USD": last_trade_price, ... }
    ss.setdefault("last_alert_hashes", set())
    ss.setdefault("diag", {})
init_state()

# ----------------------------------- CSS: Font Scale -------------------------------------
def inject_css_scale(scale: float):
    st.markdown(f"""
    <style>
      html, body {{ font-size: {scale}rem; }}
      [data-testid="stSidebar"] * {{ font-size: {scale}rem; }}
      [data-testid="stDataFrame"] * {{ font-size: {scale}rem; }}
      [data-testid="stTable"] * {{ font-size: {scale}rem; }}
      h1, h2, h3, h4 {{ line-height: 1.2; }}
    </style>
    """, unsafe_allow_html=True)

# ------------------------------- Audible: WebAudio beep + Test ----------------------------
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
        osc.type = 'sine';
        osc.frequency.value = 880;
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

# ------------------------------------ Indicators -----------------------------------------
def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    up = (delta.where(delta > 0, 0.0)).ewm(alpha=1/length, adjust=False).mean()
    down = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/length, adjust=False).mean()
    rs = up / (down + 1e-9)
    return 100 - (100 / (1 + rs))

def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series,pd.Series,pd.Series]:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def roc(close: pd.Series, length: int = 5) -> pd.Series:
    return close.pct_change(length) * 100.0

# -------------------------------- Exchange Adapters --------------------------------------
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

# Native intervals per exchange
NATIVE_COINBASE = {60:"1m",300:"5m",900:"15m",3600:"1h",21600:"6h",86400:"1d"}  # 4h/12h/30m synthetic
NATIVE_BINANCE  = {60:"1m",300:"5m",900:"15m",1800:"30m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}

ALL_TFS = {
    "1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400
}
DEFAULT_TFS = ["1m","5m","15m","30m","1h","4h","6h","12h","1d"]

QUOTE_CHOICES = ["USD","USDC","USDT","BTC","ETH","BUSD","EUR"]

def unify_pair_symbol(exchange: str, base: str, quote: str) -> str:
    return f"{base}-{quote}"

def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=15)
        r.raise_for_status()
        data = r.json()
        pairs = []
        for p in data:
            if p.get("quote_currency") == quote:
                pairs.append(f"{p['base_currency']}-{p['quote_currency']}")
        return sorted(pairs)
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=20)
        r.raise_for_status()
        data = r.json()
        pairs = []
        for s in data.get("symbols", []):
            if s.get("status") != "TRADING":
                continue
            if s.get("quoteAsset") == quote:
                base = s.get("baseAsset")
                pairs.append(f"{base}-{quote}")  # unify with dash
        return sorted(pairs)
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange == "Coinbase":
        return coinbase_list_products(quote)
    elif exchange == "Binance":
        return binance_list_products(quote)
    else:
        return []

# ------------------------------ Candle Fetch + Resampling --------------------------------
def fetch_candles_coinbase(pair_dash: str, granularity_sec: int,
                           start: Optional[dt.datetime]=None,
                           end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    product_id = pair_dash  # e.g., BTC-USD
    url = f"{CB_BASE}/products/{product_id}/candles?granularity={granularity_sec}"
    params = {}
    if start: params["start"] = start.replace(tzinfo=dt.timezone.utc).isoformat()
    if end:   params["end"]   = end.replace(tzinfo=dt.timezone.utc).isoformat()
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code != 200:
            return None
        arr = r.json()
        if not arr: return None
        df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
        df = df.sort_values("ts").reset_index(drop=True)
        return df
    except Exception:
        return None

def fetch_candles_binance(pair_dash: str, granularity_sec: int,
                          start: Optional[dt.datetime]=None,
                          end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    base, quote = pair_dash.split("-")
    symbol = f"{base}{quote}"
    interval = NATIVE_BINANCE.get(granularity_sec)
    if not interval:
        return None
    url = f"{BN_BASE}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": 1000}
    if start: params["startTime"] = int(start.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    if end:   params["endTime"]   = int(end.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    try:
        r = requests.get(url, params=params, timeout=20)
        if r.status_code != 200:
            return None
        arr = r.json()
        if not arr: return None
        # Binance: [openTime, open, high, low, close, volume, closeTime, ...]
        rows = []
        for a in arr:
            rows.append({
                "ts": pd.to_datetime(a[0], unit="ms", utc=True),
                "open": float(a[1]),
                "high": float(a[2]),
                "low": float(a[3]),
                "close": float(a[4]),
                "volume": float(a[5]),
            })
        df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
        return df
    except Exception:
        return None

def fetch_candles(exchange: str, pair_dash: str, granularity_sec: int,
                  start: Optional[dt.datetime]=None,
                  end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    if exchange == "Coinbase":
        return fetch_candles_coinbase(pair_dash, granularity_sec, start, end)
    elif exchange == "Binance":
        return fetch_candles_binance(pair_dash, granularity_sec, start, end)
    return None

def resample_ohlcv(df: pd.DataFrame, target_sec: int) -> Optional[pd.DataFrame]:
    if df is None or df.empty: return None
    g = str(target_sec) + "s"
    d = df.copy()
    d = d.set_index(pd.DatetimeIndex(d["ts"]))
    agg = {
        "open":"first","high":"max","low":"min","close":"last","volume":"sum"
    }
    out = d.resample(g, label="right", closed="right").agg(agg).dropna()
    out = out.reset_index().rename(columns={"index":"ts"})
    return out

# ------------------------------ History for ATH/ATL (daily) -------------------------------
@st.cache_data(ttl=6*3600, show_spinner=False)
def get_daily_history(exchange: str, pair_dash: str, max_years: int = 5) -> Optional[pd.DataFrame]:
    """Page daily history back up to max_years; returns OHLCV with ts (UTC)."""
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    start_cutoff = end - dt.timedelta(days=max_years*365)
    out = []
    step = 300  # max candles per Coinbase call; Binance limit 1000 per call but we normalize via time windowing

    # Use native 1d where possible
    gran = 86400
    cursor_end = end
    while True:
        # window size in seconds = step * granularity (ensures <= step candles per call)
        win = dt.timedelta(seconds=step * gran)
        cursor_start = max(start_cutoff, cursor_end - win)
        if (cursor_end - cursor_start).total_seconds() < gran:
            break
        df = fetch_candles(exchange, pair_dash, granularity_sec=gran, start=cursor_start, end=cursor_end)
        if df is None or df.empty:
            break
        out.append(df)
        cursor_end = df["ts"].iloc[0]  # move backward
        if cursor_end <= start_cutoff:
            break

    if not out:
        return None
    hist = pd.concat(out, ignore_index=True).drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    return hist

def compute_ath_atl_info(hist_daily: pd.DataFrame) -> Dict[str, object]:
    """Return dict with ATH/ATL price+date and % from ATH/ATL based on last close."""
    last = float(hist_daily["close"].iloc[-1])
    idx_ath = int(hist_daily["high"].idxmax())
    idx_atl = int(hist_daily["low"].idxmin())
    ath = float(hist_daily["high"].iloc[idx_ath]); ath_ts = pd.to_datetime(hist_daily["ts"].iloc[idx_ath])
    atl = float(hist_daily["low"].iloc[idx_atl]);  atl_ts = pd.to_datetime(hist_daily["ts"].iloc[idx_atl])
    from_ath_pct = (last / ath - 1.0) * 100.0 if ath > 0 else np.nan
    from_atl_pct = (last / atl - 1.0) * 100.0 if atl > 0 else np.nan
    return {
        "ATH": ath, "ATH date": ath_ts.date().isoformat(),
        "From ATH %": from_ath_pct,
        "ATL": atl, "ATL date": atl_ts.date().isoformat(),
        "From ATL %": from_atl_pct,
    }

# ------------------------------ Trend state & broken-since --------------------------------
def trend_state(close: pd.Series, ema_fast=50, ema_slow=200) -> pd.Series:
    e50 = ema(close, ema_fast)
    e200 = ema(close, ema_slow)
    # 1=Up, -1=Down, 0=Neutral
    stv = pd.Series(0, index=close.index, dtype=int)
    stv[(close > e50) & (e50 > e200)] = 1
    stv[(close < e50) & (e50 < e200)] = -1
    return stv

def last_trend_break(ts: pd.Series, state: pd.Series) -> Tuple[Optional[pd.Timestamp], str]:
    """Find the most recent index where state changed."""
    if state.empty: return None, "Neutral"
    curr = int(state.iloc[-1])
    label = "Up" if curr == 1 else ("Down" if curr == -1 else "Neutral")
    # Scan backwards for last change
    diffs = state.diff().fillna(0).astype(int)
    flips = diffs.nonzero()[0]  # numpy-style, but for pandas we can do:
    flips = np.flatnonzero(diffs.values)
    if flips.size == 0:
        return None, label
    last_idx = flips[-1]
    return ts.iloc[last_idx], label

def pretty_duration(seconds: float) -> str:
    if seconds is None or np.isnan(seconds): return "—"
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    out = []
    if days: out.append(f"{days}d")
    if hours: out.append(f"{hours}h")
    if minutes and not days: out.append(f"{minutes}m")
    return " ".join(out) if out else "0m"

# ------------------------------- Alerts (email + webhook) ---------------------------------
def send_email_alert(subject, body, recipient):
    try:
        cfg = st.secrets["smtp"]  # must exist
    except Exception:
        return False, "SMTP not configured in st.secrets"

    try:
        msg = MIMEMultipart()
        msg["From"] = cfg["sender"]
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port", 465), context=ctx) as server:
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

# --------------------------------- WebSocket worker (CB) ----------------------------------
def ws_worker(product_ids, channel="ticker", endpoint="wss://ws-feed.exchange.coinbase.com"):
    ss = st.session_state
    try:
        ws = websocket.WebSocket()
        ws.connect(endpoint, timeout=10)
        ws.settimeout(1.0)
        sub = {"type":"subscribe","channels":[{"name":channel,"product_ids":product_ids}]}
        ws.send(json.dumps(sub))
        ss["ws_alive"] = True
        while ss.get("ws_alive", False):
            try:
                msg = ws.recv()
                if not msg:
                    continue
                ss["ws_q"].put_nowait(("msg", time.time(), msg))
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as e:
                ss["ws_q"].put_nowait(("err", time.time(), str(e)))
                break
    except Exception as e:
        ss["ws_q"].put_nowait(("err", time.time(), str(e)))
    finally:
        try:
            ws.close()
        except Exception:
            pass
        ss["ws_alive"] = False

def drain_ws_queue():
    q = st.session_state["ws_q"]
    prices = st.session_state["ws_prices"]
    got_err = None
    while True:
        try:
            kind, ts_, payload = q.get_nowait()
        except queue.Empty:
            break
        if kind == "msg":
            try:
                d = json.loads(payload)
                if d.get("type") == "ticker":
                    pid = d.get("product_id")
                    px = d.get("price")
                    if pid and px:
                        prices[pid] = float(px)
            except Exception:
                pass
        else:
            got_err = payload
    if got_err:
        st.session_state["diag"]["ws_error"] = got_err

# -------------------------------- Spike detection & styling -------------------------------
def build_spike_mask(df: pd.DataFrame, sort_tf: str,
                     price_thresh: float, vol_mult: float,
                     all_must_pass: bool,
                     rsi_overb: float, rsi_overs: float,
                     macd_abs: float) -> pd.Series:
    pt_col = f"% {sort_tf}"
    vs_col = f"Vol x {sort_tf}"
    rsi_col = f"RSI {sort_tf}"
    macd_col = f"MACD {sort_tf}"

    mask_price = df[pt_col].abs() >= price_thresh
    mask_vol   = df[vs_col] >= vol_mult
    if all_must_pass:
        conds = [mask_price, mask_vol]
        if rsi_col in df.columns:
            conds.append((df[rsi_col] >= rsi_overb) | (df[rsi_col] <= rsi_overs))
        if macd_col in df.columns:
            conds.append(df[macd_col].abs() >= macd_abs)
        m = conds[0]
        for c in conds[1:]:
            m = m & c
        return m
    else:
        m = mask_price | mask_vol
        return m

def style_spikes(df: pd.DataFrame, spike_mask: pd.Series) -> pd.io.formats.style.Styler:
    def _row_style(r):
        base = ""
        if spike_mask.loc[r.name]:
            base += "background-color: rgba(0,255,0,0.15); font-weight:600;"
        return [base for _ in r]
    return df.style.apply(_row_style, axis=1)

# ----------------------------------- Compute View -----------------------------------------
def get_df_for_tf(exchange: str, pair: str, tf_name: str, cache_1m: Dict[str, pd.DataFrame], cache_1h: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    sec = ALL_TFS[tf_name]
    # Native?
    is_native = (sec in (NATIVE_BINANCE if exchange=="Binance" else NATIVE_COINBASE))
    if is_native:
        return fetch_candles(exchange, pair, sec)
    # Synthetic: build from base
    if tf_name == "30m":
        # build from 1m if available; else from 5m
        base = "1m"
        if pair not in cache_1m:
            cache_1m[pair] = fetch_candles(exchange, pair, ALL_TFS[base])
        return resample_ohlcv(cache_1m[pair], sec)
    elif tf_name in ("4h","12h"):
        base = "1h"
        if pair not in cache_1h:
            cache_1h[pair] = fetch_candles(exchange, pair, ALL_TFS[base])
        return resample_ohlcv(cache_1h[pair], sec)
    else:
        return None

def compute_view(exchange: str, pairs: List[str], timeframes: List[str],
                 rsi_len: int, macd_fast: int, macd_slow: int, macd_sig: int) -> pd.DataFrame:
    rows = []
    cache_1m: Dict[str, pd.DataFrame] = {}
    cache_1h: Dict[str, pd.DataFrame] = {}

    for pid in pairs:
        rec = {"Pair": pid}
        last_close = None
        for tf_name in timeframes:
            df = get_df_for_tf(exchange, pid, tf_name, cache_1m, cache_1h)
            if df is None or len(df) < 30:
                for col in [f"% {tf_name}", f"Vol x {tf_name}", f"RSI {tf_name}", f"MACD {tf_name}"]:
                    rec[col] = np.nan
                continue
            df = df.tail(200).copy()
            last_close = float(df["close"].iloc[-1])
            first_close = float(df["close"].iloc[0])
            pct = (last_close / first_close - 1.0) * 100.0
            rec[f"% {tf_name}"] = pct

            # Indicators
            rsi_vals = rsi(df["close"], rsi_len)
            rec[f"RSI {tf_name}"] = float(rsi_vals.iloc[-1])

            m_line, s_line, _ = macd(df["close"], macd_fast, macd_slow, macd_sig)
            rec[f"MACD {tf_name}"] = float((m_line - s_line).iloc[-1])

            vol_spike = float(df["volume"].iloc[-1] / (df["volume"].rolling(20).mean().iloc[-1] + 1e-9))
            rec[f"Vol x {tf_name}"] = vol_spike

        rec["Last"] = last_close if last_close is not None else np.nan
        rows.append(rec)

    view = pd.DataFrame(rows)
    return view

# ------------------------------------ Streamlit UI ----------------------------------------
st.set_page_config(page_title="Movers — Multi-Timeframe (Exchanges)", layout="wide")
st.title("Movers — Multi-Timeframe")

# Sidebar (collapsed groups to reduce clutter)
with st.sidebar:
    # Presets removed: fully reactive (no Apply)
    with st.expander("Market", expanded=False):
        exchange = st.selectbox("Exchange", ["Coinbase","Binance"], index=0, help="Binance uses REST only; Coinbase supports WebSocket+REST.")
        quote = st.selectbox("Quote currency", QUOTE_CHOICES, index=QUOTE_CHOICES.index("USD"))
        use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
        watchlist = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
        max_pairs = st.slider("Max pairs", 10, 1000, 200, 10)

    with st.expander("Timeframes", expanded=False):
        pick_tfs = st.multiselect("Select timeframes (pick ≥1)", DEFAULT_TFS, default=DEFAULT_TFS)
        sort_tf = st.selectbox("Primary sort timeframe", pick_tfs, index=pick_tfs.index("1h") if "1h" in pick_tfs else 0)
        sort_desc = st.checkbox("Sort descending (largest first)", value=True)

    with st.expander("Signals", expanded=False):
        rsi_len = st.number_input("RSI period", 5, 50, 14, 1)
        macd_fast = st.number_input("MACD fast EMA", 3, 50, 12, 1)
        macd_slow = st.number_input("MACD slow EMA", 5, 100, 26, 1)
        macd_sig = st.number_input("MACD signal", 3, 50, 9, 1)
        price_thresh = st.slider("Price spike threshold (% on sort TF)", 0.5, 50.0, 3.0, 0.5)
        vol_mult = st.slider("Volume spike multiple (×20-SMA)", 1.0, 20.0, 3.0, 0.1)
        all_must_pass = st.checkbox("Spike Gates (ALL must pass)", value=False,
                                    help="Requires Price% and Vol×; optionally RSI and MACD thresholds below.")
        rsi_overb = st.number_input("RSI overbought", 50, 100, 70, 1)
        rsi_overs = st.number_input("RSI oversold", 0, 50, 30, 1)
        macd_abs = st.number_input("MACD abs ≥", 0.0, 10.0, 0.0, 0.1)

    with st.expander("Columns", expanded=False):
        show_from_ath = st.checkbox("Show From ATH% + date", True)
        show_from_atl = st.checkbox("Show From ATL% + date", True)
        show_trend    = st.checkbox("Show Trend / Broken / Since", True)

    with st.expander("Notifications", expanded=False):
        enable_sound = st.checkbox("Audible chime (browser)", value=True)
        st.caption("Tip: Click once anywhere if your browser blocks autoplay.")
        email_to = st.text_input("Email recipient (optional)", "")
        webhook_url = st.text_input("Webhook URL (optional)", "", help="Discord/Slack/Telegram/Pushover/ntfy, or your own webhook.")
        if st.button("Test Alerts"):
            if enable_sound: trigger_beep()
            sub = "[Movers] Test alert"
            body_lines = ["This is a test alert from the app."]
            body = "\n".join(body_lines)
            if email_to:
                ok, info = send_email_alert(sub, body, email_to)
                st.success("Test email sent") if ok else st.warning(info)
            if webhook_url:
                ok, info = post_webhook(webhook_url, {"title": sub, "lines": body_lines})
                st.success("Test webhook sent") if ok else st.warning(f"Webhook error: {info}")

    with st.expander("Display", expanded=False):
        tz = st.selectbox("Time zone", ["UTC","America/New_York","America/Chicago","America/Denver","America/Los_Angeles"], index=1)
        font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05)

    with st.expander("Advanced", expanded=False):
        mode = st.radio("Data source mode", ["REST only", "WebSocket + REST (hybrid)"], index=0)
        chunk = st.slider("WebSocket subscribe chunk size (Coinbase)", 2, 200, 10, 1)
        history_years = st.slider("ATH/ATL history depth (years)", 1, 15, 5, 1)
        restart_clicked = st.button("Restart stream")

    with st.expander("Diagnostics", expanded=False):
        st.json(st.session_state.get("diag", {}))

# Apply display tweaks
inject_css_scale(font_scale)
audible_bridge()

# Discover pairs
if use_watch and watchlist.strip():
    pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs = list_products(exchange, quote)
pairs = [p for p in pairs if p.endswith(f"-{quote}")]
pairs = pairs[:max_pairs]

if not pairs:
    st.info("No pairs found for this exchange/quote. Try a different quote or watchlist.")
    st.stop()

# WebSocket logic (Coinbase only)
diag = {"WS library": WS_AVAILABLE, "ws_alive": bool(st.session_state["ws_alive"]), "exchange": exchange, "mode": mode}
if exchange != "Coinbase" and mode.startswith("WebSocket"):
    st.warning("WebSocket mode is only available for Coinbase. Falling back to REST.")
    mode = "REST only"

if mode.startswith("WebSocket") and WS_AVAILABLE and exchange == "Coinbase":
    # Start thread if not running
    if not st.session_state["ws_alive"]:
        pick = pairs[:max(2, min(chunk, len(pairs)))]
        t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start()
        time.sleep(0.2)
    if restart_clicked:
        st.session_state["ws_alive"] = False
        time.sleep(0.2)
        st.rerun()
    drain_ws_queue()
diag["ws_alive"] = bool(st.session_state["ws_alive"])
st.session_state["diag"] = diag

# Build table view (REST pulls, with synthetic TF support)
try:
    view = compute_view(exchange, pairs, pick_tfs, rsi_len, macd_fast, macd_slow, macd_sig)
except Exception as e:
    st.error(f"Error while computing view: {e}")
    st.stop()

if len(view) == 0:
    st.info("No data… try a smaller universe or different quote.")
    st.stop()

# ATH/ATL, Trend additions (per pair; cached history)
ath_atl_rows = []
trend_rows = []
if show_from_ath or show_from_atl or show_trend:
    for pid in pairs:
        row = {"Pair": pid}
        hist = get_daily_history(exchange, pid, max_years=history_years)
        if hist is not None and len(hist) >= 10:
            info = compute_ath_atl_info(hist)
            row.update(info)
        else:
            row.update({"ATH":np.nan,"ATH date":"—","From ATH %":np.nan,"ATL":np.nan,"ATL date":"—","From ATL %":np.nan})
        ath_atl_rows.append(row)

        if show_trend:
            # Trend evaluated on the selected sort_tf
            df_tf = get_df_for_tf(exchange, pid, sort_tf, cache_1m={}, cache_1h={})
            if df_tf is not None and len(df_tf) >= 220:
                stv = trend_state(df_tf["close"])
                brk_ts, label = last_trend_break(df_tf["ts"], stv)
                if brk_ts is None:
                    broken = "No"
                    since = "—"
                else:
                    # If current label differs from label at break+1, it is broken since
                    broken = "Yes"
                    secs = (df_tf["ts"].iloc[-1] - brk_ts).total_seconds()
                    since = pretty_duration(secs)
                trend_rows.append({"Pair":pid, "Trend":label, "Broken?":broken, "Broken since":since})
            else:
                trend_rows.append({"Pair":pid, "Trend":"Neutral", "Broken?":"—", "Broken since":"—"})

# Merge extra columns
if ath_atl_rows:
    add_df = pd.DataFrame(ath_atl_rows)
    view = view.merge(add_df, on="Pair", how="left")
if trend_rows:
    tr_df = pd.DataFrame(trend_rows)
    view = view.merge(tr_df, on="Pair", how="left")

# Sorting
sort_col = f"% {sort_tf}"
if sort_col in view.columns:
    view = view.sort_values(sort_col, ascending=not sort_desc, na_position="last")
else:
    st.warning(f"Sort column {sort_col} missing.")

# Spikes
spike_mask = build_spike_mask(view, sort_tf, price_thresh, vol_mult, all_must_pass, rsi_overb, rsi_overs, macd_abs)
styled = style_spikes(view, spike_mask)

# Top spikes
top_now = view.loc[spike_mask, ["Pair", sort_col]].head(10)

# Layout
colL, colR = st.columns([1,3])
with colL:
    st.subheader("Top spikes")
    if top_now.empty:
        st.write("—")
    else:
        st.dataframe(top_now.rename(columns={sort_col: f"% {sort_tf}"}), use_container_width=True)

with colR:
    st.subheader("All pairs ranked by movement")
    # Column visibility tweaks
    display_df = view.copy()
    if not show_from_ath:
        for c in ["From ATH %","ATH date","ATH"]:
            if c in display_df.columns: display_df = display_df.drop(columns=[c])
    if not show_from_atl:
        for c in ["From ATL %","ATL date","ATL"]:
            if c in display_df.columns: display_df = display_df.drop(columns=[c])
    if not show_trend:
        for c in ["Trend","Broken?","Broken since"]:
            if c in display_df.columns: display_df = display_df.drop(columns=[c])
    # Styled rows preserve highlighting; hide index
    st.dataframe(style_spikes(display_df, spike_mask.reindex(display_df.index, fill_value=False)), use_container_width=True, height=680)

# Alerts for *new* spikes
new_spikes = []
if not top_now.empty:
    for _, row in top_now.iterrows():
        pair = row["Pair"]; pct = float(row[sort_col])
        key = f"{pair}|{sort_tf}|{round(pct,2)}"
        if key not in st.session_state["last_alert_hashes"]:
            new_spikes.append((pair, pct))
            st.session_state["last_alert_hashes"].add(key)

# audible
if (st.session_state.get("last_alert_hashes") is not None) and new_spikes and st.sidebar.checkbox("Enable audible on live spikes", value=True, key="aud_on_live"):
    trigger_beep()

# email/webhook
if new_spikes and (email_to or webhook_url):
    sub = f"[{exchange}] Spike(s) on {sort_tf}"
    body_lines = [f"{p}: {pct:+.2f}% on {sort_tf}" for p, pct in new_spikes]
    body = "\n".join(body_lines)
    if email_to:
        ok, info = send_email_alert(sub, body, email_to)
        if not ok: st.warning(info)
    if webhook_url:
        ok, info = post_webhook(webhook_url, {"title": sub, "lines": body_lines})
        if not ok: st.warning(f"Webhook error: {info}")

# Footer
st.caption(f"Pairs: {len(view)} • Exchange: {exchange} • Quote: {quote} • Sort TF: {sort_tf} • Mode: {mode} • Time zone: {tz}")

