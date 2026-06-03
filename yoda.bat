@echo off
setlocal EnableDelayedExpansion
:: ============================================================
::  yoda.bat — Lancador self-heal do Mestre Yoda (sem Docker)
::
::  Roda a partir da PROPRIA pasta onde este arquivo esta (C:\JFN\jfn),
::  entao "No module named mestre_yoda" nao acontece.
::
::  Self-heal: se o bot cair, reinicia sozinho apos 5s. Equivale ao
::  restart:unless-stopped do Docker, mas em modo Python puro.
::
::  Uso:  duplo-clique, ou no terminal:  cd C:\JFN\jfn  &&  yoda.bat
:: ============================================================

:: Vai para a pasta deste .bat (raiz do repo JFN), aconteca o que acontecer.
cd /d "%~dp0"

echo ============================================================
echo  MESTRE YODA - lancador self-heal (Python puro, sem Docker)
echo  Pasta: %CD%
echo ============================================================

:: 1) O pacote precisa existir aqui. Se nao, a branch errada esta no checkout.
if not exist "mestre_yoda\__main__.py" (
    echo.
    echo ERRO: pasta mestre_yoda nao encontrada em %CD%
    echo.
    echo O codigo do bot vive na branch claude/yoda-hermes-improvements-YlYXb,
    echo NAO no main. Rode antes:
    echo.
    echo     git fetch origin
    echo     git checkout claude/yoda-hermes-improvements-YlYXb
    echo     git pull
    echo.
    pause
    goto :fim
)

:: 2) .env precisa existir com algum provedor de modelo.
if not exist ".env" (
    echo.
    echo AVISO: .env nao encontrado. Criando a partir do exemplo OpenRouter...
    if exist ".env.openrouter.example" (
        copy ".env.openrouter.example" ".env" >nul
        echo Edite .env e preencha TELEGRAM_BOT_TOKEN e OPENROUTER_API_KEY.
        notepad ".env"
        echo Pressione uma tecla apos salvar...
        pause >nul
    ) else (
        echo ERRO: .env.openrouter.example tambem nao existe. Branch errada?
        pause
        goto :fim
    )
)

:: 3) Dependencias (rapido se ja instaladas).
echo.
echo [setup] Garantindo dependencias...
python -m pip install -q -r requirements.txt

:: 4) Loop de self-heal: roda; se cair, espera 5s e sobe de novo.
echo.
echo [run] Iniciando o Mestre Yoda. Feche esta janela para parar de vez.
echo.
:loop
python -m mestre_yoda
echo.
echo [self-heal] Bot encerrou (codigo %errorlevel%). Reiniciando em 5s...
echo            (Ctrl+C agora para cancelar o reinicio.)
timeout /t 5 /nobreak >nul
goto :loop

:fim
endlocal
