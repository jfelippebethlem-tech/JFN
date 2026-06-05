@echo off
title Yoda - Bot Telegram
rem Sobe o Yoda (bot) com AUTO-RETRY: se cair (ex.: rede nao pronta no boot),
rem limpa o lock e sobe de novo sozinho. Janela visivel (Mestre Jorge ve tudo).
cd /d "C:\Users\socah\AppData\Local\hermes\hermes-agent"
set "HERMES_HOME=C:\Users\socah\AppData\Local\hermes"
set "PYTHONIOENCODING=utf-8"
:loop
echo.
echo [%DATE% %TIME%] Iniciando Yoda (bot Telegram)...
del /q "C:\Users\socah\AppData\Local\hermes\gateway.lock" 2>nul
del /q "C:\Users\socah\AppData\Local\hermes\gateway.pid" 2>nul
"venv\Scripts\python.exe" -m hermes_cli.main gateway run
echo.
echo [%DATE% %TIME%] Yoda parou. Reiniciando em 15s... (feche esta janela para parar de vez)
timeout /t 15 >nul
goto loop
