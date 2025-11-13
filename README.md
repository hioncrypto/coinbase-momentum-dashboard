# 🚀 hioncrypto's Crypto Tracker - Complete Version

**Progressive 3-Stage Alert System with Full Persistence**

---

## ✨ Features

### Core Functionality
- ✅ **Correct % Calculation**: Finds lowest LOW in lookback window (not just endpoints)
- ✅ **Full URL Persistence**: ALL settings save to URL - bookmark your configuration
- ✅ **Default 1h Timeframe**: Optimized for momentum trading
- ✅ **4h Timeframe Added**: Now supports 15m, 1h, 4h
- ✅ **Mobile Responsive**: Full touch-friendly interface for phones/tablets
- ✅ **Simple Tooltips**: (?) help icons on all major settings

### Progressive Alert System (3 Stages)
- 🟡 **Stage 1**: MACD Cross below zero (earliest entry, highest risk)
- 🟢 **Stage 2**: Histogram positive (confirmed momentum, best risk/reward)
- 🔵 **Stage 3**: % Threshold hit (late but safe entry)

**You get 3 alerts as each move develops** with full timeline showing all stages!

### Alert Delivery
- 📧 **Email**: Gmail SMTP (requires setup in secrets.toml)
- 🔗 **Webhook**: Generic JSON POST (Discord, Slack, Zapier, SMS services, custom)
- ❌ **Error Display**: Shows when alerts fail to send
- 📊 **Smart Tracking**: Prevents duplicate stage alerts per pair

### Gates & Filters
- Δ (Delta) - % change from lowest low
- Volume Spike - Filters fake-outs
- RSI - Momentum indicator
- MACD Histogram - Trend strength
- ATR % - Volatility filter
- Trend Breakout - Resistance breaks
- ROC - Rate of change
- MACD Cross - Early entry detection

### Exchanges
- Coinbase (default)
- Binance
- More coming soon

---

## 📋 Requirements

```bash
pip install streamlit>=1.33 pandas>=2.0 numpy>=1.24 requests>=2.31
```

Or use requirements.txt:
```
streamlit>=1.33
pandas>=2.0
numpy>=1.24
requests>=2.31
```

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Setup Email Alerts (Optional)
- Copy `secrets_template.toml` to `.streamlit/secrets.toml`
- Follow instructions in template to setup Gmail App Password
- Update `sender_email` and `sender_password`

### 3. Run the App
```bash
streamlit run crypto_tracker_complete.py
```

### 4. Configure Settings
- Set your preferred timeframe (default: 1h)
- Adjust lookback candles and % threshold
- Enable alerts in "Alert Strategy" section
- Enter email/webhook in "Notifications"

### 5. Bookmark Your Configuration
- All settings save to URL automatically
- Bookmark the URL to preserve your setup
- Share URL = share exact configuration

---

## ⚙️ Configuration Guide

### Market Settings
- **Exchange**: Choose Coinbase or Binance
- **Quote Currency**: USD, USDC, USDT, BTC, ETH, EUR
- **Pairs to Discover**: How many pairs to scan (5-500)

### Timeframe Settings
- **Sort Timeframe**: 15m, **1h** (default), 4h
- **Sort Descending**: Show highest % changes first

### Gates
All gates are **OFF by default** - enable only what you need:

**Quick Presets:**
- Spike Hunter: Volume + basic filters
- Early MACD Cross: Early entry signals
- Confirm Rally: Strong confirmation required
- hioncrypto's Velocity Mode: Explosive move detector
- None: Manual configuration

**Key Settings:**
- **Δ lookback**: Candles to search for lowest low (default: 3)
- **Min +% change**: Threshold for alerts and filtering (default: 3%)
- **Min bars filter**: OFF by default - turn ON to exclude new pairs

### Alert Strategy
1. Toggle **Enable Alerts** ON
2. Progressive alerts fire at all 3 stages automatically
3. No need to select stages - all fire as move develops

### Notifications
- **Email**: Enter recipient address (requires SMTP setup)
- **Webhook**: Enter URL for Discord, Slack, Zapier, SMS service, or custom endpoint

---

## 📧 Email Setup (Gmail)

### Step-by-Step:

1. **Enable 2-Factor Authentication**
   - Go to: https://myaccount.google.com/security
   - Turn ON "2-Step Verification"

