# app.py — SpikeWatch (Streamlit, single file)
# - Coinbase (USD/USDC) multi-timeframe movers scanner
# - Timeframes include 4h (synthesized from 1h)
# - Top 10 Movers + green highlight for fast movers
# - Alerts: Browser chime + Email + Webhooks (Telegram/Discord/Slack/Pushover)
# - Test Alert button
# - Works on Streamlit Cloud (use st.secrets for SMTP/webhooks)
#
# Requirements (requirements.txt):
# streamlit>=1.33
# pandas>=2.2
# numpy>=1.26
# requests>=2.32
# websocket-client>=1.8  # optional if you want WebSocket hybrid

import os, json, time, math, threading, queue, base64, ssl
import datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import pandas as pd
import numpy as np
import requests
import streamlit as st

# ---------------------------------
# Optional: WebSocket client
# ---------------------------------
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

# ---------------------------------
# Coinbase endpoints
# ---------------------------------
CB_BASE = "https://api.exchange.coinbase.com"        # REST
CB_WS   = "wss://ws-feed.exchange.coinbase.com"      # WS (Advanced Trade feed-compatible)

# ---------------------------------
# Session state
# ---------------------------------
def init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("last_ping", 0)
    ss.setdefault("play_sound", False)
    ss.setdefault("top_spikes", [])
    ss.setdefault("last_alert_hashes", set())
    ss.setdefault("bars", {})          # bars[pair][tf] -> list of dicts
    ss.setdefault("last_tick", {})     # last tick/bbo
    ss.setdefault("product_stats", {}) # last stats
    ss.setdefault("products_all", [])  # discovered full list
    ss.setdefault("pairs_active", [])  # active filtered list
init_state()

# ---------------------------------
# Utility: indicators
# ---------------------------------
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

