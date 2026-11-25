# -*- coding: utf-8 -*-
"""Decisões delegadas de 24/11/2026 (D1/D2): ASSINATURA PRIMEIRO e crédito PAGO só com autorização do dono.

Regra do dono: "priorizando SEMPRE usar a assinatura em tudo" e "créditos de API só quando eu autorizar" — vale para
toda camada paga, inclusive piloto pequeno; o teto de US$ 100 não autoriza gasto sozinho. Estes testes provam que
NENHUMA rota paga (gateway, claude_api direto e em lote, openrouter_pago) é chamada sem a autorização, e que com ela
o quem/quando/id vão ao trace. Nenhum teste gasta: backends e clientes são dublês."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from compliance_agent.adaptadores.llm import gateway as G
from compliance_agent.llm import autorizacao_paga as AP
from tests.autorizacao_paga_dubles import ID, autorizar, entrada

MSG = [{"role": "user", "content": "texto curto"}]


@pytest.fixture(autouse=True)
def _isolado(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(tmp_path / "trace.db"))
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "estado"))
    monkeypatch.setattr(G, "_pre_assinatura", lambda t: None)
    return tmp_path


def _dubles(falham=()):
    vistos = []

    def faz(nome):
        def b(**kw):
            vistos.append(nome)
            if nome in falham:
                raise RuntimeError(f"{nome} caiu")
            return G.Retorno(texto="ok", modelo="claude-haiku-5-5" if nome == "api_anthropic" else None,
                             tokens_in=10, tokens_out=5)
        return b
    return vistos, {n: faz(n) for n in ("free_llm", "assinatura_claude", "api_anthropic", "cascata_dc")}


def _pol(tmp_path, monkeypatch, **tarefas) -> dict:
    pol = yaml.safe_load(G._caminho_politica().read_text(encoding="utf-8"))
    pol["tarefas"].update(tarefas)
    p = tmp_path / "pol.yaml"
    p.write_text(yaml.safe_dump(pol, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("JFN_LLM_POLITICA", str(p))
    return pol


def _trace(tmp_path):
    con = sqlite3.connect(tmp_path / "trace.db")
    try:
        return con.execute("SELECT provedor, ok, erro, autorizacao, autorizacao_quem, autorizacao_quando FROM llm_trace "
                           "WHERE origem='gateway' ORDER BY rowid").fetchall()
    finally:
        con.close()


# ── 1. assinatura primeiro, paga por último ─────────────────────────────────────────────────────────────────
def test_paga_escrita_na_frente_vai_para_o_fim_e_assinatura_para_o_inicio(_isolado, monkeypatch):
    _pol(_isolado, monkeypatch, invertida={"camadas": [3, 4, 1, 2], "critica": False})
    autorizar(_isolado, monkeypatch, tarefas=["invertida"])
    vistos, bk = _dubles(falham=("assinatura_claude", "cascata_dc", "free_llm"))
    r = G.chamar("invertida", MSG, prompt_version="v1", classe_dado="publico", backends=bk)
    assert vistos == ["assinatura_claude", "cascata_dc", "free_llm", "api_anthropic"]
    assert r.provedor == "api_anthropic" and r.camada == 3


def test_ordem_pura():
    pol = G.politica()
    assert G.ordem_assinatura_primeiro([(3, "api_anthropic"), (1, "free_llm"), (2, "assinatura_claude"),
                                        (4, "cascata_dc")], pol) == \
        [(2, "assinatura_claude"), (1, "free_llm"), (4, "cascata_dc"), (3, "api_anthropic")]


def test_provedor_sem_marca_de_pago_conta_como_pago():
    pol = {"provedores": {"x": {"data_policy": "conhecida"}, "y": {"pago": False}, "z": {"pago": True}}}
    assert G.provedor_pago("x", pol) and not G.provedor_pago("y", pol) and G.provedor_pago("z", pol)
    assert G.provedor_pago("fora_da_politica", pol)


def test_politica_real_toda_tarefa_com_paga_tem_a_assinatura():
    pol = G.politica()
    for nome, t in pol["tarefas"].items():
        pagas = [c for c in t["camadas"] if G.provedor_pago(pol["camadas"][c]["provedor"], pol)]
        if pagas:
            assert 2 in t["camadas"], nome
    assert pol["tarefas"]["normalizacao_itens"]["camadas"][0] == 2


# ── 2. sem autorização do dono, nenhuma rota paga é chamada ─────────────────────────────────────────────────
def test_sem_autorizacao_a_api_nunca_e_chamada_e_o_item_fica_nao_julgado(_isolado):
    vistos, bk = _dubles(falham=("assinatura_claude",))
    with pytest.raises(G.PagaNaoAutorizada, match="API paga não autorizada pelo dono") as e:
        G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="interno", backends=bk)
    assert isinstance(e.value, G.SemProvedor) and "NÃO JULGADO" in str(e.value)
    assert vistos == ["assinatura_claude"]                  # a API dublê nunca foi chamada
    linhas = _trace(_isolado)
    assert ("api_anthropic", 0, "recusado: API paga não autorizada pelo dono", None, None, None) in linhas


def test_so_camada_paga_e_teto_folgado_nao_autoriza_sozinho(_isolado):
    vistos, bk = _dubles()
    assert G.gasto_mes_usd() == 0.0                         # US$ 0 de US$ 100: o teto não é autorização
    with pytest.raises(G.PagaNaoAutorizada):
        G.chamar("normalizacao_itens", MSG, prompt_version="v1", classe_dado="publico", so_camadas=(3,), backends=bk)
    assert vistos == []


@pytest.mark.parametrize("caso", ["sem_id", "id_inexistente", "vencida", "futura", "outra_tarefa", "outro_provedor",
                                  "incompleta", "sem_fuso", "repetida", "teto_zero", "livro_ilegivel"])
def test_autorizacao_invalida_recusa(caso, _isolado, monkeypatch):
    agora = datetime.now(timezone.utc)
    e = entrada(tarefas=["pericia_execucao"])
    lst = [e]
    if caso == "vencida":
        e["ate"] = (agora - timedelta(minutes=1)).isoformat()
    elif caso == "futura":
        e["quando"] = (agora + timedelta(hours=1)).isoformat()
        e["ate"] = (agora + timedelta(hours=2)).isoformat()
    elif caso == "outra_tarefa":
        e["tarefas"] = ["leitura_integral"]
    elif caso == "outro_provedor":
        e["provedores"] = ["openrouter_pago"]
    elif caso == "incompleta":
        e.pop("registro")
    elif caso == "sem_fuso":
        e["quando"] = "2026-11-24T10:00:00"
    elif caso == "repetida":
        lst = [e, dict(e)]
    elif caso == "teto_zero":
        e["teto_usd"] = 0
    p = _isolado / "aut.yaml"
    p.write_text("autorizacoes: [" if caso == "livro_ilegivel" else
                 yaml.safe_dump({"autorizacoes": lst}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("JFN_LLM_AUTORIZACOES", str(p))
    if caso != "sem_id":
        monkeypatch.setenv("JFN_LLM_AUTORIZACAO_PAGA", "AUT-OUTRA" if caso == "id_inexistente" else ID)
    vistos, bk = _dubles(falham=("assinatura_claude",))
    with pytest.raises(G.PagaNaoAutorizada):
        G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="interno", backends=bk)
    assert "api_anthropic" not in vistos


def test_com_autorizacao_valida_chama_e_registra_quem_e_quando(_isolado, monkeypatch):
    e = autorizar(_isolado, monkeypatch, tarefas=["pericia_execucao"])
    vistos, bk = _dubles(falham=("assinatura_claude",))
    r = G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="interno", backends=bk)
    assert r.provedor == "api_anthropic" and vistos == ["assinatura_claude", "api_anthropic"]
    ult = _trace(_isolado)[-1]
    assert ult[:4] == ("api_anthropic", 1, None, ID) and ult[4] == e["quem"]
    assert datetime.fromisoformat(ult[5]) == datetime.fromisoformat(e["quando"])
    assert _trace(_isolado)[0][3] is None                   # a linha da assinatura não leva a autorização


def test_autorizacao_por_chamada_sem_ambiente(_isolado, monkeypatch):
    autorizar(_isolado, monkeypatch, tarefas=["pericia_execucao"], definir_id=False)
    vistos, bk = _dubles(falham=("assinatura_claude",))
    with pytest.raises(G.PagaNaoAutorizada):
        G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="interno", backends=bk)
    r = G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="interno", backends=bk,
                 autorizacao_paga=ID)
    assert r.provedor == "api_anthropic"


def test_teto_da_autorizacao_soma_o_trace_do_id(_isolado, monkeypatch):
    autorizar(_isolado, monkeypatch, tarefas=["pericia_execucao"], teto_usd=0.50)
    con = sqlite3.connect(_isolado / "trace.db")
    G.migrar(con)
    con.execute("INSERT INTO llm_trace(origem, provedor, ok, ms, pago, custo_usd, autorizacao) "
                "VALUES('gateway', 'api_anthropic', 1, 1, 1, 0.4999, ?)", (ID,))
    con.commit()
    con.close()
    vistos, bk = _dubles(falham=("assinatura_claude",))
    with pytest.raises(G.SemProvedor, match="teto da autorização"):
        G.chamar("pericia_execucao", MSG, prompt_version="v1", classe_dado="interno", backends=bk)
    assert "api_anthropic" not in vistos


# ── 3. as portas pagas fora do gateway também exigem a autorização ──────────────────────────────────────────
class _Explode:
    def __getattr__(self, nome):
        raise AssertionError("cliente pago criado sem autorização")


def test_claude_api_direto_e_lote_recusam_sem_autorizacao(monkeypatch):
    from compliance_agent.llm import arquivo_estado as arq
    from compliance_agent.llm import claude_api as A
    monkeypatch.setattr(arq, "sob_pytest", lambda: False)
    monkeypatch.setattr(A, "disponivel", lambda: True)
    monkeypatch.setattr(A, "_cliente", lambda *a, **k: _Explode())
    assert A.pensar_api("triagem_alertas", "p") is None and AP.RECUSA in A.ultimo_motivo
    assert A.enviar_lote("triagem_alertas", [("1", "p")]) is None and AP.RECUSA in A.ultimo_motivo


def test_claude_api_com_autorizacao_passa_da_porta(tmp_path, monkeypatch):
    from compliance_agent.llm import claude_api as A
    autorizar(tmp_path, monkeypatch, tarefas=["triagem_alertas"])
    assert A._sem_autorizacao("triagem_alertas") is None
    assert AP.RECUSA in A._sem_autorizacao("camada_subjetiva")


def test_openrouter_pago_exige_autorizacao(tmp_path, monkeypatch):
    from compliance_agent.llm import openrouter_pago as OP
    env = tmp_path / "pago.env"
    env.write_text("OPENROUTER_PAGO_API_KEY=sk-or-teste-nao-real\n")
    monkeypatch.setenv("JFN_OR_PAGO_ENV", str(env))
    monkeypatch.delenv("JFN_FICHA_OR_PAGO", raising=False)
    ok, motivo = OP.ligado()
    assert not ok and motivo.startswith(AP.RECUSA)
    assert OP.chamar("qwen/qwen3.7-flash", "s", "p") == ""     # sem rede: httpx nem é chamado (ligado() barra)
    autorizar(tmp_path, monkeypatch, tarefas=[OP.TAREFA], provedores=["openrouter_pago"])
    assert OP.ligado() == (True, "")


def test_subprocesso_da_assinatura_nunca_leva_chave_nem_nuvem(monkeypatch):
    from compliance_agent.llm import claude_motor as CM
    for v in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
              "CLAUDE_CODE_USE_FOUNDRY"):
        monkeypatch.setenv(v, "x")
        assert v in CM.VARIAVEIS_PROIBIDAS and v not in CM.ambiente_limpo()
