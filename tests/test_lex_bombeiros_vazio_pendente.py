# -*- coding: utf-8 -*-
"""Bombeiros: veredito VAZIO é pendência, não "feito" — e o aprofundado tem de responder com o modelo vivo.

Medido em 11/11/2026: `bombeiros_lex.out` dizia "periciados nesta passada: 0" na imensa maioria das passadas,
porque `lex_bombeiros.py` considerava feito TODO `numero_sei` presente em `lex_execucao`, inclusive os NULL —
diferente do `_alvos` canônico, que refaz vazio após 7 dias (cura de 29/10). E o aprofundado trocou o
`deepseek-v4-pro` (410 Gone em 09/11) pelo nemotron-3.5-super-vl do catálogo, mas sem desligar o raciocínio:
com max_tokens 1500 o nemotron pensa tudo e devolve `content` vazio (medido 09/11) — a linha vazia era gravada
e contava como feita (5 linhas, todas "indeterminado").
"""
from __future__ import annotations

import json
import sqlite3
import sys

import pytest

import tools.lex_execucao as L


@pytest.fixture(autouse=True)
def _sem_memoria_real(monkeypatch):
    """`A.main()` chama `L._regras_calibracao`, que abre a memória pelo ORM e CRIA `data/compliance.db` (+WAL)
    quando ele não existe. No CI (11/11/2026, run 43074074836) esse arquivo semeado no lote 1 fazia ~14 testes
    dos lotes seguintes, que abrem a base real "se existir", morrerem com `file is not a database`/`disk I/O
    error`. Mesma cura de `test_lex_execucao_ob_siafe` (29/10/2026)."""
    monkeypatch.setattr(L, "_regras_calibracao", lambda: "(teste)")


class _SemFechar:
    """O `main()` fecha a conexão no finally — o teste precisa lê-la depois."""

    def __init__(self, con):
        self._c = con

    def __getattr__(self, k):
        return getattr(self._c, k)

    def close(self):
        return None


def _db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE sei_ficha (numero_sei TEXT, objeto TEXT, valores TEXT, documentos TEXT, "
                "red_flags TEXT, n_docs INT)")
    con.execute("CREATE TABLE lex_execucao (numero_sei TEXT PRIMARY KEY, execucao_comprovada TEXT, "
                "nota_risco INT, em TEXT)")
    for ns, n in (("SEI-270001/1/2025", 9), ("SEI-270001/2/2025", 8), ("SEI-270001/3/2025", 7)):
        con.execute("INSERT INTO sei_ficha VALUES (?,?,?,?,?,?)", (ns, "obj", "", "[]", "[]", n))
    # 1 = veredito válido · 2 = vazio antigo (volta) · 3 = vazio de hoje (espera os 7 dias)
    con.execute("INSERT INTO lex_execucao VALUES ('SEI-270001/1/2025','sim',2,'2026-10-01T00:00:00')")
    con.execute("INSERT INTO lex_execucao VALUES ('SEI-270001/2/2025',NULL,NULL,'2026-10-01T00:00:00')")
    con.execute("INSERT INTO lex_execucao VALUES ('SEI-270001/3/2025',NULL,NULL,"
                "strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))")
    return con


def test_bombeiros_refaz_o_vazio_antigo_e_pula_o_valido(monkeypatch, capsys):
    import tools.lex_bombeiros as B
    con = _SemFechar(_db())
    monkeypatch.setattr(L, "_con", lambda: con)
    feitos = []
    monkeypatch.setattr(L, "avaliar_processo", lambda c, ns, *a, **k: feitos.append(ns) or None)
    monkeypatch.setattr(sys, "argv", ["lex_bombeiros", "--max", "10"])
    B.main()
    assert feitos == ["SEI-270001/2/2025"], "vazio antigo volta; válido e vazio recente não"
    assert "periciados nesta passada: 1" in capsys.readouterr().out


def test_aprofundado_desliga_o_raciocinio_do_nemotron(monkeypatch):
    import tools.lex_bombeiros_aprofundado as A
    enviado = {}

    class _R:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 9}}

    monkeypatch.setattr(A, "_envk", lambda *a: "k")
    monkeypatch.setattr(A.httpx, "post", lambda url, headers=None, json=None, timeout=None:
                        enviado.update(json) or _R())
    A._gerar_deepseek("p", "s")
    assert "deepseek" not in enviado["model"], "deepseek-v4-pro deu 410 Gone em 09/11/2026"
    assert enviado["chat_template_kwargs"] == {"enable_thinking": False}


def test_aprofundado_vazio_nao_grava_e_volta_a_fila(monkeypatch, tmp_path):
    import tools.lex_bombeiros_aprofundado as A
    con = _SemFechar(sqlite3.connect(":memory:"))
    con.execute("CREATE TABLE sei_ficha (numero_sei TEXT, objeto TEXT, valores TEXT, documentos TEXT, "
                "red_flags TEXT, n_docs INT)")
    con.execute("INSERT INTO sei_ficha VALUES ('SEI-270001/9/2025','o','','[]','[]',3)")
    fila = tmp_path / "fila.json"
    fila.write_text(json.dumps([{"sei": "SEI-270001/9/2025", "score": 5, "flags": []}]), encoding="utf-8")
    monkeypatch.setattr(A, "FILA", str(fila))
    monkeypatch.setattr(A, "_con", lambda: con)
    con.execute("""CREATE TABLE lex_aprofundado (numero_sei TEXT PRIMARY KEY, objeto TEXT,
        execucao_comprovada TEXT, coerencia TEXT, nota_risco INTEGER, indicios TEXT, duvidas TEXT, resumo TEXT,
        modelo TEXT, em TEXT, lat_s REAL, tokens INTEGER)""")
    # linha vazia antiga (as 5 de 27/06) NÃO conta como feita
    con.execute("INSERT INTO lex_aprofundado(numero_sei, execucao_comprovada) VALUES ('SEI-270001/9/2025', NULL)")
    assert [x[1] for x in A._alvos(con, 5, False)] == ["SEI-270001/9/2025"]
    con.execute("DELETE FROM lex_aprofundado")
    monkeypatch.setattr(A, "_cap_ok", lambda p: True)
    monkeypatch.setattr(A, "_cap_inc", lambda p: None)
    monkeypatch.setattr(A, "_load_env", lambda: None)
    monkeypatch.setattr(A, "_gerar_deepseek", lambda p, s: ("", 1500))
    monkeypatch.setattr(sys, "argv", ["x", "--top", "1"])
    A.main()
    assert con.execute("select count(*) from lex_aprofundado").fetchone()[0] == 0, \
        "resposta vazia não é veredito: não grava"
