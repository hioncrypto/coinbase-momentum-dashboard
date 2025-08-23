# app.py — Crypto Tracker by hioncrypto (collapse-all + blue sidebar + robust discovery)
# - Collapse-all: reliable one-shot collapse on next render
# - Sidebar CSS: blue buttons + expander headers
# - Discovery fixed: discovery ∪ watchlist (when watchlist-only is OFF) with Coinbase fallback
# - Keeps K-of-N gates (green), Yellow ≥ Y (partial), positive-only % change
# - Internal gates: Volume spike, RSI, MACD hist, ATR, Trend breakout, ROC
# - Top-10 = green only; All pairs = green/yellow/neutral
# - Email/Webhook alerts (session opt-in)
# - Presets best-effort saved in /tmp (session-safe if disk read-only)
# - Coinbase + Binance (others fallback)

import os, json, time, ssl, smtplib, threading, queue, datetime as dt
from pathlib import Path
from typing import List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
import requests
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ---------------- Optional WS
WS_AVAILABLE = True
try:
    import websocket
except Exception:
    WS_AVAILABLE = False

# ---------------- Session init
def _init_state():
    ss = st.session_state
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("last_refresh", time.time())
    ss.setdefault("force_collapse", False)   # <— collapse-all latch
    ss.setdefault("my_pairs", set())
    ss.setdefault("gate_presets", {})
    ss.setdefault("active_preset", "")
_init_state()

TITLE = "Crypto Tracker by hioncrypto"
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
TF_TO_SEC = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}
QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"
PRESET_PATH = Path("/tmp/crypto_tracker_presets.json")

# ---------------- Utils / Indicators
def ema(s, span): return s.ewm(span=span, adjust=False).mean()
def rsi(close, length=14):
    d = close.diff()
    up = pd.Series(np.where(d>0, d, 0.0), index=close.index)
    dn = pd.Series(np.where(d<0, -d, 0.0), index=close.index)
    rs = up.ewm(alpha=1/length, adjust=False).mean()/(dn.ewm(alpha=1/length, adjust=False).mean()+1e-12)
    return 100 - (100/(1+rs))
def macd_hist(close, fast=12, slow=26, signal=9):
    line = ema(close, fast)-ema(close, slow)
    return line-ema(line, signal)
def atr(df, length=14):
    h,l,c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()
def roc(close, n=10): return (close/close.shift(n)-1.0)*100.0
def volume_spike(df, window=20):
    if len(df)<window+1: return np.nan
    return float(df["volume"].iloc[-1]/(df["volume"].rolling(window).mean().iloc[-1]+1e-12))
def find_pivots(close, span=3):
    v=close.values; n=len(v); hi=[]; lo=[]
    for i in range(span, n-span):
        if v[i]>v[i-span:i].max() and v[i]>v[i+1:i+1+span].max(): hi.append(i)
        if v[i]<v[i-span:i].min() and v[i]<v[i+1:i+1+span].min(): lo.append(i)
    return pd.Index(hi), pd.Index(lo)
def trend_breakout_up(df, span=3, within_bars=48):
    if df is None or len(df)<span*2+5: return False
    highs,_ = find_pivots(df["close"], span)
    if len(highs)==0: return False
    hi=int(highs[-1]); level=float(df["close"].iloc[hi])
    cross=None
    for j in range(hi+1, len(df)):
        if float(df["close"].iloc[j])>level: cross=j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# ---------------- Exchange discovery
def coinbase_list_products(quote):
    try:
        r=requests.get(f"{CB_BASE}/products", timeout=25); r.raise_for_status()
        data=r.json()
        return sorted(f"{p['base_currency']}-{p['quote_currency']}" for p in data if p.get("quote_currency")==quote)
    except Exception: return []
def binance_list_products(quote):
    try:
        r=requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=30); r.raise_for_status()
        out=[]
        for s in r.json().get("symbols",[]):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote: out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception: return []
