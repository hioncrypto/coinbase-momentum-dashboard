# app.py — Crypto Tracker (sellable build, fixed)
# - Fixed: Coinbase fetch_candles SyntaxError (no one-line "arr=r.json(); if not arr")
# - Semi-restrictive defaults (shows results, not noisy)
# - Collapse-all button for sidebar expanders
# - Top scrollbar fully synced with table
# - Click headers to sort ASC/DESC (client-side)
# - Green row = all gates pass; Yellow row = partial pass (true yellow)
# - Pair hover + in-app TradingView modal (iframe, CSP-safe)
# - Audible (Arm/Test), Email, Webhook alerts
# - Inline UI hints AND code comments on how to loosen gates

import json, time, threading, queue, ssl, smtplib, datetime as dt, html, uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import requests
import streamlit as st

# =========================
#  GLOBAL / WS STATE
# =========================
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
    ss.setdefault("last_alert_hashes", set())
    ss.setdefault("trend_alerted", set())
    ss.setdefault("diag", {})
    ss.setdefault("expander_keys", {})
init_state()

APP_VERSION = "v1.5.1"

# =========================
#  CSS / AUDIO
# =========================
def inject_css(display_wrap: bool, col_min_px: int, font_scale: float):
    nowrap = "normal" if display_wrap else "nowrap"
    st.markdown(f"""
    <style>
      html, body {{ font-size: {font_scale}rem; }}
      :root {{ --col-min: {col_min_px}px; }}

      .hint {{ color:#9aa3ab; font-size:0.92em; }}

      .tv-modal-backdrop {{
        position: fixed; inset: 0; background: rgba(0,0,0,0.65);
        display: none; align-items: center; justify-content: center; z-index: 99999;
      }}
      .tv-modal {{
        width: min(96vw, 1200px); height: min(85vh, 820px);
        background: var(--background-color); border-radius: 12px;
        box-shadow: 0 8px 28px rgba(0,0,0,0.45); overflow: hidden; position: relative;
      }}
      .tv-modal-header {{
        display:flex; align-items:center; justify-content:space-between;
        padding: 8px 12px; border-bottom: 1px solid rgba(255,255,255,0.08);
      }}
      .tv-modal-title {{ font-weight: 700; font-size: 1.05rem; }}
      .tv-close {{ cursor:pointer; border:0; background:transparent; font-size:1.3rem; opacity:.8; }}
      .tv-modal-body {{ width:100%; height:calc(100% - 44px); }}

      .top-scrollbar {{ width:100%; overflow-x:auto; overflow-y:hidden; height:16px; }}
      .top-scrollbar .spacer {{ height:1px; }}

      .row-green  {{ background: rgba(0,255,0,0.20); font-weight:600; }}
      .row-yellow {{ background: rgba(255,255,0,0.35); font-weight:600; }}

      table.mv-table {{ width: max(1200px, 100%); border-collapse: collapse; table-layout: fixed; }}
      table.mv-table th, table.mv-table td {{
        padding: 6px 10px; border-bottom: 1px solid rgba(255,255,255,0.06);
        white-space: {nowrap}; overflow: hidden; text-overflow: ellipsis;
        vertical-align: middle; min-width: var(--col-min);
      }}
      table.mv-table th {{
        position: sticky; top: 0; background: var(--background-color); z-index: 2; cursor: pointer;
      }}
      table.mv-table th .sort-ind {{ opacity:.6; margin-left:6px; }}

      a.mv-pair {{ color: var(--text-color); text-decoration: underline; cursor: pointer; }}
      a.mv-pair:hover::after {{ content: "  (click to view chart)"; opacity:.55; font-size:.92em; }}
    </style>
    """, unsafe_allow_html=True)

