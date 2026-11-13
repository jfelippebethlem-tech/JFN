# -*- coding: utf-8 -*-
"""Backend API do motor Claude — cliente DUBLÊ; nenhum teste chama a Anthropic nem lê a chave real."""
import json
from types import SimpleNamespace as NS

import pytest

from compliance_agent.llm import claude_api as A
from compliance_agent.llm import claude_motor as M
from compliance_agent.llm import verificacao as V


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "d"))
    monkeypatch.setenv("JFN_ANTHROPIC_ENV", str(tmp_path / "nao_existe.env"))
    for v in ("JFN_API_TETO_USD", "JFN_API_SONNET_TAREFAS", "JFN_API_RESERVA_LIBERADA", "JFN_CLAUDE_API"):
        monkeypatch.delenv(v, raising=False)


class Cliente:
    def __init__(self, texto="ok", stop="end_turn", usage=None, entrada=1000, modelo=None, categoria=None):
        self.criados = []
        cli = self
        usage = usage or {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 0,
                          "cache_creation_input_tokens": 0}

        def criar(**kw):
            cli.criados.append(kw)
            return NS(content=[NS(type="text", text=texto)], stop_reason=stop, usage=usage,
                      model=modelo or kw["model"], stop_details=NS(category=categoria))
        self.messages = NS(count_tokens=lambda **kw: NS(input_tokens=entrada), create=criar)
        self.beta = NS(messages=NS(create=criar))


