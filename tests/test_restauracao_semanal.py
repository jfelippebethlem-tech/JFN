# -*- coding: utf-8 -*-
"""Conferência da restauração semanal (tools/restauracao_semanal.py, O8.2): fixtures pequenas, sem PG real."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tools import restauracao_semanal as rs


def test_md5sums_le_formato_do_md5sum_e_recusa_lixo():
    t = "5512074d82186108eb6eaba53497a213  achados.db\n6645543ed5f16eb8acbc1a7efff3dda7 *jfn_evidencias.dump\n\n"
    assert rs.ler_md5sums(t) == {"achados.db": "5512074d82186108eb6eaba53497a213",
                                 "jfn_evidencias.dump": "6645543ed5f16eb8acbc1a7efff3dda7"}
    with pytest.raises(ValueError):
        rs.ler_md5sums("nao-e-md5  x.db")


def test_contagens_aceita_json_e_literal_python_do_snapshot():
    assert rs.ler_contagens('{"alertas": 3}') == {"alertas": 3}
    assert rs.ler_contagens("{'alertas': 63182, 'lex_execucao': 11910}\n") == {"alertas": 63182, "lex_execucao": 11910}


@pytest.mark.parametrize("ruim", ["{}", "[1, 2]", '{"a": -1}', '{"a": true}', '{"a": "3"}', '{"x; drop": 1}', ""])
def test_contagens_ambiguas_sao_recusadas(ruim):
    with pytest.raises((ValueError, SyntaxError)):
        rs.ler_contagens(ruim)


def test_conferir_contagens_exige_igualdade_exata():
    o = {"a": 10, "b": 5}
    assert rs.conferir_contagens(o, {"a": 10, "b": 5}) == {"ok": True, "conferidas": 2, "tabelas": 2, "divergencias": {}}
    r = rs.conferir_contagens(o, {"a": 11, "b": 5})                  # a mais também diverge: backup é foto, não piso
    assert not r["ok"] and r["divergencias"] == {"a": {"origem": 10, "restaurado": 11}}
    r = rs.conferir_contagens(o, {"a": 10, "b": None})               # tabela ilegível
    assert not r["ok"] and "b" in r["divergencias"]
    assert not rs.conferir_contagens(o, {"a": 10})["ok"]             # tabela ausente


def test_origem_vazia_nao_vira_sucesso():
    assert rs.conferir_contagens({}, {"a": 1})["ok"] is False
    assert rs.veredito({})["ok"] is False
    assert rs.veredito({"pg": {"ok": True}, "sqlite": {"ok": False}}) == {"ok": False, "falhas": ["sqlite"]}


def _snapshot(tmp_path: Path, linhas: int = 3) -> Path:
    pasta = tmp_path / "snapshot-20261124"
    pasta.mkdir()
    db = pasta / "compliance.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE alertas(id INTEGER)")
    con.executemany("INSERT INTO alertas VALUES (?)", [(i,) for i in range(linhas)])
    con.commit()
    con.close()
    (pasta / "MD5SUMS").write_text(f"{hashlib.md5(db.read_bytes()).hexdigest()}  compliance.db\n")
    (pasta / "contagens_12h40.txt").write_text("{'alertas': 3}\n")
    return pasta


def test_executar_sqlite_confere_md5_quick_check_e_contagem(tmp_path):
    pasta = _snapshot(tmp_path)
    r = rs.executar(pasta, None, tmp_path / "trab", None, None)
    assert r["ok"] is True
    s = r["partes"]["sqlite"]
    assert s["quick_check"] == "ok" and s["restaurado"] == {"alertas": 3} and r["md5"]["compliance.db"]["ok"]
    assert not any((tmp_path / "trab").iterdir())                    # a cópia de trabalho é apagada


def test_executar_detecta_contagem_divergente(tmp_path):
    pasta = _snapshot(tmp_path, linhas=2)
    r = rs.executar(pasta, None, tmp_path / "trab", None, None)
    assert r["ok"] is False and r["falhas"] == ["sqlite"]
    assert r["partes"]["sqlite"]["divergencias"] == {"alertas": {"origem": 3, "restaurado": 2}}


def test_executar_recusa_md5_que_nao_confere(tmp_path):
    pasta = _snapshot(tmp_path)
    (pasta / "MD5SUMS").write_text("0" * 32 + "  compliance.db\n")
    r = rs.executar(pasta, None, tmp_path / "trab", None, None)
    assert r["ok"] is False and "md5" in r["partes"]["sqlite"]["erro"]
    assert "restaurado" not in r["partes"]["sqlite"]                  # nem tentou restaurar


def test_pg_sem_contagens_da_origem_falha_sem_restaurar(tmp_path):
    pasta = _snapshot(tmp_path)
    (pasta / "jfn_evidencias.dump").write_bytes(b"x")
    md5 = hashlib.md5(b"x").hexdigest()
    (pasta / "MD5SUMS").write_text((pasta / "MD5SUMS").read_text() + f"{md5}  jfn_evidencias.dump\n")
    r = rs.executar(pasta, tmp_path / "bin-inexistente", tmp_path / "trab", None, None)
    assert r["ok"] is False and r["falhas"] == ["pg"] and "origem" in r["partes"]["pg"]["erro"]


def test_ultima_pasta_exige_md5sums(tmp_path):
    (tmp_path / "snapshot-20261201").mkdir()                           # mais novo, mas sem MD5SUMS
    _snapshot(tmp_path)
    assert rs.ultima_pasta(tmp_path).name == "snapshot-20261124"
    assert rs.ultima_pasta(tmp_path / "nada") is None


def test_linhas_metricas_ok_e_quando():
    res = {"ok": True, "quando_epoch": 1764000000.0, "pasta": "p", "host": "h", "falhas": [],
           "partes": {"pg": {"ok": True, "conferidas": 9, "tabelas": 9}}}
    ls = rs.linhas_metricas(res, "itcampo", "abc")
    assert [(no, n, v) for no, n, v, _ in ls] == [("itcampo", "backup.restauracao_ok", 1.0),
                                                 ("itcampo", "backup.restauracao_quando", 1764000000.0)]
    assert json.loads(ls[0][3])["execucao"] == "abc"
    assert rs.linhas_metricas({**res, "ok": False}, "vm2", "x")[0][2] == 0.0


class _Cur:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def executemany(self, sql, linhas):
        self.db.extend(linhas)


class _Con:
    """Falso psycopg mínimo: grava as linhas e reconta pela etiqueta `execucao`."""
    def __init__(self, perde: bool = False):
        self.linhas, self.perde = [], perde

    def cursor(self):
        return _Cur(self.linhas)

    def execute(self, sql, params):
        n = sum(1 for _, _, _, rot in self.linhas if json.loads(rot)["execucao"] == params[0])
        return type("R", (), {"fetchone": lambda s: (n - (1 if self.perde else 0),)})()


def test_gravar_reconta_pela_etiqueta_da_execucao():
    res = {"ok": True, "quando_epoch": 1.0, "partes": {}}
    g = rs.gravar(res, "itcampo", _Con())
    assert g["gravadas"] == g["conferidas"] == 2
    g = rs.gravar(res, "itcampo", _Con(perde=True))
    assert g["conferidas"] == 1                                       # o CLI devolve rc 1 nesse caso
