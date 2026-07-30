<!-- gitnexus:start -->
# GitNexus — Code Intelligence

As regras do GitNexus para este projeto vivem em **`CLAUDE.md`** (bloco gerado, no final).

**Por que não estão aqui.** `AGENTS.md` e `CLAUDE.md` são AMBOS carregados a cada turno, e o
`npx gitnexus analyze` escreve o MESMO bloco nos dois — ~640 tokens pagos duas vezes por sessão.
`tools/gitnexus_enxugar.sh` (pre-commit) devolve este arquivo ao ponteiro sempre que o analyze o
reinfla. Uma fonte, um custo.
<!-- gitnexus:end -->
