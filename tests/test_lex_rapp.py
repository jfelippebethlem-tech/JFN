# -*- coding: utf-8 -*-
"""R-RAPP — pesquisa de preços (RAPP) frágil: o achado MAIS frequente da CGE e que o JFN não avaliava.

Confronto CGE × JFN 13/11/2026 (lacuna 3): LOTERJ A-003 a A-009, ISP Q2, DETRO 004, RIOTRILHOS — menos de
3 fontes válidas, fonte única (a proposta da própria contratada), referências não independentes (negociadas
por terceiros interessados ou de empresas do mesmo grupo) e ausência de RAPP. Textos SINTÉTICOS.
"""
from __future__ import annotations

from compliance_agent import lex_redflags as LR

CONTRATADA = "11222333000181"


def _subtipos(achados):
    return {a["subtipo"] for a in achados}


def test_rapp_com_tres_fontes_independentes_nao_dispara():
    txt = ("RELATÓRIO DE PESQUISA DE PREÇOS. Fonte 1: Painel de Preços do Governo Federal. Fonte 2: PNCP, "
           "contratações similares de outros entes. Fonte 3: cotação da empresa 44.555.666/0001-77. "
           "Proposta vencedora: 11.222.333/0001-81.")
    assert LR.avaliar_rapp(txt, cnpj_contratada=CONTRATADA, texto_integral=True) == []


def test_menos_de_tres_fontes():
    txt = ("PESQUISA DE PREÇOS. Cotação 1: 44.555.666/0001-77. Cotação 2: 11.222.333/0001-81 (contratada).")
    a = LR.avaliar_rapp(txt, cnpj_contratada=CONTRATADA, texto_integral=True)
    assert "fontes_insuficientes" in _subtipos(a)
    assert all(x["rf"] == "R-RAPP" for x in a)


def test_fonte_unica_e_a_proposta_da_contratada():
    txt = ("Pesquisa de preços: o valor foi aferido pela proposta da própria contratada, "
           "11.222.333/0001-81, única fonte disponível.")
    assert "fonte_unica_contratada" in _subtipos(
        LR.avaliar_rapp(txt, cnpj_contratada=CONTRATADA, texto_integral=True))


def test_referencias_negociadas_por_terceiros_nao_sao_independentes():
    """Caso-tipo da CGE na LOTERJ: preço 'justificado' por patrocínios negociados pelas emissoras."""
    txt = ("Justificativa de preço: valores compatíveis com patrocínios anteriores negociados pelas emissoras "
           "de televisão parceiras do evento. Fonte 1: Painel de Preços. Fonte 2: PNCP. Fonte 3: Banco de Preços.")
    assert "referencias_nao_independentes" in _subtipos(
        LR.avaliar_rapp(txt, cnpj_contratada=CONTRATADA, texto_integral=True))


def test_cotacoes_do_mesmo_grupo_da_contratada_nao_sao_independentes():
    txt = ("PESQUISA DE PREÇOS. Cotação 1: 11.222.333/0002-62. Cotação 2: 44.555.666/0001-77. "
           "Cotação 3: 77.888.999/0001-02.")                  # 1ª cotação = filial da contratada
    a = LR.avaliar_rapp(txt, cnpj_contratada=CONTRATADA, texto_integral=True)
    assert "referencias_nao_independentes" in _subtipos(a)


def test_ausencia_de_rapp_so_com_texto_integral():
    txt = "Termo de referência. Objeto: serviço de limpeza. Justificativa da contratação direta."
    assert "ausencia_rapp" in _subtipos(LR.avaliar_rapp(txt, cnpj_contratada=CONTRATADA, texto_integral=True))
    # recorte parcial: ausência no recorte ≠ ausência no processo (INDISPONÍVEL ≠ 0)
    assert LR.avaliar_rapp(txt, cnpj_contratada=CONTRATADA, texto_integral=False) == []


def test_lex_le_so_o_documento_da_pesquisa(monkeypatch):
    """O Lex chama a regra sobre os documentos cujo TÍTULO é de pesquisa de preços (caller real)."""
    from compliance_agent import lex_analise_conteudo as LA
    monkeypatch.setattr(LA, "_texto_integra", lambda integra: "Contrato. Objeto: serviço de limpeza predial.")
    integra = {"numero": "SEI-000000/000001/2026", "cnpj_contratada": CONTRATADA, "conteudo_documentos": [
        {"doc": "Relatório de Pesquisa de Preços (RAPP)",
         "conteudo": "Pesquisa de preços: valor aferido pela proposta da própria contratada, única fonte."},
        {"doc": "Nota Fiscal", "conteudo": "44.555.666/0001-77 77.888.999/0001-02 12.345.678/0001-95"}]}
    achados, _ = LA._analisar_conteudo_sei(integra)
    sub = {a.get("subtipo") for a in achados if a["rf"] == "R-RAPP"}
    assert {"fonte_unica_contratada", "fontes_insuficientes"} <= sub     # CNPJs da NF não viram "fontes"


def test_r_rapp_tem_identidade_completa_no_lex():
    assert "R-RAPP" in LR._RF and "R-RAPP" in LR._MATRIZ and "R-RAPP" in LR._EXCULPATORIO
    assert LR._RF_DESTINATARIO["R-RAPP"] == ("debito",)
    assert "14.133" in LR._RF["R-RAPP"][1]
