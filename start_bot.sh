#!/bin/bash
cd /home/ubuntu/torrent_telegram_bot
source venv/bin/activate
nohup python3 torrent_bot.py > logs/bot.log 2>&1 &
echo "Bot iniciado em segundo plano. PID: $!"
