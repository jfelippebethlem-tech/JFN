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

# BLINDAGEM CONTRA EDIÇÃO EM VOO. O bash lê o script por OFFSET de byte, então editar o arquivo
# enquanto uma instância roda faz o processo vivo retomar no lugar errado — e ele morre com um erro
# de sintaxe numa linha que está correta no disco. Já custou uma passada inteira duas vezes
# (2026-08-09 e de novo em 2026-08-10, linha 143, num run que já havia drenado 296100/2025). É a
# família 37 do catálogo, e conhecê-la não impediu a repetição: por isso a guarda é mecânica.
# Rodamos de uma CÓPIA, apagada logo em seguida — o fd fica aberto, o inode sobrevive, e nenhuma
# edição posterior do original alcança esta execução.
if [ -z "${DRENO_SNAPSHOT:-}" ]; then
  SNAP=$(mktemp /tmp/siafe_drenar.XXXXXX.sh) || exit 1
  cat "$0" > "$SNAP" || { rm -f "$SNAP"; exit 1; }
  export DRENO_SNAPSHOT=1
  exec bash "$SNAP" "$@"
fi
[ -n "${SNAP:-}" ] || SNAP="$0"
case "$SNAP" in /tmp/siafe_drenar.*) rm -f "$SNAP" ;; esac
[ -f .env ] && { set -a; . ./.env; set +a; }
export PYTHONPATH=.
PY=.venv/bin/python
LOG=data/siafe_drenar.log
MAX=${1:-1}
LOGIN1="https://www5.fazenda.rj.gov.br/SiafeRio/faces/login.jsp"
say(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }

# QUARENTENA POR PAR E DISJUNTOR DE LOGIN (24/10/2026). Medido no log: 3.721 "SEM GANHO", a UG 180100/2021
# tentada 652 vezes, sempre os MESMOS 5 pares na cabeça da fila — e os outros 251 nunca chegavam. Os do
# SIAFE 1 morriam todos no login (errorDisplay.jsp desde 13/09) e o 326100/2025 gastava 46 min esperando
# MFA para um trabalho que o checkpoint já dava por feito. Trabalho que parece progresso.
QUAR=data/siafe_dreno_quarentena.json
quar(){ PYTHONPATH=. $PY - "$QUAR" "$@" <<'PYEOF'
import json, sys, time
arq, acao, chave = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.load(open(arq))
except (OSError, ValueError):
    d = {}
e = d.get(chave, {"n": 0, "ts": 0})
DIAS = 7 * 86400
if acao == "pular":          # em quarentena = 3+ sem ganho seguidos (ou conflito) há menos de 7 dias
    print("sim" if e["n"] >= 3 and time.time() - e["ts"] < DIAS else "nao"); sys.exit()
if acao == "ganho":
    d.pop(chave, None)
elif acao == "sem_ganho":
    d[chave] = {"n": e["n"] + 1, "ts": time.time(), "motivo": sys.argv[4] if len(sys.argv) > 4 else ""}
elif acao == "conflito":
    d[chave] = {"n": 99, "ts": time.time(), "motivo": sys.argv[4] if len(sys.argv) > 4 else "conflito"}
json.dump(d, open(arq, "w"), ensure_ascii=False, indent=1)
PYEOF
}

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

# COTA CONTRA INANIÇÃO. O cron pede MAX=5, mas a guarda de carga corta o laço no meio: medido no
# log de 09-10/08, cada passada drena 1 ou 2 pares. Com 551 parciais na frente, os 257 pares NUNCA
# COLETADOS (61.355 OBs que o espelho conhece e a fonte canônica não tem) não alcançariam a cabeça
# da fila em meses — a prioridade correta virava fome permanente. A cada 4ª passada eles vêm antes.
VEZF=data/.siafe_dreno_vez
VEZ=$(( $(cat "$VEZF" 2>/dev/null | tr -dc '0-9' | tail -c 9) + 1 ))
# QUEM GASTA A VEZ É QUEM TRABALHA. O contador NÃO é gravado aqui: é gravado no fim, e só se a
# passada tiver drenado ao menos um par. Duas vezes já queimei a cota sem drenar nada — no ensaio
# (MAX=0, que só lista) e na passada das 08:50 de 2026-08-10, que viu load 6 e parou logo após
# montar a fila. Se a carga estiver alta justamente nas passadas de cota, os nunca coletados voltam
# à inanição que esta guarda existe para impedir — e ninguém percebe, porque o contador anda.
if [ $(( VEZ % 4 )) -eq 0 ]; then export PRIORIZAR_NUNCA=1; say "passada $VEZ — cota dos nunca coletados"; fi

