<#
  hermes.ps1 — Lancador do Hermes via PowerShell (acesso total ao computador).

  Faz o mesmo que o HERMES.bat, mas em PowerShell: abre o Chrome no modo debug
  9222, sobe o painel web + chat do Hermes e roda o agente completo (7 loops).
  Use quando quiser que o Hermes opere com os privilegios do seu usuario.

  Como rodar (clique direito > Executar com PowerShell, ou):
      powershell -ExecutionPolicy Bypass -File hermes.ps1
#>

$ErrorActionPreference = "Continue"
Set-Location -Path $PSScriptRoot

function Write-Step($n, $msg) { Write-Host "  [$n] $msg" -ForegroundColor Cyan }

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Magenta
Write-Host "    HERMES — AUDITOR AUTONOMO (PowerShell)" -ForegroundColor Magenta
Write-Host "  ============================================================" -ForegroundColor Magenta
Write-Host ""

# 1. Credenciais (.env / .env.txt) -> variaveis de ambiente do processo
Write-Step "1/6" "Carregando credenciais (.env / .env.txt)..."
$envFile = $null
if (Test-Path ".env")     { $envFile = ".env" }
elseif (Test-Path ".env.txt") { $envFile = ".env.txt" }
if ($envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $k, $v = $line.Split("=", 2)
            [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
        }
    }
    Write-Host "        OK - credenciais de $envFile" -ForegroundColor Green
} else {
    Write-Host "        AVISO: .env/.env.txt nao encontrado." -ForegroundColor Yellow
}

# 2. Python + dependencias
Write-Step "2/6" "Verificando Python e dependencias..."
python --version > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "        ERRO: Python nao encontrado no PATH." -ForegroundColor Red
    Read-Host "Pressione ENTER para sair"; exit 1
}
python -m pip show playwright > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "        instalando dependencias (1a vez)..." -ForegroundColor Yellow
    python -m pip install -q -r requirements.txt
    python -m playwright install chromium > $null 2>&1
}
Write-Host "        OK - Python pronto" -ForegroundColor Green

# 3. Banco
Write-Step "3/6" "Inicializando banco de dados..."
python -c "from compliance_agent.database.models import init_db; init_db()" 2>$null
Write-Host "        OK - banco pronto" -ForegroundColor Green

# 4. Chrome debug 9222
Write-Step "4/6" "Abrindo Chrome no modo debug (porta 9222)..."
$chromeUp = $false
try { (Invoke-WebRequest "http://127.0.0.1:9222/json/version" -TimeoutSec 3 -UseBasicParsing) | Out-Null; $chromeUp = $true } catch {}
if (-not $chromeUp) {
    $paths = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
    )
    $chrome = $paths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($chrome) {
        $perfil = "$env:LOCALAPPDATA\Google\Chrome\User Data"
        Start-Process $chrome -ArgumentList "--remote-debugging-port=9222","--user-data-dir=`"$perfil`"","https://siafe2.fazenda.rj.gov.br/Siafe/"
        for ($i=0; $i -lt 7; $i++) {
            Start-Sleep -Seconds 2
            try { (Invoke-WebRequest "http://127.0.0.1:9222/json/version" -TimeoutSec 3 -UseBasicParsing) | Out-Null; $chromeUp = $true; break } catch {}
        }
    }
}
if ($chromeUp) { Write-Host "        OK - Chrome no ar (9222)" -ForegroundColor Green }
else { Write-Host "        AVISO: Chrome nao subiu — o Hermes tentara abrir sozinho." -ForegroundColor Yellow }

# 5. Painel web + chat do Hermes
Write-Step "5/6" "Subindo painel web e abrindo o chat do Hermes..."
Start-Process -WindowStyle Minimized powershell -ArgumentList "-NoExit","-Command","python server.py --host 0.0.0.0 --port 8000"
Start-Sleep -Seconds 4
Start-Process "http://localhost:8000/hermes"
Write-Host "        Chat do Hermes: http://localhost:8000/hermes" -ForegroundColor Green

# 6. Agente completo (7 loops, com auto-restart)
Write-Step "6/6" "Iniciando o agente completo (Hermes + missao + monitor)..."
Write-Host ""
Write-Host "  HERMES NO AR. Defina a missao no chat e ele trabalha sozinho." -ForegroundColor Magenta
Write-Host "  Feche esta janela para parar." -ForegroundColor DarkGray
Write-Host ""
while ($true) {
    python -m compliance_agent.scheduler --loop
    Write-Host "  Agente encerrou. Reiniciando em 10s..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}
