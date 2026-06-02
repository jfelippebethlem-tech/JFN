@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM   HERMES.bat — LANCADOR UNICO DO AUDITOR AUTONOMO JFN
REM ============================================================
REM   Abre TUDO num comando so, na ordem logica correta:
REM     1. Credenciais (.env / .env.txt)
REM     2. Python + dependencias
REM     3. Banco de dados
REM     4. Chrome modo debug 9222 (o Hermes precisa para coletar)
REM     5. Painel web + chat do Hermes (abre no navegador)
REM     6. Agente completo (7 loops: Hermes, missao, monitor, etc.)
REM
REM   Duplo clique para rodar. Parar: feche a janela.
REM   (Sem parenteses dentro de blocos if — usa rotulos goto.)
REM ============================================================
title JFN - Hermes Auditor Autonomo
cd /d "%~dp0"

echo.
echo   ============================================================
echo     HERMES — AUDITOR AUTONOMO  (JFN Compliance - RJ)
echo   ============================================================
echo.

REM ====== PASSO 1: credenciais ===============================
echo   [1/6] Carregando credenciais (.env / .env.txt)...
set "ENV_FILE="
if exist .env set "ENV_FILE=.env"
if not defined ENV_FILE if exist .env.txt set "ENV_FILE=.env.txt"
if not defined ENV_FILE goto :sem_env
for /f "usebackq tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    if not "%%A"=="" if not "%%A"=="#" set "%%A=%%B"
)
echo         OK - credenciais de %ENV_FILE%
goto :passo2
:sem_env
echo         AVISO: .env/.env.txt nao encontrado. Sigo, mas sem login SIAFE/LLM.
:passo2

REM ====== PASSO 2: Python + deps =============================
echo   [2/6] Verificando Python e dependencias...
python --version >nul 2>&1
if errorlevel 1 goto :sem_python
python -m pip show playwright >nul 2>&1
if not errorlevel 1 goto :deps_ok
echo         instalando dependencias 1a vez, pode demorar...
python -m pip install -q -r requirements.txt
python -m playwright install chromium >nul 2>&1
:deps_ok
echo         OK - Python pronto
goto :passo3
:sem_python
echo         ERRO: Python nao encontrado no PATH. Instale com "Add to PATH".
pause
exit /b 1
:passo3

REM ====== PASSO 3: banco de dados ============================
echo   [3/6] Inicializando banco de dados...
python -c "from compliance_agent.database.models import init_db; init_db()" 2>nul
if errorlevel 1 goto :erro_banco
echo         OK - banco pronto
goto :passo4
:erro_banco
echo         ERRO ao inicializar o banco.
pause
exit /b 1
:passo4

REM ====== PASSO 4: Chrome debug 9222 =========================
echo   [4/6] Abrindo Chrome no modo debug (porta 9222)...
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=2)" >nul 2>&1
if not errorlevel 1 goto :chrome_ok
call :abrir_chrome
set /a tent=0
:espera_chrome
set /a tent+=1
timeout /t 3 /nobreak >nul
python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9222/json/version',timeout=2)" >nul 2>&1
if not errorlevel 1 goto :chrome_subiu
if !tent! lss 12 goto :espera_chrome
echo         AVISO: Chrome nao subiu no modo debug. O Hermes tentara abrir sozinho.
goto :passo5
:chrome_subiu
echo         OK - Chrome debug no ar (9222) — faca login no SIAFE nessa janela
goto :passo5
:chrome_ok
echo         OK - Chrome debug ja estava no ar (9222)
:passo5

REM ====== PASSO 5: painel web + chat do Hermes ===============
echo   [5/6] Subindo painel web e abrindo o chat do Hermes...
start "JFN Painel Web" cmd /c "python server.py --host 0.0.0.0 --port 8000"
ping 127.0.0.1 -n 4 >nul
start "" "http://localhost:8000/hermes"
echo         Chat do Hermes: http://localhost:8000/hermes
echo         Painel completo:  http://localhost:8000

REM ====== PASSO 6: agente completo (7 loops) =================
echo   [6/6] Iniciando o agente completo (Hermes + missao + monitor)...
echo.
echo   ============================================================
echo     HERMES NO AR. Defina a missao no chat (ou /missao no Telegram)
echo     e ele trabalha sozinho, sem parar. NAO FECHE esta janela.
echo   ============================================================
echo.

:rodar
python -m compliance_agent.scheduler --loop
echo.
echo   [%date% %time%] Agente encerrou. Reiniciando em 10s... (feche para parar)
ping 127.0.0.1 -n 11 >nul
goto :rodar

REM ============================================================
:abrir_chrome
set "CHROME_EXE="
if exist "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"
if exist "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE goto :sem_chrome
set "JFN_PERFIL=%LOCALAPPDATA%\JFN\ChromeDebug"
echo         Perfil JFN: %JFN_PERFIL%
echo         Abrindo Chrome com porta 9222...
start "" "%CHROME_EXE%" --remote-debugging-port=9222 --user-data-dir="%JFN_PERFIL%" --no-first-run --no-default-browser-check "https://siafe2.fazenda.rj.gov.br/Siafe/"
goto :eof
:sem_chrome
echo         AVISO: Chrome nao encontrado.
goto :eof
