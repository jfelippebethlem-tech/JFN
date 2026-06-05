@echo off
:: Self-heal do Telegram Bot (Mestre Yoda)
:: Se cair, reseta e reinicia o gateway

tasklist /fi "imagename eq hermes.exe" | find /i "hermes.exe" >nul
if %errorlevel% neq 0 (
    echo [%date% %time%] Mestre Yoda caiu. Reiniciando... >> %USERPROFILE%\telegram-self-heal.log
    del /f /q "%USERPROFILE%\.hermes\gateway_state.json"
    start "" /b cmd /c "cd /d %USERPROFILE% && hermes gateway run"
) else (
    echo [%date% %time%] Mestre Yoda online. >> %USERPROFILE%\telegram-self-heal.log
)
