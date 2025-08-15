# app.py — Coinbase Fast Movers — Pro (with ATR/RSI/MACD gates, Pushover/Telegram, history, test button)

import os, json, time, threading, queue, ssl, datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import smtplib
import streamlit as st

# ---------- optional autorefresh helper (safe fallback if missing)
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

# ---------- Page
st.set_page_config(page_title="Coinbase Fast Movers — Pro", layout="wide")
st.title("Coinbase Fast Movers — Pro Spike Scanner")

# ---------- Durable paths
LOG_PATH = os.environ.get("FM_LOG_PATH", "/tmp/fast_movers_log.csv")
HASHES_PATH = os.environ.get("FM_HASHES_PATH", "/tmp/fast_movers_hashes.json")

# ---------- Session state
def init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("last_ticks", {})          # product_id -> last trade price
    ss.setdefault("last_bbo", {})            # product_id -> (bid, ask)
    ss.setdefault("last_alert_hashes", set())
    ss.setdefault("last_alert_time", {})     # (pair, tf) -> epoch seconds
    ss.setdefault("spike_history", [])       # list of dict rows
    if os.path.exists(HASHES_PATH) and not ss["last_alert_hashes"]:
        try:
            with open(HASHES_PATH, "r") as f:
                ss["last_alert_hashes"] = set(json.load(f))
        except:
            pass
init_state()

# ---------- CSS
def inject_css_scale(scale: float):
    st.markdown(f"""
    <style>
      html {{ font-size: {scale}rem; }}
      .stDataFrame table {{ font-size: {scale}rem; }}
      .small-muted {{ opacity: 0.75; font-size: 0.9em; }}
      .linklike a {{ text-decoration: none; }}
    </style>
    """, unsafe_allow_html=True)

# ---------- Browser beep (WebAudio, no network)
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

# Coinbase-supported granularities: 60,300,900,3600,21600,86400
TFS = {"1m":60, "5m":300, "15m":900, "1h":3600, "6h":21600, "1d":86400}

@st.cache_data(show_spinner=False, ttl=300)
def fetch_products_raw():
    r = requests.get(f"{CB_BASE}/products", timeout=15)
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
            if not arr: return None
            df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
            return df.sort_values("ts").reset_index(drop=True)
        if r.status_code in (429,500,502,503):
            time.sleep(0.4*(attempt+1))
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
        if r.status_code in (429,500,502,503):
            time.sleep(0.4*(attempt+1))
        else:
            break
    return {}

def volume_usd_est(stats: dict) -> float:
    try:
        last = float(stats.get("last"))
        vol_base = float(stats.get("volume"))
        return last * vol_base
    except:
        return 0.0

def top_n_by_24h_volume_usd(product_ids, n=100):
    vals = []
    for pid in product_ids:
        s = fetch_product_stats(pid) or {}
        v = volume_usd_est(s)
        if v > 0: vals.append((pid, v))
    vals.sort(key=lambda x: x[1], reverse=True)
    return [pid for pid,_ in vals[:n]]

# ---------- WebSocket worker
def ws_worker(pairs, channel="ticker", endpoint="wss://ws-feed.exchange.coinbase.com"):
    ss = st.session_state
    try:
        ws = websocket.WebSocket()
        ws.connect(endpoint, timeout=10)
        ws.send(json.dumps({"type":"subscribe","channels":[{"name":channel,"product_ids":pairs}]}))
        ss["ws_alive"] = True
        while ss.get("ws_alive", False):
            msg = ws.recv()
            if msg: ss["ws_q"].put_nowait(("msg", time.time(), msg))
    except Exception as e:
        ss["ws_q"].put_nowait(("err", time.time(), str(e)))
    finally:
        ss["ws_alive"] = False

def drain_ws_queue():
    if not (st.session_state.get("ws_alive") and WS_AVAILABLE): return
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
            except: pass
        drained += 1

# ---------- Alerts: Email / Generic Webhook / Pushover / Telegram
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
        return (200 <= r.status_code < 300), (r.text if r.status_code >= 300 else "OK")
    except Exception as e:
        return False, str(e)

