# -*- coding: utf-8 -*-
"""Teste TARGETED do detector X2 (prorrogação perpétua, fase de execução) — spec V2 do dono §X2.

Estratégia (leve, VM 2 vCPU/sem swap): fixtures de CONTEXTO (dicts), SEM rede — a qualidade da pesquisa de
vantajosidade vem classificada no próprio contexto (`pesquisa_vantajosidade`) ou pré-injetada
(`_rubricas_vantajosidade`). Importa a classe DIRETO do módulo (o __init__ é integrado à parte pelo dono).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_detector_x2.py -q
"""
from __future__ import annotations

from compliance_agent.detectores.base import STATUS_VALIDOS, ANCORAS, ResultadoDetector
from compliance_agent.detectores.x2_prorrogacao_perpetua import X2ProrrogacaoPerpetua


def _valido(r: ResultadoDetector) -> None:
    """Invariantes do schema §1.4."""
    assert isinstance(r, ResultadoDetector)
    assert r.status in STATUS_VALIDOS
    assert 0.0 <= r.score <= 1.0
    assert isinstance(r.evidencia, list)
    d = r.to_dict()
    assert set(d) == {"detector", "processo", "score", "valores", "evidencia",
                      "explicacao_inocente", "refutada", "motivo_refutacao", "status"}


# ═══════════════════════════════ (a) confirma: anos longos + vantajosidade viciada ═══════════════════════════════
def test_x2_confirma_8anos_vantajosidade_ausente():
    """8 anos no mesmo objeto, prorrogações com pesquisa 'ausente'/'pro_forma' → forte."""
    ctx = {
        "processo": "exec-1",
        "tempo_total_anos": 8.0,
        "fornecedor_cnpj": "11111111000100",
        "prorrogacoes": [
            {"data": "2019-01-01", "anos": 1, "pesquisa_vantajosidade": "ausente"},
            {"data": "2020-01-01", "anos": 1, "pesquisa_vantajosidade": "pro_forma"},
            {"data": "2021-01-01", "anos": 1, "pesquisa_vantajosidade": "ausente"},
        ],
    }
    r = X2ProrrogacaoPerpetua().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]
    assert r.valores["tempo_total_anos"] == 8.0
    assert r.valores["n_vantajosidade_viciada"] == 3
    assert r.evidencia


def test_x2_confirma_10anos_critico():
    """> 10 anos no mesmo objeto sem relicitar → crítico."""
    ctx = {
        "processo": "exec-2",
        "vigencia_inicio": "2010-01-01",
        "vigencia_fim_atual": "2022-01-01",  # ~12 anos
        "prorrogacoes": [{"data": "2014-01-01", "pesquisa_vantajosidade": "ausente"}],
    }
    r = X2ProrrogacaoPerpetua().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.score == ANCORAS["critico"]
    assert r.valores["tempo_total_anos"] > 10.0


# ═══════════════════════════════ (b) confirma: cadeia emergência→prorrogação ═══════════════════════════════
def test_x2_confirma_cadeia_emergencia():
    """Cadeia emergência→prorrogação detectada via fundamento → agrava."""
    ctx = {
        "processo": "exec-3",
        "tempo_total_anos": 6.5,
        "prorrogacoes": [
            {"data": "2021-01-01", "fundamento": "contratação emergencial art. 75 VIII", "pesquisa_vantajosidade": "ausente"},
        ],
    }
    r = X2ProrrogacaoPerpetua().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.valores["cadeia_emergencia"] is True
    assert r.score >= ANCORAS["forte"]


def test_x2_confirma_cadeia_emergencia_flag_sozinha():
    """Cadeia emergencial (flag bool) com tempo curto → anomalia média a confirmar."""
    ctx = {
        "processo": "exec-3b",
        "tempo_total_anos": 2.0,
        "cadeia_emergencia": True,
        "prorrogacoes": [{"data": "2023-01-01", "pesquisa_vantajosidade": "real"}],
    }
    r = X2ProrrogacaoPerpetua().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.valores["cadeia_emergencia"] is True
    assert r.score >= ANCORAS["medio"]


# ═══════════════════════════════ (c) descartado: prorrogação curta + vantajosidade real ═══════════════════════════════
def test_x2_descartado_curta_com_vantajosidade_real():
    """Prorrogação curta com vantajosidade 'real' documentada em todas → exculpatória → descartado."""
    ctx = {
        "processo": "exec-4",
        "tempo_total_anos": 3.0,
        "prorrogacoes": [
            {"data": "2023-01-01", "pesquisa_vantajosidade": "real", "preco": 100.0, "ref_mercado": 102.0},
            {"data": "2024-01-01", "pesquisa_vantajosidade": "real", "preco": 101.0, "ref_mercado": 103.0},
        ],
    }
    r = X2ProrrogacaoPerpetua().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


