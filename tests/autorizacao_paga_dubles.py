# -*- coding: utf-8 -*-
"""Dublê da autorização do dono para camada paga (regra de 24/11/2026). Os testes que exercitam a API paga COM
dublê de backend precisam dizer que o dono autorizou — um livro temporário com uma entrada válida e o id no
ambiente. Nenhum teste toca o livro real (`config/llm_autorizacoes_pagas.yaml`)."""
from datetime import datetime, timedelta, timezone

import yaml

ID = "AUT-TESTE-01"


def entrada(**kw) -> dict:
    agora = datetime.now(timezone.utc)
    base = {"id": ID, "quem": "dono (dublê de teste)", "quando": (agora - timedelta(hours=1)).isoformat(),
            "ate": (agora + timedelta(hours=1)).isoformat(), "registro": "teste", "tarefas": [],
            "provedores": ["api_anthropic"], "teto_usd": 1000.0, "motivo": "teste"}
    return {**base, **kw}


def autorizar(tmp_path, monkeypatch, *, tarefas=None, provedores=("api_anthropic",), definir_id: bool = True,
              **kw) -> dict:
    """Grava o livro temporário e (por padrão) põe o id no ambiente. `tarefas=None` ⇒ todas as da política real."""
    if tarefas is None:
        from compliance_agent.adaptadores.llm import gateway as G
        pol = yaml.safe_load(G._caminho_politica().read_text(encoding="utf-8"))
        tarefas = sorted(pol["tarefas"]) + ["tarefa_que_nao_existe"]
    e = entrada(tarefas=list(tarefas), provedores=list(provedores), **kw)
    p = tmp_path / "autorizacoes.yaml"
    p.write_text(yaml.safe_dump({"autorizacoes": [e]}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("JFN_LLM_AUTORIZACOES", str(p))
    if definir_id:
        monkeypatch.setenv("JFN_LLM_AUTORIZACAO_PAGA", e["id"])
    return e
