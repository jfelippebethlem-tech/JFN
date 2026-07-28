# -*- coding: utf-8 -*-
"""Rede de proteção do detector E6 — pontuação técnica dirigida (técnica e preço).

Duas regras objetivas e uma simulação que é o achado mais forte do pacote inteiro:
· percentual dos pontos em critérios subjetivo-puros;
· critério que pontua experiência com o PRÓPRIO órgão (barreira a entrantes por construção);
· **zerar os critérios suspeitos e recalcular** — se o vencedor MUDA, os critérios foram
  decisivos. Isso não é indício, é demonstração.

Sem rede, sem banco, sem LLM.
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.base import ANCORAS, STATUS_VALIDOS
from compliance_agent.detectores.e6_pontuacao_dirigida import E6PontuacaoDirigida

_P = {"processo": "SEI-TESTE/000016/2026"}


def _crit(nome: str, pontos: float, subjetivo: bool = False, **extra) -> dict:
    d = {"criterio": nome, "pontos": pontos, **extra}
    if subjetivo:
        d["subjetividade"] = "subjetivo_puro"
    return d


# ───────────────────────────── invariante de honestidade ──────────────────────────────────────

def test_sem_matriz_e_nao_avaliavel():
    res = E6PontuacaoDirigida().avaliar({**_P})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0
    assert "campo ausente ≠ 0" in res.motivo_refutacao


def test_matriz_sem_pontos_e_nao_avaliavel():
    """Sem pontos não há denominador — o percentual de subjetividade seria invenção."""
    res = E6PontuacaoDirigida().avaliar({**_P, "matriz_pontuacao": [{"criterio": "metodologia"}]})
    assert res.status == "nao_avaliavel"
    assert res.valores["total_pontos"] == 0


def test_matriz_objetiva_nao_e_indicio():
    matriz = [_crit("atestados comprovados", 60), _crit("prazo de entrega", 40)]
    res = E6PontuacaoDirigida().avaliar({**_P, "matriz_pontuacao": matriz})
    assert res.score == 0.0
    assert res.valores["pct_subjetivo"] == 0.0


# ───────────────────────────── percentual de subjetividade ────────────────────────────────────

@pytest.mark.parametrize("pts_subj,pontua", [(20, False), (39, False), (40, True), (70, True)])
def test_limiar_de_pontos_subjetivos(pts_subj, pontua):
    matriz = [_crit("metodologia", pts_subj, subjetivo=True),
              _crit("atestados", 100 - pts_subj)]
    res = E6PontuacaoDirigida().avaliar({**_P, "matriz_pontuacao": matriz})
    assert (res.score >= ANCORAS["medio"]) is pontua
    assert res.valores["pct_subjetivo"] == pytest.approx(pts_subj / 100)


def test_lista_os_criterios_subjetivos_para_conferencia():
    matriz = [_crit("metodologia", 30, subjetivo=True),
              _crit("qualidade da proposta", 30, subjetivo=True),
              _crit("preço", 40)]
    res = E6PontuacaoDirigida().avaliar({**_P, "matriz_pontuacao": matriz})
    assert set(res.valores["criterios_subjetivos"]) == {"metodologia", "qualidade da proposta"}


# ───────────────────────────── experiência com o próprio órgão ────────────────────────────────

def test_criterio_que_exige_experiencia_com_o_proprio_orgao_pontua():
    """Só o incumbente tem essa experiência — a barreira está na própria redação."""
    matriz = [_crit("serviços prestados a esta Secretaria", 30,
                    exige_experiencia_proprio_orgao=True),
              _crit("preço", 70)]
    res = E6PontuacaoDirigida().avaliar({**_P, "matriz_pontuacao": matriz})
    assert res.score >= ANCORAS["medio"]
    assert res.valores["criterios_proprio_orgao"] == ["serviços prestados a esta Secretaria"]


# ───────────────────────────── a simulação ────────────────────────────────────────────────────

def test_simulacao_que_troca_o_vencedor_e_o_achado_mais_forte():
    """Zerando os critérios suspeitos o vencedor muda: eles foram DECISIVOS, não acessórios."""
    matriz = [_crit("metodologia", 50, subjetivo=True), _crit("preço", 50)]
    propostas = [{"cnpj": "11222333000144", "notas": {"metodologia": 50, "preço": 10}},
                 {"cnpj": "44555666000177", "notas": {"metodologia": 0, "preço": 50}}]
    res = E6PontuacaoDirigida().avaliar({**_P, "matriz_pontuacao": matriz,
                                         "propostas_tecnicas": propostas,
                                         "vencedor_cnpj": "11222333000144"})
    assert res.score >= ANCORAS["forte"]
    assert res.valores["simulacao"]["vencedor_muda"] is True
    assert res.valores["simulacao"]["vencedor_sem"] == "44555666000177"


def test_simulacao_que_mantem_o_vencedor_nao_agrava():
    """Se o vencedor ganharia de qualquer jeito, o critério subjetivo não decidiu nada."""
    matriz = [_crit("metodologia", 50, subjetivo=True), _crit("preço", 50)]
    propostas = [{"cnpj": "11222333000144", "notas": {"metodologia": 50, "preço": 50}},
                 {"cnpj": "44555666000177", "notas": {"metodologia": 10, "preço": 10}}]
    res = E6PontuacaoDirigida().avaliar({**_P, "matriz_pontuacao": matriz,
                                         "propostas_tecnicas": propostas,
                                         "vencedor_cnpj": "11222333000144"})
    assert res.valores["simulacao"].get("vencedor_muda") is not True


def test_sem_propostas_a_simulacao_declara_que_nao_simulou():
    """Sem notas por proposta não há como recalcular — o detector diz isso, não assume nada."""
    matriz = [_crit("metodologia", 50, subjetivo=True), _crit("preço", 50)]
    res = E6PontuacaoDirigida().avaliar({**_P, "matriz_pontuacao": matriz})
    assert res.valores["simulacao"]["vencedor_muda"] is False
    assert "não aplicável" in res.valores["simulacao"]["motivo"]


def test_schema_de_saida_conforme_spec():
    matriz = [_crit("metodologia", 50, subjetivo=True), _crit("preço", 50)]
    d = E6PontuacaoDirigida().avaliar({**_P, "matriz_pontuacao": matriz}).to_dict()
    for campo in ("detector", "processo", "score", "valores", "evidencia",
                  "explicacao_inocente", "refutada", "motivo_refutacao", "status"):
        assert campo in d
    assert d["detector"] == "E6"
    assert d["status"] in STATUS_VALIDOS
