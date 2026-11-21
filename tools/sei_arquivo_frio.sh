#!/usr/bin/env bash
# Disco da VM-1 encheu em 15/11/2026 (100%, ~22 GB de PDF de íntegra a cada 6 h vindos do it-campo).
# De hora em hora (15/11: 4 GB/h de PDF), para cada pasta data/sei_cache/integra_* parada há 2 h e já arquivada (sei_arquivo/<tag>):
#   1. PDF NATIVO → NNN.txt + sha256/URL em depurados.json  (tools/sei_depurar_pdfs.py; fica na VM-1)
#   2. PDF escaneado → VM-2 ~/arquivo_frio/sei_pdfs/<pasta>/ (rsync confere e só então apaga daqui)
#      16/11/2026: dono "não vamos mais usar o it campo nem sua memória nem nada dele" — destino era o it-campo
#      (C:\JFN-Arquivo, o que já foi para lá continua lá; índice em data/sei_arquivo_frio.jsonl).
#   3. data/sei_arquivo_frio.jsonl registra onde cada pasta foi parar.
# Recomprimir escaneado foi MEDIDO e não compensa (11% com PyMuPDF; o Ghostscript aumentou arquivos).
# Lotes de 15/11 antes deste script: vm2:~/arquivo_frio/sei_cache (52 GB).
set -u
cd /home/ubuntu/JFN || exit 1
exec 9>data/locks/sei_arquivo_frio.lock
flock -n 9 || { echo "$(date '+%F %T') já rodando"; exit 0; }
PY=.venv/bin/python
NO=vm2-ts
FRIO=/home/ubuntu/arquivo_frio
DEST=$FRIO/sei_pdfs
LIVRE_MIN_GB=20                    # a VM-2 também captura: abaixo disso o frio espera (nada sai da VM-1)
echo "$(date '+%F %T') início — livre: $(df -h / | awk 'NR==2{print $4}')"
nice -n 15 ionice -c3 timeout 10800 $PY -m tools.sei_depurar_pdfs --aplicar --sem-recomprimir --idade-min-h 2 2>/dev/null | tail -1
livre_no=$(timeout 30 ssh -o ConnectTimeout=15 "$NO" "df -BG --output=avail / | tail -1 | tr -dc 0-9" 2>/dev/null)
if [ -z "$livre_no" ]; then
  echo "$(date '+%F %T') $NO fora do ar — escaneados ficam na VM-1 hoje"; exit 0
fi
if [ "$livre_no" -lt "$LIVRE_MIN_GB" ]; then
  echo "$(date '+%F %T') $NO com só ${livre_no} GB livres (< $LIVRE_MIN_GB) — escaneados ficam na VM-1 hoje"; exit 0
fi
lista=$(mktemp)
# 21/11/2026: a checagem de espaço era SÓ no início — uma rodada levou 23 GB e encheu a VM-2 (86% → 98%).
# Agora a lista cabe no orçamento: (livre na VM-2 − LIVRE_MIN_GB); o que não cabe fica para a próxima hora.
$PY - "$lista" "$(( (livre_no - LIVRE_MIN_GB) * 1000000000 ))" <<'PY'
import sys, time
from pathlib import Path
from tools.sei_depurar_pdfs import pastas_elegiveis, CACHE, ARQUIVO
orcamento, usado, out = int(sys.argv[2]), 0, []
for d in pastas_elegiveis(CACHE, 2.0, ARQUIVO):
    tam = sum(f.stat().st_size for f in d.glob("[0-9][0-9][0-9]*.pdf") if f.is_file())
    if usado + tam > orcamento:
        continue
    usado += tam
    out.append(f"{d.name}/\n")
Path(sys.argv[1]).write_text("".join(out))
print(f"orçamento {orcamento/1e9:.1f} GB · {len(out)} pasta(s) · {usado/1e9:.1f} GB", file=sys.stderr)
PY
n=$(wc -l < "$lista")
rc=0
nice -n 15 ionice -c3 timeout 21600 rsync -a --remove-source-files \
  --include='integra_*/' --include='integra_*/[0-9][0-9][0-9]*.pdf' --exclude='*' \
  --files-from="$lista" -r data/sei_cache/ "$NO:$DEST/"
rc=$?
while read -r p; do
  printf '{"pasta":"%s","destino":"%s:%s","em":"%s","rc":%d}\n' "${p%/}" "$NO" "$DEST" "$(date '+%F %T')" "$rc"
done < "$lista" >> data/sei_arquivo_frio.jsonl
rm -f "$lista"
# 15/11 14h: quarentena e versões substituídas da conferência da VM-2 (10,6 GB, só crescem; nenhum cron as lê —
# rever_quarentena é manual). Paradas há mais de 6 h vão inteiras para a VM-2 (reversível: rsync de volta).
for par in "data/vm2_quarentena:vm2_quarentena" "data/vm2_entrega/_substituidos:vm2_substituidos" \
           "data/sei_arquivo/_substituido:sei_arquivo_substituido"; do   # capturas antigas, fora dos detectores
  src=${par%%:*}; dst=$FRIO/${par##*:}
  velhos=$(mktemp)
  find "$src" -mindepth 1 -maxdepth 1 -type d -mmin +360 -printf '%f/\n' > "$velhos" 2>/dev/null
  if [ -s "$velhos" ]; then
    nice -n 15 ionice -c3 timeout 10800 rsync -a --remove-source-files \
      --files-from="$velhos" -r "$src/" "$NO:$dst/"
    r2=$?
    while read -r p; do
      printf '{"pasta":"%s/%s","destino":"%s:%s","em":"%s","rc":%d}\n' "$src" "${p%/}" "$NO" "$dst" "$(date '+%F %T')" "$r2"
      [ "$r2" -eq 0 ] && find "$src/${p%/}" -depth -type d -empty -delete
    done < "$velhos" >> data/sei_arquivo_frio.jsonl
    echo "$(date '+%F %T') $src: $(wc -l < "$velhos") pasta(s) → $NO rc=$r2"
  fi
  rm -f "$velhos"
done
echo "$(date '+%F %T') fim rc=$rc · $n pasta(s) · livre: $(df -h / | awk 'NR==2{print $4}')"
