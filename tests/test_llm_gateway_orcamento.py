# -*- coding: utf-8 -*-
"""Gateway LLM, O6.1 (b): teto MENSAL da API paga (US$ 100, corte a 85%). Abaixo do corte passa; entre 85% e
100% só tarefa crítica; acima de 100% nada pago; custo não estimável ⇒ recusa. Regra da casa: nenhum teste gasta —
o gasto do mês é semeado direto no trace e o backend pago é dublê."""
import sqlite3

import pytest
import yaml

from tests.autorizacao_paga_dubles import autorizar
from compliance_agent.adaptadores.llm import gateway as G

MSG = [{"role": "user", "content": "texto curto"}]
# 24/11/2026: normalizacao_itens passou a [2, 3] (assinatura primeiro); estes testes medem só a trava da camada PAGA,
# por isso pedem `so_camadas=(3,)`.


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    # 24/11/2026: estes testes exercitam a camada paga COM dublê — o dono "autoriza" num livro temporário
    autorizar(tmp_path, monkeypatch)
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(tmp_path / "trace.db"))
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "estado"))
    monkeypatch.setattr(G, "_pre_assinatura", lambda t: None)
    return tmp_path


def _semear_gasto(tmp_path, usd: float, mes_atual: bool = True):
    con = sqlite3.connect(tmp_path / "trace.db")
    G.migrar(con)
    ts = "datetime('now')" if mes_atual else "datetime('now', '-40 days')"
    con.execute(f"INSERT INTO llm_trace(ts, origem, provedor, ok, ms, pago, custo_usd) "
                f"VALUES({ts}, 'gateway', 'api_anthropic', 1, 1, 1, ?)", (usd,))
    con.commit()


