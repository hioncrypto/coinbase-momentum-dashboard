
# app.py — Crypto Tracker by hioncrypto (stable one-file build)
# - Blue sidebar theme
# - Discovery slider (10..500)
# - Chips + Strong Buy
# - Green/Yellow K-of-N gates
# - Looser defaults so rows appear

import time, json, ssl, smtplib, datetime as dt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Tuple, List

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ---------------------------- CONFIG

st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

TF_LIST = ["15m","1h","4h","6h","12h","1d"]
ALL_TFS = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}
QUOTES = ["USD","USDT","USDC","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance"]

# ---------------------------- SMALL UTILS

def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    delta = close.diff()
    up = np.where(delta>0, delta, 0.0)
    dn = np.where(delta<0, -delta, 0.0)
    roll_up = pd.Series(up, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    roll_dn = pd.Series(dn, index=close.index).ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / (roll_dn + 1e-12)
    return 100 - (100/(1+rs))

def macd_hist(close: pd.Series, fast=12, slow=26, signal=9) -> pd.Series:
    macd_line = ema(close, fast) - ema(close, slow)
    sig = ema(macd_line, signal)
    return macd_line - sig

def atr(df: pd.DataFrame, length=14) -> pd.Series:
    h,l,c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def rate_of_change(close: pd.Series, length=14) -> pd.Series:
    return (close/close.shift(length)-1)*100

def volume_spike_last_vs_sma(df: pd.DataFrame, window=20) -> float:
    if len(df) < window+1: return np.nan
    return float(df["volume"].iloc[-1] / (df["volume"].rolling(window).mean().iloc[-1] + 1e-12))

# ---------------------------- DATA

def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25)
        r.raise_for_status()
        data = r.json()
        return sorted(f"{p['base_currency']}-{p['quote_currency']}" for p in data
                      if p.get("quote_currency")==quote and p.get("trading_disabled") is False)
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25)
        r.raise_for_status()
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
    return []

