# app.py
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np
import requests
import streamlit as st

# -----------------------------
# Page config + compact CSS
# -----------------------------
st.set_page_config(
    page_title="Crypto Tracker by hioncrypto",
    page_icon="📈",
    layout="wide"
)

BLUE = "#2b67f6"          # calm blue
BLUE_DARK = "#1f4ec0"
ACCENT = "#00c389"

st.markdown(
    f"""
    <style>
      /* Sidebar section headers */
      .stSidebar [data-testid="stExpander"] > details > summary {{
        background: {BLUE}14;
        border-radius: 8px;
        padding: 6px 10px;
        color: {BLUE};
      }}
      .stSidebar [data-testid="stExpander"] {{
        border: 1px solid {BLUE}2A;
        border-radius: 10px;
        margin-bottom: 10px;
      }}

      /* Make the main tables not dim */
      [data-testid="stDataFrame"] div {{
        opacity: 1 !important;
      }}

      /* Little badge */
      .pill {{
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        background: {BLUE}20;
        color: {BLUE};
        border: 1px solid {BLUE}35;
      }}

      /* Strong Buy YES cell */
      .sb-yes {{
        background: {ACCENT}22 !important;
        color: #0b5137 !important;
        font-weight: 700 !important;
      }}

      /* Chips column uses plain emoji, so nothing to style there */
    </style>
    """,
    unsafe_allow_html=True
)

# -----------------------------
# Simple helpers (persistence)
# -----------------------------
def init_state():
    d = st.session_state
    if "q" not in d:
        d.q = dict(st.query_params)
    def _get(name, default):
        # prefer query param -> then session_state -> default
        if isinstance(d.q, dict) and name in d.q:
            return type(default)(d.q.get(name))
        return d.get(name, default)

    # Defaults (loose, so you see rows fast)
    d.exchange = _get("exchange", "Coinbase")
    d.quote = _get("quote", "USD")
    d.use_watchlist = bool(int(_get("use_watchlist", 0)))
    d.watchlist = d.get("watchlist", "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD")
    d.max_pairs = int(_get("max_pairs", 300))

    d.tf = _get("tf", "1h")             # primary timeframe label
    d.k_green = int(_get("k_green", 2)) # gates needed
    d.yellow_y = int(_get("yellow_y", 1))

    # Indicators (thresholds kept simple/transparent)
    d.min_p = float(_get("min_p", 0.0))           # min |% change| (no positive-only)
    d.vol_mult = float(_get("vol_mult", 1.0))     # volume spike multiple vs median
    d.rsi_min = int(_get("rsi_min", 30))          # RSI min
    d.rsi_max = int(_get("rsi_max", 75))          # RSI max
    d.macd_hist_min = float(_get("macd_hist_min", 0.02))
    d.roc_len = int(_get("roc_len", 14))
    d.min_roc = float(_get("min_roc", 0.0))
    d.trend_lookback = int(_get("trend_lookback", 90))  # days window for a simple trend break

    # Alerts
    d.send_email = bool(int(_get("send_email", 0)))
    d.email_to = _get("email_to", "")
    d.hook_url = _get("hook_url", "")
    d.refresh_sec = int(_get("refresh_sec", 30))

    # Save back to URL query
    st.query_params.update(
        exchange=d.exchange,
        quote=d.quote,
        use_watchlist=int(d.use_watchlist),
        max_pairs=d.max_pairs,
        tf=d.tf,
        k_green=d.k_green,
        yellow_y=d.yellow_y,
        min_p=d.min_p,
        vol_mult=d.vol_mult,
        rsi_min=d.rsi_min,
        rsi_max=d.rsi_max,
        macd_hist_min=d.macd_hist_min,
        roc_len=d.roc_len,
        min_roc=d.min_roc,
        trend_lookback=d.trend_lookback,
        send_email=int(d.send_email),
        email_to=d.email_to,
        hook_url=d.hook_url,
        refresh_sec=d.refresh_sec,
    )

init_state()

