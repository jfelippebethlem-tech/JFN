"""27/11/2026 — dados reais do site: «pago a fornecedores» exclui ente público (nome OU natureza 1xxx) e credor sem
CNPJ (credor genérico CG…, UG). Sem isso o «maior fornecedor» do Fundo Estadual de Saúde era um FUNDO MUNICIPAL."""
import sqlite3

from tools import site_dados as S


def _con():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob, ug_pagadora, data_emissao, status, status_envio, "
                "tipo_regularizacao, credor, nome_credor, valor, exercicio)")
    con.execute("CREATE TABLE orgao_esfera (cnpj, nome, esfera, poder, uf, natureza, via, prova)")
    ob = [("1", "294200", "10/11/2026", "Contabilizado", "", "", "11.222.333/0001-81", "EMPRESA REAL LTDA", 1000.0, 2026),
          ("2", "294200", "11/11/2026", "Contabilizado", "", "", "22.333.444/0001-81", "FUNDO MUNICIPAL DE SAUDE DE X", 9000.0, 2026),
          ("3", "294200", "12/11/2026", "Contabilizado", "", "", "33.444.555/0001-81", "CONSORCIO INTERMUNICIPAL Y", 8000.0, 2026),
          ("4", "294200", "12/11/2026", "Contabilizado", "", "", "CG0006030", "ISS", 7000.0, 2026),
          ("5", "294200", "26/11/2026", "Contabilizado", "", "", "123400", "FUNDO UNICO DE PREVIDENCIA", 6000.0, 2026)]
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?,?)", ob)
    con.execute("INSERT INTO orgao_esfera VALUES ('33444555000181','CONSORCIO','municipal','','RJ','1155','','')")  # 1xxx
    return con


def test_so_fornecedor_privado_entra(tmp_path, monkeypatch):
    monkeypatch.setattr(S.ug_nomes, "subordinacao", lambda u, a: "FUNDACAO SAUDE")
    d = S.gerar(_con(), tmp_path)
    assert d["inicio"]["pago_fornecedores"]["valor"] == 1000.0                  # só a empresa privada
    assert d["inicio"]["fora_por_ser_ente_publico"]["valor"] == 17000.0         # fundo (nome) + consórcio (natureza 1xxx)
    assert [f["nome"] for f in d["orgao"]["fornecedores"]] == ["EMPRESA REAL LTDA"]
    assert d["inicio"]["siafe_ultima_ob"]["valor"] == "2026-11-26"               # data TEXTO convertida, não ordenada crua
    assert d["dinheiro"]["empenhado"]["estado"] == "INDISPONIVEL"
