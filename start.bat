@echo off
chcp 65001 >nul
title PolitiMonitor

echo.
echo  ╔═══════════════════════════════════╗
echo  ║   🏛️   PolitiMonitor  v0.1.0      ║
echo  ║   Sistema de Gestão do Gabinete   ║
echo  ╚═══════════════════════════════════╝
echo.

cd /d C:\jfn\polimonitor

:: ── 1. Verificar Node.js ──────────────────────────────────────────────────────
echo [1/5] Verificando Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo    ERRO: Node.js nao encontrado!
    echo    Instale em: https://nodejs.org
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version') do echo    OK - Node.js %%v

:: ── 2. Verificar .env ─────────────────────────────────────────────────────────
echo.
echo [2/5] Verificando configuracao...
if not exist ".env" (
    if exist ".env.example" (
        echo    Criando .env a partir de .env.example...
        copy .env.example .env >nul
        echo    ATENCAO: Edite o arquivo C:\jfn\polimonitor\.env com suas chaves!
        echo    Abrindo para edicao...
        notepad .env
    ) else (
        echo    ERRO: .env.example nao encontrado!
        pause
        exit /b 1
    )
) else (
    echo    OK - .env encontrado
)

:: ── 3. Instalar dependências ──────────────────────────────────────────────────
echo.
echo [3/5] Instalando dependencias (aguarde)...
if not exist "node_modules" (
    npm install --silent
    if errorlevel 1 (
        echo    ERRO ao instalar dependencias!
        pause
        exit /b 1
    )
    echo    OK - Dependencias instaladas
) else (
    echo    OK - Dependencias ja instaladas
)

:: ── 4. Banco de dados ─────────────────────────────────────────────────────────
echo.
echo [4/5] Configurando banco de dados...
npx prisma db push --skip-generate >nul 2>&1
if errorlevel 1 (
    echo    ERRO ao configurar banco de dados!
    pause
    exit /b 1
)
echo    OK - Banco de dados pronto

:: ── 5. Rodar testes ───────────────────────────────────────────────────────────
echo.
echo [5/5] Rodando testes...
npm test
if errorlevel 1 (
    echo.
    echo    Alguns testes falharam.
    set /p continuar="    Continuar mesmo assim? (s/N): "
    if /i not "%continuar%"=="s" exit /b 1
)

:: ── Iniciar App + Hermes ──────────────────────────────────────────────────────
echo.
echo ══════════════════════════════════════════
echo   Iniciando PolitiMonitor + Hermes Agent
echo   Acesse: http://localhost:3000
echo   Pressione Ctrl+C para parar tudo
echo ══════════════════════════════════════════
echo.

npm run launch
