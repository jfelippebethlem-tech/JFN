# -*- coding: utf-8 -*-
"""Escalada codificada — editais/escalada.py (régua S×V + gatilhos da skill §4-§5, agora executáveis).
Rodar só este arquivo:  .venv/bin/python -m pytest tests/editais/test_escalada.py -q
"""
from __future__ import annotations

from compliance_agent.editais.escalada import PECAS, recomendar


def test_regua_base_sem_gatilhos():
    assert recomendar(3)["peca"] == "monitorar"
    assert recomendar(7)["peca"] == "diligencia"
    assert recomendar(12)["peca"] == "diligencia_prioritaria"
    assert recomendar(20)["peca"] == "representacao"


def test_certame_aberto_com_vicio_grave_vira_cautelar():
    r = recomendar(20, certame_aberto=True, sessao_marcada=True)
    assert r["peca"] == "representacao_cautelar"
    assert r["urgencia"] == "imediata"


def test_certame_aberto_sem_gravidade_nao_escala():
    # gatilho de cautelar exige vício grave (degrau ≥ representação); S×V 7 aberto continua diligência
    assert recomendar(7, certame_aberto=True)["peca"] == "diligencia"


def test_vinculo_societario_muda_a_natureza():
    r = recomendar(6, vinculo_societario_vencedor=True)
    assert r["peca"] == "representacao"
    assert any("consumado" in g for g in r["gatilhos"])


def test_teste_objetivo_violado_sobe_para_minuta():
    r = recomendar(6, teste_objetivo_violado=True)
    assert r["peca"] == "diligencia_prioritaria"


def test_reincidencia_propoe_auditoria_tematica():
    r = recomendar(8, reincidencia_orgao=3)
    assert r["auditoria_tematica"] is True
    assert r["peca"] == "diligencia"  # auditoria é proposta PARALELA, não substitui a peça do achado


def test_gatilhos_so_sobem_nunca_descem():
    # assimetria intencional: nenhuma combinação de flags pode rebaixar o degrau do S×V puro
    base = PECAS.index(recomendar(20)["peca"])
    for flags in ({"certame_aberto": False}, {"reincidencia_orgao": 0}, {"sessao_marcada": True}):
        assert PECAS.index(recomendar(20, **flags)["peca"]) >= base


def test_sv_fora_da_faixa_e_clampado():
    assert recomendar(0)["sv"] == 1
    assert recomendar(99)["sv"] == 25
