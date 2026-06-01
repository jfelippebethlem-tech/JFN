@echo off
REM ============================================================
REM   JFN.bat  —  INICIA TUDO COM UM COMANDO SO
REM ============================================================
REM   - Abre o Chrome com porta de debug (9222) no SIAFE2
REM   - Carrega o .env (credenciais)
REM   - Inicializa o banco de dados
REM   - Sobe o agente em monitoramento CONTINUO + bot Telegram
REM
REM   Basta dar DUPLO CLIQUE neste arquivo.
REM   Para parar tudo: feche esta janela ou Ctrl+C.
REM ============================================================
title JFN Compliance Agent
cd /d "%~dp0"

echo.
echo   ============================================================
echo     JFN COMPLIANCE AGENT - Auditoria continua SIAFE2 + DOERJ
echo   ============================================================
echo.

REM ---------- 1. Verificar .env ----------
if not exist .env (
    echo   ERRO: arquivo .env nao encontrado!
    echo   Crie o .env com SIAFE_USER, SIAFE_PASS, GROQ_API_KEY, etc.
    pause
    exit /b 1
)

REM Carregar .env (ignora linhas vazias e comentarios)
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" (
        if not "%%A"=="#" (
            set "%%A=%%B"
        )
    )
)
echo   [1/4] .env carregado

REM ---------- 2. Atualizar codigo (git pull) ----------
echo   [2/4] Buscando atualizacoes...
git config user.email "jfn@compliance.local" >nul 2>&1
git config user.name "JFN Compliance Bot" >nul 2>&1
git pull origin claude/rj-finance-agent-BYlhJ >nul 2>&1
if errorlevel 1 (
    echo         (sem internet ou sem atualizacoes - seguindo)
) else (
    echo         codigo atualizado
)

REM ---------- 3. Abrir Chrome com porta de debug ----------
echo   [3/4] Verificando Chrome...
curl -s "http://127.0.0.1:9222/json/version" >nul 2>&1
if errorlevel 1 (
    echo         Chrome nao esta no modo debug. Abrindo...
    call :abrir_chrome
) else (
    echo         Chrome ja esta no modo debug - OK
)

REM ---------- 4. Inicializar banco e subir agente ----------
echo   [4/4] Inicializando banco e subindo agente...
python -c "from compliance_agent.database.models import init_db; init_db()" 2>nul

echo.
echo   ============================================================
echo     AGENTE NO AR. Monitoramento a cada 15 min (7h-20h).
echo     Relatorio completo todo dia as 08:00.
echo     Bot Telegram ativo - envie /ajuda no celular.
echo.
echo     NAO FECHE esta janela. Para parar: Ctrl+C.
echo   ============================================================
echo.

python -m compliance_agent.scheduler --loop

echo.
echo   Agente parado. Pressione qualquer tecla para sair.
pause >nul
exit /b 0

REM ============================================================
REM   Sub-rotina: abrir o Chrome com porta de debug
REM ============================================================
:abrir_chrome
set CHROME_EXE=
if exist "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe" set CHROME_EXE="%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"
if exist "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe" set CHROME_EXE="%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set CHROME_EXE="%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if "%CHROME_EXE%"=="" (
    echo         AVISO: Chrome nao encontrado. Coleta SIAFE2 sera pulada.
    echo         Instale o Chrome ou edite o caminho em chrome_debug.bat
    goto :eof
)

REM Fecha Chrome aberto (porta de debug exige Chrome reiniciado)
taskkill /f /im chrome.exe >nul 2>&1
ping 127.0.0.1 -n 3 >nul

start "" %CHROME_EXE% --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data" "https://siafe2.fazenda.rj.gov.br/Siafe/"
echo         Chrome aberto no SIAFE2. Faca login se necessario.
echo         (o agente faz re-login automatico quando a sessao expira)
ping 127.0.0.1 -n 5 >nul
goto :eof
