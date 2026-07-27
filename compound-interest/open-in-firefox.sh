#!/usr/bin/env bash
# Open the daily compound calculator in Firefox (local file, no GitHub).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
FILE="$ROOT/index.html"

if command -v firefox >/dev/null 2>&1; then
  exec firefox "$FILE"
elif command -v firefox-esr >/dev/null 2>&1; then
  exec firefox-esr "$FILE"
elif command -v open >/dev/null 2>&1; then
  exec open -a Firefox "$FILE"
else
  echo "Firefox not found. Open this file manually:"
  echo "  $FILE"
  exit 1
fi
