# -*- coding: utf-8 -*-
"""O loop de autoaprimoramento tem de DENUNCIAR quando não tem sinal.

Medido em 2026-08-02 no `data/nucleo_evolucao.json`: 36 rodadas entre 02/07 e 02/08, **922
candidatos testados, 0 mantidos**, `f1_inicial == f1_final == 1.0` em todas elas, 0 red flags
propostas. Motivo: o conjunto-ouro são os 8 casos sintéticos embutidos, que o motor já acerta
100% — não existe margem para nenhuma calibração ser aprovada. O diário registrava isso como
rodada normal, e por um mês o sistema pareceu estar aprendendo enquanto revertia tudo.

Um sistema de fiscalização não pode se enganar sobre si mesmo: se o placar não tem margem, ou
se não há caso REAL na régua, o relatório diz.
"""
import json

import pytest

from compliance_agent.nucleo import autoaprimoramento as A
from compliance_agent.nucleo.avaliacao import ResultadoAvaliacao


def _placar(f1, fa=0):
    return ResultadoAvaliacao(f1_global=f1, precisao=f1, cobertura=f1,
                              acertos=10, perdidos=0, falsos_alarmes=fa)


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setenv("NUCLEO_EVOLUCAO_FILE", str(tmp_path / "evolucao.json"))
    monkeypatch.setenv("NUCLEO_CASOS_OURO", str(tmp_path / "ouro.json"))
    monkeypatch.setenv("NUCLEO_FEEDBACK_FILE", str(tmp_path / "feedback.json"))


def test_teto_saturado_e_denunciado():
    d = A.diagnosticar_sinal(_placar(1.0), mantidos=[], casos_reais=0)
    assert d["saturado"] is True
    assert "1.0" in d["motivo"] or "margem" in d["motivo"].lower()


def test_regua_so_sintetica_e_denunciada():
    """F1 abaixo do teto, mas sem nenhum caso real: a régua não representa o acervo."""
    d = A.diagnosticar_sinal(_placar(0.7), mantidos=[], casos_reais=0)
    assert d["sem_caso_real"] is True


def test_loop_com_margem_e_caso_real_nao_e_saturado():
    d = A.diagnosticar_sinal(_placar(0.7), mantidos=[{"parametro": "x"}], casos_reais=12)
    assert d["saturado"] is False and d["sem_caso_real"] is False


def test_diario_grava_o_diagnostico(monkeypatch, tmp_path):
    """O que não entra no diário não existe para o próximo turno."""
    monkeypatch.setattr(A, "avaliar_sistema", lambda *a, **k: _placar(1.0))
    monkeypatch.setattr(A, "_gerar_candidatos", lambda passo=0.10: [])
    monkeypatch.setattr(A, "descobrir_red_flags", lambda *a, **k: [])
    rel = A.executar_loop(max_rodadas=1)
    assert rel.saturado is True
    registro = json.loads((tmp_path / "evolucao.json").read_text(encoding="utf-8"))[-1]
    assert registro["saturado"] is True
    assert registro["motivo"]
    assert registro["casos_reais"] == 0
