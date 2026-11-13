# -*- coding: utf-8 -*-
"""Triagem dos alertas da Ronda — banco sintético em tmp, co-motor com Claude e cascata dublês."""
import json
import sqlite3

import pytest

from compliance_agent import triagem_alertas as T
from compliance_agent.llm import comotor as CM
from compliance_agent.llm.claude_motor import Pensamento


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("JFN_CRUZAMENTO_DB", str(tmp_path / "cruz.db"))
    c = sqlite3.connect(tmp_path / "c.db")
    c.execute("CREATE TABLE alertas(id INTEGER PRIMARY KEY, tipo TEXT, severidade TEXT, titulo TEXT, "
              "descricao TEXT, evidencias TEXT, status TEXT)")
    linhas = [
        (1, "acumulacao", "alta", "Emprego múltiplo", "d", json.dumps({"cpf": "12345678901", "total_bruto": 30000.0}), "novo"),
        (2, "direcionamento", "baixa", "OB empresa nova", "d", json.dumps({"valor": 5_000_000.0}), "novo"),
        (3, "pcrj_d7_fracionamento", "media", "Fracionamento", "d", json.dumps({"soma": 200_000.0}), "novo"),
        (4, "x", "baixa", "json torto", "d", "{nao é json", "novo"),
        (5, "direcionamento", "alta", "já confirmado", "d", json.dumps({"valor": 9e9}), "confirmado"),
    ]
    c.executemany("INSERT INTO alertas VALUES(?,?,?,?,?,?,?)", linhas)
    c.commit()
    yield c
    c.close()


def _gerar(resp_claude, resp_casc):
    prompts = []

    def pensar(t, p, **kw):
        prompts.append(p)
        return Pensamento(texto=resp_claude, modelo="claude-sonnet-5-5", segundos=1, tarefa=t) if resp_claude else None
    g = CM.juizo("triagem_alertas", pensar=pensar, cascata=lambda *a, **k: resp_casc, sorteio=lambda: 1.0)
    g.prompts = prompts
    return g


def test_prioriza_por_valor_ignora_nao_novos_e_json_torto(con):
    ids = [a["id"] for a in T.selecionar(con, 10)]
    assert ids == [2, 3, 1, 4]


def test_lote_pequeno_grava_triagem_sem_mudar_status(con):
    ok = json.dumps({"prioridade": "aprofundar", "nota": 8, "justificativa": "campo valor", "proximo_passo": "NF"})
    g = _gerar(ok, json.dumps({"prioridade": "monitorar", "nota": 5}))
    feitos = T.triar_lote(con, 2, gerar=g)
    assert [f["id"] for f in feitos] == [2, 3]
    assert all(f["prioridade"] == "aprofundar" and f["motor"].startswith("claude:") for f in feitos)
    assert con.execute("SELECT COUNT(*) FROM alertas WHERE status='novo'").fetchone()[0] == 4
    assert [a["id"] for a in T.selecionar(con, 10)] == [1, 4]       # triados não voltam


def test_cpf_vai_mascarado_no_prompt(con):
    g = _gerar(json.dumps({"prioridade": "monitorar", "nota": 3}), "{}")
    T.triar_lote(con, 3, gerar=g)
    assert not any("12345678901" in p for p in g.prompts)


def test_resposta_fora_da_rubrica_vira_nao_avaliavel():
    assert T.interpretar('{"prioridade":"culpado","nota":10}')["prioridade"] == "nao_avaliavel"
    assert T.interpretar('{"prioridade":"monitorar","nota":42}')["nota"] is None


def test_sem_claude_cai_na_cascata_e_marca_o_motor(con):
    g = _gerar(None, json.dumps({"prioridade": "provavel_falso_positivo", "nota": 2}))
    f = T.triar_lote(con, 1, gerar=g)[0]
    assert f["prioridade"] == "provavel_falso_positivo" and f["motor"] == "cascata"


def test_motor_fora_nao_aborta_o_lote(con):
    def explode(*a, **k):
        raise RuntimeError("tudo fora")
    assert T.triar_lote(con, 3, gerar=explode) == []
