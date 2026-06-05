@echo off
setlocal enabledelayedexpansion
title JFN - Checagem de Saude
cd /d "%~dp0"

REM Carrega o .env para as variaveis de ambiente
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A"=="#" set "%%A=%%B"
    )
)

echo.
echo   Rodando checagem completa do JFN...
echo   (testa Chrome, SIAFE, DOERJ, Groq, Hermes, Telegram, banco)
echo.
python checar.py
