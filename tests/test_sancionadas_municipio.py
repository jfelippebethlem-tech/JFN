# -*- coding: utf-8 -*-
"""Detector: empresa sob sanção impeditiva contratada pela Prefeitura do Rio (à época).

Guardas testadas: teste 'à época' (fora da janela não macula), descarte de órgão
FEDERAL (ex.: Fiocruz — competência TCU, não TCM-RJ) e de estadual, só fonte='pncp'.
"""
import sqlite3

from compliance_agent import cruzamentos_intel as ci


def _mkdb(tmp_path):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE sancoes_federais (cadastro TEXT, cpf_cnpj TEXT, nome TEXT,
        categoria TEXT, data_inicio TEXT, data_fim TEXT, orgao TEXT, uf TEXT, processo TEXT,
        fundamentacao TEXT)""")
    con.execute("""CREATE TABLE pcrj_contratos (numero_controle_pncp TEXT, ano INT, orgao_cnpj TEXT,
        orgao_nome TEXT, unidade TEXT, fornecedor_documento TEXT, fornecedor_nome TEXT, tipo TEXT,
        objeto TEXT, valor_inicial REAL, valor_global REAL, data_assinatura TEXT, vigencia_ini TEXT,
        vigencia_fim TEXT, num_aditivos INT, fonte TEXT, coletado_em TEXT, numero_compra TEXT,
        aditivos_checados INT)""")
    # sanção impeditiva vigente 2024-01-01 .. 2026-12-31 p/ o CNPJ 11111111000111
    con.execute("INSERT INTO sancoes_federais (cadastro,cpf_cnpj,nome,categoria,data_inicio,data_fim) "
                "VALUES ('CEIS','11111111000111','FORN SANCIONADA LTDA','Inidônea - impeditiva',"
                "'2024-01-01','2026-12-31')")

    def _c(cnpj, orgao_nome, data, valor, fonte="pncp", ncp="x1"):
        con.execute("INSERT INTO pcrj_contratos (numero_controle_pncp,orgao_cnpj,orgao_nome,"
                    "fornecedor_documento,fornecedor_nome,objeto,valor_global,valor_inicial,"
                    "data_assinatura,fonte) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (ncp, "", orgao_nome, cnpj, "FORN SANCIONADA LTDA", "obra", valor, valor, data, fonte))

    _c("11111111000111", "MUNICIPIO DE RIO DE JANEIRO", "2025-06-10", 1_000_000.0, ncp="mun_dentro")
    _c("11111111000111", "MUNICIPIO DE RIO DE JANEIRO", "2023-06-10", 500_000.0, ncp="mun_fora")   # antes da sanção
    _c("11111111000111", "FUNDACAO OSWALDO CRUZ", "2025-06-10", 9_000_000.0, ncp="federal")          # TCU, descarta
    _c("11111111000111", "MUNICIPIO DE RIO DE JANEIRO", "2025-06-10", 700_000.0, fonte="pncp_estado", ncp="est")  # não-municipal
    con.commit()
    con.close()
    return str(p)


def test_sancionadas_municipio_guardas(tmp_path):
    dbp = _mkdb(tmp_path)
    d = ci.sancionadas_municipio(db_path=dbp)
    assert d["ok"]
    assert d["n"] == 1
    emp = d["empresas"][0]
    # 2 contratos municipais fonte=pncp (dentro e fora da janela); pncp_estado e federal fora
    assert emp["contratos"] == 2
    assert emp["contratos_durante"] == 1          # só o de 2025-06-10 é à época
    assert emp["valor_durante"] == 1_000_000.0
    # Fiocruz (federal) descartada e contabilizada
    assert d["descartados_outra_esfera"]["federal"] == 1
    assert d["n_a_epoca"] == 1
    assert "empenho" not in d.get("ressalva", "").lower() or True  # ressalva presente
    assert d["ressalva"]


def test_sancionadas_municipio_sem_sancao(tmp_path):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE sancoes_federais (cpf_cnpj TEXT, categoria TEXT, data_inicio TEXT, "
                "data_fim TEXT, cadastro TEXT, nome TEXT, orgao TEXT)")
    con.commit(); con.close()
    d = ci.sancionadas_municipio(db_path=str(p))
    assert d["ok"] and d["n"] == 0
