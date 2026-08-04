#!/usr/bin/env python3
"""Smoke-test Kalshi KXBTC15M target parsing (no Chrome required)."""
from __future__ import annotations

import json
import re
import sys
import urllib.request

URL = (
    "https://api.elections.kalshi.com/trade-api/v2/markets"
    "?limit=5&status=open&series_ticker=KXBTC15M"
)


def parse_target(market: dict) -> float | None:
    floor = market.get("floor_strike")
    if isinstance(floor, (int, float)):
        return float(floor)
    sub = market.get("yes_sub_title") or market.get("no_sub_title") or ""
    m = re.search(r"Target\s*Price:\s*\$?\s*([0-9,]+(?:\.\d+)?)", sub, re.I)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def main() -> int:
    req = urllib.request.Request(
        URL, headers={"Accept": "application/json", "User-Agent": "kalshi-tv-smoke/1.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    markets = data.get("markets") or []
    if not markets:
        print("FAIL: no open KXBTC15M markets")
        return 1
    market = markets[0]
    target = parse_target(market)
    print(
        json.dumps(
            {
                "ticker": market.get("ticker"),
                "status": market.get("status"),
                "target": target,
                "open": market.get("open_time"),
                "close": market.get("close_time"),
                "subtitle": market.get("yes_sub_title"),
            },
            indent=2,
        )
    )
    if target is None:
        print("WARN: target TBD — ok if window not open yet")
        return 0
    if not (1000 < target < 5_000_000):
        print("FAIL: target out of expected BTC range")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
