# -*- coding: utf-8 -*-
"""Onda F — coletor de receita mensal do TFE (CKAN). Parser sobre CSV mock (sem rede)."""
from __future__ import annotations


def test_parsear_receita(tmp_path):
    from compliance_agent.collectors import tfe_receita as R
    # preâmbulo (5 linhas) + cabeçalho + 1 dado (27 colunas ';', latin-1)
    cab = ('"Posição";"Poder";"Nome Poder";"Categoria Economica";"Nome Categoria Economica";'
           '"Receita por Fonte";"Nome Receita por Fonte";"Receita por Sub Fonte";"Nome Receita por SubFonte";'
           '"Rubrica";"Nome Rubrica";"Alinea";"Nome Alinea";"Sub Alinea";"Nome Sub Alinea";"Gestão";"Nome Gestão";'
           '"Órgão";"Nome Órgão";"UG";"Nome UG";"Fonte de Recursos";"Nome Fonte de Recursos";'
           '"Valor Previsão Inicial";"Valor Previsão Atualizada";"Valor Receita a Realizar";"Valor Receita Realizada"')
    dado = ('"03/2025";"1";"Executivo";"1";"RECEITAS CORRENTES";"11";"RECEITA TRIBUTÁRIA";"112";"Taxas";'
            '"1121";"X";"112199";"Y";"11219915";"Z";"00001";"ADM";"00010";"SEFAZ";"100000";"UG SEFAZ";'
            '"230";"Recursos Próprios";"1.000.000,00";"1.200.000,00";"300.000,00";"900.000,00"')
    fp = tmp_path / "r.csv"
    fp.write_text("Governo\nSecretaria\nSubsec\nTransp\nReceitas entre...\n" + cab + "\n" + dado + "\n", encoding="latin-1")
    regs = list(R.parsear(fp))
    assert len(regs) == 1
    r = regs[0]
    assert r["ano"] == 2025 and r["mes"] == 3 and r["competencia"] == "03/2025"
    assert r["cat_econ"] == "RECEITAS CORRENTES" and r["orgao"] == "SEFAZ"
    assert r["previsao_inicial"] == 1000000.0 and r["realizada"] == 900000.0


def test_num_br_receita():
    from compliance_agent.collectors.tfe_receita import _num
    assert _num("1.296.000,00") == 1296000.0 and _num("") == 0.0
