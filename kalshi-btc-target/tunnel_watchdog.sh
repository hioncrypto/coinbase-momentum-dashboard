#!/usr/bin/env bash
# Keep BeatLine reachable at a STABLE public URL.
#
# Quick Cloudflare tunnels hand out a new hostname on every restart, which
# wipes browser-stored balance and breaks the home-screen icon. localtunnel
# supports a fixed subdomain, so the URL stays the same across restarts.
#
#   ./tunnel_watchdog.sh [origin_url] [subdomain]
#
# Primary URL:  https://<subdomain>.loca.lt   (stable)
# Fallback URL: rotating *.trycloudflare.com  (only if localtunnel is down)
#
# loca.lt shows a one-time "Tunnel website ahead!" page per browser — tap
# "Click to Continue" once, then it behaves like a normal site.
#
# Current URLs are written to /tmp/beatline-tunnel-url.txt (primary) and
# /tmp/beatline-tunnel-fallback.txt.
#
# For a permanent host with no click-through, see DEPLOY.md.

set -uo pipefail

ORIGIN="${1:-http://127.0.0.1:8765}"
SUBDOMAIN="${2:-beatline15m}"
PORT="${ORIGIN##*:}"
PORT="${PORT%%/*}"
CLOUDFLARED="${CLOUDFLARED:-/tmp/cloudflared}"
LT_LOG=/tmp/beatline-localtunnel.log
CF_LOG=/tmp/beatline-cloudflared.log
URL_FILE=/tmp/beatline-tunnel-url.txt
FALLBACK_FILE=/tmp/beatline-tunnel-fallback.txt
CHECK_SEC="${CHECK_SEC:-25}"

origin_ok() {
  curl -s -o /dev/null -m 5 "$ORIGIN/api/health"
}

kill_localtunnel() {
  pkill -f "localtunnel --port $PORT" 2>/dev/null || true
  pkill -f "lt --port $PORT" 2>/dev/null || true
  sleep 2
}

# One localtunnel attempt; echoes the assigned URL.
try_localtunnel() {
  kill_localtunnel
  : > "$LT_LOG"
  nohup npx -y localtunnel --port "$PORT" --subdomain "$SUBDOMAIN" >> "$LT_LOG" 2>&1 &
  for _ in $(seq 1 40); do
    url=$(grep -oE 'https://[a-z0-9.-]+\.loca\.lt' "$LT_LOG" | head -1)
    if [ -n "$url" ]; then
      echo "$url"
      return 0
    fi
    sleep 1
  done
  return 1
}

start_localtunnel() {
  # The fixed subdomain can be briefly leased to a just-killed instance, so
  # retry until we get it back — a rotating name is what breaks saved data.
  for attempt in 1 2 3 4; do
    url=$(try_localtunnel) || url=""
    if [ -n "$url" ]; then
      echo "$url" > "$URL_FILE"
      if [ "$url" = "https://$SUBDOMAIN.loca.lt" ]; then
        echo "[watchdog] stable tunnel up: $url"
        return 0
      fi
      echo "[watchdog] got $url instead of $SUBDOMAIN (attempt $attempt)"
    fi
    sleep 10
  done
  url=$(cat "$URL_FILE" 2>/dev/null || true)
  if [ -n "$url" ]; then
    echo "[watchdog] using non-fixed tunnel: $url"
    return 0
  fi
  echo "[watchdog] localtunnel did not report a URL"
  return 1
}

# localtunnel answers API calls directly; browsers get a one-time 511 reminder.
localtunnel_ok() {
  local url code
  url=$(cat "$URL_FILE" 2>/dev/null || true)
  [ -n "$url" ] || return 1
  code=$(curl -s -o /dev/null -m 15 -H 'bypass-tunnel-reminder: 1' \
    -w '%{http_code}' "$url/api/health" || echo 000)
  [ "$code" = "200" ]
}

start_cloudflared() {
  [ -x "$CLOUDFLARED" ] || return 1
  pkill -f "$CLOUDFLARED tunnel" 2>/dev/null || true
  sleep 1
  : > "$CF_LOG"
  nohup "$CLOUDFLARED" tunnel --protocol http2 --url "$ORIGIN" >> "$CF_LOG" 2>&1 &
  for _ in $(seq 1 25); do
    url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$CF_LOG" | head -1)
    if [ -n "$url" ]; then
      echo "$url" > "$FALLBACK_FILE"
      echo "[watchdog] fallback tunnel up: $url"
      return 0
    fi
    sleep 1
  done
  return 1
}

cloudflared_ok() {
  local url code
  url=$(cat "$FALLBACK_FILE" 2>/dev/null || true)
  [ -n "$url" ] || return 1
  code=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$url/api/health" || echo 000)
  [ "$code" = "200" ]
}

# Tell the phone about a new link via Web Push so nobody has to hunt for it.
announce_url() {
  local url="$1"
  [ -n "$url" ] || return 0
  [ "$url" = "$(cat /tmp/beatline-announced-url.txt 2>/dev/null || true)" ] && return 0
  if curl -s -m 10 -X POST "$ORIGIN/api/push/link" \
    -H 'Content-Type: application/json' \
    -d "{\"url\":\"$url\"}" > /dev/null; then
    echo "$url" > /tmp/beatline-announced-url.txt
    echo "[watchdog] pushed new link to subscribers: $url"
  fi
}

start_localtunnel || true
start_cloudflared || true
announce_url "$(cat "$URL_FILE" 2>/dev/null || true)"

lt_fails=0
cf_fails=0
while true; do
  sleep "$CHECK_SEC"
  if ! origin_ok; then
    echo "[watchdog] origin down, waiting"
    continue
  fi
  # Public tunnels blip constantly; only restart after repeated failures so we
  # don't churn the fixed subdomain (churn is what loses saved data).
  if localtunnel_ok; then
    lt_fails=0
  else
    lt_fails=$((lt_fails + 1))
    echo "[watchdog] stable tunnel check failed ($lt_fails)"
    if [ "$lt_fails" -ge 3 ]; then
      start_localtunnel || true
      announce_url "$(cat "$URL_FILE" 2>/dev/null || true)"
      lt_fails=0
    fi
  fi
  if cloudflared_ok; then
    cf_fails=0
  else
    cf_fails=$((cf_fails + 1))
    if [ "$cf_fails" -ge 3 ]; then
      start_cloudflared || true
      cf_fails=0
    fi
  fi
done
