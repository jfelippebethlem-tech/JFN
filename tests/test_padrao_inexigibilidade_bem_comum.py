# -*- coding: utf-8 -*-
"""inexigibilidade_bem_comum — MVT (SEI-030001/056588/2025) e Estudo Play (SEI-030001/064253/2025)."""
from compliance_agent.padroes._carona_comum import Doc
from compliance_agent.padroes.inexigibilidade_bem_comum import avaliar

DESP = Doc("arquivo", "8", "Despacho de Encaminhamento", "procedimento licitatório realizado na modalidade de "
           "inexigibilidade, com fundamento no artigo 74, inciso I da Lei nº 14.133/2021")
TR_EP = Doc("arquivo", "9", "Termo de Referência (102326553)",
            "1.3. O objeto descrito neste Termo de Referência é caracterizado como comum , em razão\nde seus padrões "
            "serem facilmente definidos e encontrados no mercado.\n... sendo possível por parte do licitante a "
            "indicação, se houver, de versões\nmais recentes e/ou outras editoras, desde que tenham características "
            "similares")


def test_positivo_estudo_play_forte():
    r = avaliar([DESP, TR_EP])
    assert r["inciso"] == "I" and r["bem_comum"] and r["outros_fornecedores"]


def test_positivo_mvt_so_bem_comum():
    tr = Doc("arquivo", "13", "Termo de Referencia - MVT", "1.4. O objeto descrito neste Termo de Referência é "
             "caracterizado como bem comum, em\nrazão de seus padrões serem facilmente definidos e encontrados no mercado.")
    r = avaliar([DESP, tr])
    assert r["bem_comum"] and not r["outros_fornecedores"]


def test_negativo_tr_que_nega_ser_comum_e_pregao():
    tr = Doc("arquivo", "5", "Termo de Referência", "O objeto não é caracterizado como comum, em razão de seus "
             "padrões não serem facilmente definidos e encontrados no mercado. Não há outras editoras que atendam.")
    r = avaliar([DESP, tr])
    assert r["bem_comum"] is None and r["outros_fornecedores"] is None
    assert avaliar([Doc("arquivo", "1", "Termo de Referência", "Pregão eletrônico; bem comum, facilmente encontrados no mercado")]) is None


def test_negativo_inexistencia_de_outros_fornecedores_e_justificativa():
    # falso positivo da 1ª varredura (SEI-240002/003084/2025 e 270006/012496/2025)
    tr = Doc("arquivo", "0", "Termo de Referência", "a contratação direta por inexigibilidade está condicionada à "
             "inexistência de outros fornecedores com capacidade técnica e institucional equivalente para realizar")
    r = avaliar([DESP, tr])
    assert r["outros_fornecedores"] is None
