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

## Hosting (stop trycloudflare from going stale)

Quick Cloudflare tunnels change hostnames and die. Use a real host:

- **Render (free, recommended):** open  
  https://render.com/deploy?repo=https://github.com/hioncrypto/coinbase-momentum-dashboard  
  → permanent `*.onrender.com` URL. Full steps: [`DEPLOY.md`](./DEPLOY.md)
- **Fly.io / Docker / VPS:** see [`DEPLOY.md`](./DEPLOY.md)

GitHub Pages cannot run BeatLine’s Python backend.

### Temporary tunnel (dev only)

`./tunnel_watchdog.sh` keeps a quick Cloudflare tunnel alive and writes the current URL to `/tmp/beatline-tunnel-url.txt`. Restarts still produce a **new hostname** — that's a limitation of free quick tunnels, which is why a real host is better.

## Demo account & trade history

Balance, open position, P/L, and trade history sync to the **BeatLine server** (`data/demo_account.json`), not only the browser.

On a **stable host URL**, your phone also keeps the same account in browser storage. Use ⋮ Options → **Export backup** for an offline P/L copy.

> Temporary `*.trycloudflare.com` links can still go down. Prefer Render/Fly from [`DEPLOY.md`](./DEPLOY.md).

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
