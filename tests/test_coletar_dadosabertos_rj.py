import sqlite3

from tools import coletar_dadosabertos_rj as m

PRE = "Governo\nSecretaria\nSubsecretaria\nTransparencia\nReceitas entre 01/01/2024 e 01/12/2024\n"


def test_numero_virgula_e_inteiro():
    assert m.numero("1216330704,81") == 1216330704.81
    assert m.numero(",02") == 0.02
    assert m.numero("29900") == 29900.0
    assert m.numero("") is None


def test_ler_csv_pula_preambulo_e_aceita_quebra_dentro_de_campo():
    corpo = '"Posição";"Nome";"Valor X"\n"12/2024";"linha\ncom quebra";10,5\n'
    periodo, cab, linhas = m.ler_csv((PRE + corpo).encode("latin1"))
    assert periodo.startswith("Receitas entre")
    assert cab == ["Posição", "Nome", "Valor X"]
    assert linhas == [["12/2024", "linha\ncom quebra", "10,5"]]


def _receita(c, ano, fonte, valor, sub="11145011", cat="1"):
    c.execute("INSERT INTO da_receita (posicao, categoria_economica, sub_alinea, ug, fonte_de_recursos, "
              "valor_previsao_inicial, valor_previsao_atualizada, valor_receita_realizada) VALUES (?,?,?,?,?,?,?,?)",
              (f"12/{ano}", cat, sub, "999900", fonte, valor, valor, valor))


def _base():
    c = sqlite3.connect(":memory:")
    m.garantir(c, "da_receita", ["Posição", "Categoria Economica", "Nome Categoria Economica", "Receita por Fonte",
                                 "Nome Receita por Fonte", "Rubrica", "Nome Rubrica", "Sub Alinea", "Nome Sub Alinea",
                                 "Órgão", "Nome Órgão", "UG", "Nome UG", "Fonte de Recursos",
                                 "Valor Previsão Inicial", "Valor Previsão Atualizada", "Valor Receita Realizada"])
    m.garantir(c, "da_despesa", ["Posição", "UG", "Grupo", "Nome Grupo", "Função", "Nome Função", "Órgão",
                                 "Nome Órgão", "Modalidade Aplicação", "Elemento de Despesa", "Valor Dotação Inicial",
                                 "Valor Dotado Atual", "Valor Empenhado", "Valor Liquidado", "Valor Pago",
                                 "Valor RP Pago", "Valor Total Desembolsado", "Valor RP A Pagar"])
    return c


def test_receita_2024_copias_por_grupo_de_fonte_contam_uma_vez():
    c = _base()
    for f in ("500", "600", "700", "800"):          # o defeito do portal: mesma linha sob 4 fontes
        _receita(c, 2024, f, 48.07e9)
    _receita(c, 2023, "100", 40e9)
    _receita(c, 2023, "200", 40e9)                  # até 2023, fontes 1xx/2xx são legítimas e distintas
    m.criar_visoes(c)
    r = dict(c.execute("SELECT ano, realizada_liquida FROM v_traj_receita_ano").fetchall())
    assert r[2024] == 48.07e9
    assert r[2023] == 80e9


def test_aposentadoria_no_grupo_3_vai_para_pessoal_e_intra_fica_fora():
    c = _base()
    ins = ("INSERT INTO da_despesa (posicao, grupo, modalidade_aplicacao, elemento_de_despesa, valor_empenhado) "
           "VALUES (?,?,?,?,?)")
    c.execute(ins, ("12/2016", "3", "90", "33900100", 10.0))   # aposentadoria classificada em 2016 como grupo 3
    c.execute(ins, ("12/2016", "3", "90", "33903900", 5.0))
    c.execute(ins, ("12/2016", "1", "91", "31911300", 7.0))    # intraorçamentária: fora do consolidado
    _receita(c, 2016, "100", 1.0)
    m.criar_visoes(c)
    g = dict(c.execute("SELECT grupo, empenhado FROM v_traj_despesa_grupo WHERE ano=2016").fetchall())
    assert g == {"1": 10.0, "3": 5.0}
    d = c.execute("SELECT empenhado, empenhado_consolidado FROM v_traj_despesa_ano WHERE ano=2016").fetchone()
    assert d == (22.0, 15.0)
