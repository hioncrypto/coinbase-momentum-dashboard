# app.py — Coinbase Movers (minimal ranking)
# One file — Streamlit UI that:
# - Discovers all Coinbase pairs for a chosen quote (USD/USDC)
# - Lets you filter by ANY base currency from a dropdown (or All Bases)
# - Lets you choose timeframe (incl. 4h, 6h, 12h, 1d)
# - Ranks by % change on the selected timeframe
# - Displays ONLY: Pair | Price | % Change
# - US timezone picker for the "Updated" footer
# - Optional WebSocket+REST hybrid for faster updates, plus auto-refresh slider
#
# Requirements (requirements.txt):
# streamlit>=1.33
# pandas>=2.2
# numpy>=1.26
# requests>=2.32
# websocket-client>=1.8   # optional; only if you enable WebSocket mode

import os, json, time, threading, queue, datetime as dt, base64
import pandas as pd
import numpy as np
import requests
import streamlit as st

# ------------- Optional WebSocket client -------------
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

CB_REST = "https://api.exchange.coinbase.com"
CB_WS   = "wss://ws-feed.exchange.coinbase.com"

# -------------------- Session state -------------------
def init_state():
    ss = st.session_state
    ss.setdefault("products_all", [])      # full discovered list e.g., ["BTC-USD", ...]
    ss.setdefault("bases_all", [])         # list of base codes e.g., ["BTC","ETH",...]
    ss.setdefault("product_stats", {})     # pid -> /stats cache
    ss.setdefault("bars", {})              # bars[pid][tf] -> list of dicts
    ss.setdefault("last_tick", {})         # pid -> {price,size,time,bid,ask}
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
init_state()

# -------------------- Timeframes ----------------------
TFS = {
    "15s": 15, "30s": 30, "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400,  # synth from 1h
    "6h": 21600,              # REST granularity supported
    "12h": 43200,             # synth from 1h
    "1d": 86400               # REST granularity supported
}
REST_GRANS = {60,300,900,3600,21600,86400}

# -------------------- Utils / indicators --------------
def pct(a, b):
    if b is None or a is None or b == 0: return np.nan
    return (a/b - 1.0)*100.0

def ema(series, span): return series.ewm(span=span, adjust=False).mean()
def rsi(close, length=14):
    delta = close.diff()
    up = np.where(delta>0, delta, 0.0); down = np.where(delta<0, -delta, 0.0)
    roll_up = pd.Series(up).ewm(alpha=1/length, adjust=False).mean()
    roll_dn = pd.Series(down).ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / (roll_dn + 1e-9)
    return 100 - (100/(1+rs))

def bucket_end(ts, seconds): return int(ts - (ts % seconds) + seconds)

# -------------------- REST helpers --------------------
def list_products(quote_currency="USD"):
    r = requests.get(f"{CB_REST}/products", timeout=20)
    r.raise_for_status()
    data = r.json()
    pairs = [
        p["id"] for p in data
        if p.get("quote_currency") == quote_currency
        and p.get("status") in {"online", "online_trading"}
        and not p.get("trading_disabled")
    ]
    return sorted(pairs), data

def fetch_stats(pid):
    try:
        r = requests.get(f"{CB_REST}/products/{pid}/stats", timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}

def fetch_candles(pair, granularity_sec):
    if granularity_sec not in REST_GRANS:
        return None
    r = requests.get(f"{CB_REST}/products/{pair}/candles?granularity={granularity_sec}", timeout=15)
    if r.status_code != 200: return None
    arr = r.json()
    if not arr: return None
    df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
    df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    return df.rename(columns={"open":"o","high":"h","low":"l","close":"c","volume":"v"})

# -------------------- WebSocket ingest ----------------
def on_tick(pid, price, size, t_unix, bid=None, ask=None):
    ss = st.session_state
    ss["last_tick"][pid] = {"price":price, "size":size, "time":t_unix, "bid":bid, "ask":ask}
    # maintain bars for short TFs + 1h (source for 4h/12h synth)
    base_tfs = ["15s","30s","1m","3m","5m","15m","30m","1h"]
    ss["bars"].setdefault(pid, {})
    for tf in base_tfs:
        secs = TFS[tf]; bars = ss["bars"][pid].setdefault(tf, [])
        endt = bucket_end(t_unix, secs)
        if bars and bars[-1]["t"] == endt:
            b = bars[-1]; b["h"]=max(b["h"],price); b["l"]=min(b["l"],price); b["c"]=price; b["v"] += size
        else:
            bars.append({"t":endt,"o":price,"h":price,"l":price,"c":price,"v":size})
            if len(bars) > 600: del bars[: len(bars)-600]

