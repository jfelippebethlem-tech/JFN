#!/bin/bash
# v65 NITIDEZ — fundo de fitas a partir dos masters 4K ampliados por IA (Real-ESRGAN x4plus, it-campo).
#
#   _SANDBOX/v65_ref/fluxo_a_raw_4k.mp4  → hero            (loop 2–12 s + crossfade 2 s com 0–2 s = 10 s;
#            os 18 s do v63 não cabiam no orçamento em H.264 sem subir o CRF até o borrão — medido: CRF 24 = 4,9 MB)
#   _SANDBOX/v65_ref/fluxo_b_raw_4k.mp4  → secao1 (0–11,2) e secao2 (12,6–20) — mesma costura, cada um
#
# Variantes (uma decodificação do 4K por cena; intermediário quase sem perda em /tmp):
#   desktop  2560×1440 (16:9 inteiro)
#   celular  1080×2160 (recorte 1:2 NATIVO da região das fitas — sem redução: num 390×844@3x o vídeo é
#            esticado 1,17×; o 1170×1560 do brief seria esticado 1,62× e jogaria fora 38 % dos pixels nas laterais)
# Codecs: AV1 (SVT preset 8, CRF 32 — o SVT 1.7 desta VM ARM não tem NEON: preset 6 levou 17 min num vídeo de 10 s) · VP9 (fallback) · H.264 High CRF 20 -preset slow. Orçamento: celular ≤ 2 MB,
# desktop ≤ 4 MB por vídeo — se estourar, o script sobe o CRF até caber, COM TETO (H.264 24, AV1 38, VP9 40):
# acima disso o traço fino das fitas borra, que é o defeito que o v65 corrige. Teto atingido = registra no log.
#
# Uso:  nice -n 15 tools/v65_fundo_videos.sh   (pesado: ~1 h na vm1; 1 encode por vez)
set -u
REF=_SANDBOX/v65_ref; OUT=static/assets/v65; TMP=/tmp/v65enc
mkdir -p "$OUT" "$TMP"
log(){ echo "$(date +%H:%M:%S) $*"; }
FF="ffmpeg -hide_banner -loglevel error -y"

# cena → arquivo-fonte, início, fim, x do recorte do celular (no 4K)
declare -A SRC=([hero]=fluxo_a [secao1]=fluxo_b [secao2]=fluxo_b)
declare -A T0=([hero]=0 [secao1]=0 [secao2]=12.6)
declare -A T1=([hero]=12 [secao1]=11.2 [secao2]=20.04)
declare -A MX=([hero]=2250 [secao1]=2160 [secao2]=1700)

intermediario(){  # $1 = cena
  local c=$1 s=${T0[$1]} e=${T1[$1]}
  local a=$(echo "$s + 2" | bc) d=$(echo "$e - $s - 2" | bc)          # A = (s+2 … e), B = (s … s+2)
  local off=$(echo "$d - 2" | bc)
  [ -s $TMP/${c}_d.mp4 ] && [ -s $TMP/${c}_m.mp4 ] && return
  log "intermediário $c (loop ${d}s)"
  $FF -threads 2 -i $REF/${SRC[$c]}_raw_4k.mp4 -filter_complex "
    [0:v]split[x][y];
    [x]trim=$a:$e,setpts=PTS-STARTPTS,fps=24[A];
    [y]trim=$s:$a,setpts=PTS-STARTPTS,fps=24[B];
    [A][B]xfade=transition=fade:duration=2:offset=$off,format=yuv420p,split[l1][l2];
    [l1]scale=2560:1440:flags=lanczos[d];
    [l2]crop=1080:2160:${MX[$c]}:0[m]" \
    -map '[d]' -c:v libx264 -preset veryfast -crf 6 -threads 2 $TMP/${c}_d.mp4 \
    -map '[m]' -c:v libx264 -preset veryfast -crf 6 -threads 2 $TMP/${c}_m.mp4
}

tam(){ stat -c %s "$1"; }

codificar(){  # $1 = cena, $2 = d|m
  local c=$1 v=$2 base=$OUT/fluxo_$1$([ $2 = m ] && echo _m) lim
  [ $v = m ] && lim=2000000 || lim=4000000
  local in=$TMP/${c}_${v}.mp4 crf
  # retomável: um arquivo já pronto (registrado no .feito) é pulado
  pronto(){ grep -qx "$1" $TMP/.feito 2>/dev/null; }
  feito(){ echo "$1" >> $TMP/.feito; }
  # H.264 High
  crf=20
  pronto $base.mp4 || while :; do
    $FF -i $in -an -c:v libx264 -profile:v high -preset slow -crf $crf -g 240 -x264-params aq-mode=3 -pix_fmt yuv420p -movflags +faststart -threads 2 $base.mp4
    log "$base.mp4 crf=$crf $(tam $base.mp4) B"; [ $(tam $base.mp4) -le $lim ] || [ $crf -ge 24 ] && { feito $base.mp4; break; }; crf=$((crf+1))
  done
  # AV1
  crf=32
  pronto $base.av1.mp4 || while :; do
    $FF -i $in -an -c:v libsvtav1 -preset 8 -crf $crf -g 240 -pix_fmt yuv420p -svtav1-params tune=0:lp=2 -movflags +faststart $TMP/av1.mp4 && mv $TMP/av1.mp4 $base.av1.mp4
    log "$base.av1.mp4 crf=$crf $(tam $base.av1.mp4) B"; [ $(tam $base.av1.mp4) -le $lim ] || [ $crf -ge 38 ] && { feito $base.av1.mp4; break; }; crf=$((crf+2))
  done
  # VP9
  crf=34
  pronto $base.webm || while :; do
    $FF -i $in -an -c:v libvpx-vp9 -b:v 0 -crf $crf -row-mt 1 -cpu-used 4 -deadline good -threads 2 -pix_fmt yuv420p $base.webm
    log "$base.webm crf=$crf $(tam $base.webm) B"; [ $(tam $base.webm) -le $lim ] || [ $crf -ge 40 ] && { feito $base.webm; break; }; crf=$((crf+3))
  done
}

ALVO=${1:-hero secao1 secao2}
for c in $ALVO; do intermediario $c; done
for c in $ALVO; do for v in m d; do codificar $c $v; done; done
log FIM
