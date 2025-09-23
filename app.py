# app.py — Crypto Tracker by hioncrypto (simplified, stable)

# ===================== Requirements (requirements.txt) =====================
# streamlit>=1.33
# pandas>=2.0
# numpy>=1.24
# requests>=2.31
# ==========================================================================

import time
import datetime as dt
from typing import List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
import requests
import streamlit as st

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None

# ----------------------------- App setup -----------------------------
st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")

# ----------------------------- Constants -----------------------------
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

TF_LIST = ["15m", "1h"]
ALL_TFS = {"15m": 900, "1h": 3600}
QUOTES = ["USD", "USDC", "USDT", "BTC", "ETH", "EUR"]
EXCHANGES = ["Coinbase", "Binance"]
DEFAULT_DISCOVER_CAP = 400

# ----------------------------- Helpers -----------------------------
def one_day_window_bars(tf: str) -> int:
    # small overfetch for stability
    return {"15m": 96, "1h": 48}.get(tf, 48)

def ema(s: pd.Series, span: int) -> pd.Series:
    return s.astype("float64").ewm(span=span, adjust=False).mean()

def rsi(close: pd.Series, length=14) -> pd.Series:
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)
    ru = pd.Series(up, index=close.index).ewm(alpha=1 / length, adjust=False).mean()
    rd = pd.Series(dn, index=close.index).ewm(alpha=1 / length, adjust=False).mean()
    rs = ru / (rd + 1e-12)
    return 100 - 100 / (1 + rs)

def macd_core(close: pd.Series, fast=12, slow=26, signal=9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def atr(df: pd.DataFrame, length=14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()

def volume_spike(df: pd.DataFrame, window=20) -> float:
    if len(df) < window + 1:
        return np.nan
    base = df["volume"].rolling(window).mean().iloc[-1]
    return float(df["volume"].iloc[-1] / (base + 1e-12))

def find_pivots(close: pd.Series, span=3) -> Tuple[pd.Index, pd.Index]:
    n = len(close)
    highs, lows = [], []
    v = close.values
    for i in range(span, n - span):
        if v[i] > v[i - span:i].max() and v[i] > v[i + 1:i + 1 + span].max():
            highs.append(i)
        if v[i] < v[i - span:i].min() and v[i] < v[i + 1:i + 1 + span].min():
            lows.append(i)
    return pd.Index(highs), pd.Index(lows)

def trend_breakout_up(df: pd.DataFrame, span=3, within_bars=48) -> bool:
    if df is None or len(df) < span * 2 + 5:
        return False
    highs, _ = find_pivots(df["close"], span)
    if len(highs) == 0:
        return False
    hi = int(highs[-1])
    level = float(df["close"].iloc[hi])
    cross = None
    for j in range(hi + 1, len(df)):
        if float(df["close"].iloc[j]) > level:
            cross = j
            break
    if cross is None:
        return False
    return (len(df) - 1 - cross) <= within_bars

# ----------------------------- Data fetch -----------------------------
def get_df(exchange: str, pair: str, tf: str, limit: Optional[int] = None) -> Optional[pd.DataFrame]:
    tf_seconds = ALL_TFS.get(tf)
    if tf_seconds is None:
        return None

    want = int(limit) if (limit and limit > 0) else one_day_window_bars(tf)
    want = max(1, min(300, want))

    ex = (exchange or "").strip().lower()

    if ex.startswith("coinbase"):
        url = f"{CB_BASE}/products/{pair}/candles"
        params = {"granularity": tf_seconds}
        headers = {"User-Agent": "hioncrypto-tracker/1.0", "Accept": "application/json"}
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, headers=headers, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    if not data:
                        return None
                    df = pd.DataFrame(data, columns=["time", "low", "high", "open", "close", "volume"])
                    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                    df = df.sort_values("time").reset_index(drop=True)
                    df = df[["time", "open", "high", "low", "close", "volume"]]
                    if len(df) > want:
                        df = df.iloc[-want:].reset_index(drop=True)
                    return df if not df.empty else None
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(0.6 * (attempt + 1))
                    continue
                return None
            except Exception:
                time.sleep(0.4 * (attempt + 1))
        return None

    if ex.startswith("binance"):
        try:
            base, quote = pair.split("-")
            symbol = f"{base}{quote}"
        except Exception:
            return None
        interval = "15m" if tf == "15m" else "1h"
        params = {"symbol": symbol, "interval": interval, "limit": max(50, want)}
        try:
            r = requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=20)
            if r.status_code != 200:
                return None
            rows = []
            for a in r.json():
                rows.append({
                    "time": pd.to_datetime(a[0], unit="ms", utc=True),
                    "open": float(a[1]), "high": float(a[2]),
                    "low": float(a[3]), "close": float(a[4]), "volume": float(a[5])
                })
            df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
            if len(df) > want:
                df = df.iloc[-want:].reset_index(drop=True)
            return df if not df.empty else None
        except Exception:
            return None

    return None

def _cache_buster_from_refresh() -> int:
    # makes the cached function refetch on the cadence of refresh_sec
    sec = int(st.session_state.get("refresh_sec", 30))
    sec = max(1, sec)
    return int(time.time() // sec)

@st.cache_data(show_spinner=False)
def df_for_tf_cached(exchange: str, pair: str, tf: str, buster: int) -> Optional[pd.DataFrame]:
    _ = buster  # used only to vary cache key on the refresh cadence
    try:
        bars = one_day_window_bars(tf)
        return get_df(exchange, pair, tf, limit=bars)
    except Exception:
        return None

# ----------------------------- Discovery -----------------------------
def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25)
        r.raise_for_status()
        q = (quote or "").strip().upper()
        return sorted(
            f"{p['base_currency']}-{p['quote_currency']}"
            for p in r.json()
            if p.get("quote_currency", "").upper() == q
        )
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25)
        r.raise_for_status()
        out = []
        q = (quote or "").strip().upper()
        for s in r.json().get("symbols", []):
            if s.get("status") != "TRADING":
                continue
            if s.get("quoteAsset", "").upper() == q:
                out.append(f"{s['baseAsset']}-{q}")
        return sorted(out)
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    ex = (exchange or "").strip().lower()
    if ex.startswith("coinbase"):
        return coinbase_list_products(quote)
    if ex.startswith("binance"):
        return binance_list_products(quote)
    return coinbase_list_products(quote)

