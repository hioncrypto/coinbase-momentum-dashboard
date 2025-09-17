# app.py — Crypto Tracker by hioncrypto (clean, stable)
# Requirements (add to requirements.txt):
# streamlit>=1.33
# pandas>=2.0
# numpy>=1.24
# requests>=2.31
# websocket-client>=1.6

import json
import time
import datetime as dt
import threading
import queue
import ssl
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Tuple, Dict

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ----------------------------- App setup -----------------------------
st.set_page_config(page_title="Crypto Tracker by hioncrypto", layout="wide")

WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

# ----------------------------- Constants -----------------------------
TF_LIST = ["15m", "1h"]
ALL_TFS = {"15m": 900, "1h": 3600}
QUOTES = ["USD", "USDC", "USDT", "BTC", "ETH", "EUR"]
EXCHANGES = ["Coinbase", "Binance", "Kraken (coming soon)", "KuCoin (coming soon)"]

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

DEFAULT_FEEDS = [
    "https://blog.coinbase.com/feed",
    "https://www.binance.com/en/support/announcement",
]

DEFAULTS = dict(
    # Sorting & TF
    sort_tf="1h", sort_desc=True, min_bars=1,
    # Δ & ROC window
    lookback_candles=3, min_pct=3.0,
    # Gates toggles
    use_vol_spike=True, vol_mult=1.10, vol_window=20,
    use_rsi=False, rsi_len=14, min_rsi=55,
    use_macd=False, macd_fast=12, macd_slow=26, macd_sig=9, min_mhist=0.0,
    use_atr=False, atr_len=14, min_atr=0.5,
    use_trend=False, pivot_span=4, trend_within=48,
    use_roc=False, min_roc=1.0,
    # MACD cross gate
    use_macd_cross=True, macd_cross_bars=5, macd_cross_only_bull=True,
    macd_cross_below_zero=True, macd_hist_confirm_bars=3,
    # Gate mode
    gate_mode="ANY", hard_filter=False, K_green=3, Y_yellow=2, preset="Spike Hunter",
    # Market
    exchange="Coinbase", quote="USD",
    watchlist="BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD",
    use_watch=False, use_my_pairs=False, my_pairs="BTC-USD, ETH-USD, SOL-USD",
    # Display & refresh
    font_scale=1.0, refresh_sec=30,
    # Notifications
    email_to="", webhook_url="",
    # ATH/ATL (optional heavy history; off by default)
    do_ath=False, basis="Daily", amount_daily=90, amount_hourly=24, amount_weekly=12,
    # Discovery cap
    discover_cap=400,
    # Listing Radar
    lr_enabled=False,
    lr_watch_coinbase=True, lr_watch_binance=True,
    lr_watch_quotes="USD, USDT, USDC",
    lr_poll_sec=30, lr_upcoming_sec=300, lr_upcoming_window_h=48,
    lr_feeds=", ".join(DEFAULT_FEEDS),
    # Mode
    mode="REST only", ws_chunk=5,
)

def one_day_window_bars(tf: str) -> int:
    # small overfetch for stability
    return {"15m": 96, "1h": 48}.get(tf, 24)

# ----------------------------- URL persist -----------------------------
def _coerce(v, typ):
    if typ is bool:
        return str(v).strip().lower() in {"1", "true", "yes", "on"}
    if typ is int:
        try: return int(str(v).strip())
        except: return None
    if typ is float:
        try: return float(str(v).strip())
        except: return None
    return str(v).strip()

PERSIST: Dict[str, Tuple[object, type]] = {
    # Market
    "exchange": (DEFAULTS["exchange"], str),
    "quote": (DEFAULTS["quote"], str),
    "use_watch": (DEFAULTS["use_watch"], bool),
    "watchlist": (DEFAULTS["watchlist"], str),
    "use_my_pairs": (DEFAULTS["use_my_pairs"], bool),
    "my_pairs": (DEFAULTS["my_pairs"], str),
    "discover_cap": (DEFAULTS["discover_cap"], int),
    # Mode
    "mode": (DEFAULTS["mode"], str), "ws_chunk": (DEFAULTS["ws_chunk"], int),
    # TF & sorting
    "sort_tf": (DEFAULTS["sort_tf"], str), "sort_desc": (DEFAULTS["sort_desc"], bool),
    "min_bars": (DEFAULTS["min_bars"], int),
    # Δ/ROC
    "lookback_candles": (DEFAULTS["lookback_candles"], int), "min_pct": (DEFAULTS["min_pct"], float),
    "use_roc": (DEFAULTS["use_roc"], bool), "min_roc": (DEFAULTS["min_roc"], float),
    # Gates
    "use_vol_spike": (DEFAULTS["use_vol_spike"], bool), "vol_mult": (DEFAULTS["vol_mult"], float), "vol_window": (DEFAULTS["vol_window"], int),
    "use_rsi": (DEFAULTS["use_rsi"], bool), "rsi_len": (DEFAULTS["rsi_len"], int), "min_rsi": (DEFAULTS["min_rsi"], int),
    "use_macd": (DEFAULTS["use_macd"], bool), "macd_fast": (DEFAULTS["macd_fast"], int),
    "macd_slow": (DEFAULTS["macd_slow"], int), "macd_sig": (DEFAULTS["macd_sig"], int), "min_mhist": (DEFAULTS["min_mhist"], float),
    "use_atr": (DEFAULTS["use_atr"], bool), "atr_len": (DEFAULTS["atr_len"], int), "min_atr": (DEFAULTS["min_atr"], float),
    "use_trend": (DEFAULTS["use_trend"], bool), "pivot_span": (DEFAULTS["pivot_span"], int), "trend_within": (DEFAULTS["trend_within"], int),
    # MACD cross
    "use_macd_cross": (DEFAULTS["use_macd_cross"], bool),
    "macd_cross_bars": (DEFAULTS["macd_cross_bars"], int),
    "macd_cross_only_bull": (DEFAULTS["macd_cross_only_bull"], bool),
    "macd_cross_below_zero": (DEFAULTS["macd_cross_below_zero"], bool),
    "macd_hist_confirm_bars": (DEFAULTS["macd_hist_confirm_bars"], int),
    # Gate mode
    "gate_mode": (DEFAULTS["gate_mode"], str), "hard_filter": (DEFAULTS["hard_filter"], bool),
    "K_green": (DEFAULTS["K_green"], int), "Y_yellow": (DEFAULTS["Y_yellow"], int), "preset": (DEFAULTS["preset"], str),
    # ATH/ATL
    "do_ath": (DEFAULTS["do_ath"], bool), "basis": (DEFAULTS["basis"], str),
    "amount_hourly": (DEFAULTS["amount_hourly"], int),
    "amount_daily": (DEFAULTS["amount_daily"], int),
    "amount_weekly": (DEFAULTS["amount_weekly"], int),
    # Display/Notif
    "font_scale": (DEFAULTS["font_scale"], float), "refresh_sec": (DEFAULTS["refresh_sec"], int),
    "email_to": (DEFAULTS["email_to"], str), "webhook_url": (DEFAULTS["webhook_url"], str),
    # Collapse
    "collapse_all": (False, bool),
    # Listing Radar
    "lr_enabled": (DEFAULTS["lr_enabled"], bool),
    "lr_watch_coinbase": (DEFAULTS["lr_watch_coinbase"], bool),
    "lr_watch_binance": (DEFAULTS["lr_watch_binance"], bool),
    "lr_watch_quotes": (DEFAULTS["lr_watch_quotes"], str),
    "lr_poll_sec": (DEFAULTS["lr_poll_sec"], int),
    "lr_upcoming_sec": (DEFAULTS["lr_upcoming_sec"], int),
    "lr_upcoming_window_h": (DEFAULTS["lr_upcoming_window_h"], int),
    "lr_feeds": (DEFAULTS["lr_feeds"], str),
}

