# Draw Kalshi 15m TARGET on TradingView — Android

TradingView’s **Play Store app cannot** run extensions or custom drawings from Kalshi.  
To get an auto horizontal **TARGET** line on TradingView on Android, use the **TradingView website** inside Firefox + Tampermonkey.

## Links (no GitHub)

1. [Firefox for Android (Google Play)](https://play.google.com/store/apps/details?id=org.mozilla.firefox)
2. [Tampermonkey for Firefox](https://addons.mozilla.org/firefox/addon/tampermonkey/)
3. Install userscript from your running app server:  
   `http://YOUR-PHONE-REACHABLE-HOST:8765/kalshi-tv-target.user.js`  
   (same file as `tradingview-kalshi-target/kalshi-tv-target.user.js`)
4. [TradingView BTCUSD chart](https://www.tradingview.com/chart/?symbol=BTCUSD)
5. Install steps page on the app server:  
   `http://YOUR-PHONE-REACHABLE-HOST:8765/android-tradingview.html`

## Setup

```bash
python3 kalshi-btc-target/server.py
```

On your phone (same Wi‑Fi / deployed host), open the install page above and tap the buttons in order.

The script:
- Pulls Kalshi’s **15-minute** target automatically  
- Redraws when each new 15m window publishes a new target  
- Needs **no manual price input**

### Optional proxy

If direct Kalshi calls fail, set `PROXY_BASE` at the top of the userscript to your server origin (the same host running `kalshi-btc-target`).

## Alternative: Kiwi Browser + Chrome extension

1. Install Kiwi Browser  
2. Load the unpacked extension folder `tradingview-kalshi-target/`  
3. Open [TradingView](https://www.tradingview.com/) → BTCUSD  

## What will not work

| Approach | Android TradingView app |
|---|---|
| Chrome extension | No |
| Pine Script auto-from-Kalshi | No |
| Userscript inside the TV app | No |

| Approach | TradingView **website** on Android browser |
|---|---|
| Firefox + Tampermonkey userscript | **Yes** |
| Kiwi + Chrome extension | **Yes** |

## Standalone chart (not TradingView UI)

If you only need the line on a BTC chart (not TradingView’s UI), open the PWA root: `http://YOUR-HOST:8765/`
