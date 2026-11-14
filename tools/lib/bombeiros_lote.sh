# shellcheck shell=bash
# docs_novos_do_lote <arquivo .out do sweep> <byte em que o lote começou>
#   Imprime quantos processos do lote vieram COM documento (o "FIM: N com docs" escrito DEPOIS do byte dado).
#   Lote que morreu antes do FIM, ou arquivo ausente, = 0. Usado pelo bombeiros_supervisor.sh para só rodar os
#   passos de depois quando houve documento novo (13/11/2026).
docs_novos_do_lote() {
  local out="$1" desde="${2:-0}" n
  [ -f "$out" ] || { echo 0; return; }
  n=$(tail -c +"$((desde + 1))" "$out" | grep -oE 'FIM: [0-9]+ com docs' | tail -1 | grep -oE '[0-9]+')
  echo "${n:-0}"
}
