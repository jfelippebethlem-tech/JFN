#!/bin/bash
# v65 — pôsteres nítidos do fundo de fitas = 1º quadro do próprio loop (intermediário de
# `tools/v65_fundo_videos.sh`, em /tmp/v65enc). Assim a troca pôster → vídeo não "pula" de composição.
# AVIF (avifenc, q 40 — indistinguível da fonte em recorte 100 % e 1/3 do peso do q 70, que custava ~1 s de LCP simulado) + WebP (q 75) — o WebP é o fallback do `image-set` no CSS.
set -eu
OUT=static/assets/v65; TMP=/tmp/v65enc
for c in ${1:-hero secao1 secao2}; do for v in d m; do
  b=$OUT/fluxo_$c$([ $v = m ] && echo _m || true)
  ffmpeg -hide_banner -loglevel error -y -i $TMP/${c}_$v.mp4 -frames:v 1 $TMP/p_${c}_$v.png
  avifenc -q 40 -s 4 -j 2 --min 0 --max 63 $TMP/p_${c}_$v.png $b.avif >/dev/null
  cwebp -quiet -q 75 -m 6 $TMP/p_${c}_$v.png -o $b.webp
  echo "$b  avif=$(stat -c %s $b.avif)  webp=$(stat -c %s $b.webp)"
done; done
