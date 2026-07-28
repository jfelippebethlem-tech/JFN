# -*- coding: utf-8 -*-
"""Rede de proteção do detector E4 — visita técnica usada como filtro.

Visita obrigatória sem alternativa de declaração é barreira: obriga deslocamento, e — pior —
**expõe ao órgão e aos concorrentes quem pretende competir**. Com agendamento controlado, o
certame vira lista de presença.

A exculpatória é real e forte: em obra peculiar as condições locais determinam o preço, e a
visita é indispensável. Sem esse guard o detector acusaria toda licitação de engenharia.

Sem rede, sem banco, sem LLM.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.e4_visita_tecnica import E4VisitaTecnica, _norm_cnpj

_P = {"processo": "SEI-TESTE/000013/2026"}
_FILTRO = {"obrigatoria": True, "alternativa_declaracao": False}


def test_normaliza_cnpj_para_digitos():
    assert _norm_cnpj("11.222.333/0001-44") == "11222333000144"
    assert _norm_cnpj(None) == ""


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_clausula_de_visita_e_nao_avaliavel():
    """Não ter ingerido a cláusula não é o mesmo que ela não existir."""
    res = E4VisitaTecnica().avaliar({**_P})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_visita_facultativa_nao_e_indicio():
    res = E4VisitaTecnica().avaliar({**_P, "visita": {"obrigatoria": False}})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert res.explicacao_inocente


def test_alternativa_de_declaracao_afasta_a_barreira():
    """A jurisprudência admite substituir a visita por declaração de conhecimento do local."""
    res = E4VisitaTecnica().avaliar({**_P, "visita": {"obrigatoria": True,
                                                      "alternativa_declaracao": True}})
    assert res.score == 0.0
    assert res.status == "descartado"


# ───────────────────────────── barreira e agravantes ──────────────────────────────────────────

def test_visita_obrigatoria_sem_alternativa_e_medio():
    res = E4VisitaTecnica().avaliar({**_P, "visita": dict(_FILTRO)})
    assert res.score == pytest.approx(ANCORAS["medio"])
    assert res.evidencia


def test_agendamento_controlado_agrava_para_forte():
    """Quem controla a agenda sabe quem vai competir — e pode avisar o preferido."""
    res = E4VisitaTecnica().avaliar({**_P, "visita": {**_FILTRO, "agendamento_controlado": True}})
    assert res.score >= ANCORAS["forte"]
    assert "agendamento controlado" in res.motivo_refutacao


@pytest.mark.parametrize("dias,agrava", [(1, True), (2, True), (3, False), (10, False)])
def test_janela_estreita_agrava(dias, agrava):
    res = E4VisitaTecnica().avaliar({**_P, "visita": {**_FILTRO, "janela_dias": dias}})
    assert (res.score >= ANCORAS["forte"]) is agrava
    assert res.valores["janela_estreita"] is agrava


def test_agravante_sozinho_sem_obrigatoriedade_nao_pontua():
    """Agenda controlada numa visita FACULTATIVA não é barreira — ninguém é obrigado a aparecer."""
    res = E4VisitaTecnica().avaliar({**_P, "visita": {"obrigatoria": False,
                                                      "agendamento_controlado": True,
                                                      "janela_dias": 1}})
    assert res.score == 0.0


# ───────────────────────────── evasão pós-visita ──────────────────────────────────────────────

def test_evasao_alta_com_amostra_suficiente_e_forte():
    """Visitou e não propôs: o candidato viu quem mais estava lá e desistiu."""
    visitantes = [f"1122233300{i:04d}" for i in range(5)]
    res = E4VisitaTecnica().avaliar({**_P, "visita": {"obrigatoria": False},
                                     "visitantes": visitantes,
                                     "licitantes": visitantes[:1]})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["n_evadidos"] == 4


def test_evasao_alta_com_amostra_pequena_e_rebaixada():
    """2 visitantes e 1 desistência não sustentam tese — o detector rebaixa e diz por quê."""
    res = E4VisitaTecnica().avaliar({**_P, "visita": {"obrigatoria": False},
                                     "visitantes": ["11222333000144", "44555666000177"],
                                     "licitantes": ["11222333000144"]})
    assert res.score == pytest.approx(ANCORAS["fraco"])
    assert "amostra pequena" in res.motivo_refutacao


def test_sem_lista_de_visitantes_nao_inventa_taxa():
    res = E4VisitaTecnica().avaliar({**_P, "visita": dict(_FILTRO)})
    assert res.valores["taxa_evasao"] is None
    assert res.valores["n_visitantes"] is None


def test_todos_os_visitantes_propuseram_nao_ha_evasao():
    visitantes = [f"1122233300{i:04d}" for i in range(5)]
    res = E4VisitaTecnica().avaliar({**_P, "visita": {"obrigatoria": False},
                                     "visitantes": visitantes, "licitantes": visitantes})
    assert res.valores["n_evadidos"] == 0
    assert res.score == 0.0


# ───────────────────────────── correlação com J1/J4 ───────────────────────────────────────────

def test_evadido_recorrente_em_outros_certames_agrava():
    """Quem visita, evade e reincide em desistência alimenta a tese de rodízio."""
    visitantes = ["11222333000144", "44555666000177"]
    res = E4VisitaTecnica().avaliar({**_P, "visita": {"obrigatoria": False},
                                     "visitantes": visitantes,
                                     "licitantes": ["11222333000144"],
                                     "evadidos_em_outros_certames": ["44.555.666/0001-77"]})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["evadidos_recorrentes"] == ["44555666000177"]


# ───────────────────────────── exculpatória de necessidade ────────────────────────────────────

def test_visita_indispensavel_rebaixa_o_achado():
    """Obra peculiar: as condições do local determinam o preço. Exigir visita é legítimo."""
    sem = E4VisitaTecnica().avaliar({**_P, "visita": dict(_FILTRO)})
    com = E4VisitaTecnica().avaliar({**_P, "visita": dict(_FILTRO),
                                     "_rubrica_necessidade": {"nivel": "indispensavel",
                                                              "trecho": "reforma em encosta com acesso restrito"}})
    assert com.score < sem.score


def test_schema_de_saida_conforme_spec():
    d = E4VisitaTecnica().avaliar({**_P, "visita": dict(_FILTRO)}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "E4"
    assert d["status"] in STATUS_VALIDOS
