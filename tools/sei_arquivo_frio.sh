#!/usr/bin/env bash
# Disco da VM-1 encheu em 15/11/2026 (100%, ~22 GB de PDF de íntegra a cada 6 h vindos do it-campo).
# Uma vez por dia, para cada pasta data/sei_cache/integra_* parada há 3 h e já arquivada (sei_arquivo/<tag>):
#   1. PDF NATIVO → NNN.txt + sha256/URL em depurados.json  (tools/sei_depurar_pdfs.py; fica na VM-1)
#   2. PDF escaneado → it-campo:~/arquivo_frio/sei_cache/<pasta>/ (rsync confere e só então apaga daqui)
#   3. data/sei_arquivo_frio.jsonl registra onde cada pasta foi parar.
# Recomprimir escaneado foi MEDIDO e não compensa (11% com PyMuPDF; o Ghostscript aumentou arquivos).
# Lotes de 15/11 antes deste script: vm2:~/arquivo_frio/sei_cache (52 GB).
set -u
cd /home/ubuntu/JFN || exit 1
exec 9>data/locks/sei_arquivo_frio.lock
flock -n 9 || { echo "$(date '+%F %T') já rodando"; exit 0; }
PY=.venv/bin/python
DEST=/home/iterj/arquivo_frio/sei_cache
echo "$(date '+%F %T') início — livre: $(df -h / | awk 'NR==2{print $4}')"
nice -n 15 ionice -c3 timeout 10800 $PY -m tools.sei_depurar_pdfs --aplicar --sem-recomprimir --idade-min-h 3 2>/dev/null | tail -1
if ! timeout 30 ssh -o ConnectTimeout=15 it-campo 'wsl -d Ubuntu -e true' >/dev/null 2>&1; then
  echo "$(date '+%F %T') it-campo fora do ar — escaneados ficam na VM-1 hoje"; exit 0
fi
lista=$(mktemp)
$PY - "$lista" <<'PY'
import sys, time
from pathlib import Path
from tools.sei_depurar_pdfs import pastas_elegiveis, CACHE, ARQUIVO
Path(sys.argv[1]).write_text("".join(f"{d.name}/\n" for d in pastas_elegiveis(CACHE, 3.0, ARQUIVO)))
PY
n=$(wc -l < "$lista")
[ "$n" -eq 0 ] && { echo "nada a levar"; rm -f "$lista"; exit 0; }
nice -n 15 ionice -c3 timeout 21600 rsync -a --remove-source-files --rsync-path="wsl -d Ubuntu -e rsync" \
  --include='integra_*/' --include='integra_*/[0-9][0-9][0-9]*.pdf' --exclude='*' \
  --files-from="$lista" -r data/sei_cache/ "it-campo:$DEST/"
rc=$?
while read -r p; do
  printf '{"pasta":"%s","destino":"it-campo:%s","em":"%s","rc":%d}\n' "${p%/}" "$DEST" "$(date '+%F %T')" "$rc"
done < "$lista" >> data/sei_arquivo_frio.jsonl
rm -f "$lista"
echo "$(date '+%F %T') fim rc=$rc · $n pasta(s) · livre: $(df -h / | awk 'NR==2{print $4}')"
