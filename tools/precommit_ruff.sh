#!/usr/bin/env bash
# Gate de lint para o pre-commit (best-effort, NÃO bloqueia — alinhado ao hook local existente).
# Roda ruff só nos arquivos .py STAGED e AVISA se houver erro novo. A ideia é não deixar lint
# novo entrar nos arquivos que você está tocando, sem brigar com os 39 do baseline legado.
# Versionado para a disciplina ser reproduzível (o hook .git/hooks/pre-commit é local-only).
# Ver docs/PLANO-BENCHMARKS-E-CODIFICACAO-2026-06-09.md (§3 item 5).
set -u
root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
cd "$root" || exit 0

mapfile -t staged < <(git diff --cached --name-only --diff-filter=ACM 2>/dev/null | grep -E '\.py$' \
  | grep -vE '^(_SANDBOX|tools/debug)/' || true)
[ "${#staged[@]}" -eq 0 ] && exit 0

ruff="$root/.venv/bin/ruff"
[ -x "$ruff" ] || ruff="ruff"
command -v "$ruff" >/dev/null 2>&1 || exit 0

if ! out="$("$ruff" check "${staged[@]}" 2>/dev/null)"; then
  echo "[pre-commit] ⚠️  ruff achou lint nos arquivos staged (não bloqueia; corrija quando puder):"
  echo "$out" | tail -20
  echo "[pre-commit]    auto-fix seguro: .venv/bin/ruff check --fix ${staged[*]}"
fi
exit 0
