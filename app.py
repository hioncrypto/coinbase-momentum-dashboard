# app.py — Crypto Tracker
# - In‑app TradingView chart modal (iframe, no external JS execution)
# - Top horizontal scrollbar synced to the table (no need to scroll to bottom)
# - Same columns you requested:
#   # | Pair | Price | % change (TF) | From ATH % | ATH date | From ATL % | ATL date | Trend broken? | Broken since
# - Green row: meets ALL enabled gates; Yellow: partial pass; Default: none
# - Top‑10 panel lists only pairs that meet ALL enabled gates
# - Sorting by signed % change (descending)
# - History caps: Hours ≤ 72, Days ≤ 365, Weeks ≤ 52
# - Alerts: Top‑10 entries + Trend breaks (audible/email/webhook) + Test Alert buttons
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
    import websocket  # pip install websocket-client
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
      .hint {{ color:#9aa3ab; font-size:0.92em; }}

      /* Modal overlay for TradingView (iframe version) */
      .tv-modal-backdrop {{
        position: fixed; inset: 0; background: rgba(0,0,0,0.65);
        display: none; align-items: center; justify-content: center;
        z-index: 99999;
      }}
      .tv-modal {{
        width: min(96vw, 1200px);
        height: min(85vh, 820px);
        background: var(--background-color);
        border-radius: 12px; box-shadow: 0 8px 28px rgba(0,0,0,0.45);
        overflow: hidden; position: relative;
      }}
      .tv-modal-header {{
        display:flex; align-items:center; justify-content:space-between;
        padding: 8px 12px; border-bottom: 1px solid rgba(255,255,255,0.08);
      }}
      .tv-modal-title {{ font-weight: 700; font-size: 1.05rem; }}
      .tv-close {{
        cursor: pointer; border: 0; background: transparent;
        font-size: 1.3rem; opacity: .8;
      }}
      .tv-modal-body {{ width: 100%; height: calc(100% - 44px); }}

      /* Top scrollbar wrapper */
      .top-scrollbar {{
        width: 100%; overflow-x: auto; overflow-y: hidden;
        height: 16px;
      }}
      .top-scrollbar .spacer {{ height: 1px; }}

      /* HTML table styling + highlights */
      .row-green {{ background: rgba(0,255,0,0.18); font-weight: 600; }}
      .row-yellow{{ background: rgba(255,215,0,0.18); font-weight: 600; }}

      table.mv-table {{
        width: max(1200px, 100%); border-collapse: collapse; table-layout: fixed;
      }}
      table.mv-table th, table.mv-table td {{
        padding: 6px 10px; border-bottom: 1px solid rgba(255,255,255,0.06);
        white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
        vertical-align: middle;
      }}
      table.mv-table th {{ position: sticky; top: 0; background: var(--background-color); z-index: 2; }}
      table.mv-table a.mv-pair {{
        color: var(--text-color); text-decoration: underline; cursor: pointer;
      }}
      table.mv-table a.mv-pair:hover::after {{
        content: " (click to view chart)"; opacity: .55; font-size: .92em;
      }}
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
        gain.gain.exponentialRampToValueAtTime(0.28, now + 0.01);
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

def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    roll_up = up.ewm(alpha=1/length, adjust=False).mean()
    roll_down = down.ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / (roll_down + 1e-12)
    return 100 - (100 / (1 + rs))

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

# ---------------- Exchanges / Timeframes ----------------
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

# ---------------- Candles & Resampling ----------------
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
            arr=r.json()
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
                             "volume":float(a[5]),
                             "quote_volume": float(a[7]) if len(a)>7 else None})
            df = pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
            if "quote_volume" not in df.columns:
                df["quote_volume"] = np.nan
            return df
        except Exception:
            return None
    return None

def resample_ohlcv(df: pd.DataFrame, target_sec: int) -> Optional[pd.DataFrame]:
    if df is None or df.empty: return None
    d=df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    if "quote_volume" in df.columns:
        agg["quote_volume"] = "sum"
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

