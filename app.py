# app.py — Coinbase Movers (Top-10 Spike, gated, single file)
# Minimal table: Pair | Price | % Change | TF
# Spike Gates panel with checkboxes; Top-10 & green tint only for rows passing ALL enabled gates.
# Alerts: Email / Webhook / Pushover + browser chime; "Send TEST alert" verifies end-to-end.
#
# requirements.txt:
# streamlit>=1.33
# pandas>=2.2
# numpy>=1.26
# requests>=2.32
# websocket-client>=1.8

import os, json, time, threading, queue, datetime as dt, base64, ssl, smtplib
import pandas as pd
import numpy as np
import requests
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------------- Optional WebSocket client ----------------
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

CB_REST = "https://api.exchange.coinbase.com"
CB_WS   = "wss://ws-feed.exchange.coinbase.com"

# ---------------- Session-state helpers -------------------
def init_state():
    ss = st.session_state
    ss.setdefault("products_all", [])
    ss.setdefault("bases_all", [])
    ss.setdefault("product_stats", {})
    ss.setdefault("bars", {})          # bars[pid][tf] -> list of dicts
    ss.setdefault("last_tick", {})     # pid -> {price,size,time,bid,ask}
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("last_alert_hashes", set())
    ss.setdefault("test_requested", False)
init_state()

def ss_get(key, default):
    if key not in st.session_state:
        st.session_state[key] = default() if callable(default) else default
    return st.session_state[key]

# ---------------- Timeframes ------------------------------
TFS = {
    "15s": 15, "30s": 30, "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400,  # synth from 1h
    "6h": 21600,              # REST
    "12h": 43200,             # synth from 1h
    "1d": 86400               # REST
}
REST_GRANS = {60,300,900,3600,21600,86400}

# ---------------- Maths / indicators ----------------------
def pct(a, b):
    if b is None or a is None or b == 0: return np.nan
    return (a/b - 1.0)*100.0

def ema(x, span): return x.ewm(span=span, adjust=False).mean()

