"""Laudo dado antes da recaptura do processo volta à perícia (18/11/2026) — com as salvaguardas."""
import os
import sqlite3
import time

from tools import lex_execucao as LX


def _base(tmp_path, monkeypatch, linhas, revistos=None):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE lex_execucao (numero_sei TEXT, nota_risco INT, execucao_comprovada TEXT, modelo TEXT, em TEXT)")
    con.executemany("INSERT INTO lex_execucao VALUES (?,?,?,?,?)", linhas)
    for ns, *_ in linhas:
        d = tmp_path / ns.replace("SEI-", "").replace("/", "_")
        d.mkdir()
        (d / "manifest.json").write_text("{}")
        agora = time.time()
        os.utime(d / "manifest.json", (agora, agora))
    monkeypatch.setattr(LX, "_ARQUIVO_SEI", tmp_path)
    monkeypatch.setattr(LX, "_revistos_sem_doc", lambda: revistos or {})
    return con


def test_laudo_antigo_de_risco_com_recaptura_volta(tmp_path, monkeypatch):
    con = _base(tmp_path, monkeypatch, [("SEI-080002/000001/2024", 8, "parcial", "gemini", "2026-06-01T10:00:00-03:00")])
    assert LX._recapturados(con) == ["SEI-080002/000001/2024"]


def test_conferido_a_mao_baixo_risco_e_revisto_depois_ficam_fora(tmp_path, monkeypatch):
    con = _base(tmp_path, monkeypatch, [
        ("SEI-080002/000002/2024", 8, "parcial", "claude:x (agente Claude Code, conferência na fonte)", "2026-06-01T10:00:00"),
        ("SEI-080002/000003/2024", 3, "sim", "gemini", "2026-06-01T10:00:00"),
        ("SEI-080002/000004/2024", 9, "nao", "gemini", "2026-06-01T10:00:00"),
        ("SEI-080002/000005/2024", 9, "nao", "gemini", "2099-01-01T00:00:00"),
    ], revistos={"SEI-080002/000004/2024": "2099-01-01T00:00:00-03:00"})
    assert LX._recapturados(con) == []
