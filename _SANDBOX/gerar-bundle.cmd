@echo off
rem Gera o arquivo unico hermes-tudo.sh (com .env + config.yaml + auth.json dentro).
rem Salva em C:\Users\socah\hermes-tudo.sh (FORA do repo).
set "PY=C:\Users\socah\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"
"%PY%" "%~dp0gerar-bundle-vm.py"
echo.
echo Pronto. O arquivo unico esta em: C:\Users\socah\hermes-tudo.sh
pause