def rsi(close, length=14):
    delta = close.diff()
    up = np.where(delta>0, delta, 0.0)
    down = np.where(delta<0, -delta, 0.0)
    roll_up = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    roll_dn = pd.Series(down, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / (roll_dn + 1e-9)
    return 100 - (100/(1+rs))

def macd(close, fast=12, slow=26, signal=9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def bucket_end(ts, seconds): return int(ts - (ts % seconds) + seconds)

# ---------------- REST helpers ----------------------------
def list_products(quote_currency="USD"):
    r = requests.get(f"{CB_REST}/products", timeout=20)
    r.raise_for_status()
    data = r.json()
    pairs = [
        p["id"] for p in data
        if p.get("quote_currency")==quote_currency
        and p.get("status") in {"online", "online_trading"}
        and not p.get("trading_disabled")
    ]
    return sorted(pairs), data

def fetch_stats(pid):
    try:
        r = requests.get(f"{CB_REST}/products/{pid}/stats", timeout=10)
        if r.status_code==200: return r.json()
    except Exception: pass
    return {}

def fetch_candles(pair, granularity_sec):
    if granularity_sec not in REST_GRANS:
        return None
    r = requests.get(f"{CB_REST}/products/{pair}/candles?granularity={granularity_sec}", timeout=15)
    if r.status_code!=200: return None
    arr = r.json()
    if not arr: return None
    df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
    df["ts"]=pd.to_datetime(df["ts"],unit="s",utc=True)
    df=df.sort_values("ts").reset_index(drop=True)
    return df.rename(columns={"open":"o","high":"h","low":"l","close":"c","volume":"v"})

# ---------------- WS ingest (optional) --------------------
def on_tick(pid, price, size, t_unix, bid=None, ask=None):
    ss_get("last_tick", dict)
    st.session_state["last_tick"][pid] = {"price":price,"size":size,"time":t_unix,"bid":bid,"ask":ask}
    base_tfs = ["15s","30s","1m","3m","5m","15m","30m","1h"]
    ss_get("bars", dict)
    st.session_state["bars"].setdefault(pid, {})
    for tf in base_tfs:
        secs=TFS[tf]; bars=st.session_state["bars"][pid].setdefault(tf, [])
        endt = bucket_end(t_unix, secs)
        if bars and bars[-1]["t"]==endt:
            b=bars[-1]; b["h"]=max(b["h"],price); b["l"]=min(b["l"],price); b["c"]=price; b["v"]+=size
        else:
            bars.append({"t":endt,"o":price,"h":price,"l":price,"c":price,"v":size})
            if len(bars)>600: del bars[:len(bars)-600]

def ws_worker(pairs, endpoint=CB_WS):
    ss = st.session_state
    try:
        ws = websocket.WebSocket(); ws.connect(endpoint, timeout=10)
        chunk=80
        for i in range(0,len(pairs),chunk):
            sub={"type":"subscribe","channels":[{"name":"ticker","product_ids":pairs[i:i+chunk]}]}
            ws.send(json.dumps(sub)); time.sleep(0.2)
        ss["ws_alive"]=True
        while ss.get("ws_alive", False):
            try:
                msg=ws.recv()
                if msg: ss["ws_q"].put_nowait(msg)
            except Exception: break
    except Exception as e:
        ss["ws_q"].put_nowait(json.dumps({"type":"error","message":str(e)}))
    finally:
        ss["ws_alive"]=False

def ws_ingest_pump():
    ss = st.session_state; did=0
    while not ss["ws_q"].empty() and did<800:
        raw = ss["ws_q"].get_nowait()
        try: d=json.loads(raw)
        except Exception: did+=1; continue
        if d.get("type")!="ticker": did+=1; continue
        pid=d.get("product_id")
        px=float(d.get("price") or 0.0) if d.get("price") else None
        sz=float(d.get("last_size") or 0.0) if d.get("last_size") else 0.0
        bid=float(d.get("best_bid")) if d.get("best_bid") else None
        ask=float(d.get("best_ask")) if d.get("best_ask") else None
        t_iso=d.get("time")
        if not (pid and px and t_iso): did+=1; continue
        t_unix=int(dt.datetime.fromisoformat(t_iso.replace("Z","+00:00")).timestamp())
        on_tick(pid, px, sz, t_unix, bid, ask)
        did+=1

# ---------------- Bars access ---------------------------
def get_bars_df(pid, tf):
    bars_store = ss_get("bars", dict)
    df = pd.DataFrame(bars_store.get(pid, {}).get(tf, []))
    if not df.empty:
        df["ts"]=pd.to_datetime(df["t"],unit="s",utc=True)
        return df.sort_values("ts")[["ts","o","h","l","c","v"]].tail(400).reset_index(drop=True)
    tf_to_rest={"1m":60,"5m":300,"15m":900,"1h":3600,"6h":21600,"1d":86400}
    if tf in tf_to_rest:
        df=fetch_candles(pid, tf_to_rest[tf])
        if df is not None:
            return df[["ts","o","h","l","c","v"]].tail(400).reset_index(drop=True)
    if tf in ("4h","12h"):
        h1=get_bars_df(pid,"1h")
        if h1 is None or h1.empty: return pd.DataFrame()
        rule="4H" if tf=="4h" else "12H"
        h1=h1.set_index(h1["ts"])
        o=h1["o"].resample(rule,label="right",closed="right").first()
        h=h1["h"].resample(rule,label="right",closed="right").max()
        l=h1["l"].resample(rule,label="right",closed="right").min()
        c=h1["c"].resample(rule,label="right",closed="right").last()
        v=h1["v"].resample(rule,label="right",closed="right").sum()
        out=pd.DataFrame({"ts":o.index,"o":o,"h":h,"l":l,"c":c,"v":v}).dropna().reset_index(drop=True)
        return out.tail(200)
    return pd.DataFrame()

# ---------------- Spike evaluation -----------------------
def compute_row(pid, tf, cfg):
    """
    Returns minimal row and 'all_ok' flag (ALL enabled gates must pass).
    """
    last_price = float(ss_get("last_tick", dict).get(pid, {}).get("price", np.nan))
    df = get_bars_df(pid, tf)
    if df is None or df.empty or len(df)<30:
        return {"Pair": pid, "Price": last_price, "Change%": np.nan, "TF": tf, "all_ok": False}

    close = df["c"].astype(float)
    vol   = df["v"].astype(float)

    n_back = 1 if tf in ("15s","30s","1m") else 2 if tf in ("3m","5m") else 3
    ref = close.iloc[-1-n_back] if len(close)>n_back else close.iloc[0]
    change = pct(close.iloc[-1], ref)
    price = float(close.iloc[-1]) if np.isfinite(close.iloc[-1]) else last_price

    # Gates (compute metrics)
    base = vol.rolling(20, min_periods=5).mean().iloc[-1]
    volx = float(vol.iloc[-1] / (base + 1e-9))

    rsi_vals = rsi(close, cfg["rsi_len"])
    N=3
    rsi_vel = float(rsi_vals.iloc[-1] - rsi_vals.iloc[-1-N]) if len(rsi_vals)>N else 0.0

    _, _, hist = macd(close, *cfg["macd"])
    macdh = hist.iloc[-20:]
    macdh_z = 0.0
    if macdh.std(ddof=0)>0:
        macdh_z = float((macdh.iloc[-1] - macdh.mean()) / (macdh.std(ddof=0)+1e-9))

    roc = pct(close.iloc[-1], close.iloc[-1-n_back]) if len(close)>n_back else 0.0

    # Evaluate ONLY enabled gates
    checks=[]
    if cfg["use_price"]:  checks.append(abs(change) >= cfg["price_thresh"].get(tf, 9e9))
    if cfg["use_vol"]:    checks.append(volx >= cfg["vol_mult"].get(tf, 9e9))
    if cfg["use_rsi"]:    checks.append(abs(rsi_vel) >= cfg["rsi_vel"].get(tf, 9e9))
    if cfg["use_macd"]:   checks.append(abs(macdh_z) >= cfg["macdh_z"].get(tf, 9e9))
    if cfg["use_mom"]:    checks.append(abs(roc) >= cfg["roc_pct"].get(tf, 9e9))

    all_ok = (len(checks)==0) or all(checks) if cfg["apply_gates"] else False

    return {
        "Pair": pid, "Price": price, "Change%": float(change) if np.isfinite(change) else np.nan,
        "TF": tf, "all_ok": bool(all_ok)
    }

def build_table(pairs, tf, cfg):
    rows=[compute_row(pid, tf, cfg) for pid in pairs]
    return pd.DataFrame(rows)

# ---------------- Alerts ----------------------------------
def _smtp_cfg():
    return st.secrets.get("smtp")

def send_email_alert(subject, body, recipient):
    cfg=_smtp_cfg()
    if not cfg: return False, "SMTP not configured (st.secrets['smtp'])."
    try:
        msg=MIMEMultipart(); msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body,"plain"))
        ctx = ssl.create_default_context()   # FIX: no 'with' here
        with smtplib.SMTP_SSL(cfg["host"], int(cfg.get("port",465)), context=ctx) as s:
            s.login(cfg["user"], cfg["password"]); s.sendmail(cfg["sender"], recipient, msg.as_string())
        return True, "Sent"
    except Exception as e:
        return False, f"Email error: {e}"

