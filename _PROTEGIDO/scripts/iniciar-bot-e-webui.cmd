@echo off
rem ============================================================
rem  Sobe JUNTOS, em JANELAS VISIVEIS e com AUTO-RETRY:
rem    (1) Yoda  = Bot do Telegram  (janela "Yoda - Bot Telegram")
rem    (2) Painel = Web UI http://127.0.0.1:8787 (janela "Hermes Web UI")
rem  Cada um se reinicia sozinho se cair. Mesmas IAs/APIs (~/.hermes), 8 Gemini em rodizio.
rem ============================================================

echo Abrindo o Yoda (Bot Telegram)...
start "Yoda - Bot Telegram" "C:\Users\socah\hermes-webui\run-yoda.cmd"

timeout /t 5 >nul

echo Abrindo o Painel (Web UI)...
start "Hermes Web UI" "C:\Users\socah\hermes-webui\run-webui.cmd"

echo.
echo Pronto! Duas janelas: Yoda (bot) e o Painel (http://127.0.0.1:8787).
echo Para PARAR tudo, basta fechar as duas janelas.
