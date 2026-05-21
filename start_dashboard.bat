@echo off
title Monster Bot - Dashboard
cd /d "C:\Users\alexc\OneDrive\Documents\Desktop\crypto_bot"

echo ============================================
echo   Dashboard gestart op http://localhost:5000
echo   Sluit dit venster NIET - dashboard stopt
echo ============================================
echo.

:loop
"C:\Users\alexc\AppData\Local\Programs\Python\Python311\python.exe" dashboard/app.py
echo.
echo Dashboard gestopt - herstart in 10 seconden...
timeout /t 10
goto loop