def init_persisted_state():
    qp = st.query_params
    for k, (dflt, typ) in PERSIST.items():
        if k in qp:
            raw = qp[k] if not isinstance(qp[k], list) else qp[k][0]
            val = _coerce(raw, typ)
            if val is None:
                val = dflt
        else:
            val = dflt
        st.session_state.setdefault(k, val)

def sync_state_to_query_params():
    payload = {}
    for k in PERSIST.keys():
        v = st.session_state.get(k)
        if v is None:
            continue
        payload[k] = v if not isinstance(v, (list, tuple)) else ", ".join(map(str, v))
    if payload:
        st.query_params.update(payload)

def _init_runtime():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("alert_seen", set())
    ss.setdefault("last_refresh", time.time())
    # Listing Radar
    ss.setdefault("lr_baseline", {"Coinbase": set(), "Binance": set()})
    ss.setdefault("lr_events", [])
    ss.setdefault("lr_unacked", 0)
    ss.setdefault("lr_last_poll", 0.0)
    ss.setdefault("lr_last_upcoming_poll", 0.0)

_init_runtime()
init_persisted_state()

# Safety seeds
for k, d in [("exchange", "Coinbase"), ("quote", "USD"), ("sort_tf", "1h")]:
    st.session_state.setdefault(k, d)

# ----------------------------- Indicators -----------------------------
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
    return float(df["volume"].iloc[-1] / (df["volume"].rolling(window).mean().iloc[-1] + 1e-12))

def find_pivots(close: pd.Series, span=3) -> Tuple[pd.Index, pd.Index]:
    n = len(close)
    highs = []
    lows = []
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

    if exchange.lower().startswith("coinbase"):
        url = f"{CB_BASE}/products/{pair}/candles"
        params = {"granularity": tf_seconds}
        headers = {"User-Agent": "coinbase-momentum-dashboard/1.0", "Accept": "application/json"}
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

    if exchange.lower().startswith("binance"):
        # Map "BASE-QUOTE" -> "BASEQUOTE"
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
            return df if not df.empty else None
        except Exception:
            return None

    return None

def df_for_tf(exchange: str, pair: str, tf: str) -> Optional[pd.DataFrame]:
    bars = one_day_window_bars(tf)
    try:
        return get_df(exchange, pair, tf, limit=bars)
    except Exception:
        return None

def coinbase_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{CB_BASE}/products", timeout=25)
        r.raise_for_status()
        return sorted(f"{p['base_currency']}-{p['quote_currency']}" for p in r.json() if p.get("quote_currency") == quote)
    except Exception:
        return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25)
        r.raise_for_status()
        out = []
        for s in r.json().get("symbols", []):
            if s.get("status") != "TRADING":
                continue
            if s.get("quoteAsset") == quote:
                out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception:
        return []

def list_products(exchange: str, quote: str) -> List[str]:
    quote = (quote or "").strip().upper()
    if exchange == "Coinbase":
        return coinbase_list_products(quote)
    if exchange == "Binance":
        return binance_list_products(quote)
    return []

# ----------------------------- Email/Webhook -----------------------------
def send_email_alert(subject, body, recipient):
    try:
        cfg = st.secrets["smtp"]
    except Exception:
        return False, "SMTP not configured in st.secrets"
    try:
        msg = MIMEMultipart()
        msg["From"] = cfg["sender"]
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port", 465), context=ctx) as s:
            s.login(cfg["user"], cfg["password"])
            s.sendmail(cfg["sender"], recipient, msg.as_string())
        return True, "Email sent"
    except Exception as e:
        return False, f"Email error: {e}"

