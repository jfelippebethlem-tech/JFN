# -*- coding: utf-8 -*-
"""Portal SIGA (sem API): linha do paginate e página de detalhe viram registro (12/09/2026)."""
from __future__ import annotations

from tools.siga_contratos import fmt_cnpj, parse_detalhe, parse_linha


def test_linha_do_paginate():
    row = ["2022004620", "28/06/2022", "SEI-080007/003132/2022", "FSERJ - FUNDAÇÃO SAÚDE DO EST. DO RIO DE JANEIRO",
           "R$\xa06.104.481,54", "", "Dispensa - Especial", "MARIA DAS GRAÇAS<br/> KATINE MULLER ", None, "false", "93385", "false"]
    d = parse_linha(row, "10.190.061/0001-12")
    assert d["id_contrato"] == "93385" and d["cnpj"] == "10190061000112" and d["valor"] == 6104481.54
    assert d["modalidade"] == "Dispensa - Especial" and d["gestores"] == "MARIA DAS GRAÇAS | KATINE MULLER"
    assert fmt_cnpj("10190061000112") == "10.190.061/0001-12"


def test_detalhe_extrai_objeto_situacao_fundamento():
    html = ("<html><body><span>Unidade:</span> FSERJ <span>Fornecedor:</span> TUISE <span>Situação da Contratação:</span> Em Aberto "
            "<span>Tipo de Aquisição:</span> Dispensa - Especial <span>Contratação:</span> 2022004620 "
            "<span>Data de Vigência da Contratação:</span> Não informada <span>Valor Total Original da Contratação:</span> R$ 6.104.481,54 "
            "<span>Valor Total Empenhado:</span> R$ 3.972.540,35 <span>Valor Total Pago:</span> Não possui "
            "<span>Fundamento Legal:</span> Em conformidade com o Inciso IV, do Art. 24 da lei 8666/93 "
            "<span>Objeto da Contratação:</span> Contratação de empresa especializada na prestação de serviços médico-hospitalares na UPA de Botafogo "
            "<span>Gestor(es) da Contratação:</span> MARIA</body></html>")
    d = parse_detalhe(html)
    assert d["situacao"] == "Em Aberto" and d["tipo"] == "Dispensa - Especial"
    assert d["fundamento"].startswith("Em conformidade com o Inciso IV")
    assert "UPA de Botafogo" in d["objeto"] and d["valor_empenhado"] == 3972540.35 and d["valor_pago_siga"] is None
