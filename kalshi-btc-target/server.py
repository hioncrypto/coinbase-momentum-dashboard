#!/usr/bin/env python3
"""
Kalshi BTC Price-to-beat chart server (Android PWA).

- Dropdown: 1m / 5m / 15m chart candles
- Price to beat + countdown follow the selected timeframe window
- 15m uses live Kalshi KXBTC15M; 1m/5m use matching wall-clock windows
  (Kalshi public API currently exposes BTC up/down as KXBTC15M only)
"""

from __future__ import annotations

import json
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

# Chart candle size + settlement window length (seconds) per TF.
TIMEFRAMES = {
    "1m": {
        "label": "1 minute",
        "granularity": 60,
        "window_sec": 60,
        "candle_limit": 300,
        "kalshi_series": ["KXBTC1M", "KXBTC15M"],
    },
    "5m": {
        "label": "5 minutes",
        "granularity": 300,
        "window_sec": 300,
        "candle_limit": 300,
        "kalshi_series": ["KXBTC5M", "KXBTC15M"],
    },
    "15m": {
        "label": "15 minutes",
        "granularity": 900,
        "window_sec": 900,
        "candle_limit": 300,
        "kalshi_series": ["KXBTC15M"],
    },
}

COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
COINBASE_TICKER = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"
KALSHI_MARKETS = "https://api.elections.kalshi.com/trade-api/v2/markets"

UA = "kalshi-btc-target/1.4 (+android-pwa)"

_cache_lock = threading.Lock()
_target_cache: dict = {}  # key -> {at, payload}
_candles_cache: dict = {"at": 0.0, "key": None, "payload": None}
_spot_cache: dict = {"at": 0.0, "payload": None}
TARGET_TTL = 2.0
CANDLES_TTL = 8.0
SPOT_TTL = 1.5


