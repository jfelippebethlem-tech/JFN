@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM iniciar.bat — Inicia o JFN Compliance Agent no Windows
REM
REM Uso:
REM   iniciar.bat            → scheduler diário (executa todo dia às 08:00)
REM   iniciar.bat --agora    → roda coleta imediatamente e mostra resultado
REM   iniciar.bat --groq     → inicia o Groq explorer (IA no SIAFE2)
REM   iniciar.bat --analisar → mostra relatório completo do banco
REM   iniciar.bat --obs      → lista OBs coletadas
REM ─────────────────────────────────────────────────────────────────────────────
cd /d "%~dp0"

echo.
echo   JFN Compliance Agent - Auditoria SIAFE2 + DOERJ
echo   ══════════════════════════════════════════════════
echo.

REM ── Verificar .env ────────────────────────────────────────────────────────────
if not exist .env (
    echo   ERRO: arquivo .env nao encontrado!
    echo   Crie o arquivo .env com:
    echo     SIAFE_USER=seu_cpf
    echo     SIAFE_PASS=sua_senha
    pause
    exit /b 1
)

REM ── Carregar variáveis do .env ────────────────────────────────────────────────
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
)
echo   .env carregado (usuario: %SIAFE_USER%)

REM ── Inicializar banco de dados ─────────────────────────────────────────────────
echo   Inicializando banco de dados...
python -c "from compliance_agent.database.models import init_db; init_db(); print('  DB OK')"
if errorlevel 1 (
    echo   ERRO ao inicializar banco de dados!
    pause
    exit /b 1
)

REM ── Verificar Chrome debug port ────────────────────────────────────────────────
curl -s "http://127.0.0.1:9222/json/version" >nul 2>&1
if errorlevel 1 (
    echo   AVISO: Chrome NAO esta aberto na porta 9222
    echo   Para coleta automatica do SIAFE2, abra o Chrome assim:
    echo     chrome.exe --remote-debugging-port=9222
    echo   Continuando sem Chrome -- coleta SIAFE2 sera pulada.
    echo.
) else (
    echo   Chrome OK na porta 9222
)

REM ── Dispatch por argumento ─────────────────────────────────────────────────────
if "%1"=="--agora" goto agora
if "%1"=="--groq"  goto groq
if "%1"=="--analisar" goto analisar
if "%1"=="--obs"   goto obs
goto scheduler

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
    echo   ERRO: Chrome nao esta aberto. Abra com --remote-debugging-port=9222 primeiro.
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

:scheduler
echo.
echo   Iniciando scheduler diario (executa todo dia as 08:00)...
echo   Pressione Ctrl+C para parar.
echo.
python -m compliance_agent.scheduler --loop

:fim
