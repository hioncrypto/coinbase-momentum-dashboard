# app.py — Crypto Tracker by hioncrypto
# One-file build: multi-exchange discovery, lenient starter gates,
# green/yellow rules (K/Y), gates chips, Top-10, alerts, blue sidebar,
# Trend Break window (Hourly/Daily/Weekly), positive-only % change.

import json, time, ssl, smtplib, threading, queue, datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, List, Tuple

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ---------------- Session state (init safe) ----------------
def _ss_init():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("collapse_req", False)
    ss.setdefault("my_pairs", set())       # user-pinned pairs
    ss.setdefault("presets", {})           # user presets (persist via JSON file later if desired)
_ss_init()

# ---------------- UI constants ----------------
APP_TITLE = "Crypto Tracker by hioncrypto"

TF_LIST = ["15m","1h","4h","6h","12h","1d"]
TF_TO_SEC = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}

EXCHANGES_FULL = [
    "Coinbase",
    "Binance",
    "Kraken (coming soon)",
    "KuCoin (coming soon)",
    "Bybit (coming soon)",
]

# Quote defaults per exchange (used when user switches)
DEFAULT_QUOTES = {
    "Coinbase": "USD",
    "Binance": "USDT",
}

ALL_QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]

# ---------------- CSS (blue sidebar, compact toggles, full-row colors) ----------------
st.set_page_config(page_title=APP_TITLE, layout="wide")
st.markdown("""
<style>
/* Sidebar deep-blue look */
section[data-testid="stSidebar"] .stButton>button,
section[data-testid="stSidebar"] .stDownloadButton>button,
section[data-testid="stSidebar"] .stBaseButton {
  background: #0a4cff !important; color: white !important; border-radius: 10px !important;
  border: 1px solid #0736b8 !important;
}
section[data-testid="stSidebar"] .stButton>button:hover { filter: brightness(1.1); }

/* Section headers */
h1, h2, h3 { letter-spacing: .2px; }

/* Dataframe row styles */
.row-green { background: rgba(0, 255, 0, 0.22) !important; font-weight: 600; }
.row-yellow { background: rgba(255, 255, 0, 0.60) !important; font-weight: 600; }

/* Tiny chips in table */
.gchip {
  display:inline-block; padding: 2px 6px; margin: 0 2px; border-radius: 8px; font-size: .8rem;
  color: #111; background: #e7f1ff; border: 1px solid #bcd3ff;
}
.gchip.pass { background:#d6f7d6; border-color:#9fdf9f; }
.gchip.fail { background:#ffd9d9; border-color:#ffb3b3; }

/* Sticky (floating) collapse button block */
#float-controls { position: sticky; top: 8px; z-index: 10; background: transparent; padding-bottom:6px; }
</style>
""", unsafe_allow_html=True)

