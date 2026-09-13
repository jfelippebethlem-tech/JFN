# -*- coding: utf-8 -*-
"""Extrato de TAC no texto de PDF do DOERJ: hífen de quebra ('Con- tas'), letras espaçadas ('PA R T E S')."""
from __future__ import annotations

from tools.doerj_tac_recorrente import extrair_tacs, normalizar

_TX = ("VALOR TOTAL: R$ 782.492,44 (setecentos e oitenta e dois mil). FUNDAMENTO: Decidido no processo "
       "administrativo SEI-080002/013873/2026. DATA DA ASSI- NATURA: 10/07/2026. INSTRUMENTO: Termo de "
       "Apostilamento - Termo de Ajuste de Con- tas nº 604/2026. Processo SEI Nº: SEI-080002/001820/2026 "
       "PA R T E S : Fundação Saúde do Estado do Rio de Janeiro e a empresa INSTI- TUTO DE DESENVOLVIMENTO "
       "PARA EDUCAÇÃO, SAÚDE E INTE- GRAÇÃO SOCIAL - IDESI. OBJETO: retificação do objeto. DATA DE ASSINATURA: "
       "09/07/2026 Id: 2748451")


def test_normaliza_hifen_de_quebra():
    t = normalizar(_TX)
    assert "Ajuste de Contas" in t and "INSTITUTO DE DESENVOLVIMENTO" in t


def test_extrato_da_ses_com_rotulos_partidos_e_NI():
    tx = ("EXTRATO DE TERMO INSTRUMEN TO : Termo de Ajuste de Contas NI 040/2026 PA RTES : Estado do Rio de "
          "Janeiro, através da Secretaria de Estado de Saúde, e Planeta de Itaboraí Ltda. OBJE TO : Prestação "
          "contínua de serviços de limpeza. VA LOR : R$ 149.488.863,38 (cento). PROCESSO Nº SEI - 0 8 0 0 0 1 / "
          "0 11 0 0 3 / 2 0 2 6 Id: 2738859")
    (r,) = extrair_tacs(tx)
    assert r["numero_tac"] == "040/2026"
    assert r["orgao"].startswith("Secretaria de Estado de Saúde")
    assert r["fornecedor"].startswith("Planeta de Itaboraí")
    assert r["valor"] == 149488863.38
    assert r["processo"] == "SEI-080001/011003/2026"


def test_extrai_numero_valor_partes_processo():
    (r,) = extrair_tacs(_TX)
    assert r["numero_tac"] == "604/2026"
    assert r["valor"] is None, "o VALOR antes do INSTRUMENTO é do extrato ANTERIOR — apostilamento não tem valor"
    assert r["orgao"].startswith("Fundação Saúde")
    assert "IDESI" in r["fornecedor"]
    assert r["processo"] == "SEI-080002/001820/2026"


# Página real do D.O. (pub 10100, 30/07/2026): três TACs em sequência. A janela de ±900 dava à CMP o nº e o
# valor da GUERREIRO (2194/2026, R$ 481.505,76) e o processo da PANTHER (017978/2026) — e o sweep SEI foi ler
# o processo errado. Cada extrato só pode enxergar o que vem DEPOIS do seu próprio INSTRUMENTO.
_TRES = ("INSTRUMENTO: Termo de Ajuste de Contas nº 2089/2026. PA R T E S : Fundação Saúde do Estado do Rio de "
         "Janeiro e a empresa PAN- THER HEALTHCARE DO BRASIL LTDA. OBJETO: indenização OPME. VALOR TOTAL: R$ "
         "329.105,00 (trezentos). FUNDAMENTO: Decidido no processo administrativo SEI-080002/017978/2026. DATA DA "
         "ASSINATURA: 27/07/2026. INSTRUMENTO: Termo de Ajuste de Contas nº 2175/2026. PA R T E S : Fundação Saúde "
         "do Estado do Rio de Janeiro e a empresa CMP - CAMPOS CLÍNICA MÉDICA E PEDIÁTRICA LTDA. OBJETO: Te m por "
         "objeto a indenização pela prestação de serviços médicos, para UPA 24h Campos dos Goytacazes. VA - LOR "
         "TOTAL: R$ 534.678,80 (quinhentos). FUNDAMENTO: De- cidido no processo administrativo SEI-080002/018591/2026. "
         "DATA DA ASSINATURA: 27/07/2026. INSTRUMENTO: Termo de Ajuste de Contas nº 2194/2026. PA R T E S : Fundação "
         "Saúde do Estado do Rio de Janeiro e a empresa GUER- REIRO SERVIÇOS MÉDICOS LTDA. OBJETO: serviços médicos, "
         "para UPA 24h Marechal Hermes. VALOR TOTAL: R$ 481.505,76 (quatrocentos). FUNDAMENTO: Decidido no processo "
         "administrativo SEI-080002/018602/2026. DATA DA ASSINATURA: 27/07/2026. Id: 2760001")