def post_webhook(url, payload):
    try:
        r = requests.post(url, json=payload, timeout=10)
        return (200 <= r.status_code < 300), r.text
    except Exception as e:
        return False, str(e)

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
    passed += int(g_delta)
    enabled += 1
    chip("Δ", True, g_delta, f"({delta_pct:+.2f}%)")

    # Volume spike ×
    if settings.get("use_vol_spike", False):
        volx = volume_spike(df_tf, int(settings.get("vol_window", 20)))
        ok = bool(pd.notna(volx) and volx >= float(settings.get("vol_mult", 1.10)))
        passed += int(ok)
        enabled += 1
        chip(" V", True, ok, f"({volx:.2f}×)" if pd.notna(volx) else "")
    else:
        chip(" V", False, False)

    # ROC
    if settings.get("use_roc", False):
        roc = (df_tf["close"].iloc[-1] / df_tf["close"].iloc[-lb] - 1.0) * 100.0 if n > lb else np.nan
        ok = bool(pd.notna(roc) and roc >= float(settings.get("min_roc", 1.0)))
        passed += int(ok)
        enabled += 1
        chip(" R", True, ok, f"({roc:+.2f}%)" if pd.notna(roc) else "")
    else:
        chip(" R", False, False)

    # Trend breakout
    if settings.get("use_trend", False):
        ok = trend_breakout_up(df_tf, span=int(settings.get("pivot_span", 4)), within_bars=int(settings.get("trend_within", 48)))
        passed += int(ok)
        enabled += 1
        chip(" T", True, ok)
    else:
        chip(" T", False, False)

    # RSI
    if settings.get("use_rsi", False):
        rcur = float(rsi(df_tf["close"], int(settings.get("rsi_len", 14))).iloc[-1])
        ok = bool(rcur >= float(settings.get("min_rsi", 55)))
        passed += int(ok)
        enabled += 1
        chip(" S", True, ok, f"({rcur:.1f})")
    else:
        chip(" S", False, False)

    # MACD histogram
    if settings.get("use_macd", False):
        mh = float(hist.iloc[-1])
        ok = bool(mh >= float(settings.get("min_mhist", 0.0)))
        passed += int(ok)
        enabled += 1
        chip(" M", True, ok, f"({mh:.3f})")
    else:
        chip(" M", False, False)

    # ATR %
    if settings.get("use_atr", False):
        atr_pct = float((atr(df_tf, int(settings.get("atr_len", 14))) / (df_tf["close"] + 1e-12) * 100.0).iloc[-1])
        ok = bool(atr_pct >= float(settings.get("min_atr", 0.5)))
        passed += int(ok)
        enabled += 1
        chip(" A", True, ok, f"({atr_pct:.2f}%)")
    else:
        chip(" A", False, False)

    # MACD Cross
    cross_meta = {"ok": False, "bars_ago": None, "below_zero": None}
    if settings.get("use_macd_cross", True):
        bars = int(settings.get("macd_cross_bars", 5))
        only_bull = bool(settings.get("macd_cross_only_bull", True))
        need_below = bool(settings.get("macd_cross_below_zero", True))
        conf = int(settings.get("macd_hist_confirm_bars", 3))

        ok = False
        bars_ago = None
        below = None
        for i in range(1, min(bars + 1, len(hist))):
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
        passed += int(ok)
        enabled += 1
        chip(" C", True, ok, f" ({bars_ago} bars ago)" if bars_ago is not None else f" (≤{bars})")
    else:
        chip(" C", False, False)

    meta = {"delta_pct": delta_pct, "macd_cross": cross_meta}
    return meta, passed, " ".join(chips), enabled

# ----------------------------- Optional ATH/ATL helpers -----------------------------
def compute_ath_atl(df: pd.DataFrame) -> Tuple[float, str, float, str]:
    # Input df must have columns ["time","open","high","low","close","volume"] sorted asc
    if df is None or df.empty:
        return np.nan, "", np.nan, ""
    last = float(df["close"].iloc[-1])
    idx_ath = int(df["high"].idxmax())
    idx_atl = int(df["low"].idxmin())
    ath = float(df["high"].iloc[idx_ath])
    atl = float(df["low"].iloc[idx_atl])
    d_ath = pd.to_datetime(df["time"].iloc[idx_ath]).date().isoformat()
    d_atl = pd.to_datetime(df["time"].iloc[idx_atl]).date().isoformat()
    from_ath = (last / ath - 1.0) * 100 if ath > 0 else np.nan
    from_atl = (last / atl - 1.0) * 100 if atl > 0 else np.nan
    return from_ath, d_ath, from_atl, d_atl

# ----------------------------- CSS -----------------------------
st.markdown("""
<style>
  /* Base size */
  html, body { font-size: 1rem; }

  /* 1) Tables & editor: never dim, never animate */
  div[data-testid="stDataFrame"],
  div[data-testid="stDataFrame"] *,
  div[data-testid="stDataEditor"],
  div[data-testid="stDataEditor"] * {
    opacity: 1 !important;
    filter: none !important;
    transition: none !important;
    animation: none !important;
    will-change: auto !important;
  }

  /* 2) Streamlit busy overlay: no dim + DO NOT eat clicks */
  [aria-busy="true"],
  [aria-busy="true"] * {
    opacity: 1 !important;
    filter: none !important;
    transition: none !important;
    animation: none !important;
    will-change: auto !important;
    pointer-events: none !important;   /* stop overlay from intercepting clicks */
  }

  /* 3) Sidebar stays interactive even when app is "busy" */
  section[data-testid="stSidebar"],
  section[data-testid="stSidebar"] * {
    pointer-events: auto !important;
    opacity: 1 !important;
    filter: none !important;
    transition: none !important;
    animation: none !important;
    position: relative;
    z-index: 2;
  }

  /* 4) Spinner: remove the gray veil look */
  div[data-testid="stSpinner"],
  div[data-testid="stSpinner"] * {
    opacity: 1 !important;
    filter: none !important;
    transition: none !important;
    animation: none !important;
  }
</style>
""", unsafe_allow_html=True)

