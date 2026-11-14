#!/bin/bash
# Pré-aquece os caches dos endpoints PESADOS do painel (medidos no walker 2026-07-22:
# fornecedor_dependente 23s, frescor 14s, perícias 7s, sócio-servidor 6.5s frios).
# O humano nunca mais espera o frio: o cron paga o custo em background (nice), o
# painel responde em ms. TTLs analíticos = 3600s; cron a cada 30min mantém sempre quente.
set -u
LOG=/home/ubuntu/JFN/data/prewarm_painel.log
exec 9>/tmp/prewarm_painel.lock
flock -n 9 || exit 0
BASE="http://127.0.0.1:8000/api"
URLS=(
  "intel/fornecedor_dependente?limite=150"
  "siafe/stats"
  "fontes/frescor"
  "pericias?limite=80&ordem=score"
  "intel/socio_servidor?limite=150"
  "intel/nepotismo_cruzado?limite=80"
  "intel/nepotismo?limite=150"
  "intel/retro"
  "intel/porta_giratoria?limite=150"
  "pncp/conluio?esfera=estado"
  "pncp/conluio?esfera=prefeitura"
  "pncp/conluio"
  "cartel"
  "compliance/painel"
  "certames/lista?esfera=prefeitura&limite=600"
  "certames/lista?esfera=estado&limite=600"
  # 2026-07-24: /api/conflito era a rota MAIS LENTA do painel (13 s, e também na 2ª chamada — não tinha
  # cache). Com o cache aplicado ela cai para 40 ms; entra aqui para que nem a primeira visita espere.
  "conflito"
  "coendereco/clusters"
  "compliance/graph"
  # 2026-09-24 (auditoria quadro a quadro): abas que passavam de 60 s a frio — mesmas URLs que o painel pede.
  "intel/fracionamento?limite=120"
  "intel/sobrepreco?limite=120&esfera=estado"
  "intel/sobrepreco?limite=120&esfera=prefeitura"
  "intel/escalada?limite=120&esfera=estado"
  "intel/escalada?limite=120&esfera=prefeitura"
  "intel/fantasmas?limite=60"
  "acervo/estatisticas"
  # 2026-11-03: a HOME (cockpit) pedia 8 rotas que nunca estiveram aqui — a fênix levava 72,6 s e o
  # lift 25 s a frio, justo na primeira tela. Mesmas URLs que cockpit.js pede (test_prewarm_cobre_home).
  "intel/ninho_sala?limite=60"
  "comparador/economia"
  "comparador/vedada"
  "comparador/dossie"
  "intel/radar?limite=6"
  "intel/comunidades"
  "intel/lift"
  "intel/fenix"
  "intel/socio_sancionada"
  "intel/competencia_futura"
  "intel/dea_recorrente"
  "intel/ordem_cronologica"
  # 2026-11-13: aba Governo Couto — ~25 s a frio (load 5) (DOERJ + OB SIAFE de dois exercícios)
  "governo_couto"
  # 2026-11-13: Nomeados × candidatos — o cache antigo (10 min, sem SWR, fora daqui) estourava o teto de 30 s do
  # cliente a frio (26,5 s medidos a load 22; 61 s = dois estouros). Agora 1 h + SWR + disco, mantido quente aqui.
  "poder/nomeados_candidatos?esfera=estado"
  # 2026-11-13: organização por ano e mês — a quebra INTEIRA de cada fonte é um cálculo só (o filtro recorta
  # o que já está em cache). A OB do SIAFE leva ~25 s a frio (1,3 mi de linhas); as do PNCP ~10 s.
  "periodo/ob_siafe"
  "periodo/execucao_estado"
  "periodo/contratos_estado"
  "periodo/contratacoes_tcerj"
  "periodo/aditivos_estado"
  "periodo/tac_estado"
  "periodo/contratos_prefeitura"
  "periodo/aditivos_prefeitura"
  "periodo/despesa_prefeitura"
  "periodo/sancoes"
  "periodo/alertas"
)
{
  echo "── $(date -Is) prewarm"
  for u in "${URLS[@]}"; do
    t=$(nice -n 15 curl -s -o /dev/null -w "%{http_code} %{time_total}" "$BASE/$u")
    echo "  $t $u"
  done
} >> "$LOG" 2>&1
# trava o log em ~2000 linhas (sem logrotate dedicado)
tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
