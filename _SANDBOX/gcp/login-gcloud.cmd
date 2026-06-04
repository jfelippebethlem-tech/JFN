@echo off
rem Login do gcloud usando Python 3.12 (estavel) - corrige o bug do 3.14
set "CLOUDSDK_PYTHON=C:\Users\socah\AppData\Local\Programs\Python\Python312\python.exe"
set "GC=C:\Users\socah\google-cloud-sdk\bin\gcloud.cmd"
echo Abrindo o login do Google (escolha jfelippebethlem@gmail.com e clique Permitir)...
call "%GC%" auth login
echo.
echo === conta ativa agora: ===
call "%GC%" auth list
echo.
echo Se apareceu sua conta acima com um asterisco (*), DEU CERTO.
echo Volte aqui e me diga: loguei
pause
