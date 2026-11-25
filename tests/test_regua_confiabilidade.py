# -*- coding: utf-8 -*-
"""O6.6 — régua de confiabilidade por par tarefa × modelo × prompt_version × release_ia (plano mestre v2 §3.10).
Carregador/validador de config/regras_novas.yaml, critérios (a)–(d) recalculados, rótulo "NÃO JULGADO — proposta de
<modelo>" e a checagem no gateway e no E11. Nenhuma chamada a LLM: backends dublês, YAML em tmp_path."""
import copy
import json

import pytest
import yaml

from compliance_agent.qualidade import regua as RG

EVID_OK = {"ouro": {"n": 125, "graves": 0, "sha256": "ab" * 32, "estratificado": True,
                    "estratos": {"processo": 125, "orgao": 18, "periodo": 4}},
           "sombra": {"dias": 14, "n": 31, "graves": 0},
           "portoes": {p: True for p in RG.PORTOES}}


def _par(**kw):
    p = {"id": "R-X", "tarefa": "pericia_execucao", "modelo": "claude-sonnet-5-5", "prompt_version": "v1",
         "release_ia": "v1+claude-sonnet-5-5", "estado": RG.APROVADO_DONO, "dono": "dono", "data": "2026-11-24",
         "motivo": "teste", "evidencia": copy.deepcopy(EVID_OK)}
    p.update(kw)
    return p


def _doc(*pares, propostas=()):
    return {"criterios": dict(RG.CRITERIOS), "pares": list(pares), "propostas": list(propostas)}


def _grava(tmp_path, doc):
    arq = tmp_path / "regras_novas.yaml"
    arq.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    return arq


@pytest.fixture(autouse=True)
def _limpa_cache():
    RG._CACHE.clear()
    yield
    RG._CACHE.clear()


# ── (b) Wilson: 125 é o 1º n que passa com 0 grave ─────────────────────────────────────────────────────────────
def test_wilson_125_e_o_primeiro_n_que_passa_com_zero_grave():
    assert RG.wilson_sup(0, 125) <= 0.03 < RG.wilson_sup(0, 124)
    assert RG.wilson_sup(1, 125) > 0.03                      # 1 grave reprova (a) e (b) no mesmo n
    assert RG.wilson_sup(0, 0) is None


def test_criterios_completos_e_cada_falta_isolada():
    c = RG.criterios(EVID_OK)
    assert (c["a"], c["b"], c["c"], c["d"]) == (True, True, True, True) and c["falta"] == []
    casos = {"a": lambda e: e["ouro"].update(sha256=None), "b": lambda e: e["ouro"].update(n=124),
             "c": lambda e: e["sombra"].update(dias=13, n=29), "d": lambda e: e["portoes"].update(numero_fonte=None)}
    for crit, muda in casos.items():
        e = copy.deepcopy(EVID_OK)
        muda(e)
        assert RG.criterios(e)[crit] is False, crit
    e = copy.deepcopy(EVID_OK)
    e["ouro"]["estratos"].pop("orgao")
    assert RG.criterios(e)["a"] is False                      # estratificado sem órgão não vale
    e = copy.deepcopy(EVID_OK)
    e["sombra"]["graves"] = 1
    assert RG.criterios(e)["c"] is False and "sombra com 1 grave(s)" in RG.criterios(e)["falta"]


def test_sombra_por_n_novo_dispensa_os_14_dias():
    e = copy.deepcopy(EVID_OK)
    e["sombra"] = {"dias": 3, "n": 30, "graves": 0}
    assert RG.criterios(e)["c"] is True


# ── validador ─────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("muda,trecho", [
    (lambda p: p.update(dono=None), "exige `dono`"),
    (lambda p: p.update(release_ia="*"), "exatos"),
    (lambda p: p["evidencia"]["ouro"].update(graves=1), "sem a régua cumprida"),
    (lambda p: p.update(estado="JULGADO"), "fora de"),
    (lambda p: p.pop("motivo"), "falta `motivo`"),
    (lambda p: p.pop("dono"), "falta `dono`"),
    (lambda p: p.update(data="24/11/2026"), "data inválida"),
])
def test_validador_recusa_aprovacao_sem_base(muda, trecho):
    p = _par()
    muda(p)
    with pytest.raises(RG.ErroRegua, match=trecho):
        RG.validar(_doc(p))


def test_em_sombra_exige_a_b_d_e_rebaixado_exige_quem():
    p = _par(estado=RG.EM_SOMBRA, dono=None)
    p["evidencia"]["sombra"] = {"dias": 2, "n": 4, "graves": 0}          # (c) ainda correndo: ok em sombra
    RG.validar(_doc(p))
    p["evidencia"]["ouro"]["n"] = 50
    with pytest.raises(RG.ErroRegua, match="EM_SOMBRA exige"):
        RG.validar(_doc(p))
    with pytest.raises(RG.ErroRegua, match="exige `dono`"):
        RG.validar(_doc(_par(estado=RG.REBAIXADO, dono=None)))


