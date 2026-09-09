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
    assert r["valor"] == 782492.44
    assert r["orgao"].startswith("Fundação Saúde")
    assert "IDESI" in r["fornecedor"]
    assert r["processo"] in ("SEI-080002/013873/2026", "SEI-080002/001820/2026")


def test_sem_tac_devolve_vazio():
    assert extrair_tacs("EXTRATO DE CONTRATO nº 1/2026 PARTES: A e B VALOR: R$ 1,00") == []


def test_cnpj_do_extrato_quando_publicado():
    tx = ("EXTRATO DE TERMO INSTRUMENTO: Termo de Ajuste de Contas nº 12/2026 PARTES: Fundação Saúde do Estado do "
          "Rio de Janeiro e a empresa AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA., CNPJ: 00.801.512/0001- 57. "
          "OBJETO: apoio. VALOR: R$ 1,00")
    (r,) = extrair_tacs(tx)
    assert r["cnpj"] == "00801512000157"
    assert extrair_tacs("Termo de Ajuste de Contas nº 1/2026 PARTES: A e B. VALOR: R$ 1,00")[0]["cnpj"] is None