# ---------------- History (capped) ----------------
@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":
        amount = min(max(1, amount), 72)
        gran=3600; start_cutoff=end - dt.timedelta(hours=amount)
    elif basis=="Daily":
        amount = min(max(1, amount), 365)
        gran=86400; start_cutoff=end - dt.timedelta(days=amount)
    else:
        amount = min(max(1, amount), 52)
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
    if "quote_volume" not in hist.columns:
        hist["quote_volume"] = hist["close"] * hist["volume"]
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
        return max((last/level - 1.0)*100.0, 0.0), "—"
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
def compute_view(exchange: str, pairs: List[str], timeframes: List[str], sort_tf: str,
                 rsi_len:int, macd_fast:int, macd_slow:int, macd_sig:int, atr_len:int) -> pd.DataFrame:
    rows=[]; cache_1m={}; cache_1h={}
    for pid in pairs:
        rec={"Pair": pid}; last_close=None
        for tf in timeframes:
            df=get_df_for_tf(exchange, pid, tf, cache_1m, cache_1h)
            if df is None or len(df)<(max(30, atr_len+macd_slow+macd_sig+5)):
                for c in [f"% {tf}", f"Vol x {tf}", f"Price {tf}"]:
                    rec[c]=np.nan
                if tf==sort_tf:
                    rec[f"RSI {tf}"]=np.nan; rec[f"MACDh {tf}"]=np.nan; rec[f"MACDcross {tf}"]=False; rec[f"ATR% {tf}"]=np.nan
                    rec[f"QuoteVol {tf}"]=np.nan; rec[f"BaseVol {tf}"]=np.nan
                continue
            df=df.tail(400).copy()
            if "quote_volume" not in df.columns:
                df["quote_volume"] = df["close"] * df["volume"]

            last_close=float(df["close"].iloc[-1]); first_close=float(df["close"].iloc[0])
            rec[f"% {tf}"]=(last_close/first_close - 1.0)*100.0
            rec[f"Vol x {tf}"]=float(df["volume"].iloc[-1] / (df["volume"].rolling(20).mean().iloc[-1] + 1e-9))
            rec[f"Price {tf}"]=last_close

            if tf==sort_tf:
                rs = rsi(df["close"], rsi_len); rec[f"RSI {tf}"]=float(rs.iloc[-1])
                macd_line, signal_line, hist = macd(df["close"], macd_fast, macd_slow, macd_sig)
                rec[f"MACDh {tf}"]=float(hist.iloc[-1])
                N=3; cross=False
                for i in range(1, min(N+1, len(macd_line))):
                    if (macd_line.iloc[-i-1] <= signal_line.iloc[-i-1]) and (macd_line.iloc[-i] > signal_line.iloc[-i]): cross=True; break
                rec[f"MACDcross {tf}"]=bool(cross)
                a = atr(df, atr_len)
                rec[f"ATR% {tf}"]=float((a.iloc[-1] / (df["close"].iloc[-1] + 1e-12)) * 100.0)
                rec[f"QuoteVol {tf}"]=float(df["quote_volume"].iloc[-1])
                rec[f"BaseVol {tf}"]=float(df["volume"].iloc[-1])

        rec["Last"]=last_close if last_close is not None else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)

def build_gate_mask(view_idxed: pd.DataFrame, sort_tf: str,
                    pct_thresh: float,
                    use_quote: bool, min_quote: float,
                    use_base: bool,  min_base: float,
                    use_spike: bool, vol_mult: float,
                    gate_logic_all: bool,
                    use_trend: bool, trend_required: str,
                    use_rsi: bool, rsi_min: float,
                    use_macd: bool, macd_hist_nonneg: bool, macd_need_cross: bool,
                    use_atr: bool, atrp_min: float) -> Tuple[pd.Series, pd.Series]:
    def col(name): return view_idxed.get(name)

    mlist = []
    m_pct = (col(f"% {sort_tf}").fillna(-1) >= pct_thresh)
    mlist.append(m_pct)

    if use_quote:
        m_quote = (col(f"QuoteVol {sort_tf}").fillna(0) >= min_quote); mlist.append(m_quote)
    if use_base:
        m_base  = (col(f"BaseVol {sort_tf}").fillna(0)  >= min_base);  mlist.append(m_base)
    if use_spike:
        m_spike = (col(f"Vol x {sort_tf}").fillna(0)   >= vol_mult);   mlist.append(m_spike)

    if use_trend:
        tb = col("Trend broken?")
        if trend_required == "Any":         m_trend = tb.isin(["Yes ↑","Yes ↓"])
        elif trend_required == "Breakout ↑": m_trend = tb.eq("Yes ↑")
        else:                                 m_trend = tb.eq("Yes ↓")
        mlist.append(m_trend.fillna(False))

    if use_rsi:
        m_rsi = (col(f"RSI {sort_tf}").fillna(0) >= rsi_min); mlist.append(m_rsi)
    if use_macd:
        m_macd = pd.Series(True, index=view_idxed.index)
        if macd_hist_nonneg: m_macd = m_macd & (col(f"MACDh {sort_tf}").fillna(-1) >= 0)
        if macd_need_cross:  m_macd = m_macd & col(f"MACDcross {sort_tf}").fillna(False)
        mlist.append(m_macd)
    if use_atr:
        m_atr = (col(f"ATR% {sort_tf}").fillna(0) >= atrp_min); mlist.append(m_atr)

    if not mlist:
        return pd.Series(False, index=view_idxed.index), pd.Series(False, index=view_idxed.index)

    m_all=mlist[0].copy(); m_any=mlist[0].copy()
    for m in mlist[1:]: m_all = m_all & m; m_any = m_any | m
    green_mask = m_all if gate_logic_all else m_any
    yellow_mask = (~green_mask) & m_any
    return green_mask, yellow_mask

