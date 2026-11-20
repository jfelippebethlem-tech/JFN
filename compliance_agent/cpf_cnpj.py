# -*- coding: utf-8 -*-
"""Dígitos verificadores e máscara de CPF/CNPJ — fonte única (só `re`, importável por qualquer módulo).

O mesmo algoritmo módulo 11 estava copiado em nucleo/dossie, qualidade/catracas, qualidade/verificadores,
sei/cotacoes_acervo, padroes/compra_fora_do_siafe, processo_360 e anomalias, com bordas diferentes (aceita
pontuação ou não, `None`, repetidos). Aqui: pontuação é ignorada, vazio/`None` e sequência de um dígito só são
inválidos. `cerebro_fts` mantém cópia de propósito (não importa nada do JFN: roda igual nas duas máquinas).

A máscara de CPF (PAD-04) estava escrita em 9 módulos da raiz com DOIS formatos: `***.456.789-**` e
`123.***.***-01` (`pericia_contabil`, e `osint/vinculos` usado por `governo_couto`, `comissao_orcamento`,
`proveniencia_manchetes`). O mesmo CPF exibido nos dois formatos fica inteiro.
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


def mascarar_cpf(cpf) -> str:
    """Máscara PAD-04 (`config/qualidade_regras.yaml`): `***.456.789-**` — só os dígitos 4–9, os mesmos que o QSA
    da Receita publica. Outra janela (ex.: `123.***.***-01`) somada a esta revela o CPF inteiro."""
    d = digitos(cpf)
    return f"***.{d[3:6]}.{d[6:9]}-**"


def mascarar_doc(doc) -> str:
    """Documento para saída: 11 dígitos (CPF) mascarado; o resto sai como veio, em texto (CNPJ é público)."""
    return mascarar_cpf(doc) if len(digitos(doc)) == 11 else str(doc or "")


# 11 dígitos soltos, com ou sem a pontuação do CPF. Não confere o DV: celular com DDD sem separador também sai
# mascarado (aceito — vazar CPF é pior). MEI traz o CPF do titular colado ao nome empresarial.
_RE_CPF_TEXTO = re.compile(r"(?<!\d)(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?!\d)")


def mascarar_cpf_no_texto(texto) -> str:
    """Todo CPF dentro de um texto livre → máscara PAD-04."""
    return _RE_CPF_TEXTO.sub(lambda m: f"***.{m[2]}.{m[3]}-**", str(texto or ""))


def mascarar_payload(x):
    """Último passo antes de sair: todo texto de um payload (dict/list aninhados) passa pela máscara de CPF."""
    if isinstance(x, str):
        return mascarar_cpf_no_texto(x)
    if isinstance(x, dict):
        return {k: mascarar_payload(v) for k, v in x.items()}
    if isinstance(x, list):
        return [mascarar_payload(v) for v in x]
    return x
