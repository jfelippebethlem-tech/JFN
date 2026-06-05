@echo off
REM ============================================================
REM  TUNNEL_WINDOWS.bat — Conecta Windows ao JFN Server
REM  Permite ao servidor cloud coletar OBs via este PC
REM ============================================================
REM  PRE-REQUISITOS:
REM    1. JFN.bat já foi executado (instala deps / abre Chrome)
REM    2. Chrome rodando com --remote-debugging-port=9222
REM    3. .env com SIAFE_USER e SIAFE_PASS preenchidos
REM
REM  COMO USAR:
REM    1. Descubra o IP do servidor cloud (está no Telegram ou .env)
REM    2. Configure JFN_SERVER no .env:
REM         JFN_SERVER=ws://IP-DO-SERVIDOR:8000/tunnel
REM    3. Duplo-clique neste arquivo
REM    4. O agente no servidor irá coletar automaticamente
REM ============================================================
title JFN Tunnel Windows

cd /d "%~dp0"

REM ── Carrega .env ─────────────────────────────────────────────
set "ENV_FILE="
if exist .env set "ENV_FILE=.env"
if not defined ENV_FILE if exist .env.txt set "ENV_FILE=.env.txt"
if not defined ENV_FILE goto :sem_env
for /f "usebackq tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    if not "%%A"=="" if not "%%A"=="#" set "%%A=%%B"
)
if "%SIAFE_USER%"=="" goto :sem_user
if not defined JFN_SERVER set "JFN_SERVER=ws://localhost:8000/tunnel"
echo   Credenciais: OK (usuario %SIAFE_USER%)
echo   Servidor:    %JFN_SERVER%

REM ── Verifica se o Chrome está em modo debug ──────────────────
echo.
echo   Verificando Chrome (modo debug, porta 9222)...
curl -s "http://127.0.0.1:9222/json/version" >nul 2>&1
if not errorlevel 1 goto :chrome_ok
echo   AVISO: Chrome não está em modo debug. Iniciando...
call :abrir_chrome
ping 127.0.0.1 -n 6 >nul
curl -s "http://127.0.0.1:9222/json/version" >nul 2>&1
if errorlevel 1 echo   AVISO: Chrome não respondeu — coleta usará Chromium próprio
if not errorlevel 1 echo   Chrome OK (porta 9222)
:chrome_ok

REM ── Instala websockets se precisar ───────────────────────────
python -c "import websockets" >nul 2>&1
if errorlevel 1 (
    echo   Instalando websockets...
    python -m pip install -q websockets
)

REM ── Inicia tunnel ────────────────────────────────────────────
echo.
echo   ============================================================
echo     JFN TUNNEL ATIVO
echo     Conectando a: %JFN_SERVER%
echo     O servidor irá coletar OBs automaticamente.
echo     NAO feche esta janela durante a coleta.
echo   ============================================================
echo.

python _SANDBOX/tunnel_windows.py --server "%JFN_SERVER%"

echo.
echo   Tunnel encerrado.
pause
goto :eof

REM ──────────────────────────────────────────────────────────────
:abrir_chrome
set "CHROME_EXE="
if exist "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"
if exist "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE goto :eof
start "" "%CHROME_EXE%" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\JFN\ChromeDebug" --no-first-run --no-default-browser-check "https://siafe2.fazenda.rj.gov.br/Siafe/"
goto :eof

:sem_env
echo   ERRO: .env nao encontrado.
echo   Configure SIAFE_USER, SIAFE_PASS e JFN_SERVER no .env
pause & exit /b 1

:sem_user
echo   ERRO: SIAFE_USER vazio no .env.
pause & exit /b 1
