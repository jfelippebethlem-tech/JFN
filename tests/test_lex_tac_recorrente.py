# -*- coding: utf-8 -*-
"""Lex: TAC como rotina vira achado estrutural graduado por quantidade/valor (Decreto 47.283/2020, art. 4º, III)."""
from __future__ import annotations

from compliance_agent.lex_conflito import _tokens_tac, achado_tac_recorrente


def _tac(d, v, org="Fundação Saúde do Estado do Rio de Janeiro"):
    return {"data": d, "numero": "1/2026", "orgao": org, "valor": v, "processo": "SEI-080002/000001/2026"}


def test_ate_dois_tacs_nao_e_achado():
    assert achado_tac_recorrente([]) is None
    assert achado_tac_recorrente([_tac("2026-01-02", 1.0), _tac("2026-02-02", 1.0)]) is None


def test_tres_tacs_grave_3_e_seis_ou_dez_milhoes_grave_4():
    a = achado_tac_recorrente([_tac("2026-01-02", 100.0), _tac("2026-02-02", 100.0), _tac("2026-03-02", 100.0)])
    assert a["rf"] == "DD/TAC-RECORRENTE" and a["grav"] == 3
    assert "3 Termos de Ajuste de Contas" in a["obs"] and "2026-01-02 → 2026-03-02" in a["obs"]
    assert achado_tac_recorrente([_tac("2026-0%d-02" % i, 1.0) for i in range(1, 7)])["grav"] == 4
    assert achado_tac_recorrente([_tac("2026-01-02", 4e6), _tac("2026-02-02", 4e6), _tac("2026-03-02", 4e6)])["grav"] == 4


def test_tokens_do_nome_ignoram_forma_juridica():
    assert _tokens_tac("CMP - CAMPOS CLÍNICA MÉDICA E PEDIÁTRICA LTDA") == ["CMP", "CAMPOS"]
    assert _tokens_tac("AGILE CORP SERVIÇOS ESPECIALIZADOS LTDA") == ["AGILE", "CORP"]
    assert _tokens_tac("LTDA") == []
