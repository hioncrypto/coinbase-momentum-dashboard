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

    spot = get("/api/spot")
    assert spot.get("ok"), spot
    assert spot.get("price") is not None, spot
    print("spot", spot.get("price"))

    tfs = get("/api/timeframes")
    assert tfs.get("ok"), tfs
    ids = {t["id"] for t in tfs.get("timeframes") or []}
    assert {"1m", "5m", "15m"} <= ids, ids
    for tf in ("1m", "5m", "15m"):
        c = get(f"/api/candles?tf={tf}")
        assert c.get("ok"), (tf, c)
        assert len(c.get("candles") or []) >= 20, (tf, len(c.get("candles") or []))
        print("tf", tf, "candles", len(c["candles"]), "gran", c.get("granularity"))
        t = get(f"/api/target?tf={tf}")
        assert t.get("ok") is not False, (tf, t)
        assert t.get("price_to_beat") is not None, (tf, t)
        print("  beat", t.get("price_to_beat"), t.get("label"), t.get("source"), t.get("close_time"))
    print("OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("FAIL", exc)
        raise SystemExit(1)
