#!/usr/bin/env python3
"""
Mobile-friendly Kalshi BTC 15m Target chart server.

Serves a PWA that works in Android Chrome (Add to Home Screen) and draws
Kalshi's rolling KXBTC15M Target Price as a chart price line — no manual input.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "0.0.0.0"
PORT = 8765
STATIC_DIR = Path(__file__).resolve().parent / "static"

KALSHI_URL = (
    "https://api.elections.kalshi.com/trade-api/v2/markets"
    "?limit=5&status=open&series_ticker=KXBTC15M"
)
COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/BTC-USD/candles"

UA = "kalshi-btc-target/1.0 (+android-pwa)"

_cache_lock = threading.Lock()
_target_cache: dict = {"at": 0.0, "payload": None}
_candles_cache: dict = {"at": 0.0, "key": None, "payload": None}
TARGET_TTL = 3.0
CANDLES_TTL = 10.0


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
    sub = market.get("yes_sub_title") or market.get("no_sub_title") or ""
    m = re.search(r"Target\s*Price:\s*\$?\s*([0-9,]+(?:\.\d+)?)", sub, re.I)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def format_et_close(close_iso: str | None) -> str | None:
    """Match Kalshi mobile label style, e.g. '9:30pm ET'."""
    if not close_iso:
        return None
    try:
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo

        dt = datetime.fromisoformat(close_iso.replace("Z", "+00:00")).astimezone(
            ZoneInfo("America/New_York")
        )
        # Kalshi-style: 9:30pm ET
        stamp = dt.strftime("%I:%M%p ET").lstrip("0").replace("AM", "am").replace("PM", "pm")
        return stamp
    except Exception:
        return close_iso


def fetch_target_payload() -> dict:
    now = time.time()
    with _cache_lock:
        cached = _target_cache["payload"]
        age = now - _target_cache["at"]
        # Don't hold a TBD/empty target — retry quickly until Kalshi publishes floor_strike.
        ttl = TARGET_TTL if cached and cached.get("price_to_beat") is not None else 1.0
        if cached and age < ttl:
            return cached

    try:
        data = http_get_json(KALSHI_URL)
        markets = data.get("markets") or []
        # Prefer an active/open market that already has Price to beat set.
        market = next(
            (
                m
                for m in markets
                if m.get("status") in ("active", "open") and parse_target(m) is not None
            ),
            None,
        )
        if market is None:
            market = next(
                (m for m in markets if m.get("status") in ("active", "open")),
                markets[0] if markets else None,
            )
        if not market:
            payload = {
                "ok": True,
                "target": None,
                "price_to_beat": None,
                "ticker": None,
                "event_ticker": None,
                "open_time": None,
                "close_time": None,
                "close_et": None,
                "subtitle": None,
                "label": "Price to beat",
                "error": "No open KXBTC15M market",
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        else:
            # Kalshi "Price to beat" == floor_strike / Target Price on KXBTC15M
            target = parse_target(market)
            close_et = format_et_close(market.get("close_time"))
            payload = {
                "ok": True,
                "target": target,
                "price_to_beat": target,
                "ticker": market.get("ticker"),
                "event_ticker": market.get("event_ticker"),
                "open_time": market.get("open_time"),
                "close_time": market.get("close_time"),
                "close_et": close_et,
                "subtitle": market.get("yes_sub_title"),
                "label": f"Price to beat • {close_et}" if close_et else "Price to beat",
                "error": None
                if target is not None
                else "Price to beat TBD (waiting for window open)",
                "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            # If this window is still TBD, keep showing the previous known Price to beat
            # until Kalshi publishes the new floor (usually seconds after rollover).
            if target is None:
                with _cache_lock:
                    prev = _target_cache.get("payload") or {}
                if prev.get("price_to_beat") is not None:
                    payload = {
                        **payload,
                        "target": prev["price_to_beat"],
                        "price_to_beat": prev["price_to_beat"],
                        "error": "Waiting for new 15m Price to beat…",
                        "stale_previous": True,
                        "previous_ticker": prev.get("ticker"),
                    }
    except Exception as exc:
        payload = {
            "ok": False,
            "target": None,
            "price_to_beat": None,
            "error": str(exc),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    with _cache_lock:
        _target_cache["at"] = time.time()
        _target_cache["payload"] = payload
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

    # Coinbase returns at most ~300 candles per call for a window; request recent window.
    end = int(now)
    start = end - granularity * limit
    qs = urllib.parse.urlencode(
        {"granularity": granularity, "start": start, "end": end}
    )
    url = f"{COINBASE_CANDLES}?{qs}"
    try:
        raw = http_get_json(url)
        # Coinbase: [time, low, high, open, close, volume], newest first
        rows = sorted(raw, key=lambda r: r[0])
        candles = [
            {
                "time": int(r[0]),
                "open": float(r[3]),
                "high": float(r[2]),
                "low": float(r[1]),
                "close": float(r[4]),
            }
            for r in rows
        ]
        # Deduplicate timestamps (lightweight-charts requires unique ascending times)
        deduped = []
        seen = set()
        for c in candles:
            if c["time"] in seen:
                continue
            seen.add(c["time"])
            deduped.append(c)
        payload = {
            "ok": True,
            "symbol": "BTC-USD",
            "granularity": granularity,
            "candles": deduped[-limit:],
            "error": None,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    except Exception as exc:
        payload = {
            "ok": False,
            "symbol": "BTC-USD",
            "candles": [],
            "error": str(exc),
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    with _cache_lock:
        _candles_cache["at"] = now
        _candles_cache["key"] = key
        _candles_cache["payload"] = payload
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "KalshiBtcTarget/1.0"

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

        if path in ("/api/target", "/api/kalshi/target"):
            self._send_json(200, fetch_target_payload())
            return

        if path in ("/api/candles", "/api/btc/candles"):
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
            limit = max(50, min(limit, 500))
            self._send_json(200, fetch_candles(gran, limit))
            return

        if path == "/api/health":
            self._send_json(200, {"ok": True})
            return

        # Static files
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
    print(f"Kalshi BTC Target mobile app → http://{HOST}:{PORT}/")
    print("On Android: open this URL in Chrome → Add to Home Screen")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        httpd.shutdown()


if __name__ == "__main__":
    main()