def fanout_webhooks(urls_csv, title, lines):
    errs = []; any_ok = False
    for url in [u.strip() for u in urls_csv.split(",") if u.strip()]:
        ok, info = post_webhook(url, title, lines)
        any_ok = any_ok or ok
        if not ok: errs.append(f"{url}: {info}")
    return any_ok, "; ".join(errs) if errs else "OK"

def pushover_send(app_token, user_key, title, message):
    try:
        r = requests.post("https://api.pushover.net/1/messages.json",
                          data={"token": app_token, "user": user_key, "title": title, "message": message},
                          timeout=10)
        return (200 <= r.status_code < 300), r.text
    except Exception as e:
        return False, str(e)

def telegram_send(bot_token, chat_id, text):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        return (200 <= r.status_code < 300), r.text
    except Exception as e:
        return False, str(e)

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
        except: continue
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
            rec[f"MACD {tf_name}"] = float(m_line.iloc[-1] - s_line.iloc[-1])  # macd diff
            rec[f"MACDh {tf_name}"] = float(hist.iloc[-1])                     # macd hist

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
                     gate_by_macd=False, use_atr=False, atr_mult=2.0):
    df = df.copy()
    pt_col = f"% {sort_tf}"
    vs_col = f"Vol x {sort_tf}"
    rsi_col = f"RSI {sort_tf}"
    macdh_col = f"MACDh {sort_tf}"
    atr_col = f"ATR {sort_tf}"

    spike_mask = (df[pt_col].abs() >= spike_thresh) & (df[vs_col] >= vol_mult)
    if gate_by_rsi and rsi_col in df.columns:
        spike_mask &= ((df[rsi_col] >= rsi_overbought) | (df[rsi_col] <= rsi_oversold))
    if gate_by_macd and macdh_col in df.columns:
        # simple MACD "impulse": histogram magnitude above its median absolute deviation
        mad = (df[macdh_col] - df[macdh_col].median()).abs().median()
        spike_mask &= (df[macdh_col].abs() >= (mad + 1e-9))
    if use_atr and atr_col in df.columns:
        atr_pct = (df[atr_col] / (df["Last"].replace(0, np.nan))) * 100.0
        spike_mask &= (df[pt_col].abs() >= (atr_pct * atr_mult))

    GREEN_ROW = 'background-color: rgba(0, 255, 0, 0.12); font-weight: 600;'
    RED_CELL  = 'background-color: rgba(255, 0, 0, 0.10);'
    BLUE_CELL = 'background-color: rgba(0, 0, 255, 0.10);'

    def _row_style(r):
        styles = []
        for c in df.columns:
            s = GREEN_ROW if spike_mask.loc[r.name] else ''
            if c == rsi_col and pd.notna(r[c]):
                if r[c] >= rsi_overbought: s += RED_CELL
                elif r[c] <= rsi_oversold: s += BLUE_CELL
            styles.append(s)
        return styles

    return spike_mask, df.style.apply(_row_style, axis=1)

