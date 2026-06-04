# bot-control.ps1 - Controle SEGURO do gateway/bot Telegram do Hermes
# Uso: powershell -ExecutionPolicy Bypass -File bot-control.ps1 [start|stop|restart|status]
#
# PROTOCOLO DE SEGURANCA:
#  - So considera "gateway" um python.exe/pythonw.exe cuja linha de comando
#    contem 'gateway run' OU 'cli.py --gateway'.
#  - NUNCA mata hermes.exe (sessao interativa), Claude, ou python que nao seja
#    o gateway. Identifica por ASSINATURA, nao por nome.

param([string]$Action = "status")

$ErrorActionPreference = "SilentlyContinue"
$H       = "C:\Users\socah\AppData\Local\hermes"
$LOCK    = Join-Path $H "gateway.lock"
$PIDFILE = Join-Path $H "gateway.pid"
$VBS     = Join-Path $H "gateway-service\run-hidden.vbs"
$LOG     = Join-Path $H "logs\gateway.log"

function Get-GatewayProcs {
    Get-CimInstance Win32_Process | Where-Object {
        $_.Name -in @('python.exe','pythonw.exe') -and
        ($_.CommandLine -like '*gateway run*' -or $_.CommandLine -like '*cli.py --gateway*')
    }
}

function Stop-Gateway {
    $procs = Get-GatewayProcs
    if (-not $procs) { Write-Host "Nenhum gateway rodando." }
    foreach ($p in $procs) {
        Write-Host ("Encerrando gateway PID " + $p.ProcessId)
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 2
    Remove-Item $LOCK -Force -ErrorAction SilentlyContinue
    Remove-Item $PIDFILE -Force -ErrorAction SilentlyContinue
    $left = Get-GatewayProcs
    if ($left) { Write-Host ("AINDA VIVO: " + ($left.ProcessId -join ',')) }
    else { Write-Host "Gateway parado e lock limpo." }
}

function Start-Gateway {
    if (Get-GatewayProcs) { Stop-Gateway }
    Remove-Item $LOCK -Force -ErrorAction SilentlyContinue
    Write-Host "Subindo o bot (oculto, sem janela)..."
    Start-Process wscript.exe -ArgumentList ('"' + $VBS + '"')
    $deadline = (Get-Date).AddSeconds(240)
    $connected = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 15
        $alive = (Get-GatewayProcs | Measure-Object).Count
        $tail = Get-Content $LOG -Tail 25 -ErrorAction SilentlyContinue
        if ($alive -ge 1 -and ($tail -match 'Gateway running with' -or $tail -match 'telegram connected')) {
            $connected = $true; break
        }
        Write-Host ("  ...subindo (procs=" + $alive + ")")
    }
    if ($connected) { Write-Host "BOT NO AR e conectado ao Telegram. OK" }
    else { Write-Host "Subiu mas ainda nao confirmou Telegram. Ver logs/gateway.log" }
}

function Get-Status {
    $procs = Get-GatewayProcs
    if ($procs) { Write-Host ("Gateway VIVO: " + ($procs.ProcessId -join ',')) }
    else { Write-Host "Gateway: PARADO" }
    if (Test-Path $LOCK) { Write-Host ("Lock: " + (Get-Content $LOCK -Raw)) } else { Write-Host "Lock: (vazio)" }
    $tail = Get-Content $LOG -Tail 40 -ErrorAction SilentlyContinue
    $conn = ($tail | Select-String 'telegram connected|Gateway running with' | Select-Object -Last 1)
    if ($conn) { Write-Host ("Ultima conexao: " + $conn) }
}

$a = $Action.ToLower()
if ($a -eq "start") { Start-Gateway }
elseif ($a -eq "stop") { Stop-Gateway }
elseif ($a -eq "restart") { Stop-Gateway; Start-Sleep 2; Start-Gateway }
else { Get-Status }
