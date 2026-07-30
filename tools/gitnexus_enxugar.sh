#!/usr/bin/env bash
# Mantém o bloco do GitNexus em UM arquivo só — o ralo que o `analyze` reabre a cada índice.
#
# POR QUE EXISTE. `npx gitnexus analyze` escreve o mesmo bloco de ~2,5 KB em `CLAUDE.md` **e** em
# `AGENTS.md`. Os dois são carregados a cada turno: ~640 tokens pagos DUAS vezes por sessão, em todas
# as sessões, para sempre. Enxugar à mão não resolve — o próximo `analyze` desfaz, e desfaz calado.
# Medido em 2026-07-30: enxuguei, rodei o analyze, e o bloco voltou nos dois arquivos.
#
# Este script reduz o AGENTS.md ao ponteiro. Roda no pre-commit, então qualquer regeneração é
# corrigida no commit seguinte, sem ninguém precisar lembrar.
set -u
root="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
a="$root/AGENTS.md"
[ -f "$a" ] || exit 0
# ~500 bytes = já é o ponteiro; acima disso, o bloco completo voltou
[ "$(stat -c%s "$a")" -le 700 ] && exit 0

cat > "$a" <<'PONTEIRO'
<!-- gitnexus:start -->
# GitNexus — Code Intelligence

As regras do GitNexus para este projeto vivem em **`CLAUDE.md`** (bloco gerado, no final).

**Por que não estão aqui.** `AGENTS.md` e `CLAUDE.md` são AMBOS carregados a cada turno, e o
`npx gitnexus analyze` escreve o MESMO bloco nos dois — ~640 tokens pagos duas vezes por sessão.
`tools/gitnexus_enxugar.sh` (pre-commit) devolve este arquivo ao ponteiro sempre que o analyze o
reinfla. Uma fonte, um custo.
<!-- gitnexus:end -->
PONTEIRO
echo "[pre-commit] AGENTS.md reinflado pelo gitnexus analyze — reduzido ao ponteiro"
git add "$a" 2>/dev/null || true
exit 0
