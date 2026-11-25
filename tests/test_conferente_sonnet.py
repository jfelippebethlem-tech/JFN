# -*- coding: utf-8 -*-
"""O6.6 — conferente intermediário Sonnet no E12 (flag JFN_CONFERENTE_SONNET, desligada). Fila, cruzamento e régua
em tmp_path; o "Sonnet" é um dublê (`pensar` injetado) — nenhuma chamada ao `claude`, a provedor ou ao banco real."""
import json

import pytest

from compliance_agent.llm import claude_api
from compliance_agent.llm import conferencia_opus as Q
from compliance_agent.llm import conferente_sonnet as CS
from compliance_agent.llm.claude_motor import Pensamento
from compliance_agent.qualidade import regua as RG


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("JFN_CONFERENCIA_DB", str(tmp_path / "conf.db"))
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))
    monkeypatch.setenv("JFN_REGRAS_NOVAS", str(tmp_path / "regras_novas.yaml"))   # ausente ⇒ nada julgado
    monkeypatch.setenv("JFN_CLAUDE_API", "0")
    for v in ("JFN_CONFERENCIA_RISCO", "JFN_CONFERENTE_SONNET", "JFN_CONFERENTE_LIMIAR_ALTO",
              "JFN_CONFERENTE_DIVERGENCIA", "JFN_CONFERENTE_TAREFAS", "JFN_CONFERENCIA_LIMIAR_VALOR",
              "JFN_CONFERENCIA_PROPAGAR", "JFN_CONFERENCIA_EXECUTOR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(Q, "RETENTAR_S", (0.0, 0.0))
    RG._CACHE.clear()
    yield
    RG._CACHE.clear()


def _exec(v, nota):
    return json.dumps({"execucao_comprovada": v, "nota_risco_execucao": nota})


def _sonnet(nivel_texto):
    def pensar(tarefa, entrada, **kw):
        assert tarefa == CS.TAREFA and kw["modelo"] == CS.MODELO and kw["backend"] == "cli"
        return Pensamento(texto=nivel_texto, modelo=CS.MODELO, segundos=1.0, tarefa=tarefa)
    return pensar


def _enfileira(item="sei:SEI-1/1/2025", valor=0.0, resposta=None, entrada="e1"):
    return Q.enfileirar("pericia_execucao", item, entrada, motor="groq", resposta=resposta or _exec("parcial", 5),
                        valor=valor)


def _status(con, chave_entrada="e1"):
    return con.execute("SELECT status, risco FROM fila WHERE chave=?",
                       (Q.chave_de("pericia_execucao", chave_entrada),)).fetchone()


def test_modelo_e_o_sonnet_da_casa():
    assert CS.MODELO == claude_api.MODELO_VOLUME


# ── regras puras ──────────────────────────────────────────────────────────────────────────────────────────────
def test_rota_divergencia_grave_valor_alto_e_indisponivel_vao_ao_opus():
    t = "pericia_execucao"
    assert CS.rota(["divergencia"], 0.0, tarefa=t) == "opus"
    assert CS.rota(["grave"], 0.0, tarefa=t) == "opus"
    assert CS.rota(["valor"], 10_000_000.00, tarefa=t) == "opus"                 # limiar alto inclusivo
    assert CS.rota(["valor"], 9_999_999.99, tarefa=t) == "sonnet"                # valor médio
    assert CS.rota(["baixa_confianca"], None, tarefa=t) == "opus"                # INDISPONÍVEL ≠ 0
    assert CS.rota(["amostra"], None, tarefa=t, valor_aplica=False) == "sonnet"  # item sem processo
    assert CS.rota(["amostra"], 0.0, tarefa="pericia_integral") == "opus"        # integral fora por padrão


def test_depois_do_sonnet_modos():
    ch = next(c for c in (f"k{i}" for i in range(100)) if not CS._sorteado(c))
    assert CS.depois_do_sonnet(1, 1, ch, "qualquer") == ("fecha", "sonnet_concorda")
    assert CS.depois_do_sonnet(1, 0, ch, "qualquer") == ("opus", "sonnet_divergiu")
    assert CS.depois_do_sonnet(1, 0, ch, "grave") == ("fecha", "sonnet_divergencia_leve")
    assert CS.depois_do_sonnet(0, 2, ch, "grave")[0] == "opus"                   # 🔴 do Sonnet sempre sobe
    assert CS.depois_do_sonnet(2, 0, ch, "grave") == ("opus", "sonnet_divergiu")   # |Δ| = 2
    assert CS.depois_do_sonnet(1, None, ch, "grave") == ("opus", "sonnet_sem_nivel")
    sort = next(c for c in (f"k{i}" for i in range(200)) if CS._sorteado(c))
    assert CS.depois_do_sonnet(1, 1, sort, "qualquer") == ("opus", "sonnet_amostra")


# ── entrada na fila ───────────────────────────────────────────────────────────────────────────────────────────
def test_sem_flag_a_entrada_e_a_de_sempre(monkeypatch):
    monkeypatch.setenv("JFN_CONFERENCIA_RISCO", "1")
    assert _enfileira(valor=2_000_000.0)
    assert _status(Q.conectar())[0] == "pendente"


def test_com_flag_valor_medio_vai_ao_sonnet_e_alto_ao_opus(monkeypatch):
    monkeypatch.setenv("JFN_CONFERENCIA_RISCO", "1")
    monkeypatch.setenv("JFN_CONFERENTE_SONNET", "1")
    assert _enfileira(item="sei:SEI-1/1/2025", valor=2_000_000.0, entrada="e1")
    assert _enfileira(item="sei:SEI-1/2/2025", valor=20_000_000.0, entrada="e2")
    assert _enfileira(item="sei:SEI-1/3/2025", valor=0.0, resposta=_exec("nao", 8), entrada="e3")
    con = Q.conectar()
    assert _status(con, "e1")[0] == CS.STATUS_SONNET
    assert _status(con, "e2")[0] == "pendente"
    assert _status(con, "e3")[0] == "pendente"                                   # 🔴 do motor vai direto
    assert Q.pendente("pericia_execucao", "sei:SEI-1/1/2025")                    # aguardando o Sonnet: aberto


# ── rodada do Sonnet ──────────────────────────────────────────────────────────────────────────────────────────
def _fila_sonnet(monkeypatch, entradas=("e1",)):
    monkeypatch.setenv("JFN_CONFERENCIA_RISCO", "1")
    monkeypatch.setenv("JFN_CONFERENTE_SONNET", "1")
    for i, e in enumerate(entradas):
        _enfileira(item=f"sei:SEI-1/{i + 1}/2025", valor=2_000_000.0, entrada=e)
    return Q.conectar()


def test_sonnet_concorda_fecha_mas_continua_nao_julgado(monkeypatch):
    ch = next(e for e in (f"x{i}" for i in range(200)) if not CS._sorteado(Q.chave_de("pericia_execucao", e)))
    con = _fila_sonnet(monkeypatch, (ch,))
    f = CS.conferir(5, pensar=_sonnet(_exec("parcial", 5)), con=con)
    assert f[0]["decisao"] == "fecha" and _status(con, ch)[0] == CS.STATUS_FECHADO
    assert Q.pendente("pericia_execucao", "sei:SEI-1/1/2025")       # régua do Sonnet não aprovada ⇒ nunca VERIFICADO
    from compliance_agent.llm import cruzamento
    c = cruzamento.conectar(somente_leitura=True)
    assert {m for (m,) in c.execute("SELECT modelo FROM veredito")} == {CS.MODELO, "groq"}


def test_sonnet_divergente_sobe_ao_opus_e_o_opus_o_ve(monkeypatch):
    monkeypatch.setenv("JFN_CONFERENTE_DIVERGENCIA", "qualquer")   # 24/11/2026 (D4): o padrão passou a `grave`
    ch = next(e for e in (f"y{i}" for i in range(200)) if not CS._sorteado(Q.chave_de("pericia_execucao", e)))
    con = _fila_sonnet(monkeypatch, (ch,))
    f = CS.conferir(5, pensar=_sonnet(_exec("sim", 1)), con=con)
    st, rsc = _status(con, ch)
    assert f[0]["decisao"] == "opus" and st == "pendente" and "sonnet_divergiu" in rsc
    vistos = []
    Q.conferir(5, pensar=lambda t, e, **k: vistos.append(e) or Pensamento(texto=_exec("sim", 1), modelo="claude-opus-5-5", segundos=1.0, tarefa=t),
               con=con, piso=False)
    assert vistos == [ch]


def test_divergencia_leve_no_modo_grave_fecha_e_aplica_o_sonnet(monkeypatch):
    monkeypatch.setenv("JFN_CONFERENTE_DIVERGENCIA", "grave")
    ch = next(e for e in (f"z{i}" for i in range(200)) if not CS._sorteado(Q.chave_de("pericia_execucao", e)))
    con = _fila_sonnet(monkeypatch, (ch,))
    aplicados = []
    monkeypatch.setattr(Q, "_aplicar", lambda *a: aplicados.append(a) or 1)
    f = CS.conferir(5, pensar=_sonnet(_exec("sim", 1)), con=con)
    assert f[0]["decisao"] == "fecha" and f[0]["aplicado"] == 1 and aplicados[0][3] == CS.MODELO


def test_sem_flag_a_rodada_nao_faz_nada_e_ritmo_contido_barra(monkeypatch):
    con = _fila_sonnet(monkeypatch)
    monkeypatch.delenv("JFN_CONFERENTE_SONNET")
    assert CS.conferir(5, pensar=_sonnet(_exec("parcial", 5)), con=con) == []
    monkeypatch.setenv("JFN_CONFERENTE_SONNET", "1")
    chamou = []
    r = CS.conferir(5, pensar=lambda *a, **k: chamou.append(1), con=con, ritmo=lambda t: "ritmo semanal — contido",
                    escolher=lambda: ("vm2", "ok"), executar_em=lambda e: None)
    assert r == [] and chamou == []


def test_sem_assinatura_para_sem_gastar_tentativa(monkeypatch):
    con = _fila_sonnet(monkeypatch)
    from compliance_agent.llm import claude_motor
    monkeypatch.setattr(claude_motor, "ultimo_motivo", "sem cota")
    assert CS.conferir(5, pensar=lambda *a, **k: None, con=con) == []
    assert con.execute("SELECT status, tentativas FROM fila").fetchone() == (CS.STATUS_SONNET, 0)


def test_regua_aprovada_tira_o_fechado_da_pendencia(tmp_path, monkeypatch):
    import copy

    import yaml
    ch = next(e for e in (f"w{i}" for i in range(200)) if not CS._sorteado(Q.chave_de("pericia_execucao", e)))
    con = _fila_sonnet(monkeypatch, (ch,))
    CS.conferir(5, pensar=_sonnet(_exec("parcial", 5)), con=con)
    ev = {"ouro": {"n": 125, "graves": 0, "sha256": "ab" * 32, "estratificado": True,
                   "estratos": {"processo": 1, "orgao": 1, "periodo": 1}},
          "sombra": {"dias": 14, "n": 30, "graves": 0}, "portoes": {p: True for p in RG.PORTOES}}
    doc = {"criterios": dict(RG.CRITERIOS), "propostas": [], "pares": [{
        "id": "R-CONF", "tarefa": CS.TAREFA, "modelo": CS.MODELO, "prompt_version": CS.PROMPT_VERSION,
        "release_ia": f"{CS.PROMPT_VERSION}+{CS.MODELO}", "estado": RG.APROVADO_DONO, "dono": "dono",
        "data": "2026-11-24", "motivo": "t", "evidencia": copy.deepcopy(ev)}]}
    (tmp_path / "regras_novas.yaml").write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    assert CS.regua_cumprida() and not Q.pendente("pericia_execucao", "sei:SEI-1/1/2025")


# ── simulação ─────────────────────────────────────────────────────────────────────────────────────────────────
def _itens():
    it = []
    for i in range(80):          # execução: 20 grave (Opus direto), 60 valor médio (Sonnet)
        it.append({"tarefa": "pericia_execucao", "item": f"sei:SEI-1/{i}/2025", "decisao": "fila",
                   "motivos": ["grave"] if i < 20 else ["valor"], "valor": 2_000_000.0})
    for i in range(20):          # integral: tudo ao Opus por padrão
        it.append({"tarefa": "pericia_integral", "item": f"sei:SEI-2/{i}/2025", "decisao": "fila",
                   "motivos": ["amostra"], "valor": 0.0})
    it.append({"tarefa": "pericia_execucao", "item": "sei:SEI-9/9/2025", "decisao": "nao_julgado", "motivos": [],
               "valor": 0.0})
    return it


def test_mix_e_simulacao_so_opus_bate_a_conta():
    mix = CS.mix_da_proposta(_itens())
    assert mix == {"pericia_execucao": {"retidos": 80, "opus_direto": 20},
                   "pericia_integral": {"retidos": 20, "opus_direto": 20}}
    cap = CS.capacidade_s(mix, 10)                                   # 10 conferências no tempo médio do mix
    assert cap == pytest.approx(10 * (0.8 * 26.6 + 0.2 * 210.0))
    r = CS.simular(mix, retidos_dia=100, cap_s=cap, peso_sonnet=0)
    assert r["opus_itens_dia"] == 100 and r["fracao_que_fecha"] == pytest.approx(0.1, abs=1e-3)


def test_sonnet_alivia_o_opus_e_corte_na_origem_soma():
    mix = CS.mix_da_proposta(_itens())
    cap = CS.capacidade_s(mix, 10)
    so = CS.simular(mix, retidos_dia=100, cap_s=cap, peso_sonnet=0)
    g = CS.simular(mix, retidos_dia=100, cap_s=cap, peso_sonnet=0.5, modo="grave")
    corte = CS.simular(mix, retidos_dia=100, cap_s=cap, peso_sonnet=0.5, modo="grave", sem=("pericia_integral",))
    assert g["opus_itens_dia"] < so["opus_itens_dia"] and g["sonnet_itens_dia"] == 60
    assert corte["retidos_dia"] == 80 and corte["fracao_que_fecha"] > g["fracao_que_fecha"]
    # 60 ao Sonnet: sobem 39/302 (grave) + 1/8 do resto; 20 direto
    sobe = 60 * 39 / 302
    assert g["opus_itens_dia"] == pytest.approx(round(20 + sobe + (60 - sobe) / 8 + 20, 1), abs=0.11)


def test_cenarios_e_semana_pelo_ritmo():
    cs = CS.cenarios(_itens(), entrada_dia=200, frac_retidos=0.5, caps=(10.0,), pesos=(1.0,))
    assert [c["cenario"] for c in cs] == ["S0", "S1", "S1", "S2", "S2", "S3", "S3", "S3-so-opus"]
    assert 7 < CS.capacidade_semanal_dias() < 8                       # sábado acima da linha vale < 1 dia
    assert all(c["fracao_que_fecha_semana"] >= c["fracao_que_fecha"] for c in cs)
