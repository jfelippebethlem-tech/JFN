# v68 · FUNDO A 60 FPS — roda NO it-campo (RTX 5070). Gera, a partir dos masters 4K (Real-ESRGAN, v65),
# o loop sem costura de cada cena a 24 fps (mesma costura do tools/v65_fundo_videos.sh), interpola 24→60
# com RIFE v4.6 (ncnn/Vulkan) e codifica AV1/VP9/H.264 dentro do orçamento (celular ≤ 2,5 MB, desktop ≤ 5 MB).
#
# Loop e RIFE: com `-n N` o rife-ncnn-vulkan gera o quadro i no tempo t = i·K/N (K = quadros de entrada;
# medido por PSNR em 18/11). Para 2,5× exatos e a emenda do loop interpolada (último → primeiro), a entrada
# leva os 2 primeiros quadros repetidos no fim (K = L+2), N = 2,5·K, e ficam só os 2,5·L primeiros.
#
# Uso (no it-campo):  powershell -File fundo60.ps1 -Cena hero -Var d [-Rife "-u"]      (retomável por etapa)
param([string]$Cena = "hero", [string]$Var = "d", [string]$Rife = "", [string]$Tag = "")
$ErrorActionPreference = "Stop"
$RIFE = "C:\up\rife\rife-ncnn-vulkan-20221029-windows\rife-ncnn-vulkan.exe"
$SRC = @{hero = "fluxo_a"; secao1 = "fluxo_b"; secao2 = "fluxo_b"}
$T0 = @{hero = 0; secao1 = 0; secao2 = 12.6}
$T1 = @{hero = 12; secao1 = 11.2; secao2 = 20.04}
$MX = @{hero = 2250; secao1 = 2160; secao2 = 1700}
$W = "C:\up\v68\fundo\$Cena`_$Var$Tag"; $in = "$W\in"; $out = "$W\out"; $enc = "C:\up\v68\enc"
New-Item -ItemType Directory -Force $in, $out, $enc | Out-Null
function log($m) { "$(Get-Date -Format HH:mm:ss) $Cena/$Var$Tag $m" | Tee-Object -Append C:\up\v68\fundo60.log }
$inv = [Globalization.CultureInfo]::InvariantCulture
$s = $T0[$Cena]; $e = $T1[$Cena]; $a = $s + 2; $d = $e - $s - 2; $off = $d - 2
$geo = if ($Var -eq "m") { "crop=1080:2160:$($MX[$Cena]):0" } else { "scale=2560:1440:flags=lanczos" }

# 1. loop a 24 fps em PNG (quadros da costura do v65)
if (-not (Test-Path "$W\.loop")) {
  Remove-Item "$in\*" -ErrorAction SilentlyContinue
  $fc = "[0:v]split[x][y];[x]trim=$($a.ToString($inv)):$($e.ToString($inv)),setpts=PTS-STARTPTS,fps=24[A];" +
        "[y]trim=$($s.ToString($inv)):$($a.ToString($inv)),setpts=PTS-STARTPTS,fps=24[B];" +
        "[A][B]xfade=transition=fade:duration=2:offset=$($off.ToString($inv)),$geo"
  ffmpeg -hide_banner -loglevel error -y -i "C:\up\$($SRC[$Cena])_raw_4k.mp4" -filter_complex $fc -fps_mode passthrough "$in\%08d.png"
  if ($LASTEXITCODE) { throw "ffmpeg loop" }
  New-Item "$W\.loop" | Out-Null
}
$L = (Get-ChildItem "$in\*.png" | Where-Object { $_.Name -match '^\d{8}\.png$' }).Count
# repetição dos 2 primeiros no fim (só se ainda não houver)
$Lreal = [int](Get-Content "$W\.L" -ErrorAction SilentlyContinue)
if (-not $Lreal) { $Lreal = $L; Set-Content "$W\.L" $L; Copy-Item "$in\00000001.png" ("$in\{0:D8}.png" -f ($L + 1)); Copy-Item "$in\00000002.png" ("$in\{0:D8}.png" -f ($L + 2)) }
$L = $Lreal; $K = $L + 2; $N = [int]($K * 5 / 2); $keep = [int]($L * 5 / 2)
log "loop L=$L quadros (24 fps) -> $keep quadros (60 fps)"

# 2. RIFE 24 -> 60
if (-not (Test-Path "$W\.rife")) {
  Remove-Item "$out\*" -ErrorAction SilentlyContinue
  $t = Get-Date
  $ra = @("-i", $in, "-o", $out, "-n", $N, "-m", "C:\up\rife\rife-ncnn-vulkan-20221029-windows\rife-v4.6", "-j", "2:4:4") + ($Rife -split " " | Where-Object { $_ })
  $ErrorActionPreference = "Continue"; & $RIFE @ra 2>$null | Out-Null; $ErrorActionPreference = "Stop"
  Get-ChildItem "$out\*.png" | Where-Object { [int]$_.BaseName -gt $keep } | Remove-Item
  $n = (Get-ChildItem "$out\*.png").Count
  if ($n -ne $keep) { throw "RIFE gerou $n, esperado $keep" }
  New-Item "$W\.rife" | Out-Null
  log "RIFE ok em $([int]((Get-Date)-$t).TotalSeconds) s"
}
if ($Tag) { log "teste ($Tag): sem codificação"; exit 0 }

# 3. codificação com orçamento e teto de CRF (acima do teto o traço fino borra)
$base = "$enc\fluxo_$Cena$(if ($Var -eq 'm') {'_m'})"
$lim = if ($Var -eq "m") { 2500000 } else { 5000000 }
function cod($ext, $crf0, $passo, $teto, $argsf) {
  $f = "$base$ext"; if (Test-Path "$f.ok") { return }
  $crf = $crf0
  while ($true) {
    $a2 = @("-hide_banner", "-loglevel", "error", "-y", "-framerate", "60", "-i", "$out\%08d.png", "-an") + (& $argsf $crf) + @($f)
    ffmpeg @a2; if ($LASTEXITCODE) { throw "ffmpeg $ext" }
    $sz = (Get-Item $f).Length; log "$(Split-Path $f -Leaf) crf=$crf $sz B"
    if ($sz -le $lim -or $crf -ge $teto) { Set-Content "$f.ok" "crf=$crf $sz"; break }
    $crf += $passo
  }
}
cod ".av1.mp4" 32 2 40 { param($c) @("-c:v", "libsvtav1", "-preset", "4", "-crf", $c, "-g", "600", "-pix_fmt", "yuv420p", "-svtav1-params", "tune=0", "-movflags", "+faststart") }
cod ".webm" 34 3 43 { param($c) @("-c:v", "libvpx-vp9", "-b:v", "0", "-crf", $c, "-row-mt", "1", "-cpu-used", "2", "-deadline", "good", "-g", "600", "-pix_fmt", "yuv420p") }
cod ".mp4" 20 1 25 { param($c) @("-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-crf", $c, "-g", "600", "-x264-params", "aq-mode=3", "-pix_fmt", "yuv420p", "-movflags", "+faststart") }
log "FIM"
