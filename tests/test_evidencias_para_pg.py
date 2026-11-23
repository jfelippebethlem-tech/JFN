# -*- coding: utf-8 -*-
"""tools/evidencias_para_pg.py contra um SQLite temporário e o PostgreSQL de `JFN_EVIDENCIAS_DSN`, num ESQUEMA
temporário criado e apagado pelo teste (nunca as tabelas reais). Sem o DSN, pula."""
import os
import sqlite3
import sys
import uuid
from pathlib import Path

import pytest

from compliance_agent import evidencias as E
from compliance_agent import leitura_integral as L

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import evidencias_para_pg as M  # noqa: E402

DSN = os.environ.get(E.ENV_DSN, "")
pytestmark = pytest.mark.skipif(not DSN.startswith(("postgresql://", "postgres://")),
                                reason="sem JFN_EVIDENCIAS_DSN (PostgreSQL)")


@pytest.fixture()
def esquema():
    import psycopg
    from psycopg import sql
    nome = f"tmp_evid_teste_{uuid.uuid4().hex[:10]}"
    pg = psycopg.connect(DSN, autocommit=True)
    pg.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(nome)))
    try:
        yield nome, pg
    finally:
        pg.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(nome)))
        pg.close()


def _sqlite(caminho: Path) -> None:
    con = E.conectar(caminho)
    con.executescript(L._DDL)
    with con:
        for k in range(12):
            E.enfileirar(con, "ocr", f"doc:{k}")
            con.execute("INSERT INTO processos VALUES(?,?,?,?)", (f"P{k}", "t", "a", "b"))
            con.execute("INSERT INTO fatos(processo, doc_id, tipo, valor, citacao, estado, payload_sha, em) "
                        "VALUES(?,?,?,?,?,?,?,?)", (f"P{k}", "sei:1", "valor", "1.00", "R$\x00 1,00", "VERIFICADO",
                                                    f"s{k % 3}", "x"))
        con.execute(L._UPSERT_LEITURA, ("P1", "leitura_integral", "li-2", 10, 10, 1.0, "integral", 1, "l", "x"))
        con.execute(L._INS_DOC_LIDO, ("sha1", "li-2", "P1", "sei:1", "l", "x"))
    con.close()


def test_copia_idempotente_confere_contagem_e_avanca_a_sequencia(tmp_path, esquema, capsys):
    nome, pg = esquema
    db = tmp_path / "ev.db"
    _sqlite(db)
    antes = db.read_bytes()
    argv = ["--sqlite", str(db), "--lote", "5", "--esquema", nome]
    assert M.main(argv) == 0
    assert M.main(argv) == 0                                              # de novo: nada duplica
    out = capsys.readouterr().out
    from psycopg.conninfo import conninfo_to_dict
    senha = conninfo_to_dict(DSN).get("password")
    assert "OK: contagens iguais nas 9 tabelas" in out and (not senha or senha not in out)
    pg.execute(f"SET search_path TO {nome}")
    assert pg.execute("SELECT COUNT(*) FROM fatos").fetchone()[0] == 12
    assert pg.execute("SELECT citacao FROM fatos WHERE id=1").fetchone()[0] == "R$ 1,00"   # NUL removido
    idx = {r[0] for r in pg.execute("SELECT indexname FROM pg_indexes WHERE schemaname=%s", (nome,))}
    assert {"ix_fatos_sha", "ix_fatos_proc", "ix_jobs_fila"} <= idx
    # sequência avançada: a próxima inserção do app não colide com os ids copiados
    novo = pg.execute("INSERT INTO fatos(processo, doc_id, estado, em) VALUES('P', 'd', 'X', 'x') RETURNING id")
    assert novo.fetchone()[0] == 13
    assert M.main(argv) == 1                                              # PG com linha a mais ⇒ diverge ⇒ sai 1
    assert db.read_bytes() == antes                                       # SQLite intocado


def test_leitura_integral_e_pericia_leem_do_pg(tmp_path, esquema, monkeypatch):
    """Os mesmos caminhos de escrita/leitura (upsert, ON CONFLICT DO NOTHING, leitores da perícia) no PostgreSQL."""
    from compliance_agent import pericia_integral as PI
    nome, pg = esquema
    dsn_esquema = DSN + ("&" if "?" in DSN else "?") + f"options=-csearch_path%3D{nome}"
    monkeypatch.setenv(E.ENV_DSN, dsn_esquema)
    con = L._con()
    try:
        with con:
            for _ in range(2):                                                 # upsert: 2ª vez substitui, não duplica
                con.execute(L._UPSERT_LEITURA, ("100001/000001/2025", "leitura_integral", "li-2", 9, 9, 1.0,
                                                "integral", 1, "lote", "2026-11-23 12:00:00"))
            con.executemany(L._INS_DOC_LIDO, [("s", "li-2", "p", "d", "l", "x")] * 2)
            con.execute("INSERT INTO fatos(processo, doc_id, tipo, valor, descricao, citacao, estado, versao, em) "
                        "VALUES(?,?,?,?,?,?,?,?,?)", ("100001/000001/2025", "sei:8", "data", "2025-01-02",
                                                      "assinatura", "02/01/2025", "VERIFICADO", "li-2", "x"))
        assert con.execute("SELECT COUNT(*) FROM leituras").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM docs_lidos").fetchone()[0] == 1
    finally:
        con.close()
    texto, info = PI._bloco_fatos("SEI-100001/000001/2025")
    assert info["linha_do_tempo"] == 1 and info["leitura_integral"] == "integral" and "02/01/2025" in texto