# ----------------------------- Gate evaluation -----------------------------
def build_gate_eval(df_tf: pd.DataFrame, settings: dict) -> Tuple[dict, int, str, int]:
    n = len(df_tf)
    lb = max(1, min(int(settings.get("lookback_candles", 3)), 100, n - 1))
    last_close = float(df_tf["close"].iloc[-1])
    ref_close = float(df_tf["close"].iloc[-lb])
    delta_pct = (last_close / ref_close - 1.0) * 100.0
    g_delta = bool(delta_pct >= float(settings.get("min_pct", 0.0)))

    macd_line, signal_line, hist = macd_core(
        df_tf["close"],
        int(settings.get("macd_fast", 12)),
        int(settings.get("macd_slow", 26)),
        int(settings.get("macd_sig", 9)),
    )

    chips = []
    passed = 0
    enabled = 0

    def chip(name, enabled_flag, ok, extra=""):
        if not enabled_flag:
            chips.append(f"{name}–")
        else:
            chips.append(f"{name}{'✅' if ok else '❌'}{extra}")

    # Δ
    passed += int(g_delta); enabled += 1; chip("Δ", True, g_delta, f"({delta_pct:+.2f}%)")

    # Volume spike ×
    if settings.get("use_vol_spike", True):
        volx = volume_spike(df_tf, int(settings.get("vol_window", 20)))
        ok = bool(pd.notna(volx) and volx >= float(settings.get("vol_mult", 1.10)))
        passed += int(ok); enabled += 1; chip(" V", True, ok, f"({volx:.2f}×)" if pd.notna(volx) else "")
    else:
        chip(" V", False, False)

    # RSI
    if settings.get("use_rsi", False):
        rcur = float(rsi(df_tf["close"], int(settings.get("rsi_len", 14))).iloc[-1])
        ok = bool(rcur >= float(settings.get("min_rsi", 55)))
        passed += int(ok); enabled += 1; chip(" S", True, ok, f"({rcur:.1f})")
    else:
        chip(" S", False, False)

    # MACD histogram
    if settings.get("use_macd", False):
        mh = float(hist.iloc[-1])
        ok = bool(mh >= float(settings.get("min_mhist", 0.0)))
        passed += int(ok); enabled += 1; chip(" M", True, ok, f"({mh:.3f})")
    else:
        chip(" M", False, False)

    # Trend breakout
    if settings.get("use_trend", False):
        ok = trend_breakout_up(
            df_tf,
            span=int(settings.get("pivot_span", 4)),
            within_bars=int(settings.get("trend_within", 48)),
        )
        passed += int(ok); enabled += 1; chip(" T", True, ok)
    else:
        chip(" T", False, False)

    # MACD Cross (bullish by default)
    cross_meta = {"ok": False, "bars_ago": None, "below_zero": None}
    if settings.get("use_macd_cross", True):
        bars = int(settings.get("macd_cross_bars", 5))
        only_bull = bool(settings.get("macd_cross_only_bull", True))
        need_below = bool(settings.get("macd_cross_below_zero", True))
        conf = int(settings.get("macd_hist_confirm_bars", 3))

        ok = False
        bars_ago = None
        below = None
        lookback = min(bars + 1, len(hist))
        for i in range(1, lookback):
            prev = macd_line.iloc[-i - 1] - signal_line.iloc[-i - 1]
            now = macd_line.iloc[-i] - signal_line.iloc[-i]
            crossed_up = (prev < 0 and now > 0)
            crossed_dn = (prev > 0 and now < 0)
            hit = crossed_up if only_bull else (crossed_up or crossed_dn)
            if not hit:
                continue
            if need_below and (macd_line.iloc[-i] > 0 or signal_line.iloc[-i] > 0):
                continue
            below = (macd_line.iloc[-i] < 0 and signal_line.iloc[-i] < 0)
            if conf > 0:
                conf_ok = any(hist.iloc[-k] > 0 for k in range(i, min(i + conf, len(hist))))
                if not conf_ok:
                    continue
            ok = True
            bars_ago = i
            break

        cross_meta.update({"ok": ok, "bars_ago": bars_ago, "below_zero": below})
        passed += int(ok); enabled += 1; chip(" C", True, ok, f" ({bars_ago} bars ago)" if bars_ago else "")
    else:
        chip(" C", False, False)

    meta = {"delta_pct": delta_pct, "macd_cross": cross_meta}
    return meta, passed, " ".join(chips), enabled

