#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gera docs/vereditos_pericia.md — ledger compacto dos vereditos da perícia p/ o RAG do Hermes.

Objetivo: o Hermes RE-ACUSAVA o que a auditoria-ouro já havia refutado, porque o RAG
não carregava os vereditos. Este digest é auto-indexado (FONTES do hermes_rag inclui
docs/*.md) e dá ao Hermes a memória de "esta entidade já foi periciada — não re-acuse".

Fonte: tabela pericia_fornecedor (compliance.db). Compacta 1 linha/entidade e DESTACA
os já-julgados-limpos (0 confirmados e 0 indícios = refutado). Rode após cada sweep de
perícia e antes do `hermes_rag.py build`.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path

REPO = Path("/home/ubuntu/JFN")
DB = REPO / "data" / "compliance.db"
OUT = REPO / "docs" / "vereditos_pericia.md"


def gerar() -> int:
    c = sqlite3.connect(str(DB))
    rows = c.execute(
        "select favorecido, cnpj, ug, grau, score, n_confirmados, n_indicios, "
        "n_indisponivel "
        "from pericia_fornecedor where resumo is not null and resumo != '' "
        "order by n_confirmados desc, score desc"
    ).fetchall()

    # Linha compacta (SEM o resumo boilerplate, que é quase idêntico entre entidades
    # e só polui o índice). Refutados = todos (núcleo anti-re-acusação). Com-achado =
    # só os com confirmado real OU top-500 por score (o resto é 🟡 formulaico sem sinal).
    limpos, com_achado = [], []
    for fav, cnpj, ug, grau, sc, ncf, nind, nindisp in rows:
        cnpj = (cnpj or "").strip() or "s/CNPJ"
        linha = (
            f"- **{(fav or '?').strip()}** (`{cnpj}`, UG {ug or '?'}) — "
            f"{grau} score {sc}: {ncf} confirmado(s), {nind} indício(s), {nindisp} INDISPONÍVEL."
        )
        if ncf == 0 and nind == 0:
            limpos.append(linha)
        else:
            com_achado.append((ncf, sc, linha))

    com_achado.sort(key=lambda t: (t[0], t[1]), reverse=True)
    com_achado = [l for ncf, sc, l in com_achado if ncf > 0][:] + \
                 [l for ncf, sc, l in com_achado if ncf == 0][:500]

    linhas = [
        "# Vereditos da perícia (memória de auditoria-ouro do Hermes)",
        "",
        "> Gerado por `tools/vereditos_para_rag.py`. **Regra:** antes de acusar uma "
        "entidade, consulte se ela JÁ foi periciada abaixo. Entidade na seção "
        "'JÁ JULGADAS SEM ACHADO' foi **refutada** — NÃO re-acuse; INDISPONÍVEL ≠ irregular.",
        "",
        f"## JÁ JULGADAS SEM ACHADO (refutadas — {len(limpos)})",
        "",
        *limpos,
        "",
        f"## COM INDÍCIO/CONFIRMADO A APURAR ({len(com_achado)})",
        "",
        *com_achado,
        "",
    ]
    OUT.write_text("\n".join(linhas), encoding="utf-8")
    return len(rows)


if __name__ == "__main__":
    n = gerar()
    print(f"OK: {n} vereditos -> {OUT}")
