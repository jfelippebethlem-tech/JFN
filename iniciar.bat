@echo off
REM JFN Compliance Agent - iniciar.bat
REM
REM Uso:
REM   iniciar.bat             - scheduler diario (08:00) + bot Telegram
REM   iniciar.bat --agora     - roda coleta imediatamente
REM   iniciar.bat --diag      - LE as paginas reais e relata a estrutura
REM   iniciar.bat --groq      - Groq explorer (IA autonoma no SIAFE2)
REM   iniciar.bat --analisar  - relatorio completo do banco
REM   iniciar.bat --obs       - lista OBs coletadas
REM   iniciar.bat --telegram  - testa conexao Telegram e aguarda comandos
REM
REM Controle pelo celular (via Telegram):
REM   /status    - situacao atual do sistema
REM   /obs       - ultimas OBs coletadas
REM   /agora     - dispara coleta agora
REM   /relatorio - envia PDF do dia
REM   /ajuda     - ajuda
cd /d "%~dp0"

echo.
echo   JFN Compliance Agent - Auditoria SIAFE2 + DOERJ
echo   ==================================================
echo.

REM Verificar .env
if not exist .env (
    echo   ERRO: arquivo .env nao encontrado!
    echo   Crie o arquivo .env com SIAFE_USER e SIAFE_PASS
    pause
    exit /b 1
)

REM Carregar .env (ignora linhas vazias e comentarios com #)
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    set "line=%%A"
    if not "%%A"=="" (
        if not "%%A"=="#" (
            set "%%A=%%B"
        )
    )
)
echo   .env carregado

REM Inicializar banco de dados
echo   Inicializando banco de dados...
python -c "from compliance_agent.database.models import init_db; init_db(); print('  DB OK')"
if errorlevel 1 (
    echo   ERRO ao inicializar banco de dados!
    pause
    exit /b 1
)

REM Verificar Chrome debug port
curl -s "http://127.0.0.1:9222/json/version" >nul 2>&1
if errorlevel 1 (
    echo   AVISO: Chrome NAO esta aberto na porta 9222
    echo   Para coleta do SIAFE2 abra: chrome.exe --remote-debugging-port=9222
    echo   Continuando sem Chrome - coleta SIAFE2 sera pulada.
    echo.
) else (
    echo   Chrome OK na porta 9222
)

REM Dispatch por argumento
if "%1"=="--agora"    goto agora
if "%1"=="--diag"     goto diag
if "%1"=="--groq"     goto groq
if "%1"=="--analisar" goto analisar
if "%1"=="--obs"      goto obs
if "%1"=="--telegram" goto telegram
goto scheduler

:diag
echo.
echo   Lendo as paginas reais (SIAFE2 + IOERJ) pelo Chrome aberto...
curl -s "http://127.0.0.1:9222/json/version" >nul 2>&1
if errorlevel 1 (
    echo   ERRO: Chrome nao esta aberto. Abra com --remote-debugging-port=9222
    pause
    exit /b 1
)
python diagnostico.py
echo.
echo   Enviando diagnosticos para o repositorio (Claude le de la)...
git add data/diagnostics
git commit -m "diagnostico automatico %DATE% %TIME%"
git pull --rebase origin claude/rj-finance-agent-BYlhJ
git push origin claude/rj-finance-agent-BYlhJ
echo   Diagnosticos enviados.
goto fim

:agora
echo.
echo   Rodando ciclo de coleta AGORA...
python -m compliance_agent.scheduler
echo.
echo   Resultado:
python analisar.py
goto fim

:groq
echo.
echo   Iniciando Groq Explorer (IA autonoma no SIAFE2)...
curl -s "http://127.0.0.1:9222/json/version" >nul 2>&1
if errorlevel 1 (
    echo   ERRO: Chrome nao esta aberto. Abra com --remote-debugging-port=9222
    pause
    exit /b 1
)
python -m siafe_agent.llm.groq_explorer
goto fim

:analisar
echo.
python analisar.py --tudo
goto fim

:obs
echo.
python analisar.py --obs
goto fim

:telegram
echo.
echo   Testando conexao Telegram e aguardando comandos do celular...
python -m compliance_agent.notifications.telegram
goto fim

:scheduler
echo.
echo   Iniciando scheduler diario (executa todo dia as 08:00)...
echo   Bot Telegram ativo - envie /ajuda para ver os comandos.
echo   Pressione Ctrl+C para parar.
echo.
python -m compliance_agent.scheduler --loop

:fim
