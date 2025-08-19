# app.py — Coinbase Movers (Multi-Timeframe) with REST/WebSocket toggle,
# US time zones, font scaling, audible + remote alerts, Top Spikes panel.

import os, json, time, math, threading, queue, base64, smtplib, ssl, datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import pandas as pd
import numpy as np
import requests
import streamlit as st

# -------------------------------
# Optional: WebSocket client
# -------------------------------
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

# ------------- UI/State helpers
def init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("last_ping", 0)
    ss.setdefault("play_sound", False)     # toggled to trigger the audible chime
    ss.setdefault("top_spikes", [])        # list of (pair, tf, pct)
    ss.setdefault("last_alert_hashes", set())  # to avoid duplicate spam
init_state()

# ------------- CSS scale (font slider)
def inject_css_scale(scale: float):
    # scale ~ 0.8 to 1.6
    st.markdown(f"""
    <style>
      html {{ font-size: {scale}rem; }}
      .stDataFrame table {{ font-size: {scale}rem; }}
      .stMarkdown p, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{
        font-size: {scale}rem;
      }}
    </style>
    """, unsafe_allow_html=True)

# ------------- Small JS bridge to play a beep
BEEP_WAV = base64.b64encode(
    requests.get("https://cdn.jsdelivr.net/gh/anars/blank-audio/1-second-of-silence.wav").content
).decode()

def audible_bridge():
    # This listens for a flag in the DOM and plays a short audio.
    st.markdown(f"""
    <audio id="beeper" src="data:audio/wav;base64,{BEEP_WAV}"></audio>
    <script>
      const audio = document.getElementById('beeper');
      const tick = () => {{
        const tag = window.localStorage.getItem('mustBeep');
        if (tag === '1') {{
          audio.volume = 1.0;
          audio.play().catch(()=>{{}});
          window.localStorage.setItem('mustBeep','0');
        }}
        requestAnimationFrame(tick);
      }};
      requestAnimationFrame(tick);
    </script>
    """, unsafe_allow_html=True)

def trigger_beep():
    # flip a small state via localStorage from python side
    st.markdown("""
    <script>window.localStorage.setItem('mustBeep','1');</script>
    """, unsafe_allow_html=True)

# -------------------- Indicators
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

# -------------------- Coinbase REST utilities
CB_BASE = "https://api.exchange.coinbase.com"

def list_products(quote_currency="USD"):
    url = f"{CB_BASE}/products"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    pairs = [p["id"] for p in data if p.get("quote_currency") == quote_currency]
    return sorted(pairs)

def fetch_candles(pair, granularity_sec):
    # Coinbase granularity allowed: 60, 300, 900, 3600, 21600, 86400
    url = f"{CB_BASE}/products/{pair}/candles?granularity={granularity_sec}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    arr = r.json()
    if not arr:
        return None
    # columns: time, low, high, open, close, volume
    df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True).sort_values()
    df = df.sort_values("ts").reset_index(drop=True)
    return df

TFS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "6h": 21600,
    "12h": 43200,
    "1d": 86400,
}

# -------------------- Alerts (email + webhooks)
def send_email_alert(subject, body, recipient):
    # expects secrets:
    # st.secrets["smtp"] = {"host": "...", "port": 465, "user":"...", "password":"...", "sender":"..."}
    try:
        cfg = st.secrets["smtp"]
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
        return ok, r.text
    except Exception as e:
        return False, str(e)

# -------------------- WebSocket worker (optional)
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

