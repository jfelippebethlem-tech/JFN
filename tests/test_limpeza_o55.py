# -*- coding: utf-8 -*-
"""Limpeza O5.5 (tools/limpeza_o55.py) sobre bancos sintéticos: ensaio não escreve, aplicar é reversível e
idempotente, desfazer não pisa mudança posterior, amostra E12 determinística; P1 fraco fora do score do 360."""
from __future__ import annotations

import json
import sqlite3

import pytest

from tools import limpeza_o55 as L

_MASC = "XX123456XXX"          # CPF mascarado como a folha publica (nunca um CPF inteiro em fixture)


def _compliance(p):
    con = sqlite3.connect(p)
    con.executescript("""
        CREATE TABLE alertas (id INTEGER PRIMARY KEY, tipo TEXT, severidade TEXT, titulo TEXT, descricao TEXT,
                              evidencias TEXT, status TEXT, created_at TEXT);
        CREATE TABLE alertas_triagem (alerta_id INTEGER PRIMARY KEY, prioridade TEXT, estado TEXT,
                                      opus_pendente INTEGER DEFAULT 0, motivo TEXT);
        CREATE TABLE pericia_integral (id INTEGER PRIMARY KEY, rodada TEXT, processo TEXT, eixo TEXT, grau INTEGER,
                                       modelo TEXT, valor_pago REAL, conferido_opus INTEGER DEFAULT 0, criado_em TEXT);
        CREATE TABLE processo_avaliacao (numero_sei TEXT PRIMARY KEY, achados_json TEXT);
    """)
    ev_parcial = json.dumps({"cpf": _MASC, "nome": "FULANA", "n_orgaos": 2})
    rows = [
        (1, "acumulacao", "alta", "Emprego múltiplo suspeito — CPF XX1XXX", "", "{}", "descartado", "2026-09-26"),
        (2, "acumulacao", "alta", "Emprego múltiplo suspeito — CPF XX2XXX", "", "{}", "descartado", "2026-09-26"),
        (3, "acumulacao", "média", "Emprego múltiplo a verificar — FULANA", "", ev_parcial, "novo", "2026-11-13"),
        (4, "acumulacao", "média", "Emprego múltiplo a verificar — BELTRANA", "",
         json.dumps({"cpf": _MASC, "nome": "B", "matricula": "123"}), "novo", "2026-11-13"),
        (5, "fracionamento", "alta", "Fracionamento OB credor A", "", "{}", "novo", "2026-11-24"),
        (6, "fracionamento", "alta", "Fracionamento OB credor B", "", "{}", "descartado", "2026-11-19"),
        (7, "emendas_d3_favorecido_sancionado", "alta", "D3 x", "", "{}", "novo", "2026-11-22"),
        (8, "acumulacao", "alta", "Emprego múltiplo a verificar — antigo", "", "{}", "descartado", "2026-09-26"),
    ]
    con.executemany("INSERT INTO alertas VALUES (?,?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO alertas_triagem VALUES (?,?,?,?,?)",
                    [(3, "monitorar", "PENDENTE", 1, None), (5, "aprofundar", "PENDENTE", 1, None),
                     (7, "monitorar", "PENDENTE", 1, None)])
    per = []
    for i in range(1, 41):          # 40 processos: grau 2 em 30, com motores e valores variados
        grau = 2 if i <= 30 else 1
        modelo = "agente Claude Code (Opus)" if i % 10 == 0 else ("gemini:x" if i % 2 else "openrouter:y")
        per.append((i, f"r{i}", f"P{i:03d}", "_global", grau, modelo, i * 1e5, 1 if i == 29 else 0, "2026-11-20"))
    con.executemany("INSERT INTO pericia_integral VALUES (?,?,?,?,?,?,?,?,?)", per)
    con.execute("INSERT INTO processo_avaliacao VALUES ('X', ?)", (json.dumps([{"codigo": "P1", "diz": "x"}]),))
    con.commit()
    return con


