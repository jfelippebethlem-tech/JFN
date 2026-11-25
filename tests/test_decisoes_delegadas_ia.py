# -*- coding: utf-8 -*-
"""Decisões delegadas de 24/11/2026 (~/vault/refatoracao/decisoes-delegadas-ia-20261124.md), itens D3–D6.

D3 perícia integral fora da fila do Opus NA ORIGEM (o E11 não gera contingência; a cascata vira "NÃO JULGADO —
proposta"; sombra + aplicar dos pendentes) · D4 conferente Sonnet: padrões da religação pela simulação + protocolo de
medição do peso (não roda antes de 28/11 19h) · D5 o E12 grava a ORIGEM do conferido e o E13 só estratifica amostra/
cota · D6 2º revisor do ouro por IA independente, cego ao 1º rótulo, NUNCA rotulado humano. Nenhuma chamada de LLM:
todo `pensar` é dublê."""
import json
import sqlite3
import zlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from compliance_agent.llm import conferencia_opus as CO
from compliance_agent.llm import conferente_sonnet as CS
from compliance_agent.llm import integral_fora_da_fila as IF


@pytest.fixture
def fila(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CONFERENCIA_DB", str(tmp_path / "conf.db"))
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "dados"))
    for v in ("JFN_CONFERENCIA_RISCO", "JFN_CONFERENTE_SONNET", "JFN_INTEGRAL_NA_FILA", "JFN_CONFERENTE_DIVERGENCIA",
              "JFN_CONFERENTE_TAREFAS"):
        monkeypatch.delenv(v, raising=False)
    con = CO.conectar()
    yield con
    con.close()


def _p(texto="ok", modelo="claude-opus-5-5"):
    return NS(texto=texto, modelo=modelo)


# ── D3: perícia integral fora da fila na origem ─────────────────────────────────────────────────────────────
def test_integral_da_cascata_vira_proposta_visivel_e_nunca_verificado(fila):
    assert CO.enfileirar("pericia_integral", "sei:SEI-1/2026", "entrada", motor="gemini", resposta="r", con=fila)
    st, rsc = fila.execute("SELECT status, risco FROM fila").fetchone()
    assert (st, rsc) == (CO.PROPOSTA, IF.MOTIVO)
    assert CO.pendente("pericia_integral", "sei:SEI-1/2026", con=fila)          # nunca VERIFICADO
    chamado = []
    assert CO.conferir(4, pensar=lambda *a, **k: chamado.append(a) or _p(), con=fila, piso=False) == []
    assert chamado == []                                                       # o Opus não relê
    assert CO.ROTULO_PROPOSTA == "NÃO JULGADO — proposta"


def test_execucao_continua_na_fila_e_o_corte_se_desfaz_por_variavel(fila, monkeypatch):
    CO.enfileirar("pericia_execucao", "sei:SEI-2/2026", "e2", motor="gemini", resposta="r", con=fila)
    monkeypatch.setenv("JFN_INTEGRAL_NA_FILA", "1")
    CO.enfileirar("pericia_integral", "sei:SEI-3/2026", "e3", motor="gemini", resposta="r", con=fila)
    assert sorted(r[0] for r in fila.execute("SELECT status FROM fila")) == ["pendente", "pendente"]


def test_painel_conta_as_propostas(fila, monkeypatch, tmp_path):
    CO.enfileirar("pericia_integral", "sei:SEI-4/2026", "e4", motor="gemini", resposta="r", con=fila)
    fila.commit()
    p = CO.painel()
    assert p["propostas"] == 1 and p["rotulo_proposta"] == CO.ROTULO_PROPOSTA


def test_e11_nunca_entra_na_fila_do_opus():
    from compliance_agent.aplicacao.estagios import periciar as E11
    laudo = {"eixos": {"execucao": {"estado": "PROPOSTA"}}, "cobertura": {"fracao": 0.5}, "grau_global": 2,
             "ob_paga": 50_000_000.0, "chave": "k"}
    m = E11.motivos_e12(laudo)
    assert m["entra"] is False and "grave" in m["motivos"] and "assinatura" in m["fora_da_fila"]


