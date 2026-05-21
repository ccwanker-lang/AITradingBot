#!/bin/bash
TRAIN_PID=54361
BOT_VENV="/home/pi/crypto_bot/venv/bin/activate"
BOT_DIR="/home/pi/crypto_bot"
LOG="$BOT_DIR/logs/bot_$(date +%Y%m%d).log"

echo "[$(date '+%H:%M:%S')] Wachten op training (PID $TRAIN_PID)..."

# Wacht tot training klaar is
while kill -0 $TRAIN_PID 2>/dev/null; do
    sleep 10
done

echo "[$(date '+%H:%M:%S')] Training klaar! Bot herstarten..."

# Stop huidige bot
BOT_PID=$(ps aux | grep "python bot.py$" | grep -v grep | awk '{print $2}')
if [ -n "$BOT_PID" ]; then
    kill $BOT_PID
    sleep 3
    echo "[$(date '+%H:%M:%S')] Oude bot gestopt (PID $BOT_PID)"
fi

# Start bot opnieuw met nieuwe modellen
cd "$BOT_DIR"
source "$BOT_VENV"
nohup python bot.py >> "$LOG" 2>&1 &
NEW_PID=$!
echo "[$(date '+%H:%M:%S')] Bot hergestart met nieuwe modellen (PID $NEW_PID)"
