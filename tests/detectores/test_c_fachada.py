# -*- coding: utf-8 -*-
"""Rede de proteção do detector C — empresa de fachada / laranja.

Este card é um TRADUTOR: `investigacao_dd` já fez o juízo por hipótese, e o C converte cada
hipótese na âncora do framework. A regra de conversão é deliberadamente conservadora e é o que
os testes trancam:

    CONFIRMADO + ALTO  -> forte      INDÍCIO + ALTO -> medio
    CONFIRMADO + outro -> medio      INDÍCIO + outro -> fraco

**Indício nunca vira crítico.** Crítico exige violação objetiva ou prova direta, e sinais de
fachada são sempre circunstanciais.

Os testes injetam `investigacao` pronta (caminho previsto no código), então nada aqui toca
DuckDB, rede ou o banco de produção.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.c_fachada import CFachada, _ancora_de_hipotese

_CNPJ = "11222333000144"


def _inv(*hipoteses: dict, grau: str = "medio") -> dict:
    return {"cnpj": _CNPJ, "grau": grau, "score": 0.5, "cobertura": {},
            "hipoteses": list(hipoteses)}


def _hip(codigo: str, status: str = "INDICIO", nivel: str = "ALTO") -> dict:
    return {"codigo": codigo, "titulo": f"hipótese {codigo}", "status": status,
            "nivel": nivel, "peso": 1.0, "fonte": "receita", "evidencia": "trecho de evidência"}


# ───────────────────────────── conversão de âncora ────────────────────────────────────────────

@pytest.mark.parametrize("status,nivel,esperado", [
    ("CONFIRMADO", "ALTO", "forte"),
    ("CONFIRMADO", "MEDIO", "medio"),
    ("INDICIO", "ALTO", "medio"),
    ("INDICIO", "BAIXO", "fraco"),
    ("", "", "fraco"),
])
def test_conversao_de_hipotese_para_ancora(status, nivel, esperado):
    assert _ancora_de_hipotese(status, nivel) == esperado


def test_indicio_nunca_vira_critico():
    """Sinal de fachada é circunstancial por natureza. Crítico exige prova direta."""
    for nivel in ("ALTO", "MEDIO", "BAIXO"):
        assert _ancora_de_hipotese("INDICIO", nivel) != "critico"
        assert _ancora_de_hipotese("CONFIRMADO", nivel) != "critico"


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_investigacao_indisponivel_e_nao_avaliavel():
    """Sem `investigacao` no contexto o card tenta o módulo pesado; falhando, declara."""
    import sys
    import types

    falso = types.ModuleType("compliance_agent.investigacao_dd")

    def _explode(*a, **k):
        raise RuntimeError("DuckDB fora do ar")

    falso.investigar = _explode
    sys.modules["compliance_agent.investigacao_dd"] = falso
    try:
        res = CFachada().avaliar({"cnpj": _CNPJ})
        assert res.status == "nao_avaliavel"
        assert res.score == 0.0
        assert "indisponível" in res.motivo_refutacao
    finally:
        sys.modules.pop("compliance_agent.investigacao_dd", None)


def test_empresa_sem_sinais_e_nao_avaliavel_nao_regular():
    """Ausência de hipótese mapeável NÃO é atestado de regularidade — o motivo diz isso."""
    res = CFachada().avaliar({"cnpj": _CNPJ, "investigacao": _inv()})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "ausência de juízo ≠ regular" in res.motivo_refutacao


def test_hipotese_de_outro_card_nao_e_absorvida():
    """H-PEP e H-BENEFICIO pertencem ao C6 e afins — este card não os reivindica."""
    res = CFachada().avaliar({"cnpj": _CNPJ, "investigacao": _inv(_hip("H-PEP"))})
    assert res.status == "nao_avaliavel"


# ───────────────────────────── mapeamento das hipóteses ───────────────────────────────────────

@pytest.mark.parametrize("codigo,card", [
    ("H-RECENTE", "C1"),
    ("H-CAPITAL", "C2"),
    ("H-END-RESID", "C2"),
    ("H-PORTE", "C2"),
    ("H-SITUACAO", "C3/C5"),
    ("H-COEND", "C4"),
    ("H-SOCIO-UNICO", "C4"),
])
def test_cada_hipotese_vira_o_card_certo(codigo, card):
    res = CFachada().avaliar({"cnpj": _CNPJ, "investigacao": _inv(_hip(codigo))})
    assert res.detector == card
    assert res.valores["hipotese"] == codigo


def test_confirmado_alto_vira_forte():
    res = CFachada().avaliar({"cnpj": _CNPJ,
                              "investigacao": _inv(_hip("H-CAPITAL", "CONFIRMADO", "ALTO"))})
    assert res.score == pytest.approx(ANCORAS["forte"])
    assert res.status == "confirmado"
    assert res.evidencia


def test_indicio_baixo_vira_fraco():
    res = CFachada().avaliar({"cnpj": _CNPJ,
                              "investigacao": _inv(_hip("H-RECENTE", "INDICIO", "BAIXO"))})
    assert res.score == pytest.approx(ANCORAS["fraco"])


# ───────────────────────────── múltiplas hipóteses ────────────────────────────────────────────

def test_avaliar_todos_devolve_um_resultado_por_hipotese():
    res = CFachada().avaliar_todos({"cnpj": _CNPJ,
                                    "investigacao": _inv(_hip("H-RECENTE"),
                                                         _hip("H-CAPITAL"),
                                                         _hip("H-COEND"))})
    assert len(res) == 3
    assert {r.detector for r in res} == {"C1", "C2", "C4"}


def test_avaliar_devolve_o_achado_lider():
    """A interface `Detector` devolve o de maior âncora — o resto vem por `avaliar_todos`."""
    res = CFachada().avaliar({"cnpj": _CNPJ,
                              "investigacao": _inv(_hip("H-RECENTE", "INDICIO", "BAIXO"),
                                                   _hip("H-CAPITAL", "CONFIRMADO", "ALTO"))})
    assert res.detector == "C2"
    assert res.score == pytest.approx(ANCORAS["forte"])


def test_todo_achado_traz_explicacao_inocente():
    """Indício ≠ acusação: todo resultado sai com a hipótese que o derrubaria."""
    for r in CFachada().avaliar_todos({"cnpj": _CNPJ,
                                       "investigacao": _inv(_hip("H-RECENTE"), _hip("H-CAPITAL"))}):
        assert r.explicacao_inocente
        assert "presunção de regularidade" in r.explicacao_inocente


def test_schema_de_saida_conforme_spec():
    d = CFachada().avaliar({"cnpj": _CNPJ, "investigacao": _inv(_hip("H-CAPITAL"))}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["status"] in STATUS_VALIDOS
    assert 0.0 <= d["score"] <= 1.0