# ---------------- TradingView modal (iframe) + top scroll sync ----------------
def tv_symbol(exchange: str, pair: str) -> Optional[str]:
    base, quote = pair.split("-")
    if exchange=="Coinbase":
        tvq = {"USDC":"USD","BUSD":"USD"}.get(quote, quote)
        return f"COINBASE:{base}{tvq}"
    if exchange=="Binance":
        tvq = {"BUSD":"USDT"}.get(quote, quote)
        return f"BINANCE:{base}{tvq}"
    return None

def tv_interval(tf: str) -> str:
    return {
        "1m":"1", "5m":"5", "15m":"15", "30m":"30", "1h":"60",
        "4h":"240", "6h":"360", "12h":"720", "1d":"D", "1w":"W"
    }.get(tf, "60")

def inject_chart_modal():
    st.markdown("""
    <div id="mv-tv-backdrop" class="tv-modal-backdrop" onclick="if(event.target.id==='mv-tv-backdrop'){mvCloseChart();}"></div>
    <div id="mv-tv-modal" class="tv-modal" style="display:none;">
      <div class="tv-modal-header">
        <div class="tv-modal-title" id="mv-tv-title">Chart</div>
        <button class="tv-close" onclick="mvCloseChart()">✕</button>
      </div>
      <div class="tv-modal-body">
        <iframe id="mv-tv-iframe" style="width:100%;height:100%;border:0;" loading="lazy" referrerpolicy="no-referrer-when-downgrade"></iframe>
      </div>
    </div>

    <script>
      function mvOpenChart(symbol, interval, title){
        document.getElementById('mv-tv-backdrop').style.display = 'flex';
        const modal = document.getElementById('mv-tv-modal');
        modal.style.display = 'block';
        document.getElementById('mv-tv-title').textContent = title || symbol;

        const iframe = document.getElementById('mv-tv-iframe');
        const params = new URLSearchParams({
          symbol: symbol,
          interval: interval,
          theme: 'dark',
          style: '1',
          timezone: 'Etc/UTC',
          hide_top_toolbar: '0',
          hide_side_toolbar: '0',
          allow_symbol_change: '0',
          withdateranges: '1',
          details: '1',
          studies: '',
          hideideas: '1',
          locale: 'en',
        });
        iframe.src = 'https://s.tradingview.com/widgetembed/?' + params.toString();

        document.onkeydown = (e) => { if(e.key === "Escape"){ mvCloseChart(); } };
      }

      function mvCloseChart(){
        document.getElementById('mv-tv-backdrop').style.display = 'none';
        const modal = document.getElementById('mv-tv-modal');
        modal.style.display = 'none';
        const iframe = document.getElementById('mv-tv-iframe');
        iframe.src = 'about:blank';
        document.onkeydown = null;
      }

      // Sync a top horizontal scrollbar with the table's scrollLeft
      window.mvSyncScroll = function(topId, tblId){
        const top = document.getElementById(topId);
        const tbl = document.getElementById(tblId);
        if(!top || !tbl) return;
        top.addEventListener('scroll', ()=>{ tbl.scrollLeft = top.scrollLeft; });
        tbl.addEventListener('scroll', ()=>{ top.scrollLeft = tbl.scrollLeft; });
      }
    </script>
    """, unsafe_allow_html=True)

