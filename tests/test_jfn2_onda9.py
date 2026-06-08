# -*- coding: utf-8 -*-
"""Testes da Onda 9 (Massare teses + validação López de Prado)."""
from __future__ import annotations


def test_aplicar_custos_desconta():
    from massare.validation import aplicar_custos
    r = aplicar_custos([0.01, 0.01], custo_por_trade=0.001, turnover=1.0)
    assert all(abs(x - 0.009) < 1e-9 for x in r)


def test_max_drawdown():
    from massare.validation import max_drawdown
    # +10% depois -50% => dd ~ -0.5
    assert max_drawdown([0.10, -0.50]) < -0.4


def test_dsr_edge_vs_ruido():
    """Série com edge forte e estável → DSR alto; ruído → DSR baixo."""
    from massare.validation import deflated_sharpe
    edge = [0.01] * 200  # retorno constante positivo (Sharpe altíssimo)
    ruido = [0.01 if i % 2 == 0 else -0.0101 for i in range(200)]  # ~zero, alterna
    de = deflated_sharpe(edge, n_tentativas=10)
    dr = deflated_sharpe(ruido, n_tentativas=10)
    assert de["dsr"] > dr["dsr"]
    assert dr["significativo"] is False  # ruído nunca é significativo


def test_dsr_amostra_pequena_indisponivel():
    from massare.validation import deflated_sharpe
    assert deflated_sharpe([0.01, 0.02])["ok"] is False  # n<10 honesto


def test_theses_mock(monkeypatch):
    """Teses a partir de narrativas em alta (news mockado); cada tese registra previsão."""
    from massare import theses

    def fake_boletim(temas=None, janela="2d", por_tema=5):
        return {"ok": True, "blocos": [
            {"tema": "Federal Reserve interest rates", "artigos": [
                {"titulo": "Federal Reserve signals hawkish interest rates", "fonte": "reuters.com"}]}]}

    monkeypatch.setattr("massare.news.boletim_temas", fake_boletim)
    r = theses.atual(registrar=False)
    assert r["ok"] is True
    # a narrativa fed_hawkish deve ter casado
    assert any(t["narrativa"] == "fed_hawkish" for t in r["teses"])
    t = next(t for t in r["teses"] if t["narrativa"] == "fed_hawkish")
    assert t["direcao"] == "baixa" and t["horizonte_dias"] == 21 and 0 < t["conf"] <= 0.9


def test_carteira_sem_json_honesto():
    from massare.carteira import carteira
    r = carteira()
    assert r["ok"] is True and r["posicoes"] == [] and "INDISPONÍVEL" in r["_nota"]


def test_capabilities_massare_onda9_pronto():
    from compliance_agent.skilltree import SkillTree
    st = SkillTree()
    st.reload()
    for cid in ("massare_teses", "massare_carteira"):
        cap = st.capacidades.get(cid)
        assert cap is not None and cap["status"] == "PRONTO", cid
    assert st.validate() == []
