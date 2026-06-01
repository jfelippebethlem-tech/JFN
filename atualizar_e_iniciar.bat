@echo off
REM JFN — Atualiza o codigo e inicia o agente automaticamente.
REM Configure este arquivo no Agendador de Tarefas para rodar na inicializacao
REM e nunca mais precisar digitar nada.
cd /d "%~dp0"

echo [%DATE% %TIME%] Iniciando JFN Compliance Agent...

REM Puxa atualizacoes do repositorio
echo Atualizando codigo...
git pull origin claude/rj-finance-agent-BYlhJ
if errorlevel 1 (
    echo AVISO: git pull falhou, continuando com versao atual...
)

REM Inicia o agente (scheduler + bot Telegram)
echo Iniciando agente...
call iniciar.bat
