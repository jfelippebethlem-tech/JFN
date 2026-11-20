# -*- coding: utf-8 -*-
"""A perícia de gastos da PREFEITURA só enxerga contrato de órgão municipal do Rio (20/11/2026).

Medido na base viva: `pcrj_contratos`, apesar do nome, guarda 82.461 contratos FEDERAIS e 19.947 do ESTADO
contra 2.588 da Prefeitura. Os detectores D7/D8/D10/D12 varriam a tabela inteira e gravavam o resultado como
"perícia de gastos da Prefeitura": dos 1.010 alertas de fracionamento, 803 eram de órgão federal (Comando do
Exército, IBGE…), 173 do Estado e só 33 da Prefeitura; da rede societária, 397 federais e 256 do Estado
contra 27. Esfera pela régua única (`esfera_orgao`), nunca pelo nome da tabela.
"""
import pytest

from compliance_agent.emendas import db as edb
from compliance_agent.pcrj import gastos_db, pericia_gastos

PCRJ = "42498733000148"        # raiz 42498733 = Município do Rio (régua: raiz_cnpj)
ESTADO = "42498600000171"      # raiz 42498600 = Estado do RJ
EXERCITO = "00394452000103"    # raiz 00394 = União


@pytest.fixture
def con(tmp_path):
    c = edb.conectar(tmp_path / "t.db")
    edb.init_schema(c)
    gastos_db.init_schema(c)
    c.execute("""create table socios_receita (cnpj_basico text, ident text, nome_socio text,
                 nome_norm text, doc_socio text, qualificacao_cod text, qualificacao_txt text,
                 data_entrada text, faixa_etaria text, fonte_mes text)""")
    c.execute("create table empresas (cnpj text, cep text, data_abertura text, updated_at text)")
    c.commit()
    return c


def _contrato(c, ncp, orgao, nome_orgao, forn, valor, data, nome_forn="FORN"):
    c.execute("""insert into pcrj_contratos (numero_controle_pncp, ano, orgao_cnpj, orgao_nome,
                 fornecedor_documento, fornecedor_nome, tipo, valor_global, data_assinatura)
                 values (?,?,?,?,?,?,'Empenho',?,?)""",
              (ncp, int(data[:4]), orgao, nome_orgao, forn, nome_forn, valor, data))


def _tres_fatias(c, orgao, nome_orgao, forn):
    for i in range(3):
        _contrato(c, f"{orgao}-{forn}-{i}", orgao, nome_orgao, forn, 50000, f"2025-03-{10 + i:02d}")


def test_d7_fracionamento_so_da_prefeitura(con):
    _tres_fatias(con, PCRJ, "MUNICIPIO DE RIO DE JANEIRO", "11222333000181")          # controle positivo
    _tres_fatias(con, EXERCITO, "COMANDO DO EXERCITO", "22333444000181")              # federal: fora
    _tres_fatias(con, ESTADO, "ESTADO DO RIO DE JANEIRO", "33444555000181")           # Estado: fora
    achados = pericia_gastos.d7_fracionamento(con)
    assert [a["evidencias"]["orgao"] for a in achados] == [PCRJ]
    assert achados[0]["evidencias"]["esfera"] == "municipal-rio"


def test_d8_recem_aberto_so_conta_contrato_da_prefeitura(con):
    _contrato(con, "F1", EXERCITO, "COMANDO DO EXERCITO", "11222333000181", 800000, "2025-03-01", "NOVATA FEDERAL")
    _contrato(con, "M1", PCRJ, "MUNICIPIO DE RIO DE JANEIRO", "22333444000181", 800000, "2025-03-01", "NOVATA RIO")
    achados = pericia_gastos.d8_credor_recem_aberto(
        con, consulta_cnpj=lambda cnpj: {"data_inicio_atividade": "2025-01-15"})
    assert [a["evidencias"]["cnpj"] for a in achados] == ["22333444000181"]


