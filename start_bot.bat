@echo off
title Monster Bot - Paper Trading
cd /d "C:\Users\alexc\OneDrive\Documents\Desktop\crypto_bot"

:: Voorkomt dat Windows in slaapstand gaat zolang dit venster open is
powercfg /change standby-timeout-ac 0 >nul 2>&1

echo ============================================
echo   Monster Bot gestart
echo   Sluit dit venster NIET - bot stopt dan
echo ============================================
echo.

:loop
echo [%date% %time%] Bot wordt gestart...
"C:\Users\alexc\AppData\Local\Programs\Python\Python311\python.exe" bot.py
echo.
echo [%date% %time%] Bot gestopt of gecrasht - herstart in 15 seconden...
echo Druk Ctrl+C om te stoppen
timeout /t 15
goto loop
