# Deploy hioncrypto Scanner (production SaaS)

## Overview

| Role | URL (example) |
|------|----------------|
| Landing / marketing | `https://hioncrypto.com` (Carrd or static site) |
| Scanner app | `https://app.hioncrypto.com` (Railway / Fly + Docker) |

The scanner runs **Streamlit in Docker** on infrastructure you control. Code stays on your server; users only get the web UI.

---

## Quick start — Railway

1. Push this repo to **private GitHub**.
2. Create a [Railway](https://railway.app) project → **Deploy from GitHub** → select repo.
3. Railway detects `Dockerfile` / `railway.toml`.
4. Set environment variables (see `.env.example`):
   - `SAAS_GATE_ENABLED=false` until Stripe is wired
   - Later: `STRIPE_SECRET_KEY`, `STRIPE_CHECKOUT_URL`, etc.
5. Add custom domain `app.hioncrypto.com` in Railway → point DNS CNAME to Railway.
6. For Streamlit secrets (SMTP), use Railway variables or mount secrets — mirror `.streamlit/secrets_template.toml`.

---

## Local Docker test

```bash
cp .env.example .env
docker build -t hioncrypto-scanner .
docker run --rm -p 8501:8501 --env-file .env hioncrypto-scanner
```

Open http://localhost:8501

---

## Streamlit Cloud (dev / beta only)

Still works for personal testing:

```bash
streamlit run app.py
```

Not recommended for multi-tenant paid SaaS (shared worker state, ephemeral disk).

---

## SaaS gate

Set `SAAS_GATE_ENABLED=true` on the host to show a subscribe placeholder instead of the scanner. Wire Stripe Checkout URL in `STRIPE_CHECKOUT_URL` until full auth webhooks are implemented.

---

## Stripe webhook (Phase 1 — next coding step)

1. Stripe Dashboard → Webhooks → endpoint `https://app.hioncrypto.com/stripe/webhook`
2. Events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
3. Set `STRIPE_WEBHOOK_SECRET` on Railway

---

## Checklist before ads

- [ ] `SAAS_GATE_ENABLED=true` + Checkout works
- [ ] Pay → access without manual email
- [ ] `.gitignore` prevents committing secrets
- [ ] Terms + Privacy linked on landing page
- [ ] Test scan on mobile browser
