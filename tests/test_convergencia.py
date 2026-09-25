# -*- coding: utf-8 -*-
"""Convergência de lentes — o cruzamento que ordena a fila de apuração.

O que estes testes protegem: (1) DIMENSÃO != DETECTOR — três lentes de tamanho votam UMA vez, e
contá-las separado já inflou "15 empresas em 3 lentes" até virar 0 quando a duplicidade saiu;
(2) os `porques` não podem repetir, porque a repetição empurra para fora do corte os motivos
informativos e o cartão passa a dizer três vezes a mesma coisa.
"""
import sqlite3

import pytest


def _diluir_ug(con, ug="404400"):
    """Sem isto a empresa de teste é a ÚNICA da UG e aciona DEPENDENCIA (100% da unidade),
    contaminando cenários que querem medir só TAMANHO ou só CONTROLE."""
    con.execute("INSERT INTO empresas_cadastro VALUES ('99999999','OUTRA','2062',1e6,'Demais')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('99999999000199',1e9,'10/03/2024',"
                "'Contabilizado','OUTRA',?)", (ug,))


def _banco():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, valor REAL, data_emissao TEXT,"
                " status TEXT, nome_credor TEXT, ug_emitente TEXT)")
    con.execute("CREATE TABLE empresas_cadastro (cnpj_basico TEXT, razao_social TEXT,"
                " natureza_cod TEXT, capital_social REAL, porte_txt TEXT)")
    con.execute("CREATE TABLE socios_receita (cnpj_basico TEXT, doc_socio TEXT, nome_socio TEXT,"
                " qualificacao_txt TEXT, data_entrada TEXT)")
    con.execute("CREATE TABLE socio_historico (cnpj_basico TEXT, nome_norm TEXT, qualificacao TEXT,"
                " saiu_entre TEXT, status TEXT, data_entrada TEXT, janela_confiavel INT)")
    con.execute("CREATE TABLE sancoes_federais (cpf_cnpj TEXT, categoria TEXT, data_inicio TEXT,"
                " data_fim TEXT, nome TEXT, orgao TEXT, cadastro TEXT, uf TEXT, processo TEXT,"
                " fundamentacao TEXT)")
    con.execute("CREATE TABLE pncp_resultado (fornecedor_cnpj TEXT, fornecedor_nome TEXT,"
                " porte_fornecedor INTEGER, data_pub TEXT, certame TEXT, valor_homologado REAL)")
    con.execute("CREATE TABLE contratos_tcerj (processo TEXT, data_contratacao TEXT, unidade TEXT,"
                " valor_contrato REAL, cnpj TEXT, fornecedor TEXT, status TEXT)")
    return con


def test_porques_nao_repetem():
    """`incompativeis` devolve CNPJ×ANO: quatro exercícios acima do teto viravam quatro frases
    iguais, e o corte em 4 descartava dependência e troca de controle."""
    from tools.convergencia import convergir

    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','X','2062',1e6,'Microempresa')")
    # mesma empresa acima do teto em QUATRO anos -> quatro marcações de TAMANHO
    for ano in ("2021", "2022", "2023", "2024"):
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199',5e6,?,"
                    "'Contabilizado','X','404400')", (f"10/03/{ano}",))
    r = convergir(con)
    assert len(r) == 1
    porques = r[0]["porques"]
    assert len(porques) == len(set(porques)), f"porques repetidos: {porques}"


def test_tamanho_conta_UMA_vez_mesmo_com_tres_lentes():
    """porte + porte declarado + contrato acima do porte medem a MESMA coisa: uma dimensão só."""
    from tools.convergencia import convergir

    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','X','2062',1e6,'Microempresa')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199',5e6,'10/03/2024',"
                "'Contabilizado','X','404400')")
    con.execute("INSERT INTO contratos_tcerj VALUES ('P','2024-01-01','U',9e6,"
                "'11111111000199','X','Ativo')")
    _diluir_ug(con)
    con.execute("INSERT INTO pncp_resultado VALUES ('11111111000199','X',1,'2024-11-25','c',1000)")
    r = [x for x in convergir(con) if x["cnpj_basico"] == "11111111"]
    assert r[0]["dimensoes"] == ["TAMANHO"], f"dimensões infladas: {r[0]['dimensoes']}"
    assert r[0]["n_dim"] == 1


def test_dimensoes_distintas_somam():
    """CONTROLE é dimensão própria — não tem relação com tamanho."""
    from tools.convergencia import convergir

    con = _banco()
    con.execute("INSERT INTO empresas_cadastro VALUES ('11111111','X','2062',1e6,'Microempresa')")
    for d in ("10/03/2021", "10/08/2026"):
        con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('11111111000199',5e6,?,"
                    "'Contabilizado','X','404400')", (d,))
    con.execute("INSERT INTO socio_historico VALUES ('11111111','ANTIGO','Sócio',"
                "'2023-09..2023-10','saiu','20190101',1)")
    con.execute("INSERT INTO socio_historico VALUES ('11111111','NOVO','Sócio',NULL,'ativo','20231001',1)")
    _diluir_ug(con)
    r = convergir(con)
    r = [x for x in r if x["cnpj_basico"] == "11111111"]
    assert set(r[0]["dimensoes"]) == {"TAMANHO", "CONTROLE"}
    assert r[0]["n_dim"] == 2
