# app.py — Crypto Tracker by hioncrypto (simple, loose-by-default, all-in-one)
# Streamlit app focused on momentum discovery with “starter” preset toggle, blue UI,
# micro/macro trend-break window, Top-10, and instant-apply controls (no Apply buttons).

import json, time, datetime as dt, ssl, smtplib, math
from typing import List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
import requests
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# --------------------------- Basic config
st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")

# --------------------------- Style (blue sidebar buttons + table highlight)
st.markdown("""
<style>
/* Global font scaling later via slider if you want */
:root { --mv-blue:#1a73e8; --mv-blue-2:#115fd1; --mv-true-yellow: rgba(255, 255, 0, .65); --mv-true-green: rgba(0, 200, 0, .22); }
section[data-testid="stSidebar"] button, section[data-testid="stSidebar"] .stButton button{
  background: var(--mv-blue)!important; color:#fff!important; border:0!important; border-radius:10px!important;
}
section[data-testid="stSidebar"] .st-emotion-cache-13ln4jf { color: var(--mv-blue)!important } /* toggle label hint */
div[data-testid="stExpander"] summary { color: var(--mv-blue)!important; font-weight: 700; }
.mv-row-green { background: var(--mv-true-green)!important; font-weight: 700; }
.mv-row-yellow { background: var(--mv-true-yellow)!important; font-weight: 700; }
.mv-chip { display:inline-block; padding:2px 6px; margin-right:6px; border-radius:6px; font-size:.78rem; color:#111; background:#e9eefb; border:1px solid #cbd5f7; }
.mv-chip.mv-ok { background:#d8f6d8; border-color:#93e093;}
.mv-chip.mv-bad{ background:#ffe3e3; border-color:#ffb1b1;}
.mv-pill { padding:3px 8px; border-radius:999px; background:#edf4ff; border:1px solid #c9dbff; color:#093; font-weight:600; }
.mv-leg { font-size:.85rem; opacity:.85; margin:2px 0 16px 0 }
.mv-topline { font-size:1rem; opacity:.8; margin-bottom:12px }
.mv-sticky { position:sticky; top:0; z-index: 5; background: rgba(22,24,29,.85); backdrop-filter: blur(6px); padding:8px 0;}
/* compact select boxes */
section[data-testid="stSidebar"] select { border:1px solid var(--mv-blue)!important }
</style>
""", unsafe_allow_html=True)

# --------------------------- Session defaults
def _init_state():
    ss = st.session_state
    ss.setdefault("collapse_all_now", False)
    ss.setdefault("my_pairs", set())                 # pins
    ss.setdefault("use_my_pairs_only", False)       # toggle
    ss.setdefault("gate_presets", {})               # user-saved presets (in session; cloud-safe)
    ss.setdefault("starter_on", True)               # hioncrypto starter preset on by default
    ss.setdefault("page_size", 50)                  # paging for large tables
    ss.setdefault("page_idx", 0)                    # current page
_init_state()

# --------------------------- Exchanges (REST only – Coinbase first)
EXCHANGES = ["Coinbase"]  # others “coming soon” can be added later
QUOTES    = ["USD","USDC","USDT","BTC","ETH","EUR"]
TF_SEC = {"15m":900, "1h":3600, "4h":14400, "6h":21600, "12h":43200, "1d":86400}
DEFAULT_TFS = ["15m","1h","4h","6h","12h","1d"]

CB_BASE = "https://api.exchange.coinbase.com"

def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25)
        r.raise_for_status()
        data = r.json()
        pairs = []
        for p in data:
            if p.get("quote_currency")==quote:
                pairs.append(f"{p['base_currency']}-{p['quote_currency']}")
        # Return ALL (no cap)
        return sorted(set(pairs))
    except Exception:
        return []