def list_products(exchange, quote):
    if exchange=="Coinbase": return coinbase_list_products(quote)
    if exchange=="Binance":  return binance_list_products(quote)
    return coinbase_list_products(quote)  # fallback

# ---------------- OHLC
def fetch_candles(exchange, pair_dash, gran_sec, start=None, end=None):
    try:
        if exchange=="Coinbase":
            url=f"{CB_BASE}/products/{pair_dash}/candles"
            params={"granularity":gran_sec}
            if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
            if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
            r=requests.get(url, params=params, timeout=25)
            if r.status_code!=200: return None
            arr=r.json()
            if not arr: return None
            df=pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"]=pd.to_datetime(df["ts"], unit="s", utc=True)
            return df.sort_values("ts").reset_index(drop=True)
        elif exchange=="Binance":
            base,quote=pair_dash.split("-"); symbol=f"{base}{quote}"
            imap={900:"15m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
            interval=imap.get(gran_sec); 
            if not interval: return None
            params={"symbol":symbol,"interval":interval,"limit":1000}
            if start: params["startTime"]=int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            if end:   params["endTime"]=int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            r=requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=25)
            if r.status_code!=200: return None
            rows=[{"ts":pd.to_datetime(a[0],unit="ms",utc=True),"open":float(a[1]),"high":float(a[2]),
                   "low":float(a[3]),"close":float(a[4]),"volume":float(a[5])} for a in r.json()]
            return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    except Exception: return None
    return None
def resample_ohlcv(df, target_sec):
    if df is None or df.empty: return None
    d=df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    out=d.resample(f"{target_sec}s", label="right", closed="right").agg(agg).dropna()
    return out.reset_index()
def df_for_tf(exchange, pair, tf):
    sec=TF_TO_SEC[tf]
    if exchange=="Coinbase":
        native = sec in {900,3600,21600,86400}
        base=fetch_candles(exchange, pair, sec if native else 3600)
        return base if native else resample_ohlcv(base, sec)
    elif exchange=="Binance":
        return fetch_candles(exchange, pair, sec)
    return None

@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange, pair, basis, amount):
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":
        amount=max(1,min(amount,72)); gran=3600; start=end-dt.timedelta(hours=amount)
    elif basis=="Daily":
        amount=max(1,min(amount,365)); gran=86400; start=end-dt.timedelta(days=amount)
    else:
        amount=max(1,min(amount,52)); gran=86400; start=end-dt.timedelta(weeks=amount)
    out=[]; step=300; cursor=end
    while True:
        win=dt.timedelta(seconds=step*gran)
        s=max(start, cursor-win)
        if (cursor-s).total_seconds()<gran: break
        df=fetch_candles(exchange, pair, gran, start=s, end=cursor)
        if df is None or df.empty: break
        out.append(df); cursor=df["ts"].iloc[0]
        if cursor<=start: break
    if not out: return None
    hist=pd.concat(out, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if basis=="Weekly": hist=resample_ohlcv(hist, 7*86400)
    return hist
def ath_atl_info(hist):
    last=float(hist["close"].iloc[-1])
    ia=int(hist["high"].idxmax()); ib=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[ia]); d_ath=pd.to_datetime(hist["ts"].iloc[ia]).date().isoformat()
    atl=float(hist["low"].iloc[ib]);  d_atl=pd.to_datetime(hist["ts"].iloc[ib]).date().isoformat()
    return {"From ATH %":(last/ath-1)*100 if ath>0 else np.nan,"ATH date":d_ath,
            "From ATL %":(last/atl-1)*100 if atl>0 else np.nan,"ATL date":d_atl}

# ---------------- Alerts / presets
def send_email_alert(subject, body, recipient):
    try: cfg=st.secrets["smtp"]
    except Exception: return False, "SMTP not configured in st.secrets"
    try:
        msg=MIMEMultipart(); msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body,"plain"))
        ctx=ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port",465), context=ctx) as s:
            s.login(cfg["user"], cfg["password"]); s.sendmail(cfg["sender"], recipient, msg.as_string())
        return True,"Email sent"
    except Exception as e: return False, f"Email error: {e}"
