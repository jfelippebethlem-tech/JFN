# -*- coding: utf-8 -*-
"""O4.2(b)(c) — Alembic no compliance.db: base no-op, stamp com trava do legado, boot exige head.

DB-02 da auditoria de 24/11/2026: o runner caseiro gravava em `_alembic_version` (homônima, não era
Alembic), migração que falhava era impressa e o boot SEGUIA, e `_sync_columns` fazia ALTER automático
engolindo falha. Todos os bancos aqui são temporários — nada toca o compliance.db vivo.
"""
import ast
import asyncio
import re
import sqlite3

import pytest
from sqlalchemy import inspect

from compliance_agent.database import migrar, models

pytest.importorskip("alembic")

BASE = migrar.PASTA_ALEMBIC / "versions" / "0001_base.py"


def _banco_antigo(db, legado=migrar.LEGADO_ESPERADO):
    """Como o vivo está hoje: tabelas do modelo + tabela caseira, sem carimbo Alembic."""
    models.Base.metadata.create_all(models.get_engine(db))
    con = sqlite3.connect(db)
    if legado is not None:
        con.execute("CREATE TABLE _alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        con.executemany("INSERT INTO _alembic_version VALUES (?)", [(v,) for v in sorted(legado)])
    con.commit()
    con.close()


def _tabelas(db):
    return set(inspect(models.get_engine(db)).get_table_names())


# ── (b) revisão base ────────────────────────────────────────────────────────────────────────────

def test_head_e_a_base_e_a_base_e_no_op():
    assert migrar.head() == "0001_base"
    arvore = ast.parse(BASE.read_text(encoding="utf-8"))
    corpos = {f.name: f.body for f in arvore.body if isinstance(f, ast.FunctionDef)}
    for nome in ("upgrade", "downgrade"):
        assert [type(n) for n in corpos[nome]] == [ast.Pass], f"{nome} da base tem de ser no-op"
    assert not re.search(r"\bop\.\w+\(", BASE.read_text(encoding="utf-8"))   # nenhuma operação de schema


def test_diff_ignora_tabela_coluna_e_indice_que_so_existem_no_banco(tmp_path):
    db = tmp_path / "c.db"
    models.init_db(str(db))
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE espelho_cru (x INTEGER)")                 # ~160 tabelas assim no vivo
    con.execute("ALTER TABLE alertas ADD COLUMN visto_em TEXT")          # achado do ensaio de 24/11
    con.execute("CREATE INDEX ix_cru_ob ON ordens_bancarias (valor)")
    con.commit()
    con.close()
    assert migrar.diferencas(db) == []


def test_diff_ainda_ve_coluna_que_o_modelo_tem_e_o_banco_nao(tmp_path):
    """Controle positivo: o filtro não pode cegar o autogenerate para o que FALTA no banco."""
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE missoes_auditoria (id INTEGER PRIMARY KEY)")
    con.commit()
    con.close()
    tipos = {op[0] for op in migrar.diferencas(db) if isinstance(op, tuple)}
    assert "add_column" in tipos


# ── (b) stamp / upgrade / status — o ensaio em miniatura ────────────────────────────────────────

def test_banco_antigo_stamp_upgrade_e_status_em_head(tmp_path):
    db = tmp_path / "vivo.db"
    _banco_antigo(db)
    antes = migrar.estado(db)
    assert antes["atual"] is None and antes["ok"] is False
    assert antes["legado"]["tabela"] == migrar.LEGADO_ATUAL and antes["legado"]["faltam"] == []

    with pytest.raises(migrar.MigracaoRecusada):
        migrar.atualizar(db)                                             # sem carimbo: recusa

    depois = migrar.carimbar(db)
    assert depois["ok"] and depois["atual"] == depois["head"] == "0001_base"
    t = _tabelas(db)
    assert migrar.LEGADO_NOVO in t and migrar.LEGADO_ATUAL not in t and "alembic_version" in t
    assert depois["legado"]["aplicadas"] == sorted(migrar.LEGADO_ESPERADO)

    assert migrar.atualizar(db)["ok"]
    assert migrar.carimbar(db)["ok"]                                     # idempotente
    assert migrar.main(["status", "--db", str(db)]) == 0


def test_stamp_recusa_legado_incompleto_e_nao_escreve(tmp_path):
    db = tmp_path / "vivo.db"
    _banco_antigo(db, legado={"001_extract_raw_json_data", "003_missoes_auditoria"})
    with pytest.raises(migrar.MigracaoRecusada, match="002_categorize_ordens_bancarias"):
        migrar.carimbar(db)
    t = _tabelas(db)
    assert "alembic_version" not in t and migrar.LEGADO_ATUAL in t
    assert migrar.main(["stamp", "--db", str(db)]) == 2


def test_stamp_recusa_banco_sem_prova_do_legado(tmp_path):
    db = tmp_path / "vivo.db"
    _banco_antigo(db, legado=None)
    with pytest.raises(migrar.MigracaoRecusada, match="sem tabela"):
        migrar.carimbar(db)


# ── init_db: banco novo nasce em head; existente não é tocado; sem runner caseiro ─────────────────

def test_init_db_banco_novo_nasce_carimbado(tmp_path):
    db = tmp_path / "novo.db"
    models.init_db(str(db))
    e = migrar.estado(db)
    assert e["ok"] and e["legado"] is None


def test_init_db_em_banco_existente_nao_carimba_nem_recria_tabela_caseira(tmp_path):
    db = tmp_path / "vivo.db"
    _banco_antigo(db)
    migrar.carimbar(db)
    models.init_db(str(db))
    t = _tabelas(db)
    assert migrar.LEGADO_ATUAL not in t                                  # o runner caseiro saiu

    db2 = tmp_path / "sem_carimbo.db"
    _banco_antigo(db2)
    models.init_db(str(db2))
    assert migrar.estado(db2)["atual"] is None                           # stamp do vivo é decisão humana


def test_sync_columns_desligado_por_padrao_e_ligado_pela_flag(tmp_path, monkeypatch):
    chamadas = []
    monkeypatch.setattr(models, "_sync_columns", lambda engine: chamadas.append(engine))
    monkeypatch.delenv("JFN_SYNC_COLUMNS", raising=False)
    models.init_db(str(tmp_path / "a.db"))
    assert chamadas == []
    monkeypatch.setenv("JFN_SYNC_COLUMNS", "1")
    models.init_db(str(tmp_path / "b.db"))
    assert len(chamadas) == 1


# ── (c) boot: verificar_schema nunca levanta; rota de dados responde 503 honesto ──────────────────

def test_verificar_schema_banco_ausente_e_pendente(tmp_path):
    r = migrar.verificar_schema(tmp_path / "nao_existe.db")
    assert r["ok"] is False and r["motivo"] == "banco ausente"
    db = tmp_path / "vivo.db"
    _banco_antigo(db)
    r = migrar.verificar_schema(db)
    assert r["ok"] is False and "SEM CARIMBO" in r["motivo"] and r["head"] == "0001_base"
    migrar.carimbar(db)
    assert migrar.verificar_schema(db)["ok"] is True


def _chamar_middleware(server, caminho):
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse

    req = Request({"type": "http", "method": "GET", "path": caminho, "headers": [], "query_string": b""})

    async def _seguinte(_r):
        return PlainTextResponse("ok")

    return asyncio.run(server._schema_em_head(req, _seguinte))


def test_rota_de_dados_503_com_schema_pendente_e_isentos_passam(monkeypatch):
    import server

    monkeypatch.setattr(server, "_ESTADO_SCHEMA", {"ok": False, "atual": None, "head": "0001_base",
                                                   "motivo": "migração pendente"})
    r = _chamar_middleware(server, "/api/compliance/alertas")
    assert r.status_code == 503 and b"0001_base" in r.body and b"pendente" in r.body
    for livre in ("/api/sistema/saude", "/api/ao-vivo/estado", "/painel"):
        assert _chamar_middleware(server, livre).status_code == 200

    monkeypatch.setattr(server, "_ESTADO_SCHEMA", {"ok": True})
    assert _chamar_middleware(server, "/api/compliance/alertas").status_code == 200
    monkeypatch.setattr(server, "_ESTADO_SCHEMA", {})                    # lifespan não rodou: não barra
    assert _chamar_middleware(server, "/api/compliance/alertas").status_code == 200


def test_boot_registra_no_logger_e_nao_em_print():
    import server

    fonte = __import__("inspect").getsource(server.lifespan)
    trecho = fonte[fonte.index("verificar_schema()"):fonte.index("verificar_schema()") + 500]
    assert "logger.error" in trecho and "print(" not in trecho
