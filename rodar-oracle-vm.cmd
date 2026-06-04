@echo off
title Oracle VM Creator - JFN (tentando ate conseguir)
rem Roda o criador de VM Oracle em PRIMEIRO PLANO (visivel), saida ao vivo.
rem Fica tentando a cada 60s ate a Oracle ter vaga. Ctrl+C para parar.
cd /d "C:\JFN\jfn"
set "PYTHONIOENCODING=utf-8"
echo ============================================================
echo   Criador de VM Oracle - JFN
echo   Fica tentando ate a Oracle ter vaga (Out of host capacity).
echo   NAO feche esta janela. Ctrl+C para parar.
echo ============================================================
python -u criar_vm.py
echo.
echo (O script terminou. Se nao criou, rode de novo.)
pause
