# JFN - pool NATIVO do Windows (OCR de reserva em CPU, fora do WSL), em JANELA VISIVEL (minimizada).
# Pausar: criar C:\JFN-Nativo\PAUSA      Desligar: schtasks /change /tn JFN-Nativo /disable
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "JFN pool nativo do Windows (it-campo)"
while ($true) {
  Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] JFN pool nativo: subindo" -ForegroundColor Cyan
  & C:\JFN-Nativo\venv\Scripts\python.exe -u C:\JFN-Nativo\pool_nativo.py
  Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] saiu (codigo $LASTEXITCODE) - religo em 120 s" -ForegroundColor Yellow
  Start-Sleep -Seconds 120
}
