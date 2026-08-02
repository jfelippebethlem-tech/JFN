#!/usr/bin/env bash
# Gate do PAINEL no pre-commit — roda só quando `static/*.{html,js,css}` foi tocado.
#
# POR QUE EXISTE. O boot do painel já morreu calado três vezes (dois TDZ + uma corrida com View
# Transitions) e o cockpit ficou inerte por treze versões, porque o sintoma visível ("o card não
# apareceu") parecia CSS. O detector correto é `pageerror`. E um `*/` órfão já engoliu um `@media`
# inteiro — por isso a checagem de comentário/chave balanceada entra junto.
#
# DUAS CAMADAS, de propósito:
#   1. ESTÁTICA (sempre, ~2 s, sem navegador): integridade do CSS e as abas do painel. Bloqueia.
#   2. VIVA (`painel_boot_check`, precisa do servidor + Chrome): bloqueia SE puder rodar. Se o
#      servidor não responde ou a máquina está sob carga, AVISA e deixa passar — INDISPONÍVEL não é
#      falha, e um gate que derruba a VM de 2 vCPU no meio de um commit é pior que o bug que pega.
set -u
root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$root" || exit 0
py="$root/.venv/bin/python"
[ -x "$py" ] || { echo "[pre-commit] venv ausente — gate do painel NÃO rodou" >&2; exit 0; }

# ── 0-A. bundle em dia com o fonte ───────────────────────────────────────────────────────────────
# Vem ANTES do bump, e é um buraco que só existe desde que o painel passou a ter build (v58).
# Enquanto fonte e artefato eram o MESMO arquivo, "editei e não bumpei" era impossível de esconder:
# o hash mudava. Agora existe um estado que a catraca `?v=` não enxerga — `static/js/src/` editado
# e bundle não reconstruído: o hash do artefato bate com a tag, a catraca diz "em dia", e a
# correção não chega a ninguém. É o mesmo defeito que o bump_versao existe para matar, um nível
# acima. Sem Node na máquina, AVISA e passa — pelo mesmo motivo da camada 2 abaixo.
if ! out="$(PYTHONPATH=. "$py" -m tools.painel_build_check 2>&1)"; then
  echo "[pre-commit] ❌ gate do painel BLOQUEOU (bundle defasado):" >&2
  echo "$out" | tail -12 >&2
  exit 1
fi

# ── 0-A2. o CSS e concatenacao dos estratos ─────────────────────────────────────────────────────
# `static/css/painel.css` passou a ser GERADO por `tools/painel_css_cortar.py --juntar` a partir de
# `static/css/src/*.css`. Editar o artefato direto e a mesma classe de bug do bundle defasado: a
# proxima concatenacao apaga a correcao, sem aviso. Bloqueia se os dois divergirem.
if ! out="$(PYTHONPATH=. "$py" -m tools.painel_css_cortar --check 2>&1)"; then
  echo "[pre-commit] ❌ gate do painel BLOQUEOU (CSS divergente dos estratos):" >&2
  echo "$out" | tail -6 >&2
  exit 1
fi

# ── 0-B. catraca de cache ────────────────────────────────────────────────────────────────────────
# Editar o painel sem mexer no `?v=` do HTML = correção que não chega em NINGUÉM (o navegador serve
# o cache). Bloqueia, porque o sintoma é invisível em revisão de código.
if ! out="$("$py" -m tools.painel_bump_versao --check 2>&1)"; then
  echo "[pre-commit] ❌ $out" >&2
  exit 1
fi

# ── 1. estática, sempre ──────────────────────────────────────────────────────────────────────────
if ! out="$("$py" -m pytest -q -p no:randomly \
      tests/test_painel_css_integro.py tests/test_painel_abas.py \
      tests/test_painel_script_classico.py tests/test_painel_ponte_completa.py \
      tests/test_painel_ordem_de_boot.py \
      tests/test_rotas_sem_orfa.py tests/test_rotas_sem_superficie.py 2>&1)"; then
  echo "[pre-commit] ❌ gate do painel BLOQUEOU (checagem estática):" >&2
  echo "$out" | tail -25 >&2
  exit 1
fi

# ── 2. viva, quando a máquina permite ────────────────────────────────────────────────────────────
carga="$(cut -d' ' -f1 /proc/loadavg)"
if ! curl -sf -m 4 -o /dev/null "${JFN_BASE:-http://127.0.0.1:8000}/status"; then
  echo "[pre-commit] ⚠️  servidor fora — `painel_boot_check` não rodou (rode à mão antes de push)" >&2
  exit 0
fi
if awk -v c="$carga" 'BEGIN{exit !(c > 3.0)}'; then
  echo "[pre-commit] ⚠️  load $carga em 2 vCPU — pulei o boot_check para não derrubar a VM" >&2
  exit 0
fi
if ! out="$(PYTHONPATH=. nice -n 10 "$py" -m tools.painel_boot_check 2>&1)"; then
  echo "[pre-commit] ❌ gate do painel BLOQUEOU (pageerror no boot):" >&2
  echo "$out" | tail -25 >&2
  exit 1
fi
exit 0