def post_webhook(url, payload):
    try:
        r=requests.post(url, json=payload, timeout=10)
        return (200<=r.status_code<300), r.text
    except Exception as e: return False, str(e)
def load_presets_from_disk():
    try:
        if PRESET_PATH.exists(): return json.loads(PRESET_PATH.read_text())
    except Exception: pass
    return {}
def save_presets_to_disk(p):
    try: PRESET_PATH.write_text(json.dumps(p, indent=2))
    except Exception: st.sidebar.info("Could not save presets to disk; presets will persist only this session.")

# ---------------- Page + CSS (blue sidebar)
st.set_page_config(page_title=TITLE, layout="wide")
st.markdown("""
<style>
/* Blue sidebar buttons */
section[data-testid="stSidebar"] .stButton>button {background:#1e88e5;color:white;border:0; }
section[data-testid="stSidebar"] .stButton>button:hover {filter:brightness(0.95);}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary {background:#1e88e522;border-radius:8px;}
</style>
""", unsafe_allow_html=True)
st.title(TITLE)

# Toolbar row: Collapse-all + “Use My Pairs only”
colA, colB = st.columns([1,3])
with colA:
    if st.button("Collapse all"):
        st.session_state["force_collapse"] = True
# quick “Use My Pairs only” toggle lives in Market section below (to not add more globals)

# -------- Sidebar expanders helper
def expander(title, key):
    opened = not st.session_state.get("force_collapse", False)
    return st.sidebar.expander(title, expanded=opened)

with expander("Reset / Utilities", "exp_reset"):
    if st.button("Reset collapse state (off)"):
        st.session_state["force_collapse"] = False

with expander("Manage My Pairs", "exp_my"):
    current = ", ".join(sorted(st.session_state["my_pairs"])) if st.session_state["my_pairs"] else ""
    txt = st.text_area("Pinned pairs (comma-separated)", current, height=80)
    if st.button("Save My Pairs"):
        st.session_state["my_pairs"] = set(p.strip().upper() for p in txt.split(",") if p.strip())
        st.success("Saved.")

with expander("Market", "exp_market"):
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    effective_exchange = exchange if "coming soon" not in exchange else "Coinbase"
    if "coming soon" in exchange:
        st.info("This exchange is coming soon. Using Coinbase for data.")
    quote = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch_only = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    watchlist = st.text_area("Watchlist (comma-separated)",
                             "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")
    max_pairs = st.slider("Max pairs to evaluate (discovery)", 10, 1000, 430, 10)

with expander("Mode", "exp_mode"):
    mode = st.radio("Data source", ["REST only","WebSocket + REST (hybrid)"], index=0, horizontal=True)
    ws_chunk = st.slider("WS subscribe chunk (Coinbase)", 2, 20, 5, 1)

with expander("Timeframes", "exp_tf"):
    sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=1)
    sort_desc = st.checkbox("Sort descending (largest first)", True)

with expander("Gates", "exp_gates"):
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 80.0, 20.0, 0.5)
    c1,c2,c3 = st.columns(3)
    with c1:
        use_vol_spike = st.toggle("Volume spike×", True)
        vol_mult = st.slider("Spike multiple ×", 1.0, 6.0, 1.10, 0.05)
        use_rsi = st.toggle("RSI", False);  min_rsi = st.slider("Min RSI", 40, 90, 55, 1)
    with c2:
        use_macd = st.toggle("MACD hist", True); min_mhist = st.slider("Min MACD hist", 0.0, 2.0, 0.0, 0.05)
        use_atr = st.toggle("ATR %", False);     min_atr = st.slider("Min ATR %", 0.0, 10.0, 0.5, 0.1)
    with c3:
        use_trend = st.toggle("Trend breakout (up)", True)
        pivot_span = st.slider("Pivot span (bars)", 2, 10, 4, 1)
        trend_within = st.slider("Breakout within (bars)", 5, 96, 48, 1)
        use_roc = st.toggle("ROC %", False)
        roc_len = st.slider("ROC length (bars)", 2, 60, 10, 1)
        min_roc = st.slider("Min ROC %", 0.0, 50.0, 1.0, 0.5)

    st.divider()
    enabled_checks = [True, use_vol_spike, use_rsi, use_macd, use_atr, use_trend, use_roc]
    N = int(sum(enabled_checks))
    K = st.selectbox("Gates needed to turn **green** (K)", list(range(1, max(N,1)+1)), index=min(2,max(N,1))-1)
    Y = st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0, K)), index=max(0, min(1, K-1)))
    st.caption(f"Enabled checks counted: **{N}** • Green needs ≥ **{K}** • Yellow needs ≥ **{Y}** (but < K).")
    st.caption("💡 If nothing shows, lower Min +% change, reduce K, or disable some checks.")

