# app.py — Crypto Tracker by hioncrypto (fast discovery • sticky settings • emoji chips)
# Notes:
# - Faster discovery via caching + small concurrency.
# - Chips are emoji (no HTML) so they render inside tables and never dim the UI.
# - "Positive-only" removed. % gate uses abs(%Δ) >= min.
# - All sidebar choices persist via session_state + URL query params.
# - Top-10 uses same green rule (K). Yellow = Y..K-1. Consistent with Discover.

import json, time, datetime as dt, ssl, smtplib, threading, math, concurrent.futures as futures
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ------------------------------- Styling (soft blue) --------------------------------
st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")
st.markdown("""
<style>
/* expander headers and sidebar widgets tint */
section[data-testid="stSidebar"] div[role="button"],
section[data-testid="stSidebar"] summary {
  background: rgba(46, 134, 222, 0.14) !important;
  border-radius: 8px !important;
}
section[data-testid="stSidebar"] .stButton>button {
  background: rgba(46, 134, 222, 0.25) !important;
  border: 1px solid rgba(46,134,222,0.45) !important;
}
section[data-testid="stSidebar"] .st-emotion-cache-1vbkxwb, /* selectbox */
section[data-testid="stSidebar"] .st-emotion-cache-uf99v8 { /* slider block */
  background: rgba(46, 134, 222, 0.08) !important;
  border-radius: 8px !important;
}
[data-testid="stSidebarNav"] { display:none !important; }

/* keep tables bright */
.stDataFrame { filter: none !important; opacity: 1 !important; }

/* small mono chips style via Unicode only (no HTML in table) */
</style>
""", unsafe_allow_html=True)

# ------------------------------- Helpers & state ------------------------------------
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

ALL_TFS = {"15m":900, "1h":3600, "4h":14400, "6h":21600, "12h":43200, "1d":86400}
TF_LIST = list(ALL_TFS.keys())

def ss_init():
    ss = st.session_state
    ss.setdefault("last_df", None)
    ss.setdefault("alert_seen", set())
    ss.setdefault("prefs_loaded", False)
ss_init()

def qp_get(name, default=None, conv=None):
    qp = st.query_params
    if name in qp:
        v = qp[name]
        if isinstance(v, list): v = v[-1]
        try:
            return conv(v) if conv else v
        except Exception:
            return default
    return default

def qp_set(mapping: Dict[str,str]):
    try:
        st.query_params.update(mapping)
    except Exception:
        pass

