# -*- coding: utf-8 -*-
"""Rede de proteção do detector C7 — sanção impeditiva vigente à época (art. 156 §§4º-5º).

O ponto que separa este detector de um verificador ingênuo de CEIS: **vigência na DATA DO ATO**,
não hoje. Empresa sancionada em 2025 podia contratar legalmente em 2023. E nem toda sanção impede
contratar — multa e publicação extraordinária são punição sem vedação.

Sem rede, sem banco.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.c7_sancionada_contratada import C7SancionadaContratada, _eh_impeditiva

_P = {"processo": "SEI-TESTE/000011/2026"}


def _s(categoria: str, ini: str, fim: str | None = None, cadastro: str = "CEIS") -> dict:
    return {"cadastro": cadastro, "categoria": categoria, "data_inicio": ini,
            "data_fim": fim, "orgao": "CGU"}


# ───────────────────────────── o que impede contratar ─────────────────────────────────────────

@pytest.mark.parametrize("cat", [
    "Impedimento de licitar e contratar",
    "Proibição de contratar com o Poder Público",
    "Inidoneidade",
    "Suspensão temporária de participação em licitação",
])
def test_categorias_impeditivas(cat):
    assert _eh_impeditiva(cat) is True


@pytest.mark.parametrize("cat", [
    "Multa",
    "Publicação extraordinária da decisão condenatória",
    "Suspensão/interdição das atividades",
])
def test_punicao_sem_vedacao_de_contratar_nao_e_impeditiva(cat):
    """'Interdição das atividades' é sanção operacional (ambiental/sanitária), não veda contratar.

    Tratá-la como impeditiva produziria acusação de vedação que a lei não impõe.
    """
    assert _eh_impeditiva(cat) is False


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

@pytest.mark.parametrize("ctx", [
    {"sancoes": []},
    {"data_referencia": "2026-01-15"},
])
def test_sem_data_ou_sem_lista_de_sancoes_e_nao_avaliavel(ctx):
    """Não ter consultado o CEIS não é o mesmo que a empresa estar limpa."""
    res = C7SancionadaContratada().avaliar({**_P, **ctx})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "INDISPONÍVEL ≠ 0" in res.motivo_refutacao


def test_cnpj_sem_registro_e_descartado():
    res = C7SancionadaContratada().avaliar({**_P, "data_referencia": "2026-01-15", "sancoes": []})
    assert res.status == "descartado"
    assert res.score == 0.0


# ───────────────────────────── vigência à época ───────────────────────────────────────────────

def test_sancao_impeditiva_vigente_na_data_e_critica():
    res = C7SancionadaContratada().avaliar({
        **_P, "data_referencia": "2026-01-15",
        "sancoes": [_s("Impedimento de licitar e contratar", "2025-01-01", "2027-01-01")]})
    assert res.score >= ANCORAS["critico"] or res.score == pytest.approx(1.0)
    assert res.valores["teste_objetivo"] == "violado"
    assert "156" in res.evidencia[0]


def test_sancao_que_comecou_depois_do_ato_nao_conta():
    """O ato foi legal quando praticado. Punir retroativamente é erro grosseiro de método."""
    res = C7SancionadaContratada().avaliar({
        **_P, "data_referencia": "2023-05-10",
        "sancoes": [_s("Inidoneidade", "2025-01-01", "2027-01-01")]})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert "fora da vigência" in res.motivo_refutacao


def test_sancao_ja_encerrada_na_data_nao_conta():
    res = C7SancionadaContratada().avaliar({
        **_P, "data_referencia": "2026-01-15",
        "sancoes": [_s("Inidoneidade", "2019-01-01", "2021-01-01")]})
    assert res.status == "descartado"


def test_sancao_sem_data_fim_permanece_vigente():
    res = C7SancionadaContratada().avaliar({
        **_P, "data_referencia": "2026-01-15",
        "sancoes": [_s("Inidoneidade", "2025-01-01", None)]})
    assert res.score > 0
    assert res.valores["n_vigentes"] == 1


# ───────────────────────────── sanção vigente porém não impeditiva ────────────────────────────

def test_sancao_vigente_nao_impeditiva_e_medio_e_nao_aferivel():
    """Multa vigente é fato relevante, mas não veda contratar — o detector não afirma vedação."""
    res = C7SancionadaContratada().avaliar({
        **_P, "data_referencia": "2026-01-15",
        "sancoes": [_s("Multa", "2025-01-01", "2027-01-01")]})
    assert res.score == pytest.approx(ANCORAS["medio"])
    assert res.valores["teste_objetivo"] == "nao_aferivel"
    assert "NÃO impeditiva" in res.evidencia[0]


def test_impeditiva_vence_a_nao_impeditiva_quando_ambas_vigem():
    res = C7SancionadaContratada().avaliar({
        **_P, "data_referencia": "2026-01-15",
        "sancoes": [_s("Multa", "2025-01-01", "2027-01-01"),
                    _s("Inidoneidade", "2025-06-01", "2028-01-01")]})
    assert res.valores["teste_objetivo"] == "violado"
    assert res.valores["n_vigentes"] == 2
    assert res.valores["n_impeditivas"] == 1


def test_schema_de_saida_conforme_spec():
    d = C7SancionadaContratada().avaliar({
        **_P, "data_referencia": "2026-01-15",
        "sancoes": [_s("Inidoneidade", "2025-01-01", "2027-01-01")]}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "C7"
    assert d["status"] in STATUS_VALIDOS
