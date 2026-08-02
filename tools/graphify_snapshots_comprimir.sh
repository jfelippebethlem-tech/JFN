#!/usr/bin/env bash
# Comprime os snapshots datados de graphify-out/ — TUDO menos o mais recente.
#
# POR QUE EXISTE. O pre-commit roda `graphify update` a cada commit, e cada update salva um
# snapshot datado com o `graph.json` de ~27 MB EM BRUTO. Em 2026-07-30 eu comprimi o snapshot do
# dia à mão (30 MB -> 3,1 MB) e o commit seguinte criou outro de 28 MB. Limpeza sem catraca é
# limpeza que se repete — então ela vira automática aqui.
#
# REGRA DA CASA: não se apaga nada que não esteja provado íntegro em outro lugar. Cada arquivo só
# é removido depois que o sha256 do DESCOMPRIMIDO bate com o do original. Se divergir, o bruto
# fica e o .zst sai — o oposto do que a falha "tamanho>0 é verificação" já custou aqui.
#
# O snapshot MAIS RECENTE fica intacto: é o que o graphify pode querer ler para comparar.
set -uo pipefail

raiz="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
dir="$raiz/graphify-out"
[ -d "$dir" ] || exit 0
command -v zstd >/dev/null 2>&1 || exit 0

# Snapshots datados (AAAA-MM-DD), ordenados; o último é preservado.
mapfile -t snaps < <(find "$dir" -maxdepth 1 -type d -regextype posix-extended \
                       -regex '.*/[0-9]{4}-[0-9]{2}-[0-9]{2}$' -printf '%f\n' | sort)
[ "${#snaps[@]}" -le 1 ] && exit 0
unset 'snaps[${#snaps[@]}-1]'

liberado=0
for s in "${snaps[@]}"; do
  while IFS= read -r -d '' f; do
    case "$f" in *.zst) continue;; esac
    dest="${f}.zst"
    # Nome já ocupado por OUTRA geração: não sobrescrever — pode não ser o mesmo conteúdo.
    [ -e "$dest" ] && dest="${f%.*}.pos-reindex.${f##*.}.zst"
    [ -e "$dest" ] && continue
    sha=$(sha256sum "$f" | cut -d' ' -f1)
    sz=$(stat -c %s "$f")
    if ! zstd -19 -q -T2 -f "$f" -o "$dest" 2>/dev/null; then
      rm -f "$dest"; continue
    fi
    if [ "$(zstdcat "$dest" | sha256sum | cut -d' ' -f1)" = "$sha" ]; then
      rm -f "$f"; liberado=$((liberado + sz - $(stat -c %s "$dest")))
    else
      # sha divergiu: o BRUTO é a fonte de verdade e permanece.
      rm -f "$dest"
      echo "[graphify-snap] sha divergiu em $f — bruto preservado" >&2
    fi
  done < <(find "$dir/$s" -maxdepth 1 -type f -print0)
done

[ "$liberado" -gt 1048576 ] && echo "[graphify-snap] snapshots comprimidos: $((liberado / 1048576)) MB liberados"
exit 0
