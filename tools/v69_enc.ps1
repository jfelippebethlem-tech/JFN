# v69 · codificação da abertura (roda no it-campo, depois de v69_render.ps1). A partir dos PNG 16 bits a 60 fps:
#   web desktop   abertura.{av1.mp4,webm,mp4}     1920×1920 (palco quadrado, object-fit:cover)   ≤ 3,0 MB
#   web celular   abertura_m.*                    1080×1920                                      ≤ 1,5 MB
#   curta         abertura_c.* / abertura_c_m.*   quadros 121–192 (ignição + abertura, 1,2 s)     ≤ 1,0 / 0,6 MB
#   pôsteres      .webp do 1º quadro de cada uma
#   entrega       abertura_2160_60.mp4, abertura_vertical_60.mp4 (+ _curta) — H.264 High CRF 14, sem texto
# Cor: PNG sRGB → YUV BT.709 (tags explícitas) — o branco final tem de sair #FFFFFF para casar com o painel.
$ErrorActionPreference = "Continue"
$R = "C:\up\v69\r"; $E = "C:\up\v69\enc"; New-Item -ItemType Directory -Force $E | Out-Null
function log($m) { "$(Get-Date -Format HH:mm:ss) $m" | Tee-Object -Append C:\up\v69\enc.log }
$FF = @("-hide_banner", "-loglevel", "error", "-y", "-framerate", "60")
$COR = @("-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv")
function filtro($w, $h) { "scale=${w}:${h}:flags=lanczos+accurate_rnd+full_chroma_int:out_color_matrix=bt709:out_range=tv,format=yuv420p" }
$FONTE = @{q = "$R\q_2160x2160\%04d.png"; v = "$R\v_1080x1920\%04d.png"}
$JOBS = @(
  @("abertura",     "q", 1,   1920, 1920, 3000000),
  @("abertura_m",   "v", 1,   1080, 1920, 1500000),
  @("abertura_c",   "q", 121, 1920, 1920, 1000000),
  @("abertura_c_m", "v", 121, 1080, 1920, 600000))
function cod($nome, $src, $ini, $w, $h, $lim) {
  $base = "$E\$nome"
  $ent = @("-start_number", $ini, "-i", $FONTE[$src])
  $tabela = @(
    @(".av1.mp4", 30, 2, 46, { param($c) @("-c:v", "libsvtav1", "-preset", "4", "-crf", $c, "-g", "240", "-svtav1-params", "tune=0", "-movflags", "+faststart") }),
    @(".webm", 30, 3, 48, { param($c) @("-c:v", "libvpx-vp9", "-b:v", "0", "-crf", $c, "-row-mt", "1", "-cpu-used", "2", "-deadline", "good", "-g", "240") }),
    @(".mp4", 20, 1, 30, { param($c) @("-c:v", "libx264", "-profile:v", "high", "-preset", "veryslow", "-crf", $c, "-g", "240", "-movflags", "+faststart") }))
  foreach ($t in $tabela) {
    $ext, $crf, $passo, $teto, $af = $t; $f = "$base$ext"
    if (Test-Path "$f.ok") { continue }
    while ($true) {
      $a = $FF + $ent + @("-vf", (filtro $w $h), "-an") + (& $af $crf) + $COR + @($f); ffmpeg @a
      $sz = (Get-Item $f).Length; log "$nome$ext crf=$crf $sz B"
      if ($sz -le $lim -or $crf -ge $teto) { Set-Content "$f.ok" "crf=$crf $sz"; break }
      $crf += $passo
    }
  }
  $p = "{0}\{1:D4}.png" -f (Split-Path $FONTE[$src]), $ini
  ffmpeg -hide_banner -loglevel error -y -i $p -vf "scale=${w}:${h}:flags=lanczos" -quality 90 "$base.webp"
}
foreach ($j in $JOBS) { cod @j }
# entrega (redes): masters H.264 High CRF 14, 60 fps nativos
foreach ($m in @(@("abertura_2160_60", "q", 1, 2160, 2160), @("abertura_vertical_60", "v", 1, 1080, 1920),
                 @("abertura_curta_2160_60", "q", 121, 2160, 2160), @("abertura_curta_vertical_60", "v", 121, 1080, 1920))) {
  $n, $s, $i, $w, $h = $m; $f = "$E\$n.mp4"
  if (-not (Test-Path $f)) {
    $a = $FF + @("-start_number", $i, "-i", $FONTE[$s], "-vf", (filtro $w $h), "-c:v", "libx264", "-profile:v", "high", "-preset", "slow", "-crf", "14") + $COR + @("-movflags", "+faststart", $f)
    ffmpeg @a; log "entrega $n $((Get-Item $f).Length) B"
  }
}
log "ENC-V69-FIM"
