# -*- coding: utf-8 -*-
"""Base do relatório de inteligência: paths/env + helpers de formatação — extraído de inteligencia.py (split 2026-07-06).
Comportamento idêntico; rede de segurança: tools/inteligencia_snapshot_check.py + tests/test_inteligencia_snapshot.py.
"""
from __future__ import annotations

import logging
import asyncio
import json
import os
import re
import sqlite3
import time
from collections import OrderedDict, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional


_ROOT = Path(__file__).resolve().parents[2]


_DATA = Path(os.environ.get("JFN_DATA_DIR", _ROOT / "data"))


_DB = _DATA / "compliance.db"


_REPORTS = _ROOT / "reports"


_REGISTRY = _DATA / "empresas_target.json"


logger = logging.getLogger(__name__)


def cabecalho_frescor() -> str:
    """Cabeçalho de FRESCOR/COBERTURA dos dados de OB (honestidade: afirmar dentro da cobertura). Sem LLM —
    só um COUNT na base. Vazio se a base não estiver acessível. Reusado pelos relatórios de fornecedor/órgão."""
    try:
        import sqlite3
        con = sqlite3.connect(str(_DB))
        try:
            tot = con.execute("SELECT COUNT(*) FROM ordens_bancarias").fetchone()[0] or 0
            cnpj = con.execute("SELECT COUNT(*) FROM ordens_bancarias WHERE length(favorecido_cpf)=14").fetchone()[0] or 0
            ult = con.execute("SELECT MAX(data_pagamento) FROM ordens_bancarias").fetchone()[0]
        finally:
            con.close()
        if not tot:
            return ""
        pct = round(100 * cnpj / tot)
        return (f"> _Cobertura da base: {tot:,} OBs · {pct}% com CNPJ (PJ) · OB mais recente: {ult or '—'}. "
                f"OB = pagamento definitivo (SIAFE/TFE-RJ); afirmações limitadas a esta cobertura._").replace(",", ".")
    except Exception:
        return ""


_RETENCAO_DIAS = int(os.environ.get("JFN_REPORTS_RETENCAO_DIAS", "7"))


def _prune_reports():
    """Apaga relatórios gerados (inteligencia*/risco* .md/.pdf/.xlsx) mais antigos que a retenção."""
    try:
        import time as _t
        corte = _t.time() - _RETENCAO_DIAS * 86400
        import itertools
        for f in itertools.chain(_REPORTS.glob("inteligencia*"), _REPORTS.glob("parecer_lex*")):
            try:
                if f.is_file() and f.stat().st_mtime < corte:
                    f.unlink()
            except Exception as exc:
                logger.debug("janitor não removeu %s: %s", f.name, exc)
    except Exception as exc:
        logger.debug("janitor de reports interrompido: %s", exc)


def so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def fmt_cnpj(c: str) -> str:
    c = so_digitos(c)
    if len(c) != 14:
        return c
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def moeda(v) -> str:
    """1234567.89 -> '1.234.567,89' (padrão BR, sempre 2 casas)."""
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:40]


def _num_brl(v):
    """Converte capital social (número ou string '1.234,56') p/ float; None se não der."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).strip()
        if "," in s:  # formato BR (1.234,56): só então o ponto é separador de milhar
            s = s.replace(".", "").replace(",", ".")
        return float(s)
    except Exception:  # noqa: BLE001
        return None
