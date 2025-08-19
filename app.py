# app.py — Movers (Signed % change, rally gates) + Pinned Top-10 + Trend Breaks + Recent-High + ATH/ATL
# Key points:
# - Sort by true signed % change (descending) so biggest gainers sit on top; losers sink.
# - Gates still catch only rallies: price % >= threshold (not abs), and Volume× (if required).
# - % column shows the timeframe explicitly: "% change (1h)".
# - Rows that pass gates turn green (in main table and Top-10).
# - Trend breaks via adjustable pivot span; recent-high metrics; ATH/ATL; alerts; hourly/daily/weekly history.
#
# SMTP example (.streamlit/secrets.toml):
# [smtp]
# host="smtp.example.com"
# port=465
# user="user"
# password="pass"
# sender="Alerts <alerts@example.com>"

import json, time, threading, queue, ssl, smtplib, datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ---------------- WebSocket (Coinbase optional) ----------------
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
    ss.setdefault("last_alert_hashes", set())  # top-10 dedupe
    ss.setdefault("trend_alerted", set())      # trend-break dedupe
    ss.setdefault("diag", {})
init_state()

# ---------------- CSS & Audio ----------------
def inject_css_scale(scale: float):
    st.markdown(f"""
    <style>
      html, body {{ font-size: {scale}rem; }}
      [data-testid="stSidebar"] * {{ font-size: {scale}rem; }}
      [data-testid="stDataFrame"] * {{ font-size: {scale}rem; }}
      .hint {{ color:#9aa3ab; font-size:0.92em; }}
      .sticky-top {{ position: sticky; top: 0; z-index: 999; background: var(--background-color); padding-top: .25rem; }}
      .sticky-bottom {{ position: sticky; bottom: 0; z-index: 999; background: var(--background-color); padding-bottom: .25rem; }}
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

# ---------------- Helpers ----------------
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

NATIVE_COINBASE = {60:"1m",300:"5m",900:"15m",3600:"1h",21600:"6h",86400:"1d"}
NATIVE_BINANCE  = {60:"1m",300:"5m",900:"15m",1800:"30m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}

ALL_TFS = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400,"1w":604800}
DEFAULT_TFS = ["1m","5m","15m","30m","1h","4h","6h","12h","1d"]
QUOTES = ["USD","USDC","USDT","BTC","ETH","BUSD","EUR"]
EXCHANGES = [
    "Coinbase","Binance",
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
    if exchange=="Coinbase": return coinbase_list_products(quote)
    if exchange=="Binance":  return binance_list_products(quote)
    return []

def fetch_candles(exchange: str, pair_dash: str, granularity_sec: int,
                  start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    if exchange=="Coinbase":
        url = f"{CB_BASE}/products/{pair_dash}/candles?granularity={granularity_sec}"
        params={}
        if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
        if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
        try:
            r=requests.get(url, params=params, timeout=20)
            if r.status_code!=200: return None
            arr=r.json(); 
            if not arr: return None
            df=pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"]=pd.to_datetime(df["ts"], unit="s", utc=True)
            return df.sort_values("ts").reset_index(drop=True)
        except Exception:
            return None
    elif exchange=="Binance":
        base, quote = pair_dash.split("-")
        symbol=f"{base}{quote}"
        interval = NATIVE_BINANCE.get(granularity_sec)
        if not interval: return None
        params={"symbol":symbol, "interval":interval, "limit":1000}
        if start: params["startTime"]=int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
        if end:   params["endTime"]=int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
        try:
            r=requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=20)
            if r.status_code!=200: return None
            arr=r.json()
            rows=[]
            for a in arr:
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
    return out.reset_index().rename(columns={"index":"ts"})

def get_df_for_tf(exchange: str, pair: str, tf: str,
                  cache_1m: Dict[str, pd.DataFrame], cache_1h: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    sec=ALL_TFS[tf]
    is_native = sec in (NATIVE_BINANCE if exchange=="Binance" else NATIVE_COINBASE)
    if is_native:
        return fetch_candles(exchange, pair, sec)
    if tf=="30m":
        if pair not in cache_1m: cache_1m[pair]=fetch_candles(exchange, pair, ALL_TFS["1m"])
        return resample_ohlcv(cache_1m[pair], sec)
    if tf in ("4h","12h"):
        if pair not in cache_1h: cache_1h[pair]=fetch_candles(exchange, pair, ALL_TFS["1h"])
        return resample_ohlcv(cache_1h[pair], sec)
    if tf=="1w":
        d1 = fetch_candles(exchange, pair, ALL_TFS["1d"])
        return resample_ohlcv(d1, 7*86400) if d1 is not None else None
    return None

# ---------------- History (Hourly/Daily/Weekly) ----------------
@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":
        gran=3600; start_cutoff=end - dt.timedelta(hours=amount)
    elif basis=="Daily":
        gran=86400; start_cutoff=end - dt.timedelta(days=amount)
    else:
        gran=86400; start_cutoff=end - dt.timedelta(weeks=amount)
    out=[]; step=300; cursor_end=end
    while True:
        win=dt.timedelta(seconds=step*gran)
        cursor_start=max(start_cutoff, cursor_end - win)
        if (cursor_end-cursor_start).total_seconds()<gran: break
        df=fetch_candles(exchange, pair, gran, start=cursor_start, end=cursor_end)
        if df is None or df.empty: break
        out.append(df); cursor_end=df["ts"].iloc[0]
        if cursor_end<=start_cutoff: break
    if not out: return None
    hist=pd.concat(out, ignore_index=True).drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    if basis=="Weekly": hist=resample_ohlcv(hist, 7*86400)
    return hist

def ath_atl_info(hist: pd.DataFrame) -> dict:
    last=float(hist["close"].iloc[-1])
    i_ath=int(hist["high"].idxmax()); i_atl=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[i_ath]); d_ath=pd.to_datetime(hist["ts"].iloc[i_ath]).date().isoformat()
    atl=float(hist["low"].iloc[i_atl]);  d_atl=pd.to_datetime(hist["ts"].iloc[i_atl]).date().isoformat()
    return {
        "From ATH %": (last/ath - 1.0)*100.0 if ath>0 else np.nan, "ATH date": d_ath,
        "From ATL %": (last/atl - 1.0)*100.0 if atl>0 else np.nan, "ATL date": d_atl
    }

# ---------------- Pivots & trend breaks ----------------
def find_pivots(close: pd.Series, span: int=3) -> Tuple[pd.Index, pd.Index]:
    n=len(close); highs=[]; lows=[]; vals=close.values
    for i in range(span, n - span):
        left  = vals[i-span:i]
        right = vals[i+1:i+1+span]
        c=vals[i]
        if c>left.max() and c>right.max(): highs.append(i)
        if c<left.min() and c<right.min(): lows.append(i)
    return pd.Index(highs), pd.Index(lows)

def recent_high_metrics(df: pd.DataFrame, span: int=3) -> Tuple[float, str]:
    if df is None or df.empty or len(df)<(span*2+5): return np.nan, "—"
    highs, _ = find_pivots(df["close"], span=span)
    if len(highs)==0: return np.nan, "—"
    idx=int(highs[-1])
    level=float(df["close"].iloc[idx])
    last=float(df["close"].iloc[-1]); last_ts=pd.to_datetime(df["ts"].iloc[-1])
    cross_idx=None
    for j in range(idx+1, len(df)):
        if float(df["close"].iloc[j]) < level:
            cross_idx=j; break
    if cross_idx is None:
        return max((last/level - 1.0)*100.0, 0.0), "—"  # still above: show 0% drop
    drop_pct=max((last/level - 1.0)*100.0, 0.0)
    dur=(last_ts - pd.to_datetime(df["ts"].iloc[cross_idx])).total_seconds()
    return drop_pct, pretty_duration(dur)

def trend_breakout_info(df: pd.DataFrame, span: int=3) -> Tuple[str, str]:
    if df is None or df.empty or len(df)<(span*2+5): return "—","—"
    highs, lows = find_pivots(df["close"], span=span)
    if len(highs)==0 and len(lows)==0: return "No","—"
    last_close=float(df["close"].iloc[-1]); last_ts=pd.to_datetime(df["ts"].iloc[-1])
    if len(highs):
        hi_idx=int(highs[-1]); level=float(df["close"].iloc[hi_idx])
        if last_close>level:
            cross=None
            for j in range(hi_idx+1, len(df)):
                if float(df["close"].iloc[j])>level: cross=j; break
            if cross is not None:
                dur=(last_ts - pd.to_datetime(df["ts"].iloc[cross])).total_seconds()
                return "Yes ↑", pretty_duration(dur)
    if len(lows):
        lo_idx=int(lows[-1]); level=float(df["close"].iloc[lo_idx])
        if last_close<level:
            cross=None
            for j in range(lo_idx+1, len(df)):
                if float(df["close"].iloc[j])<level: cross=j; break
            if cross is not None:
                dur=(last_ts - pd.to_datetime(df["ts"].iloc[cross])).total_seconds()
                return "Yes ↓", pretty_duration(dur)
    return "No","—"

def pretty_duration(seconds: float) -> str:
    if seconds is None or np.isnan(seconds): return "—"
    seconds=int(seconds); d,rem=divmod(seconds,86400); h,rem=divmod(rem,3600); m,_=divmod(rem,60)
    out=[]; 
    if d: out.append(f"{d}d")
    if h: out.append(f"{h}h")
    if m and not d: out.append(f"{m}m")
    return " ".join(out) if out else "0m"

# ---------------- Alerts ----------------
def send_email_alert(subject, body, recipient):
    try:
        cfg=st.secrets["smtp"]
    except Exception:
        return False, "SMTP not configured in st.secrets"
    try:
        msg=MIMEMultipart()
        msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body,"plain"))
        ctx=ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port",465), context=ctx) as server:
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["sender"], recipient, msg.as_string())
        return True, "Email sent"
    except Exception as e:
        return False, f"Email error: {e}"

def post_webhook(url, payload):
    try:
        r=requests.post(url, json=payload, timeout=10)
        ok=(200<=r.status_code<300)
        return ok, (r.text if not ok else "OK")
    except Exception as e:
        return False, str(e)

# ---------------- Coinbase WS ----------------
def ws_worker(product_ids, channel="ticker", endpoint="wss://ws-feed.exchange.coinbase.com"):
    ss=st.session_state
    try:
        ws=websocket.WebSocket(); ws.connect(endpoint, timeout=10); ws.settimeout(1.0)
        ws.send(json.dumps({"type":"subscribe","channels":[{"name":channel,"product_ids":product_ids}]}))
        ss["ws_alive"]=True
        while ss.get("ws_alive", False):
            try:
                msg=ws.recv()
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
        ss["ws_alive"]=False

def drain_ws_queue():
    q=st.session_state["ws_q"]; prices=st.session_state["ws_prices"]; err=None
    while True:
        try: kind,_,payload=q.get_nowait()
        except queue.Empty: break
        if kind=="msg":
            try:
                d=json.loads(payload)
                if d.get("type")=="ticker":
                    pid=d.get("product_id"); px=d.get("price")
                    if pid and px: prices[pid]=float(px)
            except Exception: pass
        else:
            err=payload
    if err: st.session_state["diag"]["ws_error"]=err

# ---------------- View building ----------------
def compute_view(exchange: str, pairs: List[str], timeframes: List[str]) -> pd.DataFrame:
    rows=[]; cache_1m={}; cache_1h={}
    for pid in pairs:
        rec={"Pair": pid}; last_close=None
        for tf in timeframes:
            df=get_df_for_tf(exchange, pid, tf, cache_1m, cache_1h)
            if df is None or len(df)<30:
                for c in [f"% {tf}", f"Vol x {tf}", f"Price {tf}"]:
                    rec[c]=np.nan
                continue
            df=df.tail(200).copy()
            last_close=float(df["close"].iloc[-1]); first_close=float(df["close"].iloc[0])
            rec[f"% {tf}"]=(last_close/first_close - 1.0)*100.0        # keep signed % change
            rec[f"Vol x {tf}"]=float(df["volume"].iloc[-1] / (df["volume"].rolling(20).mean().iloc[-1] + 1e-9))
            rec[f"Price {tf}"]=last_close
        rec["Last"]=last_close if last_close is not None else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)

def build_spike_mask(df: pd.DataFrame, sort_tf: str, pct_thresh: float, vol_mult: float, require_both: bool) -> pd.Series:
    pt_col=f"% {sort_tf}"; vs_col=f"Vol x {sort_tf}"
    # Rally-only gate: positive % must exceed threshold
    m_price = df[pt_col].fillna(-1) >= pct_thresh
    m_vol   = df[vs_col].fillna(0)  >= vol_mult
    return (m_price & m_vol) if require_both else (m_price | m_vol)

def style_spikes(df: pd.DataFrame, spike_mask: pd.Series, pct_col: str):
    def _row_style(r):
        green = (spike_mask.loc[r.name])
        cells = []
        for c in df.columns:
            if green and (c == pct_col or c == "Pair"):  # pop the % and name cells most
                cells.append("background-color: rgba(0,255,0,0.18); font-weight:700;")
            elif green:
                cells.append("background-color: rgba(0,255,0,0.12); font-weight:600;")
            else:
                cells.append("")
        return cells
    return df.style.apply(_row_style, axis=1)

# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Movers — Signed % (Rally Gates)", layout="wide")
st.title("Movers — Signed % (Rally Gates)")

with st.sidebar:
    with st.expander("Market", expanded=False):
        exchange=st.selectbox("Exchange", EXCHANGES, index=0)
        effective_exchange="Coinbase" if "(coming soon)" in exchange else exchange
        if "(coming soon)" in exchange:
            st.info("This exchange is coming soon. Please use Coinbase or Binance for now.")
        quote=st.selectbox("Quote currency", QUOTES, index=0)
        use_watch=st.checkbox("Use watchlist only", value=False)
        watchlist=st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
        max_pairs=st.slider("Max pairs", 10, 1000, 200, 10)

    with st.expander("Timeframes", expanded=False):
        pick_tfs=st.multiselect("Select timeframes", DEFAULT_TFS + ["1w"], default=DEFAULT_TFS)
        # Default Sort Timeframe = 1h if available
        default_idx = pick_tfs.index("1h") if "1h" in pick_tfs else 0
        sort_tf=st.selectbox("Primary sort timeframe", pick_tfs, index=default_idx)
        sort_desc=st.checkbox("Sort descending (largest first)", value=True)

    with st.expander("Gates", expanded=False):
        pct_thresh=st.slider("Min +% change (Sort Timeframe)", 0.1, 20.0, 1.0, 0.1)
        vol_mult=st.slider("Min Volume× (vs 20-SMA)", 1.0, 10.0, 1.2, 0.1)
        require_both=st.checkbox("Require BOTH % and Vol×", value=True)
        st.markdown("<div class='hint'>If nothing appears: lower +% (e.g., 0.5), lower Vol× (e.g., 1.1), or uncheck “Require BOTH”.</div>", unsafe_allow_html=True)

    with st.expander("History depth", expanded=False):
        basis=st.selectbox("Basis for ATH/ATL & recent-high", ["Hourly","Daily","Weekly"], index=1)
        if basis=="Hourly":
            amount=st.slider("Hours to fetch", 1, 24*90, 24, 1)
        elif basis=="Daily":
            amount=st.slider("Days to fetch", 1, 3650, 365, 1)
        else:
            amount=st.slider("Weeks to fetch", 1, 520, 104, 1)

    with st.expander("Trend Break Settings", expanded=False):
        pivot_span=st.slider("Pivot lookback span (bars)", 2, 10, 3, 1)

    with st.expander("Notifications", expanded=False):
        enable_sound=st.checkbox("Audible chime (browser)", value=True)
        st.caption("Tip: click once in the page to enable audio if your browser blocks autoplay.")
        email_to=st.text_input("Email recipient (optional)", "")
        webhook_url=st.text_input("Webhook URL (optional)", "", help="Discord/Slack/Telegram/Pushover/ntfy, etc.")
        if st.button("Test Alerts"):
            if enable_sound: trigger_beep()
            sub="[Movers] Test alert"; body="This is a test alert from the app."
            if email_to:
                ok, info=send_email_alert(sub, body, email_to); st.success("Test email sent") if ok else st.warning(info)
            if webhook_url:
                ok, info=post_webhook(webhook_url, {"title": sub, "lines": [body]})
                st.success("Test webhook sent") if ok else st.warning(f"Webhook error: {info}")

    with st.expander("Display", expanded=False):
        tz=st.selectbox("Time zone", ["UTC","America/New_York","America/Chicago","America/Denver","America/Los_Angeles"], index=1)
        font_scale=st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05)

    with st.expander("Advanced", expanded=False):
        mode=st.radio("Data source mode", ["REST only", "WebSocket + REST (hybrid)"], index=0)
        chunk=st.slider("Coinbase WebSocket subscribe chunk", 2, 200, 10, 1)
        if st.button("Restart stream"):
            st.session_state["ws_alive"]=False; time.sleep(0.2); st.rerun()

# CSS/Audio
inject_css_scale(font_scale)
audible_bridge()

# Discover
if use_watch and watchlist.strip():
    pairs=[p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs=list_products(effective_exchange, quote)
if "(coming soon)" in exchange:
    st.info("Selected exchange is coming soon; discovery disabled.")
pairs=[p for p in pairs if p.endswith(f"-{quote}")]
pairs=pairs[:max_pairs]
if not pairs:
    st.info("No pairs. Try a different Quote, uncheck Watchlist-only, or increase Max pairs.")
    st.stop()

# WebSocket (Coinbase only)
diag={"WS lib": WS_AVAILABLE, "exchange": effective_exchange, "mode": mode}
if effective_exchange!="Coinbase" and mode.startswith("WebSocket"):
    st.warning("WebSocket is only available on Coinbase. Using REST.")
    mode="REST only"
if mode.startswith("WebSocket") and WS_AVAILABLE and effective_exchange=="Coinbase":
    if not st.session_state["ws_alive"]:
        pick=pairs[:max(2, min(chunk, len(pairs)))]
        t=threading.Thread(target=ws_worker, args=(pick,), daemon=True); t.start(); time.sleep(0.2)
    drain_ws_queue()
diag["ws_alive"]=bool(st.session_state["ws_alive"])
st.session_state["diag"]=diag

# Build view (ensure we compute the chosen sort timeframe)
needed_tfs = sorted(set([sort_tf] + pick_tfs))
base=compute_view(effective_exchange, pairs, needed_tfs)
if base.empty:
    st.info("No data returned. Try fewer pairs or different Timeframes.")
    st.stop()

# ATH/ATL & pivot-based metrics (computed on the selected sort timeframe)
extras=[]
for pid in pairs:
    h=get_hist(effective_exchange, pid, basis, amount)
    if h is not None and len(h)>=10:
        info=ath_atl_info(h)
    else:
        info={"From ATH %": np.nan, "ATH date":"—", "From ATL %": np.nan, "ATL date":"—"}
    dft=get_df_for_tf(effective_exchange, pid, sort_tf, {}, {})
    if dft is not None and len(dft)>=max(50, pivot_span*4+10):
        pct_since_high, since_high = recent_high_metrics(dft[["ts","close"]], span=pivot_span)
        tb, since_break = trend_breakout_info(dft[["ts","close"]], span=pivot_span)
    else:
        pct_since_high, since_high, tb, since_break = np.nan, "—", "—", "—"
    extras.append({"Pair": pid,
                   "% since recent high": pct_since_high,
                   "Since recent high": since_high,
                   "Trend broken?": tb,
                   "Broken since": since_break,
                   **info})
view=base.merge(pd.DataFrame(extras), on="Pair", how="left")

# Minimal display columns (ordered; show timeframe in the header)
price_col=f"Price {sort_tf}" if f"Price {sort_tf}" in view.columns else "Last"
pct_col=f"% {sort_tf}"
pct_label=f"% change ({sort_tf})"
disp=view.copy()
disp = disp[["Pair"]].assign(
    **{
        "Price": view[price_col],
        pct_label: view[pct_col],
        "% since recent high": view["% since recent high"],
        "Since recent high": view["Since recent high"],
        "From ATH %": view["From ATH %"],
        "ATH date": view["ATH date"],
        "From ATL %": view["From ATL %"],
        "ATL date": view["ATL date"],
        "Trend broken?": view["Trend broken?"],
        "Broken since": view["Broken since"],
    }
)

# Sort by signed % (descending → biggest gainers first)
disp = disp.sort_values(pct_label, ascending=not sort_desc, na_position="last").reset_index(drop=True)
disp.insert(0, "#", disp.index + 1)

# Rally-only gate mask (positive % >= threshold, and Vol× if required)
spike_mask = build_spike_mask(
    df=view.set_index("Pair"),
    sort_tf=sort_tf,
    pct_thresh=pct_thresh,
    vol_mult=vol_mult,
    require_both=require_both
).reindex(disp["Pair"].values).reset_index(drop=True)

# ---------- Top area with pinned Top-10 ----------
st.markdown("<div class='sticky-top'></div>", unsafe_allow_html=True)
c1, c2 = st.columns([1, 3], gap="large")

with c1:
    st.subheader("Top-10 (meets gates)")
    top_now = disp.loc[spike_mask].copy()
    top_now = top_now.sort_values(pct_label, ascending=not sort_desc, na_position="last").head(10)
    if top_now.empty:
        st.write("—")
        st.caption("Tip: lower +% or Vol× thresholds or uncheck “Require BOTH”.")
    else:
        st.dataframe(
            style_spikes(top_now.reset_index(drop=True),
                         pd.Series([True]*len(top_now)), pct_label),
            use_container_width=True,
        )

with c2:
    st.subheader("All pairs (ranked by % change)")
    st.dataframe(
        style_spikes(disp, spike_mask, pct_label),
        use_container_width=True, height=720
    )

# Quick TradingView links
def tv_symbol(exchange: str, pair: str) -> Optional[str]:
    base, quote = pair.split("-")
    if exchange=="Coinbase":
        tvq = quote.replace("USDC","USD").replace("BUSD","USD")
        return f"https://www.tradingview.com/chart/?symbol=COINBASE:{base}{tvq}"
    if exchange=="Binance":
        tvq = quote.replace("BUSD","USDT")
        return f"https://www.tradingview.com/chart/?symbol=BINANCE:{base}{tvq}"
    return None

with st.expander("Open charts for visible pairs", expanded=False):
    links=[f"{row['#']:>2}. {row['Pair']} — [TradingView]({tv_symbol(effective_exchange, row['Pair'])})"
           for _, row in disp.iterrows()]
    st.markdown("\n".join(links))

# Alerts: Top-10 entries
new_spikes=[]
if not top_now.empty:
    for _, r in top_now.iterrows():
        key=f"TOP10|{r['Pair']}|{sort_tf}|{round(float(r[pct_label]),2)}"
        if key not in st.session_state["last_alert_hashes"]:
            new_spikes.append((r["Pair"], float(r[pct_label])))
            st.session_state["last_alert_hashes"].add(key)

# Alerts: New trend breaks
trend_triggers=[]
for _, r in disp.iterrows():
    tb=r["Trend broken?"]
    if tb in ("Yes ↑","Yes ↓"):
        tkey=f"TREND|{r['Pair']}|{tb}"
        if tkey not in st.session_state["trend_alerted"]:
            trend_triggers.append((r["Pair"], tb, r["Broken since"]))
            st.session_state["trend_alerted"].add(tkey)

if enable_sound and (new_spikes or trend_triggers):
    trigger_beep()
if (new_spikes or trend_triggers) and (email_to or webhook_url):
    lines=[]
    if new_spikes:
        lines.append(f"Top-10 entries on {sort_tf}:")
        for p, pct in new_spikes: lines.append(f" • {p}: {pct:+.2f}%")
    if trend_triggers:
        lines.append("Trend breaks:")
        for p, tb, since in trend_triggers: lines.append(f" • {p}: {tb} (since {since})")
    sub=f"[{effective_exchange}] Movers alerts"
    if email_to:
        ok, info=send_email_alert(sub, "\n".join(lines), email_to)
        if not ok: st.warning(info)
    if webhook_url:
        ok, info=post_webhook(webhook_url, {"title": sub, "lines": lines})
        if not ok: st.warning(f"Webhook error: {info}")

# Footer control bar (quick duplicates)
st.markdown("<div class='sticky-bottom'></div>", unsafe_allow_html=True)
with st.container():
    st.write("---")
    colA, colB, colC, colD, colE = st.columns([1.2,1.2,1.2,1.2,2.4])
    with colA:
        st.caption("Quick controls")
        # mirror current sort tf
        _ = st.selectbox("Sort Timeframe", DEFAULT_TFS + ["1w"], index=(DEFAULT_TFS + ["1w"]).index("1h"), key="quick_tf", disabled=True)
    with colB:
        pct_thresh = st.slider("Min +%", 0.1, 20.0, pct_thresh, 0.1, key="quick_pct")
    with colC:
        vol_mult = st.slider("Min Vol×", 1.0, 10.0, vol_mult, 0.1, key="quick_vol")
    with colD:
        require_both = st.checkbox("Require BOTH", value=require_both, key="quick_both")
    with colE:
        st.markdown("[Back to top](#movers--signed---rally-gates)")

st.caption(f"Pairs: {len(disp)} • Exchange: {effective_exchange} • Quote: {quote} • Sort Timeframe: {sort_tf} • "
           f"Gates: {'BOTH' if require_both else 'Any'} (+%≥{pct_thresh} & Vol×≥{vol_mult}) • Mode: {mode}")

