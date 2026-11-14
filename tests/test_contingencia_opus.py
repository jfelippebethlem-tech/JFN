# -*- coding: utf-8 -*-
"""Contingência do Claude + conferência do Opus (dono, 14/11/2026: "nunca ficar sem produzir; o que for feito por
eles depois tem conferência sempre pelo claude opus"). Nenhum teste chama o `claude`, provedor ou Telegram."""
import json
import sqlite3
import time
from datetime import datetime

import pytest

from compliance_agent.llm import claude_motor as M
from compliance_agent.llm import comotor as CM
from compliance_agent.llm import conferencia_opus as Q
from compliance_agent.llm import contingencia as C
from compliance_agent.llm import cruzamento as X
from compliance_agent.llm.claude_motor import Pensamento

LIMITE = "You've hit your 5-hour limit · resets 2:30am (America/Sao_Paulo)"      # texto real de 13/11/2026 22:23


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("JFN_CLAUDE_CWD", str(tmp_path / "cwd"))
    monkeypatch.setenv("JFN_CONFERENCIA_DB", str(tmp_path / "conf.db"))
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))
    monkeypatch.setenv("JFN_CLAUDE_API", "0")                    # nunca a API paga
    for v in ("JFN_CLAUDE_CONTINGENCIA", "JFN_CLAUDE_MOTOR", "JFN_CLAUDE_MAX_CHAMADAS_DIA", "JFN_CLAUDE_MAX_SEGUNDOS_DIA",
              "JFN_CLAUDE_PAUSA_LIMITE_S", "JFN_CONFERENCIA_PROPAGAR"):
        monkeypatch.delenv(v, raising=False)
    yield


def _cli(resultado, is_error=False):
    chamadas = []

    def ex(cmd, entrada, env, cwd, timeout):
        chamadas.append(cmd)
        return 0, json.dumps({"type": "result", "is_error": is_error, "result": resultado}), ""
    ex.chamadas = chamadas
    return ex


def _exec(v, nota):
    return json.dumps({"execucao_comprovada": v, "nota_risco_execucao": nota})


# ── 1. detecção ──────────────────────────────────────────────────────────────────────────────────────
def test_erro_real_de_limite_e_reconhecido_e_a_hora_de_volta_e_lida():
    assert M.classificar_erro(LIMITE) == "limite"                # antes de 14/11: "outro" — o motor seguia tentando
    assert M.classificar_erro('API Error: 429 {"type":"error","error":{"type":"rate_limit_error"}}') == "limite"
    agora = datetime(2026, 11, 13, 22, 23).timestamp()
    ate = C.hora_de_volta(LIMITE, agora)
    from zoneinfo import ZoneInfo
    volta = datetime.fromtimestamp(ate, ZoneInfo("America/Sao_Paulo"))
    assert (volta.day, volta.hour, volta.minute) == (14, 2, 32)  # 2:30 do dia seguinte + 2 min de margem
    assert C.hora_de_volta("resets 3pm", datetime(2026, 11, 14, 12, 30).timestamp()) > agora
    # 14/11/2026 16:31 — o texto REAL que derrubou a própria conferência (e o agente que a escrevia)
    real = "You've hit your 5-hour limit · resets 5:30pm (America/Sao_Paulo)"
    assert M.classificar_erro(real) == "limite"
    v = datetime.fromtimestamp(C.hora_de_volta(real, datetime(2026, 11, 14, 16, 31, 21).timestamp()),
                               ZoneInfo("America/Sao_Paulo"))
    assert (v.day, v.hour, v.minute) == (14, 17, 32)             # mesmo dia, 17:30 + 2 min
    assert C.hora_de_volta("erro qualquer sem hora") is None      # sem hora legível não se inventa hora


def test_negativo_erro_comum_nao_vira_contingencia():
    ex = _cli("algo deu errado", is_error=True)
    assert M.pensar("pericia_execucao", "x", executar=ex, espera=0, backend="cli") is None
    assert not C.estado()["ativa"] and not C.arquivo().exists()
    assert M.pensar("pericia_execucao", "x", executar=_cli("ok"), espera=0, backend="cli").texto == "ok"


