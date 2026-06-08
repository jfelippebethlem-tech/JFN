# -*- coding: utf-8 -*-
"""Varredor de direcionamento — JFN 2.0, Onda 5. "Uma vez lido, buscar direcionamento."

Varre o corpus de editais e RANQUEIA por indícios de direcionamento. Duas fontes:
  • PNCP (API pública) — editais por UF/órgão;
  • SEI-RJ via login interno **itkava/ITERJ** (`collectors/sei_cdp.ler_processo_sei`, que
    vence o WAF de fingerprint e resolve o CAPTCHA por OCR) — lê os processos das OBs.
Em ambas: extrai os campos por schema (`sei_extract`), roda os red flags do Lex
(R3/R5/R7/R9/R12) sobre o texto real, indexa no corpus FTS5 (`sei_corpus`).

Honesto: indício de direcionamento/restrição a verificar (presunção de legitimidade), nunca
acusação. Cada achado vem com os trechos/exigências que o sustentam. Se o SEI não autenticar
(WAF/CAPTCHA/sem SEI_PASS), o item reporta o erro — nunca fabrica conteúdo.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_DB = Path(__file__).resolve().parent.parent / "data" / "compliance.db"


def _sei_numeros(ug: str | None, limite: int) -> list[str]:
    """Números SEI plausíveis das OBs (opcionalmente de uma UG), p/ leitura via itkava."""
    if not _DB.exists():
        return []
    con = sqlite3.connect(str(_DB))
    try:
        where = "numero_sei IS NOT NULL AND LENGTH(numero_sei) >= 10 AND numero_sei LIKE '%/%'"
        params: list = []
        if ug:
            where += " AND ug_codigo = ?"
            params.append(ug)
        rows = con.execute(
            f"SELECT numero_sei, COUNT(*) c FROM ordens_bancarias WHERE {where} "
            f"GROUP BY numero_sei ORDER BY c DESC LIMIT ?", (*params, limite)).fetchall()
    finally:
        con.close()
    # mantém só os que parecem nº de processo (tem dígitos e barra de ano)
    return [r[0] for r in rows if re.search(r"\d{2,}.*/\d{4}", r[0] or "")]


async def _varrer_sei(ug: str | None, max_itens: int) -> list[dict]:
    """Lê processos SEI via login interno itkava e roda extração + red flags. Honesto em erro."""
    from compliance_agent.collectors.sei_cdp import ler_processo_sei
    from compliance_agent.lex import analisar_texto_edital
    from compliance_agent.sei_extract import extrair
    from compliance_agent import sei_corpus

    out: list[dict] = []
    for numero in _sei_numeros(ug, max_itens):
        try:
            integra = await ler_processo_sei(numero)
        except Exception as e:  # noqa: BLE001
            out.append({"ref": numero, "fonte": "SEI/itkava", "erro": str(e), "score": 0, "red_flags": []})
            continue
        texto = (integra.get("texto", "") or "") + "\n" + "\n".join(
            d.get("conteudo", "") for d in (integra.get("conteudo_documentos", []) or []))
        if not texto.strip():
            out.append({"ref": numero, "fonte": "SEI/itkava", "score": 0, "red_flags": [],
                        "erro": integra.get("erro") or "INDISPONÍVEL: sem texto (WAF/CAPTCHA/login)"})
            continue
        campos = extrair(texto)
        achados = analisar_texto_edital(texto, numero=numero).get("achados", [])
        sei_corpus.indexar(numero, texto, objeto=campos.get("objeto", ""), meta="SEI/itkava")
        out.append({
            "ref": numero, "fonte": "SEI/itkava",
            "objeto": campos.get("objeto"), "modalidade": campos.get("modalidade"),
            "score": sum(a.get("grav", 0) for a in achados),
            "red_flags": [{"rf": a["rf"], "grav": a["grav"], "obs": a["obs"]} for a in achados],
            "exigencias": campos.get("exigencias_habilitacao", []),
        })
    return out


async def varrer_direcionamento(uf: str = "RJ", ug: str | None = None, objeto: str | None = None,
                                max_itens: int = 8, dias: int = 30, fonte: str = "pncp") -> dict:
    """Busca editais/processos, analisa e ranqueia por indícios de direcionamento.

    fonte: 'pncp' (editais públicos) | 'sei' (processos das OBs via login itkava/ITERJ) |
    'ambos'. Retorna {ok, fonte, n_analisados, processos:[{ref, objeto, modalidade, valor,
    score, red_flags, exigencias}], _fonte, _nota}. max_itens limita o nº de leituras.
    """
    from datetime import date, timedelta

    from compliance_agent.collectors import pncp
    from compliance_agent.lex import analisar_texto_edital
    from compliance_agent.sei_extract import extrair
    from compliance_agent import sei_corpus

    processos = []
    analisados = 0

    # Fonte SEI (login interno itkava) — lê os processos das OBs
    if fonte in ("sei", "ambos"):
        sei = await _varrer_sei(ug, max_itens)
        analisados += len(sei)
        processos.extend(sei)

    # Fonte PNCP (API pública)
    contratacoes = []
    if fonte in ("pncp", "ambos"):
        hoje = date.today()
        contratacoes = await pncp.buscar_contratacoes(
            uf=uf, data_ini=hoje - timedelta(days=dias), data_fim=hoje,
            orgao_cnpj=(ug or None), max_paginas=1)
        if objeto:
            alvo = objeto.lower()
            contratacoes = [c for c in contratacoes if alvo in (c.get("objeto") or "").lower()]
    for c in contratacoes[:max_itens]:
        ref = c.get("id_pncp")
        if not ref:
            continue
        docs = await pncp.baixar_documentos(ref, max_arquivos=2)
        texto = "\n".join(d.get("texto", "") for d in docs)
        if not texto.strip():
            continue
        analisados += 1
        campos = extrair(texto)
        analise = analisar_texto_edital(texto, numero=ref)
        achados = analise.get("achados", [])
        score = sum(a.get("grav", 0) for a in achados)
        sei_corpus.indexar(ref, texto, objeto=campos.get("objeto", ""), meta=c.get("modalidade", ""))
        processos.append({
            "ref": ref, "fonte": "PNCP",
            "objeto": campos.get("objeto") or (c.get("objeto") or "")[:120],
            "modalidade": campos.get("modalidade") or c.get("modalidade"),
            "valor": c.get("valor"),
            "score": score,
            "red_flags": [{"rf": a["rf"], "grav": a["grav"], "obs": a["obs"]} for a in achados],
            "exigencias": campos.get("exigencias_habilitacao", []),
            "link": c.get("link"),
        })

    processos.sort(key=lambda p: -p.get("score", 0))
    return {
        "ok": True,
        "fonte": fonte,
        "n_analisados": analisados,
        "processos": processos,
        "_fonte": ("SEI-RJ (login itkava/ITERJ) + " if fonte in ("sei", "ambos") else "")
                  + "PNCP (editais) + extração por schema + motor Lex R1–R12",
        "_nota": ("Indício de direcionamento/restrição a verificar (presunção de legitimidade), "
                  "nunca acusação. Ranqueado por gravidade dos red flags sobre o texto lido. "
                  "Itens SEI sem texto = WAF/CAPTCHA/login não vencido (reportado, nunca fabricado)."),
    }