def test_juiz_do_e11_sem_assinatura_nao_gera_contingencia(monkeypatch):
    from compliance_agent.adaptadores.llm import gateway as G
    from compliance_agent.aplicacao.estagios import periciar as E11
    monkeypatch.setattr(E11, "motivo_assinatura", lambda con_fluxo=None: None)
    monkeypatch.setattr(G, "chamar", lambda *a, **k: (_ for _ in ()).throw(G.SemProvedor("sem cota", [])))
    monkeypatch.setattr(CO, "enfileirar", lambda *a, **k: pytest.fail("o E11 não pode gerar item de contingência"))
    assert E11.juiz_assinatura()("s", "i", []) is None


def _semear(con, linhas):
    for i, (tarefa, status, criado) in enumerate(linhas, 1):
        con.execute("INSERT INTO fila(chave, tarefa, item, entrada, motor, resposta, status, criado_em) "
                    "VALUES(?,?,?,?,?,?,?,?)", (f"c{i}", tarefa, f"sei:SEI-{i}/2026", zlib.compress(b"x"), "gemini",
                                                "r", status, criado))
    con.commit()


def test_sombra_e_aplicar_dos_pendentes(fila, tmp_path):
    _semear(fila, [("pericia_integral", "pendente", "2026-11-20T10:00:00"),
                   ("pericia_integral", "pendente", "2026-11-21T10:00:00"),
                   ("pericia_execucao", "pendente", "2026-11-21T11:00:00"),
                   ("pericia_execucao", "conferido", "2026-11-22T11:00:00")])
    risco = [{"id": 3, "chave": "c3", "tarefa": "pericia_execucao", "item": "sei:SEI-3/2026", "decisao": "fila",
              "motivos": ["grave"], "valor": 2e6, "nivel": 2},
             {"id": 1, "chave": "c1", "tarefa": "pericia_integral", "item": "sei:SEI-1/2026", "decisao": "fila",
              "motivos": ["valor"], "valor": 3e6, "nivel": 1}]
    rel, itens = IF.sombra(fila, risco, hoje=datetime(2026, 11, 24).date())
    assert rel["pendentes"] == 3 and rel["viram_proposta"] == 2 and rel["ficam_na_fila"] == 1
    assert rel["entrada_por_dia"] == {"pericia_integral": 0.2, "pericia_execucao": 0.2}
    assert rel["vazao"]["entrada_dia_depois"] == 0.2 and rel["vazao"]["cenarios"]
    assert [r[0] for r in fila.execute("SELECT status FROM fila ORDER BY id")] == \
        ["pendente", "pendente", "pendente", "conferido"]                       # sombra não altera a fila
    prop = IF.gravar(tmp_path / "p.json", rel, itens)
    fila.execute("UPDATE fila SET chave='mudou' WHERE id=2")                    # entrada mudou depois da sombra
    fila.commit()
    assert IF.aplicar(prop, fila) == {CO.PROPOSTA: 1, "ignorado": 1}
    assert [r[0] for r in fila.execute("SELECT status FROM fila ORDER BY id")] == \
        [CO.PROPOSTA, "pendente", "pendente", "conferido"]


# ── D5: origem do conferido no E12 e no E13 ─────────────────────────────────────────────────────────────────
def test_origem_pura():
    assert CO.origem_do_conferido("amostra", sorteio_zero=False) == "amostra"
    assert CO.origem_do_conferido("cota", sorteio_zero=False) == "cota"
    assert CO.origem_do_conferido("valor,amostra", sorteio_zero=False) == "risco"
    assert CO.origem_do_conferido("grave", sorteio_zero=False) == "risco"
    assert CO.origem_do_conferido(None, sorteio_zero=False) == "prioridade"
    assert CO.origem_do_conferido("amostra", sorteio_zero=True) == "amostra_zero"


