# -*- coding: utf-8 -*-
"""C5 — pensamentos determinísticos do contrato."""
from compliance_agent.contratos import thoughts as T


def test_t_aditivo_valor_dispara():
    d = {"contrato": {"valor_inicial": 100000, "objeto": "serviço de limpeza"},
         "aditivos": [{"valor_acrescido": 40000, "objeto": "acréscimo de 40%", "qualif_vigencia": None}]}
    a = T.t_aditivo(d)
    assert a and a[0]["risco"] >= 6 and "125" in a[0]["norma"]


def test_t_aditivo_so_prazo_nao_dispara():
    d = {"contrato": {"valor_inicial": 100000, "objeto": "x"},
         "aditivos": [{"valor_acrescido": 0, "objeto": "prorrogação de prazo", "qualif_vigencia": "Sim"}]}
    assert T.t_aditivo(d) == []


def test_t_execucao_nao_avaliavel():
    # pcrj_despesa não liga pagamento a contrato → não emite achado (ausente ≠ 0)
    d = {"contrato": {"valor_global": 100000},
         "pagamentos": {"pago": 150000, "empenhado": 150000, "liquidado": 150000}}
    assert T.t_execucao_financeira(d) == []


def test_t_sobrepreco_peer():
    d = {"itens": [{"descricao": "caneta azul", "unidade": "un", "valor_unitario": 30.0}], "contrato": {}}
    a = T.t_sobrepreco(d, ref_fn=lambda desc: {"disponivel": True, "mediana": 10.0, "n": 5})
    assert a and a[0]["risco"] >= 6
    assert a[0]["proveniencia"]["ratio"] >= 3.0


def test_t_sobrepreco_ratio_absurdo_descartado():
    # 800× = CATMAT errado, não sobrepreço → não marca
    d = {"itens": [{"descricao": "endonuclease", "valor_unitario": 1600.0}], "contrato": {}}
    assert T.t_sobrepreco(d, ref_fn=lambda desc: {"disponivel": True, "mediana": 1.94, "n": 50}) == []


def test_t_sobrepreco_base_insuficiente():
    d = {"itens": [{"descricao": "x", "valor_unitario": 30.0}], "contrato": {}}
    assert T.t_sobrepreco(d, ref_fn=lambda desc: {"disponivel": True, "mediana": 10.0, "n": 1}) == []


def test_t_sobrepreco_sem_ref_nao_marca():
    d = {"itens": [{"descricao": "x", "valor_unitario": 30.0}], "contrato": {}}
    assert T.t_sobrepreco(d, ref_fn=lambda desc: {"disponivel": False}) == []


def test_t_sinais_cruzados():
    d = {"sinais_fornecedor": ["fornecedor sancionado (CEIS)"]}
    a = T.t_sinais_cruzados(d)
    assert a and a[0]["dimensao"] == "beneficiario"


def test_rodar_thoughts_ordena(monkeypatch):
    d = {"contrato": {"valor_inicial": 100000, "valor_global": 100000, "objeto": "x"},
         "aditivos": [{"valor_acrescido": 40000, "objeto": "", "qualif_vigencia": None}],
         "pagamentos": {}, "itens": [], "sinais_fornecedor": []}
    achados = T.rodar_thoughts(d, ref_fn=lambda desc: {"disponivel": False})
    assert achados and achados[0]["risco"] >= achados[-1]["risco"]
