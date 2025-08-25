# app.py — Crypto Tracker by hioncrypto
# • Hioncrypto starter toggle sits directly ABOVE "Gates needed to turn green (K)"
# • Email/Webhook alerts kept (Top‑10 entrants)
# • Stronger blue sidebar styling
# • Starter preset is loose enough so rows appear immediately (then tighten)
# • Micro+Macro Trend Break window; chips; Top‑10; paging; no "Apply" buttons

import json, time, datetime as dt, ssl, smtplib
from typing import List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
import requests
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ------------- Page + CSS (prominent blue)
st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")
st.markdown("""
<style>
:root{
  --mv-blue:#0b66ff;           /* stronger blue */
  --mv-blue-2:#084cd3;
  --mv-true-yellow: rgba(255,255,0,.70);
  --mv-true-green: rgba(0,200,0,.22);
  --mv-bg-blue: #e9f1ff;
}
/* Sidebar buttons/links/chips get blue */
section[data-testid="stSidebar"] button, section[data-testid="stSidebar"] .stButton button{
  background: var(--mv-blue)!important; color:#fff!important; border:0!important; border-radius:10px!important;
  box-shadow: 0 1px 0 rgba(0,0,0,.2);
}
section[data-testid="stSidebar"] .stCheckbox, section[data-testid="stSidebar"] label, 
section[data-testid="stSidebar"] .stRadio { color: var(--mv-blue-2)!important; font-weight: 600; }

/* Sidebar expanders look like tabs with blue bars */
section[data-testid="stSidebar"] details>summary{
  background: linear-gradient(90deg, var(--mv-blue), #3b82f6); 
  color:#fff !important; padding:10px 12px; border-radius:10px; margin:6px 0;
  font-weight:800; letter-spacing:.2px; outline: none !important;
}
section[data-testid="stSidebar"] details[open]>summary{
  background: linear-gradient(90deg, var(--mv-blue-2), #2563eb);
}

/* Chips & row colors */
.mv-chip{display:inline-block;padding:2px 6px;margin-right:6px;border-radius:6px;font-size:.78rem;color:#111;
  background:#f1f5ff;border:1px solid #cfe0ff}
.mv-ok{background:#d8f6d8;border-color:#9be39b}
.mv-bad{background:#ffe3e3;border-color:#ffb1b1}
.mv-row-green{background: var(--mv-true-green)!important; font-weight:700;}
.mv-row-yellow{background: var(--mv-true-yellow)!important; font-weight:700;}
.mv-topline{position:sticky;top:0;z-index:5; padding:10px 8px; background:rgba(22,24,29,.85); backdrop-filter: blur(6px);}
</style>
""", unsafe_allow_html=True)

# ------------- Session defaults
def _init_state():
    ss = st.session_state
    ss.setdefault("collapse_all_now", False)
    ss.setdefault("my_pairs", set())
    ss.setdefault("use_my_pairs_only", False)
    ss.setdefault("page_size", 50)
    ss.setdefault("page_idx", 0)
    ss.setdefault("alert_seen", set())
_init_state()

# ------------- Market/exchange
EXCHANGES = ["Coinbase"]        # others later
QUOTES    = ["USD","USDC","USDT","BTC","ETH","EUR"]
TF_SEC    = {"15m":900, "1h":3600, "4h":14400, "6h":21600, "12h":43200, "1d":86400}
DEFAULT_TFS = ["15m","1h","4h","6h","12h","1d"]
CB_BASE   = "https://api.exchange.coinbase.com"

def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25)
        r.raise_for_status()
        out=[]
        for p in r.json():
            if p.get("quote_currency")==quote:
                out.append(f"{p['base_currency']}-{p['quote_currency']}")
        return sorted(set(out))        # NO CAP
    except Exception:
        return []

def fetch_candles_coinbase(pair: str, gran: int,
                           start: Optional[dt.datetime]=None,
                           end: Optional[dt.datetime]=None)->Optional[pd.DataFrame]:
    try:
        url=f"{CB_BASE}/products/{pair}/candles?granularity={gran}"
        params={}
        if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
        if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
        r=requests.get(url,params=params,timeout=30)
        if r.status_code!=200: return None
        arr=r.json()
        if not arr: return None
        df=pd.DataFrame(arr,columns=["ts","low","high","open","close","volume"])
        df["ts"]=pd.to_datetime(df["ts"],unit="s",utc=True)
        return df.sort_values("ts").reset_index(drop=True)
    except Exception:
        return None