def audible_js():
    st.markdown("""
    <audio id="mv_beep" preload="auto">
      <source src="data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAAAAP8AAP//AAD//wAA//8AAP//AAD//wAA" type="audio/wav">
    </audio>
    <script>
      window._mv_audio_ctx = window._mv_audio_ctx || null;
      function mvEnsureCtx() {
        if (!window._mv_audio_ctx) {
          try { window._mv_audio_ctx = new (window.AudioContext || window.webkitAudioContext)(); }
          catch(e) { window._mv_audio_ctx = null; }
        }
        if (window._mv_audio_ctx && window._mv_audio_ctx.state === 'suspended') { window._mv_audio_ctx.resume(); }
      }
      function mvBeep() {
        try {
          mvEnsureCtx();
          if (window._mv_audio_ctx) {
            const ctx = window._mv_audio_ctx;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine'; osc.frequency.value = 1000;
            osc.connect(gain); gain.connect(ctx.destination);
            const now = ctx.currentTime;
            gain.gain.setValueAtTime(0.0001, now);
            gain.gain.exponentialRampToValueAtTime(0.25, now + 0.01);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.20);
            osc.start(now); osc.stop(now + 0.21);
            return;
          }
        } catch(e) {}
        const a = document.getElementById('mv_beep'); a.currentTime = 0; a.volume = 1.0; a.play().catch(()=>{});
      }
      const tick = () => {
        if (localStorage.getItem('mustBeep') === '1') { mvBeep(); localStorage.setItem('mustBeep','0'); }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      window.addEventListener('click', mvEnsureCtx, { once:true });
      window.mvArmAudio = mvEnsureCtx;
    </script>
    """, unsafe_allow_html=True)

def trigger_beep():
    st.markdown("<script>localStorage.setItem('mustBeep','1');</script>", unsafe_allow_html=True)

# =========================
#  INDICATORS
# =========================
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    d = series.diff(); up = d.clip(lower=0); down = (-d).clip(lower=0)
    rs = up.ewm(alpha=1/length, adjust=False).mean() / (down.ewm(alpha=1/length, adjust=False).mean() + 1e-12)
    return 100 - (100/(1+rs))

def macd(series: pd.Series, fast=12, slow=26, signal=9):
    m = ema(series, fast) - ema(series, slow)
    s = ema(m, signal)
    return m, s, m-s

def atr(df: pd.DataFrame, length=14):
    h,l,c = df["high"], df["low"], df["close"]; pc = c.shift(1)
    tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

# =========================
#  EXCHANGES / PRODUCTS
# =========================
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
        r = requests.get(f"{CB_BASE}/products", timeout=15)
        r.raise_for_status()
        data = r.json()
        return sorted([f"{p['base_currency']}-{p['quote_currency']}" for p in data if p.get("quote_currency")==quote])
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=20)
        r.raise_for_status()
        info = r.json(); out=[]
        for s in info.get("symbols", []):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote: out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange=="Coinbase": return coinbase_list_products(quote)
    if exchange=="Binance":  return binance_list_products(quote)
    return []

# =========================
#  CANDLES / RESAMPLING
# =========================
def fetch_candles(exchange: str, pair_dash: str, granularity_sec: int,
                  start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    if exchange=="Coinbase":
        url = f"{CB_BASE}/products/{pair_dash}/candles?granularity={granularity_sec}"
        params={}
        if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
        if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code != 200:
                return None
            arr = r.json()
            if not arr:
                return None
            df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
            return df.sort_values("ts").reset_index(drop=True)
        except Exception:
            return None
    elif exchange=="Binance":
        base, quote = pair_dash.split("-"); symbol=f"{base}{quote}"
        interval=NATIVE_BINANCE.get(granularity_sec)
        if not interval: return None
        params={"symbol":symbol, "interval":interval, "limit":1000}
        if start: params["startTime"]=int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
        if end:   params["endTime"]=int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
        try:
            r=requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=20)
            if r.status_code!=200: return None
            rows=[]
            for a in r.json():
                rows.append({"ts":pd.to_datetime(a[0],unit="ms",utc=True),
                             "open":float(a[1]),"high":float(a[2]),
                             "low":float(a[3]),"close":float(a[4]),
                             "volume":float(a[5]),
                             "quote_volume": float(a[7]) if len(a)>7 else float(a[5])*float(a[4])})
            return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
        except Exception:
            return None
    return None

def resample_ohlcv(df: pd.DataFrame, target_sec: int) -> Optional[pd.DataFrame]:
    if df is None or df.empty: return None
    d=df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    if "quote_volume" in df.columns: agg["quote_volume"]="sum"
    out=d.resample(f"{target_sec}s", label="right", closed="right").agg(agg).dropna()
    return out.reset_index()

def get_df_for_tf(exchange: str, pair: str, tf: str,
                  cache_1m: Dict[str, pd.DataFrame], cache_1h: Dict[str, pd.DataFrame]) -> Optional[pd.DataFrame]:
    sec=ALL_TFS[tf]
    is_native = sec in (NATIVE_BINANCE if exchange=="Binance" else NATIVE_COINBASE)
    if is_native: return fetch_candles(exchange, pair, sec)
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

