# -*- coding: utf-8 -*-
"""Âncora setorial (Task 1.4): quem presta serviço REGULADO deve constar no cadastro do regulador.

CNAE de saúde sem CNES, transportadora sem RNTRC, indústria farma sem ANVISA, escola fora do INEP —
empresa contratada para serviço regulado e AUSENTE do cadastro obrigatório é indício forte de que
não presta o serviço (fantasma setorial). O `objeto` do contrato pode forçar o regulador mesmo com
CNAE genérico (ex.: CNAE de "consultoria" contratada para "serviços hospitalares" → cobra CNES).

HONESTIDADE: consulta dumps LOCAIS (data/cnes.db etc. — download documentado em
tools/baixar_ancoras_setoriais.sh). Dump ausente → presente=None (INDISPONÍVEL), NUNCA False sem
dado; False (risco alto) só com o dump na mão e o CNPJ fora dele.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent

# Prefixo de CNAE (dígitos; o mais longo ganha) → cadastro regulatório onde a empresa DEVE constar.
_CNAE_REGULADOR = {
    # Saúde (divisões 861-866/869) + farmácia de varejo → CNES (Cadastro Nacional de Estab. de Saúde)
    "861": "CNES", "862": "CNES", "863": "CNES", "864": "CNES", "865": "CNES",
    "866": "CNES", "869": "CNES", "4771": "CNES",
    # Transporte rodoviário de carga → RNTRC (ANTT)
    "4930": "RNTRC",
    # Indústria farma (21xx), atacado de medicamentos (4644) / cosméticos-saneantes (4645),
    # indústria de alimentos (ex.: 1091 panificação industrial) → ANVISA
    "21": "ANVISA", "4644": "ANVISA", "4645": "ANVISA", "1091": "ANVISA",
    # Educação (divisão 85) → INEP (censo escolar / e-MEC)
    "85": "INEP",
}

# Palavras-chave no OBJETO do contrato que forçam o regulador mesmo com CNAE genérico.
_OBJETO_REGULADOR: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)hospital|sa[uú]de|cl[ií]nic|m[eé]dic|enfermag|ambulat[oó]ri"), "CNES"),
    (re.compile(r"(?i)transporte\s+(rodovi[aá]rio\s+)?de\s+cargas?|frete\b"), "RNTRC"),
    (re.compile(r"(?i)medicament|farmac[eê]utic|saneante|insumo\s+farmac"), "ANVISA"),
    (re.compile(r"(?i)escola|ensino|educa[cç][aã]o|creche"), "INEP"),
]

# Regulador → (arquivo de dump local em data/, tabela). Colunas mínimas: cnpj, nome, municipio, uf.
_DUMPS = {
    "CNES": ("cnes.db", "cnes_estabelecimentos"),
    "RNTRC": ("antt.db", "antt_transportadores"),
    "ANVISA": ("anvisa.db", "anvisa_estabelecimentos"),
    "INEP": ("inep.db", "inep_escolas"),
}


def _regulador_por_cnae(cnae: str) -> str | None:
    d = re.sub(r"\D", "", str(cnae or ""))
    if not d:
        return None
    for pref in sorted(_CNAE_REGULADOR, key=len, reverse=True):
        if d.startswith(pref):
            return _CNAE_REGULADOR[pref]
    return None


def _regulador_por_objeto(objeto: str) -> str | None:
    for rx, reg in _OBJETO_REGULADOR:
        if rx.search(objeto or ""):
            return reg
    return None


def checar_ancora(cnpj: str, cnae: str, objeto: str = "", db_path: str | None = None) -> dict:
    """→ {esperado_em: 'CNES'|'RNTRC'|'ANVISA'|'INEP'|None, presente: bool|None, fonte, detalhe,
    risco}. presente=None = INDISPONÍVEL (dump não baixado/ilegível) — nunca False sem dado."""
    reg = _regulador_por_cnae(cnae) or _regulador_por_objeto(objeto)
    if reg is None:
        return {"esperado_em": None, "presente": None, "fonte": "", "risco": None,
                "detalhe": "CNAE/objeto sem cadastro regulatório mapeado"}
    arquivo, tabela = _DUMPS[reg]
    path = Path(db_path) if db_path else _REPO / "data" / arquivo
    if not path.exists():
        return {"esperado_em": reg, "presente": None, "fonte": str(path), "risco": None,
                "detalhe": f"dump {reg} não baixado (ver tools/baixar_ancoras_setoriais.sh)"}
    d = re.sub(r"\D", "", str(cnpj or ""))
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute(f"SELECT 1 FROM {tabela} WHERE cnpj=? LIMIT 1", (d,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error as e:
        return {"esperado_em": reg, "presente": None, "fonte": str(path), "risco": None,
                "detalhe": f"dump {reg} ilegível ({e}) — INDISPONÍVEL"}
    if row:
        return {"esperado_em": reg, "presente": True, "fonte": str(path), "risco": "baixo",
                "detalhe": f"CNPJ consta no cadastro {reg}"}
    return {"esperado_em": reg, "presente": False, "fonte": str(path), "risco": "alto",
            "detalhe": (f"atividade regulada ({reg}) e CNPJ AUSENTE do cadastro — indício de que "
                        "não presta o serviço contratado")}
