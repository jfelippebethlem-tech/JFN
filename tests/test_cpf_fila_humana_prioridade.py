# -*- coding: utf-8 -*-
"""Fila humana de CPF: sem ente público/estatal/S.A. aberta e no máximo 3 sócios por empresa."""
from tools.desmascarar_cpf_externo import natureza_fora, priorizar


def _it(cnpj, v):
    return {"cnpj": cnpj, "ob_paga_siafe": v}


def test_natureza_fora():
    assert natureza_fora("1031") and natureza_fora("2038") and natureza_fora("2046") and natureza_fora("2011")
    assert not natureza_fora("2062") and not natureza_fora("3999") and not natureza_fora(None)


def test_priorizar_tira_publica_e_limita_por_empresa():
    fila = [_it("00000000000191", 9e9)] * 5 + [_it("11111111000100", 5e6)] * 5 + [_it("22222222000100", 1e6)]
    nat = {"00000000": "2038", "11111111": "2062", "22222222": "2062"}
    out = priorizar(fila, nat, n=10)
    assert [i["cnpj"] for i in out] == ["11111111000100"] * 3 + ["22222222000100"]