# ---------------- Indicators ----------------
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0); down = np.where(delta < 0, -delta, 0.0)
    up_s = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    dn_s = pd.Series(down, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = up_s / (dn_s + 1e-12)
    return 100 - (100 / (1 + rs))

def macd_hist(close: pd.Series, fast=12, slow=26, signal=9) -> pd.Series:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    return macd_line - signal_line

def atr(df: pd.DataFrame, length=14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def roc(close: pd.Series, length=10) -> pd.Series:
    return (close / close.shift(length) - 1.0) * 100.0

def volume_spike(df: pd.DataFrame, window=20) -> float:
    if len(df) < window+1: return np.nan
    return float(df["volume"].iloc[-1] / (df["volume"].rolling(window).mean().iloc[-1] + 1e-12))

# Trend breakout (up): last close > last pivot high, within N bars
def _pivots(close: pd.Series, span=3) -> Tuple[pd.Index, pd.Index]:
    v = close.values; n=len(close); highs=[]; lows=[]
    for i in range(span, n-span):
        if v[i] > v[i-span:i].max() and v[i] > v[i+1:i+1+span].max(): highs.append(i)
        if v[i] < v[i-span:i].min() and v[i] < v[i+1:i+1+span].min(): lows.append(i)
    return pd.Index(highs), pd.Index(lows)

def trend_breakout_up(df: pd.DataFrame, span=3, within_bars=96) -> bool:
    if df is None or len(df) < span*2+10: return False
    highs,_ = _pivots(df["close"], span)
    if len(highs)==0: return False
    hi = int(highs[-1]); level = float(df["close"].iloc[hi])
    cross=None
    for j in range(hi+1, len(df)):
        if float(df["close"].iloc[j]) > level:
            cross=j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# ---------------- Exchanges (discovery + candles) ----------------
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

def coinbase_list(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=20); r.raise_for_status()
        return sorted(f"{d['base_currency']}-{d['quote_currency']}" for d in r.json()
                      if d.get("quote_currency")==quote)
    except Exception:
        return []

def binance_list(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25); r.raise_for_status()
        out=[]
        for s in r.json().get("symbols",[]):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote:
                out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange=="Coinbase": return coinbase_list(quote)
    if exchange=="Binance": return binance_list(quote)
    # coming-soon exchanges return empty but keep UI consistent
    return []

def fetch_candles(exchange: str, pair: str, sec: int,
                  start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    try:
        if exchange=="Coinbase":
            url = f"{CB_BASE}/products/{pair}/candles?granularity={sec}"
            params={}
            if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
            if end: params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
            r = requests.get(url, params=params, timeout=25)
            if r.status_code!=200: return None
            arr = r.json()
            if not arr: return None
            # ts, low, high, open, close, volume
            df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"]=pd.to_datetime(df["ts"],unit="s",utc=True)
            return df.sort_values("ts").reset_index(drop=True)

        if exchange=="Binance":
            base, quote = pair.split("-"); symbol=f"{base}{quote}"
            interval_map = {900:"15m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
            interval = interval_map.get(sec)
            if not interval: return None
            params={"symbol":symbol,"interval":interval,"limit":1000}
            if start: params["startTime"]=int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            if end: params["endTime"]=int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            r = requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=25)
            if r.status_code!=200: return None
            rows=[]
            for a in r.json():
                rows.append({"ts":pd.to_datetime(a[0],unit="ms",utc=True),
                             "open":float(a[1]),"high":float(a[2]),
                             "low":float(a[3]),"close":float(a[4]),
                             "volume":float(a[5])})
            return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
    except Exception:
        return None
    return None

def resample(df: pd.DataFrame, target_sec:int)->Optional[pd.DataFrame]:
    if df is None or df.empty: return None
    d=df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    out=d.resample(f"{target_sec}s", label="right", closed="right").agg(agg).dropna()
    return out.reset_index()

def df_for_tf(exchange: str, pair: str, tf: str)->Optional[pd.DataFrame]:
    sec = TF_TO_SEC[tf]
    if exchange=="Coinbase":
        # Native granularities: 1m,5m,15m,1h,6h,1d (but REST allows subset); we’ll call directly for ours
        return fetch_candles(exchange, pair, sec)
    if exchange=="Binance":
        return fetch_candles(exchange, pair, sec)
    return None

# ---------------- ATH/ATL (with window basis) ----------------
@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int)->Optional[pd.DataFrame]:
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":
        amount = max(1, min(amount, 72)); gran=3600; start=end-dt.timedelta(hours=amount)
    elif basis=="Daily":
        amount = max(1, min(amount, 365)); gran=86400; start=end-dt.timedelta(days=amount)
    else:
        amount = max(1, min(amount, 52)); gran=86400; start=end-dt.timedelta(weeks=amount)
    out=[]; cursor_end=end; step=300
    while True:
        win=dt.timedelta(seconds=step*gran)
        cursor_start=max(start, cursor_end-win)
        if (cursor_end-cursor_start).total_seconds()<gran: break
        df=fetch_candles(exchange, pair, gran, start=cursor_start, end=cursor_end)
        if df is None or df.empty: break
        out.append(df)
        cursor_end=df["ts"].iloc[0]
        if cursor_end<=start: break
    if not out: return None
    hist=pd.concat(out, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if basis=="Weekly":
        hist = resample(hist, 7*86400)
    return hist

def ath_atl_info(hist: pd.DataFrame)->dict:
    last=float(hist["close"].iloc[-1])
    idx_ath=int(hist["high"].idxmax()); idx_atl=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[idx_ath]); d_ath=pd.to_datetime(hist["ts"].iloc[idx_ath]).date().isoformat()
    atl=float(hist["low"].iloc[idx_atl]);  d_atl=pd.to_datetime(hist["ts"].iloc[idx_atl]).date().isoformat()
    return {"From ATH %": (last/ath-1)*100 if ath>0 else np.nan, "ATH date": d_ath,
            "From ATL %": (last/atl-1)*100 if atl>0 else np.nan, "ATL date": d_atl}

# ---------------- Alerts ----------------
def send_email_alert(subject, body, recipient):
    try: cfg=st.secrets["smtp"]
    except Exception: return False, "SMTP not configured in st.secrets"
    try:
        msg=MIMEMultipart(); msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body, "plain"))
        ctx=ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port",465), context=ctx) as s:
            s.login(cfg["user"], cfg["password"]); s.sendmail(cfg["sender"], recipient, msg.as_string())
        return True, "Email sent"
    except Exception as e:
        return False, f"Email error: {e}"

