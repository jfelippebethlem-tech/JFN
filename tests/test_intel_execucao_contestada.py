# -*- coding: utf-8 -*-
"""§1-G: veredito antigo que negava a OB (e a linha mostra OB paga) sai MARCADO como pendente de reavaliação."""
from __future__ import annotations

from compliance_agent import correlacao_sei
from compliance_agent.reporting import intel_md


def _item(em, indicios):
    return {"numero_sei": "SEI-330002/031566/2024", "n_obs": 2, "total": 1500.5, "exec": "nao", "nota": 6,
            "resumo": "execução não comprovada", "indicios": indicios, "avaliado_em": em}


def test_veredito_antigo_que_negava_a_ob_e_marcado(monkeypatch):
    monkeypatch.setattr(correlacao_sei, "execucao_de_fornecedor",
                        lambda cnpj: [_item("2026-09-01T10:00", '["Ausência de Ordem Bancária (OB)"]')])
    md = intel_md._render_execucao({"cnpj": "1"})
    assert "veredito anterior negava a OB" in md and "pendente de reavaliação" in md


def test_veredito_novo_ou_que_nao_nega_a_ob_fica_como_esta(monkeypatch):
    monkeypatch.setattr(correlacao_sei, "execucao_de_fornecedor", lambda cnpj: [
        _item("2026-10-30T10:00", '["Ausência de Ordem Bancária (OB)"]'),
        _item("2026-09-01T10:00", '["Sem atesto de recebimento"]')])
    md = intel_md._render_execucao({"cnpj": "1"})
    assert "veredito anterior" not in md and "pendente de reavaliação" not in md