# A LISTA SAI DO MEDIDOR, não de um teste de contagem redonda. Contagem redonda é a assinatura do
# TETO de consulta; coleta que morre em timeout (rc=124) para em número qualquer e ficava invisível
# — medido em 2026-08-09: 7 pares redondos contra 557 parciais. Ordem por EXPOSIÇÃO (o que mais
# falta primeiro), não por ano, porque quem fiscaliza começa pelo que pesa.
mapfile -t PARES < <(PYTHONPATH=. $PY - <<'PYEOF'
from compliance_agent.reporting.cobertura_siafe import medir
r = medir()
itens = [(t["obs_faltando_ao_menos"], t["ug"], t["exercicio"]) for t in r.get("truncados", [])]
# A amostra é de 300: pares totalmente ausentes empatam todos em 300 e a ordem vira arbitrária.
# O que ordena é quanto FALTA de verdade — as OBs que o espelho conhece e a fonte canônica não.
itens += [(max(0, p["obs_espelho_tfe"] - p["obs_siafe"]), p["ug"], p["exercicio"])
          for p in r.get("parciais", []) if p.get("estado") == "parcial"]
# NUNCA COLETADOS entram por último (peso negativo): sao lacuna real — testado em 2026-08-09 na
# UG 246300/2024 (Fundo Estadual de Recursos Hidricos), que estava com ZERO linhas e rendeu 376 OBs
# e R$ 80,4 mi, ficando `coberto`. Mas vem depois dos parciais, que escondem dado em unidade sobre
# a qual a casa JA publica numero.
# ...salvo na passada de cota, em que o peso vira positivo e eles encabeçam a lista.
import os
_peso = (lambda n: n) if os.environ.get("PRIORIZAR_NUNCA") else (lambda n: -n)
itens += [(_peso(p["obs_espelho_tfe"]) + (10**9 if os.environ.get("PRIORIZAR_NUNCA") else 0),
           p["ug"], p["exercicio"])
          for p in r.get("parciais", []) if p.get("estado") == "nunca_coletado"]
# DESLOCADOS no topo, sempre: são poucos (8 pares) e cada um esconde valor real que a casa hoje
# soma como R$ 0,00. Peso alto e fixo — não competem por exposição, competem por gravidade.
itens += [(2 * 10**9 + p["obs_siafe"], p["ug"], p["exercicio"])
          for p in r.get("parciais", []) if p.get("estado") == "deslocado"]
# um par pode estar nas DUAS listas (parou no teto E a amostra acusa ausência) — dedup, senão a
# passada gasta duas janelas de browser no mesmo alvo
visto = set()
for _, ug, ano in sorted(itens, reverse=True):
    if (ug, ano) in visto:
        continue
    visto.add((ug, ano))
    print(f"{ug} {ano}")
PYEOF
)
say "pares com coleta incompleta (teto + interrompida): ${#PARES[@]}"
[ "$MAX" = "0" ] && { printf '   %s\n' "${PARES[@]}"; exit 0; }

