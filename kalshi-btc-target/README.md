# BeatLine

Standalone Android PWA for Kalshi’s **15-minute BTC Price to beat** (`KXBTC15M`).

Not part of any Coinbase / momentum-scanner product. Chart + live spot use CF Benchmarks **BRTI** (Coinbase candles only fill longer history). Target, odds, countdown, and settlement come from Kalshi.

## How to use

1. **Read the window** — Price to beat, Live now, vs beat, and Time left.
2. **Chart** — Dashed **TO BEAT** is the Price to beat. 1m / 5m / 15m change candle size only.
3. **Odds & Best Side** — Above/Below market chance; Best Side scores the edge (stays visible after a buy for add decisions).
4. **Buy / add** — Buy Above, Best, or Buy Below → slide to confirm. Same-side buys add to the open position.
5. **Rolling P/L** — Open-trade strip tracks mark P/L; close at bid or hold to settle.
6. **Demo & alerts** — ⋮ Options for paper bankroll; bell for new-target and clear-edge alerts.

## Run

From this folder:

```bash
python3 server.py
```

Open `http://localhost:8765/`

Docker:

```bash
docker build -t beatline .
docker run --rm -p 8765:8765 beatline
```

### Android

1. Open the app URL in **Chrome**
2. Menu → **Add to Home Screen**
3. Launch the BeatLine icon

## Demo account & trade history

Balance, open position, P/L, and trade history sync to the **BeatLine server** (`data/demo_account.json`), not only the browser.

That way a new Cloudflare tunnel URL still restores the same account when it hits the same server. Clearing history in Options still clears the server copy.

> Temporary `*.trycloudflare.com` links can still go down. The account survives **URL** changes; it does not survive wiping the server disk / rebuilding a fresh host with no `data/` volume.

## Hosting notes

**GitHub Pages alone cannot host BeatLine.** Pages only serves static files; this app needs `server.py` for Kalshi/BRTI APIs and account persistence.

For a stable public URL + durable P/L:

1. Deploy `kalshi-btc-target` on a small always-on host (Fly.io, Railway, Render, a VPS) with a persistent disk for `data/`.
2. Or run `python3 server.py` on a machine you control and put a **named** Cloudflare Tunnel / custom domain in front of it (not a quick `trycloudflare` link).

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/target?tf=15m` | Live Kalshi Price to beat |
| `GET /api/candles?tf=1m\|5m\|15m` | Chart candles (BRTI tip + Coinbase history) |
| `GET /api/spot` | Live BRTI (Coinbase fallback) |
| `GET /api/demo-account` | Saved demo balance / history |
| `POST /api/demo-account` | Persist demo balance / history |
| `GET /api/health` | Health check |

## Test

```bash
python3 smoke_test.py
python3 smoke_test.py https://your-host.example
```
