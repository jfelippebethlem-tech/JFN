# -*- coding: utf-8 -*-
"""Resolução probabilística de CPF mascarado (QSA) → CPF completo, via (nome + 6 dígitos do meio).

Técnica adotada do **br-acc** (`scripts/link_partners_probable.cypher`): o CPF do QSA público vem
mascarado como `***.XXX.XXX-**`, o que **expõe os 6 dígitos do MEIO** do CPF (posições 4-9). Cruzando
(nome exato + esses 6 dígitos) contra um corpus de CPFs COMPLETOS já conhecidos (favorecidos pessoa
física nas OBs — `favorecido_cpf`/`favorecido_nome`), quando o par é **ÚNICO** temos uma ponte de
identidade de alta precisão. É a semente da resolução de entidade (roadmap P0) e destrava as consultas
por CPF (ex.: benefício social de subsistência — H-BENEFICIO do motor de DD) para sócios mascarados.

HONESTIDADE (regra-mãe): ponte NÃO factual (confiança ≈0,85, à la br-acc) — só retorna em match **1:1**
(um único CPF para aquele `nome+middle6`); ambiguidade ou ausência → vazio = INDISPONÍVEL, nunca chute.
LGPD: o CPF completo é de **uso interno** (apenas para consultar fontes); nos produtos o CPF sai mascarado.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

_DB = Path("data") / "compliance.db"


def _digitos(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _norm(s: str) -> str:
    s = (s or "").upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def middle6(doc_mascarado) -> str:
    """6 dígitos do meio do CPF a partir do doc mascarado do QSA (`***.XXX.XXX-**` → 'XXXXXX') ou ''.

    Só considera máscara padrão (contém '*'); um doc com 11 dígitos limpos NÃO é máscara (use-o direto)."""
    s = str(doc_mascarado or "")
    if "*" not in s:
        return ""
    d = _digitos(s)
    return d if len(d) == 6 else ""


def resolver(nome: str, doc_mascarado: str, *, db_path: str | Path | None = None) -> dict:
    """Resolve um CPF mascarado p/ o CPF completo via (nome + middle6) ÚNICO no corpus de favorecidos PF.

    Retorna (honesto): {resolvido: bool, cpf: str|'', confianca: float, metodo, motivo}.
    Match 1:1 obrigatório; ambíguo/sem corpus/sem máscara → resolvido=False (INDISPONÍVEL, nunca chute).
    """
    base = {"resolvido": False, "cpf": "", "confianca": 0.0, "metodo": "nome+middle6", "motivo": ""}
    m6 = middle6(doc_mascarado)
    nome_n = _norm(nome)
    if not m6 or len(nome_n) < 6:
        return {**base, "motivo": "sem 6 dígitos do meio (máscara) ou nome curto"}
    p = Path(db_path or _DB)
    if not p.exists():
        return {**base, "motivo": "base de favorecidos indisponível"}
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            rows = con.execute(
                "SELECT DISTINCT favorecido_cpf, favorecido_nome FROM ordens_bancarias "
                "WHERE length(favorecido_cpf)=11 AND substr(favorecido_cpf,4,6)=?", (m6,)).fetchall()
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        return {**base, "motivo": f"erro DB: {str(e)[:40]}"}
    # filtro de nome em Python (accent-safe — o SQL upper() não normaliza acentos)
    cpfs = {cpf for cpf, nm in rows if cpf and _norm(nm) == nome_n}
    if len(cpfs) == 1:
        return {**base, "resolvido": True, "cpf": next(iter(cpfs)), "confianca": 0.85,
                "motivo": "par (nome + 6 díg do meio) único no corpus de favorecidos PF"}
    if len(cpfs) > 1:
        return {**base, "motivo": f"ambíguo ({len(cpfs)} CPFs p/ nome+6díg) — não resolve"}
    return {**base, "motivo": "sem correspondência no corpus de favorecidos PF"}


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Resolve CPF mascarado (nome + 6 díg do meio) → CPF completo")
    ap.add_argument("nome")
    ap.add_argument("doc", help="doc mascarado do QSA, ex.: ***912137**")
    a = ap.parse_args()
    out = resolver(a.nome, a.doc)
    if out.get("cpf"):  # mascara na saída do CLI (LGPD) — confirma só os 6 do meio
        out["cpf"] = "***" + out["cpf"][3:9] + "**"
    print(json.dumps(out, ensure_ascii=False, indent=2))
