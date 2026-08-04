# Kalshi BTC Target (Android / mobile web)

Mobile web app that **automatically draws Kalshi’s 15-minute BTC Target Price** (`KXBTC15M`) as a horizontal line on a BTC-USD chart.

Works on **Android phones** in Chrome (Add to Home Screen). No manual price input — when Kalshi publishes a new target each 15 minutes, the line moves.

## Why not TradingView’s Android app?

TradingView’s phone app cannot run Chrome extensions or custom overlays. Pine Script also cannot call Kalshi. So this app shows **your own BTC-USD chart** (Coinbase candles + TradingView Lightweight Charts) with the live Kalshi TARGET line.

| Surface | Use |
|---|---|
| **Android phone** | This app (`kalshi-btc-target/`) |
| Desktop TradingView website | Optional Chrome extension in `tradingview-kalshi-target/` |

## Want this line on TradingView itself (Android)?

The Play Store TradingView app cannot host overlays. Use Firefox + Tampermonkey with the userscript instead — see [`../tradingview-kalshi-target/ANDROID.md`](../tradingview-kalshi-target/ANDROID.md).

On this server you can also open [/android-tradingview.html](/android-tradingview.html) for install steps, and fetch [/kalshi-tv-target.user.js](/kalshi-tv-target.user.js).

## Run locally

```bash
python3 kalshi-btc-target/server.py
```

Open `http://localhost:8765/` (or your machine’s LAN IP from the phone).

### Android (standalone chart)

1. Deploy or tunnel this server so the phone can reach it (same Wi‑Fi LAN IP, ngrok, Fly, etc.)
2. Open the URL in **Chrome**
3. Menu → **Add to Home Screen**
4. Launch the icon — the TARGET line updates on its own each 15m window

### Android (on TradingView website)

Follow [ANDROID.md](../tradingview-kalshi-target/ANDROID.md) (Firefox + Tampermonkey).
## API

- `GET /api/target` — live Kalshi `KXBTC15M` target
- `GET /api/candles?granularity=60&limit=300` — BTC-USD candles (Coinbase)
- `GET /api/health`

## Behavior

- Polls Kalshi about every 10s
- Also refreshes a few seconds after each window `close_time` so the new target appears promptly
- Dashed green **TARGET** price line via Lightweight Charts `createPriceLine`
