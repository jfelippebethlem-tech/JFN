# -*- coding: utf-8 -*-
"""Quem, no SIAFE, é FORNECEDOR — e quem só ocupa o campo `credor`.

Três populações distintas dividem esse campo, e tratá-las como uma só estraga a fila (browser
gasto no que não se examina) e a manchete (exposição fiscalizável superestimada):

    rubrica genérica   CG0004700 FOLHA DE PAGAMENTOS · 123400 RIOPREV · CG0006026 INATIVOS
    órgão público      FUNDO MUNICIPAL DE SAÚDE DA CIDADE DO RJ · MINISTÉRIO DA FAZENDA
    fornecedor         I.D.E.A.S · INSTITUTO D'OR · AGILE CORP

Medido na fila de processos ilegíveis (2026-08-11): dos R$ 9,90 bi, R$ 6,17 bi eram rubrica
genérica e **R$ 601 mi eram órgão público com CNPJ** — repasse a fundo municipal e tributo, não
contratação. Fornecedor de verdade: R$ 3,13 bi.

O órgão público é o caso que a primeira régua deixou passar, porque ele TEM CNPJ. A distinção vem
da natureza jurídica `1xx` (administração pública) do cadastro da Receita — a mesma família do
vício já catalogado em que o ITERJ, a SEGOV e a SECID figuravam como "vencedoras" das próprias
contratações.
"""
from __future__ import annotations

import sqlite3

from compliance_agent import credor_generico as C


def _con(linhas, cadastro=()):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (processo TEXT, credor TEXT, valor REAL)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?)", linhas)
    con.execute("CREATE TABLE empresas_cadastro (cnpj_basico TEXT, razao_social TEXT,"
                " natureza_cod TEXT)")
    con.executemany("INSERT INTO empresas_cadastro VALUES (?,?,?)", cadastro)
    con.commit()
    return con


def test_rubrica_generica_nao_e_fornecedor():
    assert C.eh_fornecedor("CG0004700") is False
    assert C.eh_fornecedor("123400") is False
    assert C.eh_fornecedor("") is False


def test_cnpj_e_cpf_passam_no_teste_de_documento():
    assert C.eh_fornecedor("12345678000199") is True
    assert C.eh_fornecedor("111.222.333-44") is True


def test_orgao_publico_TEM_cnpj_e_ainda_assim_nao_e_fornecedor():
    """`11715094000100` = FUNDO MUNICIPAL DE SAÚDE DA CIDADE DO RJ, natureza 1244. Repasse a ente
    público não é contratação — e passava como fornecedor porque tem CNPJ."""
    con = _con([("SEI-1/1/2024", "11715094000100", 100.0)],
               [("11715094", "FUNDO MUNICIPAL DE SAUDE DA CIDADE DO RJ", "1244")])
    c = C.classificar_por_processo(con)["SEI-1/1/2024"]
    con.close()
    assert c["publico"] == 100.0 and c["fornecedor"] == 0.0


def test_empresa_privada_com_cadastro_e_fornecedor():
    con = _con([("SEI-2/2/2024", "24006302000488", 500.0)],
               [("24006302", "I.D.E.A.S", "3999")])
    c = C.classificar_por_processo(con)["SEI-2/2/2024"]
    con.close()
    assert c["fornecedor"] == 500.0 and c["publico"] == 0.0


def test_cnpj_SEM_cadastro_continua_fornecedor():
    """Na dúvida NÃO rebaixa: ausência de cadastro é lacuna nossa, não prova de que é órgão. O
    contrário esconderia trabalho — e a nota da casa registra que ITERJ, SEGOV e SECID sequer
    estão em `empresas_cadastro`."""
    con = _con([("SEI-3/3/2024", "99999999000199", 70.0)], [])
    c = C.classificar_por_processo(con)["SEI-3/3/2024"]
    con.close()
    assert c["fornecedor"] == 70.0


def test_sem_a_tabela_de_cadastro_o_modulo_nao_quebra():
    """A régua roda contra bancos que não têm `empresas_cadastro` (os testes do sweep usam um
    esquema mínimo). Sem cadastro, ninguém é público — e nada estoura."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (processo TEXT, credor TEXT, valor REAL)")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('SEI-4/4/2024','12345678000199',10.0)")
    con.commit()
    c = C.classificar_por_processo(con)["SEI-4/4/2024"]
    con.close()
    assert c["fornecedor"] == 10.0


def test_processo_de_folha_continua_sendo_decidido_por_PESO():
    con = _con([("SEI-5/5/2024", "CG0004700", 900.0),
                ("SEI-5/5/2024", "12345678000199", 100.0)])
    folha = C.processos_de_folha(con)
    con.close()
    assert "SEI-5/5/2024" in folha


def test_orgao_publico_tambem_rebaixa_o_processo():
    """Processo cujo dinheiro é repasse a ente público não disputa a fila com contratação."""
    con = _con([("SEI-6/6/2024", "11715094000100", 900.0),
                ("SEI-6/6/2024", "12345678000199", 100.0)],
               [("11715094", "FUNDO MUNICIPAL DE SAUDE", "1244")])
    folha = C.processos_de_folha(con)
    con.close()
    assert "SEI-6/6/2024" in folha