def fetch_candles(exchange: str, pair_dash: str, gran_sec: int,
                  start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    try:
        if exchange=="Coinbase":
            url = f"{CB_BASE}/products/{pair_dash}/candles?granularity={gran_sec}"
            params={}
            if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
            if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
            r = requests.get(url, params=params, timeout=25)
            if r.status_code!=200: return None
            arr = r.json()
            if not arr: return None
            df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
            return df.sort_values("ts").reset_index(drop=True)
        elif exchange=="Binance":
            base, quote = pair_dash.split("-"); symbol=f"{base}{quote}"
            interval_map = {900:"15m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
            interval = interval_map.get(gran_sec)
            if not interval: return None
            params={"symbol":symbol,"interval":interval,"limit":1000}
            if start: params["startTime"]=int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
            if end:   params["endTime"]=int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
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

def resample_ohlcv(df: pd.DataFrame, target_sec: int) -> Optional[pd.DataFrame]:
    if df is None or df.empty: return None
    d=df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    out=d.resample(f"{target_sec}s", label="right", closed="right").agg(agg).dropna()
    return out.reset_index()

def df_for_tf(exchange: str, pair: str, tf: str) -> Optional[pd.DataFrame]:
    sec = ALL_TFS[tf]
    if exchange=="Coinbase":
        native = sec in {900,3600,21600,86400}
        if native: return fetch_candles(exchange, pair, sec)
        base = fetch_candles(exchange, pair, 3600)
        return resample_ohlcv(base, sec)
    elif exchange=="Binance":
        return fetch_candles(exchange, pair, sec)
    return None

@st.cache_data(ttl=4*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":
        amount = max(1, min(amount, 72)); gran=3600; start=end-dt.timedelta(hours=amount)
    elif basis=="Daily":
        amount = max(1, min(amount,365)); gran=86400; start=end-dt.timedelta(days=amount)
    else:
        amount = max(1, min(amount, 52)); gran=86400; start=end-dt.timedelta(weeks=amount)
    out=[]; step=300; cursor_end=end
    while True:
        win=dt.timedelta(seconds=step*gran)
        cursor_start=max(start, cursor_end-win)
        if (cursor_end - cursor_start).total_seconds() < gran: break
        df=fetch_candles(exchange, pair, gran, start=cursor_start, end=cursor_end)
        if df is None or df.empty: break
        out.append(df); cursor_end=df["ts"].iloc[0]
        if cursor_end<=start: break
    if not out: return None
    hist=pd.concat(out, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if basis=="Weekly": hist = resample_ohlcv(hist, 7*86400)
    return hist

def ath_atl_info(hist: pd.DataFrame) -> dict:
    last=float(hist["close"].iloc[-1])
    idx_ath=int(hist["high"].idxmax()); idx_atl=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[idx_ath]); d_ath=pd.to_datetime(hist["ts"].iloc[idx_ath]).date().isoformat()
    atl=float(hist["low"].iloc[idx_atl]);  d_atl=pd.to_datetime(hist["ts"].iloc[idx_atl]).date().isoformat()
    return {"From ATH %": (last/ath-1)*100 if ath>0 else np.nan, "ATH date": d_ath,
            "From ATL %": (last/atl-1)*100 if atl>0 else np.nan, "ATL date": d_atl}

# ---------------------------- EMAIL / WEBHOOK

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

# ---------------------------- CSS (blue sidebar + chips)

st.markdown("""
<style>
section[data-testid="stSidebar"] details > summary {
  background: #173a5e !important;
  color: #e9f2ff !important;
  border-radius: 10px; margin:6px 0; padding:8px 10px;
}
section[data-testid="stSidebar"] details[open] {
  border: 1px solid #1e4f83 !important; border-radius:10px;
}
section[data-testid="stSidebar"] button {
  background:#1e4f83 !important; color:#eef6ff !important;
  border:0 !important; border-radius:10px !important;
}
.mv-chip { display:inline-block; min-width:18px; text-align:center;
  padding:1px 6px; border-radius:8px; margin-right:4px;
  font-weight:700; font-size:0.82rem; line-height:18px; }
.mv-chip.ok   { background:#0a7d38; color:#fff; }
.mv-chip.no   { background:#6b1111; color:#fff; }
</style>
""", unsafe_allow_html=True)

# ---------------------------- SIDEBAR

st.title("Crypto Tracker by hioncrypto")

with st.sidebar.expander("Market", expanded=True):
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    quote = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    watchlist = st.text_area("Watchlist (comma-separated)",
                             "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")
    max_pairs = st.slider("Max pairs to evaluate (discovery)", 10, 500, 200, 5)

with st.sidebar.expander("Timeframes", expanded=False):
    sort_tf = st.selectbox("Primary timeframe (for % change)", TF_LIST, index=1)

with st.sidebar.expander("Gates", expanded=True):
    st.caption("Chips legend: Δ %+Change • V Volume× • R RSI • M MACD • A ATR • T Trend • C ROC")
    st.toggle("Use hioncrypto (starter)", value=True, key="hion_starter")
    logic = st.radio("Gate logic", ["ALL", "ANY"], index=0, horizontal=True)
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 50.0, 2.0, 0.1)
    # indicator toggles/thresholds (simplified)
    use_vol = st.toggle("Volume spike×", value=True);  vol_mult = st.slider("Min spike×", 1.0, 5.0, 1.05, 0.05)
    use_rsi = st.toggle("RSI", value=False);           min_rsi = st.slider("Min RSI", 40, 90, 55, 1)
    use_macd= st.toggle("MACD hist", value=True);      min_mh = st.slider("Min MACD hist", 0.0, 1.0, 0.025, 0.005)
    use_atr = st.toggle("ATR %", value=False);         min_atr = st.slider("Min ATR %", 0.0, 10.0, 0.3, 0.05)
    use_trend=st.toggle("Trend breakout (up)", True);  piv = st.slider("Pivot span", 2, 10, 4, 1); within=st.slider("Breakout within (bars)", 5, 96, 48, 1)
    use_roc = st.toggle("ROC", value=False);           roc_len = st.slider("ROC length", 5, 60, 14, 1); min_roc = st.slider("Min ROC %", -10.0, 20.0, 0.0, 0.5)

    st.divider()
    st.caption("Color rules (K-of-N)")
    K_needed = st.selectbox("Gates needed to turn green (K)", [1,2,3,4,5,6,7], index=1)
    Y_needed = st.selectbox("Yellow needs ≥ Y (but < K)", [0,1,2,3,4,5,6], index=1)
    st.session_state["k_green_needed"]=K_needed
    st.session_state["y_yellow_needed"]=Y_needed
    st.session_state["gate_min_pct"]=min_pct

with st.sidebar.expander("Indicator lengths", expanded=False):
    rsi_len = st.slider("RSI length", 5, 50, 14, 1)
    macd_fast = st.slider("MACD fast EMA", 3, 50, 12, 1)
    macd_slow = st.slider("MACD slow EMA", 5, 100, 26, 1)
    macd_sig  = st.slider("MACD signal", 3, 50, 9, 1)
    atr_len   = st.slider("ATR length", 5, 50, 14, 1)
    vol_window= st.slider("Volume SMA window", 5, 50, 20, 1)

with st.sidebar.expander("Trend Break (ATH/ATL lookback)", expanded=False):
    basis = st.selectbox("Window basis", ["Hourly","Daily","Weekly"], index=1)
    if basis=="Hourly": amount = st.slider("Hours (≤72)", 1, 72, 24, 1)
    elif basis=="Daily": amount = st.slider("Days (≤365)", 1, 365, 90, 1)
    else: amount = st.slider("Weeks (≤52)", 1, 52, 12, 1)
    st.caption("Smaller windows = local extremes (swing). Larger windows = macro extremes.")

with st.sidebar.expander("Notifications", expanded=False):
    send_now = st.checkbox("Send Email/Webhook alerts this session", value=False)
    email_to = st.text_input("Email recipient (optional)", "")
    webhook_url = st.text_input("Webhook URL (optional)", "")

with st.sidebar.expander("Auto-refresh", expanded=False):
    refresh_sec = st.slider("Refresh every (seconds)", 10, 180, 30, 5)
    st.caption("Auto-refresh is always on while the page is open.")

# ---------------------------- TABLE STYLING HELPERS

def chips_from_gates(gates: dict) -> str:
    order = [("Δ","pct"),("V","vol"),("R","rsi"),("M","macd"),("A","atr"),("T","trend"),("C","roc")]
    parts=[]
    for label,key in order:
        val = bool(gates.get(key, False))
        cls = "ok" if val else "no"
        parts.append(f'<span class="mv-chip {cls}">{label}</span>')
    return "".join(parts)

def style_rows_color(x: pd.DataFrame) -> pd.DataFrame:
    styles = pd.DataFrame("", index=x.index, columns=x.columns)
    if "Strong Buy" in x.columns:
        green_mask = x["Strong Buy"].astype(str).str.upper().eq("YES")
        styles.loc[green_mask,:] = "background-color: rgba(0,180,0,0.22); font-weight:600;"
    if "__partial__" in x.columns:
        ymask = x["__partial__"].fillna(False).astype(bool)
        if "Strong Buy" in x.columns:
            ymask = ymask & ~x["Strong Buy"].astype(str).str.upper().eq("YES")
        styles.loc[ymask,:] = "background-color: rgba(255,235,0,0.45); font-weight:600;"
    return styles

# ---------------------------- DISCOVERY

big_label = f"Timeframe: {sort_tf}"
st.markdown(f"**{big_label}**  \nLegend: Δ %Change • V Volume× • R RSI • M MACD • A ATR • T Trend • C ROC")

# discover / watchlist
if use_watch and watchlist.strip():
    pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs = list_products(exchange, quote)
pairs = [p for p in pairs if p.endswith(f"-{quote}")]
pairs = pairs[:max_pairs]

rows=[]
alerts=[]
for pid in pairs:
    dft = df_for_tf(exchange, pid, sort_tf)
    if dft is None or len(dft)<30:
        continue
    dft = dft.tail(400).copy()
    last = float(dft["close"].iloc[-1])
    first= float(dft["close"].iloc[0])
    pct = (last/first - 1.0)*100.0

    # indicators (last value)
    rsiv = float(rsi(dft["close"], rsi_len).iloc[-1])
    mhv  = float(macd_hist(dft["close"], macd_fast, macd_slow, macd_sig).iloc[-1])
    atrp = float(atr(dft, atr_len).iloc[-1] / (dft["close"].iloc[-1] + 1e-12) * 100.0)
    volx = float(volume_spike_last_vs_sma(dft, vol_window))
    rocv = float(rate_of_change(dft["close"], roc_len).iloc[-1])

    # simple trend breakout: last close > max of previous "pivot span" highs within window
    trend_up=False
    if len(dft) > piv*2+5:
        highs = dft["close"].rolling(piv).max().shift(1)
        last_high = float(highs.iloc[-1]) if not np.isnan(highs.iloc[-1]) else None
        if last_high: trend_up = (last > last_high)

    g = {
        "pct":  pct>=min_pct and pct>0,
        "vol":  (volx>=vol_mult) if use_vol else True,
        "rsi":  (rsiv>=min_rsi) if use_rsi else True,
        "macd": (mhv>=min_mh)  if use_macd else True,
        "atr":  (atrp>=min_atr) if use_atr else True,
        "trend": trend_up if use_trend else True,
        "roc":  (rocv>=min_roc) if use_roc else True
    }

    # K-of-N logic
    enabled_keys = [k for k in g.keys()]  # each gate currently contributes
    true_count = sum(bool(g[k]) for k in enabled_keys)
    green = (true_count >= K_needed)
    yellow= (true_count >= Y_needed) and (true_count < K_needed)

    # ATH/ATL
    hist = get_hist(exchange, pid, basis, amount)
    if hist is None or len(hist)<10:
        athp, athd, atlp, atld = (np.nan, "—", np.nan, "—")
    else:
        info = ath_atl_info(hist)
        athp, athd, atlp, atld = info["From ATH %"], info["ATH date"], info["From ATL %"], info["ATL date"]

    rows.append({
        "Pair": pid,
        "Price": last,
        f"% Change ({sort_tf})": pct,
        "From ATH %": athp, "ATH date": athd,
        "From ATL %": atlp, "ATL date": atld,
        "Gates": chips_from_gates(g),
        "Strong Buy": "YES" if green else "—",
        "__partial__": yellow
    })

df_all = pd.DataFrame(rows)

if df_all.empty:
    st.info("No rows yet. Try lowering Min +% change, reducing K, or increasing Max pairs.")
else:
    chg_col = f"% Change ({sort_tf})"
    df_all["__green__"] = df_all["Strong Buy"].eq("YES")
    df_sorted = df_all.sort_values(["__green__", chg_col], ascending=[False, False]).reset_index(drop=True)
    df_sorted.insert(0, "#", df_sorted.index+1)
    show_cols = ["#","Pair","Price",chg_col,"From ATH %","ATH date","From ATL %","ATL date","Gates","Strong Buy","__partial__"]

    st.subheader("📌 Top-10 (meets green rule)")
    top10 = df_sorted[df_sorted["Strong Buy"].eq("YES")].head(10).reset_index(drop=True)
    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, loosen gates.")
    else:
        st.dataframe(
            top10[show_cols]
                .style.hide(axis="columns", subset=["__partial__"])
                .apply(style_rows_color, axis=None)
                .format(precision=6, na_rep="—")
                .format({"Gates": lambda s: s}, na_rep="—", escape="html"),
            use_container_width=True
        )

    st.subheader("📑 Discover")
    st.dataframe(
        df_sorted[show_cols]
            .style.hide(axis="columns", subset=["__partial__"])
            .apply(style_rows_color, axis=None)
            .format(precision=6, na_rep="—")
            .format({"Gates": lambda s: s}, na_rep="—", escape="html"),
        use_container_width=True
    )

# ---------------------------- Alerts (optional)
if send_now and not df_all.empty:
    lines = []
    for _, r in df_sorted[df_sorted["Strong Buy"].eq("YES")].head(10).iterrows():
        lines.append(f"{r['Pair']}: {r[chg_col]:+.2f}% ({sort_tf})")
    if lines:
        subject = f"[{exchange}] Top-10 Crypto Tracker"
        body = "\n".join(lines)
        if email_to.strip():
            ok, info = send_email_alert(subject, body, email_to.strip())
            if ok: st.success("Email sent")
            else:  st.warning(info)
        if webhook_url.strip():
            ok, info = post_webhook(webhook_url.strip(), {"title": subject, "lines": lines})
            if ok: st.success("Webhook sent")
            else:  st.warning(f"Webhook error: {info}")

# ---------------------------- Auto-refresh
if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = time.time()
remaining = refresh_sec - (time.time() - st.session_state["last_refresh"])
if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {refresh_sec}s (next in {int(remaining)}s)")

