#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(pwd)"
cd "$APP_DIR"

CLOUDFLARED="${CLOUDFLARED:-/usr/local/bin/cloudflared}"
CLOUDFLARED_LOG="$APP_DIR/cloudflared_runtime.log"
BOT_LOG="$APP_DIR/assistant_runtime.log"

pkill -f "cloudflared.*127.0.0.1:8080" 2>/dev/null || true
rm -f "$CLOUDFLARED_LOG" "$BOT_LOG"

CONFIGURED_MINI_URL="$(grep -E '^MINI_APP_URL=' .env 2>/dev/null | tail -n 1 | cut -d= -f2- || true)"
CLOUDFLARED_PID=""

cleanup() {
  if [ -n "$CLOUDFLARED_PID" ]; then
    kill "$CLOUDFLARED_PID" 2>/dev/null || true
    wait "$CLOUDFLARED_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [ -n "$CONFIGURED_MINI_URL" ] && [[ "$CONFIGURED_MINI_URL" != *".trycloudflare.com"* ]]; then
  echo "Mini App URL: $CONFIGURED_MINI_URL"
else
  "$CLOUDFLARED" tunnel --protocol http2 --url http://127.0.0.1:8080 >"$CLOUDFLARED_LOG" 2>&1 &
  CLOUDFLARED_PID=$!

  MINI_URL=""
  for _ in $(seq 1 45); do
    if [ -f "$CLOUDFLARED_LOG" ]; then
      MINI_URL="$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' "$CLOUDFLARED_LOG" | head -n 1 || true)"
    fi
    if [ -n "$MINI_URL" ]; then
      break
    fi
    sleep 1
  done

  if [ -n "$MINI_URL" ]; then
    if grep -q '^MINI_APP_URL=' .env; then
      sed -i "s|^MINI_APP_URL=.*|MINI_APP_URL=$MINI_URL|" .env
    else
      printf '\nMINI_APP_URL=%s\n' "$MINI_URL" >> .env
    fi
    echo "Mini App URL: $MINI_URL"
  else
    echo "Cloudflare URL topilmadi. $CLOUDFLARED_LOG faylini tekshiring." >&2
  fi
fi

python assistant_bot.py >>"$BOT_LOG" 2>&1 &
BOT_PID=$!
set +e
wait "$BOT_PID"
BOT_EXIT=$?
set -e

if [ "$BOT_EXIT" -eq 130 ] || [ "$BOT_EXIT" -eq 143 ]; then
  exit 0
fi

exit "$BOT_EXIT"
