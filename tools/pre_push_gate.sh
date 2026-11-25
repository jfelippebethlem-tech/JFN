#!/bin/bash
# PORTÃO DE PRE-PUSH — o que impede o CI de virar spam de e-mail.
#
# POR QUE EXISTE. Em 2026-08-10 o CI ficou vermelho por SETE commits seguidos, todos por regressão
# minha, e cada um mandou e-mail de falha ao dono. O `pre-commit` roda ruff e os gates do painel,
# mas NENHUM teste — então toda regressão viajava direto para o runner. Consertar depois do e-mail
# é consertar tarde: o custo já foi pago por quem recebe o alerta.
#
# O QUE ELE RODA, e por que essa escolha:
#   1. As CATRACAS (1,4 s). São transversais e pegam a classe de erro que mais me escapou hoje:
#      `except Exception` novo, R$ no formato americano, inventário de rotas fora do golden.
#   2. Os testes CASADOS com o que mudou. Para cada arquivo tocado, procura `tests/test_<nome>*.py`
#      e também quem IMPORTA o módulo — é barato e pega o teste antigo da casa que cobre o código
#      novo (foi um teste desses que pegou meu TypeError no d3 e minha curva de severidade no d7).
#
# O QUE ELE NÃO FAZ. Não roda a suíte inteira (6.310 testes, minutos numa VM de 2 vCPU) — isso é do
# runner. E não bloqueia por carga alta: se a máquina está saturada ele DIZ que não mediu e deixa
# passar, porque portão que mente é pior que portão ausente.
#
#   bash tools/pre_push_gate.sh            # usado pelo hook .git/hooks/pre-push
#   bash tools/pre_push_gate.sh --so-catracas
set -u
# 23/11/2026: a VM-1 travou por memória (swap 100%, load 142) com DOIS portões rodando juntos (agentes diferentes
# empurrando ao mesmo tempo) e com portões ÓRFÃOS: um push abortado por tempo matava o git e o pytest do portão
# seguia (pai = systemd). Agora: (1) o portão roda no seu próprio grupo de processos e morre junto se o git morrer;
# (2) um portão por vez na máquina — o segundo espera a vez (até 30 min) em vez de somar outro pytest.
if [ -z "${JFN_GATE_GRUPO:-}" ]; then
  export JFN_GATE_GRUPO=1 JFN_GATE_GIT=$PPID
  exec setsid -w bash "$0" "$@"
fi
# 23/11/2026 08h40: o vigia herdava a saída do portão — o `rtk git push` esperava o fim dessa saída, o vigia esperava
# o git morrer: 5 h em deadlock com os testes já aprovados (153 ok às 03:20). Agora sem herdar a saída e morto no fim.
( while kill -0 "$JFN_GATE_GIT" 2>/dev/null; do sleep 5; done; kill -TERM -- -$$ 2>/dev/null ) >/dev/null 2>&1 </dev/null &
VIGIA=$!
trap 'kill "$VIGIA" 2>/dev/null' EXIT
exec 9>/tmp/jfn-pre-push.lock
if ! flock -n 9; then
  echo "[pre-push] outro push está no portão — esperando a vez (até 30 min) para não somar pytest na VM…"
  flock -w 1800 9 || { echo "[pre-push] ❌ BLOQUEADO — outro portão ocupou 30 min; tente de novo"; exit 1; }
fi
# 21/11/2026: era `cd /home/ubuntu/JFN` fixo — o push que sai de um worktree media o checkout principal (outro HEAD,
# outro índice) e aprovava sem ter rodado os testes do que ia (docs/untangle/passada-final.md §7.5). O venv é um só.
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo /home/ubuntu/JFN)" || exit 0
PY=/home/ubuntu/JFN/.venv/bin/python
[ -x "$PY" ] || { echo "[pre-push] venv ausente — não medi"; exit 0; }

# O2.5 (Esteira Única, 24/11): portão v2 — testes pelo grafo de import, rodados na VM-2/it-campo sobre o COMMIT que sobe
# (não a árvore de trabalho); nó nenhum respondendo → BLOQUEIA e registra em data/push_divida.json. Desligado até o
# dono ligar: `export JFN_PORTAO_V2=1` (sessão) ou `git config jfn.portaov2 1` (repo inteiro). Ver tools/portao.py.
if [ "${JFN_PORTAO_V2:-$(git config --get jfn.portaov2 2>/dev/null)}" = "1" ]; then
  PYTHONPATH="$(cd "$(dirname "$0")/.." && pwd)" exec nice -n 10 "$PY" -P -m tools.portao pre-push "$@"   # -P: o tools/ do worktree não sombreia este
