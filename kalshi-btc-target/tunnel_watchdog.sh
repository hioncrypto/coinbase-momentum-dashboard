#!/usr/bin/env bash
# Keep a quick Cloudflare tunnel alive in front of BeatLine.
#
# Quick tunnels drop and (on restart) hand out a NEW hostname. This watchdog
# restarts them automatically and records the current URL so you can look it up
# instead of waiting for someone to notice the app went stale.
#
# Prefer a real host (see DEPLOY.md) — this is only for temporary sharing.
#
#   ./tunnel_watchdog.sh [origin_url]
#
# Current URL is written to /tmp/beatline-tunnel-url.txt

set -uo pipefail

ORIGIN="${1:-http://127.0.0.1:8765}"
CLOUDFLARED="${CLOUDFLARED:-/tmp/cloudflared}"
LOG=/tmp/beatline-tunnel.log
URL_FILE=/tmp/beatline-tunnel-url.txt
CHECK_SEC="${CHECK_SEC:-20}"

start_tunnel() {
  pkill -f "$CLOUDFLARED tunnel" 2>/dev/null || true
  sleep 1
  : > "$LOG"
  nohup "$CLOUDFLARED" tunnel --protocol http2 --url "$ORIGIN" >> "$LOG" 2>&1 &
  for _ in $(seq 1 20); do
    url=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" | head -1)
    if [ -n "$url" ]; then
      echo "$url" > "$URL_FILE"
      echo "[watchdog] tunnel up: $url"
      return 0
    fi
    sleep 1
  done
  echo "[watchdog] tunnel did not report a URL"
  return 1
}

tunnel_ok() {
  local url
  url=$(cat "$URL_FILE" 2>/dev/null || true)
  [ -n "$url" ] || return 1
  local code
  code=$(curl -s -o /dev/null -m 12 -w '%{http_code}' "$url/api/health" || echo 000)
  [ "$code" = "200" ]
}

start_tunnel || true

while true; do
  sleep "$CHECK_SEC"
  if ! curl -s -o /dev/null -m 5 "$ORIGIN/api/health"; then
    echo "[watchdog] origin down, waiting"
    continue
  fi
  if ! tunnel_ok; then
    echo "[watchdog] tunnel unhealthy, restarting"
    start_tunnel || true
  fi
done
