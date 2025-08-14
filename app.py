# Coinbase Movers + Momentum + Alerts — Hybrid (WebSocket + REST)
# v5.1  — one-file app
# New in v5.1: Pushbullet + Pushover notifications, HTML email template

from __future__ import annotations

import json
import math
import smtplib
import ssl
import threading
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st

# -------------------- CONFIG --------------------
EXCH_REST = "https://api.exchange.coinbase.com"
EXCH_WS   = "wss://ws-feed.exchange.coinbase.com"

# Timeframes (label -> seconds)
TF_CHOICES: Dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,   # derived from 1h
    "6h": 21600,   # native
    "12h": 43200,  # derived from 1h
    "1d": 86400    # native
}

# Coinbase candle granularities (seconds)
CB_GRANS = [60, 300, 900, 3600, 21600, 86400]

st.set_page_config(page_title="Coinbase Movers + Momentum + Alerts", layout="wide")
st.title("Coinbase Movers + Momentum — Alerts (Hybrid)")

# -------------------- SIDEBAR --------------------
with st.sidebar:
    st.subheader("Mode")
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0)

    st.subheader("Universe")
    quote_currency = st.selectbox("Quote currency", ["USD", "USDT", "BTC"], index=0)
    use_watchlist = st.checkbox("Use watchlist only (ignore discovery)", False)
    wl_text = st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
    max_pairs = st.slider("Max pairs to include", 10, 1000, 200, step=10)

    st.subheader("Timeframes (for % change)")
    tf_selected = st.multiselect(
        "Select timeframes (pick ≥1)",
        list(TF_CHOICES.keys()),
        default=["1m", "5m", "15m", "1h", "4h", "6h", "12h", "1d"],
    )

    st.subheader("Ranking / sort")
    sort_metric = st.selectbox(
        "Sort by",
        ["% ALL avg", "% ALL max_abs"] + [f"% {t}" for t in tf_selected] + ["RSI", "MACD_Hist", "VolZ"],
        index=0,
    )
    descending = st.checkbox("Sort descending (largest first)", True)

    st.subheader("Auto‑refresh")
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 15, step=5)
    try:
        st.autorefresh(interval=refresh_sec * 1000, key="auto_refresh_key")
    except Exception:
        st.caption("Auto‑refresh unavailable on this Streamlit version; use the ↻ Rerun button or upgrade Streamlit.")

    st.subheader("Indicators")
    ind_gran = st.selectbox("Indicator candle granularity", ["1m", "5m", "15m"], index=0)
    rsi_len = st.number_input("RSI length", min_value=5, max_value=100, value=14, step=1)
    macd_fast = st.number_input("MACD fast", min_value=2, max_value=50, value=12, step=1)
    macd_slow = st.number_input("MACD slow", min_value=4, max_value=200, value=26, step=1)
    macd_signal = st.number_input("MACD signal", min_value=2, max_value=50, value=9, step=1)
    vol_window = st.number_input("Volume Z-Score window", min_value=10, max_value=500, value=60, step=5)
    vol_z_thresh = st.slider("Volume spike Z threshold", 1.0, 8.0, 3.0, 0.5)

    st.subheader("Spike filters & Top list")
    show_spikes_only = st.checkbox("Show only rows with any spike", False)
    top_spike_size = st.slider("Top Spike List size", 3, 30, 10, step=1)
    top_spike_metric = st.selectbox("Top list rank metric", ["% ALL max_abs", "% ALL avg", "VolZ", "RSI", "MACD_Hist"], index=0)

    st.subheader("WebSocket (Exchange ticker)")
    if mode.startswith("WebSocket"):
        ws_chunk = st.slider("Subscribe chunk size", 2, 50, 10)
        c1, c2 = st.columns(2)
        with c1:
            start_ws = st.button("Start WebSocket", use_container_width=True)
        with c2:
            stop_ws = st.button("Stop WebSocket", use_container_width=True)
    else:
        start_ws = stop_ws = False

    st.subheader("Notifications")
    enable_toast = st.checkbox("In‑app toast", True)

    st.markdown("---")
    st.markdown("**Email (SMTP)**")
    enable_email = st.checkbox("Enable Email alerts", False)
    if enable_email:
        st.caption("Tip: store credentials in `.streamlit/secrets.toml` in production.")
        smtp_host = st.text_input("SMTP host", value=st.secrets.get("smtp_host", ""))
        smtp_port = st.number_input("SMTP port", min_value=1, max_value=65535, value=int(st.secrets.get("smtp_port", 465)))
        smtp_security = st.selectbox("Security", ["SSL", "STARTTLS", "None"], index=0)
        smtp_user = st.text_input("SMTP username", value=st.secrets.get("smtp_user", ""))
        smtp_pass = st.text_input("SMTP password", type="password", value=st.secrets.get("smtp_pass", ""))
        from_email = st.text_input("From email", value=st.secrets.get("from_email", ""))
        to_emails = st.text_input("To email(s) comma‑separated", value=st.secrets.get("to_emails", ""))

    st.markdown("---")
    st.markdown("**Webhook (Slack/Discord/custom)**")
    enable_webhook = st.checkbox("Enable Webhook alerts", False)
    if enable_webhook:
        webhook_url = st.text_input("Webhook URL", value=st.secrets.get("webhook_url", ""))

    st.markdown("---")
    st.markdown("**Push Services**")
    enable_pushbullet = st.checkbox("Enable Pushbullet", False)
    if enable_pushbullet:
        pb_token = st.text_input("Pushbullet Access Token", value=st.secrets.get("pushbullet_token", ""))

    enable_pushover = st.checkbox("Enable Pushover", False)
    if enable_pushover:
        po_token = st.text_input("Pushover API Token", value=st.secrets.get("pushover_token", ""))
        po_user  = st.text_input("Pushover User/Group Key", value=st.secrets.get("pushover_user", ""))

    st.subheader("Display")
    font_size_px = st.slider("Table font size (px)", 12, 22, 15)