def atr_from_ohlc(df: pd.DataFrame, length=14):
    high = df["h"].astype(float)
    low  = df["l"].astype(float)
    close= df["c"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([(high-low).abs(), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def pct(a, b):
    if b == 0 or b is None or a is None:
        return 0.0
    return (a/b-1.0)*100.0

# ---------------------------------
# Timeframes (seconds)
# ---------------------------------
TFS = {
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,  # synthesized from 1h
    "1d": 86400,
}

# ---------------------------------
# REST utils
# ---------------------------------
def list_products(quote_currency="USD"):
    url = f"{CB_BASE}/products"
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()
    pairs = [p["id"] for p in data
             if p.get("quote_currency") == quote_currency
             and p.get("status") in {"online", "online_trading"}
             and not p.get("trading_disabled")]
    return sorted(pairs), data

def fetch_stats(pid):
    try:
        r = requests.get(f"{CB_BASE}/products/{pid}/stats", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}

def fetch_candles(pair, granularity_sec):
    # Coinbase granularity allowed: 60, 300, 900, 3600, 21600, 86400
    if granularity_sec not in {60,300,900,3600,21600,86400}:
        return None
    url = f"{CB_BASE}/products/{pair}/candles?granularity={granularity_sec}"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return None
    arr = r.json()
    if not arr:
        return None
    df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    # rename to generic ohlcv for internal funcs
    df = df.rename(columns={"open":"o","high":"h","low":"l","close":"c","volume":"v"})
    return df

# ---------------------------------
# WebSocket ingest (optional hybrid)
# ---------------------------------
def bucket_end(ts, seconds):
    return int(ts - (ts % seconds) + seconds)

def on_tick(pair, price, size, t_unix, bid=None, ask=None):
    ss = st.session_state
    ss["last_tick"].setdefault(pair, {})
    ss["last_tick"][pair] = {"price":price, "size":size, "time":t_unix, "bid":bid, "ask":ask}

    # rolling bars we maintain from ticks (short TFs + 1h)
    base_tfs = ["15s","30s","1m","3m","5m","15m","30m","1h"]
    ss["bars"].setdefault(pair, {})
    for tf in base_tfs:
        secs = TFS[tf]
        bars = ss["bars"][pair].setdefault(tf, [])
        endt = bucket_end(t_unix, secs)
        if len(bars) and bars[-1]["t"]==endt:
            b=bars[-1]
            b["h"]=max(b["h"], price); b["l"]=min(b["l"], price); b["c"]=price; b["v"]+= size
        else:
            bars.append({"t":endt, "o":price, "h":price, "l":price, "c":price, "v":size})
            # keep memory bounded
            if len(bars)>600:
                del bars[:len(bars)-600]

def ws_worker(pairs, endpoint=CB_WS):
    ss = st.session_state
    try:
        ws = websocket.WebSocket()
        ws.connect(endpoint, timeout=10)
        # chunk subscribe to avoid rate limits
        chunk=80
        for i in range(0, len(pairs), chunk):
            sub = {"type":"subscribe","channels":[{"name":"ticker","product_ids":pairs[i:i+chunk]}]}
            ws.send(json.dumps(sub))
            time.sleep(0.2)
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

def ws_ingest_pump():
    ss = st.session_state
    did = 0
    while not ss["ws_q"].empty() and did<200:
        kind, ts, payload = ss["ws_q"].get_nowait()
        if kind == "msg":
            try:
                d = json.loads(payload)
            except Exception:
                continue
            if d.get("type")!="ticker":
                continue
            pid = d.get("product_id")
            px  = float(d.get("price") or 0.0) if d.get("price") else None
            sz  = float(d.get("last_size") or 0.0) if d.get("last_size") else 0.0
            bid = float(d.get("best_bid")) if d.get("best_bid") else None
            ask = float(d.get("best_ask")) if d.get("best_ask") else None
            t_iso= d.get("time")
            if not (pid and px and t_iso): 
                continue
            t_unix = int(dt.datetime.fromisoformat(t_iso.replace("Z","+00:00")).timestamp())
            on_tick(pid, px, sz, t_unix, bid, ask)
        did += 1

# ---------------------------------
# UI helpers
# ---------------------------------
def inject_css_scale(scale: float):
    st.markdown(f"""
    <style>
      html {{ font-size: {scale}rem; }}
      .stDataFrame table {{ font-size: {scale}rem; }}
      .stMarkdown p, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {{
        font-size: {scale}rem;
      }}
    </style>
    """, unsafe_allow_html=True)

# Small JS bridge to play a beep
BEEP_WAV = base64.b64encode(
    requests.get("https://cdn.jsdelivr.net/gh/anars/blank-audio/1-second-of-silence.wav", timeout=15).content
).decode()

def audible_bridge():
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
    st.markdown("""<script>window.localStorage.setItem('mustBeep','1');</script>""",
                unsafe_allow_html=True)

# ---------------------------------
# Spike compute from REST/WS bars
# ---------------------------------
def get_bars_df(pair, tf):
    # Priority: if WS built bars exist for tf, use them; else try REST granularity
    ss = st.session_state
    df = pd.DataFrame(ss["bars"].get(pair, {}).get(tf, []))
    if not df.empty:
        df["ts"] = pd.to_datetime(df["t"], unit="s", utc=True)
        df = df.sort_values("ts").rename(columns={"o":"o","h":"h","l":"l","c":"c","v":"v"})
        return df[["ts","o","h","l","c","v"]].tail(400).reset_index(drop=True)

    # Fallback REST (limited TFs)
    tf_to_rest = {"1m":60,"5m":300,"15m":900,"1h":3600,"6h":21600,"1d":86400}
    if tf in tf_to_rest:
        df = fetch_candles(pair, tf_to_rest[tf])
        if df is not None:
            df = df.rename(columns={"ts":"ts"})
            return df[["ts","o","h","l","c","v"]].tail(400).reset_index(drop=True)
    # Synth 4h from 1h
    if tf == "4h":
        h1 = get_bars_df(pair, "1h")
        if h1 is None or h1.empty:
            return pd.DataFrame()
        h1 = h1.set_index(h1["ts"])
        o = h1["o"].resample("4H", label="right", closed="right").first()
        h = h1["h"].resample("4H", label="right", closed="right").max()
        l = h1["l"].resample("4H", label="right", closed="right").min()
        c = h1["c"].resample("4H", label="right", closed="right").last()
        v = h1["v"].resample("4H", label="right", closed="right").sum()
        out = pd.DataFrame({"ts":o.index, "o":o, "h":h, "l":l, "c":c, "v":v}).dropna().reset_index(drop=True)
        return out.tail(200)
    return pd.DataFrame()

def compute_signals(pair, tfs, rsi_len, macd_fast, macd_slow, macd_sig, atr_len,
                    price_thresh_map, vol_mult_map, atr_mult=1.8):
    out = {"Pair": pair, "Last": np.nan}
    last_tick = st.session_state["last_tick"].get(pair, {})
    if last_tick:
        out["Last"] = float(last_tick.get("price", np.nan))

    for tf in tfs:
        df = get_bars_df(pair, tf)
        if df is None or df.empty or len(df)<30:
            out[f"% {tf}"] = np.nan
            out[f"Vol x {tf}"] = np.nan
            out[f"RSI {tf}"] = np.nan
            out[f"MACD {tf}"] = np.nan
            out[f"ATR% {tf}"] = np.nan
            continue

        close = df["c"].astype(float)
        vol   = df["v"].astype(float)

        # Δ%: short TFs use shorter ref window
        n_back = 1 if tf in ("15s","30s","1m") else 2 if tf in ("3m","5m") else 3
        ref = close.iloc[-1-n_back] if len(close)>n_back else close.iloc[0]
        pct_ch = pct(close.iloc[-1], ref)
        out[f"% {tf}"] = float(pct_ch)

        # Volume multiple
        base = vol.rolling(20, min_periods=5).mean().iloc[-1]
        volx = float(vol.iloc[-1] / (base + 1e-9))
        out[f"Vol x {tf}"] = volx

        # RSI / MACD / ATR%
        rsi_vals = rsi(close, rsi_len); out[f"RSI {tf}"] = float(rsi_vals.iloc[-1])
        m_line, s_line, hist = macd(close, macd_fast, macd_slow, macd_sig)
        out[f"MACD {tf}"] = float(m_line.iloc[-1] - s_line.iloc[-1])

        # ATR% gate
        df_ohlc = df.rename(columns={"o":"o","h":"h","l":"l","c":"c"})
        atr_vals = atr_from_ohlc(df_ohlc[["o","h","l","c"]], length=atr_len)
        atrp = float((atr_vals.iloc[-1] / (close.iloc[-1] + 1e-9)) * 100.0)
        out[f"ATR% {tf}"] = atrp

        # Spike tagging (green highlight criteria)
        p_hit = abs(pct_ch) >= price_thresh_map.get(tf, 9e9)
        v_hit = volx >= vol_mult_map.get(tf, 9e9)
        a_hit = abs(pct_ch) >= atrp * atr_mult
        out[f"SPIKE {tf}"] = bool(p_hit and v_hit and a_hit)

    return out

def build_view(pairs, tfs, rsi_len, macd_fast, macd_slow, macd_sig, atr_len,
               price_thresh_map, vol_mult_map, atr_mult):
    rows=[]
    for pid in pairs:
        rows.append(
            compute_signals(
                pid, tfs, rsi_len, macd_fast, macd_slow, macd_sig, atr_len,
                price_thresh_map, vol_mult_map, atr_mult
            )
        )
    return pd.DataFrame(rows)

def style_spikes(df, sort_tf, vol_mult, price_thresh, atr_mult):
    if df is None or df.empty:
        return df, pd.Series([], dtype=bool)
    pt_col = f"% {sort_tf}"
    vs_col = f"Vol x {sort_tf}"
    at_col = f"ATR% {sort_tf}"
    spike_mask = (df[pt_col].abs() >= price_thresh.get(sort_tf, 9e9)) & \
                 (df[vs_col] >= vol_mult.get(sort_tf, 9e9)) & \
                 (df[at_col].abs() * atr_mult <= df[pt_col].abs())

    def _row_style(r):
        base = ""
        if spike_mask.loc[r.name]:
            base += "background-color: rgba(16,185,129,0.20); font-weight: 600;"
        return [base for _ in r]

    return df.style.apply(_row_style, axis=1), spike_mask

# ---------------------------------
# Alerts (Email/Webhooks/Pushover)
# ---------------------------------
def send_email_alert(subject, body, recipient):
    # expects secrets:
    # st.secrets["smtp"] = {"host": "...", "port": 465, "user":"...", "password":"...", "sender":"..."}
    if "smtp" not in st.secrets:
        return False, "SMTP not configured in st.secrets"
    cfg = st.secrets["smtp"]
    try:
        msg = MIMEMultipart()
        msg["From"] = cfg["sender"]
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with ssl.create_default_context() as ctx:
            with smtplib.SMTP_SSL(cfg["host"], int(cfg.get("port",465)), context=ctx) as server:
                server.login(cfg["user"], cfg["password"])
                server.sendmail(cfg["sender"], recipient, msg.as_string())
        return True, "Email sent"
    except Exception as e:
        return False, f"Email error: {e}"

def post_webhook(url, payload):
    try:
        # Slack/Telegram/Discord friendly
        if "discord.com/api/webhooks" in url:
            body = {"content": payload.get("text","")}
        else:
            body = payload
        r = requests.post(url, json=body, timeout=10)
        ok = (200 <= r.status_code < 300)
        return ok, r.text
    except Exception as e:
        return False, str(e)

def pushover_send(token, user_key, title, message):
    try:
        r = requests.post("https://api.pushover.net/1/messages.json",
                          data={"token": token, "user": user_key, "title": title, "message": message},
                          timeout=10)
        return (200<=r.status_code<300), r.text
    except Exception as e:
        return False, str(e)

def alert_fanout(lines, email_to="", webhook_url="", pushover_token="", pushover_user=""):
    errs=[]
    sub = "[SpikeWatch] Fast mover"
    text = "\n".join(lines)

    if email_to:
        ok,info = send_email_alert(sub, text, email_to)
        if not ok: errs.append(info)

    if webhook_url:
        ok,info = post_webhook(webhook_url, {"text": f"**{sub}**\n{text}"})
        if not ok: errs.append(f"Webhook: {info}")

    if pushover_token and pushover_user:
        ok,info = pushover_send(pushover_token, pushover_user, sub, text)
        if not ok: errs.append(f"Pushover: {info}")

    return errs

# ---------------------------------
# Streamlit UI
# ---------------------------------
st.set_page_config(page_title="SpikeWatch — Coinbase Movers", layout="wide")

st.title("SpikeWatch — Coinbase Movers (Streamlit)")
inject_css_scale(1.0)
audible_bridge()

with st.sidebar:
    st.subheader("Data source")
    mode = st.radio("Mode", ["REST only", "WebSocket + REST (hybrid)"], index=1 if WS_AVAILABLE else 0)
    if mode.startswith("WebSocket") and not WS_AVAILABLE:
        st.warning("`websocket-client` not installed. Falling back to REST.")
        mode = "REST only"

    st.subheader("Universe")
    quote = st.selectbox("Quote currency", ["USD","USDC"], index=0)
    # Discover products
    if st.button("Discover products", type="primary"):
        try:
            pairs, products_raw = list_products(quote)
            st.session_state["products_all"] = pairs
            # Build base-currency list for filter
            bases = sorted({p.split("-")[0] for p in pairs})
            st.session_state["bases_all"] = bases
            # Prefetch stats for top volume ordering
            stats = {}
            for pid in pairs:
                stats[pid] = fetch_stats(pid)
            st.session_state["product_stats"] = stats
            st.success(f"Discovered {len(pairs)} {quote} pairs.")
        except Exception as e:
            st.error(f"Discovery failed: {e}")

    bases_all = st.session_state.get("bases_all", [])
    base_filter = st.multiselect("Filter by base currencies (optional)", bases_all, default=[])

    use_watch = st.checkbox("Use watchlist only", value=False)
    watchlist = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
    max_pairs = st.slider("Max pairs to include", 10, 1000, 250, 10)

    st.subheader("Timeframes & Ranking")
    pick_tfs = st.multiselect("Select timeframes (pick ≥1)",
                              ["15s","30s","1m","3m","5m","15m","30m","1h","4h","1d"],
                              default=["15s","1m","5m","1h","4h"])
    sort_tf = st.selectbox("Primary timeframe to rank by", pick_tfs, index=0)
    sort_desc = st.checkbox("Sort descending", value=True)

    st.subheader("Indicators / Thresholds")
    rsi_len = st.number_input("RSI period", 5, 50, 14, 1)
    macd_fast = st.number_input("MACD fast EMA", 3, 50, 12, 1)
    macd_slow = st.number_input("MACD slow EMA", 5, 100, 26, 1)
    macd_sig  = st.number_input("MACD signal", 3, 50, 9, 1)
    atr_len   = st.number_input("ATR length", 5, 50, 14, 1)

    st.caption("Set spike thresholds per timeframe (price Δ% & Vol× multiple). Leave blank to ignore a TF.")
    # Sensible defaults:
    default_price = {"15s":0.35, "1m":0.8, "5m":2.5, "15m":4.0, "1h":6.0, "4h":10.0}
    default_volx  = {"1m":3.0, "5m":2.5, "15m":2.0}

    price_thresh_map = {}
    vol_mult_map = {}
    cols = st.columns(2)
    with cols[0]:
        for tf in pick_tfs:
            v = st.text_input(f"Δ% threshold for {tf}", value=str(default_price.get(tf,"")),
                              key=f"pt_{tf}")
            try:
                price_thresh_map[tf] = float(v) if v.strip()!="" else 9e9
            except:
                price_thresh_map[tf] = 9e9
    with cols[1]:
        for tf in pick_tfs:
            v = st.text_input(f"Vol× threshold for {tf}", value=str(default_volx.get(tf,"")),
                              key=f"vx_{tf}")
            try:
                vol_mult_map[tf] = float(v) if v.strip()!="" else 9e9
            except:
                vol_mult_map[tf] = 9e9

    atr_mult = st.number_input("ATR gate multiplier (Δ% ≥ ATR% × m)", 0.5, 5.0, 1.8, 0.1)

    st.subheader("Notifications")
    enable_sound = st.checkbox("Audible chime (browser)", value=True)
    st.caption("Tip: click once anywhere in the page if your browser blocks autoplay.")
    email_to = st.text_input("Email recipient (optional)", st.secrets.get("alert_email",""))
    webhook_url = st.text_input("Webhook URL (optional)", st.secrets.get("webhook_url",""))
    pushover_token = st.text_input("Pushover API token (optional)", st.secrets.get("pushover_token",""))
    pushover_user  = st.text_input("Pushover User key (optional)", st.secrets.get("pushover_user",""))
    st.button("Send TEST alert", on_click=lambda: st.session_state.update({"do_test_alert": True}))

# Apply font scaling small tweak for mobile
inject_css_scale(1.0)

# Derive active pairs
if st.session_state.get("products_all"):
    pairs = st.session_state["products_all"].copy()
else:
    try:
        pairs, _raw = list_products(quote)
        st.session_state["products_all"] = pairs
        st.session_state["bases_all"] = sorted({p.split("-")[0] for p in pairs})
        # stats
        st.session_state["product_stats"] = {pid:fetch_stats(pid) for pid in pairs}
    except Exception as e:
        st.error(f"Failed to discover products: {e}")
        pairs = []

# Filter pairs by base currency or watchlist
if use_watch and watchlist.strip():
    base_pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    if base_filter:
        base_set = set([b.upper() for b in base_filter])
        base_pairs = [p for p in pairs if p.split("-")[0].upper() in base_set]
    else:
        base_pairs = pairs[:]

# Enforce quote selection
base_pairs = [p for p in base_pairs if p.endswith(f"-{quote}")]
# Sort by approximate USD volume (last * volume)
def vol_usd_est(stat):
    try:
        return float(stat.get("last",0.0)) * float(stat.get("volume",0.0))
    except:
        return 0.0
stats = st.session_state.get("product_stats", {})
base_pairs = sorted(base_pairs, key=lambda pid: vol_usd_est(stats.get(pid,{})), reverse=True)
base_pairs = base_pairs[:max_pairs]
st.session_state["pairs_active"] = base_pairs

# WebSocket: start if requested
diag = {"WS_OK": WS_AVAILABLE, "thread_alive": False, "active_ws_url": "", "state.err": ""}
if mode.startswith("WebSocket") and WS_AVAILABLE and base_pairs:
    if not st.session_state["ws_alive"]:
        pick = base_pairs[:min(200, len(base_pairs))]
        t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start()
        st.session_state["ws_thread"] = t
        time.sleep(0.2)
    diag["thread_alive"] = bool(st.session_state["ws_alive"])
    diag["active_ws_url"] = CB_WS
    # pump inbound queue quickly
    ws_ingest_pump()

# -----------------------------
# Compute table / Top movers
# -----------------------------
if not base_pairs:
    st.info("No pairs found; adjust filters or click **Discover products** again.")
    st.stop()

try:
    view = build_view(
        pairs=base_pairs,
        tfs=pick_tfs,
        rsi_len=rsi_len,
        macd_fast=macd_fast, macd_slow=macd_slow, macd_sig=macd_sig,
        atr_len=atr_len,
        price_thresh_map=price_thresh_map,
        vol_mult_map=vol_mult_map,
        atr_mult=atr_mult,
    )
except Exception as e:
    st.error(f"Error computing view: {e}")
    st.stop()

# Sort by chosen timeframe
sort_col = f"% {sort_tf}"
if sort_col not in view.columns:
    st.warning(f"Sort column {sort_col} missing.")
else:
    view = view.sort_values(sort_col, ascending=not sort_desc, na_position="last")

# Highlight rows that meet spike rule on the sort TF
styled, spike_mask = style_spikes(view, sort_tf, vol_mult_map, price_thresh_map, atr_mult)

# Top spikes list + main table
top_now = view.loc[spike_mask, ["Pair", sort_col]].head(10)
colL, colR = st.columns([1,3])
with colL:
    st.subheader("Top 10 Movers")
    if top_now.empty:
        st.write("—")
    else:
        st.dataframe(top_now.rename(columns={sort_col: f"% {sort_tf}"}), use_container_width=True)

with colR:
    st.subheader("All pairs ranked by movement")
    st.dataframe(styled, use_container_width=True)

# ---------------------------------
# Alerts (new spikes only)
# ---------------------------------
new_spikes = []
if not top_now.empty:
    for _, row in top_now.iterrows():
        pair = row["Pair"]
        pct_val = float(row[sort_col])
        key = f"{pair}|{sort_tf}|{round(pct_val,2)}"
        if key not in st.session_state["last_alert_hashes"]:
            new_spikes.append((pair, pct_val))
            st.session_state["last_alert_hashes"].add(key)

# Test alert
if st.session_state.pop("do_test_alert", False):
    errs = alert_fanout(
        lines=["TEST: SpikeWatch alert test ✅"],
        email_to=email_to, webhook_url=webhook_url,
        pushover_token=pushover_token, pushover_user=pushover_user
    )
    if errs:
        st.warning("Test alert issues: " + "; ".join(errs))
    else:
        st.success("Test alert sent.")

# audible
if enable_sound and new_spikes:
    trigger_beep()

# email/webhook push
if new_spikes and (email_to or webhook_url or (pushover_token and pushover_user)):
    sub_lines = [f"{p}: {pct:+.2f}% on {sort_tf}" for p, pct in new_spikes]
    errs = alert_fanout(
        lines=sub_lines, email_to=email_to, webhook_url=webhook_url,
        pushover_token=pushover_token, pushover_user=pushover_user
    )
    if errs:
        st.warning("; ".join(errs))

# Diagnostics toggle
with st.expander("Diagnostics", expanded=False):
    st.json({
        "mode": mode, "quote": quote,
        "pairs_active": len(base_pairs), "ws": diag,
        "tfs": pick_tfs, "sort_tf": sort_tf
    })

st.caption(f"Pairs: {len(view)} • Sorted by: {sort_tf} • Mode: {mode} • Quote: {quote}")
