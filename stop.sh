#!/bin/bash
cd "$(dirname "$0")"

echo "Stopping Bishoply..."

for file in pids/*.pid; do
  [ -f "$file" ] || continue

  PID=$(cat "$file")

  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    sleep 1

    if kill -0 "$PID" 2>/dev/null; then
      kill -9 "$PID" 2>/dev/null || true
    fi
  fi

  rm -f "$file"
done

pkill -f "uvicorn auth_server:app" 2>/dev/null || true
pkill -f "vite --host" 2>/dev/null || true
pkill -f "npx vite" 2>/dev/null || true
pkill -f "npm exec vite" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
pkill -f "python3 bot.py" 2>/dev/null || true
pkill -f "Python bot.py" 2>/dev/null || true

echo "Bishoply stopped."
