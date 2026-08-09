#!/bin/bash
# Drena os pares (UG, ano) cuja coleta do SIAFE parou em CONTAGEM REDONDA — sintoma de teto.
#
# POR QUE EXISTE. Em 2026-08-09 a tabela canônica de OB tinha 23 pares parados em 1.000 linhas
# exatas. A causa não era só o teto de 1.000 por consulta: era a PK que apagava a OB homônima de
# outra unidade (67% dos números colidem entre UGs), o guard de fatia capada que nunca disparava
# (o platô real é 989, o limiar estava em 990), o cabeçalho da BASE usado no lugar do da TELA e a
# navegação que clicava por índice de menu. Com os cinco consertos, a UG 180100/2023 saiu de
# **1.000 para 7.839 linhas** (R$ 3,20 bi contabilizados, 1.772 credores) — e foi assim que os
# R$ 385,8 mi da PHOTONLUX apareceram na fonte canônica.
#
# COMO RODA. Um par por vez (a sessão do SIAFE é ÚNICA por IP e serializa com o sweep do SEI pelo
# browser_lock). Resumível: cada par tem checkpoint próprio, e repetir o comando continua de onde
# parou. Anos até 2023 vão ao SIAFE 1; 2024+ ao SIAFE 2 — errar o sistema devolve zero e parece
# bloqueio (ver docs/PLAYBOOK-SIAFE-NAVEGACAO.md).
#
#   bash tools/siafe_drenar_capados.sh            # lista o que falta e drena 1 par
#   bash tools/siafe_drenar_capados.sh 3          # drena até 3 pares nesta passada
#   bash tools/siafe_drenar_capados.sh 0          # só lista
set -u
cd /home/ubuntu/JFN || exit 1
[ -f .env ] && { set -a; . ./.env; set +a; }
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/siafe_drenar.log
MAX=${1:-1}
LOGIN1="https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
say(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

[ -f data/.pause_siafe_drenar ] && { say "pausado (.pause_siafe_drenar)"; exit 0; }

# a lista sai do DADO, não de um arquivo: contagem redonda é o próprio sintoma
mapfile -t PARES < <($PY - <<'PYEOF'
import sqlite3
con = sqlite3.connect("data/compliance.db")
for ug, ano in con.execute(
        "SELECT ug_emitente, exercicio FROM ob_orcamentaria_siafe GROUP BY 1,2 "
        "HAVING COUNT(*) IN (1000,2000,3000,5000) ORDER BY exercicio DESC, ug_emitente"):
    print(f"{ug} {ano}")
PYEOF
)
say "pares em contagem redonda: ${#PARES[@]}"
[ "$MAX" = "0" ] && { printf '   %s\n' "${PARES[@]}"; exit 0; }

feitos=0
for par in "${PARES[@]}"; do
  [ "$feitos" -ge "$MAX" ] && break
  set -- $par; UG=$1; ANO=$2
  # backstop de VM: 2 vCPU não comportam browser sob carga alta
  L=$(awk '{print int($1)}' /proc/loadavg); [ "$L" -ge 4 ] && { say "load $L alto — paro por aqui"; break; }
  ANTES=$($PY -c "import sqlite3;print(sqlite3.connect('data/compliance.db').execute(\"SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente='$UG' AND exercicio=$ANO\").fetchone()[0])")
  if [ "$ANO" -le 2023 ]; then export JFN_SIAFE_LOGIN_URL="$LOGIN1"; else unset JFN_SIAFE_LOGIN_URL; fi
  say "drenando UG $UG ano $ANO (SIAFE $([ "$ANO" -le 2023 ] && echo 1 || echo 2)) — $ANTES linhas"
  timeout -k 120 3300 nice -n 10 $PY -m compliance_agent.siafe_ob_orcamentaria \
      --exercicio "$ANO" --por-ug "$UG" --ug-grande --ingerir >> data/siafe_drenar_saida.log 2>&1
  rc=$?
  DEPOIS=$($PY -c "import sqlite3;print(sqlite3.connect('data/compliance.db').execute(\"SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente='$UG' AND exercicio=$ANO\").fetchone()[0])")
  # O EFEITO, não a ação: rc=0 com ganho zero já enganou nesta casa mais de uma vez.
  if [ "$DEPOIS" -gt "$ANTES" ]; then
    say "UG $UG $ANO: $ANTES → $DEPOIS linhas (rc=$rc)"
  else
    say "UG $UG $ANO: SEM GANHO ($ANTES → $DEPOIS, rc=$rc) — ver data/siafe_drenar_saida.log"
  fi
  feitos=$((feitos+1))
done
say "fim ($feitos par(es) nesta passada)"
