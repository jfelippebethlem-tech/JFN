"""Rodízio dos detectores de padrões: mais velho primeiro, dentro do orçamento; o primeiro entra sempre (19/11/2026)."""
import json
import os

from tools import padroes_varrer as PV


def _saida(d, nome, seg, mtime):
    f = d / f"{nome}.json"
    f.write_text(json.dumps({"segundos": seg}))
    os.utime(f, (mtime, mtime))


def test_rodizio_mais_velho_primeiro_e_respeita_orcamento(tmp_path, monkeypatch):
    monkeypatch.setattr(PV, "SAIDA", tmp_path)
    _saida(tmp_path, "a", 100, 3000)
    _saida(tmp_path, "b", 2000, 1000)      # mais velho, mas longo
    _saida(tmp_path, "c", 300, 2000)
    # "d" nunca rodou → primeiro de todos
    r = PV.rodizio(2500, ["a", "b", "c", "d"])
    assert r[0] == "d" and r[1] == "b" and "c" in r and sum({"a": 100, "b": 2000, "c": 300, "d": 0}[i] for i in r) <= 2500


def test_primeiro_entra_mesmo_maior_que_o_orcamento(tmp_path, monkeypatch):
    monkeypatch.setattr(PV, "SAIDA", tmp_path)
    _saida(tmp_path, "longo", 4000, 1000)
    _saida(tmp_path, "curto", 50, 2000)
    assert PV.rodizio(2700, ["longo", "curto"]) == ["longo"]


def test_paralelo_roda_cada_id_num_processo_e_conta_falhas(monkeypatch):
    import subprocess as sp
    chamados = []

    def run(cmd, **kw):
        i = cmd[cmd.index("--id") + 1]
        chamados.append(i)
        return sp.CompletedProcess(cmd, 1 if i == "b" else 0, json.dumps({"id": i}), "quebrou" if i == "b" else "")

    monkeypatch.setattr(PV.subprocess, "run", run)
    monkeypatch.setattr(PV, "mem_disponivel_gb", lambda: 99.0)
    assert PV.em_paralelo(["a", "b", "c"], 2) == 1
    assert sorted(chamados) == ["a", "b", "c"]
