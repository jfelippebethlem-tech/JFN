# -*- coding: utf-8 -*-
"""ANEXOS REMOTES (Fase 6) — política genérica R2→B2 p/ anexos grandes (reusa fachada_remotes).

Não toca rede: o `rclone` é mockado via monkeypatch de `subprocess.run`; o uso dos buckets é injetado
via monkeypatch de `fachada_remotes._uso_bytes` (mesma técnica do teste da fachada).

Cobre:
  • objeto_anexo — caminho seguro sob 'anexos/<categoria>/...' (sem acentos/barras).
  • subir_anexo — escolhe R2→B2, devolve 'remote:bucket/objeto'; None se cheio/sem arquivo/rclone falha.
  • ler_anexo / existe_anexo — caminho EXATO; None/False p/ localização legada (sem remote:).

Rodar só este arquivo:  .venv/bin/python -m pytest tests/test_anexos_remotes.py -q
"""
from __future__ import annotations

import subprocess
import types

import pytest

from compliance_agent import anexos_remotes as ar
from compliance_agent import fachada_remotes as fr


def _mock_uso(monkeypatch, uso_por_bucket):
    monkeypatch.setattr(fr, "_uso_bytes", lambda remote, bucket: uso_por_bucket.get((remote, bucket)))


def _mock_run(monkeypatch, rc=0, stdout=b"", capturar=None):
    def fake_run(cmd, *a, **k):
        if capturar is not None:
            capturar.append(cmd)
        return types.SimpleNamespace(returncode=rc, stdout=stdout)
    monkeypatch.setattr(subprocess, "run", fake_run)


# ───────────────────────── objeto_anexo ─────────────────────────
def test_objeto_anexo_caminho_seguro():
    obj = ar.objeto_anexo("dossiês", "SEI-330003/002534/2024", ".txt")
    assert obj == "anexos/dossi_s/SEI-330003_002534_2024.txt"


def test_objeto_anexo_ext_default():
    assert ar.objeto_anexo("pesquisa", "fonte x", "pdf") == "anexos/pesquisa/fonte_x.pdf"


# ───────────────────────── subir_anexo ─────────────────────────
def test_subir_arquivo_inexistente_retorna_none(tmp_path, monkeypatch):
    assert ar.subir_anexo(tmp_path / "nao_existe.txt", "anexos/x/y.txt") is None


def test_subir_escolhe_r2_e_devolve_localizacao(tmp_path, monkeypatch):
    f = tmp_path / "d.txt"; f.write_text("conteudo do dossiê" * 100, encoding="utf-8")
    _mock_uso(monkeypatch, {("r2", "jorgefelippe"): 0, ("b2", "jfn-backup-jorge"): 0})
    cmds: list = []
    _mock_run(monkeypatch, rc=0, capturar=cmds)
    loc = ar.subir_anexo(f, "anexos/dossies/abc.txt")
    assert loc == "r2:jorgefelippe/anexos/dossies/abc.txt"
    assert cmds and cmds[0][1] == "copyto" and cmds[0][-1] == loc


def test_subir_transborda_b2_quando_r2_cheio(tmp_path, monkeypatch):
    f = tmp_path / "d.txt"; f.write_text("x" * 5000, encoding="utf-8")
    cap = int(9.5 * (1024 ** 3))
    _mock_uso(monkeypatch, {("r2", "jorgefelippe"): cap, ("b2", "jfn-backup-jorge"): 0})
    _mock_run(monkeypatch, rc=0)
    loc = ar.subir_anexo(f, "anexos/dossies/abc.txt")
    assert loc == "b2:jfn-backup-jorge/anexos/dossies/abc.txt"


def test_subir_none_se_todos_cheios(tmp_path, monkeypatch):
    f = tmp_path / "d.txt"; f.write_text("x" * 5000, encoding="utf-8")
    cap = int(9.5 * (1024 ** 3))
    _mock_uso(monkeypatch, {("r2", "jorgefelippe"): cap, ("b2", "jfn-backup-jorge"): cap})
    _mock_run(monkeypatch, rc=0)
    assert ar.subir_anexo(f, "anexos/dossies/abc.txt") is None


def test_subir_none_se_rclone_falha(tmp_path, monkeypatch):
    f = tmp_path / "d.txt"; f.write_text("x" * 5000, encoding="utf-8")
    _mock_uso(monkeypatch, {("r2", "jorgefelippe"): 0, ("b2", "jfn-backup-jorge"): 0})
    _mock_run(monkeypatch, rc=1)  # copyto falhou
    assert ar.subir_anexo(f, "anexos/dossies/abc.txt") is None


# ───────────────────────── ler_anexo / existe_anexo ─────────────────────────
def test_ler_anexo_caminho_exato(monkeypatch):
    cap: list = []
    _mock_run(monkeypatch, rc=0, stdout=b"bytes do anexo", capturar=cap)
    out = ar.ler_anexo("r2:jorgefelippe/anexos/dossies/abc.txt")
    assert out == b"bytes do anexo"
    assert cap[0][1] == "cat" and cap[0][2] == "r2:jorgefelippe/anexos/dossies/abc.txt"


def test_ler_anexo_localizacao_legada_sem_remote(monkeypatch):
    # sem 'remote:' → localização incompleta → None (nem chama rclone)
    chamou: list = []
    _mock_run(monkeypatch, rc=0, stdout=b"x", capturar=chamou)
    assert ar.ler_anexo("anexos/dossies/abc.txt") is None
    assert chamou == []


def test_existe_anexo_true_quando_lsf_lista(monkeypatch):
    _mock_run(monkeypatch, rc=0, stdout="abc.txt\n".encode())
    assert ar.existe_anexo("r2:jorgefelippe/anexos/dossies/abc.txt") is True


def test_existe_anexo_false_quando_vazio(monkeypatch):
    _mock_run(monkeypatch, rc=0, stdout=b"")
    assert ar.existe_anexo("r2:jorgefelippe/anexos/dossies/abc.txt") is False