def post_webhook(url, payload):
    try:
        r=requests.post(url, json=payload, timeout=10)
        return (200<=r.status_code<300), r.text
    except Exception as e:
        return False, str(e)

# ---------------- Header ----------------
st.title(APP_TITLE)

# Top-of-page context line updates after user picks TF/Trend window
_ctx = {"tf":"1h","tbasis":"Daily","tamount":90}

# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown('<div id="float-controls">', unsafe_allow_html=True)
    if st.button("Collapse all menu tabs", use_container_width=True):
        st.session_state["collapse_req"]=True
    st.markdown("</div>", unsafe_allow_html=True)

    # Manage My Pairs (pinned)
    with st.expander("Manage My Pairs", expanded=not st.session_state.get("collapse_req", False)):
        colA, colB = st.columns([1,1])
        with colA:
            use_mine = st.toggle("⭐ Use My Pairs only", value=False, help="Show only the pairs you’ve pinned.")
        with colB:
            st.caption("Tip: from tables, click the ⭐ in the Pair cell to pin/unpin.")

        # quick view/edit
        current = sorted(list(st.session_state["my_pairs"]))
        st.write(", ".join(current) if current else "—")

    # Market
    with st.expander("Market", expanded=not st.session_state.get("collapse_req", False)):
        exch = st.selectbox("Exchange", EXCHANGES_FULL, index=0,
                            help="Binance + Coinbase live. Others listed for reference.")
        effective_exch = exch
        if "coming soon" in exch:
            effective_exch = "Coinbase"
            st.info("Selected exchange is coming soon. Using Coinbase temporarily.")

        # Choose default quote per exchange if present
        dflt_q = DEFAULT_QUOTES.get(effective_exch, "USD")
        quote = st.selectbox("Quote currency", ALL_QUOTES, index=ALL_QUOTES.index(dflt_q),
                             help="Many exchanges list mostly USDT; Coinbase uses USD a lot.")

        use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
        watchlist = st.text_area("Watchlist (comma-separated)",
                                 "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")
        max_pairs = st.slider("Max pairs to evaluate (discovery)", 50, 2000, 500, 50,
                              help="Higher is slower. Set large to include ‘everything’.")

    # Timeframes
    with st.expander("Timeframes", expanded=not st.session_state.get("collapse_req", False)):
        pick_tfs = st.multiselect("Available timeframes", TF_LIST, default=TF_LIST)
        sort_tf = st.selectbox("Primary sort timeframe", TF_LIST, index=1) # default 1h
        sort_desc = st.checkbox("Sort descending (largest first)", value=True)

    # Gates (scoring)
    with st.expander("Gates", expanded=not st.session_state.get("collapse_req", False)):
        # Hioncrypto starter (placed here ABOVE green/yellow rule)
        starter_on = st.toggle("Use hioncrypto (starter)", value=True,
                               help="Lenient defaults so you always see rows. Then tighten as you like.")

        logic = st.radio("Gate logic", ["ALL","ANY"], index=0, horizontal=True,
                         help="ALL means every enabled gate must pass to count as a ‘pass’ for that gate set.")

        # Min % change (positive only)
        min_pct = st.slider("Min +% change (Sort TF)", 0.0, 50.0, 1.0 if starter_on else 5.0, 0.5)

        st.markdown("**Indicators used internally (not shown as columns)**")
        col1, col2, col3 = st.columns(3)
        with col1:
            use_vol = st.toggle("Volume spike×", value=True, help="Last volume vs 20-SMA.")
            vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, 1.02 if starter_on else 1.10, 0.02)
            use_rsi = st.toggle("RSI", value=False)
            min_rsi = st.slider("Min RSI", 30, 90, 55, 1)
        with col2:
            use_macd = st.toggle("MACD hist", value=True, help="Histogram ≥ threshold.")
            min_mhist = st.slider("Min MACD hist", 0.0, 2.0, 0.025, 0.005)
            use_atr = st.toggle("ATR %", value=False, help="ATR/close × 100")
            min_atr = st.slider("Min ATR %", 0.0, 10.0, 0.5, 0.1)
        with col3:
            use_trend = st.toggle("Trend breakout (up)", value=True,
                                  help="Close > last pivot high within N bars (micro breakout).")
            pivot_span = st.slider("Pivot span (bars)", 2, 10, 3, 1)
            trend_within = st.slider("Breakout within (bars)", 5, 192, 96, 1)

        # ROC gate
        st.markdown("---")
        use_roc = st.toggle("ROC %", value=False, help="Rate-of-change vs N bars back.")
        roc_len = st.slider("ROC length (bars)", 5, 60, 10, 1)
        min_roc = st.slider("Min ROC %", 0.0, 50.0, 0.5, 0.1)

        st.markdown("---")
        st.caption("**Color rules (green/yellow): beginner-friendly**")
        k_green = st.selectbox("Gates needed to turn green (K)", [1,2,3,4,5,6,7], index=0)
        y_need = st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0, k_green)), index=0)
        st.caption(f"Enabled checks counted now: up to 7 • Green uses K={k_green} • Yellow uses Y={y_need}.")

        st.caption("💡 If nothing shows: lower **Min %+**, reduce **K**, or toggle off a gate.")

    # Trend Break window (macro vs micro)
    with st.expander("Trend Break window (for ATH/ATL & macro view)",
                     expanded=not st.session_state.get("collapse_req", False)):
        tbasis = st.selectbox("Window basis", ["Hourly","Daily","Weekly"], index=1,
                              help="Hourly = micro / recent swings; Weekly = macro extremes.")
        if tbasis=="Hourly":
            tamount = st.slider("Hours (≤72)", 1, 72, 24, 1)
        elif tbasis=="Daily":
            tamount = st.slider("Days (≤365)", 1, 365, 90, 1)
        else:
            tamount = st.slider("Weeks (≤52)", 1, 52, 12, 1)

    # Notifications
    with st.expander("Notifications", expanded=not st.session_state.get("collapse_req", False)):
        email_to = st.text_input("Email recipient (optional)", "")
        webhook_url = st.text_input("Webhook URL (optional)", "")

    # Auto-refresh (always on)
    with st.expander("Auto-refresh", expanded=False):
        refresh_sec = st.slider("Refresh every (seconds)", 5, 120, 30, 1)
        st.caption("Auto-refresh is always on; no apply button needed.")