def _achados(p):
    con = sqlite3.connect(p)
    con.execute("""CREATE TABLE achado_certame (certame TEXT, detector TEXT, orgao_cnpj TEXT, score REAL,
                   status TEXT, motivo TEXT, explicacao_inocente TEXT, valores TEXT, evidencia TEXT, gerado_em TEXT,
                   PRIMARY KEY (certame, detector))""")
    v0 = json.dumps({"desconto_pct": 0.0})
    con.executemany("INSERT INTO achado_certame VALUES (?,?,?,?,?,?,?,?,?,?)", [
        ("C1", "J3", "o", 0.6, "confirmado", "m", "", v0, "[]", "2026-07-28T12:32:53"),
        ("C2", "J2", "o", 0.85, "confirmado", "m", "", "{}", "[]", "2026-07-28T12:32:54"),
        ("C3", "J3", "o", 0.6, "confirmado", "m", "", v0, "[]", "2026-11-24T09:54:59"),   # reavaliado: fica
        ("C4", "J4", "o", 0.6, "confirmado", "m", "", "{}", "[]", "2026-07-28T12:32:54"),  # outro detector: fica
        ("C5", "J3", "o", 0.0, "descartado", "m", "", "{}", "[]", "2026-07-28T12:32:54"),  # não confirmado: fica
    ])
    con.commit()
    return con


@pytest.fixture
def bancos(tmp_path):
    c, a = tmp_path / "c.db", tmp_path / "a.db"
    _compliance(c).close()
    _achados(a).close()
    return c, a


def _status(p, tabela="alertas", chave="id"):
    con = sqlite3.connect(p)
    try:
        return dict(con.execute(f"SELECT {chave}, status FROM {tabela}"))  # noqa: S608
    finally:
        con.close()


def test_identidade_parcial():
    assert L.identidade_parcial(json.dumps({"cpf": _MASC, "nome": "A"}))
    assert not L.identidade_parcial(json.dumps({"cpf": _MASC, "nome": "A", "matricula": "9"}))
    assert not L.identidade_parcial(json.dumps({"cpf": "", "nome": "A"}))
    assert not L.identidade_parcial("isto não é json")


def test_ensaio_nao_escreve(bancos, capsys):
    c, a = bancos
    antes = (_status(c), _status(a, "achado_certame", "certame||detector"))
    assert L.main(["--db", str(c), "--db-achados", str(a)]) == 0
    assert (_status(c), _status(a, "achado_certame", "certame||detector")) == antes
    con = sqlite3.connect(c)
    assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='limpeza_registro'").fetchone()
    out = json.loads(capsys.readouterr().out)
    assert out["modo"] == "ensaio"
    assert out["alvos"]["1"]["mudancas"] == 2 and out["alvos"]["3"]["mudancas"] == 2


