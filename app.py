# app.py — Coinbase Fast Movers — All-in-One (autorefresh fix)
# - Scans all Coinbase products (optional Quote/Base filters, Top-N by 24h volume)
# - Multi-timeframe % change using last N bars (global + per-TF overrides)
# - Volume spike confirmation + optional RSI gate + ATR-normalized spike
# - WebSocket hybrid for fresher last price (+ optional spread guard)
# - Top 10 movers panel (fast movers = green tint)
# - Alerts: Browser beep + Email + multiple Webhooks (Discord/Slack/Generic), caps & cooldowns
# - Quiet hours by timezone
# - Heatmap view, CSV export, durable logs / hashes across sessions
# - Autorefresh (streamlit-autorefresh or JS fallback) + diagnostics + secrets checker
#
# Run: streamlit run app.py

import os, json, time, math, threading, queue, ssl, base64, datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import smtplib
import streamlit as st

# ---------- optional autorefresh helper (FIX)
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False

# ---------- Optional: WebSocket client
WS_AVAILABLE = True
try:
    import websocket  # pip install websocket-client
except Exception:
    WS_AVAILABLE = False

# ---------- Page & global UI
st.set_page_config(page_title="Coinbase Fast Movers — All-in-One", layout="wide")
st.title("Coinbase Fast Movers — All‑in‑One Spike Scanner")

# ---------- Session state + durable paths
LOG_PATH = os.environ.get("FM_LOG_PATH", "/tmp/fast_movers_log.csv")
HASHES_PATH = os.environ.get("FM_HASHES_PATH", "/tmp/fast_movers_hashes.json")

def init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("last_ticks", {})          # product_id -> last trade price (float)
    ss.setdefault("last_bbo", {})            # product_id -> (bid, ask)
    ss.setdefault("last_alert_hashes", set())
    ss.setdefault("last_alert_time", {})     # (pair, tf) -> epoch seconds (cooldown)
    if os.path.exists(HASHES_PATH) and not ss["last_alert_hashes"]:
        try:
            with open(HASHES_PATH, "r") as f:
                ss["last_alert_hashes"] = set(json.load(f))
        except:
            pass
init_state()

# ---------- CSS font scaling
def inject_css_scale(scale: float):
    st.markdown(f"""
    <style>
      html {{ font-size: {scale}rem; }}
      .stDataFrame table {{ font-size: {scale}rem; }}
      .stMarkdown p, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{ font-size: {scale}rem; }}
      .small-muted {{ opacity: 0.7; font-size: 0.85em; }}
      .linklike a {{ text-decoration: none; }}
    </style>
    """, unsafe_allow_html=True)

# ---------- Real audible beep (no network)
def audible_bridge():
    st.markdown("""
    <script>
      let AC = window.AudioContext || window.webkitAudioContext;
      let ctx;
      function ensureCtx(){ if(!ctx){ ctx = new AC(); } }
      function beep(){
        ensureCtx();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = 880;
        gain.gain.setValueAtTime(0.0001, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.2, ctx.currentTime + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.15);
        osc.connect(gain).connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.16);
      }
      const tick = () => {
        if (localStorage.getItem('mustBeep') === '1') {
          try { beep(); } catch(e){}
          localStorage.setItem('mustBeep','0');
        }
        requestAnimationFrame(tick);
      };
      window.addEventListener('click', () => { try{ ensureCtx(); }catch(e){} }, {once:true});
      requestAnimationFrame(tick);
    </script>
    """, unsafe_allow_html=True)

def trigger_beep():
    st.markdown("<script>localStorage.setItem('mustBeep','1');</script>", unsafe_allow_html=True)

# ---------- Indicators
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(close, length=14):
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    roll_down = pd.Series(down, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100 / (1 + rs))

def macd(close, fast=12, slow=26, signal=9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def atr(df, length=14):
    high = df["high"].astype(float); low = df["low"].astype(float); close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

# ---------- Coinbase REST (cached) + helpers
CB_BASE = "https://api.exchange.coinbase.com"

TFS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "6h": 21600,
    "1d": 86400,
}

@st.cache_data(show_spinner=False, ttl=300)
def fetch_products_raw():
    url = f"{CB_BASE}/products"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def unique_quotes(products):
    return sorted({p.get("quote_currency") for p in products if p.get("quote_currency")})