# ----------------------------- CSS (kill dimming) -----------------------------
st.markdown("""
<style>
  html, body { font-size: 1rem; }
  div[data-testid="stDataFrame"], div[data-testid="stDataFrame"] *,
  div[data-testid="stDataEditor"], div[data-testid="stDataEditor"] * {
    opacity: 1 !important; filter: none !important; transition: none !important; animation: none !important;
  }
  section[data-testid="stSidebar"], section[data-testid="stSidebar"] * {
    pointer-events: auto !important; opacity: 1 !important; filter: none !important; transition: none !important;
  }
</style>
""", unsafe_allow_html=True)

# ----------------------------- Sidebar -----------------------------
with st.sidebar:
    st.markdown("### Market")
    exchange = st.selectbox("Exchange", EXCHANGES, index=0, key="exchange")
    quote = st.selectbox("Quote", QUOTES, index=0, key="quote")

    st.caption("Use one source of pairs at a time.")
    use_my_pairs = st.toggle("⭐ Use My Pairs only", value=False, key="use_my_pairs")
    my_pairs = st.text_input("My Pairs (comma-sep)", "BTC-USD, ETH-USD, SOL-USD", key="my_pairs")
    use_watch = st.toggle("Use Watchlist only", value=False, key="use_watch")
    watchlist = st.text_input("Watchlist (comma-sep)", "BTC-USD, ETH-USD, AVAX-USD", key="watchlist")

    # Discover cap
    # We compute available after building the pool below; slider is here for UX
    discover_cap = st.slider("Pairs to discover (0–500)", 0, 500, DEFAULT_DISCOVER_CAP, 10, key="discover_cap")

    st.markdown("---")
    st.markdown("### Timeframes & Sort")
    sort_tf = st.selectbox("Primary timeframe", TF_LIST, index=1, key="sort_tf")
    sort_desc = st.toggle("Sort descending", value=True, key="sort_desc")
    min_bars = st.slider("Minimum bars required", 1, 100, 1, 1, key="min_bars")

    st.markdown("---")
    st.markdown("### Gates")
    gate_mode = st.radio("Gate Mode", ["ALL", "ANY", "Custom (K/Y)"], index=1, horizontal=True, key="gate_mode")
    hard_filter = st.toggle("Hard filter (hide non-passers)", value=False, key="hard_filter")
    lookback_candles = st.slider("Δ lookback (candles)", 1, 100, 3, 1, key="lookback_candles")
    min_pct = st.slider("Min +% change (Δ)", 0.0, 50.0, 3.0, 0.5, key="min_pct")

    c1, c2, c3 = st.columns(3)
    with c1:
        use_vol_spike = st.toggle("Volume spike ×", value=True, key="use_vol_spike")
        vol_mult = st.slider("Spike multiple ×", 1.0, 5.0, 1.10, 0.05, key="vol_mult")
        vol_window = st.slider("Vol window", 5, 60, 20, 1, key="vol_window")
    with c2:
        use_rsi = st.toggle("RSI", value=False, key="use_rsi")
        rsi_len = st.slider("RSI length", 5, 50, 14, 1, key="rsi_len")
        min_rsi = st.slider("Min RSI", 40, 90, 55, 1, key="min_rsi")
    with c3:
        use_macd = st.toggle("MACD hist", value=False, key="use_macd")
        macd_fast = st.slider("MACD fast", 3, 50, 12, 1, key="macd_fast")
        macd_slow = st.slider("MACD slow", 5, 100, 26, 1, key="macd_slow")
        macd_sig = st.slider("MACD signal", 3, 50, 9, 1, key="macd_sig")
        min_mhist = st.slider("Min MACD hist", 0.0, 2.0, 0.0, 0.05, key="min_mhist")

    c4, c5 = st.columns(2)
    with c4:
        use_trend = st.toggle("Trend breakout (up)", value=False, key="use_trend")
        pivot_span = st.slider("Pivot span", 2, 10, 4, 1, key="pivot_span")
        trend_within = st.slider("Breakout within (bars)", 5, 96, 48, 1, key="trend_within")
    with c5:
        use_macd_cross = st.toggle("Enable MACD Cross", value=True, key="use_macd_cross")
        macd_cross_bars = st.slider("Cross within last (bars)", 1, 10, 5, 1, key="macd_cross_bars")
        macd_cross_only_bull = st.toggle("Bullish only", value=True, key="macd_cross_only_bull")
        macd_cross_below_zero = st.toggle("Prefer below zero", value=True, key="macd_cross_below_zero")
        macd_hist_confirm_bars = st.slider("Histogram > 0 within (bars)", 0, 10, 3, 1, key="macd_hist_confirm_bars")

    st.markdown("**Color rules (Custom only)**")
    K_green = st.selectbox("Green needs ≥ K gates", list(range(1, 8)), index=2, key="K_green")
    Y_yellow = st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0, K_green)), index=min(2, K_green-1), key="Y_yellow")

    st.markdown("---")
    st.markdown("### Display & Refresh")
    font_scale = st.slider("Font size (global)", 0.8, 1.6, 1.0, 0.05, key="font_scale")
    refresh_sec = st.slider("Auto-refresh (seconds)", 5, 120, 30, 1, key="refresh_sec")

