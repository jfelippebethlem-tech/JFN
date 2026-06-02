@echo off
REM chrome_debug.bat
REM Abre o Chrome com a porta de debug para o JFN Compliance Agent.
REM Nao fecha o Chrome normal — usa um perfil separado (JFN\ChromeDebug)
REM que forca uma instancia nova com o remote-debugging-port ativo.

echo.
echo   JFN - Abrindo Chrome com porta de debug (perfil JFN)...
echo.

REM Tenta localizar o Chrome em varios locais comuns
set "CHROME_EXE="

if exist "%PROGRAMFILES%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME_EXE=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not defined CHROME_EXE goto :nao_achou

echo   Chrome encontrado: %CHROME_EXE%
echo   Perfil exclusivo: %LOCALAPPDATA%\JFN\ChromeDebug
echo   Abrindo com porta de debug 9222...
echo.

start "" "%CHROME_EXE%" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="%LOCALAPPDATA%\JFN\ChromeDebug" ^
    --no-first-run ^
    --no-default-browser-check ^
    "https://siafe2.fazenda.rj.gov.br/Siafe/"
goto :depois

:nao_achou
echo   ERRO: Chrome nao encontrado!
echo   Instale o Chrome ou edite este arquivo com o caminho correto.
pause
exit /b 1

:depois

echo   Chrome aberto! Aguarde carregar e faca login no SIAFE2.
echo.
echo   Proximos passos:
echo   1. Faca login no SIAFE2 que abriu no Chrome
echo   2. Va para: Execucao ^> Execucao Financeira ^> OB Orcamentaria
echo   3. Volte aqui e rode: iniciar.bat
echo.
pause