def test_tres_extratos_em_sequencia_nao_se_contaminam():
    rs = extrair_tacs(_TRES)
    assert [r["numero_tac"] for r in rs] == ["2089/2026", "2175/2026", "2194/2026"]
    cmp = rs[1]
    assert cmp["fornecedor"].startswith("CMP - CAMPOS")
    assert cmp["valor"] == 534678.80
    assert cmp["processo"] == "SEI-080002/018591/2026"
    assert "UPA 24h Campos" in cmp["objeto"]
    assert rs[0]["processo"] == "SEI-080002/017978/2026" and rs[0]["valor"] == 329105.00
    assert rs[2]["processo"] == "SEI-080002/018602/2026" and rs[2]["valor"] == 481505.76


def test_sem_tac_devolve_vazio():
    assert extrair_tacs("EXTRATO DE CONTRATO nº 1/2026 PARTES: A e B VALOR: R$ 1,00") == []


def test_cnpj_do_extrato_quando_publicado():
    tx = ("EXTRATO DE TERMO INSTRUMENTO: Termo de Ajuste de Contas nº 12/2026 PARTES: Fundação Saúde do Estado do "
          "Rio de Janeiro e a empresa AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA., CNPJ: 00.801.512/0001- 57. "
          "OBJETO: apoio. VALOR: R$ 1,00")
    (r,) = extrair_tacs(tx)
    assert r["cnpj"] == "00801512000157"
    assert extrair_tacs("Termo de Ajuste de Contas nº 1/2026 PARTES: A e B. VALOR: R$ 1,00")[0]["cnpj"] is None


def test_concordancia_processo_x_credor_siafe_mede_o_extrator():
    """O controle externo que pegou o defeito da janela: processo do TAC → credor da OB (nome por tokens)."""
    import sqlite3
    from tools.doerj_tac_recorrente import concordancia_siafe
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE doerj_tac (fornecedor TEXT, processo TEXT);
        CREATE TABLE ob_orcamentaria_siafe (processo TEXT, nome_credor TEXT);
        INSERT INTO doerj_tac VALUES ('CMP - CAMPOS CLÍNICA MÉDICA E PEDIÁTRICA LTDA', 'SEI-080002/018591/2026'),
                                     ('PANTHER HEALTHCARE DO BRASIL LTDA', 'SEI-080002/017978/2026'),
                                     ('GUERREIRO SERVIÇOS MÉDICOS LTDA', 'SEI-080002/000001/2026');
        INSERT INTO ob_orcamentaria_siafe VALUES ('SEI-080002/018591/2026', 'CMP CAMPOS CLINICA MEDICA E PEDIATRICA'),
                                                ('SEI-080002/017978/2026', 'PANTHER HEALTHCARE BRASIL DISTRIBUIDORA'),
                                                ('SEI-080002/000001/2026', 'MAIS CLEAN AMBIENTAL E CONSULTORIA LTDA');
    """)
    assert concordancia_siafe(con) == {"com_ob": 3, "batem": 2, "taxa": 0.667}
    vazio = sqlite3.connect(":memory:")
    vazio.execute("CREATE TABLE doerj_tac (fornecedor TEXT, processo TEXT)")
    assert concordancia_siafe(vazio)["taxa"] is None


# Layout da SEEDUC (pub 5929, 10/09): caixa alta, "por intermédio da", CNPJ colado ao nome e a frase
# "OBJETO: Termo de Ajuste de Contas tem por objeto…" — a menção dentro do OBJETO partia o extrato e
# fabricava uma linha fantasma sem fornecedor com o valor e o processo (R$ 15,6 mi da AGILE).
_SEEDUC = ("EXTRATO DE TERMO INSTRUMEN TO : Termo de Ajuste de Contas nº 06/2026 PA RTES : O ESTADO DO RIO DE "
           "JANEIRO, POR INTERMÉDIO DA SECRETARIA DE ESTADO DE EDUCAÇÃO, E A EMPRESA AGILE CORP SERVIÇOS "
           "ESPECIALIZADOS LTDA. CNPJ: 00.801.512/0001-57 OBJE TO : Termo de Ajuste de Contas tem por objeto "
           "regularizar pendência de valores em aberto pela prestação do serviço de limpeza. VALOR: R$ "
           "15.648.509,04 (quinze milhões). PROCESSO ADMINISTRATIVO Nº SEI-030001/040129/2026. Id: 2745992")


def test_mencao_dentro_do_objeto_nao_abre_extrato_e_caixa_alta_separa_as_partes():
    (r,) = extrair_tacs(_SEEDUC)
    assert r["numero_tac"] == "06/2026"
    assert r["orgao"] == "SECRETARIA DE ESTADO DE EDUCAÇÃO"
    assert r["fornecedor"] == "AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA"
    assert r["cnpj"] == "00801512000157"
    assert r["valor"] == 15648509.04
    assert r["processo"] == "SEI-030001/040129/2026"
