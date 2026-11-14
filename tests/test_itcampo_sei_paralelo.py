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


def test_relatorio_por_degrau_soma_voltas_simultaneas():
    def volta(n, slot, ini, fim, procs):
        return {"sessoes": n, "slot": slot, "inicio": ini, "ts": fim, "aprovados": 1, "procs": procs}
    ok = {"status": "ok", "segundos": 600.0, "docs": 10, "docs_com_teor": 9}
    regs = [volta(4, 1, "2026-11-14 10:00:00", "2026-11-14 10:30:00", {"1/1/1": ok, "1/1/2": ok}),
            volta(4, 2, "2026-11-14 10:00:00", "2026-11-14 10:30:00", {"1/1/3": ok}),
            volta(8, 1, "2026-11-14 10:30:00", "2026-11-14 11:00:00", {"1/1/4": ok})]
    r = P.relatorio(regs)
    assert r[4]["tentados"] == 3 and r[4]["horas"] == 0.5 and r[4]["proc_por_hora"] == 6.0
    assert r[4]["docs_por_hora"] == 60.0 and r[4]["taxa_docs_vazios"] == 0.1
    assert r[8]["voltas"] == 1


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


def test_subfatias_da_varredura_cobrem_a_metade_da_vm1_sem_sobrepor():
    """Sessão k de M varre `2(k-1)/2M`: hash ≡ 2(k-1) mod 2M ⇒ par ⇒ dentro da fatia 0/2 da VM-1, nunca na 1/2
    da VM-2, e as M sub-fatias juntas cobrem a 0/2 inteira, sem processo em duas sessões."""
    from tools.sei_sweep import na_minha_fatia
    procs = [f"SEI-{u:06d}/{n:06d}/2025" for u in (80001, 270006, 330005) for n in range(400)]
    m = 4
    for p in procs:
        donos = [k for k in range(1, m + 1) if na_minha_fatia(p, 2 * (k - 1), 2 * m)]
        assert len(donos) == (1 if na_minha_fatia(p, 0, 2) else 0)
