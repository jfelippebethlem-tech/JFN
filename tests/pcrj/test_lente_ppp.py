# -*- coding: utf-8 -*-
"""Testes da lente específica de PPP (``pcrj/lente_ppp.py``)."""
from compliance_agent.pcrj.lente_ppp import analisar_ppp

TXT_PPP = (
    "GARANTIA PÚBLICA DE PAGAMENTO. Nos termos do art. 8º, I, da Lei de PPPs, as receitas "
    "vinculadas do FUNDO NACIONAL DE SAÚDE serão destinadas à constituição da GARANTIA PÚBLICA, "
    "conforme o CONTRATO DE CONTA GARANTIA. APORTE PÚBLICO de recursos em favor da CONCESSIONÁRIA. "
    "Ressarcimento dos estudos do Procedimento de Manifestação de Interesse (PMI). PRAZO DA CONCESSÃO "
    "de 30 (trinta) anos. VALOR ESTIMADO DO CONTRATO. O VERIFICADOR INDEPENDENTE emitirá termo."
)
TXT_PREGAO = "EDITAL DE PREGÃO ELETRÔNICO para aquisição de material de escritório, menor preço por item."


def test_edital_ppp_dispara_altas():
    r = analisar_ppp(TXT_PPP)
    tipos = {f["tipo"] for f in r["flags"]}
    assert "garantia_receita_saude" in tipos
    assert "pmi_privado_ressarcimento" in tipos
    assert "valor_vs_rcl" in tipos
    assert r["n_altas"] >= 3
    assert r["grau"] == "🔴 alto"


def test_cada_flag_tem_base_legal_verificar_e_jurisprudencia():
    r = analisar_ppp(TXT_PPP)
    assert r["flags"]
    for f in r["flags"]:
        assert f["base_legal"] and f["verificar"]
        assert f["jurisprudencia"] and len(f["jurisprudencia"]) > 40  # cruzamento com o TC


def test_pregao_comum_nao_alarma():
    r = analisar_ppp(TXT_PREGAO)
    assert r["n_altas"] == 0
    assert r["grau"] in ("🟢 baixo", "🟡 médio")


def test_texto_vazio():
    r = analisar_ppp("")
    assert r["n_flags"] == 0 and r["grau"] == "🟢 baixo"