# =========================
#  HISTORY / ATH-ATL
# =========================
@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":   amount=min(max(1,amount),72);  gran=3600;  start_cutoff=end-dt.timedelta(hours=amount)
    elif basis=="Daily":  amount=min(max(1,amount),365); gran=86400; start_cutoff=end-dt.timedelta(days=amount)
    else:                 amount=min(max(1,amount),52);  gran=86400; start_cutoff=end-dt.timedelta(weeks=amount)
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
    if "quote_volume" not in hist.columns: hist["quote_volume"]=hist["close"]*hist["volume"]
    return hist

def ath_atl_info(hist: pd.DataFrame) -> dict:
    last=float(hist["close"].iloc[-1])
    i_ath=int(hist["high"].idxmax()); i_atl=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[i_ath]); d_ath=pd.to_datetime(hist["ts"].iloc[i_ath]).date().isoformat()
    atl=float(hist["low"].iloc[i_atl]);  d_atl=pd.to_datetime(hist["ts"].iloc[i_atl]).date().isoformat()
    return {"From ATH %": (last/ath-1)*100 if ath>0 else np.nan, "ATH date": d_ath,
            "From ATL %": (last/atl-1)*100 if atl>0 else np.nan, "ATL date": d_atl}

# =========================
#  PIVOTS / TREND
# =========================
def find_pivots(close: pd.Series, span=3):
    n=len(close); highs=[]; lows=[]; v=close.values
    for i in range(span, n-span):
        if v[i]>v[i-span:i].max() and v[i]>v[i+1:i+1+span].max(): highs.append(i)
        if v[i]<v[i-span:i].min() and v[i]<v[i+1:i+1+span].min(): lows.append(i)
    return pd.Index(highs), pd.Index(lows)

def recent_high_metrics(df: pd.DataFrame, span=3):
    if df is None or df.empty or len(df)<(span*2+5): return np.nan, "—"
    highs,_=find_pivots(df["close"], span); 
    if len(highs)==0: return np.nan, "—"
    idx=int(highs[-1]); level=float(df["close"].iloc[idx])
    last=float(df["close"].iloc[-1]); last_ts=pd.to_datetime(df["ts"].iloc[-1])
    cross=None
    for j in range(idx+1, len(df)):
        if float(df["close"].iloc[j]) < level: cross=j; break
    if cross is None: return max((last/level-1)*100, 0.0), "—"
    dur=(last_ts - pd.to_datetime(df["ts"].iloc[cross])).total_seconds()
    return max((last/level-1)*100, 0.0), pretty_duration(dur)

def trend_breakout_info(df: pd.DataFrame, span=3):
    if df is None or df.empty or len(df)<(span*2+5): return "—","—"
    highs,lows=find_pivots(df["close"], span)
    if len(highs)==0 and len(lows)==0: return "No","—"
    last=float(df["close"].iloc[-1]); last_ts=pd.to_datetime(df["ts"].iloc[-1])
    if len(highs):
        hi=int(highs[-1]); level=float(df["close"].iloc[hi])
        if last>level:
            cross=None
            for j in range(hi+1,len(df)):
                if float(df["close"].iloc[j])>level: cross=j; break
            if cross is not None:
                dur=(last_ts - pd.to_datetime(df["ts"].iloc[cross])).total_seconds()
                return "Yes ↑", pretty_duration(dur)
    if len(lows):
        lo=int(lows[-1]); level=float(df["close"].iloc[lo])
        if last<level:
            cross=None
            for j in range(lo+1,len(df)):
                if float(df["close"].iloc[j])<level: cross=j; break
            if cross is not None:
                dur=(last_ts - pd.to_datetime(df["ts"].iloc[cross])).total_seconds()
                return "Yes ↓", pretty_duration(dur)
    return "No","—"

def pretty_duration(sec):
    if sec is None or np.isnan(sec): return "—"
    sec=int(sec); d,rem=divmod(sec,86400); h,rem=divmod(rem,3600); m,_=divmod(rem,60)
    out=[]; 
    if d: out.append(f"{d}d")
    if h: out.append(f"{h}h")
    if m and not d: out.append(f"{m}m")
    return " ".join(out) if out else "0m"

# =========================
#  ALERTS
# =========================
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
        r=requests.post(url, json=payload, timeout=10); ok=(200<=r.status_code<300)
        return ok, (r.text if not ok else "OK")
    except Exception as e:
        return False, str(e)

# =========================
#  WEBSOCKET (Coinbase)
# =========================
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

