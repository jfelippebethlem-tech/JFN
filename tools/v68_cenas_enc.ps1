# v68 · codificação das cenas 3D (roda no it-campo, depois de render3d.ps1): a partir dos quadros a 60 fps,
#   entrega (redes)  <cena>_4k60.mp4 (3840×2160) e <cena>_vertical60.mp4 (1080×1920) — H.264 High CRF 16;
#   web desktop      <cena>3d.{av1.mp4,webm,mp4} mapa 1920×1080 ≤ 5 MB · galáxia 1600×900 ≤ 8 MB;
#   web celular      <cena>3d_m.*  mapa 1080×1080 (recorte 1:1 do vertical) ≤ 2,5 MB · galáxia 720×1280 ≤ 4 MB;
#   pôsteres         .webp (galáxia: 1º quadro; mapa: último, o mapa inteiro aceso).
param([string]$Cena = "galaxia")
# orçamento/escala por cena: a galáxia (milhares de fios finos em movimento) não cabe em 5 MB a 1080p60 sem borrar
# os fios (medido: AV1 CRF 44 = 7,0 MB e já mushy) — sobe para 1600×900 ≤ 9 MB com teto de CRF 38
# (overlay 1×/dia). O H.264 — reserva de Safari sem AV1/VP9 — da galáxia vai a 30 fps (h264fps) para não passar de ~9 MB.
$CFG = @{galaxia = @{d = "scale=1600:900:flags=lanczos"; ld = 9000000; m = "scale=720:1280:flags=lanczos"; lm = 4500000; tav1 = 38; h264fps = ",fps=30"};
         mapa    = @{d = "scale=1920:1080:flags=lanczos"; ld = 5000000; m = "crop=1080:1080:0:460"; lm = 2500000; tav1 = 40; h264fps = ""}}[$Cena]
$ErrorActionPreference = "Continue"
$R = "C:\up\v68\r3d"; $E = "C:\up\v68\enc3d"; New-Item -ItemType Directory -Force $E | Out-Null
function log($m) { "$(Get-Date -Format HH:mm:ss) $m" | Tee-Object -Append C:\up\v68\enc3d.log }
$H = "$R\${Cena}_3840x2160_60\%08d.png"; $V = "$R\${Cena}_1080x1920_60\%08d.png"
$FF = @("-hide_banner", "-loglevel", "error", "-y", "-framerate", "60")
$temH = Test-Path "$R\${Cena}_3840x2160_60\.ok"; $temV = Test-Path "$R\${Cena}_1080x1920_60\.ok"   # retomável por parte
if ($temH -and -not (Test-Path "$E\${Cena}_4k60.mp4")) {
  ffmpeg @FF -i $H -c:v libx264 -profile:v high -preset slow -crf 16 -pix_fmt yuv420p -movflags +faststart "$E\${Cena}_4k60.mp4"
  log "$Cena entrega 4K: $((Get-Item "$E\${Cena}_4k60.mp4").Length) B"
}
if ($temV -and -not (Test-Path "$E\${Cena}_vertical60.mp4")) {
  ffmpeg @FF -i $V -c:v libx264 -profile:v high -preset slow -crf 16 -pix_fmt yuv420p -movflags +faststart "$E\${Cena}_vertical60.mp4"
  log "$Cena entrega vertical: $((Get-Item "$E\${Cena}_vertical60.mp4").Length) B"
}
function cod($in, $vf, $base, $lim) {
  $tabela = @(
    @(".av1.mp4", 30, 2, $CFG.tav1, { param($c) @("-c:v", "libsvtav1", "-preset", "4", "-crf", $c, "-g", "240", "-pix_fmt", "yuv420p", "-svtav1-params", "tune=0", "-movflags", "+faststart") }),
    @(".webm", 33, 3, ($CFG.tav1 + 3), { param($c) @("-c:v", "libvpx-vp9", "-b:v", "0", "-crf", $c, "-row-mt", "1", "-cpu-used", "2", "-deadline", "good", "-g", "240", "-pix_fmt", "yuv420p") }),
    @(".mp4", 22, 1, 28, { param($c) @("-c:v", "libx264", "-profile:v", "high", "-preset", "veryslow", "-crf", $c, "-g", "240", "-pix_fmt", "yuv420p", "-movflags", "+faststart") }))
  foreach ($t in $tabela) {
    $ext, $crf, $passo, $teto, $af = $t; $f = "$base$ext"
    if (Test-Path "$f.ok") { continue }
    while ($true) {
      $vf2 = if ($ext -eq ".mp4") { $vf + $CFG.h264fps } else { $vf }
      $a = $FF + @("-i", $in, "-vf", $vf2, "-an") + (& $af $crf) + @($f); ffmpeg @a
      $sz = (Get-Item $f).Length; log "$(Split-Path $f -Leaf) crf=$crf $sz B"
      if ($sz -le $lim -or $crf -ge $teto) { Set-Content "$f.ok" "crf=$crf $sz"; break }
      $crf += $passo
    }
  }
}
$pq = if ($Cena -eq "mapa") { "00000960.png" } else { "00000001.png" }
$vm = $CFG.m
if ($temH) {
  cod $H $CFG.d "$E\${Cena}3d" $CFG.ld
  ffmpeg -hide_banner -loglevel error -y -i "$R\${Cena}_3840x2160_60\$pq" -vf $CFG.d -quality 82 "$E\${Cena}3d.webp"
}
if ($temV) {
  cod $V $vm "$E\${Cena}3d_m" $CFG.lm
  ffmpeg -hide_banner -loglevel error -y -i "$R\${Cena}_1080x1920_60\$pq" -vf $vm -quality 82 "$E\${Cena}3d_m.webp"
}
log "$Cena ENC-FIM"
