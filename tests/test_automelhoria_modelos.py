# -*- coding: utf-8 -*-
"""Automelhoria sobre os modelos grátis e fracos (dono 22/11/2026): cada sensor e cada remédio com controle POSITIVO
(o defeito montado é acusado/remediado) e NEGATIVO (o cenário conforme passa calado). Tudo sintético, em tmp_path:
nenhum banco real, nenhum provedor, nenhum Telegram, nenhuma mudança na cadeia de produção."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta

import pytest

import compliance_agent.direcionamento_cerebro as DC
import compliance_agent.llm.free_llm as F
from compliance_agent.llm import cascata_ajuste
from tools import automelhoria_modelos as M

AGORA = datetime(2026, 11, 22, 1, 0)


def _g(n, graves=0, leves=0):
    return {"n": n, "graves": graves, "leves": leves}


def _sig(probs):
    return [p["assinatura"] for p in probs]


# ───────────────────────── a) divergência do Opus ─────────────────────────
def test_contar_separa_grave_de_leve_e_junta_eixos_na_tarefa():
    pares = [("pericia_integral:juridico", "gemini:x", 2, 0, 0), ("pericia_integral:planejamento", "gemini:x", 1, 0, 0),
             ("pericia_integral", "gemini:x", 1, 1, 0), ("triagem_alertas", "claude-haiku@api-lote#ab12", 0, 2, 1)]
    c = M.contar(pares)
    assert c[("pericia_integral", "gemini:x")] == _g(3, 1, 1)
    assert c[("triagem_alertas", "claude-haiku@api-lote")] == _g(1, 1, 0), "o sufixo #lote não é outro modelo"


def test_subida_da_divergencia_grave_e_leve_vira_item_e_estavel_nao():
    atual = {("t", "gemini:a"): _g(40, 8, 20), ("t", "gemini:b"): _g(40, 1, 10)}
    anterior = {("t", "gemini:a"): _g(40, 1, 10), ("t", "gemini:b"): _g(40, 1, 10)}
    probs, reb = M.avaliar_divergencia(atual, anterior, regua={})
    assert "modelos:div_grave:t:gemini:a" in _sig(probs) and "modelos:div_leve:t:gemini:a" in _sig(probs)
    assert not [s for s in _sig(probs) if "gemini:b" in s and "div_" in s], "controle negativo: estável não acusa"
    assert reb == [], "subida sem régua do Sonnet não rebaixa ninguém"


def test_amostra_pequena_nao_acusa():
    probs, reb = M.avaliar_divergencia({("t", "gemini:a"): _g(10, 9, 0)}, {("t", "gemini:a"): _g(10, 0, 0)},
                                       regua={"t": {"taxa_grave": 0.0, "n": 100}})
    assert probs == [] and reb == []


def test_grave_acima_do_sonnet_rebaixa_e_abaixo_nao():
    regua = {"t": {"taxa_grave": 0.05, "n": 100, "fonte": "bancada"}}
    atual = {("t", "gemini:ruim"): _g(40, 6), ("t", "gemini:bom"): _g(40, 2), ("t", "groq"): _g(40, 4)}
    probs, reb = M.avaliar_divergencia(atual, {}, regua)
    assert [(t, m) for t, m, *_ in reb] == [("t", "gemini:ruim"), ("t", "groq")]
    motivo, num = reb[0][2], reb[0][3]
    assert "15.0%" in motivo and "5.0%" in motivo and num["graves"] == 6 and num["sonnet_n"] == 100
    assert "modelos:acima_sonnet:t:gemini:bom" not in _sig(probs), "controle negativo: 5% = Sonnet não é acima"


def test_modelo_fora_da_cascata_ordenavel_vira_item_humano_sem_rebaixar():
    probs, reb = M.avaliar_divergencia({("t", "claude-haiku-5-5@api-lote"): _g(40, 10)}, {},
                                       {"t": {"taxa_grave": 0.0, "n": 50}})
    assert reb == [] and probs[0]["acao_humana"]


def test_sem_regua_do_sonnet_abre_um_item_por_tarefa_pedindo_bancada():
    probs, reb = M.avaliar_divergencia({("t", "gemini:a"): _g(40, 5), ("t", "gemini:b"): _g(30, 3)}, {}, {})
    assert _sig(probs) == ["modelos:sem_regua_sonnet:t"] and reb == []
    assert "bancada" in probs[0]["acao_humana"]


def _cruz(tmp_path, linhas):
    db = tmp_path / "cruz.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE veredito(id INTEGER PRIMARY KEY, par TEXT, tarefa TEXT, item TEXT, motor TEXT, "
                "modelo TEXT, veredito TEXT, nivel INTEGER, confianca REAL, latencia_ms INTEGER, "
                "com_exemplos INTEGER DEFAULT 0, em TEXT)")
    con.executemany("INSERT INTO veredito(par,tarefa,item,motor,modelo,nivel,com_exemplos,em) VALUES(?,?,?,?,?,?,?,?)",
                    linhas)
    con.commit()
    return con


def test_regua_do_sonnet_vem_dos_pares_no_mesmo_item(tmp_path):
    em = AGORA.isoformat()
    linhas = []
    for i in range(25):   # Sonnet e Opus no MESMO item, em pares diferentes; 5 graves
        linhas += [(f"s{i}", "t", f"i{i}", "claude", "claude-sonnet-5-5", 2 if i < 5 else 1, 0, em),
                   (f"o{i}", "t", f"i{i}", "claude", "claude-opus-5-5", 0 if i < 5 else 1, 0, em)]
    con = _cruz(tmp_path, linhas)
    vazio = tmp_path / "regua.yaml"
    vazio.write_text("referencia_sonnet: {}\n")
    r = M.regua_sonnet(con, vazio, desde="2026-01-01")
    assert r["t"]["n"] == 25 and r["t"]["taxa_grave"] == pytest.approx(0.2)
    sub = tmp_path / "poucos"
    sub.mkdir()
    con2 = _cruz(sub, linhas[:10])
    assert M.regua_sonnet(con2, vazio, desde="2026-01-01") == {}, "controle negativo: 5 pares não fazem régua"


def test_fewshot_que_piora_o_acordo_vira_item_e_neutro_nao():
    pares = [("t", "g", 1, 1 if i < 8 else 0, 1) for i in range(25)] + [("t", "g", 1, 1, 0) for _ in range(25)]
    assert _sig(M.avaliar_fewshot(pares)) == ["modelos:fewshot_piorou:t"]
    neutro = [("t", "g", 1, 1, 1) for _ in range(25)] + [("t", "g", 1, 1, 0) for _ in range(25)]
    assert M.avaliar_fewshot(neutro) == []


def test_medir_le_so_pares_com_opus_e_exclui_cascata_sem_modelo(tmp_path):
    em_atual, em_ant = (AGORA - timedelta(days=1)).isoformat(timespec="seconds"), \
        (AGORA - timedelta(days=10)).isoformat(timespec="seconds")
    linhas = [("p1", "t", "i", "claude", "claude-opus-5-5", 0, 0, em_atual),
              ("p1", "t", "i", "cascata", "gemini:a", 2, 0, em_atual),
              ("p2", "t", "j", "claude", "claude-sonnet-5-5", 0, 0, em_atual),     # Sonnet ≠ Opus: fora
              ("p2", "t", "j", "cascata", "gemini:a", 2, 0, em_atual),
              ("p3", "t", "k", "claude", "claude-opus-5-5", 1, 0, em_atual),
              ("p3", "t", "k", "cascata", "cascata", 2, 0, em_atual),               # sem proveniência: fora
              ("p4", "t", "l", "claude", "claude-opus-5-5", 1, 0, em_ant),
              ("p4", "t", "l", "cascata", "gemini:a", 1, 0, em_ant)]
    _cruz(tmp_path, linhas).close()
    tr = tmp_path / "trace.db"
    sqlite3.connect(tr).execute("CREATE TABLE llm_trace(ts TEXT, provedor TEXT, ok INT, ms INT, erro TEXT, "
                                "modelo TEXT, tokens_in INT, tokens_out INT)").connection.commit()
    m = M.medir(tmp_path / "cruz.db", tr, agora=AGORA)
    assert m["atual"] == {("t", "gemini:a"): _g(1, 1, 0)} and m["anterior"] == {("t", "gemini:a"): _g(1, 0, 0)}


# ───────────────────────── b) disponibilidade ─────────────────────────
def _trace(tmp_path, linhas):
    db = tmp_path / "trace.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE llm_trace(ts TEXT, provedor TEXT, ok INT, ms INT, erro TEXT, modelo TEXT, "
                "tokens_in INT, tokens_out INT)")
    con.executemany("INSERT INTO llm_trace(ts,provedor,ok,ms,erro,modelo) VALUES(?,?,?,?,?,?)", linhas)
    con.commit()
    return con


def test_404_sem_resposta_depois_tira_e_404_seguido_de_ok_nao(tmp_path):
    con = _trace(tmp_path, [
        ("2026-11-20 10:00:00", "gemini", 1, 900, "", "morto"), ("2026-11-21 10:00:00", "gemini", 0, 90, "404", "morto"),
        ("2026-11-20 10:00:00", "gemini", 0, 90, "404", "voltou"), ("2026-11-21 10:00:00", "gemini", 1, 900, "", "voltou"),
        ("2026-11-21 10:00:00", "openrouter", 0, 90, "HTTPStatusError: Client error '404 Not Found' for url", "x/y:free")])
    probs, tirar = M.avaliar_disponibilidade(M.disponibilidade(con, "2026-11-15 00:00:00"))
    assert sorted(r for r, *_ in tirar) == ["gemini:morto", "openrouter:x/y:free"]
    assert "modelos:sumiu:gemini:voltou" not in _sig(probs), "controle negativo: respondeu depois do 404"


def test_cota_diaria_todo_dia_e_janela_estourada(tmp_path):
    linhas = [(f"2026-11-{d:02d} 10:00:00", "gemini", 0, 50, "429 generate_content_free_tier_requests;"
               "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "cotado") for d in range(15, 21)]
    linhas += [(f"2026-11-{d:02d} 10:00:00", "gemini", 0, 50, "429 GenerateRequestsPerMinute", "minuto")
               for d in range(15, 21)]
    linhas += [("2026-11-20 10:00:00", "nous", 1, 160_000 if i < 6 else 20_000, "", "lento") for i in range(25)]
    linhas += [("2026-11-20 10:00:00", "nous", 1, 20_000, "", "rapido") for _ in range(25)]
    probs, _ = M.avaliar_disponibilidade(M.disponibilidade(_trace(tmp_path, linhas), "2026-11-15 00:00:00"))
    s = _sig(probs)
    assert "modelos:cota_diaria:gemini:cotado" in s and "modelos:cota_diaria:gemini:minuto" not in s
    assert "modelos:timeout:nous:lento" in s and "modelos:timeout:nous:rapido" not in s


def test_trace_com_espaco_na_data_entra_na_janela(tmp_path):
    """O trace grava 'AAAA-MM-DD HH:MM:SS': comparado com um ISO de 'T', o dia do corte sumia inteiro."""
    con = _trace(tmp_path, [("2026-11-15 23:00:00", "gemini", 0, 1, "404", "m")])
    assert M.disponibilidade(con, "2026-11-15 01:00:00")[0]["n404"] == 1


# ───────────────────────── c) candidatos do catálogo ─────────────────────────
def test_gratis_com_prova_nao_medido_e_candidato_medido_e_falso_gratis_nao(tmp_path):
    cat = {"provedores": {
        "nous": [{"viva": True, "prova_gratis": "preço 0", "gratis_ids": ["qwen/qwen4-max:free", "novo/m1:free"]}],
        "ofox": [{"viva": True, "prova_gratis": "preço 0", "gratis_ids": ["alibaba/wan-3.0", "chat-x"]}],
        "semprova": [{"viva": True, "prova_gratis": "", "gratis_ids": ["talvez"]}],
        "gemini": [{"viva": True, "prova_gratis": "doc", "gratis_ids": ["gemini-2.5-flash-preview-tts", "gemini-3.6-flash"]}]}}
    banc = tmp_path / "b" / "res"
    banc.mkdir(parents=True)
    (banc / "tabela.json").write_text(json.dumps([{"modelo": "nous_qwen_qwen4-max_free", "processos": 100}]))
    ja = M.medidos(str(tmp_path / "*" / "res" / "tabela.json"), {"gemini:gemini-3.6-flash"})
    probs = M.avaliar_candidatos(cat, ja)
    assert _sig(probs) == ["modelos:nao_medido:nous"] and probs[0]["detalhe"] == "novo/m1:free"


# ───────────────────────── 3) aprendizado ─────────────────────────
def _conf(tmp_path):
    db = tmp_path / "conf.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE fila(chave TEXT, tarefa TEXT, motor TEXT, item TEXT, nivel INTEGER, nivel_opus INTEGER, "
                "veredito TEXT, veredito_opus TEXT, resposta TEXT, resposta_opus TEXT, criado_em TEXT, status TEXT)")
    con.executemany("INSERT INTO fila VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("k1", "pericia_execucao", "gemini:a", "sei:1", 2, 0, "irregular", "regular", "r", "CPF 123.456.789-01 no laudo",
         "2026-11-20", "conferido"),
        ("k2", "pericia_execucao", "gemini:a", "sei:2", 1, 0, "atenção", "regular", "r", "o", "2026-11-20", "conferido"),
        ("k3", "pericia_execucao", "gemini:a", "sei:3", 2, 0, "x", None, "r", None, "2026-11-20", "pendente")])
    con.commit()
    return con


def test_divergencia_grave_vira_caso_negativo_e_familia_nova_vira_licao(tmp_path):
    con, banco, md = _conf(tmp_path), tmp_path / "estado" / "casos.db", tmp_path / "CATALOGO.md"
    md.write_text("# Catálogo\n\n## 66. última\ntexto\n", encoding="utf-8")
    r = M.aprender(con, banco, md, agora=AGORA)
    assert r["casos_novos"] == 1 and r["familias_novas"] == ["pericia_execucao:superestima_risco"]
    txt = md.read_text(encoding="utf-8")
    assert txt.count("<!-- fam:pericia_execucao:superestima_risco -->") == 1 and txt.startswith("# Catálogo")
    c = sqlite3.connect(banco)
    assert c.execute("SELECT resposta_opus FROM caso").fetchone()[0].startswith("CPF ***.456.789-**"), "CPF mascarado"
    assert oct(banco.stat().st_mode)[-3:] == "600"
    # de novo: idempotente (nada duplica no banco nem no catálogo)
    r2 = M.aprender(con, banco, md, agora=AGORA)
    assert r2["casos_novos"] == 0 and r2["familias_novas"] == [] and md.read_text(encoding="utf-8") == txt
    assert "ERRO REAL 1" in M.bloco_ensino("pericia_execucao", banco=banco)
    assert M.bloco_ensino("outra", banco=banco) == "", "controle negativo: tarefa sem caso não tem bloco"


def test_familia_por_direcao():
    assert M.familia_de("pericia_integral:juridico", 0, 2)[0] == "pericia_integral:subestima_risco"
    assert M.familia_de("t", 2, 0)[0] == "t:superestima_risco"


# ───────────────────────── remédios: o arquivo da cascata ─────────────────────────
@pytest.fixture
def ajuste(tmp_path, monkeypatch):
    p = tmp_path / "cascata_ajuste.json"
    monkeypatch.setenv("JFN_CASCATA_AJUSTE", str(p))
    return p


def test_sob_pytest_sem_env_o_arquivo_real_e_inerte(monkeypatch):
    monkeypatch.delenv("JFN_CASCATA_AJUSTE", raising=False)
    assert cascata_ajuste.ler() == {} and cascata_ajuste.rebaixar("t", "gemini:a", "m", {}) is False


def test_rebaixar_vai_para_o_fim_tirar_sai_e_desfazer_volta(ajuste):
    ordem = ["gemini:a", "gemini:b", "gemini:c"]
    assert cascata_ajuste.ordenar(ordem, "t") == ordem, "controle negativo: sem ajuste, ordem de sempre"
    assert cascata_ajuste.rebaixar("t", "gemini:a", "grave 15% > Sonnet 5%", {"n": 40}) is True
    assert cascata_ajuste.rebaixar("t", "gemini:a", "de novo", {}) is False, "idempotente"
    assert cascata_ajuste.ordenar(ordem, "t:juridico") == ["gemini:b", "gemini:c", "gemini:a"]
    assert cascata_ajuste.ordenar(ordem, "outra") == ordem, "rebaixamento é POR TAREFA"
    cascata_ajuste.tirar("gemini:c", "404", {"n404": 3})
    assert cascata_ajuste.ordenar(ordem, "outra") == ["gemini:a", "gemini:b"], "404 sai de todas"
    d = json.loads(ajuste.read_text())
    assert d["rebaixados"]["t"]["gemini:a"]["numeros"] == {"n": 40} and "grave 15%" in d["historico"][0]["motivo"]
    assert cascata_ajuste.desfazer("t", "gemini:a") and cascata_ajuste.desfazer("*", "gemini:c")
    assert cascata_ajuste.ordenar(ordem, "t") == ordem


def test_sufixo_free_nao_escapa_do_ajuste(ajuste):
    cascata_ajuste.tirar("openrouter:x/y:free", "404", {})
    assert cascata_ajuste.ordenar(["x/y:free", "z/w:free"], chave=lambda m: f"openrouter:{m}") == ["z/w:free"]


def test_sensor_aplica_rebaixamento_e_nunca_promove(ajuste, monkeypatch, tmp_path):
    m = {"atual": {("t", "gemini:ruim"): _g(40, 8)}, "anterior": {}, "pares_atuais": [],
         "regua": {"t": {"taxa_grave": 0.05, "n": 100}}, "disp": [], "modelos_com_pares": set()}
    monkeypatch.setattr(M, "medir", lambda **k: m)
    monkeypatch.setattr(M, "catalogo_atual", lambda: {"provedores": {}})
    conf = _conf(tmp_path)
    conf.close()
    monkeypatch.setattr(M, "DATA", tmp_path)
    (tmp_path / "conf.db").rename(tmp_path / "conferencia_opus.db")
    monkeypatch.setenv("JFN_CASOS_NEGATIVOS", str(tmp_path / "casos.db"))
    probs = M.sensor(catalogo_md=None)
    assert cascata_ajuste.rebaixados("t") == {"gemini:ruim"}
    assert "modelos:acima_sonnet:t:gemini:ruim" in _sig(probs)
    assert all(not p["remediar"] for p in probs), "sem `remediar`: nada vai ao executor que escala pelo Telegram"
    # o modelo melhorou: o sensor não o devolve à frente sozinho (promoção é do dono, com bancada)
    m["atual"] = {("t", "gemini:ruim"): _g(40, 0)}
    M.sensor(catalogo_md=None)
    assert cascata_ajuste.rebaixados("t") == {"gemini:ruim"}


# ───────────────────────── a cascata obedece o arquivo ─────────────────────────
class _Resp:
    def __init__(self, status, txt=""):
        self.status_code, self._t, self.text = status, txt, ""

    def json(self):
        return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": self._t}]}}]}

    def raise_for_status(self):
        return None


def _gemini_roteiro(monkeypatch, tmp_path, modelos, chamados):
    class _Cli:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, json=None, **_):
            m = url.split("/models/")[1].split(":")[0]
            chamados.append(m)
            return _Resp(200, f"de {m}")
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(tmp_path / "trace.db"))
    monkeypatch.setattr(DC, "_gemini_keys", lambda: ["k"])
    monkeypatch.setenv("DIRECIONAMENTO_GEMINI_MODELS", ",".join(modelos))
    monkeypatch.delenv("DIRECIONAMENTO_GEMINI_MODEL", raising=False)
    monkeypatch.setattr(F, "cerebras_available", lambda: False)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _Cli())


def test_gerar_gemini_pula_o_rebaixado_na_tarefa_e_o_tirado(ajuste, monkeypatch, tmp_path):
    chamados = []
    _gemini_roteiro(monkeypatch, tmp_path, ["a", "b"], chamados)
    msgs = [{"role": "user", "content": "oi"}]
    assert asyncio.run(DC.gerar_gemini(msgs, tarefa="t")) == "de a", "controle negativo: sem ajuste, 'a' primeiro"
    cascata_ajuste.rebaixar("t", "gemini:a", "m", {})
    assert asyncio.run(DC.gerar_gemini(msgs, tarefa="t")) == "de b"
    assert asyncio.run(DC.gerar_gemini(msgs, tarefa="outra")) == "de a"
    cascata_ajuste.tirar("gemini:a", "404", {})
    assert asyncio.run(DC.gerar_gemini(msgs)) == "de b"


def test_groq_rebaixado_vai_para_depois_dos_extras(ajuste, monkeypatch, tmp_path):
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(tmp_path / "trace.db"))
    monkeypatch.setattr(DC, "_gemini_keys", lambda: [])
    monkeypatch.setattr(F, "_em_cooldown", lambda p: False)
    chamados = []

    async def _groq(_m):
        chamados.append("groq")
        return "groq"

    async def _or(*a, **k):
        chamados.append("openrouter")
        return "openrouter"
    monkeypatch.setattr(DC, "_groq_gerar", _groq)
    monkeypatch.setattr(F, "openrouter_available", lambda: True)
    monkeypatch.setattr(F, "openrouter_chat_async", _or)
    monkeypatch.setattr(F, "cerebras_available", lambda: False)
    monkeypatch.setattr(F, "extra_available", lambda p: False)
    msgs = [{"role": "user", "content": "x"}]
    assert asyncio.run(DC._gerar_default(msgs, tarefa="t")) == "groq", "controle negativo: groq na frente"
    cascata_ajuste.rebaixar("t", "groq", "m", {})
    assert asyncio.run(DC._gerar_default(msgs, tarefa="t")) == "openrouter"
    assert asyncio.run(DC._gerar_default(msgs, tarefa="outra")) == "groq"


# ───────────────────────── f) graves da ficha grátis (22/11/2026) ─────────────────────────
def test_grave_da_ficha_gratis_vira_item_por_modelo_e_categoria(tmp_path):
    rec = tmp_path / "recusas.jsonl"
    linhas = [{"em": "2026-11-21T10:00:00", "pasta": "p1", "tentativas": [
                  {"modelo": "gemini-x", "motivo": "grave", "graves": ["resumo: R$ 146,5 milh", "datas: 01/01/2020"]}]},
              {"em": "2026-11-21T11:00:00", "pasta": "p2", "tentativas": [
                  {"modelo": "gemini-x", "motivo": "grave", "graves": ["resumo: R$ 9 mi"]},
                  {"modelo": "outro", "motivo": "sem resposta válida"}]},
              {"em": "2026-11-01T11:00:00", "pasta": "velho", "tentativas": [            # fora da janela de 7 dias
                  {"modelo": "gemini-x", "motivo": "grave", "graves": ["cnpjs: 1"]}]}]
    rec.write_text("\n".join(json.dumps(x) for x in linhas) + "\nlixo\n", encoding="utf-8")
    probs = M.avaliar_ficha_gratis(rec, {}, agora=AGORA)
    assert sorted(_sig(probs)) == ["modelos:ficha_gratis_grave:gemini-x:datas",
                                   "modelos:ficha_gratis_grave:gemini-x:resumo"]
    assert "2 processo" in next(p["titulo"] for p in probs if p["assinatura"].endswith(":resumo"))


def test_grave_medido_na_bancada_abre_item_e_bancada_limpa_nao(tmp_path):
    bancada = {"ficha_gratis": {"modelo": "gemini-x", "fonte": "bancada 22/11", "graves": {"resumo": 3, "datas": 0}}}
    probs = M.avaliar_ficha_gratis(tmp_path / "nao_existe.jsonl", bancada, agora=AGORA)
    assert _sig(probs) == ["modelos:ficha_gratis_grave:gemini-x:resumo"]
    assert M.avaliar_ficha_gratis(tmp_path / "nao_existe.jsonl", {}, agora=AGORA) == []