def render_html_table(df: pd.DataFrame, green_mask: pd.Series, yellow_mask: pd.Series,
                      exchange: str, sort_tf: str, table_id: str="mvTable"):
    cols = list(df.columns)
    thead = "<tr>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"

    rows_html = []
    for i, (_, row) in enumerate(df.iterrows()):
        pair = row["Pair"]
        symbol = tv_symbol(exchange, pair) or ""
        interval = tv_interval(sort_tf)
        title = f"{pair} • {sort_tf}"
        pair_html = f'<a class="mv-pair" href="#" onclick="mvOpenChart(\'{symbol}\', \'{interval}\', \'{title}\');return false;">{pair}</a>'

        cls = "row-green" if bool(green_mask.iloc[i]) else ("row-yellow" if bool(yellow_mask.iloc[i]) else "")
        tds=[]
        for c in cols:
            if c=="Pair":
                tds.append(f"<td>{pair_html}</td>")
            else:
                val = row[c]
                if isinstance(val, float):
                    tds.append(f"<td>{val:.4g}</td>")
                else:
                    tds.append(f"<td>{val}</td>")
        rows_html.append(f'<tr class="{cls}">' + "".join(tds) + "</tr>")

    html = f"""
    <div id="topScroll" class="top-scrollbar"><div class="spacer" style="width: 1800px;"></div></div>
    <div id="{table_id}" style="overflow-x:auto; width:100%;">
      <table class="mv-table">
        <thead>{thead}</thead>
        <tbody>{"".join(rows_html)}</tbody>
      </table>
    </div>
    <script>window.mvSyncScroll("topScroll", "{table_id}");</script>
    """
    st.markdown(html, unsafe_allow_html=True)

# ---------------- Streamlit UI ----------------
st.set_page_config(page_title="Crypto Tracker", layout="wide")
st.title("Crypto Tracker")

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
        default_idx = pick_tfs.index("1h") if "1h" in pick_tfs else 0
        sort_tf=st.selectbox("Primary sort timeframe", pick_tfs, index=default_idx)
        sort_desc=st.checkbox("Sort descending (largest first)", value=True)

    with st.expander("Gates", expanded=False):
        gate_logic_all = st.radio("Gate logic for enabled filters", ["ALL", "ANY"], index=0) == "ALL"

        st.markdown("**Price gate**")
        pct_thresh=st.slider("Min +% change (Sort Timeframe)", 0.1, 20.0, 1.0, 0.1)

        st.markdown("**Volume gates**")
        colv1, colv2, colv3 = st.columns(3)
        with colv1:
            use_quote = st.checkbox("Use Quote $", value=True)
            min_quote = st.number_input("Min Quote $", min_value=0.0, value=1_000_000.0, step=100_000.0, format="%.0f")
        with colv2:
            use_base  = st.checkbox("Use Base units", value=False)
            min_base  = st.number_input("Min Base units", min_value=0.0, value=0.0, step=100.0, format="%.0f")
        with colv3:
            use_spike = st.checkbox("Use Volume spike (SMA×)", value=True)
            vol_mult  = st.slider("Min SMA×", 1.0, 10.0, 1.2, 0.1)

        st.markdown("**Trend gates**")
        use_trend = st.checkbox("Require trend break", value=False)
        trend_required = st.selectbox("Break type", ["Any","Breakout ↑","Breakdown ↓"], index=0)

        st.markdown("**Indicator gates**")
        colind1, colind2, colind3 = st.columns(3)
        with colind1:
            use_rsi = st.checkbox("RSI ≥", value=False)
            rsi_min = st.slider("RSI min", 0, 100, 55, 1)
        with colind2:
            use_macd = st.checkbox("MACD", value=False)
            macd_hist_nonneg = st.checkbox("Hist ≥ 0", value=True)
            macd_need_cross  = st.checkbox("Fresh bull cross (≤3 bars)", value=False)
        with colind3:
            use_atr = st.checkbox("ATR% ≥", value=False)
            atrp_min = st.slider("ATR% min", 0.0, 10.0, 0.5, 0.1)

        st.markdown("<div class='hint'>If too few names pass: lower +%, lower Quote $, disable Spike, or switch gate logic to ANY.</div>", unsafe_allow_html=True)

    with st.expander("History depth", expanded=False):
        basis=st.selectbox("Basis for ATH/ATL & recent-high", ["Hourly","Daily","Weekly"], index=1)
        if basis=="Hourly":
            amount=st.slider("Hours to fetch (≤72)", 1, 72, 24, 1)
        elif basis=="Daily":
            amount=st.slider("Days to fetch (≤365)", 1, 365, 90, 1)
        else:
            amount=st.slider("Weeks to fetch (≤52)", 1, 52, 12, 1)

    with st.expander("Trend/Indicator lengths", expanded=False):
        pivot_span=st.slider("Pivot lookback span (bars)", 2, 10, 3, 1)
        rsi_len=st.slider("RSI length", 5, 50, 14, 1)
        macd_fast=st.slider("MACD fast", 3, 50, 12, 1)
        macd_slow=st.slider("MACD slow", 5, 100, 26, 1)
        macd_sig =st.slider("MACD signal", 3, 50, 9, 1)
        atr_len =st.slider("ATR length", 5, 50, 14, 1)

    with st.expander("Notifications", expanded=False):
        enable_sound=st.checkbox("Audible chime (browser)", value=True)
        st.caption("Tip: click once in the page to enable audio if blocked.")
        email_to=st.text_input("Email recipient (optional)", "")
        webhook_url=st.text_input("Webhook URL (optional)", "", help="Discord/Slack/Telegram/Pushover/ntfy, etc.")
        if st.button("Test Alerts"):
            if enable_sound: trigger_beep()
            sub="[Crypto Tracker] Test alert"; body="This is a test alert from the app."
            if email_to:
                ok, info=send_email_alert(sub, body, email_to); st.success("Test email sent") if ok else st.warning(info)
            if webhook_url:
                ok, info=post_webhook(webhook_url, {"title": sub, "lines": [body]})
                st.success("Test webhook sent") if ok else st.warning(f"Webhook error: {info}")

    with st.expander("Advanced", expanded=False):
        mode=st.radio("Data source mode", ["REST only", "WebSocket + REST (hybrid)"], index=0)
        chunk=st.slider("Coinbase WebSocket subscribe chunk", 2, 200, 10, 1)
        if st.button("Restart stream"):
            st.session_state["ws_alive"]=False; time.sleep(0.2); st.rerun()

