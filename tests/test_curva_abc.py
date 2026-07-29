# -*- coding: utf-8 -*-
"""Curva ABC — e as três maneiras de a priorização enganar.

  1. **Item sem preço somado como zero.** Encolhe o denominador e infla o peso relativo de todos
     os outros. Ele fica FORA do cálculo e é contado à parte.
  2. **Planilha achatada tratada como concentrada.** Se mil itens têm valor parecido, a faixa A
     seria a planilha inteira — e "auditei a faixa A" deixaria de significar cobertura.
  3. **Ordenar por desvio em vez de por dano.** 300% num item de R$ 40 é R$ 120; 3% num item de
     R$ 4 milhões é R$ 120 mil. É a segunda linha que vai ao relatório primeiro.
"""
from __future__ import annotations

import pytest

from compliance_agent.analysis import curva_abc as C


def _it(nome, preco=None, qtd=None, total=None):
    d = {"item": nome}
    if preco is not None:
        d["preco_unitario"] = preco
    if qtd is not None:
        d["quantidade"] = qtd
    if total is not None:
        d["valor_total"] = total
    return d


# ─────────────────── a classificação ──────────────────────────────────────────────────────────

def test_poucos_itens_concentram_o_valor_e_ficam_na_faixa_A():
    itens = [_it("caro", total=800.0)] + [_it(f"barato{i}", total=10.0) for i in range(20)]
    c = C.montar(itens)
    assert c["faixa_a"][0]["item"] == "caro"
    assert c["concentracao"] == "alta" and c["curva_util_para_priorizar"] is True


def test_item_unico_de_quase_tudo_nao_deixa_a_faixa_A_vazia():
    """O primeiro item já cruza o corte; se ele caísse em B, a faixa A ficaria vazia."""
    c = C.montar([_it("mega", total=900.0), _it("resto", total=100.0)])
    assert c["n_faixa_a"] >= 1 and c["itens"][0]["faixa"] == "A"


def test_valor_vem_de_preco_x_quantidade_quando_nao_ha_total():
    c = C.montar([_it("a", preco=10.0, qtd=5), _it("b", total=10.0)])
    assert c["total"] == 60.0


def test_faixas_seguem_o_acumulado_80_95():
    itens = [_it(f"i{i}", total=v) for i, v in enumerate([80, 15, 5])]
    c = C.montar(itens)
    assert [x["faixa"] for x in c["itens"]] == ["A", "B", "C"]


# ─────────────────── trava 1: item sem valor ──────────────────────────────────────────────────

def test_item_sem_preco_NAO_e_somado_como_zero():
    c = C.montar([_it("com", total=100.0), _it("sem")])
    assert c["sem_valor"] == 1 and c["n_com_valor"] == 1
    assert c["total"] == 100.0
    assert "não foram somados como zero" in c["nota_sem_valor"]


def test_item_com_preco_mas_sem_quantidade_fica_de_fora():
    c = C.montar([_it("a", total=100.0), _it("b", preco=50.0)])
    assert c["sem_valor"] == 1


def test_valor_ilegivel_nao_quebra():
    c = C.montar([_it("a", total="R$ 100,00"), _it("b", total=100.0)])
    assert c["estado"] == "calculada" and c["sem_valor"] == 1


def test_planilha_sem_nenhum_valor_e_estado_declarado():
    c = C.montar([_it("a"), _it("b")])
    assert c["estado"] == "sem_valor_calculavel" and c["concentracao"] is None


# ─────────────────── trava 2: planilha achatada ───────────────────────────────────────────────

def test_planilha_achatada_declara_que_a_curva_NAO_prioriza():
    itens = [_it(f"i{i}", total=100.0) for i in range(50)]
    c = C.montar(itens)
    assert c["concentracao"] == "baixa" and c["curva_util_para_priorizar"] is False
    assert "NÃO é cobertura" in c["ressalva"]


def test_concentracao_media_ainda_serve():
    itens = [_it(f"alto{i}", total=100.0) for i in range(5)]
    itens += [_it(f"baixo{i}", total=10.0) for i in range(15)]
    c = C.montar(itens)
    assert c["concentracao"] in ("alta", "media") and c["curva_util_para_priorizar"] is True


# ─────────────────── trava 3: dano, não desvio ────────────────────────────────────────────────

def test_ordena_por_DANO_e_nao_por_desvio():
    c = C.montar([_it("caro", total=4_000_000.0), _it("barato", total=40.0)])
    d = C.dano_potencial(c, {"caro": 0.03, "barato": 3.0})
    assert d["linhas"][0]["item"] == "caro"
    assert d["linhas"][0]["dano_potencial"] == pytest.approx(120_000.0)
    assert d["linhas"][1]["dano_potencial"] == pytest.approx(120.0)


def test_item_sem_desvio_e_contado_e_nao_somado_como_zero():
    c = C.montar([_it("a", total=100.0), _it("b", total=100.0)])
    d = C.dano_potencial(c, {"a": 0.5})
    assert d["itens_sem_desvio"] == 1 and len(d["linhas"]) == 1


def test_fracao_do_dano_concentrada_na_faixa_A_sai_medida():
    c = C.montar([_it("caro", total=900.0), _it("barato", total=100.0)])
    d = C.dano_potencial(c, {"caro": 0.1, "barato": 0.1})
    assert d["fracao_do_dano_na_faixa_a"] == pytest.approx(0.9, abs=0.01)


def test_dano_POTENCIAL_declara_que_nao_e_dano():
    d = C.dano_potencial(C.montar([_it("a", total=100.0)]), {"a": 0.2})
    assert "não dano" in d["ressalva"] and "empenho não é pagamento" in d["ressalva"]


# ─────────────────── bordas ───────────────────────────────────────────────────────────────────

def test_lista_vazia_nao_quebra():
    assert C.montar([])["estado"] == "sem_valor_calculavel"


def test_cortes_sao_parametrizaveis_e_declarados():
    c = C.montar([_it(f"i{i}", total=v) for i, v in enumerate([50, 30, 20])], corte_a=0.5)
    assert c["cortes"]["a"] == 0.5
    assert c["itens"][0]["faixa"] == "A" and c["itens"][1]["faixa"] == "B"


def test_valor_negativo_ou_zero_nao_entra():
    c = C.montar([_it("a", total=100.0), _it("b", total=0.0), _it("c", total=-50.0)])
    assert c["n_com_valor"] == 1 and c["sem_valor"] == 2
