# -*- coding: utf-8 -*-
"""O2.4 — deploy por evento do worker (tools/deploy_worker.py, rotina E17 deploy_vm2): fast-forward, HEAD igual ao
que o origin anuncia, md5 da árvore == md5 do HEAD, recarga só quando o HEAD muda; código local mexido é recusado."""
from __future__ import annotations

import subprocess

import pytest

from compliance_agent.fluxo import grafo
from tools import deploy_worker as dw


def _g(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def par(tmp_path):
    canon, worker = tmp_path / "canon", tmp_path / "worker"
    canon.mkdir()
    _g(canon, "init", "-q", "-b", "main")
    (canon / "tools").mkdir()
    (canon / "tools" / "a.py").write_text("x = 1\n")
    (canon / "data").mkdir()
    (canon / "data" / "fila.json").write_text("[]\n")
    _g(canon, "add", "-A")
    _g(canon, "commit", "-q", "-m", "c1")
    _g(tmp_path, "clone", "-q", str(canon), str(worker))
    return canon, worker


def _recargas():
    feitas = []
    return feitas, lambda unit, sha: feitas.append((unit, sha))


def test_sem_novidade_nao_recarrega(par):
    _, worker = par
    feitas, rec = _recargas()
    r = dw.deploy(worker, "jfn-fluxo@vm2.service", rec)
    assert not r["mudou"] and not feitas and r["md5"] == dw.md5_trabalho(worker)


def test_commit_novo_avanca_confere_md5_e_agenda_recarga(par):
    canon, worker = par
    (canon / "tools" / "a.py").write_text("x = 2\n")
    _g(canon, "commit", "-qam", "c2")
    feitas, rec = _recargas()
    r = dw.deploy(worker, "jfn-fluxo@vm2.service", rec)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=canon, capture_output=True, text=True).stdout.strip()
    assert r["mudou"] and r["head"] == head and feitas == [("jfn-fluxo@vm2.service", head)]
    assert (worker / "tools" / "a.py").read_text() == "x = 2\n"


def test_codigo_local_mexido_recusa_e_dado_local_nao(par):
    _, worker = par
    (worker / "data" / "fila.json").write_text("[1]\n")      # dado da máquina: não impede
    dw.deploy(worker, None)
    (worker / "tools" / "a.py").write_text("x = 99\n")       # código à mão: deriva, recusa
    with pytest.raises(RuntimeError, match="código local modificado"):
        dw.deploy(worker, None)


def test_md5_da_arvore_pega_arquivo_ausente(par):
    _, worker = par
    m = dw.md5_head(worker)
    assert dw.md5_trabalho(worker) == m
    (worker / "tools" / "a.py").unlink()
    assert dw.md5_trabalho(worker) != m


def test_rotina_deploy_vm2_no_grafo_real_inativa_ate_a_o90():
    g = grafo.carregar()
    r = g.rotinas["deploy_vm2"]
    assert r.estagio == "E17" and r.nos == ["vm2"] and not r.ativa and "O9.0" in r.bloqueio
    assert r.evento and r.evento.depende == ["codigo_commit"] and "codigo_commit" in g.fontes
    assert r.comando[:3] == ["{py}", "-m", "tools.deploy_worker"]
