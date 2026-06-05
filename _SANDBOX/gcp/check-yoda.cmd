@echo off
setlocal
set "CLOUDSDK_PYTHON=C:\Users\socah\google-cloud-sdk\platform\bundledpython\python.exe"
set "GC=C:\Users\socah\google-cloud-sdk\bin\gcloud.cmd"
echo === STATUS DO SERVICO YODA ===
call "%GC%" compute ssh server-1 --zone=southamerica-east1-b --tunnel-through-iap --quiet --command="systemctl status yoda --no-pager -l"
echo.
echo === ULTIMAS LINHAS DO LOG ===
call "%GC%" compute ssh server-1 --zone=southamerica-east1-b --tunnel-through-iap --quiet --command="journalctl -u yoda -n 25 --no-pager"