def test_d8_nao_soma_contrato_federal_ao_total_do_credor_da_prefeitura(con):
    """O mesmo credor com R$ 60 mil na Prefeitura e R$ 800 mil no Exército: o total 'com a PCRJ' é 60 mil
    (abaixo do mínimo) — antes a soma federal o empurrava para dentro da perícia municipal."""
    _contrato(con, "F1", EXERCITO, "COMANDO DO EXERCITO", "11222333000181", 800000, "2025-03-01")
    _contrato(con, "M1", PCRJ, "MUNICIPIO DE RIO DE JANEIRO", "11222333000181", 60000, "2025-03-01")
    assert pericia_gastos.d8_credor_recem_aberto(
        con, consulta_cnpj=lambda cnpj: {"data_inicio_atividade": "2025-01-15"}) == []


def test_d10_rede_de_socios_so_da_prefeitura(con):
    for orgao, nome, raizes in ((PCRJ, "MUNICIPIO DE RIO DE JANEIRO", ("11111111", "22222222")),
                                (ESTADO, "ESTADO DO RIO DE JANEIRO", ("33333333", "44444444"))):
        for rz in raizes:
            _contrato(con, f"{orgao}-{rz}", orgao, nome, rz + "000100", 10000, "2025-05-05")
    for rz, socio in (("11111111", "FULANO RIO"), ("22222222", "FULANO RIO"),
                      ("33333333", "BELTRANO ESTADO"), ("44444444", "BELTRANO ESTADO")):
        con.execute("insert into socios_receita (cnpj_basico, nome_socio, nome_norm, doc_socio, data_entrada) "
                    "values (?,?,?,?, '20200101')", (rz, socio, socio, "***123456**" if "RIO" in socio else "***654321**"))
    achados = pericia_gastos.d10_rede_concorrentes(con)
    assert [a["evidencias"]["socio"] for a in achados] == ["FULANO RIO"]
    assert achados[0]["evidencias"]["orgao_cnpj"] == PCRJ


def test_d12_coendereco_so_da_prefeitura(con):
    for orgao, nome, docs, cep in ((PCRJ, "MUNICIPIO DE RIO DE JANEIRO", ("11111111000100", "22222222000100"), "20000001"),
                                   (EXERCITO, "COMANDO DO EXERCITO", ("33333333000100", "44444444000100"), "70000002")):
        for d in docs:
            _contrato(con, f"{orgao}-{d}", orgao, nome, d, 10000, "2025-05-05")
            con.execute("insert into empresas values (?,?,?,?)", (d, cep, "2010-01-01", "2026-10-06"))
    achados = pericia_gastos.d12_coendereco_concorrentes(con)
    assert [a["evidencias"]["cep"] for a in achados] == ["20000001"]
    assert achados[0]["evidencias"]["orgao_cnpj"] == PCRJ


# ── leitura: o alerta gravado ANTES do conserto não aparece na aba da Prefeitura ────────────────────────────

@pytest.mark.parametrize("ev,esperado", [
    ({"subtipo": "fracionamento", "orgao": EXERCITO}, "federal"),
    ({"subtipo": "fracionamento", "orgao": ESTADO}, "estadual-rj"),
    ({"subtipo": "fracionamento", "orgao": PCRJ}, "municipal-rio"),
    ({"subtipo": "aditivo_estourado", "controle": f"{EXERCITO}-2-001625/2026"}, "federal"),
    ({"subtipo": "aditivo_estourado", "controle": f"{PCRJ}-2-000001/2026"}, "municipal-rio"),
    ({"subtipo": "rede_socios", "socio": "X"}, ""),                                        # legado sem órgão
    ({"subtipo": "rede_socios", "orgao_cnpj": PCRJ}, "municipal-rio"),
])
def test_esfera_do_alerta(ev, esperado):
    assert pericia_gastos.esfera_do_alerta(ev) == esperado