# ------------------------------- Indicators -----------------------------------------
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    d = close.diff()
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    ru = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rd = pd.Series(dn, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = ru / (rd + 1e-12)
    return 100 - (100 / (1 + rs))

def macd_hist(close: pd.Series, fast=12, slow=26, signal=9) -> pd.Series:
    ml = ema(close, fast) - ema(close, slow)
    return ml - ema(ml, signal)

def atr(df: pd.DataFrame, length=14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def volume_spike(df: pd.DataFrame, window=20) -> float:
    if len(df) < window + 1: return np.nan
    return float(df["volume"].iloc[-1] / (df["volume"].rolling(window).mean().iloc[-1] + 1e-12))

def find_pivots(close: pd.Series, span=3) -> Tuple[pd.Index,pd.Index]:
    n=len(close); hi=[]; lo=[]; v=close.values
    for i in range(span, n-span):
        if v[i]>v[i-span:i].max() and v[i]>v[i+1:i+1+span].max(): hi.append(i)
        if v[i]<v[i-span:i].min() and v[i]<v[i+1:i+1+span].min(): lo.append(i)
    return pd.Index(hi), pd.Index(lo)

def trend_breakout_up(df: pd.DataFrame, span=3, within_bars=48) -> bool:
    if df is None or len(df) < span*2+5: return False
    highs,_ = find_pivots(df["close"], span)
    if len(highs)==0: return False
    hi = int(highs[-1]); level = float(df["close"].iloc[hi])
    cross = None
    for j in range(hi+1, len(df)):
        if float(df["close"].iloc[j]) > level:
            cross = j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# ------------------------------- Data fetch -----------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=20); r.raise_for_status()
        data = r.json()
        return sorted(f"{p['base_currency']}-{p['quote_currency']}" for p in data if p.get("quote_currency")==quote)
    except Exception:
        return []

@st.cache_data(ttl=600, show_spinner=False)
def binance_list_products(quote: str) -> List[str]:
    try:
        r=requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25); r.raise_for_status()
        out=[]
        for s in r.json().get("symbols",[]):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote:
                out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange=="Coinbase": return coinbase_list_products(quote)
    if exchange=="Binance":  return binance_list_products(quote)
    # future exchanges could fall back here
    return coinbase_list_products(quote)

@st.cache_data(ttl=300, show_spinner=False)
def fetch_candles(exchange: str, pair_dash: str, gran_sec: int, limit: int=400) -> Optional[pd.DataFrame]:
    try:
        if exchange=="Coinbase":
            url = f"{CB_BASE}/products/{pair_dash}/candles?granularity={gran_sec}"
            r = requests.get(url, timeout=20); 
            if r.status_code!=200: return None
            arr = r.json()
            if not arr: return None
            df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
            df = df.sort_values("ts").tail(limit).reset_index(drop=True)
            return df
        elif exchange=="Binance":
            base, quote = pair_dash.split("-"); symbol=f"{base}{quote}"
            interval_map = {900:"15m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
            interval = interval_map.get(gran_sec)
            if not interval: return None
            params = {"symbol":symbol, "interval":interval, "limit":min(limit,1000)}
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

# ------------------------------- Gates builder --------------------------------------
def build_gate_flags(dft: pd.DataFrame, settings: dict) -> Tuple[Dict[str,bool], float]:
    # % change over the dataframe (first->last)
    last = float(dft["close"].iloc[-1]); first=float(dft["close"].iloc[0])
    pct = (last/first - 1.0) * 100.0

    # indicators (last values)
    volx = volume_spike(dft, settings["vol_window"]) if settings["use_vol_spike"] else np.nan
    rsi_last = float(rsi(dft["close"], settings["rsi_len"]).iloc[-1]) if settings["use_rsi"] else np.nan
    mh_last  = float(macd_hist(dft["close"], settings["macd_fast"], settings["macd_slow"], settings["macd_sig"]).iloc[-1]) if settings["use_macd"] else np.nan
    atr_pct  = float(atr(dft, settings["atr_len"]).iloc[-1] / (dft["close"].iloc[-1] + 1e-12) * 100.0) if settings["use_atr"] else np.nan
    tr_up    = trend_breakout_up(dft, settings["pivot_span"], settings["trend_within"]) if settings["use_trend"] else True
    # ROC
    roc = np.nan
    if settings["use_roc"]:
        n = settings["roc_len"]
        if len(dft)>=n+1:
            roc = (dft["close"].iloc[-1] / dft["close"].iloc[-1-n] - 1.0) * 100.0

    # Gates: abs move for %Δ (no positive-only)
    g = {}
    g["Δ"] = abs(pct) >= settings["min_pct"]
    g["V"] = (not settings["use_vol_spike"]) or (volx >= settings["vol_mult"])
    g["R"] = (not settings["use_roc"]) or (roc >= settings["min_roc"])
    g["T"] = (not settings["use_trend"]) or bool(tr_up)
    g["S"] = (not settings["use_rsi"]) or (rsi_last >= settings["min_rsi"])
    g["M"] = (not settings["use_macd"]) or (mh_last  >= settings["min_mhist"])
    g["A"] = (not settings["use_atr"]) or (atr_pct  >= settings["min_atr"])
    return g, pct

def chip_line(g: Dict[str,bool]) -> str:
    # emoji chips (render in st.dataframe)
    def mark(ok): return "✅" if ok else "❌"
    order = ["Δ","V","R","T","S","M","A"]
    return " ".join(f"{k}{mark(g[k])}" for k in order)

# ------------------------------- Alerts ---------------------------------------------
def send_email_alert(subject, body, recipient):
    try: cfg=st.secrets["smtp"]
    except Exception: return False, "SMTP not configured"
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

# ------------------------------- Sidebar (persistent) -------------------------------
st.title("Crypto Tracker by hioncrypto")

with st.sidebar:
    st.markdown("### Market")
    exch = st.selectbox(
        "Exchange",
        ["Coinbase","Binance"],
        index=qp_get("ex",0,int),
        key="exch"
    )
    quote = st.selectbox(
        "Quote currency",
        ["USD","USDC","USDT","BTC","ETH","EUR"],
        index=qp_get("q",0,int),
        key="quote"
    )

    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=qp_get("wl","0")== "1", key="use_watch")
    watchlist = st.text_area("Watchlist (comma-separated)",
                             qp_get("wlst","BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD"),
                             key="watchlist")
    # discovery size
    # We'll show count found live further below
    max_pairs = st.slider("Max pairs to evaluate (discovery)", 10, 500, qp_get("mp",300,int), step=10, key="max_pairs")

    with st.expander("Timeframes"):
        sort_tf = st.selectbox("Primary timeframe (for % change)", TF_LIST, index=TF_LIST.index(qp_get("tf","1h")), key="sort_tf")

    with st.expander("Gates"):
        # built-in preset toggle (off by default, per request)
        # (We leave the switch out; presets are via dropdown at bottom.)
        st.caption("Green = passes ≥ **K** gates. Yellow = passes ≥ **Y** but < K.")
        cols = st.columns(3)
        with cols[0]:
            use_vol_spike = st.toggle("Volume spike×", value=True, key="use_vol")
            vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, qp_get("vm",1.10,float), 0.05, key="vol_mult")
        with cols[1]:
            use_macd = st.toggle("MACD hist", value=True, key="use_macd")
            min_mhist = st.slider("Min MACD hist", 0.0, 2.0, qp_get("mh",0.0,float), 0.05, key="min_mhist")
        with cols[2]:
            use_rsi = st.toggle("RSI", value=False, key="use_rsi")
            min_rsi = st.slider("Min RSI", 40, 90, qp_get("mr",55,int), 1, key="min_rsi")

        cols2 = st.columns(3)
        with cols2[0]:
            use_atr = st.toggle("ATR %", value=False, help="ATR/close × 100", key="use_atr")
            min_atr = st.slider("Min ATR %", 0.0, 10.0, qp_get("ma",0.5,float), 0.1, key="min_atr")
        with cols2[1]:
            use_trend = st.toggle("Trend breakout (up)", value=True, key="use_trend")
            pivot_span = st.slider("Pivot span (bars)", 2, 10, qp_get("ps",4,int), 1, key="pivot_span")
            trend_within = st.slider("Breakout within (bars)", 5, 96, qp_get("tw",48,int), 1, key="trend_within")
        with cols2[2]:
            use_roc = st.toggle("ROC %", value=True, key="use_roc")
            roc_len = st.slider("ROC length", 5, 60, qp_get("rl",14,int), 1, key="roc_len")
            min_roc = st.slider("Min ROC %", -20.0, 20.0, qp_get("rmin",0.0,float), 0.1, key="min_roc")

        # % change gate (abs move)
        min_pct = st.slider("Min |% change| (Sort TF)", 0.0, 50.0, qp_get("pc",2.0,float), 0.5, key="min_pct")

        st.divider()
        cols3 = st.columns(2)
        with cols3[0]:
            k_need = st.selectbox("Gates needed to turn green (K)", [1,2,3,4,5,6,7], index=qp_get("k",2,int), key="k_need")
        with cols3[1]:
            y_need = st.selectbox("Yellow needs ≥ Y (but < K)", [0,1,2,3,4,5,6], index=qp_get("y",1,int), key="y_need")
        st.caption(f"Enabled checks counted now: Δ • V • R • T • S • M • A")

        st.markdown("**Presets (Aggressive / Balanced / Conservative)**")
        preset = st.selectbox("Apply built-in preset", ["—","Aggressive","Balanced","Conservative"], key="preset_pick")

    with st.expander("Notifications"):
        do_alerts = st.checkbox("Send Email/Webhook alerts this session", value=False, key="do_alerts")
        email_to = st.text_input("Email recipient (optional)", "", key="email_to")
        webhook_url = st.text_input("Webhook URL (optional)", "", key="hook_url")