# ----------------------------- Sidebar -----------------------------
with st.sidebar:
    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("Collapse all", use_container_width=True):
            st.session_state["collapse_all"] = True
    with c2:
        if st.button("Expand all", use_container_width=True):
            st.session_state["collapse_all"] = False
    with c3:
        st.toggle("⭐ Use My Pairs only", key="use_my_pairs", value=st.session_state.get("use_my_pairs", False))

    with st.popover("Manage My Pairs"):
        st.caption("Comma-separated (e.g., BTC-USD, ETH-USDT)")
        current = st.text_area("Edit list", st.session_state.get("my_pairs", DEFAULTS["my_pairs"]))
        if st.button("Save My Pairs"):
            st.session_state["my_pairs"] = ", ".join([p.strip().upper() for p in current.split(",") if p.strip()])
            st.success("Saved.")

def expander(title: str):
    return st.sidebar.expander(title, expanded=not st.session_state.get("collapse_all", False))

# MARKET
with expander("Market"):
    st.selectbox("Exchange", EXCHANGES, index=EXCHANGES.index(st.session_state["exchange"]), key="exchange")
    effective_exchange = "Coinbase" if "coming soon" in st.session_state["exchange"] else st.session_state["exchange"]
    if "coming soon" in st.session_state["exchange"]:
        st.info("This exchange is coming soon. Using Coinbase for data.")

    st.selectbox("Quote currency", QUOTES, index=QUOTES.index(st.session_state["quote"]), key="quote")
    st.caption("Tips: Watchlist/My Pairs restrict discovery. Quote filters pairs like BTC-USD vs BTC-USDT.")
    st.checkbox("Use watchlist only (ignore discovery)", key="use_watch", value=st.session_state.get("use_watch", False))

    if "watchlist" not in st.session_state:
        st.session_state["watchlist"] = DEFAULTS["watchlist"]
    st.text_area("Watchlist", key="watchlist")

    # Available pool
    if st.session_state["use_watch"] and st.session_state["watchlist"].strip():
        avail_pairs = [p.strip().upper() for p in st.session_state["watchlist"].split(",") if p.strip()]
        avail_pairs = [p for p in avail_pairs if p.endswith(f"-{st.session_state['quote']}")]
    elif st.session_state["use_my_pairs"]:
        avail_pairs = [p.strip().upper() for p in st.session_state["my_pairs"].split(",") if p.strip()]
        avail_pairs = [p for p in avail_pairs if p.endswith(f"-{st.session_state['quote']}")]
    else:
        avail_pairs = list_products(effective_exchange, st.session_state["quote"])

    if "discover_cap" not in st.session_state:
        st.session_state["discover_cap"] = DEFAULTS["discover_cap"]

    st.slider(f"Pairs to discover (0–500) • Available: {len(avail_pairs)}", 0, 500, key="discover_cap", step=10)

# MODE
if "mode" not in st.session_state:
    st.session_state["mode"] = "REST only"
if "ws_chunk" not in st.session_state:
    st.session_state["ws_chunk"] = 5

with expander("Mode"):
    st.radio("Data source", ["REST only", "WebSocket + REST (hybrid)"], key="mode")
    st.caption("REST is pull-only. WebSocket streams faster prices (Coinbase only) for a subset.")
    st.slider("WS subscribe chunk (Coinbase)", 2, 20, key="ws_chunk", step=1)

with expander("Timeframes"):
    tf_options = ["15m", "1h"]
    if "sort_tf" not in st.session_state or st.session_state["sort_tf"] not in tf_options:
        st.session_state["sort_tf"] = "1h"
    st.selectbox("Primary sort timeframe", tf_options, index=tf_options.index(st.session_state["sort_tf"]), key="sort_tf")
    st.caption("15m is fast/noisy; 1h steadier. Sorting uses % change in this timeframe.")
    st.toggle("Sort descending (largest first)", key="sort_desc", value=st.session_state.get("sort_desc", True))
    st.caption("Minimum bars requirement is set to 1 so green/yellow can appear on short windows.")

