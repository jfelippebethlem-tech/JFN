# -*- coding: utf-8 -*-
"""C6 — memória de veredito (não re-acusar o refutado)."""
from compliance_agent.editais import db as ed
from compliance_agent.enxame import memoria


def _seed(con):
    con.execute("""create table if not exists memoria_aprendizado (id integer primary key,
        categoria text, chave text, valor text, confianca real, n_observacoes int,
        fonte text, primeira_vez text, ultima_vez text)""")
    con.commit()


def test_registrar_e_recuperar(tmp_path):
    con = ed.conectar(tmp_path / "t.db"); _seed(con)
    memoria.registrar_veredito(con, "contrato_aditivo", "11222333000181", "refutado: dentro do limite", 3)
    memoria.registrar_veredito(con, "contrato_aditivo", "11222333000181", "refutado: idem", 3)
    row = con.execute("select n_observacoes from memoria_aprendizado "
                      "where categoria='contrato_aditivo' and chave='11222333000181'").fetchone()
    assert row[0] == 2
    ctx = memoria.contexto_memoria(con, "contrato_aditivo", "11222333000181")
    assert "refutado" in ctx.lower() and "2" in ctx


def test_contexto_vazio(tmp_path):
    con = ed.conectar(tmp_path / "t.db"); _seed(con)
    assert memoria.contexto_memoria(con, "contrato_aditivo", "99") == ""
