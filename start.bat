@echo off
echo Monster Bot + Dashboard starten...
echo.

cd /d "%~dp0"

echo [1/2] Dashboard starten op http://localhost:8000
start "Monster Bot Dashboard" cmd /k python dashboard/app.py

timeout /t 2 /nobreak >nul

echo [2/2] Monster Bot starten (paper trading)
start "Monster Bot" cmd /k python bot.py

echo.
echo Klaar! Open je browser op: http://localhost:8000
echo.
pause
