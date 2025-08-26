# app.py — Crypto Tracker by hioncrypto (REST default, WS optional)
# One-file build:
# - Exchanges: Coinbase, Binance (live) • Kraken/KuCoin/OKX/Bybit/Bitfinex/Gate.io (coming soon → fallback to Coinbase)
# - Discovery + Watchlist + My Pairs
# - Max pairs slider (10..500) with live "discovered count"
# - Timeframes: 15m,1h,4h,6h,12h,1d
# - Gates (7): Δ %Change, Volume×, ROC, Trend, RSI, MACD hist, ATR%
# - K-of-N (green), Y partial (yellow). Strong Buy column.
# - Chips per row (Δ, V, R, T, S, M, A) — R=ROC, S=RSI
# - Presets: Aggressive/Balanced/Conservative + custom save/delete; hioncrypto starter toggle (default OFF)
# - Tips under controls for novices
# - Top-10 (green) and Discover (all). Sort by %Change(desc) by default; users can re-sort via table UI.
# - Email/Webhook alerts when a pair enters Top-10
# - Blue (soft) sidebar + sticky "Collapse all"
# - Selections apply immediately and persist in session; optional “Save as my defaults” exports to JSON
# - REST-only by default; optional Mode: “WebSocket + REST (hybrid)” (safe fallback to REST if WS not available)

import time, json, ssl, smtplib, datetime as dt
from typing import Optional, List, Dict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import numpy as np
import pandas as pd
import requests
import streamlit as st

# -------------------- Page / Theme --------------------
st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")

