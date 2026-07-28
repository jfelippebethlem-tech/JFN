# -*- coding: utf-8 -*-
"""SLO por FRESCOR DE DADO, não do log — o log é escrito mesmo quando nada foi coletado.

MEDIDO em 2026-07-28: a coleta SIAFE não produziu **nenhuma linha em 10 dos últimos 30 dias**
(27/07, 25/07, 19/07, 18/07, 16/07, 11/07, 05/07, 04/07, 29/06, 28/06) — e o SLO ficou verde o
tempo todo, porque ele olha o mtime de `data/siafe_runner_cron.log`, e o runner escreve o log
em toda execução, inclusive quando a execução não traz dado.

Os diários do vault denunciaram o sintoma antes: 19 e 20/07 registraram "OB coletadas 24h: 949
(R$ 83.708.629,77)" — o mesmo número ao centavo em dois dias. Dois dias iguais não existem.

A lição de origem do próprio `config/pipelines.yaml` já dizia: *"frescor de OUTPUT é o sinal que
pega starvation"*. O que faltava é que, para uma coleta, o OUTPUT é a LINHA NO BANCO — não o
arquivo de log.
"""
from __future__ import annotations

import sqlite3

import pytest

from tools.pipelines_slo import _idade_consulta


@pytest.fixture()
def db(tmp_path):
    caminho = tmp_path / "t.db"
    c = sqlite3.connect(caminho)
    c.execute("CREATE TABLE ob (numero TEXT, coletado_em TEXT)")
    c.commit()
    c.close()
    return str(caminho)


def _inserir(db, *quando):
    c = sqlite3.connect(db)
    c.executemany("INSERT INTO ob VALUES ('x', ?)", [(q,) for q in quando])
    c.commit()
    c.close()


_SQL = "SELECT MAX(coletado_em) FROM ob"


def test_dado_recente_tem_idade_baixa(db):
    c = sqlite3.connect(db)
    c.execute("INSERT INTO ob VALUES ('x', datetime('now','-2 hour'))")
    c.commit()
    c.close()
    idade = _idade_consulta(db, _SQL)
    assert idade is not None and 1.0 < idade < 3.5


def test_dado_velho_e_detectado_mesmo_com_log_novo(db):
    """O caso real: log escrito hoje, última linha de dado há dias."""
    c = sqlite3.connect(db)
    c.execute("INSERT INTO ob VALUES ('x', datetime('now','-5 day'))")
    c.commit()
    c.close()
    idade = _idade_consulta(db, _SQL)
    assert idade is not None and idade > 100


def test_tabela_vazia_devolve_None_e_nao_zero(db):
    """INDISPONÍVEL ≠ 0. Zero significaria 'acabou de coletar', o oposto da verdade."""
    assert _idade_consulta(db, _SQL) is None


def test_banco_inexistente_nao_quebra(tmp_path):
    assert _idade_consulta(str(tmp_path / "nao_existe.db"), _SQL) is None


def test_consulta_invalida_nao_quebra(db):
    assert _idade_consulta(db, "SELECT MAX(coluna_que_nao_existe) FROM ob") is None


def test_config_declara_a_consulta_para_o_siafe():
    """A trava que impede o SLO do SIAFE de voltar a olhar só o log."""
    import pathlib

    import yaml

    cfg = yaml.safe_load(pathlib.Path("config/pipelines.yaml").read_text())
    siafe = [p for p in cfg["pipelines"] if p["nome"] == "siafe-runner"]
    assert siafe, "o pipeline siafe-runner sumiu do inventário"
    assert siafe[0].get("consulta"), "siafe-runner tem de vigiar o DADO, não o log"


# ── fuso: a casa grava dos dois jeitos ─────────────────────────────────────────────────────
# `datetime('now')` do SQLite é UTC; `datetime.now()` do Python é local. Nesta VM (UTC-1),
# comparar carimbo UTC contra relógio local dava idade NEGATIVA — e a 1ª versão clampava com
# `max(0.0, ...)`, devolvendo "0 horas" = "acabou de coletar". O oposto da verdade, escondendo
# justamente o que o monitor existe para achar.

def test_carimbo_utc_nao_vira_idade_zero(db):
    """O bug real: SQLite grava UTC, a VM está atrás, e o clamp fingia dado fresquíssimo."""
    c = sqlite3.connect(db)
    c.execute("INSERT INTO ob VALUES ('x', datetime('now','-2 hour'))")   # UTC
    c.commit()
    c.close()
    idade = _idade_consulta(db, _SQL)
    assert idade is not None
    assert idade > 0.5, f"idade {idade} — carimbo UTC voltou a ser clampado para zero"


def test_carimbo_local_continua_correto(db):
    from datetime import datetime, timedelta
    c = sqlite3.connect(db)
    c.execute("INSERT INTO ob VALUES ('x', ?)",
              ((datetime.now() - timedelta(hours=3)).isoformat(sep=" ", timespec="seconds"),))
    c.commit()
    c.close()
    idade = _idade_consulta(db, _SQL)
    assert idade is not None and 2.5 < idade < 3.5
