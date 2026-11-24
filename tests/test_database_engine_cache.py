# -*- coding: utf-8 -*-
"""O4.2(a) — um engine por (processo, arquivo), um listener de pragmas, e sessão que não cria schema.

DB-01 da auditoria de 24/11/2026: `get_engine` criava engine NOVO a cada chamada (e mais um listener),
e `get_session` rodava `create_all` a cada sessão. Schema agora é só de `init_db` explícito.
"""
from sqlalchemy import event, inspect, text

from compliance_agent.database import models


def test_mesmo_arquivo_mesmo_engine_e_arquivo_diferente_engine_diferente(tmp_path):
    a = tmp_path / "a.db"
    e1 = models.get_engine(str(a))
    e2 = models.get_engine(a)                       # str e Path resolvem para a mesma chave
    assert e1 is e2
    assert models.get_engine(tmp_path / "b.db") is not e1


def test_env_jfn_db_resolve_para_o_mesmo_engine(tmp_path, monkeypatch):
    db = tmp_path / "env.db"
    monkeypatch.setenv("JFN_DB", str(db))
    assert models.get_engine() is models.get_engine(str(db))


def test_listener_de_pragmas_registrado_uma_vez(tmp_path, monkeypatch):
    registros = []
    original = models.event.listen

    def _conta(alvo, nome, fn, *a, **k):
        registros.append((nome, fn))
        return original(alvo, nome, fn, *a, **k)

    monkeypatch.setattr(models.event, "listen", _conta)
    db = tmp_path / "p.db"
    for _ in range(5):
        engine = models.get_engine(db)
    nossos = [r for r in registros if r[1] is models._pragmas_sqlite]   # SQLAlchemy registra os dele também
    assert nossos == [("connect", models._pragmas_sqlite)]
    assert event.contains(engine, "connect", models._pragmas_sqlite)


def test_pragmas_aplicados_na_conexao(tmp_path):
    engine = models.get_engine(tmp_path / "w.db")
    with engine.connect() as c:
        assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert c.execute(text("PRAGMA busy_timeout")).scalar() == 30000
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_get_session_nao_cria_tabela_init_db_cria(tmp_path):
    db = tmp_path / "s.db"
    s = models.get_session(models.get_engine(db))
    s.close()
    assert inspect(models.get_engine(db)).get_table_names() == []
    models.init_db(str(db))
    assert "ordens_bancarias" in inspect(models.get_engine(db)).get_table_names()