def fetch_candles_coinbase(pair: str, granularity_sec: int,
                           start: Optional[dt.datetime]=None,
                           end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    try:
        url = f"{CB_BASE}/products/{pair}/candles?granularity={granularity_sec}"
        params={}
        if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
        if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
        r = requests.get(url, params=params, timeout=30)
        if r.status_code!=200: return None
        arr = r.json()
        if not arr: return None
        # Coinbase: [time, low, high, open, close, volume]
        df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
        return df.sort_values("ts").reset_index(drop=True)
    except Exception:
        return None

def resample_ohlcv(df: pd.DataFrame, target_sec: int) -> Optional[pd.DataFrame]:
    if df is None or df.empty: return None
    d = df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    out = d.resample(f"{target_sec}s", label="right", closed="right").agg(agg).dropna()
    return out.reset_index()

def df_for_tf(exchange: str, pair: str, tf: str) -> Optional[pd.DataFrame]:
    sec = TF_SEC[tf]
    # Coinbase native granularities: 60, 300, 900, 3600, 21600, 86400
    native = sec in {900,3600,21600,86400}
    base = fetch_candles_coinbase(pair, sec if native else 3600)
    if base is None: return None
    return base if native else resample_ohlcv(base, sec)

# --------------------------- Indicators & helpers
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    d = close.diff()
    up = np.where(d>0, d, 0.0); dn = np.where(d<0, -d, 0.0)
    ru = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rd = pd.Series(dn, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = ru/(rd+1e-12)
    return 100 - (100/(1+rs))

def macd_hist(close: pd.Series, fast=12, slow=26, sig=9) -> pd.Series:
    m = ema(close, fast) - ema(close, slow)
    s = ema(m, sig)
    return m - s

def atr(df: pd.DataFrame, length=14) -> pd.Series:
    h,l,c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def volume_spike_x(df: pd.DataFrame, window=20) -> float:
    if len(df)<window+1: return np.nan
    return float(df["volume"].iloc[-1] / (df["volume"].rolling(window).mean().iloc[-1] + 1e-12))

def roc(close: pd.Series, length=10) -> pd.Series:
    return (close / close.shift(length) - 1.0) * 100.0

def find_pivots(close: pd.Series, span=3) -> Tuple[pd.Index, pd.Index]:
    n=len(close); v=close.values; hi=[]; lo=[]
    for i in range(span, n-span):
        if v[i]>v[i-span:i].max() and v[i]>v[i+1:i+1+span].max(): hi.append(i)
        if v[i]<v[i-span:i].min() and v[i]<v[i+1:i+1+span].min(): lo.append(i)
    return pd.Index(hi), pd.Index(lo)

def trend_breakout_up(df: pd.DataFrame, span=3, within_bars=48) -> bool:
    if df is None or len(df)<span*2+5: return False
    highs,_ = find_pivots(df["close"], span)
    if len(highs)==0: return False
    hi=int(highs[-1]); level=float(df["close"].iloc[hi])
    cross=None
    for j in range(hi+1, len(df)):
        if float(df["close"].iloc[j])>level:
            cross=j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# --------------------------- ATH/ATL window (micro/macro)
def get_hist_for_trend(pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":
        gran=3600; start=end-dt.timedelta(hours=amount)
    elif basis=="Daily":
        gran=86400; start=end-dt.timedelta(days=amount)
    else:
        gran=86400; start=end-dt.timedelta(weeks=amount)
    out=[]; cursor_end=end
    while True:
        # Coinbase allows up to 300 rows at once; do rolling windows
        df = fetch_candles_coinbase(pair, gran, start=max(start, cursor_end - dt.timedelta(days=30)), end=cursor_end)
        if df is None or df.empty: break
        out.append(df)
        cursor_end = df["ts"].iloc[0]
        if cursor_end<=start: break
    if not out: return None
    hist=pd.concat(out, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if basis=="Weekly":
        hist = resample_ohlcv(hist, 7*86400)
    return hist

def ath_atl_info(hist: pd.DataFrame) -> Dict[str,object]:
    last=float(hist["close"].iloc[-1])
    ia=int(hist["high"].idxmax()); iz=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[ia]); atd=pd.to_datetime(hist["ts"].iloc[ia]).date().isoformat()
    atl=float(hist["low"].iloc[iz]);  ztd=pd.to_datetime(hist["ts"].iloc[iz]).date().isoformat()
    return {
        "From ATH %": (last/ath-1.0)*100 if ath>0 else np.nan,
        "ATH date": atd,
        "From ATL %": (last/atl-1.0)*100 if atl>0 else np.nan,
        "ATL date": ztd,
    }

# --------------------------- Email/Webhook (optional)
def send_email_alert(subject, body, recipient):
    try: cfg = st.secrets["smtp"]
    except Exception: return False, "SMTP not configured"
    try:
        msg=MIMEMultipart(); msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body,"plain"))
        ctx=ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port",465), context=ctx) as s:
            s.login(cfg["user"], cfg["password"]); s.sendmail(cfg["sender"], recipient, msg.as_string())
        return True, "OK"
    except Exception as e:
        return False, str(e)

# --------------------------- Sidebar (sticky controller row)
with st.sidebar:
    colA, colB = st.columns([1,1])
    with colA:
        if st.button("Collapse all", use_container_width=True):
            st.session_state["collapse_all_now"]=True
    with colB:
        st.session_state["use_my_pairs_only"] = st.toggle("⭐ Use My Pairs only", value=st.session_state["use_my_pairs_only"],
                                                         help="When ON, only scan pairs you pin into ‘My Pairs’.")
    st.divider()

def expander(title, key):
    opened = not st.session_state.get("collapse_all_now", False)
    return st.sidebar.expander(title, expanded=opened)

# --------------------------- Market
with expander("Market", "exp_market"):
    st.caption("Pick exchange/quote. Discovery merges **all** products for that quote (no cap).")
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    quote    = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False,
                             help="ON = only scan the comma-separated pairs below.")
    default_watch = "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD"
    watchlist = st.text_area("Watchlist (comma-separated)", default_watch, height=80)
    st.caption("💡 Tip: Pin/unpin pairs from the table rows into **My Pairs**.")

