# -*- coding: utf-8 -*-
"""Dígitos verificadores de CPF e CNPJ — fonte única (só `re`, importável por qualquer módulo).

O mesmo algoritmo módulo 11 estava copiado em nucleo/dossie, qualidade/catracas, qualidade/verificadores,
sei/cotacoes_acervo, padroes/compra_fora_do_siafe, processo_360 e anomalias, com bordas diferentes (aceita
pontuação ou não, `None`, repetidos). Aqui: pontuação é ignorada, vazio/`None` e sequência de um dígito só são
inválidos. `cerebro_fts` mantém cópia de propósito (não importa nada do JFN: roda igual nas duas máquinas).
"""
from __future__ import annotations

import re

_P_CNPJ = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def cnpj_valido(cnpj) -> bool:
    n = digitos(cnpj)
    if len(n) != 14 or len(set(n)) == 1:
        return False
    for tam, pesos in ((12, _P_CNPJ), (13, (6,) + _P_CNPJ)):
        r = sum(int(d) * p for d, p in zip(n[:tam], pesos)) % 11
        if int(n[tam]) != (0 if r < 2 else 11 - r):
            return False
    return True


def cpf_valido(cpf) -> bool:
    n = digitos(cpf)
    if len(n) != 11 or len(set(n)) == 1:
        return False
    for tam in (9, 10):
        s = sum(int(n[i]) * (tam + 1 - i) for i in range(tam))
        if (s * 10 % 11) % 10 != int(n[tam]):
            return False
    return True
