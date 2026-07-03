# -*- coding: utf-8 -*-
"""Normalização de nomes de pessoas para casamento entre bases SEM CPF.

O cruzamento Câmara↔Prefeitura é feito por NOME (as duas bases públicas não expõem
CPF). Nome é chave fraca → homônimos. Este módulo centraliza a normalização honesta
(sem inventar identidade) usada pelo matcher; a decisão de "é a mesma pessoa" fica no
``cruzamento.py`` com níveis de confiança, nunca aqui.
"""
from __future__ import annotations

import re
import unicodedata

# Partículas que não ajudam a distinguir pessoas (de/da/dos/...). NÃO removemos do
# nome exibido; só as ignoramos ao gerar a chave de blocagem por iniciais.
_PARTICULAS = {"DE", "DA", "DO", "DAS", "DOS", "E"}


def sem_acento(texto: str) -> str:
    """Remove acentos via decomposição unicode (NFKD). 'FÁTIMA' -> 'FATIMA'."""
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalizar(nome: str) -> str:
    """Chave canônica de um nome: sem acento, MAIÚSCULO, só letras/espaço, 1 espaço.

    Determinística e reversível o suficiente para casar 'José  da Silva ' com
    'JOSE DA SILVA'. NÃO decide identidade — só canoniza a string.
    """
    # Remove indicadores ordinais ANTES do NFKD (º/ª decompõem para 'o'/'a' e sujariam o nome).
    limpo = re.sub(r"[ºª°]", " ", nome or "")
    base = sem_acento(limpo).upper()
    base = re.sub(r"[^A-Z\s]", " ", base)      # tira pontuação, dígitos, etc.
    base = re.sub(r"\s+", " ", base).strip()
    return base


def tokens_significativos(nome: str) -> list[str]:
    """Tokens do nome sem as partículas (de/da/dos...). Base para heurística de match."""
    return [t for t in normalizar(nome).split() if t not in _PARTICULAS]


def chave_blocagem(nome: str) -> str:
    """Chave de blocagem: primeiro + último token significativo.

    Reduz o espaço de comparação (não compara todo mundo com todo mundo) mantendo
    quem tem primeiro e último nome iguais no mesmo bloco. Homônimos caem juntos —
    é justamente onde o matcher precisa olhar com cuidado.
    """
    toks = tokens_significativos(nome)
    if not toks:
        return ""
    if len(toks) == 1:
        return toks[0]
    return f"{toks[0]} {toks[-1]}"
