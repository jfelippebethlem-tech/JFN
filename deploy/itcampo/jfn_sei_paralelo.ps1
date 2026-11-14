# JFN - orquestrador das sessoes SEI do it-campo, em JANELA VISIVEL (pedido do dono, 14/11/2026: "nada de janelas ocultas").
# Instalado como tarefa agendada interativa (/it) no logon:
#   schtasks /create /f /tn JFN-SEI-Paralelo /sc onlogon /it /tr "powershell -NoProfile -ExecutionPolicy Bypass -NoExit -File %USERPROFILE%\jfn_sei_paralelo.ps1"
# Abre as janelas das sessoes (uma por sessao, com titulo) e o navegador de cada uma pelo WSLg.
# Pausar entre rodadas:   wsl -d Ubuntu -- touch ~/JFN-worker/data/.pause_itcampo
# Numero de sessoes:      wsl -d Ubuntu -- bash -c "echo 4 > ~/JFN-worker/data/itcampo_n"
# Desligar de vez:        schtasks /change /tn JFN-SEI-Paralelo /disable   (e fechar esta janela)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "JFN SEI orquestrador (it-campo)"
while ($true) {
  Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] JFN SEI: subindo o orquestrador no WSL Ubuntu" -ForegroundColor Cyan
  wsl.exe -d Ubuntu --cd /home/iterj/JFN-worker -- bash -lc "PYTHONPATH=. exec .venv/bin/python -u -m tools.itcampo_sei_paralelo rodar"
  Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] orquestrador saiu (codigo $LASTEXITCODE) - religo em 60 s" -ForegroundColor Yellow
  Start-Sleep -Seconds 60
}