# =========================
#  CORE VIEW
# =========================
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
            if "quote_volume" not in df.columns: df["quote_volume"]=df["close"]*df["volume"]

            last_close=float(df["close"].iloc[-1]); first_close=float(df["close"].iloc[0])
            rec[f"% {tf}"]=(last_close/first_close - 1.0)*100.0
            rec[f"Vol x {tf}"]=float(df["volume"].iloc[-1] / (df["volume"].rolling(20).mean().iloc[-1] + 1e-9))
            rec[f"Price {tf}"]=last_close

            if tf==sort_tf:
                rs=rsi(df["close"], rsi_len); rec[f"RSI {tf}"]=float(rs.iloc[-1])
                m,s,h=macd(df["close"], macd_fast, macd_slow, macd_sig); rec[f"MACDh {tf}"]=float(h.iloc[-1])
                cross=False
                for i in range(1, min(4, len(m))):
                    if (m.iloc[-i-1] <= s.iloc[-i-1]) and (m.iloc[-i] > s.iloc[-i]): cross=True; break
                rec[f"MACDcross {tf}"]=bool(cross)
                a=atr(df, atr_len); rec[f"ATR% {tf}"]=float((a.iloc[-1]/(df["close"].iloc[-1]+1e-12))*100.0)
                rec[f"QuoteVol {tf}"]=float(df["quote_volume"].iloc[-1]); rec[f"BaseVol {tf}"]=float(df["volume"].iloc[-1])
        rec["Last"]=last_close if last_close is not None else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)

# =========================
#  GATE MASKS
# =========================
def build_gate_mask(view_idxed: pd.DataFrame, sort_tf: str,
                    pct_thresh: float,
                    use_quote: bool, min_quote: float,
                    use_base: bool,  min_base: float,
                    use_spike: bool, vol_mult: float,
                    gate_logic_all: bool,
                    use_trend: bool, trend_required: str,
                    use_rsi: bool, rsi_min: float,
                    use_macd: bool, macd_hist_nonneg: bool, macd_need_cross: bool,
                    use_atr: bool, atrp_min: float):
    # 💡 Too restrictive? Lower pct_thresh / min_quote / min_base / vol_mult,
    #    disable extra gates (RSI/MACD/ATR) or switch logic to ANY.
    def col(name): return view_idxed.get(name)

    mlist=[]
    m_pct=(col(f"% {sort_tf}").fillna(-1) >= pct_thresh); mlist.append(m_pct)
    if use_quote: mlist.append((col(f"QuoteVol {sort_tf}").fillna(0) >= min_quote))
    if use_base:  mlist.append((col(f"BaseVol {sort_tf}").fillna(0)  >= min_base))
    if use_spike: mlist.append((col(f"Vol x {sort_tf}").fillna(0)   >= vol_mult))
    if use_trend:
        tb=col("Trend broken?")
        if trend_required=="Any": m_trend=tb.isin(["Yes ↑","Yes ↓"])
        elif trend_required=="Breakout ↑": m_trend=tb.eq("Yes ↑")
        else: m_trend=tb.eq("Yes ↓")
        mlist.append(m_trend.fillna(False))
    if use_rsi:  mlist.append((col(f"RSI {sort_tf}").fillna(0) >= rsi_min))
    if use_macd:
        m=pd.Series(True, index=view_idxed.index)
        if macd_hist_nonneg: m = m & (col(f"MACDh {sort_tf}").fillna(-1) >= 0)
        if macd_need_cross:  m = m &  col(f"MACDcross {sort_tf}").fillna(False)
        mlist.append(m)
    if use_atr:  mlist.append((col(f"ATR% {sort_tf}").fillna(0) >= atrp_min))

    if not mlist:
        false=pd.Series(False, index=view_idxed.index)
        return false,false

    m_all=mlist[0].copy(); m_any=mlist[0].copy()
    for m in mlist[1:]: m_all = m_all & m; m_any = m_any | m
    green = m_all if gate_logic_all else m_any
    yellow = (~green) & m_any
    return green, yellow

# =========================
#  TV MODAL + TABLE (TOP SCROLL FIXED)
# =========================
def tv_symbol(exchange: str, pair: str) -> Optional[str]:
    base, quote = pair.split("-")
    if exchange=="Coinbase":
        tvq={"USDC":"USD","BUSD":"USD"}.get(quote, quote)
        return f"COINBASE:{base}{tvq}"
    if exchange=="Binance":
        tvq={"BUSD":"USDT"}.get(quote, quote)
        return f"BINANCE:{base}{tvq}"
    return None

