# -*- coding: utf-8 -*-
"""A cobertura da perícia documental tem de estar VISÍVEL — ninguém sabia que era 39 de 2.082.

Pedido do dono em 2026-08-03: as perícias de todos os SEI rodando 24/7 e surfadas no painel. O
primeiro requisito de "rodando" é poder ver quanto já rodou: até aqui o número só existia se
alguém abrisse o SQLite. Um painel que não mostra a cobertura deixa a impressão de que o acervo
inteiro foi periciado quando 98% dele nunca recebeu juízo documental.

Honestidade: a rota devolve o número medido, nunca uma estimativa — e diz QUEM julgou (a cadeia
de LLM), porque a procedência do veredito é o que permite auditar uma queda de qualidade depois.
"""
import sqlite3

import pytest

from compliance_agent.reporting import cobertura_pericia as C

ESQUEMA = """
create table processo_avaliacao (numero_sei text primary key, score100 real);
create table doc_veredito (id integer primary key autoincrement, numero_sei text, doc_i integer,
  rubrica_versao text, modelo text, escala integer, avaliado_em text);
"""


@pytest.fixture()
def db(tmp_path):
    caminho = tmp_path / "c.db"
    con = sqlite3.connect(caminho)
    con.executescript(ESQUEMA)
    con.executemany("insert into processo_avaliacao values (?,?)",
                    [(f"P/{i}/2026", 50.0) for i in range(10)])
    con.executemany(
        "insert into doc_veredito (numero_sei, doc_i, rubrica_versao, modelo, escala, avaliado_em)"
        " values (?,?,?,?,?,?)",
        [("P/0/2026", 1, "3", "gemini+cerebras", 2, "2026-08-03"),
         ("P/0/2026", 2, "3", "gemini+cerebras", 3, "2026-08-03"),
         ("P/1/2026", 1, "3", "cadeia_gratis", 1, "2026-08-01"),
         ("P/2/2026", 1, "2", "cadeia_gratis", 3, "2026-07-01")])  # rubrica VELHA: não conta
    con.commit()
    con.close()
    return caminho


def test_cobertura_mede_o_que_existe(db):
    r = C.medir(db=db, rubrica="3")
    assert r["processos_avaliados"] == 10
    assert r["processos_com_juizo"] == 2, "processo com veredito de rubrica velha não está coberto"
    assert r["documentos_julgados"] == 3
    assert r["pct"] == pytest.approx(20.0)


def test_diz_quem_julgou(db):
    r = C.medir(db=db, rubrica="3")
    assert r["por_cadeia"] == {"gemini+cerebras": 2, "cadeia_gratis": 1}


def test_distribuicao_de_escala_e_publicada(db):
    """Sem a distribuição, '3 documentos julgados' não diz se algum é problemático."""
    assert C.medir(db=db, rubrica="3")["por_escala"] == {"1": 1, "2": 1, "3": 1}


def test_base_ausente_devolve_indisponivel_e_nao_zero(tmp_path):
    r = C.medir(db=tmp_path / "nao_existe.db", rubrica="3")
    assert r["indisponivel"] is True
    assert r.get("pct") is None, "0% afirmaria cobertura nula onde não houve medição"


def test_denominador_e_o_PERICIAVEL_nao_o_total(tmp_path):
    """Processo cuja captura não dá para avaliar não está pendente de PERÍCIA, está pendente de
    CAPTURA — duas filas, donos diferentes. Somá-las mostrava 2.174 pendentes quando 234 deles
    não têm texto para julgar, fazendo o número da perícia parecer pior do que é e sumindo com a
    razão real do atraso. A fila da captura tem cartão próprio (`/api/captura/cobertura`).
    """
    import sqlite3
    from compliance_agent.reporting import cobertura_pericia as CP
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.executescript("""
        create table processo_avaliacao (numero_sei text primary key, score100 real, faixa text);
        create table doc_veredito (id integer primary key autoincrement, numero_sei text,
          doc_i integer, rubrica_versao text, modelo text, escala integer, avaliado_em text);
    """)
    con.executemany("insert into processo_avaliacao values (?,?,?)",
                    [(f"P{i}", 10.0, "ALTO") for i in range(8)]
                    + [(f"N{i}", 0.0, "NAO_AVALIAVEL") for i in range(2)])
    con.execute("insert into doc_veredito(numero_sei, doc_i, rubrica_versao, modelo, escala,"
                " avaliado_em) values ('P0',0,'3','x',1,'2026-01-01')")
    con.commit(); con.close()

    r = CP.medir(db=db, rubrica="3")
    assert r["processos_avaliados"] == 10
    assert r["processos_periciaveis"] == 8 and r["processos_sem_captura"] == 2
    assert r["processos_pendentes"] == 7, "pendente é sobre o periciável, não sobre o total"
    assert r["pct"] == 12.5, "1 de 8 periciáveis — não 1 de 10"


def test_esquema_sem_a_coluna_faixa_nao_derruba_a_medicao():
    """Perder a separação das duas filas é aceitável; perder a MEDIÇÃO por uma coluna, não."""
    import sqlite3
    from compliance_agent.reporting import cobertura_pericia as CP
    import pathlib
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp()) / "v.db"
    con = sqlite3.connect(d)
    con.executescript("""
        create table processo_avaliacao (numero_sei text primary key, score100 real);
        create table doc_veredito (id integer primary key autoincrement, numero_sei text,
          doc_i integer, rubrica_versao text, modelo text, escala integer, avaliado_em text);
    """)
    con.execute("insert into processo_avaliacao values ('P0', 1.0)")
    con.commit(); con.close()
    r = CP.medir(db=d, rubrica="3")
    assert r["indisponivel"] is False and r["processos_periciaveis"] == 1
