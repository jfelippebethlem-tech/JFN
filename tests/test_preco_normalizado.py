# -*- coding: utf-8 -*-
"""Preço unitário normalizado e grupos homogêneos — sintéticos (repositório público).

Pedido do dono (2026-11-13): "galão de água é diferente de copinho de água [...] isolar os
preços pela mesma unidade de medida". Diretriz: "não pode ter margem pra erro em nada".
"""
from __future__ import annotations

import pytest

from compliance_agent.preco_normalizado import (INDETERMINADO, agrupar, faixas_por_salto,
                                                normalizar)


def _chave(desc, un):
    n = normalizar(desc, un)
    assert n["ok"], n["motivo"]
    return n["chave"]


# ── galão × copo nunca se comparam ─────────────────────────────────────────────

def test_galao_e_copo_tem_chaves_diferentes():
    assert _chave("Água mineral natural", "Galão 20,00 L") != _chave("Água mineral natural",
                                                                     "Copo 200,00 ML")


def test_garrafao_e_galao_de_20l_sao_o_mesmo_recipiente():
    assert _chave("Água mineral", "Garrafão 20,00 L") == _chave("Água mineral", "Galão 20 L")


def test_garrafa_500_e_garrafa_1500_nao_se_comparam():
    assert _chave("Água", "Garrafa 500,00 ML") != _chave("Água", "Garrafa 1,50 L")


# ── embalagem com contagem declarada vira unidades ─────────────────────────────

def test_caixa_com_12_unidades_na_descricao_vira_12_unidades():
    n = normalizar("Luva descartável cx c/ 12 un", "Caixa")
    assert n["ok"] and n["fator"] == 12
    assert "cx c/ 12 un" in n["trecho"]           # trecho LITERAL que justificou


def test_caixa_100_un_no_campo_vira_unidade_e_casa_com_unidade_avulsa():
    cx = normalizar("Envelope", "Caixa 100,00 UN")
    un = normalizar("Envelope", "Unidade")
    assert cx["fator"] == 100 and un["fator"] == 1
    assert cx["chave"] == un["chave"]             # preço/100 compara com a unidade avulsa


def test_centena_e_milheiro_viram_unidades():
    assert normalizar("Envelope", "Centena")["fator"] == 100
    assert normalizar("Envelope", "Milheiro")["fator"] == 1000


def test_caixa_com_48_copos_de_200ml_casa_com_copo_200ml():
    cx = normalizar("Água mineral caixa com 48 copos de 200ml", "Caixa")
    copo = normalizar("Água mineral", "Copo 200,00 ML")
    assert cx["fator"] == 48 and cx["chave"] == copo["chave"]


def test_fardo_6x1_5l():
    n = normalizar("Água mineral fardo 6x1,5L", "Fardo")
    assert n["ok"] and n["fator"] == 6 and "1500" in n["chave"]


# ── medida pura: litro × mililitro × kg × g ──────────────────────────────────

def test_litro_e_mililitro_convertem_para_litro():
    assert normalizar("Desinfetante", "Litro")["fator"] == 1
    assert normalizar("Desinfetante", "Mililitro")["fator"] == pytest.approx(0.001)
    assert _chave("Desinfetante", "Litro") == _chave("Desinfetante", "Mililitro")


def test_kg_e_grama():
    assert normalizar("Açúcar", "Quilograma")["fator"] == 1
    assert normalizar("Açúcar", "Grama")["fator"] == pytest.approx(0.001)


def test_m2_nao_e_metro():
    assert _chave("Piso", "Metro quadrado") != _chave("Piso", "Metro")


# ── item sem unidade confiável sai da conta ─────────────────────────────────

@pytest.mark.parametrize("desc,un", [
    ("Água mineral", ""),                          # sem unidade
    ("Água mineral", None),
    ("Kit limpeza", "Kit"),                        # genérica
    ("Material elétrico", "Conjunto"),
    ("Brinquedo", "Lote"),
    ("Envelope", "Caixa"),                         # embalagem sem contagem
    ("Fralda", "Pacote"),
    ("Desinfetante 5 litros", "Litro"),            # conflito campo × descrição
    ("Água mineral caixa com 48 copos", "Unidade"),  # preço da unidade ou da caixa?
    ("Água 1,5L", "Garrafa 500 ML"),               # conteúdo contraditório
    ("Treinamento qualificação profissional", "Unidade"),  # serviço por 'unidade'
    ("Contratação de locação de imóvel", "Mês"),   # não fungível
    ("Coisa", "Xpto"),                             # unidade desconhecida
    ("Peça mecânica/elétrica - veículo", "Unidade"),  # nome de CLASSE do catálogo
])
def test_unidade_ambigua_e_indeterminado(desc, un):
    n = normalizar(desc, un)
    assert not n["ok"] and n["estado"] == INDETERMINADO and n["motivo"]