with expander("Indicator lengths", "exp_lens"):
    rsi_len  = st.slider("RSI length", 5, 50, 14, 1)
    macd_fast= st.slider("MACD fast EMA", 3, 50, 12, 1)
    macd_slow= st.slider("MACD slow EMA", 5, 100, 26, 1)
    macd_sig = st.slider("MACD signal", 3, 50, 9, 1)
    atr_len  = st.slider("ATR length", 5, 50, 14, 1)
    vol_window=st.slider("Volume SMA window", 5, 50, 20, 1)

with expander("History depth (for ATH/ATL)", "exp_hist"):
    basis = st.selectbox("Basis", ["Hourly","Daily","Weekly"], index=1)
    amount = (st.slider("Hours (≤72)", 1, 72, 24, 1) if basis=="Hourly"
              else st.slider("Days (≤365)", 1, 365, 90, 1) if basis=="Daily"
              else st.slider("Weeks (≤52)", 1, 52, 12, 1))

with expander("Notifications", "exp_notif"):
    st.caption("Enable per session at the bottom when Top‑10 updates.")

with expander("Auto-refresh", "exp_refresh"):
    refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 30, 1)
    st.caption("Auto-refresh is always on.")

# Collapse latch consumed now
st.session_state["force_collapse"] = False

# ---------------- Discovery (robust)
watch_pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
if use_watch_only:
    pairs = [p for p in watch_pairs if p.endswith(f"-{quote}")]
    disc_count = 0
else:
    discovered = list_products(effective_exchange, quote)
    if not discovered and effective_exchange!="Coinbase":
        # fallback
        discovered = list_products("Coinbase", quote)
        effective_exchange = "Coinbase"
    disc_count = len(discovered)
    # merge discovery + watchlist
    merged = sorted(set(discovered).union(watch_pairs))
    pairs = [p for p in merged if p.endswith(f"-{quote}")]
    pairs = pairs[:max_pairs]

st.caption(f"Discovery report — discovered: {disc_count} • watchlist: {len(watch_pairs)} • after merge/filter: {len(pairs)}")

if not pairs:
    st.info("No pairs to scan. If 'Use watchlist only' is ON, add pairs like BTC-USD. Otherwise lower Max pairs or check quote.")
    st.stop()

# ---------------- Optional WS
if (mode.startswith("WebSocket") and effective_exchange=="Coinbase" and WS_AVAILABLE):
    # subscribe only to the first few to keep it light
    pick = pairs[:min(10, len(pairs))]
    if not st.session_state["ws_alive"]:
        def ws_worker(product_ids, endpoint="wss://ws-feed.exchange.coinbase.com"):
            try:
                ws = websocket.WebSocket()
                ws.connect(endpoint, timeout=10); ws.settimeout(1.0)
                ws.send(json.dumps({"type":"subscribe","channels":[{"name":"ticker","product_ids":product_ids}]}))
                st.session_state["ws_alive"]=True
                while st.session_state["ws_alive"]:
                    try:
                        msg = ws.recv()
                        if not msg: continue
                        d = json.loads(msg)
                        if d.get("type")=="ticker":
                            pid=d.get("product_id"); px=d.get("price")
                            if pid and px: st.session_state["ws_prices"][pid]=float(px)
                    except websocket.WebSocketTimeoutException:
                        continue
                    except Exception:
                        break
            except Exception:
                pass
            finally:
                st.session_state["ws_alive"]=False
                try: ws.close()
                except Exception: pass
        threading.Thread(target=ws_worker, args=(pick,), daemon=True).start()

