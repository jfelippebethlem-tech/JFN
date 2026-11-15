# -*- coding: utf-8 -*-
"""Recoleta das OB 2023 no SIAFE 2 (processo da OB): janela, fila, checkpoint antigo e parada nos erros do dono."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from tools import siafe_recoleta_2023_processo as R


def test_janela_fechada_cruza_meia_noite():
    assert R.na_janela_fechada(datetime(2026, 11, 14, 23, 10))
    assert R.na_janela_fechada(datetime(2026, 11, 15, 2, 0))
    assert R.na_janela_fechada(datetime(2026, 11, 15, 5, 39))
    assert not R.na_janela_fechada(datetime(2026, 11, 15, 5, 40))
    assert not R.na_janela_fechada(datetime(2026, 11, 14, 23, 9))
    assert R.proxima_abertura(datetime(2026, 11, 14, 23, 30)) == datetime(2026, 11, 15, 5, 40)
    assert R.proxima_abertura(datetime(2026, 11, 15, 1, 0)) == datetime(2026, 11, 15, 5, 40)
    assert R.segundos_ate_fechar(datetime(2026, 11, 14, 22, 10)) == 3600
    assert R.segundos_ate_fechar(datetime(2026, 11, 14, 23, 30)) == 0


def _db(tmp_path):
    db = tmp_path / "c.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ob_orcamentaria_siafe (numero_ob TEXT, ug_emitente TEXT, exercicio INTEGER, processo TEXT)")
    linhas = [("2023OB1", "A", 2023, "")] * 5 + [("2023OB2", "B", 2023, "SEI-1")] * 2 + [("2023OB3", "C", 2023, None)] * 9
    linhas += [("2024OB1", "D", 2024, "")]          # outro ano não entra na fila
    con.executemany("INSERT INTO ob_orcamentaria_siafe VALUES (?,?,?,?)", linhas)
    con.commit(); con.close()
    return db


def test_fila_relevantes_primeiro_depois_menores(tmp_path):
    db = _db(tmp_path)
    assert R.fila({"C": 10, "X": 99}, db) == ["C", "B", "A"]     # X não tem OB 2023: fora
    assert R.medir("B", db) == {"linhas": 2, "com_processo": 2}
    assert R.medir("C", db) == {"linhas": 9, "com_processo": 0}


def test_checkpoint_do_siafe1_afastado_so_uma_vez(tmp_path):
    ck = tmp_path / "uggrande_A_2023.json"
    ck.write_text(json.dumps({"done": ["2023OB0"]}))
    est = {}
    assert R.afastar_checkpoint_siafe1("A", est, tmp_path)
    assert not ck.exists() and (tmp_path / "uggrande_A_2023.json.siafe1").exists()
    ck.write_text("{}")                                   # progresso DESTA recoleta
    assert not R.afastar_checkpoint_siafe1("A", est, tmp_path)
    assert ck.exists()


def test_resultado_do_coletor_le_o_ultimo_json():
    saida = '  pref 2023OB0: 10 OBs ✓\n{\n "ok": true,\n "ingeridas": 10\n}\n'
    assert R.resultado_do_coletor(saida) == {"ok": True, "ingeridas": 10}
    assert R.resultado_do_coletor("Traceback ...") == {}


def test_erros_que_so_o_dono_resolve_param():
    bloqueado = {"ok": False, "etapa": "login_nav", "ultimo": {"ok": False, "erro": "exercicio_bloqueado"},
                 "erros": ["exercicio_bloqueado"]}
    assert R.erro_do_dono(bloqueado) == "exercicio_bloqueado"
    assert R.erro_do_dono({"ok": False, "erro": "senha_incorreta"}) == "senha_incorreta"
    assert R.erro_do_dono({"ok": False, "ultimo": {"erro": "mfa_sem_codigo"}}) == "mfa"
    assert R.erro_do_dono({"ok": False, "etapa": "filtro_linha1"}) is None
    assert not R.concluida(bloqueado) and R.concluida({"ok": True, "nada_a_fazer": True})