def ws_worker(pairs, endpoint=CB_WS):
    ss = st.session_state
    try:
        ws = websocket.WebSocket(); ws.connect(endpoint, timeout=10)
        chunk=80
        for i in range(0, len(pairs), chunk):
            sub={"type":"subscribe","channels":[{"name":"ticker","product_ids":pairs[i:i+chunk]}]}
            ws.send(json.dumps(sub)); time.sleep(0.2)
        ss["ws_alive"]=True
        while ss.get("ws_alive", False):
            try:
                msg = ws.recv()
                if not msg: continue
                ss["ws_q"].put_nowait(msg)
            except Exception:
                break
    except Exception as e:
        ss["ws_q"].put_nowait(json.dumps({"type":"error","message":str(e)}))
    finally:
        ss["ws_alive"]=False

def ws_ingest_pump():
    ss = st.session_state; did=0
    while not ss["ws_q"].empty() and did<500:
        raw = ss["ws_q"].get_nowait()
        try: d = json.loads(raw)
        except Exception: did += 1; continue
        if d.get("type")!="ticker": did+=1; continue
        pid = d.get("product_id")
        px  = float(d.get("price") or 0.0) if d.get("price") else None
        sz  = float(d.get("last_size") or 0.0) if d.get("last_size") else 0.0
        bid = float(d.get("best_bid")) if d.get("best_bid") else None
        ask = float(d.get("best_ask")) if d.get("best_ask") else None
        t_iso= d.get("time")
        if not (pid and px and t_iso): did+=1; continue
        t_unix = int(dt.datetime.fromisoformat(t_iso.replace("Z","+00:00")).timestamp())
        on_tick(pid, px, sz, t_unix, bid, ask)
        did += 1

# -------------------- Bars access --------------------
def get_bars_df(pid, tf):
    # prefer WS-built bars if available
    ss = st.session_state
    df = pd.DataFrame(ss["bars"].get(pid, {}).get(tf, []))
    if not df.empty:
        df["ts"] = pd.to_datetime(df["t"], unit="s", utc=True)
        return df.sort_values("ts")[["ts","o","h","l","c","v"]].tail(400).reset_index(drop=True)
    # REST fallback
    tf_to_rest = {"1m":60,"5m":300,"15m":900,"1h":3600,"6h":21600,"1d":86400}
    if tf in tf_to_rest:
        df = fetch_candles(pid, tf_to_rest[tf])
        if df is not None:
            return df[["ts","o","h","l","c","v"]].tail(400).reset_index(drop=True)
    # synth 4h/12h from 1h
    if tf in ("4h","12h"):
        h1 = get_bars_df(pid, "1h")
        if h1 is None or h1.empty: return pd.DataFrame()
        h1 = h1.set_index(h1["ts"])
        rule = "4H" if tf=="4h" else "12H"
        o = h1["o"].resample(rule, label="right", closed="right").first()
        h = h1["h"].resample(rule, label="right", closed="right").max()
        l = h1["l"].resample(rule, label="right", closed="right").min()
        c = h1["c"].resample(rule, label="right", closed="right").last()
        v = h1["v"].resample(rule, label="right", closed="right").sum()
        out = pd.DataFrame({"ts":o.index,"o":o,"h":h,"l":l,"c":c,"v":v}).dropna().reset_index(drop=True)
        return out.tail(200)
    return pd.DataFrame()

# -------------------- Compute view -------------------
def compute_row(pid, tf):
    """
    Returns dict with Pair, Price, and % Change (on tf).
    """
    last_tick = st.session_state["last_tick"].get(pid, {})
    last_price = float(last_tick.get("price")) if last_tick else np.nan

    df = get_bars_df(pid, tf)
    if df is None or df.empty:
        return {"Pair": pid, "Price": last_price, "Change%": np.nan}

    close = df["c"].astype(float)
    # short TF uses 1-back; longer uses 2/3-back
    n_back = 1 if tf in ("15s","30s","1m") else 2 if tf in ("3m","5m") else 3
    ref = close.iloc[-1-n_back] if len(close) > n_back else close.iloc[0]
    change = pct(close.iloc[-1], ref)

    price = float(close.iloc[-1]) if np.isfinite(close.iloc[-1]) else last_price
    return {"Pair": pid, "Price": price, "Change%": float(change) if change is not None else np.nan}

