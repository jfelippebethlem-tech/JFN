# -*- coding: utf-8 -*-
"""E10 · `e10.p5_emergencia_recorrente` — dispensa EMERGENCIAL recorrente na mesma unidade e exercício (SOMBRA ⚖️).

Porta a régua que só existia em `tools/sweep_emergencia_recorrente.py` (plano §16.3; registro
`a_portar.p5_dedup_por_processo`): **uma linha por PROCESSO**, nunca por item — `compras_diretas_tcerj` repete o
TOTAL do processo em cada item, e somar linha a linha inflava o acervo 2,30× (R$ 39,65 bi × R$ 17,20 bi, medido em
11/08/2026; DETRAN/2025 virava "6 emergências, R$ 148,8 mi" onde há UM processo de R$ 24,8 mi). O enquadramento
legal entra como prova (art. 75, VIII; art. 24, IV da 8.666; art. 29, XV da 13.303), não só o texto do objeto. A
régua de emergência e de recorrência é a canônica de `compliance_agent/fracionamento_emergencia.py` (sem cópia).

Elegibilidade (invariante 3): só conta o processo com veredito 'E' na exigência `fornecedor` da E9
(`compra_direta_tcerj`): ente público fora; processo sem CNPJ resolvível ('?:SEM_CNPJ', '?:CREDOR_SEM_CADASTRO')
fica INDETERMINADO e é contado no resumo. Emergência é legal: o indício é a RECORRÊNCIA medida, nunca o instituto.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from decimal import Decimal

from compliance_agent.aplicacao.detectores import Carga, Disparo, elegivel
from compliance_agent.dominio.achado import Fato, Papel
from compliance_agent.dominio.contrato_id import chave_espelho_tcerj, deduplicar
from compliance_agent.fracionamento_emergencia import RESSALVA, agrupar_emergencias, eh_emergencial
from compliance_agent.reporting.intel_base import reais

ID = "e10.p5_emergencia_recorrente"
UNIDADE = "compra_direta_tcerj"
VERSAO = "e10-p5-2"   # 2: grafias do mesmo processo no espelho reduzidas pela chave canônica (dominio.contrato_id)
MINIMO = 5           # emergências no mesmo exercício para virar indício (o padrão do sweep)

# uma linha por PROCESSO (× fornecedor: processo com dois contratados conta para cada um, como no sweep)
_SQL = ("SELECT processo, unidade, ano_processo, fornecedor, MAX(valor), MIN(objeto), MIN(enquadramento_legal) "
        "FROM compras_diretas_tcerj {filtro} GROUP BY processo, unidade, ano_processo, fornecedor")


def _grupo(unidade, exercicio) -> str:
    return f"{unidade or '?'}|{exercicio}"


def _dedup(linhas) -> tuple[list, dict]:
    """Uma linha por (processo canônico, fornecedor) na unidade: a grafia `SEI-…`/`SEI…`/sem prefixo do mesmo processo
    contava como outra emergência. Fica a de maior valor (o total do processo)."""
    def chave(r):
        k = chave_espelho_tcerj(r[1], r[0])
        return None if k is None else f"{k}|{str(r[3] or '').strip().upper()}"
    return deduplicar(linhas, chave=chave, ordem=lambda r: (-float(r[4] or 0), str(r[0])), valor=lambda r: r[4])


def _itens(linhas) -> list[dict]:
    return [{"chave_e9": proc, "grupo": _grupo(uni, ano), "processo": proc, "unidade": uni, "exercicio": ano,
             "fornecedor": forn, "valor": float(valor or 0), "objeto": obj, "enquadramento": enq,
             "emergencial": eh_emergencial(obj, enq)}
            for proc, uni, ano, forn, valor, obj, enq in linhas]


def carregar(con: sqlite3.Connection, exercicio: int | None = None) -> Carga:
    filtro, par = ("WHERE ano_processo = ?", (exercicio,)) if exercicio else ("", ())
    linhas, dedup = _dedup(con.execute(_SQL.format(filtro=filtro), par).fetchall())
    return Carga(itens=_itens(linhas), contexto={"dedup_espelho": dedup})


def grupo_de(d: Disparo) -> str:
    return d.grupo


def carregar_grupo(con: sqlite3.Connection, grupo: str, exercicio: int | None = None) -> Carga:
    linhas, _ = _dedup(con.execute(_SQL.format(filtro=""), ()).fetchall())
    return Carga(itens=[c for c in _itens(linhas) if c["grupo"] == grupo])


def detectar(itens: list[dict], contexto: dict | None = None) -> list[Disparo]:
    eleg = [c for c in itens if elegivel(c)]
    grupos = agrupar_emergencias(
        [(c["unidade"], c["exercicio"], c["fornecedor"], c["valor"], c["objeto"], c["enquadramento"]) for c in eleg],
        minimo=MINIMO)
    membros: dict[str, list[dict]] = {}
    for c in eleg:
        if c["emergencial"]:
            membros.setdefault(c["grupo"], []).append(c)
    out = []
    for g in sorted(grupos, key=lambda g: _grupo(g["unidade"], g["exercicio"])):
        chave = _grupo(g["unidade"], g["exercicio"])
        ms = sorted(membros[chave], key=lambda c: (-c["valor"], str(c["processo"]), str(c["fornecedor"])))
        entradas = {"grupo": chave, "minimo": MINIMO,
                    "emergencias": [{"processo": c["processo"], "fornecedor": c["fornecedor"],
                                     "valor": round(c["valor"], 2), "enquadramento": c["enquadramento"],
                                     "e9": c["e9"]} for c in ms]}
        obs = (f"{g['n']} contratação(ões) emergencial(is) na unidade {g['unidade']}, exercício {g['exercicio']}, "
               f"somando {reais(g['total'])}; fornecedor dominante {g['fornecedor_dominante']} com "
               f"{g['concentracao_dominante']:.0%} do valor ({g['n_fornecedores']} fornecedor(es)). {RESSALVA}")
        fatos = [Fato(papel=Papel.SUPORTE, tipo="contratacao", fonte="compras_diretas_tcerj",
                      referencia=str(c["processo"]), descricao=str(c["objeto"] or "")[:240],
                      valor=Decimal(str(round(c["valor"], 2))),
                      dados={"fornecedor": c["fornecedor"], "enquadramento": c["enquadramento"],
                             "veredito_e9": c["e9"]}) for c in ms[:50]]
        out.append(Disparo(chave=chave, grupo=chave, estado="INDICIO", observacao=obs, entradas=entradas,
                           processo=str(ms[0]["processo"]) if ms else None, evidencias=fatos,
                           valores={"n": g["n"], "total": round(g["total"], 2),
                                    "fornecedor_dominante": g["fornecedor_dominante"],
                                    "concentracao_dominante": g["concentracao_dominante"],
                                    "n_fornecedores": g["n_fornecedores"]}))
    return out


def resumo(itens: list[dict], disparos: list[Disparo]) -> dict:
    emerg = [c for c in itens if c["emergencial"]]
    por = Counter(c.get("e9") or "?:SEM_LINHA_E9" for c in emerg)
    valor = Counter()
    for c in emerg:
        valor[c.get("e9") or "?:SEM_LINHA_E9"] += c["valor"]
    indet = sum(n for k, n in por.items() if k.startswith("?"))
    return {"universo_linhas_processo": len(itens), "emergenciais": len(emerg),
            "emergenciais_elegiveis": sum(1 for c in emerg if elegivel(c)), "emergenciais_indeterminadas": indet,
            "por_veredito": dict(sorted(por.items())),
            "valor_por_veredito": {k: round(v, 2) for k, v in sorted(valor.items())},
            "cobertura": round(1 - indet / len(emerg), 4) if emerg else None,
            "disparos": len(disparos), "soma_disparos": round(sum(d.valores["total"] for d in disparos), 2)}