def test_conferir_grava_a_origem_de_cada_conferido(fila):
    CO.garantir_origem(fila)
    for i, (rsc, nivel) in enumerate([("amostra", 1), ("cota", 1), ("grave", 2), (None, 1),
                                      (None, 0), (None, 0), (None, 0), (None, 0), (None, 0)], 1):
        fila.execute("INSERT INTO fila(chave, tarefa, item, entrada, motor, resposta, status, criado_em, nivel, risco) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?)", (f"o{i}", "investigacao_risco", f"x:{i}", zlib.compress(b"e"),
                                                     "gemini", "r", "pendente", "2026-11-20T10:00:00", nivel, rsc))
    fila.commit()
    risco = json.dumps({"risco": "baixo", "citacao": "", "justificativa": "ok"})   # tarefa com régua, sem aplicador
    feitos = CO.conferir(8, pensar=lambda *a, **k: _p(risco), con=fila, piso=False)
    por = {f["id"]: f["origem"] for f in feitos}
    assert por[1] == "amostra" and por[2] == "cota" and por[3] == "risco" and por[4] == "prioridade"
    assert list(por.values()).count("amostra_zero") == 1                        # 1 vaga de 8 sorteada entre ⚪
    gravadas = dict(fila.execute("SELECT id, origem FROM fila WHERE status='conferido'").fetchall())
    assert gravadas == por


@pytest.fixture
def triagem(tmp_path, monkeypatch):
    from compliance_agent import triagem_alertas as T
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "dados"))
    monkeypatch.delenv("JFN_TRIAGEM_COTA", raising=False)
    c = sqlite3.connect(tmp_path / "c.db")
    c.execute("CREATE TABLE alertas(id INTEGER PRIMARY KEY, tipo TEXT, severidade TEXT, titulo TEXT, descricao TEXT, "
              "evidencias TEXT, status TEXT, data_referencia TEXT, created_at TEXT)")
    T.garantir(c)
    for i in range(1, 21):
        tipo = "det_a" if i <= 10 else "det_b"
        c.execute("INSERT INTO alertas VALUES(?,?,?,?,?,?,?,?,?)", (i, tipo, "media", f"alerta {i}", "descrição do caso",
                                                                    json.dumps({"processo": f"P{i}"}), "novo",
                                                                    "2026-05-01", "2026-05-01"))
        # 1–6 e 11–16 esperam o Opus (🟡); o resto a triagem julgou falso e não iria ao Opus pela fila
        pend = int(i <= 6 or 11 <= i <= 16)
        c.execute("INSERT INTO alertas_triagem(alerta_id, prioridade, motor, valor, opus_pendente) VALUES(?,?,?,?,?)",
                  (i, "monitorar" if pend else "provavel_falso_positivo", "gemini", float(i), pend))
    c.commit()
    yield T, c
    c.close()


def _opus_triagem(t, p, **k):
    return NS(texto=json.dumps({"prioridade": "monitorar", "nota": 5, "citacao": "descrição do caso",
                                "justificativa": "j", "proximo_passo": "p"}), modelo="claude-opus-5-5")


def test_triagem_grava_origem_amostra_estratificada_e_risco(triagem):
    T, c = triagem
    feitos = T.verificar_com_opus(c, 8, pensar=_opus_triagem, avisar=lambda *_: None)
    origens = [f["origem"] for f in feitos]
    assert len(feitos) == 8 and origens.count("amostra") == 1 and origens.count("risco") == 7
    gravado = dict(c.execute("SELECT alerta_id, origem_conferencia FROM alertas_triagem WHERE verificado_por IS NOT NULL"))
    assert sorted(gravado.values()) == sorted(origens)
    assert T.amostra_estratificada(c, 2) and len({c.execute("SELECT tipo FROM alertas WHERE id=?", (a,)).fetchone()[0]
                                                  for a in T.amostra_estratificada(c, 2)}) == 2   # um por detector


