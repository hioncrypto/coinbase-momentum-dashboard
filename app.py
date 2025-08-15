# Coinbase Fast Movers — All-in-One Spike Scanner
# Features: Base currency dropdown, Top 10 Movers, spike highlights, phone/computer alerts,
# auto-refresh, and a test alert button.

import os, json, time, math, threading, queue, base64, smtplib, ssl, datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import pandas as pd
import numpy as np
import requests
import streamlit as st

# Optional: WebSocket
WS_AVAILABLE = True
try:
    import websocket
except Exception:
    WS_AVAILABLE = False

# Optional autorefresh
try:
    from streamlit_autorefresh import st_autorefresh
    HAS_AUTOREFRESH = True
except Exception:
    HAS_AUTOREFRESH = False

# ---------------- State Init ----------------
def init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("last_alert_hashes", set())
init_state()

# ---------------- CSS scale ----------------
def inject_css_scale(scale: float):
    st.markdown(f"""
    <style>
      html {{ font-size: {scale}rem; }}
      .stDataFrame table {{ font-size: {scale}rem; }}
    </style>
    """, unsafe_allow_html=True)

# ---------------- Audible alert bridge ----------------
BEEP_WAV = base64.b64encode(
    requests.get("https://cdn.jsdelivr.net/gh/anars/blank-audio/1-second-of-silence.wav").content
).decode()

def audible_bridge():
    st.markdown(f"""
    <audio id="beeper" src="data:audio/wav;base64,{BEEP_WAV}"></audio>
    <script>
      const audio = document.getElementById('beeper');
      const tick = () => {{
        if (window.localStorage.getItem('mustBeep') === '1') {{
          audio.play().catch(()=>{{}});
          window.localStorage.setItem('mustBeep','0');
        }}
        requestAnimationFrame(tick);
      }};
      requestAnimationFrame(tick);
    </script>
    """, unsafe_allow_html=True)

def trigger_beep():
    st.markdown("<script>window.localStorage.setItem('mustBeep','1');</script>", unsafe_allow_html=True)

# ---------------- Indicators ----------------
def ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def rsi(close, length=14):
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up).ewm(alpha=1/length, adjust=False).mean()
    roll_down = pd.Series(down).ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / (roll_down + 1e-9)
    return 100 - (100 / (1 + rs))

def macd(close, fast=12, slow=26, signal=9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

# ---------------- Coinbase REST ----------------
CB_BASE = "https://api.exchange.coinbase.com"

def list_products():
    url = f"{CB_BASE}/products"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()

def fetch_candles(pair, granularity_sec):
    url = f"{CB_BASE}/products/{pair}/candles?granularity={granularity_sec}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    arr = r.json()
    if not arr:
        return None
    df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    return df.sort_values("ts").reset_index(drop=True)

TFS = {
    "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400,
    "6h": 21600, "12h": 43200, "1d": 86400,
}

# ---------------- Alerts ----------------
def send_email_alert(subject, body, recipient):
    try:
        cfg = st.secrets["smtp"]
    except Exception:
        return False, "SMTP not configured"
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
        return False, str(e)

def post_webhook(url, payload):
    try:
        r = requests.post(url, json=payload, timeout=10)
        return (200 <= r.status_code < 300), r.text
    except Exception as e:
        return False, str(e)

# ---------------- WebSocket ----------------
def ws_worker(pairs, channel="ticker", endpoint="wss://ws-feed.exchange.coinbase.com"):
    ss = st.session_state
    try:
        ws = websocket.WebSocket()
        ws.connect(endpoint, timeout=10)
        ws.send(json.dumps({"type":"subscribe","channels":[{"name":channel,"product_ids":pairs}]}))
        ss["ws_alive"] = True
        while ss.get("ws_alive", False):
            msg = ws.recv()
            if msg:
                ss["ws_q"].put_nowait(("msg", time.time(), msg))
    except Exception as e:
        ss["ws_q"].put_nowait(("err", time.time(), str(e)))
    finally:
        ss["ws_alive"] = False

# ---------------- View & Highlight ----------------
def compute_view(pairs, timeframes, rsi_len, macd_fast, macd_slow, macd_sig):
    rows = []
    for pid in pairs:
        rec, last_close = {"Pair": pid}, None
        for tf in timeframes:
            sec = TFS[tf]
            df = fetch_candles(pid, sec)
            if df is None or len(df) < 30:
                rec[f"% {tf}"], rec[f"Vol x {tf}"] = np.nan, np.nan
                continue
            df = df.tail(200)
            last_close = float(df["close"].iloc[-1])
            first_close = float(df["close"].iloc[0])
            rec[f"% {tf}"] = (last_close / first_close - 1) * 100
            rec[f"RSI {tf}"] = float(rsi(df["close"], rsi_len).iloc[-1])
            m_line, s_line, _ = macd(df["close"], macd_fast, macd_slow, macd_sig)
            rec[f"MACD {tf}"] = float(m_line.iloc[-1] - s_line.iloc[-1])
            rec[f"Vol x {tf}"] = float(df["volume"].iloc[-1] / (df["volume"].rolling(20).mean().iloc[-1] + 1e-9))
        rec["Last"] = last_close if last_close else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)

