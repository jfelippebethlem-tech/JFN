# -*- coding: utf-8 -*-
"""Task 4.2 — screens estatísticos de conluio (OCDE/Huber & Imhof) sobre `proposta_item`."""
import sqlite3

import pytest

from compliance_agent.editais.coletor_propostas import garantir_tabela, persistir_propostas
from compliance_agent.editais.screens_conluio import (
    cv_lances,
    precos_cobertura,
    rd_vencedor,
    screens,
    skewness,
    vetores_unitarios_similares,
)

CERTAME = "PNCP-SCREEN-001/2026"
CNPJ_A = "12345678000195"
CNPJ_B = "98765432000110"
CNPJ_C = "11222333000181"


@pytest.fixture()
def con():
    con = sqlite3.connect(":memory:")
    garantir_tabela(con)
    yield con
    con.close()


def _persistir_itens(con, itens_por_forn: dict[str, list[float]], valor_total=True):
    """Persiste vetores unitários (item i → vu) por fornecedor; valor_total=vu (qtd 1)."""
    linhas = []
    for cnpj, vus in itens_por_forn.items():
        for i, vu in enumerate(vus, start=1):
            linhas.append({"item": i, "fornecedor_cnpj": cnpj, "valor_unitario": vu,
                           "valor_total": vu if valor_total else None, "fonte": "sei_precos"})
    persistir_propostas(con, CERTAME, linhas)


# ───────────────────────── screens unitários (INDISPONÍVEL ≠ 0) ─────────────────────────
def test_cv_lances():
    assert cv_lances([100.0, 101.0, 102.0]) == pytest.approx(0.00808, abs=1e-4)
    assert cv_lances([100.0, 101.0]) is None      # <3 lances → INDISPONÍVEL, não 0
    assert cv_lances([]) is None


def test_rd_vencedor():
    # b2−b1=10; diferenças entre perdedores [2, 2] → média 2 → RD=5 (cobertura clássica)
    assert rd_vencedor([100.0, 110.0, 112.0, 114.0]) == pytest.approx(5.0)
    assert rd_vencedor([100.0, 110.0, 110.0]) is None  # perdedores idênticos → divisão indefinida (honesto)
    assert rd_vencedor([100.0, 110.0]) is None


def test_skewness():
    assert skewness([1.0, 2.0, 9.0]) > 0
    assert skewness([1.0, 8.0, 9.0]) < 0
    assert skewness([5.0, 5.0, 5.0]) is None  # σ=0 → indefinida (o CV=0 já captura)
    assert skewness([1.0, 2.0]) is None


def test_precos_cobertura():
    assert precos_cobertura([100.0, 160.0, 162.0]) is True    # perdedores ≥1.5× e aglomerados
    assert precos_cobertura([100.0, 103.0, 106.0]) is False   # ninguém ≥1.5×
    assert precos_cobertura([100.0, 160.0, 300.0]) is False   # perdedores dispersos = disputa plausível
    assert precos_cobertura([100.0, 160.0]) is False          # <3 (apurabilidade tratada em screens())


def test_vetores_unitarios_similares(con):
    _persistir_itens(con, {
        CNPJ_A: [10.0, 20.0, 30.0],
        CNPJ_B: [10.5, 21.0, 31.5],    # = A × 1.05 exato → planilha compartilhada
        CNPJ_C: [10.1, 25.0, 33.0],    # razões 1.01/1.25/1.10 → dispersas
    })
    pares = vetores_unitarios_similares(con, CERTAME)
    assert len(pares) == 1
    assert {pares[0]["a"], pares[0]["b"]} == {CNPJ_A, CNPJ_B}
    assert pares[0]["n_itens"] == 3
    assert pares[0]["razao_media"] == pytest.approx(1.05)


def test_vetores_exigem_3_itens_comuns(con):
    _persistir_itens(con, {CNPJ_A: [10.0, 20.0], CNPJ_B: [10.5, 21.0]})  # só 2 itens
    assert vetores_unitarios_similares(con, CERTAME) == []


# ───────────────────────── agregado screens() ─────────────────────────
def test_certame_coordenado_score_alto(con):
    """CV<0.02 com vencedor −0,5% de B em todos os itens → planilha_compartilhada + score alto."""
    base = [100.0, 200.0, 300.0]
    _persistir_itens(con, {
        CNPJ_A: [round(v * 0.995, 2) for v in base],  # vencedor: −0,5% item a item (planilha!)
        CNPJ_B: base,
        CNPJ_C: [round(v * 1.002, 2) for v in base],
    })
    r = screens(con, CERTAME)
    assert r["n_lances"] == 3
    assert r["cv"] < 0.02
    assert {"cv_baixo", "rd_alto", "planilha_compartilhada"} <= set(r["flags"])
    assert any({p["a"], p["b"]} == {CNPJ_A, CNPJ_B} for p in r["planilha_compartilhada"])
    assert r["score_conluio"] > 0.5      # ≥2 concordantes → pode passar de 0.5
    assert r["confianca"] == 1.0


def test_certame_disperso_score_baixo(con):
    _persistir_itens(con, {
        CNPJ_A: [100.0, 50.0, 250.0],
        CNPJ_B: [150.0, 180.0, 290.0],
        CNPJ_C: [300.0, 240.0, 350.0],
    })
    r = screens(con, CERTAME)
    assert r["flags"] == []
    assert r["score_conluio"] == 0.0
    assert r["confianca"] == 1.0  # tudo apurável — e nada disparou


def test_menos_de_3_lances_indisponivel(con):
    persistir_propostas(con, CERTAME, [
        {"item": 0, "fornecedor_cnpj": CNPJ_A, "valor_total": 100.0, "fonte": "ata"},
        {"item": 0, "fornecedor_cnpj": CNPJ_B, "valor_total": 175.0, "fonte": "ata"},
    ])
    r = screens(con, CERTAME)
    assert r["n_lances"] == 2
    assert r["cv"] is None and r["rd"] is None and r["skew"] is None and r["cobertura"] is None
    assert r["flags"] == []
    assert r["score_conluio"] == 0.0
    assert r["confianca"] == 0.0  # nada apurável ≠ certame limpo


def test_um_screen_so_nao_passa_de_meio(con):
    """REGRA OCDE: 1 screen disparado sozinho fica capado em 0.5 (nunca 'suspeito' com 1 indício)."""
    # só vetores unitários apuráveis (valor_total ausente → sem lances p/ CV/RD/skew/cobertura)
    _persistir_itens(con, {CNPJ_A: [10.0, 20.0, 30.0], CNPJ_B: [10.5, 21.0, 31.5]}, valor_total=False)
    r = screens(con, CERTAME)
    assert r["n_lances"] == 0
    assert r["flags"] == ["planilha_compartilhada"]
    assert r["score_conluio"] == 0.5
    assert r["confianca"] == pytest.approx(0.2)
