# -*- coding: utf-8 -*-
"""E17 `manter:<rotina>` (O8.5): registro, modo SIMULAR (padrão) que só lê e lista o que faria, efeito que recusa
backup aparecido durante a simulação, execução real só com JFN_MANTER_REAL=1 — tudo em banco temporário."""
import sqlite3

import pytest

from compliance_agent.aplicacao.estagios import Contexto, ErroPermanente, estagio_de
from compliance_agent.aplicacao.estagios import manter as M


def _ctx(r):
    return Contexto(no="t", tipo=f"manter:{r}", chave=f"manter:{r}:teste", ficha=7, tentativa=1)


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "x.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE t(a)")
    c.executemany("INSERT INTO t VALUES (?)", [("x" * 500,)] * 200)
    c.commit()
    c.execute("DELETE FROM t")                                     # páginas livres > 5%
    c.commit()
    c.close()
    return p


def test_estagio_registrado_com_contrato():
    assert estagio_de("manter:vacuum") is M.ESTAGIO and M.ESTAGIO.recursos == ["disco"]
    assert M.ESTAGIO.prioridade == 60 and M.ESTAGIO.volta == {"nos": ["vm2", "vm1"]}
    with pytest.raises(ErroPermanente):
        M.rotina_de({"rotina": "apagar_tudo"})


def test_simular_vacuum_so_le_e_lista(db):
    antes = (db.stat().st_size, db.stat().st_mtime_ns)
    payload = {"rotina": "vacuum", "db": str(db)}
    res = M.ESTAGIO.handler(payload, _ctx("vacuum"))
    assert res.efeito["simulado"] and not res.efeito["executado"] and res.efeito["pronto"]
    livres = [p for p in res.efeito["precondicoes"] if p["nome"] == "paginas_livres"][0]
    assert livres["faria"] is True and "faria" in livres["detalhe"]
    assert M.ESTAGIO.efeito(payload, _ctx("vacuum"), res) is True
    assert (db.stat().st_size, db.stat().st_mtime_ns) == antes        # nada executado
    assert not res.eventos


def test_simular_backup_confere_precondicoes_e_recusa_backup_novo(tmp_path, monkeypatch, db):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "backup_compliance.sh").write_text("#!/bin/bash\nexit 1\n")
    monkeypatch.setattr(M, "RAIZ", tmp_path)
    monkeypatch.setenv("BACKUP_AGE_RECIPIENTS", str(tmp_path / "nao_existe.txt"))
    payload = {"rotina": "backup_compliance", "db": str(db)}
    res = M.ESTAGIO.handler(payload, _ctx("backup_compliance"))
    pre = {p["nome"]: p["ok"] for p in res.efeito["precondicoes"]}
    assert pre["script"] is True and pre["destinatarios"] is False and res.efeito["pronto"] is False
    assert res.efeito["comando"] == ["bash", "tools/backup_compliance.sh"]
    assert M.ESTAGIO.efeito(payload, _ctx("backup_compliance"), res) is True
    (tmp_path / "data" / "backups").mkdir(parents=True)
    (tmp_path / "data" / "backups" / "compliance-x.db.gz.age").write_text("x")
    assert M.ESTAGIO.efeito(payload, _ctx("backup_compliance"), res) is False   # algo rodou de verdade


def test_real_exige_liberacao_explicita(db, monkeypatch):
    monkeypatch.delenv(M.ENV_REAL, raising=False)
    with pytest.raises(ErroPermanente, match="JFN_MANTER_REAL"):
        M.ESTAGIO.handler({"rotina": "wal_checkpoint", "db": str(db), "simular": False}, _ctx("wal_checkpoint"))


def test_real_wal_checkpoint_em_banco_temporario(db, monkeypatch):
    monkeypatch.setenv(M.ENV_REAL, "1")
    payload = {"rotina": "wal_checkpoint", "db": str(db), "simular": False}
    res = M.ESTAGIO.handler(payload, _ctx("wal_checkpoint"))
    assert res.efeito["executado"] and M.ESTAGIO.efeito(payload, _ctx("wal_checkpoint"), res) is True
