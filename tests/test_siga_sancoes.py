# -*- coding: utf-8 -*-
"""Registro estadual de sanções do SIGA (sem API): linha do paginate vira registro com doc normalizado (12/09/2026)."""
from __future__ import annotations

from tools.siga_sancoes import parse_linha


def test_linha_cnpj_e_cpf():
    d = parse_linha([" B7 EMPREENDIMENTOS LTDA", "17.298.685/0001-05", "Lei Federal Nº 8.666/93, art. 87, Inc. II. (Multa)", "19/07/2021",
                     "SEFAZ - SECRETARIA DE ESTADO DE FAZENDA", "Multado", "1605", None, None, None])
    assert d["doc"] == "17298685000105" and d["tipo_doc"] == "cnpj" and d["id_sancao"] == "1605" and d["status"] == "Multado"
    p = parse_linha([" ALEX DE SOUZA OLIVEIRA", "092.730.947-59", "Lei Federal 8.429/92, art. 12º (Proibido de Contratar)", "11/06/2026",
                     "TJRJ", "Vigente", "3410", None, None, None])
    assert p["tipo_doc"] == "cpf" and p["nome"] == "ALEX DE SOUZA OLIVEIRA" and p["status"] == "Vigente"
