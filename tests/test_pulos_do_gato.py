# -*- coding: utf-8 -*-
"""Detectores dos "pulos do gato" do orçamento — controle positivo E negativo de cada um, em base SINTÉTICA.

Repositório público: nenhum nome, CNPJ ou valor real aqui. Cada detector tem um caso que TEM de acender e um caso
vizinho (a hipótese inocente) que NÃO pode acender.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from compliance_agent import pulos_do_gato as P

CNPJ_A, CNPJ_B = "11111111000111", "22222222000122"


@pytest.fixture
def c():
    con = sqlite3.connect(":memory:")
    con.executescript("""
    CREATE TABLE publicacoes_doerj (id INTEGER, data_publicacao TEXT, secao TEXT, texto TEXT, url_fonte TEXT);
    CREATE TABLE ne_siafe (numero TEXT, ug_emitente TEXT, exercicio INT, data_emissao TEXT, status TEXT, credor TEXT,
      nome_credor TEXT, fonte TEXT, natureza TEXT, tipo_reconhecimento_passivo TEXT, valor REAL);
    CREATE TABLE nl_siafe (numero TEXT, ug_emitente TEXT, status TEXT, ne TEXT);
    CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, status TEXT, tipo_ob TEXT,
      nl TEXT, credor TEXT, nome_credor TEXT, processo TEXT, vinculacao_pagamento TEXT, valor REAL, exercicio INT);
    CREATE TABLE siafe_documento_cobertura (tipo TEXT, ug_emitente TEXT, exercicio INT, completo INT, colhidas INT, em TEXT);
    """)
    return con


@pytest.fixture
def ca():
    con = sqlite3.connect(":memory:")
    cols = ("exercicio INT, periodo INT, periodicidade TEXT, co_poder TEXT, instituicao TEXT, anexo TEXT, rotulo TEXT, "
            "coluna TEXT, cod_conta TEXT, conta TEXT, valor REAL, coletado_em TEXT")
    con.executescript(f"""
    CREATE TABLE siconfi_rreo ({cols});
    CREATE TABLE siconfi_rgf ({cols});
    CREATE TABLE cge_execucao_despesa (ano INT, mes INT, ug TEXT, unidade_gestora TEXT, grupo_de_despesa TEXT,
      fonte_rj TEXT, fonte_stn TEXT, dotacao_inicial REAL, despesas_empenhadas REAL, despesas_orcamentarias_pagas REAL);
    """)
    return con


def rreo(ca, ex, per, anexo, conta, coluna, valor, cod=""):
    ca.execute("INSERT INTO siconfi_rreo VALUES (?,?, 'B','E','Ente sintético',?, '', ?, ?, ?, ?, '')",
               (ex, per, anexo, coluna, cod, conta, valor))


def rgf(ca, ex, conta, coluna, valor):
    ca.execute("INSERT INTO siconfi_rgf VALUES (?,3,'Q','E','Ente sintético','RGF-Anexo 05','',?,'',?,?,'')",
               (ex, coluna, conta, valor))


def decreto(num, dia, valor, itens, linhas=""):
    return (f"DECRETO Nº {num} DE {dia} DE MARÇO DE 2026\nABRE CRÉDITO SUPLEMENTAR A DIVERSOS ÓRGÃOS, NO VA-\n"
            f"LOR GLOBAL DE R$ {valor} PARA REFORÇO DE DOTAÇÕES.\nO GOVERNADOR DO ESTADO, no uso de suas atribuições,\n"
            "CONSIDERANDO:\n- o art. 6º da Lei Estadual nº 11.098, de 08 de janeiro de 2026, que\nestima a Receita e "
            "fixa a Despesa;\nD E C R E T A :\nArt. 1º - Fica aberto crédito suplementar.\nArt. 2º - O crédito será "
            f"compensado na forma do § 2º, {itens}, do art. 120 da Lei Estadual nº 287, de\n04 de dezembro de 1979.\n"
            f"Rio de Janeiro, {dia} de março de 2026\nANEXO\n{linhas}\n")


def _por_titulo(det, trecho):
    return [a for a in det["achados"] if trecho in a["titulo"]]


# ───────────────────────── PG01 · suplementação por decreto ─────────────────────────

def test_decreto_e_lido_com_valor_origem_e_artigo_da_loa(c):
    c.execute("INSERT INTO publicacoes_doerj VALUES (1,'2026-03-10','I',?, 'http://x')",
              (decreto("50.001", "09", "1.000.000,00", "itens 1 e 3"),))
    c.execute("INSERT INTO publicacoes_doerj VALUES (2,'2026-03-10','I',?, 'http://x')",       # mesma página repetida
              (decreto("50.001", "09", "1.000.000,00", "itens 1 e 3"),))
    d, = P.decretos_de_credito(P._textos_decreto(c))
    assert (d["numero"], d["data"], d["valor"], d["itens_art_120"]) == ("50.001", "2026-03-09", 1_000_000.0, ["1", "3"])
    assert (d["loa_artigo"], d["loa_lei"], d["exercicio"], d["tipo"]) == ("6", "11.098", 2026, "suplementar")
    assert d["citacao_itens"] in decreto("50.001", "09", "1.000.000,00", "itens 1 e 3").replace("\n", " ")


def test_decreto_que_nao_e_de_credito_fica_fora(c):
    c.execute("INSERT INTO publicacoes_doerj VALUES (1,'2026-03-10','I',?, '')",
              ("DECRETO Nº 50.002 DE 09 DE MARÇO DE 2026\nALTERA O DECRETO QUE CITA CRÉDITO SUPLEMENTAR ANTERIOR.\n"
               "O GOVERNADOR DO ESTADO\n",))
    assert P.decretos_de_credito(P._textos_decreto(c)) == []


def test_pg01_positivo_piso_de_anulacao_acima_do_limite(c, ca):
    rreo(ca, 2026, 1, "RREO-Anexo 01", "TOTAL DAS DESPESAS (XII) = (X + XI)", "DOTAÇÃO INICIAL (d)", 1_000_000.0)
    c.execute("INSERT INTO publicacoes_doerj VALUES (1,'2026-03-10','I',?, '')",
              (decreto("50.001", "09", "300.000,00", "item 3"),))
    det = P.suplementacao_por_decreto(c, ca)
    v, = [a for a in det["achados"] if a.get("tipo") == "veredito"]
    assert v["piso"] == 300_000.0 and v["limite"] == 200_000.0 and v["estado"] == P.PENDENTE
    assert "PISO de anulação já supera" in v["detalhe"] and det["prevalencia"]["acionados"] == 1
    assert "empenho" not in v["estagio"] and "pag" not in v["estagio"]


def test_pg01_negativo_teto_de_anulacao_abaixo_do_limite(c, ca):
    rreo(ca, 2026, 1, "RREO-Anexo 01", "TOTAL DAS DESPESAS (XII) = (X + XI)", "DOTAÇÃO INICIAL (d)", 10_000_000.0)
    c.execute("INSERT INTO publicacoes_doerj VALUES (1,'2026-03-10','I',?, '')",
              (decreto("50.001", "09", "300.000,00", "itens 1 e 3"),))
    c.execute("INSERT INTO publicacoes_doerj VALUES (2,'2026-03-11','I',?, '')",   # só superávit: não entra no teto
              (decreto("50.003", "10", "9.000.000,00", "item 1"),))
    det = P.suplementacao_por_decreto(c, ca)
    v, = [a for a in det["achados"] if a.get("tipo") == "veredito"]
    assert (v["piso"], v["teto"]) == (0.0, 300_000.0) and "abaixo do limite" in v["detalhe"]
    assert v["estado"] == P.PENDENTE and "TODOS os decretos" in v["por_que_estado"]   # cobertura não provada
    assert det["prevalencia"]["acionados"] == 0


def test_pg01_decreto_sem_origem_conta_inteiro_no_teto(c, ca):
    rreo(ca, 2026, 1, "RREO-Anexo 01", "TOTAL DAS DESPESAS (XII) = (X + XI)", "DOTAÇÃO INICIAL (d)", 1_000_000.0)
    sem = decreto("50.004", "09", "250.000,00", "item 3").replace("§ 2º, item 3, do art. 120", "art. 120")
    c.execute("INSERT INTO publicacoes_doerj VALUES (1,'2026-03-10','I',?, '')", (sem,))
    v, = [a for a in P.suplementacao_por_decreto(c, ca)["achados"] if a.get("tipo") == "veredito"]
    assert (v["piso"], v["teto"]) == (0.0, 250_000.0) and "50.004" in v["detalhe"] and "indeterminado" in v["detalhe"]


def test_pg01_exercicio_sem_limite_cadastrado_e_indisponivel(c, ca):
    c.execute("INSERT INTO publicacoes_doerj VALUES (1,'2026-03-10','I',?, '')",
              (decreto("50.001", "09", "300.000,00", "item 3"),))                    # sem RREO: não há despesa fixada
    v, = [a for a in P.suplementacao_por_decreto(c, ca)["achados"] if a.get("tipo") != "evidencia"]
    assert v["estado"] == P.INDISPONIVEL


# ───────────────────────── PG03 · DEA recorrente ─────────────────────────

def _ne(c, num, cnpj, mes, natureza="339092", valor=1000.0, status="Contabilizado", ug="999900"):
    c.execute("INSERT INTO ne_siafe VALUES (?,?,2025,?,?,?,?, '100', ?, 'Passivo reconhecido previamente', ?)",
              (num, ug, f"10/{mes:02d}/2025", status, cnpj, "EMPRESA SINTETICA " + cnpj[:2], natureza, valor))


def test_pg03_positivo_dea_em_tres_meses_com_pago_pela_cadeia(c):
    for i, mes in enumerate((2, 5, 9)):
        _ne(c, f"2025NE0000{i}", CNPJ_A, mes)
    c.execute("INSERT INTO nl_siafe VALUES ('2025NL00001','999900','Contabilizado','2025NE00000')")
    c.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('2025OB1','999900','01/03/2025','Contabilizado','Orçamentária',"
              "'2025NL00001',?, 'X','', '86 - FORNECEDORES', 700.0, 2025)", (CNPJ_A,))
    c.execute("INSERT INTO ob_orcamentaria_siafe VALUES ('2025OB2','999900','02/03/2025','Anulado','Orçamentária',"
              "'2025NL00001',?, 'X','', '86 - FORNECEDORES', 300.0, 2025)", (CNPJ_A,))   # OB anulada não é pagamento
    c.execute("INSERT INTO siafe_documento_cobertura VALUES ('NE','999900',2025,1,3,'')")
    a, = P.dea_recorrente(c)["achados"]
    assert (a["valor"], a["pago_ob"], a["meses"], a["estado"]) == (3000.0, 700.0, 3, P.VERIFICADO)
    assert a["estagio"].startswith("empenhado") and "não é pagamento" in a["estagio"]


def test_pg03_negativo_dea_em_um_mes_e_despesa_do_exercicio_recorrente(c):
    for i in range(3):
        _ne(c, f"2025NE1000{i}", CNPJ_A, 4)                      # três DEA no MESMO mês: reconhecimento único
    for i, mes in enumerate((1, 2, 3, 4)):
        _ne(c, f"2025NE2000{i}", CNPJ_B, mes, natureza="339039")  # despesa corrente do próprio exercício
    for i, mes in enumerate((1, 2, 3)):
        _ne(c, f"2025NE3000{i}", "33333333000133", mes, natureza="334092")   # DEA de repasse a outro ente (modalidade 40)
        _ne(c, f"2025NE4000{i}", "44444444000144", mes, status="Anulado")    # empenho anulado não conta
    det = P.dea_recorrente(c)
    assert det["achados"] == []
    assert "não é sinal" in det["prevalencia"]["contexto"]


def test_pg03_cobertura_parcial_rebaixa_para_pendente(c):
    for i, mes in enumerate((2, 5, 9)):
        _ne(c, f"2025NE0000{i}", CNPJ_A, mes)
    a, = P.dea_recorrente(c)["achados"]
    assert a["estado"] == P.PENDENTE and "piso" in a["por_que_estado"]


# ───────────────────────── PG04 · restos a pagar ─────────────────────────

def _anexo07(ca, ex, per, inscritos, cancelados):
    for col, v in (("Em Exercícios Anteriores (f)", 0.0), (f"Em 31 de dezembro de {ex - 1} (g)", inscritos),
                   ("Cancelados (j)", cancelados), ("Cancelados (d)", 0.0), ("Saldo Total L = (e + k)", 1.0)):
        rreo(ca, ex, per, "RREO-Anexo 07", "TOTAL (III) = (I + II)", col, v)


def test_pg04_positivo_e_negativo(ca):
    _anexo07(ca, 2024, 6, 1000.0, 600.0)      # 60% cancelado → acende
    _anexo07(ca, 2025, 6, 1000.0, 20.0)       # 2% → não acende
    det = P.restos_a_pagar(ca)
    por_ano = {a["ano"]: a for a in det["achados"]}
    assert por_ano[2024]["acende"] and not por_ano[2025]["acende"]
    assert det["prevalencia"]["acionados"] == 1 and det["prevalencia"]["base"] == 2
    assert all(a["estado"] == P.PENDENTE and "CANCELADOS" in a["estagio"] for a in det["achados"])


# ───────────────────────── PG05 · art. 42 ─────────────────────────

def test_pg05_positivo_negativo_e_ano_ainda_nao_publicado(ca):
    liq = "DISPONIBILIDADE DE CAIXA LÍQUIDA (APÓS A INSCRIÇÃO EM RESTOS A PAGAR NÃO PROCESSADOS DO EXERCÍCIO) (i) = (g - h)"
    rgf(ca, 2022, "Recursos Não Vinculados de Impostos", liq, -500.0)     # fim de mandato, negativo → acende
    rgf(ca, 2022, "Transferências do FUNDEB", liq, 80.0)                  # positivo → não acende
    rgf(ca, 2022, "TOTAL (IV) = (I + II + III)", liq, -420.0)             # linha de total não entra na base
    rgf(ca, 2023, "Recursos Não Vinculados de Impostos", liq, -10.0)      # negativo fora de fim de mandato
    det = P.caixa_art_42(ca, hoje=date(2026, 11, 13))
    neg = [a for a in det["achados"] if a["valor"] is not None and a["valor"] < 0]
    assert {(a["ano"], a["fim_de_mandato"]) for a in neg} == {(2022, True), (2023, False)}
    assert "art. 42 não incide" in next(a for a in neg if a["ano"] == 2023)["detalhe"]
    assert det["prevalencia"]["base"] == 3 and det["prevalencia"]["acionados"] == 2
    pend, = [a for a in det["achados"] if a["estado"] == P.INDISPONIVEL]
    assert pend["ano"] == 2026 and pend["valor"] is None                   # ausência não vira zero


# ───────────────────────── PG06 · troca de fonte ─────────────────────────

LINHA = "18010.12.368.0443.2033\nApoio\nF\n3390.00\nAplicações Diretas\n{v}\n{fr}\n"


def test_pg06_positivo_mesma_dotacao_so_a_fonte_muda(c, ca):
    linhas = LINHA.format(v="1,520,000.00", fr="1.500.100") + LINHA.format(v="1,520,000.00", fr="1.761.122")
    c.execute("INSERT INTO publicacoes_doerj VALUES (1,'2026-03-10','I',?, '')",
              (decreto("50.001", "09", "1.520.000,00", "item 3", linhas),))
    a, = [x for x in P.troca_de_fonte(c, ca)["achados"] if x.get("eixo") == "troca_em_decreto"]
    assert a["valor"] == 1_520_000.0 and "1.500.100" in a["titulo"] and "1.761.122" in a["titulo"]
    assert a["vinculada"] and "VINCULADA e fonte livre" in a["titulo"]
    assert a["estado"] == P.PENDENTE                                       # pareamento heurístico nunca é VERIFICADO


def test_pg06_negativo_remanejamento_entre_acoes_na_mesma_fonte(c, ca):
    linhas = (LINHA.format(v="1,520,000.00", fr="1.500.100")
              + LINHA.replace("2033", "2318").format(v="1,520,000.00", fr="1.500.100"))
    c.execute("INSERT INTO publicacoes_doerj VALUES (1,'2026-03-10','I',?, '')",
              (decreto("50.001", "09", "1.520.000,00", "item 3", linhas),))
    assert [x for x in P.troca_de_fonte(c, ca)["achados"] if x.get("eixo") == "troca_em_decreto"] == []


def _cge(ca, ano, mes, ug, grupo, fonte_rj, fonte_stn, dot, emp, pago=0.0):
    ca.execute("INSERT INTO cge_execucao_despesa VALUES (?,?,?,?,?,?,?,?,?,?)",
               (ano, mes, ug, f"{ug} - UNIDADE SINTETICA", grupo, fonte_rj, fonte_stn, dot, emp, pago))


def test_pg06_fundo_sem_execucao_positivo_e_negativo(c, ca):
    _cge(ca, 2025, 12, "100100", "3 - OUTRAS DESPESAS CORRENTES", "151 - Recursos Vinculados a Fundos",
         "759 - Recursos Vinculados a Fundos", 10e6, 1e6)                  # 10% empenhado → acende
    _cge(ca, 2025, 12, "100100", "3 - OUTRAS DESPESAS CORRENTES", "152 - Recursos Vinculados a Fundos",
         "759 - Recursos Vinculados a Fundos", 10e6, 9e6)                  # 90% → não acende
    _cge(ca, 2026, 7, "100100", "3 - OUTRAS DESPESAS CORRENTES", "151 - Recursos Vinculados a Fundos",
         "759 - Recursos Vinculados a Fundos", 10e6, 0.0)                  # exercício aberto: não se mede
    ach = [x for x in P.troca_de_fonte(None, ca)["achados"] if x.get("eixo") == "fundo_sem_execucao"]
    assert [(a["ano"], a["titulo"].split(" em ")[0]) for a in ach] == [(2025, "Fonte de fundo 151")]
    assert "não é despesa nem pagamento" in ach[0]["estagio"]


# ───────────────────────── PG07 · reserva de contingência ─────────────────────────

def test_pg07_positivo_reducao_e_composicao_que_fecha(ca):
    rreo(ca, 2026, 4, "RREO-Anexo 01", "RESERVA DE CONTINGÊNCIA", "DOTAÇÃO INICIAL (d)", 1000.0)
    rreo(ca, 2026, 4, "RREO-Anexo 01", "RESERVA DE CONTINGÊNCIA", "DOTAÇÃO ATUALIZADA (e)", 900.0)
    _cge(ca, 2026, 1, "123499", "9 - RESERVA DE CONTINGÊNCIA", "234 - RPPS", "800 - RPPS", 950.0, 0.0)
    _cge(ca, 2026, 1, "370200", "9 - RESERVA DE CONTINGÊNCIA", "100 - Livres", "500 - Livres", 50.0, 0.0)
    a, = P.reserva_de_contingencia(None, ca)["achados"]
    assert a["acende"] and a["valor"] == 100.0 and a["estado"] == P.VERIFICADO     # duas fontes concordam no total
    assert [p["valor"] for p in a["composicao"]] == [950.0, 50.0]


def test_pg07_negativo_sem_reducao_e_fontes_divergentes(ca):
    rreo(ca, 2025, 6, "RREO-Anexo 01", "RESERVA DE CONTINGÊNCIA", "DOTAÇÃO INICIAL (d)", 1000.0)
    rreo(ca, 2025, 6, "RREO-Anexo 01", "RESERVA DE CONTINGÊNCIA", "DOTAÇÃO ATUALIZADA (e)", 1000.0)
    _cge(ca, 2025, 1, "123499", "9 - RESERVA DE CONTINGÊNCIA", "234 - RPPS", "800 - RPPS", 700.0, 0.0)
    det = P.reserva_de_contingencia(None, ca)
    a, = det["achados"]
    assert not a["acende"] and a["estado"] == P.PENDENTE and det["prevalencia"]["acionados"] == 0


# ───────────────────────── PG09 · dezembro ─────────────────────────

def test_pg09_positivo_e_negativo(c, ca):
    for mes in range(1, 13):
        _cge(ca, 2025, mes, "100100", "3 - OUTRAS DESPESAS CORRENTES", "100 - x", "500 - x", 0, 60e6 if mes == 12 else 5e6)
        _cge(ca, 2025, mes, "200200", "3 - OUTRAS DESPESAS CORRENTES", "100 - x", "500 - x", 0, 10e6)   # uniforme
        _cge(ca, 2025, mes, "300300", "1 - PESSOAL E ENCARGOS SOCIAIS", "100 - x", "500 - x", 0,
             90e6 if mes == 12 else 5e6)                                   # 13º salário: pessoal fica fora
    _cge(ca, 2026, 6, "100100", "3 - OUTRAS DESPESAS CORRENTES", "100 - x", "500 - x", 0, 99e6)         # ano aberto
    det = P.empenho_em_dezembro(c, ca)
    a, = det["achados"]
    assert a["ug"] == "100100" and a["valor"] == 60e6 and a["estagio"] == "empenhado (não é pagamento)"
    assert det["prevalencia"]["base"] == 2 and det["prevalencia"]["acionados"] == 1
    assert "INDISPONÍVEL" in a["detalhe"]                                  # sem NE coletada: declara, não zera


# ───────────────────────── PG10 · ordem cronológica ─────────────────────────

def _ob(c, n, nl, dia_mes, cnpj=CNPJ_B, vinc="86 - FORNECEDORES", status="Contabilizado", valor=100.0):
    c.execute("INSERT INTO ob_orcamentaria_siafe VALUES (?, '999900', ?, ?, 'Orçamentária', ?, ?, 'EMPRESA SINTETICA', "
              "'SEI-000000/000001/2025', ?, ?, 2025)", (f"2025OB{n:05d}", f"{dia_mes}/2025", status, nl, cnpj, vinc, valor))


def test_pg10_positivo_liquidacao_antiga_paga_depois_de_dez_posteriores(c):
    _ob(c, 1, "2025NL00001", "20/06", cnpj=CNPJ_A, valor=5000.0)           # a mais antiga, paga por último
    for i in range(2, 13):
        _ob(c, i, f"2025NL{i:05d}", "05/03")                               # 11 posteriores pagas 107 dias antes
    det = P.ordem_cronologica(c)
    a, = det["achados"]
    assert (a["cnpj"], a["posteriores"], a["valor"], a["valor_posteriores"]) == (CNPJ_A, 11, 5000.0, 1100.0)
    assert a["estado"] == P.PENDENTE and a["estagio"].startswith("pago por OB contabilizada")
    assert det["prevalencia"]["base"] == 12 and det["total_acionados"] == 1


def test_pg10_negativo_fila_respeitada_outra_vinculacao_e_ob_anulada(c):
    for i in range(1, 13):
        _ob(c, i, f"2025NL{i:05d}", f"{i:02d}/03")                         # pagas na ordem da liquidação
    _ob(c, 20, "2025NL00000", "20/06", cnpj=CNPJ_A, vinc="93 - Obrigações Patronais, Tributárias e Contributivas")
    _ob(c, 21, "2025NL00000", "20/06", cnpj=CNPJ_A, vinc="87 - JUDICIAIS")
    for i in range(30, 45):
        _ob(c, i, f"2025NL{i:05d}", "05/01", status="Anulado")             # OB anulada não é pagamento
    c.execute("UPDATE ob_orcamentaria_siafe SET nome_credor='FUNDO MUNICIPAL DE SAUDE SINTETICO', "
              "data_emissao='20/09/2025' WHERE numero_ob='2025OB00001'")   # repasse a ente público, pago por último
    assert P.ordem_cronologica(c)["achados"] == []


def test_pg10_atraso_curto_nao_acende(c):
    _ob(c, 1, "2025NL00001", "20/03", cnpj=CNPJ_A)
    for i in range(2, 13):
        _ob(c, i, f"2025NL{i:05d}", "05/03")                               # só 15 dias de diferença
    assert P.ordem_cronologica(c)["achados"] == []


# ───────────────────────── PG15 · mínimos ─────────────────────────

def _indice(ca, ex, conta, apurado, minimo, aplicado, funcao, emp, rpnp):
    for col, v in (("Valor Apurado Até o Bimestre", apurado), ("% Mínimo a Aplicar no Exercício", minimo),
                   ("% Aplicado Até o Bimestre", aplicado)):
        rreo(ca, ex, 6, "RREO-Anexo 14", conta, col, v)
    rreo(ca, ex, 6, "RREO-Anexo 02", funcao, "DESPESAS EMPENHADAS ATÉ O BIMESTRE (b)", emp, "RREO2TotalDespesas")
    rreo(ca, ex, 6, "RREO-Anexo 02", funcao, "INSCRITAS EM RESTOS A PAGAR NÃO PROCESSADOS (f)", rpnp, "RREO2TotalDespesas")
    rreo(ca, ex, 6, "RREO-Anexo 02", funcao, "INSCRITAS EM RESTOS A PAGAR NÃO PROCESSADOS (f)", 999.0,
         "RREO2TotalDespesasIntra")                                        # linha intra não pode contaminar


SAUDE = "Despesas com Ações e Serviços Públicos de Saúde Executadas com Recursos de Impostos"
MDE = "Mínimo Anual de <18% / 25%> das Receitas de Impostos na Manutenção e Desenvolvimento do Ensino"


def test_pg15_positivo_folga_menor_que_rp_e_indice_abaixo_do_minimo(ca):
    _indice(ca, 2024, SAUDE, 1210.0, 12.0, 12.1, "Saúde", 2000.0, 50.0)    # folga 10 < RP 50 → acende
    _indice(ca, 2024, MDE, 2380.0, 25.0, 23.8, "Educação", 3000.0, 1.0)    # abaixo do mínimo → acende
    det = P.minimos_com_restos_a_pagar(ca)
    assert all(a["acende"] for a in det["achados"]) and det["prevalencia"]["acionados"] == 2
    s = next(a for a in det["achados"] if "Saúde" in a["titulo"])
    assert s["folga"] == pytest.approx(10.0) and s["valor"] == 50.0 and "INDISPONÍVEL" in s["detalhe"]


def test_pg15_negativo_folga_larga(ca):
    _indice(ca, 2025, SAUDE, 1500.0, 12.0, 15.0, "Saúde", 2000.0, 50.0)    # folga 300 > RP 50
    det = P.minimos_com_restos_a_pagar(ca)
    a, = det["achados"]
    assert not a["acende"] and det["prevalencia"]["acionados"] == 0


# ───────────────────────── contrato comum, manual, filtro ─────────────────────────

def test_fonte_ausente_e_indisponivel_e_nunca_lista_vazia():
    vazio = sqlite3.connect(":memory:")
    for det in (P.suplementacao_por_decreto(vazio, vazio), P.dea_recorrente(vazio), P.restos_a_pagar(vazio),
                P.caixa_art_42(vazio), P.reserva_de_contingencia(vazio, vazio), P.empenho_em_dezembro(vazio, vazio),
                P.ordem_cronologica(vazio), P.minimos_com_restos_a_pagar(vazio)):
        a, = det["achados"]
        assert a["estado"] == P.INDISPONIVEL and a["valor"] is None


def test_rota_serve_o_recorte_e_declara_quando_nao_rodou(tmp_path, monkeypatch):
    import json

    from rotas import comissao as R
    monkeypatch.setattr(P, "SAIDA", tmp_path / "pulos.json")
    assert R.api_comissao_pulos().status_code == 404                       # ainda não rodou: diz, não inventa
    P.gravar({"ok": True, "detectores": [{"id": "PG04", "achados": [{"ano": 2025, "mes": 12}, {"ano": 2024, "mes": 12}]}]})
    r = json.loads(R.api_comissao_pulos(ano=2025, mes=13).body)            # mês inválido = sem filtro de mês
    assert r["filtro"] == {"ano": 2025, "mes": None} and r["detectores"][0]["achados"] == [{"ano": 2025, "mes": 12}]


def test_prevalencia_alta_nao_acende_sozinha():
    assert P._prev("x", 100, 9)["acende_sozinho"] and not P._prev("x", 100, 10)["acende_sozinho"]
    assert P._prev("x", 0, 0)["taxa"] is None and not P._prev("x", 0, 0)["acende_sozinho"]


def test_todo_achado_traz_estado_estagio_e_proveniencia(c, ca, tmp_path):
    test_pg04_positivo_e_negativo(ca)
    for i, mes in enumerate((2, 5, 9)):
        _ne(c, f"2025NE0000{i}", CNPJ_A, mes)
    achados = P.restos_a_pagar(ca)["achados"] + P.dea_recorrente(c)["achados"]
    assert achados
    for a in achados:
        assert a["estado"] in (P.VERIFICADO, P.PENDENTE, P.INDISPONIVEL)
        assert a["proveniencia"] and a["por_que_estado"] and a["estagio"]
        assert not a["estagio"].lower().startswith("pago") or "ob" in a["estagio"].lower()


def test_manual_ao_lado_e_filtro_por_ano_e_mes(tmp_path):
    man = tmp_path / "manual.md"
    man.write_text("## 11. PULOS\n\n### PULO 4. Restos a pagar: inscrever e cancelar\n\n| | |\n|---|---|\n"
                   "| **Como funciona** | Inscreve-se e depois cancela-se. |\n| **Base legal** | Lei 4.320, art. 36 |\n\n"
                   "### PULO 9. Empenho de fim de ano\n\n| | |\n|---|---|\n| **Gravidade** | 2 |\n", encoding="utf-8")
    t = P.trechos_do_manual(man)
    assert t[4]["titulo"].startswith("Restos a pagar") and t[4]["campos"]["Base legal"] == "Lei 4.320, art. 36"
    assert t[9]["campos"] == {"Gravidade": "2"} and P.trechos_do_manual(tmp_path / "nao_existe.md") == {}
    painel = {"detectores": [{"id": "X", "achados": [{"ano": 2025, "mes": 12}, {"ano": 2025, "mes": None},
                                                    {"ano": 2026, "mes": 3}, {"ano": None, "mes": None}]}]}
    f = P.filtrar(painel, ano=2025, mes=3)["detectores"][0]
    assert f["achados"] == [{"ano": 2025, "mes": None}, {"ano": None, "mes": None}] and f["n_total"] == 4
    assert len(P.filtrar(painel, ano=2025)["detectores"][0]["achados"]) == 3
    assert len(P.filtrar(painel)["detectores"][0]["achados"]) == 4


def test_rodar_sem_bases_nao_quebra_e_gravar_ler(tmp_path):
    p = P.rodar(tmp_path / "a.db", tmp_path / "b.db", tmp_path / "m.md")
    assert p["ok"] and len(p["detectores"]) == len(P.DETECTORES) and not p["manual_lido"]
    assert all(d["estados"] == {P.INDISPONIVEL: 1} for d in p["detectores"])
    P.gravar(p, tmp_path / "s.json")
    assert P.ler(tmp_path / "s.json")["detectores"][0]["id"] == "PG01" and P.ler(tmp_path / "x.json") is None
