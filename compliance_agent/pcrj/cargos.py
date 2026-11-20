# -*- coding: utf-8 -*-
"""Natureza do cargo/vínculo na Prefeitura — a régua usada por coletores, cruzamentos e relatórios."""
from __future__ import annotations

import re

# Cargo em comissão, com VETOS para os falsos positivos conhecidos ("AGENTE DE APOIO A EDUCACAO
# ESPECIAL", "ESPECIALIDADE", estágios).
_RE_CARGO_COMISSAO = re.compile(r"^ESPECIAL\b|\bDAS\b|\bDAI\b|COMISS|^ASSESSOR|^ASSISTENTE ESPECIAL", re.IGNORECASE)
_RE_CARGO_VETO = re.compile(r"EDUCA[CÇ][AÃ]O ESPECIAL|ESPECIALIDADE|ESTAGI", re.IGNORECASE)

# Palavras que sugerem vínculo EFETIVO/carreira no Executivo (↑ concern de acúmulo).
_EFETIVO = ("GUARDA MUNICIPAL", "PROFESSOR", "MEDICO", "MÉDICO", "ENFERMEIR",
            "AGENTE DE ADMINISTRA", "AUXILIAR DE ENFERM", "FISCAL", "ANALISTA",
            "TECNICO", "TÉCNICO", "ASSISTENTE SOCIAL", "PROCURADOR", "AUDITOR")


def cargo_comissionado(cargo: str) -> bool:
    c = (cargo or "").strip()
    return bool(c) and bool(_RE_CARGO_COMISSAO.search(c)) and not _RE_CARGO_VETO.search(c)


def vinculo_efetivo(cargo_pcrj: str) -> bool:
    c = (cargo_pcrj or "").upper()
    return any(k in c for k in _EFETIVO)


def cessao_provavel(v: dict) -> bool:
    """Cessão/requisição (vínculo ÚNICO, NÃO acúmulo): o servidor da Prefeitura está
    formalmente 'à disposição' da Câmara, OU a Câmara o lista como 'Requisitado'. Nesses
    casos as duas folhas retratam o MESMO posto — não é duplo vínculo remunerado."""
    orgao = (v.get("orgao_pcrj") or "").upper()
    vinc = (v.get("vinculo_camara") or "").upper()
    return ("DISP" in orgao or "DISPOSI" in orgao or "CMRJ" in orgao
            or "REQUISITAD" in vinc)