st.markdown("""
<style>
:root { --hion-blue: #2962CC; --hion-blue-soft: rgba(41,98,204,0.12); --hion-blue-border: rgba(41,98,204,0.35); }

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

/* Inputs focus ring (sidebar) */
section[data-testid="stSidebar"] .stSelectbox > div > div,
section[data-testid="stSidebar"] .stTextArea > div > div,
section[data-testid="stSidebar"] .stTextInput > div > div,
section[data-testid="stSidebar"] .stSlider > div > div,
section[data-testid="stSidebar"] .stNumberInput > div > div,
section[data-testid="stSidebar"] .stMultiSelect > div > div {
  border-color: rgba(41,98,204,0.65) !important;
}

/* Expander headers (robust across Streamlit versions) */
section[data-testid="stSidebar"] details > summary,
section[data-testid="stSidebar"] [data-testid="stExpander"] summary,
section[data-testid="stSidebar"] div[role="button"][aria-expanded] {
  background: var(--hion-blue-soft) !important;
  border: 1px solid var(--hion-blue-border) !important;
  color: #dbeafe !important;
  border-radius: 10px;
  margin: 6px 0 !important;
}

/* Chips in table */
.mv-chip {
  display:inline-block; min-width:18px; text-align:center;
  padding:1px 6px; border-radius:8px; margin-right:4px;
  font-weight:700; font-size:0.82rem; line-height:18px;
}
.mv-chip.ok { background:#0a7d38; color:#fff; }
.mv-chip.no { background:#6b1111; color:#fff; }

/* Row highlights */
.row-green { background: rgba(0,255,0,0.22) !important; font-weight: 600; }
.row-yellow{ background: rgba(255,255,0,0.60) !important; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

st.title("Crypto Tracker by hioncrypto")

# -------------------- Globals --------------------
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
TF_SEC  = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}

EX_LIVE = ["Coinbase","Binance"]
EX_SOON = ["Kraken (coming soon)","KuCoin (coming soon)","OKX (coming soon)",
           "Bybit (coming soon)","Bitfinex (coming soon)","Gate.io (coming soon)"]
EX_ALL  = EX_LIVE + EX_SOON

QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]

# --- optional WS
WS_AVAILABLE = True
try:
    import websocket  # noqa
except Exception:
    WS_AVAILABLE = False

# -------------------- Utils --------------------
def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    delta = close.diff()
    up = pd.Series(np.where(delta>0, delta, 0.0), index=close.index)
    dn = pd.Series(np.where(delta<0, -delta, 0.0), index=close.index)
    rs = up.ewm(alpha=1/length, adjust=False).mean() / (dn.ewm(alpha=1/length, adjust=False).mean() + 1e-12)
    return 100 - (100/(1+rs))

def macd_hist(close: pd.Series, fast=12, slow=26, sig=9) -> pd.Series:
    macd_line = ema(close, fast) - ema(close, slow)
    return macd_line - ema(macd_line, sig)

def atr(df: pd.DataFrame, length=14) -> pd.Series:
    h,l,c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h-l), (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def roc(close: pd.Series, length=14) -> pd.Series:
    return (close/close.shift(length) - 1.0) * 100.0

def volume_spike(df: pd.DataFrame, window=20) -> float:
    if len(df) < window+1:
        return np.nan
    return float(df["volume"].iloc[-1] / (df["volume"].rolling(window).mean().iloc[-1] + 1e-12))

# -------------------- Data fetch --------------------
def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25)
        r.raise_for_status(); data = r.json()
        out=[]
        for p in data:
            if p.get("quote_currency")==quote and p.get("trading_disabled") is False:
                out.append(f"{p['base_currency']}-{p['quote_currency']}")
        return sorted(list(set(out)))
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
        return sorted(list(set(out)))
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange=="Coinbase": return coinbase_list_products(quote)
    if exchange=="Binance":  return binance_list_products(quote)
    # coming soon → fallback
    return coinbase_list_products(quote)

def fetch_candles(exchange: str, pair: str, gran_sec: int) -> Optional[pd.DataFrame]:
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
            df = df.sort_values("ts").reset_index(drop=True)
            if native_ok:
                return df[["ts","open","high","low","close","volume"]]
            # resample to target
            d = df.set_index("ts")
            agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
            out = d.resample(f"{gran_sec}s", label="right", closed="right").agg(agg).dropna()
            return out.reset_index()

        elif exchange=="Binance":
            base, quote = pair.split("-"); symbol = f"{base}{quote}"
            int_map = {900:"15m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
            interval = int_map.get(gran_sec, "1h")
            r = requests.get(f"{BN_BASE}/api/v3/klines",
                             params={"symbol":symbol,"interval":interval,"limit":1000}, timeout=25)
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

@st.cache_data(ttl=4*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly": gran=3600; start=end-dt.timedelta(hours=max(1,min(amount,72)))
    elif basis=="Daily": gran=86400; start=end-dt.timedelta(days=max(1,min(amount,365)))
    else: gran=86400; start=end-dt.timedelta(weeks=max(1,min(amount,52)))
    out=[]; step=300; cursor_end=end
    while True:
        win=dt.timedelta(seconds=step*gran)
        cursor_start=max(start, cursor_end-win)
        if (cursor_end - cursor_start).total_seconds() < gran: break
        df=fetch_candles(exchange, pair, gran)
        if df is None or df.empty: break
        df=df[(df["ts"]>=cursor_start)&(df["ts"]<cursor_end)]
        if df.empty: break
        out.append(df); cursor_end=df["ts"].iloc[0]
        if cursor_end<=start: break
    if not out: return None
    hist=pd.concat(out, ignore_index=True).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    if basis=="Weekly":
        d=hist.set_index("ts"); agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
        hist = d.resample("7D", label="right", closed="right").agg(agg).dropna().reset_index()
    return hist

def ath_atl_info(hist: pd.DataFrame) -> Dict[str,object]:
    last=float(hist["close"].iloc[-1])
    i_ath=int(hist["high"].idxmax()); i_atl=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[i_ath]); d_ath=pd.to_datetime(hist["ts"].iloc[i_ath]).date().isoformat()
    atl=float(hist["low"].iloc[i_atl]);  d_atl=pd.to_datetime(hist["ts"].iloc[i_atl]).date().isoformat()
    return {"From ATH %": (last/ath-1)*100 if ath>0 else np.nan, "ATH date": d_ath,
            "From ATL %": (last/atl-1)*100 if atl>0 else np.nan, "ATL date": d_atl}

# -------------------- Alerts --------------------
def send_email_alert(subject, body, recipient):
    try: cfg=st.secrets["smtp"]
    except Exception: return False, "SMTP not configured in st.secrets"
    try:
        msg=MIMEMultipart(); msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body,"plain"))
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

# -------------------- Session init --------------------
if "collapse_now" not in st.session_state: st.session_state.collapse_now = False
if "alert_seen"   not in st.session_state: st.session_state.alert_seen   = set()

def exp(title, key, default_open=True):
    opened = (not st.session_state.get("collapse_now", False)) and default_open
    return st.sidebar.expander(title, expanded=opened)

# -------------------- Top sticky controls --------------------
c1, c2 = st.sidebar.columns([0.62,0.38])
with c1:
    if st.button("Collapse all menu tabs", use_container_width=True):
        st.session_state.collapse_now = True
with c2:
    use_my_pairs = st.toggle("My Pairs", value=False, help="Only show your saved pairs.")

with exp("My Pairs (user list)", "exp_mypairs", default_open=False):
    my_pairs_text = st.text_area("Your pairs (comma-separated, e.g. BTC-USD, ETH-USD)", "")
    my_pairs = [p.strip().upper() for p in my_pairs_text.split(",") if p.strip()]
    st.caption("Tip: Toggle “My Pairs” at the top to filter the tables to only these.")

# -------------------- Market --------------------
with exp("Market", "exp_market", default_open=True):
    ex_choice = st.selectbox("Exchange", EX_ALL, index=0,
                             help="Live: Coinbase/Binance. Others coming soon (fallback to Coinbase).")
    if ex_choice in EX_SOON:
        st.info("This exchange is coming soon. Using Coinbase data for now.")
        exchange = "Coinbase"
    else:
        exchange = ex_choice

    quote = st.selectbox("Quote currency", QUOTES, index=0,
                         help="Pairs will end with this quote (e.g., BTC-USD).")

    use_watch = st.checkbox("Use watchlist only (ignore discovery)", value=False,
                            help="Unchecked = discover ALL pairs + include any watchlist pairs not discovered yet.")
    watchlist = st.text_area("Watchlist (comma-separated)",
                             "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")

    # Max pairs + live discovered count
    mc1, mc2 = st.columns([0.72,0.28])
    with mc1:
        max_pairs = st.slider("Max pairs to evaluate (discovery)", 10, 500, 250, 10)
    with mc2:
        # Placeholder updated after discovery below
        discovered_placeholder = st.markdown("**Found:** —")

# -------------------- Timeframes --------------------
with exp("Timeframes", "exp_tf", default_open=False):
    tf = st.selectbox("Primary timeframe (for % change)", TF_LIST, index=1,
                      help="Used for the % Change column and default sorting.")
    st.caption("You can still sort by other columns in the table header.")

# -------------------- Gates --------------------
with exp("Gates", "exp_gates", default_open=True):
    use_hion = st.toggle("hioncrypto’s preset (starter)", value=False,
                         help="Loads beginner-friendly defaults. You can still tweak anything below.")

    gate_logic = st.radio("Gate logic", ["ALL","ANY"], index=0, horizontal=True,
                          help="ALL = every enabled gate must pass. ANY = at least one gate must pass. "
                               "Coloring still uses K/Y thresholds below.")

    min_pct = st.slider("Min % change (Sort TF)", -50.0, 50.0, 2.0 if not use_hion else 1.0, 0.1,
                        help="Positive or negative allowed. Default sorting is % Change (desc).")

    g1,g2,g3 = st.columns(3)
    with g1:
        use_vol = st.toggle("Volume spike×", value=True if not use_hion else True,
                            help="Last volume vs SMA(window) multiple.")
        vol_win = st.slider("Vol SMA window", 5, 50, 20 if not use_hion else 14, 1)
        vol_mult= st.slider("Min spike ×", 1.0, 5.0, 1.15 if not use_hion else 1.05, 0.05)
    with g2:
        use_macd= st.toggle("MACD hist", value=True, help="MACD line - Signal line (histogram).")
        min_mh  = st.slider("Min MACD hist", -1.0, 1.0, 0.025, 0.005)
        use_rsi = st.toggle("RSI", value=False if not use_hion else False)
        min_rsi = st.slider("Min RSI", 40, 90, 55, 1)
    with g3:
        use_atr = st.toggle("ATR %", value=False if not use_hion else False, help="ATR/close × 100.")
        min_atr = st.slider("Min ATR %", 0.0, 10.0, 0.5 if not use_hion else 0.3, 0.1)
        use_trend= st.toggle("Trend breakout (up)", value=True, help="Close > recent pivot high.")
        piv     = st.slider("Pivot span (bars)", 2, 10, 4, 1)
        within  = st.slider("Breakout within (bars)", 5, 96, 48, 1)

    st.markdown("---")
    use_roc = st.toggle("ROC (Rate of Change)", value=False if not use_hion else True)
    roc_len = st.slider("ROC length", 5, 60, 14, 1)
    min_roc = st.slider("Min ROC %", -20.0, 20.0, 0.0 if not use_hion else -2.0, 0.5)

    st.markdown("---")
    K_needed = st.selectbox("Gates needed to turn green (K)", [1,2,3,4,5,6,7],
                            index=1 if not use_hion else 1)
    Y_needed = st.selectbox("Yellow needs ≥ Y (but < K)", [0,1,2,3,4,5,6],
                            index=1 if not use_hion else 1)
    st.caption("Green = passes ≥ K gates. Yellow = passes ≥ Y but < K.")

    # Presets (built-in)
    st.markdown("#### Presets (Aggressive / Balanced / Conservative)")
    preset_pick = st.selectbox("Apply built-in preset", ["—","Aggressive","Balanced","Conservative"], index=0)
    if preset_pick != "—":
        # Lightweight apply:
        if preset_pick=="Aggressive":
            st.session_state.update({
                "gate_logic": "ANY", "min_pct": 0.5,
            })
            min_pct = 0.5; gate_logic="ANY"; vol_mult=max(vol_mult,1.02); K_needed = 1; Y_needed = 0
            st.info("Applied Aggressive: ANY, Min %+ ≈0.5, K=1, Y=0, looser volume.")
        elif preset_pick=="Balanced":
            st.session_state.update({
                "gate_logic":"ALL","min_pct":2.0
            })
            min_pct = 2.0; gate_logic="ALL"; vol_mult=max(vol_mult,1.1); K_needed=2; Y_needed=1
            st.info("Applied Balanced: ALL, Min %+ ≈2, K=2, Y=1.")
        elif preset_pick=="Conservative":
            st.session_state.update({
                "gate_logic":"ALL","min_pct":5.0
            })
            min_pct = 5.0; gate_logic="ALL"; vol_mult=max(vol_mult,1.25); K_needed=3; Y_needed=2
            st.info("Applied Conservative: ALL, Min %+ ≈5, K=3, Y=2.")

    # Custom presets storage (session) + export/import
    st.markdown("#### Custom presets")
    if "custom_presets" not in st.session_state:
        st.session_state.custom_presets = {}
    cp = st.session_state.custom_presets

    new_name = st.text_input("Name to save current gates as preset", "")
    cols_ps = st.columns([0.4,0.3,0.3])
    with cols_ps[0]:
        if st.button("Save preset"):
            if new_name.strip():
                cp[new_name.strip()] = {
                    "gate_logic": gate_logic, "min_pct": float(min_pct),
                    "use_vol":use_vol,"vol_win":int(vol_win),"vol_mult":float(vol_mult),
                    "use_macd":use_macd,"min_mh":float(min_mh),
                    "use_rsi":use_rsi,"min_rsi":int(min_rsi),
                    "use_atr":use_atr,"min_atr":float(min_atr),
                    "use_trend":use_trend,"piv":int(piv),"within":int(within),
                    "use_roc":use_roc,"roc_len":int(roc_len),"min_roc":float(min_roc),
                    "K_needed":int(K_needed),"Y_needed":int(Y_needed),
                }
                st.success(f"Saved preset '{new_name.strip()}' (session).")
    with cols_ps[1]:
        if cp:
            to_apply = st.selectbox("Apply preset", ["—"]+list(cp.keys()))
            if to_apply!="—":
                P = cp[to_apply]
                gate_logic=P["gate_logic"]; min_pct=P["min_pct"]
                use_vol=P["use_vol"]; vol_win=P["vol_win"]; vol_mult=P["vol_mult"]
                use_macd=P["use_macd"]; min_mh=P["min_mh"]
                use_rsi=P["use_rsi"]; min_rsi=P["min_rsi"]
                use_atr=P["use_atr"]; min_atr=P["min_atr"]
                use_trend=P["use_trend"]; piv=P["piv"]; within=P["within"]
                use_roc=P["use_roc"]; roc_len=P["roc_len"]; min_roc=P["min_roc"]
                K_needed=P["K_needed"]; Y_needed=P["Y_needed"]
                st.info(f"Applied preset '{to_apply}'.")
    with cols_ps[2]:
        if cp:
            to_del = st.selectbox("Delete preset", ["—"]+list(cp.keys()))
            if to_del!="—" and st.button("Confirm delete"):
                del cp[to_del]; st.warning(f"Deleted preset '{to_del}'.")

# -------------------- Trend Break window (ATH/ATL) --------------------
with exp("Trend Break window (ATH/ATL)", "exp_tb", default_open=False):
    basis = st.selectbox("Window basis", ["Hourly","Daily","Weekly"], index=1,
                         help="Hourly = micro swings; Weekly = macro extremes.")
    if basis=="Hourly":
        amount = st.slider("Hours (≤72)", 1, 72, 24, 1)
    elif basis=="Daily":
        amount = st.slider("Days (≤365)", 1, 365, 90, 1)
    else:
        amount = st.slider("Weeks (≤52)", 1, 52, 12, 1)

# -------------------- Mode & Notifications --------------------
with exp("Mode", "exp_mode", default_open=False):
    mode = st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], index=0, horizontal=True,
                    help="REST is most stable. WebSocket adds real-time ticks where supported.")
    ws_chunk = st.slider("(WS) Subscribe chunk size", 2, 20, 5, 1,
                         help="Leave small to avoid unstable WS subscriptions.")
    if mode.startswith("WebSocket") and not WS_AVAILABLE:
        st.info("websocket-client not installed. Falling back to REST only.")

with exp("Notifications", "exp_notify", default_open=False):
    send_alerts = st.checkbox("Send Email/Webhook alerts this session", value=False)
    email_to    = st.text_input("Email recipient (optional)", "")
    webhook_url = st.text_input("Webhook URL (optional)", "")

with exp("Auto-refresh", "exp_refresh", default_open=False):
    refresh_sec = st.slider("Refresh every (seconds)", 10, 180, 30, 5)
    st.caption("No apply button needed — changes take effect immediately.")

# Reset collapse flag after drawing
st.session_state.collapse_now = False

# -------------------- Build universe --------------------
if use_my_pairs and my_pairs:
    pairs = my_pairs
else:
    if use_watch and watchlist.strip():
        pairs = [p.strip().upper() for p in watchlist.split(",") if p.strip()]
    else:
        pairs = list_products(exchange, quote)

# Filter to quote and cap discovery (but never cap My Pairs or Watchlist-only)
if not (use_my_pairs and my_pairs) and not (use_watch and watchlist.strip()):
    pairs = [p for p in pairs if p.endswith(f"-{quote}")]
    pairs = pairs[:max_pairs]

# Update discovered count near the slider
try:
    discovered_placeholder.markdown(f"**Found:** {len(pairs)}")
except Exception:
    pass

# -------------------- Table helpers --------------------
def chips_from_gates(g: Dict[str,bool]) -> str:
    # Order: Δ, V, R, T, S, M, A  (R=ROC, S=RSI)
    order = [("Δ","pct"),("V","vol"),("R","roc"),("T","trend"),("S","rsi"),("M","macd"),("A","atr")]
    parts=[]
    for lab,key in order:
        val = bool(g.get(key, False))
        cls = "ok" if val else "no"
        parts.append(f'<span class="mv-chip {cls}">{lab}</span>')
    return "".join(parts)

def style_rows(x: pd.DataFrame) -> pd.DataFrame:
    styles = pd.DataFrame("", index=x.index, columns=x.columns)
    if "Strong Buy" in x.columns:
        green_mask = x["Strong Buy"].astype(str).str.upper().eq("YES")
        styles.loc[green_mask,:] = "background-color: rgba(0,255,0,0.22); font-weight:600;"
    if "__partial__" in x.columns:
        ym = x["__partial__"].fillna(False).astype(bool)
        if "Strong Buy" in x.columns:
            ym = ym & ~x["Strong Buy"].astype(str).str.upper().eq("YES")
        styles.loc[ym,:] = "background-color: rgba(255,255,0,0.60); font-weight:600;"
    return styles

# -------------------- Compute rows --------------------
def compute_row(pid: str):
    sec = TF_SEC[tf]
    d = fetch_candles(exchange, pid, sec)
    if d is None or len(d) < 30:
        return None

    last = float(d["close"].iloc[-1]); first = float(d["close"].iloc[0])
    pct_change = (last/first - 1.0) * 100.0  # may be negative or positive

    # indicators (latest)
    mh  = float(macd_hist(d["close"]).iloc[-1])
    rsiv= float(rsi(d["close"]).iloc[-1])
    atrp= float(atr(d).iloc[-1] / (d["close"].iloc[-1] + 1e-12) * 100.0)
    volx= float(volume_spike(d, 20))  # window will be overridden by UI below if used
    rocv= float(roc(d["close"]).iloc[-1])

    # recompute with UI params
    volx = float(volume_spike(d, vol_win))
    # simple trend breakout: last close > max(prev pivot window)
    trend_up = False
    if len(d) > piv*2+5:
        prior_high = d["close"].rolling(piv).max().shift(1).iloc[-1]
        if not np.isnan(prior_high):
            trend_up = last > float(prior_high)

    g = {
        "pct":   (pct_change >= min_pct) if gate_logic=="ALL" else (pct_change >= min_pct or True),  # gate_logic shown but K/Y do coloring
        "vol":   (volx >= vol_mult) if use_vol else True,
        "roc":   (rocv >= min_roc) if use_roc else True,
        "trend": trend_up if use_trend else True,
        "rsi":   (rsiv >= min_rsi) if use_rsi else True,
        "macd":  (mh   >= min_mh)  if use_macd else True,
        "atr":   (atrp >= min_atr) if use_atr else True,
    }

    # Count enabled gates; coloring uses K/Y
    enabled_vals = [bool(v) for v in g.values()]
    score = sum(enabled_vals)
    green = (score >= K_needed)
    yellow = (score >= Y_needed) and (score < K_needed)

    # ATH/ATL (trend window)
    hist = get_hist(exchange, pid, basis, amount)
    if hist is None or len(hist) < 10:
        athp, athd, atlp, atld = (np.nan, "—", np.nan, "—")
    else:
        info = ath_atl_info(hist)
        athp, athd, atlp, atld = info["From ATH %"], info["ATH date"], info["From ATL %"], info["ATL date"]

    return {
        "Pair": pid,
        "Price": last,
        f"% Change ({tf})": pct_change,
        "From ATH %": athp, "ATH date": athd,
        "From ATL %": atlp, "ATL date": atld,
        "Gates": chips_from_gates(g),
        "Strong Buy": "YES" if green else "—",
        "__partial__": yellow
    }

rows=[]
for pid in pairs:
    r = compute_row(pid)
    if r: rows.append(r)

df = pd.DataFrame(rows)

# -------------------- Render --------------------
st.markdown(f"### Timeframe: {tf}")
st.caption("Chips legend — Δ: %Change • V: Volume× • R: ROC • T: Trend • S: RSI • M: MACD • A: ATR")

if df.empty:
    st.info("No rows yet. Tips: lower **Min % change**, reduce **K**, or increase **Max pairs**. "
            "Try Binance + USDT for a larger universe.")
else:
    chg_col = f"% Change ({tf})"
    df["__green__"] = df["Strong Buy"].eq("YES")
    df_sorted = df.sort_values(["__green__", chg_col], ascending=[False, False]).reset_index(drop=True)
    df_sorted.insert(0, "#", df_sorted.index+1)
    show_cols = ["#","Pair","Price",chg_col,"From ATH %","ATH date","From ATL %","ATL date","Gates","Strong Buy","__partial__"]

    # Top-10
    st.subheader("📌 Top-10 (meets green rule)")
    top10 = df_sorted[df_sorted["Strong Buy"].eq("YES")].head(10).reset_index(drop=True)
    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, loosen gates (lower Min % change or reduce K).")
    else:
        st.dataframe(
            top10[show_cols]
                .style.hide(axis="columns", subset=["__partial__"])
                .apply(style_rows, axis=None)
                .format(precision=6, na_rep="—")
                .format({"Gates": lambda s: s}, na_rep="—", escape="html"),
            use_container_width=True
        )

        # Alerts (session)
        if send_alerts:
            if "alert_seen" not in st.session_state: st.session_state.alert_seen=set()
            new_msgs=[]
            for _, r in top10.iterrows():
                key=f"{r['Pair']}|{tf}|{round(float(r[chg_col]),2)}"
                if key not in st.session_state.alert_seen:
                    st.session_state.alert_seen.add(key)
                    new_msgs.append(f"{r['Pair']}: {float(r[chg_col]):+.2f}% ({tf})  Gates: {r['Gates']}")
            if new_msgs:
                subject=f"[{exchange}] Top-10 — Crypto Tracker"
                body="\n".join(new_msgs)
                if email_to.strip():
                    ok, info = send_email_alert(subject, body, email_to.strip())
                    if not ok: st.warning(info)
                if webhook_url.strip():
                    ok, info = post_webhook(webhook_url.strip(), {"title": subject, "lines": new_msgs})
                    if not ok: st.warning(f"Webhook error: {info}")

    # Discover
    st.subheader("📑 Discover")
    st.dataframe(
        df_sorted[show_cols]
            .style.hide(axis="columns", subset=["__partial__"])
            .apply(style_rows, axis=None)
            .format(precision=6, na_rep="—")
            .format({"Gates": lambda s: s}, na_rep="—", escape="html"),
        use_container_width=True
    )

# -------------------- Auto-refresh --------------------
if "last_refresh" not in st.session_state: st.session_state.last_refresh = time.time()
remaining = refresh_sec - (time.time() - st.session_state.last_refresh)
if remaining <= 0:
    st.session_state.last_refresh = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {refresh_sec}s (next in {int(remaining)}s)")