# PERFIL DA CONTA. Medido em 28/10/2026: no SIAFE 1 a conta só enxerga a PRÓPRIA UG em 2016–2020 (a base tem
# 1 UG nesses anos — 010100 — contra 97 a 126 de 2021 em diante; a sessão de 2020 entra no exercício certo e
# lista só 010100). 194 dos 235 pares da fila eram 2019–2020 de outras UGs e devolviam "todas as fatias
# zeradas" a cada passada. Esses pares saem da fila; UMA sonda a cada 30 dias reabre o caminho — se a
# visibilidade for ampliada, o par rende, o exercício passa a ter 2+ UGs e a regra se desfaz sozinha.
mapfile -t RESTRITO < <($PY - <<'PYEOF'
import sqlite3
c = sqlite3.connect("file:data/compliance.db?mode=ro", uri=True)
for ano, ug in c.execute("SELECT exercicio, MIN(ug_emitente) FROM ob_orcamentaria_siafe WHERE exercicio <= 2023 "
                         "GROUP BY exercicio HAVING COUNT(DISTINCT ug_emitente) = 1"):
    print(f"{ano}:{ug}")
PYEOF
)
SONDA_PERFIL=data/.siafe_dreno_sonda_perfil
sonda_vencida() { [ ! -f "$SONDA_PERFIL" ] || [ $(( $(date +%s) - $(stat -c %Y "$SONDA_PERFIL") )) -ge 2592000 ]; }
fora_do_perfil() {  # $1=UG $2=ANO → 0 se o exercício só expõe outra UG à conta
  local r; for r in "${RESTRITO[@]}"; do [ "${r%%:*}" = "$2" ] && [ "${r#*:}" != "$1" ] && return 0; done; return 1
}
# SENHA RECUSADA (30/10/2026): o SIAFE disse "Usuário e/ou senha incorretos" e o disjuntor só parava 90 min — ~20
# logins errados no dia, o caminho para bloquear a conta. Senha recusada trava o sistema até o .env mudar (o dono
# atualizar SIAFE_PASS); não há sonda: repetir a mesma senha não testa nada.
credencial_recusada() {  # $1=sistema (1|2) → 0 se a senha foi recusada depois da última mudança do .env
  local c="data/.siafe_dreno_credencial_$1"; [ -f "$c" ] && [ "$c" -nt .env ]
}
N_FORA=0; for par in "${PARES[@]}"; do set -- $par; fora_do_perfil "$1" "$2" && N_FORA=$((N_FORA+1)); done
[ "$N_FORA" -gt 0 ] && say "fora do perfil da conta (exercício só expõe a UG própria): $N_FORA par(es) — $(sonda_vencida && echo 'sonda mensal liberada' || echo 'próxima sonda em até 30 dias')"