def test_triagem_cota_entra_com_origem_cota(triagem, tmp_path, monkeypatch):
    T, c = triagem
    monkeypatch.setattr(T, "AMOSTRA_A_CADA", 100)                              # sem vaga de amostra neste teste
    p = tmp_path / "cota.json"
    p.write_text(json.dumps({"cota": {"det_b": 2}, "candidatos": {"det_b": ["alerta:15", "alerta:16"]}}))
    monkeypatch.setenv("JFN_TRIAGEM_COTA", str(p))
    feitos = T.verificar_com_opus(c, 8, pensar=_opus_triagem, avisar=lambda *_: None)
    assert {f["id"] for f in feitos if f["origem"] == "cota"} == {15, 16}


def test_e13_le_a_origem_e_so_amostra_ou_cota_estratifica(triagem):
    from compliance_agent.aplicacao.estagios import calibrar as CAL
    T, c = triagem
    T.verificar_com_opus(c, 8, pensar=_opus_triagem, avisar=lambda *_: None)
    conf = CAL.conferidos_triagem(c)
    assert {x["origem"] for x in conf} == {"amostra", "risco"}
    assert CAL.origem_de("qualquer_coisa") == "legado" and CAL.origem_de(None) == "legado"
    base = {"detector": "d", "falso": False, "grave": False, "revisor": "claude-opus-5-5"}
    for org in ("risco", "prioridade", "amostra_zero", "legado"):
        m = CAL.medir([{**base, "item": f"i{i}", "origem": org} for i in range(40)])
        assert m["estratificada"] is False and m["n_estratificado"] == 0, org
    m = CAL.medir([{**base, "item": f"a{i}", "origem": "amostra" if i % 2 else "cota"} for i in range(30)])
    assert m["estratificada"] is True and m["n"] == 30


# ── D4: conferente Sonnet pronto para a religação ───────────────────────────────────────────────────────────
def test_sonnet_padroes_da_religacao_saem_da_simulacao(monkeypatch):
    monkeypatch.delenv("JFN_CONFERENTE_SONNET", raising=False)
    monkeypatch.delenv("JFN_CONFERENTE_DIVERGENCIA", raising=False)
    monkeypatch.delenv("JFN_CONFERENTE_TAREFAS", raising=False)
    assert CS.ativo() is False                                                 # pronta, não ligada
    assert CS.TAREFAS_PADRAO == CS.tarefas_com_ganho() == ("pericia_execucao",)
    assert CS.modo_divergencia() == "grave"
    assert all(CS.custo_relativo("pericia_execucao", "grave", w) < 1 for w in CS.PESOS_AVALIADOS)
    assert CS.custo_relativo("pericia_execucao", "qualquer", 1.0) > 1                # no `qualquer` não há ganho
    monkeypatch.setenv("JFN_CONFERENTE_DIVERGENCIA", "qualquer")
    assert CS.modo_divergencia() == "qualquer"


def test_protocolo_do_peso_nao_roda_antes_da_virada_nem_contido():
    from tools import medir_peso_sonnet as MP
    antes = datetime(2026, 11, 28, 18, 59, tzinfo=timezone(timedelta(hours=-3)))
    assert any("antes de" in m for m in MP.precondicoes(antes, nivel=lambda: {"medido": True, "nivel": "normal"}))
    depois = datetime(2026, 11, 28, 19, 1, tzinfo=timezone(timedelta(hours=-3)))
    assert MP.precondicoes(depois, nivel=lambda: {"medido": True, "nivel": "normal"}) == []
    assert MP.precondicoes(depois, nivel=lambda: {"medido": True, "nivel": "contido", "motivo": "m"})
    assert MP.precondicoes(depois, nivel=lambda: {"medido": False})