def resample_ohlcv(df: pd.DataFrame, target_sec: int)->Optional[pd.DataFrame]:
    if df is None or df.empty: return None
    d=df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    out=d.resample(f"{target_sec}s",label="right",closed="right").agg(agg).dropna()
    return out.reset_index()

def df_for_tf(pair: str, tf: str)->Optional[pd.DataFrame]:
    sec=TF_SEC[tf]
    native = sec in {900,3600,21600,86400}
    base = fetch_candles_coinbase(pair, sec if native else 3600)
    return base if native else resample_ohlcv(base, sec)

# ------------- Indicators
def ema(s: pd.Series, span:int)->pd.Series: return s.ewm(span=span,adjust=False).mean()
def rsi(close: pd.Series, length=14)->pd.Series:
    d=close.diff()
    up=np.where(d>0,d,0.0); dn=np.where(d<0,-d,0.0)
    ru=pd.Series(up,index=close.index).ewm(alpha=1/length,adjust=False).mean()
    rd=pd.Series(dn,index=close.index).ewm(alpha=1/length,adjust=False).mean()
    rs=ru/(rd+1e-12); return 100-(100/(1+rs))
def macd_hist(close: pd.Series, fast=12, slow=26, sig=9)->pd.Series:
    m=ema(close,fast)-ema(close,slow); s=ema(m,sig); return m-s
def atr(df: pd.DataFrame, length=14)->pd.Series:
    h,l,c=df["high"],df["low"],df["close"]; pc=c.shift(1)
    tr=pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/length,adjust=False).mean()
def volume_spike_x(df: pd.DataFrame, window=20)->float:
    if len(df)<window+1: return np.nan
    return float(df["volume"].iloc[-1]/(df["volume"].rolling(window).mean().iloc[-1]+1e-12))
def roc(close: pd.Series, length=10)->pd.Series:
    return (close/close.shift(length)-1.0)*100.0
def find_pivots(close: pd.Series, span=3)->Tuple[pd.Index,pd.Index]:
    n=len(close); v=close.values; hi=[]; lo=[]
    for i in range(span,n-span):
        if v[i]>v[i-span:i].max() and v[i]>v[i+1:i+1+span].max(): hi.append(i)
        if v[i]<v[i-span:i].min() and v[i]<v[i+1:i+1+span].min(): lo.append(i)
    return pd.Index(hi), pd.Index(lo)
def trend_breakout_up(df: pd.DataFrame, span=3, within_bars=96)->bool:
    if df is None or len(df)<span*2+5: return False
    highs,_=find_pivots(df["close"],span)
    if len(highs)==0: return False
    hi=int(highs[-1]); level=float(df["close"].iloc[hi]); cross=None
    for j in range(hi+1,len(df)):
        if float(df["close"].iloc[j])>level: cross=j; break
    if cross is None: return False
    return (len(df)-1 - cross) <= within_bars

# ------------- ATH/ATL window (micro+macro)
def hist_for_window(pair: str, basis:str, amt:int)->Optional[pd.DataFrame]:
    end=dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":  gran=3600;  start=end-dt.timedelta(hours=amt)
    elif basis=="Daily": gran=86400; start=end-dt.timedelta(days=amt)
    else:                gran=86400; start=end-dt.timedelta(weeks=amt)
    out=[]; cursor=end
    while True:
        df=fetch_candles_coinbase(pair, gran, start=max(start, cursor-dt.timedelta(days=30)), end=cursor)
        if df is None or df.empty: break
        out.append(df); cursor=df["ts"].iloc[0]
        if cursor<=start: break
    if not out: return None
    hist=pd.concat(out,ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if basis=="Weekly": hist = resample_ohlcv(hist, 7*86400)
    return hist

def ath_atl_info(hist: pd.DataFrame)->Dict[str,object]:
    last=float(hist["close"].iloc[-1])
    ia=int(hist["high"].idxmax()); iz=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[ia]); atd=pd.to_datetime(hist["ts"].iloc[ia]).date().isoformat()
    atl=float(hist["low"].iloc[iz]);  ztd=pd.to_datetime(hist["ts"].iloc[iz]).date().isoformat()
    return {"From ATH %":(last/ath-1.0)*100 if ath>0 else np.nan,"ATH date":atd,"From ATL %":(last/atl-1.0)*100 if atl>0 else np.nan,"ATL date":ztd}

