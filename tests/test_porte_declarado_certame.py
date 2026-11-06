# -*- coding: utf-8 -*-
"""Declaração de ME/EPP no certame × recebido no ano-calendário.

O que estes testes protegem: o corte ESTRITO (certame publicado DEPOIS do estouro) é o que separa
"a empresa sabia" de "podia não saber". Se ele afrouxar para o ano inteiro sem aviso, o número
triplica e vira acusação onde havia dúvida legítima — 8 empresas viram 24.
"""
import sqlite3

import pytest

from tools.porte_declarado_certame import (PEQUENO, PORTE_PNCP, TETO_EPP, _acumulado_no_ano,
                                           _iso, declaracoes_incompativeis)


def _banco():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, valor REAL, data_emissao TEXT, status TEXT)")
    con.execute("CREATE TABLE pncp_resultado (fornecedor_cnpj TEXT, fornecedor_nome TEXT, "
                "porte_fornecedor INTEGER, data_pub TEXT, certame TEXT, valor_homologado REAL)")
    return con


def test_data_do_siafe_e_texto_ddmmaaaa():
    """`data_emissao` é DD/MM/AAAA; comparar sem converter compara '11/08/2026' com '2026-08-11'."""
    assert _iso("25/11/2024") == "2024-11-25"
    assert _iso("") == "" and _iso(None) == ""


def test_estrito_ignora_certame_ANTERIOR_ao_estouro():
    """Certame em janeiro não pode ser julgado pelo que a empresa recebeu em dezembro."""
    con = _banco()
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199', 9e6, '20/12/2024', 'Contabilizado')")
    con.execute("INSERT INTO pncp_resultado VALUES ('11111111000199', 'X', 1, '2024-01-10', 'c1', 1000)")
    assert declaracoes_incompativeis(con, estrito=True) == []
    # no corte amplo o mesmo caso aparece — é o teto da medida, e por isso não é o padrão
    assert len(declaracoes_incompativeis(con, estrito=False)) == 1


def test_estrito_pega_certame_POSTERIOR_ao_estouro():
    con = _banco()
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199', 9e6, '20/02/2024', 'Contabilizado')")
    con.execute("INSERT INTO pncp_resultado VALUES ('11111111000199', 'X', 1, '2024-11-25', 'c1', 1000)")
    r = declaracoes_incompativeis(con, estrito=True)
    assert len(r) == 1 and r[0]["cnpj_basico"] == "11111111"
    assert r[0]["certames"][0]["recebido_ate"] == 9e6


def test_ob_nao_contabilizada_nao_e_pagamento():
    """OB Anulada/Excluída não é dinheiro que saiu — não pode compor o estouro do teto."""
    con = _banco()
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199', 9e6, '20/02/2024', 'Anulado')")
    con.execute("INSERT INTO pncp_resultado VALUES ('11111111000199', 'X', 1, '2024-11-25', 'c1', 1000)")
    assert declaracoes_incompativeis(con, estrito=True) == []


def test_ano_anterior_nao_conta_no_ano_do_certame():
    """O teto da LC 123 é POR ano-calendário: R$ 9 mi em 2023 não estoura o ano de 2024."""
    con = _banco()
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199', 9e6, '20/02/2023', 'Contabilizado')")
    con.execute("INSERT INTO pncp_resultado VALUES ('11111111000199', 'X', 1, '2024-11-25', 'c1', 1000)")
    assert declaracoes_incompativeis(con, estrito=True) == []


def test_porte_grande_declarado_nao_entra():
    """Quem se declara 'Demais' (3) não frui benefício de ME/EPP — não é achado."""
    con = _banco()
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199', 9e6, '20/02/2024', 'Contabilizado')")
    con.execute("INSERT INTO pncp_resultado VALUES ('11111111000199', 'X', 3, '2024-11-25', 'c1', 1000)")
    assert declaracoes_incompativeis(con, estrito=True) == []


def test_matriz_e_filial_somam():
    """O teto da LC 123 é da pessoa jurídica (CNPJ raiz), não do estabelecimento."""
    con = _banco()
    for suf in ("000199", "000270"):
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?, 3e6, '20/02/2024', 'Contabilizado')",
                    (f"11111111{suf}",))
    con.execute("INSERT INTO pncp_resultado VALUES ('11111111000199', 'X', 1, '2024-11-25', 'c1', 1000)")
    r = declaracoes_incompativeis(con, estrito=True)
    assert len(r) == 1 and r[0]["certames"][0]["recebido_ate"] == 6e6, "matriz+filial deviam somar 6 mi"


def test_dominio_do_pncp_bate_com_a_api_oficial():
    """Conferido em 2026-08-22 em GET /api/pncp/v1/portes-empresa. Inverter isto inverte o achado."""
    assert PORTE_PNCP == {1: "ME", 2: "EPP", 3: "Demais", 4: "Não se aplica",
                          5: "Não informado", 6: "MEI"}
    assert PEQUENO == {1, 2, 6}, "MEI também frui benefício; 'Demais' nunca"
    assert TETO_EPP == 4_800_000.0, "LC 123/2006, art. 3º, II"


def test_acumulado_respeita_a_data():
    ev = {"11111111": [("2024-01-10", 1e6), ("2024-06-10", 5e6), ("2025-01-01", 9e6)]}
    assert _acumulado_no_ano(ev, "11111111", "2024-03-01") == 1e6
    assert _acumulado_no_ano(ev, "11111111", "2024-12-31") == 6e6
