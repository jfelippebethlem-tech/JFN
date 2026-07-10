# -*- coding: utf-8 -*-
"""Task 9 — detectores determinísticos de emendas (DB semeado, sem rede)."""
import pytest

from compliance_agent.emendas import db as edb
from compliance_agent.emendas import pericia


@pytest.fixture
def con_semeado(tmp_path):
    con = edb.conectar(tmp_path / "t.db")
    edb.init_schema(con)
    # réplicas mínimas das tabelas de cruzamento (colunas reais do compliance.db)
    con.execute("""create table sancoes_federais (cadastro text, cpf_cnpj text, nome text,
                   categoria text, data_inicio text, data_fim text, orgao text, uf text,
                   processo text, fundamentacao text)""")
    con.execute("""create table socios_receita (cnpj_basico text, ident text, nome_socio text,
                   nome_norm text, doc_socio text, qualificacao_cod text, qualificacao_txt text,
                   data_entrada text, faixa_etaria text, fonte_mes text)""")
    con.execute("""create table doacoes_eleitorais (id integer primary key, cpf_cnpj_doador text,
                   nome_doador text, nome_candidato text, cargo_candidato text, partido text,
                   uf text, valor real, data_doacao text, ano_eleicao integer, created_at text)""")
    con.execute("""create table alertas (id integer primary key, tipo text, severidade text,
                   titulo text, descricao text, evidencias text, status text,
                   pessoa_id integer, empresa_id integer, contrato_id integer,
                   processo_sei_id integer, ordem_bancaria_id integer,
                   data_referencia text, created_at text)""")
    con.commit()
    return con


def test_d1_pix_impedida(con_semeado):
    con = con_semeado
    con.execute("""insert into emendas_pix_planos (id_plano, ano, cnpj_beneficiario,
                   nome_beneficiario, uf, situacao) values
                   (1, 2024, '28741072000109', 'MUNICIPIO DE RIO BONITO', 'RJ', 'IMPEDIDO'),
                   (2, 2024, '11111111000111', 'MUNICIPIO X', 'RJ', 'CIENTE')""")
    achados = pericia.d1_pix_impedida(con)
    assert len(achados) == 1
    a = achados[0]
    assert a["risco"] >= 6 and "RIO BONITO" in a["descricao"] and "indício" in a["descricao"].lower()


def test_d2_concentracao_autor(con_semeado):
    con = con_semeado
    # deputado com 80% num único município (3 emendas, 2 destinos)
    for i, (loc, v) in enumerate([("SAQUAREMA - RJ", 8_000_000.0),
                                  ("MACAE - RJ", 1_000_000.0),
                                  ("SAQUAREMA - RJ", 1_000_000.0)]):
        con.execute("""insert into emendas (codigo, ano, autor_norm, localidade_gasto,
                       uf_destino, empenhado, recorte) values (?,?,?,?,?,?,?)""",
                    (f"E{i}", 2024, "DEP FULANO", loc, "RJ", v, "AUTOR_RJ"))
    achados = pericia.d2_concentracao_autor(con, piso_total=1_000_000)
    assert len(achados) == 1
    assert "SAQUAREMA" in achados[0]["descricao"] and achados[0]["evidencias"]["share"] > 0.8


def test_d3_favorecido_sancionado(con_semeado):
    con = con_semeado
    con.execute("insert into emendas (codigo, ano, autor_norm, recorte) values ('E1',2024,'D','AUTOR_RJ')")
    con.execute("""insert into emenda_favorecidos (codigo_emenda, documento_favorecido,
                   nome_favorecido, fase, valor) values
                   ('E1','11222333000181','ACME LTDA','Pagamento',100000)""")
    con.execute("""insert into sancoes_federais (cadastro, cpf_cnpj, nome, categoria, orgao)
                   values ('CEIS','11222333000181','ACME LTDA','Inidoneidade','CGU')""")
    achados = pericia.d3_favorecido_sancionado(con)
    assert len(achados) == 1 and achados[0]["risco"] >= 8
    assert "CEIS" in achados[0]["descricao"]


def test_d4_favorecido_fantasma_injetado(con_semeado):
    con = con_semeado
    con.execute("insert into emendas (codigo, ano, autor_norm, recorte) values ('E1',2024,'D','AUTOR_RJ')")
    con.execute("""insert into emenda_favorecidos (codigo_emenda, documento_favorecido,
                   nome_favorecido, fase, valor) values
                   ('E1','11222333000181','ASSOCIACAO OBSCURA','Pagamento',900000)""")
    def perfil_fake(cnpj):
        return {"score": 75, "classificacao": "ALTO", "sinais": [
            {"id": "aberta_as_vesperas", "peso": 25, "detalhe": "aberta 2 meses antes"}]}
    achados = pericia.d4_favorecido_fantasma(con, avaliar_cnpj=perfil_fake)
    assert len(achados) == 1 and achados[0]["risco"] >= 7
    assert "aberta_as_vesperas" in str(achados[0]["evidencias"])