# ---------- Sidebar Controls
with st.sidebar:
    st.subheader("Mode")
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0)
    if mode.startswith("WebSocket") and not WS_AVAILABLE:
        st.warning("`websocket-client` not installed. Falling back to REST.")
        mode = "REST only"
    if st.button("Restart stream"):
        st.session_state["ws_alive"] = False
        time.sleep(0.3)
        st.session_state["ws_thread"] = None

    st.subheader("Universe")
    products_raw = fetch_products_raw()
    all_quotes = ["ANY"] + unique_quotes(products_raw)
    quote_pick = st.selectbox("Quote currency (filter)", all_quotes, index=0)
    base_universe = sorted({p.get("base_currency") for p in products_raw if p.get("base_currency")})
    base_sel = st.multiselect("Base filter (optional)", options=base_universe, default=[])
    exclude_patterns = st.text_input("Exclude bases (comma‑sep, pattern match)", "BULL,BEAR,DOWN,UP")
    min_24h_usd = st.number_input("Min 24h USD volume (pre-filter)", 0.0, 1e10, 0.0, step=1000.0,
                                  help="Filter illiquid pairs using /stats volume × last")

    st.markdown("**Top‑N by 24h Volume (pre-filter)**")
    enable_topn = st.checkbox("Enable Top‑N by 24h USD volume", value=False)
    topn = st.slider("Top N", 10, 500, 100, 10, disabled=not enable_topn)

    max_pairs = st.slider("Max pairs to include (safety cap)", 10, 1000, 500, 10)

    st.subheader("Timeframes & Change Window")
    pick_tfs = st.multiselect("Select timeframes (≥1)", list(TFS.keys()),
                              default=["1m","5m","15m","1h","4h","6h","1d"])
    sort_tf = st.selectbox("Primary timeframe to rank by", pick_tfs, index=0)
    sort_desc = st.checkbox("Sort descending (largest first)", value=True)
    bars_back = st.slider("Bars back (global default)", 1, 20, 1, 1,
                          help="1 = last vs previous bar; 5 = last vs 5 bars ago")
    bars_back_map_text = st.text_input("Per‑TF bars back (e.g. 1m=3,5m=2)", "")

    st.subheader("Spike Rule & Gates")
    rsi_len = st.number_input("RSI period", 5, 50, 14, 1)
    macd_fast = st.number_input("MACD fast EMA", 3, 50, 12, 1)
    macd_slow = st.number_input("MACD slow EMA", 5, 100, 26, 1)
    macd_sig  = st.number_input("MACD signal", 3, 50, 9, 1)
    vol_mult  = st.number_input("Volume spike multiple (x20‑SMA)", 1.0, 20.0, 3.0, 0.1)
    spike_thresh = st.number_input("Price spike threshold (% on sort TF)", 0.5, 50.0, 3.0, 0.5)
    rsi_overb = st.number_input("RSI overbought", 50, 100, 70, 1)
    rsi_overS = st.number_input("RSI oversold", 0, 50, 30, 1)
    gate_by_rsi = st.checkbox("Gate spikes by RSI extremes", value=False)
    gate_by_macd = st.checkbox("Gate spikes by MACD impulse", value=False)
    use_atr = st.checkbox("Require ATR‑normalized move", value=False)
    atr_len = st.slider("ATR length", 5, 50, 14, 1, disabled=not use_atr)
    atr_mult = st.slider("ATR multiple (|ΔP| ≥ ATR% × m)", 0.5, 5.0, 2.0, 0.1, disabled=not use_atr)

    st.subheader("Notifications")
    enable_sound = st.checkbox("Audible chime (browser)", value=True)
    email_to = st.text_input("Email recipient (optional)", "", placeholder="you@phone-sms-gateway or any email")
    webhooks_csv = st.text_input("Webhook URLs (comma‑separated)", "",
                                 placeholder="Discord/Slack/Generic webhook(s)")
    pushover_app = st.text_input("Pushover App Token", "")
    pushover_user = st.text_input("Pushover User Key", "")
    tg_token = st.text_input("Telegram Bot Token", "")
    tg_chat_id = st.text_input("Telegram Chat ID", "")
    cooldown_min = st.slider("Per‑pair cooldown (minutes)", 0, 120, 10, 5)
    max_alerts_hour = st.slider("Max alerts per hour", 1, 500, 120, 1)
    alert_template = st.text_area(
        "Alert line template",
        "{pair} {pct:+.2f}% on {tf} | Last {last:.6g} | RSI {rsi:.1f} | Volx {volx:.2f}",
        height=72
    )

    if st.button("Test Alert (sound + all channels)"):
        if enable_sound: trigger_beep()
        sub = "[Test] Coinbase Fast Movers"
        body = "This is a test alert from the app."
        errs = []
        if email_to:
            ok, info = send_email_alert(sub, body, email_to)
            if not ok: errs.append(f"Email: {info}")
        if webhooks_csv:
            ok, info = fanout_webhooks(webhooks_csv, sub, [body])
            if not ok: errs.append(f"Webhook(s): {info}")
        if pushover_app and pushover_user:
            ok, info = pushover_send(pushover_app, pushover_user, sub, body)
            if not ok: errs.append(f"Pushover: {info}")
        if tg_token and tg_chat_id:
            ok, info = telegram_send(tg_token, tg_chat_id, f"{sub}\n{body}")
            if not ok: errs.append(f"Telegram: {info}")
        st.success("Test dispatched." if not errs else " ; ".join(errs))

    st.subheader("Quiet Hours")
    tz_pick = st.selectbox("Time zone", ["UTC","America/New_York","America/Chicago","America/Denver","America/Los_Angeles"], index=4)
    quiet_on = st.checkbox("Enable quiet hours (suppress push alerts)", value=False)
    q_start = st.time_input("Quiet start", dt.time(22,0))
    q_end = st.time_input("Quiet end", dt.time(7,0))

    st.subheader("WebSocket / Spread Guard")
    max_ws_sub = st.slider("WS subscribe chunk size", 2, 200, 50, 1)
    spread_guard_on = st.checkbox("Require spread below max (bps)", value=False)
    max_spread_bps = st.slider("Max spread (bps = 0.01%)", 1, 200, 50, 1, disabled=not spread_guard_on)

    st.subheader("Display & Ops")
    font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05)
    refresh_seconds = st.slider("Autorefresh every (seconds)", 0, 120, 15, 1)
    show_heatmap = st.checkbox("Heatmap view (TF vs Pair)", value=False)
    enable_export = st.checkbox("Enable CSV export", value=True)
    persist_state = st.checkbox("Persist logs & hashes to disk", value=True)