def test_limite_liga_contingencia_no_arquivo_unico_e_nao_martela_o_cli():
    ex = _cli(LIMITE, is_error=True)
    assert M.pensar("pericia_execucao", "x", executar=ex, espera=0, backend="cli") is None
    e = C.estado()
    assert e["ativa"] and e["origem"] == "limite_assinatura" and e["ate"] > time.time()
    assert json.loads(C.arquivo().read_text())["entradas"][-1]["origem"] == "limite_assinatura"
    for _ in range(3):                                           # enquanto durar, nenhuma chamada ao CLI
        assert M.pensar("triagem_alertas", "y", executar=ex, espera=0, backend="cli") is None
    assert len(ex.chamadas) == 1
    assert M.motivo_desligado().startswith("limite de uso")
    assert M.painel()["contingencia"]["ativa"] is True
    assert M.canario(executar=ex, avisar=lambda *_: None)["ok"] is None       # canário ADIADO, não reprovado
    assert M.ler_estado().get("canario_ok") is not False
    C.sair("teste")
    assert not C.estado()["ativa"]


def test_noventa_por_cento_do_teto_reserva_o_resto_para_o_opus(monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_MAX_CHAMADAS_DIA", "10")
    ok = _cli("ok")
    for _ in range(8):
        assert M.pensar("pericia_execucao", "x", executar=ok, espera=0, backend="cli")
    assert not C.estado()["ativa"]                               # 80%: nada muda
    assert M.pensar("pericia_execucao", "x", executar=ok, espera=0, backend="cli")       # 9ª ⇒ 90%
    e = C.estado()
    assert e["ativa"] and e["origem"] == "teto_proprio"
    assert M.pensar("pericia_execucao", "x", executar=ok, espera=0, backend="cli") is None   # volume: outros modelos
    assert "contingência" in M.ultimo_motivo
    assert M.pensar("conferencia_opus", "x", executar=ok, espera=0, backend="cli")       # a reserva é do Opus


# ── 2 e 3. consumidor segue com outro modelo, marca pendente; o Opus confere e prevalece ─────────────
def _juizo_em_contingencia(resp_cascata):
    return CM.juizo("pericia_execucao", cascata=lambda *a, **k: resp_cascata, sorteio=lambda: 1.0)


def test_positivo_limite_cascata_produz_marca_pendente_e_opus_substitui(monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_CONTINGENCIA", "1")
    g = _juizo_em_contingencia(_exec("sim", 2))
    txt = g("PROMPT DO PROCESSO", "SISTEMA", 60.0, item="sei:SEI-1")
    u = CM.ultima_chamada()
    assert json.loads(txt)["execucao_comprovada"] == "sim"      # produziu — com a cascata
    assert u["exibido"] == "cascata" and u["conferencia_pendente"] is True
    assert Q.pendente("pericia_execucao", "sei:SEI-1")           # nunca VERIFICADO enquanto pendente
    p = Q.painel()
    assert p["contingencia"]["ativa"] and p["pendentes"] == 1 and p["por_tarefa"][0]["motor"] == "cascata"

    # assinatura ainda fora: a conferência para sem gastar tentativa, a fila fica
    assert Q.conferir(5, pensar=lambda *a, **k: None) == [] and Q.pendente("pericia_execucao", "sei:SEI-1")

    # assinatura voltou: o Opus relê a MESMA entrada, diverge (🔴 × ⚪) e prevalece
    monkeypatch.delenv("JFN_CLAUDE_CONTINGENCIA")
    visto, aplicado = {}, {}

    def opus(tarefa, prompt, **k):
        visto.update(tarefa=tarefa, prompt=prompt, **k)
        return Pensamento(texto=_exec("nao", 9), modelo="claude-opus-5-5", segundos=1, tarefa=tarefa)
    monkeypatch.setitem(Q.APLICADORES, "pericia_execucao", "tests.test_contingencia_opus:_aplicador_duble")
    _aplicador_duble.visto = aplicado
    feitos = Q.conferir(5, pensar=opus)
    assert visto["tarefa"] == "conferencia_opus" and visto["modelo"] == M.MODELO_JUIZO and visto["backend"] == "cli"
    assert visto["prompt"].startswith("PROMPT DO PROCESSO") and visto["sistema"] == "SISTEMA"
    assert feitos[0]["concorda"] == 0 and feitos[0]["aplicado"] == 1
    assert aplicado == {"item": "sei:SEI-1", "modelo": "claude-opus-5-5", "concorda": 0}
    assert not Q.pendente("pericia_execucao", "sei:SEI-1")
    con = X.conectar()
    assert {(m, n) for m, n in con.execute("SELECT motor, nivel FROM veredito WHERE item='sei:SEI-1' AND nivel IS NOT NULL")} \
        == {("claude", 2), ("cascata", 0)}
    assert con.execute("SELECT COUNT(*) FROM revisao").fetchone()[0] == 1      # divergência grave ⇒ revisão humana
    con.close()
    p = Q.painel()
    assert p["pendentes"] == 0 and p["conferidos"] == 1 and p["divergencias"] == 1

    # a mesma entrada, regenerada, sai com a resposta do OPUS sem chamar ninguém
    g2 = CM.juizo("pericia_execucao", cascata=lambda *a, **k: pytest.fail("não devia chamar a cascata"),
                  pensar=lambda *a, **k: pytest.fail("não devia chamar o Claude"))
    assert json.loads(g2("PROMPT DO PROCESSO", "SISTEMA", 60.0))["execucao_comprovada"] == "nao"
    assert CM.ultima_chamada()["exibido"] == "claude:claude-opus-5-5 (conferência)"


def _aplicador_duble(item, resposta, modelo, concorda):
    _aplicador_duble.visto.update(item=item, modelo=modelo, concorda=concorda)
    return True


def test_opus_concorda_registra_acordo_sem_divergencia(monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_CONTINGENCIA", "1")
    _juizo_em_contingencia(_exec("parcial", 5))("P2", "S", 60.0, item="sei:SEI-2")
    monkeypatch.delenv("JFN_CLAUDE_CONTINGENCIA")
    monkeypatch.setitem(Q.APLICADORES, "pericia_execucao", "modulo.inexistente:fn")       # aplicador quebrado não derruba
    feitos = Q.conferir(5, pensar=lambda t, p, **k: Pensamento(texto=_exec("parcial", 6), modelo="claude-opus-5-5",
                                                                segundos=1, tarefa=t))
    assert feitos[0]["concorda"] == 1 and feitos[0]["aplicado"] == 0
    assert X.concordancia(tarefa="pericia_execucao")["por_tarefa_modelo"][0]["acordos"] == 1


def test_prioridade_da_fila_e_gravidade_depois_valor(monkeypatch):
    for item, resp, valor in (("a", _exec("sim", 1), 9e9), ("b", _exec("nao", 9), 10.0), ("c", _exec("nao", 9), 500.0),
                              ("d", _exec("parcial", 5), 1.0)):
        Q.enfileirar("pericia_execucao", item, f"prompt {item}", motor="groq:x", resposta=resp, valor=valor)
    ordem = []
    Q.conferir(4, pensar=lambda t, p, **k: ordem.append(p) or Pensamento(texto=_exec("sim", 1), modelo="claude-opus-5-5",
                                                                         segundos=1, tarefa=t))
    assert ordem == ["prompt c", "prompt b", "prompt d", "prompt a"]       # 🔴 (maior valor antes) → 🟡 → ⚪


def test_opus_fora_do_formato_nao_vale_como_conferencia():
    Q.enfileirar("pericia_execucao", "z", "prompt z", motor="groq:x", resposta=_exec("nao", 9))
    lixo = lambda t, p, **k: Pensamento(texto="não sei dizer", modelo="claude-opus-5-5", segundos=1, tarefa=t)
    for _ in range(Q.MAX_TENTATIVAS):
        Q.conferir(1, pensar=lixo)
    assert Q.pendente("pericia_execucao", "z")                   # segue sem VERIFICADO; aparece como "erro" no painel
    assert Q.painel()["erros"] == 1 and Q.resposta_conferida("pericia_execucao", "prompt z") is None


def test_claude_barato_pela_api_tambem_vai_ao_opus():
    haiku = lambda t, p, **k: Pensamento(texto=_exec("sim", 2), modelo="claude-haiku-5-5@api", segundos=1, tarefa=t)
    g = CM.juizo("pericia_execucao", pensar=haiku, cascata=lambda *a, **k: _exec("sim", 2), sorteio=lambda: 1.0)
    g("P3", "S", 60.0, item="sei:SEI-3")
    assert CM.ultima_chamada()["conferencia_pendente"] is True and Q.pendente("pericia_execucao", "sei:SEI-3")


# ── negativos ────────────────────────────────────────────────────────────────────────────────────────
def test_negativo_sem_limite_nada_muda():
    claude = lambda t, p, **k: Pensamento(texto=_exec("sim", 2), modelo="claude-sonnet-5-5", segundos=1, tarefa=t)
    g = CM.juizo("pericia_execucao", pensar=claude, cascata=lambda *a, **k: _exec("sim", 2), sorteio=lambda: 1.0)
    assert json.loads(g("P4", "S", 60.0, item="sei:SEI-4"))["execucao_comprovada"] == "sim"
    u = CM.ultima_chamada()
    assert u["exibido"] == "claude:claude-sonnet-5-5" and u["outro"] == "cascata" and u["conferencia_pendente"] is False
    assert Q.painel()["pendentes"] == 0 and not Q.pendente("pericia_execucao", "sei:SEI-4")
    assert not C.estado()["ativa"]


def test_triagem_em_contingencia_nunca_vira_verificado_sem_opus(monkeypatch):
    from compliance_agent import triagem_alertas as T
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE alertas(id INTEGER PRIMARY KEY, tipo TEXT, severidade TEXT, titulo TEXT, descricao TEXT, "
                "evidencias TEXT, status TEXT, detectado_em TEXT, pessoa_id INTEGER)")
    con.execute("INSERT INTO alertas VALUES(1,'fracionamento','ALTA','Dispensa repetida','descrição do alerta um com "
                "trecho citável','{\"valor_total\": 100}','novo','2026-11-01',NULL)")
    T.garantir(con)
    r = json.dumps({"prioridade": "provavel_falso_positivo", "nota": 1, "citacao": "trecho citável",
                    "justificativa": "j", "proximo_passo": "p"})
    monkeypatch.setenv("JFN_CLAUDE_CONTINGENCIA", "1")
    g = CM.juizo("triagem_alertas", cascata=lambda *a, **k: r, sorteio=lambda: 1.0, conferencia=False)
    feitos = T.triar_lote(con, 1, gerar=g)
    assert feitos and feitos[0]["estado"] == T.PENDENTE and feitos[0]["motor"] == "cascata"
    estado, opus, motor = con.execute("SELECT estado, opus_pendente, motor FROM alertas_triagem").fetchone()
    assert (estado, opus, motor) == ("PENDENTE", 1, "cascata")   # ⚪ da cascata sozinha: Opus confere mesmo assim
    # assinatura volta: Opus diverge ⇒ a leitura do Opus prevalece, item segue PENDENTE de revisão humana
    monkeypatch.delenv("JFN_CLAUDE_CONTINGENCIA")
    ro = json.dumps({"prioridade": "aprofundar", "nota": 8, "citacao": "trecho citável", "justificativa": "jo",
                     "proximo_passo": "po"})
    T.verificar_com_opus(con, 5, pensar=lambda t, p, **k: Pensamento(texto=ro, modelo="claude-opus-5-5", segundos=1,
                                                                     tarefa=t), avisar=lambda *_: None)
    prio, estado, opus, por, motivo = con.execute(
        "SELECT prioridade, estado, opus_pendente, verificado_por, motivo FROM alertas_triagem").fetchone()
    assert (prio, estado, opus, por) == ("aprofundar", "PENDENTE", 0, "claude-opus-5-5")
    assert "prevalece o Opus" in motivo and "provavel_falso_positivo" in motivo


def test_rotina_base_segue_com_a_cascata_e_marca(monkeypatch):
    from compliance_agent import rotina_base as R
    esquema = {"type": "object", "required": ["hipoteses"]}
    monkeypatch.setattr(M, "pensar", lambda *a, **k: None)
    monkeypatch.setattr(M, "ultimo_motivo", "limite de uso da assinatura — pausa até 02:32")
    # sob pytest, sem cascata injetada, ninguém chama provedor: segue PENDENTE como antes
    assert R.pensar("camada_subjetiva", "p", schema=esquema) == (None, "limite de uso da assinatura — pausa até 02:32")
    monkeypatch.setattr(C, "cascata", lambda tarefa, prompt, **k: ({"hipoteses": [1]}, "gemini:gemini-3.6-flash"))
    assert R.pensar("camada_subjetiva", "p", schema=esquema) == ({"hipoteses": [1]}, None)
    assert R.ULTIMO_MODELO == "gemini:gemini-3.6-flash" and R.ULTIMA_EM_CONTINGENCIA is True
    assert R.pensar("camada_subjetiva", "p", schema=esquema, contingencia=False)[0] is None


def test_cascata_de_contingencia_enfileira_com_o_modelo_real_e_descarta_fora_do_formato():
    esquema = {"type": "object", "required": ["hipoteses"]}
    r = C.cascata("camada_subjetiva", "prompt h", schema=esquema, sistema="S", motivo="limite",
                  gerar=lambda p, s, t, j: '{"hipoteses": ["h1"]}')
    assert r[0] == {"hipoteses": ["h1"]} and Q.painel()["pendentes"] == 1
    assert C.cascata("camada_subjetiva", "prompt i", schema=esquema, gerar=lambda p, s, t, j: "prosa sem json") is None
    # tarefa sem régua para comparar: o texto do Opus prevalece e nada é contado como divergência
    feitos = Q.conferir(2, pensar=lambda t, p, **k: Pensamento(texto='{"hipoteses": ["h2"]}', modelo="claude-opus-5-5",
                                                                segundos=1, tarefa=t))
    assert feitos[0]["concorda"] is None and Q.painel()["pendentes"] == 0


def test_aplicador_do_parecer_de_execucao():
    from tools import lex_execucao as L
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE lex_execucao(numero_sei TEXT PRIMARY KEY, execucao_comprovada TEXT, coerencia TEXT, "
                "nota_risco INTEGER, indicios TEXT, duvidas TEXT, resumo TEXT, modelo TEXT, em TEXT)")
    con.execute("INSERT INTO lex_execucao VALUES('SEI-9','sim','ok',2,'[]','[]','r','gemini:gemini-3.6-flash','2026-11-14')")
    opus = json.dumps({"execucao_comprovada": "nao", "nota_risco_execucao": 9, "indicios": ["sem atesto"], "resumo": "x"})
    assert L.aplicar_conferencia("sei:SEI-9", "sem json", "claude-opus-5-5", 0, con=con) is False     # não sobrescreve
    assert con.execute("SELECT execucao_comprovada FROM lex_execucao").fetchone()[0] == "sim"
    assert L.aplicar_conferencia("sei:SEI-9", opus, "claude-opus-5-5", 0, con=con) is True
    ex, nota, modelo = con.execute("SELECT execucao_comprovada, nota_risco, modelo FROM lex_execucao").fetchone()
    assert (ex, nota) == ("nao", 9) and modelo == "claude:claude-opus-5-5 (conferência; antes gemini:gemini-3.6-flash)"
    assert L.aplicar_conferencia("sei:SEI-0", opus, "claude-opus-5-5", 0, con=con) is False
    con.execute("UPDATE lex_execucao SET modelo='groq'")
    assert L.aplicar_conferencia("sei:SEI-9", opus, "claude-opus-5-5", 1, con=con) is True
    assert con.execute("SELECT execucao_comprovada, modelo FROM lex_execucao").fetchone() == \
        ("nao", "groq · conferido claude:claude-opus-5-5")


def test_rota_do_painel_nao_expoe_custo():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from compliance_agent.aovivo import api
    Q.enfileirar("pericia_execucao", "sei:SEI-5", "p5", motor="groq:x", resposta=_exec("nao", 9), motivo="limite")
    app = FastAPI()
    app.include_router(api.router)
    j = TestClient(app).get("/api/ao-vivo/conferencia-opus").json()
    assert j["disponivel"] and j["pendentes"] == 1 and j["itens"][0]["item"] == "sei:SEI-5"
    assert not any(k in json.dumps(j).lower() for k in ("usd", "us$", "custo", "chamadas"))
