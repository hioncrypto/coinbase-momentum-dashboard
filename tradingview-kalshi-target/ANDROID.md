# Android-only: Kalshi 15m TARGET on TradingView

Phone only. No computer.

Uses **Firefox + Tampermonkey** on the TradingView **website** (not the TradingView Play Store app).

The script talks to Kalshi directly and auto-updates every 15 minutes.

## Step-by-step

### 1) Install Firefox
Open: [Firefox on Google Play](https://play.google.com/store/apps/details?id=org.mozilla.firefox)

### 2) Install Tampermonkey
In Firefox, open: [Tampermonkey](https://addons.mozilla.org/firefox/addon/tampermonkey/)  
Tap **Add to Firefox**.

### 3) Add the Kalshi TARGET script
1. Tap the **Tampermonkey** icon in Firefox  
2. Tap **Dashboard**  
3. Tap **+** (Create a new script)  
4. Delete the template text  
5. Paste the userscript  
6. Save and keep it **Enabled**

### 4) Open TradingView BTCUSD in Firefox
Open: [TradingView BTCUSD](https://www.tradingview.com/chart/?symbol=BTCUSD)

Do **not** use the TradingView app.

### 5) Confirm
Dashed green **TARGET** line on the chart. Updates automatically each new Kalshi 15m target.