# -----------------------------
# Data fetchers (REST only)
# -----------------------------
def coinbase_products(quote="USD", limit=500) -> List[str]:
    # Returns product ids like "BTC-USD"
    r = requests.get("https://api.exchange.coinbase.com/products", timeout=20)
    r.raise_for_status()
    prods = r.json()
    ids = [p["id"] for p in prods if p.get("quote_currency", "").upper() == quote.upper()]
    ids.sort()
    return ids[:limit]

def coinbase_candles(pair: str, granularity: int, since_hours: int = 24) -> pd.DataFrame:
    # granularity seconds: 60, 300, 900, 3600, 21600, 86400
    # We'll fetch ~since_hours back for fast calc
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=since_hours)
    params = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "granularity": granularity,
    }
    url = f"https://api.exchange.coinbase.com/products/{pair}/candles"
    r = requests.get(url, params=params, timeout=20)
    if r.status_code != 200:
        return pd.DataFrame()
    data = r.json()
    # Coinbase returns [time, low, high, open, close, volume]
    if not isinstance(data, list) or len(data) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(data, columns=["t", "low", "high", "open", "close", "volume"])
    df["t"] = pd.to_datetime(df["t"], unit="s", utc=True)
    return df.sort_values("t").reset_index(drop=True)

def binance_symbols(quote="USDT", limit=500) -> List[str]:
    # returns like BTCUSDT
    r = requests.get("https://api.binance.com/api/v3/exchangeInfo", timeout=20)
    r.raise_for_status()
    syms = r.json()["symbols"]
    out = [s["symbol"] for s in syms if s["quoteAsset"] == quote and s["status"] == "TRADING"]
    out.sort()
    return out[:limit]

def binance_24h(pair: str) -> Tuple[float, float]:
    # price, pct change 24h
    r = requests.get("https://api.binance.com/api/v3/ticker/24hr", params={"symbol": pair}, timeout=15)
    if r.status_code != 200:
        return (np.nan, np.nan)
    j = r.json()
    price = float(j.get("lastPrice", "nan"))
    chg = float(j.get("priceChangePercent", "nan"))
    return price, chg

# -----------------------------
# Indicators (lightweight)
# -----------------------------
def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    roll_up = pd.Series(up).ewm(alpha=1/length, adjust=False).mean()
    roll_dn = pd.Series(dn).ewm(alpha=1/length, adjust=False).mean()
    rs = roll_up / (roll_dn + 1e-12)
    return 100 - (100 / (1 + rs))

def macd_hist(series: pd.Series, fast=12, slow=26, sig=9) -> pd.Series:
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=sig, adjust=False).mean()
    return macd - signal

def roc(series: pd.Series, length: int = 14) -> pd.Series:
    return series.pct_change(length) * 100.0

def trend_break_simple(series: pd.Series, lookback: int = 90) -> bool:
    # Above a rolling max of the last N closes -> breakout up
    if len(series) < lookback + 2:
        return False
    ref = series.iloc[-(lookback+1):-1].max()
    return bool(series.iloc[-1] > ref)

