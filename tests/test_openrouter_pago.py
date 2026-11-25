# -*- coding: utf-8 -*-
"""Porta PAGA do OpenRouter (22/11/2026) — pedido do dono: usar a conta até restarem US$ 10; depois só `:free`.

Travas que estes testes seguram (§4.1 — nunca assumir free tier, guard-rail real), sem rede (httpx mockado):
piso de saldo da conta bloqueia; limite da chave bloqueia; kill-switch; teto do dia; livro ilegível = falha fechada;
rede fora = não gasta; porta paga recusa `:free`; a guarda `:free` do free_llm continua intacta; gasto vai ao trace."""
import json
import sqlite3

import httpx
import pytest

from compliance_agent.llm import free_llm as F
from compliance_agent.llm import openrouter_pago as OP
from tests.autorizacao_paga_dubles import autorizar


class _R:
    def __init__(self, status, dados):
        self.status_code, self._d = status, dados

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("x", request=None, response=None)


@pytest.fixture
def pago(monkeypatch, tmp_path):
    env = tmp_path / "pago.env"
    env.write_text("# comentário\nOPENROUTER_PAGO_API_KEY=sk-or-teste-nao-real\nOPENROUTER_PAGO_PISO_CONTA_USD=10\n")
    monkeypatch.setenv("JFN_OR_PAGO_ENV", str(env))
    monkeypatch.setenv("JFN_OR_PAGO_GASTO", str(tmp_path / "gasto.json"))
    monkeypatch.delenv("JFN_FICHA_OR_PAGO", raising=False)
    monkeypatch.delenv("JFN_FICHA_OR_PAGO_TETO_DIA_USD", raising=False)
    # 24/11/2026: a porta paga só liga com autorização do dono — aqui, num livro temporário
    autorizar(tmp_path, monkeypatch, tarefas=[OP.TAREFA], provedores=["openrouter_pago"])
    estado = {"conta": (50.0, 4.89), "restante": 35.0, "gets": 0, "posts": []}

    def get(url, headers=None, timeout=None):
        estado["gets"] += 1
        assert headers["Authorization"] == "Bearer sk-or-teste-nao-real"
        if url.endswith("/credits"):
            return _R(200, {"data": {"total_credits": estado["conta"][0], "total_usage": estado["conta"][1]}})
        return _R(200, {"data": {"limit": 35, "limit_remaining": estado["restante"]}})

    def post(url, headers=None, json=None, timeout=None):
        estado["posts"].append(json)
        return _R(200, {"choices": [{"message": {"content": '{"objeto": "x"}'}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 12000, "completion_tokens": 3000, "cost": 0.0021}})
    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", post)
    return estado


def test_saldo_folgado_libera(pago):
    assert OP.liberar(0.25) == (True, "")


def test_piso_da_conta_bloqueia(pago):
    pago["conta"] = (50.0, 39.9)                       # sobram US$ 10,10: o lote de US$ 0,25 furaria o piso
    ok, motivo = OP.liberar(0.25)
    assert not ok and "piso da conta" in motivo


def test_limite_da_chave_bloqueia(pago):
    pago["restante"] = 0.1
    ok, motivo = OP.liberar(0.25)
    assert not ok and "limite da chave" in motivo


def test_kill_switch_nao_consulta_nem_chama(pago, monkeypatch):
    monkeypatch.setenv("JFN_FICHA_OR_PAGO", "0")
    assert OP.liberar(0.01)[0] is False
    assert OP.chamar("qwen/qwen3.7-flash", "s", "p") == ""
    assert pago["gets"] == 0 and pago["posts"] == []


def test_sem_chave_paga_nao_liga(pago, monkeypatch, tmp_path):
    monkeypatch.setenv("JFN_OR_PAGO_ENV", str(tmp_path / "nao_existe.env"))
    assert OP.liberar(0.01) == (False, "sem chave paga")


def test_rede_fora_nao_gasta(pago, monkeypatch):
    def cai(*a, **k):
        raise httpx.ConnectError("sem rede")
    monkeypatch.setattr(httpx, "get", cai)
    ok, motivo = OP.liberar(0.01)
    assert not ok and "saldo indisponível" in motivo


def test_teto_do_dia_e_livro_ilegivel(pago, monkeypatch, tmp_path):
    monkeypatch.setenv("JFN_FICHA_OR_PAGO_TETO_DIA_USD", "0.003")
    assert OP.chamar("qwen/qwen3.7-flash", "s", "p") == '{"objeto": "x"}'     # gasta US$ 0,0021
    ok, motivo = OP.liberar(0.002)
    assert not ok and "teto do dia" in motivo
    monkeypatch.setenv("JFN_FICHA_OR_PAGO_TETO_DIA_USD", "0.002")
    assert OP.chamar("qwen/qwen3.7-flash", "s", "p") == ""                    # já passou: nem chama
    assert len(pago["posts"]) == 1
    (tmp_path / "gasto.json").write_text("{corrompido")
    ok, motivo = OP.liberar(0.001)
    assert not ok and "ilegível" in motivo


def test_chamada_registra_gasto_no_livro_e_no_trace(pago, tmp_path):
    assert OP.chamar("qwen/qwen3.7-flash", "s", "p")
    assert pago["posts"][0]["model"] == "qwen/qwen3.7-flash"                  # o modelo PAGO, sem `:free` forçado
    assert OP.gasto_hoje() == pytest.approx(0.0021)
    import os
    con = sqlite3.connect(os.environ["JFN_LLM_TRACE_DB"])
    linha = con.execute("SELECT provedor, ok, modelo, tokens_in, tokens_out, usd FROM llm_trace").fetchone()
    assert linha == ("openrouter_pago", 1, "qwen/qwen3.7-flash", 12000, 3000, pytest.approx(0.0021))
    e = OP.estado()
    assert e["ligado"] and e["gasto_hoje_usd"] == pytest.approx(0.0021) and e["conta_usd"] == pytest.approx(45.11)
    assert "sk-or" not in json.dumps(e)                                     # a chave nunca sai no estado


def test_porta_paga_recusa_modelo_gratis(pago):
    for m in ("particle-ai/particle-1:free", "openrouter/free"):
        with pytest.raises(ValueError):
            OP.chamar(m, "s", "p")
    assert pago["posts"] == []


def test_guarda_free_do_free_llm_intacta(monkeypatch):
    """O caminho grátis continua forçando `:free` — a porta paga não abriu brecha nele — e a chave paga, mesmo no
    ambiente, nunca entra no pool de chaves grátis."""
    _, carga = F._requisicao(F.OPENROUTER_BASE, "k", "qwen/qwen3.7-flash", [{"role": "user", "content": "x"}], 10, None)
    assert carga["model"] == "qwen/qwen3.7-flash:free"
    monkeypatch.setenv("OPENROUTER_PAGO_API_KEY", "sk-or-paga-teste")
    assert "sk-or-paga-teste" not in F._openrouter_chaves()
