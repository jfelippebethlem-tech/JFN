#!/usr/bin/env bash
# Gate de lint do pre-commit — BLOQUEIA. Roda ruff só nos .py STAGED.
#
# POR QUE MUDOU (2026-07-30). Este gate nasceu best-effort (`exit 0` sempre) para "não brigar com os
# 39 do baseline legado". Medi: o baseline é **ZERO** — os 39 já foram pagos há tempo, e o único
# resto eram 6 achados, 1 deles de plugin de terceiro (`.agents/`, agora fora do ruff) e 2 que eram
# sintoma de verdade (um dicionário órfão em `cruzamentos_intel` e um import que o `avaliar` já
# aplicava por dentro em `vantajosidade`). Curados os 6, o repo fica limpo — e gate que avisa sem
# bloquear, num repo limpo, é só ruído que a gente aprende a ignorar. O mesmo raciocínio das
# catracas numéricas: o sinal só vale se doer.
#
# As regras são as de CORREÇÃO (E4/E7/E9/F/W6 — inclui E722 bare-except), com o estilo de "uma
# linha" deliberadamente ignorado em pyproject.toml. Não é gate de gosto; é gate de erro.
#
# Escape, quando for inevitável: `git commit --no-verify` (e o motivo no corpo do commit).
set -u
root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$root" || exit 0

mapfile -t staged < <(git diff --cached --name-only --diff-filter=ACM 2>/dev/null | grep -E '\.py$' \
  | grep -vE '^(_SANDBOX|tools/debug|\.agents|\.github/skills)/' || true)
[ "${#staged[@]}" -eq 0 ] && exit 0

ruff="$root/.venv/bin/ruff"
[ -x "$ruff" ] || ruff="ruff"
if ! command -v "$ruff" >/dev/null 2>&1; then
  echo "[pre-commit] ruff ausente — gate de lint NÃO rodou (instale: uv pip install ruff)" >&2
  exit 0   # ausência de ferramenta não é achado; INDISPONÍVEL ≠ limpo, e o aviso fica visível
fi

# Só arquivos que ainda existem (staged pode conter renomeado/removido no meio do caminho).
existentes=()
for f in "${staged[@]}"; do [ -f "$f" ] && existentes+=("$f"); done
[ "${#existentes[@]}" -eq 0 ] && exit 0

if ! out="$("$ruff" check "${existentes[@]}" 2>&1)"; then
  echo "[pre-commit] ❌ ruff BLOQUEOU o commit — lint nos arquivos staged:" >&2
  echo "$out" | tail -30 >&2
  echo "[pre-commit]    auto-fix seguro: .venv/bin/ruff check --fix ${existentes[*]}" >&2
  echo "[pre-commit]    escape consciente: git commit --no-verify (diga o motivo no commit)" >&2
  exit 1
fi
exit 0
