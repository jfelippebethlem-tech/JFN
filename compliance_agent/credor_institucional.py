# -*- coding: utf-8 -*-
"""Régua ÚNICA de credor institucional (20/11/2026).

Credor que por NATUREZA recebe de muitas UGs/órgãos — administração pública, estatal, S.A. aberta, plano de
previdência complementar dos servidores, concessionária de serviço público — não é "fornecedor carimbado".
Antes havia duas cópias parciais: `natureza_fora` (fila humana de CPF, tools/desmascarar_cpf_externo.py) e
`_cnae_concessao` (consumo contínuo, pericia_contabil.py). Ambas passam a importar daqui.

Medido: 107 dos 230 vereditos do alerta `direcionamento` "favorecido em N UGs" voltaram `provavel_falso_positivo`
da triagem do Opus — Light, Ampla, Águas do Rio, Correios, RJPREV.

Honestidade: Receita indisponível ou CNPJ não achado NÃO absolve (INDISPONÍVEL ≠ 0) — devolve institucional=False
com o motivo, e o detector segue acusando como antes.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

_DB_RECEITA = Path(__file__).resolve().parents[1] / "data" / "receita_estab.db"

# Natureza jurídica (tabela da Receita).
_NATUREZA_PREFIXO = {"1": "administração pública (natureza 1xxx)"}
_NATUREZA_EXATA = {
    "2011": "empresa pública",
    "2038": "sociedade de economia mista",
    "2046": "S.A. aberta",
    "3328": "plano de benefícios de previdência complementar fechada",
}

# CNAE principal de concessionária de serviço público (energia, água/esgoto, gás canalizado, telefonia).
# `empresas.atividade_princ` vem ora com o código de 7 dígitos, ora com a descrição.
_CNAE_CONCESSAO = ("3511", "3512", "3513", "3514", "3520402", "3600", "3701", "3702", "6110", "6120", "6130",
                   "6141", "6142", "6143")
_RE_CNAE_CONCESSAO = re.compile(
    r"^\s*((GERA[ÇC][ÃA]O|TRANSMISS[ÃA]O|DISTRIBUI[ÇC][ÃA]O|COM[ÉE]RCIO\s+ATACADISTA)\s+DE\s+ENERGIA\s+EL[ÉE]TRICA|"
    r"CAPTA[ÇC][ÃA]O,?\s+TRATAMENTO\s+E\s+DISTRIBUI[ÇC][ÃA]O\s+DE\s+[ÁA]GUA|GEST[ÃA]O\s+DE\s+REDES\s+DE\s+ESGOTO|"
    r"ATIVIDADES\s+RELACIONADAS\s+A\s+ESGOTO|DISTRIBUI[ÇC][ÃA]O\s+DE\s+COMBUST[ÍI]VEIS\s+GASOSOS\s+POR\s+REDES|"
    r"SERVI[ÇC]OS\s+DE\s+TELEFONIA|TELEFONIA\s+M[ÓO]VEL|TELECOMUNICA[ÇC][ÕO]ES\s+POR\s+SAT|"
    r"OPERADORAS\s+DE\s+TELEVIS[ÃA]O\s+POR\s+ASSINATURA)", re.I)


def _dig(s: str | None) -> str:
    return re.sub(r"\D", "", str(s or ""))


def motivo_natureza(cod: str | None) -> str | None:
    """Rótulo da natureza institucional, ou None."""
    c = _dig(cod)
    if not c:
        return None
    if c in _NATUREZA_EXATA:
        return _NATUREZA_EXATA[c]
    return next((m for p, m in _NATUREZA_PREFIXO.items() if c.startswith(p)), None)


def natureza_fora(cod: str | None) -> bool:
    return motivo_natureza(cod) is not None


def cnae_concessao(cnae: str | None) -> bool:
    c = str(cnae or "").strip()
    d = _dig(c)
    if re.fullmatch(r"\d[\d.\-/ ]*", c) and len(d) == 7:
        return d.startswith(_CNAE_CONCESSAO)
    return bool(_RE_CNAE_CONCESSAO.search(c))


def _receita(cnpj: str) -> tuple[str | None, str | None] | None:
    """(natureza_cod, cnae_principal) do dump da Receita; None se o banco não existe."""
    if not _DB_RECEITA.exists():
        return None
    con = sqlite3.connect(f"file:{_DB_RECEITA}?mode=ro", uri=True, timeout=30)
    try:
        nat = con.execute("SELECT natureza_cod FROM empresas WHERE cnpj_basico=?", (cnpj[:8],)).fetchone()
        est = con.execute("SELECT cnae_principal FROM estabelecimentos WHERE cnpj=?", (cnpj,)).fetchone()
        return (nat[0] if nat else None, est[0] if est else None)
    except sqlite3.Error:
        return None
    finally:
        con.close()


def institucional(cnpj: str | None, cnae: str | None = None) -> dict:
    """{institucional: bool, motivo: str}. `cnae` informado prevalece sobre o da Receita."""
    d = _dig(cnpj)
    if len(d) != 14:
        return {"institucional": False, "motivo": "não é CNPJ"}
    rec = _receita(d)
    nat, cnae_rec = rec if rec else (None, None)
    cnae = cnae or cnae_rec
    motivos = []
    if cnae and cnae_concessao(cnae):
        motivos.append(f"concessionária de serviço público (CNAE {cnae})")
    m = motivo_natureza(nat)
    if m:
        motivos.append(f"{m} (natureza jurídica {nat})")
    if motivos:
        return {"institucional": True, "motivo": "; ".join(motivos)}
    if rec is None:
        return {"institucional": False, "motivo": "INDISPONÍVEL — Receita (receita_estab.db) não consultável"}
    if nat is None and cnae_rec is None:
        return {"institucional": False, "motivo": "INDISPONÍVEL — CNPJ fora do dump da Receita"}
    return {"institucional": False, "motivo": "credor privado comum"}
