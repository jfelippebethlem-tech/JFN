# -*- coding: utf-8 -*-
"""Task 1 — schema aditivo de emendas + gastos PCRJ."""
from compliance_agent.emendas import db as edb
from compliance_agent.pcrj import gastos_db

TABELAS_EMENDAS = {"emendas", "emenda_favorecidos", "emendas_pix_planos", "deputados_federais_rj"}
TABELAS_PCRJ = {"pcrj_despesa", "pcrj_contratos", "pcrj_licitacoes"}


def _tabelas(con):
    return {r[0] for r in con.execute("select name from sqlite_master where type='table'")}


def test_init_schema_cria_tabelas_e_e_idempotente(tmp_path):
    con = edb.conectar(tmp_path / "t.db")
    edb.init_schema(con); edb.init_schema(con)          # idempotente
    gastos_db.init_schema(con); gastos_db.init_schema(con)
    t = _tabelas(con)
    assert TABELAS_EMENDAS <= t and TABELAS_PCRJ <= t


def test_emendas_upsert_por_codigo(tmp_path):
    con = edb.conectar(tmp_path / "t.db"); edb.init_schema(con)
    row = dict(codigo="202544110010", ano=2025, autor_raw="LUCIANO VIEIRA",
               autor_norm="LUCIANO VIEIRA", autor_id_camara=None,
               tipo="Emenda Individual - Transferências com Finalidade Definida",
               e_pix=0, funcao="Saúde", subfuncao="Assistência hospitalar e ambulatorial",
               localidade_gasto="DUAS BARRAS - RJ", uf_destino="RJ", municipio_destino_ibge="3301603",
               empenhado=41161.0, liquidado=41161.0, pago=41161.0,
               resto_inscrito=0.0, resto_cancelado=0.0, resto_pago=0.0,
               recorte="DESTINO_RJ", fonte="portal_transparencia")
    edb.upsert_emenda(con, row); row["pago"] = 0.0; edb.upsert_emenda(con, row)
    got = con.execute("select count(*), max(pago) from emendas").fetchone()
    assert got[0] == 1 and got[1] == 0.0
