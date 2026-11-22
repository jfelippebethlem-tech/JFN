# -*- coding: utf-8 -*-
"""Só entra na leitura dupla o grátis que passou na bancada (dono, 20/11/2026: "grátis só entra na tarefa se
≥ Sonnet, ambos julgados pelo Opus, e zero erro grave; senão esquece").

Bancada de 20–21/11/2026 (100 processos, prompt/janela/parser de produção, conferência literal + Opus da assinatura,
comparação PAREADA nos 76–77 processos 100% adjudicados):
  particle-1:free  93,1% × Sonnet 88,6% (27 × 40 erros), 0 invenção decidida por código   → ENTRA (1º)
  qwen4-max:free   90,0% × Sonnet 88,0% (37 × 42 erros), 0 invenção decidida por código   → ENTRA (2º)
  cohere           81,4% × Sonnet 88,0% (66 × 42 erros)                                    → SAI da cadeia curta
Nemotron (as 4 `:free`) inventaram valor/dispositivo contra a fonte → fora.
"""
from __future__ import annotations

import inspect

import tools.sei_leitura_dupla as M
from compliance_agent.llm import free_llm as F


def test_aprovados_sao_so_os_da_bancada_e_todos_free():
    assert M._APROVADOS_LEITURA == (("openrouter", "particle-ai/particle-1:free"), ("nous", "qwen/qwen4-max:free"))
    assert all(m.endswith(":free") for _, m in M._APROVADOS_LEITURA)


def test_cohere_saiu_da_cadeia_curta():
    assert "cohere" not in M._GRATIS_LEITURA, "medido abaixo do Sonnet na bancada de 21/11"


def test_aprovados_vem_antes_da_reserva_de_hoje():
    fonte = inspect.getsource(M.extrair_interpretativo)
    assert fonte.index("_gerar_aprovados()") < fonte.index("_gerar_nous()") < fonte.index("_gerar_cadeia_curta()")


def test_encadear_usa_o_primeiro_que_responde_e_pula_vazio_e_none():
    chamados = []
    a = lambda p, s: chamados.append("a") or ""
    b = lambda p, s: chamados.append("b") or '{"ok": 1}'
    c = lambda p, s: chamados.append("c") or '{"nao": 1}'
    assert M._encadear(None, a, b, c)("p", "s") == '{"ok": 1}'
    assert chamados == ["a", "b"]


def test_encadear_engole_erro_de_um_e_segue(monkeypatch):
    def quebra(p, s):
        raise RuntimeError("429")
    assert M._encadear(quebra, lambda p, s: "x")("p", "s") == "x"


def test_openrouter_sem_chave_nao_monta_gerador(monkeypatch):
    monkeypatch.setattr(F, "openrouter_available", lambda: False)
    assert M._gerar_openrouter_free("particle-ai/particle-1:free") is None


def test_openrouter_recusa_modelo_que_nao_e_free(monkeypatch):
    monkeypatch.setattr(F, "openrouter_available", lambda: True)
    try:
        M._gerar_openrouter_free("particle-ai/particle-1")
    except ValueError:
        return
    raise AssertionError("modelo sem :free tem de ser recusado (§4.1)")


def test_openrouter_chama_o_modelo_pedido_e_devolve_o_conteudo(monkeypatch):
    import httpx
    enviados = []

    class R:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": '{"fatos": 1}'}, "finish_reason": "stop"}]}

    monkeypatch.setattr(F, "openrouter_available", lambda: True)
    monkeypatch.setattr(F, "_openrouter_key", lambda: "k")
    monkeypatch.setattr(F, "_trace", lambda *a, **k: None)
    monkeypatch.setattr(httpx, "post", lambda url, **k: enviados.append(k["json"]["model"]) or R())
    g = M._gerar_openrouter_free("particle-ai/particle-1:free")
    assert g("prompt", "sistema") == '{"fatos": 1}'
    assert enviados == ["particle-ai/particle-1:free"]
