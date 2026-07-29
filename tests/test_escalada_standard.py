# -*- coding: utf-8 -*-
"""A escalada passou a conferir o STANDARD, não só a gravidade.

`escalada.recomendar` media Severidade × Verossimilhança — quão grave e quão verossímil é o
padrão. Não media quanto de PROVA existe. O efeito: um caso pontuado 20 na matriz, mas sustentado
inteiramente por leitura de IA (grau C), saía como "representação ao Tribunal de Contas". É a
inflação de peça que a casa já corrigiu sete vezes, agora barrada em código.

A assimetria é intencional e igual à dos gatilhos: o standard só REBAIXA. Evidência forte não
transforma diligência em representação — quem escala é a régua S×V.
"""
from __future__ import annotations

from compliance_agent.editais.escalada import recomendar


def test_sem_grau_informado_nada_muda():
    """Retrocompatível: todos os chamadores atuais seguem funcionando igual."""
    r = recomendar(20)
    assert r["peca"] == "representacao" and r["standard"] is None


def test_representacao_sobre_juizo_de_IA_e_rebaixada():
    r = recomendar(20, grau_evidencia="C")
    assert r["peca"] == "diligencia"
    assert r["standard"]["rebaixada"] is True
    assert any("standard probatório" in g for g in r["gatilhos"])


def test_representacao_sobre_evidencia_forte_permanece():
    r = recomendar(20, grau_evidencia="B")
    assert r["peca"] == "representacao" and r["standard"]["rebaixada"] is False


def test_a_urgencia_NAO_e_rebaixada_junto_com_a_peca():
    """Certame aberto com sessão marcada continua urgente — muda a peça, não o prazo."""
    r = recomendar(20, certame_aberto=True, sessao_marcada=True, grau_evidencia="C")
    assert r["urgencia"] == "imediata"
    assert r["peca"] != "representacao_cautelar", "peça deveria ter sido rebaixada"


def test_standard_nunca_ELEVA_a_peca():
    r = recomendar(3, grau_evidencia="A", familias_independentes=3)
    assert r["peca"] == "monitorar" and r["standard"]["rebaixada"] is False


def test_grau_nao_afericavel_derruba_ate_monitorar():
    r = recomendar(22, grau_evidencia="D")
    assert r["peca"] == "monitorar"


def test_gatilho_societario_nao_supera_a_falta_de_prova():
    """Gatilho é agravante de gravidade; não substitui evidência."""
    r = recomendar(8, vinculo_societario_vencedor=True, grau_evidencia="C")
    assert r["peca"] == "diligencia"
    assert any("direcionamento consumado" in g for g in r["gatilhos"])


def test_fundamento_registra_o_rebaixamento_para_quem_assina():
    r = recomendar(20, grau_evidencia="C")
    assert "REBAIXADA" in r["fundamento"]
