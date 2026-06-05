@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  COLETAR_OBS.bat — Coleta Ordens Bancarias SIAFE 2023-2026
REM  MGS CLEAN SOLUCOES E SERVICOS LTDA — CNPJ 19.088.605/0001-04
REM ============================================================
REM  Como usar:
REM    1. Duplo clique neste arquivo (na pasta do JFN)
REM    2. O Chrome abre no SIAFE2 automaticamente
REM    3. A coleta roda e salva os dados em data/sei_cache/
REM    4. Ao terminar, os dados sao enviados ao git automaticamente
REM
REM  Prerequisito: JFN.bat ja deve ter rodado pelo menos uma vez
REM  (para instalar as dependencias Python / Playwright).
REM ============================================================
title SIAFE — Coletando Ordens Bancarias MGS CLEAN
cd /d "%~dp0"

echo.
echo   ============================================================
echo     SIAFE — Coleta de Ordens Bancarias (2023-2026)
echo     MGS CLEAN — CNPJ 19.088.605/0001-04
echo   ============================================================
echo.

REM ── Carrega .env ─────────────────────────────────────────────
set "ENV_FILE="
if exist .env set "ENV_FILE=.env"
if not defined ENV_FILE if exist .env.txt set "ENV_FILE=.env.txt"
if not defined ENV_FILE goto :sem_env

for /f "usebackq tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    if not "%%A"=="" if not "%%A"=="#" set "%%A=%%B"
)
if "%SIAFE_USER%"=="" goto :sem_user
echo   [1/4] Credenciais OK (usuario %SIAFE_USER%)

REM ── Garante que o Chrome modo debug esta rodando ──────────────
echo   [2/4] Verificando Chrome (modo debug, porta 9222)...
curl -s "http://127.0.0.1:9222/json/version" >nul 2>&1
if not errorlevel 1 goto :chrome_ok

REM Procura o executavel do Chrome
set "CHROME_EXE="
if exist "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"
if exist "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE goto :sem_chrome

echo         Abrindo Chrome com debug na porta 9222...
start "" "%CHROME_EXE%" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\JFN\ChromeDebug" --no-first-run --no-default-browser-check "https://siafe2.fazenda.rj.gov.br/Siafe/"

REM Aguarda Chrome subir (ate 30s)
set /a t=0
:aguarda_chrome
set /a t+=1
if !t! gtr 10 goto :chrome_timeout
ping 127.0.0.1 -n 4 >nul
curl -s "http://127.0.0.1:9222/json/version" >nul 2>&1
if errorlevel 1 goto :aguarda_chrome

:chrome_ok
echo         Chrome pronto (porta 9222)

REM ── Roda o coletor ────────────────────────────────────────────
echo   [3/4] Coletando Ordens Bancarias 2023-2026...
echo         (Isso pode levar 15-30 minutos — aguarde)
echo.
python _SANDBOX/coletar_obs_agora.py
if errorlevel 1 goto :erro_coleta

:coleta_ok
echo.
echo   [4/4] Coleta concluida!

REM Verifica se o arquivo foi gerado
if exist "data\sei_cache\mgsclean_obs_todas.json" goto :sucesso
echo         AVISO: arquivo consolidado nao encontrado.
echo         Verifique screenshots\ para diagnostico.
goto :fim

:sucesso
echo         Dados salvos em data/sei_cache/mgsclean_obs_todas.json
echo.
echo         Gerando relatorio PDF...
python _SANDBOX/gerar_relatorio_obs_pdf.py 2>nul
if exist "reports\auditoria_obs_mgs_clean.pdf" echo         PDF: reports/auditoria_obs_mgs_clean.pdf
echo.
echo   ============================================================
echo     COLETA CONCLUIDA COM SUCESSO!
echo     Dados enviados ao git automaticamente pelo script.
echo   ============================================================
goto :fim

REM ── Erros ──────────────────────────────────────────────────────
:sem_env
echo   ERRO: .env nao encontrado. Execute JFN.bat primeiro.
pause & exit /b 1

:sem_user
echo   ERRO: SIAFE_USER vazio no .env.
pause & exit /b 1

:sem_chrome
echo   AVISO: Chrome nao encontrado.
echo   O script tentara abrir o proprio Chromium (mais lento).
echo   Continuando...
python _SANDBOX/coletar_obs_agora.py
goto :fim

:chrome_timeout
echo   AVISO: Chrome nao respondeu em 30s. Continuando mesmo assim...
python _SANDBOX/coletar_obs_agora.py
goto :fim

:erro_coleta
echo.
echo   ERRO na coleta. Verifique:
echo   - screenshots/obs_coleta/ para ver onde parou
echo   - SIAFE esta acessivel nesta maquina?
echo   - Credenciais corretas no .env?
pause
exit /b 1

:fim
echo.
pause