def test_d4_pula_entes_publicos(con_semeado):
    con = con_semeado
    con.execute("insert into emendas (codigo, ano, autor_norm, recorte) values ('E1',2024,'D','AUTOR_RJ')")
    con.execute("""insert into emenda_favorecidos (codigo_emenda, documento_favorecido,
                   nome_favorecido, fase, valor) values
                   ('E1','06083453000105','FUNDO DE SAUDE DO MUNICIPIO DE MESQUITA','Pagamento',900000)""")
    achados = pericia.d4_favorecido_fantasma(con, avaliar_cnpj=lambda c: {"score": 99, "sinais": []})
    assert achados == []


def test_d5_retroalimentacao_eleitoral(con_semeado):
    con = con_semeado
    con.execute("""insert into emendas (codigo, ano, autor_raw, autor_norm, recorte)
                   values ('E2',2024,'Dep Fulano','DEP FULANO','AUTOR_RJ')""")
    con.execute("""insert into emenda_favorecidos (codigo_emenda, documento_favorecido,
                   nome_favorecido, fase, valor) values
                   ('E2','11222333000181','ACME LTDA','Pagamento',500000)""")
    con.execute("""insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio)
                   values ('11222333','JOAO DA SILVA','JOAO DA SILVA','***456789**')""")
    con.execute("""insert into doacoes_eleitorais (cpf_cnpj_doador, nome_doador, nome_candidato,
                   valor, ano_eleicao) values ('***456789**','JOAO DA SILVA','Dep Fulano',50000,2022)""")
    achados = pericia.d5_retroalimentacao_eleitoral(con)
    assert len(achados) == 1
    a = achados[0]
    assert a["evidencias"]["match_tipo"] == "CPF" and a["risco"] >= 8
    assert "indício" in a["descricao"].lower()


def test_d5_match_por_nome_e_indicio_fraco(con_semeado):
    con = con_semeado
    con.execute("""insert into emendas (codigo, ano, autor_raw, autor_norm, recorte)
                   values ('E3',2024,'Dep Beltrano','DEP BELTRANO','AUTOR_RJ')""")
    con.execute("""insert into emenda_favorecidos (codigo_emenda, documento_favorecido,
                   nome_favorecido, fase, valor) values
                   ('E3','44555666000199','BETA SERVICOS','Pagamento',200000)""")
    con.execute("""insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio)
                   values ('44555666','MARIA SOUZA','MARIA SOUZA','')""")
    con.execute("""insert into doacoes_eleitorais (cpf_cnpj_doador, nome_doador, nome_candidato,
                   valor, ano_eleicao) values ('***000000**','Maria Souza','Dep Beltrano',10000,2022)""")
    achados = pericia.d5_retroalimentacao_eleitoral(con)
    assert len(achados) == 1
    a = achados[0]
    assert a["evidencias"]["match_tipo"] == "NOME" and a["risco"] <= 5
    assert "homônim" in a["descricao"].lower()


def test_d6_empenho_sem_pagamento(con_semeado):
    con = con_semeado
    con.execute("""insert into emendas (codigo, ano, autor_norm, empenhado, pago,
                   resto_cancelado, recorte)
                   values ('E4',2023,'DEP X',1000000,0,900000,'DESTINO_RJ')""")
    achados = pericia.d6_empenho_sem_pagamento(con)
    assert len(achados) == 1
    d = achados[0]["descricao"]
    assert "empenhado" in d and "pago" in d and "1.000.000,00" in d


def test_rodar_todas_grava_alertas(con_semeado):
    con = con_semeado
    con.execute("""insert into emendas (codigo, ano, autor_norm, empenhado, pago,
                   resto_cancelado, recorte)
                   values ('E5',2023,'DEP X',1000000,0,900000,'DESTINO_RJ')""")
    r = pericia.rodar_todas(con, gravar_alertas=True)
    assert r["achados"]
    assert con.execute("select count(*) from alertas where tipo like 'emendas_%'").fetchone()[0] >= 1
    assert set(r["cobertura"]) == {"d1", "d2", "d3", "d4", "d5", "d6"}