def test_servico_mensal_e_comparavel_so_com_mensal():
    assert normalizar("Hospedagem de correio eletrônico", "Mensal")["ok"]
    assert _chave("Hospedagem de e-mail", "Mensal") != _chave("Hospedagem de e-mail", "Hora")


def test_medidas_da_descricao_separam_tamanhos():
    """Dose/tamanho citados na descrição entram na chave: 500 mg ≠ 250 mg."""
    assert _chave("Amoxicilina 500 mg", "Comprimido") != _chave("Amoxicilina 250 mg",
                                                                "Comprimido")


# ── agrupamento homogêneo ──────────────────────────────────────────────────

def _regs(desc, un, precos):
    return [{"d": desc, "un": un, "vu": p, "quantidade": 10, "certame": f"c{i}"}
            for i, p in enumerate(precos)]


def _ck(d):
    return d.lower()


def test_faixas_por_salto():
    assert faixas_por_salto([1, 1.2, 1.5, 9, 10]) == [(0, 3), (3, 5)]
    assert faixas_por_salto([1, 2, 3]) == [(0, 3)]


def test_galao_e_copo_nunca_caem_no_mesmo_grupo():
    regs = _regs("Água mineral", "Galão 20 L", [8, 9, 10, 11, 12]) + \
        _regs("Água mineral", "Copo 200 ML", [0.5, 0.55, 0.6, 0.62, 0.7])
    g = agrupar(regs, _ck, min_amostra=5, min_certames=4)
    assert len(g["grupos"]) == 2
    for grp in g["grupos"]:
        assert len({r["un"] for r in grp["itens"]}) == 1


def test_grupo_heterogeneo_sem_salto_vai_para_indeterminado():
    """'Desinfetante / Litro' de R$1 a R$300 sem salto ≥4×: rótulo mistura produtos."""
    regs = _regs("Desinfetante", "Litro", [1, 2, 3, 6, 12, 24, 50, 100, 200, 300])
    g = agrupar(regs, _ck, min_amostra=5, min_certames=4)
    assert g["grupos"] == []
    assert len(g["indeterminados"]) == 10
    assert all("heterog" in m for _, m in g["indeterminados"])


def test_salto_separa_faixa_isolada_que_nao_vira_sobrepreco():
    """Ampola a R$140 contra ampolas a R$0,2: salto de 700× — unidade diferente, não preço."""
    regs = _regs("Água destilada", "Ampola 10 ML", [0.15, 0.18, 0.2, 0.21, 0.25, 0.3, 140])
    g = agrupar(regs, _ck, min_amostra=5, min_certames=4)
    assert len(g["grupos"]) == 1 and g["grupos"][0]["max"] == 0.3
    (r, motivo), = g["indeterminados"]
    assert r["vu"] == 140 and "salto" in motivo


def test_grupo_heterogeneo_com_salto_e_separado_em_dois():
    regs = _regs("Lâmpada led", "Unidade", [10, 11, 12, 13, 14]) + \
        [dict(x, certame="d" + x["certame"]) for x in
         _regs("Lâmpada led", "Unidade", [100, 105, 110, 120, 130])]
    g = agrupar(regs, _ck, min_amostra=5, min_certames=4)
    assert sorted(gr["faixa"] for gr in g["grupos"]) == [1, 2]
    assert all(gr["dispersao"] < 2 for gr in g["grupos"])


def test_preco_normalizado_divide_pelo_fator():
    regs = [{"d": "Envelope", "un": "Caixa 100 UN", "vu": 50.0, "quantidade": 2, "certame": "x"}]
    agrupar(regs, _ck, min_amostra=1, min_certames=1)
    assert regs[0]["pn"] == pytest.approx(0.5) and regs[0]["qn"] == 200
