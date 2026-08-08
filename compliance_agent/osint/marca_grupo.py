# -*- coding: utf-8 -*-
"""Marca aparente e grupo econômico — fonte ÚNICA para elos_ocultos e cocontato_certame.

POR QUE UM MÓDULO SÓ. Até 2026-08-08 havia DUAS cópias de `_marca`/`_GENERICAS` — uma em
`tools/elos_ocultos.py`, outra em `compliance_agent/osint/cocontato_certame.py` — com listas de
genéricas DIFERENTES e o mesmo bug: marca de 2 letras (como "OI") era pulada pelo limiar de
comprimento, e o boilerplate jurídico que sobrava ("EM RECUPERAÇÃO JUDICIAL") virava a marca. Nos
dois consumidores isso poluía a fila: elo oculto e conluio de certame passavam a listar empresas do
MESMO grupo (OI S.A. × OI MÓVEL) como se fossem vínculo suspeito. Duas cópias de uma função
sutilmente errada é convite para a terceira divergir — por isso a lógica passou a viver aqui, e as
duas a importam.

REGRA CONSERVADORA: marcar "mesmo grupo" à toa ESCONDE um elo/conluio real da fila do fiscal. Por
isso o agrupamento exige marca distintiva coincidente OU prefixo de tokens com o PRIMEIRO token
igual — nunca uma palavra genérica sozinha.
"""
from __future__ import annotations

import re
import unicodedata

# Genéricas = o que NÃO distingue uma empresa: forma jurídica, ramo, boilerplate de situação
# cadastral, palavras-tipo e preposições. União das duas listas históricas + o que a medição de
# 2026-08-08 mostrou virar falsa marca.
_GENERICAS = frozenset({
    # ramo / atividade
    "COMERCIO", "COMERCIAL", "SERVICOS", "SERVICO", "INDUSTRIA", "DISTRIBUIDORA", "SOLUCOES",
    "SOLUCAO", "EMPREENDIMENTOS", "CONSTRUTORA", "ENGENHARIA", "PARTICIPACOES", "TECNOLOGIA",
    "ASSOCIACAO", "INSTITUTO", "CENTRO", "CLINICA", "MEDICOS", "MEDICA", "LABORATORIO",
    "TRANSPORTES", "IMPORTACAO", "EXPORTACAO", "PRODUTOS", "EQUIPAMENTOS", "MATERIAIS",
    "APOIO", "ESCOLA", "ESCOLAR", "UNIDADES", "UNIDADE", "GESTAO", "ADMINISTRACAO",
    # adjetivos-tipo — não são marca
    "GERAIS", "GERAL", "INTEGRADA", "INTEGRADAS", "INTEGRADO", "INTEGRADOS",
    "TERCEIRIZADOS", "TERCEIRIZADA", "TECNICOS", "TECNICA", "ESPECIALIZADA",
    # forma jurídica
    "LTDA", "EIRELI", "SOCIEDADE", "GRUPO", "EPP", "ME", "SA", "CIA", "COMPANHIA", "EMPRESA",
    # boilerplate de situação cadastral — situação não distingue empresa
    "RECUPERACAO", "JUDICIAL", "EXTRAJUDICIAL", "LIQUIDACAO", "FALENCIA", "FALIDA", "MASSA",
    # geográficas amplas
    "BRASIL", "RIO", "NACIONAL",
    # preposições / artigos curtos
    "EM", "NA", "NO", "DA", "DE", "DO", "AS", "OS", "DAS", "DOS", "COM", "PARA", "POR",
})


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z ]", " ", s).upper()


def marca(razao: str) -> str:
    """Primeira palavra distintiva (≥3 letras, não genérica). Vazio se não houver."""
    for p in norm(razao).split():
        if len(p) >= 3 and p not in _GENERICAS:
            return p
    return ""


def tokens_distintivos(razao: str) -> list[str]:
    """Tokens distintivos na ordem (sem genéricas, ≥2 letras) — para comparar por prefixo."""
    return [p for p in norm(razao).split() if len(p) >= 2 and p not in _GENERICAS]


def mesmo_grupo(razao_a: str, razao_b: str) -> str:
    """Marca comum aparente, ou vazio. Duas vias, ambas conservadoras.

    1. MESMA MARCA: a primeira palavra distintiva (≥3) coincide — o caso comum.
    2. PREFIXO DE TOKENS: os tokens distintivos de uma são prefixo dos da outra e o primeiro
       coincide — pega matriz/subsidiária de marca curta ("OI" ⊂ "OI MÓVEL") que o limiar de 3
       letras deixava passar. O primeiro token tem de coincidir, senão "SERVIÇOS X" e "SERVIÇOS Y"
       (SERVIÇOS é genérica e some dos tokens) uniriam meia base.
    """
    ma, mb = marca(razao_a), marca(razao_b)
    if ma and ma == mb:
        return ma
    ta, tb = tokens_distintivos(razao_a), tokens_distintivos(razao_b)
    if ta and tb and ta[0] == tb[0]:
        curto, longo = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        if longo[: len(curto)] == curto:
            return curto[0]
    return ""
