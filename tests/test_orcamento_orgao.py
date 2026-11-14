# -*- coding: utf-8 -*-
"""Aba "Orçamento por órgão" — controle positivo, controles negativos e INDISPONÍVEL ≠ 0.

Controle positivo com VALOR REAL: o órgão 01 (Assembleia Legislativa) em 2024, com os números das duas UG como
estão no arquivo `despesa_generica2024.csv` do portal de dados abertos do Estado (sha256 7ad0b78e…5ce17, baixado e
somado à mão em 14/11/2026): dotação atualizada R$ 1.351.180.554,00, empenhado R$ 1.312.019.851,41, pago do
balancete R$ 1.299.714.492,53 → 97,1% e 96,2%. O resto é sintético (nenhum credor, nenhuma pessoa).
"""
import sqlite3

import pytest

from compliance_agent import orcamento_orgao as O
from compliance_agent.qualidade.verificadores import proveniencia_incompleta

# (posicao, uo, ug, nome_ug, orgao, nome_orgao, poder, modalidade, dot_ini, dot_atual, emp, liq, pago, rp_pago)
_ALERJ = [
    ("12/2024", "0101", "010100", "ASSEMBLEIA LEGISLATIVA", "01", "Assembleia Legislativa", "2", "90",
     1606165841.00, 1324165841.00, 1295477437.52, 1295464659.52, 1283172078.64, 11863367.59),
    ("12/2024", "0161", "016100", "FUNDO ESPECIAL DA ASSEMBLEIA", "01", "Assembleia Legislativa", "2", "90",
     27014713.00, 27014713.00, 16542413.89, 16542413.89, 16542413.89, 0.0),
]
# órgão 50 (sintético, Executivo): UG 500100 com dotação; a UG 600100 (do órgão 60) executa R$ 100 de crédito do 50
_SINT = [
    ("12/2024", "5001", "500100", "SECRETARIA A", "50", "Secretaria A", "1", "90", 1000.0, 1200.0, 800.0, 700.0, 600.0, 50.0),
    ("12/2024", "5001", "500100", "SECRETARIA A", "50", "Secretaria A", "1", "99", 0.0, 300.0, 0.0, 0.0, 0.0, 0.0),
    ("12/2024", "5001", "600100", "SECRETARIA B", "50", "Secretaria A", "1", "90", 0.0, 0.0, 100.0, 100.0, 100.0, 0.0),
    ("12/2024", "6001", "600100", "SECRETARIA B", "60", "Secretaria B", "1", "90", 5000.0, 5000.0, 4000.0, 4000.0, 4000.0, 0.0),
    ("12/2024", "7001", "700100", "ENCARGOS SEM OB", "70", "Encargos", "1", "90", 900.0, 900.0, 900.0, 900.0, 900.0, 0.0),
]


def _abertos(caminho, linhas, cge=(), cge_atualizado="2026-07-15 17:11:36"):
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE da_despesa (recurso_id TEXT, posicao TEXT, codigo_uo TEXT, nome_uo TEXT, ug TEXT, "
                "nome_ug TEXT, orgao TEXT, nome_orgao TEXT, poder TEXT, modalidade_aplicacao TEXT, "
                "valor_dotacao_inicial REAL, valor_dotado_atual REAL, valor_empenhado REAL, valor_liquidado REAL, "
                "valor_pago REAL, valor_rp_pago REAL)")
    con.execute("CREATE TABLE da_recurso (recurso_id TEXT PRIMARY KEY, modificado_portal TEXT)")
    for pos, uo, ug, nug, org, norg, poder, mod, *vals in linhas:
        con.execute("INSERT INTO da_despesa VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("r-" + pos, pos, uo, "UO " + uo, ug, nug, org, norg, poder, mod, *vals))
        con.execute("INSERT OR IGNORE INTO da_recurso VALUES (?,?)", ("r-" + pos, "2025-07-14T17:24:45"))
    con.execute("CREATE TABLE cge_execucao_despesa (ug TEXT, unidade_gestora TEXT, ano INTEGER, mes INTEGER, "
                "dotacao_inicial REAL, despesas_empenhadas REAL, despesas_liquidadas REAL, "
                "despesas_orcamentarias_pagas REAL, restos_a_pagar_pagos REAL)")
    con.execute("CREATE TABLE cge_coleta (tabela TEXT PRIMARY KEY, atualizado_fonte TEXT)")
    con.execute("INSERT INTO cge_coleta VALUES ('cge_execucao_despesa', ?)", (cge_atualizado,))
    con.executemany("INSERT INTO cge_execucao_despesa VALUES (?,?,?,?,?,?,?,?,?)", cge)
    con.commit()
    con.close()


def _siafe(caminho, obs):
    """obs: (numero, ug, data DD/MM/AAAA, status, tipo_ob, valor, gd, status_envio, exercicio)"""
    con = sqlite3.connect(caminho)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, data_emissao TEXT, "
                "status TEXT, tipo_ob TEXT, valor REAL, gd TEXT, status_envio TEXT, exercicio INTEGER)")
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?,?,?,?,?,?)", obs)
    con.commit()
    con.close()


