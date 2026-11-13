# -*- coding: utf-8 -*-
"""AO VIVO: evento leva a hora REAL do que aconteceu, não a hora em que o painel foi aberto.

Laudo de motores 13/11/2026 (3.2): o coletor só lê quando alguém abre o painel. Às 07:54:10 ele
registrou "Atas de julgamento: terminou" e "SEI noturno: terminou" — as atas terminaram às 02:11:55
e o SEI noturno às 03:33:13. A transição passa a usar o carimbo do systemd (`InactiveEnterTimestamp` /
`ActiveEnterTimestamp`) e, para job de cron com trava, o mtime do log (fim) ou da trava (início).
Hora que não dá para saber sai marcada `hora_real: False` (INDISPONÍVEL ≠ agora).
"""
from __future__ import annotations

import os
import time

from compliance_agent.aovivo import coleta


def _coletor(tmp_path, monkeypatch, estado: dict, fim_systemd: float):
    trava = tmp_path / "atas.lock"
    trava.write_text("")
    log = tmp_path / "atas.log"
    log.write_text("")
    monkeypatch.setattr(coleta, "catalogo", lambda: [
        {"id": "sei-noturno", "nome": "SEI noturno", "classe": "motor", "unidade": "jfn-sei-noturno"},
        {"id": "atas", "nome": "Atas de julgamento", "classe": "motor", "trava": str(trava), "log": str(log)}])
    monkeypatch.setattr(coleta, "ler_systemd", lambda units: {
        "jfn-sei-noturno.service": {"Id": "jfn-sei-noturno.service", "LoadState": "loaded",
                                    "ActiveState": estado["sei"], "ExecMainStatus": "0",
                                    "ActiveEnterTimestamp": "@%d" % (fim_systemd - 5 * 3600),
                                    "InactiveEnterTimestamp": "@%d" % fim_systemd}})
    chave = (os.stat(trava).st_dev, os.stat(trava).st_ino)
    monkeypatch.setattr(coleta, "travas_presas", lambda: {chave} if estado["atas"] else set())
    return coleta.Coletor(), trava, log


def test_terminou_leva_a_hora_do_systemd(tmp_path, monkeypatch):
    agora = time.time()
    fim = agora - 4 * 3600 - 21 * 60                    # 03:33 visto às 07:54
    estado = {"sei": "active", "atas": False}
    c, _, _ = _coletor(tmp_path, monkeypatch, estado, fim)
    c.tick(forcar=True)
    estado["sei"] = "inactive"
    c.tick(forcar=True)
    ev = [e for e in c.eventos_publicos() if e["texto"] == "SEI noturno: terminou"][-1]
    assert ev["t"] == coleta._iso(fim) and ev.get("hora_real", True) is True


def test_job_de_cron_terminou_leva_o_mtime_do_log(tmp_path, monkeypatch):
    agora = time.time()
    estado = {"sei": "inactive", "atas": True}
    c, trava, log = _coletor(tmp_path, monkeypatch, estado, agora - 9000)
    inicio = agora - 6 * 3600
    os.utime(trava, (inicio, inicio))
    c.tick(forcar=True)                                  # 1ª leitura: atas rodando
    fim = agora - 5 * 3600 - 42 * 60                     # 02:11 visto às 07:54
    with open(log, "a") as f:
        f.write("─── fim\n")
    os.utime(log, (fim, fim))
    estado["atas"] = False
    c.tick(forcar=True)
    ev = [e for e in c.eventos_publicos() if e["texto"] == "Atas de julgamento: terminou"][-1]
    assert ev["t"] == coleta._iso(fim)


def test_hora_desconhecida_e_declarada(tmp_path, monkeypatch):
    agora = time.time()
    estado = {"sei": "inactive", "atas": True}
    c, trava, log = _coletor(tmp_path, monkeypatch, estado, agora - 9000)
    os.utime(log, (agora - 10 * 86400, agora - 10 * 86400))   # log não foi escrito nesta execução
    c.tick(forcar=True)
    estado["atas"] = False
    c.tick(forcar=True)
    ev = [e for e in c.eventos_publicos() if e["texto"] == "Atas de julgamento: terminou"][-1]
    assert ev["hora_real"] is False


def test_evento_com_hora_passada_nao_some_do_stream(tmp_path, monkeypatch):
    """O id do evento segue a ordem de EMISSÃO: com a hora real no passado, o cursor do SSE não pode pulá-lo."""
    agora = time.time()
    estado = {"sei": "active", "atas": False}
    c, _, _ = _coletor(tmp_path, monkeypatch, estado, agora - 4 * 3600)
    c.tick(forcar=True)
    c._emitir("x", "dado", "evento recente")
    cursor = c.eventos_publicos()[-1]["id"]
    estado["sei"] = "inactive"
    c.tick(forcar=True)
    assert "SEI noturno: terminou" in [e["texto"] for e in c.eventos_publicos(depois_de=cursor)]


def test_contador_acumulado_diz_desde_quando():
    """'9 novos alertas' é o acumulado desde a leitura anterior — o texto diz desde quando."""
    assert coleta._desde_texto(time.time() - 3 * 3600, time.time()).startswith(" (desde ")
    assert coleta._desde_texto(time.time() - 60, time.time()) == ""
    assert coleta._desde_texto(None, time.time()) == ""
