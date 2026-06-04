@echo off
title Hermes Web UI
rem Painel (Web UI) com AUTO-RETRY. Usa o python do HERMES DIRETO (tem AIAgent, sem re-exec
rem -> loop nao multiplica processos). Abre o Chrome no painel.
cd /d "C:\Users\socah\hermes-webui"
set "HERMES_HOME=C:\Users\socah\AppData\Local\hermes"
set "HERMES_WEBUI_HOST=127.0.0.1"
set "HERMES_WEBUI_PORT=8787"
set "HERMES_WEBUI_AGENT_DIR=C:\Users\socah\AppData\Local\hermes\hermes-agent"
set "PYTHONIOENCODING=utf-8"

rem Abre o Chrome no painel apos 12s (tempo do servidor subir)
start "" cmd /c "timeout /t 12 >nul & ( start chrome "http://127.0.0.1:8787" || start "" "http://127.0.0.1:8787" )"

:loop
echo [%DATE% %TIME%] Iniciando o Painel (Web UI)...
"C:\Users\socah\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" server.py
echo [%DATE% %TIME%] Painel parou. Reiniciando em 15s...
timeout /t 15 >nul
goto loop