def test_protocolo_do_peso_plano_nao_chama_nada(monkeypatch, capsys):
    from compliance_agent.llm import claude_motor as CMo
    from tools import medir_peso_sonnet as MP
    monkeypatch.setattr(CMo, "pensar", lambda *a, **k: pytest.fail("o plano não chama a assinatura"))
    monkeypatch.setattr(MP, "precondicoes", lambda *a, **k: ["antes de 28/11"])
    assert MP.main(["--plano"]) == 0 and "Protocolo D4" in capsys.readouterr().out
    assert MP.main(["--executar"]) == 2


def test_protocolo_do_peso_abba_com_dubles(fila, monkeypatch):
    from tools import medir_peso_sonnet as MP
    for i in range(5):
        fila.execute("INSERT INTO fila(chave, tarefa, item, entrada, motor, resposta, status, criado_em) "
                     "VALUES(?,?,?,?,?,?,?,?)", (f"k{i}", "pericia_execucao", f"sei:{i}", zlib.compress(b"entrada"),
                                                 "gemini", "r", "pendente", "2026-11-20T10:00:00"))
    fila.commit()
    cont = {"sessao": 10.0, "semana": 5.0}
    ordem = []

    def pensar(tarefa, prompt, *, modelo, **k):
        ordem.append(tarefa)
        cont["sessao"] += 1.0 if "sonnet" in modelo else 2.0
        return NS(texto="ok", modelo=modelo)

    def buscar():
        return {"five_hour": {"utilization": cont["sessao"], "resets_at": "2026-11-29T00:00:00+00:00"},
                "seven_day": {"utilization": cont["semana"], "resets_at": "2026-12-05T22:00:00+00:00"}}
    r = MP.executar(5, pensar=pensar, buscar=buscar, con=fila, dormir=lambda s: None)
    assert [b["modelo"] for b in r["blocos"]] == ["sonnet", "opus", "opus", "sonnet"]
    assert all(b["delta_sessao"] >= MP.MIN_DELTA for b in r["blocos"])
    assert [b["itens"] for b in r["blocos"]] == [3, 2, 2, 3]                  # para no Δ ≥ 3 pontos


def test_peso_puro_com_intervalo_da_resolucao():
    from tools import medir_peso_sonnet as MP
    blocos = [{"modelo": "sonnet", "delta_sessao": 3, "segundos": 60, "itens": 3},
              {"modelo": "opus", "delta_sessao": 6, "segundos": 60, "itens": 2}]
    p = MP.peso(blocos, "sessao")
    assert p["peso_por_segundo"] == 0.5 and p["intervalo_resolucao"] == [round((2 / 60) / (7 / 60), 3),
                                                                         round((4 / 60) / (5 / 60), 3)]
    assert MP.peso([{**blocos[0], "delta_sessao": 0}, blocos[1]], "sessao")["peso_por_segundo"] is None


# ── D6: 2º revisor do ouro por IA independente, não humana ──────────────────────────────────────────────────
def _fonte_ouro(tmp_path):
    db = tmp_path / "fonte.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE alertas(id INTEGER PRIMARY KEY, tipo TEXT, severidade TEXT, titulo TEXT, descricao TEXT, "
              "evidencias TEXT, status TEXT, data_referencia TEXT, created_at TEXT)")
    c.execute("CREATE TABLE alertas_triagem(alerta_id INTEGER PRIMARY KEY, prioridade TEXT, leitura_opus TEXT, "
              "verificado_por TEXT, em TEXT)")
    for i in range(1, 61):
        c.execute("INSERT INTO alertas VALUES(?,?,?,?,?,?,?,?,?)", (i, "emendas_d2", "media", f"Concentração {i}",
                                                                    "autor concentra emendas no município",
                                                                    json.dumps({"processo": f"P-{i}"}), "novo",
                                                                    "2026-05-01", "2026-05-01"))
        c.execute("INSERT INTO alertas_triagem VALUES(?,?,?,?,?)",
                  (i, "monitorar", "provavel_falso_positivo" if i % 3 == 0 else "monitorar", "claude-opus-5-5",
                   "2026-11-20"))
    c.commit()
    c.close()
    return db


