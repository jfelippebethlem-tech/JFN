# -*- coding: utf-8 -*-
"""O4.1 — `dominio.contrato_id`: `(orgao, numero_normalizado, exercicio)`, com PARIDADE do número contra as cópias:
  compliance_agent/padroes/_aditivos_comum.py:382 `norm_contrato`
  compliance_agent/sei/instrumento_assinatura.py:586 `num_contrato`
  compliance_agent/sei/reuso_documento_execucao.py:227 `contratos_citados` (extrai do texto)
"""
from __future__ import annotations

import pytest

from compliance_agent.dominio import contrato_id as C

NUMEROS = ["034/2026", "34/2026", "0034 / 2026", "16/2023", "016/2023", "1/2024", "000/2025", "1234/2019", "7/24", "07/24"]


def test_paridade_norm_contrato():
    from compliance_agent.padroes._aditivos_comum import norm_contrato
    for n in NUMEROS:
        assert C.numero_contrato(n) == norm_contrato(n), n


def test_paridade_num_contrato():
    """DIVERGÊNCIA DOCUMENTADA: `num_contrato` mantém o ano como escrito ('7/24' fica '7/24'); a nova expande para
    '7/2024' como `norm_contrato` — senão '7/24' e '7/2024' (o mesmo ajuste) não casam. Com ano de 4 dígitos, igual."""
    from compliance_agent.sei.instrumento_assinatura import num_contrato
    for n in NUMEROS:
        if n.endswith("/24"):
            assert num_contrato(n) == n.lstrip("0") and C.numero_contrato(n) == f"{int(n.split('/')[0])}/2024"
        else:
            assert C.numero_contrato(n) == num_contrato(n), n


def test_paridade_contratos_citados():
    from compliance_agent.sei.reuso_documento_execucao import contratos_citados
    for n in NUMEROS:
        if n.endswith("/24"):
            continue   # `contratos_citados` só lê ano 20AA com 4 dígitos (o texto do contrato o escreve inteiro)
        assert contratos_citados(f"Contrato nº {n} firmado") == {C.numero_contrato(n)}, n


@pytest.mark.parametrize("entrada", ["", None, "abc", "34/2026/1", "34-2026", "/2026"])
def test_numero_irreconhecivel(entrada):
    assert C.numero_contrato(entrada) is None


def test_chave_do_contrato():
    k = C.contrato_id(" 080001 ", "034/2026")
    assert k == C.ContratoId("080001", "34/2026", 2026) and k.chave == ("080001", "34/2026", 2026)
    assert C.contrato_id("08.000-1", "34", exercicio=2026).chave == ("080001", "34/2026", 2026)
    assert C.contrato_id("seeduc ", "34/26").orgao == "SEEDUC"
    assert C.contrato_id("080001", "34/2026", exercicio=2025) is None   # fontes discordam: ninguém vence calado
    assert C.contrato_id("", "34/2026") is None and C.contrato_id("080001", "34") is None