def post_webhook(url, text):
    try:
        payload={"text":text}
        if "discord.com/api/webhooks" in url: payload={"content":text}
        r=requests.post(url, json=payload, timeout=10)
        return (200<=r.status_code<300), r.text
    except Exception as e:
        return False, str(e)

def pushover_send(token, user, title, message):
    try:
        r=requests.post("https://api.pushover.net/1/messages.json",
                        data={"token":token,"user":user,"title":title,"message":message}, timeout=10)
        return (200<=r.status_code<300), r.text
    except Exception as e:
        return False, str(e)

def fanout_alert(lines, email_to="", webhook_url="", po_token="", po_user=""):
    errs=[]
    sub="[Coinbase Movers] Spike notification"
    body="\n".join(lines)
    if email_to:
        ok,info=send_email_alert(sub, body, email_to); 
        if not ok: errs.append(info)
    if webhook_url:
        ok,info=post_webhook(webhook_url, f"**{sub}**\n{body}")
        if not ok: errs.append(f"Webhook: {info}")
    if po_token and po_user:
        ok,info=pushover_send(po_token, po_user, sub, body)
        if not ok: errs.append(f"Pushover: {info}")
    return errs

# ---------------- Browser chime ---------------------------
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
    st.markdown("<script>window.localStorage.setItem('mustBeep','1');</script>", unsafe_allow_html=True)

