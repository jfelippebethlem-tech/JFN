# -*- coding: utf-8 -*-
"""Emergência RECORRENTE — o art. 75, VIII exige imprevisibilidade, e ela não se repete 245 vezes.

POR QUE ISTO EXISTE. O sweep de fracionamento (`sweep_fracionamento_tcerj`) mede dispensa por
VALOR — soma contratações que, juntas, ultrapassam o teto do inciso II. Ele é cego para o outro
caminho de fuga à licitação, que na base do Estado é muito maior: a dispensa EMERGENCIAL do
inciso VIII, cujo teto é o próprio valor da urgência.

Medido em 2026-07-28, sobre `compras_diretas_tcerj`:

    contratações com objeto EMERGENCIAL ......... 1.638 · R$ 1.963.745.047,92
      FSERJ 2023 .................................. 245 · R$   392.350.345,76
      SEDSODH 2023 ................................ 471 · R$   121.557.667,80
      UERJ Hospital Universitário 2024 ............ 203 · R$   120.101.832,55

Apareceu ao avaliar o grupo de topo do sweep de fracionamento: SEDSODH/2024, cuja composição
real era **LOCALMED com 147 contratações emergenciais, R$ 8,5 milhões** — matéria do inciso
VIII, não do II. A régua de valor via o grupo e chamava de outra coisa.

O QUE ESTA RÉGUA NÃO FAZ. Não chama emergência de irregular: ela é instrumento legal, e um
hospital sem insumo precisa dela. O indício é a RECORRÊNCIA, e ela é medida — não presumida.
Emergência que se repete todo ano, sempre com o mesmo fornecedor, não descreve o imprevisível;
descreve planejamento ausente, que a jurisprudência do TCU trata como emergência fabricada
(desídia administrativa não legitima a dispensa).

O julgamento fino (o objeto era mesmo urgente? houve fato superveniente?) é do card P5 sobre o
processo. Aqui é a TRIAGEM em lote que diz onde olhar primeiro.
"""
from __future__ import annotations

import collections
import re

# O objeto do TCE-RJ vem em caixa alta e sem padronização; `emergenc` cobre emergencial,
# emergência e emergencia. `urgen` fica de fora de propósito: "atendimento de urgência" é
# NOME DE SERVIÇO de saúde, não fundamento de contratação — casá-lo encheria a fila de
# pronto-socorro contratado por licitação normal.
_RE_EMERGENCIA = re.compile(r"emergenc|emerg[êe]ncia", re.IGNORECASE)

RESSALVA = ("indício a apurar, não afirmação de irregularidade: a dispensa emergencial é "
            "legal (art. 75, VIII); o que se mede aqui é a RECORRÊNCIA, que o inciso não "
            "prevê — imprevisibilidade não se repete todo exercício")


def eh_emergencial(objeto: str | None) -> bool:
    return bool(_RE_EMERGENCIA.search(str(objeto or "")))


def agrupar_emergencias(linhas, *, minimo: int = 5) -> list[dict]:
    """Agrupa contratações EMERGENCIAIS por unidade × exercício.

    `linhas` = iterável de `(unidade, exercicio, fornecedor, valor, objeto)`.
    `minimo` = quantas emergências no mesmo exercício para o grupo virar indício. Uma
    emergência isolada é o uso legítimo do inciso; o padrão é o que interessa.

    Cada grupo traz o fornecedor DOMINANTE e a concentração nele: repetir emergência sempre
    com o mesmo contratado é fuga à licitação, enquanto emergências pulverizadas entre muitos
    fornecedores sugerem um serviço realmente sob pressão.
    """
    grupos: dict[tuple, dict] = {}
    for unidade, exercicio, fornecedor, valor, objeto in linhas or []:
        if not eh_emergencial(objeto):
            continue
        chave = (str(unidade or "?"), exercicio)
        g = grupos.setdefault(chave, {"unidade": chave[0], "exercicio": exercicio, "n": 0,
                                      "total": 0.0, "_por_forn": collections.Counter()})
        g["n"] += 1
        g["total"] += float(valor or 0)
        g["_por_forn"][str(fornecedor or "?")] += float(valor or 0)

    saida = []
    for g in grupos.values():
        if g["n"] < minimo:
            continue
        por_forn = g.pop("_por_forn")
        dominante, valor_dom = por_forn.most_common(1)[0]
        g["fornecedor_dominante"] = dominante
        g["n_fornecedores"] = len(por_forn)
        g["concentracao_dominante"] = round(valor_dom / g["total"], 4) if g["total"] else 0.0
        g["ressalva"] = RESSALVA
        saida.append(g)
    saida.sort(key=lambda g: -g["total"])
    return saida
