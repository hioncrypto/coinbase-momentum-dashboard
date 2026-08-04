# Android-only: Kalshi 15m TARGET on TradingView

Phone only. No computer. No GitHub.

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
5. Paste in `kalshi-tv-target.user.js` (full file)  
6. Tap the save / checkmark icon  
7. Make sure the script is **Enabled**

### 4) Open TradingView BTCUSD in Firefox
Open: [TradingView BTCUSD](https://www.tradingview.com/chart/?symbol=BTCUSD)

Do **not** use the TradingView app.

### 5) Confirm
You should see a dashed green **TARGET** line and label on the chart.  
It moves automatically when Kalshi publishes the next 15m target.

## Notes
- TradingView Play Store app cannot run this  
- After one install, it runs automatically — no price typing  