def test_x2_descartado_tempo_curto_sem_indicio():
    """Tempo curto, sem prorrogações suficientes, sem cadeia → descartado."""
    ctx = {
        "processo": "exec-4b",
        "tempo_total_anos": 2.0,
        "prorrogacoes": [{"data": "2024-01-01", "pesquisa_vantajosidade": "real"}],
    }
    r = X2ProrrogacaoPerpetua().avaliar(ctx)
    _valido(r)
    assert r.status == "descartado"
    assert r.score == 0.0


# ═══════════════════════════════ (d) nao_avaliavel: sem vigência/prorrogações ═══════════════════════════════
def test_x2_nao_avaliavel_sem_dados():
    """Sem vigência/tempo e sem prorrogações → nao_avaliavel (campo ausente ≠ 0)."""
    r = X2ProrrogacaoPerpetua().avaliar({"processo": "exec-5"})
    _valido(r)
    assert r.status == "nao_avaliavel"
    assert r.score == 0.0
    assert "nao_avaliavel" in r.motivo_refutacao


def test_x2_nao_avaliavel_vantajosidade_sem_classificacao():
    """Tempo longo confirma pelo CÓDIGO, mas sem classificação/LLM a vantajosidade fica nao_avaliavel (honesto)."""
    ctx = {
        "processo": "exec-5b",
        "tempo_total_anos": 7.0,
        "prorrogacoes": [{"data": "2021-01-01"}, {"data": "2022-01-01"}],
    }
    r = X2ProrrogacaoPerpetua().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"  # tempo objetivo > 5 anos
    assert all(v["classe"] == "nao_avaliavel" for v in r.valores["vantajosidade"])
    assert r.valores["n_vantajosidade_viciada"] == 0


# ═══════════════════════════════ (e) parse de datas → tempo total ═══════════════════════════════
def test_x2_parse_datas_tempo_total():
    """Parse de vigencia_inicio→vigencia_fim_atual (datas) calcula o tempo total no CÓDIGO."""
    ctx = {
        "processo": "exec-6",
        "vigencia_inicio": "2016-06-01",
        "vigencia_fim_atual": "2024-06-01",  # ~8 anos
        "prorrogacoes": [{"data": "2020-06-01", "pesquisa_vantajosidade": "pro_forma"}],
    }
    r = X2ProrrogacaoPerpetua().avaliar(ctx)
    _valido(r)
    assert 7.9 <= r.valores["tempo_total_anos"] <= 8.1
    assert r.status == "confirmado"


def test_x2_parse_datas_br_e_soma_anos():
    """Parse de data BR (dd/mm/aaaa) no início + soma de 'anos' das prorrogações (sem fim explícito)."""
    ctx = {
        "processo": "exec-6b",
        "vigencia_inicio": "01/01/2018",
        "vigencia_original_anos": 1.0,
        "prorrogacoes": [
            {"anos": 2, "pesquisa_vantajosidade": "ausente"},
            {"anos": 3, "pesquisa_vantajosidade": "ausente"},
        ],
    }
    r = X2ProrrogacaoPerpetua().avaliar(ctx)
    _valido(r)
    # 1 (original) + 2 + 3 = 6 anos → forte
    assert r.valores["tempo_total_anos"] == 6.0
    assert r.status == "confirmado"
    assert r.score >= ANCORAS["forte"]


# ═══════════════════════════════ prorrogações sem nova licitação (contagem) ═══════════════════════════════
def test_x2_confirma_muitas_prorrogacoes():
    """≥3 prorrogações sem nova licitação → forte, mesmo com tempo moderado."""
    ctx = {
        "processo": "exec-7",
        "tempo_total_anos": 4.0,
        "prorrogacoes": [
            {"data": "2021-01-01", "pesquisa_vantajosidade": "ausente"},
            {"data": "2022-01-01", "pesquisa_vantajosidade": "ausente"},
            {"data": "2023-01-01", "pesquisa_vantajosidade": "pro_forma"},
        ],
    }
    r = X2ProrrogacaoPerpetua().avaliar(ctx)
    _valido(r)
    assert r.status == "confirmado"
    assert r.valores["n_prorrogacoes"] == 3
    assert r.score >= ANCORAS["forte"]
