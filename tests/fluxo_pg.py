# -*- coding: utf-8 -*-
"""Apoio dos testes do motor de fluxo no PostgreSQL: SEMPRE num esquema temporário criado aqui com o MESMO
deploy/vm2/postgres/fluxo_*.sql e apagado no fim (23/11/2026: a suíte antiga esvaziava a tabela real).
Sem `JFN_EVIDENCIAS_DSN=postgresql://…` no ambiente, os testes PG são pulados com o motivo."""
import os
import random
import uuid

import pytest

from compliance_agent.evidencias import ENV_DSN

DSN = os.environ.get(ENV_DSN, "")
precisa_pg = pytest.mark.skipif(not DSN.startswith(("postgresql://", "postgres://")),
                                reason="sem JFN_EVIDENCIAS_DSN (PostgreSQL de teste) — rodar na VM-2 com o DSN")


@pytest.fixture(scope="module")
def esquema_tmp():
    """Nome do esquema temporário com o schema do fluxo aplicado; apagado (CASCADE) ao fim do módulo."""
    import psycopg

    from compliance_agent.fluxo import schema
    nome = f"tmp_fluxo_{uuid.uuid4().hex[:10]}"
    con = psycopg.connect(DSN, autocommit=True)
    try:
        schema.aplicar(con, nome)
        yield nome
    finally:
        con.execute(f'DROP SCHEMA IF EXISTS "{nome}" CASCADE')
        con.close()


@pytest.fixture()
def con(esquema_tmp):
    """Conexão no esquema temporário, com as tabelas esvaziadas antes de cada teste (só no temporário)."""
    from compliance_agent.fluxo import fila
    c = fila.conectar(DSN, esquema_tmp)
    c.execute("TRUNCATE jobs, eventos, agenda, nos, metricas, liberacao, eventos_arquivo RESTART IDENTITY")
    yield c
    c.close()


def chave_lock() -> int:
    """Chave de advisory lock só do teste: nunca a 42 da produção (o lock é por banco)."""
    return random.randint(10**9, 2 * 10**9)