@st.cache_data(show_spinner=False, ttl=300)
def list_products_filtered(quote_currency=None, base_filter=None):
    data = fetch_products_raw()
    out = []
    for p in data:
        if p.get("status") not in {"online", "online_trading"} and p.get("trading_disabled", False):
            continue
        if quote_currency and p.get("quote_currency") != quote_currency:
            continue
        if base_filter and p.get("base_currency") not in base_filter:
            continue
        out.append(p["id"])
    return sorted(set(out))

def _ttl_for_granularity(sec: int) -> int:
    return 15 if sec == 60 else 60 if sec == 300 else 120 if sec == 900 else 300 if sec == 3600 else 600 if sec == 21600 else 1800

def _fetch_candles_uncached(pair, granularity_sec):
    url = f"{CB_BASE}/products/{pair}/candles?granularity={granularity_sec}"
    for attempt in range(3):
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            arr = r.json()
            if not arr:
                return None
            df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
            df = df.sort_values("ts").reset_index(drop=True)
            return df
        if r.status_code in (429, 500, 502, 503):
            time.sleep(0.5 * (attempt + 1))
        else:
            break
    return None

def fetch_candles(pair, granularity_sec):
    ttl = _ttl_for_granularity(granularity_sec)
    @st.cache_data(show_spinner=False, ttl=ttl)
    def _cached(pair, granularity_sec):
        return _fetch_candles_uncached(pair, granularity_sec)
    return _cached(pair, granularity_sec)

@st.cache_data(show_spinner=False, ttl=300)
def fetch_product_stats(product_id: str):
    url = f"{CB_BASE}/products/{product_id}/stats"
    for attempt in range(3):
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503):
            time.sleep(0.4 * (attempt + 1))
        else:
            break
    return {}

def top_n_by_24h_volume_usd(product_ids, n=100):
    stats = []
    for pid in product_ids:
        s = fetch_product_stats(pid) or {}
        try:
            last = float(s.get("last")) if s.get("last") is not None else None
            vol_base = float(s.get("volume")) if s.get("volume") is not None else None
            if last is not None and vol_base is not None:
                stats.append((pid, last * vol_base))
        except:
            pass
    stats.sort(key=lambda x: x[1], reverse=True)
    return [pid for pid, _ in stats[:n]]

# ---------- WebSocket worker (optional)
def ws_worker(pairs, channel="ticker", endpoint="wss://ws-feed.exchange.coinbase.com"):
    ss = st.session_state
    try:
        ws = websocket.WebSocket()
        ws.connect(endpoint, timeout=10)
        sub = {"type":"subscribe","channels":[{"name":channel,"product_ids":pairs}]}
        ws.send(json.dumps(sub))
        ss["ws_alive"] = True
        while ss.get("ws_alive", False):
            try:
                msg = ws.recv()
                if not msg:
                    continue
                ss["ws_q"].put_nowait(("msg", time.time(), msg))
            except Exception:
                break
    except Exception as e:
        ss["ws_q"].put_nowait(("err", time.time(), str(e)))
    finally:
        ss["ws_alive"] = False

def drain_ws_queue():
    if not (st.session_state.get("ws_alive") and WS_AVAILABLE):
        return
    drained = 0
    while not st.session_state["ws_q"].empty() and drained < 5000:
        kind, ts_msg, payload = st.session_state["ws_q"].get_nowait()
        if kind == "msg":
            try:
                d = json.loads(payload)
                if d.get("type") == "ticker":
                    pid = d.get("product_id")
                    px = d.get("price")
                    bid = d.get("best_bid"); ask = d.get("best_ask")
                    if pid and px:
                        try: st.session_state["last_ticks"][pid] = float(px)
                        except: pass
                    if pid and bid and ask:
                        try: st.session_state["last_bbo"][pid] = (float(bid), float(ask))
                        except: pass
            except:
                pass
        drained += 1

# ---------- Alerts
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
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port", 465), context=ctx) as server:
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["sender"], recipient, msg.as_string())
        return True, "Email sent"
    except Exception as e:
        return False, f"Email error: {e}"