# ----------------------------- Build discovery pool -----------------------------
def _split_pairs(csv_text: str) -> List[str]:
    return [p.strip().upper() for p in (csv_text or "").split(",") if p.strip()]

if use_my_pairs:
    pairs = _split_pairs(my_pairs)
elif use_watch and watchlist.strip():
    pairs = _split_pairs(watchlist)
else:
    pairs = list_products(exchange, quote)

# Filter by quote, cap list
pairs = [p for p in pairs if p.endswith(f"-{quote}")]
if discover_cap > 0:
    pairs = pairs[:discover_cap]

# ----------------------------- Gate settings snapshot -----------------------------
gate_settings = dict(
    lookback_candles=int(lookback_candles),
    min_pct=float(min_pct),

    use_vol_spike=bool(use_vol_spike),
    vol_mult=float(vol_mult),
    vol_window=int(vol_window),

    use_rsi=bool(use_rsi),
    rsi_len=int(rsi_len),
    min_rsi=int(min_rsi),

    use_macd=bool(use_macd),
    macd_fast=int(macd_fast),
    macd_slow=int(macd_slow),
    macd_sig=int(macd_sig),
    min_mhist=float(min_mhist),

    use_trend=bool(use_trend),
    pivot_span=int(pivot_span),
    trend_within=int(trend_within),

    use_macd_cross=bool(use_macd_cross),
    macd_cross_bars=int(macd_cross_bars),
    macd_cross_only_bull=bool(macd_cross_only_bull),
    macd_cross_below_zero=bool(macd_cross_below_zero),
    macd_hist_confirm_bars=int(macd_hist_confirm_bars),
)

