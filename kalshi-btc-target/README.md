# Kalshi BTC Price to beat (Android)

Finished Android chart app: auto-draws Kalshi’s rolling **15-minute Price to beat** (`KXBTC15M`) as a dashed **TARGET** line on a BTC-USD chart.

No Tampermonkey. No manual price input. New line level each 15m window.

## Run

```bash
python3 kalshi-btc-target/server.py
```

Open `http://localhost:8765/`  

Or Docker:

```bash
docker build -t kalshi-btc-target kalshi-btc-target
docker run --rm -p 8765:8765 kalshi-btc-target
```

### Android

1. Open the app URL in **Chrome**
2. Menu → **Add to Home Screen**
3. Launch the icon — Price to beat + TARGET line update automatically

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/target` | Live Kalshi Price to beat (`price_to_beat`, `label`, `close_et`) |
| `GET /api/candles?granularity=60&limit=300` | BTC-USD candles (Coinbase) |
| `GET /api/health` | Health check |

## Test

```bash
python3 kalshi-btc-target/smoke_test.py
# or against a remote host:
python3 kalshi-btc-target/smoke_test.py https://your-host.example
```

## Notes

- Uses Kalshi’s `floor_strike` / Target Price field (same as Kalshi app “Price to beat”)
- Chart candles are Coinbase BTC-USD (Kalshi settles on CF Benchmarks BRTI, so spot can differ slightly)
- TradingView overlay (optional, desktop/Firefox): see `tradingview-kalshi-target/`
