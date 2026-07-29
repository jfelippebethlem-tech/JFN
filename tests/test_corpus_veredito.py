# -*- coding: utf-8 -*-
"""Conjunto-ouro de vereditos jurídicos — a base que faltava para MEDIR a hermenêutica.

`tests/golden/` guarda snapshots de FORMATO de relatório. `eval_groundtruth.py` mede o motor
determinístico contra punições do TCE-RJ. O veredito da camada LLM — grau verde/amarelo/vermelho
de direcionamento, classe trivial/substancial, cumprimento de parecer — nunca teve precisão nem
recall medidos. Sem isso, toda melhoria de prompt é fé, e `LEARNING.md` proíbe promover o que não
sobreviveu out-of-sample.

O rótulo não é opinião: vem do ENUNCIADO do próprio TCU, publicado na Jurisprudência Selecionada
e já indexado em `data/tcu_juris.db` (17.510 acórdãos). Um enunciado que começa por "É irregular a
exigência de..." está dizendo que a conduta é vício; um que diz "Não é obrigatório..." está
dizendo que a conduta é lícita. É rótulo juridicamente defensável e de custo zero.

Todos os enunciados abaixo são VERBATIM do acervo — nenhum foi escrito para o teste.
"""
from __future__ import annotations

import pytest

from compliance_agent.knowledge.corpus_veredito import (
    POLARIDADES,
    ROTULOS,
    classificar_enunciado,
    mapear_vicio,
    montar_caso,
)

# ─────────────────────── enunciados VERBATIM de data/tcu_juris.db ─────────────────────────────

_VEDA = [
    "É ilegal a exigência de que somente poderão participar da licitação as empresas "
    "devidamente cadastradas e habilitadas no SICAF.",
    "É irregular o critério de avaliação de proposta técnica que conceda pontuação a empresas "
    "pelo fato de terem sido anteriormente contratadas pela entidade ou por outras ligadas ao "
    "Sistema S.",
    "É irregular a exigência, para fins de qualificação técnico-operacional, de comprovação de "
    "aptidão para execução de serviços similares ou de complexidade equivalente à do objeto "
    "licitado sem delimitação, de modo claro e verificável, das características mínimas.",
]

_ADMITE = [
    "Não é obrigatório que o orçamento estimado em planilhas de quantitativos e preços "
    "unitários seja parte integrante do edital do pregão, mas o ato convocatório deve conter "
    "informações para obter tal orçamento.",
    "O sobrepreço é desqualificado quando a metodologia de cálculo utiliza apenas um conjunto "
    "parcial de itens da obra e computa somente os serviços cujos preços são superiores aos do "
    "Sinapi, acrescidos de Benefícios e Despesas Indiretas.",
]

_DEVER = [
    "A demonstração da vantagem de renovação de contrato de serviços de natureza continuada "
    "deve ser realizada mediante ampla pesquisa de preços, priorizando-se consultas a portais "
    "de compras governamentais e a contratações similares.",
    "A modalidade de licitação aplicável à contratação de serviços de natureza continuada deve "
    "levar em consideração o valor global do contrato, incluindo as possíveis prorrogações.",
]


# ───────────────────────────── polaridade ─────────────────────────────────────────────────────

@pytest.mark.parametrize("enunciado", _VEDA)
def test_enunciado_que_veda(enunciado):
    r = classificar_enunciado(enunciado)
    assert r["polaridade"] == "veda"
    assert r["rotulo"] == "vicio"


@pytest.mark.parametrize("enunciado", _ADMITE)
def test_enunciado_que_admite(enunciado):
    r = classificar_enunciado(enunciado)
    assert r["polaridade"] == "admite"
    assert r["rotulo"] == "licito"


@pytest.mark.parametrize("enunciado", _DEVER)
def test_enunciado_de_dever(enunciado):
    """Dever descumprido é vício, mas a tese em si descreve a conduta CORRETA."""
    r = classificar_enunciado(enunciado)
    assert r["polaridade"] == "dever"
    assert r["rotulo"] == "vicio_por_omissao"


def test_abster_se_de_e_vedacao_nao_dever():
    """"A Administração deve abster-se de X" contém "deve", mas VEDA X."""
    e = "A Administração deve abster-se de exigir a comprovação de propriedade de equipamentos."
    assert classificar_enunciado(e)["polaridade"] == "veda"


def test_enunciado_sem_polaridade_e_declarado_nao_chutado():
    r = classificar_enunciado("Na contratação de serviços de engenharia, o objeto é complexo.")
    assert r["polaridade"] == "indefinida"
    assert r["rotulo"] is None, "sem polaridade não há rótulo — o caso sai do conjunto-ouro"


def test_texto_vazio_nao_quebra():
    assert classificar_enunciado("")["polaridade"] == "indefinida"
    assert classificar_enunciado(None)["polaridade"] == "indefinida"


def test_condicional_e_marcado_mas_nao_apaga_a_polaridade():
    """"É irregular X, salvo se Y" continua vedando X — mas o caso é mais difícil e isso conta."""
    e = ("É irregular a exigência de visita técnica obrigatória, salvo quando devidamente "
         "justificada a sua imprescindibilidade.")
    r = classificar_enunciado(e)
    assert r["polaridade"] == "veda"
    assert r["condicionada"] is True


