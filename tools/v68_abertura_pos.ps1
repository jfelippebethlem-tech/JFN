# v68 · pós-produção da abertura LTX (roda no it-campo): recorte dos quadros estáveis → Real-ESRGAN x4plus
# (704 → 2816) → 1080×1080 → RIFE v4.6 24→60 → AV1/VP9/H.264 ≤ 1,5 MB + pôster (1º quadro).
param([string]$Nome = "ini_22", [int]$Q = 65)
$ErrorActionPreference = "Continue"
$B = "C:\up\v68\ab"; $f = "$B\f"; $u = "$B\u"; $s = "$B\s"; $r = "$B\r"; $E = "C:\up\v68\enc_ab"
Remove-Item -Recurse -Force $B -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force $f, $u, $s, $r, $E | Out-Null
function log($m) { "$(Get-Date -Format HH:mm:ss) $m" | Tee-Object -Append C:\up\v68\abertura_pos.log }
ffmpeg -hide_banner -loglevel error -y -i "C:\up\v68\ltx\$Nome.mp4" -frames:v $Q -pix_fmt rgb24 "$f\%08d.png"
& C:\up\re\realesrgan-ncnn-vulkan.exe -i $f -o $u -n realesrgan-x4plus -m C:\up\re\models -f png -j 2:2:2 2>$null | Out-Null
log "ESRGAN $((Get-ChildItem $u).Count) quadros"
Get-ChildItem "$u\*.png" | ForEach-Object { ffmpeg -hide_banner -loglevel error -y -i $_.FullName -vf "scale=1080:1080:flags=lanczos" -pix_fmt rgb24 "$s\$($_.Name)" }
# 24 → 60: t = i·K/N; N = 2,5·K, mantém os 2,5·(K−1)+1 primeiros (o último quadro não extrapola)
$K = (Get-ChildItem "$s\*.png").Count; $N = [int]($K * 5 / 2); $keep = [int](($K - 1) * 5 / 2) + 1
& C:\up\rife\rife-ncnn-vulkan-20221029-windows\rife-ncnn-vulkan.exe -i $s -o $r -n $N -m C:\up\rife\rife-ncnn-vulkan-20221029-windows\rife-v4.6 2>$null | Out-Null
Get-ChildItem "$r\*.png" | Where-Object { [int]$_.BaseName -gt $keep } | Remove-Item
log "RIFE $K -> $((Get-ChildItem "$r\*.png").Count) quadros a 60 fps"
$FF = @("-hide_banner", "-loglevel", "error", "-y", "-framerate", "60", "-i", "$r\%08d.png", "-an")
function cod($ext, $crf, $passo, $teto, $af) {
  while ($true) { $o = "$E\abertura$ext"; $a = $FF + (& $af $crf) + @($o); ffmpeg @a
    $sz = (Get-Item $o).Length; log "abertura$ext crf=$crf $sz B"; if ($sz -le 1500000 -or $crf -ge $teto) { break }; $crf += $passo } }
cod ".av1.mp4" 30 2 40 { param($c) @("-c:v", "libsvtav1", "-preset", "4", "-crf", $c, "-pix_fmt", "yuv420p", "-svtav1-params", "tune=0", "-movflags", "+faststart") }
cod ".webm" 32 3 42 { param($c) @("-c:v", "libvpx-vp9", "-b:v", "0", "-crf", $c, "-row-mt", "1", "-cpu-used", "2", "-deadline", "good", "-pix_fmt", "yuv420p") }
cod ".mp4" 20 1 28 { param($c) @("-c:v", "libx264", "-profile:v", "high", "-preset", "veryslow", "-crf", $c, "-pix_fmt", "yuv420p", "-movflags", "+faststart") }
ffmpeg -hide_banner -loglevel error -y -i "$r\00000001.png" -quality 85 "$E\abertura.webp"
log "ABERTURA-POS-FIM"
