# -*- coding: utf-8 -*-
"""Formatação dos produtos PCRJ (HTML, moeda, competência, data) — um lugar só."""
from __future__ import annotations

import html
import re
from datetime import date

from compliance_agent.reporting.intel_base import moeda as brl  # noqa: F401 — '1.234,56'

_MESES = ["", "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def e(x) -> str:
    return html.escape(str(x or ""))


def brl_rs(v) -> str:
    return "R$ " + brl(v)


def comp(c: str | None) -> str:
    """'aaaamm' → 'mm/aaaa'; vazio → '—'."""
    return f"{c[4:6]}/{c[:4]}" if c and len(c) == 6 else "—"


def comp_legivel(ym: str) -> str:
    """'aaaamm' → 'jan/2025'; ilegível volta como veio."""
    try:
        return f"{_MESES[int(ym[4:6])]}/{ym[:4]}"
    except Exception:
        return ym


def data(s: str | None) -> date | None:
    """'dd/mm/aaaa' ou 'aaaa-mm-dd' → date; outro formato → None."""
    s = (s or "").strip()
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def fmt_data(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"