def test_toda_polaridade_conhecida_tem_rotulo_ou_none():
    for p in POLARIDADES:
        assert p in ROTULOS


# ───────────────────────────── mapeamento para o catálogo ─────────────────────────────────────

@pytest.mark.parametrize("tema,subtema,vicio", [
    ("Qualificação técnica", "Atestado de capacidade técnica", "barreira_habilitacao"),
    ("Qualificação econômico-financeira", "Capital social", "barreira_habilitacao"),
    ("Dispensa de licitação", "", "contratacao_direta_indevida"),
    ("Inexigibilidade de licitação", "", "contratacao_direta_indevida"),
    ("Edital de licitação", "Especificação do objeto", "especificacao_dirigida"),
    ("Parcelamento do objeto", "", "lote_pacote"),
    ("Prorrogação de contrato", "Serviços contínuos", "prorrogacao_perpetua"),
    ("Alteração do contrato", "", "aditivo_excessivo"),
])
def test_mapeamento_para_o_catalogo_canonico(tema, subtema, vicio):
    """O rótulo tem de cair num dos 42 vícios do catálogo — senão não mede nada nosso."""
    from compliance_agent.knowledge.catalogo_vicios import obter
    assert mapear_vicio(tema, subtema) == vicio
    assert obter(vicio) is not None, f"{vicio} não está no catálogo canônico"


def test_tema_desconhecido_nao_e_chutado():
    assert mapear_vicio("Tema que não existe", "") is None


def test_todo_vicio_mapeado_existe_no_catalogo():
    """Trava: se alguém renomear um vício no catálogo, o mapa quebra aqui e não em produção."""
    from compliance_agent.knowledge.catalogo_vicios import obter
    from compliance_agent.knowledge.corpus_veredito import MAPA_TEMA_VICIO

    faltando = sorted({v for v in MAPA_TEMA_VICIO.values() if v and obter(v) is None})
    assert not faltando, f"vícios inexistentes no catálogo: {faltando}"


# ───────────────────────────── o caso do conjunto-ouro ────────────────────────────────────────

def test_caso_carrega_a_citacao_e_o_trecho_ancora():
    """Rótulo sem fonte é opinião. O caso guarda o acórdão e o enunciado VERBATIM."""
    caso = montar_caso({
        "numero": 1742, "ano": 2026, "colegiado": "Plenário", "area": "Licitação",
        "tema": "Qualificação técnica", "subtema": "Atestado de capacidade técnica",
        "enunciado": _VEDA[2], "referencia_legal": "[Lei Ordinária 14.133/2021 Art. 67 Inc. II]",
        "key": "JURISPRUDENCIA-SELECIONADA-205696",
    })
    assert caso["rotulo"] == "vicio"
    assert caso["vicio"] == "barreira_habilitacao"
    assert caso["citacao"] == "Acórdão 1.742/2026-Plenário"
    assert caso["trecho_ancora"] == _VEDA[2]
    assert caso["fonte"] == "TCU/Jurisprudência Selecionada"
    assert caso["id"] == "JURISPRUDENCIA-SELECIONADA-205696"


def test_caso_sem_rotulo_ou_sem_vicio_nao_entra():
    """Conjunto-ouro com caso não rotulado contamina a medição — melhor fora, e declarado."""
    assert montar_caso({"numero": 1, "ano": 2020, "colegiado": "Plenário",
                        "tema": "Qualificação técnica", "subtema": "",
                        "enunciado": "Na contratação de serviços, o objeto é complexo."}) is None
    assert montar_caso({"numero": 1, "ano": 2020, "colegiado": "Plenário",
                        "tema": "Tema inexistente", "subtema": "",
                        "enunciado": _VEDA[0]}) is None


def test_numeracao_do_acordao_sai_no_formato_da_casa():
    """`gate_citacoes` e `tcu_juris_index` esperam 'Acórdão 1.234/2020-Plenário'."""
    caso = montar_caso({"numero": 234, "ano": 2020, "colegiado": "Primeira Câmara",
                        "tema": "Dispensa de licitação", "subtema": "",
                        "enunciado": _VEDA[0], "key": "x"})
    assert caso["citacao"] == "Acórdão 234/2020-Primeira Câmara"


def test_a_citacao_gerada_e_verificavel_no_proprio_indice():
    """Fecha o círculo: o rótulo do conjunto-ouro tem de passar no gate anti-alucinação."""
    from compliance_agent.knowledge.tcu_juris_index import verificar_citacao

    caso = montar_caso({"numero": 1742, "ano": 2026, "colegiado": "Plenário",
                        "tema": "Qualificação técnica", "subtema": "", "key": "k",
                        "enunciado": _VEDA[2]})
    achados = verificar_citacao(caso["citacao"])
    assert achados, "citação gerada não foi sequer reconhecida como citação"
    assert achados[0]["status"] in {"confirmado", "indice_ausente"}, achados[0]
