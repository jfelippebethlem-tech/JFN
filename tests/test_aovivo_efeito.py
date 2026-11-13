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
        assert ef.get("arquivo") or ef.get("log") and ef.get("regex") or ef.get("json") and ef.get("chave") or \
            (ef.get("db") and ef.get("tabela") and ef.get("coluna")), m["id"]


# ── laudo de motores 13/11/2026 (3.1): siafe-ob, sei-integras e atas apareciam "ociosos" sem produzir ──────────
def test_catalogo_da_efeito_aos_tres_motores_que_rodavam_sem_produzir():
    por_id = {m["id"]: m for m in coleta.catalogo()}
    for mid in ("siafe-ob", "sei-integras", "atas"):
        assert por_id[mid].get("efeito"), mid


def test_efeito_por_chave_de_json(tmp_path):
    """siafe-ob: o runner grava `ultimo_efeito_iso` só com OB ingerida; falhas de MFA não o renovam."""
    f = tmp_path / "ultimo.json"
    f.write_text('{"iso": "2026-11-13T08:15:30+00:00", "ok": false, '
                 '"ultimo_ok_iso": "2026-11-11T08:02:38+00:00"}')
    cfg = {"json": str(f), "chave": ["ultimo_efeito_iso", "ultimo_ok_iso"]}
    assert coleta.medir_efeito(cfg) == datetime.fromisoformat("2026-11-11T08:02:38+00:00").timestamp()
    f.write_text('{"ultimo_efeito_iso": "2026-11-12T08:00:00+00:00", "ultimo_ok_iso": "2026-11-13T08:00:00+00:00"}')
    assert coleta.medir_efeito(cfg) == datetime.fromisoformat("2026-11-12T08:00:00+00:00").timestamp()
    assert coleta.medir_efeito({"json": str(tmp_path / "nao.json"), "chave": "x"}) is None


def test_efeito_por_log_sem_grupo_e_a_ultima_linha_que_casa(tmp_path):
    """sei-integras: o efeito é a última linha 'proc: ok' — não a mudança de um número."""
    log = tmp_path / "f.log"
    log.write_text(
        "[2026-11-10 03:30:00] rodada: 4 candidato(s)\n"
        "[2026-11-10 03:31:00]   000001/000001/2026: ok\n"
        "[2026-11-12 03:31:00]   000001/000002/2026: vazio\n")
    assert coleta.medir_efeito({"log": str(log), "regex": r"^\[[^\]]+\]\s+\S+: ok\s*$"}) == \
        datetime(2026, 11, 10, 3, 31).timestamp()


def test_efeito_por_log_desde_ignora_o_ok_que_mentia(tmp_path):
    """Antes da correção de 13/11/2026 o 'ok' da fila de íntegras valia também para captura vazia: linha anterior
    a `desde` não prova efeito, e sem linha válida o efeito é no máximo o início da cauda (🟡, nunca verde)."""
    log = tmp_path / "f.log"
    log.write_text(
        "[2026-11-06 03:30:00] rodada: 4 candidato(s)\n"
        "[2026-11-13 03:53:14]   000001/000001/2026: ok\n")
    cfg = {"log": str(log), "regex": r"^\[[^\]]+\]\s+\S+: ok\s*$", "desde": "2026-11-13 08:05:00"}
    assert coleta.medir_efeito(cfg) == datetime(2026, 11, 6, 3, 30).timestamp()
    with open(log, "a") as fh:
        fh.write("[2026-11-14 03:40:00]   000001/000003/2026: ok\n")
    assert coleta.medir_efeito(cfg) == datetime(2026, 11, 14, 3, 40).timestamp()
