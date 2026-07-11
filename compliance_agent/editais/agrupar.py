# -*- coding: utf-8 -*-
"""Agrupamento de editais por objeto semelhante — SEMÂNTICO (não por CATMAT).

POR QUE semântico: o CATMAT/CATSER vem ~0% preenchido na PCRJ (verificado ao
vivo). O agrupamento usa embedding do objeto + descrições dos itens (Cohere,
via tools/hermes_rag._embed). Pré-partição barata por material/serviço (M/S) e
ordem de grandeza do valor evita comparar caneta com hospital. Clusterização
aglomerativa simples (sem dependência pesada). Grupo < 3 = não avaliável por
peer-diff (declarado, não silenciado).
"""
from __future__ import annotations

import json
import math

_LIMIAR_PADRAO = 0.72


def cosseno(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _particao(item: dict) -> tuple:
    """M/S + ordem de grandeza do valor (log10) — o balde grosso antes do cosseno."""
    v = item.get("valor_estimado") or 0
    ordem = int(math.log10(v + 1)) if v and v > 0 else -1
    return (item.get("material_servico") or "?", ordem)


def agrupar(itens: list[dict], limiar: float = _LIMIAR_PADRAO) -> list[list[int]]:
    """Retorna listas de ÍNDICES de `itens`. Junta ao 1º grupo (mesma partição)
    cujo representante tenha cosseno ≥ limiar; senão abre grupo novo."""
    grupos: list[list[int]] = []
    reps: list[tuple] = []  # (particao, emb) do 1º membro de cada grupo
    for idx, it in enumerate(itens):
        part = _particao(it)
        emb = it["emb"]
        alvo = None
        for g, (rpart, remb) in enumerate(reps):
            if rpart == part and cosseno(emb, remb) >= limiar:
                alvo = g
                break
        if alvo is None:
            grupos.append([idx])
            reps.append((part, emb))
        else:
            grupos[alvo].append(idx)
    return grupos


def _texto_do_edital(row) -> str:
    """objeto + descrições dos itens (o que o comprador de fato preencheu)."""
    partes = [row["objeto"] or ""]
    try:
        for it in json.loads(row["itens_json"] or "[]")[:20]:
            d = it.get("descricao")
            if d:
                partes.append(d)
    except (ValueError, TypeError, AttributeError):
        pass
    return " · ".join(p for p in partes if p)[:1000]


def construir_clusters(con, limiar: float = _LIMIAR_PADRAO) -> dict:
    """Embeda os editais com documento, agrupa e grava edital_cluster."""
    from tools.hermes_rag import _embed
    rows = con.execute(
        """select numero_controle_pncp, objeto, material_servico, valor_estimado, itens_json
           from edital_documento where documento_disponivel=1""").fetchall()
    if not rows:
        return {"verificado": False, "motivo": "corpus vazio", "clusters": 0}
    textos = [_texto_do_edital(r) for r in rows]
    embs = _embed(textos, "search_document")
    itens = [{"id": r["numero_controle_pncp"], "material_servico": r["material_servico"],
              "valor_estimado": r["valor_estimado"], "emb": e} for r, e in zip(rows, embs)]
    grupos = agrupar(itens, limiar=limiar)
    con.execute("DELETE FROM edital_cluster")
    n_avaliaveis = 0
    for g in grupos:
        membros = [itens[i]["id"] for i in g]
        avaliavel = 1 if len(membros) >= 3 else 0
        n_avaliaveis += avaliavel
        con.execute(
            "INSERT INTO edital_cluster (assinatura_objeto, membros_json, tamanho, avaliavel) "
            "VALUES (?,?,?,?)",
            (textos[g[0]][:120], json.dumps(membros, ensure_ascii=False), len(membros), avaliavel))
    con.commit()
    return {"verificado": True, "clusters": len(grupos), "avaliaveis": n_avaliaveis,
            "editais": len(rows)}