# ---------------- UI -------------------------------------
st.set_page_config(page_title="Coinbase Movers — Top‑10 Spikes", layout="wide")
st.title("Coinbase Movers — Top‑10 Spikes (ALL‑gates)")

audible_bridge()

with st.sidebar:
    st.subheader("Data")
    mode = st.radio("Source", ["REST only","WebSocket + REST (hybrid)"], index=1 if WS_AVAILABLE else 0)
    if mode.startswith("WebSocket") and not WS_AVAILABLE:
        st.warning("`websocket-client` not installed. Falling back to REST.")
        mode="REST only"

    st.subheader("Auto refresh")
    auto_refresh = st.checkbox("Enable", value=True)
    refresh_secs = st.slider("Interval (sec)", 1, 30, 3, 1)

    st.subheader("Quote & Base")
    quote = st.selectbox("Quote currency", ["USD","USDC"], index=0)
    if st.button("Discover products", type="primary"):
        try:
            pairs, raw = list_products(quote)
            st.session_state["products_all"]=pairs
            st.session_state["bases_all"]=sorted({p.split("-")[0] for p in pairs})
            st.session_state["product_stats"]={pid:fetch_stats(pid) for pid in pairs}
            st.success(f"Discovered {len(pairs)} {quote} pairs.")
        except Exception as e:
            st.error(f"Discovery failed: {e}")

    bases_all = ["All Bases"] + st.session_state.get("bases_all", [])
    base_choice = st.selectbox("Base currency", bases_all, index=0)

    st.subheader("Timeframe")
    tf_choice = st.selectbox("Rank TF", ["15s","30s","1m","3m","5m","15m","30m","1h","4h","6h","12h","1d"], index=2)

    st.subheader("Spike Gates (ALL must pass)")
    apply_gates = st.checkbox("Apply gates (Top‑10 & green tint use ALL enabled)", value=True)
    # Enable/disable individual gates
    c1,c2 = st.columns(2)
    with c1:
        use_price = st.checkbox("Price Δ%", True)
        use_vol   = st.checkbox("Volume ×", True)
        use_rsi   = st.checkbox("RSI velocity", True)
    with c2:
        use_macd  = st.checkbox("MACD hist z‑score", True)
        use_mom   = st.checkbox("Momentum ROC%", True)

    st.caption("Per‑TF thresholds (leave blank to ignore TF).")
    # Reasonable defaults:
    def_map = lambda **kw: kw
    def_price = def_map(**{"15s":0.35,"1m":0.8,"5m":2.5,"15m":4.0,"1h":6.0,"4h":10.0,"6h":8.0,"12h":12.0,"1d":15.0})
    def_volx  = def_map(**{"1m":3.0,"5m":2.5,"15m":2.0,"1h":1.8,"4h":1.8,"6h":1.8,"12h":1.6,"1d":1.5})
    def_rsiv  = def_map(**{"1m":8.0,"5m":10.0,"15m":12.0,"1h":12.0,"4h":14.0,"6h":14.0,"12h":16.0,"1d":18.0})
    def_macdz = def_map(**{"1m":2.0,"5m":2.0,"15m":2.2,"1h":2.2,"4h":2.2,"6h":2.2,"12h":2.4,"1d":2.5})
    def_rocp  = def_map(**{"1m":0.8,"5m":2.0,"15m":3.5,"1h":5.0,"4h":6.5,"6h":6.0,"12h":7.5,"1d":9.0})

    price_thresh = {}
    vol_mult = {}
    rsi_vel = {}
    macdh_z = {}
    roc_pct = {}

    cols = st.columns(5)
    all_tfs = ["15s","30s","1m","3m","5m","15m","30m","1h","4h","6h","12h","1d"]
    for tf in all_tfs:
        with cols[all_tfs.index(tf)%5]:
            p = st.text_input(f"Δ% {tf}", value=str(def_price.get(tf,"")), key=f"pt_{tf}")
            v = st.text_input(f"Vol× {tf}", value=str(def_volx.get(tf,"")), key=f"vx_{tf}")
            rv= st.text_input(f"RSIΔ {tf}", value=str(def_rsiv.get(tf,"")), key=f"rv_{tf}")
            mz= st.text_input(f"MACDz {tf}", value=str(def_macdz.get(tf,"")), key=f"mz_{tf}")
            rp= st.text_input(f"ROC% {tf}", value=str(def_rocp.get(tf,"")), key=f"rp_{tf}")
        try: price_thresh[tf] = float(p) if p.strip()!="" else 9e9
        except: price_thresh[tf] = 9e9
        try: vol_mult[tf] = float(v) if v.strip()!="" else 9e9
        except: vol_mult[tf] = 9e9
        try: rsi_vel[tf] = float(rv) if rv.strip()!="" else 9e9
        except: rsi_vel[tf] = 9e9
        try: macdh_z[tf] = float(mz) if mz.strip()!="" else 9e9
        except: macdh_z[tf] = 9e9
        try: roc_pct[tf] = float(rp) if rp.strip()!="" else 9e9
        except: roc_pct[tf] = 9e9

    st.subheader("Indicators")
    rsi_len = st.number_input("RSI length", 5, 50, 14, 1)
    macd_fast = st.number_input("MACD fast", 3, 50, 12, 1)
    macd_slow = st.number_input("MACD slow", 5, 100, 26, 1)
    macd_sig  = st.number_input("MACD signal", 3, 50, 9, 1)

    st.subheader("Rows")
    top_n = st.slider("Show top N", 5, 300, 80, 5)

    st.subheader("US Timezone")
    tz_choice = st.selectbox("Display timezone", [
        "America/New_York","America/Chicago","America/Denver","America/Los_Angeles"
    ], index=0)

    st.subheader("Alerts")
    email_to = st.text_input("Email (optional)", st.secrets.get("smtp",{}).get("alert_email",""))
    webhook_url = st.text_input("Webhook (optional)", st.secrets.get("webhook_url",""))
    pushover_token = st.text_input("Pushover token (optional)", st.secrets.get("pushover_token",""))
    pushover_user  = st.text_input("Pushover user (optional)", st.secrets.get("pushover_user",""))
    if st.button("Send TEST alert"):
        st.session_state["test_requested"] = True

