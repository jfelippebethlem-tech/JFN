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
cd /home/ubuntu/JFN || exit 0
PY=.venv/bin/python
[ -x "$PY" ] || { echo "[pre-push] venv ausente — não medi"; exit 0; }

CATRACAS="tests/test_catraca_excepts.py tests/test_moeda_padrao_brasileiro.py"

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

L=$(awk '{print int($1)}' /proc/loadavg)
if [ "$L" -ge 6 ]; then
  echo "[pre-push] ⚠️  load $L em 2 vCPU — NÃO rodei os testes. Isto é dívida, não aprovação."
  exit 0
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
