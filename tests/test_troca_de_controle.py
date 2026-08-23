# -*- coding: utf-8 -*-
"""Troca de controle durante a execução do contrato.

O que estes testes protegem: o corte FORTE (nenhum sócio atual estava no 1º pagamento) é o que
separa sinal de ruído — o fraco marca 21,6% do universo e não ordena fila nenhuma. E o filtro de
natureza/qualificação é o que impedia o primeiro protótipo de coroar Light, Ampla e Correios,
onde diretor eleito virava "troca de controle".
"""
import sqlite3

from tools.troca_de_controle import NATUREZAS, _ym, trocas


def _banco():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, valor REAL, data_emissao TEXT, "
                "status TEXT, nome_credor TEXT)")
    con.execute("CREATE TABLE empresas_cadastro (cnpj_basico TEXT, natureza_cod TEXT)")
    con.execute("CREATE TABLE socio_historico (cnpj_basico TEXT, nome_norm TEXT, qualificacao TEXT,"
                " saiu_entre TEXT, status TEXT, data_entrada TEXT, janela_confiavel INT)")
    return con


def _empresa(con, basico="11111111", natureza="2062"):
    con.execute("INSERT INTO empresas_cadastro VALUES (?,?)", (basico, natureza))
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?)",
                (f"{basico}000199", 5e6, "10/03/2021", "Contabilizado", "EMPRESA X"))
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?)",
                (f"{basico}000199", 5e6, "10/08/2026", "Contabilizado", "EMPRESA X"))


def test_data_do_siafe_e_texto():
    assert _ym("10/03/2021") == "2021-03"
    assert _ym("") == "" and _ym(None) == ""


def test_troca_total_entra():
    con = _banco(); _empresa(con)
    con.execute("INSERT INTO socio_historico VALUES ('11111111','ANTIGO','Sócio','2023-09..2023-10',"
                "'saiu','20190101',1)")
    con.execute("INSERT INTO socio_historico VALUES ('11111111','NOVO','Sócio-Administrador',NULL,"
                "'ativo','20231001',1)")
    r = trocas(con)
    assert len(r) == 1 and r[0]["troca_total"] is True


def test_socio_remanescente_NAO_entra_no_corte_forte():
    """Se alguém do quadro original continua, não houve troca de controle — só saída de um sócio."""
    con = _banco(); _empresa(con)
    con.execute("INSERT INTO socio_historico VALUES ('11111111','ANTIGO','Sócio','2023-09..2023-10',"
                "'saiu','20190101',1)")
    con.execute("INSERT INTO socio_historico VALUES ('11111111','FICOU','Sócio',NULL,'ativo','20190101',1)")
    assert trocas(con, forte=True) == []
    assert len(trocas(con, forte=False)) == 1, "o corte fraco deve pegar — é o de conferência"


def test_diretor_eleito_nao_e_troca_de_controle():
    """Rotação de Diretor/Presidente é mandato, não venda. Foi o que coroou Light e Correios."""
    con = _banco(); _empresa(con)
    con.execute("INSERT INTO socio_historico VALUES ('11111111','EX','Diretor','2023-09..2023-10',"
                "'saiu','20190101',1)")
    con.execute("INSERT INTO socio_historico VALUES ('11111111','ATUAL','Presidente',NULL,'ativo','20231001',1)")
    assert trocas(con) == []


def test_sociedade_anonima_fica_de_fora():
    con = _banco(); _empresa(con, natureza="2054")     # S.A. fechada
    con.execute("INSERT INTO socio_historico VALUES ('11111111','ANTIGO','Sócio','2023-09..2023-10',"
                "'saiu','20190101',1)")
    con.execute("INSERT INTO socio_historico VALUES ('11111111','NOVO','Sócio',NULL,'ativo','20231001',1)")
    assert trocas(con) == []
    assert "2054" not in NATUREZAS


def test_saida_FORA_da_janela_de_pagamentos_nao_conta():
    """Sócio que saiu depois do último pagamento não trocou o controle DURANTE a execução."""
    con = _banco(); _empresa(con)
    con.execute("INSERT INTO socio_historico VALUES ('11111111','ANTIGO','Sócio','2030-01..2030-02',"
                "'saiu','20190101',1)")
    con.execute("INSERT INTO socio_historico VALUES ('11111111','NOVO','Sócio',NULL,'ativo','20231001',1)")
    assert trocas(con) == []


def test_ob_nao_contabilizada_nao_forma_janela():
    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','2062')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199',5e6,'10/03/2021','Anulado','X')")
    con.execute("INSERT INTO socio_historico VALUES ('11111111','ANTIGO','Sócio','2023-09..2023-10',"
                "'saiu','20190101',1)")
    con.execute("INSERT INTO socio_historico VALUES ('11111111','NOVO','Sócio',NULL,'ativo','20231001',1)")
    assert trocas(con) == []


def test_janela_nao_confiavel_fica_de_fora():
    con = _banco(); _empresa(con)
    con.execute("INSERT INTO socio_historico VALUES ('11111111','ANTIGO','Sócio','2023-09..2023-10',"
                "'saiu','20190101',0)")
    con.execute("INSERT INTO socio_historico VALUES ('11111111','NOVO','Sócio',NULL,'ativo','20231001',0)")
    assert trocas(con) == []
