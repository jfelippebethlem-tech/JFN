# -*- coding: utf-8 -*-
"""Resolvedor UG SIAFE → CNPJ do órgão no PNCP (F5.1 do dossiê mestre).

O índice de UG (`data/ug_index_siafe.json`) só tem NOME/SIGLA; o PNCP identifica o órgão por CNPJ
(`pncp_resultado.orgao_cnpj`/`orgao_nome`). Sem esta ponte, o /orgao (UG) não enxerga a avaliação
de conjunto dos certames (CNPJ). Resolução DETERMINÍSTICA por nome, em 3 métodos (nesta ordem):

  a) `sigla_no_nome`  — a sigla/nome da UG aparece como PALAVRA no orgao_nome do PNCP
                        (ex.: "ITERJ" em "INSTITUTO DE TERRAS E CARTOGRAFIA ... ITERJ");
  b) `acronimo`       — as iniciais das palavras significativas do orgao_nome formam a sigla da UG;
  c) `contencao`      — nome longo da UG contido no orgao_nome (ou vice-versa), ≥2 tokens.

Honesto: 2+ CNPJs distintos casando → None (ambíguo não vira palpite); nenhum match → None.
Nunca inventamos CNPJ em código — só o que a base do PNCP afirma."""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

from compliance_agent.emendas.db import _DB_PADRAO

_CONECTIVOS = {"DE", "DO", "DA", "DOS", "DAS", "E", "EM", "NO", "NA", "PARA", "A", "O"}
_cache_candidatos: list[tuple[str, str]] | None = None


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9 ]", " ", s.upper()).strip()


def _tokens(s: str) -> list[str]:
    return [t for t in _norm(s).split() if t and t not in _CONECTIVOS]


def _acronimo(nome: str) -> str:
    return "".join(t[0] for t in _tokens(nome))


def _candidatos(db_path=None) -> list[tuple[str, str]]:
    """(cnpj, orgao_nome) distintos das bases PNCP — cacheado por processo."""
    global _cache_candidatos
    if _cache_candidatos is not None and db_path is None:
        return _cache_candidatos
    p = Path(db_path) if db_path else _DB_PADRAO
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        vistos: dict[str, str] = {}
        for sql in ("SELECT DISTINCT orgao_cnpj, orgao_nome FROM pncp_resultado "
                    "WHERE orgao_cnpj IS NOT NULL AND orgao_nome IS NOT NULL",
                    "SELECT DISTINCT orgao_cnpj, orgao_nome FROM pcrj_licitacoes "
                    "WHERE orgao_cnpj IS NOT NULL AND orgao_nome IS NOT NULL"):
            try:
                for cnpj, nome in con.execute(sql):
                    vistos.setdefault(re.sub(r"\D", "", cnpj), nome)
            except sqlite3.OperationalError:
                continue  # tabela ausente nesta base — segue com o que houver
        out = sorted(vistos.items())
    finally:
        con.close()
    if db_path is None:
        _cache_candidatos = out
    return out


def resolver(ug_cod: str, nome_ug: str, db_path=None) -> dict | None:
    """Resolve a UG para {cnpj, orgao_nome, metodo}. None = sem match confiável (ambíguo/ausente)."""
    from compliance_agent.ugs import ALIASES

    nomes_alvo = [nome_ug or ""]
    alias = ALIASES.get(str(ug_cod)) or {}
    if alias.get("instituicao"):
        nomes_alvo.append(alias["instituicao"])
    nomes_alvo = [n for n in {_norm(n) for n in nomes_alvo} if n]
    if not nomes_alvo:
        return None

    # anti-FP aprendido no dado real (2026-07-20): "CENTRAL"/"PENSAO" casavam órgão federal aleatório
    # e {ESTADO,RIO,JANEIRO} do ente genérico tornava tudo ambíguo. Precisão > cobertura: melhor
    # NENHUM match que match errado num relatório.
    hits: dict[str, tuple[str, str]] = {}  # cnpj -> (orgao_nome, metodo)
    for cnpj, orgao_nome in _candidatos(db_path):
        toks_orgao = set(_tokens(orgao_nome))
        for alvo in nomes_alvo:
            toks_alvo = set(_tokens(alvo))
            alvo_compacto = alvo.replace(" ", "")  # "TCE RJ" (norm de TCE-RJ) → "TCERJ"
            sigla_forte = len(alvo) >= 5 or (len(alvo) == 4 and alvo.endswith("RJ"))
            if len(toks_alvo) >= 3 and toks_alvo == toks_orgao:
                hits[cnpj] = (orgao_nome, "nome_exato")
            elif (sigla_forte and " " not in alvo and alvo in toks_orgao
                  and ("RIO DE JANEIRO" in _norm(orgao_nome) or "ESTADO DO RIO" in _norm(orgao_nome))):
                # âncora de esfera: UG é do ERJ — sem "Rio de Janeiro" no nome do órgão, uma palavra
                # genérica ("CENTRAL", "PENSAO") casa com federal/outro município (FP real de 2026-07-20)
                hits.setdefault(cnpj, (orgao_nome, "sigla_no_nome"))
            elif len(alvo_compacto) >= 4 and _acronimo(orgao_nome) == alvo_compacto:
                hits.setdefault(cnpj, (orgao_nome, "acronimo"))
            elif (min(len(toks_alvo), len(toks_orgao)) >= 4
                  and (toks_alvo <= toks_orgao or toks_orgao <= toks_alvo)):
                hits.setdefault(cnpj, (orgao_nome, "contencao"))
    if not hits:
        return None
    # desempate por FORÇA do método (nome_exato > sigla > acrônimo > contenção): a ALERJ colide em
    # contenção com o próprio fundo de previdência dela, mas o nome_exato é único — vence. Empate
    # DENTRO do tier mais forte → ambíguo de verdade → None (sem palpite).
    forca = {"nome_exato": 0, "sigla_no_nome": 1, "acronimo": 2, "contencao": 3}
    melhor_tier = min(forca[m] for _, m in hits.values())
    top = [(c, nm, m) for c, (nm, m) in hits.items() if forca[m] == melhor_tier]
    if len(top) > 1 and melhor_tier == forca["contencao"]:
        # empate só em CONTENÇÃO: fica o candidato mais PRÓXIMO do alvo (menor diferença simétrica
        # de tokens) — "ALERJ por extenso" bate mais perto de "RIO DE JANEIRO ASSEMBLEIA LEGISLATIVA"
        # (Δ={ESTADO}) que do fundo de previdência dela (Δ={INSTITUTO,PREVIDENCIA}). Empate no mínimo
        # → ambíguo real → None.
        alvo_ref = max((set(_tokens(a)) for a in nomes_alvo), key=len)
        dist = sorted((len(set(_tokens(nm)) ^ alvo_ref), c, nm, m) for c, nm, m in top)
        if len(dist) > 1 and dist[0][0] == dist[1][0]:
            return None
        top = [dist[0][1:]]
    if len(top) != 1:
        return None
    cnpj, orgao_nome, metodo = top[0]
    return {"cnpj": cnpj, "orgao_nome": orgao_nome, "metodo": metodo}
