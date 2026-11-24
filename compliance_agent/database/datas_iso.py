# -*- coding: utf-8 -*-
"""Datas do SIAFE em TEXTO 'DD/MM/AAAA' → coluna gerada `<col>_iso` 'AAAA-MM-DD' (O4.3, Esteira Única, 24/11/2026).

POR QUE: `ob_orcamentaria_siafe.data_emissao` (e NE/NL) chegam do SIAFE como texto 'DD/MM/AAAA'. `ORDER BY`,
`MIN`/`MAX` e `<`/`>` sobre o texto cru comparam o DIA primeiro: '31/12/2025' > '02/01/2026'. Já errou num
parecer (lição `data-emissao-siafe-e-texto`). A coluna gerada VIRTUAL não ocupa disco, não muda o dado de
origem e aceita índice; texto fora do formato vira NULL (nunca uma data inventada).

Quem cria a coluna no banco existente é a revisão Alembic `0002_datas_iso` (cópia congelada da expressão
abaixo — `tests/test_regra_data_texto.py` confere que as duas não divergem). As DDLs de criação das tabelas
(`siafe_ob_orcamentaria`, `siafe_documento`) usam `coluna_gerada()` para que banco novo já nasça com ela.
A catraca `tests/test_regra_data_texto.py` barra ORDER BY/MIN/MAX/comparação sobre o texto cru.
"""
from __future__ import annotations

# Só o formato exato vira data; o resto é NULL (INDISPONÍVEL ≠ data).
GLOB_DD_MM_AAAA = "[0-3][0-9]/[0-1][0-9]/[12][0-9][0-9][0-9]"

# tabela → coluna texto que ganha `<col>_iso` (e índice `ix_<tabela>_<col>_iso`)
COLUNAS_ISO: dict[str, str] = {
    "ob_orcamentaria_siafe": "data_emissao",
    "ne_siafe": "data_emissao",
    "nl_siafe": "data_emissao",
}


def expr_iso(col: str) -> str:
    """Expressão SQL determinística: 'DD/MM/AAAA' → 'AAAA-MM-DD'; fora do formato → NULL."""
    return (f"CASE WHEN {col} GLOB '{GLOB_DD_MM_AAAA}' "
            f"THEN substr({col},7,4)||'-'||substr({col},4,2)||'-'||substr({col},1,2) END")


def coluna_gerada(col: str) -> str:
    """Trecho de DDL da coluna gerada (para CREATE TABLE e ALTER TABLE ADD COLUMN)."""
    return f"{col}_iso TEXT GENERATED ALWAYS AS ({expr_iso(col)}) VIRTUAL"


def nome_indice(tabela: str, col: str) -> str:
    return f"ix_{tabela}_{col}_iso"
