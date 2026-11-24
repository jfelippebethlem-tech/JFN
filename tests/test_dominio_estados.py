# -*- coding: utf-8 -*-
"""O4.1 — `dominio.estados`: os 5 estados de saída + ABSTEVE(motivo) e a saúde operacional (plano §3.10)."""
from __future__ import annotations

import pytest

from compliance_agent.dominio.estados import EstadoSaida, Saida, SaudeOperacional, absteve


def test_estados_de_saida_sao_os_do_plano():
    assert [e.value for e in EstadoSaida] == ["AUSENTE", "INDISPONIVEL", "INCERTO", "INDICIO", "CONCLUSAO_REVISADA",
                                              "ABSTEVE"]
    assert EstadoSaida("AUSENTE") is EstadoSaida.AUSENTE and EstadoSaida.AUSENTE == "AUSENTE"


def test_saude_operacional():
    assert [e.value for e in SaudeOperacional] == ["SAUDAVEL", "DEGRADADO", "ATRASADO", "BLOQUEADO", "INDISPONIVEL"]


def test_indisponivel_nao_e_ausente():
    assert EstadoSaida.INDISPONIVEL != EstadoSaida.AUSENTE
    assert SaudeOperacional.INDISPONIVEL != SaudeOperacional.SAUDAVEL


def test_absteve_exige_motivo():
    assert str(absteve("sem texto legível")) == "ABSTEVE(sem texto legível)"
    with pytest.raises(ValueError):
        absteve("  ")
    with pytest.raises(ValueError):
        Saida("ABSTEVE")
    assert str(Saida("INDICIO")) == "INDICIO" and Saida("INDICIO").estado is EstadoSaida.INDICIO
    with pytest.raises(ValueError):
        Saida("LIMPO")
