# -*- coding: utf-8 -*-
"""Mensagem com contagem que muda a cada rodada não pode virar um item novo por rodada (670 cópias de 7 temas)."""
from __future__ import annotations

import sqlite3

from tools import lex_feedback as F


def test_chave_atualiza_o_item_aberto_em_vez_de_inserir(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "DB", str(tmp_path / "c.db"))
    k = "Perícia: tema 'pesquisa de preços' "
    assert F.registrar("jfn", "dificuldade", "perícia SEI (loop de aprendizado)", k + "em 3 de 40.", chave=k)
    assert not F.registrar("jfn", "dificuldade", "perícia SEI (loop de aprendizado)", k + "em 5 de 41.", chave=k)
    rows = sqlite3.connect(tmp_path / "c.db").execute("SELECT mensagem FROM lex_feedback").fetchall()
    assert rows == [(k + "em 5 de 41.",)]


def test_sem_chave_segue_o_dedup_exato(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "DB", str(tmp_path / "c.db"))
    assert F.registrar("lex", "ideia", "x", "a")
    assert not F.registrar("lex", "ideia", "x", "a")
    assert F.registrar("lex", "ideia", "x", "b")