def test_aplicar_reversivel_e_idempotente(bancos):
    c, a = bancos
    L.main(["--db", str(c), "--db-achados", str(a), "--aplicar", "--alvo", "1", "--alvo", "2", "--alvo", "3",
            "--alvo", "4"])
    st = _status(c)
    assert st[1] == st[2] == "arquivado"                 # alvo 1
    assert st[8] == "descartado"                         # título atual da regra: não é zumbi
    assert st[5] == st[6] == "arquivado"                 # alvo 2 (novo e descartado)
    assert st[3] == "em_revisao" and st[4] == "novo"     # alvo 4: só a identidade parcial
    assert st[7] == "novo"                               # outro detector intacto
    con = sqlite3.connect(c)
    assert dict(con.execute("SELECT alerta_id, opus_pendente FROM alertas_triagem")) == {3: 0, 5: 0, 7: 1}
    reg = con.execute("SELECT DISTINCT autor FROM limpeza_registro").fetchall()
    assert reg == [("limpeza-O5.5",)]
    assert con.execute("SELECT COUNT(*) FROM limpeza_registro WHERE motivo='' OR motivo IS NULL").fetchone()[0] == 0
    assert con.execute("SELECT estado_saida FROM limpeza_registro WHERE chave='[3]' AND campo='status'"
                       ).fetchone() == ("INCERTO",)
    n_reg = con.execute("SELECT COUNT(*) FROM limpeza_registro").fetchone()[0]
    assert n_reg == 2 + 2 + 1 + 1 + 1                   # alvo1 2 · alvo2 2+1 triagem · alvo4 1+1 triagem
    ach = _status(a, "achado_certame", "certame")
    assert ach == {"C1": "arquivado", "C2": "arquivado", "C3": "confirmado", "C4": "confirmado", "C5": "descartado"}

    # idempotente: 2ª corrida não troca nada nem duplica o registro
    for alvo in (1, 2, 4):
        assert L.aplicar(con, L.selecionar(alvo, con, None)) == 0
    assert con.execute("SELECT COUNT(*) FROM limpeza_registro").fetchone()[0] == n_reg
    con.close()

    # desfazer devolve o estado anterior, mas não pisa quem mudou depois
    con = sqlite3.connect(c)
    con.execute("UPDATE alertas SET status='confirmado' WHERE id=5")      # decisão humana posterior
    con.commit()
    r = L.desfazer(con, aplicar_=True)
    assert r["conflitos"] == 1
    st = _status(c)
    assert st[1] == st[2] == "descartado" and st[3] == "novo" and st[6] == "descartado"
    assert st[5] == "confirmado"
    assert dict(con.execute("SELECT alerta_id, opus_pendente FROM alertas_triagem")) == {3: 1, 5: 1, 7: 1}
    con.close()
    ca = sqlite3.connect(a)
    L.desfazer(ca, aplicar_=True)
    assert _status(a, "achado_certame", "certame")["C1"] == "confirmado"


def test_desfazer_em_ensaio_nao_escreve(bancos):
    c, _ = bancos
    con = sqlite3.connect(c)
    L.aplicar(con, L.selecionar(1, con))
    assert L.desfazer(con)["desfeitos"] == 2
    assert _status(c)[1] == "arquivado"


def test_amostra_e12_estratificada_e_deterministica(bancos):
    c, _ = bancos
    con = sqlite3.connect(c)
    a1, a2 = L.amostra_e12(con, n=10), L.amostra_e12(con, n=10)
    assert a1 == a2
    assert a1["vermelhos"] == 30
    assert a1["ja_conferidos_opus"] == 1 and a1["escritos_pelo_opus"] == 3
    assert a1["universo_sorteio"] == 26
    procs = [x["processo"] for x in a1["amostra"]]
    assert len(procs) == len(set(procs)) == 10
    assert "P029" not in procs and "P010" not in procs and "P020" not in procs
    assert {x["motor"] for x in a1["amostra"]} == {"gemini", "openrouter"}
    assert all(e["cota"] >= 1 for e in a1["estratos"].values())


def test_medir_p1(bancos):
    c, a = bancos
    assert L.medir_p1(sqlite3.connect(c), sqlite3.connect(a))["processo_avaliacao_com_P1"] == 1


def test_p1_fraco_fora_do_score_processo():
    from compliance_agent.detectores.base import ResultadoDetector, score_processo
    from compliance_agent.processo_360 import entra_no_score

    def rd(det, s):
        return ResultadoDetector(detector=det, processo="x", score=s, status="confirmado")

    fraco, forte, outro = rd("P1", 0.3), rd("P1", 0.85), rd("E7", 0.3)
    assert not entra_no_score(fraco)
    assert entra_no_score(forte) and entra_no_score(outro)
    assert entra_no_score(ResultadoDetector(detector="P1", processo="x", score=0.3, status="descartado"))
    assert score_processo([r for r in (fraco,) if entra_no_score(r)]) == 0.0


def test_painel_nao_conta_arquivado(tmp_path):
    from compliance_agent.periodo_fontes import _alertas_itens
    con = _compliance(tmp_path / "p.db")
    con.execute("UPDATE alertas SET status='arquivado' WHERE id=5")
    itens = {i["nome"]: i["n"] for i in _alertas_itens(con, 2026, 11)}
    assert "fracionamento" not in itens and itens.get("acumulacao") == 2
