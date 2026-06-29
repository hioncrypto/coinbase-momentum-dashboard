# hioncrypto Crypto Scanner

Multi-exchange momentum scanner with custom gates, email/webhook alerts, Coinbase WebSocket, and Listing Radar.

## Quick start

```bash
pip install -r requirements.txt
streamlit run app.py
```

Email alerts (optional): copy `.streamlit/secrets_template.toml` to `.streamlit/secrets.toml` and add SMTP credentials.

## Features

- **Exchanges:** Coinbase, Binance (auto `.us` fallback), Kraken, KuCoin
- **Scans:** All available pairs per quote (auto count)
- **Gates:** Δ % from lookback low, volume, RSI, MACD, ATR, trend, ROC, presets
- **Alerts:** Batch email + webhook; top-10 Strong Buy; +5% re-alert ladder
- **WebSocket:** Coinbase live prices (REST fallback)
- **Listing Radar:** New pair detection per exchange + quote

## Deploy (production / SaaS)

See **[DEPLOY.md](DEPLOY.md)** for Docker + Railway hosting.

- `SAAS_GATE_ENABLED=false` (default) — open access, current behavior
- `SAAS_GATE_ENABLED=true` — subscribe placeholder until Stripe is wired (`saas_gate.py`)

Copy `.env.example` to `.env` for local Docker tests.

## Marketing / legal (templates)

- Landing page copy: [landing/COPY.md](landing/COPY.md)
- Terms: [legal/TERMS.md](legal/TERMS.md) (review with counsel before selling)
- Privacy: [legal/PRIVACY.md](legal/PRIVACY.md)

## Legacy files

`app_v2.py`, `app-before-cursor.py`, and `app_broken_backup.py` are old backups — **use `app.py` only**.

## Streamlit Cloud

Push to `main` on GitHub; connect repo in Streamlit Cloud. Do not commit `secrets.toml`, `user_settings.json`, or `alerted_pairs.json` (see `.gitignore`).