def build_table(pairs, tf):
    rows=[compute_row(pid, tf) for pid in pairs]
    df = pd.DataFrame(rows)
    return df

# -------------------- Streamlit UI -------------------
st.set_page_config(page_title="Coinbase Movers — Minimal", layout="wide")
st.title("Coinbase Movers — Minimal Ranking")

with st.sidebar:
    st.subheader("Data")
    mode = st.radio("Source", ["REST only", "WebSocket + REST (hybrid)"], index=1 if WS_AVAILABLE else 0)
    if mode.startswith("WebSocket") and not WS_AVAILABLE:
        st.warning("`websocket-client` not installed. Falling back to REST.")
        mode = "REST only"

    st.subheader("Auto refresh")
    auto_refresh = st.checkbox("Enable", value=True)
    refresh_secs = st.slider("Interval (sec)", 1, 30, 3, 1)

    st.subheader("Quote & Base")
    quote = st.selectbox("Quote currency", ["USD","USDC"], index=0)
    discover = st.button("Discover products", type="primary")
    if discover or not st.session_state.get("products_all"):
        try:
            pairs, raw = list_products(quote)
            st.session_state["products_all"] = pairs
            st.session_state["bases_all"] = sorted({p.split("-")[0] for p in pairs})
            # warm stats (for volume sort if needed later)
            st.session_state["product_stats"] = {pid: fetch_stats(pid) for pid in pairs}
            st.success(f"Discovered {len(pairs)} {quote} pairs.")
        except Exception as e:
            st.error(f"Discovery failed: {e}")

    bases_all = ["All Bases"] + st.session_state.get("bases_all", [])
    base_choice = st.selectbox("Base currency", bases_all, index=0)

    st.subheader("Timeframe")
    tf_choice = st.selectbox(
        "Rank by % change on timeframe",
        ["15s","30s","1m","3m","5m","15m","30m","1h","4h","6h","12h","1d"],
        index=2  # default 1m
    )

    st.subheader("Rows")
    top_n = st.slider("Show top N", 5, 200, 50, 5)

    st.subheader("Timezone (USA)")
    tz_choice = st.selectbox("Display timezone", [
        "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles"
    ], index=0)

# Derive active universe
pairs_all = [p for p in st.session_state.get("products_all", []) if p.endswith(f"-{quote}")]
if base_choice != "All Bases":
    pairs_all = [p for p in pairs_all if p.split("-")[0] == base_choice]

if not pairs_all:
    st.info("No pairs match the current filters. Click **Discover products** or change filters.")
    st.stop()

# Start WS if requested
diag = {"WS": WS_AVAILABLE, "thread": False, "url": CB_WS}
if mode.startswith("WebSocket") and WS_AVAILABLE:
    if not st.session_state["ws_alive"]:
        # subscribe to a capped list (WS feed can handle a lot, but be reasonable)
        pick = pairs_all[:min(250, len(pairs_all))]
        t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
        t.start()
        st.session_state["ws_thread"] = t
        time.sleep(0.2)
    diag["thread"] = bool(st.session_state["ws_alive"])
    ws_ingest_pump()

# Build and sort table
df = build_table(pairs_all, tf_choice)
if df.empty:
    st.info("Not enough data yet — give it a moment or switch timeframe.")
    st.stop()

df = df.sort_values("Change%", ascending=False, na_position="last").head(top_n)

# Minimal ranking view: Pair | Price | % Change
# Apply subtle green tint to positive movers (cell-level style only)
def style_df(d):
    def colorize(val):
        try:
            return "background-color: rgba(16,185,129,0.12)" if float(val) > 0 else ""
        except Exception:
            return ""
    styled = d.style.format({"Price":"{:.6f}", "Change%":"{:+.2f}%"}).applymap(colorize, subset=["Change%"])
    return styled

st.subheader("Top Movers")
st.dataframe(style_df(df), use_container_width=True)

# Footer with timezone-adjusted update time
try:
    import zoneinfo
    tz = zoneinfo.ZoneInfo(tz_choice)
except Exception:
    tz = None
now_local = dt.datetime.now(tz) if tz else dt.datetime.now()
st.caption(f"Updated: {now_local.strftime('%Y-%m-%d %H:%M:%S %Z')}  •  Pairs scanned: {len(pairs_all)}  •  TF: {tf_choice}")

# Auto-refresh loop
if auto_refresh:
    time.sleep(max(1, int(refresh_secs)))
    st.experimental_rerun()