# --------------------------- “My Pairs” manager (top)
with expander("Manage My Pairs", "exp_my"):
    pins = sorted(st.session_state["my_pairs"])
    st.write("Pinned pairs:", ", ".join(pins) if pins else "—")
    newpin = st.text_input("Add pair (e.g. SOL-USD)")
    cols = st.columns([1,1,1])
    if cols[0].button("Add", use_container_width=True) and newpin.strip():
        st.session_state["my_pairs"].add(newpin.strip().upper())
    if cols[1].button("Clear all", use_container_width=True):
        st.session_state["my_pairs"].clear()
    if cols[2].button("Load defaults (BTC/ETH/SOL)", use_container_width=True):
        st.session_state["my_pairs"].update({"BTC-USD","ETH-USD","SOL-USD"})

# --------------------------- Timeframes
with expander("Timeframes", "exp_tf"):
    pick_tfs = st.multiselect("Available timeframes", DEFAULT_TFS, default=DEFAULT_TFS)
    sort_tf  = st.selectbox("Primary sort timeframe", DEFAULT_TFS, index=1,
                            help="Used for % Change and ranking (default 1h).")
    sort_desc = st.checkbox("Sort descending (largest first)", value=True)

# --------------------------- Gates + hioncrypto starter toggle
with expander("Gates", "exp_gates"):
    # Very first control: the starter preset
    st.session_state["starter_on"] = st.toggle(
        "Use hioncrypto (starter)",
        value=st.session_state["starter_on"],
        help="A friendly loose preset so rows appear right away. Toggle OFF to fine‑tune manually."
    )

    # Manual gate controls (all instant-apply)
    gate_logic = st.radio("Gate logic", ["ALL","ANY"], index=0, horizontal=True,
                          help="ALL = pair must satisfy K gates; ANY = passes if any considered gate is true.")
    # basic momentum gate
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 50.0, 5.0, 0.5,
                        help="Positive-only % change over selected TF.")
    st.caption("If nothing shows, lower this % or turn **starter** ON.")

    colsA = st.columns(3)
    with colsA[0]:
        use_vol = st.toggle("Volume spike×", value=True, help="Last volume vs 20-SMA.")
        vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, 1.05, 0.05)
    with colsA[1]:
        use_macd = st.toggle("MACD hist", value=True, help="Momentum must be ≥ threshold.")
        min_mhist = st.slider("Min MACD hist", 0.0, 2.0, 0.025, 0.005)
    with colsA[2]:
        use_trend = st.toggle("Trend breakout (up)", value=True,
                              help="Close breaks above last pivot high within lookback bars.")
        pivot_span = st.slider("Pivot span (bars)", 2, 10, 3, 1)
        trend_within = st.slider("Breakout within (bars)", 5, 96, 72, 1)

    colsB = st.columns(3)
    with colsB[0]:
        use_rsi = st.toggle("RSI", value=False, help="Min RSI filter (optional).")
        min_rsi = st.slider("Min RSI", 40, 90, 55, 1)
    with colsB[1]:
        use_atr = st.toggle("ATR %", value=False, help="ATR/close ×100, min threshold.")
        min_atr = st.slider("Min ATR %", 0.0, 10.0, 0.30, 0.05)
    with colsB[2]:
        use_roc = st.toggle("ROC %", value=False, help="Rate of Change over N bars.")
        roc_len = st.slider("ROC length (bars)", 2, 60, 10, 1)
        min_roc = st.slider("Min ROC %", -10.0, 50.0, 0.0, 0.5)

    st.markdown("**Color rules (beginner‑friendly)**")
    k_needed = st.selectbox("Gates needed to turn green (K)", [1,2,3,4,5,6,7], index=1)
    y_needed = st.selectbox("Yellow needs ≥ Y (but < K)", [0,1,2,3,4,5,6], index=1)

    # Apply “starter” loose values if toggle ON
    if st.session_state["starter_on"]:
        gate_logic = "ALL"
        min_pct    = 5.0
        use_vol, vol_mult = True, 1.05
        use_macd, min_mhist = True, 0.025
        use_trend, pivot_span, trend_within = True, 3, 72
        # keep RSI/ATR/ROC optional but off by default in starter
        use_rsi, min_rsi = False, 55
        use_atr, min_atr = False, 0.30
        use_roc, roc_len, min_roc = False, 10, 0.0
        k_needed, y_needed = 2, 1
        st.info("Starter preset ON — loose, rows should appear. Toggle OFF to adjust manually.", icon="✨")

