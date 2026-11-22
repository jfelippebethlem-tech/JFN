#!/bin/bash
# Dossiê da gestão Couto — a VARREDURA PESADA de OB (duas janelas inteiras do SIAFE) roda NO it-campo, sobre a réplica
# só-leitura (~/jfn-replica/data, ver replica_sync.sh). O código chega antes, num pacote (codigo.tgz) enviado pela
# VM-1 (tools/dossie_couto.sh) — assim roda o código do commit que a VM-1 está usando, não o do worker. O JSON volta
# para data/dossie_couto/ da VM-1 por rsync e o md5 é impresso para a VM-1 conferir do lado de lá. Entrada padrão.
set -u
main() {
  local D=~/jfn-replica/dossie R=~/jfn-replica/data PY=~/JFN-worker/.venv/bin/python
  exec 7>~/jfn-replica/.dossie.lock; flock -n 7 || { echo '{"ev":"dossie_ocupado"}'; return 1; }
  [ -s "$D/codigo.tgz" ] || { echo '{"ev":"sem_codigo"}'; return 1; }
  rm -rf "$D/codigo" && mkdir -p "$D/codigo/data" && tar xzf "$D/codigo.tgz" -C "$D/codigo" || return 1
  for x in compliance.db receita_estab.db; do ln -sfn "$R/$x" "$D/codigo/data/$x"; done
  local t0=$(date +%s) rc
  cd "$D/codigo" && PYTHONPATH="$D/codigo" nice -n 15 ionice -c3 "$PY" -m compliance_agent.reporting.dossie_couto \
      coletar-ob --saida "$D/ob_brutos.json" > "$D/coletar.log" 2>&1
  rc=$?
  [ $rc -eq 0 ] && [ -s "$D/ob_brutos.json" ] || { echo "{\"ev\":\"coleta_falhou\",\"rc\":$rc}"; tail -5 "$D/coletar.log"; return 1; }
  rsync -a "$D/ob_brutos.json" vm1-ts:JFN/data/dossie_couto/ob_brutos_itcampo.json || { echo '{"ev":"rsync_falhou"}'; return 1; }
  echo "{\"ev\":\"dossie_fim\",\"md5\":\"$(md5sum "$D/ob_brutos.json" | cut -d' ' -f1)\",\"s\":$(( $(date +%s)-t0 ))}"
}
main "$@" < /dev/null