_OBS = [
    # UG 500100 — pago que conta: 2 OB orçamentárias contabilizadas (300 + 250 = 550)
    ("2024OB00001", "500100", "10/02/2024", "Contabilizado", "Orçamentária", 300.0, "", "Processado e Pago", 2024),
    ("2024OB00002", "500100", "15/08/2024", "Contabilizado", "Orçamentária", 250.0, "", "Enviado Manualmente", 2024),
    # controles negativos — nenhum destes é pagamento do orçamento de 2024
    ("2024OB00003", "500100", "20/03/2024", "Contabilizado", "Orçamentária", 9000.0, "2024GD00007", "Erro no Pagamento", 2024),
    ("2024OB00004", "500100", "21/03/2024", "Anulado", "Orçamentária", 8000.0, "", "Aguardando Geração RE", 2024),
    ("2024OB00005", "500100", "22/03/2024", "Excluído", "Orçamentária", 7000.0, "", "Enviado Manualmente", 2024),
    ("", "500100", "23/03/2024", "Contabilizado", "Orçamentária", 6000.0, "", "", 2024),                     # sem número
    ("2024OB00006", "500100", "24/03/2024", "Contabilizado", "RPP", 50.0, "", "Processado e Pago", 2024),      # restos
    ("2024OB00007", "500100", "25/03/2024", "Contabilizado", "Orçamentária", 5000.0, "2024GD00009", "Parcialmente Pago", 2024),
    ("2023OB00001", "500100", "10/02/2023", "Contabilizado", "", 4000.0, "", "Processado e Pago", 2023),       # outro ano
    # duas guias de devolução no mesmo campo: a regra da casa (uma guia só) deixava passar como pagamento integral
    ("2024OB00008", "500100", "26/03/2024", "Contabilizado", "Orçamentária", 3000.0, "2024GD00010,2024GD00017", "Parcialmente Pago", 2024),
    # UG 600100 — confere com o balancete (4.000 + 100 de crédito do órgão 50)
    ("2024OB00010", "600100", "05/05/2024", "Contabilizado", "Orçamentária", 4100.0, "", "Processado e Pago", 2024),
    # UG 010100 — soma real das OB orçamentárias de 2024 na base
    ("2024OB00020", "010100", "30/06/2024", "Contabilizado", "Orçamentária", 1079458869.87, "", "Processado e Pago", 2024),
]


@pytest.fixture
def bases(tmp_path):
    ab, db = tmp_path / "abertos.db", tmp_path / "compliance.db"
    cge = [("500100", "500100 - SECRETARIA A", 2024, m, 1000.0 if m == 1 else 0.0, 75.0, 65.0, 58.0, 0.0)
           for m in range(1, 13)]               # 12 × 75 = 900 = empenho da UG 500100 no TFE (800 + crédito 0)
    _abertos(ab, _ALERJ + _SINT, cge)
    _siafe(db, _OBS)
    return {"db": db, "db_abertos": ab}


def _org(d, cod):
    return next(o for o in d["orgaos"] if o["orgao"] == cod)


def _ug(o, ug):
    return next(x for x in o["ugs"] if x["ug"] == ug)