def test_sem_chave_o_backend_some_em_silencio(monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST")
    assert A.disponivel() is False
    assert A.pensar_api("triagem_alertas", "p") is None and "sem chave" in A.ultimo_motivo


def test_chave_lida_do_arquivo_e_nunca_no_motivo(tmp_path, monkeypatch):
    f = tmp_path / "a.env"
    f.write_text("ANTHROPIC_API_KEY_JFN=sk-ant-SEGREDO\nJFN_API_TETO_USD=100\n")
    monkeypatch.setenv("JFN_ANTHROPIC_ENV", str(f))
    assert A.disponivel() and A.teto_usd() == 100 and A.limite_efetivo() == 95

    class Explode(Cliente):
        def __init__(self):
            super().__init__()
            self.messages = NS(count_tokens=lambda **kw: (_ for _ in ()).throw(RuntimeError("sk-ant-SEGREDO")))
    assert A.pensar_api("triagem_alertas", "p", cliente=Explode()) is None
    assert "SEGREDO" not in A.ultimo_motivo and "SEGREDO" not in json.dumps(A.ler_gasto())


def test_custo_por_usage_com_cache_e_lote():
    u = {"input_tokens": 40_000, "output_tokens": 40_000, "cache_read_input_tokens": 40_000,
         "cache_creation_input_tokens": 0}
    base = (0.10 + 0.50 + 0.01) * 0.04
    assert A.custo("claude-haiku-5-5", u) == pytest.approx(base)
    assert A.custo("claude-haiku-5-5", u, lote=True) == pytest.approx(base / 2)
    longo = {"input_tokens": 200_000}                     # prompt > 100K: preço de cima do Haiku
    assert A.custo("claude-haiku-5-5", longo) == pytest.approx(0.10)
    assert A.custo("claude-sonnet-5-5", {"input_tokens": 1_000_000}) == pytest.approx(2.0)
    assert A.custo("modelo-desconhecido", {"input_tokens": 1_000_000}) == pytest.approx(4.0)


def test_haiku_padrao_sonnet_so_por_lista_opus_nunca(monkeypatch):
    cli = Cliente()
    A.pensar_api("triagem_alertas", "p", cliente=cli)
    A.pensar_api("triagem_alertas", "p2", modelo="claude-opus-5-5", cliente=cli)
    assert [c["model"] for c in cli.criados] == ["claude-haiku-5-5", "claude-haiku-5-5"]
    monkeypatch.setenv("JFN_API_SONNET_TAREFAS", "triagem_alertas")
    A.pensar_api("triagem_alertas", "p3", cliente=cli)
    assert cli.criados[-1]["model"] == "claude-sonnet-5-5" and cli.criados[-1]["fallbacks"] == "default"


def test_parametros_cache_effort_e_formato():
    p = A.parametros("claude-haiku-5-5", "FIXO", "ITEM", 300, "low", {"type": "object"})
    assert p["system"] == [{"type": "text", "text": "FIXO", "cache_control": {"type": "ephemeral"}}]
    assert p["messages"][-1]["content"] == "ITEM"
    assert p["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}}


def test_teto_total_e_do_balde_e_reserva_bloqueada(monkeypatch):
    monkeypatch.setenv("JFN_API_TETO_USD", "5.01")          # limite efetivo 0,01
    assert A.pensar_api("triagem_alertas", "p", cliente=Cliente(entrada=1_000_000)) is None
    assert "teto total" in A.ultimo_motivo
    monkeypatch.setenv("JFN_API_TETO_USD", "100")
    A._mutar(lambda d: A._b(d, "triagem_alertas").__setitem__("usd", 9.9999))
    assert A.pensar_api("triagem_alertas", "p", cliente=Cliente()) is None and "balde" in A.ultimo_motivo
    assert A.pensar_api("tarefa_sem_balde", "p", cliente=Cliente()) is None and "reserva" in A.ultimo_motivo


def test_recusa_e_corte_nao_sao_resposta_mas_sao_cobrados():
    assert A.pensar_api("triagem_alertas", "a", cliente=Cliente(stop="refusal", categoria="cyber")) is None
    assert "recusa" in A.ultimo_motivo
    assert A.pensar_api("triagem_alertas", "b", cliente=Cliente(stop="max_tokens")) is None
    g = A.ler_gasto()
    assert g["total_usd"] > 0 and g["reservado_usd"] == 0 and g["chamadas"] == 0


def test_memoria_mesma_entrada_nao_paga_duas_vezes():
    cli = Cliente("resposta")
    assert A.pensar_api("triagem_alertas", "igual", cliente=cli)[0] == "resposta"
    assert A.pensar_api("triagem_alertas", "igual", cliente=cli) == ("resposta", "claude-haiku-5-5", 0.0)
    assert len(cli.criados) == 1


def test_pausa_bloqueia_ate_despausar():
    A.pausar("triagem_alertas", "qualidade caiu")
    assert A.pensar_api("triagem_alertas", "p", cliente=Cliente()) is None and "PAUSADA" in A.ultimo_motivo
    A.despausar("triagem_alertas")
    assert A.pensar_api("triagem_alertas", "p", cliente=Cliente()) is not None


def test_motor_cai_na_api_quando_assinatura_sem_cota(monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_MAX_PERICIA_EXECUCAO", "0")
    cli = Cliente('{"execucao_comprovada":"sim"}')
    duble_cli = lambda *a, **k: pytest.fail("não devia chamar o CLI")
    r = M.pensar("pericia_execucao", "p", executar=duble_cli, espera=0, api_cliente=cli)
    assert r.modelo == "claude-haiku-5-5@api" and r.extras["backend"] == "api"
    assert A.ler_gasto()["por_tarefa"]["pericia_execucao"]["chamadas"] == 1


def test_kill_switch_desliga_a_api_tambem(monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_MOTOR", "0")
    cli = Cliente()
    assert M.pensar("pericia_execucao", "p", executar=lambda *a, **k: None, api_cliente=cli) is None
    assert cli.criados == []


def test_projecao_por_balde_no_painel():
    A._liquidar("triagem_alertas", "claude-haiku-5-5", 0.0, 0.02, {"input_tokens": 1}, itens=200)
    A.registrar_restantes("triagem_alertas", 62000)
    b = A.painel()["baldes"]["triagem_alertas"]
    assert b["usd_por_item"] == pytest.approx(0.0001) and b["projecao_total_usd"] == pytest.approx(6.22)
    assert b["projecao_cabe"] is True


# ── verificação determinística ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cit,fonte,ok", [
    ("Valor global de R$ 1.234,56", "O contrato tem valor global de R$ 1.234,56 por ano.", True),
    ("valor  global de r$ 1.234,56", "O contrato tem Valor Global de R$ 1.234,56", True),
    ("valor inventado de R$ 9", "O contrato tem valor global de R$ 1.234,56", False),
    ("curto", "curto", False),
])
def test_citacao_existe(cit, fonte, ok):
    assert V.citacao_existe(cit, fonte) is ok


@pytest.mark.parametrize("valor,trecho,ok", [
    (1234.56, "total de R$ 1.234,56", True), ("1234,56", "R$ 1234.56", True), (1200, "R$ 1.200,00", True),
    (1200.0, "R$ 1200", True), (1235, "R$ 1.234,56", False), (None, "R$ 1", False),
])
def test_numero_no_trecho(valor, trecho, ok):
    assert V.numero_no_trecho(valor, trecho) is ok


def test_conferir_extracao_e_dupla_leitura():
    fonte = "Nota fiscal nº 42 no valor de R$ 10.500,00 emitida em 01/02/2026."
    assert V.conferir_extracao({"valor": 10500, "nf": 42}, "NF nº 42 no valor de R$ 10.500,00", fonte)[0] is False
    assert V.conferir_extracao({"valor": 10500.0}, "valor de R$ 10.500,00", fonte, ("valor",)) == (True, "")
    assert V.conferir_extracao({"valor": 9999}, "valor de R$ 10.500,00", fonte, ("valor",))[0] is False
    assert V.conferir_extracao({"valor": None}, "valor de R$ 10.500,00", fonte, ("valor",)) == (True, "")
    assert V.estado_dupla_leitura("a", "a") == "VERIFICADO" and V.estado_dupla_leitura("a", "b") == "PENDENTE"
    assert V.estado_dupla_leitura("a", None) == "PENDENTE" and V.estado_dupla_leitura(None, None) == "INDISPONIVEL"
