@echo off
:: Auto-start do Hermes Telegram Bot (Mestre Yoda)
:: Coloca este script no Startup do Windows

:: Reset seguro do estado do gateway antes de subir
if exist "%USERPROFILE%\.hermes\gateway_state.json" (
    del /f /q "%USERPROFILE%\.hermes\gateway_state.json"
)

:: Sobe o Hermes em background (sem travar o terminal)
start "" /b cmd /c "cd /d %USERPROFILE% && hermes gateway run"

:: Log opcional para debug
:: echo Hermes iniciado em %date% %time% >> %USERPROFILE%\hermes-start.log