inject_css_scale(font_scale)
audible_bridge()

# --- Autorefresh
if refresh_seconds > 0:
    if HAS_AUTOREFRESH:
        st_autorefresh(interval=int(refresh_seconds*1000), key="auto_ref")
    else:
        st.markdown(
            f"<script>setTimeout(() => window.location.reload(), {int(refresh_seconds*1000)});</script>",
            unsafe_allow_html=True
        )

# ---------- Build Universe
def match_excluded(base_symbol: str, patterns: str) -> bool:
    pats = [p.strip().upper() for p in patterns.split(",") if p.strip()]
    s = (base_symbol or "").upper()
    return any(p in s for p in pats)

if quote_pick == "ANY":
    pairs_all = list_products_filtered(quote_currency=None,
                                       base_filter=set(base_sel) if base_sel else None)
else:
    pairs_all = list_products_filtered(quote_currency=quote_pick,
                                       base_filter=set(base_sel) if base_sel else None)

# exclude patterns (leveraged tokens, etc.)
pairs_all = [pid for pid in pairs_all if not match_excluded(pid.split("-")[0], exclude_patterns)]

# Pre-filter by min 24h USD volume
if min_24h_usd > 0:
    keep = []
    for pid in pairs_all:
        v = volume_usd_est(fetch_product_stats(pid) or {})
        if v >= min_24h_usd:
            keep.append(pid)
    pairs_all = keep

# Optional Top-N by 24h volume
if enable_topn and pairs_all:
    pairs_all = top_n_by_24h_volume_usd(pairs_all, n=topn)

if not pairs_all:
    st.stop()

pairs = pairs_all[:max_pairs]

# ---------- WebSocket boot & ingest
diag = {"WS_AVAILABLE": WS_AVAILABLE, "ws_alive": False, "active_ws_url": "", "ws_pairs": 0}
if mode.startswith("WebSocket") and WS_AVAILABLE:
    if not st.session_state["ws_alive"]:
        pick = pairs[:max(2, min(max_ws_sub, len(pairs)))]
        t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start()
        st.session_state["ws_thread"] = t
        time.sleep(0.2)
    diag["ws_alive"] = bool(st.session_state["ws_alive"])
    diag["active_ws_url"] = "wss://ws-feed.exchange.coinbase.com"
    diag["ws_pairs"] = min(max_ws_sub, len(pairs))
    drain_ws_queue()

with st.expander("Diagnostics", expanded=False):
    st.json(diag)

# ---------- Compute view
bars_back_map = parse_bars_back_map(bars_back_map_text)
try:
    view = compute_view(
        pairs=pairs,
        timeframes=pick_tfs,
        rsi_len=rsi_len,
        macd_fast=macd_fast,
        macd_slow=macd_slow,
        macd_sig=macd_sig,
        bars_back=bars_back,
        bars_back_map=bars_back_map,
        ticks=st.session_state.get("last_ticks", {}),
        atr_len=atr_len if use_atr else 14,
    )
except Exception as e:
    st.error(f"Error while computing view: {e}")
    st.stop()

if len(view) == 0:
    st.info("No data… try different filters or a smaller cap.")
    st.stop()

