# -*- coding: utf-8 -*-
"""O `-wal` do compliance.db não pode ficar no tamanho do maior lote que já passou por ele.

Medido em 21/11/2026: `compliance.db-wal` com **4,5 GB** e só 361–1.119 quadros em uso. O WAL é
reaproveitado do começo a cada reinício do log, mas o ARQUIVO só encolhe com `wal_checkpoint(TRUNCATE)`
— que exige um instante sem NENHUM leitor no WAL e, num banco com sonda de integridade, sweeps e o
servidor, voltava `busy` em toda rodada do cron (`manut_wal.log`: quatro de quatro). O SQLite tem a
saída própria: `journal_size_limit` faz o escritor que REINICIA o log truncar o arquivo ao teto.
"""
import os
import sqlite3

from compliance_agent import manutencao as M


def _wal_inchado(tmp_path):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("CREATE TABLE t(x TEXT)")
    c.executemany("INSERT INTO t VALUES (?)", [("x" * 900,) for _ in range(6000)])   # ~6 MB de WAL
    c.commit()
    c.execute("PRAGMA wal_checkpoint(PASSIVE)")   # devolve ao banco, mas o arquivo continua do tamanho
    return str(p), c                              # `c` aberta = não é a última conexão (como o wal_keeper)


def test_trunca_wal_inchado_e_dado_intacto(tmp_path):
    db, guarda = _wal_inchado(tmp_path)
    antes = os.path.getsize(db + "-wal")
    assert antes > 4_000_000
    r = M.checkpoint_wal(db, teto_wal=256 * 1024)
    assert r["wal_depois"] <= 256 * 1024 < r["wal_antes"]
    assert guarda.execute("SELECT COUNT(*), SUM(LENGTH(x)) FROM t").fetchone() == (6000, 6000 * 900)
    assert guarda.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    guarda.close()


def test_truncate_ocupado_ainda_encolhe_pelo_reinicio_do_log(tmp_path, monkeypatch):
    """Simula o `busy` do TRUNCATE (o que o cron via): a segunda via — reinício do log por uma
    escrita neutra (`user_version` = ele mesmo) sob `journal_size_limit` — encolhe o arquivo."""
    db, guarda = _wal_inchado(tmp_path)
    monkeypatch.setattr(M, "_MODO_CHECKPOINT", "PASSIVE")   # PASSIVE nunca trunca: é o TRUNCATE que falhou
    v_antes = guarda.execute("PRAGMA user_version").fetchone()[0]
    r = M.checkpoint_wal(db, teto_wal=256 * 1024)
    assert r["wal_depois"] <= 256 * 1024 < r["wal_antes"]
    assert r["reinicio_log"] is True
    assert guarda.execute("PRAGMA user_version").fetchone()[0] == v_antes
    assert guarda.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 6000
    guarda.close()


def test_leitor_preso_no_wal_nao_quebra_nem_perde(tmp_path, monkeypatch):
    """Leitor com transação aberta sobre quadros do WAL: não dá para encolher — e nada pode quebrar."""
    db, guarda = _wal_inchado(tmp_path)
    guarda.execute("INSERT INTO t VALUES ('novo')")
    guarda.commit()                                   # quadro novo, ainda não devolvido ao banco
    leitor = sqlite3.connect(db, isolation_level=None)
    leitor.execute("BEGIN")
    assert leitor.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 6001   # segura o snapshot
    r = M.checkpoint_wal(db, teto_wal=256 * 1024, timeout=0.2, tentativas=2, intervalo_s=0.01)
    assert r["wal_depois"] > 0
    assert leitor.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 6001
    leitor.execute("COMMIT")
    leitor.close()
    assert guarda.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    guarda.close()
