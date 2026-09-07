#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo "Choose logs:"
echo "1) backend"
echo "2) frontend"
echo "3) tunnel"
echo "4) bot"
echo "5) all recent"
echo ""

read -p "Enter number: " choice

case "$choice" in
  1)
    tail -n 120 logs/backend.log
    ;;
  2)
    tail -n 120 logs/frontend.log
    ;;
  3)
    tail -n 120 logs/tunnel.log
    ;;
  4)
    tail -n 120 logs/bot.log
    ;;
  5)
    echo ""
    echo "===== BACKEND ====="
    tail -n 60 logs/backend.log 2>/dev/null || true
    echo ""
    echo "===== FRONTEND ====="
    tail -n 60 logs/frontend.log 2>/dev/null || true
    echo ""
    echo "===== TUNNEL ====="
    tail -n 60 logs/tunnel.log 2>/dev/null || true
    echo ""
    echo "===== BOT ====="
    tail -n 60 logs/bot.log 2>/dev/null || true
    ;;
  *)
    echo "Invalid choice."
    ;;
esac
