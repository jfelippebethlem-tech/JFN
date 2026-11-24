# -*- coding: utf-8 -*-
"""Gateway LLM, O6.1 (b): roteamento pela política (camadas 0..3), classe de dado com recusa EXPLÍCITA e circuit
breaker por provedor. Backends dublês; nenhuma chamada real."""
import sqlite3
import time

import pytest
import yaml

from compliance_agent.adaptadores.llm import gateway as G

MSG = [{"role": "user", "content": "texto"}]


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(tmp_path / "trace.db"))
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "estado"))
    monkeypatch.setattr(G, "_pre_assinatura", lambda t: None)
    return tmp_path


def _pol_real() -> dict:
    return yaml.safe_load(G._caminho_politica().read_text(encoding="utf-8"))


def _usar(tmp_path, monkeypatch, pol: dict) -> dict:
    p = tmp_path / "pol.yaml"
    p.write_text(yaml.safe_dump(pol, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("JFN_LLM_POLITICA", str(p))
    return pol


def _dubles():
    vistos = []

    def faz(nome, falha=False):
        def b(**kw):
            vistos.append(nome)
            if falha:
                raise RuntimeError(f"{nome} caiu")
            return G.Retorno(texto="ok", modelo="claude-haiku-5-5" if nome == "api_anthropic" else None,
                             tokens_in=10, tokens_out=5)
        return b
    return vistos, faz


def test_politica_real_e_consistente():
    pol = G.politica()
    assert set(pol["classes_dado"]) == set(G.CLASSES)
    for nome, t in pol["tarefas"].items():
        for c in t["camadas"]:
            assert c in pol["camadas"], (nome, c)
    assert pol["orcamento_mensal"] == {"teto_usd": 100.0, "corte_fracao": 0.85}
    # Opus de juízo/conferência nunca pela API paga (decisão do dono de 13/11/2026)
    for t in ("verificacao_opus", "conferencia_opus", "juiz_qualidade", "pericia_integral", "canario"):
        assert 3 not in pol["tarefas"][t]["camadas"]
    assert pol["padrao"]["camadas"] == [1]       # tarefa desconhecida nunca cai no pago
    # sem ✅ do dono registrado, nenhum provedor recebe dado pessoal
    assert not any(p.get("aprovada_dono") for p in pol["provedores"].values())


def test_tarefa_desconhecida_usa_o_padrao_gratis():
    vistos, faz = _dubles()
    r = G.chamar("tarefa_que_nao_existe", MSG, prompt_version="v1", classe_dado="publico",
                 backends={"free_llm": faz("free_llm"), "api_anthropic": faz("api_anthropic")})
    assert r.provedor == "free_llm" and r.camada == 1 and vistos == ["free_llm"]


def test_ordem_das_camadas():
    vistos, faz = _dubles()
    r = G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="publico",
                 backends={"assinatura_claude": faz("assinatura_claude"), "api_anthropic": faz("api_anthropic")})
    assert r.provedor == "assinatura_claude" and vistos == ["assinatura_claude"]


def test_camada_zero_recusa(_isolado, monkeypatch):
    pol = _pol_real()
    pol["tarefas"]["regra_fixa"] = {"camadas": [0], "critica": False}
    _usar(_isolado, monkeypatch, pol)
    with pytest.raises(G.TarefaDeterministica, match="camada 0"):
        G.chamar("regra_fixa", MSG, prompt_version="v1", classe_dado="publico")


@pytest.mark.parametrize("classe", ["pessoal", "restrito"])
def test_pessoal_sem_aprovacao_recusa_em_todo_provedor(_isolado, classe):
    vistos, faz = _dubles()
    with pytest.raises(G.ClasseDadoRecusada, match="✅"):
        G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado=classe,
                 backends={"assinatura_claude": faz("assinatura_claude"), "api_anthropic": faz("api_anthropic")})
    assert vistos == []                                  # nada saiu da máquina
    con = sqlite3.connect(_isolado / "trace.db")
    assert con.execute("SELECT ok, erro FROM llm_trace WHERE origem='gateway'").fetchall() == \
        [(0, "recusado: classe de dado")]


