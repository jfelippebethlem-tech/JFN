# -*- coding: utf-8 -*-
"""O relatório é produto da casa, e a ordem das seções é parte do produto.

Relatório ruim põe o número primeiro e a ressalva no rodapé. Aqui, sem as três separações — janela
de mandato, exclusão de inativo, trava de matrícula única — o número engana: **3.495 pessoas viram
50**. Por isso a fonte e as separações vêm ANTES do resultado, e isso é testado.
"""
from __future__ import annotations

from compliance_agent.pcrj import relatorio_candidatos as R

LINHAS = [
    {"nome_tse": "MARIA SOUZA", "ano": 2024, "cargo": "PREFEITO", "municipio": "QUISSAMÃ",
     "partido": "PP", "meses_no_mandato": 15, "c_ini": "202501", "c_fim": "202605",
     "orgao": "Comlurb (Companhia Municipal de Limpeza Urbana)", "n_matriculas": 1},
    {"nome_tse": "JOAO LIMA", "ano": 2024, "cargo": "VEREADOR", "municipio": "MAGÉ",
     "partido": "PV", "meses_no_mandato": 17, "c_ini": "202501", "c_fim": "202605",
     "orgao": "Guarda Municipal (GM/IG/DOP)", "n_matriculas": 1},
]


def test_a_fonte_e_as_separacoes_vem_antes_do_numero():
    titulos = [s["titulo"] for s in R.montar_contexto(LINHAS)["secoes"]]
    assert titulos[0].startswith("1.") and "cruzado" in titulos[0]
    assert titulos[1].startswith("2.") and "separações" in titulos[1]
    assert titulos[2].startswith("3.") and "Resultado" in titulos[2]


def test_o_limite_do_indicio_esta_no_documento():
    ctx = R.montar_contexto(LINHAS)
    corpo = " ".join(s["html"] for s in ctx["secoes"])
    assert "nunca prova" in corpo, "o relatório precisa dizer que o casamento por nome é indício"
    assert "matrícula" in corpo and "homônimo" in corpo
    assert "NÃO foi tratada como ausência" in ctx["ressalva"], \
        "a ausência de ato no D.O. não pode virar ausência do ato"


def test_chefia_do_executivo_e_separada_do_legislativo():
    ctx = R.montar_contexto(LINHAS)
    assert ctx["score"] == 10, "1 chefe de executivo × 10"
    assert any("art. 38, II" in f for f in ctx["top_flags"])


def test_agrupamento_por_orgao_usa_o_orgao_e_nao_a_sigla():
    assert R._org("Guarda Municipal (GM/IG/DOP/SUBDOC/CI)") == "Guarda Municipal"
    assert R._org("RioSaúde (RS/PRE/NG-HMRG)") == "Saúde / RioSaúde"
    assert R._org("Secretaria Municipal de Educação (E/SUBG)") == "Educação"
