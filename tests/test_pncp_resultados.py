# -*- coding: utf-8 -*-
"""Coletor de resultados estruturados do PNCP — lógica determinística (sem rede).

A coleta HTTP (coletar_resultados) não é testada com rede na suíte; aqui vão o schema, o gerador
de janelas mensais, a agregação registros_vencedores e o detector de rodízio de vencedores.
"""
import sqlite3

from compliance_agent.collectors import pncp_resultados as PR
from compliance_agent.rodizio_grafo import detectar_rodizio_vencedores

A, B, C = "11111111000111", "22222222000122", "33333333000133"


def _con():
    con = sqlite3.connect(":memory:")
    PR.init_schema(con)
    return con


def _seed(con, certame, orgao, item, cnpj, nome, valor, ordem=1, uf="RJ"):
    con.execute("INSERT OR IGNORE INTO pncp_resultado (certame,orgao_cnpj,uf,item,fornecedor_cnpj,"
                "fornecedor_nome,valor_homologado,ordem_classificacao) VALUES (?,?,?,?,?,?,?,?)",
                (certame, orgao, uf, item, cnpj, nome, valor, ordem))
    con.commit()


def test_schema_cria_tabela_e_indices():
    con = _con()
    cols = {r[1] for r in con.execute("PRAGMA table_info(pncp_resultado)")}
    assert {"certame", "fornecedor_cnpj", "valor_homologado", "ordem_classificacao", "uf"} <= cols
    idx = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert any("forn" in i for i in idx)


def test_meses_gera_janelas_fechadas():
    janelas = list(PR._meses(2024, 11, 2025, 2))
    assert janelas[0] == ("20241101", "20241130")
    assert janelas[1] == ("20241201", "20241231")  # dezembro fecha em 31
    assert janelas[2] == ("20250101", "20250131")
    assert janelas[-1] == ("20250201", "20250228")  # fevereiro 2025 = 28 dias
    assert len(janelas) == 4


def test_meses_um_unico_mes():
    assert list(PR._meses(2025, 6, 2025, 6)) == [("20250601", "20250630")]


def test_registros_vencedores_agrega_por_certame():
    con = _con()
    _seed(con, "cert-1", A, 1, B, "EMP B", 1000.0)
    _seed(con, "cert-1", A, 2, B, "EMP B", 500.0)   # mesmo vencedor, 2 itens → soma
    _seed(con, "cert-2", A, 1, C, "EMP C", 2000.0)
    regs = PR.registros_vencedores(con)
    by = {r["certame"]: r for r in regs}
    assert len(regs) == 2
    v1 = by["cert-1"]["vencedores"][0]
    assert v1["cnpj"] == B and abs(v1["valor"] - 1500.0) < 0.01  # soma dos 2 itens


def test_registros_vencedores_ignora_nao_homologado():
    con = _con()
    _seed(con, "cert-1", A, 1, B, "EMP B", 1000.0, ordem=1)
    _seed(con, "cert-1", A, 1, C, "EMP C", 900.0, ordem=2)  # 2º lugar não é vencedor
    regs = PR.registros_vencedores(con)
    cnpjs = {v["cnpj"] for v in regs[0]["vencedores"]}
    assert cnpjs == {B}  # só o ordem=1


def test_registros_vencedores_filtra_uf():
    con = _con()
    _seed(con, "c-rj", A, 1, B, "B", 1.0, uf="RJ")
    _seed(con, "c-sp", A, 1, C, "C", 1.0, uf="SP")
    assert len(PR.registros_vencedores(con, uf="RJ")) == 1
    assert len(PR.registros_vencedores(con, uf=None)) == 2


def test_detecta_captura_de_orgao():
    regs = [{"certame": f"c{i}", "orgao": A, "vencedores": [{"cnpj": B, "valor": 100}]} for i in range(9)]
    regs.append({"certame": "c9", "orgao": A, "vencedores": [{"cnpj": C, "valor": 100}]})
    r = detectar_rodizio_vencedores(regs, min_certames=5)
    assert r["captura"] and r["captura"][0]["vencedor"] == B
    assert r["captura"][0]["share"] == 0.9


def test_detecta_rodizio_de_vencedores():
    regs = [{"certame": f"c{i}", "orgao": A, "vencedores": [{"cnpj": (B if i % 2 else C), "valor": 100}]}
            for i in range(10)]
    r = detectar_rodizio_vencedores(regs, min_certames=5)
    assert r["rodizio_vencedores"] and r["rodizio_vencedores"][0]["cobertura_grupo"] == 1.0
    assert set(r["rodizio_vencedores"][0]["grupo"]) == {B, C}


def test_mercado_competitivo_nao_dispara():
    # 10 certames, 10 vencedores distintos → nem captura nem rodízio
    regs = [{"certame": f"c{i}", "orgao": A,
             "vencedores": [{"cnpj": f"{i:014d}", "valor": 100}]} for i in range(10)]
    r = detectar_rodizio_vencedores(regs, min_certames=5)
    assert not r["captura"] and not r["rodizio_vencedores"]


def test_amostra_pequena_nao_dispara():
    regs = [{"certame": f"c{i}", "orgao": A, "vencedores": [{"cnpj": B, "valor": 100}]} for i in range(4)]
    r = detectar_rodizio_vencedores(regs, min_certames=5)
    assert not r["captura"]
