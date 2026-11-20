# -*- coding: utf-8 -*-
"""Leitura de célula de fonte — valor em reais e documento (CNPJ/CPF) — com UMA régua para os coletores.

Havia uma cópia por coletor (13 de valor, cada uma com uma semântica): umas tiravam "R$", outras não;
umas devolviam 0.0 quando a célula era ilegível, outras None; umas apagavam o ponto SEMPRE (formato BR
estrito), outras só quando havia vírgula (fonte que mistura "1.234,56" com número de API "1234.56").
Corrigir uma não corrigia as outras.

As duas réguas são DIFERENTES de propósito e o nome diz qual é qual:

- `valor_br`        — a fonte é planilha/tela brasileira: ponto é SEMPRE milhar ("1.234" = mil e
                      duzentos e trinta e quatro). Usar onde o arquivo é "1.234,56" por contrato.
- `valor_br_ou_ponto` — a fonte mistura número de API (float, ou "1234.56") com texto BR: o ponto só é
                      milhar quando há vírgula. "1.234" sem vírgula aqui vira 1.234 — por isso NÃO serve
                      para planilha BR.

Ambas devolvem **None** quando a célula não é número: ilegível é INDISPONÍVEL, não zero. O coletor que
historicamente grava 0.0 nesse caso escreve `valor_br(x) or 0.0` à vista — o defeito fica no chamador,
nomeado, e não escondido dentro do parser.
"""
from __future__ import annotations

import csv
import io
import re

# "R$", espaço e NBSP saem; o que sobra tem de ser número BR: dígitos com ponto de milhar e vírgula decimal.
_LIXO_DE_MOEDA = re.compile(r"R\$|\s")  # em str, \s já casa o NBSP
_NUMERO_BR = re.compile(r"-?[\d.]*\d(,\d*)?|-?,\d+")


def _numero_cru(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None   # v == v descarta NaN
    return None


def valor_br(texto) -> float | None:
    """'R$ 1.234,56' → 1234.56 · '1.234' → 1234.0 · '' / '-' / 'abc' → None. Ponto é sempre milhar."""
    n = _numero_cru(texto)
    if n is not None or isinstance(texto, (int, float)):
        return n
    s = _LIXO_DE_MOEDA.sub("", str(texto or ""))
    if not _NUMERO_BR.fullmatch(s):
        return None
    return float(s.replace(".", "").replace(",", "."))


def valor_br_ou_ponto(texto) -> float | None:
    """Número de API passa direto; texto com vírgula é BR ('7.188,00' → 7188.0); sem vírgula é ponto
    decimal ('1234.56' → 1234.56). None quando não é número (inclusive 'nan')."""
    n = _numero_cru(texto)
    if n is not None or isinstance(texto, (int, float)):
        return n
    s = _LIXO_DE_MOEDA.sub("", str(texto or ""))
    if "," in s:
        return valor_br(s)
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def so_digitos(texto) -> str:
    """'12.345.678/0001-90' → '12345678000190'. None vira ''."""
    return re.sub(r"\D", "", str(texto or ""))


def csv_apos_preambulo(texto: str, primeira_coluna: str, sep: str = ";") -> csv.DictReader:
    """CSV do TFE/SEFAZ: linhas de título ("Governo do Estado…", "Transparência Fiscal") antes do cabeçalho.
    Sem o cabeçalho, levanta ValueError. Antes as duas cópias caíam na linha 0: as linhas viravam
    dicionários sem as colunas esperadas e a falha virava dado — o `tfe_ob` pulava TODAS as OB (e o
    `ingest` apagava o exercício inteiro, registrando cada OB como "retirada pela fonte"); o `tfe_aberto`
    somava zeros."""
    linhas = texto.splitlines()
    for i, linha in enumerate(linhas):
        if linha.replace('"', "").strip().startswith(primeira_coluna):
            return csv.DictReader(io.StringIO("\n".join(linhas[i:])), delimiter=sep)
    raise ValueError(f"cabeçalho {primeira_coluna!r} não encontrado — a fonte mudou o layout ou não devolveu "
                     "o CSV (página de erro/bloqueio?)")