def test_validador_recusa_criterio_divergente_par_repetido_e_proposta_sem_dono():
    d = _doc(_par())
    d["criterios"]["ouro_n_min"] = 100
    with pytest.raises(RG.ErroRegua, match="divergem"):
        RG.validar(d)
    with pytest.raises(RG.ErroRegua, match="repetido"):
        RG.validar(_doc(_par(), _par(id="R-Y")))
    prop = {"id": "P1", "titulo": "t", "data": "2026-11-24", "motivo": "m", "evidencia": {"x": 1},
            "decisao": "aprovada", "dono": None}
    with pytest.raises(RG.ErroRegua, match="sem `dono`"):
        RG.validar(_doc(propostas=[prop]))
    with pytest.raises(RG.ErroRegua, match="ids repetidos"):
        RG.validar(_doc(_par(id="P1"), propostas=[dict(prop, decisao="pendente")]))


def test_config_real_carrega_e_nada_esta_aprovado_sem_o_dono():
    """Catraca: o arquivo versionado valida, todo par tem dono/data/motivo/evidência e nenhum está APROVADO_DONO
    sem dono (hoje nenhum par cumpre (a): não há ouro congelado de juízo)."""
    d = RG.carregar(RG._REPO / "config" / "regras_novas.yaml")
    assert d["pares"] and d["propostas"]
    for p in d["pares"]:
        assert p["estado"] in RG.ESTADOS and p["motivo"] and p["evidencia"] and "dono" in p
        if p["estado"] == RG.APROVADO_DONO:
            assert p["dono"] and all(p["_criterios"][k] for k in "abcd")
    assert {r["id"] for r in d["propostas"]} >= {"O66-P1", "O66-P2", "O66-P3"}


# ── checagem / rótulo ─────────────────────────────────────────────────────────────────────────────────────────
def test_sem_par_registrado_e_nao_julgado_com_o_modelo():
    r = RG.checar("tarefa_inexistente", "gemini:gemini-3.6-flash#lote", "v1", "x")
    assert r["julgado"] is False and r["rotulo"] == "NÃO JULGADO — proposta de gemini:gemini-3.6-flash"


def test_aprovado_exato_e_julgado_e_outra_versao_nao(tmp_path):
    arq = _grava(tmp_path, _doc(_par()))
    ok = RG.checar("pericia_execucao", "claude-sonnet-5-5", "v1", "v1+claude-sonnet-5-5", arq=arq)
    assert ok["julgado"] and ok["rotulo"] == "JULGADO — claude-sonnet-5-5 (régua R-X)" and ok["estado"] == RG.APROVADO_DONO
    outra = RG.checar("pericia_execucao", "claude-sonnet-5-5", "v2", "v2+claude-sonnet-5-5", arq=arq)
    assert not outra["julgado"] and outra["rotulo"].startswith("NÃO JULGADO — proposta de")
    eixo = RG.checar("pericia_execucao:juridico", "claude-sonnet-5-5", "v1", "v1+claude-sonnet-5-5", arq=arq)
    assert eixo["julgado"]                                            # eixo herda o par da tarefa base


def test_rebaixado_e_coringa_nunca_julgam(tmp_path):
    reb = _par(estado=RG.REBAIXADO, motivo="1º grave na amostra do Opus")
    cor = _par(id="R-C", modelo="gemini:x", prompt_version="*", release_ia="*", estado=RG.NAO_JULGADO, dono=None)
    arq = _grava(tmp_path, _doc(reb, cor))
    r = RG.checar("pericia_execucao", "claude-sonnet-5-5", "v1", "v1+claude-sonnet-5-5", arq=arq)
    assert not r["julgado"] and r["estado"] == RG.REBAIXADO
    c = RG.checar("pericia_execucao", "gemini:x", "qualquer", "qualquer", arq=arq)
    assert c["par"] == "R-C" and not c["julgado"]


def test_regua_ilegivel_falha_fechado(tmp_path):
    p = _par()
    p["evidencia"]["ouro"]["n"] = 10                                   # aprovação que não fecha derruba a carga
    arq = _grava(tmp_path, _doc(p))
    r = RG.checar("pericia_execucao", "claude-sonnet-5-5", "v1", "v1+claude-sonnet-5-5", arq=arq)
    assert not r["julgado"] and "ilegível" in r["motivo"]
    r2 = RG.checar("pericia_execucao", "m", "v1", "x", arq=tmp_path / "nao_existe.yaml")
    assert not r2["julgado"] and "ilegível" in r2["motivo"]


