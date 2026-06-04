@echo off
rem Hermes Agent Gateway - Messaging Platform Integration
rem Sem argumento (chamado pela Task): re-lanca oculto via VBS e sai (sem janela persistente).
rem Com argumento RUN (chamado pelo VBS): executa o gateway de fato, oculto.
if /I not "%~1"=="RUN" (
    rem Autostart agora e VISIVEL pelo launcher no Startup (iniciar-yoda-e-painel.cmd).
    rem A tarefa agendada nao sobe mais um bot oculto (evita duplicata). Sai sem fazer nada.
    exit /b 0
)
cd /d C:\Users\socah\AppData\Local\hermes\hermes-agent
set "HERMES_HOME=C:\Users\socah\AppData\Local\hermes"
set "PYTHONIOENCODING=utf-8"
set "HERMES_GATEWAY_DETACHED=1"
set "VIRTUAL_ENV=C:\Users\socah\AppData\Local\hermes\hermes-agent\venv"
C:\Users\socah\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe -m hermes_cli.main gateway run >> "C:\Users\socah\AppData\Local\hermes\logs\gateway-stdio.log" 2>&1
exit /b 0
