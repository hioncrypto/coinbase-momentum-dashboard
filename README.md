# Coinbase Momentum & Volume Dashboard (Streamlit)

## Quick start (local)
```bash
pip install -r requirements.txt
streamlit run app.py
# phone on same Wi‑Fi:
# streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

## Deploy to Streamlit Community Cloud
1. Create a new GitHub repo and add these three files (`app.py`, `requirements.txt`, `README.md`).
2. Go to https://share.streamlit.io and connect your GitHub.
3. New app → pick the repo + `app.py` as the entry file → Deploy.
4. Share/open the URL on your phone and **Add to Home Screen** for an app‑like icon.

## Notes
- Uses Coinbase Advanced Trade Market Data WebSocket (`ticker_batch`) for efficient real-time updates across many pairs.
- Product discovery uses a public Coinbase Exchange endpoint as a fallback. You can paste your own product list in the sidebar.
- Alerts: configurable thresholds for 1‑min momentum (ROC), volume Z‑score spikes, and RSI crossings. Toasts appear in the browser; optional webhooks (Discord/Telegram) can be enabled in code.