# ── controle positivo: valor real ──────────────────────────────────────────────────────────────────────────────
def test_orgao_real_reproduz_o_arquivo_publicado(bases):
    d = O.calcular(2024, **bases)
    assert d["ok"] and d["exercicio"] == 2024 and d["visao"] == "orcamentaria" and d["execucao_ate"] == 12
    o = _org(d, "01")
    assert o["nome"] == "Assembleia Legislativa" and o["n_ugs"] == 2
    assert o["dotacao_inicial"] == 1633180554.00
    assert o["dotacao_atualizada"] == 1351180554.00
    assert o["empenhado"] == 1312019851.41
    assert o["liquidado"] == 1312007073.41
    assert o["pago_balancete"] == 1299714492.53
    assert o["taxa_empenho"] == 97.1 and o["taxa_pago_balancete"] == 96.2
    # pago por OB: só a UG que tem OB; a outra tem pagamento no balancete e nenhuma OB → soma incompleta, sem taxa
    assert o["pago_siafe"] == 1079458869.87
    assert o["faltam"] == {"pago_siafe": 1} and o["taxa_pago"] is None and o["taxa_pago_empenhado"] is None
    u = _ug(o, "010100")
    assert u["divergencia"] == round(1079458869.87 - 1283172078.64, 2) and u["divergencia_pct"] == -15.9
    assert u["estados"]["pago_siafe"] == "PENDENTE"
    assert not proveniencia_incompleta(d), "o payload tem de trazer proveniência completa (PAD-01/02/06/07)"


# ── controles negativos: o que NÃO é pagamento ─────────────────────────────────────────────────────────────────
def test_ob_devolvida_anulada_sem_numero_e_restos_nao_entram_no_pago(bases):
    d = O.calcular(2024, **bases)
    u = _ug(_org(d, "50"), "500100")
    assert u["pago_siafe"] == 550.00, "só as duas OB orçamentárias contabilizadas, não devolvidas"
    assert u["rp_pago_siafe"] == 50.00, "restos a pagar ficam em coluna própria"
    assert u["ob"]["devolvidas_n"] == 1 and u["ob"]["devolvidas_valor"] == 9000.00          # Erro no Pagamento
    # GD parcial: uma OB com uma guia (5.000) e uma com DUAS guias no campo (3.000) — nenhuma entra no pago
    assert u["ob"]["devolucao_sem_valor_n"] == 2 and u["ob"]["devolucao_sem_valor_bruto"] == 8000.00
    assert d["controles"]["ob_sem_numero_fora"] == {"n": 1, "valor": 6000.00}
    assert any("piso" in n for n in u["notas"])


def test_empenho_e_liquidacao_nunca_viram_pago(bases):
    d = O.calcular(2024, **bases)
    o = _org(d, "70")                       # empenhou e liquidou 900, o balancete diz pago 900, nenhuma OB na base
    assert o["empenhado"] == 900.00 and o["liquidado"] == 900.00 and o["pago_balancete"] == 900.00
    assert o["pago_siafe"] is None, "sem OB não há pago do SIAFE — INDISPONÍVEL, nunca o empenhado nem zero"
    assert o["taxa_pago"] is None and o["estados"]["pago_siafe"] == "INDISPONIVEL"
    assert "não é zero" in _ug(o, "700100")["motivos"]["pago_siafe"]
    assert o["taxa_pago_balancete"] == 100.0, "a taxa do balancete continua existindo, rotulada como referência"


# ── órgão do crédito × UG executora ────────────────────────────────────────────────────────────────────────────
def test_credito_executado_por_ug_de_outro_orgao_fica_no_orgao_do_credito(bases):
    d = O.calcular(2024, **bases)
    o50, o60 = _org(d, "50"), _org(d, "60")
    assert o50["dotacao_atualizada"] == 1500.00 and o50["empenhado"] == 900.00      # 800 próprios + 100 pela UG 600100
    assert o50["taxa_empenho"] == 60.0
    alheia = _ug(o50, "600100")
    assert alheia["credito_de_outro_orgao"] and alheia["pago_siafe"] is None
    assert "órgão 60" in alheia["motivos"]["pago_siafe"]
    # 100 de 900 cruzam de órgão (11,1%): a OB não diz de quem é o crédito → sem taxa de pago por OB no órgão 50
    assert o50["cruzado"] == 100.00 and o50["cruzado_pct"] == 11.1 and o50["taxa_pago"] is None
    assert any("cruza de órgão" in n for n in o50["notas"])
    # no órgão 60 o cruzamento é 100 de 4.000 (2,5%) — também acima da tolerância de 1%
    assert o60["cruzado_pct"] == 2.5 and o60["taxa_pago"] is None
    # a diferença SIAFE × balancete é medida na UG inteira: 4.100 de OB contra 4.100 pagos → confere
    u = _ug(o60, "600100")
    assert u["divergencia"] == 0.00 and u["estados"]["pago_siafe"] == "VERIFICADO"
    assert d["controles"]["empenhado_que_cruza_de_orgao"] == 100.00