# ----------------------------- Build rows -----------------------------
rows = []
buster = _cache_buster_from_refresh()
for pid in pairs:
    dft = df_for_tf_cached(exchange, pid, sort_tf, buster)
    if dft is None or getattr(dft, "empty", True):
        continue
    if len(dft) < int(min_bars):
        continue

    # Evaluate gates
    meta, passed, chips, enabled_cnt = build_gate_eval(dft, gate_settings)

    # Decide color by mode
    if gate_mode == "ALL":
        include = (enabled_cnt > 0 and passed == enabled_cnt)
        is_green = include
        is_yellow = (0 < passed < enabled_cnt)
    elif gate_mode == "ANY":
        include = True
        is_green = (passed >= 1)
        is_yellow = (not is_green) and (passed >= 1)
    else:  # Custom (K/Y)
        include = True
        is_green = (passed >= int(K_green))
        is_yellow = (not is_green) and (passed >= int(Y_yellow))

    if hard_filter:
        if gate_mode in {"ALL", "ANY"}:
            if not include:
                continue
        else:
            if not (is_green or is_yellow):
                continue

    last_price = float(dft["close"].iloc[-1])
    first_price = float(dft["close"].iloc[0])
    pct_change = (last_price / (first_price + 1e-12) - 1.0) * 100.0

    signal_text = "Strong Buy" if is_green else ("Watch" if is_yellow else "")

    rows.append({
        "Pair": pid,
        "Price": round(last_price, 6),
        f"% Change ({sort_tf})": round(pct_change, 3),
        "Signal": signal_text,
        "Gates passed": passed,
        "Gates enabled": enabled_cnt,
        "Chips": chips,
    })

# ----------------------------- DataFrame & styling -----------------------------
df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair", "Price", f"% Change ({sort_tf})", "Signal", "Gates passed", "Gates enabled", "Chips"])

st.caption(f"⏱️ Last updated: {time.strftime('%Y-%m-%d %H:%M:%S')}")

if df.empty:
    st.info("No rows to show. Try ANY mode, lower Min Δ, shorten lookback, set Minimum bars to 1, or increase discovery cap.")
else:
    # Normalize Signal helpers every time (no stale carryover)
    sig_norm = df["Signal"].astype(str).str.strip().str.upper()
    df["_green"] = sig_norm.isin(["STRONG BUY", "GREEN"])
    df["_yellow"] = sig_norm.isin(["WATCH", "YELLOW"])

    chg_col = f"% Change ({sort_tf})"
    df = df.sort_values(chg_col, ascending=not bool(sort_desc), na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index + 1)

    arrow = "↓" if sort_desc else "↑"
    st.markdown(f"### Timeframe: **{sort_tf}** • Sorting: **{arrow} {chg_col}**")

    # ---------- Top-10 ----------
    if df["_green"].any():
        top10 = df.loc[df["_green"]].sort_values(chg_col, ascending=not bool(sort_desc), na_position="last").head(10)
    else:
        top10 = df.head(10)
    top10 = top10.reset_index(drop=True)
    top10["#"] = np.arange(1, len(top10) + 1)
    _top10_display = top10.drop(columns=[c for c in ["_green", "_yellow"] if c in top10.columns])

    st.subheader("📌 Top-10")
    def _row_style(row):
        s = str(row.get("Signal", "")).strip().upper()
        if s == "STRONG BUY":
            return ["background-color: #16a34a; color: white;"] * len(row)
        if s == "WATCH":
            return ["background-color: #eab308; color: black;"] * len(row)
        return [""] * len(row)

    st.table(_top10_display.style.apply(_row_style, axis=1))

    # ---------- All pairs ----------
    st.subheader("📑 All pairs")
    _df_display = df.drop(columns=[c for c in ["_green", "_yellow"] if c in df.columns])
    st.table(_df_display.style.apply(_row_style, axis=1))

# Footer
st.caption(
    f"Pairs shown: {len(df)} • Exchange: {exchange} • Quote: {quote} • TF: {sort_tf} "
    f"• Gate Mode: {gate_mode} • Hard filter: {'On' if hard_filter else 'Off'}"
)

# ----------------------------- Auto-refresh -----------------------------
_interval_ms = int(max(1, int(refresh_sec))) * 1000
if st_autorefresh:
    st_autorefresh(interval=_interval_ms, key="heartbeat")
else:
    st.markdown(f"<script>setTimeout(function(){{window.location.reload();}}, {_interval_ms});</script>", unsafe_allow_html=True)

st.caption(f"Last updated: {dt.datetime.utcnow().strftime('%H:%M:%S')} UTC")
