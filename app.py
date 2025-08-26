# app.py — Crypto Tracker by hioncrypto (single-file, discovery + UI fixes)
# - Blue (soft) sidebar styling (robust selectors)
# - Sticky "Collapse all menu tabs" (actually collapses all)
# - "Max pairs to evaluate (discovery)" slider (50..500)
# - Looser defaults so pairs show immediately; tighten later
# - Top-10 (greens only) + Discover (greens first, then %chg)
# - Gate chips (Δ %chg, V volume×, M MACD, R RSI)
# - Email/Webhook alerts for new Top-10 entrants (opt-in)
# - Auto-refresh always on; no apply buttons

import time, ssl
from typing import List, Optional
import numpy as np
import pandas as pd
import requests
import streamlit as st
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib

# -------------------------- Page / Theme --------------------------
st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")

st.markdown("""
<style>
:root { --hion-blue: #3B82F6; --hion-blue-soft: rgba(59,130,246,0.12); --hion-blue-border: rgba(59,130,246,0.25); }

/* Sticky strip at top of sidebar */
section[data-testid="stSidebar"] > div:first-child {
  position: sticky; top: 0; z-index: 999;
  background: linear-gradient(180deg, rgba(13,17,23,0.98) 75%, rgba(13,17,23,0));
  padding-bottom: 6px; margin-bottom: 8px; border-bottom: 1px solid var(--hion-blue-border);
}

/* Buttons (sidebar + general) */
section[data-testid="stSidebar"] button, .stButton>button {
  background: var(--hion-blue) !important; color: #ffffff !important; border: 0 !important;
  border-radius: 10px !important; font-weight: 600 !important;
}

/* Inputs focus ring */
section[data-testid="stSidebar"] .stSelectbox > div > div,
section[data-testid="stSidebar"] .stTextArea > div > div,
section[data-testid="stSidebar"] .stTextInput > div > div,
section[data-testid="stSidebar"] .stSlider > div > div,
section[data-testid="stSidebar"] .stNumberInput > div > div {
  border-color: rgba(59,130,246,0.65) !important;
}

/* Expander headers (robust selectors across Streamlit versions) */
section[data-testid="stSidebar"] details > summary,
section[data-testid="stSidebar"] [data-testid="stExpander"] summary,
section[data-testid="stSidebar"] div[role="button"][aria-expanded] {
  background: var(--hion-blue-soft) !important;
  border: 1px solid var(--hion-blue-border) !important;
  color: #dbeafe !important;
  border-radius: 10px;
  margin: 6px 0 !important;
}

/* Table row highlights */
.row-green { background: rgba(0,255,0,0.22) !important; font-weight: 600; }
.row-yellow{ background: rgba(255,255,0,0.60) !important; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

st.title("Crypto Tracker by hioncrypto")

# -------------------------- Constants / Helpers --------------------------
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
TF_SEC  = {"15m":900, "1h":3600, "4h":14400, "6h":21600, "12h":43200, "1d":86400}
EXCHANGES = ["Coinbase","Binance"]
QUOTES    = ["USD","USDC","USDT","BTC","ETH","EUR"]

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0.0)
    dn = (-d).clip(lower=0.0)
    rs = up.ewm(alpha=1/length, adjust=False).mean() / (dn.ewm(alpha=1/length, adjust=False).mean() + 1e-12)
    return 100 - (100/(1+rs))

def macd_hist(close: pd.Series, fast=12, slow=26, sig=9) -> pd.Series:
    macd_line = ema(close, fast) - ema(close, slow)
    return macd_line - ema(macd_line, sig)

def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25)
        r.raise_for_status(); data = r.json()
        return sorted(f"{p['base_currency']}-{p['quote_currency']}"
                      for p in data if p.get("quote_currency")==quote)
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25)
        r.raise_for_status()
        out=[]
        for s in r.json().get("symbols", []):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote:
                out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    return coinbase_list_products(quote) if exchange=="Coinbase" else binance_list_products(quote)

def fetch_candles(exchange: str, pair: str, gran_sec: int, limit: int=300) -> Optional[pd.DataFrame]:
    """Return sorted OHLCV with columns: ts, open, high, low, close, volume"""
    try:
        if exchange=="Coinbase":
            native_ok = gran_sec in {60,300,900,3600,21600,86400}
            g = gran_sec if native_ok else 3600
            r = requests.get(f"{CB_BASE}/products/{pair}/candles?granularity={g}", timeout=25)
            if r.status_code!=200: return None
            arr = r.json()
            if not arr: return None
            df = pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="s", utc=True)
            df = df.sort_values("ts").tail(limit).reset_index(drop=True)
            if native_ok:
                return df[["ts","open","high","low","close","volume"]]
            # resample to target
            d = df.set_index("ts")
            agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
            out = d.resample(f"{gran_sec}s", label="right", closed="right").agg(agg).dropna()
            return out.reset_index()

        # Binance
        int_map = {900:"15m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
        interval = int_map.get(gran_sec, "1h")
        base, quote = pair.split("-"); symbol = base+quote
        r = requests.get(f"{BN_BASE}/api/v3/klines",
                         params={"symbol":symbol,"interval":interval,"limit":min(limit,1000)}, timeout=25)
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

def send_email_alert(subject, body, recipient):
    try:
        cfg = st.secrets["smtp"]
    except Exception:
        return False, "SMTP not configured in st.secrets"
    try:
        msg = MIMEMultipart()
        msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body, "plain"))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port",465), context=ctx) as s:
            s.login(cfg["user"], cfg["password"]); s.sendmail(cfg["sender"], recipient, msg.as_string())
        return True, "Email sent"
    except Exception as e:
        return False, f"Email error: {e}"

def post_webhook(url, payload):
    try:
        r = requests.post(url, json=payload, timeout=10)
        return (200<=r.status_code<300), r.text
    except Exception as e:
        return False, str(e)

# -------------------------- Sidebar (sticky collapse + My Pairs) --------------------------
if "collapse_now" not in st.session_state:
    st.session_state.collapse_now = False
c1, c2 = st.sidebar.columns([0.65, 0.35])
with c1:
    if st.button("Collapse all menu tabs", use_container_width=True):
        st.session_state.collapse_now = True
with c2:
    use_my_pairs = st.toggle("My Pairs", value=False, help="Only show your preferred pairs.")

def exp(title, key):
    expanded = not st.session_state.get("collapse_now", False)
    return st.sidebar.expander(title, expanded=expanded)

with exp("My Pairs (user list)", "exp_mypairs"):
    my_pairs_text = st.text_area("Your pairs (comma-separated, e.g. BTC-USD, ETH-USD)", "")
    my_pairs = [p.strip().upper() for p in my_pairs_text.split(",") if p.strip()]

with exp("Market", "exp_market"):
    exchange = st.selectbox("Exchange", EXCHANGES, index=0)
    quote    = st.selectbox("Quote currency", QUOTES, index=0)
    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False)
    watchlist = st.text_area("Watchlist (comma-separated)",
                             "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")
    # ✅ Slider restored (50..500)
    max_pairs = st.slider("Max pairs to evaluate (discovery)", 50, 500, 300, 10)

with exp("Timeframes", "exp_tf"):
    tf = st.selectbox("Primary timeframe (for % change)", TF_LIST, index=1)  # 1h default

with exp("Gates", "exp_gates"):
    # Very loose defaults so rows appear; you can tighten later
    use_hion = st.toggle("Use hioncrypto (starter)", value=True,
                         help="Loose defaults to ensure results on first load.")
    gate_logic = st.radio("Gate logic", ["ALL","ANY"], index=1, horizontal=True)  # ANY by default
    min_pct = st.slider("Min +% change (Sort TF)", 0.0, 50.0, 0.2 if use_hion else 2.0, 0.1,
                        help="Positive only; rows must meet/exceed this gain for selected TF.")

    c1,c2,c3 = st.columns(3)
    with c1:
        use_vol = st.toggle("Volume spike×", True)
        vol_win = st.slider("Spike window", 5, 50, 20, 1)
        vol_mult= st.slider("Min spike ×", 1.0, 5.0, 1.02 if use_hion else 1.20, 0.02)
    with c2:
        use_macd = st.toggle("MACD hist", True)
        min_mh   = st.slider("Min MACD hist", 0.0, 1.0, 0.01 if use_hion else 0.025, 0.005)
    with c3:
        use_rsi = st.toggle("RSI", False)
        min_rsi = st.slider("Min RSI", 40, 90, 55, 1)

    st.markdown("---")
    k_need = st.selectbox("Gates needed to turn green (K)", [1,2,3,4,5,6,7], index=0 if use_hion else 1)
    y_need = st.selectbox("Yellow needs ≥ Y (but < K)", [0,1,2,3,4,5,6], index=0)
    st.caption("Gate chips in table: **Δ** %Change • **V** Volume× • **M** MACD • **R** RSI")

with exp("Notifications", "exp_notif"):
    send_session_alerts = st.checkbox("Send Email/Webhook alerts this session", value=False)
    email_to = st.text_input("Email recipient (optional)", "")
    webhook_url = st.text_input("Webhook URL (optional)", "")

with exp("Auto-refresh", "exp_refresh"):
    refresh_sec = st.slider("Refresh every (seconds)", 10, 180, 45, 5)
    st.caption("Auto-refresh is always on while this page is open.")

# reset collapse flag after laying out the expanders
st.session_state.collapse_now = False

# -------------------------- Build Universe --------------------------
if use_my_pairs and my_pairs:
    pairs = my_pairs
else:
    if use_watch and watchlist.strip():
        pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
    else:
        pairs = list_products(exchange, quote)
        # Honor the discovery cap only when discovering (not when using watchlist/My Pairs)
        pairs = pairs[:max_pairs]

# -------------------------- Compute rows --------------------------
def compute_row(pid: str):
    sec = TF_SEC[tf]
    d = fetch_candles(exchange, pid, sec, limit=300)
    if d is None or len(d) < 30:
        return None

    last = float(d["close"].iloc[-1]); first = float(d["close"].iloc[0])
    chg = (last/first - 1.0) * 100.0

    checks = []
    chips  = []

    # Δ (positive % change gate)
    ok_pct = chg >= min_pct
    checks.append(ok_pct); chips.append("Δ" if ok_pct else "Δ×")

    # Volume spike×
    if use_vol:
        if len(d) >= vol_win+1:
            ma = d["volume"].rolling(vol_win).mean().iloc[-2] + 1e-12
            spike = d["volume"].iloc[-1] / ma
            ok = spike >= vol_mult
        else:
            ok = False
        checks.append(ok); chips.append("V" if ok else "V×")

    # MACD hist
    if use_macd:
        mh = float(macd_hist(d["close"], 12, 26, 9).iloc[-1])
        ok = mh >= min_mh
        checks.append(ok); chips.append("M" if ok else "M×")

    # RSI
    if use_rsi:
        rv = float(rsi(d["close"], 14).iloc[-1])
        ok = rv >= min_rsi
        checks.append(ok); chips.append("R" if ok else "R×")

    # Gate logic (ALL vs ANY) influences the pass definition if you later want to extend,
    # but for color scoring we simply count enabled-gate truths vs K/Y thresholds.
    enabled_checks = []
    if True:  # Δ always on
        enabled_checks.append(checks[0])
    if use_vol:  enabled_checks.append(checks[1])
    if use_macd: enabled_checks.append(checks[2])
    if use_rsi:  enabled_checks.append(checks[3])

    score = sum(1 for c in enabled_checks if c)
    green = (score >= k_need)
    yellow = (not green) and (score >= y_need)

    return {
        "Pair": pid,
        "Price": last,
        f"% Change ({tf})": chg,
        "Gates": " ".join(chips),
        "_green": green,
        "_yellow": yellow
    }

rows=[]
for pid in pairs:
    r = compute_row(pid)
    if r: rows.append(r)

df = pd.DataFrame(rows)

st.caption(f"Discovery status — Universe fetched: {len(pairs)} • Rows computed: {len(df)} • "
           f"Exchange: {exchange} • Quote: {quote} • TF: {tf}")

if df.empty:
    st.warning("No rows to show. Try: lower **Min +% change**, reduce **K**, or toggle off a gate (Volume/MACD/RSI).")
else:
    chg_col = f"% Change ({tf})"

    # ---------------------- Top-10 (greens only) ----------------------
    st.subheader("📌 Top-10 (meets green rule)")
    top10 = df[df["_green"]].sort_values(chg_col, ascending=False).head(10).reset_index(drop=True)
    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, loosen gates (lower **Min +% change** or reduce **K**).")
    else:
        def style_green(x):
            return pd.DataFrame("background-color: rgba(0,255,0,0.22); font-weight: 600;",
                                index=x.index, columns=x.columns)
        st.dataframe(top10[["Pair","Price",chg_col,"Gates"]].style.apply(style_green, axis=None),
                     use_container_width=True)

        # Alerts when new pairs enter Top-10 (session only)
        with st.sidebar:
            if send_session_alerts:
                if "alert_seen" not in st.session_state: st.session_state.alert_seen=set()
                new_msgs=[]
                for _, r in top10.iterrows():
                    key=f"{r['Pair']}|{tf}|{round(float(r[chg_col]),2)}"
                    if key not in st.session_state.alert_seen:
                        st.session_state.alert_seen.add(key)
                        new_msgs.append(f"{r['Pair']}: {float(r[chg_col]):+.2f}% ({tf})  Gates: {r['Gates']}")
                if new_msgs:
                    subject = f"[{exchange}] Top-10 — Crypto Tracker"
                    body    = "\n".join(new_msgs)
                    if email_to.strip():
                        ok, info = send_email_alert(subject, body, email_to.strip())
                        if not ok: st.warning(info)
                    if webhook_url.strip():
                        ok, info = post_webhook(webhook_url.strip(), {"title": subject, "lines": new_msgs})
                        if not ok: st.warning(f"Webhook error: {info}")

    # ---------------------- Discover (all rows) ----------------------
    st.subheader("📑 Discover")
    df_sorted = df.sort_values(["_green", chg_col], ascending=[False, False]).reset_index(drop=True)
    df_sorted.insert(0, "#", df_sorted.index+1)
    show_cols = ["#","Pair","Price",chg_col,"Gates"]

    def style_rows(x):
        s = pd.DataFrame("", index=x.index, columns=x.columns)
        for i in range(len(x)):
            if x.loc[i, "_green"]:    s.loc[i,:] = "background-color: rgba(0,255,0,0.22); font-weight: 600;"
            elif x.loc[i, "_yellow"]: s.loc[i,:] = "background-color: rgba(255,255,0,0.60); font-weight: 600;"
        return s

    st.dataframe(df_sorted[show_cols].style.apply(style_rows, axis=None), use_container_width=True)

# -------------------------- Auto-refresh (always on) --------------------------
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()
remaining = refresh_sec - (time.time() - st.session_state.last_refresh)
if remaining <= 0:
    st.session_state.last_refresh = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {refresh_sec}s (next in {int(remaining)}s)")
