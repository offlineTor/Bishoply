#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo "Bishoply status"
echo "==============="

check_pid () {
  NAME="$1"
  FILE="$2"

  if [ ! -f "$FILE" ]; then
    echo "$NAME: not started"
    return
  fi

  PID=$(cat "$FILE")

  if kill -0 "$PID" 2>/dev/null; then
    echo "$NAME: running, PID $PID"
  else
    echo "$NAME: stopped, stale PID $PID"
  fi
}

check_pid "Bot" "pids/bot.pid"
check_pid "Backend" "pids/backend.pid"
check_pid "Frontend" "pids/frontend.pid"
check_pid "Tunnel" "pids/tunnel.pid"

echo ""
TUNNEL_URL=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' logs/tunnel.log 2>/dev/null | tail -1)
echo "Public tunnel URL: ${TUNNEL_URL:-unknown}"
echo "Live process check:"
ps aux | grep -E "uvicorn|vite|cloudflared|bot.py" | grep -v grep || echo "No Bishoply processes found."
echo ""
