# -*- coding: utf-8 -*-
"""Migrações do compliance.db pelo Alembic — porta única (O4.2 do plano Esteira Única, 24/11/2026).

    python -m compliance_agent.database.migrar status   [--db CAMINHO]   # atual × head (sai 0 só se iguais)
    python -m compliance_agent.database.migrar stamp    [--db CAMINHO]   # marca o banco existente na base (0001)
    python -m compliance_agent.database.migrar upgrade  [--db CAMINHO]   # aplica revisões pendentes
    python -m compliance_agent.database.migrar diff     [--db CAMINHO]   # autogenerate SÓ LEITURA: modelo × banco

Sem `--db` vale a mesma régua do app (`JFN_DB` > `data/compliance.db`).

POR QUE (DB-02 da auditoria): o runner caseiro (`models._migrate`) gravava numa tabela própria
`_alembic_version` (homônima do Alembic, sem ser Alembic), e migração que falhava era impressa e o
boot SEGUIA — o painel servia sobre schema pela metade sem ninguém saber. Agora:
  • as 3 migrações caseiras (001 extract_raw_json, 002 categoria das OB, 003 missões) estão
    ABSORVIDAS na revisão base `0001_base` — o banco vivo já as tem (conferido na tabela caseira);
  • `stamp` só carimba se a tabela caseira tiver as 3; depois RENOMEIA a caseira para
    `_jfn_migracoes_legado` (histórico preservado, nome não confunde mais com o Alembic);
  • o boot do painel exige `atual == head` (`verificar_schema`); senão as rotas de dados
    respondem 503 honesto e o motivo vai ao logger.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from compliance_agent.database.models import _resolver_db, get_engine

logger = logging.getLogger(__name__)

PASTA_ALEMBIC = Path(__file__).parent / "alembic"
LEGADO_ATUAL = "_alembic_version"            # tabela do runner caseiro (não é do Alembic)
LEGADO_NOVO = "_jfn_migracoes_legado"
LEGADO_ESPERADO = frozenset({"001_extract_raw_json_data", "002_categorize_ordens_bancarias",
                             "003_missoes_auditoria"})
# O legado prova só 001–003, que a BASE absorve: o stamp carimba a base, nunca o head. Carimbar o head
# (desde a 0002_datas_iso) marcaria como aplicada uma revisão que nunca rodou naquele banco.
REVISAO_BASE = "0001_base"


def incluir_objeto(objeto, nome, tipo, refletido, par_no_modelo):
    """Filtro do autogenerate (usado pelo env.py e pelo `diff`).

    O compliance.db tem ~160 tabelas FORA dos modelos ORM (sqlite3 cru: espelhos SIAFE, FTS, filas).
    Sem este filtro o autogenerate proporia DROP de todas — e dos índices criados à mão nas tabelas
    do modelo. O que só existe no banco (refletido, sem par no modelo) fica fora da comparação.
    Coluna também: o ensaio de 24/11 no snapshot achou `alertas.visto_em` (alertas_persistencia.py) e
    `registros_folha.matricula` (collectors/folha_estado.py), criadas por ALTER TABLE cru e ausentes do
    modelo — o autogenerate propunha DROP das duas.
    """
    return not (refletido and par_no_modelo is None
                and tipo in ("table", "column", "index", "unique_constraint"))


class MigracaoRecusada(RuntimeError):
    """Pré-condição não atendida — nada foi escrito."""


def _config(conexao=None):
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(PASTA_ALEMBIC))
    if conexao is not None:
        cfg.attributes["connection"] = conexao
    return cfg


def head() -> str:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(_config()).get_current_head()


def _atual(conexao) -> str | None:
    from alembic.runtime.migration import MigrationContext

    return MigrationContext.configure(conexao).get_current_revision()


def _legado(conexao) -> dict | None:
    tabelas = set(inspect(conexao).get_table_names())
    for nome in (LEGADO_ATUAL, LEGADO_NOVO):
        if nome in tabelas:
            linhas = {r[0] for r in conexao.execute(text(f'SELECT version_num FROM "{nome}"'))}
            return {"tabela": nome, "aplicadas": sorted(linhas),
                    "faltam": sorted(LEGADO_ESPERADO - linhas)}
    return None


def estado(db_path=None) -> dict:
    db = _resolver_db(db_path)
    with get_engine(db).connect() as c:
        atual = _atual(c)
        legado = _legado(c)
    h = head()
    return {"db": str(db), "atual": atual, "head": h, "ok": atual == h, "legado": legado}


def verificar_schema(db_path=None) -> dict:
    """Para o boot: nunca levanta. `ok` False com `motivo` quando o schema não está provado em head."""
    db = _resolver_db(db_path)
    if not db.exists():
        return {"db": str(db), "ok": False, "atual": None, "head": None, "motivo": "banco ausente"}
    try:
        e = estado(db)
    except ImportError as exc:
        return {"db": str(db), "ok": False, "atual": None, "head": None,
                "motivo": f"alembic indisponível no ambiente ({exc})"}
    except SQLAlchemyError as exc:
        return {"db": str(db), "ok": False, "atual": None, "head": None,
                "motivo": f"não consegui ler a versão do schema ({type(exc).__name__}: {exc})"}
    if not e["ok"]:
        e["motivo"] = (f"migração pendente: banco em {e['atual'] or 'SEM CARIMBO'}, código exige {e['head']}"
                       " — rode `python -m compliance_agent.database.migrar status`")
    return e


def carimbar(db_path=None) -> dict:
    """`stamp` da BASE num banco EXISTENTE, com a trava do legado, e renomeia a tabela caseira.

    Banco já carimbado não é tocado (re-carimbar a base faria um banco em head "voltar" sem desfazer nada).
    Depois do stamp, `upgrade` aplica as revisões posteriores à base."""
    from alembic import command

    db = _resolver_db(db_path)
    if not db.exists():
        raise MigracaoRecusada(f"{db} não existe — banco novo nasce por init_db(), não por stamp")
    engine = get_engine(db)
    with engine.connect() as c:
        legado = _legado(c)
        if legado is None:
            raise MigracaoRecusada("sem tabela de migrações caseiras: não há prova de que 001–003 foram "
                                   "aplicadas neste banco — conferir à mão antes de carimbar")
        if legado["faltam"]:
            raise MigracaoRecusada(f"migrações caseiras NÃO aplicadas: {legado['faltam']} — a base as "
                                   "absorve, carimbar esconderia o defeito")
        if _atual(c) is not None:
            return estado(db)
    with engine.begin() as c:
        command.stamp(_config(c), REVISAO_BASE)
        if legado["tabela"] == LEGADO_ATUAL:
            c.execute(text(f'ALTER TABLE "{LEGADO_ATUAL}" RENAME TO "{LEGADO_NOVO}"'))
    return estado(db)


def atualizar(db_path=None) -> dict:
    from alembic import command

    db = _resolver_db(db_path)
    engine = get_engine(db)
    with engine.connect() as c:
        if _atual(c) is None and inspect(c).get_table_names():
            raise MigracaoRecusada("banco existente SEM carimbo — rode `stamp` primeiro (ele confere o legado)")
    with engine.begin() as c:
        command.upgrade(_config(c), "head")
    return estado(db)


def diferencas(db_path=None) -> list:
    """Autogenerate em modo só-leitura: o que o modelo ORM tem de diferente do banco (mesmo filtro do env.py)."""
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext

    from compliance_agent.database.models import Base

    with get_engine(_resolver_db(db_path)).connect() as c:
        ctx = MigrationContext.configure(c, opts={"include_object": incluir_objeto,
                                                  "compare_type": True, "render_as_batch": True})
        return compare_metadata(ctx, Base.metadata)


def carimbar_banco_novo(engine) -> None:
    """Banco que `init_db` acabou de criar do zero já nasce no head (o schema é o do modelo)."""
    try:
        from alembic import command
    except ImportError as exc:
        logger.warning("banco novo sem carimbo Alembic (alembic indisponível: %s)", exc)
        return
    with engine.begin() as c:
        command.stamp(_config(c), "head")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m compliance_agent.database.migrar",
                                 description="Migrações Alembic do compliance.db")
    ap.add_argument("acao", choices=("status", "stamp", "upgrade", "diff"))
    ap.add_argument("--db", help="caminho do banco (padrão: JFN_DB ou data/compliance.db)")
    a = ap.parse_args(argv)
    try:
        if a.acao == "diff":
            ops = diferencas(a.db)
            for op in ops:
                print(op)
            print(f"{len(ops)} diferença(s) entre o modelo ORM e o banco")
            return 0 if not ops else 1
        r = {"status": estado, "stamp": carimbar, "upgrade": atualizar}[a.acao](a.db)
    except MigracaoRecusada as exc:
        print(f"RECUSADO: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
