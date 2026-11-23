# -*- coding: utf-8 -*-
"""llm_trace grava a TAREFA (estágio) de cada chamada — linha de base de tokens por estágio (plano de reescrita,
Fase 0d, 23/11/2026). Base antiga sem a coluna é migrada no lugar, sem perder linha."""
import sqlite3

from compliance_agent.llm import free_llm


def test_grava_tarefa_do_ambiente(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(db))
    monkeypatch.setenv("JFN_LLM_TAREFA", "pericia_integral")
    free_llm._trace("gemini", True, 10, modelo="m", tokens_in=100, tokens_out=5)
    assert sqlite3.connect(db).execute("SELECT tarefa, tokens_in FROM llm_trace").fetchall() == [("pericia_integral", 100)]


def test_sem_ambiente_usa_o_script(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(db))
    monkeypatch.delenv("JFN_LLM_TAREFA", raising=False)
    monkeypatch.setattr("sys.argv", ["/home/ubuntu/JFN/tools/sei_ficha_acervo.py", "--x"])
    free_llm._trace("nous", False, 10, "erro")
    assert sqlite3.connect(db).execute("SELECT tarefa FROM llm_trace").fetchone() == ("sei_ficha_acervo",)


def test_base_antiga_migra_sem_perder_linha(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE llm_trace(ts TEXT DEFAULT (datetime('now')), provedor TEXT, ok INT, ms INT, erro TEXT)")
    con.execute("INSERT INTO llm_trace(provedor, ok, ms, erro) VALUES('groq', 1, 5, '')")
    con.commit(); con.close()
    monkeypatch.setenv("JFN_LLM_TRACE_DB", str(db))
    monkeypatch.setenv("JFN_LLM_TAREFA", "lex_execucao")
    free_llm._trace("gemini", True, 7)
    assert sqlite3.connect(db).execute("SELECT provedor, tarefa FROM llm_trace ORDER BY rowid").fetchall() == \
        [("groq", None), ("gemini", "lex_execucao")]