# Universe
pairs_all = [p for p in st.session_state.get("products_all", []) if p.endswith(f"-{quote}")]
if base_choice != "All Bases":
    pairs_all = [p for p in pairs_all if p.split("-")[0] == base_choice]
if not pairs_all:
    st.info("No pairs match filters. Click **Discover products**.")
    st.stop()

# WS start/pump
if mode.startswith("WebSocket") and WS_AVAILABLE:
    if not st.session_state["ws_alive"]:
        pick=pairs_all[:min(250,len(pairs_all))]
        t=threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start(); time.sleep(0.2)
    ws_ingest_pump()

# Config
cfg = {
    "apply_gates": bool(apply_gates),
    "use_price": bool(use_price),
    "use_vol": bool(use_vol),
    "use_rsi": bool(use_rsi),
    "use_macd": bool(use_macd),
    "use_mom": bool(use_mom),
    "price_thresh": price_thresh,
    "vol_mult": vol_mult,
    "rsi_vel": rsi_vel,
    "macdh_z": macdh_z,
    "roc_pct": roc_pct,
    "rsi_len": int(rsi_len),
    "macd": [int(macd_fast), int(macd_slow), int(macd_sig)],
}

# Build
df = build_table(pairs_all, tf_choice, cfg)
if df.empty:
    st.info("Not enough data for chosen timeframe.")
    st.stop()

