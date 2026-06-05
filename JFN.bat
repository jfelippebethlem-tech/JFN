@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM   JFN.bat  —  CADEIA DE INICIALIZACAO AUTONOMA
REM ============================================================
REM   Cada passo so avanca se o anterior deu certo.
REM   Ordem logica:
REM     1. .env (credenciais)        -> sem isso, para tudo
REM     2. git pull (atualizacao)    -> opcional, segue mesmo sem net
REM     3. dependencias python       -> instala se faltar
REM     4. banco de dados            -> sem isso, para tudo
REM     5. Chrome modo debug + SIAFE -> abre e espera ficar pronto
REM     6. login automatico SIAFE    -> o agente loga sozinho
REM     7. agente continuo + Telegram-> conversa via PC e celular
REM
REM   Duplo clique para rodar. Para parar: Ctrl+C ou feche a janela.
REM
REM   IMPORTANTE: nao use parenteses ( ) dentro de blocos if (...)
REM   no CMD; eles fecham o bloco e quebram o script. Por isso este
REM   arquivo usa rotulos (goto) em vez de blocos if multi-linha.
REM ============================================================
title JFN Compliance Agent
cd /d "%~dp0"

echo.
echo   ============================================================
echo     JFN COMPLIANCE AGENT
echo     Auditoria continua SIAFE2 + DOERJ  (RJ)
echo   ============================================================
echo.

REM ====== PASSO 1: .env (aceita .env e .env.txt) =============
echo   [1/7] Carregando credenciais (.env / .env.txt)...
set "ENV_FILE="
if exist .env set "ENV_FILE=.env"
if not defined ENV_FILE if exist .env.txt set "ENV_FILE=.env.txt"
if not defined ENV_FILE goto :sem_env
for /f "usebackq tokens=1,* delims==" %%A in ("%ENV_FILE%") do (
    if not "%%A"=="" if not "%%A"=="#" set "%%A=%%B"
)
if "%SIAFE_USER%"=="" goto :sem_user
echo         OK - credenciais carregadas de %ENV_FILE% (usuario %SIAFE_USER%)
goto :passo2

:sem_env
echo         ERRO: .env (nem .env.txt) encontrado. Nao da pra continuar.
echo         Crie o .env com SIAFE_USER, SIAFE_PASS, GROQ_API_KEY...
pause
exit /b 1

:sem_user
echo         ERRO: SIAFE_USER vazio no .env. Nao da pra logar no SIAFE2.
pause
exit /b 1

:passo2
REM ====== PASSO 2: git pull ==================================
echo   [2/7] Buscando atualizacoes do codigo...
git config user.email "jfn@compliance.local" >nul 2>&1
git config user.name "JFN Compliance Bot" >nul 2>&1
git pull origin claude/rj-finance-agent-BYlhJ >nul 2>&1
if errorlevel 1 echo         sem internet/atualizacoes - seguindo com o codigo atual
if not errorlevel 1 echo         OK - codigo atualizado

REM ====== PASSO 3: dependencias python ========================
echo   [3/7] Verificando Python e dependencias...
python --version >nul 2>&1
if errorlevel 1 goto :sem_python
python -m pip show playwright >nul 2>&1
if not errorlevel 1 goto :deps_ok
echo         instalando dependencias 1a vez, pode demorar...
python -m pip install -q -r requirements.txt
python -m playwright install chromium >nul 2>&1
:deps_ok
echo         OK - Python pronto
goto :passo4

:sem_python
echo         ERRO: Python nao encontrado no PATH.
echo         Instale o Python 3 e marque "Add to PATH" na instalacao.
pause
exit /b 1

:passo4
REM ====== PASSO 4: banco de dados =============================
echo   [4/7] Inicializando banco de dados...
python -c "from compliance_agent.database.models import init_db; init_db()" 2>nul
if errorlevel 1 goto :erro_banco
echo         OK - banco pronto
goto :passo5

:erro_banco
echo         ERRO ao inicializar o banco.
pause
exit /b 1

:passo5
REM ====== PASSO 5: Chrome modo debug =========================
echo   [5/7] Preparando Chrome (modo debug) no SIAFE2...
curl -s "http://127.0.0.1:9222/json/version" >nul 2>&1
if not errorlevel 1 goto :chrome_ja_ok
call :abrir_chrome
set /a tentativas=0
:espera_chrome
set /a tentativas+=1
ping 127.0.0.1 -n 3 >nul
curl -s "http://127.0.0.1:9222/json/version" >nul 2>&1
if not errorlevel 1 goto :chrome_subiu
if !tentativas! lss 7 goto :espera_chrome
echo         AVISO: Chrome nao subiu no modo debug.
echo         A coleta do SIAFE2 sera pulada, mas o resto roda.
echo         Telegram, DOERJ e analises continuam funcionando.
goto :passo6

:chrome_subiu
echo         OK - Chrome no ar na porta 9222
goto :passo6

:chrome_ja_ok
echo         OK - Chrome ja estava no modo debug

:passo6
REM ====== PASSO 6: coleta inicial de OBs (se nao existir) ====
echo   [6/7] Verificando dados de Ordens Bancarias...
if exist "data\sei_cache\mgsclean_obs_todas.json" goto :obs_ok
echo         Dados de OBs nao encontrados.
echo         Iniciando coleta SIAFE 2023-2026 (pode levar ~20 min)...
python _SANDBOX/coletar_obs_agora.py
if errorlevel 1 echo         AVISO: coleta de OBs falhou - o agente continua sem esses dados.
if not errorlevel 1 echo         OBs coletadas e salvas.
goto :passo7

:obs_ok
echo         OK - dados de OBs ja coletados anteriormente.

:passo7
REM ====== (passo 7 continua) dashboard web + agente continuo ==
echo   [7/7] Subindo dashboard web e o agente...

REM Sobe o painel profissional numa janela separada (PC e celular)
start "JFN Painel Web" cmd /c "python server.py --host 0.0.0.0 --port 8000"
echo         Painel: http://localhost:8000  no celular use http://IP-DO-PC:8000
echo.
echo   ============================================================
echo     AGENTE NO AR.
echo       - Monitoramento SIAFE2 a cada 15 min (7h-20h)
echo       - Relatorio completo todo dia as 08:00
echo       - Telegram ativo: fale comigo pelo celular!
echo         mande /ajuda ou pergunte: tem alerta grave hoje?
echo       - Auto-restart: se cair, reinicia sozinho em 10s
echo.
echo     NAO FECHE esta janela. Parar: feche a janela.
echo   ============================================================
echo.

REM Loop de auto-restart: se o agente cair, reinicia automaticamente.
:rodar_agente
python -m compliance_agent.scheduler --loop
echo.
echo   [%date% %time%] Agente encerrou. Reiniciando em 10s...
echo   para parar de vez, feche esta janela agora
ping 127.0.0.1 -n 11 >nul
goto :rodar_agente

REM ============================================================
REM   Sub-rotina: abrir Chrome com porta de debug no SIAFE2
REM ============================================================
:abrir_chrome
set "CHROME_EXE="
if exist "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"
if exist "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"
if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE goto :sem_chrome
echo         abrindo Chrome JFN no modo debug (perfil separado, porta 9222)...
start "" "%CHROME_EXE%" --remote-debugging-port=9222 --user-data-dir="%LOCALAPPDATA%\JFN\ChromeDebug" --no-first-run --no-default-browser-check "https://siafe2.fazenda.rj.gov.br/Siafe/"
goto :eof

:sem_chrome
echo         AVISO: Chrome nao encontrado - coleta SIAFE2 sera pulada.
goto :eof
