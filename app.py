# app.py — Crypto Tracker by hioncrypto (one-file fix • v2)
# - Fix: tolerate old session_state["my_pairs"] being a list (backward compatible)
# - Sidebar tabs: soft blue
# - All settings persist via URL query params (bookmarkable)
# - Discovery evaluates ALL pairs (no "only A…")
# - Collapse/Expand All works and sticks

import json, time, datetime as dt, threading, queue, ssl, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import streamlit as st

# ----------------------------- Optional WebSocket
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

# ----------------------------- Constants
TF_LIST = ["15m","1h","4h","6h","12h","1d"]
ALL_TFS = {"15m":900,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400}

QUOTES = ["USD","USDC","USDT","BTC","ETH","EUR"]
EXCHANGES = ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"]

CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

DEFAULTS = dict(
    sort_tf = "1h",
    sort_desc = True,
    min_pct = 20.0,
    use_vol_spike = True,   vol_mult = 1.10, vol_window = 20,
    use_rsi = False,        rsi_len = 14,    min_rsi = 55,
    use_macd = True,        macd_fast = 12,  macd_slow = 26, macd_sig = 9, min_mhist = 0.0,
    use_atr = False,        atr_len = 14,    min_atr = 0.5,
    use_trend = True,       pivot_span = 4,  trend_within = 48,
    use_roc = True,         min_roc = 1.0,   roc_len = 14,
    K_green = 3,            Y_yellow = 2,
    basis = "Daily",        amount_daily = 90, amount_hourly = 24, amount_weekly = 12,
    refresh_sec = 30,
    quote = "USD",          exchange = "Coinbase",
    watchlist = "BTC-USD, ETH-USD, SOL-USD, AVAX-USD, ADA-USD, DOGE-USD, MATIC-USD",
)

# ----------------------------- Persistent settings via URL params
def _coerce(v, target_type):
    if target_type is bool:
        return str(v).lower() in {"1","true","yes","on"}
    if target_type is int:
        try: return int(v)
        except: return None
    if target_type is float:
        try: return float(v)
        except: return None
    return str(v)

PERSIST = {
    "exchange": (DEFAULTS["exchange"], str),
    "quote": (DEFAULTS["quote"], str),
    "use_watch": (False, bool),
    "watchlist": (DEFAULTS["watchlist"], str),

    "mode": ("REST only", str),
    "ws_chunk": (5, int),

    "sort_tf": (DEFAULTS["sort_tf"], str),
    "sort_desc": (True, bool),

    "min_pct": (DEFAULTS["min_pct"], float),
    "use_vol_spike": (DEFAULTS["use_vol_spike"], bool),
    "vol_mult": (DEFAULTS["vol_mult"], float),

    "use_rsi": (DEFAULTS["use_rsi"], bool),
    "min_rsi": (DEFAULTS["min_rsi"], int),

    "use_macd": (DEFAULTS["use_macd"], bool),
    "min_mhist": (DEFAULTS["min_mhist"], float),

    "use_atr": (DEFAULTS["use_atr"], bool),
    "min_atr": (DEFAULTS["min_atr"], float),

    "use_trend": (DEFAULTS["use_trend"], bool),
    "pivot_span": (DEFAULTS["pivot_span"], int),
    "trend_within": (DEFAULTS["trend_within"], int),

    "use_roc": (DEFAULTS["use_roc"], bool),
    "min_roc": (DEFAULTS["min]()_

