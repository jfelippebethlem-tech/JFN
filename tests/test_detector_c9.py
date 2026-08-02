# -*- coding: utf-8 -*-
"""C9 — fornecedor pago majoritariamente FORA de contrato regular (TAC/indenização).

Cita C9TacFornecedor (exigência de test_todo_detector_tem_teste)."""
from compliance_agent.detectores.c9_tac_fornecedor import C9TacFornecedor


def _ctx(pct, total_tac, cobertura="verificado (10 OBs)", n=10):
    return {"processo": "X", "cnpj": "11111111000111",
            "tac": {"n": n, "n_tac": 5, "total": total_tac / (pct / 100) if pct else 0.0,
                    "total_tac": total_tac, "pct": pct, "n_sem_obs": 0, "cobertura": cobertura}}


def test_sem_contexto_nao_avaliavel():
    r = C9TacFornecedor().avaliar({"processo": "X"})
    assert r.status == "nao_avaliavel"


def test_cobertura_indisponivel_nao_avaliavel():
    # 100% das OB sem observação: pct=0 mas NÃO é "limpo" (INDISPONÍVEL ≠ 0)
    r = C9TacFornecedor().avaliar(_ctx(0.0, 0.0, cobertura="INDISPONIVEL (nenhuma OB com observação preenchida)"))
    assert r.status == "nao_avaliavel"


def test_pct_alto_confirma_critico():
    r = C9TacFornecedor().avaliar(_ctx(97.2, 20_746_999.52))
    assert r.status == "confirmado"
    assert r.score >= 0.9


def test_pct_medio_confirma_medio():
    r = C9TacFornecedor().avaliar(_ctx(33.9, 14_666_578.54))
    assert r.status == "confirmado"
    assert 0.4 <= r.score < 0.9


def test_pct_baixo_descarta():
    r = C9TacFornecedor().avaliar(_ctx(4.0, 120_000.0))
    assert r.status == "descartado"


def test_absoluto_reforca():
    # 30%+ com R$ 100M+ de TAC é grave mesmo sem passar de 50%
    r = C9TacFornecedor().avaliar(_ctx(35.0, 150_000_000.0))
    assert r.status == "confirmado"
    assert r.score >= 0.9