def test_reserva_de_contingencia_vira_nota_e_ug_nao_tem_taxa_sobre_dotacao(bases):
    d = O.calcular(2024, **bases)
    o = _org(d, "50")
    assert any("reserva de contingência" in n and "R$ 300,00" in n for n in o["notas"])
    assert all(x["taxa_empenho"] is None for x in o["ugs"]), "a dotação é da unidade orçamentária, não da UG"
    assert o["uos"] == [{"uo": "5001", "nome": "UO 5001", "dotacao_inicial": 1000.0, "dotacao_atualizada": 1500.0,
                         "empenhado": 900.0, "liquidado": 800.0, "pago_balancete": 700.0, "taxa_empenho": 60.0,
                         "taxa_pago_balancete": 46.7}]


# ── estado: VERIFICADO só com duas publicações iguais ──────────────────────────────────────────────────────────
def test_verificado_exige_tfe_e_cge_iguais(tmp_path):
    ab, db = tmp_path / "a.db", tmp_path / "c.db"
    linhas = [("12/2024", "5001", "500100", "SECRETARIA A", "50", "Secretaria A", "1", "90", 1000.0, 1200.0, 900.0, 780.0, 696.0, 0.0),
              ("12/2024", "6001", "600100", "SECRETARIA B", "60", "Secretaria B", "1", "90", 500.0, 500.0, 400.0, 400.0, 400.0, 0.0)]
    cge = [("500100", "500100 - SECRETARIA A", 2024, m, 1000.0 if m == 1 else 0.0, 80.0, 65.0, 58.0, 0.0) for m in range(1, 13)]
    cge += [("600100", "600100 - SECRETARIA B", 2024, 1, 499.0, 400.0, 400.0, 399.0, 0.0)]
    _abertos(ab, linhas, cge)
    _siafe(db, [])
    d = O.calcular(2024, db=db, db_abertos=ab)
    a = _ug(_org(d, "50"), "500100")["estados"]
    assert a["liquidado"] == a["pago_balancete"] == a["dotacao_inicial"] == "VERIFICADO"      # 780 e 696 nas duas
    assert a["empenhado"] == "PENDENTE", "empenhado difere entre as fontes (900 × 960): não é verificado"
    assert a["dotacao_atualizada"] == "PENDENTE", "fonte única"
    b = _ug(_org(d, "60"), "600100")
    assert b["estados"]["pago_balancete"] == "PENDENTE" and "diferem em R$ 1,00" in b["motivos"]["pago_balancete"]
    assert b["estados"]["dotacao_inicial"] == "PENDENTE"
    assert d["proveniencia"]["estado"] == "PENDENTE", "o estado da tela é o pior entre os órgãos"


# ── ano e mês ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_mes_acumula_de_janeiro_ate_o_mes_e_corta_as_ob_no_mesmo_mes(bases):
    d = O.calcular(2024, 3, **bases)
    assert d["periodo"] == "janeiro a março de 2024" and d["visao"] == "unidade_executora"
    assert d["execucao_fonte"] == "CGE" and d["ob_ate_mes"] == 3
    o = _org(d, "50")
    assert o["empenhado"] == 225.00 and o["liquidado"] == 195.00 and o["pago_balancete"] == 174.00   # 3 meses
    u = _ug(o, "500100")
    assert u["pago_siafe"] == 300.00, "só a OB de fevereiro; a de agosto fica fora do recorte"
    # quem não está no painel da CGE não tem execução por mês — INDISPONÍVEL, não zero
    o01 = _org(d, "01")
    assert o01["empenhado"] is None and o01["estados"]["empenhado"] == "INDISPONIVEL"
    assert o01["dotacao_atualizada"] == 1351180554.00
    assert d["meses_com_execucao"] == list(range(1, 13))


