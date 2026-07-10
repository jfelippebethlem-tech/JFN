# -*- coding: utf-8 -*-
"""Task 6 — coleta PNCP municipal Rio (contratos + contratações)."""
from compliance_agent.collectors import pncp

# payload real capturado na sondagem de 2026-07-10 (campos reduzidos)
CONTRATO_REAL = {
    "numeroControlePncpCompra": "42498600000171-1-001296/2023",
    "numeroControlePNCP": "42498600000171-2-001515/2024",
    "anoContrato": 2024,
    "tipoContrato": {"id": 7, "nome": "Empenho"},
    "numeroContratoEmpenho": "2024NE000921",
    "dataAssinatura": "2024-02-22",
    "dataVigenciaInicio": "2024-02-22",
    "dataVigenciaFim": "2025-01-21",
    "niFornecedor": "18809570000354",
    "nomeRazaoSocialFornecedor": "FORNECEDOR EXEMPLO LTDA",
    "tipoPessoa": "PJ",
    "orgaoEntidade": {"razaoSocial": "MUNICIPIO DE RIO DE JANEIRO",
                      "poderId": "N", "esferaId": "M", "cnpj": "42498733000148"},
    "categoriaProcesso": {"id": 2, "nome": "Compras"},
    "sequencialContrato": 1515,
    "unidadeOrgao": {"ufNome": "Rio de Janeiro", "codigoIbge": "3304557",
                     "nomeUnidade": "SMS", "ufSigla": "RJ"},
    "valorInicial": 100000.0,
    "valorGlobal": 120000.0,
    "objetoContrato": "Aquisição de materiais",
}


def test_simplificar_contrato_pcrj():
    row = pncp._simplificar_contrato_pcrj(CONTRATO_REAL)
    assert row["numero_controle_pncp"] == "42498600000171-2-001515/2024"
    assert row["ano"] == 2024
    assert row["orgao_cnpj"] == "42498733000148"
    assert row["fornecedor_documento"] == "18809570000354"
    assert row["tipo"] == "Empenho"
    assert row["valor_global"] == 120000.0
    assert row["vigencia_fim"] == "2025-01-21"


def test_constantes_municipio():
    assert pncp.MUNICIPIO_RIO_IBGE == "3304557"
    assert pncp.CNPJ_PCRJ == "42498733000148"
