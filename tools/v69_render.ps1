# v69 · fila de render da abertura (roda no it-campo): 192 quadros NATIVOS a 60 fps (sem interpolar), PNG 16 bits,
# quadrado 2160×2160 e vertical 1080×1920. Retomável: recomeça do 1º quadro que falta.
param([string]$Var = "ambos")
cd C:\up\v69
function log($m) { "$(Get-Date -Format HH:mm:ss) $m" | Tee-Object -Append C:\up\v69\render.log }
$jobs = @(@("q", 2160, 2160), @("v", 1080, 1920)) | Where-Object { $Var -eq "ambos" -or $_[0] -eq $Var }
foreach ($j in $jobs) {
  $n, $w, $h = $j; $d = "C:\up\v69\r\${n}_${w}x${h}"; New-Item -ItemType Directory -Force $d | Out-Null
  $tem = @(Get-ChildItem "$d\*.png" -ErrorAction SilentlyContinue | Where-Object { $_.Length -gt 10000 } | ForEach-Object { [int]$_.BaseName })
  $q0 = 1; while ($tem -contains $q0) { $q0++ }
  if ($q0 -le 192) {
    log "$n ${w}x${h} render a partir do quadro $q0"
    .\..\v68\blender\blender.exe -b --factory-startup -P v69_abertura_blender.py -- $w $h $d $q0 192 2>&1 | Select-String "CENA-MONTADA|RENDER-FIM|Error|Traceback|out of memory" | ForEach-Object { log $_.Line }
  }
  $c = (Get-ChildItem "$d\*.png").Count; log "$n ${w}x${h}: $c quadros"
}
log "RENDER-V69-FIM"
