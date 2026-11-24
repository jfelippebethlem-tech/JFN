# -*- coding: utf-8 -*-
"""Gateway LLM, O6.1 (a): uma linha de trace por tentativa, só hashes e tamanhos (nunca o texto), migração
idempotente da tabela que o free_llm já usa, custo pela tabela oficial e preço desconhecido = None (nunca 0).
Nenhum teste chama provedor: backends dublês e cliente Anthropic falso."""
import sqlite3
from types import SimpleNamespace

import pytest

from compliance_agent.adaptadores.llm import gateway as G

CPF = "123.456.789-00"   # DV inválido de propósito: formato de CPF, de ninguém


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(tmp_path / "trace.db"))
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "estado"))
    monkeypatch.setenv("JFN_ANTHROPIC_ENV", str(tmp_path / "sem_chave.env"))
    return tmp_path


def _linhas(tmp_path):
    con = sqlite3.connect(tmp_path / "trace.db")
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute("SELECT * FROM llm_trace WHERE origem='gateway' ORDER BY rowid")]


def _ok(texto="resposta", **kw):
    return lambda **_a: G.Retorno(texto=texto, **kw)


def _falha(**_a):
    raise RuntimeError("provedor caiu")


def test_grava_campos_e_nunca_o_texto(_isolado):
    r = G.chamar("classificacao", [{"role": "system", "content": "regras"},
                                   {"role": "user", "content": f"o sócio {CPF} assinou"}],
                 prompt_version="v7", classe_dado="publico", backends={"free_llm": _ok(f"achei {CPF}")})
    assert r.provedor == "free_llm" and r.camada == 1 and r.retry == 0 and r.custo_usd is None
    [ln] = _linhas(_isolado)
    assert ln["tarefa"] == "classificacao" and ln["prompt_version"] == "v7" and ln["ok"] == 1
    assert ln["input_hash"] == r.input_hash and len(ln["input_hash"]) == 64
    assert ln["output_hash"] == G._sha(f"achei {CPF}")
    assert ln["chars_in"] == len("regras") + len(f"o sócio {CPF} assinou") and ln["chars_out"] == len(f"achei {CPF}")
    assert ln["release_ia"] == "v7+free_llm" and ln["classe_dado"] == "publico" and ln["pago"] == 0
    assert ln["custo_usd"] is None                     # grátis sem prova ≠ 0
    bruto = (_isolado / "trace.db").read_bytes()
    assert CPF.encode() not in bruto and b"assinou" not in bruto and b"regras" not in bruto


def test_escalonamento_grava_retry_e_motivo(_isolado, monkeypatch):
    monkeypatch.setattr(G, "_pre_assinatura", lambda t: None)
    r = G.chamar("pericia_execucao", [{"role": "user", "content": "x"}], prompt_version="v1", classe_dado="publico",
                 backends={"assinatura_claude": _falha, "api_anthropic": _ok(
                     "ok", modelo="claude-haiku-5-5", tokens_in=1000, tokens_out=200, tokens_cache_lido=0,
                     tokens_cache_escrito=0)})
    assert r.camada == 3 and r.retry == 1 and "provedor caiu" in r.motivo_escalonamento
    a, b = _linhas(_isolado)
    assert (a["provedor"], a["ok"], a["retry"]) == ("assinatura_claude", 0, 0) and "RuntimeError" in a["erro"]
    assert (b["provedor"], b["ok"], b["retry"], b["pago"]) == ("api_anthropic", 1, 1, 1)
    assert "provedor caiu" in b["motivo_escalonamento"]
    assert b["custo_usd"] == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6) and b["custo_fonte"] == "tabela"
    assert b["release_ia"] == "v1+claude-haiku-5-5" and b["trace_id"] == a["trace_id"]


def test_migracao_idempotente_sem_perder_linha(_isolado):
    db = _isolado / "trace.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE llm_trace(ts TEXT DEFAULT (datetime('now')), provedor TEXT, ok INT, ms INT, erro TEXT)")
    con.execute("INSERT INTO llm_trace(provedor, ok, ms, erro) VALUES('groq', 1, 5, '')")
    con.commit()
    G.migrar(con)
    G.migrar(con)                                       # segunda vez não falha nem duplica
    cols = [r[1] for r in con.execute("PRAGMA table_info(llm_trace)")]
    assert len(cols) == len(set(cols))
    for c in ("prompt_version", "input_hash", "output_hash", "custo_usd", "retry", "motivo_escalonamento",
              "release_ia", "tokens_cache", "origem"):
        assert c in cols
    assert con.execute("SELECT provedor FROM llm_trace").fetchall() == [("groq",)]


