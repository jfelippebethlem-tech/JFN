@echo off
REM ============================================================
REM   configurar_tudo.bat  —  CONFIGURACAO INICIAL (rodar 1 vez)
REM ============================================================
REM   - Coloca o JFN para iniciar sozinho quando o PC ligar
REM   - Abre a configuracao do Chrome Remote Desktop (acesso pelo celular)
REM
REM   Depois disso, o agente roda 24/7 e voce controla pelo celular:
REM     - Pelo Telegram (comandos)
REM     - Pelo Chrome Remote Desktop (tela do PC)
REM ============================================================
title JFN - Configuracao Inicial
cd /d "%~dp0"

echo.
echo   ============================================================
echo     JFN - CONFIGURACAO INICIAL (so precisa rodar uma vez)
echo   ============================================================
echo.

REM ---------- 1. Inicio automatico do agente ----------
echo   [1/2] Configurando inicio automatico do agente...

set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set ATALHO=%STARTUP_DIR%\JFN_Agente.lnk
set ALVO=%~dp0JFN.bat

REM Cria um atalho para JFN.bat na pasta de inicializacao
powershell -NoProfile -Command ^
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%ATALHO%');" ^
    "$s.TargetPath='%ALVO%';" ^
    "$s.WorkingDirectory='%~dp0';" ^
    "$s.WindowStyle=7;" ^
    "$s.Description='JFN Compliance Agent';" ^
    "$s.Save()"

if exist "%ATALHO%" (
    echo         OK - o agente vai iniciar sozinho quando o PC ligar
) else (
    echo         AVISO - nao consegui criar o atalho automatico
    echo         Faca manual: copie JFN.bat para a pasta que abrir com:
    echo         Win+R  ^>  shell:startup
)

echo.

REM ---------- 2. Chrome Remote Desktop ----------
echo   [2/2] Configurando acesso remoto pelo celular...
echo.
echo         Vou abrir a pagina do Chrome Remote Desktop.
echo         Siga os passos:
echo           1. Clique em "Acesso remoto" / "Configurar acesso remoto"
echo           2. Baixe e instale o que ele pedir
echo           3. De um nome ao PC (ex: PC Casa) e crie um PIN
echo           4. No celular, instale o app "Chrome Remote Desktop"
echo           5. Faca login com a MESMA conta Google
echo.
pause

start "" "https://remotedesktop.google.com/access"

echo.
echo   ============================================================
echo     CONFIGURACAO CONCLUIDA!
echo.
echo     A partir de agora:
echo       - O agente inicia sozinho quando o PC liga
echo       - Voce controla pelo Telegram (comandos /ajuda)
echo       - Voce ve a tela do PC pelo app Chrome Remote Desktop
echo.
echo     Para iniciar o agente AGORA sem reiniciar:
echo       de duplo clique em  JFN.bat
echo   ============================================================
echo.
pause
