#!/usr/bin/env python3
"""
Kalshi BTC Price-to-beat chart server (Android PWA).

- Chart + moving price: CF Benchmarks BRTI (same index Kalshi uses)
- Price to beat, countdown, Yes/No %: always live Kalshi KXBTC15M
- Chart buttons 1m / 5m / 15m only change BRTI candle size
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8765"))
STATIC_DIR = Path(__file__).resolve().parent / "static"
DATA_DIR = Path(__file__).resolve().parent / "data"
PUSH_SUBS_FILE = DATA_DIR / "push_subscriptions.json"
DEMO_ACCOUNT_FILE = DATA_DIR / "demo_account.json"
VAPID_PRIVATE = DATA_DIR / "vapid_private.pem"
VAPID_PUBLIC_RAW = DATA_DIR / "vapid_public_raw.txt"
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:kalshi-btc-target@localhost")
DEMO_HISTORY_LIMIT = 80
_demo_lock = threading.Lock()


# Chart candle size + settlement window length (seconds) per TF.
TIMEFRAMES = {
    "1m": {
        "label": "1 minute",
        "granularity": 60,
        "window_sec": 60,
        # ~6h of 1m bars (CF BRTI alone only covers ~60m).
        "candle_limit": 360,
        "kalshi_series": ["KXBTC1M", "KXBTC15M"],
    },
    "5m": {
        "label": "5 minutes",
        "granularity": 300,
        "window_sec": 300,
        # ~24h of 5m bars.
        "candle_limit": 288,
        "kalshi_series": ["KXBTC5M", "KXBTC15M"],
    },
    "15m": {
        "label": "15 minutes",
        "granularity": 900,
        "window_sec": 900,
        # ~48h of 15m bars.
        "candle_limit": 192,
        "kalshi_series": ["KXBTC15M"],
    },
}

COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
COINBASE_TICKER = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
KALSHI_MARKETS = "https://api.elections.kalshi.com/trade-api/v2/markets"
# Same CF Benchmarks BRTI index Kalshi uses for BTC 15m charts / settlement.
CF_BRTI_VALUES = "https://www.cfbenchmarks.com/api/v1/values?id=BRTI"
CF_BASIC_USER = os.environ.get("CF_API_USER", "cfbenchmarksws2")
CF_BASIC_PASS = os.environ.get(
    "CF_API_PASS", "e3709a02-9876-45ea-ac46-e9020e06d7c6"
)

UA = "kalshi-btc-target/2.0 (+android-pwa)"

_cache_lock = threading.RLock()
_target_cache: dict = {}  # key -> {at, payload}
_candles_cache: dict = {"at": 0.0, "key": None, "payload": None}
_spot_cache: dict = {"at": 0.0, "payload": None}
_brti_cache: dict = {"at": 0.0, "ticks": None, "error": None}
_push_lock = threading.Lock()
_push_subs: list[dict] = []
_last_push_ticker: str | None = None
_last_edge_key: str | None = None
_last_edge_at: float = 0.0
_last_edge_gone_at: float = 0.0
_vapid_app_server_key: str | None = None
_vapid_private_path: str | None = None
TARGET_TTL = 0.75
CANDLES_TTL = 5.0
SPOT_TTL = 1.0
BRTI_TTL = 1.0
PUSH_POLL_SEC = 2.0
EDGE_PUSH_COOLDOWN_SEC = 120.0
EDGE_GONE_RESET_SEC = 60.0
SETTLE_WINDOW_SEC = 60.0
KALSHI_SERIES_URL = "https://kalshi.com/markets/kxbtc15m"


def _parse_dollars(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _dollars_to_pct_cents(value) -> int | None:
    """Kalshi UI shows whole cents truncated (0.999 → 99), not rounded (100)."""
    dollars = _parse_dollars(value)
    if dollars is None:
        return None
    dollars = max(0.0, min(1.0, dollars))
    return int(dollars * 100 + 1e-9)


def parse_close_ms(close_time) -> float | None:
    if not close_time:
        return None
    try:
        if isinstance(close_time, (int, float)):
            return float(close_time) * (1000 if close_time < 1e12 else 1)
        dt = datetime.fromisoformat(str(close_time).replace("Z", "+00:00"))
        return dt.timestamp() * 1000.0
    except Exception:
        return None


def parse_open_ms(open_time) -> float | None:
    return parse_close_ms(open_time)


def market_odds(market: dict) -> dict:
    """
    Yes/No % the way Kalshi's UI tends to show them.
    Prefer live bid/ask mid over a stale last trade right after a new
    15m window opens (last can still look like 1%/99% briefly).
    """
    last = _parse_dollars(market.get("last_price_dollars"))
    yes_bid = _parse_dollars(market.get("yes_bid_dollars"))
    yes_ask = _parse_dollars(market.get("yes_ask_dollars"))
    no_bid = _parse_dollars(market.get("no_bid_dollars"))
    no_ask = _parse_dollars(market.get("no_ask_dollars"))
    mid = None
    if yes_bid is not None and yes_ask is not None:
        mid = (yes_bid + yes_ask) / 2.0

    open_ms = parse_open_ms(market.get("open_time"))
    age_sec = None
    if open_ms is not None:
        age_sec = max(0.0, time.time() - open_ms / 1000.0)

    # Fresh window: lean on the book (near 50/50), not a leftover last print.
    fresh = age_sec is not None and age_sec < 90.0
    last_extreme = last is not None and (last <= 0.08 or last >= 0.92)

    if fresh:
        if mid is not None:
            yes = mid
        elif last is not None and not last_extreme:
            yes = last
        else:
            yes = 0.50
    elif mid is not None:
        # Prefer live book over last for displayable "fair" price.
        yes = mid
    elif last is not None:
        yes = last
    elif yes_bid is not None:
        yes = yes_bid
    elif yes_ask is not None:
        yes = yes_ask
    else:
        yes = None

    spread_cents = None
    if yes_bid is not None and yes_ask is not None:
        spread_cents = max(0, int(round((yes_ask - yes_bid) * 100)))

    if yes is None:
        return {
            "yes_pct": None,
            "no_pct": None,
            "yes_bid_pct": _dollars_to_pct_cents(yes_bid),
            "yes_ask_pct": _dollars_to_pct_cents(yes_ask),
            "no_bid_pct": _dollars_to_pct_cents(no_bid),
            "no_ask_pct": _dollars_to_pct_cents(no_ask),
            "last_pct": _dollars_to_pct_cents(last),
            "spread_cents": spread_cents,
            "odds_fresh": fresh,
            "thin_book": spread_cents is not None and spread_cents >= 5,
        }

    yes_pct = int(max(0.0, min(1.0, yes)) * 100 + 1e-9)
    live = market.get("status") in ("active", "open", "initialized")
    if live:
        yes_pct = min(99, max(1, yes_pct))
    no_pct = 100 - yes_pct

    return {
        "yes_pct": yes_pct,
        "no_pct": no_pct,
        "yes_bid_pct": _dollars_to_pct_cents(yes_bid),
        "yes_ask_pct": _dollars_to_pct_cents(yes_ask),
        "no_bid_pct": _dollars_to_pct_cents(no_bid),
        "no_ask_pct": _dollars_to_pct_cents(no_ask),
        "last_pct": _dollars_to_pct_cents(last),
        "spread_cents": spread_cents,
        "odds_fresh": bool(fresh),
        "thin_book": bool(spread_cents is not None and spread_cents >= 5),
    }


def kalshi_market_url(ticker: str | None, event_ticker: str | None) -> str:
    if event_ticker:
        return f"{KALSHI_SERIES_URL}/{str(event_ticker).lower()}"
    if ticker:
        return f"{KALSHI_SERIES_URL}/{str(ticker).lower()}"
    return KALSHI_SERIES_URL


def pick_current_market(markets: list) -> dict | None:
    """
    Pick the *current* 15m window — newest market that has already opened
    and has not closed yet. Never cling to an expired market.
    """
    now_ms = time.time() * 1000.0
    openish = [
        m
        for m in markets
        if m.get("status") in ("active", "open", "initialized")
    ] or list(markets)

    current = []
    for m in openish:
        open_ms = parse_open_ms(m.get("open_time"))
        close_ms = parse_close_ms(m.get("close_time"))
        if close_ms is None:
            continue
        # Strict: do not keep markets after close.
        if close_ms <= now_ms:
            continue
        # Prefer markets that have opened (or are about to within 3s).
        if open_ms is not None and open_ms > now_ms + 3_000:
            continue
        remaining = close_ms - now_ms
        current.append((open_ms or 0.0, remaining, m))

    if current:
        # Newest open_time first; among ties, more time remaining.
        current.sort(key=lambda x: (x[0], x[1]), reverse=True)
        # If the newest has almost no time left but a later window already
        # opened, prefer the later one.
        best = current[0]
        for cand in current:
            if cand[0] > best[0] and cand[1] > 5_000:
                best = cand
                break
        # Prefer a market that already has Price to beat among the newest cohort.
        newest_open = current[0][0]
        cohort = [p for p in current if abs(p[0] - newest_open) < 1_000]
        with_target = [p for p in cohort if parse_target(p[2]) is not None]
        return (with_target or cohort or current)[0][2]

    # No live window: next upcoming open (rollover gap).
    upcoming = []
    for m in openish:
        open_ms = parse_open_ms(m.get("open_time"))
        close_ms = parse_close_ms(m.get("close_time"))
        if open_ms is None or close_ms is None:
            continue
        if open_ms >= now_ms - 5_000 and close_ms > now_ms:
            upcoming.append((open_ms, m))
    if upcoming:
        upcoming.sort(key=lambda x: x[0])
        return upcoming[0][1]
    return None


def brti_settlement_snapshot(
    ticks: list[dict], close_ms: float | None, beat: float | None
) -> dict:
    """
    Kalshi crypto settlement = average of 60 BRTI 1s samples in the final minute.
    While that minute is running, return the running average of samples so far.
    """
    now_ms = time.time() * 1000.0
    out = {
        "settlement_mode": False,
        "settlement_avg": None,
        "settlement_samples": 0,
        "settlement_delta": None,
        "settlement_side": None,  # above | below | null
        "seconds_to_close": None,
        "settle_window_sec": SETTLE_WINDOW_SEC,
    }
    if close_ms is None:
        return out
    seconds_to_close = (close_ms - now_ms) / 1000.0
    out["seconds_to_close"] = seconds_to_close
    window_start = close_ms - SETTLE_WINDOW_SEC * 1000.0
    # Enter settlement mode in the final minute (and briefly after close).
    if seconds_to_close > SETTLE_WINDOW_SEC:
        return out
    out["settlement_mode"] = True
    end_ms = min(now_ms, close_ms)
    samples = [
        float(t["value"])
        for t in ticks
        if window_start <= float(t["time_ms"]) <= end_ms
    ]
    # One sample per second bucket if we somehow get duplicates.
    if not samples and ticks:
        # Fall back to last ≤60 ticks before end.
        prior = [t for t in ticks if float(t["time_ms"]) <= end_ms]
        samples = [float(t["value"]) for t in prior[-60:]]
    out["settlement_samples"] = len(samples)
    if not samples:
        return out
    avg = sum(samples) / len(samples)
    # Kalshi rounds settlement-style values to 2 decimals in practice.
    avg = round(avg, 2)
    out["settlement_avg"] = avg
    if beat is not None and Number_is_finite(beat):
        delta = avg - float(beat)
        out["settlement_delta"] = round(delta, 2)
        out["settlement_side"] = "above" if delta >= 0 else "below"
    return out


def Number_is_finite(x) -> bool:
    try:
        return x is not None and float(x) == float(x) and abs(float(x)) != float("inf")
    except (TypeError, ValueError):
        return False


def http_get_json(url: str, timeout: float = 20.0, headers: dict | None = None):
    hdrs = {"Accept": "application/json", "User-Agent": UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def http_get_json_basic(url: str, user: str, password: str, timeout: float = 20.0):
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return http_get_json(
        url,
        timeout=timeout,
        headers={"Authorization": f"Basic {token}"},
    )


def fetch_brti_ticks(force: bool = False) -> list[dict]:
    """1-second CF Benchmarks BRTI ticks (≈ last 60 minutes)."""
    now = time.time()
    with _cache_lock:
        if (
            not force
            and _brti_cache["ticks"]
            and now - _brti_cache["at"] < BRTI_TTL
        ):
            return _brti_cache["ticks"]
    data = http_get_json_basic(CF_BRTI_VALUES, CF_BASIC_USER, CF_BASIC_PASS)
    payload = data.get("payload") or []
    ticks = []
    for row in payload:
        try:
            ticks.append(
                {
                    "time_ms": int(row["time"]),
                    "value": float(row["value"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    ticks.sort(key=lambda t: t["time_ms"])
    with _cache_lock:
        _brti_cache["at"] = time.time()
        _brti_cache["ticks"] = ticks
        _brti_cache["error"] = None
    return ticks


def brti_to_candles(ticks: list[dict], granularity: int, limit: int) -> list[dict]:
    """Resample 1s BRTI ticks into OHLC candles (same index Kalshi charts)."""
    buckets: dict[int, list[float]] = {}
    for tick in ticks:
        ts = int(tick["time_ms"] // 1000)
        bucket = ts - (ts % granularity)
        v = float(tick["value"])
        if bucket not in buckets:
            buckets[bucket] = [v, v, v, v]  # o,h,l,c
        else:
            o, h, l, c = buckets[bucket]
            buckets[bucket] = [o, max(h, v), min(l, v), v]
    candles = [
        {
            "time": t,
            "open": ohlc[0],
            "high": ohlc[1],
            "low": ohlc[2],
            "close": ohlc[3],
        }
        for t, ohlc in sorted(buckets.items())
    ]
    return candles[-limit:]


def fetch_coinbase_candles(granularity: int, limit: int) -> list[dict]:
    """Paginate Coinbase BTC-USD candles (API returns ≤300 bars per request)."""
    if limit <= 0:
        return []
    per_page = 300
    pages = max(1, (limit + per_page - 1) // per_page)
    by_time: dict[int, dict] = {}
    t_end = int(time.time())
    for _ in range(pages):
        t_start = t_end - granularity * per_page
        qs = urllib.parse.urlencode(
            {
                "granularity": granularity,
                "start": datetime.fromtimestamp(t_start, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "end": datetime.fromtimestamp(t_end, tz=timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        )
        raw = http_get_json(f"{COINBASE_CANDLES}?{qs}")
        if not isinstance(raw, list) or not raw:
            break
        oldest = None
        for r in raw:
            try:
                t = int(r[0])
                by_time[t] = {
                    "time": t,
                    "open": float(r[3]),
                    "high": float(r[2]),
                    "low": float(r[1]),
                    "close": float(r[4]),
                }
                if oldest is None or t < oldest:
                    oldest = t
            except (TypeError, ValueError, IndexError):
                continue
        if oldest is None:
            break
        t_end = oldest
        if len(by_time) >= limit:
            break
    return [by_time[t] for t in sorted(by_time)][-limit:]


def merge_candle_history(
    history: list[dict], tip: list[dict], limit: int
) -> list[dict]:
    """Stitch longer exchange history with recent BRTI tip (BRTI wins on overlap)."""
    by_time: dict[int, dict] = {int(c["time"]): c for c in history}
    for c in tip:
        by_time[int(c["time"])] = c
    return [by_time[t] for t in sorted(by_time)][-limit:]


def parse_target(market: dict) -> float | None:
    floor = market.get("floor_strike")
    if isinstance(floor, (int, float)):
        return float(floor)
    sub = market.get("yes_sub_title") or ""
    m = re.search(r"Target\s*Price:\s*\$?\s*([0-9,]+(?:\.\d+)?)", sub, re.I)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def format_et(ts_iso_or_unix) -> str | None:
    try:
        if isinstance(ts_iso_or_unix, (int, float)):
            dt = datetime.fromtimestamp(ts_iso_or_unix, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(ts_iso_or_unix).replace("Z", "+00:00"))
        dt = dt.astimezone(ZoneInfo("America/New_York"))
        return (
            dt.strftime("%I:%M%p ET")
            .lstrip("0")
            .replace("AM", "am")
            .replace("PM", "pm")
        )
    except Exception:
        return None


def fetch_kalshi_markets(series: str) -> list:
    """Open markets plus nearby unopened windows (for seamless rollover)."""
    markets: list = []
    seen = set()
    queries = [
        f"{KALSHI_MARKETS}?limit=30&status=open&series_ticker={urllib.parse.quote(series)}",
        f"{KALSHI_MARKETS}?limit=40&status=unopened&series_ticker={urllib.parse.quote(series)}",
    ]
    for url in queries:
        try:
            data = http_get_json(url, timeout=12.0)
        except Exception:
            continue
        for m in data.get("markets") or []:
            ticker = m.get("ticker")
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            markets.append(m)
    return markets


def fetch_kalshi_series_target(series: str) -> dict | None:
    markets = fetch_kalshi_markets(series)
    if not markets:
        return None
    market = pick_current_market(markets)
    if not market:
        return {
            "ok": False,
            "source": "kalshi",
            "series": series,
            "target": None,
            "price_to_beat": None,
            "ticker": None,
            "event_ticker": None,
            "kalshi_url": KALSHI_SERIES_URL,
            "open_time": None,
            "close_time": None,
            "close_et": None,
            "subtitle": None,
            "title": None,
            "label": "Price to beat",
            "yes_pct": None,
            "no_pct": None,
            "yes_bid_pct": None,
            "yes_ask_pct": None,
            "no_bid_pct": None,
            "no_ask_pct": None,
            "last_pct": None,
            "spread_cents": None,
            "odds_fresh": False,
            "thin_book": False,
            "stale_previous": True,
            "waiting_next": True,
            "settlement_mode": False,
            "settlement_avg": None,
            "settlement_samples": 0,
            "settlement_delta": None,
            "settlement_side": None,
            "error": "Waiting for next Kalshi 15m market…",
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    target = parse_target(market)
    close_et = format_et(market.get("close_time"))
    odds = market_odds(market)
    close_ms = parse_close_ms(market.get("close_time"))
    open_ms = parse_open_ms(market.get("open_time"))
    now_ms = time.time() * 1000.0
    stale_previous = bool(close_ms is not None and close_ms <= now_ms)
    waiting_next = bool(open_ms is not None and open_ms > now_ms)

    settle = {
        "settlement_mode": False,
        "settlement_avg": None,
        "settlement_samples": 0,
        "settlement_delta": None,
        "settlement_side": None,
        "seconds_to_close": None,
        "settle_window_sec": SETTLE_WINDOW_SEC,
    }
    try:
        ticks = fetch_brti_ticks()
        settle = brti_settlement_snapshot(ticks, close_ms, target)
    except Exception:
        pass

    return {
        "ok": True,
        "source": "kalshi",
        "series": series,
        "target": target,
        "price_to_beat": target,
        "ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "kalshi_url": kalshi_market_url(market.get("ticker"), market.get("event_ticker")),
        "open_time": market.get("open_time"),
        "close_time": market.get("close_time"),
        "close_et": close_et,
        "subtitle": market.get("yes_sub_title"),
        "title": market.get("title") or "BTC above or below in 15 minutes?",
        "label": f"Price to beat · {close_et}" if close_et else "Price to beat",
        "yes_pct": odds["yes_pct"],
        "no_pct": odds["no_pct"],
        "yes_bid_pct": odds.get("yes_bid_pct"),
        "yes_ask_pct": odds.get("yes_ask_pct"),
        "no_bid_pct": odds.get("no_bid_pct"),
        "no_ask_pct": odds.get("no_ask_pct"),
        "last_pct": odds.get("last_pct"),
        "spread_cents": odds.get("spread_cents"),
        "odds_fresh": odds.get("odds_fresh"),
        "thin_book": odds.get("thin_book"),
        "stale_previous": stale_previous,
        "waiting_next": waiting_next,
        "settlement_mode": settle.get("settlement_mode"),
        "settlement_avg": settle.get("settlement_avg"),
        "settlement_samples": settle.get("settlement_samples"),
        "settlement_delta": settle.get("settlement_delta"),
        "settlement_side": settle.get("settlement_side"),
        "seconds_to_close": settle.get("seconds_to_close"),
        "error": None
        if target is not None
        else "Price to beat TBD (waiting for window open)",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def fetch_target_payload(tf: str = "15m") -> dict:
    """
    Price to beat is ALWAYS the live Kalshi KXBTC15M market.

    Chart timeframe (1m/5m/15m) only affects candles on the client — never the
    Kalshi target, countdown, or Above/Below odds.
    """
    _ = tf
    cache_key = "15m"
    now = time.time()
    cached_payload = None
    refresh_settle = False
    close_ms = None
    with _cache_lock:
        cached = _target_cache.get(cache_key)
        if cached:
            payload = cached["payload"] or {}
            close_ms = parse_close_ms(payload.get("close_time"))
            expired = close_ms is not None and close_ms <= now * 1000.0
            settling = bool(payload.get("settlement_mode"))
            age = now - cached["at"]
            ttl = (
                0.35
                if expired or settling or payload.get("price_to_beat") is None
                else TARGET_TTL
            )
            if not expired and age < ttl:
                if settling:
                    # Refresh settlement outside the lock (avoids deadlock).
                    cached_payload = dict(payload)
                    refresh_settle = True
                else:
                    return payload

    if refresh_settle and cached_payload is not None:
        try:
            ticks = fetch_brti_ticks()
            settle = brti_settlement_snapshot(
                ticks, close_ms, cached_payload.get("price_to_beat")
            )
            cached_payload.update(settle)
            with _cache_lock:
                _target_cache[cache_key] = {"at": time.time(), "payload": cached_payload}
            return cached_payload
        except Exception:
            return cached_payload

    payload = fetch_kalshi_series_target("KXBTC15M")
    if payload:
        payload["timeframe"] = "15m"
        payload["chart_tf_hint"] = "candles only — target is always Kalshi 15m"
    else:
        # Fail closed — never present Coinbase as Kalshi Price to beat.
        payload = {
            "ok": False,
            "source": "kalshi",
            "series": "KXBTC15M",
            "timeframe": "15m",
            "target": None,
            "price_to_beat": None,
            "ticker": None,
            "event_ticker": None,
            "kalshi_url": KALSHI_SERIES_URL,
            "yes_pct": None,
            "no_pct": None,
            "stale_previous": True,
            "waiting_next": True,
            "settlement_mode": False,
            "error": "Kalshi unreachable — pull to refresh",
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    with _cache_lock:
        _target_cache[cache_key] = {"at": time.time(), "payload": payload}
    return payload


def fetch_spot() -> dict:
    """Live moving price = CF Benchmarks BRTI (same source Kalshi uses)."""
    now = time.time()
    with _cache_lock:
        if _spot_cache["payload"] and now - _spot_cache["at"] < SPOT_TTL:
            return _spot_cache["payload"]
    try:
        ticks = fetch_brti_ticks()
        if not ticks:
            raise RuntimeError("No BRTI ticks")
        last = ticks[-1]
        payload = {
            "ok": True,
            "symbol": "BRTI",
            "source": "cf_benchmarks",
            "label": "CF BRTI (Kalshi)",
            "price": float(last["value"]),
            "time": datetime.fromtimestamp(
                last["time_ms"] / 1000.0, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bid": None,
            "ask": None,
            "error": None,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    except Exception as exc:
        # Fallback only if CF is down — still label clearly.
        try:
            data = http_get_json(COINBASE_TICKER)
            price = float(data.get("price"))
            payload = {
                "ok": True,
                "symbol": "BTC-USD",
                "source": "coinbase_fallback",
                "label": "Coinbase (BRTI unavailable)",
                "price": price,
                "bid": float(data["bid"]) if data.get("bid") is not None else None,
                "ask": float(data["ask"]) if data.get("ask") is not None else None,
                "time": data.get("time"),
                "error": f"BRTI fallback: {exc}",
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        except Exception as exc2:
            payload = {
                "ok": False,
                "symbol": "BRTI",
                "source": None,
                "price": None,
                "error": f"BRTI: {exc}; Coinbase: {exc2}",
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
    with _cache_lock:
        _spot_cache["at"] = time.time()
        _spot_cache["payload"] = payload
    return payload


def fetch_candles(granularity: int = 60, limit: int = 300) -> dict:
    """Chart candles: Coinbase history + CF BRTI tip (Kalshi's index).

    CF BRTI values only cover ~60 minutes. Coinbase fills older bars so the
    chart shows multi-hour (or multi-day) price history; recent bars prefer BRTI.
    """
    now = time.time()
    key = (granularity, limit, "brti+coinbase")
    with _cache_lock:
        if (
            _candles_cache["payload"]
            and _candles_cache["key"] == key
            and now - _candles_cache["at"] < CANDLES_TTL
        ):
            return _candles_cache["payload"]

    brti_candles: list[dict] = []
    brti_err: Exception | None = None
    try:
        ticks = fetch_brti_ticks()
        brti_candles = brti_to_candles(ticks, granularity, limit)
        if not brti_candles:
            raise RuntimeError("No BRTI candles")
    except Exception as exc:
        brti_err = exc

    cb_candles: list[dict] = []
    cb_err: Exception | None = None
    try:
        cb_candles = fetch_coinbase_candles(granularity, limit)
        if not cb_candles:
            raise RuntimeError("No Coinbase candles")
    except Exception as exc:
        cb_err = exc

    fetched_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if brti_candles and cb_candles:
        candles = merge_candle_history(cb_candles, brti_candles, limit)
        payload = {
            "ok": True,
            "symbol": "BRTI",
            "source": "cf_benchmarks+coinbase",
            "label": "BRTI tip + Coinbase history",
            "granularity": granularity,
            "candles": candles,
            "brti_bars": len(brti_candles),
            "history_bars": len(cb_candles),
            "error": None,
            "fetched_at": fetched_at,
        }
    elif brti_candles:
        payload = {
            "ok": True,
            "symbol": "BRTI",
            "source": "cf_benchmarks",
            "label": "CF BRTI (Kalshi)",
            "granularity": granularity,
            "candles": brti_candles[-limit:],
            "error": f"Coinbase history unavailable: {cb_err}" if cb_err else None,
            "fetched_at": fetched_at,
        }
    elif cb_candles:
        payload = {
            "ok": True,
            "symbol": "BTC-USD",
            "source": "coinbase_fallback",
            "label": "Coinbase (BRTI unavailable)",
            "granularity": granularity,
            "candles": cb_candles[-limit:],
            "error": f"BRTI fallback: {brti_err}",
            "fetched_at": fetched_at,
        }
    else:
        payload = {
            "ok": False,
            "symbol": "BRTI",
            "source": None,
            "granularity": granularity,
            "candles": [],
            "error": f"BRTI: {brti_err}; Coinbase: {cb_err}",
            "fetched_at": fetched_at,
        }

    with _cache_lock:
        _candles_cache["at"] = time.time()
        _candles_cache["key"] = key
        _candles_cache["payload"] = payload
    return payload


def ensure_vapid_keys() -> tuple[str | None, str | None]:
    """Return (applicationServerKey, private_pem_path)."""
    global _vapid_app_server_key, _vapid_private_path
    if _vapid_app_server_key and _vapid_private_path:
        return _vapid_app_server_key, _vapid_private_path
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid
    except Exception as exc:
        print(f"[kalshi-btc-target] Web Push unavailable (install pywebpush): {exc}")
        return None, None

    vapid = Vapid()
    if VAPID_PRIVATE.is_file() and VAPID_PUBLIC_RAW.is_file():
        vapid = Vapid.from_file(str(VAPID_PRIVATE))
        app_key = VAPID_PUBLIC_RAW.read_text().strip()
    else:
        vapid.generate_keys()
        vapid.save_key(str(VAPID_PRIVATE))
        raw = vapid.public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint,
        )
        app_key = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        VAPID_PUBLIC_RAW.write_text(app_key)

    _vapid_app_server_key = app_key
    _vapid_private_path = str(VAPID_PRIVATE)
    return _vapid_app_server_key, _vapid_private_path


def load_push_subs() -> None:
    global _push_subs
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not PUSH_SUBS_FILE.is_file():
        _push_subs = []
        return
    try:
        _push_subs = json.loads(PUSH_SUBS_FILE.read_text())
        if not isinstance(_push_subs, list):
            _push_subs = []
    except Exception:
        _push_subs = []


def _normalize_demo_account(raw: dict | None) -> dict | None:
    """Single-user BeatLine demo account (survives tunnel URL changes)."""
    if not isinstance(raw, dict):
        return None
    history = raw.get("history")
    if not isinstance(history, list):
        history = []
    history = [h for h in history if isinstance(h, dict)][:DEMO_HISTORY_LIMIT]
    start = raw.get("start")
    balance = raw.get("balance")
    realized = raw.get("realizedPl")
    try:
        start_n = float(start) if start is not None else 1000.0
    except (TypeError, ValueError):
        start_n = 1000.0
    try:
        balance_n = float(balance) if balance is not None else start_n
    except (TypeError, ValueError):
        balance_n = start_n
    try:
        realized_n = float(realized) if realized is not None else 0.0
    except (TypeError, ValueError):
        realized_n = 0.0
    updated = raw.get("updatedAt")
    try:
        updated_n = int(updated) if updated is not None else int(time.time() * 1000)
    except (TypeError, ValueError):
        updated_n = int(time.time() * 1000)
    position = raw.get("position")
    if not isinstance(position, dict):
        position = None
    last_result = raw.get("lastResult")
    if not isinstance(last_result, dict):
        last_result = None
    return {
        "on": bool(raw.get("on")),
        "start": start_n,
        "balance": balance_n,
        "realizedPl": realized_n,
        "position": position,
        "lastResult": last_result,
        "history": history,
        "updatedAt": updated_n,
    }


def load_demo_account() -> dict | None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DEMO_ACCOUNT_FILE.is_file():
        return None
    try:
        with _demo_lock:
            raw = json.loads(DEMO_ACCOUNT_FILE.read_text())
        return _normalize_demo_account(raw if isinstance(raw, dict) else None)
    except Exception:
        return None


def save_demo_account(raw: dict) -> dict | None:
    normalized = _normalize_demo_account(raw)
    if not normalized:
        return None
    if not normalized.get("updatedAt"):
        normalized["updatedAt"] = int(time.time() * 1000)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _demo_lock:
        tmp = DEMO_ACCOUNT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(normalized, indent=2))
        tmp.replace(DEMO_ACCOUNT_FILE)
    return normalized


def save_push_subs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _push_lock:
        payload = json.dumps(_push_subs, indent=2)
    PUSH_SUBS_FILE.write_text(payload)


def upsert_push_sub(sub: dict) -> None:
    endpoint = (sub or {}).get("endpoint")
    if not endpoint:
        return
    with _push_lock:
        _push_subs[:] = [s for s in _push_subs if s.get("endpoint") != endpoint]
        _push_subs.append(sub)
    save_push_subs()


def remove_push_sub(endpoint: str) -> None:
    if not endpoint:
        return
    with _push_lock:
        _push_subs[:] = [s for s in _push_subs if s.get("endpoint") != endpoint]
    save_push_subs()


def send_web_push(payload: dict) -> int:
    app_key, priv = ensure_vapid_keys()
    if not app_key or not priv:
        return 0
    try:
        from pywebpush import webpush, WebPushException
    except Exception as exc:
        print(f"[kalshi-btc-target] pywebpush missing: {exc}")
        return 0

    body = json.dumps(payload)
    sent = 0
    dead: list[str] = []
    with _push_lock:
        subs = list(_push_subs)
    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=body,
                vapid_private_key=priv,
                vapid_claims={"sub": VAPID_SUBJECT},
                ttl=120,
            )
            sent += 1
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            msg = str(exc)
            if status in (404, 410) or "410" in msg or "404" in msg:
                dead.append(sub.get("endpoint") or "")
            else:
                print(f"[kalshi-btc-target] push failed: {exc}")
    for endpoint in dead:
        remove_push_sub(endpoint)
    return sent


def _usable_ask_cents(ask_pct) -> int | None:
    if ask_pct is None:
        return None
    try:
        n = int(round(float(ask_pct)))
    except (TypeError, ValueError):
        return None
    if n < 2 or n > 98:
        return None
    return n


def _model_prob_above(
    spot: float,
    beat: float,
    secs_left: float,
    settlement_mode: bool,
    settlement_side: str | None,
    settlement_avg: float | None,
) -> float | None:
    if settlement_mode and settlement_side == "above":
        return 0.97
    if settlement_mode and settlement_side == "below":
        return 0.03
    if (
        settlement_mode
        and settlement_avg is not None
        and math.isfinite(settlement_avg)
    ):
        d = float(settlement_avg) - float(beat)
        sigma = max(8.0, abs(float(beat)) * 0.00015)
        return 0.5 * (1.0 + math.erf((d / sigma) / math.sqrt(2.0)))
    t = max(1.0, float(secs_left) or 1.0)
    sigma = max(8.0, abs(float(beat)) * 0.55 * math.sqrt(t / (365.25 * 24 * 3600)))
    return 0.5 * (1.0 + math.erf(((float(spot) - float(beat)) / sigma) / math.sqrt(2.0)))


def _kalshi_taker_fee(contracts: int, price: float) -> float:
    c = max(0, contracts)
    p = min(0.99, max(0.01, price))
    raw = 0.07 * c * p * (1.0 - p)
    return math.ceil(raw * 100 - 1e-9) / 100.0


def score_clear_edge(data: dict, spot: float | None) -> dict | None:
    """Mirror client Best Side clear-edge thresholds for background push."""
    if spot is None or not math.isfinite(float(spot)):
        return None
    beat = data.get("price_to_beat")
    if beat is None:
        beat = data.get("target")
    if beat is None or not math.isfinite(float(beat)):
        return None

    close_iso = data.get("close_time")
    if not close_iso:
        return None
    try:
        close_dt = datetime.fromisoformat(str(close_iso).replace("Z", "+00:00"))
        secs = max(0.0, (close_dt.timestamp() - time.time()))
    except Exception:
        return None

    above_ask = _usable_ask_cents(data.get("yes_ask_pct"))
    below_ask = _usable_ask_cents(data.get("no_ask_pct"))
    # Prefer mid-based asks when extreme settlement quotes appear.
    yes = data.get("yes_pct")
    no = data.get("no_pct")
    if above_ask is None and yes is not None:
        try:
            above_ask = _usable_ask_cents(max(2, min(98, round(float(yes)))))
        except (TypeError, ValueError):
            above_ask = None
    if below_ask is None and no is not None:
        try:
            below_ask = _usable_ask_cents(max(2, min(98, round(float(no)))))
        except (TypeError, ValueError):
            below_ask = None
    if above_ask is None and below_ask is None:
        return None

    model = _model_prob_above(
        float(spot),
        float(beat),
        secs,
        bool(data.get("settlement_mode")),
        data.get("settlement_side"),
        data.get("settlement_avg"),
    )
    if model is None:
        return None

    scored = []
    for side, ask in (("above", above_ask), ("below", below_ask)):
        if ask is None:
            continue
        p = ask / 100.0
        fee = _kalshi_taker_fee(1, p)
        cost_per = p + fee
        p_win = model if side == "above" else 1.0 - model
        ev = p_win * 1.0 - cost_per
        risk = max(0.04, 1.0 - p_win)
        scored.append(
            {
                "side": side,
                "ask_cents": ask,
                "p_win": p_win,
                "ev": ev,
                "score": ev / risk,
            }
        )
    if not scored:
        return None
    scored.sort(key=lambda x: x["score"], reverse=True)
    best = scored[0]
    if data.get("thin_book"):
        best = {**best, "score": best["score"] - 0.08}
    clear = (
        best["ev"] > 0.01
        and best["score"] > 0.04
        and best["p_win"] >= 0.52
        and not (secs > 12 * 60 and abs(best["ev"]) < 0.03)
    )
    if not clear:
        return None
    return best


def push_watcher_loop() -> None:
    """Poll Kalshi and push to phones even when the PWA is backgrounded."""
    global _last_push_ticker, _last_edge_key, _last_edge_at, _last_edge_gone_at
    print("[kalshi-btc-target] background push watcher started")
    while True:
        try:
            data = fetch_target_payload("15m")
            ticker = data.get("ticker")
            beat = data.get("price_to_beat")
            if beat is None:
                beat = data.get("target")
            if (
                ticker
                and _last_push_ticker
                and ticker != _last_push_ticker
                and data.get("source") == "kalshi"
            ):
                n = send_web_push(
                    {
                        "type": "new_target",
                        "ticker": ticker,
                        "beat": beat,
                        "price_to_beat": beat,
                        "target": beat,
                        "close_et": data.get("close_et"),
                        "close_time": data.get("close_time"),
                    }
                )
                print(
                    f"[kalshi-btc-target] new 15m target {ticker} "
                    f"beat={beat} pushed={n}"
                )
                _last_edge_key = None
                _last_edge_gone_at = 0.0
            if ticker:
                _last_push_ticker = ticker

            # Clear-edge Best Side push (same thresholds as the app).
            spot = None
            try:
                spot_payload = fetch_spot()
                if spot_payload.get("ok"):
                    spot = spot_payload.get("price")
            except Exception:
                spot = None
            edge = score_clear_edge(data, spot)
            now = time.time()
            if edge:
                key = f"{edge['side']}:{edge['ask_cents']}"
                cooled = now - _last_edge_at >= EDGE_PUSH_COOLDOWN_SEC
                if key != _last_edge_key and cooled:
                    n = send_web_push(
                        {
                            "type": "clear_edge",
                            "side": edge["side"],
                            "ask_cents": edge["ask_cents"],
                            "p_win": edge["p_win"],
                            "ticker": ticker,
                            "beat": beat,
                            "price_to_beat": beat,
                            "target": beat,
                        }
                    )
                    print(
                        f"[kalshi-btc-target] clear edge {edge['side']} "
                        f"ask={edge['ask_cents']}¢ pushed={n}"
                    )
                    _last_edge_key = key
                    _last_edge_at = now
                _last_edge_gone_at = 0.0
            else:
                # Only forget the edge after it has been gone for a while —
                # prevents push loops when the score flickers around threshold.
                if _last_edge_key is not None:
                    if not _last_edge_gone_at:
                        _last_edge_gone_at = now
                    elif now - _last_edge_gone_at >= EDGE_GONE_RESET_SEC:
                        _last_edge_key = None
                        _last_edge_gone_at = 0.0
        except Exception as exc:
            print(f"[kalshi-btc-target] push watcher error: {exc}")
        time.sleep(PUSH_POLL_SEC)


class Handler(BaseHTTPRequestHandler):
    server_version = "KalshiBtcTarget/2.0"

    def log_message(self, fmt, *args):
        print(f"[kalshi-btc-target] {self.address_string()} {fmt % args}")

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj: dict):
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            obj = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return {}
        return obj if isinstance(obj, dict) else {}

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_json_body()

        if path == "/api/push/subscribe":
            sub = body.get("subscription") if isinstance(body.get("subscription"), dict) else body
            if not sub.get("endpoint") or not sub.get("keys"):
                self._send_json(400, {"ok": False, "error": "invalid subscription"})
                return
            upsert_push_sub(sub)
            self._send_json(200, {"ok": True, "subscribers": len(_push_subs)})
            return

        if path == "/api/push/unsubscribe":
            endpoint = body.get("endpoint") or ""
            remove_push_sub(endpoint)
            self._send_json(200, {"ok": True, "subscribers": len(_push_subs)})
            return

        if path == "/api/push/test":
            n = send_web_push(
                {
                    "type": "test",
                    "beat": body.get("beat"),
                    "ticker": "TEST",
                    "close_et": body.get("close_et"),
                }
            )
            self._send_json(200, {"ok": True, "pushed": n})
            return

        if path == "/api/push/link":
            url = str(body.get("url") or "").strip()
            if not url.startswith("https://"):
                self._send_json(400, {"ok": False, "error": "https url required"})
                return
            n = send_web_push({"type": "new_link", "url": url})
            self._send_json(200, {"ok": True, "pushed": n, "url": url})
            return

        if path in ("/api/demo-account", "/api/account"):
            state = body.get("state") if isinstance(body.get("state"), dict) else body
            saved = save_demo_account(state)
            if not saved:
                self._send_json(400, {"ok": False, "error": "invalid demo account"})
                return
            self._send_json(200, {"ok": True, "state": saved})
            return

        self._send_json(404, {"ok": False, "error": "not found"})

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if path == "/api/timeframes":
            self._send_json(
                200,
                {
                    "ok": True,
                    "default": "15m",
                    "timeframes": [
                        {
                            "id": key,
                            "label": cfg["label"],
                            "granularity": cfg["granularity"],
                            "window_sec": cfg["window_sec"],
                        }
                        for key, cfg in TIMEFRAMES.items()
                    ],
                },
            )
            return

        if path in ("/api/target", "/api/kalshi/target"):
            tf = (qs.get("tf") or qs.get("timeframe") or ["15m"])[0].strip().lower()
            self._send_json(200, fetch_target_payload(tf))
            return

        if path in ("/api/spot", "/api/btc/spot", "/api/price"):
            self._send_json(200, fetch_spot())
            return

        if path in ("/api/candles", "/api/btc/candles"):
            tf = (qs.get("tf") or qs.get("timeframe") or [""])[0].strip().lower()
            cfg = TIMEFRAMES.get(tf)
            if cfg:
                gran = cfg["granularity"]
                limit = cfg["candle_limit"]
            else:
                try:
                    gran = int((qs.get("granularity") or ["60"])[0])
                except ValueError:
                    gran = 60
                if gran not in (60, 300, 900, 3600):
                    gran = 60
                try:
                    limit = int((qs.get("limit") or ["300"])[0])
                except ValueError:
                    limit = 300
                limit = max(50, min(limit, 300))
            payload = fetch_candles(gran, limit)
            payload["timeframe"] = tf or None
            self._send_json(200, payload)
            return

        if path == "/api/push/vapid-public":
            app_key, _priv = ensure_vapid_keys()
            self._send_json(
                200,
                {
                    "ok": bool(app_key),
                    "publicKey": app_key,
                    "subscribers": len(_push_subs),
                },
            )
            return

        if path in ("/api/demo-account", "/api/account"):
            state = load_demo_account()
            self._send_json(
                200,
                {
                    "ok": True,
                    "state": state,
                    "has_state": state is not None,
                },
            )
            return

        if path == "/api/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "kalshi-btc-target",
                    "version": "2.1.0",
                    "push": bool(_vapid_app_server_key or VAPID_PUBLIC_RAW.is_file()),
                    "subscribers": len(_push_subs),
                    "demo_account": DEMO_ACCOUNT_FILE.is_file(),
                },
            )
            return

        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        if ".." in rel or rel.startswith("/"):
            self._send_json(400, {"ok": False, "error": "bad path"})
            return
        file_path = (STATIC_DIR / rel).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.is_file():
            self._send_json(404, {"ok": False, "error": "not found"})
            return

        data = file_path.read_bytes()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".user.js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".webmanifest": "application/manifest+json",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }.get(file_path.suffix.lower(), "application/octet-stream")
        # Service worker must not be cached aggressively.
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        if rel == "sw.js":
            self.send_header("Service-Worker-Allowed", "/")
        self.end_headers()
        self.wfile.write(data)


def main():
    if not STATIC_DIR.is_dir():
        raise SystemExit(f"Missing static dir: {STATIC_DIR}")
    load_push_subs()
    ensure_vapid_keys()
    watcher = threading.Thread(target=push_watcher_loop, name="push-watcher", daemon=True)
    watcher.start()
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"BeatLine → http://{HOST}:{PORT}/")
    print("Android Chrome → open URL → Add to Home Screen")
    print("Background chime → allow Notifications when prompted")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        httpd.shutdown()


if __name__ == "__main__":
    main()