# reset collapse request after building sidebar
st.session_state["collapse_req"]=False

# Context label
_ctx["tf"]=sort_tf; _ctx["tbasis"]=tbasis; _ctx["tamount"]=tamount
st.markdown(f"**Timeframe:** { _ctx['tf'] } • **Trend Break window:** {tbasis} {_ctx['tamount']}")

# ---------------- Discover pairs ----------------
if use_watch and watchlist.strip():
    pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs = list_products(effective_exch, quote)
pairs = [p for p in pairs if p.endswith(f"-{quote}")]

# Optional “My Pairs only”
if 'use_mine' in locals() and use_mine and st.session_state["my_pairs"]:
    pairs = [p for p in pairs if p in st.session_state["my_pairs"]]

# Allow big sets
pairs = pairs[:max_pairs]

# ---------------- Build rows ----------------
def gate_chips(passes: dict)->str:
    # order and labels: Δ, V, R, M, A, T, X  (change, volume, rsi, macd, atr, trend, roc)
    items = [
        ("Δ", passes["pct"]),
        ("V", passes["vol"]),
        ("R", passes["rsi"]),
        ("M", passes["macd"]),
        ("A", passes["atr"]),
        ("T", passes["trend"]),
        ("X", passes["roc"]),
    ]
    html = "".join([f'<span class="gchip {"pass" if ok else "fail"}">{lbl}</span>' for lbl, ok in items])
    return html

