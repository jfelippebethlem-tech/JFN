# -*- coding: utf-8 -*-
"""Trava o ERRO CONCEITUAL OB ≠ contrato ≠ processo (cadeia da despesa).

Um contrato gera várias OBs; um processo SEI (licitação/SRP) pode gerar vários contratos, aditivos e muitas
OBs. O relatório NUNCA pode contar OB como contrato. Testa o helper, a frase e a nota conceitual."""
from compliance_agent.reporting.inteligencia import (
    _NOTA_CARDINALIDADE,
    _frase_cardinalidade,
    cardinalidade_contratual,
)


def test_nota_conceitual_distingue_os_tres_niveis():
    n = _NOTA_CARDINALIDADE
    assert "OB" in n and "contrato" in n and "processo" in n
    assert "nº de OBs ≠ nº de contratos ≠ nº de processos" in n
    assert "SRP" in n or "Registro de Preços" in n  # ata de registro de preços
    assert "aditivos" in n  # processo gera aditivos


def test_frase_nunca_equipara_ob_a_contrato():
    card = {"n_obs": 3669, "n_obs_com_processo": 101, "n_processos": 46,
            "cobertura_processo": 0.028, "n_contratos": 0}
    f = _frase_cardinalidade(card)
    assert "3669 OBs" in f
    assert "46 processo" in f
    assert "cobertura 3%" in f  # honesto sobre a vinculação esparsa
    assert "OB ≠ contrato" in f
    # NUNCA dizer "3669 contratos"
    assert "3669 contrato" not in f


def test_frase_vazia_sem_dados():
    assert _frase_cardinalidade({}) == ""
    assert _frase_cardinalidade({"n_obs": 0}) == ""


def test_cardinalidade_real_ob_maior_que_processo():
    # na base real, nº de OBs >= nº de processos distintos (um processo gera muitas OBs)
    card = cardinalidade_contratual("05969071000110")
    if card["n_obs"]:  # só se o CNPJ tem OBs na base
        assert card["n_obs"] >= card["n_processos"]
        assert 0.0 <= card["cobertura_processo"] <= 1.0
