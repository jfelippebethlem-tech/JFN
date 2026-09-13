# -*- coding: utf-8 -*-
"""Pagamento a sancionado e sucessão societária (`tools/pago_a_sancionado.py`).

O que estes testes protegem: o filtro TEMPORAL da `sucessao_societaria`. Sem ele o detector
marcava 178 empresas e R$ 1,02 bi, dos quais 146 casos (82%) tinham a sanção começando DEPOIS de
o sócio já estar na empresa nova — a ordem dos fatos desmentindo a hipótese que o detector nomeia.
Com o filtro: 32 empresas, R$ 39,28 mi. O valor inflava 26×.
"""
import sqlite3


def _banco_sucessao():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE sancoes_federais (cpf_cnpj TEXT, categoria TEXT, data_inicio TEXT, "
                "data_fim TEXT, nome TEXT, orgao TEXT, cadastro TEXT, uf TEXT, processo TEXT, "
                "fundamentacao TEXT)")
    con.execute("CREATE TABLE socios_receita (cnpj_basico TEXT, doc_socio TEXT, nome_socio TEXT, "
                "qualificacao_txt TEXT, data_entrada TEXT)")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (credor TEXT, valor REAL, status TEXT)")
    con.execute("CREATE TABLE empresas_cadastro (cnpj_basico TEXT, razao_social TEXT)")
    # a PUNIDA (11111111) é sancionada; a NOVA (22222222) recebe do Estado
    con.execute("INSERT INTO sancoes_federais VALUES ('11111111000199','Suspensão','2024-05-13',"
                "'2026-05-12','PUNIDA','X','CEIS','RJ','p','f')")
    con.execute("INSERT INTO socios_receita VALUES ('11111111','***1**','FULANO','Sócio-Administrador','20200101')")
    con.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('22222222000199', 5e6, 'Contabilizado')")
    con.execute("INSERT INTO empresas_cadastro VALUES ('22222222','NOVA LTDA')")
    return con


def test_sucessao_exige_sancao_ANTERIOR_a_entrada():
    """A ordem dos fatos É o achado: não há fuga quando a punição ainda não existia.

    Medido em 2026-08-23: sem este filtro, 146 dos 178 casos (82%) tinham a sanção começando
    DEPOIS de o sócio já estar na empresa nova, e o valor somado inflava de R$ 39,28 mi para
    R$ 1,02 bi — 26×. O caso que abriu isso foi a DIMPI: os sócios entraram em 01-02/2026 e a
    punição da origem (RC Gestão) só veio em 13/05/2026.
    """
    from tools.pago_a_sancionado import sucessao_societaria

    con = _banco_sucessao()
    # sócio entrou na NOVA em 2026 — DEPOIS da sanção de 2024-05: sucessão possível
    con.execute("INSERT INTO socios_receita VALUES ('22222222','***1**','FULANO',"
                "'Sócio-Administrador','20260119')")
    assert len(sucessao_societaria(con)) == 1


def test_sancao_POSTERIOR_a_entrada_nao_e_sucessao():
    from tools.pago_a_sancionado import sucessao_societaria

    con = _banco_sucessao()
    # sócio já estava na NOVA em 2019, muito antes da sanção de 2024 — a ordem desmente a hipótese
    con.execute("INSERT INTO socios_receita VALUES ('22222222','***1**','FULANO',"
                "'Sócio-Administrador','20190101')")
    assert sucessao_societaria(con) == []
    assert len(sucessao_societaria(con, temporal=False)) == 1, (
        "o corte sem tempo deve continuar existindo para conferência")


def test_sem_data_de_entrada_fica_de_fora():
    """Data ausente não vira presunção de sucessão — INDISPONÍVEL não é evidência."""
    from tools.pago_a_sancionado import sucessao_societaria

    con = _banco_sucessao()
    con.execute("INSERT INTO socios_receita VALUES ('22222222','***1**','FULANO',"
                "'Sócio-Administrador','')")
    assert sucessao_societaria(con) == []
