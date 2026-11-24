# Remote Control do it-campo sempre no ar (dono, 24/11/2026: controlar tudo pelo celular, sem barrar).
# --permission-mode bypassPermissions: sem isso as sessões criadas pelo app ligam o modo "auto" e o classificador barra.
Set-Location C:\Users\iterj\JFN-rc
while ($true) {
  "y`ny`n" | & claude.cmd remote-control --name itcampo-windows --permission-mode bypassPermissions --spawn same-dir
  Add-Content C:\Users\iterj\JFN-rc\rc.log ("{0} remote-control saiu; reinicio em 15 s" -f (Get-Date -Format s))
  Start-Sleep -Seconds 15
}
