#!/bin/bash
# Os 25 detectores de `compliance_agent/padroes/` (tools.padroes_varrer) rodando NO it-campo sobre a réplica só-leitura
# (~/jfn-replica/data, ver replica_sync.sh), em paralelo e com prioridade baixa; o JSON de cada detector volta para
# data/padroes/ da VM-1 com md5 conferido nas duas pontas. Código = commit atual do ~/JFN-worker (o orquestrador do
# SEI faz `git pull` dele a cada 10 min), num worktree próprio. Uso: bash -s -- <paralelo> [ids...] (entrada padrão).
set -u
main() {
  local N=${1:-4}; shift || true
  B=~/JFN-worker; C=~/jfn-replica/codigo; R=~/jfn-replica/data
  exec 8>~/jfn-replica/.padroes.lock; flock -n 8 || { echo '{"ev":"padroes_ocupado"}'; return 0; }
  local head; head=$(git -C "$B" rev-parse HEAD)
  [ -e "$C/.git" ] || git -C "$B" worktree add -q --detach "$C" "$head" || return 1
  git -C "$C" checkout -q --detach "$head" || return 1
  [ -e "$C/.venv" ] || ln -s "$B/.venv" "$C/.venv"
  mkdir -p "$R/padroes"
  for x in compliance.db receita_estab.db sei_arquivo sei_cache pericia_agentes padroes; do
    [ -L "$C/data/$x" ] || { [ -e "$C/data/$x" ] && mv "$C/data/$x" "$C/data/$x.local-$(date +%s)"; ln -s "$R/$x" "$C/data/$x"; }
  done
  touch ~/jfn-replica/.marco_padroes
  local t0=$(date +%s) rc ids_arg=""
  for i in "$@"; do ids_arg="$ids_arg --id $i"; done
  cd "$C" && PYTHONPATH="$C" JFN_PADROES_MEM_MIN_GB=${JFN_PADROES_MEM_MIN_GB:-5} nice -n 15 ionice -c3 \
      .venv/bin/python -m tools.padroes_varrer --paralelo "$N" $ids_arg
  rc=$?
  # devolve à VM-1 só o que esta rodada gravou (os caches _* ficam na réplica)
  cd "$R/padroes" || return 1
  find . -maxdepth 1 -name '*.json' ! -name '_*' -newer ~/jfn-replica/.marco_padroes -printf '%f\n' > ~/jfn-replica/.devolver
  local n; n=$(wc -l < ~/jfn-replica/.devolver)
  if [ "$n" -gt 0 ]; then
    rsync -a --files-from=~/jfn-replica/.devolver . vm1-ts:JFN/data/padroes/ || rc=1
    md5sum $(cat ~/jfn-replica/.devolver) | sort > ~/jfn-replica/.md5_local
    ssh -o BatchMode=yes vm1-ts "cd JFN/data/padroes && md5sum $(tr '\n' ' ' < ~/jfn-replica/.devolver)" | sort > ~/jfn-replica/.md5_vm1
    cmp -s ~/jfn-replica/.md5_local ~/jfn-replica/.md5_vm1 || { echo '{"ev":"md5_diverge"}'; rc=1; }
  fi
  echo "{\"ev\":\"padroes_fim\",\"rc\":$rc,\"devolvidos\":$n,\"s\":$(( $(date +%s)-t0 ))}"
  return $rc
}
main "$@" < /dev/null
