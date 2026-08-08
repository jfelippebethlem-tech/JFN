#!/usr/bin/env bash
# colher_vm2 — traz para a VM-1 o que a VM-2 capturou, e arquiva.
#
# O QUE ESTAVA ACONTECENDO, medido em 2026-08-07: a VM-2 roda o sweep SEI da fatia 1/2 a cada 30
# minutos, consome 34 MINUTOS DE CPU por rodada e tinha 267 processos feitos, 111 com documentos —
# e **nada disso chegava à VM-1**, onde mora toda a análise. Duas máquinas capturando, uma
# analisando, e nenhuma ponte entre elas: o trabalho da segunda ficava parado no disco dela.
#
# Dos 111 com documentos, **61 a VM-1 nunca tinha visto** (as fatias são disjuntas de propósito).
# A primeira colheita trouxe **65 processos e 15.228.502 caracteres**.
#
# NÃO MEXE NA VM-2: só lê o cache dela por rsync. O arquivamento acontece aqui, com
# `sei_arquivar_do_cache`, que é idempotente e nunca sobrescreve captura boa.
#
# Uso:  tools/colher_vm2.sh
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
PY="$REPO/.venv/bin/python"
DEST="$REPO/data/sei_cache_vm2"
LOG="$REPO/data/colher_vm2.log"
say(){ echo "[$(date '+%F %T')] [colher_vm2] $*" | tee -a "$LOG"; }

# Guarda de carga: a VM-1 tem 2 vCPU e já caiu quatro vezes.
carga=$(awk '{print int($1)}' /proc/loadavg)
if [ "$carga" -ge 4 ]; then say "load $carga — adiado"; exit 0; fi

if ! timeout 60 ssh -o ConnectTimeout=20 -o BatchMode=yes vm2 true 2>/dev/null; then
  say "VM-2 inalcançável agora — nada a fazer (o cron repete)"; exit 0
fi

mkdir -p "$DEST"
say "trazendo o cache da VM-2…"
if ! timeout 900 rsync -az --timeout=120 vm2:~/JFN/data/sei_cache/ "$DEST/" >> "$LOG" 2>&1; then
  say "rsync falhou (rc=$?) — o cron repete"; exit 0
fi
n=$(ls "$DEST"/cdp_*.json 2>/dev/null | wc -l)
say "cache da VM-2: $n arquivos"

# O arquivamento roda com a CACHE APONTADA para a pasta da VM-2 — o cache local não é tocado.
say "arquivando o que ainda não existe aqui…"
PYTHONPATH="$REPO" timeout 900 "$PY" - <<'PYEOF' >> "$LOG" 2>&1
import sys
from pathlib import Path

import tools.sei_arquivar_do_cache as M

M.CACHE = Path("data/sei_cache_vm2")
sys.argv = ["colher_vm2", "--aplicar"]
M.main()
PYEOF
# A ÁRVORE VEM JUNTO, e não é detalhe de sincronização: `sei_arvore.n_docs` é quantos documentos o
# processo TEM, e o arquivo diz quantos foram LIDOS. Sem o primeiro número, "16 lidos" é
# indistinguível de "processo de 16 lido inteiro" — família 22 do catálogo. Medido: dos 63 trazidos
# na primeira colheita, 44 não tinham árvore aqui; com ela, ZERO se revelou parcial.
say "trazendo as árvores que faltam…"
PYTHONPATH="$REPO" timeout 600 "$PY" -m tools.colher_vm2_arvore --aplicar >> "$LOG" 2>&1
# O GRAFO TAMBÉM ATRAVESSA. A VM-2 percorre a fatia 1/2 dos credores do SIAFE; sem esta colheita o
# trabalho fica parado no disco dela — o mesmo defeito que custou dias no sweep SEI. O `id` de
# `pessoas` é local e NÃO é copiado: cada ponta é resolvida por documento (ou nome, quando não há
# documento) e a aresta entra por `salvar_grafo`, que já aplica a direção canônica e a dedução.
say "trazendo o grafo de vínculos da VM-2…"
PYTHONPATH="$REPO" timeout 900 "$PY" -m tools.colher_vm2_grafo --aplicar >> "$LOG" 2>&1
# ── A FILA DE RECAPTURA ATRAVESSA NO SENTIDO CONTRÁRIO ────────────────────────────────────────
# Tudo acima TRAZ da VM-2. Este passo LEVA — e é a única escrita que este script faz lá, com a
# razão declarada: o dono pediu que a segunda máquina dividisse a carga, e sem isto ela não tem
# como. A fila de recaptura nasce do acervo LOCAL de cada máquina, e os acervos mal se tocam:
# medido em 2026-08-07, a VM-1 tem 1.515 processos pendentes, a VM-2 tem 96, e só 45 são os
# mesmos. Sem a fila atravessar, a fatia (`JFN_SWEEP_FATIA`) apenas faria cada uma trabalhar
# menos. Com ela, as duas dividem a MESMA união e a vazão dobra — 2 processos a cada 3 horas
# viram 4, sobre uma fila que hoje leva meses.
#
# A recaptura não precisa do arquivo local: precisa do NÚMERO, e lê tudo do SEI. São 156 KB de
# JSON. Falha aqui não derruba a colheita — o cron repete.
say "levando a fila de recaptura para a VM-2 (para ela dividir a carga)…"
PYTHONPATH="$REPO" timeout 300 "$PY" -c \
  "from tools.sweep_recaptura_integral import exportar_compartilhada as e; print(e())" \
  >> "$LOG" 2>&1 \
  && timeout 180 rsync -az --timeout=60 "$REPO/data/fila_recaptura_compartilhada.json" \
       vm2:~/JFN/data/ >> "$LOG" 2>&1 \
  && say "fila exportada e entregue" || say "não consegui entregar a fila (segue o baile)"

say "fim (rc=$?) — arquivo local: $(ls "$REPO/data/sei_arquivo" | wc -l) processos"