# apply font-size CSS
st.markdown(
    f"""
    <style>
      div[data-testid="stDataFrame"] div[role="gridcell"] {{ font-size: {font_size_px}px; }}
      div[data-testid="stDataFrame"] div[role="columnheader"] {{ font-size: {font_size_px}px; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# -------------------- SESSION STATE --------------------
if "ws_thread" not in st.session_state:
    st.session_state.ws_thread = None
if "ws_running" not in st.session_state:
    st.session_state.ws_running = False
if "ws_prices" not in st.session_state:
    st.session_state.ws_prices: Dict[str, float] = {}
if "ws_last_err" not in st.session_state:
    st.session_state.ws_last_err = ""
if "ws_diag" not in st.session_state:
    st.session_state.ws_diag: List[str] = []
if "alerted" not in st.session_state:
    st.session_state.alerted: Dict[str, float] = {}  # pid -> last alert ts

# -------------------- HELPERS --------------------
def best_granularity(seconds: int) -> int:
    allowed = [g for g in CB_GRANS if g <= seconds]
    return allowed[-1] if allowed else 60

@st.cache_data(ttl=600)
def discover_pairs(quote: str) -> List[str]:
    try:
        r = requests.get(f"{EXCH_REST}/products", timeout=15)
        r.raise_for_status()
        out = []
        for it in r.json():
            pid = it.get("id")
            q = it.get("quote_currency", "")
            if pid and q and q.upper() == quote.upper():
                out.append(pid)
        return sorted(set(out))
    except Exception:
        return ["BTC-USD", "ETH-USD", "SOL-USD"]

def fetch_candles(pid: str, granularity: int, bars: int) -> pd.DataFrame:
    end = datetime.utcnow()
    start = end - timedelta(seconds=granularity * (bars + 5))
    params = {
        "granularity": granularity,
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
    }
    try:
        r = requests.get(f"{EXCH_REST}/products/{pid}/candles", params=params, timeout=15)
        if r.status_code != 200:
            return pd.DataFrame()
        data = r.json()
        if not isinstance(data, list) or not data:
            return pd.DataFrame()
        df = pd.DataFrame(data, columns=["ts", "low", "high", "open", "close", "volume"])
        df = df.sort_values("ts").reset_index(drop=True)
        df["time"] = pd.to_datetime(df["ts"], unit="s", utc=True)
        return df[["time", "open", "high", "low", "close", "volume"]]
    except Exception:
        return pd.DataFrame()

def pct_change_from_candles(pid: str, window_sec: int) -> Optional[float]:
    g = best_granularity(window_sec)
    steps = max(1, math.ceil(window_sec / g))
    df = fetch_candles(pid, g, steps + 2)
    if df.empty or len(df) < steps + 1:
        return None
    latest = df.iloc[-1]["close"]
    ref = df.iloc[-(steps + 1)]["close"]
    try:
        return (latest - ref) / ref * 100.0
    except Exception:
        return None

@st.cache_data(ttl=15)
def rest_spot_price(pid: str) -> Optional[float]:
    try:
        r = requests.get(f"{EXCH_REST}/products/{pid}/ticker", timeout=10)
        if r.status_code != 200:
            return None
        return float(r.json().get("price"))
    except Exception:
        return None

# ----- Indicators -----
def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False, min_periods=length).mean()

def rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    gain = (delta.clip(lower=0)).ewm(alpha=1/length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/length, adjust=False).mean()
    rs = gain / (loss.replace(0, 1e-12))
    return 100 - (100 / (1 + rs))

def macd(series: pd.Series, fast: int, slow: int, signal: int) -> Tuple[pd.Series, pd.Series, pd.Series]:
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def volume_zscore(vol: pd.Series, window: int) -> pd.Series:
    m = vol.rolling(window).mean()
    s = vol.rolling(window).std(ddof=0)
    return (vol - m) / (s.replace(0, 1e-12))

def compute_indicators(pid: str, gran_label: str, rsi_len: int, m_fast:int, m_slow:int, m_sig:int, vol_win:int, vol_z_thresh:float) -> Dict[str, Optional[float]]:
    gran_map = {"1m": 60, "5m": 300, "15m": 900}
    g = gran_map.get(gran_label, 60)
    bars_needed = max(200, m_slow + m_sig + vol_win + rsi_len + 5)
    df = fetch_candles(pid, g, bars_needed)
    if df.empty or len(df) < max(rsi_len, m_slow + m_sig, vol_win) + 5:
        return {"RSI": None, "MACD": None, "MACD_Signal": None, "MACD_Hist": None, "VolZ": None,
                "RSI_Spike": False, "MACD_Spike": False, "Vol_Spike": False}

    close = df["close"].astype(float)
    vol = df["volume"].astype(float)

    rsi_series = rsi(close, rsi_len)
    macd_line, signal_line, hist = macd(close, m_fast, m_slow, m_sig)
    volz = volume_zscore(vol, vol_win)

    latest = {
        "RSI": float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None,
        "MACD": float(macd_line.iloc[-1]) if not pd.isna(macd_line.iloc[-1]) else None,
        "MACD_Signal": float(signal_line.iloc[-1]) if not pd.isna(signal_line.iloc[-1]) else None,
        "MACD_Hist": float(hist.iloc[-1]) if not pd.isna(hist.iloc[-1]) else None,
        "VolZ": float(volz.iloc[-1]) if not pd.isna(volz.iloc[-1]) else None,
    }

    # Spike heuristics
    rsi_spike = False
    if latest["RSI"] is not None:
        rsi_prev = float(rsi_series.iloc[-2]) if not pd.isna(rsi_series.iloc[-2]) else latest["RSI"]
        rsi_spike = (rsi_prev < 30 <= latest["RSI"]) or (rsi_prev > 70 >= latest["RSI"])

    macd_spike = False
    if latest["MACD_Hist"] is not None:
        macd_prev = float(hist.iloc[-2]) if not pd.isna(hist.iloc[-2]) else latest["MACD_Hist"]
        macd_spike = (macd_prev <= 0 < latest["MACD_Hist"]) or (macd_prev >= 0 > latest["MACD_Hist"])

    vol_spike = False
    if latest["VolZ"] is not None:
        vol_spike = latest["VolZ"] >= vol_z_thresh

    latest.update({"RSI_Spike": rsi_spike, "MACD_Spike": macd_spike, "Vol_Spike": vol_spike})
    return latest

# -------------------- NOTIFICATIONS --------------------
def toast(msg: str):
    if enable_toast:
        st.toast(msg, icon="📣")

def send_email(subject: str, body_md: str):
    if not enable_email:
        return
    try:
        recipients = [e.strip() for e in (to_emails or "").split(",") if e.strip()]
        if not recipients or not smtp_host or not from_email:
            return
        # HTML template
        html = f"""
        <html><body style="font-family:Arial,Helvetica,sans-serif;">
            <h3>{subject}</h3>
            <p>{body_md}</p>
            <p style="color:#888;">Sent {datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC</p>
        </body></html>
        """
        msg = MIMEMultipart("alternative")
        msg["From"] = from_email
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body_md, "plain"))
        msg.attach(MIMEText(html, "html"))

        if smtp_security == "SSL":
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=20) as server:
                if smtp_user:
                    server.login(smtp_user, smtp_pass or "")
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                if smtp_security == "STARTTLS":
                    server.starttls()
                if smtp_user:
                    server.login(smtp_user, smtp_pass or "")
                server.send_message(msg)
    except Exception as e:
        st.warning(f"Email send failed: {e}")

def send_webhook(text: str, extra: dict | None = None):
    if not enable_webhook:
        return
    try:
        if not webhook_url:
            return
        payload = {"text": text}
        if extra:
            payload.update(extra)
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        st.warning(f"Webhook failed: {e}")

def send_pushbullet(title: str, body: str):
    if not enable_pushbullet:
        return
    try:
        if not pb_token:
            return
        headers = {"Access-Token": pb_token, "Content-Type": "application/json"}
        payload = {"type": "note", "title": title, "body": body}
        requests.post("https://api.pushbullet.com/v2/pushes", headers=headers, json=payload, timeout=10)
    except Exception as e:
        st.warning(f"Pushbullet failed: {e}")

def send_pushover(title: str, body: str):
    if not enable_pushover:
        return
    try:
        if not po_token or not po_user:
            return
        payload = {"token": po_token, "user": po_user, "title": title, "message": body, "priority": 0}
        requests.post("https://api.pushover.net/1/messages.json", data=payload, timeout=10)
    except Exception as e:
        st.warning(f"Pushover failed: {e}")

def alert_once(pair: str, message: str):
    # rate‑limit duplicate alerts per pair (60s)
    t = time.time()
    last = st.session_state.alerted.get(pair, 0)
    if t - last < 60:
        return
    st.session_state.alerted[pair] = t
    # fire all enabled channels
    toast(message)
    send_email(subject=f"[Spike] {pair}", body_md=message)
    send_webhook(text=message)
    send_pushbullet(title=f"[Spike] {pair}", body=message)
    send_pushover(title=f"[Spike] {pair}", body=message)

# -------------------- WEBSOCKET --------------------
def ws_worker(product_ids: List[str], chunk_size: int):
    try:
        from websocket import WebSocketApp
    except Exception:
        st.session_state.ws_last_err = "websocket-client not installed. Add 'websocket-client' to requirements.txt"
        st.session_state.ws_running = False
        return

    url = EXCH_WS
    st.session_state.ws_last_err = ""
    st.session_state.ws_diag.append(f"{datetime.utcnow():%H:%M:%S} starting ws thread")

    def on_message(ws, msg):
        try:
            data = json.loads(msg)
            if isinstance(data, dict) and data.get("type") == "ticker":
                pid = data.get("product_id")
                price = data.get("price")
                if pid and price is not None:
                    try:
                        st.session_state.ws_prices[pid] = float(price)
                    except Exception:
                        pass
        except Exception:
            pass

    def on_error(ws, err):
        m = f"{datetime.utcnow():%H:%M:%S} error: {err}"
        st.session_state.ws_last_err = m
        st.session_state.ws_diag.append(m)

    def on_close(ws, *args):
        st.session_state.ws_running = False
        st.session_state.ws_diag.append(f"{datetime.utcnow():%H:%M:%S} closed ws")

    def on_open(ws):
        st.session_state.ws_diag.append(f"{datetime.utcnow():%H:%M:%S} ws open")
        chunks = [product_ids[i:i + chunk_size] for i in range(0, len(product_ids), chunk_size)]
        for ch in chunks:
            sub = {"name": "ticker", "product_ids": ch}
            ws.send(json.dumps({"type": "subscribe", "channels": [sub]}))
            time.sleep(0.25)

    ws = WebSocketApp(url, on_open=on_open, on_message=on_message, on_error=on_error, on_close=on_close)
    st.session_state.ws_running = True
    try:
        ws.run_forever(ping_interval=25, ping_timeout=10)
    except Exception as e:
        st.session_state.ws_last_err = f"Exception: {e}"
    st.session_state.ws_running = False

def control_ws(product_ids: List[str], chunk_size: int, want_start: bool, want_stop: bool):
    if want_start and not st.session_state.ws_running:
        st.session_state.ws_prices = {}
        t = threading.Thread(target=ws_worker, args=(product_ids, chunk_size), daemon=True)
        t.start()
        st.session_state.ws_thread = t
    if want_stop and st.session_state.ws_running:
        st.session_state.ws_last_err = "Stop requested. Refresh page to fully disconnect."
        st.session_state.ws_running = False

# -------------------- UNIVERSE --------------------
if use_watchlist and wl_text.strip():
    pairs = [x.strip().upper() for x in wl_text.split(",") if x.strip()]
else:
    pairs = discover_pairs(quote_currency)

pairs = pairs[:max_pairs]
st.caption(f"Tracking {len(pairs)} pairs ending in -{quote_currency.upper()}.")

if mode.startswith("WebSocket"):
    control_ws(pairs, ws_chunk, start_ws, stop_ws)

# -------------------- DATA --------------------
rows: List[Dict] = []

if not tf_selected:
    st.warning("Please select at least one timeframe.")
else:
    with st.spinner("Collecting prices and indicators…"):
        for pid in pairs:
            row: Dict[str, Optional[float]] = {"Pair": pid}

            # % change columns
            per_tf: List[Optional[float]] = []
            for lbl in tf_selected:
                pct = pct_change_from_candles(pid, TF_CHOICES[lbl])
                row[f"% {lbl}"] = pct
                per_tf.append(pct)

            # aggregate
            clean = [v for v in per_tf if isinstance(v, (float, int))]
            row["% ALL avg"] = sum(clean)/len(clean) if clean else None
            row["% ALL max_abs"] = max(clean, key=lambda x: abs(x)) if clean else None

            # latest price (REST fallback even in hybrid)
            if mode.startswith("WebSocket"):
                px = st.session_state.ws_prices.get(pid)
                if px is None:
                    px = rest_spot_price(pid)
                row["Last price"] = px
            else:
                row["Last price"] = rest_spot_price(pid)

            # Indicators + spikes
            ind = compute_indicators(pid, ind_gran, rsi_len, macd_fast, macd_slow, macd_signal, vol_window, vol_z_thresh)
            row.update(ind)

            # any spike?
            row["Any_Spike"] = bool(ind["Vol_Spike"] or ind["RSI_Spike"] or ind["MACD_Spike"])

            # optional alert (fire once per minute per pair)
            if row["Any_Spike"]:
                reasons = []
                if ind["Vol_Spike"] and ind["VolZ"] is not None: reasons.append(f"VolZ={ind['VolZ']:.2f}")
                if ind["RSI_Spike"] and ind["RSI"] is not None: reasons.append(f"RSI={ind['RSI']:.1f}")
                if ind["MACD_Spike"] and ind["MACD_Hist"] is not None: reasons.append(f"MACD flip ({ind['MACD_Hist']:.4g})")
                msg = f"{pid} spike — " + ", ".join(reasons) if reasons else f"{pid} spike"
                alert_once(pid, msg)

            rows.append(row)

# -------------------- DIAGNOSTICS --------------------
with st.expander("Diagnostics"):
    diag = {
        "mode": mode,
        "ws_running": st.session_state.ws_running,
        "ws_err": st.session_state.ws_last_err,
        "tracked_pairs": len(pairs),
        "products_first3": pairs[:3],
        "ws_prices_count": len(st.session_state.ws_prices),
        "time": f"{datetime.utcnow():%H:%M:%S}Z",
    }
    st.json(diag)
    if st.session_state.ws_diag:
        st.write("debug_tail:", st.session_state.ws_diag[-5:])

if st.session_state.ws_last_err:
    st.error(st.session_state.ws_last_err)

# -------------------- RENDER --------------------
df = pd.DataFrame(rows)

if df.empty:
    st.info("Waiting for data… Try fewer pairs or timeframes.")
else:
    # Spike list on top
    spike_df = df[df["Any_Spike"]].copy()
    if not spike_df.empty:
        spike_df = spike_df.sort_values(
            by=top_spike_metric if top_spike_metric in spike_df.columns else "% ALL max_abs",
            ascending=False, na_position="last"
        ).head(top_spike_size)
        st.subheader("🔥 Top Spike List")
        cols_to_show = ["Pair", "Last price", "VolZ", "RSI", "MACD_Hist", "% ALL max_abs", "% ALL avg"] + [c for c in df.columns if c.startswith("% ")]
        cols_to_show = [c for c in cols_to_show if c in spike_df.columns]
        st.dataframe(spike_df[cols_to_show], use_container_width=True)

    st.subheader("All pairs ranked by movement & momentum")

    # main table
    view = df.copy()
    if show_spikes_only:
        view = view[view["Any_Spike"]]

    ascending = not descending
    if sort_metric not in view.columns:
        sort_metric = "% ALL avg"
    view = view.sort_values(by=sort_metric, ascending=ascending, na_position="last").reset_index(drop=True)

    # style helpers
    def fmt_pct(v):
        return f"{v:.2f}%" if isinstance(v, (float, int)) else "—"

    def row_highlight(row):
        color = "background-color: #103f10; color: #d9ffd9;" if row.get("Any_Spike") else ""
        return [color] * len(row)

    pretty = view.copy()
    for c in [col for col in pretty.columns if col.startswith("% ")] + ["% ALL avg", "% ALL max_abs"]:
        if c in pretty: pretty[c] = pretty[c].map(fmt_pct)
    if "RSI" in pretty:          pretty["RSI"] = pretty["RSI"].map(lambda v: f"{v:.1f}" if isinstance(v, (float, int)) else "—")
    for c in ["MACD", "MACD_Signal", "MACD_Hist", "VolZ", "Last price"]:
        if c in pretty: pretty[c] = pretty[c].map(lambda v: f"{v:.6g}" if isinstance(v, (float, int)) else "—")

    styler = pretty.style.apply(row_highlight, axis=1)
    st.dataframe(styler, use_container_width=True, height=720)

with st.expander("Notes"):
    st.markdown(
        """
- **Spike rules**  
  - **VolZ** spike: latest volume Z‑score ≥ threshold.  
  - **RSI** spike: crosses 30↑ or 70↓ on last bar.  
  - **MACD** spike: histogram sign flip on last bar.  
- **Alerts** fire to any enabled channels and are rate‑limited (1 per pair per 60s).  
- **Pushbullet**: paste your Access Token from https://www.pushbullet.com/#settings/account  
- **Pushover**: create an App/API token + your User/Group key from https://pushover.net/  
- If you hit API limits, reduce **Max pairs** or timeframes, raise refresh interval, or use **REST only**.
        """
    )

