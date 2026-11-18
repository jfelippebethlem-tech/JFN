# fila de render das cenas 3D a 30 fps (quadros ímpares 1,3,…,959), retomável; depois RIFE 2× → 60 fps
cd C:\up\v68
function log($m) { "$(Get-Date -Format HH:mm:ss) $m" | Tee-Object -Append C:\up\v68\render3d.log }
foreach ($j in @(@("galaxia",3840,2160), @("mapa",3840,2160), @("galaxia",1080,1920), @("mapa",1080,1920))) {
  $c, $w, $h = $j; $d = "C:\up\v68\r3d\${c}_${w}x${h}"; New-Item -ItemType Directory -Force $d | Out-Null
  $impares = @(Get-ChildItem "$d\*.png" -ErrorAction SilentlyContinue | Where-Object { $_.Length -gt 1000 -and ([int]$_.BaseName % 2) -eq 1 } | ForEach-Object { [int]$_.BaseName } | Sort-Object)
  $q0 = if ($impares.Count) { $impares[-1] + 2 } else { 1 }
  if ($q0 -le 959) {
    log "$c ${w}x${h} render a partir do quadro $q0 (passo 2)"
    .\blender\blender.exe -b -P v68_blender_cenas.py -- $c $w $h $d $q0 960 2 2>&1 | Select-String "CENA-MONTADA|RENDER-FIM|Error|Traceback|out of memory" | ForEach-Object { log $_.Line }
  }
  # RIFE 2× (UHD em 4K): ímpares → 960 quadros a 60 fps
  $ri = "$d`_in"; $ro = "$d`_60"
  if (-not (Test-Path "$ro\.ok")) {
    Remove-Item -Recurse -Force $ri, $ro -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force $ri, $ro | Out-Null
    # RGB 24 bits: PNG RGBA do Blender sai listrado no RIFE ncnn
    $k = 0; Get-ChildItem "$d\*.png" | Where-Object { ([int]$_.BaseName % 2) -eq 1 } | Sort-Object { [int]$_.BaseName } | ForEach-Object { $k++; ffmpeg -hide_banner -loglevel error -y -i $_.FullName -pix_fmt rgb24 ("$ri\{0:D8}.png" -f $k) }
    $u = if ($w -gt 2000) { "-u" } else { "" }
    $ErrorActionPreference = "Continue"
    & C:\up\rife\rife-ncnn-vulkan-20221029-windows\rife-ncnn-vulkan.exe -i $ri -o $ro -n ($k * 2) -m C:\up\rife\rife-ncnn-vulkan-20221029-windows\rife-v4.6 $u 2>$null | Out-Null
    $n = (Get-ChildItem "$ro\*.png").Count; log "$c ${w}x${h} RIFE: $k -> $n quadros"
    if ($n -eq $k * 2) { New-Item "$ro\.ok" | Out-Null }
  }
}
log "RENDER3D-FIM"