def _parse_dollars(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def market_odds(market: dict) -> dict:
    """Kalshi Yes/No % from last trade or mid of bid/ask (dollars fields)."""
    last = _parse_dollars(market.get("last_price_dollars"))
    yes_bid = _parse_dollars(market.get("yes_bid_dollars"))
    yes_ask = _parse_dollars(market.get("yes_ask_dollars"))
    no_bid = _parse_dollars(market.get("no_bid_dollars"))
    no_ask = _parse_dollars(market.get("no_ask_dollars"))

    yes = last
    if yes is None and yes_bid is not None and yes_ask is not None:
        yes = (yes_bid + yes_ask) / 2.0
    elif yes is None and yes_ask is not None:
        yes = yes_ask
    elif yes is None and yes_bid is not None:
        yes = yes_bid

    if yes is None:
        return {
            "yes_pct": None,
            "no_pct": None,
            "yes_bid_pct": None,
            "yes_ask_pct": None,
            "last_pct": None,
        }

    yes = max(0.0, min(1.0, yes))
    no = 1.0 - yes
    return {
        "yes_pct": round(yes * 100),
        "no_pct": round(no * 100),
        "yes_bid_pct": round(yes_bid * 100) if yes_bid is not None else None,
        "yes_ask_pct": round(yes_ask * 100) if yes_ask is not None else None,
        "last_pct": round(last * 100) if last is not None else None,
        "no_bid_pct": round(no_bid * 100) if no_bid is not None else None,
        "no_ask_pct": round(no_ask * 100) if no_ask is not None else None,
    }


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


def pick_current_market(markets: list) -> dict | None:
    """Prefer the open market whose close is soonest but still in the future."""
    now_ms = time.time() * 1000.0
    openish = [
        m
        for m in markets
        if m.get("status") in ("active", "open", "initialized")
    ] or list(markets)
    future = []
    for m in openish:
        close_ms = parse_close_ms(m.get("close_time"))
        if close_ms is None:
            continue
        if close_ms > now_ms - 5_000:  # allow tiny clock skew
            future.append((close_ms, m))
    if future:
        future.sort(key=lambda x: x[0])
        # Prefer a market that already has a Price to beat when possible.
        with_target = [pair for pair in future if parse_target(pair[1]) is not None]
        return (with_target or future)[0][1]
    return openish[0] if openish else None


def http_get_json(url: str, timeout: float = 20.0):
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


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


def fetch_kalshi_series_target(series: str) -> dict | None:
    url = (
        f"{KALSHI_MARKETS}?limit=20&status=open&series_ticker="
        + urllib.parse.quote(series)
    )
    try:
        data = http_get_json(url)
    except Exception:
        return None
    markets = data.get("markets") or []
    market = pick_current_market(markets)
    if not market:
        return None
    target = parse_target(market)
    close_et = format_et(market.get("close_time"))
    odds = market_odds(market)
    close_ms = parse_close_ms(market.get("close_time"))
    stale_previous = bool(close_ms is not None and close_ms <= time.time() * 1000.0)
    return {
        "ok": True,
        "source": "kalshi",
        "series": series,
        "target": target,
        "price_to_beat": target,
        "ticker": market.get("ticker"),
        "event_ticker": market.get("event_ticker"),
        "open_time": market.get("open_time"),
        "close_time": market.get("close_time"),
        "close_et": close_et,
        "subtitle": market.get("yes_sub_title"),
        "title": market.get("title"),
        "label": f"Price to beat • {close_et}" if close_et else "Price to beat",
        "yes_pct": odds["yes_pct"],
        "no_pct": odds["no_pct"],
        "yes_bid_pct": odds.get("yes_bid_pct"),
        "yes_ask_pct": odds.get("yes_ask_pct"),
        "last_pct": odds.get("last_pct"),
        "stale_previous": stale_previous,
        "error": None
        if target is not None
        else "Price to beat TBD (waiting for window open)",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def fetch_window_target(tf: str, cfg: dict) -> dict:
    """Price to beat = open of the current 1m/5m/15m wall-clock window (Coinbase)."""
    window = int(cfg["window_sec"])
    now = int(time.time())
    open_ts = now - (now % window)
    close_ts = open_ts + window
    # Fetch a short candle window around open_ts
    start = open_ts - window
    end = min(now + window, close_ts)
    qs = urllib.parse.urlencode(
        {
            "granularity": cfg["granularity"],
            "start": datetime.fromtimestamp(start, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "end": datetime.fromtimestamp(end, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
    )
    target = None
    try:
        raw = http_get_json(f"{COINBASE_CANDLES}?{qs}")
        # Coinbase rows: [time, low, high, open, close, volume]
        rows = sorted(raw, key=lambda r: r[0])
        for r in rows:
            if int(r[0]) == open_ts:
                target = float(r[3])  # open
                break
        if target is None and rows:
            # nearest at-or-before open
            prior = [r for r in rows if int(r[0]) <= open_ts]
            if prior:
                target = float(prior[-1][3])
    except Exception:
        spot = fetch_spot()
        target = spot.get("price")

    close_iso = datetime.fromtimestamp(close_ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    open_iso = datetime.fromtimestamp(open_ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    close_et = format_et(close_ts)
    return {
        "ok": True,
        "source": "window",
        "series": None,
        "timeframe": tf,
        "target": target,
        "price_to_beat": target,
        "ticker": f"WINDOW-{tf.upper()}",
        "event_ticker": None,
        "open_time": open_iso,
        "close_time": close_iso,
        "close_et": close_et,
        "subtitle": f"Window open @ {format_et(open_ts)}" if target else None,
        "label": f"Price to beat • {close_et}" if close_et else "Price to beat",
        "error": None if target is not None else "Waiting for window open price",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def fetch_target_payload(tf: str = "15m") -> dict:
    if tf not in TIMEFRAMES:
        tf = "15m"
    cfg = TIMEFRAMES[tf]
    now = time.time()
    with _cache_lock:
        cached = _target_cache.get(tf)
        if cached:
            payload = cached["payload"] or {}
            close_ms = parse_close_ms(payload.get("close_time"))
            expired = close_ms is not None and close_ms <= now * 1000.0
            age = now - cached["at"]
            ttl = (
                0.4
                if expired or payload.get("price_to_beat") is None
                else TARGET_TTL
            )
            if not expired and age < ttl:
                return payload

    payload = None
    # Prefer a live Kalshi series for this TF when it exists.
    for series in cfg["kalshi_series"]:
        # For 1m/5m only accept exact series match; don't silently fall back to 15m
        # unless this IS the 15m timeframe.
        if tf != "15m" and series == "KXBTC15M":
            continue
        payload = fetch_kalshi_series_target(series)
        if payload and payload.get("price_to_beat") is not None:
            payload["timeframe"] = tf
            break
        # Keep TBD kalshi payload briefly so client can roll / chime on ticker.
        if payload and tf == "15m":
            payload["timeframe"] = tf
            break
        payload = None

    if payload is None:
        payload = fetch_window_target(tf, cfg)
        payload["yes_pct"] = None
        payload["no_pct"] = None

    with _cache_lock:
        _target_cache[tf] = {"at": time.time(), "payload": payload}
    return payload


def fetch_spot() -> dict:
    now = time.time()
    with _cache_lock:
        if _spot_cache["payload"] and now - _spot_cache["at"] < SPOT_TTL:
            return _spot_cache["payload"]
    try:
        data = http_get_json(COINBASE_TICKER)
        price = float(data.get("price"))
        payload = {
            "ok": True,
            "symbol": "BTC-USD",
            "price": price,
            "bid": float(data["bid"]) if data.get("bid") is not None else None,
            "ask": float(data["ask"]) if data.get("ask") is not None else None,
            "time": data.get("time"),
            "error": None,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    except Exception as exc:
        payload = {
            "ok": False,
            "symbol": "BTC-USD",
            "price": None,
            "error": str(exc),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    with _cache_lock:
        _spot_cache["at"] = time.time()
        _spot_cache["payload"] = payload
    return payload


def fetch_candles(granularity: int = 60, limit: int = 300) -> dict:
    now = time.time()
    key = (granularity, limit)
    with _cache_lock:
        if (
            _candles_cache["payload"]
            and _candles_cache["key"] == key
            and now - _candles_cache["at"] < CANDLES_TTL
        ):
            return _candles_cache["payload"]

    end = int(now)
    start = end - granularity * limit
    qs = urllib.parse.urlencode(
        {
            "granularity": granularity,
            "start": datetime.fromtimestamp(start, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "end": datetime.fromtimestamp(end, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        }
    )
    try:
        raw = http_get_json(f"{COINBASE_CANDLES}?{qs}")
        rows = sorted(raw, key=lambda r: r[0])
        candles = []
        seen = set()
        for r in rows:
            t = int(r[0])
            if t in seen:
                continue
            seen.add(t)
            candles.append(
                {
                    "time": t,
                    "open": float(r[3]),
                    "high": float(r[2]),
                    "low": float(r[1]),
                    "close": float(r[4]),
                }
            )
        payload = {
            "ok": True,
            "symbol": "BTC-USD",
            "granularity": granularity,
            "candles": candles[-limit:],
            "error": None,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    except Exception as exc:
        payload = {
            "ok": False,
            "symbol": "BTC-USD",
            "granularity": granularity,
            "candles": [],
            "error": str(exc),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    with _cache_lock:
        _candles_cache["at"] = time.time()
        _candles_cache["key"] = key
        _candles_cache["payload"] = payload
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "KalshiBtcTarget/1.4"

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
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

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

        if path == "/api/health":
            self._send_json(
                200,
                {"ok": True, "service": "kalshi-btc-target", "version": "1.4"},
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
        self._send(200, data, ctype)


def main():
    if not STATIC_DIR.is_dir():
        raise SystemExit(f"Missing static dir: {STATIC_DIR}")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Kalshi BTC Price-to-beat app → http://{HOST}:{PORT}/")
    print("Android Chrome → open URL → Add to Home Screen")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        httpd.shutdown()


if __name__ == "__main__":
    main()
