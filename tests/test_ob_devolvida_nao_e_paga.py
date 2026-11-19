"""OB devolvida pelo banco ('Erro no Pagamento') não é pagamento em NENHUM detector de cruzamentos_intel.
18/11/2026: 21.044 OB (R$ 5,57 bi, 2021–2026) seguem 'Contabilizado' com status_envio='Erro no Pagamento';
em amostra de 400, 72% têm outra OB Contabilizada do mesmo credor/UG/valor (reemissão) — somar as duas é contar
o pagamento duas vezes; nas demais o dinheiro não chegou ao credor."""
import sqlite3

from compliance_agent import cruzamentos_intel as CI


def test_regra_com_e_sem_coluna_status_envio():
    com = sqlite3.connect(":memory:")
    com.execute("CREATE TABLE ob_orcamentaria_siafe (status TEXT, status_envio TEXT, valor REAL)")
    com.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?)",
                    [("Contabilizado", None, 10.0), ("Contabilizado", "Erro no Pagamento", 99.0),
                     ("Contabilizado", "Enviado", 5.0), ("Cancelado", None, 7.0)])
    assert com.execute(f"SELECT SUM(valor) FROM ob_orcamentaria_siafe WHERE {CI._ob_paga(com)}").fetchone()[0] == 15.0
    sem = sqlite3.connect(":memory:")
    sem.execute("CREATE TABLE ob_orcamentaria_siafe (status TEXT, valor REAL)")
    sem.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?)", [("Contabilizado", 10.0), ("Cancelado", 7.0)])
    assert sem.execute(f"SELECT SUM(valor) FROM ob_orcamentaria_siafe WHERE {CI._ob_paga(sem)}").fetchone()[0] == 10.0


def test_nenhum_detector_usa_a_regra_antiga_direto():
    import inspect
    fonte = inspect.getsource(CI)
    # 2 = a própria _ob_paga + _pagou_apos_baixa, que separa a devolvida por conta própria (conta à parte)
    assert fonte.count("{_OB_PAGA}") == 2, "use _ob_paga(con): a constante não exclui a OB devolvida"


def test_regra_com_alias_de_tabela():
    com = sqlite3.connect(":memory:")
    com.execute("CREATE TABLE ob_orcamentaria_siafe (status TEXT, status_envio TEXT, valor REAL)")
    com.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?)",
                    [("Contabilizado", None, 10.0), ("Contabilizado", "Erro no Pagamento", 99.0)])
    assert CI._ob_paga(com, "o") == ("o.status='Contabilizado' AND COALESCE(o.status_envio,'')<>'Erro no Pagamento'")
    assert com.execute(f"SELECT SUM(o.valor) FROM ob_orcamentaria_siafe o WHERE {CI._ob_paga(com, 'o')}").fetchone()[0] == 10.0


def test_ob_sem_numero_nao_e_paga():
    """18/11/2026: 58 linhas sem numero_ob (uma coleta de 09/08/2026) duplicavam a OB numerada de mesmo PD/valor."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, status TEXT, status_envio TEXT, valor REAL)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?)",
                    [("2026OB29974", "Contabilizado", "Enviado ao Banco", 10.0), ("", "Contabilizado", "", 10.0),
                     (None, "Contabilizado", None, 10.0)])
    assert con.execute(f"SELECT SUM(valor) FROM ob_orcamentaria_siafe WHERE {CI._ob_paga(con)}").fetchone()[0] == 10.0
    assert con.execute(f"SELECT SUM(o.valor) FROM ob_orcamentaria_siafe o WHERE {CI._ob_paga(con, 'o')}").fetchone()[0] == 10.0


def test_pagamento_complementar_nao_e_paga():
    """19/11/2026: 6.905 OB 'Pagamento Complementar' (R$ 294,32 mi), todas 'Enviado Manualmente' — nunca vão ao
    banco: o dinheiro sai na OB principal, que paga o código de barras inteiro e lista as complementares no espelho.
    Prova: FES × Águas de Juturnaíba, 2026OB08840 = R$ 218.665,32 = NL03911 líquida 181.489,48 + complementar
    37.175,84 (lançada 2× como 08790 e 08834); ISS Itaboraí, espelho da 2025OB01938 lista a complementar 01934."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, status TEXT, status_envio TEXT, "
                "tipo_regularizacao TEXT, valor REAL)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?)",
                    [("2026OB08840", "Contabilizado", "Processado e Pago", "", 218665.32),
                     ("2026OB08834", "Contabilizado", "Enviado Manualmente", "Pagamento Complementar", 37175.84),
                     ("2026OB08790", "Contabilizado", "Enviado Manualmente", "Pagamento Complementar", 37175.84),
                     ("2026OB03764", "Contabilizado", "Enviado Manualmente", "OB já encaminhada ao banco", 11437.7)])
    for a, pre in (("", ""), ("o", "o.")):
        tot = con.execute(f"SELECT SUM({pre}valor) FROM ob_orcamentaria_siafe {a} WHERE {CI._ob_paga(con, a)}").fetchone()[0]
        assert round(tot, 2) == 230103.02