def test_mes_da_atualizacao_da_cge_fica_fora_por_estar_incompleto(tmp_path):
    ab, db = tmp_path / "a.db", tmp_path / "c.db"
    cge = [("500100", "500100 - SECRETARIA A", 2026, m, 1000.0 if m == 1 else 0.0, 100.0, 90.0, 80.0, 5.0) for m in range(1, 8)]
    _abertos(ab, _SINT, cge)                    # TFE só tem 2024; a CGE foi atualizada em 15/07/2026
    _siafe(db, [("2026OB1", "500100", "10/03/2026", "Contabilizado", "Orçamentária", 200.0, "", "Processado e Pago", 2026),
                ("2026OB2", "500100", "10/09/2026", "Contabilizado", "Orçamentária", 999.0, "", "Processado e Pago", 2026)])
    d = O.calcular(2026, db=db, db_abertos=ab)
    assert d["execucao_ate"] == 6 and d["meses_com_execucao"] == [1, 2, 3, 4, 5, 6]
    o = _org(d, "50")
    assert o["empenhado"] == 600.00, "julho (pela metade) não entra"
    assert o["pago_siafe"] == 200.00, "OB de setembro fica fora: as OB param no mês da execução publicada"
    # sem TFE do exercício não existe dotação atualizada — INDISPONÍVEL, nunca a inicial no lugar
    assert o["dotacao_inicial"] == 1000.00 and o["dotacao_atualizada"] is None
    assert o["estados"]["dotacao_atualizada"] == "INDISPONIVEL" and o["taxa_empenho"] is None
    assert "repete a dotação inicial" in _ug(o, "500100")["motivos"]["dotacao_atualizada"]
    assert list(d["rankings"]) == ["taxa_empenho_inicial"]
    # o órgão 50 tem 11,1% de crédito cruzado na posição de referência (12/2024): sem taxa na visão por UG
    assert d["cruzado_posicao_ref"] == "12/2024" and o["taxa_empenho_inicial"] is None
    # mês além do que a fonte publicou: só dotação e OB
    d9 = O.calcular(2026, 9, db=db, db_abertos=ab)
    assert d9["visao"] == "so_ob" and _org(d9, "50")["empenhado"] is None
    assert _org(d9, "50")["pago_siafe"] == 1199.00


def test_posicao_parcial_do_tfe_nao_e_comparada_com_ob(tmp_path):
    ab, db = tmp_path / "a.db", tmp_path / "c.db"
    _abertos(ab, [("07/2025", "5001", "500100", "SECRETARIA A", "50", "Secretaria A", "1", "90", 1000.0, 1200.0, 500.0, 400.0, 300.0, 0.0)])
    _siafe(db, [("2025OB1", "500100", "30/07/2025", "Contabilizado", "Orçamentária", 350.0, "", "Processado e Pago", 2025)])
    d = O.calcular(2025, db=db, db_abertos=ab)
    assert d["execucao_parcial"] and "publicado em 14/07/2025" in d["periodo"]
    o = _org(d, "50")
    assert o["taxa_empenho"] == 41.7 and o["pago_siafe"] == 350.00
    assert o["divergencia"] is None and o["taxa_pago"] is None and o["taxa_pago_empenhado"] is None
    assert "posição parcial" in _ug(o, "500100")["motivos"]["pago_siafe"]


def test_dotacao_publicada_antes_do_fim_da_execucao_nao_e_denominador(tmp_path):
    ab, db = tmp_path / "a.db", tmp_path / "c.db"
    cge = [("500100", "500100 - SECRETARIA A", 2025, m, 1000.0 if m == 1 else 0.0, 150.0, 150.0, 150.0, 0.0) for m in range(1, 13)]
    _abertos(ab, [("07/2025", "5001", "500100", "SECRETARIA A", "50", "Secretaria A", "1", "90", 1000.0, 1200.0, 500.0, 400.0, 300.0, 0.0)], cge)
    _siafe(db, [])
    d = O.calcular(2025, 12, db=db, db_abertos=ab)
    o = _org(d, "50")
    assert d["dotacao_defasada"] and o["empenhado"] == 1800.00 and o["dotacao_atualizada"] == 1200.00
    assert o["taxa_empenho"] is None, "1.800 ÷ 1.200 daria 150% — a dotação é de julho, a execução vai a dezembro"
    assert O.calcular(2025, 5, db=db, db_abertos=ab)["orgaos"][0]["taxa_empenho"] == 62.5      # 750 ÷ 1.200


