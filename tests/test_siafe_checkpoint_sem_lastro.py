# -*- coding: utf-8 -*-
"""Checkpoint de UG grande que diz "feito" sem lastro no banco.

04/11/2026: quatro pares (100100/2023, 263100/2023, 026100/2025, 370200/2021) ficaram em quarentena
"checkpoint feito × medidor incompleto". Os checkpoints eram de agosto — anteriores à correção de
24/10 (ae72a7bf) que impediu zero transitório de virar "feito" — e seguiam escondendo fatias inteiras:
na 100100/2023, OB04–OB09 estavam 100% ausentes do SIAFE e marcadas como feitas.
"""
import sqlite3

from compliance_agent import siafe_ob_orcamentaria as S


def _db(tmp_path):
    p = tmp_path / "c.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE ordens_bancarias(ug_codigo TEXT, numero_ob TEXT, data_emissao TEXT)")
    c.execute("CREATE TABLE ob_orcamentaria_siafe(ug_emitente TEXT, exercicio INTEGER, numero_ob TEXT)")
    esp = [(f"2023OB04{i:03d}",) for i in range(100)] + [(f"2023OB05{i:03d}",) for i in range(100)] \
        + [(f"2023OB06{i:03d}",) for i in range(100)]
    c.executemany("INSERT INTO ordens_bancarias VALUES ('100100', ?, '2023-05-01')", esp)
    siafe = [(f"2023OB05{i:03d}",) for i in range(10)] + [(f"2023OB06{i:03d}",) for i in range(95)] \
        + [(f"2023OB07{i:03d}",) for i in range(3)]
    c.executemany("INSERT INTO ob_orcamentaria_siafe VALUES ('100100', 2023, ?)", siafe)
    c.commit()
    c.close()
    return p


def test_fatia_feita_sem_lastro_volta_para_a_fila(tmp_path):
    done = {"2023OB04", "2023OB05", "2023OB06", "2023OB07", "2023OB08"}
    sem = S._ckpt_sem_lastro("100100", 2023, done, db=_db(tmp_path))
    assert "2023OB04" in sem          # zero no SIAFE: refazer
    assert "2023OB05" in sem          # 10 de 100 do espelho: coleta parcial gravada como feita
    assert "2023OB08" in sem          # zero no SIAFE e no espelho: re-consultar custa segundos
    assert "2023OB06" not in sem      # 95 de 100: feita de verdade
    assert "2023OB07" not in sem      # tem linha e o espelho não conhece a fatia: nada contra


def test_banco_ilegivel_nao_apaga_checkpoint(tmp_path):
    assert S._ckpt_sem_lastro("100100", 2023, {"2023OB04"}, db=tmp_path / "nao-existe.db") == set()