def test_alerta_da_prefeitura_exige_prova_de_esfera():
    d9 = {"subtipo": "socio_folha", "credor": "01837232000161"}        # despesa CGM × folha municipal: é da casa
    assert pericia_gastos.alerta_e_da_prefeitura("d9_socio_na_folha", d9) is True
    assert pericia_gastos.alerta_e_da_prefeitura("d7_fracionamento", {"orgao": PCRJ}) is True
    assert pericia_gastos.alerta_e_da_prefeitura("d7_fracionamento", {"orgao": EXERCITO}) is False
    assert pericia_gastos.alerta_e_da_prefeitura("d10_rede_concorrentes", {"socio": "X"}) is False   # sem prova ≠ Prefeitura


def test_agrupar_alertas_filtra_esfera_e_conta_o_total_real():
    import json

    def linha(tipo, titulo, ev):
        return {"tipo": tipo, "severidade": "alta", "titulo": titulo, "descricao": "", "evidencias": json.dumps(ev)}
    rows = [linha("pcrj_d7_fracionamento", f"Fracionamento — F{i} × PCRJ", {"subtipo": "fracionamento", "orgao": PCRJ})
            for i in range(5)]
    rows += [linha("pcrj_d7_fracionamento", "Fracionamento — X × COMANDO DO EXERCITO",
                   {"subtipo": "fracionamento", "orgao": EXERCITO}),
             linha("pcrj_d7_fracionamento", "Fracionamento — Y × ESTADO", {"subtipo": "fracionamento", "orgao": ESTADO}),
             linha("pcrj_d10_rede_concorrentes", "Rede societária — legado", {"subtipo": "rede_socios", "socio": "Z"}),
             linha("pcrj_d9_socio_na_folha", "Sócio na folha — W", {"subtipo": "socio_folha"})]
    g = pericia_gastos.agrupar_alertas(rows, limite=3)
    assert g["detectores"] == {"d7_fracionamento": 5, "d9_socio_na_folha": 1}     # total real, não o corte
    assert g["exibidos"] == {"d7_fracionamento": 3, "d9_socio_na_folha": 1}
    assert all(a["evidencias"]["orgao"] == PCRJ for a in g["achados"]["d7_fracionamento"])
    assert g["fora_da_esfera"] == {"d7_fracionamento": {"federal": 1, "estadual-rj": 1},
                                   "d10_rede_concorrentes": {"sem_prova": 1}}
    assert "3 alerta(s)" in g["nota_esfera"]


def test_retira_alerta_gravado_de_outra_esfera_e_preserva_triado_e_sem_prova(con):
    import json
    con.execute("""create table if not exists alertas (id integer primary key, tipo text, severidade text,
                   titulo text, descricao text, evidencias text, status text, created_at text, visto_em text)""")
    casos = [("federal novo", {"subtipo": "aditivo_estourado", "controle": f"{EXERCITO}-2-1/2026"}, "novo"),
             ("estado novo", {"subtipo": "fracionamento", "orgao": ESTADO}, None),
             ("federal triado", {"subtipo": "fracionamento", "orgao": EXERCITO}, "confirmado"),
             ("prefeitura", {"subtipo": "fracionamento", "orgao": PCRJ}, "novo"),
             ("sem prova", {"subtipo": "rede_socios", "socio": "X"}, "novo")]
    for titulo, ev, status in casos:
        con.execute("insert into alertas (tipo, titulo, evidencias, status) values ('pcrj_d7_fracionamento',?,?,?)",
                    (titulo, json.dumps(ev), status))
    con.execute("insert into alertas (tipo, titulo, evidencias, status) values ('emendas_d1','outra perícia',?, 'novo')",
                (json.dumps({"orgao": EXERCITO}),))
    aviso = pericia_gastos.retirar_alertas_de_outra_esfera(con)
    ficou = {r[0] for r in con.execute("select titulo from alertas")}
    assert ficou == {"federal triado", "prefeitura", "sem prova", "outra perícia"}
    assert aviso.startswith("2 alerta(s)") and "federal: 1" in aviso and "estadual-rj: 1" in aviso