def test_ouro_preparar_e_cego_ao_primeiro_rotulo(tmp_path):
    from tools import ouro_revisao_ia as OR
    lote = OR.preparar(str(_fonte_ouro(tmp_path)))
    assert lote["itens"] and lote["reservados"] == len(lote["itens"]) + len(lote["sem_texto"])
    for it in lote["itens"]:
        assert it["rotulo_1"] in ("falso", "verdadeiro")
        for vazado in ("provavel_falso_positivo", "monitorar", "claude-opus", "leitura_opus"):
            assert vazado not in it["texto"]
    vistos = []
    OR.rodar({"itens": lote["itens"][:2]}, pensar=lambda t, p, **k: vistos.append((p, k)) or NS(
        texto=json.dumps({"rotulo": "verdadeiro", "citacao": "autor concentra emendas", "justificativa": "j"}),
        modelo="claude-opus-5-5"))
    assert len(vistos) == 2 and all("1º" not in p and "revisor anterior" not in p and "falso_positivo" not in p
                                    for p, _ in vistos)
    assert all(k["backend"] == "cli" and "revisor" not in k["sistema"].lower().replace("revisor independente", "")
               for _, k in vistos)                                              # só a assinatura; sistema cego


def test_ouro_interpretar_confere_a_citacao():
    from tools import ouro_revisao_ia as OR
    txt = "ALERTA #1 — autor concentra emendas no município"
    ok = OR.interpretar(json.dumps({"rotulo": "falso", "citacao": "autor concentra emendas", "justificativa": "j"}), txt)
    assert ok["rotulo"] == "falso"
    ruim = OR.interpretar(json.dumps({"rotulo": "falso", "citacao": "trecho inventado pelo modelo", "j": 1}), txt)
    assert ruim["rotulo"] == "indeterminado" and "citação" in ruim["motivo"]
    assert OR.interpretar("lixo", txt)["rotulo"] == "indeterminado"


def test_ouro_kappa_rotulado_como_ia_e_nunca_humano():
    from compliance_agent.qualidade import ouro
    from tools import ouro_revisao_ia as OR
    itens = [{"detector": "d", "item": f"alerta:{i}", "rotulo_1": "falso" if i < 4 else "verdadeiro",
              "revisor_1": "claude-opus-5-5"} for i in range(10)]
    resp = {f"alerta:{i}": {"rotulo": ("falso" if i < 3 else "verdadeiro") if i != 9 else "indeterminado"}
            for i in range(10)}
    rel = OR.kappa({"itens": itens}, resp)
    assert rel["rotulo"] == "REVISÃO POR IA INDEPENDENTE — NÃO HUMANA" and "HUMANO" in rel["aviso"]
    g = rel["geral"]
    assert g["pareados"] == 9 and g["indeterminados_ia"] == 1 and g["kappa"] == ouro.kappa_cohen(
        ["falso"] * 4 + ["verdadeiro"] * 5, ["falso"] * 3 + ["verdadeiro"] * 6)
    assert rel["por_1o_revisor"]["1o_revisor_humano (IA × humano)"]["itens"] == 0
    rot = OR.rotulos_ia({"itens": itens}, resp, "2026-11-29")
    assert rot and not any(ouro._humano(r.revisor) for r in rot)
    opus1 = [ouro.Rotulo(detector="d", item=i["item"], rotulo=i["rotulo_1"], revisor="claude-opus-5-5",
                         rotulado_em="2026-11-20") for i in itens]
    est = ouro.estado_revisao_tier1(opus1 + rot, "d")
    assert est["pronto"] is False and est["pendencia"] == "pendente_2o_revisor"  # 2 IAs ≠ revisor humano