def post_webhook(url, title, lines):
    text = f"*{title}*\n" + "\n".join(lines)
    try:
        if "discord.com/api/webhooks" in url:
            payload = {"content": text}
        elif "hooks.slack.com" in url:
            payload = {"text": text}
        else:
            payload = {"title": title, "text": "\n".join(lines)}
        r = requests.post(url, json=payload, timeout=10)
        ok = 200 <= r.status_code < 300
        return ok, (r.text if not ok else "OK")
    except Exception as e:
        return False, str(e)

def fanout_webhooks(urls_csv, title, lines):
    errs = []; any_ok = False
    for url in [u.strip() for u in urls_csv.split(",") if u.strip()]:
        ok, info = post_webhook(url, title, lines)
        any_ok = any_ok or ok
        if not ok: errs.append(f"{url}: {info}")
    return any_ok, "; ".join(errs) if errs else "OK"

# ---------- Computation
def parse_bars_back_map(text: str):
    out = {}
    for part in text.split(","):
        part = part.strip()
        if not part or "=" not in part: continue
        tf, n = part.split("=", 1)
        tf = tf.strip()
        try:
            n = int(n.strip())
            if tf in TFS and n >= 1: out[tf] = n
        except:
            continue
    return out

def compute_view(pairs, timeframes, rsi_len, macd_fast, macd_slow, macd_sig,
                 bars_back=1, bars_back_map=None, ticks=None, atr_len=14):
    ticks = ticks or {}
    bars_back_map = bars_back_map or {}
    rows = []
    for pid in pairs:
        rec = {"Pair": pid}
        ok_any = False
        last_close = None
        for tf_name in timeframes:
            sec = TFS[tf_name]
            df = fetch_candles(pid, sec)
            n_back = int(bars_back_map.get(tf_name, bars_back))
            need = max(30, n_back + 2, atr_len + 2)
            if df is None or len(df) < need:
                for col in (f"% {tf_name}", f"Vol x {tf_name}", f"RSI {tf_name}", f"MACD {tf_name}", f"ATR {tf_name}"):
                    rec[col] = np.nan
                continue
            df = df.tail(400).copy()
            last_px = float(ticks.get(pid, df["close"].iloc[-1]))
            ref_idx = -1 - n_back
            ref_px = float(df["close"].iloc[ref_idx]) if len(df) > abs(ref_idx) else float(df["close"].iloc[0])
            pct = (last_px / ref_px - 1.0) * 100.0
            rec[f"% {tf_name}"] = pct
            last_close = last_px

            rsi_vals = rsi(df["close"], rsi_len)
            rec[f"RSI {tf_name}"] = float(rsi_vals.iloc[-1])

            m_line, s_line, hist = macd(df["close"], macd_fast, macd_slow, macd_sig)
            rec[f"MACD {tf_name}"] = float(m_line.iloc[-1] - s_line.iloc[-1])

            vol = df["volume"]; base = vol.rolling(20, min_periods=5).mean().iloc[-1]
            rec[f"Vol x {tf_name}"] = float(vol.iloc[-1] / (base + 1e-9))

            atr_vals = atr(df[["high","low","close"]], atr_len)
            rec[f"ATR {tf_name}"] = float(atr_vals.iloc[-1])

            ok_any = True
        rec["Last"] = last_close if ok_any else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)

def highlight_spikes(df, sort_tf, rsi_overbought, rsi_oversold,
                     vol_mult, spike_thresh, gate_by_rsi=False,
                     use_atr=False, atr_mult=2.0):
    df = df.copy()
    pt_col = f"% {sort_tf}"
    vs_col = f"Vol x {sort_tf}"
    rsi_col = f"RSI {sort_tf}"
    atr_col = f"ATR {sort_tf}"
    spike_mask = (df[pt_col].abs() >= spike_thresh) & (df[vs_col] >= vol_mult)
    if gate_by_rsi and rsi_col in df.columns:
        spike_mask &= ((df[rsi_col] >= rsi_overbought) | (df[rsi_col] <= rsi_oversold))
    if use_atr and atr_col in df.columns:
        atr_pct = (df[atr_col] / (df["Last"].replace(0, np.nan))) * 100.0
        spike_mask &= (df[pt_col].abs() >= (atr_pct * atr_mult))

    def _row_style(r):
        styles = []
        for c in df.columns:
            base = ""
            if spike_mask.loc[r.name]:
                base += "background-color: rgba(0,255

