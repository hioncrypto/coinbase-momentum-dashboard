# Draw Kalshi 15m TARGET on TradingView — Android

TradingView’s **Play Store app cannot** run extensions or custom drawings from Kalshi.  
To get an auto horizontal **TARGET** line on TradingView on Android, use the **TradingView website** inside a browser that can run a userscript/extension.

## Recommended: Firefox + Tampermonkey (Android)

1. Install **Firefox** from the Play Store  
2. In Firefox, install **Tampermonkey**  
   - Menu → Add-ons → find Tampermonkey (or open the Firefox add-ons site)  
3. Open this userscript file from the repo and install it in Tampermonkey:  
   - `tradingview-kalshi-target/kalshi-tv-target.user.js`  
   - Or after you push/host it, open the raw file URL → Tampermonkey will prompt **Install**  
4. In **Firefox** (not the TradingView app), go to:  
   - https://www.tradingview.com/  
5. Open a **BTCUSD** chart  
6. You should see a dashed green **TARGET** line at Kalshi’s live `KXBTC15M` Target Price  

The script:
- Pulls Kalshi’s **15-minute** target automatically  
- Redraws when each new 15m window publishes a new target  
- Needs **no manual price input**

### Optional proxy

If direct Kalshi calls fail on your network, run `kalshi-btc-target/server.py`, deploy it, then set `PROXY_BASE` at the top of the userscript to that origin (e.g. `https://your-server`).

## Alternative: Kiwi Browser + Chrome extension

1. Install **Kiwi Browser** (supports Chrome extensions on Android)  
2. Load the unpacked extension folder `tradingview-kalshi-target/` (Kiwi developer mode), or pack/install the extension  
3. Open https://www.tradingview.com/ → BTCUSD  

## What will not work

| Approach | Android TradingView app |
|---|---|
| Chrome extension | No |
| Pine Script auto-from-Kalshi | No (Pine can’t call Kalshi) |
| This userscript **inside the TV app** | No |

| Approach | TradingView **website** on Android browser |
|---|---|
| Firefox + Tampermonkey userscript | **Yes** |
| Kiwi + Chrome extension | **Yes** |

## Standalone chart (not TradingView UI)

If you only need the line on a BTC chart (not TradingView’s UI), use `kalshi-btc-target/` — Add to Home Screen in Chrome.
