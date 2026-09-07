#!/bin/bash
cd "$(dirname "$0")"

echo "Starting Bishoply..."

mkdir -p logs pids

if [ ! -f ".env" ]; then
  echo "Missing .env file. Bishoply cannot start without secrets."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Missing .venv. Backend is not installed yet."
else
  source .venv/bin/activate

  if [ -f "auth_server.py" ]; then
    nohup uvicorn auth_server:app --host 127.0.0.1 --port 8000 > logs/backend.log 2>&1 &
    echo $! > pids/backend.pid
    echo "Backend started."
  else
    echo "Backend source missing. Skipping backend."
  fi

  if [ -f "bot.py" ]; then
    nohup python3 bot.py > logs/bot.log 2>&1 &
    echo $! > pids/bot.pid
    echo "Bot started."
  else
    echo "Bot source missing. Skipping bot."
  fi
fi

if [ -d "frontend" ]; then
  cd frontend

  if [ -f "package.json" ]; then
    nohup npx vite --host 0.0.0.0 --port 5173 > ../logs/frontend.log 2>&1 &
    echo $! > ../pids/frontend.pid
    echo "Frontend started."
  else
    echo "Frontend package missing. Skipping frontend."
  fi

  cd ..
else
  echo "Frontend folder missing. Skipping frontend."
fi

if command -v cloudflared >/dev/null 2>&1; then
  nohup cloudflared tunnel --url http://localhost:5173 > logs/tunnel.log 2>&1 &
  echo $! > pids/tunnel.pid
  echo "Tunnel started."
else
  echo "cloudflared not installed or not found. Skipping tunnel."
fi

sleep 2
TUNNEL_URL=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' logs/tunnel.log 2>/dev/null | tail -1)
if [ -n "$TUNNEL_URL" ]; then
  echo "Public tunnel URL: $TUNNEL_URL"
else
  echo "Public tunnel URL: pending (see logs/tunnel.log)"
fi

echo ""
echo "Bishoply startup command finished."
echo "Run ./status.sh to check what is running."
echo "Run ./logs.sh to inspect errors."