fi

# O inventário de rotas ENTROU em 2026-08-11, e estava prometido no cabeçalho desde o primeiro dia
# sem estar na lista. O preço: liguei `/api/fiscal/emergencia_recorrente`, o portão aprovou o push
# e o CI ficou vermelho em `test_inventario_de_rotas_identico_ao_golden` — o e-mail ao dono que
# este portão existe para evitar. E o critério de casamento NÃO alcança esse caso: ele casa por
# nome de arquivo e por quem IMPORTA o módulo tocado, e `test_server_snapshot` não importa
# `rotas/vinculos`. Rota nova é onde o import não chega; por isso é transversal. Custo: 6,6 s.
# Regras de qualidade (docs/REGRAS-DE-QUALIDADE.md): toda catraca de regra é transversal — `test_regra_registro`
# barra o push se alguma delas sair desta lista (CST-05).
CATRACAS="tests/test_catraca_excepts.py tests/test_catraca_modulo_sem_chamador.py tests/test_moeda_padrao_brasileiro.py tests/test_server_snapshot.py tests/test_regra_registro.py tests/test_regra_catracas.py tests/test_regra_inventario.py tests/test_regra_motores.py tests/test_regra_controles_detector.py tests/test_regra_controles_sinteticos.py tests/test_regra_verificadores.py tests/test_regra_sensores.py tests/test_regra_juiz.py"

alvos() {
  # arquivos .py que este push leva (contra o upstream; sem upstream, contra o último commit)
  local base
  base=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)
  if [ -n "$base" ]; then git diff --name-only "$base"..HEAD -- '*.py'
  else git diff --name-only HEAD~1..HEAD -- '*.py' 2>/dev/null; fi
}

