# -*- coding: utf-8 -*-
"""Testes do detector de remuneração acima do teto (CF 37 XI) — classificação honesta, sem rede."""
from __future__ import annotations

from compliance_agent import acima_do_teto as T

TETO = 50000.0  # teto fixo p/ o teste


def test_dentro_do_teto():
    assert T.classificar(40000, teto=TETO)["acima"] is False


def test_rra_retroativo_provavel():
    c = T.classificar(200000, componentes=None, teto=TETO)  # 4× teto, sem detalhe
    assert c["status"] == "RRA_RETROATIVO_PROVAVEL"


def test_verificar_sem_composicao():
    c = T.classificar(60000, componentes=None, teto=TETO)   # 1,2× teto, sem detalhe
    assert c["status"] == "VERIFICAR"


def test_indicio_supersalario_mesmo_sem_indenizatorias():
    comp = {"Vencimento": 55000, "Auxílio-alimentação (indeniz)": 8000}
    c = T.classificar(63000, componentes=comp, teto=TETO)
    assert c["status"] == "INDICIO_SUPERSALARIO"
    assert c["base_teto"] == 55000  # 63000 - 8000 indenizatório
    assert c["excesso_sobre_teto"] == 5000


def test_dentro_apos_excluir_indenizatorias():
    comp = {"Vencimento": 45000, "Férias indenizadas": 20000}
    c = T.classificar(65000, componentes=comp, teto=TETO)
    assert c["status"] == "DENTRO_APOS_EXCLUSAO"   # base 45k < teto


def test_analisar_agrega_e_e_honesto():
    regs = [
        {"nome": "A", "remuneracao_bruta": 200000},                                   # RRA
        {"nome": "B", "remuneracao_bruta": 60000},                                    # verificar
        {"nome": "C", "remuneracao_bruta": 63000, "componentes": {"Venc": 55000, "diaria indeniz": 8000}},  # indício
        {"nome": "D", "remuneracao_bruta": 30000},                                    # dentro
    ]
    r = T.analisar(regs, teto=TETO)
    assert r["n_acima_bruto"] == 3 and r["n_indicio"] == 1
    assert "não é ilegal" in r["leitura"].lower()


def test_relatorio_traz_o_porque():
    reg = {"nome": "C", "orgao": "X", "cargo": "Y", "vinculo": "EFETIVO", "competencia": "2025-01",
           "remuneracao_bruta": 63000, "componentes": {"Vencimento": 55000, "Diária (indeniz)": 8000}}
    md = T.relatorio(reg, teto=TETO)
    assert "Vencimento" in md and "não conta p/ teto" in md and "INDICIO_SUPERSALARIO" in md
