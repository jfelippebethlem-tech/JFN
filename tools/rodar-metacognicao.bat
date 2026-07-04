@echo off
title HERMES - metacognicao (ciclo diario: RAG + reflexao + backup)
cd /d C:\JFN\jfn
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo ============================================================
echo   HERMES metacognicao (it-campo) - ciclo diario
echo   1.higiene 2.reflexao(sem dado=pula) 3.auto-melhoria
echo   4.RAG rebuild-se-mudou 5.backup memoria -^> vault
echo ============================================================
echo.
".venv\Scripts\python.exe" tools\hermes_metacognicao.py run
echo.
echo (ciclo concluido)
pause