casados() {
  local t=""
  for f in $(alvos); do
    case "$f" in tests/*) [ -f "$f" ] && t="$t $f"; continue ;; esac
    local nome; nome=$(basename "$f" .py)
    for cand in tests/test_"$nome".py tests/test_"$nome"_*.py; do
      [ -f "$cand" ] && t="$t $cand"
    done
    # quem IMPORTA o módulo tocado — pega o teste ANTIGO que cobre código novo
    local mod; mod=$(printf '%s' "$f" | sed 's|/|.|g; s|\.py$||')
    for cand in $(grep -rl "$(basename "$f" .py)" tests/ --include='test_*.py' 2>/dev/null | head -6); do
      t="$t $cand"
    done
  done
  printf '%s\n' $t | sort -u | tr '\n' ' '
}

# O0.5 (Esteira Única, 24/11): repo PÚBLICO — nenhum CPF íntegro novo sobe. Barato (só o diff do
# push) e independe da carga: este bloqueio nunca é pulado.
_pii_base=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
if [ -n "$_pii_base" ]; then _pii_faixa="$_pii_base..HEAD"; else _pii_faixa="HEAD~1..HEAD"; fi
_pii_py="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)/.venv/bin/python"   # worktree não tem .venv
if ! "$_pii_py" -m tools.scan_pii --faixa "$_pii_faixa"; then
  echo "[portão] ⛔ CPF com DV válido no que este push leva ($_pii_faixa) — mascare antes de subir"
  exit 1
fi
# O0.5 (25/11): gitleaks no mesmo recorte — token/chave/senha novo nunca sobe. Ausente = não medido = bloqueia
# (gate que declara não ter medido guarda defeito). Instalação: release oficial em ~/.local/bin, sha256 conferido.
_gl=$(command -v gitleaks 2>/dev/null || echo "$HOME/.local/bin/gitleaks")
if [ ! -x "$_gl" ]; then
  echo "[portão] ⛔ gitleaks ausente — segredo NÃO medido neste push; instale-o antes de subir"
  exit 1
fi
if ! "$_gl" git --log-opts="$_pii_faixa" --redact --no-banner --log-level warn "$(git rev-parse --show-toplevel)"; then
  echo "[portão] ⛔ gitleaks achou segredo no que este push leva ($_pii_faixa) — tire do commit antes de subir"
  exit 1
fi

L=$(awk '{print int($1)}' /proc/loadavg)
# 24/11/2026: SEMPRE assim (catracas aqui, testes casados na VM-2). Com load < 6 o portão rodava 149 arquivos de
# teste NA VM-1 com teto de 600 s — estourava o tempo (log cortado em 56%, "teste falhando" sem nome) e é a mesma
# suíte ampla que travou a VM-1 em 23/11. A VM-1 só coordena (plano aprovado, Etapa 2 item 6). O ramo local abaixo
# fica só para VM-2 indisponível com JFN_GATE_LOCAL=1.
if [ "${JFN_GATE_LOCAL:-0}" != "1" ]; then
  # 15/11/2026: com a VM-1 carregada os testes eram pulados ("dívida, não aprovação") em quase todo push.
  # Agora as catracas (leves; leem o índice do git, que só existe aqui) rodam aqui e os testes casados vão à VM-2.
  echo "[pre-push] load $L em 2 vCPU — catracas aqui, testes casados na VM-2…"
  # shellcheck disable=SC2086
  # 18/11/2026: com load 14–38 as catracas levam 12–20 min; o teto de 300 s bloqueava o push SEM catraca falhando
  # (exit 124, log sem FAILED) e 4 sessões ficaram com 28 commits presos. Teto maior + timeout dito pelo nome.
  nice -n 19 timeout 1500 $PY -m pytest $CATRACAS -q --no-header -p no:cacheprovider >/tmp/pre_push.log 2>&1
  rc=$?
  if [ "$rc" -eq 124 ]; then
    echo "[pre-push] ❌ BLOQUEADO — catracas NÃO terminaram em 1500 s (load $L): não medido, tente com a VM mais leve"; exit 1
  elif [ "$rc" -ne 0 ]; then
    echo "[pre-push] ❌ BLOQUEADO — catraca falhando:"; grep -E "^FAILED|^ERROR|^E " /tmp/pre_push.log | head -12; exit 1
  fi
  C=$(casados)
  if [ "${1:-}" = "--so-catracas" ] || [ -z "${C// /}" ]; then echo "[pre-push] ✅ catracas ok; nada casado para a VM-2"; exit 0; fi
  # shellcheck disable=SC2086
  if timeout 900 bash tools/testar_na_vm2.sh $C >/tmp/pre_push_vm2.log 2>&1; then
    echo "[pre-push] ✅ catracas ok; VM-2: $(grep -E 'passed|failed' /tmp/pre_push_vm2.log | tail -1)"; exit 0
  fi
  if grep -qE "scp falhou|md5 do pacote" /tmp/pre_push_vm2.log || ! grep -qE "passed|failed|error" /tmp/pre_push_vm2.log; then
    echo "[pre-push] ⚠️  VM-2 indisponível — testes casados NÃO rodados. Isto é dívida, não aprovação."; exit 0
  fi
  echo "[pre-push] ❌ BLOQUEADO — teste falhando na VM-2:"; grep -E "^FAILED|^ERROR" /tmp/pre_push_vm2.log | head -12
  echo "[pre-push]    log completo: /tmp/pre_push_vm2.log"; exit 1
fi

SUITE="$CATRACAS"
[ "${1:-}" = "--so-catracas" ] || SUITE="$CATRACAS $(casados)"
# shellcheck disable=SC2086
SUITE=$(printf '%s\n' $SUITE | sort -u | tr '\n' ' ')
N=$(printf '%s\n' $SUITE | grep -c .)
echo "[pre-push] $N arquivo(s) de teste para o que este push muda…"

# shellcheck disable=SC2086
if nice -n 19 timeout 600 $PY -m pytest $SUITE -q --no-header -p no:cacheprovider >/tmp/pre_push.log 2>&1; then
  echo "[pre-push] ✅ $(tail -1 /tmp/pre_push.log)"
  exit 0
fi
echo "[pre-push] ❌ BLOQUEADO — teste falhando (o CI mandaria e-mail de falha):"
grep -E "^FAILED|^ERROR|assert" /tmp/pre_push.log | head -12
echo "[pre-push]    log completo: /tmp/pre_push.log"
echo "[pre-push]    escape consciente: git push --no-verify (diga o motivo no commit seguinte)"
exit 1
