#!/bin/bash
# Captura DIRIGIDA dos processos grandes da AMC — v2, SEM guarda por nome de processo.
#
# POR QUE A v1 FALHOU. Ela esperava `alheios == 0`, onde "alheio" era qualquer processo com
# `sweep|recaptura|integra` no nome. Rodou QUATRO horas em duas rodadas e capturou ZERO. Medido em
# 2026-08-15 no momento exato de mais uma desistência: `data/browser.lock` NÃO EXISTIA, havia ZERO
# Chromium vivo, e o "alheio" que bloqueava era um `sei_sweep --ug 296100` com DOIS SEGUNDOS de vida.
#
# Os sweeps do cron nascem e morrem o tempo todo (`*/30`, `*/10`, `30 */2`, `20 */4`, `50 1,9,17`...).
# Esperar que NENHUM exista é esperar por algo que quase nunca acontece — enquanto o recurso que
# importa, o navegador, estava livre o tempo inteiro. E eu vinha relatando "navegador tomado" a cada
# rodada, com base numa mensagem que o próprio roteiro imprimia sem ter medido o navegador.
#
# O CONSERTO NÃO É AQUI, É NO `sei_integra_completa.py`: ele passou a abrir o Playwright dentro de
# `browser_lock_async` — o mutex que `sei_reader.ler()` e `extrair_primarios_v3` já usavam. A exclusão
# agora é sobre o RECURSO (um browser por vez, que é o que derrubou esta VM 4×), não sobre um nome.
#
# Sobra para este roteiro o que ele sabe fazer: ir aos processos, um a um, e deixar o lock arbitrar.
set -u
cd /home/ubuntu/JFN || exit 1
set -a; . .env 2>/dev/null; set +a

PROCESSOS=(
  "SEI-080002/023009/2024"   # R$ 6,59 mi
  "SEI-080002/011494/2024"   # R$ 6,40 mi
)

for p in "${PROCESSOS[@]}"; do
  slug=$(echo "$p" | sed 's|SEI-||; s|/|_|g')
  if [ -d "data/sei_arquivo/${slug}/texto" ]; then
    echo "$(date -Is) $p já arquivado — pulo"
    continue
  fi
  echo "$(date -Is) === $p : baixando íntegra (lock arbitra a vez) ==="
  # 90 MIN, NÃO 30. Medido no `000803/2025`: com `timeout 1800` a íntegra morreu em 30 minutos
  # EXATOS, com 34 dos 71 PDFs no disco, e o log dizia só "íntegra falhou" — a coincidência do
  # relógio foi o que denunciou que o assassino era o MEU teto, não o SEI.
  timeout 5400 nice -n 10 .venv/bin/python tools/sei_integra_completa.py "$p" || echo "  íntegra falhou (código $?)"
  echo "$(date -Is) === $p : arquivando ==="
  timeout 5400 nice -n 10 .venv/bin/python tools/sei_arquivar.py "${p#SEI-}" || echo "  arquivar falhou"
  n=$(ls "data/sei_arquivo/${slug}/texto" 2>/dev/null | wc -l)
  echo "$(date -Is) $p -> $n documentos no arquivo"
  if [ "$n" -gt 0 ]; then
    echo "$(date -Is) === $p : lendo ==="
    timeout 900 nice -n 10 .venv/bin/python -m tools.sei_leitura_dupla \
        --processo "${p#SEI-}" --gravar --max-chars 150000 >/dev/null 2>&1
  fi
done
echo "$(date -Is) FIM da captura dirigida da AMC (v2)"
