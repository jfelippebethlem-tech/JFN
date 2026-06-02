"""Migração: cria tabela de missões de auditoria."""
from compliance_agent.database.models import Base, get_engine


def upgrade(session):
    Base.metadata.create_all(
        get_engine(),
        tables=[Base.metadata.tables.get("missoes_auditoria")],
    )