# ------------- Alerts
def send_email_alert(subject, body, recipient):
    try: cfg=st.secrets["smtp"]
    except Exception: return False,"SMTP not configured"
    try:
        msg=MIMEMultipart(); msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body,"plain"))
        ctx=ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port",465), context=ctx) as s:
            s.login(cfg["user"], cfg["password"]); s.sendmail(cfg["sender"], recipient, msg.as_string())
        return True,"OK"
    except Exception as e:
        return False, str(e)

def post_webhook(url, payload):
    try:
        r=requests.post(url, json=payload, timeout=10)
        return (200<=r.status_code<300), r.text
    except Exception as e:
        return False, str(e)

# ------------- Sidebar top row
with st.sidebar:
    c1,c2 = st.columns([1,1])
    if c1.button("Collapse all", use_container_width=True):
        st.session_state["collapse_all_now"]=True
    st.session_state["use_my_pairs_only"] = c2.toggle("⭐ Use My Pairs only", value=st.session_state["use_my_pairs_only"],
                                                     help="Show only the pairs you've pinned.")
    st.divider()

def expander(title, key):
    opened = not st.session_state.get("collapse_all_now", False)
    return st.sidebar.expander(title, expanded=opened)

# ------------- Reset / Utilities (optional)
with expander("Reset / Utilities","exp_utils"):
    cols = st.columns(3)
    if cols[0].button("Reset pins"):
        st.session_state["my_pairs"]=set()
    if cols[1].button("Reset paging"):
        st.session_state["page_idx"]=0
    if cols[2].button("Reset ‘Collapse all’"):
        st.session_state["collapse_all_now"]=False

# ------------- Manage My Pairs
with expander("Manage My Pairs","exp_my"):
    st.caption("Add pins or load some defaults. Toggle ⭐ at top to filter to pins.")
    pins = sorted(st.session_state["my_pairs"])
    st.write("Pinned:", ", ".join(pins) if pins else "—")
    npair = st.text_input("Add pair (e.g. SOL-USD)")
    cc = st.columns([1,1,1])
    if cc[0].button("Add"):
        if npair.strip(): st.session_state["my_pairs"].add(npair.strip().upper())
    if cc[1].button("Clear"):
        st.session_state["my_pairs"]=set()
    if cc[2].button("Load BTC/ETH/SOL"):
        st.session_state["my_pairs"].update({"BTC-USD","ETH-USD","SOL-USD"})

# ------------- Market
with expander("Market","exp_market"):
    st.caption("Discovery merges ALL products for the quote; no cap.")
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    quote    = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    default_watch = "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD"
    watchlist = st.text_area("Watchlist (comma-separated)", default_watch, height=80)

# ------------- Timeframes
with expander("Timeframes","exp_tf"):
    pick_tfs = st.multiselect("Available timeframes", list(TF_SEC.keys()), default=list(TF_SEC.keys()))
    sort_tf  = st.selectbox("Primary sort timeframe", list(TF_SEC.keys()), index=1)
    sort_desc = st.checkbox("Sort descending (largest first)", value=True)

# ------------- Gates (starter placed above K)
with expander("Gates","exp_gates"):
    gate_logic = st.radio("Gate logic", ["ALL","ANY"], index=0, horizontal=True)
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 50.0, 3.0, 0.5,
                        help="Positive‑only % change on the selected timeframe.")

    cA = st.columns(3)
    with cA[0]:
        use_vol = st.toggle("Volume spike×", value=True, help="Last vol vs 20‑SMA.")
        vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, 1.03, 0.02)
    with cA[1]:
        use_macd = st.toggle("MACD hist", value=True)
        min_mhist = st.slider("Min MACD hist", 0.0, 2.0, 0.025, 0.005)
    with cA[2]:
        use_trend = st.toggle("Trend breakout (up)", value=True)
        pivot_span = st.slider("Pivot span (bars)", 2, 10, 3, 1)
        trend_within = st.slider("Breakout within (bars)", 5, 120, 96, 1)

    cB = st.columns(3)
    with cB[0]:
        use_rsi = st.toggle("RSI", value=False)
        min_rsi = st.slider("Min RSI", 40, 90, 55, 1)
    with cB[1]:
        use_atr = st.toggle("ATR %", value=False)
        min_atr = st.slider("Min ATR %", 0.0, 10.0, 0.30, 0.05)
    with cB[2]:
        use_roc = st.toggle("ROC %", value=False)
        roc_len = st.slider("ROC length (bars)", 2, 60, 10, 1)
        min_roc = st.slider("Min ROC %", -10.0, 50.0, 0.0, 0.5)

    st.markdown("---")
    # >>> HIONCRYPTO STARTER TOGGLE — placed RIGHT ABOVE K selector <<<
    starter_on = st.toggle("Use hioncrypto (starter)", value=True,
                           help="Loose defaults so rows appear immediately. Turn OFF to fine‑tune.")
    if starter_on:
        gate_logic = "ALL"
        min_pct    = 3.0
        use_vol, vol_mult = True, 1.03
        use_macd, min_mhist = True, 0.025
        use_trend, pivot_span, trend_within = True, 3, 96
        use_rsi, min_rsi = False, 55
        use_atr, min_atr = False, 0.30
        use_roc, roc_len, min_roc = False, 10, 0.0
        st.info("Starter ON: loose gating so pairs show. Tighten later.", icon="✨")

    # K/Y threshold selectors
    k_needed = st.selectbox("Gates needed to turn green (K)", [1,2,3,4,5,6,7], index=1)
    y_needed = st.selectbox("Yellow needs ≥ Y (but < K)", [0,1,2,3,4,5,6], index=1)
    st.caption(f"Enabled now: gates counted dynamically by toggles. Green needs K={k_needed} • Yellow uses Y={y_needed}")

