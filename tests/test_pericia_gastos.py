# -*- coding: utf-8 -*-
"""Task 10 — detectores de gastos PCRJ (DB semeado, sem rede)."""
import pytest

from compliance_agent.emendas import db as edb
from compliance_agent.pcrj import gastos_db, pericia_gastos


@pytest.fixture
def con_semeado(tmp_path):
    con = edb.conectar(tmp_path / "t.db")
    edb.init_schema(con)
    gastos_db.init_schema(con)
    con.execute("""create table socios_receita (cnpj_basico text, ident text, nome_socio text,
                   nome_norm text, doc_socio text, qualificacao_cod text, qualificacao_txt text,
                   data_entrada text, faixa_etaria text, fonte_mes text)""")
    con.execute("""create table alertas (id integer primary key, tipo text, severidade text,
                   titulo text, descricao text, evidencias text, status text,
                   pessoa_id integer, empresa_id integer, contrato_id integer,
                   processo_sei_id integer, ordem_bancaria_id integer,
                   data_referencia text, created_at text)""")
    con.commit()
    return con


def test_d7_fracionamento(con_semeado):
    con = con_semeado
    for i in range(3):   # 3 empenhos abaixo do teto p/ mesmo credor+órgão em 90 dias
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       orgao_nome, fornecedor_documento, fornecedor_nome, tipo,
                       valor_global, data_assinatura)
                       values (?,2025,'42498733000148','PCRJ','11222333000181','ACME',
                               'Empenho',50000,?)""",
                    (f"C{i}", f"2025-03-{10 + i:02d}"))
    achados = pericia_gastos.d7_fracionamento(con)
    assert len(achados) == 1 and achados[0]["risco"] >= 6
    assert "indício" in achados[0]["descricao"].lower()
    assert achados[0]["evidencias"]["n_contratos"] == 3


def test_d7_ignora_acima_do_teto(con_semeado):
    con = con_semeado
    for i in range(3):
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       fornecedor_documento, tipo, valor_global, data_assinatura)
                       values (?,2025,'42498733000148','11222333000181','Empenho',900000,?)""",
                    (f"G{i}", f"2025-03-{10 + i:02d}"))
    assert pericia_gastos.d7_fracionamento(con) == []


def test_d8_credor_recem_aberto(con_semeado):
    con = con_semeado
    con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                   fornecedor_documento, fornecedor_nome, tipo, valor_global, data_assinatura)
                   values ('N1',2025,'42498733000148','11222333000181','NOVATA LTDA',
                           'Contrato',800000,'2025-03-01')""")
    def consulta_fake(cnpj):
        return {"data_inicio_atividade": "2025-01-15", "razao_social": "NOVATA LTDA"}
    achados = pericia_gastos.d8_credor_recem_aberto(con, consulta_cnpj=consulta_fake)
    assert len(achados) == 1 and achados[0]["risco"] >= 7
    assert "dias" in achados[0]["descricao"]


def test_d9_socio_na_folha(con_semeado):
    con = con_semeado
    con.execute("""insert into pcrj_despesa (exercicio, orgao, credor_documento, credor_nome,
                   natureza, fonte_recurso, empenhado, liquidado, pago, arquivo_origem)
                   values (2023,'SMS','11222333000181','ACME','339039','100',
                           500000,500000,500000,'x.csv')""")
    con.execute("""insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio)
                   values ('11222333','CARLOS PEREIRA DIAS','CARLOS PEREIRA DIAS','***111222**')""")
    folha = {"CARLOS PEREIRA DIAS": {"orgao": "SMS", "cargo": "ASSESSOR"}}
    achados = pericia_gastos.d9_socio_na_folha(con, folha_norm=folha)
    assert len(achados) == 1
    a = achados[0]
    assert a["risco"] <= 6 and "homônim" in a["descricao"].lower()   # nome = indício


def test_d10_rede_concorrentes_e_aditivos(con_semeado):
    con = con_semeado
    # mesmo sócio (raiz) em 2 fornecedores contratados pelo mesmo órgão no ano
    con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj, orgao_nome,
                   fornecedor_documento, fornecedor_nome, tipo, valor_global, data_assinatura)
                   values ('R1',2025,'42498733000148','PCRJ','11222333000181','ALFA',
                           'Contrato',100000,'2025-02-01')""")
    con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj, orgao_nome,
                   fornecedor_documento, fornecedor_nome, tipo, valor_global, data_assinatura)
                   values ('R2',2025,'42498733000148','PCRJ','44555666000199','BETA',
                           'Contrato',120000,'2025-02-15')""")
    con.execute("""insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio)
                   values ('11222333','MESMO DONO','MESMO DONO','***999888**'),
                          ('44555666','MESMO DONO','MESMO DONO','***999888**')""")
    # aditivo estourado: global 2x o inicial
    con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                   fornecedor_documento, fornecedor_nome, tipo, valor_inicial, valor_global,
                   data_assinatura)
                   values ('A1',2024,'42498733000148','77888999000155','GAMA','Contrato',
                           100000,210000,'2024-05-01')""")
    achados = pericia_gastos.d10_rede_concorrentes(con)
    tipos = {a["evidencias"].get("subtipo") for a in achados}
    assert "rede_socios" in tipos and "aditivo_estourado" in tipos


def test_rodar_todas_cobertura(con_semeado):
    r = pericia_gastos.rodar_todas(con_semeado)
    assert set(r["cobertura"]) == {"d7", "d8", "d9", "d10"}
