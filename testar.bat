@echo off
setlocal enabledelayedexpansion
title JFN - Testes Offline
cd /d "%~dp0"

echo.
echo   Rodando a suite de testes OFFLINE do JFN...
echo   (logica interna: env, chaves, memoria, Hermes, analise de OB, DOERJ)
echo.
python tests\test_offline.py
echo.
pause
