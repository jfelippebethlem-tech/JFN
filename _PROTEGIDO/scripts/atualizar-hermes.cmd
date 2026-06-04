@echo off
rem ============================================================
rem  ATUALIZADOR SEGURO DO HERMES (substitui o 'hermes update' bugado)
rem  Para o bot -> atualiza codigo -> reinstala deps -> religa o bot.
rem  NAO usa 'hermes update' (que falha no stash e quebra o venv).
rem ============================================================
setlocal
set "AGENT=C:\Users\socah\AppData\Local\hermes\hermes-agent"
set "UV=C:\Users\socah\.local\bin\uv.exe"

echo [1/4] Parando o bot (Yoda)...
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\socah\AppData\Local\hermes\gateway-service\bot-control.ps1" stop

echo [2/4] Atualizando o codigo (git pull)...
cd /d "%AGENT%"
git pull --ff-only

echo [3/4] Reinstalando dependencias (uv)...
"%UV%" pip install --python "%AGENT%\venv\Scripts\python.exe" -e ".[messaging]"

echo [4/4] Religando o bot (Yoda)...
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\socah\AppData\Local\hermes\gateway-service\bot-control.ps1" start

echo.
echo === Atualizacao concluida. ===
endlocal
