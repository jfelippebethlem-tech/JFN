#!/bin/bash
# Captura DIRIGIDA dos 4 processos grandes da AMC — decisão do dono em 2026-08-14.
#
# POR QUE NÃO PELA FILA DO SWEEP. Três corridas de `sei_sweep --cnpj` começaram pelo MESMO processo
# já arquivado (`080002/017399/2024`), gastando 682 s, 802 s e 989 s — tempo CRESCENTE — e nunca
# chegaram aos quatro que interessam. A causa está na ordenação que o próprio sweep declara:
# "legível > lacuna provada > sinal > fornecedor antes de folha > valor". Processo JÁ LEGÍVEL vem
# primeiro, o que serve à leitura e é o inverso do que se quer numa CAPTURA.
#
# Este roteiro não mexe na fila nem na regra de frescor (que é pedido do dono): vai direto aos
# quatro, um a um, pelo caminho `integra_completa -> arquivar -> ler`.
#
# O QUE ESTÁ EM JOGO: ~R$ 25,9 mi pagos à AMC em processos sem um único documento capturado.
set -u
cd /home/ubuntu/JFN || exit 1
set -a; . .env 2>/dev/null; set +a

PROCESSOS=(
  "SEI-080002/000803/2025"   # R$ 6,64 mi
  "SEI-080002/023009/2024"   # R$ 6,59 mi
  "SEI-080002/011494/2024"   # R$ 6,40 mi
  "SEI-080002/008950/2024"   # R$ 6,28 mi
)

# ESPERAR O NAVEGADOR, NUNCA DISPUTAR. `ps -C python` não enxerga shells, então este script não casa
# consigo mesmo — a armadilha do `pgrep -f` que já mordeu esta casa.
espera_navegador() {
  local fim=$(( $(date +%s) + 3600 ))
  while [ "$(date +%s)" -lt "$fim" ]; do
    local alheios carga
    alheios=$(ps -C python -o args= 2>/dev/null | grep -E 'sweep|recaptura|integra' | grep -vc leitura_dupla)
    carga=$(awk '{printf "%d", $1}' /proc/loadavg)
    [ "$alheios" -eq 0 ] && [ "$carga" -lt 4 ] && return 0
    sleep 20
  done
  return 1
}

for p in "${PROCESSOS[@]}"; do
  slug=$(echo "$p" | sed 's|SEI-||; s|/|_|g')
  if [ -d "data/sei_arquivo/${slug}/texto" ]; then
    echo "$(date -Is) $p já arquivado — pulo"
    continue
  fi
  if ! espera_navegador; then
    echo "$(date -Is) desisti de $p — navegador ocupado por 1 h"
    continue
  fi
  echo "$(date -Is) === $p : baixando íntegra ==="
  timeout 1800 nice -n 10 .venv/bin/python tools/sei_integra_completa.py "$p" || echo "  íntegra falhou"
  echo "$(date -Is) === $p : arquivando ==="
  timeout 900 nice -n 10 .venv/bin/python tools/sei_arquivar.py "$p" || echo "  arquivar falhou"
  n=$(ls "data/sei_arquivo/${slug}/texto" 2>/dev/null | wc -l)
  echo "$(date -Is) $p -> $n documentos no arquivo"
  if [ "$n" -gt 0 ]; then
    echo "$(date -Is) === $p : lendo ==="
    timeout 900 nice -n 10 .venv/bin/python -m tools.sei_leitura_dupla \
        --processo "${p#SEI-}" --gravar --max-chars 150000 >/dev/null 2>&1
  fi
done
echo "$(date -Is) FIM da captura dirigida da AMC"
