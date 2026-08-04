# Kalshi BTC Target → TradingView (desktop only)

Chrome extension that draws Kalshi's rolling **15-minute BTC Target Price** (`KXBTC15M`) as a dashed horizontal **TARGET** line on TradingView **BTCUSD** charts in a **desktop** Chromium browser.

> **Android / iPhone:** browser extensions do not run inside the TradingView mobile app. Use the mobile web app in [`../kalshi-btc-target/`](../kalshi-btc-target/) instead — it auto-draws the same Kalshi target on a phone-friendly chart.

A new target is published every 15 minutes. The extension polls Kalshi on an ongoing basis and redraws the line when the window rolls.

## Install (Chrome / Edge / Brave — desktop)

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select this folder (`tradingview-kalshi-target`)
4. Open [TradingView](https://www.tradingview.com/) on a **BTCUSD** chart

Use the extension popup to see the live target, force a refresh, or disable the overlay.

## How it works

| Piece | Role |
|---|---|
| `background.js` | Fetches open `KXBTC15M` markets from Kalshi; stores `floor_strike` / `Target Price` |
| Alarms | Polls about every minute + schedules a refresh a few seconds after each window `close_time` |
| `content.js` | Maps target price → Y pixel via TradingView's price axis and draws the line |
| `popup` | Status / enable toggle / manual refresh |

## Notes

- Desktop Chromium only (TradingView's mobile apps don't support extensions).
- Overlay activates on pages that look like a BTCUSD chart (title/URL heuristics).
- If the axis hasn't rendered yet, the badge shows the target while the line waits for scale labels.
- Not affiliated with Kalshi or TradingView. Settlement uses CF Benchmarks BRTI per Kalshi rules.
