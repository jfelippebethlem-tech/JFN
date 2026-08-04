# -*- coding: utf-8 -*-
"""A fonte CANÔNICA de pagamento está truncada, e nada avisava.

A regra nº 2 desta casa é que OB do SIAFE é a verdade sobre pagamento, e o espelho TFE não se usa
para valor. A regra continua certa — mas ela só vale se o SIAFE estiver COMPLETO, e em 2026-08-04
ele não estava: a tela de OB Orçamentária do SIAFE-Rio 2 devolve no máximo **1.000 registros por
consulta**, e uma coleta feita só com `--por-ug` para uma UG grande para exatamente nesse número
sem dizer nada.

Como isso apareceu. Perseguindo um achado C3/C5 do IDESI (CNPJ 28470707000180, INAPTA na Receita,
R$ 92,37 mi pagos), o espelho TFE mostrava R$ 507,75 mi para o mesmo fornecedor — 5,5× o SIAFE.
Todos na UG 294200 (Fundação Saúde). Aí a UG inteira: SIAFE R$ 2,85 bi contra R$ 10,41 bi no
espelho. E na quebra por ano, 2022 e 2023 tinham **exatamente 1.000 OBs** cada.

    23 pares (UG, ano) param em exatamente 1.000 registros, de 642 pares
    outros pares chegam a 6.836 — distribuição natural não empata 23 vezes num número redondo
    nesses 23: SIAFE R$ 8,46 bi · espelho TFE R$ 19,26 bi · 137.654 OBs a menos na fonte canônica

O QUE NÃO É. Não é defeito de código: `siafe_ob_orcamentaria` já tem os três caminhos que furam o
teto (`chkRemoveLimit`, `--por-numero`, `--ug-grande`, com subdivisão por prefixo de Número). É
COLETA INACABADA — as UGs grandes foram varridas com `--por-ug` simples e ninguém as refez.

POR QUE VIRA MÓDULO. Enquanto o truncamento não é medido, ele mente para cima em toda peça que
some valor por UG e para baixo em toda cobertura: a manchete de captura publicada no painel
(universo de R$ 18,06 bi com OB paga) sai de um SIAFE que, nesses 23 pares, conhece menos da
metade do que o espelho registra. INDISPONÍVEL ≠ 0 vale também para a nossa própria coleta.

HONESTIDADE: a comparação com o TFE é indicativa, não aritmética — os dois universos não são
idênticos (há pares com MAIS valor no SIAFE que no espelho, p.ex. 180100/2021). O que prova o
truncamento é o **1.000 exato**, não a diferença; a diferença só dimensiona a ordem de grandeza
do que falta recoletar.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent.parent
_DB = _REPO / "data" / "compliance.db"

TETO_CONSULTA = 1000
"""Teto de registros por consulta da tela de OB Orçamentária (SIAFE-Rio 2). Um par (UG, ano) que
para exatamente nele foi truncado — ver docs/SIAFE-RIO2-GUIA-AUTOMACAO.md §5."""


def medir(*, db: str | Path | None = None) -> dict[str, Any]:
    """Pares (UG, exercício) cujo total de OBs no SIAFE parou no teto de consulta.

    Devolve a lista dos truncados com o comparativo do espelho TFE (indicativo do que falta), e o
    comando exato que recoleta cada um. Sem a tabela → INDISPONÍVEL declarado, nunca zero.
    """
    caminho = Path(db or os.environ.get("JFN_DB") or _DB)
    if not caminho.exists():
        return {"ok": False, "indisponivel": True, "motivo": "compliance.db ausente"}

    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        tem = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('ob_orcamentaria_siafe','ordens_bancarias')")}
        if "ob_orcamentaria_siafe" not in tem:
            return {"ok": True, "indisponivel": True,
                    "motivo": "`ob_orcamentaria_siafe` ausente — sem a fonte canônica não se afere "
                              "o truncamento dela"}
        # data_emissao do SIAFE é TEXTO DD/MM/AAAA: o ano são os 4 últimos, nunca os 4 primeiros.
        pares = con.execute(
            "SELECT ug_emitente, substr(data_emissao, 7, 4) ano, COUNT(*) n, "
            "       ROUND(COALESCE(SUM(valor), 0), 2) v "
            "FROM ob_orcamentaria_siafe GROUP BY 1, 2").fetchall()
        espelho: dict[tuple[str, str], tuple[int, float]] = {}
        if "ordens_bancarias" in tem:
            for ug, ano, n, v in con.execute(
                    "SELECT ug_codigo, substr(data_emissao, 1, 4) ano, COUNT(*), "
                    "       COALESCE(SUM(valor), 0) FROM ordens_bancarias GROUP BY 1, 2"):
                espelho[(str(ug), str(ano))] = (n, float(v or 0))
    finally:
        con.close()

    truncados = []
    for ug, ano, n, v in pares:
        if n != TETO_CONSULTA:
            continue
        e_n, e_v = espelho.get((str(ug), str(ano)), (0, 0.0))
        truncados.append({
            "ug": str(ug), "exercicio": str(ano),
            "obs_siafe": n, "valor_siafe": v,
            "obs_espelho_tfe": e_n, "valor_espelho_tfe": round(e_v, 2),
            "obs_faltando_ao_menos": max(0, e_n - n),
            "recoletar": (f"python -m compliance_agent.siafe_ob_orcamentaria --por-ug {ug} "
                          f"--exercicio {ano} --ug-grande"),
        })
    truncados.sort(key=lambda t: t["obs_faltando_ao_menos"], reverse=True)

    return {
        "ok": True, "indisponivel": False,
        "teto_consulta": TETO_CONSULTA,
        "pares_avaliados": len(pares),
        "pares_truncados": len(truncados),
        "obs_faltando_ao_menos": sum(t["obs_faltando_ao_menos"] for t in truncados),
        "valor_siafe_nos_truncados": round(sum(t["valor_siafe"] for t in truncados), 2),
        "valor_espelho_nos_truncados": round(sum(t["valor_espelho_tfe"] for t in truncados), 2),
        "truncados": truncados,
        "nota": ("O que prova o truncamento é a contagem parar em exatamente "
                 f"{TETO_CONSULTA}, não a diferença para o espelho TFE — os dois universos não são "
                 "idênticos e há pares com mais valor no SIAFE que no espelho. A diferença serve "
                 "só para dimensionar o que falta recoletar. Recoleta pelo caminho que fura o "
                 "teto (`--ug-grande`), que subdivide por prefixo de Número — e só na máquina "
                 "autorizada a falar com o SIAFE (`host_siafe.exigir_autorizacao`), uma sessão "
                 "por IP."),
    }