# Top 10 (all enabled gates must pass)
spike_df = df[df["all_ok"]].sort_values("Change%", ascending=False, na_position="last").head(10)

st.subheader("Top 10 Mover (ALL enabled gates true)")
if spike_df.empty:
    st.write("—")
else:
    st.dataframe(
        spike_df[["Pair","Price","Change%","TF"]].style.format({"Price":"{:.6f}","Change%":"{:+.2f}%"}),
        use_container_width=True
    )

# Main table (green only where all_ok==True)
df_sorted = df.sort_values("Change%", ascending=False, na_position="last").head(top_n)
def style_df(d):
    d2 = d[["Pair","Price","Change%","TF"]].copy()
    styles = pd.DataFrame("", index=d2.index, columns=d2.columns)
    for idx, ok in d["all_ok"].items():
        if ok:
            styles.loc[idx,:] = "background-color: rgba(16,185,129,0.18)"
    return d2.style.format({"Price":"{:.6f}","Change%":"{:+.2f}%"}).apply(lambda _: styles, axis=None)
st.subheader("All pairs ranked")
st.dataframe(style_df(df_sorted), use_container_width=True)

# Alerts: new all_ok in Top-10
new_lines=[]
if not spike_df.empty:
    for _, r in spike_df.iterrows():
        key=f"{r['Pair']}|{tf_choice}|{round(float(r['Change%']),2)}"
        if key not in st.session_state["last_alert_hashes"]:
            new_lines.append(f"{r['Pair']}: {float(r['Change%']):+.2f}% on {tf_choice}")
            st.session_state["last_alert_hashes"].add(key)

# Test alert: beep + fanout (even if no destinations set)
if st.session_state.pop("test_requested", False):
    trigger_beep()
    errs = fanout_alert(["TEST: Coinbase Movers alert ✅"], email_to, webhook_url, pushover_token, pushover_user)
    if errs: st.warning("Test alert issues: " + "; ".join(errs))
    else: st.success("Test alert sent (and chime played).")

if new_lines and (email_to or webhook_url or (pushover_token and pushover_user)):
    trigger_beep()
    errs = fanout_alert(new_lines, email_to, webhook_url, pushover_token, pushover_user)
    if errs: st.warning("; ".join(errs))

# Footer with timezone
try:
    import zoneinfo; tz=zoneinfo.ZoneInfo(tz_choice)
except Exception:
    tz=None
now_local = dt.datetime.now(tz) if tz else dt.datetime.now()
st.caption(f"Updated: {now_local.strftime('%Y-%m-%d %H:%M:%S %Z')} • Pairs: {len(pairs_all)} • TF: {tf_choice} • WS alive: {bool(st.session_state.get('ws_alive'))}")

# Auto-refresh
if auto_refresh:
    time.sleep(max(1, int(refresh_secs)))
    st.rerun()  # FIX: modern rerun
