# -*- coding: utf-8 -*-
"""Task 5 — planos de ação das emendas PIX (Transferegov)."""
from compliance_agent.emendas import transferegov


def test_parse_plano():
    # item real capturado na sondagem de 2026-07-10 (campos reduzidos)
    item = {"id_plano_acao": 22296, "codigo_plano_acao": "09032022-3-022296",
            "ano_plano_acao": 2022, "situacao_plano_acao": "IMPEDIDO",
            "cnpj_beneficiario_plano_acao": "28741072000109",
            "nome_beneficiario_plano_acao": "MUNICIPIO DE RIO BONITO",
            "uf_beneficiario_plano_acao": "RJ",
            "modalidade_plano_acao": "Especial"}
    row = transferegov.parse_plano(item)
    assert row["id_plano"] == 22296 and row["situacao"] == "IMPEDIDO" and row["uf"] == "RJ"
    assert row["cnpj_beneficiario"] == "28741072000109"
    assert '"modalidade_plano_acao"' in row["payload_json"]
