# -*- coding: utf-8 -*-
"""Rede de proteção do detector J4 — supressão de propostas / licitante único.

O afunilamento (muitos inscritos → um classificado) é o sinal clássico de bid rigging da OECD.
Mas inabilitação técnica fundada e uniforme é saneamento LEGÍTIMO (art. 64) — a exculpatória
tem de ser respeitada, senão o detector acusa todo pregão bem conduzido.

Sem rede, sem banco.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.j4_supressao_propostas import J4SupressaoPropostas, _n

_P = {"processo": "SEI-TESTE/000003/2026"}


def _inab(n: int, motivo: str = "índice de liquidez abaixo do exigido") -> list[dict]:
    return [{"cnpj": f"1122233300{i:04d}", "motivo": motivo} for i in range(n)]


# ───────────────────────────── contagem ───────────────────────────────────────────────────────

@pytest.mark.parametrize("valor,esperado", [
    (5, 5),
    ([1, 2, 3], 3),
    ((1, 2), 2),
    ({"a", "b"}, 2),
    ([], 0),
])
def test_conta_aceita_int_e_colecao(valor, esperado):
    assert _n(valor) == esperado


def test_booleano_nao_conta_como_numero():
    """`True` é int em Python e viraria 1 classificado — guard necessário."""
    assert _n(True) is None
    assert _n(None) is None


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_classificados_e_nao_avaliavel():
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 10})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


# ───────────────────────────── afunilamento ───────────────────────────────────────────────────

def test_afunilamento_de_muitos_para_um_pontua_forte():
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 8,
                                          "licitantes_classificados": 1,
                                          "inabilitados": _inab(7)})
    assert res.score >= ANCORAS["forte"]
    assert res.status == "confirmado"
    assert "afunilamento" in res.motivo_refutacao
    assert res.evidencia


def test_inscritos_estimado_quando_nao_informado():
    """Muita ata não traz o total de inscritos — reconstrói por classificados+inabilitados+desistências."""
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_classificados": 1,
                                          "inabilitados": _inab(5)})
    assert res.valores["inscritos_efetivo"] == 6
    assert res.score >= ANCORAS["forte"]


def test_inabilitacao_fundada_e_uniforme_e_exculpatoria():
    """Saneamento legítimo (art. 64) não é supressão. Sem este guard o detector acusa pregão correto."""
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 8,
                                          "licitantes_classificados": 1,
                                          "inabilitados": _inab(7),
                                          "inabilitacao_fundada_uniforme": True})
    assert res.score == 0.0
    assert res.status == "descartado"


def test_competicao_preservada_nao_inventa_indicio():
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 8,
                                          "licitantes_classificados": 6,
                                          "inabilitados": _inab(2)})
    assert res.score == 0.0
    assert res.status == "descartado"
    assert res.explicacao_inocente


def test_poucos_inscritos_com_um_classificado_e_apenas_medio():
    """2 inscritos → 1 classificado não é afunilamento: mercado pequeno explica. Anomalia a confirmar."""
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 2,
                                          "licitantes_classificados": 1,
                                          "inabilitados": _inab(1)})
    assert res.score == pytest.approx(ANCORAS["medio"])


def test_licitante_unico_sem_ninguem_barrado_nao_pontua():
    """Certame que só teve um interessado desde o início não é supressão — é falta de mercado."""
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 1,
                                          "licitantes_classificados": 1})
    assert res.score == 0.0
    assert res.status == "descartado"


# ───────────────────────────── motivos grosseiros ─────────────────────────────────────────────

def test_erro_grosseiro_agrava_o_afunilamento():
    """Empresa experiente que entrega proposta em branco sugere cobertura combinada."""
    base = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 8,
                                           "licitantes_classificados": 1,
                                           "inabilitados": _inab(7)})
    grosseiro = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 8,
                                                "licitantes_classificados": 1,
                                                "inabilitados": _inab(7, "proposta em branco")})
    assert grosseiro.score > base.score


def test_motivo_legitimo_nao_conta_como_grosseiro():
    """A lista de motivos grosseiros é ESTREITA de propósito: 'atestado insuficiente' é inabilitação
    técnica legítima e não pode virar agravante."""
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 8,
                                          "licitantes_classificados": 1,
                                          "inabilitados": _inab(7, "atestado de capacidade insuficiente")})
    assert res.score == pytest.approx(ANCORAS["forte"])


def test_erro_grosseiro_sem_afunilamento_nao_pontua_sozinho():
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 8,
                                          "licitantes_classificados": 6,
                                          "inabilitados": _inab(2, "certidão vencida")})
    assert res.score == 0.0


# ───────────────────────────── desistência em massa ───────────────────────────────────────────

def test_desistencia_em_massa_deixando_um_pontua_forte():
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 6,
                                          "licitantes_classificados": 1,
                                          "desistencias": ["a", "b", "c", "d"]})
    assert res.score >= ANCORAS["forte"]
    assert "desistências em massa" in res.motivo_refutacao


def test_desistencia_em_massa_com_inabilitacao_uniforme_nao_pontua():
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 6,
                                          "licitantes_classificados": 1,
                                          "desistencias": ["a", "b", "c", "d"],
                                          "inabilitacao_fundada_uniforme": True})
    assert res.score == 0.0


# ───────────────────────────── robustez e schema ──────────────────────────────────────────────

def test_lixo_na_lista_de_inabilitados_nao_quebra():
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 8,
                                          "licitantes_classificados": 1,
                                          "inabilitados": [None, "texto", 42, {"cnpj": "x"}]})
    assert res.status in STATUS_VALIDOS


def test_schema_de_saida_conforme_spec():
    res = J4SupressaoPropostas().avaliar({**_P, "licitantes_inscritos": 8,
                                          "licitantes_classificados": 1,
                                          "inabilitados": _inab(7)})
    d = res.to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "J4"
    assert 0.0 <= d["score"] <= 1.0