# TradingView link
def tv_symbol(pid: str):
    base, quote = pid.split("-")
    return f"https://www.tradingview.com/chart/?symbol=COINBASE%3A{base}{quote}"

view["Chart"] = [f"[📈]({tv_symbol(pid)})" for pid in view["Pair"]]

# ---------- Sort
sort_col = f"% {sort_tf}"
if sort_col in view.columns:
    view = view.sort_values(sort_col, ascending=not sort_desc, na_position="last")
else:
    st.warning(f"Sort column {sort_col} missing.")

# ---------- Spike highlight + Top 10
spike_mask, styled = highlight_spikes(
    view, sort_tf, rsi_overb, rsi_overS, vol_mult, spike_thresh,
    gate_by_rsi=gate_by_rsi, gate_by_macd=gate_by_macd,
    use_atr=use_atr, atr_mult=atr_mult
)

top_now = view.loc[spike_mask, ["Pair", sort_col]].head(10)

# ---------- Heatmap (optional)
if show_heatmap:
    hm = view[["Pair"] + [f"% {tf}" for tf in pick_tfs if f"% {tf}" in view.columns]].set_index("Pair")
    st.subheader("Heatmap — % Change by Timeframe")
    st.dataframe(hm.style.background_gradient(axis=None), use_container_width=True)

# ---------- Panels
colL, colR = st.columns([1,3], gap="large")
with colL:
    st.subheader("Top 10 Movers")
    st.dataframe(
        top_now.rename(columns={sort_col: f"% {sort_tf}"}) if not top_now.empty
        else pd.DataFrame({"Pair": [], f"% {sort_tf}": []}),
        use_container_width=True
    )

    if enable_export:
        csv = view.to_csv(index=False).encode()
        st.download_button("Export table (CSV)", csv, "fast_movers.csv", "text/csv")

with colR:
    st.subheader("All Pairs Ranked by Movement")
    display_cols = ["Chart","Pair","Last"] + \
        [c for c in view.columns if c.startswith("% ")] + \
        [c for c in view.columns if c.startswith("Vol x ")] + \
        [c for c in view.columns if c.startswith("RSI ")] + \
        [c for c in view.columns if c.startswith("MACD ")] + \
        [c for c in view.columns if c.startswith("MACDh ")] + \
        [c for c in view.columns if c.startswith("ATR ")]
    display_cols = [c for c in display_cols if c in view.columns]
    styled = styled.set_properties(subset=["Chart"], **{"text-align":"center"})
    st.dataframe(styled, use_container_width=True)

# ---------- Utilities
def within_quiet_hours(now_utc, tzname, start_t: dt.time, end_t: dt.time):
    try:
        tz = ZoneInfo(tzname)
    except:
        tz = ZoneInfo("UTC")
    local = now_utc.astimezone(tz)
    start_dt = dt.datetime.combine(local.date(), start_t, tzinfo=tz)
    end_dt = dt.datetime.combine(local.date(), end_t, tzinfo=tz)
    if start_dt <= end_dt:
        return start_dt <= local <= end_dt
    return local >= start_dt or local <= end_dt  # crosses midnight

def can_send(pair, tf, now_ts: float, cooldown_min: int) -> bool:
    key = (pair, tf)
    last = st.session_state["last_alert_time"].get(key, 0)
    return (now_ts - last) >= cooldown_min * 60

def mark_sent(pair, tf, now_ts: float):
    st.session_state["last_alert_time"][(pair, tf)] = now_ts

def compute_spread_bps(pid: str):
    bbo = st.session_state["last_bbo"].get(pid)
    if not bbo: return None
    bid, ask = bbo
    if bid is None or ask is None or bid <= 0 or ask <= 0: return None
    mid = 0.5 * (bid + ask)
    return ((ask - bid) / mid) * 10000  # bps

# ---------- Alerting (new spikes only + cooldown + caps + spread guard + quiet hours + history)
now_ts = time.time()
now_utc = dt.datetime.utcfromtimestamp(now_ts).replace(tzinfo=ZoneInfo("UTC"))

new_spikes = []
sent_this_hour = sum(1 for k in st.session_state["last_alert_hashes"]
                     if now_ts - float(k.split("|")[-1]) < 3600)

