# -*- coding: utf-8 -*-
"""Rede de proteção do detector E3 — lote-pacote / agregação anticompetitiva (art. 40 §2º).

Juntar mercados distintos num lote só elimina o especialista: quem fornece cabo não fornece
software, e quem fornece os dois é revendedor. A lei exige justificar o não-parcelamento.

O guard que não pode faltar: integração técnica REAL (itens que operam como sistema único) e
economia de escala DEMONSTRADA com números são exculpatórias legítimas. Sem elas, o detector
acusaria toda compra de solução integrada.

Sem rede, sem banco, sem LLM (as rubricas são injetadas).
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.e3_lote_pacote import E3LotePacote, _classe_mercado

_P = {"processo": "SEI-TESTE/000006/2026"}


def _lote(id_lote: str, *catmats: str) -> dict:
    return {"id": id_lote,
            "itens": [{"descricao": f"item {i}", "catmat": c} for i, c in enumerate(catmats)]}


# ───────────────────────────── classe de mercado ──────────────────────────────────────────────

def test_classe_e_o_prefixo_de_quatro_digitos_do_catmat():
    """4 primeiros dígitos = grupo de mercado. Dois CATMAT do mesmo grupo são o mesmo mercado."""
    assert _classe_mercado({"catmat": "123456789"}, None) == "1234"
    assert _classe_mercado({"catmat": "1234000"}, None) == "1234"


@pytest.mark.parametrize("campo", ["catmat", "catser", "classe", "mercado"])
def test_aceita_os_quatro_nomes_de_campo(campo):
    assert _classe_mercado({campo: "56789012"}, None) == "5678"


def test_usa_o_mapa_externo_quando_o_item_nao_traz_a_classe():
    item = {"descricao": "cabo de rede cat6"}
    assert _classe_mercado(item, {"cabo de rede cat6": "61451234"}) == "6145"


def test_sem_classe_devolve_none_e_nao_inventa_mercado():
    assert _classe_mercado({"descricao": "item sem código"}, None) is None
    assert _classe_mercado({"descricao": "x"}, {}) is None


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_lotes_e_nao_avaliavel():
    res = E3LotePacote().avaliar({**_P})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_lotes_sem_nenhum_item_classificado_e_nao_avaliavel():
    """Sem CATMAT não dá para contar mercados. Chutar aqui produziria achado inventado."""
    lotes = [{"id": "L1", "itens": [{"descricao": "material diverso"}] * 8}]
    res = E3LotePacote().avaliar({**_P, "lotes": lotes})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "CATMAT" in res.motivo_refutacao


# ───────────────────────────── heterogeneidade ────────────────────────────────────────────────

def test_lote_coeso_nao_e_indicio():
    res = E3LotePacote().avaliar({**_P, "lotes": [_lote("L1", "12340001", "12340002", "12340003")]})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert res.valores["n_mercados_no_lote"] == 1


def test_dois_mercados_ainda_nao_pontua():
    """O piso é 3 mercados: dois itens correlatos no mesmo lote é prática normal."""
    res = E3LotePacote().avaliar({**_P, "lotes": [_lote("L1", "11110001", "22220001")]})
    assert res.score == 0.0


def test_tres_mercados_e_heterogeneo_medio():
    res = E3LotePacote().avaliar({**_P, "lotes": [_lote("L1", "11110001", "22220001", "33330001")],
                                  "justificativa_pesquisada_nos_autos": True})
    assert res.score >= ANCORAS["medio"]
    assert res.valores["n_mercados_no_lote"] == 3
    assert res.evidencia


def test_cinco_mercados_e_fortemente_heterogeneo():
    lote = _lote("L1", "11110001", "22220001", "33330001", "44440001", "55550001")
    res = E3LotePacote().avaliar({**_P, "lotes": [lote],
                                  "justificativa_pesquisada_nos_autos": True})
    assert res.score >= ANCORAS["forte"]


def test_escolhe_o_lote_mais_heterogeneo_como_achado():
    lotes = [_lote("L1", "11110001", "11110002"),
             _lote("L2", "11110001", "22220001", "33330001", "44440001")]
    res = E3LotePacote().avaliar({**_P, "lotes": lotes,
                                  "justificativa_pesquisada_nos_autos": True})
    assert res.valores["lote_mais_heterogeneo"] == "L2"
    assert res.valores["n_lotes"] == 2


# ───────────────────────────── justificativa do art. 40 §2º ───────────────────────────────────

def test_justificativa_nao_ingerida_nao_vira_omissao_do_dever():
    """Distinção que o detector faz e que é o coração da regra do projeto:
    **indisponível ≠ ausente dos autos**.

    Não ter o campo no contexto é limitação NOSSA de ingestão. Só vira "omissão do dever do
    art. 40 §2º" quando o coletor afirma que pesquisou a íntegra e não achou.
    """
    res = E3LotePacote().avaliar({**_P, "lotes": [_lote("L1", "1111", "2222", "3333")]})
    assert res.valores["justificativa_status"] == "nao_avaliavel"
    assert "AUSENTE" not in res.motivo_refutacao


def test_lote_heterogeneo_sem_justificativa_NOS_AUTOS_e_omissao_do_dever():
    """Aqui sim: o coletor pesquisou os autos e não há justificativa. É omissão objetiva."""
    res = E3LotePacote().avaliar({**_P, "lotes": [_lote("L1", "1111", "2222", "3333")],
                                  "justificativa_pesquisada_nos_autos": True})
    assert res.score >= ANCORAS["forte"]
    assert "AUSENTE" in res.motivo_refutacao
    assert "40 §2º" in res.motivo_refutacao


def test_justificativa_generica_pontua_menos_que_ausencia_nos_autos():
    lotes = [_lote("L1", "1111", "2222", "3333")]
    ausente = E3LotePacote().avaliar({**_P, "lotes": lotes,
                                      "justificativa_pesquisada_nos_autos": True})
    generica = E3LotePacote().avaliar({**_P, "lotes": lotes,
                                       "_rubrica_justificativa": {"nivel": "generica",
                                                                  "trecho": "por conveniência administrativa"}})
    assert generica.score <= ausente.score


def test_justificativa_demonstrada_com_numeros_e_exculpatoria():
    """Economia de escala quantificada é justificativa VÁLIDA — a lei pede demonstração, e houve."""
    lotes = [_lote("L1", "1111", "2222", "3333", "4444", "5555")]
    res = E3LotePacote().avaliar({**_P, "lotes": lotes,
                                  "_rubrica_justificativa": {"nivel": "demonstrada",
                                                             "trecho": "ganho de escala de 12% na cotação"}})
    assert res.score <= ANCORAS["fraco"]


def test_rubrica_sem_citacao_literal_e_descartada():
    """Regra de ouro da spec §1.3: rubrica sem `trecho` não pontua — nunca se aceita chute do LLM."""
    lotes = [_lote("L1", "1111", "2222", "3333", "4444", "5555")]
    res = E3LotePacote().avaliar({**_P, "lotes": lotes,
                                  "_rubrica_interdep": {"nivel": "integracao_necessaria"}})
    assert res.valores["interdependencia"] == "nao_avaliavel"


def test_lote_coeso_sem_justificativa_nao_e_cobrado():
    """O dever de justificar nasce do não-parcelamento. Lote de um mercado só não o aciona."""
    res = E3LotePacote().avaliar({**_P, "lotes": [_lote("L1", "11110001", "11110002")]})
    assert res.score == 0.0


# ───────────────────────────── corroboração pelo resultado ────────────────────────────────────

def test_poucos_licitantes_no_lote_corrobora():
    lotes = [_lote("L1", "1111", "2222", "3333")]
    base = E3LotePacote().avaliar({**_P, "lotes": lotes,
                                   "justificativa_pesquisada_nos_autos": True})
    corrob = E3LotePacote().avaliar({**_P, "lotes": lotes,
                                     "justificativa_pesquisada_nos_autos": True,
                                     "resultado": {"licitantes_por_lote": {"L1": 1}}})
    assert corrob.score >= base.score
    assert corrob.valores["licitantes_no_lote"] == 1


def test_muitos_licitantes_nao_corrobora():
    """Se o mercado respondeu em peso, a tese de que o lote eliminou especialistas enfraquece."""
    lotes = [_lote("L1", "1111", "2222", "3333")]
    res = E3LotePacote().avaliar({**_P, "lotes": lotes,
                                  "justificativa_pesquisada_nos_autos": True,
                                  "resultado": {"licitantes_por_lote": {"L1": 9}}})
    assert res.valores["licitantes_no_lote"] == 9


# ───────────────────────────── exculpatórias ──────────────────────────────────────────────────

def test_integracao_tecnica_real_rebaixa_o_achado():
    """Itens que operam como sistema único justificam o lote. Sem este guard, toda compra de
    solução integrada (servidor + storage + licença) viraria achado."""
    lotes = [_lote("L1", "1111", "2222", "3333", "4444", "5555")]
    sem = E3LotePacote().avaliar({**_P, "lotes": lotes})
    com = E3LotePacote().avaliar({**_P, "lotes": lotes,
                                  "_rubrica_interdep": {"nivel": "integracao_necessaria",
                                                        "trecho": "servidor, storage e licença operam "
                                                                  "como sistema único"}})
    assert com.score < sem.score
    assert com.score <= ANCORAS["fraco"]


# ───────────────────────────── schema §1.4 ────────────────────────────────────────────────────

def test_schema_de_saida_conforme_spec():
    res = E3LotePacote().avaliar({**_P, "lotes": [_lote("L1", "1111", "2222", "3333")]})
    d = res.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "E3"
    assert d["status"] in STATUS_VALIDOS
    assert 0.0 <= d["score"] <= 1.0
