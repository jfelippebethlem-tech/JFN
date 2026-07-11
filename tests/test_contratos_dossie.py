# -*- coding: utf-8 -*-
"""C4 — dossiê compartilhado do contrato."""
from compliance_agent.contratos import db as cd
from compliance_agent.contratos import dossie


def _seed(con):
    cd.init_schema(con)
    con.execute("""create table if not exists pcrj_contratos (numero_controle_pncp text primary key,
        ano int, orgao_cnpj text, orgao_nome text, fornecedor_documento text, fornecedor_nome text,
        tipo text, objeto text, valor_inicial real, valor_global real, data_assinatura text,
        vigencia_ini text, vigencia_fim text, num_aditivos int, fonte text, numero_compra text)""")
    con.execute("""create table if not exists pcrj_despesa (id integer primary key, exercicio int,
        orgao text, credor_documento text, credor_nome text, natureza text, fonte_recurso text,
        empenhado real, liquidado real, pago real, arquivo_origem text)""")
    con.execute("insert into pcrj_contratos (numero_controle_pncp, fornecedor_documento, objeto, valor_inicial, valor_global) "
                "values ('C1','11222333000181','obra X',100000,100000)")
    con.execute("insert into contrato_aditivo (numero_controle_pncp, sequencial_termo, valor_acrescido) "
                "values ('C1',1,40000)")
    con.execute("insert into pcrj_despesa (exercicio, credor_documento, empenhado, liquidado, pago) "
                "values (2024,'11222333000181',120000,120000,120000)")
    con.commit()


def test_montar_dossie(tmp_path):
    con = cd.conectar(tmp_path / "t.db")
    _seed(con)
    d = dossie.montar_dossie(con, "C1", com_rede=False, itens_fn=lambda nc: [])
    assert d["contrato"]["valor_inicial"] == 100000
    assert d["aditivos"][0]["valor_acrescido"] == 40000
    assert d["pagamentos"]["pago"] == 120000
    assert "proveniencia" in d