def _critica(tmp_path, monkeypatch, tarefa="leitura_integral"):
    pol = yaml.safe_load(G._caminho_politica().read_text(encoding="utf-8"))
    pol["tarefas"][tarefa]["critica"] = True
    p = tmp_path / "pol.yaml"
    p.write_text(yaml.safe_dump(pol, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("JFN_LLM_POLITICA", str(p))


def _api():
    vistos = []

    def b(**kw):
        vistos.append(kw["tarefa"])
        return G.Retorno(texto="ok", modelo="claude-haiku-5-5", tokens_in=100, tokens_out=10)
    return vistos, b


def test_regra_do_corte_pura():
    assert G.motivo_orcamento(10.0, 1.0, 100.0, 0.85, critica=False) is None
    assert "corte" in G.motivo_orcamento(84.99, 0.02, 100.0, 0.85, critica=False)
    assert G.motivo_orcamento(84.99, 0.02, 100.0, 0.85, critica=True) is None
    assert "teto mensal" in G.motivo_orcamento(99.99, 0.02, 100.0, 0.85, critica=True)


def test_abaixo_do_corte_passa_e_soma_no_mes(_isolado):
    _semear_gasto(_isolado, 10.0)
    vistos, b = _api()
    r = G.chamar("normalizacao_itens", MSG, prompt_version="v1", classe_dado="publico", so_camadas=(3,), backends={"api_anthropic": b})
    assert vistos == ["normalizacao_itens"] and r.custo_usd == pytest.approx((100 * 0.10 + 10 * 0.50) / 1e6)
    assert G.gasto_mes_usd() == pytest.approx(10.0 + r.custo_usd)


def test_entre_85_e_100_so_critica(_isolado, monkeypatch):
    _semear_gasto(_isolado, 86.0)
    vistos, b = _api()
    with pytest.raises(G.OrcamentoEsgotado, match="corte de 85%"):
        G.chamar("normalizacao_itens", MSG, prompt_version="v1", classe_dado="publico", so_camadas=(3,),
                 backends={"api_anthropic": b})
    assert vistos == []
    _critica(_isolado, monkeypatch, "normalizacao_itens")
    r = G.chamar("normalizacao_itens", MSG, prompt_version="v1", classe_dado="publico", so_camadas=(3,), backends={"api_anthropic": b})
    assert vistos == ["normalizacao_itens"] and r.camada == 3


def test_acima_de_100_nada_pago_nem_critica(_isolado, monkeypatch):
    _semear_gasto(_isolado, 100.0)
    _critica(_isolado, monkeypatch, "normalizacao_itens")
    vistos, b = _api()
    with pytest.raises(G.OrcamentoEsgotado, match="teto mensal"):
        G.chamar("normalizacao_itens", MSG, prompt_version="v1", classe_dado="publico", so_camadas=(3,), backends={"api_anthropic": b})
    assert vistos == []
    con = sqlite3.connect(_isolado / "trace.db")
    assert con.execute("SELECT erro FROM llm_trace WHERE origem='gateway' AND ok=0").fetchall() == \
        [("recusado: orçamento",)]


def test_teto_barra_o_pago_mas_o_gratis_da_tarefa_segue(_isolado, monkeypatch):
    """Tarefa com assinatura antes da API: teto estourado não impede a camada não paga."""
    _semear_gasto(_isolado, 150.0)
    vistos, b = _api()
    r = G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="publico",
                 backends={"assinatura_claude": lambda **kw: G.Retorno(texto="ok", modelo="claude-sonnet-5-5"),
                           "api_anthropic": b})
    assert r.camada == 2 and r.custo_usd is None and vistos == []


def test_gasto_de_outro_mes_nao_conta(_isolado):
    _semear_gasto(_isolado, 99.0, mes_atual=False)
    assert G.gasto_mes_usd() == 0.0


def test_reservas_em_curso_contam_e_sao_liberadas(_isolado):
    pol = G.politica()
    _semear_gasto(_isolado, 84.0)
    rid, motivo = G._reservar(0.9, False, pol)           # 84 + 0,9 = 84,9 < 85: cabe e fica reservado
    assert rid and motivo is None
    rid2, motivo2 = G._reservar(0.2, False, pol)         # 84 + 0,9 + 0,2 > 85: a reserva viva conta
    assert rid2 is None and "corte" in motivo2
    G._liberar(rid)
    rid3, _ = G._reservar(0.2, False, pol)
    assert rid3


def test_reserva_de_processo_morto_expira(_isolado, monkeypatch):
    pol = G.politica()
    _semear_gasto(_isolado, 84.0)
    rid, _ = G._reservar(0.9, False, pol)
    agora = G.time.time()
    monkeypatch.setattr(G.time, "time", lambda: agora + G._RESERVA_VALIDADE_S + 1)
    rid2, motivo = G._reservar(0.2, False, pol)
    assert rid2 and motivo is None


def test_custo_nao_estimavel_recusa_o_pago(_isolado, monkeypatch, tmp_path):
    p = tmp_path / "precos.yaml"
    p.write_text("fonte: {url: x, conferido_em: '2026-11-24'}\nmodelos: {}\n", encoding="utf-8")
    monkeypatch.setenv("JFN_LLM_PRECOS", str(p))
    vistos, b = _api()
    with pytest.raises(G.OrcamentoEsgotado, match="não estimável"):
        G.chamar("normalizacao_itens", MSG, prompt_version="v1", classe_dado="publico", so_camadas=(3,), backends={"api_anthropic": b})
    assert vistos == []


def test_falha_paga_conta_a_estimativa(_isolado):
    def cai(**kw):
        raise RuntimeError("API: falhou (APIConnectionError)")
    with pytest.raises(G.SemProvedor):
        G.chamar("normalizacao_itens", MSG, prompt_version="v1", classe_dado="publico", so_camadas=(3,),
                 backends={"api_anthropic": cai})
    con = sqlite3.connect(_isolado / "trace.db")
    custo, fonte = con.execute("SELECT custo_usd, custo_fonte FROM llm_trace WHERE origem='gateway'").fetchone()
    assert custo is not None and custo > 0 and fonte == "estimativa_falha"
    assert G.estado_orcamento()["reservado_usd"] == 0.0     # reserva liberada


def test_estimativa_conservadora_usa_o_pior_caso():
    tab = G.precos()
    modelo, mt, est = G._estimativa_api("normalizacao_itens", None, "s" * 250, "p" * 2500, None, tab)
    assert modelo == "claude-haiku-5-5" and mt == 4000
    assert est == pytest.approx(G.estimar_usd(modelo, 150 + 1050, 4000, tab))
    assert est >= G.custo_usd(modelo, 1200, 4000, tab=tab)