# ---------------- Build rows
rows=[]
for pid in pairs:
    dft = df_for_tf(effective_exchange, pid, sort_tf)
    if dft is None or len(dft)<30: continue
    dft = dft.tail(400).copy()
    last_price=float(dft["close"].iloc[-1])
    if effective_exchange=="Coinbase" and st.session_state["ws_prices"].get(pid):
        last_price=float(st.session_state["ws_prices"][pid])
    first_price=float(dft["close"].iloc[0])
    pct=(last_price/first_price-1.0)*100.0

    hist=get_hist(effective_exchange, pid, basis, amount)
    if hist is None or len(hist)<10:
        athp, athd, atlp, atld = np.nan, "—", np.nan, "—"
    else:
        metrics=ath_atl_info(hist); athp,athd,atlp,atld = metrics["From ATH %"],metrics["ATH date"],metrics["From ATL %"],metrics["ATL date"]

    # indicators
    rsi_ser=rsi(dft["close"], rsi_len)
    mh_ser=macd_hist(dft["close"], macd_fast, macd_slow, macd_sig)
    atr_pct=atr(dft, atr_len)/(dft["close"]+1e-12)*100.0
    volx=volume_spike(dft, vol_window)
    tr_up=trend_breakout_up(dft, span=pivot_span, within_bars=trend_within)
    roc_ser=roc(dft["close"], roc_len)

    checks=[]
    checks.append( (pct>0) and (pct>=min_pct) )
    if use_vol_spike: checks.append(volx>=vol_mult)
    if use_rsi:       checks.append(rsi_ser.iloc[-1]>=min_rsi)
    if use_macd:      checks.append(mh_ser.iloc[-1]>=min_mhist)
    if use_atr:       checks.append(atr_pct.iloc[-1]>=min_atr)
    if use_trend:     checks.append(bool(tr_up))
    if use_roc:       checks.append(roc_ser.iloc[-1]>=min_roc)

    gates_met=int(sum(bool(x) for x in checks))
    is_green=gates_met>=K
    is_yellow=(not is_green) and (gates_met>=Y) and (pct>0)

    rows.append({
        "Pair":pid, "Price":last_price, f"% Change ({sort_tf})":pct,
        "From ATH %":athp, "ATH date":athd, "From ATL %":atlp, "ATL date":atld,
        "Strong Buy":"YES" if is_green else "—",
        "_green":is_green, "_yellow":is_yellow
    })

df=pd.DataFrame(rows)
if df.empty:
    st.info("No rows to show. Loosen gates or choose a different timeframe.")
    st.stop()

chg_col=f"% Change ({sort_tf})"
df=df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
df.insert(0,"#",df.index+1)

def style_rows_full(x):
    styles=pd.DataFrame("", index=x.index, columns=x.columns)
    if "_green" in x.columns:
        styles.loc[x["_green"].fillna(False),:]="background-color: rgba(0,255,0,0.22); font-weight: 600;"
    if "_yellow" in x.columns:
        idx=x["_yellow"].fillna(False) & ~x.get("_green",pd.Series(False,index=x.index))
        styles.loc[idx,:]="background-color: rgba(255,255,0,0.60); font-weight: 600;"
    return styles
def style_rows_green_only(x):
    return pd.DataFrame("background-color: rgba(0,255,0,0.22); font-weight: 600;", index=x.index, columns=x.columns)

st.markdown(f"**Timeframe:** {sort_tf}  \n*Legend: Δ %Change • V Volume× • S RSI • M MACD • A ATR • T Trend • R ROC*")