# GATES
with expander("Gates"):
    st.radio("Preset", ["Spike Hunter", "Early MACD Cross", "Confirm Rally", "None"],
             index=["Spike Hunter", "Early MACD Cross", "Confirm Rally", "None"].index(st.session_state.get("preset", "Spike Hunter")),
             horizontal=True, key="preset")
    st.markdown(
        "**Tips:** Gate Mode 'ALL' requires every enabled gate. 'ANY' needs at least one. "
        "'Custom (K/Y)' colors rows based on how many gates pass (K=green, Y=yellow). "
        "Volume spike needs vol_window+1 bars."
    )

    # Apply light presets (non-destructive for non-listed keys)
    if st.session_state["preset"] == "Spike Hunter":
        st.session_state.update(dict(gate_mode="ANY", hard_filter=False, lookback_candles=3, min_pct=3.0,
                                     use_vol_spike=True, vol_mult=1.10, use_rsi=False, use_macd=False,
                                     use_trend=False, use_roc=False, use_macd_cross=False))
    elif st.session_state["preset"] == "Early MACD Cross":
        st.session_state.update(dict(gate_mode="ANY", hard_filter=False, lookback_candles=3, min_pct=3.0,
                                     use_vol_spike=True, vol_mult=1.10, use_rsi=True, min_rsi=50,
                                     use_macd=False, use_trend=False, use_roc=False, use_macd_cross=True,
                                     macd_cross_bars=5, macd_cross_only_bull=True, macd_cross_below_zero=True,
                                     macd_hist_confirm_bars=3))
    elif st.session_state["preset"] == "Confirm Rally":
        st.session_state.update(dict(gate_mode="Custom (K/Y)", hard_filter=True, lookback_candles=2, min_pct=5.0,
                                     use_vol_spike=True, vol_mult=1.20, use_rsi=True, min_rsi=60,
                                     use_macd=True, min_mhist=0.0, use_trend=True, pivot_span=4, trend_within=48,
                                     use_roc=False, use_macd_cross=False, K_green=3, Y_yellow=2))

    st.radio("Gate Mode", ["ALL", "ANY", "Custom (K/Y)"],
             index=["ALL", "ANY", "Custom (K/Y)"].index(st.session_state.get("gate_mode", "ANY")),
             horizontal=True, key="gate_mode")
    st.toggle("Hard filter (hide non-passers)", key="hard_filter", value=st.session_state.get("hard_filter", False))

    st.slider("Δ lookback (candles)", 1, 100, int(st.session_state.get("lookback_candles", 3)), 1, key="lookback_candles")
    st.slider("Min +% change (Δ gate)", 0.0, 50.0, float(st.session_state.get("min_pct", 3.0)), 0.5, key="min_pct")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.toggle("Volume spike ×", key="use_vol_spike", value=st.session_state.get("use_vol_spike", True))
        st.slider("Spike multiple ×", 1.0, 5.0, float(st.session_state.get("vol_mult", 1.10)), 0.05, key="vol_mult")
    with c2:
        st.toggle("RSI", key="use_rsi", value=st.session_state.get("use_rsi", False))
        st.slider("Min RSI", 40, 90, int(st.session_state.get("min_rsi", 55)), 1, key="min_rsi")
    with c3:
        st.toggle("MACD hist", key="use_macd", value=st.session_state.get("use_macd", False))
        st.slider("Min MACD hist", 0.0, 2.0, float(st.session_state.get("min_mhist", 0.0)), 0.05, key="min_mhist")

    c4, c5, c6 = st.columns(3)
    with c4:
        st.toggle("ATR %", key="use_atr", value=st.session_state.get("use_atr", False))
        st.slider("Min ATR %", 0.0, 10.0, float(st.session_state.get("min_atr", 0.5)), 0.1, key="min_atr")
    with c5:
        st.toggle("Trend breakout (up)", key="use_trend", value=st.session_state.get("use_trend", False))
        st.slider("Pivot span (bars)", 2, 10, int(st.session_state.get("pivot_span", 4)), 1, key="pivot_span")
        st.slider("Breakout within (bars)", 5, 96, int(st.session_state.get("trend_within", 48)), 1, key="trend_within")
    with c6:
        st.toggle("ROC (rate of change)", key="use_roc", value=st.session_state.get("use_roc", False))
        st.slider("Min ROC %", 0.0, 50.0, float(st.session_state.get("min_roc", 1.0)), 0.5, key="min_roc")

    st.markdown("**MACD Cross (early entry)**")
    c7, c8, c9, c10 = st.columns(4)
    with c7:
        st.toggle("Enable MACD Cross", key="use_macd_cross", value=st.session_state.get("use_macd_cross", True))
    with c8:
        st.slider("Cross within last (bars)", 1, 10, int(st.session_state.get("macd_cross_bars", 5)), 1, key="macd_cross_bars")
    with c9:
        st.toggle("Bullish only", key="macd_cross_only_bull", value=st.session_state.get("macd_cross_only_bull", True))
    with c10:
        st.toggle("Prefer below zero", key="macd_cross_below_zero", value=st.session_state.get("macd_cross_below_zero", True))
    st.slider("Histogram > 0 within (bars)", 0, 10, int(st.session_state.get("macd_hist_confirm_bars", 3)), 1, key="macd_hist_confirm_bars")

    st.markdown("---")
    st.subheader("Color rules (Custom only)")
    st.selectbox("Gates needed to turn green (K)", list(range(1, 8)), index=int(st.session_state.get("K_green", 3)) - 1, key="K_green")
    st.selectbox("Yellow needs ≥ Y (but < K)", list(range(0, int(st.session_state.get("K_green", 3)))), index=min(int(st.session_state.get("Y_yellow", 2)), int(st.session_state.get("K_green", 3)) - 1), key="Y_yellow")

# Indicator lengths
with expander("Indicator lengths"):
    st.caption("Longer = smoother; shorter = more reactive.")
    st.slider("RSI length", 5, 50, int(st.session_state.get("rsi_len", 14)), 1, key="rsi_len")
    st.slider("MACD fast EMA", 3, 50, int(st.session_state.get("macd_fast", 12)), 1, key="macd_fast")
    st.slider("MACD slow EMA", 5, 100, int(st.session_state.get("macd_slow", 26)), 1, key="macd_slow")
    st.slider("MACD signal", 3, 50, int(st.session_state.get("macd_sig", 9)), 1, key="macd_sig")
    st.slider("ATR length", 5, 50, int(st.session_state.get("atr_len", 14)), 1, key="atr_len")

# ATH/ATL history (single clean block; optional)
with expander("History depth (for ATH/ATL)"):
    do_ath = st.toggle("Compute ATH/ATL", key="do_ath", value=st.session_state.get("do_ath", False))
    basis = st.selectbox("Basis", ["Hourly", "Daily", "Weekly"], index=["Hourly", "Daily", "Weekly"].index(st.session_state.get("basis", "Daily")), key="basis")
    if basis == "Hourly":
        st.slider("Hours (≤72)", 1, 72, int(st.session_state.get("amount_hourly", 24)), 1, key="amount_hourly")
    elif basis == "Daily":
        st.slider("Days (≤365)", 1, 365, int(st.session_state.get("amount_daily", 90)), 1, key="amount_daily")
    else:
        st.slider("Weeks (≤52)", 1, 52, int(st.session_state.get("amount_weekly", 12)), 1, key="amount_weekly")

# Display
with expander("Display"):
    st.slider("Font size (global)", 0.8, 1.6, float(st.session_state.get("font_scale", 1.0)), 0.05, key="font_scale")
    st.slider("Auto-refresh (seconds)", 5, 120, int(st.session_state.get("refresh_sec", 30)), 1, key="refresh_sec")
