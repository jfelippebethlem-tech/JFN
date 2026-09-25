# -*- coding: utf-8 -*-
"""Pagamentos que o portal publicou e depois DESPUBLICOU.

Por que existe. A base de OBs é reconstruída por exercício a cada coleta: `collectors/tfe_ob`
apaga o ano e reinsere o que o zip do TFE-RJ traz. Isso é correto — a fonte manda — e era
SILENCIOSO. Medido em 2026-08-04, comparando a base com o backup off-box de 02/08: **140 OBs de
sete exercícios, R$ 30.001.367,60, deixaram de ser publicadas** e sumiram da base sem que nada
avisasse. A descoberta veio dois dias depois, por um golden de números que quebrou.

Para uma casa de controle externo, isto não é ruído de dado. Ordem bancária é a prova de
pagamento; sair do portal da transparência é fato sobre a prova, com hipóteses inocentes
(cancelamento, correção, reclassificação) e não inocentes. Nenhuma delas se investiga sobre o que
não se registrou — por isso `ob_retirada` guarda a linha inteira, e esta leitura a expõe.

HONESTIDADE: retirada é INDÍCIO de nada por si só. O que este módulo afirma é factual — "estava
publicada, não está mais" — e a leitura fica com quem fiscaliza. Tabela ausente devolve
`indisponivel`, nunca 0: zero afirmaria que nada foi retirado, onde não houve medição.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

_DB = Path(__file__).resolve().parent.parent.parent / "data" / "compliance.db"


def _tem_tabela(con) -> bool:
    return bool(con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='ob_retirada'").fetchone())


def medir(*, db: str | Path | None = None, teto: int = 20) -> dict[str, Any]:
    """Resumo das OBs despublicadas: quanto, quando, e as maiores."""
    import os

    caminho = Path(db or os.environ.get("JFN_DB") or _DB)
    if not caminho.exists():
        return {"ok": False, "indisponivel": True, "motivo": "compliance.db ausente"}
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        if not _tem_tabela(con):
            return {"ok": True, "indisponivel": True,
                    "motivo": ("tabela ob_retirada ainda não existe — ela nasce na primeira "
                               "ingestão do TFE após 2026-08-04; ausência de registro NÃO é "
                               "ausência de retirada")}
        n, valor = con.execute(
            "SELECT COUNT(*), ROUND(COALESCE(SUM(valor), 0), 2) FROM ob_retirada").fetchone()
        por_exercicio = [{"exercicio": e, "n": q, "valor": v} for e, q, v in con.execute(
            "SELECT exercicio, COUNT(*), ROUND(SUM(valor), 2) FROM ob_retirada "
            "GROUP BY exercicio ORDER BY exercicio")]
        maiores = [{"numero_ob": o, "exercicio": e, "ug_nome": u, "favorecido_nome": f,
                    "valor": v, "data_pagamento": d, "retirada_em": r}
                   for o, e, u, f, v, d, r in con.execute(
                       "SELECT numero_ob, exercicio, ug_nome, favorecido_nome, valor, "
                       "data_pagamento, retirada_em FROM ob_retirada "
                       "ORDER BY valor DESC LIMIT ?", (teto,))]
        # Concentração é o que separa correção de fonte de remoção dirigida: 140 OBs em 140
        # favorecidos diferentes tem cara de correção; 140 num só, não.
        favorecidos = con.execute(
            "SELECT COUNT(DISTINCT favorecido_cpf) FROM ob_retirada").fetchone()[0]
        ultima = con.execute("SELECT MAX(retirada_em) FROM ob_retirada").fetchone()[0]
        return {"ok": True, "indisponivel": False, "n": n, "valor": valor,
                "favorecidos_distintos": favorecidos, "ultima_retirada": ultima,
                "por_exercicio": por_exercicio, "maiores": maiores,
                "ressalva": ("Despublicação é FATO, não acusação: cancelamento, correção e "
                             "reclassificação explicam parte. O registro existe para que a "
                             "verificação seja possível — sem ele, a linha some sem rastro.")}
    finally:
        con.close()
