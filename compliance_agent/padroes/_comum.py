# -*- coding: utf-8 -*-
"""O que vale para TODAS as famílias de padrões (aditivos, pagamento/MROSC, carona): banco só-leitura, trecho literal
da prova, LGPD do credor e a ordem dos achados na saída. Os caches de data/padroes gravam com
`rotina_base.gravar_json` (temporário único: os detectores rodam em paralelo, um processo cada).

Cada família tem a sua leitura do acervo (`_aditivos_comum`, `_pagamento_comum`, `_carona_comum`); estas regras não
dependem de família e mudam juntas — por isso moram num lugar só.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DB = RAIZ / "data" / "compliance.db"
ORDEM_GRAU = {"forte": 0, "medio": 1, "fraco": 2}

_RE_CPF = re.compile(r"(?<!\d)(\d{3})\.?(\d{3})\.?(\d{3})-?(\d{2})(?!\d)")


def con_ro() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=60)


def mascarar_cpf(texto: str) -> str:
    """123.456.789-01 → ***.456.789-** (LGPD; nunca expor CPF inteiro)."""
    return _RE_CPF.sub(lambda m: f"***.{m[2]}.{m[3]}-**", texto or "")


def trecho(texto: str, ini: int, fim: int, folga: int) -> str:
    """Trecho literal em uma linha em volta de [ini, fim), CPF mascarado — para a prova."""
    a, b = max(0, ini - folga), min(len(texto), fim + folga)
    return mascarar_cpf(re.sub(r"\s+", " ", texto[a:b]).strip())


def eh_pessoa_fisica(documento) -> bool:
    return len(re.sub(r"\D", "", str(documento or ""))) == 11


def credor_publico(documento, nome: str | None) -> str | None:
    """Nome do credor que pode sair num achado: pessoa física (11 dígitos) sai omitida — LGPD (nome de PF só de agente
    público no exercício da função, e com prova). Nome de MEI/EI traz o CPF do titular ("NOME 12345678900", 11 dígitos colados ao nome): mascarado."""
    if not nome:
        return None
    return "pessoa física (nome omitido)" if eh_pessoa_fisica(documento) else mascarar_cpf(nome)


def documento_publico(documento):
    """CNPJ inteiro; CPF mascarado."""
    return mascarar_cpf(str(documento)) if eh_pessoa_fisica(documento) else documento


def ordenar(achados: list[dict]) -> list[dict]:
    """Ordem da saída: grau (forte → fraco), depois maior valor pago."""
    achados.sort(key=lambda a: (ORDEM_GRAU.get(a.get("grau"), 9), -(a.get("valor_pago_ob") or 0)))
    return achados