# Apply built-in presets AFTER we created the widgets (no extra buttons)
if preset != "—":
    if preset=="Aggressive":
        st.session_state.min_pct = 1.0; st.session_state.k_need = 2; st.session_state.y_need = 1
        st.session_state.use_rsi=False; st.session_state.use_atr=False
        st.session_state.use_trend=True; st.session_state.use_vol=True; st.session_state.vol_mult=1.05
        st.session_state.use_macd=True; st.session_state.min_mhist=0.0
        st.session_state.use_roc=True; st.session_state.min_roc=0.0
    elif preset=="Balanced":
        st.session_state.min_pct = 2.0; st.session_state.k_need = 3; st.session_state.y_need = 2
        st.session_state.use_rsi=False; st.session_state.use_atr=False
        st.session_state.use_trend=True; st.session_state.use_vol=True; st.session_state.vol_mult=1.10
        st.session_state.use_macd=True; st.session_state.min_mhist=0.0
        st.session_state.use_roc=True; st.session_state.min_roc=0.0
    else: # Conservative
        st.session_state.min_pct = 3.0; st.session_state.k_need = 4; st.session_state.y_need = 2
        st.session_state.use_rsi=True; st.session_state.min_rsi=55
        st.session_state.use_atr=False
        st.session_state.use_trend=True; st.session_state.use_vol=True; st.session_state.vol_mult=1.15
        st.session_state.use_macd=True; st.session_state.min_mhist=0.1
        st.session_state.use_roc=True; st.session_state.min_roc=0.0

