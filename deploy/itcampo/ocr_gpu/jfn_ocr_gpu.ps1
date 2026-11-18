# JFN - OCR por IA na GPU (Surya 2.5) dos PDFs escaneados do SEI, em JANELA VISIVEL.
# Pausar:   wsl -d Ubuntu -- touch ~/jfn-gpu/ocr/PAUSA      Desligar: schtasks /change /tn JFN-OCR-GPU /disable
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "JFN OCR por IA na GPU (it-campo)"
while ($true) {
  Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] JFN OCR GPU: subindo" -ForegroundColor Cyan
  wsl.exe -d Ubuntu -- bash /mnt/c/Users/iterj/ocr_gpu.sh
  Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] saiu (codigo $LASTEXITCODE) - religo em 120 s" -ForegroundColor Yellow
  Start-Sleep -Seconds 120
}