# -----------------------------
# Core compute: Coinbase fast path
# -----------------------------
def discover_coinbase(quote: str, max_pairs: int, tf_label: str) -> pd.DataFrame:
    # timeframe -> seconds (granularity) and hours of history to pull
    gran = {"1h": 3600, "4h": 14400, "1d": 86400}.get(tf_label, 3600)
    hist_hours = {"1h": 24, "4h": 7*24, "1d": 90*24}.get(tf_label, 24)
    all_pairs = coinbase_products(quote=quote, limit=max_pairs)
    rows = []
    for pid in all_pairs:
        df = coinbase_candles(pid, granularity=gran, since_hours=hist_hours)
        if df.empty or len(df) < 20:
            continue
        close = df["close"]
        price = float(close.iloc[-1])
        pct = (close.iloc[-1] / close.iloc[0] - 1) * 100.0
        from_ath = (close.iloc[-1] / close.max() - 1) * 100.0
        ath_date = df.loc[close.idxmax(), "t"].date().isoformat()
        atl_date = df.loc[close.idxmin(), "t"].date().isoformat()
        # Indicators
        rsi_now = float(rsi(close, 14).iloc[-1])
        macd_h = float(macd_hist(close).iloc[-1])
        roc_now = float(roc(close, st.session_state.roc_len).iloc[-1]) if len(close) > st.session_state.roc_len else np.nan
        t_break = trend_break_simple(close, st.session_state.trend_lookback if tf_label != "1h" else 90)
        # Very fast volume proxy: last bar vs median volume
        volx = float(df["volume"].iloc[-1] / (df["volume"].median() + 1e-9))
        rows.append(
            dict(
                Pair=pid,
                Price=price,
                pct_change=pct,
                From_ATH=from_ath,
                ATH_date=ath_date,
                From_ATL=(price / close.min() - 1) * 100.0,
                ATL_date=atl_date,
                volx=volx,
                rsi=rsi_now,
                macd_hist=macd_h,
                roc=roc_now,
                trend_up=t_break
            )
        )
    return pd.DataFrame(rows)

def discover_binance(quote: str, max_pairs: int) -> pd.DataFrame:
    # Discovery: price + 24h change (fast). No candles, so limited gates.
    quote_asset = {"USD":"USDT", "USDT":"USDT"}.get(quote.upper(), "USDT")
    syms = binance_symbols(quote=quote_asset, limit=max_pairs)
    rows = []
    for s in syms:
        price, chg = binance_24h(s)
        if math.isnan(price):
            continue
        pair = f"{s[:-len(quote_asset)]}-{quote}"  # make it look like ABC-USD
        rows.append(dict(Pair=pair, Price=price, pct_change=chg, From_ATH=np.nan, ATH_date="—",
                         From_ATL=np.nan, ATL_date="—", volx=np.nan, rsi=np.nan, macd_hist=np.nan,
                         roc=np.nan, trend_up=False))
    return pd.DataFrame(rows)

# -----------------------------
# Gates + chips
# -----------------------------
def evaluate_gates(df: pd.DataFrame) -> pd.DataFrame:
    d = st.session_state
    chips = []
    passes = []

    for _, r in df.iterrows():
        c = []  # chip emojis
        n_pass = 0

        # Δ% change >= threshold (in magnitude; no positive-only filter)
        ok_pct = abs(r["pct_change"]) >= d.min_p
        c.append("✅Δ" if ok_pct else "❌Δ")
        n_pass += int(ok_pct)

        # Volume spike multiple
        ok_v = (not math.isnan(r["volx"])) and (r["volx"] >= d.vol_mult)
        c.append("✅V" if ok_v else "❌V")
        n_pass += int(ok_v)

        # RSI window
        ok_rsi = (not math.isnan(r["rsi"])) and (d.rsi_min <= r["rsi"] <= d.rsi_max)
        c.append("✅S" if ok_rsi else "❌S")   # S for RSI like before
        n_pass += int(ok_rsi)

        # MACD histogram minimum
        ok_macd = (not math.isnan(r["macd_hist"])) and (r["macd_hist"] >= d.macd_hist_min)
        c.append("✅M" if ok_macd else "❌M")
        n_pass += int(ok_macd)

        # ROC
        ok_roc = (not math.isnan(r["roc"])) and (r["roc"] >= d.min_roc)
        c.append("✅R" if ok_roc else "❌R")
        n_pass += int(ok_roc)

        # Trend up (breakout)
        ok_t = bool(r["trend_up"])
        c.append("✅T" if ok_t else "❌T")
        n_pass += int(ok_t)

        chips.append(" ".join(c))
        passes.append(n_pass)

    out = df.copy()
    out["Gates"] = chips
    out["passes"] = passes
    out["Strong Buy"] = np.where(out["passes"] >= st.session_state.k_green, "YES", "—")
    out["__partial__"] = np.where(
        (out["passes"] >= st.session_state.yellow_y) & (out["passes"] < st.session_state.k_green),
        "YES",
        "—"
    )
    return out

