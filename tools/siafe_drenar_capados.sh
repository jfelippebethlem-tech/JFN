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

# INSTÂNCIA ÚNICA. A sessão do SIAFE é uma por IP: dois drenadores derrubam a sessão um do outro e
# o log fica ilegível (medido em 2026-08-09, quando lancei o segundo sem ver que o primeiro ainda
# corria — os dois apareceram intercalados no mesmo arquivo). PID em arquivo, não flock: um flock
# em fd é herdado pelo filho, e um chromium órfão seguraria a trava para sempre.
PIDF=data/.siafe_drenar.pid
if [ -f "$PIDF" ]; then
  ANT=$(tr -dc '0-9' < "$PIDF")
  if [ -n "$ANT" ] && kill -0 "$ANT" 2>/dev/null && \
     tr '\0' ' ' < "/proc/$ANT/cmdline" 2>/dev/null | grep -q 'siafe_drenar'; then
    say "já rodando (pid $ANT) — saio sem tocar no SIAFE"; exit 0
  fi
fi
echo $$ > "$PIDF"
trap 'rm -f "$PIDF"' EXIT

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
  # A LISTA ENVELHECE DENTRO DA PRÓPRIA PASSADA. Ela é tirada uma vez no início; se um par foi
  # drenado enquanto os outros rodavam, ele já não está mais redondo — reprocessá-lo gasta uma
  # janela de browser à toa. Medido 2026-08-09: a 263100/2023 voltou à fila com 3.938 linhas, e a
  # mensagem ainda dizia "contagem redonda", o que era falso.
  case "$ANTES" in
    1000|2000|3000|5000) ;;
    *) say "UG $UG $ANO: já não está redonda ($ANTES linhas) — pulo"; continue ;;
  esac
  # CHECKPOINT DE COLETA QUEBRADA NÃO VALE. Os arquivos `uggrande_*.json` de junho marcam fatias
  # como feitas, mas foram escritos quando a ingestão usava o cabeçalho errado (as linhas entravam
  # com a chave vazia e sobrava UMA por fatia) e quando a PK apagava a OB de outra unidade. Se a
  # contagem da UG ainda está redonda, o "feito" do checkpoint é desmentido pelo próprio banco —
  # medido em 2026-08-09 na UG 243200/2023, que respondeu "nada a fazer" com 1.000 linhas.
  # …mas SÓ UMA VEZ. Se já existe o backup, o checkpoint atual foi escrito pelo código CORRIGIDO e
  # guarda progresso real: afastá-lo de novo faz a UG recomeçar do zero a cada passada, e uma
  # unidade que precisa de várias janelas (a 404340/2023 tem a primeira fatia inteira capada, com
  # subdivisão profunda) nunca chegaria ao fim. Medido em 2026-08-09, depois de ela dar SEM GANHO
  # três vezes seguidas.
  CK="data/sei_cache/uggrande_${UG}_${ANO}.json"
  if [ -f "$CK" ] && [ ! -f "$CK.desmentido_pelo_banco" ]; then
    mv -f "$CK" "$CK.desmentido_pelo_banco"
    say "checkpoint de $UG/$ANO afastado (1ª vez): dizia 'feito' com a contagem redonda ($ANTES)"
  fi
  if [ "$ANO" -le 2023 ]; then export JFN_SIAFE_LOGIN_URL="$LOGIN1"; else unset JFN_SIAFE_LOGIN_URL; fi
  say "drenando UG $UG ano $ANO (SIAFE $([ "$ANO" -le 2023 ] && echo 1 || echo 2)) — $ANTES linhas"
  # LOG POR PAR. Com todos os pares escrevendo no mesmo arquivo não dá para saber de QUAL coleta
  # veio um erro — e foi exatamente o que me custou três medições erradas em 2026-08-09, quando um
  # processo antigo (código de antes de um conserto) seguia escrevendo ao lado do novo. Saída sem
  # procedência é dado sem valor.
  SAIDA="data/siafe_drenar_${UG}_${ANO}.log"
  timeout -k 120 3300 nice -n 10 $PY -m compliance_agent.siafe_ob_orcamentaria \
      --exercicio "$ANO" --por-ug "$UG" --ug-grande --ingerir > "$SAIDA" 2>&1
  rc=$?
  DEPOIS=$($PY -c "import sqlite3;print(sqlite3.connect('data/compliance.db').execute(\"SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente='$UG' AND exercicio=$ANO\").fetchone()[0])")
  # O EFEITO, não a ação: rc=0 com ganho zero já enganou nesta casa mais de uma vez.
  if [ "$DEPOIS" -gt "$ANTES" ]; then
    say "UG $UG $ANO: $ANTES → $DEPOIS linhas (rc=$rc)"
  else
    say "UG $UG $ANO: SEM GANHO ($ANTES → $DEPOIS, rc=$rc) — ver $SAIDA"
  fi
  feitos=$((feitos+1))
  # RESPIRO ENTRE PARES. A sessão do SIAFE é única por IP e o servidor demora a soltá-la: medido em
  # 2026-08-09, a UG 404340 deu SEM GANHO duas vezes seguidas e o log DELA (por par, justamente
  # para isso) mostrou o login falhando 3× em `Page.fill` — o campo de usuário nem aparecia, que é
  # a cara de sessão anterior ainda aberta. É MITIGAÇÃO, não certeza: se voltar a acontecer, o log
  # do par mostra de novo e aí se investiga o lado do servidor.
  [ "$feitos" -lt "$MAX" ] && sleep 45
done
# O AVISO DO VAULT SE MANTÉM SOZINHO. As notas de caso avisam que seus valores de SIAFE são PISO
# e listam quais (UG, ano) faltam — lista que ENVELHECE a cada par drenado. Aviso desatualizado é
# ruído, e ruído ensina o leitor a pular o bloco de alerta. Reescreve depois de cada passada, e a
# ferramenta RETIRA o aviso da nota cujas unidades já foram todas drenadas.
if [ "$feitos" -gt 0 ]; then
  $PY -m tools.vault_aviso_piso_siafe --aplicar >> "$LOG" 2>&1 || say "aviso do vault falhou (segue)"
fi
say "fim ($feitos par(es) nesta passada)"
