# -*- coding: utf-8 -*-
"""Agrupamento de OBJETO para fracionamento (art. 75 §1º) — refino pedido pelo dono 2026-07-24.

O P4 agrupava por similaridade de SEQUÊNCIA (difflib) sobre a descrição. Isso erra dos dois lados:
  • falso NEGATIVO: "aquisição de material de limpeza" × "compra de produtos de limpeza" — mesmo objeto,
    palavras diferentes → não agrupava, e o fracionamento passava batido;
  • falso POSITIVO: "material de limpeza" × "material de escritório" — textos parecidíssimos, objetos
    distintos → quase agrupava.
A correção é pesar cada palavra pelo que ela DISCRIMINA no lote (TF-IDF): num lote de compras, "material"
e "aquisição" aparecem em quase tudo e não distinguem nada; "limpeza" distingue.
"""
from __future__ import annotations

from compliance_agent import objeto_similaridade as OS

_LOTE = [
    {"objeto": "Aquisição de material de limpeza para o almoxarifado"},
    {"objeto": "Compra de produtos de limpeza e higienização"},
    {"objeto": "Aquisição de material de escritório"},
    {"objeto": "Contratação de serviços de manutenção predial"},
    {"objeto": "Aquisição de copos descartáveis 200ml"},
    {"objeto": "Aquisição de copo descartável 200 ml"},
]


def _grupo_de(clusters, i):
    return next(c for c in clusters if i in c)


def test_mesmo_objeto_com_palavras_diferentes_agrupa():
    cl = OS.agrupar(_LOTE)
    assert 1 in _grupo_de(cl, 0)          # material de limpeza × produtos de limpeza


def test_material_de_limpeza_nao_agrupa_com_material_de_escritorio():
    cl = OS.agrupar(_LOTE)
    assert 2 not in _grupo_de(cl, 0)      # o que os une ("material", "aquisição") não discrimina nada


def test_plural_e_flexao_agrupam():
    cl = OS.agrupar(_LOTE)
    assert 5 in _grupo_de(cl, 4)          # copos descartáveis × copo descartável


def test_servico_distinto_fica_sozinho():
    cl = OS.agrupar(_LOTE)
    assert _grupo_de(cl, 3) == [3]


def test_chave_dura_vence_o_texto():
    # CATMAT/natureza de despesa é classificação OFICIAL: agrupa mesmo com descrições diferentes
    lote = [{"objeto": "Aquisição de tinta acrílica branca", "catmat": "123456"},
            {"objeto": "Compra de material para pintura interna", "catmat": "123456"},
            {"objeto": "Aquisição de tinta acrílica azul", "catmat": "999999"}]
    cl = OS.agrupar(lote)
    assert 1 in _grupo_de(cl, 0)
    assert 2 not in _grupo_de(cl, 0)


def test_natureza_de_despesa_do_siafe_e_chave_dura():
    lote = [{"objeto": "Aquisição de gêneros alimentícios", "natureza_despesa": "33903007"},
            {"objeto": "Compra de alimentos para a merenda", "natureza_despesa": "33903007"}]
    assert _grupo_de(OS.agrupar(lote), 0) == [0, 1]


def test_objeto_generico_nao_arrasta_tudo():
    # "material diverso"/"serviços gerais" não descrevem objeto: não podem formar cluster por si
    lote = [{"objeto": "Material diverso"}, {"objeto": "Materiais diversos"},
            {"objeto": "Serviços gerais"}, {"objeto": "Aquisição de pneus para a frota"}]
    cl = OS.agrupar(lote)
    assert OS.generico("Material diverso") is True
    assert OS.generico("Aquisição de pneus para a frota") is False
    assert _grupo_de(cl, 3) == [3]
    # os genéricos ficam isolados (não se soma o que não se sabe o que é)
    assert all(len(g) == 1 for g in cl if 3 not in g)


def test_descricao_puramente_administrativa_e_generica_dado_real():
    # textos REAIS de compras_diretas_tcerj: não dizem O QUE foi comprado — não podem somar entre si
    reais = ["GERAMOS O PROCESSO ADMINISTRATIVO PARA O EMPENHO E PAGAMENTO DAS DESPESAS RELATIVAS AO "
             "EXERCÍCIO DE 2023",
             "GERAMOS O PROCESSO ADMINISTRATIVO PARA OEMPENHO E PAGAMENTO DAS DESPESAS RELATIVAS AO "
             "EXERCÍCIO DE 2024",
             "ABERTURA DE PROCESSO ADMINISTRATIVO PARA O EXERCÍCIO DE 2023"]
    for t in reais:
        assert OS.generico(t) is True, t
    cl = OS.agrupar([{"objeto": t} for t in reais])
    assert cl == [[0], [1], [2]]                  # cada um isolado: não se soma o que não se sabe o que é


def test_objeto_real_com_conteudo_nao_e_generico():
    assert OS.generico("REFERENTE AO PAGAMENTO DO CONDOMÍNIO DE EDIFÍCIO MANOEL JOÃO GONÇALVES") is False
    assert OS.generico("CONTRATAÇÃO PARA O FORNECIMENTO DE ENERGIA ELÉTRICA") is False


def test_ano_solto_nao_identifica_objeto():
    assert "2023" not in OS.tokens("Despesas do exercício de 2023")


def test_motivo_do_agrupamento_e_explicito():
    inf = OS.explicar(_LOTE, 0, 1)
    assert inf["criterio"] == "similaridade_tfidf"
    assert inf["score"] >= OS.LIMIAR
    assert "limpeza" in inf["termos_em_comum"]        # o auditor vê POR QUE agrupou


def test_determinismo():
    assert OS.agrupar(_LOTE) == OS.agrupar(_LOTE)


def test_lote_vazio_ou_unitario():
    assert OS.agrupar([]) == []
    assert OS.agrupar([{"objeto": "x"}]) == [[0]]


def test_p4_continua_verde_com_o_novo_agrupamento():
    # o refino entra POR DENTRO do P4: a doutrina (limites, âncoras) não muda
    from compliance_agent.detectores.p4_fracionamento import clusterizar
    cl = clusterizar([{"objeto": o["objeto"]} for o in _LOTE])
    assert sorted(sorted(g) for g in cl) == sorted(sorted(g) for g in OS.agrupar(_LOTE))
