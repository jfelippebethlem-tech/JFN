#!/bin/bash
# Dossiê-mestre da gestão Couto — COMANDO ÚNICO de atualização (chamado pela propagação, derivado `dossie_couto` em
# config/propagacao.yaml; à mão: `bash tools/dossie_couto.sh`).
#
#   1. sincroniza a réplica só-leitura no it-campo e roda lá a varredura pesada de OB (as duas janelas do SIAFE);
#   2. traz o JSON e confere o md5 nas duas pontas (memória entrega-entre-maquinas-confirmar-md5);
#   3. aqui, `gerar --ob-brutos` reconfere uma AMOSTRA de UGs no banco vivo (tem de dar igual) e monta HTML + PDF;
#   4. o verificador reprova o PDF se algum número não rastrear a fato com id, se achado não tiver prova primária
#      reconferida ou se o PDF perdeu conteúdo do HTML — reprovado não substitui o vigente (rc 2).
# Sem it-campo → varredura local, só com a VM-1 folgada (carga ≤ 7); senão rc 75 (a propagação tenta de novo).
set -u
J=/home/ubuntu/JFN
cd "$J" || exit 1
PY=.venv/bin/python
S=(ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=60 it-campo)
B=data/dossie_couto/ob_brutos_itcampo.json
mkdir -p data/dossie_couto
rm -f "$B"
say(){ echo "[$(date '+%F %T')] [dossie_couto] $*"; }
TGZ=$(mktemp /tmp/dossie-couto-XXXXXX.tgz)
trap 'rm -f "$TGZ"' EXIT
find compliance_agent -name '*.py' -not -path '*/__pycache__/*' | tar czf "$TGZ" -T - 2>/dev/null
say "réplica → it-campo"
if timeout -k 60 2400 "${S[@]}" 'wsl -d Ubuntu -- bash -s' < deploy/itcampo/replica/replica_sync.sh \
   && timeout -k 30 300 "${S[@]}" 'wsl -d Ubuntu -- bash -c "mkdir -p ~/jfn-replica/dossie && cat > ~/jfn-replica/dossie/codigo.tgz"' < "$TGZ" \
   && SAI=$(timeout -k 60 3600 "${S[@]}" 'wsl -d Ubuntu -- bash -s' < deploy/itcampo/replica/dossie_couto_remoto.sh) \
   && [ -s "$B" ]; then
  echo "$SAI" | tail -3
  MR=$(echo "$SAI" | grep -o '"md5":"[0-9a-f]*"' | cut -d'"' -f4)
  ML=$(md5sum "$B" | cut -d' ' -f1)
  if [ -n "$MR" ] && [ "$MR" = "$ML" ]; then
    say "it-campo ok (md5 $ML confere) — amostra igual + documento aqui"
    exec nice -n 10 $PY -m compliance_agent.reporting.dossie_couto gerar --ob-brutos "$B"
  fi
  say "md5 diverge (réplica $MR × VM-1 $ML) — JSON recusado"
  rm -f "$B"
fi
L=$(cut -d' ' -f1 /proc/loadavg)
if awk -v l="$L" 'BEGIN{exit !(l > 7)}'; then
  say "it-campo indisponível/recusado e VM-1 em carga $L — adiado (a propagação tenta de novo)"
  exit 75
fi
say "it-campo indisponível — varredura local"
exec nice -n 15 $PY -m compliance_agent.reporting.dossie_couto gerar