# ------------- Trend Break window
with expander("Trend Break window","exp_window"):
    basis = st.selectbox("Window basis", ["Hourly","Daily","Weekly"], index=1,
                         help="Hourly = micro swings, Weekly = macro extremes.")
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1)
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 90, 1)
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 12, 1)

# ------------- Display + Alerts
with expander("Display","exp_display"):
    st.session_state["page_size"] = st.slider("Rows per page", 25, 200, st.session_state["page_size"], 25)
    st.session_state["page_idx"]  = st.number_input("Page index (0‑based)", min_value=0, value=st.session_state["page_idx"], step=1)

with expander("Notifications","exp_notif"):
    alerts_on = st.checkbox("Send Email/Webhook alerts for NEW Top‑10 entrants", value=False)
    email_to  = st.text_input("Email recipient (optional)")
    hook_url  = st.text_input("Webhook URL (optional)")

# ------------- Discovery universe
if use_watch and watchlist.strip():
    universe = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    universe = coinbase_list_products(quote)

if st.session_state["use_my_pairs_only"] and st.session_state["my_pairs"]:
    universe = sorted(set(universe).intersection(st.session_state["my_pairs"]))

if not universe:
    st.warning("No pairs discovered. Try another quote or toggle starter ON.")
    st.stop()

# ------------- Build rows
rows=[]
for pid in universe:
    dft = df_for_tf(pid, sort_tf)
    if dft is None or len(dft)<30: continue
    dft = dft.tail(500).copy()

    last=float(dft["close"].iloc[-1]); first=float(dft["close"].iloc[0])
    pct = (last/first - 1.0)*100.0  # positive-only gating below

    hist = hist_for_window(pid, basis, amount)
    if hist is None or len(hist)<10:
        athp, atd, atlp, atld = np.nan,"—",np.nan,"—"
    else:
        info = ath_atl_info(hist)
        athp, atd, atlp, atld = info["From ATH %"], info["ATH date"], info["From ATL %"], info["ATL date"]

    checks=[]
    checks.append(("Δ%Change", bool(pct>0 and pct>=min_pct)))
    if use_vol:
        sp = volume_spike_x(dft, 20); checks.append(("Volume×", bool(sp>=vol_mult)))
    if use_macd:
        mh = float(macd_hist(dft["close"]).iloc[-1]); checks.append(("MACD", bool(mh>=min_mhist)))
    if use_trend:
        tb = trend_breakout_up(dft, span=pivot_span, within_bars=trend_within); checks.append(("Trend", bool(tb)))
    if use_rsi:
        rv = float(rsi(dft["close"]).iloc[-1]); checks.append(("RSI", bool(rv>=min_rsi)))
    if use_atr:
        ap = float(atr(dft).iloc[-1])/(last+1e-12)*100.0; checks.append(("ATR", bool(ap>=min_atr)))
    if use_roc:
        rc = float(roc(dft["close"], roc_len).iloc[-1]); checks.append(("ROC", bool(rc>=min_roc)))

    enabled = [name for name,_ in checks]; trues=[ok for _,ok in checks]
    cnt_true = sum(trues)
    green = (cnt_true>=k_needed) if gate_logic=="ALL" else (cnt_true>=k_needed)
    yellow = (not green) and (cnt_true>=y_needed)

    # chips
    chips_html=[]
    for name, ok in checks:
        chips_html.append(f"<span class='mv-chip {'mv-ok' if ok else 'mv-bad'}'>{name[0]}</span>")
    chips="".join(chips_html)

    rows.append({
        "Pair": pid, "Price": last, f"% Change ({sort_tf})": pct,
        "From ATH %": athp, "ATH date": atd, "From ATL %": atlp, "ATL date": atld,
        "Gates": chips, "Strong Buy": "YES" if green else ("PARTIAL" if yellow else "—"),
        "_g": green, "_y": yellow
    })