if not top_now.empty:
    for _, row in top_now.iterrows():
        pair = row["Pair"]; pct = float(row[sort_col]); last = float(view.loc[view["Pair"]==pair, "Last"].iloc[0])
        if spread_guard_on:
            sp = compute_spread_bps(pair)
            if sp is None or sp > max_spread_bps:
                continue
        key_simple = f"{pair}|{sort_tf}|{round(pct,2)}"
        if key_simple in st.session_state["last_alert_hashes"]:
            continue
        if not can_send(pair, sort_tf, now_ts, cooldown_min):
            continue
        if sent_this_hour >= max_alerts_hour:
            break

        rsi_col = f"RSI {sort_tf}"
        vol_col = f"Vol x {sort_tf}"
        rsi_v = view.loc[view["Pair"]==pair, rsi_col].iloc[0] if rsi_col in view.columns else np.nan
        volx_v = view.loc[view["Pair"]==pair, vol_col].iloc[0] if vol_col in view.columns else np.nan

        line = alert_template.format(pair=pair, pct=pct, tf=sort_tf, last=last, rsi=rsi_v, volx=volx_v)
        new_spikes.append((pair, pct, line))
        st.session_state["last_alert_hashes"].add(f"{key_simple}|{now_ts}")
        mark_sent(pair, sort_tf, now_ts)
        sent_this_hour += 1

# Beep
if new_spikes and enable_sound:
    trigger_beep()

# Quiet hours
suppress_push = quiet_on and within_quiet_hours(now_utc, tz_pick, q_start, q_end)

# Dispatch alerts
if new_spikes and not suppress_push and (email_to or webhooks_csv or pushover_app and pushover_user or tg_token and tg_chat_id):
    sub = f"[Coinbase] Spike(s) on {sort_tf}"
    body_lines = [ln for _,_,ln in new_spikes]
    errs = []
    if email_to:
        ok, info = send_email_alert(sub, "\n".join(body_lines), email_to)
        if not ok: errs.append(info)
    if webhooks_csv:
        ok, info = fanout_webhooks(webhooks_csv, sub, body_lines)
        if not ok: errs.append(info)
    if pushover_app and pushover_user:
        ok, info = pushover_send(pushover_app, pushover_user, sub, "\n".join(body_lines))
        if not ok: errs.append(info)
    if tg_token and tg_chat_id:
        ok, info = telegram_send(tg_token, tg_chat_id, f"{sub}\n" + "\n".join(body_lines))
        if not ok: errs.append(info)
    if errs: st.warning("; ".join(errs))

# History (append + show)
if new_spikes:
    for pair, pct, line in new_spikes:
        st.session_state["spike_history"].append({
            "ts": dt.datetime.utcnow().isoformat(timespec="seconds"),
            "pair": pair, "tf": sort_tf, "pct": round(pct, 3), "detail": line
        })

with st.expander("Spike History (latest first)", expanded=False):
    if st.session_state["spike_history"]:
        hist_df = pd.DataFrame(st.session_state["spike_history"])[::-1].reset_index(drop=True)
        st.dataframe(hist_df, use_container_width=True)
    else:
        st.write("—")

# Persist logs / hashes
if persist_state:
    try:
        with open(HASHES_PATH, "w") as f:
            json.dump(list(st.session_state["last_alert_hashes"]), f)
    except Exception as e:
        st.caption(f"Could not persist hashes: {e}")
    if new_spikes:
        rows = []
        for pair, pct, line in new_spikes:
            rows.append({
                "ts": dt.datetime.utcnow().isoformat(),
                "pair": pair,
                "tf": sort_tf,
                "pct": pct,
                "line": line
            })
        try:
            df_new = pd.DataFrame(rows)
            if os.path.exists(LOG_PATH):
                df_prev = pd.read_csv(LOG_PATH)
                df_out = pd.concat([df_prev, df_new], ignore_index=True)
            else:
                df_out = df_new
            df_out.to_csv(LOG_PATH, index=False)
        except Exception as e:
            st.caption(f"Could not write log: {e}")

# Footer
st.caption(
    f"Pairs scanned: {len(view)} • Sorted by: {sort_tf} • Mode: {mode} • "
    f"Cooldown: {cooldown_min}m • Cap/hr: {max_alerts_hour} • Quiet hours: {'ON' if suppress_push else 'OFF'}"
)
