# -*- coding: utf-8 -*-
"""Testes do detector P4 · Fracionamento (compliance_agent/detectores/p4_fracionamento.py).

Cluster sintético pequeno, LLM ausente/monkeypatchado. Cenários do spec:
  • 3 dispensas mesma natureza somando > limite → CONFIRMA (forte)
  • naturezas distintas (rubrica) → DESCARTA
  • sem marcador de dispensa / sem dado → nao_avaliavel (campo ausente ≠ 0)
  • demandas imprevisíveis (rubrica) → score limitado a 0.3 (exculpatória do spec)
"""
from __future__ import annotations

import pytest

from compliance_agent.detectores.p4_fracionamento import (
    P4Fracionamento,
    clusterizar,
    limite_dispensa,
)

P4 = P4Fracionamento()


# ───────────────────────────── helpers de fixture ─────────────────────────────
def _disp(objeto, valor, data, cnpj, **kw):
    return {"objeto": objeto, "valor": valor, "data_pagamento": data, "favorecido_cpf": cnpj,
            "dispensa": True, "exercicio": 2024, **kw}


# ───────────────────────────── limites / clustering ─────────────────────────────
def test_limite_dispensa_por_exercicio():
    assert limite_dispensa(2024, "compras") == pytest.approx(59906.02)
    assert limite_dispensa(2024, "obras") == pytest.approx(119812.02)
    # exercício futuro sem tabela → cai no mais próximo ≤
    assert limite_dispensa(2030, "compras") is not None


def test_clusteriza_objetos_similares_juntos():
    cs = [
        {"objeto": "aquisição de material de limpeza para o almoxarifado"},
        {"objeto": "aquisição de material de limpeza geral almoxarifado"},
        {"objeto": "contratação de serviço de transporte rodoviário"},
    ]
    clusters = clusterizar(cs)
    tam = sorted(len(c) for c in clusters)
    assert tam == [1, 2]  # os 2 de limpeza juntos, transporte sozinho


def test_clusteriza_por_catmat_explicito():
    cs = [{"objeto": "x", "catmat": "1234"}, {"objeto": "y totalmente diferente", "catmat": "1234"}]
    assert len(clusterizar(cs)) == 1  # mesmo CATMAT agrupa mesmo com objeto textual distinto


# ───────────────────────────── CONFIRMA: 3 dispensas mesma natureza > limite ─────────────────────────────
def test_tres_dispensas_mesma_natureza_acima_do_limite_confirma():
    # limite compras 2024 = 59.906,02 · 3 dispensas de ~25k cada = 75k > limite, mesmo fornecedor
    contratacoes = [
        _disp("aquisição de material de limpeza almoxarifado", 25000, "2024-01-10", "11222333000181"),
        _disp("aquisição de material de limpeza para almoxarifado", 25000, "2024-01-25", "11222333000181"),
        _disp("aquisição material de limpeza geral almoxarifado", 25000, "2024-02-05", "11222333000181"),
    ]
    res = P4.avaliar({"processo": "UG-X", "contratacoes": contratacoes})  # sem LLM (gerar ausente)
    assert res.status == "confirmado"
    assert res.score >= 0.85  # forte
    assert res.valores["n_dispensas_cluster"] == 3
    assert res.valores["soma_cluster"] == 75000.0
    assert res.valores["max_dispensas_mesmo_grupo_economico"] == 3
    assert res.valores["previsibilidade"] == "nao_avaliavel"  # sem LLM, natureza não auditada (honesto)
    assert res.evidencia  # cita as dispensas
    assert res.detector == "P4"


def test_proximidade_temporal_agrava():
    contratacoes = [
        _disp("material de limpeza almoxarifado", 25000, "2024-01-10", "11222333000181"),
        _disp("material de limpeza almoxarifado", 25000, "2024-01-15", "11222333000181"),  # 5 dias
        _disp("material de limpeza almoxarifado", 25000, "2024-01-20", "11222333000181"),
    ]
    res = P4.avaliar({"processo": "p", "contratacoes": contratacoes})
    assert res.status == "confirmado"
    assert res.score > 0.85  # 0.85 + 0.10 proximidade (clamp 1.0)
    assert res.valores["min_intervalo_dias"] == 5


# ───────────────────────────── DESCARTA: naturezas distintas (rubrica) ─────────────────────────────
def test_rubrica_naturezas_distintas_descarta():
    # objetos forçados ao mesmo cluster via CATMAT, mas a rubrica do auditor diz "naturezas distintas"
    contratacoes = [
        _disp("item A", 40000, "2024-01-10", "11222333000181", catmat="999",
              _rubrica_previsibilidade={"nivel": "naturezas_distintas", "trecho": "objetos sem relação"}),
        _disp("item B", 40000, "2024-02-10", "11222333000181", catmat="999"),
    ]
    res = P4.avaliar({"processo": "p", "contratacoes": contratacoes})
    assert res.status == "descartado"
    assert res.score == 0.0
    assert "naturezas distintas" in res.motivo_refutacao.lower()


