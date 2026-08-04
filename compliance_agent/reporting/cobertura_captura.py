# -*- coding: utf-8 -*-
"""Quanto do que foi PAGO o motor consegue ler — o número que limita todos os outros.

Por que existe. O painel mostra achados, fila do fiscal e cobertura da perícia, e nenhum deles
diz o mais básico: sobre que fração do dinheiro a casa consegue afirmar alguma coisa. Medido em
2026-08-04, o quadro era este e só existia para quem rodasse ferramenta de linha de comando:

    38.955 processos com OB paga NUNCA foram tocados     R$ 13,86 bi
       234 arquivados sem captura utilizável              (94 sem teor · 86 parciais · 54 sem docs)
     1.941 arquivados e íntegros                          ← a base de tudo que o motor afirma

Um painel que mostra 51 processos EXTREMO sem dizer que eles saem de 1.941 lidos, num universo de
40 mil pagos, deixa a impressão contrária à verdade. INDISPONÍVEL ≠ 0, e ponto cego medido é
melhor que ponto cego calado.

HONESTIDADE: a contagem de "nunca tocados" vem do SIAFE (`ob_orcamentaria_siafe`, status
Contabilizado — OB é pagamento, empenho não), que é a fonte canônica da casa. Folha, previdência
e encargo entram SEPARADOS: não são alvo da fiscalização de contratação, e somá-los ao ponto cego
inflaria o problema com dinheiro que ninguém pretende auditar por este caminho.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent.parent
_DB = _REPO / "data" / "compliance.db"
_ACERVO = _REPO / "data" / "sei_arquivo"


def _estado_do_acervo(base: Path) -> dict[str, int]:
    """Quantos processos arquivados estão íntegros, parciais, sem teor ou sem índice.

    Lê o manifesto UMA vez por processo. A versão anterior chamava `docs_com_conteudo` e depois
    `captura_integra`, que reabre e reparseia o mesmo JSON — três leituras por processo, 30
    segundos no acervo inteiro. O `J()` do painel aborta em 30s: a promessa rejeitava e a aba
    INTEIRA deixava de renderizar, sem erro no console. Cartão que mata a aba é pior que cartão
    nenhum. (2026-08-04)
    """
    from compliance_agent.sei import acervo_texto

    fora = {"integro": 0, "parcial": 0, "sem_teor": 0, "sem_docs": 0}
    if not base.is_dir():
        return fora
    for p in base.iterdir():
        if not p.is_dir() or p.name.startswith("_"):
            continue
        mf = p / "manifest.json"
        if not mf.exists():
            continue
        try:
            man = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        docs = [d for d in (man.get("docs") or []) if isinstance(d, dict)]
        if not docs:
            fora["sem_docs"] += 1
            continue
        # mesmo critério do `manifesto_norm.captura_integra` — 60% dos declarados com teor —
        # mas sem reabrir o manifesto: os caminhos já estão em mãos.
        com = sum(1 for d in docs
                  if d.get("texto") and acervo_texto.tem_conteudo(p / str(d["texto"])))
        if com == 0:
            fora["sem_teor"] += 1
        elif com >= max(1, int(len(docs) * 0.6)):
            fora["integro"] += 1
        else:
            fora["parcial"] += 1
        # A bandeira `captura_vazia`/`captura_completa` do manifesto NÃO entra aqui de propósito:
        # o disco é que diz o estado da captura, e bandeira desmentida pelo disco é dado velho —
        # a mesma doutrina que `manifesto_norm.captura_integra` aplica desde 2026-08-04.
    return fora


def medir(*, db: str | Path | None = None, acervo: Path | None = None) -> dict[str, Any]:
    """Cobertura de captura: o que o motor lê, o que não lê, e quanto dinheiro há de cada lado."""
    caminho = Path(db or os.environ.get("JFN_DB") or _DB)
    base = Path(acervo or _ACERVO)
    if not caminho.exists():
        return {"ok": False, "indisponivel": True, "motivo": "compliance.db ausente"}

    estado = _estado_do_acervo(base)
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        tem = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                          "AND name='ob_orcamentaria_siafe'").fetchone()
        if not tem:
            return {"ok": True, "indisponivel": True, "acervo": estado,
                    "motivo": ("`ob_orcamentaria_siafe` ausente — sem a fonte canônica de "
                               "pagamento não se afirma quanto do dinheiro está fora do alcance")}
        # universo: processos SEI com OB paga (Contabilizado); o resto é empenho/cancelado
        universo, pago = con.execute(
            "SELECT COUNT(DISTINCT processo), ROUND(COALESCE(SUM(valor), 0), 2) "
            "FROM ob_orcamentaria_siafe "
            "WHERE processo LIKE 'SEI-%/%/20%' AND status='Contabilizado'").fetchone()
    finally:
        con.close()

    arquivados = sum(estado.values())
    return {
        "ok": True, "indisponivel": False,
        "acervo": estado,
        "arquivados": arquivados,
        "processos_com_ob_paga": universo,
        "nunca_tocados": max(0, (universo or 0) - arquivados),
        "valor_pago_universo": pago,
        "pct_arquivado": round(100 * arquivados / universo, 1) if universo else None,
        "pct_utilizavel": round(100 * estado["integro"] / universo, 1) if universo else None,
        "nota": ("Sobre 'nunca tocados' a casa não afirma NADA — não é ausência de irregularidade, "
                 "é ausência de leitura. Os parciais e sem teor voltam à fila do sweep pelo "
                 "critério do `captura_integra` (ver tools/sei_sweep._arquivo_incompleto)."),
    }