# --------------------------- Trend Break window (ATH/ATL)
with expander("Trend Break window", "exp_window"):
    st.caption("Micro + macro: choose the window for ATH/ATL context and trend break age.")
    basis = st.selectbox("Window basis", ["Hourly","Daily","Weekly"], index=1,
                         help="Hourly for micro swings, Weekly for macro extremes.")
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1)
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 90, 1)
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 12, 1)

# --------------------------- Display & paging
with expander("Display", "exp_display"):
    st.caption("Large universes can be paged while still scanning everything.")
    st.session_state["page_size"] = st.slider("Rows per page (table only)", 25, 200, st.session_state["page_size"], 25)
    st.session_state["page_idx"]  = st.number_input("Page index (0‑based)", min_value=0, value=st.session_state["page_idx"], step=1)

# --------------------------- Discovery
if use_watch and watchlist.strip():
    universe = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    universe = coinbase_list_products(quote)

# Apply “My Pairs only”
if st.session_state["use_my_pairs_only"] and st.session_state["my_pairs"]:
    universe = sorted(set(universe).intersection(st.session_state["my_pairs"]))

if not universe:
    st.warning("No pairs discovered. Try different quote currency or disable filters.")
    st.stop()

# --------------------------- Build rows
rows=[]
for pid in universe:
    dft = df_for_tf("Coinbase", pid, sort_tf)
    if dft is None or len(dft)<30: continue
    dft = dft.tail(500).copy()

    last = float(dft["close"].iloc[-1])
    first= float(dft["close"].iloc[0])
    pct  = (last/first - 1.0)*100.0  # positive-only handled by gate

    # ATH/ATL context
    hist = get_hist_for_trend(pid, basis, amount)
    if hist is None or len(hist)<10:
        athp, atld, atlq, atlqd = np.nan,"—",np.nan,"—"
    else:
        info = ath_atl_info(hist)
        athp, atld, atlq, atlqd = info["From ATH %"], info["ATH date"], info["From ATL %"], info["ATL date"]

    # Gates
    checks = []
    # % change (positive & min)
    checks.append(("Δ%Change", (pct>0 and pct>=min_pct)))

    # Volume spike
    if use_vol:
        spx = volume_spike_x(dft, window=20)
        checks.append(("Volume×", bool(spx>=vol_mult)))
    # MACD hist
    if use_macd:
        mh = macd_hist(dft["close"]).iloc[-1]
        checks.append(("MACD", bool(mh>=min_mhist)))
    # Trend breakout
    if use_trend:
        tb = trend_breakout_up(dft, span=pivot_span, within_bars=trend_within)
        checks.append(("Trend", bool(tb)))
    # RSI
    if use_rsi:
        r = rsi(dft["close"]).iloc[-1]
        checks.append(("RSI", bool(r>=min_rsi)))
    # ATR%
    if use_atr:
        ap = float(atr(dft).iloc[-1])/(last+1e-12)*100.0
        checks.append(("ATR", bool(ap>=min_atr)))
    # ROC%
    if use_roc:
        rc = float(roc(dft["close"], roc_len).iloc[-1])
        checks.append(("ROC", bool(rc>=min_roc)))

    # Evaluate gates
    enabled = [name for name,_ in checks]
    trues   = [ok for _,ok in checks]
    cnt_true = sum(trues)
    if gate_logic=="ALL":
        green = (cnt_true >= k_needed)
    else:
        green = (cnt_true >= 1)  # ANY logic still respects K for “green” threshold
    yellow = (not green) and (cnt_true >= y_needed)

    # Chips string
    chips_html = []
    for name, ok in checks:
        chips_html.append(f"<span class='mv-chip {'mv-ok' if ok else 'mv-bad'}'>{name[0]}</span>")
    chips = "".join(chips_html)

    rows.append({
        "Pair": pid, "Price": last, f"% Change ({sort_tf})": pct,
        "From ATH %": athp, "ATH date": atld, "From ATL %": atlq, "ATL date": atlqd,
        "Gates": chips, "Strong Buy": "YES" if green else ("—" if not yellow else "PARTIAL"),
        "_green": green, "_yellow": yellow
    })

