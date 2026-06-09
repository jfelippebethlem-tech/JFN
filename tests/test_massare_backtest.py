"""
Loop 10 — backtest OOS do Massare (reproduz o mercado em todos os pregões).

Garante que: (1) walk_forward expõe a taxa-base do mercado; (2) predict_today carrega o
edge honesto (skill acima do ingênuo); (3) o harness de backtest agrega sem inventar Brier.
Lê a base local massare/data/massare.db (sem rede).
"""
from pathlib import Path

import pytest

_DB = Path(__file__).resolve().parent.parent / "massare" / "data" / "massare.db"
pytestmark = pytest.mark.skipif(not _DB.exists(), reason="massare.db ausente neste ambiente")


def _symbol_com_dados():
    import sqlite3
    with sqlite3.connect(str(_DB)) as c:
        r = c.execute("SELECT symbol FROM prices GROUP BY symbol HAVING COUNT(*) >= 320 "
                      "ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    return r[0] if r else None


def test_walk_forward_expoe_taxa_base():
    from massare.engine import walk_forward
    sym = _symbol_com_dados()
    assert sym, "sem símbolo com série suficiente"
    wf = walk_forward(sym, horizon=5)
    assert wf.get("ensemble_n", 0) > 100
    assert wf["base_up_rate"] is not None and 0.0 <= wf["base_up_rate"] <= 1.0
    # piso ingênuo é sempre >= 0.5 (direção majoritária)
    assert wf["base_naive_rate"] >= 0.5


def test_predict_today_carrega_edge_honesto():
    from massare.engine import predict_today
    sym = _symbol_com_dados()
    pred = predict_today(sym, horizon=5)
    assert pred is not None
    assert pred["direction"] in ("up", "down")
    # os campos de honestidade têm de existir
    assert "edge_oos" in pred and "tem_skill" in pred and "base_naive_rate" in pred
    if pred["edge_oos"] is not None:
        assert pred["tem_skill"] == (pred["edge_oos"] > 0)


def test_backtest_run_agrega_sem_inventar_brier():
    from massare import backtest
    sym = _symbol_com_dados()
    res = backtest.run(symbols=[sym], horizons=(5,))
    o = res["overall"]
    assert o["n_pregoes_avaliados"] > 100
    assert o["hit_rate_oos"] is not None
    assert o["edge_medio"] is not None
    # honestidade: nada de Brier calibrado fabricado
    assert "brier" not in str(res).lower()


def test_resumo_overall_para_placar():
    """O /placar consome backtest.resumo_overall(): ou None (nunca rodou) ou um dict honesto."""
    from massare import backtest
    r = backtest.resumo_overall()
    if r is not None:
        assert "hit_rate_oos" in r and "base_naive_rate" in r and "edge_medio" in r
        # edge é hit_rate - piso ingênuo (coerência)
        if all(r.get(k) is not None for k in ("hit_rate_oos", "base_naive_rate", "edge_medio")):
            assert abs((r["hit_rate_oos"] - r["base_naive_rate"]) - r["edge_medio"]) < 0.01
