# -*- coding: utf-8 -*-
"""Contexto de um certame, montado a partir do que a base realmente tem.

Separado de `varredura_certames` porque é aqui que mora a decisão delicada: **o que se
preenche e o que se deixa vazio**. Cada campo entregue a um detector é uma afirmação sobre o
mundo; preencher um campo com aproximação faz o detector produzir achado com aparência de
medido. Vazio faz ele responder `nao_avaliavel`, que é a resposta honesta.

REGRA DESTE MÓDULO: nenhum campo é inferido. Ou o dado está na base, ou a chave não existe.

Fontes e o que cada uma entrega:
  `pncp_resultado`   — um registro por ITEM por fornecedor, com valor homologado e classificação.
                       É daqui que sai a lista de propostas e a contagem de licitantes.
  `edital_documento` — objeto, valor estimado e o TEXTO do edital/TR.
  `edital_clausula`  — cláusula já classificada por eixo/subtipo, com o trecho-fonte.

Sobre `valor_estimado`: vem do edital, não do resultado. Somar homologados e chamar de
estimativa inverteria a comparação que J3 faz — o desconto ficaria sempre zero.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


def _linhas(con: sqlite3.Connection, sql: str, par: tuple) -> list[sqlite3.Row]:
    """Consulta tolerante a tabela ausente — base incompleta não derruba a varredura."""
    try:
        return list(con.execute(sql, par))
    except sqlite3.OperationalError as e:
        logger.debug("consulta indisponível (%s)", str(e)[:80])
        return []


def _propostas(con: sqlite3.Connection, certame: str) -> list[dict]:
    """Uma proposta por fornecedor, com o valor do certame e a melhor classificação dele.

    `pncp_resultado` tem uma linha por ITEM. Agrupar por fornecedor evita contar o mesmo
    licitante N vezes num certame de N itens — que faria J4 achar concorrência onde há um só.
    """
    rows = _linhas(con, """
        SELECT fornecedor_cnpj cnpj, MIN(fornecedor_nome) nome,
               SUM(COALESCE(valor_homologado,0)) valor,
               MIN(COALESCE(ordem_classificacao, 9999)) classificacao,
               MIN(COALESCE(porte_fornecedor,'')) porte,
               COUNT(*) n_itens
        FROM pncp_resultado
        WHERE certame = ? AND COALESCE(fornecedor_cnpj,'') <> ''
        GROUP BY fornecedor_cnpj
        ORDER BY classificacao
    """, (certame,))
    out = []
    for r in rows:
        d = dict(r)
        d["classificacao"] = None if d["classificacao"] == 9999 else int(d["classificacao"])
        out.append(d)
    return out


def _edital(con: sqlite3.Connection, certame: str) -> dict:
    rows = _linhas(con, """
        SELECT objeto, valor_estimado, texto, itens_json, material_servico, ano, orgao_cnpj
        FROM edital_documento WHERE numero_controle_pncp = ? LIMIT 1
    """, (certame,))
    return dict(rows[0]) if rows else {}


def _clausulas(con: sqlite3.Connection, certame: str) -> list[dict]:
    return [dict(r) for r in _linhas(con, """
        SELECT eixo, subtipo, texto, parametro_num, trecho_fonte
        FROM edital_clausula WHERE numero_controle_pncp = ?
    """, (certame,))]


def _cabecalho(con: sqlite3.Connection, certame: str) -> dict:
    rows = _linhas(con, """
        SELECT MIN(orgao_cnpj) orgao_cnpj, MIN(orgao_nome) orgao_nome,
               MIN(modalidade) modalidade, MIN(objeto) objeto, MIN(data_pub) data_pub,
               MIN(uf) uf, MIN(municipio) municipio
        FROM pncp_resultado WHERE certame = ?
    """, (certame,))
    return dict(rows[0]) if rows else {}


def _itens(edital: dict) -> list[dict]:
    try:
        dados = json.loads(edital.get("itens_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return dados if isinstance(dados, list) else []


def _serie_do_item(con: sqlite3.Connection, descricao: str, limite: int = 40) -> list[dict]:
    """Preços homologados do mesmo item em OUTROS certames — a régua de P3.

    Casamento por descrição normalizada é grosseiro e produz falso negativo (grafia diferente
    não casa). Falso negativo aqui é o erro tolerável: deixa de apontar sobrepreço que existe,
    em vez de apontar sobrepreço que não existe.
    """
    alvo = " ".join((descricao or "").upper().split())[:60]
    if len(alvo) < 12:
        return []
    return [dict(r) for r in _linhas(con, """
        SELECT certame, item, valor_homologado, fornecedor_cnpj
        FROM pncp_resultado
        WHERE UPPER(item) LIKE ? AND COALESCE(valor_homologado,0) > 0
        LIMIT ?
    """, (f"%{alvo}%", limite))]


def montar_contexto(con: sqlite3.Connection, certame: str) -> dict[str, Any]:
    """Contexto do certame. Chave ausente = dado ausente — nunca preenchida por estimativa."""
    cab = _cabecalho(con, certame)
    edital = _edital(con, certame)
    propostas = _propostas(con, certame)
    clausulas = _clausulas(con, certame)
    itens = _itens(edital)

    ctx: dict[str, Any] = {
        "processo": certame,
        "id": certame,
        "orgao_cnpj": cab.get("orgao_cnpj") or edital.get("orgao_cnpj") or "",
        "orgao_contratante": cab.get("orgao_nome") or "",
        "modalidade": cab.get("modalidade") or "",
        "objeto": edital.get("objeto") or cab.get("objeto") or "",
        "data_publicacao": cab.get("data_pub") or "",
        # Desligados de propósito: caros e não pertinentes ao eixo certame.
        "usar_rede": False, "geocode": False, "usar_beneficios": False,
    }

    if propostas:
        ctx["propostas"] = propostas
        ctx["licitantes"] = [p["cnpj"] for p in propostas]
        ctx["licitantes_inscritos"] = [p["cnpj"] for p in propostas]
        ctx["licitantes_classificados"] = [p["cnpj"] for p in propostas
                                           if p.get("classificacao") is not None]
        vencedor = next((p for p in propostas if p.get("classificacao") == 1), None)
        if vencedor:
            ctx["vencedor_cnpj"] = vencedor["cnpj"]
            ctx["valor_homologado"] = vencedor["valor"]
        ctx["resultado"] = {"propostas": propostas,
                            "n_licitantes": len(propostas),
                            "vencedor": (vencedor or {}).get("cnpj")}

    if edital.get("valor_estimado") is not None:
        ctx["valor_estimado"] = edital["valor_estimado"]
    if edital.get("texto"):
        ctx["tr_texto"] = edital["texto"]
        ctx["texto_habilitacao"] = edital["texto"]
    if clausulas:
        ctx["clausulas_edital"] = clausulas
        # E1 lê exigências de habilitação; o eixo já vem classificado pelo extrator de cláusulas.
        hab = [c for c in clausulas if (c.get("eixo") or "").lower().startswith("habilit")]
        if hab:
            ctx["exigencias_habilitacao"] = hab
    if itens:
        ctx["itens"] = itens
        ctx["lotes"] = [{"id": str(i.get("numero") or n),
                         "itens": [i]} for n, i in enumerate(itens, 1)]
        cat = {str(i.get("numero") or n): i.get("catmat")
               for n, i in enumerate(itens, 1) if i.get("catmat")}
        if cat:
            ctx["catmat_por_item"] = cat
        principal = itens[0].get("descricao") or ""
        serie = _serie_do_item(con, principal)
        if len(serie) >= 3:
            ctx["item"] = principal
            ctx["registros"] = serie
    return ctx