def tv_interval(tf: str) -> str:
    return {"1m":"1","5m":"5","15m":"15","30m":"30","1h":"60","4h":"240","6h":"360","12h":"720","1d":"D","1w":"W"}.get(tf,"60")

def inject_chart_modal_and_helpers():
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
        document.getElementById('mv-tv-backdrop').style.display='flex';
        const modal=document.getElementById('mv-tv-modal'); modal.style.display='block';
        document.getElementById('mv-tv-title').textContent = title || symbol;
        const iframe=document.getElementById('mv-tv-iframe');
        const p=new URLSearchParams({symbol, interval, theme:'dark', style:'1', timezone:'Etc/UTC',
                                     hide_top_toolbar:'0', hide_side_toolbar:'0',
                                     allow_symbol_change:'0', withdateranges:'1', details:'1',
                                     studies:'', hideideas:'1', locale:'en'});
        iframe.src='https://s.tradingview.com/widgetembed/?'+p.toString();
        document.onkeydown=(e)=>{ if(e.key==='Escape') mvCloseChart(); };
      }
      function mvCloseChart(){
        document.getElementById('mv-tv-backdrop').style.display='none';
        const modal=document.getElementById('mv-tv-modal'); modal.style.display='none';
        const iframe=document.getElementById('mv-tv-iframe'); iframe.src='about:blank';
        document.onkeydown=null;
      }

      function mvMakeSortable(tableId){
        const tbl=document.getElementById(tableId); if(!tbl) return;
        const thead=tbl.querySelector('thead'); const tbody=tbl.querySelector('tbody');
        if(!thead || !tbody) return;
        const ths=[...thead.querySelectorAll('th')];
        ths.forEach((th, idx)=>{
          th.addEventListener('click', ()=>{
            const asc = !(th.dataset.asc === 'true');
            ths.forEach(t=>{ t.dataset.asc=''; const s=t.querySelector('.sort-ind'); if(s) s.textContent=''; });
            th.dataset.asc = asc ? 'true':'false';
            const rows=[...tbody.querySelectorAll('tr')];
            const parseVal=(td)=>{
              const t=td.textContent.trim().replace('%','').replace('$','').replaceAll(',','');
              const n=parseFloat(t);
              return isNaN(n) ? t.toLowerCase() : n;
            };
            rows.sort((a,b)=>{
              const va=parseVal(a.children[idx]); const vb=parseVal(b.children[idx]);
              if(va<vb) return asc?-1:1;
              if(va>vb) return asc?1:-1;
              return 0;
            });
            rows.forEach(r=>tbody.appendChild(r));
            const ind=th.querySelector('.sort-ind') || Object.assign(document.createElement('span'),{className:'sort-ind'});
            if(!th.querySelector('.sort-ind')) th.appendChild(ind);
            ind.textContent = asc ? '▲' : '▼';
          });
        });
      }

      // FIXED: size spacer from table.scrollWidth; sync both directions
      function mvInitTopScroll(topId, wrapId, tableId){
        const top=document.getElementById(topId);
        const wrap=document.getElementById(wrapId);
        const tbl=document.getElementById(tableId);
        if(!top || !wrap || !tbl) return;

        function size(){
          const w = tbl.scrollWidth;
          const sp = top.querySelector('.spacer');
          if(sp) sp.style.width = Math.max(w, wrap.clientWidth) + 'px';
        }
        size(); setTimeout(size, 120); setTimeout(size, 500);
        new ResizeObserver(size).observe(wrap);
        new ResizeObserver(size).observe(tbl);

        top.addEventListener('scroll', ()=>{ wrap.scrollLeft = top.scrollLeft; });
        wrap.addEventListener('scroll', ()=>{ top.scrollLeft = wrap.scrollLeft; });
      }
      window.mvMakeSortable = mvMakeSortable;
      window.mvInitTopScroll = mvInitTopScroll;
    </script>
    """, unsafe_allow_html=True)

def render_html_table(df: pd.DataFrame, green_mask: pd.Series, yellow_mask: pd.Series,
                      exchange: str, sort_tf: str, table_key: str):
    wrap_id = f"{table_key}_wrap_{uuid.uuid4().hex[:6]}"
    table_id = f"{table_key}_tbl_{uuid.uuid4().hex[:6]}"
    top_id   = f"{table_key}_top_{uuid.uuid4().hex[:6]}"

    cols = list(df.columns)
    thead = "<tr>" + "".join(f"<th>{html.escape(c)} <span class='sort-ind'></span></th>" for c in cols) + "</tr>"

    rows=[]
    for i, (_, row) in enumerate(df.iterrows()):
        pair = str(row["Pair"])
        sym  = tv_symbol(exchange, pair) or ""
        interval = tv_interval(sort_tf)
        title = f"{pair} • {sort_tf}"
        pair_html = f'<a class="mv-pair" title="Click to view chart" href="#" onclick="mvOpenChart(\'{sym}\', \'{interval}\', \'{html.escape(title)}\');return false;">{html.escape(pair)}</a>'
        cls = "row-green" if bool(green_mask.iloc[i]) else ("row-yellow" if bool(yellow_mask.iloc[i]) else "")
        tds=[]
        for c in cols:
            if c=="Pair":
                tds.append(f"<td>{pair_html}</td>")
            else:
                v=row[c]
                if isinstance(v, float):
                    tds.append(f"<td>{v:.6g}</td>")
                else:
                    tds.append(f"<td>{html.escape(str(v))}</td>")
        rows.append(f'<tr class="{cls}">'+"".join(tds)+"</tr>")

    html_block = f"""
    <div id="{top_id}" class="top-scrollbar"><div class="spacer"></div></div>
    <div id="{wrap_id}" style="overflow-x:auto; width:100%;">
      <table class="mv-table" id="{table_id}">
        <thead>{thead}</thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
    <script>
      mvMakeSortable("{table_id}");
      mvInitTopScroll("{top_id}", "{wrap_id}", "{table_id}");
    </script>
    """
    st.markdown(html_block, unsafe_allow_html=True)

# =========================
#  UI
# =========================
st.set_page_config(page_title="Crypto Tracker", layout="wide")
st.title(f"Crypto Tracker — {APP_VERSION}")

with st.sidebar:
    colA, colB = st.columns([1.2, 1])
    with colA:
        if st.button("Collapse all open menu tabs"):
            st.session_state["collapse_all"] = True
            st.rerun()
    with colB:
        st.caption("Quick tidy")

with st.sidebar:
    exp_market = st.expander("Market", expanded=not st.session_state.get("collapse_all", False))
    with exp_market:
        exchange=st.selectbox("Exchange", EXCHANGES, index=0, help="💡 Use Coinbase or Binance now; others are 'coming soon'.")
        effective_exchange="Coinbase" if "(coming soon)" in exchange else exchange
        if "(coming soon)" in exchange: st.info("This exchange is coming soon. Please use Coinbase or Binance for now.")
        quote=st.selectbox("Quote currency", QUOTES, index=0)
        use_watch=st.checkbox("Use watchlist only", value=False)
        watchlist=st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
        max_pairs=st.slider("Max pairs", 10, 1000, 200, 10)

with st.sidebar:
    exp_tf = st.expander("Timeframes", expanded=not st.session_state.get("collapse_all", False))
    with exp_tf:
        pick_tfs=st.multiselect("Select timeframes", DEFAULT_TFS + ["1w"], default=DEFAULT_TFS,
                                help="💡 Choose windows to calculate % change. 1w is resampled from daily.")
        default_idx = pick_tfs.index("1h") if "1h" in pick_tfs else 0
        sort_tf=st.selectbox("Primary sort timeframe", pick_tfs, index=default_idx,
                             help="💡 This timeframe drives % change ranking and most gates.")
        sort_desc=st.checkbox("Sort descending (largest first)", value=True)

with st.sidebar:
    exp_gates = st.expander("Gates", expanded=not st.session_state.get("collapse_all", False))
    with exp_gates:
        gate_logic_all = st.radio("Gate logic for enabled filters", ["ALL", "ANY"], index=0) == "ALL"
        st.caption("💡 If nothing shows up, switch to ANY or loosen thresholds below.")

        st.markdown("**Price gate**")
        pct_thresh=st.slider("Min +% change (Sort TF)", 0.0, 20.0, 1.0, 0.1,
                             help="💡 Lower this % if no pairs are appearing. Set to 0 to disable.")
        st.divider()

        st.markdown("**Volume gates**")
        colv1, colv2, colv3 = st.columns(3)
        with colv1:
            use_quote = st.checkbox("Use Quote $", value=True, help="💡 Uncheck to disable this gate.")
            min_quote = st.number_input("Min Quote $", min_value=0.0, value=500_000.0, step=50_000.0, format="%.0f",
                                        help="💡 Lower this $ to include smaller names.")
        with colv2:
            use_base  = st.checkbox("Use Base units", value=False, help="💡 Rarely needed; uncheck to disable.")
            min_base  = st.number_input("Min Base units", min_value=0.0, value=0.0, step=100.0, format="%.0f",
                                        help="💡 Lower this to include more pairs.")
        with colv3:
            use_spike = st.checkbox("Use Volume spike (SMA×)", value=True, help="💡 Uncheck to disable spike filter.")
            vol_mult  = st.slider("Min SMA×", 1.0, 10.0, 1.2, 0.1,
                                  help="💡 Reduce from 1.5× → 1.1× if too few pass.")
        st.divider()

        st.markdown("**Trend gate**")
        use_trend = st.checkbox("Require trend break", value=False, help="💡 Turn off to include names that haven't broken trend yet.")
        trend_required = st.selectbox("Break type", ["Any","Breakout ↑","Breakdown ↓"], index=0,
                                      help="💡 'Any' is least restrictive.")
        st.divider()

        st.markdown("**Indicator gates (optional)**")
        colind1, colind2, colind3 = st.columns(3)
        with colind1:
            use_rsi = st.checkbox("RSI ≥", value=False, help="💡 Uncheck to disable.")
            rsi_min = st.slider("RSI min", 0, 100, 55, 1, help="💡 Lower to include more.")
        with colind2:
            use_macd = st.checkbox("MACD", value=False, help="💡 Uncheck to disable MACD gate.")
            macd_hist_nonneg = st.checkbox("Hist ≥ 0", value=True, help="💡 Makes MACD gate stricter.")
            macd_need_cross  = st.checkbox("Fresh bull cross (≤3 bars)", value=False, help="💡 Very restrictive when on.")
        with colind3:
            use_atr = st.checkbox("ATR% ≥", value=False, help="💡 Uncheck to disable ATR gate.")
            atrp_min = st.slider("ATR% min", 0.0, 10.0, 0.5, 0.1, help="💡 Lower to include more.")

with st.sidebar:
    exp_hist = st.expander("History depth", expanded=not st.session_state.get("collapse_all", False))
    with exp_hist:
        basis=st.selectbox("Basis for ATH/ATL & recent-high", ["Hourly","Daily","Weekly"], index=1,
                           help="💡 Shorter windows run faster; extend if ATH/ATL dates look too recent.")
        if basis=="Hourly":
            amount=st.slider("Hours to fetch (≤72)", 1, 72, 24, 1)
        elif basis=="Daily":
            amount=st.slider("Days to fetch (≤365)", 1, 365, 90, 1)
        else:
            amount=st.slider("Weeks to fetch (≤52)", 1, 52, 12, 1)

with st.sidebar:
    exp_len = st.expander("Trend/Indicator lengths", expanded=not st.session_state.get("collapse_all", False))
    with exp_len:
        pivot_span=st.slider("Pivot lookback span (bars)", 2, 10, 5, 1,
                             help="💡 Increase to smooth noise; decrease for earlier (noisier) signals.")
        rsi_len=st.slider("RSI length", 5, 50, 14, 1)
        macd_fast=st.slider("MACD fast", 3, 50, 12, 1)
        macd_slow=st.slider("MACD slow", 5, 100, 26, 1)
        macd_sig =st.slider("MACD signal", 3, 50, 9, 1)
        atr_len =st.slider("ATR length", 5, 50, 14, 1)

with st.sidebar:
    exp_disp = st.expander("Display", expanded=not st.session_state.get("collapse_all", False))
    with exp_disp:
        display_wrap = st.checkbox("Wrap text (show full cell text)", value=False)
        col_min_px   = st.slider("Column min width (px)", 120, 360, 160, 10)
        font_scale   = st.slider("Font scale", 0.8, 1.6, 1.0, 0.05)

with st.sidebar:
    exp_notif = st.expander("Notifications", expanded=not st.session_state.get("collapse_all", False))
    with exp_notif:
        enable_sound=st.checkbox("Audible chime (browser)", value=True)
        st.caption("Click **Arm audio** once if your browser blocks sound. 💡 If no alerts, loosen gates above.")
        colA, colB = st.columns([1, 1.4])
        with colA:
            if st.button("🔊 Arm audio"): st.markdown("<script>window.mvArmAudio && window.mvArmAudio();</script>", unsafe_allow_html=True)
        with colB:
            if st.button("Test beep"): st.markdown("<script>localStorage.setItem('mustBeep','1');</script>", unsafe_allow_html=True)
        email_to=st.text_input("Email recipient (optional)", "")
        webhook_url=st.text_input("Webhook URL (optional)", "", help="Discord/Slack/Telegram/Pushover/ntfy, etc.")

with st.sidebar:
    exp_adv = st.expander("Advanced", expanded=not st.session_state.get("collapse_all", False))
    with exp_adv:
        mode=st.radio("Data source mode", ["REST only", "WebSocket + REST (hybrid)"], index=0)
        chunk=st.slider("Coinbase WebSocket subscribe chunk", 2, 200, 10, 1)
        if st.button("Restart stream"): st.session_state["ws_alive"]=False; time.sleep(0.2); st.rerun()

st.session_state["collapse_all"] = False

inject_css(display_wrap, col_min_px, font_scale)
audible_js()
inject_chart_modal_and_helpers()

st.markdown("### 🔧 Quick Controls")
col1, col2, col3, col4 = st.columns([1.1, 1.2, 1.3, 1.0])
with col1: st.write(f"**Sort TF:** {sort_tf}")
with col2: pct_thresh = st.slider("Min +% change", 0.0, 20.0, pct_thresh, 0.1, key="qc_pct")
with col3: min_quote  = st.number_input("Min Quote $", min_value=0.0, value=min_quote, step=50_000.0, format="%.0f", key="qc_qv")
with col4:
    if st.button("🔔 Test alert"):
        if enable_sound: trigger_beep()
        if email_to:
            ok, info=send_email_alert("[Crypto Tracker] Test alert", "Quick test", email_to); st.success("Email OK") if ok else st.warning(info)
        if webhook_url:
            ok, info=post_webhook(webhook_url, {"title":"[Crypto Tracker] Test alert","lines":["Quick test"]}); st.success("Webhook OK") if ok else st.warning(f"Webhook error: {info}")
st.divider()

# Discover pairs
if use_watch and watchlist.strip():
    pairs=[p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs=list_products(effective_exchange, quote)
if "(coming soon)" in exchange: st.info("Selected exchange is coming soon; discovery disabled.")
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
base=compute_view(effective_exchange, pairs, needed_tfs, sort_tf, rsi_len, macd_fast, macd_slow, macd_sig, atr_len)
if base.empty:
    st.info("No data returned. Try fewer pairs or different Timeframes."); st.stop()

# Enrich with ATH/ATL + trend/recent-high
def recent_high_metrics_safe(df_prices: pd.DataFrame, span: int):
    try:
        return recent_high_metrics(df_prices, span)
    except Exception:
        return np.nan, "—"

extras=[]
for pid in pairs:
    h=get_hist(effective_exchange, pid, basis, amount)
    if h is not None and len(h)>=10: info=ath_atl_info(h)
    else: info={"From ATH %": np.nan, "ATH date":"—", "From ATL %": np.nan, "ATL date":"—"}
    dft=get_df_for_tf(effective_exchange, pid, sort_tf, {}, {})
    if dft is not None and len(dft)>=max(50, pivot_span*4+10):
        pct_since_high, since_high = recent_high_metrics_safe(dft[["ts","close"]], span=pivot_span)
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

# Display table
price_col=f"Price {sort_tf}" if f"Price {sort_tf}" in view.columns else "Last"
pct_col=f"% {sort_tf}"; pct_label=f"% change ({sort_tf})"
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
disp = disp.sort_values(pct_label, ascending=not sort_desc, na_position="last").reset_index(drop=True)
disp.insert(0, "#", disp.index + 1)

# Gates
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

# Top‑10 (ALL gates)
st.subheader("📌 Top‑10 (meets ALL enabled gates)")
top_now = disp.loc[green_mask].copy()
top_now = top_now.sort_values(pct_label, ascending=not sort_desc, na_position="last").head(10)
if top_now.empty:
    st.write("—"); st.caption("💡 Nothing? Lower +%, lower Quote $, disable Spike, or switch logic to ANY.")
else:
    render_html_table(top_now.reset_index(drop=True), pd.Series([True]*len(top_now)),
                      pd.Series([False]*len(top_now)), effective_exchange, sort_tf, table_key="top")

# All pairs
st.subheader("📑 All pairs (ranked by % change)")
render_html_table(disp, green_mask, yellow_mask, effective_exchange, sort_tf, table_key="main")

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
