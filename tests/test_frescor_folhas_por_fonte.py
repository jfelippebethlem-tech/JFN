# -*- coding: utf-8 -*-
"""Frescor das folhas: uma linha por FONTE, com a esfera de cada uma (20/11/2026).

A rota /api/fontes/frescor servia uma linha só — "Folhas (Estado)", `MAX(competencia)` da tabela inteira,
detalhe "DPE + CMRJ + TJRJ". Dois erros num número:
  · mistura de esfera: a Câmara MUNICIPAL do Rio (camara_csv) sob o rótulo "Estado";
  · não atualiza, escondido: o máximo era o do Executivo (GESPERJ, 2026-11) e encobria a Defensoria parada em
    2025-10 (13 meses) e o TJRJ parado em 2026-05, cujo coletor diário responde "ok: false" sem alarme.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from compliance_agent.nomeados_candidatos import frescor_folhas

HOJE = datetime(2026, 11, 20, 3, 0).astimezone()


def _con():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE registros_folha (fonte TEXT, competencia TEXT, created_at TEXT)")
    con.executemany("INSERT INTO registros_folha VALUES (?,?,?)", [
        ("gesperj_estado", "2026-11", "2026-11-14 09:13:34"),
        ("gesperj_estado", "2026-10", "2026-10-14 09:00:00"),
        ("dprj_transparencia", "2025-10", "2026-06-07 06:33:40"),
        ("tjrj_anexo8", "2026-05", "2026-07-17 03:18:43"),
        ("camara_csv", "2026", "2026-07-17 02:43:11"),
        ("camara_csv", "1978", "2026-07-17 02:43:11"),
        ("fonte_nova_sem_mapa", "2026-11", "2026-11-19 00:00:00"),
    ])
    return con


def test_uma_linha_por_fonte_com_a_esfera_de_cada_uma():
    por = {f["chave"]: f for f in frescor_folhas(_con(), HOJE)}
    assert por["gesperj_estado"]["esfera"] == "estado"
    assert por["camara_csv"]["esfera"] == "municipal"                     # nunca "Estado"
    assert "Câmara Municipal" in por["camara_csv"]["fonte"] and "Estado" not in por["camara_csv"]["fonte"]
    assert por["fonte_nova_sem_mapa"]["esfera"] == "indefinida"           # fonte sem mapa não vira estadual


def test_fonte_parada_nao_se_esconde_atras_da_mais_nova():
    por = {f["chave"]: f for f in frescor_folhas(_con(), HOJE)}
    assert por["gesperj_estado"]["estado"] == "ok" and por["gesperj_estado"]["ultimo"] == "2026-11-01"
    assert por["dprj_transparencia"]["estado"] == "critico" and por["dprj_transparencia"]["ultimo"] == "2025-10-01"
    assert por["tjrj_anexo8"]["estado"] == "critico"
    assert por["dprj_transparencia"]["idade_dias"] > 365


def test_lista_anual_usa_a_data_da_carga_e_diz_isso():
    cam = {f["chave"]: f for f in frescor_folhas(_con(), HOJE)}["camara_csv"]
    assert cam["ultimo"] == "2026-07-17 02:43:11"                         # competência "2026" não é data
    assert "carga" in cam["detalhe"]
    assert cam["estado"] == "critico"                                      # 126 dias sem recarga


def test_tabela_ausente_e_indisponivel_nao_zero():
    con = sqlite3.connect(":memory:")
    r = frescor_folhas(con, HOJE)
    assert len(r) == 1 and r[0]["ultimo"] is None and r[0]["estado"] == "critico" and "erro" in r[0]["detalhe"]