def test_pessoal_so_vai_ao_provedor_aprovado(_isolado, monkeypatch):
    pol = _pol_real()
    pol["provedores"]["assinatura_claude"]["aprovada_dono"] = True
    _usar(_isolado, monkeypatch, pol)
    vistos, faz = _dubles()
    r = G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="pessoal",
                 backends={"assinatura_claude": faz("assinatura_claude"), "api_anthropic": faz("api_anthropic")})
    assert r.provedor == "assinatura_claude"
    # assinatura caiu: a API (sem ✅) NÃO é tentada — dado pessoal não escala para provedor não aprovado
    vistos.clear()
    with pytest.raises(G.SemProvedor) as e:
        G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="pessoal",
                 backends={"assinatura_claude": faz("assinatura_claude", falha=True),
                           "api_anthropic": faz("api_anthropic")})
    assert vistos == ["assinatura_claude"] and any("api_anthropic" in m and "✅" in m for m in e.value.motivos)


def test_interno_nao_vai_a_politica_desconhecida():
    vistos, faz = _dubles()
    with pytest.raises(G.ClasseDadoRecusada, match="desconhecida"):
        G.chamar("classificacao", MSG, prompt_version="v1", classe_dado="interno",
                 backends={"free_llm": faz("free_llm")})
    assert vistos == []


def test_segredo_e_classe_invalida_sempre_recusam():
    with pytest.raises(G.ClasseDadoRecusada, match="nunca"):
        G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="segredo")
    with pytest.raises(G.ClasseDadoRecusada, match="inválida"):
        G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="confidencial")


def test_circuit_breaker_abre_pula_e_fecha(_isolado, monkeypatch):
    pol = _pol_real()
    pol["circuito"] = {"falhas": 2, "janela_s": 60, "aberto_s": 120}
    _usar(_isolado, monkeypatch, pol)
    vistos, faz = _dubles()
    bk = {"assinatura_claude": faz("assinatura_claude", falha=True), "api_anthropic": faz("api_anthropic")}
    for _ in range(2):
        G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="publico", backends=bk)
    assert vistos == ["assinatura_claude", "api_anthropic"] * 2
    assert G.circuito_aberto("assinatura_claude", pol)
    vistos.clear()
    r = G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="publico", backends=bk)
    assert vistos == ["api_anthropic"] and "circuito aberto" in r.motivo_escalonamento
    assert G.circuito_aberto("assinatura_claude", pol, agora=time.time() + 121) is None


def test_falhas_fora_da_janela_nao_abrem(_isolado, monkeypatch):
    pol = {"circuito": {"falhas": 2, "janela_s": 10, "aberto_s": 120}}
    G.registrar_falha("free_llm", pol, agora=1000.0)
    G.registrar_falha("free_llm", pol, agora=1020.0)
    assert G.circuito_aberto("free_llm", pol, agora=1021.0) is None
    G.registrar_falha("free_llm", pol, agora=1025.0)
    assert G.circuito_aberto("free_llm", pol, agora=1026.0)


def test_sucesso_zera_o_contador(_isolado):
    pol = {"circuito": {"falhas": 2, "janela_s": 60, "aberto_s": 120}}
    G.registrar_falha("free_llm", pol, agora=1000.0)
    G.registrar_sucesso("free_llm")
    G.registrar_falha("free_llm", pol, agora=1001.0)
    assert G.circuito_aberto("free_llm", pol, agora=1002.0) is None


def test_todas_falham_sem_provedor_com_motivos():
    vistos, faz = _dubles()
    with pytest.raises(G.SemProvedor) as e:
        G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="publico",
                 backends={"assinatura_claude": faz("assinatura_claude", falha=True),
                           "api_anthropic": faz("api_anthropic", falha=True)})
    # 24/11/2026: pericia_execucao ganhou a camada 4 (cascata_dc); sob pytest o backend real dela NÃO TENTA (pulada,
    # sem contar falha no circuito) — o motivo aparece, explícito
    assert len(e.value.motivos) == 3 and "assinatura_claude caiu" in str(e.value)
    assert e.value.motivos[2] == "cascata_dc: não tentou — cascata: sob pytest sem dublê"


def test_assinatura_desligada_e_pulada_sem_tentar(monkeypatch):
    monkeypatch.setattr(G, "_pre_assinatura", lambda t: "pausado (.pause_claude_motor)")
    vistos, faz = _dubles()
    monkeypatch.setitem(G.BACKENDS, "assinatura_claude", faz("assinatura_claude"))
    r = G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="publico",
                 backends={"api_anthropic": faz("api_anthropic")})
    assert vistos == ["api_anthropic"] and "pausado" in r.motivo_escalonamento
