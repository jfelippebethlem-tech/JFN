# -*- coding: utf-8 -*-
"""it-campo com N sessões SEI: fatias disjuntas na ordem de prioridade, métricas da rodada a partir do log da casa,
erro de método separado de processo restrito, e sessões em árvores diferentes não se tratam como duplicata."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import tools.itcampo_sei_paralelo as P
import tools.sei_integra_fila as F


def test_fatias_disjuntas_cobrem_tudo_e_preservam_ordem():
    fila = [{"sei": f"SEI-100000/{i:06d}/2025"} for i in range(11)]
    fatias = P.fatiar([dict(e) for e in fila], 4)
    todos = [e["sei"] for f in fatias for e in f]
    assert sorted(todos) == sorted(e["sei"] for e in fila) and len(todos) == len(set(todos))
    assert [e["sei"] for e in fatias[0]] == [fila[0]["sei"], fila[4]["sei"], fila[8]["sei"]]
    for f in fatias:          # `--fila` ordena por score desc: tem de reproduzir a ordem da fatia
        assert sorted(f, key=lambda e: -e["score"]) == f


def test_metricas_do_log(tmp_path):
    arq, cache = tmp_path / "arq", tmp_path / "cache"
    (arq / "100000_000001_2025").mkdir(parents=True)
    (arq / "100000_000001_2025" / "manifest.json").write_text(json.dumps(
        {"docs": [{"chars": 500}, {"chars": 10}, {"chars": "90"}, {"chars": 0}]}))
    (cache / "integra_100000_000001_2025").mkdir(parents=True)
    (cache / "integra_100000_000001_2025" / "manifest.json").write_text(json.dumps(
        {"total_arvore": 4, "docs": [{"ok": True}, {"ok": True}, {"ok": True}, {"ok": False}]}))
    linhas = [
        "[2026-11-14 10:00:00] ÍNTEGRA 100000/000001/2025 …",
        "[2026-11-14 10:02:00]   100000/000001/2025: ok",
        "[2026-11-14 10:02:05] ÍNTEGRA 100000/000002/2025 …",
        "[2026-11-14 10:03:05]   100000/000002/2025: SEM ÁRVORE (processo não abriu) — RESTRITO: SEI diz 'x' — via=1",
        "[2026-11-14 10:03:05]   100000/000002/2025: sem_arvore",
        "[2026-11-14 10:03:10] ÍNTEGRA 100000/000003/2025 …",
        "[2026-11-14 10:04:10]   100000/000003/2025: sem_arvore",
        "[2026-11-14 10:04:15] ÍNTEGRA 100000/000004/2025 …",
        "[2026-11-14 10:19:15]   100000/000004/2025: timeout",
    ]
    m = P.metricas_do_log(linhas, arq, cache)
    assert m["tentados"] == 4 and m["ok"] == 1 and m["restritos"] == 1
    assert m["erros_metodo"] == 2                       # timeout + sem árvore SEM causa do SEI; restrito não conta
    assert m["docs"] == 4 and m["docs_com_teor"] == 2 and m["taxa_docs_vazios"] == 0.5
    assert m["s_por_doc"] == 30.0
    assert m["procs"]["100000/000001/2025"]["docs_falhos"] == 1


def test_sessao_em_outra_arvore_nao_e_duplicata(tmp_path):
    outra = tmp_path / "s2" / "tools"
    outra.mkdir(parents=True)
    (outra / "sei_integra_fila.py").write_text("import time; time.sleep(30)\n")
    p = subprocess.Popen([sys.executable, "tools/sei_integra_fila.py"], cwd=tmp_path / "s2")
    try:
        assert F._mesmo_worker(str(p.pid)) is False
    finally:
        p.kill(); p.wait()
    assert F._mesmo_worker(str(os.getpid())) is True    # sem o script na linha de comando: na dúvida, duplicata
