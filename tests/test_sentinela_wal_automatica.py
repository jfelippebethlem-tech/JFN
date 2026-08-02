# -*- coding: utf-8 -*-
"""A bandeira PERSIST_WAL precisa valer para a CASA INTEIRA, não só para o servidor.

Medido em 31/07/2026: a bandeira é consultada por quem FECHA. A guardiã do servidor cobre o caso de
ele ser o último a fechar — mas **188 arquivos** abrem o banco com `sqlite3` cru (91 deles escrevem),
e a stdlib não expõe file controls. Enquanto um sweep for o último a fechar sem a bandeira, ele
desvincula `-wal`/`-shm` e o servidor fica com um mapeamento morto → "malformed" com o arquivo
íntegro.

Migrar 91 call-sites não é cirúrgico e quebraria API (o `apsw` tem semântica própria de
transação). A alavanca é outra: a bandeira é por CONEXÃO, mas a proteção é por PROCESSO. Basta que
CADA processo tenha UMA sentinela `apsw` com a bandeira, aberta enquanto ele viver — aí ele nunca é
"o último a fechar sem a bandeira". Instalando isso no `__init__` do pacote, todo processo que toca
o banco herda, com ZERO mudança de chamador.

Verificado antes de fiar: a sentinela aberta **não** bloqueia `wal_checkpoint(TRUNCATE)`, `VACUUM`
nem `ANALYZE` no mesmo processo — era o efeito de segunda ordem que poderia trocar um defeito por
"database is locked" na manutenção.
"""
from __future__ import annotations

import sqlite3

import pytest

from compliance_agent.database import guarda_wal


@pytest.fixture()
def banco(tmp_path):
    p = tmp_path / "compliance.db"
    con = sqlite3.connect(p)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    guarda_wal.soltar()
    return p


def test_instalar_automatico_liga_a_sentinela(banco, monkeypatch):
    monkeypatch.setattr(guarda_wal, "_DB_PADRAO", banco)

    assert guarda_wal.instalar_automatico() is True
    try:
        assert guarda_wal.vivo() and guarda_wal.persist_wal_ligado()
    finally:
        guarda_wal.soltar()


def test_pode_ser_desligada_por_ambiente(banco, monkeypatch):
    """Escotilha: um processo que não queira o descritor extra desliga sem editar código."""
    monkeypatch.setattr(guarda_wal, "_DB_PADRAO", banco)
    monkeypatch.setenv("JFN_SENTINELA_WAL", "0")

    assert guarda_wal.instalar_automatico() is False
    assert guarda_wal.vivo() is False


def test_banco_ausente_nao_derruba_o_import(tmp_path, monkeypatch):
    """O `__init__` do pacote chama isto: falhar ali quebraria TODO import da casa."""
    monkeypatch.setattr(guarda_wal, "_DB_PADRAO", tmp_path / "nao_existe.db")

    assert guarda_wal.instalar_automatico() is False


def test_instalar_e_idempotente(banco, monkeypatch):
    """Import acontece muitas vezes; não pode vazar um descritor por vez."""
    monkeypatch.setattr(guarda_wal, "_DB_PADRAO", banco)
    guarda_wal.instalar_automatico()
    primeira = guarda_wal._CONEXAO
    try:
        guarda_wal.instalar_automatico()
        assert guarda_wal._CONEXAO is primeira
    finally:
        guarda_wal.soltar()


def test_a_sentinela_nao_atrapalha_a_manutencao(banco, monkeypatch):
    """Guarda-costas do efeito de segunda ordem: VACUUM/checkpoint seguem funcionando."""
    monkeypatch.setattr(guarda_wal, "_DB_PADRAO", banco)
    guarda_wal.instalar_automatico()
    try:
        for sql in ("PRAGMA wal_checkpoint(TRUNCATE)", "VACUUM", "ANALYZE"):
            con = sqlite3.connect(banco, timeout=10)
            try:
                con.execute(sql)
                con.commit()
            finally:
                con.close()
    finally:
        guarda_wal.soltar()


def test_o_pacote_instala_no_import():
    """A fiação que dá o alcance: importar `compliance_agent` já deixa a sentinela pronta."""
    import compliance_agent

    assert hasattr(compliance_agent, "_SENTINELA_WAL"), (
        "o __init__ do pacote não instala a sentinela — o alcance volta a ser só o servidor")