# -----------------------------
# Sidebar
# -----------------------------
SUPPORTED_EXCHANGES = ["Coinbase", "Binance"]  # (Kraken, KuCoin later)
with st.sidebar:
    st.title("Market")
    st.caption("Tips: **Uncheck** watchlist to discover *all* pairs. Tighten gates after you see rows.")

    st.session_state.exchange = st.selectbox("Exchange", SUPPORTED_EXCHANGES, index=SUPPORTED_EXCHANGES.index(st.session_state.exchange) if st.session_state.exchange in SUPPORTED_EXCHANGES else 0, key="exch")

    st.session_state.quote = st.selectbox("Quote currency", ["USD", "USDT"], index=["USD","USDT"].index(st.session_state.quote) if st.session_state.quote in ["USD","USDT"] else 0, key="quote_sel")

    st.session_state.use_watchlist = st.checkbox("Use watchlist only (ignore discovery)", value=st.session_state.use_watchlist, help="If off, we scan all listed pairs for the exchange.")
    st.session_state.watchlist = st.text_area("Watchlist (comma-separated)", value=st.session_state.watchlist, height=70)

    st.session_state.max_pairs = st.slider("Max pairs to evaluate (discovery)", 10, 500, st.session_state.max_pairs)

    st.markdown("### Timeframes")
    st.session_state.tf = st.selectbox("Primary timeframe (for % change)", ["1h","4h","1d"], index=["1h","4h","1d"].index(st.session_state.tf) if st.session_state.tf in ["1h","4h","1d"] else 0)

    st.markdown("### Gates")
    st.session_state.min_p = st.slider("Min |% change| (Sort TF)", 0.0, 50.0, st.session_state.min_p, step=0.5)
    st.session_state.vol_mult = st.slider("Volume spike×", 0.5, 10.0, st.session_state.vol_mult, step=0.1)
    st.session_state.rsi_min, st.session_state.rsi_max = st.slider("RSI band", 1, 99, (st.session_state.rsi_min, st.session_state.rsi_max))
    st.session_state.macd_hist_min = st.slider("Min MACD hist", 0.00, 0.50, float(st.session_state.macd_hist_min), step=0.01)
    st.session_state.roc_len = st.slider("ROC length", 5, 60, st.session_state.roc_len)
    st.session_state.min_roc = st.slider("Min ROC %", -20.0, 20.0, float(st.session_state.min_roc), step=0.5)
    st.session_state.trend_lookback = st.slider("Trend Break window (days)", 20, 180, st.session_state.trend_lookback, help="Macro view with higher values; micro with lower.")

    st.session_state.k_green = st.selectbox("Gates needed to turn green (K)", list(range(1, 7)), index=max(0, st.session_state.k_green-1))
    st.session_state.yellow_y = st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0, st.session_state.k_green)), index=min(st.session_state.yellow_y, st.session_state.k_green-1))

    st.markdown("### Notifications")
    st.session_state.send_email = st.checkbox("Send Email/Webhook after this session", value=st.session_state.send_email)
    st.session_state.email_to = st.text_input("Email recipient (optional)", value=st.session_state.email_to)
    st.session_state.hook_url = st.text_input("Webhook URL (optional)", value=st.session_state.hook_url)
    st.session_state.refresh_sec = st.slider("Auto-refresh every (seconds)", 10, 180, st.session_state.refresh_sec, help="Auto-refresh is active while the page is open.")

# -----------------------------
# Header
# -----------------------------
st.title("Crypto Tracker by hioncrypto")