# CSS/Audio & modal scaffolding
inject_css_scale(1.0)
audible_bridge()
inject_chart_modal()  # modal + top-scroll sync

# Quick Controls (minimal + sticky feel when near top)
st.markdown("### 🔧 Quick Controls")
col1, col2, col3, col4, col5 = st.columns([1.1, 1.2, 1.3, 1.0, 0.8])
with col1: st.write(f"**Sort TF:** {sort_tf}")
with col2: pct_thresh = st.slider("Min +% change", 0.1, 20.0, pct_thresh, 0.1, key="qc_pct")
with col3: min_quote  = st.number_input("Min Quote $", min_value=0.0, value=min_quote, step=100_000.0, format="%.0f", key="qc_qv")
with col4: gate_logic_all = st.radio("Gate logic", ["ALL","ANY"], index=0 if gate_logic_all else 1, horizontal=True, key="qc_logic")=="ALL"
with col5:
    if st.button("🔊 Test Alert (quick)"): 
        trigger_beep()
        if email_to:
            ok, info=send_email_alert("[Crypto Tracker] Test alert", "Quick test", email_to); st.success("Email OK") if ok else st.warning(info)

st.divider()

# Discover pairs
if use_watch and watchlist.strip():
    pairs=[p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs=list_products(effective_exchange, quote)
if "(coming soon)" in exchange:
    st.info("Selected exchange is coming soon; discovery disabled.")
pairs=[p for p in pairs if p.endswith(f"-{quote}")]
pairs=pairs[:max_pairs]
if not pairs:
    st.info("No pairs. Try a different Quote, uncheck Watchlist-only, or increase Max pairs."); st.stop()

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

# Build view
needed_tfs = sorted(set([sort_tf] + DEFAULT_TFS))
base=compute_view(
    effective_exchange, pairs, needed_tfs, sort_tf,
    rsi_len, macd_fast, macd_slow, macd_sig, atr_len
)
if base.empty:
    st.info("No data returned. Try fewer pairs or different Timeframes."); st.stop()

# ATH/ATL, recent-high, trend-break
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

# Display set (your order)
price_col=f"Price {sort_tf}" if f"Price {sort_tf}" in view.columns else "Last"
pct_col=f"% {sort_tf}"
pct_label=f"% change ({sort_tf})"
disp=view.copy()
disp = disp[["Pair"]].assign(
    **{
        "Price": view[price_col],
        pct_label: view[pct_col],
        "From ATH %": view["From ATH %"],
        "ATH date": view["ATH date"],
        "From ATL %": view["From ATL %"],
        "ATL date": view["ATL date"],
        "Trend broken?": view["Trend broken?"],
        "Broken since": view["Broken since"],
    }
)

# Sort by signed % (descending)
disp = disp.sort_values(pct_label, ascending=not sort_desc, na_position="last").reset_index(drop=True)
disp.insert(0, "#", disp.index + 1)

# Gate masks
view_idxed = view.set_index("Pair")
green_mask, yellow_mask = build_gate_mask(
    view_idxed, sort_tf,
    pct_thresh,
    use_quote, min_quote,
    use_base,  min_base,
    use_spike, vol_mult,
    gate_logic_all,
    use_trend, trend_required,
    use_rsi, rsi_min,
    use_macd, macd_hist_nonneg, macd_need_cross,
    use_atr, atrp_min
)
green_mask = green_mask.reindex(disp["Pair"].values).reset_index(drop=True)
yellow_mask = yellow_mask.reindex(disp["Pair"].values).reset_index(drop=True)

# ---------- Top‑10 panel (ALL gates) ----------
st.subheader("📌 Top‑10 (meets ALL enabled gates)")
top_now = disp.loc[green_mask].copy()
top_now = top_now.sort_values(pct_label, ascending=not sort_desc, na_position="last").head(10)
if top_now.empty:
    st.write("—")
    st.caption("Tip: lower +%, lower Quote $, disable Spike, or switch gate logic to ANY.")
else:
    render_html_table(top_now.reset_index(drop=True), pd.Series([True]*len(top_now)),
                      pd.Series([False]*len(top_now)), effective_exchange, sort_tf, table_id="mvTopTable")

st.subheader("📑 All pairs (ranked by % change)")
render_html_table(disp, green_mask, yellow_mask, effective_exchange, sort_tf, table_id="mvMainTable")

# Alerts
new_spikes=[]
if not top_now.empty:
    for _, r in top_now.iterrows():
        key=f"TOP10|{r['Pair']}|{sort_tf}|{round(float(r[pct_label]),2)}"
        if key not in st.session_state["last_alert_hashes"]:
            new_spikes.append((r["Pair"], float(r[pct_label])))
            st.session_state["last_alert_hashes"].add(key)

trend_triggers=[]
for _, r in disp.iterrows():
    tb=r["Trend broken?"]
    if tb in ("Yes ↑","Yes ↓"):
        tkey=f"TREND|{r['Pair']}|{tb}"
        if tkey not in st.session_state["trend_alerted"]:
            trend_triggers.append((r["Pair"], tb, r["Broken since"]))
            st.session_state["trend_alerted"].add(tkey)

if enable_sound and (new_spikes or trend_triggers): trigger_beep()
if (new_spikes or trend_triggers) and (email_to or webhook_url):
    lines=[]
    if new_spikes:
        lines.append(f"Top-10 entries on {sort_tf}:")
        for p, pct in new_spikes: lines.append(f" • {p}: {pct:+.2f}%")
    if trend_triggers:
        lines.append("Trend breaks:")
        for p, tb, since in trend_triggers: lines.append(f" • {p}: {tb} (since {since})")
    sub=f"[{effective_exchange}] Crypto Tracker alerts"
    if email_to:
        ok, info=send_email_alert(sub, "\n".join(lines), email_to); 
        if not ok: st.warning(info)
    if webhook_url:
        ok, info=post_webhook(webhook_url, {"title": sub, "lines": lines});
        if not ok: st.warning(f"Webhook error: {info}")

st.caption(f"Pairs: {len(disp)} • Exchange: {effective_exchange} • Quote: {quote} • Sort TF: {sort_tf} • "
           f"Gates: {'ALL' if gate_logic_all else 'ANY'} • Mode: {mode}")