feitos=0
for par in "${PARES[@]}"; do
  [ "$feitos" -ge "$MAX" ] && break
  set -- $par; UG=$1; ANO=$2
  # JANELA DO DIÁRIO. O cron das 04:50 começava um par que segurava o browser do SIAFE até ~05:45; o
  # diário das 05:00 esperava 15 min pelo lock e morria (21→24/10/2026, quatro madrugadas sem OB).
  HM=$((10#$(date +%H%M)))
  if [ "$HM" -ge 425 ] && [ "$HM" -lt 535 ]; then say "janela do diário (04:25-05:35) — não começo par novo"; break; fi
  if [ "$(quar pular "${UG}_${ANO}")" = "sim" ]; then continue; fi
  if fora_do_perfil "$UG" "$ANO"; then
    sonda_vencida || continue
    touch "$SONDA_PERFIL"; say "sonda mensal do perfil: tento $UG/$ANO (fora do perfil da conta)"
  fi
  # sistema com LOGIN quebrado (disjuntor abaixo) fica de fora 90 min — os pares do outro seguem. Eram 24 h:
  # em 28/10/2026 um soluço às 13:36 (sessão presa no servidor, que vive 30 min) parou 37 pares por um dia
  # inteiro, embora 240 s entre logins já resolvessem (A/B das 10:37). A pausa curta é a sonda: se o login
  # seguir quebrado, o disjuntor rearma sozinho; o AVISO ao dono continua no máximo 1 por 24 h.
  _S=$([ "$ANO" -le 2023 ] && echo 1 || echo 2); _PAUSA=data/.siafe_dreno_pausa_login_$_S
  if [ -f "$_PAUSA" ] && [ $(( $(date +%s) - $(stat -c %Y "$_PAUSA") )) -lt 5400 ]; then continue; fi
  credencial_recusada "$_S" && continue
  # backstop de VM: 2 vCPU não comportam browser sob carga alta
  # GUARDA DA CASA, DOIS CRITÉRIOS. A versão anterior era `load >= 4` à mão, e medido em
  # 2026-08-10 ela barrou **10 de 10** passadas do cron — a maioria drenou ZERO pares, porque a
  # linha de base da máquina fica em 3-5 com o sweep SEI rodando. Guarda que sempre fecha não
  # protege, só impede o trabalho: a fila tem 805 pares e ia levar meses.
  # O modo de crash desta VM é MEMÓRIA (2 Chromium + DuckDB, 4 vezes), não carga — e o
  # `vm_guard.preflight` já checa os dois. O dreno é UM browser, ligado à rede: teto de carga em 6
  # (o guard usa 1.7 para o sweep, que é outro perfil) e o piso de memória do próprio guard.
  OK_VM=$(VM_GUARD_MAX_LOAD=${DRENO_MAX_LOAD:-6.0} PYTHONPATH=. $PY -c "
from tools.vm_guard import preflight
ok, motivo = preflight()
print(('ok|' if ok else 'nao|') + motivo)" 2>/dev/null || echo "ok|guarda indisponível — sigo")
  case "$OK_VM" in
    nao\|*) say "VM saturada (${OK_VM#nao|}) — paro por aqui"; break ;;
  esac
  ANTES=$($PY -c "import sqlite3;print(sqlite3.connect('data/compliance.db').execute(\"SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente='$UG' AND exercicio=$ANO\").fetchone()[0])")
  # quantas linhas deste par estão DESLOCADAS antes de mexer — é a régua do reparo (ver abaixo)
  DESLOCADAS_ANTES=$($PY -c "import sqlite3;print(sqlite3.connect('data/compliance.db').execute(\"SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente='$UG' AND exercicio=$ANO AND nome_credor GLOB '*[0-9],[0-9][0-9]' AND nome_credor NOT GLOB '*[A-Za-z]*'\").fetchone()[0])")
  # A LISTA ENVELHECE DENTRO DA PRÓPRIA PASSADA. Ela é tirada uma vez no início; se um par foi
  # drenado enquanto os outros rodavam, ele já não está mais redondo — reprocessá-lo gasta uma
  # janela de browser à toa. Medido 2026-08-09: a 263100/2023 voltou à fila com 3.938 linhas, e a
  # mensagem ainda dizia "contagem redonda", o que era falso.
  # A lista envelhece dentro da própria passada: um par drenado enquanto os outros rodavam já não
  # precisa de browser. O teste agora é "ainda incompleto?" (amostra de números de OB contra o
  # espelho), não "ainda redondo" — que só valia para o teto.
  AINDA=$(PYTHONPATH=. $PY - "$UG" "$ANO" <<'PYEOF'
import sys
from compliance_agent.reporting.cobertura_siafe import medir
ug, ano = sys.argv[1], str(sys.argv[2])
r = medir()
alvo = {(t["ug"], t["exercicio"]) for t in r.get("truncados", [])}
# NUNCA COLETADO TAMBÉM É INCOMPLETO — e este filtro o excluía. O par com ZERO linhas no SIAFE
# falhava o teste "ainda incompleto?" e era descartado com a mensagem "coleta já completa (0
# linhas)", que diz o contrário do que zero significa. Foi o que anulou a cota anti-inanição:
# medido em 2026-08-10 12:52, a passada de cota levou os nunca coletados à cabeça da fila e esta
# guarda pulou TODOS, um a um, terminando com "0 par(es) nesta passada".
# DESLOCADO entra junto: a linha existe e é inutilizável (valor em `nome_credor`), então o par
# precisa de RECOLETA tanto quanto o nunca coletado. Sem isto o dreno passaria batido justamente
# nos 12.073 registros que escondem R$ 3,41 bi.
alvo |= {(p["ug"], p["exercicio"]) for p in r.get("parciais", [])
         if p.get("estado") in ("parcial", "nunca_coletado", "deslocado")}
print("sim" if (ug, ano) in alvo else "nao")
PYEOF
)
  # a mensagem nomeia o número: "já completa (0 linhas)" era autocontraditória e escondeu o defeito
  [ "$AINDA" = "sim" ] || { say "UG $UG $ANO: nada a drenar ($ANTES linhas no SIAFE, o medidor não a lista como incompleta) — pulo"; continue; }
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
  # GANHO NÃO É SÓ CONTAGEM. Par DESLOCADO se cura por SUBSTITUIÇÃO (a PK é
  # (numero_ob, ug_emitente, exercicio) com INSERT OR REPLACE), então a contagem fica igual e o
  # teste de crescimento dizia "SEM GANHO" para uma passada que consertou tudo — medido em
  # 2026-08-10 na 010100/2016, que saiu de 2.544 linhas tortas e R$ 0,00 para 2.544 linhas certas e
  # R$ 666.741.527,24. Para reparo, o efeito é QUALIDADE, não quantidade.
  TORTAS=$($PY -c "import sqlite3;print(sqlite3.connect('data/compliance.db').execute(\"SELECT COUNT(*) FROM ob_orcamentaria_siafe WHERE ug_emitente='$UG' AND exercicio=$ANO AND nome_credor GLOB '*[0-9],[0-9][0-9]' AND nome_credor NOT GLOB '*[A-Za-z]*'\").fetchone()[0])")
  # REPARO É GRADIENTE, não interruptor. A 1ª versão exigia TORTAS = 0 e a 010100/2020 — que foi de
  # 2.260 linhas deslocadas para 22, fazendo aparecer R$ 739.925.353,31 — saiu como "SEM GANHO".
  # Resíduo é esperado: recoleta substitui o que a tela devolve HOJE, e OB que a fonte não mostra
  # mais fica torta para sempre (ver `limites_de_fonte`). O que conta é ter DIMINUÍDO.
  if [ "${DESLOCADAS_ANTES:-0}" -gt 0 ] && [ "${TORTAS:-0}" -lt "${DESLOCADAS_ANTES:-0}" ]; then
    if [ "${TORTAS:-0}" = "0" ]; then _resto=""; else _resto=" (restam ${TORTAS} irreparáveis: a tela não devolve mais esses números)"; fi
    say "UG $UG $ANO: REPARADO — ${DESLOCADAS_ANTES} linha(s) deslocada(s) → ${TORTAS}${_resto} (contagem segue $DEPOIS, rc=$rc)"
  elif [ "$DEPOIS" -gt "$ANTES" ]; then
    say "UG $UG $ANO: $ANTES → $DEPOIS linhas (rc=$rc)"
  else
    say "UG $UG $ANO: SEM GANHO ($ANTES → $DEPOIS, rc=$rc) — ver $SAIDA"
  fi
  if [ "$DEPOIS" -gt "$ANTES" ] || { [ "${DESLOCADAS_ANTES:-0}" -gt 0 ] && [ "${TORTAS:-0}" -lt "${DESLOCADAS_ANTES:-0}" ]; }; then
    quar ganho "${UG}_${ANO}"
    # o login FUNCIONOU: a sequência de falhas de login acabou. Sem isto, falha–sucesso–falha disparava o
    # disjuntor como "2 seguidos" (28/10/2026 09:13, com 316100/2022 rendendo 66 OBs entre as duas falhas).
    ULT_LOGIN_FALHO=; touch "data/.siafe_dreno_login_ok_$_S"     # o vigia lê: logou depois do disjuntor = curado
  elif grep -q '"nada_a_fazer": true' "$SAIDA"; then
    ULT_LOGIN_FALHO=; touch "data/.siafe_dreno_login_ok_$_S"     # chegou ao checkpoint = logou
    # o checkpoint diz "tudo feito" e o medidor diz "incompleto": repetir não resolve, só gasta browser
    quar conflito "${UG}_${ANO}" "checkpoint_feito_x_medidor_incompleto"
    say "UG $UG $ANO: CONFLITO — checkpoint diz feito, medidor diz incompleto. Quarentena 7 dias; exame humano."
  else
    _mot=$(grep -o '"etapa": "[a-z_]*"' "$SAIDA" | head -1 | cut -d'"' -f4)
    quar sem_ganho "${UG}_${ANO}" "${_mot:-sem_ganho}"
    if grep -qE '"erro": "senha_(incorreta|expirada)"' "$SAIDA"; then
      SIS=$([ "$ANO" -le 2023 ] && echo 1 || echo 2); touch "data/.siafe_dreno_credencial_$SIS"
      say "SENHA RECUSADA pelo SIAFE $SIS — paro esse sistema até o .env mudar (ver $SAIDA)"
      $PY -c "from compliance_agent.siafe_coord import notificar; notificar('🔑 JFN — o SIAFE $SIS recusou a senha (Usuário e/ou senha incorretos, ou senha expirada). Parei as tentativas para não bloquear a conta. Atualize SIAFE_PASS no .env do JFN; o dreno volta sozinho quando o .env mudar.')" >/dev/null 2>&1
      feitos=$((feitos+1)); continue
    fi
    # DISJUNTOR: dois pares seguidos do MESMO sistema caindo no login = o login está quebrado, não o par.
    if [ "${_mot:-}" = "login_nav" ] || [ "${_mot:-}" = "login" ]; then
      SIS=$([ "$ANO" -le 2023 ] && echo 1 || echo 2)
      if [ "${ULT_LOGIN_FALHO:-}" = "$SIS" ]; then
        say "DISJUNTOR: 2 pares seguidos do SIAFE $SIS falharam no LOGIN — paro a passada (ver $SAIDA)"
        AVISO=data/.siafe_dreno_aviso_login_$SIS; touch "data/.siafe_dreno_pausa_login_$SIS"
        if [ ! -f "$AVISO" ] || [ $(( $(date +%s) - $(stat -c %Y "$AVISO") )) -gt 86400 ]; then
          touch "$AVISO"
          $PY -c "from compliance_agent.siafe_coord import notificar; notificar('⚠️ JFN — o dreno do SIAFE $SIS parou: o LOGIN falha em todos os pares (último: UG $UG/$ANO). A coleta histórica desse sistema está travada até investigar — log: $SAIDA')" >/dev/null 2>&1
        fi
        feitos=$((feitos+1)); break
      fi
      ULT_LOGIN_FALHO=$SIS
    else
      ULT_LOGIN_FALHO=; touch "data/.siafe_dreno_login_ok_$_S"   # falhou DEPOIS do login: o login funcionou
    fi
  fi
  feitos=$((feitos+1))
  # RESPIRO ENTRE PARES. A sessão do SIAFE é única por IP e o servidor demora a soltá-la: medido em
  # 2026-08-09, a UG 404340 deu SEM GANHO duas vezes seguidas e o log DELA (por par, justamente
  # para isso) mostrou o login falhando 3× em `Page.fill` — o campo de usuário nem aparecia, que é
  # a cara de sessão anterior ainda aberta. É MITIGAÇÃO, não certeza: se voltar a acontecer, o log
  # do par mostra de novo e aí se investiga o lado do servidor.
  # SIAFE 1 SEGURA A SESSÃO MAIS TEMPO. Medido em 25/10/2026 com logins espaçados: 2016, 2020, 2021, 2022 e
  # 2023 entram num browser novo, mas a tentativa feita 45-90 s depois da anterior cai em errorDisplay/campo
  # ausente (sessão do usuário ainda presa no servidor). 4 min entre pares do SIAFE 1; o SIAFE 2 segue em 45 s.
  if [ "$feitos" -lt "$MAX" ]; then if [ "$ANO" -le 2023 ]; then sleep 240; else sleep 45; fi; fi
done
# O AVISO DO VAULT SE MANTÉM SOZINHO. As notas de caso avisam que seus valores de SIAFE são PISO
# e listam quais (UG, ano) faltam — lista que ENVELHECE a cada par drenado. Aviso desatualizado é
# ruído, e ruído ensina o leitor a pular o bloco de alerta. Reescreve depois de cada passada, e a
# ferramenta RETIRA o aviso da nota cujas unidades já foram todas drenadas.
if [ "$feitos" -gt 0 ]; then
  $PY -m tools.vault_aviso_piso_siafe --aplicar >> "$LOG" 2>&1 || say "aviso do vault falhou (segue)"
fi
# a vez só é consumida por passada que trabalhou (ver a nota do contador, acima)
if [ "$feitos" -gt 0 ]; then
  echo "$VEZ" > "$VEZF"
else
  say "vez $VEZ NÃO consumida (0 pares drenados) — a próxima passada repete esta prioridade"
fi
say "fim ($feitos par(es) nesta passada)"