def test_rubrica_demandas_imprevisiveis_limita_score_a_03():
    # spec: sem previsibilidade → máximo 0.3
    contratacoes = [
        _disp("manutenção corretiva predial", 35000, "2024-01-10", "11222333000181", catmat="555",
              _rubrica_previsibilidade={"nivel": "mesma_natureza_mas_demandas_independentes",
                                        "trecho": "manutenções corretivas distintas e imprevisíveis"}),
        _disp("manutenção corretiva predial", 35000, "2024-06-10", "11222333000181", catmat="555"),
    ]
    res = P4.avaliar({"processo": "p", "contratacoes": contratacoes})
    assert res.status == "confirmado"
    assert res.score == pytest.approx(0.3)


def test_rubrica_via_gerar_injetado():
    # LLM monkeypatchado (sem rede): retorna JSON da rubrica
    def fake_gerar(prompt, sistema):
        return '{"nivel":"mesma_natureza_e_previsivel","trecho":"material de limpeza recorrente"}'

    contratacoes = [
        _disp("material de limpeza almoxarifado", 30000, "2024-01-10", "11222333000181"),
        _disp("material de limpeza almoxarifado", 35000, "2024-02-10", "11222333000181"),
    ]
    res = P4.avaliar({"processo": "p", "contratacoes": contratacoes, "gerar": fake_gerar})
    assert res.status == "confirmado"
    assert res.valores["previsibilidade"] == "mesma_natureza_e_previsivel"


# ───────────────────────────── NAO_AVALIAVEL: sem dado / sem marcador ─────────────────────────────
def test_sem_contratacoes_nao_avaliavel():
    res = P4.avaliar({"processo": "p", "contratacoes": []})
    assert res.status == "nao_avaliavel"
    assert res.score == 0.0


def test_sem_marcador_de_dispensa_nao_avaliavel():
    # contratações sem nenhum campo de modalidade/dispensa (como vêm da DB de OBs) → nao_avaliavel, não 0
    contratacoes = [
        {"objeto": "material de limpeza", "valor": 30000, "data_pagamento": "2024-01-10", "favorecido_cpf": "11222333000181"},
        {"objeto": "material de limpeza", "valor": 35000, "data_pagamento": "2024-02-10", "favorecido_cpf": "11222333000181"},
    ]
    res = P4.avaliar({"processo": "p", "contratacoes": contratacoes})
    assert res.status == "nao_avaliavel"
    assert "dispensa" in res.motivo_refutacao.lower()
    assert res.valores["dispensas_identificaveis"] == 0


def test_dispensas_de_objetos_distintos_descartado():
    # 2 dispensas mas de objetos diferentes (clusters separados) → sem fracionamento
    contratacoes = [
        _disp("aquisição de material de limpeza", 40000, "2024-01-10", "11222333000181"),
        _disp("contratação de serviço de transporte rodoviário", 40000, "2024-02-10", "99888777000166"),
    ]
    res = P4.avaliar({"processo": "p", "contratacoes": contratacoes})
    assert res.status == "descartado"
    assert res.score == 0.0


def test_uma_dispensa_so_nao_fraciona():
    contratacoes = [_disp("material de limpeza", 80000, "2024-01-10", "11222333000181")]
    res = P4.avaliar({"processo": "p", "contratacoes": contratacoes})
    assert res.status == "descartado"


def test_soma_sob_o_limite_descartado():
    # 2 dispensas mesma natureza mas soma (40k) < limite (59.9k) e nenhuma rente ao teto → descartado
    contratacoes = [
        _disp("material de limpeza almoxarifado", 20000, "2024-01-10", "11222333000181"),
        _disp("material de limpeza almoxarifado", 20000, "2024-02-10", "11222333000181"),
    ]
    res = P4.avaliar({"processo": "p", "contratacoes": contratacoes})
    assert res.status == "descartado"
    assert res.score == 0.0


# ───────────────────────────── exculpatória estrutural: UGs autônomas ─────────────────────────────
def test_ugs_autonomas_rebaixa_para_medio():
    contratacoes = [
        _disp("material de limpeza almoxarifado", 30000, "2024-01-10", "11222333000181"),
        _disp("material de limpeza almoxarifado", 35000, "2024-02-10", "11222333000181"),
    ]
    res = P4.avaliar({"processo": "p", "contratacoes": contratacoes, "ug_autonomas": True})
    assert res.status == "confirmado"
    assert res.score == pytest.approx(0.6)  # rebaixado para médio