def test_antes_de_2024_a_ob_nao_tem_tipo_e_o_pago_do_exercicio_fica_indisponivel(tmp_path):
    ab, db = tmp_path / "a.db", tmp_path / "c.db"
    _abertos(ab, [("12/2023", "5001", "500100", "SECRETARIA A", "50", "Secretaria A", "1", "90", 1000.0, 1200.0, 900.0, 800.0, 700.0, 100.0)])
    _siafe(db, [("2023OB1", "500100", "10/02/2023", "Contabilizado", "", 780.0, "", "Processado e Pago", 2023)])
    d = O.calcular(2023, db=db, db_abertos=ab)
    u = _ug(_org(d, "50"), "500100")
    assert u["pago_siafe"] is None and u["ob_total"] == 780.00 and u["ob_sem_tipo"]
    assert u["divergencia_base"] == "total_com_restos" and u["divergencia"] == -20.00       # 780 − (700 + 100)
    assert u["estados"]["pago_siafe"] == "INDISPONIVEL"


# ── ranking e exercícios ───────────────────────────────────────────────────────────────────────────────────────
def test_ranking_declara_quantos_entram_e_respeita_o_piso(bases):
    d = O.calcular(2024, **bases)
    r = d["rankings"]["taxa_empenho"]
    assert r["total_orgaos"] == 4 and r["elegiveis"] == 1, "só a ALERJ tem dotação a partir de R$ 1 milhão"
    assert r["mais"][0] == {"orgao": "01", "nome": "Assembleia Legislativa", "taxa": 97.1,
                            "notas": _org(d, "01")["notas"][:2]}
    assert d["rankings"]["taxa_pago"]["elegiveis"] == 0


def test_exercicios_e_padrao(bases):
    exs = O.exercicios(**bases)
    assert [e["ano"] for e in exs] == [2024]
    assert exs[0]["tfe_posicao"] == "12/2024" and exs[0]["cge_mes"] == 12 and exs[0]["ob_ugs"] == 3
    assert O.exercicio_padrao(exs) == 2024
    assert O.exercicio_padrao([{"ano": 2026, "tfe_mes": None}, {"ano": 2025, "tfe_mes": 7},
                               {"ano": 2024, "tfe_mes": 12}]) == 2024, "o padrão é o último exercício fechado"
    assert O.calcular(1999, **bases)["ok"] is False


def test_base_ausente_nao_inventa_numero(tmp_path):
    d = O.calcular(2024, db=tmp_path / "nao_existe.db", db_abertos=tmp_path / "tambem_nao.db")
    assert d["ok"] is False and "não está na base" in d["erro"]


def test_total_do_estado_soma_as_linhas_e_declara_o_que_falta(bases):
    d = O.calcular(2024, **bases)
    t = d["total"]
    assert t["empenhado"] == round(1312019851.41 + 900 + 4000 + 900, 2)
    assert t["dotacao_atualizada"] == round(1351180554.00 + 1500 + 5000 + 900, 2)
    assert t["pago_siafe"] == round(1079458869.87 + 550 + 4100, 2)
    assert t["faltam"] == {"pago_siafe": 2} and t["taxa_pago"] is None        # UG 016100 e 700100 sem OB
    assert t["divergencia_n"] == 3 and t["n_orgaos"] == 4 and t["n_ugs"] == 5


# ── rota ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_rota_devolve_o_payload_e_404_para_exercicio_fora_da_base(bases, monkeypatch):
    import json

    from rotas import investigacao, orcamento_orgao as R
    monkeypatch.setattr(O, "DB", bases["db"])
    monkeypatch.setattr(O, "DB_ABERTOS", bases["db_abertos"])
    monkeypatch.setattr(investigacao, "_cache_calc", lambda chave, ttl, calcular: calcular())
    d = json.loads(R.api_orcamento_orgao().body)
    assert d["ok"] and d["exercicio"] == 2024 and d["mes"] is None and len(d["orgaos"]) == 4
    assert json.loads(R.api_orcamento_orgao(ano=2024, mes=3).body)["mes"] == 3
    r = R.api_orcamento_orgao(ano=1999)
    assert r.status_code == 404 and json.loads(r.body)["ok"] is False