# Top-10 (green only)
st.subheader("📌 Top‑10 (meets green rule)")
top10=df[df["_green"]].copy()
if not top10.empty:
    top10=top10.sort_values(chg_col, ascending=False, na_position="last").head(10).reset_index(drop=True)
    show_cols=[c for c in top10.columns if c not in ["_green","_yellow"]]
    st.dataframe(top10[show_cols].style.apply(style_rows_green_only, axis=None), use_container_width=True)
else:
    st.write("—")
    st.caption("💡 If nothing appears, lower Min +% change, reduce K, or disable some checks.")

# All pairs
st.subheader("📑 All pairs")
show_cols=[c for c in df.columns if c not in ["_green","_yellow"]]
st.dataframe(df[show_cols].style.apply(style_rows_full, axis=None), use_container_width=True)

# Alerts
new_msgs=[]
for _, r in top10.iterrows():
    key=f"{r['Pair']}|{sort_tf}|{round(float(r[chg_col]),2)}"
    if key not in st.session_state["alert_seen"]:
        st.session_state["alert_seen"].add(key)
        new_msgs.append(f"{r['Pair']}: {float(r[chg_col]):+.2f}% ({sort_tf})")

with st.sidebar.expander("Send alerts this session", expanded=False):
    arm = st.checkbox("Enable", value=False)
    email_to = st.text_input("Email recipient", key="alerts_email")
    webhook_url = st.text_input("Webhook URL", key="alerts_hook")
if new_msgs and arm:
    subject=f"[{effective_exchange}] Top‑10 Crypto Tracker"
    body="\n".join(new_msgs)
    if email_to:
        ok,info=send_email_alert(subject, body, email_to)
        if not ok: st.sidebar.warning(info)
    if webhook_url:
        ok,info=post_webhook(webhook_url, {"title":subject,"lines":new_msgs})
        if not ok: st.sidebar.warning(f"Webhook error: {info}")

# Presets section
with st.sidebar.expander("Gate presets", expanded=False):
    if not st.session_state["gate_presets"]:
        st.session_state["gate_presets"]={**load_presets_from_disk()}
    snapshot={
        "min_pct":min_pct,
        "use_vol_spike":use_vol_spike,"vol_mult":vol_mult,
        "use_rsi":use_rsi,"min_rsi":min_rsi,"rsi_len":rsi_len,
        "use_macd":use_macd,"min_mhist":min_mhist,
        "use_atr":use_atr,"min_atr":min_atr,"atr_len":atr_len,
        "use_trend":use_trend,"pivot_span":pivot_span,"trend_within":trend_within,
        "use_roc":use_roc,"roc_len":roc_len,"min_roc":min_roc,
        "K":K,"Y":Y,
    }
    name=st.text_input("New preset name")
    c1,c2=st.columns(2)
    with c1:
        if st.button("Save preset"):
            if name.strip():
                st.session_state["gate_presets"][name.strip()]=snapshot
                save_presets_to_disk(st.session_state["gate_presets"])
                st.success("Saved.")
            else: st.warning("Enter a name.")
    with c2:
        if st.button("Delete preset"):
            key=st.session_state.get("active_preset")
            if key and key in st.session_state["gate_presets"]:
                del st.session_state["gate_presets"][key]; save_presets_to_disk(st.session_state["gate_presets"]); st.success("Deleted.")
    if st.session_state["gate_presets"]:
        choices=["(choose)"]+sorted(st.session_state["gate_presets"].keys())
        st.selectbox("Apply preset (reload app after choosing)", choices, index=0, key="active_preset")

# Footer + auto-refresh
mode_label = 'WS+REST' if (mode.startswith('WebSocket') and effective_exchange=='Coinbase' and WS_AVAILABLE) else 'REST only'
st.caption(f"Pairs: {len(df)} • Exchange: {effective_exchange} • Quote: {quote} • Sort TF: {sort_tf} • Mode: {mode_label}")
remaining = refresh_sec - (time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"]=time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {refresh_sec}s (next in {int(remaining)}s)")
