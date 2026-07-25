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
    # split 2026-07-18: d10 = SÓ rede societária; aditivo estourado virou detector próprio (d11)
    achados = pericia_gastos.d10_rede_concorrentes(con)
    tipos = {a["evidencias"].get("subtipo") for a in achados}
    assert tipos == {"rede_socios"}
    aditivos = pericia_gastos.d11_aditivo_estourado(con)
    assert {a["evidencias"].get("subtipo") for a in aditivos} == {"aditivo_estourado"}
    assert all(a["detector"] == "d11_aditivo_estourado" for a in aditivos)


def test_rodar_todas_cobertura(con_semeado):
    r = pericia_gastos.rodar_todas(con_semeado)
    assert set(r["cobertura"]) == {"d7", "d8", "d9", "d10", "d11", "d12"}


def test_teto_dispensa_datado_por_ano():
    """O teto vem da FONTE ÚNICA, nunca de um número digitado aqui.

    Este teste afirmava `teto_dispensa(2026) == 62_725.68` — e **62.725,68 não é o teto de
    2026 nem de ano nenhum**: o de 2026 é R$ 65.492,11 (Decreto 12.807/2025) e o de 2025 é
    R$ 62.725,59. O teste estava travando o valor errado, o que é pior que não haver teste:
    impedia a correção. Agora ele compara com `limites_dispensa`, onde os valores foram
    conferidos verbatim nos decretos — assim não há como os dois divergirem de novo.
    """
    from compliance_agent.limites_dispensa import LIMITES, limite_dispensa

    for ano in LIMITES:
        assert pericia_gastos.teto_dispensa(ano) == limite_dispensa(ano, "compras")
    assert pericia_gastos.teto_dispensa(2026) == 65_492.11      # Decreto 12.807/2025
    assert pericia_gastos.teto_dispensa(2025) == 62_725.59      # Decreto 12.343/2024
    assert pericia_gastos.teto_dispensa(2024) == 59_906.02      # Decreto 11.871/2023
    # ano futuro sem decreto publicado usa o último conhecido — fallback honesto
    assert pericia_gastos.teto_dispensa(2027) == pericia_gastos.teto_dispensa(max(LIMITES))
    assert pericia_gastos.teto_dispensa() > 0


def test_d7_usa_o_teto_do_ANO_da_contratacao(con_semeado):
    """O teto sobe todo ano; um valor único faz falso positivo num ano e falso negativo noutro.

    Cenário: mesmo valor de contrato (R$ 61.000) em 2024 e em 2026.
      · 2024 — teto R$ 59.906,02 → está ACIMA do teto, não é dispensa, NÃO pode entrar;
      · 2026 — teto R$ 65.492,11 → está abaixo do teto, PODE entrar.
    Com teto único (o que havia), os dois anos recebiam o mesmo tratamento e um deles saía
    errado — foi o defeito medido: 46 contratos de 2024 entravam indevidamente e 35 de 2026
    sumiam.
    """
    con = con_semeado
    con.execute("delete from pcrj_contratos")
    for i, (ano, dia) in enumerate([(2024, "05"), (2024, "15"), (2024, "25"),
                                    (2026, "05"), (2026, "15"), (2026, "25")]):
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       fornecedor_documento, fornecedor_nome, orgao_nome, tipo, valor_global,
                       data_assinatura)
                       values (?,?,?,?,?,?,?,?,?)""",
                    (f"nc{i}", ano, "111", "222", "FORN X", "ORGAO Y", "contrato",
                     61_000.0, f"{ano}-03-{dia}"))
    con.commit()
    anos = {a["evidencias"]["controles_pncp"][0] for a in pericia_gastos.d7_fracionamento(con)}
    achados = pericia_gastos.d7_fracionamento(con)
    assert len(achados) == 1, (
        "só 2026 pode acender: em 2024 R$ 61.000 está ACIMA do teto de R$ 59.906,02 "
        f"e não é contratação por dispensa. Achados: {[a['titulo'] for a in achados]}")
    assert "2026" in achados[0]["descricao"], "a evidência tem de citar o teto do ano certo"
    assert "65.492,11" in achados[0]["descricao"]
    assert anos


def test_d8_usa_cadastro_local_antes_da_api(con_semeado):
    con = con_semeado
    con.execute("""create table empresas (cnpj text, razao_social text, situacao text,
                   data_abertura text, cep text)""")
    con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                   fornecedor_documento, fornecedor_nome, tipo, valor_global, data_assinatura)
                   values ('L1',2025,'42498733000148','11222333000181','LOCAL LTDA',
                           'Contrato',900000,'2025-03-01')""")
    con.execute("insert into empresas (cnpj, data_abertura) values ('11222333000181','2025-01-15')")
    def api_fora_do_ar(cnpj):
        return None   # minhareceita indisponível — antes disso o D8 zerava silenciosamente
    achados = pericia_gastos.d8_credor_recem_aberto(con, consulta_cnpj=api_fora_do_ar)
    assert len(achados) == 1 and "LOCAL" in achados[0]["titulo"]


def test_d12_coendereco_entre_concorrentes(con_semeado):
    con = con_semeado
    con.execute("""create table empresas (cnpj text, razao_social text, situacao text,
                   data_abertura text, cep text)""")
    # dois fornecedores do MESMO órgão/ano com o MESMO CEP → indício OCDE
    for doc, nome in (("11222333000181", "ALFA"), ("44555666000199", "BETA")):
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       orgao_nome, fornecedor_documento, fornecedor_nome, tipo, valor_global,
                       data_assinatura) values (?,2025,'42498733000148','PCRJ',?,?,
                       'Contrato',100000,'2025-02-01')""", (f"CE-{doc}", doc, nome))
        con.execute("insert into empresas (cnpj, cep) values (?, '20031-170')", (doc,))
    achados = pericia_gastos.d12_coendereco_concorrentes(con)
    assert len(achados) == 1
    assert achados[0]["evidencias"]["cep"] == "20031-170"
    assert "OCDE" in achados[0]["descricao"] or "endereço" in achados[0]["descricao"]


def test_d12_guard_cep_popular(con_semeado):
    con = con_semeado
    con.execute("""create table empresas (cnpj text, razao_social text, situacao text,
                   data_abertura text, cep text)""")
    # CEP compartilhado por MUITAS empresas da base (edifício comercial) → guard descarta
    for i in range(2):
        doc = f"1122233300018{i}"
        con.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj,
                       fornecedor_documento, tipo, valor_global, data_assinatura)
                       values (?,2025,'42498733000148',?,'Contrato',100000,'2025-02-01')""",
                    (f"CP{i}", doc))
        con.execute("insert into empresas (cnpj, cep) values (?, '20000-000')", (doc,))
    for i in range(6):  # +6 empresas quaisquer no mesmo CEP = popular
        con.execute("insert into empresas (cnpj, cep) values (?, '20000-000')", (f"9988877700010{i}",))
    assert pericia_gastos.d12_coendereco_concorrentes(con) == []
