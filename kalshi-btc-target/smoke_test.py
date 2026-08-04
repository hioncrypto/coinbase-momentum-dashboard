#!/usr/bin/env python3
"""End-to-end smoke test for Kalshi 15m Price-to-beat + candles."""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=25) as r:
        return json.load(r)


def main() -> int:
    health = get("/api/health")
    assert health.get("ok"), health

    target = get("/api/target")
    assert target.get("ok") is True, target
    beat = target.get("price_to_beat")
    print("price_to_beat", beat, target.get("label"), target.get("ticker"))
    if beat is not None:
        assert 1000 < float(beat) < 5_000_000, beat

    candles = get("/api/candles?granularity=60&limit=120")
    assert candles.get("ok"), candles
    rows = candles.get("candles") or []
    assert len(rows) >= 50, len(rows)
    print("candles", len(rows), "last", rows[-1])
    print("OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("FAIL", exc)
        raise SystemExit(1)
