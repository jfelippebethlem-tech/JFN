# -*- coding: utf-8 -*-
"""E12/O6.5 — entrada por risco na fila do Opus, aplicador que falhava com OperationalError e piso de concordância.
Nenhum teste chama o `claude`, provedor ou o banco real (fila, compliance.db e cascata_ajuste em tmp_path)."""
import json
import sqlite3

import pytest

from compliance_agent.llm import cascata_ajuste as CA
from compliance_agent.llm import conferencia_opus as Q
from compliance_agent.llm import conferencia_risco as R
from compliance_agent.llm.claude_motor import Pensamento


@pytest.fixture(autouse=True)
def _isola(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CLAUDE_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("JFN_CONFERENCIA_DB", str(tmp_path / "conf.db"))
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))
    monkeypatch.setenv("JFN_CLAUDE_API", "0")
    for v in ("JFN_CONFERENCIA_RISCO", "JFN_CONFERENCIA_LIMIAR_VALOR", "JFN_CONFERENCIA_PROPAGAR",
              "JFN_CONFERENCIA_EXECUTOR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(Q, "RETENTAR_S", (0.0, 0.0))
    yield


def _exec(v, nota):
    return json.dumps({"execucao_comprovada": v, "nota_risco_execucao": nota})


def _item(i, **kw):
    base = {"id": i, "chave": f"c{i}", "tarefa": "pericia_execucao", "item": f"sei:SEI-1/{i}/2025", "motor": "groq",
            "nivel": 1, "baixa": False, "valor": 0.0, "valor_aplica": True, "divergente": False}
    return {**base, **kw}


# ── regra ────────────────────────────────────────────────────────────────────────────────────────────
def test_cada_motivo_mantem_na_fila_e_o_resto_vira_nao_julgado():
    itens = [_item(1, divergente=True), _item(2, valor=2_000_000.0), _item(3, nivel=2), _item(4, baixa=True),
             _item(5, valor=None)] + [_item(10 + k) for k in range(40)]
    R.classificar_lote(itens, limiar=1_000_000.0)
    por = {i["id"]: i for i in itens}
    assert por[1]["motivos"] == ["divergencia"] and por[2]["motivos"] == ["valor"]
    assert por[3]["motivos"] == ["grave"] and por[4]["motivos"] == ["baixa_confianca"]
    assert por[5]["motivos"] == ["valor_indeterminavel"]          # INDISPONÍVEL ≠ 0: na dúvida, entra
    resto = [i for i in itens if i["id"] >= 10]
    sorteio = [i for i in resto if i["motivos"] == ["amostra"]]
    assert 1 <= len(sorteio) < len(resto)                         # ~1/8, nunca zero no estrato
    assert all(i["decisao"] == R.NAO_JULGADO for i in resto if not i["motivos"])
    assert all(i["decisao"] == "fila" for i in itens if i["motivos"])


def test_negativo_valor_abaixo_do_limiar_e_nivel_1_nao_seguram_o_item():
    it = R.classificar_lote([_item(1, valor=999_999.99, chave="x")], limiar=1_000_000.0)[0]
    assert "valor" not in it["motivos"]
    assert R.motivos_do_item(nivel=1, baixa=False, valor=1_000_000.0, valor_aplica=True, divergente=False,
                             limiar=1_000_000.0) == ["valor"]       # limiar inclusivo


def test_amostra_e_estratificada_todo_estrato_tem_ao_menos_um():
    itens = [_item(k, motor="groq", nivel=0) for k in range(3)] + [_item(100 + k, motor="openrouter", nivel=0)
                                                                 for k in range(3)]
    R.classificar_lote(itens, limiar=1e12)
    for motor in ("groq", "openrouter"):
        assert any(i["motivos"] == ["amostra"] for i in itens if i["motor"] == motor)


def test_baixa_confianca_indeterminado_e_eixos_sem_grau():
    assert R.baixa_confianca("pericia_execucao", _exec("indeterminado", 4), "indeterminado/nota 4", 1)
    assert R.baixa_confianca("pericia_integral", "", "juri? plan? econ1 orca?", 1)
    assert not R.baixa_confianca("pericia_integral", "", "juri1 plan0 econ1 orca?", 1)
    assert R.baixa_confianca("x", "", None, None)
    assert not R.baixa_confianca("pericia_execucao", _exec("parcial", 6), "parcial/nota 6", 1)


def test_divergencia_exige_motores_e_niveis_diferentes():
    linhas = [("t", "a", "groq", 1), ("t", "a", "openrouter", 2), ("t", "b", "groq", 1), ("t", "b", "groq", 2),
              ("t", "c", "groq", 1), ("t", "c", "openrouter", 1)]
    assert R.divergentes(linhas) == {("t", "a")}


# ── sombra e aplicação ───────────────────────────────────────────────────────────────────────────────
def _fila_com(n_limpos=20):
    con = Q.conectar()
    Q.enfileirar("pericia_execucao", "sei:SEI-9/1/2025", "grave", motor="groq", resposta=_exec("nao", 9), con=con)
    Q.enfileirar("pericia_execucao", "sei:SEI-9/2/2025", "caro", motor="groq", resposta=_exec("parcial", 5), con=con)
    for k in range(n_limpos):
        Q.enfileirar("pericia_execucao", f"sei:SEI-9/{100 + k}/2025", f"limpo{k}", motor="groq",
                     resposta=_exec("sim", 1), con=con)
    return con


def test_sombra_nao_altera_a_fila_e_aplicar_respeita_a_chave(tmp_path):
    con = _fila_com()
    antes = con.execute("SELECT id, status FROM fila ORDER BY id").fetchall()
    valores = {f"SEI-9/{k}/2025": 0.0 for k in range(1, 120)} | {"SEI-9/2/2025": 5_000_000.0}   # consultados
    rel, itens = R.sombra(con, valores, limiar=1_000_000.0)
    assert con.execute("SELECT id, status FROM fila ORDER BY id").fetchall() == antes       # SOMBRA
    assert rel["pendentes"] == 22 and rel["por_motivo_principal"]["grave"] == 1
    assert rel["por_motivo_principal"]["valor"] == 1
    assert rel["ficam_na_fila"] + rel["viram_nao_julgado"] == 22 and rel["viram_nao_julgado"] > 0
    prop = R.gravar_proposta(tmp_path / "p.json", rel, itens)
    # a linha mudou de entrada depois da sombra: a proposta não a toca
    mudou = next(i for i in itens if i["decisao"] == R.NAO_JULGADO)
    con.execute("UPDATE fila SET chave='outra' WHERE id=?", (mudou["id"],))
    con.commit()
    n = R.aplicar(prop, con)
    assert n["ignorado"] == 1 and n["pendente"] == rel["ficam_na_fila"]
    assert con.execute("SELECT COUNT(*) FROM fila WHERE status='nao_julgado'").fetchone()[0] == rel["viram_nao_julgado"] - 1
    # NÃO JULGADO nunca é limpo: o consumidor continua vendo pendência, e o painel mostra o rótulo
    nj = con.execute("SELECT item FROM fila WHERE status='nao_julgado' LIMIT 1").fetchone()[0]
    assert Q.pendente("pericia_execucao", nj, con=con)
    p = Q.painel()
    assert p["nao_julgados"] == rel["viram_nao_julgado"] - 1 and p["rotulo_nao_julgado"] == "NÃO JULGADO — fila"
    # o Opus só puxa o que ficou pendente
    vistos = []
    Q.conferir(50, pensar=lambda t, e, **k: vistos.append(e) or Pensamento(texto=_exec("sim", 1),
               modelo="claude-opus-5-5", segundos=1.0, tarefa=t), con=con, piso=False)
    assert len(vistos) == rel["ficam_na_fila"] + 1                # +1: a linha cuja chave mudou ficou pendente


def test_entrada_por_risco_ligada_pela_variavel(monkeypatch):
    monkeypatch.setenv("JFN_CONFERENCIA_RISCO", "1")
    monkeypatch.setattr(R, "_valor_ob_de", lambda p: 0.0)
    con = Q.conectar()
    for k in range(30):
        Q.enfileirar("pericia_execucao", f"sei:SEI-8/{k}/2025", f"e{k}", motor="groq", resposta=_exec("sim", 1),
                     con=con)
    st = dict(con.execute("SELECT status, COUNT(*) FROM fila GROUP BY 1").fetchall())
    assert st.get("nao_julgado", 0) > 0 and 0 < st.get("pendente", 0) < 30          # só a amostra entra
    Q.enfileirar("pericia_execucao", "sei:SEI-8/99/2025", "g", motor="groq", resposta=_exec("nao", 9), con=con)
    assert con.execute("SELECT status, risco FROM fila WHERE item='sei:SEI-8/99/2025'").fetchone() == ("pendente", "grave")
    # outro motor dá outro nível para um item NÃO JULGADO: os dois voltam à fila
    nj = con.execute("SELECT item FROM fila WHERE status='nao_julgado' LIMIT 1").fetchone()[0]
    Q.enfileirar("pericia_execucao", nj, "outra entrada", motor="openrouter", resposta=_exec("parcial", 5), con=con)
    assert {s for (s,) in con.execute("SELECT status FROM fila WHERE item=?", (nj,))} == {"pendente"}


def test_negativo_sem_a_variavel_a_entrada_e_a_de_sempre():
    con = Q.conectar()
    for k in range(10):
        Q.enfileirar("pericia_execucao", f"sei:SEI-7/{k}/2025", f"e{k}", motor="groq", resposta=_exec("sim", 1),
                     con=con)
    assert con.execute("SELECT COUNT(*) FROM fila WHERE status='pendente'").fetchone()[0] == 10
    assert "risco" not in {r[1] for r in con.execute("PRAGMA table_info(fila)")}


def test_ob_paga_em_lote_pelo_indice_igual_a_por_processo():
    """Controle positivo e negativo: OB paga (grafias variantes) soma; não paga e de outro processo não."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE ob_orcamentaria_siafe(numero_ob, ug_emitente, data_emissao, status, status_envio, "
                "tipo_regularizacao, gd, processo, credor, nl, pd, valor)")
    con.execute("CREATE TABLE ob_reemitida(ob, ug)")
    linhas = [("2025OB1", "1", "01/01/2025", "Contabilizado", "", "", "", "SEI-120001/000010/2025", "c", "", "", 100.0),
              ("2025OB2", "1", "02/01/2025", "Contabilizado", "", "", "", "120001/10/25", "c", "", "", 50.0),
              ("2025OB3", "1", "03/01/2025", "Cancelado", "", "", "", "SEI-120001/000010/2025", "c", "", "", 999.0),
              ("2025OB4", "1", "04/01/2025", "Contabilizado", "", "", "", "SEI-120001/000011/2025", "c", "", "", 7.0)]
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", linhas)
    procs = ["SEI-120001/000010/2025"] + [f"SEI-120001/{900 + k:06d}/2025" for k in range(60)]   # > 50: lote
    v = R.ob_paga_por_processo(con, procs)
    assert v["SEI-120001/000010/2025"] == 150.0 and v["SEI-120001/000900/2025"] == 0.0
    assert R.ob_paga_por_processo(con, ["SEI-120001/000010/2025"])["SEI-120001/000010/2025"] == 150.0   # ≤ 50
    assert R.ob_paga_por_processo(con, ["sem número"]) == {"sem número": None}


# ── aplicador (OperationalError de 22/11/2026) ───────────────────────────────────────────────────────
def _opus_diverge(t, e, **k):
    return Pensamento(texto=_exec("nao", 9), modelo="claude-opus-5-5", segundos=1.0, tarefa=t)


def test_aplicador_com_banco_travado_tenta_de_novo_e_aplica(monkeypatch):
    tentativas = []

    def aplicador(item, resp, modelo, concorda):
        tentativas.append(1)
        if len(tentativas) < 3:
            raise sqlite3.OperationalError("database is locked")
        return True
    import types
    import sys
    monkeypatch.setitem(sys.modules, "falso_aplicador", types.SimpleNamespace(ap=aplicador))
    monkeypatch.setitem(Q.APLICADORES, "pericia_execucao", "falso_aplicador:ap")
    con = Q.conectar()
    Q.enfileirar("pericia_execucao", "sei:SEI-1/1/2025", "e", motor="groq", resposta=_exec("sim", 1), con=con)
    f = Q.conferir(1, pensar=_opus_diverge, con=con, piso=False)
    assert f[0]["aplicado"] == 1 and len(tentativas) == 3


def test_aplicador_que_falha_guarda_a_entrada_e_reaplicar_conclui(monkeypatch):
    import types
    import sys
    estado = {"falha": True}

    def aplicador(item, resp, modelo, concorda):
        if estado["falha"]:
            raise sqlite3.OperationalError("database is locked")
        return True
    monkeypatch.setitem(sys.modules, "falso_aplicador2", types.SimpleNamespace(ap=aplicador))
    monkeypatch.setitem(Q.APLICADORES, "pericia_execucao", "falso_aplicador2:ap")
    con = Q.conectar()
    Q.enfileirar("pericia_execucao", "sei:SEI-1/2/2025", "e", motor="groq", resposta=_exec("sim", 1), con=con)
    assert Q.conferir(1, pensar=_opus_diverge, con=con, piso=False)[0]["aplicado"] == 0
    # antes de 24/11 a entrada era apagada aqui e o veredito do Opus nunca chegava ao registro
    assert con.execute("SELECT status, aplicado, entrada IS NOT NULL FROM fila").fetchone() == ("conferido", 0, 1)
    estado["falha"] = False
    r = Q.reaplicar(10, con=con)
    assert r[0]["aplicado"] == 1
    assert con.execute("SELECT aplicado, entrada IS NULL FROM fila").fetchone() == (1, 1)
    assert Q.reaplicar(10, con=con) == []                         # nada mais a reaplicar


# ── piso de concordância ─────────────────────────────────────────────────────────────────────────────
def _conferidos(con, motor, n, concordou, tarefa="pericia_execucao"):
    for k in range(n):
        con.execute("INSERT INTO fila(chave,tarefa,item,motor,status,criado_em,concorda) VALUES(?,?,?,?,?,?,?)",
                    (f"{motor}{k}{tarefa}", tarefa, f"i{k}", motor, "conferido", "2026-11-24", int(k < concordou)))
    con.commit()


def test_piso_rebaixa_motor_abaixo_de_60_por_cento_na_tarefa(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CASCATA_AJUSTE", str(tmp_path / "ajuste.json"))
    con = Q.conectar()
    _conferidos(con, "gemini:gemini-3-flash-preview", 30, 10)     # 33% → rebaixa
    _conferidos(con, "openrouter", 30, 25)                        # 83% → fica
    _conferidos(con, "groq", 10, 0)                               # n < 20 → sem amostra, não age
    _conferidos(con, "cascata", 40, 5, tarefa="pericia_integral")   # agregado: não é um modelo
    _conferidos(con, "claude:claude-haiku-5-5@api", 40, 5)         # Claude pela API não é cascata
    abaixo = Q.aplicar_piso(con)
    assert [(c["tarefa"], c["modelo"]) for c in abaixo] == [("pericia_execucao", "gemini:gemini-3-flash-preview")]
    assert CA.rebaixados("pericia_execucao") == {"gemini:gemini-3-flash-preview"}
    assert not CA.rebaixados("pericia_integral")
    assert Q.aplicar_piso(con)[0]["novo"] is False                # idempotente


def test_piso_roda_ao_fim_da_rodada(monkeypatch):
    chamadas = []
    monkeypatch.setattr(Q, "aplicar_piso", lambda con, **k: chamadas.append(1) or [])
    con = Q.conectar()
    Q.enfileirar("pericia_execucao", "sei:SEI-1/3/2025", "e", motor="groq", resposta=_exec("sim", 1), con=con)
    Q.conferir(1, pensar=_opus_diverge, con=con)
    assert chamadas == [1]