rows = []
chg_col_name = f"% Change ({sort_tf})"
if pairs:
    for pid in pairs:
        dft = df_for_tf(effective_exch, pid, sort_tf)
        if dft is None or len(dft)<30: continue
        dft = dft.tail(600).copy()
        last = float(dft["close"].iloc[-1])
        first = float(dft["close"].iloc[0])
        pct = (last/first - 1.0) * 100.0  # total change over fetched window
        # positive-only gate later; but we keep raw pct for display
        # ATH/ATL info (macro/micro window)
        hist = get_hist(effective_exch, pid, tbasis, tamount)
        if hist is None or len(hist)<10:
            athp, athd, atlp, atld = np.nan, "—", np.nan, "—"
        else:
            aa = ath_atl_info(hist)
            athp, athd, atlp, atld = aa["From ATH %"], aa["ATH date"], aa["From ATL %"], aa["ATL date"]

        # Indicators for gates (latest bar)
        # Volume spike
        volx = volume_spike(dft, 20)

        # RSI / MACD / ATR / ROC latest values
        rsi_ser = rsi(dft["close"], 14)
        macdh = macd_hist(dft["close"], 12, 26, 9)
        atrp = (atr(dft, 14) / (dft["close"] + 1e-12)) * 100.0
        roc_ser = roc(dft["close"], 10)

        # Trend breakout recent?
        tr_up = trend_breakout_up(dft, span=pivot_span, within_bars=trend_within)

        # Assemble per-gate booleans (respect toggles + thresholds)
        g_pct  = (pct >= min_pct) and (pct > 0)
        g_vol  = (not use_vol)  or (volx >= vol_mult)
        g_rsi  = (not use_rsi)  or (rsi_ser.iloc[-1] >= min_rsi)
        g_macd = (not use_macd) or (macdh.iloc[-1] >= min_mhist)
        g_atr  = (not use_atr)  or (atrp.iloc[-1] >= min_atr)
        g_trd  = (not use_trend) or tr_up
        g_roc  = (not use_roc)  or (roc_ser.iloc[-1] >= min_roc)

        # Count passes among enabled gates
        enabled = [
            g_pct,
            g_vol if use_vol else None,
            g_rsi if use_rsi else None,
            g_macd if use_macd else None,
            g_atr if use_atr else None,
            g_trd if use_trend else None,
            g_roc if use_roc else None,
        ]
        enabled_vals = [x for x in enabled if x is not None]
        passes_ct = sum(1 for x in enabled_vals if x)
        green = passes_ct >= k_green
        yellow = (not green) and (passes_ct >= y_need if y_need>0 else False)

        rows.append({
            "Pair": pid,
            "Price": last,
            chg_col_name: pct,
            "From ATH %": athp, "ATH date": athd,
            "From ATL %": atlp, "ATL date": atld,
            "Gates": gate_chips({"pct":g_pct,"vol":g_vol,"rsi":g_rsi,"macd":g_macd,"atr":g_atr,"trend":g_trd,"roc":g_roc}),
            "Strong Buy": "YES" if green else "—",
            "_green": green,
            "_yellow": yellow,
        })

