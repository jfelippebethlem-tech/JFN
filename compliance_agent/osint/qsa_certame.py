# -*- coding: utf-8 -*-
"""Alimenta o direcionamento consumado com o QSA REAL do certame (E.3.2).

A TAREFA QUE ISTO FECHA está aberta no caderno do dono desde antes deste motor existir: *"cruzar
QSA das concorrentes perdedoras com o grupo — se perdedora ∈ grupo, corrobora forte"*.
`osint/direcionamento_consumado.avaliar` já sabe responder; o que faltava era quem lhe entregasse
vencedor e perdedores com o quadro societário de cada um, lidos da base.

DE ONDE VÊM OS PERDEDORES, e por que não da fonte que parecia óbvia. `tcerj_licitante` nomeia
vencedor E perdedores, mas por NOME — e sem CNPJ não há QSA para cruzar. Quem serve aqui é
`pncp_resultado`, que traz `fornecedor_cnpj` junto de `ordem_classificacao`.

A DEFINIÇÃO DE PERDEDOR IMPORTA, e é onde um erro silencioso moraria: perdedor é quem ficou em
ordem > 1 **no mesmo ITEM**. Empresa que venceu o item 3 não é "perdedora" do item 1 — é
co-adjudicatária, e num certame multi-item isso é o resultado normal. Medido na base: 4.549
certames têm mais de um fornecedor distinto, mas só **684 itens** têm de fato disputa registrada
com classificação. Confundir os dois inflaria a cobertura em quase 7×.

COBERTURA, sempre declarada: a classificação além do 1º lugar existe em uma fração pequena do
acervo (600 linhas em 2º, 150 em 3º, 90 em 4º). Um certame sem perdedor registrado NÃO é um
certame sem disputa — é um certame não observado, e o resultado diz isso com todas as letras.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from compliance_agent.osint.direcionamento_consumado import avaliar as avaliar_direcionamento


def _doc(s: Any) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _qsa(con: sqlite3.Connection, cnpj: str) -> list[dict]:
    """Quadro societário de um CNPJ. Lista vazia = não observado, e o chamador precisa saber."""
    basico = _doc(cnpj)[:8]
    if len(basico) != 8:
        return []
    try:
        return [{"cpf": r[1], "nome": r[0], "desde": r[2]} for r in con.execute(
            "SELECT nome_socio, doc_socio, data_entrada FROM socios_receita WHERE cnpj_basico = ?",
            (basico,))]
    except sqlite3.OperationalError:
        return []


def _endereco(con: sqlite3.Connection, cnpj: str) -> dict:
    """Endereço cadastral, quando a verificação já o registrou. Ausente ⇒ sem aresta, não aresta fraca."""
    try:
        r = con.execute("SELECT evidencia FROM endereco_verificacao WHERE cnpj = ? LIMIT 1",
                        (_doc(cnpj),)).fetchone()
    except sqlite3.OperationalError:
        return {}
    return {"logradouro": r[0]} if r and r[0] else {}


def participantes(con: sqlite3.Connection, certame: str, *,
                  item: str | None = None) -> dict[str, Any]:
    """Vencedor e perdedores de um certame, com QSA — no formato que `avaliar` consome.

    Quando o certame tem vários itens e nenhum é indicado, escolhe o item com MAIS disputa
    registrada: é onde o cruzamento tem o que cruzar. O item escolhido sai declarado, porque um
    veredito sobre o item 7 apresentado como veredito do certame seria falso.
    """
    try:
        linhas = [dict(r) for r in con.execute(
            "SELECT item, fornecedor_cnpj, fornecedor_nome, ordem_classificacao, valor_homologado "
            "FROM pncp_resultado WHERE certame = ? AND COALESCE(fornecedor_cnpj,'') <> ''",
            (certame,))]
    except sqlite3.OperationalError:
        linhas = []
    if not linhas:
        return {"certame": certame, "vencedor": None, "perdedores": [], "item": None,
                "motivo": "certame sem resultado com CNPJ em pncp_resultado"}

    por_item: dict[Any, list[dict]] = {}
    for x in linhas:
        por_item.setdefault(x["item"], []).append(x)

    if item is not None:
        alvo = por_item.get(item, [])
    else:
        # Preferência: item que TEM classificado além do 1º lugar. Ordenar só por "mais
        # participantes distintos" escolhia, em 45 de 114 certames medidos, um item de
        # adjudicação múltipla (todos em 1º) e devolvia `nao_observado` num certame que TINHA
        # disputa registrada em outro item — o veredito certo pelo item errado.
        alvo = max(por_item.values(),
                   key=lambda ls: (any((x["ordem_classificacao"] or 0) > 1 for x in ls),
                                   len({x["fornecedor_cnpj"] for x in ls}), len(ls)))
        item = alvo[0]["item"] if alvo else None

    def _p(x):
        c = x["fornecedor_cnpj"]
        return {"cnpj": c, "nome": x["fornecedor_nome"], "socios": _qsa(con, c),
                "endereco": _endereco(con, c), "ordem": x["ordem_classificacao"]}

    venc = next((x for x in alvo if x["ordem_classificacao"] == 1), None) or (alvo[0] if alvo else None)
    perd = [x for x in alvo
            if x is not venc and (x["ordem_classificacao"] or 0) > 1
            and _doc(x["fornecedor_cnpj"]) != _doc(venc["fornecedor_cnpj"] if venc else "")]

    return {"certame": certame, "item": item, "itens_no_certame": len(por_item),
            "vencedor": _p(venc) if venc else None,
            "perdedores": [_p(x) for x in perd]}


def avaliar_certame(con: sqlite3.Connection, certame: str, *, item: str | None = None,
                    clausula_restritiva: bool = False, **kw) -> dict[str, Any]:
    """Veredito de direcionamento consumado sobre um certame concreto da base.

    Sem perdedor registrado o veredito é `nao_observado` — jamais "sem vínculo". A diferença é a
    de sempre nesta casa: ausência de registro não é ausência de disputa.
    """
    p = participantes(con, certame, item=item)
    if not p.get("vencedor"):
        return {"certame": certame, "veredito": "nao_observado", "cobertura": {"perdedoras": 0},
                "motivo": p.get("motivo", "vencedor não identificado"), "item": p.get("item")}
    if not p["perdedores"]:
        # Medido em 114 certames: nos 45 sem perdedora, a linha de ordem > 1 traz o PRÓPRIO
        # vencedor — o PNCP registra o mesmo fornecedor em mais de uma posição. Não é disputa.
        return {"certame": certame, "veredito": "nao_observado", "item": p["item"],
                "itens_no_certame": p.get("itens_no_certame"),
                "cobertura": {"perdedoras": 0},
                "motivo": ("nenhum concorrente DISTINTO classificado além do 1º lugar neste item "
                           "(quando há linha de ordem > 1, ela traz o próprio vencedor) — certame "
                           "NÃO OBSERVADO quanto à disputa, e não certame sem disputa")}
    r = avaliar_direcionamento(p["vencedor"], p["perdedores"],
                               clausula_restritiva=clausula_restritiva, **kw)
    r.update({"certame": certame, "item": p["item"], "itens_no_certame": p["itens_no_certame"],
              "vencedor_cnpj": p["vencedor"]["cnpj"], "vencedor_nome": p["vencedor"]["nome"]})
    return r


def cobertura(con: sqlite3.Connection) -> dict[str, Any]:
    """Quantos certames têm disputa registrada — o número que qualquer varredura precisa declarar."""
    try:
        total = con.execute("SELECT COUNT(DISTINCT certame) FROM pncp_resultado").fetchone()[0]
        itens = con.execute(
            "SELECT COUNT(*) FROM (SELECT certame, item FROM pncp_resultado "
            "WHERE COALESCE(fornecedor_cnpj,'') <> '' GROUP BY 1,2 "
            "HAVING SUM(CASE WHEN ordem_classificacao > 1 THEN 1 ELSE 0 END) > 0)").fetchone()[0]
        certames = con.execute(
            "SELECT COUNT(DISTINCT certame) FROM pncp_resultado "
            "WHERE ordem_classificacao > 1").fetchone()[0]
    except sqlite3.OperationalError:
        return {"certames": 0, "com_disputa": 0, "motivo": "pncp_resultado ausente"}
    return {"certames": total, "certames_com_disputa": certames, "itens_com_disputa": itens,
            "frac": round(certames / total, 4) if total else 0.0,
            "ressalva": ("certame sem classificado além do 1º lugar é NÃO OBSERVADO quanto à "
                         "disputa; tratá-lo como 'sem concorrência' inventaria um achado")}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    import argparse
    import json
    import os

    ap = argparse.ArgumentParser(description="Direcionamento consumado sobre um certame da base")
    ap.add_argument("certame", nargs="?")
    ap.add_argument("--item")
    ap.add_argument("--restritiva", action="store_true",
                    help="o certame já tem achado de cláusula restritiva")
    ap.add_argument("--cobertura", action="store_true")
    ap.add_argument("--db", default=os.environ.get("JFN_DB", "data/compliance.db"))
    a = ap.parse_args(argv)
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if a.cobertura or not a.certame:
            print(json.dumps(cobertura(con), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(avaliar_certame(con, a.certame, item=a.item,
                                             clausula_restritiva=a.restritiva),
                             ensure_ascii=False, indent=2, default=str))
    finally:
        con.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