# ── avaliação com dados existentes ────────────────────────────────────────────────────────────────────────────
def test_avaliar_pares_unidade_e_o_item_e_estratos_do_processo():
    pares = [{"tarefa": "pericia_integral", "modelo": "m#1", "item": "sei:SEI-270006/017964/2024", "nivel": 0,
              "nivel_ref": 2},
             {"tarefa": "pericia_integral:juridico", "modelo": "m", "item": "sei:SEI-270006/017964/2024", "nivel": 0,
              "nivel_ref": 2},                                         # mesmo processo: 1 item grave, não 2
             {"tarefa": "pericia_integral", "modelo": "m", "item": "sei:SEI-030001/000071/2025", "nivel": 1,
              "nivel_ref": 1},
             {"tarefa": "pericia_integral", "modelo": "m", "item": "sei:SEI-030001/000072/2025", "nivel": None,
              "nivel_ref": 1}]                                         # sem nível: fora da conta
    [r] = RG.avaliar_pares(pares)
    assert (r["pares"], r["graves_pares"], r["n_itens"], r["graves_itens"]) == (3, 2, 2, 1)
    assert (r["processos"], r["orgaos"], r["periodos"]) == (2, 2, ["2024", "2025"])
    assert r["cumpre_a"] is False and any("versão nova" in f for f in r["falta_a"])
    assert RG.estratos_do_item("alerta:123") == {"processo": None, "orgao": None, "periodo": None}


def test_avaliar_le_cruzamento_so_leitura(tmp_path):
    import sqlite3
    db = tmp_path / "cruz.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE veredito(id INTEGER PRIMARY KEY, par TEXT, tarefa TEXT, item TEXT, motor TEXT, "
                "modelo TEXT, veredito TEXT, nivel INT, confianca REAL, latencia_ms INT, com_exemplos INT, em TEXT)")
    con.executemany("INSERT INTO veredito(par,tarefa,item,motor,modelo,nivel) VALUES(?,?,?,?,?,?)", [
        ("p1", "pericia_execucao", "sei:SEI-1/2/2024", "claude", "claude-opus-5-5", 2),
        ("p1", "pericia_execucao", "sei:SEI-1/2/2024", "cascata", "gemini:g", 0),
        ("p2", "pericia_execucao", "sei:SEI-3/4/2024", "claude", "claude-sonnet-5-5", 1),
        ("p3", "pericia_execucao", "sei:SEI-3/4/2024", "claude", "claude-opus-5-5", 1)])
    con.commit()
    con.close()
    out = tmp_path / "av.json"
    assert RG._main(["avaliar", "--cruzamento", str(db), "--saida", str(out)]) == 0
    res = {r["modelo"]: r for r in json.loads(out.read_text(encoding="utf-8"))}
    assert res["gemini:g"]["graves_itens"] == 1 and res["claude-sonnet-5-5"]["graves_itens"] == 0


# ── integração: E11 e gateway (CHECAGEM, sem mudar roteamento) ─────────────────────────────────────────────────
def test_e11_rotulo_vem_da_regua(tmp_path, monkeypatch):
    from compliance_agent.aplicacao.estagios import periciar as P
    base = P.release_ia(P.MODELO, P.eixos_pedidos())
    assert base["regua"] == "nao_cumprida" and base["rotulo"] == f"NÃO JULGADO — proposta de {P.MODELO}"
    arq = _grava(tmp_path, _doc(_par(tarefa=P.TAREFA, modelo=P.MODELO, prompt_version=P.PROMPT_VERSION,
                                     release_ia=base["id"])))
    monkeypatch.setenv("JFN_REGRAS_NOVAS", str(arq))
    r = P.release_ia(P.MODELO, P.eixos_pedidos())
    assert r["regua"] == "cumprida" and r["rotulo"] == f"JULGADO — {P.MODELO} (régua R-X)" and r["id"] == base["id"]


def test_gateway_devolve_o_rotulo_sem_mudar_a_camada(tmp_path, monkeypatch):
    from compliance_agent.adaptadores.llm import gateway as G
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(tmp_path / "trace.db"))
    monkeypatch.setenv("JFN_LLM_CACHE_DB", str(tmp_path / "cache.db"))
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "estado"))
    monkeypatch.setattr(G, "_pre_assinatura", lambda t: None)
    msg = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    bk = {"assinatura_claude": lambda **kw: G.Retorno(texto="ok", modelo="claude-sonnet-5-5", tokens_in=1,
                                                      tokens_out=1)}
    sem = G.chamar("pericia_execucao", msg, prompt_version="v1", classe_dado="publico", backends=bk)
    assert sem.extras["regua"]["julgado"] is False
    assert sem.extras["regua"]["rotulo"] == "NÃO JULGADO — proposta de claude-sonnet-5-5"
    arq = _grava(tmp_path, _doc(_par(release_ia=sem.release_ia)))
    monkeypatch.setenv("JFN_REGRAS_NOVAS", str(arq))
    com = G.chamar("pericia_execucao", msg, prompt_version="v1", classe_dado="publico", backends=bk)
    assert com.extras["regua"]["julgado"] is True
    assert (com.camada, com.provedor) == (sem.camada, sem.provedor)          # checagem não muda o roteamento
