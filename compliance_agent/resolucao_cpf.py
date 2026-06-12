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


def _match_indice(nome: str, doc_mascarado: str, idx: dict, rotulo: str, confianca: float = 0.85) -> dict:
    """Resolve (nome + 6 díg do meio) contra um índice pré-construído {(nome_norm, middle6) -> set(cpf)}.

    Mesmo contrato honesto de `resolver()` (match 1:1; ambíguo/sem match → resolvido=False), mas SEM SQL por
    chamada — para o sweep usar um índice carregado UMA vez e não fazer 1 full-scan por sócio (VM-safe, §8)."""
    base = {"resolvido": False, "cpf": "", "confianca": 0.0, "metodo": "nome+middle6", "motivo": ""}
    m6 = middle6(doc_mascarado)
    nome_n = _norm(nome)
    if not m6 or len(nome_n) < 6:
        return {**base, "motivo": "sem 6 dígitos do meio (máscara) ou nome curto"}
    cpfs = idx.get((nome_n, m6))
    if cpfs and len(cpfs) == 1:
        return {**base, "resolvido": True, "cpf": next(iter(cpfs)), "confianca": confianca,
                "motivo": f"par (nome + 6 díg do meio) único no {rotulo}"}
    if cpfs and len(cpfs) > 1:
        return {**base, "motivo": f"ambíguo ({len(cpfs)} CPFs p/ nome+6díg) — não resolve"}
    return {**base, "motivo": f"sem correspondência no {rotulo}"}


def carregar_indice_favorecidos(db_path: str | Path | None = None) -> dict:
    """Índice {(nome_norm, middle6) -> set(cpf)} dos FAVORECIDOS PF (`ordens_bancarias`, CPF completo).
    Espelha `carregar_indice_tse`: construído UMA vez p/ resolver muitos sócios no sweep SEM um full-scan de
    1,1M OBs por sócio (a query `substr(favorecido_cpf,4,6)` de `resolver()` não usa índice → custo de CPU).
    Passe-o como `pf_idx` em `resolver_multi`. Fonte legítima/interna (LGPD art. 7º,II/23)."""
    idx: dict = {}
    p = Path(db_path or _DB)
    if not p.exists():
        return idx
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            for cpf, nome in con.execute(
                    "SELECT DISTINCT favorecido_cpf, favorecido_nome FROM ordens_bancarias "
                    "WHERE length(favorecido_cpf)=11"):
                d = _digitos(cpf)
                if len(d) == 11:
                    idx.setdefault((_norm(nome), d[3:9]), set()).add(d)
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — tabela ausente / DB indisponível → índice vazio (honesto)
        return idx
    return idx


def carregar_indice_tse(db_path: str | Path | None = None) -> dict:
    """Índice {(nome_norm, middle6) -> set(cpf)} dos DOADORES do TSE (`doacoes_eleitorais`, CPF completo —
    dado PÚBLICO OFICIAL). Construído UMA vez p/ resolver muitos sócios no sweep (evita SQL por sócio).
    Fonte legítima (oversight de deputado, LGPD art. 7º,II/23) — nada de base de vazamento."""
    idx: dict = {}
    p = Path(db_path or _DB)
    if not p.exists():
        return idx
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            for nome, doc in con.execute("SELECT nome_doador, cpf_cnpj_doador FROM doacoes_eleitorais"):
                d = _digitos(doc)
                if len(d) == 11:
                    idx.setdefault((_norm(nome), d[3:9]), set()).add(d)
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — tabela ausente / DB indisponível → índice vazio (honesto)
        return idx
    return idx


def carregar_indice_sei(db_path: str | Path | None = None) -> dict:
    """Índice {(nome_norm, middle6) -> set(cpf)} dos CPFs extraídos de DOCUMENTOS do SEI (`sei_cpf` —
    contrato social/habilitação/procuração, CPF com DV validado). Fonte AUTORITATIVA (contratação pública
    aberta; dever de fiscalização). Espelha `carregar_indice_tse`; passe como `sei_idx` em `resolver_multi`."""
    idx: dict = {}
    p = Path(db_path or _DB)
    if not p.exists():
        return idx
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
        try:
            for nome, cpf in con.execute("SELECT nome_norm, cpf FROM sei_cpf"):
                d = _digitos(cpf)
                if len(d) == 11 and nome:
                    idx.setdefault((_norm(nome), d[3:9]), set()).add(d)
        finally:
            con.close()
    except Exception:  # noqa: BLE001 — tabela ausente → índice vazio (honesto)
        return idx
    return idx


def resolver_multi(nome: str, doc_mascarado: str, *, db_path: str | Path | None = None,
                   tse_idx: dict | None = None, pf_idx: dict | None = None,
                   sei_idx: dict | None = None) -> dict:
    """Resolução de CPF de sócio mascarado MULTI-FONTE (todas oficiais/públicas):
      1) corpus de favorecidos PF (OB) — `resolver()` (SQL) ou `pf_idx` (índice pré-construído, VM-safe);
      2) doadores do TSE — `tse_idx` (passe `carregar_indice_tse()` no sweep p/ não reconstruir por sócio).
    Match 1:1 obrigatório (nome + 6 díg do meio como checksum). Ambíguo/sem match → INDISPONÍVEL (nunca chute).
    Acrescenta `fonte` ao retorno. Cobertura medida: middle-6 ~2% → +TSE ~5% (a somar SEI-docs no futuro).
    No sweep, passe `pf_idx=carregar_indice_favorecidos()` p/ NÃO fazer 1 full-scan de OBs por sócio (§8)."""
    if pf_idx is not None:
        r = _match_indice(nome, doc_mascarado, pf_idx, "corpus de favorecidos PF")
    else:
        r = resolver(nome, doc_mascarado, db_path=db_path)
    if r.get("resolvido"):
        return {**r, "fonte": "favorecidos_pf"}
    if tse_idx is not None:
        m6 = middle6(doc_mascarado)
        nome_n = _norm(nome)
        if m6 and len(nome_n) >= 6:
            cpfs = tse_idx.get((nome_n, m6))
            if cpfs and len(cpfs) == 1:
                return {"resolvido": True, "cpf": next(iter(cpfs)), "confianca": 0.8,
                        "metodo": "nome+middle6", "fonte": "tse_doadores",
                        "motivo": "par (nome + 6 díg do meio) único nos doadores TSE (dado público oficial)"}
            if cpfs and len(cpfs) > 1:
                return {**r, "resolvido": False, "fonte": "",
                        "motivo": f"ambíguo no TSE ({len(cpfs)} CPFs p/ nome+6díg) — não resolve"}
    if sei_idx is not None:
        m6 = middle6(doc_mascarado)
        nome_n = _norm(nome)
        if m6 and len(nome_n) >= 6:
            cpfs = sei_idx.get((nome_n, m6))
            if cpfs and len(cpfs) == 1:
                return {"resolvido": True, "cpf": next(iter(cpfs)), "confianca": 0.9,
                        "metodo": "nome+middle6", "fonte": "sei_docs",
                        "motivo": "par (nome + 6 díg do meio) único em documento do SEI (contrato social/habilitação)"}
            if cpfs and len(cpfs) > 1:
                return {**r, "resolvido": False, "fonte": "",
                        "motivo": f"ambíguo no SEI ({len(cpfs)} CPFs p/ nome+6díg) — não resolve"}
    return {**r, "fonte": ""}


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