# Notifications
with expander("Notifications"):
    st.caption("Tips: Email requires SMTP in st.secrets; webhook posts JSON to your endpoint.")
    st.text_input("Email recipient (optional)", st.session_state.get("email_to", ""), key="email_to")
    st.text_input("Webhook URL (optional)", st.session_state.get("webhook_url", ""), key="webhook_url")

# Listing Radar
with expander("Listing Radar"):
    st.caption("‘New’ listings are detected by symbol diffs. ‘Upcoming’ scraped from feeds within a window.")
    if st.session_state.get("lr_unacked", 0) > 0:
        st.markdown('<span class="blink-badge">New/Upcoming listings</span>', unsafe_allow_html=True)

    st.toggle("Enable Listing Radar", key="lr_enabled", value=st.session_state.get("lr_enabled", False))
    cA, cB = st.columns(2)
    with cA:
        st.text_area("Announcement feeds (comma-separated)", value=st.session_state.get("lr_feeds", DEFAULTS["lr_feeds"]), key="lr_feeds", height=100)
        st.text_input("Quotes to watch (CSV)", value=st.session_state.get("lr_watch_quotes", DEFAULTS["lr_watch_quotes"]), key="lr_watch_quotes")
    with cB:
        st.slider("Poll interval (seconds)", 15, 600, st.session_state.get("lr_poll_sec", DEFAULTS["lr_poll_sec"]), key="lr_poll_sec")
        st.slider("Upcoming scan every (seconds)", 60, 3600, st.session_state.get("lr_upcoming_sec", DEFAULTS["lr_upcoming_sec"]), key="lr_upcoming_sec")
        st.slider("Upcoming alert window (hours)", 1, 72, st.session_state.get("lr_upcoming_window_h", DEFAULTS["lr_upcoming_window_h"]), key="lr_upcoming_window_h")

    if st.button("Acknowledge all alerts"):
        st.session_state["lr_unacked"] = 0

# Header label
st.markdown(f"<div style='font-size:1.3rem;font-weight:700;margin:4px 0 10px 2px;'>Timeframe: {st.session_state['sort_tf']}</div>", unsafe_allow_html=True)

# ----------------------------- Discovery pool -----------------------------
if st.session_state.get("use_my_pairs", False):
    pairs = [p.strip().upper() for p in st.session_state.get("my_pairs", "").split(",") if p.strip()]
else:
    if st.session_state.get("use_watch", False) and st.session_state.get("watchlist", "").strip():
        pairs = [p.strip().upper() for p in st.session_state["watchlist"].split(",") if p.strip()]
    else:
        effective_exchange = "Coinbase" if "coming soon" in st.session_state["exchange"] else st.session_state["exchange"]
        pairs = list_products(effective_exchange, st.session_state["quote"])
        pairs = [p for p in pairs if p.endswith(f"-{st.session_state['quote']}")]
        cap = max(0, min(500, int(st.session_state.get("discover_cap", DEFAULTS["discover_cap"]))))

        pairs = pairs[:cap] if cap > 0 else []

# ----------------------------- WebSocket lifecycle -----------------------------
def ws_worker(product_ids, endpoint="wss://ws-feed.exchange.coinbase.com"):
    try:
        ws = websocket.WebSocket()
        ws.connect(endpoint, timeout=10)
        ws.settimeout(1.0)
        ws.send(json.dumps({"type": "subscribe", "channels": [{"name": "ticker", "product_ids": product_ids}]}))
        st.session_state["ws_alive"] = True
        while st.session_state.get("ws_alive", False):
            try:
                msg = ws.recv()
                if not msg:
                    continue
                d = json.loads(msg)
                if d.get("type") == "ticker":
                    pid = d.get("product_id")
                    px = d.get("price")
                    if pid and px:
                        st.session_state["ws_q"].put((pid, float(px)))
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break
    except Exception:
        pass
    finally:
        st.session_state["ws_alive"] = False
        try:
            ws.close()
        except Exception:
            pass

def start_ws(exchange: str, pairs: List[str], chunk: int):
    if exchange != "Coinbase" or not WS_AVAILABLE or not pairs:
        return
    if st.session_state.get("ws_alive"):
        return
    pick = pairs[:max(2, min(chunk, len(pairs)))]
    t = threading.Thread(target=ws_worker, args=(pick,), daemon=True)
    st.session_state["ws_thread"] = t
    t.start()
    time.sleep(0.2)

def stop_ws():
    if st.session_state.get("ws_alive"):
        st.session_state["ws_alive"] = False

def drain_ws_queue():
    q = st.session_state.get("ws_q")
    prices = st.session_state.get("ws_prices", {})
    try:
        while True:
            pid, px = q.get_nowait()
            prices[pid] = px
    except Exception:
        pass
    st.session_state["ws_prices"] = prices

effective_exchange = "Coinbase" if "coming soon" in st.session_state["exchange"] else st.session_state["exchange"]
want_ws = (
    pairs
    and st.session_state.get("mode", "REST only").startswith("WebSocket")
    and effective_exchange == "Coinbase"
    and WS_AVAILABLE
)
if want_ws:
    start_ws(effective_exchange, pairs, int(st.session_state.get("ws_chunk", 5)))
    drain_ws_queue()
else:
    stop_ws()

# ----------------------------- Build rows -----------------------------
sort_tf = st.session_state.get("sort_tf", "1h")
chg_col = f"% Change ({sort_tf})"

rows: List[Dict] = []

for pid in pairs:
    dft = df_for_tf(effective_exchange, pid, sort_tf)
    if dft is None or getattr(dft, "empty", True):
        continue

    # respect minimum bars if user raises it above 1
    if len(dft) < int(st.session_state.get("min_bars", 1)):
        continue

    # Price and % change over the fetched window (prefer WS tick if available)
last_price = float(dft["close"].iloc[-1])          # candle fallback
px_ws = st.session_state.get("ws_prices", {}).get(pid)
if px_ws:
    try:
        last_price = float(px_ws)                  # live tick from WebSocket
    except Exception:
        pass

