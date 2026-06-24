# Enhanced Crypto Tracker by hioncrypto - Updated Version
# Requirements (add to requirements.txt):
# streamlit>=1.33
# pandas>=2.0
# numpy>=1.24
# requests>=2.31
# websocket-client>=1.6


import streamlit as st
import streamlit.components.v1 as components

# st.fragment landed after experimental_fragment; 1.36 still uses the experimental name
st_fragment = getattr(st, "fragment", None) or getattr(st, "experimental_fragment", None)
if st_fragment is None:
    raise RuntimeError("Streamlit >= 1.33 is required (fragment / experimental_fragment missing).")

# Page configuration - MUST be first Streamlit command
st.set_page_config(
    page_title="hioncrypto's: Crypto Tracker",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================================
# GLOBAL CSS (MOBILE TWEAKS + SIDEBAR RESIZE HANDLE)
# ============================================================================
st.markdown(
    """
    <style>
    /* Hide resize handle / separator (display:none avoids subpixel artefacts) */
    section[data-testid="stSidebar"] [data-testid="stVerticalBlockBorder"],
    section[data-testid="stSidebar"] [data-testid="stSidebarResizer"],
    section[data-testid="stSidebar"] div[role="separator"][aria-orientation="vertical"] {
        display: none !important;
        opacity: 0 !important;
        border: none !important;
        background: transparent !important;
        pointer-events: none !important;
    }

    /* Native Streamlit toggles — hidden; custom buttons trigger them via JS */
    [data-testid="collapsedControl"] {
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
    }

    section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"],
    section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        min-height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden !important;
    }

    /* Custom collapse button — fixed inside sidebar edge (not clipped by overflow) */
    #hion-collapse-sidebar-btn {
        position: fixed !important;
        top: 12px !important;
        z-index: 999999 !important;
        display: none !important;
        align-items: center !important;
        justify-content: center !important;
        width: 36px !important;
        min-width: 36px !important;
        height: 36px !important;
        min-height: 36px !important;
        margin: 0 !important;
        padding: 0 !important;
        background: #3b4252 !important;
        border: 1px solid #9ca3af !important;
        border-radius: 8px !important;
        color: #f9fafb !important;
        font-size: 20px !important;
        line-height: 1 !important;
        cursor: pointer !important;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.45) !important;
        pointer-events: auto !important;
    }

    #hion-collapse-sidebar-btn:hover {
        background: #4b5563 !important;
    }

    /* Custom expand button when sidebar is collapsed */
    #hion-expand-sidebar-btn {
        position: fixed !important;
        top: 12px !important;
        left: 12px !important;
        z-index: 999999 !important;
        display: none !important;
        align-items: center !important;
        justify-content: center !important;
        width: 36px !important;
        min-width: 36px !important;
        height: 36px !important;
        min-height: 36px !important;
        margin: 0 !important;
        padding: 0 !important;
        background: #3b4252 !important;
        border: 1px solid #9ca3af !important;
        border-radius: 8px !important;
        color: #f9fafb !important;
        font-size: 20px !important;
        line-height: 1 !important;
        cursor: pointer !important;
        box-shadow: 0 2px 10px rgba(0, 0, 0, 0.45) !important;
    }

    #hion-expand-sidebar-btn:hover {
        background: #4b5563 !important;
    }

    /* Global mobile-friendly tweaks */
    @media (max-width: 768px) {
        .stDataFrame { font-size: 11px; }
        [data-testid="stMetricValue"] { font-size: 18px; }
        [data-testid="stMetricLabel"] { font-size: 11px; }
        .block-container { padding: 0.5rem !important; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

components.html(
    """
    <script>
    (function () {
        const doc = window.parent.document;

        function clickNativeCollapse() {
            const wrap = doc.querySelector("[data-testid='stSidebarCollapseButton']");
            const btn = wrap && wrap.querySelector("button");
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        }

        function clickNativeExpand() {
            const ctrl = doc.querySelector("[data-testid='collapsedControl']");
            const btn = ctrl && ctrl.querySelector("button");
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        }

        function isSidebarOpen() {
            const sidebar = doc.querySelector("section[data-testid='stSidebar']");
            if (!sidebar) return false;
            return sidebar.getBoundingClientRect().width > 80;
        }

        function setupSidebarToggles() {
            const sidebar = doc.querySelector("section[data-testid='stSidebar']");

            const oldBar = doc.getElementById("hion-sidebar-collapse-bar");
            if (oldBar) {
                oldBar.remove();
            }

            let expandBtn = doc.getElementById("hion-expand-sidebar-btn");
            if (!expandBtn) {
                expandBtn = doc.createElement("button");
                expandBtn.id = "hion-expand-sidebar-btn";
                expandBtn.type = "button";
                expandBtn.title = "Expand sidebar";
                expandBtn.setAttribute("aria-label", "Expand sidebar");
                expandBtn.innerHTML = "&#x203A;";
                expandBtn.addEventListener("click", function () {
                    clickNativeExpand();
                });
                doc.body.appendChild(expandBtn);
            }

            let collapseBtn = doc.getElementById("hion-collapse-sidebar-btn");
            if (!collapseBtn) {
                collapseBtn = doc.createElement("button");
                collapseBtn.id = "hion-collapse-sidebar-btn";
                collapseBtn.type = "button";
                collapseBtn.title = "Collapse sidebar";
                collapseBtn.setAttribute("aria-label", "Collapse sidebar");
                collapseBtn.innerHTML = "&#x2039;";
                collapseBtn.addEventListener("click", function () {
                    clickNativeCollapse();
                });
                doc.body.appendChild(collapseBtn);
            }

            const open = isSidebarOpen();
            if (sidebar && open) {
                const rect = sidebar.getBoundingClientRect();
                const inset = 12;
                const btnSize = 36;
                collapseBtn.style.display = "flex";
                collapseBtn.style.top = inset + "px";
                collapseBtn.style.left = Math.max(inset, rect.right - btnSize - inset) + "px";
            } else {
                collapseBtn.style.display = "none";
            }

            expandBtn.style.display = open ? "none" : "flex";
        }

        const observer = new MutationObserver(setupSidebarToggles);
        observer.observe(doc.body, { childList: true, subtree: true });
        setupSidebarToggles();
        setInterval(setupSidebarToggles, 800);
    })();
    </script>
    """,
    height=0,
)

# ============================================================================
# IMPORTS
# ============================================================================
import json
import time
import datetime as dt
import threading
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# Optional dependencies
try:
    from streamlit_autorefresh import st_autorefresh
except ImportError:
    st_autorefresh = None

try:
    import websocket
    WS_AVAILABLE = True
except ImportError:
    WS_AVAILABLE = False
@st.cache_data(ttl=3600)
def get_market_caps():
    """Fetches market cap data for top 250 coins (Refreshes every 1 hour)"""
    try:
        url = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page=1&sparkline=false"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return {coin['symbol'].upper(): coin['market_cap'] for coin in resp.json()}
    except Exception:
        pass
    return {}

def format_market_cap(val):
    """Converts raw number (e.g., 41000000) to clean string (e.g., '41M')"""
    if val >= 1_000_000_000:
        return f"{val/1_000_000_000:.1f}B"
    elif val >= 1_000_000:
        return f"{int(val/1_000_000)}M"
    return "--"

# =============================================================================
# CONFIGURATION & CONSTANTS
# =============================================================================
# CONFIGURATION
# =============================================================================
APP_DIR = Path(__file__).resolve().parent


class Config:
    """Application configuration"""

    COINBASE_BASE = "https://api.exchange.coinbase.com"
    COINBASE_V2 = "https://api.coinbase.com/v2"
    BINANCE_BASE = "https://api.binance.com"
    COINBASE_WS = "wss://ws-feed.exchange.coinbase.com"
    # Exchange feed (matches api.exchange.coinbase.com REST). Advanced Trade uses
    # wss://advanced-trade-ws.coinbase.com with a different message schema.
    # ticker_batch exhausts quickly on free-tier limits (10 subs/product/channel);
    # ticker works and updates on each trade.
    COINBASE_WS_CHANNELS = ("ticker",)

    TIMEFRAMES = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    QUOTES = ["USD", "USDC", "USDT", "BTC", "ETH", "EUR"]
    EXCHANGES = [
        "Coinbase",
        "Binance",
        "Kraken (coming soon)",
        "KuCoin (coming soon)",
    ]

    ALERT_FILE = APP_DIR / "alerted_pairs.json"


CONFIG = Config()

# ============================================================================
# LAYOUT / SIDEBAR CSS
# ============================================================================
st.markdown(
    """
    <style>
    section[data-testid="stSidebar"] {
        padding-top: 0 !important;
    }

    section[data-testid="stSidebar"] > div:first-child {
        height: 100vh !important;
        display: flex !important;
        flex-direction: column !important;
    }

    section[data-testid="stSidebar"] > div:first-child > div:first-child {
        padding: 1rem !important;
        min-width: 360px !important;
        max-width: 520px !important;
        resize: horizontal;
        overflow: auto;
        background: #262730 !important;
    }

    section[data-testid="stSidebar"] * {
        max-width: 100% !important;
    }

    section[data-testid="stSidebar"] .stButton,
    section[data-testid="stSidebar"] .stButton > button,
    section[data-testid="stSidebar"] .stSelectbox,
    section[data-testid="stSidebar"] .stSlider,
    section[data-testid="stSidebar"] .stNumberInput,
    section[data-testid="stSidebar"] .stTextInput,
    section[data-testid="stSidebar"] .stTextArea,
    section[data-testid="stSidebar"] .stRadio,
    section[data-testid="stSidebar"] .stCheckbox {
        width: 100% !important;
    }

    /* Don't stretch custom sidebar toggle buttons */
    section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"],
    #hion-collapse-sidebar-btn,
    #hion-expand-sidebar-btn {
        width: auto !important;
        max-width: none !important;
    }

    [data-testid="stAppViewContainer"] .main {
        max-width: 100vw !important;
    }
    [data-testid="stAppViewContainer"] > .main > div.block-container {
        max-width: 100vw !important;
        padding-left: 12px !important;
        padding-right: 12px !important;
    }

    /* Keep table fully visible — including stale/rerun overlays */
    div[data-testid="stDataFrame"],
    div[data-testid="stDataFrame"] * {
        opacity: 1 !important;
        filter: none !important;
    }

    [data-stale="true"] div[data-testid="stDataFrame"],
    [data-stale="true"] div[data-testid="stDataFrame"] * {
        opacity: 1 !important;
        filter: none !important;
    }

    div[data-testid="stDataEditor"],
    div[data-testid="stDataEditor"] * {
        opacity: 1 !important;
    }

    .row-green {
        background-color: #16a34a !important;
        color: white !important;
        font-weight: 600;
    }
    .row-yellow {
        background-color: #eab308 !important;
        color: black !important;
    }

    @media (max-width: 768px) {
        .stDataFrame { font-size: 11px; }
        [data-testid="stMetricValue"] { font-size: 18px; }
        [data-testid="stMetricLabel"] { font-size: 11px; }
        .block-container { padding: 0.5rem !important; }
        section[data-testid="stSidebar"] > div:first-child > div:first-child {
            min-width: 280px !important;
            max-width: 100% !important;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# =============================================================================
# URL PARAMETER MAPPING
# =============================================================================
URL_PARAM_MAP = {
    "exchange": "ex",
    "quote": "q",
    "pairs_to_discover": "ptd",
    "mode": "md",
    "ws_chunk": "wsc",
    "sort_tf": "tf",
    "sort_desc": "sd",
    "lookback_candles": "lb",
    "min_pct": "mp",
    "min_bars": "mb",
    "use_vol_spike": "vs",
    "vol_mult": "vm",
    "vol_window": "vw",
    "use_rsi": "ur",
    "rsi_len": "rl",
    "min_rsi": "mr",
    "use_macd": "um",
    "macd_fast": "mf",
    "macd_slow": "ms",
    "macd_sig": "mg",
    "min_mhist": "mh",
    "use_atr": "ua",
    "atr_len": "al",
    "min_atr": "ma",
    "use_trend": "ut",
    "pivot_span": "ps",
    "trend_within": "tw",
    "use_roc": "uro",
    "min_roc": "mro",
    "use_macd_cross": "umc",
    "macd_cross_bars": "mcb",
    "macd_cross_only_bull": "mcob",
    "macd_cross_below_zero": "mcbz",
    "macd_hist_confirm_bars": "mhcb",
    "gate_mode": "gm",
    "hard_filter": "hf",
    "K_green": "kg",
    "Y_yellow": "yy",
    "preset": "pr",
    
    "email_to": "et",
    "webhook_url": "wu",
    "font_scale": "fs",
    "refresh_sec": "rs",
    "do_ath": "da",
    "basis": "bs",
    "amount_daily": "ad",
    "amount_hourly": "ah",
    "amount_weekly": "aw",
    "lr_enabled": "lre",
    "lr_watch_coinbase": "lrwc",
    "lr_watch_binance": "lrwb",
    "lr_watch_quotes": "lrwq",
    "lr_poll_sec": "lrps",
    "lr_upcoming_window_h": "lruwh",
    "lr_feeds": "lrf",
    "use_watch": "uw",
    "use_my_pairs": "ump",
    "watchlist": "wl",
    "my_pairs": "myp",
}


def save_to_url(key: str, value):
    try:
        param_name = URL_PARAM_MAP.get(key, key)
        st.query_params[param_name] = str(value)
    except Exception:
        pass


def load_from_url(key: str, default_value, value_type=str):
    try:
        param_name = URL_PARAM_MAP.get(key, key)
        qv = st.query_params.get(param_name)
        if qv is not None:
            if value_type == bool:
                return qv.lower() in ("true", "1", "yes", "on")
            elif value_type == int:
                return int(qv)
            elif value_type == float:
                return float(qv)
            else:
                return qv
    except Exception:
        pass
    return default_value


# =============================================================================
# ALERT FILE MANAGEMENT
# =============================================================================
def load_alerted_pairs() -> dict:
    try:
        if CONFIG.ALERT_FILE.exists():
            with open(CONFIG.ALERT_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_alerted_pairs(pairs: dict):
    try:
        with open(CONFIG.ALERT_FILE, "w") as f:
            json.dump(pairs, f)
    except Exception:
        pass


def clear_alerted_pairs():
    try:
        if CONFIG.ALERT_FILE.exists():
            CONFIG.ALERT_FILE.unlink()
    except Exception:
        pass


USER_SETTINGS_FILE = Path(__file__).resolve().parent / "user_settings.json"
NOTIFICATION_SETTING_KEYS = ("email_to", "webhook_url")


def load_user_settings() -> dict:
    try:
        if USER_SETTINGS_FILE.exists():
            with open(USER_SETTINGS_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception:
        pass
    return {}


def save_user_settings() -> None:
    try:
        settings = {
            key: st.session_state.get(key, "")
            for key in NOTIFICATION_SETTING_KEYS
        }
        with open(USER_SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass


NOTIFICATION_MSG_DURATION_SEC = 2.5


def _set_notification_save_msg(msg_key: str, until_key: str, snapshot_key: str, value: str, message: str):
    st.session_state[msg_key] = message
    st.session_state[until_key] = time.time() + NOTIFICATION_MSG_DURATION_SEC
    st.session_state[snapshot_key] = value


def _clear_notification_save_msg_if_expired(msg_key: str, until_key: str):
    until = st.session_state.get(until_key)
    if until and time.time() >= until:
        st.session_state.pop(msg_key, None)
        st.session_state.pop(until_key, None)


def _render_notification_save_msg(msg_key: str, until_key: str):
    _clear_notification_save_msg_if_expired(msg_key, until_key)
    if st.session_state.get(msg_key):
        st.success(st.session_state[msg_key])


def _schedule_notification_msg_dismiss():
    deadlines = []
    for until_key in ("email_save_msg_until", "webhook_save_msg_until"):
        until = st.session_state.get(until_key)
        if until and time.time() < until:
            deadlines.append(until)
    if not deadlines:
        return

    remaining_ms = int((min(deadlines) - time.time()) * 1000)
    remaining_ms = max(500, remaining_ms)

    if st_autorefresh:
        st_autorefresh(interval=remaining_ms, limit=1, key="notification_msg_dismiss")

    components.html(
        f"""
        <script>
        (function () {{
            const doc = window.parent.document;
            setTimeout(function () {{
                const sidebar = doc.querySelector("section[data-testid='stSidebar']");
                if (!sidebar) return;
                sidebar.querySelectorAll('[data-testid="stAlert"]').forEach(function (el) {{
                    if (el.textContent.indexOf("will persist after closing") !== -1) {{
                        el.style.transition = "opacity 0.4s ease";
                        el.style.opacity = "0";
                        setTimeout(function () {{ el.style.display = "none"; }}, 400);
                    }}
                }});
            }}, {remaining_ms});
        }})();
        </script>
        """,
        height=0,
    )


def on_email_saved():
    email = (st.session_state.get("email_to") or "").strip()
    st.session_state.pop("email_save_msg", None)
    st.session_state.pop("email_save_msg_until", None)
    if not email:
        return
    save_to_url("email_to", email)
    save_user_settings()
    _set_notification_save_msg(
        "email_save_msg",
        "email_save_msg_until",
        "email_saved_snapshot",
        email,
        "✓ Email saved - will persist after closing",
    )


def on_webhook_saved():
    webhook = (st.session_state.get("webhook_url") or "").strip()
    st.session_state.pop("webhook_save_msg", None)
    st.session_state.pop("webhook_save_msg_until", None)
    if not webhook:
        return
    save_to_url("webhook_url", webhook)
    save_user_settings()
    _set_notification_save_msg(
        "webhook_save_msg",
        "webhook_save_msg_until",
        "webhook_saved_snapshot",
        webhook,
        "✓ Webhook saved - will persist after closing",
    )


def clear_notification_save_msgs_if_edited():
    if st.session_state.get("email_save_msg"):
        current = (st.session_state.get("email_to") or "").strip()
        if current != st.session_state.get("email_saved_snapshot", ""):
            st.session_state.pop("email_save_msg", None)
            st.session_state.pop("email_save_msg_until", None)
    if st.session_state.get("webhook_save_msg"):
        current = (st.session_state.get("webhook_url") or "").strip()
        if current != st.session_state.get("webhook_saved_snapshot", ""):
            st.session_state.pop("webhook_save_msg", None)
            st.session_state.pop("webhook_save_msg_until", None)


# =============================================================================
# STATE MANAGEMENT
# =============================================================================
def init_session_state():
    if "_initialized" not in st.session_state:
        st.session_state["_initialized"] = True

    defaults = {
        "exchange": "Coinbase",
        "quote": "USD",
        "pairs_to_discover": 400,
        "mode": "REST only",
        "ws_chunk": 100,
        "sort_tf": "1h",
        "sort_desc": True,
        "min_bars": 3,
        "lookback_candles": 3,
        "min_pct": 15.0,
        "use_vol_spike": True,
        "vol_mult": 4.0,
        "vol_window": 20,
        "use_rsi": False,
        "rsi_len": 14,
        "min_rsi": 55,
        "use_macd": False,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_sig": 9,
        "min_mhist": 0.0,
        "use_atr": False,
        "atr_len": 14,
        "min_atr": 0.5,
        "use_trend": False,
        "pivot_span": 4,
        "trend_within": 48,
        "use_roc": True,
        "min_roc": 10.0,
        "use_macd_cross": False,
        "macd_cross_bars": 5,
        "macd_cross_only_bull": True,
        "macd_cross_below_zero": True,
        "macd_hist_confirm_bars": 3,
        "gate_mode": "ANY",
        "hard_filter": False,
        "K_green": 3,
        "Y_yellow": 2,
        "preset": "None",
        
        "email_to": "",
        "webhook_url": "",
        "font_scale": 1.0,
        "refresh_sec": 30,
        "do_ath": False,
        "basis": "Daily",
        "amount_daily": 90,
        "amount_hourly": 24,
        "amount_weekly": 12,
        "collapse_all": False,
        "use_watch": False,
        "use_my_pairs": False,
        "watchlist": "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD",
        "my_pairs": "",
        "ws_thread": None,
        "ws_alive": False,
        "ws_prices": {},
        "ws_stop": False,
        "ws_runtime": {
            "connected": False,
            "connecting": False,
            "last_msg": 0.0,
            "error": None,
            "subscribed": 0,
            "connection_count": 0,
            "chunk_status": {},
        },
        "lr_enabled": False,
        "lr_baselines": {},
        "lr_events": [],
        "lr_unacked": 0,
        "lr_last_poll": 0.0,
        "lr_feed_hashes": {},
        "lr_watch_coinbase": True,
        "lr_watch_binance": True,
        "lr_watch_quotes": "USD, USDT, USDC",
        "lr_poll_sec": 30,
        "lr_upcoming_window_h": 48,
        "lr_feeds": "",
    }

    saved_settings = load_user_settings()

    for key, default in defaults.items():
        if key not in st.session_state:
            initial = default
            if key in NOTIFICATION_SETTING_KEYS and saved_settings.get(key):
                initial = saved_settings[key]
            st.session_state[key] = load_from_url(key, initial, type(initial))


init_session_state()


# =============================================================================
# SCAN / EXCHANGE HELPERS (read live session_state — safe inside fragments)
# =============================================================================
def get_effective_exchange() -> str:
    exchange = st.session_state.get("exchange", "Coinbase")
    return "Coinbase" if "coming soon" in exchange.lower() else exchange


def build_gate_settings() -> dict:
    return {
        "lookback_candles": int(st.session_state.get("lookback_candles", 3)),
        "min_pct": float(st.session_state.get("min_pct", 3.0)),
        "use_vol_spike": bool(st.session_state.get("use_vol_spike", False)),
        "vol_mult": float(st.session_state.get("vol_mult", 1.10)),
        "vol_window": int(st.session_state.get("vol_window", 20)),
        "use_rsi": bool(st.session_state.get("use_rsi", False)),
        "rsi_len": int(st.session_state.get("rsi_len", 14)),
        "min_rsi": int(st.session_state.get("min_rsi", 55)),
        "use_macd": bool(st.session_state.get("use_macd", False)),
        "macd_fast": int(st.session_state.get("macd_fast", 12)),
        "macd_slow": int(st.session_state.get("macd_slow", 26)),
        "macd_sig": int(st.session_state.get("macd_sig", 9)),
        "min_mhist": float(st.session_state.get("min_mhist", 0.0)),
        "use_atr": bool(st.session_state.get("use_atr", False)),
        "atr_len": int(st.session_state.get("atr_len", 14)),
        "min_atr": float(st.session_state.get("min_atr", 0.5)),
        "use_trend": bool(st.session_state.get("use_trend", False)),
        "pivot_span": int(st.session_state.get("pivot_span", 4)),
        "trend_within": int(st.session_state.get("trend_within", 48)),
        "use_roc": bool(st.session_state.get("use_roc", False)),
        "min_roc": float(st.session_state.get("min_roc", 1.0)),
        "use_macd_cross": bool(st.session_state.get("use_macd_cross", False)),
        "macd_cross_bars": int(st.session_state.get("macd_cross_bars", 5)),
        "macd_cross_only_bull": bool(st.session_state.get("macd_cross_only_bull", True)),
        "macd_cross_below_zero": bool(st.session_state.get("macd_cross_below_zero", True)),
        "macd_hist_confirm_bars": int(st.session_state.get("macd_hist_confirm_bars", 3)),
    }


def build_scan_pairs() -> list:
    if st.session_state.get("use_my_pairs", False):
        pairs = [
            p.strip().upper()
            for p in st.session_state.get("my_pairs", "").split(",")
            if p.strip()
        ]
    elif st.session_state.get("use_watch", False):
        pairs = [
            p.strip().upper()
            for p in st.session_state.get("watchlist", "").split(",")
            if p.strip()
        ]
    else:
        pairs = get_products(get_effective_exchange(), st.session_state.get("quote", "USD"))

    cap = max(5, min(500, int(st.session_state.get("pairs_to_discover", 400))))
    pairs = pairs[:cap]

    if st.session_state.get("mc_filter_enabled"):
        mc_data = get_market_caps()
        min_mc = st.session_state.get("min_market_cap_millions", 10) * 1_000_000

        def normalize_symbol(pair: str) -> str:
            return pair.split("-")[0].upper()

        pairs = [p for p in pairs if mc_data.get(normalize_symbol(p), 0) >= min_mc]

    return pairs


def migrate_lr_baselines() -> None:
    if "lr_baselines" not in st.session_state:
        st.session_state["lr_baselines"] = {}
    legacy = st.session_state.get("lr_baseline")
    if legacy and not st.session_state["lr_baselines"]:
        for name, products in legacy.items():
            st.session_state["lr_baselines"][name] = (
                set(products) if not isinstance(products, set) else products
            )


def run_listing_radar_poll(force: bool = False) -> None:
    if not st.session_state.get("lr_enabled", False):
        return

    migrate_lr_baselines()
    interval = int(st.session_state.get("lr_poll_sec", 30))
    last_poll = float(st.session_state.get("lr_last_poll", 0.0))
    if not force and (time.time() - last_poll) < interval:
        return

    st.session_state["lr_last_poll"] = time.time()
    lr_quotes = [
        q.strip().upper()
        for q in st.session_state.get("lr_watch_quotes", "USD,USDT,USDC").split(",")
        if q.strip()
    ]

    for exchange_name in ["Coinbase", "Binance"]:
        watch_key = f"lr_watch_{exchange_name.lower()}"
        if not st.session_state.get(watch_key, True):
            continue
        for quote in lr_quotes:
            try:
                current_products = get_products(exchange_name, quote)
                known = st.session_state["lr_baselines"].get(exchange_name, set())
                if not known:
                    st.session_state["lr_baselines"][exchange_name] = set(current_products)
                    continue

                new_listings = [p for p in current_products if p not in known]
                if new_listings:
                    if "lr_events" not in st.session_state:
                        st.session_state["lr_events"] = []
                    for pair in new_listings:
                        st.session_state["lr_events"].append({
                            "pair": pair,
                            "exchange": exchange_name,
                            "quote": quote,
                            "detected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                            "type": "listing",
                        })

                st.session_state["lr_baselines"][exchange_name] = set(current_products)
            except Exception:
                pass

    feeds_raw = (st.session_state.get("lr_feeds") or "").strip()
    if feeds_raw:
        feed_hashes = st.session_state.setdefault("lr_feed_hashes", {})
        for url in feeds_raw.splitlines():
            url = url.strip()
            if not url:
                continue
            try:
                resp = requests.get(url, timeout=12, headers={"User-Agent": "crypto-tracker/2.0"})
                if resp.status_code != 200:
                    continue
                snippet = resp.text[:8000]
                content_hash = str(hash(snippet))
                prev = feed_hashes.get(url)
                if prev is not None and prev != content_hash:
                    if "lr_events" not in st.session_state:
                        st.session_state["lr_events"] = []
                    st.session_state["lr_events"].append({
                        "pair": url,
                        "exchange": "Feed",
                        "quote": "",
                        "detected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "type": "feed",
                    })
                feed_hashes[url] = content_hash
            except Exception:
                pass


# =============================================================================
# TECHNICAL INDICATORS
# =============================================================================
def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype("float64").ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    up = np.where(delta > 0, delta, 0.0)
    dn = np.where(delta < 0, -delta, 0.0)

    ru = pd.Series(up, index=close.index).ewm(alpha=1 / length, adjust=False).mean()
    rd = pd.Series(dn, index=close.index).ewm(alpha=1 / length, adjust=False).mean()

    rs = ru / (rd + 1e-12)
    return 100 - 100 / (1 + rs)


def macd_core(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def volume_spike(df: pd.DataFrame, window: int = 20) -> float:
    if len(df) < window + 1:
        return np.nan

    current_vol = df["volume"].iloc[-1]
    avg_vol = df["volume"].rolling(window).mean().iloc[-1]
    return float(current_vol / (avg_vol + 1e-12))


def find_pivots(close: pd.Series, span: int = 3) -> Tuple[List[int], List[int]]:
    n = len(close)
    highs, lows = [], []
    values = close.values

    for i in range(span, n - span):
        if (values[i] > values[i - span : i].max()) and (
            values[i] > values[i + 1 : i + 1 + span].max()
        ):
            highs.append(i)

        if (values[i] < values[i - span : i].min()) and (
            values[i] < values[i + 1 : i + 1 + span].min()
        ):
            lows.append(i)

    return highs, lows


def trend_breakout_up(df: pd.DataFrame, span: int = 3, within_bars: int = 48) -> bool:
    if df is None or len(df) < span * 2 + 5:
        return False

    highs, _ = find_pivots(df["close"], span)
    if not highs:
        return False

    latest_high_idx = highs[-1]
    resistance_level = float(df["close"].iloc[latest_high_idx])

    for i in range(latest_high_idx + 1, len(df)):
        if float(df["close"].iloc[i]) > resistance_level:
            bars_since_breakout = len(df) - 1 - i
            return bars_since_breakout <= within_bars

    return False


# =============================================================================
# DATA FETCHING
# =============================================================================
REST_MIN_GAP_SEC = 0.12  # ~8 req/s — stays under Coinbase public limits
_REST_LOCK = threading.Lock()
_LAST_REST_AT = 0.0
_REST_BACKOFF_UNTIL = 0.0


def _rest_throttle() -> None:
    global _LAST_REST_AT, _REST_BACKOFF_UNTIL
    with _REST_LOCK:
        now = time.time()
        if now < _REST_BACKOFF_UNTIL:
            time.sleep(_REST_BACKOFF_UNTIL - now)
            now = time.time()
        gap = REST_MIN_GAP_SEC - (now - _LAST_REST_AT)
        if gap > 0:
            time.sleep(gap)
        _LAST_REST_AT = time.time()


def _rest_backoff(seconds: float) -> None:
    global _REST_BACKOFF_UNTIL
    with _REST_LOCK:
        _REST_BACKOFF_UNTIL = max(_REST_BACKOFF_UNTIL, time.time() + seconds)


def get_bars_limit(timeframe: str) -> int:
    limits = {"5m": 120, "15m": 96, "1h": 48, "4h": 24, "1d": 30}
    return limits.get(timeframe, 48)


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate OHLCV bars (e.g. build 4h candles from 1h — Coinbase has no native 4h feed)."""
    if df is None or df.empty:
        return df
    indexed = df.set_index("time")
    resampled = indexed.resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    resampled = resampled.dropna(subset=["open", "close"]).reset_index()
    return resampled[["time", "open", "high", "low", "close", "volume"]]


def _fetch_coinbase_candles_raw(
    pair: str, granularity_seconds: int, limit: int,
) -> Optional[pd.DataFrame]:
    url = f"{CONFIG.COINBASE_BASE}/products/{pair}/candles"
    params = {"granularity": granularity_seconds}
    headers = {"User-Agent": "crypto-tracker/2.0", "Accept": "application/json"}

    for attempt in range(3):
        try:
            _rest_throttle()
            response = requests.get(url, params=params, headers=headers, timeout=15)

            if response.status_code == 200:
                data = response.json()
                if not data:
                    return None

                df = pd.DataFrame(
                    data, columns=["time", "low", "high", "open", "close", "volume"]
                )
                df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
                df = df.sort_values("time").reset_index(drop=True)
                df = df[["time", "open", "high", "low", "close", "volume"]]

                if len(df) > limit:
                    df = df.iloc[-limit:].reset_index(drop=True)

                return df if not df.empty else None

            elif response.status_code in (429, 500, 502, 503, 504):
                _rest_backoff(1.5 * (attempt + 1))
                time.sleep(0.6 * (attempt + 1))
                continue
            else:
                return None

        except Exception:
            time.sleep(0.4 * (attempt + 1))

    return None


def fetch_coinbase_data(pair: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
    # Coinbase Exchange candles: 60, 300, 900, 3600, 21600, 86400 — NOT 14400 (4h).
    if timeframe == "4h":
        hour_limit = min(300, max(limit * 4 + 8, 24))
        df_1h = _fetch_coinbase_candles_raw(pair, 3600, hour_limit)
        if df_1h is None or len(df_1h) < 4:
            return None
        df = resample_ohlcv(df_1h, "4h")
        if df is None or df.empty:
            return None
        if len(df) > limit:
            df = df.iloc[-limit:].reset_index(drop=True)
        return df

    tf_seconds = CONFIG.TIMEFRAMES.get(timeframe)
    if not tf_seconds:
        return None

    return _fetch_coinbase_candles_raw(pair, tf_seconds, limit)


def fetch_binance_data(pair: str, timeframe: str, limit: int) -> Optional[pd.DataFrame]:
    url = f"{CONFIG.BINANCE_BASE}/api/v3/klines"

    try:
        base, quote = pair.split("-")
        symbol = f"{base}{quote}"
    except ValueError:
        return None

    interval_map = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"}
    interval = interval_map.get(timeframe, "1h")
    params = {"symbol": symbol, "interval": interval, "limit": max(50, limit)}

    try:
        _rest_throttle()
        response = requests.get(url, params=params, timeout=20)

        if response.status_code != 200:
            if response.status_code == 429:
                _rest_backoff(2.0)
            return None

        raw = response.json()
        if not raw or not isinstance(raw, list):
            return None

        rows = []
        for kline in raw:
            rows.append(
                {
                    "time": pd.to_datetime(kline[0], unit="ms", utc=True),
                    "open": float(kline[1]),
                    "high": float(kline[2]),
                    "low": float(kline[3]),
                    "close": float(kline[4]),
                    "volume": float(kline[5]),
                }
            )

        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        df = df[["time", "open", "high", "low", "close", "volume"]]

        if len(df) > limit:
            df = df.iloc[-limit:].reset_index(drop=True)

        return df if not df.empty else None

    except Exception:
        return None


def fetch_data(
    exchange: str, pair: str, timeframe: str, limit: Optional[int] = None
) -> Optional[pd.DataFrame]:
    if limit is None:
        limit = get_bars_limit(timeframe)

    limit = max(1, min(300, limit))
    exchange_lower = exchange.lower()

    if exchange_lower.startswith("coinbase"):
        return fetch_coinbase_data(pair, timeframe, limit)
    elif exchange_lower.startswith("binance"):
        return fetch_binance_data(pair, timeframe, limit)
    else:
        return fetch_coinbase_data(pair, timeframe, limit)


# Bump when fetch logic changes (e.g. Coinbase 4h built from 1h candles).
_FETCH_CACHE_REV = 5
# =============================================================================
# CACHING
# =============================================================================
@st.cache_data(show_spinner=False, ttl=300)
def get_cached_data(
    exchange: str,
    pair: str,
    timeframe: str,
    refresh_sec: int,
    cache_rev: int,
) -> Optional[pd.DataFrame]:
    try:
        limit = get_bars_limit(timeframe)
        return fetch_data(exchange, pair, timeframe, limit)
    except Exception:
        return None


def fetch_pair_data(exchange: str, pair: str, timeframe: str) -> Optional[pd.DataFrame]:
    refresh_sec = int(st.session_state.get("refresh_sec", 30))
    return get_cached_data(
        exchange, pair, timeframe, refresh_sec, _FETCH_CACHE_REV,
    )


def check_alert_strategy(df, mode, min_pct=20.0):
    if df is None or len(df) < 10:
        return False

    exp1 = df["close"].ewm(span=12, adjust=False).mean()
    exp2 = df["close"].ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal

    cross_bars_ago = 999
    for i in range(1, 6):
        if macd.iloc[-i] > signal.iloc[-i] and macd.iloc[-i - 1] <= signal.iloc[-i - 1]:
            if macd.iloc[-i] < 0:
                cross_bars_ago = i
                break

    if cross_bars_ago > 5:
        return False

    stage1 = True
    stage2 = hist.iloc[-1] > 0

    recent_low = df["close"].iloc[-5:].min()
    pct_move = ((df["close"].iloc[-1] - recent_low) / recent_low) * 100
    stage3 = pct_move >= min_pct

    if mode == "Aggressive":
        return stage1
    elif mode == "Balanced":
        return stage1 and stage2
    elif mode == "Conservative":
        return stage1 and stage2 and stage3
    else:
        return False


# =============================================================================
# PRODUCT LISTING
# =============================================================================
def get_coinbase_products(quote: str) -> List[str]:
    try:
        response = requests.get(f"{CONFIG.COINBASE_BASE}/products", timeout=25)
        response.raise_for_status()

        products = []
        for product in response.json():
            if (
                product.get("quote_currency") == quote.upper()
                and product.get("status") == "online"
                and not product.get("trading_disabled", False)
                and not product.get("cancel_only", False)
            ):
                pair = f"{product['base_currency']}-{product['quote_currency']}"
                products.append(pair)

        return sorted(products)
    except Exception:
        return []


def get_binance_products(quote: str) -> List[str]:
    url = f"{CONFIG.BINANCE_BASE}/api/v3/exchangeInfo"
    quote_upper = quote.upper()

    try:
        response = requests.get(url, timeout=25)

        if response.status_code != 200:
            return []

        data = response.json()
        if not data:
            return []

        all_symbols = data.get("symbols", [])
        if not all_symbols:
            return []

        products = []
        for symbol in all_symbols:
            if symbol.get("status") == "TRADING" and symbol.get("quoteAsset") == quote_upper:
                pair = f"{symbol['baseAsset']}-{quote_upper}"
                products.append(pair)

        return sorted(products)
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def get_products(exchange: str, quote: str) -> List[str]:
    exchange_lower = exchange.lower()

    if exchange_lower.startswith("coinbase"):
        return get_coinbase_products(quote)
    elif exchange_lower.startswith("binance"):
        return get_binance_products(quote)
    else:
        return get_coinbase_products(quote)


# =============================================================================
# PROGRESSIVE ALERT CHECKING
# =============================================================================
def check_progressive_stages(df: pd.DataFrame, settings: dict) -> Dict[str, Any]:
    result = {
        "stage1_met": False,
        "stage1_bars_ago": None,
        "stage2_met": False,
        "stage2_bars_ago": None,
        "stage3_met": False,
        "current_pct": 0.0,
    }

    if df is None or len(df) < 10:
        return result

    macd_line, signal_line, hist = macd_core(
        df["close"],
        settings.get("macd_fast", 12),
        settings.get("macd_slow", 26),
        settings.get("macd_sig", 9),
    )

    bars_to_check = settings.get("macd_cross_bars", 5)
    for i in range(1, min(bars_to_check + 1, len(hist))):
        prev_diff = macd_line.iloc[-i - 1] - signal_line.iloc[-i - 1]
        curr_diff = macd_line.iloc[-i] - signal_line.iloc[-i]

        if prev_diff < 0 and curr_diff > 0:
            if macd_line.iloc[-i] < 0 and signal_line.iloc[-i] < 0:
                result["stage1_met"] = True
                result["stage1_bars_ago"] = i
                break

    hist_confirm = settings.get("macd_hist_confirm_bars", 3)
    for i in range(0, min(hist_confirm, len(hist))):
        if hist.iloc[-(i + 1)] > 0:
            result["stage2_met"] = True
            result["stage2_bars_ago"] = i
            break

    lookback = max(1, min(settings.get("lookback_candles", 3), 50, len(df) - 1))
    current_close = float(df["close"].iloc[-1])
    # Calculate the index for 'lookback' bars ago
    # iloc[-1] is current, so -(lookback + 1) gets the candle lookback days ago
    start_index = -(lookback + 1)

    # Safety check to ensure the index exists in the dataframe
    if abs(start_index) > len(df):
        start_index = -(len(df))

    # Get the LOW price of that specific candle
    start_price = float(df["low"].iloc[start_index])

    # Calculate % change from that Low price to current Close
    delta_pct = ((current_close - start_price) / start_price) * 100.0
    result["current_pct"] = delta_pct
    result["stage3_met"] = delta_pct >= settings.get("min_pct", 3.0)

    return result


def format_alert_stage(pair: str, alert_type: str, rel_vol: float) -> Optional[str]:
    """Apply MACD cross-sync filter; return None to suppress delivery."""
    if st.session_state.get("macd_cross_sync") and "MACD" in str(alert_type):
        tf = st.session_state.get("sort_tf", "1h")
        vol_req = float(st.session_state.get("spike_multiple", 3.5))
        if tf not in ("4h", "1d", "1D", "Daily") or rel_vol < vol_req:
            return None
        return f"{pair} | {tf}"
    return alert_type


def dispatch_scan_alerts(alerts_to_send: List[dict], scan_id: float) -> None:
    """One email + one webhook per scan cycle (no duplicate sends on fragment reruns)."""
    if not alerts_to_send:
        return
    if st.session_state.get("_alerts_sent_scan_id") == scan_id:
        return

    sent = False
    if st.session_state.get("email_to"):
        ok, _ = send_email_alert(alerts_to_send)
        sent = sent or ok
    if st.session_state.get("webhook_url"):
        ok, _ = send_webhook_alert(alerts_to_send)
        sent = sent or ok

    if sent or alerts_to_send:
        st.session_state["_alerts_sent_scan_id"] = scan_id


def should_send_alert(pair, delta_pct, rel_volume, alerted_pairs, use_vol_spike=False):
    """Dynamic price-ladder alert logic (delta + optional volume gate)."""
    base_delta = float(st.session_state.get("min_pct", 0.0))
    base_volume = float(st.session_state.get("vol_mult", 1.10))
    delta_step = 5.0

    delta_ok = delta_pct >= base_delta
    volume_ok = True
    if use_vol_spike:
        volume_ok = rel_volume >= base_volume

    if not (delta_ok and volume_ok):
        if pair in alerted_pairs:
            alerted_pairs.pop(pair, None)
        return False, None

    pair_state = alerted_pairs.get(pair)
    if not pair_state:
        alerted_pairs[pair] = {"last_alerted_delta": float(delta_pct)}
        return True, f"initial_{delta_pct:.2f}"

    last_alerted_delta = float(pair_state.get("last_alerted_delta", base_delta))
    if delta_pct >= last_alerted_delta + delta_step:
        alerted_pairs[pair]["last_alerted_delta"] = float(delta_pct)
        return True, f"delta_{delta_pct:.2f}"

    return False, None


# =============================================================================
# ALERT SENDING (batch only — one email/webhook per scan)
# =============================================================================
def send_email_alert(pairs_data: List[dict]) -> Tuple[bool, str]:
    try:
        smtp_host = st.secrets.get("email", {}).get("smtp_host", "smtp.gmail.com")
        smtp_port = int(st.secrets.get("email", {}).get("smtp_port", 587))
        sender_email = st.secrets.get("email", {}).get("sender_email")
        sender_password = st.secrets.get("email", {}).get("sender_password")
        recipient = st.session_state.get("email_to", "")

        if not all([sender_email, sender_password, recipient]):
            return False, "Email not configured"

        subject = f"🚀 {len(pairs_data)} Alert{'s' if len(pairs_data) > 1 else ''}"

        body_parts = []
        for data in pairs_data:
            body_parts.append(
                f"""
{data['pair']} - {data['stage']}
Price: ${data['price']:.6f}
Change: {data['pct']:+.2f}%
Timeframe: {data['timeframe']}
Exchange: {data['exchange']}
Signal: {data['signal']}
"""
            )

        body = "\n---\n".join(body_parts)
        body += "\n\n📌 Note: Re-alerts require ≥5% price increase from previous alert"
        body += f"\n\nTimestamp: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
        body += "\n\nhioncrypto's Crypto Tracker"

        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)

        return True, ""
    except Exception as e:
        return False, str(e)


def send_webhook_alert(pairs_data: List[dict]) -> Tuple[bool, str]:
    try:
        webhook_url = st.session_state.get("webhook_url", "")
        if not webhook_url:
            return False, "Webhook URL not set"

        payload = {
            "alerts": pairs_data,
            "count": len(pairs_data),
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        }

        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )

        if response.status_code not in [200, 201, 202, 204]:
            return False, f"HTTP {response.status_code}"

        return True, ""
    except Exception as e:
        return False, str(e)


# =============================================================================
# GATE EVALUATION
# =============================================================================
def check_macd_cross(
    macd_line: pd.Series,
    signal_line: pd.Series,
    hist: pd.Series,
    settings: dict,
) -> Tuple[bool, Optional[int]]:
    bars_to_check = settings.get("macd_cross_bars", 5)
    only_bull = settings.get("macd_cross_only_bull", True)
    need_below = settings.get("macd_cross_below_zero", True)
    confirm_bars = settings.get("macd_hist_confirm_bars", 3)

    for i in range(1, min(bars_to_check + 1, len(hist))):
        prev_diff = macd_line.iloc[-i - 1] - signal_line.iloc[-i - 1]
        curr_diff = macd_line.iloc[-i] - signal_line.iloc[-i]

        crossed_up = prev_diff < 0 and curr_diff > 0
        crossed_down = prev_diff > 0 and curr_diff < 0

        if only_bull and not crossed_up:
            continue
        if not only_bull and not (crossed_up or crossed_down):
            continue

        if need_below and (macd_line.iloc[-i] > 0 or signal_line.iloc[-i] > 0):
            continue

        if confirm_bars > 0:
            conf_start = max(0, len(hist) - i)
            conf_end = min(len(hist), conf_start + confirm_bars)
            has_positive_hist = any(hist.iloc[j] > 0 for j in range(conf_start, conf_end))
            if not has_positive_hist:
                continue

        return True, i

    return False, None


def evaluate_gates(df: pd.DataFrame, settings: dict) -> Tuple[dict, int, str, int]:
    n = len(df)
    lookback = max(1, min(settings.get("lookback_candles", 3), 50, n - 1))

    current_close = float(df["close"].iloc[-1])

    if lookback > 0 and n > 1:
        window = df.iloc[-(lookback + 1):-1]
        start_price = float(window["low"].min()) if len(window) else float(df["low"].iloc[-2])
    else:
        start_price = float(df["low"].iloc[-1])

    delta_pct = ((current_close - start_price) / start_price) * 100.0
    macd_line, signal_line, hist = macd_core(
        df["close"],
        settings.get("macd_fast", 12),
        settings.get("macd_slow", 26),
        settings.get("macd_sig", 9),
    )

    gates_passed = 0
    gates_enabled = 0
    gate_chips = []

    # Δ gate (always on)
    delta_threshold = float(st.session_state.get("min_pct", 0.0))
    delta_pass = pd.notna(delta_pct) and delta_pct >= delta_threshold
    gates_passed += int(delta_pass)
    gates_enabled += 1
    gate_chips.append(f"Δ{'✅' if delta_pass else '❌'}({delta_pct:+.2f}%)")

    # Volume spike gate
    if settings.get("use_vol_spike", True):
        vol_spike_ratio = volume_spike(df, settings.get("vol_window", 20))
        vol_pass = (
            pd.notna(vol_spike_ratio)
            and vol_spike_ratio >= settings.get("vol_mult", 4.0)
        )
        gates_passed += int(vol_pass)
        gates_enabled += 1
        vol_display = f"({vol_spike_ratio:.2f}×)" if pd.notna(vol_spike_ratio) else "(N/A)"
        gate_chips.append(f" V{'✅' if vol_pass else '❌'}{vol_display}")
    else:
        gate_chips.append(" V–")

    # RSI gate
    if settings.get("use_rsi", False):
        rsi_values = rsi(df["close"], settings.get("rsi_len", 14))
        current_rsi = float(rsi_values.iloc[-1])
        rsi_pass = current_rsi >= settings.get("min_rsi", 55)
        gates_passed += int(rsi_pass)
        gates_enabled += 1
        gate_chips.append(f" S{'✅' if rsi_pass else '❌'}({current_rsi:.1f})")
    else:
        gate_chips.append(" S–")

    # MACD hist gate
    if settings.get("use_macd", False):
        macd_hist = float(hist.iloc[-1])
        macd_pass = macd_hist >= settings.get("min_mhist", 0.0)
        gates_passed += int(macd_pass)
        gates_enabled += 1
        gate_chips.append(f" M{'✅' if macd_pass else '❌'}({macd_hist:.3f})")
    else:
        gate_chips.append(" M–")

    # ATR gate
    if settings.get("use_atr", False):
        high_low = df["high"] - df["low"]
        high_close = abs(df["high"] - df["close"].shift())
        low_close = abs(df["low"] - df["close"].shift())
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr_values = true_range.rolling(window=settings.get("atr_len", 14)).mean()

        current_atr = float(atr_values.iloc[-1]) if not atr_values.empty else 0
        atr_pct = (current_atr / current_close * 100) if current_close > 0 else 0
        atr_pass = atr_pct >= settings.get("min_atr", 0.5)
        gates_passed += int(atr_pass)
        gates_enabled += 1
        gate_chips.append(f" A{'✅' if atr_pass else '❌'}({atr_pct:.2f}%)")
    else:
        gate_chips.append(" A–")

    # Trend breakout gate
    if settings.get("use_trend", False):
        trend_pass = trend_breakout_up(
            df, settings.get("pivot_span", 4), settings.get("trend_within", 48)
        )
        gates_passed += int(trend_pass)
        gates_enabled += 1
        gate_chips.append(f" T{'✅' if trend_pass else '❌'}")
    else:
        gate_chips.append(" T–")

    # ROC gate
    if settings.get("use_roc", True):
        if lookback > 1:
            ref_close = float(df["close"].iloc[-(lookback - 1)])
        else:
            ref_close = float(df["close"].iloc[-1])
        roc = ((current_close / ref_close) - 1.0) * 100.0 if n > lookback else np.nan
        roc_pass = pd.notna(roc) and roc >= settings.get("min_roc", 1.0)
        gates_passed += int(roc_pass)
        gates_enabled += 1
        roc_display = f"({roc:+.2f}%)" if pd.notna(roc) else "(N/A)"
        gate_chips.append(f" R{'✅' if roc_pass else '❌'}{roc_display}")
    else:
        gate_chips.append(" R–")

    # MACD cross gate
    cross_info = {"ok": False, "bars_ago": None}
    if settings.get("use_macd_cross", False):
        cross_pass, bars_ago = check_macd_cross(macd_line, signal_line, hist, settings)
        cross_info.update({"ok": cross_pass, "bars_ago": bars_ago})
        gates_passed += int(cross_pass)
        gates_enabled += 1
        cross_display = f" ({bars_ago} bars ago)" if bars_ago is not None else ""
        gate_chips.append(f" C{'✅' if cross_pass else '❌'}{cross_display}")
    else:
        gate_chips.append(" C–")

    metadata = {"delta_pct": delta_pct, "macd_cross": cross_info}
    return metadata, gates_passed, " ".join(gate_chips), gates_enabled


# =============================================================================
# SIDEBAR CONTROLS
# =============================================================================
def expander(title: str):
    expanded = not st.session_state.get("collapse_all", False)
    return st.sidebar.expander(title, expanded=expanded)


with st.sidebar:
    st.title("🚀 Crypto Tracker")

    c1, c2, c3 = st.columns([1, 1, 1])
    with c1:
        if st.button("Collapse All", use_container_width=True, key="collapse_btn"):
            st.session_state["collapse_all"] = True
            st.rerun()
    with c2:
        if st.button("Expand All", use_container_width=True, key="expand_btn"):
            st.session_state["collapse_all"] = False
            st.rerun()
    with c3:
        use_my_pairs = st.toggle("⭐ My Pairs", key="use_my_pairs")
        if use_my_pairs != load_from_url("use_my_pairs", False, bool):
            save_to_url("use_my_pairs", use_my_pairs)

    with st.popover("Manage My Pairs"):
        st.caption("Comma-separated (e.g., BTC-USD, ETH-USDT)")
        current = st.text_area("Edit list", st.session_state.get("my_pairs", ""))
        if st.button("Save My Pairs"):
            st.session_state["my_pairs"] = ", ".join(
                [p.strip().upper() for p in current.split(",") if p.strip()]
            )
            save_to_url("my_pairs", st.session_state["my_pairs"])
            st.success("Saved!")

    with expander("Market Settings"):
        new_exch = st.selectbox(
            "Exchange",
            CONFIG.EXCHANGES,
            index=CONFIG.EXCHANGES.index(st.session_state["exchange"])
            if st.session_state["exchange"] in CONFIG.EXCHANGES
            else 0,
            key="exchange_widget",
            help="Select cryptocurrency exchange",
        )
        if new_exch != st.session_state.get("exchange"):
            st.session_state["exchange"] = new_exch
            save_to_url("exchange", new_exch)

        new_quote = st.selectbox(
            "Quote Currency",
            CONFIG.QUOTES,
            index=CONFIG.QUOTES.index(st.session_state["quote"])
            if st.session_state["quote"] in CONFIG.QUOTES
            else 0,
            key="quote_widget",
            help="Base currency for trading pairs",
        )
        if new_quote != st.session_state.get("quote"):
            st.session_state["quote"] = new_quote
            save_to_url("quote", new_quote)

        new_use_watch = st.checkbox(
            "Use watchlist only",
            value=st.session_state.get("use_watch", False),
            key="use_watch_widget",
            help="Scan only watchlist pairs",
        )
        if new_use_watch != st.session_state.get("use_watch"):
            st.session_state["use_watch"] = new_use_watch
            save_to_url("use_watch", new_use_watch)

    with expander("Watchlist"):
        st.caption("Monitor specific pairs")
        current_watchlist = st.text_area(
            "Watchlist pairs",
            st.session_state.get(
                "watchlist", "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD"
            ),
            key="watchlist_edit",
            help="Comma-separated pairs",
        )
        if st.button("Update Watchlist"):
            cleaned = ", ".join(
                [p.strip().upper() for p in current_watchlist.split(",") if p.strip()]
            )
            st.session_state["watchlist"] = cleaned
            save_to_url("watchlist", cleaned)
            st.success("Updated!")
            st.rerun()

    if st.session_state.get("use_my_pairs", False):
        avail_pairs = [
            p.strip().upper()
            for p in st.session_state.get("my_pairs", "").split(",")
            if p.strip()
        ]
    elif st.session_state.get("use_watch", False):
        avail_pairs = [
            p.strip().upper()
            for p in st.session_state.get("watchlist", "").split(",")
            if p.strip()
        ]
    else:
        avail_pairs = get_products(get_effective_exchange(), st.session_state["quote"])

    avail_count = len(avail_pairs)

    st.sidebar.subheader("Discover Settings")
      # Alert Strategy: Easy Start for Novice Users
    alert_mode = st.radio(
        "Easy Start: Pre-Set Alert Logic",
        ["Aggressive", "Balanced", "Conservative", "Off"],
        index=3,
        key="alert_mode",
        help="Designed for novice users until you learn manual controls."
    )

    ptd = st.sidebar.slider(
        f"Pairs to discover{f' (Available: {avail_count})' if avail_count else ''}",
        min_value=5,
        max_value=500,
        step=5,
        value=st.session_state.get("pairs_to_discover", 400),
        key="ui_pairs_to_discover",
        help="Number of pairs to scan",
    )
    if ptd != st.session_state.get("pairs_to_discover"):
        st.session_state["pairs_to_discover"] = int(ptd)
        save_to_url("pairs_to_discover", ptd)

with expander("Mode & Timeframes"):
    new_mode = st.radio(
        "Data Source",
        ["REST only", "WebSocket + REST"],
        index=0 if st.session_state["mode"] == "REST only" else 1,
        key="mode_widget",
        help="REST = API polling, WebSocket = real-time",
    )
    if new_mode != st.session_state.get("mode"):
        st.session_state["mode"] = new_mode
        save_to_url("mode", new_mode)

    if st.session_state.get("mode", "").startswith("WebSocket"):
        st.caption(
            "WebSocket uses one Coinbase ticker connection for all pairs. "
            "Candle data still comes from REST."
        )

    timeframe_options = ["5m", "15m", "1h", "4h", "1d"]
    current_tf_index = (
        timeframe_options.index(st.session_state.get("sort_tf", "1h"))
        if st.session_state.get("sort_tf") in timeframe_options
        else 2
    )
    new_tf = st.selectbox(
        "Sort Timeframe",
        timeframe_options,
        index=current_tf_index,
        key="sort_tf_widget",
        help="Timeframe for % calculations",
    )
    if new_tf != st.session_state.get("sort_tf"):
        st.session_state["sort_tf"] = new_tf
        st.session_state["scan_in_progress"] = False
        st.session_state["immediate_rescan"] = True
        get_cached_data.clear()
        save_to_url("sort_tf", new_tf)

    new_sort_desc = st.toggle(
        "Sort Descending",
        value=st.session_state.get("sort_desc", True),
        key="sort_desc_widget",
        help="Highest % first",
    )
    if new_sort_desc != st.session_state.get("sort_desc"):
        st.session_state["sort_desc"] = new_sort_desc
        save_to_url("sort_desc", new_sort_desc)

with expander("Gates"):
    presets = [
        "Spike Hunter",
        "Early MACD Cross",
        "Confirm Rally",
        "hioncrypto's Velocity Mode",
        "None",
    ]
    current_preset_idx = (
        presets.index(st.session_state.get("preset", "None"))
        if st.session_state.get("preset") in presets
        else 4
    )
    new_preset = st.radio(
        "Preset",
        presets,
        index=current_preset_idx,
        key="preset_widget",
        horizontal=True,
        help="Quick filter configs. Default: None",
    )
    if new_preset != st.session_state.get("preset"):
        st.session_state["preset"] = new_preset
        save_to_url("preset", new_preset)

        if new_preset == "Spike Hunter":
            st.session_state.update(
                {
                    "use_vol_spike": True,
                    "vol_mult": 1.10,
                    "use_rsi": False,
                    "use_macd": False,
                    "use_trend": False,
                    "use_roc": False,
                    "use_macd_cross": False,
                }
            )
        elif new_preset == "Early MACD Cross":
            st.session_state.update(
                {
                    "use_vol_spike": True,
                    "vol_mult": 1.10,
                    "use_rsi": True,
                    "min_rsi": 50,
                    "use_macd": True,
                    "use_macd_cross": True,
                    "macd_cross_bars": 1,
                    "macd_cross_only_bull": True,
                    "macd_hist_confirm_bars": 3,
                }
            )
        elif new_preset == "Confirm Rally":
            st.session_state.update(
                {
                    "use_vol_spike": True,
                    "vol_mult": 1.20,
                    "use_rsi": True,
                    "min_rsi": 60,
                    "use_macd": True,
                    "use_trend": True,
                }
            )
        elif new_preset == "hioncrypto's Velocity Mode":
            st.session_state.update(
                {
                    "use_vol_spike": True,
                    "vol_mult": 2.15,
                    "use_roc": True,
                    "min_roc": 3.0,
                    "use_macd_cross": True,
                    "macd_cross_bars": 3,
                    "macd_cross_below_zero": True,
                    "K_green": 2,
                    "Y_yellow": 1,
                    "lookback_candles": 3,
                    "min_bars": 3,
                    "min_pct": 10.0,
                }
            )
        # MARKET CAP FILTER TOGGLE
    mc_enabled = st.sidebar.toggle(
        "📊 Filter by Market Cap",
        key="mc_filter_enabled",
        help="Only scan coins above minimum market cap"
    )

    # CONDITIONAL SLIDER (Hidden unless toggle is ON)
    if mc_enabled:
        st.sidebar.slider(
            "Minimum Market Cap",
            min_value=1,        # $1M
            max_value=100000,   # $100B
            value=10,           # Default: $10M
            step=1,             # $1M increments
            
            key="min_market_cap_millions"
        )
    st.markdown("**Δ (Delta) gate is always active.** Other gates optional.")

    new_lookback = st.slider(
        "Δ lookback (candles)",
        1,
        100,
        value=int(st.session_state["lookback_candles"]),
        step=1,
        key="lookback_widget",
        help="Bars to find lowest LOW (skips start position)",
    )
    if new_lookback != st.session_state.get("lookback_candles"):
        st.session_state["lookback_candles"] = new_lookback
        save_to_url("lookback_candles", new_lookback)
    st.caption(f"Scan window: {new_lookback * {'5m':0.08,'15m':0.25,'1h':1,'4h':4,'1d':24}.get(st.session_state.get('sort_tf','1h'),1):.1f}h")
    
    new_min_pct = st.slider(
        "Min +% change (Δ gate)",
        0.0,
        100.0,
        value=float(st.session_state["min_pct"]),
        step=0.5,
        key="min_pct_widget",
        help="Minimum % gain from lowest LOW",
    )
    if new_min_pct != st.session_state.get("min_pct"):
        st.session_state["min_pct"] = new_min_pct
        save_to_url("min_pct", new_min_pct)

    new_min_bars = st.slider(
        "Min rows (bars)",
        1,
        20,
        value=int(st.session_state.get("min_bars", 3)),
        step=1,
        key="min_bars_widget",
        help="Minimum bars required",
    )
    if new_min_bars != st.session_state.get("min_bars"):
        st.session_state["min_bars"] = new_min_bars
        save_to_url("min_bars", new_min_bars)

    c1, c2, c3 = st.columns(3)
    with c1:
        new_use_vol = st.toggle("Volume spike", key="use_vol_spike", help="Volume exceeds average")
        if new_use_vol != load_from_url("use_vol_spike", False, bool):
            save_to_url("use_vol_spike", new_use_vol)
        if st.session_state.get("use_vol_spike"):
            new_vm = st.slider(
                "Spike multiple",
                1.0,
                20.0,
                value=float(st.session_state.get("vol_mult", 1.10)),
                step=0.05,
                key="vol_mult",
            )
            if new_vm != st.session_state.get("vol_mult"):
                save_to_url("vol_mult", new_vm)
    with c2:
        new_use_rsi = st.toggle("RSI", key="use_rsi", help="Momentum indicator")
        if new_use_rsi != load_from_url("use_rsi", False, bool):
            save_to_url("use_rsi", new_use_rsi)
        if st.session_state.get("use_rsi"):
            new_mr = st.slider(
                "Min RSI",
                40,
                90,
                value=int(st.session_state.get("min_rsi", 55)),
                step=1,
                key="min_rsi",
            )
            if new_mr != st.session_state.get("min_rsi"):
                save_to_url("min_rsi", new_mr)
    with c3:
        new_use_macd = st.toggle("MACD hist", key="use_macd", help="Histogram indicator")
        if new_use_macd != load_from_url("use_macd", False, bool):
            save_to_url("use_macd", new_use_macd)
        if st.session_state.get("use_macd"):
            new_mh = st.slider(
                "Min MACD hist",
                0.0,
                2.0,
                value=float(st.session_state.get("min_mhist", 0.0)),
                step=0.05,
                key="min_mhist",
            )
            if new_mh != st.session_state.get("min_mhist"):
                save_to_url("min_mhist", new_mh)

    c4, c5, c6 = st.columns(3)
    with c4:
        new_use_atr = st.toggle("ATR %", key="use_atr", help="Volatility filter")
        if new_use_atr != load_from_url("use_atr", False, bool):
            save_to_url("use_atr", new_use_atr)
        if st.session_state.get("use_atr"):
            new_ma = st.slider(
                "Min ATR %",
                0.0,
                10.0,
                value=float(st.session_state.get("min_atr", 0.5)),
                step=0.1,
                key="min_atr",
            )
            if new_ma != st.session_state.get("min_atr"):
                save_to_url("min_atr", new_ma)
    with c5:
        new_use_trend = st.toggle("Trend breakout", key="use_trend", help="Resistance break")
        if new_use_trend != load_from_url("use_trend", False, bool):
            save_to_url("use_trend", new_use_trend)
        if st.session_state.get("use_trend"):
            st.slider(
                "Pivot span",
                2,
                10,
                value=int(st.session_state.get("pivot_span", 4)),
                step=1,
                key="pivot_span",
            )
            st.slider(
                "Breakout within",
                0,
                96,
                value=int(st.session_state.get("trend_within", 48)),
                step=1,
                key="trend_within",
            )
    with c6:
        new_use_roc = st.toggle("ROC", key="use_roc", help="Rate of change")
        if new_use_roc != load_from_url("use_roc", False, bool):
            save_to_url("use_roc", new_use_roc)
        if st.session_state.get("use_roc"):
            new_mro = st.slider(
                "Min ROC %",
                0.0,
                100.0,
                value=float(st.session_state.get("min_roc", 1.0)),
                step=0.5,
                key="min_roc",
            )
            if new_mro != st.session_state.get("min_roc"):
                save_to_url("min_roc", new_mro)

    st.markdown("**MACD Cross (early entry)**")
    c7, c8, c9, c10 = st.columns(4)
    with c7:
        new_umc = st.toggle("Enable", key="use_macd_cross", help="MACD cross detection")
        if new_umc != load_from_url("use_macd_cross", False, bool):
            save_to_url("use_macd_cross", new_umc)
    with c8:
        if st.session_state.get("use_macd_cross"):
            st.slider(
                "Cross within",
                1,
                10,
                value=int(st.session_state.get("macd_cross_bars", 5)),
                step=1,
                key="macd_cross_bars",
            )
    with c9:
        if st.session_state.get("use_macd_cross"):
            st.toggle("Bullish only", key="macd_cross_only_bull")
    with c10:
        if st.session_state.get("use_macd_cross"):
            st.toggle(
                "Below zero",
                key="macd_cross_below_zero",
                help="Cross must be below zero line",
            )
        st.toggle(
            "✚Vol. + MACD Cross",
            key="macd_cross_sync",
            help="Alert only when MACD Cross + Volume Spike align on 4h/Daily",
            )
    if st.session_state.get("use_macd_cross"):
        st.slider(
            "Histogram > 0 within",
            0,
            10,
            value=int(st.session_state.get("macd_hist_confirm_bars", 3)),
            step=1,
            key="macd_hist_confirm_bars",
        )

    st.markdown("---")

    gate_modes = ["ALL", "ANY", "BALANCED", "Custom (K/Y)"]
    current_mode_idx = (
        gate_modes.index(st.session_state.get("gate_mode", "ANY"))
        if st.session_state.get("gate_mode") in gate_modes
        else 1
    )
    new_gm = st.radio(
        "Gate Mode",
        gate_modes,
        index=current_mode_idx,
        key="gate_mode_widget",
        horizontal=True,
        help="ALL = need all, ANY = need one, Custom = color by count",
    )
    if new_gm != st.session_state.get("gate_mode"):
        st.session_state["gate_mode"] = new_gm
        save_to_url("gate_mode", new_gm)

    new_hf = st.toggle("Hard filter (hide non-passers)", key="hard_filter")
    if new_hf != load_from_url("hard_filter", False, bool):
        save_to_url("hard_filter", new_hf)

    if st.session_state.get("gate_mode") == "Custom (K/Y)":
        st.subheader("Color rules")
        st.selectbox(
            "Gates for green (K)",
            list(range(1, 8)),
            index=int(st.session_state.get("K_green", 3)) - 1,
            key="K_green",
        )
        st.selectbox(
            "Yellow needs ≥ Y (< K)",
            list(range(0, int(st.session_state.get("K_green", 3)))),
            index=min(
                int(st.session_state.get("Y_yellow", 2)),
                max(0, int(st.session_state.get("K_green", 3)) - 1),
            ),
            key="Y_yellow",
        )
with expander("🔔 Notifications"):
    st.caption("Email requires SMTP in st.secrets.toml")

    clear_notification_save_msgs_if_edited()

    st.text_input(
        "Email recipient",
        key="email_to",
        on_change=on_email_saved,
        help="Press Enter or click away to save (non-empty only)",
    )
    _render_notification_save_msg("email_save_msg", "email_save_msg_until")

    st.text_input(
        "Webhook URL",
        key="webhook_url",
        on_change=on_webhook_saved,
        help="Press Enter or click away to save (non-empty only)",
    )
    _render_notification_save_msg("webhook_save_msg", "webhook_save_msg_until")

    _schedule_notification_msg_dismiss()

with expander("Display"):
    new_fs = st.slider(
        "Font size",
        0.8,
        1.6,
        value=float(st.session_state.get("font_scale", 1.0)),
        step=0.05,
        key="font_scale",
    )
    if new_fs != st.session_state.get("font_scale"):
        save_to_url("font_scale", new_fs)

    new_rs = st.slider(
        "Auto-refresh (seconds)",
        5,
        120,
        value=int(st.session_state.get("refresh_sec", 30)),
        step=1,
        key="refresh_sec",
        help=(
            "Minimum seconds between automatic scans. The results panel also "
            "refreshes on this interval via the fragment timer."
        ),
    )
    if new_rs != st.session_state.get("refresh_sec"):
        get_cached_data.clear()
        save_to_url("refresh_sec", new_rs)

with expander("Listing Radar"):
    st.caption("Detect new listings")

    current_lr_enabled = st.session_state.get(
        "lr_enabled", load_from_url("lr_enabled", False, bool)
    )
    new_lre = st.toggle(
        "Enable Listing Radar",
        value=current_lr_enabled,
        key="lr_enabled_widget",
    )
    if new_lre != current_lr_enabled:
        st.session_state["lr_enabled"] = new_lre
        save_to_url("lr_enabled", new_lre)
        if new_lre:
            run_listing_radar_poll(force=True)

    if st.session_state.get("lr_enabled", False):
        c1, c2 = st.columns(2)
        with c1:
            st.toggle(
                "Watch Coinbase",
                key="lr_watch_coinbase",
                value=st.session_state.get("lr_watch_coinbase", True),
            )
        with c2:
            st.toggle(
                "Watch Binance",
                key="lr_watch_binance",
                value=st.session_state.get("lr_watch_binance", True),
            )

        st.text_input(
            "Watch quotes",
            st.session_state.get("lr_watch_quotes", "USD, USDT, USDC"),
            key="lr_watch_quotes",
        )

        st.slider(
            "Poll interval (seconds)",
            10,
            300,
            st.session_state.get("lr_poll_sec", 30),
            5,
            key="lr_poll_sec",
        )

        st.slider(
            "Upcoming window (hours)",
            1,
            168,
            st.session_state.get("lr_upcoming_window_h", 48),
            1,
            key="lr_upcoming_window_h",
        )

        st.text_area(
            "News feeds (URLs)",
            st.session_state.get("lr_feeds", ""),
            key="lr_feeds",
        )

run_listing_radar_poll()

lr_window = int(st.session_state.get("lr_upcoming_window_h", 48))
if st.session_state.get("lr_events"):
    with st.sidebar.expander("🆕 Listing Radar"):
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=lr_window)
        recent = [e for e in st.session_state.lr_events 
                  if dt.datetime.fromisoformat(e["detected_at"]) > cutoff]
        
        if recent:
            st.write(f"**New listings (last {lr_window}h):**")
            for event in recent[-20:]:
                icon = "📰" if event.get("type") == "feed" else "🆕"
                st.write(f"{icon} {event['pair']} ({event['exchange']})")
        else:
            st.write("No new listings in window")

# =============================================================================
# WEBSOCKET HELPERS
# =============================================================================
WS_MSG_STALE_SEC = 45
WS_CONNECT_TIMEOUT = 20
WS_RECV_TIMEOUT = 5.0
WS_MAX_RETRIES = 3
WS_RETRY_DELAY_SEC = 2.0
WS_STAGGER_SEC = 1.0
WS_START_GRACE_SEC = 300
WS_ERROR_LOG_INTERVAL = 30.0
FRAGMENT_POLL_SEC = 5

# Streamlit session_state is main-thread only — workers use this shared store.
_WS_LOCK = threading.Lock()
_WS_THREADS_LOCK = threading.Lock()
_WS_WORKERS: Dict[int, threading.Thread] = {}
_WS_SHARED: Dict[str, Any] = {
    "stop": False,
    "prices": {},
    "last_msg": 0.0,
    "error": None,
    "chunk_status": {},
    "connected": False,
    "connecting": False,
    "subscribed": 0,
    "connection_count": 0,
    "limit_hit": False,
}
_WS_ERROR_LOG: Dict[str, float] = {}
_WS_ERROR_COUNTS: Dict[str, int] = {}


def _ws_snapshot() -> dict:
    with _WS_LOCK:
        return {
            "stop": _WS_SHARED["stop"],
            "prices": dict(_WS_SHARED["prices"]),
            "last_msg": _WS_SHARED["last_msg"],
            "error": _WS_SHARED["error"],
            "chunk_status": dict(_WS_SHARED["chunk_status"]),
            "connected": _WS_SHARED["connected"],
            "connecting": _WS_SHARED["connecting"],
            "subscribed": _WS_SHARED["subscribed"],
            "connection_count": _WS_SHARED["connection_count"],
            "limit_hit": _WS_SHARED.get("limit_hit", False),
        }


def sync_ws_to_session() -> None:
    snap = _ws_snapshot()
    st.session_state["ws_prices"] = snap["prices"]
    runtime = _ws_runtime()
    runtime["last_msg"] = snap["last_msg"]
    runtime["error"] = snap["error"]
    runtime["chunk_status"] = snap["chunk_status"]
    runtime["connected"] = snap["connected"]
    runtime["connecting"] = snap["connecting"]
    runtime["subscribed"] = snap["subscribed"]
    runtime["connection_count"] = snap["connection_count"]


def get_ws_price(pair: str) -> Optional[float]:
    with _WS_LOCK:
        return _WS_SHARED["prices"].get(pair)


def clear_ws_shared() -> None:
    with _WS_LOCK:
        _WS_SHARED["prices"].clear()
        _WS_SHARED["last_msg"] = 0.0
        _WS_SHARED["error"] = None
        _WS_SHARED["chunk_status"] = {}
        _WS_SHARED["connected"] = False
        _WS_SHARED["connecting"] = False
        _WS_SHARED["limit_hit"] = False


def _ws_runtime() -> dict:
    if "ws_runtime" not in st.session_state:
        st.session_state["ws_runtime"] = {
            "connected": False,
            "connecting": False,
            "last_msg": 0.0,
            "error": None,
            "subscribed": 0,
            "connection_count": 0,
            "chunk_status": {},
        }
    return st.session_state["ws_runtime"]


def _ws_count_alive_threads() -> int:
    with _WS_THREADS_LOCK:
        return sum(1 for t in _WS_WORKERS.values() if t.is_alive())


def _ws_log_server_error(data: dict) -> None:
    err = data.get("message", str(data))
    reason = data.get("reason", "")
    detail = f"{err}" + (f" — {reason}" if reason else "")
    reason_key = reason or err

    with _WS_LOCK:
        _WS_SHARED["error"] = detail
        _WS_ERROR_COUNTS[reason_key] = _WS_ERROR_COUNTS.get(reason_key, 0) + 1
        if "subscription limit" in reason_key.lower():
            _WS_SHARED["limit_hit"] = True

    # Per-product failures are expected; log a summary instead of flooding the terminal.
    if reason_key.startswith("subscription limit"):
        return
    if "delisted" in reason_key or "not a valid product" in reason_key:
        return

    key = f"{err}|{reason}"
    now = time.time()
    with _WS_LOCK:
        last = _WS_ERROR_LOG.get(key, 0.0)
        if now - last < WS_ERROR_LOG_INTERVAL:
            return
        _WS_ERROR_LOG[key] = now
    print(f"[WS] Server error: {detail}")


def _ws_maybe_log_error_summary() -> None:
    now = time.time()
    with _WS_LOCK:
        if not _WS_ERROR_COUNTS:
            return
        last = _WS_ERROR_LOG.get("__summary__", 0.0)
        if now - last < WS_ERROR_LOG_INTERVAL:
            return
        _WS_ERROR_LOG["__summary__"] = now
        counts = dict(_WS_ERROR_COUNTS)
        _WS_ERROR_COUNTS.clear()

    parts = []
    for reason, count in sorted(counts.items(), key=lambda x: -x[1])[:5]:
        short = reason if len(reason) <= 80 else reason[:77] + "..."
        parts.append(f"{count}× {short}")
    print(f"[WS] Subscribe issues (summary): {'; '.join(parts)}")


def _ws_send_coinbase_subscribe(ws, product_ids: list, subscribe: bool = True) -> None:
    msg = {
        "type": "subscribe" if subscribe else "unsubscribe",
        "product_ids": product_ids,
        "channels": list(CONFIG.COINBASE_WS_CHANNELS),
    }
    ws.send(json.dumps(msg))


def _ws_close_coinbase(ws, product_ids: list) -> None:
    if ws is None:
        return
    try:
        _ws_send_coinbase_subscribe(ws, product_ids, subscribe=False)
    except Exception:
        pass
    try:
        ws.close()
    except Exception:
        pass


def _ws_handle_coinbase_message(data: dict) -> None:
    msg_type = data.get("type")

    if msg_type == "error":
        _ws_log_server_error(data)
        _ws_maybe_log_error_summary()
        return

    if msg_type == "subscriptions":
        _ws_maybe_log_error_summary()
        ch_names = [c.get("name") for c in data.get("channels", []) if isinstance(c, dict)]
        print(f"[WS] Subscriptions confirmed: {ch_names} ({len(data.get('channels', []))} channels)")
        with _WS_LOCK:
            _WS_SHARED["last_msg"] = time.time()
        return

    if msg_type in ("ticker", "ticker_batch", "heartbeat"):
        product_id = data.get("product_id")
        price = data.get("price")
        with _WS_LOCK:
            if product_id and price:
                _WS_SHARED["prices"][product_id] = float(price)
            _WS_SHARED["last_msg"] = time.time()


def stop_websocket_workers(clear_cache: bool = False) -> None:
    with _WS_LOCK:
        _WS_SHARED["stop"] = True
    with _WS_THREADS_LOCK:
        workers = list(_WS_WORKERS.values())
    for worker in workers:
        if worker.is_alive():
            worker.join(timeout=WS_RECV_TIMEOUT + 3)
    with _WS_THREADS_LOCK:
        _WS_WORKERS.clear()
    st.session_state["ws_stop"] = True
    st.session_state["ws_alive"] = False
    st.session_state.pop("ws_threads", None)
    st.session_state.pop("ws_thread", None)
    # Keep ws_pairs_key — clearing it forces redundant reconnects on the next ensure() call.
    if clear_cache:
        clear_ws_shared()
        st.session_state.pop("ws_pairs_key", None)
        st.session_state.pop("ws_started_at", None)
    runtime = st.session_state.get("ws_runtime")
    if runtime:
        runtime["connected"] = False
        runtime["connecting"] = False
        runtime["chunk_status"] = {}


def ensure_coinbase_websocket(pairs: list, exchange: str) -> None:
    mode = st.session_state.get("mode", "REST only")
    if not mode.startswith("WebSocket") or exchange != "Coinbase" or not WS_AVAILABLE:
        return

    if not pairs:
        return

    # One connection for all pairs — Coinbase limits subscriptions per product per
    # channel account-wide; multiple connections + reconnects exhaust the free tier.
    chunks = [pairs]
    pairs_key = (tuple(pairs), 0)

    alive = _ws_count_alive_threads()
    if pairs_key == st.session_state.get("ws_pairs_key") and alive > 0:
        return

    snap = _ws_snapshot()
    last_msg = float(snap["last_msg"])
    msg_fresh = last_msg > 0 and (time.time() - last_msg) < WS_MSG_STALE_SEC

    if pairs_key == st.session_state.get("ws_pairs_key"):
        price_count = len(snap["prices"])
        started_at = float(st.session_state.get("ws_started_at", 0))
        in_grace = (time.time() - started_at) < WS_START_GRACE_SEC
        if in_grace:
            return
        if msg_fresh and price_count > 0:
            return

    stop_websocket_workers(clear_cache=False)
    with _WS_LOCK:
        _WS_SHARED["stop"] = False
    st.session_state["ws_stop"] = False
    st.session_state["ws_pairs_key"] = pairs_key
    st.session_state["ws_started_at"] = time.time()
    st.session_state.setdefault("ws_prices", {})

    with _WS_LOCK:
        _WS_SHARED["connecting"] = True
        _WS_SHARED["connected"] = False
        _WS_SHARED["error"] = None
        _WS_SHARED["limit_hit"] = False
        _WS_SHARED["subscribed"] = len(pairs)
        _WS_SHARED["connection_count"] = len(chunks)
        _WS_SHARED["chunk_status"] = {}

    runtime = _ws_runtime()
    runtime["connecting"] = True
    runtime["connected"] = False
    runtime["error"] = None
    runtime["subscribed"] = len(pairs)
    runtime["connection_count"] = len(chunks)
    runtime["chunk_status"] = {}

    def ws_worker(chunk_id: int, product_ids: list):
        time.sleep(chunk_id * WS_STAGGER_SEC)
        with _WS_LOCK:
            _WS_SHARED["chunk_status"][chunk_id] = "connecting"

        while not _WS_SHARED.get("stop"):
            ws = None
            connected_ok = False

            for attempt in range(1, WS_MAX_RETRIES + 1):
                if _WS_SHARED.get("stop"):
                    return
                try:
                    print(
                        f"[WS #{chunk_id}] Attempt {attempt}/{WS_MAX_RETRIES}: "
                        f"connecting to {CONFIG.COINBASE_WS} "
                        f"({len(product_ids)} pairs)"
                    )
                    ws = websocket.WebSocket()
                    ws.connect(CONFIG.COINBASE_WS, timeout=WS_CONNECT_TIMEOUT)
                    ws.settimeout(WS_RECV_TIMEOUT)

                    _ws_send_coinbase_subscribe(ws, product_ids)
                    print(
                        f"[WS #{chunk_id}] Subscribe sent: "
                        f"{len(product_ids)} products, channels={CONFIG.COINBASE_WS_CHANNELS}"
                    )

                    with _WS_LOCK:
                        _WS_SHARED["connected"] = True
                        _WS_SHARED["connecting"] = False
                        _WS_SHARED["chunk_status"][chunk_id] = "connected"
                    connected_ok = True

                    while not _WS_SHARED.get("stop"):
                        try:
                            message = ws.recv()
                            if not message:
                                continue
                            data = json.loads(message)
                            _ws_handle_coinbase_message(data)
                        except websocket.WebSocketTimeoutException:
                            continue
                        except Exception as recv_err:
                            print(
                                f"[WS #{chunk_id}] Receive error: "
                                f"{type(recv_err).__name__}: {recv_err}"
                            )
                            break

                    break

                except Exception as conn_err:
                    err_msg = f"chunk {chunk_id} attempt {attempt}: {conn_err}"
                    with _WS_LOCK:
                        _WS_SHARED["error"] = err_msg
                        _WS_SHARED["chunk_status"][chunk_id] = f"error ({attempt})"
                    print(
                        f"[WS #{chunk_id}] Connection failed (attempt {attempt}): "
                        f"{type(conn_err).__name__}: {conn_err}"
                    )
                    if ws is not None:
                        _ws_close_coinbase(ws, product_ids)
                        ws = None
                    if attempt < WS_MAX_RETRIES:
                        delay = WS_RETRY_DELAY_SEC * attempt
                        print(f"[WS #{chunk_id}] Retrying in {delay:.0f}s...")
                        time.sleep(delay)

            if ws is not None:
                _ws_close_coinbase(ws, product_ids)

            with _WS_LOCK:
                _WS_SHARED["chunk_status"][chunk_id] = "disconnected"
            print(f"[WS #{chunk_id}] Connection closed")

            with _WS_THREADS_LOCK:
                others_alive = sum(
                    1 for tid, t in _WS_WORKERS.items()
                    if tid != chunk_id and t.is_alive()
                )
            if not others_alive:
                with _WS_LOCK:
                    _WS_SHARED["connected"] = False
                    _WS_SHARED["connecting"] = False

            if _WS_SHARED.get("stop"):
                return

            if not connected_ok:
                print(f"[WS #{chunk_id}] All retries failed; waiting before reconnect...")
                time.sleep(WS_RETRY_DELAY_SEC * WS_MAX_RETRIES)
            else:
                print(f"[WS #{chunk_id}] Reconnecting after drop...")
                time.sleep(WS_RETRY_DELAY_SEC)

    ws_threads = {}
    for i, chunk in enumerate(chunks):
        ws_thread = threading.Thread(
            target=ws_worker,
            args=(i, chunk),
            daemon=True,
            name=f"coinbase-ws-{i}",
        )
        ws_threads[i] = ws_thread
        with _WS_THREADS_LOCK:
            _WS_WORKERS[i] = ws_thread
        ws_thread.start()

    st.session_state["ws_threads"] = ws_threads
    st.session_state["ws_thread"] = ws_threads.get(0)
    st.session_state["ws_alive"] = True
    print(
        f"[WS] Started 1 connection for {len(pairs)} pairs "
        f"(channel={CONFIG.COINBASE_WS_CHANNELS[0]}) → {CONFIG.COINBASE_WS}"
    )


def get_websocket_status_label() -> Tuple[str, str]:
    mode = st.session_state.get("mode", "REST only")
    exchange = st.session_state.get("exchange", "Coinbase")
    effective = (
        "Coinbase"
        if "coming soon" in exchange.lower()
        else exchange
    )
    price_count = len(_ws_snapshot()["prices"])

    if not mode.startswith("WebSocket"):
        return "⚪", f"REST only (WebSocket off) | Cached prices: {price_count}"

    if not WS_AVAILABLE:
        return "🔴", "WebSocket library not installed"

    if effective != "Coinbase":
        return "⚪", f"WebSocket N/A for {effective}"

    snap = _ws_snapshot()
    alive_count = _ws_count_alive_threads()
    subscribed = int(snap["subscribed"])
    conn_count = int(snap["connection_count"])
    chunk_status = snap["chunk_status"]
    connected_chunks = sum(1 for v in chunk_status.values() if v == "connected")
    last_msg = float(snap["last_msg"])
    age = time.time() - last_msg if last_msg > 0 else None

    if snap.get("limit_hit"):
        return (
            "🟡",
            f"Subscription limit hit — using REST for candles | "
            f"Cache: {price_count} prices",
        )

    if snap["connecting"] and (alive_count > 0 or price_count > 0):
        return (
            "🟡",
            f"Connecting {subscribed} pairs on ticker channel | Cache: {price_count}",
        )

    is_live = (
        last_msg > 0
        and age is not None
        and age < WS_MSG_STALE_SEC
        and (connected_chunks > 0 or alive_count > 0 or price_count > 0)
    )

    if is_live:
        return (
            "🟢",
            f"Live ticker ({subscribed} pairs) | "
            f"{price_count} in cache | Last msg {int(age)}s ago",
        )

    if snap.get("error"):
        return "🔴", f"Disconnected ({snap['error']}) | Cache: {price_count}"

    stale_note = f" | Last tick {int(age)}s ago" if age is not None else ""
    return "🔴", f"Disconnected | Pairs in cache: {price_count}{stale_note}"


def render_scan_results(
    rows: list,
    sort_tf: str,
    hard_filter: bool,
    header_note: Optional[str] = None,
    interactive: bool = True,
) -> None:
    if header_note:
        st.caption(header_note)

    if not rows:
        if hard_filter:
            st.info(
                "Hard filter is ON — no pairs passed gate classification. "
                "Adjust gates or turn off hard filter."
            )
        else:
            st.info(
                "No pairs in the current scan results. "
                "If you changed timeframe or filters, wait for the next scan to finish."
            )
        return

    df_results = pd.DataFrame(rows)
    chg_col = f"% Change ({sort_tf})"
    if chg_col not in df_results.columns:
        alt_cols = [c for c in df_results.columns if c.startswith("% Change (")]
        if alt_cols:
            chg_col = alt_cols[0]
        else:
            st.warning("Results column mismatch — run Refresh Now to rescan.")
            return
    ascending = not st.session_state["sort_desc"]

    df_results = df_results.sort_values(chg_col, ascending=ascending)
    df_results.insert(0, "#", range(1, len(df_results) + 1))

    green_count = df_results["_green"].sum()
    yellow_count = df_results["_yellow"].sum()
    total_count = len(df_results)
    max_pct = df_results[chg_col].max() if not df_results.empty else 0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Pairs", total_count)
    with col2:
        st.metric("Strong Buy", green_count)
    with col3:
        st.metric("Watch", yellow_count)
    with col4:
        st.metric("Max % Change", f"{max_pct:.2f}%")

    st.subheader("🔥 Top 10 Opportunities")

    top_10_filtered = df_results.head(10).copy()
    top_10_filtered = top_10_filtered.reset_index(drop=True)
    mc_data = get_market_caps()

    def format_market_cap(val):
        if val >= 1_000_000_000:
            return f"{val/1_000_000_000:.1f}B"
        elif val >= 1_000_000:
            return f"{int(val/1_000_000)}M"
        return "--"

    top_10_filtered["Market Cap"] = top_10_filtered["Pair"].apply(
        lambda x: format_market_cap(mc_data.get(x.split("-")[0], 0))
    )
    if "#" in top_10_filtered.columns:
        top_10_filtered = top_10_filtered.drop(columns=["#"])
    top_10_filtered.insert(0, "Rank", range(1, len(top_10_filtered) + 1))

    if not top_10_filtered.empty:
        def style_top10_rows(row):
            idx = row.name
            if idx < len(top_10_filtered):
                if top_10_filtered.iloc[idx]["_green"]:
                    return [
                        "background-color: #16a34a; color: white; font-weight: 600"
                    ] * len(row)
                elif top_10_filtered.iloc[idx]["_yellow"]:
                    return ["background-color: #eab308; color: black"] * len(row)
            return [""] * len(row)

        display_cols = [c for c in top_10_filtered.columns if not c.startswith("_")]
        styled_df = top_10_filtered[display_cols].style.apply(style_top10_rows, axis=1)
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        st.info("No pairs found.")

    col1, col2 = st.columns([3, 1])
    if interactive:
        with col1:
            show_all = st.checkbox("Show all pairs", value=True, key="show_all_pairs")
        with col2:
            sort_option = st.selectbox("Sort by", ["% Change", "Signal", "Pair"], index=0)
    else:
        show_all = True
        sort_option = "% Change"

    if not show_all:
        display_df = df_results[df_results["_green"] | df_results["_yellow"]]
    else:
        display_df = df_results

    if sort_option == "Signal":
        display_df = display_df.sort_values(["_green", "_yellow"], ascending=[False, False])
    elif sort_option == "Pair":
        display_df = display_df.sort_values("Pair")

    if not display_df.empty:
        display_cols = [c for c in display_df.columns if not c.startswith("_")]
        final_display = display_df[display_cols].reset_index(drop=True)

        def style_all_rows(row):
            if row.name < len(display_df):
                original_idx = display_df.index[row.name]
                if display_df.loc[original_idx, "_green"]:
                    return [
                        "background-color: #16a34a; color: white; font-weight: 600"
                    ] * len(row)
                elif display_df.loc[original_idx, "_yellow"]:
                    return ["background-color: #eab308; color: black"] * len(row)
            return [""] * len(row)

        styled_all = final_display.style.apply(style_all_rows, axis=1)
        st.dataframe(styled_all, use_container_width=True, hide_index=True, height=600)
    else:
        st.info("No pairs match filters.")


def ws_status_panel() -> None:
    """WebSocket status — isolated fragment so scan panel does not touch main-page widgets."""
    sync_ws_to_session()
    sym, lbl = get_websocket_status_label()
    st.caption(f"WebSocket: {sym} | {lbl}")


def scan_results_panel() -> None:
    """Scan + results island — reads live session_state so fragment reruns stay current."""
    pairs = build_scan_pairs()
    effective_exchange = get_effective_exchange()
    gate_settings = build_gate_settings()
    sort_tf = st.session_state.get("sort_tf", "1h")
    hard_filter = bool(st.session_state.get("hard_filter", False))
    refresh_interval = int(st.session_state.get("refresh_sec", 30))
    min_bars = int(st.session_state.get("min_bars", 3))

    if st.session_state.get("mc_filter_enabled") and pairs:
        st.caption(
            f"Market cap filter active — scanning {len(pairs)} pairs "
            f"(min ${st.session_state.get('min_market_cap_millions', 10)}M)."
        )

    if not pairs:
        st.info("No pairs found. Adjust settings.")
        return

    scan_busy = st.session_state.get("scan_in_progress", False)
    scan_started = float(st.session_state.get("scan_started_at", 0))
    scan_elapsed = (time.time() - scan_started) if scan_started else 0

    if not scan_busy:
        ensure_coinbase_websocket(pairs, effective_exchange)

    if "alerted_pairs" not in st.session_state:
        st.session_state["alerted_pairs"] = load_alerted_pairs()
    alerted_pairs = st.session_state["alerted_pairs"]

    mode = st.session_state["gate_mode"]
    k_required = st.session_state.get("K_green", 3)
    y_required = st.session_state.get("Y_yellow", 2)
    alert_mode = st.session_state.get("alert_mode", "Off")

    current_time = int(time.time())
    if "last_update" not in st.session_state:
        st.session_state["last_update"] = 0
    time_since_update = current_time - st.session_state["last_update"]
    cached_tf = st.session_state.get("scan_sort_tf", sort_tf)
    config_stale = cached_tf != sort_tf
    need_rescan = (
        st.session_state.get("scan_rows") is None
        or config_stale
        or st.session_state.pop("immediate_rescan", False)
        or time_since_update >= refresh_interval
    )
    # Orphan scan_in_progress (crashed run) blocks rescans — clear before starting anew.
    if need_rescan and scan_busy:
        st.session_state["scan_in_progress"] = False
        scan_busy = False

    progress_ph = st.empty()
    status_ph = st.empty()
    remaining_ph = st.empty()
    results_ph = st.empty()
    alerts_to_send = []

    cached_rows = list(st.session_state.get("scan_rows") or [])
    scan_ran = False
    scan_warning = None

    if need_rescan:
        st.session_state["scan_in_progress"] = True
        st.session_state["scan_started_at"] = time.time()
        scan_id = time.time()
        st.session_state["_current_scan_id"] = scan_id
        rows = []
        try:
            total_pairs = len(pairs)
            for i, pair in enumerate(pairs):
                done = i + 1
                left = total_pairs - done
                progress_ph.progress(done / total_pairs)
                status_ph.caption(f"Processing {pair}... ({done}/{total_pairs})")
                remaining_ph.caption(f"{left} pairs remaining")

                df = fetch_pair_data(effective_exchange, pair, sort_tf)
                if df is None or df.empty or len(df) < min_bars:
                    ws_price = get_ws_price(pair)
                    price_str = f"${float(ws_price):.6f}" if ws_price else "—"
                    rows.append({
                        "Pair": pair,
                        "Price": price_str,
                        f"% Change ({sort_tf})": 0.0,
                        "Signal": "",
                        "Gates": "— (no candle data)",
                        "_passed": 0,
                        "_enabled": 0,
                        "_green": False,
                        "_yellow": False,
                        "_ws_active": ws_price is not None,
                    })
                    continue
                if gate_settings.get("use_vol_spike", False):
                    vol_spike_ratio = volume_spike(df, gate_settings.get("vol_window", 20))
                else:
                    vol_spike_ratio = 0.0

                meta, passed, chips, enabled = evaluate_gates(df, gate_settings)
                delta_pct = meta.get("delta_pct", 0.0)
                rel_vol = vol_spike_ratio
                use_vol = st.session_state.get("use_vol_spike", False)

                is_green = passed >= enabled and enabled > 0
                is_yellow = (0 < passed < enabled) and (passed >= enabled - 1) if enabled > 0 else False

                if mode == "ALL":
                    is_green = (enabled > 0 and passed == enabled)
                elif mode == "ANY":
                    is_green = (passed >= 1)
                elif mode == "BALANCED":
                    is_green = (passed >= (enabled // 2 + 1)) if enabled > 0 else False
                elif mode == "Custom (K/Y)":
                    is_green = passed >= k_required
                    is_yellow = (passed >= y_required) and (passed < k_required)
                else:
                    is_green = False

                ws_price = get_ws_price(pair)
                last_price = float(ws_price) if ws_price else float(df["close"].iloc[-1])
                pct_change = meta["delta_pct"]

                strategy_approved = True
                if alert_mode != "Off" and is_green:
                    df_4h = fetch_pair_data(effective_exchange, pair, "4h")
                    df_1d = fetch_pair_data(effective_exchange, pair, "1d")

                    strategy_approved = False
                    if check_alert_strategy(df_1d, alert_mode, 20.0):
                        strategy_approved = True
                    elif check_alert_strategy(df_4h, alert_mode, 20.0):
                        strategy_approved = True

                    if alert_mode == "Conservative" and strategy_approved:
                        df_15m = fetch_pair_data(effective_exchange, pair, "15m")
                        if df_15m is not None:
                            recent_low_15m = df_15m["close"].iloc[-5:].min()
                            pct_move_15m = (
                                (df_15m["close"].iloc[-1] - recent_low_15m) / recent_low_15m
                            ) * 100
                            if pct_move_15m < 20.0:
                                strategy_approved = False

                if is_green and strategy_approved:
                    include, alert_type = should_send_alert(
                        pair, delta_pct, rel_vol, st.session_state["alerted_pairs"],
                        use_vol_spike=use_vol,
                    )
                    if include:
                        stage = format_alert_stage(pair, alert_type, rel_vol)
                        if stage is not None:
                            alerts_to_send.append({
                                "pair": pair,
                                "price": last_price,
                                "pct": pct_change,
                                "timeframe": sort_tf,
                                "exchange": effective_exchange,
                                "signal": "Strong Buy",
                                "stage": stage,
                            })

                if not is_green and pair in alerted_pairs:
                    alerted_pairs.pop(pair, None)

                if hard_filter:
                    if mode in {"ALL", "ANY", "BALANCED"} and not is_green:
                        continue
                    if mode == "Custom (K/Y)" and not (is_green or is_yellow):
                        continue

                signal = ""
                if is_green:
                    signal = "Strong Buy"
                elif is_yellow:
                    signal = "Watch"

                rows.append({
                    "Pair": pair,
                    "Price": f"${last_price:.6f}",
                    f"% Change ({sort_tf})": pct_change,
                    "Signal": signal,
                    "Gates": chips,
                    "_passed": passed,
                    "_enabled": enabled,
                    "_green": is_green,
                    "_yellow": is_yellow,
                    "_ws_active": ws_price is not None,
                })

            status_ph.caption("Scan finished.")
            remaining_ph.caption("")

            if alerts_to_send and rows:
                chg_col = f"% Change ({sort_tf})"
                temp_df = pd.DataFrame(rows)
                temp_df = temp_df.sort_values(chg_col, ascending=False)
                top_10_pairs = temp_df[temp_df["_green"] == True].head(10)["Pair"].tolist()
                alerts_to_send = [
                    alert for alert in alerts_to_send if alert["pair"] in top_10_pairs
                ]

            save_alerted_pairs(st.session_state["alerted_pairs"])

            dispatch_scan_alerts(alerts_to_send, scan_id)

            scan_ran = True
            scanned_count = len(rows)
            if rows:
                st.session_state["scan_rows"] = rows
                st.session_state["scan_sort_tf"] = sort_tf
                display_rows = rows
                display_tf = sort_tf
            elif cached_rows and cached_tf != sort_tf:
                st.session_state["scan_rows"] = cached_rows
                display_rows = cached_rows
                display_tf = cached_tf
                scan_warning = (
                    f"Scan on {sort_tf} returned 0 rows "
                    f"({'hard filter ON' if hard_filter else 'check REST/API'}). "
                    f"Showing previous {cached_tf} results until the next scan succeeds."
                )
            else:
                st.session_state["scan_rows"] = rows
                st.session_state["scan_sort_tf"] = sort_tf
                display_rows = rows
                display_tf = sort_tf
                if total_pairs > 0 and not rows:
                    scan_warning = (
                        f"No rows produced for {sort_tf} — try Refresh Now to clear stale cache."
                    )

            st.session_state["last_update"] = int(time.time())
            st.session_state["last_scan_count"] = scanned_count
        finally:
            st.session_state["scan_in_progress"] = False
    else:
        display_rows = cached_rows
        display_tf = cached_tf

    with results_ph.container():
        if scan_ran:
            scanned = st.session_state.get("last_scan_count", len(display_rows))
            st.success(f"✅ Scan complete — {scanned} pairs on {sort_tf}")
            if scan_warning:
                st.warning(scan_warning)
        elif config_stale and cached_rows:
            st.caption(
                f"Timeframe changed to {sort_tf} — rescan will run shortly. "
                f"Showing previous {cached_tf} results ({len(cached_rows)} pairs)."
            )
        elif scan_busy and scan_started:
            st.caption(f"Scan in progress ({int(scan_elapsed)}s)…")
        else:
            age = int(time.time()) - st.session_state.get("last_update", 0)
            next_scan = max(0, refresh_interval - age)
            st.caption(
                f"Showing cached results ({len(display_rows)} pairs, updated {age}s ago). "
                f"Next scan in {next_scan}s."
            )
        render_scan_results(display_rows, display_tf, hard_filter, interactive=True)

    if scan_ran:
        st.session_state["immediate_rescan"] = True


# =============================================================================
# MAIN DISPLAY
# =============================================================================
st.title("🚀 hioncrypto's: Crypto Tracker")

col1, col2, col3 = st.columns([1, 1, 2])
with col1:
    if st.button("🔄 Refresh Now", type="primary"):
        get_cached_data.clear()
        get_products.clear()
        st.session_state["ws_prices"] = {}
        stop_websocket_workers(clear_cache=True)
        st.session_state["last_update"] = 0
        st.session_state["scan_in_progress"] = False
        st.session_state.pop("scan_rows", None)
        st.rerun()

with col2:
    if st.button("🧹 Clear Cache"):
        get_cached_data.clear()
        get_products.clear()
        get_market_caps.clear()
        stop_websocket_workers(clear_cache=True)
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        init_session_state()
        clear_alerted_pairs()
        st.rerun()

with col3:
    ws_status_fragment = st_fragment(run_every=10)(ws_status_panel)
    ws_status_fragment()

refresh_interval = int(st.session_state.get("refresh_sec", 30))
scan_results_fragment = st_fragment(run_every=FRAGMENT_POLL_SEC)(scan_results_panel)
scan_results_fragment()

st.markdown("---")
st.caption("🚀 Enhanced Crypto Tracker with Progressive Alerts — by hioncrypto")