df = pd.DataFrame(rows)
if df.empty:
    st.warning("Discovery returned pairs but gating hid them. Starter is ON and very loose; if you still see nothing, try a different TF.")
    st.stop()

chg_col = f"% Change ({sort_tf})"
df = df.sort_values(chg_col, ascending=not sort_desc, na_position="last").reset_index(drop=True)
df.insert(0,"#",df.index+1)

gmask = df["_g"].copy(); ymask = df["_y"].copy()
df = df.drop(columns=["_g","_y"])

# ------------- Topline + legend
st.markdown(f"<div class='mv-topline'>Timeframe: <b>{sort_tf}</b> • Trend Break window: <b>{basis}{amount}</b></div>", unsafe_allow_html=True)
st.markdown("<div class='mv-chip mv-ok'>Δ</div> %Change &nbsp; <div class='mv-chip mv-ok'>V</div> Volume× &nbsp; <div class='mv-chip mv-ok'>R</div> ROC &nbsp; <div class='mv-chip mv-ok'>T</div> Trend &nbsp; <div class='mv-chip mv-ok'>S</div> RSI &nbsp; <div class='mv-chip mv-ok'>M</div> MACD &nbsp; <div class='mv-chip mv-ok'>A</div> ATR",
            unsafe_allow_html=True)

# ------------- Top‑10 (green only) + alerts
st.subheader("📌 Top‑10 (meets green rule)")
top10 = df[gmask].copy().sort_values(chg_col, ascending=False).head(10).reset_index(drop=True)

def _style_green(x: pd.DataFrame):
    s=pd.DataFrame("",index=x.index,columns=x.columns)
    s.loc[:,:]="background-color: var(--mv-true-green); font-weight:700;"
    return s

if top10.empty:
    st.write("—")
else:
    st.dataframe(top10.style.apply(_style_green, axis=None), use_container_width=True,
                 height=min(600, 80+len(top10)*35))

# Alerts for new Top‑10 entries
if alerts_on and not top10.empty:
    msgs=[]
    for _,r in top10.iterrows():
        key=f"{r['Pair']}|{round(float(r[chg_col]),2)}|{sort_tf}"
        if key not in st.session_state["alert_seen"]:
            st.session_state["alert_seen"].add(key)
            msgs.append(f"{r['Pair']}: {float(r[chg_col]):+.2f}% ({sort_tf})  • Strong Buy")
    if msgs:
        subject="Crypto Tracker — NEW Top‑10 entry"
        body="\n".join(msgs)
        if email_to.strip():
            ok,info=send_email_alert(subject, body, email_to.strip())
            if not ok: st.warning(f"Email failed: {info}")
        if hook_url.strip():
            ok,info=post_webhook(hook_url.strip(), {"title":subject, "lines":msgs})
            if not ok: st.warning(f"Webhook failed: {info}")

# ------------- All pairs (paged) with coloring & chips HTML
st.subheader("📑 All pairs")
ps=st.session_state["page_size"]; pi=st.session_state["page_idx"]
start=pi*ps; end=start+ps
p_df=df.iloc[start:end].copy()
p_g=gmask.iloc[start:end].reset_index(drop=True)
p_y=ymask.iloc[start:end].reset_index(drop=True)

def _style_full(x: pd.DataFrame):
    s=pd.DataFrame("",index=x.index,columns=x.columns)
    for i in range(len(x)):
        if p_g.iloc[i]: s.iloc[i,:]="background-color: var(--mv-true-green); font-weight:700;"
        elif p_y.iloc[i]: s.iloc[i,:]="background-color: var(--mv-true-yellow); font-weight:700;"
    return s

p_df["Gates"]=p_df["Gates"].astype(str)
st.dataframe(p_df.style.apply(_style_full, axis=None), use_container_width=True,
             height=min(900, 120+len(p_df)*35))
st.caption(f"Discovery: {len(universe)} pairs • showing rows {start+1}–{min(end,len(df))} of {len(df)}")

# ------------- finalize collapse state
st.session_state["collapse_all_now"]=False

