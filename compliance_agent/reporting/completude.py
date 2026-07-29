# -*- coding: utf-8 -*-
"""Completude do entregável — quem corta, DECLARA.

Nasceu da auditoria de 2026-07-29: os relatórios traziam ~20 cortes silenciosos (`[:10]`..`[:120]`)
exatamente nas seções que mais importam — cartel, laranja, rede societária, contratos por
fornecedor. O leitor via 15 linhas e não tinha como saber que havia 60. Pior: um dos cortes era
`LIMIT 50` na própria consulta (`inteligencia_orgao.py`), de modo que o relatório nem sabia quantos
haviam ficado de fora.

A diretriz do dono é "sem corte": o documento é do tamanho que a verdade exigir. Onde o corte for
mesmo inevitável (uma tabela de 5.000 linhas não é leitura, é anexo), ele passa por
`top_declarado()`, que devolve a nota dizendo quantos ficaram e onde achá-los.

Uso:
    for ob in tudo(obs):                      # não corta, e diz isso ao leitor do código
        ...
    vistos, nota = top_declarado(obs, 20, "ordens bancárias", onde="na planilha XLSX anexa")
    md.append(nota)                           # "" quando não houve corte
"""
from __future__ import annotations

from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")

__all__ = ["tudo", "top_declarado", "campo"]


def campo(valor: object, largura: int, vazio: str = "—") -> str:
    """Trunca uma CÉLULA marcando o corte com reticência. Nunca corta em silêncio.

    `objeto[:45]` produzia "Fornecimento de medicamentos para a rede públ" — que o leitor lê como
    o objeto inteiro. Com a reticência ele ao menos sabe que precisa ir ao anexo.
    """
    txt = ("" if valor is None else str(valor)).strip().replace("\n", " ")
    if not txt:
        return vazio
    if largura and len(txt) > largura:
        return txt[:largura].rstrip() + "…"
    return txt


def tudo(itens: Iterable[T]) -> list[T]:
    """Materializa a coleção INTEIRA. Existe para tornar a ausência de corte explícita no código —
    `for x in tudo(itens)` é uma afirmação; `for x in itens` é um silêncio."""
    return list(itens)


def top_declarado(
    itens: Sequence[T],
    n: int,
    rotulo: str,
    *,
    onde: str = "",
    criterio: str = "maiores",
) -> tuple[list[T], str]:
    """Devolve `(os n primeiros, nota)`. A nota é `""` quando nada foi cortado.

    Args:
        itens: a coleção já ordenada pelo critério que o chamador quer exibir.
        n: quantos entram no corpo do documento.
        rotulo: o que são, no plural e em português ("ordens bancárias", "contratos").
        onde: para onde o leitor deve ir atrás do resto ("na planilha XLSX anexa").
        criterio: como os n foram escolhidos, para a nota não sugerir que são "os primeiros".

    A nota é markdown de bloco (`> _…_`), o mesmo formato que as seções já usam.
    """
    seq = list(itens)
    total = len(seq)
    if n is None or n <= 0 or total <= n:
        return seq, ""
    restantes = total - n
    destino = f" — {onde}" if onde else ""
    nota = (
        f"> _{n} {criterio} de {total} {rotulo}; **{restantes} não aparecem acima**{destino}._"
    )
    return seq[:n], nota