df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair"])

# ---------------- Tables + styling ----------------
if df.empty:
    st.info("No rows to show. Try: lower **Min %+**, reduce **K**, or toggle off one or more gates. "
            "Also verify quote currency fits the exchange (e.g., USDT on Binance).")
else:
    # sort by % change desc by default
    df = df.sort_values(chg_col_name, ascending=not sort_desc, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index+1)

    # Styling masks
    green_mask = df["_green"].fillna(False)
    yellow_mask = df["_yellow"].fillna(False)

    def style_rows_full(x):
        styles = pd.DataFrame("", index=x.index, columns=x.columns)
        gm = green_mask.reindex(x.index, fill_value=False)
        ym = yellow_mask.reindex(x.index, fill_value=False)
        styles.loc[gm, :] = "background-color: rgba(0,255,0,0.22); font-weight:600;"
        styles.loc[ym, :] = "background-color: rgba(255,255,0,0.60); font-weight:600;"
        return styles

    # Top-10 (green rule)
    st.subheader("📌 Top‑10 (meets green rule)")
    top10 = df[df["_green"]].sort_values(chg_col_name, ascending=False).head(10).reset_index(drop=True)
    if top10.empty:
        st.write("—")
        st.caption("💡 If empty, loosen gates or lower Min %+.")
    else:
        # alerts on new green entrants
        new_msgs=[]
        for _, r in top10.iterrows():
            key=f"{r['Pair']}|{sort_tf}|{round(float(r[chg_col_name]),2)}"
            if key not in st.session_state["alert_seen"]:
                st.session_state["alert_seen"].add(key)
                new_msgs.append(f"{r['Pair']}: {float(r[chg_col_name]):+.2f}% ({sort_tf})")
        if new_msgs:
            subject=f"[{effective_exch}] Top‑10 Crypto Tracker"
            body="\n".join(new_msgs)
            if email_to:
                ok,info=send_email_alert(subject, body, email_to)
                if not ok: st.warning(info)
            if webhook_url:
                ok,info=post_webhook(webhook_url, {"title":subject,"lines":new_msgs})
                if not ok: st.warning(f"Webhook error: {info}")

        # render top10 (hide helper cols)
        rcols=[c for c in top10.columns if not c.startswith("_")]
        st.dataframe(top10[rcols].style.apply(style_rows_full, axis=None), use_container_width=True)

    # All pairs
    st.subheader("📑 All pairs")
    rcols=[c for c in df.columns if not c.startswith("_")]
    # add star pin in Pair cell? simple: click-to-pin not supported natively; we show instruction above
    st.dataframe(df[rcols].style.apply(style_rows_full, axis=None), use_container_width=True)

    st.caption(f"Pairs: {len(df)} • Exchange: {effective_exch} • Quote: {quote} • Sort TF: {sort_tf}")

# ---------------- Auto-refresh ----------------
if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"]=time.time()
remaining = refresh_sec - (time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"]=time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {refresh_sec}s (next in {int(remaining)}s)")