# -------------------- Spike detection across timeframes
def compute_view(pairs, timeframes, tz, rsi_len, macd_fast, macd_slow, macd_sig, vol_mult):
    rows = []
    for pid in pairs:
        rec = {"Pair": pid}
        ok = False
        last_close = None

        for tf_name in timeframes:
            sec = TFS[tf_name]
            df = fetch_candles(pid, sec)
            if df is None or len(df) < 30:
                rec[f"% {tf_name}"] = np.nan
                rec[f"Vol x {tf_name}"] = np.nan
                continue

            df = df.tail(200).copy()
            last_close = float(df["close"].iloc[-1])
            first_close = float(df["close"].iloc[0])
            pct = (last_close / first_close - 1.0) * 100.0
            rec[f"% {tf_name}"] = pct

            # Indicators
            rsi_vals = rsi(df["close"], rsi_len)
            rec[f"RSI {tf_name}"] = float(rsi_vals.iloc[-1])

            m_line, s_line, hist = macd(df["close"], macd_fast, macd_slow, macd_sig)
            rec[f"MACD {tf_name}"] = float(m_line.iloc[-1] - s_line.iloc[-1])

            vol = df["volume"]
            vol_spike = float(vol.iloc[-1] / (vol.rolling(20).mean().iloc[-1] + 1e-9))
            rec[f"Vol x {tf_name}"] = vol_spike

            ok = True

        rec["Last"] = last_close if ok else np.nan
        rows.append(rec)

    view = pd.DataFrame(rows)
    # Fill for sorting stability
    return view

def highlight_spikes(df, sort_tf, rsi_overbought, rsi_oversold, vol_mult, spike_thresh):
    df = df.copy()
    # A spike rule = abs(% change on sort_tf) >= spike_thresh *and* Vol x >= vol_mult
    pt_col = f"% {sort_tf}"
    vs_col = f"Vol x {sort_tf}"
    spike_mask = (df[pt_col].abs() >= spike_thresh) & (df[vs_col] >= vol_mult)

    # build styled dataframe
    def _row_style(r):
        base = ""
        if spike_mask.loc[r.name]:
            base += "background-color: rgba(0,255,0,0.15);"
            base += "font-weight: 600;"
        return [base for _ in r]

    return spike_mask, df.style.apply(_row_style, axis=1)

# -------------------- Streamlit UI
st.set_page_config(page_title="Coinbase Movers — Multi-Timeframe", layout="wide")

st.title("Coinbase Movers — Multi-Timeframe")

with st.sidebar:
    st.subheader("Mode")
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0)
    if mode.startswith("WebSocket"):
        if not WS_AVAILABLE:
            st.warning("`websocket-client` not installed. Falling back to REST.")
            mode = "REST only"

    st.subheader("Universe")
    quote = st.selectbox("Quote currency", ["USD", "USDC"], index=0)
    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    watchlist = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
    max_pairs = st.slider("Max pairs to include", 10, 1000, 200, 10)

    st.subheader("Timeframes (for % change)")
    pick_tfs = st.multiselect("Select timeframes (pick ≥1)",
                              list(TFS.keys()),
                              default=["1m","5m","15m","1h","4h","6h","12h","1d"])

    st.subheader("Ranking / sort")
    sort_tf = st.selectbox("Primary timeframe to rank by", pick_tfs, index=0)
    sort_desc = st.checkbox("Sort descending (largest first)", value=True)

    st.subheader("WebSocket")
    chunk = st.slider("Subscribe chunk size", 2, 200, 10, 1)
    st.button("Restart stream")

    st.subheader("Display")
    tz = st.selectbox("Time zone", ["UTC","America/New_York","America/Chicago","America/Denver","America/Los_Angeles"], index=1)
    font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05)

    st.subheader("Indicators / Alerts")
    rsi_len = st.number_input("RSI period", 5, 50, 14, 1)
    macd_fast = st.number_input("MACD fast EMA", 3, 50, 12, 1)
    macd_slow = st.number_input("MACD slow EMA", 5, 100, 26, 1)
    macd_sig = st.number_input("MACD signal", 3, 50, 9, 1)
    vol_mult = st.number_input("Volume spike multiple (e.g., 3.0 = 3x 20-SMA)", 1.0, 20.0, 3.0, 0.1)
    spike_thresh = st.number_input("Price spike threshold (% on sort TF)", 0.5, 50.0, 3.0, 0.5)
    rsi_overb = st.number_input("RSI overbought", 50, 100, 70, 1)
    rsi_overS = st.number_input("RSI oversold", 0, 50, 30, 1)

    st.subheader("Notifications")
    enable_sound = st.checkbox("Audible chime (browser)", value=True)
    st.caption("Click once anywhere in the page if your browser blocks autoplay.")
    st.write("**Email** (configure in *Secrets* to enable)")
    email_to = st.text_input("Email recipient (optional)", "")
    st.write("**Webhook** (Telegram/Pushover/Slack/Discord/Twilio—paste a webhook URL)")
    webhook_url = st.text_input("Webhook URL (optional)", "")

