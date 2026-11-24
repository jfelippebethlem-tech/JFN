# -*- coding: utf-8 -*-
"""Ambiente Alembic do compliance.db (O4.2 do plano Esteira Única, 24/11/2026).

Entrada única: `python -m compliance_agent.database.migrar status|stamp|upgrade|diff` — ela monta o
`Config` (sem alembic.ini) e passa a conexão em `config.attributes["connection"]`.

Duas travas deste arquivo:
  • `render_as_batch=True` — SQLite não faz ALTER de coluna; o modo batch recria a tabela.
  • `incluir_objeto` (em migrar.py) — tabela/índice que só existe no banco fica FORA da comparação;
    sem isso o autogenerate proporia DROP das ~160 tabelas que não estão nos modelos ORM.
"""
from alembic import context
from sqlalchemy import create_engine

from compliance_agent.database.migrar import incluir_objeto
from compliance_agent.database.models import Base

config = context.config
target_metadata = Base.metadata


def _configurar(conexao):
    context.configure(
        connection=conexao,
        target_metadata=target_metadata,
        render_as_batch=True,
        include_object=incluir_objeto,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def rodar_online():
    conexao = config.attributes.get("connection")
    if conexao is not None:
        _configurar(conexao)
        return
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.connect() as conexao:
        _configurar(conexao)


if context.is_offline_mode():
    raise SystemExit("modo offline (SQL impresso) não é usado no JFN — rode online pelo migrar")
rodar_online()
