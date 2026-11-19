# -*- coding: utf-8 -*-
"""despesa_sem_previo_empenho — Cobrape (SEI-070002/004385/2024) × pareceres que citam a norma."""
from compliance_agent.padroes.despesa_sem_previo_empenho import confissoes, ne_posterior


def test_positivo_confissao_cobrape():
    t = ("JUSTIFICATIVA DE DESPESAS SEM PREVIO EMPENHO\nO pagamento da 33ª medição à COMPANHIA BRASILEIRA DE PROJETOS "
         "E EMPREENDIMENTOS, está sendo efetuado sem seu prévio empenho devido à natureza crítica")
    assert confissoes(t)
    assert confissoes("referente ao período de 01/01/2026 até 16/01/2026, pois no período não existia o prévio empenho")


def test_negativo_texto_normativo():
    assert confissoes("Quanto à reserva orçamentária é vedada a realização de despesa sem prévio empenho ou acima do "
                      "limite dos créditos orçamentários concedidos, nos termos dos arts. 59 e 60") == []
    assert confissoes("o Art. 60 veda qualquer realização de despesas sem prévio empenho, qual já atendido") == []


def test_positivo_ne_original_posterior_a_nf():
    nes = {"2026NE08145": {"data": "2026-05-14", "reforco": False, "reforco_de": None, "doc": 46, "titulo": "NE"}}
    nfs = [{"data": "2026-05-04", "doc": 54, "titulo": "NF", "trecho": ""}]
    assert ne_posterior(nes, nfs)["ne"]["numero"] == "2026NE08145"


def test_negativo_ne_original_anterior_e_reforco_sozinho():
    nes = {"2026NE03993": {"data": "2026-03-30", "reforco": False, "reforco_de": None, "doc": 45, "titulo": "NE"},
           "2026NE08145": {"data": "2026-05-14", "reforco": False, "reforco_de": None, "doc": 46, "titulo": "NE"}}
    nfs = [{"data": "2026-05-04", "doc": 54, "titulo": "NF", "trecho": ""}]
    assert ne_posterior(nes, nfs) is None
    so_reforco = {"2025NE14975": {"data": "2025-07-21", "reforco": True, "reforco_de": None, "doc": 24, "titulo": "NE"}}
    assert ne_posterior(so_reforco, [{"data": "2025-06-10", "doc": 18, "titulo": "NF", "trecho": ""}]) is None
