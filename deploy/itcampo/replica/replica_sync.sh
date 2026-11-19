#!/bin/bash
# RÉPLICA SÓ-LEITURA dos dados da VM-1 no it-campo (WSL Ubuntu, ~/jfn-replica/data) — pedido do dono 19/11/2026
# ("rode o que precisar na vm2 e no it campo"): os jobs pesados que só LEEM o banco rodam aqui e devolvem JSON.
# Bancos SQLite pelo sqlite3_rsync (cópia CONSISTENTE de um banco vivo em WAL, só as páginas que mudaram); acervo
# SEI pelo rsync (só texto/manifesto — fotos e PDFs ficam). Chega pela entrada padrão (bash -s): nada fora do git.
set -u
main() {
  R=~/jfn-replica/data; mkdir -p "$R"
  exec 9>~/jfn-replica/.sync.lock; flock -n 9 || { echo '{"ev":"sync_ocupado"}'; return 0; }
  local t0=$(date +%s) rc=0 inicio
  for db in compliance.db receita_estab.db; do
    inicio=$(date +%s)
    nice -n 10 ~/bin/sqlite3_rsync "vm1-ts:/home/ubuntu/JFN/data/$db" "$R/$db" \
        --exe /home/ubuntu/JFN/tools/replica/sqlite3_rsync_origem.sh || rc=1
    echo "{\"ev\":\"db\",\"db\":\"$db\",\"rc\":$rc,\"s\":$(( $(date +%s)-inicio )),\"bytes\":$(stat -c %s "$R/$db" 2>/dev/null || echo 0)}"
  done
  inicio=$(date +%s)
  # acervo SEI: texto + manifestos (os detectores nunca abrem foto nem PDF)
  nice -n 10 rsync -a --delete --rsync-path="nice -n 15 ionice -c3 rsync" \
      --exclude='fotos/' --exclude='*.pdf' --exclude='*.jpg' --exclude='*.jpeg' --exclude='*.png' \
      vm1-ts:JFN/data/sei_arquivo/ "$R/sei_arquivo/" || rc=1
  nice -n 10 rsync -a --delete --rsync-path="nice -n 15 ionice -c3 rsync" --include='*/' \
      --include='manifest.json' --include='*.txt' --include='*.json' --exclude='*' --prune-empty-dirs \
      vm1-ts:JFN/data/sei_cache/ "$R/sei_cache/" || rc=1
  nice -n 10 rsync -a --rsync-path="nice -n 15 ionice -c3 rsync" vm1-ts:JFN/data/pericia_agentes "$R/" || rc=1
  # caches dos detectores (PNCP/NE): semeados da VM-1 só se ainda não existem aqui (a réplica os mantém depois)
  nice -n 10 rsync -a --ignore-existing --rsync-path="nice -n 15 ionice -c3 rsync" --include='_cache*' --exclude='*' \
      vm1-ts:JFN/data/padroes/ "$R/padroes/" || rc=1
  echo "{\"ev\":\"acervo\",\"rc\":$rc,\"s\":$(( $(date +%s)-inicio ))}"
  printf '{"t":"%s","rc":%d,"s":%d}\n' "$(date '+%F %T')" "$rc" "$(( $(date +%s)-t0 ))" > ~/jfn-replica/ultimo_sync.json
  echo "{\"ev\":\"sync_fim\",\"rc\":$rc,\"s\":$(( $(date +%s)-t0 ))}"
  return $rc
}
main "$@" < /dev/null