2. **Generate App Password**
   - Go to: https://myaccount.google.com/apppasswords
   - App: "Mail"
   - Device: "Other" → name it "Crypto Tracker"
   - Copy the 16-character password

3. **Create Secrets File**
   ```bash
   mkdir .streamlit
   cp secrets_template.toml .streamlit/secrets.toml
   ```

4. **Edit `.streamlit/secrets.toml`**
   ```toml
   [email]
   smtp_host = "smtp.gmail.com"
   smtp_port = 587
   sender_email = "your-actual-email@gmail.com"
   sender_password = "your-16-char-app-password"
   ```

5. **Test in App**
   - Enter recipient email
   - Enable alerts
   - Wait for real alert or trigger manually

---

## 🔗 Webhook Setup

### Discord
```
https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
```

### Slack
```
https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### Zapier/Make/IFTTT
Use your webhook trigger URL from the service

### SMS via Twilio/Vonage
1. Set up account with SMS provider
2. Create webhook → SMS automation
3. Enter webhook URL in app

### Custom Endpoint
Any URL that accepts JSON POST with this structure:
```json
{
  "pair": "ALCX-USD",
  "stage": "stage2",
  "stage_name": "Histogram Confirmed",
  "price": 9.60,
  "change_pct": 4.2,
  "timeframe": "1h",
  "exchange": "Coinbase",
  "signal": "Watch",
  "timestamp": "2025-11-13T15:00:00Z",
  "timeline": {
    "stage1": true,
    "stage2": true,
    "stage3": false,
    "stage1_price": 9.21,
    "stage2_price": 9.60
  }
}
```

---

## 📱 Mobile Usage

The tracker is **fully mobile-responsive**:

- Sidebar auto-collapses on phones
- Tables scroll horizontally
- Touch-friendly buttons (44px minimum)
- Stacked metrics on small screens
- Optimized fonts for readability

**Recommended:**
- Use landscape orientation for tables
- Bookmark configured URL for quick access
- Enable browser notifications for alerts

---

## 🎯 Alert Examples

### Stage 1 Alert (Email)
```
⚠️ ALCX-USD - Stage 1: MACD Cross

Pair: ALCX-USD
Price: $9.210000
Change: +0.00%
Timeframe: 1h
Exchange: Coinbase
Signal: Neutral

Timeline:
✅ Stage 1: MACD crossed @ $9.21 (0 min ago)

Detected: 2025-11-13 12:30:00 UTC
```

### Stage 2 Alert (Email)
```
📈 ALCX-USD - Stage 2: Histogram Confirmed

Pair: ALCX-USD
Price: $9.600000
Change: +4.23%
Timeframe: 1h
Exchange: Coinbase
Signal: Watch

Timeline:
✅ Stage 1: MACD crossed @ $9.21 (75 min ago)
✅ Stage 2: Histogram+ @ $9.60 (0 min ago)

Detected: 2025-11-13 13:45:00 UTC
```

### Stage 3 Alert (Email)
```
🚀 ALCX-USD - Stage 3: Threshold Hit

Pair: ALCX-USD
Price: $10.150000
Change: +10.25%
Timeframe: 1h
Exchange: Coinbase
Signal: Strong Buy

Timeline:
✅ Stage 1: MACD crossed @ $9.21 (150 min ago)
✅ Stage 2: Histogram+ @ $9.60 (75 min ago)
🚀 Stage 3: Threshold @ $10.15 (0 min ago)

