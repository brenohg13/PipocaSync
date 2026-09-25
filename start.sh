#!/bin/bash
kill -9 $(pgrep -f "/home/ubuntu/torrent_telegram_bot/venv/bin/python3 torrent_bot.py") 2>/dev/null || true
cd /home/ubuntu/torrent_telegram_bot
nohup /home/ubuntu/torrent_telegram_bot/venv/bin/python3 torrent_bot.py > bot.log 2>&1 &
echo "Bot iniciado com sucesso em background!"
