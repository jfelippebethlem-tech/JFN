# -*- coding: utf-8 -*-
"""carona_aderente_vedado — CDEL × SEGOV (SEI-420001/003312/2024) e CIM Jequitinhonha (SEI-150002/000471/2025)."""
from compliance_agent.padroes._carona_comum import Doc
from compliance_agent.padroes.carona_aderente_vedado import _ente_restrito, avaliar

NE_EXTERNO = Doc("arquivo", "14", "Nota de Empenho Original - NE",
                 "Mod. Licitação 12 - Adesão ao Registro de Preços Externo - Pregão Emb. Legal LEI Nº 8.666/93")
EDITAL_FDE = Doc("arquivo", "10", "Anexo EDITAL e Anexos (85050002)",
                 "15. ADESÃO À ATA DE REGISTRO DE PREÇOS POR ÓRGÃOS OU ENTIDADES NÃO PARTICIPANTES\n15.1. Limites "
                 "subjetivos. Desde que devidamente justificada a vantagem, a Ata de Registro de Preços\ndecorrente desta "
                 "licitação poderá ser utilizada, durante a sua validade, por órgãos ou entidades da\nAdministração Pública "
                 "do Estado de São Paulo e de Municípios paulistas que não tenham participado do\ncertame licitatório.")
NF_CIM = Doc("arquivo", "86", "Nota Fiscal - NF 2855",
             "oriundo da adesão à Ata de Registro de Preços número 061/2023, do Consórcio Integrado Multifinalitário do "
             "Vale do Jequitinhonha - CIM JEQUITINHONHA, proveniente do Pregão Eletrônico número 047/2023")
CONTRATO_CIM = Doc("arquivo", "2", "Contrato", "elegem as partes o Foro da Comarca de Diamantina/MG, com renúncia")


def test_positivo_cdel_restricao_a_paulistas():
    r = avaliar("420001_003312_2024", [NE_EXTERNO, EDITAL_FDE])
    s = {x["sinal"]: x for x in r["sinais"]}
    assert r["adesao"] == "externa" and s["restricao_ente"]["grau"] == "forte"
    assert "São Paulo" in s["restricao_ente"]["ente"] or "Sao Paulo" in s["restricao_ente"]["ente"]


def test_positivo_cim_consorcio_de_outro_estado_pelo_foro():
    r = avaliar("150002_000471_2025", [NE_EXTERNO, NF_CIM, CONTRATO_CIM])
    s = {x["sinal"]: x for x in r["sinais"]}
    assert s["gerenciador_municipal"]["uf"] == "MG" and s["gerenciador_municipal"]["grau"] == "medio"


def test_negativo_clausula_permissiva_e_ente_rj():
    assert _ente_restrito("poderá ser utilizada por qualquer órgão ou entidade da Administração Pública federal, "
                          "estadual, distrital e municipal que não tenha participado") is None
    assert _ente_restrito("poderá ser utilizada por órgãos da Administração Pública do Estado do Rio de Janeiro "
                          "que não tenham participado do certame") is None


def test_negativo_sem_adesao_do_orgao_fica_fora():
    # edital do próprio órgão (gerenciador) com a cláusula — sem NE/ato de adesão não é carona deste órgão
    r = avaliar("x", [EDITAL_FDE])
    assert r["adesao"] is None and r["sinais"] == []


def test_negativo_vedacao_federal_art86_par8_nao_conta():
    veda = Doc("arquivo", "3", "Edital", "É vedada a adesão a ata de registro de preços gerenciada por órgão estadual "
                                          "por órgãos e entidades da Administração Pública federal.")
    r = avaliar("x", [NE_EXTERNO, veda])
    assert not [s for s in r["sinais"] if s["sinal"] == "vedacao_carona"]
