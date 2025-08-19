# app.py — Coinbase Movers (Multi-Timeframe) with REST/WebSocket hybrid,
# US time zones, font scaling, audible + remote alerts, Top Spikes panel,
# spike "ALL must pass" gates, and test-alert button.

import os, json, time, math, threading, queue, ssl, smtplib, base64, datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ------------------------------- Optional: WebSocket client -------------------------------
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
    ss.setdefault("last_ping", 0.0)
    ss.setdefault("top_spikes", [])
    ss.setdefault("last_alert_hashes", set())
init_state()

# ----------------------------------- CSS: Font Scale -------------------------------------
def inject_css_scale(scale: float):
    # Works on most Streamlit primitives + DataFrame cells.
    st.markdown(f"""
    <style>
      html, body {{ font-size: {scale}rem; }}
      /* Sidebars & controls */
      [data-testid="stSidebar"], .stMarkdown, .stTextInput, .stNumberInput, .stSelectbox,
      .stMultiSelect, .stSlider, .stCheckbox, .stRadio, .stButton {{
        font-size: {scale}rem;
      }}
      /* DataFrame (Arrow grid) */
      [data-testid="stDataFrame"] * {{ font-size: {scale}rem; }}
      /* Tables (static) */
      [data-testid="stTable"] * {{ font-size: {scale}rem; }}
      /* Headers */
      h1, h2, h3, h4 {{ line-height: 1.2; }}
    </style>
    """, unsafe_allow_html=True)

# ------------------------------- Audible: real WebAudio beep ------------------------------
def audible_bridge():
    # Uses WebAudio (tone generator) so there's no external file and it actually beeps.
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
        osc.connect(gain);
        gain.connect(ctx.destination);
        const now = ctx.currentTime;
        gain.gain.setValueAtTime(0.0001, now);
        gain.gain.exponentialRampToValueAtTime(0.3, now + 0.01);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.25);
        osc.start(now);
        osc.stop(now + 0.26);
      }
      const tick = () => {
        if (localStorage.getItem('mustBeep') === '1') {
          mvBeep();
          localStorage.setItem('mustBeep', '0');
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
      // Allow one user click to unlock audio on some browsers
      window.addEventListener('click', mvEnsureCtx, { once: true });
    </script>
    """, unsafe_allow_html=True)

def trigger_beep():
    st.markdown("<script>localStorage.setItem('mustBeep','1');</script>", unsafe_allow_html=True)

# ------------------------------------ Indicators -----------------------------------------
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(close, length=14):
    delta = close.diff()
    up = (delta.where(delta > 0, 0.0)).ewm(alpha=1/length, adjust=False).mean()
    down = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/length, adjust=False).mean()
    rs = up / (down + 1e-9)
    return 100 - (100 / (1 + rs))

def macd(close, fast=12, slow=26, signal=9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def roc(close, length=5):
    return close.pct_change(length) * 100.0

# -------------------------------- Coinbase REST utilities --------------------------------
CB_BASE = "https://api.exchange.coinbase.com"

def list_products(quote_currency="USD"):
    url = f"{CB_BASE}/products"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    pairs = [p["id"] for p in data if p.get("quote_currency") == quote_currency]
    return sorted(pairs)

def fetch_candles(pair, granularity_sec):
    # Allowed: 60, 300, 900, 3600, 21600, 86400 (Coinbase)
    url = f"{CB_BASE}/products/{pair}/candles?granularity={granularity_sec}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    arr = r.json()
    if not arr:
        return None
    # cols: time, low, high, open, close, volume (time is seconds)
    df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    return df

TFS = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600,
    "4h": 14400, "6h": 21600, "12h": 43200, "1d": 86400,
}

# ------------------------------- Alerts (email + webhook) --------------------------------
def send_email_alert(subject, body, recipient):
    try:
        cfg = st.secrets["smtp"]  # must exist in .streamlit/secrets.toml
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

# --------------------------------- WebSocket worker --------------------------------------
def ws_worker(pairs, channel="ticker", endpoint="wss://ws-feed.exchange.coinbase.com"):
    ss = st.session_state
    try:
        ws = websocket.WebSocket()
        ws.connect(endpoint, timeout=10)
        ws.settimeout(1.0)  # so we can exit when ws_alive becomes False
        sub = {"type": "subscribe", "channels": [{"name": channel, "product_ids": pairs}]}
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

def start_ws(pairs, chunk_size):
    # Subscribe only to a chunk to keep it light, still useful for "live last price".
    pick = pairs[:max(2, min(chunk_size, len(pairs)))]
    t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
    t.start()
    st.session_state["ws_thread"] = t

def stop_ws():
    st.session_state["ws_alive"] = False

def drain_ws_queue():
    """Pull socket messages into session ws_prices."""
    q = st.session_state["ws_q"]
    prices = st.session_state["ws_prices"]
    got_err = None
    while True:
        try:
            kind, ts, payload = q.get_nowait()
        except queue.Empty:
            break
        if kind == "msg":
            try:
                d = json.loads(payload)
                if d.get("type") == "ticker":
                    pid = d.get("product_id")
                    px = d.get("price")
                    if pid and px:
                        try:
                            prices[pid] = float(px)
                        except Exception:
                            pass
            except Exception:
               

