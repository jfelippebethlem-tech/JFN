# -*- coding: utf-8 -*-
"""AO VIVO: motor que RODA SEM PRODUZIR tem de aparecer.

Medido em 11/11/2026: o painel classificava só por systemd/exit code e via 2 dos 5 vermelhos.
`sei-varredura` girava a cada 10 min com `resumo: {}` e `bombeiros` saía com rc=0 com a LACUNA
parada em 9.458–9.459 por 11 dias — ambos "saudáveis" na tela. O campo opcional `efeito` do
`motores.yaml` diz onde o trabalho do motor aparece; se ele não avança em `horas`, o motor sai
com `efeito.parado = True` (🟡 "rodando sem efeito"). Efeito que não dá para medir é `None`
(INDISPONÍVEL ≠ parado).
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime

from compliance_agent.aovivo import coleta

AGORA = time.time()


def _iso(ts):
    return datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def test_efeito_por_coluna_de_data(tmp_path, monkeypatch):
    monkeypatch.setattr(coleta, "DATA", tmp_path)
    c = sqlite3.connect(tmp_path / "x.db")
    c.execute("CREATE TABLE t (lido_em TEXT)")
    c.execute("INSERT INTO t VALUES (?), (?)", (_iso(AGORA - 50 * 3600), _iso(AGORA - 3 * 3600)))
    c.commit(); c.close()
    ts = coleta.medir_efeito({"db": "x.db", "tabela": "t", "coluna": "lido_em"})
    assert abs(ts - (AGORA - 3 * 3600)) < 2


def test_efeito_por_arquivo_e_mtime(tmp_path):
    f = tmp_path / "saida.csv"
    f.write_text("x")
    os.utime(f, (AGORA - 7200, AGORA - 7200))
    assert abs(coleta.medir_efeito({"arquivo": str(f)}) - (AGORA - 7200)) < 2


def test_efeito_por_log_e_a_ultima_MUDANCA_do_valor(tmp_path):
    """O caso dos bombeiros: a linha se repete a cada lote; efeito é quando o NÚMERO mudou."""
    log = tmp_path / "b.log"
    log.write_text(
        "[2026-11-01 10:00:00] LACUNA: 9460 processos sem íntegra completa\n"
        "[2026-11-01 11:00:00] LACUNA: 9458 processos sem íntegra completa\n"
        "[2026-11-05 11:00:00] LACUNA: 9458 processos sem íntegra completa\n"
        "[2026-11-11 13:08:38] LACUNA: 9458 processos sem íntegra completa\n")
    ts = coleta.medir_efeito({"log": str(log), "regex": r"LACUNA: (\d+) processos"})
    assert ts == datetime(2026, 11, 1, 11, 0, 0).timestamp()


def test_efeito_por_log_com_sentido_ignora_a_lacuna_que_SOBE(tmp_path):
    """Medido: a lacuna dos bombeiros foi de 9.458 a 9.459 em 09/11 — processo novo, não trabalho."""
    log = tmp_path / "b.log"
    log.write_text(
        "[2026-11-01 10:00:00] LACUNA: 9460 processos\n"
        "[2026-11-01 11:00:00] LACUNA: 9458 processos\n"
        "[2026-11-09 16:44:19] LACUNA: 9459 processos\n"
        "[2026-11-11 13:08:38] LACUNA: 9459 processos\n")
    cfg = {"log": str(log), "regex": r"LACUNA: (\d+) processos"}
    assert coleta.medir_efeito(cfg) == datetime(2026, 11, 9, 16, 44, 19).timestamp()
    assert coleta.medir_efeito({**cfg, "sentido": "desce"}) == datetime(2026, 11, 1, 11, 0, 0).timestamp()


def test_efeito_que_nao_da_para_medir_e_None(tmp_path, monkeypatch):
    monkeypatch.setattr(coleta, "DATA", tmp_path)
    assert coleta.medir_efeito({"arquivo": str(tmp_path / "nao_existe")}) is None
    assert coleta.medir_efeito({"db": "nao.db", "tabela": "t", "coluna": "c"}) is None
    assert coleta.efeito_parado(None, 24, AGORA) is None


def test_efeito_parado_pela_janela():
    assert coleta.efeito_parado(AGORA - 30 * 3600, 24, AGORA) is True
    assert coleta.efeito_parado(AGORA - 2 * 3600, 24, AGORA) is False


def test_coletor_marca_sem_efeito_e_emite_um_aviso(tmp_path, monkeypatch):
    f = tmp_path / "saida.csv"
    f.write_text("x")
    os.utime(f, (AGORA - 72 * 3600, AGORA - 72 * 3600))
    monkeypatch.setattr(coleta, "catalogo", lambda: [
        {"id": "bombeiros", "nome": "Bombeiros", "classe": "motor", "unidade": "jfn-bombeiros-supervisor",
         "efeito": {"arquivo": str(f), "horas": 48}}])
    monkeypatch.setattr(coleta, "ler_systemd", lambda units: {
        "jfn-bombeiros-supervisor.service": {"Id": "jfn-bombeiros-supervisor.service", "LoadState": "loaded",
                                             "ActiveState": "active", "ExecMainStatus": "0",
                                             "ExecMainStartTimestamp": "@%d" % (AGORA - 60)}})
    monkeypatch.setattr(coleta, "travas_presas", lambda: set())
    c = coleta.Coletor()
    c.tick(forcar=True)
    m = c.motores[0]
    assert m["estado"] == "rodando"                       # o estado do systemd não é reescrito
    assert m["efeito"]["parado"] is True and m["efeito"]["horas"] == 48 and m["efeito"]["ultimo"]
    assert c.snapshot()["resumo"]["sem_efeito"] == 1
    c.tick(forcar=True)
    avisos = [e for e in c.eventos_publicos() if "sem efeito" in e["texto"]]
    assert len(avisos) == 1, "o aviso sai na transição, não a cada leitura"


def test_catalogo_efeito_bem_formado():
    for m in coleta.catalogo():
        ef = m.get("efeito")
        if not ef:
            continue
        assert ef.get("horas", 0) > 0, m["id"]
        assert ef.get("arquivo") or ef.get("log") and ef.get("regex") or \
            (ef.get("db") and ef.get("tabela") and ef.get("coluna")), m["id"]