# -----------------------------
# Data pipeline
# -----------------------------
# Discovery set
if st.session_state.use_watchlist:
    # Use only watchlist
    wl = [w.strip().upper() for w in st.session_state.watchlist.split(",") if w.strip()]
    found = len(wl)
    st.sidebar.markdown(f"**Found:** {found}")
    # For watchlist, try to resolve via exchange
    if st.session_state.exchange == "Coinbase":
        pairs = [w for w in wl if w.endswith(f"-{st.session_state.quote}")]
        df = discover_coinbase(st.session_state.quote, max_pairs=len(pairs), tf_label=st.session_state.tf)
        # Keep only the requested
        df = df[df["Pair"].isin(pairs)].reset_index(drop=True)
    else:
        # Binance watchlist interpretation: "BTC-USD" => "BTCUSDT"
        quote_asset = "USDT" if st.session_state.quote.upper() in ("USD", "USDT") else "USDT"
        uname = [p.replace("-USD","USDT").replace("-USDT","USDT").replace("-"+st.session_state.quote, quote_asset) for p in wl]
        bdf = discover_binance(st.session_state.quote, max_pairs=len(uname))
        df = bdf[bdf["Pair"].str.replace("-USD","-USDT").str.endswith("-"+st.session_state.quote)].reset_index(drop=True)
else:
    # Full discovery
    if st.session_state.exchange == "Coinbase":
        df = discover_coinbase(st.session_state.quote, st.session_state.max_pairs, st.session_state.tf)
        st.sidebar.markdown(f"**Found:** {len(df)}")
    else:
        df = discover_binance(st.session_state.quote, st.session_state.max_pairs)
        st.sidebar.markdown(f"**Found:** {len(df)}")

if df.empty:
    st.info("No pairs found yet. Tips: lower *Min |% change|*, reduce *Volume spike×*, or switch timeframe.")
else:
    # Evaluate & display
    df = evaluate_gates(df)

    # Top-10 (meets green rule)
    top = df[df["passes"] >= st.session_state.k_green].copy()
    top = top.sort_values(["passes", "pct_change"], ascending=[False, False]).head(10)
    if not top.empty:
        st.subheader("📌 Top-10 (meets green rule)")
        show_cols = ["Pair","Price","pct_change","From_ATH","ATH_date","From_ATL","ATL_date","Gates","Strong Buy","__partial__"]
        top2 = top[show_cols].rename(columns={
            "pct_change":"% Change",
            "From_ATH":"From ATH %",
            "From_ATL":"From ATL %",
            "__partial__":"partial"
        })
        # Style Strong Buy
        def _sb_style(v):
            return ["sb-yes" if x=="YES" else "" for x in v]
        st.dataframe(
            top2.style.apply(_sb_style, subset=["Strong Buy"]),
            use_container_width=True
        )

    # Discover table
    st.subheader("🧭 Discover")
    show_cols = ["Pair","Price","pct_change","From_ATH","ATH_date","From_ATL","ATL_date","Gates","Strong Buy","__partial__"]
    disc = df.sort_values(["passes","pct_change"], ascending=[False, False])[show_cols].rename(columns={
        "pct_change":"% Change",
        "From_ATH":"From ATH %",
        "From_ATL":"From ATL %",
        "__partial__":"partial"
    })
    st.dataframe(disc, use_container_width=True)

# -----------------------------
# Alerts (stubs)
# -----------------------------
def send_email_stub(to_addr: str, subject: str, body: str):
    # You can wire smtp here; left as stub per your request to keep it in file.
    pass

def send_webhook_stub(url: str, payload: dict):
    try:
        requests.post(url, json=payload, timeout=8)
    except Exception:
        pass

if st.session_state.send_email and not df.empty:
    green_now = df[df["passes"] >= st.session_state.k_green].sort_values("pct_change", ascending=False)
    if not green_now.empty:
        msg = f"{len(green_now)} pairs meet green rule (K={st.session_state.k_green}). Top: {green_now.iloc[0]['Pair']} ({green_now.iloc[0]['pct_change']:.2f}%)."
        if st.session_state.email_to:
            send_email_stub(st.session_state.email_to, "Crypto Tracker alert", msg)
        if st.session_state.hook_url:
            send_webhook_stub(st.session_state.hook_url, {"text": msg})

# -----------------------------
# Auto refresh
# -----------------------------
if st.session_state.refresh_sec > 0:
    st.caption(f"Auto-refresh every {st.session_state.refresh_sec}s is active while you keep the page open.")
    time.sleep(0.1)
    st.experimental_rerun()