df = pd.DataFrame(rows)
if df.empty:
    st.warning("Discovery found pairs, but filters removed everything. Starter preset is ON; if you still see nothing, try changing timeframe.")
    st.stop()

chg_col = f"% Change ({sort_tf})"
df = df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
df.insert(0, "#", df.index+1)

# Keep coloring data in columns for style use
green_mask = df["_green"].copy()
yellow_mask= df["_yellow"].copy()
df = df.drop(columns=["_green","_yellow"])

# --------------------------- Legend + counts
st.markdown(f"<div class='mv-sticky mv-topline'>Timeframe: <b>{sort_tf}</b> • Trend Break window: <b>{basis}{amount}</b></div>", unsafe_allow_html=True)
st.markdown("<div class='mv-leg'>Legend: <span class='mv-chip mv-ok'>Δ</span> %Change • <span class='mv-chip mv-ok'>V</span> Volume× • <span class='mv-chip mv-ok'>R</span> ROC • <span class='mv-chip mv-ok'>T</span> Trend • <span class='mv-chip mv-ok'>S</span> RSI • <span class='mv-chip mv-ok'>M</span> MACD • <span class='mv-chip mv-ok'>A</span> ATR</div>", unsafe_allow_html=True)

# --------------------------- Top-10 (green only)
st.subheader("📌 Top‑10 (meets green rule)")
top10 = df[green_mask].copy().sort_values(chg_col, ascending=False).head(10).reset_index(drop=True)
if top10.empty:
    st.write("—")
else:
    def style_green(x: pd.DataFrame):
        s = pd.DataFrame("", index=x.index, columns=x.columns)
        s.loc[:, :] = "background-color: var(--mv-true-green); font-weight: 700;"
        return s
    st.dataframe(top10.style.apply(style_green, axis=None), use_container_width=True, height=min(600, 80+len(top10)*35))

# --------------------------- All pairs (paged)
st.subheader("📑 All pairs")
ps = st.session_state["page_size"]
pi = st.session_state["page_idx"]
start = pi*ps; end = start+ps
page_df = df.iloc[start:end].copy()
page_green = green_mask.iloc[start:end].reset_index(drop=True)
page_yellow= yellow_mask.iloc[start:end].reset_index(drop=True)

def style_full(x: pd.DataFrame):
    s = pd.DataFrame("", index=x.index, columns=x.columns)
    for i in range(len(x)):
        if page_green.iloc[i]:
            s.iloc[i,:] = "background-color: var(--mv-true-green); font-weight: 700;"
        elif page_yellow.iloc[i]:
            s.iloc[i,:] = "background-color: var(--mv-true-yellow); font-weight: 700;"
    # style HTML in Gates column
    return s

# show Gates HTML
page_df_display = page_df.copy()
page_df_display["Gates"] = page_df_display["Gates"].astype(str)
st.dataframe(page_df_display.style.apply(style_full, axis=None).format(precision=6), use_container_width=True, height=min(800, 100+len(page_df)*35))

st.caption(f"Discovery: found {len(universe)} exchange pairs • merged set {len(df)}")

# Reset collapse flag
st.session_state["collapse_all_now"] = False