first_price = float(dft["close"].iloc[0])
pct_display = (last_price / (first_price + 1e-12) - 1.0) * 100.0


        # Gather gate settings (ALL 4-SPACE INDENTS, NO TABS)
    gate_settings = dict(
        lookback_candles=int(st.session_state.get("lookback_candles", 3)),
        min_pct=float(st.session_state.get("min_pct", 3.0)),

        use_vol_spike=bool(st.session_state.get("use_vol_spike", True)),
        vol_mult=float(st.session_state.get("vol_mult", 1.10)),
        vol_window=int(st.session_state.get("vol_window", 20)),

        use_rsi=bool(st.session_state.get("use_rsi", False)),
        rsi_len=int(st.session_state.get("rsi_len", 14)),
        min_rsi=int(st.session_state.get("min_rsi", 55)),

        use_macd=bool(st.session_state.get("use_macd", False)),
        macd_fast=int(st.session_state.get("macd_fast", 12)),
        macd_slow=int(st.session_state.get("macd_slow", 26)),
        macd_sig=int(st.session_state.get("macd_sig", 9)),
        min_mhist=float(st.session_state.get("min_mhist", 0.0)),

        use_atr=bool(st.session_state.get("use_atr", False)),
        atr_len=int(st.session_state.get("atr_len", 14)),
        min_atr=float(st.session_state.get("min_atr", 0.5)),

        use_trend=bool(st.session_state.get("use_trend", False)),
        pivot_span=int(st.session_state.get("pivot_span", 4)),
        trend_within=int(st.session_state.get("trend_within", 48)),

        use_roc=bool(st.session_state.get("use_roc", False)),
        min_roc=float(st.session_state.get("min_roc", 1.0)),

        use_macd_cross=bool(st.session_state.get("use_macd_cross", True)),
        macd_cross_bars=int(st.session_state.get("macd_cross_bars", 5)),
        macd_cross_only_bull=bool(st.session_state.get("macd_cross_only_bull", True)),
        macd_cross_below_zero=bool(st.session_state.get("macd_cross_below_zero", True)),
        macd_hist_confirm_bars=int(st.session_state.get("macd_hist_confirm_bars", 3)),
    )

    # Evaluate gates
    meta, passed, chips, enabled_cnt = build_gate_eval(dft, gate_settings)

    # Decide colors (GREEN/YELLOW) using your existing mode logic
    mode = st.session_state.get("gate_mode", "ANY")
    hard_filter = bool(st.session_state.get("hard_filter", False))
    k_required = int(st.session_state.get("K_green", 3))
    y_required = int(st.session_state.get("Y_yellow", 2))

    if mode == "ALL":
        include = (enabled_cnt > 0 and passed == enabled_cnt)
        is_green = include
        is_yellow = (0 < passed < enabled_cnt)
    else:
        is_green = (passed >= k_required)
        is_yellow = (not is_green) and (passed >= y_required)
        include = True

    if hard_filter:
        if mode in {"ALL", "ANY"}:
            keep_row = include
        else:
            keep_row = (is_green or is_yellow)
        if not keep_row:
            continue

    # Final “Signal” text used by the row styler
    signal_text = "Strong Buy" if is_green else ("Watch" if is_yellow else "")

    # Append row
    rows.append({
        "Pair": pid,
        "Price": last_price,
        chg_col: pct_display,
        f"Δ% (last {max(1, int(st.session_state.get('lookback_candles', 3)))} bars)": meta.get("delta_pct"),
        "Gates": chips,
        "Signal": signal_text,
        "_green": is_green,
        "_yellow": is_yellow,
        "_passed": passed,
    })

# ----------------------------- Diagnostics & Tables -----------------------------
df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair"])

if df.empty:
    st.info("No rows to show. Try ANY mode, lower Min Δ, shorten lookback, set Minimum bars to 1, or increase discovery cap.")
else:
    df = df.sort_values(chg_col, ascending=not st.session_state.get("sort_desc", True), na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index + 1)

    def highlight_rows(row):
        sig = row.get("Signal", "")
        if sig == "Strong Buy":
            return ['background-color: green; color: white'] * len(row)
        if sig == "Watch":
            return ['background-color: yellow; color: black'] * len(row)
        return [''] * len(row)

    # --- Top 10 section ---
    st.subheader("📌 Top-10")
    st.caption(f"Last updated: {dt.datetime.utcnow().strftime('%H:%M:%S')} UTC • Refresh: {st.session_state.get('refresh_sec', 30)}s")
    top10 = df[df["_green"]].sort_values(chg_col, ascending=False, na_position="last").head(10).drop(columns=["_green", "_yellow"])
    st.dataframe(top10.style.apply(highlight_rows, axis=1), use_container_width=True)

    # --- All pairs section ---
    st.subheader("📑 All pairs")
    st.caption(f"Last updated: {dt.datetime.utcnow().strftime('%H:%M:%S')} UTC • Refresh: {st.session_state.get('refresh_sec', 30)}s")
    st.dataframe(df.drop(columns=["_green", "_yellow"]).style.apply(highlight_rows, axis=1), use_container_width=True)

    # --- Footer info ---
    q = st.session_state.get("quote", "USD")
    tf = st.session_state.get("sort_tf", "1h")
    gm = st.session_state.get("gate_mode", "ANY")
    hf = "On" if st.session_state.get("hard_filter", False) else "Off"
    effective_exchange = "Coinbase" if "coming soon" in st.session_state["exchange"] else st.session_state["exchange"]

    st.caption(
        f"Pairs shown: {len(df)} • Exchange: {effective_exchange} • Quote: {q} "
        f"• TF: {tf} • Gate Mode: {gm} • Hard filter: {hf}"
    )

# ----------------------------- Listing Radar engine -----------------------------
def lr_parse_quotes(csv_text: str) -> set:
    return set(x.strip().upper() for x in (csv_text or "").split(",") if x.strip())

