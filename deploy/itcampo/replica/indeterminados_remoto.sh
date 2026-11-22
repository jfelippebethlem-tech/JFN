#!/bin/bash
# DIAGNÓSTICO DOS LAUDOS SEM CONCLUSÃO (compliance_agent.indeterminados diagnosticar) NO it-campo, sobre a réplica
# só-leitura (~/jfn-replica/data, ver replica_sync.sh). Sem LLM e sem rede: lê compliance.db, o acervo SEI (texto e
# manifesto) e a família do acervo; lê os autos SEM teto por rodada (na VM-1 são 150). O diagnostico.json volta para
# data/indeterminados/itcampo_diagnostico.json da VM-1 com md5 conferido nas duas pontas — e lá só é aceito se a
# amostra re-diagnosticada na VM-1 der igual (indeterminados.importar_diagnostico). Código = commit atual do
# ~/JFN-worker, num worktree próprio (o dos padrões faz checkout no meio da rodada dele). Uso: bash -s (entrada padrão).
set -u
main() {
  B=~/JFN-worker; C=~/jfn-replica/codigo-indeterminados; R=~/jfn-replica/data
  exec 7>~/jfn-replica/.indeterminados.lock; flock -n 7 || { echo '{"ev":"indeterminados_ocupado"}'; return 0; }
  local head; head=$(git -C "$B" rev-parse HEAD)
  [ -e "$C/.git" ] || git -C "$B" worktree add -q --detach "$C" "$head" || return 1
  git -C "$C" checkout -q --detach "$head" || return 1
  [ -e "$C/.venv" ] || ln -s "$B/.venv" "$C/.venv"
  # a família do acervo (diária na VM-1) entra na réplica; o cache de relacionados fica AQUI (incremental por mtime)
  nice -n 10 rsync -a vm1-ts:JFN/data/sei_familia.json "$R/" || return 1
  mkdir -p "$R/indeterminados"
  for x in compliance.db sei_arquivo pericia_agentes sei_familia.json indeterminados; do
    [ -L "$C/data/$x" ] || { [ -e "$C/data/$x" ] && mv "$C/data/$x" "$C/data/$x.local-$(date +%s)"; ln -s "$R/$x" "$C/data/$x"; }
  done
  local t0=$(date +%s) rc
  cd "$C" && PYTHONPATH="$C" nice -n 15 ionice -c3 \
      .venv/bin/python -m compliance_agent.indeterminados diagnosticar --max-ler 0 > "$R/indeterminados/.ultimo.log" 2>&1
  rc=$?
  [ $rc -eq 0 ] || { tail -5 "$R/indeterminados/.ultimo.log"; echo "{\"ev\":\"indeterminados_fim\",\"rc\":$rc}"; return $rc; }
  cd "$R/indeterminados" || return 1
  rsync -a diagnostico.json vm1-ts:JFN/data/indeterminados/itcampo_diagnostico.json.tmp || return 1
  local m_local m_vm1
  m_local=$(md5sum diagnostico.json | cut -d' ' -f1)
  m_vm1=$(ssh -o BatchMode=yes vm1-ts "md5sum JFN/data/indeterminados/itcampo_diagnostico.json.tmp" | cut -d' ' -f1)
  [ "$m_local" = "$m_vm1" ] || { echo '{"ev":"md5_diverge"}'; return 1; }
  ssh -o BatchMode=yes vm1-ts "mv JFN/data/indeterminados/itcampo_diagnostico.json.tmp JFN/data/indeterminados/itcampo_diagnostico.json" || return 1
  echo "{\"ev\":\"indeterminados_fim\",\"rc\":0,\"md5\":\"$m_local\",\"s\":$(( $(date +%s)-t0 ))}"
}
main "$@" < /dev/null
