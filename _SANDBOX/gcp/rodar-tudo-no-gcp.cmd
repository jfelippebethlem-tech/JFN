@echo off
setlocal enableextensions

rem ====== caminhos ======
set "CLOUDSDK_PYTHON=C:\Users\socah\google-cloud-sdk\platform\bundledpython\python.exe"
set "GC=C:\Users\socah\google-cloud-sdk\bin\gcloud.cmd"
set "HERMESHOME=C:\Users\socah\AppData\Local\hermes"
set "STAGE=%TEMP%\hermes-config"
set "ZONE=southamerica-east1-b"
set "VM=server-1"

echo ============================================================
echo   YODA NO GCP - instala e sobe o bot no servidor.
echo   So precisa do SEU login Google UMA vez (abre o navegador).
echo ============================================================
echo.

echo [1/7] Login Google (escolha jfelippebethlem@gmail.com e clique Permitir)...
call "%GC%" auth login
if errorlevel 1 ( echo ERRO no login. & pause & exit /b 1 )

echo.
echo [2/7] Definindo projeto jfn-vps...
call "%GC%" config set project jfn-vps

echo.
echo [3/7] Liberando SSH via tunel seguro (IAP)...
call "%GC%" services enable iap.googleapis.com compute.googleapis.com
call "%GC%" compute firewall-rules create allow-iap-ssh --direction=INGRESS --action=allow --rules=tcp:22 --source-ranges=35.235.240.0/20 2>nul

echo.
echo [4/7] Preparando config (so as chaves do bot, sem segredos do SEI/Oracle)...
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%"
> "%STAGE%\.env" (
  findstr /B /C:"TELEGRAM_BOT_TOKEN=" "%HERMESHOME%\.env"
  findstr /B /C:"TELEGRAM_ALLOWED_USERS=" "%HERMESHOME%\.env"
  findstr /B /C:"GEMINI_API_KEY=" "%HERMESHOME%\.env"
  findstr /B /C:"OPENROUTER_API_KEY=" "%HERMESHOME%\.env"
  findstr /B /C:"MISTRAL_API_KEY=" "%HERMESHOME%\.env"
  findstr /B /C:"HF_TOKEN=" "%HERMESHOME%\.env"
)
copy /y "%HERMESHOME%\config.yaml" "%STAGE%\config.yaml" >nul 2>nul
copy /y "%HERMESHOME%\auth.json"   "%STAGE%\auth.json"   >nul 2>nul
copy /y "%~dp0bootstrap-vm.sh"     "%STAGE%\bootstrap-vm.sh" >nul

echo.
echo [5/7] Parando o bot LOCAL (pra nao conflitar com o do servidor)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%HERMESHOME%\gateway-service\bot-control.ps1" stop 2>nul

echo.
echo [6/7] Enviando config para a VM (tunel IAP)...
call "%GC%" compute scp --recurse --zone=%ZONE% --tunnel-through-iap --quiet "%STAGE%" %VM%:~/hermes-config
if errorlevel 1 ( echo ERRO ao enviar arquivos. Veja a mensagem acima. & pause & exit /b 1 )

echo.
echo [7/7] Instalando e subindo o Yoda na VM (pode levar 3-6 min)...
call "%GC%" compute ssh %VM% --zone=%ZONE% --tunnel-through-iap --quiet --command="sed -i 's/\r$//' ~/hermes-config/bootstrap-vm.sh ; bash ~/hermes-config/bootstrap-vm.sh"

echo.
echo ============================================================
echo   PRONTO! O Yoda deve estar rodando no servidor GCP.
echo   Teste mandando uma mensagem pro bot no Telegram.
echo ============================================================
pause
