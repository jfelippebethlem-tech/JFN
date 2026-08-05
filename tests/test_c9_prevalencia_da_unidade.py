# -*- coding: utf-8 -*-
"""O C9 apontava para o fornecedor quando o padrão era da UNIDADE.

O detector dispara com limiar ABSOLUTO: 30% do valor recebido via TAC/indenização. Mas numa
unidade que paga **27,0% de tudo** por essa via, um fornecedor com 29,8% é a NORMA, não a exceção.

Medido em 2026-08-04 no acervo: **24 dos 41 disparos** eram de fornecedores a menos de 2× a taxa
da própria unidade, e **nove marcavam exatamente 29,8% na Fundação Saúde (27,0%)** — 1,1×,
indistinguível do comportamento local.

O achado NÃO some: a docstring do próprio C9 sempre disse que o vício é do ÓRGÃO, com o
fornecedor como beneficiário. Ele passa a dizer isso, e cai de grau para não dominar a fila do
fiscal com empresas que só parecem ruins porque a unidade inteira é.

É a doutrina que a casa já aplicava noutro lugar: **prevalência decide o eixo**.
"""
from compliance_agent.detectores.c9_tac_fornecedor import C9TacFornecedor

_TAC = {"n": 100, "n_tac": 30, "total": 1e9, "total_tac": 2.98e8, "pct": 29.8,
        "cobertura": "verificado (100 OBs)"}
_UNIDADE = {"ug": "294200", "ug_nome": "FUNDACAO SAUDE DO ESTADO DO RIO DE JANEIRO", "pct": 27.0}


def _avaliar(**ctx):
    return C9TacFornecedor().avaliar({"processo": "SEI-080002/000001/2024", **ctx})


def test_fornecedor_na_NORMA_da_unidade_cai_de_grau_e_aponta_o_orgao():
    r = _avaliar(tac=_TAC, tac_unidade=_UNIDADE)
    assert r.status == "confirmado", "o achado não some — o dinheiro fora de contrato existe"
    assert r.score < 0.6
    assert r.valores["padrao_e_do_orgao"] is True
    assert r.valores["razao_sobre_a_unidade"] == 1.1
    trecho = r.evidencia[0]["trecho"]
    assert "ÓRGÃO" in trecho and "27.0%" in trecho


def test_sem_base_da_unidade_o_comportamento_antigo_permanece():
    """Ausência de base não pode virar absolvição: sem saber a norma local, vale o limiar."""
    r = _avaliar(tac=_TAC)
    assert r.status == "confirmado" and r.score == 0.6
    assert "padrao_e_do_orgao" not in r.valores


def test_fornecedor_MUITO_acima_da_unidade_mantem_o_grau():
    """82% numa unidade de 27% é 3× a norma — aí a empresa é o eixo, e o achado fica forte."""
    tac = {**_TAC, "pct": 82.0, "total_tac": 8.2e8}
    r = _avaliar(tac=tac, tac_unidade=_UNIDADE)
    assert r.score >= 0.9
    assert not r.valores.get("padrao_e_do_orgao")


def test_unidade_com_taxa_zero_nao_divide_por_zero():
    r = _avaliar(tac=_TAC, tac_unidade={"ug": "999999", "pct": 0.0})
    assert r.status == "confirmado" and r.score == 0.6


def test_abaixo_do_limiar_continua_descartado():
    tac = {**_TAC, "pct": 5.0, "total_tac": 5e7}
    r = _avaliar(tac=tac, tac_unidade=_UNIDADE)
    assert r.status == "descartado"