def highlight_spikes(df, sort_tf, rsi_overbought, rsi_oversold, vol_mult, spike_thresh):
    df = df.copy()
    spike_mask = (df[f"% {sort_tf}"].abs() >= spike_thresh) & (df[f"Vol x {sort_tf}"] >= vol_mult)
    GREEN_ROW = 'background-color: rgba(0, 255, 0, 0.12); font-weight: 600;'
    RED_CELL  = 'background-color: rgba(255, 0, 0, 0.10);'
    BLUE_CELL = 'background-color: rgba(0, 0, 255, 0.10);'
    def _row_style(r):
        styles = []
        for c in df.columns:
            s = GREEN_ROW if spike_mask.loc[r.name] else ''
            if c == f"RSI {sort_tf}":
                if r[c] >= rsi_overbought: s += RED_CELL
                elif r[c] <= rsi_oversold: s += BLUE_CELL
            styles.append(s)
        return styles
    return spike_mask, df.style.apply(_row_style, axis=1)

# ---------------- UI ----------------
st.set_page_config(page_title="Coinbase Fast Movers", layout="wide")
st.title("Coinbase Fast Movers — All-in-One Spike Scanner")

with st.sidebar:
    st.subheader("Base Currency")
    products = list_products()
    base_currencies = sorted({p['quote_currency'] for p in products})
    quote = st.selectbox("Quote currency", base_currencies, index=0)
    pairs = [p['id'] for p in products if p['quote_currency'] == quote]
    max_pairs = st.slider("Max pairs", 10, 1000, 200, 10)

    st.subheader("Timeframes")
    pick_tfs = st.multiselect("Select timeframes", list(TFS.keys()), default=["1m","5m","15m","1h","4h"])

    sort_tf = st.selectbox("Primary sort TF", pick_tfs)
    sort_desc = st.checkbox("Sort descending", True)

    st.subheader("Indicators / Alerts")
    rsi_len = st.number_input("RSI period", 5, 50, 14)
    macd_fast = st.number_input("MACD fast EMA", 3, 50, 12)
    macd_slow = st.number_input("MACD slow EMA", 5, 100, 26)
    macd_sig = st.number_input("MACD signal", 3, 50, 9)
    vol_mult = st.number_input("Volume spike multiple", 1.0, 20.0, 3.0)
    spike_thresh = st.number_input("Price spike threshold (%)", 0.5, 50.0, 3.0)
    rsi_overb = st.number_input("RSI overbought", 50, 100, 70)
    rsi_overS = st.number_input("RSI oversold", 0, 50, 30)

    st.subheader("Notifications")
    enable_sound = st.checkbox("Audible chime", True)
    email_to = st.text_input("Email recipient")
    webhook_url = st.text_input("Webhook URL")

    st.subheader("Auto-refresh (sec)")
    refresh_seconds = st.number_input("Refresh interval", 0, 3600, 60)

    if st.button("Test Alert Now"):
        trigger_beep()
        if email_to:
            send_email_alert("[Test] Coinbase Fast Movers", "This is a test alert.", email_to)
        if webhook_url:
            post_webhook(webhook_url, {"title": "[Test] Coinbase Fast Movers", "lines": ["This is a test alert."]})
        st.success("Test alert sent.")

inject_css_scale(1.0)
audible_bridge()

# Auto-refresh
if refresh_seconds > 0:
    if HAS_AUTOREFRESH:
        st_autorefresh(interval=refresh_seconds*1000, key="auto_ref")
    else:
        st.markdown(f"<script>setTimeout(() => window.location.reload(), {int(refresh_seconds*1000)});</script>", unsafe_allow_html=True)

pairs = pairs[:max_pairs]
view = compute_view(pairs, pick_tfs, rsi_len, macd_fast, macd_slow, macd_sig)
view = view.sort_values(f"% {sort_tf}", ascending=not sort_desc)

spike_mask, styled = highlight_spikes(view, sort_tf, rsi_overb, rsi_overS, vol_mult, spike_thresh)
top_now = view.loc[spike_mask, ["Pair", f"% {sort_tf}"]].head(10)

colL, colR = st.columns([1,3])
with colL:
    st.subheader("Top 10 Movers")
    st.dataframe(top_now if not top_now.empty else pd.DataFrame({"Pair": [], f"% {sort_tf}": []}))

with colR:
    st.subheader("All Pairs")
    st.dataframe(styled, use_container_width=True)

# Alerts
new_spikes = []
for _, row in top_now.iterrows():
    key = f"{row['Pair']}|{sort_tf}|{round(row[f'% {sort_tf}'],2)}"
    if key not in st.session_state["last_alert_hashes"]:
        new_spikes.append((row["Pair"], row[f"% {sort_tf}"]))
        st.session_state["last_alert_hashes"].add(key)

if enable_sound and new_spikes:
    trigger_beep()
if new_spikes and (email_to or webhook_url):
    sub = f"[Coinbase] Spike(s) on {sort_tf}"
    lines = [f"{p}: {pct:+.2f}%" for p, pct in new_spikes]
    if email_to: send_email_alert(sub, "\n".join(lines), email_to)
    if webhook_url: post_webhook(webhook_url, {"title": sub, "lines": lines})

st.caption(f"Pairs: {len(view)} | Sorted by: {sort_tf} | Base: {quote}")
