# Kalshi BTC Target → TradingView (desktop + Android browser)

Auto-draws Kalshi's rolling **15-minute BTC Target Price** (`KXBTC15M`) as a dashed horizontal **TARGET** line on TradingView **BTCUSD** charts.

> **Android:** The TradingView Play Store app cannot run overlays. Use the **TradingView website** in Firefox + Tampermonkey — see **[ANDROID.md](ANDROID.md)**. Userscript: `kalshi-tv-target.user.js`.

## Android (TradingView website)

1. Firefox → Tampermonkey → install `kalshi-tv-target.user.js`
2. Open https://www.tradingview.com/ → BTCUSD
3. TARGET line updates each Kalshi 15m window automatically

Full steps: [ANDROID.md](ANDROID.md)

## Desktop Chrome extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select this folder (`tradingview-kalshi-target`)
4. Open [TradingView](https://www.tradingview.com/) on a **BTCUSD** chart

## How it works

| Piece | Role |
|---|---|
| `kalshi-tv-target.user.js` | Android-capable Tampermonkey script (TradingView website) |
| `background.js` | Desktop extension: fetches open `KXBTC15M` Target Price |
| `content.js` | Desktop overlay on TradingView page |
| Alarms / poll | Refresh ongoing + at each 15m window boundary |

## Notes

- Not inside the TradingView mobile **app** (platform limitation).
- Standalone phone chart alternative: [`../kalshi-btc-target/`](../kalshi-btc-target/)
- Not affiliated with Kalshi or TradingView.