def lr_fetch_symbols(exchange: str, quotes: set) -> set:
    try:
        if exchange == "Coinbase":
            r = requests.get(f"{CB_BASE}/products", timeout=25); r.raise_for_status()
            return set(f"{p['base_currency']}-{p['quote_currency']}" for p in r.json() if p.get("quote_currency") in quotes)
        elif exchange == "Binance":
            r = requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=25); r.raise_for_status()
            out = set()
            for s in r.json().get("symbols", []):
                if s.get("status") != "TRADING":
                    continue
                qte = s.get("quoteAsset", "")
                if qte in quotes:
                    out.add(f"{s['baseAsset']}-{qte}")
            return out
    except Exception:
        return set()
    return set()

def lr_note_event(kind:str, exchange:str, pair:str, when:Optional[str], link:str):
    ev_id = f"{kind}|{exchange}|{pair}|{when or ''}"
    if any(ev.get("id") == ev_id for ev in st.session_state["lr_events"]):
        return
    st.session_state["lr_events"].insert(0, {"id": ev_id, "kind": kind, "exchange": exchange, "pair": pair, "when": when, "link": link, "ts": dt.datetime.utcnow().isoformat() + "Z"})
    st.session_state["lr_unacked"] += 1
    subject = f"[Listing Radar] {kind}: {exchange} {pair}" + (f" at {when}" if when else "")
    body = f"{kind} detected\nExchange: {exchange}\nPair: {pair}\nWhen: {when or 'unknown'}\nLink: {link or 'n/a'}"
    if st.session_state.get("email_to"):
        send_email_alert(subject, body, st.session_state["email_to"])
    if st.session_state.get("webhook_url"):
        post_webhook(st.session_state["webhook_url"], {"title": subject, "details": body})

def lr_extract_upcoming_from_text(txt:str) -> List[Tuple[str, Optional[str], Optional[str]]]:
    out = []
    for ln in re.split(r"[\r\n]+", txt):
        if "<" in ln and ">" in ln:
            continue
        low = ln.lower()
        if any(k in low for k in ["will list", "trading opens", "trading will open", "launches", "goes live", "lists "]):
            when = None
            m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?)", ln)
            if m:
                when = m.group(1)
            sym = None
            sm = re.search(r"\b([A-Z0-9]{2,10})[-/ ](USD|USDC|USDT|BTC|ETH|EUR)\b", ln)
            if sm:
                sym = sm.group(0).replace(" ", "-").replace("/", "-")
            out.append((ln.strip(), when, sym))
    return out

def lr_scan_new_listings():
    if not st.session_state.get("lr_enabled"):
        return
    quotes = lr_parse_quotes(st.session_state.get("lr_watch_quotes", "USD, USDT, USDC"))
    now = time.time()
    if now - st.session_state.get("lr_last_poll", 0) < int(st.session_state.get("lr_poll_sec", 30)):
        return
    st.session_state["lr_last_poll"] = now

    for exch, enabled in [("Coinbase", st.session_state.get("lr_watch_coinbase", True)),
                          ("Binance", st.session_state.get("lr_watch_binance", True))]:
        if not enabled:
            continue
        current = lr_fetch_symbols(exch, quotes)
        base = st.session_state["lr_baseline"].get(exch, set())
        if not base:
            st.session_state["lr_baseline"][exch] = current
            continue
        for sy in sorted(list(current - base)):
            lr_note_event("NEW", exch, sy, None, "")
        st.session_state["lr_baseline"][exch] = current

def lr_scan_upcoming():
    if not st.session_state.get("lr_enabled"):
        return
    now = time.time()
    if now - st.session_state.get("lr_last_upcoming_poll", 0) < int(st.session_state.get("lr_upcoming_sec", 300)):
        return
    st.session_state["lr_last_upcoming_poll"] = now

    feeds = [u.strip() for u in st.session_state.get("lr_feeds", "").split(",") if u.strip()]
    for url in feeds:
        try:
            r = requests.get(url, timeout=20)
            if r.status_code != 200:
                continue
            txt = r.text
            found = lr_extract_upcoming_from_text(txt)
            horizon = dt.datetime.utcnow() + dt.timedelta(hours=int(st.session_state.get("lr_upcoming_window_h", 48)))
            for snippet, when, pair_guess in found:
                pair = pair_guess or "UNKNOWN"
                if pair == "UNKNOWN":
                    continue
                when_iso = None
                if when:
                    try:
                        dt_guess = pd.to_datetime(when, utc=True)
                        if dt_guess.tzinfo is None:
                            dt_guess = dt_guess.tz_localize("UTC")
                        if dt_guess.to_pydatetime() <= horizon:
                            when_iso = dt_guess.isoformat()
                    except Exception:
                        when_iso = None
                lr_note_event("UPCOMING", "Unknown", pair, when_iso, url)
        except Exception:
            continue

lr_scan_new_listings()
lr_scan_upcoming()

if st.session_state.get("lr_enabled"):
    st.subheader("🛰️ Listing Radar events")
    if not st.session_state["lr_events"]:
        st.caption("No events yet.")
    else:
        evdf = pd.DataFrame(st.session_state["lr_events"]).reindex(columns=["ts", "kind", "exchange", "pair", "when", "link"])
        st.data_editor(evdf, use_container_width=True, hide_index=True, disabled=True)

# ----------------------------- Persist URL state & auto-refresh -----------------------------
sync_state_to_query_params()

remaining = int(st.session_state.get("refresh_sec", 30)) - int(
    time.time() - st.session_state.get("last_refresh", time.time())
)
if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(
        f"Auto-refresh every {int(st.session_state.get('refresh_sec', 30))}s "
        f"(next in {max(0, remaining)}s)"
    )

# Show a heartbeat so you know it really reran
import datetime as dt
st.caption(f"Last updated: {dt.datetime.utcnow().strftime('%H:%M:%S')} UTC")