inject_css_scale(font_scale)
audible_bridge()

# Discovery
if use_watch and watchlist.strip():
    pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    try:
        pairs = list_products(quote)
    except Exception as e:
        st.error(f"Failed to discover products: {e}")
        pairs = []
pairs = [p for p in pairs if p.endswith(f"-{quote}")]
if not pairs:
    st.stop()
pairs = pairs[:max_pairs]

# WebSocket (optional)
diag = {"WS_OK": WS_AVAILABLE, "thread_alive": False, "active_ws_url": "", "state.err": ""}

if mode.startswith("WebSocket") and WS_AVAILABLE:
    # start if not running
    if not st.session_state["ws_alive"]:
        # pick a tiny chunk from first few to avoid big subs
        pick = pairs[:max(2, min(chunk, len(pairs)))]
        t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start()
        st.session_state["ws_thread"] = t
        time.sleep(0.2)
    diag["thread_alive"] = bool(st.session_state["ws_alive"])
    diag["active_ws_url"] = "wss://ws-feed.exchange.coinbase.com"

# Diagnostics
with st.expander("Diagnostics", expanded=False):
    st.json(diag)

# Build the table (REST pulls)
try:
    view = compute_view(
        pairs=pairs,
        timeframes=pick_tfs,
        tz=tz,
        rsi_len=rsi_len,
        macd_fast=macd_fast,
        macd_slow=macd_slow,
        macd_sig=macd_sig,
        vol_mult=vol_mult,
    )
except Exception as e:
    st.error(f"Error while computing view: {e}")
    st.stop()

if len(view) == 0:
    st.info("No data… try a smaller watchlist or different quote currency.")
    st.stop()

# Sort
sort_col = f"% {sort_tf}"
if sort_col not in view.columns:
    st.warning(f"Sort column {sort_col} missing.")
else:
    view = view.sort_values(sort_col, ascending=not sort_desc, na_position="last")

# Top spikes (green list at the top)
spike_mask, styled = highlight_spikes(
    view, sort_tf, rsi_overb, rsi_overS, vol_mult, spike_thresh
)

top_now = view.loc[spike_mask, ["Pair", sort_col]].head(10)
colL, colR = st.columns([1,3])
with colL:
    st.subheader("Top spikes")
    if top_now.empty:
        st.write("—")
    else:
        st.dataframe(top_now.rename(columns={sort_col: f"% {sort_tf}"}), use_container_width=True)

with colR:
    st.subheader("All pairs ranked by movement")
    st.dataframe(styled, use_container_width=True)

# Alerts: send for *new* spikes only (avoid spam)
new_spikes = []
if not top_now.empty:
    for _, row in top_now.iterrows():
        pair = row["Pair"]
        pct = float(row[sort_col])
        key = f"{pair}|{sort_tf}|{round(pct,2)}"
        if key not in st.session_state["last_alert_hashes"]:
            new_spikes.append((pair, pct))
            st.session_state["last_alert_hashes"].add(key)

# audible
if enable_sound and new_spikes:
    trigger_beep()

# email/webhook
if new_spikes and (email_to or webhook_url):
    sub = f"[Coinbase] Spike(s) on {sort_tf}"
    body_lines = [f"{p}: {pct:+.2f}% on {sort_tf}" for p, pct in new_spikes]
    body = "\n".join(body_lines)
    if email_to:
        ok, info = send_email_alert(sub, body, email_to)
        if not ok:
            st.warning(info)
    if webhook_url:
        ok, info = post_webhook(webhook_url, {"title": sub, "lines": body_lines})
        if not ok:
            st.warning(f"Webhook error: {info}")

# Footer status bar
st.caption(f"Pairs: {len(view)}   •   Sorted by: {sort_tf}   •   Mode: {mode}   •   Time zone: {tz}")