def test_free_llm_trace_continua_gravando_na_tabela_ampliada(_isolado):
    from compliance_agent.llm import free_llm
    G.migrar(sqlite3.connect(_isolado / "trace.db"))
    free_llm._trace("gemini", True, 7, modelo="m")
    con = sqlite3.connect(_isolado / "trace.db")
    assert con.execute("SELECT provedor, origem FROM llm_trace").fetchall() == [("gemini", None)]


def test_preco_desconhecido_e_none_nunca_zero():
    tab = G.precos()
    assert G.custo_usd("modelo-que-nao-existe", 100, 100, tab=tab) is None
    assert G.custo_usd("claude-haiku-5-5", None, 100, tab=tab) is None
    assert G.custo_usd("claude-haiku-5-5", 0, 0, tab=tab) == 0.0


def test_precos_da_tabela_oficial():
    tab = G.precos()
    assert tab["fonte"]["url"].startswith("https://platform.claude.com/") and tab["fonte"]["conferido_em"]
    # Opus 5.5: cache lido a 0,05× (US$ 0,20); lote 50%
    assert G.custo_usd("claude-opus-5-5", 1_000_000, 0, 1_000_000, tab=tab) == pytest.approx(4.20)
    assert G.custo_usd("claude-sonnet-5-5", 1_000_000, 1_000_000, lote=True, tab=tab) == pytest.approx(6.0)
    # Haiku 5.5 acima de 100K tokens de prompt: faixa longa na requisição inteira
    assert G.custo_usd("claude-haiku-5-5", 100_001, 0, tab=tab) == pytest.approx(100_001 * 0.50 / 1e6)
    assert G.custo_usd("claude-haiku-5-5@api", 1_000_000, 0, tab=tab) == pytest.approx(0.50)


def _cliente_falso(usage, modelo="claude-haiku-5-5"):
    criados = []

    def create(**kw):
        criados.append(kw)
        return SimpleNamespace(model=modelo, usage=usage, stop_reason="end_turn",
                               content=[SimpleNamespace(type="text", text='{"ok": true}')])
    msgs = SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=50), create=create)
    return SimpleNamespace(messages=msgs, beta=SimpleNamespace(messages=msgs)), criados


def test_backend_api_captura_usage_sem_mudar_claude_api(_isolado):
    usage = {"input_tokens": 50, "output_tokens": 10, "cache_read_input_tokens": 7, "cache_creation_input_tokens": 3}
    cli, criados = _cliente_falso(usage)
    ret = G._backend_api(tarefa="leitura_integral", sistema="s", prompt="p", schema=None, modelo_pref=None,
                         max_tokens=100, timeout=5, cliente=cli)
    assert len(criados) == 1 and ret.texto == '{"ok": true}' and ret.modelo == "claude-haiku-5-5"
    assert (ret.tokens_in, ret.tokens_out, ret.tokens_cache_lido, ret.tokens_cache_escrito) == (50, 10, 7, 3)
    assert ret.usd_backend is not None and ret.usd_backend > 0 and not ret.memo
    # mesma entrada de novo: memória do claude_api, nenhuma chamada nova, custo 0 conhecido
    ret2 = G._backend_api(tarefa="leitura_integral", sistema="s", prompt="p", schema=None, modelo_pref=None,
                          max_tokens=100, timeout=5, cliente=cli)
    assert len(criados) == 1 and ret2.memo and ret2.usd_backend == 0.0


def test_backend_api_sob_pytest_sem_dubl_nao_chama():
    with pytest.raises(RuntimeError, match="pytest"):
        G._backend_api(tarefa="leitura_integral", sistema="", prompt="p", schema=None, modelo_pref=None,
                       max_tokens=10, timeout=5)


def test_schema_invalido_escala(_isolado, monkeypatch):
    monkeypatch.setattr(G, "_pre_assinatura", lambda t: None)
    sch = {"type": "object", "required": ["grau"], "properties": {"grau": {"type": "integer"}}}
    r = G.chamar("pericia_execucao", [{"role": "user", "content": "x"}], prompt_version="v1", classe_dado="publico",
                 schema=sch, backends={"assinatura_claude": _ok("sem json"),
                                       "api_anthropic": _ok('{"grau": 1}', modelo="claude-haiku-5-5",
                                                            tokens_in=10, tokens_out=5)})
    assert r.dados == {"grau": 1} and r.camada == 3 and "JSON" in r.motivo_escalonamento


def test_campos_obrigatorios():
    with pytest.raises(G.GatewayErro, match="prompt_version"):
        G.chamar("classificacao", [{"role": "user", "content": "x"}], prompt_version="", classe_dado="publico")
    with pytest.raises(G.GatewayErro, match="user"):
        G.chamar("classificacao", [{"role": "system", "content": "x"}], prompt_version="v1", classe_dado="publico")
