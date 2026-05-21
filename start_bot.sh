#!/bin/bash
# Watchdog: herstart bot automatisch bij crash of na training
# Gebruik: bash start_bot.sh
# Stop: maak /tmp/bot_stop aan of Ctrl+C

cd /home/pi/crypto_bot
VENV="/home/pi/crypto_bot/venv/bin/python"
STOP_FLAG="/tmp/bot_stop"
RESTART_LOG="logs/bot_restarts.log"

rm -f "$STOP_FLAG"

echo "$(date) | Watchdog gestart" >> "$RESTART_LOG"

while true; do
    if [ -f "$STOP_FLAG" ]; then
        echo "$(date) | Stop-vlag gevonden — watchdog stopt" >> "$RESTART_LOG"
        break
    fi

    LOGFILE="logs/bot_$(date +%Y%m%d).log"
    echo "$(date) | Bot wordt gestart" >> "$RESTART_LOG"

    $VENV bot.py >> "$LOGFILE" 2>&1
    EXIT_CODE=$?

    if [ -f "$STOP_FLAG" ]; then
        echo "$(date) | Bot gestopt (exit $EXIT_CODE) — stop-vlag actief, niet herstarten" >> "$RESTART_LOG"
        break
    fi

    echo "$(date) | Bot gestopt (exit $EXIT_CODE) — herstart over 10 seconden" >> "$RESTART_LOG"
    sleep 10
done