# Persist choices to URL so refresh keeps them
qp_set({
    "ex": str(["Coinbase","Binance"].index(st.session_state.exch)),
    "q":  str(["USD","USDC","USDT","BTC","ETH","EUR"].index(st.session_state.quote)),
    "wl": "1" if st.session_state.use_watch else "0",
    "wlst": st.session_state.watchlist,
    "mp": str(st.session_state.max_pairs),
    "tf": st.session_state.sort_tf,
    "vm": str(st.session_state.vol_mult),
    "mh": str(st.session_state.min_mhist),
    "mr": str(st.session_state.min_rsi),
    "ma": str(st.session_state.min_atr),
    "ps": str(st.session_state.pivot_span),
    "tw": str(st.session_state.trend_within),
    "rl": str(st.session_state.roc_len),
    "rmin": str(st.session_state.min_roc),
    "pc": str(st.session_state.min_pct),
    "k": str(st.session_state.k_need),
    "y": str(st.session_state.y_need),
})

# ------------------------------- Discovery ------------------------------------------
# Build pair list
if st.session_state.use_watch:
    pairs = [p.strip().upper() for p in st.session_state.watchlist.split(",") if p.strip()]
else:
    pairs = list_products(st.session_state.exch, st.session_state.quote)

pairs = [p for p in pairs if p.endswith(f"-{st.session_state.quote}")]
found_count = len(pairs)
pairs = pairs[:st.session_state.max_pairs]

st.caption(f"Discovery: found **{found_count}** exchange pairs • evaluating **{len(pairs)}**")

