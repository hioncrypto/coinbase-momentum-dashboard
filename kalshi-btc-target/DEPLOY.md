# Deploy BeatLine (stable hosting)

Temporary Cursor tunnels (`*.loca.lt`, `*.trycloudflare.com`) **die when the
cloud agent expires**. That is why the link keeps dying. A real host is the
only permanent fix.

## Option A — Render (recommended, free, ~2 minutes)

1. Open this deploy link (GitHub account → Render):

   **https://render.com/deploy?repo=https://github.com/hioncrypto/coinbase-momentum-dashboard**

2. If Render asks for a branch, pick the BeatLine branch
   (`cursor/beatline-standalone-7903` or the latest BeatLine PR branch).
3. Create / sign in to Render → confirm the **beatline** web service (free).
4. Wait for the first deploy. Your permanent URL looks like:

   `https://beatline.onrender.com`

5. On Android Chrome: open that URL → Add to Home Screen.
6. ⋮ Options → **Import backup** if you have an export from the old tunnel,
   or wait for the server to restore your synced account.
7. After a few trades: ⋮ Options → **Export backup** (safety copy of P/L).

### Notes

- Free Render **sleeps after ~15 minutes idle**; the first open after sleep can take ~30–60s. The URL does **not** change.
- Free tier has **no persistent disk**. BeatLine still keeps account data in your phone on that stable URL, and syncs to the server while the instance is warm. Use **Export backup** before long gaps if you care about every trade.
- Paid Render Starter (~$7/mo) + a small disk on `/opt/render/project/src/kalshi-btc-target/data` keeps server-side `demo_account.json` across sleeps.

`render.yaml` at the repo root defines this Blueprint.

## Option B — Fly.io (always-on friendly + volume)

```bash
cd kalshi-btc-target
fly auth login
fly apps create beatline-YOURNAME   # edit fly.toml app name to match
fly volumes create beatline_data --size 1 --region iad
fly deploy
```

Volume mount `/app/data` stores demo balance + trade history on the server.

Optional: add a GitHub Actions secret `FLY_API_TOKEN` so
`.github/workflows/beatline-fly.yml` can redeploy on push.

## Option C — Any VPS / Docker

```bash
cd kalshi-btc-target
docker build -t beatline .
docker run -d --restart unless-stopped -p 8765:8765 \
  -v beatline-data:/app/data --name beatline beatline
```

Put a reverse proxy or a **named** Cloudflare Tunnel (not quick trycloudflare) in front.

## Interim (dev only) — fixed localtunnel name

While a Cursor agent is running, the watchdog keeps:

`https://beatline15m.loca.lt`

Same hostname across agent restarts **when** someone brings the server back up.
It still goes offline whenever the agent VM dies. Prefer Render.

## Why not GitHub Pages?

Pages only serves static files. BeatLine needs `server.py` for Kalshi/BRTI APIs and account sync.

## After you deploy

Update your phone bookmark / home-screen icon to the new permanent URL once.
Hard-refresh once so you get the latest `app.js` / `styles.css`.
