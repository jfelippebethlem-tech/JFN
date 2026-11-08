# -*- coding: utf-8 -*-
"""O PDF do 360 não pode entregar o MESMO documento julgado por rubricas diferentes.

Medido em 2026-08-02: `doc_veredito` tinha 1.084 linhas para 57 processos, com **50 processos
carregando veredito de 2 ou 3 rubricas** e **407 pares (numero_sei, doc_i) duplicados**. O
`_vereditos_persistidos` fazia `select ... where numero_sei=?` sem filtro de versão, então o
entregável mostrava o mesmo despacho três vezes — inclusive sob as rubricas v1 e v2, que o próprio
`doc_juizo` documenta como ERRADAS (v1 inflava "74% problemáticos"; v2 marcava escala 3 em parecer
que apenas aponta lacuna, "14 de 14 reprovados na releitura").

Regra: um documento, um juízo — o da rubrica MAIS NOVA em que ele foi avaliado.
"""
import json
import sqlite3

import pytest

from compliance_agent.reporting import processo_360_ctx as ctx

ESQUEMA = """
create table doc_veredito (
  id integer primary key autoincrement,
  numero_sei text, doc_i integer, tipo_canonico text, hash_texto text,
  rubrica_versao text, modelo text, escala integer, trecho_literal text,
  veredito_json text, grau text, avaliado_em text
)
"""


def _semear(db, linhas):
    con = sqlite3.connect(db)
    con.execute(ESQUEMA)
    con.executemany(
        "insert into doc_veredito (numero_sei, doc_i, rubrica_versao, escala, veredito_json,"
        " avaliado_em) values (?,?,?,?,?,?)", linhas)
    con.commit()
    con.close()


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "compliance.db"


def test_um_documento_um_juizo(db):
    """Mesmo doc_i julgado em v1, v2 e v3 → sai só o da v3."""
    _semear(db, [
        ("080002/009942/2026", 7, "1", 3, json.dumps({"i": 7, "escala": 3}), "2026-07-01"),
        ("080002/009942/2026", 7, "2", 3, json.dumps({"i": 7, "escala": 3}), "2026-07-20"),
        ("080002/009942/2026", 7, "3", 2, json.dumps({"i": 7, "escala": 2}), "2026-08-01"),
    ])
    out = ctx._vereditos_persistidos("080002/009942/2026", db=db)
    assert out is not None
    assert len(out["vereditos"]) == 1, "o entregável repetiu o mesmo documento"
    assert out["vereditos"][0]["escala"] == 2, "prevaleceu a rubrica retratada"


def test_versao_compara_como_numero_nao_como_texto(db):
    """Com rubrica v10 vs v9, a ordenação lexical escolheria a v9 — errado."""
    _semear(db, [
        ("P/1/2026", 1, "9", 3, json.dumps({"i": 1, "escala": 3}), "2026-07-01"),
        ("P/1/2026", 1, "10", 1, json.dumps({"i": 1, "escala": 1}), "2026-08-01"),
    ])
    out = ctx._vereditos_persistidos("P/1/2026", db=db)
    assert [v["escala"] for v in out["vereditos"]] == [1]


def test_mantem_todos_os_documentos_distintos_em_ordem(db):
    """Deduplicar por documento não pode encolher o processo: 3 docs continuam 3."""
    _semear(db, [
        ("P/2/2026", 3, "3", 1, json.dumps({"i": 3}), "2026-08-01"),
        ("P/2/2026", 1, "2", 2, json.dumps({"i": 1}), "2026-07-01"),
        ("P/2/2026", 1, "3", 2, json.dumps({"i": 1}), "2026-08-01"),
        ("P/2/2026", 2, "3", 3, json.dumps({"i": 2}), "2026-08-01"),
    ])
    out = ctx._vereditos_persistidos("P/2/2026", db=db)
    assert [v["i"] for v in out["vereditos"]] == [1, 2, 3]


def test_empate_de_rubrica_fica_com_a_avaliacao_mais_recente(db):
    """Recaptura na MESMA rubrica (hash novo) → vale a leitura mais nova, não a primeira."""
    _semear(db, [
        ("P/3/2026", 5, "3", 3, json.dumps({"i": 5, "escala": 3}), "2026-08-01T10:00"),
        ("P/3/2026", 5, "3", 1, json.dumps({"i": 5, "escala": 1}), "2026-08-02T10:00"),
    ])
    out = ctx._vereditos_persistidos("P/3/2026", db=db)
    assert [v["escala"] for v in out["vereditos"]] == [1]


def test_processo_sem_veredito_devolve_none(db):
    _semear(db, [])
    assert ctx._vereditos_persistidos("P/4/2026", db=db) is None
