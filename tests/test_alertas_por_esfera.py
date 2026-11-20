# -*- coding: utf-8 -*-
"""Alertas: a esfera de cada família e a contagem estanque por esfera (20/11/2026)."""
from compliance_agent.alertas_persistencia import contagem_por_esfera, esfera_do_tipo


def test_esfera_do_tipo():
    assert esfera_do_tipo("pcrj_d7_fracionamento") == "prefeitura"
    assert esfera_do_tipo("emendas_d3_favorecido_sancionado") == "federal"     # emendas parlamentares federais
    assert esfera_do_tipo("fracionamento") == "estado"                         # motor de regras sobre OB do SIAFE
    assert esfera_do_tipo("doerj_anomalia") == "estado"
    assert esfera_do_tipo(None) == "estado"


def test_contagem_por_esfera_nao_soma_esferas():
    r = contagem_por_esfera([("fracionamento", "alta", 2), ("enriquecimento", "média", 3), ("enriquecimento", "media", 1),
                             ("pcrj_d7_fracionamento", "alta", 5), ("pcrj_d9_socio_na_folha", None, 4),
                             ("emendas_d1_pix_impedida", "baixa", 7)])
    assert r["estado"] == {"alta": 2, "media": 4, "baixa": 0, "total": 6}
    assert r["prefeitura"] == {"alta": 5, "media": 0, "baixa": 4, "total": 9}
    assert r["federal"] == {"alta": 0, "media": 0, "baixa": 7, "total": 7}
    assert all(d["alta"] + d["media"] + d["baixa"] == d["total"] for d in r.values())