# Prepare settings dict
settings = dict(
    min_pct=st.session_state.min_pct,
    use_vol_spike=st.session_state.use_vol, vol_window=20, vol_mult=st.session_state.vol_mult,
    use_rsi=st.session_state.use_rsi, min_rsi=st.session_state.min_rsi, rsi_len=14,
    use_macd=st.session_state.use_macd, min_mhist=st.session_state.min_mhist,
    use_atr=st.session_state.use_atr, min_atr=st.session_state.min_atr, atr_len=14,
    use_trend=st.session_state.use_trend, pivot_span=st.session_state.pivot_span, trend_within=st.session_state.trend_within,
    macd_fast=12, macd_slow=26, macd_sig=9,
    use_roc=st.session_state.use_roc, roc_len=st.session_state.roc_len, min_roc=st.session_state.min_roc
)

gran = ALL_TFS[st.session_state.sort_tf]

# Concurrent fetch + compute
rows = []
if pairs:
    with st.spinner(f"Evaluating {len(pairs)} pairs…"):
        def work(pid):
            df = fetch_candles(st.session_state.exch, pid, gran, limit=240)
            if df is None or len(df) < 30: 
                return None
            g, pct = build_gate_flags(df, settings)
            pass_cnt = sum(g.values())
            state = "green" if pass_cnt >= st.session_state.k_need else ("yellow" if pass_cnt >= st.session_state.y_need else "none")
            return {
                "Pair": pid,
                "Price": float(df["close"].iloc[-1]),
                f"% Change ({st.session_state.sort_tf})": pct,
                "Gates": chip_line(g),
                "Passes": pass_cnt,
                "Strong Buy": "YES" if state=="green" else "—",
                "_state": state
            }

        with futures.ThreadPoolExecutor(max_workers=8) as exr:
            for res in exr.map(work, pairs):
                if res: rows.append(res)

# Build DataFrames
df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair"])
if not df.empty:
    chg_col = f"% Change ({st.session_state.sort_tf})"
    # sort by % change desc (no positive-only)
    df = df.sort_values(chg_col, ascending=False, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index+1)

    # Top-10 (green)
    top10 = df[df["_state"].eq("green")].sort_values(chg_col, ascending=False).head(10).reset_index(drop=True)
    top10.insert(0, "#", top10.index+1)

    st.subheader("📌 Top-10 (meets green rule)")
    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, loosen gates (lower Min |% change| or toggle some gates off).")
    else:
        st.dataframe(
            top10.drop(columns=["_state"]),
            use_container_width=True,
            height=min(600, 44*(len(top10)+1))
        )

    st.subheader("📑 Discover")
    st.dataframe(
        df.drop(columns=["_state"]),
        use_container_width=True,
        height=min(720, 44*(min(len(df), 16)+1))
    )

    # Alerts (Top-10 new)
    if st.session_state.get("do_alerts") and (st.session_state.get("email_to") or st.session_state.get("hook_url")):
        new_msgs=[]
        for _, r in top10.iterrows():
            key = f"{r['Pair']}|{st.session_state.sort_tf}|{round(float(r[chg_col]),2)}"
            if key not in st.session_state["alert_seen"]:
                st.session_state["alert_seen"].add(key)
                new_msgs.append(f"{r['Pair']}: {float(r[chg_col]):+.2f}% ({st.session_state.sort_tf})")
        if new_msgs:
            subject = f"[{st.session_state.exch}] Top-10 Crypto Tracker"
            body    = "\n".join(new_msgs)
            if st.session_state.get("email_to"):
                ok, info = send_email_alert(subject, body, st.session_state["email_to"])
                if not ok: st.sidebar.warning(info)
            if st.session_state.get("hook_url"):
                ok, info = post_webhook(st.session_state["hook_url"], {"title": subject, "lines": new_msgs})
                if not ok: st.sidebar.warning(f"Webhook error: {info}")

    st.session_state["last_df"] = df.copy()
else:
    # nothing new — show last if available
    if st.session_state["last_df"] is not None:
        st.warning("No fresh rows matched right now. Showing last results.")
        st.dataframe(st.session_state["last_df"].drop(columns=["_state"]), use_container_width=True)
    else:
        st.info("No rows to show yet. Try a looser Min |% change| or fewer required gates.")
