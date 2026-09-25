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


# Forma jurídica, situação cadastral e preposições — o que pode sobrar numa razão social que é
# SÓ a sigla ("OI S.A. - EM RECUPERAÇÃO JUDICIAL"). Ramo/atividade fica de fora de propósito:
# "JS CONSTRUTORA" não é "só a sigla JS" — é uma construtora cujas iniciais coincidem à toa.
_FORMA_OU_SITUACAO = frozenset({
    "LTDA", "EIRELI", "SOCIEDADE", "GRUPO", "EPP", "ME", "SA", "CIA", "COMPANHIA", "EMPRESA",
    "RECUPERACAO", "JUDICIAL", "EXTRAJUDICIAL", "LIQUIDACAO", "FALENCIA", "FALIDA", "MASSA",
    "EM", "NA", "NO", "DA", "DE", "DO", "AS", "OS", "DAS", "DOS", "COM", "PARA", "POR",
})


def _so_sigla(razao: str, sigla: str) -> bool:
    """A razão social é apenas a sigla + forma jurídica/situação (ex.: "OI S.A. EM REC. JUD.")."""
    toks = norm(razao).split()
    return bool(toks) and toks[0] == sigla and all(
        len(t) < 2 or t in _FORMA_OU_SITUACAO for t in toks[1:])


def mesmo_grupo(razao_a: str, razao_b: str) -> str:
    """Marca comum aparente, ou vazio. Vias conservadoras — agrupar à toa esconde elo real.

    1. MESMA MARCA: a primeira palavra distintiva (≥3) coincide — o caso comum.
    2. SIGLA (2 letras) coincidindo, só em dois desenhos medidos no acervo real (2026-08-08):
       a. MARCA COMPOSTA: o segundo token BRUTO também coincide — "CS BRASIL FROTAS" ×
          "CS BRASIL TRANSPORTES…" (a marca é "CS BRASIL"; "BRASIL" sozinha é genérica).
       b. MATRIZ SÓ-SIGLA: um dos nomes é apenas a sigla + forma jurídica e os tokens distintivos
          de um são prefixo dos do outro — "OI S.A." ⊂ "OI MÓVEL S.A.". Sem essa exigência,
          "JS COMERCIO…" × "JS CONSTRUTORA" agrupava por iniciais — e iniciais coincidem à toa.
    3. PREFIXO DE TOKENS (primeiro token ≥3 igual): matriz/subsidiária de marca normal.
    """
    ma, mb = marca(razao_a), marca(razao_b)
    if ma and ma == mb:
        return ma
    ta, tb = tokens_distintivos(razao_a), tokens_distintivos(razao_b)
    if not (ta and tb and ta[0] == tb[0]):
        return ""
    sigla = ta[0]
    if len(sigla) == 2:
        ra, rb = norm(razao_a).split(), norm(razao_b).split()
        if len(ra) > 1 and len(rb) > 1 and ra[1] == rb[1]:
            return f"{sigla} {ra[1]}"
        if not (_so_sigla(razao_a, sigla) or _so_sigla(razao_b, sigla)):
            return ""
    curto, longo = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if longo[: len(curto)] == curto:
        return curto[0]
    return ""