Detected: 2025-11-13 15:00:00 UTC
```

---

## 🔧 Troubleshooting

### Settings Not Persisting
- **Solution**: Check browser allows URL updates
- Settings save to URL parameters automatically
- Bookmark the URL with parameters

### Emails Not Sending
- Check spam folder
- Verify App Password (not regular Gmail password)
- Ensure 2FA enabled on Gmail
- Check error messages in app

### Webhook Failing
- Test webhook URL manually (curl/Postman)
- Check endpoint accepts JSON POST
- Verify webhook URL is correct
- Check error messages in app

### ALCX % Doesn't Match TradingView
- Verify timeframe matches (1h = 1h)
- Check lookback setting (20 candles = 20 bars)
- Remember: calculates from LOWEST LOW in window

### No Alerts Firing
- Check "Enable Alerts" toggle is ON
- Verify email/webhook configured
- Ensure pairs actually hit thresholds
- Lower "Min +% change" slider temporarily to test

### Mobile Issues
- Use landscape for better table view
- Clear browser cache
- Update to latest iOS/Android browser

---

## 📊 Understanding the Calculations

### Percentage Change
```
For lookback = 20:
1. Examine last 20 candles (positions -19 to 0)
2. Find LOWEST LOW in those 20 candles
3. Calculate: (Current Close - Lowest Low) / Lowest Low × 100
```

**Example:**
- Lookback: 20 candles
- Lowest LOW: $9.21
- Current Close: $10.15
- % Change: (10.15 - 9.21) / 9.21 × 100 = **10.2%**

### MACD Cross Detection
```
Stage 1: MACD line crosses signal line below zero
Stage 2: Histogram turns positive (MACD > Signal)
Stage 3: Price hits % threshold
```

---

## 🎨 Customization Tips

### For Day Trading (Fast Moves)
```
Timeframe: 15m
Lookback: 10
Min %: 5%
Preset: hioncrypto's Velocity Mode
```

### For Swing Trading (Quality Moves)
```
Timeframe: 4h
Lookback: 30
Min %: 15%
Preset: Confirm Rally
```

### For Early Entry Hunting
```
Timeframe: 1h
Lookback: 20
Min %: 10%
Gates: Enable MACD Cross + Histogram
Alerts: ON
```

---

## 🔐 Security Best Practices

1. **Never commit secrets.toml to Git**
   - Add to `.gitignore`
   - Use environment variables for production

2. **Use App Passwords**
   - Never use real Gmail password
   - Revoke if compromised

3. **Secure Webhooks**
   - Use HTTPS endpoints only
   - Validate webhook sources
   - Rate limit your endpoints

4. **URL Persistence**
   - Email/webhook visible in browser history
   - Clear history if using shared computer
   - Use private/incognito for sensitive configs

---

## 📈 Performance Tips

1. **Reduce Pairs for Speed**
   - Mobile: 50 pairs recommended
   - Desktop: 100-200 pairs optimal
   - 500 pairs: slower but comprehensive

2. **Cache Management**
   - Auto-refreshes every 30 seconds
   - Click "Clear Cache" if data seems stale
   - "Refresh Now" forces immediate update

3. **API Rate Limits**
   - Coinbase: Generally lenient
   - Binance: May hit limits with 500+ pairs
   - Reduce pairs if seeing errors

---

## 🐛 Known Issues

1. **WebSocket**: Currently disabled - using REST only
2. **Listing Radar**: Placeholder - monitoring not yet active
3. **ATH/ATL**: Calculation in progress but not displayed

---

## 🚀 Coming Soon

- Real-time WebSocket price updates
- Active Listing Radar notifications
- Stock tracker with same features
- Discord bot integration
- Advanced charting
- Backtesting mode
- Portfolio tracking

---

## 💡 Tips & Tricks

1. **Create Multiple Bookmarks**
   - Conservative setup (high threshold)
   - Aggressive setup (low threshold + early alerts)
   - Watchlist-only setup

2. **Use My Pairs**
   - Track specific coins you own
   - Quick access via ⭐ toggle

3. **Alert Management**
   - Start with higher threshold (20%+) to avoid spam
   - Lower gradually as you learn patterns
   - Use webhook for mobile notifications

4. **Interpretation**
   - Stage 1: Research time (not committed yet)
   - Stage 2: Decision time (enter or wait?)
   - Stage 3: Late entry or validation (already moving)

---

## 📞 Support

**Issues/Bugs:**
- Open GitHub issue
- Include error messages
- Describe steps to reproduce

**Feature Requests:**
- Submit via GitHub
- Explain use case
- Vote on existing requests

---

## 📄 License

Created by **hioncrypto** - All Rights Reserved

This software is for personal use only.
Commercial use requires explicit permission.

---

## 🙏 Acknowledgments

Built with:
- Streamlit (UI framework)
- Pandas (data processing)
- NumPy (calculations)
- Requests (API calls)

Powered by:
- Coinbase Pro API
- Binance API

---

**Last Updated**: 2025-11-13
**Version**: 3.0.0 (Progressive Alerts + Full Persistence)
**Author**: hioncrypto

---

*Happy Trading! 🚀📈*
