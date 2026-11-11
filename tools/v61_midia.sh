#!/usr/bin/env bash
# v61_midia — mídia do painel v61 «TRON CLARO» (static/assets/v61/).
#
#   tools/v61_midia.sh conferir     (padrão) ffprobe de cada peça + alvo de tamanho + emenda dos loops
#   tools/v61_midia.sh codificar    recodifica a partir dos brutos em static/assets/v61/src/ (fora do git)
#
# As peças entregues em 2026-11-11 JÁ vieram prontas (geradas no Higgsfield, emendadas com crossfade
# de 0,8 s e comprimidas): o modo `conferir` é o que roda. `codificar` fica para a próxima leva de
# brutos — mesmos parâmetros do brief, um ffmpeg por vez, sempre com `nice -n 10` (VM de 2 vCPU).
set -euo pipefail
cd "$(dirname "$0")/.."
D=static/assets/v61
LOOPS="reator sala fluxo estado prefeitura transversal"
modo="${1:-conferir}"

kb() { echo $(( ($(stat -c %s "$1") + 1023) / 1024 )); }

conferir() {
  local falhas=0
  printf '%-22s %-6s %-9s %7s %6s %8s  %s\n' arquivo codec dimensão dur_s áudio KB alvo
  for n in abertura $LOOPS; do
    for suf in "" "-m"; do
      for ext in webm mp4; do
        f="$D/$n$suf.$ext"
        [ -f "$f" ] || { echo "FALTA $f"; falhas=$((falhas+1)); continue; }
        codec=$(ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$f")
        dim=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$f")
        dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")
        aud=$(ffprobe -v error -select_streams a -show_entries stream=codec_name -of csv=p=0 "$f" | head -1)
        k=$(kb "$f")
        if [ "$n" = abertura ]; then teto=3584; elif [ -n "$suf" ]; then teto=922; else teto=1843; fi
        quer=$([ -n "$suf" ] && echo 854x480 || echo 1280x720)
        ok=ok
        [ "$k" -le "$teto" ] || { ok="ACIMA(${teto}KB)"; falhas=$((falhas+1)); }
        [ "$dim" = "$quer" ] || { ok="$ok DIM≠$quer"; falhas=$((falhas+1)); }
        [ -z "$aud" ] || { ok="$ok TEM-ÁUDIO"; falhas=$((falhas+1)); }
        printf '%-22s %-6s %-9s %7.2f %6s %8s  %s\n' "$n$suf.$ext" "$codec" "$dim" "$dur" "${aud:-não}" "$k" "$ok"
      done
    done
  done
  echo
  echo "pôsteres (webp):"
  for n in $LOOPS; do
    for suf in "" "-sm"; do
      f="$D/$n$suf.webp"
      [ -f "$f" ] || { echo "FALTA $f"; falhas=$((falhas+1)); continue; }
      printf '  %-22s %-9s %5s KB\n' "$n$suf.webp" \
        "$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$f")" "$(kb "$f")"
    done
  done
  echo
  echo "emenda dos loops (1º quadro × último; PSNR em dB — acima de ~30 não há salto visível):"
  for n in $LOOPS; do
    f="$D/$n.mp4"; t=$(mktemp -d)
    nice -n 10 ffmpeg -v error -y -i "$f" -frames:v 1 "$t/a.png"
    nice -n 10 ffmpeg -v error -y -sseof -0.1 -i "$f" -update 1 "$t/z.png"
    p=$(nice -n 10 ffmpeg -v info -i "$t/a.png" -i "$t/z.png" -lavfi psnr -f null - 2>&1 | grep -o 'average:[0-9.a-z]*' | cut -d: -f2)
    printf '  %-14s PSNR %s dB\n' "$n" "${p:-?}"
    rm -rf "$t"
  done
  echo
  echo "total da pasta: $(du -sh "$D" | cut -f1) · falhas: $falhas"
  return $(( falhas > 0 ))
}

codificar() {
  local S="$D/src"
  [ -d "$S" ] || { echo "sem brutos em $S — nada a codificar"; exit 1; }
  for src in "$S"/*.mp4; do
    n=$(basename "$src" .mp4)
    for par in "1280:720:" "854:480:-m"; do
      IFS=: read -r w h suf <<<"$par"
      nice -n 10 ffmpeg -v error -y -i "$src" -an -vf "scale=$w:$h" -c:v libvpx-vp9 -crf 36 -b:v 0 -row-mt 1 \
        -deadline good -cpu-used 4 "$D/$n$suf.webm"
      nice -n 10 ffmpeg -v error -y -i "$src" -an -vf "scale=$w:$h" -c:v libx264 -crf 26 -preset veryfast \
        -movflags +faststart -pix_fmt yuv420p "$D/$n$suf.mp4"
    done
    if [ -f "$S/$n.png" ]; then
      nice -n 10 ffmpeg -v error -y -i "$S/$n.png" -vf scale=1600:-2 -quality 80 "$D/$n.webp"
      nice -n 10 ffmpeg -v error -y -i "$S/$n.png" -vf scale=800:-2 -quality 78 "$D/$n-sm.webp"
    fi
    echo "ok $n"
  done
  conferir
}

case "$modo" in
  conferir) conferir ;;
  codificar) codificar ;;
  *) echo "uso: $0 [conferir|codificar]"; exit 2 ;;
esac
